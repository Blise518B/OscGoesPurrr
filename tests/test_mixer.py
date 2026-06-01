"""Tests for the pure-function mixer in `mixer.py`.

These functions are stateless; the router maintains per-motor
prev-state outside of them. Each function is tested in isolation
against the math documented in docs/MOTOR_SIGNAL_CHAIN.md."""

import math

import pytest

from mixer import (
    apply_curve, combine, smooth, activity_meter, activity_gate, merge_chains,
    sample_pattern, WAVEFORMS,
)


# ============================================================ apply_curve

class TestApplyCurveLinear:

    @pytest.mark.parametrize("x", [0.0, 0.1, 0.25, 0.5, 0.75, 0.9, 1.0])
    def test_identity(self, x):
        assert apply_curve(x, "linear", 1.0) == pytest.approx(x)

    @pytest.mark.parametrize("param", [0.0, 0.5, 1.0, 2.0, 5.0])
    def test_ignores_param(self, param):
        assert apply_curve(0.5, "linear", param) == pytest.approx(0.5)


class TestApplyCurvePower:

    @pytest.mark.parametrize("x", [0.0, 0.25, 0.5, 0.75, 1.0])
    def test_exponent_1_is_identity(self, x):
        assert apply_curve(x, "power", 1.0) == pytest.approx(x)

    def test_exponent_below_1_boosts_low_input(self):
        # power(0.5) = sqrt; sqrt(0.25) = 0.5, sqrt(0.5) ≈ 0.707
        assert apply_curve(0.25, "power", 0.5) == pytest.approx(0.5)
        assert apply_curve(0.5, "power", 0.5) == pytest.approx(math.sqrt(0.5))

    def test_exponent_above_1_suppresses_low_input(self):
        # power(2) squares; 0.5² = 0.25, 0.7² = 0.49
        assert apply_curve(0.5, "power", 2.0) == pytest.approx(0.25)
        assert apply_curve(0.7, "power", 2.0) == pytest.approx(0.49)

    def test_exponent_clamps_below_lower_bound(self):
        # exponent 0.1 should clamp to 0.3
        clamped = apply_curve(0.5, "power", 0.1)
        expected = 0.5 ** 0.3
        assert clamped == pytest.approx(expected)

    def test_exponent_clamps_above_upper_bound(self):
        # exponent 10 should clamp to 3.0
        clamped = apply_curve(0.5, "power", 10.0)
        expected = 0.5 ** 3.0
        assert clamped == pytest.approx(expected)

    def test_endpoints_preserved(self):
        # x = 0 and x = 1 are fixed points of x ** exp for any exp > 0
        for exp in (0.3, 1.0, 2.0, 3.0):
            assert apply_curve(0.0, "power", exp) == pytest.approx(0.0)
            assert apply_curve(1.0, "power", exp) == pytest.approx(1.0)


class TestApplyCurveS:

    def test_endpoints(self):
        # Smoothstep(0) = 0, Smoothstep(1) = 1; iterating preserves these.
        for n in (1, 2, 3, 8):
            assert apply_curve(0.0, "s_curve", n) == pytest.approx(0.0)
            assert apply_curve(1.0, "s_curve", n) == pytest.approx(1.0)

    def test_midpoint_is_half(self):
        # 3·0.25 - 2·0.125 = 0.75 - 0.25 = 0.5; symmetric, iteration-stable.
        for n in (1, 2, 3, 8):
            assert apply_curve(0.5, "s_curve", n) == pytest.approx(0.5)

    def test_more_iterations_sharpen_low_input(self):
        # Below 0.5 the curve pulls toward 0; more iterations pull harder.
        v1 = apply_curve(0.3, "s_curve", 1)
        v2 = apply_curve(0.3, "s_curve", 2)
        v3 = apply_curve(0.3, "s_curve", 4)
        assert v1 > v2 > v3 > 0.0

    def test_more_iterations_sharpen_high_input(self):
        # Symmetric: above 0.5 the curve pulls toward 1.
        v1 = apply_curve(0.7, "s_curve", 1)
        v2 = apply_curve(0.7, "s_curve", 2)
        v3 = apply_curve(0.7, "s_curve", 4)
        assert v1 < v2 < v3 < 1.0

    def test_iteration_count_clamps_low(self):
        # 0 iterations clamps to 1.
        assert apply_curve(0.3, "s_curve", 0) == pytest.approx(
            apply_curve(0.3, "s_curve", 1)
        )

    def test_iteration_count_clamps_high(self):
        # 100 iterations clamps to 8.
        assert apply_curve(0.3, "s_curve", 100) == pytest.approx(
            apply_curve(0.3, "s_curve", 8)
        )

    def test_iteration_count_rounds(self):
        # Float params are rounded.
        assert apply_curve(0.3, "s_curve", 2.4) == pytest.approx(
            apply_curve(0.3, "s_curve", 2)
        )
        assert apply_curve(0.3, "s_curve", 2.6) == pytest.approx(
            apply_curve(0.3, "s_curve", 3)
        )


class TestApplyCurveDefensive:

    @pytest.mark.parametrize("kind", ["linear", "power", "s_curve"])
    def test_input_below_zero_clamps_to_zero(self, kind):
        assert apply_curve(-0.5, kind, 1.0) == pytest.approx(0.0)
        assert apply_curve(-100.0, kind, 1.0) == pytest.approx(0.0)

    @pytest.mark.parametrize("kind", ["linear", "power", "s_curve"])
    def test_input_above_one_clamps_to_one(self, kind):
        assert apply_curve(1.5, kind, 1.0) == pytest.approx(1.0)
        assert apply_curve(100.0, kind, 1.0) == pytest.approx(1.0)

    def test_unknown_kind_falls_back_to_linear(self):
        assert apply_curve(0.5, "unknown_curve", 1.0) == pytest.approx(0.5)
        assert apply_curve(0.5, "", 1.0) == pytest.approx(0.5)
        assert apply_curve(0.5, "power_log", 1.0) == pytest.approx(0.5)


# ============================================================ combine

class TestCombineAdd:

    def test_adds_normally(self):
        assert combine(0.3, 0.4, "add") == pytest.approx(0.7)

    def test_zero_left_passes_right(self):
        assert combine(0.0, 0.6, "add") == pytest.approx(0.6)

    def test_zero_right_passes_left(self):
        assert combine(0.7, 0.0, "add") == pytest.approx(0.7)

    def test_clamps_overflow(self):
        assert combine(0.6, 0.7, "add") == pytest.approx(1.0)
        assert combine(1.0, 1.0, "add") == pytest.approx(1.0)


class TestCombineMax:

    def test_picks_higher(self):
        assert combine(0.3, 0.7, "max") == pytest.approx(0.7)
        assert combine(0.9, 0.4, "max") == pytest.approx(0.9)
        assert combine(0.5, 0.5, "max") == pytest.approx(0.5)

    def test_zero_channel_does_not_dominate(self):
        # Max passes the non-zero channel through unchanged.
        assert combine(0.0, 0.6, "max") == pytest.approx(0.6)
        assert combine(0.7, 0.0, "max") == pytest.approx(0.7)


class TestCombineMultiply:

    def test_product(self):
        assert combine(0.5, 0.5, "multiply") == pytest.approx(0.25)
        assert combine(0.8, 0.5, "multiply") == pytest.approx(0.4)

    def test_zero_channel_zeroes_output(self):
        # Locked behavior per docs/MOTOR_SIGNAL_CHAIN.md "Multiply + zero
        # channel": no hidden bypass. The diagram makes this visible.
        assert combine(0.0, 0.9, "multiply") == 0.0
        assert combine(0.9, 0.0, "multiply") == 0.0
        assert combine(0.0, 0.0, "multiply") == 0.0

    def test_one_channel_passes_other(self):
        # Symmetric pass-through when the other channel is at unity.
        assert combine(1.0, 0.6, "multiply") == pytest.approx(0.6)
        assert combine(0.6, 1.0, "multiply") == pytest.approx(0.6)


class TestCombineDefensive:

    def test_unknown_op_falls_back_to_max(self):
        assert combine(0.3, 0.7, "unknown_op") == pytest.approx(0.7)
        assert combine(0.5, 0.5, "") == pytest.approx(0.5)

    def test_output_always_in_unit_interval(self):
        # Extreme positive inputs.
        assert 0.0 <= combine(1.5, 1.5, "add") <= 1.0
        # Extreme negative inputs (shouldn't happen but defensive).
        assert 0.0 <= combine(-0.5, -0.5, "add") <= 1.0


# ============================================================ merge_chains

class TestMergeChainsBoundary:

    def test_empty_list_returns_zero(self):
        assert merge_chains([], "max") == 0.0
        assert merge_chains([], "add") == 0.0
        assert merge_chains([], "multiply") == 0.0

    def test_single_value_passes_through_clamped(self):
        assert merge_chains([0.3], "max") == pytest.approx(0.3)
        assert merge_chains([0.7], "add") == pytest.approx(0.7)
        assert merge_chains([0.5], "multiply") == pytest.approx(0.5)
        # Out-of-range single-element clamps.
        assert merge_chains([1.5], "max") == 1.0
        assert merge_chains([-0.5], "max") == 0.0


class TestMergeChainsAdd:

    def test_two_chains_sum(self):
        assert merge_chains([0.3, 0.4], "add") == pytest.approx(0.7)

    def test_clamps_overflow(self):
        assert merge_chains([0.7, 0.6], "add") == pytest.approx(1.0)
        assert merge_chains([1.0, 1.0], "add") == pytest.approx(1.0)


class TestMergeChainsMax:

    def test_picks_higher(self):
        assert merge_chains([0.3, 0.7], "max") == pytest.approx(0.7)
        assert merge_chains([0.9, 0.4], "max") == pytest.approx(0.9)

    def test_default_for_unknown_op(self):
        assert merge_chains([0.3, 0.7], "garbage") == pytest.approx(0.7)


class TestMergeChainsMultiply:

    def test_product(self):
        assert merge_chains([0.5, 0.5], "multiply") == pytest.approx(0.25)

    def test_zero_chain_zeros_output(self):
        # Locked semantics — same as combine's multiply: no hidden bypass.
        assert merge_chains([0.0, 0.9], "multiply") == 0.0
        assert merge_chains([0.9, 0.0], "multiply") == 0.0


# ============================================================ sample_pattern

class TestSamplePatternEdge:

    def test_zero_freq_returns_zero(self):
        # No oscillation at zero or negative frequency.
        assert sample_pattern(0.0, 1.0, "sine", 0.5) == 0.0
        assert sample_pattern(-1.0, 1.0, "sine", 0.5) == 0.0

    def test_unknown_waveform_returns_zero(self):
        assert sample_pattern(1.0, 1.0, "noise", 0.5) == 0.0
        assert sample_pattern(1.0, 1.0, "", 0.5) == 0.0

    def test_known_waveforms_covered_by_constant(self):
        # Sanity: the public WAVEFORMS tuple matches what we test.
        assert set(WAVEFORMS) == {"sine", "square", "triangle", "sawtooth"}


class TestSamplePatternSine:

    def test_starts_at_midpoint(self):
        # sin(0) = 0 → shifted/scaled → 0.5 * amp.
        assert sample_pattern(1.0, 1.0, "sine", 0.0) == pytest.approx(0.5)
        assert sample_pattern(1.0, 0.6, "sine", 0.0) == pytest.approx(0.3)

    def test_peak_at_quarter_period(self):
        # sin(π/2) = 1 → 1.0 * amp. At freq=1 Hz, quarter period = 0.25 s.
        assert sample_pattern(1.0, 1.0, "sine", 0.25) == pytest.approx(1.0)

    def test_trough_at_three_quarters_period(self):
        # sin(3π/2) = -1 → 0.0 * amp.
        assert sample_pattern(1.0, 1.0, "sine", 0.75) == pytest.approx(0.0, abs=1e-9)

    def test_returns_to_midpoint_after_full_period(self):
        assert sample_pattern(1.0, 1.0, "sine", 1.0) == pytest.approx(0.5)


class TestSamplePatternSquare:

    def test_high_first_half(self):
        assert sample_pattern(1.0, 1.0, "square", 0.0) == 1.0
        assert sample_pattern(1.0, 1.0, "square", 0.25) == 1.0
        assert sample_pattern(1.0, 0.7, "square", 0.25) == pytest.approx(0.7)

    def test_low_second_half(self):
        assert sample_pattern(1.0, 1.0, "square", 0.5) == 0.0
        assert sample_pattern(1.0, 1.0, "square", 0.75) == 0.0


class TestSamplePatternTriangle:

    def test_starts_at_zero(self):
        assert sample_pattern(1.0, 1.0, "triangle", 0.0) == 0.0

    def test_peak_at_half_period(self):
        assert sample_pattern(1.0, 1.0, "triangle", 0.5) == pytest.approx(1.0)

    def test_returns_to_zero_at_end_of_period(self):
        # At φ=1.0 the modulo wraps to 0 → ramp starts again at 0.
        assert sample_pattern(1.0, 1.0, "triangle", 1.0) == 0.0

    def test_linear_ramp_up(self):
        # At quarter-cycle, should be half of amp on the way up.
        assert sample_pattern(1.0, 1.0, "triangle", 0.25) == pytest.approx(0.5)

    def test_linear_ramp_down(self):
        # At three-quarter-cycle, should be half of amp on the way down.
        assert sample_pattern(1.0, 1.0, "triangle", 0.75) == pytest.approx(0.5)


class TestSamplePatternSawtooth:

    def test_starts_at_zero(self):
        assert sample_pattern(1.0, 1.0, "sawtooth", 0.0) == 0.0

    def test_ramps_linearly_to_amp(self):
        # Just before φ=1, value ≈ amp; modulo wraps at exactly 1.
        assert sample_pattern(1.0, 1.0, "sawtooth", 0.5) == pytest.approx(0.5)
        assert sample_pattern(1.0, 0.8, "sawtooth", 0.5) == pytest.approx(0.4)

    def test_wraps_to_zero_at_period_boundary(self):
        assert sample_pattern(1.0, 1.0, "sawtooth", 1.0) == 0.0


class TestSamplePatternFrequency:

    def test_frequency_scales_phase(self):
        # 2 Hz at t=0.25 = half a period of a 2 Hz sine → midpoint to peak.
        # phase = 2*0.25 % 1 = 0.5; sine at φ=0.5 ≈ midpoint (sin(π) = 0 → 0.5*amp)
        assert sample_pattern(2.0, 1.0, "sine", 0.25) == pytest.approx(0.5, abs=1e-9)

    def test_high_frequency_completes_many_cycles(self):
        # 10 Hz sawtooth at t=1 should wrap exactly 10 times → back to 0.
        assert sample_pattern(10.0, 1.0, "sawtooth", 1.0) == pytest.approx(0.0)


# ============================================================ activity_meter

class TestActivityMeter:
    """Asymmetric EMA with locked time constants (50 ms attack,
    500 ms release). Output always clamped to [0, 1]."""

    def test_zero_dt_returns_prev(self):
        # No time has passed — meter can't integrate. Output = prev.
        assert activity_meter(0.4, 1.0, 0.0) == pytest.approx(0.4)
        assert activity_meter(0.0, 0.5, -0.1) == pytest.approx(0.0)

    def test_zero_signal_zero_prev_stays_zero(self):
        assert activity_meter(0.0, 0.0, 0.1) == pytest.approx(0.0)

    def test_rising_uses_fast_attack(self):
        # prev=0, signal=1, dt=0.05 s, tau=0.05 s → alpha = 1-exp(-1) ≈ 0.632
        result = activity_meter(0.0, 1.0, 0.05)
        expected = 1.0 - math.exp(-1.0)
        assert result == pytest.approx(expected, abs=1e-9)

    def test_falling_uses_slow_release(self):
        # prev=1, signal=0, dt=0.5 s, tau=0.5 s → alpha = 1-exp(-1) ≈ 0.632
        # smoothed = 1 + (0-1)*0.632 = 0.368
        result = activity_meter(1.0, 0.0, 0.5)
        expected = math.exp(-1.0)
        assert result == pytest.approx(expected, abs=1e-9)

    def test_attack_faster_than_release(self):
        # 100 ms rise from 0→1 covers more ground than 100 ms fall from 1→0.
        rising = activity_meter(0.0, 1.0, 0.1)
        falling = activity_meter(1.0, 0.0, 0.1)
        # `rising` is how much we covered up; `1 - falling` is how much
        # we covered down. Attack 50 ms vs release 500 ms → asymmetric.
        assert rising > (1.0 - falling)

    def test_clamps_above_one(self):
        # Defensive: a signal > 1 still gives meter ≤ 1 (anti-windup).
        result = activity_meter(0.95, 5.0, 0.01)
        assert 0.0 <= result <= 1.0

    def test_clamps_below_zero(self):
        # Defensive: negative signals don't drive the meter below 0.
        result = activity_meter(0.5, -1.0, 0.05)
        assert result >= 0.0

    def test_converges_to_signal_when_held(self):
        # Hold a constant signal and tick repeatedly — the meter
        # should approach the signal value.
        meter = 0.0
        for _ in range(200):
            meter = activity_meter(meter, 0.7, 0.01)
        assert meter == pytest.approx(0.7, abs=1e-3)


# ============================================================ activity_gate

class TestActivityGate:
    """State machine: opens instantly above wake_threshold, closes
    after meter has stayed below threshold for sleep_delay_s seconds
    while open."""

    def test_opens_when_meter_crosses_threshold(self):
        # Closed → above threshold → opens, below_since cleared.
        open_, below = activity_gate(
            prev_open=False, below_since=None,
            meter=0.5, now_s=1.0,
            wake_threshold=0.4, sleep_delay_s=0.5,
        )
        assert open_ is True
        assert below is None

    def test_stays_closed_below_threshold(self):
        # Closed + below threshold → still closed, no count starts.
        open_, below = activity_gate(
            prev_open=False, below_since=None,
            meter=0.1, now_s=1.0,
            wake_threshold=0.4, sleep_delay_s=0.5,
        )
        assert open_ is False
        assert below is None

    def test_stays_open_above_threshold(self):
        # Open + still above threshold → stays open, below_since cleared.
        open_, below = activity_gate(
            prev_open=True, below_since=None,
            meter=0.6, now_s=2.0,
            wake_threshold=0.4, sleep_delay_s=0.5,
        )
        assert open_ is True
        assert below is None

    def test_recovery_resets_below_since(self):
        # Open + had been counting → meter goes above again → counter cleared.
        open_, below = activity_gate(
            prev_open=True, below_since=1.5,
            meter=0.7, now_s=1.8,
            wake_threshold=0.4, sleep_delay_s=0.5,
        )
        assert open_ is True
        assert below is None

    def test_open_to_below_starts_count(self):
        # Open + first sample below → start counting, stay open.
        open_, below = activity_gate(
            prev_open=True, below_since=None,
            meter=0.1, now_s=2.0,
            wake_threshold=0.4, sleep_delay_s=0.5,
        )
        assert open_ is True
        assert below == pytest.approx(2.0)

    def test_close_after_sleep_delay(self):
        # Open + below since t=2.0, now=2.6, delay=0.5 → elapsed 0.6 ≥ 0.5 → close.
        open_, below = activity_gate(
            prev_open=True, below_since=2.0,
            meter=0.1, now_s=2.6,
            wake_threshold=0.4, sleep_delay_s=0.5,
        )
        assert open_ is False
        assert below is None

    def test_no_close_before_sleep_delay(self):
        # Open + below since t=2.0, now=2.3, delay=0.5 → elapsed 0.3 < 0.5 → still open.
        open_, below = activity_gate(
            prev_open=True, below_since=2.0,
            meter=0.1, now_s=2.3,
            wake_threshold=0.4, sleep_delay_s=0.5,
        )
        assert open_ is True
        assert below == pytest.approx(2.0)

    def test_zero_sleep_delay_closes_immediately(self):
        # Open + first sample below + delay=0 → closes that tick.
        open_, below = activity_gate(
            prev_open=True, below_since=None,
            meter=0.1, now_s=5.0,
            wake_threshold=0.4, sleep_delay_s=0.0,
        )
        assert open_ is False
        assert below is None

    def test_threshold_exact_match_opens(self):
        # Boundary: meter == threshold counts as "at threshold" → open.
        open_, below = activity_gate(
            prev_open=False, below_since=None,
            meter=0.4, now_s=1.0,
            wake_threshold=0.4, sleep_delay_s=0.5,
        )
        assert open_ is True
        assert below is None


# ============================================================ smooth

class TestSmoothInstant:

    def test_zero_rise_zero_fall_snaps_to_input(self):
        assert smooth(0.0, 0.5, 10.0, 0.0, 0.0) == pytest.approx(0.5)
        assert smooth(0.8, 0.2, 10.0, 0.0, 0.0) == pytest.approx(0.2)
        assert smooth(0.3, 0.3, 10.0, 0.0, 0.0) == pytest.approx(0.3)

    def test_zero_dt_snaps_to_input(self):
        # Edge case: dt is zero (no time has passed). Output should
        # equal input — no smoothing can occur in zero time.
        assert smooth(0.5, 0.8, 0.0, 100.0, 100.0) == pytest.approx(0.8)


class TestSmoothRising:

    def test_uses_rise_rate(self):
        # prev=0, mixed=1, rise=100ms, dt=100ms.
        # alpha = 1 - exp(-1) ≈ 0.632
        result = smooth(0.0, 1.0, 100.0, 100.0, 1000.0)
        expected = 1.0 - math.exp(-1.0)
        assert result == pytest.approx(expected, abs=1e-9)

    def test_fall_unused_when_rising(self):
        # Same dt and prev<mixed; different fall values shouldn't matter.
        with_long_fall = smooth(0.0, 1.0, 100.0, 100.0, 5000.0)
        with_short_fall = smooth(0.0, 1.0, 100.0, 100.0, 1.0)
        assert with_long_fall == pytest.approx(with_short_fall)

    def test_rise_zero_snaps_up(self):
        # Rising with rise=0 → instant rise to mixed.
        assert smooth(0.0, 1.0, 100.0, 0.0, 500.0) == pytest.approx(1.0)


class TestSmoothFalling:

    def test_uses_fall_rate(self):
        # prev=1, mixed=0, fall=100ms, dt=100ms.
        # alpha = 1 - exp(-1) ≈ 0.632
        result = smooth(1.0, 0.0, 100.0, 1000.0, 100.0)
        expected = math.exp(-1.0)
        assert result == pytest.approx(expected, abs=1e-9)

    def test_rise_unused_when_falling(self):
        with_long_rise = smooth(1.0, 0.0, 100.0, 5000.0, 100.0)
        with_short_rise = smooth(1.0, 0.0, 100.0, 1.0, 100.0)
        assert with_long_rise == pytest.approx(with_short_rise)

    def test_fall_zero_snaps_down(self):
        assert smooth(1.0, 0.0, 100.0, 500.0, 0.0) == pytest.approx(0.0)


class TestSmoothSteady:

    def test_no_change_when_input_equals_prev(self):
        assert smooth(0.5, 0.5, 10.0, 50.0, 300.0) == pytest.approx(0.5)
        assert smooth(0.0, 0.0, 10.0, 50.0, 300.0) == pytest.approx(0.0)
        assert smooth(1.0, 1.0, 10.0, 50.0, 300.0) == pytest.approx(1.0)


class TestSmoothConvergence:

    def test_rising_converges_to_target(self):
        # Repeated 10ms ticks toward target=1.0 with rise=50ms.
        state = 0.0
        for _ in range(100):
            state = smooth(state, 1.0, 10.0, 50.0, 1000.0)
        assert state == pytest.approx(1.0, abs=1e-3)

    def test_falling_converges_to_target(self):
        state = 1.0
        for _ in range(100):
            state = smooth(state, 0.0, 10.0, 1000.0, 50.0)
        assert state == pytest.approx(0.0, abs=1e-3)

    def test_asymmetric_envelope_rises_faster_than_falls(self):
        # Symmetric step: 0 → 1 (rise) vs 1 → 0 (fall) at the same dt.
        # With rise << fall, the rise covers more ground than the fall.
        dt = 10.0
        rising = smooth(0.0, 1.0, dt, 10.0, 1000.0)
        falling = smooth(1.0, 0.0, dt, 10.0, 1000.0)
        # `rising` is what we covered up; `1 - falling` is what we covered down.
        assert rising > (1.0 - falling)


class TestSmoothDefensive:

    def test_negative_dt_snaps_to_input(self):
        # Defensive: dt going backwards shouldn't crash. Treat as zero.
        assert smooth(0.5, 0.7, -10.0, 100.0, 100.0) == pytest.approx(0.7)

    def test_negative_tau_snaps_to_input(self):
        # Defensive: a negative tau is meaningless. Treat as instant.
        assert smooth(0.0, 1.0, 10.0, -50.0, 100.0) == pytest.approx(1.0)
        assert smooth(1.0, 0.0, 10.0, 100.0, -50.0) == pytest.approx(0.0)


class TestSmoothTailSnap:
    """Lock the snap-to-target behavior so the exponential tail can't
    re-introduce a multi-second residue (toy 'stuck buzz') regression."""

    def test_falling_tail_reaches_exact_zero(self):
        # Real-world setup: 90 Hz tick (11.1 ms), 300 ms fall.
        # Without the snap, after ~5 s the value is still ~6e-8 — non-zero
        # forever. With the snap, it should hit exactly 0 inside a couple
        # of seconds and stay there.
        state = 1.0
        for _ in range(180):  # ~2 s
            state = smooth(state, 0.0, 11.1, 50.0, 300.0)
        assert state == 0.0  # exact, not approx

    def test_rising_tail_reaches_exact_one(self):
        # Same idea on the rising side: a long-running rise should not
        # leave the toy stuck a hair below the user's max.
        state = 0.0
        for _ in range(180):
            state = smooth(state, 1.0, 11.1, 300.0, 50.0)
        assert state == 1.0  # exact

    def test_snaps_when_within_epsilon(self):
        # 0.001 residue from target — well inside the 0.005 snap window.
        out = smooth(0.001, 0.0, 11.1, 50.0, 300.0)
        assert out == 0.0

    def test_does_not_snap_far_from_target(self):
        # 0.5 residue from target — well outside the snap window; the
        # normal exponential math should apply.
        out = smooth(0.5, 0.0, 11.1, 50.0, 300.0)
        assert 0.0 < out < 0.5
        assert out != pytest.approx(0.0)
