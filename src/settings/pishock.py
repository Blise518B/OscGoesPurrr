"""Shocker settings: the USB port, the safety limits, the OpenShock
shocker list and the four behaviour lists the Shockers page edits.

  * ``zones``      — Touch zones: several bool contacts, each driving its
    own shockers (the neck the collar, a thigh its shocker ...), all at
    one ``intensity``, pulsed once or held like a trigger.
  * ``continuous`` — a float parameter (a proximity contact, say) runs the
    shocker for as long as it is above ``threshold``, strength scaled
    between ``min_int`` and ``max_int`` by the value.
  * ``triggers``   — one bool contact at a fixed ``intensity``: ``pulse``
    fires once per contact for ``duration_ms`` -- once it has stayed on for
    ``hold_ms`` (0: at once; ShockOSC's touch waits 250 ms) --, ``hold`` runs
    while the contact stays on.
  * ``impacts``    — a group of OnEnter contacts (receivers with different
    Min Velocity on the avatar), each ``tier`` with its own intensity; the
    strongest tier that fired picks the pulse.
  * ``pulls``      — a PhysBone (its parameter ``param``, read as
    ``<param>_IsGrabbed`` / ``<param>_Stretch``): ``held_op`` while it is
    held ("none" for nothing), and a let-go with any stretch fires ``op``
    once for ``duration_ms`` -- the strength between ``min_int`` and
    ``max_int`` by the stretch at the let-go, as ShockOSC does.

Every rule names its ``shockers`` (ids from the hub, or "all"; a Touch
zone names its own) and its ``op``. Older files named one ``shocker``; a
new rule drives none until shockers are dropped on it. A PiShock hub
reports its own shockers; OpenShock firmware has no
list of its own, so ``openshock_shockers`` holds them: a model and the
transmitter id the collar was paired to (see openshock_serial.py).

Every value is cleaned on the way in AND on the way out, so a hand-edited
file can't hand the router a malformed or unsafe rule — and PiShockEngine
re-clamps every send against the limits (pishock_limits.py) regardless.

Each shocker may have its own ``shocker_limits`` (max shock, max vibrate,
longest pulse -- pishock_limits.PER_SHOCKER); one without takes the
hub-wide values, which are also where a newly paired shocker starts. The
timing rules (rest, longest hold, break) are the hub's, for every shocker.
While ``separate_limits`` is on, friends keep to ``friend_limits``: their
own timing and their own max shock, max vibrate and longest pulse, which
only ever lower each shocker's own for them (pishock_limits.FRIEND_KEYS).

``shocker_ops_off`` holds each shocker's Shock / Vibrate / Beep switched off
on its card (Blise's friends, 2026-11-14): the engine refuses those ops on
that shocker, whoever sends them.

``armed`` is remembered across launches (Blise's call, 2026-10-28: it used
to start off every launch)."""

import random
from typing import Any, Dict, List

import openshock_serial
import pishock_limits
from utilities import strip_param_prefix

from ._base import JsonSettingsManager
from ._paths import PISHOCK_SETTINGS_FILE

OPS = ("shock", "vibrate", "beep")
HELD_OPS = ("none",) + OPS
TRIGGER_MODES = ("pulse", "hold")
RULE_KINDS = ("zones", "triggers", "continuous", "impacts", "pulls")
MAX_HOLD_MS = 2000          # a touch's "for at least" (ShockOSC's goes to 1 s)
MAX_REST_MS = 100000        # a ShockOSC behaviour's rest after a shock (its CooldownTime's 100 s)
# a PhysBone's own parameters, past the name it is given on the avatar
PHYSBONE_SUFFIXES = ("_IsGrabbed", "_Stretch", "_IsPosed", "_Angle", "_Squish")
MAX_TIERS = 8
MAX_ZONES = 16
MAX_TARGETS = 16            # shockers one behaviour (or zone) drives


# OverflowError: json reads 1e999 as inf (no int holds it) and a 400-digit
# number as an int no float holds -- a hand-edited file falls back like any
# other garbage instead of breaking the whole page.

def _f(value, default: float, lo: float, hi: float) -> float:
    try:
        v = float(value)
    except (TypeError, ValueError, OverflowError):
        return default
    if v != v:
        return default
    return max(lo, min(hi, v))


def _i(value, default: int, lo: int, hi: int) -> int:
    try:
        v = int(float(value))
    except (TypeError, ValueError, OverflowError):
        return default
    return max(lo, min(hi, v))


def _param(value) -> str:
    """Bare parameter name, the way the store keys it."""
    return strip_param_prefix(value)


def _shocker_id(value):
    try:
        v = int(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return v if 0 <= v < 2 ** 32 else None


def _shockers(rule: Dict[str, Any]):
    """Who a behaviour (or a zone) drives: "all", or shocker ids in the
    order they were dropped. An older file's single ``shocker`` (an id, or
    "all") reads as the same; a rule naming neither drives nothing."""
    raw = rule.get("shockers", rule.get("shocker", []))
    if raw == "all":
        return "all"
    if not isinstance(raw, (list, tuple)):
        raw = [] if raw is None or raw == "" else [raw]
    ids: List[int] = []
    for item in raw:
        if item == "all":
            return "all"
        sid = _shocker_id(item)
        if sid is not None and sid not in ids and len(ids) < MAX_TARGETS:
            ids.append(sid)
    return ids


SHOCKER_NAME_MAX = 40       # remote_protocol.TOY_NAME_MAX: what a friend is shown


def _shocker_name(value) -> str:
    return " ".join(str(value or "").split())[:SHOCKER_NAME_MAX]


def _common(rule: Dict[str, Any], default_name: str) -> Dict[str, Any]:
    op = str(rule.get("op", "vibrate"))
    return {
        "name": str(rule.get("name", "") or "").strip() or default_name,
        "enabled": bool(rule.get("enabled", True)),
        "op": op if op in OPS else "vibrate",
        "shockers": _shockers(rule),
    }


# Contact, Continuous and Pull keep a strength of 0 (it sends nothing): the
# avatar's ShockOSC Intensity can say 0, and a synced value is the same on
# both sides (shockosc_sync.py). Each also keeps `rest_ms`, the rest after
# a shock its ShockOSC group takes (CooldownTime) -- 0: the shockers' own.

def clean_continuous(rule: Dict[str, Any]) -> Dict[str, Any]:
    lo = _i(rule.get("min_int"), 5, 0, 100)
    hi = _i(rule.get("max_int"), 30, 0, 100)
    if lo > hi:
        lo, hi = hi, lo
    return {
        **_common(rule, "Continuous"),
        "param": _param(rule.get("param")),
        "threshold": _f(rule.get("threshold"), 0.0, 0.0, 0.99),
        "min_int": lo,
        "max_int": hi,
        "rest_ms": _i(rule.get("rest_ms"), 0, 0, MAX_REST_MS),
    }


def clean_trigger(rule: Dict[str, Any]) -> Dict[str, Any]:
    mode = str(rule.get("mode", "pulse"))
    return {
        **_common(rule, "Trigger"),
        "param": _param(rule.get("param")),
        "mode": mode if mode in TRIGGER_MODES else "pulse",
        "intensity": _i(rule.get("intensity"), 20, 0, 100),
        "duration_ms": _i(rule.get("duration_ms"), 500, 100, 15000),
        "hold_ms": _i(rule.get("hold_ms"), 0, 0, MAX_HOLD_MS),
        "rest_ms": _i(rule.get("rest_ms"), 0, 0, MAX_REST_MS),
    }


def physbone_name(value) -> str:
    """A PhysBone's own parameter name: what was picked, less the
    ``_IsGrabbed`` / ``_Stretch`` / ... VRChat adds to it."""
    name = _param(value)
    for suffix in PHYSBONE_SUFFIXES:
        if name.endswith(suffix) and len(name) > len(suffix):
            return name[:-len(suffix)]
    return name


def clean_pull(rule: Dict[str, Any]) -> Dict[str, Any]:
    lo = _i(rule.get("min_int"), 5, 0, 100)
    hi = _i(rule.get("max_int"), 30, 0, 100)
    if lo > hi:
        lo, hi = hi, lo
    held = str(rule.get("held_op", "vibrate"))
    common = _common(rule, "Pull")
    if "op" not in rule:
        common["op"] = "shock"       # ShockOSC's let-go is a shock
    return {
        **common,
        "param": physbone_name(rule.get("param")),
        "held_op": held if held in HELD_OPS else "vibrate",
        "min_int": lo,
        "max_int": hi,
        "duration_ms": _i(rule.get("duration_ms"), 500, 100, 15000),
        "rest_ms": _i(rule.get("rest_ms"), 0, 0, MAX_REST_MS),
    }


def clean_impact(rule: Dict[str, Any]) -> Dict[str, Any]:
    tiers = []
    for t in rule.get("tiers") or []:
        if isinstance(t, dict) and len(tiers) < MAX_TIERS:
            tiers.append({"param": _param(t.get("param")),
                          "intensity": _i(t.get("intensity"), 20, 1, 100)})
    return {
        **_common(rule, "Impact"),
        "duration_ms": _i(rule.get("duration_ms"), 500, 100, 15000),
        "tiers": tiers,
    }


def clean_zones(rule: Dict[str, Any]) -> Dict[str, Any]:
    mode = str(rule.get("mode", "pulse"))
    zones = []
    for z in rule.get("zones") or []:
        if isinstance(z, dict) and len(zones) < MAX_ZONES:
            zones.append({"param": _param(z.get("param")), "shockers": _shockers(z)})
    common = _common(rule, "Touch zones")
    del common["shockers"]          # each zone names its own
    return {
        **common,
        "mode": mode if mode in TRIGGER_MODES else "pulse",
        "intensity": _i(rule.get("intensity"), 20, 1, 100),
        "duration_ms": _i(rule.get("duration_ms"), 500, 100, 15000),
        "zones": zones,
    }


_CLEANERS = {
    "zones": clean_zones,
    "continuous": clean_continuous,
    "triggers": clean_trigger,
    "impacts": clean_impact,
    "pulls": clean_pull,
}

# What a new behaviour of each kind starts with -- the page's ＋ Add and the
# ShockOSC setup alike (Blise's call, 2026-11-16: the same values).
NEW_RULES = {
    "zones": {"name": "Touch zones", "intensity": 20, "duration_ms": 500,
              "zones": [{"param": "", "shockers": []}, {"param": "", "shockers": []}]},
    "continuous": {"name": "Continuous", "min_int": 5, "max_int": 30, "shockers": []},
    "triggers": {"name": "Contact", "intensity": 20, "duration_ms": 500, "shockers": []},
    "impacts": {"name": "Impact", "duration_ms": 500, "shockers": [], "tiers": [
        {"param": "", "intensity": 10},
        {"param": "", "intensity": 25},
        {"param": "", "intensity": 45},
    ]},
    "pulls": {"name": "Pull", "op": "shock", "held_op": "vibrate", "min_int": 5,
              "max_int": 30, "duration_ms": 500, "shockers": []},
}


def new_rule_values(kind: str) -> Dict[str, Any]:
    """A new behaviour of `kind`, every value as it starts (cleaned): the
    one source the ShockOSC setup takes its values from too."""
    clean = _CLEANERS.get(kind)
    return clean(dict(NEW_RULES[kind])) if clean is not None else {}


# Blise's ask (2026-10-28): an example of a contact picking the shocker,
# there from the start but switched off until its contacts are yours. Added
# once -- deleting it keeps it gone.
EXAMPLE_ZONES = {
    "name": "Touch zones (example)", "enabled": False, "op": "vibrate", "mode": "pulse",
    "intensity": 15, "duration_ms": 500,
    "zones": [{"param": "Contact/Neck", "shockers": []},
              {"param": "Contact/ThighL", "shockers": []},
              {"param": "Contact/ThighR", "shockers": []}],
}


# Ctrl+Z's names for the settings (the page's own words where it has them)
_LIMIT_NAMES = {
    "max_intensity": "Up to shock strength",
    "max_vibrate": "Up to vibrate strength",
    "max_pulse_ms": "Up to a pulse of",
    "cooldown_s": "At least a rest of",
    "max_hold_s": "Up to a hold of",
    "hold_rest_s": "Then a forced break of",
}
_NAMES = {
    "armed": "Arm shocks",
    "friends_may_use": "Share with friends",
    "enabled": "Shockers On / Off",
    "port": "Hub port",
    "auto_connect": "Connect on start",
    "shockers_off": "a shocker's On / Off",
    "shocker_ops_off": "a shocker's Shock / Vibrate / Beep",
    "separate_limits": "Separate limits for friends",
    "shocker_names": "a shocker's name",
    "openshock_shockers": "OpenShock shockers",
    "zones": "Touch zones",
    "triggers": "a behaviour",
    "continuous": "a behaviour",
    "impacts": "a behaviour",
}
# Which way loosens a limit: a cap up, a rest down
_LOOSER_UP = frozenset({"max_intensity", "max_vibrate", "max_pulse_ms", "max_hold_s"})


def _limit_text(key: str, value: Any) -> str:
    if key in ("max_intensity", "max_vibrate"):
        return f"{float(value):.0f}"
    if key == "max_pulse_ms":
        return f"{float(value) / 1000:g} s"
    return f"{float(value):g} s"


def _looser(key: str, before: Any, after: Any) -> bool:
    try:
        b, a = float(before), float(after)
    except (TypeError, ValueError):
        return False
    return a > b if key in _LOOSER_UP else a < b


def history_asks(current: Dict[str, Any], target: Dict[str, Any]) -> list:
    """What an undo or redo from `current` to `target` must ask first
    (settings_history.py): arming asks Arm shocks' own question; a shocker,
    one of its Shock / Vibrate / Beep, the hub or sharing switched back on,
    and a limit loosened -- a cap raised, a rest shortened, the hub's or one
    shocker's own -- ask Yes / No. Switching anything off, lowering a cap or
    lengthening a rest never asks."""
    from settings_history import Ask, turned_on
    asks = []
    names = target.get("shocker_names") or {}
    for o in target.get("openshock_shockers") or []:
        if isinstance(o, dict) and o.get("name") and str(o.get("id")) not in names:
            names = {**names, str(o.get("id")): o["name"]}

    def name(sid) -> str:
        return names.get(str(sid)) or f"Shocker {sid}"

    if turned_on(current, target, ("armed",)):
        asks.append(Ask("arm", "arms shocks"))
    if turned_on(current, target, ("enabled",), True):
        asks.append(Ask("confirm", "switches your shockers back on"))
    if turned_on(current, target, ("friends_may_use",), True):
        asks.append(Ask("confirm", "shares your shockers with friends again"))
    back = [s for s in current.get("shockers_off") or []
            if s not in (target.get("shockers_off") or [])]
    for sid in back:
        asks.append(Ask("confirm", f"switches {name(sid)} back on"))
    cur_ops = current.get("shocker_ops_off") or {}
    tgt_ops = target.get("shocker_ops_off") or {}
    for sid, ops in cur_ops.items():
        for op in ops or []:
            if op not in (tgt_ops.get(sid) or []):
                asks.append(Ask("confirm", f"switches {name(sid)}'s {op.capitalize()} back on"))
    for key in pishock_limits.RANGES:
        if key in current and key in target and _looser(key, current[key], target[key]):
            asks.append(Ask("confirm", f"sets “{_LIMIT_NAMES[key]}” to "
                            f"{_limit_text(key, target[key])}"))
    # Separate limits for friends: on, a friend's long hold and your
    # avatar's can run back to back -- looser, so it asks; so does raising a
    # limit in the friends' set, a cap or the timing (the set as it stands:
    # a copy when first switched on)
    if turned_on(current, target, ("separate_limits",)):
        asks.append(Ask("confirm", "gives friends separate limits"))
    cur_f = _friend_set(current)
    tgt_f = _friend_set(target)
    for key in pishock_limits.FRIEND_KEYS if target.get("separate_limits") else ():
        if _looser(key, cur_f.get(key), tgt_f.get(key)):
            asks.append(Ask("confirm", f"sets friends' “{_LIMIT_NAMES[key]}” to "
                            f"{_limit_text(key, tgt_f[key])}"))
    cur_own = current.get("shocker_limits") or {}
    tgt_own = target.get("shocker_limits") or {}
    for sid in dict.fromkeys(list(cur_own) + list(tgt_own)):
        for key in pishock_limits.PER_SHOCKER:
            before = (cur_own.get(sid) or {}).get(key, current.get(key))
            after = (tgt_own.get(sid) or {}).get(key, target.get(key))
            if _looser(key, before, after):
                asks.append(Ask("confirm", f"sets {name(sid)}'s “{_LIMIT_NAMES[key]}” to "
                                f"{_limit_text(key, after)}"))
    return asks


def _friend_set(raw: Dict[str, Any]) -> Dict[str, Any]:
    """The friends' set as a settings dict stores it: their own values,
    where it starts (`_friend_start`) where they have none."""
    own = raw.get("friend_limits") if isinstance(raw.get("friend_limits"), dict) else {}
    start = _friend_start(raw)
    return {key: own.get(key, start[key]) for key in pishock_limits.FRIEND_KEYS}


def _friend_start(raw: Dict[str, Any]) -> Dict[str, Any]:
    """Where the friends' set starts, and what it reads for a value it has
    none of: the hub's timing, and for each cap the highest any shocker has
    (the hub-wide value or a shocker's own) -- so switching Separate limits
    for friends on lowers nobody's cap until a friends' value is moved."""
    own = raw.get("shocker_limits") if isinstance(raw.get("shocker_limits"), dict) else {}
    out: Dict[str, Any] = {}
    for key in pishock_limits.FRIEND_KEYS:
        lo, hi, d = pishock_limits.RANGES[key]
        clean = _i if key in pishock_limits.WHOLE else _f
        values = [clean(raw.get(key), d, lo, hi)]
        if key in pishock_limits.PER_SHOCKER:
            values += [clean(o[key], d, lo, hi) for o in own.values()
                       if isinstance(o, dict) and key in o]
        out[key] = max(values)
    return out


class PiShockSettingsManager(JsonSettingsManager):
    FILE_PATH = PISHOCK_SETTINGS_FILE
    HISTORY_KEY = "pishock"
    HISTORY_LABEL = "Shockers"

    @staticmethod
    def history_asks(current: Dict[str, Any], target: Dict[str, Any]) -> list:
        return history_asks(current, target)

    def history_describe(self, path) -> str:
        if not path:
            return ""
        key = str(path[0])
        if key in _LIMIT_NAMES:
            return _LIMIT_NAMES[key]
        if key == "friend_limits" and len(path) >= 2:
            return f"Friends: {_LIMIT_NAMES.get(str(path[1]), path[1])}"
        if key == "shocker_limits" and len(path) >= 3:
            sid = str(path[1])
            nm = (self.settings.get("shocker_names") or {}).get(sid) or f"Shocker {sid}"
            return f"{nm}: {_LIMIT_NAMES.get(str(path[2]), path[2])}"
        return _NAMES.get(key, "")

    DEFAULTS: Dict[str, Any] = {
        "port": "",                 # "" = find the hub by its USB id
        "auto_connect": False,      # a shock device never connects unasked
        # the limits (pishock_limits): max_intensity, max_vibrate (vibrates'
        # own cap), max_pulse_ms, cooldown_s, max_hold_s, hold_rest_s
        **{key: pishock_limits.default(key) for key in pishock_limits.RANGES},
        "openshock_shockers": [],   # [{id, model, name}], OpenShock hubs only
        # your own names for the shockers a PiShock hub reports by id only
        # ("Shocker 24325"): {"24325": "Collar"} -- friends see them too
        "shocker_names": {},
        # each shocker's own limits, by id: {"24325": {"max_intensity": 20}};
        # what one doesn't have, the hub-wide values above give it
        "shocker_limits": {},
        # Separate limits for friends (Blise's call, 2026-11-17; off: one set
        # for everyone): on, friends -- Me and the web remote too -- keep to
        # `friend_limits`' rest, longest hold and forced break, with their
        # own accounting, and to its max shock, max vibrate and longest
        # pulse, which only lower each shocker's own; it starts as a copy
        # (`_friend_start`)
        "separate_limits": False,
        "friend_limits": {},
        # the shockers switched off on their card, by id (Blise's ask,
        # 2026-10-28: only show the ones in use) -- the engine sends them
        # nothing and lists them to nobody; a new one starts on
        "shockers_off": [],
        # each shocker's Shock / Vibrate / Beep switched off on its card, by
        # id: {"24325": ["shock"]} -- the engine refuses those, whoever sends
        # them; a shocker not listed has all three on
        "shocker_ops_off": {},
        # Arm shocks, remembered across launches (Blise's call, 2026-10-28)
        "armed": False,
        # Home's "Share with friends": off, no friend's shock gets through and
        # friends don't see the shockers, whatever each friend's own switch says
        "friends_may_use": True,
        # Home's On / Off (= the page's Stop all / Resume): off, the engine
        # holds everything stopped -- kept across restarts
        "enabled": True,
        # a new file -- or one from before Touch zones -- starts with the
        # example, switched off; once deleted it stays gone
        "zones": [clean_zones(EXAMPLE_ZONES)],
        "continuous": [],
        "triggers": [],
        "impacts": [],
        "pulls": [],
    }

    def _post_load(self, loaded: Dict[str, Any]) -> None:
        if "max_vibrate" not in loaded:
            # Older files: vibrates shared the shock cap -- keep that until
            # the user picks their own.
            self.settings["max_vibrate"] = self.settings.get("max_intensity", 30)
        for kind in RULE_KINDS:
            if not isinstance(self.settings.get(kind), list):
                self.settings[kind] = []
        raw = self.settings.get("shockers_off")
        self.settings["shockers_off"] = sorted({
            sid for sid in (_shocker_id(v) for v in (raw if isinstance(raw, list) else []))
            if sid is not None})
        raw = self.settings.get("shocker_names")
        self.settings["shocker_names"] = {
            str(k)[:16]: _shocker_name(v) for k, v in (raw.items() if isinstance(raw, dict) else [])
            if _shocker_name(v)}

    # ---- connection --------------------------------------------------
    def get_port(self) -> str:
        return str(self.settings.get("port", "") or "").strip()

    def set_port(self, port: str) -> None:
        self.settings["port"] = str(port or "").strip()
        self._save()

    def get_auto_connect(self) -> bool:
        return bool(self.settings.get("auto_connect", False))

    def set_auto_connect(self, value: bool) -> None:
        self.settings["auto_connect"] = bool(value)
        self._save()

    def get_enabled(self) -> bool:
        return bool(self.settings.get("enabled", True))

    def set_enabled(self, value: bool) -> None:
        if bool(value) != self.get_enabled():
            self.settings["enabled"] = bool(value)
            self._save()

    def get_armed(self) -> bool:
        return bool(self.settings.get("armed", False))

    def set_armed(self, value: bool) -> None:
        if bool(value) != self.get_armed():
            self.settings["armed"] = bool(value)
            self._save()

    def get_friends_may_use(self) -> bool:
        return bool(self.settings.get("friends_may_use", True))

    def set_friends_may_use(self, value: bool) -> None:
        self.settings["friends_may_use"] = bool(value)
        self._save()

    # ---- limits ------------------------------------------------------
    def get_limits(self) -> Dict[str, Any]:
        s = self.settings
        return {key: (_i if key in pishock_limits.WHOLE else _f)(s.get(key), d, lo, hi)
                for key, (lo, hi, d) in pishock_limits.RANGES.items()}

    def set_limit(self, key: str, value) -> None:
        if key not in pishock_limits.RANGES:   # the limits only, nothing else
            return
        self.settings[key] = value
        self.settings[key] = self.get_limits()[key]  # store it clamped
        self._save()

    def get_separate_limits(self) -> bool:
        return bool(self.settings.get("separate_limits", False))

    def set_separate_limits(self, on: bool) -> None:
        """Separate limits for friends. The first time it goes on, the
        friends' set starts as a copy (`_friend_start`: the hub's timing,
        each cap the highest any shocker has); a value it has none of yet
        is copied then too."""
        on = bool(on)
        have = self.settings.get("friend_limits")
        have = have if isinstance(have, dict) else {}
        if on and any(k not in have for k in pishock_limits.FRIEND_KEYS):
            self.settings["friend_limits"] = self.get_friend_limits()
        if on != self.get_separate_limits():
            self.settings["separate_limits"] = on
        self._save()

    def get_friend_limits(self) -> Dict[str, Any]:
        """The friends' max shock, max vibrate, longest pulse, rest after a
        pulse, longest hold and forced break, each inside its range --
        where it starts (`_friend_start`) for one they have none of yet."""
        start = _friend_start(self.settings)
        own = self.settings.get("friend_limits")
        own = own if isinstance(own, dict) else {}
        out: Dict[str, Any] = {}
        for key in pishock_limits.FRIEND_KEYS:
            lo, hi, _d = pishock_limits.RANGES[key]
            clean = _i if key in pishock_limits.WHOLE else _f
            out[key] = clean(own.get(key), start[key], lo, hi)
        return out

    def set_friend_limit(self, key: str, value) -> None:
        if key not in pishock_limits.FRIEND_KEYS:
            return
        lo, hi, _d = pishock_limits.RANGES[key]
        limits = self.get_friend_limits()
        clean = _i if key in pishock_limits.WHOLE else _f
        limits[key] = clean(value, limits[key], lo, hi)
        self.settings["friend_limits"] = limits
        self._save()

    def get_shocker_limits(self) -> Dict[str, Dict[str, int]]:
        """Each shocker's own limits, by id -- only the ones it has (the
        rest come from the hub-wide values), every one inside its range."""
        raw = self.settings.get("shocker_limits")
        out: Dict[str, Dict[str, int]] = {}
        for key, own in (raw.items() if isinstance(raw, dict) else []):
            if not isinstance(own, dict) or _shocker_id(key) is None:
                continue
            cleaned = {}
            for name in pishock_limits.PER_SHOCKER:
                if name in own:
                    lo, hi, d = pishock_limits.RANGES[name]
                    cleaned[name] = _i(own[name], d, lo, hi)
            if cleaned:
                out[str(_shocker_id(key))] = cleaned
        return out

    def set_shocker_limit(self, shocker_id, key: str, value) -> None:
        """One shocker's own max shock, max vibrate or longest pulse."""
        sid = _shocker_id(shocker_id)
        if sid is None or key not in pishock_limits.PER_SHOCKER:
            return
        lo, hi, d = pishock_limits.RANGES[key]
        limits = self.get_shocker_limits()
        limits.setdefault(str(sid), {})[key] = _i(value, d, lo, hi)
        if limits != self.settings.get("shocker_limits"):
            self.settings["shocker_limits"] = limits
            self._save()

    def shocker_limits_for(self, shocker_id) -> Dict[str, int]:
        """What one shocker's caps are: its own, else the hub-wide ones."""
        hub = self.get_limits()
        own = self.get_shocker_limits().get(str(_shocker_id(shocker_id)), {})
        return {key: own.get(key, hub[key]) for key in pishock_limits.PER_SHOCKER}

    # ---- shockers in use ------------------------------------------------
    def get_shockers_off(self) -> List[int]:
        """The shockers switched off on their card (ids)."""
        return list(self.settings.get("shockers_off") or [])

    def set_shocker_on(self, shocker_id, on: bool) -> None:
        sid = _shocker_id(shocker_id)
        if sid is None:
            return
        off = set(self.get_shockers_off())
        (off.discard if on else off.add)(sid)
        if sorted(off) != self.settings.get("shockers_off"):
            self.settings["shockers_off"] = sorted(off)
            self._save()

    # ---- each shocker's Shock / Vibrate / Beep -----------------------------
    def get_shocker_ops_off(self) -> Dict[str, List[str]]:
        """The ops switched off on each shocker's card, by id -- only the
        shockers with one off, each op once, in OPS order."""
        raw = self.settings.get("shocker_ops_off")
        out: Dict[str, List[str]] = {}
        for key, ops in (raw.items() if isinstance(raw, dict) else []):
            sid = _shocker_id(key)
            if sid is None or not isinstance(ops, list):
                continue
            cleaned = [op for op in OPS if op in ops]
            if cleaned:
                out[str(sid)] = cleaned
        return out

    def set_shocker_op(self, shocker_id, op: str, on: bool) -> None:
        """Switch one op on or off for one shocker."""
        sid = _shocker_id(shocker_id)
        if sid is None or op not in OPS:
            return
        ops_off = self.get_shocker_ops_off()
        now = set(ops_off.get(str(sid), []))
        (now.discard if on else now.add)(op)
        if now:
            ops_off[str(sid)] = [o for o in OPS if o in now]
        else:
            ops_off.pop(str(sid), None)
        if ops_off != self.settings.get("shocker_ops_off"):
            self.settings["shocker_ops_off"] = ops_off
            self._save()

    # ---- names for the hub's own shockers ---------------------------------
    def get_shocker_names(self) -> Dict[str, str]:
        return dict(self.settings.get("shocker_names") or {})

    def set_shocker_name(self, shocker_id, name: str) -> None:
        """Name a shocker (by its id); an empty name gives it back its
        own ("Shocker 24325")."""
        names = self.get_shocker_names()
        name = _shocker_name(name)
        key = str(shocker_id)[:16]
        if name:
            names[key] = name
        else:
            names.pop(key, None)
        if names != self.settings.get("shocker_names"):
            self.settings["shocker_names"] = names
            self._save()

    # ---- OpenShock shockers --------------------------------------------
    def get_openshock_shockers(self) -> List[Dict[str, Any]]:
        return openshock_serial.clean_shockers(self.settings.get("openshock_shockers"))

    def add_openshock_shocker(self) -> int:
        """Append a shocker with a fresh random transmitter id — pairing a
        new collar to it is the page's Beep. Returns its index (or -1 when
        the list is full)."""
        shockers = self.get_openshock_shockers()
        if len(shockers) >= openshock_serial.MAX_SHOCKERS:
            return -1
        used = {s["id"] for s in shockers}
        rf_id = random.randint(1, openshock_serial.MAX_RF_ID)
        while rf_id in used:
            rf_id = random.randint(1, openshock_serial.MAX_RF_ID)
        shockers.append({"id": rf_id, "model": openshock_serial.DEFAULT_MODEL,
                         "name": f"Shocker {len(shockers) + 1}"})
        self.settings["openshock_shockers"] = shockers
        self._save()
        return len(shockers) - 1

    def set_openshock_shocker(self, index: int, shocker: Dict[str, Any]) -> None:
        """Replace one entry. An id another entry already has is refused
        (the entry keeps its old one)."""
        shockers = self.get_openshock_shockers()
        if not 0 <= index < len(shockers):
            return
        others = shockers[:index] + shockers[index + 1:]
        cleaned = openshock_serial.clean_shockers([shocker])
        if not cleaned or any(s["id"] == cleaned[0]["id"] for s in others):
            cleaned = openshock_serial.clean_shockers(
                [{**shocker, "id": shockers[index]["id"]}])
        if cleaned:
            shockers[index] = cleaned[0]
            self.settings["openshock_shockers"] = shockers
            self._save()

    def delete_openshock_shocker(self, index: int) -> None:
        shockers = self.get_openshock_shockers()
        if 0 <= index < len(shockers):
            shockers.pop(index)
            self.settings["openshock_shockers"] = shockers
            self._save()

    # ---- rules -------------------------------------------------------
    def get_rules(self, kind: str) -> List[Dict[str, Any]]:
        clean = _CLEANERS.get(kind)
        if clean is None:
            return []
        return [clean(r) for r in self.settings.get(kind, []) if isinstance(r, dict)]

    def get_all_rules(self) -> Dict[str, List[Dict[str, Any]]]:
        return {kind: self.get_rules(kind) for kind in RULE_KINDS}

    def add_rule(self, kind: str) -> int:
        """Append a fresh rule of `kind`; returns its index (or -1)."""
        clean = _CLEANERS.get(kind)
        if clean is None:
            return -1
        rules = self.get_rules(kind)
        rules.append(clean(dict(NEW_RULES[kind])))
        self.settings[kind] = rules
        self._save()
        return len(rules) - 1

    def set_rule(self, kind: str, index: int, rule: Dict[str, Any]) -> None:
        clean = _CLEANERS.get(kind)
        rules = self.get_rules(kind)
        if clean is None or not 0 <= index < len(rules):
            return
        rules[index] = clean(rule)
        self.settings[kind] = rules
        self._save()

    def set_rules(self, changed: Dict[str, List[Dict[str, Any]]]) -> None:
        """Whole lists of behaviours at once, in one save -- the ShockOSC
        sync changing the same value on several (shockosc_sync.py)."""
        touched = False
        for kind, rules in (changed or {}).items():
            clean = _CLEANERS.get(kind)
            if clean is None or not isinstance(rules, list):
                continue
            self.settings[kind] = [clean(r) for r in rules if isinstance(r, dict)]
            touched = True
        if touched:
            self._save()

    def add_rules(self, new: List[Any]) -> int:
        """Append several behaviours at once ((kind, rule) pairs) in one
        save -- the ShockOSC setup. Returns how many went in."""
        added = 0
        for kind, rule in new or ():
            clean = _CLEANERS.get(kind)
            if clean is None or not isinstance(rule, dict):
                continue
            rules = self.get_rules(kind)
            rules.append(clean(rule))
            self.settings[kind] = rules
            added += 1
        if added:
            self._save()
        return added

    def delete_rule(self, kind: str, index: int) -> None:
        rules = self.get_rules(kind)
        if kind in _CLEANERS and 0 <= index < len(rules):
            rules.pop(index)
            self.settings[kind] = rules
            self._save()
