"""DG-Lab Coyote facade mixin.

The UI talks to the Coyote engine, router, and persisted settings only through
these methods. Assumes the host controller has
`self.profile_manager.coyote_settings`, `self.coyote_engine`,
`self.coyote_router`, `self._get_sps_source_map`, and `self.log_message`."""

from typing import Any, Dict, List, Tuple


class CoyoteFacade:
    """Mixin: Coyote-related controller methods. Composed into OscGoesPurrrApp."""

    # ---- private getters for the engine/router ----

    def _coyote_settings(self):
        return self.profile_manager.coyote_settings

    def _coyote_get_auto_connect(self) -> bool:
        return self._coyote_settings().get_auto_connect()

    def _coyote_get_channel_configs(self) -> Dict[str, Dict[str, Any]]:
        return self._coyote_settings().get_channels()

    def _coyote_apply_config(self) -> None:
        """Push device target + soft limits + per-channel waveform into the
        engine. Called on startup and after any settings edit."""
        s = self._coyote_settings()
        dev = s.get_device()
        lim = s.get_limits()
        try:
            self.coyote_engine.configure(
                address=dev["address"], name=dev["name"],
                limit_a=lim["limit_a"], limit_b=lim["limit_b"])
            chans = s.get_channels()
            for ch in ("A", "B"):
                c = chans[ch]
                self.coyote_engine.set_waveform(ch, c["freq"], c["intensity"])
        except Exception as e:
            self.log_message(f"Coyote config apply failed: {e}")

    # ---- UI-facing API ----

    def get_coyote_status(self) -> Dict[str, Any]:
        s = self._coyote_settings()
        eng = self.coyote_engine
        return {
            "available": eng.is_available,
            "connected": eng.is_connected,
            "last_error": eng.last_error,
            "auto_connect": s.get_auto_connect(),
            "device": s.get_device(),
            "limits": s.get_limits(),
            "battery": eng.battery,
            "strengths": eng.strengths,
            "channels": s.get_channels(),
        }

    def set_coyote_auto_connect(self, enabled: bool) -> None:
        self._coyote_settings().set_auto_connect(bool(enabled))

    def set_coyote_device(self, address: str, name: str) -> None:
        self._coyote_settings().set_device(address, name)
        self._coyote_apply_config()

    def set_coyote_limits(self, limit_a: int, limit_b: int) -> None:
        self._coyote_settings().set_limits(limit_a, limit_b)
        # Live-apply the new hardware soft limits.
        try:
            lim = self._coyote_settings().get_limits()
            self.coyote_engine.set_strength_limits(lim["limit_a"], lim["limit_b"])
        except Exception as e:
            self.log_message(f"Coyote limit apply failed: {e}")

    def get_coyote_channels(self) -> Dict[str, Dict[str, Any]]:
        return self._coyote_settings().get_channels()

    def set_coyote_channel(self, channel: str, cfg: Dict[str, Any]) -> None:
        self._coyote_settings().set_channel(channel, cfg)
        self._coyote_apply_config()

    def coyote_connect_now(self) -> bool:
        self._coyote_apply_config()
        return self.coyote_engine.manual_connect()

    def coyote_scan_devices(self) -> List[Tuple[str, str]]:
        """Scan for nearby BLE devices so the user can pick the Coyote.
        Returns [(name, address)]."""
        try:
            return self.coyote_engine.scan_devices()
        except Exception as e:
            self.log_message(f"Coyote scan failed: {e}")
            return []
