"""Vector icons painted at runtime — independent of emoji-font availability."""

from PySide6.QtCore import Qt, QPointF, QRectF
from PySide6.QtGui import QBrush, QColor, QIcon, QPainter, QPen, QPixmap, QPolygonF

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
