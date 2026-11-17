"""Bars in the fold bars' look that do one thing when clicked: Home's
folded Getting started line and the Toys page's folds (SPS Sources,
Tuning tools)."""

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QFrame, QLabel

from ui.layout_helpers import hbox as _hbox


class ClickBar(QFrame):
    """A bar in the fold bars' look that does one thing when clicked.
    Reachable by Tab, pressed by Space/Return."""

    clicked = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("toolsFoldBar")
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.TabFocus)

    def mousePressEvent(self, ev) -> None:  # noqa: N802
        if ev.button() == Qt.LeftButton:
            self.clicked.emit()
            ev.accept()
        else:
            super().mousePressEvent(ev)

    def keyPressEvent(self, ev) -> None:  # noqa: N802
        if (not ev.isAutoRepeat()
                and ev.key() in (Qt.Key_Space, Qt.Key_Return, Qt.Key_Enter)):
            self.clicked.emit()
            ev.accept()
        else:
            super().keyPressEvent(ev)


class FoldHeader(ClickBar):
    """The clickable bar of a fold: caret, title, and a dim one-line
    summary of what is inside."""

    def __init__(self, title: str, parent=None):
        super().__init__(parent)
        lay = _hbox(0, 8)
        lay.setContentsMargins(12, 7, 12, 7)
        self.setLayout(lay)
        self._caret = QLabel("▸")
        self._caret.setObjectName("expandCaret")
        self._caret.setFixedWidth(14)
        lay.addWidget(self._caret)
        name = QLabel(title)
        name.setObjectName("cardHeader")
        lay.addWidget(name)
        self.summary = QLabel("")
        self.summary.setProperty("hint", "true")
        self.summary.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        lay.addWidget(self.summary, 1)

    def set_open(self, is_open: bool) -> None:
        self._caret.setText("▾" if is_open else "▸")
