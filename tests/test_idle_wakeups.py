"""Nothing to do, nothing to wake for: the routing tick sleeps while no OSC
arrives and every output rests at zero, and wakes at once when something
does -- no added latency; its beat comes from a PreciseAlarm, and a beat
from an older generation does nothing. The Buttplug worker runs a pass the
moment a target changes and otherwise idles, keeping the full rate only
while something still needs it (main._routing_next_delay / _wake_routing /
_routing_schedule, haptic_engine)."""

import asyncio
import queue
import threading
import time

import pytest
from buttplug import OutputType

import haptic_engine
import main
from constants import HAPTIC_IDLE_RATE, HAPTIC_POLL_RATE, ROUTER_IDLE_MS
from controllers.osc_facade import OscFacade


class FakeUI:
    def __init__(self):
        self.scheduled = []

    def schedule_callback(self, delay, fn):
        self.scheduled.append((delay, fn))


class Host:
    _routing_next_delay = main.OscGoesPurrrApp._routing_next_delay
    _wake_routing = main.OscGoesPurrrApp._wake_routing
    _routing_wake_now = main.OscGoesPurrrApp._routing_wake_now
    _routing_schedule = main.OscGoesPurrrApp._routing_schedule
    _routing_alarm_rang = main.OscGoesPurrrApp._routing_alarm_rang
    _routing_beat = main.OscGoesPurrrApp._routing_beat
    on_osc_message = OscFacade.on_osc_message

    def __init__(self):
        self.ui = FakeUI()
        self._needs_recalculation = False
        self._routing_asleep = False
        self._routing_gen = 0
        self._routing_alarm = None
        self._routing_alarm_gen = -1
        self.thread_queue = queue.Queue()
        self.ticks = 0
        self._routing_tick = self._tick

    def _tick(self):
        self.ticks += 1


def test_busy_keeps_the_full_rate():
    h = Host()
    assert h._routing_next_delay(True, 11) == 11
    assert not h._routing_asleep


def test_idle_sleeps():
    h = Host()
    assert h._routing_next_delay(False, 11) == ROUTER_IDLE_MS
    assert h._routing_asleep


def test_a_packet_that_lands_while_falling_asleep_is_not_missed():
    h = Host()
    h._needs_recalculation = True           # set after the tick looked, before it slept
    assert h._routing_next_delay(False, 11) == 11
    assert not h._routing_asleep


def test_a_packet_wakes_the_sleeping_tick_once():
    h = Host()
    h._routing_next_delay(False, 11)
    h.on_osc_message("avatar/parameters/Contact", 0.5)
    h.on_osc_message("avatar/parameters/Contact", 0.6)
    assert [d for d, _fn in h.ui.scheduled] == [0]     # one wake, at once
    assert not h._routing_asleep
    _delay, fn = h.ui.scheduled[0]
    gen = h._routing_gen
    fn()
    assert h.ticks == 1 and h._routing_gen == gen + 1   # the sleeping chain retires


def test_awake_packets_schedule_nothing():
    h = Host()
    h.on_osc_message("avatar/parameters/Contact", 0.5)
    assert h.ui.scheduled == [] and h._needs_recalculation


class FakeAlarm:
    def __init__(self):
        self.armed = []

    def set(self, delay_ms):
        self.armed.append(delay_ms)


def test_the_beat_comes_from_the_alarm():
    h = Host()
    h._routing_alarm = FakeAlarm()
    h._routing_schedule(11.1)
    assert h._routing_alarm.armed == [11.1] and h.ui.scheduled == []
    h._routing_alarm_rang()                 # the alarm's thread
    [(delay, beat)] = h.ui.scheduled
    assert delay == 0                       # straight to the UI thread
    beat()
    assert h.ticks == 1


def test_a_beat_of_an_older_generation_does_nothing():
    h = Host()
    h._routing_alarm = FakeAlarm()
    h._routing_schedule(11.1)
    h._routing_alarm_rang()                 # rang, on its way to the UI thread...
    h._routing_wake_now()                   # ...while a packet already ran a tick
    assert h.ticks == 1
    _delay, stale = h.ui.scheduled[-1]
    stale()
    assert h.ticks == 1


def test_without_an_alarm_the_beat_is_a_ui_callback():
    h = Host()
    h._routing_schedule(11.1)
    [(delay, beat)] = h.ui.scheduled
    assert delay == 11
    beat()
    assert h.ticks == 1


# ---- the Buttplug worker -------------------------------------------------------

async def _nothing():
    return None


def _first_nap(engine, monkeypatch):
    paces = []

    async def fake_nap(seconds):
        paces.append(seconds)
        raise asyncio.CancelledError

    monkeypatch.setattr(engine, "_nap", fake_nap)
    monkeypatch.setattr(engine, "_poll_device_list", _nothing)
    monkeypatch.setattr(engine, "_poll_device_batteries", _nothing)
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(engine.async_worker())
    return paces[0]


class FakeClient:
    connected = True

    def __init__(self, devices):
        self.devices = devices


class FakeDevice:
    name = "Toy"


class FakeFeature:
    def __init__(self):
        self.sent = []

    async def _send(self, cmd):
        self.sent.append(cmd)

    def run_output(self, cmd):
        return self._send(cmd)


def _connected(features=None):
    eng = haptic_engine.HapticEngine(queue.Queue())
    eng.buttplug_client = FakeClient({1: FakeDevice()})
    eng.mark_connected(True)
    if features is not None:
        eng._motor_features["Toy"] = features
    return eng


def test_worker_idles_without_a_toy_server(monkeypatch):
    eng = haptic_engine.HapticEngine(queue.Queue())
    assert _first_nap(eng, monkeypatch) == HAPTIC_IDLE_RATE


def test_worker_idles_with_a_server_but_no_toy(monkeypatch):
    eng = haptic_engine.HapticEngine(queue.Queue())
    eng.buttplug_client = FakeClient({})
    eng.mark_connected(True)
    assert _first_nap(eng, monkeypatch) == HAPTIC_IDLE_RATE


def test_worker_idles_with_a_toy_and_nothing_to_send(monkeypatch):
    # A change wakes it, so with nothing held back it needs no fast passes.
    eng = _connected([("vibrate", OutputType.VIBRATE, FakeFeature())])
    assert _first_nap(eng, monkeypatch) == HAPTIC_IDLE_RATE


def test_worker_keeps_the_full_rate_while_a_value_is_held_back(monkeypatch):
    # A stop the cap or an in-flight send holds back must still go out,
    # even if nothing changes again.
    eng = _connected([("vibrate", OutputType.VIBRATE, FakeFeature())])
    eng.update_target("Toy", 0, 0.5)
    eng._send_gate.set_inflight(("Toy", 0), True)
    assert _first_nap(eng, monkeypatch) == HAPTIC_POLL_RATE


def test_worker_keeps_the_full_rate_for_a_linear_toy(monkeypatch):
    # Its stroke physics moves between target changes.
    eng = _connected([("linear", OutputType.POSITION, FakeFeature())])
    assert _first_nap(eng, monkeypatch) == HAPTIC_POLL_RATE


class FakeLoop:
    def __init__(self):
        self.calls = []

    def call_soon_threadsafe(self, fn):
        self.calls.append(fn)


def test_a_changed_target_wakes_the_worker_once_per_pass():
    eng = haptic_engine.HapticEngine(queue.Queue())
    eng._loop, eng._wake = FakeLoop(), asyncio.Event()
    eng.update_target("Toy", 0, 0.5)
    eng.update_target("Toy", 1, 0.6)
    assert len(eng._loop.calls) == 1        # one wake for both
    eng._wake_asked = False                 # the worker's next pass began
    eng.update_target("Toy", 0, 0.5)        # unchanged: nothing to wake for
    assert len(eng._loop.calls) == 1
    eng.update_target("Toy", 0, 0.7)
    assert len(eng._loop.calls) == 2


def test_a_target_from_another_thread_ends_the_nap_at_once(monkeypatch):
    monkeypatch.setattr(haptic_engine, "HAPTIC_IDLE_RATE", 5.0)   # a nap of 5 s
    eng = haptic_engine.HapticEngine(queue.Queue())
    naps = []
    real_nap = eng._nap

    async def nap(seconds):
        naps.append(time.perf_counter())
        if len(naps) == 2:
            raise asyncio.CancelledError
        await real_nap(seconds)

    monkeypatch.setattr(eng, "_nap", nap)

    def router():
        time.sleep(0.05)
        eng.update_target("Toy", 0, 0.5)

    threading.Thread(target=router, daemon=True).start()
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(eng.async_worker())
    assert naps[1] - naps[0] < 1.0


def test_a_held_value_goes_out_when_its_send_finishes(monkeypatch):
    feature = FakeFeature()
    eng = _connected([("vibrate", OutputType.VIBRATE, feature)])
    passes = []

    async def nap(seconds):
        passes.append(seconds)
        if len(passes) == 1:
            eng.update_target("Toy", 0, 0.8)    # arrives while 0.5 is in flight
        if len(passes) == 4:
            raise asyncio.CancelledError
        await asyncio.sleep(0)                  # let the send task run

    monkeypatch.setattr(eng, "_nap", nap)
    monkeypatch.setattr(eng, "_poll_device_list", _nothing)
    monkeypatch.setattr(eng, "_poll_device_batteries", _nothing)
    monkeypatch.setattr(eng._send_gate, "default_interval_ms", 0.0)   # no cap here
    eng.update_target("Toy", 0, 0.5)
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(eng.async_worker())
    assert [c.value for c in feature.sent] == [0.5, 0.8]
