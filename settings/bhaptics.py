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
