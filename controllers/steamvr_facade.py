"""SteamVR Haptics facade mixin.

The UI and other backend services must go through these methods — they
MUST NOT touch `self.steamvr_engine`, `self.steamvr_router`, or
`self.profile_manager.steamvr_settings` directly.
"""

from typing import Any, Dict, List

from steamvr_engine import TrackerConfig as SteamVRTrackerConfig
from steamvr_engine import PatternConfig as SteamVRPatternConfig


class SteamVRFacade:
    """Mixin: SteamVR-related controller methods. Composed into OscGoesPurrrApp."""

    # ------------------------------------------------------------------
    # Private getters used both internally and by router/battery callbacks
    # ------------------------------------------------------------------

    def _steamvr_settings(self):
        return self.profile_manager.steamvr_settings

    def _steamvr_get_tracker_config(self, serial: str) -> SteamVRTrackerConfig:
        return SteamVRTrackerConfig.from_dict(self._steamvr_settings().get_tracker(serial))

    def _steamvr_get_all_tracker_configs(self) -> Dict[str, SteamVRTrackerConfig]:
        return {
            serial: SteamVRTrackerConfig.from_dict(d)
            for serial, d in self._steamvr_settings().get_tracker_dict().items()
        }

    def _steamvr_get_pattern_configs(self) -> List[SteamVRPatternConfig]:
        return [SteamVRPatternConfig.from_dict(d) for d in self._steamvr_settings().get_patterns()]

    def _steamvr_get_no_data(self) -> Dict[str, Any]:
        return self._steamvr_settings().get_no_data()

    def _steamvr_get_battery_interval(self) -> float:
        return float(self._steamvr_settings().get_battery_interval())

    def _steamvr_get_auto_connect(self) -> bool:
        return self._steamvr_settings().get_auto_connect()

    def _steamvr_send_osc(self, address: str, value: float) -> None:
        # Reuse the existing outbound VRChat client (already targets the
        # discovered OSCQuery port). No-op if VRChat isn't connected.
        if not self.osc_manager or not getattr(self.osc_manager, "is_connected", False):
            return
        try:
            self.osc_manager.send_parameter(address, float(value), ignore_rate_limit=True)
        except Exception as e:
            self.log_message(f"SteamVR battery OSC send failed ({address}): {e}")

    # ------------------------------------------------------------------
    # UI-facing API
    # ------------------------------------------------------------------

    def get_steamvr_status(self) -> Dict[str, Any]:
        """Snapshot for the UI: runtime alive, device list, autostart, manifest reg."""
        devices = self.steamvr_engine.snapshot_devices()
        return {
            "available": self.steamvr_engine.is_available,
            "alive": self.steamvr_engine.is_alive,
            "bundled": self.steamvr_engine.is_app_bundled,
            "autostart": self._steamvr_settings().get_autostart(),
            "auto_connect": self._steamvr_settings().get_auto_connect(),
            "registered": self.steamvr_engine.is_registered() if self.steamvr_engine.is_alive else False,
            "battery_interval_s": self._steamvr_get_battery_interval(),
            "no_data": self._steamvr_settings().get_no_data(),
            "trackers": [
                {
                    "serial": d.serial,
                    "model": d.model,
                    "device_class": d.device_class,
                    "supports_haptics": d.supports_haptics,
                    "battery": self.steamvr_engine.battery_for(d.serial),
                    "config": self._steamvr_settings().get_tracker(d.serial),
                }
                for d in devices
            ],
        }

    def refresh_steamvr_trackers(self) -> int:
        devices = self.steamvr_engine.refresh_devices(quiet=False)
        return len(devices)

    def pulse_steamvr_tracker(self, serial: str, length_ms: int = 500) -> None:
        self.steamvr_engine.pulse_test(serial, length_ms)

    def set_steamvr_tracker_config(self, serial: str, cfg: Dict[str, Any]) -> None:
        self._steamvr_settings().set_tracker(serial, cfg)

    def set_steamvr_autostart(self, enabled: bool) -> None:
        self._steamvr_settings().set_autostart(enabled)
        try:
            self.steamvr_engine.setup_autostart(enabled)
        except Exception as e:
            self.log_message(f"SteamVR autostart toggle failed: {e}")

    def set_steamvr_pattern(self, index: int, pattern_dict: Dict[str, Any]) -> None:
        self._steamvr_settings().set_pattern(index, pattern_dict)

    def get_steamvr_pattern_configs(self) -> List[Dict[str, Any]]:
        return list(self._steamvr_settings().get_patterns())

    def set_steamvr_no_data(self, enabled: bool, timeout_active_s: int,
                            timeout_peaked_s: int) -> None:
        self._steamvr_settings().set_no_data(enabled, timeout_active_s, timeout_peaked_s)

    def set_steamvr_battery_interval(self, seconds: float) -> None:
        self._steamvr_settings().set_battery_interval(seconds)
        self.steamvr_battery.set_interval(seconds)

    def set_steamvr_auto_connect(self, enabled: bool) -> None:
        self._steamvr_settings().set_auto_connect(enabled)
        # If just turned on, try one immediate refresh so the UI updates quickly.
        if enabled:
            try:
                self.steamvr_engine.refresh_devices(quiet=True)
            except Exception:
                pass
