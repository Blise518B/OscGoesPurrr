"""The avatar menu's slots on the Avatar Remote page (Blise's design,
2026-10-29): a small circle in a card's top bar -- and in a category's
header -- that says which of Avatar Remote ▸'s seven Toggles / Radials it
sits in, and the radial picker it opens, laid out like VRChat's own menu:
Back at the top, 1-7 around it clockwise, each saying what has it now.

A click on a number gives that slot to the card (or category), taking it
from whatever had it; a click on one it already has frees it. A category
can sit in both sets: the middle of the picker switches between Toggles
and Radials.

The picker is a child of the window, never a popup window (a VR overlay
capturing the window doesn't show those), and closes on Back, Esc or a
click anywhere else."""

import math
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from PySide6.QtCore import QEvent, QPoint, QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QApplication, QPushButton, QWidget

import param_board as pb
from ui import theme as _theme

_LETTER = {"toggle": "T", "radial": "R"}
_NAMES = {"toggle": ("Toggle", "Toggles"), "radial": ("Radial", "Radials")}

R_OUT, R_IN = 104.0, 40.0        # the ring
_GAP_DEG = 2.0                    # between two wedges
_CAPTION_H = 26
SIZE = int(2 * R_OUT) + 12


def slots_text(taken: Sequence[Tuple[str, int]], both: bool) -> str:
    """A circle's text: "1·5", or for a category "T2·R1"."""
    return "·".join((_LETTER[menu] if both else "") + str(i + 1) for menu, i in taken)


class SlotDot(QPushButton):
    """The circle in a top bar: a plain ring while it sits in no slot, else its
    slot numbers. `key` is the slot's "c:<id>" / "g:<id>", `menus` the
    sets it can sit in."""

    def __init__(self, key: str, menus: Sequence[str]):
        super().__init__()
        self.key = key
        self.menus = tuple(menus)
        self.setObjectName("slotDot")
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedSize(18, 18)
        self.setFocusPolicy(Qt.NoFocus)
        self.set_slots([])

    def set_slots(self, taken: Sequence[Tuple[str, int]]) -> None:
        taken = [(m, i) for m, i in taken if m in self.menus]
        text = slots_text(taken, len(self.menus) > 1)
        if self.text() != text:
            self.setText(text)
            # a circle while empty, as wide as its numbers once it has some
            self.setFixedWidth(max(18, self.fontMetrics().horizontalAdvance(text) + 12))
        state = "true" if taken else "false"
        if self.property("set") != state:
            self.setProperty("set", state)
            self.style().unpolish(self)
            self.style().polish(self)
        where = ", ".join(f"{_NAMES[m][0]} {i + 1}" for m, i in taken)
        self.setToolTip(
            f"In your avatar menu: Avatar Remote ▸ {where} - click to change" if taken else
            "Put this in your avatar menu: click, then pick one of Avatar Remote ▸'s seven "
            + ("toggles or radials" if len(self.menus) > 1 else
               "toggles" if self.menus == ("toggle",) else "radials"))


class SlotRadial(QWidget):
    """The picker. `on_pick(menu, index, key)` when a number is clicked."""

    def __init__(self, parent: QWidget, on_pick: Callable[[str, int, str], None]):
        super().__init__(parent)
        self._on_pick = on_pick
        self._anchor: Optional[SlotDot] = None
        self._key = ""
        self._menus: Tuple[str, ...] = ("toggle",)
        self._menu = "toggle"
        self._title = ""
        self._slots: Dict[str, List[Optional[str]]] = pb.no_slots()
        self._labels: Dict[str, str] = {}
        self._hover = -1                  # wedge under the pointer (0 = Back), -2 the middle
        self.setObjectName("slotRadial")
        self.setFixedSize(SIZE, SIZE + _CAPTION_H)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.StrongFocus)
        self.hide()

    # -- open / close ----------------------------------------------------------

    @property
    def key(self) -> str:
        return self._key if self.isVisible() else ""

    def open_for(self, anchor: SlotDot, title: str, board: Dict[str, Any]) -> None:
        self._anchor = anchor
        self._key = anchor.key
        self._menus = anchor.menus
        taken = [m for m, _i in pb.slots_of(board, anchor.key)]
        self._menu = taken[0] if taken and taken[0] in self._menus else self._menus[0]
        self._title = title
        self.set_board(board)
        host = self.parentWidget()
        below = anchor.mapTo(host, QPoint(anchor.width() // 2, anchor.height() + 4))
        x = max(4, min(below.x() - self.width() // 2, host.width() - self.width() - 4))
        y = below.y()
        if y + self.height() > host.height() - 4:            # no room under it: above
            y = anchor.mapTo(host, QPoint(0, 0)).y() - self.height() - 4
        self.move(x, max(4, y))
        self.show()
        self.raise_()
        self.setFocus()
        QApplication.instance().installEventFilter(self)

    def close_picker(self) -> None:
        if self.isVisible():
            self.hide()
        app = QApplication.instance()
        if app is not None:
            app.removeEventFilter(self)
        self._anchor = None

    def set_board(self, board: Dict[str, Any]) -> None:
        """What has each slot now (after a pick, or anything else)."""
        self._slots = board.get("slots") or pb.no_slots()
        self._labels = {key: pb.slot_label(board, key)
                        for menu in pb.SLOT_MENUS for key in self._slots.get(menu) or [] if key}
        self.update()

    def eventFilter(self, obj, ev):  # noqa: N802
        if ev.type() == QEvent.MouseButtonPress and self.isVisible():
            target = obj if isinstance(obj, QWidget) else None
            inside = target is not None and (target is self or self.isAncestorOf(target))
            on_anchor = False
            try:
                on_anchor = target is not None and target is self._anchor
            except RuntimeError:
                pass
            if not inside and not on_anchor:
                self.close_picker()          # the circle's own click toggles it
        return False

    def keyPressEvent(self, ev) -> None:  # noqa: N802
        if ev.key() == Qt.Key_Escape:
            self.close_picker()
        else:
            super().keyPressEvent(ev)

    # -- geometry --------------------------------------------------------------

    def _centre(self) -> QPointF:
        return QPointF(self.width() / 2.0, _CAPTION_H + SIZE / 2.0)

    def _hit(self, pos: QPointF) -> int:
        """0 Back, 1-7 a slot, -2 the middle, -1 nothing."""
        c = self._centre()
        dx, dy = pos.x() - c.x(), pos.y() - c.y()
        r = math.hypot(dx, dy)
        if r < R_IN:
            return -2
        if r > R_OUT:
            return -1
        angle = math.degrees(math.atan2(dx, -dy)) % 360.0     # clockwise from the top
        return int(round(angle / 45.0)) % 8

    def _wedge(self, k: int) -> QPainterPath:
        c = self._centre()
        mid = 90.0 - 45.0 * k                                 # Qt: counter-clockwise from 3 o'clock
        start, span = mid - 22.5 + _GAP_DEG / 2, 45.0 - _GAP_DEG
        outer = QRectF(c.x() - R_OUT, c.y() - R_OUT, 2 * R_OUT, 2 * R_OUT)
        inner = QRectF(c.x() - R_IN, c.y() - R_IN, 2 * R_IN, 2 * R_IN)
        path = QPainterPath()
        path.arcMoveTo(outer, start)
        path.arcTo(outer, start, span)
        path.arcTo(inner, start + span, -span)
        path.closeSubpath()
        return path

    # -- mouse -----------------------------------------------------------------

    def mouseMoveEvent(self, ev) -> None:  # noqa: N802
        hit = self._hit(ev.position())
        if hit != self._hover:
            self._hover = hit
            self.setCursor(Qt.PointingHandCursor if hit != -1 and (
                hit != -2 or len(self._menus) > 1) else Qt.ArrowCursor)
            self.update()

    def leaveEvent(self, _ev) -> None:  # noqa: N802
        self._hover = -1
        self.update()

    def mousePressEvent(self, ev) -> None:  # noqa: N802
        if ev.button() != Qt.LeftButton:
            return
        hit = self._hit(ev.position())
        if hit == 0:
            self.close_picker()
        elif hit == -2 and len(self._menus) > 1:
            upper = ev.position().y() < self._centre().y()
            self._menu = self._menus[0] if upper else self._menus[1]
            self.update()
        elif hit > 0:
            self._on_pick(self._menu, hit - 1, self._key)
        ev.accept()

    # -- paint -----------------------------------------------------------------

    def paintEvent(self, _ev) -> None:  # noqa: N802
        v = _theme.qss_vars()
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        p.setPen(QPen(QColor(v["line"]), 1.0))
        p.setBrush(QColor(v["panel"]))
        p.drawRoundedRect(QRectF(0.5, 0.5, self.width() - 1.0, self.height() - 1.0), 12, 12)
        base = QFont(self.font())
        # the caption: what is being placed, and in which set
        cap = QFont(base)
        cap.setPixelSize(12)
        cap.setBold(True)
        p.setFont(cap)
        p.setPen(QColor(v["txt"]))
        what = _NAMES[self._menu][1]
        title = QFontMetrics(cap).elidedText(self._title, Qt.ElideRight, self.width() - 110)
        p.drawText(QRectF(10, 4, self.width() - 20, _CAPTION_H - 6),
                   Qt.AlignLeft | Qt.AlignVCenter, title)
        small = QFont(base)
        small.setPixelSize(11)
        p.setFont(small)
        p.setPen(QColor(v["muted"]))
        p.drawText(QRectF(10, 4, self.width() - 20, _CAPTION_H - 6),
                   Qt.AlignRight | Qt.AlignVCenter, f"Avatar Remote ▸ {what}")
        c = self._centre()
        num = QFont(base)
        num.setPixelSize(16)
        num.setBold(True)
        taken = self._slots.get(self._menu) or []
        for k in range(8):
            owner = taken[k - 1] if k and k - 1 < len(taken) else None
            mine = bool(owner) and owner == self._key
            fill = v["tint"] if mine else (v["hover"] if k == self._hover else v["well"])
            p.setPen(QPen(QColor(v["accent"] if mine else v["line"]), 1.2 if mine else 1.0))
            p.setBrush(QColor(fill))
            p.drawPath(self._wedge(k))
            angle = math.radians(-90.0 + 45.0 * k)
            r = (R_IN + R_OUT) / 2.0
            x, y = c.x() + r * math.cos(angle), c.y() + r * math.sin(angle)
            if k == 0:
                p.setFont(small)
                p.setPen(QColor(v["muted"]))
                p.drawText(QRectF(x - 30, y - 9, 60, 18), Qt.AlignCenter, "Back")
                continue
            label = self._labels.get(owner, "") if owner else ""
            p.setFont(num)
            p.setPen(QColor(v["accent"] if mine else v["txt"]))
            p.drawText(QRectF(x - 20, y - (16 if label else 10), 40, 20), Qt.AlignCenter, str(k))
            if label:
                p.setFont(small)
                p.setPen(QColor(v["accent"] if mine else v["muted"]))
                label = QFontMetrics(small).elidedText(label, Qt.ElideRight, 56)
                p.drawText(QRectF(x - 30, y + 2, 60, 16), Qt.AlignCenter, label)
        # the middle: which set (a category switches it here)
        p.setPen(QPen(QColor(v["line"]), 1.0))
        p.setBrush(QColor(v["hover"] if self._hover == -2 and len(self._menus) > 1 else v["panel"]))
        p.drawEllipse(c, R_IN - 4, R_IN - 4)
        p.setFont(small)
        if len(self._menus) > 1:
            for i, menu in enumerate(self._menus):
                on = menu == self._menu
                f = QFont(small)
                f.setBold(on)
                p.setFont(f)
                p.setPen(QColor(v["accent"] if on else v["dim"]))
                p.drawText(QRectF(c.x() - 34, c.y() - 17 + i * 16, 68, 16), Qt.AlignCenter,
                           _NAMES[menu][1])
        else:
            p.setPen(QColor(v["muted"]))
            p.drawText(QRectF(c.x() - 34, c.y() - 9, 68, 18), Qt.AlignCenter,
                       _NAMES[self._menu][0])
        p.end()
