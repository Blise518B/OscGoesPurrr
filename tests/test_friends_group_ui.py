"""A group on the Friends panel, headless (friends_panel.py): its members
box shows only the members -- never every friend, the list gets long
(Blise's call, 2026-10-29) -- takes a friend's row dropped on it, you
included, and a chip's × takes one out."""

import sys

import pytest
from PySide6.QtCore import QMimeData, QPointF, Qt
from PySide6.QtGui import QDropEvent
from PySide6.QtWidgets import QApplication

import ui_components as uc
from settings.friends import ME
from ui.layout_helpers import vbox
from ui.views.friends_list import MIME_FRIEND, _members_text
from ui.widgets import Card

A, B, C = "a" * 64, "b" * 64, "c" * 64


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


def friend(fid, nick, me=False):
    return {"id": fid, "nick": nick, "linked": True, "rtt": 20.0, "path": "direct",
            "driving_me": False, "others": [], "sync": True, "me": me,
            "my_levels": {}, "my_override": (), "my_patterns": {}, "theirs": None}


def group_st(members):
    friends = [friend(ME, "Blise", me=True), friend(A, "Mika"), friend(B, "Kiko"),
               friend(C, "Nova")]
    return {"friends": friends,
            "groups": [{"id": "g1", "name": "Us", "members": list(members)}],
            "selected": {"kind": "group", "id": "g1"}}


def panel(st):
    ui = uc.OscGoesPurrrUI.__new__(uc.OscGoesPurrrUI)
    ui.controller = Stub()
    ui.controller.get_friends_status = lambda: st
    ui.views = {}
    ui.refresh_friends = lambda: None
    ui._friends_big = False
    ui._panel_card = Card()
    ui._panel_lay = vbox(0, 0)
    ui._panel_card.setLayout(ui._panel_lay)
    ui._panel_w = {}
    ui._rebuild_panel(st)
    ui._update_panel(st)
    return ui


def chips(zone):
    return [zone._flow.itemAt(i).widget().text() for i in range(zone._flow.count() - 1)]


def drop(zone, fid):
    mime = QMimeData()
    mime.setData(MIME_FRIEND, fid.encode())
    zone.dropEvent(QDropEvent(QPointF(4, 4), Qt.CopyAction, mime, Qt.LeftButton, Qt.NoModifier))


def test_only_the_members_show_and_a_dropped_friend_joins(qapp):
    ui = panel(group_st([ME, A]))
    zone = ui._panel_w["members"]
    assert chips(zone) == ["Blise (you)  ×", "Mika  ×"]       # Kiko and Nova aren't listed
    drop(zone, B)
    assert ui.controller.calls[-1] == ("set_group_member", "g1", B, True)
    drop(zone, A)                                              # already in: nothing
    assert ui.controller.calls[-1] == ("set_group_member", "g1", B, True)


def test_a_chips_x_takes_one_out_and_the_box_follows(qapp):
    ui = panel(group_st([ME, A]))
    zone = ui._panel_w["members"]
    zone._flow.itemAt(1).widget().click()
    assert ui.controller.calls[-1] == ("set_group_member", "g1", A, False)
    ui._update_panel(group_st([A, C]))
    assert chips(zone) == ["Mika  ×", "Nova  ×"]


def test_an_empty_group_says_where_members_come_from(qapp):
    zone = panel(group_st([]))._panel_w["members"]
    assert chips(zone) == []
    assert "Drag a friend here" in zone._flow.itemAt(0).widget().text()


def test_a_group_rows_count_says_whether_you_are_in_it():
    assert _members_text([A, B]) == "2 friends"
    assert _members_text([ME, A]) == "you + 1 friend"
    assert _members_text([ME]) == "just you"
    assert _members_text([]) == "0 friends"
