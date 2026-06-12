# pishock_serial.py
# PiShock USB-serial transport (the low-latency, local, no-account path).
#
# Wire format (PiShock V3 firmware, 115200 8n1, newline-terminated JSON):
#   {"cmd":"operate","value":{"id":<id>,"op":"shock|vibrate|beep|end",
#                             "duration":<ms>,"intensity":<0-100>}}
# There is no reply, so sends are pure fire-and-forget — exactly what the
# latency budget wants. The shocker `id` is shown on pishock.com / in the
# device's TERMINALINFO block.

import json
import threading
from typing import Callable, Optional

from pishock_connection import MODE_SERIAL

try:
    import serial  # pyserial
    _SERIAL_AVAILABLE = True
except Exception:
    serial = None  # type: ignore
    _SERIAL_AVAILABLE = False

BAUD = 115200


class PiShockSerialConnection:
    """Talks to a USB-attached PiShock. Holds the open port; writes one JSON
    line per operation. All clamping/safety is done upstream in PiShockEngine —
    this layer only marshals bytes."""

    mode = MODE_SERIAL

    def __init__(self, log: Optional[Callable[[str], None]] = None):
        self._log = log or (lambda _m: None)
        self._port_name: str = ""
        self._shocker_id: int = 0
        self._ser = None
        self._lock = threading.Lock()

    @property
    def status_label(self) -> str:
        return "PiShock (USB serial)"

    @property
    def is_available(self) -> bool:
        return _SERIAL_AVAILABLE

    def configure(self, config: dict) -> None:
        port = str((config or {}).get("serial_port", "") or "").strip()
        try:
            shocker_id = int((config or {}).get("shocker_id", 0))
        except (TypeError, ValueError):
            shocker_id = 0
        # Re-open on next prepare() if the port changed.
        if port != self._port_name:
            self._close()
        self._port_name = port
        self._shocker_id = shocker_id

    def prepare(self) -> bool:
        if not _SERIAL_AVAILABLE:
            self._log("PiShock serial: pyserial not installed")
            return False
        if not self._port_name:
            self._log("PiShock serial: no COM port configured")
            return False
        with self._lock:
            if self._ser is not None and getattr(self._ser, "is_open", False):
                return True
            try:
                self._ser = serial.Serial(self._port_name, BAUD, timeout=0)
                return True
            except Exception as e:
                self._ser = None
                self._log(f"PiShock serial: open {self._port_name} failed: {e}")
                return False

    def operate(self, op: str, intensity: int, duration_ms: int) -> None:
        self._write({
            "id": self._shocker_id,
            "op": op,
            "duration": int(duration_ms),
            "intensity": int(intensity),
        })

    def end(self) -> None:
        self._write({"id": self._shocker_id, "op": "end"})

    def _write(self, value: dict) -> None:
        line = json.dumps({"cmd": "operate", "value": value}) + "\n"
        with self._lock:
            ser = self._ser
            if ser is None:
                return
            try:
                ser.write(line.encode("utf-8"))
            except Exception as e:
                self._log(f"PiShock serial write failed: {e}")
                self._close_locked()

    def shutdown(self) -> None:
        self._close()

    def _close(self) -> None:
        with self._lock:
            self._close_locked()

    def _close_locked(self) -> None:
        ser = self._ser
        self._ser = None
        if ser is not None:
            try:
                ser.close()
            except Exception:
                pass
