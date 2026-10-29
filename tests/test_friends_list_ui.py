"""The Friends page's left column, headless: a friend dragged onto a group
joins it, right-clicking a group or a friend opens its menu, and the
invite link / ID copy what they say."""

import sys

import pytest
from PySide6.QtCore import QMimeData, QPoint, QPointF, Qt
from PySide6.QtGui import QContextMenuEvent, QDropEvent, QGuiApplication
from PySide6.QtWidgets import QApplication, QWidget

import ui_components as uc
from ui.layout_helpers import vbox
from ui.views.friends_list import MIME_FRIEND

A, B = "a" * 64, "b" * 64


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication(sys.argv[:1])


class Stub:
    def __init__(self):
        self.calls = []
        self.groups = [{"id": "g1", "name": "Night crew", "members": [A]}]

    def status(self):
        friends = [{"id": f, "nick": n, "toys": True, "shock": True, "params": True,
                    "linked": True, "rtt": 20.0, "driving_me": False}
                   for f, n in ((A, "Mika"), (B, "Kiko"))]
        return {"friends": friends, "groups": self.groups, "selected": {}, "params_on": True}

    def get_friends_status(self):
        return self.status()

    def set_group_member(self, gid, fid, on):
        self.calls.append(("member", gid, fid, on))

    def friends_invite_message(self, kind):
        self.calls.append(("invite", kind))
        return f"invite-{kind}"

    def __getattr__(self, name):
        if name.startswith("__"):
            raise AttributeError(name)
        return lambda *a, **k: None


def column(qapp):
    ui = uc.OscGoesPurrrUI.__new__(uc.OscGoesPurrrUI)
    ui.controller = Stub()
    ui.views = {}
    root = QWidget()
    ui.window = root
    lay = vbox(0, 0)
    root.setLayout(lay)
    lay.addWidget(ui._build_friends_list_column())
    ui.refresh_friends = lambda: None
    ui._rebuild_friend_rows(ui.controller.status())
    root.show()
    qapp.processEvents()
    return ui, root


def test_a_friend_dropped_on_a_group_joins_it(qapp):
    ui, root = column(qapp)
    row = ui._group_rows["g1"]
    # Qt only delivers a drop while a real drag runs: hand it to the group's
    # drop handler the way Qt would
    drop_handler = next(c for c in row.children() if type(c).__name__ == "_GroupDrop")

    def drop(fid):
        mime = QMimeData()
        mime.setData(MIME_FRIEND, fid.encode())
        ev = QDropEvent(QPointF(5, 5), Qt.CopyAction, mime, Qt.LeftButton, Qt.NoModifier)
        assert drop_handler.eventFilter(row, ev)

    drop(B)
    assert ui.controller.calls == [("member", "g1", B, True)]
    drop(A)                                                # already in it: nothing to do
    assert len(ui.controller.calls) == 1
    root.hide()


def test_right_click_opens_a_groups_and_a_friends_menu(qapp, monkeypatch):
    ui, root = column(qapp)
    opened = []
    monkeypatch.setattr(ui, "_group_row_menu", lambda gid, *a: opened.append(("group", gid)))
    monkeypatch.setattr(ui, "_friend_row_menu", lambda fid, *a: opened.append(("friend", fid)))
    # rebuilt so the rows connect to the patched menus
    ui._rebuild_friend_rows(ui.controller.status())
    for target, row in (("group", ui._group_rows["g1"]), ("friend", ui._friend_rows[A]["name"])):
        ev = QContextMenuEvent(QContextMenuEvent.Mouse, QPoint(3, 3), row.mapToGlobal(QPoint(3, 3)))
        QApplication.sendEvent(row, ev)
    assert opened == [("group", "g1"), ("friend", A)]       # even on the name inside the row
    root.hide()


def test_the_invite_link_copies_with_the_lifetime_picked(qapp):
    ui, root = column(qapp)
    ui._friends_invite_group.button(2).click()             # 1 week
    ui._friends_invite_btn.click()
    assert ("invite", "week") in ui.controller.calls
    assert QGuiApplication.clipboard().text() == "invite-week"
    assert ui._friends_invite_btn.text().startswith("Copied")
    ui._friends_my_id = A
    ui._friends_copy_btn.setEnabled(True)
    ui._friends_copy_btn.click()
    assert QGuiApplication.clipboard().text() == A
    root.hide()


def test_add_a_friend_folds_out_by_itself_only_while_you_have_none(qapp):
    ui = uc.OscGoesPurrrUI.__new__(uc.OscGoesPurrrUI)
    ui.controller = Stub()
    ui.views = {}
    root = QWidget()
    ui.window = root
    lay = vbox(0, 0)
    root.setLayout(lay)
    lay.addWidget(ui._build_friends_list_column())
    ui.refresh_friends = lambda: None
    me = {"id": "__me__", "nick": "Blise", "me": True, "toys": True, "shock": True,
          "params": True, "linked": True, "rtt": None, "driving_me": False}
    alone = {"friends": [me], "groups": [], "selected": {}, "params_on": False}
    ui._rebuild_friend_rows(alone)
    root.show()
    qapp.processEvents()
    assert ui._friends_add_fold.isVisible()                  # nobody yet: open
    assert ui._friends_none.isVisible()                      # you alone count as nobody
    assert "__me__" in ui._friend_rows                       # but you're on the list
    ui._friends_add_toggle.click()
    assert not ui._friends_add_fold.isVisible()              # it closes when asked
    ui._friends_add_toggle.click()
    ui._rebuild_friend_rows({**alone, "friends": [me] + ui.controller.status()["friends"]})
    qapp.processEvents()
    assert not ui._friends_add_fold.isVisible()              # the first friend folds it away
    ui._friends_add_toggle.click()
    ui._rebuild_friend_rows({**alone, "friends": [me] + ui.controller.status()["friends"]})
    assert ui._friends_add_fold.isVisible()                  # opened by hand, it stays open
    ui._friends_add_edit.setText(A)
    ui._friends_add_btn.click()                              # sent (the stub says no problem)
    assert not ui._friends_add_fold.isVisible()
    root.hide()


def test_your_own_row_has_no_menu(qapp, monkeypatch):
    ui, root = column(qapp)
    opened = []

    class Menu:                     # a real QMenu would sit there, modal
        def __init__(self, _anchor):
            opened.append(self)

        def addAction(self, _text):  # noqa: N802
            return type("A", (), {"triggered": type("S", (), {"connect": lambda *_: None})()})()

        def exec(self, _pos):
            pass

    monkeypatch.setattr("ui.views.friends_list.QMenu", Menu)
    ui._friend_row_menu("__me__", "Blise (you)", root, QPoint(1, 1), True)
    assert opened == []
    ui._friend_row_menu(A, "Mika", root, QPoint(1, 1), False)
    assert len(opened) == 1
    root.hide()


def test_each_column_icon_explains_its_own_column(qapp):
    # Blise's ask (2026-10-28): one text for all three read the same on each
    ui, root = column(qapp)
    tips = {what: head.toolTip() for what, head in ui._friends_heads.items()}
    assert "Toys" in tips["toys"] and "bolt" not in tips["toys"]
    assert "Shockers" in tips["shock"] and "arm shocks" in tips["shock"]
    assert "Avatar Remote" in tips["params"] and "toy" not in tips["params"]
    assert len(set(tips.values())) == 3
    root.hide()


def test_the_web_remote_row_sits_right_after_you(qapp):
    ui, root = column(qapp)
    calls = []
    ui.controller.set_friends_web_permission = lambda what, on: calls.append((what, on))
    ui.controller.set_friends_selected = lambda kind, sid: calls.append(("pick", kind, sid))
    me = {"id": "__me__", "nick": "Blise", "me": True, "toys": True, "shock": True,
          "params": True, "linked": True, "rtt": None, "driving_me": False}
    web = {"on": True, "toys": True, "shock": False, "params": False, "driving": False,
           "selected": False,
           "guests": [{"id": B, "nick": "Sam", "rtt": 40.0, "driving": False}]}
    st = {**ui.controller.status(), "web": web}
    st["friends"] = [me] + st["friends"]
    ui._rebuild_friend_rows(st)
    rows = [ui._friends_rows_lay.itemAt(i).widget() for i in range(ui._friends_rows_lay.count())]
    assert rows[0] is ui._friend_rows["__me__"]["btn"] and rows[1] is ui._web_row["btn"]
    ui._update_friend_rows(st)
    assert ui._web_row["ping"].text() == "1 on"
    assert ui._web_row["ping"].toolTip() == "On your web remote now: Sam"   # who, on hover
    ui._web_row["toys"].click()
    ui._web_row["shock"].click()
    ui._web_row["btn"].click()
    assert calls == [("toys", False), ("shock", True), ("pick", "web", "__web__")]
    assert "params" in ui._web_row                           # Avatar Remote is on here
    ui._rebuild_friend_rows({**st, "web": None})
    assert ui._web_row is None                               # no link, no row
    root.hide()


def test_the_web_remote_link_copies_from_the_add_fold(qapp):
    ui, root = column(qapp)
    ui.controller.friends_web_link_message = lambda: "web-link"
    ui._friends_web_btn.setEnabled(True)
    ui._friends_web_btn.click()
    assert QGuiApplication.clipboard().text() == "web-link"
    assert ui._friends_web_btn.text().startswith("Copied")
    root.hide()


def test_add_a_friend_is_a_header_with_its_own_plus_and_its_fold_hangs_from_it(qapp):
    """Blise's ask, 2026-10-29: the fold reads as the button's child -- a
    distinct + / − box at the header's left, and while open the header and
    the fold are one card (the header's bottom corners square off onto the
    fold's frame)."""
    ui, root = column(qapp)
    ui._set_friends_add_open(False)
    assert ui._friends_add_sign.text() == "+" and ui._friends_add_toggle.property("open") == "false"
    ui._friends_add_toggle.click()
    assert ui._friends_add_sign.text() == "−" and ui._friends_add_toggle.property("open") == "true"
    assert ui._friends_add_fold.objectName() == "addFold"
    assert ui._friends_add_fold.parentWidget() is ui._friends_add_toggle.parentWidget()
    assert ui._friends_add_toggle.parentWidget().layout().spacing() == 0     # they touch
    root.hide()
