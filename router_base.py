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

import time
from typing import Any, Callable, Dict

from parameter_store import store
from polling import PollingThread

# No OSC traffic for this long => treat the parameter snapshot as stale and
# pull every output to its zero level. parameter_store retains last values
# forever, so without this a VRChat crash mid-contact would latch e-stim /
# EMS / stroking at the last strength indefinitely. This is the shared
# analogue of motor_router's anti-stuck fuse and SteamVR's no-data fallback.
#
# 10 s balances the two failure modes: VRChat only sends parameters on
# CHANGE, so a fully-pinned, motionless held contact can be legitimately
# silent for several seconds (a 5 s cutoff false-positived there, zeroing
# output mid-scene); total silence for 10 s in a live session is almost
# certainly a dead VRChat. Comparable to motor_router's 15 s peaked fuse.
STALE_SIGNAL_CUTOFF_S = 10.0


class StaleSignalMonitor:
    """Tracks parameter_store's packet counter and reports stale once
    `cutoff_s` seconds pass without a single OSC write. One locked counter
    read per call — cheap enough for a 60 Hz router tick. Shared by
    PollingRouter and the discrete-event PiShock router (whose sustain
    re-fires would otherwise keep shocking off a frozen snapshot)."""

    def __init__(self, cutoff_s: float = STALE_SIGNAL_CUTOFF_S):
        self.cutoff_s = cutoff_s
        self._count = -1
        self._ts = time.monotonic()

    def is_stale(self) -> bool:
        if self.cutoff_s <= 0:
            return False
        count = store.get_packets_received()
        now = time.monotonic()
        if count != self._count:
            self._count = count
            self._ts = now
            return False
        return (now - self._ts) >= self.cutoff_s


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

    Stale-signal cutoff: when no OSC packet has arrived for
    ``stale_signal_cutoff_s`` seconds (VRChat crashed / closed), the tick
    computes over an EMPTY snapshot so every enabled output resolves to its
    zero level, then goes idle. Costs one counter read per tick.
    """

    def __init__(self, name: str, engine, poll_rate_s: float = 0.016,
                 stale_signal_cutoff_s: float = STALE_SIGNAL_CUTOFF_S):
        super().__init__(name)
        self.engine = engine
        self.poll_rate_s = poll_rate_s
        self.stale_signal_cutoff_s = stale_signal_cutoff_s
        # key -> last dispatched target; debounces so a held value adds no
        # traffic and the first change after idle is sent immediately.
        self._last_outputs: Dict[Any, Any] = {}
        self._stale_monitor = StaleSignalMonitor(stale_signal_cutoff_s)
        self._stale_zeroed = False

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
        if self._signal_is_stale():
            # OSC went silent while values may be latched non-zero: once,
            # resolve every enabled output against an empty snapshot (-> its
            # zero level), then go fully idle until the signal returns.
            if not self._stale_zeroed:
                self._pull_outputs_to_zero()
                self._stale_zeroed = True
            return
        self._stale_zeroed = False
        if not params and not self._wants_tick_when_idle():
            if self._last_outputs:
                # The store emptied (e.g. an OSCQuery rebuild yielded no
                # avatar params) while outputs were live — pull them to zero
                # rather than latching (same recipe as the stale cutoff).
                self._pull_outputs_to_zero()
            return
        targets = self.compute_targets(params)
        for key, target in targets.items():
            if self._last_outputs.get(key) != target:
                self._last_outputs[key] = target
                self.dispatch(key, target)

    def _pull_outputs_to_zero(self) -> None:
        """Dispatch every enabled output's zero level (computed over an empty
        snapshot), then clear the debounce cache so the first tick after the
        signal returns re-sends current values. One raising dispatch must not
        skip the remaining outputs — each key is guarded individually."""
        try:
            for key, target in self.compute_targets({}).items():
                if self._last_outputs.get(key) != target:
                    try:
                        self.dispatch(key, target)
                    except Exception:
                        continue
        finally:
            self._last_outputs.clear()
            self._on_cleared()

    def _signal_is_stale(self) -> bool:
        """True when no OSC parameter write has arrived within the cutoff."""
        # Kept in sync so tests / callers can tune the cutoff at runtime.
        self._stale_monitor.cutoff_s = self.stale_signal_cutoff_s
        return self._stale_monitor.is_stale()

    def reset_dispatch_cache(self) -> None:
        """Drop the debounce cache so the next tick re-dispatches every output.

        Called from the GUI thread on mode / master-scale changes: the scale
        factor lives outside the router's inputs, so without this a tick would
        see identical targets and debounce away the change. Same recipe as the
        disconnect-clear in ``_tick`` — a plain dict mutation under the GIL,
        matching the existing cross-thread pattern."""
        self._last_outputs.clear()
        self._on_cleared()

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
