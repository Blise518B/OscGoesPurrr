"""The Shockers page's pieces, in Avatar Remote's card design
(param_cards.py): a card per shocker with its own limits and test
buttons, the card with the timing every shocker shares, and the drop zones
the behaviour cards take shockers in -- a shocker card's ⠿ dragged onto
one (or its ＋, which lists them, for a VR pointer or a touch screen).

A limit is a slider with its value written beside it in full ("1.0 s",
"60"), never a spin box: their numbers were cut off on a scaled display.
The limits sit in a boxed "Limits" group (limits_group) with the ceiling
icon and the line "Nothing is sent from here", each labelled "Up to ..."
(or "At least" for the rest); the Test buttons, which do send, sit under
a line of their own, apart from it (Blise's friends, 2026-11-14: the
sliders read as controls).
Every value goes out after the hand stops moving it (SAVE_AFTER_MS), not
on every pixel of a drag. Cards only draw and call back with primitive
values; pishock.py and pishock_rules.py wire them to the controller.
"""

import math
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple, Union

from PySide6.QtCore import QEvent, QMimeData, QPoint, QRect, QSize, Qt, QTimer
from PySide6.QtGui import QDrag
from PySide6.QtWidgets import (
    QApplication, QComboBox, QFrame, QGraphicsOpacityEffect, QLabel, QLayout, QLineEdit,
    QPushButton, QSpinBox, QVBoxLayout, QWidget,
)

from ui.layout_helpers import FlowLayout, hbox, vbox
from ui.tooltips import tip_html
from ui.views.card_parts import set_quiet, slider
from ui.views.op_chips import SHOCKER_OP_TIPS, OpChips
from ui.views.param_cards import CARD_W
from ui.widgets import IdentityMark, ToggleSwitch

MIME_SHOCKER = "application/x-ogp-shocker"      # a shocker card dragged by its ⠿
SHOCK_HUE = "yellow"
SAVE_AFTER_MS = 300
Targets = Union[str, List[int]]                 # "all", or shocker ids

# What a Limits group says about itself (Blise's friends, 2026-11-14: the
# sliders looked like they operate the shocker). The hover explanation says
# the rest.
LIMITS_HINT = ("The most anything may send: friends, behaviours, the menu. "
               "Nothing is sent from here.")
SHARED_LIMITS_HINT = ("All shockers keep to these: friends, behaviours, the menu. "
                      "Nothing is sent from here.")


def fmt_seconds(s: float) -> str:
    if s >= 120:
        return f"{s / 60:.0f} min"
    if s >= 10:
        return f"{s:.0f} s"
    return f"{s:.1f} s"


def fmt_short(ms: float) -> str:
    """A short wait in seconds, to the hundredth under a second (a touch
    held 0.25 s -- fmt_seconds would say 0.2)."""
    if ms >= 1000:
        return fmt_seconds(ms / 1000)
    return f"{ms / 1000:.2f}".rstrip("0").rstrip(".") + " s"


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
        self.name_label = QLabel(label)
        self.name_label.setProperty("muted", "true")
        row.addWidget(self.name_label)
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


def limits_group(hint: str, tip: str) -> Tuple[QFrame, QVBoxLayout]:
    """A card's Limits: a box headed by the ceiling icon and "Limits", one
    line on what they are, then the caller's sliders in the returned layout.
    Nothing in it sends anything -- that is what the box says, and what
    sets it apart from the Test buttons under it. Not folded: the heading
    and the "Up to ..." labels are what stop them reading as controls."""
    box = QFrame()
    box.setObjectName("limitsGroup")
    box.setToolTip(tip_html("Limits", tip))
    lay = vbox(0, 6)
    lay.setContentsMargins(8, 6, 8, 8)
    box.setLayout(lay)
    head = hbox(0, 5)
    head.addWidget(IdentityMark("limits", 16))
    title = QLabel("Limits")
    title.setObjectName("limitsTitle")
    head.addWidget(title)
    head.addStretch(1)
    lay.addLayout(head)
    note = QLabel(hint)
    note.setObjectName("cardHint")
    note.setWordWrap(True)
    lay.addWidget(note)
    return box, lay


def card_rule() -> QFrame:
    """A thin line across a card, between what only sets a limit and what
    sends something."""
    rule = QFrame()
    rule.setObjectName("cardRule")
    rule.setFixedHeight(1)
    return rule


# ---- a shocker --------------------------------------------------------------

class ShockerSetupCard(QFrame):
    """One shocker: its name, its On / Off, what it is doing, its Shock /
    Vibrate / Beep switches, its own limits and three test buttons. Dragged by its ⠿ onto a behaviour, it is that
    behaviour's shocker from then on. An OpenShock shocker carries its model
    and the transmitter id the collar is paired to as well, and can be
    deleted. Switched off (not in use) the card stays where it is, greyed
    out, its switch the one thing lit (Blise's call, 2026-10-28)."""

    def __init__(self, shocker: Dict[str, Any], limits: Dict[str, int],
                 ranges: Dict[str, Tuple], on_name: Callable[[str], None],
                 on_limit: Callable[[str, float], None], on_test: Callable[[str], None],
                 openshock: Optional[Dict[str, Any]] = None,
                 on_use: Optional[Callable[[bool], None]] = None,
                 on_op: Optional[Callable[[str, bool], None]] = None,
                 ops_off: Sequence[str] = ()):
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
        self.use = ToggleSwitch("")
        self.use.setChecked(not shocker.get("off"))
        self.use.setToolTip("In use. Off: this shocker gets nothing - behaviours skip it, "
                            "friends and the web remote don't see it, Home leaves it out. "
                            "Its limits are kept for when you switch it back on.")
        if on_use is not None:
            self.use.toggled.connect(lambda on: on_use(bool(on)))
        top.addWidget(self.use)
        lay.addLayout(top)

        # everything under the title: greyed out while the shocker is off
        self.body = QWidget()
        lay.addWidget(self.body)
        lay = vbox(0, 6)
        self.body.setLayout(lay)
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

        # its Shock / Vibrate / Beep: what may reach it at all, whoever sends
        # it (the engine refuses one switched off) -- Blise's friends,
        # 2026-11-14. Kept apart from the Limits: these say whether, those how
        # much.
        self.ops = OpChips(lambda op, on: self._op_flipped(op, on, on_op), SHOCKER_OP_TIPS,
                           label="Allowed")
        lay.addWidget(self.ops)

        # the ceilings: boxed under "Limits", every label "Up to ..."; nothing
        # in the box sends anything
        box, group = limits_group(
            LIMITS_HINT,
            "The most anything may send to this shocker: behaviours, friends, the web "
            "remote and your avatar's menu. Nothing is sent from here - these only set "
            "the ceiling. The Test buttons below are what send.")
        lay.addWidget(box)
        self.limits: Dict[str, ValueSlider] = {}
        for key, label, hue, fmt, title, tip in (
                ("max_intensity", "Up to shock strength", SHOCK_HUE, lambda v: f"{v:.0f}",
                 "Up to shock strength",
                 "No shock on this shocker goes above this, whatever a behaviour, a friend "
                 "or the menu asks for. Moving it sends nothing."),
                ("max_vibrate", "Up to vibrate strength", "pink", lambda v: f"{v:.0f}",
                 "Up to vibrate strength",
                 "The most any vibrate on this shocker may carry. A shock that isn't armed "
                 "goes out as a vibrate under this one. Moving it sends nothing."),
                ("max_pulse_ms", "Up to a pulse of", SHOCK_HUE,
                 lambda v: fmt_seconds(v / 1000), "Up to a pulse of",
                 "The longest one pulse on this shocker may run. Moving it sends nothing.")):
            lo, hi, _default = ranges[key]
            step = 100 if key == "max_pulse_ms" else 1
            s = ValueSlider(label, lo, hi, limits[key], step, fmt, hue,
                            on_change=lambda v, k=key: on_limit(k, v), tip=tip_html(title, tip))
            self.limits[key] = s
            group.addWidget(s)

        # what does send, set apart from the ceilings by a line and its own
        # heading -- kept last: add_row's rows go in above it
        self._tail = QWidget()
        tail = vbox(0, 6)
        self._tail.setLayout(tail)
        tail.addWidget(card_rule())
        head = hbox(0, 6)
        test_title = QLabel("Test")
        test_title.setObjectName("testTitle")
        head.addWidget(test_title)
        test_note = QLabel("sends one short pulse")
        test_note.setObjectName("cardHint")
        head.addStretch(1)
        head.addWidget(test_note)
        tail.addLayout(head)
        tests = hbox(0, 4)
        self.tests: Dict[str, QPushButton] = {}
        for label, op in (("Beep", "beep"), ("Vibrate", "vibrate"), ("Shock", "shock")):
            b = mini_button(label, tip_html(
                f"Test: {label}",
                f"Sends one short {label.lower()} at strength 10 to this shocker, now. "
                + ("It only shocks while shocks are armed; otherwise it vibrates."
                   if op == "shock" else "It stays under this shocker's limits.")))
            b.setObjectName("testButton")
            b.clicked.connect(lambda _=False, o=op: on_test(o))
            tests.addWidget(b, 1)
            self.tests[op] = b
        tail.addLayout(tests)
        lay.addWidget(self._tail)
        self._body_lay = lay

        self.set_on(not shocker.get("off"))
        self.set_ops_off(ops_off)

    def _op_flipped(self, op: str, on: bool, on_op) -> None:
        self._show_ops()
        if on_op is not None:
            on_op(op, on)

    def set_ops_off(self, ops_off: Sequence[str]) -> None:
        """Which of Shock / Vibrate / Beep are switched off (from the
        settings: shown, not sent back)."""
        self.ops.set_on({op: op not in ops_off for op in self.ops.chips})
        self._show_ops()

    def ops_off(self) -> List[str]:
        return [op for op, chip in self.ops.chips.items() if not chip.isChecked()]

    def _show_ops(self) -> None:
        """A Test button rests while its op is switched off."""
        off = set(self.ops_off())
        for op, b in self.tests.items():
            b.setEnabled(op not in off)

    def add_row(self, widget: QWidget) -> None:
        """One more row above the Test buttons, greyed with the rest while
        the shocker is off (the page puts its "Tell VRChat" row here): the
        Limits and the Test buttons stay apart with it between."""
        self._body_lay.insertWidget(self._body_lay.indexOf(self._tail), widget)

    def set_on(self, on: bool) -> None:
        """In use (on) or not: off, the card dims and its controls rest --
        all but the switch, which brings it back."""
        if self.use.isChecked() != on:
            self.use.blockSignals(True)
            self.use.setChecked(on)
            self.use.blockSignals(False)
        self.body.setEnabled(on)
        state = "false" if on else "true"         # off: the frame greyed (theme_params)
        if self.property("off") != state:
            self.setProperty("off", state)
            self.style().unpolish(self)
            self.style().polish(self)
        for w in (self.body, self.grip, self.name):
            if on:
                w.setGraphicsEffect(None)
            elif w.graphicsEffect() is None:
                dim = QGraphicsOpacityEffect(w)
                dim.setOpacity(0.35)
                w.setGraphicsEffect(dim)

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


# The timing limits, in the order the box lists them: (key, label, step, tip)
TIMING_LIMITS = (
    ("cooldown_s", "At least a rest of", 0.1,
     "How long a shocker rests after a pulse ends before the next one - the least it "
     "gets. A stronger pulse may still take over one that's running, so a hard hit "
     "lands at full strength. Moving it sends nothing."),
    ("max_hold_s", "Up to a hold of", 1.0,
     "Continuous, While touching and a friend's hold run at most this long in one go, "
     "then the shocker takes a forced break. Moving it sends nothing."),
    ("hold_rest_s", "Then a forced break of", 0.5,
     "How long that forced break lasts. Moving it sends nothing."),
)
# The friends' own caps while their limits are separate (Blise's call,
# 2026-11-17): (key, label, hue, fmt, step, tip) -- each only ever lowers a
# shocker's own for friends
FRIEND_CAPS = (
    ("max_intensity", "Up to shock strength", SHOCK_HUE, lambda v: f"{v:.0f}", 1,
     "No shock a friend sends goes above this, on any shocker - where a shocker's own "
     "limit is lower, that one holds. Your avatar keeps each shocker's own. Moving it "
     "sends nothing."),
    ("max_vibrate", "Up to vibrate strength", "pink", lambda v: f"{v:.0f}", 1,
     "The most any vibrate a friend sends may carry, on any shocker - a shocker's own "
     "limit still wins where it is lower. Moving it sends nothing."),
    ("max_pulse_ms", "Up to a pulse of", SHOCK_HUE, lambda v: fmt_seconds(v / 1000), 100,
     "The longest one pulse a friend sends may run, on any shocker - a shocker's own "
     "still wins where it is shorter. Moving it sends nothing."),
)
SEPARATE_TITLE = "Separate limits for friends"
SEPARATE_TIP = (
    "Gives friends limits of their own: a max shock, max vibrate and longest pulse - "
    "which only ever lower each shocker's own - and a rest, longest hold and forced "
    "break, counted apart from your avatar's. Off, everyone keeps to one set - the "
    "easy way, and the default. On, your avatar (your behaviours, ShockOSC's and your "
    "avatar menu) keeps to each shocker's own caps and the timing above, and friends "
    "(Me and the web remote too) to theirs, so a friend's long hold never blocks your "
    "contact shocks, and the other way round. The catch: your avatar's longest hold "
    "and a friend's can then run back to back, without the forced break between them. "
    "Arming and each shocker's switches stay shared either way. Switching it sends "
    "nothing.")


class SharedTimingCard(QFrame):
    """The timing every shocker shares: the rest after a pulse, the longest
    a hold may run, and the break it then takes -- under "Limits" like each
    shocker's own ceilings, and with no button that sends anything.

    Its switch, Separate limits for friends (Blise's call, 2026-11-17; off
    by default), gives friends a set of their own under a Friends heading --
    their max shock, max vibrate and longest pulse (each lowering a
    shocker's own, never raising it) and their timing -- and the first set
    becomes your avatar's."""

    def __init__(self, limits: Dict[str, float], ranges: Dict[str, Tuple],
                 on_limit: Callable[[str, float], None], *, separate: bool = False,
                 friend_limits: Optional[Dict[str, float]] = None,
                 on_separate: Optional[Callable[[bool], None]] = None,
                 on_friend_limit: Optional[Callable[[str, float], None]] = None):
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
        box, group = limits_group(
            SHARED_LIMITS_HINT,
            "The timing every shocker on the hub keeps to, whoever drives it: behaviours, "
            "friends, the web remote and your avatar's menu. Nothing is sent from here - "
            "these only set the limits.")
        lay.addWidget(box)
        self.separate = ToggleSwitch(SEPARATE_TITLE)
        self.separate.setChecked(bool(separate))
        self.separate.setToolTip(tip_html(SEPARATE_TITLE, SEPARATE_TIP))
        if on_separate is not None:
            self.separate.toggled.connect(on_separate)
        group.addWidget(self.separate)
        self.avatar_head = _sub_head("Your avatar")
        group.addWidget(self.avatar_head)
        self.limits: Dict[str, ValueSlider] = {}
        for key, label, step, tip in TIMING_LIMITS:
            lo, hi, _default = ranges[key]
            s = ValueSlider(label, lo, hi, limits[key], step, fmt_seconds, log=True,
                            on_change=lambda v, k=key: on_limit(k, v),
                            tip=tip_html(label, tip))
            self.limits[key] = s
            group.addWidget(s)
        # the friends' own set: shown while the switch is on
        self.friends_box = QWidget()
        fl = vbox(0, 6)
        fl.setContentsMargins(0, 4, 0, 0)
        self.friends_box.setLayout(fl)
        fl.addWidget(_sub_head("Friends", "friends"))
        theirs = dict(limits, **(friend_limits or {}))
        self.friend_limits: Dict[str, ValueSlider] = {}
        friend_change = on_friend_limit or (lambda *_a: None)
        for key, label, hue, fmt, step, tip in FRIEND_CAPS:
            lo, hi, _default = ranges[key]
            s = ValueSlider(label, lo, hi, theirs[key], step, fmt, hue,
                            on_change=lambda v, k=key: friend_change(k, v),
                            tip=tip_html(label, tip))
            self.friend_limits[key] = s
            fl.addWidget(s)
        for key, label, step, tip in TIMING_LIMITS:
            lo, hi, _default = ranges[key]
            s = ValueSlider(label, lo, hi, theirs[key], step, fmt_seconds, log=True,
                            on_change=lambda v, k=key: friend_change(k, v),
                            tip=tip_html(label, "Friends' own, while their limits are separate: "
                                         + tip[0].lower() + tip[1:]))
            self.friend_limits[key] = s
            fl.addWidget(s)
        group.addWidget(self.friends_box)
        self._show_separate(bool(separate))

    def _show_separate(self, on: bool) -> None:
        self.avatar_head.setVisible(on)
        self.friends_box.setVisible(on)

    def set_limits(self, limits: Dict[str, float]) -> None:
        for key, s in self.limits.items():
            s.set_value(limits[key])

    def set_separate(self, on: bool, friend_limits: Optional[Dict[str, float]] = None) -> None:
        """The switch and the friends' set as the settings have them now."""
        if self.separate.isChecked() != bool(on):
            self.separate.blockSignals(True)
            self.separate.setChecked(bool(on))
            self.separate.blockSignals(False)
        self._show_separate(bool(on))
        for key, s in self.friend_limits.items():
            if friend_limits and key in friend_limits:
                s.set_value(friend_limits[key])


def _sub_head(text: str, identity: str = "") -> QWidget:
    """A set's heading inside the Limits box: Your avatar / Friends (with
    the Friends icon -- one icon per thing)."""
    w = QWidget()
    row = hbox(0, 5)
    w.setLayout(row)
    if identity:
        row.addWidget(IdentityMark(identity, 14))
    label = QLabel(text)
    label.setObjectName("limitsSub")
    row.addWidget(label)
    row.addStretch(1)
    return w


# ---- where a behaviour takes its shockers -------------------------------------

class ShockerDropZone(QFrame):
    """The shockers a behaviour (or one Touch zone) drives, as chips -- a
    chip's × takes one off. A shocker card dropped here adds it; so does
    the ＋, which lists them (no drag needed, for a VR pointer). A chip is
    grey while its shocker is switched off, or has the behaviour's op
    switched off (`op_off`: the ids, `op`: which one) -- skipped either way."""

    def __init__(self, targets: Targets, names: Sequence[Tuple[int, str]],
                 on_change: Callable[[Targets], None], off: Sequence[int] = (),
                 op_off: Sequence[int] = (), op: str = ""):
        super().__init__()
        self.setObjectName("dropZone")
        self.setAcceptDrops(True)
        self._targets: Targets = targets if targets == "all" else list(targets)
        self._names = list(names)              # ((id, label), ...) on the page now
        self._off = set(off)                   # switched off on their card: skipped
        self._op_off, self._op = set(op_off), op   # this behaviour's op off there: skipped
        self._on_change = on_change
        self._picking = False
        self._flow = FlowLayout(margin=6, h_spacing=6, v_spacing=6)
        self._flow.setContentsMargins(6, 3, 6, 3)   # as tall as a field beside it
        self.setLayout(self._flow)
        self._fill()

    def targets(self) -> Targets:
        return self._targets

    def set_op_off(self, op_off: Sequence[int], op: str) -> None:
        """The behaviour's op changed (or a shocker's switch for it): the
        chips grey again for it."""
        if set(op_off) != self._op_off or op != self._op:
            self._op_off, self._op = set(op_off), op
            self._fill()

    def _label(self, sid: int) -> str:
        return next((n for i, n in self._names if i == sid), f"Shocker {sid}")

    def _fill(self) -> None:
        while self._flow.count():
            item = self._flow.takeAt(0)
            if item.widget() is not None:
                item.widget().deleteLater()
        chosen = ["all"] if self._targets == "all" else list(self._targets)
        every = [i for i, _n in self._names]
        for sid in chosen:
            text = "All shockers" if sid == "all" else self._label(sid)
            chip = QPushButton(f"{text}  ×")
            chip.setProperty("role", "chip")
            chip.setProperty("hue", SHOCK_HUE)
            chip.setCheckable(True)
            ids = every if sid == "all" else [sid]
            off = bool(ids) and all(i in self._off for i in ids)
            op_off = not off and bool(ids) and all(i in self._off or i in self._op_off
                                                   for i in ids)
            chip.setChecked(not (off or op_off))    # unchecked: the grey chip
            chip.setCursor(Qt.PointingHandCursor)
            if off:
                tip = ("Switched off on its card - this behaviour skips it until it's back on. "
                       "Click to take it off.")
            elif op_off:
                tip = (f"{self._op.capitalize()} is switched off on its card - this behaviour "
                       "skips it until that's back on. Click to take it off.")
            else:
                tip = "Click to take it off"
            chip.setToolTip(tip)
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
