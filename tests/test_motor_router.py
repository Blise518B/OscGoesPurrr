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
    pass-through: speed channel gain=0 (so it contributes nothing under
    `combine=max`), gate disabled, smoothing disabled, linear curve at
    unit gain on depth. Used by integration tests that just want to
    verify the depth-side compute pipeline (custom addresses + zones)."""
    return {
        "0": {
            "chains": [
                {
                    "depth": {"gain": 1.0, "curve": "linear", "curve_param": 1.0},
                    "speed": {"gain": 0.0, "curve": "linear", "curve_param": 1.0},
                    "combine": "max",
                    "gate": {
                        "enabled": False,
                        "wake_threshold": 0.05,
                        "sleep_delay_s": 0.5,
                    },
                    "smoothing": {"rise_ms": 0.0, "fall_ms": 0.0},
                },
            ],
            "merge": "max",
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

    def _chain(self, cfg):
        """Convenience: return the (only) chain dict from the per-motor
        mix block built by _pass_through_mix."""
        return cfg["mix"]["0"]["chains"][0]

    def _mix_cfg(self, **chain_overrides):
        """Build a config with the first chain partially overridden on
        top of _pass_through_mix's defaults."""
        cfg = _basic_motor_cfg(osc_addresses={"0": ["P"]})
        self._chain(cfg).update(chain_overrides)
        return cfg

    def test_missing_mix_block_falls_back_to_defaults(self, router):
        # Profile without a `mix` key still produces a sensible first-tick
        # output: dt=0 so smoothing snaps to mixed; speed default has
        # gain 1.0 but s_raw=0 on the first sample → mixed=d_shaped=d_raw.
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
            "gain": 0.5, "curve": "linear", "curve_param": 1.0,
        })
        out = router._calculate_motor_target("dev", 0, cfg, {"P": 1.0}, zones=set())
        assert out == pytest.approx(0.5)

    def test_zero_gain_on_both_channels_zeroes_output(self, router):
        # No "enabled" flag in the new schema — gain=0 is how a channel
        # gets silenced. Depth=0, speed=0 → mixed=0 regardless of input.
        cfg = self._mix_cfg()
        self._chain(cfg)["depth"]["gain"] = 0.0
        self._chain(cfg)["speed"]["gain"] = 0.0
        out = router._calculate_motor_target("dev", 0, cfg, {"P": 1.0}, zones=set())
        assert out == 0.0

    def test_smoothing_ramps_up_on_step(self, router, clock):
        cfg = self._mix_cfg()
        self._chain(cfg)["smoothing"] = {"rise_ms": 100.0, "fall_ms": 100.0}
        # First tick: dt=0 → snaps to mixed=0 (no input).
        router._calculate_motor_target("dev", 0, cfg, {"P": 0.0}, zones=set())
        clock.advance(0.05)
        # Step the input up. 50ms with 100ms rise gives a ~39% rise.
        out = router._calculate_motor_target("dev", 0, cfg, {"P": 1.0}, zones=set())
        assert 0.0 < out < 1.0, f"expected partial rise, got {out}"

    def test_per_motor_state_is_isolated(self, router, clock):
        cfg = self._mix_cfg()
        self._chain(cfg)["smoothing"] = {"rise_ms": 100.0, "fall_ms": 100.0}
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
            "gain": 1.0, "curve": "power", "curve_param": 2.0,
        })
        out = router._calculate_motor_target("dev", 0, cfg, {"P": 0.5}, zones=set())
        assert out == pytest.approx(0.25)

    def test_combine_max_picks_higher_channel(self, router, clock):
        # Enable speed (gain=1.0), drive a stroke so s_raw > d_raw,
        # expect max-wins.
        cfg = self._mix_cfg()
        self._chain(cfg)["speed"]["gain"] = 1.0
        self._chain(cfg)["combine"] = "max"
        # First tick at 0 to seed last_position.
        router._calculate_motor_target("dev", 0, cfg, {"P": 0.0}, zones=set())
        clock.advance(0.05)
        # Big jump: position 0→0.6 in 50ms. raw_speed ~= 12, * 0.75
        # normalization = 9 → clamped to 1.0. So s_raw=1.0 (above cutoff).
        # d_raw = 0.6. With combine=max → out = max(0.6, 1.0) = 1.0.
        out = router._calculate_motor_target("dev", 0, cfg, {"P": 0.6}, zones=set())
        assert out == pytest.approx(1.0)

    def test_combine_add_sums_channels(self, router, clock):
        cfg = self._mix_cfg()
        self._chain(cfg)["speed"]["gain"] = 1.0
        self._chain(cfg)["combine"] = "add"
        router._calculate_motor_target("dev", 0, cfg, {"P": 0.0}, zones=set())
        clock.advance(0.05)
        # Same stroke as above gives s_raw=1.0. d_raw=0.3 → out = clamp(0.3+1.0) = 1.0.
        out = router._calculate_motor_target("dev", 0, cfg, {"P": 0.3}, zones=set())
        assert out == pytest.approx(1.0)

    def test_combine_multiply_zero_channel_zeroes_output(self, router):
        # Locked semantics: multiply with zero in either channel → 0.
        # Speed at gain 0 → s_shaped = 0 → multiply gives 0 regardless
        # of depth. Visible in the diagram, no hidden bypass.
        cfg = self._mix_cfg()
        self._chain(cfg)["speed"]["gain"] = 0.0
        self._chain(cfg)["combine"] = "multiply"
        out = router._calculate_motor_target("dev", 0, cfg, {"P": 0.9}, zones=set())
        assert out == 0.0


# ============================================================ Tier 3.5: activity gate

class TestActivityGateIntegration:
    """Gate state machine threaded through _calculate_motor_target.
    Validates the sidechain placement (gate observes the speed-detector
    output, gates the combined signal before smoothing)."""

    def _gate_cfg(self, **gate_overrides):
        """Pass-through chain + gate enabled. Smoothing disabled so
        the gated output appears immediately on the tick the gate
        flips, simplifying assertions."""
        cfg = _basic_motor_cfg(osc_addresses={"0": ["P"]})
        chain = cfg["mix"]["0"]["chains"][0]
        chain["gate"] = {
            "enabled": True,
            "wake_threshold": 0.1,
            "sleep_delay_s": 0.5,
        }
        chain["gate"].update(gate_overrides)
        chain["smoothing"] = {"rise_ms": 0.0, "fall_ms": 0.0}
        return cfg

    def test_gate_disabled_passes_signal_through(self, router):
        # Sanity: identical setup with gate disabled = today's behavior.
        cfg = _basic_motor_cfg(osc_addresses={"0": ["P"]})
        out = router._calculate_motor_target("dev", 0, cfg, {"P": 0.7}, zones=set())
        assert out == pytest.approx(0.7)

    def test_static_input_does_not_open_gate(self, router, clock):
        # Static depth never produces speed → activity meter stays at 0
        # → gate stays closed → output suppressed.
        cfg = self._gate_cfg()
        router._calculate_motor_target("dev", 0, cfg, {"P": 0.5}, zones=set())
        # Hold the same value for several ticks. No movement, no activity.
        for _ in range(20):
            clock.advance(0.05)
            out = router._calculate_motor_target("dev", 0, cfg, {"P": 0.5}, zones=set())
        assert out == 0.0
        chain_state = router._motor_state[("dev", 0)]["chains"][0]
        assert chain_state["gate_open"] is False

    def test_sustained_movement_opens_gate(self, router, clock):
        # Oscillating input produces s_raw > 0 → activity meter rises
        # → crosses wake_threshold → gate opens → signal passes.
        cfg = self._gate_cfg(wake_threshold=0.1, sleep_delay_s=0.5)
        # Seed at 0 with dt=0.
        router._calculate_motor_target("dev", 0, cfg, {"P": 0.0}, zones=set())
        # Drive ~30 Hz oscillation by toggling P between 0.0 and 0.5.
        # Each big delta produces a strong s_raw which the activity
        # meter (50 ms attack tau) integrates rapidly.
        out = 0.0
        for i in range(20):
            clock.advance(0.03)
            p = 0.5 if i % 2 == 0 else 0.0
            out = router._calculate_motor_target("dev", 0, cfg, {"P": p}, zones=set())
        # By now the meter should be well above 0.1 → gate open →
        # output reflects the non-zero half of the oscillation.
        chain_state = router._motor_state[("dev", 0)]["chains"][0]
        assert chain_state["gate_open"] is True
        assert chain_state["activity_meter"] > 0.1

    def test_gate_closes_after_sleep_delay(self, router, clock):
        # Open the gate with movement, then let it sit still longer
        # than sleep_delay_s and verify it closes.
        cfg = self._gate_cfg(wake_threshold=0.1, sleep_delay_s=0.3)
        router._calculate_motor_target("dev", 0, cfg, {"P": 0.0}, zones=set())
        # Drive activity to open the gate.
        for i in range(20):
            clock.advance(0.03)
            p = 0.5 if i % 2 == 0 else 0.0
            router._calculate_motor_target("dev", 0, cfg, {"P": p}, zones=set())
        assert router._motor_state[("dev", 0)]["chains"][0]["gate_open"] is True

        # Now hold P at a steady value. Activity decays (500 ms release)
        # → eventually falls below threshold → after sleep_delay → close.
        # Run long enough for the meter to decay AND the delay to elapse.
        for _ in range(60):
            clock.advance(0.05)  # 3.0 s total
            out = router._calculate_motor_target("dev", 0, cfg, {"P": 0.4}, zones=set())
        assert router._motor_state[("dev", 0)]["chains"][0]["gate_open"] is False
        assert out == 0.0

    def test_gate_observes_speed_detector_not_per_channel_shaping(self, router, clock):
        # Critical placement test: changing depth gain/curve must NOT
        # affect when the gate opens. Two configs with different depth
        # gains but identical motion should produce identical gate
        # state at the same tick.
        def run(depth_gain: float):
            r = type(router)(clock=router._clock)
            cfg = self._gate_cfg(wake_threshold=0.1, sleep_delay_s=0.5)
            cfg["mix"]["0"]["chains"][0]["depth"]["gain"] = depth_gain
            return r, cfg

        # We need a deterministic FakeClock; reset via fresh router
        # below. Easiest: use the existing router but reset its state.
        cfg_a = self._gate_cfg()
        cfg_b = self._gate_cfg()
        cfg_a["mix"]["0"]["chains"][0]["depth"]["gain"] = 0.1
        cfg_b["mix"]["0"]["chains"][0]["depth"]["gain"] = 2.0

        # Drive both motors with identical motion.
        router._calculate_motor_target("devA", 0, cfg_a, {"P": 0.0}, zones=set())
        router._calculate_motor_target("devB", 0, cfg_b, {"P": 0.0}, zones=set())
        for i in range(15):
            clock.advance(0.03)
            p = 0.5 if i % 2 == 0 else 0.0
            router._calculate_motor_target("devA", 0, cfg_a, {"P": p}, zones=set())
            router._calculate_motor_target("devB", 0, cfg_b, {"P": p}, zones=set())

        state_a = router._motor_state[("devA", 0)]["chains"][0]
        state_b = router._motor_state[("devB", 0)]["chains"][0]
        # The activity meters should be identical to numerical precision
        # — depth gain does not enter the gate's input path.
        assert state_a["activity_meter"] == pytest.approx(state_b["activity_meter"])
        assert state_a["gate_open"] == state_b["gate_open"]

    def test_smoothing_applies_to_gate_close(self, router, clock):
        # Gate-close steps the signal from `mixed` to 0. With non-zero
        # fall_ms the output decays smoothly across ticks rather than
        # snapping to 0 in one step.
        cfg = _basic_motor_cfg(osc_addresses={"0": ["P"]})
        chain = cfg["mix"]["0"]["chains"][0]
        chain["gate"] = {
            "enabled": True,
            "wake_threshold": 0.1,
            "sleep_delay_s": 0.0,  # close immediately when below
        }
        chain["smoothing"] = {"rise_ms": 0.0, "fall_ms": 200.0}

        # Pre-seed chain 0's `smoothed_output` to 0.8 by hand-walking
        # the state; easier than driving the gate open and then
        # asserting on the tick the gate flips closed.
        router._calculate_motor_target("dev", 0, cfg, {"P": 0.0}, zones=set())
        chain_state = router._motor_state[("dev", 0)]["chains"][0]
        chain_state["smoothed_output"] = 0.8
        chain_state["gate_open"] = True
        chain_state["activity_meter"] = 0.0  # already below threshold

        clock.advance(0.05)
        # First post-close tick: gated input is 0, prev smoothed_output
        # is 0.8 → smoothing falls from 0.8 toward 0 with 200 ms tau.
        # 50 ms with 200 ms fall: alpha = 1 - exp(-0.25) ≈ 0.221.
        # new = 0.8 + (0 - 0.8) * 0.221 = 0.623.
        out = router._calculate_motor_target("dev", 0, cfg, {"P": 0.0}, zones=set())
        # Output is between previous 0.8 and target 0 → smoothing applied.
        assert 0.0 < out < 0.8, f"expected partial decay, got {out}"
        assert router._motor_state[("dev", 0)]["chains"][0]["gate_open"] is False


# ============================================================ Tier 3.6: multi-chain (Cut 5)

class TestMultiChainRouting:
    """End-to-end coverage of the multi-chain compute path. Each
    chain processes the same input independently; their outputs
    merge per the per-motor `merge` op."""

    def _two_chain_cfg(self, *, gain_a: float = 1.0, gain_b: float = 1.0,
                       merge_op: str = "max"):
        """Pass-through both chains: linear curve, no smoothing, gate
        off. `gain_a` / `gain_b` set the depth gain on chain 0 / 1
        respectively so tests can produce distinct per-chain outputs."""
        def _chain(gain):
            return {
                "depth": {"gain": gain, "curve": "linear", "curve_param": 1.0},
                "speed": {"gain": 0.0, "curve": "linear", "curve_param": 1.0},
                "combine": "max",
                "gate": {"enabled": False, "wake_threshold": 0.05,
                         "sleep_delay_s": 0.5},
                "smoothing": {"rise_ms": 0.0, "fall_ms": 0.0},
            }
        cfg = _basic_motor_cfg(osc_addresses={"0": ["P"]})
        cfg["mix"]["0"] = {
            "chains": [_chain(gain_a), _chain(gain_b)],
            "merge":  merge_op,
        }
        return cfg

    def test_merge_max_two_chains(self, router):
        # gain_a=0.5 → chain 0 out = 0.5 * input; gain_b=1.5 (clamped)
        # → chain 1 out = clamp(1.5*input). With input=0.4: chain0=0.2,
        # chain1=0.6 → merged max = 0.6.
        cfg = self._two_chain_cfg(gain_a=0.5, gain_b=1.5, merge_op="max")
        out = router._calculate_motor_target("dev", 0, cfg, {"P": 0.4}, zones=set())
        assert out == pytest.approx(0.6)

    def test_merge_add_clamps(self, router):
        # gain_a=1, gain_b=1, input=0.7 → both chains = 0.7 → add
        # would give 1.4 → clamped to 1.0.
        cfg = self._two_chain_cfg(gain_a=1.0, gain_b=1.0, merge_op="add")
        out = router._calculate_motor_target("dev", 0, cfg, {"P": 0.7}, zones=set())
        assert out == pytest.approx(1.0)

    def test_merge_multiply_zero_chain_zeroes_output(self, router):
        # chain B has gain 0 → its output is 0 → multiply gives 0
        # regardless of chain A. Locked semantics from the doc.
        cfg = self._two_chain_cfg(gain_a=1.0, gain_b=0.0, merge_op="multiply")
        out = router._calculate_motor_target("dev", 0, cfg, {"P": 0.9}, zones=set())
        assert out == 0.0

    def test_caps_chains_at_two(self, router):
        # A profile asking for 3 chains is silently truncated by the
        # router (UI also enforces). With three chains all gain 1.0
        # and merge=add, the output should reflect TWO chains added
        # (clamped), not three.
        chain = {
            "depth": {"gain": 1.0, "curve": "linear", "curve_param": 1.0},
            "speed": {"gain": 0.0, "curve": "linear", "curve_param": 1.0},
            "combine": "max",
            "gate": {"enabled": False, "wake_threshold": 0.05,
                     "sleep_delay_s": 0.5},
            "smoothing": {"rise_ms": 0.0, "fall_ms": 0.0},
        }
        cfg = _basic_motor_cfg(osc_addresses={"0": ["P"]})
        # input=0.3, two chains added = 0.6; three would have been 0.9
        cfg["mix"]["0"] = {
            "chains": [
                {**chain, "depth": {**chain["depth"], "gain": 1.0}},
                {**chain, "depth": {**chain["depth"], "gain": 1.0}},
                {**chain, "depth": {**chain["depth"], "gain": 1.0}},
            ],
            "merge": "add",
        }
        out = router._calculate_motor_target("dev", 0, cfg, {"P": 0.3}, zones=set())
        assert out == pytest.approx(0.6)
        # Per-motor state only allocated for two chains, confirming
        # the third was dropped before any state was created.
        state = router._motor_state[("dev", 0)]
        assert len(state["chains"]) == 2

    def test_per_chain_gate_state_is_independent(self, router, clock):
        # Two chains, one with a gate (low threshold so activity opens
        # it), the other gate-disabled (state parked at "False" /
        # signal passes through unconditionally). After driving
        # activity, the per-chain `gate_open` flags must differ —
        # proves each chain owns its own gate state machine.
        gate_on = {
            "depth": {"gain": 1.0, "curve": "linear", "curve_param": 1.0},
            "speed": {"gain": 0.0, "curve": "linear", "curve_param": 1.0},
            "combine": "max",
            "gate": {"enabled": True, "wake_threshold": 0.05,
                     "sleep_delay_s": 0.5},
            "smoothing": {"rise_ms": 0.0, "fall_ms": 0.0},
        }
        gate_off = {
            "depth": {"gain": 1.0, "curve": "linear", "curve_param": 1.0},
            "speed": {"gain": 0.0, "curve": "linear", "curve_param": 1.0},
            "combine": "max",
            "gate": {"enabled": False, "wake_threshold": 0.05,
                     "sleep_delay_s": 0.5},
            "smoothing": {"rise_ms": 0.0, "fall_ms": 0.0},
        }
        cfg = _basic_motor_cfg(osc_addresses={"0": ["P"]})
        cfg["mix"]["0"] = {"chains": [gate_on, gate_off], "merge": "max"}
        # Seed + drive activity (oscillation produces s_raw → meter
        # rises → chain 0's gate opens; chain 1's state stays parked).
        router._calculate_motor_target("dev", 0, cfg, {"P": 0.0}, zones=set())
        for i in range(10):
            clock.advance(0.03)
            p = 0.5 if i % 2 == 0 else 0.0
            router._calculate_motor_target("dev", 0, cfg, {"P": p}, zones=set())
        chain_states = router._motor_state[("dev", 0)]["chains"]
        # Chain 0: gate enabled, activity above threshold → open.
        assert chain_states[0]["gate_open"] is True
        assert chain_states[0]["activity_meter"] > 0.05
        # Chain 1: gate disabled, state parked at rest. Meter is held
        # at 0 because the disabled branch resets it every tick.
        assert chain_states[1]["gate_open"] is False
        assert chain_states[1]["activity_meter"] == 0.0
        # Structural: the two chain states are distinct dict objects,
        # never aliased. Mutation through one must not affect the other.
        assert chain_states[0] is not chain_states[1]

    def test_session_broadcast_carries_chains_array(self, router):
        # The session broadcast now includes a `chains` array
        # alongside the flat fields. The flat fields reflect chain 0
        # (backward-compat with SessionLogger.log_motor's six-field
        # signature); `out` is the merged final.
        records = []
        router.set_session_broadcast(
            lambda dev, midx, intermediates: records.append((dev, midx, intermediates))
        )
        cfg = self._two_chain_cfg(gain_a=0.5, gain_b=1.0, merge_op="max")
        out = router._calculate_motor_target("dev", 0, cfg, {"P": 0.4}, zones=set())
        assert len(records) == 1
        _, _, payload = records[0]
        assert payload["d_raw"] == pytest.approx(0.4)
        # Flat `d_shaped` is chain 0's value (0.5 gain * 0.4 = 0.2).
        assert payload["d_shaped"] == pytest.approx(0.2)
        # `out` is the merged final (max(0.2, 0.4) = 0.4).
        assert payload["out"] == pytest.approx(0.4)
        assert payload["out"] == pytest.approx(out)
        # `chains` array carries per-chain detail.
        assert isinstance(payload.get("chains"), list)
        assert len(payload["chains"]) == 2
        assert payload["chains"][0]["d_shaped"] == pytest.approx(0.2)
        assert payload["chains"][1]["d_shaped"] == pytest.approx(0.4)
        assert payload["merge"] == "max"

# ============================================================ Tier 3.7: per-(motor, chain) subscribers (Cut 6)

class TestIntermediatesSubscribers:
    """The per-(motor, chain) subscriber API powers the chain
    widget's per-stage mini-graphs. Multiple subscribers per key
    allowed; subscription state controls `has_tune_subscription` so
    main.py's routing tick keeps firing while traces are live."""

    def _pass_through(self):
        return _basic_motor_cfg(osc_addresses={"0": ["P"]})

    def test_subscribe_then_callback_fires(self, router):
        records = []
        router.subscribe_intermediates(
            "dev", 0, 0, lambda payload: records.append(payload)
        )
        router._calculate_motor_target("dev", 0, self._pass_through(),
                                       {"P": 0.5}, zones=set())
        assert len(records) == 1
        assert records[0]["chain_idx"] == 0
        assert records[0]["d_raw"] == pytest.approx(0.5)

    def test_unsubscribe_stops_callback(self, router):
        records = []
        cb = lambda payload: records.append(payload)
        router.subscribe_intermediates("dev", 0, 0, cb)
        router._calculate_motor_target("dev", 0, self._pass_through(),
                                       {"P": 0.5}, zones=set())
        router.unsubscribe_intermediates("dev", 0, 0, cb)
        router._calculate_motor_target("dev", 0, self._pass_through(),
                                       {"P": 0.5}, zones=set())
        # Only the first tick fired the callback.
        assert len(records) == 1

    def test_unsubscribe_unknown_callback_is_noop(self, router):
        # Defensive: removing a callback that was never registered
        # should not raise.
        router.unsubscribe_intermediates("dev", 0, 0, lambda p: None)

    def test_multiple_subscribers_per_key_all_fire(self, router):
        a_records = []
        b_records = []
        router.subscribe_intermediates(
            "dev", 0, 0, lambda p: a_records.append(p)
        )
        router.subscribe_intermediates(
            "dev", 0, 0, lambda p: b_records.append(p)
        )
        router._calculate_motor_target("dev", 0, self._pass_through(),
                                       {"P": 0.3}, zones=set())
        assert len(a_records) == 1
        assert len(b_records) == 1

    def test_different_chains_get_different_subscribers(self, router):
        # Subscribe to chain 0 and chain 1 with separate callbacks;
        # each gets its own chain's data.
        a_records = []
        b_records = []
        router.subscribe_intermediates(
            "dev", 0, 0, lambda p: a_records.append(p)
        )
        router.subscribe_intermediates(
            "dev", 0, 1, lambda p: b_records.append(p)
        )
        # Two-chain profile so chain 1 exists.
        cfg = _basic_motor_cfg(osc_addresses={"0": ["P"]})
        cfg["mix"]["0"]["chains"].append({
            "depth": {"gain": 2.0, "curve": "linear", "curve_param": 1.0},
            "speed": {"gain": 0.0, "curve": "linear", "curve_param": 1.0},
            "combine": "max",
            "gate": {"enabled": False, "wake_threshold": 0.05,
                     "sleep_delay_s": 0.5},
            "smoothing": {"rise_ms": 0.0, "fall_ms": 0.0},
        })
        router._calculate_motor_target("dev", 0, cfg, {"P": 0.3}, zones=set())
        assert len(a_records) == 1
        assert len(b_records) == 1
        # Chain 0 has gain 1.0 (from _pass_through_mix); chain 1 has gain 2.0.
        assert a_records[0]["d_shaped"] == pytest.approx(0.3)
        assert b_records[0]["d_shaped"] == pytest.approx(0.6)
        # chain_idx fields differ.
        assert a_records[0]["chain_idx"] == 0
        assert b_records[0]["chain_idx"] == 1

    def test_no_subscribers_means_zero_cost(self, router):
        # Sanity: with no subscribers, the per-tick emit loop must
        # not call any callback. We can't directly measure cost, but
        # we can verify nothing was invoked and the dict is empty.
        router._calculate_motor_target("dev", 0, self._pass_through(),
                                       {"P": 0.5}, zones=set())
        assert router._intermediates_subscribers == {}

    def test_has_tune_subscription_reflects_subscriber_state(self, router):
        # main.py's routing tick uses has_tune_subscription to keep
        # ticking while UI surfaces need data. Cut 8 retired the
        # legacy single-slot subscription; the method now reports on
        # the per-(motor, chain) subscriber dict + chain providers.
        assert router.has_tune_subscription() is False
        router.subscribe_intermediates("dev", 0, 0, lambda p: None)
        assert router.has_tune_subscription() is True
        assert router.has_intermediates_subscribers() is True

    def test_subscriber_exceptions_dont_break_hot_path(self, router):
        # A misbehaving callback must be silently swallowed so the
        # routing tick keeps running.
        def boom(_payload):
            raise RuntimeError("subscriber blew up")
        router.subscribe_intermediates("dev", 0, 0, boom)
        # Should not raise.
        out = router._calculate_motor_target(
            "dev", 0, self._pass_through(), {"P": 0.5}, zones=set()
        )
        assert out == pytest.approx(0.5)


# ============================================================ Tier 3.8: per-chain providers + toy suppression (Cut 7)

class TestChainValueProviders:
    """Per-chain d_raw overrides — the new path that the wrapper's
    parametric simulator uses."""

    def _two_chain_cfg(self):
        chain_template = {
            "depth": {"gain": 1.0, "curve": "linear", "curve_param": 1.0},
            "speed": {"gain": 0.0, "curve": "linear", "curve_param": 1.0},
            "combine": "max",
            "gate": {"enabled": False, "wake_threshold": 0.05,
                     "sleep_delay_s": 0.5},
            "smoothing": {"rise_ms": 0.0, "fall_ms": 0.0},
        }
        cfg = _basic_motor_cfg(osc_addresses={"0": ["P"]})
        # Use deep-copy templates so changing one doesn't poison the other.
        import copy as _c
        cfg["mix"]["0"] = {
            "chains": [_c.deepcopy(chain_template), _c.deepcopy(chain_template)],
            "merge": "max",
        }
        return cfg

    def test_chain_provider_overrides_live_d_raw_per_chain(self, router):
        # Live input is 0.4; chain 0's provider returns 0.9, chain 1
        # has no provider. The two chains should produce different
        # outputs even though they share the same motor + zones.
        records = []
        router.subscribe_intermediates(
            "dev", 0, 0, lambda p: records.append(("c0", p))
        )
        router.subscribe_intermediates(
            "dev", 0, 1, lambda p: records.append(("c1", p))
        )
        router.set_chain_value_provider("dev", 0, 0, lambda: 0.9)
        cfg = self._two_chain_cfg()
        router._calculate_motor_target("dev", 0, cfg, {"P": 0.4}, zones=set())
        c0 = next(p for tag, p in records if tag == "c0")
        c1 = next(p for tag, p in records if tag == "c1")
        # Chain 0 got the provider's 0.9; chain 1 got live 0.4.
        assert c0["d_raw"] == pytest.approx(0.9)
        assert c1["d_raw"] == pytest.approx(0.4)

    def test_chain_provider_returning_none_falls_through_to_live(self, router):
        # Provider that returns None on every call must NOT override
        # the chain's d_raw — it should see live input as if no
        # provider were registered.
        router.set_chain_value_provider("dev", 0, 0, lambda: None)
        cfg = self._two_chain_cfg()
        out = router._calculate_motor_target(
            "dev", 0, cfg, {"P": 0.4}, zones=set()
        )
        assert out == pytest.approx(0.4)

    def test_chain_provider_clamped_to_unit_interval(self, router):
        # Provider that returns out-of-range values must be clamped
        # so a misbehaving simulator can't drive d_raw negative or
        # past 1.0.
        router.set_chain_value_provider("dev", 0, 0, lambda: 1.7)
        cfg = self._two_chain_cfg()
        out = router._calculate_motor_target(
            "dev", 0, cfg, {"P": 0.0}, zones=set()
        )
        assert out == pytest.approx(1.0)

    def test_clear_chain_value_provider_restores_live(self, router):
        router.set_chain_value_provider("dev", 0, 0, lambda: 0.9)
        router.clear_chain_value_provider("dev", 0, 0)
        cfg = self._two_chain_cfg()
        out = router._calculate_motor_target(
            "dev", 0, cfg, {"P": 0.4}, zones=set()
        )
        assert out == pytest.approx(0.4)

    def test_has_chain_value_providers_reflects_state(self, router):
        assert router.has_chain_value_providers() is False
        router.set_chain_value_provider("dev", 0, 0, lambda: 0.5)
        assert router.has_chain_value_providers() is True
        # has_tune_subscription now also includes simulator state.
        assert router.has_tune_subscription() is True
        router.clear_chain_value_provider("dev", 0, 0)
        assert router.has_chain_value_providers() is False

    def test_provider_exception_does_not_break_hot_path(self, router):
        def boom():
            raise RuntimeError("provider blew up")
        router.set_chain_value_provider("dev", 0, 0, boom)
        cfg = self._two_chain_cfg()
        # Should not raise; chain falls through to live d_raw.
        out = router._calculate_motor_target(
            "dev", 0, cfg, {"P": 0.4}, zones=set()
        )
        assert out == pytest.approx(0.4)


class TestToyOutputSuppression:
    """should_send_to_toy gates the controller's engine call. The
    router itself keeps computing — meters and traces stay accurate
    — but the engine receives 0 while a motor is suppressed."""

    def test_default_is_send(self, router):
        assert router.should_send_to_toy("dev", 0) is True

    def test_suppress_and_unsuppress(self, router):
        router.suppress_toy_output("dev", 0)
        assert router.should_send_to_toy("dev", 0) is False
        # Other motors on the same device unaffected.
        assert router.should_send_to_toy("dev", 1) is True
        # Other devices unaffected.
        assert router.should_send_to_toy("other", 0) is True
        router.unsuppress_toy_output("dev", 0)
        assert router.should_send_to_toy("dev", 0) is True

    def test_unsuppress_unknown_is_noop(self, router):
        # Defensive: removing an entry that was never added should
        # not raise (matches how the wrapper sometimes calls
        # unsuppress on stop without checking state).
        router.unsuppress_toy_output("dev", 0)
        assert router.should_send_to_toy("dev", 0) is True


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
