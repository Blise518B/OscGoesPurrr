"""Synthetic depth-value producer for the Phase 3 Tune view.

Pull-based: the pattern functions are pure (t_s) → [0, 1] mappings,
and the router samples the current value via `current_value()` on its
own tick. No internal thread, no shared variable — eliminates the
push/pull sample-rate mismatch that would otherwise cause the speed
derivation's |Δposition|/dt to alias into a visible zig-zag.

Sealed-box contract: primitive-only public methods (`start`, `stop`,
`current_value`, `list_patterns`, `is_running`). The Tune facade is
the only caller. No Qt, no controller imports, no parameter_store
imports — the patterns are pure functions of elapsed time."""

import math
import random
import threading
import time
from typing import Callable, Dict, List, Optional


# ----------------------------------------------------------
# Pattern functions: pure (t_s) -> [0, 1] mappings
# ----------------------------------------------------------

def _pattern_slow_stroke(t: float) -> float:
    """Sine at ~0.4 Hz — gentle exploratory stroke."""
    return 0.5 + 0.5 * math.sin(2.0 * math.pi * 0.4 * t)


def _pattern_medium_stroke(t: float) -> float:
    """Sine at ~1 Hz — comfortable steady rhythm."""
    return 0.5 + 0.5 * math.sin(2.0 * math.pi * 1.0 * t)


def _pattern_fast_stroke(t: float) -> float:
    """Sine at ~2 Hz — quick, energetic."""
    return 0.5 + 0.5 * math.sin(2.0 * math.pi * 2.0 * t)


def _pattern_fast_in_slow_out(t: float) -> float:
    """Asymmetric sawtooth — sharp rise (~0.2s), gentle fall (~0.8s).
    Useful for tuning the speed channel's attack response."""
    period = 1.0
    rise_frac = 0.2
    phase = (t % period) / period
    if phase < rise_frac:
        return phase / rise_frac
    return 1.0 - (phase - rise_frac) / (1.0 - rise_frac)


def _pattern_burst(t: float) -> float:
    """Rectangular envelope, on for 1s every 3s. Stress-tests the
    post-mix envelope follower's attack and release timings."""
    period = 3.0
    duty_s = 1.0
    return 1.0 if (t % period) < duty_s else 0.0


class _TeaseState:
    """Random-walk state for the tease pattern. Module-scope so the
    walk persists across calls within one start/stop session."""

    def __init__(self) -> None:
        self.walk = 0.5
        self.rng = random.Random(0xCAFEF00D)
        self.last_step_t: Optional[float] = None

    def reset(self) -> None:
        self.walk = 0.5
        self.rng = random.Random(0xCAFEF00D)
        self.last_step_t = None


_TEASE_STATE = _TeaseState()


def _pattern_tease(t: float) -> float:
    """Random-walk-modulated sine. The walk advances on a fixed time
    grid (~50 ms) rather than every call so the tease behaves the same
    regardless of how often the router samples us."""
    walk_step_s = 0.05
    if _TEASE_STATE.last_step_t is None or t - _TEASE_STATE.last_step_t >= walk_step_s:
        step = (_TEASE_STATE.rng.random() - 0.5) * 0.04
        _TEASE_STATE.walk = max(0.0, min(1.0, _TEASE_STATE.walk + step))
        _TEASE_STATE.last_step_t = t
    carrier = 0.5 + 0.5 * math.sin(2.0 * math.pi * 1.5 * t)
    return _TEASE_STATE.walk * carrier


# Patterns are registered here in display order (the Tune view shows
# them in a dropdown in this order).
_PATTERNS: Dict[str, Callable[[float], float]] = {
    "slow_stroke": _pattern_slow_stroke,
    "medium_stroke": _pattern_medium_stroke,
    "fast_stroke": _pattern_fast_stroke,
    "fast_in_slow_out": _pattern_fast_in_slow_out,
    "burst": _pattern_burst,
    "tease": _pattern_tease,
}


class TunePatternGenerator:
    """Pull-based simulated-input source for the Tune view. The Tune
    facade is the only caller. Thread-safe; protected by a lock so
    start/stop races are clean."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._pattern_name: Optional[str] = None
        self._pattern_fn: Optional[Callable[[float], float]] = None
        self._t0: Optional[float] = None

    def list_patterns(self) -> List[str]:
        """Display-ordered list of available pattern names."""
        return list(_PATTERNS.keys())

    def is_running(self) -> bool:
        with self._lock:
            return self._pattern_fn is not None

    def start(self, pattern_name: str) -> bool:
        """Start (or switch to) `pattern_name`. Returns True on success,
        False if the pattern name is unknown. Switching patterns resets
        the t=0 reference so each pattern begins from its own phase 0
        and the tease state re-seeds for a reproducible walk."""
        if pattern_name not in _PATTERNS:
            return False
        with self._lock:
            self._pattern_name = pattern_name
            self._pattern_fn = _PATTERNS[pattern_name]
            self._t0 = time.monotonic()
            _TEASE_STATE.reset()
        return True

    def stop(self) -> None:
        """Stop emitting. Subsequent current_value() calls return None
        so the router falls back to normal zone/address routing for
        the subscribed motor."""
        with self._lock:
            self._pattern_name = None
            self._pattern_fn = None
            self._t0 = None

    def current_value(self) -> Optional[float]:
        """Evaluate the current pattern at the caller's exact `now` time.
        Returns a value in [0, 1], or None when no pattern is running.
        Cheap enough to call on the router's hot path."""
        with self._lock:
            fn = self._pattern_fn
            t0 = self._t0
        if fn is None or t0 is None:
            return None
        t = time.monotonic() - t0
        try:
            v = float(fn(t))
        except Exception:
            return None
        if v < 0.0:
            return 0.0
        if v > 1.0:
            return 1.0
        return v
