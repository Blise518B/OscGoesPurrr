"""A friend's VRChat account on the Friends page, headless
(friends_account.py): the people in your instance as chips, dropped onto a
friend's row to link them; the linked row's second line; and the friend's
panel field with its picker folded out inside the window -- never for Me
or the Web remote, never in control mode."""

import sys

import pytest
from PySide6.QtCore import QMimeData, QPointF, Qt
from PySide6.QtGui import QDragEnterEvent, QDropEvent
from PySide6.QtWidgets import QApplication, QWidget

import ui_components as uc
from settings.friends import ME
from ui.layout_helpers import vbox
from ui.views.friends_account import HERE, MIME_VRC, vrc_payload
from ui.views.friends_list import MIME_FRIEND
from ui.widgets import Card

A, B = "a" * 64, "b" * 64
RIN = "usr_0000000a-0000-4000-8000-00000000000a"
KAI = "usr_0000000c-0000-4000-8000-00000000000c"


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication(sys.argv[:1])


def friend(fid, nick, me=False, **kw):
    f = {"id": fid, "nick": nick, "linked": True, "rtt": 20.0, "path": "direct",
         "driving_me": False, "others": [], "sync": True, "me": me, "toys": True,
         "shock": True, "params": True, "my_levels": {}, "my_override": (),
         "my_patterns": {}, "theirs": None, "vrc": "", "vrc_name": "", "here": False}
    f.update(kw)
    return f


class Stub:
    def __init__(self):
        self.calls = []
        self.log_on = True
        self.people = [{"id": RIN, "name": "Rin", "friend": A},
                       {"id": KAI, "name": "Kai", "friend": ""}]
        self.choices = {"log": True, "state": "ok", "instance": list(self.people),
                        "vrcx": [], "vrcx_more": 0, "vrcx_state": "", "vrcx_count": 0,
                        "vrcx_installed": True}

    def status(self, selected=None):
        friends = [friend(ME, "Blise", me=True),
                   friend(A, "Mika", vrc=RIN, vrc_name="Rin", here=True),
                   friend(B, "Kiko")]
        return {"friends": friends, "groups": [], "params_on": True,
                "selected": selected or {}, "online": True,
                "vrchat": {"log": self.log_on, "state": "ok" if self.log_on else "off",
                           "people": self.people if self.log_on else [],
                           "vrcx": "", "vrcx_count": 0}}

    def get_friends_status(self):
        return self.status()

    def get_vrchat_choices(self, query="", limit=40):
        self.calls.append(("choices", query))
        return dict(self.choices)

    def __getattr__(self, name):
        if name.startswith("__"):
            raise AttributeError(name)
        return lambda *a, **k: self.calls.append((name,) + a)


def column(qapp, stub=None):
    ui = uc.OscGoesPurrrUI.__new__(uc.OscGoesPurrrUI)
    ui.controller = stub or Stub()
    ui.views = {}
    root = QWidget()
    ui.window = root
    lay = vbox(0, 0)
    root.setLayout(lay)
    lay.addWidget(ui._build_friends_list_column())
    ui.refresh_friends = lambda: None
    st = ui.controller.status()
    ui._rebuild_friend_rows(st)
    ui._update_friend_rows(st)
    root.show()
    qapp.processEvents()
    return ui, root


def panel(qapp, fid, stub=None, big=False):
    ui = uc.OscGoesPurrrUI.__new__(uc.OscGoesPurrrUI)
    ui.controller = stub or Stub()
    st = ui.controller.status({"kind": "friend", "id": fid})
    ui.controller.get_friends_status = lambda: st
    ui.views = {}
    ui.refresh_friends = lambda: None
    ui._friends_big = big
    ui._panel_card = Card()
    ui._panel_lay = vbox(0, 0)
    ui._panel_card.setLayout(ui._panel_lay)
    ui._panel_w = {}
    ui._rebuild_panel(st)
    ui._update_panel(st)
    return ui, st


def drop_on(widget, uid, name, mime_type=MIME_VRC):
    handler = next(c for c in widget.children() if type(c).__name__ == "VrcDrop")
    mime = QMimeData()
    mime.setData(mime_type, vrc_payload(uid, name) if mime_type == MIME_VRC else uid.encode())
    ev = QDropEvent(QPointF(5, 5), Qt.CopyAction, mime, Qt.LeftButton, Qt.NoModifier)
    return handler.eventFilter(widget, ev)


def chips(ui):
    flow = ui._vrc_chips
    return [flow.itemAt(i).widget() for i in range(flow.count())
            if flow.itemAt(i).widget() is not None and flow.itemAt(i).widget().property("role") == "chip"]


def test_the_people_in_your_instance_are_chips(qapp):
    ui, root = column(qapp)
    got = chips(ui)
    assert [c.text() for c in got] == ["Rin", "Kai"]
    assert got[0].isChecked() and "Linked to Mika" in got[0].toolTip()   # in Mika's colour
    assert not got[1].isChecked() and "Drag onto a friend" in got[1].toolTip()
    got[1].click()                                       # a click links nothing
    assert not got[1].isChecked()
    assert ui._vrc_log_switch.isChecked()


def test_a_chip_dropped_on_a_friends_row_links_them(qapp):
    ui, root = column(qapp)
    assert drop_on(ui._friend_rows[B]["btn"], KAI, "Kai")
    assert ("link_friend_vrchat", B, KAI, "Kai") in ui.controller.calls


def test_the_rows_drop_takes_nothing_else_and_me_has_none(qapp):
    ui, root = column(qapp)
    row = ui._friend_rows[B]["btn"]
    handler = next(c for c in row.children() if type(c).__name__ == "VrcDrop")
    mime = QMimeData()
    mime.setData(MIME_FRIEND, A.encode())                # a friend's row dragged over it
    enter = QDragEnterEvent(QPointF(5, 5).toPoint(), Qt.CopyAction, mime, Qt.LeftButton,
                            Qt.NoModifier)
    assert not handler.eventFilter(row, enter)
    me_row = ui._friend_rows[ME]["btn"]
    assert not any(type(c).__name__ == "VrcDrop" for c in me_row.children())
    assert ui._friend_rows[ME]["vrc"] is None


def test_a_linked_row_shows_their_vrchat_name_and_in_your_instance(qapp):
    ui, root = column(qapp)
    line = ui._friend_rows[A]["vrc"]
    assert line.isVisible() and line.vrc_name.full_text() == "Rin"
    assert line.vrc_here.isVisible() and line.vrc_here.text() == HERE
    assert ui._friend_rows[A]["name"].text() == "Mika"            # the nickname first
    assert not ui._friend_rows[B]["vrc"].isVisible()              # Kiko isn't linked
    st = ui.controller.status()
    st["friends"][1]["here"] = False                              # Rin left
    ui._update_friend_rows(st)
    assert line.isVisible() and not line.vrc_here.isVisible()


def test_with_the_log_off_the_list_says_how_to_switch_it_on(qapp):
    stub = Stub()
    stub.log_on = False
    ui, root = column(qapp, stub)
    assert chips(ui) == [] and not ui._vrc_log_switch.isChecked()
    assert ui._vrc_state_lbl.text().startswith("Off. On, the people in your VRChat instance")
    ui._vrc_log_switch.setChecked(True)
    assert ("set_friends_vrc_log", True) in stub.calls


def test_the_panel_field_and_its_picker(qapp):
    ui, st = panel(qapp, B)
    v = ui._panel_w["vrc"]
    assert v["name"].text() == "Not linked yet" and v["pick"].text() == "Link…"
    assert v["picker"].isHidden() and v["unlink"].isHidden()
    v["pick"].click()                                    # folds out inside the panel
    assert not v["picker"].isHidden() and v["pick"].text() == "Close"
    flow = v["picker"].here_flow
    texts = [flow.itemAt(i).widget().text() for i in range(flow.count())]
    assert texts == ["Rin (Mika)", "Kai"]                 # whose a linked one is
    assert v["picker"].here_hint.isHidden()
    flow.itemAt(1).widget().click()                      # pick Kai
    assert ("link_friend_vrchat", B, KAI, "Kai") in ui.controller.calls
    assert ui._vrc_pick_for is None                      # done: it folds away


def test_the_picker_says_how_when_the_log_is_off_and_imports_vrcx(qapp):
    stub = Stub()
    stub.choices.update(log=False, state="off", instance=[])
    ui, st = panel(qapp, B, stub)
    v = ui._panel_w["vrc"]
    v["pick"].click()
    assert v["picker"].here_flow.count() == 0
    assert "Read VRChat's log" in v["picker"].here_hint.text()
    assert "Import from VRCX to pick" in v["picker"].vrcx_hint.text()
    stub.choices.update(vrcx=[{"id": RIN, "name": "Rin", "friend": A}], vrcx_count=1,
                        vrcx_state="ok")
    v["picker"].vrcx_btn.click()
    assert ("import_vrcx_friends",) in stub.calls
    chip = v["picker"].vrcx_flow.itemAt(0).widget()
    assert chip.text() == "Rin (Mika)" and "Linked to Mika" in chip.toolTip()
    assert v["picker"].vrcx_hint.isHidden()
    assert v["picker"].vrcx_btn.text() == "Import again"
    v["picker"].search.setText("ri")
    assert ("choices", "ri") in stub.calls


def test_without_vrcx_the_button_says_so(qapp):
    stub = Stub()
    stub.choices.update(vrcx_installed=False)
    ui, st = panel(qapp, B, stub)
    v = ui._panel_w["vrc"]
    v["pick"].click()
    btn = v["picker"].vrcx_btn
    assert btn.text() == "VRCX isn't on this PC" and not btn.isEnabled()
    assert "VRCX isn't on this PC" in v["picker"].vrcx_hint.text()


def test_a_linked_friends_panel(qapp):
    ui, st = panel(qapp, A)
    v = ui._panel_w["vrc"]
    assert v["name"].text() == "Rin" and not v["here"].isHidden()
    assert v["pick"].text() == "Change…" and not v["unlink"].isHidden()
    v["unlink"].click()
    assert ("unlink_friend_vrchat", A) in ui.controller.calls
    assert drop_on(v["box"], KAI, "Kai")                 # dragged onto the box
    assert ("link_friend_vrchat", A, KAI, "Kai") in ui.controller.calls


def test_no_field_for_me_or_in_control_mode(qapp):
    ui, st = panel(qapp, ME)
    assert "vrc" not in ui._panel_w
    ui, st = panel(qapp, A, big=True)
    assert "vrc" not in ui._panel_w


def test_the_vrchat_name_is_below_smaller_and_muted(qapp):
    """Blise's call (2026-11-14): below the nickname, never next to it, a
    little smaller and less bright -- the theme's muted label; only a linked
    friend's row grows for it."""
    from ui.views.friends_account import ROW_H
    from ui.theme import build_qss
    ui, root = column(qapp)
    root.setStyleSheet(build_qss())
    qapp.processEvents()
    linked, plain = ui._friend_rows[A], ui._friend_rows[B]
    line = linked["vrc"]
    assert line.vrc_name.property("muted") == "true" and not line.vrc_name.property("hint")
    for w in (line.vrc_name, linked["name"]):
        w.ensurePolished()
    assert line.vrc_name.font().pixelSize() < linked["name"].font().pixelSize() or (
        line.vrc_name.fontInfo().pixelSize() < linked["name"].fontInfo().pixelSize())
    # below: the line is a row of its own under the name, not beside it
    rows = linked["btn"].layout()
    assert rows.indexOf(line) == rows.count() - 1
    assert linked["btn"].minimumHeight() > ROW_H
    assert plain["btn"].minimumHeight() == ROW_H and not plain["vrc"].isVisible()
