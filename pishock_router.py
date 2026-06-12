# pishock_router.py
# Discrete-event router for PiShock. Unlike the continuous-level routers
# (SteamVR / OWO / Coyote), a shock device is NOT driven by a streamed 0..1
# level — it fires a single (op, intensity, duration) event on a rising edge,
# then must re-arm before it can fire again. This file owns that edge logic.
#
# Safety lives in two layers (defense in depth): per-zone policy here (rising
# edge, hysteresis re-arm, per-zone cooldown, a global rate backstop) AND hard
# clamps + a global min-interval in PiShockEngine.fire(). The pure helpers
# (decide_fire, map_intensity, RateLimiter) are unit-tested without a thread.

import time
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional

from parameter_store import store
from polling import PollingThread
from pishock_connection import OP_SHOCK, VALID_OPS
from zone_strength import zone_filter_strength


@dataclass
class ZoneState:
    """Per-zone edge state. Starts armed so the first crossing fires."""
    armed: bool = True
    last_fire_ts: float = -1e9


@dataclass
class FireEvent:
    op: str
    intensity: int
    duration_ms: int


def map_intensity(strength: float, threshold: float, lo: int, hi: int) -> int:
    """Map a strength in [threshold, 1] linearly onto [lo, hi]. Clamped to a
    valid 1-100 op intensity."""
    span = max(1e-6, 1.0 - threshold)
    frac = max(0.0, min(1.0, (strength - threshold) / span))
    val = int(round(lo + frac * (hi - lo)))
    return max(1, min(100, val))


def decide_fire(zone: Dict[str, Any], strength: float,
                state: ZoneState, now: float) -> Optional[FireEvent]:
    """Pure rising-edge decision. Mutates `state` (arm/disarm + last_fire_ts)
    and returns a FireEvent to dispatch, or None.

    Rules:
      * Re-arm once strength drops below (threshold - hysteresis).
      * Fire only when strength >= threshold AND armed (a fresh rising edge),
        or — if the zone opts into `sustain` — every `cadence_s` while held.
      * A per-zone `min_interval_s` cooldown blocks too-soon repeats.
      * The first crossing after idle fires immediately (no cooldown debt).
    """
    threshold = float(zone.get("threshold", 0.5))
    hysteresis = float(zone.get("hysteresis", 0.1))

    # Re-arm on clear release.
    if strength < max(0.0, threshold - hysteresis):
        state.armed = True
        return None

    # Below threshold (or zero) — nothing to do.
    if strength <= 0.0 or strength < threshold:
        return None

    sustain = bool(zone.get("sustain", False))
    cadence_s = float(zone.get("cadence_s", 1.0))
    min_interval_s = float(zone.get("min_interval_s", 1.0))

    fire_due = False
    if state.armed:
        fire_due = True
    elif sustain and (now - state.last_fire_ts) >= cadence_s:
        fire_due = True
    if not fire_due:
        return None

    # Per-zone cooldown (the first fire after idle passes because last_fire_ts
    # starts far in the past).
    if (now - state.last_fire_ts) < min_interval_s:
        # Consume the edge so we don't busy-spin re-checking it; the zone will
        # naturally re-arm + re-fire on the next genuine crossing.
        state.armed = False
        return None

    op = zone.get("op", OP_SHOCK)
    if op not in VALID_OPS:
        op = OP_SHOCK
    lo = int(zone.get("min_int", 1))
    hi = int(zone.get("max_int", 30))
    intensity = map_intensity(strength, threshold, lo, hi)
    duration_ms = int(zone.get("duration_ms", 300))

    state.armed = False
    state.last_fire_ts = now
    return FireEvent(op, intensity, duration_ms)


class RateLimiter:
    """Sliding-window global backstop: at most `max_events` in any `window_s`.
    A hard cap across all zones so multiple zones can't gang up into a burst,
    independent of each zone's own cooldown."""

    def __init__(self, max_events: int = 6, window_s: float = 10.0):
        self.max_events = max(1, int(max_events))
        self.window_s = max(0.1, float(window_s))
        self._events: List[float] = []

    def try_acquire(self, now: float) -> bool:
        cutoff = now - self.window_s
        self._events = [t for t in self._events if t >= cutoff]
        if len(self._events) >= self.max_events:
            return False
        self._events.append(now)
        return True


class PiShockRouter(PollingThread):
    """Polls parameter_store at ~60 Hz and fires PiShock events on rising edges.

    Not a PollingRouter: shocks are discrete events, not a debounced level, so
    the edge/cooldown/rate-limit semantics replace the simple last_outputs
    debounce."""

    def __init__(self,
                 engine,
                 get_zone_configs: Callable[[], List[Dict[str, Any]]],
                 get_sps_sources: Optional[Callable[[], Dict[str, Any]]] = None,
                 get_global_rate: Optional[Callable[[], Dict[str, Any]]] = None,
                 poll_rate_s: float = 0.016,
                 clock: Callable[[], float] = time.monotonic):
        super().__init__("PiShockRouter")
        self.engine = engine
        self.get_zone_configs = get_zone_configs
        self.get_sps_sources = get_sps_sources or (lambda: None)
        self.get_global_rate = get_global_rate or (lambda: {"max_events": 6, "window_s": 10.0})
        self.poll_rate_s = poll_rate_s
        self._clock = clock
        self._states: Dict[str, ZoneState] = {}
        self._limiter = RateLimiter()

    def _run(self):
        print("[PiShock] Router thread started")
        while not self._stop.is_set():
            try:
                self._tick()
            except Exception as e:
                print(f"[PiShock][Router] tick error: {e}")
            self._interruptible_sleep(self.poll_rate_s)

    def _tick(self):
        if not self.engine.is_connected:
            return
        zones = self.get_zone_configs() or []
        if not zones:
            return
        params = store.get_all_parameters() or {}
        if not params:
            return
        try:
            sps_sources = self.get_sps_sources()
        except Exception:
            sps_sources = None
        # Keep the global limiter's window in sync with live settings.
        self._sync_limiter()
        now = self._clock()
        for i, zone in enumerate(zones):
            if not isinstance(zone, dict) or not zone.get("enabled", True):
                continue
            key = str(zone.get("name") or i)
            state = self._states.setdefault(key, ZoneState())
            strength = zone_filter_strength(
                zone.get("ogb_zone"), zone.get("zone_type", "Orf"),
                zone.get("filters") or [], params, sps_sources)
            event = decide_fire(zone, strength, state, now)
            if event is None:
                continue
            # Global backstop across all zones, then the engine's own caps.
            if not self._limiter.try_acquire(now):
                continue
            self.engine.fire(event.op, event.intensity, event.duration_ms)

    def _sync_limiter(self):
        try:
            cfg = self.get_global_rate() or {}
            self._limiter.max_events = max(1, int(cfg.get("max_events", 6)))
            self._limiter.window_s = max(0.1, float(cfg.get("window_s", 10.0)))
        except (TypeError, ValueError):
            pass
