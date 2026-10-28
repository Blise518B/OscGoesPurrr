"""The Suits page's pieces, in Avatar Remote's card design (like the
Shockers page): the inspector cards that open beside the body for what's
picked on her -- the bHaptics part in orange, the OWO muscle in purple, a
Vive tracker in blue -- each with whether the avatar has its contacts, the
lines from her to them (Leaders), the rows of chips that list every part
and muscle with its setting, and the contact check's row of pills.

A value is a slider with the number written out (pishock_cards.ValueSlider),
never a spin box. Cards only draw and call back with primitive values;
suits.py wires them to the controller.
"""

from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QFrame, QLabel, QPushButton, QWidget

import body_map
from ui import theme as _theme
from ui.layout_helpers import FlowLayout, hbox, vbox
from ui.theme import BHAPTICS_HUE, OWO_HUE, TRACKERS_HUE
from ui.views.pishock_cards import ValueSlider, mini_button, state_pill
from ui.widgets import ToggleSwitch

INSPECTOR_W = 250
TEST_PERCENT = 10           # owo_engine's test level (the button says so)


def _pct(v: float) -> str:
    return f"{v:.0f} %"


def _card(hue: str) -> Tuple[QFrame, Any]:
    card = QFrame()
    card.setObjectName("paramCard")
    card.setProperty("hue", hue)
    card.setFixedWidth(INSPECTOR_W)
    lay = vbox(0, 6)
    lay.setContentsMargins(10, 8, 8, 10)
    card.setLayout(lay)
    return card, lay


def _head(lay, tag_text: str, hue: str) -> QLabel:
    row = hbox(0, 6)
    title = QLabel("")
    title.setObjectName("paramLabel")
    title.setWordWrap(True)
    row.addWidget(title, 1)
    tag = QLabel(tag_text)
    tag.setObjectName("suitTag")
    tag.setProperty("hue", hue)
    row.addWidget(tag, 0, Qt.AlignTop)
    lay.addLayout(row)
    return title


def _check(lay) -> QLabel:
    """The card's contact check: a pill under its title, hidden until there
    is an avatar to check."""
    pill = state_pill("", "idle")
    pill.hide()
    lay.addWidget(pill, 0, Qt.AlignLeft)
    return pill


def _set_check(pill: QLabel, text: str, tone: str) -> None:
    pill.setVisible(bool(text))
    if text:
        pill.setText(text)
        pill.setProperty("tone", tone)
        pill.style().unpolish(pill)
        pill.style().polish(pill)


def _hint() -> QLabel:
    hint = QLabel("")
    hint.setObjectName("cardHint")
    hint.setProperty("muted", "true")
    hint.setWordWrap(True)
    return hint


class PartCard(QFrame):
    """The bHaptics part picked on the body: on or off, how strong a full
    touch gets there, and a buzz on all its motors."""

    def __init__(self, on_enabled: Callable[[str, bool], None],
                 on_strength: Callable[[str, int], None], on_test: Callable[[str], None]):
        super().__init__()
        self.part = "VestFront"
        self._filling = False
        self.frame, lay = _card(BHAPTICS_HUE)
        outer = vbox(0, 0)
        outer.addWidget(self.frame)
        self.setLayout(outer)
        self.title = _head(lay, "bHaptics", BHAPTICS_HUE)
        self.check = _check(lay)
        self.on = ToggleSwitch("On")
        self.on.toggled.connect(
            lambda v: None if self._filling else on_enabled(self.part, bool(v)))
        lay.addWidget(self.on)
        self.strength = ValueSlider(
            "Strength", 0, 100, 100, 5, _pct, hue=BHAPTICS_HUE,
            on_change=lambda v: on_strength(self.part, int(v)),
            tip="How strong this part gets at a full touch, before the sidebar's strength.")
        lay.addWidget(self.strength)
        self.test = mini_button("Feel it", "A gentle buzz on every motor of this part.")
        self.test.clicked.connect(lambda _=False: on_test(self.part))
        lay.addWidget(self.test, 0, Qt.AlignLeft)
        self.hint = _hint()
        lay.addWidget(self.hint)

    def show_part(self, part: str, cfg: Dict[str, Any]) -> None:
        if part != self.part:
            self.strength.flush()            # a drag still saving belongs to the old part
        self.part = part
        on = bool(cfg.get("enabled", True))
        self._filling = True
        try:
            self.title.setText(body_map.display_name(part))
            self.on.setChecked(on)
            self.strength.set_value(float(cfg.get("intensity", 100)))
        finally:
            self._filling = False
        self.strength.setEnabled(on)
        self.test.setEnabled(on)
        n = body_map.NODE_COUNTS.get(part, 0)
        self.hint.setText(
            f"{n} motors. Press and hold a dot to feel just that one."
            if on else "Off: this part never buzzes, whatever touches it.")

    def set_check(self, found: Optional[int]) -> None:
        """How many of the part's contacts the avatar has (None: unknown)."""
        n = body_map.NODE_COUNTS.get(self.part, 0)
        if found is None:
            _set_check(self.check, "", "idle")
        elif found >= n:
            _set_check(self.check, f"On your avatar: all {n} contacts", "ok")
        elif found:
            _set_check(self.check, f"On your avatar: {found} of {n} contacts", "warn")
        else:
            _set_check(self.check, "Not on your avatar", "err")


class MuscleCard(QFrame):
    """The OWO muscle picked on the body (or the one around the picked
    dot): on or off, its top, a short test, and what it plays now."""

    def __init__(self, on_enabled: Callable[[str, bool], None],
                 on_top: Callable[[str, int], None], on_test: Callable[[str], None]):
        super().__init__()
        self.muscle: Optional[str] = "Pectoral_R"
        self._filling = False
        self.frame, lay = _card(OWO_HUE)
        outer = vbox(0, 0)
        outer.addWidget(self.frame)
        self.setLayout(outer)
        self.title = _head(lay, "OWO", OWO_HUE)
        self.check = _check(lay)
        self.controls = QWidget()
        cl = vbox(0, 6)
        self.controls.setLayout(cl)
        self.on = ToggleSwitch("On")
        self.on.toggled.connect(
            lambda v: None if self._filling or self.muscle is None
            else on_enabled(self.muscle, bool(v)))
        cl.addWidget(self.on)
        self.top = ValueSlider(
            "Top", 0, 100, 100, 5, _pct, hue=OWO_HUE,
            on_change=lambda v: None if self.muscle is None else on_top(self.muscle, int(v)),
            tip="A full touch on this muscle goes this high -- still under the ceiling.")
        cl.addWidget(self.top)
        self.ceiling = _hint()
        cl.addWidget(self.ceiling)
        row = hbox(0, 8)
        self.test = mini_button(f"Feel it ({TEST_PERCENT} %)",
                                f"One short, gentle sensation on this muscle ({TEST_PERCENT} %, "
                                "or its top if that's lower).")
        self.test.clicked.connect(
            lambda _=False: None if self.muscle is None else on_test(self.muscle))
        row.addWidget(self.test)
        self.live = QLabel("")
        self.live.setProperty("role", "live")
        row.addWidget(self.live, 1)
        cl.addLayout(row)
        lay.addWidget(self.controls)
        self.hint = _hint()
        lay.addWidget(self.hint)

    def show_muscle(self, muscle: Optional[str], cfg: Dict[str, Any], ceiling: int,
                    follows_bhaptics: bool, dots_shown: bool = True) -> None:
        if muscle != self.muscle:
            self.top.flush()
            self.live.setText("")
        self.muscle = muscle
        self.controls.setVisible(muscle is not None)
        if muscle is None:
            _set_check(self.check, "", "idle")
            self.title.setText("No OWO muscle here")
            self.hint.setText("OWO has none on the head, the hands or the feet.")
            return
        on = bool(cfg.get("enabled", True))
        self._filling = True
        try:
            self.title.setText(body_map.display_name(muscle))
            self.on.setChecked(on)
            self.top.set_value(float(cfg.get("max", 100)))
        finally:
            self._filling = False
        self.top.setEnabled(on)
        self.test.setEnabled(on)
        self.ceiling.setText(f"Never above the ceiling ({ceiling} %).")
        n = len(body_map.OWO_REGIONS[muscle][1])
        if not on:
            hint = "Off: this muscle never plays."
        elif not follows_bhaptics:
            hint = "Plays from your avatar's OWO contacts and zone routes."
        elif dots_shown:
            hint = (f"Any touch on the {n} bHaptics dots inside it plays it too; each "
                    "dot still buzzes on its own on the bHaptics suit.")
        else:
            hint = ("Plays from your avatar's OWO contacts, zone routes, and any "
                    "bHaptics contact your avatar has inside it.")
        self.hint.setText(hint)

    def set_check(self, own: Optional[bool], via: int = 0) -> None:
        """Whether the avatar has the muscle's OWO contact (None: unknown),
        and how many bHaptics contacts inside it play it too."""
        if own is None or self.muscle is None:
            _set_check(self.check, "", "idle")
        elif own:
            _set_check(self.check, "On your avatar: its OWO contact", "ok")
        elif via:
            _set_check(self.check, f"Played by {via} bHaptics contacts", "ok")
        else:
            _set_check(self.check, "No contact for it on your avatar", "err")

    def show_level(self, percent: Optional[int]) -> None:
        self.live.setText(f"Playing {percent} %" if percent else "")


class TrackerCard(QFrame):
    """A Vive tracker picked on the body (tracker haptics): on or off, how
    strong it buzzes, a test buzz, and whether its contacts are on the
    avatar."""

    def __init__(self, on_enabled: Callable[[str, bool], None],
                 on_strength: Callable[[str, int], None], on_test: Callable[[str], None]):
        super().__init__()
        self.tracker: Optional[str] = None
        self._filling = False
        self.frame, lay = _card(TRACKERS_HUE)
        outer = vbox(0, 0)
        outer.addWidget(self.frame)
        self.setLayout(outer)
        self.title = _head(lay, "Tracker", TRACKERS_HUE)
        self.check = _check(lay)
        self.on = ToggleSwitch("On")
        self.on.toggled.connect(
            lambda v: None if self._filling or self.tracker is None
            else on_enabled(self.tracker, bool(v)))
        lay.addWidget(self.on)
        self.strength = ValueSlider(
            "Strength", 0, 100, 100, 5, _pct, hue=TRACKERS_HUE,
            on_change=lambda v: None if self.tracker is None else on_strength(self.tracker, int(v)),
            tip="How strong this tracker buzzes at a full touch, before the sidebar's strength.")
        lay.addWidget(self.strength)
        self.test = mini_button("Feel it", "A short buzz on this tracker.")
        self.test.clicked.connect(
            lambda _=False: None if self.tracker is None else on_test(self.tracker))
        lay.addWidget(self.test, 0, Qt.AlignLeft)
        self.hint = _hint()
        lay.addWidget(self.hint)

    def show_tracker(self, key: str, name: str, cfg: Dict[str, Any]) -> None:
        """`cfg`: enabled, intensity, and contacts as [found, total] (or
        nothing, when there's no avatar to check)."""
        if key != self.tracker:
            self.strength.flush()
        self.tracker = key
        on = bool(cfg.get("enabled", True))
        self._filling = True
        try:
            self.title.setText(f"{name} tracker")
            self.on.setChecked(on)
            self.strength.set_value(float(cfg.get("intensity", 100)))
        finally:
            self._filling = False
        self.strength.setEnabled(on)
        self.test.setEnabled(on)
        contacts = cfg.get("contacts")
        if contacts:
            found, total = contacts
            if found >= total:
                _set_check(self.check, "On your avatar: its contact" if total == 1
                           else f"On your avatar: all {total} contacts", "ok")
            elif found:
                _set_check(self.check, f"On your avatar: {found} of {total} contacts", "warn")
            else:
                _set_check(self.check, "Not on your avatar", "err")
        else:
            _set_check(self.check, "", "idle")
        self.hint.setText("Buzzes with the contacts it's set to follow." if on
                          else "Off: this tracker never buzzes.")


class CheckRow(QWidget):
    """The contact check's summary: a pill per thing you have ("Vest
    40 / 40", "Sleeves 0 / 12") and where the check looked."""

    def __init__(self):
        super().__init__()
        lay = vbox(0, 4)
        self.setLayout(lay)
        self._pills = QWidget()
        self._flow = FlowLayout(margin=0, h_spacing=6, v_spacing=6)
        self._pills.setLayout(self._flow)
        lay.addWidget(self._pills)
        self.note = _hint()
        lay.addWidget(self.note)
        self.pills: List[QLabel] = []

    def set_items(self, items: List[Tuple[str, str]], note: str) -> None:
        """[(text, tone)] -- "ok", "warn" or "err" -- and the note under them."""
        if [(p.text(), p.property("tone")) for p in self.pills] != list(items):
            while self._flow.count():
                w = self._flow.takeAt(0).widget()
                if w is not None:
                    w.deleteLater()
            self.pills = [state_pill(text, tone) for text, tone in items]
            for pill in self.pills:
                self._flow.addWidget(pill)
        self._pills.setVisible(bool(items))
        self.note.setText(note)


class Leaders(QWidget):
    """The lines from what's picked on her to its card, drawn over the body
    card's stage and never in the way of a click. `lines()` gives them, in
    this widget's coordinates: [(hue, start on her, end at the card)]."""

    def __init__(self, parent: QWidget, lines: Callable[[], List[Tuple[str, QPointF, QPointF]]]):
        super().__init__(parent)
        self._lines = lines
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WA_NoSystemBackground, True)

    def paintEvent(self, _event) -> None:  # noqa: N802
        lines = self._lines()
        if not lines:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        for hue, start, end in lines:
            color = QColor(_theme.tri(hue)[0])
            elbow = QPointF(start.x() + 12, start.y())
            p.setPen(QPen(color, 1.5))
            p.drawLine(start, elbow)
            p.drawLine(elbow, end)
            p.setPen(Qt.NoPen)
            p.setBrush(color)
            p.drawEllipse(start, 2.5, 2.5)
            p.drawEllipse(end, 3.0, 3.0)
        p.end()


class Stage(QWidget):
    """Her and the inspector column side by side, with the Leaders drawn
    over both."""

    def __init__(self, body: QWidget, column, lines: Callable[[], List[Tuple[str, QPointF, QPointF]]]):
        super().__init__()
        row = hbox(0, 16)
        self.setLayout(row)
        row.addWidget(body, 1)
        row.addLayout(column)
        self.leaders = Leaders(self, lines)

    def resizeEvent(self, event) -> None:  # noqa: N802
        self.leaders.setGeometry(self.rect())
        self.leaders.raise_()
        super().resizeEvent(event)


class Swatch(QWidget):
    """The legend's mark, drawn as the body draws it (the font has none of
    these glyphs): "dot" a bHaptics motor, "patch" an OWO muscle, "puck" a
    tracker, "missing" the contact check's dashed ring. Coloured at paint
    time, so it follows the colour picker."""

    def __init__(self, hue: str, shape: str):
        super().__init__()
        self._hue, self._shape = hue, shape
        self.setFixedSize(16, 16)

    def paintEvent(self, _event) -> None:  # noqa: N802
        vib, mid, tint = _theme.tri(self._hue)
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(2.5, 2.5, 11, 11)
        well = QColor(_theme.CHROME["well"])
        if self._shape == "patch":
            p.setPen(QPen(QColor(mid), 1.3))
            p.setBrush(QColor(tint))
            p.drawRoundedRect(r, 3, 3)
        elif self._shape == "missing":
            p.setPen(QPen(QColor(vib), 1.3, Qt.DashLine))
            p.setBrush(Qt.NoBrush)
            p.drawEllipse(r.adjusted(-1.5, -1.5, 1.5, 1.5))
        else:
            p.setPen(QPen(QColor(vib), 1.4))
            p.setBrush(well)
            p.drawEllipse(r if self._shape == "dot" else r.adjusted(-1.5, -1.5, 1.5, 1.5))
            if self._shape == "puck":
                p.setPen(Qt.NoPen)
                p.setBrush(QColor(mid))
                p.drawEllipse(r.center(), 2.6, 2.6)
        p.end()


class ChipRow(QWidget):
    """Every part (or muscle) as a chip with its setting -- "Left arm 80 %",
    "Head off" -- the picked one checked. A click picks it."""

    def __init__(self, names: Iterable[str], hue: str, on_pick: Callable[[str], None],
                 labels: Optional[Dict[str, str]] = None):
        super().__init__()
        flow = FlowLayout(margin=0, h_spacing=6, v_spacing=6)
        self.setLayout(flow)
        self.chips: Dict[str, QPushButton] = {}
        names = list(names)
        self._labels = {name: (labels or {}).get(name) or body_map.display_name(name)
                        for name in names}
        for name in names:
            chip = QPushButton(self._labels[name])
            chip.setCheckable(True)
            chip.setProperty("role", "chip")
            chip.setProperty("hue", hue)
            chip.setCursor(Qt.PointingHandCursor)
            chip.clicked.connect(lambda _=False, n=name: on_pick(n))
            flow.addWidget(chip)
            self.chips[name] = chip

    def set_values(self, values: Dict[str, Tuple[bool, int]]) -> None:
        """{name: (on, percent)}."""
        for name, chip in self.chips.items():
            on, pct = values.get(name, (True, 100))
            chip.setText(f"{self._labels[name]}  {pct} %" if on
                         else f"{self._labels[name]}  off")

    def set_picked(self, name: Optional[str]) -> None:
        self.set_checked({name})

    def set_checked(self, names: Iterable[Optional[str]]) -> None:
        names = set(names)
        for n, chip in self.chips.items():
            chip.setChecked(n in names)

    def set_shown(self, names: Iterable[str]) -> None:
        """Only these chips (the parts you have)."""
        names = set(names)
        for n, chip in self.chips.items():
            chip.setVisible(n in names)
