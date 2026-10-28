"""Small Qt layout constructors used all over the UI code."""

from typing import Callable, List, Optional

from PySide6.QtCore import QEvent, QPoint, QRect, QSize, Qt
from PySide6.QtWidgets import QBoxLayout, QGridLayout, QHBoxLayout, QLayout, QVBoxLayout, QWidget


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


# ---------------------------------------------------------------------------
# Layouts that follow the width (the Friends page)
# ---------------------------------------------------------------------------

SIDE_GAP = 14            # SideBySide's gap between its two columns


class CardGrid(QWidget):
    """Cards two per row -- one per row once two don't fit: `min_card_w`,
    or what the widest card needs, whichever is more (a card is never
    squeezed under its own minimum). Each card keeps its own height:
    one growing (a toy started) leaves its neighbour as it was."""

    def __init__(self, cards: List[QWidget], min_card_w: int = 300, gap: int = 8,
                 max_cols: int = 2):
        super().__init__()
        self._cards, self._min, self._gap, self._max = list(cards), min_card_w, gap, max_cols
        self._grid = QGridLayout(self)
        self._grid.setContentsMargins(0, 0, 0, 0)
        self._grid.setSpacing(gap)
        # The grid must not pin the widget to two columns' width, or it
        # could never get narrow enough to switch to one.
        self._grid.setSizeConstraint(QLayout.SetNoConstraint)
        self._cols = 0
        self._relayout(min(max_cols, max(1, len(cards))))

    def _relayout(self, cols: int) -> None:
        self._cols = cols
        for c in self._cards:
            self._grid.removeWidget(c)
        for i, c in enumerate(self._cards):
            self._grid.addWidget(c, i // cols, i % cols, Qt.AlignTop)
        for col in range(self._max):
            self._grid.setColumnStretch(col, 1 if col < cols else 0)
        self.updateGeometry()

    def minimumSizeHint(self) -> QSize:
        return QSize(min(self._min, 260), self._grid.minimumSize().height())

    def sizeHint(self) -> QSize:
        return self._grid.sizeHint()

    def _need(self) -> int:
        """The width one column needs: a card that can fold for a narrow
        window (a shocker card) counts with its unfolded width."""
        def need(c) -> int:
            wide = getattr(c, "wide_width", None)
            return wide() if callable(wide) else c.minimumSizeHint().width()
        return max([self._min] + [need(c) for c in self._cards])

    def event(self, event) -> bool:
        # A card grew (a shocker card folding for a narrow window puts a
        # row under its columns): the grid's own layout takes no size from
        # it, so tell the layout around the grid, or the card is squeezed.
        if event.type() == QEvent.LayoutRequest:
            self.updateGeometry()
        return super().event(event)

    def resizeEvent(self, event) -> None:
        fit = max(1, (self.width() + self._gap) // (self._need() + self._gap))
        cols = max(1, min(self._max, fit, len(self._cards)))
        if cols != self._cols:
            self._relayout(cols)
        super().resizeEvent(event)


class SideBySide(QWidget):
    """Two columns side by side -- one under the other once the width drops
    below `breakpoint` (a window snapped to half a screen).
    `on_stack(stacked, width)` lets the owner size its columns for either
    (called again on every resize while stacked)."""

    def __init__(self, left: QWidget, right: QWidget, breakpoint: int,
                 on_stack: Callable[[bool, int], None], spacing: int = SIDE_GAP):
        super().__init__()
        self._left, self._right = left, right
        self._breakpoint, self._on_stack = breakpoint, on_stack
        self._box = QBoxLayout(QBoxLayout.LeftToRight, self)
        self._box.setContentsMargins(0, 0, 0, 0)
        self._box.setSpacing(spacing)
        self._box.setSizeConstraint(QLayout.SetNoConstraint)
        self._box.addWidget(left, 0, Qt.AlignTop)
        self._box.addWidget(right, 1)
        self._box.addStretch(0)          # past the right column's max width: empty
        self._stacked: Optional[bool] = None
        self._apply(False)

    def _apply(self, stacked: bool) -> None:
        self._stacked = stacked
        self._box.setDirection(QBoxLayout.TopToBottom if stacked else QBoxLayout.LeftToRight)
        self._box.setAlignment(self._left, (Qt.AlignTop | Qt.AlignLeft) if stacked else Qt.AlignTop)
        self._on_stack(stacked, self.width())
        self.updateGeometry()

    def minimumSizeHint(self) -> QSize:
        w = max(self._left.minimumSizeHint().width(), self._right.minimumSizeHint().width())
        return QSize(w, self._box.minimumSize().height())

    def sizeHint(self) -> QSize:
        return self._box.sizeHint()

    def resizeEvent(self, event) -> None:
        stacked = self.width() < self._breakpoint
        if stacked != self._stacked:
            self._apply(stacked)
        elif stacked:
            self._on_stack(True, self.width())
        super().resizeEvent(event)
