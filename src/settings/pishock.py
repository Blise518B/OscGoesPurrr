"""Shocker settings: the USB port, the safety limits, the OpenShock
shocker list and the four behaviour lists the Shockers page edits.

  * ``zones``      — Touch zones: several bool contacts, each driving its
    own shockers (the neck the collar, a thigh its shocker ...), all at
    one ``intensity``, pulsed once or held like a trigger.
  * ``continuous`` — a float parameter (a proximity contact, say) runs the
    shocker for as long as it is above ``threshold``, strength scaled
    between ``min_int`` and ``max_int`` by the value.
  * ``triggers``   — one bool contact at a fixed ``intensity``: ``pulse``
    fires once per contact for ``duration_ms``, ``hold`` runs while the
    contact stays on.
  * ``impacts``    — a group of OnEnter contacts (receivers with different
    Min Velocity on the avatar), each ``tier`` with its own intensity; the
    strongest tier that fired picks the pulse.

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
TRIGGER_MODES = ("pulse", "hold")
RULE_KINDS = ("zones", "triggers", "continuous", "impacts")
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


def clean_continuous(rule: Dict[str, Any]) -> Dict[str, Any]:
    lo = _i(rule.get("min_int"), 5, 1, 100)
    hi = _i(rule.get("max_int"), 30, 1, 100)
    if lo > hi:
        lo, hi = hi, lo
    return {
        **_common(rule, "Continuous"),
        "param": _param(rule.get("param")),
        "threshold": _f(rule.get("threshold"), 0.0, 0.0, 0.99),
        "min_int": lo,
        "max_int": hi,
    }


def clean_trigger(rule: Dict[str, Any]) -> Dict[str, Any]:
    mode = str(rule.get("mode", "pulse"))
    return {
        **_common(rule, "Trigger"),
        "param": _param(rule.get("param")),
        "mode": mode if mode in TRIGGER_MODES else "pulse",
        "intensity": _i(rule.get("intensity"), 20, 1, 100),
        "duration_ms": _i(rule.get("duration_ms"), 500, 100, 15000),
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
}

_NEW_RULES = {
    "zones": {"name": "Touch zones", "intensity": 20, "duration_ms": 500,
              "zones": [{"param": "", "shockers": []}, {"param": "", "shockers": []}]},
    "continuous": {"name": "Continuous", "min_int": 5, "max_int": 30, "shockers": []},
    "triggers": {"name": "Contact", "intensity": 20, "duration_ms": 500, "shockers": []},
    "impacts": {"name": "Impact", "duration_ms": 500, "shockers": [], "tiers": [
        {"param": "", "intensity": 10},
        {"param": "", "intensity": 25},
        {"param": "", "intensity": 45},
    ]},
}

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


class PiShockSettingsManager(JsonSettingsManager):
    FILE_PATH = PISHOCK_SETTINGS_FILE

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
    }

    def _post_load(self, loaded: Dict[str, Any]) -> None:
        if "max_vibrate" not in loaded:
            # Older files: vibrates shared the shock cap -- keep that until
            # the user picks their own.
            self.settings["max_vibrate"] = self.settings.get("max_intensity", 30)
        for kind in RULE_KINDS:
            if not isinstance(self.settings.get(kind), list):
                self.settings[kind] = []
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
        rules.append(clean(dict(_NEW_RULES[kind])))
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

    def delete_rule(self, kind: str, index: int) -> None:
        rules = self.get_rules(kind)
        if kind in _CLEANERS and 0 <= index < len(rules):
            rules.pop(index)
            self.settings[kind] = rules
            self._save()
