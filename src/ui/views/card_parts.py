"""What the Friends panel's toy and shocker cards share: their sizes, a
slider the page's scrolling can't move, and the small builders both use
(toy_card.py, shocker_card.py)."""

import math
from typing import Callable, List, Optional, Tuple

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QButtonGroup, QLabel, QPushButton, QSlider, QWidget

import friend_patterns
from ui.layout_helpers import hbox
from ui.theme import PALETTE

CARD_MIN_W = 300                 # two cards side by side need twice this
PERIOD_MIN_S, PERIOD_MAX_S = friend_patterns.PERIOD_MIN_S, friend_patterns.PERIOD_MAX_S


def hue_color(hue: str) -> str:
    return PALETTE[hue][0]


def bigger(w: QWidget, big: bool) -> QWidget:
    if big:
        w.setProperty("big", "true")
    return w


class WheelSafeSlider(QSlider):
    """A slider that scrolling the page can't move: the wheel only works on
    one you clicked first (it has focus); otherwise the page scrolls on. A
    level or shock slider passing under the mouse must never drive
    anyone's toy or shocker."""

    def __init__(self, orientation=Qt.Horizontal, parent=None):
        super().__init__(orientation, parent)
        self.setFocusPolicy(Qt.StrongFocus)

    def wheelEvent(self, event) -> None:
        if self.hasFocus():
            super().wheelEvent(event)
        else:
            event.ignore()


def slider(hue: str, lo: int = 0, hi: int = 1000, big: bool = False,
           vertical: bool = False) -> QSlider:
    s = WheelSafeSlider(Qt.Vertical if vertical else Qt.Horizontal)
    s.setRange(lo, hi)
    s.setProperty("hue", hue)
    s.setCursor(Qt.PointingHandCursor)
    return bigger(s, big)


def small_label(text: str = "", muted: bool = True, big: bool = False) -> QLabel:
    lbl = QLabel(text)
    if muted:
        lbl.setProperty("muted", "true")
    return bigger(lbl, big)


def segmented(labels: List[str], hue: str, on_pick: Callable[[int], None],
         big: bool = False) -> Tuple[QWidget, QButtonGroup]:
    """A small segmented switch: checkable buttons side by side."""
    box = QWidget()
    lay = hbox(0, 0)
    box.setLayout(lay)
    group = QButtonGroup(box)
    group.setExclusive(True)
    for i, text in enumerate(labels):
        b = QPushButton(text)
        b.setCheckable(True)
        b.setProperty("role", "seg")
        b.setProperty("hue", hue)
        b.setProperty("pos", "first" if i == 0 else ("last" if i == len(labels) - 1 else "mid"))
        b.setCursor(Qt.PointingHandCursor)
        bigger(b, big)
        group.addButton(b, i)
        lay.addWidget(b)
    group.button(0).setChecked(True)
    group.idClicked.connect(on_pick)
    return box, group


def mini_button(icon: Optional[QIcon], tip: str, on_click: Optional[Callable[[], None]],
          text: str = "", big: bool = False) -> QPushButton:
    b = QPushButton(text)
    if icon is not None:
        b.setIcon(icon)
        b.setIconSize(QSize(20, 20) if big else QSize(14, 14))
    b.setProperty("role", "mini")
    b.setToolTip(tip)
    b.setCursor(Qt.PointingHandCursor)
    if on_click is not None:
        b.clicked.connect(lambda _=False: on_click())
    return bigger(b, big)


def set_quiet(slider: QSlider, value: int) -> None:
    if slider.value() != value:
        slider.blockSignals(True)
        slider.setValue(value)
        slider.blockSignals(False)


def period_to_slider(period: float) -> int:
    period = max(PERIOD_MIN_S, min(PERIOD_MAX_S, period))
    return round(1000 * math.log(period / PERIOD_MIN_S) / math.log(PERIOD_MAX_S / PERIOD_MIN_S))


def slider_to_period(x: int) -> float:
    return PERIOD_MIN_S * (PERIOD_MAX_S / PERIOD_MIN_S) ** (x / 1000.0)


def fmt_period(period: float) -> str:
    return f"{period:.2f} s" if period < 1 else (f"{period:.1f} s" if period < 10 else f"{period:.0f} s")
