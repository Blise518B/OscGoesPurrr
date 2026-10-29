"""Auto modes for a friend's toy: the shape a level follows by itself.

The controller only sends the mode -- wave, period, low, high -- and the
receiver's OGP plays it, so the curve is smooth at the router's own rate
and costs the link nothing while it runs. Pure functions, any thread.

The first five are the simulator's own waveforms (`mixer.sample_pattern`),
so a friend's Sine feels like the app's. Three more:

  * ``heart``  — a heartbeat: two beats close together, then a rest.
  * ``build``  — climbs from low to high over one period with a ripple on
    top, then drops back and starts again.
  * ``osc``    — Oscillate: a sine around the level the friend set, as deep
    as they like (their card sends it as low/high around that level).
"""

import math
from typing import Any, Dict, Optional, Tuple

import mixer

WAVES = ("sine", "square", "triangle", "saw", "random", "heart", "build", "osc")
LABELS = {
    "sine": "Sine", "square": "Square", "triangle": "Triangle", "saw": "Saw",
    "random": "Random", "heart": "Heartbeat", "build": "Build-up", "osc": "Oscillate",
}
PERIOD_MIN_S = 0.25
PERIOD_MAX_S = 120.0
MENU_SLOW_S, MENU_FAST_S = 8.0, 0.3    # the VRChat menu's Speed radial, 0 .. 1
_SAMPLER = {"sine": "sine", "square": "square", "triangle": "triangle",
            "saw": "sawtooth", "random": "random", "osc": "sine"}


def clean(wave, period, lo, hi) -> Optional[Tuple[str, float, float, float]]:
    """A pattern as sent, cleaned -- or None when it isn't one."""
    if wave not in WAVES:
        return None
    try:
        period, lo, hi = float(period), float(lo), float(hi)
    except (TypeError, ValueError):
        return None
    if not all(math.isfinite(v) for v in (period, lo, hi)):
        return None
    period = max(PERIOD_MIN_S, min(PERIOD_MAX_S, period))
    lo = max(0.0, min(1.0, lo))
    hi = max(0.0, min(1.0, hi))
    if hi < lo:
        lo, hi = hi, lo
    return wave, period, lo, hi


def menu_period(wave: str, speed: float) -> float:
    """The VRChat menu's Speed radial (0 slow .. 1 fast) as a period; a
    Build-up climbs ten times slower than the rest."""
    u = max(0.0, min(1.0, float(speed)))
    period = MENU_SLOW_S * (MENU_FAST_S / MENU_SLOW_S) ** u
    return min(PERIOD_MAX_S, period * (10.0 if wave == "build" else 1.0))


def menu_speed(wave: str, period: float) -> float:
    """menu_period's inverse: a period as the menu's Speed radial (0..1),
    for showing an auto mode set in the app on the menu."""
    p = max(1e-6, float(period)) / (10.0 if wave == "build" else 1.0)
    u = math.log(p / MENU_SLOW_S) / math.log(MENU_FAST_S / MENU_SLOW_S)
    return max(0.0, min(1.0, u))


def shape(wave: str, phase: float, t: float, period: float) -> float:
    """0..1 at `phase` (cycles since the start, any real) -- `t` seconds
    since the start feeds the deterministic random."""
    p = phase % 1.0
    if wave in _SAMPLER:
        if wave == "random":
            return mixer.sample_pattern(1.0 / period, 1.0, "random", t)
        return mixer.sample_pattern(1.0, 1.0, _SAMPLER[wave], p)
    if wave == "heart":
        beat = 0.0
        for start, depth in ((0.0, 1.0), (0.22, 0.7)):
            x = (p - start) / 0.14
            if 0.0 <= x < 1.0:
                beat = max(beat, depth * math.sin(math.pi * x))
        return beat
    if wave == "build":
        if p > 0.94:                       # the drop
            return 0.0
        ramp = p / 0.94
        ripple = 0.5 + 0.5 * math.sin(2.0 * math.pi * p * 12.0)
        return ramp * (0.75 + 0.25 * ripple)
    return 0.0


def level(pattern: Tuple[str, float, float, float], t: float, phase: float) -> float:
    """The level a cleaned pattern asks for: low + (high - low) * shape."""
    wave, period, lo, hi = pattern
    return lo + (hi - lo) * max(0.0, min(1.0, shape(wave, phase, t, period)))


def anchor(pattern: Tuple[str, float, float, float], old: Optional[Dict[str, Any]],
           now: float) -> Dict[str, Any]:
    """A playing auto mode, anchored in time: {p, t0, ph0, ts}. The same wave
    carries on where its cycle stands (a new speed doesn't jump the phase);
    a new wave starts at 0."""
    if old is not None and old["p"][0] == pattern[0]:
        if old["p"][1] == pattern[1]:
            return {**old, "p": pattern}
        phase = old["ph0"] + (now - old["t0"]) / old["p"][1]
        return {"p": pattern, "t0": now, "ph0": phase, "ts": old["ts"]}
    return {"p": pattern, "t0": now, "ph0": 0.0, "ts": now}


def play(a: Dict[str, Any], now: float) -> float:
    """The level an anchored auto mode asks for at `now`."""
    phase = a["ph0"] + (now - a["t0"]) / a["p"][1]
    return level(a["p"], now - a["ts"], phase)
