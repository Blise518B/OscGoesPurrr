"""Statistics counted from the log -- and the suits' and trackers' on-time.

The log (event_log.py) keeps one record per thing that happened, for 30
days. This store counts those records as they arrive and keeps the counts
for good: the lifetime totals, and each session's (by the session timeline's
id, stats_history). Nothing here is a second record of the events -- only
numbers. What it counts, of what happened TO YOU (dir IN):

* **shocks, vibrates and beeps** that reached a shocker -- how many, the
  strongest, and the seconds they ran -- in all, per shocker, and by source.
  An operation on two shockers counts on each. A hold counts when it starts
  and adds its seconds when it ends (a let-go, a Stop, or the session
  closing); a hold held past the hub's longest hold runs in cycles of on and
  rest (pishock_engine), so its seconds are estimated that way
  (`held_on_time`).
* **the sources**: your avatar's behaviours (by name, the entry's `via`),
  you as Me (from your avatar menu or Party Mode, where the entry says so),
  each friend by name, each web remote guest. A friend's own menu or Party
  Mode isn't said over the link, so friends aren't split that way.
* **held back**: what was refused (Off, Pause, a switched-off action, the instance...).
* **friends' drive time** on your toys (their start / stop entries), and
  **friends' Avatar Remote sets** (every Avatar Remote entry from them).
* **worn**: the bHaptics parts', the OWO suit's and each haptic tracker's
  on-time, sampled once a second by the controller (no log entries).

Friends' names are kept unless the Statistics page's switch says not to
(`names=False` when counting: a friend counts as "A friend", a web remote
guest as "Web remote"); `forget_names` folds every name already kept into
those two.

Stored in ``stats_events.json`` next to stats.json, never inside it: the
full edition shares the folder and rewrites stats.json with only the keys it
knows. Shape::

    {"schema": 1,
     "lifetime": <tally>,
     "sessions": {<session id>: {"started_ts": float, "tally": <tally>}}}

    <tally> = {"ops": {<op>: [count, strongest, ms]},
               "shockers": {<name>: {<op>: [count, strongest, ms]}},
               "from": {<key>: {"name", "role", "last", "ops", "held",
                                "drive_s", "sets",
                                "via": {<via>: {"ops", "held"}}}},
               "worn": {<name>: seconds}}

Sealed like stats_tracker: no Qt, no threads, no wall-clock reads -- times
come from the entries and the caller. Loading is defensive the same way: a
missing file starts empty, an unreadable one is moved aside to ``.bak``,
and nothing here can crash app boot.
"""

import json
import os
from typing import Any, Dict, Iterable, List, Mapping, NamedTuple, Optional, Sequence, Tuple

import event_log as el
from stats_tracker import safe_count, safe_num
from utilities import atomic_write_json

_SCHEMA_VERSION = 1

OPS = el.SHOCKER_OPS                 # shock, vibrate, beep
SESSIONS_CAP = 500                   # as stats_history.SESSIONS_CAP
MARKS_CAP = 4000                     # marks on one session's timeline
NAME_MAX = 48

# The people counted: what reached you from them
COUNTED_ROLES = frozenset({el.ROLE_FRIEND, el.ROLE_ME, el.ROLE_WEB, el.ROLE_AVATAR})
COUNTED_KINDS = frozenset({el.SHOCK, el.TOYS, el.PARAMS})

# Names left out: everyone of a kind under one key
ANON_FRIEND, ANON_FRIEND_NAME = "friend", "A friend"
ANON_WEB, ANON_WEB_NAME = "web", "Web remote"
_ANON = {el.ROLE_FRIEND: (ANON_FRIEND, ANON_FRIEND_NAME), el.ROLE_WEB: (ANON_WEB, ANON_WEB_NAME)}

_DRIVE_ON = ("start", "back")
_DRIVE_OFF = ("stop", "dropout")


# ----------------------------------------------------------------------
# Who: the source of an entry
# ----------------------------------------------------------------------

class Source(NamedTuple):
    key: str          # who it is counted under
    name: str         # how they are called (the newest name wins)
    role: str
    via: str          # what it came through ("" for none / not known)


def source_of(ev: el.Event, names: bool = True) -> Source:
    """Who an entry is counted under. Your avatar and you (as Me) keep their
    own; with `names` off a friend is "A friend" and a web remote guest
    "Web remote"."""
    via = _clean(ev.via)
    if ev.role == el.ROLE_AVATAR:
        return Source(el.AVATAR, el.AVATAR_NAME, ev.role, via)
    if not names and ev.role in _ANON:
        key, name = _ANON[ev.role]
        return Source(key, name, ev.role, via)
    return Source(str(ev.who), _clean(ev.name) or str(ev.who), ev.role, via)


def via_label(via: str) -> str:
    """How what something came through reads ("menu" -> "Avatar menu"; a
    behaviour's name as it is)."""
    return el.VIA_LABELS.get(via, via)


def source_label(name: str, via: str = "") -> str:
    """A source as one line: "Your avatar · Touch zones · Neck",
    "You (Me) · Avatar menu", "Mika"."""
    return f"{name} · {via_label(via)}" if via else name


def _clean(text: Any) -> str:
    return " ".join(str(text or "").split())[:NAME_MAX]


# ----------------------------------------------------------------------
# A tally
# ----------------------------------------------------------------------

def fresh_tally() -> Dict[str, Any]:
    return {"ops": {}, "shockers": {}, "from": {}, "worn": {}}


def _op_entry(ops: Dict[str, List[int]], op: str) -> List[int]:
    cur = ops.get(op)
    if cur is None:
        cur = ops[op] = [0, 0, 0]
    return cur


def _op_add(ops: Dict[str, List[int]], op: str, level: Optional[int] = None,
            ms: Optional[int] = None, n: int = 1) -> None:
    cur = _op_entry(ops, op)
    cur[0] += n
    if level is not None:
        cur[1] = max(cur[1], int(level))
    if ms:
        cur[2] += max(0, int(ms))


def _person(tally: Dict[str, Any], src: Source, t: float) -> Dict[str, Any]:
    p = tally["from"].get(src.key)
    if p is None:
        p = tally["from"][src.key] = {"name": src.name, "role": src.role, "last": 0.0,
                                      "ops": {}, "held": 0, "drive_s": 0.0, "sets": 0,
                                      "via": {}}
    p["name"], p["role"] = src.name, src.role
    p["last"] = max(p["last"], float(t))
    return p


def _via(p: Dict[str, Any], via: str) -> Dict[str, Any]:
    v = p["via"].get(via)
    if v is None:
        v = p["via"][via] = {"ops": {}, "held": 0}
    return v


def held_on_time(length_s: float, caps: Optional[Tuple[float, float]] = None) -> float:
    """How long a hold held for `length_s` actually ran: past the hub's
    longest hold (`caps` = (longest hold s, rest s)) the engine rests the
    shocker, then a still-held input starts again -- on, rest, on ..."""
    length = max(0.0, float(length_s))
    if not caps:
        return length
    longest, rest = float(caps[0]), max(0.0, float(caps[1]))
    if longest <= 0:
        return length
    cycle = longest + rest
    full = int(length // cycle) if cycle > 0 else 0
    return full * longest + min(longest, length - full * cycle)


def is_mark(ev: el.Event) -> bool:
    """An entry the session timeline marks: a shock, vibrate or beep that
    reached one of your shockers (or a hold of one starting)."""
    return (ev.kind == el.SHOCK and ev.dir == el.IN and not ev.held
            and ev.role in COUNTED_ROLES and (ev.op in OPS or ev.op == "hold"))


# ----------------------------------------------------------------------
# The store
# ----------------------------------------------------------------------

class StatsEvents:
    """Lifetime + per-session counts of the log's entries, with atomic JSON
    persistence. See the module docstring for what is counted."""

    def __init__(self, file_path) -> None:
        self.file_path = file_path
        self.lifetime: Dict[str, Any] = fresh_tally()
        self.sessions: Dict[str, Dict[str, Any]] = {}
        # Open holds: (who, shocker) -> [start t, op, source, session id,
        # session start]; open drives: who -> [start t, source, sid, start].
        # In memory only: a hold or drive still open when the app closes is
        # closed then (close_all).
        self._holds: Dict[Tuple[str, str], List[Any]] = {}
        self._drives: Dict[str, List[Any]] = {}
        self._dirty = False
        self._load()

    # ------------------------------------------------------------------
    # Load / save
    # ------------------------------------------------------------------

    def _load(self) -> None:
        path = self.file_path
        if not path or not os.path.exists(path):
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                raw = json.load(f)
            if not isinstance(raw, dict):
                raise ValueError("not a dict")
            self.lifetime = clean_tally(raw.get("lifetime"))
            sessions = raw.get("sessions")
            if isinstance(sessions, dict):
                for sid, entry in sessions.items():
                    if isinstance(entry, dict):
                        self.sessions[str(sid)] = {
                            "started_ts": safe_num(entry.get("started_ts")),
                            "tally": clean_tally(entry.get("tally"))}
            self._prune()
        except Exception as e:
            print(f"StatsEvents load error: {e}, starting fresh")
            self.lifetime, self.sessions = fresh_tally(), {}
            try:
                os.replace(path, str(path) + ".bak")
            except OSError:
                pass

    def flush(self, force: bool = False) -> None:
        """Atomic write, when anything changed (or `force`)."""
        if not self._dirty and not force:
            return
        try:
            atomic_write_json(self.file_path, {"schema": _SCHEMA_VERSION,
                                               "lifetime": self.lifetime,
                                               "sessions": self.sessions})
            self._dirty = False
        except OSError as e:
            print(f"StatsEvents save error: {e}")

    def _session(self, sid: str, started: float) -> Optional[Dict[str, Any]]:
        if not sid:
            return None
        entry = self.sessions.get(sid)
        if entry is None:
            entry = self.sessions[sid] = {"started_ts": safe_num(started),
                                          "tally": fresh_tally()}
            self._prune()
        return entry["tally"]

    def _tallies(self, sid: str, started: float) -> List[Dict[str, Any]]:
        out = [self.lifetime]
        tally = self._session(sid, started)
        if tally is not None:
            out.append(tally)
        return out

    def _prune(self) -> None:
        if len(self.sessions) > SESSIONS_CAP:
            order = sorted(self.sessions, key=lambda s: self.sessions[s]["started_ts"])
            for sid in order[:len(self.sessions) - SESSIONS_CAP]:
                del self.sessions[sid]

    def keep_sessions(self, ids: Iterable[str]) -> None:
        """Forget the sessions whose timelines are gone (stats_history keeps
        its newest SESSIONS_CAP); the lifetime totals keep what they held."""
        keep = set(ids)
        gone = [sid for sid in self.sessions if sid not in keep]
        for sid in gone:
            del self.sessions[sid]
        if gone:
            self._dirty = True

    def reset(self) -> None:
        """Zero everything (Statistics' Reset)."""
        self.lifetime, self.sessions = fresh_tally(), {}
        self._holds, self._drives = {}, {}
        self.flush(force=True)

    # ------------------------------------------------------------------
    # Counting
    # ------------------------------------------------------------------

    def count(self, ev: el.Event, sid: str = "", started: float = 0.0, names: bool = True,
              hold_caps: Optional[Tuple[float, float]] = None) -> bool:
        """Count one log entry into the lifetime totals and session `sid`'s
        (started at `started`). `names`: the Statistics page keeps friends'
        names; `hold_caps`: (longest hold s, rest s) of the hub now. True
        when it counted anything."""
        if (ev.dir != el.IN or ev.kind not in COUNTED_KINDS
                or ev.role not in COUNTED_ROLES):
            return False
        src = source_of(ev, names)
        if ev.held:
            for tally in self._tallies(sid, started):
                p = _person(tally, src, ev.t)
                p["held"] += 1
                if src.via:
                    _via(p, src.via)["held"] += 1
            self._dirty = True
            return True
        if ev.kind == el.SHOCK:
            done = self._shock(ev, src, sid, started, hold_caps)
        elif ev.kind == el.TOYS:
            done = self._drive(ev, src, sid, started)
        else:
            for tally in self._tallies(sid, started):
                _person(tally, src, ev.t)["sets"] += 1
            done = True
        if done:
            self._dirty = True
        return done

    def _add_op(self, tallies: List[Dict[str, Any]], src: Source, t: float, shocker: str,
                op: str, level: Optional[int], ms: Optional[int], n: int = 1) -> None:
        for tally in tallies:
            _op_add(tally["ops"], op, level, ms, n)
            _op_add(tally["shockers"].setdefault(shocker, {}), op, level, ms, n)
            p = _person(tally, src, t)
            _op_add(p["ops"], op, level, ms, n)
            if src.via:
                _op_add(_via(p, src.via)["ops"], op, level, ms, n)

    def _shock(self, ev: el.Event, src: Source, sid: str, started: float,
               caps: Optional[Tuple[float, float]]) -> bool:
        shockers = [_clean(s) for s in ev.on] or [""]
        level = None if ev.op == "beep" else ev.level
        if ev.op in OPS:
            tallies = self._tallies(sid, started)
            for shocker in shockers:
                self._add_op(tallies, src, ev.t, shocker, ev.op, level, ev.ms)
            return True
        if ev.op == "hold":
            plays = ev.asked if ev.asked in OPS else "vibrate"
            tallies = self._tallies(sid, started)
            for shocker in shockers:
                key = (str(ev.who), shocker)
                if key in self._holds:
                    self._close_hold(key, ev.t, caps=caps)
                self._add_op(tallies, src, ev.t, shocker, plays,
                             None if plays == "beep" else ev.level, 0)
                self._holds[key] = [ev.t, plays, src, sid, started]
            return True
        if ev.op in ("let-go", "stop"):
            who = str(ev.who)
            keys = ([(who, _clean(s)) for s in ev.on] if ev.on
                    else [k for k in self._holds if k[0] == who])
            keys = [k for k in keys if k in self._holds]
            exact = ev.op == "let-go" and len(keys) == 1
            for key in keys:
                self._close_hold(key, ev.t, ms=ev.ms if exact else None,
                                 level=ev.level if ev.op == "let-go" else None, caps=caps)
            return bool(keys)
        return False

    def _close_hold(self, key: Tuple[str, str], t: float, ms: Optional[int] = None,
                    level: Optional[int] = None,
                    caps: Optional[Tuple[float, float]] = None) -> None:
        h = self._holds.pop(key, None)
        if h is None:
            return
        start, op, src, sid, started = h
        length = ms / 1000.0 if ms is not None else max(0.0, t - start)
        ran = int(round(held_on_time(length, caps) * 1000))
        self._add_op(self._tallies(sid, started), src, start, key[1], op,
                     None if op == "beep" else level, ran, n=0)
        self._dirty = True

    def _drive(self, ev: el.Event, src: Source, sid: str, started: float) -> bool:
        who = str(ev.who)
        if ev.op in _DRIVE_ON:
            if who not in self._drives:
                self._drives[who] = [ev.t, src, sid, started]
                for tally in self._tallies(sid, started):
                    _person(tally, src, ev.t)
            return True
        if ev.op in _DRIVE_OFF:
            return self._close_drive(who, ev.t)
        return False

    def _close_drive(self, who: str, t: float) -> bool:
        d = self._drives.pop(who, None)
        if d is None:
            return False
        start, src, sid, started = d
        for tally in self._tallies(sid, started):
            _person(tally, src, t)["drive_s"] += max(0.0, t - start)
        self._dirty = True
        return True

    def close_all(self, t: float, caps: Optional[Tuple[float, float]] = None) -> None:
        """End every hold and drive still open, at `t` (the session closing,
        statistics switched off)."""
        for key in list(self._holds):
            self._close_hold(key, t, caps=caps)
        for who in list(self._drives):
            self._close_drive(who, t)

    def add_worn(self, sid: str, started: float, dt: float, names: Iterable[str]) -> None:
        """One sample of the suits and trackers: `names` were on for `dt` s."""
        dt = safe_num(dt)
        names = [_clean(n) for n in names if _clean(n)]
        if dt <= 0 or not names:
            return
        for tally in self._tallies(sid, started):
            worn = tally["worn"]
            for name in names:
                worn[name] = worn.get(name, 0.0) + dt
        self._dirty = True

    # ------------------------------------------------------------------
    # Names
    # ------------------------------------------------------------------

    def has_names(self) -> bool:
        """Is any friend's or web remote guest's name kept?"""
        return any(p.get("role") in _ANON and key not in (ANON_FRIEND, ANON_WEB)
                   for tally in self._all_tallies() for key, p in tally["from"].items())

    def forget_names(self) -> bool:
        """Fold every friend into "A friend" and every web remote guest into
        "Web remote" -- in the lifetime totals, every session and what is
        open. True when anything changed."""
        changed = False
        for tally in self._all_tallies():
            changed |= _fold_names(tally)
        for store in (self._holds, self._drives):
            for entry in store.values():
                i = 2 if store is self._holds else 1
                src = entry[i]
                if src.role in _ANON:
                    key, name = _ANON[src.role]
                    entry[i] = Source(key, name, src.role, src.via)
        if changed:
            self._dirty = True
        return changed

    def _all_tallies(self) -> List[Dict[str, Any]]:
        return [self.lifetime] + [e["tally"] for e in self.sessions.values()]

    # ------------------------------------------------------------------
    # Read model
    # ------------------------------------------------------------------

    def lifetime_view(self) -> Dict[str, Any]:
        return view(self.lifetime)

    def session_view(self, sid: str) -> Optional[Dict[str, Any]]:
        entry = self.sessions.get(str(sid or ""))
        return view(entry["tally"]) if entry is not None else None


def _merge_ops(into: Dict[str, List[int]], ops: Mapping[str, List[int]]) -> None:
    for op, (n, top, ms) in ops.items():
        cur = _op_entry(into, op)
        cur[0] += n
        cur[1] = max(cur[1], top)
        cur[2] += ms


def _fold_names(tally: Dict[str, Any]) -> bool:
    changed = False
    for key in list(tally["from"]):
        p = tally["from"][key]
        anon = _ANON.get(p.get("role"))
        if anon is None or key == anon[0]:
            continue
        changed = True
        del tally["from"][key]
        into = tally["from"].get(anon[0])
        if into is None:
            tally["from"][anon[0]] = dict(p, name=anon[1])
            continue
        _merge_ops(into["ops"], p["ops"])
        into["held"] += p["held"]
        into["drive_s"] += p["drive_s"]
        into["sets"] += p["sets"]
        into["last"] = max(into["last"], p["last"])
        for via, v in p["via"].items():
            iv = _via(into, via)
            _merge_ops(iv["ops"], v["ops"])
            iv["held"] += v["held"]
    return changed


# ----------------------------------------------------------------------
# Loading a tally (defensive: a hand-edited file degrades per field)
# ----------------------------------------------------------------------

def _clean_ops(raw: Any) -> Dict[str, List[int]]:
    out: Dict[str, List[int]] = {}
    if isinstance(raw, dict):
        for op, v in raw.items():
            if op in OPS and isinstance(v, list) and len(v) == 3:
                out[op] = [safe_count(v[0]), min(100, safe_count(v[1])), safe_count(v[2])]
    return out


def clean_tally(raw: Any) -> Dict[str, Any]:
    out = fresh_tally()
    if not isinstance(raw, dict):
        return out
    out["ops"] = _clean_ops(raw.get("ops"))
    shockers = raw.get("shockers")
    if isinstance(shockers, dict):
        for name, ops in shockers.items():
            out["shockers"][_clean(name)] = _clean_ops(ops)
    people = raw.get("from")
    if isinstance(people, dict):
        for key, p in people.items():
            if not isinstance(p, dict):
                continue
            via = {}
            if isinstance(p.get("via"), dict):
                for name, v in p["via"].items():
                    if isinstance(v, dict):
                        via[_clean(name)] = {"ops": _clean_ops(v.get("ops")),
                                             "held": safe_count(v.get("held"))}
            role = str(p.get("role") or el.ROLE_FRIEND)
            out["from"][str(key)] = {
                "name": _clean(p.get("name")) or str(key),
                "role": role if role in COUNTED_ROLES else el.ROLE_FRIEND,
                "last": safe_num(p.get("last")), "ops": _clean_ops(p.get("ops")),
                "held": safe_count(p.get("held")), "drive_s": safe_num(p.get("drive_s")),
                "sets": safe_count(p.get("sets")), "via": via}
    worn = raw.get("worn")
    if isinstance(worn, dict):
        for name, s in worn.items():
            out["worn"][_clean(name)] = safe_num(s)
    return out


# ----------------------------------------------------------------------
# What the page reads
# ----------------------------------------------------------------------

def ops_view(ops: Mapping[str, List[int]]) -> Dict[str, Dict[str, Any]]:
    """{op: {"n", "max", "s"}} for all three ops (zeros where none)."""
    out = {}
    for op in OPS:
        n, top, ms = ops.get(op, (0, 0, 0))
        out[op] = {"n": int(n), "max": int(top), "s": round(ms / 1000.0, 1)}
    return out


def _weight(p: Mapping[str, Any]) -> tuple:
    ops = p["ops"]
    return (ops["shock"]["n"], ops["vibrate"]["n"] + ops["beep"]["n"], p["drive_s"],
            p["sets"], p["held"])


def view(tally: Mapping[str, Any]) -> Dict[str, Any]:
    """A tally as the Statistics page shows it: "ops" (all three, see
    ops_view), "people" (most shocks first; each with name, role, last,
    ops, held, drive_s, sets and "via" -- the same per behaviour / menu /
    Party Mode), "shockers" (by name, each with its ops), "worn" ([name,
    seconds], most first) and "any" (anything at all)."""
    people = []
    for key, p in tally["from"].items():
        via = [{"via": v, "label": via_label(v), "ops": ops_view(d["ops"]), "held": d["held"]}
               for v, d in p["via"].items()]
        via.sort(key=lambda d: (-d["ops"]["shock"]["n"],
                                -(d["ops"]["vibrate"]["n"] + d["ops"]["beep"]["n"]), d["label"]))
        people.append({"key": key, "name": p["name"], "role": p["role"], "last": p["last"],
                       "ops": ops_view(p["ops"]), "held": p["held"],
                       "drive_s": round(p["drive_s"], 1), "sets": p["sets"], "via": via})
    people.sort(key=lambda p: tuple(-x for x in _weight(p)) + (p["name"].casefold(),))
    shockers = [{"name": name or "A shocker", "ops": ops_view(ops)}
                for name, ops in sorted(tally["shockers"].items(), key=lambda kv: kv[0].casefold())]
    worn = sorted(([k, round(v, 1)] for k, v in tally["worn"].items() if v > 0),
                  key=lambda kv: (-kv[1], kv[0]))
    return {"ops": ops_view(tally["ops"]), "people": people, "shockers": shockers,
            "worn": worn, "any": bool(tally["ops"] or tally["from"] or worn)}


def marks(events: Sequence[el.Event], names: bool = True,
          cap: int = MARKS_CAP) -> List[Dict[str, Any]]:
    """A session timeline's marks, from the log's entries for its stretch
    (oldest first): every shock, vibrate and beep that reached a shocker --
    {t, op, level, ms, on, who (who did it, as one line), hold}. A hold's
    `ms` is how long it was held (None while it still is)."""
    out: List[Dict[str, Any]] = []
    open_: Dict[Tuple[str, str], Dict[str, Any]] = {}
    for ev in events:
        if ev.kind != el.SHOCK or ev.dir != el.IN or ev.held or ev.role not in COUNTED_ROLES:
            continue
        src = source_of(ev, names)
        who = source_label(src.name, src.via)
        if ev.op in OPS:
            out.append({"t": ev.t, "op": ev.op, "level": None if ev.op == "beep" else ev.level,
                        "ms": ev.ms, "on": list(ev.on), "who": who, "hold": False})
        elif ev.op == "hold":
            plays = ev.asked if ev.asked in OPS else "vibrate"
            for shocker in (ev.on or ("",)):
                m = {"t": ev.t, "op": plays, "level": None if plays == "beep" else ev.level,
                     "ms": None, "on": [shocker] if shocker else [], "who": who, "hold": True}
                out.append(m)
                open_[(str(ev.who), shocker)] = m
        elif ev.op in ("let-go", "stop"):
            who_id = str(ev.who)
            keys = ([(who_id, s) for s in ev.on] if ev.on
                    else [k for k in open_ if k[0] == who_id])
            for key in keys:
                m = open_.pop(key, None)
                if m is None:
                    continue
                m["ms"] = (int(ev.ms) if ev.op == "let-go" and ev.ms is not None and len(keys) == 1
                           else int(max(0.0, ev.t - m["t"]) * 1000))
                if ev.op == "let-go" and ev.level is not None and m["level"] is not None:
                    m["level"] = max(m["level"], ev.level)
    return out[-cap:]
