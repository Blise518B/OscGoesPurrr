"""Fold strip — the Device Routing chain's visual language, shared.

Device Routing's motor signal chain (ui/motor_signal_chain.py)
established the app's "signal flows left → right" design: collapsible
fold cards joined by directional arrows, where each fold's border (its
activity ring) and each arrow charge from idle purple/grey toward
vivid pink as live signal passes through. This module generalises
those design decisions so the backend views (bHaptics, SteamVR,
PiShock, Coyote, OWO) can render their per-item cards in the same
language without depending on the chain widget's router-specific
accordion machinery.

Pieces:

* ``lerp_color`` / ``activity_border_color`` / ``connector_color`` —
  the shared colour ramps (border: dark purple → vivid pink;
  connector: muted grey → vivid pink). Same endpoints as the chain.
* ``FoldCard`` — one collapsible fold: bold title, optional live
  value readout, an always-visible quick row (one-line summary or
  custom widgets), and an editor region revealed on click. The
  border glows via ``set_level``. Reuses objectName
  ``tuneStageCard`` so the global QSS for the chain's stage cells
  applies unchanged.
* ``FoldStrip`` — hosts FoldCards horizontally with elastic spacer
  cells between them and paints the connecting arrows in its own
  paintEvent (behind the cards, so card backgrounds occlude any
  overrun — same trick as the chain's strip host). Clicking a fold
  expands it accordion-style; at most one fold per strip is open.

Unlike the chain's strip, editors here are mounted eagerly (they are
small), there is no rail-squish width animation, and there is no
fork/join branching — backend flows are strictly linear. Everything
visual (colours, arrowheads, hover, epsilon gating) matches the chain
so the tabs read as one design.
"""

from typing import List, Optional, Sequence

from PySide6.QtCore import QPoint, QPointF, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QPainter, QPen, QPolygonF
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QSizePolicy, QWidget

from constants import COLOR_SURFACE, COLOR_SURFACE_HOVER, COLOR_TEXT_MUTED
from ui.layout_helpers import vbox as _vbox, hbox as _hbox

# ---- Shared colour ramp (endpoints copied from motor_signal_chain) ----
# Border: idle dark purple → saturated vivid pink.
BORDER_LOW = "#5030A0"
BORDER_HIGH = "#FF40A0"
# Connector: idle muted grey → the same vivid pink.
_CONNECTOR_IDLE = QColor(COLOR_TEXT_MUTED)
_CONNECTOR_LIVE = QColor(BORDER_HIGH)

# Only restyle when the level moved by at least this much — keeps the
# stylesheet churn far below the UI tick (same gate as the chain).
LEVEL_EPSILON = 0.02

# Connector spacer minimum width; the cells are Expanding so arrows
# genuinely stretch when a neighbour grows.
_CONNECTOR_GAP = 18
# Arrow attach height when a fold is expanded (cards top-align and the
# arrow rides the header row instead of mid-editor).
_HEADER_CENTER_Y = 17


def lerp_color(lo: QColor, hi: QColor, t: float) -> QColor:
    """Channel-wise lerp between two QColors by t in [0, 1] (clamped)."""
    t = max(0.0, min(1.0, float(t)))
    return QColor(
        int(lo.red()   + (hi.red()   - lo.red())   * t),
        int(lo.green() + (hi.green() - lo.green()) * t),
        int(lo.blue()  + (hi.blue()  - lo.blue())  * t),
    )


def activity_border_color(level: float) -> QColor:
    """Border ring colour for a live signal level in [0, 1]."""
    return lerp_color(QColor(BORDER_LOW), QColor(BORDER_HIGH), level)


def connector_color(level: float) -> QColor:
    """Arrow colour for a live signal level in [0, 1]."""
    return lerp_color(_CONNECTOR_IDLE, _CONNECTOR_LIVE, level)


def draw_arrow(p: QPainter, start, end, color: QColor) -> None:
    """Directional arrow from start=(x,y) to end=(x,y); head points
    along the line. Skips degenerate / too-short spans. Identical
    geometry to the chain strip's arrows."""
    x1, y1 = float(start[0]), float(start[1])
    x2, y2 = float(end[0]), float(end[1])
    dx, dy = x2 - x1, y2 - y1
    length = (dx * dx + dy * dy) ** 0.5
    if length < 6.0:
        return
    ux, uy = dx / length, dy / length
    ah = 5.0
    base_x, base_y = x2 - ux * 2.0 * ah, y2 - uy * 2.0 * ah
    pen = QPen(color)
    pen.setWidth(2)
    pen.setCapStyle(Qt.RoundCap)
    p.setPen(pen)
    p.drawLine(QPointF(x1, y1), QPointF(base_x, base_y))
    px, py = -uy, ux
    p.setPen(Qt.NoPen)
    p.setBrush(QBrush(color))
    head = QPolygonF([
        QPointF(x2, y2),
        QPointF(base_x + px * ah, base_y + py * ah),
        QPointF(base_x - px * ah, base_y - py * ah),
    ])
    p.drawPolygon(head)


class FoldCard(QFrame):
    """One collapsible fold in a FoldStrip.

    Regions, top to bottom:
      * Header (always visible): bold title + optional live value.
      * Quick region (visible when collapsed): a one-line muted
        summary (``set_subtitle``) and/or custom widgets added to
        ``quick_layout``.
      * Editor region (visible when expanded): widgets added eagerly
        to ``editor_layout``.

    Clicking anywhere on the card that a child control doesn't consume
    emits ``clicked(fold_id)``; the owning strip handles the accordion
    toggle. The border ring is driven by ``set_level``."""

    clicked = Signal(str)

    def __init__(self, fold_id: str, title: str,
                 show_value: bool = False,
                 expandable: bool = True,
                 parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._fold_id = str(fold_id)
        self._last_level = -1.0
        self._last_value = -1.0
        self._expanded = False
        # Non-expandable folds keep their quick content permanently on
        # display (e.g. the bHaptics live dot grids) — no editor, no
        # pointer cursor, clicks fall through to children only.
        self._expandable = bool(expandable)

        self.setObjectName("tuneStageCard")
        if self._expandable:
            self.setCursor(Qt.PointingHandCursor)
        self.setProperty("active", "false")

        root = _vbox(8, 4)
        self.setLayout(root)

        header = _hbox(0, 6)
        self._header_lay = header
        self._title = QLabel(title)
        tf = self._title.font(); tf.setBold(True)
        self._title.setFont(tf)
        header.addWidget(self._title)
        header.addStretch(1)
        self._value_label: Optional[QLabel] = None
        if show_value:
            self._value_label = QLabel("—")
            self._value_label.setObjectName("stageOutNum")
            self._value_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            header.addWidget(self._value_label)
        root.addLayout(header)

        self._quick = QFrame()
        self._quick.setObjectName("stageQuick")
        self._quick_lay = _vbox(0, 2)
        self._quick.setLayout(self._quick_lay)
        self._subtitle: Optional[QLabel] = None
        root.addWidget(self._quick)

        self._editor = QFrame()
        self._editor.setObjectName("stageEditorRegion")
        self._editor_lay = _vbox(0, 4)
        self._editor.setLayout(self._editor_lay)
        self._editor.setVisible(False)
        root.addWidget(self._editor)

    # ------------------------------------------------------------ basics
    @property
    def fold_id(self) -> str:
        return self._fold_id

    @property
    def quick_layout(self):
        return self._quick_lay

    @property
    def editor_layout(self):
        return self._editor_lay

    def add_header_widget(self, widget: QWidget) -> None:
        """Insert a small widget right after the title (before the
        stretch) — used for Help Mode `?` badges in fold headers."""
        self._header_lay.insertWidget(1, widget)

    def set_subtitle(self, text: str) -> None:
        """One-line muted summary in the quick region (created lazily;
        repeated calls just retext it)."""
        if self._subtitle is None:
            self._subtitle = QLabel("")
            self._subtitle.setProperty("muted", "true")
            self._subtitle.setStyleSheet(f"color: {COLOR_TEXT_MUTED};")
            self._quick_lay.addWidget(self._subtitle)
        if self._subtitle.text() != text:
            self._subtitle.setText(text)

    def mousePressEvent(self, ev) -> None:
        if self._expandable and ev.button() == Qt.LeftButton:
            self.clicked.emit(self._fold_id)
            ev.accept()
        else:
            super().mousePressEvent(ev)

    # ------------------------------------------------------------ state
    def is_expanded(self) -> bool:
        return self._expanded

    def set_expanded(self, expanded: bool) -> None:
        """Show the editor (hiding the quick summary) or collapse back.
        Mirrors the chain cards: the editor replaces the quick row so
        the two never show stale duplicates of the same knob. A no-op
        on non-expandable folds."""
        expanded = bool(expanded) and self._expandable
        if expanded == self._expanded:
            return
        self._expanded = expanded
        self._quick.setVisible(not expanded)
        self._editor.setVisible(expanded)

    # ------------------------------------------------------------ live
    def set_level(self, level: float) -> None:
        """Charge the border ring with the live signal level [0, 1].
        Epsilon-gated so a quiet card costs nothing per tick."""
        try:
            lv = max(0.0, min(1.0, float(level)))
        except (TypeError, ValueError):
            return
        if abs(lv - self._last_level) < LEVEL_EPSILON:
            return
        self._last_level = lv
        color = activity_border_color(lv)
        # Same per-widget override the chain applies to its stage
        # cards — keeps hover/active QSS behaviour intact.
        self.setStyleSheet(
            f"QFrame#tuneStageCard {{"
            f"  background-color: {COLOR_SURFACE_HOVER};"
            f"  border-radius: 8px;"
            f"  border: 1px solid {color.name()};"
            f"  padding: 4px;"
            f"}}"
            f"QFrame#tuneStageCard:hover {{"
            f"  background-color: {COLOR_SURFACE};"
            f"}}"
        )

    def set_value(self, value: float) -> None:
        """Update the live value readout (if enabled), churn-gated."""
        if self._value_label is None:
            return
        try:
            v = max(0.0, min(1.0, float(value)))
        except (TypeError, ValueError):
            return
        if abs(v - self._last_value) < 0.005:
            return
        self._last_value = v
        self._value_label.setText(f"{v:.2f}")


class FoldStrip(QWidget):
    """Horizontal strip of FoldCards with painted connector arrows.

    Cards are separated by elastic spacer cells (min ``_CONNECTOR_GAP``
    wide, expanding) so the arrows stretch as a fold expands. Arrows
    are painted in this widget's paintEvent from live child geometry —
    behind the cards — and tinted per-connector by the level of the
    signal leaving the upstream fold (``set_levels``).

    Clicking a fold expands it and collapses its siblings; clicking it
    again collapses it. While any fold is expanded the cards top-align
    and arrows ride the header row (the chain's behaviour); collapsed
    strips centre the cards and the arrows."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._cards: List[FoldCard] = []
        self._levels: List[float] = []
        self._expanded_id: Optional[str] = None
        self._lay = QHBoxLayout()
        self._lay.setContentsMargins(0, 0, 0, 0)
        self._lay.setSpacing(0)
        self.setLayout(self._lay)

    # ------------------------------------------------------------ build
    def add_fold(self, card: FoldCard) -> FoldCard:
        if self._cards:
            spacer = QWidget()
            spacer.setMinimumWidth(_CONNECTOR_GAP)
            spacer.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)
            # Transparent for mouse events so a click in the gap
            # doesn't swallow anything.
            spacer.setAttribute(Qt.WA_TransparentForMouseEvents, True)
            self._lay.addWidget(spacer)
        self._lay.addWidget(card, 0, Qt.AlignVCenter)
        self._cards.append(card)
        self._levels = [0.0] * len(self._cards)
        card.clicked.connect(self._on_fold_clicked)
        return card

    def cards(self) -> List[FoldCard]:
        return list(self._cards)

    # ------------------------------------------------------------ accordion
    def _on_fold_clicked(self, fold_id: str) -> None:
        target = None if fold_id == self._expanded_id else fold_id
        self._expanded_id = target
        any_open = target is not None
        for card in self._cards:
            card.set_expanded(any_open and card.fold_id == target)
            self._lay.setAlignment(
                card, Qt.AlignTop if any_open else Qt.AlignVCenter)
        self.update()

    # ------------------------------------------------------------ live
    def set_levels(self, levels: Sequence[float]) -> None:
        """`levels[i]` is the live signal LEAVING fold i. Drives fold
        i's border ring and tints the arrow from fold i to fold i+1.
        Cheap when nothing changed — cards epsilon-gate their restyle
        and the repaint only fires on a visible delta."""
        changed = False
        for i, card in enumerate(self._cards):
            lv = float(levels[i]) if i < len(levels) else 0.0
            lv = max(0.0, min(1.0, lv))
            if i < len(self._levels) and abs(lv - self._levels[i]) >= LEVEL_EPSILON:
                changed = True
            self._levels[i] = lv
            card.set_level(lv)
        if changed:
            self.update()

    # ------------------------------------------------------------ paint
    def _card_anchor(self, w: QWidget, right: bool):
        tl = w.mapTo(self, QPoint(0, 0))
        x = tl.x() + (w.width() if right else 0)
        h = max(2, w.height())
        centered = self._expanded_id is None
        y = tl.y() + (h // 2 if centered
                      else min(_HEADER_CENTER_Y, h - 2))
        return (x, y)

    def resizeEvent(self, ev) -> None:
        super().resizeEvent(ev)
        self.update()

    def paintEvent(self, _ev) -> None:
        if len(self._cards) < 2:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        for i in range(len(self._cards) - 1):
            try:
                a = self._cards[i]
                b = self._cards[i + 1]
                if not a.isVisible() or not b.isVisible():
                    continue
                if a.geometry().isEmpty() or b.geometry().isEmpty():
                    continue
                level = self._levels[i] if i < len(self._levels) else 0.0
                draw_arrow(p, self._card_anchor(a, right=True),
                           self._card_anchor(b, right=False),
                           connector_color(level))
            except RuntimeError:
                continue
        p.end()
