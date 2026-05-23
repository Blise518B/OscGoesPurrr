"""bHaptics integration state: Player connection endpoint, auto-connect,
anti-stuck, and per-device enable + intensity."""

import json
import os
from typing import Any, Dict

from utilities import atomic_write_json, strip_param_prefix

from ._paths import BHAPTICS_SETTINGS_FILE


class BHapticsSettingsManager:
    """Persists bHaptics integration state: Player connection endpoint,
    auto-connect flag, and per-device enable + intensity. Per-device
    defaults match the v1.0.0 bHapticsOSC layout (9 device categories)."""

    _DEFAULT_DEVICES: Dict[str, Dict[str, Any]] = {
        "Head":      {"enabled": True, "intensity": 100},
        "VestFront": {"enabled": True, "intensity": 100},
        "VestBack":  {"enabled": True, "intensity": 100},
        "ForearmL":  {"enabled": True, "intensity": 100},
        "ForearmR":  {"enabled": True, "intensity": 100},
        "HandL":     {"enabled": True, "intensity": 100},
        "HandR":     {"enabled": True, "intensity": 100},
        "FootL":     {"enabled": True, "intensity": 100},
        "FootR":     {"enabled": True, "intensity": 100},
    }

    # SPS-mirror defaults — off, empty entries list. No pre-baked zone
    # mappings: the user builds entries from currently-detected OGB
    # zones via the Cross-Routing sub-tab. Keeps the avatar in the
    # driver's seat (an avatar without "Booty" will never see a Booty
    # entry suggested, much less created).
    _DEFAULT_SPS_MIRROR: Dict[str, Any] = {
        "enabled": False,
        "entries": [],
    }

    DEFAULTS: Dict[str, Any] = {
        "auto_connect": True,
        "host": "127.0.0.1",
        "port": 15881,
        # Anti-stuck: when a dot's input value hasn't changed for `hold_s`
        # seconds, linearly ramp it down to 0 over `ramp_s` seconds. Guards
        # against avatars that latch a contact at full strength and never
        # release it (e.g. when the sending controller drops out mid-touch).
        "antistuck_enabled": True,
        "antistuck_hold_s": 2.0,
        "antistuck_ramp_s": 2.0,
        # When the bHaptics Player connection state changes, push the bool
        # to this VRChat avatar parameter so an animation can react. Bare
        # parameter name — the /avatar/parameters/ prefix is added at send
        # time, matching the Hardware Monitor convention.
        "osc_connected_enabled": True,
        "osc_connected_param": "bHaptics_Connected",
        "devices": _DEFAULT_DEVICES,
        "sps_mirror": _DEFAULT_SPS_MIRROR,
    }

    def __init__(self):
        self.settings: Dict[str, Any] = {}
        self._load_or_create_defaults()

    def _load_or_create_defaults(self) -> None:
        if os.path.exists(BHAPTICS_SETTINGS_FILE):
            try:
                with open(BHAPTICS_SETTINGS_FILE, 'r') as f:
                    loaded = json.load(f)
                    if isinstance(loaded, dict):
                        merged = {**self.DEFAULTS, **loaded}
                        # Backfill any newly-added devices into older configs.
                        devs = dict(self._DEFAULT_DEVICES)
                        devs.update(loaded.get("devices", {}) or {})
                        merged["devices"] = devs
                        # Backfill the sps_mirror block if the loaded
                        # config predates the feature; preserve the
                        # user's existing entries otherwise.
                        loaded_mirror = loaded.get("sps_mirror")
                        if not isinstance(loaded_mirror, dict):
                            merged["sps_mirror"] = json.loads(
                                json.dumps(self._DEFAULT_SPS_MIRROR)
                            )
                        else:
                            merged["sps_mirror"] = {
                                "enabled": bool(loaded_mirror.get("enabled", False)),
                                "entries": list(loaded_mirror.get("entries", [])),
                            }
                        self.settings = merged
                        return
            except (json.JSONDecodeError, IOError) as e:
                print(f"bHaptics settings load error: {e}, using defaults")
        self.settings = json.loads(json.dumps(self.DEFAULTS))
        self._save()

    def _save(self) -> None:
        try:
            atomic_write_json(BHAPTICS_SETTINGS_FILE, self.settings, indent=2)
        except OSError as e:
            print(f"bHaptics settings save error: {e}")

    # ---- Endpoint ----
    def get_host(self) -> str:
        return str(self.settings.get("host", "127.0.0.1"))

    def get_port(self) -> int:
        try:
            return int(self.settings.get("port", 15881))
        except (TypeError, ValueError):
            return 15881

    def set_endpoint(self, host: str, port: int) -> None:
        self.settings["host"] = str(host or "127.0.0.1").strip()
        try:
            self.settings["port"] = int(port)
        except (TypeError, ValueError):
            self.settings["port"] = 15881
        self._save()

    # ---- Auto-connect ----
    def get_auto_connect(self) -> bool:
        return bool(self.settings.get("auto_connect", True))

    def set_auto_connect(self, value: bool) -> None:
        self.settings["auto_connect"] = bool(value)
        self._save()

    # ---- Anti-stuck ----
    def get_antistuck(self) -> Dict[str, Any]:
        return {
            "enabled": bool(self.settings.get("antistuck_enabled", True)),
            "hold_s": float(self.settings.get("antistuck_hold_s", 2.0)),
            "ramp_s": float(self.settings.get("antistuck_ramp_s", 2.0)),
        }

    def set_antistuck(self, enabled: bool, hold_s: float, ramp_s: float) -> None:
        self.settings["antistuck_enabled"] = bool(enabled)
        try:
            self.settings["antistuck_hold_s"] = max(0.1, float(hold_s))
        except (TypeError, ValueError):
            self.settings["antistuck_hold_s"] = 2.0
        try:
            self.settings["antistuck_ramp_s"] = max(0.1, float(ramp_s))
        except (TypeError, ValueError):
            self.settings["antistuck_ramp_s"] = 2.0
        self._save()

    # ---- Connected-state OSC bool ----
    def get_osc_connected(self) -> Dict[str, Any]:
        return {
            "enabled": bool(self.settings.get("osc_connected_enabled", True)),
            "param":   strip_param_prefix(
                self.settings.get("osc_connected_param", "bHaptics_Connected")
            ) or "bHaptics_Connected",
        }

    def set_osc_connected(self, enabled: bool, param: str) -> None:
        self.settings["osc_connected_enabled"] = bool(enabled)
        cleaned = strip_param_prefix(param) or "bHaptics_Connected"
        self.settings["osc_connected_param"] = cleaned
        self._save()

    # ---- Devices ----
    def get_devices(self) -> Dict[str, Dict[str, Any]]:
        return dict(self.settings.get("devices", {}))

    def get_device(self, position: str) -> Dict[str, Any]:
        devs = self.settings.setdefault("devices", {})
        if position not in devs:
            devs[position] = dict(self._DEFAULT_DEVICES.get(position, {"enabled": True, "intensity": 100}))
            self._save()
        return dict(devs[position])

    def set_device(self, position: str, cfg: Dict[str, Any]) -> None:
        devs = self.settings.setdefault("devices", {})
        devs[position] = dict(cfg)
        self._save()

    # ---- SPS -> bHaptics mirror ----

    def _sps_mirror_block(self) -> Dict[str, Any]:
        """Return the live sps_mirror block, lazily filling defaults if
        the on-disk file is from a pre-feature build."""
        block = self.settings.get("sps_mirror")
        if not isinstance(block, dict):
            block = json.loads(json.dumps(self._DEFAULT_SPS_MIRROR))
            self.settings["sps_mirror"] = block
            self._save()
        return block

    def get_sps_mirror(self) -> Dict[str, Any]:
        """Snapshot: {enabled: bool, entries: list of entry dicts}.
        The entries list is a deep copy so the caller can mutate
        without touching the persisted state."""
        block = self._sps_mirror_block()
        return {
            "enabled": bool(block.get("enabled", False)),
            "entries": [dict(e) for e in block.get("entries", [])],
        }

    def is_sps_mirror_enabled(self) -> bool:
        return bool(self._sps_mirror_block().get("enabled", False))

    def set_sps_mirror_enabled(self, enabled: bool) -> None:
        block = self._sps_mirror_block()
        block["enabled"] = bool(enabled)
        self._save()

    def set_sps_mirror_entry(self, index: int, entry: Dict[str, Any]) -> None:
        """Insert or update an entry. `index == len(entries)` appends.
        Out-of-range indices clamp to the nearest valid slot."""
        block = self._sps_mirror_block()
        entries = list(block.get("entries", []))
        cleaned = self._clean_mirror_entry(entry)
        if index < 0:
            entries.insert(0, cleaned)
        elif index >= len(entries):
            entries.append(cleaned)
        else:
            entries[index] = cleaned
        block["entries"] = entries
        self._save()

    def delete_sps_mirror_entry(self, index: int) -> None:
        block = self._sps_mirror_block()
        entries = list(block.get("entries", []))
        if 0 <= index < len(entries):
            entries.pop(index)
            block["entries"] = entries
            self._save()

    @staticmethod
    def _clean_mirror_entry(entry: Dict[str, Any]) -> Dict[str, Any]:
        """Coerce + clamp every field of a mirror entry so a bad
        user input or hand-edited file can't crash the router."""
        valid_filters = ("TouchSelf", "TouchOthers", "PenSelf", "PenOthers")
        valid_zone_types = ("Orf", "Pen")
        try:
            gain = float(entry.get("gain", 1.0))
        except (TypeError, ValueError):
            gain = 1.0
        try:
            threshold = float(entry.get("threshold", 0.0))
        except (TypeError, ValueError):
            threshold = 0.0
        try:
            dots = [int(d) for d in (entry.get("dot_indices") or [])]
        except (TypeError, ValueError):
            dots = []
        filters = [f for f in (entry.get("filters") or []) if f in valid_filters]
        zone_type = str(entry.get("zone_type", "Orf"))
        if zone_type not in valid_zone_types:
            zone_type = "Orf"
        return {
            "name": str(entry.get("name", "")).strip() or "Mirror",
            "ogb_zone": str(entry.get("ogb_zone", "")).strip(),
            "zone_type": zone_type,
            "filters": filters,
            "position": str(entry.get("position", "VestFront")).strip(),
            "dot_indices": sorted(set(d for d in dots if d >= 0)),
            "gain": max(0.0, min(2.0, gain)),
            "threshold": max(0.0, min(1.0, threshold)),
        }
