# openshock_serial.py
# OpenShock firmware over the USB cable: the second wire format the hub link
# (pishock_serial.PiShockSerialLink) speaks, picked by whichever firmware
# answers the handshake.
#
# OpenShock (github.com/OpenShock/Firmware) is open firmware for ESP32 boards
# with a 433 MHz transmitter — PiShock's own 2023 and Lite hubs among them.
# It drives cheap collars (CaiXianlin, Petrainer, ...) and PiShock's own
# shocker, which is a CaiXianlin. Serial is 115200 8n1, one command a line:
#   $rftransmit {"model":"caixianlin","id":12345,"type":"vibrate",
#                "intensity":40,"durationMs":300}
#   version     -> "  Version:  1.5.2" ... "    Board:  ..." lines
# The leading "$" marks a line as automated, so the hub doesn't echo it —
# but only firmware 1.4.0 and later knows it; older firmware answers
# "$rftransmit" with "command not found". So the handshake asks a plain
# "version" (every release has it), and the "$" goes on once the hub's
# version says it is understood. Every command answers "$SYS$|Success|..."
# or "$SYS$|Error|..."; nothing waits for that — a send is fire-and-forget,
# like PiShock's operate.
#
# Over serial the hub keeps no shocker list: a shocker is a model plus the
# 16-bit transmitter id the collar learnt while pairing. So the list comes
# from the Shockers page, and pairing a new collar is: hold its power button
# until the light blinks fast, then send it anything from a new id.
#
# A command for a shocker that is still running replaces it (the firmware's
# RF task overwrites the running sequence for that model + id), which the
# engine's hold chunks rely on; "stop" is a 300 ms zero-strength
# replacement. The firmware reads one line per 20 ms, so several shockers
# sent in the same tick go out about 20 ms apart.

import json
import re
from typing import Any, Dict, List, Optional

# (firmware model id, what the page calls it). Older firmware refuses a
# model it doesn't know with "Failed to parse shocker command".
MODELS = (
    ("caixianlin", "CaiXianlin / PiShock shocker"),
    ("petrainer", "Petrainer"),
    ("petrainer998dr", "Petrainer 998DR"),
    ("wellturnt330", "Wellturn T330 (firmware 1.5+)"),
    ("d80", "D80 (firmware 1.5+)"),
)
MODEL_IDS = tuple(m for m, _label in MODELS)
DEFAULT_MODEL = "caixianlin"
MAX_RF_ID = 65535
MAX_SHOCKERS = 16

# The engine's ops in OpenShock's words.
_TYPES = {"shock": "shock", "vibrate": "vibrate", "beep": "sound"}

SYS_PREFIX = b"$SYS$|"
_ERROR_PREFIX = b"$SYS$|Error|"
_BANNER = b"OPENSHOCK"
_VERSION_RE = re.compile(rb"^\s*Version:\s*(\S+)")
_BOARD_RE = re.compile(rb"^\s*Board:\s*(.*?)\s*$")
_SEMVER_RE = re.compile(r"^\s*v?(\d+)\.(\d+)")


def supports_automated(version: str) -> bool:
    """Does firmware `version` understand the "$" prefix (1.4.0 and later)?
    An unknown version gets plain lines, which every release takes — at
    worst the hub echoes them back."""
    m = _SEMVER_RE.match(version or "")
    return bool(m) and (int(m.group(1)), int(m.group(2))) >= (1, 4)


def _line(command: str, value: Dict[str, Any], automated: bool) -> bytes:
    text = command + " " + json.dumps(value, separators=(",", ":")) + "\n"
    return (("$" if automated else "") + text).encode()


def encode_rftransmit(model: str, rf_id: int, op: str, intensity: int,
                      duration_ms: int, automated: bool = True) -> bytes:
    value = {
        "model": model,
        "id": max(0, min(MAX_RF_ID, int(rf_id))),
        "type": _TYPES[op],
        # A sound carries no strength (the firmware zeroes it anyway).
        "intensity": max(0, min(100, int(intensity))) if op != "beep" else 0,
        "durationMs": max(0, min(65535, int(duration_ms))),
    }
    return _line("rftransmit", value, automated)


def encode_stop(model: str, rf_id: int, automated: bool = True) -> bytes:
    value = {"model": model, "id": max(0, min(MAX_RF_ID, int(rf_id))),
             "type": "stop", "intensity": 0, "durationMs": 0}
    return _line("rftransmit", value, automated)


def encode_version() -> bytes:
    # Plain, not "$version": firmware before 1.4.0 has no "$" prefix.
    return b"version\n"


def is_openshock_line(line: bytes) -> bool:
    """A line only OpenShock prints: a command reply or the boot banner.
    (A bare "Version:" line isn't enough — other firmware may log one.)"""
    return line.startswith(SYS_PREFIX) or _BANNER in line


def parse_version(line: bytes) -> Optional[str]:
    m = _VERSION_RE.match(line)
    return m.group(1).decode("utf-8", "replace") if m else None


def parse_board(line: bytes) -> Optional[str]:
    m = _BOARD_RE.match(line)
    return m.group(1).decode("utf-8", "replace") if m else None


def parse_error(line: bytes) -> Optional[str]:
    if not line.startswith(_ERROR_PREFIX):
        return None
    return line[len(_ERROR_PREFIX):].decode("utf-8", "replace").strip()


def clean_shockers(raw: Any) -> List[Dict[str, Any]]:
    """The page's OpenShock shocker list, made safe to send from: known
    models only, ids in range, each id once (the first one wins)."""
    out: List[Dict[str, Any]] = []
    seen = set()
    for s in raw if isinstance(raw, list) else []:
        if not isinstance(s, dict) or len(out) >= MAX_SHOCKERS:
            continue
        try:
            rf_id = int(float(s.get("id")))
        except (TypeError, ValueError, OverflowError):     # 1e999 / a 400-digit id
            continue
        if not 0 <= rf_id <= MAX_RF_ID or rf_id in seen:
            continue
        model = str(s.get("model", "") or "")
        seen.add(rf_id)
        out.append({
            "id": rf_id,
            "model": model if model in MODEL_IDS else DEFAULT_MODEL,
            "name": str(s.get("name", "") or "").strip()[:40],
        })
    return out
