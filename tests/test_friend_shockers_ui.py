"""A friend's and a group's shockers on the Friends panel, headless
(friends_shockers.py): the cards' Party boxes and the Party panel stay one,
Stop all stops each shocker, a rebuild keeps how they were set, a group's
Party lists every member's shockers, and pausing rests Operate."""

import sys

import pytest
from PySide6.QtWidgets import QApplication

import ui_components as uc
from ui.layout_helpers import vbox
from ui.widgets import Card

A, B = "a" * 64, "b" * 64


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication(sys.argv[:1])


class Stub:
    def __init__(self):
        self.calls = []

    def __getattr__(self, name):
        if name.startswith("__"):
            raise AttributeError(name)
        return lambda *a, **k: self.calls.append((name,) + a)


def friend(fid, nick, shockers, armed=True, paused=False):
    return {"id": fid, "nick": nick, "linked": True, "rtt": 20.0, "path": "direct",
            "driving_me": False, "others": [], "sync": True, "me": False,
            "my_levels": {}, "my_override": (), "my_patterns": {},
            "theirs": {"toys": [], "allow_toys": False, "allow_shock": True,
                       "shockers": shockers, "armed": armed, "max_intensity": 60,
                       "max_vibrate": 80, "max_pulse_ms": 5000, "max_hold_s": 10.0,
                       "strength": 1.0, "outputs": {}, "paused": paused, "off": False}}


def panel(st, ui=None):
    if ui is None:
        ui = uc.OscGoesPurrrUI.__new__(uc.OscGoesPurrrUI)
        ui.controller = Stub()
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


def friend_st(*friends, sel=A):
    return {"friends": list(friends), "groups": [], "selected": {"kind": "friend", "id": sel}}


def test_party_boxes_on_the_cards_and_the_party_panel_are_one(qapp):
    ui = panel(friend_st(friend(A, "Mika", ["Collar", "Thigh"])))
    w = ui._panel_w
    c1, c2 = w["shockers"]
    party = w["party"]
    assert party.isHidden()                         # until a shocker is ticked for it
    c1.party_box.setChecked(True)
    c2.party_box.setChecked(True)
    assert not party.isHidden() and party.ticked() == [(A, 0), (A, 1)]
    party._tick((A, 0), False)                      # unticked in the party's own list
    assert not c1.party_box.isChecked()
    party.card._tap("shock")
    assert ui.controller.calls[-1][:2] == ("party_shock", [(A, 1)])
    c2.party_box.setChecked(False)
    assert party.isHidden()


def test_one_shocker_has_no_party_and_no_stop_all(qapp):
    ui = panel(friend_st(friend(A, "Mika", ["Collar"])))
    w = ui._panel_w
    assert w["party"] is None and w["shockers"][0].party_box is None


def test_stop_all_stops_each_shocker(qapp):
    ui = panel(friend_st(friend(A, "Mika", ["Collar", "Thigh"])))
    for card in ui._panel_w["shockers"]:
        card.stop()
    stops = [c for c in ui.controller.calls if c[0] == "friend_stop"]
    assert stops == [("friend_stop", A, [0]), ("friend_stop", A, [1])]


def test_a_rebuild_keeps_the_cards_and_the_party_as_they_were(qapp):
    st = friend_st(friend(A, "Mika", ["Collar", "Thigh"]))
    ui = panel(st)
    w = ui._panel_w
    w["shockers"][0]._mode_picked(1)                # Remote
    w["shockers"][1].party_box.setChecked(True)
    w["party"]._mode_picked(2)                      # Round Robin
    ui._friends_panel_key = None
    ui = panel(st, ui)
    w = ui._panel_w
    assert w["shockers"][0]._use == "remote"
    assert w["party"].ticked() == [(A, 1)] and w["party"]._mode == "robin"
    assert w["shockers"][1].party_box.isChecked() and not w["party"].isHidden()


def test_a_groups_party_lists_every_members_shockers_it_may_use(qapp):
    fa, fb = friend(A, "Mika", ["Collar", "Thigh"]), friend(B, "Kiko", ["Collar"], armed=False)
    fc = friend("c" * 64, "Nope", ["Collar"])
    fc["theirs"]["allow_shock"] = False
    st = {"friends": [fa, fb, fc],
          "groups": [{"id": "g1", "name": "Pups", "members": [A, B, "c" * 64]}],
          "selected": {"kind": "group", "id": "g1"}}
    ui = panel(st)
    party = ui._panel_w["party"]
    assert party.ticked() == [(A, 0), (A, 1), (B, 0)]      # all of them, ticked
    strip = ui._panel_w["state"]
    assert "1 of 2 ARMED" in strip.head.text() and "Mika" in strip.rest.text()


def test_paused_rests_operate_and_says_why(qapp):
    ui = panel(friend_st(friend(A, "Mika", ["Collar"], paused=True)))
    w = ui._panel_w
    card = w["shockers"][0]
    assert not card._tiles["shock"].isEnabled() and card._tiles["stop"].isEnabled()
    assert w["state"].head.text() == "Paused"
    ui._update_panel(friend_st(friend(A, "Mika", ["Collar"])))
    assert card._tiles["shock"].isEnabled() and "ARMED" in w["state"].head.text()
