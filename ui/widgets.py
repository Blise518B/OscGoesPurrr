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

    _TRACK_W = 40
    _TRACK_H = 20
    _KNOB_MARGIN = 2
    _LABEL_SPACING = 8

    _COLOR_OFF = QColor(COLOR_BUTTON)
    _COLOR_ON = QColor(COLOR_LIVE)
    _COLOR_KNOB = QColor("#FFFFFF")
    _COLOR_DISABLED_KNOB = QColor("#CCCCCC")

    def __init__(self, text: str = "", parent=None):
        super().__init__(text, parent)
        self.setCursor(Qt.PointingHandCursor)

    def sizeHint(self) -> QSize:
        fm = self.fontMetrics()
        text = self.text()
        text_w = fm.horizontalAdvance(text) if text else 0
        text_h = fm.height()
        w = self._TRACK_W + (self._LABEL_SPACING + text_w if text else 0)
        h = max(self._TRACK_H, text_h) + 2
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
        if not enabled:
            bg.setAlpha(110)

        p.setPen(Qt.NoPen)
        p.setBrush(QBrush(bg))
        p.drawRoundedRect(track_rect, self._TRACK_H / 2.0, self._TRACK_H / 2.0)

        knob_d = self._TRACK_H - 2 * self._KNOB_MARGIN
        if checked:
            knob_x = track_rect.right() - self._KNOB_MARGIN - knob_d
        else:
            knob_x = track_rect.left() + self._KNOB_MARGIN
        knob_y = track_rect.top() + self._KNOB_MARGIN
        knob_color = QColor(self._COLOR_KNOB if enabled else self._COLOR_DISABLED_KNOB)
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


class BHapticsDotGrid(QWidget):
    """Live debug grid of dots for one bHaptics device.

    Dots fill left-to-right, top-to-bottom — matching the dot-mode index
    ordering bHaptics expects. Color interpolates red(0%) → yellow(50%) →
    green(100%) so you can see which nodes are active and how hard.
    """

    DOT_PX = 18
    SPACING = 6
    PADDING = 4

    # Debug click-to-test signals. Mouse press emits dotPressed(index) and
    # dotReleased(prev_index_or_-1) so the controller can drive that single
    # dot at 100% intensity while held. Drag across dots cleanly releases the
    # previous index before pressing the new one.
    dotPressed = Signal(int)
    dotReleased = Signal(int)

    def __init__(self, node_count: int, cols: int, rows: int, parent=None, interactive: bool = True):
        super().__init__(parent)
        self.node_count = max(0, int(node_count))
        self.cols = max(1, int(cols))
        self.rows = max(1, int(rows))
        self._values: List[int] = [0] * self.node_count
        w = self.PADDING * 2 + self.cols * self.DOT_PX + (self.cols - 1) * self.SPACING
        h = self.PADDING * 2 + self.rows * self.DOT_PX + (self.rows - 1) * self.SPACING
        self.setFixedSize(int(w), int(h))
        self._active_dot: int = -1
        self._interactive = bool(interactive)
        if self._interactive:
            self.setCursor(Qt.PointingHandCursor)
            self.setToolTip("Click and hold a dot to fire it at 100% (debug test).")
        else:
            self.setToolTip("Raw OSC input — pre anti-stuck, pre manual override.")

    def set_values(self, values):
        """values: iterable of ints 0..100, length should match node_count.
        None or shorter iterables get treated as all-zeros for missing slots."""
        new_vals = [0] * self.node_count
        if values:
            for i, v in enumerate(values):
                if i >= self.node_count:
                    break
                try:
                    new_vals[i] = max(0, min(100, int(v)))
                except (TypeError, ValueError):
                    new_vals[i] = 0
        if new_vals != self._values:
            self._values = new_vals
            self.update()

    @staticmethod
    def _color_for(value: int) -> QColor:
        # Three-stop interpolation: 0 → red, 50 → yellow, 100 → green.
        # Slightly dim red at 0 so off-nodes read as "off" not "alerting".
        v = max(0, min(100, int(value)))
        if v <= 50:
            t = v / 50.0
            r = int(180 + (255 - 180) * t)
            g = int( 50 + (200 -  50) * t)
            b = int( 50 + ( 50 -  50) * t)
        else:
            t = (v - 50) / 50.0
            r = int(255 + ( 70 - 255) * t)
            g = int(200 + (200 - 200) * t)
            b = int( 50 + ( 70 -  50) * t)
        return QColor(r, g, b)

    def paintEvent(self, _ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        p.fillRect(self.rect(), QColor("#1A1A26"))
        pen_off = QPen(QColor(80, 80, 100, 180))
        pen_off.setWidth(1)
        # Bright white ring around the dot the user is currently click-holding,
        # so the press reads instantly without waiting on the snapshot tick.
        pen_active = QPen(QColor("#FFFFFF"))
        pen_active.setWidth(2)
        diameter = self.DOT_PX
        for i in range(self.node_count):
            col = i % self.cols
            row = i // self.cols
            if row >= self.rows:
                break
            x = self.PADDING + col * (diameter + self.SPACING)
            y = self.PADDING + row * (diameter + self.SPACING)
            value = self._values[i] if i < len(self._values) else 0
            fill = self._color_for(value)
            is_active = (i == self._active_dot)
            p.setPen(pen_active if is_active else pen_off)
            p.setBrush(QBrush(fill))
            p.drawEllipse(x, y, diameter, diameter)
        p.end()

    def _dot_at(self, pos) -> int:
        """Return the 0-based dot index at widget-local pos, or -1 if none."""
        diameter = self.DOT_PX
        x = pos.x()
        y = pos.y()
        for i in range(self.node_count):
            col = i % self.cols
            row = i // self.cols
            if row >= self.rows:
                break
            dx = self.PADDING + col * (diameter + self.SPACING)
            dy = self.PADDING + row * (diameter + self.SPACING)
            if dx <= x <= dx + diameter and dy <= y <= dy + diameter:
                return i
        return -1

    def _set_active(self, idx: int) -> None:
        if idx == self._active_dot:
            return
        if self._active_dot >= 0:
            self.dotReleased.emit(self._active_dot)
        self._active_dot = idx
        if idx >= 0:
            self.dotPressed.emit(idx)
        # Repaint so the highlight ring tracks the press instantly, without
        # waiting on the 100 ms snapshot tick that drives fill color.
        self.update()

    def mousePressEvent(self, ev):
        if self._interactive and ev.button() == Qt.LeftButton:
            self._set_active(self._dot_at(ev.position().toPoint()))
            ev.accept()
            return
        super().mousePressEvent(ev)

    def mouseMoveEvent(self, ev):
        if self._interactive and (ev.buttons() & Qt.LeftButton):
            self._set_active(self._dot_at(ev.position().toPoint()))
            ev.accept()
            return
        super().mouseMoveEvent(ev)

    def mouseReleaseEvent(self, ev):
        if self._interactive and ev.button() == Qt.LeftButton:
            self._set_active(-1)
            ev.accept()
            return
        super().mouseReleaseEvent(ev)

    def leaveEvent(self, ev):
        # If the mouse leaves while still held, release; if it re-enters we'll
        # repress on mouseMove. Prevents a stuck dot when the user drags off.
        if self._interactive:
            self._set_active(-1)
        super().leaveEvent(ev)


class BHapticsDotPicker(QWidget):
    """Click-to-toggle grid for choosing a subset of dot indices on a
    single bHaptics device. Used by the SPS-mirror entry editor: each
    entry maps one OGB zone onto these picked dots.

    Visual differs from `BHapticsDotGrid` deliberately:
      * No animated intensity colors — picker dots are either selected
        (bright accent) or unselected (dim grey).
      * Each dot shows its 0-based index in small text so the user can
        match what they see here against bHaptics docs / the live-debug
        grid (which uses the same numbering).
      * Click toggles membership; click-and-drag paint-toggles with the
        first dot's new state, so it's quick to fill or clear a region.
    """

    DOT_PX = 24
    SPACING = 5
    PADDING = 6

    selectionChanged = Signal()

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.node_count = 0
        self.cols = 1
        self.rows = 1
        self._selected: set = set()
        # Drag-paint state: when the mouse press toggles a dot, the new
        # state of that dot becomes the "paint value" for the rest of
        # the drag. Mouse-move dots get forced to that state — so the
        # user paints in or paints out cleanly without flickering.
        self._drag_paint_state: Optional[bool] = None
        self._hover_idx: int = -1
        self.setMouseTracking(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip(
            "Click a dot to toggle. Click and drag to paint multiple dots "
            "in one motion (the first dot's new state is painted onto the rest)."
        )

    def set_device(self, cols: int, rows: int, node_count: int) -> None:
        """Reconfigure the picker for a different device layout. Any
        previously-selected indices that no longer fit on the new
        device are dropped silently."""
        self.cols = max(1, int(cols))
        self.rows = max(1, int(rows))
        self.node_count = max(0, int(node_count))
        w = self.PADDING * 2 + self.cols * self.DOT_PX + (self.cols - 1) * self.SPACING
        h = self.PADDING * 2 + self.rows * self.DOT_PX + (self.rows - 1) * self.SPACING
        self.setFixedSize(int(w), int(h))
        # Drop out-of-range selections so a position change doesn't
        # silently keep dot 17 selected when the new device has 6 nodes.
        self._selected = {i for i in self._selected if 0 <= i < self.node_count}
        self.update()

    def set_selection(self, indices) -> None:
        """Replace the selection set. Does NOT emit selectionChanged —
        meant for syncing the widget from a parallel source (e.g. the
        text line edit) without ping-ponging the signal."""
        try:
            new_sel = {int(i) for i in (indices or [])
                       if 0 <= int(i) < self.node_count}
        except (TypeError, ValueError):
            new_sel = set()
        if new_sel != self._selected:
            self._selected = new_sel
            self.update()

    def selection(self) -> List[int]:
        return sorted(self._selected)

    def _dot_at(self, pos) -> int:
        diameter = self.DOT_PX
        x = pos.x()
        y = pos.y()
        for i in range(self.node_count):
            col = i % self.cols
            row = i // self.cols
            if row >= self.rows:
                break
            dx = self.PADDING + col * (diameter + self.SPACING)
            dy = self.PADDING + row * (diameter + self.SPACING)
            if dx <= x <= dx + diameter and dy <= y <= dy + diameter:
                return i
        return -1

    def _paint_dot(self, idx: int, on: bool) -> bool:
        """Set dot `idx` to `on`; return True if anything changed."""
        if idx < 0 or idx >= self.node_count:
            return False
        if on and idx not in self._selected:
            self._selected.add(idx)
            return True
        if (not on) and idx in self._selected:
            self._selected.discard(idx)
            return True
        return False

    def mousePressEvent(self, ev):
        if ev.button() != Qt.LeftButton:
            super().mousePressEvent(ev)
            return
        idx = self._dot_at(ev.position().toPoint())
        if idx < 0:
            ev.accept()
            return
        # Toggle this dot; remember the new state so the rest of the
        # drag follows it.
        new_state = idx not in self._selected
        if self._paint_dot(idx, new_state):
            self._drag_paint_state = new_state
            self.update()
            self.selectionChanged.emit()
        else:
            self._drag_paint_state = new_state
        ev.accept()

    def mouseMoveEvent(self, ev):
        idx = self._dot_at(ev.position().toPoint())
        if idx != self._hover_idx:
            self._hover_idx = idx
            self.update()
        if self._drag_paint_state is not None and (ev.buttons() & Qt.LeftButton):
            if idx >= 0 and self._paint_dot(idx, self._drag_paint_state):
                self.update()
                self.selectionChanged.emit()
        ev.accept()

    def mouseReleaseEvent(self, ev):
        if ev.button() == Qt.LeftButton:
            self._drag_paint_state = None
            ev.accept()
            return
        super().mouseReleaseEvent(ev)

    def leaveEvent(self, ev):
        if self._hover_idx != -1:
            self._hover_idx = -1
            self.update()
        super().leaveEvent(ev)

    def paintEvent(self, _ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        p.fillRect(self.rect(), QColor("#1A1A26"))

        fill_on = QColor("#4FC3F7")    # bright cyan — selected
        fill_off = QColor("#33344A")   # dim — unselected
        pen_off = QPen(QColor(80, 80, 100, 180)); pen_off.setWidth(1)
        pen_on = QPen(QColor("#80DCFF")); pen_on.setWidth(2)
        pen_hover = QPen(QColor("#FFFFFF")); pen_hover.setWidth(2)
        text_on = QColor("#0B1A28")    # dark text on bright dot
        text_off = QColor(180, 180, 200)

        f = p.font(); f.setPointSize(7); f.setBold(True); p.setFont(f)
        diameter = self.DOT_PX
        for i in range(self.node_count):
            col = i % self.cols
            row = i // self.cols
            if row >= self.rows:
                break
            x = self.PADDING + col * (diameter + self.SPACING)
            y = self.PADDING + row * (diameter + self.SPACING)
            is_sel = i in self._selected
            if i == self._hover_idx:
                p.setPen(pen_hover)
            else:
                p.setPen(pen_on if is_sel else pen_off)
            p.setBrush(QBrush(fill_on if is_sel else fill_off))
            p.drawEllipse(x, y, diameter, diameter)
            p.setPen(text_on if is_sel else text_off)
            p.drawText(QRectF(x, y, diameter, diameter), Qt.AlignCenter, str(i))
        p.end()


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

        # Static rainbow on the full track. Stops match the slider groove
        # and QProgressBar[tone="rainbow"] QSS so the visual language is
        # consistent across the app.
        grad = QLinearGradient(0, 0, w, 0)
        grad.setColorAt(0.0, QColor(COLOR_PRIMARY))
        grad.setColorAt(1.0, QColor(COLOR_LIVE))
        p.setPen(Qt.NoPen)
        p.setBrush(QBrush(grad))
        p.drawRoundedRect(QRectF(0, 0, w, h), radius, radius)

        # Mask the unfilled (right-side) portion with the bg color, so the
        # filled portion reveals the rainbow at its fixed position. The
        # mask extends 1px past the right edge so the rainbow's rounded
        # corner can't peek through.
        filled = (self._value / self._max) * w if self._max else 0
        if filled < w:
            p.setBrush(QBrush(QColor(COLOR_BG)))
            p.drawRoundedRect(QRectF(filled, 0, w - filled + 1, h), radius, radius)

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
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        w, h = self.width(), self.height()
        vertical = self.orientation() == Qt.Vertical
        bar_rect = QRectF(0, 0, w, h)
        r = float(self._CORNER_RADIUS)

        # 1. Paint the full track with the brand gradient (rounded).
        if vertical:
            grad = QLinearGradient(0, 0, 0, h)
        else:
            grad = QLinearGradient(0, 0, w, 0)
        grad.setColorAt(0.0, QColor(COLOR_PRIMARY))
        grad.setColorAt(1.0, QColor(COLOR_LIVE))
        p.setPen(Qt.NoPen)
        p.setBrush(QBrush(grad))
        p.drawRoundedRect(bar_rect, r, r)

        # 2. Mask everything outside the handle pill with bg color, so only
        #    the slice under the handle reveals the gradient.
        handle = self._handle_rect()
        if handle.isValid() and handle.width() > 0 and handle.height() > 0:
            full_path = QPainterPath()
            full_path.addRoundedRect(bar_rect, r, r)
            handle_path = QPainterPath()
            handle_radius = min(handle.width(), handle.height()) / 2.0
            handle_path.addRoundedRect(handle, handle_radius, handle_radius)
            mask = full_path.subtracted(handle_path)
            p.setBrush(QBrush(QColor(COLOR_BG)))
            p.drawPath(mask)

        p.end()
