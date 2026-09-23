"""Tier-aware client of the 518 OSC Fallback Standard (518Hub/docs/STANDARD.md).

VRChat's mDNS *listener* dies after a few hours of gameplay; from then on it
never discovers a freshly started or re-advertised app, so the app receives
nothing until VRChat is restarted (518Hub/docs/PROBLEM.md). OSC Router 518
starts early, gets discovered while VRChat is still healthy, and
re-broadcasts VRChat's stream verbatim. Subscribing our receive port there
keeps data flowing when VRChat can no longer see us.

This implements the standard's decision ladder rather than subscribing
unconditionally:

  * **Tier 0 (default)** — plain OSCQuery. VRChat pushes to us directly; the
    router is not involved.
  * **Tier 1 (automatic fallback)** — if nothing has arrived DIRECTLY from
    VRChat within 10 s of advertising (or an established stream goes silent
    for 30 s), subscribe and take VRChat's stream from the router instead.
    The Tier 0 advertisement stays up the whole time, so when VRChat
    rediscovers us the direct stream resumes, and we unsubscribe.

The direct/router split is what makes the ladder stable: router traffic
arrives on the same UDP port as VRChat's own, so if it counted as "healthy
direct discovery" the fallback would unsubscribe itself the instant it
started working, then re-subscribe 30 s later, forever. `VRChatOSCManager`
classifies each datagram by source address and reports only the direct ones
here (see `seconds_since_direct_packet`).

Stdlib only. A missing router is a silent no-op — this is the fallback, it
must never become a failure mode of its own.
"""
from __future__ import annotations

import socket
import struct
import threading
import time
from typing import Callable, NamedTuple, Optional

# --- Well-known constants from the standard ---
# The port moved from 51518 to 18518 on 2026-08-08: 51518 sits inside Windows'
# dynamic range (49152+), where Hyper-V/WSL reserve random blocks at every boot, and
# a block landing on it stopped the hub from starting at all. Must stay below 49152.
ROUTER_HOST = "127.0.0.1"
ROUTER_PORT = 18518
ROUTER = (ROUTER_HOST, ROUTER_PORT)

#: Keep-alive cadence. Spec: send at least every 30 s; subscriptions expire
#: after 90 s of silence.
KEEPALIVE_S = 20.0
#: How often the ladder re-evaluates. Well under FIRST_CONTACT_S so the
#: escalation lands close to the spec'd deadline rather than a tick late.
TICK_S = 2.0
#: Spec: "no OSC has arrived from VRChat within 10 seconds of advertising".
FIRST_CONTACT_S = 10.0
#: Spec: "an established stream goes silent for 30 s while gameplay is
#: clearly running". Longer than first contact because a working stream
#: legitimately pauses (menus, loading screens) and re-subscribing on every
#: lull would churn the router for nothing.
STREAM_SILENT_S = 30.0
#: A router that hasn't acked in this long is treated as absent in the UI.
#: Purely cosmetic — subscription attempts continue regardless.
ROUTER_PRESENT_S = 90.0

TIER_DIRECT = "direct"   # Tier 0
TIER_ROUTER = "router"   # Tier 1


class OscFlowState(NamedTuple):
    """What the fallback needs to know about our OSC reception, supplied by
    the caller each tick so this module stays decoupled from the OSC stack.

    port:           our UDP receive port, or None/0 while unbound.
    advertising:    our OSCQuery service is published and VRChat is known to
                    be running (nothing to fall back to otherwise).
    ever_direct:    a packet has arrived straight from VRChat this session,
                    which selects the 30 s (vs 10 s) starvation deadline.
    since_direct_s: seconds since the last direct packet, or since we started
                    advertising if none has ever arrived. None = unknown.
    """
    port: Optional[int]
    advertising: bool
    ever_direct: bool
    since_direct_s: Optional[float]


def _pad(raw: bytes) -> bytes:
    raw += b"\x00"
    return raw + b"\x00" * (-len(raw) % 4)


def _control(address: str, port: int, name: str = "") -> bytes:
    """
    /router518/* control message: OSC address, the port, and optionally this program's
    name so the router's control panel can list who is connected by name rather than
    guessing from the port's owning process (from source we're all just "python").
    """
    if name:
        return (_pad(address.encode("ascii")) + _pad(b",is")
                + struct.pack(">i", port) + _pad(name.encode("ascii", "replace")))
    return _pad(address.encode("ascii")) + _pad(b",i") + struct.pack(">i", port)


def starvation_deadline(ever_direct: bool) -> float:
    """The spec'd silence a direct stream may have before we fall back."""
    return STREAM_SILENT_S if ever_direct else FIRST_CONTACT_S


def is_starved(state: Optional[OscFlowState]) -> bool:
    """Pure predicate: has the DIRECT VRChat stream been silent long enough
    to justify Tier 1? Split out from the loop so the rule the standard
    states in prose is testable on its own."""
    if state is None or not state.advertising or not state.port:
        return False
    if state.since_direct_s is None:
        return False
    return state.since_direct_s >= starvation_deadline(state.ever_direct)


class Router518Fallback:
    """Runs the Tier 0 → Tier 1 ladder on a background thread.

    ``state_getter`` is called every tick (never cached): the OSC manager is
    replaced wholesale on reconnect and its port only exists after the
    deferred bind, so anything captured once would go stale.
    """

    def __init__(self, state_getter: Callable[[], Optional[OscFlowState]],
                 name: str = "OscGoesPurrr",
                 log: Optional[Callable[[str], None]] = None) -> None:
        self._state_getter = state_getter
        self._name = name
        self._log_fn = log
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._sock: Optional[socket.socket] = None
        # Ladder state. Plain attribute reads/writes — get_state() is called
        # from the GUI thread and only ever reads, which the GIL makes safe.
        self._tier = TIER_DIRECT
        self._sub_port = 0
        self._last_keepalive = 0.0
        self._router_ack_at: Optional[float] = None
        self._reason = "starting up"

    # ------------------------------------------------------------------ API

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._sock.setblocking(False)
        self._thread = threading.Thread(
            target=self._run, name="Router518-Fallback", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        sock, self._sock = self._sock, None
        if sock is not None:
            try:
                if self._tier == TIER_ROUTER and self._sub_port:
                    sock.sendto(_control("/router518/unsubscribe", self._sub_port), ROUTER)
            except OSError:
                pass
            try:
                sock.close()
            except OSError:
                pass
        self._tier = TIER_DIRECT
        self._sub_port = 0
        self._reason = "stopped"

    def get_state(self) -> dict:
        """Snapshot for the diagnostics view. Cheap attribute reads only."""
        ack = self._router_ack_at
        ack_age = (time.monotonic() - ack) if ack is not None else None
        return {
            "tier": self._tier,
            "using_router": self._tier == TIER_ROUTER,
            "subscribed_port": self._sub_port or None,
            "router_present": ack_age is not None and ack_age <= ROUTER_PRESENT_S,
            "router_ack_age_s": ack_age,
            "reason": self._reason,
        }

    # -------------------------------------------------------------- internals

    def _log(self, message: str) -> None:
        if self._log_fn is None:
            print(f"[518] {message}")
            return
        try:
            self._log_fn(f"[518] {message}")
        except Exception:
            pass

    def _send(self, address: str, port: int, name: str = "") -> None:
        sock = self._sock
        if sock is None:
            return
        try:
            sock.sendto(_control(address, port, name), ROUTER)
        except OSError:
            pass  # no router running: stay quiet, try again next tick

    def _drain_acks(self) -> None:
        """Consume /router518/ok replies so the socket buffer can't fill, and
        note that a router is alive. On Windows an ICMP port-unreachable from
        a dead router also surfaces here (ConnectionResetError, an OSError)."""
        sock = self._sock
        if sock is None:
            return
        try:
            while True:
                data = sock.recv(2048)
                if data.startswith(b"/router518/ok"):
                    self._router_ack_at = time.monotonic()
        except OSError:
            pass

    def _enter_router(self, port: int, state: OscFlowState) -> None:
        if self._tier == TIER_ROUTER and self._sub_port and self._sub_port != port:
            self._send("/router518/unsubscribe", self._sub_port)
        silence = state.since_direct_s or 0.0
        self._reason = (
            f"no direct OSC for {silence:.0f}s "
            f"(limit {starvation_deadline(state.ever_direct):.0f}s)"
        )
        if self._tier != TIER_ROUTER or self._sub_port != port:
            self._log(
                f"VRChat has not reached us directly for {silence:.0f}s — "
                f"falling back to OSC Router 518 on port {port} (Tier 1)"
            )
        self._tier = TIER_ROUTER
        self._sub_port = port
        self._send("/router518/subscribe", port, self._name)
        self._last_keepalive = time.monotonic()

    def _leave_router(self, reason: str) -> None:
        if self._tier == TIER_ROUTER:
            if self._sub_port:
                self._send("/router518/unsubscribe", self._sub_port)
            self._log(f"back on Tier 0 (direct from VRChat) — {reason}")
        self._tier = TIER_DIRECT
        self._sub_port = 0
        self._reason = reason

    def _tick(self) -> None:
        self._drain_acks()
        state = self._state_getter()
        if state is None or not state.advertising or not state.port:
            self._leave_router("OSC server is not advertising")
            return
        if is_starved(state):
            port = int(state.port)
            if self._tier != TIER_ROUTER or self._sub_port != port:
                self._enter_router(port, state)
            elif (time.monotonic() - self._last_keepalive) >= KEEPALIVE_S:
                self._send("/router518/subscribe", port, self._name)
                self._last_keepalive = time.monotonic()
        elif self._tier == TIER_ROUTER:
            if state.ever_direct:
                self._leave_router("VRChat is pushing to us directly again")
            else:
                # Not starved, yet no direct packet has EVER arrived: the
                # silent-connection self-heal re-published mDNS and reset the
                # first-contact anchor (`seconds_since_direct_packet` measures
                # the advertisement age until a real direct packet exists).
                # Leaving now would cut the only stream we have for the length
                # of the fresh 10 s window — stay subscribed and keep the
                # subscription warm until VRChat actually reaches us.
                self._reason = ("subscribed; advertisement re-published, "
                                "still no direct packet from VRChat")
                if (time.monotonic() - self._last_keepalive) >= KEEPALIVE_S:
                    self._send("/router518/subscribe", self._sub_port, self._name)
                    self._last_keepalive = time.monotonic()
        else:
            self._reason = "VRChat is pushing to us directly"

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                self._tick()
            except Exception as e:  # never let the fallback take the app down
                print(f"[518] tick error: {type(e).__name__}: {e}")
            if self._stop.wait(TICK_S):
                return
