"""Home's rows for the shocker hub and the suits (ui/views/home_devices.py):
what each says, its switches and logo, that a row shows only while its
feature is switched on, and where it sits in the toy list -- switched on
and connected ones under the connected toys, the rest greyed at the bottom
under a small divider."""

import sys

import pytest

from PySide6.QtCore import QPoint
from PySide6.QtWidgets import QApplication, QVBoxLayout, QWidget

from ui import theme
from ui.views.device_frame import DeviceFrameMixin
from ui.views.home_devices import (
    HomeDeviceRow, bhaptics_row, brand_pixmap, owo_row, shockers_row,
)
from ui.views.shocker_switches import ArmSwitch


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication(sys.argv[:1])


def hub(**over):
    st = {"connected": True, "connecting": False, "last_error": "", "paused": False,
          "armed": False, "hub_name": "PiShock hub", "friends_may_use": True,
          "shockers": [{"id": 24325, "name": "Collar"}, {"id": 22}]}
    st.update(over)
    return st


# --- what a row says -----------------------------------------------------

def test_a_connected_hub_names_its_shockers():
    s = shockers_row(hub(), friends_on=True)
    assert s["connected"] and s["pill"] is None and s["share"] is True
    assert s["summary"] == "PiShock hub · Collar, Shocker 22"


def test_many_shockers_are_counted_not_listed():
    many = [{"id": i, "name": f"S{i}"} for i in range(5)]
    assert shockers_row(hub(shockers=many), True)["summary"].endswith("S0, S1, S2 +2")


def test_the_hub_row_says_armed_and_offline():
    # armed or not is Arm's own red words, never a second ARMED pill
    armed = shockers_row(hub(armed=True), True)
    assert armed["pill"] is None and armed["armed"] is True
    off = shockers_row(hub(connected=False, last_error="No hub on COM3"), True)
    assert off["pill"] == ("OFFLINE", "idle") and off["summary"] == "No hub on COM3"
    assert shockers_row(hub(connected=False, connecting=True), True)["summary"] \
        == "Connecting to the hub…"


def test_a_hub_without_a_usable_shocker_is_grey():
    """The hub alone isn't "connected": it needs a shocker it can use."""
    bare = shockers_row(hub(shockers=[]), True)
    assert not bare["connected"] and bare["pill"] == ("NO SHOCKER", "idle")
    assert bare["summary"] == "PiShock hub connected · no shocker paired yet"
    held = shockers_row(hub(shockers=[{"id": 1, "paused": True}]), True)
    assert not held["connected"] and held["pill"] == ("PAUSED IN PISHOCK", "idle")
    one = shockers_row(hub(shockers=[{"id": 1, "paused": True}, {"id": 2}]), True)
    assert one["connected"] and one["pill"] is None


def test_switched_off_it_is_connected_but_not_up():
    s = shockers_row(hub(armed=True, paused=True), True)
    assert s["connected"] and not s["enabled"] and not s["up"]
    assert s["pill"] is None                    # the switch says it; no ARMED
    assert shockers_row(hub(), True)["up"]


def test_a_hub_wears_its_firmwares_logo():
    assert shockers_row(hub(), True)["icon"] == "pishock"
    assert shockers_row(hub(hub_kind="openshock"), True)["icon"] == "openshock"
    unplugged = hub(connected=False, hub_kind="", openshock_shockers=[{"id": 7}])
    assert shockers_row(unplugged, True)["icon"] == "openshock"


def test_every_logo_is_there_in_colour_and_grey(qapp):
    for kind in ("pishock", "openshock", "bhaptics", "owo"):
        for grey in (False, True):
            pm = brand_pixmap(kind, grey)
            assert pm is not None and pm.width() == 64, (kind, grey)


def test_no_sharing_switch_without_friends():
    assert shockers_row(hub(), friends_on=False)["share"] is None


def test_the_hub_row_carries_arm_shocks_and_the_suits_dont():
    assert shockers_row(hub(), True)["armed"] is False
    assert shockers_row(hub(armed=True), True)["armed"] is True
    # whether or not the hub is there: it's a setting, kept either way
    assert shockers_row(hub(armed=True, connected=False), False)["armed"] is True
    assert bhaptics_row({"devices": [], "settings": {}}, True)["armed"] is None
    assert owo_row({"connected": True, "settings": {}}, True)["armed"] is None


def test_a_suit_shows_its_parts_and_lowest_battery():
    st = {"devices": [{"label": "TactSuit Pro", "battery": 80},
                      {"label": "Tactosy for arms", "battery": 35}],
          "settings": {"follow_owo": True}}
    s = bhaptics_row(st, owo_on=True)
    assert s["summary"] == "TactSuit Pro, Tactosy for arms · 🔋 35 %"
    assert s["share"] is True and s["pill"] is None
    assert bhaptics_row(st, owo_on=False)["share"] is None     # no OWO, no switch


def test_a_suit_that_was_let_go_says_so():
    s = bhaptics_row({"devices": [], "released": True, "settings": {}}, False)
    assert s["pill"] == ("OFFLINE", "idle")
    assert s["summary"] == "Let go - the bHaptics Player can have it"


def test_the_owo_row():
    st = {"connected": True, "paused": True, "settings": {"follow_bhaptics": False}}
    s = owo_row(st, bhaptics_on=True)
    assert s["summary"] == "Connected through My OWO" and s["icon"] == "owo"
    assert s["connected"] and not s["up"] and s["pill"] is None
    assert s["share"] is False
    assert owo_row({"connected": False, "wanted": True}, False)["summary"] == "Looking for My OWO…"


# --- the row widget ------------------------------------------------------

class _Dots(DeviceFrameMixin):
    pass


def make_row(with_arm=True):
    calls = []
    # "row" is no place ARM_ASKS_FROM names: this switch never asks
    arm = ArmSwitch("row", lambda on: calls.append(("arm", on))) if with_arm else None
    row = HomeDeviceRow("Shockers", theme.SHOCKERS_HUE, "pishock", "Friends may use them",
                        on_open=lambda: calls.append("open"),
                        on_power=lambda on: calls.append(("power", on)),
                        on_share=lambda on: calls.append(("share", on)),
                        apply_dot=_Dots()._apply_connect_dot, arm=arm)
    return row, calls


def test_the_arm_switch_shows_the_setting_and_reports_clicks(qapp):
    row, calls = make_row()
    row.set_state(shockers_row(hub(), True))
    assert not row.arm.isHidden() and not row.arm.isChecked() and calls == []
    assert row.arm.status.text() == "Shocks not armed"
    row.set_state(shockers_row(hub(armed=True), True))     # changed elsewhere
    assert row.arm.isChecked() and calls == []               # shown, not reported
    assert row.arm.status.text() == "Shocks armed" and row.arm.status.font().bold()
    row.arm.switch.click()
    assert calls == [("arm", False)]


def test_a_row_without_arm_text_has_no_arm_switch(qapp):
    row, _calls = make_row(with_arm=False)
    row.set_state(owo_row({"connected": True, "settings": {}}, True))
    assert row.arm is None


def test_armed_sits_beside_its_switch_then_sharing_then_on_off(qapp):
    """The state pill, Arm shocks with its red words right after the
    switch, then sharing, then On / Off (the Shockers page's order)."""
    row, _calls = make_row()
    lay = row.lines[0]                        # all on one line: the widest
    row._arrange(1)
    order = [lay.itemAt(i).widget() for i in range(lay.count())]
    at = [order.index(w) for w in (row.pill, row.arm, row.share, row.power)]
    assert at == sorted(at) and at[1] == at[0] + 1
    row._arrange(2)                           # narrower: Arm and sharing under the name
    second = [row.lines[1].itemAt(i).widget() for i in range(row.lines[1].count())]
    assert [w for w in second if w is not None] == [row.arm, row.share]
    assert row.lines[0].indexOf(row.power) >= 0
    inner = row.arm.layout()
    parts = [inner.itemAt(i).widget() for i in range(inner.count())]
    assert [w for w in parts if w is not None] == [row.arm.switch, row.arm.ask,
                                                   row.arm.status]


def test_offline_or_off_the_row_is_grey(qapp):
    row, _calls = make_row()
    row.set_state(shockers_row(hub(connected=False), True))
    assert row.bar.property("hue") == theme.OFFLINE_HUE
    assert not row.pill.isHidden() and row.power.isChecked()
    row.set_state(shockers_row(hub(), True))
    assert row.bar.property("hue") == theme.SHOCKERS_HUE and row.pill.isHidden()
    row.set_state(shockers_row(hub(paused=True), True))
    assert row.bar.property("hue") == theme.OFFLINE_HUE and not row.power.isChecked()


def test_the_on_off_switch(qapp):
    row, calls = make_row()
    row.set_state(shockers_row(hub(), True))
    assert row.power.isChecked() and calls == []
    row.power.click()
    row.set_state(shockers_row(hub(paused=True), True))
    row.power.click()
    assert calls == [("power", False), ("power", True)]


def test_the_switch_reports_clicks_but_not_refreshes(qapp):
    row, calls = make_row()
    row.set_state(shockers_row(hub(friends_may_use=False), True))
    assert not row.share.isChecked() and calls == []
    row.share.click()
    assert calls == [("share", True)]
    row.set_state(shockers_row(hub(), friends_on=False))
    assert row.share.isHidden()


def test_a_click_on_the_bar_opens_the_page(qapp):
    from PySide6.QtCore import QPoint, Qt
    from PySide6.QtTest import QTest
    row, calls = make_row()
    row.set_state(shockers_row(hub(), True))
    row.resize(700, 50)
    row.show()
    QTest.mouseClick(row.summary, Qt.LeftButton, Qt.NoModifier, QPoint(2, 2))
    row.hide()
    assert calls == ["open"]


# --- on Home -------------------------------------------------------------

import test_home_view as _home  # noqa: E402


class FakeController(_home.FakeController):
    def __init__(self, features, hub_on=True, bh_on=False, owo_on=True, **k):
        super().__init__(**k)
        self.features = {"feature_intiface": True, **features}
        self.hub_on, self.bh_on, self.owo_on = hub_on, bh_on, owo_on
        self.hub_paused = False
        self.calls = []

    def get_feature_enabled(self, key):
        return self.features.get(key, False)

    def get_pishock_status(self):
        return hub(connected=self.hub_on, paused=self.hub_paused,
                   armed=getattr(self, "armed", False))

    def set_pishock_armed(self, on):
        self.calls.append(("set_pishock_armed", on))
        self.armed = on

    def get_suits_status(self):
        bh = [{"label": "TactSuit Pro", "battery": 80}] if self.bh_on else []
        return {"bhaptics": {"devices": bh, "settings": {"follow_owo": True}},
                "owo": {"connected": self.owo_on, "settings": {"follow_bhaptics": True}}}

    def pishock_stop_all(self):
        self.calls.append("pishock_stop_all")
        self.hub_paused = True

    def pishock_resume(self):
        self.calls.append("pishock_resume")
        self.hub_paused = False

    def set_owo_option(self, key, value):
        self.calls.append((key, value))


class Host(_home._Host):
    def __init__(self, controller):
        self.opened = []
        super().__init__(controller)

    def select_view(self, name):
        self.opened.append(name)

    def listed(self):
        """Home's list top to bottom: toy names, row titles, divider captions."""
        names = {d["home"]["frame"]: n for n, d in self.device_ui_frames.items()}
        rows = {r: r.name.text() for r in self._home_rows()}
        dividers = {self._home_shockers_divider: "--SHOCKERS",
                    self._home_suits_divider: "--HAPTIC SUITS"}
        out = []
        lay = self.home_list_layout
        for i in range(lay.count()):
            w = lay.itemAt(i).widget()
            for table in (names, rows, dividers):
                if w in table:
                    out.append(table[w])
        return out


def home(features, **k):
    toys = {"Alpha": {"motor_count": 1}, "Bravo": {"motor_count": 1}}
    h = Host(FakeController(features, profiles=toys, connected={"Bravo"}, **k))
    h._refresh_home_devices()
    return h


ALL = {"feature_pishock": True, "feature_bhaptics": True, "feature_owo": True,
       "feature_friends": True}


def test_rows_show_only_while_their_feature_is_on(qapp):
    h = home({})
    assert h.listed() == ["Bravo", "Alpha"]
    h = home({"feature_pishock": True, "feature_owo": True})
    assert "bHaptics" not in h.listed()
    assert h._home_owo_row.share.isHidden()         # no bHaptics to follow
    assert h._home_shockers_row.share.isHidden()    # Friends is off


def test_connected_ones_go_under_the_connected_toys_the_rest_to_the_bottom(qapp):
    h = home(ALL)                       # hub and OWO connected, bHaptics not
    assert h.listed() == ["Bravo", "Shockers", "OWO", "Alpha",
                          "--HAPTIC SUITS", "bHaptics"]
    assert not h._home_suits_divider.isHidden()
    assert h._home_shockers_divider.isHidden()
    h.controller.hub_on, h.controller.bh_on = False, True
    h._refresh_home_devices()
    assert h.listed() == ["Bravo", "bHaptics", "OWO", "Alpha",
                          "--SHOCKERS", "Shockers"]
    assert h._home_suits_divider.isHidden()


def test_a_toy_change_keeps_the_rows_in_place(qapp):
    h = home(ALL)
    h.controller.connected = {"Alpha", "Bravo"}
    h.update_stored_devices_ui()
    assert h.listed() == ["Alpha", "Bravo", "Shockers", "OWO",
                          "--HAPTIC SUITS", "bHaptics"]
    h.build_stored_devices_ui()                     # a mode switch rebuilds the list
    h.update_stored_devices_ui()
    assert h.listed() == ["Alpha", "Bravo", "Shockers", "OWO",
                          "--HAPTIC SUITS", "bHaptics"]


def test_a_toy_that_reconnects_has_the_rows_under_it_at_once(qapp):
    """The list asks the controller who is connected -- the same answer it
    sorts by -- not each card's state from the last 1 Hz repaint. Bravo
    sorts after the toy that was already connected, so its stale card
    state would put the rows above it."""
    toys = {"Alpha": {"motor_count": 1}, "Bravo": {"motor_count": 1}}
    h = Host(FakeController(ALL, profiles=toys, connected={"Alpha"}))
    h._refresh_home_devices()
    h.controller.connected = {"Alpha", "Bravo"}
    h._reorder_device_frames()          # build_device_list_ui, before that repaint
    assert h.listed() == ["Alpha", "Bravo", "Shockers", "OWO",
                          "--HAPTIC SUITS", "bHaptics"]


def test_an_unchanged_list_is_left_alone(qapp, monkeypatch):
    """The 1 Hz heartbeat and Home's 2 Hz refresh don't move anything that
    is already in place."""
    h = home(ALL)
    lay = h.home_list_layout
    moved = []
    take, insert = lay.takeAt, lay.insertWidget     # the real ones, still called

    def spy_take(i):
        moved.append(i)
        return take(i)

    def spy_insert(*a):
        moved.append(a)
        return insert(*a)

    monkeypatch.setattr(lay, "takeAt", spy_take, raising=False)
    monkeypatch.setattr(lay, "insertWidget", spy_insert, raising=False)
    h.update_stored_devices_ui()
    h._refresh_home_devices()
    h._place_home_devices()
    assert moved == []
    h.controller.connected = {"Alpha", "Bravo"}     # a real change does move
    h.update_stored_devices_ui()
    assert moved and h.listed() == ["Alpha", "Bravo", "Shockers", "OWO",
                                    "--HAPTIC SUITS", "bHaptics"]


def test_the_rows_come_back_with_the_toy_server(qapp):
    h = home({**ALL, "feature_intiface": False})
    h.controller.features["feature_intiface"] = True
    h._refresh_home_devices()
    assert h.listed() == ["Bravo", "Shockers", "OWO", "Alpha",
                          "--HAPTIC SUITS", "bHaptics"]
    assert h._home_devices.isHidden()
    assert all(h._home_devices_lay.indexOf(r) < 0 for r in h._home_rows())


def test_a_feature_switched_off_takes_its_row_out(qapp):
    h = home(ALL)
    h.controller.features["feature_owo"] = False
    h._refresh_home_devices()
    assert "OWO" not in h.listed() and h._home_owo_row.isHidden()
    h.build_stored_devices_ui()                     # and a rebuild doesn't bring it back
    assert "OWO" not in h.listed() and h._home_owo_row.isHidden()


def test_no_toys_yet_puts_the_rows_under_the_note(qapp):
    h = Host(FakeController(ALL, profiles={}, connected=()))
    h._refresh_home_devices()
    lay = h.home_list_layout
    first = lay.itemAt(0).widget()
    assert first not in h._home_rows() and "No toys yet" in first.text()
    assert lay.indexOf(h._home_shockers_row) == 1


def test_with_the_toy_server_off_the_rows_stay_on_home(qapp):
    h = home({**ALL, "feature_intiface": False})
    assert h.listed() == ["Bravo", "Alpha"]          # the toy list steps aside
    assert not h._home_devices.isHidden()
    assert h._home_devices_lay.indexOf(h._home_shockers_row) == 0


def test_rows_line_up_with_the_toys(qapp):
    """A row is the toy bar's sibling: the same logo slot and dot, so the
    names start in one column, and every one-line row is as tall as the
    next. (A toy's bar is taller since 2026-11-16: its chips are two rows.)"""
    h = home(ALL)
    h.window.resize(1700, 600)
    h.window.show()
    qapp.processEvents()
    inner = h.home_list_frame
    toy_x = h.device_ui_frames["Bravo"]["home"]["name_label"].mapTo(inner, QPoint(0, 0)).x()
    shown = [r for r in h._home_rows() if r in h._home_rows_on]
    assert {r.name.mapTo(inner, QPoint(0, 0)).x() for r in shown} == {toy_x}
    assert len({r.height() for r in shown}) == 1
    h.window.hide()


@pytest.mark.parametrize("width", [1700, 1100, 960, 860, 760])
def test_the_rows_fit_their_place_at_any_width(qapp, width):
    """No sideways scrollbar (Blise's ask, 2026-11-16): in a narrow window
    Arm shocks and the sharing switch move under the name, then one line
    each; On / Off stays at the end of the first line."""
    h = home(ALL)
    h._home_shockers_row.set_state(shockers_row(hub(), True))
    h.window.resize(width, 900)
    h.window.show()
    qapp.processEvents()
    qapp.processEvents()
    for row in [r for r in h._home_rows() if r in h._home_rows_on]:
        m = row.bar.layout().contentsMargins()
        room = row.bar.width() - m.left() - m.right()
        assert row._need(row._arranged) <= room or row._arranged == 3, row.name.text()
        assert row.lines[0].indexOf(row.power) >= 0
    row = h._home_shockers_row
    if width >= 1700:
        assert row._arranged == 1
    if width <= 860:
        assert row._arranged >= 2 and row.lines[0].indexOf(row.share) < 0
    h.window.hide()
    h.window.hide()


def test_switching_off_sends_it_down_and_on_brings_it_back(qapp):
    h = home(ALL)
    h._home_shockers_row.power.click()                  # off
    assert h.controller.calls == ["pishock_stop_all"]
    assert h.listed() == ["Bravo", "OWO", "Alpha", "--SHOCKERS", "Shockers",
                          "--HAPTIC SUITS", "bHaptics"]
    h._home_shockers_row.power.click()                  # on again
    assert h.controller.calls[-1] == "pishock_resume"
    assert h.listed() == ["Bravo", "Shockers", "OWO", "Alpha",
                          "--HAPTIC SUITS", "bHaptics"]


def test_quick_switches_reach_the_controller(qapp):
    h = home(ALL)
    h._home_owo_row.share.click()
    assert h.controller.calls == [("follow_bhaptics", False)]
    h._home_bhaptics_row.bar.clicked.emit()
    assert h.opened == ["Suits"]


def test_arm_shocks_on_home_goes_to_the_controller(qapp, monkeypatch):
    from ui.views import shocker_switches
    monkeypatch.setattr(shocker_switches, "ARM_ASKS_FROM", frozenset())
    h = home(ALL)
    arm = h._home_shockers_row.arm
    assert not arm.isHidden() and not arm.isChecked()
    arm.switch.click()
    assert h.controller.calls == [("set_pishock_armed", True)]
    assert arm.isChecked() and arm.status.text() == "Shocks armed"
    arm.switch.click()
    assert h.controller.calls[-1] == ("set_pishock_armed", False)
    assert not arm.isChecked()


def test_a_click_on_homes_arm_question_never_opens_the_page(qapp, monkeypatch):
    """The question sits on the row's clickable bar: a click on its words
    is the question's, not the bar's."""
    from PySide6.QtCore import QPoint, Qt
    from PySide6.QtTest import QTest
    from ui.views import shocker_switches
    monkeypatch.setattr(shocker_switches, "ARM_ASKS_FROM", frozenset({"home"}))
    h = home(ALL)
    h.window.resize(1100, 600)
    h.window.show()
    arm = h._home_shockers_row.arm
    arm.switch.click()
    qapp.processEvents()
    assert arm.asking and arm.question.isVisible()
    QTest.mouseClick(arm.question, Qt.LeftButton, Qt.NoModifier, QPoint(3, 3))
    assert h.opened == [] and arm.asking
    arm.no.click()
    h.window.hide()
    assert h.controller.calls == [] and not arm.asking


def test_a_hub_with_no_shocker_waits_at_the_bottom(qapp):
    h = home(ALL)
    h.controller.get_pishock_status = lambda: hub(shockers=[])
    h._refresh_home_devices()
    assert h.listed() == ["Bravo", "OWO", "Alpha", "--SHOCKERS", "Shockers",
                          "--HAPTIC SUITS", "bHaptics"]
    assert h._home_shockers_row.bar.property("hue") == theme.OFFLINE_HUE


# --- the PSVR2 headset -------------------------------------------------------

class HeadsetController(FakeController):
    def __init__(self, features, psvr2_on=True, **k):
        super().__init__(features, **k)
        self.psvr2_on, self.psvr2_paused = psvr2_on, False

    def get_psvr2_status(self):
        return {"connected": self.psvr2_on, "paused": self.psvr2_paused,
                "available": True, "auto_connect": True, "extras": {}}

    def psvr2_stop_all(self):
        self.calls.append("psvr2_stop_all")
        self.psvr2_paused = True

    def psvr2_resume(self):
        self.calls.append("psvr2_resume")
        self.psvr2_paused = False


def headset_home(features, **k):
    toys = {"Alpha": {"motor_count": 1}, "Bravo": {"motor_count": 1}}
    h = Host(HeadsetController(features, profiles=toys, connected={"Bravo"}, **k))
    h._refresh_home_devices()
    return h


def test_the_headset_row_shows_only_with_its_feature(qapp):
    assert "PSVR2" not in headset_home({}).listed()
    h = headset_home({"feature_psvr2": True})
    assert h.listed() == ["Bravo", "PSVR2", "Alpha"]
    assert h._home_psvr2_row.share.isHidden()           # nothing to share


def test_the_headset_waits_at_the_bottom_while_offline(qapp):
    h = headset_home({"feature_psvr2": True}, psvr2_on=False)
    assert h.listed() == ["Bravo", "Alpha", "--HAPTIC SUITS", "PSVR2"]


def test_the_headsets_on_off(qapp):
    h = headset_home({"feature_psvr2": True})
    h._home_psvr2_row.power.click()
    assert h.controller.calls == ["psvr2_stop_all"]
    assert h.listed() == ["Bravo", "Alpha", "--HAPTIC SUITS", "PSVR2"]
    h._home_psvr2_row.power.click()
    assert h.controller.calls[-1] == "psvr2_resume"
    h._home_psvr2_row.bar.clicked.emit()
    assert h.opened == [h._PSVR2_PAGE]


def test_the_headset_draws_its_own_icon(qapp):
    """No maker's logo in brand_icons/: the headset shows its identity
    icon while up and a grey one while not."""
    from ui.views.home_devices import _BrandIcon
    icon = _BrandIcon("psvr2")
    icon.set_look("psvr2", True)
    img = icon.grab().toImage()
    lit = [img.pixelColor(x, y) for x in range(img.width()) for y in range(img.height())
           if img.pixelColor(x, y).alpha() > 200]
    assert lit, "nothing drawn"
