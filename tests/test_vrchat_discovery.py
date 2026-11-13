"""Which VRChat the OSC manager talks to when more than one VRChat record is
on the mDNS bus (vrchat_osc._on_service_state_change / _handle_disconnect /
the health check).

A crashed VRChat's mDNS record can linger for hours. The user's
osc_diagnostics.log (2026-11-08 07:48-09:29) shows a dead
VRChat-Client-305E19 (HTTP port 51722) next to the live
VRChat-Client-28372B (59868): every time the dead record was reported,
`http_port` was pointed at 51722 before anything checked it answered, the
health check then polled the dead port, and after two misses it dropped the
WORKING connection -- 125 times, ~3 s each -- and at 09:29:17 the dead
record's Removed dropped it once more.

The manager is built with its real __init__ but no Zeroconf, no sockets and
no network: `requests.get` is answered by a fake that knows which VRChat
HTTP ports are alive, and mDNS events go straight into the real handler.
"""
import socket
import threading
from types import SimpleNamespace
from urllib.parse import urlsplit

import pytest
import requests
from zeroconf import ServiceStateChange

import vrchat_osc
from vrchat_osc import VRChatOSCManager

LIVE = "VRChat-Client-28372B._oscjson._tcp.local."
LIVE_PORT = 59868
DEAD = "VRChat-Client-305E19._oscjson._tcp.local."
DEAD_PORT = 51722
OTHER = "VRChat-Client-AAAAAA._oscjson._tcp.local."
OTHER_PORT = 60001
SERVICE_TYPE = "_oscjson._tcp.local."


class _FakeVRChatHTTP:
    """Stands in for `requests.get`: a port in `alive` answers 200, any
    other times out the way a dead VRChat's port does on Windows."""

    def __init__(self, alive):
        self.alive = set(alive)
        self.calls = []                # (port, path) in order
        self.on_call = None            # hook: runs before the answer

    def get(self, url, timeout=None, **_kw):
        parts = urlsplit(url)
        self.calls.append((parts.port, parts.path or "/"))
        if self.on_call is not None:
            self.on_call(parts.port)
        if parts.port not in self.alive:
            raise requests.exceptions.ConnectTimeout(
                f"Connection to 127.0.0.1:{parts.port} timed out")
        return SimpleNamespace(status_code=200, json=lambda: {"FULL_PATH": "/"})


class _FakeZeroconf:
    def __init__(self, ports):
        self.ports = ports

    def get_service_info(self, service_type, name):
        return SimpleNamespace(port=self.ports[name],
                               addresses=[socket.inet_aton("127.0.0.1")])


class _FakeUDPClient:
    def __init__(self, ip, port):
        self.address = (ip, port)

    def send_message(self, *_a, **_kw):
        pass


class _FakeServerSocket:
    def sendto(self, *_a, **_kw):
        pass

    def getsockname(self):
        return ("127.0.0.1", 54958)


class _InlineThread:
    """Runs the target on start(), synchronously."""

    def __init__(self, target=None, daemon=None, name=None, args=()):
        self._target, self._args = target, args

    def start(self):
        if self._target is not None:
            self._target(*self._args)

    def is_alive(self):
        return False


class _Ticks:
    """A `_shutdown` event for the health loop: `wait()` returns False for
    `n` ticks (one poll each), then True so the loop ends."""

    def __init__(self, n):
        self.left = n

    def is_set(self):
        return self.left < 0

    def wait(self, _timeout=None):
        self.left -= 1
        return self.left < 0


@pytest.fixture
def net(monkeypatch):
    fake = _FakeVRChatHTTP(alive={LIVE_PORT, OTHER_PORT})
    monkeypatch.setattr(vrchat_osc.requests, "get", fake.get)
    monkeypatch.setattr(vrchat_osc, "SimpleUDPClient", _FakeUDPClient)
    return fake


@pytest.fixture
def mgr(monkeypatch, net):
    monkeypatch.setattr(vrchat_osc, "Zeroconf", lambda: None)
    m = VRChatOSCManager()
    m.logged = []
    m._log = m.logged.append                       # never the real log file
    m._vrchat_first_discovered_done = True         # sockets "already bound"
    m.osc_server = SimpleNamespace(socket=_FakeServerSocket())
    m.local_listen_port = 54958
    m.poll_current_parameters = lambda: {}
    m.fetch_all_parameters = lambda: None
    m.send_parameter = lambda *_a, **_kw: None     # the OGB heartbeat
    m.events = []
    m.on_connected = lambda ports: m.events.append(
        ("connected", ports["http_oscquery_port"]))
    m.on_disconnected = lambda: m.events.append("disconnected")
    m.zc = _FakeZeroconf({LIVE: LIVE_PORT, DEAD: DEAD_PORT, OTHER: OTHER_PORT})
    return m


def added(m, name):
    m._on_service_state_change(m.zc, SERVICE_TYPE, name, ServiceStateChange.Added)


def removed(m, name):
    m._on_service_state_change(m.zc, SERVICE_TYPE, name, ServiceStateChange.Removed)


def run_health_check(monkeypatch, m, polls):
    monkeypatch.setattr(vrchat_osc.threading, "Thread", _InlineThread)
    m._shutdown = _Ticks(polls)
    m._health_thread = None
    m._start_health_check()


# ----------------------------------------------------------------------
# One VRChat: unchanged
# ----------------------------------------------------------------------

def test_a_single_vrchat_connects_as_before(mgr):
    added(mgr, LIVE)
    assert mgr.is_connected
    assert mgr.http_port == LIVE_PORT
    assert mgr.vrc_osc_port == vrchat_osc.VRC_DEFAULT_PORT
    assert mgr.events == [("connected", LIVE_PORT)]
    assert mgr._connected_since is not None
    assert mgr._advertising_since == mgr._connected_since
    assert mgr.get_flow_state().advertising is True


def test_removal_of_the_vrchat_we_talk_to_disconnects_once(mgr):
    added(mgr, LIVE)
    removed(mgr, LIVE)
    removed(mgr, LIVE)
    assert not mgr.is_connected
    assert mgr.events == [("connected", LIVE_PORT), "disconnected"]


def test_the_health_check_still_drops_a_vrchat_that_stopped_answering(monkeypatch, mgr, net):
    added(mgr, LIVE)
    net.alive.discard(LIVE_PORT)                   # crashed, no mDNS goodbye
    run_health_check(monkeypatch, mgr, polls=2)
    assert not mgr.is_connected
    assert mgr.events == [("connected", LIVE_PORT), "disconnected"]


# ----------------------------------------------------------------------
# The dead leftover record from the log
# ----------------------------------------------------------------------

def test_a_leftover_dead_record_does_not_take_the_port(mgr):
    added(mgr, LIVE)
    added(mgr, DEAD)
    assert mgr.is_connected
    assert mgr.http_port == LIVE_PORT
    assert mgr.events == [("connected", LIVE_PORT)]


def test_the_health_check_keeps_polling_the_live_vrchat(monkeypatch, mgr, net):
    """The log's cycle end to end: live connects, the dead record shows up,
    two health-check polls later the working connection must still be up."""
    added(mgr, LIVE)
    added(mgr, DEAD)
    net.calls.clear()
    run_health_check(monkeypatch, mgr, polls=2)
    assert mgr.is_connected
    assert mgr.events == [("connected", LIVE_PORT)]
    assert net.calls == [(LIVE_PORT, "/"), (LIVE_PORT, "/")]


def test_removal_of_the_dead_record_keeps_the_connection(mgr):
    """09:29:17 in the log: VRChat-Client-305E19's Removed dropped the live one."""
    added(mgr, LIVE)
    added(mgr, DEAD)
    removed(mgr, DEAD)
    assert mgr.is_connected
    assert mgr.events == [("connected", LIVE_PORT)]


def test_a_dead_record_while_disconnected_does_not_block_the_live_one(mgr):
    added(mgr, DEAD)
    assert not mgr.is_connected
    assert mgr.http_port != DEAD_PORT              # the dead port is never kept
    added(mgr, LIVE)
    assert mgr.is_connected
    assert mgr.http_port == LIVE_PORT
    assert mgr.events == [("connected", LIVE_PORT)]


# ----------------------------------------------------------------------
# Two VRChat records that both answer
# ----------------------------------------------------------------------

def test_a_second_live_vrchat_does_not_take_over(mgr):
    added(mgr, LIVE)
    added(mgr, OTHER)
    assert mgr.http_port == LIVE_PORT
    assert mgr.events == [("connected", LIVE_PORT)]


def test_a_restarted_vrchat_replaces_the_dead_one(mgr, net):
    """VRChat crashed and came back before the health check noticed: the new
    record answers, ours doesn't -- switch, with a disconnect in between."""
    added(mgr, LIVE)
    net.alive.discard(LIVE_PORT)
    added(mgr, OTHER)
    assert mgr.is_connected
    assert mgr.http_port == OTHER_PORT
    assert mgr.events == [("connected", LIVE_PORT), "disconnected",
                          ("connected", OTHER_PORT)]
    removed(mgr, LIVE)                             # the old record's goodbye
    assert mgr.is_connected


def test_a_health_miss_on_the_old_port_keeps_the_new_connection(monkeypatch, mgr, net):
    """The health check polled the old port; by the time its second miss
    lands the manager already switched to the restarted VRChat."""
    added(mgr, LIVE)
    net.alive.discard(LIVE_PORT)
    misses = []

    def switch_during_second_miss(port):
        if port == LIVE_PORT:
            misses.append(port)
            if len(misses) == 2:
                added(mgr, OTHER)                  # mDNS thread, mid-poll

    net.on_call = switch_during_second_miss
    run_health_check(monkeypatch, mgr, polls=2)
    assert mgr.is_connected
    assert mgr.http_port == OTHER_PORT
    assert mgr.events == [("connected", LIVE_PORT), "disconnected",
                          ("connected", OTHER_PORT)]
