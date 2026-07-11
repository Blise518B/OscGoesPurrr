"""OWO suit integration state: connection (game auth id + optional suit IP),
global sensation frequency, and per-muscle zone routing for the 10 muscle
groups. EMS, so auto-connect defaults OFF."""

from typing import Any, Dict

from ._base import JsonSettingsManager
from ._paths import OWO_SETTINGS_FILE

MUSCLE_NAMES = [
    "Pectoral_R", "Pectoral_L",
    "Abdominal_R", "Abdominal_L",
    "Arm_R", "Arm_L",
    "Dorsal_R", "Dorsal_L",
    "Lumbar_R", "Lumbar_L",
]

_VALID_FILTERS = ("TouchSelf", "TouchOthers", "PenSelf", "PenOthers")
_VALID_ZONE_TYPES = ("Orf", "Pen", "Touch")


def _default_muscle() -> Dict[str, Any]:
    return {
        "enabled": False,
        "ogb_zone": "",
        "zone_type": "Orf",
        "filters": ["TouchSelf", "TouchOthers"],
        "threshold": 0.0,
        "gain": 1.0,
        "max_intensity": 100,
    }


class OwoSettingsManager(JsonSettingsManager):
    FILE_PATH = OWO_SETTINGS_FILE

    DEFAULTS: Dict[str, Any] = {
        "auto_connect": False,
        # OWO game-auth id. Optional — left blank uses an anonymous GameAuth;
        # set your registered id if your OWO setup requires one.
        "game_id": "",
        # Suit/app IP. Blank = AutoConnect (the My OWO app discovers the PC).
        "ip": "",
        "frequency": 100,        # global sensation frequency 0-100
        "muscles": {name: _default_muscle() for name in MUSCLE_NAMES},
    }

    def _post_load(self, loaded: Dict[str, Any]) -> None:
        muscles = self.settings.get("muscles")
        if not isinstance(muscles, dict):
            muscles = {}
        for name in MUSCLE_NAMES:
            base = _default_muscle()
            if isinstance(muscles.get(name), dict):
                base.update(muscles[name])
            muscles[name] = base
        self.settings["muscles"] = muscles

    # ---- connection ----
    def get_auto_connect(self) -> bool:
        return bool(self.settings.get("auto_connect", False))

    def set_auto_connect(self, value: bool) -> None:
        self.settings["auto_connect"] = bool(value)
        self._save()

    def get_connection(self) -> Dict[str, str]:
        return {
            "game_id": str(self.settings.get("game_id", "")),
            "ip": str(self.settings.get("ip", "")),
        }

    def set_connection(self, game_id: str, ip: str) -> None:
        self.settings["game_id"] = str(game_id or "").strip()
        self.settings["ip"] = str(ip or "").strip()
        self._save()

    # ---- frequency ----
    def get_frequency(self) -> int:
        try:
            return max(0, min(100, int(self.settings.get("frequency", 100))))
        except (TypeError, ValueError):
            return 100

    def set_frequency(self, value: int) -> None:
        try:
            self.settings["frequency"] = max(0, min(100, int(value)))
        except (TypeError, ValueError):
            self.settings["frequency"] = 100
        self._save()

    # ---- muscles ----
    def get_muscles(self) -> Dict[str, Dict[str, Any]]:
        muscles = self.settings.get("muscles", {})
        return {n: self._clean_muscle(muscles.get(n, {})) for n in MUSCLE_NAMES}

    def set_muscle(self, name: str, cfg: Dict[str, Any]) -> None:
        if name not in MUSCLE_NAMES:
            return
        muscles = dict(self.settings.get("muscles", {}))
        muscles[name] = self._clean_muscle(cfg)
        self.settings["muscles"] = muscles
        self._save()

    @staticmethod
    def _clean_muscle(cfg: Dict[str, Any]) -> Dict[str, Any]:
        base = _default_muscle()
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
            "max_intensity": max(0, min(100, _i("max_intensity", 100))),
        }
