"""Tests for `MotorRouter` instance behavior — anything that needs the
router class or its FakeClock-injected speed math.

Tier 1 covers ``_compile_motor_config`` and the ``_zone_contribution``
filter matrix. Tier 2 covers the speed-blend math.

See ``PLAN.md`` for the full punch-list.
"""

import math

import pytest


# ============================================================ Tier 1: compile

class TestCompileMotorConfig:
    def _config_with(self, **kwargs):
        """Tiny helper to build a per-motor config dict; only fields the
        method reads need to be present."""
        return kwargs

    def test_splits_literals_vs_globs(self, router):
        cfg = self._config_with(osc_addresses={"0": ["A/B", "X/*/Y", "P/Q"]})
        compiled = router._compile_motor_config({}, "dev", 0, cfg)
        assert compiled["literals"] == ["A/B", "P/Q"]
        assert compiled["globs"] == ["X/*/Y"]

    def test_cleans_avatar_parameters_prefix(self, router):
        cfg = self._config_with(osc_addresses={"0": ["/avatar/parameters/Foo"]})
        compiled = router._compile_motor_config({}, "dev", 0, cfg)
        assert compiled["literals"] == ["Foo"]

    def test_parses_comma_separated_zones(self, router):
        cfg = self._config_with(motor_0_zones="Boob, Tail, Crotch")
        compiled = router._compile_motor_config({}, "dev", 0, cfg)
        assert compiled["allowed_zones"] == {"Boob", "Tail", "Crotch"}
        assert compiled["has_zone_filter"] is True
        assert compiled["is_all_sps"] is False

    def test_drops_empty_and_none_zones(self, router):
        cfg = self._config_with(motor_0_zones="Boob,,None,Tail")
        compiled = router._compile_motor_config({}, "dev", 0, cfg)
        assert compiled["allowed_zones"] == {"Boob", "Tail"}

    def test_detects_all_sps(self, router):
        cfg = self._config_with(motor_0_zones="All SPS")
        compiled = router._compile_motor_config({}, "dev", 0, cfg)
        assert compiled["is_all_sps"] is True
        assert compiled["has_zone_filter"] is True

    def test_falls_back_to_legacy_zone_key(self, router):
        # Legacy single-zone string when the new list-form key is missing.
        cfg = self._config_with(motor_0_zone="Boob")
        compiled = router._compile_motor_config({}, "dev", 0, cfg)
        assert compiled["allowed_zones"] == {"Boob"}

    def test_no_zones_has_no_filter(self, router):
        cfg = self._config_with()
        compiled = router._compile_motor_config({}, "dev", 0, cfg)
        assert compiled["allowed_zones"] == set()
        assert compiled["has_zone_filter"] is False


# ============================================================ Tier 1: filter matrix

# Helpers to build params for the filter matrix tests. Each contribution
# type lives behind its own close-gate, so a complete test param has both
# the value and the gate set.

def _params_touch_self(amount: float = 0.7) -> dict:
    return {
        "OGB/Orf/Z/TouchSelfClose": True,
        "OGB/Orf/Z/TouchSelf": amount,
    }


def _params_touch_others(amount: float = 0.7) -> dict:
    return {
        "OGB/Orf/Z/TouchOthersClose": True,
        "OGB/Orf/Z/TouchOthers": amount,
    }


def _params_pen_self_legacy(amount: float = 0.4) -> dict:
    # No new-pen proximity sensors → falls back to legacy PenSelf.
    return {"OGB/Orf/Z/PenSelf": amount}


def _params_pen_others_legacy(amount: float = 0.4) -> dict:
    return {
        "OGB/Orf/Z/PenOthersClose": True,
        "OGB/Orf/Z/PenOthers": amount,
    }


def _cfg(touch=True, pen=True, self_=True, others=True) -> dict:
    return {
        "motor_0_touch": touch,
        "motor_0_pen": pen,
        "motor_0_self": self_,
        "motor_0_others": others,
    }


class TestZoneContributionFilters:
    def test_allow_touch_false_blocks_touch(self, router):
        params = {**_params_touch_self(0.8), **_params_touch_others(0.9)}
        out = router._zone_contribution("Orf", "Z", _cfg(touch=False), 0, params)
        assert out == 0.0

    def test_allow_pen_false_blocks_pen(self, router):
        params = {**_params_pen_self_legacy(0.5), **_params_pen_others_legacy(0.6)}
        out = router._zone_contribution("Orf", "Z", _cfg(pen=False), 0, params)
        assert out == 0.0

    def test_allow_self_false_excludes_self(self, router):
        # Only Self present → with self disabled, output must be zero.
        params = _params_touch_self(0.7)
        out = router._zone_contribution("Orf", "Z", _cfg(self_=False), 0, params)
        assert out == 0.0

    def test_allow_others_false_excludes_others(self, router):
        params = _params_touch_others(0.7)
        out = router._zone_contribution("Orf", "Z", _cfg(others=False), 0, params)
        assert out == 0.0

    def test_touch_self_close_gate(self, router):
        # Value present but close-gate off → no contribution.
        params = {
            "OGB/Orf/Z/TouchSelfClose": False,
            "OGB/Orf/Z/TouchSelf": 0.8,
        }
        out = router._zone_contribution("Orf", "Z", _cfg(others=False), 0, params)
        assert out == 0.0

    def test_touch_others_close_gate(self, router):
        params = {
            "OGB/Orf/Z/TouchOthersClose": False,
            "OGB/Orf/Z/TouchOthers": 0.8,
        }
        out = router._zone_contribution("Orf", "Z", _cfg(self_=False), 0, params)
        assert out == 0.0

    def test_pen_others_close_defaults_true_when_absent(self, router):
        # No close-gate key present at all → legacy PenOthers passes through.
        params = {"OGB/Orf/Z/PenOthers": 0.6}
        out = router._zone_contribution("Orf", "Z", _cfg(self_=False), 0, params)
        assert out == pytest.approx(0.6)

    def test_pen_others_close_false_blocks_legacy(self, router):
        params = {
            "OGB/Orf/Z/PenOthersClose": False,
            "OGB/Orf/Z/PenOthers": 0.6,
        }
        out = router._zone_contribution("Orf", "Z", _cfg(self_=False), 0, params)
        assert out == 0.0

    def test_max_wins_across_contributions(self, router):
        # Both touch and pen contribute; output is the max, not the sum.
        params = {
            **_params_touch_others(0.3),
            **_params_pen_others_legacy(0.7),
        }
        out = router._zone_contribution("Orf", "Z", _cfg(self_=False), 0, params)
        assert out == pytest.approx(0.7)

    def test_no_contributions_returns_zero(self, router):
        out = router._zone_contribution("Orf", "Z", _cfg(), 0, {})
        assert out == 0.0


# ============================================================ Tier 2: speed-blend math

# All Tier 2 tests use the FakeClock fixture from conftest.py to drive
# time deterministically. `router` is wired to clock.now via the fixture
# chain.

class TestSpeedBlendEndpoints:
    def test_blend_zero_returns_position(self, router):
        # blend == 0 → output is the raw position, regardless of speed state.
        out = router._apply_speed_blend(("dev", 0), 0.5, blend=0.0)
        assert out == 0.5

    def test_blend_one_first_tick_returns_zero_speed(self, router):
        # First tick has no prior position → derivative is zero.
        out = router._apply_speed_blend(("dev", 0), 0.5, blend=1.0)
        assert out == 0.0

    def test_blend_half_is_linear_interpolation(self, router, clock):
        # At blend=0.5, output = 0.5*position + 0.5*derived_speed.
        # Build up a known speed at blend=1.0, then call again with dt=0 so
        # the smoothed speed is reused verbatim and we can assert the exact
        # formula.
        router.apply_speed_tuning(speed_output_cutoff=0.0)
        router._apply_speed_blend(("dev", 0), 0.0, blend=1.0)
        clock.advance(0.1)
        speed_only = router._apply_speed_blend(("dev", 0), 0.5, blend=1.0)
        assert speed_only > 0.0  # sanity check the setup produced a real speed

        mixed = router._apply_speed_blend(("dev", 0), 0.5, blend=0.5)
        expected = 0.5 * 0.5 + 0.5 * speed_only
        assert mixed == pytest.approx(expected)


class TestSpeedSignalStatic:
    def test_constant_position_smoothed_speed_stays_zero(self, router, clock):
        # Same position repeated over many ticks → speed signal stays at 0.
        for _ in range(10):
            out = router._apply_speed_blend(("dev", 0), 0.5, blend=1.0)
            clock.advance(0.05)
            assert out == 0.0

    def test_sub_deadband_jitter_stays_zero(self, router, clock):
        # Position wobbles by less than speed_input_deadband — should be gated.
        router.apply_speed_tuning(speed_input_deadband=0.05)
        positions = [0.50, 0.51, 0.50, 0.52, 0.49, 0.50]
        for p in positions:
            out = router._apply_speed_blend(("dev", 0), p, blend=1.0)
            clock.advance(0.05)
            assert out == 0.0


class TestSpeedSignalMoving:
    def test_step_change_produces_positive_speed(self, router, clock):
        # Initialize at 0.0, then jump to 0.5 over 0.05s → strong speed signal.
        router._apply_speed_blend(("dev", 0), 0.0, blend=1.0)
        clock.advance(0.05)
        out = router._apply_speed_blend(("dev", 0), 0.5, blend=1.0)
        assert out > 0.0

    def test_larger_step_produces_larger_speed(self, router, clock):
        # Two parallel motors, same dt — bigger Δposition → bigger speed.
        # Use a low gain so neither sample saturates; otherwise both clamp
        # to 1.0 and the comparison is meaningless.
        router.apply_speed_tuning(speed_gain=0.1, speed_output_cutoff=0.0)
        router._apply_speed_blend(("dev", 0), 0.0, blend=1.0)
        router._apply_speed_blend(("dev", 1), 0.0, blend=1.0)
        clock.advance(0.5)
        small = router._apply_speed_blend(("dev", 0), 0.2, blend=1.0)
        big = router._apply_speed_blend(("dev", 1), 0.8, blend=1.0)
        assert big > small
        assert big < 1.0  # saturation would invalidate the comparison


class TestSpeedSignalDecay:
    def test_decays_toward_zero_after_motion_stops(self, router, clock):
        # Drive a speed signal high, then hold position static and watch decay.
        router.apply_speed_tuning(speed_output_cutoff=0.0)  # don't snap to zero
        router._apply_speed_blend(("dev", 0), 0.0, blend=1.0)
        clock.advance(0.05)
        peak = router._apply_speed_blend(("dev", 0), 0.8, blend=1.0)
        assert peak > 0.0

        # Now hold position; over multiple long ticks the speed must decay.
        prev = peak
        seen_lower = False
        for _ in range(8):
            clock.advance(0.2)
            out = router._apply_speed_blend(("dev", 0), 0.8, blend=1.0)
            if out < prev - 1e-6:
                seen_lower = True
            prev = out
        assert seen_lower, "speed signal should monotonically decay after motion stops"
        assert prev < peak

    def test_smaller_tau_decays_faster(self, router, clock):
        # Set fast decay, build speed, measure value after a fixed wait.
        router.apply_speed_tuning(speed_decay_tau=0.05, speed_output_cutoff=0.0)
        router._apply_speed_blend(("dev", "fast"), 0.0, blend=1.0)
        clock.advance(0.05)
        router._apply_speed_blend(("dev", "fast"), 0.8, blend=1.0)
        clock.advance(0.3)
        fast_decayed = router._apply_speed_blend(("dev", "fast"), 0.8, blend=1.0)

        # Slow decay, same input pattern, same wait.
        router.apply_speed_tuning(speed_decay_tau=1.0, speed_output_cutoff=0.0)
        router._apply_speed_blend(("dev", "slow"), 0.0, blend=1.0)
        clock.advance(0.05)
        router._apply_speed_blend(("dev", "slow"), 0.8, blend=1.0)
        clock.advance(0.3)
        slow_decayed = router._apply_speed_blend(("dev", "slow"), 0.8, blend=1.0)

        assert fast_decayed < slow_decayed


class TestOutputCutoff:
    def test_below_cutoff_snaps_to_zero(self, router, clock):
        # Use a large cutoff so a low speed signal is forced to zero.
        router.apply_speed_tuning(speed_output_cutoff=0.5)
        router._apply_speed_blend(("dev", 0), 0.0, blend=1.0)
        clock.advance(0.05)
        # Tiny step — produces a small smoothed speed, well below 0.5.
        out = router._apply_speed_blend(("dev", 0), 0.02, blend=1.0)
        assert out == 0.0

    def test_above_cutoff_is_rescaled(self, router, clock):
        # With cutoff=0.0, output equals the raw smoothed speed.
        router.apply_speed_tuning(speed_output_cutoff=0.0)
        router._apply_speed_blend(("dev", 0), 0.0, blend=1.0)
        clock.advance(0.05)
        raw = router._apply_speed_blend(("dev", 0), 0.5, blend=1.0)
        assert raw > 0.0

    def test_at_exactly_cutoff_snaps_to_zero(self, router, clock):
        # The cutoff comparison is <= (not <), so a smoothed value exactly
        # equal to the cutoff still snaps to 0.
        router.apply_speed_tuning(speed_gain=0.1, speed_output_cutoff=0.0)
        router._apply_speed_blend(("dev", 0), 0.0, blend=1.0)
        clock.advance(0.5)
        smoothed = router._apply_speed_blend(("dev", 0), 0.5, blend=1.0)
        # Sanity-check we're below the clamp ceiling so we can set cutoff to this value.
        assert 0.0 < smoothed < 0.95

        # Setting cutoff to exactly the stored smoothed value and re-evaluating
        # with dt=0 (so the smoothed value is reused verbatim) snaps to 0.
        router.apply_speed_tuning(speed_output_cutoff=smoothed)
        out = router._apply_speed_blend(("dev", 0), 0.5, blend=1.0)
        assert out == 0.0


class TestApplySpeedTuningClamps:
    def test_deadband_clamped_to_range(self, router):
        router.apply_speed_tuning(speed_input_deadband=999.0)
        assert router.speed_input_deadband == 0.5
        router.apply_speed_tuning(speed_input_deadband=-1.0)
        assert router.speed_input_deadband == 0.0

    def test_gain_clamped_to_range(self, router):
        router.apply_speed_tuning(speed_gain=1000.0)
        assert router.speed_gain == 50.0
        router.apply_speed_tuning(speed_gain=-5.0)
        assert router.speed_gain == 0.0

    def test_tau_never_zero(self, router):
        # exp(-dt/tau) blows up at tau→0; router must keep tau strictly positive.
        router.apply_speed_tuning(speed_decay_tau=0.0)
        assert router.speed_decay_tau >= 0.01
        router.apply_speed_tuning(speed_decay_tau=999.0)
        assert router.speed_decay_tau == 5.0

    def test_cutoff_clamped_to_range(self, router):
        router.apply_speed_tuning(speed_output_cutoff=1.5)
        assert router.speed_output_cutoff == 0.95
        router.apply_speed_tuning(speed_output_cutoff=-0.3)
        assert router.speed_output_cutoff == 0.0

    def test_non_numeric_input_silently_ignored(self, router):
        # Bad input must NOT raise and must NOT change the value.
        before = router.speed_gain
        router.apply_speed_tuning(speed_gain="not a number")
        assert router.speed_gain == before


# ============================================================ Tier 3: integration

# Shared helpers for the integration tests. Every motor config in these
# tests uses speed_blend=0 so the blend stage is a no-op and we test pure
# routing logic without speed math interference.

def _basic_motor_cfg(**overrides) -> dict:
    cfg = {
        "motor_0_touch": True,
        "motor_0_pen": True,
        "motor_0_self": False,
        "motor_0_others": True,
        "motor_0_speed_blend": 0.0,
    }
    cfg.update(overrides)
    return cfg


class TestCalculateMotorTarget:
    def test_no_match_returns_zero(self, router):
        out = router._calculate_motor_target(
            "dev", 0, _basic_motor_cfg(), {}, zones=set()
        )
        assert out == 0.0

    def test_custom_literal_match(self, router):
        cfg = _basic_motor_cfg(osc_addresses={"0": ["MyParam"]})
        params = {"MyParam": 0.7}
        out = router._calculate_motor_target("dev", 0, cfg, params, zones=set())
        assert out == pytest.approx(0.7)

    def test_custom_glob_match_takes_max(self, router):
        cfg = _basic_motor_cfg(osc_addresses={"0": ["foo/*"]})
        params = {"foo/a": 0.3, "foo/b": 0.8, "bar/c": 0.9}
        out = router._calculate_motor_target("dev", 0, cfg, params, zones=set())
        # Only foo/* matches; bar/c is filtered out.
        assert out == pytest.approx(0.8)

    def test_zone_filter_specific_excludes_other_zones(self, router):
        cfg = _basic_motor_cfg(motor_0_zones="Boob")
        params = {
            "OGB/Orf/Boob/TouchOthersClose": True,
            "OGB/Orf/Boob/TouchOthers": 0.6,
            "OGB/Orf/Tail/TouchOthersClose": True,
            "OGB/Orf/Tail/TouchOthers": 0.9,  # not in zone filter — ignored
        }
        zones = {("Orf", "Boob"), ("Orf", "Tail")}
        out = router._calculate_motor_target("dev", 0, cfg, params, zones=zones)
        assert out == pytest.approx(0.6)

    def test_zone_filter_all_sps_includes_everything(self, router):
        cfg = _basic_motor_cfg(motor_0_zones="All SPS")
        params = {
            "OGB/Orf/Boob/TouchOthersClose": True,
            "OGB/Orf/Boob/TouchOthers": 0.4,
            "OGB/Orf/Tail/TouchOthersClose": True,
            "OGB/Orf/Tail/TouchOthers": 0.9,
        }
        zones = {("Orf", "Boob"), ("Orf", "Tail")}
        out = router._calculate_motor_target("dev", 0, cfg, params, zones=zones)
        assert out == pytest.approx(0.9)

    def test_custom_and_zone_take_max(self, router):
        cfg = _basic_motor_cfg(
            osc_addresses={"0": ["ExtraParam"]},
            motor_0_zones="Boob",
        )
        params = {
            "ExtraParam": 0.3,
            "OGB/Orf/Boob/TouchOthersClose": True,
            "OGB/Orf/Boob/TouchOthers": 0.7,
        }
        zones = {("Orf", "Boob")}
        out = router._calculate_motor_target("dev", 0, cfg, params, zones=zones)
        assert out == pytest.approx(0.7)


class TestReevaluateState:
    def test_empty_profile_returns_empty(self, router):
        out = router.reevaluate_state({}, {}, zones=set())
        assert out == []

    def test_emits_changed_motor(self, router):
        profile = {
            "dev": {
                "motor_count": 1,
                "osc_addresses": {"0": ["MyParam"]},
                **_basic_motor_cfg(),
            }
        }
        out = router.reevaluate_state(profile, {"MyParam": 0.5}, zones=set())
        assert len(out) == 1
        device, value, motor_idx = out[0]
        assert device == "dev"
        assert motor_idx == 0
        assert value == pytest.approx(0.5)

    def test_debounce_unchanged_value(self, router):
        profile = {
            "dev": {
                "motor_count": 1,
                "osc_addresses": {"0": ["MyParam"]},
                **_basic_motor_cfg(),
            }
        }
        first = router.reevaluate_state(profile, {"MyParam": 0.5}, zones=set())
        second = router.reevaluate_state(profile, {"MyParam": 0.5}, zones=set())
        assert len(first) == 1
        assert second == []

    def test_emits_on_change(self, router):
        profile = {
            "dev": {
                "motor_count": 1,
                "osc_addresses": {"0": ["MyParam"]},
                **_basic_motor_cfg(),
            }
        }
        router.reevaluate_state(profile, {"MyParam": 0.5}, zones=set())
        out = router.reevaluate_state(profile, {"MyParam": 0.8}, zones=set())
        assert len(out) == 1
        assert out[0][1] == pytest.approx(0.8)


class TestReevaluateSimpleMode:
    def test_same_value_to_every_motor(self, router):
        params = {
            "OGB/Orf/Z/TouchOthersClose": True,
            "OGB/Orf/Z/TouchOthers": 0.7,
        }
        zones = {("Orf", "Z")}
        counts = {"deviceA": 2, "deviceB": 1}
        out = router.reevaluate_simple_mode(counts, params, zones=zones)
        # Should emit one update per (device, motor) — 3 total.
        assert len(out) == 3
        # All values should be identical.
        unique = {v for _, v, _ in out}
        assert len(unique) == 1
        assert next(iter(unique)) == pytest.approx(0.7)

    def test_self_contributions_excluded(self, router):
        # Only TouchSelf present — simple mode disables self, so output is 0.
        params = {
            "OGB/Orf/Z/TouchSelfClose": True,
            "OGB/Orf/Z/TouchSelf": 0.7,
        }
        zones = {("Orf", "Z")}
        out = router.reevaluate_simple_mode({"dev": 1}, params, zones=zones)
        # First call emits because last_outputs has no entry yet.
        assert len(out) == 1
        assert out[0][1] == 0.0

    def test_debounces_across_calls(self, router):
        params = {
            "OGB/Orf/Z/TouchOthersClose": True,
            "OGB/Orf/Z/TouchOthers": 0.7,
        }
        zones = {("Orf", "Z")}
        router.reevaluate_simple_mode({"dev": 1}, params, zones=zones)
        second = router.reevaluate_simple_mode({"dev": 1}, params, zones=zones)
        assert second == []


class TestResetOutputs:
    def test_clears_last_outputs(self, router):
        profile = {
            "dev": {
                "motor_count": 1,
                "osc_addresses": {"0": ["MyParam"]},
                **_basic_motor_cfg(),
            }
        }
        params = {"MyParam": 0.5}
        router.reevaluate_state(profile, params, zones=set())
        assert router.last_outputs  # populated
        router.reset_outputs()
        assert router.last_outputs == {}
        # Next call emits — the debounce state was wiped.
        out = router.reevaluate_state(profile, params, zones=set())
        assert len(out) == 1

    def test_clears_speed_state(self, router, clock):
        router._apply_speed_blend(("dev", 0), 0.0, blend=1.0)
        clock.advance(0.1)
        router._apply_speed_blend(("dev", 0), 0.5, blend=1.0)
        assert router._speed_state
        router.reset_outputs()
        assert router._speed_state == {}


# ============================================================ Tier 4: depth model

class TestGetNewPenAmount:
    def test_no_proximity_params_returns_none(self, router):
        # Both root and tip absent → caller should fall back to legacy.
        out = router._get_new_pen_amount("Orf", "Z", True, {})
        assert out is None

    def test_zero_proximity_returns_none(self, router):
        # Penetrator is "nowhere near" → defer to legacy path.
        params = {
            "OGB/Orf/Z/PenSelfNewRoot": 0.0,
            "OGB/Orf/Z/PenSelfNewTip": 0.0,
        }
        out = router._get_new_pen_amount("Orf", "Z", True, params)
        assert out is None

    def test_nearby_uncalibrated_returns_zero(self, router):
        # Penetrator is in radius but tip hasn't reached center yet, so we
        # commit to the new-pen path (not None) but can't compute a depth.
        params = {
            "OGB/Orf/Z/PenSelfNewRoot": 0.3,
            "OGB/Orf/Z/PenSelfNewTip": 0.5,
        }
        out = router._get_new_pen_amount("Orf", "Z", True, params)
        assert out == 0.0

    def test_calibrated_depth_calculation(self, router):
        # Calibrate the detector with length-0.2 samples.
        det = router._get_length_detector("Orf", "Z", "self")
        for _ in range(5):
            det.update(0.3, 0.5)  # tip < 0.99 → normal samples, length 0.2

        # Query with tip>0.99 and root=0.9 → exposed=0.1, ratio=0.5, depth=0.5.
        params = {
            "OGB/Orf/Z/PenSelfNewRoot": 0.9,
            "OGB/Orf/Z/PenSelfNewTip": 1.0,
        }
        out = router._get_new_pen_amount("Orf", "Z", True, params)
        assert out == pytest.approx(0.5)


class TestUpdateLengthDetectors:
    def test_only_orf_zones_get_detectors(self, router):
        params = {
            "OGB/Orf/A/PenSelfNewRoot": 0.5,
            "OGB/Orf/A/PenSelfNewTip": 0.7,
            "OGB/Pen/B/PenSelfNewRoot": 0.5,
            "OGB/Pen/B/PenSelfNewTip": 0.7,
        }
        zones = {("Orf", "A"), ("Pen", "B")}
        router._update_length_detectors(params, zones)
        assert ("Orf", "A", "self") in router._length_detectors
        assert ("Pen", "B", "self") not in router._length_detectors

    def test_no_proximity_params_no_detector(self, router):
        # Zone has no NewRoot/NewTip → no detector created.
        zones = {("Orf", "A")}
        params = {"OGB/Orf/A/TouchSelf": 0.5}
        router._update_length_detectors(params, zones)
        assert ("Orf", "A", "self") not in router._length_detectors

    def test_feeds_both_self_and_others(self, router):
        params = {
            "OGB/Orf/A/PenSelfNewRoot": 0.5,
            "OGB/Orf/A/PenSelfNewTip": 0.7,
            "OGB/Orf/A/PenOthersNewRoot": 0.4,
            "OGB/Orf/A/PenOthersNewTip": 0.6,
        }
        zones = {("Orf", "A")}
        router._update_length_detectors(params, zones)
        assert ("Orf", "A", "self") in router._length_detectors
        assert ("Orf", "A", "others") in router._length_detectors


# ============================================================ Tier 5: hardening

class TestCompiledConfigCache:
    def test_cache_hit_on_unchanged_config(self, router):
        profile = {"dev": {}}
        cfg = {"motor_0_zones": "Boob"}
        first = router._compile_motor_config(profile, "dev", 0, cfg)
        second = router._compile_motor_config(profile, "dev", 0, cfg)
        assert first is second  # exact same dict — cache hit

    def test_cache_invalidates_on_zone_change(self, router):
        profile = {"dev": {}}
        cfg = {"motor_0_zones": "Boob"}
        first = router._compile_motor_config(profile, "dev", 0, cfg)
        # Mutate the same dict — the token includes zones_str so the cache
        # key changes and we get a fresh compile.
        cfg["motor_0_zones"] = "Tail"
        second = router._compile_motor_config(profile, "dev", 0, cfg)
        assert first is not second
        assert first["allowed_zones"] == {"Boob"}
        assert second["allowed_zones"] == {"Tail"}

    def test_cache_clears_when_oversized(self, router):
        # Feed 300 distinct entries; the > 256 threshold must trigger a
        # clear so the cache doesn't grow unboundedly.
        for i in range(300):
            profile = {f"d{i}": {}}
            cfg = {"motor_0_zones": f"zone_{i}"}
            router._compile_motor_config(profile, f"d{i}", 0, cfg)
        assert len(router._compiled_cfg) < 300


class TestGetParamBadTypes:
    def test_missing_key_returns_none(self, router):
        assert router._get_param({}, "missing") is None

    def test_none_value_returns_none(self, router):
        assert router._get_param({"k": None}, "k") is None

    def test_garbage_string_returns_none(self, router):
        # Non-numeric string can't be float()'d.
        assert router._get_param({"k": "not a number"}, "k") is None

    def test_numeric_passes_through(self, router):
        assert router._get_param({"k": 0.7}, "k") == 0.7

    def test_int_coerces_to_float(self, router):
        assert router._get_param({"k": 1}, "k") == 1.0


class TestGetBoolBadTypes:
    def test_missing_key_returns_false(self, router):
        assert router._get_bool({}, "missing") is False

    def test_true_passes_through(self, router):
        assert router._get_bool({"k": True}, "k") is True

    def test_high_float_is_true(self, router):
        # > 0.5 threshold
        assert router._get_bool({"k": 0.8}, "k") is True

    def test_low_float_is_false(self, router):
        assert router._get_bool({"k": 0.3}, "k") is False

    def test_non_numeric_string_falls_back_to_bool(self, router):
        # float("junk") fails → bool("junk") is True (non-empty).
        assert router._get_bool({"k": "junk"}, "k") is True

    def test_empty_string_is_false(self, router):
        # float("") fails → bool("") is False.
        assert router._get_bool({"k": ""}, "k") is False
