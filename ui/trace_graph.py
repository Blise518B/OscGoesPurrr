"""Custom-painted scrolling time-series widget used throughout the
chain visual: per-stage mini-graphs in `MotorSignalChainWidget`, the
optional six-trace Overview disclosure in `MotorChainListWidget`, and
any other place that wants a live signal plot.

Designed to be data-source-agnostic: callers push samples via
`push_sample(trace_id, t_s, value)` and the widget owns the per-trace
ring buffers and the paint. No internal timer — the widget repaints
on every push, so paint frequency naturally tracks the data source's
tick rate.

Pushes are fed by the router's per-(motor, chain) intermediates
subscribers (see `MotorRouter.subscribe_intermediates`)."""

from collections import deque
from typing import Iterable, Optional, Tuple

from PySide6.QtCore import Qt, QPointF
from PySide6.QtGui import QColor, QPainter, QPen, QPolygonF
from PySide6.QtWidgets import QWidget

from constants import COLOR_INPUT_BG, COLOR_SUCCESS, COLOR_TEXT


# Reasonable cap so a long-lived widget that never gets samples popped
# from the back (e.g. driver paused at a huge dt) can't accumulate
# unbounded memory. At ~60 Hz with a 3-second window, ~180 samples per
# trace is the working set — 4096 is generous headroom.
_MAX_SAMPLES_PER_TRACE = 4096


class TraceGraph(QWidget):
    """Scrolling line graph for one or more (trace_id, color) pairs.

    Sample values are assumed to lie in [0, 1] — the widget rescales
    them to its drawing area with y=0 at the bottom edge and y=1 at the
    top. Out-of-range samples are clipped during paint (the ring buffer
    keeps them as-is so a later visibility toggle reveals the truth)."""

    DEFAULT_TRACE_ID = "output"

    def __init__(self,
                 traces: Optional[Iterable[Tuple[str, str]]] = None,
                 window_s: float = 3.0,
                 parent: Optional[QWidget] = None) -> None:
        """`traces` is an iterable of (trace_id, color) or
        (trace_id, color, style_dict). style_dict may contain
        `width` (float, default 1.6) and `dash` (one of 'solid',
        'dash', 'dot', 'dashdot'; default 'solid'). Dashed/dotted
        styles let overlapping traces stay individually readable —
        useful for the Tune view's Raw vs Influence pairs that lie
        on top of each other at default gain/curve."""
        super().__init__(parent)
        if traces is None:
            traces = [(self.DEFAULT_TRACE_ID, COLOR_SUCCESS)]
        self._traces: dict = {}
        for spec in traces:
            if len(spec) == 2:
                trace_id, color = spec
                style: dict = {}
            else:
                trace_id, color, style = spec
            self._traces[trace_id] = {
                "color": str(color),
                "visible": True,
                "samples": deque(maxlen=_MAX_SAMPLES_PER_TRACE),
                "width": float(style.get("width", 1.6)),
                "dash": str(style.get("dash", "solid")),
            }
        self._window_s = float(window_s)
        self.setMinimumHeight(36)

    # ------------------------------------------------------------------
    # Data ingestion
    # ------------------------------------------------------------------

    def push_sample(self, trace_id: str, t_s: float, value: float) -> None:
        """Append a sample and request a repaint. Stale samples that
        fall outside the time window are dropped lazily during paint —
        leaving them in the buffer keeps push_sample O(1)."""
        trace = self._traces.get(trace_id)
        if trace is None:
            return
        trace["samples"].append((float(t_s), float(value)))
        self.update()

    def set_trace_visible(self, trace_id: str, visible: bool) -> None:
        trace = self._traces.get(trace_id)
        if trace is None:
            return
        trace["visible"] = bool(visible)
        self.update()

    def clear(self) -> None:
        """Wipe every trace's history. Used by Tune view when the
        selected motor changes."""
        for trace in self._traces.values():
            trace["samples"].clear()
        self.update()

    # ------------------------------------------------------------------
    # Painting
    # ------------------------------------------------------------------

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        rect = self.rect()
        p.fillRect(rect, QColor(COLOR_INPUT_BG))

        # The widget's "current time" is the newest sample across all
        # visible traces. With no samples there's nothing to draw.
        max_t = self._max_visible_sample_time()
        if max_t is None:
            return

        t_start = max_t - self._window_s
        w = float(rect.width())
        h = float(rect.height())
        if w <= 0.0 or h <= 0.0:
            return

        # Faint baseline grid (zero, mid, full) so the eye has reference
        # marks. Painted under the traces.
        grid_pen = QPen(QColor(COLOR_TEXT))
        grid_pen.setStyle(Qt.DotLine)
        grid_pen.setColor(QColor(60, 60, 60))
        p.setPen(grid_pen)
        for frac in (0.0, 0.5, 1.0):
            y = h - (h * frac)
            p.drawLine(QPointF(0.0, y), QPointF(w, y))

        for trace in self._traces.values():
            if not trace["visible"]:
                continue
            samples = trace["samples"]
            if len(samples) < 2:
                continue
            pen = QPen(QColor(trace["color"]), float(trace.get("width", 1.6)))
            pen.setCosmetic(True)
            dash = trace.get("dash", "solid")
            if dash == "dash":
                pen.setStyle(Qt.DashLine)
            elif dash == "dot":
                pen.setStyle(Qt.DotLine)
            elif dash == "dashdot":
                pen.setStyle(Qt.DashDotLine)
            p.setPen(pen)
            poly = QPolygonF()
            for t, v in samples:
                if t < t_start:
                    continue
                x = w * (t - t_start) / self._window_s
                # Clip y to the drawing area; out-of-range samples are
                # kept in the buffer but pinned to the edge for paint.
                v_clamped = max(0.0, min(1.0, v))
                y = h - (h * v_clamped)
                poly.append(QPointF(x, y))
            if poly.size() >= 2:
                p.drawPolyline(poly)

        p.end()

    # ------------------------------------------------------------------

    def _max_visible_sample_time(self) -> Optional[float]:
        max_t: Optional[float] = None
        for trace in self._traces.values():
            if not trace["visible"]:
                continue
            samples = trace["samples"]
            if not samples:
                continue
            t_last = samples[-1][0]
            if max_t is None or t_last > max_t:
                max_t = t_last
        return max_t
