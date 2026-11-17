"""Ctrl+Z / Ctrl+Y anywhere in the app: the keys, who did it, and asking.

One event filter on the QApplication (`install`), like the wheel guard --
every window and every page, those built later included:

* **The keys.** Ctrl+Z steps back through the app's history of settings
  changes (settings_history.py, through the controller's History facade),
  Ctrl+Y -- or Ctrl+Shift+Z -- forward again, in the main window and the
  popped-out Control window alike. While a text field has focus (a line
  edit, a text box, a spin box being typed in, an editable dropdown) the
  keys are its own: they undo the typing, as everywhere.
* **Who did it.** A save is a step only while the user has just pressed,
  dragged, dropped or typed in the app (`GESTURE_S`) -- never a friend, the
  avatar menu or a timer on its own. The control pressed names the step
  ("changed “Arm shocks”", from its hover explanation's title) and its
  value before is kept, so an undo can go through that same control first
  -- the way doing it by hand would -- before writing to the store.
* **Asking.** A step that would arm shocks asks Arm shocks' own "Arm
  shocks? Yes / No" in the switch's place (ui/views/shocker_switches.py);
  that switch has to be on screen (Home or the Shockers page), else it
  isn't done and the status line says why. Every other question -- a
  shocker or an action back on, a friend allowed more, a limit raised --
  is a Yes / No on the window's own line (HistoryLine): inside the window,
  never a popup.
* **Saying.** What was undone or redone goes on the status line: the main
  window's status bar, the Control window's bar.

`HistoryMixin` wires it into OscGoesPurrrUI."""

import time
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional

import shiboken6
from PySide6.QtCore import QEvent, QObject, Qt, QThread, QTimer
from PySide6.QtWidgets import (
    QAbstractButton, QAbstractScrollArea, QAbstractSlider, QAbstractSpinBox, QApplication,
    QComboBox, QLabel, QLineEdit, QPlainTextEdit, QPushButton, QScrollBar, QTextEdit, QWidget,
)

from constants import BTN_HEIGHT_SMALL
from ui.layout_helpers import hbox

GESTURE_S = 2.0       # a save this soon after the user's last input is theirs
SAME_S = 1.0          # pressing or typing on in the same control this soon: one step
ASK_S = 8.0           # an unanswered question is a No after this long
SAY_S = 6.0           # the Control window's line keeps a message this long

UNDO, REDO = "undo", "redo"

_KEYS = (QEvent.KeyPress,)
_MOUSE = (QEvent.MouseButtonPress, QEvent.MouseButtonDblClick)
_CTRL = Qt.ControlModifier
_SHIFT = Qt.ShiftModifier


def which_key(event) -> Optional[str]:
    """UNDO for Ctrl+Z, REDO for Ctrl+Y and Ctrl+Shift+Z, else None."""
    mods = event.modifiers() & ~Qt.KeypadModifier
    key = event.key()
    if key == Qt.Key_Z and mods == _CTRL:
        return UNDO
    if (key == Qt.Key_Y and mods == _CTRL) or (key == Qt.Key_Z and mods == _CTRL | _SHIFT):
        return REDO
    return None


def editing_text(widget: Optional[QWidget]) -> bool:
    """Is `widget` a text field the user types in? Its own Ctrl+Z then."""
    if widget is None:
        return False
    if isinstance(widget, QLineEdit):
        return not widget.isReadOnly()
    if isinstance(widget, (QTextEdit, QPlainTextEdit)):
        return not widget.isReadOnly()
    if isinstance(widget, QAbstractSpinBox):
        return not widget.isReadOnly()
    if isinstance(widget, QComboBox):
        return widget.isEditable()
    return False


# ---------------------------------------------------------------------------
# The control a change was made on
# ---------------------------------------------------------------------------

def _valued(w: QWidget) -> bool:
    if isinstance(w, QScrollBar):
        return False
    if isinstance(w, QAbstractButton):
        return w.isCheckable()
    return isinstance(w, (QAbstractSlider, QAbstractSpinBox, QComboBox))


def value_widget(w: Optional[QWidget], up: int = 4) -> Optional[QWidget]:
    """The control under a press: `w` or one of its first parents that
    holds a value (a switch, a slider, a spin box, a dropdown -- a
    dropdown's list included). None past a scroll area or a window."""
    while w is not None and up >= 0:
        if _valued(w):
            return w
        if isinstance(w, QAbstractScrollArea):
            # a dropdown's open list: the list, its popup, the dropdown
            p = w.parentWidget()
            for cand in (p, p.parentWidget() if p is not None else None):
                if isinstance(cand, QComboBox):
                    return cand
            return None
        w = w.parentWidget()
        up -= 1
    return None


def read_value(w: QWidget) -> Any:
    if isinstance(w, QAbstractButton):
        return bool(w.isChecked())
    if isinstance(w, (QAbstractSlider, QAbstractSpinBox)):
        return w.value()
    if isinstance(w, QComboBox):
        return w.currentIndex()
    return None


def write_value(w: QWidget, value: Any, quiet: bool = False) -> None:
    """Set a control as a user would (its signals fire), or `quiet`ly
    (only shown)."""
    if quiet:
        w.blockSignals(True)
    try:
        if isinstance(w, QAbstractButton):
            if w.isChecked() != bool(value):
                if quiet:
                    w.setChecked(bool(value))
                else:
                    w.click()           # clicked and toggled, as a press
        elif isinstance(w, (QAbstractSlider, QAbstractSpinBox)):
            w.setValue(value)
        elif isinstance(w, QComboBox):
            w.setCurrentIndex(int(value))
    finally:
        if quiet:
            w.blockSignals(False)
            w.update()


def label_of(w: Optional[QWidget]) -> str:
    """A control's name: the title of its hover explanation (its own, or
    the nearest one above it), else a switch's own text."""
    from ui.help_mode import split_tip
    node, up = w, 0
    while node is not None and up <= 4:
        tip = node.toolTip()
        if tip:
            title = split_tip(tip)[0].strip()
            if title:
                return title
        node = node.parentWidget()
        up += 1
    if isinstance(w, QAbstractButton) and w.isCheckable():
        return w.text().replace("&", "").strip()
    return ""


class WidgetRef:
    """A widget held without trusting it outlives its page: `data()` is
    None once Qt deleted it (a card rebuilt, a page redrawn)."""

    def __init__(self, widget: QWidget):
        self._w = widget

    def data(self) -> Optional[QWidget]:
        w = self._w
        return w if w is not None and shiboken6.isValid(w) else None


@dataclass
class ControlRef:
    """The control a step was made on, what it held before, and (filled in
    at undo) what it held after."""
    widget: Any            # WidgetRef of a control with a value, or None
    before: Any
    label: str
    t: float
    after: Any = None
    used: bool = False
    src: Any = None        # WidgetRef of what was pressed or typed in

    def alive(self) -> Optional[QWidget]:
        w = self.widget.data() if self.widget is not None else None
        try:
            if w is None or not w.isEnabled():
                return None
        except RuntimeError:
            return None
        return w


def replay(control: Any, undo: bool) -> bool:
    """Ctrl+Z / Ctrl+Y through the step's own control: set back to what it
    held before (undo) or after (redo), its signals firing as by hand."""
    if not isinstance(control, ControlRef):
        return False
    w = control.alive()
    if w is None:
        return False
    if undo:
        control.after = read_value(w)
        target = control.before
    else:
        target = control.after
    if target is None:
        return False
    write_value(w, target)
    return True


def resync(control: Any, undo: bool) -> None:
    """After an undo the store did itself: the control shows it."""
    if not isinstance(control, ControlRef):
        return
    w = control.alive()
    target = control.before if undo else control.after
    if w is not None and target is not None and read_value(w) != target:
        write_value(w, target, quiet=True)


# ---------------------------------------------------------------------------
# A window's line: what was undone, and the questions
# ---------------------------------------------------------------------------

class HistoryLine(QWidget):
    """A line in a window's bar: a message, and while a step asks, its
    question with Yes / No. Hidden while it has nothing to say."""

    def __init__(self, parent=None, say_s: float = SAY_S, compact: bool = False):
        """`compact`: in a status bar (the theme sizes its buttons there)."""
        super().__init__(parent)
        self.setObjectName("historyLine")
        lay = hbox(0, 6)
        self.setLayout(lay)
        self.text = QLabel("")
        self.text.setObjectName("historyText")
        self.text.setTextFormat(Qt.PlainText)
        lay.addWidget(self.text, 1, Qt.AlignVCenter)
        self.yes = QPushButton("Yes")
        self.yes.setProperty("role", "danger")
        self.no = QPushButton("No")
        self.no.setProperty("role", "secondary")
        for b in (self.yes, self.no):
            b.setCursor(Qt.PointingHandCursor)
            if not compact:
                b.setFixedHeight(BTN_HEIGHT_SMALL)
            lay.addWidget(b, 0, Qt.AlignVCenter)
        self.yes.clicked.connect(lambda _=False: self._answer(True))
        self.no.clicked.connect(lambda _=False: self._answer(False))
        self._then: Optional[Callable[[bool], None]] = None
        self._say_s = say_s
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._timeout)
        self._set_buttons(False)
        self.hide()

    @property
    def asking(self) -> bool:
        return self._then is not None

    def _set_buttons(self, on: bool) -> None:
        self.yes.setVisible(on)
        self.no.setVisible(on)

    def say(self, text: str) -> None:
        if self.asking:
            return
        self.text.setText(text)
        self._set_buttons(False)
        self.setVisible(bool(text))
        if text and self._say_s:
            self._timer.start(int(self._say_s * 1000))

    def ask(self, text: str, then: Callable[[bool], None], seconds: float = ASK_S) -> bool:
        if self.asking:
            return False
        self._then = then
        self.text.setText(text)
        self._set_buttons(True)
        self.show()
        self._timer.start(int(seconds * 1000))
        return True

    def _timeout(self) -> None:
        if self.asking:
            self._answer(False)
        else:
            self.hide()

    def _answer(self, yes: bool) -> None:
        then, self._then = self._then, None
        self._timer.stop()
        self._set_buttons(False)
        self.hide()
        if then is not None:
            then(bool(yes))


# ---------------------------------------------------------------------------
# The filter
# ---------------------------------------------------------------------------

class HistoryKeys(QObject):
    """Ctrl+Z / Ctrl+Y outside text fields, and the user's last input."""

    def __init__(self, on_key: Callable[[str, QWidget], None], parent=None,
                 clock: Callable[[], float] = time.monotonic):
        super().__init__(parent)
        self._on_key = on_key
        self.clock = clock
        self.last_input = -1e9
        self.pending: Optional[ControlRef] = None
        self.on_boundary: Optional[Callable[[], None]] = None
        self._last_stamp = None
        self._thread = QThread.currentThread()
        self.focus: Callable[[], Optional[QWidget]] = QApplication.focusWidget

    # who did it
    def user_active(self) -> bool:
        if QThread.currentThread() is not self._thread:
            return False
        return self.clock() - self.last_input <= GESTURE_S

    def context(self) -> Dict[str, Any]:
        p = self.pending
        if p is None or self.clock() - self.last_input > GESTURE_S:
            return {}
        label = f"changed “{p.label}”" if p.label else ""
        if p.used or p.widget is None:
            return {"label": label}
        p.used = True
        return {"label": label, "control": p}

    def _touched(self, w: Optional[QWidget], stamp=None) -> None:
        now = self.clock()
        if stamp is not None and stamp == self._last_stamp:
            self.last_input = now
            return                      # the same press, handed up to a parent
        self._last_stamp = stamp
        target = value_widget(w)
        src = target if target is not None else w
        p = self.pending
        same = (p is not None and src is not None and p.src is not None
                and p.src.data() is src and now - self.last_input <= SAME_S)
        self.last_input = now
        if same:
            return          # nudging the same control, typing on: one step
        if self.on_boundary is not None:
            self.on_boundary()
        if target is None:
            self.pending = ControlRef(None, None, label_of(w), now,
                                      src=WidgetRef(w) if w is not None else None)
        else:
            self.pending = ControlRef(WidgetRef(target), read_value(target), label_of(target),
                                      now, src=WidgetRef(target))

    def eventFilter(self, obj, event) -> bool:  # noqa: N802
        kind = event.type()
        if kind in _MOUSE:
            if isinstance(obj, QWidget):
                self._touched(obj, ("m", event.timestamp()))
            return False
        if kind == QEvent.MouseMove:
            if event.buttons() != Qt.NoButton:
                self.last_input = self.clock()      # a drag goes on
            return False
        if kind == QEvent.Drop:
            self.last_input = self.clock()
            return False
        if kind == QEvent.ShortcutOverride:
            if which_key(event) and not editing_text(self.focus()):
                event.accept()              # ours: nothing else takes it
            return False
        if kind in _KEYS:
            what = which_key(event)
            if what is None:
                if event.key() not in (Qt.Key_Control, Qt.Key_Shift, Qt.Key_Alt, Qt.Key_Meta) \
                        and isinstance(obj, QWidget):
                    self._touched(self.focus() or obj, ("k", event.timestamp()))
                return False
            if editing_text(self.focus()):
                return False                # the text field's own undo
            if event.isAutoRepeat():
                return True
            win = obj.window() if isinstance(obj, QWidget) else QApplication.activeWindow()
            self._on_key(what, win)
            return True
        return False


_keys: Optional[HistoryKeys] = None


def install(app: QApplication, on_key: Callable[[str, QWidget], None]) -> HistoryKeys:
    """Once per application; a second call hands the keys to `on_key`."""
    global _keys
    if _keys is None:
        _keys = HistoryKeys(on_key, app)
        app.installEventFilter(_keys)
    else:
        _keys._on_key = on_key
    return _keys


def uninstall(app: QApplication) -> None:
    """Take the filter off again (tests)."""
    global _keys
    if _keys is not None:
        app.removeEventFilter(_keys)
        _keys = None


# ---------------------------------------------------------------------------
# The UI mixin
# ---------------------------------------------------------------------------

class HistoryMixin:
    """Ctrl+Z / Ctrl+Y on OscGoesPurrrUI. Assumes `self.controller`,
    `self.qapp`, `self.window` and `set_status_message`."""

    _history_keys: Optional[HistoryKeys] = None

    def _history_install(self) -> None:
        keys = install(self.qapp, self._history_key)
        self._history_keys = keys
        set_input = getattr(self.controller, "history_set_input", None)
        if set_input is not None:
            set_input(keys.user_active, keys.context)
        boundary = getattr(self.controller, "history_boundary", None)
        keys.on_boundary = boundary
        bar = self.window.statusBar() if hasattr(self.window, "statusBar") else None
        self._history_line = HistoryLine(say_s=0, compact=True)
        if bar is not None:
            bar.insertWidget(1, self._history_line)
        self.window.history_line = self._history_line

    # -- the keys -----------------------------------------------------------------

    def _history_key(self, what: str, win: Optional[QWidget]) -> None:
        win = win or self.window
        go = getattr(self.controller, "history_undo" if what == UNDO else "history_redo", None)
        if go is None:
            return
        state: Dict[str, Any] = {"hint": ""}

        def ask(asks: List[Dict[str, str]], text: str, answer) -> bool:
            return self._history_ask(win, asks, text, answer, what, state)

        result = go(ask, replay)
        if result.get("status") == "asking":
            return
        self._history_done(win, result, what, state.get("hint", ""))

    def _history_done(self, win: QWidget, result: Dict[str, Any], what: str,
                      hint: str = "") -> None:
        text = result.get("text", "")
        if hint and result.get("status") == "blocked":
            text = f"{text} - {hint}"
        if result.get("status") == "done":
            control = result.get("control")
            if control is not None:
                resync(control, what == UNDO)
        self._history_say(win, text)

    def _history_say(self, win: Optional[QWidget], text: str) -> None:
        line = getattr(win, "history_line", None) if win is not None else None
        if line is not None and win is not self.window:
            line.say(text)
        else:
            self.set_status_message(text)

    # -- asking -------------------------------------------------------------------

    def _history_ask(self, win: QWidget, asks: List[Dict[str, str]], text: str, answer,
                     what: str, state: Dict[str, Any]) -> bool:
        def finished(result: Dict[str, Any]) -> None:
            self._history_done(win, result, what)

        if any(a.get("kind") == "arm" for a in asks):
            arm = self._history_arm_switch(win)
            if arm is None:
                state["hint"] = ("go to Home or the Shockers page and press it again: "
                                 "Arm shocks asks there")
                return False
            others = [a["text"] for a in asks if a.get("kind") != "arm"]
            if others:
                self._history_say(win, "Arm shocks? It also " + "; ".join(others))
            return arm.ask_first(lambda yes: finished(answer(yes)))
        line = getattr(win, "history_line", None)
        if line is None:
            return False
        verb = "Undo" if what == UNDO else "Redo"
        question = f"{verb}? It {'; '.join(a['text'] for a in asks)}."
        return line.ask(question, lambda yes: finished(answer(yes)))

    @staticmethod
    def _history_arm_switch(win: QWidget):
        """Arm shocks' switch on screen in this window (Home's shocker row,
        the Shockers page's Hub card), if one is."""
        from ui.views.shocker_switches import ArmSwitch
        for arm in win.findChildren(ArmSwitch):
            try:
                if arm.isVisible():
                    return arm
            except RuntimeError:
                continue
        return None

    # -- a Settings value came back -------------------------------------------------

    def history_app_restored(self, keys: List[str]) -> None:
        """Controller facade: app settings got old values back. What the
        Settings page shows that no control of the step did: the Features
        switches and the sidebar, the colours."""
        c = self.controller
        if any(k.startswith("feature_") for k in keys):
            for name in ("_sync_feature_toggles", "apply_feature_visibility"):
                fn = getattr(self, name, None)
                if fn is not None:
                    fn()
        for key, attr in (("auto_refresh", "auto_refresh_var"),
                          ("auto_connect", "auto_connect_var"),
                          ("avatar_modes_enabled", "avatar_modes_toggle")):
            w = getattr(self, attr, None)
            if key in keys and isinstance(w, QAbstractButton):
                write_value(w, bool(c.get_app_setting(key)), quiet=True)
        if "auto_refresh" in keys:
            fn = getattr(self, "refresh_link_buttons", None)
            if fn is not None:
                fn()
        if "ui_mode" in keys and hasattr(self, "_set_ui_mode"):
            self._set_ui_mode(c.get_app_setting("ui_mode") or "neon")
        if "ui_accent_hue" in keys and hasattr(self, "_apply_accent_pick"):
            self._accent_pick = c.get_app_setting("ui_accent_hue")
            self._apply_accent_pick()
        if "ui_identity_hues" in keys and hasattr(self, "_apply_identity_pick"):
            self._identity_pick = dict(c.get_app_setting("ui_identity_hues") or {})
            self._apply_identity_pick()
