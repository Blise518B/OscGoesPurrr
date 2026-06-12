"""Per-feature physics models for linear actuators.

Pure simulation classes — no asyncio, no buttplug. The HapticEngine ticks these
every engine loop to integrate a routed 0-1 level into the current stroke
*position* (0-1). Each `tick()` returns where the sleeve should be *now*; the
engine owns send cadence and the commanded interpolation `duration` (see
`compute_send_duration_ms` and the linear branch of `HapticEngine.async_worker`).

Keeping integration here and send policy in the engine is what lets the physics
run smooth at the full loop rate while the actual hardware sends stay rate-capped
— a linear toy reaches the commanded position then HOLDS, so a coarse, send-rate
integration is exactly what made slow motion "step".

Used for hardware that supports position-with-duration (Lovense Solace Pro,
Gravity, OSR2, The Handy, ...).
"""

import math


# Default linear-actuator config -- mirrors OscGoesBrrr getDefaultLinearActuatorConfig()
# in src/common/configTypes.ts.
LINEAR_DEFAULTS = {
    "max_v": 3.0,             # max velocity in normalized position units / second
    "max_a": 20.0,            # max acceleration in units / second^2
    "resting_pos": 0.0,       # position the actuator returns to when idle
    "resting_time_s": 3.0,    # seconds of zero level before returning to resting_pos
    "min_pos": 0.0,           # minimum stroke position (after remap)
    "max_pos": 1.0,           # maximum stroke position (after remap)
}


class LinearActuator:
    """Per-feature position integrator for a linear actuator.

    Port of the linear branch in OscGoesBrrr's BridgeOutput.pushToBio
    (src/main/bridge.ts). Call `tick(level, now_ms)` once per engine loop; it
    advances the velocity/acceleration-limited physics and returns the current
    stroke position (0-1). Send cadence and the commanded interpolation
    `duration` are the engine's responsibility, not this model's.
    """

    def __init__(self, **config) -> None:
        merged = {**LINEAR_DEFAULTS, **config}
        self.max_v: float = merged["max_v"]
        self.max_a: float = merged["max_a"]
        self.resting_pos: float = merged["resting_pos"]
        self.resting_time_ms: float = merged["resting_time_s"] * 1000.0
        self.min_pos: float = merged["min_pos"]
        self.max_pos: float = merged["max_pos"]

        self.last_position: float = 0.0
        self.velocity: float = 0.0
        self.last_target: float = 0.0
        self.last_push_time_ms: float = 0.0
        # Initialize to -inf so the resting-return branch engages on the very
        # first tick at level=0, regardless of the caller's clock origin. (OGB
        # gets the same effect from Date.now() being a huge absolute number.)
        self.last_suck_time_ms: float = float("-inf")

    def tick(self, level: float, now_ms: float, idle_mode: str = "rest") -> float:
        """Advance the physics by one loop and return the current 0-1 position."""
        # Safety-limited tick interval (matches OGB's clamp(timeDeltaReal, 0, 250)).
        time_delta = max(0.0, min(250.0, now_ms - self.last_push_time_ms))
        time_delta_s = time_delta / 1000.0
        old_velocity = self.velocity
        max_v = self.max_v
        max_a = self.max_a

        # High level => low position ("sucked in"). Remap into the [min,max] stroke.
        clamped_level = max(0.0, min(1.0, level))
        target = 1.0 - clamped_level
        target = self.min_pos + target * (self.max_pos - self.min_pos)

        if clamped_level > 0:
            self.last_suck_time_ms = now_ms
        elif idle_mode == "rest":
            if self.last_suck_time_ms < now_ms - self.resting_time_ms:
                # Resting timeout: snap back toward the resting position.
                target = max(0.0, min(1.0, self.resting_pos))
                max_a = 999.0
                max_v = max(0.0, min(1.0, max_v))
            # else: target stays at 1.0 (top of stroke) during the grace period --
            # this is OGB's stroke-and-return feel.
        else:
            # idle_mode == "hold": freeze at the current position when level==0.
            target = self.last_position

        target = max(0.0, min(1.0, target))
        current = self.last_position

        # How far we'd travel if we decelerated to zero right now.
        if max_a > 0:
            stop_distance = (old_velocity * old_velocity) / (2.0 * max_a)
        else:
            stop_distance = 0.0
        stop_pos = current + (-1.0 if old_velocity < 0 else 1.0) * stop_distance
        from_stop_to_target = target - stop_pos

        # New velocity if we accelerate vs decelerate this tick.
        v_add = old_velocity + max_a * time_delta_s
        v_sub = old_velocity - max_a * time_delta_s
        if abs(v_add) > max_v:
            v_add = (1.0 if v_add > 0 else -1.0) * max_v
        if abs(v_sub) > max_v:
            v_sub = (1.0 if v_sub > 0 else -1.0) * max_v

        pos_add = current + v_add * time_delta_s
        pos_sub = current + v_sub * time_delta_s

        if target == pos_add:
            new_velocity = v_add
        elif target == pos_sub:
            new_velocity = v_sub
        elif (pos_add < target) != (pos_sub < target):
            # Target lies between the accel and decel trajectories -- lock onto it.
            new_velocity = (target - current) / time_delta_s if time_delta_s > 0 else 0.0
        else:
            new_velocity = v_add if from_stop_to_target > 0 else v_sub

        new_position = current + new_velocity * time_delta_s
        if new_position > 1.0:
            new_position = 1.0
            new_velocity = 0.0
        if new_position < 0.0:
            new_position = 0.0
            new_velocity = 0.0

        self.velocity = new_velocity
        self.last_target = target
        self.last_push_time_ms = now_ms
        self.last_position = new_position
        return new_position


STROKE_SPEED_DEFAULTS = {
    "max_strokes_per_sec": 2.5,   # full in-out cycles per second at level=1
    "min_pos": 0.0,
    "max_pos": 1.0,
    "resting_pos": 0.0,
    "resting_time_s": 3.0,
}


class StrokeSpeedActuator:
    """Per-feature continuous-oscillator for "speed mode" on linear actuators.

    Unlike `LinearActuator`, this one ignores depth and instead generates a sine-wave
    stroke pattern whose frequency is scaled by the routed 0-1 level. Level=0 means
    no stroking; level=1 means `max_strokes_per_sec` full in-out cycles per second.
    Each `tick()` returns the current 0-1 position; the engine owns send cadence and
    the commanded interpolation `duration`.

    `idle_mode` (passed to `tick`):
      - "rest": after `resting_time_s` of zero level, drift toward `resting_pos`
      - "hold": freeze at the last commanded position when level=0
    """

    def __init__(self, **config) -> None:
        merged = {**STROKE_SPEED_DEFAULTS, **config}
        self.max_strokes_per_sec: float = merged["max_strokes_per_sec"]
        self.min_pos: float = merged["min_pos"]
        self.max_pos: float = merged["max_pos"]
        self.resting_pos: float = merged["resting_pos"]
        self.resting_time_ms: float = merged["resting_time_s"] * 1000.0

        self.phase: float = 0.0          # 0..1, wraps; current position in the sine cycle
        self.last_position: float = 0.0
        self.last_push_time_ms: float = 0.0
        # Initialize to -inf so the "rest" branch can engage on the very first idle tick
        # regardless of the caller's clock origin (same defensive trick as LinearActuator).
        self.last_active_time_ms: float = float("-inf")

    def tick(self, level: float, now_ms: float, idle_mode: str = "rest") -> float:
        """Advance the oscillator by one loop and return the current 0-1 position."""
        dt_real_ms = max(0.0, min(250.0, now_ms - self.last_push_time_ms))
        dt_s = dt_real_ms / 1000.0
        clamped = max(0.0, min(1.0, level))
        self.last_push_time_ms = now_ms

        if clamped > 0:
            self.last_active_time_ms = now_ms
            rate_hz = clamped * self.max_strokes_per_sec
            self.phase = (self.phase + rate_hz * dt_s) % 1.0

            # Half-cosine wave: phase 0 -> min, phase 0.5 -> max, phase 1 -> min again.
            normalized = (1.0 - math.cos(2.0 * math.pi * self.phase)) * 0.5
            new_position = self.min_pos + normalized * (self.max_pos - self.min_pos)
            self.last_position = max(0.0, min(1.0, new_position))
            return self.last_position

        # level == 0 from here.
        if idle_mode == "rest" and self.last_active_time_ms < now_ms - self.resting_time_ms:
            # Resting timeout: settle at the resting position.
            self.last_position = max(0.0, min(1.0, self.resting_pos))
        # Otherwise (still in the grace period, already resting, or idle "hold"):
        # freeze in place and hold the last position.
        return self.last_position


def compute_send_duration_ms(
    interval_ms: float,
    overlap: float,
    min_interval_ms: float,
    max_interval_ms: float,
) -> int:
    """Commanded interpolation duration (ms) for a linear `position+duration` send.

    A stroker moves to the commanded position then HOLDS there until the next
    command arrives, so to avoid "stepping" the duration must cover the gap until
    that next command *with margin*. Given the measured `interval_ms` since our
    last send, clamp it to a sane band (`min_interval_ms`..`max_interval_ms`, so a
    post-idle gap can't command a sluggish multi-hundred-ms move) and scale by
    `overlap` (> 1) so the device is still travelling toward the target when the
    next position lands. Returns whole milliseconds, floored at 1.
    """
    clamped = max(min_interval_ms, min(interval_ms, max_interval_ms))
    return max(1, int(round(clamped * overlap)))
