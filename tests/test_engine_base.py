"""Tests for the cold-path connection supervisors in engine_base.

Driven entirely through fakes — no real sockets/time. The reconnect loop's
sleep is injected so backoff math is asserted deterministically; most tests
run the loop inline (not via start()) so they control exactly how many
iterations happen before stopping. Lifecycle and locking tests use real
(short-lived) threads because that is the surface under test.

Both flavours share one documented contract, so the public surface is
asserted in parity: a method existing on ReconnectingEngine but missing on
AsyncReconnectingEngine is a bug (this exact gap shipped once — the Coyote
Connect button called a manual_connect() that did not exist).
"""

import threading
import time

import pytest

from engine_base import AsyncReconnectingEngine, ReconnectingEngine


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

    def test_auto_connect_off_closes_loop_owned_link_and_idles(self):
        # Connect via the loop itself (auto-connect on), then flip the getter
        # off: the loop must drop the link IT opened.
        eng = FakeEngine()
        auto = {"on": True}
        eng.set_auto_connect_getter(lambda: auto["on"])
        calls = []

        def sleep(d):
            calls.append(d)
            auto["on"] = False               # user disables auto-connect
            if len(calls) >= 2:
                eng._stop.set()

        eng._sleep = sleep
        eng._reconnect_loop()
        assert eng.open_calls == 1
        assert eng.close_calls == 1          # dropped the loop-owned link
        assert eng.is_connected is False

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


class TestManualHold:
    """The reconnect loop must never tear down a manual_connect() session
    just because auto-connect is off — that is the primary connect flow for
    the backends whose auto-connect deliberately defaults off (PiShock,
    Coyote, OWO, Handy)."""

    def test_loop_keeps_manual_connection_when_auto_connect_off(self):
        eng = FakeEngine()
        eng.set_auto_connect_getter(lambda: False)
        assert eng.manual_connect() is True
        calls, sleep = _looping_sleep(eng, stop_after=3)
        eng._sleep = sleep
        eng._reconnect_loop()
        assert eng.close_calls == 0          # survived three loop passes
        assert eng.is_connected is True

    def test_manual_hold_expires_when_connection_drops(self):
        eng = FakeEngine()
        eng.set_auto_connect_getter(lambda: False)
        assert eng.manual_connect() is True
        eng._connected = False               # link died on its own
        calls, sleep = _looping_sleep(eng, stop_after=1)
        eng._sleep = sleep
        eng._reconnect_loop()
        assert eng._manual_hold is False     # latch expired with the session
        assert eng.open_calls == 1           # loop did not auto-reopen

    def test_manual_connect_on_live_link_latches_it(self):
        eng = FakeEngine()
        eng.set_auto_connect_getter(lambda: False)
        eng._connected = True                # loop-owned link
        assert eng.manual_connect() is True  # user clicks Connect anyway
        calls, sleep = _looping_sleep(eng, stop_after=1)
        eng._sleep = sleep
        eng._reconnect_loop()
        assert eng.close_calls == 0          # now held as a manual session


class TestConnectLocking:
    def test_manual_connect_during_loop_open_does_not_double_open(self):
        eng = FakeEngine()
        eng.set_auto_connect_getter(lambda: True)
        gate = threading.Event()
        entered = threading.Event()
        real_open = FakeEngine._open

        def slow_open(self):
            entered.set()
            assert gate.wait(timeout=5.0)
            real_open(self)

        eng._open = slow_open.__get__(eng)
        calls, sleep = _looping_sleep(eng, stop_after=1)
        eng._sleep = sleep
        loop_thread = threading.Thread(target=eng._reconnect_loop, daemon=True)
        loop_thread.start()
        assert entered.wait(timeout=5.0)     # loop is inside _open()

        results = []
        ui_thread = threading.Thread(
            target=lambda: results.append(eng.manual_connect()), daemon=True)
        ui_thread.start()                    # blocks on the connect lock
        time.sleep(0.05)
        gate.set()                           # let the loop's open finish
        ui_thread.join(timeout=5.0)
        loop_thread.join(timeout=5.0)
        assert not ui_thread.is_alive() and not loop_thread.is_alive()
        assert results == [True]
        assert eng.open_calls == 1           # manual saw the live link, no 2nd open


class TestStartStop:
    def test_stop_calls_close(self):
        eng = FakeEngine()
        eng._connected = True
        eng.stop()
        assert eng.close_calls == 1

    def test_stop_clears_manual_hold(self):
        eng = FakeEngine()
        eng.manual_connect()
        eng.stop()
        assert eng._manual_hold is False

    def test_stop_then_start_spawns_fresh_supervisor(self):
        # stop() doesn't join; a quick stop→start (Settings feature toggle)
        # must still leave a LIVE supervisor, not no-op against the old
        # draining thread.
        eng = FakeEngine()
        eng.set_auto_connect_getter(lambda: False)
        eng.start()
        first = eng._conn_thread
        assert first.is_alive()
        eng.stop()
        eng.start()
        second = eng._conn_thread
        try:
            assert second is not first
            assert second.is_alive()
            assert not eng._stop.is_set()
        finally:
            eng.stop()
            second.join(timeout=2.0)


# ======================================================================
# Contract parity — both flavours document "same public surface".
# ======================================================================

PUBLIC_SURFACE = [
    "is_connected", "is_available", "last_error",
    "set_auto_connect_getter", "set_state_callback",
    "start", "stop", "manual_connect",
]


@pytest.mark.parametrize("cls", [ReconnectingEngine, AsyncReconnectingEngine])
@pytest.mark.parametrize("name", PUBLIC_SURFACE)
def test_public_surface_parity(cls, name):
    assert hasattr(cls, name), f"{cls.__name__} is missing {name}"


class FakeAsyncEngine(AsyncReconnectingEngine):
    def __init__(self, **kw):
        super().__init__("FakeAsync", **kw)
        self.open_calls = 0
        self.close_calls = 0
        self.open_should_raise = False

    async def _open(self):
        self.open_calls += 1
        if self.open_should_raise:
            raise RuntimeError("boom")
        self._connected = True

    async def _close(self):
        self.close_calls += 1
        self._connected = False


class TestAsyncManualConnect:
    def test_connects_and_survives_auto_connect_off_loop(self):
        eng = FakeAsyncEngine()
        eng.set_auto_connect_getter(lambda: False)
        eng.start()
        try:
            assert eng.manual_connect(timeout=5.0) is True
            assert eng.is_connected is True
            assert eng.open_calls == 1
            # Let the reconnect loop take at least one full auto-connect-off
            # pass: it must NOT tear the manual session down.
            time.sleep(1.3)
            assert eng.is_connected is True
            assert eng.close_calls == 0
        finally:
            eng.stop()

    def test_failure_records_error(self):
        eng = FakeAsyncEngine()
        eng.open_should_raise = True
        eng.start()
        try:
            assert eng.manual_connect(timeout=5.0) is False
            assert eng.last_error == "boom"
            assert eng.is_connected is False
        finally:
            eng.stop()

    def test_without_running_loop_fails_cleanly(self):
        eng = FakeAsyncEngine()
        assert eng.manual_connect() is False
        assert "not running" in (eng.last_error or "")

    def test_quick_stop_start_toggle_leaves_live_engine(self):
        # Regression: start() used to no-op against a still-draining loop
        # thread, leaving the engine permanently dead ("engine is not
        # running") after a fast feature off/on toggle — and the connect
        # lock used to stay pinned to the FIRST loop generation, raising
        # "bound to a different event loop" on the new one.
        eng = FakeAsyncEngine()
        eng.set_auto_connect_getter(lambda: False)
        eng.start()
        eng.stop()
        eng.start()   # must wait out the draining generation, then respawn
        try:
            assert eng.manual_connect(timeout=5.0) is True
            assert eng.is_connected is True
        finally:
            eng.stop()

    def test_manual_connect_racing_stop_does_not_leak(self):
        # A manual connect that completes after stop() must not hand back a
        # live, unsupervised link.
        eng = FakeEngine()
        eng.stop()                       # stop event set before the click
        assert eng.manual_connect() is False
        assert eng.is_connected is False
        assert eng.close_calls >= 1      # the fresh link was torn down
