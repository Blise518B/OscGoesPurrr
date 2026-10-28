"""One Friends connection's wire behaviour: what goes out when -- changes
only, REPEATS more copies, the status every STATE_REFRESH_S, a cmd that
drives something every SEND_S -- how it is kept alive, and why it ended.
RemoteLink (remote_link.py) owns the sessions; test_link_light.py pins
what is here.
"""

import ipaddress
import time
from typing import Any, Dict, Optional

import remote_protocol as proto

SEND_S = 0.25        # how often a link looks for something to send
PING_S = 5.0         # keepalive + round trip, only when nothing else went out
HELLO_S = 60.0       # who we are, again (and 3x right after linking)
DEAD_S = 16.0        # three pings unanswered: the link is gone
STATE_REFRESH_S = 10.0
REPEATS = 2          # a change goes out 1 + REPEATS times
CMD_HZ = 60          # live changes, per friend


def path_kind(conn) -> str:
    """How a connection runs: "relay", "direct", "direct (same network)" or
    "connecting" -- never the address itself."""
    try:
        paths = conn.paths()
    except Exception:
        return ""
    for p in paths:
        if not p.is_selected:
            continue
        if p.is_relay:
            return "relay"
        host = p.remote_addr.rsplit(":", 1)[0].strip("[]")
        try:
            ip = ipaddress.ip_address(host)
        except ValueError:
            return "direct"
        return "direct" if ip.is_global else "direct (same network)"
    return "connecting"


def drives(slot: str, msg: Dict[str, Any]) -> bool:
    """A slot that goes out every SEND_S: its receiver lets go of what it
    says once it stops (a toy level, a held button)."""
    if slot == "cmd":
        return proto.drives(msg)
    return slot == "ph" and bool(msg.get("h"))


def refreshes(slot: str, msg: Dict[str, Any]) -> bool:
    """A slot repeated every STATE_REFRESH_S though unchanged: the status,
    who else drives and the shared panel, a panel or board being watched
    and its values."""
    return (slot in ("st", "pnl") or (slot == "oth" and bool(msg.get("n")))
            or slot.startswith("pv") or (slot == "pw" and not msg.get("off"))
            or (slot == "lw" and bool(msg.get("on"))))


def reason_word(reason: str) -> str:
    for word in ("bye", "timeout", "duplicate", "unanswered", "refused", "removed", "busy"):
        if word in reason:
            return word
    return "lost"


class Session:
    def __init__(self, conn, peer: str, dialer: str):
        self.conn, self.peer, self.dialer = conn, peer, dialer
        self.live = False
        self.waiting = False
        self.last_rx = self.last_tx = time.monotonic()
        self.sent: Dict[str, list] = {}   # a slot -> [bytes, when, repeats left]
        self.hellos = 3                   # right after linking, then every HELLO_S
        self.early_hellos = 3             # while not live yet, every SEND_S
        self.rtt: Optional[float] = None
        self.closed = False
        self.err = ""                     # what the read loop died of
        self.reason = ""                  # why WE closed it, when we did
        self.send_error = ""              # the first send that failed
        self.last_cmd = 0.0
        self.cmd_handle = None
        # for the debug log (RemoteLink): how this link has been doing
        self.linked_at = time.monotonic()
        self.rx_n = self.tx_n = 0         # datagrams in / out
        self.path = ""                    # path_kind, as last seen
        self.reported = time.monotonic()  # the last quality line

    def send(self, msg: Dict[str, Any]) -> None:
        self.send_raw(proto.encode(msg))

    def send_raw(self, data: bytes) -> None:
        self.last_tx = time.monotonic()
        self.tx_n += 1
        try:
            self.conn.send_datagram(data)
        except Exception as e:
            if not self.send_error:       # the link logs the first one
                try:
                    room = self.conn.max_datagram_size()
                except Exception:
                    room = None
                self.send_error = (f"{type(e).__name__}: {e} - {len(data)} bytes, "
                                   f"the path takes {room if room is not None else '?'}")

    def close(self, code: int, reason: bytes) -> None:
        if not self.closed:
            self.closed = True
            self.reason = reason.decode("utf-8", "replace")
            try:
                self.conn.close(code, reason)
            except Exception:
                pass

    def send_state(self, slot: str, msg: Dict[str, Any], now: float) -> None:
        """Only what changed, REPEATS more times, the status (and a board's
        watch and values) every STATE_REFRESH_S -- and a cmd that drives
        toys, or hold buttons held, every time."""
        data = proto.encode(msg)
        last = self.sent.get(slot)
        if last is None or last[0] != data:
            self.sent[slot] = [data, now, REPEATS]
        elif drives(slot, msg) or last[2] > 0:
            last[1] = now
            last[2] = max(0, last[2] - 1)
        elif refreshes(slot, msg) and now - last[1] >= STATE_REFRESH_S:
            last[1] = now
        else:
            return
        self.send_raw(data)

    def quality(self) -> str:
        """For the debug log: the path, its round trip, the datagrams that
        went through and what QUIC itself had to resend."""
        bits = [self.path or "no path yet"]
        try:
            rtt = self.conn.rtt()
        except Exception:
            rtt = None
        bits.append(f"round trip {rtt} ms" if rtt is not None else "round trip unknown")
        if self.rtt is not None:
            # OGP's own ping: the network plus both OGPs' time to answer
            bits.append(f"ping {self.rtt:.0f} ms")
        bits.append(f"{self.rx_n} datagrams in / {self.tx_n} out")
        try:
            st = self.conn.stats()
            bits.append(f"QUIC lost {st.lost_packets} of {st.udp_tx_datagrams} packets sent")
        except Exception:
            pass
        return ", ".join(bits)

    def ended_word(self) -> str:
        """Why it ended, in one word: our own reason when we closed it (the
        connection then only says it was closed locally), else theirs."""
        return reason_word(self.reason or f"{self.conn.close_reason() or ''} {self.err}")
