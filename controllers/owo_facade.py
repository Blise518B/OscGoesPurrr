"""OWO suit facade mixin.

The UI talks to the OWO engine, router, and persisted settings only through
these methods. Assumes the host controller has
`self.profile_manager.owo_settings`, `self.owo_engine`, `self.owo_router`,
`self._get_sps_source_map`, and `self.log_message`."""

from typing import Any, Dict


class OwoFacade:
    """Mixin: OWO-related controller methods. Composed into OscGoesPurrrApp."""

    # ---- private getters for the engine/router ----

    def _owo_settings(self):
        return self.profile_manager.owo_settings

    def _owo_get_auto_connect(self) -> bool:
        return self._owo_settings().get_auto_connect()

    def _owo_get_game_id(self) -> str:
        return self._owo_settings().get_connection()["game_id"]

    def _owo_get_ip(self) -> str:
        return self._owo_settings().get_connection()["ip"]

    def _owo_get_muscle_configs(self) -> Dict[str, Dict[str, Any]]:
        return self._owo_settings().get_muscles()

    def _owo_get_frequency(self) -> int:
        return self._owo_settings().get_frequency()

    # ---- UI-facing API ----

    def get_owo_status(self) -> Dict[str, Any]:
        s = self._owo_settings()
        eng = self.owo_engine
        return {
            "available": eng.is_available,
            "connected": eng.is_connected,
            "last_error": eng.last_error,
            "auto_connect": s.get_auto_connect(),
            "connection": s.get_connection(),
            "frequency": s.get_frequency(),
            "muscles": s.get_muscles(),
        }

    def set_owo_auto_connect(self, enabled: bool) -> None:
        self._owo_settings().set_auto_connect(bool(enabled))

    def set_owo_connection(self, game_id: str, ip: str) -> None:
        self._owo_settings().set_connection(game_id, ip)

    def set_owo_frequency(self, value: int) -> None:
        self._owo_settings().set_frequency(value)

    def get_owo_muscles(self) -> Dict[str, Dict[str, Any]]:
        return self._owo_settings().get_muscles()

    def set_owo_muscle(self, name: str, cfg: Dict[str, Any]) -> None:
        self._owo_settings().set_muscle(name, cfg)

    def owo_connect_now(self) -> bool:
        return self.owo_engine.manual_connect()
