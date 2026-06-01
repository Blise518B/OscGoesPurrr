"""Tests for the session_logger engine.

Most tests use the real file system (pytest's tmp_path fixture) plus
the real worker thread — these are integration tests against the
engine's public API. The pure-function `ogb_diff` is tested
separately without any I/O.

We `stop()` after every test to drain the worker; reading the file
before stop() risks seeing only what's been flushed so far."""

import json
import os
import time

import pytest

import session_logger as sl
from session_logger import (
    OGB_SNAPSHOT_INTERVAL_S,
    SessionLogger,
    ogb_diff,
)


# ----------------------------------------------------------
# helpers
# ----------------------------------------------------------

def _read_lines(path):
    with open(path, "r", encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def _session_file(dir_path, session_id):
    return dir_path / (session_id + ".jsonl")


def _events_of(lines, event_type):
    return [l for l in lines if l.get("type") == event_type]


# ----------------------------------------------------------
# ogb_diff (pure)
# ----------------------------------------------------------

class TestOgbDiff:

    def test_first_call_emits_full_snapshot(self):
        diff = ogb_diff({}, {"OGB/Orf/Boob/TouchSelf": 0.5, "x": True})
        assert diff == {"OGB/Orf/Boob/TouchSelf": 0.5, "x": True}

    def test_no_change_returns_empty(self):
        prev = {"a": 0.5, "b": True, "c": "x"}
        assert ogb_diff(prev, dict(prev)) == {}

    def test_only_changed_keys(self):
        prev = {"a": 0.5, "b": True, "c": "x"}
        curr = {"a": 0.5, "b": False, "c": "y"}
        assert ogb_diff(prev, curr) == {"b": False, "c": "y"}

    def test_new_keys_emitted_in_full(self):
        prev = {"a": 0.5}
        curr = {"a": 0.5, "new_key": 0.9}
        assert ogb_diff(prev, curr) == {"new_key": 0.9}

    def test_disappeared_keys_silently_ignored(self):
        # We have no "deleted" event in the schema; gone-from-curr keys
        # just don't appear in the diff. (See docs/SESSION_LOGGING.md.)
        prev = {"a": 0.5, "b": True}
        curr = {"a": 0.5}
        assert ogb_diff(prev, curr) == {}

    def test_float_tolerance_suppresses_noise(self):
        prev = {"a": 0.5}
        curr = {"a": 0.5 + 1e-6}
        assert ogb_diff(prev, curr) == {}

    def test_float_threshold_above_tolerance(self):
        prev = {"a": 0.5}
        curr = {"a": 0.5005}  # > 1e-4
        assert ogb_diff(prev, curr) == {"a": 0.5005}

    def test_bool_change_detected(self):
        # bool == int in Python; verify we don't collapse True/1.
        prev = {"a": True}
        curr = {"a": False}
        assert ogb_diff(prev, curr) == {"a": False}

    def test_mixed_int_float_close_enough(self):
        # Float 1.0 vs int 1 — no meaningful difference.
        prev = {"a": 1.0}
        curr = {"a": 1}
        assert ogb_diff(prev, curr) == {}


# ----------------------------------------------------------
# Lifecycle + basic file shape
# ----------------------------------------------------------

class TestLifecycle:

    def test_start_then_stop_writes_header_and_footer(self, tmp_path):
        logger = SessionLogger(tmp_path)
        sid = logger.start({"profile": "Default", "router_hz": 90})
        assert logger.is_running
        assert sid.startswith("session_")
        logger.stop()
        assert not logger.is_running

        lines = _read_lines(_session_file(tmp_path, sid))
        assert len(lines) >= 2
        assert lines[0]["type"] == "header"
        assert lines[0]["schema"] == 1
        assert lines[0]["profile"] == "Default"
        assert lines[0]["router_hz"] == 90
        assert "started_at" in lines[0]
        assert "started_at_unix" in lines[0]
        assert lines[-1]["type"] == "footer"
        assert lines[-1]["event_count"] >= 1  # at least the header
        assert "ended_at" in lines[-1]
        assert "duration_s" in lines[-1]

    def test_start_when_running_raises(self, tmp_path):
        logger = SessionLogger(tmp_path)
        logger.start({})
        try:
            with pytest.raises(RuntimeError):
                logger.start({})
        finally:
            logger.stop()

    def test_stop_is_idempotent(self, tmp_path):
        logger = SessionLogger(tmp_path)
        logger.start({})
        logger.stop()
        logger.stop()  # second stop is a no-op, must not raise

    def test_log_before_start_silently_ignored(self, tmp_path):
        logger = SessionLogger(tmp_path)
        logger.log_motor(0, "d", 0, 0.1, 0, 0.1, 0, 0.1, 0.1)
        logger.log_ogb(0, {"x": 1})
        logger.log_bhaptics(0, {"VestFront": [1, 2, 3]})
        # No file should exist.
        assert list(tmp_path.glob("session_*.jsonl")) == []

    def test_log_after_stop_silently_ignored(self, tmp_path):
        logger = SessionLogger(tmp_path)
        sid = logger.start({})
        logger.stop()
        # These should be no-ops.
        logger.log_motor(99, "d", 0, 0.1, 0, 0.1, 0, 0.1, 0.1)
        logger.log_ogb(99, {"x": 1})
        # No new motor / ogb events should appear in the file.
        lines = _read_lines(_session_file(tmp_path, sid))
        assert _events_of(lines, "motor") == []
        assert _events_of(lines, "ogb") == []

    def test_multiple_sessions_one_logger(self, tmp_path):
        logger = SessionLogger(tmp_path)
        sid1 = logger.start({"profile": "p1"})
        logger.log_motor(0, "d", 0, 0.1, 0, 0.1, 0, 0.1, 0.1)
        logger.stop()

        sid2 = logger.start({"profile": "p2"})
        logger.log_motor(0, "d", 0, 0.2, 0, 0.2, 0, 0.2, 0.2)
        logger.stop()

        assert sid1 != sid2
        files = sorted(tmp_path.glob("session_*.jsonl"))
        assert len(files) == 2

    def test_same_second_restart_uses_numeric_suffix(self, tmp_path):
        # Manually create a file matching today's-second prefix so the
        # next start() has to bump the suffix.
        from datetime import datetime
        stem = "session_" + datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        (tmp_path / (stem + ".jsonl")).write_text("preexisting\n")
        logger = SessionLogger(tmp_path)
        sid = logger.start({})
        logger.stop()
        # Sid should have a numeric suffix appended.
        assert sid.startswith(stem + "_")


# ----------------------------------------------------------
# Motor events
# ----------------------------------------------------------

class TestMotorEvents:

    def test_motor_event_shape(self, tmp_path):
        logger = SessionLogger(tmp_path)
        sid = logger.start({})
        logger.log_motor(123.456, "Lovense Hush", 0,
                         0.71234, 0.0, 0.71234, 0.0, 0.71234, 0.65432)
        logger.stop()
        lines = _read_lines(_session_file(tmp_path, sid))
        motors = _events_of(lines, "motor")
        assert len(motors) == 1
        e = motors[0]
        assert e["device"] == "Lovense Hush"
        assert e["motor"] == 0
        assert e["t_ms"] == pytest.approx(123.5, abs=0.1)
        # Four-decimal rounding.
        assert e["d_raw"] == pytest.approx(0.7123)
        assert e["out"]   == pytest.approx(0.6543)

    def test_motor_int_motor_index_coerced(self, tmp_path):
        logger = SessionLogger(tmp_path)
        sid = logger.start({})
        logger.log_motor(0, "d", 2, 0, 0, 0, 0, 0, 0)  # int motor
        logger.stop()
        motors = _events_of(_read_lines(_session_file(tmp_path, sid)), "motor")
        assert motors[0]["motor"] == 2


# ----------------------------------------------------------
# OGB events: change-diff + periodic full snapshot
# ----------------------------------------------------------

class TestOgbLogging:

    def test_first_ogb_call_writes_full_snapshot_via_periodic_path(self, tmp_path):
        # The "periodic full snapshot" interval triggers on the first
        # call because _ogb_last_full_snapshot_t_ms is initialised to
        # very negative. So the very first ogb event is `ogb_snapshot`,
        # not `ogb`.
        logger = SessionLogger(tmp_path)
        sid = logger.start({})
        logger.log_ogb(100.0, {"OGB/Orf/Boob/TouchSelf": 0.5,
                                "OGB/Orf/Boob/TouchSelfClose": True})
        logger.stop()
        lines = _read_lines(_session_file(tmp_path, sid))
        snapshots = _events_of(lines, "ogb_snapshot")
        assert len(snapshots) == 1
        assert snapshots[0]["params"]["OGB/Orf/Boob/TouchSelf"] == 0.5
        assert snapshots[0]["params"]["OGB/Orf/Boob/TouchSelfClose"] is True

    def test_subsequent_ogb_calls_only_diff(self, tmp_path):
        logger = SessionLogger(tmp_path)
        sid = logger.start({})
        # First call inside interval — periodic full snapshot.
        logger.log_ogb(100.0, {"a": 0.5, "b": True})
        # Second call, same values — no diff, no event.
        logger.log_ogb(110.0, {"a": 0.5, "b": True})
        # Third call, one value changed — diff event with just `a`.
        logger.log_ogb(120.0, {"a": 0.7, "b": True})
        logger.stop()
        lines = _read_lines(_session_file(tmp_path, sid))
        snapshots = _events_of(lines, "ogb_snapshot")
        diffs = _events_of(lines, "ogb")
        assert len(snapshots) == 1
        assert len(diffs) == 1
        assert diffs[0]["params"] == {"a": 0.7}
        assert diffs[0]["t_ms"] == pytest.approx(120.0, abs=0.1)

    def test_periodic_full_snapshot_fires(self, tmp_path):
        logger = SessionLogger(tmp_path)
        sid = logger.start({})
        # t=0 -> periodic full snapshot (first call).
        logger.log_ogb(0.0, {"a": 0.5})
        # t=10s -> still within first 30s window, would be diff but
        # value unchanged, no event.
        logger.log_ogb(10000.0, {"a": 0.5})
        # t=31s -> past the 30s interval, periodic snapshot fires
        # even though value hasn't changed.
        logger.log_ogb((OGB_SNAPSHOT_INTERVAL_S + 1.0) * 1000.0, {"a": 0.5})
        logger.stop()
        lines = _read_lines(_session_file(tmp_path, sid))
        snapshots = _events_of(lines, "ogb_snapshot")
        assert len(snapshots) == 2
        # First snapshot at t=0, second at t=31000.
        assert snapshots[0]["t_ms"] == 0.0
        assert snapshots[1]["t_ms"] == pytest.approx(31000.0, abs=1)

    def test_empty_snapshot_is_noop(self, tmp_path):
        logger = SessionLogger(tmp_path)
        sid = logger.start({})
        logger.log_ogb(0, {})
        logger.stop()
        lines = _read_lines(_session_file(tmp_path, sid))
        assert _events_of(lines, "ogb") == []
        assert _events_of(lines, "ogb_snapshot") == []


# ----------------------------------------------------------
# bHaptics events: per-position, non-zero only
# ----------------------------------------------------------

class TestBHapticsLogging:

    def test_one_event_per_position(self, tmp_path):
        logger = SessionLogger(tmp_path)
        sid = logger.start({})
        logger.log_bhaptics(50.0, {
            "VestFront": [0, 0, 80, 0, 0],
            "VestBack":  [10, 0, 0, 0, 0],
        })
        logger.stop()
        events = _events_of(_read_lines(_session_file(tmp_path, sid)), "bhaptics")
        assert len(events) == 2
        positions = {e["position"]: e["dots"] for e in events}
        assert positions["VestFront"] == {"2": 80}
        assert positions["VestBack"]  == {"0": 10}

    def test_all_zero_position_skipped(self, tmp_path):
        logger = SessionLogger(tmp_path)
        sid = logger.start({})
        logger.log_bhaptics(50.0, {
            "VestFront": [0, 0, 0, 0],
            "VestBack":  [0, 0, 0, 0],
        })
        logger.stop()
        events = _events_of(_read_lines(_session_file(tmp_path, sid)), "bhaptics")
        assert events == []

    def test_empty_dict_is_noop(self, tmp_path):
        logger = SessionLogger(tmp_path)
        sid = logger.start({})
        logger.log_bhaptics(0, {})
        logger.stop()
        events = _events_of(_read_lines(_session_file(tmp_path, sid)), "bhaptics")
        assert events == []

    def test_non_int_dot_values_silently_dropped(self, tmp_path):
        logger = SessionLogger(tmp_path)
        sid = logger.start({})
        logger.log_bhaptics(0, {"VestFront": [None, "garbage", 50, 0]})
        logger.stop()
        events = _events_of(_read_lines(_session_file(tmp_path, sid)), "bhaptics")
        assert len(events) == 1
        # Only the int 50 at index 2 survives.
        assert events[0]["dots"] == {"2": 50}


# ----------------------------------------------------------
# current_session / introspection
# ----------------------------------------------------------

class TestCurrentSession:

    def test_none_when_idle(self, tmp_path):
        logger = SessionLogger(tmp_path)
        assert logger.current_session is None

    def test_populated_while_running(self, tmp_path):
        logger = SessionLogger(tmp_path)
        sid = logger.start({})
        cs = logger.current_session
        assert cs is not None
        assert cs["id"] == sid
        assert cs["duration_s"] >= 0.0
        assert cs["event_count"] >= 0
        assert cs["dropped_count"] == 0
        assert cs["file_size_bytes"] >= 0
        assert cs["path"].endswith(sid + ".jsonl")
        logger.stop()

    def test_none_after_stop(self, tmp_path):
        logger = SessionLogger(tmp_path)
        logger.start({})
        logger.stop()
        assert logger.current_session is None


# ----------------------------------------------------------
# Static library: list / delete / prune
# ----------------------------------------------------------

class TestStaticLibrary:

    def test_list_sessions_empty_dir(self, tmp_path):
        assert SessionLogger.list_sessions(tmp_path) == []

    def test_list_sessions_missing_dir(self, tmp_path):
        # Path under tmp_path that doesn't exist.
        assert SessionLogger.list_sessions(tmp_path / "nope") == []

    def test_list_sessions_returns_metadata(self, tmp_path):
        logger = SessionLogger(tmp_path)
        sid = logger.start({"profile": "Default", "router_hz": 90})
        logger.log_motor(0, "d", 0, 0.1, 0, 0.1, 0, 0.1, 0.1)
        logger.stop()

        sessions = SessionLogger.list_sessions(tmp_path)
        assert len(sessions) == 1
        s = sessions[0]
        assert s["id"] == sid
        assert s["size_bytes"] > 0
        assert s["mtime_unix"] > 0
        # Header-derived fields:
        assert s.get("profile") == "Default"
        assert s.get("router_hz") == 90
        assert "started_at" in s
        # Footer-derived fields:
        assert "ended_at" in s
        assert s.get("event_count", 0) >= 1
        assert "duration_s" in s

    def test_list_sessions_newest_first(self, tmp_path):
        # Make 3 files with staggered mtimes.
        names = []
        for i in range(3):
            f = tmp_path / f"session_x_{i}.jsonl"
            f.write_text('{"type": "header"}\n{"type": "footer"}\n')
            os.utime(f, (1000 + i * 100, 1000 + i * 100))
            names.append(f.stem)
        ordered = [s["id"] for s in SessionLogger.list_sessions(tmp_path)]
        assert ordered == list(reversed(names))

    def test_list_ignores_non_session_files(self, tmp_path):
        # Stray files in the dir shouldn't be picked up.
        (tmp_path / "notes.txt").write_text("...")
        (tmp_path / "other.json").write_text("{}")
        # Real session file.
        (tmp_path / "session_x.jsonl").write_text('{"type": "header"}\n')
        ids = [s["id"] for s in SessionLogger.list_sessions(tmp_path)]
        assert ids == ["session_x"]

    def test_list_survives_partial_files(self, tmp_path):
        # Corrupted JSON in the first line shouldn't crash listing.
        (tmp_path / "session_bad.jsonl").write_text("not json at all\n")
        sessions = SessionLogger.list_sessions(tmp_path)
        assert len(sessions) == 1
        assert sessions[0]["id"] == "session_bad"
        # Header/footer fields are absent, but the file is still listed
        # with size + mtime.
        assert sessions[0]["size_bytes"] > 0

    def test_delete_session_removes_file(self, tmp_path):
        f = tmp_path / "session_abc.jsonl"
        f.write_text("{}\n")
        assert SessionLogger.delete_session(tmp_path, "session_abc") is True
        assert not f.exists()

    def test_delete_session_missing_returns_false(self, tmp_path):
        assert SessionLogger.delete_session(tmp_path, "session_nope") is False

    def test_delete_all_sessions(self, tmp_path):
        for i in range(3):
            (tmp_path / f"session_x_{i}.jsonl").write_text("{}\n")
        # Stray non-session file is NOT deleted.
        (tmp_path / "notes.txt").write_text("keep me")
        n = SessionLogger.delete_all_sessions(tmp_path)
        assert n == 3
        assert list(tmp_path.glob("session_*.jsonl")) == []
        assert (tmp_path / "notes.txt").exists()

    def test_prune_keeps_newest_n(self, tmp_path):
        for i in range(5):
            f = tmp_path / f"session_x_{i}.jsonl"
            f.write_text("{}\n")
            os.utime(f, (1000 + i * 100, 1000 + i * 100))
        removed = SessionLogger.prune(tmp_path, keep_n=3)
        assert removed == 2
        remaining = sorted(p.stem for p in tmp_path.glob("session_*.jsonl"))
        assert remaining == ["session_x_2", "session_x_3", "session_x_4"]

    def test_prune_noop_when_under_limit(self, tmp_path):
        for i in range(2):
            (tmp_path / f"session_x_{i}.jsonl").write_text("{}\n")
        assert SessionLogger.prune(tmp_path, keep_n=5) == 0
        assert len(list(tmp_path.glob("session_*.jsonl"))) == 2

    def test_prune_keep_zero_deletes_all(self, tmp_path):
        for i in range(3):
            (tmp_path / f"session_x_{i}.jsonl").write_text("{}\n")
        assert SessionLogger.prune(tmp_path, keep_n=0) == 3
        assert list(tmp_path.glob("session_*.jsonl")) == []

    def test_prune_negative_is_noop(self, tmp_path):
        (tmp_path / "session_x.jsonl").write_text("{}\n")
        assert SessionLogger.prune(tmp_path, keep_n=-1) == 0


# ----------------------------------------------------------
# Back-pressure: dropped events emit a marker
# ----------------------------------------------------------

class TestBackPressure:

    def test_dropped_event_recorded_when_queue_overflows(self, tmp_path, monkeypatch):
        # Slam the queue past the high-water mark by lowering it.
        monkeypatch.setattr(sl, "QUEUE_HIGH_WATER", 5)
        monkeypatch.setattr(sl, "DROP_BATCH_SIZE", 3)
        # Slow the worker so the queue can actually build up before
        # the drain catches up.
        monkeypatch.setattr(sl, "FLUSH_INTERVAL_S", 0.01)

        logger = SessionLogger(tmp_path)
        sid = logger.start({})
        # Pump way more motor events than the lowered high-water
        # mark, faster than the worker can drain.
        for i in range(200):
            logger.log_motor(i, "d", 0, 0.1, 0, 0.1, 0, 0.1, 0.1)
        logger.stop()
        lines = _read_lines(_session_file(tmp_path, sid))
        # We expect at least one `dropped` marker, and the footer's
        # dropped_count to be > 0.
        dropped = _events_of(lines, "dropped")
        assert len(dropped) >= 1
        assert all(d["count"] == 3 for d in dropped)
        footer = _events_of(lines, "footer")[0]
        assert footer["dropped_count"] >= 3
