"""Modes controller facade.

Mixin: the four routing modes — switching, metadata editing, device
seeding, per-avatar memory — the global strength multiplier and the
Off / Sleep toggles, plus the VRChat expression-menu integration
(OGP/Mode int, OGP/Strength float, OGP/Off + OGP/Sleep bools, all
two-way; OGP/Test connectivity pulse). Composed into OscGoesPurrrApp.
Relies on `self.mode_manager`, `self.ui`, `self.log_message`,
`self.force_recalculate`, `self.thread_queue`, the backend router/engine
attributes, and `self.osc_manager`."""

import threading
import time
from collections import deque
from typing import Any, Dict, List

from constants import (
    OGP_MODE_PARAMETER,
    OGP_MODE_SYNC_GUARD_S,
    OGP_OFF_PARAMETER,
    OGP_SLEEP_PARAMETER,
    OGP_STRENGTH_EPSILON,
    OGP_STRENGTH_PARAMETER,
    OGP_TEST_LEVEL,
    OGP_TEST_MAX_HOLD_S,
)

_OGP_MODE_ADDRESS = "/avatar/parameters/" + OGP_MODE_PARAMETER
_OGP_STRENGTH_ADDRESS = "/avatar/parameters/" + OGP_STRENGTH_PARAMETER

# Inbound OGP/Mode values matching one of our own sends within this window
# are VRChat echoing us back, not the user tapping the menu.
_OGP_ECHO_WINDOW_S = 1.0

# Quiet period after the last strength change before it's written to disk.
# Long enough to swallow a slider drag or a menu-puppet sweep, short
# enough that a normal quit lands after it.
_STRENGTH_SAVE_DEBOUNCE_MS = 400


def _split_touch_from_penetration(mix: Any) -> bool:
    """Give a single-chain motor its second chain: Touch beside the one
    it already has. Returns True when something changed.

    Touch and penetration want completely different tuning, so a motor
    now carries one chain for each. A motor configured before that split
    has a single chain holding whatever compromise the user landed on
    between the two — so that chain is KEPT exactly as tuned and becomes
    the Penetration chain, and a fresh Touch chain is added beside it
    from the touch preset. Nothing already dialled in is touched; only
    the half that never had its own settings is new.

    Runs from the device seeder rather than as a version-gated migration:
    it is idempotent (a motor that already has a typed chain is left
    alone), so it costs one dict lookup per motor per launch and needs no
    schema number to hang off.
    """
    from config_manager import _TOUCH_FEEL, _apply_feel  # local: cycles
    from motor_router import (
        CHAIN_TYPE_CUSTOM, CHAIN_TYPE_PENETRATION, CHAIN_TYPE_TOUCH,
    )

    if not isinstance(mix, dict):
        return False
    chains = mix.get("chains")
    if not isinstance(chains, list) or not chains:
        return False
    # Already split (or deliberately arranged some other way) — leave it.
    if any(isinstance(c, dict) and c.get("type") for c in chains):
        return False
    if len(chains) != 1:
        # A hand-built multi-chain motor predates types but is clearly
        # intentional. Label it rather than reshaping it.
        for c in chains:
            if isinstance(c, dict):
                c["type"] = CHAIN_TYPE_CUSTOM
        return True

    import copy as _copy
    existing = chains[0]
    if not isinstance(existing, dict):
        return False
    existing["type"] = CHAIN_TYPE_PENETRATION
    touch = _apply_feel(_copy.deepcopy(existing), _TOUCH_FEEL)
    touch["type"] = CHAIN_TYPE_TOUCH
    # The Output stage is per-toy calibration, not feel — the new chain
    # drives the same motor, so it inherits the same band and gain.
    chains.append(touch)
    mix["merge"] = "max"
    return True


class ModesFacade:

    # Set lazily; declared here so is_ogp_test_active works before any
    # toggle arrives.
    _ogp_test_active = False
    _ogp_test_seq = 0
    _ogp_mode_guard_until = 0.0
    _strength_save_seq = 0

    # ------------------------------------------------------------------
    # UI refresh plumbing
    # ------------------------------------------------------------------

    def _refresh_mode_buttons_ui(self) -> None:
        """Tell the UI to repaint the mode buttons (sidebar grid + dashboard
        rows). No-op when self.ui is None or doesn't expose the method
        (early startup, headless tests)."""
        ui = getattr(self, "ui", None)
        if ui is None:
            return
        refresh = getattr(ui, "_refresh_mode_buttons", None)
        if refresh is not None:
            refresh()

    # ------------------------------------------------------------------
    # Seeding — every known toy gets a wiring entry + a feel entry in
    # every mode
    # ------------------------------------------------------------------

    def _seed_known_devices(self) -> None:
        """Make sure every known toy has a rig entry, a per-motor feel block,
        and a routing block in ALL four modes.

        This is what gives a fresh install (and every newly-seen toy) the
        "remember my toys" behaviour — blank-but-present device cards to
        configure — and what makes a toy routable in every mode before the
        user ever opens that mode. Structural facts (motor_count,
        motor_kinds) describe the toy's hardware and aren't user-
        customisable, so a fresh classification from the engine always wins
        over a stale wiring snapshot.
        """
        import copy
        from config_manager import preset_motor_mix  # local: avoid cycles
        mm = self.mode_manager
        known = mm.known_devices.all()
        if not known:
            return
        changed = []
        for name, meta in known.items():
            meta_count = int(meta.get("motor_count", 1))
            meta_kinds = meta.get("motor_kinds")
            entry = mm.wiring.get(name)
            is_new = entry is None
            if is_new:
                entry = {"motor_count": max(1, meta_count)}
                if meta_kinds:
                    entry["motor_kinds"] = list(meta_kinds)
                mm.wiring[name] = entry
                changed.append(name)
            else:
                if meta_count > 0 and entry.get("motor_count") != meta_count:
                    entry["motor_count"] = meta_count
                    changed.append(name)
                if meta_kinds and entry.get("motor_kinds") != list(meta_kinds):
                    entry["motor_kinds"] = list(meta_kinds)
                    if name not in changed:
                        changed.append(name)
            motor_count = int(entry.get("motor_count", 1) or 1)
            # Routing layer: a freshly-seen toy gets the same default
            # per-motor OSC addresses build_device_list_ui seeds, in EVERY
            # mode — a new toy should be routable whichever mode you switch
            # to, not only the one that happened to be active. An existing
            # toy is left alone: an empty address block is a legitimate
            # choice (zone routing instead), not a gap to backfill.
            if is_new:
                addrs = {}
                for i in range(motor_count):
                    suffix = f"_{i}" if motor_count > 1 else ""
                    addrs[str(i)] = [f"{name.replace(' ', '_')}{suffix}"]
                for mode in mm.modes:
                    per_dev = mode.setdefault("routing", {}).setdefault(name, {})
                    per_dev.setdefault("osc_addresses", copy.deepcopy(addrs))
            # Feel layer: ONE shared per-motor mix block, seeded from the
            # shipped chain so a toy added later starts on the tuned preset
            # instead of flat defaults.
            per_device_feel = mm.feel.setdefault(name, {})
            for i in range(motor_count):
                if str(i) not in per_device_feel:
                    per_device_feel[str(i)] = preset_motor_mix()
                    if name not in changed:
                        changed.append(name)
                elif _split_touch_from_penetration(per_device_feel[str(i)]):
                    if name not in changed:
                        changed.append(name)
        # Re-point the installed feel references / routing keys at whatever
        # we just seeded.
        mm._install_active_layers()
        if changed:
            mm.save_profiles()
            print(f"[modes] seeded/refreshed device entries: {changed}")

    # ------------------------------------------------------------------
    # Mode switching
    # ------------------------------------------------------------------

    def switch_mode(self, index: int, source: str = "ui") -> None:
        """Switch the active mode and re-apply everything that depends on it.

        `source` is "ui" | "osc" | "avatar" — OSC-originated switches skip
        the echo back to VRChat (the menu already holds the value).

        Deliberate: per-toy mutes SURVIVE a mode switch. Modes are the same
        rig wired to the avatar differently, switched constantly (from VR);
        a mute is a session safety toggle on one toy and must not silently
        lift because the user tapped Combined → Separate.
        """
        mm = self.mode_manager
        changed = mm.set_active_mode(index)
        info = mm.get_active_profile_info()
        if changed:
            # Routing first — the new wiring must reach the hardware before
            # any UI work. dispatch_direct: this runs on the GUI thread
            # already (button click or queue drain), so the targets go
            # straight to the engines without a queue hop.
            self._reset_output_caches()
            if hasattr(self, "force_recalculate"):
                self.force_recalculate(dispatch_direct=True)
            # Chain widgets seed their editors from the merged device view
            # at construction time only — a mode switch changes every
            # motor's Input stage, so the cards must be rebuilt. Deferred
            # one event-loop turn: the rebuild is the
            # heaviest UI operation in the app and VR-menu switches happen
            # mid-contact, so routing ticks get to interleave first.
            ui = getattr(self, "ui", None)
            if ui is not None:
                def _rebuild(u=ui):
                    u.clear_device_caches()
                    u.build_stored_devices_ui()
                schedule = getattr(ui, "schedule_callback", None)
                if schedule is not None:
                    schedule(0, _rebuild)
                else:
                    _rebuild()
            self.log_message(
                f"Mode → {info.get('icon', '')} {info.get('name', '')}".strip()
            )
        self._refresh_mode_buttons_ui()
        if source != "osc":
            self._send_ogp_mode_out()

    def _reset_output_caches(self) -> None:
        """Clear every router's change-debounce cache so the first tick
        after a mode/master-scale change re-dispatches all outputs (a scale
        change alters what reaches hardware without changing router inputs —
        without this, devices hold the old level until the next contact
        change)."""
        if hasattr(self, "motor_router"):
            self.motor_router.reset_outputs()

    # ------------------------------------------------------------------
    # Mode metadata (editor surface)
    # ------------------------------------------------------------------

    def get_active_profile_dict(self) -> Dict[str, Any]:
        """Facade: the live {device: merged wiring + active-mode feel} map
        the router and UI read (name kept from the profile era)."""
        return self.mode_manager.get_active_profile_dict()

    def get_modes_info(self) -> List[Dict[str, Any]]:
        return self.mode_manager.get_mode_infos()

    def get_active_mode_info(self) -> Dict[str, Any]:
        return self.mode_manager.get_active_profile_info()

    def rename_mode(self, index: int, name: str) -> None:
        self.mode_manager.set_mode_name(index, name)
        self._refresh_mode_buttons_ui()

    def set_mode_icon(self, index: int, icon: str) -> None:
        self.mode_manager.set_mode_icon(index, icon)
        self._refresh_mode_buttons_ui()

    def get_master_scale(self) -> float:
        """The dispatch multiplier: 0.0 while the Off toggle is on, else the
        global strength. Called from backend dispatch paths on their own
        threads — plain attribute read, no I/O."""
        return self.mode_manager.get_master_scale()

    # ------------------------------------------------------------------
    # Global strength + the Off / Sleep toggles
    # ------------------------------------------------------------------

    def get_strength(self) -> float:
        """The global output multiplier in [0, 1] (UI facade)."""
        return self.mode_manager.get_strength()

    def set_strength(self, value: float, source: str = "ui") -> None:
        """Set the global output multiplier. `source` is "ui" | "osc" —
        OSC-originated changes skip the echo back to VRChat.

        A strength change alters what reaches the hardware without changing
        any router input, so the debounce caches must be cleared or every
        device would hold its old level until the next contact change.

        Applied live, saved lazily: both drivers of this (a slider drag, a
        VRChat radial puppet) produce a continuous stream of values, and
        the value must reach the toy on every one of them — but the disk
        only needs the last."""
        if not self.mode_manager.set_strength(value, save=False):
            return
        self._apply_output_change()
        self._schedule_strength_save()
        if source != "osc":
            self._send_ogp_strength_out()
        self._refresh_strength_ui()

    def _schedule_strength_save(self) -> None:
        """Persist the strength once the stream of changes settles. Falls
        back to an immediate save when there's no UI to schedule on
        (headless tests)."""
        self._strength_save_seq += 1
        seq = self._strength_save_seq
        ui = getattr(self, "ui", None)
        schedule = getattr(ui, "schedule_callback", None)
        if schedule is None:
            self.mode_manager.save_profiles()
            return

        def _save():
            # A newer change superseded this one — it will save instead.
            if seq == self._strength_save_seq:
                self.mode_manager.save_profiles()

        schedule(_STRENGTH_SAVE_DEBOUNCE_MS, _save)

    def is_output_off(self) -> bool:
        return bool(self.mode_manager.output_off)

    def set_output_off(self, active: bool, source: str = "ui") -> None:
        """Panic silence on/off. Same cache-clearing rule as strength."""
        if not self.mode_manager.set_output_off(active):
            return
        self._apply_output_change()
        self.log_message("Output OFF — everything silenced"
                         if self.mode_manager.output_off
                         else "Output back on")
        if source != "osc":
            self._send_ogp_bool_out(OGP_OFF_PARAMETER,
                                    self.mode_manager.output_off)
        self._refresh_strength_ui()

    def is_sleep_active(self) -> bool:
        """Read by motor_router on its own thread every tick — must stay a
        plain attribute read."""
        return bool(self.mode_manager.sleep_active)

    def set_sleep_active(self, active: bool, source: str = "ui") -> None:
        """Sleep toggle on/off. Hands the chain's Wake stage over to
        stroke-counter mode; nothing is written to the stored chain."""
        if not self.mode_manager.set_sleep_active(active):
            return
        self._apply_output_change()
        self.log_message("Sleep ON — takes three strokes to wake"
                         if self.mode_manager.sleep_active
                         else "Sleep OFF — normal wake restored")
        if source != "osc":
            self._send_ogp_bool_out(OGP_SLEEP_PARAMETER,
                                    self.mode_manager.sleep_active)
        self._refresh_strength_ui()

    def _apply_output_change(self) -> None:
        """Push a change that alters output without changing router inputs
        all the way to the hardware now."""
        self._reset_output_caches()
        if hasattr(self, "force_recalculate"):
            self.force_recalculate(dispatch_direct=True)

    def _refresh_strength_ui(self) -> None:
        ui = getattr(self, "ui", None)
        if ui is None:
            return
        refresh = getattr(ui, "refresh_output_controls", None)
        if refresh is not None:
            refresh()

    # ------------------------------------------------------------------
    # OGP/Test — the VR-menu connectivity pulse
    # ------------------------------------------------------------------

    def is_ogp_test_active(self) -> bool:
        return bool(self._ogp_test_active)

    def get_ogp_test_level(self) -> float:
        """Floor level for vibration-type backends while the menu's Test
        button is held; 0.0 otherwise. E-stim/EMS backends never read this."""
        return OGP_TEST_LEVEL if self._ogp_test_active else 0.0

    def set_ogp_test_active(self, active: bool) -> None:
        active = bool(active)
        if active == self._ogp_test_active:
            return
        self._ogp_test_active = active
        self._ogp_test_seq += 1
        engine = getattr(self, "haptic_engine", None)
        if active:
            self.log_message("OGP/Test held — running connectivity pulse")
            # Watchdog: the release edge is one OSC bool; if VRChat dies
            # mid-hold it never arrives and every vibration backend would
            # latch at the test level forever. Auto-release after the max
            # hold (the seq token keeps a release+re-press alive).
            ui = getattr(self, "ui", None)
            schedule = getattr(ui, "schedule_callback", None)
            if schedule is not None:
                seq = self._ogp_test_seq

                def _watchdog():
                    if self._ogp_test_active and self._ogp_test_seq == seq:
                        self.log_message(
                            "OGP/Test auto-released (max hold reached / "
                            "release edge lost)")
                        self.set_ogp_test_active(False)

                schedule(int(OGP_TEST_MAX_HOLD_S * 1000), _watchdog)
            # Toys: push the test level to every connected, un-muted motor
            # right now instead of waiting for a router change.
            #
            # Remapped per motor into its calibrated output band, exactly
            # as the per-tick floor in intiface_facade is — a motor whose
            # band starts above OGP_TEST_LEVEL would otherwise sit in its
            # dead zone and read as a dead toy. Doing it on both paths also
            # keeps this immediate push from being overwritten by a
            # different value on the very next recalc.
            router = getattr(self, "motor_router", None)
            if engine is not None and engine.is_connected:
                try:
                    counts = engine.get_motor_count_map() or {}
                except Exception:
                    counts = {}
                for device_name, motor_count in counts.items():
                    if device_name in getattr(self, "_muted_devices", set()):
                        continue
                    for motor_idx in range(int(motor_count or 1)):
                        level = OGP_TEST_LEVEL
                        if router is not None:
                            try:
                                level = router.map_into_output_band(
                                    device_name, motor_idx, OGP_TEST_LEVEL)
                            except Exception:
                                level = OGP_TEST_LEVEL
                        engine.update_target(device_name, motor_idx, level)
        else:
            self.log_message("OGP/Test released — restoring routed output")
        # Both edges: clear debounce caches and recompute so routed values
        # (or zeros) immediately replace / merge with the test floor.
        self._reset_output_caches()
        if hasattr(self, "force_recalculate"):
            self.force_recalculate(dispatch_direct=True)

    # ------------------------------------------------------------------
    # VRChat OGP/Mode sync (in + out)
    # ------------------------------------------------------------------

    def _send_ogp_mode_out(self) -> None:
        """Push the active mode index to VRChat so the expression-menu
        highlight matches the app. Fire-and-forget; typed int so a float
        never lands on the avatar's Int parameter."""
        osc = getattr(self, "osc_manager", None)
        if osc is None or not getattr(osc, "is_connected", False):
            return
        idx = int(self.mode_manager.get_active_mode_index())
        try:
            osc.send_parameter(_OGP_MODE_ADDRESS, idx,
                               ignore_rate_limit=True, force_type="i")
        except Exception:
            return
        # Remember what we sent: VRChat echoes every parameter change back
        # on its OSC output, and a stale echo arriving after a second quick
        # switch must not yank the mode backwards (see _on_ogp_mode_osc).
        if not hasattr(self, "_ogp_mode_recent_sends"):
            self._ogp_mode_recent_sends = deque(maxlen=8)
        self._ogp_mode_recent_sends.append((idx, time.monotonic()))

    def _send_ogp_strength_out(self) -> None:
        """Push the global strength to VRChat so a radial menu puppet keeps
        showing the real value. Fire-and-forget, typed float."""
        osc = getattr(self, "osc_manager", None)
        if osc is None or not getattr(osc, "is_connected", False):
            return
        value = float(self.mode_manager.get_strength())
        try:
            osc.send_parameter(_OGP_STRENGTH_ADDRESS, value,
                               ignore_rate_limit=True, force_type="f")
        except Exception:
            return
        if not hasattr(self, "_ogp_strength_recent_sends"):
            self._ogp_strength_recent_sends = deque(maxlen=8)
        self._ogp_strength_recent_sends.append((value, time.monotonic()))

    def _send_ogp_bool_out(self, parameter: str, value: bool) -> None:
        """Push one of the OGP toggles back to VRChat so the menu checkbox
        matches the app."""
        osc = getattr(self, "osc_manager", None)
        if osc is None or not getattr(osc, "is_connected", False):
            return
        try:
            osc.send_parameter("/avatar/parameters/" + parameter, bool(value),
                               ignore_rate_limit=True, force_type="T")
        except Exception:
            return

    def _send_ogp_state_out(self) -> None:
        """Re-assert every OGP control parameter at once (OSC (re)connect,
        avatar swap). The app is the source of truth for all of them."""
        self._send_ogp_mode_out()
        self._send_ogp_strength_out()
        self._send_ogp_bool_out(OGP_OFF_PARAMETER,
                                self.mode_manager.output_off)
        self._send_ogp_bool_out(OGP_SLEEP_PARAMETER,
                                self.mode_manager.sleep_active)

    def _on_ogp_strength_osc(self, value: Any) -> None:
        """Handle an incoming OGP/Strength float from the expression menu
        (runs on the GUI thread via the queue drain)."""
        try:
            level = float(value)
        except (TypeError, ValueError):
            return
        if level != level:  # NaN
            return
        level = max(0.0, min(1.0, level))
        now = time.monotonic()
        if now < self._ogp_mode_guard_until:
            # Avatar just loaded: VRChat is replaying saved parameter
            # values, not the user turning the dial. Re-assert instead.
            self._send_ogp_strength_out()
            return
        current = self.mode_manager.get_strength()
        if abs(level - current) < OGP_STRENGTH_EPSILON:
            return
        # Our own echo coming back — see _on_ogp_mode_osc for why a stale
        # one must not drag the value backwards.
        recent = getattr(self, "_ogp_strength_recent_sends", ())
        if any(abs(level - s_val) < OGP_STRENGTH_EPSILON
               and now - s_t < _OGP_ECHO_WINDOW_S for s_val, s_t in recent):
            return
        self.set_strength(level, source="osc")

    def _on_ogp_toggle_osc(self, which: str, value: Any) -> None:
        """Handle an incoming OGP/Off or OGP/Sleep bool from the menu."""
        active = bool(value)
        if time.monotonic() < self._ogp_mode_guard_until:
            # Avatar replay — re-assert what the app actually holds.
            if which == "off":
                self._send_ogp_bool_out(OGP_OFF_PARAMETER,
                                        self.mode_manager.output_off)
            else:
                self._send_ogp_bool_out(OGP_SLEEP_PARAMETER,
                                        self.mode_manager.sleep_active)
            return
        if which == "off":
            self.set_output_off(active, source="osc")
        else:
            self.set_sleep_active(active, source="osc")

    def _on_ogp_mode_osc(self, value: Any) -> None:
        """Handle an incoming OGP/Mode int from the expression menu (runs on
        the GUI thread via the queue drain)."""
        try:
            idx = int(float(value))
        except (TypeError, ValueError):
            return
        now = time.monotonic()
        if now < self._ogp_mode_guard_until:
            # Avatar just loaded: VRChat is replaying saved/reset parameter
            # values, not the user tapping the menu. The app is the source
            # of truth — re-assert instead of following.
            self._send_ogp_mode_out()
            return
        if not 0 <= idx < self.mode_manager.MODE_COUNT:
            # A mis-built menu toggle (Value = 6, say) would otherwise leave
            # VRChat highlighting a phantom selection while the app silently
            # keeps its mode — correct the menu instead.
            self.log_message(f"Ignoring out-of-range OGP/Mode {idx} from "
                             "VRChat — check the menu toggle values (0-3)")
            self._send_ogp_mode_out()
            return
        if idx == self.mode_manager.get_active_mode_index():
            return
        # VRChat echoes our own sends back; after two quick app-side
        # switches the FIRST echo arrives when the app is already on the
        # second mode and would yank it backwards. Anything we ourselves
        # sent recently is an echo, not user intent.
        recent = getattr(self, "_ogp_mode_recent_sends", ())
        if any(idx == s_idx and now - s_t < _OGP_ECHO_WINDOW_S
               for s_idx, s_t in recent):
            return
        self.switch_mode(idx, source="osc")

    # ------------------------------------------------------------------
    # Avatar change handling
    # ------------------------------------------------------------------

    def _schedule_avatar_id_probe(self):
        """Spawn a short background poll that asks VRChat's OSCQuery server
        for the current avatar id. Posts an avatar_change queue message on
        success. Safe to call repeatedly — it's just a few HTTP GETs."""
        def _probe():
            # OSCQuery mDNS discovery + JSON build can lag a couple of
            # seconds after OSC starts. Retry briefly so the user doesn't
            # see "not detected" on first launch.
            for _attempt in range(6):
                if not self.osc_manager or not self.osc_manager.is_connected:
                    return
                avatar_id = self.osc_manager.query_avatar_id()
                if avatar_id:
                    self.thread_queue.put(("avatar_change", avatar_id))
                    return
                time.sleep(1.0)
        threading.Thread(target=_probe, daemon=True).start()

    def _on_avatar_change(self, avatar_id: str):
        """Handle a fresh /avatar/change message from VRChat.

        Remembers the avatar id, optionally restores that avatar's last
        mode (only when the "remember mode per avatar" setting is on), and
        re-asserts the outgoing avatar parameters — avatar swaps reset every
        parameter on the VRChat side.
        """
        avatar_id = (avatar_id or "").strip()
        remembered = self.mode_manager.set_current_avatar(avatar_id)
        # VRChat replays parameter values right after a swap; don't let a
        # stale saved OGP/Mode drag the app around (see _on_ogp_mode_osc).
        self._ogp_mode_guard_until = (time.monotonic()
                                      + OGP_MODE_SYNC_GUARD_S)

        per_avatar = bool(self.get_app_setting("avatar_modes_enabled", False)) \
            if hasattr(self, "get_app_setting") else False
        if (per_avatar and remembered is not None
                and remembered != self.mode_manager.get_active_mode_index()):
            info = self.mode_manager.get_mode(remembered)
            self.log_message(
                f"Avatar changed → restoring its last mode "
                f"'{info.get('name', remembered)}'"
            )
            self.switch_mode(remembered, source="avatar")
        else:
            self.log_message(f"Avatar changed (id={avatar_id or 'unknown'})")
        # Every OGP control parameter was reset by the swap — re-assert the
        # whole set, not just the mode (switch_mode above only echoes that
        # one).
        self._send_ogp_state_out()

    def get_current_avatar_id(self) -> str:
        return self.mode_manager.current_avatar_id or ""
