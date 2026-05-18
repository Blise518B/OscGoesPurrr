# bhaptics_engine.py
# Sealed black box that owns the WebSocket connection to the bHaptics Player.
# Outside callers go through facade methods only.
#
# Protocol: ws://<host>:15881/v2/feedbacks  (bHaptics Player v2 endpoint)
# Submit format (dot mode):
#   {"Submit": [{"Type": "frame", "Key": "<unique>", "Frame": {
#       "position": "<VestFront|VestBack|Head|ForearmL|ForearmR|HandL|HandR|FootL|FootR>",
#       "dotPoints": [{"index": 0, "intensity": 0..100}, ...],
#       "durationMillis": <int>
#   }}]}
#
# Schema reference: v1.0.0 of HerpDerpinstine/bHapticsOSC (GPL3).

import json
import threading
import time
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional

try:
    import websocket  # websocket-client
    _WEBSOCKET_AVAILABLE = True
except Exception:
    websocket = None  # type: ignore
    _WEBSOCKET_AVAILABLE = False


# bHaptics device positions (v2 Player SDK names). These match the v1 schema's
# device categories one-for-one.
POSITIONS: List[str] = [
    "Head",
    "VestFront", "VestBack",
    "ForearmL", "ForearmR",
    "HandL", "HandR",
    "FootL", "FootR",
]

NODE_COUNTS: Dict[str, int] = {
    "Head": 6,
    "VestFront": 20, "VestBack": 20,
    "ForearmL": 6, "ForearmR": 6,
    "HandL": 3, "HandR": 3,
    "FootL": 3, "FootR": 3,
}


@dataclass
class DeviceConfig:
    enabled: bool = True
    intensity: int = 100   # 0..100, applied to active nodes

    def to_dict(self) -> dict:
        return {"enabled": bool(self.enabled), "intensity": int(self.intensity)}

    @classmethod
    def from_dict(cls, d: dict) -> "DeviceConfig":
        return cls(
            enabled=bool(d.get("enabled", True)),
            intensity=int(d.get("intensity", 100)),
        )


class BHapticsEngine:
    """Sealed bHaptics Player WebSocket client. Threadsafe facade."""

    DEFAULT_PORT = 15881
    DEFAULT_PATH = "/v2/feedbacks"
    DURATION_MS = 100  # each submitted frame lasts this long on the device

    def __init__(self, host: str = "127.0.0.1", port: int = DEFAULT_PORT):
        self.host = host
        self.port = port
        self._ws: Optional["websocket.WebSocket"] = None
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._connect_thread: Optional[threading.Thread] = None
        self._connected = False
        self._last_error: Optional[str] = None
        self._auto_connect_getter: Callable[[], bool] = lambda: False

    # ---- Properties / status -----------------------------------------

    @property
    def is_available(self) -> bool:
        return _WEBSOCKET_AVAILABLE

    @property
    def is_connected(self) -> bool:
        return self._connected

    @property
    def last_error(self) -> Optional[str]:
        return self._last_error

    @property
    def url(self) -> str:
        return f"ws://{self.host}:{self.port}{self.DEFAULT_PATH}"

    def set_endpoint(self, host: str, port: int) -> None:
        self.host = host
        self.port = int(port)
        # Force reconnect with new endpoint next loop iteration.
        self._close_ws()

    def set_auto_connect_getter(self, fn: Callable[[], bool]) -> None:
        self._auto_connect_getter = fn

    # ---- Connection lifecycle ----------------------------------------

    def start(self) -> None:
        if self._connect_thread is not None and self._connect_thread.is_alive():
            return
        self._stop.clear()
        self._connect_thread = threading.Thread(
            target=self._reconnect_loop, daemon=True, name="bHapticsReconnect")
        self._connect_thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._close_ws()

    def _reconnect_loop(self) -> None:
        backoff = 1.0
        while not self._stop.is_set():
            if not _WEBSOCKET_AVAILABLE:
                time.sleep(5.0)
                continue
            if not self._auto_connect_getter():
                # Auto-connect disabled — sit idle, don't open sockets.
                if self._connected:
                    self._close_ws()
                time.sleep(1.0)
                continue
            if self._connected:
                time.sleep(1.0)
                continue
            try:
                ws = websocket.create_connection(self.url, timeout=2.0)
                ws.settimeout(2.0)
                with self._lock:
                    self._ws = ws
                    self._connected = True
                    self._last_error = None
                print(f"[bHaptics] Connected to {self.url}")
                backoff = 1.0
            except Exception as e:
                self._last_error = str(e)
                self._connected = False
                # Cap backoff at 10s so reconnect picks up the Player launching.
                time.sleep(backoff)
                backoff = min(backoff * 1.5, 10.0)

    def _close_ws(self) -> None:
        with self._lock:
            ws = self._ws
            self._ws = None
            self._connected = False
        if ws is not None:
            try:
                ws.close()
            except Exception:
                pass

    def manual_connect(self) -> bool:
        """One-shot blocking attempt — used by the UI 'Connect' button."""
        if not _WEBSOCKET_AVAILABLE:
            self._last_error = "websocket-client not installed"
            return False
        if self._connected:
            return True
        try:
            ws = websocket.create_connection(self.url, timeout=2.0)
            ws.settimeout(2.0)
            with self._lock:
                self._ws = ws
                self._connected = True
                self._last_error = None
            print(f"[bHaptics] Connected to {self.url}")
            return True
        except Exception as e:
            self._last_error = str(e)
            self._connected = False
            return False

    # ---- Submission --------------------------------------------------

    def submit_dot_frame(self, position: str, dot_intensities: List[int]) -> None:
        """Send a single dot-mode frame for one device.

        dot_intensities length should match NODE_COUNTS[position]. Values
        clamp to 0..100. No-op when not connected or the position is unknown.
        """
        if not self._connected:
            return
        if position not in NODE_COUNTS:
            return
        # Filter out zero-intensity points; bHaptics doesn't need them and it
        # keeps the payload small.
        dots = []
        for i, v in enumerate(dot_intensities):
            iv = max(0, min(100, int(v)))
            if iv > 0:
                dots.append({"index": i, "intensity": iv})

        payload = {
            "Submit": [{
                "Type": "frame",
                "Key": f"oscgoespurrr_{position}",
                "Frame": {
                    "position": position,
                    "dotPoints": dots,
                    "durationMillis": self.DURATION_MS,
                },
            }]
        }
        body = json.dumps(payload)
        with self._lock:
            ws = self._ws
            if ws is None:
                return
            try:
                ws.send(body)
            except Exception as e:
                self._last_error = f"send failed: {e}"
                self._connected = False
                try:
                    ws.close()
                except Exception:
                    pass
                self._ws = None
