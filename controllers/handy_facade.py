"""The Handy facade mixin.

The UI talks to the Handy engine, router, and persisted settings only
through these methods. Assumes the host controller has
`self.profile_manager.handy_settings`, `self.handy_engine`,
`self.handy_router`, `self._get_sps_source_map`, and `self.log_message`."""

from typing import Any, Dict


class HandyFacade:
    """Mixin: Handy-related controller methods. Composed into OscGoesPurrrApp."""

    # ---- private getters for the engine/router ----

    def _handy_settings(self):
        return self.profile_manager.handy_settings

    def _handy_get_auto_connect(self) -> bool:
        return self._handy_settings().get_auto_connect()

    def _handy_get_connection_key(self) -> str:
        return self._handy_settings().get_connection()["connection_key"]

    def _handy_get_api_key(self) -> str:
        return self._handy_settings().get_connection()["api_key"]

    def _handy_get_motion(self) -> Dict[str, Any]:
        return self._handy_settings().get_motion()

    def _handy_get_zone_config(self) -> Dict[str, Any]:
        return self._handy_settings().get_zone()

    # ---- UI-facing API ----

    def get_handy_status(self) -> Dict[str, Any]:
        s = self._handy_settings()
        eng = self.handy_engine
        return {
            "available": eng.is_available,
            "connected": eng.is_connected,
            "last_error": eng.last_error,
            "auto_connect": s.get_auto_connect(),
            "connection": s.get_connection(),
            "motion": s.get_motion(),
            "zone": s.get_zone(),
            "extras": eng.get_status_extras(),
        }

    def set_handy_auto_connect(self, enabled: bool) -> None:
        self._handy_settings().set_auto_connect(bool(enabled))

    def set_handy_connection(self, connection_key: str, api_key: str) -> None:
        self._handy_settings().set_connection(connection_key, api_key)

    def set_handy_motion(self, cfg: Dict[str, Any]) -> None:
        before = self._handy_settings().get_motion()
        self._handy_settings().set_motion(cfg)
        after = self._handy_settings().get_motion()
        # Stroke zone changes are device state, not just routing math —
        # push them to the connected device right away.
        if (before["stroke_min"], before["stroke_max"]) != (
                after["stroke_min"], after["stroke_max"]):
            self.handy_engine.refresh_stroke_zone()

    def set_handy_zone(self, cfg: Dict[str, Any]) -> None:
        self._handy_settings().set_zone(cfg)

    def handy_connect_now(self) -> bool:
        return self.handy_engine.manual_connect()
