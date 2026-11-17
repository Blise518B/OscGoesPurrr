"""Well-known avatar parameters, in named groups -- the Add Variable
picker's filter chips (ui/osc_variable_picker.py) and the friend's YOLO
list (remote_params.settable, through BUILTINS).

Pure: no Qt, no settings file. Every name here was read off real avatars'
OSC configs (VRChat's ``OSC/<user>/Avatars/*.json``) and checked against
the projects that generate them:

  * VRChat's own -- its documented built-in parameters.
  * GoGo Loco -- everything under ``Go/``.
  * Face tracking -- VRCFaceTracking matches a parameter by its name after
    any prefix ending in ``/v2/`` (``FT/v2/JawOpen``, the older bare
    ``v2/JawOpen``, a prefab's own ``EchoFT/v2/JawOpen``), sends a float
    also as binary bits (``Name1`` ``Name2`` ``Name4`` ... ``NameNegative``),
    and still answers its v1 (SRanipal) names unprefixed; its status Bools
    end in ``TrackingActive``. OSCmooth generates everything under ``OSCm/``.
    Jerry's VRCFT templates add a few toggles of their own.
  * VRCFury internals -- the debug Bools ``VF <part>`` (AddDebugParamService),
    the Parameter Compressor's ``SyncPointer`` / ``SyncIndex<n>`` /
    ``SyncDataNum<n>`` / ``SyncDataBool<n>`` and ``<param>/LastSynced`` /
    ``<param>/Current``, the tracking conflict resolver's ``TC_...``, the
    world-scale detector's ``WSD - <name> - Rcv`` and the security lock's
    ``SecurityInput`` -- each behind VRCFury's renaming prefix (below).
  * VRCFury toggles -- VRCFury renames every parameter of a prefab that
    isn't marked global to ``VF<n>_<name>`` (UniqueParamService), toggles
    included. Shown by default (Blise's call, 2026-11-14).
  * PhysBone states -- VRChat's PhysBone suffixes.
  * ShockOSC -- everything under ``ShockOsc/`` (OpenShock's VRChat app,
    shockosc.py): hidden in the toys' pickers, listed first in the
    Shockers' (``split``'s `first`).
  * Physics assets -- Marshmallow PB (``MPB_``).
  * OGP's own (``OGP/``) and SPS (``OGB/``, ``VFH/``, ``TPS_Internal/``):
    what OGP sends, or already reads by itself.

A parameter belongs to one group at most -- the first in MATCH_ORDER that
claims it -- so the chips' counts add up and a PhysBone state on a physics
asset (``MPB_L_IsGrabbed``) is a PhysBone state, which the Shockers'
picker keeps visible. Groups that VRCFury's renaming can hide behind
(``VF12_Go/Locomotion``, ``VF3_MPB_L_Angle``) look past the ``VF<n>_``.
"""

import fnmatch
import re
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Dict, FrozenSet, Iterable, List, Mapping, Optional, Tuple

# The app setting that remembers the chips, once for every picker:
# {group key: hidden}. A group it doesn't name takes its default.
SETTING_KEY = "picker_hidden_groups"

# VRChat drives these itself: setting one over OSC does nothing, and the
# motion ones change every frame -- not worth a datagram. Never offered to
# a friend's YOLO list (remote_params.settable).
BUILTINS = frozenset({
    "IsLocal", "PreviewMode", "Viseme", "Voice", "GestureLeft", "GestureRight",
    "GestureLeftWeight", "GestureRightWeight", "AngularY", "VelocityX", "VelocityY",
    "VelocityZ", "VelocityMagnitude", "Upright", "Grounded", "Seated", "AFK",
    "TrackingType", "VRMode", "MuteSelf", "InStation", "Earmuffs", "IsOnFriendsList",
    "AvatarVersion", "IsAnimatorEnabled", "ScaleModified", "ScaleFactor",
    "ScaleFactorInverse", "EyeHeightAsMeters", "EyeHeightAsPercent",
})

# VRChat's own messages that aren't avatar parameters but land in the
# parameter store all the same (the OSC layer stores what it hears): your
# height and the world's say on it (avatar_height.py, the Avatar Remote
# page's Height box). Never a control, never in a friend's YOLO list.
NOT_PARAMETERS = frozenset({
    "avatar/eyeheight", "avatar/eyeheightmin", "avatar/eyeheightmax",
    "avatar/eyeheightscalingallowed",
})

VRCHAT = "vrchat"
GOGO = "gogo"
FACE = "face"
VRCFURY = "vrcfury"
PHYSICS = "physics"
PHYSBONES = "physbones"
OGP = "ogp"
SPS = "sps"
SHOCKOSC = "shockosc"
VF_TOGGLES = "vf_toggles"

# VRCFury's renaming prefix: "VF" + the feature's number + "_".
_VF_PREFIX = re.compile(r"VF\d+_")

# VRCFaceTracking's binary bits: a float sent as Name1, Name2, Name4 ... and
# NameNegative (BinaryBaseParameter). Longest first, so "16" wins over "6".
_BIT_SUFFIXES = ("Negative", "128", "64", "32", "16", "8", "4", "2", "1")

# VRCFaceTracking's v1 (SRanipal) names, still answered unprefixed: the eye
# and brow set (Legacy/Eye/EyeTrackingParams.cs; the gaze ones as X / Y),
# SRanipal's lip shapes and the merged ones (Legacy/Lip). Each also as bits.
_VRCFT_V1 = frozenset({
    # eyes and brows
    "EyesX", "EyesY", "LeftEyeX", "LeftEyeY", "RightEyeX", "RightEyeY",
    "LeftEyeWiden", "RightEyeWiden", "EyeWiden", "LeftEyeSqueeze", "RightEyeSqueeze",
    "EyesSqueeze", "EyesDilation", "EyesPupilDiameter", "LeftEyeLid", "RightEyeLid",
    "CombinedEyeLid", "LeftEyeLidExpanded", "RightEyeLidExpanded", "EyeLidExpanded",
    "CombinedEyeLidExpanded", "LeftEyeLidExpandedSqueeze", "RightEyeLidExpandedSqueeze",
    "EyeLidExpandedSqueeze", "CombinedEyeLidExpandedSqueeze", "LeftEyeWidenToggle",
    "RightEyeWidenToggle", "EyesWidenToggle", "LeftEyeSqueezeToggle",
    "RightEyeSqueezeToggle", "EyesSqueezeToggle", "BrowsInnerUp", "BrowInnerUpLeft",
    "BrowInnerUpRight", "BrowsOuterUp", "BrowOuterUpLeft", "BrowOuterUpRight",
    "BrowsDown", "BrowDownLeft", "BrowDownRight", "MouthRaiserLower", "MouthRaiserUpper",
    "EyesSquint", "EyeSquintLeft", "EyeSquintRight", "CheeksSquint", "CheekSquintLeft",
    "CheekSquintRight", "MouthDimple", "MouthDimpleLeft", "MouthDimpleRight",
    "MouthPress", "MouthPressLeft", "MouthPressRight", "MouthStretch",
    "MouthStretchLeft", "MouthStretchRight", "MouthTightener", "MouthTightenerLeft",
    "MouthTightenerRight", "NoseSneer", "NoseSneerLeft", "NoseSneerRight",
    # SRanipal's lip shapes
    "JawRight", "JawLeft", "JawForward", "JawOpen", "MouthApeShape", "MouthUpperRight",
    "MouthUpperLeft", "MouthLowerRight", "MouthLowerLeft", "MouthUpperOverturn",
    "MouthLowerOverturn", "MouthPout", "MouthSmileRight", "MouthSmileLeft",
    "MouthSadRight", "MouthSadLeft", "CheekPuffRight", "CheekPuffLeft", "CheekSuck",
    "MouthUpperUpRight", "MouthUpperUpLeft", "MouthLowerDownRight", "MouthLowerDownLeft",
    "MouthUpperInside", "MouthLowerInside", "MouthLowerOverlay", "TongueLongStep1",
    "TongueLongStep2", "TongueDown", "TongueUp", "TongueRight", "TongueLeft",
    "TongueRoll", "TongueUpLeftMorph", "TongueUpRightMorph", "TongueDownLeftMorph",
    "TongueDownRightMorph",
    # merged lip shapes
    "JawX", "MouthUpper", "MouthLower", "MouthX", "SmileSadRight", "SmileSadLeft",
    "SmileSad", "TongueY", "TongueX", "PuffSuckRight", "PuffSuckLeft", "PuffSuck",
    "JawOpenApe", "JawOpenPuff", "JawOpenPuffRight", "JawOpenPuffLeft", "JawOpenSuck",
    "JawOpenForward", "JawOpenOverlay", "MouthUpperUpRightUpperInside",
    "MouthUpperUpRightPuffRight", "MouthUpperUpRightApe", "MouthUpperUpRightPout",
    "MouthUpperUpRightOverlay", "MouthUpperUpRightSuck", "MouthUpperUpLeftUpperInside",
    "MouthUpperUpLeftPuffLeft", "MouthUpperUpLeftApe", "MouthUpperUpLeftPout",
    "MouthUpperUpLeftOverlay", "MouthUpperUpLeftSuck", "MouthUpperUpUpperInside",
    "MouthUpperUpInside", "MouthUpperUpPuff", "MouthUpperUpPuffLeft",
    "MouthUpperUpPuffRight", "MouthUpperUpApe", "MouthUpperUpPout",
    "MouthUpperUpOverlay", "MouthUpperUpSuck", "MouthLowerDownRightLowerInside",
    "MouthLowerDownRightPuffRight", "MouthLowerDownRightApe", "MouthLowerDownRightPout",
    "MouthLowerDownRightOverlay", "MouthLowerDownRightSuck",
    "MouthLowerDownLeftLowerInside", "MouthLowerDownLeftPuffLeft",
    "MouthLowerDownLeftApe", "MouthLowerDownLeftPout", "MouthLowerDownLeftOverlay",
    "MouthLowerDownLeftSuck", "MouthLowerDownLowerInside", "MouthLowerDownInside",
    "MouthLowerDownPuff", "MouthLowerDownPuffLeft", "MouthLowerDownPuffRight",
    "MouthLowerDownApe", "MouthLowerDownPout", "MouthLowerDownOverlay",
    "MouthLowerDownSuck", "MouthUpperInsideOverturn", "MouthLowerInsideOverturn",
    "SmileRightUpperOverturn", "SmileRightLowerOverturn", "SmileRightOverturn",
    "SmileRightApe", "SmileRightOverlay", "SmileRightPout", "SmileLeftUpperOverturn",
    "SmileLeftLowerOverturn", "SmileLeftOverturn", "SmileLeftApe", "SmileLeftOverlay",
    "SmileLeftPout", "SmileUpperOverturn", "SmileLowerOverturn", "SmileOverturn",
    "SmileApe", "SmileOverlay", "SmilePout", "PuffRightUpperOverturn",
    "PuffRightLowerOverturn", "PuffRightOverturn", "PuffLeftUpperOverturn",
    "PuffLeftLowerOverturn", "PuffLeftOverturn", "PuffUpperOverturn",
    "PuffLowerOverturn", "PuffOverturn", "TongueSteps",
})

# Face-tracking toggles that aren't VRCFaceTracking's own: Jerry's VRCFT
# templates (the first four), and ones seen next to face tracking on real
# avatars from prefabs whose source isn't public.
_FT_TOGGLES = frozenset({
    "VisemesEnable", "EyeDilationEnable", "FacialExpressionsDisabled",
    "State/TrackingActive", "State/VisemesEnable",
    "EyePuppetActive", "TonguePuppetActive", "EyeDilationActive",
    "EyeLocalSmoothness", "FaceLocalSmoothness", "UserEyeTracking", "UserFaceTracking",
})


@dataclass(frozen=True)
class Group:
    """One chip. A name is in it when the name (or, with `under_vf`, the
    name past VRCFury's ``VF<n>_``) is one of `exact`, starts with one of
    `prefixes`, ends with one of `suffixes`, contains one of `contains`, or
    is a name in `bits` -- as it is or with a binary-bit suffix. `vf_prefixes` /
    `vf_suffixes` match only past a ``VF<n>_``; `vf_any` takes every
    ``VF<n>_`` name no group before it claimed."""
    key: str
    label: str
    tip: str
    hidden_by_default: bool = True
    exact: FrozenSet[str] = frozenset()
    prefixes: Tuple[str, ...] = ()
    suffixes: Tuple[str, ...] = ()
    contains: Tuple[str, ...] = ()
    bits: FrozenSet[str] = frozenset()
    under_vf: bool = False
    vf_prefixes: Tuple[str, ...] = ()
    vf_suffixes: Tuple[str, ...] = ()
    vf_any: bool = False

    def _plain(self, name: str) -> bool:
        if name in self.exact or name in self.bits:
            return True
        if self.prefixes and name.startswith(self.prefixes):
            return True
        if self.suffixes and name.endswith(self.suffixes):
            return True
        if any(c in name for c in self.contains):
            return True
        if self.bits:
            for s in _BIT_SUFFIXES:
                if name.endswith(s) and name[:-len(s)] in self.bits:
                    return True
        return False

    def matches(self, name: str) -> bool:
        if self._plain(name):
            return True
        m = _VF_PREFIX.match(name)
        if m is None:
            return False
        rest = name[m.end():]
        if self.vf_any:
            return True
        if self.vf_prefixes and rest.startswith(self.vf_prefixes):
            return True
        if self.vf_suffixes and rest.endswith(self.vf_suffixes):
            return True
        return self.under_vf and self._plain(rest)


# In the order the chips show.
GROUPS: Tuple[Group, ...] = (
    Group(VRCHAT, "VRChat's own",
          "Parameters VRChat drives itself: gestures, voice, movement, AFK, scale "
          "and the like.",
          exact=BUILTINS | NOT_PARAMETERS),
    Group(GOGO, "GoGo Loco",
          "GoGo Loco's locomotion parameters (Go/...): poses, flying, height.",
          prefixes=("Go/",), under_vf=True),
    Group(FACE, "Face tracking",
          "Face tracking: VRCFaceTracking's parameters (FT/v2/..., v2/..., their "
          "binary bits, the v1 names, ...TrackingActive) and OSCmooth's (OSCm/...).",
          prefixes=("v2/", "OSCm/", "OSCm_"), contains=("/v2/",),
          suffixes=("TrackingActive",), exact=_FT_TOGGLES, bits=_VRCFT_V1,
          under_vf=True),
    Group(VRCFURY, "VRCFury internals",
          "What VRCFury builds for itself: its Parameter Compressor's sync "
          "parameters, the tracking resolver's TC_..., world-scale detection, "
          "its \"VF ...\" debug parameters.",
          prefixes=("VF ",),
          vf_prefixes=("TC_", "SyncPointer", "SyncIndex", "SyncData", "WSD - ",
                       "SecurityInput"),
          vf_suffixes=("/LastSynced", "/Current")),
    Group(PHYSICS, "Physics assets",
          "Physics assets' own parameters: Marshmallow PB (MPB_...).",
          prefixes=("MPB_",), under_vf=True),
    Group(PHYSBONES, "PhysBone states",
          "Every PhysBone's state: ..._IsGrabbed, _IsPosed, _Angle, _Stretch, _Squish.",
          suffixes=("_IsGrabbed", "_IsPosed", "_Angle", "_Stretch", "_Squish"),
          under_vf=True),
    Group(SHOCKOSC, "ShockOSC",
          "ShockOSC's parameters (ShockOsc/...): the contacts, PhysBones and "
          "feedback an avatar set up for OpenShock's VRChat app uses.",
          prefixes=("ShockOsc/",)),
    Group(OGP, "OGP's own",
          "The parameters OGP sends your avatar itself (OGP/...).",
          prefixes=("OGP/",)),
    Group(SPS, "SPS",
          "SPS and TPS plumbing OGP already reads by itself (OGB/..., VFH/..., "
          "TPS_Internal/...).",
          prefixes=("OGB/", "VFH/", "TPS_Internal/"), exact=frozenset({"OGB_ENABLED"})),
    Group(VF_TOGGLES, "VRCFury toggles",
          "Parameters VRCFury renamed to VF<number>_..., your toggles among them. "
          "Shown unless you light this chip.",
          hidden_by_default=False, vf_any=True),
)

GROUP_KEYS: Tuple[str, ...] = tuple(g.key for g in GROUPS)
BY_KEY: Dict[str, Group] = {g.key: g for g in GROUPS}

# Which group claims a name first. The specific ones go before the broad
# ones: VRCFury's internals before the groups that look past VF<n>_,
# PhysBone states before physics assets (so the Shockers' picker keeps
# MPB_L_IsGrabbed), ShockOSC before PhysBone states (ShockOsc/Tail_Stretch
# is ShockOSC's), and VRCFury's toggles last.
MATCH_ORDER: Tuple[str, ...] = (VRCHAT, OGP, SPS, SHOCKOSC, VRCFURY, GOGO, FACE,
                                PHYSBONES, PHYSICS, VF_TOGGLES)
_ORDERED = tuple(BY_KEY[k] for k in MATCH_ORDER)
assert set(MATCH_ORDER) == set(GROUP_KEYS)


@lru_cache(maxsize=16384)
def group_of(name: str) -> Optional[str]:
    """The key of the group a parameter belongs to, or None. Cached: the
    picker asks again for every name on each refresh."""
    for g in _ORDERED:
        if g.matches(name):
            return g.key
    return None


def default_hidden() -> FrozenSet[str]:
    return frozenset(g.key for g in GROUPS if g.hidden_by_default)


def hidden_from_setting(saved: object) -> FrozenSet[str]:
    """The groups hidden, from the app setting (``{key: hidden}``; anything
    else, or a group it doesn't name, falls back to the defaults)."""
    saved = saved if isinstance(saved, Mapping) else {}
    out = set()
    for g in GROUPS:
        v = saved.get(g.key)
        if (bool(v) if isinstance(v, bool) else g.hidden_by_default):
            out.add(g.key)
    return frozenset(out)


def setting_from_hidden(hidden: Iterable[str]) -> Dict[str, bool]:
    """What the app setting stores for a set of hidden groups: every group,
    so a later change of default never flips a chip someone set."""
    hidden = set(hidden)
    return {g.key: g.key in hidden for g in GROUPS}


def mapped_matcher(mapped: Iterable[str]):
    """``fn(name) -> bool``: whether a parameter is one of `mapped` -- bare
    names, or globs (``OGB/Tail/*``) matched like the router matches them
    (motor_router: fnmatch, case-insensitive)."""
    literals, globs = set(), []
    for m in mapped or ():
        m = str(m or "").strip()
        if m.startswith("/avatar/parameters/"):
            m = m[len("/avatar/parameters/"):]
        m = m.lstrip("/")
        if not m:
            continue
        if any(c in m for c in "*?["):
            globs.append(fnmatch.translate(m))
        else:
            literals.add(m)
    glob_re = None
    if globs:
        try:
            glob_re = re.compile("|".join(globs), re.IGNORECASE)
        except re.error:
            glob_re = None

    def is_mapped(name: str) -> bool:
        return name in literals or (glob_re is not None and glob_re.match(name) is not None)
    return is_mapped


@dataclass
class Split:
    """The picker's list: `shown` (matching the search), `hidden` (hidden by
    the filters and matching the search -- only while searching), and how
    many parameters each group has (every name, searched or not). `first`:
    the groups this picker lists before everything else, each as (key,
    its names matching the search) -- only those with a name."""
    shown: List[str]
    hidden: List[str]
    counts: Dict[str, int]
    first: List[Tuple[str, List[str]]] = field(default_factory=list)


def split(names: Iterable[str], hidden: Iterable[str], *, mapped: Iterable[str] = (),
          keep: Iterable[str] = (), first: Iterable[str] = (), query: str = "") -> Split:
    """Sort a picker's parameters into shown and hidden. A parameter is
    hidden when its group is in `hidden` and not in `keep` (groups this
    picker always shows); one that is `mapped` is never hidden. A group in
    `first` is never hidden either, and its names go to `Split.first`
    instead of `shown` (the Shockers' picker: ShockOSC's before the rest).
    `query` (case-insensitive, substring) narrows every list; with no query
    the hidden ones aren't listed at all."""
    first = tuple(dict.fromkeys(first))
    hide = set(hidden) - set(keep) - set(first)
    is_mapped = mapped_matcher(mapped)
    q = (query or "").strip().lower()
    shown, gone = [], []
    top: Dict[str, List[str]] = {k: [] for k in first}
    counts = {k: 0 for k in GROUP_KEYS}
    for name in sorted(names):
        key = group_of(name)
        if key is not None:
            counts[key] += 1
        hit = not q or q in name.lower()
        if key in top:
            if hit:
                top[key].append(name)
        elif key in hide and not is_mapped(name):
            if q and hit:
                gone.append(name)
        elif hit:
            shown.append(name)
    return Split(shown, gone, counts, [(k, top[k]) for k in first if top[k]])
