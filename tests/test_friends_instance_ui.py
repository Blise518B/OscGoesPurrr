"""Only friends in my instance on the Friends page, headless: its switch
under Read VRChat's log and the line saying who may drive you, "not here"
on a refused friend's row (an unlinked one's points to linking), "from
anywhere" for their exception, the Web remote row's "not here", a
friend's Allow from anywhere and the Web remote panel's Allow the web
remote anyway -- those two shown only while the option is on."""

import pytest

from controllers.friends_common import WEB
from settings.friends import ME
from test_friends_account_ui import A, B, RIN, Stub, column, friend, panel, qapp  # noqa: F401
from ui.views.friends_account import (
    FROM_ANYWHERE, NOT_HERE, NOT_HERE_LINK, instance_line, row_tag,
)

C = "c" * 64
WEB_ENTRY = {"on": True, "toys": True, "shock": False, "params": False, "driving": False,
             "selected": False, "share": {}, "anyway": False,
             "guests": [{"id": "e" * 64, "nick": "Visitor", "rtt": None, "driving": False}]}


class InstanceStub(Stub):
    """The page's status with Only friends in my instance on: Mika (A) in
    your instance, Kiko (B) unlinked, Juno (C) linked but elsewhere."""

    def __init__(self, on=True, web_anyway=False):
        super().__init__()
        self.on, self.web_anyway = on, web_anyway

    def status(self, selected=None):
        st = super().status(selected)
        st["friends"][2].update(not_here=self.on)                       # Kiko, unlinked
        st["friends"].append(friend(C, "Juno", vrc="usr_0000000d-0000-4000-8000-00000000000d",
                                    vrc_name="Juno", not_here=self.on))
        st["instance"] = {"on": self.on, "web_anyway": self.web_anyway,
                          "web_blocked": self.on and not self.web_anyway}
        st["web"] = dict(WEB_ENTRY, anyway=self.web_anyway)
        return st


def test_the_switch_and_its_line(qapp):
    stub = InstanceStub()
    ui, root = column(qapp, stub)
    assert ui._inst_switch.isChecked()
    assert ui._inst_lbl.isVisible()
    assert ui._inst_lbl.text() == "Only friends in your instance can drive you - 1 of 3 can right now."
    ui._inst_switch.setChecked(False)
    assert ("set_friends_instance_only", False) in stub.calls
    stub.on = False
    ui._update_friend_rows(stub.status())
    assert not ui._inst_switch.isChecked() and not ui._inst_lbl.isVisible()
    root.hide()


def test_its_hover_text_says_it_switches_the_log_on(qapp):
    ui, root = column(qapp, InstanceStub())
    tip = ui._inst_switch.toolTip()
    assert "Only friends in my instance" in tip               # its title
    assert "also switches on Read VRChat's log" in tip and "Off by default" in tip
    root.hide()


def test_the_line_says_why_nobody_may_drive_you():
    st = InstanceStub().status()
    st["vrchat"]["log"] = False
    assert instance_line(st).startswith("Read VRChat's log is off")
    assert instance_line(st).endswith("no friend can drive you.")
    st["friends"][1]["anywhere"] = True
    assert instance_line(st).endswith("only the friend allowed from anywhere can drive you.")
    st["vrchat"].update(log=True, state="no_vrchat")
    assert instance_line(st).startswith("VRChat isn't running")


def test_rows_say_not_here_and_an_unlinked_one_points_to_linking(qapp):
    ui, root = column(qapp, InstanceStub())
    mika, kiko, juno = (ui._friend_rows[f]["vrc"] for f in (A, B, C))
    assert mika.vrc_here.isVisible() and not mika.vrc_tag.isVisible()     # here
    assert kiko.isVisible() and kiko.vrc_tag.text() == NOT_HERE_LINK      # unlinked: a line now
    assert "Link…" in kiko.vrc_tag.toolTip() and "Kiko" in kiko.vrc_tag.toolTip()
    assert juno.vrc_tag.text() == NOT_HERE and juno.vrc_tag.property("role") == "warning"
    assert juno.vrc_name.full_text() == "Juno"
    root.hide()


def test_rows_say_nothing_while_it_is_off(qapp):
    ui, root = column(qapp, InstanceStub(on=False))
    assert not ui._friend_rows[B]["vrc"].isVisible()                      # unlinked, no line
    assert not ui._friend_rows[C]["vrc"].vrc_tag.isVisible()
    assert ui._friend_rows[ME]["vrc"] is None                             # Me never has one
    root.hide()


def test_from_anywhere_on_the_row():
    f = friend(C, "Juno", vrc="usr_x", anywhere=True)
    assert row_tag(f, True)[0] == FROM_ANYWHERE
    assert row_tag(f, False)[0] == ""                  # nothing to say while it's off
    assert row_tag(dict(f, here=True), True)[0] == ""  # in your instance says it already


def test_the_web_remote_row_says_not_here(qapp):
    stub = InstanceStub()
    ui, root = column(qapp, stub)
    st = stub.status()
    st["friends"] = [friend(ME, "Blise", me=True)] + st["friends"][1:]
    ui._rebuild_friend_rows(st)
    ui._update_friend_rows(st)
    assert not ui._web_row["not_here"].isHidden() and ui._web_row["not_here"].text() == NOT_HERE
    stub.web_anyway = True
    ui._update_friend_rows(stub.status())
    assert ui._web_row["not_here"].isHidden()
    root.hide()


def test_a_friends_panel_has_allow_from_anywhere_only_while_it_is_on(qapp):
    stub = InstanceStub()
    ui, st = panel(qapp, C, stub)
    v = ui._panel_w["vrc"]
    assert not v["anywhere"].isHidden() and not v["anywhere"].isChecked()
    assert not v["not_here"].isHidden()
    v["anywhere"].setChecked(True)
    assert ("set_friend_anywhere", C, True) in stub.calls
    ui, st = panel(qapp, C, InstanceStub(on=False))
    assert ui._panel_w["vrc"]["anywhere"].isHidden()
    assert ui._panel_w["vrc"]["not_here"].isHidden()


def test_the_web_panel_has_its_own_switch(qapp):
    stub = InstanceStub()
    ui, st = panel(qapp, WEB, stub)
    st = stub.status({"kind": "web", "id": WEB})
    ui._rebuild_panel(st)
    ui._update_panel(st)
    w = ui._panel_w
    assert not w["anyway"].isHidden() and not w["anyway"].isChecked()
    assert not w["anyway_note"].isHidden()
    w["anyway"].setChecked(True)
    assert ("set_friends_web_anyway", True) in stub.calls
    stub.on = False
    st = stub.status({"kind": "web", "id": WEB})
    ui._update_panel(st)
    assert w["anyway"].isHidden() and w["anyway_note"].isHidden()


@pytest.mark.parametrize("text", [NOT_HERE, NOT_HERE_LINK, FROM_ANYWHERE])
def test_the_words_are_short(text):
    assert len(text) <= 40
