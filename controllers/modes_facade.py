"""Modes controller facade.

Mixin: the six fixed haptic modes — switching, metadata editing, device
seeding, per-avatar memory — plus the VRChat expression-menu integration
(OGP/Mode int in/out, OGP/Test connectivity pulse). Composed into
OscGoesPurrrApp. Relies on `self.mode_manager`, `self.ui`,
`self.log_message`, `self.force_recalculate`, `self.thread_queue`, the
backend router/engine attributes, and `self.osc_manager`."""

import threading
import time
from collections import deque
from typing import Any, Dict, List

from constants import (
    OGP_MODE_PARAMETER,
    OGP_MODE_SYNC_GUARD_S,
    OGP_TEST_LEVEL,
    OGP_TEST_MAX_HOLD_S,
)

_OGP_MODE_ADDRESS = "/avatar/parameters/" + OGP_MODE_PARAMETER

# Inbound OGP/Mode values matching one of our own sends within this window
# are VRChat echoing us back, not the user tapping the menu.
_OGP_ECHO_WINDOW_S = 1.0


class ModesFacade:

    # Set lazily; declared here so is_ogp_test_active works before any
    # toggle arrives.
    _ogp_test_active = False
    _ogp_test_seq = 0
    _ogp_mode_guard_until = 0.0
    _scale_save_scheduled = False

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
        """Make sure every known toy has a wiring entry and a per-motor mix
        block in ALL six modes.

        This is what gives a fresh install (and every newly-seen toy) the
        "remember my toys" behaviour — blank-but-present device cards to
        configure — and what makes each mode's feel presets exist before the
        user ever opens that mode. Structural facts (motor_count,
        motor_kinds) describe the toy's hardware and aren't user-
        customisable, so a fresh classification from the engine always wins
        over a stale wiring snapshot.
        """
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
            if entry is None:
                entry = {"motor_count": max(1, meta_count)}
                if meta_kinds:
                    entry["motor_kinds"] = list(meta_kinds)
                # Default per-motor OSC addresses match what
                # build_device_list_ui seeds for a freshly-discovered device.
                addrs = {}
                for i in range(max(1, meta_count)):
                    suffix = f"_{i}" if meta_count > 1 else ""
                    addrs[str(i)] = [f"{name.replace(' ', '_')}{suffix}"]
                entry["osc_addresses"] = addrs
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
            # Feel layer: seed missing per-motor mix blocks in every mode
            # with that slot's preset so a toy added later still lands on
            # Low/Medium/High/Sleep defaults instead of flat defaults.
            motor_count = int(entry.get("motor_count", 1) or 1)
            for slot, mode in enumerate(mm.modes):
                per_device = mode.setdefault("mix", {}).setdefault(name, {})
                for i in range(motor_count):
                    if str(i) not in per_device:
                        per_device[str(i)] = preset_motor_mix(slot)
                        if name not in changed:
                            changed.append(name)
        # Re-point the installed "mix" references at whatever we just seeded.
        mm._install_active_mix()
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
        rig at a different feel, switched constantly (from VR); a mute is a
        session safety toggle on one toy and must not silently lift because
        the user tapped Low → Medium.
        """
        mm = self.mode_manager
        changed = mm.set_active_mode(index)
        info = mm.get_active_profile_info()
        if changed:
            # Routing first — the new feel + master scale must reach the
            # hardware before any UI work. dispatch_direct: this runs on
            # the GUI thread already (button click or queue drain), so the
            # targets go straight to the engines without a queue hop.
            self._reset_output_caches()
            if hasattr(self, "force_recalculate"):
                self.force_recalculate(dispatch_direct=True)
            # Chain widgets seed their editors from the active feel layer
            # at construction time only — a mode switch must rebuild the
            # cards. Deferred one event-loop turn: the rebuild is the
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
        for attr in ("steamvr_router", "bhaptics_router", "pishock_router",
                     "coyote_router", "owo_router", "handy_router"):
            router = getattr(self, attr, None)
            reset = getattr(router, "reset_dispatch_cache", None)
            if reset is not None:
                try:
                    reset()
                except Exception:
                    pass

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

    def set_mode_master_scale(self, index: int, scale: float) -> None:
        mm = self.mode_manager
        # In-memory + live output immediately; the disk write is coalesced
        # (a held spinbox arrow fires many changes per second, and each
        # save is a full fsync'd profiles.json rewrite on the GUI thread).
        mm.set_mode_master_scale(index, scale, save=False)
        self._schedule_scale_save()
        if int(index) == mm.get_active_mode_index():
            self._reset_output_caches()
            if hasattr(self, "force_recalculate"):
                self.force_recalculate()
        self._refresh_mode_buttons_ui()

    def _schedule_scale_save(self) -> None:
        """Coalesced save for rapid master-scale edits: one disk write
        ~600 ms after the last change. Falls back to an immediate save
        when no UI timer exists (headless tests, early startup)."""
        ui = getattr(self, "ui", None)
        schedule = getattr(ui, "schedule_callback", None)
        if schedule is None:
            self.mode_manager.save_profiles()
            return
        if self._scale_save_scheduled:
            return
        self._scale_save_scheduled = True

        def _flush():
            self._scale_save_scheduled = False
            self.mode_manager.save_profiles()

        schedule(600, _flush)

    def get_master_scale(self) -> float:
        """The active mode's output multiplier (0..1). Called from backend
        dispatch paths on their own threads — plain dict read, no I/O."""
        return self.mode_manager.get_master_scale()

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
            self.log_message("OGP/Test held — running connectivity pulse "
                             "(toys, SteamVR, bHaptics)")
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
            # right now instead of waiting for a router change. The polling
            # backends (SteamVR/bHaptics) pick up their test floor on the
            # next ~60 Hz tick by themselves.
            if engine is not None and engine.is_connected:
                try:
                    counts = engine.get_motor_count_map() or {}
                except Exception:
                    counts = {}
                for device_name, motor_count in counts.items():
                    if device_name in getattr(self, "_muted_devices", set()):
                        continue
                    for motor_idx in range(int(motor_count or 1)):
                        engine.update_target(device_name, motor_idx,
                                             OGP_TEST_LEVEL)
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
                             "VRChat — check the menu toggle values (0-5)")
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
            self._send_ogp_mode_out()

        # bHaptics' connected bool needs re-asserting whether or not the
        # mode changed.
        try:
            self._bhaptics_send_connected_bool()
        except Exception:
            pass

    def get_current_avatar_id(self) -> str:
        return self.mode_manager.current_avatar_id or ""
