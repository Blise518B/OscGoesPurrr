# router_base.py
# Shared ~60 Hz poll loop for the stateless level-routers.
#
# Every simple router (SteamVR trackers, OWO muscles, Coyote channels) does the
# same thing: poll parameter_store on a fast timer, compute a per-output target,
# and push it to its engine only when the value actually changes (debounced).
# That loop + debounce lives here so each router only declares how to compute
# its targets and how to dispatch one.
#
# This is the COLD compute/debounce layer, not a transport — it never blocks,
# never queues, and dispatches straight to the engine on the producing thread.
# See ARCHITECTURE.md "Latency budget".
#
# bHaptics keeps its own bespoke `_tick` (anti-stuck ramp + raw/override
# snapshots don't fit the flat target model) but still inherits `_run` so the
# loop isn't duplicated. motor_router stays separate entirely (it's driven from
# the UI thread via force_recalculate, not a poll thread).

from typing import Any, Callable, Dict

from parameter_store import store
from polling import PollingThread


class PollingRouter(PollingThread):
    """Debounced ~60 Hz poll loop. Subclasses implement:

      * ``compute_targets(params) -> {key: hashable_target}`` — the per-output
        values for this tick (omit an output to leave its last value latched).
      * ``dispatch(key, target)`` — push one changed target to the engine.

    Optional hooks:
      * ``_engine_ready()`` — gate ticking on a live connection. Default True
        (always tick); override to ``self.engine.is_connected`` for backends
        that must go quiet while disconnected (and get clear-on-disconnect).
      * ``_wants_tick_when_idle()`` — keep ticking with an empty param store.
      * ``_on_cleared()`` — called once when the debounce cache is cleared on a
        disconnect, so a subclass can flush any mirrored snapshot state.
    """

    def __init__(self, name: str, engine, poll_rate_s: float = 0.016):
        super().__init__(name)
        self.engine = engine
        self.poll_rate_s = poll_rate_s
        # key -> last dispatched target; debounces so a held value adds no
        # traffic and the first change after idle is sent immediately.
        self._last_outputs: Dict[Any, Any] = {}

    def _run(self) -> None:
        print(f"[{self._thread_name}] thread started")
        while not self._stop.is_set():
            try:
                self._tick()
            except Exception as e:
                print(f"[{self._thread_name}] tick error: {e}")
            self._interruptible_sleep(self.poll_rate_s)

    def _tick(self) -> None:
        if not self._engine_ready():
            # Clear debounce so we re-send immediately on reconnect.
            if self._last_outputs:
                self._last_outputs.clear()
                self._on_cleared()
            return
        params = store.get_all_parameters() or {}
        if not params and not self._wants_tick_when_idle():
            return
        targets = self.compute_targets(params)
        for key, target in targets.items():
            if self._last_outputs.get(key) != target:
                self._last_outputs[key] = target
                self.dispatch(key, target)

    # ---- Hooks (override as needed) ----------------------------------
    def _engine_ready(self) -> bool:
        return True

    def _wants_tick_when_idle(self) -> bool:
        return False

    def _on_cleared(self) -> None:
        pass

    def compute_targets(self, params: Dict[str, Any]) -> Dict[Any, Any]:
        raise NotImplementedError

    def dispatch(self, key: Any, target: Any) -> None:
        raise NotImplementedError
