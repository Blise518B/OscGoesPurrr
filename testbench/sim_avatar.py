"""Avatar parameter schemas for the VRChat simulator.

Defines a small library of fake avatars and helpers that build the
OSCQuery JSON tree the way real VRChat builds it. The simulator's
network layer serves the tree at `/avatar/parameters` so OscGoesPurrr
sees exactly what it would see talking to a live VRChat client.

The schemas mirror what `motor_router.py` and `bhaptics_router.py`
look for:

OGB / SPS (OscGoesBrrr-compat) parameters — matches a current SPS avatar
exported via VRCFury Haptics (verified against a real avatar's OSC config):
    OGB/Orf/<name>/TouchSelf            (f)
    OGB/Orf/<name>/TouchSelfClose       (T/F)
    OGB/Orf/<name>/TouchOthers          (f)
    OGB/Orf/<name>/TouchOthersClose     (T/F)
    OGB/Orf/<name>/PenSelfNewRoot       (f)
    OGB/Orf/<name>/PenSelfNewTip        (f)
    OGB/Orf/<name>/PenOthers            (f)
    OGB/Orf/<name>/PenOthersClose       (T/F)
    OGB/Orf/<name>/PenOthersNewRoot     (f)
    OGB/Orf/<name>/PenOthersNewTip      (f)
    OGB/Orf/<name>/FrotOthers           (f)
        (current full orifices carry no plain PenSelf / PenSelfClose — depth
         is reported via the New Root/Tip pair instead)
    OGB/Pen/<name>/TouchSelf            (f)
    OGB/Pen/<name>/TouchSelfClose       (T/F)
    OGB/Pen/<name>/TouchOthers          (f)
    OGB/Pen/<name>/TouchOthersClose     (T/F)
    OGB/Pen/<name>/PenSelf              (f)
    OGB/Pen/<name>/PenOthers            (f)
    OGB/Pen/<name>/FrotOthers           (f)
    OGB/Pen/<name>/FrotOthersClose      (T/F)
    VFH/Version/10                      (T/F)   # SPS/VRCFury haptics version

bHaptics OSC v1 (HerpDerpinstine schema, per dot):
    bHaptics_<Slot>_<N>_bool            (T/F)   # N is 1-based
where Slot is one of:
    Head, Vest_Front, Vest_Back, Arm_Left, Arm_Right,
    Hand_Left, Hand_Right, Foot_Left, Foot_Right
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Tuple, Any


# OSCQuery TYPE codes (per the spec): f=float32, i=int32, s=string,
# T=true, F=false. OGP also accepts 'T'/'F' for bools.
TYPE_FLOAT = "f"
TYPE_BOOL = "T"      # OSCQuery uses T/F as the type code for booleans
TYPE_STRING = "s"
TYPE_INT = "i"


# VRCFury Haptics version marker advertised by current SPS avatars: a bool
# parameter named VFH/Version/<N> (always true) where N is the haptics schema
# version. OSC Goes Brrr and similar apps read N to tell a current avatar from
# an outdated one — an avatar with no VFH/Version reads as "outdated SPS". 10
# is the current version (verified against a real avatar's OSC config, 2026-06).
SPS_VERSION_PARAM = "VFH/Version/10"


# (position, v1_slot, node_count) — mirrors bhaptics_router._DEVICE_TABLE so
# the simulator's bHaptics dots match what the real router subscribes to.
BHAPTICS_DEVICES: List[Tuple[str, str, int]] = [
    ("Head",       "Head",        6),
    ("VestFront",  "Vest_Front",  20),
    ("VestBack",   "Vest_Back",   20),
    ("ForearmL",   "Arm_Left",    6),
    ("ForearmR",   "Arm_Right",   6),
    ("HandL",      "Hand_Left",   3),
    ("HandR",      "Hand_Right",  3),
    ("FootL",      "Foot_Left",   3),
    ("FootR",      "Foot_Right",  3),
]


@dataclass
class SPSZone:
    """One OGB SPS zone — either an orifice or a penetrator."""
    name: str
    kind: str  # "Orf" or "Pen"


@dataclass
class AvatarPreset:
    avatar_id: str
    display_name: str
    sps_zones: List[SPSZone] = field(default_factory=list)
    bhaptics_positions: List[str] = field(default_factory=list)


# A handful of preset avatars covering the common test cases.
# All ids use a fake but well-formed avtr_ UUID so OGP's avatar-binding
# logic treats them as distinct identities.
AVATAR_PRESETS: List[AvatarPreset] = [
    AvatarPreset(
        avatar_id="avtr_11111111-1111-1111-1111-111111111111",
        display_name="Full Test (SPS + bHaptics)",
        sps_zones=[
            SPSZone("Mouth", "Orf"),
            SPSZone("Pussy", "Orf"),
            SPSZone("Butt", "Orf"),
            SPSZone("PenisShaft", "Pen"),
            SPSZone("PenisTip", "Pen"),
        ],
        bhaptics_positions=[pos for pos, _, _ in BHAPTICS_DEVICES],
    ),
    AvatarPreset(
        avatar_id="avtr_22222222-2222-2222-2222-222222222222",
        display_name="Pussy Only",
        sps_zones=[SPSZone("Pussy", "Orf")],
    ),
    AvatarPreset(
        avatar_id="avtr_33333333-3333-3333-3333-333333333333",
        display_name="Penis Only",
        sps_zones=[SPSZone("PenisShaft", "Pen")],
    ),
    AvatarPreset(
        avatar_id="avtr_44444444-4444-4444-4444-444444444444",
        display_name="bHaptics Vest Only",
        bhaptics_positions=["VestFront", "VestBack"],
    ),
    AvatarPreset(
        avatar_id="avtr_55555555-5555-5555-5555-555555555555",
        display_name="Empty Avatar (base VRChat only)",
    ),
]


# Base VRChat built-ins that any real avatar exposes. The simulator
# advertises a small subset so OGP's OSC Inspector shows the kind of
# noise a real session has. None of these are used by the router, but
# seeing them in the inspector is what makes the simulator feel real.
_BASE_VRCHAT_PARAMS: Dict[str, Tuple[str, Any]] = {
    "Voice":         (TYPE_FLOAT,  0.0),
    "VelocityX":     (TYPE_FLOAT,  0.0),
    "VelocityY":     (TYPE_FLOAT,  0.0),
    "VelocityZ":     (TYPE_FLOAT,  0.0),
    "Upright":       (TYPE_FLOAT,  1.0),
    "Grounded":      (TYPE_BOOL,   True),
    "Seated":        (TYPE_BOOL,   False),
    "AFK":           (TYPE_BOOL,   False),
    "MuteSelf":      (TYPE_BOOL,   False),
    "InStation":     (TYPE_BOOL,   False),
    "IsLocal":       (TYPE_BOOL,   True),
    "GestureLeft":   (TYPE_INT,    0),
    "GestureRight":  (TYPE_INT,    0),
    "Viseme":        (TYPE_INT,    0),
}


def _orifice_params(name: str) -> Dict[str, Tuple[str, Any]]:
    p = f"OGB/Orf/{name}"
    # Mirrors a current full SPS orifice: depth via the New Root/Tip pair (no
    # plain PenSelf/PenSelfClose), plus touch/frot and their Close gates.
    return {
        f"{p}/TouchSelf":         (TYPE_FLOAT, 0.0),
        f"{p}/TouchSelfClose":    (TYPE_BOOL,  False),
        f"{p}/TouchOthers":       (TYPE_FLOAT, 0.0),
        f"{p}/TouchOthersClose":  (TYPE_BOOL,  False),
        f"{p}/PenSelfNewRoot":    (TYPE_FLOAT, 0.0),
        f"{p}/PenSelfNewTip":     (TYPE_FLOAT, 0.0),
        f"{p}/PenOthers":         (TYPE_FLOAT, 0.0),
        f"{p}/PenOthersClose":    (TYPE_BOOL,  False),
        f"{p}/PenOthersNewRoot":  (TYPE_FLOAT, 0.0),
        f"{p}/PenOthersNewTip":   (TYPE_FLOAT, 0.0),
        f"{p}/FrotOthers":        (TYPE_FLOAT, 0.0),
    }


def _penetrator_params(name: str) -> Dict[str, Tuple[str, Any]]:
    p = f"OGB/Pen/{name}"
    # Mirrors a current SPS penetrator: touch/frot with their Close gates,
    # plus self/others depth floats.
    return {
        f"{p}/TouchSelf":         (TYPE_FLOAT, 0.0),
        f"{p}/TouchSelfClose":    (TYPE_BOOL,  False),
        f"{p}/TouchOthers":       (TYPE_FLOAT, 0.0),
        f"{p}/TouchOthersClose":  (TYPE_BOOL,  False),
        f"{p}/PenSelf":           (TYPE_FLOAT, 0.0),
        f"{p}/PenOthers":         (TYPE_FLOAT, 0.0),
        f"{p}/FrotOthers":        (TYPE_FLOAT, 0.0),
        f"{p}/FrotOthersClose":   (TYPE_BOOL,  False),
    }


def _bhaptics_params(positions: List[str]) -> Dict[str, Tuple[str, Any]]:
    """Build the full bool grid for every requested bHaptics position."""
    out: Dict[str, Tuple[str, Any]] = {}
    by_position = {pos: (slot, count) for pos, slot, count in BHAPTICS_DEVICES}
    for pos in positions:
        if pos not in by_position:
            continue
        slot, count = by_position[pos]
        for n in range(1, count + 1):
            out[f"bHaptics_{slot}_{n}_bool"] = (TYPE_BOOL, False)
    return out


def build_params(preset: AvatarPreset) -> Dict[str, Tuple[str, Any]]:
    """Return the full {short_name: (type, value)} map for an avatar preset.

    Short_name is the parameter name without the `/avatar/parameters/`
    prefix — same form `parameter_store` uses as its dict key. The
    network layer adds the prefix when serving OSCQuery / sending UDP.
    """
    params: Dict[str, Tuple[str, Any]] = {}
    params.update(_BASE_VRCHAT_PARAMS)
    for zone in preset.sps_zones:
        if zone.kind == "Orf":
            params.update(_orifice_params(zone.name))
        elif zone.kind == "Pen":
            params.update(_penetrator_params(zone.name))
    # Stamp the SPS version marker iff the avatar actually has SPS zones, so
    # apps (e.g. OSC Goes Brrr) recognise it as a current avatar rather than
    # flagging it as an outdated-SPS export.
    if preset.sps_zones:
        params[SPS_VERSION_PARAM] = (TYPE_BOOL, True)
    params.update(_bhaptics_params(preset.bhaptics_positions))
    return params


# ---------------------------------------------------------------------------
# OSCQuery tree builder
# ---------------------------------------------------------------------------

_AVATAR_PARAM_PREFIX = "avatar/parameters"


def _insert_path(root: Dict[str, Any], full_path: str, type_code: str, value: Any) -> None:
    """Insert one leaf into a nested OSCQuery tree, building intermediate
    CONTENTS dictionaries as needed. `full_path` is the absolute OSC path
    starting with a leading slash (e.g. `/avatar/parameters/OGB/Orf/Pussy/TouchSelf`).
    """
    parts = [p for p in full_path.split("/") if p]
    node = root
    walked: List[str] = []
    for i, part in enumerate(parts):
        walked.append(part)
        contents = node.setdefault("CONTENTS", {})
        child = contents.get(part)
        if child is None:
            child = {"FULL_PATH": "/" + "/".join(walked)}
            contents[part] = child
        is_leaf = (i == len(parts) - 1)
        if is_leaf:
            child["TYPE"] = type_code
            child["ACCESS"] = 3  # read+write — what VRChat uses for avatar params
            child["VALUE"] = [_coerce_value(value, type_code)]
        node = child


def _coerce_value(value: Any, type_code: str) -> Any:
    """OSCQuery wraps each leaf value in a one-element list. The element's
    Python type should match the declared TYPE so the JSON looks like the
    real thing (floats stay floats, bools stay bools, etc.)."""
    if type_code == TYPE_FLOAT:
        try:
            return float(value)
        except (TypeError, ValueError):
            return 0.0
    if type_code == TYPE_INT:
        try:
            return int(value)
        except (TypeError, ValueError):
            return 0
    if type_code == TYPE_BOOL:
        return bool(value)
    if type_code == TYPE_STRING:
        return str(value)
    return value


def build_oscquery_root(
    name: str,
    osc_ip: str,
    osc_port: int,
    avatar_id: str,
    params: Dict[str, Tuple[str, Any]],
) -> Dict[str, Any]:
    """Build the full root OSCQuery JSON document served at GET /.

    The tree includes `/avatar/change` (the string avatar id) and
    `/avatar/parameters/<short_name>` for every entry in `params`.
    """
    root: Dict[str, Any] = {
        "NAME": name,
        "OSC_IP": osc_ip,
        "OSC_PORT": osc_port,
        "OSC_TRANSPORT": "UDP",
    }
    _insert_path(root, "/avatar/change", TYPE_STRING, avatar_id)
    for short_name, (type_code, value) in params.items():
        _insert_path(root, f"/{_AVATAR_PARAM_PREFIX}/{short_name}", type_code, value)
    return root


def get_subtree(root: Dict[str, Any], path: str) -> Dict[str, Any] | None:
    """Walk the OSCQuery tree to the node at `path` (e.g. `/avatar/parameters`
    or `/avatar/change`). Returns None if no such node exists."""
    parts = [p for p in path.split("/") if p]
    node = root
    for part in parts:
        contents = node.get("CONTENTS")
        if not isinstance(contents, dict):
            return None
        child = contents.get(part)
        if child is None:
            return None
        node = child
    return node


def update_value(root: Dict[str, Any], full_path: str, value: Any) -> bool:
    """Mutate a leaf's VALUE in-place. Returns True if the leaf was found.

    `full_path` is the absolute OSC path (with leading slash). The tree
    is expected to already contain the leaf — call `_insert_path` first
    if you're adding a brand-new parameter mid-session.
    """
    node = get_subtree(root, full_path)
    if node is None or "TYPE" not in node:
        return False
    node["VALUE"] = [_coerce_value(value, node["TYPE"])]
    return True


def preset_by_id(avatar_id: str) -> AvatarPreset | None:
    for p in AVATAR_PRESETS:
        if p.avatar_id == avatar_id:
            return p
    return None
