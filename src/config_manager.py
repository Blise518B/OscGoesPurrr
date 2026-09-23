# Config Manager - ModeManager + re-exports of the settings/ package.
#
# The individual settings managers (AppSettingsManager, SpsSourceManager,
# etc.) and their file-path constants live in the `settings/` package. They are
# re-exported here so existing callers `from config_manager import X` keep
# working.

import copy
import json
import os
import shutil
import time
from typing import Any, Dict, List, Optional

from utilities import atomic_write_json, strip_param_prefix

from settings import (
    APPDATA_DIR,
    APP_SETTINGS_FILE,
    KNOWN_DEVICES_FILE,
    MODES_FILE,
    SPS_SOURCES_FILE,
    AppSettingsManager,
    DEFAULT_APP_SETTINGS,
    KnownDevicesRegistry,
    SpsSourceManager,
)


# ---------------------------------------------------------------------------
# The shipped feel — ONE hand-tuned signal chain, dialled in live on hardware
# (2026-07: depth 0.38 + speed 0.41, punch 1.32 accent, activity wake,
# 120/200 ms smoothing, zero cut on). Every value is user-editable afterwards;
# this only decides what a fresh install (or a newly-seen motor) starts from.
# Gains stay inside the router's accepted [0, 2] range.
#
# There is exactly one feel for the whole app — it is NOT per mode. Overall
# intensity is the global `strength` multiplier, and a single chain that runs
# hot relative to the others is trimmed with its own Output stage (`gain`
# plus the toy's usable `min`/`max` band). Modes carry routing, not feel.
# ---------------------------------------------------------------------------

_DEFAULT_FEEL: Dict[str, Any] = {
    "depth_gain": 0.38, "speed_gain": 0.41, "speed_decay_ms": 350.0,
    "rise_ms": 120.0, "fall_ms": 200.0, "combine": "add",
    "punch": {"gain": 1.32, "decay_ms": 120.0},
    "wake": {"enabled": True, "mode": "activity"},
    "zerocut": {"enabled": True},
}

# The TOUCH half of a motor, which wants a different shape entirely.
# Penetration is a stroke with real depth and velocity behind it; touch is
# a hand brushing skin — shallower, jitterier, and over as soon as it
# started. So: depth carries most of it, the speed channel is calmer with a
# shorter tail, the punch accent goes away (a brush is not a thrust), and
# the envelope is quicker so a passing hand actually registers instead of
# being smoothed into nothing. Zero cut stays on; wake stays off, because a
# gate that has to be woken defeats the point of a light touch.
_TOUCH_FEEL: Dict[str, Any] = {
    "depth_gain": 0.62, "speed_gain": 0.22, "speed_decay_ms": 180.0,
    "rise_ms": 45.0, "fall_ms": 260.0, "combine": "add",
    "punch": {"gain": 0.0, "decay_ms": 120.0},
    "wake": {"enabled": False, "mode": "activity"},
    "zerocut": {"enabled": True},
    # Off until the owner decides: whether a hand at the orifice
    # should go quiet while something is inside is a taste call,
    # and the toggle lives on the Touch chain's Input stage.
    "duck": {"enabled": False, "release_ms": 400.0},
}


def _apply_feel(chain: Dict[str, Any], feel: Dict[str, Any]) -> Dict[str, Any]:
    """Overlay one feel preset onto a default chain, in place."""
    chain["depth"]["gain"] = feel["depth_gain"]
    chain["speed"]["gain"] = feel["speed_gain"]
    chain["speed"]["decay_ms"] = feel["speed_decay_ms"]
    chain["smoothing"]["rise_ms"] = feel["rise_ms"]
    chain["smoothing"]["fall_ms"] = feel["fall_ms"]
    if "combine" in feel:
        chain["combine"] = feel["combine"]
    for stage in ("wake", "punch", "texture", "zerocut", "duck"):
        if stage in feel:
            chain[stage].update(feel[stage])
    return chain


def preset_motor_mix() -> Dict[str, Any]:
    """A fresh per-motor mix block: TWO chains, one per kind of contact.

    Touch and penetration are different sensations and want different
    tuning — a hand brushing past versus a stroke with depth behind it.
    Sharing one chain meant every setting was a compromise between them,
    so a motor now ships with one of each and they are tuned apart.

    They merge max-wins: whichever contact is actually happening drives
    the toy, and the two never sum into something neither asked for."""
    # Local import to avoid a cycle.
    from motor_router import (
        MotorRouter, CHAIN_TYPE_PENETRATION, CHAIN_TYPE_TOUCH,
    )
    mix = copy.deepcopy(MotorRouter.DEFAULT_MIX_CONFIG)
    base = mix["chains"][0]

    pen_chain = _apply_feel(copy.deepcopy(base), _DEFAULT_FEEL)
    pen_chain["type"] = CHAIN_TYPE_PENETRATION
    touch_chain = _apply_feel(copy.deepcopy(base), _TOUCH_FEEL)
    touch_chain["type"] = CHAIN_TYPE_TOUCH

    mix["chains"] = [pen_chain, touch_chain]
    mix["merge"] = "max"
    return mix


# ---------------------------------------------------------------------------
# Routing keys — the per-device config that belongs to a MODE (what feeds
# what), as opposed to the rig facts that describe the hardware and are
# shared by every mode (motor_count, motor_kinds, icon_override, the linear
# envelope, per-motor speed_blend...).
#
# `osc_addresses` is a whole-device dict ({motor_idx: [param, ...]}); the
# rest are per-motor flat keys named `motor_<i>_<suffix>`. Anything not
# listed here stays in the shared wiring store — the allowlist is
# deliberate, so a new per-motor tuning key defaults to "shared" rather
# than silently becoming mode-local.
# ---------------------------------------------------------------------------

_ROUTING_DEVICE_KEYS = frozenset({"osc_addresses"})
_ROUTING_MOTOR_SUFFIXES = (
    "_zones",                # SPS / OGB zone filter
    "_touch", "_pen", "_self", "_others",   # interaction filters
    "_param_out_enabled", "_param_out_address",   # mirror-to-VRChat output
)


def is_routing_key(key: Any) -> bool:
    """True when `key` is a per-mode routing key (see above). `motor_count`
    and `motor_kinds` share the `motor_` prefix but are rig facts, so the
    suffix test — not the prefix — decides."""
    if not isinstance(key, str):
        return False
    if key in _ROUTING_DEVICE_KEYS:
        return True
    if not key.startswith("motor_"):
        return False
    return any(key.endswith(suffix) for suffix in _ROUTING_MOTOR_SUFFIXES)


class ModeManager:
    """Four routing modes over one shared rig + one shared feel.

    Replaces the old ProfileManager (global + avatar profiles). The split:

      * WIRING (`self.wiring`) — one dict per device holding the rig facts:
        motor_count, motor_kinds, icon_override, the linear actuator
        envelope, per-motor speed_blend. Describes the hardware, so it is
        shared by every mode.
      * FEEL (`self.feel`) — the per-device per-motor "mix" layer (the
        signal-chain config). ONE copy for the whole app: tune a chain once
        and every mode uses it. Overall intensity is the global `strength`
        multiplier, not a per-mode property.
      * ROUTING (per mode) — each of the four modes carries its own
        per-device routing block (`osc_addresses`, zone filters, interaction
        filters, param-out mapping — see `is_routing_key`) plus a name and
        an icon. THIS is what a mode is: the same toys wired to the avatar
        differently (every socket combined onto one motor, each socket on
        its own motor, or anything between).

    Both layers are INSTALLED into the wiring dicts — "mix" by reference,
    the routing keys as flat keys — so `get_active_profile_dict()` keeps
    returning one merged per-device dict per device: the exact shape
    motor_router.reevaluate_state() and the whole UI already consume. The
    top-level dict and every per-device dict keep a stable identity across
    mode switches (only their contents change), which the router's
    compiled-config cache relies on (it keys on id()).

    Silence and sleep are TOGGLES, not slots, and neither is persisted (a
    fresh launch is never silently muted or asleep):

      * `output_off` — the panic switch. get_master_scale() returns 0.0
        while it is on. The polling backends zero on their own dispatch
        multiply; the Buttplug path takes the scale upstream (inside each
        chain's Output stage, so a floor can sit downstream of it) and so
        hard-zeroes on `scale <= 0` at dispatch instead — silence must
        never wait for a recompute. The per-motor param-out mirror is
        deliberately NOT silenced: Off is a toy switch, and an avatar
        visual should keep reporting the contact that is still happening.
      * `sleep_active` — hands the Buttplug chain's Wake stage over to
        stroke-counter mode (see MotorRouter.SLEEP_WAKE_OVERRIDE). Read by
        the router at tick time; nothing is written to the stored chain, so
        switching it off restores the user's real wake settings exactly.

    The settings managers ride on this object exactly as they did on
    ProfileManager (self.app_settings, self.sps_sources, ...) — many
    call sites reach them through the manager.
    """

    SCHEMA_VERSION = 4
    MODE_COUNT = 4
    DEFAULT_ACTIVE_MODE = 0  # Combined on a fresh install

    #: Global output multiplier bounds + the fresh-install default. 0.85
    #: reproduces the level the shipped chain was originally dialled in at.
    STRENGTH_MIN = 0.0
    STRENGTH_MAX = 1.0
    DEFAULT_STRENGTH = 0.85

    #: Shipped slot metadata. `routing` is added per instance. A mode holds
    #: routing only — no feel, no output multiplier.
    DEFAULT_MODES: List[Dict[str, Any]] = [
        {"name": "Combined", "icon": "\U0001F517"},
        {"name": "Separate", "icon": "\U0001F500"},
        {"name": "Custom 1", "icon": "\U0001F0CF"},
        {"name": "Custom 2", "icon": "\U0001F3B2"},
    ]

    def __init__(self):
        # device_name -> merged per-device config dict (rig keys + the
        # shared "mix" and the active mode's routing keys, both installed by
        # _install_active_layers). This is THE object graph the router and
        # UI read; it is never rebuilt, only mutated in place.
        self.wiring: Dict[str, Dict[str, Any]] = {}
        # device_name -> {motor_idx_str: mix block}. Shared by every mode.
        self.feel: Dict[str, Dict[str, Any]] = {}
        self.modes: List[Dict[str, Any]] = self._fresh_modes()
        self.active_mode: int = self.DEFAULT_ACTIVE_MODE
        self._strength: float = self.DEFAULT_STRENGTH
        # Session-only toggles — deliberately not persisted.
        self.output_off: bool = False
        self.sleep_active: bool = False
        # avtr_xxx id -> last active mode index. Always recorded; only
        # APPLIED on avatar change when the "remember mode per avatar" app
        # setting is on (the facade checks it).
        self.avatar_last_mode: Dict[str, int] = {}
        # Transient: latest avatar id reported by VRChat. Not persisted.
        self.current_avatar_id: Optional[str] = None

        self.app_settings = AppSettingsManager()
        self.known_devices = KnownDevicesRegistry()
        self.sps_sources = SpsSourceManager()
        self._load_or_create_default()

    # ------------------------------------------------------------------
    # Construction helpers
    # ------------------------------------------------------------------

    @classmethod
    def _fresh_modes(cls) -> List[Dict[str, Any]]:
        return [dict(meta, routing={}) for meta in cls.DEFAULT_MODES]

    # ------------------------------------------------------------------
    # Load / save with schema migration
    # ------------------------------------------------------------------

    # True when this session loaded on in-memory defaults because the
    # (possibly healthy) file could not be READ — the first save must
    # preserve the on-disk file before overwriting it.
    _degraded_load = False

    def _load_or_create_default(self) -> None:
        """Load modes + wiring + feel from modes.json (schema v4).

        No modes.json means a fresh install: start from defaults. There is
        no migration from any older config — the app is pre-release and
        carries no legacy schema readers.

        Nothing that EXISTS is silently clobbered: transient read errors
        run this session on defaults without touching the file, and a
        corrupt or unknown-schema modes.json is preserved aside before
        defaults are persisted.
        """
        raw: Any = None
        self._degraded_load = False  # reset on every (re)load attempt
        exists = os.path.exists(MODES_FILE)
        if exists:
            try:
                with open(MODES_FILE, 'r', encoding='utf-8') as f:
                    raw = json.load(f)
                    print(f"Loaded config from {MODES_FILE}")
            except ValueError as e:
                print(f"Config load error: {e}, creating defaults")
                raw = None
            except OSError as e:
                print(f"Config read error: {e}, running on in-memory "
                      "defaults without overwriting modes.json")
                self._degraded_load = True
                self._reset_to_defaults()
                self._install_active_layers()
                return

        schema = raw.get("schema") if isinstance(raw, dict) else None
        if schema == self.SCHEMA_VERSION:
            self._load_v4(raw)
        else:
            # Unreadable, or an unsupported schema. Preserve it aside, then
            # start fresh. (An OLDER schema lands here too — there is no
            # migration path; pre-release builds don't carry one.)
            if exists:
                self._preserve_aside("unusable", move=True)
            self._reset_to_defaults()
            self.save_profiles()

        self._normalize_wiring_addresses()
        self._backfill_known_devices()
        self._install_active_layers()

    @staticmethod
    def _preserve_aside(tag: str, move: bool = False) -> None:
        """Keep a copy of the current modes.json before this session
        rewrites it, named `modes.json.<tag>-<epoch>.bak`.

        The timestamp is the point: a FIXED `.bak` name is destroyed by the
        second rescue, and the second rescue is exactly when it matters —
        alternate two builds with different schema versions and the good
        copy from flip #1 is overwritten by the already-wiped file from
        flip #2. Never overwrite a rescue copy; a stale extra file is
        cheap, the user's routing is not.

        `move` renames (the file is being replaced by defaults); otherwise
        it copies (the file is being migrated in place). Failure is
        reported, never raised — a rescue copy that can't be written must
        not stop the app from starting."""
        backup = f"{MODES_FILE}.{tag}-{int(time.time())}.bak"
        try:
            if move:
                os.replace(MODES_FILE, backup)
            else:
                shutil.copyfile(MODES_FILE, backup)
            print(f"[modes] modes.json preserved at {backup}")
        except OSError as e:
            print(f"[modes] could not preserve modes.json: {e}")

    def _reset_to_defaults(self) -> None:
        self.wiring = {}
        self.feel = {}
        self.modes = self._fresh_modes()
        self.active_mode = self.DEFAULT_ACTIVE_MODE
        self._strength = self.DEFAULT_STRENGTH

    @staticmethod
    def _clean_feel(raw: Any) -> Dict[str, Dict[str, Any]]:
        """Coerce a stored {device: {motor_idx: mix}} map into shape."""
        if not isinstance(raw, dict):
            return {}
        return {dev: {k: v for k, v in per_motor.items()
                      if isinstance(v, dict)}
                for dev, per_motor in raw.items()
                if isinstance(per_motor, dict)}

    @staticmethod
    def _clean_routing(raw: Any) -> Dict[str, Dict[str, Any]]:
        """Coerce a stored {device: {routing_key: value}} map into shape,
        dropping anything that isn't a routing key (a hand edit, or a rig
        key that leaked in)."""
        if not isinstance(raw, dict):
            return {}
        return {dev: {k: v for k, v in per_dev.items() if is_routing_key(k)}
                for dev, per_dev in raw.items()
                if isinstance(per_dev, dict)}

    def _load_v4(self, raw: Dict[str, Any], source=None) -> None:
        """Populate the stores from a v4 payload. `source` is the file it
        came from (modes.json), and is only used to name a rescue copy."""
        source = MODES_FILE if source is None else source
        # A present-but-mis-shaped section (hand edit gone wrong) is
        # salvaged by dropping it — but the next save would then persist
        # the emptied sections over the original with no copy. Preserve
        # the original first, like the corrupt-JSON path does.
        if (("wiring" in raw and not isinstance(raw.get("wiring"), dict))
                or ("feel" in raw and not isinstance(raw.get("feel"), dict))
                or ("modes" in raw
                    and not isinstance(raw.get("modes"), list))):
            backup = f"{source}.misshaped-{int(time.time())}.bak"
            try:
                shutil.copyfile(source, backup)
                print(f"[modes] mis-shaped sections in {source} — "
                      f"original preserved at {backup}")
            except OSError as e:
                print(f"[modes] could not back up mis-shaped "
                      f"{source}: {e}")
        wiring = raw.get("wiring")
        self.wiring = {}
        if isinstance(wiring, dict):
            for name, cfg in wiring.items():
                if isinstance(cfg, dict):
                    # Neither the feel nor the routing belongs in the wiring
                    # store on disk; strip both defensively in case of a
                    # hand edit.
                    self.wiring[name] = {
                        k: v for k, v in cfg.items()
                        if k != "mix" and not is_routing_key(k)
                    }
        self.feel = self._clean_feel(raw.get("feel"))
        self.modes = self._fresh_modes()
        loaded_modes = raw.get("modes")
        if isinstance(loaded_modes, list):
            for i, mode in enumerate(loaded_modes[:self.MODE_COUNT]):
                if not isinstance(mode, dict):
                    continue
                slot = self.modes[i]
                if isinstance(mode.get("name"), str) and mode["name"].strip():
                    slot["name"] = mode["name"].strip()
                if isinstance(mode.get("icon"), str) and mode["icon"]:
                    slot["icon"] = mode["icon"]
                slot["routing"] = self._clean_routing(mode.get("routing"))
        self._strength = self._coerce_strength(raw.get("strength"),
                                               self.DEFAULT_STRENGTH)
        idx = raw.get("active_mode")
        self.active_mode = idx if (isinstance(idx, int)
                                   and 0 <= idx < self.MODE_COUNT) \
            else self.DEFAULT_ACTIVE_MODE
        last = raw.get("avatar_last_mode")
        self.avatar_last_mode = {
            k: v for k, v in (last or {}).items()
            if isinstance(k, str) and isinstance(v, int)
            and 0 <= v < self.MODE_COUNT
        } if isinstance(last, dict) else {}

    def _normalize_wiring_addresses(self) -> None:
        """Validate saved OSC address lists: drop blanks and non-strings,
        and reduce a pasted `/avatar/parameters/X` to the bare name the
        router and UI both speak. This is hand-edit tolerance, not a
        migration — the UI already writes the clean form. Idempotent, and
        only re-saves when something actually changed."""
        migrated = False
        for device in self.wiring.values():
            osc_addresses = device.get("osc_addresses", {})
            if not isinstance(osc_addresses, dict):
                continue
            for key, val in list(osc_addresses.items()):
                if not isinstance(val, list):
                    continue
                new_list = [strip_param_prefix(a) for a in val
                            if isinstance(a, str) and a.strip()]
                if new_list != val:
                    osc_addresses[key] = new_list
                    migrated = True
        if migrated:
            self.save_profiles()

    def _backfill_known_devices(self) -> None:
        # Recovery path: when known_devices.json is empty (fresh install,
        # deleted cache) but the wiring already has device entries, seed
        # known_devices from those entries. Backfill only fills gaps — the
        # engine's last report wins over stale wiring snapshots.
        added = 0
        for name, cfg in self.wiring.items():
            if not isinstance(cfg, dict) or name in self.known_devices.devices:
                continue
            if self.known_devices.register(
                name,
                int(cfg.get("motor_count", 1)),
                cfg.get("motor_kinds"),
            ):
                added += 1
        if added:
            print(f"[modes] backfilled {added} toy entries into the global "
                  "known-devices registry")

    def load_profiles(self) -> None:
        """Reload from disk (legacy-named facade; kept for callers)."""
        return self._load_or_create_default()

    def save_profiles(self) -> None:
        """Persist wiring + modes to modes.json in the v4 schema — the only
        config file this app reads or writes.

        Degraded sessions (the file existed but could not be READ at load
        time) must never trade the user's real config for this session's
        in-memory defaults: before the first save we retry the read, and if
        the file is healthy again — a transient AV/backup lock is the
        classic cause — the save is SKIPPED so the boot-time reload (or the
        next launch) can recover the real data. Only a genuinely corrupt
        file is moved aside and overwritten."""
        if self._degraded_load:
            try:
                with open(MODES_FILE, 'r', encoding='utf-8') as f:
                    if isinstance(json.load(f), dict):
                        print("[modes] modes.json is readable again — "
                              "skipping save so the real config isn't "
                              "overwritten by this session's defaults")
                        return
            except ValueError:
                pass  # unreadable JSON: genuinely corrupt, back up below
            except OSError as e:
                print(f"[modes] modes.json still unreadable ({e}) — "
                      "skipping save to protect it")
                return
            backup = f"{MODES_FILE}.corrupt-{int(time.time())}.bak"
            try:
                os.replace(MODES_FILE, backup)
                print(f"[modes] corrupt modes.json backed up to {backup} "
                      "before first save")
            except OSError as e:
                if os.path.exists(MODES_FILE):
                    print(f"[modes] could not back up modes.json ({e}) — "
                          "refusing to overwrite it")
                    return
            self._degraded_load = False
        payload = {
            "schema": self.SCHEMA_VERSION,
            # The shared feel and the active mode's routing are installed
            # into the wiring dicts (by reference / as flat keys); both are
            # persisted from their own stores, so strip them here.
            "wiring": {name: {k: v for k, v in cfg.items()
                              if k != "mix" and not is_routing_key(k)}
                       for name, cfg in self.wiring.items()},
            "feel": self.feel,
            "modes": self.modes,
            "active_mode": self.active_mode,
            "strength": self._strength,
            "avatar_last_mode": self.avatar_last_mode,
        }
        try:
            atomic_write_json(MODES_FILE, payload, indent=2)
        except OSError as e:
            print(f"Config save error: {e}")

    # ------------------------------------------------------------------
    # Active mode
    # ------------------------------------------------------------------

    def _active_mode_dict(self) -> Dict[str, Any]:
        return self.modes[self.active_mode]

    def _install_active_layers(self) -> None:
        """Merge the shared feel and the active mode's routing into every
        wiring dict. Per-device dict identities stay stable — only their
        contents change — so the router's id()-keyed compile cache survives
        a mode switch."""
        self._install_feel()
        self._install_active_routing()

    def _install_feel(self) -> None:
        """Point every wiring dict's "mix" key at the shared per-device feel
        (by reference, so a chain edit through the merged view lands in the
        store)."""
        for dev, cfg in self.wiring.items():
            cfg["mix"] = self.feel.setdefault(dev, {})

    def _install_active_routing(self) -> None:
        """Copy the active mode's routing keys onto every wiring dict.

        Stale keys are cleared FIRST: a mode that has no `motor_1_zones`
        must actually leave that motor unfiltered, not inherit the previous
        mode's filter. `osc_addresses` is always installed (even when
        empty) as a stable dict object — motor_router keys its compiled-
        config cache on `id(osc_addresses)`, and a missing key would hand
        it a fresh `{}` default every tick and thrash the cache."""
        routing_store = self._active_mode_dict().setdefault("routing", {})
        for dev, cfg in self.wiring.items():
            for key in [k for k in cfg if is_routing_key(k)]:
                del cfg[key]
            per_dev = routing_store.setdefault(dev, {})
            per_dev.setdefault("osc_addresses", {})
            cfg.update(per_dev)

    def set_active_mode(self, index: int) -> bool:
        """Switch the active mode. Returns True when the index changed.
        Records the choice for the current avatar (applied on avatar change
        only when the per-avatar setting is enabled)."""
        try:
            idx = int(index)
        except (TypeError, ValueError):
            return False
        if not 0 <= idx < self.MODE_COUNT:
            return False
        changed = idx != self.active_mode
        self.active_mode = idx
        self._install_active_routing()
        if self.current_avatar_id:
            self.avatar_last_mode[self.current_avatar_id] = idx
        if changed:
            self.save_profiles()
        return changed

    def get_active_mode_index(self) -> int:
        return self.active_mode

    def get_mode(self, index: int) -> Dict[str, Any]:
        idx = max(0, min(self.MODE_COUNT - 1, int(index)))
        return self.modes[idx]

    def get_mode_infos(self) -> List[Dict[str, Any]]:
        """UI-friendly snapshot: one {index, name, icon, active} per
        slot."""
        return [
            {"index": i, "name": m.get("name", f"Mode {i}"),
             "icon": m.get("icon", ""),
             "active": i == self.active_mode}
            for i, m in enumerate(self.modes)
        ]

    def set_mode_name(self, index: int, name: str) -> None:
        name = (name or "").strip()
        if name:
            self.get_mode(index)["name"] = name
            self.save_profiles()

    def set_mode_icon(self, index: int, icon: str) -> None:
        if isinstance(icon, str) and icon:
            self.get_mode(index)["icon"] = icon
            self.save_profiles()

    # ------------------------------------------------------------------
    # Global strength + the Off / Sleep toggles
    # ------------------------------------------------------------------

    @classmethod
    def _coerce_strength(cls, value: Any, fallback: float) -> float:
        """Clamp anything user- or OSC-supplied into [0, 1]. NaN (which
        survives both float() and a naive min/max) falls back."""
        try:
            v = float(value)
        except (TypeError, ValueError):
            return fallback
        if v != v:  # NaN
            return fallback
        return max(cls.STRENGTH_MIN, min(cls.STRENGTH_MAX, v))

    def get_strength(self) -> float:
        """The global output multiplier in [0, 1] — how strong everything
        runs, independent of which routing mode is active."""
        return self._strength

    def set_strength(self, value: Any, save: bool = True) -> bool:
        """Set the global multiplier. Returns True when it changed.

        `save=False` applies the value without touching disk — for callers
        that drive this continuously (a slider drag, a VRChat radial
        puppet) and own a debounced save of their own. Serialising the
        whole profile a thousand times across one drag is a real stutter,
        not a theoretical one."""
        new = self._coerce_strength(value, self._strength)
        if new == self._strength:
            return False
        self._strength = new
        if save:
            self.save_profiles()
        return True

    def set_output_off(self, active: bool) -> bool:
        """Panic silence on/off. Returns True when it changed. Session-only
        — never persisted, so a relaunch is never silently muted."""
        active = bool(active)
        if active == self.output_off:
            return False
        self.output_off = active
        return True

    def set_sleep_active(self, active: bool) -> bool:
        """Sleep toggle on/off. Returns True when it changed. Session-only,
        same reasoning as `set_output_off`."""
        active = bool(active)
        if active == self.sleep_active:
            return False
        self.sleep_active = active
        return True

    def get_master_scale(self) -> float:
        """The dispatch multiplier: 0.0 while the Off toggle is on (panic
        silence), otherwise the global strength. Read from backend dispatch
        paths (any thread) — must stay a plain attribute read with no
        locking or I/O."""
        return 0.0 if self.output_off else self._strength

    # ------------------------------------------------------------------
    # Avatar memory
    # ------------------------------------------------------------------

    def set_current_avatar(self, avatar_id: Optional[str]) -> Optional[int]:
        """Update `current_avatar_id`. Returns this avatar's remembered mode
        index (or None). The caller decides whether to apply it — the
        per-avatar option lives in app settings."""
        self.current_avatar_id = (avatar_id or None)
        if not self.current_avatar_id:
            return None
        idx = self.avatar_last_mode.get(self.current_avatar_id)
        if isinstance(idx, int) and 0 <= idx < self.MODE_COUNT:
            return idx
        return None

    # ------------------------------------------------------------------
    # Device-config get/set (the stable accessor family the UI + router
    # use; names kept from the profile era)
    # ------------------------------------------------------------------

    def get_active_profile_dict(self) -> Dict[str, Any]:
        """The live {device: merged config} map the router/UI read & write.
        Identity-stable: always the same top-level dict object."""
        return self.wiring

    def get_active_profile_info(self) -> Dict[str, Any]:
        """Metadata about the active mode (kind kept for legacy callers)."""
        mode = self._active_mode_dict()
        return {"kind": "mode", "index": self.active_mode,
                "name": mode.get("name", ""), "icon": mode.get("icon", "")}

    def get_profile_config(self, device_name: str, key: str, default=None) -> Optional[Any]:
        """Get one config value for a device off the merged view — rig keys,
        the shared "mix", or the active mode's routing keys alike."""
        cfg = self.wiring.get(device_name)
        if cfg is not None:
            return cfg.get(key, default)
        return default

    def update_device_config(self, device_name: str, key: str, value) -> None:
        """Set one config value for a device, writing it through to whichever
        store owns it: "mix" to the shared feel, routing keys to the ACTIVE
        mode's routing block, everything else to the shared rig. The merged
        view is updated either way, so readers see the write immediately."""
        dev = self.wiring.get(device_name)
        if dev is None:
            dev = self.wiring[device_name] = {}
            dev["mix"] = self.feel.setdefault(device_name, {})
        if key == "mix":
            self.feel[device_name] = value
        elif is_routing_key(key):
            (self._active_mode_dict().setdefault("routing", {})
             .setdefault(device_name, {}))[key] = value
        dev[key] = value

    def delete_device(self, device_name: str) -> None:
        """Forget a device everywhere: rig, shared feel, every mode's
        routing."""
        self.wiring.pop(device_name, None)
        self.feel.pop(device_name, None)
        for mode in self.modes:
            routing = mode.get("routing")
            if isinstance(routing, dict):
                routing.pop(device_name, None)
        self.save_profiles()


