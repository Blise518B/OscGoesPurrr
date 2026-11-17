"""Haptic trackers: the spot table and SteamVR roles (tracker_spots), the
engine's pulses against a fake OpenVR (tracker_engine), the router's levels
(suits_router) and the settings that feed them."""

import pytest

import tracker_engine as te
import tracker_spots as ts
from parameter_store import ParameterStore
from settings.suits import SuitsSettingsManager, TRACKER_DEFAULT_MAX, clean_tracker_spot
from suits_router import SuitsRouter, tracker_spot_levels

# ---- spots and roles -----------------------------------------------------------


def test_spots_use_haptic_pancakes_parameter_names():
    assert ts.SPOT_KEYS == ("head", "chest", "hips", "elbow_r", "elbow_l",
                            "knee_r", "knee_l", "foot_r", "foot_l")
    assert ts.DEFAULT_PARAM["hips"] == "HapticHips"
    assert ts.DEFAULT_PARAM["elbow_l"] == "HapticElbowLeft"
    assert ts.DEFAULT_PARAM["foot_r"] == "HapticFootRight"


@pytest.mark.parametrize("role, spot", [
    ("TrackerRole_Waist", "hips"), ("TrackerRole_Chest", "chest"),
    ("TrackerRole_LeftFoot", "foot_l"), ("TrackerRole_RightAnkle", "foot_r"),
    ("TrackerRole_LeftKnee", "knee_l"), ("TrackerRole_RightElbow", "elbow_r"),
    ("TrackerRole_Handed,TrackedControllerRole_LeftHand", None),
    ("TrackerRole_None", None), ("TrackerRole_LeftShoulder", None), ("", None),
])
def test_steamvr_roles_map_onto_spots(role, spot):
    assert ts.spot_for_role(role) == spot


def test_roles_are_read_from_steamvrs_settings_without_ogps_own_devices():
    text = """{"trackers": {
        "/devices/htc/vive_trackerLHR-781FC61B": "TrackerRole_LeftFoot",
        "/devices/lighthouse/LHR-33668EFC": "TrackerRole_Handed,TrackedControllerRole_RightHand",
        "/devices/oscgoespurrr/OGP_TOY_LOVENSE_EDGE": "TrackerRole_RightElbow"}}"""
    roles = ts.roles_from_settings(text)
    assert len(roles) == 2
    assert ts.role_of("LHR-781FC61B", roles) == "TrackerRole_LeftFoot"
    assert ts.role_of("LHR-UNKNOWN", roles) == ""
    assert ts.roles_from_settings("not json") == {}
    assert ts.roles_from_settings('{"trackers": 3}') == {}


def test_params_are_cleaned():
    assert ts.clean_params(None, "chest") == ["HapticChest"]
    assert ts.clean_params(["/avatar/parameters/HapticChest", " Extra ", "", "Extra"],
                           "chest") == ["HapticChest", "Extra"]
    assert len(ts.clean_params([f"P{i}" for i in range(20)], "chest")) == ts.MAX_PARAMS
    assert ts.split_params("HapticChest, ChestB; ChestC") == ["HapticChest", "ChestB", "ChestC"]


# ---- pulse maths -----------------------------------------------------------------

def test_timing_follows_the_model():
    assert te.timing_for("VIVE Tracker 3.0 MV") is te.VIVE
    assert te.timing_for("Tundra Tracker") is te.TUNDRA
    assert te.timing_for("VIVE Controller MV") is te.CONTROLLER
    assert te.timing_for("") is te.VIVE


def test_pulse_value_holds_the_cap():
    assert te.pulse_value(te.VIVE, 1.0, 100) == 50
    assert te.pulse_value(te.VIVE, 1.0, 80) == 40          # the default top
    assert te.pulse_value(te.VIVE, 0.5, 80) == 25
    assert te.pulse_value(te.TUNDRA, 1.0, 100) == 3999
    assert te.pulse_value(te.VIVE, 0.0, 100) == 0
    assert te.pulse_value(te.VIVE, float("nan"), 100) == 0
    assert te.pulse_value(te.VIVE, 5.0, 200) == 50          # nothing widens it


# ---- the engine against a fake OpenVR -----------------------------------------------

class FakeEvent:
    eventType = 0


class FakeVR:
    TRACKER = 3

    def __init__(self):
        # index -> (class, serial, model, system, battery)
        self.devices = {
            1: (1, "HMD-1", "Index", "lighthouse", None),
            3: (3, "LHR-781FC61B", "VIVE Tracker 3.0 MV", "lighthouse", 0.8),
            4: (3, "STBL_FOOT", "Standable", "standable", None),
            5: (3, "OGP_TOY_EDGE", "Edge", "oscgoespurrr", None),
        }
        self.pulses = []
        self.events = []
        self.quit_acked = False

    def pollNextEvent(self, event):
        if self.events:
            event.eventType = self.events.pop(0)
            return True
        return False

    def acknowledgeQuit_Exiting(self):
        self.quit_acked = True

    def getTrackedDeviceClass(self, i):
        return self.devices.get(i, (0,))[0]

    def isTrackedDeviceConnected(self, i):
        return i in self.devices

    def getStringTrackedDeviceProperty(self, i, prop):
        _c, serial, model, system, _b = self.devices[i]
        return {1002: serial, 1001: model, 1000: system}[prop]

    def getFloatTrackedDeviceProperty(self, i, prop):
        b = self.devices[i][4]
        if b is None:
            raise RuntimeError("no battery")
        return b

    def triggerHapticPulse(self, index, axis, value):
        self.pulses.append((index, value))


class FakeOpenVR:
    VRApplication_Background = 3
    TrackedDeviceClass_GenericTracker = 3
    k_unMaxTrackedDeviceCount = 8
    Prop_SerialNumber_String = 1002
    Prop_ModelNumber_String = 1001
    Prop_TrackingSystemName_String = 1000
    Prop_DeviceBatteryPercentage_Float = 1012
    VREvent_Quit = 700
    VREvent_t = FakeEvent

    def __init__(self, running=True):
        self.running = running
        self.vr = FakeVR()
        self.shutdowns = 0

    def init(self, kind):
        assert kind == self.VRApplication_Background     # never starts SteamVR
        if not self.running:
            raise RuntimeError("Init_NoServerForBackgroundApp")
        return self.vr

    def shutdown(self):
        self.shutdowns += 1


class Clock:
    def __init__(self):
        self.t = 100.0

    def __call__(self):
        return self.t


def _engine(running=True, roles=None):
    mod, clock = FakeOpenVR(running), Clock()
    eng = te.TrackerEngine(log=lambda m: None, vr_module=mod, clock=clock,
                           read_roles=lambda cache: dict(roles or {}))
    return eng, mod, clock


def test_no_steamvr_means_no_trackers():
    eng, mod, _clock = _engine(running=False)
    assert eng._attach() is None
    assert eng.is_alive is False


def test_only_real_trackers_are_listed_with_their_role():
    eng, mod, _clock = _engine(roles={"/devices/htc/vive_trackerLHR-781FC61B":
                                      "TrackerRole_LeftFoot"})
    vr = eng._attach()
    assert eng._scan(vr) is True
    devs = eng.status_snapshot()["devices"]
    assert [d["serial"] for d in devs] == ["LHR-781FC61B"]   # no HMD, Standable or OGP toy
    assert devs[0]["battery"] == 80
    assert devs[0]["role_spot"] == "foot_l"


def test_a_level_pulses_at_once_and_stops_when_not_sent_again():
    eng, mod, clock = _engine()
    vr = eng._attach()
    eng._scan(vr)
    eng.set_caps({"LHR-781FC61B": 100})
    eng.set_levels({"LHR-781FC61B": 1.0})
    eng._pulse_all(vr, clock())
    assert mod.vr.pulses == [(3, 50)]
    # the next pulse waits for its period
    clock.t += 0.01
    eng._pulse_all(vr, clock())
    assert len(mod.vr.pulses) == 1
    clock.t += 0.05
    eng._pulse_all(vr, clock())
    assert len(mod.vr.pulses) == 2
    # nobody sends it again: it stops on its own
    clock.t += te.LEVEL_TTL_S + 0.1
    eng._pulse_all(vr, clock())
    assert len(mod.vr.pulses) == 2
    assert eng.output_snapshot() == {}


def test_the_cap_and_pause_hold():
    eng, mod, clock = _engine()
    vr = eng._attach()
    eng._scan(vr)
    eng.set_levels({"LHR-781FC61B": 1.0})              # no cap given: DEFAULT_CAP
    eng._pulse_all(vr, clock())
    assert mod.vr.pulses == [(3, 40)]
    eng.set_paused(True)
    assert eng.identify("LHR-781FC61B") is False
    clock.t += 0.1
    eng.set_levels({"LHR-781FC61B": 1.0})
    eng._pulse_all(vr, clock())
    assert len(mod.vr.pulses) == 1


def test_identify_buzzes_a_tracker_briefly():
    eng, mod, clock = _engine()
    vr = eng._attach()
    eng._scan(vr)
    assert eng.identify("LHR-781FC61B") is True
    assert eng.identify("NOT-THERE") is False
    eng._pulse_all(vr, clock())
    assert mod.vr.pulses == [(3, 40)]
    clock.t += te.IDENTIFY_S + 0.01
    eng._pulse_all(vr, clock())
    assert len(mod.vr.pulses) == 1


def test_steamvr_quitting_is_acknowledged():
    eng, mod, _clock = _engine()
    vr = eng._attach()
    mod.vr.events.append(FakeOpenVR.VREvent_Quit)
    assert eng._scan(vr) is None
    assert mod.vr.quit_acked
    eng._detach(None)
    assert eng.is_alive is False and mod.shutdowns == 1


# ---- settings ---------------------------------------------------------------------

def test_tracker_settings_are_cleaned():
    assert clean_tracker_spot({}, "hips") == {
        "enabled": True, "intensity": 100, "max": TRACKER_DEFAULT_MAX, "params": ["HapticHips"]}
    assert clean_tracker_spot({"max": 400, "intensity": -5}, "hips")["max"] == 100
    m = SuitsSettingsManager()
    m.place_tracker("LHR-1", "knee_l")
    m.place_tracker("LHR-2", "nowhere")
    assert m.trackers()["placed"] == {"LHR-1": "knee_l"}
    m.place_tracker("LHR-1", None)
    assert m.trackers()["placed"] == {}
    m.set_tracker_spot("chest", params=["A", "B"], max=60)
    assert m.trackers()["spots"]["chest"]["params"] == ["A", "B"]
    assert m.trackers()["spots"]["chest"]["max"] == 60


# ---- router -----------------------------------------------------------------------

def test_spot_levels_take_the_strongest_parameter_times_strength():
    spots = {"hips": {"enabled": True, "intensity": 50, "params": ["A", "B"]},
             "chest": {"enabled": False, "intensity": 100, "params": ["A"]}}
    out = tracker_spot_levels({"A": 0.4, "B": 0.8}, spots, 1.0)
    assert out == {"hips": pytest.approx(0.4), "chest": 0.0}
    assert tracker_spot_levels({"A": 0.4, "B": 0.8}, spots, 0.0)["hips"] == 0.0


class FakeTrackers:
    def __init__(self):
        self.is_alive = True
        self.levels = []

    def set_levels(self, levels):
        self.levels.append(dict(levels))


class _Off:
    is_connected = False


class Stale:
    value = False

    def is_stale(self):
        return self.value


def test_the_router_feeds_each_placed_tracker():
    store, trk, clock, scale = ParameterStore(), FakeTrackers(), Clock(), {"v": 1.0}
    r = SuitsRouter(_Off(), _Off(), get_master_scale=lambda: scale["v"], clock=clock,
                    param_store=store, trackers=trk)
    r._stale = Stale()
    cfg = SuitsSettingsManager().snapshot()
    cfg["trackers"]["at"] = {"LHR-1": "hips", "LHR-2": "foot_l"}
    cfg["trackers"]["antistuck"] = {"enabled": True, "active_s": 1, "peaked_s": 10}
    r.configure(cfg, bhaptics_on=False, owo_on=False, trackers_on=True)
    store.update_parameter("HapticHips", 0.5)
    r.tick()
    assert trk.levels[-1] == {"LHR-1": pytest.approx(0.5), "LHR-2": 0.0}
    # a parameter the spots follow wakes the router
    r._wake.clear()
    r.notify("/avatar/parameters/HapticHips")
    assert r._wake.is_set()
    # frozen part-way for longer than the trackers' anti-stuck active_s: cut
    clock.t += 1.5
    r.tick()
    assert trk.levels[-1]["LHR-1"] == 0.0
    # Off silences every tracker
    store.update_parameter("HapticHips", 0.7)
    scale["v"] = 0.0
    r.tick()
    assert trk.levels[-1] == {"LHR-1": 0.0, "LHR-2": 0.0}


def test_the_trackers_have_their_own_anti_stuck():
    """The trackers' anti-stuck is theirs: off, a frozen contact keeps
    them buzzing while the suits' would cut it."""
    store, trk, clock, scale = ParameterStore(), FakeTrackers(), Clock(), {"v": 1.0}
    r = SuitsRouter(_Off(), _Off(), get_master_scale=lambda: scale["v"], clock=clock,
                    param_store=store, trackers=trk)
    r._stale = Stale()
    cfg = SuitsSettingsManager().snapshot()
    cfg["trackers"]["at"] = {"LHR-1": "hips"}
    cfg["trackers"]["antistuck"] = {"enabled": False, "active_s": 1, "peaked_s": 10}
    for kind in ("bhaptics", "owo"):
        cfg[kind]["antistuck"] = {"enabled": True, "active_s": 1, "peaked_s": 10}
    r.configure(cfg, bhaptics_on=False, owo_on=False, trackers_on=True)
    store.update_parameter("HapticHips", 0.5)
    r.tick()
    clock.t += 5.0
    r.tick()
    assert trk.levels[-1]["LHR-1"] == pytest.approx(0.5)
