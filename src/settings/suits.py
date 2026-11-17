"""Suits page state: the bHaptics suit (the parts you have, per-position
on/strength, who it reacts to, whether it follows OWO's contacts), the OWO
suit (My OWO's address, frequency, per-muscle top and the overall ceiling
-- EMS, so it never connects on its own unless asked), the zone routes
both share, and the haptic trackers (each spot's on / strength / top and
the avatar parameters it follows; where you placed a tracker by hand).

Every value is cleaned on the way in and out: this file feeds the last gate
before EMS reaches a person, and a hand-edited value must never widen it.
"""

import json
import math
from typing import Any, Dict, List

import antistuck
import body_map
import tracker_spots
from ._base import JsonSettingsManager
from ._paths import SUITS_SETTINGS_FILE

OWO_ABSOLUTE_MAX = 100          # 100 % = the user's calibrated max in My OWO
OWO_DEFAULT_GLOBAL_MAX = 60
TRACKER_DEFAULT_MAX = 80       # a plain motor on a Vive Tracker's pin: not full
MAX_PLACED = 64
# The kinds here with an anti-stuck of their own (antistuck.py): each one's
# block sits in its own section.
ANTISTUCK_KINDS = ("bhaptics", "owo", "trackers")
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
        "antistuck": antistuck.clean(b.get("antistuck")),
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
        "antistuck": antistuck.clean(o.get("antistuck")),
    }


def clean_tracker_spot(d: Any, spot: str) -> Dict[str, Any]:
    d = d if isinstance(d, dict) else {}
    return {"enabled": bool(d.get("enabled", True)),
            "intensity": _int(d.get("intensity", 100), 0, 100, 100),
            "max": _int(d.get("max", TRACKER_DEFAULT_MAX), 0, 100, TRACKER_DEFAULT_MAX),
            "params": tracker_spots.clean_params(d.get("params"), spot)}


def _clean_trackers(t: Any) -> Dict[str, Any]:
    """Spots by key; "placed" = serial -> spot for trackers placed by hand
    (the rest go where their SteamVR role says)."""
    t = t if isinstance(t, dict) else {}
    spots = t.get("spots") if isinstance(t.get("spots"), dict) else {}
    placed = t.get("placed") if isinstance(t.get("placed"), dict) else {}
    clean_placed: Dict[str, str] = {}
    for serial, spot in placed.items():
        serial = str(serial or "").strip()[:64]
        if serial and spot in tracker_spots.SPOT_NAMES and len(clean_placed) < MAX_PLACED:
            clean_placed[serial] = spot
    return {"spots": {k: clean_tracker_spot(spots.get(k), k) for k in tracker_spots.SPOT_KEYS},
            "placed": clean_placed,
            "antistuck": antistuck.clean(t.get("antistuck"))}


def history_asks(current: Dict[str, Any], target: Dict[str, Any]) -> list:
    """What an undo or redo from `current` to `target` must ask first
    (settings_history.py): the OWO suit (EMS) switched back on after its
    Stop all, and a ceiling raised -- OWO's overall one or a muscle's, a
    haptic tracker spot's Top -- and a kind's anti-stuck switched off or
    made to wait longer."""
    from settings_history import Ask, raised, turned_on
    asks = []
    for kind, words in (("bhaptics", "bHaptics anti-stuck"), ("owo", "OWO anti-stuck"),
                        ("trackers", "Trackers' anti-stuck")):
        for what in antistuck.loosens((current.get(kind) or {}).get("antistuck"),
                                      (target.get(kind) or {}).get("antistuck")):
            asks.append(Ask("confirm", f"{words}: {what}"))
    if turned_on(current, target, ("owo", "enabled"), True):
        asks.append(Ask("confirm", "switches the OWO suit back on"))
    if raised(current, target, ("owo", "global_max"), OWO_DEFAULT_GLOBAL_MAX):
        asks.append(Ask("confirm", f"raises OWO's overall ceiling to "
                        f"{target['owo']['global_max']} %"))
    for m in (target.get("owo") or {}).get("muscles") or {}:
        if raised(current, target, ("owo", "muscles", m, "max"), 100):
            asks.append(Ask("confirm", f"raises the OWO {m} ceiling"))
    for spot in (target.get("trackers") or {}).get("spots") or {}:
        if raised(current, target, ("trackers", "spots", spot, "max"), TRACKER_DEFAULT_MAX):
            asks.append(Ask("confirm", f"raises the {spot} tracker's Top"))
    return asks


class SuitsSettingsManager(JsonSettingsManager):
    HISTORY_KEY = "suits"
    HISTORY_LABEL = "Suits"

    @staticmethod
    def history_asks(current: Dict[str, Any], target: Dict[str, Any]) -> list:
        return history_asks(current, target)

    FILE_PATH = SUITS_SETTINGS_FILE

    DEFAULTS: Dict[str, Any] = {
        "bhaptics": _clean_bhaptics({}),
        "owo": _clean_owo({}),
        "routes": [],
        "trackers": _clean_trackers({}),
    }

    # The kinds whose anti-stuck this file didn't have yet: seed_antistuck
    # copies the toys' values into them once (all of them for a new file).
    _antistuck_unseeded = ANTISTUCK_KINDS

    def _post_load(self, loaded: Dict[str, Any]) -> None:
        self._antistuck_unseeded = tuple(
            k for k in ANTISTUCK_KINDS
            if not isinstance((loaded.get(k) if isinstance(loaded.get(k), dict) else {})
                              .get("antistuck"), dict))
        self.settings["bhaptics"] = _clean_bhaptics(self.settings.get("bhaptics"))
        self.settings["owo"] = _clean_owo(self.settings.get("owo"))
        self.settings["trackers"] = _clean_trackers(self.settings.get("trackers"))
        routes = self.settings.get("routes")
        self.settings["routes"] = [clean_route(r) for r in routes] if isinstance(routes, list) else []

    # ---- anti-stuck, one per kind (antistuck.py) --------------------------
    def seed_antistuck(self, values: Dict[str, Any]) -> None:
        """Before 2026-11-17 the suits and the trackers followed the toys'
        anti-stuck: a kind this file had no block for yet starts as a copy of
        the toys' `values`, so nothing anyone had set changes. Once."""
        kinds, self._antistuck_unseeded = self._antistuck_unseeded, ()
        for kind in kinds:
            self.settings[kind]["antistuck"] = antistuck.clean(values)
        if kinds:
            self._save()

    def antistuck(self, kind: str) -> Dict[str, Any]:
        """`{enabled, active_s, peaked_s}` of "bhaptics", "owo" or "trackers"."""
        return dict((self.settings.get(kind) or {}).get("antistuck") or antistuck.DEFAULTS)

    def set_antistuck(self, kind: str, **changes) -> None:
        if kind not in ANTISTUCK_KINDS:
            return
        new = antistuck.changed(self.antistuck(kind), **changes)
        if new != self.antistuck(kind):
            self.settings[kind]["antistuck"] = new
            self._save()

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

    # ---- haptic trackers --------------------------------------------------
    def trackers(self) -> Dict[str, Any]:
        return json.loads(json.dumps(self.settings["trackers"]))

    def set_tracker_spot(self, spot: str, **changes) -> None:
        if spot not in tracker_spots.SPOT_NAMES:
            return
        t = self.settings["trackers"]
        d = dict(t["spots"].get(spot) or {})
        d.update({k: v for k, v in changes.items()
                  if k in ("enabled", "intensity", "max", "params")})
        t["spots"][spot] = clean_tracker_spot(d, spot)
        self._save()

    def place_tracker(self, serial: str, spot) -> None:
        """Put a tracker on a spot by hand; None hands it back to its
        SteamVR role."""
        placed = dict(self.settings["trackers"]["placed"])
        if spot is None:
            placed.pop(str(serial), None)
        elif spot in tracker_spots.SPOT_NAMES:
            placed[str(serial)] = spot
        else:
            return
        self.settings["trackers"] = _clean_trackers(
            {**self.settings["trackers"], "placed": placed})
        self._save()
