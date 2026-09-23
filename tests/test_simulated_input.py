"""The input simulator as an input SOURCE: a `random` waveform that is still
a pure function, synthetic parameters that never look like VRChat traffic,
and the two simulator addresses passing a chain's type filter."""
import pytest

from constants import SIM_PEN_ADDRESS, SIM_TOUCH_ADDRESS
from mixer import WAVEFORMS, sample_pattern
from parameter_store import ParameterStore


class TestRandomWaveform:
    def test_is_a_known_waveform(self):
        assert "random" in WAVEFORMS

    def test_stays_inside_zero_to_amp(self):
        for i in range(2000):
            v = sample_pattern(1.3, 0.8, "random", i * 0.031)
            assert 0.0 <= v <= 0.8

    def test_deterministic_in_time(self):
        assert sample_pattern(1.0, 1.0, "random", 12.345) == sample_pattern(1.0, 1.0, "random", 12.345)

    def test_visits_quiet_and_intense_sections(self):
        peaks = []
        # One value per stroke cycle, sampled at the stroke's crest.
        for cycle in range(300):
            t = (cycle + 0.5) / 1.0
            peaks.append(sample_pattern(1.0, 1.0, "random", t))
        assert min(peaks) < 0.3, "never went quiet"
        assert max(peaks) > 0.8, "never got intense"
        assert len({round(p, 2) for p in peaks}) > 50, "not varied"

    def test_no_stroke_is_a_flat_line(self):
        vals = [sample_pattern(1.0, 1.0, "random", 3.0 + k * 0.05) for k in range(20)]
        assert max(vals) - min(vals) > 0.05


class TestSyntheticParameters:
    def test_synthetic_writes_count_no_packet(self):
        st = ParameterStore()
        before = st.get_packets_received()
        st.update_synthetic(SIM_PEN_ADDRESS, 0.5)
        assert st.get_all_parameters()[SIM_PEN_ADDRESS] == 0.5
        assert st.get_packets_received() == before

    def test_synthetic_ignores_the_replay_lock(self):
        st = ParameterStore()
        st.set_input_locked(True)
        st.update_parameter("OGB/Orf/Pussy/PenOthers", 0.9)       # live: dropped
        st.update_synthetic(SIM_TOUCH_ADDRESS, 0.4)               # ours: kept
        params = st.get_all_parameters()
        assert "OGB/Orf/Pussy/PenOthers" not in params
        assert params[SIM_TOUCH_ADDRESS] == 0.4

    def test_remove_drops_the_key_and_bumps_the_version(self):
        st = ParameterStore()
        st.update_synthetic(SIM_PEN_ADDRESS, 0.5)
        v = st.get_version()
        st.remove_synthetic(SIM_PEN_ADDRESS)
        assert SIM_PEN_ADDRESS not in st.get_all_parameters()
        assert st.get_version() > v
        st.remove_synthetic(SIM_PEN_ADDRESS)                       # idempotent


class TestSimAddressesPassTheTypeFilter:
    """A Penetration chain hears OGP/Sim/Pen and ignores OGP/Sim/Touch; a
    Touch chain the reverse; a Custom chain follows its own filters."""

    def _cfg(self):
        import copy
        from config_manager import preset_motor_mix
        mix = preset_motor_mix()                       # [penetration, touch]
        for ch in mix["chains"]:
            ch["wake"] = {"enabled": False}
            ch["smoothing"] = {"rise_ms": 0.0, "fall_ms": 0.0}
            ch["depth"]["gain"] = 1.0
            ch["speed"]["gain"] = 0.0
            ch["punch"] = {"gain": 0.0, "gain_out": 0.0, "decay_ms": 120.0}
            ch["zerocut"] = {"enabled": False}
        mix["merge"] = "max"
        return {
            "motor_count": 1,
            "motor_0_zones": "",                       # no zones: only the sim
            "osc_addresses": {"0": [SIM_PEN_ADDRESS, SIM_TOUCH_ADDRESS]},
            "mix": {"0": mix},
        }

    def _outs(self, router, clock, cfg, params):
        captured = {0: [], 1: []}
        for c in (0, 1):
            router.subscribe_intermediates("dev", 0, c, captured[c].append)
        for _ in range(3):
            router._calculate_motor_target("dev", 0, cfg, params, zones=set())
            clock.advance(0.05)
        return {c: captured[c][-1]["d_raw"] for c in (0, 1)}

    def test_pen_address_reaches_only_the_penetration_chain(self, router, clock):
        d = self._outs(router, clock, self._cfg(), {SIM_PEN_ADDRESS: 0.7})
        assert d[0] == pytest.approx(0.7)            # penetration chain
        assert d[1] == pytest.approx(0.0)            # touch chain

    def test_touch_address_reaches_only_the_touch_chain(self, router, clock):
        d = self._outs(router, clock, self._cfg(), {SIM_TOUCH_ADDRESS: 0.6})
        assert d[0] == pytest.approx(0.0)
        assert d[1] == pytest.approx(0.6)

    def test_custom_chain_follows_its_own_filters(self, router, clock):
        cfg = self._cfg()
        cfg["mix"]["0"]["chains"][0]["type"] = "custom"
        cfg["motor_0_touch"] = True
        cfg["motor_0_pen"] = False                   # custom chain: touch only
        d = self._outs(router, clock, cfg, {SIM_PEN_ADDRESS: 0.9, SIM_TOUCH_ADDRESS: 0.3})
        assert d[0] == pytest.approx(0.3)
