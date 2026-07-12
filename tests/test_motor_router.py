"""Tests for `MotorRouter` instance behavior — anything that needs the
router class or its FakeClock-injected speed math.

Tier 1 covers ``_compile_motor_config`` and the ``_zone_contribution``
filter matrix. Tier 2 covers the speed-blend math.

See ``PLAN.md`` for the full punch-list.
"""

import math

import pytest

from motor_router import MotorRouter


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

    def test_globs_precompile_to_one_regex(self, router):
        # The hot loop matches params against ONE alternation regex instead
        # of per-pattern fnmatch calls; semantics must stay fnmatch's
        # (full-string, case-insensitive per Windows normcase).
        cfg = self._config_with(osc_addresses={"0": ["foo/*", "*/Prox"]})
        compiled = router._compile_motor_config({}, "dev", 0, cfg)
        rx = compiled["glob_re"]
        assert rx is not None
        assert rx.match("foo/a")
        assert rx.match("FOO/A")            # fnmatch normcase parity
        assert rx.match("Zone/Prox")
        assert not rx.match("bar/c")
        assert not rx.match("prefix-foo/a")  # full-string, not substring

    def test_no_globs_means_no_regex(self, router):
        cfg = self._config_with(osc_addresses={"0": ["A/B"]})
        compiled = router._compile_motor_config({}, "dev", 0, cfg)
        assert compiled["glob_re"] is None

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

    def test_touch_zone_drives_motor(self, router):
        cfg = _basic_motor_cfg(motor_0_zones="Head")
        params = {"OGB/Touch/Head/Others": 0.5}
        zones = {("Touch", "Head")}
        out = router._calculate_motor_target("dev", 0, cfg, params, zones=zones)
        assert out == pytest.approx(0.5)

    def test_touch_zone_vfh_wire_form(self, router):
        cfg = _basic_motor_cfg(motor_0_zones="Head")
        params = {"VFH/Zone/Touch/Head/Others": 0.4}
        zones = {("Touch", "Head")}
        out = router._calculate_motor_target("dev", 0, cfg, params, zones=zones)
        assert out == pytest.approx(0.4)

    def test_touch_zone_honors_self_filter(self, router):
        # Default profile disables self-contact; a Self-only touch reads 0.
        cfg = _basic_motor_cfg(motor_0_zones="Head")
        params = {"OGB/Touch/Head/Self": 0.9}
        zones = {("Touch", "Head")}
        out = router._calculate_motor_target("dev", 0, cfg, params, zones=zones)
        assert out == 0.0

    def test_touch_zone_ignored_when_touch_filter_off(self, router):
        # OGB parity: touch zones ride the hands toggle only, so turning
        # Touch off silences them even with pen enabled.
        cfg = _basic_motor_cfg(motor_0_zones="Head", motor_0_touch=False)
        params = {"OGB/Touch/Head/Others": 0.9}
        zones = {("Touch", "Head")}
        out = router._calculate_motor_target("dev", 0, cfg, params, zones=zones)
        assert out == 0.0


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

    def test_touch_zone_contributes_others_only(self, router):
        # Simple Mode's synthetic config allows others but never self;
        # a touch zone flows through _zone_contribution like any other.
        params = {
            "OGB/Touch/Head/Others": 0.6,
            "OGB/Touch/Head/Self": 0.9,   # excluded: self disabled
        }
        zones = {("Touch", "Head")}
        out = router.reevaluate_simple_mode({"dev": 1}, params, zones=zones)
        assert len(out) == 1
        assert out[0][1] == pytest.approx(0.6)

    # ---- Simple Mode anti-stuck: flat, non-adjustable 2 s cutoff ----

    @staticmethod
    def _others(amount: float) -> dict:
        return {"OGB/Orf/Z/TouchOthersClose": True, "OGB/Orf/Z/TouchOthers": amount}

    def test_antistuck_cuts_stuck_value_after_two_seconds(self, router, clock):
        zones = {("Orf", "Z")}
        params = self._others(0.7)
        out = router.reevaluate_simple_mode({"dev": 1}, params, zones=zones)
        assert out == [("dev", pytest.approx(0.7), 0)]
        # Under 2 s — value held (debounced, no change).
        clock.advance(1.9)
        assert router.reevaluate_simple_mode({"dev": 1}, params, zones=zones) == []
        # Crosses 2 s of a frozen value → forced to 0.
        clock.advance(0.2)
        out = router.reevaluate_simple_mode({"dev": 1}, params, zones=zones)
        assert out == [("dev", 0.0, 0)]

    def test_antistuck_resets_when_value_changes(self, router, clock):
        zones = {("Orf", "Z")}
        router.reevaluate_simple_mode({"dev": 1}, self._others(0.7), zones=zones)
        clock.advance(1.9)
        # Value moves before the cut → fuse restarts, new value flows.
        out = router.reevaluate_simple_mode({"dev": 1}, self._others(0.6), zones=zones)
        assert out == [("dev", pytest.approx(0.6), 0)]
        # 1 s into the fresh window → still held.
        clock.advance(1.0)
        assert router.reevaluate_simple_mode({"dev": 1}, self._others(0.6), zones=zones) == []
        # Past 2 s from the change → now cut.
        clock.advance(1.2)
        out = router.reevaluate_simple_mode({"dev": 1}, self._others(0.6), zones=zones)
        assert out == [("dev", 0.0, 0)]

    def test_antistuck_stays_cut_until_value_changes(self, router, clock):
        zones = {("Orf", "Z")}
        router.reevaluate_simple_mode({"dev": 1}, self._others(0.7), zones=zones)
        clock.advance(2.1)
        assert router.reevaluate_simple_mode(
            {"dev": 1}, self._others(0.7), zones=zones) == [("dev", 0.0, 0)]
        # Still frozen → stays cut, nothing new emitted.
        clock.advance(3.0)
        assert router.reevaluate_simple_mode(
            {"dev": 1}, self._others(0.7), zones=zones) == []
        # Value finally moves → restored.
        out = router.reevaluate_simple_mode({"dev": 1}, self._others(0.4), zones=zones)
        assert out == [("dev", pytest.approx(0.4), 0)]

    def test_reset_outputs_resets_simple_antistuck_fuse(self, router, clock):
        zones = {("Orf", "Z")}
        params = self._others(0.7)
        router.reevaluate_simple_mode({"dev": 1}, params, zones=zones)
        clock.advance(1.9)
        router.reevaluate_simple_mode({"dev": 1}, params, zones=zones)  # age fuse to 1.9 s
        router.reset_outputs()  # clears the fuse + debounce
        # Fresh start: value passes again and is NOT instantly cut despite the
        # clock already being at t=1.9 (a stale fuse would fire next tick).
        out = router.reevaluate_simple_mode({"dev": 1}, params, zones=zones)
        assert out == [("dev", pytest.approx(0.7), 0)]
        clock.advance(1.0)  # only 1 s since reset → still held
        assert router.reevaluate_simple_mode({"dev": 1}, params, zones=zones) == []


class TestNeedsSettling:
    """`needs_settling` keeps main.py's routing tick alive while any
    motor output is non-zero — the hardware-safety condition that lets
    smoothing tails finish and anti-stuck fire after VRChat goes
    silent, independent of any UI trace subscription (those pause
    while their pages are hidden)."""

    def _profile(self):
        return {
            "dev": {
                "motor_count": 1,
                "osc_addresses": {"0": ["P"]},
                **_basic_motor_cfg(),
            }
        }

    def test_idle_router_does_not_need_settling(self, router):
        assert router.needs_settling() is False

    def test_driven_motor_needs_settling_until_it_rests(self, router):
        profile = self._profile()
        router.reevaluate_state(profile, {"P": 0.8}, zones=set())
        assert router.needs_settling() is True
        # Input released: pass-through config (no smoothing) lands the
        # output at exactly 0 on the next recompute → idle again.
        router.reevaluate_state(profile, {"P": 0.0}, zones=set())
        assert router.needs_settling() is False

    def test_frozen_nonzero_output_keeps_needing_ticks(self, router, clock):
        # The anti-stuck scenario: VRChat freezes mid-contact, no OSC
        # wake-up is ever coming. The router must keep reporting "tick
        # me" so the cutoff logic gets a chance to run.
        profile = self._profile()
        router.reevaluate_state(profile, {"P": 0.6}, zones=set())
        clock.advance(5.0)
        router.reevaluate_state(profile, {"P": 0.6}, zones=set())
        assert router.needs_settling() is True


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


# ============================================================ Tier 3.35: zero cut

class TestZeroCut:
    """The chain's final override: while the raw input reads at/below
    the zero threshold (plug removed), the output snaps to 0 instantly
    instead of riding the smoothing fall tail / speed ring down."""

    def _cfg(self, enabled=True, threshold=0.0, **smoothing):
        cfg = _basic_motor_cfg(osc_addresses={"0": ["P"]})
        chain = cfg["mix"]["0"]["chains"][0]
        chain["smoothing"] = {
            "rise_ms": smoothing.get("rise_ms", 0.0),
            "fall_ms": smoothing.get("fall_ms", 500.0),
        }
        chain["zerocut"] = {"enabled": enabled, "threshold": threshold}
        return cfg

    def test_default_chain_config_has_zerocut_disabled(self):
        zc = MotorRouter.DEFAULT_MIX_CONFIG["chains"][0]["zerocut"]
        assert zc == {"enabled": False, "threshold": 0.0}

    def test_disabled_removal_leaves_a_fall_tail(self, router, clock):
        # Baseline: with the cut off, pulling out rides the 500 ms fall.
        cfg = self._cfg(enabled=False)
        router._calculate_motor_target("dev", 0, cfg, {"P": 1.0}, zones=set())
        clock.advance(0.05)
        out = router._calculate_motor_target("dev", 0, cfg, {"P": 0.0}, zones=set())
        assert out > 0.5, f"expected a decaying tail, got {out}"

    def test_enabled_removal_cuts_to_zero_instantly(self, router, clock):
        cfg = self._cfg(enabled=True)
        router._calculate_motor_target("dev", 0, cfg, {"P": 1.0}, zones=set())
        clock.advance(0.05)
        out = router._calculate_motor_target("dev", 0, cfg, {"P": 0.0}, zones=set())
        assert out == 0.0

    def test_enabled_does_not_touch_live_signal(self, router, clock):
        # Input above the threshold: the cut is a bystander.
        cfg = self._cfg(enabled=True)
        router._calculate_motor_target("dev", 0, cfg, {"P": 0.8}, zones=set())
        clock.advance(0.05)
        out = router._calculate_motor_target("dev", 0, cfg, {"P": 0.8}, zones=set())
        assert out == pytest.approx(0.8)

    def test_threshold_treats_near_zero_as_removed(self, router, clock):
        # A contact idling at 0.05 with threshold 0.1 counts as "out".
        cfg = self._cfg(enabled=True, threshold=0.1)
        router._calculate_motor_target("dev", 0, cfg, {"P": 1.0}, zones=set())
        clock.advance(0.05)
        out = router._calculate_motor_target("dev", 0, cfg, {"P": 0.05}, zones=set())
        assert out == 0.0

    def test_cut_kills_the_speed_ring_too(self, router, clock):
        # The speed channel keeps ringing after movement stops (decay_ms);
        # the cut must override that as well, not just the smoothing tail.
        cfg = self._cfg(enabled=True, fall_ms=0.0)
        chain = cfg["mix"]["0"]["chains"][0]
        chain["speed"] = {"gain": 1.0, "curve": "linear", "curve_param": 1.0,
                          "decay_ms": 2000.0}
        router._calculate_motor_target("dev", 0, cfg, {"P": 0.0}, zones=set())
        clock.advance(0.05)
        # Vigorous stroke charges the speed channel to saturation…
        router._calculate_motor_target("dev", 0, cfg, {"P": 0.8}, zones=set())
        clock.advance(0.05)
        # …then the plug comes out. The removal itself is a huge |d/dt|
        # spike, so without the cut the ring would drive the motor hard.
        out = router._calculate_motor_target("dev", 0, cfg, {"P": 0.0}, zones=set())
        assert out == 0.0

    def test_reinsert_attacks_from_silence_not_the_old_tail(self, router, clock):
        # The cut resets the envelope: a quick re-insert must rise from 0
        # (fresh attack), not resume near the pre-removal level.
        cfg = self._cfg(enabled=True, rise_ms=100.0, fall_ms=2000.0)
        router._calculate_motor_target("dev", 0, cfg, {"P": 1.0}, zones=set())
        clock.advance(0.05)
        out = router._calculate_motor_target("dev", 0, cfg, {"P": 0.0}, zones=set())
        assert out == 0.0
        clock.advance(0.05)
        out = router._calculate_motor_target("dev", 0, cfg, {"P": 1.0}, zones=set())
        # 50 ms into a 100 ms rise from zero ≈ 0.39; resuming the
        # near-full 2 s tail would put it above 0.9.
        assert 0.0 < out < 0.5, f"expected a fresh attack from 0, got {out}"

    def test_non_dict_zerocut_is_treated_as_disabled(self, router, clock):
        # Hand-edited profile: `"zerocut": true`. Must not crash the hot
        # loop; behaves as if the stage were absent (tail persists).
        cfg = self._cfg(enabled=False)
        cfg["mix"]["0"]["chains"][0]["zerocut"] = True
        router._calculate_motor_target("dev", 0, cfg, {"P": 1.0}, zones=set())
        clock.advance(0.05)
        out = router._calculate_motor_target("dev", 0, cfg, {"P": 0.0}, zones=set())
        assert out > 0.5

    def test_nan_threshold_falls_back_to_default_and_still_cuts(self, router, clock):
        # json round-trips bare NaN; a NaN threshold must not silently
        # disable an enabled cut (NaN comparisons are always False).
        cfg = self._cfg(enabled=True, threshold=float("nan"))
        router._calculate_motor_target("dev", 0, cfg, {"P": 1.0}, zones=set())
        clock.advance(0.05)
        out = router._calculate_motor_target("dev", 0, cfg, {"P": 0.0}, zones=set())
        assert out == 0.0

    def test_cut_zeroes_only_its_own_chain_in_a_merge(self, router, clock):
        # Two chains, max-merge: chain 0 has the cut and rides the live
        # input; chain 1 is simulator-driven (provider) and stays hot.
        # Cutting chain 0 must not silence chain 1's contribution.
        cfg = self._cfg(enabled=True)
        import copy as _copy
        chain1 = _copy.deepcopy(cfg["mix"]["0"]["chains"][0])
        chain1["zerocut"] = {"enabled": False, "threshold": 0.0}
        cfg["mix"]["0"]["chains"].append(chain1)
        cfg["mix"]["0"]["merge"] = "max"
        router.set_chain_value_provider("dev", 0, 1, lambda: 0.6)
        router._calculate_motor_target("dev", 0, cfg, {"P": 1.0}, zones=set())
        clock.advance(0.05)
        out = router._calculate_motor_target("dev", 0, cfg, {"P": 0.0}, zones=set())
        # Chain 0 cut to 0; chain 1 still driven at 0.6 by its provider.
        assert out == pytest.approx(0.6)

    def test_emits_pre_cut_smoothed_and_final_out(self, router, clock):
        # The Smoothing card graphs the tail it computed ("smoothed");
        # the Zero cut card shows that tail being cut to "out".
        cfg = self._cfg(enabled=True)
        captured = []
        router.subscribe_intermediates("dev", 0, 0, captured.append)
        router._calculate_motor_target("dev", 0, cfg, {"P": 1.0}, zones=set())
        clock.advance(0.05)
        router._calculate_motor_target("dev", 0, cfg, {"P": 0.0}, zones=set())
        assert captured, "intermediates subscriber never fired"
        last = captured[-1]
        assert last["smoothed"] > 0.5   # the tail the smoother produced
        assert last["out"] == 0.0       # …cut to silence


# ============================================================ Tier 3.3b: punch

class TestPunch:
    """Third parallel source next to Depth and Speed: a fast RISE in
    depth strikes an impulse that decays quickly and merges max-wins
    after the depth/speed combine."""

    def _cfg(self, gain=1.0, decay_ms=120.0, depth_gain=0.3):
        cfg = _basic_motor_cfg(osc_addresses={"0": ["P"]})
        chain = cfg["mix"]["0"]["chains"][0]
        chain["depth"]["gain"] = depth_gain
        chain["punch"] = {"gain": gain, "decay_ms": decay_ms}
        return cfg

    def test_default_chain_config_has_punch_off(self):
        p = MotorRouter.DEFAULT_MIX_CONFIG["chains"][0]["punch"]
        assert p == {"gain": 0.0, "decay_ms": 120.0}

    def test_fast_rise_strikes_above_the_depth_level(self, router, clock):
        cfg = self._cfg()
        router._calculate_motor_target("dev", 0, cfg, {"P": 0.0}, zones=set())
        clock.advance(0.1)
        # 0 → 0.6 in 100 ms = 6.0/s — a full-strength hit; depth alone
        # would only read 0.6 * 0.3 = 0.18.
        out = router._calculate_motor_target("dev", 0, cfg, {"P": 0.6}, zones=set())
        assert out == pytest.approx(1.0)

    def test_envelope_decays_after_the_hit(self, router, clock):
        cfg = self._cfg(decay_ms=120.0)
        router._calculate_motor_target("dev", 0, cfg, {"P": 0.0}, zones=set())
        clock.advance(0.1)
        router._calculate_motor_target("dev", 0, cfg, {"P": 0.6}, zones=set())
        clock.advance(0.12)   # one decay tau, input held still
        out = router._calculate_motor_target("dev", 0, cfg, {"P": 0.6}, zones=set())
        assert out == pytest.approx(0.3679, abs=0.01)   # e^-1

    def test_slow_rise_never_ticks_the_envelope(self, router, clock):
        # 0.02 over 100 ms = 0.2/s — below the jitter deadband.
        cfg = self._cfg(gain=2.0, depth_gain=0.0)
        router._calculate_motor_target("dev", 0, cfg, {"P": 0.0}, zones=set())
        clock.advance(0.1)
        out = router._calculate_motor_target("dev", 0, cfg, {"P": 0.02}, zones=set())
        assert out == 0.0

    def test_pull_out_is_not_a_punch(self, router, clock):
        cfg = self._cfg(gain=1.0, depth_gain=0.0)
        router._calculate_motor_target("dev", 0, cfg, {"P": 1.0}, zones=set())
        clock.advance(2.0)    # any earlier strike has fully decayed
        router._calculate_motor_target("dev", 0, cfg, {"P": 1.0}, zones=set())
        clock.advance(0.05)
        # Fast REMOVAL: huge negative rate — must contribute nothing.
        out = router._calculate_motor_target("dev", 0, cfg, {"P": 0.0}, zones=set())
        assert out == 0.0

    def test_gain_zero_is_off(self, router, clock):
        cfg = self._cfg(gain=0.0)
        router._calculate_motor_target("dev", 0, cfg, {"P": 0.0}, zones=set())
        clock.advance(0.1)
        out = router._calculate_motor_target("dev", 0, cfg, {"P": 0.6}, zones=set())
        assert out == pytest.approx(0.18)   # depth only (0.6 * 0.3)

    def test_enabling_mid_hold_reads_no_phantom_rise(self, router, clock):
        # While punch is off its position memory keeps tracking, so
        # flipping it on mid-hold must not read the held depth as one
        # giant rise.
        cfg = self._cfg(gain=0.0, depth_gain=0.0)
        router._calculate_motor_target("dev", 0, cfg, {"P": 1.0}, zones=set())
        clock.advance(0.1)
        router._calculate_motor_target("dev", 0, cfg, {"P": 1.0}, zones=set())
        cfg["mix"]["0"]["chains"][0]["punch"]["gain"] = 1.0
        clock.advance(0.1)
        out = router._calculate_motor_target("dev", 0, cfg, {"P": 1.0}, zones=set())
        assert out == 0.0

    def test_punch_overrides_a_multiply_combine(self, router, clock):
        # combine=multiply with a silent speed channel yields 0 — the
        # accent must still land (it merges max-wins after the combine).
        cfg = self._cfg(gain=1.0)
        cfg["mix"]["0"]["chains"][0]["combine"] = "multiply"
        router._calculate_motor_target("dev", 0, cfg, {"P": 0.0}, zones=set())
        clock.advance(0.1)
        out = router._calculate_motor_target("dev", 0, cfg, {"P": 0.6}, zones=set())
        assert out == pytest.approx(1.0)

    def test_punch_rides_the_emit_stream(self, router, clock):
        cfg = self._cfg()
        captured = []
        router.subscribe_intermediates("dev", 0, 0, captured.append)
        router._calculate_motor_target("dev", 0, cfg, {"P": 0.0}, zones=set())
        clock.advance(0.1)
        router._calculate_motor_target("dev", 0, cfg, {"P": 0.6}, zones=set())
        assert captured[-1]["punch"] == pytest.approx(1.0)


# ============================================================ Tier 3.3d: arming

class TestArming:
    """The sleep gate: output stays silent until N full strokes land
    inside the window, stays armed while strokes keep coming, and
    disarms after a quiet spell."""

    def _cfg(self, enabled=True, thrusts=3, window_s=6.0,
             disarm_after_s=45.0):
        cfg = _basic_motor_cfg(osc_addresses={"0": ["P"]})
        cfg["mix"]["0"]["chains"][0]["arming"] = {
            "enabled": enabled, "thrusts": thrusts,
            "window_s": window_s, "disarm_after_s": disarm_after_s,
        }
        return cfg

    def _stroke(self, router, clock, cfg, depth=0.8, half_s=0.15):
        """One full in-out stroke: rise to `depth`, fall back to ~0."""
        clock.advance(half_s)
        router._calculate_motor_target("dev", 0, cfg, {"P": depth}, zones=set())
        clock.advance(half_s)
        out = router._calculate_motor_target("dev", 0, cfg, {"P": 0.02}, zones=set())
        return out

    def test_default_chain_config_has_arming_off(self):
        a = MotorRouter.DEFAULT_MIX_CONFIG["chains"][0]["arming"]
        assert a == {"enabled": False, "thrusts": 3, "window_s": 6.0,
                     "disarm_after_s": 45.0}

    def test_idle_contact_stays_silent(self, router, clock):
        # Resting against the receiver at half depth: no strokes, no output.
        cfg = self._cfg()
        router._calculate_motor_target("dev", 0, cfg, {"P": 0.5}, zones=set())
        clock.advance(1.0)
        out = router._calculate_motor_target("dev", 0, cfg, {"P": 0.5}, zones=set())
        assert out == 0.0

    def test_one_stroke_is_not_enough(self, router, clock):
        cfg = self._cfg(thrusts=3)
        router._calculate_motor_target("dev", 0, cfg, {"P": 0.0}, zones=set())
        self._stroke(router, clock, cfg)
        clock.advance(0.1)
        out = router._calculate_motor_target("dev", 0, cfg, {"P": 0.8}, zones=set())
        assert out == 0.0

    def test_n_strokes_inside_the_window_arm_the_chain(self, router, clock):
        cfg = self._cfg(thrusts=3, window_s=6.0)
        router._calculate_motor_target("dev", 0, cfg, {"P": 0.0}, zones=set())
        for _ in range(3):
            self._stroke(router, clock, cfg)
        clock.advance(0.1)
        out = router._calculate_motor_target("dev", 0, cfg, {"P": 0.8}, zones=set())
        assert out == pytest.approx(0.8)

    def test_strokes_spread_past_the_window_never_arm(self, router, clock):
        cfg = self._cfg(thrusts=3, window_s=2.0)
        router._calculate_motor_target("dev", 0, cfg, {"P": 0.0}, zones=set())
        for _ in range(3):
            self._stroke(router, clock, cfg)
            clock.advance(3.0)   # each stroke ages out before the next
            router._calculate_motor_target("dev", 0, cfg, {"P": 0.02}, zones=set())
        out = router._calculate_motor_target("dev", 0, cfg, {"P": 0.8}, zones=set())
        assert out == 0.0

    def test_quiet_spell_disarms_again(self, router, clock):
        cfg = self._cfg(thrusts=2, window_s=6.0, disarm_after_s=10.0)
        router._calculate_motor_target("dev", 0, cfg, {"P": 0.0}, zones=set())
        for _ in range(2):
            self._stroke(router, clock, cfg)
        clock.advance(0.1)
        assert router._calculate_motor_target(
            "dev", 0, cfg, {"P": 0.8}, zones=set()) > 0.0
        # Hold still past the disarm timeout: back to silence.
        clock.advance(11.0)
        out = router._calculate_motor_target("dev", 0, cfg, {"P": 0.8}, zones=set())
        assert out == 0.0

    def test_shallow_jitter_never_ticks_the_counter(self, router, clock):
        # Swings under the hysteresis floor (0.15) are OSC jitter, not
        # strokes — even many of them must not arm the chain.
        cfg = self._cfg(thrusts=2)
        router._calculate_motor_target("dev", 0, cfg, {"P": 0.5}, zones=set())
        for i in range(20):
            clock.advance(0.1)
            p = 0.5 + (0.05 if i % 2 == 0 else -0.05)
            router._calculate_motor_target("dev", 0, cfg, {"P": p}, zones=set())
        out = router._calculate_motor_target("dev", 0, cfg, {"P": 0.55}, zones=set())
        assert out == 0.0

    def test_disabled_is_passthrough(self, router, clock):
        cfg = self._cfg(enabled=False)
        router._calculate_motor_target("dev", 0, cfg, {"P": 0.0}, zones=set())
        clock.advance(0.1)
        out = router._calculate_motor_target("dev", 0, cfg, {"P": 0.8}, zones=set())
        assert out == pytest.approx(0.8)

    def test_brush_after_a_tick_gap_cannot_cancel_an_overdue_disarm(
            self, router, clock):
        # Regression: ticks stop while all outputs are 0 (silent VRChat),
        # so the disarm deadline may first be evaluated hours late — on
        # the SAME tick a brush lands. The brush used to refresh
        # last_thrust_t before the deadline check, keeping the chain
        # armed; it must instead count as stroke 1-of-N toward re-arming.
        cfg = self._cfg(thrusts=3, window_s=6.0, disarm_after_s=45.0)
        router._calculate_motor_target("dev", 0, cfg, {"P": 0.0}, zones=set())
        for _ in range(3):
            self._stroke(router, clock, cfg)
        clock.advance(0.1)
        # Armed: partner pushes fully in, then the OSC stream freezes.
        assert router._calculate_motor_target(
            "dev", 0, cfg, {"P": 0.95}, zones=set()) > 0.0
        clock.advance(3 * 3600.0)   # hours of silence, zero ticks
        # A single pull-out-shaped brush event arrives.
        out = router._calculate_motor_target(
            "dev", 0, cfg, {"P": 0.4}, zones=set())
        assert out == 0.0
        clock.advance(0.1)
        out = router._calculate_motor_target(
            "dev", 0, cfg, {"P": 0.4}, zones=set())
        assert out == 0.0

    def test_reenabling_arming_reads_no_phantom_stroke(self, router, clock):
        # Regression: motion while arming was disabled left the swing
        # detector's extremes stale; re-enabling then counted the old
        # rise + a new fall as one phantom stroke (instant arm at
        # thrusts=1, the editor's minimum).
        cfg = self._cfg(enabled=True, thrusts=1)
        cfg["mix"]["0"]["chains"][0]["arming"]["enabled"] = False
        router._calculate_motor_target("dev", 0, cfg, {"P": 0.0}, zones=set())
        clock.advance(0.15)
        router._calculate_motor_target("dev", 0, cfg, {"P": 0.8}, zones=set())
        clock.advance(0.15)
        router._calculate_motor_target("dev", 0, cfg, {"P": 0.8}, zones=set())
        cfg["mix"]["0"]["chains"][0]["arming"]["enabled"] = True
        clock.advance(0.15)
        out = router._calculate_motor_target(
            "dev", 0, cfg, {"P": 0.02}, zones=set())
        assert out == 0.0
        clock.advance(0.15)
        out = router._calculate_motor_target(
            "dev", 0, cfg, {"P": 0.5}, zones=set())
        assert out == 0.0   # still disarmed: no phantom stroke counted

    def test_armed_state_rides_the_emit_stream(self, router, clock):
        cfg = self._cfg(thrusts=2)
        captured = []
        router.subscribe_intermediates("dev", 0, 0, captured.append)
        router._calculate_motor_target("dev", 0, cfg, {"P": 0.0}, zones=set())
        assert captured[-1]["armed"] is False
        for _ in range(2):
            self._stroke(router, clock, cfg)
        assert captured[-1]["armed"] is True
        assert captured[-1]["thrusts"] == 2


# ============================================================ Tier 3.3c: texture

class TestTexture:
    """Post-smoothing wobble: downward-only modulation of the held level
    (never exceeds it, never parks it at zero), animated by the settling
    tick between OSC events."""

    def _cfg(self, enabled=True, amount=0.5, rate_hz=2.5, follow=False):
        cfg = _basic_motor_cfg(osc_addresses={"0": ["P"]})
        cfg["mix"]["0"]["chains"][0]["texture"] = {
            "enabled": enabled, "amount": amount,
            "rate_hz": rate_hz, "follow_speed": follow,
        }
        return cfg

    def _run_held(self, router, clock, cfg, level=0.8, ticks=60, dt=1 / 60):
        router._calculate_motor_target("dev", 0, cfg, {"P": level}, zones=set())
        outs = []
        for _ in range(ticks):
            clock.advance(dt)
            outs.append(router._calculate_motor_target(
                "dev", 0, cfg, {"P": level}, zones=set()))
        return outs

    def test_default_chain_config_has_texture_off(self):
        t = MotorRouter.DEFAULT_MIX_CONFIG["chains"][0]["texture"]
        assert t == {"enabled": False, "amount": 0.25,
                     "rate_hz": 2.0, "follow_speed": False}

    def test_disabled_is_identity(self, router, clock):
        outs = self._run_held(router, clock, self._cfg(enabled=False))
        assert all(o == pytest.approx(0.8) for o in outs)

    def test_wobble_stays_inside_the_downward_band(self, router, clock):
        # amount 0.5 on a held 0.8: outputs sweep [0.4, 0.8], never above.
        outs = self._run_held(router, clock, self._cfg(amount=0.5))
        assert max(outs) <= 0.8 + 1e-9
        assert max(outs) > 0.75          # crest reaches the level
        assert min(outs) == pytest.approx(0.4, abs=0.03)   # trough
        assert min(outs) > 0.0

    def test_activation_starts_at_full_level(self, router, clock):
        cfg = self._cfg(amount=0.9)
        router._calculate_motor_target("dev", 0, cfg, {"P": 0.0}, zones=set())
        clock.advance(0.01)
        out = router._calculate_motor_target("dev", 0, cfg, {"P": 0.8}, zones=set())
        # First driven tick: phase parked at the wobble top — the attack
        # lands at (almost) full level, then the grain begins.
        assert out == pytest.approx(0.8, abs=0.02)

    def test_full_amount_never_parks_output_at_zero(self, router, clock):
        # amount clamps at 0.9: the trough floor keeps needs_settling()
        # true so the LFO can't freeze a driven motor at exactly zero.
        outs = self._run_held(router, clock, self._cfg(amount=1.0), level=1.0)
        assert min(outs) > 0.0
        assert min(outs) == pytest.approx(0.1, abs=0.03)

    def test_follow_speed_is_inert_while_holding_still(self, router, clock):
        # With no motion the speed signal is 0, so follow_speed must not
        # change the wobble at all.
        plain = self._run_held(router, clock, self._cfg(follow=False))
        router2 = MotorRouter(clock=clock.now)
        follow = self._run_held(router2, clock, self._cfg(follow=True))
        assert plain == pytest.approx(follow)

    def test_zerocut_still_wins(self, router, clock):
        cfg = self._cfg(amount=0.5)
        cfg["mix"]["0"]["chains"][0]["zerocut"] = {
            "enabled": True, "threshold": 0.0}
        cfg["mix"]["0"]["chains"][0]["smoothing"] = {
            "rise_ms": 0.0, "fall_ms": 500.0}
        router._calculate_motor_target("dev", 0, cfg, {"P": 0.8}, zones=set())
        clock.advance(0.05)
        out = router._calculate_motor_target("dev", 0, cfg, {"P": 0.0}, zones=set())
        assert out == 0.0

    def test_textured_rides_the_emit_stream(self, router, clock):
        cfg = self._cfg(amount=0.5)
        captured = []
        router.subscribe_intermediates("dev", 0, 0, captured.append)
        self._run_held(router, clock, cfg)
        last = captured[-1]
        assert last["textured"] == last["out"]
        assert last["smoothed"] == pytest.approx(0.8)


# ============================================================ Tier 3.4: speed fall-off

class TestSpeedFalloffIntegration:
    """Per-chain `speed.decay_ms` threaded through the speed detector.
    The depth channel is muted (gain 0) so the output is the speed
    channel alone, and smoothing is disabled so the detector's decay
    is the only time constant in play."""

    def _speed_cfg(self, decay_ms=None):
        cfg = _basic_motor_cfg(osc_addresses={"0": ["P"]})
        chain = cfg["mix"]["0"]["chains"][0]
        chain["depth"]["gain"] = 0.0
        chain["speed"] = {"gain": 1.0, "curve": "linear", "curve_param": 1.0}
        if decay_ms is not None:
            chain["speed"]["decay_ms"] = decay_ms
        chain["smoothing"] = {"rise_ms": 0.0, "fall_ms": 0.0}
        return cfg

    def _charge_then_stop(self, router, clock, cfg, settle_s):
        """Drive a vigorous stroke until the speed channel saturates,
        then hold the position still for `settle_s` seconds and return
        the final output."""
        router._calculate_motor_target("dev", 0, cfg, {"P": 0.0}, zones=set())
        for i in range(10):
            clock.advance(0.03)
            p = 0.5 if i % 2 == 0 else 0.0
            router._calculate_motor_target("dev", 0, cfg, {"P": p}, zones=set())
        out = None
        ticks = int(round(settle_s / 0.02))
        for _ in range(ticks):
            clock.advance(0.02)
            out = router._calculate_motor_target(
                "dev", 0, cfg, {"P": 0.0}, zones=set()
            )
        return out

    def test_stroke_saturates_speed_channel(self, router, clock):
        # Sanity for the helper: right after the stroke the channel is hot.
        cfg = self._speed_cfg(decay_ms=300.0)
        out = self._charge_then_stop(router, clock, cfg, settle_s=0.02)
        assert out > 0.8

    def test_short_falloff_cuts_speed_quickly(self, router, clock):
        # 50 ms tau: 0.4 s of stillness is 8 taus → far below the
        # output cutoff → exact 0. This is the user-facing fix for
        # "the toy keeps going after I stopped".
        cfg = self._speed_cfg(decay_ms=50.0)
        out = self._charge_then_stop(router, clock, cfg, settle_s=0.4)
        assert out == 0.0

    def test_long_falloff_keeps_speed_ringing(self, router, clock):
        # 1 s tau: 0.4 s of stillness only sheds ~1/3 of the charge.
        cfg = self._speed_cfg(decay_ms=1000.0)
        out = self._charge_then_stop(router, clock, cfg, settle_s=0.4)
        assert out > 0.4

    def test_missing_field_falls_back_to_300ms(self, router, clock):
        # Profiles written before the knob existed keep the original
        # 300 ms feel: after 0.4 s ≈ e^(-4/3) ≈ 0.26 of the charge left.
        cfg = self._speed_cfg(decay_ms=None)
        out = self._charge_then_stop(router, clock, cfg, settle_s=0.4)
        assert 0.05 < out < 0.5

    def test_falloff_clamped_to_floor(self, router, clock):
        # An absurd 0 ms from a hand-edited profile clamps to the 10 ms
        # floor (no division-by-zero in the exp decay) and the channel
        # still dies out smoothly after the stroke.
        cfg = self._speed_cfg(decay_ms=0.0)
        out = self._charge_then_stop(router, clock, cfg, settle_s=0.2)
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

    def test_slow_buildup_requires_sustained_movement(self, router, clock):
        # `gate.attack_s` is the "Build-up" knob: with a 2 s tau and a
        # 0.5 threshold the meter needs ~1.4 s of continuous movement
        # to wake the gate — a brief twitch is ignored entirely.
        cfg = self._gate_cfg(wake_threshold=0.5, sleep_delay_s=0.5,
                             attack_s=2.0, release_s=0.5)
        router._calculate_motor_target("dev", 0, cfg, {"P": 0.0}, zones=set())
        # ~0.3 s of vigorous movement: with the default 50 ms attack
        # this would already be wide open; with 2 s it must stay shut.
        for i in range(10):
            clock.advance(0.03)
            p = 0.5 if i % 2 == 0 else 0.0
            router._calculate_motor_target("dev", 0, cfg, {"P": p}, zones=set())
        chain_state = router._motor_state[("dev", 0)]["chains"][0]
        assert chain_state["gate_open"] is False
        assert chain_state["activity_meter"] < 0.5
        # Keep going to ~2.4 s total — now the budget has built up.
        for i in range(70):
            clock.advance(0.03)
            p = 0.5 if i % 2 == 0 else 0.0
            router._calculate_motor_target("dev", 0, cfg, {"P": p}, zones=set())
        chain_state = router._motor_state[("dev", 0)]["chains"][0]
        assert chain_state["gate_open"] is True

    def test_slow_release_coasts_across_pauses(self, router, clock):
        # `gate.release_s` is the "Decay" knob: a 5 s tau keeps the
        # charged meter above threshold through a 1 s pause, where the
        # default 0.5 s tau would have dropped it long since.
        def run(device, release_s):
            cfg = self._gate_cfg(wake_threshold=0.3, sleep_delay_s=0.0,
                                 attack_s=0.05, release_s=release_s)
            router._calculate_motor_target(device, 0, cfg, {"P": 0.0}, zones=set())
            for i in range(20):
                clock.advance(0.03)
                p = 0.5 if i % 2 == 0 else 0.0
                router._calculate_motor_target(device, 0, cfg, {"P": p}, zones=set())
            assert router._motor_state[(device, 0)]["chains"][0]["gate_open"] is True
            # 1 s pause, motionless. sleep_delay 0 → the gate closes the
            # moment the meter dips below threshold; staying open means
            # the meter itself stayed charged.
            for _ in range(50):
                clock.advance(0.02)
                router._calculate_motor_target(device, 0, cfg, {"P": 0.4}, zones=set())
            return router._motor_state[(device, 0)]["chains"][0]

        slow = run("devSlow", 5.0)
        fast = run("devFast", 0.1)
        assert slow["gate_open"] is True
        assert slow["activity_meter"] > 0.3
        assert fast["gate_open"] is False

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


# ============================================================ Anti-stuck cutoff

class TestAntiStuck:
    """Per-resolved-input stuck-value safety cutoff. VRChat only sends OSC
    on parameter change, so a frozen SPS proximity must not drive a toy
    forever. Two-timer model: mid-range static is cut hard after the active
    timeout; saturated (~1.0) static gets the longer peaked fuse then ramps.
    Detection is on combined d_raw; the cut scales the final output without
    perturbing the speed detector or smoothing envelope."""

    def _cfg(self):
        # Depth-only pass-through, no smoothing — so the output equals the
        # held input times the anti-stuck factor, making the math assertable.
        return _basic_motor_cfg(osc_addresses={"0": ["P"]})

    def _on(self, active_s=2.0, peaked_s=10.0):
        return {"enabled": True, "active_s": active_s, "peaked_s": peaked_s}

    def _drive(self, router, cfg, p, asc):
        return router._calculate_motor_target(
            "dev", 0, cfg, {"P": p}, zones=set(), antistuck=asc
        )

    def test_default_none_never_cuts(self, router, clock):
        # Backward compat: no antistuck arg (default None) holds forever.
        cfg = self._cfg()
        out = router._calculate_motor_target("dev", 0, cfg, {"P": 0.5}, zones=set())
        assert out == pytest.approx(0.5)
        for _ in range(200):
            clock.advance(0.05)  # 10 s of frozen input
            out = router._calculate_motor_target("dev", 0, cfg, {"P": 0.5}, zones=set())
        assert out == pytest.approx(0.5)

    def test_disabled_config_never_cuts(self, router, clock):
        cfg = self._cfg()
        off = {"enabled": False, "active_s": 2.0, "peaked_s": 10.0}
        out = self._drive(router, cfg, 0.5, off)
        assert out == pytest.approx(0.5)
        clock.advance(60.0)
        out = self._drive(router, cfg, 0.5, off)
        assert out == pytest.approx(0.5)

    def test_midrange_static_cut_after_active_timeout(self, router, clock):
        cfg = self._cfg()
        asc = self._on(active_s=2.0, peaked_s=10.0)
        assert self._drive(router, cfg, 0.5, asc) == pytest.approx(0.5)
        clock.advance(1.9)
        assert self._drive(router, cfg, 0.5, asc) == pytest.approx(0.5)
        clock.advance(0.2)  # crosses 2.0 s static
        assert self._drive(router, cfg, 0.5, asc) == 0.0

    def test_stays_cut_until_input_changes(self, router, clock):
        cfg = self._cfg()
        asc = self._on(active_s=2.0, peaked_s=10.0)
        self._drive(router, cfg, 0.5, asc)
        clock.advance(2.1)
        assert self._drive(router, cfg, 0.5, asc) == 0.0
        # Still frozen → still cut.
        clock.advance(5.0)
        assert self._drive(router, cfg, 0.5, asc) == 0.0
        # Input finally moves → fuse resets, output follows immediately.
        clock.advance(0.05)
        assert self._drive(router, cfg, 0.3, asc) == pytest.approx(0.3)

    def test_input_change_resets_fuse(self, router, clock):
        cfg = self._cfg()
        asc = self._on(active_s=2.0, peaked_s=10.0)
        self._drive(router, cfg, 0.5, asc)
        clock.advance(1.95)
        assert self._drive(router, cfg, 0.5, asc) == pytest.approx(0.5)
        # Change before the cut — fuse restarts from here.
        clock.advance(0.05)  # t=2.0, but input changes this tick
        assert self._drive(router, cfg, 0.6, asc) == pytest.approx(0.6)
        # 1.0 s after the change is still under the 2 s active timeout.
        clock.advance(1.0)
        assert self._drive(router, cfg, 0.6, asc) == pytest.approx(0.6)

    def test_saturated_holds_through_active_then_ramps(self, router, clock):
        cfg = self._cfg()
        asc = self._on(active_s=2.0, peaked_s=4.0)
        assert self._drive(router, cfg, 1.0, asc) == pytest.approx(1.0)
        # Past the active timeout but under the peaked fuse → still full.
        clock.advance(3.0)
        assert self._drive(router, cfg, 1.0, asc) == pytest.approx(1.0)
        # Halfway through the ramp (peaked 4 + 1.5 of the 3 s ramp = 5.5 s).
        clock.advance(2.5)
        assert self._drive(router, cfg, 1.0, asc) == pytest.approx(0.5)
        # Past peaked + full ramp window (4 + 3 = 7 s) → fully cut.
        clock.advance(1.6)
        assert self._drive(router, cfg, 1.0, asc) == 0.0

    def test_cut_does_not_perturb_speed_detector(self, router, clock):
        # The cut scales the final output, NOT d_raw — so the speed
        # detector still sees the true held value (no spoofed motion spike).
        cfg = self._cfg()
        asc = self._on(active_s=2.0, peaked_s=10.0)
        self._drive(router, cfg, 0.5, asc)
        clock.advance(2.1)
        assert self._drive(router, cfg, 0.5, asc) == 0.0
        chain_state = router._motor_state[("dev", 0)]["chains"][0]
        assert chain_state["last_position"] == pytest.approx(0.5)
        # Static input → no derived speed despite the output being cut.
        assert chain_state["smoothed_speed"] == pytest.approx(0.0)

    def test_enabling_midsession_does_not_instantly_fire(self, router, clock):
        # A value already static while the feature was OFF must not be cut
        # the instant the user enables it — the fuse starts fresh on enable.
        cfg = self._cfg()
        off = {"enabled": False, "active_s": 2.0, "peaked_s": 10.0}
        on = self._on(active_s=2.0, peaked_s=10.0)
        self._drive(router, cfg, 0.5, off)
        clock.advance(5.0)  # long static hold, but disabled
        assert self._drive(router, cfg, 0.5, off) == pytest.approx(0.5)
        # Enable now — output still passes (fuse reset while disabled).
        assert self._drive(router, cfg, 0.5, on) == pytest.approx(0.5)
        # Only cut after a fresh active timeout from the enable point.
        clock.advance(2.1)
        assert self._drive(router, cfg, 0.5, on) == 0.0

    def test_reevaluate_state_threads_antistuck(self, router, clock):
        # End-to-end through the public entry point the routing tick uses.
        profile = {
            "dev": {**_basic_motor_cfg(osc_addresses={"0": ["P"]}),
                    "motor_count": 1},
        }
        asc = self._on(active_s=2.0, peaked_s=10.0)
        updates = router.reevaluate_state(
            profile, {"P": 0.5}, zones=set(), antistuck=asc
        )
        assert updates == [("dev", pytest.approx(0.5), 0)]
        clock.advance(2.1)
        updates = router.reevaluate_state(
            profile, {"P": 0.5}, zones=set(), antistuck=asc
        )
        assert updates == [("dev", 0.0, 0)]


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
