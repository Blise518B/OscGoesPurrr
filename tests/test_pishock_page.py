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
                      "continuous": [], "impacts": [], "pulls": []}

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

    def get_device_connected_param(self, slot):
        return (True, f"Default/{slot}")

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


def test_the_hub_switches_go_to_the_controller(qapp, monkeypatch):
    from ui.views import shocker_switches
    monkeypatch.setattr(shocker_switches, "ARM_ASKS_FROM", frozenset())
    ui, _root = page(qapp)
    ui._pishock_arm.switch.setChecked(True)
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


def test_a_shocker_switched_off_stays_on_the_page_greyed_and_its_chips_go_grey(qapp):
    """Its card's switch: Off greys the card where it is (its switch still
    lit, to bring it back), says OFF, and a behaviour that names it shows
    its chip grey -- the behaviour skips it."""
    from PySide6.QtWidgets import QPushButton
    ui, _root = page(qapp)
    ctl, off, base = ui.controller, [], ui.controller.get_pishock_status
    ctl.set_pishock_shocker_on = lambda sid, on: (off.remove(sid) if on else off.append(sid))
    ctl.get_pishock_status = lambda: dict(base(), all_shockers=SHOCKERS, shockers_off=list(off),
                                          shockers=[s for s in SHOCKERS if s["id"] not in off])
    ctl.rules["triggers"][0]["shockers"] = [24325, 24326]
    ui.refresh_pishock_status()
    card = ui._pishock_cards[24326]
    assert card.use.isChecked() and card.body.isEnabled() and card.body.graphicsEffect() is None
    card.use.setChecked(False)
    card = ui._pishock_cards[24326]                       # still on the page
    assert off == [24326] and not card.use.isChecked()
    assert not card.body.isEnabled() and card.body.graphicsEffect() is not None
    assert card.use.isEnabled() and card.use.graphicsEffect() is None
    assert card.pill.text() == "OFF"
    headpat = next(w for w in ui._pishock_behaviours if w["kind"] == "triggers")
    chips = {b.text().split("  ")[0]: b.isChecked() for b in headpat["card"].zone.findChildren(QPushButton)
             if b.property("role") == "chip"}
    assert chips == {"Collar": True, "Shocker 24326": False}
    card.use.setChecked(True)                             # and back
    assert off == [] and ui._pishock_cards[24326].body.isEnabled()


def test_the_hub_and_every_shocker_can_tell_vrchat(qapp):
    """The "connected" avatar parameters (presence_facade): the hub card's
    for any shocker, and one on each shocker's card -- reaching the
    controller by slot."""
    from ui.widgets import ToggleSwitch
    ui, root = page(qapp)
    hub = [t for t in root.findChildren(ToggleSwitch)
           if t.text() == "Tell VRChat while a shocker is connected"]
    assert len(hub) == 1 and hub[0].isChecked()
    for sid, card in ui._pishock_cards.items():
        mine = [t for t in card.findChildren(ToggleSwitch) if t.text() == "Tell VRChat"]
        assert len(mine) == 1 and mine[0].isChecked(), sid
    hub[0].setChecked(False)
    assert ui.controller.calls[-1] == ("set_device_connected_param", "shockers",
                                       False, "Default/shockers")
    card_switch = [t for t in ui._pishock_cards[24326].findChildren(ToggleSwitch)
                   if t.text() == "Tell VRChat"][0]
    card_switch.setChecked(False)
    assert ui.controller.calls[-1] == ("set_device_connected_param", "shocker:24326",
                                       False, "Default/shocker:24326")


# ---- the limits read as limits (friends' review, 2026-11-14) ------------------

def _group(card):
    from PySide6.QtWidgets import QFrame
    boxes = [f for f in card.findChildren(QFrame) if f.objectName() == "limitsGroup"]
    assert len(boxes) == 1
    return boxes[0]


def _texts(widget):
    from PySide6.QtWidgets import QLabel
    return [lbl.text() for lbl in widget.findChildren(QLabel)]


def test_a_shockers_limits_sit_in_a_limits_group_that_says_nothing_is_sent(qapp):
    from ui.widgets import IdentityMark
    ui, _root = page(qapp)
    for sid, card in ui._pishock_cards.items():
        box = _group(card)
        assert "Limits" in _texts(box)
        marks = box.findChildren(IdentityMark)
        assert [m._what for m in marks] == ["limits"], sid          # the ceiling icon
        hint = " ".join(_texts(box))
        assert "The most anything may send" in hint
        assert "friends, behaviours, the menu" in hint
        assert "Nothing is sent from here" in hint
        # all three ceilings are in the box, each labelled "Up to ..."
        for key, s in card.limits.items():
            assert box.isAncestorOf(s), (sid, key)
            assert s.name_label.text().startswith("Up to"), (sid, key)
        # not folded: the box and what is in it are there from the start
        assert not box.isHidden() and all(not s.isHidden() for s in card.limits.values())


def test_the_buttons_that_send_stay_apart_from_the_limits(qapp):
    from PySide6.QtWidgets import QFrame, QPushButton
    ui, _root = page(qapp)
    card = ui._pishock_cards[24325]
    box = _group(card)
    assert box.findChildren(QPushButton) == []                      # nothing in it sends
    tests = [b for b in card.findChildren(QPushButton) if b.objectName() == "testButton"]
    assert [b.text() for b in tests] == ["Beep", "Vibrate", "Shock"]
    assert not any(box.isAncestorOf(b) for b in tests)
    assert "Test" in _texts(card._tail)
    assert any(f.objectName() == "cardRule" for f in card._tail.findChildren(QFrame))
    # order down the card: Limits, then the card's own rows (Tell VRChat), then Test
    lay = card.body.layout()
    order = [lay.itemAt(i).widget() for i in range(lay.count()) if lay.itemAt(i).widget()]
    from ui.widgets import ToggleSwitch
    tell = next(w for w in order if w.findChildren(ToggleSwitch))
    assert order.index(box) < order.index(tell) < order.index(card._tail)
    # a test button still asks the controller for its test, on this shocker
    tests[0].click()
    assert ui.controller.calls[-1] == ("pishock_test", "beep", 24325)


def test_the_shared_timing_is_a_limits_group_without_a_button(qapp):
    from PySide6.QtWidgets import QPushButton
    ui, _root = page(qapp)
    shared = ui._pishock_shared_card
    box = _group(shared)
    assert "Limits" in _texts(box) and "Nothing is sent from here" in " ".join(_texts(box))
    assert shared.findChildren(QPushButton) == []
    labels = {key: s.name_label.text() for key, s in shared.limits.items()}
    # a ceiling is "Up to ..."; the rest is a floor, so it says "At least"
    assert labels == {"cooldown_s": "At least a rest of", "max_hold_s": "Up to a hold of",
                      "hold_rest_s": "Then a forced break of"}
    shared.limits["max_hold_s"].slider.setValue(shared.limits["max_hold_s"].slider.maximum())
    shared.limits["max_hold_s"]._send()
    assert ui.controller.calls[-1] == ("set_pishock_limit", "max_hold_s", 600.0)


def test_limit_sliders_keep_their_number_reach_both_ends_and_ignore_the_wheel(qapp):
    from PySide6.QtCore import QPoint
    from PySide6.QtGui import QWheelEvent
    from PySide6.QtWidgets import QSpinBox
    from ui.views.card_parts import WheelSafeSlider
    ui, _root = page(qapp)
    card = ui._pishock_cards[24325]
    sliders = list(card.limits.values()) + list(ui._pishock_shared_card.limits.values())
    assert len(sliders) == 6
    for s in sliders:
        assert isinstance(s.slider, WheelSafeSlider)                # the wheel scrolls the page
        assert s.value_label.text()                                 # the number, written out
        before = s.slider.value()
        ev = QWheelEvent(QPointF(5, 5), QPointF(s.slider.mapToGlobal(QPoint(5, 5))),
                         QPoint(0, 0), QPoint(0, -120), Qt.NoButton, Qt.NoModifier,
                         Qt.NoScrollPhase, False)
        QApplication.sendEvent(s.slider, ev)
        assert s.slider.value() == before and not ev.isAccepted()
        for end in (s._lo, s._hi):                                  # each end is reachable
            s.set_value(end)
            assert s.value() == end
            assert s.slider.value() in (s.slider.minimum(), s.slider.maximum())
    for box in (_group(card), _group(ui._pishock_shared_card)):
        assert box.findChildren(QSpinBox) == []                     # never spin boxes


def test_the_limits_explain_themselves_on_hover(qapp):
    from ui.help_mode import split_tip
    ui, _root = page(qapp)
    card = ui._pishock_cards[24325]
    title, first = split_tip(_group(card).toolTip())
    assert title == "Limits"
    assert first.startswith("The most anything may send to this shocker")
    for key, s in card.limits.items():
        title, first = split_tip(s.toolTip())
        assert title == s.name_label.text(), key
        assert first, key                                           # its first sentence stands alone
        assert "sends nothing" in s.toolTip(), key
    for shared in ui._pishock_shared_card.limits.values():
        assert split_tip(shared.toolTip())[1]
    from PySide6.QtWidgets import QPushButton
    buttons = [b for b in card.findChildren(QPushButton) if b.objectName() == "testButton"]
    for b in buttons:
        title, first = split_tip(b.toolTip())
        assert title == f"Test: {b.text()}" and first.startswith("Sends one short")


def test_an_openshock_card_keeps_its_model_and_id_outside_the_limits(qapp):
    from PySide6.QtWidgets import QSpinBox
    ui, _root = page(qapp)
    base = ui.controller.get_pishock_status
    ui.controller.openshock_models = lambda: [("caixianlin", "CaiXianlin")]
    ui.controller.get_pishock_status = lambda: dict(
        base(), hub_kind="openshock", connected=False, shockers=[],
        openshock_shockers=[{"id": 7, "name": "Mine", "model": "caixianlin"}])
    ui.refresh_pishock_status()
    card = ui._pishock_cards[7]
    box = _group(card)
    assert card.rf_id is not None and not box.isAncestorOf(card.rf_id)
    assert box.findChildren(QSpinBox) == []
    assert card.delete is not None and not box.isAncestorOf(card.delete)


# --- ShockOSC: the Pull, a touch's hold time, the tag, the setup card ---------------

def test_a_pull_card_saves_its_physbone_and_both_ops(qapp):
    ui, _root = page(qapp)
    ui.controller.rules["pulls"] = [{"enabled": True, "name": "Tail", "param": "ShockOsc/Tail",
                                     "op": "shock", "held_op": "vibrate", "min_int": 5,
                                     "max_int": 30, "duration_ms": 500, "shockers": []}]
    ui._rebuild_pishock_rules()
    pull = next(w for w in ui._pishock_behaviours if w["kind"] == "pulls")
    pull["held_op"].button(0).click()                  # Nothing while held
    rule = ui.controller.calls[-1][3]
    assert (rule["param"], rule["op"], rule["held_op"]) == ("ShockOsc/Tail", "shock", "none")
    pull["param"].setText("ShockOsc/Ear_IsGrabbed")    # a picked PhysBone parameter
    pull["param"].editingFinished.emit()
    assert ui.controller.calls[-1][3]["param"] == "ShockOsc/Ear"
    # its live readout: held, and how far it is stretched
    ui._refresh_pishock_rules_live({"ShockOsc/Ear_IsGrabbed": 1.0, "ShockOsc/Ear_Stretch": 0.4})
    assert pull["live"].text() == "held · 0.40"


def test_a_contacts_hold_time_shows_for_pulse_once_only(qapp):
    ui, root = page(qapp)
    root.show()
    try:
        headpat = next(w for w in ui._pishock_behaviours if w["kind"] == "triggers")
        assert headpat["hold_ms"].isVisible()
        assert headpat["hold_ms"].value_label.text() == "at once"
        headpat["mode"].button(1).click()             # While touching
        assert not headpat["hold_ms"].isVisible()
        headpat["mode"].button(0).click()
        headpat["hold_ms"].slider.setValue(5)          # 5 x 50 ms
        headpat["hold_ms"]._send()
        assert ui.controller.calls[-1][3]["hold_ms"] == 250
        assert headpat["hold_ms"].value_label.text() == "0.25 s"   # not "0.2 s"
    finally:
        root.hide()


def test_a_behaviour_on_a_shockosc_parameter_wears_the_tag(qapp):
    from PySide6.QtWidgets import QLabel
    ui, _root = page(qapp)
    ui.controller.rules["triggers"][0]["param"] = "ShockOsc/Collar_IShock"
    ui._rebuild_pishock_rules()

    def tags(kind):
        w = next(b for b in ui._pishock_behaviours if b["kind"] == kind)
        return [l.text() for l in w["card"].findChildren(QLabel) if l.text() == "SHOCKOSC"]
    assert tags("triggers") == ["SHOCKOSC"]
    assert tags("zones") == []


SETUP = {"source": "file", "synced": ["Intensity", "CooldownTime", "HoldTime", "Paused"],
         "groups": [{"name": "Collar", "label": "Collar", "makes": ["touch", "shock at once"],
                     "total": 2, "missing": 2, "suggested": [24325]},
                    {"name": "_All", "label": "All shockers", "makes": ["beep at once"],
                     "total": 1, "missing": 0, "suggested": "all"}]}


def test_the_shockosc_card_shows_while_the_avatar_has_it(qapp):
    from ui.views.pishock_cards import ShockerDropZone as Zone
    ui, _root = page(qapp)
    assert ui._shockosc_card.isHidden()               # nothing from the stub
    ui.controller.get_shockosc_setup = lambda: SETUP
    ui.refresh_pishock_shockosc()
    assert not ui._shockosc_card.isHidden()
    assert ui._shockosc_go.text() == "Set up 2 behaviours"
    zones = ui._shockosc_rows.findChildren(Zone)
    assert len(zones) == 1 and zones[0].targets() == [24325]   # the set-up group has none
    assert ui._shockosc_settings.text() == (
        "Kept in step with your avatar's ShockOSC settings: strength, rest after a shock, "
        "touch time, On / Off. Change one in its menu or here, and the other follows.")
    # a shocker dropped on the row is what the click sets it up with
    zones[0].add(24326)
    asked = []
    ui.controller.shockosc_set_up = lambda chosen: asked.append(chosen) or 2
    ui._shockosc_go.click()
    assert asked == [{"Collar": [24325, 24326]}]


def test_the_shockosc_card_once_everything_is_set_up(qapp):
    ui, _root = page(qapp)
    done = dict(SETUP, groups=[dict(g, missing=0) for g in SETUP["groups"]], synced=[])
    ui.controller.get_shockosc_setup = lambda: done
    ui.refresh_pishock_shockosc()
    assert ui._shockosc_go.isHidden()
    assert "are set up" in ui._shockosc_title.text()
    assert ui._shockosc_settings.isHidden()            # the avatar has no settings of its own
    ui.controller.get_shockosc_setup = lambda: {"groups": [], "synced": [], "source": "file"}
    ui.refresh_pishock_shockosc()
    assert ui._shockosc_card.isHidden()


def test_a_shockosc_behaviour_has_a_rest_and_strength_may_be_0(qapp):
    ui, _root = page(qapp)
    ui.controller.rules["triggers"][0]["param"] = "ShockOsc/Collar_IShock"
    ui.controller.rules["triggers"][0]["rest_ms"] = 5000
    ui.controller.rules["continuous"] = [{"enabled": True, "name": "Prox", "param": "Prox",
                                          "op": "vibrate", "threshold": 0.0, "min_int": 5,
                                          "max_int": 30, "shockers": []}]
    ui.refresh_pishock_rules()
    contact = next(w for w in ui._pishock_behaviours if w["kind"] == "triggers")
    prox = next(w for w in ui._pishock_behaviours if w["kind"] == "continuous")
    assert "rest_ms" in contact and "rest_ms" not in prox      # ShockOSC's only
    assert contact["rest_ms"].value_label.text() == "5.0 s"
    contact["rest_ms"].slider.setValue(0)
    contact["rest_ms"]._send()
    rule = ui.controller.calls[-1][3]
    assert rule["rest_ms"] == 0
    assert contact["rest_ms"].value_label.text() == "the shockers' own"
    contact["intensity"].slider.setValue(0)                    # 0..100 now
    contact["intensity"]._send()
    assert ui.controller.calls[-1][3]["intensity"] == 0
    assert contact["intensity"].value_label.text() == "0 · nothing"


# --- separate limits for friends (Blise's call, 2026-11-17) ------------------------

def test_the_limits_box_has_the_separate_switch_off_and_one_set(qapp):
    from ui.help_mode import split_tip
    from ui.widgets import ToggleSwitch
    ui, _root = page(qapp)
    shared = ui._pishock_shared_card
    box = _group(shared)
    assert shared.separate in box.findChildren(ToggleSwitch)        # inside the Limits box
    assert not shared.separate.isChecked()                          # off by default
    assert not shared.friends_box.isVisibleTo(shared) and not shared.avatar_head.isVisibleTo(shared)
    title, first = split_tip(shared.separate.toolTip())
    assert title == "Separate limits for friends" and first.startswith("Gives friends limits")
    assert "back to back" in shared.separate.toolTip()              # the trade-off, said plainly
    shared.separate.setChecked(True)
    assert ui.controller.calls[-1] == ("set_pishock_separate_limits", True)


def test_with_separate_limits_on_friends_get_their_own_set_read_as_limits(qapp):
    ui, _root = page(qapp)
    base = ui.controller.get_pishock_status
    friends = {"max_intensity": 20, "max_vibrate": 15, "max_pulse_ms": 400,
               "cooldown_s": 3.0, "max_hold_s": 20.0, "hold_rest_s": 5.0}
    ui.controller.get_pishock_status = lambda: dict(base(), separate_limits=True,
                                                    friend_limits=friends)
    ui._pishock_cards_key = None
    ui.refresh_pishock_status()
    shared = ui._pishock_shared_card
    assert shared.separate.isChecked()
    assert shared.friends_box.isVisibleTo(shared) and shared.avatar_head.isVisibleTo(shared)
    assert "Friends" in _texts(shared.friends_box) and "Your avatar" in _texts(shared)
    labels = {key: s.name_label.text() for key, s in shared.friend_limits.items()}
    assert labels == {"max_intensity": "Up to shock strength",
                      "max_vibrate": "Up to vibrate strength",
                      "max_pulse_ms": "Up to a pulse of",
                      "cooldown_s": "At least a rest of", "max_hold_s": "Up to a hold of",
                      "hold_rest_s": "Then a forced break of"}
    assert list(shared.friend_limits)[:3] == ["max_intensity", "max_vibrate", "max_pulse_ms"]
    assert {k: s.value() for k, s in shared.friend_limits.items()} == friends
    assert shared.friend_limits["max_intensity"].value_label.text() == "20"   # written out
    assert shared.friend_limits["max_pulse_ms"].value_label.text() == "0.4 s"
    shock = shared.friend_limits["max_intensity"]
    shock.slider.setValue(shock.slider.maximum())
    shock._send()
    assert ui.controller.calls[-1] == ("set_pishock_friend_limit", "max_intensity", 100)
    hold = shared.friend_limits["max_hold_s"]
    hold.slider.setValue(hold.slider.minimum())
    hold._send()
    assert ui.controller.calls[-1] == ("set_pishock_friend_limit", "max_hold_s", 1.0)
    ui.controller.get_pishock_status = base                         # switched off again
    ui.refresh_pishock_status()
    assert not shared.separate.isChecked() and not shared.friends_box.isVisibleTo(shared)
