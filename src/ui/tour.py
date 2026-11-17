"""The guided tour: the first launch walked through for real.

Help mode (ui/help_mode.py) explains a page; the tour walks someone through
the app one real step at a time, on help mode's drawing -- the rest of the
window dimmed, the one control that matters ringed, a bubble beside it
saying what to do and what the tour waits for. The steps are
ui/tour_steps.py: switch your toy on, it lights up on Home, open it, its
Input, Select Zones (your SPS sources), the four chips, Test, total
strength, the avatar menu, then a short branch for each feature picked.

What it promises:

* it moves on when the real thing happens -- a toy connects, its card
  opens, a zone is picked -- which the window answers (the host's
  `tour_waiter`); a step with nothing to happen waits for Next;
* the lit control takes its click, unlike help mode: the tour lets that one
  through (and anything in its ring -- Arm shocks' question takes the
  switch's place), with the strip, scroll bars and the sidebar's pages
  (the tour follows, and points back at its page). Every other click on
  the window does nothing, so nothing changes by accident;
* it never changes a setting by itself: it only looks, scrolls a lit
  control into view and paints. Only the user's own clicks do anything;
* a step on another page first rings that page's sidebar entry;
* skip any step (the strip's button), end it any time (End tour, Esc);
  with no toy, the first step says what to check and waits, or Continue
  without a toy leaves the toy's steps out;
* everything is drawn inside the window: no popups.

It only runs while it is on (a 60 ms look at the window, as help mode).
The host (ui/views/tour.py `TourMixin`) answers:

    tour_page(name)      -> the page widget in the stack, None while switched off
    tour_nav(name)       -> its sidebar entry
    tour_applies(step, no_toy) -> whether the step is for this user
    tour_scopes(step)    -> where to look for its control
    tour_fill(target)    -> the target with the tour's toy's name filled in
    tour_waiter(step)    -> a callable, True once the step's thing happened
    tour_passthrough(w)  -> whether `w` keeps its clicks (the sidebar's pages)
    tour_finished(how)   -> "done" (Finish) or "ended" (End tour, Esc)
"""

from __future__ import annotations

from typing import Callable, List, Optional, Sequence

from PySide6.QtCore import QEvent, QObject, QPoint, QPointF, QRect, QRectF, QSize, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QFontMetricsF, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (QApplication, QHBoxLayout, QPushButton, QScrollBar,
                               QStackedWidget, QToolTip, QWidget)
from shiboken6 import isValid

from ui import tour_steps
from ui.help_mode import (_Overlay, _badge, _c, _ring, _scroll_into_view, draw_bubble,
                          find_control, visible_rect)

POLL_MS = 60            # how often the window is looked at
REFIND_TICKS = 5        # a control not on screen is looked for again after this
DIM_ALPHA = 140         # how dark the rest of the window goes (help mode's is lighter)
_SWALLOWED = (QEvent.MouseButtonPress, QEvent.MouseButtonRelease,
              QEvent.MouseButtonDblClick, QEvent.ContextMenu)
NOT_ON_SCREEN = "Not on screen right now - scroll to it, or skip this step."


class _StripTitle(QWidget):
    """"Guided tour · 3 of 12 · <step>" at the strip's left."""

    def __init__(self):
        super().__init__()
        self.where = ""
        self._f = QFont(self.font())
        self._f.setBold(True)
        self._f.setPixelSize(14)

    def set_where(self, where: str) -> None:
        self.where = where
        self.updateGeometry()
        self.update()

    def _texts(self):
        return "Guided tour", f"  ·  {self.where}" if self.where else ""

    def sizeHint(self) -> QSize:  # noqa: N802
        a, b = self._texts()
        return QSize(int(30 + QFontMetricsF(self._f).horizontalAdvance(a + b)) + 6, 30)

    def minimumSizeHint(self) -> QSize:  # noqa: N802
        a, _b = self._texts()
        return QSize(int(30 + QFontMetricsF(self._f).horizontalAdvance(a)) + 6, 30)

    def paintEvent(self, _ev) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        cy = self.height() / 2
        p.setPen(QPen(_c("accent"), 1.6))
        p.setBrush(_c("tint"))
        p.drawEllipse(QPointF(11, cy), 10, 10)
        p.setBrush(_c("accent"))                      # a path of three dots
        for dx in (-4.5, 0, 4.5):
            p.drawEllipse(QPointF(11 + dx, cy), 1.6, 1.6)
        p.setFont(self._f)
        a, b = self._texts()
        fm = QFontMetricsF(self._f)
        p.drawText(QRectF(30, 0, self.width(), self.height()), Qt.AlignLeft | Qt.AlignVCenter, a)
        p.setPen(_c("muted"))
        p.drawText(QRectF(30 + fm.horizontalAdvance(a), 0, self.width(), self.height()),
                   Qt.AlignLeft | Qt.AlignVCenter, fm.elidedText(
                       b, Qt.ElideRight, max(0, self.width() - 30 - fm.horizontalAdvance(a))))
        p.end()


class _Strip(QWidget):
    """Over the page while the tour is on: where you are, the step's button
    (Skip this step / Next / Continue without a toy / Finish), End tour."""

    def __init__(self, tour: "Tour"):
        super().__init__()
        self.setObjectName("tourStrip")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(14, 8, 10, 8)
        lay.setSpacing(10)
        self.title = _StripTitle()
        lay.addWidget(self.title, 1, Qt.AlignVCenter)
        self.main = QPushButton("Skip this step")
        self.main.setProperty("role", "sideSmall")
        self.main.setCursor(Qt.PointingHandCursor)
        self.main.clicked.connect(tour.next)
        lay.addWidget(self.main, 0, Qt.AlignVCenter)
        self.end = QPushButton("End tour")
        self.end.setProperty("role", "sideSmall")
        self.end.setCursor(Qt.PointingHandCursor)
        self.end.setToolTip("<b>End tour</b><br>Leaves the tour (Esc does too). "
                            "Help → Take the tour starts it again.")
        self.end.clicked.connect(tour.end)
        lay.addWidget(self.end, 0, Qt.AlignVCenter)

    def paintEvent(self, _ev) -> None:  # noqa: N802
        p = QPainter(self)
        p.fillRect(self.rect(), _c("panel"))
        p.setPen(QPen(_c("accent"), 1))
        p.drawLine(0, self.height() - 1, self.width(), self.height() - 1)
        p.end()


class Tour(QObject):
    """The tour over `root` (the window body: sidebar and pages); its strip
    goes above `stack` (the pages), in its layout, as help mode's does."""

    def __init__(self, root: QWidget, stack: QStackedWidget, host,
                 steps: Sequence[tour_steps.TourStep] = tour_steps.TOUR,
                 add_section: Optional[Callable[[QWidget], None]] = None):
        super().__init__(root)
        self.root, self.stack, self.host = root, stack, host
        self.steps = tuple(steps)
        self._add_section = add_section
        self.active = False
        self.index = -1
        self.no_toy = False
        self.phase = ""                 # "nav" (open its page first) / "here"
        self.overlay: Optional[_Overlay] = None
        self.strip: Optional[_Strip] = None
        self._waiter: Callable[[], bool] = lambda: False
        self._targets: Optional[List[QWidget]] = None
        self._rect: Optional[QRect] = None
        self._scrolled = False
        self._clicked = False
        self._refind = 0
        self._progress = (0, 0)
        self._timer = QTimer(self)
        self._timer.setInterval(POLL_MS)
        self._timer.timeout.connect(self._tick)
        root.installEventFilter(self)
        # Quitting mid-tour: off first, so the app-wide filter never sees
        # the window being taken apart.
        QApplication.instance().aboutToQuit.connect(self.stop)
        root.destroyed.connect(self._root_gone)

    # ---- switching -------------------------------------------------------
    @property
    def step(self) -> Optional[tour_steps.TourStep]:
        return self.steps[self.index] if 0 <= self.index < len(self.steps) else None

    def start(self) -> None:
        """From the first step (again, when it is already on)."""
        if self.overlay is None:
            self._build()
        self.no_toy = False
        if not self.active:
            self.active = True
            self.strip.show()
            self.overlay.setGeometry(self.root.rect())
            self.overlay.raise_()
            self.overlay.show()
            QToolTip.hideText()
            QApplication.instance().installEventFilter(self)
            self._timer.start()
        self._go(0)

    def next(self) -> None:
        """The strip's button: Next, Skip this step, Continue without a toy
        (the toy's steps are left out then) or Finish."""
        step = self.step
        if not self.active or step is None:
            return
        if step.waits == "toy":
            self.no_toy = True
        self._go(self.index + 1)

    def end(self) -> None:
        """End tour or Esc: off, wherever it was."""
        self._finish("ended")

    def stop(self) -> None:
        """Off without a word (help mode is starting)."""
        self._finish("")

    def _root_gone(self, *_a) -> None:
        if self.active:
            self.active = False
            self._timer.stop()
            QApplication.instance().removeEventFilter(self)

    def _finish(self, how: str) -> None:
        if not self.active:
            return
        self.active = False
        self._timer.stop()
        QApplication.instance().removeEventFilter(self)
        self.overlay.hide()
        self.strip.hide()
        self.index = -1
        self._targets = self._rect = None
        done = getattr(self.host, "tour_finished", None)
        if how and callable(done):
            done(how)

    def _build(self) -> None:
        self.overlay = _Overlay(self)       # paints through self._paint
        self.strip = _Strip(self)
        self.strip.hide()
        holder = self.stack.parentWidget()
        lay = holder.layout() if holder is not None else None
        if lay is not None:
            lay.insertWidget(lay.indexOf(self.stack), self.strip)
        if self._add_section is not None:
            self._add_section(self.strip)   # its buttons follow the colour picker

    # ---- the steps -------------------------------------------------------
    def applies(self, step: tour_steps.TourStep) -> bool:
        return bool(self.host.tour_applies(step, self.no_toy))

    def _go(self, i: int, look: bool = True) -> None:
        """To the first step from `i` on that is for this user; past the
        last one the tour is done. `look`: look at the window at once."""
        while i < len(self.steps) and not self.applies(self.steps[i]):
            i += 1
        if i >= len(self.steps):
            self._finish("done")
            return
        self.index = i
        step = self.steps[i]
        self._clicked = False
        self._scrolled = False
        self._targets = self._rect = None
        self._refind = 0
        if step.waits == "click":
            self._waiter = lambda: self._clicked
        elif step.waits == "next":
            self._waiter = lambda: False
        else:
            self._waiter = self.host.tour_waiter(step) or (lambda: False)
        self._show_where()
        if look:
            self._tick()

    def progress(self) -> tuple:
        """(this step's place, how many there are) among the steps for this
        user."""
        mine = [i for i, s in enumerate(self.steps) if self.applies(s)]
        return (mine.index(self.index) + 1 if self.index in mine else 0), len(mine)

    def _show_where(self) -> None:
        step = self.step
        if step is None or self.strip is None:
            return
        self._progress = n, total = self.progress()
        self.strip.title.set_where(f"{n} of {total}  ·  {step.label}")
        self.strip.main.setText(step.button or "Skip this step")

    # ---- looking at the window ------------------------------------------
    def _tick(self) -> None:
        if not self.active:
            return
        # The real thing happened: on to the next step (several at once
        # when they already have -- a toy that is already connected).
        for _ in range(len(self.steps) + 1):
            step = self.step
            if step is None or not self.active:
                return
            page = self.host.tour_page(step.page) if step.page else None
            if (step.page and page is None) or not self.applies(step):
                self._go(self.index + 1, look=False)    # switched off meanwhile
                continue
            try:
                happened = bool(self._waiter())
            except RuntimeError:            # a widget went while looking
                happened = False
            if not happened:
                break
            self._go(self.index + 1, look=False)
        step = self.step
        if step is None:
            return
        page = self.host.tour_page(step.page) if step.page else None
        here = page is None or self.stack.currentWidget() is page
        phase = "here" if here else "nav"
        if phase != self.phase:
            self.phase = phase
            self._targets = None
            self._refind = 0
        if not self._still_there():
            if self._refind <= 0:
                self._targets = self._find(step) if here else self._nav(step.page)
                self._refind = REFIND_TICKS
            else:
                self._refind -= 1
        if here and self._targets and not self._scrolled:
            self._scrolled = True
            _scroll_into_view(self._targets[0])
        self._rect = self._lit_rect()
        self._repaint()

    def _still_there(self) -> bool:
        ws = self._targets
        return bool(ws) and all(isValid(w) and w.isVisible() for w in ws)

    def _nav(self, page: str) -> Optional[List[QWidget]]:
        btn = self.host.tour_nav(page)
        return [btn] if btn is not None and isValid(btn) and btn.isVisible() else None

    def _find(self, step: tour_steps.TourStep) -> Optional[List[QWidget]]:
        """The first of the step's targets whose controls are all on screen."""
        scopes = [w for w in (self.host.tour_scopes(step) or ()) if w is not None]
        if not scopes:
            return None
        for target in step.targets:
            names = (target,) if isinstance(target, str) else tuple(target)
            found = [find_control(scopes, self.host.tour_fill(t), skip=self.strip)
                     for t in names]
            if None not in found:
                return self._with_rows(found)
        return None

    @staticmethod
    def _with_rows(found: List[QWidget]) -> List[QWidget]:
        """A control explained once with the widgets beside it (a heading and
        its slider, a label and its switch) lights and takes clicks as one,
        as in help mode."""
        out = list(found)
        for w in found:
            tip, parent = w.toolTip(), w.parentWidget()
            if not tip or parent is None:
                continue
            for sib in parent.findChildren(QWidget, options=Qt.FindDirectChildrenOnly):
                if sib not in out and sib.toolTip() == tip and sib.isVisible():
                    out.append(sib)
        return out

    def _lit_rect(self) -> Optional[QRect]:
        ws = self._targets
        if not ws:
            return None
        rects = [visible_rect(w, self.root) for w in ws if isValid(w)]
        if not rects or None in rects:
            return None
        r = rects[0]
        for more in rects[1:]:
            r = r.united(more)
        return r

    def lit(self) -> Optional[List[QWidget]]:
        """The control(s) lit right now (its sidebar entry while its page
        isn't open)."""
        return list(self._targets) if self._targets else None

    def _repaint(self) -> None:
        if self.overlay is not None and self.active:
            self.overlay.raise_()
            self.overlay.update()

    # ---- events ----------------------------------------------------------
    def _inside(self, w: QWidget) -> bool:
        return w is self.root or self.root.isAncestorOf(w)

    def _on_target(self, w: QWidget) -> bool:
        return any(isValid(t) and (t is w or t.isAncestorOf(w)) for t in (self._targets or ()))

    def _in_ring(self, global_pos: Optional[QPoint]) -> bool:
        if global_pos is None or self._rect is None:
            return False
        return self._rect.adjusted(-6, -6, 6, 6).contains(self.root.mapFromGlobal(global_pos))

    def _lets_through(self, w: QWidget, global_pos: Optional[QPoint] = None) -> bool:
        if self.strip is not None and (w is self.strip or self.strip.isAncestorOf(w)):
            return True
        if isinstance(w, QScrollBar):
            return True
        if self._on_target(w) or self._in_ring(global_pos):
            return True
        return bool(self.host.tour_passthrough(w))

    @staticmethod
    def _global_pos(ev) -> Optional[QPoint]:
        if hasattr(ev, "globalPosition"):
            return ev.globalPosition().toPoint()
        if hasattr(ev, "globalPos"):
            return ev.globalPos()
        return None

    def eventFilter(self, obj, ev) -> bool:  # noqa: N802
        try:
            return self._filter(obj, ev)
        except RuntimeError:                # a widget going away under it
            return False

    def _filter(self, obj, ev) -> bool:
        t = ev.type()
        if obj is self.root and t == QEvent.Resize and self.overlay is not None:
            self.overlay.setGeometry(self.root.rect())
            return False
        if not self.active or not isinstance(obj, QWidget):
            return False
        if (t == QEvent.KeyPress and ev.key() == Qt.Key_Escape
                and obj.window() is self.root.window()):
            self.end()
            return True
        if not self._inside(obj):
            return False
        if t in (QEvent.ToolTip, QEvent.WhatsThis):
            # the bubble explains; a tooltip would cover it
            return not (self.strip is not None
                        and (obj is self.strip or self.strip.isAncestorOf(obj)))
        if t in _SWALLOWED:
            pos = self._global_pos(ev)
            if not self._lets_through(obj, pos):
                return True
            if (t == QEvent.MouseButtonRelease and self.phase == "here"
                    and (self._on_target(obj) or self._in_ring(pos))):
                self._clicked = True        # a "click" step moves on at the next look
        return False

    # ---- painting --------------------------------------------------------
    def _paint(self, p: QPainter, overlay: QWidget) -> None:
        step = self.step
        if step is None:
            return
        full = QRectF(overlay.rect())
        holes: List[QRectF] = []
        strip_rect = None
        if self.strip is not None and self.strip.isVisible():
            strip_rect = QRectF(QRect(self.strip.mapTo(self.root, QPoint(0, 0)),
                                      self.strip.size()))
            holes.append(strip_rect)
        ring = QRectF(self._rect).adjusted(-6, -6, 6, 6) if self._rect is not None else None
        if ring is not None:
            holes.append(ring)
        shade = QPainterPath()
        shade.addRect(full)
        for r in holes:
            hole = QPainterPath()
            hole.addRoundedRect(r, 9, 9)
            shade = shade.subtracted(hole)
        p.fillPath(shade, QColor(0, 0, 0, DIM_ALPHA))

        n, _total = self._progress
        if ring is not None:
            _ring(p, ring, True)
            _badge(p, QPointF(max(ring.left(), 11), max(ring.top(), 11)), n)
        lines = self.bubble_lines()
        anchor = self._rect if self._rect is not None else (
            strip_rect.toRect() if strip_rect is not None else QRect(8, 8, 0, 0))
        draw_bubble(p, overlay, anchor, [
            (lines[0], 14, True, "txt"), (lines[1], 13, False, "muted"),
            (lines[2], 12, False, "muted"), (lines[3], 13, True, "accent")])

    def bubble_lines(self) -> tuple:
        """(title, hint, more, waiting) -- what the bubble says right now."""
        step = self.step
        if step is None:
            return "", "", "", ""
        if self.phase == "nav":
            return (f"Open {step.page}", f"Next: {step.label}.", "",
                    f"Waiting for {step.page} to open")
        more = step.more if self._rect is not None else (
            (step.more + " " if step.more else "") + NOT_ON_SCREEN)
        return step.label, step.hint, more, step.waiting
