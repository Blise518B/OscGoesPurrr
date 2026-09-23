"""The silent-connection watchdog's retry loop (vrchat_osc._emit_diagnostics_tick).

Direct delivery is the lowest-latency path, so while it stays dead the
watchdog must keep courting it — reprobe + mDNS re-publish repeating every
_SILENT_RETRY_INTERVAL_S — instead of the old one-shot flags that gave up
after a single attempt ~90 s in and left the session riding the 518 router
forever. Managers are built without __init__ (no sockets, no zeroconf) and
threading.Thread is swapped for a synchronous shim so the self-heal targets
run inline.
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import vrchat_osc  # noqa: E402
from vrchat_osc import VRChatOSCManager  # noqa: E402


class _InlineThread:
    """Runs the target on start(), synchronously — no daemon threads in tests."""

    def __init__(self, target=None, daemon=None, name=None, args=()):
        self._target, self._args = target, args

    def start(self):
        if self._target is not None:
            self._target(*self._args)


def _silent_manager(silent_for: float):
    """A connected manager whose DIRECT stream has been dead for `silent_for`
    seconds while router traffic keeps the total packet counter moving."""
    now = time.time()
    m = object.__new__(VRChatOSCManager)
    m.is_connected = True
    m._connected_since = now - max(silent_for, 60.0)
    m._advertising_since = now - silent_for
    m._last_direct_packet_time = None
    m._last_packet_time = now              # router data is arriving
    m._packets_handled = 10_000
    m._packets_handled_at_last_log = 0
    m._packets_direct = 0
    m._packets_via_router = 10_000
    m._direct_at_last_log = 0
    m._phonebook_requests = 0
    m._handler_exceptions = 0
    m._silent_warning_logged = False
    m._last_silent_reprobe = None
    m._last_silent_rereg = None
    m.logged = []
    m._log = m.logged.append
    m.reprobes = 0
    m.reregs = 0
    m._reprobe_silent_connection = lambda: setattr(m, "reprobes", m.reprobes + 1)
    m.reregister_mdns = lambda: setattr(m, "reregs", m.reregs + 1)
    return m


def test_first_pass_runs_both_self_heals(monkeypatch):
    monkeypatch.setattr(vrchat_osc.threading, "Thread", _InlineThread)
    m = _silent_manager(silent_for=80.0)
    m._emit_diagnostics_tick()
    assert m._silent_warning_logged is True
    assert m.reprobes == 1 and m.reregs == 1


def test_not_retried_before_the_interval(monkeypatch):
    monkeypatch.setattr(vrchat_osc.threading, "Thread", _InlineThread)
    m = _silent_manager(silent_for=80.0)
    m._emit_diagnostics_tick()
    m._emit_diagnostics_tick()      # next tick, interval not elapsed
    assert m.reprobes == 1 and m.reregs == 1


def test_retried_after_the_interval(monkeypatch):
    """The core change: the self-heals repeat while direct stays dead, so a
    mid-session mDNS recovery can still promote us back off the router."""
    monkeypatch.setattr(vrchat_osc.threading, "Thread", _InlineThread)
    m = _silent_manager(silent_for=80.0)
    m._emit_diagnostics_tick()
    m._last_silent_reprobe -= VRChatOSCManager._SILENT_RETRY_INTERVAL_S
    m._last_silent_rereg -= VRChatOSCManager._SILENT_RETRY_INTERVAL_S
    m._emit_diagnostics_tick()
    assert m.reprobes == 2 and m.reregs == 2


def test_direct_recovery_rearms_and_router_traffic_does_not(monkeypatch):
    monkeypatch.setattr(vrchat_osc.threading, "Thread", _InlineThread)
    m = _silent_manager(silent_for=80.0)
    m._emit_diagnostics_tick()
    # Router packets alone (total moves, direct doesn't) never clear the
    # latch or reset the retry clocks — the direct stream is still dead.
    m._packets_handled += 5_000
    m._emit_diagnostics_tick()
    assert m._silent_warning_logged is True
    assert m._last_silent_rereg is not None
    # A real DIRECT packet clears the latch and re-arms both self-heals.
    m._packets_direct += 50
    m._last_direct_packet_time = time.time()
    m._emit_diagnostics_tick()
    assert m._silent_warning_logged is False
    assert m._last_silent_reprobe is None and m._last_silent_rereg is None
    assert any("direct packet flow restored" in line for line in m.logged)


def test_healthy_direct_stream_triggers_nothing(monkeypatch):
    monkeypatch.setattr(vrchat_osc.threading, "Thread", _InlineThread)
    m = _silent_manager(silent_for=1.0)
    m._packets_direct = 500
    m._last_direct_packet_time = time.time()
    m._emit_diagnostics_tick()
    assert m.reprobes == 0 and m.reregs == 0
    assert m._silent_warning_logged is False
