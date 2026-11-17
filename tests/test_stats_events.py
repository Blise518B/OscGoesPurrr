"""Statistics counted from the log: stats_events.py (the store and its pure
read model), controllers/stats_events_facade.py (the log's listener, the
1 Hz count, the session's timeline and marks, the names switch, the suits)
and the From whom card.

What must hold: only what reached YOU is counted, an operation counts on
each shocker it went to, a hold's seconds are what it ran (in on / rest
cycles past the longest hold), held-back entries are counted apart, the
lifetime totals outlive the log's 30 days, names off means "A friend",
Forget names folds every name kept -- and the listener never counts on the
thread that logs."""

import sys
import time

import pytest

import event_log as el
import stats_events as se
from controllers import stats_facade as sf
from controllers.stats_facade import StatsFacade
from pishock_router import behaviour_name
from stats_events import StatsEvents
from stats_history import StatsHistory
from stats_tracker import StatsTracker

T0 = 1_790_000_000.0
A, B = "a" * 64, "b" * 64


def ev(t, who=A, name="Alex", role=el.ROLE_FRIEND, kind=el.SHOCK, op="shock", d=el.IN,
       level=30, ms=500, on=("Collar",), held="", asked="", via=""):
    return el.Event(T0 + t, f"{name} {op}", who, name, role, kind, op, d, level, ms,
                    tuple(on), held, asked, via)


def avatar(t, op="vibrate", via="Touch zones · Neck", **kw):
    return ev(t, who=el.AVATAR, name=el.AVATAR_NAME, role=el.ROLE_AVATAR, op=op, via=via, **kw)


@pytest.fixture
def store(tmp_path):
    return StatsEvents(tmp_path / "stats_events.json")


def count(store, *events, sid="s1", started=T0, **kw):
    for e in events:
        store.count(e, sid, started, **kw)


def person(view, name):
    return next(p for p in view["people"] if p["name"] == name)


# --- counting ---------------------------------------------------------------------------

def test_an_operation_counts_on_each_shocker_with_its_strongest_and_seconds(store):
    count(store, ev(0, on=("Collar", "Thigh"), level=30, ms=500),
          ev(10, op="vibrate", level=20, ms=1000), ev(20, op="beep", level=None, ms=300),
          ev(30, level=12, ms=200))
    v = store.lifetime_view()
    assert v["ops"]["shock"] == {"n": 3, "max": 30, "s": 1.2}
    assert v["ops"]["vibrate"] == {"n": 1, "max": 20, "s": 1.0}
    assert v["ops"]["beep"] == {"n": 1, "max": 0, "s": 0.3}
    shockers = {s["name"]: s["ops"] for s in v["shockers"]}
    assert shockers["Collar"]["shock"]["n"] == 2 and shockers["Thigh"]["shock"]["n"] == 1
    alex = person(v, "Alex")
    assert alex["ops"]["shock"]["n"] == 3 and alex["role"] == el.ROLE_FRIEND
    assert alex["last"] == T0 + 30


def test_only_what_reached_you_is_counted_and_held_back_apart(store):
    count(store,
          ev(0, d=el.OUT),                                       # you, to a friend
          ev(1, kind=el.LINK, op="online"),                      # the link
          ev(2, who=el.YOU, name=el.YOU_NAME, role=el.ROLE_YOU),  # your own switch
          ev(3, held="Off is on"),                               # refused
          ev(4, kind=el.TOYS, op="start", held="not in your instance"))
    v = store.lifetime_view()
    assert v["ops"]["shock"]["n"] == 0 and not v["shockers"]
    assert [(p["name"], p["held"]) for p in v["people"]] == [("Alex", 2)]


def test_your_avatar_is_one_person_split_by_behaviour(store):
    count(store, avatar(0), avatar(5, level=40), avatar(9, op="shock", via="Contact · Tap"))
    you = person(store.lifetime_view(), "Your avatar")
    assert you["ops"]["vibrate"]["n"] == 2 and you["ops"]["shock"]["n"] == 1
    assert [(v["label"], v["ops"]["shock"]["n"], v["ops"]["vibrate"]["n"])
            for v in you["via"]] == [("Contact · Tap", 1, 0), ("Touch zones · Neck", 0, 2)]


def test_a_hold_counts_when_it_starts_and_adds_its_seconds_when_it_ends(store):
    # your avatar: the let-go says how long and how strong (the router measured)
    count(store, avatar(0, op="hold", level=12, ms=None, asked="vibrate", via="Continuous · Prox"))
    assert store.lifetime_view()["ops"]["vibrate"] == {"n": 1, "max": 12, "s": 0.0}
    count(store, avatar(5, op="let-go", level=22, ms=4000, asked="vibrate", via="Continuous · Prox"))
    assert store.lifetime_view()["ops"]["vibrate"] == {"n": 1, "max": 22, "s": 4.0}
    # a friend's: its length is the time between (their let-go names the shocker)
    count(store, ev(10, op="hold", level=20, ms=None, asked="shock"),
          ev(13, op="let-go", level=None, ms=None))
    assert store.lifetime_view()["ops"]["shock"] == {"n": 1, "max": 20, "s": 3.0}


def test_an_unarmed_shock_hold_counts_as_the_vibrate_it_plays(store):
    count(store, ev(0, op="hold", level=20, ms=None, asked="vibrate"),
          ev(2, op="let-go", level=None, ms=None))
    ops = store.lifetime_view()["ops"]
    assert ops["shock"]["n"] == 0 and ops["vibrate"]["n"] == 1


def test_a_hold_past_the_longest_hold_runs_in_cycles():
    assert se.held_on_time(8, (10, 5)) == 8
    assert se.held_on_time(12, (10, 5)) == 10          # on 10, resting
    assert se.held_on_time(26, (10, 5)) == 20          # on, rest, on 10 of 11
    assert se.held_on_time(30, (10, 5)) == 20
    assert se.held_on_time(30, None) == 30


def test_a_stop_or_the_session_closing_ends_a_hold(store):
    count(store, ev(0, op="hold", ms=None, asked="vibrate"),
          ev(4, op="stop", level=None, ms=None))
    assert store.lifetime_view()["ops"]["vibrate"]["s"] == 4.0
    count(store, ev(10, op="hold", ms=None, asked="vibrate", on=("Thigh",)))
    store.close_all(T0 + 16, caps=(5.0, 1.0))
    assert store.lifetime_view()["ops"]["vibrate"]["s"] == 4.0 + 5.0   # 6 s held, 5 ran


def test_friends_drive_time_and_avatar_remote_sets(store):
    count(store,
          ev(0, kind=el.TOYS, op="start"), ev(60, kind=el.TOYS, op="dropout"),
          ev(100, kind=el.TOYS, op="back"), ev(160, kind=el.TOYS, op="stop"),
          ev(170, kind=el.TOYS, op="strength", level=50),          # not a drive
          *[ev(200 + i, kind=el.PARAMS, op="set") for i in range(3)],
          ev(210, kind=el.PARAMS, op="set", held="locked"))
    alex = person(store.lifetime_view(), "Alex")
    assert alex["drive_s"] == 120.0 and alex["sets"] == 3 and alex["held"] == 1
    count(store, ev(300, kind=el.TOYS, op="start"))
    store.close_all(T0 + 330)                                       # the session ends
    assert person(store.lifetime_view(), "Alex")["drive_s"] == 150.0


def test_sessions_keep_their_own_counts_and_go_with_their_timelines(store):
    count(store, ev(0), sid="s1")
    count(store, ev(10), ev(11), sid="s2", started=T0 + 5)
    assert store.session_view("s1")["ops"]["shock"]["n"] == 1
    assert store.session_view("s2")["ops"]["shock"]["n"] == 2
    assert store.lifetime_view()["ops"]["shock"]["n"] == 3
    store.keep_sessions(["s2"])
    assert store.session_view("s1") is None
    assert store.lifetime_view()["ops"]["shock"]["n"] == 3          # lifetime keeps it


def test_the_file_round_trips_and_a_damaged_one_starts_fresh(tmp_path, store):
    count(store, ev(0), avatar(1), ev(2, kind=el.TOYS, op="start"), ev(9, kind=el.TOYS, op="stop"))
    store.add_worn("s1", T0, 30.0, ["bHaptics Vest"])
    store.flush()
    again = StatsEvents(tmp_path / "stats_events.json")
    assert again.lifetime_view() == store.lifetime_view()
    assert again.session_view("s1") == store.session_view("s1")
    path = tmp_path / "stats_events.json"
    path.write_text("{ not json", encoding="utf-8")
    fresh = StatsEvents(path)
    assert not fresh.lifetime_view()["any"]
    assert (tmp_path / "stats_events.json.bak").exists()


# --- names --------------------------------------------------------------------------------

def test_names_off_counts_friends_as_a_friend(store):
    count(store, ev(0), ev(1, who=B, name="Sam"),
          ev(2, who="web-1", name="Kit (web)", role=el.ROLE_WEB),
          avatar(3), ev(4, who="__me__", name="You (Me)", role=el.ROLE_ME, via=el.VIA_MENU),
          names=False)
    names = {p["name"] for p in store.lifetime_view()["people"]}
    assert names == {"A friend", "Web remote", "Your avatar", "You (Me)"}
    assert person(store.lifetime_view(), "A friend")["ops"]["shock"]["n"] == 2
    assert not store.has_names()


def test_forget_names_folds_every_name_kept(store):
    count(store, ev(0), ev(1, who=B, name="Sam", op="vibrate"),
          ev(2, who="web-1", name="Kit (web)", role=el.ROLE_WEB), avatar(3),
          ev(4, kind=el.TOYS, op="start"))
    count(store, ev(5, held="paused"), names=False)          # already anonymous: merged in
    assert store.has_names()
    assert store.forget_names()
    for v in (store.lifetime_view(), store.session_view("s1")):
        assert {p["name"] for p in v["people"]} == {"A friend", "Web remote", "Your avatar"}
        friend = person(v, "A friend")
        assert (friend["ops"]["shock"]["n"], friend["ops"]["vibrate"]["n"], friend["held"]) == (
            1, 1, 1)
    assert not store.has_names() and not store.forget_names()
    count(store, ev(64, kind=el.TOYS, op="stop"))           # Alex's open drive: no name left
    assert person(store.lifetime_view(), "A friend")["drive_s"] == 60.0
    assert "Alex" not in {p["name"] for p in store.lifetime_view()["people"]}


# --- the timeline's marks -------------------------------------------------------------

def test_marks_say_when_how_strong_and_from_whom():
    events = [ev(0, on=("Collar", "Thigh")), ev(1, held="Off is on"), ev(2, d=el.OUT),
              avatar(5, op="hold", level=10, ms=None, asked="vibrate"),
              avatar(9, op="let-go", level=25, ms=4000, asked="vibrate"),
              ev(12, who="__me__", name="You (Me)", role=el.ROLE_ME, op="beep", level=None,
                 via=el.VIA_PARTY)]
    marks = se.marks(events)
    assert [(m["op"], m["level"], m["who"]) for m in marks] == [
        ("shock", 30, "Alex"), ("vibrate", 25, "Your avatar · Touch zones · Neck"),
        ("beep", None, "You (Me) · Party Mode")]
    assert marks[0]["on"] == ["Collar", "Thigh"]
    assert marks[1]["hold"] and marks[1]["ms"] == 4000
    assert se.marks(events, names=False)[0]["who"] == "A friend"


def test_behaviour_names_are_their_kind_and_zone_or_label():
    assert behaviour_name("zones", {"name": "Touch zones"}, "Contact/Neck") == "Touch zones · Neck"
    assert behaviour_name("zones", {"name": "Collar spots"}, "Contact/ThighL") == (
        "Collar spots · ThighL")
    assert behaviour_name("triggers", {"name": "Spank", "param": "Contact/Butt"}) == (
        "Contact · Spank")
    assert behaviour_name("triggers", {"name": "Trigger", "param": "Contact/Butt"}) == (
        "Contact · Butt")
    assert behaviour_name("continuous", {"name": "Continuous", "param": "Prox"}) == (
        "Continuous · Prox")
    assert behaviour_name("impacts", {"name": "Impact", "tiers": [
        {"param": ""}, {"param": "Impact/Butt"}]}) == "Impact · Butt"
    assert behaviour_name("triggers", {"name": "", "param": ""}) == "Contact"
    assert len(behaviour_name("triggers", {"name": "x" * 200})) <= 48


# --- the controller: the log's listener, the 1 Hz count, the session ------------------

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


class Host(StatsFacade):
    """The statistics with the app's log; the stores in a temp folder."""

    def __init__(self, tmp_path, log=None, start=T0):
        self.mode_manager = _Modes()
        self.event_log = log if log is not None else el.EventLog(None)
        self.stats_tracker = StatsTracker(tmp_path / "stats.json")
        self.stats_tracker.start_session(start)
        self.stats_history = StatsHistory(tmp_path / "sessions", tmp_path / "hours.json", pid=1)
        self.stats_history.start_session(start)
        self.stats_people = None
        self._stats_events_init()

    @property
    def sid(self):
        return self.stats_history.live["id"]


def test_the_log_is_counted_on_the_stats_tick_not_where_it_is_logged(tmp_path):
    h = Host(tmp_path)
    h.event_log.add(ev(5))
    # the listener only queued it: nothing counted on the logging thread
    assert len(h._stats_events_pending) == 1
    assert not h.stats_events.lifetime_view()["any"]
    h._stats_events_tick(1.0)
    assert not h._stats_events_pending
    assert h.get_stats_from_whom()["ops"]["shock"]["n"] == 1
    assert h.get_stats_from_whom("session")["ops"]["shock"]["n"] == 1


def test_a_session_of_only_shocks_is_filed_with_its_marks(tmp_path, monkeypatch):
    h = Host(tmp_path)
    h.event_log.add(ev(35))
    h._stats_events_tick(1.0)
    assert 3 in h.stats_history.live["buckets"]               # the shock's 10 s bucket
    d = h.get_stats_session_detail(h.sid)
    assert d["shocks"]["tally"]["ops"]["shock"]["n"] == 1
    assert [m["who"] for m in d["shocks"]["marks"]] == ["Alex"]
    sid = h.sid
    monkeypatch.setattr(sf.time, "time", lambda: T0 + 600)
    h._stats_shutdown()
    assert sid in [e["id"] for e in h.stats_history.index]
    assert h.get_stats_session_detail(sid)["shocks"]["tally"]["ops"]["shock"]["n"] == 1


def test_shutdown_counts_what_is_left_and_ends_open_holds(tmp_path, monkeypatch):
    h = Host(tmp_path)
    h.event_log.add(ev(10, op="hold", ms=None, asked="vibrate"))
    monkeypatch.setattr(sf.time, "time", lambda: T0 + 13)
    h._stats_shutdown()                       # never ticked: counted on the way out
    again = StatsEvents(tmp_path / "stats_events.json")
    assert again.lifetime_view()["ops"]["vibrate"] == {"n": 1, "max": 30, "s": 3.0}


def test_lifetime_totals_outlive_the_logs_30_days(tmp_path, monkeypatch):
    now = [T0]
    log = el.EventLog(tmp_path / "log", clock=lambda: now[0])
    h = Host(tmp_path, log)
    log.add(ev(20))
    log.add(avatar(25))
    h._stats_events_tick(1.0)
    sid = h.sid
    monkeypatch.setattr(sf.time, "time", lambda: T0 + 600)
    h._stats_shutdown()
    log.close()
    assert list((tmp_path / "log").glob("*.jsonl"))
    # 31 days on: the log has dropped those days...
    now[0] = T0 + 31 * 86400
    log2 = el.EventLog(tmp_path / "log", clock=lambda: now[0])
    log2.rotate()
    log2.load()
    assert log2.recent() == [] and not list((tmp_path / "log").glob("*.jsonl"))
    # ...the statistics haven't
    h2 = Host(tmp_path, log2, start=now[0])
    whom = h2.get_stats_from_whom()
    assert whom["ops"]["shock"]["n"] == 1 and whom["ops"]["vibrate"]["n"] == 1
    assert {p["name"] for p in whom["people"]} == {"Alex", "Your avatar"}
    old = h2.get_stats_session_detail(sid)
    assert old["shocks"]["tally"]["ops"]["shock"]["n"] == 1     # the session's own counts
    assert old["shocks"]["marks"] == []                          # its marks went with the log
    log2.add(el.Event(now[0] + 5, "", A, "Alex", el.ROLE_FRIEND, el.SHOCK, "shock", el.IN,
                      10, 300, ("Collar",)))
    h2._stats_events_tick(1.0)
    assert h2.get_stats_from_whom()["ops"]["shock"]["n"] == 2   # rolled up on top


def test_the_names_switch_and_forget_names(tmp_path):
    h = Host(tmp_path)
    assert h.get_stats_friend_names()                            # on by default
    h.set_stats_friend_names(False)
    h.event_log.add(ev(1))
    h._stats_events_tick(1.0)
    whom = h.get_stats_from_whom()
    assert [p["name"] for p in whom["people"]] == ["A friend"]
    assert not whom["names"] and not whom["kept"] and not h.stats_friend_names_kept()
    h.set_stats_friend_names(True)
    h.event_log.add(ev(2, who=B, name="Sam"))
    h._stats_events_tick(1.0)
    assert h.stats_friend_names_kept()
    assert h.forget_stats_friend_names()
    assert {p["name"] for p in h.get_stats_from_whom()["people"]} == {"A friend"}
    assert person(h.get_stats_from_whom(), "A friend")["ops"]["shock"]["n"] == 2


def test_reset_and_delete_take_the_counts_too(tmp_path, monkeypatch):
    h = Host(tmp_path)
    h.event_log.add(ev(1))
    h._stats_events_tick(1.0)
    h.reset_stats()
    assert not h.get_stats_from_whom()["any"]
    from controllers import stats_events_facade
    path = stats_events_facade.STATS_EVENTS_FILE
    h.event_log.add(ev(2))
    h._stats_events_tick(1.0)
    h.stats_events.flush()
    assert path.exists()
    for name in ("STATS_FILE", "STATS_HOURS_FILE", "STATS_PEOPLE_FILE"):
        monkeypatch.setattr(sf, name, tmp_path / f"{name}.json")
    monkeypatch.setattr(sf, "STATS_SESSIONS_DIR", tmp_path / "gone")
    sf._delete_stats_files()
    assert not path.exists()


def test_statistics_off_counts_nothing(tmp_path):
    h = Host(tmp_path)
    h._stats_drop()
    h.event_log.add(ev(1))
    assert not h._stats_events_pending
    assert not h.get_stats_from_whom()["on"]


# --- the suits and trackers ------------------------------------------------------------

class _Bh:
    def status_snapshot(self):
        return {"devices": [{"positions": ["VestFront", "VestBack"]}]}

    def output_snapshot(self):
        return {"VestFront": (0, 40, 0), "VestBack": (0, 0, 0), "ForearmL": (50,)}


class _Owo:
    def __init__(self, active):
        self.active = active

    def status_snapshot(self):
        return {"connected": True, "active": self.active}


class _Trk:
    def output_snapshot(self):
        return {"LHR-1": 0.5, "LHR-2": 0.0}


def test_the_suits_and_trackers_on_time(tmp_path):
    h = Host(tmp_path)
    h.bhaptics_engine, h.owo_engine, h.tracker_engine = _Bh(), _Owo({"Pectoral_R": 30}), _Trk()
    h._tracker_places = lambda: {"LHR-1": "hips", "LHR-2": "chest"}
    assert h._stats_worn_now() == ["bHaptics Vest", "OWO suit", "Tracker · Hips"]
    h._stats_events_tick(2.0)
    h.owo_engine.active = {}
    h.get_feature_enabled = lambda key: key != "feature_trackers"
    h._stats_events_tick(1.0)
    worn = h.get_stats_worn()
    assert dict(worn["lifetime"]) == {"bHaptics Vest": 3.0, "OWO suit": 2.0,
                                      "Tracker · Hips": 2.0}
    assert worn["session"] == worn["lifetime"]


# --- the page -----------------------------------------------------------------------------

@pytest.fixture(scope="module")
def qapp():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication(sys.argv[:1])


class FakeController:
    """The From whom getters, answered from a real store."""

    def __init__(self, store, names=True):
        self.store, self.names, self.forgot = store, names, 0

    def get_stats_from_whom(self, span="lifetime"):
        out = (self.store.session_view("s1") or se.view(se.fresh_tally())
               if span == "session" else self.store.lifetime_view())
        out.update(names=self.names, kept=self.store.has_names(), on=True)
        return out

    def get_stats_worn(self):
        return {"lifetime": self.store.lifetime_view()["worn"],
                "session": (self.store.session_view("s1") or {"worn": []})["worn"]}

    def get_stats_friend_names(self):
        return self.names

    def set_stats_friend_names(self, on):
        self.names = on

    def forget_stats_friend_names(self):
        self.forgot += 1
        return self.store.forget_names()


def whom_page(controller):
    from PySide6.QtWidgets import QVBoxLayout, QWidget
    from ui.views.device_frame import DeviceFrameMixin
    from ui.views.statistics import StatisticsMixin

    class _Host(StatisticsMixin, DeviceFrameMixin):
        def __init__(self):
            self.controller = controller
            self.window = QWidget()
            self.views = {}
            lay = QVBoxLayout(self.window)
            self._stats_build_whom_card(lay)
            self._stats_build_worn_table(lay)

        def _repolish(self, w):
            w.style().unpolish(w)
            w.style().polish(w)

        def log_message(self, text):
            pass

    return _Host()


def _grid_texts(grid):
    rows = {}
    for i in range(grid.count()):
        w = grid.itemAt(i).widget()
        r, c, _rs, _cs = grid.getItemPosition(i)
        if hasattr(w, "text"):
            rows.setdefault(r, {})[c] = w.text()
    return rows


def test_the_from_whom_card_lists_people_behaviours_and_shockers(qapp, store):
    count(store, ev(0, on=("Collar", "Thigh"), level=30, ms=500), avatar(1),
          avatar(2, op="shock", via="Contact · Tap", level=15),
          ev(3, kind=el.TOYS, op="start"), ev(63, kind=el.TOYS, op="stop"),
          ev(70, who=B, name="Sam", kind=el.PARAMS, op="set"))
    store.add_worn("s1", T0, 90.0, ["bHaptics Vest"])
    page = whom_page(FakeController(store))
    page._stats_fill_whom()
    page._stats_fill_worn()
    rows = _grid_texts(page._stats_whom_grid)
    by_name = {r.get(1, "").strip(): r for r in rows.values()}
    assert by_name["Alex"][2] == "2" and by_name["Alex"][5] == "30" and by_name["Alex"][7] == "1m"
    assert by_name["Your avatar"][2] == "1" and by_name["Your avatar"][3] == "1"
    assert by_name["↳ Contact · Tap"][2] == "1" and by_name["↳ Touch zones · Neck"][3] == "1"
    assert by_name["Sam"][8] == "1"                                   # an Avatar Remote set
    shockers = {r[0]: r for r in _grid_texts(page._stats_shockers_grid).values() if 0 in r}
    assert shockers["Collar"][1] == "2" and shockers["Thigh"][1] == "1"
    assert page._stats_whom_tiles["shock"].value.text() == "3"
    assert page._stats_forget_btn.isEnabled()
    assert not page._stats_worn_box.isHidden()


def test_the_names_switch_and_forget_on_the_card(qapp, store, monkeypatch):
    from PySide6.QtWidgets import QMessageBox
    count(store, ev(0))
    c = FakeController(store)
    page = whom_page(c)
    page._stats_names_toggle.setChecked(False)
    assert c.names is False
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.No)
    page._on_stats_forget_names()
    assert c.forgot == 0                                              # asked first: no
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.Yes)
    page._on_stats_forget_names()
    assert c.forgot == 1
    assert not page._stats_forget_btn.isEnabled()                     # nothing left to forget
    rows = _grid_texts(page._stats_whom_grid)
    assert "A friend" in {r.get(1) for r in rows.values()}


def test_an_empty_card_says_what_lands_there(qapp, store):
    page = whom_page(FakeController(store))
    page._stats_fill_whom()
    page._stats_fill_worn()
    assert not page._stats_whom_empty.isHidden() and page._stats_whom_host.isHidden()
    assert page._stats_worn_box.isHidden() and page._stats_shockers_host.isHidden()


def test_the_timeline_marks_each_shock_and_says_who(qapp):
    from ui.session_timeline import SessionTimeline, mark_text
    tl = SessionTimeline()
    detail = {"started_ts": T0, "dense": {"bucket_s": 10, "start_i": 0, "n": 30,
                                          "active": [10.0] * 30, "thrusts": [0] * 30,
                                          "toys": {}, "zones": {}},
              "toys": {}, "zones": {}}
    tl.set_detail(detail)
    bare = tl.height()
    marks = se.marks([ev(40, ms=1000), ev(41, who=B, name="Sam", op="beep", level=None)])
    tl.set_detail(dict(detail, shocks={"tally": None, "marks": marks}))
    assert tl.height() > bare                                         # the shockers lane
    assert tl._marks_between(T0 + 40, T0 + 50) == marks
    text = mark_text(marks[0])
    assert text.endswith("shock 30 · 1.0 s on Collar — from Alex")
    assert time.strftime("%H:%M:%S", time.localtime(T0 + 40)) in text
    tl.grab()                                                         # paints without error


def test_a_corrected_operation_counts_what_went_out_not_what_was_asked(store):
    count(store, el.Event(T0, "Alex: shock 80 · 3.0 s on Collar", A, "Alex", el.ROLE_FRIEND,
                          el.SHOCK, "shock", el.IN, 30, 1200, ("Collar",),
                          asked_level=80, asked_ms=3000, fixed="their longest pulse"))
    assert store.lifetime_view()["ops"]["shock"] == {"n": 1, "max": 30, "s": 1.2}
