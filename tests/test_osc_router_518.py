"""Tests for the 518 OSC Fallback Standard client (518Hub/docs/STANDARD.md).

Two halves:
  * the starvation predicate — the standard's "10 s from advertising / 30 s
    for an established stream" rule, stated in prose there and here as code;
  * the Tier 0 <-> Tier 1 ladder — subscribe when VRChat's DIRECT stream dies,
    unsubscribe the moment it comes back.

The ladder is driven by calling `_tick()` directly with a fake socket, so no
threads, no sleeps, and no real router are involved.
"""

import struct
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from osc_router_518 import (  # noqa: E402
    FIRST_CONTACT_S, KEEPALIVE_S, ROUTER, ROUTER_PORT, STREAM_SILENT_S,
    TIER_DIRECT, TIER_ROUTER, OscFlowState, Router518Fallback, is_starved,
    starvation_deadline,
)


def _flow(port=9001, advertising=True, ever_direct=False, since=0.0):
    return OscFlowState(port=port, advertising=advertising,
                        ever_direct=ever_direct, since_direct_s=since)


def _decode(datagram):
    """Minimal OSC parse -> (address, [args]). Only the ,i and ,is control
    shapes the standard defines are supported."""
    end = datagram.index(b"\x00")
    address = datagram[:end].decode()
    rest = datagram[(len(address) // 4 + 1) * 4:]
    end = rest.index(b"\x00")
    tags = rest[:end].decode()
    rest = rest[(len(tags) // 4 + 1) * 4:]
    args = []
    for tag in tags[1:]:
        if tag == "i":
            args.append(struct.unpack(">i", rest[:4])[0])
            rest = rest[4:]
        elif tag == "s":
            end = rest.index(b"\x00")
            sval = rest[:end].decode()
            args.append(sval)
            rest = rest[(len(sval) // 4 + 1) * 4:]
    return address, args


class _FakeSock:
    """Captures control messages; recv() reports an empty buffer like a real
    non-blocking socket with nothing queued."""

    def __init__(self):
        self.sent = []
        self.closed = False

    def sendto(self, data, addr):
        assert addr == ROUTER
        self.sent.append(_decode(data))

    def recv(self, _n):
        raise BlockingIOError

    def close(self):
        self.closed = True

    # --- helpers -------------------------------------------------------
    def addresses(self):
        return [a for a, _ in self.sent]

    def pop(self):
        out, self.sent = self.sent, []
        return out


@pytest.fixture
def ladder():
    """A fallback wired to a mutable state slot and a fake socket."""
    box = {"state": _flow()}
    fb = Router518Fallback(lambda: box["state"], name="OGP-Test", log=lambda m: None)
    fb._sock = _FakeSock()
    return fb, box


class TestStarvationRule:
    def test_deadline_matches_the_standard(self):
        assert starvation_deadline(ever_direct=False) == FIRST_CONTACT_S == 10.0
        assert starvation_deadline(ever_direct=True) == STREAM_SILENT_S == 30.0

    def test_first_contact_window(self):
        # Never heard from VRChat: 10 s from advertising, per the standard.
        assert is_starved(_flow(ever_direct=False, since=9.9)) is False
        assert is_starved(_flow(ever_direct=False, since=10.0)) is True

    def test_established_stream_gets_the_longer_grace(self):
        # A working stream legitimately pauses; only 30 s of silence counts.
        assert is_starved(_flow(ever_direct=True, since=20.0)) is False
        assert is_starved(_flow(ever_direct=True, since=30.0)) is True

    def test_never_starved_without_somewhere_to_receive(self):
        assert is_starved(None) is False
        assert is_starved(_flow(advertising=False, since=999.0)) is False
        assert is_starved(_flow(port=None, since=999.0)) is False
        assert is_starved(_flow(since=None)) is False


class TestLadder:
    def test_starts_on_tier_0_and_stays_quiet(self, ladder):
        fb, box = ladder
        box["state"] = _flow(since=1.0)
        fb._tick()
        assert fb._tier == TIER_DIRECT
        assert fb._sock.sent == []          # a healthy stream never touches the router
        assert fb.get_state()["using_router"] is False

    def test_subscribes_once_the_direct_stream_starves(self, ladder):
        fb, box = ladder
        box["state"] = _flow(port=9001, since=FIRST_CONTACT_S + 0.1)
        fb._tick()
        assert fb._tier == TIER_ROUTER
        assert fb._sock.sent == [("/router518/subscribe", [9001, "OGP-Test"])]
        state = fb.get_state()
        assert state["using_router"] is True
        assert state["subscribed_port"] == 9001

    def test_unsubscribes_when_vrchat_comes_back(self, ladder):
        fb, box = ladder
        box["state"] = _flow(port=9001, since=FIRST_CONTACT_S + 0.1)
        fb._tick()
        fb._sock.pop()
        # A direct packet lands: since_direct_s resets and ever_direct flips.
        box["state"] = _flow(port=9001, ever_direct=True, since=0.0)
        fb._tick()
        assert fb._tier == TIER_DIRECT
        assert fb._sock.sent == [("/router518/unsubscribe", [9001])]

    def test_keepalive_cadence_while_subscribed(self, ladder):
        fb, box = ladder
        box["state"] = _flow(port=9001, since=FIRST_CONTACT_S + 0.1)
        fb._tick()
        fb._sock.pop()
        # Still starved, but not yet due: no traffic (spec allows <= 30 s).
        fb._tick()
        assert fb._sock.sent == []
        # Due: one more subscribe, which doubles as the keep-alive.
        fb._last_keepalive -= KEEPALIVE_S
        fb._tick()
        assert fb._sock.sent == [("/router518/subscribe", [9001, "OGP-Test"])]

    def test_rebound_port_moves_the_subscription(self, ladder):
        fb, box = ladder
        box["state"] = _flow(port=9001, since=FIRST_CONTACT_S + 0.1)
        fb._tick()
        fb._sock.pop()
        # toggle_osc_connection rebinds us on a new port while still starved.
        box["state"] = _flow(port=9100, since=FIRST_CONTACT_S + 0.1)
        fb._tick()
        assert fb._sock.sent == [("/router518/unsubscribe", [9001]),
                                 ("/router518/subscribe", [9100, "OGP-Test"])]
        assert fb.get_state()["subscribed_port"] == 9100

    def test_losing_the_osc_server_drops_the_subscription(self, ladder):
        fb, box = ladder
        box["state"] = _flow(port=9001, since=FIRST_CONTACT_S + 0.1)
        fb._tick()
        fb._sock.pop()
        box["state"] = None            # manager gone (disconnect / shutdown)
        fb._tick()
        assert fb._tier == TIER_DIRECT
        assert fb._sock.sent == [("/router518/unsubscribe", [9001])]

    def test_stop_unsubscribes_and_closes(self, ladder):
        fb, box = ladder
        box["state"] = _flow(port=9001, since=FIRST_CONTACT_S + 0.1)
        fb._tick()
        sock = fb._sock
        sock.pop()
        fb.stop()
        assert sock.sent == [("/router518/unsubscribe", [9001])]
        assert sock.closed is True
        assert fb.get_state()["using_router"] is False

    def test_a_missing_router_is_a_silent_no_op(self, ladder):
        fb, box = ladder

        class _Dead(_FakeSock):
            def sendto(self, data, addr):
                raise ConnectionResetError("ICMP port unreachable")

        fb._sock = _Dead()
        box["state"] = _flow(port=9001, since=FIRST_CONTACT_S + 0.1)
        fb._tick()      # must not raise — the fallback can't become a fault
        assert fb.get_state()["router_present"] is False

    def test_mdns_rereg_does_not_cut_the_router_stream(self, ladder):
        """Observed live 2026-08-01: the silent-connection self-heal re-publishes
        mDNS ~90 s in, which resets the first-contact anchor. The ladder then
        read the young advertisement age as 'VRChat is back', unsubscribed, and
        cut the only working stream for the length of the fresh 10 s window.
        With no direct packet EVER received, a subscription must survive the
        anchor reset."""
        fb, box = ladder
        box["state"] = _flow(port=9001, since=FIRST_CONTACT_S + 2.0)
        fb._tick()
        fb._sock.pop()
        # reregister_mdns(): advertisement age snaps back to ~0, ever_direct
        # still False because VRChat never actually reached us.
        box["state"] = _flow(port=9001, ever_direct=False, since=1.0)
        fb._tick()
        assert fb._tier == TIER_ROUTER
        assert "/router518/unsubscribe" not in fb._sock.addresses()
        # Keep-alives continue through the window so the TTL can't lapse.
        fb._last_keepalive -= KEEPALIVE_S
        fb._tick()
        assert fb._sock.sent == [("/router518/subscribe", [9001, "OGP-Test"])]
        # And once a REAL direct packet lands, the normal exit still works.
        box["state"] = _flow(port=9001, ever_direct=True, since=0.0)
        fb._tick()
        assert fb._tier == TIER_DIRECT
        assert fb._sock.addresses()[-1] == "/router518/unsubscribe"

    def test_ladder_does_not_flap_on_its_own_router_traffic(self, ladder):
        """The whole point of the direct/router split: once Tier 1 works, the
        router's own packets must NOT read as 'VRChat is back'. If they did,
        we'd unsubscribe, starve for 30 s, re-subscribe, forever."""
        fb, box = ladder
        box["state"] = _flow(port=9001, since=FIRST_CONTACT_S + 0.1)
        fb._tick()
        fb._sock.pop()
        # Router data is now pouring in, but since_direct_s keeps climbing
        # because only DIRECT packets reset it.
        for extra in (5.0, 30.0, 120.0):
            box["state"] = _flow(port=9001, since=FIRST_CONTACT_S + extra)
            fb._tick()
        assert fb._tier == TIER_ROUTER
        assert "/router518/unsubscribe" not in fb._sock.addresses()

    def test_router_ack_marks_it_present(self, ladder):
        fb, box = ladder

        class _Acking(_FakeSock):
            def __init__(self):
                super().__init__()
                self._replies = [b"/router518/ok\x00\x00\x00,i\x00\x00" + struct.pack(">i", 9001)]

            def recv(self, _n):
                if self._replies:
                    return self._replies.pop()
                raise BlockingIOError

        fb._sock = _Acking()
        assert fb.get_state()["router_present"] is False
        fb._tick()
        assert fb.get_state()["router_present"] is True


class TestPacketSourceClassification:
    """`VRChatOSCManager._dispatch_incoming` decides what counts as VRChat
    reaching us directly. Built without __init__ so the test never touches
    Zeroconf, sockets or the network."""

    def _manager(self):
        from vrchat_osc import VRChatOSCManager
        m = object.__new__(VRChatOSCManager)
        m._packets_direct = 0
        m._packets_via_router = 0
        m._last_direct_packet_time = None
        m._advertising_since = None
        m._connected_since = None
        m.seen = []
        m._handle_incoming_osc = lambda address, *args: m.seen.append((address, args))
        return m

    def test_router_rebroadcast_is_not_direct_contact(self):
        m = self._manager()
        m._dispatch_incoming(("127.0.0.1", ROUTER_PORT), "/avatar/parameters/X", 1.0)
        assert m._packets_via_router == 1
        assert m._packets_direct == 0
        # Crucially: the direct clock did NOT move.
        assert m._last_direct_packet_time is None
        # ...but the payload still reached the app untouched.
        assert m.seen == [("/avatar/parameters/X", (1.0,))]

    def test_vrchat_push_counts_as_direct_contact(self):
        m = self._manager()
        m._dispatch_incoming(("127.0.0.1", 9000), "/avatar/parameters/X", 1.0)
        assert m._packets_direct == 1
        assert m._packets_via_router == 0
        assert m._last_direct_packet_time is not None
        assert m.seen == [("/avatar/parameters/X", (1.0,))]

    def test_same_port_from_off_box_is_not_our_router(self):
        # The router is loopback-only; a LAN sender on the router port is someone else.
        m = self._manager()
        m._dispatch_incoming(("192.168.1.50", ROUTER_PORT), "/x", 1.0)
        assert m._packets_direct == 1
        assert m._packets_via_router == 0

    def test_malformed_source_never_raises(self):
        m = self._manager()
        for bogus in (None, (), ("only-host",), ("127.0.0.1", "not-a-port")):
            m._dispatch_incoming(bogus, "/x", 1.0)
        assert m._packets_direct == 4          # treated as direct, never dropped
        assert len(m.seen) == 4                # and always delivered

    def test_starvation_clock_anchors_on_advertising(self):
        import time as _time
        m = self._manager()
        assert m.seconds_since_direct_packet() is None      # nothing to measure yet
        m._advertising_since = _time.time() - 12.0
        assert m.seconds_since_direct_packet() == pytest.approx(12.0, abs=0.5)
        m._dispatch_incoming(("127.0.0.1", 9000), "/x", 1.0)
        assert m.seconds_since_direct_packet() == pytest.approx(0.0, abs=0.5)
        # Router traffic must not reset it.
        m._last_direct_packet_time = _time.time() - 40.0
        m._dispatch_incoming(("127.0.0.1", ROUTER_PORT), "/x", 1.0)
        assert m.seconds_since_direct_packet() == pytest.approx(40.0, abs=0.5)


class TestDispatcherWiring:
    """The classifier above is only worth anything if it is the handler the
    dispatcher actually calls.

    `_setup_osc` re-registers the default handler on every bind, and
    python-osc's `set_default_handler` REPLACES rather than chains — so
    registering the bare `_handle_incoming_osc` there silently disabled the
    direct/router split for the whole app: no packet ever reached
    `_dispatch_incoming`, `_last_direct_packet_time` stayed None forever, the
    status pill read "CONNECTED (518)" with no router running, the ladder
    never left Tier 1, and the silent watchdog re-published mDNS on a
    perfectly healthy link. Unit-testing `_dispatch_incoming` directly could
    not see any of that, so these tests go through the real dispatcher.

    Binds a real UDP socket on 127.0.0.1:0 — loopback only, no hardware.
    """

    @pytest.fixture
    def bound(self):
        from pythonosc.dispatcher import Dispatcher

        from vrchat_osc import VRChatOSCManager

        m = object.__new__(VRChatOSCManager)
        m.dispatcher = Dispatcher()
        m.osc_server = None
        m.server_thread = None
        m.osc_client = None
        m.local_listen_port = 0          # let the OS pick
        m.vrc_ip, m.vrc_osc_port = "127.0.0.1", 9000
        m._packets_direct = 0
        m._packets_via_router = 0
        m._last_direct_packet_time = None
        m.seen = []
        m._log = lambda *a, **k: None
        m._handle_incoming_osc = lambda address, *args: m.seen.append((address, args))
        # Everything past the UDP bind is out of scope here: the HTTP
        # phonebook and mDNS advertisement prove nothing about dispatch.
        m._start_phonebook_server = lambda: None
        m._advertise_service = lambda: None
        m._setup_osc()
        try:
            yield m
        finally:
            if m.osc_server is not None:
                m.osc_server.shutdown()
                m.osc_server.server_close()
            if m.osc_client is not None:
                m.osc_client._sock.close()

    @staticmethod
    def _deliver(m, source, address="/avatar/parameters/X", value=1.0):
        """Push one datagram through the dispatcher exactly as the UDP server
        would, so the registered handler — whichever it is — decides."""
        from pythonosc.osc_message_builder import OscMessageBuilder
        msg = OscMessageBuilder(address=address)
        msg.add_arg(value)
        m.dispatcher.call_handlers_for_packet(msg.build().dgram, source)

    def test_bind_registers_the_classifying_handler(self, bound):
        handler = bound.dispatcher._default_handler
        assert handler.callback == bound._dispatch_incoming
        # Without this the wrapper is called with the address as its first
        # positional arg and every source looks malformed.
        assert handler.needs_reply_address is True

    def test_vrchat_push_reaches_the_classifier_as_direct(self, bound):
        self._deliver(bound, ("127.0.0.1", 9000))
        assert bound._packets_direct == 1
        assert bound._packets_via_router == 0
        assert bound._last_direct_packet_time is not None
        assert bound.seen == [("/avatar/parameters/X", (1.0,))]

    def test_router_rebroadcast_reaches_the_classifier_as_router(self, bound):
        self._deliver(bound, ("127.0.0.1", ROUTER_PORT))
        assert bound._packets_via_router == 1
        assert bound._packets_direct == 0
        assert bound._last_direct_packet_time is None
        assert bound.seen == [("/avatar/parameters/X", (1.0,))]
