"""Ctrl+Z / Ctrl+Y in the app's windows, headless (ui/history_keys.py):
the keys outside text fields and the text field's own undo inside one; a
change made on a control undone through that same control; the questions
-- Arm shocks' own in the switch's place, a Yes / No on the window's line
for the rest -- and a step that can't ask staying undone; the Control
window's own line; and the controller's History facade between them."""

import sys

import pytest
from PySide6.QtCore import QEvent, QPoint, Qt
from PySide6.QtGui import QKeyEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import (
    QApplication, QLineEdit, QMainWindow, QPushButton, QSlider, QStatusBar, QTextEdit,
    QVBoxLayout, QWidget,
)

import settings_history as sh
from controllers.history_facade import HistoryFacade
from settings_history import SettingsHistory
from ui import history_keys as hk
from ui.views.shocker_switches import ArmSwitch
from ui.widgets import ToggleSwitch


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication(sys.argv[:1])


def key(widget, k, mods=Qt.ControlModifier):
    QApplication.sendEvent(widget, QKeyEvent(QEvent.KeyPress, k, mods))
    QApplication.sendEvent(widget, QKeyEvent(QEvent.KeyRelease, k, mods))


# ---------------------------------------------------------------------------
# the keys
# ---------------------------------------------------------------------------

class Keys:
    """The filter on a window with a text field, a text box and a switch."""

    def __init__(self, qapp):
        self.calls = []
        self.win = QWidget()
        lay = QVBoxLayout(self.win)
        self.edit = QLineEdit()
        self.log = QTextEdit()
        self.log.setReadOnly(True)
        self.switch = ToggleSwitch("Thing")
        for w in (self.edit, self.log, self.switch):
            lay.addWidget(w)
        self.win.show()
        self.filter = hk.HistoryKeys(lambda what, win: self.calls.append((what, win)))
        self.focused = None
        self.filter.focus = lambda: self.focused
        qapp.installEventFilter(self.filter)
        self.qapp = qapp

    def done(self):
        self.qapp.removeEventFilter(self.filter)
        self.win.close()


@pytest.fixture
def keys(qapp):
    k = Keys(qapp)
    yield k
    k.done()


def test_ctrl_z_and_ctrl_y_outside_text_fields_are_the_apps(keys):
    keys.focused = keys.switch
    key(keys.switch, Qt.Key_Z)
    key(keys.switch, Qt.Key_Y)
    key(keys.switch, Qt.Key_Z, Qt.ControlModifier | Qt.ShiftModifier)
    assert [c[0] for c in keys.calls] == ["undo", "redo", "redo"]
    assert keys.calls[0][1] is keys.win          # the window it was pressed in
    key(keys.switch, Qt.Key_Z, Qt.NoModifier)    # plain Z: nothing of ours
    assert len(keys.calls) == 3


def test_a_text_field_keeps_its_own_undo(keys):
    keys.focused = keys.edit
    keys.edit.setText("")
    QTest.keyClicks(keys.edit, "abc")
    assert keys.edit.text() == "abc"
    key(keys.edit, Qt.Key_Z)
    assert keys.calls == [] and keys.edit.text() == ""       # the typing went
    key(keys.edit, Qt.Key_Y)
    assert keys.calls == [] and keys.edit.text() == "abc"


def test_a_read_only_text_box_is_no_text_field(keys):
    keys.focused = keys.log
    key(keys.log, Qt.Key_Z)
    assert [c[0] for c in keys.calls] == ["undo"]


def test_editing_text_knows_the_kinds():
    from PySide6.QtWidgets import QComboBox, QPlainTextEdit, QSpinBox
    assert hk.editing_text(QLineEdit()) and hk.editing_text(QSpinBox())
    assert hk.editing_text(QPlainTextEdit())
    ro = QLineEdit()
    ro.setReadOnly(True)
    assert not hk.editing_text(ro)
    combo = QComboBox()
    assert not hk.editing_text(combo)
    combo.setEditable(True)
    assert hk.editing_text(combo)
    assert not hk.editing_text(QPushButton()) and not hk.editing_text(None)


def test_typing_on_or_nudging_one_control_is_one_step(keys):
    """Each keystroke in a field that saves as you type, each arrow on a
    slider: the same control within a second starts no new step."""
    starts = []
    keys.filter.on_boundary = lambda: starts.append(1)
    keys.focused = keys.edit
    QTest.keyClicks(keys.edit, "hello")
    assert len(starts) == 1
    QTest.mouseClick(keys.switch, Qt.LeftButton, Qt.NoModifier, QPoint(5, 5))
    assert len(starts) == 2                     # another control: a new step


def test_a_press_names_the_control_and_keeps_its_value(keys):
    keys.switch.setToolTip("<b>Arm the thing</b><br>What it does.")
    QTest.mouseClick(keys.switch, Qt.LeftButton, Qt.NoModifier, QPoint(5, 5))
    assert keys.filter.user_active()
    ctx = keys.filter.context()
    assert ctx["label"] == "changed “Arm the thing”"
    assert ctx["control"].before is False and ctx["control"].alive() is keys.switch
    assert "control" not in keys.filter.context()     # one step per press


# ---------------------------------------------------------------------------
# through the History facade, with real stores
# ---------------------------------------------------------------------------

class Ctl(HistoryFacade):
    """The controller: the history, and what an undo of the shocker store
    tells the engine (here: noted)."""

    def __init__(self, history):
        self.settings_history = history
        self.engine_armed = []

    def pishock_restored(self, changes):
        self.engine_armed.append(self.pishock.get_armed())


class UI(hk.HistoryMixin):
    """A main window with a status bar, Arm shocks on it (Home's row)."""

    def __init__(self, qapp, ctl, arm=True):
        self.qapp, self.controller = qapp, ctl
        self.window = QMainWindow()
        self.window.setStatusBar(QStatusBar())
        body = QWidget()
        lay = QVBoxLayout(body)
        self.arm = ArmSwitch("home", lambda on: None)
        self.arm.setVisible(arm)
        self.switch = ToggleSwitch("Share")
        self.slider = QSlider(Qt.Horizontal)
        self.slider.setRange(0, 100)
        for w in (self.arm, self.switch, self.slider):
            lay.addWidget(w)
        self.window.setCentralWidget(body)
        self.messages = []
        self._history_install()
        self.window.show()

    def set_status_message(self, text):
        self.messages.append(text)

    def press_undo(self, win=None):
        self._history_key("undo", win or self.window)

    def press_redo(self, win=None):
        self._history_key("redo", win or self.window)


@pytest.fixture
def world(qapp, tmp_path):
    from settings.pishock import PiShockSettingsManager
    h = SettingsHistory()
    old = sh.activate(h)
    ctl = Ctl(h)
    ctl.pishock = PiShockSettingsManager()
    h.on_restored(ctl.pishock, ctl.pishock_restored)
    ui = UI(qapp, ctl)
    # the UI made its input tracker the judge; most tests save by hand
    h.gate = lambda: True
    h.context = lambda: {}
    yield ui, ctl, h
    ui.window.close()
    hk.uninstall(qapp)
    sh.activate(old)


def test_an_undo_that_would_arm_asks_in_the_switchs_place(world, qapp):
    ui, ctl, h = world
    h.gate = lambda: True                       # (the presses are the test's)
    ctl.pishock.set_armed(True)
    h.boundary()
    ctl.pishock.set_armed(False)
    ui.press_undo()
    assert ui.arm.asking and ctl.pishock.get_armed() is False
    QTest.mouseClick(ui.arm.yes, Qt.LeftButton)
    assert not ui.arm.asking
    assert ctl.pishock.get_armed() is True and ctl.engine_armed == [True]
    assert ui.messages[-1].startswith("Undid: ")


def test_no_or_no_answer_keeps_shocks_unarmed(world, qapp):
    ui, ctl, h = world
    ctl.pishock.set_armed(True)
    h.boundary()
    ctl.pishock.set_armed(False)
    ui.press_undo()
    QTest.mouseClick(ui.arm.no, Qt.LeftButton)
    assert ctl.pishock.get_armed() is False and h.can_undo()
    assert ui.messages[-1].startswith("Kept as it is")


def test_without_arm_shocks_on_screen_it_isnt_done(world, qapp):
    ui, ctl, h = world
    ui.arm.hide()                               # another page
    ctl.pishock.set_armed(True)
    h.boundary()
    ctl.pishock.set_armed(False)
    ui.press_undo()
    assert ctl.pishock.get_armed() is False and h.can_undo()
    assert "Home or the Shockers page" in ui.messages[-1]
    assert "arms shocks" in ui.messages[-1]


def test_a_raised_limit_asks_yes_no_on_the_windows_line(world, qapp):
    ui, ctl, h = world
    ctl.pishock.set_limit("max_intensity", 20)
    ui.press_undo()                             # back to 30: raised
    line = ui._history_line
    assert line.asking and "“Up to shock strength” to 30" in line.text.text()
    assert ctl.pishock.get_limits()["max_intensity"] == 20
    QTest.mouseClick(line.yes, Qt.LeftButton)
    assert ctl.pishock.get_limits()["max_intensity"] == 30
    assert not line.asking and ui.messages[-1].startswith("Undid: ")
    ui.press_redo()                             # lowering it again never asks
    assert ctl.pishock.get_limits()["max_intensity"] == 20


def test_ctrl_z_in_the_control_window_says_it_there(world, qapp):
    from ui.views.friends_window import ControlWindow
    ui, ctl, h = world
    win = ControlWindow(lambda: None, lambda: None, lambda on: None)
    win.show()
    try:
        ctl.pishock.set_armed(True)
        h.boundary()
        ctl.pishock.set_armed(False)
        ui.press_undo(win)                      # no Arm shocks in there
        assert ctl.pishock.get_armed() is False
        assert win.history_line.isVisible() and "arms shocks" in win.history_line.text.text()
        ctl.pishock.set_auto_connect(True)
        ui.press_undo(win)
        assert ctl.pishock.get_auto_connect() is False
        assert win.history_line.text.text().startswith("Undid: ")
        # its questions are asked in there too
        h.boundary()
        ctl.pishock.set_limit("max_vibrate", 10)
        ui.press_undo(win)
        assert win.history_line.asking
        QTest.mouseClick(win.history_line.yes, Qt.LeftButton)
        assert ctl.pishock.get_limits()["max_vibrate"] == 30
    finally:
        win.close()


def test_undo_goes_through_the_control_it_was_made_on(world, qapp):
    """The switch's own handler is what puts it back -- as by hand."""
    ui, ctl, h = world
    keys = ui._history_keys
    h.gate = keys.user_active
    h.context = keys.context
    handled = []

    def toggled(on):
        handled.append(on)
        ctl.pishock.set_auto_connect(on)
    ui.switch.toggled.connect(toggled)
    ui.switch.setToolTip("<b>Connect on start</b><br>x")
    QTest.mouseClick(ui.switch, Qt.LeftButton, Qt.NoModifier, QPoint(5, 5))
    assert ctl.pishock.get_auto_connect() is True and h.can_undo()
    ui.press_undo()
    assert handled == [True, False]             # undone by the switch itself
    assert not ui.switch.isChecked() and ctl.pishock.get_auto_connect() is False
    assert ui.messages[-1] == "Undid: changed “Connect on start”"
    ui.press_redo()
    assert ui.switch.isChecked() and ctl.pishock.get_auto_connect() is True


def test_the_control_shows_what_the_store_got(world, qapp):
    """A slider whose own handler isn't what saved (it saves on release,
    say): after Yes the store gets the old value written back, and the
    slider is moved to show it, quietly."""
    ui, ctl, h = world
    keys = ui._history_keys
    h.gate = keys.user_active
    h.context = keys.context
    ui.slider.setValue(30)
    moved = []
    ui.slider.valueChanged.connect(moved.append)
    QTest.mousePress(ui.slider, Qt.LeftButton, Qt.NoModifier, QPoint(2, 5))
    ui.slider.setValue(70)
    ctl.pishock.set_limit("max_vibrate", 10)
    QTest.mouseRelease(ui.slider, Qt.LeftButton, Qt.NoModifier, QPoint(2, 5))
    del moved[:]
    ui.press_undo()                             # 10 back to 30 raises it: asked
    assert ui._history_line.asking
    QTest.mouseClick(ui._history_line.yes, Qt.LeftButton)
    assert ctl.pishock.get_limits()["max_vibrate"] == 30
    assert ui.slider.value() == 30 and moved == []       # shown, not set


def test_the_avatar_remote_strip_undoes_through_the_history(world, qapp):
    ui, ctl, h = world
    h.gate = lambda: True
    with sh.action() as act:
        pass
    key_obj = {"snap": 1}
    undone = []
    act.done("removed Ears from the Avatar Remote",
             lambda: undone.append(1) or True, lambda: True, key=key_obj)
    assert ctl.history_undo_action({"other": 1}) is None
    r = ctl.history_undo_action(key_obj)
    assert r["status"] == "done" and undone == [1] and h.can_redo()
    assert ctl.history_undo_action(key_obj) is None       # not the newest any more


def test_history_status_names_both_ways(world):
    ui, ctl, h = world
    assert ctl.history_status() == {"undo": "", "redo": ""}
    ctl.pishock.set_auto_connect(True)
    st = ctl.history_status()
    assert st["undo"] and st["redo"] == ""


def test_startup_makes_the_history_before_any_store():
    import inspect
    import main
    init = inspect.getsource(main.OscGoesPurrrApp.__init__)
    assert init.index("self._history_init()") < init.index("ModeManager()")
    setup = inspect.getsource(main.OscGoesPurrrApp._setup_components)
    assert setup.index("self._history_hooks()") < setup.index("OscGoesPurrrUI(self)")
    assert setup.index("self._pishock_init()") < setup.index("self._history_hooks()")
    assert setup.index("self._friends_init()") < setup.index("self._history_hooks()")
