"""Tests for `StatsTracker` — sampling math, toy/zone accumulation,
session lifecycle (finalize / cap / no-activity), reset, persistence
round-trips, and defensive loading of corrupt files."""

import json
import os

import pytest

from stats_tracker import StatsTracker, _RECENT_SESSIONS_CAP


@pytest.fixture
def stats_path(tmp_path):
    return tmp_path / "stats.json"


@pytest.fixture
def tracker(stats_path):
    t = StatsTracker(stats_path)
    t.start_session(1000.0)
    return t


# ============================================================ boot safety

class TestBootSafety:
    """'No load path can ever crash app boot' is the module invariant —
    including exception classes outside the obvious (TypeError,
    ValueError) catches."""

    def test_infinity_in_counters_cannot_brick_boot(self, stats_path):
        # json.load parses bare Infinity, and int(inf) raises
        # OverflowError — which used to escape the sanitizers, crash
        # StatsTracker(...) inside app boot, and persist (no .bak) so
        # every subsequent launch died too.
        stats_path.write_text(
            '{"schema": 1, "lifetime": {"sessions": Infinity, '
            '"thrusts": -Infinity, "active_s": Infinity}, '
            '"recent_sessions": [{"thrusts": Infinity}]}',
            encoding="utf-8")
        t = StatsTracker(stats_path)
        assert t.lifetime["sessions"] == 0
        assert t.lifetime["thrusts"] == 0
        assert t.lifetime["active_s"] == 0.0
        assert t.recent_sessions[0]["thrusts"] == 0

    def test_idle_periodic_flush_is_a_no_op(self, stats_path):
        t = StatsTracker(stats_path)
        t.start_session(1000.0)
        t.flush(force=True)
        before = os.path.getmtime(stats_path)
        t.sample(1.0, [], [], 0)    # fully idle sample
        t.flush()                   # periodic flush: nothing changed
        assert os.path.getmtime(stats_path) == before
        t.sample(1.0, ["ToyA"], [], 0)
        t.flush()                   # dirty now: really writes
        assert json.loads(stats_path.read_text("utf-8"))[
            "lifetime"]["toys"]["ToyA"]["on_s"] == 1.0


# ============================================================ sampling math

class TestSampling:
    def test_fresh_tracker_is_all_zero(self, tracker):
        assert tracker.lifetime == {
            "sessions": 0, "active_s": 0.0, "thrusts": 0,
            "toys": {}, "zones": {},
        }
        assert tracker.session["started_ts"] == 1000.0
        assert tracker.session["active_s"] == 0.0
        assert tracker.recent_sessions == []

    def test_sample_integrates_into_both_accumulators(self, tracker):
        tracker.sample(1.0, ["ToyA"], [("Orf/Boob", "Orf")], 2)
        for acc in (tracker.lifetime, tracker.session):
            assert acc["active_s"] == pytest.approx(1.0)
            assert acc["thrusts"] == 2
            assert acc["toys"]["ToyA"]["on_s"] == pytest.approx(1.0)
            assert acc["zones"]["Orf/Boob"] == {
                "type": "Orf", "contact_s": pytest.approx(1.0),
            }

    def test_idle_sample_adds_nothing(self, tracker):
        tracker.sample(1.0, [], [], 0)
        assert tracker.lifetime["active_s"] == 0.0
        assert tracker.session["active_s"] == 0.0
        assert tracker.lifetime["toys"] == {}
        assert tracker.lifetime["zones"] == {}

    def test_zone_contact_alone_ticks_active_time(self, tracker):
        tracker.sample(1.0, [], [("Touch/Head", "Touch")], 0)
        assert tracker.lifetime["active_s"] == pytest.approx(1.0)
        assert tracker.lifetime["toys"] == {}

    def test_toy_alone_ticks_active_time(self, tracker):
        tracker.sample(1.0, ["ToyA"], [], 0)
        assert tracker.lifetime["active_s"] == pytest.approx(1.0)
        assert tracker.lifetime["zones"] == {}

    def test_accumulation_sums_across_samples(self, tracker):
        for _ in range(3):
            tracker.sample(0.5, ["ToyA", "ToyB"], [("Pen/Shaft", "Pen")], 1)
        assert tracker.lifetime["active_s"] == pytest.approx(1.5)
        assert tracker.lifetime["thrusts"] == 3
        assert tracker.lifetime["toys"]["ToyA"]["on_s"] == pytest.approx(1.5)
        assert tracker.lifetime["toys"]["ToyB"]["on_s"] == pytest.approx(1.5)
        assert tracker.lifetime["zones"]["Pen/Shaft"]["contact_s"] == \
            pytest.approx(1.5)

    def test_thrusts_count_even_with_zero_dt(self, tracker):
        tracker.sample(0.0, [], [], 3)
        assert tracker.lifetime["thrusts"] == 3
        assert tracker.lifetime["active_s"] == 0.0

    def test_negative_dt_is_ignored(self, tracker):
        tracker.sample(-5.0, ["ToyA"], [], 0)
        assert tracker.lifetime["active_s"] == 0.0
        assert tracker.lifetime["toys"] == {}

    def test_malformed_inputs_never_raise(self, tracker):
        tracker.sample("nan", None, None, "x")
        tracker.sample(float("nan"), ["ToyA"], [], 0)
        assert tracker.lifetime["active_s"] == 0.0


# ============================================================ sessions

class TestSessionLifecycle:
    def test_finalize_records_summary_and_counts_session(self, tracker):
        tracker.sample(2.0, ["ToyA"], [("Orf/Boob", "Orf")], 4)
        tracker.finalize_session(1090.0)
        assert tracker.lifetime["sessions"] == 1
        assert len(tracker.recent_sessions) == 1
        summary = tracker.recent_sessions[0]
        assert summary["started_ts"] == 1000.0
        assert summary["duration_s"] == pytest.approx(90.0)
        assert summary["active_s"] == pytest.approx(2.0)
        assert summary["thrusts"] == 4
        assert summary["toys"]["ToyA"]["on_s"] == pytest.approx(2.0)
        assert summary["zones"]["Orf/Boob"]["contact_s"] == pytest.approx(2.0)
        # Session accumulators reset (re-anchored at the finalize epoch).
        assert tracker.session["active_s"] == 0.0
        assert tracker.session["thrusts"] == 0
        assert tracker.session["toys"] == {}
        assert tracker.session["started_ts"] == 1090.0

    def test_no_activity_session_is_not_counted(self, tracker):
        tracker.sample(5.0, [], [], 0)  # idle heartbeat samples
        tracker.finalize_session(2000.0)
        assert tracker.lifetime["sessions"] == 0
        assert tracker.recent_sessions == []

    def test_thrusts_alone_count_as_activity(self, tracker):
        tracker.sample(0.0, [], [], 1)
        tracker.finalize_session(1001.0)
        assert tracker.lifetime["sessions"] == 1
        assert len(tracker.recent_sessions) == 1

    def test_recent_sessions_newest_first_capped_at_20(self, tracker):
        for i in range(_RECENT_SESSIONS_CAP + 5):
            tracker.start_session(1000.0 + i)
            tracker.sample(1.0, ["ToyA"], [], 0)
            tracker.finalize_session(1000.0 + i + 0.5)
        assert tracker.lifetime["sessions"] == _RECENT_SESSIONS_CAP + 5
        assert len(tracker.recent_sessions) == _RECENT_SESSIONS_CAP
        # Newest (last started) first.
        assert tracker.recent_sessions[0]["started_ts"] == pytest.approx(
            1000.0 + _RECENT_SESSIONS_CAP + 4)
        assert tracker.recent_sessions[-1]["started_ts"] == pytest.approx(
            1000.0 + 5)


# ============================================================ reset

class TestReset:
    def test_reset_zeroes_everything(self, tracker, stats_path):
        tracker.sample(3.0, ["ToyA"], [("Orf/Boob", "Orf")], 2)
        tracker.finalize_session(1100.0)
        tracker.start_session(1100.0)
        tracker.sample(1.0, ["ToyA"], [], 1)
        tracker.reset_lifetime()
        assert tracker.lifetime == {
            "sessions": 0, "active_s": 0.0, "thrusts": 0,
            "toys": {}, "zones": {},
        }
        assert tracker.recent_sessions == []
        # Live session accumulators are wiped too — "reset ALL" must not
        # leave a half-populated this-session view behind.
        assert tracker.session["active_s"] == 0.0
        assert tracker.session["thrusts"] == 0
        # And the zeroed state is flushed to disk.
        on_disk = json.loads(stats_path.read_text(encoding="utf-8"))
        assert on_disk["lifetime"]["sessions"] == 0
        assert on_disk["recent_sessions"] == []


# ============================================================ persistence

class TestPersistence:
    def test_flush_load_round_trip(self, stats_path):
        t1 = StatsTracker(stats_path)
        t1.start_session(1000.0)
        t1.sample(2.5, ["ToyA"], [("Pen/Shaft", "Pen")], 3)
        t1.finalize_session(1060.0)

        t2 = StatsTracker(stats_path)
        assert t2.lifetime["sessions"] == 1
        assert t2.lifetime["active_s"] == pytest.approx(2.5)
        assert t2.lifetime["thrusts"] == 3
        assert t2.lifetime["toys"]["ToyA"]["on_s"] == pytest.approx(2.5)
        assert t2.lifetime["zones"]["Pen/Shaft"] == {
            "type": "Pen", "contact_s": pytest.approx(2.5),
        }
        assert len(t2.recent_sessions) == 1
        assert t2.recent_sessions[0]["duration_s"] == pytest.approx(60.0)
        # The live session is never persisted — a new tracker starts fresh.
        assert t2.session["active_s"] == 0.0

    def test_file_has_schema_marker(self, stats_path, tracker):
        # force: a clean tracker's periodic flush is deliberately a no-op.
        tracker.flush(force=True)
        on_disk = json.loads(stats_path.read_text(encoding="utf-8"))
        assert on_disk["schema"] == 1
        assert set(on_disk.keys()) == {"schema", "lifetime",
                                       "recent_sessions"}

    def test_missing_file_starts_fresh_without_creating_it(self, stats_path):
        t = StatsTracker(stats_path)
        assert t.lifetime["sessions"] == 0
        assert not os.path.exists(stats_path)

    def test_corrupt_json_backed_up_and_defaults_used(self, stats_path):
        stats_path.write_text("{not json at all", encoding="utf-8")
        t = StatsTracker(stats_path)
        assert t.lifetime["sessions"] == 0
        assert t.recent_sessions == []
        backup = stats_path.parent / (stats_path.name + ".bak")
        assert backup.exists()
        assert backup.read_text(encoding="utf-8") == "{not json at all"

    def test_wrong_shape_json_backed_up_and_defaults_used(self, stats_path):
        stats_path.write_text(json.dumps([1, 2, 3]), encoding="utf-8")
        t = StatsTracker(stats_path)
        assert t.lifetime["sessions"] == 0
        assert (stats_path.parent / (stats_path.name + ".bak")).exists()

    def test_partially_malformed_fields_degrade_per_field(self, stats_path):
        stats_path.write_text(json.dumps({
            "schema": 1,
            "lifetime": {
                "sessions": "many",           # bad -> 0
                "active_s": 12.5,             # good
                "thrusts": -3,                # negative -> 0
                "toys": {"ToyA": {"on_s": "x"}, "ToyB": {"on_s": 4.0}},
                "zones": "nope",              # bad -> {}
            },
            "recent_sessions": [{"started_ts": 5.0, "thrusts": 1},
                                "garbage-entry"],
        }), encoding="utf-8")
        t = StatsTracker(stats_path)
        assert t.lifetime["sessions"] == 0
        assert t.lifetime["active_s"] == pytest.approx(12.5)
        assert t.lifetime["thrusts"] == 0
        assert t.lifetime["toys"]["ToyA"]["on_s"] == 0.0
        assert t.lifetime["toys"]["ToyB"]["on_s"] == pytest.approx(4.0)
        assert t.lifetime["zones"] == {}
        assert len(t.recent_sessions) == 1
        assert t.recent_sessions[0]["started_ts"] == pytest.approx(5.0)


# ============================================================ snapshot

class TestSnapshot:
    def test_snapshot_shape(self, tracker):
        snap = tracker.snapshot()
        assert set(snap.keys()) == {"lifetime", "session",
                                    "recent_sessions"}

    def test_snapshot_is_a_deep_copy(self, tracker):
        tracker.sample(1.0, ["ToyA"], [("Orf/Boob", "Orf")], 1)
        snap = tracker.snapshot()
        snap["lifetime"]["active_s"] = 999.0
        snap["lifetime"]["toys"]["ToyA"]["on_s"] = 999.0
        snap["recent_sessions"].append({"bogus": True})
        assert tracker.lifetime["active_s"] == pytest.approx(1.0)
        assert tracker.lifetime["toys"]["ToyA"]["on_s"] == pytest.approx(1.0)
        assert tracker.recent_sessions == []
