"""OwoEngine is the last gate before an EMS sensation reaches a person, so
its rules are pinned here against a fake My OWO link: what goes out per
muscle, the re-send cadence, caps that can't be widened, Stop / pause /
end_all, the Test button's ceiling, garbage input, and the app leaving."""

import math
import threading
import time

import pytest

import owo_engine as oe
import owo_link as ol
from owo_engine import OwoEngine


class FakeLink:
    def __init__(self, host="127.0.0.1", answer=True):
        self._answer_host = host if answer else None
        self.host = None
        self.sent = []
        self.inbox = []
        self.closed = False
        self.fail = False
        self.candidates = None
        self.game_id = None
        self._lock = threading.Lock()

    def connect(self, candidates, game_id, timeout_s):
        self.candidates = list(candidates)
        self.game_id = game_id
        self.host = self._answer_host
        return self.host

    def send(self, data):
        with self._lock:
            self.sent.append(bytes(data))
        return not self.fail

    def poll(self, timeout_s):
        if self.inbox:
            return self.inbox.pop(0)
        time.sleep(min(timeout_s, 0.01))
        return None

    def close(self):
        self.closed = True

    def snapshot(self):
        with self._lock:
            return list(self.sent)


def wait_until(pred, timeout=2.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if pred():
            return True
        time.sleep(0.005)
    return pred()


def sensation(muscle, level, freq=oe.DEFAULT_FREQUENCY, game="0"):
    return ol.build_sensation(game, ol.sensation_text(freq, oe.SENSATION_S, level), {muscle: 100})


@pytest.fixture
def rig():
    links = []

    def factory():
        link = FakeLink()
        links.append(link)
        return link

    eng = OwoEngine(link_factory=factory)
    eng.start(True)
    assert wait_until(lambda: eng.is_connected)
    yield eng, links[-1], links
    eng.stop()


def test_connects_to_this_pc_then_the_network(rig):
    eng, link, _links = rig
    assert link.candidates == [ol.LOCALHOST, ol.BROADCAST]
    assert link.game_id == "0"
    assert eng.status_snapshot()["connected"] is True


def test_a_fixed_host_is_the_only_candidate():
    link = FakeLink("10.0.0.5")
    eng = OwoEngine(link_factory=lambda: link)
    eng.set_host("10.0.0.5")
    eng.set_game_id("12345")
    eng.start(True)
    try:
        assert wait_until(lambda: eng.is_connected)
        assert link.candidates == ["10.0.0.5"]
        assert link.game_id == "12345"
    finally:
        eng.stop()


def test_one_datagram_per_muscle_at_its_level(rig):
    eng, link, _ = rig
    eng.set_active({"Arm_L": 40, "Pectoral_R": 70}, 30)
    want = {sensation("Arm_L", 40, 30), sensation("Pectoral_R", 70, 30)}
    assert wait_until(lambda: want <= set(link.snapshot()))


def test_a_held_muscle_is_re_sent(rig):
    eng, link, _ = rig
    eng.set_active({"Lumbar_R": 25}, 50)
    msg = sensation("Lumbar_R", 25)
    assert wait_until(lambda: link.snapshot().count(msg) >= 3, timeout=2.0)


def test_caps_hold_and_cannot_be_widened(rig):
    eng, link, _ = rig
    eng.set_caps({"Arm_L": 30}, 50)
    eng.set_active({"Arm_L": 90, "Pectoral_R": 90}, 50)
    assert wait_until(lambda: {sensation("Arm_L", 30), sensation("Pectoral_R", 50)}
                      <= set(link.snapshot()))
    assert all(sensation("Arm_L", 90) != m for m in link.snapshot())

    eng.set_caps({"Arm_L": 999}, 500)            # a hand-edited settings file
    eng.set_active({"Arm_L": 100}, 50)
    assert wait_until(lambda: sensation("Arm_L", 100) in link.snapshot())
    assert eng.status_snapshot()["active"]["Arm_L"] == oe.ABSOLUTE_MAX


def test_letting_go_sends_a_stop(rig):
    eng, link, _ = rig
    eng.set_active({"Arm_R": 20}, 50)
    assert wait_until(lambda: sensation("Arm_R", 20) in link.snapshot())
    eng.set_active({}, 50)
    assert wait_until(lambda: link.snapshot()[-1] == ol.build_stop())
    assert eng.status_snapshot()["active"] == {}


def test_end_all_stops_twice(rig):
    eng, link, _ = rig
    eng.set_active({"Arm_R": 20}, 50)
    assert wait_until(lambda: sensation("Arm_R", 20) in link.snapshot())
    eng.end_all()
    sent = link.snapshot()
    assert sent.count(ol.build_stop()) >= 2


def test_paused_refuses_everything(rig):
    eng, link, _ = rig
    eng.set_paused(True)
    assert link.snapshot()[-2:] == [ol.build_stop(), ol.build_stop()]
    n = len(link.snapshot())
    eng.set_active({"Arm_L": 50}, 50)
    assert eng.test_pulse("Arm_L") is False
    time.sleep(0.35)
    assert all(b"SENSATION" not in m for m in link.snapshot()[n:])
    eng.set_paused(False)
    eng.set_active({"Arm_L": 51}, 50)
    assert wait_until(lambda: sensation("Arm_L", 51) in link.snapshot())


def test_the_test_button_has_its_own_ceiling(rig):
    eng, link, _ = rig
    assert eng.test_pulse("Dorsal_L", 90) is True
    assert link.snapshot()[-1] == sensation("Dorsal_L", oe.TEST_MAX)
    eng.set_caps({"Dorsal_L": 5}, 100)
    eng.test_pulse("Dorsal_L", 90)
    assert link.snapshot()[-1] == sensation("Dorsal_L", 5)
    assert eng.test_pulse("Tail") is False


def test_garbage_is_dropped_never_raised(rig):
    eng, link, _ = rig
    eng.set_active({"Arm_L": math.nan, "Tail": 50, "Arm_R": "x",
                    "Dorsal_L": math.inf, "Lumbar_L": -4}, "loud")
    time.sleep(0.1)
    assert all(b"SENSATION" not in m for m in link.snapshot())
    assert eng.status_snapshot()["frequency"] == oe.DEFAULT_FREQUENCY


def test_the_app_leaving_drops_the_link(rig):
    eng, link, links = rig
    calls = []
    eng.set_state_callback(lambda: calls.append(1))
    link.inbox.append(ol.APP_CLOSED)
    assert wait_until(lambda: link.closed)
    assert eng.status_snapshot()["error"] == "My OWO closed"
    assert calls
    # Still wanted: it looks for the app again on its next round.
    assert wait_until(lambda: len(links) >= 2 and eng.is_connected, timeout=5.0)


def test_disconnect_says_goodbye_after_the_stops(rig):
    eng, link, _ = rig
    eng.disconnect()
    assert link.snapshot()[-3:] == [ol.build_stop(), ol.build_stop(), ol.build_unavailable()]
    assert link.closed
    assert not eng.is_connected


def test_app_not_found_says_so():
    eng = OwoEngine(link_factory=lambda: FakeLink(answer=False))
    eng.start(True)
    try:
        assert wait_until(lambda: "not found" in eng.status_snapshot()["error"])
        assert not eng.is_connected
    finally:
        eng.stop()


def test_without_auto_connect_nothing_is_looked_for():
    made = []
    eng = OwoEngine(link_factory=lambda: made.append(1) or FakeLink())
    eng.start(False)
    try:
        time.sleep(0.1)
        assert made == []
        eng.connect()
        assert wait_until(lambda: eng.is_connected)
    finally:
        eng.stop()
