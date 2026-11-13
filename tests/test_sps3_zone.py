"""SPS 3 zones (VRCFury 1.1443.0, Nov 2026): the renamed categories, the
depth contacts, ungated touch, VRChat's touch speed in the chain, and the
OGB/Enabled heartbeat. See src/sps3_zone.py."""

import pytest

import sps3_zone
from motor_router import MotorRouter
from parameter_store import ParameterStore
from vrchat_osc import (
    OGB_ENABLED_ADDRESS, OGB_ENABLED_SPS3_ADDRESS, OGB_PRESENCE_ADDRESSES,
    VRChatOSCManager,
)
from zone_strength import zone_filter_strength


# ------------------------------------------------------------- naming

class TestCanonZoneKey:
    @pytest.mark.parametrize("raw, canon", [
        ("OGB/Socket/Booty/TouchSelf", "OGB/Orf/Booty/TouchSelf"),
        ("OGB/Plug/Tail/DepthOthers_PointSeparation",
         "OGB/Pen/Tail/DepthOthers_PointSeparation"),
        ("OGB/Socket/B/DepthSelf_CollisionTag_SPS/Plug/x",
         "OGB/Orf/B/DepthSelf_CollisionTag_SPS/Plug/x"),
    ])
    def test_sps3_categories_are_renamed(self, raw, canon):
        assert sps3_zone.canon_zone_key(raw) == canon

    @pytest.mark.parametrize("key", [
        "OGB/Orf/Booty/TouchSelf", "OGB/Pen/Tail/PenOthers",
        "OGB/Touch/Head/Self", "OGB/Enabled", "OGB/HapticsDisabled",
        "OGB_ENABLED", "OGB/Version/11", "OGB/Sockets/x/y", "Socket/x",
    ])
    def test_everything_else_is_untouched(self, key):
        assert sps3_zone.canon_zone_key(key) == key


class TestStoreIngest:
    def test_live_socket_and_plug_land_as_orf_and_pen(self):
        s = ParameterStore()
        s.update_parameter("OGB/Socket/Booty/TouchSelf", 0.4)
        s.update_parameter("OGB/Plug/Tail/LengthMult2", 0.2)
        params, _v, zones = s.snapshot()
        assert params["OGB/Orf/Booty/TouchSelf"] == 0.4
        assert "OGB/Socket/Booty/TouchSelf" not in params
        assert zones == {("Orf", "Booty"), ("Pen", "Tail")}
        assert s.get_detected_zones()["Orifices"] == ["Booty"]
        assert s.get_detected_zones()["Penetrators"] == ["Tail"]

    def test_vfh_socket_form_lands_as_orf(self):
        s = ParameterStore()
        s.update_parameter("VFH/Zone/Socket/Mouth/TouchOthers", 0.1)
        assert s.get_zone_tuples() == {("Orf", "Mouth")}

    def test_oscquery_snapshot_is_renamed(self):
        tree = {"CONTENTS": {"avatar": {"CONTENTS": {"parameters": {
            "CONTENTS": {"OGB": {"CONTENTS": {"Socket": {"CONTENTS": {
                "Booty": {"CONTENTS": {
                    "DepthRadius": {"VALUE": [0.3]},
                    "DepthSelf": {"VALUE": [0.0]},
                }}}}}}}}}}}}
        s = ParameterStore()
        s.rebuild_from_json(tree)
        params, _v, zones = s.snapshot()
        assert zones == {("Orf", "Booty")}
        assert params["OGB/Orf/Booty/DepthRadius"] == 0.3


# ------------------------------------------------------------- depth

def _plug(prox, sep, mult1=1.0, mult2=0.2, contact="DepthOthers"):
    p = "OGB/Pen/T"
    return {f"{p}/LengthMult1": mult1, f"{p}/LengthMult2": mult2,
            f"{p}/{contact}": prox, f"{p}/{contact}_PointSeparation": sep}


class TestPlugDepth:
    def test_depth_is_one_minus_separation_over_length(self):
        # 20 cm plug, base 5 cm from the socket: 3/4 in.
        assert sps3_zone.depth(_plug(0.5, 0.05), "OGB/Pen/T", "Pen",
                               "DepthOthers") == pytest.approx(0.75)

    def test_all_the_way_in_and_tip_at_the_entrance(self):
        assert sps3_zone.depth(_plug(1.0, 0.0), "OGB/Pen/T", "Pen",
                               "DepthOthers") == pytest.approx(1.0)
        assert sps3_zone.depth(_plug(0.2, 0.2), "OGB/Pen/T", "Pen",
                               "DepthOthers") == pytest.approx(0.0)
        assert sps3_zone.depth(_plug(0.1, 0.5), "OGB/Pen/T", "Pen",
                               "DepthOthers") == 0.0      # not in yet

    @pytest.mark.parametrize("params", [
        _plug(0.0, 0.05),                        # nothing in range
        _plug(0.5, -1.0),                        # no separation reading
        _plug(0.5, 0.05, mult2=0.0),             # length unknown
        {"OGB/Pen/T/DepthOthers": 0.5},          # separation missing
        _plug(float("nan"), 0.05),
    ])
    def test_unreadable_is_zero(self, params):
        assert sps3_zone.depth(params, "OGB/Pen/T", "Pen", "DepthOthers") == 0.0


class TestSocketPlugLength:
    """The socket learns the entering plug's length in the store."""

    P = "OGB/Socket/B"     # wire form; the store keeps it as OGB/Orf/B

    def _store(self):
        s = ParameterStore()
        s.update_parameter(f"{self.P}/DepthRadius", 0.5)
        return s

    @staticmethod
    def _depth(s):
        params = s.get_all_parameters()
        return sps3_zone.depth(params, "OGB/Orf/B", "Orf", "DepthOthers")

    def _send(self, s, prox, sep):
        s.update_parameter(f"{self.P}/DepthOthers_PointSeparation", sep)
        s.update_parameter(f"{self.P}/DepthOthers", prox)

    def test_sps3_plug_states_its_length(self):
        s = self._store()
        s.update_parameter(f"{self.P}/DepthOthers_CollisionTag_SPS/Plug/a", True)
        s.update_parameter(f"{self.P}/DepthOthers_SenderLossyScaleZ", 0.2)
        self._send(s, 1.0, 0.05)
        assert self._depth(s) == pytest.approx(0.75)

    def test_older_plug_is_measured_on_the_way_in_and_kept_inside(self):
        s = self._store()
        # A 20 cm plug's base sphere is 20 cm; with a 50 cm receiver,
        # proximity 0.4 sits 0.2 + 0.5 * 0.6 = 0.5 m away.
        self._send(s, 0.4, 0.5)
        assert s.get_all_parameters()["OGB/Orf/B/DepthOthers_PlugLength"] \
            == pytest.approx(0.2)
        assert self._depth(s) == 0.0              # still outside
        # Inside: the proximity is pinned at 1, the length is kept.
        self._send(s, 1.0, 0.1)
        assert self._depth(s) == pytest.approx(0.5)
        self._send(s, 1.0, 0.0)
        assert self._depth(s) == pytest.approx(1.0)

    def test_leaving_forgets_the_length(self):
        s = self._store()
        self._send(s, 0.4, 0.5)
        s.update_parameter(f"{self.P}/DepthOthers", 0.0)
        assert s.get_all_parameters()["OGB/Orf/B/DepthOthers_PlugLength"] == 0.0
        # The next plug in starts fresh: pinned at once, no measurement
        # yet -> only the lower bound, so it reads as at the entrance.
        self._send(s, 1.0, 0.1)
        assert self._depth(s) == pytest.approx(0.0)

    def test_a_later_reading_on_the_way_in_improves_the_lower_bound(self):
        s = self._store()
        self._send(s, 1.0, 0.1)                   # first seen already pinned
        self._send(s, 0.8, 0.3)                   # 0.3 - 0.5 * 0.2 = 0.2
        self._send(s, 1.0, 0.1)
        assert self._depth(s) == pytest.approx(0.5)

    def test_the_two_halves_of_a_reading_come_from_one_frame(self):
        # VRChat sends separation and proximity as two messages per frame.
        # A frame that carries only one of them must not get its other half
        # paired with the NEXT frame's message.
        lengths = sps3_zone.SocketPlugLengths()
        key = "OGB/Orf/B/DepthOthers"
        params = {"OGB/Orf/B/DepthRadius": 0.5}
        clock = [0.0]

        def frame(*writes):
            for k, v in writes:
                params[k] = v
                for dk, dv in lengths.on_write(k, v, params, clock[0]):
                    params[dk] = dv
                clock[0] += 0.0005               # one frame's burst
            clock[0] += 0.011                    # 90 fps

        def at(prox):                            # a 20 cm plug's reading
            return ((key + "_PointSeparation", 0.2 + 0.5 * (1.0 - prox)),
                    (key, prox))

        frame(*at(0.2))
        frame(*at(0.4))
        frame((key, 0.6))                        # its separation got lost
        frame(*at(0.8))
        frame(*at(0.9))
        readings = lengths._readings[("OGB/Orf/B", "DepthOthers")]
        assert readings == pytest.approx([0.2] * len(readings))
        assert len(readings) == 4
        frame((key + "_PointSeparation", 0.15), (key, 1.0))   # inside
        assert params[key + "_PlugLength"] == pytest.approx(0.2)
        assert sps3_zone.depth(params, "OGB/Orf/B", "Orf",
                               "DepthOthers") == pytest.approx(0.25)

    def test_a_stray_reading_is_outvoted(self):
        lengths = sps3_zone.SocketPlugLengths()
        slot = ("OGB/Orf/B", "DepthOthers")
        lengths._readings[slot] = [0.1, 0.2, 0.2, 0.21]
        assert lengths._best(slot) == pytest.approx(0.2)

    def test_snapshot_rebuild_starts_over(self):
        s = self._store()
        self._send(s, 0.4, 0.5)
        s.rebuild_from_json({"CONTENTS": {}})
        assert "OGB/Orf/B/DepthOthers_PlugLength" not in s.get_all_parameters()

    def test_older_zones_are_left_alone(self):
        s = ParameterStore()
        s.update_parameter("OGB/Orf/Old/PenOthers", 0.5)
        s.update_parameter("OGB/Orf/Old/PenOthersNewTip", 0.9)
        assert not any(k.endswith("_PlugLength")
                       for k in s.get_all_parameters())


# ------------------------------------------------------------- touch speed

class TestTouchSpeed:
    K = "OGB/Orf/B/TouchOthers"

    def test_metres_per_second_to_unit(self):
        params = {self.K: 0.3, self.K + "_SenderVelocityMagnitude": 0.5}
        assert sps3_zone.touch_speed(params, self.K) == pytest.approx(0.5)
        params[self.K + "_SenderVelocityMagnitude"] = 3.0
        assert sps3_zone.touch_speed(params, self.K) == 1.0

    def test_needs_something_in_range(self):
        # VRChat leaves the last speed standing after the touch ends.
        params = {self.K: 0.0, self.K + "_SenderVelocityMagnitude": 0.5}
        assert sps3_zone.touch_speed(params, self.K) == 0.0

    def test_older_avatars_report_none(self):
        assert sps3_zone.touch_speed({self.K: 0.8}, self.K) == 0.0


# ------------------------------------------------------------- router

def _cfg(touch=True, pen=True, self_=False, others=True):
    return {"motor_0_touch": touch, "motor_0_pen": pen,
            "motor_0_self": self_, "motor_0_others": others}


SOCKET = {"OGB/Orf/B/DepthRadius": 0.5}      # marks the zone as SPS 3


class TestZoneLevelAndSpeed:
    def test_touch_needs_no_close_gate(self, router):
        params = {**SOCKET, "OGB/Orf/B/TouchOthers": 0.6}
        level, speed = router._zone_level_and_speed(
            "Orf", "B", _cfg(), 0, params)
        assert level == pytest.approx(0.6)
        assert speed == 0.0

    def test_older_zone_still_needs_its_close_gate(self, router):
        params = {"OGB/Orf/B/TouchOthers": 0.6}
        assert router._zone_contribution("Orf", "B", _cfg(), 0, params) == 0.0

    def test_speed_comes_with_the_touch(self, router):
        params = {**SOCKET, "OGB/Orf/B/TouchOthers": 0.6,
                  "OGB/Orf/B/TouchOthers_SenderVelocityMagnitude": 0.4}
        level, speed = router._zone_level_and_speed(
            "Orf", "B", _cfg(), 0, params)
        assert (level, speed) == (pytest.approx(0.6), pytest.approx(0.4))
        # The touch filter off takes the speed with it.
        assert router._zone_level_and_speed(
            "Orf", "B", _cfg(touch=False), 0, params) == (0.0, 0.0)
        # So does Others off when only Others touches.
        assert router._zone_level_and_speed(
            "Orf", "B", _cfg(others=False, self_=True), 0, params) == (0.0, 0.0)

    def test_depth_is_the_pen_filter(self, router):
        params = {**SOCKET, "OGB/Orf/B/DepthOthers": 1.0,
                  "OGB/Orf/B/DepthOthers_PointSeparation": 0.05,
                  "OGB/Orf/B/DepthOthers_PlugLength": 0.2,
                  "OGB/Orf/B/DepthOthers_SenderVelocityMagnitude": 0.9}
        level, speed = router._zone_level_and_speed(
            "Orf", "B", _cfg(), 0, params)
        assert level == pytest.approx(0.75)
        assert speed == 0.0            # depth's own speed is never used
        assert router._zone_contribution(
            "Orf", "B", _cfg(pen=False), 0, params) == 0.0

    def test_plug_depth_and_frot(self, router):
        params = {**_plug(0.5, 0.15), "OGB/Pen/T/FrotOthers": 0.3,
                  "OGB/Pen/T/FrotOthers_SenderVelocityMagnitude": 0.7}
        level, speed = router._zone_level_and_speed(
            "Pen", "T", _cfg(touch=False), 0, params)
        assert level == pytest.approx(0.3)     # max(depth 0.25, frot 0.3)
        assert speed == pytest.approx(0.7)

    def test_touch_zone_speed(self, router):
        params = {"OGB/Touch/Head/Others": 0.5,
                  "OGB/Touch/Head/Others_SenderVelocityMagnitude": 0.25}
        assert router._zone_level_and_speed(
            "Touch", "Head", _cfg(), 0, params) == (
                pytest.approx(0.5), pytest.approx(0.25))


def _speed_only_cfg():
    """Custom chain, depth channel muted: the output IS the Speed channel."""
    return {
        **_cfg(), "motor_0_zones": "All SPS",
        "mix": {"0": {"chains": [{
            "depth": {"gain": 0.0, "curve": "linear", "curve_param": 1.0},
            "speed": {"gain": 1.0, "curve": "linear", "curve_param": 1.0,
                      "decay_ms": 300.0},
            "combine": "max",
            "gate": {"enabled": False},
            "smoothing": {"rise_ms": 0.0, "fall_ms": 0.0},
        }], "merge": "max"}},
    }


class TestSpeedInTheChain:
    ZONES = {("Orf", "B")}

    def _run(self, router, clock, params, ticks=4):
        out = None
        for _ in range(ticks):
            out = router._calculate_motor_target(
                "dev", 0, _speed_only_cfg(), params, zones=self.ZONES)
            clock.advance(0.05)
        return out

    def test_a_hand_sliding_at_the_same_distance_is_felt(self, router, clock):
        params = {**SOCKET, "OGB/Orf/B/TouchOthers": 0.6,
                  "OGB/Orf/B/TouchOthers_SenderVelocityMagnitude": 0.5}
        out = self._run(router, clock, params)
        # (0.5 - cutoff) / (1 - cutoff): the Speed channel's own floor.
        cut = MotorRouter._SPEED_OUTPUT_CUTOFF
        assert out == pytest.approx((0.5 - cut) / (1.0 - cut))

    def test_without_speed_a_still_level_is_no_motion(self, router, clock):
        params = {**SOCKET, "OGB/Orf/B/TouchOthers": 0.6}
        assert self._run(router, clock, params) == 0.0

    def test_it_rings_down_like_any_speed(self, router, clock):
        moving = {**SOCKET, "OGB/Orf/B/TouchOthers": 0.6,
                  "OGB/Orf/B/TouchOthers_SenderVelocityMagnitude": 0.8}
        peak = self._run(router, clock, moving)
        still = dict(moving)
        still["OGB/Orf/B/TouchOthers_SenderVelocityMagnitude"] = 0.0
        tail = self._run(router, clock, still, ticks=1)
        assert 0.0 < tail < peak

    def test_both_rings_are_struck(self, router, clock):
        params = {**SOCKET, "OGB/Orf/B/TouchOthers": 0.6,
                  "OGB/Orf/B/TouchOthers_SenderVelocityMagnitude": 0.5}
        self._run(router, clock, params)
        cs = router._motor_state[("dev", 0)]["chains"][0]
        assert cs["smoothed_speed_in"] == pytest.approx(0.5)
        assert cs["smoothed_speed_out"] == pytest.approx(0.5)

    def test_zero_sender_speed_changes_nothing(self, router, clock):
        state_a = {"last_position": 0.2, "smoothed_speed_in": 0.3,
                   "smoothed_speed_out": 0.1}
        state_b = dict(state_a)
        a = router._derive_speed_signal(state_a, 0.5, 0.05, 0.3)
        b = router._derive_speed_signal(state_b, 0.5, 0.05, 0.3, 0.0)
        assert a == b and state_a == state_b


# ------------------------------------------------------------- zone_strength

class TestZoneStrength:
    def test_touch_needs_no_close_gate(self):
        params = {**SOCKET, "OGB/Orf/B/TouchSelf": 0.7,
                  "OGB/Orf/B/TouchSelfClose": False}   # stale, not SPS 3's
        assert zone_filter_strength("B", "Orf", ["TouchSelf"], params) \
            == pytest.approx(0.7)

    @pytest.mark.parametrize("fname", ["PenOthers", "PenetratingOthers"])
    def test_pen_filters_read_the_depth(self, fname):
        params = {**SOCKET, "OGB/Orf/B/DepthOthers": 1.0,
                  "OGB/Orf/B/DepthOthers_PointSeparation": 0.1,
                  "OGB/Orf/B/DepthOthers_PlugLength": 0.2}
        assert zone_filter_strength("B", "Orf", [fname], params) \
            == pytest.approx(0.5)

    def test_plug_frot(self):
        params = {**_plug(0.0, 0.0), "OGB/Pen/T/FrotOthers": 0.4}
        assert zone_filter_strength("T", "Pen", ["FrotOthers"], params) \
            == pytest.approx(0.4)


# ------------------------------------------------------------- OSC out

class TestPresenceHeartbeat:
    def test_both_names_are_sent(self):
        assert OGB_ENABLED_SPS3_ADDRESS == "/avatar/parameters/OGB/Enabled"
        assert OGB_PRESENCE_ADDRESSES == (OGB_ENABLED_ADDRESS,
                                          OGB_ENABLED_SPS3_ADDRESS)

        class _Osc:
            def __init__(self):
                self.sent = []

            def send_parameter(self, address, value, ignore_rate_limit=False):
                self.sent.append((address, value, ignore_rate_limit))

        osc = _Osc()
        VRChatOSCManager._send_ogb_presence(osc)
        assert osc.sent == [(a, True, True) for a in OGB_PRESENCE_ADDRESSES]

    def test_a_failing_send_never_raises(self):
        class _Broken:
            def send_parameter(self, *a, **k):
                raise OSError("socket closed")

        VRChatOSCManager._send_ogb_presence(_Broken())


@pytest.mark.parametrize("value, off", [
    (True, True), (1, True), (1.0, True), (False, False), (0, False),
    (None, False), ("yes", False),
])
def test_haptics_disabled(value, off):
    assert sps3_zone.haptics_disabled(value) is off
