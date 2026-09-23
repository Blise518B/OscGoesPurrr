"""Small Qt layout constructors used all over the UI code."""

from PySide6.QtCore import QPoint, QRect, QSize, Qt
from PySide6.QtWidgets import QLayout, QHBoxLayout, QVBoxLayout


def vbox(margin: int = 0, spacing: int = 6) -> QVBoxLayout:
    lay = QVBoxLayout()
    lay.setContentsMargins(margin, margin, margin, margin)
    lay.setSpacing(spacing)
    return lay


def hbox(margin: int = 0, spacing: int = 6) -> QHBoxLayout:
    lay = QHBoxLayout()
    lay.setContentsMargins(margin, margin, margin, margin)
    lay.setSpacing(spacing)
    return lay


def clear_layout(layout):
    """Remove and destroy every child of `layout`."""
    if layout is None:
        return
    while layout.count():
        item = layout.takeAt(0)
        w = item.widget()
        if w is not None:
            # Hide before detaching: reparenting a still-visible child to
            # None can briefly realise it as a top-level window (a flash)
            # before deleteLater() destroys it. Hiding first keeps the
            # teardown invisible.
            w.hide()
            w.setParent(None)
            w.deleteLater()
        else:
            sub = item.layout()
            if sub is not None:
                clear_layout(sub)
                sub.deleteLater()


class FlowLayout(QLayout):
    """Left-to-right layout that wraps items onto the next line when the
    row runs out of width -- the Qt "flowlayout" example, trimmed. Used
    for tool bars whose groups should sit in one row on a wide window
    and stack when the window is narrow, instead of forcing a
    horizontal scroll."""

    def __init__(self, parent=None, margin: int = 0, h_spacing: int = 12,
                 v_spacing: int = 8):
        super().__init__(parent)
        self._items = []
        self._h = h_spacing
        self._v = v_spacing
        self.setContentsMargins(margin, margin, margin, margin)

    # -- QLayout API --
    def addItem(self, item):  # noqa: N802
        self._items.append(item)

    def count(self):
        return len(self._items)

    def itemAt(self, index):  # noqa: N802
        return self._items[index] if 0 <= index < len(self._items) else None

    def takeAt(self, index):  # noqa: N802
        return self._items.pop(index) if 0 <= index < len(self._items) else None

    def expandingDirections(self):  # noqa: N802
        return Qt.Orientations(0)

    def hasHeightForWidth(self):  # noqa: N802
        return True

    def heightForWidth(self, width):  # noqa: N802
        return self._arrange(QRect(0, 0, width, 0), dry=True)

    def setGeometry(self, rect):  # noqa: N802
        super().setGeometry(rect)
        self._arrange(rect, dry=False)

    def sizeHint(self):  # noqa: N802
        return self.minimumSize()

    def minimumSize(self):  # noqa: N802
        size = QSize()
        for item in self._items:
            size = size.expandedTo(item.minimumSize())
        m = self.contentsMargins()
        return size + QSize(m.left() + m.right(), m.top() + m.bottom())

    def _arrange(self, rect, dry: bool) -> int:
        m = self.contentsMargins()
        x = rect.x() + m.left()
        y = rect.y() + m.top()
        right = rect.right() - m.right()
        line_h = 0
        for item in self._items:
            hint = item.sizeHint()
            nx = x + hint.width() + self._h
            if nx - self._h > right + 1 and line_h > 0:
                x = rect.x() + m.left()
                y += line_h + self._v
                nx = x + hint.width() + self._h
                line_h = 0
            if not dry:
                item.setGeometry(QRect(QPoint(x, y), hint))
            x = nx
            line_h = max(line_h, hint.height())
        return y + line_h - rect.y() + m.bottom()
