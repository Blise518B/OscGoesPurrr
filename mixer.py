"""Pure-function mixer math for the motor signal chain.

Stateless helpers that the router composes into the per-motor pipeline:

* `apply_curve(x, kind, param)` — shape a [0, 1] signal through one
  of the supported curves (linear / power / s_curve).
* `combine(d_shaped, s_shaped, op)` — merge the Depth and Speed
  channels with the per-motor combine policy (`add` / `max` /
  `multiply`).
* `activity_meter(prev, signal, dt_s)` — asymmetric EMA over the
  speed-detector output. Time constants are hidden constants so the
  user-facing gate knobs stay in consistent units.
* `activity_gate(prev_open, below_since, meter, now_s, wake, sleep)`
  — gate state machine. Opens instantly when the meter crosses the
  wake threshold; closes after the meter has stayed below for
  `sleep_delay_s` seconds.
* `smooth(prev, mixed, dt_ms, rise_ms, fall_ms)` — asymmetric
  exponential envelope follower. Rising uses `rise_ms`, falling
  uses `fall_ms`.

These functions don't know anything about profiles, devices, or the
parameter store — they take primitive numbers and return primitive
numbers. The router reads the per-motor chain config, extracts the
fields, and calls these in order.

Schema and defaults are documented in docs/MOTOR_SIGNAL_CHAIN.md."""

import math
from typing import Optional, Tuple


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

def combine(d_shaped: float, s_shaped: float, combine_op: str) -> float:
    """Merge the two per-channel shaped values into a single
    pre-gate target. Output is clamped to [0, 1].

    - `add`: clamped addition. Either channel at 0 passes the other
      through unchanged.
    - `max`: element-wise max. Default; matches the "loudest wins"
      convention used across the router.
    - `multiply`: element-wise product. Either channel at 0 forces
      the output to 0 — the diagram makes this visible, no hidden
      bypass.

    Unknown `combine_op` falls back to `max`."""
    d = float(d_shaped)
    s = float(s_shaped)
    if combine_op == "add":
        out = d + s
    elif combine_op == "multiply":
        out = d * s
    else:
        # Default + any unrecognised op falls through to max.
        out = max(d, s)
    return _clamp_unit(out)


def merge_chains(values, op: str) -> float:
    """Merge multiple chain outputs into the final motor target.
    Same semantic family as `combine` but generalised over a list of
    chain post-smoothing values. Output is clamped to [0, 1].

    - Empty list → 0.0 (no chains, no output).
    - Single-element list → that value clamped (no merge needed).
    - 2+: fold with the op:
      * `add`: clamped sum.
      * `max`: element-wise max (default).
      * `multiply`: element-wise product. Any chain at 0 zeros the
        final output — the same "no hidden bypass" semantics as
        combine's multiply.

    The list shape — rather than a fixed 2-arg signature — keeps the
    router clean if the design ever decides to allow 3+ chains.
    The doc currently caps at 2 in the UI, but the math is N-safe.
    Unknown `op` falls back to `max`."""
    if not values:
        return 0.0
    if len(values) == 1:
        return _clamp_unit(float(values[0]))
    result = float(values[0])
    for v in values[1:]:
        v = float(v)
        if op == "add":
            result = result + v
        elif op == "multiply":
            result = result * v
        else:
            # Default + any unrecognised op falls through to max.
            if v > result:
                result = v
    return _clamp_unit(result)


# ----------------------------------------------------------
# activity meter + gate
# ----------------------------------------------------------

# Default time constants for the activity meter. These used to be
# hidden (locked) constants; they are now the fallbacks for the
# per-chain `gate.attack_s` / `gate.release_s` knobs. The defaults
# preserve the original feel: attack fast so new movement registers
# immediately; release slow so brief stillness does not instantly
# drop the meter below threshold. Raising attack makes the gate
# demand *sustained* movement before it wakes (a slow "budget"
# build-up); raising release makes the meter coast down over seconds
# instead of collapsing between strokes.
_ACTIVITY_ATTACK_TAU_S = 0.05
_ACTIVITY_RELEASE_TAU_S = 0.50

# Floor for either tau. `1 - exp(-dt/tau)` with tau at or below a
# router tick is already "instant"; allowing 0 would divide by zero.
_ACTIVITY_TAU_MIN_S = 0.01


def activity_meter(prev: float, signal: float, dt_s: float,
                   attack_tau_s: float = _ACTIVITY_ATTACK_TAU_S,
                   release_tau_s: float = _ACTIVITY_RELEASE_TAU_S) -> float:
    """Asymmetric EMA on the speed-detector output, clamped to
    `[0, 1]` (anti-windup). Returns the new meter value given the
    previous meter, the current speed signal, and the elapsed
    seconds since the last update.

    Rising uses `attack_tau_s` (default 50 ms), falling uses
    `release_tau_s` (default 500 ms); both are floored at
    `_ACTIVITY_TAU_MIN_S`. A non-positive `dt_s` returns `prev`
    unchanged — no integration can happen in zero elapsed time, and
    clock-rewind shouldn't blow up the meter."""
    prev_f = float(prev)
    sig = _clamp_unit(float(signal))
    dt = float(dt_s)
    if dt <= 0.0:
        return prev_f
    if sig > prev_f:
        tau = max(_ACTIVITY_TAU_MIN_S, float(attack_tau_s))
    else:
        tau = max(_ACTIVITY_TAU_MIN_S, float(release_tau_s))
    alpha = 1.0 - math.exp(-dt / tau)
    new = prev_f + (sig - prev_f) * alpha
    return _clamp_unit(new)


def activity_gate(prev_open: bool,
                  below_since: Optional[float],
                  meter: float,
                  now_s: float,
                  wake_threshold: float,
                  sleep_delay_s: float) -> Tuple[bool, Optional[float]]:
    """Update the activity gate's open/closed state.

    Returns `(new_open, new_below_since)`. `below_since` is the wall
    time when the meter most recently dropped below `wake_threshold`
    while the gate was open, or `None` if the meter has been at-or-
    above threshold (or the gate has been closed).

    Transitions:
    - Closed + meter ≥ threshold → open (instant). `below_since` reset
      to `None`.
    - Closed + meter < threshold → stays closed. `below_since` stays
      `None` (irrelevant while closed).
    - Open + meter ≥ threshold → stays open. `below_since` reset to
      `None` (the meter recovered).
    - Open + meter < threshold:
      - `below_since is None` → start counting: `below_since = now_s`.
      - Else if `now_s - below_since ≥ sleep_delay_s` → close gate.
      - Else → stays open, still counting.

    A `sleep_delay_s ≤ 0` makes the gate close immediately when the
    meter dips below threshold."""
    above = float(meter) >= float(wake_threshold)
    if above:
        return True, None
    # below threshold
    if not prev_open:
        return False, None
    # gate is open, meter has just gone (or stayed) below threshold
    if below_since is None:
        below_since = float(now_s)
    elapsed = float(now_s) - float(below_since)
    if elapsed >= float(sleep_delay_s):
        return False, None
    return True, below_since


# ----------------------------------------------------------
# smooth
# ----------------------------------------------------------

# Snap-to-target threshold for the exponential follower. Pure
# `prev + (mixed-prev)*alpha` decays toward the target but never
# reaches it — a `1.0 → 0.0` fall at the default 300 ms release
# tau (90 Hz tick) is still at ~0.005 after 1.6 s and ~0.001 after
# 2.1 s. Toy hardware that quantizes floats to integer command
# steps can hold that residue as a faint motor command, so the
# user feels a "stuck" buzz long after the input signal stopped.
# Snapping to target inside the epsilon kills the floating-point
# tail without changing the audible envelope shape — 0.5% is well
# below any common toy's perceivable step (Lovense quantizes to
# 5% steps, bHaptics to 1%).
_SMOOTH_SNAP_EPSILON = 0.005


def smooth(prev: float, mixed: float, dt_ms: float,
           rise_ms: float, fall_ms: float) -> float:
    """Asymmetric exponential envelope follower. Returns the new
    smoothed value given the previous smoothed value, the incoming
    raw mixed value, and the elapsed milliseconds since the last call.

    Rising (`mixed > prev`) uses `rise_ms`; falling uses `fall_ms`.
    Either tau at zero (or below) disables that direction — the
    output snaps to `mixed` for that polarity. A non-positive
    `dt_ms` also disables smoothing for safety.

    Gate transitions step the input from `combined` to 0 (close) or
    0 to `combined` (open). Because closes are falling and opens are
    rising, `fall_ms` rounds the close and `rise_ms` rounds the open
    — the rise/fall knobs the user already tuned automatically handle
    gate transitions without a separate set of constants.

    Rate independence: `rise_ms` and `fall_ms` are wall-clock time
    constants. The `1 - exp(-dt/tau)` factor compensates for the
    elapsed interval, so the perceived envelope shape is identical at
    any sampling rate. Never recalibrate these values when the
    router's tick rate changes.

    Tail snap: once the smoothed value is within `_SMOOTH_SNAP_EPSILON`
    of the target, return the target exactly. Without this, the
    floating-point residue from exponential decay holds a faint motor
    command for seconds after the input stopped."""
    prev_f = float(prev)
    mixed_f = float(mixed)
    dt = float(dt_ms)
    tau = float(rise_ms) if mixed_f > prev_f else float(fall_ms)
    if tau <= 0.0 or dt <= 0.0:
        return mixed_f
    alpha = 1.0 - math.exp(-dt / tau)
    new = prev_f + (mixed_f - prev_f) * alpha
    if abs(new - mixed_f) < _SMOOTH_SNAP_EPSILON:
        return mixed_f
    return new


# ----------------------------------------------------------
# sample_pattern — parametric simulator generator (Cut 7).
# Replaces the preset-zoo pattern generator with a frequency + amp
# + waveform sampler. See docs/CHAIN_INLINED_TUNING.md § "Simulator panel"
# for the locked design.
# ----------------------------------------------------------

# Known waveform identifiers — kept here so consumers (UI dropdowns)
# can import a single source of truth.
WAVEFORMS = ("sine", "square", "triangle", "sawtooth")


def sample_pattern(freq_hz: float, amp: float, waveform: str,
                   t_s: float) -> float:
    """Compute one sample of a parametric periodic signal at time
    `t_s` seconds, frequency `freq_hz`, amplitude `amp`, in waveform
    `waveform`. Output is normalised to `[0, amp]` (not `[-amp, +amp]`)
    because `d_raw` is unsigned by convention in this codebase.

    Waveforms:
      * `sine`     — shifted sine, `0` at φ=0, peak `amp` at φ=0.5.
      * `square`   — `amp` for the first half of the cycle, `0` for the second.
      * `triangle` — ramp up to `amp` at φ=0.5, back to `0` at φ=1.
      * `sawtooth` — linear ramp `0` → `amp` over the cycle.

    Edge cases:
      * `freq_hz <= 0` → returns `0.0` (no oscillation).
      * Negative `amp` → wraps at the math; not clamped here (the
        caller's chain pipeline does its own clamping downstream).
      * Unknown `waveform` → returns `0.0` (silence — defensive).
      * `t_s` may be any real number; the phase calculation uses
        `% 1.0` so negative or large `t_s` values still produce a
        sensible phase in `[0, 1)`.

    Pure function — no state, safe to call from any thread."""
    if freq_hz <= 0.0:
        return 0.0
    phase = (float(freq_hz) * float(t_s)) % 1.0
    if waveform == "sine":
        # sin(2πφ) ∈ [-1, 1] → shifted/scaled to [0, 1] then * amp.
        return float(amp) * (0.5 + 0.5 * math.sin(2.0 * math.pi * phase))
    if waveform == "square":
        return float(amp) if phase < 0.5 else 0.0
    if waveform == "triangle":
        # /\ peak at φ=0.5
        if phase < 0.5:
            return float(amp) * (2.0 * phase)
        return float(amp) * (2.0 * (1.0 - phase))
    if waveform == "sawtooth":
        # / ramp 0→amp over the cycle
        return float(amp) * phase
    return 0.0


# ----------------------------------------------------------
# tiny helpers (private)
# ----------------------------------------------------------

def _clamp_unit(x: float) -> float:
    if x < 0.0:
        return 0.0
    if x > 1.0:
        return 1.0
    return x
