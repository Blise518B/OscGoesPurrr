"""PreciseAlarm keeps the routing tick's beat: it rings once per set, the
newest set wins, cancel and close silence it -- and it keeps time where a
QTimer or a Python timed wait falls back to Windows' 15.6 ms step."""

import statistics
import threading
import time

from precise_alarm import PreciseAlarm


class Rings:
    def __init__(self):
        self.times = []
        self.event = threading.Event()

    def __call__(self):
        self.times.append(time.perf_counter())
        self.event.set()

    def wait(self, timeout=2.0):
        ok = self.event.wait(timeout)
        self.event.clear()
        return ok


def test_it_rings_once_per_set():
    rings = Rings()
    alarm = PreciseAlarm(rings)
    try:
        alarm.set(5)
        assert rings.wait()
        time.sleep(0.05)
        assert len(rings.times) == 1
    finally:
        alarm.close()


def test_the_newest_set_wins():
    rings = Rings()
    alarm = PreciseAlarm(rings)
    try:
        start = time.perf_counter()
        alarm.set(2000)
        alarm.set(5)                        # replaces the 2 s one
        assert rings.wait()
        assert rings.times[0] - start < 1.0
        time.sleep(0.05)
        assert len(rings.times) == 1
    finally:
        alarm.close()


def test_cancel_and_close_silence_it():
    rings = Rings()
    alarm = PreciseAlarm(rings)
    alarm.set(30)
    alarm.cancel()
    time.sleep(0.1)
    assert rings.times == []
    alarm.close()
    alarm.set(1)                            # closed for good
    time.sleep(0.05)
    assert rings.times == []


def test_a_failing_ring_does_not_stop_it():
    calls = []

    def ring():
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("boom")

    alarm = PreciseAlarm(ring)
    try:
        alarm.set(1)
        time.sleep(0.1)
        alarm.set(1)
        time.sleep(0.1)
        assert len(calls) == 2
    finally:
        alarm.close()


def test_it_keeps_time():
    # 4 ms asked: a QTimer past Qt's 16 precise ones, Event.wait or
    # Condition.wait on Windows all take ~15.6 ms. Median, so a busy
    # machine's odd late ring doesn't fail it.
    rings = Rings()
    alarm = PreciseAlarm(rings)
    took = []
    try:
        for _ in range(15):
            start = time.perf_counter()
            alarm.set(4)
            assert rings.wait()
            took.append((rings.times[-1] - start) * 1000.0)
    finally:
        alarm.close()
    assert statistics.median(took) < 10.0, took
