"""Nothing to do, nothing to wake for: the routing tick sleeps while no OSC
arrives and every output rests at zero, and wakes at once when something
does -- no added latency; the Buttplug worker idles while no toy is
connected (main._routing_next_delay / _wake_routing, haptic_engine)."""

import asyncio
import queue

import pytest

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
    on_osc_message = OscFacade.on_osc_message

    def __init__(self):
        self.ui = FakeUI()
        self._needs_recalculation = False
        self._routing_asleep = False
        self._routing_gen = 0
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


# ---- the Buttplug worker -------------------------------------------------------

def _first_sleep(engine, monkeypatch):
    delays = []

    async def fake_sleep(d):
        delays.append(d)
        raise asyncio.CancelledError

    async def nothing():
        return None

    monkeypatch.setattr(haptic_engine.asyncio, "sleep", fake_sleep)
    monkeypatch.setattr(engine, "_poll_device_list", nothing)
    monkeypatch.setattr(engine, "_poll_device_batteries", nothing)
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(engine.async_worker())
    return delays[0]


class FakeClient:
    connected = True

    def __init__(self, devices):
        self.devices = devices


class FakeDevice:
    name = "Toy"


def test_worker_idles_without_a_toy_server(monkeypatch):
    eng = haptic_engine.HapticEngine(queue.Queue())
    assert _first_sleep(eng, monkeypatch) == HAPTIC_IDLE_RATE


def test_worker_idles_with_a_server_but_no_toy(monkeypatch):
    eng = haptic_engine.HapticEngine(queue.Queue())
    eng.buttplug_client = FakeClient({})
    eng.mark_connected(True)
    assert _first_sleep(eng, monkeypatch) == HAPTIC_IDLE_RATE


def test_worker_keeps_the_full_rate_with_a_toy(monkeypatch):
    eng = haptic_engine.HapticEngine(queue.Queue())
    eng.buttplug_client = FakeClient({1: FakeDevice()})
    eng.mark_connected(True)
    assert _first_sleep(eng, monkeypatch) == HAPTIC_POLL_RATE
