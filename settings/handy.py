"""The Handy (Handy 2 / Pro 2) integration state: cloud credentials
(connection key + handyfeeling API key), motion settings (control mode,
slider stroke zone, speed cap, send cadence), and the single zone routing.
Moving hardware strapped to the user, so auto-connect defaults OFF."""

from typing import Any, Dict

from ._base import JsonSettingsManager
from ._paths import HANDY_SETTINGS_FILE

_VALID_FILTERS = ("TouchSelf", "TouchOthers", "PenSelf", "PenOthers")
_VALID_ZONE_TYPES = ("Orf", "Pen")
_VALID_MODES = ("speed", "position")


def _default_zone() -> Dict[str, Any]:
    return {
        "enabled": False,
        "ogb_zone": "",
        "zone_type": "Orf",
        "filters": ["TouchSelf", "TouchOthers"],
        "threshold": 0.0,
        "gain": 1.0,
    }


class HandySettingsManager(JsonSettingsManager):
    FILE_PATH = HANDY_SETTINGS_FILE

    DEFAULTS: Dict[str, Any] = {
        "auto_connect": False,
        # Device connection key — shown in the Handyverse app / onboarding.
        "connection_key": "",
        # handyfeeling.com API key (Application ID) from user.handyfeeling.com.
        # API v3 requires it on every device request.
        "api_key": "",
        # "speed" = HAMP alternating motion (level drives stroke speed).
        # "position" = HDSP direct positioning (level drives slider position).
        "mode": "speed",
        # Slider stroke zone (0-1, device-enforced across all modes).
        "stroke_min": 0.0,
        "stroke_max": 1.0,
        # Hard cap on the HAMP velocity (0-1) no matter the contact strength.
        "max_velocity": 1.0,
        # Cloud command budget (commands/second). The documented API window
        # is ~240 requests/min; 4/s fills exactly that.
        "max_cmd_hz": 4.0,
        # Speed mode: seconds of zero level before /hamp/stop is sent.
        "idle_stop_s": 5.0,
        # Position mode: False = stronger contact pulls the slider down.
        "invert": False,
        "zone": _default_zone(),
    }

    def _post_load(self, loaded: Dict[str, Any]) -> None:
        base = _default_zone()
        if isinstance(self.settings.get("zone"), dict):
            base.update(self.settings["zone"])
        self.settings["zone"] = self._clean_zone(base)

    # ---- connection ----
    def get_auto_connect(self) -> bool:
        return bool(self.settings.get("auto_connect", False))

    def set_auto_connect(self, value: bool) -> None:
        self.settings["auto_connect"] = bool(value)
        self._save()

    def get_connection(self) -> Dict[str, str]:
        return {
            "connection_key": str(self.settings.get("connection_key", "")),
            "api_key": str(self.settings.get("api_key", "")),
        }

    def set_connection(self, connection_key: str, api_key: str) -> None:
        self.settings["connection_key"] = str(connection_key or "").strip()
        self.settings["api_key"] = str(api_key or "").strip()
        self._save()

    # ---- motion ----
    def get_motion(self) -> Dict[str, Any]:
        """Primitive snapshot the engine's send loop reads every tick."""
        mode = str(self.settings.get("mode", "speed"))
        if mode not in _VALID_MODES:
            mode = "speed"
        return {
            "mode": mode,
            "stroke_min": self._f("stroke_min", 0.0, 0.0, 1.0),
            "stroke_max": self._f("stroke_max", 1.0, 0.0, 1.0),
            "max_velocity": self._f("max_velocity", 1.0, 0.0, 1.0),
            "max_cmd_hz": self._f("max_cmd_hz", 4.0, 0.5, 15.0),
            "idle_stop_s": self._f("idle_stop_s", 5.0, 0.5, 60.0),
            "invert": bool(self.settings.get("invert", False)),
        }

    def set_motion(self, cfg: Dict[str, Any]) -> None:
        if not isinstance(cfg, dict):
            return
        merged = self.get_motion()
        merged.update({k: v for k, v in cfg.items() if k in merged})
        if merged["mode"] not in _VALID_MODES:
            merged["mode"] = "speed"
        self.settings.update({
            "mode": merged["mode"],
            "stroke_min": max(0.0, min(1.0, float(merged["stroke_min"]))),
            "stroke_max": max(0.0, min(1.0, float(merged["stroke_max"]))),
            "max_velocity": max(0.0, min(1.0, float(merged["max_velocity"]))),
            "max_cmd_hz": max(0.5, min(15.0, float(merged["max_cmd_hz"]))),
            "idle_stop_s": max(0.5, min(60.0, float(merged["idle_stop_s"]))),
            "invert": bool(merged["invert"]),
        })
        self._save()

    # ---- zone routing ----
    def get_zone(self) -> Dict[str, Any]:
        return self._clean_zone(self.settings.get("zone", {}))

    def set_zone(self, cfg: Dict[str, Any]) -> None:
        self.settings["zone"] = self._clean_zone(cfg)
        self._save()

    # ---- helpers ----
    def _f(self, key: str, default: float, lo: float, hi: float) -> float:
        try:
            return max(lo, min(hi, float(self.settings.get(key, default))))
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _clean_zone(cfg: Dict[str, Any]) -> Dict[str, Any]:
        base = _default_zone()
        if not isinstance(cfg, dict):
            return base

        def _f(key, default):
            try:
                return float(cfg.get(key, default))
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
        }
