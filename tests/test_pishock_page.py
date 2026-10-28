"""The Shockers page, headless (pishock.py, pishock_cards.py,
pishock_rules.py): a card per shocker with its own limits, the behaviours
taking shockers by drop or by their ＋, and the hub's switches -- against a
stub controller that records what the page asks for."""

import sys

import pytest
from PySide6.QtCore import QMimeData, QPointF, Qt
from PySide6.QtGui import QDropEvent
from PySide6.QtWidgets import QApplication, QVBoxLayout, QWidget

import pishock_limits
import ui_components as uc
from ui.views.pishock_cards import MIME_SHOCKER, ShockerDropZone, ValueSlider


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication(sys.argv[:1])


SHOCKERS = [{"id": 24325, "name": "Collar"}, {"id": 24326}]


class Stub:
    def __init__(self):
        self.calls = []
        self.rules = {"zones": [{"enabled": False, "name": "Touch zones (example)",
                                 "op": "vibrate", "mode": "pulse", "intensity": 15,
                                 "duration_ms": 500,
                                 "zones": [{"param": "Contact/Neck", "shockers": []}]}],
                      "triggers": [{"enabled": True, "name": "Headpat", "param": "Headpat",
                                    "mode": "pulse", "intensity": 15, "duration_ms": 500,
                                    "op": "vibrate", "shockers": []}],
                      "continuous": [], "impacts": []}

    def get_pishock_status(self):
        return {"available": True, "connected": True, "connecting": False, "port": "COM7",
                "port_setting": "", "hub_kind": "pishock", "firmware": "3.1.2",
                "board": "PiShock Next", "shockers": SHOCKERS, "openshock_shockers": [],
                "armed": False, "paused": False, "auto_connect": False,
                "limits": {k: d for k, (_lo, _hi, d) in pishock_limits.RANGES.items()},
                "ranges": dict(pishock_limits.RANGES), "hub_name": "PiShock",
                "shocker_limits": {"24325": {"max_intensity": 20, "max_vibrate": 60,
                                             "max_pulse_ms": 1000},
                                   "24326": {"max_intensity": 30, "max_vibrate": 30,
                                             "max_pulse_ms": 1000}}}

    def list_pishock_ports(self):
        return []

    def get_pishock_rules(self, kind):
        return [dict(r) for r in self.rules[kind]]

    def set_pishock_rule(self, kind, idx, rule):
        self.calls.append(("rule", kind, idx, rule))
        self.rules[kind][idx] = rule

    def get_pishock_live(self):
        return {"values": {}, "outputs": {}}

    def __getattr__(self, name):
        if name.startswith("__"):
            raise AttributeError(name)
        return lambda *a, **k: self.calls.append((name,) + a)


def page(qapp):
    ui = uc.OscGoesPurrrUI.__new__(uc.OscGoesPurrrUI)
    ui.controller = Stub()
    ui.views = {}
    ui.main_stack = None
    root = QWidget()
    ui.window = root
    lay = QVBoxLayout(root)
    ui._build_pishock_view(lay)
    return ui, root


def test_a_card_per_shocker_with_its_own_limits(qapp):
    ui, _root = page(qapp)
    cards = ui._pishock_cards
    assert set(cards) == {24325, 24326}
    assert cards[24325].limits["max_intensity"].value() == 20
    assert cards[24326].label() == "Shocker 24326"
    cards[24325].limits["max_intensity"].slider.setValue(11)   # 1..100: notch 11 = 12
    cards[24325].limits["max_intensity"]._send()               # the hand stopped
    assert ui.controller.calls[-1] == ("set_pishock_shocker_limit", 24325, "max_intensity", 12)


def test_a_shocker_dropped_on_a_behaviour_is_what_it_drives(qapp):
    ui, _root = page(qapp)
    headpat = next(w for w in ui._pishock_behaviours if w["kind"] == "triggers")
    zone = headpat["card"].zone
    mime = QMimeData()
    mime.setData(MIME_SHOCKER, b"24326")
    drop = QDropEvent(QPointF(5, 5), Qt.CopyAction, mime, Qt.LeftButton, Qt.NoModifier)
    zone.dropEvent(drop)
    kind, idx, rule = ui.controller.calls[-1][1:]
    assert (kind, idx, rule["shockers"]) == ("triggers", 0, [24326])
    # its ＋ lists the shockers that aren't on it yet, and All shockers
    zone._toggle_pick()
    zone.add(24325)
    assert ui.controller.calls[-1][3]["shockers"] == [24326, 24325]
    zone._remove(24326)
    assert ui.controller.calls[-1][3]["shockers"] == [24325]


def test_a_touch_zone_takes_its_own_shockers(qapp):
    ui, _root = page(qapp)
    zones = next(w for w in ui._pishock_behaviours if w["kind"] == "zones")
    # the card as a whole takes none: each contact's row does
    assert zones["card"].zone is None
    row = zones["card"].findChildren(ShockerDropZone)[0]
    row.add(24325)
    rule = ui.controller.calls[-1][3]
    assert rule["zones"] == [{"param": "Contact/Neck", "shockers": [24325]}]


def test_the_hub_switches_go_to_the_controller(qapp):
    ui, _root = page(qapp)
    ui._pishock_arm.setChecked(True)
    assert ("set_pishock_armed", True) in ui.controller.calls
    assert "COM7" in ui._pishock_pill.text()


def test_a_value_slider_rounds_to_its_step_and_spans_log_ranges(qapp):
    s = ValueSlider("Rest", 0.1, 3600.0, 0.5, 0.1, log=True)
    assert s.value() == pytest.approx(0.5, abs=0.05)
    s.slider.setValue(s.slider.maximum())
    assert s.value() == 3600.0
    pulse = ValueSlider("Longest pulse", 100, 15000, 1000, 100)
    assert pulse.value() == 1000 and pulse.slider.maximum() == 149


def test_building_the_page_never_opens_a_window(qapp):
    from PySide6.QtCore import QEvent, QObject

    opened = []

    class Spy(QObject):
        def eventFilter(self, obj, ev):
            if ev.type() == QEvent.Show and isinstance(obj, QWidget) and obj.isWindow():
                opened.append(type(obj).__name__)
            return False

    spy = Spy()
    qapp.installEventFilter(spy)
    try:
        ui, _root = page(qapp)
        ui.refresh_pishock_status()
        qapp.processEvents()
    finally:
        qapp.removeEventFilter(spy)
    assert opened == []
