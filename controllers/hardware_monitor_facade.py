"""Hardware Monitor facade mixin.

The UI talks to the hardware-monitor engine and its persisted settings
only through these methods.
"""

from typing import Any, Dict


class HardwareMonitorFacade:
    """Mixin: hardware-monitor controller methods. Composed into OscGoesPurrrApp."""

    # ------------------------------------------------------------------
    # Private getters used by the monitor engine callbacks
    # ------------------------------------------------------------------

    def _hardware_monitor_settings(self):
        return self.profile_manager.hardware_monitor_settings

    def _hardware_monitor_get_config(self) -> Dict[str, Any]:
        return self._hardware_monitor_settings().get_all()

    def _hardware_monitor_send_osc(self, address: str, value: float) -> None:
        if not self.osc_manager or not getattr(self.osc_manager, "is_connected", False):
            return
        try:
            self.osc_manager.send_parameter(address, float(value), ignore_rate_limit=True)
        except Exception as e:
            self.log_message(f"HardwareMonitor OSC send failed ({address}): {e}")

    # ------------------------------------------------------------------
    # UI-facing API
    # ------------------------------------------------------------------

    def get_hardware_monitor_status(self) -> Dict[str, Any]:
        """Snapshot for the UI: live hardware stats merged with current settings."""
        snap = self.hardware_monitor.snapshot()
        cfg = self._hardware_monitor_settings().get_all()
        return {"stats": snap, "settings": cfg}

    def set_hardware_monitor_enabled(self, enabled: bool) -> None:
        self._hardware_monitor_settings().set_enabled(bool(enabled))

    def set_hardware_monitor_send_osc(self, enabled: bool) -> None:
        self._hardware_monitor_settings().set_send_osc(bool(enabled))

    def set_hardware_monitor_gpu_enabled(self, enabled: bool) -> None:
        self._hardware_monitor_settings().set_gpu_enabled(bool(enabled))

    def set_hardware_monitor_poll_rate(self, seconds: float) -> None:
        self._hardware_monitor_settings().set_poll_rate(seconds)

    def set_hardware_monitor_address(self, key: str, address: str) -> None:
        self._hardware_monitor_settings().set_address(key, address)

    def set_hardware_monitor_send_toggle(self, key: str, enabled: bool) -> None:
        self._hardware_monitor_settings().set_send_toggle(key, bool(enabled))
