"""Arm shocks, Share with friends and On / Off -- one setting each, shown on
Home's shocker row and the Shockers page (ui/views/shocker_switches.py).

Home and the page are built side by side on the real PiShock facade (its
settings in the test's tmp folder, the engine never started): a flip in
either place reaches the one setting, and the "pishock_state" the facade
posts redraws the other. Also: arming from Home is remembered across
launches; ARM_ASKS_FROM decides where arming asks first (Blise's answer:
both places -- each other answer still tested), and the question is the
switch's own row -- Yes / No in its place, never a window; red words beside
Arm say Shocks armed / Shocks not armed in both places, from the setting;
and the hover explanations say how the switches stack."""

import queue
import sys

import pytest
from PySide6.QtCore import QEvent, QObject
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication, QLabel, QVBoxLayout, QWidget

import test_home_devices as _hd
import ui_components as uc
from controllers.pishock_facade import FEATURE_KEY, PiShockFacade
from ui import help_mode, page_steps, theme
from ui.views import shocker_switches


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication(sys.argv[:1])


@pytest.fixture
def no_asking(monkeypatch):
    monkeypatch.setattr(shocker_switches, "ARM_ASKS_FROM", frozenset())


class Ctl(PiShockFacade, _hd.FakeController):
    """Home's fake controller with the real shocker facade in front of it."""

    def __init__(self, friends=True):
        _hd.FakeController.__init__(
            self, {"feature_friends": friends},
            profiles={"Alpha": {"motor_count": 1}}, connected={"Alpha"})
        self.thread_queue = queue.Queue()
        self.logged = []
        self.ui = None
        self._pishock_init()                 # feature still off: nothing starts
        self.features[FEATURE_KEY] = True    # ... but the page and Home show

    def is_output_off(self):
        return False

    def log_message(self, msg):
        self.logged.append(msg)

    def pump(self):
        """What main.py's queue loop does with the facade's messages."""
        while True:
            try:
                kind, _data = self.thread_queue.get_nowait()
            except queue.Empty:
                return
            if kind == "pishock_state":
                self._pishock_state_changed()


def launch(friends=True):
    """A controller and a UI with Home and the Shockers page both built."""
    ctl = Ctl(friends)
    ui = uc.OscGoesPurrrUI.__new__(uc.OscGoesPurrrUI)
    ui.controller = ctl
    ui.window = QWidget()
    ui.views = {}
    ui.nav_buttons = {}
    ui.main_stack = None
    ui.intiface_sidebar_section = None
    ui.device_ui_frames = {}
    ui.stored_device_frames = {}
    ui.unified_devices_layout = None
    ui.select_view = lambda name: None
    ui._build_home_view(QVBoxLayout(ui.window))
    ui.build_stored_devices_ui()
    ui.update_stored_devices_ui()
    ui._shockers_page = QWidget()
    ui._build_pishock_view(QVBoxLayout(ui._shockers_page))
    ui._refresh_home_devices()
    ctl.ui = ui
    ctl.pump()
    return ctl, ui


@pytest.fixture
def both(qapp):
    made = []

    def make(friends=True):
        ctl, ui = launch(friends)
        made.append(ctl)
        return ctl, ui
    yield make
    for ctl in made:
        ctl._pishock_shutdown()


def said(ui):
    """The red words beside Arm: (Home's row, the page)."""
    return ui._home_shockers_row.arm.status.text(), ui._pishock_arm.status.text()


def shown(ui):
    """What each place shows: (Home's row, the page)."""
    row = ui._home_shockers_row
    return ({"armed": row.arm.isChecked(), "share": row.share.isChecked(),
             "on": row.power.isChecked()},
            {"armed": ui._pishock_arm.isChecked(), "share": ui._pishock_share.isChecked(),
             "on": ui._pishock_stop_btn.text() == "Stop all"})


# --- one setting, shown in both places --------------------------------------

def test_arming_on_home_shows_on_the_page_and_back(both, no_asking):
    ctl, ui = both()
    assert shown(ui)[0]["armed"] is shown(ui)[1]["armed"] is False
    ui._home_shockers_row.arm.switch.click()                # on Home
    ctl.pump()
    assert ctl.pishock_settings.get_armed() and ctl.pishock_engine.is_armed
    assert shown(ui)[0]["armed"] and shown(ui)[1]["armed"]
    assert said(ui) == ("Shocks armed", "Shocks armed")
    ui._pishock_arm.switch.click()                          # off on the page
    ctl.pump()
    assert not ctl.pishock_settings.get_armed() and not ctl.pishock_engine.is_armed
    assert not shown(ui)[0]["armed"] and not shown(ui)[1]["armed"]


def test_arming_on_the_page_shows_on_home(both, no_asking):
    ctl, ui = both()
    ui._pishock_arm.switch.click()
    ctl.pump()
    assert shown(ui)[0]["armed"] and ctl.pishock_engine.is_armed
    # no hub plugged in here: OFFLINE wins the pill, the switch says armed
    assert ui._home_shockers_row.pill.text() == "OFFLINE"
    assert ui._home_shockers_row.arm.isChecked()


def test_sharing_is_one_setting_both_ways(both):
    ctl, ui = both()
    assert shown(ui) == ({"armed": False, "share": True, "on": True},
                         {"armed": False, "share": True, "on": True})
    ui._home_shockers_row.share.click()
    ctl.pump()
    assert ctl.pishock_settings.get_friends_may_use() is False
    assert not shown(ui)[1]["share"]
    ui._pishock_share.click()
    ctl.pump()
    assert ctl.pishock_settings.get_friends_may_use() is True
    assert shown(ui)[0]["share"]


def test_on_off_and_stop_all_are_one_setting_both_ways(both):
    ctl, ui = both()
    ui._home_shockers_row.power.click()                      # Off on Home
    ctl.pump()
    assert ctl.pishock_engine.is_paused and not shown(ui)[1]["on"]
    assert ui._pishock_stop_btn.text() == "Resume"
    ui._pishock_stop_btn.click()                             # Resume on the page
    ctl.pump()
    assert not ctl.pishock_engine.is_paused and shown(ui)[0]["on"]


def test_no_copy_of_the_state_anywhere(both):
    """Changed behind both pages' backs (the facade alone), each shows it
    after the redraw the facade posts."""
    ctl, ui = both()
    ctl.set_pishock_armed(True)
    ctl.set_pishock_friends_may_use(False)
    ctl.pishock_stop_all()
    ctl.pump()
    expected = {"armed": True, "share": False, "on": False}
    assert shown(ui) == (expected, expected)


def test_the_app_redraws_both_places_on_a_pishock_state():
    """main.py's queue loop hands "pishock_state" to the facade, which
    redraws the page and Home's row (what Ctl.pump stands in for)."""
    import inspect
    import main
    src = inspect.getsource(main.OscGoesPurrrApp)
    at = src.index('msg_type == "pishock_state"')
    assert "self._pishock_state_changed()" in src[at:src.index("elif", at)]


def test_without_friends_neither_place_offers_sharing(both):
    _ctl, ui = both(friends=False)
    assert ui._home_shockers_row.share.isHidden()
    assert not ui._pishock_share_box.isVisibleTo(ui._shockers_page)
    assert not ui._home_shockers_row.arm.isHidden()          # arming still is


def test_arming_from_home_is_remembered_across_launches(both, no_asking):
    ctl, ui = both()
    ui._home_shockers_row.arm.switch.click()
    ctl.pump()
    ctl._pishock_shutdown()
    again, ui2 = both()                                      # the next launch
    assert again.pishock_engine.is_armed is True
    assert shown(ui2) == ({"armed": True, "share": True, "on": True},
                          {"armed": True, "share": True, "on": True})
    ui2._pishock_arm.switch.click()                          # disarmed on the page
    again.pump()
    again._pishock_shutdown()
    third, ui3 = both()
    assert third.pishock_engine.is_armed is False
    assert not shown(ui3)[0]["armed"]


# --- armed or not, in red, in both places -----------------------------------

def test_the_red_words_follow_the_setting_in_both_places(both):
    """Asked and answered in either place, both places' words change at
    once -- and only when the setting does: never while the question is up."""
    ctl, ui = both()
    assert said(ui) == ("Shocks not armed", "Shocks not armed")
    home = ui._home_shockers_row.arm
    home.switch.click()                                   # asks ...
    ctl.pump()
    assert home.asking and said(ui) == ("Shocks not armed", "Shocks not armed")
    # the question takes the words' place too (it says as much); the page's stay
    assert home.status.isHidden() and not ui._pishock_arm.status.isHidden()
    home.yes.click()                                      # ... Yes on Home
    ctl.pump()
    assert said(ui) == ("Shocks armed", "Shocks armed")
    assert not home.status.isHidden()
    ui._pishock_arm.switch.click()                        # off on the page
    ctl.pump()
    assert said(ui) == ("Shocks not armed", "Shocks not armed")
    page = ui._pishock_arm
    page.switch.click()                                   # asks on the page too
    assert page.asking
    page._timer.timeout.emit()                            # unanswered: words back
    assert not page.asking and not page.status.isHidden()
    assert said(ui) == ("Shocks not armed", "Shocks not armed")
    page.switch.click()
    page.yes.click()
    ctl.pump()
    assert said(ui) == ("Shocks armed", "Shocks armed")
    ctl.set_pishock_armed(False)                          # behind both backs
    ctl.pump()
    assert said(ui) == ("Shocks not armed", "Shocks not armed")


def test_the_red_words_are_the_themes_danger_red(both):
    """The theme's "alert" label role, which is its err red -- no hex of
    their own -- and armed reads bold."""
    ctl, ui = both()
    for arm in (ui._home_shockers_row.arm, ui._pishock_arm):
        assert arm.status.property("role") == "alert"
        assert "color" not in (arm.status.styleSheet() or "")
    probe = QWidget()
    probe.setStyleSheet(theme.build_qss())
    label = QLabel("x", probe)
    label.setProperty("role", "alert")
    label.ensurePolished()
    assert label.palette().color(QPalette.WindowText) == QColor(theme.qss_vars()["err"])
    ctl.set_pishock_armed(True)
    ctl.pump()
    assert ui._pishock_arm.status.font().bold()
    assert ui._home_shockers_row.arm.status.font().bold()


def test_armed_reads_bold_in_both_places_under_the_apps_style(both):
    """With the app's stylesheet on, as in the running app: a style sheet's
    font wins over setFont, so "Shocks armed" read bold on Home but plain
    on the Shockers page. The bold comes from the theme now."""
    ctl, ui = both()
    for arm in (ui._home_shockers_row.arm, ui._pishock_arm):
        arm.status.window().setStyleSheet(theme.build_qss())
    ctl.set_pishock_armed(True)
    ctl.pump()
    for arm in (ui._home_shockers_row.arm, ui._pishock_arm):
        arm.status.ensurePolished()
        assert arm.status.font().bold(), arm
    ctl.set_pishock_armed(False)
    ctl.pump()
    for arm in (ui._home_shockers_row.arm, ui._pishock_arm):
        arm.status.ensurePolished()
        assert not arm.status.font().bold(), arm


def test_arming_never_shifts_the_row(both):
    """The words keep room for the wider of the two, so the switch beside
    them (right-aligned on Home) doesn't jump when shocks are armed."""
    ctl, ui = both()
    for arm in (ui._home_shockers_row.arm, ui._pishock_arm):
        width = arm.sizeHint().width()
        assert arm.status.minimumWidth() >= arm.status.sizeHint().width()
        ctl.set_pishock_armed(True)
        ctl.pump()
        assert arm.status.text() == "Shocks armed"
        assert arm.status.minimumWidth() >= arm.status.sizeHint().width()
        assert arm.sizeHint().width() == width
        ctl.set_pishock_armed(False)
        ctl.pump()
        arm.switch.click()                       # the question never widens it
        assert arm.asking and arm.sizeHint().width() <= width
        arm.no.click()
        assert arm.sizeHint().width() == width


def test_a_wider_question_never_widens_the_row_either(both):
    """Where a font makes "Arm shocks? Yes / No" wider than the switch and
    its words (Linux's stand-in for Segoe UI, CI 0.16.0), the words keep
    that much more room, so asking still never widens the row. Forced here
    with a wide Yes, so it holds whatever the font; the question itself,
    its timeout and the words are untouched."""
    ctl, ui = both()
    for arm in (ui._home_shockers_row.arm, ui._pishock_arm):
        plain = arm.sizeHint().width()
        arm.yes.setMinimumWidth(plain)                  # the question: wider than it all
        arm.set_armed(False)                            # a redraw measures again
        width = arm.sizeHint().width()
        assert width >= arm.ask.sizeHint().width() > plain
        assert arm.status.text() == shocker_switches.NOT_ARMED_TEXT and not arm.isChecked()
        arm.switch.click()
        assert arm.asking and arm.sizeHint().width() <= width
        assert arm.question.text() == shocker_switches.ARM_TEXT + "?"
        arm.set_armed(False)                            # a redraw while asking keeps the room
        assert arm.asking and arm.sizeHint().width() <= width
        arm.no.click()
        assert not arm.asking and not arm.isChecked()
        assert arm.sizeHint().width() == width
        arm.yes.setMinimumWidth(0)                      # back to the real question
        arm.set_armed(False)
        assert arm.sizeHint().width() == plain


def test_no_second_armed_pill_beside_the_words(both):
    ctl, ui = both()
    ctl.set_pishock_armed(True)
    ctl.pump()
    assert not hasattr(ui, "_pishock_armed_pill")
    assert ui._home_shockers_row.pill.text() != "ARMED"


def test_the_red_words_explain_themselves(both):
    _ctl, ui = both()
    for arm in (ui._home_shockers_row.arm, ui._pishock_arm):
        title, first = help_mode.split_tip(arm.status.toolTip())
        assert title == "Shocks armed or not"
        assert first.startswith("Whether your shocks are real right now")
        assert first.endswith(".") and "Shocks not armed" in first, first
        # Arm's own explanation names the words it means
        assert "Shocks armed or Shocks not armed" in arm.switch.toolTip()


def test_the_shockers_steps_point_at_arm_and_its_words(both):
    """Help mode and the group gallery find the arm step's controls by their
    explanations' titles: the switch and the red words, together."""
    _ctl, ui = both()
    step = next(s for s in page_steps.for_page("Shockers") if s.label == "Arm shocks")
    assert step.target == ("Arm shocks", "Shocks armed or not")
    ui._shockers_page.resize(1100, 1400)
    ui._shockers_page.show()
    try:
        QApplication.instance().processEvents()
        found = [help_mode.find_control([ui._shockers_page], t) for t in step.target]
        assert found == [ui._pishock_arm.switch, ui._pishock_arm.status]
    finally:
        ui._shockers_page.hide()


# --- asking before arming, in the switch's own place -------------------------

def test_arming_asks_in_both_places(both):
    """Blise's call (2026-11-14): arm from Home or the page, and both ask."""
    assert shocker_switches.ARM_ASKS_FROM == frozenset({"home", "page"})
    ctl, ui = both()
    for where in ("home", "page"):
        arm = arm_of(ui, where)
        assert "asks first" in arm.switch.toolTip()
        arm.switch.click()
        ctl.pump()
        assert arm.asking and not ctl.pishock_engine.is_armed
        arm.no.click()
        ctl.pump()
        assert not arm.asking and not ctl.pishock_engine.is_armed


def arm_of(ui, where):
    return ui._home_shockers_row.arm if where == "home" else ui._pishock_arm


@pytest.mark.parametrize("where_asks", [frozenset(), frozenset({"home"}),
                                        frozenset({"home", "page"})])
def test_arm_asks_first_where_blise_says(both, monkeypatch, where_asks):
    monkeypatch.setattr(shocker_switches, "ARM_ASKS_FROM", where_asks)
    for where in ("home", "page"):
        ctl, ui = both()
        arm = arm_of(ui, where)
        arm.switch.click()
        ctl.pump()
        if where in where_asks:
            # the question, in the switch's place -- nothing armed yet
            assert arm.asking and arm.switch.isHidden() and not arm.ask.isHidden()
            assert not ctl.pishock_engine.is_armed and not ctl.pishock_settings.get_armed()
            arm.no.click()                                    # No
            ctl.pump()
            assert not arm.asking and not arm.switch.isHidden()
            assert not arm.isChecked() and not ctl.pishock_engine.is_armed
            arm.switch.click()                                # ask again ...
            assert arm.asking
            arm._timer.timeout.emit()                         # ... nobody answers
            ctl.pump()
            assert not arm.asking and not arm.isChecked()
            assert not ctl.pishock_engine.is_armed
            arm.switch.click()
            arm.yes.click()                                   # Yes
            ctl.pump()
        assert not arm.asking
        assert ctl.pishock_engine.is_armed and ctl.pishock_settings.get_armed()
        assert shown(ui) == ({"armed": True, "share": True, "on": True},
                             {"armed": True, "share": True, "on": True})
        arm.switch.click()                                    # disarming never asks
        assert not arm.asking
        ctl.pump()
        assert not ctl.pishock_engine.is_armed
        ctl._pishock_shutdown()


def test_the_question_gives_up_by_itself(qapp, monkeypatch):
    """Its own timer: ARM_ASK_S, then it is off again, nothing sent.
    Waited for rather than slept on: late in the full suite thousands of
    earlier tests' widgets keep Qt's loop so busy that a 150 ms wait could
    end before the 30 ms timeout was delivered (Ubuntu, 0.16.1's checks)."""
    import time
    from PySide6.QtTest import QTest
    monkeypatch.setattr(shocker_switches, "ARM_ASKS_FROM", frozenset({"x"}))
    sent = []
    arm = shocker_switches.ArmSwitch("x", sent.append)
    assert arm._timer.interval() == int(shocker_switches.ARM_ASK_S * 1000)
    arm._timer.setInterval(30)
    arm.switch.click()
    assert arm.asking
    deadline = time.monotonic() + 3     # under ARM_ASK_S: only the 30 ms timer ends it
    while arm.asking and time.monotonic() < deadline:
        QTest.qWait(10)
    assert not arm.asking and not arm.isChecked() and sent == []


def test_a_redraw_keeps_the_question_unless_armed_elsewhere(both, monkeypatch):
    monkeypatch.setattr(shocker_switches, "ARM_ASKS_FROM", frozenset({"home"}))
    ctl, ui = both()
    arm = ui._home_shockers_row.arm
    arm.switch.click()
    ui._refresh_home_devices()                    # Home's 2 Hz tick: still off
    assert arm.asking
    ui._pishock_arm.switch.click()                # armed on the page meanwhile
    ctl.pump()
    assert not arm.asking and arm.isChecked() and ctl.pishock_engine.is_armed


def test_asking_never_opens_a_window(both, monkeypatch):
    """A VR overlay that captures only the main window shows no popup: the
    question stays inside the window."""
    monkeypatch.setattr(shocker_switches, "ARM_ASKS_FROM", frozenset({"home", "page"}))
    opened = []

    class Spy(QObject):
        def eventFilter(self, obj, ev):
            if ev.type() == QEvent.Show and isinstance(obj, QWidget) and obj.isWindow():
                opened.append(type(obj).__name__)
            return False

    _ctl, ui = both()
    ui.window.show()
    ui._shockers_page.show()
    spy = Spy()
    qapp = QApplication.instance()
    qapp.processEvents()
    qapp.installEventFilter(spy)
    try:
        for where in ("home", "page"):
            arm = arm_of(ui, where)
            arm.switch.click()
            qapp.processEvents()
            assert arm.asking and arm.yes.isVisible() and arm.window() in (
                ui.window, ui._shockers_page)
            arm.no.click()
    finally:
        qapp.removeEventFilter(spy)
        ui.window.hide()
        ui._shockers_page.hide()
    assert opened == []


# --- how the switches stack ------------------------------------------------

def test_every_switch_says_how_they_stack(both):
    _ctl, ui = both()
    row = ui._home_shockers_row
    for w in (row.share, row.arm.switch, row.power,
              ui._pishock_share, ui._pishock_arm.switch, ui._pishock_stop_btn):
        tip = w.toolTip()
        assert "How the shocker switches stack" in tip, tip
        # help mode shows the first sentence alone: the stack stays out of it
        _title, first = help_mode.split_tip(tip)
        assert "stack" not in first and first.endswith("."), first


def test_the_question_explains_itself(both):
    _ctl, ui = both()
    for arm in (ui._home_shockers_row.arm, ui._pishock_arm):
        title, first = help_mode.split_tip(arm.ask.toolTip())
        assert title == "Arm shocks?" and first.startswith("Yes arms your shocks")


def test_the_stack_names_the_switches_in_order():
    order = ["<b>On</b>", "<b>Arm shocks</b>", "<b>Share with friends</b>",
             "<b>Shockers</b>"]
    at = [shocker_switches.STACK.index(name) for name in order]
    assert at == sorted(at)


def test_home_and_the_page_call_arm_shocks_the_same(both):
    _ctl, ui = both()
    row = ui._home_shockers_row
    assert row.arm.switch.text() == ui._pishock_arm.switch.text() == "Arm shocks"
    assert row.share.text() == ui._pishock_share.text()
    for w in (row.arm.switch, ui._pishock_arm.switch):
        assert help_mode.split_tip(w.toolTip())[0] == "Arm shocks"
