"""ShockOSC's avatar parameters -- the interface, never its code.

ShockOSC (OpenShock's VRChat app, github.com/OpenShock/ShockOSC, AGPL-3.0)
drives shockers from avatar parameters named ``ShockOsc/<Group><suffix>``,
so an avatar set up for it already carries them. OGP reads the same names
(Blise's friends, 2026-11-14): the Shockers' picker lists them first, the
page sets them up as behaviours in one click, the avatar's ShockOSC
settings and those behaviours' values are one value each, kept in step
both ways (shockosc_sync.py; Blise's call 2026-11-16), and
shockosc_feedback.py sends ShockOSC's feedback parameters back. The names
and what they mean were read from ShockOSC's source (3.2.0, branch
``develop`` at 97e4b47, 2026-11-11); parameter names are an interface,
and nothing of its code is here.

The names (case matters for everything but the group, which ShockOSC
matches case-insensitively):

  * ``ShockOsc/<Group>`` (bool) -- a touch: a shock once it has been held
    for the hold time (250 ms by default); let go sooner, nothing.
  * ``_IShock`` / ``_IVibrate`` / ``_ISound`` (bool) -- that action at once.
  * ``_CShock`` / ``_CVibrate`` / ``_CSound`` (float 0-1) -- continuous, the
    strength following the value; 0 stops.
  * ``_IsGrabbed`` / ``_Stretch`` -- a PhysBone's (its parameter set to
    ``ShockOsc/<Group>``): vibrates while held, and a let-go with any
    stretch shocks, the strength from the stretch at the let-go.
  * ``_NextIntensity`` (0-1 = 0-100 %) / ``_NextDuration`` (0-1 of the
    length) -- the next action's strength and length; 0 means unset.
  * ``ShockOsc/_All...`` -- the group of every shocker, always there.
  * ``ShockOsc/_Config/_All/<Setting>`` and ``_Config/<Group>/<Setting>`` --
    ShockOSC's settings, which it writes to the avatar (CONFIG below).
  * Sent back to the avatar: ``<Group>_Active`` / ``_Cooldown`` (bool),
    ``_CooldownPercentage`` / ``_DurationRemaining`` / ``_Intensity``
    (float 0-1), per group and as ``ShockOsc/_Any_...`` (FEEDBACK).

A name is split the way ShockOSC splits it: at its last underscore -- a
group name never has one (ShockOSC refuses it), and ``_All`` / ``_Any``
begin with one. Pure: no Qt, no settings, no store.
"""

import math
import re
from dataclasses import dataclass, field
from typing import Any, Dict, FrozenSet, Iterable, List, Mapping, Optional, Sequence, Set, Tuple

PREFIX = "ShockOsc/"
ALL = "_All"            # every shocker -- ShockOSC always has this group
ANY = "_Any"            # feedback only: across every group
CONFIG = "_Config/"

# what a group's parameter does, by its suffix
TOUCH = ""
I_SHOCK, I_VIBRATE, I_SOUND = "IShock", "IVibrate", "ISound"
C_SHOCK, C_VIBRATE, C_SOUND = "CShock", "CVibrate", "CSound"
IS_GRABBED, STRETCH = "IsGrabbed", "Stretch"
NEXT_INTENSITY, NEXT_DURATION = "NextIntensity", "NextDuration"
INPUTS: Tuple[str, ...] = (TOUCH, I_SHOCK, I_VIBRATE, I_SOUND, C_SHOCK, C_VIBRATE,
                           C_SOUND, IS_GRABBED, STRETCH, NEXT_INTENSITY, NEXT_DURATION)
# sent back: per group and as _Any
ACTIVE, COOLDOWN = "Active", "Cooldown"
COOLDOWN_PCT, DURATION_LEFT, INTENSITY = "CooldownPercentage", "DurationRemaining", "Intensity"
FEEDBACK: Tuple[str, ...] = (ACTIVE, COOLDOWN, COOLDOWN_PCT, DURATION_LEFT, INTENSITY)
KNOWN: FrozenSet[str] = frozenset(INPUTS + FEEDBACK)

# The op each instant / continuous suffix sends (OGP's names for them).
INSTANT_OPS = {I_SHOCK: "shock", I_VIBRATE: "vibrate", I_SOUND: "beep"}
CONTINUOUS_OPS = {C_SHOCK: "shock", C_VIBRATE: "vibrate", C_SOUND: "beep"}
# what a setup makes of a group: these suffixes are behaviours
SETUP_INPUTS: Tuple[str, ...] = (TOUCH, I_SHOCK, I_VIBRATE, I_SOUND, C_SHOCK, C_VIBRATE,
                                 C_SOUND, IS_GRABBED)



def split(name: str) -> Optional[Tuple[str, str]]:
    """``(group, suffix)`` for a ShockOSC parameter -- the bare name, or
    with ``/avatar/parameters/`` -- split the way ShockOSC does; None for
    anything else: not under ``ShockOsc/``, a ``_Config/`` setting, an
    empty group, or a suffix ShockOSC doesn't know (a PhysBone's
    ``_Angle``, ``_IsPosed``, ``_Squish``)."""
    name = str(name or "")
    if name.startswith("/avatar/parameters/"):
        name = name[len("/avatar/parameters/"):]
    if not name.startswith(PREFIX):
        return None
    rest = name[len(PREFIX):]
    if not rest or rest.startswith(CONFIG):
        return None
    cut = rest.rfind("_")
    group, suffix = (rest[:cut], rest[cut + 1:]) if cut > 0 else (rest, TOUCH)
    if not group or suffix not in KNOWN:
        return None
    return group, suffix


def param(group: str, suffix: str = TOUCH) -> str:
    """The parameter name for a group's suffix."""
    return f"{PREFIX}{group}" + (f"_{suffix}" if suffix else "")


def config_param(group: str, setting: str) -> str:
    return f"{PREFIX}{CONFIG}{group}/{setting}"


def group_key(group: str) -> str:
    """A group's identity: ShockOSC matches group names case-insensitively."""
    return str(group).casefold()


def label(group: str) -> str:
    """How the page names a group: ``_All`` is every shocker."""
    return "All shockers" if group_key(group) == group_key(ALL) else group


def _norm(text: str) -> str:
    return re.sub(r"[\s_\-]+", "", str(text or "")).casefold()


def suggested_shockers(group: str, shockers: Sequence[Tuple[int, str]]):
    """Whom a group drives until something is dropped on it: ``_All`` every
    shocker, a group the shocker with its name (spaces, dashes and case
    aside) -- else nobody (``[]``)."""
    if group_key(group) == group_key(ALL):
        return "all"
    want = _norm(group)
    return [sid for sid, name in shockers if want and _norm(name) == want][:1]


# ---- what an avatar has -------------------------------------------------------

def groups_on_avatar(names: Iterable[str]) -> Dict[str, FrozenSet[str]]:
    """The groups an avatar's parameters drive, each with its input
    suffixes (``TOUCH`` for the bare name) -- groups with only feedback,
    and ``_Any``, aren't in it. Keyed by the name as the avatar spells it
    (the first spelling, when two differ only in case)."""
    found: Dict[str, Set[str]] = {}
    spelling: Dict[str, str] = {}
    for name in sorted(names or ()):
        parts = split(name)
        if parts is None:
            continue
        group, suffix = parts
        if suffix not in INPUTS or group_key(group) == group_key(ANY):
            continue
        key = group_key(group)
        found.setdefault(spelling.setdefault(key, group), set()).add(suffix)
    return {g: frozenset(s) for g, s in found.items()}


def feedback_groups_on_avatar(names: Iterable[str]) -> FrozenSet[str]:
    """The groups whose feedback the avatar has a parameter for (``_Any``
    included) -- what it would light up."""
    out = set()
    for name in names or ():
        parts = split(name)
        if parts is not None and parts[1] in FEEDBACK:
            out.add(parts[0])
    return frozenset(out)


def has_shockosc(names: Iterable[str]) -> bool:
    return any(str(n).startswith(PREFIX) for n in names or ())


# ---- the one-click setup ----------------------------------------------------------

# A touch (``ShockOsc/<Group>``) shocks only once it has been held this long,
# so a brush does nothing: ShockOSC's own hold time, kept for its touches
# where everything else starts with the page's values (Blise's call,
# 2026-11-17). The avatar's HoldTime still sets it (shockosc_sync).
TOUCH_HOLD_MS = 250

def planned_rules(group: str, inputs: Iterable[str], shockers,
                  defaults: Mapping[str, Mapping[str, Any]]) -> List[Tuple[str, Dict[str, Any]]]:
    """``(kind, rule)`` for each behaviour a group's parameters become:
    the touch a Contact (a shock, once touched), ``_IShock`` / ``_IVibrate``
    / ``_ISound`` a Contact that pulses once with that action, ``_CShock`` /
    ``_CVibrate`` / ``_CSound`` a Continuous, a PhysBone (``_IsGrabbed``) a
    Pull. Every one drives `shockers` and starts with `defaults` -- kind ->
    the values a new behaviour of that kind starts with on the Shockers page
    (settings.pishock.new_rule_values: one source, Blise's call 2026-11-16) --
    except the touch's *Touch for at least*, ShockOSC's TOUCH_HOLD_MS."""
    inputs = set(inputs or ())
    name = label(group)
    targets = shockers if shockers == "all" else list(shockers or [])
    out: List[Tuple[str, Dict[str, Any]]] = []

    def made(kind: str, **own) -> Tuple[str, Dict[str, Any]]:
        return kind, {**dict(defaults.get(kind) or {}), **own, "shockers": targets}

    if TOUCH in inputs:
        out.append(made("triggers", name=f"{name} · touch", param=param(group),
                        mode="pulse", op="shock", hold_ms=TOUCH_HOLD_MS))
    for suffix, op in INSTANT_OPS.items():
        if suffix in inputs:
            out.append(made("triggers", name=f"{name} · {op} at once",
                            param=param(group, suffix), mode="pulse", op=op))
    for suffix, op in CONTINUOUS_OPS.items():
        if suffix in inputs:
            out.append(made("continuous", name=f"{name} · continuous {op}",
                            param=param(group, suffix), op=op))
    if IS_GRABBED in inputs:
        out.append(made("pulls", name=name, param=param(group)))
    return out


def rule_params(rules: Mapping[str, Sequence[Mapping[str, Any]]]) -> Set[Tuple[str, str]]:
    """``(kind, parameter)`` of every behaviour there is -- a Touch zone's
    contacts count as Contacts."""
    out = set()
    for kind, listed in (rules or {}).items():
        for r in listed or ():
            if kind == "zones":
                out.update(("triggers", z.get("param", "")) for z in r.get("zones") or ())
            else:
                out.add((kind, r.get("param", "")))
    return out


def missing_rules(plan: Iterable[Tuple[str, Dict[str, Any]]],
                  rules: Mapping[str, Sequence[Mapping[str, Any]]]) -> List[Tuple[str, Dict[str, Any]]]:
    """The planned behaviours not there yet -- one of the same kind on the
    same parameter already is (set up before, or by hand), so a second
    setup adds nothing."""
    have = rule_params(rules)
    out = []
    for kind, rule in plan:
        if (kind, rule["param"]) not in have:
            have.add((kind, rule["param"]))
            out.append((kind, rule))
    return out


def group_of_rule(param_name: str) -> Optional[str]:
    """The ShockOSC group a behaviour's parameter belongs to (a Pull's is
    its PhysBone's ``ShockOsc/<Group>``), or None for any other parameter."""
    parts = split(param_name)
    return None if parts is None else parts[0]


def is_touch(param_name: str) -> bool:
    """Is it a group's touch (the bare ``ShockOsc/<Group>``)?"""
    parts = split(param_name)
    return parts is not None and parts[1] == TOUCH


# ---- _NextIntensity / _NextDuration: per action, only ever less ----------------------

def _number(value) -> Optional[float]:
    if value is None or isinstance(value, bool):
        return None
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def _flag(value) -> Optional[bool]:
    if isinstance(value, bool):
        return value
    f = _number(value)
    return None if f is None else f >= 0.5


def _unit(value) -> Optional[float]:
    f = _number(value)
    return None if f is None else max(0.0, min(1.0, f))


def watched_params(groups: Iterable[str]) -> List[str]:
    """The per-action parameters the router reads for these groups:
    ``_NextIntensity`` / ``_NextDuration``."""
    keys = []
    for g in dict.fromkeys(groups or ()):
        keys += [param(g, NEXT_INTENSITY), param(g, NEXT_DURATION)]
    return keys


@dataclass(frozen=True)
class NextValues:
    """A group's ``_NextIntensity`` / ``_NextDuration`` as the avatar holds
    them: the next action's strength (0-100 %) and length (a fraction of
    the behaviour's own). They only ever make an action gentler -- never
    past the behaviour's own strength or length (0 = unset, as in ShockOSC)."""
    intensity: Dict[str, int] = field(default_factory=dict)    # group key -> %
    fraction: Dict[str, float] = field(default_factory=dict)   # group key -> 0-1

    def strength(self, group: str, wanted: int) -> int:
        nxt = self.intensity.get(group_key(group))
        return min(wanted, nxt) if nxt else wanted

    def length(self, group: str, wanted_ms: int) -> int:
        frac = self.fraction.get(group_key(group))
        return max(1, int(round(wanted_ms * frac))) if frac else wanted_ms


def read_next(values: Mapping[str, Any], groups: Iterable[str]) -> NextValues:
    """The groups' ``_Next...`` from the parameter values the avatar sent."""
    values = values or {}
    intensity, fraction = {}, {}
    for g in dict.fromkeys(groups or ()):
        ni = _unit(values.get(param(g, NEXT_INTENSITY)))
        if ni and int(round(ni * 100)) > 0:
            intensity[group_key(g)] = int(round(ni * 100))
        nd = _unit(values.get(param(g, NEXT_DURATION)))
        if nd:
            fraction[group_key(g)] = nd
    return NextValues(intensity, fraction)


# ---- ShockOSC's settings <-> the behaviours' own values: one value each ------------
#
# Blise's call (2026-11-16): "We should always have the same values, and they
# should try to sync to each other as good as they can." Each value of a
# behaviour on a ShockOSC parameter that ShockOSC has a setting for is that
# setting: the avatar's menu changing it changes the behaviour, the page
# changing the behaviour changes the avatar's (shockosc_sync.py does the
# sending). Which avatar parameter a behaviour's value goes with:
#
#   * ShockOSC's own reading of `_All`: its settings are the default every
#     group follows. A group goes with its own `_Config/<Group>/<Setting>`
#     when the avatar has that parameter (and doesn't say its Override is
#     off), else with `_Config/_All/<Setting>` -- so one global Intensity on
#     the avatar's menu moves every group's behaviours together, and the
#     `_All` group's behaviours always go with `_All`.
#   * strength -> Intensity in ShockOSC's fixed mode, MaxIntensity in its
#     range mode (ModeIntensity); the bottom of a Continuous / Pull ->
#     MinIntensity in range mode; length -> Duration / MaxDuration
#     (ModeDuration); a mode the avatar doesn't say: whichever it has.
#   * rest after a shock -> CooldownTime; a touch's "for at least" ->
#     HoldTime (global only); On / Off -> Paused (with the legacy
#     `_Config/Paused` as the global one's stand-in).

PAUSED = "Paused"
MODE_INTENSITY, MODE_DURATION = "ModeIntensity", "ModeDuration"     # True = a range
FIXED_INTENSITY, MIN_INTENSITY, MAX_INTENSITY = "Intensity", "MinIntensity", "MaxIntensity"
FIXED_DURATION, MAX_DURATION = "Duration", "MaxDuration"
COOLDOWN_TIME, HOLD_TIME = "CooldownTime", "HoldTime"
OVERRIDE_INTENSITY, OVERRIDE_DURATION, OVERRIDE_COOLDOWN = (
    "OverrideIntensity", "OverrideDuration", "OverrideCooldownTime")
LEGACY_PAUSED = f"{PREFIX}{CONFIG}{PAUSED}"         # ShockOsc/_Config/Paused
CONFIG_PREFIX = f"{PREFIX}{CONFIG}"

# the behaviours' values that sync, and with what
STRENGTH, LOW, LENGTH, REST, HOLD, ON = "strength", "low", "length", "rest", "hold", "on"
_OVERRIDE = {STRENGTH: OVERRIDE_INTENSITY, LOW: OVERRIDE_INTENSITY,
             LENGTH: OVERRIDE_DURATION, REST: OVERRIDE_COOLDOWN}
SYNCED_KINDS = ("triggers", "continuous", "pulls")

# kind -> value -> the behaviour's field holding it
_FIELDS = {
    "triggers": {STRENGTH: "intensity", LENGTH: "duration_ms", REST: "rest_ms",
                 HOLD: "hold_ms", ON: "enabled"},
    "continuous": {STRENGTH: "max_int", LOW: "min_int", REST: "rest_ms", ON: "enabled"},
    "pulls": {STRENGTH: "max_int", LOW: "min_int", LENGTH: "duration_ms", REST: "rest_ms",
              ON: "enabled"},
}
# the order a parameter's value is read from its behaviours (the first wins)
VALUE_ORDER = (STRENGTH, LOW, LENGTH, REST, HOLD, ON)


def config_setting(name: str) -> Optional[Tuple[str, str]]:
    """``(group, setting)`` of a ``ShockOsc/_Config/...`` parameter (the
    legacy ``_Config/Paused`` reads as ``_All``'s), or None."""
    name = str(name or "")
    if name.startswith("/avatar/parameters/"):
        name = name[len("/avatar/parameters/"):]
    if name == LEGACY_PAUSED:
        return ALL, PAUSED
    if not name.startswith(CONFIG_PREFIX):
        return None
    rest = name[len(CONFIG_PREFIX):]
    if rest.count("/") != 1:
        return None
    group, setting = rest.split("/")
    return (group, setting) if group and setting else None


def fields_of(kind: str, rule_param: str) -> Dict[str, str]:
    """value -> field, for a behaviour of `kind` on `rule_param`: what of it
    syncs ({} for a behaviour that isn't ShockOSC's, or of another kind).
    "For at least" only on a group's touch."""
    if kind not in _FIELDS or group_of_rule(rule_param) is None:
        return {}
    out = dict(_FIELDS[kind])
    if HOLD in out and not is_touch(rule_param):
        del out[HOLD]
    return out


def address(group: str, value: str, has, values: Mapping[str, Any]) -> Optional[str]:
    """The avatar parameter a group's `value` (STRENGTH ...) goes with, or
    None when the avatar has none for it. `has(name)`: whether the avatar
    has that parameter; `values`: what it last said (the modes, the
    overrides)."""
    values = values or {}

    def mode_pick(src: str, mode: str, fixed: str, top: str) -> Optional[str]:
        m = _flag(values.get(config_param(src, mode)))
        if m is None and src != ALL:
            m = _flag(values.get(config_param(ALL, mode)))
        f, t = config_param(src, fixed), config_param(src, top)
        if m is True:
            return t if has(t) else None
        if m is False:
            return f if has(f) else None
        return f if has(f) else (t if has(t) else None)

    def pick(src: str) -> Optional[str]:
        if value == STRENGTH:
            return mode_pick(src, MODE_INTENSITY, FIXED_INTENSITY, MAX_INTENSITY)
        if value == LOW:
            m = _flag(values.get(config_param(src, MODE_INTENSITY)))
            if m is None and src != ALL:
                m = _flag(values.get(config_param(ALL, MODE_INTENSITY)))
            p = config_param(src, MIN_INTENSITY)
            return p if m is True and has(p) else None      # a range's bottom only
        if value == LENGTH:
            return mode_pick(src, MODE_DURATION, FIXED_DURATION, MAX_DURATION)
        if value == REST:
            p = config_param(src, COOLDOWN_TIME)
            return p if has(p) else None
        if value == ON:
            p = config_param(src, PAUSED)
            if has(p):
                return p
            return LEGACY_PAUSED if src == ALL and has(LEGACY_PAUSED) else None
        return None

    if value == HOLD:
        p = config_param(ALL, HOLD_TIME)            # ShockOSC has it global only
        return p if has(p) else None
    if group_key(group) != group_key(ALL):
        flag = _OVERRIDE.get(value)
        own_off = flag is not None and _flag(values.get(config_param(group, flag))) is False
        if not own_off:
            own = pick(group)
            if own is not None:
                return own
    return pick(ALL)


def to_avatar(name: str, value: str, ogp: Any) -> Any:
    """A behaviour's value as the avatar parameter `name` holds it: 0-1
    floats in ShockOSC's units, Paused a bool."""
    setting = (config_setting(name) or ("", ""))[1]
    if value == ON:
        return not bool(ogp)
    v = float(ogp or 0)
    if setting in (FIXED_INTENSITY, MIN_INTENSITY, MAX_INTENSITY):
        return round(max(0.0, min(1.0, v / 100.0)), 3)
    if setting in (FIXED_DURATION, MAX_DURATION):
        return round(max(0.0, min(1.0, v / 10000.0)), 4)
    if setting == COOLDOWN_TIME:
        return round(max(0.0, min(1.0, v / 100000.0)), 5)
    if setting == HOLD_TIME:
        return round(max(0.0, min(1.0, v / 1000.0)), 3)
    return v


def from_avatar(name: str, value: str, avatar: Any) -> Any:
    """What the avatar parameter `name` says, as a behaviour's value -- None
    for nothing usable. Clamped as ShockOSC clamps it; OGP's own ranges
    (settings.pishock) clamp again on the way in, and every shocker's
    limits hold at the send whatever this says."""
    setting = (config_setting(name) or ("", ""))[1]
    if value == ON:
        paused = _flag(avatar)
        return None if paused is None else not paused
    u = _unit(avatar)
    if u is None:
        return None
    if setting in (FIXED_INTENSITY, MIN_INTENSITY, MAX_INTENSITY):
        return int(round(u * 100))
    if setting == FIXED_DURATION:
        return int(round(max(300.0, min(10000.0, u * 10000.0))))
    if setting == MAX_DURATION:
        return int(round(max(300.0, min(30000.0, u * 10000.0))))
    if setting == COOLDOWN_TIME:
        return int(round(u * 100000.0))
    if setting == HOLD_TIME:
        return int(round(u * 1000.0))
    return None


def same(a: Any, b: Any) -> bool:
    """Two avatar values alike (a float comes back from VRChat as a float32)."""
    if isinstance(a, bool) or isinstance(b, bool):
        return _flag(a) is not None and _flag(a) == _flag(b)
    x, y = _number(a), _number(b)
    return x is not None and y is not None and abs(x - y) < 1e-4


def field_name(kind: str, value: str) -> Optional[str]:
    """The behaviour's field holding `value` (STRENGTH ...) for its kind."""
    return _FIELDS.get(kind, {}).get(value)


def with_value(kind: str, rule: Mapping[str, Any], value: str, new: Any) -> Dict[str, Any]:
    """`rule` with `value` set to `new` -- a Continuous's or a Pull's bottom
    kept at or under its top, so the top (the synced strength) stays what
    was set rather than being swapped by the settings' cleaning."""
    out = dict(rule)
    fld = field_name(kind, value)
    if fld is None:
        return out
    out[fld] = new
    if value == STRENGTH and "min_int" in out:
        out["min_int"] = min(int(out.get("min_int") or 0), int(new))
    elif value == LOW and "max_int" in out:
        out[fld] = min(int(new), int(out.get("max_int") or 0))
    return out


def describe(kind: str, rule: Mapping[str, Any]) -> str:
    """What a planned behaviour is, in a word or two (the setup card)."""
    if kind == "pulls":
        return "pull"
    if kind == "continuous":
        return f"continuous {rule.get('op', '')}".strip()
    return "touch" if is_touch(rule.get("param", "")) else f"{rule.get('op', '')} at once"


_SYNCABLE = frozenset({PAUSED, FIXED_INTENSITY, MIN_INTENSITY, MAX_INTENSITY, FIXED_DURATION,
                       MAX_DURATION, COOLDOWN_TIME, HOLD_TIME})


def synced_settings(names: Iterable[str]) -> List[str]:
    """Which of ShockOSC's settings an avatar has that a behaviour's value
    goes with (Intensity, Duration, ...), in a stable order."""
    order = (FIXED_INTENSITY, MIN_INTENSITY, MAX_INTENSITY, FIXED_DURATION, MAX_DURATION,
             COOLDOWN_TIME, HOLD_TIME, PAUSED)
    have = {(config_setting(n) or ("", ""))[1] for n in names or ()} & _SYNCABLE
    return [s for s in order if s in have]
