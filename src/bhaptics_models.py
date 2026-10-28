# bhaptics_models.py
# What each bHaptics device is and how its Bluetooth frame is built. Pure --
# no Bluetooth, no threads -- so the byte layout is unit-testable on its own.
#
# The protocol is unpublished. What's here comes from SenseShift's reverse
# engineering, checked against three independent implementations, and from
# the bHaptics Player's own logs:
#   * service 6e400001-..., written without response; battery 6e400008-...
#     (first byte = percent).
#   * The TactSuit Pro and Air take 40 bytes on 6e400014-..., one byte per
#     motor, 0..100 -- 32 motors (see GRID_* below).
#   * Older vests (X40, X16, Tactot) take 20 bytes on 6e40000a-... = 40 slots
#     of 0..15, two per byte, the even slot in the high half. A Pro reads
#     that frame as one byte per motor, so every touch lands on the wrong
#     motor -- why the two vests are kept apart.
#   * Sleeves, head, hands and feet take one byte per motor, 0..100, on
#     6e40000a-....
#
# The X40 dot -> slot tables below are the community-reported layout, never
# checked on a real X40. Which side of the Pro / Air grid is the wearer's
# left is the one thing the Player's logs can't say: pressing a dot on the
# Suits page settles it (then set `verified`).

from dataclasses import dataclass
from typing import Dict, Mapping, Optional, Sequence, Tuple

SERVICE_UUID = "6e400001-b5a3-f393-e0a9-e50e24dcca9e"
MOTOR_CHAR = "6e40000a-b5a3-f393-e0a9-e50e24dcca9e"
GRID_MOTOR_CHAR = "6e400014-b5a3-f393-e0a9-e50e24dcca9e"
BATTERY_CHAR = "6e400008-b5a3-f393-e0a9-e50e24dcca9e"

# Advertised-name prefixes worth connecting to.
NAME_PREFIXES = ("TactSuit", "Tactot", "Tactosy", "Tactal")

# Positions use the bHaptics Player's names, which the avatar packages use too.
NODE_COUNTS: Dict[str, int] = {
    "Head": 6,
    "VestFront": 20, "VestBack": 20,
    "ForearmL": 6, "ForearmR": 6,
    "HandL": 3, "HandR": 3,
    "FootL": 3, "FootR": 3,
}

VEST_SLOTS = 40
VEST_LEVELS = 15        # a vest slot runs 0..15
PLAIN_MAX = 100         # a plain device's byte runs 0..100

# Dot index (4 columns x 5 rows, row-major, as the Player numbers them) ->
# slot in the 40-slot frame. Columns 0-1 of the front sit in slots 30-39,
# columns 2-3 in slots 0-9; the back's columns 0-1 in 10-19, 2-3 in 20-29.
VEST_FRONT_SLOTS: Tuple[int, ...] = (
    31, 30, 1, 0,
    33, 32, 3, 2,
    35, 34, 5, 4,
    37, 36, 7, 6,
    39, 38, 9, 8,
)
VEST_BACK_SLOTS: Tuple[int, ...] = (
    10, 11, 20, 21,
    12, 13, 22, 23,
    14, 15, 24, 25,
    16, 17, 26, 27,
    18, 19, 28, 29,
)

# The Pro / Air frame, read off the bHaptics Player's logs of Blise's suits
# (2025-08, ~13,000 frames): 40 bytes, of which only 0-31 ever carry
# anything -- 32 motors, 4 columns x 4 rows a side, in four groups of eight,
# the X40's slot order with four rows instead of five:
#   bytes  0- 7  front, columns 0-1        bytes 16-23  back, columns 2-3
#   bytes  8-15  back,  columns 0-1        bytes 24-31  front, columns 2-3
# each group row by row, two motors a row. Scored against every other
# order, it's the one where motors that play together sit side by side.
GRID_FRAME_BYTES = 40
GRID_ROWS = 4
# The avatar sends five rows a side; the grid has four. The middle row goes
# with the belly, as OWO's muscles split it (body_map: chest = rows 0-1).
_DOT_ROW_TO_GRID_ROW = (0, 1, 2, 2, 3)


def _grid_byte(front: bool, row: int, col: int) -> int:
    group = (0 if col < 2 else 3) if front else (1 if col < 2 else 2)
    return group * 8 + row * 2 + col % 2


def _grid_table(front: bool) -> Tuple[int, ...]:
    """Dot index (4 x 5, row-major) -> byte in the Pro / Air frame."""
    return tuple(_grid_byte(front, _DOT_ROW_TO_GRID_ROW[i // 4], i % 4) for i in range(20))


GRID_FRONT_BYTES = _grid_table(True)
GRID_BACK_BYTES = _grid_table(False)


@dataclass(frozen=True)
class Model:
    key: str
    label: str
    vest: bool
    motors: int = 0                 # plain devices: bytes per frame
    verified: bool = False          # slot layout checked on real hardware
    # Plain devices: the position for each side; vests serve both panels.
    left: str = ""
    right: str = ""
    grid: bool = False              # vests: the Pro / Air 32-motor frame

    @property
    def motor_char(self) -> str:
        return GRID_MOTOR_CHAR if self.grid else MOTOR_CHAR


_VEST_MODELS = (
    # (name prefix, model) -- longest prefix first.
    ("TactSuitX40", Model("x40", "TactSuit X40", True)),
    ("TactSuitX16", Model("x16", "TactSuit X16", True)),
    ("TactSuitAir", Model("air", "TactSuit Air", True, grid=True)),
    ("TactSuitPro", Model("pro", "TactSuit Pro", True, grid=True)),
    ("TactSuit", Model("vest", "TactSuit", True)),
    ("Tactot", Model("tactot", "Tactot", True)),
)
_PLAIN_MODELS = (
    ("Tactosy2", Model("tactosy2", "Tactosy for arms", False, 6, left="ForearmL", right="ForearmR")),
    ("TactosyH", Model("tactosyh", "Tactosy for hands", False, 3, left="HandL", right="HandR")),
    ("TactosyF", Model("tactosyf", "Tactosy for feet", False, 3, left="FootL", right="FootR")),
    ("Tactal", Model("tactal", "Tactal", False, 6, left="Head", right="Head")),
)


@dataclass(frozen=True)
class Binding:
    """A model bound to one device: which positions it plays."""
    model: Model
    positions: Tuple[str, ...]


def _side(name: str) -> str:
    """'L' / 'R' from a sleeve's advertised name (Tactosy2_L, TactosyH_R ...).
    Unknown -> 'L'; the page can swap it later."""
    n = name.upper()
    if "_R" in n or n.endswith("R"):
        return "R"
    return "L"


def bind(name: Optional[str]) -> Optional[Binding]:
    """Advertised name -> Binding, or None for anything that isn't a known
    bHaptics device."""
    if not name:
        return None
    for prefix, model in _VEST_MODELS:
        if name.startswith(prefix):
            return Binding(model, ("VestFront", "VestBack"))
    for prefix, model in _PLAIN_MODELS:
        if name.startswith(prefix):
            pos = model.right if _side(name) == "R" else model.left
            return Binding(model, (pos,))
    return None


def _to_level(value, top: int) -> int:
    """0..100 -> 0..top, rounded; garbage reads as 0."""
    try:
        v = float(value)
    except (TypeError, ValueError):
        return 0
    if not v > 0:           # also catches NaN
        return 0
    return min(top, int(round(min(100.0, v) * top / 100.0)))


def vest_levels(frames: Mapping[str, Sequence[int]]) -> Tuple[int, ...]:
    """VestFront / VestBack dots (0..100) -> 40 slot levels (0..15). Two dots
    on one slot keep the stronger."""
    levels = [0] * VEST_SLOTS
    for position, table in (("VestFront", VEST_FRONT_SLOTS), ("VestBack", VEST_BACK_SLOTS)):
        dots = frames.get(position) or ()
        for i, slot in enumerate(table):
            if i < len(dots):
                lv = _to_level(dots[i], VEST_LEVELS)
                if lv > levels[slot]:
                    levels[slot] = lv
    return tuple(levels)


def pack_vest(levels: Sequence[int]) -> bytes:
    """40 slot levels (0..15) -> the 20-byte frame."""
    lv = (list(levels) + [0] * VEST_SLOTS)[:VEST_SLOTS]
    return bytes(
        (max(0, min(VEST_LEVELS, int(lv[i * 2]))) << 4)
        | max(0, min(VEST_LEVELS, int(lv[i * 2 + 1])))
        for i in range(VEST_SLOTS // 2)
    )


def grid_frame(frames: Mapping[str, Sequence[int]]) -> bytes:
    """VestFront / VestBack dots (0..100) -> the Pro / Air's 40 bytes. Two
    dots on one motor keep the stronger."""
    out = [0] * GRID_FRAME_BYTES
    for position, table in (("VestFront", GRID_FRONT_BYTES), ("VestBack", GRID_BACK_BYTES)):
        dots = frames.get(position) or ()
        for i, byte in enumerate(table):
            if i < len(dots):
                lv = _to_level(dots[i], PLAIN_MAX)
                if lv > out[byte]:
                    out[byte] = lv
    return bytes(out)


def encode(binding: Binding, frames: Mapping[str, Sequence[int]]) -> bytes:
    """The frame for one device from per-position dots (0..100)."""
    if binding.model.vest:
        return grid_frame(frames) if binding.model.grid else pack_vest(vest_levels(frames))
    dots = frames.get(binding.positions[0]) or ()
    count = binding.model.motors
    return bytes(_to_level(dots[i], PLAIN_MAX) if i < len(dots) else 0 for i in range(count))


def zero_frame(binding: Binding) -> bytes:
    if binding.model.grid:
        return bytes(GRID_FRAME_BYTES)
    return bytes(VEST_SLOTS // 2) if binding.model.vest else bytes(binding.model.motors)
