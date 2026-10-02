"""Custom-painted charts for the Statistics page.

Four widgets, all fed primitive data by `ui/views/statistics.py` (which
gets it from the controller's stats facade) and none of them reading
anything themselves:

* `Sparkline` — the small activity graph on each session row.
* `WeekHourChart` — active time by weekday x hour as a heatmap, with
  totals per hour underneath and per weekday on the right.
* `MonthCalendar` — one month, a cell per day shaded by active time.
* `SessionTimeline` — one session over clock time: an intensity lane per
  toy, thrusts per minute, a contact lane per zone, the hottest five
  minutes marked. Hover shows the values under the pointer.

Colours follow the 518 rules: active time is the green sequential ramp
(tint -> vibrant), thrusts and socket/plug contact are penetration pink,
touch contact is amber, and a session's toys take the cool toy hues in
the order they were used. Text stays in text tokens; colour marks carry
identity. Every value is also in a hover tooltip.
"""

import math
import time
from datetime import datetime
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QToolTip, QWidget

from ui import theme as _theme


WEEKDAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
WEEKDAYS_LONG = ("Mondays", "Tuesdays", "Wednesdays", "Thursdays",
                 "Fridays", "Saturdays", "Sundays")
ZONE_TYPE_LABELS = {"Orf": "socket", "Pen": "plug", "Touch": "touch"}


# ----------------------------------------------------------------------
# Formatting (shared with the view)
# ----------------------------------------------------------------------

def fmt_dur(seconds: Any) -> str:
    """Compact human duration: "58s", "12m 03s", "3h 24m", "1d 9h 02m".
    Past a day the minutes stay, so a growing total visibly moves."""
    try:
        s = max(0, int(round(float(seconds or 0))))
    except (TypeError, ValueError):
        s = 0
    if s < 60:
        return f"{s}s"
    m, s = divmod(s, 60)
    if m < 60:
        return f"{m}m {s:02d}s"
    h, m = divmod(m, 60)
    if h < 24:
        return f"{h}h {m:02d}m"
    d, h = divmod(h, 24)
    return f"{d}d {h}h {m:02d}m"


def fmt_short(seconds: Any) -> str:
    """Like fmt_dur but drops the seconds once there are minutes —
    for chart labels and tooltips, where "42m" reads faster."""
    try:
        s = max(0, int(round(float(seconds or 0))))
    except (TypeError, ValueError):
        s = 0
    if s < 60:
        return f"{s}s"
    m = s // 60
    if m < 60:
        return f"{m}m"
    h, m = divmod(m, 60)
    if h < 24:
        return f"{h}h {m:02d}m"
    d, h = divmod(h, 24)
    return f"{d}d {h}h {m:02d}m"


def fmt_clock(epoch: Any) -> str:
    try:
        return datetime.fromtimestamp(float(epoch)).strftime("%H:%M")
    except (TypeError, ValueError, OSError, OverflowError):
        return "--:--"


def fmt_day(epoch: Any) -> str:
    """"Wed 30 Sep"."""
    try:
        d = datetime.fromtimestamp(float(epoch))
    except (TypeError, ValueError, OSError, OverflowError):
        return "—"
    return f"{WEEKDAYS[d.weekday()]} {d.day} {d.strftime('%b')}"


def zone_label(key: str) -> str:
    """"Orf/Pussy" -> "Pussy (socket)"."""
    ztype, _, name = str(key).partition("/")
    if not name:
        return str(key)
    return f"{name} ({ZONE_TYPE_LABELS.get(ztype, ztype)})"


# ----------------------------------------------------------------------
# Colour helpers
# ----------------------------------------------------------------------

def _qc(hex_value: str, alpha: Optional[float] = None) -> QColor:
    c = QColor(hex_value)
    if alpha is not None:
        c.setAlphaF(max(0.0, min(1.0, alpha)))
    return c


def _blend(a: str, b: str, t: float) -> QColor:
    ca, cb = QColor(a), QColor(b)
    t = max(0.0, min(1.0, t))
    return QColor(
        round(ca.red() + (cb.red() - ca.red()) * t),
        round(ca.green() + (cb.green() - ca.green()) * t),
        round(ca.blue() + (cb.blue() - ca.blue()) * t),
    )


def _chrome(name: str) -> str:
    return _theme.CHROME[name]


def ramp(t: float) -> QColor:
    """Green sequential ramp for active time: nothing = the well, then
    the green tint stepping up to the vibrant green."""
    if t <= 0.0:
        return QColor(_chrome("well"))
    vib, _mid, tint = _theme.tri("green")
    return _blend(tint, vib, 0.22 + 0.78 * min(1.0, t))


def toy_color(index: int) -> str:
    return _theme.hue(_theme.toy_hue(index))


def zone_color(key: str) -> str:
    return _theme.hue("amber" if str(key).startswith("Touch/") else "pink")


def _font(px: int, bold: bool = False) -> QFont:
    f = QFont("Segoe UI")
    f.setPixelSize(px)
    f.setBold(bold)
    return f


def _text(p: QPainter, x: float, y: float, s: str, color: str,
          align: str = "left", px: int = 11, bold: bool = False) -> None:
    """Draw `s` with its baseline at y; align left / center / right on x."""
    p.setFont(_font(px, bold))
    p.setPen(QColor(color))
    w = p.fontMetrics().horizontalAdvance(s)
    if align == "center":
        x -= w / 2
    elif align == "right":
        x -= w
    p.drawText(QPointF(x, y), s)


# ----------------------------------------------------------------------
# Sparkline
# ----------------------------------------------------------------------

class Sparkline(QWidget):
    """Small filled activity graph (values 0..1). Mouse-transparent, so a
    click lands on the row it sits in."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._values: List[float] = []
        self.setFixedHeight(22)
        self.setMinimumWidth(60)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)

    def set_values(self, values: Optional[Sequence[float]]) -> None:
        v = [max(0.0, min(1.0, float(x))) for x in (values or [])]
        if v != self._values:
            self._values = v
            self.update()

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = float(self.width()), float(self.height())
        base = h - 1.0
        green = _theme.hue("green")
        vals = self._values
        if not vals:
            p.setPen(QPen(_qc(_theme.tri("green")[1]), 1))
            p.drawLine(QPointF(0, base), QPointF(w, base))
            return
        n = len(vals)
        pts = [QPointF((k + 0.5) / n * w, base - v * (h - 3.0))
               for k, v in enumerate(vals)]
        if n == 1:
            pts = [QPointF(0, pts[0].y()), QPointF(w, pts[0].y())]
        area = QPainterPath(QPointF(pts[0].x(), base))
        for pt in pts:
            area.lineTo(pt)
        area.lineTo(QPointF(pts[-1].x(), base))
        area.closeSubpath()
        p.fillPath(area, _qc(green, 0.32))
        line = QPainterPath(pts[0])
        for pt in pts[1:]:
            line.lineTo(pt)
        pen = QPen(QColor(green), 1.5)
        pen.setJoinStyle(Qt.RoundJoin)
        p.setPen(pen)
        p.drawPath(line)


# ----------------------------------------------------------------------
# Weekday x hour heatmap
# ----------------------------------------------------------------------

class WeekHourChart(QWidget):
    """Active time by weekday (rows, Monday first) and hour (columns),
    with per-hour totals below and per-weekday totals on the right."""

    _LEFT = 38
    _TOP = 4
    _ROW = 20           # row pitch; cells are 18 px tall
    _BARS_H = 40
    _RIGHT_W = 112      # weekday totals column (hidden when narrow)
    _HEIGHT = 7 * 20 + 4 + 12 + 40 + 18

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._active = [[0.0] * 24 for _ in range(7)]
        self._thrusts = [[0] * 24 for _ in range(7)]
        self._span = ""
        self.setFixedHeight(self._HEIGHT)
        self.setMinimumWidth(360)
        self.setMouseTracking(True)

    def set_data(self, active: Sequence[Sequence[float]],
                 thrusts: Sequence[Sequence[int]], span_label: str) -> None:
        a = [[float(v) for v in row] for row in active]
        t = [[int(v) for v in row] for row in thrusts]
        if a != self._active or t != self._thrusts or span_label != self._span:
            self._active, self._thrusts, self._span = a, t, span_label
            self.update()

    # geometry -----------------------------------------------------------

    def _layout(self) -> Tuple[float, float, float]:
        """(right column width, cell pitch, grid right edge)."""
        w = float(self.width())
        right = self._RIGHT_W if w >= 560 else 0.0
        grid_w = w - self._LEFT - right - (12 if right else 4)
        pitch = max(8.0, grid_w / 24.0)
        return right, pitch, self._LEFT + pitch * 24

    def _bars_base(self) -> float:
        return self._TOP + 7 * self._ROW + 12 + self._BARS_H

    # paint --------------------------------------------------------------

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        right, pitch, grid_r = self._layout()
        act = self._active
        cell_max = max(max(row) for row in act)
        rows = [sum(row) for row in act]
        cols = [sum(act[d][h] for d in range(7)) for h in range(24)]
        row_max, col_max = max(rows), max(cols)
        green = _theme.hue("green")
        muted, dim, txt = _chrome("muted"), _chrome("dim"), _chrome("txt")

        for d in range(7):
            y = self._TOP + d * self._ROW
            _text(p, self._LEFT - 6, y + 13, WEEKDAYS[d], muted, "right")
            for h in range(24):
                v = act[d][h]
                r = QRectF(self._LEFT + h * pitch, y, pitch - 2, self._ROW - 2)
                p.setPen(Qt.NoPen)
                p.setBrush(ramp(v / cell_max if cell_max else 0.0))
                p.drawRoundedRect(r, 3, 3)
            if right and row_max > 0:
                bw = max(2.0, rows[d] / row_max * (right - 46))
                p.setBrush(QColor(green))
                p.drawRoundedRect(QRectF(grid_r + 12, y + 3, bw, 12), 3, 3)
                if rows[d] == row_max:
                    _text(p, grid_r + 12 + bw + 5, y + 13,
                          fmt_short(rows[d]), txt)
        if right:
            _text(p, grid_r + 12, self._TOP + 7 * self._ROW + 12,
                  "by weekday", dim)

        base = self._bars_base()
        if col_max > 0:
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(green))
            for h in range(24):
                if cols[h] <= 0:
                    continue
                bh = max(2.0, cols[h] / col_max * self._BARS_H)
                p.drawRoundedRect(QRectF(self._LEFT + h * pitch + pitch * 0.2,
                                         base - bh, pitch * 0.6 - 2, bh), 2, 2)
            peak = cols.index(col_max)
            _text(p, self._LEFT + peak * pitch + (pitch - 2) / 2,
                  base - self._BARS_H - 3, "peak", txt, "center")
        for h in (0, 6, 12, 18, 23):
            _text(p, self._LEFT + h * pitch + (pitch - 2) / 2, base + 14,
                  f"{h:02d}", dim, "center")
        _text(p, self._LEFT - 6, base - 2, "hour", dim, "right")

        if cell_max <= 0:
            msg = "Nothing recorded here yet. This fills in as you play."
            p.setFont(_font(12))
            fm = p.fontMetrics()
            tw = fm.horizontalAdvance(msg) + 20
            cx = (self._LEFT + grid_r) / 2
            cy = self._TOP + 3.5 * self._ROW
            box = QRectF(cx - tw / 2, cy - 14, tw, 26)
            p.setPen(QPen(QColor(_theme.tri("green")[1]), 1))
            p.setBrush(QColor(_chrome("card")))
            p.drawRoundedRect(box, 8, 8)
            p.setPen(QColor(muted))
            p.drawText(box, Qt.AlignCenter, msg)

    # hover --------------------------------------------------------------

    def _hit(self, x: float, y: float) -> Optional[str]:
        right, pitch, grid_r = self._layout()
        act, thr = self._active, self._thrusts
        span = f" {self._span}" if self._span else ""
        if self._LEFT <= x < grid_r:
            h = int((x - self._LEFT) // pitch)
            d = int((y - self._TOP) // self._ROW)
            if 0 <= d < 7 and 0 <= h < 24 and y >= self._TOP:
                return (f"<b>{WEEKDAYS[d]} {h:02d}:00–{(h + 1) % 24:02d}:00</b>"
                        f"{span}<br>{fmt_short(act[d][h])} active · "
                        f"{thr[d][h]:,} thrusts")
            base = self._bars_base()
            if 0 <= h < 24 and base - self._BARS_H - 14 <= y <= base + 16:
                a = sum(act[dd][h] for dd in range(7))
                t = sum(thr[dd][h] for dd in range(7))
                return (f"<b>{h:02d}:00–{(h + 1) % 24:02d}:00, every day</b>"
                        f"{span}<br>{fmt_short(a)} active · {t:,} thrusts")
        if right and x >= grid_r + 8:
            d = int((y - self._TOP) // self._ROW)
            if 0 <= d < 7 and y >= self._TOP:
                return (f"<b>{WEEKDAYS_LONG[d]}</b>{span}<br>"
                        f"{fmt_short(sum(act[d]))} active · "
                        f"{sum(thr[d]):,} thrusts")
        return None

    def mouseMoveEvent(self, event) -> None:
        pos = event.position()
        tip = self._hit(pos.x(), pos.y())
        if tip:
            QToolTip.showText(event.globalPosition().toPoint(), tip, self)
        else:
            QToolTip.hideText()

    def leaveEvent(self, _event) -> None:
        QToolTip.hideText()


# ----------------------------------------------------------------------
# Month calendar
# ----------------------------------------------------------------------

class MonthCalendar(QWidget):
    """A month as a Monday-first grid, each day shaded by active time.
    Today gets an accent outline."""

    _CW, _CH, _GAP, _HEAD = 38, 30, 4, 18

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._year, self._month = 2000, 1
        self._days: Dict[int, Dict[str, Any]] = {}
        self._today: Optional[Tuple[int, int, int]] = None
        self._estimated_until = 0.0
        self.setFixedSize(7 * (self._CW + self._GAP) - self._GAP,
                          self._HEAD + 6 * (self._CH + self._GAP) - self._GAP)
        self.setMouseTracking(True)

    def set_month(self, year: int, month: int,
                  days: Mapping[int, Mapping[str, Any]],
                  today: Optional[Tuple[int, int, int]] = None,
                  estimated_until: float = 0.0) -> None:
        """`estimated_until` — days before it were estimated rather than
        measured; their tooltips say so."""
        clean = {int(d): dict(v) for d, v in days.items()}
        state = (int(year), int(month), clean, today, float(estimated_until))
        if state != (self._year, self._month, self._days, self._today,
                     self._estimated_until):
            (self._year, self._month, self._days, self._today,
             self._estimated_until) = state
            self.update()

    def _first_weekday(self) -> int:
        return datetime(self._year, self._month, 1).weekday()

    def _ndays(self) -> int:
        y, m = (self._year + 1, 1) if self._month == 12 else (self._year, self._month + 1)
        return (datetime(y, m, 1) - datetime(self._year, self._month, 1)).days

    def _cell(self, day: int) -> QRectF:
        i = self._first_weekday() + day - 1
        return QRectF((i % 7) * (self._CW + self._GAP),
                      self._HEAD + (i // 7) * (self._CH + self._GAP),
                      self._CW, self._CH)

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        dim, muted = _chrome("dim"), _chrome("muted")
        for i, name in enumerate(("Mo", "Tu", "We", "Th", "Fr", "Sa", "Su")):
            _text(p, i * (self._CW + self._GAP) + self._CW / 2, 12,
                  name, dim, "center")
        top = max((v.get("active_s", 0.0) for v in self._days.values()),
                  default=0.0)
        for day in range(1, self._ndays() + 1):
            r = self._cell(day)
            v = self._days.get(day, {}).get("active_s", 0.0)
            t = v / top if top else 0.0
            p.setPen(Qt.NoPen)
            p.setBrush(ramp(t if v > 0 else 0.0))
            p.drawRoundedRect(r, 5, 5)
            is_today = self._today == (self._year, self._month, day)
            if is_today:
                p.setPen(QPen(QColor(_chrome("accent")), 1.5))
                p.setBrush(Qt.NoBrush)
                p.drawRoundedRect(r.adjusted(0.75, 0.75, -0.75, -0.75), 5, 5)
            color = _chrome("ink") if t > 0.6 else (
                _chrome("txt") if is_today else muted)
            _text(p, r.x() + 5, r.y() + 13, str(day), color, bold=is_today)

    def mouseMoveEvent(self, event) -> None:
        pos = event.position()
        for day in range(1, self._ndays() + 1):
            if self._cell(day).contains(pos):
                e = self._days.get(day, {})
                when = datetime(self._year, self._month, day)
                head = f"{WEEKDAYS[when.weekday()]} {day} {when.strftime('%b')}"
                if e.get("active_s", 0.0) > 0 or e.get("sessions", 0):
                    n = int(e.get("sessions", 0))
                    body = (f"{fmt_short(e.get('active_s', 0.0))} active · "
                            f"{int(e.get('thrusts', 0)):,} thrusts"
                            + (f" · {n} session{'s' if n != 1 else ''}"
                               if n else ""))
                else:
                    body = "nothing"
                if self._estimated_until and e.get("active_s", 0.0) > 0:
                    cut = datetime.fromtimestamp(self._estimated_until).date()
                    if when.date() < cut:
                        body += "<br><i>estimated</i>"
                    elif when.date() == cut:
                        body += "<br><i>partly estimated</i>"
                QToolTip.showText(event.globalPosition().toPoint(),
                                  f"<b>{head}</b><br>{body}", self)
                return
        QToolTip.hideText()

    def leaveEvent(self, _event) -> None:
        QToolTip.hideText()


# ----------------------------------------------------------------------
# One session over time
# ----------------------------------------------------------------------

class SessionTimeline(QWidget):
    """A session's timeline: intensity lane per toy, thrusts per minute,
    contact lane per zone, on one clock-time axis. Hover shows a
    crosshair and the values in that slice."""

    _LABEL_W = 116
    _TOP = 20
    _TOY_H, _TOY_GAP = 36, 8
    _THR_H, _THR_GAP = 44, 12
    _CAPTION_H = 16
    _ZONE_H, _ZONE_GAP = 14, 6
    _AXIS_H = 20
    _MIN_COL_PX = 3.0

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._d: Dict[str, Any] = {}
        self._a: Dict[str, Any] = {}
        self._toys: List[str] = []
        self._zones: List[str] = []
        self._started = 0.0
        self._hover_col: Optional[int] = None
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
        h = (self._TOP
             + len(self._toys) * (self._TOY_H + self._TOY_GAP)
             + self._THR_H + self._THR_GAP
             + (self._CAPTION_H + len(self._zones) * (self._ZONE_H + self._ZONE_GAP)
                if self._zones else 0)
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

    # paint --------------------------------------------------------------

    def paintEvent(self, _event) -> None:
        if not self._d.get("n"):
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        left, pw = self._plot()
        right = left + pw
        n = int(self._d["n"])
        bs = float(self._d.get("bucket_s", 10))
        cols = self._columns()
        txt, muted, dim = _chrome("txt"), _chrome("muted"), _chrome("dim")
        mid = _theme.tri("green")[1]
        bottom = self.height() - self._AXIS_H

        # Time grid + axis, under everything.
        span_s = n * bs
        px_per_s = pw / span_s if span_s else 1.0
        step = next((s for s in (60, 120, 300, 600, 900, 1800, 3600, 7200,
                                 10800, 21600) if s * px_per_s >= 72), 21600)
        t0 = self._bucket_epoch(0)
        offset = time.localtime(t0).tm_gmtoff
        first = math.ceil((t0 + offset) / step) * step - offset
        tick = first
        p.setFont(_font(11))
        half_label = p.fontMetrics().horizontalAdvance("00:00") / 2 + 1
        while tick <= t0 + span_s:
            x = left + (tick - t0) * px_per_s
            p.setPen(QPen(_qc(mid, 0.55), 1))
            p.drawLine(QPointF(x, self._TOP - 4), QPointF(x, bottom))
            # Keep the label inside the widget at either end.
            lx = min(max(x, left + half_label), self.width() - half_label)
            _text(p, lx, bottom + 15, fmt_clock(tick), dim, "center")
            tick += step

        # The hottest five minutes, behind the lanes.
        a = self._a
        if a.get("hot_len_s"):
            k0 = a["hot_at_s"] / bs - int(self._d.get("start_i", 0))
            x0 = self._x_of_bucket(k0)
            x1 = self._x_of_bucket(k0 + a["hot_len_s"] / bs)
            p.setPen(Qt.NoPen)
            p.setBrush(_qc(txt, 0.07))
            p.drawRect(QRectF(x0, self._TOP - 4, max(3.0, x1 - x0),
                              bottom - self._TOP + 4))
            label = ("hottest 5 min" if a.get("hot_kind") == "thrusts"
                     else "most intense 5 min")
            p.setFont(_font(11))
            half = p.fontMetrics().horizontalAdvance(label) / 2
            cx = min(right - half, max(left + half, (x0 + x1) / 2))
            _text(p, cx, self._TOP - 8, label, txt, "center")

        y = float(self._TOP)
        # Toy intensity lanes.
        for idx, name in enumerate(self._toys):
            vals = self._d["toys"][name]
            color = toy_color(idx)
            base = y + self._TOY_H
            _text(p, 0, y + 15, name, txt, bold=True)
            _text(p, 0, y + 29, "intensity", dim)
            p.setPen(QPen(QColor(mid), 1))
            p.drawLine(QPointF(left, base), QPointF(right, base))
            pts = []
            for a_i, b_i in cols:
                v = sum(vals[a_i:b_i]) / (b_i - a_i)
                pts.append(QPointF(self._x_of_bucket((a_i + b_i) / 2),
                                   base - v * (self._TOY_H - 4)))
            if pts:
                area = QPainterPath(QPointF(pts[0].x(), base))
                for pt in pts:
                    area.lineTo(pt)
                area.lineTo(QPointF(pts[-1].x(), base))
                area.closeSubpath()
                p.fillPath(area, _qc(color, 0.25))
                line = QPainterPath(pts[0])
                for pt in pts[1:]:
                    line.lineTo(pt)
                pen = QPen(QColor(color), 2)
                pen.setJoinStyle(Qt.RoundJoin)
                p.setPen(pen)
                p.setBrush(Qt.NoBrush)
                p.drawPath(line)
            y += self._TOY_H + self._TOY_GAP

        # Thrusts per minute.
        thr = self._d.get("thrusts", [])
        base = y + self._THR_H
        rates = [sum(thr[a_i:b_i]) * 60.0 / ((b_i - a_i) * bs)
                 for a_i, b_i in cols]
        top_rate = max(rates, default=0.0)
        _text(p, 0, y + 15, "Thrusts", txt, bold=True)
        _text(p, 0, y + 29, f"up to {top_rate:.0f}/min" if top_rate
              else "none", dim)
        p.setPen(QPen(QColor(mid), 1))
        p.drawLine(QPointF(left, base), QPointF(right, base))
        if top_rate > 0:
            pink = QColor(_theme.hue("pink"))
            p.setPen(Qt.NoPen)
            p.setBrush(pink)
            for (a_i, b_i), r in zip(cols, rates):
                if r <= 0:
                    continue
                x0, x1 = self._x_of_bucket(a_i), self._x_of_bucket(b_i)
                bh = max(2.0, r / top_rate * (self._THR_H - 4))
                w = max(1.0, x1 - x0 - 1.0)
                p.drawRoundedRect(QRectF(x0, base - bh, w, bh),
                                  min(2.0, w / 2), min(2.0, w / 2))
        y += self._THR_H + self._THR_GAP

        # Contact lanes.
        if self._zones:
            _text(p, 0, y + 11, "Contact", txt, bold=True)
            y += self._CAPTION_H
            for key in self._zones:
                vals = self._d["zones"][key]
                lane = QRectF(left, y, pw, self._ZONE_H)
                p.setPen(Qt.NoPen)
                p.setBrush(QColor(_chrome("well")))
                p.drawRoundedRect(lane, 3, 3)
                p.setPen(QColor(muted))
                p.setFont(_font(11))
                label = p.fontMetrics().elidedText(
                    zone_label(key), Qt.ElideRight, int(self._LABEL_W - 8))
                p.drawText(QPointF(0, y + 11), label)
                p.setPen(Qt.NoPen)
                p.setBrush(_qc(zone_color(key), 0.9))
                for s, e in _runs(vals):
                    x0, x1 = self._x_of_bucket(s), self._x_of_bucket(e)
                    p.drawRoundedRect(QRectF(x0, y, max(2.0, x1 - x0),
                                             self._ZONE_H), 3, 3)
                y += self._ZONE_H + self._ZONE_GAP

        # Hover crosshair.
        if self._hover_col is not None and self._hover_col < len(cols):
            a_i, b_i = cols[self._hover_col]
            x = self._x_of_bucket((a_i + b_i) / 2)
            p.setPen(QPen(QColor(muted), 1))
            p.drawLine(QPointF(x, self._TOP - 4), QPointF(x, bottom))

    # hover --------------------------------------------------------------

    def mouseMoveEvent(self, event) -> None:
        cols = self._columns()
        left, pw = self._plot()
        x = event.position().x()
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


def _runs(values: Sequence[float], gap: int = 1) -> List[Tuple[int, int]]:
    """[start, end) bucket runs where values > 0, bridging gaps of up to
    `gap` empty buckets so a flickering contact reads as one span."""
    runs: List[Tuple[int, int]] = []
    start = last = None
    for k, v in enumerate(values):
        if v <= 0:
            continue
        if start is None:
            start = last = k
        elif k - last - 1 > gap:
            runs.append((start, last + 1))
            start = k
        last = k
    if start is not None:
        runs.append((start, last + 1))
    return runs


# ----------------------------------------------------------------------
# Toy-connected stretches (sessions from before the timelines)
# ----------------------------------------------------------------------

def _merge_fractions(toys: Mapping[str, Sequence[Sequence[float]]],
                     start: float, length: float) -> List[Tuple[float, float]]:
    """All toys' connected spans as merged 0..1 fractions of the window."""
    if length <= 0:
        return []
    fr = sorted((max(0.0, (a - start) / length), min(1.0, (b - start) / length))
                for spans in toys.values() for a, b in spans)
    out: List[Tuple[float, float]] = []
    for a, b in fr:
        if b <= a:
            continue
        if out and a <= out[-1][1]:
            out[-1] = (out[-1][0], max(out[-1][1], b))
        else:
            out.append((a, b))
    return out


class SpanStrip(QWidget):
    """Where the activity graph would be, for a session recorded before
    timelines: thin bars for when any toy was connected (from the app's
    log). Drawn in the green mid tone so it never reads as measured
    activity. Mouse-transparent like the Sparkline."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._fr: List[Tuple[float, float]] = []
        self.setFixedHeight(22)
        self.setMinimumWidth(60)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)

    def set_spans(self, toys: Optional[Mapping[str, Sequence[Sequence[float]]]],
                  start: float, length: float) -> None:
        fr = _merge_fractions(toys or {}, float(start), float(length))
        if fr != self._fr:
            self._fr = fr
            self.update()

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = float(self.width()), float(self.height())
        mid = _theme.tri("green")[1]
        y = h / 2
        p.setPen(QPen(_qc(mid, 0.6), 1))
        p.drawLine(QPointF(0, y), QPointF(w, y))
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(mid))
        for a, b in self._fr:
            p.drawRoundedRect(QRectF(a * w, y - 4, max(2.0, (b - a) * w), 8), 3, 3)


class SpanTimeline(QWidget):
    """A pre-timeline session's page chart: one lane per toy with the
    stretches it was connected, on a clock-time axis. Hover names the
    stretch."""

    _LABEL_W = 116
    _TOP = 6
    _LANE_H, _LANE_GAP = 16, 8
    _AXIS_H = 20

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._toys: List[Tuple[str, List[Tuple[float, float]]]] = []
        self._start = 0.0
        self._length = 1.0
        self.setMinimumWidth(420)
        self.setMouseTracking(True)
        self.setFixedHeight(self._TOP + self._AXIS_H)

    def set_spans(self, toys: Optional[Mapping[str, Sequence[Sequence[float]]]],
                  start: float, length: float) -> None:
        toys = toys or {}
        order = sorted(toys, key=lambda n: (-sum(b - a for a, b in toys[n]), n.lower()))
        self._toys = [(n, [(float(a), float(b)) for a, b in toys[n]]) for n in order]
        self._start, self._length = float(start), max(1.0, float(length))
        self.setFixedHeight(self._TOP + len(self._toys) * (self._LANE_H + self._LANE_GAP)
                            + self._AXIS_H)
        self.update()

    def toy_order(self) -> List[str]:
        return [n for n, _ in self._toys]

    def _x(self, t: float) -> float:
        left = float(self._LABEL_W)
        pw = max(10.0, self.width() - left - 6.0)
        return left + (t - self._start) / self._length * pw

    def paintEvent(self, _event) -> None:
        if not self._toys:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        left = float(self._LABEL_W)
        right = self.width() - 6.0
        dim = _chrome("dim")
        mid = _theme.tri("green")[1]
        bottom = self.height() - self._AXIS_H
        pw = right - left
        step = next((s for s in (300, 600, 900, 1800, 3600, 7200, 10800, 21600)
                     if s * pw / self._length >= 72), 21600)
        offset = time.localtime(self._start).tm_gmtoff
        tick = math.ceil((self._start + offset) / step) * step - offset
        p.setFont(_font(11))
        half = p.fontMetrics().horizontalAdvance("00:00") / 2 + 1
        while tick <= self._start + self._length:
            x = self._x(tick)
            p.setPen(QPen(_qc(mid, 0.55), 1))
            p.drawLine(QPointF(x, self._TOP), QPointF(x, bottom))
            _text(p, min(max(x, left + half), self.width() - half), bottom + 15,
                  fmt_clock(tick), dim, "center")
            tick += step
        y = float(self._TOP)
        for idx, (name, spans) in enumerate(self._toys):
            p.setPen(QColor(_chrome("txt")))
            p.setFont(_font(11))
            label = p.fontMetrics().elidedText(name, Qt.ElideRight,
                                               int(self._LABEL_W - 8))
            p.drawText(QPointF(0, y + 12), label)
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(_chrome("well")))
            p.drawRoundedRect(QRectF(left, y, pw, self._LANE_H), 3, 3)
            p.setBrush(_qc(toy_color(idx), 0.55))
            for a, b in spans:
                x0, x1 = self._x(a), self._x(b)
                p.drawRoundedRect(QRectF(x0, y, max(2.0, x1 - x0), self._LANE_H), 3, 3)
            y += self._LANE_H + self._LANE_GAP

    def mouseMoveEvent(self, event) -> None:
        pos = event.position()
        lane = int((pos.y() - self._TOP) // (self._LANE_H + self._LANE_GAP))
        if 0 <= lane < len(self._toys):
            name, spans = self._toys[lane]
            for a, b in spans:
                if self._x(a) - 2 <= pos.x() <= self._x(b) + 2:
                    QToolTip.showText(
                        event.globalPosition().toPoint(),
                        f"<b>{name}</b><br>connected {fmt_clock(a)} to "
                        f"{fmt_clock(b)} ({fmt_short(b - a)})", self)
                    return
        QToolTip.hideText()

    def leaveEvent(self, _event) -> None:
        QToolTip.hideText()
