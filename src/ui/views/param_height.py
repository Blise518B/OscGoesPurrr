"""The Avatar Remote page's Height box (Blise's calls, 2026-11-14): your
height in VRChat, like the OSC scaler tools -- in a category box's frame,
below the categories, and kept small: only what it needs.

  * the top bar: "Height", the avatar menu's slot circle (a Radial can hold
    it), 🔒 (look-only for friends), ⋯ (its settings, folded out inside the
    box -- never a popup window) and its On / Off switch (off: friends and
    the web remote don't see it);
  * your height right now (VRChat's own word on it) and what Grow is doing;
  * one slider between your lowest and highest height (a log scale: equal
    steps are equal factors), and Grow (glides there), Right away (jumps)
    and Reset (back to your own height);
  * behind ⋯: the lowest and highest height (0.1-100 m, VRChat's own menu
    range out of the box) and Grow's speed.

The same box draws a friend's on the Friends page (and the web remote's in
remote-board.js), `editable=False`: no slot, lock, ⋯ or switch -- a locked
one says "🔒 look only" and greys out. The box only emits what you did; the
page or the panel passes it to the controller."""

import time
from typing import Any, Dict, Optional, Tuple

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QFrame, QLabel, QPushButton, QToolButton, QWidget

import avatar_height as ah
import param_board as pb
from ui.layout_helpers import hbox, vbox
from ui.views.card_parts import WheelSafeSlider
from ui.views.param_cards import CARD_W
from ui.views.param_slots import SlotDot
from ui.widgets import ToggleSwitch

BOX_W = 2 * CARD_W + 34          # as wide as a category holding two cards
HUE = "green"                    # Avatar Remote's green, through the categories' rules
STEPS = 1000                     # the sliders' steps
HANDS_OFF_S = 4.0                # the slider isn't moved for you this long after you moved it
SPEED_STEP = 0.5                 # Grow's speed slider, in half seconds


def speed_to_pos(double_s: float) -> int:
    """Grow's speed slider: faster to the right (fewer seconds per doubling)."""
    return round((ah.DOUBLE_S_MIN + ah.DOUBLE_S_MAX - double_s) / SPEED_STEP)


def pos_to_speed(pos: int) -> float:
    return ah.DOUBLE_S_MIN + ah.DOUBLE_S_MAX - pos * SPEED_STEP


def _log_slider(lo: float, hi: float) -> WheelSafeSlider:
    s = WheelSafeSlider(Qt.Horizontal)
    s.setProperty("hue", HUE)
    s.setRange(0, STEPS)
    s.setCursor(Qt.PointingHandCursor)
    s.setProperty("lo", lo)
    s.setProperty("hi", hi)
    return s


class HeightBox(QFrame):
    """`go(mode, metres)` for Grow / Right away, `reset()`; on your own
    board also `switched(on)`, `lock_toggled(locked)` and
    `option_changed(key, value)` for lo / hi / double_s."""

    go = Signal(str, float)
    reset = Signal()
    switched = Signal(bool)
    lock_toggled = Signal(bool)
    option_changed = Signal(str, float)

    def __init__(self, editable: bool = True) -> None:
        super().__init__()
        self.setObjectName("paramCat")
        self.setProperty("hue", HUE)
        self.setProperty("box", "height")
        self.setMaximumWidth(BOX_W)
        self._editable = editable
        self._range: Tuple[float, float] = (ah.MENU_MIN, ah.MENU_MAX)
        self._chosen: Optional[float] = None       # what the slider says
        self._last_height: Optional[float] = None
        self._hands_t = -1e9
        self._updating = False
        self.slot_dot: Optional[SlotDot] = None
        self.switch: Optional[ToggleSwitch] = None
        self.lock_btn: Optional[QToolButton] = None
        self.menu_btn: Optional[QToolButton] = None
        self.options: Optional[QWidget] = None

        root = vbox(0, 8)
        root.setContentsMargins(8, 8, 8, 10)
        self.setLayout(root)
        head = QWidget()
        head.setObjectName("paramCatHead")
        head.setProperty("hue", HUE)
        hl = hbox(0, 4)
        hl.setContentsMargins(8, 4, 6, 4)
        head.setLayout(hl)
        self.title = QLabel("Height")
        self.title.setObjectName("paramCatTitle")
        hl.addWidget(self.title, 1)
        if editable:
            self.slot_dot = SlotDot(pb.HEIGHT_SLOT, ("radial",))
            hl.addWidget(self.slot_dot)
            self.lock_btn = QToolButton()
            self.lock_btn.setObjectName("paramCatLock")
            self.lock_btn.setCheckable(True)
            self.lock_btn.setText("🔓")
            self.lock_btn.setCursor(Qt.PointingHandCursor)
            self.lock_btn.toggled.connect(self._on_lock)
            hl.addWidget(self.lock_btn)
            self.menu_btn = QToolButton()
            self.menu_btn.setObjectName("paramMenu")
            self.menu_btn.setText("⋯")
            self.menu_btn.setCheckable(True)
            self.menu_btn.setCursor(Qt.PointingHandCursor)
            self.menu_btn.toggled.connect(self._fold)
            hl.addWidget(self.menu_btn)
            self.switch = ToggleSwitch("")
            self.switch.setChecked(True)
            self.switch.toggled.connect(self._on_switch)
            hl.addWidget(self.switch)
        else:
            self.lock_lbl = QLabel("🔒 look only")
            self.lock_lbl.setObjectName("paramCatTitle")
            self.lock_lbl.hide()
            hl.addWidget(self.lock_lbl)
        root.addWidget(head)

        self.body = QWidget()
        bl = vbox(0, 8)
        bl.setContentsMargins(4, 0, 4, 0)
        self.body.setLayout(bl)
        now_row = hbox(0, 8)
        self.now_lbl = QLabel("–")
        self.now_lbl.setObjectName("heightNow")
        now_row.addWidget(self.now_lbl)
        self.state_lbl = QLabel("")
        self.state_lbl.setObjectName("paramValue")
        now_row.addWidget(self.state_lbl, 1, Qt.AlignBottom)
        bl.addLayout(now_row)
        slide_row = hbox(0, 6)
        self.slider = _log_slider(*self._range)
        self.slider.valueChanged.connect(self._on_slider)
        slide_row.addWidget(self.slider, 1)
        self.target_lbl = QLabel("–")
        self.target_lbl.setObjectName("paramValue")
        self.target_lbl.setFixedWidth(52)
        self.target_lbl.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        slide_row.addWidget(self.target_lbl)
        bl.addLayout(slide_row)
        buttons = hbox(0, 6)
        self.grow_btn = QPushButton("Grow")
        self.now_btn = QPushButton("Right away")
        self.reset_btn = QPushButton("Reset")
        for b in (self.grow_btn, self.now_btn, self.reset_btn):
            b.setProperty("role", "secondary")
            b.setCursor(Qt.PointingHandCursor)
            buttons.addWidget(b)
        buttons.addStretch(1)
        self.grow_btn.clicked.connect(lambda _=False: self._go(ah.GROW))
        self.now_btn.clicked.connect(lambda _=False: self._go(ah.NOW))
        self.reset_btn.clicked.connect(lambda _=False: self.reset.emit())
        bl.addLayout(buttons)
        root.addWidget(self.body)
        self.note = QLabel("")
        self.note.setProperty("muted", "true")
        self.note.setWordWrap(True)
        self.note.hide()
        root.addWidget(self.note)
        if editable:
            root.addWidget(self._build_options())

    # -- behind ⋯ (your own box) -------------------------------------------------------

    def _build_options(self) -> QWidget:
        box = QFrame()
        box.setObjectName("heightOptions")
        lay = vbox(0, 6)
        lay.setContentsMargins(4, 8, 4, 0)
        box.setLayout(lay)
        self.opt_rows: Dict[str, Tuple[WheelSafeSlider, QLabel]] = {}
        for key, name in (("lo", "Lowest"), ("hi", "Highest"), ("double_s", "Grow speed")):
            row = hbox(0, 6)
            label = QLabel(name)
            label.setObjectName("paramLabel")
            label.setFixedWidth(84)
            row.addWidget(label)
            if key == "double_s":
                s = WheelSafeSlider(Qt.Horizontal)
                s.setProperty("hue", HUE)
                s.setRange(int(ah.DOUBLE_S_MIN / SPEED_STEP), int(ah.DOUBLE_S_MAX / SPEED_STEP))
                s.setCursor(Qt.PointingHandCursor)
            else:
                s = _log_slider(ah.SAFE_MIN, ah.SAFE_MAX)
            value = QLabel("–")
            value.setObjectName("paramValue")
            value.setFixedWidth(72)
            value.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            s.valueChanged.connect(lambda _v, k=key: self._on_option(k, False))
            s.sliderReleased.connect(lambda k=key: self._on_option(k, True))
            row.addWidget(s, 1)
            row.addWidget(value)
            lay.addLayout(row)
            self.opt_rows[key] = (s, value)
        self.world_lbl = QLabel("")
        self.world_lbl.setObjectName("paramValue")
        self.world_lbl.setWordWrap(True)
        lay.addWidget(self.world_lbl)
        box.hide()
        self.options = box
        return box

    def _fold(self, open_: bool) -> None:
        if self.options is not None:
            self.options.setVisible(open_)

    def _option_value(self, key: str) -> float:
        s, _ = self.opt_rows[key]
        if key == "double_s":
            return pos_to_speed(s.value())
        return ah.from_slider(s.value() / STEPS, ah.SAFE_MIN, ah.SAFE_MAX)

    def _on_option(self, key: str, released: bool) -> None:
        s, label = self.opt_rows[key]
        v = self._option_value(key)
        label.setText(ah.fmt_speed(v) if key == "double_s" else ah.fmt(v))
        # dragging: sent once let go; a click or a key: at once
        if not self._updating and (released or not s.isSliderDown()):
            self.option_changed.emit(key, v)

    def show_settings(self, on: bool, locked: bool, lo: float, hi: float, double_s: float,
                      world: Tuple[Optional[float], Optional[float]] = (None, None)) -> None:
        """Your own box's switch, lock and what is behind ⋯."""
        if not self._editable:
            return
        self._updating = True
        try:
            if self.switch.isChecked() != on:
                self.switch.setChecked(on)
            if self.lock_btn.isChecked() != locked:
                self.lock_btn.setChecked(locked)
            self.lock_btn.setText("🔒" if locked else "🔓")
            for key, v in (("lo", lo), ("hi", hi), ("double_s", double_s)):
                s, label = self.opt_rows[key]
                if s.isSliderDown():
                    continue
                pos = (speed_to_pos(v) if key == "double_s" else
                       round(ah.to_slider(v, ah.SAFE_MIN, ah.SAFE_MAX) * STEPS))
                if s.value() != pos:
                    s.setValue(pos)
                label.setText(ah.fmt_speed(v) if key == "double_s" else ah.fmt(v))
            wmin, wmax = world
            text = (f"VRChat's own menu here: {ah.fmt(wmin)} to {ah.fmt(wmax)}"
                    if wmin is not None and wmax is not None else "")
            if self.world_lbl.text() != text:
                self.world_lbl.setText(text)
            if self.world_lbl.isHidden() == bool(text):
                self.world_lbl.setVisible(bool(text))
        finally:
            self._updating = False

    def _on_switch(self, on: bool) -> None:
        if not self._updating:
            self.switched.emit(on)

    def _on_lock(self, locked: bool) -> None:
        self.lock_btn.setText("🔒" if locked else "🔓")
        if not self._updating:
            self.lock_toggled.emit(locked)

    # -- the slider and the buttons ----------------------------------------------------

    def chosen(self) -> Optional[float]:
        return self._chosen

    def _put_slider(self, height: Optional[float]) -> None:
        lo, hi = self._range
        x = ah.to_slider(height, lo, hi)
        self._updating = True
        try:
            if x is not None and self.slider.value() != round(x * STEPS):
                self.slider.setValue(round(x * STEPS))
        finally:
            self._updating = False
        self.target_lbl.setText(ah.fmt(height))

    def _on_slider(self, pos: int) -> None:
        if self._updating:
            return
        lo, hi = self._range
        self._chosen = ah.from_slider(pos / STEPS, lo, hi)
        self._hands_t = time.monotonic()
        self.target_lbl.setText(ah.fmt(self._chosen))

    def _go(self, mode: str) -> None:
        if self._chosen is not None:
            self.go.emit(mode, float(self._chosen))

    def show_state(self, height: Optional[float], lo: float, hi: float, *,
                   gliding: bool = False, target: Optional[float] = None,
                   usable: bool = True, can_reset: bool = True, note: str = "",
                   locked: bool = False) -> None:
        """What VRChat says now. The slider follows your height (a glide's
        end while one runs) -- except while you hold it, or moved it a
        moment ago."""
        now = time.monotonic()
        if (lo, hi) != self._range:
            self._range = (lo, hi)
            if self._chosen is not None:
                self._chosen = ah.clamp(self._chosen, lo, hi)
                self._put_slider(self._chosen)
        text = ah.fmt(height)
        if self.now_lbl.text() != text:
            self.now_lbl.setText(text)
        if gliding and target is not None:
            shrink = height is not None and target < height
            state = f"{'shrinking' if shrink else 'growing'} to {ah.fmt(target)}"
        else:
            state = "eye height" if height is not None else ""
        if self.state_lbl.text() != state:
            self.state_lbl.setText(state)
        mine = self.slider.isSliderDown() or now - self._hands_t < HANDS_OFF_S
        follow = None
        if gliding and target is not None:
            follow = target
        elif height is not None and (height != self._last_height or self._chosen is None):
            follow = height
        if follow is not None and not mine:
            self._chosen = ah.clamp(follow, lo, hi)
            self._put_slider(self._chosen)
        self._last_height = height
        if self.body.isEnabled() != usable:
            self.body.setEnabled(usable)
        self.reset_btn.setEnabled(usable and can_reset)
        self.grow_btn.setEnabled(usable and self._chosen is not None)
        self.now_btn.setEnabled(usable and self._chosen is not None)
        if self.note.text() != note:
            self.note.setText(note)
        if self.note.isHidden() == bool(note):
            self.note.setVisible(bool(note))
        if not self._editable and self.lock_lbl.isHidden() == locked:
            self.lock_lbl.setVisible(locked)
