# owo_link.py
# The My OWO app's UDP protocol, spoken natively -- what OWO's own SDK
# (OWO.dll) does, without the DLL or pythonnet. The suit itself only ever
# talks to My OWO, which holds the user's per-muscle calibration and the
# Bluetooth link; this module is the game side of that conversation.
#
# Every byte here is pinned against real SDK output captured with
# tools/owo_udp_capture.py, and the handshake follows OWO's MIT-licensed C++
# SDK (OWODevelopers/OWO_GTAV, OWOAPI/Controller/FindServer):
#
#   game -> app   "ping"                      (unicast, or 255.255.255.255)
#   app  -> game  "okay"                      (the app is there)
#   game -> app   "<gameId>*AUTH*<baked>"     (anonymous: gameId "0", nothing baked)
#   app  -> game  "pong"                      (connected)
#   game -> app   "<gameId>*SENSATION*<f>,<dur/10 s>,<int>,<up ms>,<down ms>,<exit/10 s>,<name>|<muscle>%<int>,..."
#   game -> app   "<gameId>*STOP"
#   game -> app   "<gameId>*GAMEUNAVAILABLE"  (the game is leaving)
#   app  -> game  "OWO_Close"                 (the app is leaving)
#
# All on UDP 54020; the app answers to whatever port the game sent from.

import socket
from typing import Callable, Mapping, Optional, Sequence

PORT = 54020
BROADCAST = "255.255.255.255"
LOCALHOST = "127.0.0.1"

PING = b"ping"
PRESENCE = b"okay"
VERIFIED = b"pong"
APP_CLOSED = b"OWO_Close"

# The SDK's muscle indices.
MUSCLES = (
    "Pectoral_R", "Pectoral_L",
    "Abdominal_R", "Abdominal_L",
    "Arm_R", "Arm_L",
    "Dorsal_R", "Dorsal_L",
    "Lumbar_R", "Lumbar_L",
)
MUSCLE_INDEX = {name: i for i, name in enumerate(MUSCLES)}


def _clamp(value, lo, hi, default):
    try:
        v = float(value)
    except (TypeError, ValueError):
        return default
    if v != v:          # NaN
        return default
    return max(lo, min(hi, v))


def sensation_text(frequency, duration_s, intensity, ramp_up_ms=0, ramp_down_ms=0,
                   exit_delay_s=0, name: str = "") -> str:
    """One micro-sensation, clamped the way the SDK clamps it: frequency
    1..100 Hz, duration 0.1..20 s (sent in tenths), intensity 0..100 %,
    ramps 0..2000 ms, exit delay 0..2 s (in tenths)."""
    f = int(_clamp(frequency, 1, 100, 1))
    dur = int(_clamp(duration_s, 0.1, 20.0, 0.1) * 10 + 1e-6)
    i = int(_clamp(intensity, 0, 100, 0))
    up = int(_clamp(ramp_up_ms, 0, 2000, 0))
    down = int(_clamp(ramp_down_ms, 0, 2000, 0))
    exit_t = int(_clamp(exit_delay_s, 0.0, 2.0, 0.0) * 10 + 1e-6)
    clean = "".join(ch for ch in str(name or "") if ch not in ",|&*%#~")
    return f"{f},{dur},{i},{up},{down},{exit_t},{clean}"


def muscles_text(muscles: Mapping) -> str:
    """{muscle name or index: percent} -> '5%100,0%60'. Unknown names are
    dropped; percent is clamped to 0..100."""
    parts = []
    for key, pct in muscles.items():
        idx = MUSCLE_INDEX.get(key, key) if isinstance(key, str) else key
        if not isinstance(idx, int) or not 0 <= idx < len(MUSCLES):
            continue
        parts.append(f"{idx}%{int(_clamp(pct, 0, 100, 0))}")
    return ",".join(parts)


def build_auth(game_id: str = "0", baked: Sequence[str] = ()) -> bytes:
    return f"{game_id or '0'}*AUTH*{'#'.join(baked)}".encode("ascii", "replace")


def build_sensation(game_id: str, micro: str, muscles: Mapping) -> bytes:
    body = micro
    group = muscles_text(muscles)
    if group:
        body = f"{micro}|{group}"
    return f"{game_id or '0'}*SENSATION*{body}".encode("ascii", "replace")


def build_stop(game_id: str = "0") -> bytes:
    return f"{game_id or '0'}*STOP".encode("ascii", "replace")


def build_unavailable(game_id: str = "0") -> bytes:
    return f"{game_id or '0'}*GAMEUNAVAILABLE".encode("ascii", "replace")


def _default_socket():
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    sock.bind(("0.0.0.0", 0))
    return sock


class OwoLink:
    """One UDP socket to the My OWO app: find it, then fire and forget."""

    def __init__(self, socket_factory: Optional[Callable[[], object]] = None):
        self._sock = (socket_factory or _default_socket)()
        self.host: Optional[str] = None

    def _recv(self, timeout_s: float):
        try:
            self._sock.settimeout(timeout_s)
            return self._sock.recvfrom(2048)
        except (socket.timeout, BlockingIOError):
            return None, None
        except OSError:
            # Windows reports an ICMP "port unreachable" from an earlier
            # send here; it only means nothing is listening (yet).
            return None, None

    def _send_to(self, data: bytes, host: str) -> bool:
        try:
            self._sock.sendto(data, (host, PORT))
            return True
        except OSError:
            return False

    def connect(self, candidates: Sequence[str], game_id: str = "0",
                timeout_s: float = 1.0) -> Optional[str]:
        """Ping each candidate (an IP, or BROADCAST); the first app that
        answers "okay" gets the AUTH, and its "pong" makes it ours. Returns
        the app's address, or None."""
        for candidate in candidates:
            if not candidate:
                continue
            if not self._send_to(PING, candidate):
                continue
            data, addr = self._recv(timeout_s)
            if data != PRESENCE or addr is None:
                continue
            host = addr[0]
            self._send_to(build_auth(game_id), host)
            for _ in range(3):
                data, addr = self._recv(timeout_s)
                if data == VERIFIED:
                    self.host = host
                    return host
                if data is None:
                    break
        return None

    def send(self, data: bytes) -> bool:
        if self.host is None:
            return False
        return self._send_to(data, self.host)

    def poll(self, timeout_s: float = 0.0) -> Optional[bytes]:
        """One message from the app, if any arrived (e.g. OWO_Close)."""
        data, _addr = self._recv(timeout_s)
        return data

    def close(self) -> None:
        try:
            self._sock.close()
        except OSError:
            pass
