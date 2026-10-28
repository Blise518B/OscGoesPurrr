"""Help mode: a page explained on the page itself.

F1, the status bar's Show me around or a Help card's Show me switches it on
for the page on screen; Esc, F1 again or Done switches it off. While it is
on:

* a strip over the page lists what you do there in a few numbered steps
  (ui/page_steps.py -- the VRChat gallery draws the same ones). Each
  step's control stays lit with its number on it; resting on a step rings
  its control and points at it, a click scrolls it into view and keeps it;
* resting the mouse on any control lights it, the rest of the window dims
  a little, and a small bubble says what it is: its hover explanation's
  title and first sentence (ui/tooltips.py -- the whole text is there
  again once help mode is off);
* clicks on the window do nothing, so looking around never changes a
  setting -- except on the strip, the sidebar's pages (help mode follows
  to the next page), scroll bars and anything outside the window's body.

It reads nothing from the controller and keeps no state beyond what is
lit: the explanations are the widgets' own tooltips, the steps come from
page_steps, and the colours are the theme's at paint time, so the colour
picker needs nothing from it. It only runs while it is on.
"""

from __future__ import annotations

import html
import math
import re
from typing import Callable, List, Optional, Sequence, Tuple

from PySide6.QtCore import QEvent, QObject, QPoint, QPointF, QRect, QRectF, QSize, Qt, QTimer
from PySide6.QtGui import (QColor, QCursor, QFont, QFontMetricsF, QPainter, QPainterPath, QPen,
                           QTextDocument)
from PySide6.QtWidgets import (QAbstractButton, QApplication, QHBoxLayout, QLabel, QLineEdit,
                               QPushButton, QScrollArea, QScrollBar, QStackedWidget, QToolTip,
                               QWidget)
from shiboken6 import isValid

from ui import theme as _theme
from ui.layout_helpers import FlowLayout

_TIP = re.compile(r"^\s*<b>(.*?)</b>\s*(?:<br\s*/?>)?(.*)$", re.S | re.I)
_SENTENCE = re.compile(r"^(.+?[.!?])(?:\s|$)", re.S)
POLL_MS = 60            # how often the pointer and the steps' controls are looked at
RETRY_TICKS = 16        # a step whose control is not on screen is looked for again after this
DIM_ALPHA = 96          # how dark the rest of the window goes
BUBBLE_W = 320
_SWALLOWED = (QEvent.MouseButtonPress, QEvent.MouseButtonRelease,
              QEvent.MouseButtonDblClick, QEvent.ContextMenu)


# ---------------------------------------------------------------------------
# Reading the window: explanations, controls, where they are
# ---------------------------------------------------------------------------

def _plain(text: str) -> str:
    if "<" not in text and "&" not in text:
        return " ".join(text.split())
    doc = QTextDocument()
    doc.setHtml(text)
    return " ".join(doc.toPlainText().split())


def split_tip(tip: str) -> Tuple[str, str]:
    """(title, first sentence) of a hover explanation -- all a help-mode
    bubble shows of it."""
    m = _TIP.match(tip or "")
    title, body = (m.group(1), m.group(2)) if m else (tip or "", "")
    body = _plain(body)
    first = _SENTENCE.match(body)
    return _plain(title), (first.group(1) if first else body).strip()


def find_control(scopes: Sequence[QWidget], title: str,
                 skip: Optional[QWidget] = None) -> Optional[QWidget]:
    """The first visible widget under `scopes` (searched in turn) whose
    hover explanation is titled `title` -- or, failing that, the first
    label, button or field that says `title`. Nothing under `skip`."""
    prefix = "<b>" + html.escape(title) + "</b>"
    seen, found = set(), []
    for scope in scopes:
        for w in scope.findChildren(QWidget):
            if id(w) in seen or (skip is not None and (w is skip or skip.isAncestorOf(w))):
                continue
            seen.add(id(w))
            found.append(w)
    for w in found:
        if w.isVisible() and (w.toolTip() or "").startswith(prefix):
            return w
    for w in found:
        if (w.isVisible() and isinstance(w, (QLabel, QAbstractButton, QLineEdit))
                and w.text().strip() == title):
            return w
    return None


def visible_rect(w: QWidget, root: QWidget) -> Optional[QRect]:
    """Where `w` shows inside `root` (root's coordinates), clipped by every
    widget between them -- a scroll area cuts a control off at its edge."""
    if not isValid(w) or not w.isVisible() or not root.isAncestorOf(w):
        return None
    r = QRect(w.mapTo(root, QPoint(0, 0)), w.size())
    p = w.parentWidget()
    while p is not None and p is not root:
        r = r.intersected(QRect(p.mapTo(root, QPoint(0, 0)), p.size()))
        p = p.parentWidget()
    r = r.intersected(root.rect())
    return None if r.isEmpty() else r


def explained(widget: Optional[QWidget], root: QWidget) -> Optional[QWidget]:
    """The widget whose explanation shows when resting on `widget`: itself
    or its nearest ancestor with one, the way Qt looks a tooltip up."""
    w = widget
    while w is not None and w is not root:
        if w.toolTip():
            return w
        w = w.parentWidget()
    return None


def explained_rect(w: QWidget, root: QWidget) -> Optional[QRect]:
    """`w` together with its siblings that carry the same explanation -- a
    row explained once (label, switch, value) lights up as one."""
    rect = visible_rect(w, root)
    parent = w.parentWidget()
    if parent is None or rect is None:
        return rect
    for sib in parent.findChildren(QWidget, options=Qt.FindDirectChildrenOnly):
        if sib is not w and sib.toolTip() == w.toolTip():
            r = visible_rect(sib, root)
            if r is not None:
                rect = rect.united(r)
    return rect


def _scroll_into_view(w: QWidget) -> None:
    area = w.parentWidget()
    while area is not None and not isinstance(area, QScrollArea):
        area = area.parentWidget()
    if area is not None:
        area.ensureWidgetVisible(w, 40, 60)


# ---------------------------------------------------------------------------
# Painting helpers (the theme's colours, read when painting)
# ---------------------------------------------------------------------------

def _c(role: str, alpha: int = 255) -> QColor:
    col = QColor(_theme.CHROME[role])
    col.setAlpha(alpha)
    return col


def _ring(p: QPainter, r: QRectF, glow: bool) -> None:
    if glow:
        for width, alpha in ((12, 30), (7, 60), (4, 110)):
            p.setPen(QPen(_c("accent", alpha), width))
            p.setBrush(Qt.NoBrush)
            p.drawRoundedRect(r, 9, 9)
    p.setPen(QPen(_c("accent"), 2))
    p.setBrush(Qt.NoBrush)
    p.drawRoundedRect(r, 9, 9)


def _badge(p: QPainter, centre: QPointF, n: int, radius: float = 10) -> None:
    p.setPen(QPen(_c("bg"), 2))
    p.setBrush(_c("accent"))
    p.drawEllipse(centre, radius, radius)
    f = QFont(p.font())
    f.setPixelSize(round(radius * 1.2))
    f.setBold(True)
    p.setFont(f)
    p.setPen(_c("ink"))
    p.drawText(QRectF(centre.x() - radius, centre.y() - radius, 2 * radius, 2 * radius),
               Qt.AlignCenter, str(n))


def _arrow(p: QPainter, start: QPointF, end: QPointF) -> None:
    """From a step on the strip down to its control."""
    dy = end.y() - start.y()
    c1 = QPointF(start.x(), start.y() + dy * 0.5)
    c2 = QPointF(end.x(), end.y() - dy * 0.5)
    shaft = QPainterPath(start)
    shaft.cubicTo(c1, c2, end)
    head = QPainterPath(end)
    angle = math.atan2(end.y() - c2.y(), end.x() - c2.x())
    for side in (-0.45, 0.45):
        head.lineTo(end.x() - 13 * math.cos(angle + side), end.y() - 13 * math.sin(angle + side))
    head.closeSubpath()
    for col, width in ((_c("bg", 220), 6), (_c("accent"), 2.5)):
        p.setPen(QPen(col, width, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        p.setBrush(Qt.NoBrush)
        p.drawPath(shaft)
        p.setBrush(col)
        p.drawPath(head)


# ---------------------------------------------------------------------------
# The pieces on screen
# ---------------------------------------------------------------------------

class _Overlay(QWidget):
    """Over the whole window body; paints the dimming, rings, numbers,
    arrow and bubble. Never takes the mouse."""

    def __init__(self, mode: "HelpMode"):
        super().__init__(mode.root)
        self._mode = mode
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WA_NoSystemBackground, True)
        self.setFocusPolicy(Qt.NoFocus)

    def paintEvent(self, _ev) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        p.setRenderHint(QPainter.TextAntialiasing, True)
        self._mode._paint(p, self)
        p.end()


class _StripTitle(QWidget):
    """"? Show me around · <page>" at the strip's left."""

    def __init__(self):
        super().__init__()
        self.page = ""
        self._f = QFont(self.font())
        self._f.setBold(True)
        self._f.setPixelSize(14)

    def set_page(self, page: str) -> None:
        self.page = page
        self.updateGeometry()
        self.update()

    def _texts(self):
        return "Show me around", f"  ·  {self.page}" if self.page else ""

    def sizeHint(self) -> QSize:  # noqa: N802
        a, b = self._texts()
        fm = QFontMetricsF(self._f)
        return QSize(int(30 + fm.horizontalAdvance(a + b)) + 6, 30)

    def paintEvent(self, _ev) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        cy = self.height() / 2
        p.setPen(QPen(_c("accent"), 1.6))
        p.setBrush(_c("tint"))
        p.drawEllipse(QPointF(11, cy), 10, 10)
        p.setFont(self._f)
        p.drawText(QRectF(1, cy - 10, 20, 20), Qt.AlignCenter, "?")
        a, b = self._texts()
        fm = QFontMetricsF(self._f)
        p.drawText(QRectF(30, 0, self.width(), self.height()), Qt.AlignLeft | Qt.AlignVCenter, a)
        p.setPen(_c("muted"))
        p.drawText(QRectF(30 + fm.horizontalAdvance(a), 0, self.width(), self.height()),
                   Qt.AlignLeft | Qt.AlignVCenter, b)
        p.end()


class _StepChip(QAbstractButton):
    """One step on the strip: its number and what you do."""

    def __init__(self, mode: "HelpMode", index: int, label: str, hint: str):
        super().__init__()
        self._mode, self.index, self.label, self.hint = mode, index, label, hint
        self.missing = False
        self.setCursor(Qt.PointingHandCursor)
        self._f = QFont(self.font())
        self._f.setPixelSize(13)
        self.clicked.connect(lambda: mode.pin_step(index))

    def sizeHint(self) -> QSize:  # noqa: N802
        return QSize(int(QFontMetricsF(self._f).horizontalAdvance(self.label)) + 52, 30)

    def enterEvent(self, ev) -> None:  # noqa: N802
        self._mode.hover_step(self.index, True)
        super().enterEvent(ev)

    def leaveEvent(self, ev) -> None:  # noqa: N802
        self._mode.hover_step(self.index, False)
        super().leaveEvent(ev)

    def paintEvent(self, _ev) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        on = self._mode.shown_step() == self.index
        r = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        p.setPen(QPen(_c("accent" if on else "line"), 1.4))
        p.setBrush(_c("tint" if on else "card"))
        p.drawRoundedRect(r, r.height() / 2, r.height() / 2)
        _badge(p, QPointF(16, self.height() / 2), self.index + 1, 9)
        p.setFont(self._f)
        p.setPen(_c("dim" if self.missing else "txt"))
        p.drawText(QRectF(32, 0, self.width() - 40, self.height()),
                   Qt.AlignLeft | Qt.AlignVCenter, self.label)
        p.end()


class _Strip(QWidget):
    """The steps over the page: title, numbered chips, Done."""

    def __init__(self, mode: "HelpMode"):
        super().__init__()
        self.setObjectName("helpStrip")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(14, 8, 10, 8)
        lay.setSpacing(12)
        self.title = _StripTitle()
        lay.addWidget(self.title, 0, Qt.AlignVCenter)
        self.chips = QWidget()
        self.flow = FlowLayout(margin=0, h_spacing=6, v_spacing=6)
        self.chips.setLayout(self.flow)
        lay.addWidget(self.chips, 1)
        self.point = QLabel("Point at anything")
        self.point.setProperty("muted", "true")
        lay.addWidget(self.point, 0, Qt.AlignVCenter)
        self.done = QPushButton("Done")
        self.done.setProperty("role", "sideSmall")
        self.done.setCursor(Qt.PointingHandCursor)
        self.done.setToolTip("<b>Done</b><br>Leaves help mode (Esc or F1 does too).")
        self.done.clicked.connect(mode.stop)
        lay.addWidget(self.done, 0, Qt.AlignVCenter)

    def paintEvent(self, _ev) -> None:  # noqa: N802
        p = QPainter(self)
        p.fillRect(self.rect(), _c("panel"))
        p.setPen(QPen(_c("accent"), 1))
        p.drawLine(0, self.height() - 1, self.width(), self.height() - 1)
        p.end()


# ---------------------------------------------------------------------------
# Help mode itself
# ---------------------------------------------------------------------------

class HelpMode(QObject):
    """Help mode over `root` (the window body: sidebar and pages). The strip
    goes above `stack` (the pages), in its layout. `steps_for(page)` gives
    (page name, steps) for the page widget on screen; `passthrough(widget)`
    says which widgets keep taking clicks (the sidebar's pages)."""

    def __init__(self, root: QWidget, stack: QStackedWidget,
                 steps_for: Callable[[QWidget], Tuple[str, Sequence]],
                 passthrough: Optional[Callable[[QWidget], bool]] = None,
                 add_section: Optional[Callable[[QWidget], None]] = None):
        super().__init__(root)
        self.root, self.stack = root, stack
        self._steps_for = steps_for
        self._passthrough = passthrough or (lambda _w: False)
        self._add_section = add_section
        self.active = False
        self.overlay: Optional[_Overlay] = None
        self.strip: Optional[_Strip] = None
        self.page_name = ""
        self.steps: Sequence = ()
        self._chips: List[_StepChip] = []
        self._targets: List[Optional[List[QWidget]]] = []
        self._rects: List[Optional[QRect]] = []
        self._retry = 0
        self._hover: Optional[Tuple[QWidget, QRect, str, str]] = None
        self._step_hover: Optional[int] = None
        self._pinned: Optional[int] = None
        self._timer = QTimer(self)
        self._timer.setInterval(POLL_MS)
        self._timer.timeout.connect(self._tick)
        stack.currentChanged.connect(self._page_changed)
        root.installEventFilter(self)

    # ---- switching -------------------------------------------------------
    def start(self) -> None:
        if self.active:
            self._load_page()
            return
        self.active = True
        if self.overlay is None:
            self._build()
        self.strip.show()
        self.overlay.setGeometry(self.root.rect())
        self.overlay.raise_()
        self.overlay.show()
        self._load_page()
        QToolTip.hideText()
        QApplication.instance().installEventFilter(self)
        self._timer.start()
        self._tick()

    def stop(self) -> None:
        if not self.active:
            return
        self.active = False
        self._timer.stop()
        QApplication.instance().removeEventFilter(self)
        self.overlay.hide()
        self.strip.hide()
        self._hover = self._step_hover = self._pinned = None

    def toggle(self) -> None:
        self.stop() if self.active else self.start()

    def _build(self) -> None:
        self.overlay = _Overlay(self)
        self.strip = _Strip(self)
        holder = self.stack.parentWidget()
        lay = holder.layout() if holder is not None else None
        if lay is not None:
            lay.insertWidget(lay.indexOf(self.stack), self.strip)
        if self._add_section is not None:
            self._add_section(self.strip)       # its Done button follows the colour picker

    # ---- the page --------------------------------------------------------
    def _page_changed(self, _index: int) -> None:
        if self.active:
            self._load_page()

    def _load_page(self) -> None:
        name, steps = self._steps_for(self.stack.currentWidget())
        self.page_name, self.steps = name, tuple(steps or ())
        self._step_hover = self._pinned = None
        self.strip.title.set_page(name)
        while self.flow_count():
            item = self.strip.flow.takeAt(0)
            if item is not None and item.widget() is not None:
                item.widget().hide()            # gone now, not when Qt deletes it
                item.widget().deleteLater()
        self._chips = [_StepChip(self, i, s.label, s.hint) for i, s in enumerate(self.steps)]
        for chip in self._chips:
            self.strip.flow.addWidget(chip)
        self.strip.chips.setVisible(bool(self._chips))
        self._targets = [None] * len(self.steps)
        self._rects = [None] * len(self.steps)
        self._find_targets(force=True)

    def flow_count(self) -> int:
        return self.strip.flow.count() if self.strip is not None else 0

    def _find_targets(self, force: bool = False) -> None:
        page = self.stack.currentWidget()
        scopes = [w for w in (page, self.root) if w is not None]
        for i, step in enumerate(self.steps):
            have = self._targets[i]
            if not force and have and all(isValid(w) and w.isVisible() for w in have):
                continue
            names = (step.target,) if isinstance(step.target, str) else tuple(step.target)
            found = [find_control(scopes, t, skip=self.strip) for t in names]
            self._targets[i] = None if None in found else found
            if i < len(self._chips):
                self._chips[i].missing = self._targets[i] is None
                self._chips[i].update()

    def step_rect(self, i: int) -> Optional[QRect]:
        """Where step `i`'s control is on screen now (root coordinates)."""
        ws = self._targets[i] if i < len(self._targets) else None
        if not ws:
            return None
        rects = [visible_rect(w, self.root) for w in ws]
        if None in rects:
            return None
        r = rects[0]
        for more in rects[1:]:
            r = r.united(more)
        return r

    # ---- steps on the strip ---------------------------------------------
    def shown_step(self) -> Optional[int]:
        return self._step_hover if self._step_hover is not None else self._pinned

    def hover_step(self, i: int, on: bool) -> None:
        if on:
            self._step_hover = i
        elif self._step_hover == i:
            self._step_hover = None
        self._repaint()

    def pin_step(self, i: int) -> None:
        self._pinned = None if self._pinned == i else i
        ws = self._targets[i] if i < len(self._targets) else None
        if self._pinned is not None and ws:
            _scroll_into_view(ws[0])
        self._repaint()

    # ---- the pointer -----------------------------------------------------
    def hover_at(self, pos: QPoint) -> None:
        """Light what the pointer at `pos` (root coordinates) rests on."""
        w = self.root.childAt(pos)
        if w is None or (self.strip is not None and (w is self.strip or self.strip.isAncestorOf(w))):
            self._set_hover(None)
            return
        self._set_hover(explained(w, self.root))

    def hovered(self) -> Optional[QWidget]:
        return self._hover[0] if self._hover else None

    def _set_hover(self, w: Optional[QWidget]) -> None:
        if w is None:
            self._hover = None
            return
        rect = explained_rect(w, self.root)
        if rect is None:
            self._hover = None
            return
        title, text = split_tip(w.toolTip())
        self._hover = (w, rect, title, text)

    def _tick(self) -> None:
        if not self.active:
            return
        pos = self.root.mapFromGlobal(QCursor.pos())
        if self.root.rect().contains(pos):
            self.hover_at(pos)
        elif self._hover is not None:
            self._set_hover(None)
        self._retry += 1
        if self._retry >= RETRY_TICKS:
            self._retry = 0
            self._find_targets()
        self._rects = [self.step_rect(i) for i in range(len(self.steps))]
        self._repaint()

    def _repaint(self) -> None:
        if self.overlay is not None and self.active:
            self.overlay.raise_()
            self.overlay.update()
        for chip in self._chips:
            chip.update()

    # ---- events ----------------------------------------------------------
    def _inside(self, w: QWidget) -> bool:
        return w is self.root or self.root.isAncestorOf(w)

    def _lets_through(self, w: QWidget) -> bool:
        if self.strip is not None and (w is self.strip or self.strip.isAncestorOf(w)):
            return True
        if isinstance(w, QScrollBar):
            return True
        return bool(self._passthrough(w))

    def eventFilter(self, obj, ev) -> bool:  # noqa: N802
        t = ev.type()
        if obj is self.root and t == QEvent.Resize and self.overlay is not None:
            self.overlay.setGeometry(self.root.rect())
            return False
        if not self.active or not isinstance(obj, QWidget):
            return False
        if t == QEvent.KeyPress and ev.key() == Qt.Key_Escape:
            self.stop()
            return True
        if not self._inside(obj):
            return False
        if t in (QEvent.ToolTip, QEvent.WhatsThis):
            return not self._lets_through(obj)
        if t in _SWALLOWED and not self._lets_through(obj):
            if t == QEvent.MouseButtonPress:            # a tap lights it too
                self._set_hover(explained(obj, self.root))
                self._repaint()
            return True
        return False

    # ---- painting --------------------------------------------------------
    def _paint(self, p: QPainter, overlay: QWidget) -> None:
        full = QRectF(overlay.rect())
        lit: List[QRectF] = []
        if self.strip is not None and self.strip.isVisible():
            lit.append(QRectF(QRect(self.strip.mapTo(self.root, QPoint(0, 0)), self.strip.size())))
        rects = list(self._rects)
        lit += [QRectF(r).adjusted(-5, -5, 5, 5) for r in rects if r is not None]
        if self._hover is not None:
            lit.append(QRectF(self._hover[1]).adjusted(-5, -5, 5, 5))
        shade = QPainterPath()
        shade.addRect(full)
        for r in lit:
            hole = QPainterPath()
            hole.addRoundedRect(r, 9, 9)
            shade = shade.subtracted(hole)
        p.fillPath(shade, QColor(0, 0, 0, DIM_ALPHA))

        shown = self.shown_step()
        for i, r in enumerate(rects):
            if r is None:
                continue
            ring = QRectF(r).adjusted(-5, -5, 5, 5)
            if i == shown:
                _ring(p, ring, True)
            else:
                p.setPen(QPen(_c("accent", 150), 1.4))
                p.setBrush(Qt.NoBrush)
                p.drawRoundedRect(ring, 9, 9)
            _badge(p, QPointF(max(ring.left(), 11), max(ring.top(), 11)), i + 1)

        if shown is not None and shown < len(self._chips):
            chip = self._chips[shown]
            c = QRectF(QRect(chip.mapTo(self.root, QPoint(0, 0)), chip.size()))
            step = self.steps[shown]
            target = rects[shown] if shown < len(rects) else None
            if target is not None:
                t = QRectF(target).adjusted(-5, -5, 5, 5)
                start = QPointF(c.center().x(), c.bottom() + 3)
                end = QPointF(t.center().x(), t.top() - 3) if t.top() > c.bottom() + 20 \
                    else QPointF(t.right() + 3 if t.center().x() < start.x() else t.left() - 3,
                                 t.center().y())
                _arrow(p, start, end)
                self._bubble(p, overlay, t.toRect(), step.label, step.hint)
            else:
                self._bubble(p, overlay, c.toRect(), step.label,
                             step.hint + " Not on screen right now.")
        elif self._hover is not None:
            _w, rect, title, text = self._hover
            _ring(p, QRectF(rect).adjusted(-5, -5, 5, 5), True)
            self._bubble(p, overlay, rect, title, text)

    def _bubble(self, p: QPainter, overlay: QWidget, anchor: QRect, title: str, text: str) -> None:
        pad = 12
        f_title = QFont(overlay.font())
        f_title.setPixelSize(14)
        f_title.setBold(True)
        f_text = QFont(overlay.font())
        f_text.setPixelSize(13)
        inner = QRectF(0, 0, BUBBLE_W - 2 * pad, 2000)
        tr = QFontMetricsF(f_title).boundingRect(inner, Qt.TextWordWrap, title)
        br = QFontMetricsF(f_text).boundingRect(inner, Qt.TextWordWrap, text) if text else QRectF()
        w = max(tr.width(), br.width()) + 2 * pad
        h = tr.height() + (br.height() + 4 if text else 0) + 2 * pad
        x = min(max(anchor.left(), 8), overlay.width() - w - 8)
        below = anchor.bottom() + 14
        y = below if below + h < overlay.height() - 8 else max(8, anchor.top() - 14 - h)
        box = QRectF(x, y, w, h)
        p.setPen(QPen(_c("accent"), 1.5))
        p.setBrush(_c("panel"))
        p.drawRoundedRect(box, 10, 10)
        p.setFont(f_title)
        p.setPen(_c("txt"))
        p.drawText(QRectF(x + pad, y + pad, w - 2 * pad, tr.height()), Qt.TextWordWrap, title)
        if text:
            p.setFont(f_text)
            p.setPen(_c("muted"))
            p.drawText(QRectF(x + pad, y + pad + tr.height() + 4, w - 2 * pad, br.height()),
                       Qt.TextWordWrap, text)
