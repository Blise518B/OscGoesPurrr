"""PiShock facade mixin.

The UI talks to the PiShock engine, router, and persisted settings only
through these methods. Assumes the host controller (OscGoesPurrrApp) has
`self.profile_manager.pishock_settings`, `self.pishock_engine`,
`self.pishock_router`, `self._get_sps_source_map`, and `self.log_message`."""

from typing import Any, Dict, List


class PiShockFacade:
    """Mixin: PiShock-related controller methods. Composed into OscGoesPurrrApp."""

    # ---- private getters consumed by the engine/router callbacks ----

    def _pishock_settings(self):
        return self.profile_manager.pishock_settings

    def _pishock_get_auto_connect(self) -> bool:
        return self._pishock_settings().get_auto_connect()

    def _pishock_get_zones(self) -> List[Dict[str, Any]]:
        return self._pishock_settings().get_zones()

    def _pishock_get_global_rate(self) -> Dict[str, Any]:
        return self._pishock_settings().get_global_rate()

    def _pishock_apply_config(self) -> None:
        """Push the persisted mode + connection + caps into the engine. Called
        on startup and after any settings edit so live changes take effect."""
        s = self._pishock_settings()
        try:
            self.pishock_engine.set_connection_mode(s.get_mode())
            self.pishock_engine.configure(s.get_engine_config())
        except Exception as e:
            self.log_message(f"PiShock config apply failed: {e}")

    # ---- UI-facing API ----

    def get_pishock_status(self) -> Dict[str, Any]:
        s = self._pishock_settings()
        eng = self.pishock_engine
        return {
            "available": eng.is_available,
            "connected": eng.is_connected,
            "last_error": eng.last_error,
            "status_label": eng.status_label,
            "auto_connect": s.get_auto_connect(),
            "mode": s.get_mode(),
            "serial_port": s.settings.get("serial_port", ""),
            "shocker_id": s.settings.get("shocker_id", 0),
            "username": s.settings.get("username", ""),
            "code": s.settings.get("code", ""),
            "has_apikey": bool(s.settings.get("apikey", "")),
            "name": s.settings.get("name", "OscGoesPurrr"),
            "caps": s.get_caps(),
            "global_rate": s.get_global_rate(),
            "zones": s.get_zones(),
            # Absolute ceilings so the UI can show the user where the hard
            # limits are (settings may only lower these).
            "absolute": {
                "max_intensity": eng.ABSOLUTE_MAX_INTENSITY,
                "max_duration_ms": eng.ABSOLUTE_MAX_DURATION_MS,
                "min_interval_s": eng.ABSOLUTE_MIN_INTERVAL_S,
            },
        }

    def set_pishock_auto_connect(self, enabled: bool) -> None:
        self._pishock_settings().set_auto_connect(bool(enabled))

    def set_pishock_mode(self, mode: str) -> None:
        self._pishock_settings().set_mode(mode)
        self._pishock_apply_config()

    def set_pishock_serial(self, port: str, shocker_id: int) -> None:
        self._pishock_settings().set_serial(port, shocker_id)
        self._pishock_apply_config()

    def set_pishock_cloud(self, username: str, apikey: str, code: str, name: str) -> None:
        self._pishock_settings().set_cloud(username, apikey, code, name)
        self._pishock_apply_config()

    def set_pishock_caps(self, max_intensity: int, max_duration_ms: int,
                         min_interval_s: float) -> None:
        self._pishock_settings().set_caps(max_intensity, max_duration_ms, min_interval_s)
        self._pishock_apply_config()

    def set_pishock_global_rate(self, max_events: int, window_s: float) -> None:
        self._pishock_settings().set_global_rate(max_events, window_s)

    def get_pishock_zones(self) -> List[Dict[str, Any]]:
        return self._pishock_settings().get_zones()

    def set_pishock_zone(self, index: int, zone: Dict[str, Any]) -> None:
        self._pishock_settings().set_zone(index, zone)

    def delete_pishock_zone(self, index: int) -> None:
        self._pishock_settings().delete_zone(index)

    def pishock_connect_now(self) -> bool:
        self._pishock_apply_config()
        return self.pishock_engine.manual_connect()

    def pishock_test_fire(self, op: str = "vibrate") -> bool:
        """Fire one short, gently-capped test op so the user can confirm the
        device responds. Intensity is held to a low test value (the engine
        clamps further); returns False if not connected or throttled."""
        if not self.pishock_engine.is_connected:
            self.log_message("PiShock: connect before testing.")
            return False
        caps = self._pishock_settings().get_caps()
        test_int = min(int(caps.get("max_intensity", 30)), 15)
        fired = self.pishock_engine.fire(op, test_int, 300)
        self.log_message(
            f"PiShock test {op} @ {test_int}" if fired
            else "PiShock test throttled (safety cooldown) — try again shortly.")
        return fired
