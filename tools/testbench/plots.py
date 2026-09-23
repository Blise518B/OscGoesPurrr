"""pyqtgraph plot widgets for the bench.

Two widgets:

* :class:`LivePlot` — input vs output on one scrolling time axis (last
  ``window_s`` seconds), refreshed by the app on a timer from
  ``BenchEngine.snapshot()``.
* :class:`LatencyHistogram` — distribution of measured latencies (ms).

pyqtgraph's global background/foreground is set once to match the dark theme.
"""

from __future__ import annotations

import numpy as np
import pyqtgraph as pg
from PySide6.QtWidgets import QVBoxLayout, QWidget

from .style import COLOR_BG, COLOR_LIVE, COLOR_PRIMARY, COLOR_SUCCESS, COLOR_TEXT_MUTED

pg.setConfigOptions(antialias=True, background=COLOR_BG, foreground=COLOR_TEXT_MUTED)

_INPUT_PEN = pg.mkPen(COLOR_PRIMARY, width=2)
_OUTPUT_PEN = pg.mkPen(COLOR_LIVE, width=2)


class LivePlot(QWidget):
    """Scrolling input-vs-output line plot, values in 0..1 on a shared axis."""

    def __init__(self, window_s: float = 8.0, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._window_s = float(window_s)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)

        self._pw = pg.PlotWidget()
        self._pw.setYRange(0.0, 1.02, padding=0)
        self._pw.setLabel("left", "level (0..1)")
        self._pw.setLabel("bottom", "time (s)")
        self._pw.showGrid(x=True, y=True, alpha=0.18)
        self._pw.addLegend(offset=(-10, 10))
        # Render only visible, downsampled points so zooming/panning into a long
        # trace stays fast — otherwise pyqtgraph redraws every point each frame.
        self._pw.setClipToView(True)
        self._pw.setDownsampling(auto=True, mode="peak")
        self._in_curve = self._pw.plot([], [], pen=_INPUT_PEN, name="input → target")
        self._out_curve = self._pw.plot([], [], pen=_OUTPUT_PEN, name="toy output")
        lay.addWidget(self._pw)

    def set_window(self, seconds: float) -> None:
        self._window_s = float(seconds)

    def update_from(self, in_arr: np.ndarray, out_arr: np.ndarray) -> None:
        latest = 0.0
        if in_arr.size:
            latest = max(latest, float(in_arr[-1, 0]))
        if out_arr.size:
            latest = max(latest, float(out_arr[-1, 0]))
        x0 = latest - self._window_s

        def _clip(a: np.ndarray):
            if not a.size:
                return [], []
            mask = a[:, 0] >= x0
            return a[mask, 0], a[mask, 1]

        ix, iy = _clip(in_arr)
        ox, oy = _clip(out_arr)
        self._in_curve.setData(ix, iy)
        self._out_curve.setData(ox, oy)
        self._pw.setXRange(x0, latest if latest > x0 else x0 + self._window_s, padding=0)


class LatencyHistogram(QWidget):
    """Histogram of measured end-to-end latencies (ms)."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self._pw = pg.PlotWidget()
        self._pw.setLabel("left", "count")
        self._pw.setLabel("bottom", "latency (ms)")
        self._pw.showGrid(x=True, y=True, alpha=0.18)
        lay.addWidget(self._pw)

    def update_from(self, latencies_ms) -> None:
        self._pw.clear()
        if not latencies_ms:
            return
        arr = np.asarray(latencies_ms, dtype=float)
        bins = int(min(30, max(5, round(arr.size ** 0.5))))
        counts, edges = np.histogram(arr, bins=bins)
        bg = pg.BarGraphItem(
            x0=edges[:-1], x1=edges[1:], height=counts,
            brush=COLOR_SUCCESS, pen=pg.mkPen(COLOR_BG, width=1),
        )
        self._pw.addItem(bg)
        # Pin the view to the data — otherwise the bars render off-scale (the
        # axes keep a stale range from when only a few small samples existed).
        lo, hi = float(edges[0]), float(edges[-1])
        if hi <= lo:
            hi = lo + 1.0
        self._pw.setXRange(lo, hi, padding=0.05)
        ymax = float(counts.max()) if counts.size and counts.max() > 0 else 1.0
        self._pw.setYRange(0.0, ymax, padding=0.08)
