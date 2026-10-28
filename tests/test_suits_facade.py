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

    def configure(self, cfg, bhaptics_on, owo_on):
        self.config = (cfg, bhaptics_on, owo_on)

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
