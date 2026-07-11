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


# ============================================================ schema detection

from types import SimpleNamespace

import bhaptics_router
from bhaptics_router import BHapticsRouter, detected_positions


def _zone_params(strength=0.6, zone="Boob", f="TouchOthers"):
    return {
        f"OGB/Orf/{zone}/{f}Close": True,
        f"OGB/Orf/{zone}/{f}": strength,
    }


class TestDetectedPositions:
    def test_detects_both_schemas(self):
        params = {"bHaptics_Vest_Front_1_bool": True, "bOSC_v1_HandL_2": 0.4}
        assert detected_positions(params) == {"VestFront", "HandL"}

    def test_empty_params_detect_nothing(self):
        assert detected_positions({}) == set()


# ============================================================ router _tick
# Driven directly with a fake engine, a fake parameter store
# (monkeypatched module global) and a fake clock - no Player, no thread.
# Covers what the pure-function tests above can't: the v1 bool/float
# per-dot max-wins merge, intensity scaling, frame debounce, the
# anti-stuck hold->ramp, manual overrides, the disabled-device zero
# frame, and disconnect cleanup.


class _FakeStore:
    def __init__(self):
        self.params = {}

    def get_all_parameters(self):
        return dict(self.params)


class _FakeClock:
    def __init__(self):
        self.now = 1000.0

    def time(self):
        return self.now

    def advance(self, s):
        self.now += s


class _FakeEngine:
    is_connected = True

    def __init__(self):
        self.frames = []

    def submit_dot_frame(self, position, dots):
        self.frames.append((position, list(dots)))


def _mk(monkeypatch, configs, antistuck=None, sps_cfg=None):
    """Router + fake engine/store/clock, no thread started."""
    fake_store = _FakeStore()
    clock = _FakeClock()
    monkeypatch.setattr(bhaptics_router, "store", fake_store)
    monkeypatch.setattr(bhaptics_router.time, "time", clock.time)
    eng = _FakeEngine()
    r = BHapticsRouter(
        eng,
        get_device_configs=lambda: configs,
        get_antistuck=(lambda: antistuck) if antistuck else None,
        get_sps_mirror_config=(lambda: sps_cfg) if sps_cfg else None,
    )
    return r, eng, fake_store, clock


def _dev(enabled=True, intensity=100):
    """Duck-typed DeviceConfig - _tick reads .enabled / .intensity."""
    return SimpleNamespace(enabled=enabled, intensity=intensity)


class TestRouterTick:
    def test_bool_schema_drives_dot_at_device_intensity(self, monkeypatch):
        r, eng, st, _ = _mk(monkeypatch, {"VestFront": _dev(intensity=80)})
        st.params["bHaptics_Vest_Front_5_bool"] = True
        r._tick()
        assert eng.frames == [("VestFront", [0] * 4 + [80] + [0] * 15)]

    def test_float_schema_scales_by_intensity(self, monkeypatch):
        r, eng, st, _ = _mk(monkeypatch, {"VestFront": _dev(intensity=80)})
        st.params["bOSC_v1_VestFront_5"] = 0.5
        r._tick()
        assert eng.frames[-1][1][4] == 40

    def test_schemas_merge_max_wins_per_dot(self, monkeypatch):
        r, eng, st, _ = _mk(monkeypatch, {"VestFront": _dev(intensity=80)})
        st.params["bHaptics_Vest_Front_5_bool"] = True   # -> 80
        st.params["bOSC_v1_VestFront_5"] = 0.5           # -> 40
        r._tick()
        assert eng.frames[-1][1][4] == 80

    def test_sps_mirror_layer_merges_in(self, monkeypatch):
        sps_cfg = {"enabled": True, "entries": [{
            "ogb_zone": "Boob", "zone_type": "Orf",
            "filters": ["TouchOthers"], "position": "VestFront",
            "dot_indices": [4], "gain": 1.0, "threshold": 0.0,
        }]}
        r, eng, st, _ = _mk(
            monkeypatch, {"VestFront": _dev(intensity=100)}, sps_cfg=sps_cfg)
        st.params.update(_zone_params(0.6))
        r._tick()
        assert eng.frames[-1][1][4] == 60

    def test_unchanged_frames_are_debounced(self, monkeypatch):
        r, eng, st, _ = _mk(monkeypatch, {"VestFront": _dev()})
        st.params["bHaptics_Vest_Front_1_bool"] = True
        r._tick()
        r._tick()
        assert len(eng.frames) == 1

    def test_antistuck_holds_then_ramps_to_zero(self, monkeypatch):
        antistuck = {"enabled": True, "hold_s": 1.0, "ramp_s": 2.0}
        r, eng, st, clock = _mk(
            monkeypatch, {"VestFront": _dev(intensity=100)}, antistuck=antistuck)
        st.params["bHaptics_Vest_Front_1_bool"] = True
        r._tick()
        assert eng.frames[-1][1][0] == 100
        # Inside the hold window: unchanged, debounced - no new frame.
        clock.advance(0.5)
        r._tick()
        assert len(eng.frames) == 1
        # Halfway down the ramp (age 2.0 -> ramp_t 1.0 of 2.0): 50%.
        clock.advance(1.5)
        r._tick()
        assert eng.frames[-1][1][0] == 50
        # Past the ramp: silenced.
        clock.advance(2.0)
        r._tick()
        assert eng.frames[-1][1][0] == 0
        # A real input change resets the timer and springs back.
        st.params["bHaptics_Vest_Front_1_bool"] = False
        r._tick()
        st.params["bHaptics_Vest_Front_1_bool"] = True
        r._tick()
        assert eng.frames[-1][1][0] == 100

    def test_master_scale_not_clobbered_by_antistuck_ramp(self, monkeypatch):
        # Regression: the anti-stuck ramp factor briefly shared a local
        # name with the mode master scale, so every position processed
        # AFTER a ramping one was scaled by the ramp factor instead of
        # the master — overdriving the suit past the mode's intensity.
        antistuck = {"enabled": True, "hold_s": 1.0, "ramp_s": 2.0}
        r, eng, st, clock = _mk(
            monkeypatch,
            {"Head": _dev(intensity=100), "VestFront": _dev(intensity=100)},
            antistuck=antistuck)
        r.get_master_scale = lambda: 0.6
        st.params["bHaptics_Head_1_bool"] = True
        r._tick()
        # Head latched long enough to be mid-ramp (factor 0.5), then a
        # fresh contact drives VestFront — which is processed after Head.
        clock.advance(2.0)
        st.params["bOSC_v1_VestFront_5"] = 1.0
        r._tick()
        vest = [f for f in eng.frames if f[0] == "VestFront"][-1]
        assert vest[1][4] == 60   # 100 * 0.6 master — not 100 * 0.5 ramp

    def test_manual_override_wins_even_on_disabled_device(self, monkeypatch):
        r, eng, st, _ = _mk(monkeypatch, {"VestFront": _dev(enabled=False)})
        r.set_manual_override("VestFront", 4, 100)
        r._tick()
        assert eng.frames[-1] == ("VestFront", [0] * 4 + [100] + [0] * 15)
        r.set_manual_override("VestFront", 4, None)  # clear
        st.params["keepalive"] = 1.0  # _tick early-outs on no params + no overrides
        r._tick()
        assert eng.frames[-1][1][4] == 0

    def test_disabling_device_pushes_one_zero_frame(self, monkeypatch):
        cfg = _dev()
        r, eng, st, _ = _mk(monkeypatch, {"VestFront": cfg})
        st.params["bHaptics_Vest_Front_1_bool"] = True
        r._tick()
        assert any(eng.frames[-1][1])
        cfg.enabled = False
        r._tick()
        assert eng.frames[-1] == ("VestFront", [0] * 20)
        n = len(eng.frames)
        r._tick()  # stays silent, no frame spam
        assert len(eng.frames) == n

    def test_disconnect_clears_state_for_clean_reconnect(self, monkeypatch):
        r, eng, st, _ = _mk(monkeypatch, {"VestFront": _dev()})
        st.params["bHaptics_Vest_Front_1_bool"] = True
        r._tick()
        assert r.get_snapshot()
        eng.is_connected = False
        r._tick()
        assert r.get_snapshot() == {}
        # Reconnect: the debounce was wiped, so the frame re-submits.
        eng.is_connected = True
        r._tick()
        assert eng.frames[-1][1][0] == 100
