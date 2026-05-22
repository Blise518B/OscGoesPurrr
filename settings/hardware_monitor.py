"""Hardware monitor settings: master toggle, poll rate, GPU enable,
per-stat send toggles, and per-stat OSC address overrides."""

import json
import os
from typing import Any, Dict

from utilities import atomic_write_json, strip_param_prefix

from ._paths import HARDWARE_MONITOR_SETTINGS_FILE


class HardwareMonitorSettingsManager:
    """Persists Hardware Monitor settings: master toggle, poll rate, GPU enable,
    per-stat send toggles, and per-stat OSC address overrides. Output is sent
    over the existing VRChat OSC client so any VRChat avatar parameter can
    receive the values."""

    # User-facing parameter names. The VRChat /avatar/parameters/ prefix is
    # hidden from the user and re-added at send time by the engine.
    _DEFAULT_ADDRESSES: Dict[str, str] = {
        "cpu_percent":   "HW_CPU",
        "ram_used_gb":   "HW_RAM_Used",
        "ram_total_gb":  "HW_RAM_Total",
        "gpu_percent":   "HW_GPU",
        "vram_used_gb":  "HW_VRAM_Used",
        "vram_total_gb": "HW_VRAM_Total",
    }

    _DEFAULT_TOGGLES: Dict[str, bool] = {
        "cpu_percent":   True,
        "ram_used_gb":   True,
        "ram_total_gb":  True,
        "gpu_percent":   True,
        "vram_used_gb":  True,
        "vram_total_gb": True,
    }

    DEFAULTS: Dict[str, Any] = {
        "enabled": False,
        "send_osc": True,
        "gpu_enabled": True,
        "poll_rate_s": 2.0,
        "addresses": _DEFAULT_ADDRESSES,
        "send_toggles": _DEFAULT_TOGGLES,
    }

    def __init__(self):
        self.settings: Dict[str, Any] = {}
        self._load_or_create_defaults()

    def _load_or_create_defaults(self) -> None:
        if os.path.exists(HARDWARE_MONITOR_SETTINGS_FILE):
            try:
                with open(HARDWARE_MONITOR_SETTINGS_FILE, 'r') as f:
                    loaded = json.load(f)
                    if isinstance(loaded, dict):
                        merged = {**self.DEFAULTS, **loaded}
                        # Backfill any newly-added keys for forward-compat.
                        addrs = dict(self._DEFAULT_ADDRESSES)
                        for k, v in (loaded.get("addresses", {}) or {}).items():
                            addrs[k] = strip_param_prefix(v) or self._DEFAULT_ADDRESSES.get(k, "")
                        merged["addresses"] = addrs
                        tgs = dict(self._DEFAULT_TOGGLES)
                        tgs.update(loaded.get("send_toggles", {}) or {})
                        merged["send_toggles"] = tgs
                        self.settings = merged
                        return
            except (json.JSONDecodeError, IOError) as e:
                print(f"Hardware monitor settings load error: {e}, using defaults")
        self.settings = json.loads(json.dumps(self.DEFAULTS))
        self._save()

    def _save(self) -> None:
        try:
            atomic_write_json(HARDWARE_MONITOR_SETTINGS_FILE, self.settings, indent=2)
        except OSError as e:
            print(f"Hardware monitor settings save error: {e}")

    def get_all(self) -> Dict[str, Any]:
        # Return a shallow copy so callers can't mutate persisted state.
        out = dict(self.settings)
        out["addresses"] = dict(self.settings.get("addresses", {}))
        out["send_toggles"] = dict(self.settings.get("send_toggles", {}))
        return out

    def get_enabled(self) -> bool:
        return bool(self.settings.get("enabled", False))

    def set_enabled(self, value: bool) -> None:
        self.settings["enabled"] = bool(value)
        self._save()

    def get_send_osc(self) -> bool:
        return bool(self.settings.get("send_osc", True))

    def set_send_osc(self, value: bool) -> None:
        self.settings["send_osc"] = bool(value)
        self._save()

    def get_gpu_enabled(self) -> bool:
        return bool(self.settings.get("gpu_enabled", True))

    def set_gpu_enabled(self, value: bool) -> None:
        self.settings["gpu_enabled"] = bool(value)
        self._save()

    def get_poll_rate(self) -> float:
        try:
            return max(0.25, float(self.settings.get("poll_rate_s", 2.0)))
        except (TypeError, ValueError):
            return 2.0

    def set_poll_rate(self, seconds: float) -> None:
        try:
            self.settings["poll_rate_s"] = max(0.25, float(seconds))
        except (TypeError, ValueError):
            self.settings["poll_rate_s"] = 2.0
        self._save()

    def get_address(self, key: str) -> str:
        return str(self.settings.get("addresses", {}).get(key, self._DEFAULT_ADDRESSES.get(key, "")))

    def set_address(self, key: str, address: str) -> None:
        addrs = self.settings.setdefault("addresses", {})
        clean = strip_param_prefix(address)
        addrs[key] = clean or self._DEFAULT_ADDRESSES.get(key, "")
        self._save()

    def get_send_toggle(self, key: str) -> bool:
        return bool(self.settings.get("send_toggles", {}).get(key, True))

    def set_send_toggle(self, key: str, value: bool) -> None:
        toggles = self.settings.setdefault("send_toggles", {})
        toggles[key] = bool(value)
        self._save()
