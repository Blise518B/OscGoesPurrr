"""Who a session was with — the per-person statistics.

A session (one app run, see stats_history) can be tagged with people in
two ways, each with one or more names:

* **the whole session** — one tag per session;
* **a stretch of it** — marked on the session's timeline, as many as you
  like, for a session that had more than one person in it.

Optionally the app tags stretches by itself (controllers/people_facade.py,
opt-in): while VRChat's log says you are alone in an instance with exactly
one other person, that stretch carries their name (`auto`, with their
VRChat user id in `vrc`).

Each person is credited with the activity inside their tags: active time,
thrusts, and their peak pace (the most thrusts in one minute). Two people
on the same stretch both get all of it, and a person tagged twice on
overlapping stretches is counted once. A name is matched without regard to
case or doubled spaces, so "alex" and "Alex" are one person.

Stored in ``stats_people.json`` next to stats.json, never inside it: the
full edition shares the folder and rewrites stats.json with only the keys
it knows. Shape::

    {"schema": 1,
     "sessions": {<session id>: {
         "started_ts": float,
         "tags": [{"id": int, "people": [str], "whole": bool,
                   "start": float, "end": float | null,
                   "auto": bool, "vrc": str}],
         "credit": {<name>: {"active_s", "thrusts", "peak_pace"}}}},
     "vrc_names": {<VRChat user id>: <the name first seen for it>}}

`credit` caches what a finished session gives each person. Any tag edit
drops it and the controller works it out again from the session's timeline
when it is next needed (`needs_credit`); a re-gated timeline drops every
cache (`invalidate_all`). The running session is never cached — it grows.
Sessions recorded before timelines existed ("summary:<start>" ids) can
only be tagged whole; their credit is their totals.

Sealed like stats_tracker: no Qt, no threads, no wall-clock reads. Loading
is defensive the same way: a missing file starts empty, an unreadable one
is moved aside to ``.bak``, and nothing here can crash app boot.
"""

import json
import os
from typing import Any, Dict, Iterable, List, Mapping, Optional, Set, Tuple

from stats_tracker import safe_count, safe_num
from utilities import atomic_write_json


_SCHEMA_VERSION = 1

# A name longer than this is cut (a pasted paragraph is not a name).
_NAME_MAX = 48

# Peak pace window, in seconds (one minute, like everywhere else).
_PACE_S = 60.0


# ----------------------------------------------------------------------
# Names
# ----------------------------------------------------------------------

def clean_name(name: Any) -> str:
    """A name as stored: trimmed, inner whitespace collapsed, capped."""
    return " ".join(str(name or "").split())[:_NAME_MAX].strip()


def person_key(name: Any) -> str:
    """What makes two spellings the same person."""
    return clean_name(name).casefold()


def clean_names(names: Any) -> List[str]:
    """A list of names from a list or a comma-separated string: cleaned,
    blanks dropped, the same person only once (first spelling wins)."""
    if isinstance(names, str):
        names = names.split(",")
    out: List[str] = []
    seen: Set[str] = set()
    for n in names or ():
        c = clean_name(n)
        k = c.casefold()
        if c and k not in seen:
            seen.add(k)
            out.append(c)
    return out


# ----------------------------------------------------------------------
# Credit — pure
# ----------------------------------------------------------------------

def _tag_buckets(tag: Mapping[str, Any], buckets: Iterable[int],
                 started: float, bs: float, end_epoch: float) -> Set[int]:
    """The bucket indices a tag covers: all of them for a whole-session
    tag, else every bucket whose middle lies inside the stretch (an open
    stretch runs to `end_epoch`)."""
    if tag.get("whole"):
        return set(buckets)
    s = safe_num(tag.get("start"))
    e = tag.get("end")
    e = end_epoch if e is None else safe_num(e)
    return {i for i in buckets if s <= started + (i + 0.5) * bs < e}


def _measure(buckets: Mapping[int, Mapping[str, Any]], idx: Set[int],
             bs: float) -> Dict[str, Any]:
    """Active seconds, thrusts and peak pace over a set of buckets."""
    active = 0.0
    thrusts = 0
    for i in idx:
        b = buckets[i]
        active += safe_num(b.get("a"))
        thrusts += safe_count(b.get("t"))
    width = max(1, int(round(_PACE_S / bs)))
    peak = 0
    for i in idx:
        s = sum(safe_count(buckets[j].get("t")) for j in range(i, i + width)
                if j in idx)
        if s > peak:
            peak = s
    return {"active_s": round(active, 1), "thrusts": int(thrusts),
            "peak_pace": int(peak)}


def credit(tl: Mapping[str, Any], tags: Iterable[Mapping[str, Any]],
           end_epoch: float) -> Dict[str, Dict[str, Any]]:
    """What each person in `tags` gets from timeline `tl` (a stats_history
    timeline: started_ts, bucket_s, buckets {i: {"a", "t", ...}}). Open
    stretches run to `end_epoch`. Keyed by each person's first spelling;
    people with nothing in their stretches still appear, at zero."""
    buckets = tl.get("buckets") or {}
    bs = float(tl.get("bucket_s") or 10)
    started = safe_num(tl.get("started_ts"))
    covered: Dict[str, Set[int]] = {}
    spelling: Dict[str, str] = {}
    for tag in tags:
        idx = _tag_buckets(tag, buckets, started, bs, end_epoch)
        for name in tag.get("people") or ():
            k = person_key(name)
            if not k:
                continue
            spelling.setdefault(k, clean_name(name))
            covered.setdefault(k, set()).update(idx)
    return {spelling[k]: _measure(buckets, idx, bs)
            for k, idx in covered.items()}


def tag_measure(tl: Mapping[str, Any], tag: Mapping[str, Any],
                end_epoch: float) -> Dict[str, Any]:
    """Active seconds, thrusts and peak pace inside one tag."""
    buckets = tl.get("buckets") or {}
    bs = float(tl.get("bucket_s") or 10)
    idx = _tag_buckets(tag, buckets, safe_num(tl.get("started_ts")), bs, end_epoch)
    return _measure(buckets, idx, bs)


def held_nothing(tl: Dict[str, Any], tag: Dict[str, Any], end: float) -> bool:
    """A stretch with no active time and no thrusts in it -- what a stretch
    the VRChat log tagged is dropped for."""
    m = tag_measure(tl, tag, end)
    return not m["active_s"] and not m["thrusts"]


def credit_from_totals(tags: Iterable[Mapping[str, Any]], active_s: float,
                       thrusts: int) -> Dict[str, Dict[str, Any]]:
    """Credit for a session that has only its totals (no timeline): the
    whole-session tag's people get all of it. No peak pace is known."""
    out: Dict[str, Dict[str, Any]] = {}
    for tag in tags:
        if not tag.get("whole"):
            continue
        for name in tag.get("people") or ():
            c = clean_name(name)
            if c and person_key(c) not in {person_key(n) for n in out}:
                out[c] = {"active_s": round(safe_num(active_s), 1),
                          "thrusts": safe_count(thrusts), "peak_pace": 0}
    return out


# ----------------------------------------------------------------------
# The store
# ----------------------------------------------------------------------

def _sanitize_tag(raw: Any) -> Optional[Dict[str, Any]]:
    if not isinstance(raw, dict):
        return None
    people = clean_names(raw.get("people") if isinstance(raw.get("people"), list) else [])
    if not people:
        return None
    tag: Dict[str, Any] = {"id": safe_count(raw.get("id")), "people": people,
                           "whole": bool(raw.get("whole"))}
    if not tag["whole"]:
        start = safe_num(raw.get("start"))
        end = raw.get("end")
        end = None if end is None else safe_num(end)
        if not start or (end is not None and end <= start):
            return None
        tag["start"], tag["end"] = start, end
    if raw.get("auto"):
        tag["auto"] = True
        tag["vrc"] = str(raw.get("vrc") or "")
    return tag


def _sanitize_credit(raw: Any) -> Optional[Dict[str, Dict[str, Any]]]:
    if not isinstance(raw, dict):
        return None
    out = {}
    for name, v in raw.items():
        c = clean_name(name)
        if c and isinstance(v, dict):
            out[c] = {"active_s": safe_num(v.get("active_s")),
                      "thrusts": safe_count(v.get("thrusts")),
                      "peak_pace": safe_count(v.get("peak_pace"))}
    return out


class StatsPeople:
    """Session tags + cached per-person credit with atomic JSON
    persistence. See the module docstring for the file's shape."""

    def __init__(self, file_path) -> None:
        self.file_path = file_path
        # session id -> {"started_ts", "tags", optional "credit"}
        self.sessions: Dict[str, Dict[str, Any]] = {}
        # VRChat user id -> the name it was first seen with
        self.vrc_names: Dict[str, str] = {}
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
                raise ValueError("not an object")
        except (OSError, ValueError) as e:
            print(f"StatsPeople: unreadable {path}, starting empty: {e}")
            try:
                os.replace(path, str(path) + ".bak")
            except OSError:
                pass
            return
        sessions = raw.get("sessions")
        if isinstance(sessions, dict):
            for sid, s in sessions.items():
                if not isinstance(s, dict):
                    continue
                tags = [t for t in (_sanitize_tag(r) for r in s.get("tags") or [])
                        if t is not None]
                if not tags:
                    continue
                entry = {"started_ts": safe_num(s.get("started_ts")), "tags": tags}
                cred = _sanitize_credit(s.get("credit"))
                if cred is not None:
                    entry["credit"] = cred
                self.sessions[str(sid)] = entry
        names = raw.get("vrc_names")
        if isinstance(names, dict):
            for uid, name in names.items():
                c = clean_name(name)
                if c:
                    self.vrc_names[str(uid)] = c

    def flush(self, force: bool = False) -> None:
        """Write the file if anything changed. Atomic; an OSError leaves
        the data dirty for the next try."""
        if not (self._dirty or force) or not self.file_path:
            return
        try:
            atomic_write_json(self.file_path, {
                "schema": _SCHEMA_VERSION,
                "sessions": self.sessions,
                "vrc_names": self.vrc_names,
            })
            self._dirty = False
        except OSError as e:
            print(f"StatsPeople save error: {e}")

    def reset(self) -> None:
        """Forget every tag and every name."""
        self.sessions = {}
        self.vrc_names = {}
        self._dirty = True
        self.flush()

    # ------------------------------------------------------------------
    # Reading
    # ------------------------------------------------------------------

    def tags(self, sid: str) -> List[Dict[str, Any]]:
        """A session's tags (copies), whole-session tag first, then the
        stretches in time order."""
        s = self.sessions.get(sid)
        if not s:
            return []
        out = [dict(t, people=list(t["people"])) for t in s["tags"]]
        out.sort(key=lambda t: (not t["whole"], t.get("start", 0.0)))
        return out

    def people_in(self, sid: str) -> List[str]:
        """Everyone tagged anywhere in a session, first spelling, in the
        order `tags` lists them."""
        return clean_names(n for t in self.tags(sid) for n in t["people"])

    def whole_people(self, sid: str) -> List[str]:
        """Who the whole session is tagged with ([] when it isn't)."""
        s = self.sessions.get(sid)
        whole = next((t for t in (s["tags"] if s else ()) if t["whole"]), None)
        return list(whole["people"]) if whole else []

    def known_names(self) -> List[str]:
        """Every name ever tagged (latest spelling per person), A to Z."""
        latest: Dict[str, Tuple[float, str]] = {}
        for s in self.sessions.values():
            for t in s["tags"]:
                for n in t["people"]:
                    k = person_key(n)
                    if k not in latest or s["started_ts"] >= latest[k][0]:
                        latest[k] = (s["started_ts"], n)
        return sorted((v[1] for v in latest.values()), key=str.casefold)

    def needs_credit(self, sid: str) -> bool:
        s = self.sessions.get(sid)
        return bool(s) and "credit" not in s

    def tagged_sessions(self) -> List[str]:
        return list(self.sessions)

    # ------------------------------------------------------------------
    # Editing
    # ------------------------------------------------------------------

    def _session(self, sid: str, started_ts: float) -> Dict[str, Any]:
        s = self.sessions.get(sid)
        if s is None:
            s = self.sessions[sid] = {"started_ts": safe_num(started_ts), "tags": []}
        return s

    def _next_id(self, s: Mapping[str, Any]) -> int:
        return max((t["id"] for t in s["tags"]), default=0) + 1

    def _changed(self, sid: str) -> None:
        s = self.sessions.get(sid)
        if s is not None:
            s.pop("credit", None)
            if not s["tags"]:
                del self.sessions[sid]
        self._dirty = True

    def tag_whole(self, sid: str, started_ts: float, names: Any) -> None:
        """Set who the whole session was with. No names removes the
        whole-session tag."""
        people = clean_names(names)
        s = self._session(sid, started_ts)
        whole = next((t for t in s["tags"] if t["whole"]), None)
        if not people:
            s["tags"] = [t for t in s["tags"] if not t["whole"]]
        elif whole is not None:
            whole["people"] = people
        else:
            s["tags"].append({"id": self._next_id(s), "people": people,
                              "whole": True})
        self._changed(sid)

    def add_stretch(self, sid: str, started_ts: float, start: float,
                    end: Optional[float], names: Any, auto: bool = False,
                    vrc: str = "") -> int:
        """Tag a stretch of a session; returns the new tag's id, or 0 when
        there was nothing to tag (no names, an empty stretch). `end` None
        leaves it open: it runs to the session's end."""
        people = clean_names(names)
        start = safe_num(start)
        end = None if end is None else safe_num(end)
        if not people or not start or (end is not None and end <= start):
            return 0
        s = self._session(sid, started_ts)
        tag: Dict[str, Any] = {"id": self._next_id(s), "people": people,
                               "whole": False, "start": start, "end": end}
        if auto:
            tag["auto"] = True
            tag["vrc"] = str(vrc or "")
        s["tags"].append(tag)
        self._changed(sid)
        return tag["id"]

    def remove_tag(self, sid: str, tag_id: int) -> bool:
        s = self.sessions.get(sid)
        if not s:
            return False
        before = len(s["tags"])
        s["tags"] = [t for t in s["tags"] if t["id"] != int(tag_id)]
        if len(s["tags"]) == before:
            return False
        self._changed(sid)
        return True

    def close_stretch(self, sid: str, tag_id: int, end: float) -> bool:
        """Give an open stretch its end. One that would end before it
        starts is removed instead."""
        s = self.sessions.get(sid)
        tag = next((t for t in (s["tags"] if s else ())
                    if t["id"] == int(tag_id)), None)
        if tag is None or tag["whole"] or tag.get("end") is not None:
            return False
        if safe_num(end) <= tag["start"]:
            return self.remove_tag(sid, tag_id)
        tag["end"] = safe_num(end)
        self._changed(sid)
        return True

    def reopen_stretch(self, sid: str, tag_id: int) -> bool:
        """Make an ended stretch open again (its person came back)."""
        s = self.sessions.get(sid)
        tag = next((t for t in (s["tags"] if s else ())
                    if t["id"] == int(tag_id)), None)
        if tag is None or tag["whole"] or tag.get("end") is None:
            return False
        tag["end"] = None
        self._changed(sid)
        return True

    def close_open(self, sid: str, end: float) -> None:
        """End every stretch of a session that is still open."""
        s = self.sessions.get(sid)
        for t in list(s["tags"] if s else ()):
            if not t["whole"] and t.get("end") is None:
                self.close_stretch(sid, t["id"], end)

    def drop_session(self, sid: str) -> None:
        if self.sessions.pop(sid, None) is not None:
            self._dirty = True

    def set_credit(self, sid: str, cred: Mapping[str, Mapping[str, Any]]) -> None:
        s = self.sessions.get(sid)
        if s is None:
            return
        s["credit"] = {clean_name(n): dict(v) for n, v in cred.items()}
        self._dirty = True

    def invalidate_all(self) -> None:
        """Drop every cached credit (the timelines they came from changed)."""
        for s in self.sessions.values():
            s.pop("credit", None)
        self._dirty = True

    def vrc_name(self, user_id: str, name: str) -> str:
        """The name a VRChat user is tagged with: the one they were first
        seen with, so a later display-name change stays the same person."""
        uid = str(user_id or "")
        c = clean_name(name)
        if not uid:
            return c
        known = self.vrc_names.get(uid)
        if known:
            return known
        if c:
            self.vrc_names[uid] = c
            self._dirty = True
        return c

    # ------------------------------------------------------------------
    # The People table
    # ------------------------------------------------------------------

    def table(self, extra: Optional[Mapping[str, Tuple[float, Mapping[str, Mapping[str, Any]]]]] = None
              ) -> List[Dict[str, Any]]:
        """One row per person, most thrusts first: name (latest spelling),
        sessions, active_s, thrusts, peak_pace, last_ts. Built from the
        cached credit; `extra` adds sessions that aren't cached (the
        running one): {sid: (started_ts, credit)}, and wins over a cache."""
        per: Dict[str, Dict[str, Any]] = {}
        sources: Dict[str, Tuple[float, Mapping[str, Any]]] = {}
        for sid, s in self.sessions.items():
            if "credit" in s:
                sources[sid] = (s["started_ts"], s["credit"])
        for sid, src in (extra or {}).items():
            sources[sid] = src
        for _sid, (started, cred) in sources.items():
            for name, v in cred.items():
                k = person_key(name)
                if not k:
                    continue
                active = safe_num(v.get("active_s"))
                thrusts = safe_count(v.get("thrusts"))
                row = per.get(k)
                if row is None:
                    row = per[k] = {"name": clean_name(name), "sessions": 0,
                                    "active_s": 0.0, "thrusts": 0,
                                    "peak_pace": 0, "last_ts": 0.0}
                if started >= row["last_ts"]:
                    row["last_ts"] = started
                    row["name"] = clean_name(name)
                if active <= 0.0 and thrusts <= 0:
                    continue
                row["sessions"] += 1
                row["active_s"] += active
                row["thrusts"] += thrusts
                row["peak_pace"] = max(row["peak_pace"], safe_count(v.get("peak_pace")))
        # Someone whose stretches held nothing has no statistics to show.
        rows = [r for r in per.values() if r["sessions"]]
        for r in rows:
            r["active_s"] = round(r["active_s"], 1)
        rows.sort(key=lambda r: (-r["thrusts"], -r["active_s"], r["name"].casefold()))
        return rows
