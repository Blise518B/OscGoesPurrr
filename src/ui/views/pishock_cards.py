"""The Shockers page's pieces, in Avatar Remote's card design
(param_cards.py): a card per shocker with its own limits and test
buttons, the card with the timing every shocker shares, and the drop zones
the behaviour cards take shockers in -- a shocker card's ⠿ dragged onto
one (or its ＋, which lists them, for a VR pointer or a touch screen).

A limit is a slider with its value written beside it in full ("1.0 s",
"60"), never a spin box: their numbers were cut off on a scaled display.
Every value goes out after the hand stops moving it (SAVE_AFTER_MS), not
on every pixel of a drag. Cards only draw and call back with primitive
values; pishock.py and pishock_rules.py wire them to the controller.
"""

import math
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple, Union

from PySide6.QtCore import QEvent, QMimeData, QPoint, QRect, QSize, Qt, QTimer
from PySide6.QtGui import QDrag
from PySide6.QtWidgets import (
    QApplication, QComboBox, QFrame, QLabel, QLayout, QLineEdit, QPushButton, QSpinBox,
    QWidget,
)

from ui.layout_helpers import FlowLayout, hbox, vbox
from ui.views.card_parts import set_quiet, slider
from ui.views.param_cards import CARD_W
from ui.widgets import IdentityMark

MIME_SHOCKER = "application/x-ogp-shocker"      # a shocker card dragged by its ⠿
SHOCK_HUE = "yellow"
SAVE_AFTER_MS = 300
Targets = Union[str, List[int]]                 # "all", or shocker ids


def fmt_seconds(s: float) -> str:
    if s >= 120:
        return f"{s / 60:.0f} min"
    if s >= 10:
        return f"{s:.0f} s"
    return f"{s:.1f} s"


class ValueSlider(QWidget):
    """A label, the value in full on the right, a slider under them. Linear
    (`step` per notch) or, for ranges like 0.1 s .. 1 h, logarithmic --
    either way the value it reports is rounded to `step`."""

    def __init__(self, label: str, lo: float, hi: float, value: float, step: float = 1,
                 fmt: Callable[[float], str] = lambda v: f"{v:g}", hue: str = SHOCK_HUE,
                 log: bool = False, on_change: Optional[Callable[[float], None]] = None,
                 tip: str = ""):
        super().__init__()
        self._lo, self._hi, self._step, self._fmt, self._log = lo, hi, step, fmt, log
        self._on_change = on_change
        lay = vbox(0, 2)
        self.setLayout(lay)
        row = hbox(0, 6)
        name = QLabel(label)
        name.setProperty("muted", "true")
        row.addWidget(name)
        row.addStretch(1)
        self.value_label = QLabel("")
        self.value_label.setObjectName("cardValue")
        row.addWidget(self.value_label)
        lay.addLayout(row)
        self._steps = 1000 if log else max(1, round((hi - lo) / step))
        self.slider = slider(hue, 0, self._steps)
        lay.addWidget(self.slider)
        self._timer = QTimer(self, singleShot=True, interval=SAVE_AFTER_MS)
        self._timer.timeout.connect(self._send)
        self.slider.valueChanged.connect(self._moved)
        if tip:
            self.setToolTip(tip)
        self.set_value(value)

    def _to_value(self, x: int) -> float:
        if self._log:
            v = self._lo * (self._hi / self._lo) ** (x / self._steps)
        else:
            v = self._lo + x * self._step
        v = round(v / self._step) * self._step
        return max(self._lo, min(self._hi, round(v, 6)))

    def _to_slider(self, v: float) -> int:
        v = max(self._lo, min(self._hi, v))
        if self._log:
            return round(self._steps * math.log(v / self._lo) / math.log(self._hi / self._lo))
        return round((v - self._lo) / self._step)

    def value(self) -> float:
        return self._to_value(self.slider.value())

    def set_value(self, v: float) -> None:
        """From the settings: shown, not sent back."""
        if not self.slider.isSliderDown() and not self._timer.isActive():
            set_quiet(self.slider, self._to_slider(v))
        self.value_label.setText(self._fmt(self.value()))

    def flush(self) -> None:
        """Send a value still waiting for the hand to stop, now (the card is
        about to show something else)."""
        if self._timer.isActive():
            self._timer.stop()
            self._send()

    def _moved(self, _x: int) -> None:
        self.value_label.setText(self._fmt(self.value()))
        self._timer.start()

    def _send(self) -> None:
        if self._on_change is not None:
            self._on_change(self.value())


class CardColumns(QLayout):
    """Cards in columns that fill the frame's width (no empty strip on the
    right): as many columns of at least CARD_W as fit, a card spanning as
    many as its own minimum width needs (a behaviour card, two). Each card
    goes where the columns under it end highest, so cards of different
    heights leave no holes."""

    def __init__(self, parent: Optional[QWidget] = None, spacing: int = 10, margin: int = 2):
        super().__init__(parent)
        self._items: List[Any] = []
        self._sp = spacing
        self.setContentsMargins(margin, margin, margin, margin)

    def addItem(self, item) -> None:  # noqa: N802
        self._items.append(item)

    def count(self) -> int:
        return len(self._items)

    def itemAt(self, index: int):  # noqa: N802
        return self._items[index] if 0 <= index < len(self._items) else None

    def takeAt(self, index: int):  # noqa: N802
        return self._items.pop(index) if 0 <= index < len(self._items) else None

    def expandingDirections(self):  # noqa: N802
        return Qt.Orientation(0)

    def hasHeightForWidth(self) -> bool:  # noqa: N802
        return True

    def heightForWidth(self, width: int) -> int:  # noqa: N802
        return self._arrange(QRect(0, 0, width, 0), dry=True)

    def setGeometry(self, rect: QRect) -> None:  # noqa: N802
        super().setGeometry(rect)
        self._arrange(rect, dry=False)

    def sizeHint(self) -> QSize:  # noqa: N802
        return self.minimumSize()

    def minimumSize(self) -> QSize:  # noqa: N802
        size = QSize()
        for item in self._items:
            if not item.isEmpty():
                size = size.expandedTo(QSize(CARD_W, item.minimumSize().height()))
        m = self.contentsMargins()
        return size + QSize(m.left() + m.right(), m.top() + m.bottom())

    def _arrange(self, rect: QRect, dry: bool) -> int:
        m = self.contentsMargins()
        width = rect.width() - m.left() - m.right()
        sp = self._sp
        cols = max(1, (width + sp) // (CARD_W + sp))
        col_w = (width - (cols - 1) * sp) / cols
        bottoms = [0] * cols
        for item in self._items:
            if item.isEmpty():
                continue
            span = max(1, min(cols, math.ceil((item.minimumSize().width() + sp) / (CARD_W + sp))))
            w = round(span * col_w + (span - 1) * sp)
            h = (item.heightForWidth(w) if item.hasHeightForWidth()
                 else item.sizeHint().height())
            h = max(h, item.minimumSize().height())
            col = min(range(cols - span + 1), key=lambda c: (max(bottoms[c:c + span]), c))
            top = max(bottoms[col:col + span])
            if not dry:
                item.setGeometry(QRect(rect.x() + m.left() + round(col * (col_w + sp)),
                                       rect.y() + m.top() + top, w, h))
            for c in range(col, col + span):
                bottoms[c] = top + h + sp
        used = max(bottoms) - sp if any(bottoms) else 0
        return used + m.top() + m.bottom()


def category_frame(title: str, hue: str, icon: str = ""):
    """Avatar Remote's category: a frame in its hue, a filled header bar,
    cards flowing left to right and wrapping. Returns (frame, its layout,
    the cards' flow, the header bar's layout)."""
    frame = QFrame()
    frame.setObjectName("paramCat")
    frame.setProperty("hue", hue)
    root = vbox(0, 8)
    root.setContentsMargins(8, 8, 8, 10)
    frame.setLayout(root)
    head = QWidget()
    head.setObjectName("paramCatHead")
    head.setProperty("hue", hue)
    hl = hbox(0, 6)
    hl.setContentsMargins(8, 4, 6, 4)
    head.setLayout(hl)
    if icon:
        hl.addWidget(IdentityMark(icon, 14))
    label = QLabel(title)
    label.setObjectName("paramCatTitle")
    hl.addWidget(label, 1)
    root.addWidget(head)
    host = QWidget()
    flow = CardColumns(host)
    root.addWidget(host)
    return frame, root, flow, hl


def mini_button(text: str, tip: str = "", role: str = "secondary") -> QPushButton:
    b = QPushButton(text)
    b.setProperty("role", role)
    b.setProperty("size", "small")
    b.setMinimumHeight(26)
    b.setCursor(Qt.PointingHandCursor)
    if tip:
        b.setToolTip(tip)
    return b


def state_pill(text: str = "", tone: str = "idle") -> QLabel:
    pill = QLabel(text)
    pill.setProperty("role", "pill")
    pill.setProperty("tone", tone)
    return pill


def card_frame(hue: str, width: int = CARD_W):
    """Avatar Remote's card: a well-coloured frame in the hue's mid."""
    c = QFrame()
    c.setObjectName("paramCard")
    c.setProperty("hue", hue)
    c.setFixedWidth(width)
    lay = vbox(0, 6)
    lay.setContentsMargins(10, 8, 8, 10)
    c.setLayout(lay)
    return c, lay


def name_edit(text: str, placeholder: str, on_done: Callable[[str], None]) -> QLineEdit:
    """A card's name, edited in place (Avatar Remote's category names)."""
    edit = QLineEdit(text)
    edit.setObjectName("cardName")
    edit.setPlaceholderText(placeholder)
    edit.setMaxLength(40)
    edit.editingFinished.connect(lambda: on_done(edit.text()))
    return edit


# ---- a shocker --------------------------------------------------------------

class ShockerSetupCard(QFrame):
    """One shocker: its name, what it is doing, its own limits and three
    test buttons. Dragged by its ⠿ onto a behaviour, it is that behaviour's
    shocker from then on. An OpenShock shocker carries its model and the
    transmitter id the collar is paired to as well, and can be deleted."""

    def __init__(self, shocker: Dict[str, Any], limits: Dict[str, int],
                 ranges: Dict[str, Tuple], on_name: Callable[[str], None],
                 on_limit: Callable[[str, float], None], on_test: Callable[[str], None],
                 openshock: Optional[Dict[str, Any]] = None):
        super().__init__()
        self.shocker_id = int(shocker["id"])
        self.setObjectName("paramCard")
        self.setProperty("hue", SHOCK_HUE)
        self.setMinimumWidth(CARD_W)
        self._press: Optional[QPoint] = None
        lay = vbox(0, 6)
        lay.setContentsMargins(10, 8, 8, 10)
        self.setLayout(lay)

        top = hbox(0, 4)
        self.grip = QLabel("⠿")
        self.grip.setObjectName("paramGrip")
        self.grip.setCursor(Qt.OpenHandCursor)
        self.grip.setToolTip("Drag onto a behaviour below: it drives this shocker")
        self.grip.installEventFilter(self)
        top.addWidget(self.grip)
        self.name = name_edit(shocker.get("name") or "", f"Shocker {self.shocker_id}", on_name)
        self.name.setToolTip("Your name for this shocker - here, on the behaviours, and for "
                             "friends you let use it. Empty: its ID again.")
        top.addWidget(self.name, 1)
        self.delete: Optional[QPushButton] = None
        if openshock is not None:
            self.delete = QPushButton("×")
            self.delete.setProperty("role", "chipClose")
            self.delete.setToolTip("Take this shocker off the list")
            top.addWidget(self.delete)
        lay.addLayout(top)

        row = hbox(0, 6)
        self.id_label = QLabel(f"ID {self.shocker_id}")
        self.id_label.setProperty("muted", "true")
        row.addWidget(self.id_label)
        row.addStretch(1)
        self.pill = state_pill()
        row.addWidget(self.pill)
        lay.addLayout(row)

        self.model: Optional[QComboBox] = None
        self.rf_id: Optional[QSpinBox] = None
        if openshock is not None:
            self.id_label.hide()
            line = hbox(0, 6)
            self.model = QComboBox()
            for m, label in openshock["models"]:
                self.model.addItem(label, m)
            self.model.setCurrentIndex(max(0, self.model.findData(openshock["model"])))
            self.model.setToolTip("Which kind of collar. PiShock's own shocker and the "
                                  "AliExpress collars OpenShock recommends are CaiXianlin.")
            line.addWidget(self.model, 1)
            self.rf_id = QSpinBox()
            self.rf_id.setRange(0, 65535)
            self.rf_id.setKeyboardTracking(False)
            self.rf_id.setValue(self.shocker_id)
            self.rf_id.setToolTip("The transmitter ID the collar is paired to (0-65535). "
                                  "Change it and the collar needs pairing again: hold its "
                                  "power button until the light blinks fast, then Beep.")
            line.addWidget(self.rf_id)
            lay.addLayout(line)

        self.limits: Dict[str, ValueSlider] = {}
        for key, label, hue, fmt, tip in (
                ("max_intensity", "Max shock", SHOCK_HUE, lambda v: f"{v:.0f}",
                 "No shock on this shocker goes above this, whatever a behaviour or a "
                 "friend asks for."),
                ("max_vibrate", "Max vibrate", "pink", lambda v: f"{v:.0f}",
                 "The same for vibrates. A shock that isn't armed goes out as a vibrate "
                 "under this one."),
                ("max_pulse_ms", "Longest pulse", SHOCK_HUE, lambda v: fmt_seconds(v / 1000),
                 "The longest one pulse on this shocker may run.")):
            lo, hi, _default = ranges[key]
            step = 100 if key == "max_pulse_ms" else 1
            s = ValueSlider(label, lo, hi, limits[key], step, fmt, hue,
                            on_change=lambda v, k=key: on_limit(k, v), tip=tip)
            self.limits[key] = s
            lay.addWidget(s)

        tests = hbox(0, 4)
        for label, op in (("Beep", "beep"), ("Vibrate", "vibrate"), ("Shock", "shock")):
            b = mini_button(label, f"One short {label.lower()} at strength 10 on this shocker. "
                            "Shock only shocks while shocks are armed; else it vibrates.")
            b.clicked.connect(lambda _=False, o=op: on_test(o))
            tests.addWidget(b, 1)
        lay.addLayout(tests)

    def set_limits(self, limits: Dict[str, int]) -> None:
        for key, s in self.limits.items():
            s.set_value(limits[key])

    def set_state(self, text: str, tone: str) -> None:
        if self.pill.text() != text:
            self.pill.setText(text)
        if self.pill.property("tone") != tone:
            self.pill.setProperty("tone", tone)
            self.pill.style().unpolish(self.pill)
            self.pill.style().polish(self.pill)

    def label(self) -> str:
        return self.name.text().strip() or f"Shocker {self.shocker_id}"

    # -- dragged by its ⠿
    def eventFilter(self, obj, event) -> bool:  # noqa: N802
        if obj is self.grip:
            kind = event.type()
            if kind == QEvent.MouseButtonPress and event.button() == Qt.LeftButton:
                self._press = event.position().toPoint()
                return True
            if kind == QEvent.MouseMove and self._press is not None:
                if (event.position().toPoint() - self._press).manhattanLength() \
                        >= QApplication.startDragDistance():
                    self._press = None
                    self._drag()
                return True
            if kind == QEvent.MouseButtonRelease:
                self._press = None
        return False

    def _drag(self) -> None:
        mime = QMimeData()
        mime.setData(MIME_SHOCKER, str(self.shocker_id).encode())
        drag = QDrag(self)
        drag.setMimeData(mime)
        pm = self.grab()
        drag.setPixmap(pm.scaledToWidth(max(1, pm.width() * 2 // 3), Qt.SmoothTransformation))
        drag.setHotSpot(QPoint(12, 12))
        drag.exec(Qt.CopyAction)


class SharedTimingCard(QFrame):
    """The timing every shocker shares: the rest after a pulse, the longest
    a hold may run, and the break it then takes."""

    def __init__(self, limits: Dict[str, float], ranges: Dict[str, Tuple],
                 on_limit: Callable[[str, float], None]):
        super().__init__()
        self.setObjectName("paramCard")
        self.setProperty("hue", SHOCK_HUE)
        self.setMinimumWidth(CARD_W)
        lay = vbox(0, 6)
        lay.setContentsMargins(10, 8, 8, 10)
        self.setLayout(lay)
        title = QLabel("Every shocker")
        title.setObjectName("paramLabel")
        lay.addWidget(title)
        self.limits: Dict[str, ValueSlider] = {}
        for key, label, step, tip in (
                ("cooldown_s", "Rest after a pulse", 0.1,
                 "How long a shocker rests after a pulse ends before the next one. A "
                 "stronger pulse may still take over one that's running, so a hard hit "
                 "lands at full strength."),
                ("max_hold_s", "Longest hold", 1.0,
                 "Continuous, While touching and a friend's hold run at most this long in "
                 "one go, then the shocker takes a forced break."),
                ("hold_rest_s", "Then a break of", 0.5, "How long that forced break lasts.")):
            lo, hi, _default = ranges[key]
            s = ValueSlider(label, lo, hi, limits[key], step, fmt_seconds, log=True,
                            on_change=lambda v, k=key: on_limit(k, v), tip=tip)
            self.limits[key] = s
            lay.addWidget(s)
        hint = QLabel("Every shocker on the hub keeps to these, whoever drives it.")
        hint.setProperty("muted", "true")
        hint.setWordWrap(True)
        hint.setObjectName("cardHint")
        lay.addWidget(hint)

    def set_limits(self, limits: Dict[str, float]) -> None:
        for key, s in self.limits.items():
            s.set_value(limits[key])


# ---- where a behaviour takes its shockers -------------------------------------

class ShockerDropZone(QFrame):
    """The shockers a behaviour (or one Touch zone) drives, as chips -- a
    chip's × takes one off. A shocker card dropped here adds it; so does
    the ＋, which lists them (no drag needed, for a VR pointer)."""

    def __init__(self, targets: Targets, names: Sequence[Tuple[int, str]],
                 on_change: Callable[[Targets], None]):
        super().__init__()
        self.setObjectName("dropZone")
        self.setAcceptDrops(True)
        self._targets: Targets = targets if targets == "all" else list(targets)
        self._names = list(names)              # ((id, label), ...) on the page now
        self._on_change = on_change
        self._picking = False
        self._flow = FlowLayout(margin=6, h_spacing=6, v_spacing=6)
        self._flow.setContentsMargins(6, 3, 6, 3)   # as tall as a field beside it
        self.setLayout(self._flow)
        self._fill()

    def targets(self) -> Targets:
        return self._targets

    def _label(self, sid: int) -> str:
        return next((n for i, n in self._names if i == sid), f"Shocker {sid}")

    def _fill(self) -> None:
        while self._flow.count():
            item = self._flow.takeAt(0)
            if item.widget() is not None:
                item.widget().deleteLater()
        chosen = ["all"] if self._targets == "all" else list(self._targets)
        for sid in chosen:
            text = "All shockers" if sid == "all" else self._label(sid)
            chip = QPushButton(f"{text}  ×")
            chip.setProperty("role", "chip")
            chip.setProperty("hue", SHOCK_HUE)
            chip.setCheckable(True)
            chip.setChecked(True)
            chip.setCursor(Qt.PointingHandCursor)
            chip.setToolTip("Click to take it off")
            chip.clicked.connect(lambda _=False, s=sid: self._remove(s))
            self._flow.addWidget(chip)
        add = QPushButton("＋" if chosen else "＋  Drop a shocker here")
        add.setObjectName("dropAdd")
        add.setCursor(Qt.PointingHandCursor)
        add.setToolTip("Drag a shocker card's ⠿ here - or click to pick one")
        add.clicked.connect(self._toggle_pick)
        self._flow.addWidget(add)
        if self._picking:
            offer = [(i, n) for i, n in self._names
                     if self._targets != "all" and i not in self._targets]
            if self._targets != "all":
                offer.append(("all", "All shockers"))
            for sid, text in offer:
                b = QPushButton(text)
                b.setProperty("role", "chip")
                b.setProperty("hue", SHOCK_HUE)
                b.setCursor(Qt.PointingHandCursor)
                b.clicked.connect(lambda _=False, s=sid: self.add(s))
                self._flow.addWidget(b)
            if not offer:
                none = QLabel("every shocker is on it")
                none.setObjectName("dropHint")
                self._flow.addWidget(none)

    def _toggle_pick(self) -> None:
        self._picking = not self._picking
        self._fill()

    def add(self, sid) -> None:
        if sid == "all":
            self._targets = "all"
        else:
            sid = int(sid)
            current = [] if self._targets == "all" else list(self._targets)
            if sid in current:
                return
            self._targets = current + [sid]
        self._picking = False
        self._fill()
        self._on_change(self._targets)

    def _remove(self, sid) -> None:
        self._targets = [] if sid == "all" else [s for s in self._targets if s != sid]
        self._fill()
        self._on_change(self._targets)

    # -- a shocker card dropped on it
    def _set_hover(self, on: bool) -> None:
        self.setProperty("hover", "true" if on else "false")
        self.style().unpolish(self)
        self.style().polish(self)

    def dragEnterEvent(self, event) -> None:  # noqa: N802
        if event.mimeData().hasFormat(MIME_SHOCKER):
            event.acceptProposedAction()
            self._set_hover(True)

    def dragLeaveEvent(self, event) -> None:  # noqa: N802
        self._set_hover(False)

    def dropEvent(self, event) -> None:  # noqa: N802
        self._set_hover(False)
        data = bytes(event.mimeData().data(MIME_SHOCKER)).decode(errors="ignore")
        try:
            sid = int(data)
        except ValueError:
            return
        event.acceptProposedAction()
        self.add(sid)
