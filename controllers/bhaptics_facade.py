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
    # VRChat-side: bool that tracks the bHaptics Player connection
    # ------------------------------------------------------------------

    def _bhaptics_send_connected_bool(self) -> None:
        """Push the current bHaptics connection state to the user-configured
        VRChat avatar parameter as a bool. Called when:
          * the bHaptics Player connects / disconnects (state callback)
          * VRChat OSC reconnects (parameter values reset on the wire)
          * /avatar/change fires (loading an avatar resets its params)
        Silent no-op if the user disabled the feature or VRChat OSC isn't
        connected yet — the next OSC connect will re-send."""
        cfg = self._bhaptics_settings().get_osc_connected()
        if not cfg.get("enabled"):
            return
        if not self.osc_manager or not getattr(self.osc_manager, "is_connected", False):
            return
        param = cfg.get("param") or "bHaptics_Connected"
        address = f"/avatar/parameters/{param}"
        try:
            value = bool(self.bhaptics_engine.is_connected)
        except Exception:
            value = False
        try:
            # ignore_rate_limit so state-change edges always land; rate
            # limiting could swallow the transition we care about.
            self.osc_manager.send_parameter(address, value, ignore_rate_limit=True)
        except Exception as e:
            self.log_message(f"bHaptics OSC connected-bool send failed ({address}): {e}")

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
            "osc_connected": s.get_osc_connected(),
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

    def set_bhaptics_osc_connected(self, enabled: bool, param: str) -> None:
        """Configure the connected-state OSC bool. `param` is the bare avatar
        parameter name (e.g. 'bHaptics_Connected'); a leading
        /avatar/parameters/ is stripped if the user pastes one in. Re-sends
        the current value immediately so the avatar parameter reflects
        whatever the engine state is right now."""
        self._bhaptics_settings().set_osc_connected(enabled, param)
        self._bhaptics_send_connected_bool()
