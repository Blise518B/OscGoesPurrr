"""Tests for `StatsHistory` and the pure chart helpers — bucketing,
hourly totals, the live/finished/recovered session lifecycle, index
upkeep, defensive loading, and the session analysis."""

import json
import time

import pytest

import stats_history as sh
from stats_history import (
    BUCKET_S, StatsHistory, analyse, dense, fun_facts, hour_key, month_days,
    summarize, weekday_hour,
)
from stats_tracker import StatsTracker
from controllers.stats_facade import StatsFacade


T0 = 1_790_000_000.0   # a fixed epoch; everything is relative to it


@pytest.fixture
def paths(tmp_path):
    return tmp_path / "stats_sessions", tmp_path / "stats_hours.json"


@pytest.fixture
def hist(paths):
    h = StatsHistory(*paths, pid=111)
    h.start_session(T0)
    return h


def _play(h, start_offset, seconds, toys=None, zones=(), thrusts_every=0):
    """Feed `seconds` one-second samples starting at T0 + start_offset."""
    toys = {"Domi": 0.5} if toys is None else toys
    for k in range(seconds):
        t = 0
        if thrusts_every and k % thrusts_every == 0:
            t = 1
        h.sample(T0 + start_offset + k + 1, 1.0, toys, zones, t)


# ============================================================ sampling

class TestSampling:
    def test_idle_samples_record_nothing(self, hist):
        hist.sample(T0 + 1, 1.0, {}, [], 0)
        hist.sample(T0 + 2, 1.0, {"Domi": 0.0}, [], 0)
        assert hist.live["buckets"] == {}
        assert hist.hours == {}

    def test_samples_land_in_ten_second_buckets(self, hist):
        _play(hist, 0, 25, toys={"Domi": 0.5}, zones=["Orf/Pussy"])
        buckets = hist.live["buckets"]
        assert sorted(buckets) == [0, 1, 2]
        b0 = buckets[0]
        assert b0["a"] == pytest.approx(9.0)        # samples at +1..+9
        assert b0["y"]["Domi"][0] == pytest.approx(9.0)
        assert b0["y"]["Domi"][1] == pytest.approx(4.5)   # level x dt
        assert b0["z"]["Orf/Pussy"] == pytest.approx(9.0)

    def test_thrusts_count_even_without_activity(self, hist):
        hist.sample(T0 + 3, 1.0, {}, [], 2)
        assert hist.live["buckets"][0]["t"] == 2
        assert hist.live["buckets"][0]["a"] == 0.0

    def test_levels_are_clamped(self, hist):
        hist.sample(T0 + 1, 1.0, {"Domi": 7.0}, [], 0)
        assert hist.live["buckets"][0]["y"]["Domi"] == [1.0, 1.0]

    def test_hourly_totals(self, hist):
        _play(hist, 0, 30, thrusts_every=10)
        key = hour_key(T0 + 1)
        assert hist.hours[key][0] == pytest.approx(30.0)
        assert hist.hours[key][1] == 3


# ============================================================ lifecycle

class TestLifecycle:
    def test_idle_run_leaves_no_trace(self, hist, paths):
        sessions_dir, hours_file = paths
        assert hist.finalize_session(T0 + 600) is None
        assert not sessions_dir.exists() or not list(sessions_dir.glob("*.json"))
        assert hist.index == []

    def test_flush_writes_live_file_with_pid(self, hist, paths):
        sessions_dir, hours_file = paths
        _play(hist, 0, 5)
        hist.flush()
        live = sessions_dir / f"{hist.live['id']}.live.json"
        data = json.loads(live.read_text("utf-8"))
        assert data["pid"] == 111
        assert data["ended_ts"] is None
        assert json.loads(hours_file.read_text("utf-8"))["hours"]

    def test_finalize_writes_timeline_and_index(self, hist, paths):
        sessions_dir, _ = paths
        _play(hist, 0, 60, thrusts_every=2)
        sid = hist.live["id"]
        hist.flush()
        summary = hist.finalize_session(T0 + 3600)
        assert summary["id"] == sid
        assert summary["duration_s"] == pytest.approx(3600.0)
        assert summary["active_s"] == pytest.approx(60.0)
        assert summary["thrusts"] == 30
        assert summary["peak_pace"] == 30
        assert summary["toys"] == {"Domi": 60.0}
        assert not (sessions_dir / f"{sid}.live.json").exists()
        assert (sessions_dir / f"{sid}.json").exists()
        index = json.loads((sessions_dir / "index.json").read_text("utf-8"))
        assert [e["id"] for e in index["sessions"]] == [sid]
        # And a fresh session is running, with a different id.
        assert hist.live["id"] != sid and hist.live["buckets"] == {}

    def test_finished_timeline_reads_back(self, hist):
        _play(hist, 0, 20, zones=["Touch/Hand"])
        sid = hist.live["id"]
        hist.finalize_session(T0 + 100)
        tl = hist.timeline(sid)
        assert tl is not None and tl["ended_ts"] == T0 + 100
        assert tl["buckets"][1]["z"]["Touch/Hand"] == pytest.approx(10.0)

    def test_live_timeline_comes_from_memory(self, hist):
        _play(hist, 0, 5)
        assert hist.timeline(hist.live["id"]) is hist.live
        assert hist.is_live(hist.live["id"])

    def test_timeline_rejects_odd_ids(self, hist):
        assert hist.timeline("../stats") is None
        assert hist.timeline("20260101-000000") is None

    def test_same_second_restart_gets_a_new_id(self, paths):
        a = StatsHistory(*paths, pid=1)
        a.start_session(T0)
        _play(a, 0, 3)
        a.finalize_session(T0 + 10)
        b = StatsHistory(*paths, pid=2)
        b.start_session(T0)
        assert b.live["id"] == a.index[0]["id"] + "-2"

    def test_index_is_capped(self, paths, monkeypatch):
        monkeypatch.setattr(sh, "SESSIONS_CAP", 3)
        h = StatsHistory(*paths, pid=1)
        for n in range(5):
            h.start_session(T0 + n * 1000)
            h.sample(T0 + n * 1000 + 1, 1.0, {"Domi": 1.0}, [], 0)
            h.finalize_session(T0 + n * 1000 + 10)
        assert len(h.index) == 3
        files = [p for p in paths[0].glob("*.json") if p.name != "index.json"]
        assert len(files) == 3
        assert h.index[0]["started_ts"] == T0 + 4000   # newest first

    def test_reset_forgets_everything(self, hist, paths):
        _play(hist, 0, 20)
        hist.finalize_session(T0 + 100)
        _play(hist, 200, 5)
        hist.flush()
        hist.reset(T0 + 500)
        assert hist.index == [] and hist.hours == {}
        assert list(paths[0].glob("*.json")) == []
        assert hist.live["started_ts"] == T0 + 500


# ============================================================ recovery

class TestRecovery:
    def _crash(self, paths, pid=111):
        h = StatsHistory(*paths, pid=pid)
        h.start_session(T0)
        _play(h, 0, 35, thrusts_every=5)
        h.flush()
        return h.live["id"]

    def test_killed_session_is_closed_at_next_launch(self, paths):
        sid = self._crash(paths)
        h = StatsHistory(*paths, pid=222)
        recovered = h.recover_unfinished(lambda pid: False)
        assert [s["id"] for s in recovered] == [sid]
        s = recovered[0]
        assert s["recovered"] is True
        # Ends at the end of the last recorded bucket (+31..+35 -> bucket 3).
        assert s["duration_s"] == pytest.approx(4 * BUCKET_S)
        assert s["thrusts"] == 7
        assert not (paths[0] / f"{sid}.live.json").exists()
        assert h.index[0]["id"] == sid

    def test_a_running_writer_is_left_alone(self, paths):
        sid = self._crash(paths, pid=111)
        h = StatsHistory(*paths, pid=222)
        assert h.recover_unfinished(lambda pid: pid == 111) == []
        assert (paths[0] / f"{sid}.live.json").exists()

    def test_recovered_session_reaches_the_tracker(self, paths, tmp_path):
        self._crash(paths)
        tracker = StatsTracker(tmp_path / "stats.json")
        h = StatsHistory(*paths, pid=222)
        for s in h.recover_unfinished():
            tracker.add_recovered_session(s)
            tracker.add_recovered_session(s)        # idempotent
        assert tracker.lifetime["sessions"] == 1
        entry = tracker.recent_sessions[0]
        assert entry["started_ts"] == T0
        assert entry["toys"]["Domi"]["on_s"] == pytest.approx(35.0)


# ============================================================ defensive loads

class TestDefensiveLoading:
    def test_corrupt_hours_file_is_set_aside(self, paths):
        sessions_dir, hours_file = paths
        hours_file.write_text("{not json", encoding="utf-8")
        h = StatsHistory(*paths)
        assert h.hours == {}
        assert hours_file.with_name(hours_file.name + ".bak").exists()

    def test_bad_hour_entries_are_dropped(self, paths):
        _, hours_file = paths
        hours_file.write_text(json.dumps({"hours": {
            "2026-09-30T22": [120, 5], "nonsense": [1, 1],
            "2026-09-30T23": ["x", -3], "2026-10-01T00": "bad"}}),
            encoding="utf-8")
        h = StatsHistory(*paths)
        assert h.hours == {"2026-09-30T22": [120.0, 5],
                           "2026-09-30T23": [0.0, 0]}

    def test_missing_index_is_rebuilt_from_timelines(self, hist, paths):
        _play(hist, 0, 20)
        sid = hist.live["id"]
        hist.finalize_session(T0 + 100)
        (paths[0] / "index.json").unlink()
        h = StatsHistory(*paths)
        assert [e["id"] for e in h.index] == [sid]
        assert (paths[0] / "index.json").exists()

    def test_garbage_timeline_rows_are_skipped(self, paths):
        sessions_dir, _ = paths
        sessions_dir.mkdir()
        (sessions_dir / "20260101-000000.json").write_text(json.dumps({
            "started_ts": T0, "ended_ts": T0 + 50, "bucket_s": 10,
            "buckets": [[0, 5, 1, {"Domi": [5, 9]}, {}], "junk", [-1, 1, 1],
                        [2, "x", 1]]}),
            encoding="utf-8")
        h = StatsHistory(*paths)
        tl = h.timeline("20260101-000000")
        assert sorted(tl["buckets"]) == [0, 2]
        # Level-seconds can never exceed on-seconds.
        assert tl["buckets"][0]["y"]["Domi"] == [5.0, 5.0]


# ============================================================ analysis

def _timeline(spec, bs=BUCKET_S):
    """spec: {bucket: (active_s, thrusts, {toy: (on, lvl)}, {zone: s})}"""
    buckets = {}
    for i, (a, t, toys, zones) in spec.items():
        buckets[i] = {"a": float(a), "t": t,
                      "y": {k: [float(v[0]), float(v[1])] for k, v in toys.items()},
                      "z": {k: float(v) for k, v in zones.items()}}
    return {"id": "20260101-000000", "started_ts": T0, "ended_ts": None,
            "bucket_s": bs, "recovered": False, "buckets": buckets}


class TestAnalysis:
    def test_dense_spans_first_to_last_active_bucket(self):
        tl = _timeline({5: (10, 2, {"Domi": (10, 5)}, {"Orf/A": 10}),
                        8: (4, 0, {}, {})})
        d = dense(tl)
        assert d["start_i"] == 5 and d["n"] == 4
        assert d["active"] == [10.0, 0.0, 0.0, 4.0]
        assert d["toys"]["Domi"] == [0.5, 0.0, 0.0, 0.0]
        assert d["zones"]["Orf/A"] == [1.0, 0.0, 0.0, 0.0]

    def test_peak_hot_streak_break(self):
        spec = {}
        for i in range(0, 12):                   # 2 minutes busy
            spec[i] = (10, 3 if i >= 6 else 1, {"Domi": (10, 8)}, {"Orf/A": 10})
        for i in range(30, 33):                  # after a 3-minute break
            spec[i] = (10, 0, {"Hush": (10, 2)}, {"Pen/B": 5})
        a = analyse(_timeline(spec))
        assert a["peak_pace"] == 18              # buckets 6..11, 3 each
        assert a["peak_pace_at_s"] == 60
        assert a["hot_kind"] == "thrusts"
        assert a["hot_value"] == 24              # 6x1 + 6x3 inside 5 minutes
        assert a["streak_s"] == 120
        assert a["break_s"] == 180 and a["break_at_s"] == 120
        assert a["top_toy"] == "Domi"
        assert a["top_toy_share"] == pytest.approx(120 / 150)
        assert a["top_toy_level"] == pytest.approx(0.8)
        assert a["top_zone"] == "Orf/A" and a["top_zone_s"] == 120

    def test_short_gaps_do_not_break_a_streak(self):
        spec = {i: (10, 0, {"Domi": (10, 5)}, {}) for i in (0, 1, 4, 5)}
        a = analyse(_timeline(spec))
        assert a["streak_s"] == 60
        assert a["break_s"] == 0                 # 20 s isn't a break

    def test_vibe_only_session_reports_intensity(self):
        spec = {i: (10, 0, {"Domi": (10, 10 if i == 3 else 2)}, {}) for i in range(6)}
        a = analyse(_timeline(spec))
        assert a["hot_kind"] == "intensity"
        assert 0.0 < a["hot_value"] <= 1.0

    def test_empty_timeline(self):
        a = analyse(_timeline({}))
        assert a["peak_pace"] == 0 and a["top_toy"] is None

    def test_summary_sparkline_is_activity_share(self):
        spec = {0: (10, 0, {}, {"Orf/A": 10}), 1: (5, 0, {}, {"Orf/A": 5})}
        s = summarize(_timeline(spec), now_epoch=T0 + 100)
        assert s["spark"] == [1.0, 0.5]
        assert s["duration_s"] == 100


# ============================================================ charts' data

class TestAggregations:
    def test_weekday_hour(self):
        hours = {
            "2026-09-28T22": [600.0, 10],   # a Monday
            "2026-09-29T01": [300.0, 4],    # a Tuesday
            "2026-08-01T10": [60.0, 1],     # a Saturday, old
        }
        g = weekday_hour(hours)
        assert g["active"][0][22] == 600.0 and g["thrusts"][1][1] == 4
        assert g["active"][5][10] == 60.0
        g = weekday_hour(hours, since="2026-09-01T00")
        assert g["active"][5][10] == 0.0

    def test_month_days_mix_hours_and_untimed_sessions(self):
        hours = {"2026-09-30T00": [600.0, 10], "2026-09-30T01": [60.0, 2],
                 "2026-10-01T00": [5.0, 0]}
        sep30 = time.mktime((2026, 9, 30, 0, 30, 0, 0, 0, -1))
        sep7 = time.mktime((2026, 9, 7, 5, 0, 0, 0, 0, -1))
        sessions = [
            {"started_ts": sep30, "active_s": 660, "thrusts": 12, "timeline": True},
            {"started_ts": sep7, "active_s": 5123, "thrusts": 0, "timeline": False},
        ]
        days = month_days(hours, sessions, 2026, 9)
        assert days[30] == {"active_s": 660.0, "thrusts": 12, "sessions": 1}
        assert days[7] == {"active_s": 5123.0, "thrusts": 0, "sessions": 1}
        assert 1 not in days

    def test_fun_facts_only_say_what_they_can(self):
        assert fun_facts({}, [], {}) == {}
        lifetime = {"sessions": 4, "active_s": 3600.0, "thrusts": 1200,
                    "toys": {"Domi": {"on_s": 300.0}, "Hush": {"on_s": 100.0}},
                    "zones": {"Orf/A": {"type": "Orf", "contact_s": 50.0}}}
        sessions = [{"started_ts": 1.0, "thrusts": 900, "active_s": 100.0,
                     "peak_pace": 40},
                    {"started_ts": 2.0, "thrusts": 300, "active_s": 2000.0,
                     "peak_pace": 0}]
        hours = {"2026-09-28T23": [900.0, 0], "2026-09-29T15": [100.0, 0]}
        f = fun_facts(lifetime, sessions, hours)
        assert f["avg_session_s"] == 900.0
        assert f["pace"] == pytest.approx(20.0)
        assert f["fav_toy"] == ("Domi", 0.75)
        assert f["fav_zone"] == ("Orf/A", 1.0)
        assert f["night_share"] == pytest.approx(0.9)
        assert f["busiest_weekday"] == 0
        assert f["best_session"] == (900, 1.0)
        assert f["longest_session"] == (2000.0, 2.0)
        assert f["record_pace"] == (40, 1.0)


# ============================================================ facade merge

class _Host(StatsFacade):
    def __init__(self, tracker, history):
        self.stats_tracker = tracker
        self.stats_history = history


class TestFacadeSessionList:
    def test_untimed_sessions_join_the_list_once(self, paths, tmp_path):
        tracker = StatsTracker(tmp_path / "stats.json")
        hist = StatsHistory(*paths, pid=1)
        # One session recorded by both stores...
        tracker.start_session(T0)
        hist.start_session(T0)
        tracker.sample(1.0, ["Domi"], [], 0)
        hist.sample(T0 + 1, 1.0, {"Domi": 1.0}, [], 0)
        tracker.finalize_session(T0 + 60)
        hist.finalize_session(T0 + 60)
        # ...and an older one only stats.json knows.
        tracker.recent_sessions.append({
            "started_ts": T0 - 86400, "duration_s": 100.0, "active_s": 50.0,
            "thrusts": 7, "toys": {}, "zones": {}})
        host = _Host(tracker, hist)
        rows = host.get_stats_sessions()
        assert [r["kind"] for r in rows] == ["timeline", "summary"]
        assert rows[1]["thrusts"] == 7 and rows[1]["spark"] is None
        detail = host.get_stats_session_detail(rows[1]["id"])
        assert detail["active_s"] == 50.0
        detail = host.get_stats_session_detail(rows[0]["id"])
        assert detail["analysis"]["top_toy"] == "Domi"
        assert detail["dense"]["n"] == 1

    def test_running_session_is_on_top(self, paths, tmp_path):
        tracker = StatsTracker(tmp_path / "stats.json")
        hist = StatsHistory(*paths, pid=1)
        hist.start_session(time.time() - 30)
        hist.sample(time.time(), 1.0, {"Domi": 0.4}, [], 1)
        rows = _Host(tracker, hist).get_stats_sessions()
        assert rows[0]["kind"] == "live"
        assert _Host(tracker, hist).get_stats_session_detail(
            rows[0]["id"])["kind"] == "live"
