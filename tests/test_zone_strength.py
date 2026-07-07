"""Tests for the shared OGB zone-strength evaluation (zone_strength.py).

Covers the close-gate / max-wins / synthetic-source-delegation logic now
shared by the bHaptics SPS-mirror and the OWO / PiShock / Coyote routers.
Pure functions — no engine, no thread, no AppData.
"""

import pytest

from zone_strength import truthy, zone_filter_strength


class TestTruthy:
    def test_none_is_false(self):
        assert truthy(None) is False

    def test_bool_passthrough(self):
        assert truthy(True) is True
        assert truthy(False) is False

    def test_number_threshold(self):
        assert truthy(1.0) is True
        assert truthy(0.6) is True
        assert truthy(0.5) is False
        assert truthy(0.0) is False

    def test_non_numeric_is_false(self):
        assert truthy("nope") is False


class TestZoneFilterStrength:
    def test_blank_zone_returns_zero(self):
        assert zone_filter_strength("", "Orf", ["TouchSelf"], {}) == 0.0

    def test_no_filters_returns_zero(self):
        assert zone_filter_strength("Boob", "Orf", [], {}) == 0.0

    def test_single_filter_passes_value(self):
        params = {"OGB/Orf/Boob/TouchSelf": 0.7,
                  "OGB/Orf/Boob/TouchSelfClose": True}
        assert zone_filter_strength("Boob", "Orf", ["TouchSelf"], params) == pytest.approx(0.7)

    def test_close_gate_false_blocks(self):
        params = {"OGB/Orf/Boob/TouchSelf": 0.7,
                  "OGB/Orf/Boob/TouchSelfClose": False}
        assert zone_filter_strength("Boob", "Orf", ["TouchSelf"], params) == 0.0

    def test_close_gate_absent_is_open(self):
        # Convention: no *Close key present = assume open (live).
        params = {"OGB/Orf/Boob/TouchSelf": 0.7}
        assert zone_filter_strength("Boob", "Orf", ["TouchSelf"], params) == pytest.approx(0.7)

    def test_max_across_filters(self):
        params = {
            "OGB/Orf/Boob/TouchSelf": 0.3, "OGB/Orf/Boob/TouchSelfClose": True,
            "OGB/Orf/Boob/TouchOthers": 0.8, "OGB/Orf/Boob/TouchOthersClose": True,
        }
        out = zone_filter_strength("Boob", "Orf", ["TouchSelf", "TouchOthers"], params)
        assert out == pytest.approx(0.8)

    def test_value_clamped_to_unit(self):
        assert zone_filter_strength("Boob", "Orf", ["TouchSelf"],
                                    {"OGB/Orf/Boob/TouchSelf": 1.5}) == 1.0
        assert zone_filter_strength("Boob", "Orf", ["TouchSelf"],
                                    {"OGB/Orf/Boob/TouchSelf": -0.3}) == 0.0

    def test_bad_value_silently_skipped(self):
        assert zone_filter_strength("Boob", "Orf", ["TouchSelf"],
                                    {"OGB/Orf/Boob/TouchSelf": "not a number"}) == 0.0

    @pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf")])
    def test_non_finite_value_is_zero_not_full_power(self, bad):
        # Regression: min(1.0, nan) returns 1.0 in CPython, so an unguarded
        # clamp turned one NaN packet into FULL strength on every backend
        # that resolves zones through this function (e-stim included).
        assert zone_filter_strength("Boob", "Orf", ["TouchSelf"],
                                    {"OGB/Orf/Boob/TouchSelf": bad}) == 0.0

    def test_non_finite_value_does_not_mask_other_filters(self):
        params = {
            "OGB/Orf/Boob/TouchSelf": float("nan"),
            "OGB/Orf/Boob/TouchOthers": 0.4,
        }
        out = zone_filter_strength("Boob", "Orf", ["TouchSelf", "TouchOthers"], params)
        assert out == pytest.approx(0.4)

    def test_pen_zone_type_path(self):
        params = {"OGB/Pen/Shaft/PenSelf": 0.6, "OGB/Pen/Shaft/PenSelfClose": True}
        assert zone_filter_strength("Shaft", "Pen", ["PenSelf"], params) == pytest.approx(0.6)

    def test_blank_zone_type_defaults_orf(self):
        params = {"OGB/Orf/Boob/TouchSelf": 0.4}
        assert zone_filter_strength("Boob", "", ["TouchSelf"], params) == pytest.approx(0.4)


class TestSyntheticSourceDelegation:
    def test_matching_source_uses_evaluator(self):
        # A source-named zone resolves through evaluate_sps_source, ignoring
        # filters/zone_type. Plain proximity 0.5, no gate -> 0.5.
        sources = {"GSpot": {
            "proximity": ["Contact/GSpotProx"], "activation": [],
            "velocity": [], "multiplier": 1.0, "max_value": 1.0,
        }}
        params = {"Contact/GSpotProx": 0.5}
        out = zone_filter_strength("GSpot", "Orf", ["TouchSelf"], params, sources)
        assert out == pytest.approx(0.5)

    def test_source_activation_gate_blocks(self):
        sources = {"GSpot": {
            "proximity": ["Contact/GSpotProx"], "activation": ["Contact/GSpotZone"],
            "velocity": [], "multiplier": 1.0, "max_value": 1.0,
        }}
        # Gate present-but-false -> 0 even though proximity reads high.
        params = {"Contact/GSpotProx": 0.9, "Contact/GSpotZone": False}
        assert zone_filter_strength("GSpot", "Orf", [], params, sources) == 0.0

    def test_non_matching_name_falls_through_to_ogb(self):
        # A zone not in the sources map still evaluates as a normal OGB zone.
        sources = {"Other": {"proximity": ["x"]}}
        params = {"OGB/Orf/Boob/TouchSelf": 0.7}
        out = zone_filter_strength("Boob", "Orf", ["TouchSelf"], params, sources)
        assert out == pytest.approx(0.7)

    def test_source_result_is_clamped_and_never_nan(self):
        # Whatever the synthetic evaluator returns, this chokepoint clamps to
        # [0, 1] and rejects non-finite — routers must never see NaN.
        sources = {"GSpot": {
            "proximity": ["Contact/GSpotProx"], "activation": [],
            "velocity": [], "multiplier": 1.0, "max_value": 1.0,
        }}
        params = {"Contact/GSpotProx": float("nan")}
        assert zone_filter_strength("GSpot", "Orf", [], params, sources) == 0.0
