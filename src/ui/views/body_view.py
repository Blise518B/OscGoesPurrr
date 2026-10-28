"""The Suits page's body: a cat girl's front and back (OGP purrs), every
bHaptics motor a dot on her where the avatar's contact sits, OWO's ten
muscles as patches around the dots that play them, and -- once tracker
haptics are in -- a puck where each Vive tracker sits. bHaptics wears the
suits' orange, OWO purple, trackers blue (theme.BHAPTICS_HUE / OWO_HUE /
TRACKERS_HUE).

A dot fills as it's touched, a patch as its muscle plays, a puck as its
tracker buzzes; something switched off is drawn dim, and a bHaptics part
you don't have (the page's You have) isn't drawn at all. A dot, patch or
puck your avatar has no contact for gets a dashed amber ring (the page's
contact check).

Click a dot to pick its part and the muscle around it, a patch for just the
muscle, a puck for its tracker -- the page opens their cards beside her,
each with a line from here (anchor) -- and empty space to close them. A
held dot is felt: a gentle test through the router until let go.

Her pictures (src/Images/suits, made by tools/make_suit_figure.py) are line
art alone, tinted at paint time in the accent, so she follows the colour
picker like the chrome does. Every dot is placed in the drawing's own
pixels (1024 x 1536); FIG_BOX is the part of it that's shown.

Painted, not built from widgets: one cheap repaint per live tick.
"""

import math
import os
from typing import Callable, Dict, FrozenSet, Iterable, Optional, Sequence, Tuple

from PySide6.QtCore import QPointF, QRectF, QSize, Qt
from PySide6.QtGui import (
    QColor, QFont, QImage, QPainter, QPainterPath, QPainterPathStroker, QPen, QPixmap,
    QTransform,
)
from PySide6.QtWidgets import QSizePolicy, QWidget

import body_map
from ui import theme as _theme

FRONT, BACK = 0, 1
FIG_BOX = QRectF(255, 20, 535, 1480)     # what's shown of the 1024 x 1536 drawing
DOT_R = 10.0                             # a dot's radius, in the drawing's pixels ...
DOT_MIN_PX = 4.5                         # ... never smaller than this on screen
PUCK_R = 15.0                            # a tracker's puck, the same way
ZONE_PAD = 7.0                           # how far a patch reaches past its dots
HEIGHT = 700
CAPTION_H = 24
VIEW_GAP = 28
FIGURE_ALPHA = 0.5                       # her lines, quieter than the dots
CAPTION_PX = 11

Point = Tuple[float, float]


# ---- where everything sits on her (the drawing's pixels) ---------------------

def _grid(origin: Point, angle: float, step_c: float, step_r: float,
          cols: int, rows: int) -> Tuple[Point, ...]:
    """A cols x rows grid, row-major (body_map's order): c across, r along
    -- down her body, or down a limb turned by `angle` degrees."""
    a = math.radians(angle)
    ux, uy = math.cos(a), math.sin(a)
    vx, vy = -math.sin(a), math.cos(a)
    ox, oy = origin
    return tuple((ox + c * step_c * ux + r * step_r * vx, oy + c * step_c * uy + r * step_r * vy)
                 for r in range(rows) for c in range(cols))


def _along(start: Point, angle: float, steps: Iterable[float]) -> Tuple[Point, ...]:
    a = math.radians(angle)
    return tuple((start[0] - d * math.sin(a), start[1] + d * math.cos(a)) for d in steps)


def _mirror(points: Sequence[Point]) -> Tuple[Point, ...]:
    return tuple((1024.0 - x, y) for x, y in points)


# Her right forearm's arm warmer, elbow band to wrist band (on the left as
# she faces us); the left one is its mirror image.
_ELBOW, _WRIST = (356.0, 590.0), (316.0, 738.0)
_ARM_ANGLE = math.degrees(math.atan2(_ELBOW[0] - _WRIST[0], _WRIST[1] - _ELBOW[1]))


def _places() -> Dict[str, Tuple[int, float, Tuple[Point, ...]]]:
    """position -> (view, the angle its grid is turned by, dot centres)."""
    a = _ARM_ANGLE
    arm_step = 41.0
    first = _along(_ELBOW, a, (0.15 * math.hypot(_WRIST[0] - _ELBOW[0], _WRIST[1] - _ELBOW[1]),))[0]
    across = 21.0
    arm = _grid((first[0] - across / 2 * math.cos(math.radians(a)),
                 first[1] - across / 2 * math.sin(math.radians(a))), a, across, arm_step, 2, 3)
    hand = _along(_WRIST, a, (26.0, 50.0, 74.0))
    foot = ((446.0, 1433.0), (465.0, 1428.0), (484.0, 1433.0))
    head = tuple((516.0 + k, 150.0 + 6.0 * (k / 62.5) ** 2)
                 for k in (-62.5, -37.5, -12.5, 12.5, 37.5, 62.5))
    return {
        "Head": (FRONT, 0.0, head),
        # each vest panel as seen from outside it (body_map): her right is
        # on our left on the front, her left on the back
        "VestFront": (FRONT, 0.0, _grid((452.0, 372.0), 0.0, 40.0, 63.0, 4, 5)),
        "VestBack": (BACK, 0.0, _grid((452.0, 368.0), 0.0, 40.0, 63.0, 4, 5)),
        "ForearmR": (FRONT, a, arm),
        "ForearmL": (FRONT, -a, _mirror(arm)),
        "HandR": (FRONT, a, hand),
        "HandL": (FRONT, -a, _mirror(hand)),
        "FootR": (FRONT, 0.0, foot),
        "FootL": (FRONT, 0.0, _mirror(foot)),
    }


PLACES = _places()
_SIDE_MARKS = ((268.0, 440.0), (756.0, 440.0))     # where the R / L letters go

# Where a Vive tracker can sit, for tracker haptics -- their backend lives on
# main and isn't in this build yet, so the page shows these only when the
# controller reports trackers. (key, name, centre on her front)
TRACKERS: Tuple[Tuple[str, str, Point], ...] = (
    ("chest", "Chest", (512.0, 341.0)),
    ("hip", "Hip", (512.0, 745.0)),
    ("upper_arm_r", "Right upper arm", (365.0, 470.0)),
    ("upper_arm_l", "Left upper arm", (659.0, 470.0)),
    ("upper_leg_r", "Right upper leg", (455.0, 960.0)),
    ("upper_leg_l", "Left upper leg", (569.0, 960.0)),
    ("ankle_r", "Right ankle", (468.0, 1345.0)),
    ("ankle_l", "Left ankle", (556.0, 1345.0)),
)
TRACKER_NAMES: Dict[str, str] = {key: name for key, name, _xy in TRACKERS}
_TRACKER_AT: Dict[str, Point] = {key: xy for key, _name, xy in TRACKERS}

_MUSCLE_OF: Dict[Tuple[str, int], str] = {
    (position, i): muscle
    for muscle, (position, cells) in body_map.OWO_REGIONS.items() for i in cells}


def muscle_at(position: str, index: int) -> Optional[str]:
    """The OWO muscle whose patch a bHaptics dot is in (None: no muscle
    there -- OWO has none on the head, hands or feet)."""
    return _MUSCLE_OF.get((position, index))


def _blend(a: str, b: str, t: float) -> QColor:
    ca, cb = QColor(a), QColor(b)
    t = max(0.0, min(1.0, t))
    return QColor(round(ca.red() + (cb.red() - ca.red()) * t),
                  round(ca.green() + (cb.green() - ca.green()) * t),
                  round(ca.blue() + (cb.blue() - ca.blue()) * t))


def _outset(path: QPainterPath, by: float) -> QPainterPath:
    """`path` grown outward by `by` px (for a ring drawn around it)."""
    stroker = QPainterPathStroker()
    stroker.setWidth(2 * by)
    return (stroker.createStroke(path) + path).simplified()


def _figure_path(view: int) -> str:
    return os.path.join(_theme.asset_dir(), "suits", ("front.png", "back.png")[view])


class BodyView(QWidget):
    """Her front and back side by side, the dots, patches and pucks on them."""

    def __init__(self, on_hold: Optional[Callable[[str, int, bool], None]] = None,
                 on_pick: Optional[Callable[[Optional[str], Optional[str], Optional[str]],
                                            None]] = None,
                 parent=None):
        super().__init__(parent)
        self._on_hold = on_hold
        self._on_pick = on_pick
        self._frame: Dict[str, Sequence[float]] = {}
        self._owo: Dict[str, float] = {}
        self._trackers: Dict[str, float] = {}
        self._held: Optional[Tuple[str, int]] = None
        self._part: Optional[str] = None
        self._muscle: Optional[str] = None
        self._tracker: Optional[str] = None
        self._parts_off: FrozenSet[str] = frozenset()
        self._parts_shown: FrozenSet[str] = frozenset(PLACES)
        self._muscles_off: FrozenSet[str] = frozenset()
        self._trackers_shown: FrozenSet[str] = frozenset()
        self._trackers_off: FrozenSet[str] = frozenset()
        self._missing_dots: Dict[str, FrozenSet[int]] = {}
        self._missing_muscles: FrozenSet[str] = frozenset()
        self._missing_trackers: FrozenSet[str] = frozenset()
        self._show_bh = True
        self._show_owo = True
        self._figures = [QImage(_figure_path(v)) for v in (FRONT, BACK)]
        self._tinted: Dict[int, Tuple[tuple, QPixmap]] = {}
        self.setCursor(Qt.PointingHandCursor)
        policy = QSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        policy.setHeightForWidth(True)
        self.setSizePolicy(policy)
        self.setMinimumWidth(340)

    def hasHeightForWidth(self) -> bool:  # noqa: N802
        return True

    def heightForWidth(self, width: int) -> int:  # noqa: N802
        """HEIGHT, or less once she's narrowed by the width (no empty band
        under her in a half-screen window)."""
        by_w = (width - VIEW_GAP) / 2 / FIG_BOX.width()
        return int(min(HEIGHT, CAPTION_H + FIG_BOX.height() * by_w + 2))

    def sizeHint(self) -> QSize:  # noqa: N802
        return QSize(640, HEIGHT)

    def minimumSizeHint(self) -> QSize:  # noqa: N802
        return QSize(340, self.heightForWidth(340))

    # ---- data ----------------------------------------------------------
    def set_live(self, frame: Dict[str, Sequence[float]], owo: Dict[str, float],
                 trackers: Optional[Dict[str, float]] = None) -> None:
        trackers = dict(trackers or {})
        if frame == self._frame and owo == self._owo and trackers == self._trackers:
            return
        self._frame = dict(frame or {})
        self._owo = dict(owo or {})
        self._trackers = trackers
        self.update()

    def set_state(self, show_bhaptics: bool, show_owo: bool,
                  parts_off: Iterable[str] = (), muscles_off: Iterable[str] = (),
                  parts_shown: Optional[Iterable[str]] = None,
                  trackers_shown: Iterable[str] = (), trackers_off: Iterable[str] = ()) -> None:
        """Which suits are on (Settings -> Features), the bHaptics parts
        you have (the page's You have; None = all), the trackers there are,
        and what is switched off on the page."""
        shown = frozenset(PLACES if parts_shown is None else parts_shown)
        state = (bool(show_bhaptics), bool(show_owo), frozenset(parts_off),
                 frozenset(muscles_off), shown, frozenset(trackers_shown),
                 frozenset(trackers_off))
        if state == (self._show_bh, self._show_owo, self._parts_off, self._muscles_off,
                     self._parts_shown, self._trackers_shown, self._trackers_off):
            return
        (self._show_bh, self._show_owo, self._parts_off, self._muscles_off,
         self._parts_shown, self._trackers_shown, self._trackers_off) = state
        self.update()

    def set_missing(self, dots: Optional[Dict[str, Iterable[int]]] = None,
                    muscles: Iterable[str] = (), trackers: Iterable[str] = ()) -> None:
        """What the contact check found missing on the avatar: dot indices
        per position, muscles, trackers (nothing = all there, or unknown)."""
        state = ({pos: frozenset(i) for pos, i in (dots or {}).items() if i},
                 frozenset(muscles), frozenset(trackers))
        if state == (self._missing_dots, self._missing_muscles, self._missing_trackers):
            return
        self._missing_dots, self._missing_muscles, self._missing_trackers = state
        self.update()

    def select(self, part: Optional[str], muscle: Optional[str],
               tracker: Optional[str] = None) -> None:
        """Mark what the inspector shows (no callback)."""
        if (part, muscle, tracker) != (self._part, self._muscle, self._tracker):
            self._part, self._muscle, self._tracker = part, muscle, tracker
            self.update()

    def selection(self) -> Tuple[Optional[str], Optional[str]]:
        """(part, muscle) picked."""
        return self._part, self._muscle

    def picked_tracker(self) -> Optional[str]:
        return self._tracker

    # ---- geometry --------------------------------------------------------
    def _scale(self) -> float:
        by_h = (self.height() - CAPTION_H) / FIG_BOX.height()
        by_w = (self.width() - VIEW_GAP) / 2 / FIG_BOX.width()
        return max(0.05, min(by_h, by_w))

    def view_rect(self, view: int) -> QRectF:
        """Where FIG_BOX of her `view` lands in the widget."""
        s = self._scale()
        w, h = FIG_BOX.width() * s, FIG_BOX.height() * s
        x0 = (self.width() - (2 * w + VIEW_GAP)) / 2
        return QRectF(x0 + view * (w + VIEW_GAP), CAPTION_H, w, h)

    def _to_widget(self, view: int) -> QTransform:
        s = self._scale()
        r = self.view_rect(view)
        return QTransform(s, 0, 0, s, r.x() - FIG_BOX.x() * s, r.y() - FIG_BOX.y() * s)

    def dot_radius(self) -> float:
        return max(DOT_MIN_PX, DOT_R * self._scale())

    def puck_radius(self) -> float:
        return max(DOT_MIN_PX + 2.5, PUCK_R * self._scale())

    def dot_center(self, position: str, index: int) -> QPointF:
        view, _angle, points = PLACES[position]
        x, y = points[index]
        return self._to_widget(view).map(QPointF(x, y))

    def tracker_center(self, key: str) -> QPointF:
        x, y = _TRACKER_AT[key]
        return self._to_widget(FRONT).map(QPointF(x, y))

    def zone_path(self, muscle: str) -> QPainterPath:
        """A muscle's patch: a rounded box around its dots, turned with the
        limb they sit on."""
        position, cells = body_map.OWO_REGIONS[muscle]
        view, angle, points = PLACES[position]
        a = math.radians(angle)
        ca, sa = math.cos(a), math.sin(a)
        local = [(x * ca + y * sa, -x * sa + y * ca) for x, y in (points[i] for i in cells)]
        pad = self.dot_radius() / self._scale() + ZONE_PAD
        xs, ys = [p[0] for p in local], [p[1] for p in local]
        path = QPainterPath()
        path.addRoundedRect(QRectF(min(xs) - pad, min(ys) - pad,
                                   max(xs) - min(xs) + 2 * pad, max(ys) - min(ys) + 2 * pad),
                            pad, pad)
        return self._to_widget(view).map(QTransform().rotate(angle).map(path))

    def anchor(self, kind: str, name: Optional[str]) -> Optional[QPointF]:
        """Where the line to its card starts (kind "part", "muscle" or
        "tracker"): the right edge of a part's dots, a patch or a puck, at
        its middle. None for something not on her right now."""
        if kind == "part" and name in self._parts_shown and self._show_bh:
            pts = [self.dot_center(name, i) for i in range(len(PLACES[name][2]))]
            return QPointF(max(p.x() for p in pts) + self.dot_radius() + 2,
                           (min(p.y() for p in pts) + max(p.y() for p in pts)) / 2)
        if kind == "muscle" and name in body_map.OWO_REGIONS and self._show_owo:
            rect = self.zone_path(name).boundingRect()
            return QPointF(rect.right() + 1, rect.center().y())
        if kind == "tracker" and name in self._trackers_shown:
            c = self.tracker_center(name)
            return QPointF(c.x() + self.puck_radius() + 2, c.y())
        return None

    def _hit_tracker(self, pos: QPointF) -> Optional[str]:
        reach = (self.puck_radius() + 3.0) ** 2
        for key, _name, _xy in TRACKERS:
            if key in self._trackers_shown:
                c = self.tracker_center(key)
                if (c.x() - pos.x()) ** 2 + (c.y() - pos.y()) ** 2 <= reach:
                    return key
        return None

    def _hit_dot(self, pos: QPointF) -> Optional[Tuple[str, int]]:
        if not self._show_bh:
            return None
        best, best_d = None, (self.dot_radius() + 4.0) ** 2
        for position, (_view, _a, points) in PLACES.items():
            if position not in self._parts_shown:
                continue
            for i in range(len(points)):
                c = self.dot_center(position, i)
                d = (c.x() - pos.x()) ** 2 + (c.y() - pos.y()) ** 2
                if d <= best_d:
                    best, best_d = (position, i), d
        return best

    def _hit_muscle(self, pos: QPointF) -> Optional[str]:
        if not self._show_owo:
            return None
        for muscle in body_map.MUSCLES:
            if self.zone_path(muscle).contains(pos):
                return muscle
        return None

    # ---- input -----------------------------------------------------------
    def mousePressEvent(self, event) -> None:
        pos = event.position()
        tracker = self._hit_tracker(pos)
        dot = None if tracker is not None else self._hit_dot(pos)
        if tracker is not None:
            self._pick(None, None, tracker)
        elif dot is not None:
            self._pick(dot[0], muscle_at(*dot), None)
            if self._on_hold is not None:
                self._held = dot
                self._on_hold(dot[0], dot[1], True)
        else:
            # a patch between dots: just its muscle; empty space: close the cards
            self._pick(None, self._hit_muscle(pos), None)
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        if self._held is not None and self._on_hold is not None:
            self._on_hold(self._held[0], self._held[1], False)
        self._held = None
        super().mouseReleaseEvent(event)

    def _pick(self, part: Optional[str], muscle: Optional[str], tracker: Optional[str]) -> None:
        self.select(part, muscle, tracker)
        if self._on_pick is not None:
            self._on_pick(part, muscle, tracker)

    # ---- paint -----------------------------------------------------------
    def _figure(self, view: int, rect: QRectF, color: QColor) -> QPixmap:
        """Her lines at `rect`'s size in `color`, made once per size and
        colour (a live tick only repaints the dots)."""
        dpr = self.devicePixelRatioF()
        w, h = max(1, round(rect.width() * dpr)), max(1, round(rect.height() * dpr))
        key = (color.rgba(), w, h)
        cached = self._tinted.get(view)
        if cached is not None and cached[0] == key:
            return cached[1]
        img = self._figures[view].scaled(w, h, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
        img = img.convertToFormat(QImage.Format_ARGB32_Premultiplied)
        p = QPainter(img)
        p.setCompositionMode(QPainter.CompositionMode_SourceIn)
        p.fillRect(img.rect(), color)
        p.end()
        pix = QPixmap.fromImage(img)
        pix.setDevicePixelRatio(dpr)
        self._tinted[view] = (key, pix)
        return pix

    def paintEvent(self, _event) -> None:
        chrome = _theme.CHROME
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        muted, dim = QColor(chrome["muted"]), QColor(chrome["dim"])
        warn = QPen(QColor(_theme.PALETTE["amber"][0]), 1.3, Qt.DashLine)

        font = QFont(self.font())
        font.setPixelSize(CAPTION_PX)
        font.setBold(True)
        font.setLetterSpacing(QFont.AbsoluteSpacing, 2.0)
        p.setFont(font)
        her = QColor(chrome["accent"])
        her.setAlphaF(FIGURE_ALPHA)
        for view, caption, sides in ((FRONT, "FRONT", ("R", "L")), (BACK, "BACK", ("L", "R"))):
            r = self.view_rect(view)
            p.setPen(muted)
            p.drawText(QRectF(r.x(), 0, r.width(), CAPTION_H), Qt.AlignCenter, caption)
            p.drawPixmap(r.topLeft(), self._figure(view, r, her))
            # her right and left as she stands, beside her chest: on the
            # front her right is on our left
            p.setPen(dim)
            for (x, y), side in zip(_SIDE_MARKS, sides):
                at = self._to_widget(view).map(QPointF(x, y))
                p.drawText(QRectF(at.x() - 10, at.y() - 10, 20, 20), Qt.AlignCenter, side)

        well = QColor(chrome["well"])
        if self._show_owo:
            self._paint_zones(p, dim, warn)
        if self._show_bh:
            self._paint_dots(p, dim, well, warn)
        if self._trackers_shown:
            self._paint_trackers(p, dim, well, warn)
        p.end()

    def _paint_zones(self, p: QPainter, dim: QColor, warn: QPen) -> None:
        vib, mid, tint = _theme.tri(_theme.OWO_HUE)
        for muscle in body_map.MUSCLES:
            path = self.zone_path(muscle)
            off = muscle in self._muscles_off
            picked = muscle == self._muscle
            level = 0.0 if off else min(1.0, float(self._owo.get(muscle, 0.0) or 0.0))
            if level > 0.0:
                fill = _blend(tint, vib, 0.25 + 0.6 * level)
                fill.setAlphaF(0.75)
            else:
                fill = QColor(tint)
                fill.setAlphaF(0.0 if off else 0.6)
            edge = dim if off else QColor(vib if picked or level > 0.0 else mid)
            p.setPen(QPen(edge, 2.2 if picked else 1.3, Qt.DashLine if off else Qt.SolidLine))
            p.setBrush(fill)
            p.drawPath(path)
            if muscle in self._missing_muscles and not off:
                p.setPen(warn)
                p.setBrush(Qt.NoBrush)
                p.drawPath(_outset(path, 3.0))

    def _paint_dots(self, p: QPainter, dim: QColor, well: QColor, warn: QPen) -> None:
        vib, mid, tint = _theme.tri(_theme.BHAPTICS_HUE)
        r = self.dot_radius()
        for position, (_view, _a, points) in PLACES.items():
            if position not in self._parts_shown:
                continue
            off = position in self._parts_off
            picked = position == self._part
            vals = self._frame.get(position) or ()
            missing = self._missing_dots.get(position, frozenset())
            for i in range(len(points)):
                v = 0.0 if off else min(1.0, float(vals[i]) if i < len(vals) else 0.0)
                held = self._held == (position, i)
                if v > 0.0 or held:
                    fill = _blend(tint, vib, 0.3 + 0.7 * max(v, 0.5 if held else 0.0))
                else:
                    fill = QColor(tint) if picked and not off else well
                edge = dim if off else QColor(vib)
                c = self.dot_center(position, i)
                p.setPen(QPen(edge, 2.0 if picked else 1.3))
                p.setBrush(fill)
                p.drawEllipse(c, r, r)
                if i in missing and not off:
                    p.setPen(warn)
                    p.setBrush(Qt.NoBrush)
                    p.drawEllipse(c, r + 2.5, r + 2.5)

    def _paint_trackers(self, p: QPainter, dim: QColor, well: QColor, warn: QPen) -> None:
        """A puck: a ring with a hub, like a Vive tracker seen from above."""
        vib, mid, tint = _theme.tri(_theme.TRACKERS_HUE)
        r = self.puck_radius()
        for key, _name, _xy in TRACKERS:
            if key not in self._trackers_shown:
                continue
            off = key in self._trackers_off
            picked = key == self._tracker
            v = 0.0 if off else min(1.0, float(self._trackers.get(key, 0.0) or 0.0))
            c = self.tracker_center(key)
            if v > 0.0:
                fill = _blend(tint, vib, 0.3 + 0.7 * v)
            else:
                fill = QColor(tint) if picked and not off else well
            edge = dim if off else QColor(vib)
            p.setPen(QPen(edge, 2.2 if picked else 1.4, Qt.DashLine if off else Qt.SolidLine))
            p.setBrush(fill)
            p.drawEllipse(c, r, r)
            p.setPen(Qt.NoPen)
            p.setBrush(dim if off else QColor(vib if v > 0.0 else mid))
            p.drawEllipse(c, r * 0.42, r * 0.42)
            if key in self._missing_trackers and not off:
                p.setPen(warn)
                p.setBrush(Qt.NoBrush)
                p.drawEllipse(c, r + 3.0, r + 3.0)
