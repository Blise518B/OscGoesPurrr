"""One-time estimate of the hourly history from what existed before it.

Before `stats_history` recorded activity hour by hour, the app kept only
session totals (`stats.json`: the last 20 sessions' start, length, active
time and thrusts, plus lifetime totals) and its own debug log, which notes
every app start and exit and every time a toy connected or disconnected.
Neither says what happened inside a session — but a toy is connected
when it is being played with, so the connected stretches say *when*.

This module turns those into estimated hourly totals so the Statistics
charts don't start empty:

* each saved session's active time and thrusts are spread over the hours
  its toys were connected during it (over the whole session when no toy
  was — a contact-only session);
* what the lifetime totals hold beyond those sessions (older sessions
  whose summaries have rolled off) is spread over the most recent
  earlier app runs that had a toy connected for a while — as many runs
  as there are missing sessions.

Pure: no Qt, no file writes, no clock — the caller reads the log and
`stats.json`, and stores the result (StatsHistory keeps estimates apart
from what it measured). The charts label estimated hours as such.
"""

import re
import time
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from stats_tracker import _count, _num


# A log line: "2026-07-11 12:42:16,672 INFO    [MainThread] ogp: ..."
_LINE_RE = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2}) (\d{2}):(\d{2}):(\d{2}),\d+ +\w+ +\[[^\]]*\] +[\w.]+: (.*)$")
_START = "OscGoesPurrr starting"
_EXIT = "process exiting"
_CONNECTED = re.compile(r"^Device connected: (.+?) \(\d+ motors?\)")
_DISCONNECTED = re.compile(r"^Device disconnected: (.+)$")

# An earlier run counts as a likely session when a toy was connected for
# at least this long (shorter ones are tests and restarts).
_MIN_RUN_CONNECTED_S = 300.0

# A saved session whose toys were connected for less than this share of
# its active time was mostly contact-only: spread it over the session.
_MIN_CONNECTED_SHARE = 0.25


def _epoch(m: "re.Match") -> float:
    y, mo, d, h, mi, s = (int(m.group(i)) for i in range(1, 7))
    return time.mktime((y, mo, d, h, mi, s, 0, 0, -1))


def parse_runs(lines: Iterable[str]) -> List[Dict[str, Any]]:
    """App runs from debug-log lines (oldest first): {"start", "end",
    "toys": [(name, t0, t1), ...]}. A run ends at its exit line, or at its
    last timestamped line when it never wrote one (killed, crashed)."""
    runs: List[Dict[str, Any]] = []
    run: Optional[Dict[str, Any]] = None
    open_toys: Dict[str, float] = {}

    def close(at: float) -> None:
        nonlocal run
        if run is None:
            return
        for name, t0 in open_toys.items():
            if at > t0:
                run["toys"].append((name, t0, at))
        open_toys.clear()
        run["end"] = max(run["start"], at)
        runs.append(run)
        run = None

    last_t = 0.0
    for raw in lines:
        m = _LINE_RE.match(raw.rstrip("\r\n"))
        if m is None:
            continue
        try:
            t = _epoch(m)
        except (OverflowError, ValueError):
            continue
        msg = m.group(7)
        if msg.startswith(_START):
            close(last_t)
            run = {"start": t, "end": t, "toys": []}
        elif run is not None:
            if msg.startswith(_EXIT):
                close(t)
            else:
                c = _CONNECTED.match(msg)
                if c is not None:
                    open_toys.setdefault(c.group(1), t)
                else:
                    d = _DISCONNECTED.match(msg)
                    if d is not None:
                        t0 = open_toys.pop(d.group(1).strip(), None)
                        if t0 is not None and t > t0:
                            run["toys"].append((d.group(1).strip(), t0, t))
        last_t = t
    close(last_t)
    return runs


def _union(spans: Iterable[Tuple[float, float]]) -> List[Tuple[float, float]]:
    out: List[Tuple[float, float]] = []
    for a, b in sorted(spans):
        if b <= a:
            continue
        if out and a <= out[-1][1]:
            out[-1] = (out[-1][0], max(out[-1][1], b))
        else:
            out.append((a, b))
    return out


def _clip(spans: Iterable[Tuple[float, float]], lo: float, hi: float) -> List[Tuple[float, float]]:
    return [(max(a, lo), min(b, hi)) for a, b in spans if b > lo and a < hi]


def _hour_seconds(spans: Iterable[Tuple[float, float]]) -> Dict[str, float]:
    """Seconds each local clock hour overlaps the spans."""
    out: Dict[str, float] = {}
    for a, b in spans:
        t = a
        while t < b:
            lt = time.localtime(t)
            nxt = t - ((t + lt.tm_gmtoff) % 3600) + 3600
            end = min(b, nxt)
            key = time.strftime("%Y-%m-%dT%H", lt)
            out[key] = out.get(key, 0.0) + (end - t)
            t = end
    return out


def _spread(hours: Dict[str, List[float]], spans: Sequence[Tuple[float, float]],
            active_s: float, thrusts: int) -> None:
    """Add active seconds and thrusts to `hours`, proportional to how much
    of the spans falls in each hour."""
    per_hour = _hour_seconds(spans)
    total = sum(per_hour.values())
    if total <= 0 or (active_s <= 0 and thrusts <= 0):
        return
    for key, secs in per_hour.items():
        share = secs / total
        h = hours.setdefault(key, [0.0, 0.0])
        h[0] += active_s * share
        h[1] += thrusts * share


def estimate(runs: Sequence[Mapping[str, Any]],
             recent_sessions: Sequence[Mapping[str, Any]],
             lifetime: Mapping[str, Any],
             skip_starts: Iterable[float] = ()) -> Dict[str, Any]:
    """Estimated hourly totals from saved sessions + app runs.

    `skip_starts` — start times of sessions that already have a real
    timeline (they are measured, not estimated). Returns {"hours": {hour
    key: [active_s, thrusts]}, "sessions": [start times of the saved
    sessions it placed], "extra_starts": [start times of the earlier runs
    it took as the older sessions], "until_ts": the end of the latest
    estimated stretch (0 when nothing was estimated), "connected": [{
    "started_ts", "toys": {name: [[t0, t1], ...]}} per placed session —
    when each toy was connected during it, straight from the log]}."""
    skip = [float(t) for t in skip_starts]
    hours: Dict[str, List[float]] = {}
    placed: List[float] = []
    connected_by_session: List[Dict[str, Any]] = []
    until = 0.0

    all_toys = [(t0, t1) for r in runs for (_n, t0, t1) in r["toys"]]
    saved = sorted(recent_sessions, key=lambda s: _num(s.get("started_ts")))
    for s in saved:
        start = _num(s.get("started_ts"))
        end = start + _num(s.get("duration_s"))
        active = _num(s.get("active_s"))
        thrusts = _count(s.get("thrusts"))
        if not start or end <= start or any(abs(start - t) < 2.0 for t in skip):
            continue
        if active <= 0 and thrusts <= 0:
            continue
        spans = _union(_clip(all_toys, start, end))
        connected = sum(b - a for a, b in spans)
        if connected < active * _MIN_CONNECTED_SHARE or connected <= 0:
            spans = [(start, end)]
        _spread(hours, spans, active, thrusts)
        placed.append(start)
        until = max(until, end)
        per_toy: Dict[str, List[Tuple[float, float]]] = {}
        for r in runs:
            for name, t0, t1 in r["toys"]:
                if t1 > start and t0 < end:
                    per_toy.setdefault(name, []).append(
                        (max(t0, start), min(t1, end)))
        if per_toy:
            connected_by_session.append({
                "started_ts": start,
                "toys": {name: [[round(a, 1), round(b, 1)] for a, b in _union(sp)]
                         for name, sp in per_toy.items()},
            })

    # What the lifetime totals hold beyond the saved sessions.
    rem_n = _count(lifetime.get("sessions")) - len(saved)
    rem_active = _num(lifetime.get("active_s")) - sum(_num(s.get("active_s")) for s in saved)
    rem_thrusts = _count(lifetime.get("thrusts")) - sum(_count(s.get("thrusts")) for s in saved)
    extra: List[float] = []
    if rem_n > 0 and (rem_active > 60 or rem_thrusts > 0):
        first_saved = _num(saved[0].get("started_ts")) if saved else float("inf")
        candidates = []
        for r in runs:
            if r["end"] > first_saved:
                continue
            spans = _union((t0, t1) for (_n, t0, t1) in r["toys"])
            if sum(b - a for a, b in spans) >= _MIN_RUN_CONNECTED_S:
                candidates.append((r["start"], spans))
        candidates.sort(key=lambda c: c[0], reverse=True)
        taken = candidates[:rem_n]
        spans = [sp for _start, run_spans in taken for sp in run_spans]
        if spans:
            _spread(hours, spans, max(0.0, rem_active), max(0, rem_thrusts))
            extra = sorted(start for start, _ in taken)
            until = max(until, max(b for _a, b in spans))

    # An hour holds at most an hour of activity.
    clean = {k: [round(min(3600.0, a), 1), int(round(t))]
             for k, (a, t) in hours.items() if a > 0 or t > 0}
    return {"hours": clean, "sessions": placed, "extra_starts": extra,
            "until_ts": until, "connected": connected_by_session}
