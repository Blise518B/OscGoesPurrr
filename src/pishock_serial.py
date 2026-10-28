# pishock_serial.py
# The shocker hub over its USB cable: the local, no-account, low-latency
# path. The hub runs one of two firmwares and the link speaks both, picking
# whichever answers the handshake:
#
# PiShock's own (115200 8n1, newline-terminated JSON; see docs.pishock.com
# "Serial API Documentation"):
#   {"cmd":"operate","value":{"id":<shocker id>,"op":"shock|vibrate|beep|end",
#                             "duration":<ms>,"intensity":<0-100>}}
#   {"cmd":"info"}  -> the hub prints one line "TERMINALINFO: {json}"
# OpenShock (the same hubs reflashed, or a DIY ESP32 board): one
# "$rftransmit {json}" line per command — see openshock_serial.py.
#
# Neither waits for a reply, so every send is fire-and-forget: one small
# write on the caller's thread, no ack, no queue (ARCHITECTURE.md "Latency
# budget").
#
# PiShock's info block carries the hub's saved Wi-Fi passwords, MAC, public
# IP and a one-time key next to the shocker list. Only `safe_info()`'s fields
# ever leave this module — the raw line is parsed and dropped, never logged.
#
# All safety (caps, cooldowns, arming) lives upstream in PiShockEngine; this
# layer only finds the hub and marshals bytes.

import errno
import json
import sys
import threading
import time
from typing import Any, Callable, Dict, List, Optional

import openshock_serial as openshock

PISHOCK = "pishock"
OPENSHOCK = "openshock"
HUB_NAMES = {PISHOCK: "PiShock", OPENSHOCK: "OpenShock"}

try:
    import serial  # pyserial
    from serial.tools import list_ports as _list_ports
    SERIAL_AVAILABLE = True
except Exception:  # pragma: no cover - exercised only without pyserial
    serial = None  # type: ignore
    _list_ports = None  # type: ignore
    SERIAL_AVAILABLE = False

BAUD = 115200
INFO_PREFIX = b"TERMINALINFO: "

# USB-serial bridges the hubs ship with (PiShock's from python-pishock's
# serialapi). These are common on hobby boards too, which is why a candidate
# port only counts once it answers the handshake.
USB_IDS = (
    (0x1A86, 0x7523),  # CH340  - PiShock 2023 / Next, Firebeetle 2 ESP32-E
    (0x1A86, 0x55D4),  # CH9102 - PiShock Lite
    (0x10C4, 0xEA60),  # CP210x - Wemos D1 Mini ESP32 (OpenShock boards)
)
# Boards on the chip's own USB (ESP32-S2/S3: Lolin S2 Mini / S3, Xiao S3,
# OpenShock Core) report Espressif's vendor id with any product id.
ESPRESSIF_VID = 0x303A

# The handshake re-asks for info this often — a hub that was mid-boot when
# the port opened misses the first request.
_INFO_RETRY_S = 2.0
# Bounds a write on a wedged port so the router thread can't hang on it.
_WRITE_TIMEOUT_S = 0.1


def list_ports() -> List[Dict[str, Any]]:
    """Every serial port on the PC, hub-shaped ones flagged."""
    if not SERIAL_AVAILABLE:
        return []
    out = []
    try:
        for p in _list_ports.comports():
            out.append({
                "device": str(p.device),
                "description": str(p.description or ""),
                "hub": (p.vid, p.pid) in USB_IDS or p.vid == ESPRESSIF_VID,
            })
    except Exception:
        return []
    return sorted(out, key=lambda p: (not p["hub"], p["device"]))


def hub_candidates() -> List[str]:
    return [p["device"] for p in list_ports() if p["hub"]]


def safe_info(raw: Any) -> Dict[str, Any]:
    """The fields of a TERMINALINFO block the app may keep and show."""
    if not isinstance(raw, dict):
        return {"version": "", "type": None, "shockers": []}
    shockers = []
    for s in raw.get("shockers") or []:
        if not isinstance(s, dict):
            continue
        try:
            sid = int(s.get("id"))
        except (TypeError, ValueError):
            continue
        shockers.append({"id": sid, "paused": bool(s.get("paused", False))})
    hub_type = raw.get("type")
    return {
        "version": str(raw.get("version", "") or ""),
        "type": hub_type if isinstance(hub_type, int) else None,
        "shockers": shockers,
    }


def encode_operate(shocker_id: int, op: str, intensity: int,
                   duration_ms: int) -> bytes:
    value = {"id": int(shocker_id), "op": op, "duration": int(duration_ms)}
    if op in ("shock", "vibrate"):
        value["intensity"] = int(intensity)
    return (json.dumps({"cmd": "operate", "value": value}) + "\n").encode("utf-8")


def encode_end(shocker_id: int) -> bytes:
    return encode_operate(shocker_id, "end", 0, 0)


def encode_info() -> bytes:
    return b'{"cmd": "info"}\n'


def _permission_denied(exc: BaseException) -> bool:
    """pyserial reports a refused open as SerialException(EACCES, ...)."""
    return (isinstance(exc, PermissionError)
            or getattr(exc, "errno", None) == errno.EACCES)


class PiShockSerialLink:
    """One open USB link to a hub, whichever firmware it runs. `open()`
    blocks through the handshake (call it off the GUI thread); everything
    after that is non-blocking. A reader thread drains the hub's log output,
    picks up info, and reports a vanished port through `on_lost` — so an
    unplugged cable is noticed even while nothing is being sent.

    The shocker ids the engine sends to are PiShock's own ids on a PiShock
    hub, and the transmitter ids from `set_openshock_shockers()` on an
    OpenShock one (that firmware has no list of its own)."""

    def __init__(self,
                 on_info: Optional[Callable[[Dict[str, Any]], None]] = None,
                 on_lost: Optional[Callable[[str], None]] = None,
                 on_error: Optional[Callable[[str], None]] = None,
                 serial_factory: Optional[Callable[..., Any]] = None):
        self._on_info = on_info or (lambda _i: None)
        self._on_lost = on_lost or (lambda _r: None)
        self._on_error = on_error or (lambda _m: None)
        self._factory = serial_factory
        self._ser = None
        self._port = ""
        self._write_lock = threading.Lock()
        self._closing = False
        self._reader: Optional[threading.Thread] = None
        self._first_info = threading.Event()
        self._info: Dict[str, Any] = {}
        self._kind = ""                      # PISHOCK / OPENSHOCK once known
        # OpenShock: what the handshake has seen so far, and the page's list.
        self._os_seen = False
        self._os_version = ""
        self._os_board = ""
        self._os_auto = False                # firmware takes "$" lines
        self._os_shockers: List[Dict[str, Any]] = []
        self._os_models: Dict[int, str] = {}

    @property
    def port(self) -> str:
        return self._port

    @property
    def is_open(self) -> bool:
        return self._ser is not None

    @property
    def kind(self) -> str:
        return self._kind

    @property
    def info(self) -> Dict[str, Any]:
        return dict(self._info)

    def set_openshock_shockers(self, shockers: List[Dict[str, Any]]) -> None:
        """The shockers to drive on an OpenShock hub (id, model, name).
        Ignored on a PiShock hub, which reports its own."""
        shockers = openshock.clean_shockers(shockers)
        self._os_models = {s["id"]: s["model"] for s in shockers}
        self._os_shockers = shockers
        if self._kind == OPENSHOCK:
            self._set_openshock_info(notify=True)

    # ---- cold path ---------------------------------------------------
    def open(self, port: str, handshake_timeout_s: float = 6.0) -> Dict[str, Any]:
        """Open `port` and wait for the hub to identify itself. Returns the
        safe info; raises (with the port closed again) when the port won't
        open or nothing answering like a PiShock or OpenShock hub is on
        it."""
        factory = self._factory
        if factory is None:
            if not SERIAL_AVAILABLE:
                raise RuntimeError("pyserial is not installed")
            factory = serial.Serial
        try:
            ser = factory(port, BAUD, timeout=0.25,
                          write_timeout=_WRITE_TIMEOUT_S)
        except Exception as e:
            if _permission_denied(e) and sys.platform.startswith("linux"):
                # Linux gives USB serial ports to one group; a fresh install
                # doesn't put the user in it.
                raise RuntimeError(
                    f"no permission to open {port} - add yourself to the "
                    f"'dialout' group ('uucp' on Arch), then log out and "
                    f"back in") from e
            if _permission_denied(e) or "access is denied" in str(e).lower():
                # Windows: another program holds the port.
                raise RuntimeError(
                    f"{port} is in use by another program - close OpenShock "
                    f"Desktop's serial relay, a web flasher tab or any serial "
                    f"monitor, then connect again") from e
            raise
        self._ser = ser
        self._port = port
        self._closing = False
        self._kind = ""
        self._os_seen, self._os_version, self._os_board = False, "", ""
        self._os_auto = False
        self._first_info.clear()
        self._reader = threading.Thread(
            target=self._read_loop, args=(ser,), daemon=True,
            name="PiShockSerialReader")
        self._reader.start()
        deadline = time.monotonic() + handshake_timeout_s
        while True:
            # Ask both ways; each firmware ignores the other's question.
            # (OpenShock answers PiShock's with a "$SYS$|Error" line, which
            # is itself a sure sign of OpenShock.)
            self._write(encode_info())
            self._write(openshock.encode_version())
            left = deadline - time.monotonic()
            if left <= 0 or self._first_info.wait(min(_INFO_RETRY_S, left)):
                break
        if not self._first_info.is_set():
            self.close()
            raise RuntimeError(f"no PiShock or OpenShock hub answered on {port}")
        return self.info

    def close(self) -> None:
        self._closing = True
        ser, self._ser = self._ser, None
        if ser is not None:
            try:
                ser.close()
            except Exception:
                pass

    # ---- hot path ----------------------------------------------------
    def operate(self, shocker_id: int, op: str, intensity: int,
                duration_ms: int) -> bool:
        if self._kind == OPENSHOCK:
            model = self._os_models.get(shocker_id)
            if model is None:
                return False
            return self._write(openshock.encode_rftransmit(
                model, shocker_id, op, intensity, duration_ms, self._os_auto))
        return self._write(encode_operate(shocker_id, op, intensity, duration_ms))

    def end(self, shocker_id: int) -> bool:
        if self._kind == OPENSHOCK:
            model = self._os_models.get(shocker_id)
            if model is None:
                return False
            return self._write(openshock.encode_stop(model, shocker_id, self._os_auto))
        return self._write(encode_end(shocker_id))

    def _write(self, data: bytes) -> bool:
        ser = self._ser
        if ser is None:
            return False
        try:
            with self._write_lock:
                ser.write(data)
            return True
        except Exception as e:
            self._lost(f"write failed: {e}")
            return False

    # ---- reader ------------------------------------------------------
    def _read_loop(self, ser) -> None:
        while not self._closing and self._ser is ser:
            try:
                line = ser.readline()
            except Exception as e:
                self._lost(f"read failed: {e}")
                return
            if not line:
                continue
            if line.startswith(INFO_PREFIX):
                if self._kind == OPENSHOCK:
                    continue
                try:
                    raw = json.loads(line[len(INFO_PREFIX):])
                except ValueError:
                    continue
                self._info = safe_info(raw)
                del raw  # the passwords go no further than this frame
                self._kind = PISHOCK
                self._first_info.set()
                self._emit_info()
            elif self._kind != PISHOCK:
                self._read_openshock(line)

    def _read_openshock(self, line: bytes) -> None:
        if openshock.is_openshock_line(line):
            self._os_seen = True
        version = openshock.parse_version(line)
        if version:
            self._os_version = version
            # "$" (no echo) only where the firmware knows it.
            self._os_auto = openshock.supports_automated(version)
        board = openshock.parse_board(line)
        if board is not None and self._os_version:
            self._os_board = board
        if self._kind == OPENSHOCK:
            if version or board is not None:
                self._set_openshock_info(notify=True)
            error = openshock.parse_error(line)
            # "not found" answers a handshake question meant for PiShock,
            # sent before this hub had identified itself.
            if error and "not found" not in error:
                try:
                    self._on_error(error)
                except Exception:
                    pass
        elif self._os_seen and self._os_version:
            self._kind = OPENSHOCK
            self._set_openshock_info(notify=False)
            self._first_info.set()
            self._emit_info()

    def _set_openshock_info(self, notify: bool) -> None:
        self._info = {
            "version": self._os_version,
            "type": None,
            "board": self._os_board,
            "shockers": [{"id": s["id"], "paused": False, "name": s["name"],
                          "model": s["model"]} for s in self._os_shockers],
        }
        if notify:
            self._emit_info()

    def _emit_info(self) -> None:
        try:
            self._on_info(self.info)
        except Exception:
            pass

    def _lost(self, reason: str) -> None:
        if self._closing:
            return
        self.close()
        try:
            self._on_lost(reason)
        except Exception:
            pass
