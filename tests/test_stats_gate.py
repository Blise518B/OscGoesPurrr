"""Tests for the statistics' activity gate (`stats_gate`) and the one-time
clean-up of what was recorded before it."""

import json

import pytest

from stats_gate import (
    ActivityGate, CONTACT_GRACE_S, CONTACT_WINDOW_S, GATE_VERSION, LEAD_S,
    MIN_CONTACT_S, MIN_THRUSTS, SCENE_END_S, STREAK_GAP_S,
)
from stats_history import BUCKET_S, StatsHistory, hour_key, regate
from stats_tracker import StatsTracker


T0 = 1_790_000_000.0


def _feed(gate, samples):
    """samples: (t, toy_on, contact, thrusts). Returns the released times."""
    out = []
    for t, toy, contact, thrusts in samples:
        out += gate.push(t, t, toy, contact, thrusts)
    return out


# ============================================================ the gate

class TestGate:
    def test_stray_contacts_and_lone_strokes_never_count(self):
        g = ActivityGate()
        released = _feed(g, [
            (T0, False, True, 0),
            (T0 + 1, False, True, 1),
            (T0 + 40, False, False, 2),
            (T0 + 200, False, True, 1),
            (T0 + 600, False, False, 0),
        ])
        assert released == [] and not g.in_scene

    def test_a_running_toy_counts_at_once(self):
        g = ActivityGate()
        assert g.push(T0, "a", True, False, 0) == ["a"]
        assert g.in_scene

    def test_twenty_thrusts_confirm_and_bring_their_lead_in(self):
        g = ActivityGate()
        samples = [(T0 + k, False, True, 0) for k in range(0, 60, 5)]     # contact, no strokes
        samples += [(T0 + 60 + 2 * k, False, True, 1) for k in range(MIN_THRUSTS)]
        released = _feed(g, samples)
        # Released at the 20th thrust — with the touching that led up to
        # it (it is inside the contact window), not just the streak.
        assert released[0] == T0
        assert released[-1] == T0 + 60 + 2 * (MIN_THRUSTS - 1)
        assert g.in_scene

    def test_strokes_long_after_a_touch_bring_only_their_own_lead_in(self):
        g = ActivityGate()
        g.push(T0, "old touch", False, 1.0, 0)
        start = T0 + CONTACT_WINDOW_S + LEAD_S + 60
        released = _feed(g, [(start + k, False, True, 1) for k in range(MIN_THRUSTS)])
        assert released[0] == start and "old touch" not in released

    def test_a_long_pause_restarts_the_streak(self):
        g = ActivityGate()
        samples = [(T0 + k, False, True, 1) for k in range(MIN_THRUSTS - 1)]
        gap = T0 + MIN_THRUSTS - 1 + STREAK_GAP_S + 5
        samples += [(gap + k, False, True, 1) for k in range(MIN_THRUSTS - 1)]
        assert _feed(g, samples) == []
        assert g.push(gap + 30, "x", False, True, 1) == []         # 19 + 1 after another gap
        g2 = ActivityGate()
        assert _feed(g2, [(T0 + k, False, True, 1) for k in range(MIN_THRUSTS)])

    def test_several_strokes_in_one_sample_add_up(self):
        g = ActivityGate()
        assert _feed(g, [(T0, False, True, 12), (T0 + 1, False, True, 8)]) == [T0, T0 + 1]

    def test_a_scene_keeps_counting_until_it_goes_quiet(self):
        g = ActivityGate()
        _feed(g, [(T0 + k, False, True, 1) for k in range(MIN_THRUSTS)])
        # Slower strokes and contact after the streak still count.
        assert g.push(T0 + 60, "slow", False, True, 0) == ["slow"]
        assert g.push(T0 + 60 + SCENE_END_S - 1, "late", False, True, 1) == ["late"]
        # Then a long quiet ends the scene...
        g.push(T0 + 60 + 2 * SCENE_END_S + 10, "q", False, False, 0)
        assert not g.in_scene
        # ...and a stray contact after it is held back again.
        assert g.push(T0 + 1000, "stray", False, True, 1) == []

    def test_lots_of_touching_counts_without_any_thrust(self):
        g = ActivityGate()
        # 3 s touches every 6 s: a minute of contact after ~2 minutes.
        samples = [(T0 + k, False, (k % 6) < 3, 0) for k in range(150)]
        released = _feed(g, samples)
        assert released and released[0] == T0
        assert g.in_scene

    def test_long_contact_counts_once_it_reaches_a_minute(self):
        g = ActivityGate()
        released = _feed(g, [(T0 + k, False, True, 0) for k in range(int(MIN_CONTACT_S))])
        assert len(released) == int(MIN_CONTACT_S)

    def test_a_few_touches_spread_out_never_count(self):
        g = ActivityGate()
        # 1 s every 10 s: 18 s per three minutes, never a minute.
        assert _feed(g, [(T0 + k, False, k % 10 == 0, 0) for k in range(5000)]) == []

    def test_held_back_contact_stays_bounded(self):
        g = ActivityGate()
        for k in range(10_000):
            g.push(T0 + k, k, False, k % 10 == 0, 0)
        assert len(g._held) <= (CONTACT_WINDOW_S + LEAD_S) / 10 + 2

    def test_strokes_with_nothing_touching_never_count(self):
        g = ActivityGate()
        assert _feed(g, [(T0 + k, False, False, 3) for k in range(600)]) == []
        assert not g.in_scene

    def test_strokes_just_after_contact_still_count(self):
        g = ActivityGate()
        g.push(T0, "touch", False, True, 0)
        released = _feed(g, [(T0 + 1, False, False, 12), (T0 + 2, False, False, 8)])
        assert released == ["touch", T0 + 1, T0 + 2]

    def test_a_running_toy_counts_strokes_without_contact(self):
        g = ActivityGate()
        assert g.push(T0, "toy", True, False, 4) == ["toy"]

    def test_contactless_strokes_do_not_keep_a_scene_going(self):
        g = ActivityGate()
        _feed(g, [(T0 + k, False, True, 1) for k in range(MIN_THRUSTS)])
        # (Past the couple of seconds' grace after the last contact.)
        for k in range(int(CONTACT_GRACE_S) + 2, int(SCENE_END_S) + 60, 5):
            assert g.push(T0 + MIN_THRUSTS + k, k, False, False, 1) == []
        assert not g.in_scene

    def test_a_gap_with_no_samples_ends_the_scene(self):
        # The clean-up only sees buckets with something in them, so a
        # quiet stretch arrives as a jump in time, not as quiet samples.
        g = ActivityGate()
        _feed(g, [(T0 + k, False, True, 1) for k in range(MIN_THRUSTS)])
        assert g.push(T0 + MIN_THRUSTS + SCENE_END_S + 60, "blip", False, True, 1) == []
        assert not g.in_scene

    def test_contact_before_a_toy_comes_on_joins_the_scene(self):
        g = ActivityGate()
        g.push(T0, "touch", False, True, 0)
        assert g.push(T0 + 5, "toy", True, True, 0) == ["touch", "toy"]


# ============================================================ after the fact

def _timeline(spec):
    buckets = {i: {"a": float(a), "t": t, "y": {k: [float(v), float(v) / 2] for k, v in toys.items()},
                   "z": {k: float(v) for k, v in zones.items()}}
               for i, (a, t, toys, zones) in spec.items()}
    return {"id": "20260101-000000", "started_ts": T0, "ended_ts": T0 + 7200,
            "bucket_s": BUCKET_S, "recovered": False, "gated": False, "buckets": buckets}


class TestRegate:
    def test_blips_go_scenes_and_toys_stay(self):
        spec = {
            0: (5, 1, {}, {"Orf/A": 5}),                 # a blip
            30: (0, 2, {}, {}),                          # lone strokes
            100: (10, 0, {"Domi": 10}, {}),              # a toy running
        }
        for i in range(200, 204):                        # a 24-stroke streak
            spec[i] = (10, 6, {}, {"Pen/B": 10})
        spec[400] = (5, 2, {}, {"Pen/B": 5})            # a blip long after
        spec[401] = (0, 9, {}, {})                       # strokes, nothing touching
        tl = _timeline(spec)
        dropped = regate(tl)
        assert sorted(tl["buckets"]) == [100, 200, 201, 202, 203]
        assert dropped["thrusts"] == 14 and dropped["active_s"] == 10
        assert dropped["zones"] == {"Orf/A": 5.0, "Pen/B": 5.0}
        assert sum(t for _a, t in dropped["hours"].values()) == 14


class TestCleanup:
    @pytest.fixture
    def stores(self, tmp_path):
        tracker = StatsTracker(tmp_path / "stats.json")
        hist = StatsHistory(tmp_path / "stats_sessions", tmp_path / "stats_hours.json")
        return tracker, hist, tmp_path

    def _old_timeline(self, hist, tracker, spec, start):
        """A finished timeline as the first test builds wrote it, with its
        totals in the tracker and the hours."""
        tl = _timeline(spec)
        tl["started_ts"] = start
        tl["id"] = "20260101-%06d" % (int(start) % 1_000_000)
        hist.sessions_dir.mkdir(parents=True, exist_ok=True)
        from stats_history import _timeline_payload, summarize
        (hist.sessions_dir / f"{tl['id']}.json").write_text(
            json.dumps(_timeline_payload(tl)), encoding="utf-8")
        entry = summarize(tl)
        entry["gated"] = 0
        hist.index.append(entry)
        for i, b in tl["buckets"].items():
            h = hist.hours.setdefault(hour_key(start + i * BUCKET_S + 5), [0.0, 0])
            h[0] += b["a"]
            h[1] += b["t"]
        tracker.lifetime["sessions"] += 1
        tracker.lifetime["active_s"] += entry["active_s"]
        tracker.lifetime["thrusts"] += entry["thrusts"]
        tracker.recent_sessions.insert(0, {
            "started_ts": start, "duration_s": 7200.0,
            "active_s": entry["active_s"], "thrusts": entry["thrusts"],
            "toys": {k: {"on_s": v} for k, v in entry["toys"].items()},
            "zones": {k: {"type": k.split("/")[0], "contact_s": v}
                      for k, v in entry["zones"].items()}})
        return tl["id"]

    def test_cleanup_shrinks_timelines_drops_noise_and_backs_up(self, stores, monkeypatch):
        from controllers import stats_facade as sf
        tracker, hist, tmp = stores
        monkeypatch.setattr(sf, "STATS_FILE", tmp / "stats.json")
        monkeypatch.setattr(sf, "STATS_HOURS_FILE", tmp / "stats_hours.json")
        tracker.flush(force=True)
        # A real session with some noise in it...
        real = {0: (3, 1, {}, {"Orf/A": 3}), 50: (10, 0, {"Domi": 10}, {})}
        keep_id = self._old_timeline(hist, tracker, real, T0)
        # ...one that was nothing but noise...
        gone_id = self._old_timeline(hist, tracker, {0: (2, 1, {}, {"Orf/A": 2})}, T0 + 86400)
        # ...and two totals-only sessions: a blip and a real one.
        tracker.recent_sessions += [
            {"started_ts": T0 - 86400, "duration_s": 600.0, "active_s": 1.0,
             "thrusts": 0, "toys": {}, "zones": {}},
            {"started_ts": T0 - 2 * 86400, "duration_s": 600.0, "active_s": 300.0,
             "thrusts": 150, "toys": {}, "zones": {}},
        ]
        tracker.lifetime["sessions"] += 2
        tracker.lifetime["active_s"] += 301.0
        tracker.lifetime["thrusts"] += 150

        class Host(sf.StatsFacade):
            pass

        host = Host()
        host.stats_tracker, host.stats_history = tracker, hist
        host._stats_clean_history()

        assert [e["id"] for e in hist.index] == [keep_id]
        assert hist.index[0]["gated"] == GATE_VERSION
        assert not (hist.sessions_dir / f"{gone_id}.json").exists()
        starts = [e["started_ts"] for e in tracker.recent_sessions]
        assert starts == [T0, T0 - 2 * 86400]
        assert tracker.lifetime["sessions"] == 2
        assert tracker.lifetime["thrusts"] == 150
        assert tracker.lifetime["active_s"] == pytest.approx(310.0)
        assert (tmp / "stats.json.before-gate.bak").exists()
        # Idempotent: a second launch changes nothing.
        before = json.dumps(tracker.snapshot())
        host._stats_clean_history()
        assert json.dumps(tracker.snapshot()) == before


# ============================================================ the live path

class _Clock:
    def __init__(self):
        self.t = T0

    def time(self):
        return self.t

    def monotonic(self):
        return self.t


class _Router:
    def __init__(self):
        self.last_outputs = {}
        self.pending = 0

    def should_send_to_toy(self, device, motor):
        return True

    def consume_thrusts(self):
        n, self.pending = self.pending, 0
        return n


class _Engine:
    is_connected = True

    def list_connected_device_names(self):
        return ["Domi"]


class TestLiveSampling:
    def _host(self, tmp_path, monkeypatch):
        from controllers import stats_facade as sf
        clock = _Clock()
        monkeypatch.setattr(sf, "time", clock)
        self.touching = False
        test = self

        class Store:
            def get_detected_zones(self):
                return {"Orifices": ["Ass"]}

            def get_all_parameters(self):
                return {}

        class Fresh:
            def is_stale(self):
                return False

        monkeypatch.setattr(sf, "store", Store())
        monkeypatch.setattr(sf, "zone_filter_strength",
                            lambda *a, **k: 1.0 if test.touching else 0.0)

        class Host(sf.StatsFacade):
            def get_master_scale(self):
                return 1.0

        h = Host()
        h.stats_tracker = StatsTracker(tmp_path / "stats.json")
        h.stats_history = StatsHistory(tmp_path / "s", tmp_path / "h.json")
        h.stats_tracker.start_session(T0)
        h.stats_history.start_session(T0)
        h._stats_gate = ActivityGate()
        h._stats_last_sample_t = None
        h._stats_samples_since_flush = 0
        h._stats_stale_monitor = Fresh()
        h.haptic_engine = _Engine()
        h.motor_router = _Router()
        h._muted_devices = set()
        return h, clock

    def _tick(self, h, clock, thrusts=0, toy=0.0, touching=False):
        clock.t += 1.0
        self.touching = touching
        h.motor_router.pending = thrusts
        h.motor_router.last_outputs = {("Domi", 0): toy} if toy else {}
        h._stats_sample_tick()

    def test_lone_strokes_without_a_toy_do_not_count(self, tmp_path, monkeypatch):
        h, clock = self._host(tmp_path, monkeypatch)
        self._tick(h, clock)                          # anchors the clock
        for k in range(200):
            self._tick(h, clock, thrusts=1 if k % 30 == 0 else 0)
        assert h.stats_tracker.lifetime["thrusts"] == 0
        assert h.stats_history.live_summary(clock.t) is None

    def test_a_streak_counts_from_its_start(self, tmp_path, monkeypatch):
        h, clock = self._host(tmp_path, monkeypatch)
        self._tick(h, clock)
        for _ in range(MIN_THRUSTS - 1):
            self._tick(h, clock, thrusts=1, touching=True)
        assert h.stats_tracker.lifetime["thrusts"] == 0      # still held back
        self._tick(h, clock, thrusts=1, touching=True)
        assert h.stats_tracker.lifetime["thrusts"] == MIN_THRUSTS
        assert h.stats_history.live_summary(clock.t)["thrusts"] == MIN_THRUSTS

    def test_a_running_toy_counts_straight_away(self, tmp_path, monkeypatch):
        h, clock = self._host(tmp_path, monkeypatch)
        self._tick(h, clock)
        self._tick(h, clock, thrusts=1, toy=0.5)
        assert h.stats_tracker.lifetime["thrusts"] == 1
        assert h.stats_tracker.lifetime["toys"]["Domi"]["on_s"] == 1.0


# ============================================================ the off switch

class TestStatisticsSwitch:
    def _host(self, tmp_path, monkeypatch, enabled=True):
        from controllers import stats_facade as sf
        monkeypatch.setattr(sf, "STATS_FILE", tmp_path / "stats.json")
        monkeypatch.setattr(sf, "STATS_HOURS_FILE", tmp_path / "stats_hours.json")
        monkeypatch.setattr(sf, "STATS_SESSIONS_DIR", tmp_path / "stats_sessions")
        monkeypatch.setattr(sf.debug_log, "log_path", lambda: tmp_path / "ogp_debug.log")
        flags = {"feature_statistics": enabled}

        class Host(sf.StatsFacade):
            def get_feature_enabled(self, key):
                return flags.get(key, True)

        h = Host()
        h._stats_init()
        return h, flags

    def test_off_at_launch_records_nothing_and_writes_nothing(self, tmp_path, monkeypatch):
        h, _ = self._host(tmp_path, monkeypatch, enabled=False)
        assert h.stats_tracker is None and h.stats_history is None
        h._stats_sample_tick()
        h._stats_shutdown()
        assert list(tmp_path.iterdir()) == []

    def test_switching_off_deletes_everything_recorded(self, tmp_path, monkeypatch):
        h, flags = self._host(tmp_path, monkeypatch)
        h.stats_tracker.sample(1.0, ["Domi"], [], 3)
        h.stats_tracker.flush(force=True)
        h.stats_history.sample(T0 + 1, 1.0, {"Domi": 1.0}, [], 3)
        h.stats_history.flush(force=True)
        (tmp_path / "stats.json.before-gate.bak").write_text("{}", encoding="utf-8")
        assert (tmp_path / "stats_sessions").exists()
        flags["feature_statistics"] = False
        h._stats_set_enabled(False)
        assert h.stats_tracker is None and h.stats_history is None
        assert list(tmp_path.iterdir()) == []
        h._stats_shutdown()                      # writes nothing back
        assert list(tmp_path.iterdir()) == []

    def test_switching_back_on_starts_fresh(self, tmp_path, monkeypatch):
        h, flags = self._host(tmp_path, monkeypatch)
        h.stats_tracker.sample(1.0, ["Domi"], [], 3)
        h._stats_set_enabled(False)
        flags["feature_statistics"] = True
        h._stats_set_enabled(True)
        assert h.stats_tracker is not None and h.stats_history is not None
        assert h.stats_tracker.lifetime["thrusts"] == 0
