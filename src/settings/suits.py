"""Suits page state: the bHaptics suit (the parts you have, per-position
on/strength, who it reacts to, whether it follows OWO's contacts), the OWO
suit (My OWO's address, frequency, per-muscle top and the overall ceiling
-- EMS, so it never connects on its own unless asked) and the zone routes
both share.

Every value is cleaned on the way in and out: this file feeds the last gate
before EMS reaches a person, and a hand-edited value must never widen it.
"""

import json
import math
from typing import Any, Dict, List

import body_map
from ._base import JsonSettingsManager
from ._paths import SUITS_SETTINGS_FILE

OWO_ABSOLUTE_MAX = 100          # 100 % = the user's calibrated max in My OWO
OWO_DEFAULT_GLOBAL_MAX = 60
FILTERS = ("TouchSelf", "TouchOthers", "PenSelf", "PenOthers")
ZONE_TYPES = ("Orf", "Pen", "Touch")


# OverflowError: json reads a 400-digit number as an int no float holds --
# it falls back like inf and any other garbage, instead of failing the load
# (which sets the whole file aside as .bak and starts from defaults).

def _int(value, lo: int, hi: int, default: int) -> int:
    try:
        f = float(value)
    except (TypeError, ValueError, OverflowError):
        return default
    if not math.isfinite(f):
        return default
    return max(lo, min(hi, int(round(f))))


def _float(value, lo: float, hi: float, default: float) -> float:
    try:
        f = float(value)
    except (TypeError, ValueError, OverflowError):
        return default
    if not math.isfinite(f):
        return default
    return max(lo, min(hi, f))


def _react(value) -> str:
    return value if value in body_map.REACT_CHOICES else body_map.REACT_BOTH


def clean_device(d: Any) -> Dict[str, Any]:
    d = d if isinstance(d, dict) else {}
    return {"enabled": bool(d.get("enabled", True)),
            "intensity": _int(d.get("intensity", 100), 0, 100, 100)}


def clean_muscle(m: Any) -> Dict[str, Any]:
    m = m if isinstance(m, dict) else {}
    return {"enabled": bool(m.get("enabled", True)),
            "max": _int(m.get("max", 100), 0, OWO_ABSOLUTE_MAX, 100)}


def clean_route(r: Any) -> Dict[str, Any]:
    r = r if isinstance(r, dict) else {}
    region = str(r.get("region", "") or "")
    zone_type = r.get("zone_type", "Orf")
    filters = [f for f in (r.get("filters") or []) if f in FILTERS]
    return {
        "enabled": bool(r.get("enabled", True)),
        "zone": str(r.get("zone", "") or "").strip(),
        "zone_type": zone_type if zone_type in ZONE_TYPES else "Orf",
        "filters": filters,
        "region": region if region in body_map.REGIONS else "VestFront",
        "gain": _float(r.get("gain", 1.0), 0.0, 4.0, 1.0),
    }


def _have(value) -> List[str]:
    """The bHaptics parts someone owns (body_map.PART_GROUPS keys, in that
    order). Not a list at all: the default, a vest; an empty list stays empty."""
    if not isinstance(value, list):
        return list(body_map.DEFAULT_HAVE)
    return [key for key, _name, _p in body_map.PART_GROUPS if key in value]


def _clean_bhaptics(b: Any) -> Dict[str, Any]:
    b = b if isinstance(b, dict) else {}
    devices = b.get("devices") if isinstance(b.get("devices"), dict) else {}
    return {
        "enabled": bool(b.get("enabled", True)),     # Home's On / Off (Stop / Resume)
        "auto_connect": bool(b.get("auto_connect", True)),
        "react_to": _react(b.get("react_to")),
        "follow_owo": bool(b.get("follow_owo", True)),
        "have": _have(b.get("have")),                # only these show on the page
        "devices": {pos: clean_device(devices.get(pos)) for pos in body_map.NODE_COUNTS},
    }


def _clean_owo(o: Any) -> Dict[str, Any]:
    o = o if isinstance(o, dict) else {}
    muscles = o.get("muscles") if isinstance(o.get("muscles"), dict) else {}
    return {
        "enabled": bool(o.get("enabled", True)),     # Home's On / Off (Stop all / Resume)
        "auto_connect": bool(o.get("auto_connect", False)),
        "host": str(o.get("host", "") or "").strip(),
        "game_id": str(o.get("game_id", "") or "").strip(),
        "frequency": _int(o.get("frequency", 50), 1, 100, 50),
        "react_to": _react(o.get("react_to")),
        "follow_bhaptics": bool(o.get("follow_bhaptics", True)),
        "global_max": _int(o.get("global_max", OWO_DEFAULT_GLOBAL_MAX), 0,
                           OWO_ABSOLUTE_MAX, OWO_DEFAULT_GLOBAL_MAX),
        "muscles": {m: clean_muscle(muscles.get(m)) for m in body_map.MUSCLES},
    }


class SuitsSettingsManager(JsonSettingsManager):
    FILE_PATH = SUITS_SETTINGS_FILE

    DEFAULTS: Dict[str, Any] = {
        "bhaptics": _clean_bhaptics({}),
        "owo": _clean_owo({}),
        "routes": [],
    }

    def _post_load(self, loaded: Dict[str, Any]) -> None:
        self.settings["bhaptics"] = _clean_bhaptics(self.settings.get("bhaptics"))
        self.settings["owo"] = _clean_owo(self.settings.get("owo"))
        routes = self.settings.get("routes")
        self.settings["routes"] = [clean_route(r) for r in routes] if isinstance(routes, list) else []

    # ---- whole snapshot (what the router gets) -------------------------
    def snapshot(self) -> Dict[str, Any]:
        """A deep copy -- safe to hand to another thread."""
        return json.loads(json.dumps(self.settings))

    # ---- bHaptics -------------------------------------------------------
    def bhaptics(self) -> Dict[str, Any]:
        return json.loads(json.dumps(self.settings["bhaptics"]))

    def set_bhaptics_enabled(self, value: bool) -> None:
        """Home's On / Off. Only the facade's bhaptics_stop_all / _resume
        set it, pausing the engine with it -- set_bhaptics_option ignores
        "enabled" so the two can't drift apart."""
        if bool(value) != self.settings["bhaptics"]["enabled"]:
            self.settings["bhaptics"] = _clean_bhaptics(
                {**self.settings["bhaptics"], "enabled": bool(value)})
            self._save()

    def set_bhaptics_option(self, key: str, value: Any) -> None:
        b = dict(self.settings["bhaptics"])
        if key in ("auto_connect", "follow_owo"):
            b[key] = bool(value)
        elif key == "react_to":
            b[key] = _react(value)
        elif key == "have":
            b[key] = _have(value)
        else:
            return
        self.settings["bhaptics"] = _clean_bhaptics(b)
        self._save()

    def add_bhaptics_have(self, positions) -> List[str]:
        """A part connected: it's one you have. Returns the names of the
        part groups that were new (nothing saved when there are none)."""
        have = self.settings["bhaptics"]["have"]
        new = [key for key, _n, _p in body_map.PART_GROUPS
               if key not in have and key in {body_map.group_of(p) for p in positions}]
        if new:
            self.set_bhaptics_option("have", have + new)
        return [name for key, name, _p in body_map.PART_GROUPS if key in new]

    def set_bhaptics_device(self, position: str, **changes) -> None:
        if position not in body_map.NODE_COUNTS:
            return
        b = self.settings["bhaptics"]
        dev = dict(b["devices"].get(position) or {})
        dev.update({k: v for k, v in changes.items() if k in ("enabled", "intensity")})
        b["devices"][position] = clean_device(dev)
        self._save()

    # ---- OWO ------------------------------------------------------------
    def owo(self) -> Dict[str, Any]:
        return json.loads(json.dumps(self.settings["owo"]))

    def set_owo_enabled(self, value: bool) -> None:
        """Home's On / Off (= the page's Stop all / Resume). Only the
        facade's owo_stop_all / owo_resume set it, pausing the engine with
        it -- set_owo_option ignores "enabled"."""
        if bool(value) != self.settings["owo"]["enabled"]:
            self.settings["owo"] = _clean_owo({**self.settings["owo"], "enabled": bool(value)})
            self._save()

    def set_owo_option(self, key: str, value: Any) -> None:
        o = dict(self.settings["owo"])
        if key not in ("auto_connect", "host", "game_id", "frequency",
                       "react_to", "follow_bhaptics", "global_max"):
            return
        o[key] = value
        self.settings["owo"] = _clean_owo(o)
        self._save()

    def set_owo_muscle(self, muscle: str, **changes) -> None:
        if muscle not in body_map.MUSCLES:
            return
        o = self.settings["owo"]
        m = dict(o["muscles"].get(muscle) or {})
        m.update({k: v for k, v in changes.items() if k in ("enabled", "max")})
        o["muscles"][muscle] = clean_muscle(m)
        self._save()

    # ---- zone routes ------------------------------------------------------
    def routes(self) -> List[Dict[str, Any]]:
        return json.loads(json.dumps(self.settings["routes"]))

    def add_route(self) -> int:
        self.settings["routes"].append(clean_route({"filters": ["TouchOthers"]}))
        self._save()
        return len(self.settings["routes"]) - 1

    def set_route(self, index: int, route: Dict[str, Any]) -> None:
        routes = self.settings["routes"]
        if 0 <= index < len(routes):
            routes[index] = clean_route(route)
            self._save()

    def delete_route(self, index: int) -> None:
        routes = self.settings["routes"]
        if 0 <= index < len(routes):
            del routes[index]
            self._save()
