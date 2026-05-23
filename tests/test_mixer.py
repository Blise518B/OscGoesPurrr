"""Tests for the pure-function mixer in `mixer.py`.

These functions are stateless; the router maintains smoothing
prev-state outside of them. Each function is tested in isolation
against the math documented in ROUTING_REDESIGN.md § Phase 2."""

import math

import pytest

from mixer import apply_curve, combine, smooth


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

class TestCombineEnabled:

    def test_both_disabled_returns_zero(self):
        assert combine(0.5, 0.5, False, "additive", False, "additive",
                       "sum", 0.5, 1.5) == 0.0
        assert combine(0.5, 0.5, False, "additive", False, "additive",
                       "max", 0.5, 1.5) == 0.0

    def test_only_depth_enabled_passes_depth_clamped(self):
        assert combine(0.7, 0.3, True, "additive", False, "additive",
                       "max", 0.5, 1.5) == pytest.approx(0.7)
        # Depth shaped value can exceed 1 (gain > 1) — combine clamps.
        assert combine(1.5, 0.0, True, "additive", False, "additive",
                       "max", 0.5, 1.5) == pytest.approx(1.0)

    def test_only_speed_enabled_passes_speed_clamped(self):
        assert combine(0.7, 0.3, False, "additive", True, "additive",
                       "max", 0.5, 1.5) == pytest.approx(0.3)
        assert combine(0.0, 1.5, False, "additive", True, "additive",
                       "max", 0.5, 1.5) == pytest.approx(1.0)


class TestCombineAdditive:

    def test_sum_adds_normally(self):
        assert combine(0.3, 0.4, True, "additive", True, "additive",
                       "sum", 0.5, 1.5) == pytest.approx(0.7)

    def test_sum_clamps_overflow(self):
        assert combine(0.6, 0.7, True, "additive", True, "additive",
                       "sum", 0.5, 1.5) == pytest.approx(1.0)
        assert combine(1.0, 1.0, True, "additive", True, "additive",
                       "sum", 0.5, 1.5) == pytest.approx(1.0)

    def test_sum_endpoints(self):
        assert combine(0.0, 0.0, True, "additive", True, "additive",
                       "sum", 0.5, 1.5) == pytest.approx(0.0)

    def test_max_picks_higher(self):
        assert combine(0.3, 0.7, True, "additive", True, "additive",
                       "max", 0.5, 1.5) == pytest.approx(0.7)
        assert combine(0.9, 0.4, True, "additive", True, "additive",
                       "max", 0.5, 1.5) == pytest.approx(0.9)
        assert combine(0.5, 0.5, True, "additive", True, "additive",
                       "max", 0.5, 1.5) == pytest.approx(0.5)

    def test_unknown_combine_op_falls_back_to_max(self):
        assert combine(0.3, 0.7, True, "additive", True, "additive",
                       "unknown_op", 0.5, 1.5) == pytest.approx(0.7)


class TestCombineModulate:

    def test_speed_modulates_depth_at_zero(self):
        # S=0 → factor = mod_min = 0.5; D=0.8 → out = 0.8 * 0.5 = 0.4
        assert combine(0.8, 0.0, True, "additive", True, "modulate",
                       "max", 0.5, 1.5) == pytest.approx(0.4)

    def test_speed_modulates_depth_at_full(self):
        # S=1 → factor = mod_max = 1.5; D=0.8 → out = 1.2 → clamped to 1.0
        assert combine(0.8, 1.0, True, "additive", True, "modulate",
                       "max", 0.5, 1.5) == pytest.approx(1.0)

    def test_speed_modulates_depth_at_half(self):
        # S=0.5 → factor = 1.0 (midpoint of 0.5..1.5); out = D
        assert combine(0.6, 0.5, True, "additive", True, "modulate",
                       "max", 0.5, 1.5) == pytest.approx(0.6)

    def test_depth_modulates_speed_at_zero(self):
        # D=0 → factor = 0.5; S=0.8 → out = 0.4
        assert combine(0.0, 0.8, True, "modulate", True, "additive",
                       "max", 0.5, 1.5) == pytest.approx(0.4)

    def test_depth_modulates_speed_at_full(self):
        # D=1 → factor = 1.5; S=0.8 → out = 1.2 → clamped to 1.0
        assert combine(1.0, 0.8, True, "modulate", True, "additive",
                       "max", 0.5, 1.5) == pytest.approx(1.0)

    def test_both_modulate_depth_wins(self):
        # Defensive: UI prevents both-modulate. If it slips through,
        # depth's mode wins (i.e. depth modulates speed).
        # D=0.5 → factor=1.0; S=0.7 → out = 0.7 * 1.0 = 0.7
        assert combine(0.5, 0.7, True, "modulate", True, "modulate",
                       "max", 0.5, 1.5) == pytest.approx(0.7)

    def test_modulator_range_can_be_below_one(self):
        # Pure attenuation range: 0.0 to 1.0.
        # S=1.0 → factor=1.0; D=0.8 → out=0.8
        assert combine(0.8, 1.0, True, "additive", True, "modulate",
                       "max", 0.0, 1.0) == pytest.approx(0.8)
        # S=0.0 → factor=0.0; D=0.8 → out=0.0 (full cut)
        assert combine(0.8, 0.0, True, "additive", True, "modulate",
                       "max", 0.0, 1.0) == pytest.approx(0.0)

    def test_modulator_range_can_amplify(self):
        # Pure boost range: 1.0 to 2.0.
        # S=0.0 → factor=1.0; D=0.5 → out=0.5 (no change)
        assert combine(0.5, 0.0, True, "additive", True, "modulate",
                       "max", 1.0, 2.0) == pytest.approx(0.5)
        # S=1.0 → factor=2.0; D=0.5 → out=1.0
        assert combine(0.5, 1.0, True, "additive", True, "modulate",
                       "max", 1.0, 2.0) == pytest.approx(1.0)


class TestCombineDefensive:

    def test_output_always_in_unit_interval(self):
        # Extreme positive inputs.
        assert 0.0 <= combine(1.5, 1.5, True, "additive", True, "additive",
                              "sum", 0.5, 1.5) <= 1.0
        # Extreme negative inputs (shouldn't happen but defensive).
        assert 0.0 <= combine(-0.5, -0.5, True, "additive", True, "additive",
                              "sum", 0.5, 1.5) <= 1.0


# ============================================================ smooth

class TestSmoothInstant:

    def test_zero_attack_zero_release_snaps_to_input(self):
        assert smooth(0.0, 0.5, 10.0, 0.0, 0.0) == pytest.approx(0.5)
        assert smooth(0.8, 0.2, 10.0, 0.0, 0.0) == pytest.approx(0.2)
        assert smooth(0.3, 0.3, 10.0, 0.0, 0.0) == pytest.approx(0.3)

    def test_zero_dt_snaps_to_input(self):
        # Edge case: dt is zero (no time has passed). Output should
        # equal input — no smoothing can occur in zero time.
        assert smooth(0.5, 0.8, 0.0, 100.0, 100.0) == pytest.approx(0.8)


class TestSmoothRising:

    def test_uses_attack_rate(self):
        # prev=0, mixed=1, attack=100ms, dt=100ms.
        # alpha = 1 - exp(-1) ≈ 0.632
        # smoothed = 0 + 1 * 0.632 = 0.632
        result = smooth(0.0, 1.0, 100.0, 100.0, 1000.0)
        expected = 1.0 - math.exp(-1.0)
        assert result == pytest.approx(expected, abs=1e-9)

    def test_release_unused_when_rising(self):
        # Same dt and prev<mixed; different release values shouldn't matter.
        with_long_release = smooth(0.0, 1.0, 100.0, 100.0, 5000.0)
        with_short_release = smooth(0.0, 1.0, 100.0, 100.0, 1.0)
        assert with_long_release == pytest.approx(with_short_release)

    def test_attack_zero_snaps_up(self):
        # Rising with attack=0 → instant rise to mixed.
        assert smooth(0.0, 1.0, 100.0, 0.0, 500.0) == pytest.approx(1.0)


class TestSmoothFalling:

    def test_uses_release_rate(self):
        # prev=1, mixed=0, release=100ms, dt=100ms.
        # alpha = 1 - exp(-1) ≈ 0.632
        # smoothed = 1 + (0-1) * 0.632 = 1 - 0.632 = 0.368
        result = smooth(1.0, 0.0, 100.0, 1000.0, 100.0)
        expected = math.exp(-1.0)
        assert result == pytest.approx(expected, abs=1e-9)

    def test_attack_unused_when_falling(self):
        with_long_attack = smooth(1.0, 0.0, 100.0, 5000.0, 100.0)
        with_short_attack = smooth(1.0, 0.0, 100.0, 1.0, 100.0)
        assert with_long_attack == pytest.approx(with_short_attack)

    def test_release_zero_snaps_down(self):
        assert smooth(1.0, 0.0, 100.0, 500.0, 0.0) == pytest.approx(0.0)


class TestSmoothSteady:

    def test_no_change_when_input_equals_prev(self):
        assert smooth(0.5, 0.5, 10.0, 50.0, 300.0) == pytest.approx(0.5)
        assert smooth(0.0, 0.0, 10.0, 50.0, 300.0) == pytest.approx(0.0)
        assert smooth(1.0, 1.0, 10.0, 50.0, 300.0) == pytest.approx(1.0)


class TestSmoothConvergence:

    def test_rising_converges_to_target(self):
        # Repeated 10ms ticks toward target=1.0 with attack=50ms.
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
        # With attack << release, the rise covers more ground than the fall.
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
        # Real-world setup: 90 Hz tick (11.1 ms), 300 ms release default.
        # Without the snap, after ~5 s the value is still ~6e-8 — non-zero
        # forever. With the snap, it should hit exactly 0 inside a couple
        # of seconds and stay there.
        state = 1.0
        for _ in range(180):  # ~2 s
            state = smooth(state, 0.0, 11.1, 50.0, 300.0)
        assert state == 0.0  # exact, not approx

    def test_rising_tail_reaches_exact_one(self):
        # Same idea on the rising side: a long-running attack should not
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
