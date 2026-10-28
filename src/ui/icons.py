"""Vector icons painted at runtime — independent of emoji-font availability."""

from typing import Tuple

from PySide6.QtCore import Qt, QPointF, QRectF
from PySide6.QtGui import QBrush, QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap, QPolygonF

import friend_patterns

from constants import COLOR_ALERT, COLOR_BG, COLOR_INPUT_BG, COLOR_SUCCESS, COLOR_SURFACE, COLOR_TEXT


def new_icon_pixmap(size: int = 20) -> QPixmap:
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    return pm


def icon_pencil(color: str = COLOR_TEXT, size: int = 20) -> QIcon:
    """Edit pencil with a stronger outline."""
    pm = new_icon_pixmap(size)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    c = QColor(color)
    p.setPen(QPen(c, 1.6))
    p.setBrush(QBrush(c))
    # Diagonal pencil body from (4,16) to (14,6) with a triangular tip at top-right.
    body = QPolygonF([
        QPointF(3.5, 14.5), QPointF(5.5, 16.5),
        QPointF(14.0, 8.0), QPointF(12.0, 6.0),
    ])
    p.drawPolygon(body)
    # Pencil tip
    tip = QPolygonF([
        QPointF(14.0, 8.0), QPointF(12.0, 6.0),
        QPointF(16.5, 3.5),
    ])
    p.setBrush(QBrush(QColor("#FFD27A")))
    p.drawPolygon(tip)
    # Eraser end
    p.setBrush(QBrush(QColor(color)))
    eraser = QPolygonF([
        QPointF(3.5, 14.5), QPointF(5.5, 16.5),
        QPointF(3.5, 18.5), QPointF(1.5, 16.5),
    ])
    p.drawPolygon(eraser)
    p.end()
    return QIcon(pm)


def icon_copy(color: str = COLOR_TEXT, size: int = 20) -> QIcon:
    """Two overlapping sheets of paper."""
    pm = new_icon_pixmap(size)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    c = QColor(color)
    # Back sheet
    p.setPen(QPen(c, 1.4))
    p.setBrush(QBrush(QColor(COLOR_SURFACE)))
    p.drawRoundedRect(QRectF(7.0, 3.0, 10.0, 12.0), 1.5, 1.5)
    # Front sheet (overlapping, offset down-left)
    p.setBrush(QBrush(QColor(COLOR_INPUT_BG)))
    p.drawRoundedRect(QRectF(3.0, 6.5, 10.0, 12.0), 1.5, 1.5)
    p.setPen(QPen(c, 1.0))
    p.drawLine(QPointF(5.0, 10.0), QPointF(11.0, 10.0))
    p.drawLine(QPointF(5.0, 13.0), QPointF(11.0, 13.0))
    p.drawLine(QPointF(5.0, 16.0), QPointF(9.0, 16.0))
    p.end()
    return QIcon(pm)


def icon_paste(color: str = COLOR_TEXT, size: int = 20) -> QIcon:
    """Clipboard with a down-arrow — paste-into-this-slot."""
    pm = new_icon_pixmap(size)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    c = QColor(color)
    p.setPen(QPen(c, 1.4))
    p.setBrush(QBrush(QColor(COLOR_SURFACE)))
    p.drawRoundedRect(QRectF(4.0, 5.0, 12.0, 13.0), 1.5, 1.5)
    p.setBrush(QBrush(c))
    p.drawRoundedRect(QRectF(7.0, 2.5, 6.0, 3.5), 1.0, 1.0)
    pen = QPen(c, 1.8)
    pen.setCapStyle(Qt.RoundCap)
    pen.setJoinStyle(Qt.RoundJoin)
    p.setPen(pen)
    p.setBrush(Qt.NoBrush)
    p.drawLine(QPointF(10.0, 9.0), QPointF(10.0, 14.0))
    p.drawPolyline(QPolygonF([
        QPointF(7.5, 12.0), QPointF(10.0, 14.5), QPointF(12.5, 12.0),
    ]))
    p.end()
    return QIcon(pm)


def icon_trash(color: str = COLOR_TEXT, size: int = 20) -> QIcon:
    """Trapezoid-style trash can with a lid."""
    pm = new_icon_pixmap(size)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    c = QColor(color)
    p.setPen(QPen(c, 1.5))
    p.setBrush(QBrush(c))
    p.drawRoundedRect(QRectF(3.0, 4.5, 14.0, 2.0), 1.0, 1.0)
    p.setBrush(Qt.NoBrush)
    p.drawRoundedRect(QRectF(7.5, 2.5, 5.0, 2.0), 1.0, 1.0)
    body = QPolygonF([
        QPointF(4.5, 7.0), QPointF(15.5, 7.0),
        QPointF(14.5, 17.5), QPointF(5.5, 17.5),
    ])
    p.setBrush(QBrush(c))
    p.drawPolygon(body)
    p.setPen(QPen(QColor(COLOR_BG), 1.0))
    p.drawLine(QPointF(8.0, 9.0), QPointF(7.7, 16.0))
    p.drawLine(QPointF(10.0, 9.0), QPointF(10.0, 16.0))
    p.drawLine(QPointF(12.0, 9.0), QPointF(12.3, 16.0))
    p.end()
    return QIcon(pm)


def icon_check(color: str = COLOR_SUCCESS, size: int = 20) -> QIcon:
    pm = new_icon_pixmap(size)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    pen = QPen(QColor(color), 2.6)
    pen.setCapStyle(Qt.RoundCap)
    pen.setJoinStyle(Qt.RoundJoin)
    p.setPen(pen)
    p.drawPolyline(QPolygonF([
        QPointF(3.5, 10.5), QPointF(8.5, 15.5), QPointF(16.5, 5.5),
    ]))
    p.end()
    return QIcon(pm)


def icon_cross(color: str = COLOR_ALERT, size: int = 20) -> QIcon:
    pm = new_icon_pixmap(size)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    pen = QPen(QColor(color), 2.6)
    pen.setCapStyle(Qt.RoundCap)
    p.setPen(pen)
    p.drawLine(QPointF(5.0, 5.0), QPointF(15.0, 15.0))
    p.drawLine(QPointF(15.0, 5.0), QPointF(5.0, 15.0))
    p.end()
    return QIcon(pm)


def icon_home(color: str = COLOR_SUCCESS, size: int = 20) -> QIcon:
    """Line-art house for the sidebar's Home entry: a roof, walls and a
    door, stroked in the accent. Painted once per display scale (1x, 2x,
    3x) so it is drawn, not stretched, at whatever scaling the screen
    runs; the straight strokes sit on pixel centres so they stay sharp
    at 1x."""
    icon = QIcon()
    for scale in (1, 2, 3):
        pm = QPixmap(size * scale, size * scale)
        pm.fill(Qt.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.Antialiasing)
        p.scale(scale * size / 20.0, scale * size / 20.0)
        pen = QPen(QColor(color), 1.5)
        pen.setCapStyle(Qt.RoundCap)
        pen.setJoinStyle(Qt.RoundJoin)
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        p.drawPolyline(QPolygonF([
            QPointF(2.5, 10.0), QPointF(10.0, 3.0), QPointF(17.5, 10.0),
        ]))
        p.drawPolyline(QPolygonF([
            QPointF(4.5, 8.5), QPointF(4.5, 16.5),
            QPointF(15.5, 16.5), QPointF(15.5, 8.5),
        ]))
        p.drawPolyline(QPolygonF([
            QPointF(8.5, 16.5), QPointF(8.5, 11.5),
            QPointF(11.5, 11.5), QPointF(11.5, 16.5),
        ]))
        p.end()
        pm.setDevicePixelRatio(scale)
        icon.addPixmap(pm)
    return icon


def icon_no_battery(color: str = COLOR_TEXT, size: int = 20) -> QIcon:
    """Battery outline with a diagonal slash — for toys that don't report
    a battery level. Avoids the font-dependent Unicode glyph (U+1FAAB)."""
    pm = new_icon_pixmap(size)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    c = QColor(color)

    # Battery body (outline) + positive-terminal nub.
    p.setPen(QPen(c, 1.4))
    p.setBrush(Qt.NoBrush)
    p.drawRoundedRect(QRectF(2.5, 6.0, 12.0, 8.0), 1.5, 1.5)
    p.setBrush(QBrush(c))
    p.drawRoundedRect(QRectF(14.5, 8.5, 2.0, 3.0), 0.6, 0.6)

    # Diagonal slash across the whole icon. Backstroke in the canvas
    # color first so the slash reads cleanly where it crosses the body
    # outline, then the slash on top in the icon color.
    backstroke = QPen(QColor(COLOR_BG), 3.0)
    backstroke.setCapStyle(Qt.RoundCap)
    p.setPen(backstroke)
    p.drawLine(QPointF(3.0, 17.0), QPointF(17.0, 3.0))
    slash = QPen(c, 1.8)
    slash.setCapStyle(Qt.RoundCap)
    p.setPen(slash)
    p.drawLine(QPointF(3.0, 17.0), QPointF(17.0, 3.0))
    p.end()
    return QIcon(pm)


# ---------------------------------------------------------------------------
# The Friends page's cards: the auto modes' own curves and a few glyphs
# ---------------------------------------------------------------------------

def _pixmap(w: int, h: int) -> Tuple[QPixmap, QPainter]:
    pm = QPixmap(w * 2, h * 2)
    pm.setDevicePixelRatio(2.0)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    return pm, p


def wave_icon(wave: str, color: str, w: int = 22, h: int = 14) -> QIcon:
    """A mode's own curve, drawn from friend_patterns (Random is a die,
    Linear a level line, Oscillate a swing around one)."""
    if wave == "random":
        return glyph_icon("dice", color, h + 2)
    pm, p = _pixmap(w, h)
    pen = QPen(QColor(color), 1.6, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
    p.setPen(pen)
    if wave == "linear":
        p.drawLine(QPointF(1, h * 0.45), QPointF(w - 1, h * 0.45))
        p.end()
        return QIcon(pm)
    if wave == "osc":
        dash = QPen(QColor(color), 1.0, Qt.DashLine)
        p.setPen(dash)
        p.drawLine(QPointF(1, h / 2), QPointF(w - 1, h / 2))
        p.setPen(pen)
    cycles = 1.0 if wave in ("build", "heart") else 2.0
    lo, hi = (0.25, 0.75) if wave == "osc" else (0.0, 1.0)
    path = QPainterPath()
    n = 64
    for i in range(n + 1):
        x = i / n
        y = lo + (hi - lo) * friend_patterns.shape(wave, x * cycles, x * 3.0, 1.0)
        pt = QPointF(1 + x * (w - 2), h - 2 - y * (h - 4))
        path.lineTo(pt) if i else path.moveTo(pt)
    p.drawPath(path)
    p.end()
    return QIcon(pm)


def glyph_icon(kind: str, color: str, size: int = 16) -> QIcon:
    pm, p = _pixmap(size, size)
    c = QColor(color)
    s = size / 16.0
    if kind == "bolt":
        p.setPen(Qt.NoPen)
        p.setBrush(QBrush(c))
        p.drawPolygon(QPolygonF([QPointF(9.5 * s, 0.5 * s), QPointF(3 * s, 9 * s),
                                 QPointF(7.5 * s, 9 * s), QPointF(6 * s, 15.5 * s),
                                 QPointF(13 * s, 6.5 * s), QPointF(8.5 * s, 6.5 * s)]))
    elif kind == "vibrate":
        p.setPen(QPen(c, 1.5 * s))
        p.setBrush(Qt.NoBrush)
        p.drawRoundedRect(QRectF(5 * s, 2 * s, 6 * s, 12 * s), 1.5 * s, 1.5 * s)
        for x0, sign in ((2.5, -1), (13.5, 1)):
            path = QPainterPath(QPointF(x0 * s, 4 * s))
            for k, y in enumerate((6, 8, 10, 12)):
                path.lineTo(QPointF((x0 + sign * (1.2 if k % 2 == 0 else 0)) * s, y * s))
            p.drawPath(path)
    elif kind == "bell":
        p.setPen(QPen(c, 1.5 * s))
        p.setBrush(Qt.NoBrush)
        path = QPainterPath(QPointF(3 * s, 12 * s))
        path.cubicTo(QPointF(4.5 * s, 10 * s), QPointF(4 * s, 3 * s), QPointF(8 * s, 3 * s))
        path.cubicTo(QPointF(12 * s, 3 * s), QPointF(11.5 * s, 10 * s), QPointF(13 * s, 12 * s))
        path.closeSubpath()
        p.drawPath(path)
        p.drawLine(QPointF(6.5 * s, 14.5 * s), QPointF(9.5 * s, 14.5 * s))
    elif kind == "dice":
        p.setPen(QPen(c, 1.4 * s))
        p.setBrush(Qt.NoBrush)
        p.drawRoundedRect(QRectF(2 * s, 2 * s, 12 * s, 12 * s), 2.5 * s, 2.5 * s)
        p.setPen(Qt.NoPen)
        p.setBrush(QBrush(c))
        for x, y in ((5, 5), (8, 8), (11, 11)):
            p.drawEllipse(QPointF(x * s, y * s), 1.3 * s, 1.3 * s)
    elif kind in ("expand", "collapse"):
        # two diagonal arrows: out to the corners (full screen) or back in
        p.setPen(QPen(c, 1.6 * s, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        for sx, sy in ((1, -1), (-1, 1)):
            far = QPointF(8 + sx * 6, 8 + sy * 6)
            near = QPointF(8 + sx * 1.5, 8 + sy * 1.5)
            p.drawLine(QPointF(near.x() * s, near.y() * s), QPointF(far.x() * s, far.y() * s))
            tip = far if kind == "expand" else near
            back = -1 if kind == "expand" else 1
            p.drawPolyline(QPolygonF([
                QPointF((tip.x() + back * sx * 4) * s, tip.y() * s),
                QPointF(tip.x() * s, tip.y() * s),
                QPointF(tip.x() * s, (tip.y() + back * sy * 4) * s)]))
    elif kind in ("up", "down"):
        p.setPen(QPen(c, 1.6 * s, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        for dy in (0, 5):
            if kind == "up":
                pts = [QPointF(4 * s, (8 + dy) * s), QPointF(8 * s, (4 + dy) * s), QPointF(12 * s, (8 + dy) * s)]
            else:
                pts = [QPointF(4 * s, (3 + dy) * s), QPointF(8 * s, (7 + dy) * s), QPointF(12 * s, (3 + dy) * s)]
            p.drawPolyline(QPolygonF(pts))
    # PiShock's shocker panel (ui/views/shocker_card.py): Duration, Warning,
    # the three Use Modes, STOP and the intensity gauge under each slider
    elif kind == "clock":
        p.setPen(QPen(c, 1.5 * s, Qt.SolidLine, Qt.RoundCap))
        p.setBrush(Qt.NoBrush)
        p.drawEllipse(QPointF(8 * s, 8 * s), 6.2 * s, 6.2 * s)
        p.drawPolyline(QPolygonF([QPointF(8 * s, 4.2 * s), QPointF(8 * s, 8 * s),
                                  QPointF(10.8 * s, 9.6 * s)]))
    elif kind == "alert":
        # a circle with "!" and a bracket either side, like a warning lamp
        p.setPen(QPen(c, 1.5 * s, Qt.SolidLine, Qt.RoundCap))
        p.setBrush(Qt.NoBrush)
        p.drawEllipse(QPointF(8 * s, 8 * s), 4.6 * s, 4.6 * s)
        p.drawArc(QRectF(0.6 * s, 1.6 * s, 6 * s, 12.8 * s), 120 * 16, 120 * 16)
        p.drawArc(QRectF(9.4 * s, 1.6 * s, 6 * s, 12.8 * s), -60 * 16, 120 * 16)
        p.drawLine(QPointF(8 * s, 5.6 * s), QPointF(8 * s, 8.6 * s))
        p.setPen(Qt.NoPen)
        p.setBrush(QBrush(c))
        p.drawEllipse(QPointF(8 * s, 10.6 * s), 0.9 * s, 0.9 * s)
    elif kind == "tap":
        # a hand, its index finger up: press
        p.setPen(Qt.NoPen)
        p.setBrush(QBrush(c))
        hand = QPainterPath()
        hand.addRoundedRect(QRectF(5.6 * s, 1.0 * s, 3.0 * s, 9.0 * s), 1.5 * s, 1.5 * s)
        hand.addRoundedRect(QRectF(4.0 * s, 7.2 * s, 9.0 * s, 7.8 * s), 2.6 * s, 2.6 * s)
        hand.addRoundedRect(QRectF(2.0 * s, 8.4 * s, 3.4 * s, 4.2 * s), 1.6 * s, 1.6 * s)
        hand.setFillRule(Qt.WindingFill)
        p.drawPath(hand.simplified())
    elif kind == "remote":
        # a hand-held remote, sending
        p.setPen(QPen(c, 1.4 * s, Qt.SolidLine, Qt.RoundCap))
        p.setBrush(Qt.NoBrush)
        p.drawRoundedRect(QRectF(5.5 * s, 6 * s, 5 * s, 9 * s), 1.4 * s, 1.4 * s)
        p.drawArc(QRectF(4.5 * s, 2.4 * s, 7 * s, 5 * s), 40 * 16, 100 * 16)
        p.drawArc(QRectF(2.5 * s, 0.4 * s, 11 * s, 7 * s), 45 * 16, 90 * 16)
        p.setPen(Qt.NoPen)
        p.setBrush(QBrush(c))
        p.drawEllipse(QPointF(8 * s, 9 * s), 1.1 * s, 1.1 * s)
    elif kind == "infinity":
        p.setPen(QPen(c, 1.7 * s, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        p.setBrush(Qt.NoBrush)
        path = QPainterPath(QPointF(8 * s, 8 * s))
        path.cubicTo(QPointF(10.5 * s, 4.2 * s), QPointF(15 * s, 4.6 * s), QPointF(15 * s, 8 * s))
        path.cubicTo(QPointF(15 * s, 11.4 * s), QPointF(10.5 * s, 11.8 * s), QPointF(8 * s, 8 * s))
        path.cubicTo(QPointF(5.5 * s, 4.2 * s), QPointF(1 * s, 4.6 * s), QPointF(1 * s, 8 * s))
        path.cubicTo(QPointF(1 * s, 11.4 * s), QPointF(5.5 * s, 11.8 * s), QPointF(8 * s, 8 * s))
        p.drawPath(path)
    elif kind == "stop":
        # an octagon with "!" cut out of it
        p.setPen(Qt.NoPen)
        p.setBrush(QBrush(c))
        k = 2.2
        p.drawPolygon(QPolygonF([QPointF(x * s, y * s) for x, y in (
            (5.2, 1.2), (10.8, 1.2), (14.8, 5.2), (14.8, 10.8), (10.8, 14.8),
            (5.2, 14.8), (1.2, 10.8), (1.2, 5.2))]))
        p.setCompositionMode(QPainter.CompositionMode_Clear)
        p.drawRoundedRect(QRectF((8 - k / 2) * s, 4 * s, k * s, 5.6 * s), 1 * s, 1 * s)
        p.drawEllipse(QPointF(8 * s, 11.6 * s), 1.25 * s, 1.25 * s)
    elif kind == "gauge":
        p.setPen(QPen(c, 1.6 * s, Qt.SolidLine, Qt.RoundCap))
        p.setBrush(Qt.NoBrush)
        p.drawArc(QRectF(1.5 * s, 2.5 * s, 13 * s, 13 * s), -30 * 16, 240 * 16)
        p.drawLine(QPointF(8 * s, 9 * s), QPointF(11.4 * s, 5.4 * s))
        p.setPen(Qt.NoPen)
        p.setBrush(QBrush(c))
        p.drawEllipse(QPointF(8 * s, 9 * s), 1.4 * s, 1.4 * s)
    p.end()
    return QIcon(pm)


# ---------------------------------------------------------------------------
# What a thing is, one icon wherever it shows: toys in pink, shockers in
# yellow, Avatar Remote in the accent green (Blise's ask, 2026-10-27), and
# Friends in cyan, as in the VRChat menu (his ask, 2026-10-28). On a
# 20-unit grid, painted per display scale like icon_home.
# ---------------------------------------------------------------------------

def _scaled(draw, color: str, size: int) -> QIcon:
    icon = QIcon()
    for scale in (1, 2, 3, 4):
        pm = QPixmap(size * scale, size * scale)
        pm.fill(Qt.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.Antialiasing)
        p.scale(scale * size / 20.0, scale * size / 20.0)
        if draw is not None:
            draw(p, QColor(color))
        p.end()
        pm.setDevicePixelRatio(scale)
        icon.addPixmap(pm)
    return icon


def _stroke(p: QPainter, c: QColor, width: float = 1.5) -> None:
    p.setPen(QPen(c, width, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
    p.setBrush(Qt.NoBrush)


def _draw_toy(p: QPainter, c: QColor) -> None:
    """A toy: a capsule with a band, buzzing either side (the VRChat
    menu's toy)."""
    _stroke(p, c)
    p.drawRoundedRect(QRectF(7.25, 2.0, 5.5, 16.0), 2.75, 2.75)
    p.drawLine(QPointF(7.25, 13.5), QPointF(12.75, 13.5))
    for x0, side in ((4.4, -1), (15.6, 1)):
        path = QPainterPath(QPointF(x0, 5.0))
        for k, y in enumerate((6.75, 8.5, 10.25, 12.0, 13.75)):
            path.lineTo(QPointF(x0 + side * (1.4 if k % 2 == 0 else 0), y))
        p.drawPath(path)


def _draw_bolt(p: QPainter, c: QColor) -> None:
    """A shocker: the bolt, solid (the VRChat menu's bolt)."""
    p.setPen(Qt.NoPen)
    p.setBrush(QBrush(c))
    pts = ((30, -200), (-110, 30), (0, 30), (-40, 200), (110, -40), (0, -40))
    p.drawPolygon(QPolygonF([QPointF(10 + x * 0.042, 10 + y * 0.042) for x, y in pts]))


def _draw_remote(p: QPainter, c: QColor) -> None:
    """Avatar Remote: a remote with a dial and four buttons."""
    _stroke(p, c)
    p.drawRoundedRect(QRectF(5.5, 1.75, 9.0, 16.5), 2.5, 2.5)
    p.drawEllipse(QPointF(10.0, 6.5), 2.2, 2.2)
    p.setPen(Qt.NoPen)
    p.setBrush(QBrush(c))
    for x, y in ((8.0, 11.5), (12.0, 11.5), (8.0, 14.75), (12.0, 14.75)):
        p.drawEllipse(QPointF(x, y), 1.05, 1.05)


def _person(cx: float, cy: float, s: float) -> Tuple[QPainterPath, QPainterPath]:
    """(head, shoulders) of a person standing at (cx, cy), `s` big -- the
    VRChat menu icons' person (tools/make_menu_icons.py), on their
    512-unit grid."""
    head = QPainterPath()
    head.addEllipse(QPointF(cx, cy - 70 * s), 62 * s, 62 * s)
    shoulders = QPainterPath(QPointF(cx - 130 * s, cy + 150 * s))
    shoulders.cubicTo(QPointF(cx - 130 * s, cy + 20 * s),
                      QPointF(cx + 130 * s, cy + 20 * s),
                      QPointF(cx + 130 * s, cy + 150 * s))
    return head, shoulders


def _draw_friends(p: QPainter, c: QColor) -> None:
    """Friends: two people, the one behind cut where the one in front
    stands (the VRChat menu's friends icon, in one colour)."""
    from PySide6.QtGui import QPainterPathStroker
    k = 17.0 / 381.5                    # the pair's 512-unit box -> 17 units
    p.save()
    p.translate(10.0, 10.0)
    p.scale(k, k)
    p.translate(-260.25, -288.45)
    width = 1.5 / k
    back = _person(330, 250, 0.8)
    front = _person(210, 290, 0.95)
    # Where the one in front stands, with a gap around their lines
    stand = QPainterPath(front[0])
    body = QPainterPath(front[1])
    body.closeSubpath()
    stand.addPath(body)
    stroker = QPainterPathStroker()
    stroker.setWidth(width * 2.4)
    stroker.setCapStyle(Qt.RoundCap)
    stand = stand.united(stroker.createStroke(front[0]))
    stand = stand.united(stroker.createStroke(front[1]))
    room = QPainterPath()
    room.addRect(QRectF(-200, -200, 912, 912))
    _stroke(p, c, width)
    p.setClipPath(room.subtracted(stand))
    for path in back:
        p.drawPath(path)
    p.setClipping(False)
    for path in front:
        p.drawPath(path)
    p.restore()


def _draw_suit(p: QPainter, c: QColor) -> None:
    """A haptic suit: a vest with a round neck and its motors."""
    _stroke(p, c)
    vest = QPainterPath(QPointF(7.0, 2.25))
    vest.cubicTo(QPointF(7.6, 5.0), QPointF(12.4, 5.0), QPointF(13.0, 2.25))
    vest.lineTo(QPointF(16.25, 4.0))
    vest.cubicTo(QPointF(15.0, 5.5), QPointF(15.0, 8.0), QPointF(16.25, 9.0))
    vest.lineTo(QPointF(16.25, 16.5))
    vest.quadTo(QPointF(16.25, 17.75), QPointF(15.0, 17.75))
    vest.lineTo(QPointF(5.0, 17.75))
    vest.quadTo(QPointF(3.75, 17.75), QPointF(3.75, 16.5))
    vest.lineTo(QPointF(3.75, 9.0))
    vest.cubicTo(QPointF(5.0, 8.0), QPointF(5.0, 5.5), QPointF(3.75, 4.0))
    vest.closeSubpath()
    p.drawPath(vest)
    p.setPen(Qt.NoPen)
    p.setBrush(QBrush(c))
    for x in (7.75, 12.25):
        for y in (9.25, 12.25, 15.0):
            p.drawEllipse(QPointF(x, y), 1.0, 1.0)


def _draw_web(p: QPainter, c: QColor) -> None:
    """The web remote: a globe -- a browser, anywhere, driving your toys."""
    _stroke(p, c)
    p.drawEllipse(QPointF(10.0, 10.0), 7.75, 7.75)
    p.drawEllipse(QPointF(10.0, 10.0), 3.4, 7.75)
    p.drawLine(QPointF(2.25, 10.0), QPointF(17.75, 10.0))
    for y in (6.0, 14.0):
        half = (7.75 ** 2 - (y - 10.0) ** 2) ** 0.5 - 0.6
        p.drawLine(QPointF(10.0 - half, y), QPointF(10.0 + half, y))


# by the Friends list's column keys (and "friends" for Friends itself)
_IDENTITY_DRAW = {"toys": _draw_toy, "shock": _draw_bolt, "params": _draw_remote,
                  "friends": _draw_friends, "suits": _draw_suit, "web": _draw_web}
IDENTITY_NAMES = {"toys": "Toys", "shock": "Shockers", "params": "Avatar Remote",
                  "friends": "Friends", "suits": "Suits", "web": "Web remote"}


def identity_color(what: str) -> str:
    """The colour of `what` now -- the colour picker moves them, so ask
    again after a change."""
    import constants
    from ui import theme
    if what == "params":
        return constants.COLOR_ACCENT
    return theme.hue({"toys": theme.FRIEND_TOYS_HUE, "friends": theme.FRIENDS_HUE,
                      "web": theme.FRIENDS_HUE,          # part of Friends
                      "suits": theme.SUITS_HUE}.get(what, theme.FRIEND_SHOCK_HUE))


def identity_icon(what: str, size: int = 20) -> QIcon:
    """The toys / shock / params icon in its colour now; any other `what`
    is a blank of the same size, to keep a column of labels lined up."""
    draw = _IDENTITY_DRAW.get(what)
    return _scaled(draw, identity_color(what) if draw else "#000000", size)


def identity_pixmap(what: str, size: int, dpr: float) -> QPixmap:
    """identity_icon for a QLabel, sharp at the label's display scale."""
    from PySide6.QtCore import QSize
    return identity_icon(what, size).pixmap(QSize(size, size), dpr)


# ---------------------------------------------------------------------------
# The pages that are not a kind of thing -- Statistics, the tools, Settings,
# Help -- so every sidebar entry has an icon (Blise's ask, 2026-10-28). Line
# art like the ones above, in the sidebar's text tone: a colour stays the
# sign of what something is.
# ---------------------------------------------------------------------------

def _draw_stats(p: QPainter, c: QColor) -> None:
    """Statistics: three bars on a baseline."""
    _stroke(p, c)
    for x, top in ((4.5, 10.0), (8.75, 4.5), (13.0, 7.5)):
        p.drawRoundedRect(QRectF(x, top, 2.75, 14.75 - top), 0.8, 0.8)
    p.drawLine(QPointF(2.75, 17.5), QPointF(17.25, 17.5))


def _draw_sps(p: QPainter, c: QColor) -> None:
    """SPS Sources: a contact -- a ring and its centre, sensing either
    side."""
    _stroke(p, c)
    p.drawEllipse(QPointF(10.0, 10.0), 3.5, 3.5)
    for r in (6.25, 8.75):
        for start in (135, -45):
            p.drawArc(QRectF(10 - r, 10 - r, 2 * r, 2 * r), start * 16, 90 * 16)
    p.setPen(Qt.NoPen)
    p.setBrush(QBrush(c))
    p.drawEllipse(QPointF(10.0, 10.0), 1.3, 1.3)


def _draw_inspector(p: QPainter, c: QColor) -> None:
    """OSC Inspector: a magnifying glass."""
    _stroke(p, c)
    p.drawEllipse(QPointF(8.5, 8.5), 5.25, 5.25)
    p.setPen(QPen(c, 2.25, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
    p.drawLine(QPointF(12.4, 12.4), QPointF(16.75, 16.75))


def _draw_diagnostics(p: QPainter, c: QColor) -> None:
    """OSC Diagnostics: a pulse line."""
    _stroke(p, c)
    p.drawPolyline(QPolygonF([QPointF(x, y) for x, y in (
        (2.0, 10.5), (6.0, 10.5), (8.0, 4.5), (11.25, 16.0),
        (13.25, 8.5), (14.75, 10.5), (18.0, 10.5))]))


def _draw_log(p: QPainter, c: QColor) -> None:
    """System Log: a page of lines."""
    _stroke(p, c)
    page = QPainterPath(QPointF(13.0, 2.25))
    page.lineTo(QPointF(5.5, 2.25))
    page.quadTo(QPointF(4.0, 2.25), QPointF(4.0, 3.75))
    page.lineTo(QPointF(4.0, 16.25))
    page.quadTo(QPointF(4.0, 17.75), QPointF(5.5, 17.75))
    page.lineTo(QPointF(14.5, 17.75))
    page.quadTo(QPointF(16.0, 17.75), QPointF(16.0, 16.25))
    page.lineTo(QPointF(16.0, 5.25))
    page.closeSubpath()
    p.drawPath(page)
    for y, x1 in ((7.5, 12.5), (10.5, 13.0), (13.5, 10.75)):
        p.drawLine(QPointF(7.0, y), QPointF(x1, y))


def _draw_gear(p: QPainter, c: QColor) -> None:
    """Settings: a gear."""
    import math
    _stroke(p, c)
    teeth, outer, inner = 8, 8.0, 6.0
    gear = QPainterPath()
    for i in range(teeth):
        a = 2 * math.pi * i / teeth
        half_top, half_root = math.pi / teeth * 0.42, math.pi / teeth * 0.62
        pts = ((a - half_root, inner), (a - half_top, outer),
               (a + half_top, outer), (a + half_root, inner))
        for j, (ang, r) in enumerate(pts):
            pt = QPointF(10 + r * math.cos(ang), 10 + r * math.sin(ang))
            if i == 0 and j == 0:
                gear.moveTo(pt)
            else:
                gear.lineTo(pt)
        nxt = a + 2 * math.pi / teeth - half_root
        gear.arcTo(QRectF(10 - inner, 10 - inner, 2 * inner, 2 * inner),
                   -math.degrees(a + half_root), -math.degrees(nxt - a - half_root))
    gear.closeSubpath()
    p.drawPath(gear)
    p.drawEllipse(QPointF(10.0, 10.0), 2.5, 2.5)


def _draw_help(p: QPainter, c: QColor) -> None:
    """Help: a question mark in a ring."""
    _stroke(p, c)
    p.drawEllipse(QPointF(10.0, 10.0), 7.75, 7.75)
    q = QPainterPath(QPointF(7.5, 8.0))
    q.cubicTo(QPointF(7.5, 4.75), QPointF(12.75, 4.75), QPointF(12.6, 7.9))
    q.cubicTo(QPointF(12.5, 9.75), QPointF(10.0, 9.9), QPointF(10.0, 12.0))
    p.drawPath(q)
    p.setPen(Qt.NoPen)
    p.setBrush(QBrush(c))
    p.drawEllipse(QPointF(10.0, 14.75), 1.05, 1.05)


_PAGE_DRAW = {"stats": _draw_stats, "sps": _draw_sps, "inspector": _draw_inspector,
              "diagnostics": _draw_diagnostics, "log": _draw_log,
              "settings": _draw_gear, "help": _draw_help}


def page_icon(what: str, size: int = 20) -> QIcon:
    """The icon of a page that is not a kind of thing, in the sidebar's
    text tone now; an identity name gets its identity_icon instead, and
    anything else a blank."""
    if what in _IDENTITY_DRAW or what not in _PAGE_DRAW:
        return identity_icon(what, size)
    import constants
    return _scaled(_PAGE_DRAW[what], constants.COLOR_MUTED, size)


# Every name identity_icon / page_icon draws (what an icon field may say)
ICON_NAMES = tuple(_IDENTITY_DRAW) + tuple(_PAGE_DRAW)
