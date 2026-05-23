"""Help Mode widgets — toggle-driven `?` badges anchored to controls,
each opening a small popover with a title and short explanation.

The badges live alongside the controls they explain; the popover is a
`Qt.Popup`-flagged QFrame so clicks outside dismiss it automatically.
Visibility is driven from the UI mixin's `_set_help_badges_visible`,
which iterates the registered badges on every Help Mode toggle.

Layout-stability promise: badges call `setRetainSizeWhenHidden(True)`
so toggling Help Mode flips visibility without reflowing the
surrounding controls."""

from PySide6.QtCore import Qt, QPoint
from PySide6.QtWidgets import (
    QApplication, QFrame, QLabel, QToolButton, QVBoxLayout,
)


class HelpBadge(QToolButton):
    """Small `?` button placed next to a control."""

    def __init__(self, title: str, text: str, parent=None):
        super().__init__(parent)
        self.setText("?")
        self.setFixedSize(16, 16)
        self.setCursor(Qt.PointingHandCursor)
        self.setProperty("role", "helpBadge")
        # Keep the badge's layout slot even when hidden so toggling
        # Help Mode doesn't shuffle the surrounding widgets.
        sp = self.sizePolicy()
        sp.setRetainSizeWhenHidden(True)
        self.setSizePolicy(sp)
        self._title = title
        self._text = text
        self.clicked.connect(self._show_popover)
        # Hidden by default; the registering UI sets the right state.
        self.setVisible(False)

    def _show_popover(self):
        popover = HelpPopover(self._title, self._text, parent=self)
        popover.adjustSize()
        anchor = self.mapToGlobal(QPoint(0, self.height() + 4))
        screen = QApplication.screenAt(anchor)
        if screen is not None:
            avail = screen.availableGeometry()
            # Flip above the badge if it would render off the bottom.
            if anchor.y() + popover.height() > avail.bottom():
                anchor = self.mapToGlobal(QPoint(0, -popover.height() - 4))
            # Slide left so the popover stays on-screen when the badge
            # sits near the right edge (common in the bar's right-side
            # group). Clamp to the left edge as well so it never slides
            # off-screen the other way.
            if anchor.x() + popover.width() > avail.right():
                anchor.setX(avail.right() - popover.width())
            if anchor.x() < avail.left():
                anchor.setX(avail.left())
        popover.move(anchor)
        popover.show()


class HelpPopover(QFrame):
    """Floating popover anchored to a HelpBadge. `Qt.Popup` means any
    click outside dismisses it; the badge owns it so it dies with its
    anchor on widget-tree rebuild (profile switch, etc.)."""

    def __init__(self, title: str, text: str, parent=None):
        super().__init__(parent, Qt.Popup)
        self.setObjectName("helpPopover")
        self.setMinimumWidth(280)
        self.setMaximumWidth(360)

        lay = QVBoxLayout()
        lay.setContentsMargins(14, 12, 14, 12)
        lay.setSpacing(6)
        self.setLayout(lay)

        title_lbl = QLabel(title)
        tf = title_lbl.font()
        tf.setBold(True)
        tf.setPointSize(max(tf.pointSize(), 11))
        title_lbl.setFont(tf)
        lay.addWidget(title_lbl)

        body = QLabel(text)
        body.setWordWrap(True)
        body.setTextFormat(Qt.RichText)
        lay.addWidget(body)
