"""Usage-statistics controller facade.

Mixin: owns the `StatsTracker` (lifetime totals + per-session
summaries) and the `StatsHistory` (session timelines + hourly totals
behind the charts), and adapts the app's live state into their 1 Hz
samples.

Wiring contract:

* `main._setup_components()` calls `_stats_init()` once, after the
  motor router exists.
* `main.run()`'s 1 Hz `refresh_device_states` heartbeat calls
  `_stats_sample_tick()` — that's the whole sampling cadence; no
  timer or thread of its own, and nothing touches a routing hot path
  beyond the router's O(1) `consume_thrusts()` drain.
* `quit_app()` calls `_stats_shutdown()` before engine teardown so
  the session summary + final flush land on disk.

Host attributes assumed: `self.motor_router`, `self.haptic_engine`,
`self._muted_devices`, and the modes facade's `get_master_scale()`.
"""

import shutil
import time
from typing import Any, Dict, List, Optional, Tuple

import debug_log
from parameter_store import store
from router_base import StaleSignalMonitor
from settings import STATS_FILE, STATS_HOURS_FILE, STATS_SESSIONS_DIR
from stats_backfill import estimate as estimate_history, parse_runs
from stats_gate import ActivityGate, GATE_VERSION, MIN_CONTACT_S, MIN_THRUSTS
from stats_history import (
    StatsHistory, analyse, dense, fun_facts, hour_key, month_days,
    summarize, weekday_hour,
)
from stats_tracker import StatsTracker
from utilities import process_alive
from zone_strength import zone_filter_strength


# parameter_store.get_detected_zones() bucket -> OGB zone-type prefix.
_ZONE_BUCKETS: Tuple[Tuple[str, str], ...] = (
    ("Orifices", "Orf"),
    ("Penetrators", "Pen"),
    ("Touch", "Touch"),
)

# Every filter zone_strength can resolve for a zone type. Contact for
# statistics means "any signal at all", so this is the union of what
# the routers select from per type: Orf/Pen carry the four
# touch/pen filters plus FrotOthers (zone_filter_strength applies the
# generic <filter>Close gate, absent = open, so FrotOthers works on
# both sides); Touch zones only ever expose Self/Others proximity.
_CONTACT_FILTERS: Dict[str, List[str]] = {
    # PenetratingSelf/Others are the legacy parameter names older
    # avatars emit — the motor router falls back to them, so contact
    # statistics must see them too or those zones read 0 forever.
    "Orf": ["TouchSelf", "TouchOthers", "PenSelf", "PenOthers",
            "FrotOthers", "PenetratingSelf", "PenetratingOthers"],
    "Pen": ["TouchSelf", "TouchOthers", "PenSelf", "PenOthers",
            "FrotOthers", "PenetratingSelf", "PenetratingOthers"],
    "Touch": ["TouchSelf", "TouchOthers"],
}

# Cap on a single sample's dt. The heartbeat runs at 1 Hz, so anything
# much larger means the process was suspended (laptop sleep, debugger
# pause) — hours nobody was being touched must not count as on-time.
_MAX_SAMPLE_DT_S = 5.0

# Flush the stats files roughly once a minute of sampling. Losing up to
# a minute of lifetime totals on a hard crash is fine; the session
# summary lands via finalize at clean shutdown, or from its timeline at
# the next launch when there was none.
_FLUSH_EVERY_SAMPLES = 60

# A session saved before the activity gate existed (totals only) still
# counts when a toy ran at least this long, it has MIN_THRUSTS thrusts, or
# MIN_CONTACT_S of activity — as close to the gate's rule as totals can
# tell.
_MIN_TOY_ON_S = 30.0

# A stats.json recent-session entry and a timeline are the same session
# when their start times agree this closely (both come from one
# time.time() read; the file round-trip keeps full precision).
_SAME_SESSION_S = 2.0


def _delete_stats_files() -> None:
    """Every file the statistics keep: the totals, the hourly history, the
    session timelines, and their backups and leftovers."""
    for path in (STATS_FILE, STATS_HOURS_FILE):
        for suffix in ("", ".bak", ".before-gate.bak", ".tmp"):
            target = path.with_name(path.name + suffix)
            try:
                target.unlink()
            except FileNotFoundError:
                pass
            except OSError as e:
                print(f"[stats] could not delete {target.name}: {e}")
    shutil.rmtree(STATS_SESSIONS_DIR, ignore_errors=True)


class StatsFacade:
    """Mixin: usage statistics. Composed into OscGoesPurrrApp."""

    # ------------------------------------------------------------------
    # Init / shutdown wiring (called from main.py)
    # ------------------------------------------------------------------

    def _stats_init(self) -> None:
        """Build the tracker and the history and open this app run's
        session. Called from _setup_components after the motor router
        exists. Guarded: statistics must never be able to break app boot
        — both stores self-heal corrupt files, but if anything still
        raises, that store stays off for the session and everything else
        runs."""
        now = time.time()
        self.stats_tracker = None
        self.stats_history = None
        # Monotonic timestamp of the previous sample; None = no sample
        # yet (the first heartbeat only anchors the clock).
        self._stats_last_sample_t = None
        self._stats_samples_since_flush = 0
        # parameter_store retains values forever; if VRChat dies with a
        # contact latched high, zone "contact" would accrue off the
        # frozen snapshot indefinitely. Same primitive the routers use.
        self._stats_stale_monitor = StaleSignalMonitor()
        # Holds back contact-only activity until it is a real scene.
        self._stats_gate = ActivityGate()
        if not self._stats_feature_on():
            # Settings → Features → Usage statistics is off: record
            # nothing and touch no file.
            return
        try:
            self.stats_tracker = StatsTracker(STATS_FILE)
            self.stats_tracker.start_session(now)
        except Exception as e:
            print(f"[stats] init failed, statistics disabled: {e}")
        try:
            self.stats_history = StatsHistory(STATS_SESSIONS_DIR,
                                              STATS_HOURS_FILE)
            # A run that was killed left its timeline open: close it now
            # and give it the session entry its shutdown never wrote.
            for summary in self.stats_history.recover_unfinished(process_alive):
                if self.stats_tracker is not None:
                    self.stats_tracker.add_recovered_session(summary)
            self.stats_history.start_session(now)
        except Exception as e:
            print(f"[stats] history init failed, charts disabled: {e}")
            self.stats_history = None
        reestimate = False
        try:
            reestimate = self._stats_clean_history()
        except Exception as e:
            print(f"[stats] cleaning up older statistics failed: {e}")
        try:
            self._stats_estimate_history(force=reestimate)
        except Exception as e:
            print(f"[stats] estimating earlier hours failed: {e}")

    def _stats_feature_on(self) -> bool:
        get = getattr(self, "get_feature_enabled", None)
        if get is None:
            return True
        try:
            return bool(get("feature_statistics"))
        except Exception:
            return True

    def _stats_set_enabled(self, enabled: bool) -> None:
        """Settings → Features → Usage statistics (main's feature switch).
        Off: stop recording and delete everything recorded — the user
        asked for it gone, and the Settings switch asked first. On: start
        recording afresh."""
        if enabled:
            if self.stats_tracker is None and self.stats_history is None:
                self._stats_init()
            return
        self.stats_tracker = None
        self.stats_history = None
        self._stats_gate = ActivityGate()
        _delete_stats_files()

    def _stats_clean_history(self) -> bool:
        """Apply the activity gate to what was recorded before it existed,
        once: timelines from the first test builds lose the buckets that
        don't count, and totals-only sessions that couldn't have passed it
        are dropped — the tracker's totals shrink by the same amounts.
        `stats.json` and `stats_hours.json` are copied to `*.before-gate.bak`
        first. Returns True when an existing estimate should be redone
        (the sessions it was built from changed)."""
        hist, tracker = self.stats_history, self.stats_tracker
        if hist is None or tracker is None:
            return False
        timed = {int(e["started_ts"]) for e in hist.index}

        def keep(e: Dict[str, Any]) -> bool:
            if int(e.get("started_ts", 0)) in timed:
                return True
            toy_s = sum(v.get("on_s", 0.0) for v in (e.get("toys") or {}).values())
            return (toy_s >= _MIN_TOY_ON_S
                    or e.get("thrusts", 0) >= MIN_THRUSTS
                    or e.get("active_s", 0.0) >= MIN_CONTACT_S)

        ungated = any(e.get("gated", 0) < GATE_VERSION for e in hist.index)
        noisy = any(not keep(e) for e in tracker.recent_sessions)
        if not ungated and not noisy:
            return False
        for path in (STATS_FILE, STATS_HOURS_FILE):
            backup = path.with_name(path.name + ".before-gate.bak")
            try:
                if path.exists() and not backup.exists():
                    shutil.copy2(path, backup)
            except OSError as e:
                print(f"[stats] backup of {path.name} failed: {e}")
        for res in hist.regate_finished():
            tracker.discount(res["started_ts"], res["dropped"], res["removed"])
        removed = tracker.drop_sessions(keep)
        tracker.flush(force=True)
        est = hist.estimate_info()
        return bool(removed) and est["until_ts"] > 0

    def _stats_estimate_history(self, force: bool = False) -> None:
        """Once, on the first launch with the hourly history: estimate the
        hours before it from the saved session totals and the app's debug
        log (stats_backfill), so the charts don't start empty. Reads at
        most the log and its three rotations (~8 MB); runs before the UI
        exists, never again after — unless `force` (the saved sessions it
        was built from changed)."""
        hist, tracker = self.stats_history, self.stats_tracker
        if hist is None or tracker is None:
            return
        if not hist.needs_estimate() and not force:
            return
        lines: List[str] = []
        base = debug_log.log_path()
        for path in [base.with_name(f"{base.name}.{n}") for n in (3, 2, 1)] + [base]:
            try:
                with open(path, "r", encoding="utf-8", errors="replace") as f:
                    lines.extend(f.read().splitlines())
            except OSError:
                continue
        est = estimate_history(
            parse_runs(lines), tracker.recent_sessions, tracker.lifetime,
            skip_starts=[e["started_ts"] for e in hist.index])
        hist.set_estimate(est)

    def _stats_shutdown(self) -> None:
        """Finalize the session (records it if it saw activity) and
        flush. Called from quit_app before engine teardown."""
        now = time.time()
        try:
            self.stats_tracker.finalize_session(now)
        except Exception:
            pass
        try:
            self.stats_history.finalize_session(now)
        except Exception:
            pass

    # ------------------------------------------------------------------
    # 1 Hz sampling (called from main.py's device-state heartbeat)
    # ------------------------------------------------------------------

    def _stats_sample_tick(self) -> None:
        """Gather one usage sample and hand it to the tracker and the
        history. The whole body is guarded — a stats bug must never
        break the heartbeat that hosts it."""
        try:
            if self.stats_tracker is None and self.stats_history is None:
                return
            now = time.monotonic()
            last = self._stats_last_sample_t
            self._stats_last_sample_t = now
            if last is None:
                return
            dt = min(max(0.0, now - last), _MAX_SAMPLE_DT_S)

            # Toys currently driven — meaning ACTUALLY driven. The
            # router's last_outputs covers every stored toy (wiring is
            # remembered for offline devices) and is computed upstream
            # of every silencing layer, so it alone would book on-time
            # against toys in a drawer, muted toys, the Off mode, and
            # simulator-suppressed motors. Apply the same gates
            # update_device_target applies before anything reaches
            # hardware. Keys are (device, motor) tuples; this read and
            # the router's writes share the GUI thread. A toy's level is
            # its strongest motor times the master scale — what it felt.
            levels: Dict[str, float] = {}
            engine = getattr(self, "haptic_engine", None)
            scale = self.get_master_scale() if engine is not None else 0.0
            if engine is not None and engine.is_connected and scale > 0.0:
                try:
                    connected = set(
                        engine.list_connected_device_names() or ())
                except Exception:
                    connected = set()
                muted = getattr(self, "_muted_devices", set())
                router = self.motor_router
                for (device, motor), val in router.last_outputs.items():
                    if (val > 0.0
                            and device in connected
                            and device not in muted
                            and router.should_send_to_toy(device, motor)):
                        level = min(1.0, float(val) * scale)
                        if level > levels.get(device, 0.0):
                            levels[device] = level
            on_toys = sorted(levels)

            # Zones currently in contact: every detected zone whose
            # full filter set resolves to a non-zero strength — but only
            # while OSC is demonstrably alive. The store retains values
            # forever, so a crash mid-contact would otherwise read as
            # "in contact" for hours.
            contact_zones: List[Tuple[str, str]] = []
            if not self._stats_stale_monitor.is_stale():
                detected = store.get_detected_zones() or {}
                params = store.get_all_parameters() or {}
                for bucket, ztype in _ZONE_BUCKETS:
                    filters = _CONTACT_FILTERS[ztype]
                    for zone_name in detected.get(bucket, ()):
                        strength = zone_filter_strength(
                            zone_name, ztype, filters, params, None)
                        if strength > 0.0:
                            contact_zones.append(
                                (f"{ztype}/{zone_name}", ztype))

            thrusts = self.motor_router.consume_thrusts()
            flush = False
            self._stats_samples_since_flush += 1
            if self._stats_samples_since_flush >= _FLUSH_EVERY_SAMPLES:
                self._stats_samples_since_flush = 0
                flush = True

            # The activity gate: with no toy running, stray contacts and
            # lone strokes are held back until they add up to a scene, and
            # dropped when they don't (stats_gate). What it lets through
            # may include held-back samples, each with its own time.
            sample = (time.time(), dt, levels, on_toys, contact_zones, thrusts)
            released = self._stats_gate.push(
                sample[0], sample, bool(levels),
                dt if contact_zones else 0.0, thrusts)
            for epoch, s_dt, s_levels, s_toys, s_zones, s_thrusts in released:
                if self.stats_tracker is not None:
                    self.stats_tracker.sample(s_dt, s_toys, s_zones, s_thrusts)
                # Separately guarded: a history bug must not stop the
                # lifetime totals above from being counted.
                try:
                    if self.stats_history is not None:
                        self.stats_history.sample(
                            epoch, s_dt, s_levels,
                            [key for key, _ in s_zones], s_thrusts)
                except Exception as e:
                    print(f"[stats] history sample failed: {e}")
            if flush:
                if self.stats_tracker is not None:
                    self.stats_tracker.flush()
                try:
                    if self.stats_history is not None:
                        self.stats_history.flush()
                except Exception as e:
                    print(f"[stats] history flush failed: {e}")
        except Exception:
            pass

    # ------------------------------------------------------------------
    # UI facade
    # ------------------------------------------------------------------

    def get_stats_snapshot(self) -> Dict[str, Any]:
        """Deep-copied {"lifetime", "session", "recent_sessions"} for
        the Statistics view. Defensive: never raises into the UI."""
        try:
            return self.stats_tracker.snapshot()
        except Exception:
            return {}

    def reset_stats(self) -> None:
        """Zero ALL statistics — lifetime totals, recent sessions, every
        session timeline and the hourly history — and start a fresh
        session anchored now."""
        now = time.time()
        try:
            self.stats_tracker.reset_lifetime()
            self.stats_tracker.start_session(now)
        except Exception:
            pass
        try:
            self.stats_history.reset(now)
        except Exception:
            pass

    def _stats_all_sessions(self) -> List[Dict[str, Any]]:
        """Every session we know, newest first: the running one (while it
        has activity), every finished timeline, and the stats.json
        sessions that have no timeline — recorded before the history
        existed, or by the full edition, which shares the folder.

        Each row: id, kind ("live" / "timeline" / "summary"), started_ts,
        duration_s, active_s, thrusts, peak_pace, spark (None for
        "summary"), recovered, timeline (bool), toys, zones."""
        rows: List[Dict[str, Any]] = []
        hist = self.stats_history
        if hist is not None:
            live = hist.live_summary(time.time())
            if live is not None:
                live.update(kind="live", timeline=True)
                rows.append(live)
            for entry in hist.session_list():
                entry.update(kind="timeline", timeline=True)
                rows.append(entry)
        # Whole seconds around every timeline's start, for an O(1) match.
        reach = int(_SAME_SESSION_S)
        starts = set()
        for r in rows:
            sec = int(r["started_ts"])
            starts.update(range(sec - reach, sec + reach + 1))
        estimated = set()
        connected: Dict[int, Dict[str, Any]] = {}
        if hist is not None:
            info = hist.estimate_info()
            for t in info["sessions"]:
                estimated.update(range(int(t) - reach, int(t) + reach + 1))
            for entry in info["connected"]:
                connected[int(entry["started_ts"])] = entry["toys"]
        tracker = self.stats_tracker
        if tracker is not None:
            for s in tracker.recent_sessions:
                ts = s.get("started_ts", 0.0)
                if int(ts) in starts:
                    continue
                rows.append({
                    "id": f"summary:{ts:.3f}",
                    "kind": "summary",
                    "timeline": False,
                    # Its hours are in the estimate (stats_backfill).
                    "in_hours": int(ts) in estimated,
                    # When each toy was connected, from the app's log.
                    "connected": connected.get(int(ts)),
                    "started_ts": ts,
                    "ended_ts": ts + s.get("duration_s", 0.0),
                    "duration_s": s.get("duration_s", 0.0),
                    "active_s": s.get("active_s", 0.0),
                    "thrusts": s.get("thrusts", 0),
                    "peak_pace": 0,
                    "recovered": False,
                    "spark": None,
                    "toys": {k: v.get("on_s", 0.0)
                             for k, v in (s.get("toys") or {}).items()},
                    "zones": {k: v.get("contact_s", 0.0)
                              for k, v in (s.get("zones") or {}).items()},
                })
        rows.sort(key=lambda r: r["started_ts"], reverse=True)
        return rows

    def get_stats_sessions(self) -> List[Dict[str, Any]]:
        """Session list for the Statistics page, newest first (see
        `_stats_all_sessions` for the row shape). Never raises."""
        try:
            return self._stats_all_sessions()
        except Exception as e:
            print(f"[stats] session list failed: {e}")
            return []

    def get_stats_session_detail(self, session_id: str) -> Optional[Dict[str, Any]]:
        """One session for its page: the list row's fields plus, for a
        session with a timeline, `bucket_s`, `dense` (per-bucket arrays,
        see stats_history.dense) and `analysis` (stats_history.analyse).
        A "summary" session has totals only. None if it is gone."""
        try:
            sid = str(session_id or "")
            if sid.startswith("summary:"):
                for row in self._stats_all_sessions():
                    if row["id"] == sid:
                        return row
                return None
            hist = self.stats_history
            if hist is None:
                return None
            tl = hist.timeline(sid)
            if tl is None:
                return None
            live = hist.is_live(sid)
            out = summarize(tl, time.time() if live else None)
            out.update(kind="live" if live else "timeline", timeline=True,
                       bucket_s=tl["bucket_s"], dense=dense(tl),
                       analysis=analyse(tl))
            return out
        except Exception as e:
            print(f"[stats] session detail failed: {e}")
            return None

    def get_stats_patterns(self, days: Optional[int] = None) -> Dict[str, Any]:
        """Weekday x hour grids of active seconds and thrusts over the
        last `days` days (None = everything), plus `first_hour` — the
        earliest hour on record (None before any)."""
        try:
            hours = self.stats_history.hours_snapshot()
        except Exception:
            hours = {}
        since = hour_key(time.time() - days * 86400) if days else None
        out = weekday_hour(hours, since)
        out["first_hour"] = min(hours) if hours else None
        out["estimated_until"] = self._stats_estimated_until()
        return out

    def _stats_estimated_until(self) -> float:
        """Where the estimated hours end (0 when there are none)."""
        try:
            return float(self.stats_history.estimate_info()["until_ts"])
        except Exception:
            return 0.0

    def get_stats_month(self, year: int, month: int) -> Dict[int, Dict[str, Any]]:
        """day -> {active_s, thrusts, sessions} for one calendar month."""
        try:
            hours = self.stats_history.hours_snapshot()
        except Exception:
            hours = {}
        try:
            sessions = self._stats_all_sessions()
        except Exception:
            sessions = []
        # The older sessions the estimate placed (their hours are already
        # in `hours`) still count as sessions on their day.
        try:
            for t in self.stats_history.estimate_info()["extra_starts"]:
                sessions.append({"started_ts": t, "in_hours": True})
        except Exception:
            pass
        return month_days(hours, sessions, int(year), int(month))

    def get_stats_fun_facts(self) -> Dict[str, Any]:
        """The lifetime card's fun facts (stats_history.fun_facts)."""
        try:
            lifetime = (self.stats_tracker.snapshot() or {}).get("lifetime") or {}
        except Exception:
            lifetime = {}
        try:
            hours = self.stats_history.hours_snapshot()
        except Exception:
            hours = {}
        try:
            sessions = self._stats_all_sessions()
        except Exception:
            sessions = []
        try:
            return fun_facts(lifetime, sessions, hours)
        except Exception as e:
            print(f"[stats] fun facts failed: {e}")
            return {}
