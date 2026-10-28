"""The people facade: tagging sessions from the Statistics page, the People
table, and the opt-in tagging from VRChat's log — with a real StatsHistory
and StatsPeople, and a stand-in for the log watcher.

What must hold for the log tagging: a stretch only while you are alone with
exactly one other person (and VRChat is there), starting no earlier than
the session, ending when that changes, gone again if nothing happened in
it, and one stretch — not a pile of fragments — when the same person comes
straight back.
"""
import pytest

import controllers.people_facade as pf
from controllers.people_facade import PeopleFacade
from controllers.stats_facade import StatsFacade
from stats_history import StatsHistory
from stats_people import StatsPeople
from stats_tracker import StatsTracker


T0 = 1_790_000_000.0
ALEX = "usr_aaaa"
SAM = "usr_bbbb"


class _Settings:
    def __init__(self):
        self.values = {}

    def get(self, key, default=None):
        return self.values.get(key, default)

    def set(self, key, value):
        self.values[key] = value


class _Modes:
    def __init__(self):
        self.app_settings = _Settings()


class _Osc:
    is_connected = True


class _Watcher:
    def __init__(self):
        self.snap = {"state": "ok", "others": [], "since": None}
        self.started = self.stopped = 0

    def snapshot(self):
        return self.snap

    def start(self):
        self.started += 1

    def stop(self):
        self.stopped += 1


class Host(PeopleFacade, StatsFacade):
    def __init__(self, tmp_path):
        self.mode_manager = _Modes()
        self.osc_manager = _Osc()
        self.stats_tracker = StatsTracker(tmp_path / "stats.json")
        self.stats_tracker.start_session(T0)
        self.stats_history = StatsHistory(tmp_path / "sessions",
                                          tmp_path / "hours.json", pid=1)
        self.stats_history.start_session(T0)
        self.stats_people = StatsPeople(tmp_path / "people.json")
        self.watcher = _Watcher()
        self._people_make_watcher = lambda: self.watcher
        self._people_init()

    @property
    def sid(self):
        return self.stats_history.live["id"]

    def play(self, at, seconds=10, thrusts_every=2):
        """Activity from T0 + at: a toy on, a thrust every few seconds."""
        for k in range(seconds):
            t = 1 if thrusts_every and k % thrusts_every == 0 else 0
            self.stats_history.sample(T0 + at + k, 1.0, {"Toy": 0.5}, [], t)
            self.stats_tracker.sample(1.0, ["Toy"], [], t)

    def follow(self, at, others=(), since=None):
        self.watcher.snap = {"state": "ok", "others": list(others),
                             "since": None if since is None else T0 + since}
        self._people_follow_log(T0 + at)

    def tags(self):
        return self.stats_people.tags(self.sid)


@pytest.fixture
def host(tmp_path):
    return Host(tmp_path)


@pytest.fixture
def auto(host):
    host.set_people_autodetect(True)
    return host


class TestLogTagging:
    def test_off_by_default(self, host):
        assert not host.get_people_autodetect_enabled()
        assert host.watcher.started == 0
        assert host.get_people_autodetect_status() == {"state": "off"}

    def test_alone_with_one_person_opens_a_stretch(self, auto):
        auto.follow(100, [(ALEX, "Alex")], since=60)
        (tag,) = auto.tags()
        assert tag["people"] == ["Alex"] and tag["auto"] and tag["vrc"] == ALEX
        assert tag["start"] == T0 + 60 and tag["end"] is None
        assert auto.get_people_autodetect_status() == {"state": "with",
                                                        "name": "Alex"}

    def test_never_starts_before_the_session(self, auto):
        auto.follow(100, [(ALEX, "Alex")], since=-500)
        assert auto.tags()[0]["start"] == T0

    def test_ends_when_someone_joins_and_keeps_what_happened(self, auto):
        auto.follow(0, [(ALEX, "Alex")], since=0)
        auto.play(10, 60)
        auto.follow(200, [(ALEX, "Alex"), (SAM, "Sam")], since=150)
        (tag,) = auto.tags()
        assert tag["end"] == T0 + 150
        assert auto.get_people_autodetect_status() == {"state": "crowd",
                                                        "count": 2}

    def test_a_stretch_with_nothing_in_it_is_dropped(self, auto):
        auto.follow(0, [(ALEX, "Alex")], since=0)
        auto.follow(200, [], since=150)
        assert auto.tags() == []

    def test_a_new_person_gets_their_own_stretch(self, auto):
        auto.follow(0, [(ALEX, "Alex")], since=0)
        auto.play(10, 30)
        auto.follow(300, [(SAM, "Sam")], since=250)
        auto.play(260, 30)
        tags = auto.tags()
        assert [t["people"] for t in tags] == [["Alex"], ["Sam"]]
        assert tags[0]["end"] == T0 + 250 and tags[1]["start"] == T0 + 250

    def test_coming_straight_back_continues_the_stretch(self, auto):
        auto.follow(0, [(ALEX, "Alex")], since=0)
        auto.play(10, 30)
        auto.osc_manager.is_connected = False      # VRChat blinked
        auto.follow(100, [(ALEX, "Alex")], since=0)
        auto.osc_manager.is_connected = True
        auto.follow(160, [(ALEX, "Alex")], since=0)
        (tag,) = auto.tags()
        assert tag["end"] is None and tag["start"] == T0

    def test_vrchat_gone_ends_it(self, auto):
        auto.follow(0, [(ALEX, "Alex")], since=0)
        auto.play(10, 30)
        auto.osc_manager.is_connected = False
        auto.follow(100, [(ALEX, "Alex")], since=0)
        assert auto.tags()[0]["end"] == T0 + 100
        assert auto.get_people_autodetect_status() == {"state": "no_vrchat"}

    def test_a_renamed_user_keeps_their_name(self, auto):
        auto.stats_people.vrc_name(ALEX, "Alex")
        auto.follow(0, [(ALEX, "AlexNewName")], since=0)
        assert auto.tags()[0]["people"] == ["Alex"]

    def test_switching_off_ends_it_and_stops_reading(self, auto, monkeypatch):
        auto.follow(0, [(ALEX, "Alex")], since=0)
        auto.play(10, 30)
        monkeypatch.setattr(pf.time, "time", lambda: T0 + 90)
        auto.set_people_autodetect(False)
        assert auto.tags()[0]["end"] == T0 + 90
        assert auto.watcher.stopped == 1
        auto.follow(120, [(ALEX, "Alex")], since=0)
        assert len(auto.tags()) == 1


class TestTagging:
    def test_whole_session_and_stretches(self, host):
        host.play(0, 100)
        assert host.tag_session(host.sid, "Alex")
        assert host.tag_session_stretch(host.sid, T0 + 50, T0 + 20, "Sam, Kim")
        tags = host.tags()
        assert tags[0]["whole"] and tags[1]["start"] == T0 + 20
        row = host.get_stats_sessions()[0]
        assert row["people"] == ["Alex", "Sam", "Kim"]
        assert row["whole_people"] == ["Alex"]
        detail = host.get_stats_session_detail(host.sid)
        assert detail["tags"][1]["thrusts"] == 15

    def test_unknown_session_is_refused(self, host):
        assert not host.tag_session("20200101-000000", "Alex")

    def test_remove(self, host):
        host.play(0, 20)
        host.tag_session(host.sid, "Alex")
        tid = host.tags()[0]["id"]
        assert host.remove_session_tag(host.sid, tid)
        assert host.tags() == []

    def test_table_counts_the_running_session(self, host):
        host.play(0, 60)
        host.tag_session(host.sid, "Alex")
        (row,) = host.get_people_table()
        assert row["name"] == "Alex" and row["thrusts"] == 30
        assert host.get_people_names() == ["Alex"]

    def test_finished_sessions_are_credited_once_filed(self, host, monkeypatch):
        host.play(0, 60)
        host.tag_session(host.sid, "Alex")
        sid = host.sid
        import controllers.stats_facade as sf
        monkeypatch.setattr(sf.time, "time", lambda: T0 + 600)
        host._stats_shutdown()
        assert not host.stats_people.needs_credit(sid)
        (row,) = host.get_people_table()
        assert row["thrusts"] == 30 and row["sessions"] == 1

    def test_lost_cache_is_rebuilt_from_the_timeline(self, host, monkeypatch):
        host.play(0, 60)
        host.tag_session(host.sid, "Alex")
        import controllers.stats_facade as sf
        monkeypatch.setattr(sf.time, "time", lambda: T0 + 600)
        host._stats_shutdown()
        host.stats_people.invalidate_all()
        assert host.get_people_table()[0]["thrusts"] == 30

    def test_summary_sessions_take_whole_tags_only(self, host):
        host.stats_tracker.recent_sessions.append(
            {"started_ts": T0 - 9000.0, "duration_s": 600.0, "active_s": 300.0,
             "thrusts": 44, "toys": {}, "zones": {}})
        sid = f"summary:{T0 - 9000.0:.3f}"
        assert host.tag_session(sid, "Sam")
        assert not host.tag_session_stretch(sid, T0 - 8900, T0 - 8800, "Kim")
        assert host.get_stats_session_detail(sid)["tags"][0]["thrusts"] == 44
        assert host.get_people_table()[0]["thrusts"] == 44


class TestFiling:
    def test_idle_run_drops_its_tags(self, auto):
        auto.follow(0, [(ALEX, "Alex")], since=0)
        sid = auto.sid
        auto._stats_shutdown()
        assert auto.stats_people.tags(sid) == []

    def test_open_stretch_closes_with_the_session(self, auto, monkeypatch):
        auto.follow(0, [(ALEX, "Alex")], since=0)
        auto.play(10, 30)
        sid = auto.sid
        import controllers.stats_facade as sf
        monkeypatch.setattr(sf.time, "time", lambda: T0 + 500)
        auto._stats_shutdown()
        (tag,) = auto.stats_people.tags(sid)
        assert tag["end"] == T0 + 500

    def test_reset_forgets_people(self, host):
        host.play(0, 20)
        host.tag_session(host.sid, "Alex")
        host.reset_stats()
        assert host.stats_people.sessions == {}
        assert host.get_people_table() == []

    def test_statistics_off_ends_the_log_stretch(self, auto):
        auto.follow(0, [(ALEX, "Alex")], since=0)
        auto.stats_people = None
        auto.follow(30, [(ALEX, "Alex")], since=0)
        assert auto._people_auto is None
        assert auto.get_people_autodetect_status() == {"state": "no_stats"}
