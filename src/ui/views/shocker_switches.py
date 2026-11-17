"""The shocker hub's switches, the same on Home's shocker row and the
Shockers page's Hub card (friends' review, 2026-11-14: arm and share in one
place, shown everywhere):

  * On / Off      -- the hub for everyone (the page's Stop all / Resume);
  * Arm shocks    -- shocks are real; until then each goes out as a vibrate;
  * Share with friends -- friends (and the web remote) see the shockers at all.

Each is ONE setting, kept by settings/pishock.py behind the controller's
PiShock facade: a flip in either place goes there, the facade posts
"pishock_state", and both places redraw from get_pishock_status() -- no
second copy of the state anywhere. Here: what they say on hover (one
paragraph, STACK, says how they stack) and the Arm switch itself
(ArmSwitch), which asks first where ARM_ASKS_FROM says -- in its own place,
inside the window: a VR overlay that captures only the main window never
shows a popup, and there a switch waiting on one would just look broken --
and says in red beside it whether shocks are armed (Blise's call,
2026-11-14: "so you kind of know what is going on")."""

from typing import Callable

from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QFont, QFontMetrics
from PySide6.QtWidgets import QLabel, QPushButton, QWidget

from constants import BTN_HEIGHT_SMALL
from ui.layout_helpers import hbox as _hbox
from ui.widgets import ToggleSwitch

# Where switching Arm shocks ON asks "are you sure" first: "home" (Home's
# shocker row), "page" (the Shockers page). Switching it off never asks.
# Blise's call (2026-11-14): both -- you can arm from either, and either
# asks. frozenset() = never, {"home"} = from Home only.
ARM_ASKS_FROM = frozenset({"home", "page"})

# How long the question waits for Yes before it falls back to off.
ARM_ASK_S = 5.0

ARM_TEXT = "Arm shocks"
SHARE_TEXT = "Share with friends"

# The red words beside the switch, from the setting (never the switch's
# look while it asks), and their hover title.
ARMED_TEXT = "Shocks armed"
NOT_ARMED_TEXT = "Shocks not armed"
STATUS_TITLE = "Shocks armed or not"

# How the switches stack -- the same paragraph under each of them.
STACK = (
    "<br><br><b>How the shocker switches stack</b>, from everyone to one friend:"
    "<br><b>On</b> (the hub) → <b>Arm shocks</b> (real shocks) → "
    "<b>Share with friends</b> (friends at all) → each friend's own "
    "<b>Shockers</b> switch on the Friends page (and the web remote's)."
    "<br>Off stops everything, whatever the rest say. Unarmed, every shock - "
    "yours or a friend's - is a vibrate. Not shared, no friend sees your "
    "shockers. Home's shocker row and the Shockers page show the same switches.")


def arm_tip(where: str) -> str:
    """Arm shocks' hover explanation on Home ("home") or the page ("page")."""
    ask = (" Switching it on here asks first, in the switch's place: Yes arms."
           if where in ARM_ASKS_FROM else "")
    return ("Until this is on, every shock - a behaviour's, a friend's, a test - "
            "goes out as a vibrate instead." + ask + " The red words beside it "
            "say which it is now: " + ARMED_TEXT + " or " + NOT_ARMED_TEXT + ". "
            "It stays as you leave it, across restarts too." + STACK)


STATUS_TIP = (
    "Whether your shocks are real right now: " + ARMED_TEXT + ", or "
    + NOT_ARMED_TEXT + " - then every shock goes out as a vibrate. It follows "
    "the one Arm shocks setting, so Home's shocker row and the Shockers page "
    "always say the same.")


SHARE_TIP = (
    "Sharing only, for all your friends at once: off, your friends don't see "
    "your shockers at all and nothing they send reaches them, whatever their "
    "own Shockers switch on the Friends page says. Your own rules and the "
    "Shockers page still work." + STACK)

POWER_TIP = (
    "Your shockers, all of it. Off ends whatever they are doing now and keeps "
    "them quiet - your rules, friends, tests - until you switch them on again, "
    "even after a restart; friends don't see them meanwhile. The hub stays "
    "connected, and who may use them stays as you set it. The same as Stop "
    "all / Resume on the Shockers page." + STACK)

STOP_TIP = (
    "Ends whatever every shocker is doing right now and keeps them quiet until "
    "you press Resume - even after a restart. The same as the On / Off switch "
    "on Home's shocker row. The sidebar's Off silences the shockers too, along "
    "with the toys." + STACK)

ASK_TIP = (
    "Yes arms your shocks: from then on every shock is real - your "
    "behaviours', your avatar menu's, and your friends' where you share your "
    "shockers with them. No, or a few seconds without an answer, leaves them "
    "unarmed. Armed, they stay armed until you switch it off, even after a "
    "restart.")


class ArmSwitch(QWidget):
    """Arm shocks: a switch that, switched on where ARM_ASKS_FROM says,
    turns into "Arm shocks? Yes / No" in its own place for ARM_ASK_S
    seconds, then falls back to off. Only Yes (or a place that doesn't
    ask) hands it on: on_arm(on) -- to the controller, the one place it is
    kept. Switching off never asks. Beside it, `status` says in the
    theme's red ("alert") whether shocks are armed -- hidden while the
    question is up, which says as much (and Home's row at 960 px has no
    room for both).

    A redraw from get_pishock_status() calls set_armed(): shown, never
    reported -- the only thing that changes `status`, so it says the
    setting, not the switch's look. An unanswered question stays up through
    one (the setting is still off), unless the setting turned on elsewhere
    meanwhile."""

    def __init__(self, where: str, on_arm: Callable[[bool], None], parent=None):
        super().__init__(parent)
        self._where = where
        self._on_arm = on_arm
        lay = _hbox(0, 6)
        self.setLayout(lay)

        self.switch = ToggleSwitch(ARM_TEXT)
        self.switch.toggled.connect(self._flipped)
        lay.addWidget(self.switch, 0, Qt.AlignVCenter)

        # the question, in the switch's place while it is up
        self.ask = QWidget()
        al = _hbox(0, 6)
        self.ask.setLayout(al)
        self.question = QLabel(ARM_TEXT + "?")
        al.addWidget(self.question, 0, Qt.AlignVCenter)
        self.yes = QPushButton("Yes")
        self.yes.setProperty("role", "danger")          # shocks become real
        self.no = QPushButton("No")
        self.no.setProperty("role", "secondary")
        for btn in (self.yes, self.no):
            btn.setFixedHeight(BTN_HEIGHT_SMALL)
            btn.setCursor(Qt.PointingHandCursor)
            al.addWidget(btn, 0, Qt.AlignVCenter)
        self.yes.clicked.connect(lambda: self._answer(True))
        self.no.clicked.connect(lambda: self._answer(False))
        self.ask.hide()
        lay.addWidget(self.ask, 0, Qt.AlignVCenter)

        # armed or not, in red, from the setting
        self.status = QLabel(NOT_ARMED_TEXT)
        self.status.setObjectName("armStatus")
        self.status.setProperty("role", "alert")        # the theme's danger red
        lay.addSpacing(6)
        lay.addWidget(self.status, 0, Qt.AlignVCenter)
        self._fit_status()

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(int(ARM_ASK_S * 1000))
        self._timer.timeout.connect(lambda: self._answer(False))
        # Ctrl+Z / Ctrl+Y waiting on the question (ask_first): the answer
        # goes there instead of on_arm
        self._answer_to = None

    def mousePressEvent(self, ev) -> None:  # noqa: N802
        # a click on the question (or between its buttons) is the switch's:
        # it never falls through to Home's row, which would open the page
        ev.accept()

    @property
    def asking(self) -> bool:
        """The question is up, waiting for Yes."""
        return not self.ask.isHidden()

    def isChecked(self) -> bool:  # noqa: N802 -- reads like the switch it is
        return self.switch.isChecked()

    def set_armed(self, on: bool) -> None:
        """What the setting is now (a redraw): shown, never reported."""
        if on and self.asking:
            then, self._answer_to = self._answer_to, None
            self._close(True)               # armed elsewhere meanwhile
            if then is not None:
                then(False)                 # nothing left for Ctrl+Z to arm
        self._show_switch(on)
        text = ARMED_TEXT if on else NOT_ARMED_TEXT
        if self.status.text() != text:
            self.status.setText(text)
            font = self.status.font()
            font.setBold(bool(on))          # armed reads louder
            self.status.setFont(font)
            # ... and the theme says so too (`armed`): where a style sheet
            # gives the label a font, that font beats setFont, and the
            # Shockers page showed "Shocks armed" plain
            self.status.setProperty("armed", "true" if on else "false")
            self.status.style().unpolish(self.status)
            self.status.style().polish(self.status)
        self._fit_status()                  # (the page's style may have come since)

    def _fit_status(self) -> None:
        """Room for the wider of the two, so arming never shifts the row."""
        self.status.ensurePolished()
        bold, plain = QFont(self.status.font()), QFont(self.status.font())
        bold.setBold(True)
        plain.setBold(False)
        self.status.setMinimumWidth(max(
            QFontMetrics(bold).horizontalAdvance(ARMED_TEXT),
            QFontMetrics(plain).horizontalAdvance(NOT_ARMED_TEXT)) + 2)

    def _flipped(self, on: bool) -> None:
        if on and self._where in ARM_ASKS_FROM:
            self._put_question()
            return
        self._on_arm(bool(on))

    def _put_question(self) -> None:
        self._show_switch(False)            # not armed until Yes
        self.switch.hide()
        self.status.hide()
        self.ask.show()
        self._timer.start()

    def ask_first(self, on_answer: Callable[[bool], None]) -> bool:
        """Ctrl+Z or Ctrl+Y would arm shocks (ui/history_keys.py): the same
        question as switching it on by hand, in the switch's place, and the
        same few seconds; Yes or No goes to `on_answer` -- the history then
        arms through the controller, the one place it is kept. False when
        it can't ask now (shocks are armed already, or it is asking)."""
        if self.asking or self.switch.isChecked():
            return False
        self._answer_to = on_answer
        self._put_question()
        return True

    def _answer(self, yes: bool) -> None:
        if not self.asking:
            return
        then, self._answer_to = self._answer_to, None
        self._close(yes)
        if then is not None:
            then(bool(yes))
        elif yes:
            self._on_arm(True)

    def _close(self, on: bool) -> None:
        self._timer.stop()
        self.ask.hide()
        self._show_switch(on)
        self.switch.show()
        self.status.show()

    def _show_switch(self, on: bool) -> None:
        if self.switch.isChecked() != bool(on):
            self.switch.blockSignals(True)
            self.switch.setChecked(bool(on))
            self.switch.blockSignals(False)
