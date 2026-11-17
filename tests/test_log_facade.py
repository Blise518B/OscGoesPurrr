"""The log, end to end: the Friends paths write records that know who and
what (and the line is written from them), your own avatar's shocker
behaviours land as "Your avatar", the Log page's queries and Clear, and the
two views -- the Friends card's As it happens / By person and the Log
page. Every file lands in a temp folder (conftest points LOG_DIR there)."""

import os
import time

import pytest

import event_log as el
import pishock_engine as pe
import pishock_router
import remote_protocol as proto
import router_base
from controllers import log_facade
from controllers.friends_common import ME
from controllers.log_facade import LogFacade
from parameter_store import ParameterStore
from pishock_router import PiShockRouter
from settings.pishock import clean_continuous, clean_trigger
from test_friends_facade import A, B, Host as FriendsHost, linked_with_toys


class Host(LogFacade, FriendsHost):
    """The Friends test host with the app's log (files in a temp folder)."""

    def __init__(self, folder=None, **features):
        self.event_log = el.EventLog(folder)
        super().__init__(**features)


def records(h, **where):
    return [e for e in h.event_log.recent()
            if all(getattr(e, k) == v for k, v in where.items())]


# --- the records the Friends paths write -------------------------------------------

def test_a_friends_shock_is_a_record_of_who_and_what():
    h = Host()
    h.befriend(A, shock=True)
    h.pishock_engine.is_armed = True
    h._friends_on_event("message", A, proto.make_shock("x1", [0, 1], 0.5, 0.5))
    [e] = records(h, kind=el.SHOCK)
    assert (e.who, e.name, e.role, e.dir, e.op) == (A, "Alex", el.ROLE_FRIEND, el.IN, "shock")
    assert e.level == 20 and e.ms > 0 and e.on == ("Collar", "Shocker 22") and not e.held
    assert e.stands_out
    assert e.text.startswith("Alex: shock 20 · ")          # the line, from the record


def test_an_unarmed_shock_is_logged_as_the_vibrate_it_became():
    h = Host()
    h.befriend(A, shock=True)
    h._friends_on_event("message", A, proto.make_shock("x2", [0], 1.0, 1.0))
    [e] = records(h, kind=el.SHOCK)
    assert (e.op, e.asked) == ("vibrate", "shock") and not e.stands_out and e.shocker_op
    assert "vibrate 40 (shocks aren't armed)" in e.text


def test_a_held_back_shock_says_why():
    h = Host()
    h.befriend(A, shock=True)
    h._off = True
    h._friends_on_event("message", A, proto.make_shock("x3", [0], 1.0, 1.0))
    [e] = records(h, kind=el.SHOCK)
    assert e.held == "Off is on" and e.op == "shock" and not e.shocker_op


def test_your_drive_on_a_friend_and_theirs_on_you_point_both_ways():
    h = Host()
    h.befriend(A)
    linked_with_toys(h, A)
    h.set_friend_strength(A, 0.3)
    h.set_friend_strength(A, 0.6)                    # a drag: one entry
    h._friends_on_queue("strength", (A, 0.5))
    out = records(h, kind=el.TOYS, dir=el.OUT)
    assert [(e.op, e.level, e.text) for e in out] == [
        ("strength", 60, "You set Alex's strength to 60 %")]
    [inn] = records(h, kind=el.TOYS, dir=el.IN)
    assert (inn.who, inn.level, inn.text) == (A, 50, "Alex set your strength to 50 %")


def test_the_name_comes_from_the_record_for_every_kind_of_person():
    h = Host()
    h.befriend(A)
    h._friends_note("{who} did a thing", who=A)
    h._friends_note("{who} did a thing", who=ME)
    gid = h.friends_settings.add_group("Night crew")
    h._friends_note("{who} did a thing", who=el.group_key(gid))
    h._web_guests = {"w" * 64: "Kim"}
    h._friends_note("{who} did a thing", who="w" * 64)
    h._friends_note("You went online")
    got = [(e.name, e.role, e.text) for e in reversed(h.event_log.recent())
           if e.text.endswith("did a thing") or e.role == el.ROLE_YOU]
    assert ("Alex", el.ROLE_FRIEND, "Alex did a thing") in got
    assert ("You (Me)", el.ROLE_ME, "You (Me) did a thing") in got
    assert ("Night crew", el.ROLE_GROUP, "Night crew did a thing") in got
    assert ("Kim (web)", el.ROLE_WEB, "Kim (web) did a thing") in got
    assert got[-1] == ("You", el.ROLE_YOU, "You went online")


def test_a_nickname_with_braces_is_only_a_name():
    h = Host()
    h.friends_settings.add_friend(A, "{who}{0}")
    h._friends_note("{who} went offline (closed OGP)", who=A, op="offline")
    assert h.event_log.recent()[0].text == "{who}{0} went offline (closed OGP)"


def test_the_friends_card_leaves_your_avatar_to_the_log_page():
    h = Host()
    h.befriend(A)
    h._friends_note("{who} is online", who=A, op="online")
    h.event_log.add(el.Event(time.time(), "Your avatar: shock 10", el.AVATAR, "Your avatar",
                             el.ROLE_AVATAR, el.SHOCK, "shock", el.IN))
    h._friends_note("You went online")
    assert [e["text"] for e in h.get_friends_log()] == ["You went online", "Alex is online"]
    people = h.get_friends_log_people()
    assert [p["who"] for p in people] == [A]           # no avatar, no "You" row
    assert people[0]["last"]["text"] == "Alex is online" and people[0]["ago"] == "just now"
    assert {e["role"] for e in h.get_log_events()["events"]} == {
        el.ROLE_YOU, el.ROLE_AVATAR, el.ROLE_FRIEND}


# --- your own avatar's behaviours ----------------------------------------------------

@pytest.fixture
def store(monkeypatch):
    s = ParameterStore()
    monkeypatch.setattr(pishock_router, "store", s)
    monkeypatch.setattr(router_base, "store", s)
    return s


class RulesEngine:
    """Enough of PiShockEngine for the router and the log."""
    is_connected, is_paused, is_armed = True, False, True

    def __init__(self):
        self.calls = []

    def shocker_ids(self):
        return [11]

    def shockers(self):
        return [{"id": 11, "name": "Collar"}]

    def limits_for(self, sid):
        return {"max_intensity": 25, "max_vibrate": 60, "max_pulse_ms": 2000}

    def op_allowed(self, sid, op):          # every Shock / Vibrate / Beep switch on
        return True

    def pulse(self, sid, op, intensity, ms, **rules):     # run_cap_ms
        """What the engine sends: the level under the op's ceiling, the
        length under the longest pulse (pishock_engine.Sent)."""
        self.calls.append(("pulse", sid, op, intensity, ms))
        caps = self.limits_for(sid)
        top = caps["max_intensity"] if op == "shock" else caps["max_vibrate"]
        return pe.Sent(op, min(intensity, top), min(ms, caps["max_pulse_ms"]),
                       capped=intensity > top,
                       cut=pe.CUT_LONGEST if ms > caps["max_pulse_ms"] else "")

    def hold_free_in(self, sid, group="avatar"):     # no pulse running, no rest
        return 0.0

    def is_resting(self, sid, group="avatar"):
        return False

    def hold(self, sid, op, intensity, source="", group="avatar"):
        self.calls.append(("hold", sid, op, intensity))

    def release(self, sid, source=""):
        self.calls.append(("release", sid))

    def end(self, sid):
        pass

    def end_all(self):
        pass


def avatar_host(rules):
    h = Host()
    h.pishock_engine = RulesEngine()
    router = PiShockRouter(h.pishock_engine, get_rules=lambda: rules,
                           is_output_off=lambda: False, report=h._log_avatar_shock)
    return h, router


def test_your_avatars_pulse_is_logged_within_the_shockers_caps(store):
    h, router = avatar_host({"triggers": [clean_trigger(
        {"param": "Tap", "intensity": 40, "duration_ms": 400, "op": "shock",
         "shockers": "all"})]})
    router.tick()
    store.update_parameter("Tap", True)
    store.update_parameter("Tap", False)
    router.tick()
    assert ("pulse", 11, "shock", 40, 400) in h.pishock_engine.calls   # the send went first
    [e] = records(h, who=el.AVATAR)
    assert (e.name, e.role, e.kind, e.op, e.dir) == (
        "Your avatar", el.ROLE_AVATAR, el.SHOCK, "shock", el.IN)
    assert (e.level, e.ms, e.on) == (25, 400, ("Collar",))              # capped at 25
    # the line says what the behaviour asked, the muted line under it what
    # went out and why
    assert e.text == "Your avatar (Contact · Tap): shock 40 · 0.4 s on Collar" and e.stands_out
    assert (e.asked_level, e.asked_ms) == (40, None)
    assert e.correction == "Lowered to 25: your shock limit"
    assert e.via == "Contact · Tap"                         # which behaviour fired
    assert h.get_friends_log() == []                                     # Log page only


def test_your_avatars_hold_is_logged_when_it_starts_and_ends(store, monkeypatch):
    h, router = avatar_host({"continuous": [clean_continuous(
        {"param": "Prox", "threshold": 0.0, "min_int": 10, "max_int": 50, "op": "vibrate",
         "shockers": "all"})]})
    t = [100.0]
    router._clock = lambda: t[0]
    for v in (0.2, 0.9, 0.5):
        store.update_parameter("Prox", v)
        router.tick()
        t[0] += 1.0
    store.update_parameter("Prox", 0.0)
    router.tick()
    got = [(e.op, e.asked, e.level, e.ms) for e in reversed(records(h, who=el.AVATAR))]
    assert got == [("hold", "vibrate", 18, None), ("let-go", "vibrate", 46, 3000)]
    assert records(h, who=el.AVATAR)[0].text == (
        "Your avatar (Continuous · Prox) let go of Collar after 3.0 s (up to vibrate 46)")
    assert {e.via for e in records(h, who=el.AVATAR)} == {"Continuous · Prox"}


def test_a_router_without_the_log_sends_the_same(store):
    eng = RulesEngine()
    router = PiShockRouter(eng, get_rules=lambda: {"triggers": [clean_trigger(
        {"param": "Tap", "intensity": 40, "op": "shock", "shockers": "all"})]},
        is_output_off=lambda: False)
    router.tick()
    store.update_parameter("Tap", True)
    router.tick()
    assert [c[0] for c in eng.calls] == ["pulse"]


# --- the Log page ------------------------------------------------------------------------

def test_the_log_pages_queries_and_clear(tmp_path):
    h = Host(folder=tmp_path / "log")
    h.befriend(A)
    h.befriend(B)
    now = time.time()
    rows = [(now - 2 * 86400, A, "Alex", el.TOYS, "Alex drove your toys"),
            (now - 120, B, "Sam", el.SHOCK, "Sam: shock 20 on Collar"),
            (now - 60, el.AVATAR, "Your avatar", el.SHOCK, "Your avatar: vibrate 10")]
    for t, who, name, kind, text in rows:
        role = el.ROLE_AVATAR if who == el.AVATAR else el.ROLE_FRIEND
        h.event_log.add(el.Event(t, text, who, name, role, kind,
                                 "shock" if "shock" in text else ""))
    assert h.get_log_spans()[-1] == "Last 30 days"
    assert [k["key"] for k in h.get_log_kinds()] == list(el.KINDS)
    got = h.get_log_events(span="Today")
    assert [e["text"] for e in got["events"]] == ["Your avatar: vibrate 10",
                                                  "Sam: shock 20 on Collar"]
    got = h.get_log_events(hide_avatar=True, kinds=[el.SHOCK])
    assert [e["who"] for e in got["events"]] == [B] and got["total"] == 1
    assert h.get_log_events(person=A)["total"] == 1
    assert h.get_log_events(limit=1) == {**h.get_log_events(limit=1), "shown": 1, "total": 3}
    people = h.get_log_people(span="Last 7 days")
    assert [p["who"] for p in people] == [el.AVATAR, B, A]
    assert [p["who"] for p in h.get_log_people(hide_avatar=True, text="sam")] == [B]
    assert people[1]["shocks"] == 1
    page = h.get_log_page(person=B, span="Last 7 days")          # one pass for the page
    assert [e["who"] for e in page["events"]] == [B] and page["total"] == 1
    assert [p["who"] for p in page["people"]] == [el.AVATAR, B, A]   # whoever is picked
    h.event_log.flush(force=True)
    assert any((tmp_path / "log").iterdir())
    v = h.get_log_version()
    h.clear_log()
    assert h.get_log_events()["total"] == 0 and h.get_log_version() > v
    h.event_log.flush()
    assert not any(p.suffix == ".jsonl" for p in (tmp_path / "log").iterdir())


def test_the_app_keeps_its_log_in_the_temp_folder_in_tests(tmp_path):
    class App(LogFacade):
        def log_message(self, _m):
            pass
    app = App()
    app._event_log_init()
    try:
        assert app.event_log.folder == log_facade.LOG_DIR == tmp_path / "event_log"
    finally:
        app._event_log_shutdown()
    assert not app.event_log._thread.is_alive()


def test_the_time_spans_start_where_they_say():
    now = time.time()
    assert abs(log_facade._since("Last hour") - (now - 3600)) < 5
    lt = time.localtime(now)
    assert log_facade._since("Today") == time.mktime(
        (lt.tm_year, lt.tm_mon, lt.tm_mday, 0, 0, 0, 0, 0, -1))
    assert log_facade._since("Last 30 days") is None and log_facade._since("") is None


# --- the views ---------------------------------------------------------------------------

@pytest.fixture
def qapp():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def _person(who, name, texts, shocks=0):
    now = time.time()
    recent = [el.Event(now - i, t, who, name, el.ROLE_FRIEND, el.SHOCK if "shock" in t
                       else el.TOYS, "shock" if "shock" in t else "").as_dict()
              for i, t in enumerate(texts)]
    return {"who": who, "name": name, "role": el.ROLE_FRIEND, "last": recent[0],
            "ago": "just now", "count": len(texts), "shocks": shocks, "shocker_ops": shocks,
            "recent": recent}


def test_by_person_rows_unfold_and_stay_unfolded(qapp):
    from ui.views.log_people import PersonLog
    picked = []
    w = PersonLog("nobody yet", on_pick=picked.append)
    w.set_people([])
    assert w.people() == [] and w._empty.isVisibleTo(w)
    sam = _person(B, "Sam", ["Sam: shock 20 on Collar", "Sam is online"], shocks=1)
    alex = _person(A, "<b>Alex</b>", ["Alex drove your toys"])
    w.set_people([sam, alex])
    assert w.people() == [B, A] and not w._empty.isVisibleTo(w)
    row = w._rows[B]
    assert row.shocks.text() == "1 shock" and not row.body.isVisibleTo(w)
    assert w._rows[A].name.text() == "<b>Alex</b>"               # plain text, never markup
    w.toggle(B)
    assert row.body.isVisibleTo(w) and row.caret.text() == "▾"
    assert "<b " in row.body.text() and "shock 20" in row.body.text()   # the shock stands out
    w.set_people([alex, sam])                                     # Alex acted since
    assert w.people() == [A, B] and w.is_open(B) and w._rows[B] is row
    row.pick.click()
    assert picked == [B]
    w.set_people([alex])
    assert w.people() == [A] and not w.is_open(B)
    w.refresh_ago(alex["last"]["t"] + 200)           # time passes, nothing new comes in
    assert w._rows[A].ago.text() == "3 min ago"


def test_history_lines_escape_what_strangers_wrote():
    from ui.views.log_people import history_html
    html = history_html([el.Event(time.time(), "<img src=x> & co", A, "x").as_dict()])
    assert "<img" not in html and "&lt;img src=x&gt; &amp; co" in html


def _corrected(text="Alex: vibrate 40 · 2.0 s on Collar"):
    return el.Event(time.time(), text, A, "Alex", el.ROLE_FRIEND, el.SHOCK, "vibrate", el.IN,
                    10, 500, ("Collar",), asked_level=40, asked_ms=2000,
                    fixed="their longest pulse").as_dict()


def test_a_corrected_entry_has_what_went_out_muted_under_it_in_the_history():
    from ui.views.log_people import history_html
    html = history_html([_corrected()])
    line = "Lowered to 10 and cut to 0.5 s: their longest pulse"
    assert line in html and html.index("vibrate 40") < html.index(line)


def test_the_log_pages_corrected_entry_gets_a_second_line(qapp):
    from ui.views import log_page

    class Page(log_page.LogPageMixin):
        def _explain(self, *_args):
            pass

    p = Page()
    t = p._build_log_table()
    plain = el.Event(time.time(), "Alex: vibrate 10", A, "Alex", el.ROLE_FRIEND, el.SHOCK,
                     "vibrate", el.IN, 10, 500).as_dict()
    p._fill_log_table([plain, _corrected()], time.time())
    assert t.item(0, 2).data(log_page.CORRECTION_ROLE) is None
    assert t.item(1, 2).data(log_page.CORRECTION_ROLE) == (
        "Lowered to 10 and cut to 0.5 s: their longest pulse")
    assert t.rowHeight(1) > t.rowHeight(0)
    assert "their longest pulse" in t.item(1, 2).toolTip()
    t.resize(700, 300)
    assert not t.grab().isNull()                                 # the delegate paints it
    p._fill_log_table([plain, plain], time.time())               # a reused row shrinks back
    assert t.rowHeight(1) == t.rowHeight(0)


def test_the_log_page_has_its_steps_icon_and_sidebar_place():
    import ui_components
    from ui import icons, page_steps
    ui = ui_components.OscGoesPurrrUI
    assert ui._NAV_ICONS["Log"] == "activity" and "activity" in icons.ICON_NAMES
    assert page_steps.for_page("Log") and page_steps.for_page("System Log") == ()
    assert "Log" in ui._NAV_TIPS
    from ui.views.dashboard import DashboardMixin
    assert DashboardMixin._FEATURE_VIEW_ANY["Log"] == ("feature_friends", "feature_pishock")


# --- what an action came through, and what a hold plays (Statistics counts them) --------

def test_a_touch_zone_names_the_zone_that_fired(store):
    import stats_events
    from settings.pishock import clean_zones
    h, router = avatar_host({"zones": [clean_zones(
        {"name": "Touch zones", "op": "vibrate", "intensity": 15, "duration_ms": 500,
         "zones": [{"param": "Contact/Neck", "shockers": "all"},
                   {"param": "Contact/ThighL", "shockers": "all"}]})]})
    router.tick()
    store.update_parameter("Contact/Neck", True)
    store.update_parameter("Contact/Neck", False)
    router.tick()
    [e] = records(h, who=el.AVATAR)
    assert e.via == "Touch zones · Neck"
    assert e.text == "Your avatar (Touch zones · Neck): vibrate 15 · 0.5 s on Collar"
    counted = stats_events.StatsEvents(None)
    counted.count(e)
    [you] = counted.lifetime_view()["people"]
    assert you["name"] == "Your avatar"
    assert [(v["label"], v["ops"]["vibrate"]["n"]) for v in you["via"]] == [
        ("Touch zones · Neck", 1)]


def test_your_avatars_unarmed_shock_hold_is_the_vibrate_it_plays(store):
    h, router = avatar_host({"continuous": [clean_continuous(
        {"param": "Prox", "threshold": 0.0, "min_int": 10, "max_int": 50, "op": "shock",
         "shockers": "all"})]})
    h.pishock_engine.is_armed = False
    store.update_parameter("Prox", 0.5)
    router.tick()
    [e] = records(h, who=el.AVATAR)
    assert (e.op, e.asked) == ("hold", "vibrate") and not e.stands_out
    assert "vibrate 30 (shocks aren't armed)" in e.text


def _me_host():
    from controllers.friends_me import MeLink
    h = Host()
    h.friends_link = MeLink(h, h.friends_link)
    h.set_friends_selected("friend", ME)
    h._my_state = h._build_my_state()
    h._me_tick()
    return h


def test_what_you_send_yourself_says_whether_your_menu_or_party_mode_sent_it():
    h = _me_host()
    h.pishock_engine.is_armed = True
    h._friends_on_osc("OGP/Friend/Shock", True)               # your avatar menu
    h._friends_on_osc("OGP/Friend/Shock", False)
    [got] = records(h, who=ME, dir=el.IN, kind=el.SHOCK)
    assert (got.op, got.via) == ("shock", el.VIA_MENU)
    assert {e.via for e in records(h, who=ME, dir=el.OUT, kind=el.SHOCK)} == {el.VIA_MENU}
    assert h.party_shock([(ME, 0)], "vibrate", 0.5, 500) == 1   # Party Mode
    assert records(h, who=ME, dir=el.IN)[0].via == el.VIA_PARTY
    assert h.friend_shock(ME, [0], 0.5, 0.5, "beep")            # the page
    assert records(h, who=ME, dir=el.IN)[0].via == ""


def test_a_warned_shock_from_your_menu_still_says_so_when_it_fires():
    h = _me_host()
    h.pishock_engine.is_armed = True
    h._friend_menu.warning = True
    h._friends_on_osc("OGP/Friend/Shock", True)
    warned = records(h, who=ME, dir=el.IN, kind=el.SHOCK)
    assert [(e.op, e.via) for e in warned] == [("warning", el.VIA_MENU)]
    h._pump_friend_holds(time.monotonic() + 5)                  # the warning is over
    fired = records(h, who=ME, dir=el.IN, op="shock")     # one per shocker it warned on
    assert fired and {e.via for e in fired} == {el.VIA_MENU}


def test_a_friend_never_says_what_they_sent_it_from():
    # their own menu or Party Mode isn't told over the link
    h = Host()
    h.befriend(A, shock=True)
    h.pishock_engine.is_armed = True
    h._friends_on_event("message", A, proto.make_shock("v1", [0], 0.5, 0.5))
    [e] = records(h, kind=el.SHOCK, who=A)
    assert e.via == ""


def test_a_friends_hold_says_what_it_plays_and_their_let_go_names_the_shocker():
    h = Host()
    h.befriend(A, shock=True)
    h._friends_on_event("message", A, proto.make_cmd({}, None, holds={0: ("vibrate", 0.5)}))
    h._pump_friend_holds(time.monotonic())
    [held] = records(h, who=A, op="hold")
    assert (held.asked, held.on) == ("vibrate", ("Collar",))
    h._friends_on_event("message", A, proto.make_cmd({}, None, holds={}))
    h._pump_friend_holds(time.monotonic())
    [gone] = records(h, who=A, op="let-go")
    assert gone.on == ("Collar",) and gone.text == "Alex let go of Collar"
