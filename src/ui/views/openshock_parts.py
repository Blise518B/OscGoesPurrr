"""The parts OpenShock's shocker card is built from (openshock_card.py),
drawn after OpenShock's own web app (OpenShock/Frontend, read for how they
look and behave, none of its code used):

  * Dial -- its round slider: a 270° arc open at the bottom, the value in
    the middle, the name under it. Pressing anywhere on it jumps the knob
    there; dragging past the bottom sticks at the end you came from.
  * LivePad -- Live control's pad: hold and drag, the strength follows the
    finger (top = the most), letting go drops it to 0. Behind the handle,
    the last 3 s of strength as a line moving left.

Both reach both ends (Blise's rule: the knob or handle sits right at the
end at the minimum and the maximum) and leave the scroll wheel alone (it
scrolls the page -- ui/wheel_guard.py's rule)."""

import math
import time
from collections import deque
from typing import Callable, Optional

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QBrush, QColor, QFont, QLinearGradient, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QSizePolicy, QWidget

import shocker_layout as layout
from ui import frame_clock, theme
from ui.views.card_parts import hue_color

_ARC_START = 225.0          # Qt degrees: 7:30 on a clock ...
_ARC_SPAN = 270.0           # ... clockwise round to 4:30


def _colour(hue: str, enabled: bool) -> QColor:
    v = theme.qss_vars()
    if not enabled:
        return QColor(v["dim"])
    return QColor(hue_color(hue) if hue else v["txt"])


class Dial(QWidget):
    """OpenShock's round slider. Integer values `lo`..`hi` in `step`s;
    `fmt` writes the value in the middle. valueChanged fires on the user's
    hand only (setValue is quiet), like the PiShock card's set_quiet."""

    valueChanged = Signal(int)

    def __init__(self, name: str, hue: str, lo: int, hi: int, step: int, value: int,
                 fmt: Callable[[int], str] = str, big: bool = False):
        super().__init__()
        self._name, self._hue, self._fmt, self._big = name, hue, fmt, big
        self._lo, self._hi, self._step = int(lo), max(int(lo), int(hi)), max(1, int(step))
        self._value = self._snap(value)
        self._last: Optional[float] = None          # the fraction the drag was at
        # square, but it gives up a little height when the panel squeezes
        # its cards (the ring just gets a touch smaller)
        side = 150 if big else 104
        self._side = side
        self.setFixedWidth(side)
        self.setMinimumHeight(side - (20 if big else 16))
        self.setMaximumHeight(side)
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Preferred)
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setAccessibleName(name)

    def sizeHint(self) -> QSize:  # noqa: N802
        return QSize(self._side, self._side)

    # -- value
    def value(self) -> int:
        return self._value

    def minimum(self) -> int:
        return self._lo

    def maximum(self) -> int:
        return self._hi

    def _snap(self, v: float) -> int:
        steps = layout.js_round((float(v) - self._lo) / self._step)
        return max(self._lo, min(self._hi, self._lo + steps * self._step))

    def setValue(self, v: float) -> None:  # noqa: N802
        """Quietly: no valueChanged."""
        v = self._snap(v)
        if v != self._value:
            self._value = v
            self.update()

    def setRange(self, lo: int, hi: int) -> None:  # noqa: N802
        self._lo, self._hi = int(lo), max(int(lo), int(hi))
        self._value = self._snap(self._value)
        self.update()

    def _set_by_hand(self, v: float) -> None:
        v = self._snap(v)
        if v != self._value:
            self._value = v
            self.update()
            self.valueChanged.emit(v)

    def fraction(self) -> float:
        return 0.0 if self._hi <= self._lo else (self._value - self._lo) / (self._hi - self._lo)

    # -- geometry
    def _ring(self):
        side = min(self.width(), self.height())
        r = side * 0.40
        cx, cy = self.width() / 2.0, self.height() / 2.0
        return cx, cy, r, side

    def _fraction_at(self, pos: QPointF) -> float:
        cx, cy, _r, _side = self._ring()
        # 0° straight up, clockwise positive; the arc runs -135° .. +135°
        angle = math.degrees(math.atan2(pos.x() - cx, cy - pos.y()))
        return max(0.0, min(1.0, angle / _ARC_SPAN + 0.5))

    def _from_fraction(self, f: float) -> float:
        return self._lo + f * (self._hi - self._lo)

    # -- drawing
    def paintEvent(self, _event) -> None:  # noqa: N802
        v = theme.qss_vars()
        on = self.isEnabled()
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        cx, cy, r, side = self._ring()
        rect = QRectF(cx - r, cy - r, 2 * r, 2 * r)
        # the track: the hue's quiet tone (its _mid), grey while it rests
        track = QColor(theme.PALETTE[self._hue][1] if on and self._hue in theme.PALETTE
                       else v["grey_mid"])
        p.setPen(QPen(track, side * 0.16, Qt.SolidLine, Qt.RoundCap))
        p.drawArc(rect, int(_ARC_START * 16), int(-_ARC_SPAN * 16))
        f = self.fraction()
        col = _colour(self._hue, on)
        if f > 0:
            p.setPen(QPen(col, side * 0.08, Qt.SolidLine, Qt.RoundCap))
            p.drawArc(rect, int(_ARC_START * 16), int(-_ARC_SPAN * f * 16))
        # the knob, right on the value: at the arc's very ends at lo and hi
        a = math.radians(_ARC_START - _ARC_SPAN * f)
        kx, ky = cx + r * math.cos(a), cy - r * math.sin(a)
        p.setPen(QPen(QColor(v["muted"] if on else v["dim"]), 1.5))
        p.setBrush(QBrush(QColor(v["panel"])))
        kr = side * 0.095
        p.drawEllipse(QPointF(kx, ky), kr, kr)
        if self.hasFocus():
            p.setPen(QPen(QColor(v["accent"]), 2))
            p.setBrush(Qt.NoBrush)
            p.drawEllipse(QPointF(kx, ky), kr + 2, kr + 2)
        # the value in the middle, the name under the arc's gap
        font = QFont(self.font())
        font.setBold(True)
        font.setPixelSize(round(side * 0.2))
        p.setFont(font)
        p.setPen(QColor(v["txt"] if on else v["dim"]))
        p.drawText(QRectF(0, cy - side * 0.16, self.width(), side * 0.32), Qt.AlignCenter,
                   self._fmt(self._value))
        font.setBold(False)
        font.setPixelSize(round(side * 0.115))
        p.setFont(font)
        p.setPen(QColor(v["muted"] if on else v["dim"]))
        p.drawText(QRectF(0, self.height() - side * 0.2, self.width(), side * 0.2),
                   Qt.AlignHCenter | Qt.AlignVCenter, self._name)
        p.end()

    # -- the hand
    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() != Qt.LeftButton:
            return
        f = self._fraction_at(event.position())     # a press jumps right there
        self._last = f
        self._set_by_hand(self._from_fraction(f))

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        if self._last is None:
            return
        f = self._fraction_at(event.position())
        # across the gap at the bottom: stay at the end you came from
        if abs(f - self._last) > 0.5:
            if self._last > 0.75 and f < 0.25:
                f = 1.0
            elif self._last < 0.25 and f > 0.75:
                f = 0.0
        self._last = f
        self._set_by_hand(self._from_fraction(f))

    def mouseReleaseEvent(self, _event) -> None:  # noqa: N802
        self._last = None

    def keyPressEvent(self, event) -> None:  # noqa: N802
        step = {Qt.Key_Up: 1, Qt.Key_Right: 1, Qt.Key_Down: -1, Qt.Key_Left: -1}.get(event.key())
        if step is None:
            super().keyPressEvent(event)
            return
        self._set_by_hand(self._value + step * self._step)

    def wheelEvent(self, event) -> None:  # noqa: N802
        event.ignore()                     # the wheel scrolls the page


class LivePad(QWidget):
    """Live control's pad (see the module's notes). `on_level(strength)`
    whenever the strength under the finger changes -- 0 at the bottom --
    and `on_release()` when the finger lets go. `cap` is the top."""

    WINDOW_S = 3.0                       # the line behind: this much history
    _TICK_MS = 33                        # ... sampled this often while it moves
    _SMOOTH_S = 0.05                     # ... and eased like OpenShock's

    def __init__(self, hue: str, on_level: Callable[[int], None],
                 on_release: Callable[[], None], big: bool = False):
        super().__init__()
        self._hue, self._big = hue, big
        self._on_level, self._on_release = on_level, on_release
        self._cap = 100
        self._y = 1.0                    # 0 top .. 1 bottom: where the handle is
        self._dragging = False
        self._strength = 0
        self._samples: deque = deque()   # (t, eased strength)
        self._eased = 0.0
        self._last_t = 0.0
        self._timer = QTimer(self)
        self._timer.setInterval(self._TICK_MS)
        self._timer.timeout.connect(self._tick)
        # OpenShock's is 200 px tall; it gives up a little when squeezed
        self._tall = 280 if big else 200
        self.setMinimumHeight(self._tall - 30)
        self.setMaximumHeight(self._tall)
        self.setMinimumWidth(160)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setAccessibleName("Live intensity")

    def sizeHint(self) -> QSize:  # noqa: N802
        return QSize(240, self._tall)

    # -- what it shows
    def set_hue(self, hue: str) -> None:
        if hue != self._hue:
            self._hue = hue
            self.update()

    def set_cap(self, cap: int) -> None:
        cap = max(1, int(cap))
        if cap != self._cap:
            self._cap = cap
            if self._dragging:
                self._moved(self._y)
            self.update()

    def strength(self) -> int:
        return self._strength

    def dragging(self) -> bool:
        return self._dragging

    def _radius(self) -> float:
        return (24.0 if self._dragging else 20.0) * (1.4 if self._big else 1.0)

    def _travel(self):
        """(top, bottom) of the handle's centre: it sits flush with both ends."""
        r = 24.0 * (1.4 if self._big else 1.0)
        return r + 1, self.height() - r - 1

    # -- the hand
    def _y_at(self, y_px: float) -> float:
        top, bottom = self._travel()
        return 0.0 if bottom <= top else max(0.0, min(1.0, (y_px - top) / (bottom - top)))

    def _moved(self, y: float) -> None:
        self._y = y
        s = layout.live_strength(y, self._cap)
        self.update()
        if s != self._strength:
            self._strength = s
            self._on_level(s)                  # sent on change, like a toy level

    def _start_trace(self) -> None:
        if not self._timer.isActive():
            self._last_t = time.monotonic()
            self._timer.start()

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() != Qt.LeftButton or not self.isEnabled():
            return
        self._dragging = True
        self._start_trace()
        self._moved(self._y_at(event.position().y()))

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        if self._dragging:
            self._moved(self._y_at(event.position().y()))

    def mouseReleaseEvent(self, _event) -> None:  # noqa: N802
        self.let_go()

    def keyPressEvent(self, event) -> None:  # noqa: N802
        step = {Qt.Key_Up: -1, Qt.Key_Right: -1, Qt.Key_Down: 1, Qt.Key_Left: 1}.get(event.key())
        if step is None or not self.isEnabled():
            super().keyPressEvent(event)
            return
        self._start_trace()
        self._moved(max(0.0, min(1.0, self._y + step * layout.LIVE_STEP)))

    def focusOutEvent(self, event) -> None:  # noqa: N802
        if not self._dragging and self._strength:
            self.let_go()                      # an arrow-key level lets go with the focus
        super().focusOutEvent(event)

    def wheelEvent(self, event) -> None:  # noqa: N802
        event.ignore()                         # the wheel scrolls the page

    def let_go(self, quiet: bool = False) -> None:
        """Back to the bottom, nothing held -- `quiet` without calling back
        (the card let go itself)."""
        was = self._dragging or self._strength > 0
        self._dragging = False
        self._y = 1.0
        self._strength = 0
        self.update()
        if was and not quiet:
            self._on_release()

    def changeEvent(self, event) -> None:  # noqa: N802
        super().changeEvent(event)
        if not self.isEnabled() and (self._dragging or self._strength):
            self.let_go()

    # -- the line behind it
    def _tick(self) -> None:
        now = time.monotonic()
        dt = now - self._last_t
        self._last_t = now
        self._eased += (self._strength - self._eased) * (1 - math.exp(-dt / self._SMOOTH_S))
        self._samples.append((now, self._eased))
        while self._samples and now - self._samples[0][0] > self.WINDOW_S + 0.1:
            self._samples.popleft()
        frame_clock.request(self)
        # nothing held and the line flat at 0 for the whole window: rest
        if not self._dragging and self._strength == 0 and all(v < 0.05 for _t, v in self._samples):
            self._timer.stop()
            self._samples.clear()
            self._eased = 0.0
            self.update()

    def paintEvent(self, _event) -> None:  # noqa: N802
        v = theme.qss_vars()
        on = self.isEnabled()
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = float(self.width()), float(self.height())
        box = QRectF(0.5, 0.5, w - 1, h - 1)
        p.setPen(QPen(QColor(v["line"]), 1))
        p.setBrush(QBrush(QColor(v["well"])))
        p.drawRoundedRect(box, 6, 6)
        col = _colour(self._hue, on)
        top, bottom = self._travel()
        if len(self._samples) >= 2:
            now = time.monotonic()
            path = QPainterPath()
            for i, (t, val) in enumerate(self._samples):
                x = w - (now - t) / self.WINDOW_S * w
                y = bottom - min(val, self._cap) / self._cap * (bottom - top)
                path.lineTo(x, y) if i else path.moveTo(x, y)
            grad = QLinearGradient(0, 0, w, 0)
            clear = QColor(col)
            clear.setAlpha(0)
            grad.setColorAt(0.0, clear)
            grad.setColorAt(0.4, col)
            grad.setColorAt(1.0, col)
            p.setClipRect(box)
            p.setBrush(Qt.NoBrush)
            p.setPen(QPen(QBrush(grad), 3.0 * (1.4 if self._big else 1.0), Qt.SolidLine,
                          Qt.RoundCap, Qt.RoundJoin))
            p.drawPath(path)
            p.setClipping(False)
        # the handle, its strength in it (OpenShock's "NN%")
        r = self._radius()
        cy = top + self._y * (bottom - top)
        p.setPen(QPen(QColor(v["txt"]), 1.5) if self._dragging else Qt.NoPen)
        p.setBrush(QBrush(col))
        p.drawEllipse(QPointF(w / 2, cy), r, r)
        font = QFont(self.font())
        font.setBold(True)
        font.setPixelSize(round(r * 0.62))
        p.setFont(font)
        p.setPen(QColor(v["ink"]))
        p.drawText(QRectF(w / 2 - r, cy - r, 2 * r, 2 * r), Qt.AlignCenter, f"{self._strength}%")
        p.end()
