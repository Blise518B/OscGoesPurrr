"""BHapticsEngine against a fake radio: what reaches the suit, when.

Pinned here: a found device is connected and zeroed, a changed frame goes
out at once and an unchanged one doesn't, a burst collapses into its newest
frame, a stalled frame expires to zero, Off / release / stop write zero
twice, and a failed write drops the device."""

import threading
import time

import pytest

import bhaptics_models as models
from bhaptics_ble import Found
from bhaptics_engine import BHapticsEngine


class FakeLink:
    def __init__(self, found):
        self.address = found.address
        self.name = found.name
        self.writes = []
        self.closed = False
        self.fail = False
        self.battery = 77

    @property
    def is_connected(self):
        return not self.closed

    async def write(self, data):
        if self.fail:
            raise OSError("radio gone")
        self.writes.append(bytes(data))

    async def read_battery(self):
        return self.battery

    async def close(self):
        self.closed = True


class FakeRadio:
    available = True
    unavailable_reason = ""

    def __init__(self, names=("TactSuitPro",)):
        self.found = [Found(f"AA:00:00:00:00:{i:02X}", n) for i, n in enumerate(names)]
        self.links = {}
        self.scans = 0

    async def discover(self, timeout):
        self.scans += 1
        return list(self.found)

    async def open(self, found, on_lost, motor_char=models.MOTOR_CHAR):
        link = FakeLink(found)
        link.motor_char = motor_char
        self.links[found.address] = link
        return link


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


def wait_until(pred, timeout=2.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if pred():
            return True
        time.sleep(0.005)
    return pred()


@pytest.fixture
def rig():
    radio = FakeRadio()
    clock = Clock()
    eng = BHapticsEngine(radio_factory=lambda: radio, clock=clock)
    eng.start(True)
    assert wait_until(lambda: eng.is_connected)
    link = next(iter(radio.links.values()))
    assert wait_until(lambda: link.writes)     # the initial zero frame
    yield eng, radio, link, clock
    eng.stop()


ZERO = models.zero_frame(models.bind("TactSuitPro"))


def vest(front=None, back=None):
    return models.encode(models.bind("TactSuitPro"),
                         {"VestFront": front or [0] * 20, "VestBack": back or [0] * 20})


def test_found_device_is_connected_and_zeroed(rig):
    eng, _radio, link, _clock = rig
    assert link.writes == [ZERO]
    assert link.motor_char == models.GRID_MOTOR_CHAR     # a Pro takes its own frame
    snap = eng.status_snapshot()
    assert snap["devices"][0]["model"] == "pro"
    assert snap["devices"][0]["positions"] == ["VestFront", "VestBack"]
    assert wait_until(lambda: eng.status_snapshot()["devices"][0]["battery"] == 77)
    assert eng.connected_positions() == {"VestFront", "VestBack"}


def test_a_changed_frame_goes_out_and_an_unchanged_one_does_not(rig):
    eng, _radio, link, _clock = rig
    front = [0] * 20
    front[5] = 100
    eng.submit_frame("VestFront", front)
    assert wait_until(lambda: len(link.writes) == 2)
    assert link.writes[-1] == vest(front=front)
    eng.submit_frame("VestFront", front)
    time.sleep(0.08)
    assert len(link.writes) == 2


def test_a_burst_collapses_into_its_newest_frame(rig):
    eng, _radio, link, _clock = rig
    eng.submit_frame("VestFront", [10] * 20)
    assert wait_until(lambda: len(link.writes) == 2)
    # The clock stands still, so the next write waits out the full gap and
    # these three land inside it.
    eng.submit_frame("VestFront", [20] * 20)
    eng.submit_frame("VestFront", [30] * 20)
    eng.submit_frame("VestFront", [100] * 20)
    assert wait_until(lambda: link.writes[-1] == vest(front=[100] * 20))
    time.sleep(0.08)
    assert len(link.writes) <= 4


def test_a_stalled_frame_expires_to_zero(rig):
    eng, _radio, _link, clock = rig
    eng.submit_frame("VestBack", [60] * 20)
    assert eng._expire_stale(clock.t + 0.1) == []
    assert eng._expire_stale(clock.t + 0.3) == ["VestBack"]
    assert eng.output_snapshot()["VestBack"] == (0,) * 20
    # Already zero: nothing more to expire.
    assert eng._expire_stale(clock.t + 1.0) == []


def test_resubmitting_keeps_a_held_frame_alive(rig):
    eng, _radio, _link, clock = rig
    eng.submit_frame("VestFront", [40] * 20)
    clock.t += 0.2
    eng.submit_frame("VestFront", [40] * 20)
    assert eng._expire_stale(clock.t + 0.1) == []


def test_end_all_writes_zero_twice(rig):
    eng, _radio, link, _clock = rig
    eng.submit_frame("VestFront", [100] * 20)
    assert wait_until(lambda: link.writes[-1] == vest(front=[100] * 20))
    n = len(link.writes)
    eng.end_all()
    assert wait_until(lambda: link.writes[n:n + 2] == [ZERO, ZERO])
    assert eng.output_snapshot()["VestFront"] == (0,) * 20


def test_release_lets_go_and_stays_released(rig):
    eng, radio, link, _clock = rig
    eng.submit_frame("VestFront", [100] * 20)
    assert wait_until(lambda: link.writes[-1] == vest(front=[100] * 20))
    eng.release()
    assert wait_until(lambda: link.closed)
    assert link.writes[-2:] == [ZERO, ZERO]
    assert wait_until(lambda: not eng.is_connected)
    assert eng.status_snapshot()["released"] is True
    scans = radio.scans
    time.sleep(0.1)
    assert radio.scans == scans          # no reconnect behind the user's back


def test_connect_after_release_reconnects(rig):
    eng, radio, link, _clock = rig
    eng.release()
    assert wait_until(lambda: not eng.is_connected)
    eng.connect()
    assert wait_until(lambda: eng.is_connected)
    assert radio.links[link.address] is not link


def test_a_failed_write_drops_the_device(rig):
    eng, _radio, link, _clock = rig
    calls = []
    eng.set_state_callback(lambda: calls.append(1))
    link.fail = True
    eng.submit_frame("VestFront", [100] * 20)
    assert wait_until(lambda: not eng.is_connected)
    assert "write failed" in eng.status_snapshot()["error"]
    assert calls


def test_stop_zeroes_and_ends_the_thread():
    radio = FakeRadio()
    eng = BHapticsEngine(radio_factory=lambda: radio, clock=Clock())
    eng.start(True)
    assert wait_until(lambda: eng.is_connected)
    link = next(iter(radio.links.values()))
    assert wait_until(lambda: link.writes)     # the initial zero frame
    eng.submit_frame("VestFront", [100] * 20)
    assert wait_until(lambda: link.writes[-1] == vest(front=[100] * 20))
    threads = threading.active_count()
    eng.stop()
    assert link.closed
    assert link.writes[-2:] == [ZERO, ZERO]
    assert not eng.is_connected
    assert threading.active_count() < threads


def test_plain_devices_get_their_own_position():
    radio = FakeRadio(("Tactosy2_R",))
    eng = BHapticsEngine(radio_factory=lambda: radio, clock=Clock())
    eng.start(True)
    try:
        assert wait_until(lambda: eng.is_connected)
        link = next(iter(radio.links.values()))
        assert wait_until(lambda: link.writes)     # the initial zero frame
        eng.submit_frame("ForearmL", [100] * 6)     # not this sleeve
        eng.submit_frame("ForearmR", [0, 10, 20, 30, 40, 50])
        assert wait_until(lambda: link.writes[-1] == bytes([0, 10, 20, 30, 40, 50]))
        assert all(w != bytes([100] * 6) for w in link.writes)
    finally:
        eng.stop()


def test_garbage_and_unknown_positions_are_harmless(rig):
    eng, _radio, link, _clock = rig
    eng.submit_frame("Tail", [100] * 20)
    eng.submit_frame("VestFront", ["x", float("nan"), float("inf"), -3, None])
    assert eng.output_snapshot()["VestFront"][:5] == (0, 0, 100, 0, 0)
    assert "Tail" not in eng.output_snapshot()


def test_without_bluetooth_it_says_so_and_never_scans():
    radio = FakeRadio()
    radio.available = False
    radio.unavailable_reason = "bleak is not installed"
    eng = BHapticsEngine(radio_factory=lambda: radio, clock=Clock())
    eng.start(True)
    try:
        time.sleep(0.05)
        assert radio.scans == 0
        assert eng.status_snapshot()["error"] == "bleak is not installed"
    finally:
        eng.stop()


def test_paused_zeroes_and_ignores_every_frame_until_resume(rig):
    eng, _radio, link, _clock = rig
    eng.submit_frame("VestFront", [100] * 20)
    assert wait_until(lambda: link.writes[-1] == vest(front=[100] * 20))
    n = len(link.writes)
    eng.set_paused(True)
    assert eng.is_paused and eng.status_snapshot()["paused"]
    assert wait_until(lambda: link.writes[n:n + 2] == [ZERO, ZERO])
    eng.submit_frame("VestFront", [100] * 20)       # the router, a test, a held dot
    time.sleep(0.08)
    assert eng.output_snapshot()["VestFront"] == (0,) * 20
    assert link.writes[-1] == ZERO
    eng.set_paused(False)
    eng.submit_frame("VestFront", [50] * 20)
    assert wait_until(lambda: link.writes[-1] == vest(front=[50] * 20))
