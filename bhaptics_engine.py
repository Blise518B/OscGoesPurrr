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
from typing import Callable, Dict, List, Optional, Set

from engine_base import ReconnectingEngine

try:
    import websocket  # websocket-client
    _WEBSOCKET_AVAILABLE = True
except Exception:
    websocket = None  # type: ignore
    _WEBSOCKET_AVAILABLE = False


NODE_COUNTS: Dict[str, int] = {
    "Head": 6,
    "VestFront": 20, "VestBack": 20,
    "ForearmL": 6, "ForearmR": 6,
    "HandL": 3, "HandR": 3,
    "FootL": 3, "FootR": 3,
}

# Position names the Player can report in status broadcasts but which are
# aliases of the canonical set above. Used by the status-receiver normaliser
# so old / sandbox builds of the Player don't trip the position filter.
_POSITION_ALIASES: Dict[str, str] = {
    "vest":       "VestFront",
    "vestfront":  "VestFront",
    "vestback":   "VestBack",
    "head":       "Head",
    "forearml":   "ForearmL",
    "forearmr":   "ForearmR",
    "handl":      "HandL",
    "handr":      "HandR",
    "footl":      "FootL",
    "footr":      "FootR",
}


def _canon_position(raw) -> Optional[str]:
    """Normalise a position string from a Player status broadcast into one of
    the canonical NODE_COUNTS keys, or None if it doesn't map cleanly."""
    if not isinstance(raw, str):
        return None
    lo = raw.replace("_", "").replace("-", "").lower()
    return _POSITION_ALIASES.get(lo)


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


class BHapticsEngine(ReconnectingEngine):
    """Sealed bHaptics Player WebSocket client. Threadsafe facade.

    Connection lifecycle (connected flag, last_error, auto-connect gate,
    state callback, start/stop, backoff reconnect loop, manual_connect) is
    inherited from ReconnectingEngine; this class supplies the WebSocket
    transport via `_open()` / `_close()` and keeps the hot `submit_dot_frame`
    send path plus the Player status-mirror receive thread."""

    DEFAULT_PORT = 15881
    DEFAULT_PATH = "/v2/feedbacks"
    DURATION_MS = 100  # each submitted frame lasts this long on the device

    def __init__(self, host: str = "127.0.0.1", port: int = DEFAULT_PORT):
        super().__init__("bHaptics")
        self.host = host
        self.port = port
        self._ws: Optional["websocket.WebSocket"] = None
        self._lock = threading.Lock()
        self._recv_thread: Optional[threading.Thread] = None

        # Status mirror — populated by the receive thread when the Player
        # broadcasts {"Status": {...}} (or similar) frames. Empty when the
        # Player doesn't broadcast status, in which case the facade falls
        # back to a single "bHaptics Suit" SteamVR entry.
        self._state_lock = threading.Lock()
        self._connected_positions: Set[str] = set()
        self._position_batteries: Dict[str, float] = {}

    # ---- Transport availability (ReconnectingEngine hooks) -----------

    @property
    def _available(self) -> bool:
        return _WEBSOCKET_AVAILABLE

    @property
    def _unavailable_reason(self) -> str:
        return "websocket-client not installed"

    # ---- Properties / status -----------------------------------------

    @property
    def url(self) -> str:
        return f"ws://{self.host}:{self.port}{self.DEFAULT_PATH}"

    def set_endpoint(self, host: str, port: int) -> None:
        self.host = host
        self.port = int(port)
        # Force reconnect with new endpoint next loop iteration.
        self._close()

    # ---- Connected-device status mirror (consumed by the SteamVR facade) ----

    def get_connected_positions(self) -> Set[str]:
        """Snapshot of the position names the Player has reported as
        connected. Empty set when the Player doesn't broadcast status —
        callers should treat that as 'unknown, fall back to one suit
        entry' rather than 'definitely nothing connected'."""
        with self._state_lock:
            return set(self._connected_positions)

    def get_position_battery(self, position: str) -> Optional[float]:
        """Per-position battery level (0..1) if the Player has reported one,
        else None. Most public Player builds don't broadcast battery, so
        None is the common case."""
        with self._state_lock:
            return self._position_batteries.get(position)

    # ---- Connection transport (ReconnectingEngine hooks) -------------

    def _open(self) -> None:
        """Open one WebSocket to the Player and start its status-receive
        thread. Sets `_connected` on success; raises on failure. The base
        reconnect loop / manual_connect own backoff, last_error, and the
        state-change notify."""
        ws = websocket.create_connection(self.url, timeout=2.0)
        ws.settimeout(2.0)
        with self._lock:
            self._ws = ws
            self._connected = True
        print(f"[bHaptics] Connected to {self.url}")
        # Fresh receive thread per connection: shutdown is implicit when the
        # ws closes (its own ws.recv() raises and the thread exits).
        self._start_recv_thread(ws)

    def _close(self) -> None:
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
        # Clear the status mirror so a fresh connection starts empty rather
        # than reporting stale device state from the previous session.
        with self._state_lock:
            changed = bool(self._connected_positions or self._position_batteries)
            self._connected_positions.clear()
            self._position_batteries.clear()
        if was_connected or changed:
            self._notify_state_change()

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

    # ---- Receive thread ----------------------------------------------
    # The Player broadcasts JSON status frames on the same WebSocket as the
    # feedback channel. Public Player builds vary wildly in what they
    # broadcast — some send {"Status": {...}}, some send {"Registered":
    # [...], "ActiveKeys": [...]}, some send nothing at all. We parse
    # defensively: anything that looks like a position list is consumed,
    # anything else is ignored. When the Player sends nothing, the
    # _connected_positions set stays empty and the facade falls back to a
    # single "bHaptics Suit" SteamVR entry.

    def _start_recv_thread(self, ws) -> None:
        # Per-connection thread so shutdown is implicit when ws closes.
        t = threading.Thread(
            target=self._recv_loop, args=(ws,),
            daemon=True, name="bHapticsRecv",
        )
        self._recv_thread = t
        t.start()

    def _recv_loop(self, ws) -> None:
        while not self._stop.is_set():
            with self._lock:
                # If the ws we were spawned with isn't the current one, this
                # connection has been replaced; exit so the new connection's
                # receiver can take over.
                if self._ws is not ws:
                    return
            try:
                msg = ws.recv()
            except Exception:
                # Timeout, close, or socket error — let the reconnect loop
                # observe the broken connection via the next send attempt.
                return
            if not msg:
                continue
            try:
                data = json.loads(msg)
            except (TypeError, ValueError):
                continue
            self._apply_status(data)

    def _apply_status(self, data) -> None:
        """Best-effort extraction of connected positions + per-position
        battery from a Player broadcast frame. Unknown shapes are ignored."""
        if not isinstance(data, dict):
            return

        positions: Optional[Set[str]] = None
        batteries: Dict[str, float] = {}

        # Shape 1: {"Status": {"connectedPositions": [...], ...}}
        status = data.get("Status")
        if isinstance(status, dict):
            cp = status.get("connectedPositions")
            if isinstance(cp, list):
                positions = set()
                for raw in cp:
                    c = _canon_position(raw)
                    if c is not None:
                        positions.add(c)
            # Battery — sometimes under Status.deviceList / Status.devices.
            for k in ("deviceList", "devices", "connectedDevices"):
                items = status.get(k)
                if isinstance(items, list):
                    self._extract_batteries(items, batteries)

        # Shape 2: flat top-level keys.
        if positions is None:
            cp = data.get("connectedPositions")
            if isinstance(cp, list):
                positions = set()
                for raw in cp:
                    c = _canon_position(raw)
                    if c is not None:
                        positions.add(c)
        for k in ("BatteryLevels", "Devices", "DeviceStatusList"):
            items = data.get(k)
            if isinstance(items, list):
                self._extract_batteries(items, batteries)

        if positions is None and not batteries:
            # Nothing we recognised in this frame.
            return

        with self._state_lock:
            changed = False
            if positions is not None and positions != self._connected_positions:
                self._connected_positions = positions
                changed = True
            for pos, lvl in batteries.items():
                prev = self._position_batteries.get(pos)
                if prev is None or abs(prev - lvl) >= 0.005:
                    self._position_batteries[pos] = lvl
                    changed = True
        if changed:
            self._notify_state_change()

    @staticmethod
    def _extract_batteries(items, out: Dict[str, float]) -> None:
        """Read [{"position": "VestFront", "battery": 0..100 or 0..1}, ...]
        entries into `out` keyed by canonical position name. Battery values
        from the Player are usually 0..100 integers, occasionally 0..1
        floats — we normalise both into the 0..1 form SteamVR expects."""
        for item in items:
            if not isinstance(item, dict):
                continue
            pos = _canon_position(item.get("position") or item.get("Position"))
            if pos is None:
                continue
            for key in ("battery", "Battery", "batteryLevel", "BatteryLevel"):
                if key in item:
                    try:
                        v = float(item[key])
                    except (TypeError, ValueError):
                        continue
                    if v > 1.0:
                        v = v / 100.0
                    out[pos] = max(0.0, min(1.0, v))
                    break

    def _notify_state_change(self) -> None:
        cb = self._state_callback
        if cb is None:
            return
        try:
            cb()
        except Exception:
            pass
