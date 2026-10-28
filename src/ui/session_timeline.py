"""A session's timeline on the Statistics page: an intensity lane per toy,
thrusts per minute, a contact lane per zone and the people lane, on one
clock-time axis -- with hover values and a drag that selects a stretch to
tag. Its colours and painting helpers are stats_charts'."""

import math
import time
from typing import Any, Dict, List, Mapping, NamedTuple, Optional, Sequence, Tuple

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QToolTip, QWidget

from ui import theme as _theme
from ui.stats_charts import (
    chart_font, chrome_color, draw_text, fmt_clock, qcolor, runs, toy_color, zone_color,
    zone_label,
)


class _Frame(NamedTuple):
    """Where one paint draws: the plot's x range, the buckets, the columns
    they are drawn in, and the axis line's y."""
    left: float
    right: float
    pw: float
    n: int
    bs: float
    cols: List[Tuple[int, int]]
    bottom: float


class SessionTimeline(QWidget):
    """A session's timeline: intensity lane per toy, thrusts per minute,
    contact lane per zone and the people lane, on one clock-time axis.
    Hover shows a crosshair and the values in that slice; a drag selects
    a stretch and emits `stretchSelected(start epoch, end epoch)`, snapped
    to whole buckets. The selection stays drawn until `clear_selection`."""

    stretchSelected = Signal(float, float)

    _LABEL_W = 116
    _TOP = 20
    _TOY_H, _TOY_GAP = 36, 8
    _THR_H, _THR_GAP = 44, 12
    _CAPTION_H = 16
    _ZONE_H, _ZONE_GAP = 14, 6
    _PEOPLE_H, _PEOPLE_GAP = 16, 4
    _AXIS_H = 20
    _MIN_COL_PX = 3.0
    # A press that moves less than this is a click, not a selection.
    _MIN_DRAG_PX = 4.0

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._d: Dict[str, Any] = {}
        self._a: Dict[str, Any] = {}
        self._toys: List[str] = []
        self._zones: List[str] = []
        self._started = 0.0
        self._hover_col: Optional[int] = None
        # Tagged stretches: (start epoch, end epoch, label, row).
        self._tags: List[Tuple[float, float, str, int]] = []
        self._tag_rows = 0
        # The selection, in epochs (so it holds still while a running
        # session's axis grows), and the drag making it.
        self._sel: Optional[Tuple[float, float]] = None
        self._drag_x0: Optional[float] = None
        self.setMinimumWidth(420)
        self.setMouseTracking(True)
        self.setFixedHeight(self._TOP + self._AXIS_H)

    def set_detail(self, detail: Mapping[str, Any]) -> None:
        self._d = dict(detail.get("dense") or {})
        self._a = dict(detail.get("analysis") or {})
        self._started = float(detail.get("started_ts") or 0.0)
        toys = detail.get("toys") or {}
        self._toys = sorted(self._d.get("toys", {}),
                            key=lambda n: (-float(toys.get(n, 0.0)), n.lower()))
        zones = detail.get("zones") or {}
        self._zones = sorted(self._d.get("zones", {}),
                             key=lambda z: (-float(zones.get(z, 0.0)), z.lower()))
        self._resize()

    def set_tags(self, stretches: Sequence[Tuple[float, float, str]]) -> None:
        """The tagged stretches to draw: (start epoch, end epoch, label).
        Overlapping ones stack on rows of the people lane."""
        rows_end: List[float] = []
        tags = []
        for start, end, label in sorted(stretches, key=lambda t: (t[0], t[1])):
            row = next((r for r, e in enumerate(rows_end) if e <= start), None)
            if row is None:
                row = len(rows_end)
                rows_end.append(end)
            else:
                rows_end[row] = end
            tags.append((float(start), float(end), str(label), row))
        self._tags = tags
        self._tag_rows = len(rows_end)
        self._resize()

    def clear_selection(self) -> None:
        self._sel = None
        self._drag_x0 = None
        self.update()

    def _resize(self) -> None:
        h = (self._TOP
             + len(self._toys) * (self._TOY_H + self._TOY_GAP)
             + self._THR_H + self._THR_GAP
             + (self._CAPTION_H + len(self._zones) * (self._ZONE_H + self._ZONE_GAP)
                if self._zones else 0)
             + (self._CAPTION_H + self._tag_rows * (self._PEOPLE_H + self._PEOPLE_GAP)
                if self._tag_rows else 0)
             + self._AXIS_H)
        self.setFixedHeight(int(h))
        self.update()

    def toy_order(self) -> List[str]:
        """Toys in lane order — lane k wears toy_color(k)."""
        return list(self._toys)

    # geometry -----------------------------------------------------------

    def _plot(self) -> Tuple[float, float]:
        left = float(self._LABEL_W)
        return left, max(10.0, float(self.width()) - left - 6.0)

    def _columns(self) -> List[Tuple[int, int]]:
        """Bucket ranges [a, b) per drawn column."""
        n = int(self._d.get("n", 0))
        if n <= 0:
            return []
        _left, pw = self._plot()
        c = max(1, min(n, int(pw // self._MIN_COL_PX)))
        return [(k * n // c, max(k * n // c + 1, (k + 1) * n // c))
                for k in range(c)]

    def _x_of_bucket(self, k: float) -> float:
        left, pw = self._plot()
        n = max(1, int(self._d.get("n", 1)))
        return left + k / n * pw

    def _bucket_epoch(self, k: float) -> float:
        bs = float(self._d.get("bucket_s", 10))
        return self._started + (int(self._d.get("start_i", 0)) + k) * bs

    def _x_of_epoch(self, t: float) -> float:
        bs = float(self._d.get("bucket_s", 10))
        return self._x_of_bucket((t - self._bucket_epoch(0)) / bs)

    def _epoch_of_x(self, x: float) -> float:
        """The bucket edge nearest to x, as an epoch."""
        left, pw = self._plot()
        n = max(1, int(self._d.get("n", 1)))
        k = round(min(max(0.0, (x - left) / pw), 1.0) * n)
        return self._bucket_epoch(k)

    # paint --------------------------------------------------------------

    def paintEvent(self, _event) -> None:
        if not self._d.get("n"):
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        left, pw = self._plot()
        g = _Frame(left=left, right=left + pw, pw=pw, n=int(self._d["n"]),
                   bs=float(self._d.get("bucket_s", 10)), cols=self._columns(),
                   bottom=self.height() - self._AXIS_H)
        # under everything: the time grid, the hottest five minutes, the
        # tagged stretches; then the lanes top to bottom; then the
        # selection and the hover line on top
        self._paint_grid(p, g)
        self._paint_hottest(p, g)
        self._paint_tag_shading(p, g)
        y = float(self._TOP)
        y = self._paint_toys(p, g, y)
        y = self._paint_thrusts(p, g, y)
        y = self._paint_zones(p, g, y)
        self._paint_people(p, g, y)
        self._paint_selection(p, g)
        self._paint_hover(p, g)

    def _paint_grid(self, p: QPainter, g: "_Frame") -> None:
        """Time grid + axis labels."""
        dim, mid = chrome_color("dim"), _theme.tri("green")[1]
        span_s = g.n * g.bs
        px_per_s = g.pw / span_s if span_s else 1.0
        step = next((s for s in (60, 120, 300, 600, 900, 1800, 3600, 7200,
                                 10800, 21600) if s * px_per_s >= 72), 21600)
        t0 = self._bucket_epoch(0)
        offset = time.localtime(t0).tm_gmtoff
        first = math.ceil((t0 + offset) / step) * step - offset
        tick = first
        p.setFont(chart_font(11))
        half_label = p.fontMetrics().horizontalAdvance("00:00") / 2 + 1
        while tick <= t0 + span_s:
            x = g.left + (tick - t0) * px_per_s
            p.setPen(QPen(qcolor(mid, 0.55), 1))
            p.drawLine(QPointF(x, self._TOP - 4), QPointF(x, g.bottom))
            # Keep the label inside the widget at either end.
            lx = min(max(x, g.left + half_label), self.width() - half_label)
            draw_text(p, lx, g.bottom + 15, fmt_clock(tick), dim, "center")
            tick += step

    def _paint_hottest(self, p: QPainter, g: "_Frame") -> None:
        """The hottest five minutes, behind the lanes."""
        a = self._a
        if not a.get("hot_len_s"):
            return
        txt = chrome_color("txt")
        k0 = a["hot_at_s"] / g.bs - int(self._d.get("start_i", 0))
        x0 = self._x_of_bucket(k0)
        x1 = self._x_of_bucket(k0 + a["hot_len_s"] / g.bs)
        p.setPen(Qt.NoPen)
        p.setBrush(qcolor(txt, 0.07))
        p.drawRect(QRectF(x0, self._TOP - 4, max(3.0, x1 - x0),
                          g.bottom - self._TOP + 4))
        label = ("hottest 5 min" if a.get("hot_kind") == "thrusts"
                 else "most intense 5 min")
        p.setFont(chart_font(11))
        half = p.fontMetrics().horizontalAdvance(label) / 2
        cx = min(g.right - half, max(g.left + half, (x0 + x1) / 2))
        draw_text(p, cx, self._TOP - 8, label, txt, "center")

    def _paint_tag_shading(self, p: QPainter, g: "_Frame") -> None:
        """Tagged stretches, faintly, behind the lanes."""
        grey = _theme.hue("grey")
        for t0_, t1_, _label, _row in self._tags:
            x0 = max(g.left, self._x_of_epoch(t0_))
            x1 = min(g.right, self._x_of_epoch(t1_))
            if x1 > x0:
                p.setPen(Qt.NoPen)
                p.setBrush(qcolor(grey, 0.08))
                p.drawRect(QRectF(x0, self._TOP - 4, x1 - x0,
                                  g.bottom - self._TOP + 4))

    def _paint_toys(self, p: QPainter, g: "_Frame", y: float) -> float:
        """An intensity lane per toy."""
        txt, dim, mid = chrome_color("txt"), chrome_color("dim"), _theme.tri("green")[1]
        for idx, name in enumerate(self._toys):
            vals = self._d["toys"][name]
            color = toy_color(idx)
            base = y + self._TOY_H
            draw_text(p, 0, y + 15, name, txt, bold=True)
            draw_text(p, 0, y + 29, "intensity", dim)
            p.setPen(QPen(QColor(mid), 1))
            p.drawLine(QPointF(g.left, base), QPointF(g.right, base))
            pts = []
            for a_i, b_i in g.cols:
                v = sum(vals[a_i:b_i]) / (b_i - a_i)
                pts.append(QPointF(self._x_of_bucket((a_i + b_i) / 2),
                                   base - v * (self._TOY_H - 4)))
            if pts:
                area = QPainterPath(QPointF(pts[0].x(), base))
                for pt in pts:
                    area.lineTo(pt)
                area.lineTo(QPointF(pts[-1].x(), base))
                area.closeSubpath()
                p.fillPath(area, qcolor(color, 0.25))
                line = QPainterPath(pts[0])
                for pt in pts[1:]:
                    line.lineTo(pt)
                pen = QPen(QColor(color), 2)
                pen.setJoinStyle(Qt.RoundJoin)
                p.setPen(pen)
                p.setBrush(Qt.NoBrush)
                p.drawPath(line)
            y += self._TOY_H + self._TOY_GAP
        return y

    def _paint_thrusts(self, p: QPainter, g: "_Frame", y: float) -> float:
        """Thrusts per minute, a bar per column."""
        txt, dim, mid = chrome_color("txt"), chrome_color("dim"), _theme.tri("green")[1]
        thr = self._d.get("thrusts", [])
        base = y + self._THR_H
        rates = [sum(thr[a_i:b_i]) * 60.0 / ((b_i - a_i) * g.bs)
                 for a_i, b_i in g.cols]
        top_rate = max(rates, default=0.0)
        draw_text(p, 0, y + 15, "Thrusts", txt, bold=True)
        draw_text(p, 0, y + 29, f"up to {top_rate:.0f}/min" if top_rate
                  else "none", dim)
        p.setPen(QPen(QColor(mid), 1))
        p.drawLine(QPointF(g.left, base), QPointF(g.right, base))
        if top_rate > 0:
            pink = QColor(_theme.hue("pink"))
            p.setPen(Qt.NoPen)
            p.setBrush(pink)
            for (a_i, b_i), r in zip(g.cols, rates):
                if r <= 0:
                    continue
                x0, x1 = self._x_of_bucket(a_i), self._x_of_bucket(b_i)
                bh = max(2.0, r / top_rate * (self._THR_H - 4))
                w = max(1.0, x1 - x0 - 1.0)
                p.drawRoundedRect(QRectF(x0, base - bh, w, bh),
                                  min(2.0, w / 2), min(2.0, w / 2))
        return y + self._THR_H + self._THR_GAP

    def _paint_zones(self, p: QPainter, g: "_Frame", y: float) -> float:
        """A contact lane per zone."""
        if not self._zones:
            return y
        txt, muted = chrome_color("txt"), chrome_color("muted")
        draw_text(p, 0, y + 11, "Contact", txt, bold=True)
        y += self._CAPTION_H
        for key in self._zones:
            vals = self._d["zones"][key]
            lane = QRectF(g.left, y, g.pw, self._ZONE_H)
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(chrome_color("well")))
            p.drawRoundedRect(lane, 3, 3)
            p.setPen(QColor(muted))
            p.setFont(chart_font(11))
            label = p.fontMetrics().elidedText(
                zone_label(key), Qt.ElideRight, int(self._LABEL_W - 8))
            p.drawText(QPointF(0, y + 11), label)
            p.setPen(Qt.NoPen)
            p.setBrush(qcolor(zone_color(key), 0.9))
            for s, e in runs(vals):
                x0, x1 = self._x_of_bucket(s), self._x_of_bucket(e)
                p.drawRoundedRect(QRectF(x0, y, max(2.0, x1 - x0),
                                         self._ZONE_H), 3, 3)
            y += self._ZONE_H + self._ZONE_GAP
        return y

    def _paint_people(self, p: QPainter, g: "_Frame", y: float) -> None:
        """The people lane: one bar per tagged stretch, its names inside."""
        if not self._tag_rows:
            return
        txt, grey = chrome_color("txt"), _theme.hue("grey")
        draw_text(p, 0, y + 11, "People", txt, bold=True)
        y += self._CAPTION_H
        for row in range(self._tag_rows):
            lane = QRectF(g.left, y + row * (self._PEOPLE_H + self._PEOPLE_GAP),
                          g.pw, self._PEOPLE_H)
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(chrome_color("well")))
            p.drawRoundedRect(lane, 3, 3)
        p.setFont(chart_font(11))
        for t0_, t1_, label, row in self._tags:
            x0 = max(g.left, self._x_of_epoch(t0_))
            x1 = min(g.right, self._x_of_epoch(t1_))
            if x1 <= x0:
                continue
            ry = y + row * (self._PEOPLE_H + self._PEOPLE_GAP)
            bar = QRectF(x0, ry, max(3.0, x1 - x0), self._PEOPLE_H)
            p.setPen(QPen(QColor(_theme.tri("grey")[1]), 1))
            p.setBrush(qcolor(grey, 0.28))
            p.drawRoundedRect(bar, 3, 3)
            text = p.fontMetrics().elidedText(
                label, Qt.ElideRight, int(bar.width() - 8))
            if text and bar.width() > 14:
                p.setPen(QColor(txt))
                p.drawText(QPointF(bar.left() + 4, ry + 12), text)

    def _paint_selection(self, p: QPainter, g: "_Frame") -> None:
        """The selection being made (or waiting to be tagged)."""
        if self._sel is None:
            return
        accent = chrome_color("accent")
        x0 = max(g.left, self._x_of_epoch(self._sel[0]))
        x1 = min(g.right, self._x_of_epoch(self._sel[1]))
        if x1 > x0:
            p.setPen(Qt.NoPen)
            p.setBrush(qcolor(accent, 0.16))
            p.drawRect(QRectF(x0, self._TOP - 4, x1 - x0,
                              g.bottom - self._TOP + 4))
            p.setPen(QPen(QColor(accent), 1.5))
            p.drawLine(QPointF(x0, self._TOP - 4), QPointF(x0, g.bottom))
            p.drawLine(QPointF(x1, self._TOP - 4), QPointF(x1, g.bottom))

    def _paint_hover(self, p: QPainter, g: "_Frame") -> None:
        """The hover crosshair."""
        if self._hover_col is None or self._hover_col >= len(g.cols):
            return
        a_i, b_i = g.cols[self._hover_col]
        x = self._x_of_bucket((a_i + b_i) / 2)
        p.setPen(QPen(QColor(chrome_color("muted")), 1))
        p.drawLine(QPointF(x, self._TOP - 4), QPointF(x, g.bottom))

    # hover --------------------------------------------------------------

    def mousePressEvent(self, event) -> None:
        left, pw = self._plot()
        x = event.position().x()
        if (event.button() == Qt.LeftButton and self._d.get("n")
                and left <= x <= left + pw):
            self._drag_x0 = x
            self._sel = None
            self.update()
            return
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        x0 = self._drag_x0
        if x0 is None or event.button() != Qt.LeftButton:
            super().mouseReleaseEvent(event)
            return
        self._drag_x0 = None
        x1 = event.position().x()
        if abs(x1 - x0) < self._MIN_DRAG_PX:
            self.clear_selection()
            return
        t0, t1 = sorted((self._epoch_of_x(x0), self._epoch_of_x(x1)))
        if t1 <= t0:
            self.clear_selection()
            return
        self._sel = (t0, t1)
        self.update()
        QToolTip.hideText()
        self.stretchSelected.emit(t0, t1)

    def mouseMoveEvent(self, event) -> None:
        cols = self._columns()
        left, pw = self._plot()
        x = event.position().x()
        self.setCursor(Qt.CrossCursor if cols and left <= x <= left + pw
                       else Qt.ArrowCursor)
        if self._drag_x0 is not None:
            t0, t1 = sorted((self._epoch_of_x(self._drag_x0),
                             self._epoch_of_x(x)))
            self._sel = (t0, t1)
            self.update()
            QToolTip.showText(event.globalPosition().toPoint(),
                              f"{fmt_clock(t0)} to {fmt_clock(t1)}", self)
            return
        if not cols or x < left or x > left + pw:
            self._clear_hover()
            return
        n = int(self._d["n"])
        k = min(n - 1, max(0, int((x - left) / pw * n)))
        col = next((i for i, (a_i, b_i) in enumerate(cols) if a_i <= k < b_i), None)
        if col is None:
            self._clear_hover()
            return
        if col != self._hover_col:
            self._hover_col = col
            self.update()
        a_i, b_i = cols[col]
        bs = float(self._d.get("bucket_s", 10))
        lines = [f"<b>{fmt_clock(self._bucket_epoch(a_i))}</b>"]
        for idx, name in enumerate(self._toys):
            vals = self._d["toys"][name][a_i:b_i]
            lines.append(f"<span style='color:{toy_color(idx)}'>&#9632;</span> "
                         f"{name} {round(sum(vals) / len(vals) * 100)}%")
        rate = sum(self._d.get("thrusts", [])[a_i:b_i]) * 60.0 / ((b_i - a_i) * bs)
        lines.append(f"<span style='color:{_theme.hue('pink')}'>&#9632;</span> "
                     f"{rate:.0f} thrusts/min")
        touching = [zone_label(z) for z in self._zones
                    if any(v > 0 for v in self._d["zones"][z][a_i:b_i])]
        lines.append(", ".join(touching) if touching else "no contact")
        QToolTip.showText(event.globalPosition().toPoint(),
                          "<br>".join(lines), self)

    def _clear_hover(self) -> None:
        if self._hover_col is not None:
            self._hover_col = None
            self.update()
        QToolTip.hideText()

    def leaveEvent(self, _event) -> None:
        self._clear_hover()
