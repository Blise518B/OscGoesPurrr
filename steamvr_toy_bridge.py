# steamvr_toy_bridge.py
# Talks to the OscGoesPurrr SteamVR toy driver over a localhost TCP socket.
# The driver listens on 127.0.0.1:24855 once vrserver loads it; we open a
# client socket from the Python side, push the current toy list whenever it
# changes, and reconnect transparently if SteamVR (and therefore the driver)
# restarts.
#
# Wire format: newline-delimited JSON. See steamvr_toy_driver/README.md for
# the schema. Sealed box: no caller touches `self._sock` — they go through
# `set_devices()` / `update_battery()` / `start()` / `stop()`.

from __future__ import annotations

import json
import socket
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional


DRIVER_HOST = "127.0.0.1"
DRIVER_PORT = 24855


@dataclass
class ToyEntry:
    """Primitives-only view of a connected toy, ready for IPC."""
    serial: str
    name: str
    icon_path: str = ""
    # icon_key is the bare lookup name (e.g. "edge_2") that the C++ driver
    # sets as Prop_ModelNumber_String. SteamVR uses ModelNumber to pick
    # which entry of the statusicons map to render — without this we'd
    # fall back to the generic GenericTracker silhouette.
    icon_key: str = ""
    battery: float = 1.0  # 0..1, 1.0 == unknown / full

    def to_dict(self) -> Dict[str, object]:
        d: Dict[str, object] = {
            "serial": self.serial,
            "name": self.name,
            "battery": float(max(0.0, min(1.0, self.battery))),
        }
        if self.icon_key:
            d["icon_key"] = self.icon_key
        if self.icon_path:
            # Path comes in one of two forms:
            #   * SteamVR substitution syntax — "{oscgoespurrr}/icons/foo.png"
            #     (preferred; lets SteamVR's strip renderer find the asset)
            #   * Absolute filesystem path (fallback for tests / non-Windows)
            # Either way, normalise backslashes to forward slashes so the
            # driver-side JSON parser doesn't have to deal with escape
            # nuances. The braces and substitution token survive that.
            d["icon"] = str(self.icon_path).replace("\\", "/")
        return d


class SteamVRToyBridge:
    """Sealed client that mirrors the controller's view of connected toys
    into the SteamVR driver process.

    Threadsafe: every public method may be called from any thread. The
    bridge owns one background sender thread that handles connect-loop +
    flush-on-change.
    """

    RECONNECT_BACKOFF_S = 2.0
    HEARTBEAT_S = 30.0  # forces a periodic resend so a freshly-restarted
                       # SteamVR picks up the device list within ~30s
                       # even if no toy events have happened.

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._sock: Optional[socket.socket] = None
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None

        # The "shadow state" the controller pushes into us. The sender
        # thread mirrors this to the driver whenever the version counter
        # advances.
        self._devices: Dict[str, ToyEntry] = {}
        self._version = 0                 # bumped on every state change
        self._last_sent_version = -1      # last version successfully shipped
        self._wake = threading.Event()

        # Optional sink for status messages (set by the controller; defaults
        # to no-op so unit tests don't need a logger).
        self._log = lambda msg: None

    # ---- Lifecycle ---------------------------------------------------

    def set_logger(self, fn) -> None:
        if callable(fn):
            self._log = fn

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._wake.clear()
        self._thread = threading.Thread(
            target=self._sender_loop, name="SteamVRToyBridge", daemon=True
        )
        self._thread.start()
        self._log("[steamvr-toys] bridge started")

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()
        with self._lock:
            sock = self._sock
            self._sock = None
        if sock is not None:
            try:
                sock.close()
            except Exception:
                pass
        if self._thread is not None:
            self._thread.join(timeout=2.0)
        self._thread = None
        self._log("[steamvr-toys] bridge stopped")

    @property
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    @property
    def is_connected(self) -> bool:
        with self._lock:
            return self._sock is not None

    # ---- State updates ------------------------------------------------
    # All of these bump the version counter and wake the sender thread.
    # No I/O happens on the caller's thread.

    def set_devices(self, entries: List[ToyEntry]) -> None:
        """Replace the full toy list. Driver-side wins the diff."""
        with self._lock:
            new_map = {e.serial: e for e in entries if e.serial}
            if self._entries_equal(self._devices, new_map):
                return
            self._devices = new_map
            self._version += 1
        self._wake.set()

    def update_battery(self, serial: str, battery: float) -> None:
        """Cheaper-than-full-resend path for battery-only changes."""
        if not serial:
            return
        try:
            battery = float(battery)
        except (TypeError, ValueError):
            return
        battery = max(0.0, min(1.0, battery))
        with self._lock:
            existing = self._devices.get(serial)
            if existing is None:
                return
            if abs(existing.battery - battery) < 0.005:
                return
            existing.battery = battery
            self._version += 1
        self._wake.set()

    def clear_devices(self) -> None:
        with self._lock:
            if not self._devices:
                return
            self._devices = {}
            self._version += 1
        self._wake.set()

    # ---- Internal ----------------------------------------------------

    @staticmethod
    def _entries_equal(a: Dict[str, ToyEntry], b: Dict[str, ToyEntry]) -> bool:
        if a.keys() != b.keys():
            return False
        for k, av in a.items():
            bv = b[k]
            if (av.name, av.icon_path, av.icon_key) != (bv.name, bv.icon_path, bv.icon_key):
                return False
            if abs(av.battery - bv.battery) >= 0.005:
                return False
        return True

    def _sender_loop(self) -> None:
        backoff = self.RECONNECT_BACKOFF_S
        last_heartbeat = 0.0
        while not self._stop.is_set():
            # Establish or re-establish the connection.
            if not self.is_connected:
                if not self._try_connect():
                    # Wait, but wake early if stop / new state arrives.
                    self._wake.wait(timeout=backoff)
                    self._wake.clear()
                    continue
                # On a fresh connect, send a hello and force a state push.
                self._send_line({"type": "hello", "version": 1})
                last_heartbeat = time.monotonic()
                with self._lock:
                    self._last_sent_version = -1  # force resend on reconnect

            # Decide whether to send.
            now = time.monotonic()
            need_send = False
            payload: Optional[Dict[str, object]] = None
            with self._lock:
                if self._version != self._last_sent_version:
                    need_send = True
                    payload = self._build_set_devices_payload()
                    self._last_sent_version = self._version

            if not need_send and (now - last_heartbeat) > self.HEARTBEAT_S:
                # Periodic resend so a SteamVR restart re-populates without
                # waiting for the next toy event.
                with self._lock:
                    payload = self._build_set_devices_payload()
                need_send = True

            if need_send and payload is not None:
                ok = self._send_line(payload)
                if not ok:
                    self._drop_connection()
                    continue
                last_heartbeat = now

            # Sleep until either a state update or the heartbeat fires.
            wait_s = max(0.1, min(1.0, self.HEARTBEAT_S - (time.monotonic() - last_heartbeat)))
            self._wake.wait(timeout=wait_s)
            self._wake.clear()

    def _build_set_devices_payload(self) -> Dict[str, object]:
        # Caller holds self._lock.
        devices = [e.to_dict() for e in self._devices.values()]
        return {"type": "set_devices", "devices": devices}

    def _try_connect(self) -> bool:
        try:
            s = socket.create_connection((DRIVER_HOST, DRIVER_PORT), timeout=1.0)
            s.settimeout(2.0)
            with self._lock:
                self._sock = s
            self._log("[steamvr-toys] connected to driver on "
                      f"{DRIVER_HOST}:{DRIVER_PORT}")
            return True
        except OSError:
            return False

    def _drop_connection(self) -> None:
        with self._lock:
            sock = self._sock
            self._sock = None
        if sock is not None:
            try:
                sock.close()
            except Exception:
                pass

    def _send_line(self, payload: Dict[str, object]) -> bool:
        try:
            body = json.dumps(payload, separators=(",", ":"), ensure_ascii=False)
        except (TypeError, ValueError):
            return True  # malformed payload — drop silently, don't kill connection
        with self._lock:
            sock = self._sock
        if sock is None:
            return False
        try:
            sock.sendall((body + "\n").encode("utf-8"))
            return True
        except OSError:
            return False
