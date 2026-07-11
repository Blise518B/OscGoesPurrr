"""DG-Lab Coyote 3.0 integration state: BLE target, per-channel soft strength
limits (enforced in hardware via the BF command), and the A/B channel routing
config. e-stim, so auto-connect defaults OFF."""

from typing import Any, Dict

from ._base import JsonSettingsManager
from ._paths import COYOTE_SETTINGS_FILE

_VALID_FILTERS = ("TouchSelf", "TouchOthers", "PenSelf", "PenOthers")
_VALID_ZONE_TYPES = ("Orf", "Pen", "Touch")


def _default_channel() -> Dict[str, Any]:
    return {
        "enabled": False,
        "ogb_zone": "",
        "zone_type": "Orf",
        "filters": ["TouchSelf", "TouchOthers"],
        "threshold": 0.0,
        "gain": 1.0,
        "max_strength": 100,   # 0-200; the per-channel mapping ceiling
        "freq": 100,           # waveform frequency 10-240
        "intensity": 100,      # waveform intensity 0-100
    }


class CoyoteSettingsManager(JsonSettingsManager):
    FILE_PATH = COYOTE_SETTINGS_FILE

    DEFAULTS: Dict[str, Any] = {
        "auto_connect": False,
        "address": "",
        "name": "",
        # Hardware soft strength limits (BF command), 0-200.
        "limit_a": 100,
        "limit_b": 100,
        "channels": {"A": _default_channel(), "B": _default_channel()},
    }

    def _post_load(self, loaded: Dict[str, Any]) -> None:
        chans = self.settings.get("channels")
        if not isinstance(chans, dict):
            chans = {}
        for ch in ("A", "B"):
            base = _default_channel()
            if isinstance(chans.get(ch), dict):
                base.update(chans[ch])
            chans[ch] = base
        self.settings["channels"] = chans

    # ---- connection ----
    def get_auto_connect(self) -> bool:
        return bool(self.settings.get("auto_connect", False))

    def set_auto_connect(self, value: bool) -> None:
        self.settings["auto_connect"] = bool(value)
        self._save()

    def get_device(self) -> Dict[str, str]:
        return {
            "address": str(self.settings.get("address", "")),
            "name": str(self.settings.get("name", "")),
        }

    def set_device(self, address: str, name: str) -> None:
        self.settings["address"] = str(address or "").strip()
        self.settings["name"] = str(name or "").strip()
        self._save()

    # ---- limits ----
    def get_limits(self) -> Dict[str, int]:
        # Tolerant + clamped on READ: this feeds the connect path and the
        # status poll, and a hand-edited "limit_a": null used to crash
        # both. Mirrors the clamps set_limits applies on write.
        def _lim(key: str) -> int:
            try:
                v = int(self.settings.get(key, 100))
            except (TypeError, ValueError):
                return 100
            return max(0, min(200, v))

        return {"limit_a": _lim("limit_a"), "limit_b": _lim("limit_b")}

    def set_limits(self, limit_a: int, limit_b: int) -> None:
        self.settings["limit_a"] = max(0, min(200, int(limit_a)))
        self.settings["limit_b"] = max(0, min(200, int(limit_b)))
        self._save()

    # ---- channels ----
    def get_channels(self) -> Dict[str, Dict[str, Any]]:
        chans = self.settings.get("channels", {})
        return {ch: self._clean_channel(chans.get(ch, {})) for ch in ("A", "B")}

    def set_channel(self, channel: str, cfg: Dict[str, Any]) -> None:
        if channel not in ("A", "B"):
            return
        chans = dict(self.settings.get("channels", {}))
        chans[channel] = self._clean_channel(cfg)
        self.settings["channels"] = chans
        self._save()

    @staticmethod
    def _clean_channel(cfg: Dict[str, Any]) -> Dict[str, Any]:
        base = _default_channel()
        if not isinstance(cfg, dict):
            return base

        def _f(key, default):
            try:
                return float(cfg.get(key, default))
            except (TypeError, ValueError):
                return default

        def _i(key, default):
            try:
                return int(cfg.get(key, default))
            except (TypeError, ValueError):
                return default

        zone_type = str(cfg.get("zone_type", "Orf"))
        if zone_type not in _VALID_ZONE_TYPES:
            zone_type = "Orf"
        return {
            "enabled": bool(cfg.get("enabled", False)),
            "ogb_zone": str(cfg.get("ogb_zone", "")).strip(),
            "zone_type": zone_type,
            "filters": [f for f in (cfg.get("filters") or []) if f in _VALID_FILTERS],
            "threshold": max(0.0, min(1.0, _f("threshold", 0.0))),
            "gain": max(0.0, min(5.0, _f("gain", 1.0))),
            "max_strength": max(0, min(200, _i("max_strength", 100))),
            "freq": max(10, min(240, _i("freq", 100))),
            "intensity": max(0, min(100, _i("intensity", 100))),
        }
