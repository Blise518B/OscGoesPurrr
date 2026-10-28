# body_map.py
# One body for both suits. Every avatar input a haptic suit can react to is
# read into a single "body frame" -- 0..1 per node, on the bHaptics layout --
# and each suit takes its own view of it: bHaptics plays the nodes as dots,
# OWO plays each muscle as the strongest node in its patch. So one avatar
# setup drives both suits (Blise's call, 2026-10-23: contacts are shared both
# ways), and a zone routed to a body region lands on both.
#
# Pure: no Qt, no threads, no I/O. The SuitsRouter calls it once per tick.
#
# Inputs, as parameter_store keys them (`/avatar/parameters/` stripped,
# inner slashes kept):
#   * official bHaptics avatar package: bools  bOSC/v2/<Pos>/<n>/self  and
#     .../others  (n 0-based), and the Quest prefabs' bOSC/v2m/...;
#   * older avatars: bHaptics_<Slot>_<N>_bool (HerpDerpinstine bHapticsOSC
#     v1, N 1-based) and bOSC_v1_<Pos>_<N> floats -- no self/others split;
#   * the OWO avatar package: owo_suit_<Muscle>, bool or float;
#   * zone routes: an OGB / SPS zone or synthetic source, resolved by
#     zone_strength.zone_filter_strength, onto a named region.

from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Set, Tuple

from zone_strength import truthy, zone_filter_strength

POSITIONS: Tuple[Tuple[str, int], ...] = (
    ("Head", 6),
    ("VestFront", 20),
    ("VestBack", 20),
    ("ForearmL", 6),
    ("ForearmR", 6),
    ("HandL", 3),
    ("HandR", 3),
    ("FootL", 3),
    ("FootR", 3),
)
NODE_COUNTS: Dict[str, int] = dict(POSITIONS)

# The bHaptics parts someone owns, as the Suits page asks it ("You have",
# Blise's ask 2026-10-28: a vest alone shows no arm, head or foot dots).
# (key, name, positions) -- a vest is both panels, sleeves both arms.
PART_GROUPS: Tuple[Tuple[str, str, Tuple[str, ...]], ...] = (
    ("vest", "Vest", ("VestFront", "VestBack")),
    ("arms", "Sleeves", ("ForearmL", "ForearmR")),
    ("hands", "Hands", ("HandL", "HandR")),
    ("feet", "Feet", ("FootL", "FootR")),
    ("head", "Head", ("Head",)),
)
DEFAULT_HAVE: Tuple[str, ...] = ("vest",)
_GROUP_OF = {pos: key for key, _name, positions in PART_GROUPS for pos in positions}


def group_of(position: str) -> Optional[str]:
    """The part group ("vest", "arms", ...) a position belongs to."""
    return _GROUP_OF.get(position)


def positions_of(groups: Iterable[str]) -> Tuple[str, ...]:
    """The positions of these part groups, in POSITIONS order."""
    wanted = set(groups)
    return tuple(pos for pos, _n in POSITIONS if _GROUP_OF.get(pos) in wanted)

# OWO's muscles in its SDK's index order (0-9).
MUSCLES: Tuple[str, ...] = (
    "Pectoral_R", "Pectoral_L",
    "Abdominal_R", "Abdominal_L",
    "Arm_R", "Arm_L",
    "Dorsal_R", "Dorsal_L",
    "Lumbar_R", "Lumbar_L",
)

REACT_BOTH = "both"
REACT_OTHERS = "others"
REACT_SELF = "self"
REACT_CHOICES = (REACT_BOTH, REACT_OTHERS, REACT_SELF)

# Grid layout for the 4 x 5 vest panels, row-major. Each panel is numbered
# as seen from outside it (the front from the front, the back from behind),
# which is what the X40 slot table implies -- NOT yet felt on Blise's suit.
# tools/bhaptics_probe.py `walk --interactive` settles it; swap these if the
# sides come out mirrored.
_FRONT_WEARER_RIGHT_COLS = (0, 1)
_FRONT_WEARER_LEFT_COLS = (2, 3)
_BACK_WEARER_LEFT_COLS = (0, 1)
_BACK_WEARER_RIGHT_COLS = (2, 3)
_UPPER_ROWS = (0, 1)
_LOWER_ROWS = (2, 3, 4)


def _cells(rows: Sequence[int], cols: Sequence[int]) -> Tuple[int, ...]:
    return tuple(r * 4 + c for r in rows for c in cols)


# Each OWO muscle's patch of the body: (position, node indices).
OWO_REGIONS: Dict[str, Tuple[str, Tuple[int, ...]]] = {
    "Pectoral_R": ("VestFront", _cells(_UPPER_ROWS, _FRONT_WEARER_RIGHT_COLS)),
    "Pectoral_L": ("VestFront", _cells(_UPPER_ROWS, _FRONT_WEARER_LEFT_COLS)),
    "Abdominal_R": ("VestFront", _cells(_LOWER_ROWS, _FRONT_WEARER_RIGHT_COLS)),
    "Abdominal_L": ("VestFront", _cells(_LOWER_ROWS, _FRONT_WEARER_LEFT_COLS)),
    "Arm_R": ("ForearmR", tuple(range(6))),
    "Arm_L": ("ForearmL", tuple(range(6))),
    "Dorsal_R": ("VestBack", _cells(_UPPER_ROWS, _BACK_WEARER_RIGHT_COLS)),
    "Dorsal_L": ("VestBack", _cells(_UPPER_ROWS, _BACK_WEARER_LEFT_COLS)),
    "Lumbar_R": ("VestBack", _cells(_LOWER_ROWS, _BACK_WEARER_RIGHT_COLS)),
    "Lumbar_L": ("VestBack", _cells(_LOWER_ROWS, _BACK_WEARER_LEFT_COLS)),
}

# What a zone route can land on: a whole device, or one muscle's patch.
REGIONS: Dict[str, Tuple[str, Tuple[int, ...]]] = dict(
    {pos: (pos, tuple(range(n))) for pos, n in POSITIONS}, **OWO_REGIONS)

_GRID_LAYOUTS: Dict[str, Tuple[int, int]] = {
    "Head": (6, 1),
    "VestFront": (4, 5),
    "VestBack": (4, 5),
    "ForearmL": (2, 3),
    "ForearmR": (2, 3),
    "HandL": (3, 1),
    "HandR": (3, 1),
    "FootL": (3, 1),
    "FootR": (3, 1),
}

_DISPLAY = {
    "Head": "Head",
    "VestFront": "Vest front",
    "VestBack": "Vest back",
    "ForearmL": "Left arm",
    "ForearmR": "Right arm",
    "HandL": "Left hand",
    "HandR": "Right hand",
    "FootL": "Left foot",
    "FootR": "Right foot",
}

_MUSCLE_DISPLAY = {
    "Pectoral_R": "Right chest", "Pectoral_L": "Left chest",
    "Abdominal_R": "Right belly", "Abdominal_L": "Left belly",
    "Arm_R": "Right arm", "Arm_L": "Left arm",
    "Dorsal_R": "Right upper back", "Dorsal_L": "Left upper back",
    "Lumbar_R": "Right lower back", "Lumbar_L": "Left lower back",
}


def grid_layout(position: str) -> Tuple[int, int]:
    """(cols, rows) for drawing a position's dots."""
    return _GRID_LAYOUTS.get(position, (NODE_COUNTS.get(position, 1), 1))


def display_name(name: str) -> str:
    """A position's or a muscle's name for the page."""
    return _DISPLAY.get(name) or _MUSCLE_DISPLAY.get(name) or name


# ---- the key table -----------------------------------------------------
# Every key any schema can send, built once: key -> (kind, target, index).
_V1_SLOTS = {
    "Head": "Head", "VestFront": "Vest_Front", "VestBack": "Vest_Back",
    "ForearmL": "Arm_Left", "ForearmR": "Arm_Right",
    "HandL": "Hand_Left", "HandR": "Hand_Right",
    "FootL": "Foot_Left", "FootR": "Foot_Right",
}
_SELF, _OTHERS, _ANY_BOOL, _ANY_FLOAT, _OWO = "self", "others", "anyb", "anyf", "owo"


def _build_keys() -> Dict[str, Tuple[str, str, int]]:
    keys: Dict[str, Tuple[str, str, int]] = {}
    for pos, count in POSITIONS:
        for i in range(count):
            for prefix in ("bOSC/v2", "bOSC/v2m"):
                keys[f"{prefix}/{pos}/{i}/self"] = (_SELF, pos, i)
                keys[f"{prefix}/{pos}/{i}/others"] = (_OTHERS, pos, i)
            keys[f"bHaptics_{_V1_SLOTS[pos]}_{i + 1}_bool"] = (_ANY_BOOL, pos, i)
            keys[f"bOSC_v1_{pos}_{i + 1}"] = (_ANY_FLOAT, pos, i)
    for muscle in MUSCLES:
        keys[f"owo_suit_{muscle}"] = (_OWO, muscle, 0)
    return keys


_KEYS = _build_keys()

Frame = Dict[str, Tuple[float, ...]]


def empty_frame() -> Frame:
    return {pos: (0.0,) * n for pos, n in POSITIONS}


def _unit(value: Any) -> float:
    """A bool or number as 0..1; anything else (NaN included) is 0."""
    if value is True:
        return 1.0
    if value is False or value is None:
        return 0.0
    try:
        v = float(value)
    except (TypeError, ValueError):
        return 0.0
    if not v > 0.0:
        return 0.0
    return 1.0 if v > 1.0 else v


@dataclass(frozen=True)
class BodyReading:
    """Everything read this tick, kept apart so each suit can pick."""
    self_touch: Frame = field(default_factory=empty_frame)
    others_touch: Frame = field(default_factory=empty_frame)
    any_touch: Frame = field(default_factory=empty_frame)     # schemas without a split
    owo: Dict[str, float] = field(default_factory=dict)
    routes: Frame = field(default_factory=empty_frame)


def _lists() -> Dict[str, List[float]]:
    return {pos: [0.0] * n for pos, n in POSITIONS}


def _frozen(lists: Mapping[str, List[float]]) -> Frame:
    return {pos: tuple(vals) for pos, vals in lists.items()}


def _raise(lists: Dict[str, List[float]], pos: str, indices: Iterable[int], v: float) -> None:
    row = lists[pos]
    for i in indices:
        if v > row[i]:
            row[i] = v


def read_body(params: Mapping[str, Any],
              routes: Sequence[Mapping[str, Any]] = (),
              sps_sources: Optional[Mapping[str, Any]] = None) -> BodyReading:
    """Read every suit input from one parameter snapshot."""
    self_t, others_t, any_t, route_t = _lists(), _lists(), _lists(), _lists()
    owo: Dict[str, float] = {}
    for key, value in params.items():
        spec = _KEYS.get(key)
        if spec is None:
            continue
        kind, target, i = spec
        if kind == _OWO:
            v = _unit(value)
            if v > owo.get(target, 0.0):
                owo[target] = v
            continue
        v = (1.0 if truthy(value) else 0.0) if kind == _ANY_BOOL else _unit(value)
        if v <= 0.0:
            continue
        lists = self_t if kind == _SELF else others_t if kind == _OTHERS else any_t
        if v > lists[target][i]:
            lists[target][i] = v
    for route in routes or ():
        if not isinstance(route, Mapping) or not route.get("enabled", True):
            continue
        region = REGIONS.get(str(route.get("region", "")))
        zone = str(route.get("zone", "") or "")
        if region is None or not zone:
            continue
        strength = zone_filter_strength(zone, route.get("zone_type", "Orf"),
                                        route.get("filters") or [], params, sps_sources)
        try:
            gain = float(route.get("gain", 1.0))
        except (TypeError, ValueError):
            gain = 1.0
        v = _unit(strength * gain) if gain == gain else 0.0
        if v > 0.0:
            _raise(route_t, region[0], region[1], v)
    return BodyReading(_frozen(self_t), _frozen(others_t), _frozen(any_t),
                       owo, _frozen(route_t))


def _merge(frames: Iterable[Frame]) -> Frame:
    out = _lists()
    for frame in frames:
        for pos, vals in frame.items():
            row = out.get(pos)
            if row is None:
                continue
            for i, v in enumerate(vals[:len(row)]):
                if v > row[i]:
                    row[i] = v
    return _frozen(out)


def _touch(reading: BodyReading, react_to: str) -> List[Frame]:
    frames = [reading.any_touch]
    if react_to in (REACT_BOTH, REACT_SELF):
        frames.append(reading.self_touch)
    if react_to in (REACT_BOTH, REACT_OTHERS):
        frames.append(reading.others_touch)
    return frames


def spread_owo(levels: Mapping[str, float]) -> Frame:
    """OWO muscle levels painted onto their patches of the body."""
    lists = _lists()
    for muscle, v in levels.items():
        region = OWO_REGIONS.get(muscle)
        v = _unit(v)
        if region is not None and v > 0.0:
            _raise(lists, region[0], region[1], v)
    return _frozen(lists)


def owo_muscles(frame: Frame) -> Dict[str, float]:
    """Each muscle as the strongest node in its patch."""
    out = {}
    for muscle, (pos, indices) in OWO_REGIONS.items():
        vals = frame.get(pos) or ()
        out[muscle] = max((vals[i] for i in indices if i < len(vals)), default=0.0)
    return out


def bhaptics_frame(reading: BodyReading, react_to: str = REACT_BOTH,
                   follow_owo: bool = True) -> Frame:
    """What the bHaptics suit should feel: its own contacts (filtered by
    self / others), every zone route, and -- when it follows OWO's
    contacts -- the OWO package's muscles on their patches."""
    frames = _touch(reading, react_to)
    frames.append(reading.routes)
    if follow_owo and reading.owo:
        frames.append(spread_owo(reading.owo))
    return _merge(frames)


def owo_levels(reading: BodyReading, react_to: str = REACT_BOTH,
               follow_bhaptics: bool = True) -> Dict[str, float]:
    """What each OWO muscle should feel (0..1): the OWO package's own
    contacts, every zone route, and -- when it follows bHaptics' contacts --
    the bHaptics nodes in its patch."""
    levels = {m: 0.0 for m in MUSCLES}
    sources = [owo_muscles(reading.routes)]
    if follow_bhaptics:
        sources.append(owo_muscles(_merge(_touch(reading, react_to))))
    sources.append(reading.owo)
    for src in sources:
        for muscle, v in src.items():
            if muscle in levels and v > levels[muscle]:
                levels[muscle] = v
    return levels


def bhaptics_dots(frame: Frame, devices: Mapping[str, Mapping[str, Any]],
                  scale: float) -> Dict[str, List[int]]:
    """Body frame -> per-position dots (0..100) for the engine. A disabled
    position is all zero; otherwise node x the position's intensity x the
    global scale."""
    try:
        scale = float(scale)
    except (TypeError, ValueError):
        scale = 0.0
    if not scale > 0.0:
        scale = 0.0
    out: Dict[str, List[int]] = {}
    for pos, n in POSITIONS:
        cfg = devices.get(pos) or {}
        vals = frame.get(pos) or (0.0,) * n
        if not cfg.get("enabled", True) or scale == 0.0:
            out[pos] = [0] * n
            continue
        try:
            intensity = max(0.0, min(100.0, float(cfg.get("intensity", 100))))
        except (TypeError, ValueError):
            intensity = 100.0
        out[pos] = [max(0, min(100, int(round(_unit(v) * intensity * min(scale, 1.0)))))
                    for v in vals[:n]] + [0] * max(0, n - len(vals))
    return out


def is_input_key(key: str) -> bool:
    """Does this parameter feed the body? (The router wakes on these; zone
    routes read OGB keys, synthetic sources anything -- the poll catches
    those.)"""
    return key in _KEYS or key.startswith(("OGB/", "VFH/"))


def detected_positions(params: Mapping[str, Any]) -> Set[str]:
    """bHaptics positions the avatar sends anything for."""
    found = set()
    for key in params:
        spec = _KEYS.get(key)
        if spec is not None and spec[0] != _OWO:
            found.add(spec[1])
    return found


def contacts_per_position(names: Iterable[str]) -> Dict[str, Tuple[int, ...]]:
    """Which nodes of each position the avatar has a contact for, in any
    schema -- the Suits page's contact check. `names` are parameter names
    (an OSC snapshot's keys, or VRChat's list of the avatar's parameters)."""
    seen: Dict[str, Set[int]] = {pos: set() for pos in NODE_COUNTS}
    for key in names:
        spec = _KEYS.get(key)
        if spec is not None and spec[0] != _OWO:
            seen[spec[1]].add(spec[2])
    return {pos: tuple(sorted(s)) for pos, s in seen.items()}


def detected_owo(params: Mapping[str, Any]) -> Set[str]:
    """OWO muscles the avatar's OWO package sends."""
    return {spec[1] for key in params
            if (spec := _KEYS.get(key)) is not None and spec[0] == _OWO}
