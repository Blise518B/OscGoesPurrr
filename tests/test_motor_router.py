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


# ============================================================ Tier 2: mixer math (covered in test_mixer.py)

# Phase 2 moved the speed-blend math out of the router into a pure-
# function module (mixer.py); see test_mixer.py for the exhaustive
# coverage of curves, combine modes, and smoothing. End-to-end
# integration through _calculate_motor_target is below in Tier 3.


# ============================================================ Tier 3: integration

# Shared helpers for the integration tests. Without a `mix` block in
# the config, _calculate_motor_target falls back to DEFAULT_MIX_CONFIG —
# which means a moderate Δposition will produce a smoothed-output that
# trails the raw depth signal. Tests that want to ignore the mixer
# entirely use _disabled_speed_cfg() to mute the speed channel, leaving
# the depth channel as a pure pass-through with no smoothing.

def _pass_through_mix() -> dict:
    """Mixer config that turns _calculate_motor_target into a depth-only
    pass-through: speed channel disabled, smoothing disabled, linear
    curve, gain 1.0. Used by integration tests that just want to verify
    the depth-side compute pipeline (custom addresses + zones)."""
    return {
        "0": {
            "depth": {
                "enabled": True, "gain": 1.0,
                "curve": "linear", "curve_param": 1.0,
                "mode": "additive",
                "min_remap": 0.0, "max_remap": 1.0,
            },
            "speed": {
                "enabled": False, "gain": 1.0,
                "curve": "linear", "curve_param": 1.0,
                "mode": "additive",
                "input_deadband": 0.005,
                "output_cutoff": 0.02,
                "decay_tau": 0.30,
            },
            "combine": "max",
            "modulator_range": [0.5, 1.5],
            "smoothing": {"attack_ms": 0.0, "release_ms": 0.0},
        }
    }


def _basic_motor_cfg(**overrides) -> dict:
    cfg = {
        "motor_0_touch": True,
        "motor_0_pen": True,
        "motor_0_self": False,
        "motor_0_others": True,
        "mix": _pass_through_mix(),
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

    def test_clears_motor_state(self, router, clock):
        # The per-motor mixer state (last position / smoothed speed /
        # smoothed output) is cleared too so a routing-mode switch can't
        # leave a stale Δposition spike on the next tick.
        cfg = _basic_motor_cfg(osc_addresses={"0": ["P"]})
        router._calculate_motor_target("dev", 0, cfg, {"P": 0.5}, zones=set())
        clock.advance(0.1)
        router._calculate_motor_target("dev", 0, cfg, {"P": 0.5}, zones=set())
        assert router._motor_state, "motor state should populate after a tick"
        router.reset_outputs()
        assert router._motor_state == {}


class TestMixerIntegration:
    """End-to-end smoke tests that confirm _calculate_motor_target wires
    the mixer correctly. The math itself is unit-tested in test_mixer.py;
    these tests just make sure the router pulls the right fields out of
    the per-motor mix config and threads state through."""

    def _mix_cfg(self, **mix_overrides):
        """Build a config with a custom mix block built on top of
        _pass_through_mix's defaults."""
        cfg = _basic_motor_cfg(osc_addresses={"0": ["P"]})
        cfg["mix"]["0"].update(mix_overrides)
        return cfg

    def test_missing_mix_block_falls_back_to_defaults(self, router):
        # Profile without a `mix` key still produces a sensible first-tick
        # output: dt=0 so smoothing snaps to mixed; speed defaults are
        # enabled but s_raw=0 on the first sample → mixed=d_shaped=d_raw.
        cfg = {
            "motor_0_touch": True,
            "motor_0_pen": True,
            "motor_0_self": False,
            "motor_0_others": True,
            "osc_addresses": {"0": ["P"]},
        }
        out = router._calculate_motor_target("dev", 0, cfg, {"P": 0.5}, zones=set())
        assert out == pytest.approx(0.5)

    def test_depth_gain_scales_output(self, router):
        cfg = self._mix_cfg(depth={
            "enabled": True, "gain": 0.5,
            "curve": "linear", "curve_param": 1.0,
            "mode": "additive", "min_remap": 0.0, "max_remap": 1.0,
        })
        out = router._calculate_motor_target("dev", 0, cfg, {"P": 1.0}, zones=set())
        assert out == pytest.approx(0.5)

    def test_depth_disabled_zeroes_depth_contribution(self, router):
        cfg = self._mix_cfg()
        cfg["mix"]["0"]["depth"]["enabled"] = False
        # Speed is also disabled in _pass_through_mix → both disabled → 0
        out = router._calculate_motor_target("dev", 0, cfg, {"P": 1.0}, zones=set())
        assert out == 0.0

    def test_smoothing_ramps_up_on_step(self, router, clock):
        cfg = self._mix_cfg()
        cfg["mix"]["0"]["smoothing"] = {"attack_ms": 100.0, "release_ms": 100.0}
        # First tick: dt=0 → snaps to mixed=0 (no input).
        router._calculate_motor_target("dev", 0, cfg, {"P": 0.0}, zones=set())
        clock.advance(0.05)
        # Step the input up. 50ms with 100ms attack gives a ~39% rise.
        out = router._calculate_motor_target("dev", 0, cfg, {"P": 1.0}, zones=set())
        assert 0.0 < out < 1.0, f"expected partial rise, got {out}"

    def test_per_motor_state_is_isolated(self, router, clock):
        cfg = self._mix_cfg()
        cfg["mix"]["0"]["smoothing"] = {"attack_ms": 100.0, "release_ms": 100.0}
        # Seed devA at P=0 then ramp toward P=1; the second tick will be
        # part-way up the envelope (smoothing hasn't converged yet).
        router._calculate_motor_target("devA", 0, cfg, {"P": 0.0}, zones=set())
        clock.advance(0.05)
        out_a = router._calculate_motor_target("devA", 0, cfg, {"P": 1.0}, zones=set())
        assert 0.0 < out_a < 1.0, "devA should be mid-ramp"
        # devB starts fresh: first call has dt=0 → snaps to mixed=1.0
        # regardless of where devA is in its envelope.
        out_b = router._calculate_motor_target("devB", 0, cfg, {"P": 1.0}, zones=set())
        assert out_b == pytest.approx(1.0)
        assert out_a < out_b, "devA state shouldn't bleed into devB"
        assert ("devA", 0) in router._motor_state
        assert ("devB", 0) in router._motor_state

    def test_curve_applied_to_depth(self, router):
        # power(2) squares 0.5 → 0.25.
        cfg = self._mix_cfg(depth={
            "enabled": True, "gain": 1.0,
            "curve": "power", "curve_param": 2.0,
            "mode": "additive", "min_remap": 0.0, "max_remap": 1.0,
        })
        out = router._calculate_motor_target("dev", 0, cfg, {"P": 0.5}, zones=set())
        assert out == pytest.approx(0.25)

    def test_combine_max_picks_higher_channel(self, router, clock):
        # Enable speed, drive a stroke so s_raw > d_raw, expect max-wins.
        cfg = self._mix_cfg()
        cfg["mix"]["0"]["speed"]["enabled"] = True
        cfg["mix"]["0"]["combine"] = "max"
        # First tick at 0 to seed last_position.
        router._calculate_motor_target("dev", 0, cfg, {"P": 0.0}, zones=set())
        clock.advance(0.05)
        # Big jump: position 0→0.6 in 50ms. raw_speed ~= 12, * 0.75
        # normalization = 9 → clamped to 1.0. So s_raw=1.0 (above cutoff).
        # d_raw = 0.6. With combine=max → out = max(0.6, 1.0) = 1.0.
        out = router._calculate_motor_target("dev", 0, cfg, {"P": 0.6}, zones=set())
        assert out == pytest.approx(1.0)


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
