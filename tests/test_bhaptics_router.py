"""Tests for the SPS -> bHaptics mirror compute in bhaptics_router.

The router itself is a polling thread with a real engine dependency,
so the SPS-mirror math lives in pure-function module-level helpers
(`_sps_entry_strength`, `compute_sps_mirror_dots`) that take a config
dict and a params dict and return per-dot intensities. Those are what
this file exercises."""

from typing import Any, Dict, List

import pytest

from bhaptics_router import (
    _sps_entry_strength,
    compute_sps_mirror_dots,
)


def _entry(**overrides) -> Dict[str, Any]:
    """Build a default mirror entry; overrides replace named keys."""
    base = {
        "name": "Boob",
        "ogb_zone": "Boob",
        "zone_type": "Orf",
        "filters": ["TouchSelf", "TouchOthers", "PenSelf", "PenOthers"],
        "position": "VestFront",
        "dot_indices": [5, 6, 9, 10],
        "gain": 1.0,
        "threshold": 0.0,
    }
    base.update(overrides)
    return base


# ============================================================ _sps_entry_strength

class TestEntryStrength:
    def test_no_filters_returns_zero(self):
        assert _sps_entry_strength(_entry(filters=[]), {}) == 0.0

    def test_no_zone_returns_zero(self):
        assert _sps_entry_strength(_entry(ogb_zone=""), {}) == 0.0

    def test_single_filter_passes_value(self):
        params = {
            "OGB/Orf/Boob/TouchSelf": 0.7,
            "OGB/Orf/Boob/TouchSelfClose": True,
        }
        assert _sps_entry_strength(_entry(filters=["TouchSelf"]), params) == pytest.approx(0.7)

    def test_close_gate_false_blocks(self):
        params = {
            "OGB/Orf/Boob/TouchSelf": 0.7,
            "OGB/Orf/Boob/TouchSelfClose": False,
        }
        assert _sps_entry_strength(_entry(filters=["TouchSelf"]), params) == 0.0

    def test_close_gate_absent_is_open(self):
        # Convention: no *Close key present = assume open (live).
        params = {"OGB/Orf/Boob/TouchSelf": 0.7}
        assert _sps_entry_strength(_entry(filters=["TouchSelf"]), params) == pytest.approx(0.7)

    def test_max_across_filters(self):
        params = {
            "OGB/Orf/Boob/TouchSelf": 0.3,
            "OGB/Orf/Boob/TouchSelfClose": True,
            "OGB/Orf/Boob/TouchOthers": 0.8,
            "OGB/Orf/Boob/TouchOthersClose": True,
            "OGB/Orf/Boob/PenSelf": 0.5,
        }
        out = _sps_entry_strength(_entry(), params)
        assert out == pytest.approx(0.8)

    def test_only_enabled_filters_contribute(self):
        params = {
            "OGB/Orf/Boob/TouchSelf": 0.3,
            "OGB/Orf/Boob/TouchSelfClose": True,
            "OGB/Orf/Boob/TouchOthers": 0.9,
            "OGB/Orf/Boob/TouchOthersClose": True,
        }
        # Entry only listens to TouchSelf — TouchOthers ignored.
        out = _sps_entry_strength(_entry(filters=["TouchSelf"]), params)
        assert out == pytest.approx(0.3)

    def test_value_clamped_to_unit(self):
        params = {"OGB/Orf/Boob/TouchSelf": 1.5}
        assert _sps_entry_strength(_entry(filters=["TouchSelf"]), params) == 1.0
        params = {"OGB/Orf/Boob/TouchSelf": -0.3}
        assert _sps_entry_strength(_entry(filters=["TouchSelf"]), params) == 0.0

    def test_bad_param_value_silently_skipped(self):
        params = {"OGB/Orf/Boob/TouchSelf": "not a number"}
        assert _sps_entry_strength(_entry(filters=["TouchSelf"]), params) == 0.0

    def test_pen_zone_type_path(self):
        params = {
            "OGB/Pen/Shaft/PenSelf": 0.6,
            "OGB/Pen/Shaft/PenSelfClose": True,
        }
        out = _sps_entry_strength(
            _entry(ogb_zone="Shaft", zone_type="Pen", filters=["PenSelf"]),
            params,
        )
        assert out == pytest.approx(0.6)


# ============================================================ compute_sps_mirror_dots

class TestComputeMirrorDots:

    def _params_boob_touch(self, val: float = 0.6) -> dict:
        return {
            "OGB/Orf/Boob/TouchSelf": val,
            "OGB/Orf/Boob/TouchSelfClose": True,
        }

    def test_disabled_mirror_returns_empty(self):
        cfg = {"enabled": False, "entries": [_entry()]}
        assert compute_sps_mirror_dots(cfg, self._params_boob_touch()) == {}

    def test_none_config_returns_empty(self):
        assert compute_sps_mirror_dots(None, self._params_boob_touch()) == {}

    def test_empty_entries_returns_empty(self):
        cfg = {"enabled": True, "entries": []}
        assert compute_sps_mirror_dots(cfg, self._params_boob_touch()) == {}

    def test_single_entry_projects_to_dots(self):
        cfg = {"enabled": True, "entries": [_entry(dot_indices=[5, 6, 9, 10])]}
        out = compute_sps_mirror_dots(cfg, self._params_boob_touch(0.6))
        assert out == {"VestFront": {5: pytest.approx(0.6),
                                     6: pytest.approx(0.6),
                                     9: pytest.approx(0.6),
                                     10: pytest.approx(0.6)}}

    def test_two_entries_overlapping_dots_max_wins(self):
        # Entry A drives dot 5 at 0.3; entry B drives dot 5 at 0.8.
        # Dot 5 should end up at 0.8.
        params = {
            "OGB/Orf/Boob/TouchSelf": 0.3,
            "OGB/Orf/Boob/TouchSelfClose": True,
            "OGB/Orf/Crotch/TouchSelf": 0.8,
            "OGB/Orf/Crotch/TouchSelfClose": True,
        }
        cfg = {"enabled": True, "entries": [
            _entry(ogb_zone="Boob",   filters=["TouchSelf"], dot_indices=[5, 6]),
            _entry(ogb_zone="Crotch", filters=["TouchSelf"], dot_indices=[5, 10]),
        ]}
        out = compute_sps_mirror_dots(cfg, params)
        assert out == {"VestFront": {5: pytest.approx(0.8),
                                     6: pytest.approx(0.3),
                                     10: pytest.approx(0.8)}}

    def test_threshold_deadband(self):
        # Threshold 0.5 vs strength 0.3 → no contribution.
        cfg = {"enabled": True, "entries": [
            _entry(filters=["TouchSelf"], dot_indices=[5], threshold=0.5),
        ]}
        out = compute_sps_mirror_dots(cfg, self._params_boob_touch(0.3))
        assert out == {}

    def test_threshold_subtracts_then_gain_scales(self):
        # strength 0.6, threshold 0.2, gain 1.0 → (0.6 - 0.2) * 1.0 = 0.4
        cfg = {"enabled": True, "entries": [
            _entry(filters=["TouchSelf"], dot_indices=[5],
                   threshold=0.2, gain=1.0),
        ]}
        out = compute_sps_mirror_dots(cfg, self._params_boob_touch(0.6))
        assert out == {"VestFront": {5: pytest.approx(0.4)}}

    def test_gain_amplifies_then_clamps_at_one(self):
        # strength 0.6, threshold 0, gain 2.0 → 1.2 → clamp to 1.0
        cfg = {"enabled": True, "entries": [
            _entry(filters=["TouchSelf"], dot_indices=[5], gain=2.0),
        ]}
        out = compute_sps_mirror_dots(cfg, self._params_boob_touch(0.6))
        assert out == {"VestFront": {5: pytest.approx(1.0)}}

    def test_close_gate_false_drops_entry(self):
        params = {
            "OGB/Orf/Boob/TouchSelf": 0.8,
            "OGB/Orf/Boob/TouchSelfClose": False,
        }
        cfg = {"enabled": True, "entries": [
            _entry(filters=["TouchSelf"], dot_indices=[5]),
        ]}
        assert compute_sps_mirror_dots(cfg, params) == {}

    def test_enabled_positions_filter(self):
        # Suit only has VestFront enabled — VestBack entry is dropped.
        params = {
            "OGB/Orf/Boob/TouchSelf": 0.5,
            "OGB/Orf/Boob/TouchSelfClose": True,
            "OGB/Orf/Booty/TouchSelf": 0.7,
            "OGB/Orf/Booty/TouchSelfClose": True,
        }
        cfg = {"enabled": True, "entries": [
            _entry(ogb_zone="Boob",  filters=["TouchSelf"],
                   position="VestFront", dot_indices=[5]),
            _entry(ogb_zone="Booty", filters=["TouchSelf"],
                   position="VestBack",  dot_indices=[13]),
        ]}
        out = compute_sps_mirror_dots(cfg, params, enabled_positions={"VestFront"})
        assert out == {"VestFront": {5: pytest.approx(0.5)}}

    def test_enabled_positions_none_means_no_filtering(self):
        # When the caller doesn't supply the set, every entry contributes.
        params = {
            "OGB/Orf/Boob/TouchSelf": 0.5,
            "OGB/Orf/Boob/TouchSelfClose": True,
        }
        cfg = {"enabled": True, "entries": [
            _entry(filters=["TouchSelf"], dot_indices=[5]),
        ]}
        out = compute_sps_mirror_dots(cfg, params)
        assert out == {"VestFront": {5: pytest.approx(0.5)}}

    def test_invalid_dot_index_silently_skipped(self):
        cfg = {"enabled": True, "entries": [
            _entry(filters=["TouchSelf"],
                   dot_indices=[5, "not a number", -3, 7]),
        ]}
        out = compute_sps_mirror_dots(cfg, self._params_boob_touch(0.5))
        # Only 5 and 7 should make it through.
        assert out == {"VestFront": {5: pytest.approx(0.5),
                                     7: pytest.approx(0.5)}}

    def test_empty_position_string_silently_skipped(self):
        cfg = {"enabled": True, "entries": [
            _entry(position="", filters=["TouchSelf"], dot_indices=[5]),
        ]}
        out = compute_sps_mirror_dots(cfg, self._params_boob_touch(0.5))
        assert out == {}

    def test_non_dict_entry_silently_skipped(self):
        cfg = {"enabled": True, "entries": [
            None,
            "not a dict",
            _entry(filters=["TouchSelf"], dot_indices=[5]),
        ]}
        out = compute_sps_mirror_dots(cfg, self._params_boob_touch(0.5))
        assert out == {"VestFront": {5: pytest.approx(0.5)}}
