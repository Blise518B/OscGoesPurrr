"""Pure (I/O-free) Lovense wire-protocol logic for the bench's toy side.

Intiface Central's Device Websocket Server (WSDM) hands a connecting device
the *protocol's own bytes* — for Lovense those are ASCII command strings. This
module models a single virtual Lovense toy: it knows how to build the WSDM
handshake, answer the `DeviceType;` / `Battery;` queries Intiface issues during
init, and decode the motor commands OGP ends up sending into per-feature 0..1
levels for display.

Kept deliberately free of any websocket / Qt import so it can be unit-tested
without hardware, Intiface, or a GUI (see testbench/tests/test_lovense_protocol.py).

Wire facts (verified against buttplugio/buttplug source, May 2026):

  * WSDM default port is 54817 on 127.0.0.1.
  * The FIRST websocket frame must be TEXT: a JSON packet
    `{"identifier": <str>, "address": <str>, "version": 0}`. All three fields
    are required (serde rejects a missing field and the server drops the
    connection). `identifier` is matched against a `websocket` specifier in
    Intiface's device config — NOT the Lovense model letter. The model is
    decided later, from our `DeviceType;` reply.
  * Every later frame is BINARY and carries raw protocol bytes with no endpoint
    framing. Intiface writes `DeviceType;`, `Battery;`, `Vibrate:N;` etc.; any
    binary frame we send back is delivered to the protocol as a notification.
  * Lovense `DeviceType;` reply is `"<LETTER>:<firmware>:<MAC>;"`. The leading
    letter selects the model (and therefore the motor layout OGP sees):
      S / Z  -> single vibrator        (Vibrate:N;)
      P      -> dual vibrator           (Vibrate1:N; / Vibrate2:N;)
      A / C  -> vibrate + rotate         (Vibrate:N; / Rotate:N; / RotateChange;)
      B      -> vibrate + air pump        (Vibrate:N; / Air:Level:N;)
      BA     -> Solace Pro stroker        (FSetSite:N; position, or Mply:s:r;)
"""

from __future__ import annotations

import json
import random
from dataclasses import dataclass
from typing import List, Optional, Tuple

# ---------------------------------------------------------------- feature kinds
# These mirror the kind labels OGP's haptic_engine assigns so the simulator's
# bars line up with what the main app calls each motor.
KIND_VIBRATE = "vibrate"
KIND_ROTATE = "rotate"
KIND_CONSTRICT = "constrict"
KIND_LINEAR = "linear"
KIND_OSCILLATE = "oscillate"


@dataclass(frozen=True)
class Feature:
    """One controllable output on a virtual toy.

    `max_raw` is the largest integer the Lovense command for this feature
    carries (vibrate/rotate = 20, Max air pump = 3, stroker position = 100), so
    a decoded raw value normalises to 0..1 as `raw / max_raw`.
    """
    label: str
    kind: str
    max_raw: int


@dataclass(frozen=True)
class LovenseModel:
    device_type: str           # letter returned to a DeviceType; query
    name: str                  # how Intiface labels the device
    features: Tuple[Feature, ...]
    firmware: str = "11"


# The curated model menu. Each entry exercises a different OGP classification
# path; the letters are the real identifiers from buttplug's lovense.yml so
# Intiface registers the matching motor layout.
MODELS: Tuple[LovenseModel, ...] = (
    LovenseModel("Z", "Lovense Hush", (Feature("Vibrate", KIND_VIBRATE, 20),)),
    LovenseModel("S", "Lovense Lush", (Feature("Vibrate", KIND_VIBRATE, 20),)),
    LovenseModel("P", "Lovense Edge", (
        Feature("Vibrate 1", KIND_VIBRATE, 20),
        Feature("Vibrate 2", KIND_VIBRATE, 20),
    )),
    LovenseModel("A", "Lovense Nora", (
        Feature("Vibrate", KIND_VIBRATE, 20),
        Feature("Rotate", KIND_ROTATE, 20),
    )),
    LovenseModel("B", "Lovense Max", (
        Feature("Vibrate", KIND_VIBRATE, 20),
        Feature("Air Pump", KIND_CONSTRICT, 3),
    )),
    LovenseModel("BA", "Lovense Solace Pro", (
        Feature("Stroker", KIND_LINEAR, 100),
    )),
)

MODELS_BY_NAME = {m.name: m for m in MODELS}

# Default websocket-specifier identifier. The user must list this same string
# under lovense -> websocket -> names in Intiface's user device config so the
# handshake maps to the Lovense protocol.
DEFAULT_WS_IDENTIFIER = "OGPSim"


def random_address() -> str:
    """A random 12-hex-digit string used as the per-toy address / fake MAC."""
    return "".join(random.choice("0123456789ABCDEF") for _ in range(12))


def _safe_int(text: str) -> Optional[int]:
    try:
        return int(text.strip())
    except (ValueError, AttributeError):
        return None


class LovenseProtocol:
    """Stateful, transport-free decoder/responder for one virtual toy."""

    def __init__(
        self,
        model: LovenseModel,
        address: str,
        ws_identifier: str = DEFAULT_WS_IDENTIFIER,
        battery_pct: int = 90,
    ) -> None:
        self.model = model
        self.address = address
        self.ws_identifier = ws_identifier
        self.battery_pct = int(battery_pct)
        # Current decoded level per feature index, 0..1.
        self.levels: List[float] = [0.0] * len(model.features)
        # Lovense rotation direction toggles via RotateChange; (+1 / -1).
        self.rotate_dir = 1

    # ------------------------------------------------------------- handshake
    def handshake_text(self) -> str:
        """The first frame (TEXT) Intiface's WSDM expects."""
        return json.dumps({
            "identifier": self.ws_identifier,
            "address": self.address,
            "version": 0,
        })

    def device_type_response(self) -> bytes:
        """Reply to `DeviceType;` — `<LETTER>:<firmware>:<MAC>;`."""
        mac = (self.address + "0" * 12)[:12]
        return f"{self.model.device_type}:{self.model.firmware}:{mac};".encode("ascii")

    # ------------------------------------------------------------- decoding
    def _index_of_kind(self, kind: str) -> Optional[int]:
        for i, feat in enumerate(self.model.features):
            if feat.kind == kind:
                return i
        return None

    def _apply(self, updates: List[Tuple[int, float]], idx: int, raw: int) -> None:
        if idx is None or idx < 0 or idx >= len(self.model.features):
            return
        max_raw = self.model.features[idx].max_raw or 1
        level = max(0.0, min(1.0, raw / max_raw))
        self.levels[idx] = level
        updates.append((idx, level))

    def process_command(
        self, raw: bytes
    ) -> Tuple[List[Tuple[int, float]], Optional[bytes], List[str]]:
        """Decode one inbound binary frame.

        Returns `(level_updates, response, log_lines)` where `level_updates` is
        a list of `(feature_index, level_0_to_1)`, `response` is bytes to send
        back (only for queries Intiface waits on), and `log_lines` is the raw
        commands for display. A single frame may pack several `;`-terminated
        commands, so each is handled in turn.
        """
        text = raw.decode("utf-8", errors="replace")
        updates: List[Tuple[int, float]] = []
        response: Optional[bytes] = None
        logs: List[str] = []

        for token in text.split(";"):
            cmd = token.strip()
            if not cmd:
                continue
            logs.append(cmd + ";")

            if cmd == "DeviceType":
                response = self.device_type_response()
            elif cmd == "Battery":
                response = f"{self.battery_pct};".encode("ascii")
            elif cmd == "RotateChange":
                self.rotate_dir *= -1
            elif cmd.startswith("Vibrate"):
                head, _, val = cmd.partition(":")
                n = _safe_int(val)
                if n is None:
                    continue
                suffix = head[len("Vibrate"):]          # "" or "1" / "2"
                if suffix.isdigit():
                    self._apply(updates, int(suffix) - 1, n)
                else:
                    self._apply(updates, self._index_of_kind(KIND_VIBRATE), n)
            elif cmd.startswith("Rotate:"):
                n = _safe_int(cmd.split(":", 1)[1])
                if n is not None:
                    self._apply(updates, self._index_of_kind(KIND_ROTATE), n)
            elif cmd.startswith("Air:Level:"):
                n = _safe_int(cmd.rsplit(":", 1)[1])
                if n is not None:
                    self._apply(updates, self._index_of_kind(KIND_CONSTRICT), n)
            elif cmd.startswith("Air:In:") or cmd.startswith("Air:Out:"):
                pass  # relative pump nudge — shown in the log, no level to set
            elif cmd.startswith("FSetSite:"):
                n = _safe_int(cmd.split(":", 1)[1])
                if n is not None:
                    self._apply(updates, self._index_of_kind(KIND_LINEAR), n)
            elif cmd.startswith("Mply:"):
                # Multi/oscillate form, e.g. Solace `Mply:<speed>:<range>;`. Map
                # the leading speed onto the first output as an oscillation
                # magnitude (0..20) so the bar still moves.
                parts = cmd.split(":")[1:]
                n = _safe_int(parts[0]) if parts else None
                if n is not None and self.model.features:
                    idx = 0
                    cap = self.model.features[idx].max_raw
                    self._apply(updates, idx, n if cap >= 20 else int(round(n / 20 * cap)))
            # Anything else: already logged, nothing to decode.

        return updates, response, logs
