"""The parts PiShock's shocker panel is built from (shocker_card.py): its
tiles (an icon, a value, a caption under them), a vertical slider with two
handles for Random's range, and the pickers that open over the card
(Duration's .1 / .3 / 1-10, Warning, Use Mode)."""

from typing import Callable, List, Optional, Tuple

from PySide6.QtCore import QEvent, QPoint, QRectF, QSize, Qt
from PySide6.QtGui import QBrush, QColor, QPainter, QPen
from PySide6.QtWidgets import QApplication, QFrame, QGridLayout, QLabel, QPushButton, QSlider, QWidget

from ui import theme
from ui.icons import glyph_icon
from ui.layout_helpers import vbox
from ui.views.card_parts import bigger, hue_color

TILE = {False: QSize(62, 58), True: QSize(100, 88)}     # control mode (VR): big
MIDDLE_W = {False: 76, True: 116}                         # Use Mode, STOP, Beep


class Tile(QPushButton):
    """A PiShock tile: an icon on top, a value under it, a caption at the
    bottom (Operate, Duration, Warning, Use Mode ...). `filled` is the
    Operate look: the hue filled in, the way the big Shock button was.
    `hue` "" is the plain middle column (Use Mode, Beep); "stop" is STOP."""

    def __init__(self, caption: str, hue: str = "", filled: bool = False, big: bool = False,
                 wide: bool = False, small_value: bool = False):
        super().__init__()
        self.setProperty("role", "opTile")
        self.setProperty("hue", hue)
        self.setProperty("filled", "true" if filled else "false")
        bigger(self, big)
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedSize(TILE[big])
        if wide:
            self.setFixedWidth(MIDDLE_W[big])
        self._big = big
        lay = vbox(0, 0)
        lay.setContentsMargins(2, 5 if big else 4, 2, 3 if big else 2)
        self.setLayout(lay)
        self._icon = QLabel()
        self._icon.setObjectName("tileIcon")
        self._value = QLabel()
        self._value.setObjectName("tileValue")
        if small_value:
            self._value.setProperty("small", "true")
        self._caption = QLabel(caption)
        self._caption.setObjectName("tileCaption")
        for lbl in (self._icon, self._value, self._caption):
            lbl.setAlignment(Qt.AlignCenter)
            lbl.setAttribute(Qt.WA_TransparentForMouseEvents)
            bigger(lbl, big)
            lay.addWidget(lbl)
        self._value.setVisible(False)

    def set_glyph(self, kind: str, color: str) -> None:
        """Its glyph (ui.icons.glyph_icon) in this colour -- in the dim grey
        while it rests (Qt's own disabled look leaves a white glyph white)."""
        self._glyph = (kind, color)
        self._paint_glyph()

    def _paint_glyph(self) -> None:
        glyph = getattr(self, "_glyph", None)
        if glyph is not None:
            kind, color = glyph
            if not self.isEnabled():
                color = theme.qss_vars()["dim"]
            px = 26 if self._big else 18
            self._icon.setPixmap(glyph_icon(kind, color, 20).pixmap(QSize(px, px)))

    def changeEvent(self, event) -> None:  # noqa: N802
        if event.type() == QEvent.EnabledChange:
            self._paint_glyph()         # resting: the glyph greys with the text
        super().changeEvent(event)

    def set_value(self, text: str) -> None:
        if self._value.text() != text:
            self._value.setText(text)
        self._value.setVisible(bool(text))

    def value(self) -> str:
        return self._value.text()


class RangeSlider(QWidget):
    """Random's min and max: two handles on one vertical groove, the range
    between them filled. Mirrors two sliders the card keeps (hidden), so
    its maths reads `lo` / `hi` like any other slider."""

    def __init__(self, hue: str, lo: QSlider, hi: QSlider, big: bool):
        super().__init__()
        self._hue, self._lo, self._hi, self._big = hue, lo, hi, big
        self._drag: Optional[QSlider] = None
        self.setFixedWidth(34 if big else 22)
        self.setMinimumHeight(120)
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip("Random: every shock picks a strength between the two handles")
        for s in (lo, hi):
            s.valueChanged.connect(lambda _v: self.update())

    def _span(self) -> Tuple[float, float, float]:
        r = 14.0 if self._big else 7.0
        return r, r + 1, self.height() - r - 1          # radius, top, bottom

    def _y(self, v: int) -> float:
        _r, top, bottom = self._span()
        lo, hi = self._lo.minimum(), self._lo.maximum()
        f = 0.0 if hi <= lo else (v - lo) / (hi - lo)
        return bottom - (bottom - top) * f

    def _v(self, y: float) -> int:
        _r, top, bottom = self._span()
        lo, hi = self._lo.minimum(), self._lo.maximum()
        f = 0.0 if bottom <= top else max(0.0, min(1.0, (bottom - y) / (bottom - top)))
        return round(lo + f * (hi - lo))

    def paintEvent(self, _event) -> None:  # noqa: N802
        v = theme.qss_vars()
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r, top, bottom = self._span()
        cx = self.width() / 2
        gw = 12.0 if self._big else 8.0
        p.setPen(QPen(QColor(v["line"]), 1))
        p.setBrush(QBrush(QColor(v["well"])))
        p.drawRoundedRect(QRectF(cx - gw / 2, top - r, gw, bottom - top + 2 * r), gw / 2, gw / 2)
        a, b = sorted((self._y(self._lo.value()), self._y(self._hi.value())))
        col = QColor(hue_color(self._hue) if self.isEnabled() else v["dim"])
        p.setPen(Qt.NoPen)
        p.setBrush(QBrush(col))
        p.drawRoundedRect(QRectF(cx - gw / 2 + 1, a, gw - 2, b - a), gw / 2 - 1, gw / 2 - 1)
        for y in (a, b):
            p.drawEllipse(QRectF(cx - r, y - r, 2 * r, 2 * r))
        p.end()

    def mousePressEvent(self, event) -> None:  # noqa: N802
        y = event.position().y()
        self._drag = min((self._lo, self._hi), key=lambda s: abs(self._y(s.value()) - y))
        self._drag.setValue(self._v(y))

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        if self._drag is not None:
            self._drag.setValue(self._v(event.position().y()))

    def mouseReleaseEvent(self, _event) -> None:  # noqa: N802
        self._drag = None


class Picker(QFrame):
    """PiShock's pickers -- Duration's round .1 / .3 / 1-10, Warning's and
    Use Mode's choices -- opened over the card. A child of the card, not a
    popup window: a VR overlay that captures OGP's window wouldn't show a
    window of its own. A pick, the tile that opened it, Esc or a click
    anywhere else closes it."""

    def __init__(self, host: QWidget, opener: QWidget, options: List[Tuple[str, bool]],
                 current: int, cols: int, on_pick: Callable[[int], None], hue: str,
                 big: bool, wide: bool = False):
        super().__init__(host)
        self.setObjectName("picker")
        self.setProperty("hue", hue)
        self._opener, self._on_pick = opener, on_pick
        grid = QGridLayout(self)
        m = 8 if big else 6
        grid.setContentsMargins(m, m, m, m)
        grid.setSpacing(8 if big else 6)
        self.buttons: List[QPushButton] = []
        for i, (text, enabled) in enumerate(options):
            b = QPushButton(text)
            b.setProperty("role", "pick")
            b.setProperty("hue", hue)
            if wide:
                b.setProperty("wide", "true")
            bigger(b, big)
            b.setCheckable(True)
            b.setChecked(i == current)
            b.setEnabled(enabled)
            b.setCursor(Qt.PointingHandCursor)
            b.clicked.connect(lambda _=False, k=i: self._pick(k))
            grid.addWidget(b, i // cols, i % cols)
            self.buttons.append(b)
        QApplication.instance().installEventFilter(self)

    def _pick(self, i: int) -> None:
        self.close_picker()
        self._on_pick(i)

    def place(self, pos: QPoint) -> None:
        """Show it at `pos` in the card, moved in to stay inside it."""
        self.adjustSize()
        host = self.parentWidget()
        x = max(0, min(pos.x(), host.width() - self.width()))
        y = max(0, min(pos.y(), host.height() - self.height()))
        self.move(x, y)
        self.raise_()
        self.show()

    def close_picker(self) -> None:
        app = QApplication.instance()
        if app is not None:
            app.removeEventFilter(self)
        self.hide()
        self.deleteLater()

    def eventFilter(self, obj, event) -> bool:  # noqa: N802
        kind = event.type()
        if kind == QEvent.KeyPress and event.key() == Qt.Key_Escape:
            self.close_picker()
            return True
        if kind == QEvent.MouseButtonPress and isinstance(obj, QWidget):
            inside = self.rect().contains(self.mapFromGlobal(event.globalPosition().toPoint()))
            if not inside:
                on_opener = self._opener.rect().contains(
                    self._opener.mapFromGlobal(event.globalPosition().toPoint()))
                self.close_picker()
                return on_opener          # the opener's own press only closes it
        return False
