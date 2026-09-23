"""Websocket transport for one virtual Lovense toy.

Wraps a :class:`~testbench.lovense_protocol.LovenseProtocol` in a background
thread that speaks Intiface Central's Device Websocket Server (WSDM). This is
the same connection path a DIY ESP32 toy would use:

  1. Open a client websocket to Intiface's WSDM (default ``ws://127.0.0.1:54817``).
  2. Send the TEXT handshake frame (JSON identifier/address/version).
  3. Loop on BINARY frames — Intiface writes ``DeviceType;``, ``Battery;``,
     ``Vibrate:N;`` etc.; we decode them and send any required reply as a
     BINARY frame straight back.

I/O lives here; all wire *meaning* lives in `lovense_protocol`. Mirrors the
`create_connection` + daemon-thread style of the app's `bhaptics_engine.py`
and the callback API of `testbench/sim_network.py`, so the UI layer can
subscribe without knowing anything about websockets.
"""

from __future__ import annotations

import threading
import time
from typing import Callable, List, Optional, Tuple

from .lovense_protocol import LovenseProtocol

try:
    import websocket  # websocket-client
    _WEBSOCKET_AVAILABLE = True
except Exception:  # pragma: no cover - import guard mirrors bhaptics_engine
    websocket = None  # type: ignore
    _WEBSOCKET_AVAILABLE = False


# WSDM listens here by default (127.0.0.1:54817). The path is ignored by the
# server, so the bare host:port is enough.
DEFAULT_WSDM_URL = "ws://127.0.0.1:54817"


class LovenseToy:
    """A single virtual toy that connects to Intiface's WSDM in its own thread.

    Lifecycle mirrors the other engines::

        toy = LovenseToy(proto, on_levels=..., on_log=..., on_state=...)
        toy.start()        # spawns the daemon connect/serve loop
        toy.set_battery(55)
        ...
        toy.stop()

    Callbacks fire from the worker thread; a Qt UI must marshal them onto the
    GUI thread itself (see the bench's signal bridge in testbench/app.py).
    """

    def __init__(
        self,
        proto: LovenseProtocol,
        url: str = DEFAULT_WSDM_URL,
        on_levels: Optional[Callable[[List[Tuple[int, float]]], None]] = None,
        on_log: Optional[Callable[[str], None]] = None,
        on_state: Optional[Callable[[bool, Optional[str]], None]] = None,
    ) -> None:
        self.proto = proto
        self.url = url
        self._on_levels = on_levels or (lambda _u: None)
        self._on_log = on_log or (lambda _m: None)
        self._on_state = on_state or (lambda _c, _e: None)

        self._lock = threading.Lock()
        self._ws: Optional["websocket.WebSocket"] = None
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._connected = False
        self._last_error: Optional[str] = None

    # ---------------------------------------------------------- properties
    @property
    def is_available(self) -> bool:
        return _WEBSOCKET_AVAILABLE

    @property
    def is_connected(self) -> bool:
        return self._connected

    @property
    def last_error(self) -> Optional[str]:
        return self._last_error

    # ------------------------------------------------------------- battery
    def set_battery(self, pct: int) -> None:
        """Update the value reported on the next ``Battery;`` query."""
        self.proto.battery_pct = max(0, min(100, int(pct)))

    # ----------------------------------------------------------- lifecycle
    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run, daemon=True, name=f"ToySim-{self.proto.address[:4]}"
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._close_ws()

    # ------------------------------------------------------------- threads
    def _run(self) -> None:
        """Reconnect loop: keep a live WSDM connection until stopped."""
        if not _WEBSOCKET_AVAILABLE:
            self._last_error = "websocket-client not installed"
            self._on_state(False, self._last_error)
            return

        backoff = 1.0
        while not self._stop.is_set():
            session_start = time.monotonic()
            try:
                ws = websocket.create_connection(self.url, timeout=3.0)
                # Short recv timeout so the serve loop can poll the stop flag.
                ws.settimeout(1.0)
            except Exception as exc:
                self._last_error = f"{type(exc).__name__}: {exc}"
                self._connected = False
                self._on_state(False, self._last_error)
            else:
                with self._lock:
                    self._ws = ws
                    self._connected = True
                    self._last_error = None
                self._on_state(True, None)
                try:
                    self._serve_connection(ws)
                finally:
                    self._close_ws()
                    if not self._stop.is_set():
                        self._on_state(False, self._last_error)

            if self._stop.is_set():
                break
            # Reset the backoff only after a session that actually stayed up a
            # while. A refused connect — or one Intiface drops right after our
            # handshake because the identifier maps to no protocol — keeps the
            # backoff growing (to 10s) so we don't spin-hammer the server.
            if time.monotonic() - session_start >= 5.0:
                backoff = 1.0
            if self._stop.wait(backoff):
                break
            backoff = min(backoff * 1.5, 10.0)

        self._on_log("toy stopped")

    def _serve_connection(self, ws: "websocket.WebSocket") -> None:
        """Handshake, then pump inbound frames until the socket drops."""
        # First frame MUST be the TEXT handshake; WSDM drops us otherwise.
        ws.send(self.proto.handshake_text())
        self._on_log(f"handshake -> {self.url} as {self.proto.ws_identifier!r}")
        handshook_at = time.monotonic()
        got_command = False

        while not self._stop.is_set():
            try:
                frame = ws.recv()
            except websocket.WebSocketTimeoutException:
                continue  # idle tick — just re-check the stop flag
            except Exception as exc:
                self._last_error = f"{type(exc).__name__}: {exc}"
                return
            if frame is None or frame == "" or frame == b"":
                # Empty payload means the server closed the connection. If it
                # did so promptly without ever issuing a command, Intiface has
                # no device protocol mapped to our identifier — the usual cause.
                if not got_command and (time.monotonic() - handshook_at) < 3.0:
                    self._last_error = (
                        "Intiface closed the connection right after the "
                        f"handshake — identifier {self.proto.ws_identifier!r} is "
                        "not mapped to any device protocol in Intiface."
                    )
                else:
                    self._last_error = "connection closed by Intiface"
                return

            got_command = True
            raw = frame.encode("utf-8") if isinstance(frame, str) else frame
            updates, response, logs = self.proto.process_command(raw)
            for line in logs:
                self._on_log(f"<- {line}")
            if updates:
                self._on_levels(updates)
            if response is not None:
                try:
                    ws.send_binary(response)
                    self._on_log(f"-> {response.decode('ascii', 'replace')}")
                except Exception as exc:
                    self._last_error = f"{type(exc).__name__}: {exc}"
                    return

    def _close_ws(self) -> None:
        with self._lock:
            ws = self._ws
            self._ws = None
            was_connected = self._connected
            self._connected = False
        if ws is not None:
            try:
                ws.close()
            except Exception:
                pass
        if was_connected:
            # Reset decoded levels so the UI doesn't show a frozen bar after a
            # drop; the next connection re-queries DeviceType anyway.
            self.proto.levels = [0.0] * len(self.proto.model.features)
