"""Widget tests for the Suits page: it builds against the facade alone,
shows only the suits that are switched on and the bHaptics parts you
have, says what's connected, puts every dot, patch and tracker on her,
hands a pressed dot to the controller and opens its part's and muscle's
cards with a line to each, checks the avatar's contacts, saves a slider to
the part it was moved for, and keeps the EMS ceiling away from the scroll
wheel."""

import sys

import pytest

from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QImage, QMouseEvent, QWheelEvent
from PySide6.QtWidgets import QApplication, QVBoxLayout, QWidget

import body_map
from settings.suits import _clean_bhaptics, _clean_owo
from ui.views import body_view
from ui.views.device_frame import DeviceFrameMixin
from ui.views.pishock import PiShockMixin
from ui.views.suits import SuitsMixin


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication(sys.argv[:1])


class FakeController:
    def __init__(self, bh_on=True, owo_on=True):
        self.bh_on, self.owo_on = bh_on, owo_on
        self.calls = []
        self.bs, self.os = _clean_bhaptics({}), _clean_owo({})
        self.bs["have"] = [key for key, _n, _p in body_map.PART_GROUPS]   # every part
        self.devices = []
        self.owo_connected = False
        self.detected = {"positions": [], "owo": []}
        self.trackers = None

    def get_suits_status(self):
        return {"bhaptics": {"available": True, "wanted": True, "released": False,
                             "scanning": False, "error": "", "devices": list(self.devices),
                             "settings": self.bs, "feature": self.bh_on},
                "owo": {"connected": self.owo_connected, "host": "127.0.0.1", "wanted": False,
                        "paused": False, "error": "", "active": {}, "frequency": 50,
                        "settings": self.os, "feature": self.owo_on},
                "output_off": False,
                **({"trackers": self.trackers} if self.trackers else {})}

    def get_suits_detected(self):
        return dict(self.detected)

    def get_suits_live(self):
        return {"frame": body_map.empty_frame(), "owo": {}, "dots": {}, "owo_sending": {}}

    def get_suit_routes(self):
        return []

    def get_detected_zones(self):
        return {"Orifices": [], "Penetrators": [], "Touch": []}

    def get_sps_source_names_flat(self):
        return []

    def __getattr__(self, name):
        if name.startswith("__"):
            raise AttributeError(name)
        return lambda *a, **k: self.calls.append((name, a, k))


class _Host(SuitsMixin, PiShockMixin, DeviceFrameMixin):
    def __init__(self, controller):
        self.controller = controller
        self.window = QWidget()
        self.views = {}
        self.main_stack = None
        self._build_suits_view(QVBoxLayout(self.window))
        self._suits_body.resize(self._suits_body.sizeHint())

    def _repolish(self, w):
        w.style().unpolish(w)
        w.style().polish(w)


def _press(body, point: QPointF):
    press = QMouseEvent(QMouseEvent.MouseButtonPress, point, point,
                        Qt.LeftButton, Qt.LeftButton, Qt.NoModifier)
    release = QMouseEvent(QMouseEvent.MouseButtonRelease, point, point,
                          Qt.LeftButton, Qt.NoButton, Qt.NoModifier)
    body.mousePressEvent(press)
    body.mouseReleaseEvent(release)


# ---- her ---------------------------------------------------------------------

def test_every_part_has_its_dots_on_her():
    assert set(body_view.PLACES) == set(body_map.NODE_COUNTS)
    box = body_view.FIG_BOX
    for position, (view, _angle, points) in body_view.PLACES.items():
        assert len(points) == body_map.NODE_COUNTS[position], position
        assert view == (body_view.BACK if position == "VestBack" else body_view.FRONT)
        for x, y in points:
            assert box.contains(QPointF(x, y)), (position, x, y)


def test_each_vest_panel_is_drawn_as_seen_from_outside():
    # body_map numbers a panel as seen from outside it: on the front her
    # right (columns 0-1) is on our left, on the back her left is
    front = body_view.PLACES["VestFront"][2]
    back = body_view.PLACES["VestBack"][2]
    for points in (front, back):
        assert points[0][0] < points[1][0] < points[2][0] < points[3][0]
        assert points[0][1] < points[4][1] < points[16][1]
    right_arm = body_view.PLACES["ForearmR"][2]
    left_arm = body_view.PLACES["ForearmL"][2]
    assert max(x for x, _y in right_arm) < 512 < min(x for x, _y in left_arm)


def test_a_dot_knows_the_muscle_around_it():
    for muscle, (position, cells) in body_map.OWO_REGIONS.items():
        for i in cells:
            assert body_view.muscle_at(position, i) == muscle
    assert body_view.muscle_at("Head", 0) is None
    assert body_view.muscle_at("FootL", 2) is None


def test_each_patch_holds_its_own_dots_and_no_others(qapp):
    view = body_view.BodyView()
    view.resize(view.sizeHint())
    for muscle, (position, cells) in body_map.OWO_REGIONS.items():
        path = view.zone_path(muscle)
        for pos, (_v, _a, points) in body_view.PLACES.items():
            for i in range(len(points)):
                inside = path.contains(view.dot_center(pos, i))
                assert inside == (pos == position and i in cells), (muscle, pos, i)


def test_her_pictures_ship():
    for v in (body_view.FRONT, body_view.BACK):
        assert not QImage(body_view._figure_path(v)).isNull()


def test_the_view_shrinks_with_the_width_and_never_grows_past_its_height(qapp):
    view = body_view.BodyView()
    assert view.heightForWidth(2000) == body_view.HEIGHT
    assert view.heightForWidth(500) < body_view.HEIGHT


# ---- the page ----------------------------------------------------------------

def test_only_switched_on_suits_show(qapp):
    h = _Host(FakeController(bh_on=True, owo_on=False))
    assert not h._suits_bh_card.isHidden()
    assert h._suits_owo_card.isHidden()
    assert h._suits_muscle_chips.isHidden()
    assert h._suits_tracker_chips.isHidden()          # no trackers in this build
    h._on_suits_muscle_chip("Pectoral_L")             # OWO off: nothing to open
    assert h._suits_muscle_card.isHidden()
    assert not h._suits_pick_hint.isHidden()


def test_status_text(qapp):
    c = FakeController()
    c.devices = [{"address": "a", "name": "TactSuitPro", "label": "TactSuit Pro",
                  "model": "pro", "positions": ["VestFront", "VestBack"],
                  "battery": 87, "verified": False}]
    c.owo_connected = True
    h = _Host(c)
    assert h._bh_pill.text() == "Connected · 1 part"
    assert "TactSuit Pro · 87 %" in h._bh_info.text()
    assert h._owo_pill.text() == "Connected · My OWO on this PC"
    assert h._owo_connect_btn.text() == "Disconnect"


def test_settings_show_on_the_chips_and_the_inspector(qapp):
    c = FakeController()
    c.bs["devices"]["HandL"] = {"enabled": False, "intensity": 40}
    c.os["muscles"]["Arm_L"] = {"enabled": True, "max": 25}
    c.os["global_max"] = 33
    h = _Host(c)
    assert h._suits_part_chips.chips["HandL"].text().endswith("off")
    assert h._suits_muscle_chips.chips["Arm_L"].text().endswith("25 %")
    assert h._owo_ceiling.value() == 33
    h._on_suits_part_chip("HandL")
    assert h._suits_part_card.title.text() == "Left hand"
    assert not h._suits_part_card.on.isChecked()
    assert not h._suits_part_card.strength.isEnabled()
    h._on_suits_muscle_chip("Arm_L")
    assert h._suits_muscle_card.top.value() == 25
    assert "33 %" in h._suits_muscle_card.ceiling.text()
    assert h._suits_body.selection() == (None, "Arm_L")    # a chip picks just itself
    assert ("HandL",) == tuple(p for p in body_map.NODE_COUNTS if p in h._suits_body._parts_off)
    assert not c.calls          # filling the page sends nothing back


def test_a_pressed_dot_is_held_let_go_and_picked(qapp):
    c = FakeController()
    h = _Host(c)
    body = h._suits_body
    _press(body, body.dot_center("VestBack", 5))
    holds = [a for name, a, _k in c.calls if name == "bhaptics_hold_dot"]
    assert holds == [("VestBack", 5, True), ("VestBack", 5, False)]
    assert h._suits_part_card.title.text() == "Vest back"
    assert h._suits_muscle_card.title.text() == "Left upper back"
    assert h._suits_part_chips.chips["VestBack"].isChecked()

    _press(body, body.dot_center("Head", 2))
    assert h._suits_part_card.title.text() == "Head"
    assert h._suits_muscle_card.isHidden()            # OWO has no head


def test_a_press_between_dots_picks_just_the_muscle(qapp):
    c = FakeController()
    h = _Host(c)
    body = h._suits_body
    h._on_suits_part_chip("Head")
    a, b = body.dot_center("VestFront", 0), body.dot_center("VestFront", 5)
    _press(body, (a + b) / 2)
    assert body.selection() == (None, "Pectoral_R")
    assert not [1 for name, _a, _k in c.calls if name == "bhaptics_hold_dot"]


def test_a_slider_saves_to_the_part_it_was_moved_for(qapp):
    c = FakeController()
    h = _Host(c)
    card = h._suits_part_card
    h._on_suits_part_chip("ForearmL")
    card.strength.slider.setValue(card.strength._to_slider(60))
    assert not [1 for name, _a, _k in c.calls if name == "set_bhaptics_device"]
    h._on_suits_part_chip("Head")        # picked something else before it saved
    assert ("set_bhaptics_device", ("ForearmL",), {"intensity": 60}) in c.calls
    assert card.part == "Head"


def test_the_inspector_switches_and_tests_reach_the_controller(qapp):
    c = FakeController()
    h = _Host(c)
    h._on_suits_muscle_chip("Dorsal_R")
    h._suits_muscle_card.on.setChecked(False)
    h._suits_muscle_card.test.click()
    h._on_suits_part_chip("VestFront")
    h._suits_part_card.test.click()
    assert ("set_owo_muscle", ("Dorsal_R",), {"enabled": False}) in c.calls
    assert ("owo_test", ("Dorsal_R",), {}) in c.calls
    assert ("bhaptics_test", ("VestFront",), {}) in c.calls


def test_the_scroll_wheel_never_moves_the_ceiling(qapp):
    c = FakeController()
    h = _Host(c)
    slider = h._owo_ceiling.slider
    before = slider.value()
    wheel = QWheelEvent(QPointF(5, 5), QPointF(5, 5), QPoint(0, 0), QPoint(0, 120),
                        Qt.NoButton, Qt.NoModifier, Qt.NoScrollPhase, False)
    slider.wheelEvent(wheel)
    assert slider.value() == before
    assert not wheel.isAccepted()


# ---- You have ----------------------------------------------------------------

def test_only_the_parts_you_have_show(qapp):
    c = FakeController()
    c.bs["have"] = ["vest"]
    h = _Host(c)
    chips = h._suits_part_chips.chips
    assert not chips["VestBack"].isHidden()
    assert chips["HandL"].isHidden() and chips["Head"].isHidden()
    assert h._bh_have.chips["vest"].isChecked()
    assert not h._bh_have.chips["head"].isChecked()
    body = h._suits_body
    _press(body, body.dot_center("Head", 2))          # no head: no dot there
    assert not [1 for name, _a, _k in c.calls if name == "bhaptics_hold_dot"]


def test_a_part_you_take_off_closes_its_card(qapp):
    c = FakeController()
    h = _Host(c)
    h._on_suits_part_chip("Head")
    c.bs["have"] = ["vest"]
    h.refresh_suits_status()
    assert h._suits_body.selection()[0] is None
    assert h._suits_part_card.isHidden()
    assert not h._suits_pick_hint.isHidden()


def test_having_nothing_hides_the_bhaptics_part_of_the_body_card(qapp):
    c = FakeController()
    c.bs["have"] = []
    h = _Host(c)
    assert h._suits_part_card.isHidden()
    assert h._suits_part_chips.isHidden()
    assert not h._suits_bh_card.isHidden()            # where you pick them again


def test_you_have_chips_reach_the_controller(qapp):
    c = FakeController()
    c.bs["have"] = ["vest"]
    h = _Host(c)
    h._bh_have.chips["head"].click()
    assert ("set_bhaptics_have", ("head", True), {}) in c.calls


def test_zone_routes_offer_the_parts_you_have(qapp):
    c = FakeController()
    c.bs["have"] = ["vest"]
    c.get_suit_routes = lambda: [{"enabled": True, "zone": "z", "zone_type": "Orf",
                                  "filters": [], "region": "HandL", "gain": 1.0}]
    h = _Host(c)
    combo = h._suit_route_rows[0]["region"]
    names = [combo.itemData(i) for i in range(combo.count())]
    assert "VestFront" in names and "Pectoral_R" in names
    assert "HandL" in names                           # where it already lands
    assert "Head" not in names and "FootR" not in names
    assert combo.currentData() == "HandL"


# ---- cards that open with a line to her --------------------------------------

def _laid_out(h):
    h.window.resize(1200, 1800)
    h.window.show()
    QApplication.processEvents()
    return h


def test_nothing_is_open_until_she_is_clicked_and_empty_space_closes_it(qapp):
    c = FakeController()
    h = _Host(c)
    body = h._suits_body
    assert not h._suits_pick_hint.isHidden()
    assert h._suits_part_card.isHidden() and h._suits_muscle_card.isHidden()
    _press(body, body.dot_center("VestFront", 0))
    assert not h._suits_part_card.isHidden() and not h._suits_muscle_card.isHidden()
    assert h._suits_pick_hint.isHidden()
    _press(body, QPointF(2, body.height() - 2))       # a corner: nothing there
    assert h._suits_part_card.isHidden() and h._suits_muscle_card.isHidden()
    assert not h._suits_pick_hint.isHidden()


def test_a_line_runs_from_each_picked_thing_to_its_card(qapp):
    c = FakeController()
    h = _laid_out(_Host(c))
    body = h._suits_body
    assert h._suits_leader_lines() == []
    _press(body, body.dot_center("VestFront", 5))
    QApplication.processEvents()                       # the column moves the cards
    lines = h._suits_leader_lines()
    assert [hue for hue, _s, _e in lines] == ["orange", "purple"]
    stage = h._suits_stage
    for (hue, start, end), card in zip(lines, (h._suits_part_card, h._suits_muscle_card)):
        corner = card.frame.mapTo(stage, QPoint(0, 0))
        assert end.x() == corner.x()                  # it ends at its card
        assert start.x() < end.x()
        assert body.geometry().contains(start.toPoint())
    # the cards open level with the dot, not at the top of the column
    assert abs(lines[0][2].y() - lines[0][1].y()) < 40
    h.window.hide()


# ---- trackers ------------------------------------------------------------------

def test_trackers_show_on_her_only_when_there_are_some(qapp):
    c = FakeController()
    c.trackers = {"feature": True, "spots": {
        "hip": {"enabled": True, "intensity": 70, "contacts": [1, 1]},
        "ankle_l": {"enabled": False, "intensity": 100, "contacts": [0, 2]}}}
    h = _laid_out(_Host(c))
    chips = h._suits_tracker_chips.chips
    assert not chips["hip"].isHidden() and chips["chest"].isHidden()
    assert chips["hip"].text().endswith("70 %") and chips["ankle_l"].text().endswith("off")
    body = h._suits_body
    _press(body, body.tracker_center("hip"))
    card = h._suits_tracker_card
    assert not card.isHidden()
    assert card.title.text() == "Hip tracker"
    assert card.check.text() == "On your avatar: its contact"
    assert [hue for hue, _s, _e in h._suits_leader_lines()] == ["blue"]
    card.test.click()
    card.strength.slider.setValue(card.strength._to_slider(40))
    card.strength.flush()
    assert ("tracker_test", ("hip",), {}) in c.calls
    assert ("set_tracker", ("hip",), {"intensity": 40}) in c.calls
    assert "ankle_l" in body._missing_trackers
    h.window.hide()


# ---- the contact check ---------------------------------------------------------

def test_the_check_says_what_the_avatar_is_missing(qapp):
    c = FakeController()
    c.bs["have"] = ["vest", "arms"]
    vest_front = tuple(range(20))
    c.detected = {"positions": ["VestFront"], "owo": ["Arm_L"], "source": "file",
                  "contacts": {"VestFront": vest_front, "VestBack": tuple(range(10)),
                               "ForearmL": (), "ForearmR": ()}}
    h = _Host(c)
    pills = {p.text(): p.property("tone") for p in h._suits_check.pills}
    assert pills["Vest  30 / 40"] == "warn"
    assert pills["Sleeves  0 / 12"] == "err"
    # the front muscles, the upper back and Lumbar_L via bHaptics, Arm_L its own
    assert pills["OWO  8 / 10"] == "warn"    # all but Lumbar_R and Arm_R
    assert "every parameter" in h._suits_check.note.text()
    body = h._suits_body
    assert body._missing_dots["VestBack"] == frozenset(range(10, 20))
    assert "VestFront" not in body._missing_dots
    assert "Arm_R" in body._missing_muscles and "Arm_L" not in body._missing_muscles
    assert not h._suits_legend["missing"][0].isHidden()

    h._on_suits_part_chip("VestBack")
    assert h._suits_part_card.check.text() == "On your avatar: 10 of 20 contacts"
    h._on_suits_part_chip("ForearmL")
    assert h._suits_part_card.check.text() == "Not on your avatar"
    h._on_suits_muscle_chip("Dorsal_L")
    assert h._suits_muscle_card.check.text() == "Played by 4 bHaptics contacts"
    h._on_suits_muscle_chip("Arm_L")
    assert h._suits_muscle_card.check.text() == "On your avatar: its OWO contact"


def test_no_avatar_yet_checks_nothing_and_says_how(qapp):
    h = _Host(FakeController())
    assert h._suits_check.pills == []
    assert "Wear your avatar" in h._suits_check.note.text()
    assert h._suits_body._missing_dots == {}
    h._on_suits_part_chip("VestFront")
    assert h._suits_part_card.check.isHidden()
