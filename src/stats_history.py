"""Usage history — per-session timelines and per-hour totals.

The detail behind the Statistics page's charts. It lives next to
`stats.json`, never inside it: the full edition shares the AppData folder,
and its StatsTracker rewrites stats.json with only the keys it knows, so
anything new stored in there would vanish on its next save.

Two stores:

* **Session timelines** — `stats_sessions/<id>.json`, one per app run that
  saw activity, in 10-second buckets: active seconds, thrusts, each toy's
  on-time and level, each zone's contact time. Only buckets with activity
  are stored, so a long, mostly idle evening stays small. The running
  session is `<id>.live.json`, rewritten about once a minute; a file still
  named `.live` at the next launch belongs to a run that never shut down
  cleanly and is closed then (`recover_unfinished`). `index.json` keeps a
  summary + sparkline per finished session, so the session list never has
  to parse every timeline.
* **Hourly totals** — `stats_hours.json`: active seconds and thrusts per
  local clock hour, kept forever. The time-of-day, weekday and month charts
  are built from it. The same file keeps, apart from what was measured, a
  one-time *estimate* of the hours before this history existed
  (`stats_backfill.py`); its presence — even empty — marks that estimate
  as done.

Sealed like stats_tracker: no Qt, no threads, no wall-clock reads — the
caller hands in epochs, so every behaviour is deterministic under test.
Every load path is defensive: a missing file starts fresh, an unreadable
one is moved aside to `.bak`, and nothing here can crash app boot.

The pure helpers at the bottom (`dense`, `analyse`, `weekday_hour`,
`month_days`, `fun_facts`) turn the stored data into what the charts draw.
"""

import json
import os
import re
import time
from datetime import date
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Tuple

from stats_gate import (
    ActivityGate, CONTACT_GRACE_S, CONTACT_WINDOW_S, GATE_VERSION, LEAD_S,
    MIN_CONTACT_S, MIN_THRUSTS, SCENE_END_S, STREAK_GAP_S,
)
from stats_tracker import _count, _num
from utilities import atomic_write_json


_SCHEMA_VERSION = 1

# Timeline resolution. Fine enough that a session graph looks alive,
# coarse enough that a seven-hour evening is a few thousand rows at most.
BUCKET_S = 10

# Finished timelines kept on disk (the oldest go first). A busy session is
# a few tens of KB, so this caps the folder at roughly 10-20 MB.
SESSIONS_CAP = 500

# Points in each session's list sparkline.
SPARK_POINTS = 48

_LIVE_SUFFIX = ".live.json"
_INDEX_NAME = "index.json"
_ID_FORMAT = "%Y%m%d-%H%M%S"
_HOUR_FORMAT = "%Y-%m-%dT%H"
_ID_RE = re.compile(r"\d{8}-\d{6}(?:-\d+)?")
_HOUR_RE = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}")

# A pause this short (in buckets) doesn't break a streak — re-positioning,
# a contact flickering off for a moment.
_STREAK_GAP_BUCKETS = 3

# Idle stretches shorter than this aren't worth calling a break.
_MIN_BREAK_S = 60.0

# "Night owl" hours for the lifetime fun facts: 22:00 to 03:59.
NIGHT_HOURS = frozenset({22, 23, 0, 1, 2, 3})


def hour_key(epoch: float) -> str:
    """The local clock hour an epoch falls in, as ``YYYY-MM-DDTHH``."""
    return time.strftime(_HOUR_FORMAT, time.localtime(epoch))


def _session_id(epoch: float) -> str:
    return time.strftime(_ID_FORMAT, time.localtime(epoch))


def _fresh_timeline(started_ts: float, sid: str = "") -> Dict[str, Any]:
    return {
        "id": sid,
        "started_ts": float(started_ts),
        "ended_ts": None,
        "bucket_s": BUCKET_S,
        "recovered": False,
        # Which version of the activity gate (stats_gate) recorded it: 0 =
        # none (the first test builds). regate_finished() re-runs the
        # current gate over anything older, once.
        "gated": GATE_VERSION,
        "buckets": {},
    }


def _new_bucket() -> Dict[str, Any]:
    # a: active seconds, t: thrusts,
    # y: toy name -> [on seconds, level-seconds (level x dt, so / bucket_s
    #    is the bucket's mean level)],
    # z: zone key -> contact seconds.
    return {"a": 0.0, "t": 0, "y": {}, "z": {}}


# ----------------------------------------------------------------------
# On-disk shape
# ----------------------------------------------------------------------

def _bucket_rows(buckets: Mapping[int, Dict[str, Any]]) -> List[list]:
    """Buckets as compact rows ``[i, a, t, {toy: [on, lvl]}, {zone: s}]``."""
    rows = []
    for i in sorted(buckets):
        b = buckets[i]
        rows.append([
            i, round(b["a"], 2), b["t"],
            {n: [round(v[0], 2), round(v[1], 3)] for n, v in b["y"].items()},
            {z: round(s, 2) for z, s in b["z"].items()},
        ])
    return rows


def _parse_rows(raw: Any) -> Dict[int, Dict[str, Any]]:
    out: Dict[int, Dict[str, Any]] = {}
    if not isinstance(raw, list):
        return out
    for row in raw:
        if not isinstance(row, list) or len(row) < 3:
            continue
        i = _count(row[0], -1)
        if i < 0:
            continue
        b = _new_bucket()
        b["a"] = _num(row[1])
        b["t"] = _count(row[2])
        if len(row) > 3 and isinstance(row[3], dict):
            for name, v in row[3].items():
                if isinstance(v, list) and len(v) >= 2:
                    on = _num(v[0])
                    b["y"][str(name)] = [on, min(_num(v[1]), on)]
        if len(row) > 4 and isinstance(row[4], dict):
            for zone, s in row[4].items():
                b["z"][str(zone)] = _num(s)
        out[i] = b
    return out


def _timeline_payload(tl: Mapping[str, Any], pid: Optional[int] = None) -> Dict[str, Any]:
    payload = {
        "schema": _SCHEMA_VERSION,
        "id": tl["id"],
        "started_ts": tl["started_ts"],
        "ended_ts": tl["ended_ts"],
        "bucket_s": tl["bucket_s"],
        "recovered": bool(tl.get("recovered")),
        "gated": int(tl.get("gated") or 0),
        "buckets": _bucket_rows(tl["buckets"]),
    }
    if pid is not None:
        payload["pid"] = int(pid)
    return payload


def _read_json(path: Path) -> Tuple[bool, Any]:
    """(ok, data). Missing file: (True, None). Unreadable or unparseable:
    the file is moved aside to `.bak` and (False, None) comes back."""
    if not path.exists():
        return True, None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return True, json.load(f)
    except (ValueError, OSError) as e:
        print(f"StatsHistory: cannot read {path.name}: {e}")
        _set_aside(path)
        return False, None


def _set_aside(path: Path) -> None:
    try:
        os.replace(path, str(path) + ".bak")
    except OSError:
        pass


def _load_timeline(path: Path) -> Optional[Dict[str, Any]]:
    ok, raw = _read_json(path)
    if not ok or not isinstance(raw, dict):
        return None
    try:
        name = path.name
        sid = name[:-len(_LIVE_SUFFIX)] if name.endswith(_LIVE_SUFFIX) else path.stem
        ended = raw.get("ended_ts")
        tl = _fresh_timeline(_num(raw.get("started_ts")), sid)
        tl["ended_ts"] = None if ended is None else _num(ended)
        tl["bucket_s"] = _count(raw.get("bucket_s"), BUCKET_S) or BUCKET_S
        tl["recovered"] = bool(raw.get("recovered"))
        tl["gated"] = _count(raw.get("gated"))      # old files: true/false
        tl["buckets"] = _parse_rows(raw.get("buckets"))
        tl["pid"] = _count(raw.get("pid"))
        return tl
    except Exception as e:
        # Field coercion should catch everything; this is the "never
        # crash boot" backstop.
        print(f"StatsHistory: bad timeline {path.name}: {e}")
        return None


def _parse_hours(raw: Any) -> Dict[str, List[float]]:
    out: Dict[str, List[float]] = {}
    if not isinstance(raw, dict):
        return out
    for key, v in raw.items():
        if (isinstance(key, str) and _HOUR_RE.fullmatch(key)
                and isinstance(v, list) and len(v) >= 2):
            out[key] = [_num(v[0]), _count(v[1])]
    return out


def _parse_connected(raw: Any) -> List[Dict[str, Any]]:
    """[{"started_ts", "toys": {name: [[t0, t1], ...]}}] from the estimate."""
    out: List[Dict[str, Any]] = []
    if not isinstance(raw, list):
        return out
    for entry in raw:
        if not isinstance(entry, dict) or not isinstance(entry.get("toys"), dict):
            continue
        toys = {}
        for name, spans in entry["toys"].items():
            if isinstance(spans, list):
                clean = [[_num(s[0]), _num(s[1])] for s in spans
                         if isinstance(s, list) and len(s) >= 2
                         and _num(s[1]) > _num(s[0])]
                if clean:
                    toys[str(name)] = clean
        if toys:
            out.append({"started_ts": _num(entry.get("started_ts")), "toys": toys})
    return out


def _sanitize_entry(raw: Any) -> Optional[Dict[str, Any]]:
    if not isinstance(raw, dict):
        return None
    sid = str(raw.get("id", ""))
    if not _ID_RE.fullmatch(sid):
        return None
    spark = raw.get("spark")
    ended = raw.get("ended_ts")
    return {
        "id": sid,
        "started_ts": _num(raw.get("started_ts")),
        "ended_ts": None if ended is None else _num(ended),
        "duration_s": _num(raw.get("duration_s")),
        "active_s": _num(raw.get("active_s")),
        "thrusts": _count(raw.get("thrusts")),
        "peak_pace": _count(raw.get("peak_pace")),
        "recovered": bool(raw.get("recovered")),
        "gated": _count(raw.get("gated")),
        "spark": [min(1.0, _num(v)) for v in spark[:SPARK_POINTS * 2]]
        if isinstance(spark, list) else [],
        "toys": {str(k): _num(v) for k, v in (raw.get("toys") or {}).items()}
        if isinstance(raw.get("toys"), dict) else {},
        "zones": {str(k): _num(v) for k, v in (raw.get("zones") or {}).items()}
        if isinstance(raw.get("zones"), dict) else {},
    }


# ----------------------------------------------------------------------
# The store
# ----------------------------------------------------------------------

class StatsHistory:
    """Session timelines + hourly totals with atomic JSON persistence.
    See the module docstring for the files and their shapes."""

    def __init__(self, sessions_dir, hours_file,
                 pid: Optional[int] = None) -> None:
        self.sessions_dir = Path(sessions_dir)
        self.hours_file = Path(hours_file)
        self._pid = os.getpid() if pid is None else int(pid)
        # local hour key -> [active seconds, thrusts]
        self.hours: Dict[str, List[float]] = {}
        # The one-time estimate of the hours before this history existed,
        # kept apart from what was measured. None = not made yet.
        self.estimated: Optional[Dict[str, Any]] = None
        # finished sessions, newest first
        self.index: List[Dict[str, Any]] = []
        self.live: Dict[str, Any] = _fresh_timeline(0.0)
        self._live_dirty = False
        self._hours_dirty = False
        self._load_hours()
        self._load_index()

    # ------------------------------------------------------------------
    # Paths
    # ------------------------------------------------------------------

    def _final_path(self, sid: str) -> Path:
        return self.sessions_dir / f"{sid}.json"

    def _live_path(self, sid: str) -> Path:
        return self.sessions_dir / f"{sid}{_LIVE_SUFFIX}"

    # ------------------------------------------------------------------
    # Load
    # ------------------------------------------------------------------

    def _load_hours(self) -> None:
        ok, raw = _read_json(self.hours_file)
        if not isinstance(raw, dict):
            return
        self.hours = _parse_hours(raw.get("hours"))
        est = raw.get("estimated")
        if isinstance(est, dict):
            self.estimated = {
                "hours": _parse_hours(est.get("hours")),
                "sessions": [_num(t) for t in est.get("sessions") or []
                             if isinstance(t, (int, float))],
                "extra_starts": [_num(t) for t in est.get("extra_starts") or []
                                 if isinstance(t, (int, float))],
                "until_ts": _num(est.get("until_ts")),
                "connected": _parse_connected(est.get("connected")),
            }

    def _load_index(self) -> None:
        if not self.sessions_dir.is_dir():
            return
        ok, raw = _read_json(self.sessions_dir / _INDEX_NAME)
        entries = raw.get("sessions") if isinstance(raw, dict) else None
        if ok and isinstance(entries, list):
            for e in entries:
                clean = _sanitize_entry(e)
                if clean is not None:
                    self.index.append(clean)
            self.index.sort(key=lambda e: e["started_ts"], reverse=True)
            return
        # No usable index: rebuild it from the timelines themselves.
        self._rebuild_index()

    def _rebuild_index(self) -> None:
        entries = []
        for path in self.sessions_dir.glob("*.json"):
            if path.name == _INDEX_NAME or path.name.endswith(_LIVE_SUFFIX):
                continue
            if not _ID_RE.fullmatch(path.stem):
                continue
            tl = _load_timeline(path)
            if tl is not None and tl["buckets"]:
                entries.append(summarize(tl))
        entries.sort(key=lambda e: e["started_ts"], reverse=True)
        self.index = entries
        if entries:
            self._prune()
            self._write_index()

    # ------------------------------------------------------------------
    # Live session
    # ------------------------------------------------------------------

    def start_session(self, epoch: float) -> None:
        """Begin recording a fresh session anchored at `epoch`. Nothing is
        written until it sees activity."""
        started = _num(epoch)
        base = _session_id(started)
        sid, n = base, 2
        while (self._final_path(sid).exists()
               or self._live_path(sid).exists()):
            sid = f"{base}-{n}"
            n += 1
        self.live = _fresh_timeline(started, sid)
        self._live_dirty = False

    def sample(self, epoch: float, dt_s: float,
               toy_levels: Mapping[str, float],
               contact_zones: Iterable[str],
               thrusts: int) -> None:
        """Integrate one sampling interval ending at `epoch`.

        `toy_levels` — name -> output level (0..1) for each toy currently
        driven above zero. `contact_zones` — zone keys currently in
        contact. Same activity rule as StatsTracker.sample: a toy on or a
        zone in contact makes the interval active; thrusts count either
        way."""
        dt = _num(dt_s)
        n_thrusts = _count(thrusts)
        levels = {}
        for name, lvl in (toy_levels or {}).items():
            v = min(1.0, _num(lvl))
            if v > 0.0:
                levels[str(name)] = v
        zones = [str(z) for z in (contact_zones or ())]
        active = dt > 0.0 and (bool(levels) or bool(zones))
        if not active and not n_thrusts:
            return
        tl = self.live
        offset = max(0.0, _num(epoch) - tl["started_ts"])
        i = int(offset // tl["bucket_s"])
        b = tl["buckets"].get(i)
        if b is None:
            b = tl["buckets"][i] = _new_bucket()
        if active:
            b["a"] += dt
            for name, lvl in levels.items():
                entry = b["y"].get(name)
                if entry is None:
                    entry = b["y"][name] = [0.0, 0.0]
                entry[0] += dt
                entry[1] += lvl * dt
            for zone in zones:
                b["z"][zone] = b["z"].get(zone, 0.0) + dt
        b["t"] += n_thrusts
        key = hour_key(_num(epoch))
        h = self.hours.get(key)
        if h is None:
            h = self.hours[key] = [0.0, 0]
        if active:
            h[0] += dt
        h[1] += n_thrusts
        self._live_dirty = True
        self._hours_dirty = True

    def flush(self, force: bool = False) -> None:
        """Write the live timeline and the hourly totals if they changed
        (`force`: write whatever exists). Atomic; an OSError leaves the
        data dirty for the next try."""
        tl = self.live
        if tl["buckets"] and (self._live_dirty or force):
            try:
                self.sessions_dir.mkdir(parents=True, exist_ok=True)
                atomic_write_json(self._live_path(tl["id"]),
                                  _timeline_payload(tl, self._pid))
                self._live_dirty = False
            except OSError as e:
                print(f"StatsHistory: live save error: {e}")
        if self._hours_dirty or (force and self.hours):
            self._write_hours()

    def _write_hours(self) -> None:
        payload: Dict[str, Any] = {
            "schema": _SCHEMA_VERSION,
            "hours": {k: [round(v[0], 1), v[1]]
                      for k, v in sorted(self.hours.items())},
        }
        if self.estimated is not None:
            est = self.estimated
            payload["estimated"] = {
                "hours": {k: [round(v[0], 1), v[1]]
                          for k, v in sorted(est["hours"].items())},
                "sessions": est["sessions"],
                "extra_starts": est["extra_starts"],
                "until_ts": est["until_ts"],
                "connected": est.get("connected", []),
            }
        try:
            atomic_write_json(self.hours_file, payload)
            self._hours_dirty = False
        except OSError as e:
            print(f"StatsHistory: hours save error: {e}")

    # ------------------------------------------------------------------
    # The one-time estimate of the time before this history
    # ------------------------------------------------------------------

    def needs_estimate(self) -> bool:
        return self.estimated is None

    def set_estimate(self, est: Mapping[str, Any]) -> None:
        """Store stats_backfill.estimate()'s result (once) and save it."""
        self.estimated = {
            "hours": _parse_hours(est.get("hours")),
            "sessions": [float(t) for t in est.get("sessions") or []],
            "extra_starts": [float(t) for t in est.get("extra_starts") or []],
            "until_ts": _num(est.get("until_ts")),
            "connected": _parse_connected(est.get("connected")),
        }
        self._write_hours()

    def estimate_info(self) -> Dict[str, Any]:
        """{"until_ts", "sessions", "extra_starts", "connected"} of the
        estimate (zeros and empty lists when there is none). The
        "connected" entries are shared — read-only."""
        est = self.estimated or {}
        return {"until_ts": est.get("until_ts", 0.0),
                "sessions": list(est.get("sessions", [])),
                "extra_starts": list(est.get("extra_starts", [])),
                "connected": est.get("connected", [])}

    def finalize_session(self, epoch: float) -> Optional[Dict[str, Any]]:
        """Close the live session. One that saw activity is written to its
        final file and filed in the index (its summary is returned); an
        idle run leaves no trace. A fresh session starts at `epoch`."""
        tl = self.live
        summary = None
        if tl["buckets"]:
            tl["ended_ts"] = max(tl["started_ts"], _num(epoch))
            summary = self._close(tl, self._live_path(tl["id"]))
            if summary is None:
                # Couldn't write the final file: bring its .live file up
                # to date instead, so the next launch recovers all of it.
                tl["ended_ts"] = None
                self.flush(force=True)
        self.start_session(epoch)
        self.flush(force=True)      # the hourly totals
        return summary

    def _close(self, tl: Dict[str, Any], live_path: Path) -> Optional[Dict[str, Any]]:
        """Write a finished timeline to its final file, drop its `.live`
        file and file it in the index. On a write error the `.live` file
        stays, so the next launch recovers it."""
        try:
            self.sessions_dir.mkdir(parents=True, exist_ok=True)
            atomic_write_json(self._final_path(tl["id"]), _timeline_payload(tl))
        except OSError as e:
            print(f"StatsHistory: session save error: {e}")
            return None
        try:
            os.remove(live_path)
        except OSError:
            pass
        summary = summarize(tl)
        self.index = [e for e in self.index if e["id"] != summary["id"]]
        self.index.append(summary)
        self.index.sort(key=lambda e: e["started_ts"], reverse=True)
        self._prune()
        self._write_index()
        return summary

    def recover_unfinished(
            self, is_running: Callable[[int], bool] = lambda pid: False,
    ) -> List[Dict[str, Any]]:
        """Close every `.live` timeline left by a run that never shut down
        cleanly (killed, crashed, PC switched off). Its end is its last
        recorded bucket. A file whose writer process is still running
        (another copy of the app) is left alone. Returns the summaries of
        the sessions closed here, oldest first, for StatsTracker."""
        out: List[Dict[str, Any]] = []
        if not self.sessions_dir.is_dir():
            return out
        for path in sorted(self.sessions_dir.glob("*" + _LIVE_SUFFIX)):
            tl = _load_timeline(path)
            if tl is None:
                continue
            pid = tl.get("pid") or 0
            if pid and pid != self._pid:
                try:
                    if is_running(pid):
                        continue
                except Exception:
                    pass
            if not tl["buckets"]:
                try:
                    os.remove(path)
                except OSError:
                    pass
                continue
            last = max(tl["buckets"])
            tl["ended_ts"] = tl["started_ts"] + (last + 1) * tl["bucket_s"]
            tl["recovered"] = True
            summary = self._close(tl, path)
            if summary is not None:
                out.append(summary)
        out.sort(key=lambda e: e["started_ts"])
        return out

    def regate_finished(self) -> List[Dict[str, Any]]:
        """Run the activity gate over every finished timeline recorded
        without it (the first test builds), once: drop the buckets that
        don't count, take them off the measured hours, and delete a
        timeline left with nothing. Returns, per timeline it changed,
        {"started_ts", "removed" (nothing left), "dropped": {"active_s",
        "thrusts", "toys": {name: on_s}, "zones": {key: s}}} so the
        tracker can take the same amounts off its totals."""
        results: List[Dict[str, Any]] = []
        changed = False
        for entry in list(self.index):
            if entry.get("gated", 0) >= GATE_VERSION:
                continue
            tl = self.timeline(entry["id"])
            changed = True
            if tl is None:
                entry["gated"] = GATE_VERSION
                continue
            dropped = regate(tl)
            if not tl["buckets"]:
                try:
                    os.remove(self._final_path(entry["id"]))
                except OSError:
                    pass
                self.index = [e for e in self.index if e["id"] != entry["id"]]
            else:
                tl["gated"] = GATE_VERSION
                try:
                    atomic_write_json(self._final_path(tl["id"]), _timeline_payload(tl))
                except OSError as e:
                    print(f"StatsHistory: session save error: {e}")
                    continue
                fresh = summarize(tl)
                self.index = [fresh if e["id"] == fresh["id"] else e
                              for e in self.index]
            for key, (a, t) in dropped.pop("hours").items():
                h = self.hours.get(key)
                if h is not None:
                    h[0] = max(0.0, h[0] - a)
                    h[1] = max(0, h[1] - t)
                    if h[0] <= 0 and h[1] <= 0:
                        del self.hours[key]
            if dropped["active_s"] or dropped["thrusts"] or not tl["buckets"]:
                results.append({"started_ts": tl["started_ts"],
                                "removed": not tl["buckets"],
                                "dropped": dropped})
        if changed:
            self._write_index()
            self._write_hours()
        return results

    def _prune(self) -> None:
        while len(self.index) > SESSIONS_CAP:
            old = self.index.pop()
            try:
                os.remove(self._final_path(old["id"]))
            except OSError:
                pass

    def _write_index(self) -> None:
        try:
            self.sessions_dir.mkdir(parents=True, exist_ok=True)
            atomic_write_json(self.sessions_dir / _INDEX_NAME, {
                "schema": _SCHEMA_VERSION, "sessions": self.index,
            })
        except OSError as e:
            print(f"StatsHistory: index save error: {e}")

    def reset(self, epoch: float) -> None:
        """Forget everything: every timeline, the index and the hourly
        totals. A fresh session starts at `epoch`."""
        if self.sessions_dir.is_dir():
            for path in self.sessions_dir.iterdir():
                name = path.name
                stem = name.split(".", 1)[0]
                if name == _INDEX_NAME or _ID_RE.fullmatch(stem):
                    try:
                        os.remove(path)
                    except OSError:
                        pass
        self.index = []
        self.hours = {}
        # An empty estimate, not none: a reset is a clean slate, and the
        # old logs must not be estimated back into it.
        self.estimated = {"hours": {}, "sessions": [], "extra_starts": [],
                          "until_ts": 0.0, "connected": []}
        self._write_hours()
        self.start_session(epoch)

    # ------------------------------------------------------------------
    # Read model
    # ------------------------------------------------------------------

    def session_list(self) -> List[Dict[str, Any]]:
        """Summaries of every finished session, newest first. Each dict is
        a fresh copy (callers may add keys); the nested values are shared
        and must be treated as read-only. Called every second while the
        Statistics page is open, so no deep copy."""
        return [dict(e) for e in self.index]

    def live_summary(self, now_epoch: float) -> Optional[Dict[str, Any]]:
        """Summary of the running session, or None while it is idle."""
        if not self.live["buckets"]:
            return None
        return summarize(self.live, now_epoch)

    def timeline(self, sid: str) -> Optional[Dict[str, Any]]:
        """A session's full timeline: the running one from memory, a
        finished one from its file. None for an unknown id."""
        if sid and sid == self.live["id"]:
            return self.live if self.live["buckets"] else None
        if not _ID_RE.fullmatch(str(sid)):
            return None
        path = self._final_path(sid)
        if not path.exists():
            return None
        return _load_timeline(path)

    def is_live(self, sid: str) -> bool:
        return bool(sid) and sid == self.live["id"]

    def hours_snapshot(self) -> Dict[str, List[float]]:
        """Measured hours plus the estimated ones, summed per hour."""
        out = {k: list(v) for k, v in self.hours.items()}
        if self.estimated:
            for k, (a, t) in self.estimated["hours"].items():
                h = out.setdefault(k, [0.0, 0])
                h[0] += a
                h[1] += t
        return out


# ----------------------------------------------------------------------
# Pure helpers — what the charts draw
# ----------------------------------------------------------------------

def dense(tl: Mapping[str, Any]) -> Dict[str, Any]:
    """Contiguous per-bucket arrays from the first active bucket to the
    last: `active` and `thrusts`, `toys` (name -> mean level 0..1) and
    `zones` (key -> share of the bucket in contact, 0..1). `start_i` is
    the first bucket's index, so bucket k began at
    ``started_ts + (start_i + k) * bucket_s``."""
    bs = tl.get("bucket_s") or BUCKET_S
    buckets = tl.get("buckets") or {}
    out: Dict[str, Any] = {"bucket_s": bs, "start_i": 0, "n": 0,
                           "active": [], "thrusts": [], "toys": {},
                           "zones": {}}
    if not buckets:
        return out
    i0, i1 = min(buckets), max(buckets)
    n = i1 - i0 + 1
    active = [0.0] * n
    thrusts = [0] * n
    toys: Dict[str, List[float]] = {}
    zones: Dict[str, List[float]] = {}
    for i, b in buckets.items():
        k = i - i0
        active[k] = b["a"]
        thrusts[k] = b["t"]
        for name, (on, lvl) in b["y"].items():
            if name not in toys:
                toys[name] = [0.0] * n
            toys[name][k] = min(1.0, lvl / bs)
        for zone, s in b["z"].items():
            if zone not in zones:
                zones[zone] = [0.0] * n
            zones[zone][k] = min(1.0, s / bs)
    out.update(start_i=i0, n=n, active=active, thrusts=thrusts,
               toys=toys, zones=zones)
    return out


def _sparkline(d: Mapping[str, Any], points: int = SPARK_POINTS) -> List[float]:
    """Share of each slice of the active window that was active, 0..1."""
    n = d["n"]
    if n <= 0:
        return []
    bs = d["bucket_s"]
    p = min(points, n)
    out = []
    for k in range(p):
        a, b = k * n // p, max(k * n // p + 1, (k + 1) * n // p)
        span = (b - a) * bs
        out.append(round(min(1.0, sum(d["active"][a:b]) / span), 2))
    return out


def regate(tl: Dict[str, Any]) -> Dict[str, Any]:
    """Apply the activity gate to a timeline's buckets in place (bucket
    resolution: the streak gap widens by a bucket). Returns what it
    dropped: active_s, thrusts, toys {name: on_s}, zones {key: s} and
    hours {hour key: [active_s, thrusts]}."""
    bs = tl.get("bucket_s") or BUCKET_S
    gate = ActivityGate(MIN_THRUSTS, STREAK_GAP_S + bs, LEAD_S, SCENE_END_S,
                        MIN_CONTACT_S, CONTACT_WINDOW_S, CONTACT_GRACE_S + bs)
    keep = set()
    for i in sorted(tl["buckets"]):
        b = tl["buckets"][i]
        toy_on = any(v[0] > 0 for v in b["y"].values())
        # Without a toy, a bucket's active seconds are its contact time.
        contact = max([b["a"]] + list(b["z"].values()))
        keep.update(gate.push(tl["started_ts"] + i * bs, i, toy_on, contact, b["t"]))
    dropped: Dict[str, Any] = {"active_s": 0.0, "thrusts": 0, "toys": {},
                               "zones": {}, "hours": {}}
    for i in [i for i in tl["buckets"] if i not in keep]:
        b = tl["buckets"].pop(i)
        dropped["active_s"] += b["a"]
        dropped["thrusts"] += b["t"]
        for name, (on, _lvl) in b["y"].items():
            dropped["toys"][name] = dropped["toys"].get(name, 0.0) + on
        for zone, s in b["z"].items():
            dropped["zones"][zone] = dropped["zones"].get(zone, 0.0) + s
        h = dropped["hours"].setdefault(
            hour_key(tl["started_ts"] + i * bs + bs / 2), [0.0, 0])
        h[0] += b["a"]
        h[1] += b["t"]
    return dropped


def _window_max(values: List[float], width: int) -> Tuple[float, int]:
    """(largest sum over `width` consecutive values, where it starts)."""
    n = len(values)
    if n == 0:
        return 0.0, 0
    width = max(1, min(width, n))
    s = sum(values[:width])
    best, at = s, 0
    for k in range(width, n):
        s += values[k] - values[k - width]
        if s > best:
            best, at = s, k - width + 1
    return best, at


def summarize(tl: Mapping[str, Any], now_epoch: Optional[float] = None) -> Dict[str, Any]:
    """The index entry for a timeline: totals, per-toy on-time, per-zone
    contact, peak pace and the list sparkline. A running session (no
    `ended_ts`) measures its duration to `now_epoch`."""
    buckets = tl.get("buckets") or {}
    bs = tl.get("bucket_s") or BUCKET_S
    started = _num(tl.get("started_ts"))
    toys: Dict[str, float] = {}
    zones: Dict[str, float] = {}
    active = 0.0
    thrusts = 0
    for b in buckets.values():
        active += b["a"]
        thrusts += b["t"]
        for name, (on, _lvl) in b["y"].items():
            toys[name] = toys.get(name, 0.0) + on
        for zone, s in b["z"].items():
            zones[zone] = zones.get(zone, 0.0) + s
    ended = tl.get("ended_ts")
    if ended is not None:
        end = ended
    elif now_epoch is not None:
        end = now_epoch
    else:
        end = started + ((max(buckets) + 1) * bs if buckets else 0)
    d = dense(tl)
    peak, _ = _window_max(d["thrusts"], max(1, int(round(60 / bs))))
    return {
        "id": tl.get("id", ""),
        "started_ts": started,
        "ended_ts": ended,
        "duration_s": round(max(0.0, end - started), 1),
        "active_s": round(active, 1),
        "thrusts": int(thrusts),
        "peak_pace": int(peak),
        "recovered": bool(tl.get("recovered")),
        "gated": int(tl.get("gated") or 0),
        "spark": _sparkline(d),
        "toys": {k: round(v, 1) for k, v in toys.items()},
        "zones": {k: round(v, 1) for k, v in zones.items()},
    }


def analyse(tl: Mapping[str, Any]) -> Dict[str, Any]:
    """Everything the session page says about one session. Times are
    seconds from the session's start (`*_at_s`) or lengths (`*_s`)."""
    d = dense(tl)
    bs = d["bucket_s"]
    n = d["n"]
    base = d["start_i"] * bs
    out: Dict[str, Any] = {
        "window_start_s": base, "window_s": n * bs,
        "peak_pace": 0, "peak_pace_at_s": base,
        "hot_kind": "thrusts", "hot_value": 0.0, "hot_at_s": base,
        "hot_len_s": 0,
        "streak_s": 0, "streak_at_s": base,
        "break_s": 0, "break_at_s": base,
        "top_toy": None, "top_toy_share": 0.0, "top_toy_level": 0.0,
        "top_zone": None, "top_zone_s": 0.0,
    }
    if n == 0:
        return out
    per_min = max(1, int(round(60 / bs)))
    five = min(n, max(1, int(round(300 / bs))))
    peak, peak_at = _window_max(d["thrusts"], per_min)
    out["peak_pace"] = int(peak)
    out["peak_pace_at_s"] = base + peak_at * bs
    hot, hot_at = _window_max(d["thrusts"], five)
    if hot <= 0:
        # No thrusts at all (a vibe-only session): the most intense five
        # minutes by toy level instead, reported as the mean level.
        intensity = [max((arr[k] for arr in d["toys"].values()), default=0.0)
                     for k in range(n)]
        hot, hot_at = _window_max(intensity, five)
        out["hot_kind"] = "intensity"
        hot = hot / five
    out["hot_value"] = hot
    out["hot_at_s"] = base + hot_at * bs
    out["hot_len_s"] = five * bs

    # Streaks and breaks over the active buckets.
    active_idx = [k for k, a in enumerate(d["active"]) if a > 0.0]
    if active_idx:
        run_start = last = active_idx[0]
        best_run, best_run_at = 1, run_start
        best_gap, best_gap_at = 0, run_start
        for k in active_idx[1:]:
            gap = k - last - 1
            if gap > _STREAK_GAP_BUCKETS:
                run_start = k
            if gap > best_gap:
                best_gap, best_gap_at = gap, last + 1
            last = k
            if last - run_start + 1 > best_run:
                best_run, best_run_at = last - run_start + 1, run_start
        out["streak_s"] = best_run * bs
        out["streak_at_s"] = base + best_run_at * bs
        if best_gap * bs >= _MIN_BREAK_S:
            out["break_s"] = best_gap * bs
            out["break_at_s"] = base + best_gap_at * bs

    toys: Dict[str, List[float]] = {}
    zones: Dict[str, float] = {}
    for b in (tl.get("buckets") or {}).values():
        for name, (on, lvl) in b["y"].items():
            acc = toys.setdefault(name, [0.0, 0.0])
            acc[0] += on
            acc[1] += lvl
        for zone, s in b["z"].items():
            zones[zone] = zones.get(zone, 0.0) + s
    total_on = sum(v[0] for v in toys.values())
    if total_on > 0:
        top = max(toys, key=lambda k: toys[k][0])
        out["top_toy"] = top
        out["top_toy_share"] = toys[top][0] / total_on
        out["top_toy_level"] = toys[top][1] / toys[top][0] if toys[top][0] else 0.0
    if zones:
        top_zone = max(zones, key=zones.get)
        out["top_zone"] = top_zone
        out["top_zone_s"] = zones[top_zone]
    return out


def weekday_hour(hours: Mapping[str, List[float]],
                 since: Optional[str] = None) -> Dict[str, Any]:
    """7 x 24 grids (Monday first) of active seconds and thrusts by local
    weekday and hour, over the hour keys at or after `since` (an
    ``hour_key``; None = all of them)."""
    active = [[0.0] * 24 for _ in range(7)]
    thrusts = [[0] * 24 for _ in range(7)]
    for key, (a, t) in hours.items():
        if since is not None and key < since:
            continue
        try:
            # Sliced, not strptime: this runs over the whole history every
            # few seconds while the page is open.
            wd = date(int(key[0:4]), int(key[5:7]), int(key[8:10])).weekday()
            hour = int(key[11:13])
        except ValueError:
            continue
        if 0 <= hour < 24:
            active[wd][hour] += a
            thrusts[wd][hour] += int(t)
    return {"active": active, "thrusts": thrusts}


def month_days(hours: Mapping[str, List[float]],
               sessions: Iterable[Mapping[str, Any]],
               year: int, month: int) -> Dict[int, Dict[str, Any]]:
    """day of month -> {active_s, thrusts, sessions} for one month.

    Activity comes from the hourly totals, so a session over midnight
    lands on both days. `sessions` count on their start day; one with
    neither a timeline nor estimated hours (`in_hours`) — recorded by the
    full edition, say — has no hours either, so its totals land on its
    start day too."""
    days: Dict[int, Dict[str, Any]] = {}

    def day(d: int) -> Dict[str, Any]:
        e = days.get(d)
        if e is None:
            e = days[d] = {"active_s": 0.0, "thrusts": 0, "sessions": 0}
        return e

    prefix = f"{year:04d}-{month:02d}-"
    for key, (a, t) in hours.items():
        if key.startswith(prefix):
            try:
                e = day(int(key[8:10]))
            except ValueError:
                continue
            e["active_s"] += a
            e["thrusts"] += int(t)
    for s in sessions:
        lt = time.localtime(_num(s.get("started_ts")))
        if lt.tm_year != year or lt.tm_mon != month:
            continue
        e = day(lt.tm_mday)
        e["sessions"] += 1
        if not s.get("timeline") and not s.get("in_hours"):
            e["active_s"] += _num(s.get("active_s"))
            e["thrusts"] += _count(s.get("thrusts"))
    return days


def fun_facts(lifetime: Mapping[str, Any],
              sessions: Iterable[Mapping[str, Any]],
              hours: Mapping[str, List[float]]) -> Dict[str, Any]:
    """The lifetime card's fun facts. Each key is present only when there
    is enough data to say something; the view shows what it gets."""
    out: Dict[str, Any] = {}
    n = _count(lifetime.get("sessions"))
    active = _num(lifetime.get("active_s"))
    thrusts = _count(lifetime.get("thrusts"))
    if n:
        out["avg_session_s"] = active / n
        out["avg_session_thrusts"] = thrusts / n
    if active >= 60.0 and thrusts:
        out["pace"] = thrusts / (active / 60.0)

    toys = {k: _num((v or {}).get("on_s")) for k, v in
            (lifetime.get("toys") or {}).items() if isinstance(v, dict)}
    total = sum(toys.values())
    if total > 0:
        fav = max(toys, key=toys.get)
        out["fav_toy"] = (fav, toys[fav] / total)
    zones = {k: _num((v or {}).get("contact_s")) for k, v in
             (lifetime.get("zones") or {}).items() if isinstance(v, dict)}
    total = sum(zones.values())
    if total > 0:
        fav = max(zones, key=zones.get)
        out["fav_zone"] = (fav, zones[fav] / total)

    grid = weekday_hour(hours)["active"]
    total = sum(sum(row) for row in grid)
    if total >= 600.0:
        night = sum(grid[d][h] for d in range(7) for h in NIGHT_HOURS)
        out["night_share"] = night / total
        per_day = [sum(row) for row in grid]
        out["busiest_weekday"] = per_day.index(max(per_day))

    sessions = list(sessions)
    if sessions:
        best = max(sessions, key=lambda s: _count(s.get("thrusts")))
        if _count(best.get("thrusts")):
            out["best_session"] = (_count(best.get("thrusts")),
                                   _num(best.get("started_ts")))
        longest = max(sessions, key=lambda s: _num(s.get("active_s")))
        if _num(longest.get("active_s")):
            out["longest_session"] = (_num(longest.get("active_s")),
                                      _num(longest.get("started_ts")))
        paced = [s for s in sessions if _count(s.get("peak_pace"))]
        if paced:
            rec = max(paced, key=lambda s: _count(s.get("peak_pace")))
            out["record_pace"] = (_count(rec.get("peak_pace")),
                                  _num(rec.get("started_ts")))
    return out
