"""The shocker buttons' two faces (shocker_layout.py; Blise's call,
2026-11-15): PiShock's own panel by default, OpenShock's card with Live
control at a switch -- one app setting for every panel, remembered, undone
by Ctrl+Z without asking. A layout is only a face: the same press sends
the same message, their shockers' switches grey the same things with the
same words, and Live control is a hold like PiShock's Remote mode -- let go
when the finger lifts or the updates stop."""

import sys
import time

import pytest
from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QApplication

import remote_protocol as proto
import settings_history as sh
import shocker_layout as layout
from test_friend_shockers_ui import A, Stub, friend, friend_st, panel
from ui.views.openshock_card import OpenShockCard
from ui.views.shock_party import ShockParty
from ui.views.shocker_card import PARTY_CAPS, ShockerCard

CAPS = (40, 60, 5000)                  # their shock cap, vibrate cap, longest pulse


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication(sys.argv[:1])


def cards(caps=CAPS, **kw):
    """A PiShock card and an OpenShock card, each recording what it sends."""
    out = []
    for cls in (ShockerCard, OpenShockCard):
        calls = []
        card = cls("1 · Collar", "yellow",
                   on_fire=lambda *a, c=calls: c.append(("fire",) + a),
                   on_hold=lambda *a, c=calls: c.append(("hold",) + a),
                   on_release=lambda c=calls: c.append(("release",)),
                   on_stop=lambda c=calls: c.append(("stop",)), **kw)
        card.set_caps(caps, 10.0)
        out.append((card, calls))
    return out


def message(fire) -> dict:
    """What a card's on_fire goes out as (friends_control.friend_shock)."""
    _f, op, it, ln, wms, wi = fire
    return proto.make_shock("x", [0], it, ln, op, "vibrate" if wms > 0 else "", wi, wms)


def mouse(widget, kind, y):
    pos = QPointF(widget.width() / 2, y)
    QApplication.sendEvent(widget, QMouseEvent(kind, pos, pos, Qt.LeftButton,
                                               Qt.LeftButton if kind != QEvent.MouseButtonRelease
                                               else Qt.NoButton, Qt.NoModifier))


# ---------------------------------------------------------------------------
# the setting
# ---------------------------------------------------------------------------

def test_the_default_is_pishock_and_anything_else_reads_as_it():
    from settings.app import DEFAULT_APP_SETTINGS, DESCRIBE, is_setting
    assert DEFAULT_APP_SETTINGS[layout.SETTING_KEY] == layout.DEFAULT == layout.PISHOCK
    assert is_setting(layout.SETTING_KEY) and DESCRIBE[layout.SETTING_KEY] == "Shocker buttons"
    for bad in (None, "", "OpenShock", 3, "pi"):
        assert layout.clean(bad) == "pishock"
    assert layout.clean("openshock") == "openshock"
    assert layout.LAYOUTS == ("pishock", "openshock")


from controllers.friends_control import FriendsControlMixin  # noqa: E402


class _Host(FriendsControlMixin):
    """The friends facade's two calls on an app settings dict."""

    def __init__(self):
        self.saved, self.refreshed = {}, 0

    def get_app_setting(self, key, default=None):
        return self.saved.get(key, default)

    def set_app_setting(self, key, value):
        self.saved[key] = value

    def _friends_refresh_ui(self):
        self.refreshed += 1


def test_the_switch_is_one_remembered_setting_and_redraws_the_panels():
    h = _Host()
    assert h.get_shocker_layout() == "pishock"          # nothing saved yet
    h.set_shocker_layout("openshock")
    assert h.saved == {"shocker_layout": "openshock"} and h.refreshed == 1
    assert h.get_shocker_layout() == "openshock"
    h.set_shocker_layout("openshock")                   # the same: nothing to do
    assert h.refreshed == 1
    h.set_shocker_layout("nonsense")                    # reads as the default
    assert h.saved["shocker_layout"] == "pishock" and h.refreshed == 2


def test_the_friends_status_says_which():
    from test_friends_facade import Host
    h = Host()
    h.get_app_setting = lambda key, default=None: {"shocker_layout": "openshock"}.get(key, default)
    assert h.get_friends_status()["shocker_layout"] == "openshock"


@pytest.fixture
def hist():
    class Clock:
        t = 100.0

        def __call__(self):
            return self.t
    clock = Clock()
    h = sh.SettingsHistory(clock=clock)
    old = sh.activate(h)
    yield h, clock
    sh.activate(old)


def test_ctrl_z_takes_the_switch_back_without_asking(hist, monkeypatch, tmp_path):
    import settings.app as app_mod
    from controllers.history_facade import HistoryFacade
    monkeypatch.setattr(app_mod, "APP_SETTINGS_FILE", tmp_path / "app_settings.json")
    h, clock = hist
    app = app_mod.AppSettingsManager()

    class Host(HistoryFacade):
        refreshed = 0

        def get_app_setting(self, key, default=None):
            return app.get(key, default)

        def _friends_refresh_ui(self):
            Host.refreshed += 1

    host = Host()
    h.on_restored(app, host._history_app_restored)
    clock.t += 5
    app.set("shocker_layout", "openshock")
    assert h.can_undo()
    r = h.undo()                                  # no ask: it loosens nothing
    assert r.status == sh.DONE and "Shocker buttons" in r.text
    assert app.get("shocker_layout") == "pishock" and Host.refreshed == 1
    assert h.redo().status == sh.DONE and app.get("shocker_layout") == "openshock"


# ---------------------------------------------------------------------------
# the panel
# ---------------------------------------------------------------------------

def test_the_panel_is_built_in_the_layout_the_switch_says(qapp):
    st = friend_st(friend(A, "Mika", ["Collar", "Thigh"]))
    ui = panel(st)
    w = ui._panel_w
    assert all(type(c) is ShockerCard for c in w["shockers"])           # the default
    assert type(w["party"].card) is ShockerCard
    switch = w["layout_switch"]
    assert switch.group.checkedId() == 0                               # PiShock picked
    assert switch.toolTip()                                            # it explains itself
    switch.group.button(1).click()                                     # OpenShock
    assert ("set_shocker_layout", "openshock") in ui.controller.calls
    st["shocker_layout"] = "openshock"
    ui._friends_panel_key = None
    ui = panel(st, ui)
    w = ui._panel_w
    assert all(type(c) is OpenShockCard for c in w["shockers"])
    assert type(w["party"].card) is OpenShockCard
    assert w["layout_switch"].group.checkedId() == 1


def test_the_panel_key_rebuilds_on_a_switch():
    import ui_components as uc
    st = friend_st(friend(A, "Mika", ["Collar"]))
    before = uc.OscGoesPurrrUI._panel_key(st)
    st["shocker_layout"] = "openshock"
    assert uc.OscGoesPurrrUI._panel_key(st) != before
    group = {"friends": [], "groups": [{"id": "g", "name": "G", "members": []}],
             "selected": {"kind": "group", "id": "g"}}
    before = uc.OscGoesPurrrUI._panel_key(group)
    group["shocker_layout"] = "openshock"
    assert uc.OscGoesPurrrUI._panel_key(group) != before


def test_each_layout_keeps_its_own_memory_and_lets_go_on_a_switch(qapp):
    st = friend_st(friend(A, "Mika", ["Collar"]))
    st["shocker_layout"] = "openshock"
    ui = panel(st)
    card = ui._panel_w["shockers"][0]
    card.intensity.setValue(33)
    card.live_tag.setChecked(True)
    card._live_level(20)                                   # Live control holding
    assert ui.controller.calls[-1][0] == "friend_hold"
    st["shocker_layout"] = "pishock"                       # switched while holding
    ui._friends_panel_key = None
    ui = panel(st, ui)
    assert ("friend_release", A, [0]) in ui.controller.calls   # let go first
    ui._panel_w["shockers"][0]._mode_picked(1)                  # PiShock: Remote
    st["shocker_layout"] = "openshock"
    ui._friends_panel_key = None
    ui = panel(st, ui)
    card = ui._panel_w["shockers"][0]
    assert card.intensity.value() == 33 and card.live() and card._holding == ""
    st["shocker_layout"] = "pishock"
    ui._friends_panel_key = None
    ui = panel(st, ui)
    assert ui._panel_w["shockers"][0]._use == "remote"


def test_openshock_keeps_stop_all_even_for_one_shocker(qapp):
    st = friend_st(friend(A, "Mika", ["Collar"]))
    ui = panel(st)
    assert not _stop_all(ui)                               # PiShock's card has its STOP
    st["shocker_layout"] = "openshock"
    ui._friends_panel_key = None
    ui = panel(st, ui)
    stop = _stop_all(ui)
    assert stop
    stop[0].click()
    assert ("friend_stop", A, [0]) in ui.controller.calls


def _stop_all(ui):
    from PySide6.QtWidgets import QPushButton
    return [b for b in ui._panel_card.findChildren(QPushButton) if b.text() == "Stop all"]


def test_a_groups_party_takes_the_layout_too(qapp):
    fa = friend(A, "Mika", ["Collar"])
    st = {"friends": [fa], "groups": [{"id": "g1", "name": "Pups", "members": [A]}],
          "selected": {"kind": "group", "id": "g1"}, "shocker_layout": "openshock"}
    ui = panel(st)
    party = ui._panel_w["party"]
    assert type(party.card) is OpenShockCard and ui._panel_w["layout_switch"].group.checkedId() == 1
    party.card._press("vibrate")
    assert ui.controller.calls[-1][:3] == ("party_shock", [(A, 0)], "vibrate")


# ---------------------------------------------------------------------------
# the same press, the same message
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("op,strength,ms", [
    ("shock", 1, 300), ("shock", 25, 1000), ("shock", 40, 5000),
    ("vibrate", 1, 2000), ("vibrate", 45, 300), ("vibrate", 60, 4000),
    ("beep", 1, 300), ("beep", 1, 3000),
])
def test_both_layouts_send_the_same_message_for_the_same_press(qapp, op, strength, ms):
    (pi, pi_calls), (os_, os_calls) = cards()
    if op != "beep":
        pi._sliders[op].setValue(strength)
    pi._dur["vibrate" if op == "beep" else op] = ms
    pi._tap(op)
    os_.intensity.setValue(strength)
    os_.duration.setValue(ms)
    os_._press(op)
    assert message(pi_calls[-1]) == message(os_calls[-1])


def test_a_partys_press_is_the_same_in_both_layouts(qapp):
    got = []
    for cls in (ShockerCard, OpenShockCard):
        calls = []
        party = ShockParty("Party", "yellow", on_fire=lambda *a, c=calls: c.append(a),
                           on_hold=lambda *a: None, on_release=lambda *a: None,
                           on_stop=lambda *a: None, card_cls=cls)
        party.set_targets([(A, 0, "Collar", "yellow"), (A, 1, "Thigh", "yellow")])
        if cls is ShockerCard:
            party.card._sliders["shock"].setValue(70)
            party.card._dur["shock"] = 2000
            party.card._tap("shock")
        else:
            party.card.intensity.setValue(70)
            party.card.duration.setValue(2000)
            party.card._press("shock")
        pairs, op, it, ms, wms, _wi = calls[-1]
        got.append((pairs, op, it, ms, wms))
    assert got[0] == got[1] == ([(A, 0), (A, 1)], "shock", pytest.approx(69 / 99), 2000, 0)


def test_holds_go_the_same_way_as_pishocks_remote_mode(qapp):
    (pi, pi_calls), (os_, os_calls) = cards()
    pi._mode_picked(1)                                    # Remote
    pi._sliders["vibrate"].setValue(30)
    pi._press("vibrate")
    os_.live_tag.setChecked(True)                         # Live control, Vibrate
    os_.pad._moved(0.5)                                   # half way up: 30 of their 60
    assert pi_calls[-1] == os_calls[-1] == ("hold", "vibrate", pytest.approx(29 / 59))
    pi._unpress("vibrate")
    os_.pad.let_go()
    assert pi_calls[-1] == os_calls[-1] == ("release",)


# ---------------------------------------------------------------------------
# OpenShock's card: their caps, their reasons
# ---------------------------------------------------------------------------

def test_the_dials_stop_at_their_max(qapp):
    (_pi, _), (card, calls) = cards(caps=(25, 60, 800))
    assert (card.intensity.minimum(), card.intensity.maximum()) == (1, 60)
    assert (card.duration.minimum(), card.duration.maximum()) == (300, 800)
    card.intensity.setValue(500)
    card.duration.setValue(20000)
    assert card.intensity.value() == 60 and card.duration.value() == 800
    card._press("shock")                       # the shock stops at its own cap
    assert calls[-1][1:4] == ("shock", 1.0, 1.0)
    card._press("vibrate")
    assert calls[-1][1:4] == ("vibrate", 1.0, 1.0)
    assert card._lim_text["int"].text() == "Shock 25% · Vibrate 60%"
    assert card._lim_text["dur"].text() == "0.8 s"
    card.set_caps((40, 40, 15000))
    assert card._lim_text["int"].text() == "40%" and card.duration.maximum() == 15000
    # a pulse shorter than OpenShock's 0.3 s: just theirs
    card.set_caps((40, 40, 100))
    assert (card.duration.minimum(), card.duration.maximum()) == (100, 100)


def test_the_card_starts_where_the_percentage_was(qapp):
    (pi, _), (card, _) = cards(caps=PARTY_CAPS)
    assert card.intensity.value() == layout.INTENSITY_DEFAULT == 25
    assert card.duration.value() == layout.DURATION_DEFAULT_MS
    card.set_caps((40, 60, 5000))
    assert card.intensity.value() == 15                   # 25 % of their 60


def test_a_greyed_button_says_why_like_the_pishock_card(qapp):
    (pi, _), (card, calls) = cards()
    why = {"shock": "Shock is switched off on their side",
           "beep": "They don't let you beep", "warn": proto.WARN_OFF_WHY}
    for c in (pi, card):
        c.set_rules({"vibrate"}, why, warn_ok=False)
    for op in ("shock", "beep"):
        assert not card.buttons[op].isEnabled() and not card.live_types[op].isEnabled()
        assert card.buttons[op].toolTip() == why[op] == pi._tiles[op].toolTip()
    assert card.buttons["vibrate"].isEnabled()
    # the line under the name: the same reasons -- OpenShock has no Warning,
    # so its reason is left out there
    assert card._why_line.text() == pi._why_line.text() ==         "Shock is switched off on their side. They don't let you beep."
    card._press("shock")
    card._press("beep")
    assert calls == []                                    # nothing greyed goes out
    card._press("vibrate")
    assert calls[-1][1] == "vibrate"


def test_paused_rests_every_button_and_the_pad(qapp):
    (_pi, _), (card, calls) = cards()
    card.live_tag.setChecked(True)
    card._live_level(30)
    card.set_blocked(True)
    assert calls[-1] == ("release",)
    assert not any(b.isEnabled() for b in card.buttons.values())
    assert not card.pad.isEnabled()
    card._press("vibrate")
    card._live_level(40)
    assert calls[-1] == ("release",)
    card.set_blocked(False)
    assert card.pad.isEnabled()


def test_a_shock_goes_without_a_warning(qapp):
    # OpenShock has no Warning button, and nothing makes a friend warn first
    # any more (the per-friend share is gone, 2026-11-17)
    (_pi, _), (card, calls) = cards()
    assert "warning" not in card.buttons["shock"].toolTip()
    card.intensity.setValue(30)
    card._press("shock")
    _f, op, it, _ln, wms, _wi = calls[-1]
    assert (op, wms) == ("shock", 0) and it == pytest.approx(29 / 39)
    assert proto.read_shock(message(calls[-1]))["warn"] == ""


def test_pressing_a_running_button_again_stops_it(qapp):
    (_pi, _), (card, calls) = cards()
    card._press("vibrate")
    assert card.buttons["vibrate"].isChecked() and "again to stop" in card.buttons["vibrate"].toolTip()
    card._press("vibrate")
    assert calls[-1] == ("stop",) and not card.buttons["vibrate"].isChecked()
    card._press("beep")
    card._ran_out()                                       # its Duration is over
    assert not card.buttons["beep"].isChecked()


# ---------------------------------------------------------------------------
# Live control
# ---------------------------------------------------------------------------

def test_live_control_follows_the_finger_and_lets_go(qapp):
    (_pi, _), (card, calls) = cards()
    card.resize(340, 560)
    card.show()
    card.live_tag.setChecked(True)
    pad = card.pad
    top, bottom = pad._travel()
    mid = (top + bottom) / 2
    mouse(pad, QEvent.MouseButtonPress, top)              # the top: their strongest
    assert calls[-1] == ("hold", "vibrate", 1.0)
    mouse(pad, QEvent.MouseMove, mid)
    assert calls[-1] == ("hold", "vibrate", pytest.approx(29 / 59))   # 30 of their 60
    n = len(calls)
    mouse(pad, QEvent.MouseMove, mid)                    # no change: nothing sent
    assert len(calls) == n
    card._live_pick("shock")                             # another op, still held:
    assert calls[-1] == ("hold", "shock", pytest.approx(19 / 39))  # the same spot, half their 40
    assert calls.count(("hold", "shock", pytest.approx(19 / 39))) == 1
    mouse(pad, QEvent.MouseMove, bottom)                 # 0: nothing held
    assert calls[-1] == ("release",)
    mouse(pad, QEvent.MouseMove, mid)                    # back up, still pressed
    assert calls[-1][:2] == ("hold", "shock")
    mouse(pad, QEvent.MouseButtonRelease, mid)
    assert calls[-1] == ("release",) and pad.strength() == 0
    assert calls.count(("release",)) == 2
    card.hide()


def test_live_control_is_always_there(qapp):
    # holds aren't a friend's to be refused any more: LIVE never greys
    (_pi, _), (card, calls) = cards()
    card.set_rules({"shock", "vibrate", "beep"})
    assert card.live_tag.isEnabled()
    card.live_tag.setChecked(True)
    card._live_pick("vibrate")
    card._live_level(30)
    assert card.live() and calls[-1][:2] == ("hold", "vibrate")


def test_a_switched_off_op_can_not_be_held_live(qapp):
    (_pi, _), (card, calls) = cards()
    card.live_tag.setChecked(True)
    card._live_pick("shock")
    card._live_level(10)
    assert calls[-1][:2] == ("hold", "shock")
    card.set_rules({"vibrate", "beep"}, why={"shock": "They don't let you shock"})
    assert calls[-1] == ("release",) and not card.pad.isEnabled()
    card._live_level(30)
    assert calls[-1] == ("release",)
    card._live_pick("shock")                              # greyed: stays where it was
    card._live_pick("vibrate")
    assert card.pad.isEnabled()


def test_a_live_hold_follows_and_stops_when_the_updates_stop():
    """The receiver's side: Live control's hold is a friend's hold -- each
    change reaches the shocker, the engine's caps hold, and once the
    sender goes quiet (a lost link) it ends by itself."""
    from test_friends_facade import A as FA, _held_levels, real_shocker_host
    h, _eng, link, clock = real_shocker_host()
    h.befriend(FA, shock=True)
    t = time.monotonic()
    for level in (0.25, 0.5, 1.0):                         # the finger moving up
        h._friends_on_event("message", FA, proto.make_cmd({}, None, holds={0: ("vibrate", level)}))
        h._pump_friend_holds(time.monotonic())
        clock["t"] += 0.1
    levels = _held_levels(link)
    changes = [x for i, x in enumerate(levels) if i == 0 or x != levels[i - 1]]
    want = [proto.shock_values(v, 0.0, 40, 2000)[0] for v in (0.25, 0.5, 1.0)]
    assert changes == want and want[-1] == 40              # every change, capped at their 40
    assert link.sent[-1] != (11, "end")
    h._pump_friend_holds(t + proto.DRIVE_STALE_S + 0.5)    # no update since: quiet
    assert link.sent[-1] == (11, "end")


def test_a_live_hold_of_an_op_switched_off_there_never_reaches_the_shocker():
    """Even a sender that ignores the greyed button: the receiver refuses."""
    from test_friends_facade import A as FA, Host
    h = Host()
    h.befriend(FA, shock=True)
    h.pishock_engine.switched = {11: {"shock"}}
    h._friends_on_event("message", FA, proto.make_cmd({}, None, holds={0: ("shock", 0.8)}))
    h._pump_friend_holds(time.monotonic())
    assert h.pishock_engine.holds == []


# ---------------------------------------------------------------------------
# OpenShock's numbers
# ---------------------------------------------------------------------------

def test_the_maths_is_the_pishock_cards():
    for cap in (1, 2, 40, 100):
        for v in range(1, cap + 1, max(1, cap // 7)):
            assert layout.to_fraction(v, cap) == (1.0 if cap <= 1 else (v - 1) / (cap - 1))
    assert layout.length_fraction(1000, 5000) == pytest.approx(900 / 4900)
    assert layout.length_fraction(9000, 5000) == 1.0 and layout.length_fraction(500, 100) == 0.0
    assert layout.duration_range(15000) == (300, 15000)
    assert layout.snap_duration(1234, 5000) == 1200 and layout.snap_duration(50, 5000) == 300
    assert layout.snap_duration(99999, 5000) == 5000
    assert [layout.live_strength(y, 40) for y in (0, 0.25, 0.5, 0.98, 1, -3, 7)] == \
        [40, 30, 20, 1, 0, 40, 0]
