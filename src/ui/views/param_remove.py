"""The strip above the Avatar Remote page's parameter list that follows a
drop onto it (params.py): a control dragged back to the list is gone at
once and the strip offers Undo for a few seconds; a whole category asks
here first. In the window, never a popup -- a VR overlay that captures the
window doesn't show popup windows.

The strip only says and asks; the page does the removing and the putting
back (through the controller's Params facade)."""

from typing import Any, Callable, Optional

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QFrame, QLabel, QPushButton

from ui.layout_helpers import hbox

UNDO_S = 8          # how long Undo is offered
NOTE_S = 5          # ... and a note with nothing to press stays


class RemoveStrip(QFrame):
    """Hidden until something was dropped on the list. `key` is the board
    it is about (avatar, preset): the page lets it go when that board is
    no longer the one open."""

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("paramRemoveStrip")
        lay = hbox(0, 8)
        lay.setContentsMargins(10, 6, 6, 6)
        self.setLayout(lay)
        self.text = QLabel("")
        self.text.setObjectName("paramRemoveText")
        self.text.setWordWrap(True)
        self.text.setTextFormat(Qt.PlainText)
        lay.addWidget(self.text, 1)
        self.undo = self._button("Undo", "secondary")
        self.yes = self._button("Remove", "danger")
        self.no = self._button("Keep", "secondary")
        for b in (self.undo, self.yes, self.no):
            lay.addWidget(b, 0, Qt.AlignVCenter)
        self.undo.clicked.connect(lambda _=False: self._go())
        self.yes.clicked.connect(lambda _=False: self._go())
        self.no.clicked.connect(lambda _=False: self.dismiss())
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.dismiss)
        self._then: Optional[Callable[[], None]] = None
        self.key: Any = None
        self.mode = ""
        self.hide()

    @staticmethod
    def _button(text: str, role: str) -> QPushButton:
        b = QPushButton(text)
        b.setProperty("role", role)
        b.setCursor(Qt.PointingHandCursor)
        return b

    def _show(self, mode: str, text: str, key: Any, then, seconds: float) -> None:
        self.mode, self.key, self._then = mode, key, then
        self.text.setText(text)
        self.undo.setVisible(mode == "undo")
        self.yes.setVisible(mode == "ask")
        self.no.setVisible(mode == "ask")
        if self.property("tone") != mode:
            self.setProperty("tone", mode)
            self.style().unpolish(self)
            self.style().polish(self)
        if seconds > 0:
            self._timer.start(int(seconds * 1000))
        else:
            self._timer.stop()             # a question waits for its answer
        self.show()

    def offer_undo(self, text: str, key: Any, undo: Callable[[], None]) -> None:
        """Something just went: Undo for UNDO_S seconds."""
        self._show("undo", text, key, undo, UNDO_S)

    def ask(self, text: str, key: Any, remove: Callable[[], None]) -> None:
        """Remove or Keep -- until answered (or its board isn't open)."""
        self._show("ask", text, key, remove, 0)

    def note(self, text: str) -> None:
        self._show("note", text, None, None, NOTE_S)

    def dismiss(self) -> None:
        self._timer.stop()
        self._then, self.key, self.mode = None, None, ""
        self.hide()

    def keep_only_for(self, key: Any) -> None:
        """The page shows board `key` now: an Undo or question about another
        one goes (a note about nothing in particular stays)."""
        if self.mode in ("undo", "ask") and self.key != key:
            self.dismiss()

    def _go(self) -> None:
        then = self._then
        self.dismiss()
        if then is not None:
            then()                         # it may put up the next message
