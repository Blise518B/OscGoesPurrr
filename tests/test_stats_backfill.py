"""Tests for the one-time estimate of the hours before the hourly
history existed (`stats_backfill`), and how StatsHistory keeps it."""

import time

import pytest

from stats_backfill import estimate, parse_runs
from stats_history import StatsHistory, hour_key, month_days


def _ts(y, mo, d, h, mi=0, s=0):
    return time.mktime((y, mo, d, h, mi, s, 0, 0, -1))


def _line(t, msg, logger="ogp"):
    stamp = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(t))
    return f"{stamp},123 INFO    [MainThread] {logger}: {msg}"


T = _ts(2026, 9, 26, 22)    # a Saturday, 22:00


def _start(t, pid=1):
    return _line(t, f"OscGoesPurrr starting — version 0.10.1 (abc), pid {pid}")


def _exit(t):
    return _line(t, "process exiting (atexit) — clean shutdown path")


def _conn(t, name, motors=1):
    return _line(t, f"Device connected: {name} ({motors} motors)", "ogp.engine")


def _disc(t, name):
    return _line(t, f"Device disconnected: {name}", "ogp.engine")


class TestParseRuns:
    def test_runs_and_toy_spans(self):
        lines = [
            _start(T),
            _conn(T + 60, "Lovense Domi"),
            _conn(T + 120, "Lovense Gemini", 2),
            "\x1b[2m2026-09-26T20:00:00Z\x1b[0m INFO engine noise",
            _disc(T + 600, "Lovense Domi"),
            _exit(T + 3600),
        ]
        runs = parse_runs(lines)
        assert len(runs) == 1
        r = runs[0]
        assert r["start"] == T and r["end"] == T + 3600
        assert sorted(r["toys"]) == [("Lovense Domi", T + 60, T + 600),
                                     ("Lovense Gemini", T + 120, T + 3600)]

    def test_a_run_without_an_exit_ends_at_its_last_line(self):
        lines = [_start(T), _conn(T + 10, "Lovense Hush"),
                 _line(T + 900, "Avatar changed (id=x)"),
                 _start(T + 5000, pid=2), _exit(T + 5100)]
        runs = parse_runs(lines)
        assert [r["end"] for r in runs] == [T + 900, T + 5100]
        assert runs[0]["toys"] == [("Lovense Hush", T + 10, T + 900)]


class TestEstimate:
    def test_a_session_lands_in_its_connected_hours(self):
        # Session 22:00-01:00; toy connected 23:00-00:30.
        runs = parse_runs([_start(T), _conn(T + 3600, "Lovense Domi"),
                           _disc(T + 3600 * 2.5, "Lovense Domi"),
                           _exit(T + 3 * 3600)])
        saved = [{"started_ts": T + 5, "duration_s": 3 * 3600 - 10,
                  "active_s": 1800.0, "thrusts": 900}]
        est = estimate(runs, saved, {"sessions": 1, "active_s": 1800.0,
                                     "thrusts": 900})
        h = est["hours"]
        assert set(h) == {hour_key(T + 3600), hour_key(T + 7200)}
        assert h[hour_key(T + 3600)][0] == pytest.approx(1200.0, abs=0.2)
        assert h[hour_key(T + 7200)][0] == pytest.approx(600.0, abs=0.2)
        assert h[hour_key(T + 3600)][1] + h[hour_key(T + 7200)][1] == 900
        assert est["sessions"] == [T + 5]
        assert est["until_ts"] == T + 3 * 3600 - 5
        assert est["connected"] == [{"started_ts": T + 5, "toys": {
            "Lovense Domi": [[T + 3600, T + 3600 * 2.5]]}}]

    def test_contact_only_session_spreads_over_its_length(self):
        saved = [{"started_ts": T, "duration_s": 7200.0, "active_s": 600.0,
                  "thrusts": 0}]
        est = estimate([], saved, {"sessions": 1, "active_s": 600.0})
        assert sorted(est["hours"]) == [hour_key(T), hour_key(T + 3600)]
        assert sum(v[0] for v in est["hours"].values()) == pytest.approx(600.0)

    def test_measured_sessions_are_skipped(self):
        saved = [{"started_ts": T, "duration_s": 600.0, "active_s": 300.0,
                  "thrusts": 5}]
        est = estimate([], saved, {"sessions": 1, "active_s": 300.0},
                       skip_starts=[T + 0.5])
        assert est["hours"] == {} and est["sessions"] == []

    def test_older_lifetime_goes_to_the_latest_earlier_runs(self):
        day = 86400
        lines = []
        for k, start in enumerate((T - 3 * day, T - 2 * day, T - day)):
            lines += [_start(start, pid=k + 10),
                      _conn(start + 60, "Lovense Domi"),
                      _disc(start + 60 + (1800 if k else 100), "Lovense Domi"),
                      _exit(start + 3600)]
        lines += [_start(T, pid=99), _exit(T + 600)]
        saved = [{"started_ts": T + 3, "duration_s": 590.0, "active_s": 0.0,
                  "thrusts": 0}]
        # Two sessions' worth beyond the saved one, but only two earlier
        # runs had a toy on for long enough (the first had 100 s).
        est = estimate(parse_runs(lines), saved,
                       {"sessions": 3, "active_s": 1200.0, "thrusts": 40})
        assert est["extra_starts"] == [T - 2 * day, T - day]
        assert sum(v[0] for v in est["hours"].values()) == pytest.approx(1200.0, abs=0.5)
        assert sum(v[1] for v in est["hours"].values()) == 40

    def test_an_hour_never_holds_more_than_an_hour(self):
        saved = [{"started_ts": T, "duration_s": 3600.0, "active_s": 9000.0,
                  "thrusts": 0}]
        est = estimate([], saved, {"sessions": 1})
        assert max(v[0] for v in est["hours"].values()) <= 3600.0

    def test_nothing_to_go_on(self):
        est = estimate([], [], {})
        assert est == {"hours": {}, "sessions": [], "extra_starts": [],
                       "until_ts": 0.0, "connected": []}


class TestStoredEstimate:
    @pytest.fixture
    def paths(self, tmp_path):
        return tmp_path / "stats_sessions", tmp_path / "stats_hours.json"

    def test_estimate_is_kept_apart_and_made_once(self, paths):
        h = StatsHistory(*paths)
        assert h.needs_estimate()
        key = hour_key(T)
        h.set_estimate({"hours": {key: [600.0, 10]}, "sessions": [T],
                        "extra_starts": [], "until_ts": T + 3600})
        h.start_session(T + 7200)
        h.sample(T + 7201, 1.0, {"Domi": 1.0}, [], 0)
        h.flush()
        again = StatsHistory(*paths)
        assert not again.needs_estimate()
        assert again.hours == {hour_key(T + 7201): [1.0, 0]}
        assert again.estimate_info()["until_ts"] == T + 3600
        merged = again.hours_snapshot()
        assert merged[key] == [600.0, 10]

    def test_reset_keeps_the_estimate_from_coming_back(self, paths):
        h = StatsHistory(*paths)
        h.set_estimate({"hours": {hour_key(T): [600.0, 10]}})
        h.reset(T + 9999)
        again = StatsHistory(*paths)
        assert not again.needs_estimate()
        assert again.hours_snapshot() == {}

    def test_month_days_does_not_count_estimated_sessions_twice(self):
        hours = {hour_key(T): [600.0, 10]}
        sessions = [{"started_ts": T + 5, "active_s": 600.0, "thrusts": 10,
                     "timeline": False, "in_hours": True}]
        lt = time.localtime(T)
        days = month_days(hours, sessions, lt.tm_year, lt.tm_mon)
        assert days[lt.tm_mday] == {"active_s": 600.0, "thrusts": 10,
                                    "sessions": 1}


class TestSessionRowsGetTheirSpans:
    def test_summary_row_carries_connected_spans(self, tmp_path):
        from controllers.stats_facade import StatsFacade
        from stats_tracker import StatsTracker

        class Host(StatsFacade):
            pass

        tracker = StatsTracker(tmp_path / "stats.json")
        tracker.recent_sessions.append({
            "started_ts": T + 5, "duration_s": 7200.0, "active_s": 600.0,
            "thrusts": 3, "toys": {}, "zones": {}})
        hist = StatsHistory(tmp_path / "s", tmp_path / "h.json")
        runs = parse_runs([_start(T), _conn(T + 600, "Lovense Domi"),
                           _disc(T + 1800, "Lovense Domi"), _exit(T + 7300)])
        hist.set_estimate(estimate(runs, tracker.recent_sessions,
                                   {"sessions": 1, "active_s": 600.0}))
        host = Host()
        host.stats_tracker, host.stats_history = tracker, hist
        row = host.get_stats_sessions()[0]
        assert row["kind"] == "summary" and row["in_hours"] is True
        assert row["connected"] == {"Lovense Domi": [[T + 600, T + 1800]]}
        # Its activity is in the hours, so the calendar counts it once.
        lt = time.localtime(T)
        day = host.get_stats_month(lt.tm_year, lt.tm_mon)[lt.tm_mday]
        assert day["active_s"] == pytest.approx(600.0, abs=0.2)
        assert day["sessions"] == 1
