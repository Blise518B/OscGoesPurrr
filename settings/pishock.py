"""PiShock integration state: transport (serial / cloud), credentials, the
hard safety caps, a global rate backstop, and per-zone routing rules.

A shock device is opt-in by design: auto-connect defaults OFF and the caps
default conservative. The engine clamps every cap to an absolute ceiling, so
nothing here can widen them past what PiShockEngine allows."""

from typing import Any, Dict, List

from ._base import JsonSettingsManager
from ._paths import PISHOCK_SETTINGS_FILE

_VALID_OPS = ("shock", "vibrate", "beep")
_VALID_FILTERS = ("TouchSelf", "TouchOthers", "PenSelf", "PenOthers")
_VALID_ZONE_TYPES = ("Orf", "Pen")


class PiShockSettingsManager(JsonSettingsManager):
    FILE_PATH = PISHOCK_SETTINGS_FILE

    DEFAULTS: Dict[str, Any] = {
        # Safety: a shock device should never auto-fire on first launch.
        "auto_connect": False,
        "mode": "serial",            # "serial" | "cloud"
        # serial transport
        "serial_port": "",
        "shocker_id": 0,
        # cloud transport
        "username": "",
        "apikey": "",
        "code": "",
        "name": "OscGoesPurrr",
        # Hard safety caps (clamped to absolute ceilings by PiShockEngine).
        "max_intensity": 30,
        "max_duration_ms": 1000,
        "min_interval_s": 1.0,
        # Global rate backstop across all zones.
        "rate_max_events": 6,
        "rate_window_s": 10.0,
        # Per-zone routing rules (list of zone dicts; see _clean_zone).
        "zones": [],
    }

    def _post_load(self, loaded: Dict[str, Any]) -> None:
        if not isinstance(loaded.get("zones"), list):
            self.settings["zones"] = []

    # ---- Connection ----
    def get_auto_connect(self) -> bool:
        return bool(self.settings.get("auto_connect", False))

    def set_auto_connect(self, value: bool) -> None:
        self.settings["auto_connect"] = bool(value)
        self._save()

    def get_mode(self) -> str:
        m = str(self.settings.get("mode", "serial"))
        return m if m in ("serial", "cloud") else "serial"

    def set_mode(self, mode: str) -> None:
        self.settings["mode"] = mode if mode in ("serial", "cloud") else "serial"
        self._save()

    def set_serial(self, port: str, shocker_id: int) -> None:
        self.settings["serial_port"] = str(port or "").strip()
        try:
            self.settings["shocker_id"] = int(shocker_id)
        except (TypeError, ValueError):
            self.settings["shocker_id"] = 0
        self._save()

    def set_cloud(self, username: str, apikey: str, code: str, name: str) -> None:
        self.settings["username"] = str(username or "").strip()
        self.settings["apikey"] = str(apikey or "").strip()
        self.settings["code"] = str(code or "").strip()
        self.settings["name"] = str(name or "OscGoesPurrr").strip() or "OscGoesPurrr"
        self._save()

    # ---- Caps + rate ----
    def get_caps(self) -> Dict[str, Any]:
        return {
            "max_intensity": int(self.settings.get("max_intensity", 30)),
            "max_duration_ms": int(self.settings.get("max_duration_ms", 1000)),
            "min_interval_s": float(self.settings.get("min_interval_s", 1.0)),
        }

    def set_caps(self, max_intensity: int, max_duration_ms: int,
                 min_interval_s: float) -> None:
        self.settings["max_intensity"] = max(1, min(100, int(max_intensity)))
        self.settings["max_duration_ms"] = max(1, min(15000, int(max_duration_ms)))
        try:
            self.settings["min_interval_s"] = max(0.3, float(min_interval_s))
        except (TypeError, ValueError):
            self.settings["min_interval_s"] = 1.0
        self._save()

    def get_global_rate(self) -> Dict[str, Any]:
        return {
            "max_events": int(self.settings.get("rate_max_events", 6)),
            "window_s": float(self.settings.get("rate_window_s", 10.0)),
        }

    def set_global_rate(self, max_events: int, window_s: float) -> None:
        self.settings["rate_max_events"] = max(1, int(max_events))
        try:
            self.settings["rate_window_s"] = max(0.1, float(window_s))
        except (TypeError, ValueError):
            self.settings["rate_window_s"] = 10.0
        self._save()

    def get_engine_config(self) -> Dict[str, Any]:
        """The flat dict PiShockEngine.configure() expects (connection +
        caps merged)."""
        return {
            "mode": self.get_mode(),
            "serial_port": self.settings.get("serial_port", ""),
            "shocker_id": self.settings.get("shocker_id", 0),
            "username": self.settings.get("username", ""),
            "apikey": self.settings.get("apikey", ""),
            "code": self.settings.get("code", ""),
            "name": self.settings.get("name", "OscGoesPurrr"),
            **self.get_caps(),
        }

    # ---- Zones ----
    def get_zones(self) -> List[Dict[str, Any]]:
        return [self._clean_zone(z) for z in self.settings.get("zones", [])
                if isinstance(z, dict)]

    def set_zone(self, index: int, zone: Dict[str, Any]) -> None:
        zones = list(self.settings.get("zones", []))
        cleaned = self._clean_zone(zone)
        if index >= len(zones):
            zones.append(cleaned)
        elif index < 0:
            zones.insert(0, cleaned)
        else:
            zones[index] = cleaned
        self.settings["zones"] = zones
        self._save()

    def delete_zone(self, index: int) -> None:
        zones = list(self.settings.get("zones", []))
        if 0 <= index < len(zones):
            zones.pop(index)
            self.settings["zones"] = zones
            self._save()

    @staticmethod
    def _clean_zone(zone: Dict[str, Any]) -> Dict[str, Any]:
        """Coerce + clamp every field so a bad input or hand-edited file can't
        crash the router or smuggle an unsafe value past the UI."""
        def _f(key, default):
            try:
                return float(zone.get(key, default))
            except (TypeError, ValueError):
                return default

        def _i(key, default):
            try:
                return int(zone.get(key, default))
            except (TypeError, ValueError):
                return default

        op = str(zone.get("op", "shock"))
        if op not in _VALID_OPS:
            op = "shock"
        zone_type = str(zone.get("zone_type", "Orf"))
        if zone_type not in _VALID_ZONE_TYPES:
            zone_type = "Orf"
        filters = [f for f in (zone.get("filters") or []) if f in _VALID_FILTERS]
        return {
            "name": str(zone.get("name", "")).strip() or "Zone",
            "ogb_zone": str(zone.get("ogb_zone", "")).strip(),
            "zone_type": zone_type,
            "filters": filters,
            "op": op,
            "threshold": max(0.0, min(1.0, _f("threshold", 0.5))),
            "hysteresis": max(0.0, min(1.0, _f("hysteresis", 0.1))),
            "min_int": max(1, min(100, _i("min_int", 1))),
            "max_int": max(1, min(100, _i("max_int", 30))),
            "duration_ms": max(1, min(15000, _i("duration_ms", 300))),
            "min_interval_s": max(0.3, _f("min_interval_s", 1.0)),
            "sustain": bool(zone.get("sustain", False)),
            "cadence_s": max(0.3, _f("cadence_s", 1.0)),
            "enabled": bool(zone.get("enabled", True)),
        }
