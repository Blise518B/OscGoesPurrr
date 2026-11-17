"""SuitsFacade wiring: with both switches off nothing starts; each switch
starts and stops its own engine and the shared router follows; settings
edits reach the router and the OWO engine's caps."""

import queue

import pytest

import controllers.suits_facade as sf
from controllers.suits_facade import SuitsFacade


class FakeEngine:
    def __init__(self, **_k):
        self.started = None
        self.stopped = 0
        self.callback = None
        self.caps = None
        self.host = None
        self.game_id = None
        self.is_connected = False
        self.paused = False

    def set_state_callback(self, cb):
        self.callback = cb

    def start(self, auto):
        self.started = auto

    def stop(self):
        self.stopped += 1
        self.started = None

    def set_caps(self, per_muscle, global_max):
        self.caps = (dict(per_muscle), global_max)

    def set_host(self, host):
        self.host = host

    def set_game_id(self, gid):
        self.game_id = gid

    def set_paused(self, paused):
        self.paused = bool(paused)

    def status_snapshot(self):
        return {"active": {}}

    def output_snapshot(self):
        return {}


class FakeRouter:
    def __init__(self, *a, **k):
        self.running = False
        self.config = None

    def start(self):
        self.running = True

    def stop(self):
        self.running = False

    def configure(self, cfg, bhaptics_on, owo_on, trackers_on=False):
        self.config = (cfg, bhaptics_on, owo_on)
        self.trackers_on = trackers_on

    def live(self):
        return {}


class Host(SuitsFacade):
    def __init__(self, features=None):
        self.thread_queue = queue.Queue()
        self._features = features or {}
        self.logs = []

    def get_feature_enabled(self, key):
        return self._features.get(key, False)

    def get_master_scale(self):
        return 1.0

    def log_message(self, m):
        self.logs.append(m)


@pytest.fixture(autouse=True)
def fakes(monkeypatch):
    monkeypatch.setattr(sf, "BHapticsEngine", FakeEngine)
    monkeypatch.setattr(sf, "OwoEngine", FakeEngine)
    monkeypatch.setattr(sf, "SuitsRouter", FakeRouter)
    monkeypatch.setattr(sf, "TrackerEngine", FakeTrackerEngine)


class FakeTrackerEngine:
    def __init__(self, **_k):
        self.running = False
        self.caps = {}
        self.devices = []
        self.identified = []

    def set_state_callback(self, cb):
        self.callback = cb

    def start(self):
        self.running = True

    def stop(self):
        self.running = False

    def set_caps(self, caps):
        self.caps = dict(caps)

    def status_snapshot(self):
        return {"available": True, "alive": self.running, "paused": False,
                "devices": [dict(d) for d in self.devices]}

    def output_snapshot(self):
        return {}

    def identify(self, serial):
        self.identified.append(serial)
        return True


def test_both_switches_off_starts_nothing():
    h = Host()
    h._suits_init()
    assert h.bhaptics_engine.started is None
    assert h.owo_engine.started is None
    assert h.suits_router.running is False


def test_each_switch_starts_its_engine_and_the_router_follows():
    h = Host({sf.FEATURE_BHAPTICS: True})
    h._suits_init()
    assert h.bhaptics_engine.started is True           # bHaptics: auto-connect on
    assert h.owo_engine.started is None
    assert h.suits_router.running is True
    assert h.suits_router.config[1:] == (True, False)

    h._features[sf.FEATURE_OWO] = True
    h._owo_feature_changed(True)
    assert h.owo_engine.started is False               # EMS: never auto-connects by default
    assert h.suits_router.config[1:] == (True, True)

    h._features[sf.FEATURE_BHAPTICS] = False
    h._bhaptics_feature_changed(False)
    h._features[sf.FEATURE_OWO] = False
    h._owo_feature_changed(False)
    assert h.bhaptics_engine.stopped and h.owo_engine.stopped
    assert h.suits_router.running is False


def test_settings_reach_the_owo_caps_and_the_router():
    h = Host({sf.FEATURE_OWO: True})
    h._suits_init()
    h.set_owo_muscle("Arm_L", max=25)
    h.set_owo_option("global_max", 40)
    caps, global_max = h.owo_engine.caps
    assert caps["Arm_L"] == 25 and global_max == 40
    assert h.suits_router.config[0]["owo"]["muscles"]["Arm_L"]["max"] == 25


def test_each_kind_starts_as_the_toys_anti_stuck_and_reaches_the_router():
    """An update from one anti-stuck for all: each suit and the trackers
    start with the toys' switch and times, then change on their own."""
    h = Host({sf.FEATURE_OWO: True})
    toys = {"enabled": False, "active_s": 4, "peaked_s": 30}
    h._get_toy_antistuck = lambda: dict(toys)
    h._suits_init()
    for kind in ("bhaptics", "owo", "trackers"):
        assert h.get_suit_antistuck(kind) == toys
    h.set_suit_antistuck("owo", enabled=True)
    cfg = h.suits_router.config[0]
    assert cfg["owo"]["antistuck"]["enabled"] is True
    assert cfg["bhaptics"]["antistuck"]["enabled"] is False
    assert cfg["trackers"]["antistuck"] == toys


def test_state_changes_go_through_the_queue():
    h = Host()
    h._suits_init()
    h.bhaptics_engine.callback()
    assert h.thread_queue.get_nowait() == ("suits_state", None)


def test_a_suit_switched_off_stays_off_after_a_restart():
    h = Host({sf.FEATURE_BHAPTICS: True, sf.FEATURE_OWO: True})
    h._suits_init()
    h.bhaptics_stop_all()
    h.owo_stop_all()
    assert h.bhaptics_engine.paused and h.owo_engine.paused
    again = Host({sf.FEATURE_BHAPTICS: True, sf.FEATURE_OWO: True})
    again._suits_init()                    # the next launch
    assert again.bhaptics_engine.paused and again.owo_engine.paused
    again.owo_resume()
    assert not again.owo_engine.paused
    assert again.suits_settings.owo()["enabled"] is True
    assert again.suits_settings.bhaptics()["enabled"] is False


def test_a_part_that_connects_shows_on_the_page_from_then_on():
    h = Host({sf.FEATURE_BHAPTICS: True})
    h._suits_init()
    h.bhaptics_engine.status_snapshot = lambda: {"devices": [
        {"positions": ["VestFront", "VestBack"]}, {"positions": ["ForearmL", "ForearmR"]}]}
    h._suits_note_connected()
    assert h.suits_settings.bhaptics()["have"] == ["vest", "arms"]
    assert any("Sleeves" in m for m in h.logs)
    logs = len(h.logs)
    h._suits_note_connected()                  # nothing new: nothing said
    assert len(h.logs) == logs
    h.set_bhaptics_have("arms", False)
    h.set_bhaptics_have("head", True)
    h._suits_note_connected()                  # still connected: stays off
    assert h.suits_settings.bhaptics()["have"] == ["vest", "head"]
    h.bhaptics_engine.status_snapshot = lambda: {"devices": []}
    h._suits_note_connected()
    h.bhaptics_engine.status_snapshot = lambda: {"devices": [{"positions": ["ForearmR"]}]}
    h._suits_note_connected()                  # connected again: back on
    assert h.suits_settings.bhaptics()["have"] == ["vest", "arms", "head"]


def test_the_contact_check_reads_the_worn_avatars_parameter_list(monkeypatch):
    h = Host()
    h._suits_init()
    h.get_current_avatar_id = lambda: "avtr_x"
    monkeypatch.setattr(sf.store, "get_all_parameters", lambda: {"owo_suit_Arm_L": 0.0})
    monkeypatch.setattr(sf.vrchat_avatars, "avatar_parameters",
                        lambda aid: {"bOSC/v2/VestBack/3/self", "bOSC/v2/VestBack/3/others",
                                     "bHaptics_Head_1_bool"} if aid == "avtr_x" else None)
    found = h.get_suits_detected()
    assert found["source"] == "file"
    assert found["contacts"]["VestBack"] == (3,)
    assert found["contacts"]["Head"] == (0,)
    assert found["owo"] == ["Arm_L"]                  # what was sent counts too
    h.get_current_avatar_id = lambda: ""
    assert h.get_suits_detected()["source"] == "osc"
    monkeypatch.setattr(sf.store, "get_all_parameters", lambda: {})
    assert h.get_suits_detected()["source"] == ""


# ---- haptic trackers -------------------------------------------------------------

def _dev(serial, role_spot=None, role=""):
    return {"serial": serial, "model": "VIVE Tracker 3.0 MV", "kind": "vive",
            "battery": 80, "role": role, "role_spot": role_spot}


def test_trackers_follow_their_switch_their_role_and_your_placing():
    h = Host({sf.FEATURE_TRACKERS: True})
    h._suits_init()
    eng = h.tracker_engine
    assert eng.running and h.suits_router.running and h.suits_router.trackers_on
    eng.devices = [_dev("LHR-1", "hips", "TrackerRole_Waist"), _dev("LHR-2")]
    h._suits_note_connected()                    # a tracker came: the router hears it
    assert h.suits_router.config[0]["trackers"]["at"] == {"LHR-1": "hips"}
    assert eng.caps == {"LHR-1": 80}
    h.place_tracker("LHR-2", "knee_l")
    assert h.suits_router.config[0]["trackers"]["at"] == {"LHR-1": "hips", "LHR-2": "knee_l"}
    st = h.get_suits_status()["trackers"]
    assert st["feature"] is True and set(st["spots"]) == {"hips", "knee_l"}
    assert [d["placed_by"] for d in st["devices"]] == ["steamvr", "you"]
    h.set_tracker("hips", params="HapticHips, Extra", max=60)
    assert h.suits_settings.trackers()["spots"]["hips"]["params"] == ["HapticHips", "Extra"]
    assert eng.caps["LHR-1"] == 60
    assert h.tracker_test("hips") is True and eng.identified == ["LHR-1"]
    h._features[sf.FEATURE_TRACKERS] = False
    h._trackers_feature_changed(False)
    assert not eng.running and not h.suits_router.running
