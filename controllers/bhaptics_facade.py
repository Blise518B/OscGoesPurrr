"""bHaptics facade mixin.

The UI talks to the bHaptics engine, router, and persisted settings only
through these methods.
"""

from typing import Any, Dict, List

from bhaptics_engine import DeviceConfig as BHapticsDeviceConfig
from bhaptics_router import (
    device_table as bhaptics_device_table,
    display_name as bhaptics_display_name,
    grid_layout as bhaptics_grid_layout,
    detected_positions as bhaptics_detected_positions,
)
from parameter_store import store


class BHapticsFacade:
    """Mixin: bHaptics-related controller methods. Composed into OscGoesPurrrApp."""

    # ------------------------------------------------------------------
    # Private getters used by the bHaptics router/engine callbacks
    # ------------------------------------------------------------------

    def _bhaptics_settings(self):
        return self.profile_manager.bhaptics_settings

    def _bhaptics_get_auto_connect(self) -> bool:
        return self._bhaptics_settings().get_auto_connect()

    def _bhaptics_get_device_configs(self) -> Dict[str, BHapticsDeviceConfig]:
        raw = self._bhaptics_settings().get_devices()
        return {pos: BHapticsDeviceConfig.from_dict(d) for pos, d in raw.items()}

    def _bhaptics_get_antistuck(self) -> Dict[str, Any]:
        return self._bhaptics_settings().get_antistuck()

    # ------------------------------------------------------------------
    # UI-facing API
    # ------------------------------------------------------------------

    def get_bhaptics_status(self) -> Dict[str, Any]:
        s = self._bhaptics_settings()
        detected = bhaptics_detected_positions(store.get_all_parameters())
        return {
            "available": self.bhaptics_engine.is_available,
            "connected": self.bhaptics_engine.is_connected,
            "last_error": self.bhaptics_engine.last_error,
            "auto_connect": s.get_auto_connect(),
            "host": s.get_host(),
            "port": s.get_port(),
            "antistuck": s.get_antistuck(),
            "devices": [
                {
                    "position": pos,
                    "display_name": bhaptics_display_name(pos),
                    "node_count": count,
                    "grid": bhaptics_grid_layout(pos),  # (cols, rows)
                    "config": s.get_device(pos),
                    "detected": pos in detected,
                }
                for pos, _slot, count in bhaptics_device_table()
            ],
        }

    def get_bhaptics_snapshot(self) -> Dict[str, List[int]]:
        """Live per-device dot intensities (0-100). Used by the debug grid."""
        return self.bhaptics_router.get_snapshot()

    def get_bhaptics_raw_snapshot(self) -> Dict[str, List[int]]:
        """Pre anti-stuck, pre override raw OSC intensities. Used by the
        debug grid's left-hand 'raw input' view."""
        return self.bhaptics_router.get_raw_snapshot()

    def set_bhaptics_auto_connect(self, enabled: bool) -> None:
        self._bhaptics_settings().set_auto_connect(enabled)

    def set_bhaptics_endpoint(self, host: str, port: int) -> None:
        self._bhaptics_settings().set_endpoint(host, port)
        self.bhaptics_engine.set_endpoint(host, port)

    def set_bhaptics_device(self, position: str, cfg: Dict[str, Any]) -> None:
        self._bhaptics_settings().set_device(position, cfg)

    def set_bhaptics_manual_dot(self, position: str, index: int, intensity) -> None:
        """Debug-only: drive a single bHaptics dot at fixed intensity (or
        None to release). Used by the UI's click-to-test grid."""
        self.bhaptics_router.set_manual_override(position, index, intensity)

    def bhaptics_connect_now(self) -> bool:
        return self.bhaptics_engine.manual_connect()

    def set_bhaptics_antistuck(self, enabled: bool, hold_s: float, ramp_s: float) -> None:
        self._bhaptics_settings().set_antistuck(enabled, hold_s, ramp_s)
