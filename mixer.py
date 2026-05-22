"""Pure-function mixer math for the Phase 2 router rework.

Three responsibilities, kept as stateless functions so the unit tests
can exercise them without a full router instance:

* `apply_curve(x, kind, param)` — shape a [0, 1] signal through one
  of the supported curves (linear / power / s_curve).
* `combine(...)` — merge the Depth and Speed channels' shaped values
  into a single pre-smoothing target, honouring per-channel `mode`
  (additive vs modulate) and the per-motor `combine` policy
  (sum vs max).
* `smooth(prev, mixed, dt_ms, attack_ms, release_ms)` — asymmetric
  exponential envelope follower. The caller maintains the per-motor
  `prev` state between ticks.

These functions don't know anything about profiles, devices, or the
parameter store — they take primitive numbers and return primitive
numbers. The router (Cut B) reads the per-motor `mix` config block,
extracts the fields, calls these in order, and pushes the final
target into the engine.

Schema and defaults are documented in ROUTING_REDESIGN.md § Phase 2."""

import math


# ----------------------------------------------------------
# apply_curve
# ----------------------------------------------------------

_POWER_PARAM_MIN = 0.3
_POWER_PARAM_MAX = 3.0
_S_CURVE_ITERS_MIN = 1
_S_CURVE_ITERS_MAX = 8


def apply_curve(x: float, kind: str, param: float = 1.0) -> float:
    """Shape `x` (clamped to [0, 1]) through one of the supported
    curves. Output is always in [0, 1].

    - `linear`: identity. `param` is ignored.
    - `power`: `x ** exp` with `exp` clamped to [0.3, 3.0]. Default
      `1.0` = identity. `exp < 1` boosts low input (sharper response
      near zero); `exp > 1` suppresses low input.
    - `s_curve`: iterated Hermite smoothstep (`3x² - 2x³`) applied N
      times. `param` is rounded and clamped to [1, 8]. N=1 is the
      textbook smoothstep; higher iterations give a sharper sigmoid
      through the midpoint while preserving the endpoints.

    Unknown `kind` falls back to linear (defensive — the UI never
    writes anything else, but bad on-disk profiles shouldn't crash)."""
    x = _clamp_unit(float(x))
    if kind == "power":
        exponent = max(_POWER_PARAM_MIN, min(_POWER_PARAM_MAX, float(param)))
        return x ** exponent
    if kind == "s_curve":
        n = int(max(_S_CURVE_ITERS_MIN,
                    min(_S_CURVE_ITERS_MAX, round(float(param)))))
        for _ in range(n):
            x = x * x * (3.0 - 2.0 * x)
        return x
    # linear / unknown
    return x


# ----------------------------------------------------------
# combine
# ----------------------------------------------------------

def combine(d_shaped: float, s_shaped: float,
            depth_enabled: bool, depth_mode: str,
            speed_enabled: bool, speed_mode: str,
            combine_op: str,
            mod_min: float, mod_max: float) -> float:
    """Merge the two per-channel shaped values into a single
    pre-smoothing target. Output is clamped to [0, 1].

    Disabled channels are treated as not contributing:
    - Both disabled → 0.
    - Only one enabled → that channel's value (clamped).

    With both enabled, the per-channel `mode` decides:
    - One channel `modulate`: that channel scales the *other* (the
      carrier) by `lerp(mod_min, mod_max, modulator_value)`. With the
      default `(0.5, 1.5)` range: the carrier feels at 50% when the
      modulator is 0, 150% at full modulator (clamped to 1.0).
    - Both `additive`: `combine_op` decides. `'sum'` → clamped
      addition; anything else (including `'max'`) → element-wise max.

    Defensive: if both channels somehow end up in `modulate` (UI
    prevents this; on-disk profiles might not), depth's mode wins
    (depth modulates speed)."""
    d_shaped = float(d_shaped) if depth_enabled else 0.0
    s_shaped = float(s_shaped) if speed_enabled else 0.0

    if not depth_enabled and not speed_enabled:
        return 0.0
    if not depth_enabled:
        return _clamp_unit(s_shaped)
    if not speed_enabled:
        return _clamp_unit(d_shaped)

    if depth_mode == "modulate":
        # Depth modulates speed (depth is the modulator, speed the carrier).
        factor = _lerp(mod_min, mod_max, d_shaped)
        out = s_shaped * factor
    elif speed_mode == "modulate":
        # Speed modulates depth.
        factor = _lerp(mod_min, mod_max, s_shaped)
        out = d_shaped * factor
    elif combine_op == "sum":
        out = d_shaped + s_shaped
    else:
        # Default + any unrecognised combine_op falls through to max
        # (the project-wide max-wins convention).
        out = max(d_shaped, s_shaped)
    return _clamp_unit(out)


# ----------------------------------------------------------
# smooth
# ----------------------------------------------------------

def smooth(prev: float, mixed: float, dt_ms: float,
           attack_ms: float, release_ms: float) -> float:
    """Asymmetric exponential envelope follower. Returns the new
    smoothed value given the previous smoothed value, the incoming
    raw mixed value, and the elapsed milliseconds since the last call.

    Rising (`mixed > prev`) uses `attack_ms`; falling uses
    `release_ms`. Either tau at zero (or below) disables that
    direction — the output snaps to `mixed` for that polarity. A
    non-positive `dt_ms` also disables smoothing for safety."""
    prev_f = float(prev)
    mixed_f = float(mixed)
    dt = float(dt_ms)
    tau = float(attack_ms) if mixed_f > prev_f else float(release_ms)
    if tau <= 0.0 or dt <= 0.0:
        return mixed_f
    alpha = 1.0 - math.exp(-dt / tau)
    return prev_f + (mixed_f - prev_f) * alpha


# ----------------------------------------------------------
# tiny helpers (private)
# ----------------------------------------------------------

def _clamp_unit(x: float) -> float:
    if x < 0.0:
        return 0.0
    if x > 1.0:
        return 1.0
    return x


def _lerp(a: float, b: float, t: float) -> float:
    """Linear interpolation between `a` and `b` by `t`. `t` is not
    clamped — callers (modulator math) intentionally pass values that
    may exceed [0, 1] when a channel's `gain > 1`."""
    return a + (b - a) * t
