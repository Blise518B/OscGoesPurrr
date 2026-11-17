"""Shock, Vibrate and Beep switched off separately, headless:

  * the Shockers page: each shocker card's three switches reach the
    controller, rest its Test button, and grey a behaviour's chip for a
    shocker that has that behaviour's op off;
  * a friend's panel shows THEIR shockers' switches on your side of it --
    buttons of ops switched off there are greyed, and say why;
  * your side has no per-friend share any more (Blise's call, 2026-11-17):
    a friend's, a group's and the web remote's panel are about them, and
    each shocker's own limits on the Shockers page are what every friend
    gets.
"""

import sys

import pytest
from PySide6.QtWidgets import QApplication, QLabel, QPushButton

import ui_components as uc
from ui.layout_helpers import vbox
from ui.views.shocker_card import ShockerCard
from ui.widgets import Card

from test_friend_shockers_ui import Stub as PanelStub, friend
from test_pishock_page import Stub as PageStub, page

A, B = "a" * 64, "b" * 64


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication(sys.argv[:1])


# ---- the Shockers page --------------------------------------------------------

def _chips(zone):
    return {b.text().split("  ")[0]: b.isChecked() for b in zone.findChildren(QPushButton)
            if b.property("role") == "chip"}


def test_a_shockers_three_switches_reach_the_controller_and_rest_its_test(qapp):
    ui, _root = page(qapp)
    ctl, ops_off, base = ui.controller, {}, ui.controller.get_pishock_status

    def set_op(sid, op, on):
        now = set(ops_off.get(str(sid), []))
        (now.discard if on else now.add)(op)
        ops_off[str(sid)] = sorted(now)
        ctl.calls.append(("set_pishock_shocker_op", sid, op, on))

    ctl.set_pishock_shocker_op = set_op
    ctl.get_pishock_status = lambda: dict(base(), ops_off={k: v for k, v in ops_off.items() if v})
    ui.refresh_pishock_status()
    card = ui._pishock_cards[24325]
    assert set(card.ops.chips) == {"shock", "vibrate", "beep"}
    assert all(c.isChecked() for c in card.ops.chips.values())       # all on to start
    card.ops.chips["shock"].setChecked(False)
    assert ("set_pishock_shocker_op", 24325, "shock", False) in ctl.calls
    card = ui._pishock_cards[24325]
    assert not card.ops.chips["shock"].isChecked()
    assert not card.tests["shock"].isEnabled() and card.tests["vibrate"].isEnabled()


def test_a_behaviour_greys_the_chip_of_a_shocker_with_its_op_off(qapp):
    ui, _root = page(qapp)
    ctl, base = ui.controller, ui.controller.get_pishock_status
    ctl.rules["triggers"][0]["shockers"] = [24325, 24326]
    ctl.get_pishock_status = lambda: dict(base(), ops_off={"24326": ["vibrate"]})
    ui.refresh_pishock_status()
    headpat = next(w for w in ui._pishock_behaviours if w["kind"] == "triggers")
    zone = headpat["card"].zone
    assert _chips(zone) == {"Collar": True, "Shocker 24326": False}    # a vibrate behaviour
    assert "Vibrate is switched off on its card" in next(
        b for b in zone.findChildren(QPushButton) if b.text().startswith("Shocker 24326")).toolTip()
    headpat["op"].button(1).click()                                   # Shock now
    assert _chips(zone) == {"Collar": True, "Shocker 24326": True}
    assert ctl.calls[-1][0] == "rule" and ctl.calls[-1][3]["op"] == "shock"


def test_a_shockers_switches_explain_themselves(qapp):
    ui, _root = page(qapp)
    tip = ui._pishock_cards[24325].ops.chips["shock"].toolTip()
    assert "Shock on this shocker" in tip and "whoever sends it" in tip


# ---- a friend's panel: their switches on your side of it -----------------------------

def _card():
    return ShockerCard("1 · Collar", "yellow", on_fire=lambda *a: None, on_hold=lambda *a: None,
                       on_release=lambda: None, on_stop=lambda: None)


def test_an_op_switched_off_there_is_greyed_and_does_nothing(qapp):
    fired = []
    card = ShockerCard("1 · Collar", "yellow", on_fire=lambda *a: fired.append(a),
                       on_hold=lambda *a: None, on_release=lambda: None, on_stop=lambda: None)
    card.set_rules({"vibrate", "beep"})
    t = card._tiles
    assert not t["shock"].isEnabled() and not t["warn"].isEnabled()
    assert not card._sliders["shock"].isEnabled() and not card._dice_btn.isEnabled()
    assert t["vibrate"].isEnabled() and t["beep"].isEnabled() and t["stop"].isEnabled()
    card._tap("shock")
    card._tap("vibrate")
    assert [a[0] for a in fired] == ["vibrate"]


def test_a_friends_cards_follow_what_their_status_says(qapp):
    f = friend(A, "Mika", ["Collar", "Thigh"])
    f["theirs"].update(shocker_ops=[["vibrate"], ["shock", "vibrate", "beep"]])
    ui = _panel({"friends": [f], "groups": [], "selected": {"kind": "friend", "id": A},
                 "shockers_on": True})
    c1, c2 = ui._panel_w["shockers"]
    assert not c1._tiles["shock"].isEnabled() and c2._tiles["shock"].isEnabled()
    party = ui._panel_w["party"]                         # what any of them lets through
    assert party.card._ops == {"shock", "vibrate", "beep"}


def test_a_friends_cards_stop_at_the_caps_their_status_gives(qapp):
    # with Separate limits for friends on their side, their caps are the
    # friends' (lower) ones: the sliders and durations never promise more
    f = friend(A, "Mika", ["Collar"])
    f["theirs"].update(shocker_caps=[(10, 8, 500)], max_intensity=10, max_vibrate=8,
                       max_pulse_ms=500)
    ui = _panel({"friends": [f], "groups": [], "selected": {"kind": "friend", "id": A},
                 "shockers_on": True})
    c1, = ui._panel_w["shockers"]
    assert c1._sliders["shock"].maximum() == 10 and c1._sliders["vibrate"].maximum() == 8
    assert max(c1._durations()) <= 500


# ---- your side: no per-friend share ---------------------------------------------------

def _panel(st, ui=None):
    if ui is None:
        ui = uc.OscGoesPurrrUI.__new__(uc.OscGoesPurrrUI)
        ui.controller = PanelStub()
        ui.views = {}
        ui.refresh_friends = lambda: None
        ui._friends_big = False
        ui._build_friend_board = lambda fid: None
        ui._update_friend_board = lambda: None
        ui._panel_card = Card()
        ui._panel_lay = vbox(0, 0)
        ui._panel_card.setLayout(ui._panel_lay)
        ui._panel_w = {}
    ui._rebuild_panel(st)
    ui._update_panel(st)
    return ui


def _texts(ui):
    return {w.text() for w in ui._panel_card.findChildren(QLabel)}


def test_no_panel_has_a_share_section_any_more(qapp):
    """A friend's (online or not), a group's and the web remote's panel: no
    YOUR SHOCKERS - WHAT THEY MAY DO, and an old file's "share" changes
    nothing on screen."""
    fa, fb = friend(A, "Mika", ["Collar"]), friend(B, "Kiko", ["Collar"])
    fa.update(shock=True, share={"shock": False, "max": 5})        # left behind in an old file
    off = dict(fb, linked=False, theirs=None)
    web = {"on": True, "toys": True, "shock": True, "params": False, "guests": [],
           "share": {"cont": False}}
    for st in ({"friends": [fa], "groups": [], "selected": {"kind": "friend", "id": A}},
               {"friends": [off], "groups": [], "selected": {"kind": "friend", "id": B}},
               {"friends": [fa, fb], "groups": [{"id": "g1", "name": "Pups", "members": [A, B]}],
                "selected": {"kind": "group", "id": "g1"}},
               {"friends": [], "groups": [], "selected": {"kind": "web", "id": "__web__"},
                "web": web}):
        ui = _panel(dict(st, shockers_on=True))
        assert "share" not in ui._panel_w
        assert not any("WHAT THEY MAY DO" in t and "SHOCKERS" in t for t in _texts(ui))
    c1, = _panel({"friends": [fa], "groups": [], "selected": {"kind": "friend", "id": A},
                  "shockers_on": True})._panel_w["shockers"]
    assert c1._tiles["shock"].isEnabled()                  # only their own switches count


# ---- the sender sees why a button is greyed --------------------------------------------

def test_a_greyed_button_says_why_under_the_name_and_on_hover(qapp):
    card = _card()
    card.set_rules({"vibrate", "beep"}, why={"shock": "Shock is switched off on their side"})
    assert not card._tiles["shock"].isEnabled()
    assert card._tiles["shock"].toolTip() == "Shock is switched off on their side"
    assert not card._why_line.isHidden()
    assert card._why_line.text() == "Shock is switched off on their side."
    card.set_rules({"shock", "vibrate", "beep"})
    assert card._why_line.isHidden() and "Shock at this strength" in card._tiles["shock"].toolTip()


def test_a_friends_card_and_party_say_why_from_their_status(qapp):
    f = friend(A, "Mika", ["Collar", "Thigh"])
    f["theirs"].update(shocker_ops=[["vibrate", "beep"], ["vibrate", "beep"]],
                       shocker_off=[["shock"], []])
    ui = _panel({"friends": [f], "groups": [], "selected": {"kind": "friend", "id": A},
                 "shockers_on": True})
    c1, c2 = ui._panel_w["shockers"]
    assert c1._why_line.text() == "Shock is switched off on their side."
    assert c2._why_line.text() == "They don't let you shock."
    party = ui._panel_w["party"]                          # two different reasons
    assert party.card._why == {"shock": "None of them lets you shock"}



# ---- a shocker that can't warn greys Warning (Blise's call, 2026-11-14) ----------------

def test_a_shocker_that_cant_warn_greys_warning_and_sends_none(qapp):
    fired = []
    card = ShockerCard("1 · Collar", "yellow", on_fire=lambda *a: fired.append(a),
                       on_hold=lambda *a: None, on_release=lambda: None, on_stop=lambda: None)
    card._warn_picked(2)                                   # Mid, picked before
    card.set_rules({"shock"}, warn_ok=False,
                   why={"warn": "Can't warn: vibrate and beep are both off on their side",
                        "vibrate": "Vibrate is switched off on their side"})
    t = card._tiles
    assert not t["warn"].isEnabled() and t["shock"].isEnabled()
    assert t["warn"].toolTip() == "Can't warn: vibrate and beep are both off on their side"
    assert "Can't warn: vibrate and beep are both off on their side" in card._why_line.text()
    card._warn_picked(1)                                   # nothing to pick while it can't
    card._tap("shock")
    assert fired[-1][0] == "shock" and fired[-1][3] == 0   # no warning asked for
    card.set_rules({"shock", "vibrate", "beep"})           # it can again: Mid comes back
    assert t["warn"].isEnabled() and card._warn == 2


def test_their_status_greys_warning_where_vibrate_and_beep_are_off(qapp):
    f = friend(A, "Mika", ["Collar", "Thigh"])
    f["theirs"].update(shocker_ops=[["shock"], ["shock", "vibrate", "beep"]],
                       shocker_off=[["vibrate", "beep"], []])
    ui = _panel({"friends": [f], "groups": [], "selected": {"kind": "friend", "id": A},
                 "shockers_on": True})
    c1, c2 = ui._panel_w["shockers"]
    assert not c1._tiles["warn"].isEnabled() and c2._tiles["warn"].isEnabled()
    assert c1._tiles["warn"].toolTip() == "Can't warn: vibrate and beep are both off on their side"
    party = ui._panel_w["party"]                           # one of them can: the party can
    assert party.card._warn_ok
