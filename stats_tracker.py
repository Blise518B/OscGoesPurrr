"""Usage-statistics accumulator — lifetime totals + per-session summaries.

Sealed, pure logic: no Qt, no threads, no wall-clock reads of its own.
The controller feeds it pre-computed samples (`sample()`) at ~1 Hz and
hands in wall-clock epochs for session boundaries (`start_session` /
`finalize_session`), so every time-dependent behavior is deterministic
under test — the tracker itself never calls `time.time()`.

What it counts:

* **active_s** — seconds during which anything was happening: at least
  one toy motor driven above zero OR at least one zone in contact.
* **toys** — per-toy on-time (`on_s`), keyed by device name.
* **zones** — per-zone contact time (`contact_s`), keyed by
  ``"<zone_type>/<zone_name>"`` so a socket and a plug sharing a name
  never merge; each entry remembers its ``type`` ("Orf"/"Pen"/"Touch").
* **thrusts** — completed in-out strokes (from the motor router's
  swing detector, consumed by the controller and passed in here).

Persistence is a single JSON file (`stats.json`, schema 1) holding the
lifetime totals plus the last `_RECENT_SESSIONS_CAP` finalized session
summaries. The live session accumulator is deliberately NOT persisted —
a crash loses at most the in-flight session, never the lifetime totals
(which flush periodically via the controller). Loading is defensive the
same way the settings managers are: a missing file starts fresh, an
unreadable/misshapen file is moved aside to a ``.bak`` and replaced
with defaults, and no load path can ever crash app boot.
"""

import json
import math
import os
import time
from typing import Any, Callable, Dict, Iterable, List, Tuple

from utilities import atomic_write_json


# On-disk schema version. Bump when the file shape changes so a future
# loader can migrate instead of guessing.
_SCHEMA_VERSION = 1

# How many finalized session summaries the file keeps (newest first).
_RECENT_SESSIONS_CAP = 20


def _fresh_lifetime() -> Dict[str, Any]:
    return {
        "sessions": 0,
        "active_s": 0.0,
        "thrusts": 0,
        "toys": {},
        "zones": {},
    }


def _fresh_session(started_ts: float = 0.0) -> Dict[str, Any]:
    # Same shape as lifetime minus the session counter, plus the
    # wall-clock start epoch (passed in by the caller, never read here).
    return {
        "started_ts": float(started_ts),
        "active_s": 0.0,
        "thrusts": 0,
        "toys": {},
        "zones": {},
    }


def _num(value: Any, default: float = 0.0) -> float:
    """Non-negative finite float, or the default. NaN/inf from a
    hand-edited file must never poison the accumulators."""
    try:
        f = float(value)
    except (TypeError, ValueError):
        return default
    if not math.isfinite(f) or f < 0.0:
        return default
    return f


def _count(value: Any, default: int = 0) -> int:
    """Non-negative int, or the default. Route through float + isfinite
    first: json.load parses bare ``Infinity`` and ``int(inf)`` raises
    OverflowError — an exception class a plain (TypeError, ValueError)
    catch misses, which would let a hand-edited file crash app boot."""
    try:
        f = float(value)
    except (TypeError, ValueError):
        return default
    if not math.isfinite(f) or f < 0.0:
        return default
    return int(f)


class StatsTracker:
    """Lifetime + per-session usage accumulators with atomic JSON
    persistence. See the module docstring for the counted quantities.

    `clock` is dependency-injected for parity with MotorRouter's
    convention (tests drive time deterministically); the current
    implementation takes all time inputs from its callers, so the
    clock is held for future time-based logic rather than read today.
    """

    def __init__(self, file_path,
                 clock: Callable[[], float] = time.monotonic) -> None:
        self.file_path = file_path
        self._clock = clock
        self.lifetime: Dict[str, Any] = _fresh_lifetime()
        self.recent_sessions: List[Dict[str, Any]] = []
        # The live session starts un-anchored; the controller calls
        # start_session(epoch) right after construction.
        self.session: Dict[str, Any] = _fresh_session()
        # True while unflushed mutations exist. Lets the periodic flush
        # no-op through fully idle stretches instead of fsync-rewriting
        # an unchanged stats.json once a minute on the GUI thread.
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
                loaded = json.load(f)
        except (ValueError, OSError) as e:
            # Unparseable or unreadable: preserve whatever is there for
            # manual recovery, then run on fresh defaults. (A transient
            # read lock makes the rename fail too — that's fine, the
            # backup is best-effort and stats are low-stakes data.)
            print(f"StatsTracker load error: {e}, starting fresh")
            self._backup_corrupt_file()
            return
        if not isinstance(loaded, dict):
            print("StatsTracker: stats file is not a dict, starting fresh")
            self._backup_corrupt_file()
            return
        try:
            self.lifetime = self._sanitize_lifetime(loaded.get("lifetime"))
            self.recent_sessions = self._sanitize_recent(
                loaded.get("recent_sessions"))
        except Exception as e:
            # The sanitizers coerce field-by-field, but "no load path can
            # ever crash app boot" is the module invariant — any value that
            # still slips through self-heals instead of bricking launch.
            print(f"StatsTracker sanitize error: {e}, starting fresh")
            self.lifetime = _fresh_lifetime()
            self.recent_sessions = []
            self._backup_corrupt_file()

    def _backup_corrupt_file(self) -> None:
        backup = str(self.file_path) + ".bak"
        try:
            os.replace(self.file_path, backup)
            print(f"StatsTracker: unreadable stats backed up to {backup}")
        except OSError as e:
            print(f"StatsTracker: could not back up corrupt stats: {e}")

    def _sanitize_lifetime(self, raw: Any) -> Dict[str, Any]:
        """Field-by-field coercion so a partially hand-edited file
        degrades to defaults per field instead of being discarded."""
        out = _fresh_lifetime()
        if not isinstance(raw, dict):
            return out
        out["sessions"] = _count(raw.get("sessions"))
        out["active_s"] = _num(raw.get("active_s"))
        out["thrusts"] = _count(raw.get("thrusts"))
        out["toys"] = self._sanitize_toys(raw.get("toys"))
        out["zones"] = self._sanitize_zones(raw.get("zones"))
        return out

    @staticmethod
    def _sanitize_toys(raw: Any) -> Dict[str, Dict[str, float]]:
        out: Dict[str, Dict[str, float]] = {}
        if isinstance(raw, dict):
            for name, entry in raw.items():
                if isinstance(entry, dict):
                    out[str(name)] = {"on_s": _num(entry.get("on_s"))}
        return out

    @staticmethod
    def _sanitize_zones(raw: Any) -> Dict[str, Dict[str, Any]]:
        out: Dict[str, Dict[str, Any]] = {}
        if isinstance(raw, dict):
            for key, entry in raw.items():
                if isinstance(entry, dict):
                    out[str(key)] = {
                        "type": str(entry.get("type", "")),
                        "contact_s": _num(entry.get("contact_s")),
                    }
        return out

    def _sanitize_recent(self, raw: Any) -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []
        if not isinstance(raw, list):
            return out
        for entry in raw[:_RECENT_SESSIONS_CAP]:
            if not isinstance(entry, dict):
                continue
            out.append({
                "started_ts": _num(entry.get("started_ts")),
                "duration_s": _num(entry.get("duration_s")),
                "active_s": _num(entry.get("active_s")),
                "thrusts": _count(entry.get("thrusts")),
                "toys": self._sanitize_toys(entry.get("toys")),
                "zones": self._sanitize_zones(entry.get("zones")),
            })
        return out

    def flush(self, force: bool = False) -> None:
        """Atomic write of the persistent state (lifetime totals +
        finalized session summaries). The live session accumulator is
        intentionally left out — see the module docstring. A clean
        tracker is a no-op unless `force` — idle app runs must not
        fsync-rewrite an unchanged file once a minute."""
        if not self._dirty and not force:
            return
        payload = {
            "schema": _SCHEMA_VERSION,
            "lifetime": self.lifetime,
            "recent_sessions": self.recent_sessions,
        }
        try:
            atomic_write_json(self.file_path, payload, indent=2)
            self._dirty = False
        except OSError as e:
            print(f"StatsTracker save error: {e}")

    # ------------------------------------------------------------------
    # Accumulation
    # ------------------------------------------------------------------

    def sample(self, dt_s: float,
               on_toys: Iterable[str],
               contact_zones: Iterable[Tuple[str, str]],
               thrusts: int) -> None:
        """Integrate one sampling interval into both accumulators.

        `dt_s` — seconds since the previous sample (caller-computed).
        `on_toys` — device names with any motor currently driven > 0.
        `contact_zones` — (zone_key, zone_type) pairs currently in
        contact. `thrusts` — completed strokes observed this interval.
        O(len(on_toys) + len(contact_zones)) — safe at 1 Hz forever.
        """
        dt = _num(dt_s)
        n_thrusts = _count(thrusts)
        if dt <= 0.0 and n_thrusts <= 0:
            return
        on_toys = list(on_toys or ())
        contact_zones = list(contact_zones or ())
        active = dt > 0.0 and (bool(on_toys) or bool(contact_zones))
        if not active and not n_thrusts:
            return
        self._dirty = True
        for acc in (self.lifetime, self.session):
            if active:
                acc["active_s"] += dt
            if n_thrusts:
                acc["thrusts"] += n_thrusts
            if dt > 0.0:
                toys = acc["toys"]
                for name in on_toys:
                    entry = toys.get(name)
                    if entry is None:
                        entry = toys[name] = {"on_s": 0.0}
                    entry["on_s"] += dt
                zones = acc["zones"]
                for zone_key, zone_type in contact_zones:
                    entry = zones.get(zone_key)
                    if entry is None:
                        entry = zones[zone_key] = {
                            "type": str(zone_type), "contact_s": 0.0,
                        }
                    entry["contact_s"] += dt

    # ------------------------------------------------------------------
    # Session boundaries
    # ------------------------------------------------------------------

    def start_session(self, epoch: float) -> None:
        """Begin a fresh session anchored at the given wall-clock epoch
        (the caller reads time.time(); the tracker never does)."""
        self.session = _fresh_session(_num(epoch))

    def finalize_session(self, epoch: float) -> None:
        """Close the live session. A session that saw any activity
        (active time or thrusts) bumps the lifetime session counter and
        lands as the newest entry in `recent_sessions` (capped); an
        idle app run leaves no trace. Either way the accumulators reset
        and the file flushes so shutdown always persists."""
        s = self.session
        if s["active_s"] > 0.0 or s["thrusts"] > 0:
            self.lifetime["sessions"] += 1
            started = _num(s.get("started_ts"))
            end = _num(epoch)
            summary = {
                "started_ts": started,
                "duration_s": max(0.0, end - started) if started else 0.0,
                "active_s": s["active_s"],
                "thrusts": s["thrusts"],
                "toys": {k: dict(v) for k, v in s["toys"].items()},
                "zones": {k: dict(v) for k, v in s["zones"].items()},
            }
            self.recent_sessions.insert(0, summary)
            del self.recent_sessions[_RECENT_SESSIONS_CAP:]
        self.session = _fresh_session(_num(epoch))
        # Shutdown persistence is unconditional — one cheap atomic write.
        self.flush(force=True)

    def reset_lifetime(self) -> None:
        """Zero everything — lifetime totals, recent sessions, and the
        live session's accumulators (the user asked for a clean slate;
        a half-populated 'this session' surviving the reset would read
        as a bug). The session's start anchor is kept so the caller can
        immediately start_session() with a fresh epoch or not."""
        self.lifetime = _fresh_lifetime()
        self.recent_sessions = []
        self.session = _fresh_session(_num(self.session.get("started_ts")))
        self.flush(force=True)

    # ------------------------------------------------------------------
    # UI read model
    # ------------------------------------------------------------------

    def snapshot(self) -> Dict[str, Any]:
        """Deep-copied read model for the UI. Values are JSON-safe by
        construction, so a json round-trip is the cheapest correct deep
        copy (same trick as settings/_base.py)."""
        return json.loads(json.dumps({
            "lifetime": self.lifetime,
            "session": self.session,
            "recent_sessions": self.recent_sessions,
        }))
