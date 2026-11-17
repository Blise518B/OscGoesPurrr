"""Shock, Vibrate and Beep as switch chips (lit: on, grey: off) -- on a
shocker's card on the Shockers page, that shocker's own switches
(PiShockEngine refuses an op switched off, whoever sends it). Chips rather
than labelled switches: three of them fit across a shocker's card."""

from typing import Callable, Dict

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QPushButton, QWidget

from ui.layout_helpers import hbox
from ui.theme import FRIEND_SHOCK_HUE as SHOCK_HUE     # the shockers' yellow
from ui.tooltips import explain

OPS = (("shock", "Shock"), ("vibrate", "Vibrate"), ("beep", "Beep"))


class OpChips(QWidget):
    """Switch chips in one row: `items` are (key, label); each click flips
    one and calls on_toggle(key, on). `tips` is key -> (title, text), the
    hover explanation (its first sentence is what help mode shows)."""

    def __init__(self, on_toggle: Callable[[str, bool], None],
                 tips: Dict[str, tuple], items=OPS, hue: str = SHOCK_HUE, label: str = ""):
        super().__init__()
        self._on_toggle = on_toggle
        row = hbox(0, 4)
        self.setLayout(row)
        if label:
            name = QLabel(label)
            name.setProperty("muted", "true")
            row.addWidget(name)
            row.addSpacing(2)
        self.chips: Dict[str, QPushButton] = {}
        for key, label in items:
            chip = QPushButton(label)
            chip.setProperty("role", "chip")
            chip.setProperty("hue", hue)
            chip.setCheckable(True)
            chip.setChecked(True)
            chip.setCursor(Qt.PointingHandCursor)
            chip.toggled.connect(lambda on, k=key: self._on_toggle(k, bool(on)))
            if key in tips:
                explain(chip, *tips[key])
            row.addWidget(chip)
            self.chips[key] = chip
        row.addStretch(1)

    def set_on(self, on: Dict[str, bool]) -> None:
        """Show each chip as `on` says, without calling back."""
        for key, chip in self.chips.items():
            want = bool(on.get(key, True))
            if chip.isChecked() != want:
                chip.blockSignals(True)
                chip.setChecked(want)
                chip.blockSignals(False)


# The hover explanations of a shocker card's own switches.
SHOCKER_OP_TIPS = {
    "shock": ("Shock on this shocker",
              "Off: no shock reaches this shocker, whoever sends it - behaviours, friends, "
              "the web remote, your avatar's menu. A shock asked for is dropped, not turned "
              "into a vibrate. Friends see their Shock button greyed."),
    "vibrate": ("Vibrate on this shocker",
                "Off: no vibrate reaches this shocker, whoever sends it. A shock that isn't "
                "armed goes out as a vibrate, so it stops too, and a friend's warning beeps "
                "instead."),
    "beep": ("Beep on this shocker",
             "Off: no beep reaches this shocker, whoever sends it. A friend's warning then "
             "vibrates."),
}
