"""Standalone Qt widgets and tiny proxies used by `OscGoesPurrrUI`.

None of these touch the controller — they are pure view-layer building
blocks. Cross-thread invocation is handled by `Invoker` so the controller
can schedule callbacks onto the UI thread without importing Qt.
"""

from typing import Callable, List, Optional

from PySide6.QtCore import QEvent, QObject, QPointF, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import (
    QBrush,
    QColor,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
)
from PySide6.QtWidgets import (
    QCheckBox,
    QFrame,
    QMainWindow,
    QProgressBar,
    QScrollBar,
    QSlider,
    QStyle,
    QStyleOptionSlider,
    QWidget,
)

import constants as _C
from constants import (
    COLOR_BG,
    COLOR_BUTTON,
    COLOR_LIVE,
    COLOR_PRIMARY,
    COLOR_SUCCESS,
    COLOR_TEXT,
)


class ToggleSwitch(QCheckBox):
    """Drop-in QCheckBox replacement painted as a sliding toggle.

    Off: knob on the left, muted button-grey track. On: knob on the
    right, hot-pink track. The off colour intentionally matches the
    rest of the idle interactive surfaces (segmented buttons, secondary
    buttons) so the toggle reads as "inactive control" rather than
    "danger / error". On is the brand "live" pink so toggling something
    on aligns visually with the live-intensity meters / sliders.
    All QCheckBox APIs (isChecked, setChecked, toggled, stateChanged, …)
    work unchanged — only the visual is replaced.
    """

    _TRACK_W = 36
    _TRACK_H = 18
    _KNOB_MARGIN = 3
    _LABEL_SPACING = 8

    # Off: the well inside the frame line, a muted knob. On: the accent
    # track with an ink knob -- never white on green.
    _COLOR_OFF = QColor(_C.COLOR_WELL)
    _COLOR_OFF_LINE = QColor(_C.COLOR_LINE)
    _COLOR_ON = QColor(_C.COLOR_ACCENT)
    _COLOR_KNOB_OFF = QColor(_C.COLOR_MUTED)
    _COLOR_KNOB_ON = QColor(_C.COLOR_INK)
    _COLOR_DISABLED_KNOB = QColor(_C.COLOR_DIM)

    def __init__(self, text: str = "", parent=None):
        super().__init__(text, parent)
        self.setCursor(Qt.PointingHandCursor)

    def sizeHint(self) -> QSize:
        fm = self.fontMetrics()
        text = self.text()
        text_w = fm.horizontalAdvance(text) if text else 0
        text_h = fm.height()
        w = self._TRACK_W + (self._LABEL_SPACING + text_w if text else 0) + 2
        h = max(self._TRACK_H, text_h) + 4
        return QSize(w, h)

    def minimumSizeHint(self) -> QSize:
        return self.sizeHint()

    def hitButton(self, pos) -> bool:
        return self.rect().contains(pos)

    def paintEvent(self, event):  # noqa: N802 (Qt API)
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)

        checked = self.isChecked()
        enabled = self.isEnabled()

        track_y = (self.height() - self._TRACK_H) / 2
        track_rect = QRectF(0.0, float(track_y),
                            float(self._TRACK_W), float(self._TRACK_H))

        bg = QColor(self._COLOR_ON if checked else self._COLOR_OFF)
        line = QColor(self._COLOR_ON if checked else self._COLOR_OFF_LINE)
        if not enabled:
            bg.setAlpha(110)
            line.setAlpha(110)
        # Inset by half the pen so the 1px frame is not clipped away.
        track_rect = track_rect.adjusted(0.5, 0.5, -0.5, -0.5)
        p.setPen(QPen(line, 1.0))
        p.setBrush(QBrush(bg))
        r = track_rect.height() / 2.0
        p.drawRoundedRect(track_rect, r, r)
        p.setPen(Qt.NoPen)

        knob_d = self._TRACK_H - 2 * self._KNOB_MARGIN
        if checked:
            knob_x = track_rect.right() - self._KNOB_MARGIN - knob_d
        else:
            knob_x = track_rect.left() + self._KNOB_MARGIN
        knob_y = track_rect.top() + self._KNOB_MARGIN
        knob_color = QColor((self._COLOR_KNOB_ON if checked else self._COLOR_KNOB_OFF)
                            if enabled else self._COLOR_DISABLED_KNOB)
        p.setBrush(QBrush(knob_color))
        p.drawEllipse(QRectF(float(knob_x), float(knob_y),
                             float(knob_d), float(knob_d)))

        text = self.text()
        if text:
            text_color = QColor(COLOR_TEXT)
            if not enabled:
                text_color.setAlpha(140)
            p.setPen(text_color)
            text_x = self._TRACK_W + self._LABEL_SPACING
            p.drawText(
                QRectF(float(text_x), 0.0,
                       float(self.width() - text_x), float(self.height())),
                int(Qt.AlignVCenter | Qt.AlignLeft),
                text,
            )
        p.end()


class Invoker(QObject):
    """Lives on the UI thread. Other threads can ask it to run callables
    by emitting signals — signals are thread-safe and queued."""

    _invoke = Signal(int, object)  # (delay_ms, callable)

    def __init__(self):
        super().__init__()
        self._invoke.connect(self._on_invoke, Qt.QueuedConnection)

    def schedule(self, delay_ms: int, func: Callable) -> None:
        self._invoke.emit(int(delay_ms), func)

    def _on_invoke(self, delay_ms: int, func: Callable) -> None:
        if delay_ms <= 0:
            func()
        else:
            QTimer.singleShot(delay_ms, func)


class MainWindow(QMainWindow):
    """QMainWindow that hands the X-button close back to the controller."""

    def __init__(self):
        super().__init__()
        self._close_handler: Optional[Callable] = None
        self._allow_close = False

    def set_close_handler(self, cb: Callable) -> None:
        self._close_handler = cb

    def allow_close(self) -> None:
        self._allow_close = True

    def closeEvent(self, event):
        if self._allow_close or self._close_handler is None:
            event.accept()
            return
        # Hand control to the controller; it decides hide vs quit.
        try:
            self._close_handler()
        except Exception:
            event.accept()
            return
        event.ignore()


class Card(QFrame):
    """QFrame styled as a rounded card."""

    def __init__(self, dark_bg: bool = False, parent=None):
        super().__init__(parent)
        self.setObjectName("cardDark" if dark_bg else "card")


class SliderProxy:
    """Wraps a QSlider so the controller can speak in floats 0.0–1.0
    instead of the slider's integer range."""

    def __init__(self, slider: QSlider):
        self._slider = slider

    def set(self, value: float):
        v = max(0, min(1000, int(round(float(value) * 1000))))
        # blockSignals so programmatic updates don't echo back through the controller.
        self._slider.blockSignals(True)
        self._slider.setValue(v)
        self._slider.blockSignals(False)

    def get(self) -> float:
        return self._slider.value() / 1000.0


class ProgressProxy:
    def __init__(self, bar):
        self._bar = bar

    def set(self, value: float):
        v = max(0, min(1000, int(round(float(value) * 1000))))
        self._bar.setValue(v)

    def get(self) -> float:
        return self._bar.value() / 1000.0


class RainbowMeter(QWidget):
    """Read-only intensity meter painted with a static brand-rainbow track.

    Unlike QProgressBar, the rainbow lives on the full-width track and the
    unfilled portion is masked by an opaque overlay in the bg color — so
    each color holds a fixed horizontal position regardless of the
    current value. Same visual contract as the slider gradient.

    API mirrors QProgressBar.setValue/value so ProgressProxy works
    unchanged.
    """

    def __init__(self, parent: Optional[QWidget] = None, maximum: int = 1000):
        super().__init__(parent)
        self._max = max(1, int(maximum))
        self._value = 0
        self.setFixedHeight(8)

    # -- QProgressBar-compatible API -----------------------------------
    def setRange(self, minimum: int, maximum: int) -> None:
        # minimum is assumed 0 — matches QProgressBar usage in this app.
        self._max = max(1, int(maximum))
        self.update()

    def setValue(self, v: int) -> None:
        v = max(0, min(self._max, int(v)))
        if v != self._value:
            self._value = v
            self.update()

    def value(self) -> int:
        return self._value

    def maximum(self) -> int:
        return self._max

    def setTextVisible(self, _visible: bool) -> None:  # no-op, here for parity
        return

    # -- Painting ------------------------------------------------------
    def paintEvent(self, _ev) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        w = self.width()
        h = self.height()
        radius = h / 2.0

        # Track: the well inside a 1px frame line (inset half a pen so
        # the outline is not clipped by the widget edge).
        track = QRectF(0.5, 0.5, w - 1.0, h - 1.0)
        p.setPen(QPen(QColor(_C.COLOR_LINE), 1.0))
        p.setBrush(QBrush(QColor(_C.COLOR_WELL)))
        p.drawRoundedRect(track, radius, radius)

        # Fill: the live ramp -- accent at rest, pink as it saturates --
        # painted on the full track and clipped, so every colour keeps a
        # fixed position regardless of the value.
        filled = (self._value / self._max) * (w - 2.0) if self._max else 0
        if filled > 0:
            inner = QRectF(1.0, 1.0, w - 2.0, h - 2.0)
            grad = QLinearGradient(inner.left(), 0, inner.right(), 0)
            grad.setColorAt(0.0, QColor(_C.COLOR_ACCENT))
            grad.setColorAt(1.0, QColor(_C.COLOR_LIVE))
            p.setPen(Qt.NoPen)
            p.setBrush(QBrush(grad))
            p.setClipRect(QRectF(0, 0, 1.0 + filled, h))
            ir = max(0.0, radius - 1.0)
            p.drawRoundedRect(inner, ir, ir)
        p.end()


def install_rainbow_scrollbars(scroll_area) -> None:
    """Replace a QScrollArea's default scrollbars with RainbowScrollBars.

    Call right after constructing a QScrollArea so both orientations get
    the static-gradient track + rounded-pill handle treatment.
    """
    scroll_area.setVerticalScrollBar(RainbowScrollBar(Qt.Vertical, scroll_area))
    scroll_area.setHorizontalScrollBar(RainbowScrollBar(Qt.Horizontal, scroll_area))


class RainbowScrollBar(QScrollBar):
    """QScrollBar that paints a static gradient on the full track and shows
    the handle as a rounded pill "window" revealing the gradient slice
    behind it. Same visual idea as the RainbowMeter, but the visible
    portion (the handle) is positioned by scroll value, not by fill.

    Pure-QSS can't do this — masking the handle area with rounded inner
    corners on ::sub-page / ::add-page produces inverted-notch artifacts.
    Custom paint sidesteps that by drawing the track and the dark mask as
    a single QPainterPath (mask = full-rounded-track − handle-pill).
    """

    _CORNER_RADIUS = 5

    def _handle_rect(self) -> QRectF:
        opt = QStyleOptionSlider()
        self.initStyleOption(opt)
        rect = self.style().subControlRect(
            QStyle.CC_ScrollBar, opt, QStyle.SC_ScrollBarSlider, self
        )
        return QRectF(rect)

    def paintEvent(self, _ev) -> None:  # noqa: N802 (Qt API)
        # The 518 scrollbar: a transparent track and a thumb in the frame
        # line that lights to the accent under the mouse.
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        handle = self._handle_rect()
        if handle.isValid() and handle.width() > 0 and handle.height() > 0:
            handle = handle.adjusted(2, 2, -2, -2)
            handle_radius = min(handle.width(), handle.height()) / 2.0
            colour = QColor(_C.COLOR_ACCENT if self.underMouse() else _C.COLOR_LINE)
            p.setPen(Qt.NoPen)
            p.setBrush(QBrush(colour))
            p.drawRoundedRect(handle, handle_radius, handle_radius)
        p.end()
