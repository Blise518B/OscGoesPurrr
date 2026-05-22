"""Tune view controller facade.

Mixin: owns the per-session Tune state (source mode, send-to-toy
safety switch, currently-selected motor, pattern generator handle).
Composed into OscGoesPurrrApp. Relies on `self.motor_router`,
`self.tune_pattern_generator`, `self.thread_queue`, `self.ui`, and
the per-session attrs `self._tune_send_to_toy`, `self._tune_source`,
`self._tune_selected_motor` — all initialised in
`OscGoesPurrrApp._setup_components` before any Tune method is called.

The router's intermediates feed is wired here (set_tune_emit_callback
pushes records onto the existing thread_queue under msg_type
'tune_trace'); the main queue-processing loop hands those records to
the UI via update_tune_trace."""

from typing import Any, Dict, List, Optional, Tuple


_SOURCE_SIMULATED = "simulated"
_SOURCE_LIVE = "live"
_VALID_SOURCES = (_SOURCE_SIMULATED, _SOURCE_LIVE)


class TuneFacade:

    # ----------------------------------------------------------
    # Read facades — UI uses these to populate dropdowns / labels
    # ----------------------------------------------------------

    def tune_list_patterns(self) -> List[str]:
        if not hasattr(self, "tune_pattern_generator"):
            return []
        return self.tune_pattern_generator.list_patterns()

    def tune_get_status(self) -> Dict[str, Any]:
        return {
            "source": getattr(self, "_tune_source", _SOURCE_SIMULATED),
            "send_to_toy": bool(getattr(self, "_tune_send_to_toy", False)),
            "selected_motor": getattr(self, "_tune_selected_motor", None),
            "pattern_running": (
                self.tune_pattern_generator.is_running()
                if hasattr(self, "tune_pattern_generator") else False
            ),
        }

    # ----------------------------------------------------------
    # Selection — which motor's intermediates feed is active
    # ----------------------------------------------------------

    def tune_select_motor(self, device_name: Optional[str],
                          motor_idx: Optional[int]) -> None:
        """Subscribe the Tune view to one motor's intermediates feed,
        or clear the subscription when either arg is None. The router
        only emits traces for the subscribed motor — every other tick
        is a single None comparison and a no-op."""
        if device_name is None or motor_idx is None:
            self._tune_selected_motor = None
            if hasattr(self, "motor_router"):
                self.motor_router.clear_tune_subscription()
            return
        self._tune_selected_motor = (str(device_name), int(motor_idx))
        if hasattr(self, "motor_router"):
            self.motor_router.set_tune_subscription(device_name, int(motor_idx))

    # ----------------------------------------------------------
    # Source mode + simulator control
    # ----------------------------------------------------------

    def tune_set_source(self, source: str) -> None:
        """Switch between 'simulated' (driven by the pattern generator)
        and 'live' (driven by real VRChat OSC). Switching away from
        'simulated' stops the generator so it doesn't keep writing
        synthetic params on top of live input."""
        if source not in _VALID_SOURCES:
            return
        self._tune_source = source
        if source != _SOURCE_SIMULATED:
            self.tune_stop_pattern()

    def tune_start_pattern(self, pattern_name: str) -> bool:
        """Start the named pattern. No-op if Tune isn't in simulated
        mode — patterns only make sense when the user has explicitly
        asked for synthetic input."""
        if getattr(self, "_tune_source", _SOURCE_SIMULATED) != _SOURCE_SIMULATED:
            return False
        if not hasattr(self, "tune_pattern_generator"):
            return False
        return self.tune_pattern_generator.start(pattern_name)

    def tune_stop_pattern(self) -> None:
        if not hasattr(self, "tune_pattern_generator"):
            return
        self.tune_pattern_generator.stop()

    # ----------------------------------------------------------
    # Safety: Send-to-toy switch
    # ----------------------------------------------------------

    def tune_set_send_to_toy(self, enabled: bool) -> None:
        """When OFF (and Tune source = simulated), update_device_target
        forces the selected motor's engine target to 0 so the toy stays
        silent while the user tunes against the graph. The mixer keeps
        computing real values internally so the trace still shows what
        WOULD play."""
        self._tune_send_to_toy = bool(enabled)

    def tune_should_silence(self, device_name: str, motor_idx: int) -> bool:
        """Helper for the controller's update_device_target hook. True
        when the engine should receive 0 for this motor because Tune is
        in simulated mode with Send-to-toy off.

        Only silences the SELECTED motor — the simulator's input
        override only drives the subscribed motor's d_raw, so other
        motors are unaffected by simulation and shouldn't be silenced
        either."""
        if getattr(self, "_tune_source", _SOURCE_SIMULATED) != _SOURCE_SIMULATED:
            return False
        if getattr(self, "_tune_send_to_toy", False):
            return False
        selected = getattr(self, "_tune_selected_motor", None)
        if selected is None:
            return False
        return selected == (device_name, int(motor_idx))
