# Config Manager - ModeManager + re-exports of the settings/ package.
#
# The individual settings managers (AppSettingsManager, SteamVRSettingsManager,
# etc.) and their file-path constants live in the `settings/` package. They are
# re-exported here so existing callers `from config_manager import X` keep
# working.

import copy
import json
import math
import os
import shutil
import time
from typing import Any, Dict, List, Optional

from utilities import atomic_write_json, strip_param_prefix

from settings import (
    APPDATA_DIR,
    APP_SETTINGS_FILE,
    BHAPTICS_SETTINGS_FILE,
    COYOTE_SETTINGS_FILE,
    HANDY_SETTINGS_FILE,
    KNOWN_DEVICES_FILE,
    OWO_SETTINGS_FILE,
    PISHOCK_SETTINGS_FILE,
    PROFILE_FILE,
    SPS_SOURCES_FILE,
    STEAMVR_SETTINGS_FILE,
    AppSettingsManager,
    BHapticsSettingsManager,
    CoyoteSettingsManager,
    DEFAULT_APP_SETTINGS,
    HandySettingsManager,
    KnownDevicesRegistry,
    OwoSettingsManager,
    PiShockSettingsManager,
    SpsSourceManager,
    SteamVRSettingsManager,
)


# ---------------------------------------------------------------------------
# Mode presets — the "feel" each slot ships with. Every value is user-editable
# afterwards; these only decide what a fresh install (or a newly-seen motor)
# starts from. Slot meanings: 0 Off, 1 Low, 2 Medium, 3 High, 4 Sleep,
# 5 Custom. Gains stay inside the router's accepted [0, 2] range.
# ---------------------------------------------------------------------------

_SLOT_FEEL: Dict[int, Dict[str, Any]] = {
    # Low — teasing: subdued depth, barely speed-reactive, slow envelopes,
    # and a slow grain wobble so a held contact keeps feeling alive.
    1: {"depth_gain": 0.55, "speed_gain": 0.35, "speed_decay_ms": 500.0,
        "rise_ms": 350.0, "fall_ms": 600.0,
        "texture": {"enabled": True, "amount": 0.3, "rate_hz": 1.5,
                    "follow_speed": False}},
    # Medium — between Low and High: most of the depth, moderate speed.
    2: {"depth_gain": 0.85, "speed_gain": 0.70, "speed_decay_ms": 350.0,
        "rise_ms": 120.0, "fall_ms": 200.0},
    # High — reacts hard to speed: full depth, speed dominates, snappy,
    # with a punch accent so sharp thrusts land as crisp hits.
    3: {"depth_gain": 1.0, "speed_gain": 1.6, "speed_decay_ms": 220.0,
        "rise_ms": 40.0, "fall_ms": 80.0,
        "punch": {"gain": 0.9, "decay_ms": 140.0}},
    # Sleep — hard to wake: the Wake stage in stroke-counter mode keeps
    # everything silent until three full strokes land inside six seconds
    # (an accidental brush can't trigger it), stays awake while strokes
    # keep coming, and everything ramps gently.
    4: {"depth_gain": 0.70, "speed_gain": 0.40, "speed_decay_ms": 500.0,
        "rise_ms": 600.0, "fall_ms": 900.0,
        "wake": {"enabled": True, "mode": "strokes", "thrusts": 3,
                 "window_s": 6.0, "disarm_after_s": 45.0}},
}


def preset_motor_mix(slot: int) -> Dict[str, Any]:
    """A fresh per-motor mix block ({"chains": [...], "merge": ...})
    expressing the given mode slot's default feel. Slots without an entry in
    _SLOT_FEEL (Off, Custom) get the router's plain defaults."""
    from motor_router import MotorRouter  # local import to avoid cycle
    mix = copy.deepcopy(MotorRouter.DEFAULT_MIX_CONFIG)
    feel = _SLOT_FEEL.get(int(slot))
    if not feel:
        return mix
    chain = mix["chains"][0]
    chain["depth"]["gain"] = feel["depth_gain"]
    chain["speed"]["gain"] = feel["speed_gain"]
    chain["speed"]["decay_ms"] = feel["speed_decay_ms"]
    chain["smoothing"]["rise_ms"] = feel["rise_ms"]
    chain["smoothing"]["fall_ms"] = feel["fall_ms"]
    for stage in ("wake", "punch", "texture"):
        if stage in feel:
            chain[stage].update(feel[stage])
    return mix


class ModeManager:
    """Six fixed haptic modes over one shared device-wiring store.

    Replaces the old ProfileManager (global + avatar profiles). The split:

      * WIRING (`self.wiring`) — one dict per device holding everything that
        describes the rig: motor_count, motor_kinds, osc_addresses, zone
        assignments, interaction filters, param-out mapping, linear actuator
        envelope, icon override. Shared by every mode — edit once.
      * FEEL (per mode) — each of the six modes carries its own per-device
        per-motor "mix" layer (the signal-chain config) plus a master
        intensity scale, a name, and an icon.

    The active mode's per-device mix dict is INSTALLED into the wiring dicts
    under the "mix" key (by reference), so `get_active_profile_dict()` keeps
    returning one merged per-device dict per device — the exact shape
    motor_router.reevaluate_state() and the whole UI already consume. The
    top-level dict and every per-device dict keep a stable identity across
    mode switches (only the "mix" value is swapped), which the router's
    compiled-config cache relies on (it keys on id()).

    Mode slot 0 defaults to "Off" (master scale 0 — the panic mode); slots
    1-3 Low/Medium/High, 4 Sleep, 5 Custom. Every slot stays fully
    user-editable (name, icon, scale, feel).

    The settings managers ride on this object exactly as they did on
    ProfileManager (self.app_settings, self.steamvr_settings, ...) — many
    call sites reach them through the manager.
    """

    SCHEMA_VERSION = 3
    MODE_COUNT = 6
    OFF_SLOT = 0
    CUSTOM_SLOT = 5
    DEFAULT_ACTIVE_MODE = 2  # Medium on a fresh install

    #: Shipped slot metadata. `mix` is added per instance.
    DEFAULT_MODES: List[Dict[str, Any]] = [
        {"name": "Off", "icon": "\U0001F507", "master_scale": 0.0},
        {"name": "Low", "icon": "\U0001F508", "master_scale": 0.6},
        {"name": "Medium", "icon": "\U0001F509", "master_scale": 0.85},
        {"name": "High", "icon": "\U0001F50A", "master_scale": 1.0},
        {"name": "Sleep", "icon": "\U0001F319", "master_scale": 0.7},
        {"name": "Custom", "icon": "\U0001F0CF", "master_scale": 1.0},
    ]

    def __init__(self):
        # device_name -> merged per-device config dict (wiring keys + the
        # active mode's "mix" installed by _install_active_mix). This is THE
        # object graph the router and UI read; it is never rebuilt, only
        # mutated in place.
        self.wiring: Dict[str, Dict[str, Any]] = {}
        self.modes: List[Dict[str, Any]] = self._fresh_modes()
        self.active_mode: int = self.DEFAULT_ACTIVE_MODE
        # avtr_xxx id -> last active mode index. Always recorded; only
        # APPLIED on avatar change when the "remember mode per avatar" app
        # setting is on (the facade checks it).
        self.avatar_last_mode: Dict[str, int] = {}
        # Transient: latest avatar id reported by VRChat. Not persisted.
        self.current_avatar_id: Optional[str] = None

        self.app_settings = AppSettingsManager()
        self.steamvr_settings = SteamVRSettingsManager()
        self.bhaptics_settings = BHapticsSettingsManager()
        self.pishock_settings = PiShockSettingsManager()
        self.coyote_settings = CoyoteSettingsManager()
        self.owo_settings = OwoSettingsManager()
        self.handy_settings = HandySettingsManager()
        self.known_devices = KnownDevicesRegistry()
        self.sps_sources = SpsSourceManager()
        self._load_or_create_default()

    # ------------------------------------------------------------------
    # Construction helpers
    # ------------------------------------------------------------------

    @classmethod
    def _fresh_modes(cls) -> List[Dict[str, Any]]:
        return [dict(meta, mix={}) for meta in cls.DEFAULT_MODES]

    # ------------------------------------------------------------------
    # Load / save with schema migration
    # ------------------------------------------------------------------

    # True when this session loaded on in-memory defaults because the
    # (possibly healthy) file could not be READ — the first save must
    # preserve the on-disk file before overwriting it.
    _degraded_load = False

    def _load_or_create_default(self) -> None:
        """Load modes + wiring from profiles.json (schema v3 only).

        A file that EXISTS but can't be used is never silently clobbered:
        transient read errors run this session on defaults without touching
        the file; a corrupt or non-v3 one is renamed aside before defaults
        are persisted — modes are the user's tuning work, losing them to a
        disk hiccup is not acceptable. There is deliberately no migration
        from the pre-modes profile format: v3 is the only schema.
        """
        raw: Any = None
        self._degraded_load = False  # reset on every (re)load attempt
        exists = os.path.exists(PROFILE_FILE)
        if exists:
            try:
                with open(PROFILE_FILE, 'r', encoding='utf-8') as f:
                    raw = json.load(f)
                    print(f"Loaded config from {PROFILE_FILE}")
            except ValueError as e:
                print(f"Config load error: {e}, creating defaults")
                raw = None
            except OSError as e:
                print(f"Config read error: {e}, running on in-memory "
                      "defaults without overwriting profiles.json")
                self._degraded_load = True
                self.wiring = {}
                self.modes = self._fresh_modes()
                self.active_mode = self.DEFAULT_ACTIVE_MODE
                self._install_active_mix()
                return

        if isinstance(raw, dict) and raw.get("schema") == self.SCHEMA_VERSION:
            self._load_v3(raw)
        else:
            # Unreadable, or an unsupported (non-v3) schema. Preserve it
            # aside, then start fresh.
            if exists:
                backup = str(PROFILE_FILE) + ".bak"
                try:
                    os.replace(PROFILE_FILE, backup)
                    print(f"[modes] unusable profiles.json backed up to {backup}")
                except OSError as e:
                    print(f"[modes] could not back up profiles.json: {e}")
            self.wiring = {}
            self.modes = self._fresh_modes()
            self.active_mode = self.DEFAULT_ACTIVE_MODE
            self.save_profiles()

        self._normalize_wiring_addresses()
        self._backfill_known_devices()
        self._install_active_mix()

    def _load_v3(self, raw: Dict[str, Any]) -> None:
        # A present-but-mis-shaped section (hand edit gone wrong) is
        # salvaged by dropping it — but the next save would then persist
        # the emptied sections over the original with no copy. Preserve
        # the original first, like the corrupt-JSON path does.
        if (("wiring" in raw and not isinstance(raw.get("wiring"), dict))
                or ("modes" in raw
                    and not isinstance(raw.get("modes"), list))):
            backup = f"{PROFILE_FILE}.{int(time.time())}.bak"
            try:
                shutil.copyfile(PROFILE_FILE, backup)
                print(f"[modes] mis-shaped sections in profiles.json — "
                      f"original preserved at {backup}")
            except OSError as e:
                print(f"[modes] could not back up mis-shaped "
                      f"profiles.json: {e}")
        wiring = raw.get("wiring")
        self.wiring = {}
        if isinstance(wiring, dict):
            for name, cfg in wiring.items():
                if isinstance(cfg, dict):
                    # "mix" never belongs in the wiring store on disk;
                    # strip it defensively in case of a hand edit.
                    self.wiring[name] = {k: v for k, v in cfg.items()
                                         if k != "mix"}
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
                slot["master_scale"] = _clamp_scale(
                    mode.get("master_scale"), slot["master_scale"])
                mix = mode.get("mix")
                if isinstance(mix, dict):
                    slot["mix"] = {dev: per_motor
                                   for dev, per_motor in mix.items()
                                   if isinstance(per_motor, dict)}
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
        """Normalizes saved OSC addresses: strips /avatar/parameters/ prefixes
        and upgrades the old string-per-motor format to a list-per-motor.
        Idempotent."""
        migrated = False
        for device in self.wiring.values():
            osc_addresses = device.get("osc_addresses", {})
            if isinstance(osc_addresses, dict):
                for key, val in list(osc_addresses.items()):
                    if isinstance(val, str):
                        cleaned = strip_param_prefix(val)
                        osc_addresses[key] = [cleaned] if cleaned else []
                        migrated = True
                    elif isinstance(val, list):
                        new_list = [strip_param_prefix(a) for a in val
                                    if isinstance(a, str) and a.strip()]
                        if new_list != val:
                            osc_addresses[key] = new_list
                            migrated = True
            legacy_addr = device.get("osc_address", "")
            if isinstance(legacy_addr, str) and legacy_addr.startswith("/"):
                device["osc_address"] = strip_param_prefix(legacy_addr)
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
        """Persist wiring + modes to profiles.json in the v3 schema.

        Degraded sessions (the file existed but could not be READ at load
        time) must never trade the user's real config for this session's
        in-memory defaults: before the first save we retry the read, and if
        the file is healthy again — a transient AV/backup lock is the
        classic cause — the save is SKIPPED so the boot-time reload (or the
        next launch) can recover the real data. Only a genuinely corrupt
        file is moved aside and overwritten."""
        if self._degraded_load:
            try:
                with open(PROFILE_FILE, 'r', encoding='utf-8') as f:
                    if isinstance(json.load(f), dict):
                        print("[modes] profiles.json is readable again — "
                              "skipping save so the real config isn't "
                              "overwritten by this session's defaults")
                        return
            except ValueError:
                pass  # unreadable JSON: genuinely corrupt, back up below
            except OSError as e:
                print(f"[modes] profiles.json still unreadable ({e}) — "
                      "skipping save to protect it")
                return
            backup = f"{PROFILE_FILE}.{int(time.time())}.bak"
            try:
                os.replace(PROFILE_FILE, backup)
                print(f"[modes] corrupt profiles.json backed up to {backup} "
                      "before first save")
            except OSError as e:
                if os.path.exists(PROFILE_FILE):
                    print(f"[modes] could not back up profiles.json ({e}) — "
                          "refusing to overwrite it")
                    return
            self._degraded_load = False
        payload = {
            "schema": self.SCHEMA_VERSION,
            # The active mode's mix is installed into the wiring dicts by
            # reference; it belongs to the mode, so strip it here.
            "wiring": {name: {k: v for k, v in cfg.items() if k != "mix"}
                       for name, cfg in self.wiring.items()},
            "modes": self.modes,
            "active_mode": self.active_mode,
            "avatar_last_mode": self.avatar_last_mode,
        }
        try:
            atomic_write_json(PROFILE_FILE, payload, indent=2)
        except OSError as e:
            print(f"Config save error: {e}")

    # ------------------------------------------------------------------
    # Active mode + master scale
    # ------------------------------------------------------------------

    def _active_mode_dict(self) -> Dict[str, Any]:
        return self.modes[self.active_mode]

    def _install_active_mix(self) -> None:
        """Point every wiring dict's "mix" key at the active mode's
        per-device mix (by reference). Keeps dict identities stable — only
        the "mix" value changes — so the router's id()-keyed compile cache
        stays valid across mode switches."""
        mix_store = self._active_mode_dict().setdefault("mix", {})
        for dev, cfg in self.wiring.items():
            cfg["mix"] = mix_store.setdefault(dev, {})

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
        self._install_active_mix()
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
        """UI-friendly snapshot: one {index, name, icon, master_scale,
        active} per slot."""
        return [
            {"index": i, "name": m.get("name", f"Mode {i}"),
             "icon": m.get("icon", ""),
             "master_scale": _clamp_scale(m.get("master_scale"), 1.0),
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

    def set_mode_master_scale(self, index: int, scale: float,
                              save: bool = True) -> None:
        """`save=False` lets the caller coalesce disk writes (a held
        spinbox arrow fires many changes per second — see the facade's
        debounced save)."""
        self.get_mode(index)["master_scale"] = _clamp_scale(scale, 1.0)
        if save:
            self.save_profiles()

    def get_master_scale(self) -> float:
        """The active mode's output multiplier, always a finite 0..1 float.
        Read from backend dispatch paths (any thread) — must stay a plain
        dict read with no locking or I/O."""
        return _clamp_scale(self._active_mode_dict().get("master_scale"), 1.0)

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
        """Get one config value for a device (wiring keys, or "mix" which
        resolves to the active mode's feel layer)."""
        cfg = self.wiring.get(device_name)
        if cfg is not None:
            return cfg.get(key, default)
        return default

    def update_device_config(self, device_name: str, key: str, value) -> None:
        """Set one config value for a device. Wiring keys land in the shared
        store; "mix" writes go to the active mode's feel layer (and the
        installed reference in the device dict stays in sync)."""
        dev = self.wiring.get(device_name)
        if dev is None:
            dev = self.wiring[device_name] = {}
            dev["mix"] = (self._active_mode_dict().setdefault("mix", {})
                          .setdefault(device_name, {}))
        if key == "mix":
            self._active_mode_dict().setdefault("mix", {})[device_name] = value
        dev[key] = value

    def delete_device(self, device_name: str) -> None:
        """Forget a device everywhere: shared wiring + every mode's feel."""
        self.wiring.pop(device_name, None)
        for mode in self.modes:
            mix = mode.get("mix")
            if isinstance(mix, dict):
                mix.pop(device_name, None)
        self.save_profiles()


def _clamp_scale(value: Any, default: float) -> float:
    """Coerce a master scale to a finite float clamped to [0, 1]."""
    try:
        f = float(value)
    except (TypeError, ValueError):
        return default
    if not math.isfinite(f):
        return default
    return max(0.0, min(1.0, f))
