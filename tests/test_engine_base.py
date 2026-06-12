"""Tests for the ReconnectingEngine cold-path connection supervisor.

Driven entirely through fakes — no real sockets/threads/time. The reconnect
loop's sleep is injected so backoff math is asserted deterministically, and
the loop is run inline (not via start()) so each test controls exactly how
many iterations happen before stopping.
"""

from engine_base import ReconnectingEngine


class FakeEngine(ReconnectingEngine):
    def __init__(self, *, available=True, **kw):
        super().__init__("Fake", **kw)
        self._avail = available
        self.open_calls = 0
        self.close_calls = 0
        self.open_should_raise = False

    @property
    def _available(self):
        return self._avail

    def _open(self):
        self.open_calls += 1
        if self.open_should_raise:
            raise RuntimeError("boom")
        self._connected = True

    def _close(self):
        self.close_calls += 1
        self._connected = False


def _looping_sleep(engine, stop_after):
    """A fake sleep that records durations and stops the engine's loop after
    `stop_after` calls, so _reconnect_loop terminates deterministically."""
    calls = []

    def sleep(d):
        calls.append(d)
        if len(calls) >= stop_after:
            engine._stop.set()

    return calls, sleep


class TestReconnectLoop:
    def test_successful_open_clears_error_and_notifies(self):
        notes = []
        eng = FakeEngine()
        eng.set_auto_connect_getter(lambda: True)
        eng.set_state_callback(lambda: notes.append(1))
        calls, sleep = _looping_sleep(eng, stop_after=1)
        eng._sleep = sleep
        eng._last_error = "stale"
        eng._reconnect_loop()
        assert eng.open_calls == 1
        assert eng.is_connected is True
        assert eng.last_error is None        # cleared on success
        assert notes == [1]                  # state-change fired once
        assert calls[0] == 1.0               # connected branch idles at 1s

    def test_open_failure_backs_off_and_caps(self):
        eng = FakeEngine(backoff_start=1.0, backoff_max=10.0, backoff_factor=2.0)
        eng.set_auto_connect_getter(lambda: True)
        eng.open_should_raise = True
        calls, sleep = _looping_sleep(eng, stop_after=6)
        eng._sleep = sleep
        eng._reconnect_loop()
        # Backoff doubles each failure and caps at backoff_max.
        assert calls[:5] == [1.0, 2.0, 4.0, 8.0, 10.0]
        assert eng.last_error == "boom"
        assert eng.is_connected is False

    def test_auto_connect_off_closes_and_idles(self):
        eng = FakeEngine()
        eng._connected = True                # pretend we were connected
        eng.set_auto_connect_getter(lambda: False)
        calls, sleep = _looping_sleep(eng, stop_after=1)
        eng._sleep = sleep
        eng._reconnect_loop()
        assert eng.close_calls == 1          # dropped the live link
        assert eng.open_calls == 0           # never reopened
        assert calls[0] == 1.0

    def test_unavailable_transport_idles_without_open(self):
        eng = FakeEngine(available=False)
        eng.set_auto_connect_getter(lambda: True)
        calls, sleep = _looping_sleep(eng, stop_after=1)
        eng._sleep = sleep
        eng._reconnect_loop()
        assert eng.open_calls == 0
        assert calls[0] == 5.0               # unavailable branch sleeps 5s


class TestManualConnect:
    def test_success(self):
        notes = []
        eng = FakeEngine()
        eng.set_state_callback(lambda: notes.append(1))
        assert eng.manual_connect() is True
        assert eng.is_connected is True
        assert eng.open_calls == 1
        assert notes == [1]

    def test_already_connected_is_noop(self):
        eng = FakeEngine()
        eng._connected = True
        assert eng.manual_connect() is True
        assert eng.open_calls == 0           # did not reopen

    def test_unavailable_sets_reason(self):
        eng = FakeEngine(available=False)
        assert eng.manual_connect() is False
        assert eng.last_error == eng._unavailable_reason

    def test_failure_records_error(self):
        eng = FakeEngine()
        eng.open_should_raise = True
        assert eng.manual_connect() is False
        assert eng.is_connected is False
        assert eng.last_error == "boom"


class TestStartStop:
    def test_stop_calls_close(self):
        eng = FakeEngine()
        eng._connected = True
        eng.stop()
        assert eng.close_calls == 1
