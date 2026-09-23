"""Tests for the linear-actuator physics models (haptic_actuators.py).

Pure simulation — no engine, no buttplug, no hardware. Covers the decoupled
design where each `tick()` integrates one engine loop and returns the *current*
0-1 stroke position (the engine owns send cadence + interpolation `duration`),
plus the pure `compute_send_duration_ms` helper that sizes that duration.
"""

import pytest

from haptic_actuators import (
    LinearActuator,
    StrokeSpeedActuator,
    compute_send_duration_ms,
)


def _drive(actuator, level, idle, *, start_ms=10.0, ticks=100, dt_ms=10.0):
    """Tick `actuator` `ticks` times at `dt_ms` spacing; return the list of
    returned positions. Starts at a small `start_ms` so the first tick's dt is
    `dt_ms` (the model clamps an initial huge dt to 250 ms, which we avoid)."""
    out = []
    now = float(start_ms)
    for _ in range(ticks):
        out.append(actuator.tick(level, now, idle_mode=idle))
        now += dt_ms
    return out


class TestComputeSendDurationMs:
    def test_scales_by_overlap(self):
        # Steady ~20 ms gap, 2x overlap -> 40 ms commanded duration.
        assert compute_send_duration_ms(20.0, 2.0, 16.0, 60.0) == 40

    def test_clamps_to_min_interval(self):
        # A sub-cap gap is floored to the min interval before scaling.
        assert compute_send_duration_ms(5.0, 2.0, 16.0, 60.0) == 32

    def test_clamps_to_max_interval(self):
        # A huge post-idle gap is capped so the move isn't sluggish.
        assert compute_send_duration_ms(5000.0, 2.0, 16.0, 60.0) == 120

    def test_floored_at_one_ms(self):
        assert compute_send_duration_ms(0.0, 0.0, 0.0, 0.0) == 1

    def test_returns_int(self):
        assert isinstance(compute_send_duration_ms(20.0, 1.7, 16.0, 60.0), int)


class TestLinearActuator:
    def test_tick_returns_float_in_range(self):
        act = LinearActuator()
        pos = act.tick(0.5, 10.0)
        assert isinstance(pos, float)
        assert 0.0 <= pos <= 1.0

    def test_converges_to_min_pos_when_fully_sucked(self):
        # level=1 -> target = min_pos (top of "sucked in"); start at 0 so it moves.
        act = LinearActuator(min_pos=0.2, max_pos=0.8)
        positions = _drive(act, 1.0, "rest", ticks=200)
        assert positions[-1] == pytest.approx(0.2, abs=0.01)

    def test_converges_to_max_pos_within_grace(self):
        # After a recent "suck", level=0 (still inside resting grace) targets max_pos.
        act = LinearActuator(min_pos=0.2, max_pos=0.8, resting_time_s=3.0)
        _drive(act, 1.0, "rest", start_ms=10.0, ticks=50)          # establish a suck
        positions = _drive(act, 0.0, "rest", start_ms=600.0, ticks=120)
        assert positions[-1] == pytest.approx(0.8, abs=0.01)

    def test_motion_is_smooth_no_giant_jumps(self):
        # The whole point of ticking every loop: per-tick position deltas are
        # bounded by max_v * dt (no coarse, send-rate-sized steps).
        act = LinearActuator(min_pos=0.2, max_pos=0.8, max_v=3.0)  # 3.0/s * 0.01s = 0.03
        positions = _drive(act, 1.0, "rest", ticks=200, dt_ms=10.0)
        deltas = [abs(b - a) for a, b in zip(positions, positions[1:])]
        assert max(deltas) <= 0.032

    def test_resting_return_after_timeout(self):
        # Long idle in "rest" drifts back to resting_pos.
        act = LinearActuator(resting_pos=0.5, resting_time_s=1.0)
        _drive(act, 1.0, "rest", start_ms=10.0, ticks=20)          # suck first
        positions = _drive(act, 0.0, "rest", start_ms=300.0, ticks=1500)
        assert positions[-1] == pytest.approx(0.5, abs=0.02)

    def test_idle_hold_freezes_position(self):
        act = LinearActuator()
        _drive(act, 1.0, "rest", start_ms=10.0, ticks=30)          # move somewhere
        frozen = _drive(act, 0.0, "hold", start_ms=400.0, ticks=20)
        assert frozen[-1] == pytest.approx(frozen[0], abs=1e-9)


class TestStrokeSpeedActuator:
    def test_oscillates_within_stroke_range(self):
        act = StrokeSpeedActuator(min_pos=0.2, max_pos=0.8, max_strokes_per_sec=2.0)
        positions = _drive(act, 1.0, "rest", ticks=120, dt_ms=10.0)  # ~2.4 cycles
        assert min(positions) >= 0.2 - 1e-6
        assert max(positions) <= 0.8 + 1e-6
        assert (max(positions) - min(positions)) > 0.4   # it actually swings

    def test_tick_returns_float(self):
        act = StrokeSpeedActuator()
        assert isinstance(act.tick(0.5, 10.0), float)

    def test_higher_level_strokes_faster(self):
        # Short window so neither phase wraps past 1.0 (fast = 0.4, slow = 0.1).
        fast = StrokeSpeedActuator(max_strokes_per_sec=2.0)
        slow = StrokeSpeedActuator(max_strokes_per_sec=2.0)
        _drive(fast, 1.0, "rest", ticks=20)
        _drive(slow, 0.25, "rest", ticks=20)
        assert fast.phase > slow.phase   # same window, more phase advanced

    def test_idle_hold_freezes(self):
        act = StrokeSpeedActuator(max_strokes_per_sec=2.0)
        _drive(act, 1.0, "rest", start_ms=10.0, ticks=15)
        frozen = _drive(act, 0.0, "hold", start_ms=300.0, ticks=20)
        assert frozen[-1] == pytest.approx(frozen[0], abs=1e-9)

    def test_resting_return_after_timeout(self):
        act = StrokeSpeedActuator(resting_pos=0.5, resting_time_s=1.0)
        _drive(act, 1.0, "rest", start_ms=10.0, ticks=15)          # be active first
        # One tick well past the resting timeout snaps to resting_pos.
        pos = act.tick(0.0, 5000.0, idle_mode="rest")
        assert pos == pytest.approx(0.5, abs=1e-9)
