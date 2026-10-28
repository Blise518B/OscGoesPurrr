"""A ShockerCard is PiShock's own shocker panel, for one of a friend's
shockers (or a party of them -- shock_party.py), laid out the way PiShock's
is so someone used to PiShock is at home (docs.pishock.com, "Shocker
Interface"):

       SHOCK                 [Use Mode]                 VIBRATE
    [Operate ] ┃   ⇈           [STOP]            ⇈   ┃ [Operate ]
    [Duration] ┃   🎲          [Beep]            ⇊   ┃ [Duration]
    [Warning ] ┃   ⇊                                 ┃
               ◔                                     ◔

  * Use Mode -- Tap: a press is one operation of the set Duration;
    Remote: it runs while the button is held; Continuous: the sliders
    drive the shocker for as long as they're above 0 (Operate, Duration,
    Random and Beep are off).
  * Random (the dice) -- the shock slider gets two handles, and every shock
    picks a strength between them. ⇈ / ⇊ nudge the strength (the range).
  * Warning -- None / Small (1-3 s) / Mid (3-6 s) / Long (6-9 s) of
    vibration before a shock, at the vibrate strength, how long exactly
    random -- in every mode, as PiShock has it: Tap sends it with the
    shock, Remote vibrates first and then shocks while still held,
    Continuous vibrates first when the shock slider leaves 0.
  * Duration -- 0.1 s, 0.3 s, then whole seconds to 10 s, never past theirs.
    Duration, Warning and Use Mode open a picker over the card.

Cards only draw and call back with primitive values; the Friends view wires
those to the controller. Strengths go out as 0..1 of the RECEIVER's caps
(`set_caps`); a party's card keeps PARTY_CAPS: percent of each one's caps
and real seconds up to 10 s. `big` makes everything
larger for control mode (VR). Narrower than its three columns
(`wide_width`), it folds: Use Mode, STOP and Beep go under the Shock and
Vibrate columns, as PiShock's Party panel has them.
"""

import random
from typing import Callable, Dict, List, Optional, Tuple

from PySide6.QtCore import QPoint, QSize, Qt, QTimer
from PySide6.QtWidgets import QCheckBox, QFrame, QLabel, QLayout, QSizePolicy

from remote_protocol import SHOCK_MIN_MS
from ui import theme
from ui.icons import glyph_icon
from ui.layout_helpers import hbox, vbox
from ui.views.card_parts import bigger, hue_color, mini_button, set_quiet, slider, small_label
from ui.views.shocker_parts import TILE, Picker, RangeSlider, Tile

# PiShock's own lengths: 0.1 s, 0.3 s, then whole seconds to 10 s
_DURATIONS_MS = (100, 300, 1000, 2000, 3000, 4000, 5000, 6000, 7000, 8000, 9000, 10000)
# PiShock's warnings: vibration before the shock, a random length in these
WARNINGS = (None, (1000, 3000), (3000, 6000), (6000, 9000))
WARNING_NAMES = ("NONE", "SMALL", "MID", "LONG")
_WARNING_PICKS = ("None", "Small · 1–3 s", "Mid · 3–6 s", "Long · 6–9 s")
USES = ("tap", "remote", "continuous")
_USE_NAMES = ("TAP", "REMOTE", "CONTINUOUS")
_USE_PICKS = ("Tap", "Remote", "Continuous")
_USE_GLYPHS = ("tap", "remote", "infinity")
# a party: percent of each one's caps, and real seconds up to PiShock's 10
PARTY_CAPS = (100, 100, _DURATIONS_MS[-1])
_NUDGE = 0.05                          # ⇈ / ⇊: this much of the cap


def _secs(ms: int) -> str:
    return f"{ms / 1000:g}"


class ShockerCard(QFrame):
    """PiShock's shocker panel (see the module's notes).

    Callbacks: on_fire(op, intensity, length, warn_ms, warn_intensity) --
    Tap; on_hold(op, intensity) / on_release() -- Remote and Continuous
    (a warning holds "vibrate" first, then "shock"); on_stop()."""

    def __init__(self, title: str, hue: str,
                 on_fire: Callable[[str, float, float, int, float], None],
                 on_hold: Callable[[str, float], None],
                 on_release: Callable[[], None],
                 on_stop: Callable[[], None],
                 big: bool = False, vibrate_hue: str = "pink", party_box: bool = False):
        super().__init__()
        self.hue, self._vibrate_hue = hue, vibrate_hue
        self._big = big
        self._on_fire, self._on_hold, self._on_release, self._on_stop = (
            on_fire, on_hold, on_release, on_stop)
        self._caps: Tuple[int, int, int] = PARTY_CAPS            # shock, vibrate, ms
        self._caps_known = False
        self._hold_s = 0.0                                       # their longest hold
        self._holding = ""                                       # op held right now
        self._pending = ""             # "shock": its warning vibrates first
        self._pending_v = 1            # ... and the strength it then holds
        self._use = "tap"
        self._warn = 0                                           # index into WARNINGS
        self._random = False
        self._blocked = False                                    # they paused you / Off
        self._dur = {"shock": 300, "vibrate": 1000}             # ms
        self._before_cont: Optional[Dict[str, int]] = None       # strengths before Continuous
        self._picker: Optional[Picker] = None
        self._warn_timer = QTimer(self)
        self._warn_timer.setSingleShot(True)
        self._warn_timer.timeout.connect(self._warned)
        self.setObjectName("friendCard")
        self.setProperty("hue", hue)
        bigger(self, big)
        lay = vbox(10 if big else 8, 8 if big else 6)
        self.setLayout(lay)

        head = hbox(0, 6)
        name = bigger(QLabel(title), big)
        name.setObjectName("friendCardName")
        name.setTextFormat(Qt.PlainText)        # their shocker's name, never markup
        head.addWidget(name)
        head.addStretch(1)
        self.party_box: Optional[QCheckBox] = None
        if party_box:
            self.party_box = bigger(QCheckBox("Party"), big)
            self.party_box.setProperty("hue", hue)
            self.party_box.setToolTip("Party Mode: drive this shocker together with the "
                                      "others you tick - all at once, one at random or "
                                      "one after the other")
            head.addWidget(self.party_box)
        lay.addLayout(head)

        self._tiles: Dict[str, Tile] = {}
        self._sliders, self._max_lbls, self._gauges = {}, {}, {}
        body = hbox(0, 6 if big else 4)
        body.addStretch(1)
        # SHOCK: its tiles, then its slider
        block, blay = self._block("SHOCK", hue)
        row = hbox(0, 6)
        tiles = vbox(0, 6)
        self._tiles["shock"] = self._operate("shock", hue)
        self._tiles["shock_dur"] = self._duration_tile("shock", hue)
        warn = Tile("Warning", hue, big=big)
        warn.setToolTip("Vibration before a shock: Small 1-3 s, Mid 3-6 s, Long 6-9 s - how "
                        "long exactly is random, at the vibrate strength. Works in every "
                        "Use Mode.")
        warn.clicked.connect(lambda _=False: self._open_picker("warn"))
        self._tiles["warn"] = warn
        for key in ("shock", "shock_dur", "warn"):
            tiles.addWidget(self._tiles[key])
        tiles.addStretch(1)
        row.addLayout(tiles)
        row.addLayout(self._slider_column("shock", hue))
        blay.addLayout(row)
        body.addWidget(block)
        # nudges and Random, between the Shock column and the middle
        col = vbox(0, 6)
        col.addStretch(1)
        self._up = mini_button(None, "Stronger", lambda: self._nudge("shock", +1), big=big)
        self._dice_btn = mini_button(None,
                                     "Random Intensity: two handles on the slider, and every "
                                     "shock picks a strength between them",
                                     self._toggle_random, big=big)
        self._dice_btn.setCheckable(True)
        self._dice_btn.setProperty("hue", hue)
        self._down = mini_button(None, "Weaker", lambda: self._nudge("shock", -1), big=big)
        for b in (self._up, self._dice_btn, self._down):
            col.addWidget(b)
        col.addStretch(1)
        body.addLayout(col)
        # the middle: Use Mode, STOP, Beep
        self._center = vbox(0, 6)
        use = Tile("Use Mode", "", big=big, wide=True, small_value=True)
        use.clicked.connect(lambda _=False: self._open_picker("use"))
        stop = Tile("STOP", "stop", big=big, wide=True)
        # the biggest of the three: it takes what the column has left
        stop.setMinimumHeight(round(TILE[big].height() * 1.35))
        stop.setMaximumHeight(16777215)
        stop.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Expanding)
        stop.setToolTip("Emergency Stop: this shocker stops now - a running pulse, a hold, "
                        "a shock waiting after its warning")
        stop.clicked.connect(lambda _=False: self._stop())
        beep = Tile("Beep", "", big=big, wide=True)
        beep.setToolTip("A beep (Remote: while you hold it)")
        self._wire(beep, "beep")
        self._tiles.update(use=use, stop=stop, beep=beep)
        self._center_tiles = [use, stop, beep]
        for t in self._center_tiles:
            self._center.addWidget(t, 1 if t is stop else 0, Qt.AlignHCenter)
        body.addLayout(self._center)
        col = vbox(0, 6)
        col.addStretch(1)
        self._vup = mini_button(None, "Stronger", lambda: self._nudge("vibrate", +1), big=big)
        self._vdown = mini_button(None, "Weaker", lambda: self._nudge("vibrate", -1), big=big)
        col.addWidget(self._vup)
        col.addWidget(self._vdown)
        col.addStretch(1)
        body.addLayout(col)
        # VIBRATE: its slider, then its tiles
        block, blay = self._block("VIBRATE", vibrate_hue)
        row = hbox(0, 6)
        row.addLayout(self._slider_column("vibrate", vibrate_hue))
        tiles = vbox(0, 6)
        self._tiles["vibrate"] = self._operate("vibrate", vibrate_hue)
        self._tiles["vibrate_dur"] = self._duration_tile("vibrate", vibrate_hue)
        tiles.addWidget(self._tiles["vibrate"])
        tiles.addWidget(self._tiles["vibrate_dur"])
        tiles.addStretch(1)
        row.addLayout(tiles)
        blay.addLayout(row)
        body.addWidget(block)
        body.addStretch(1)
        lay.addLayout(body)
        self._body = body
        # folded (narrow): Use Mode, STOP and Beep come down here
        self._foot = hbox(0, 8)
        lay.addLayout(self._foot)
        self._compact = False

        self.recolour()
        self._show_controls()
        lay.setSizeConstraint(QLayout.SetNoConstraint)
        self._wide = lay.minimumSize().width()             # three columns
        self._fold(True)
        self._narrow = lay.minimumSize().width()           # folded
        self._fold(False)

    # -- building
    def _block(self, title: str, hue: str):
        block = QFrame()
        block.setObjectName("opBlock")
        block.setProperty("hue", hue)
        blay = vbox(8 if self._big else 6, 4)
        block.setLayout(blay)
        head = QLabel(title)
        head.setObjectName("friendsMicro")
        head.setProperty("hue", hue)
        head.setAlignment(Qt.AlignCenter)
        bigger(head, self._big)
        blay.addWidget(head)
        return block, blay

    def _operate(self, op: str, hue: str) -> Tile:
        t = Tile("Operate", hue, filled=True, big=self._big)
        t.setToolTip(f"{op.capitalize()} at this strength for the Duration "
                     "(Remote: while you hold it)")
        self._wire(t, op)
        return t

    def _duration_tile(self, op: str, hue: str) -> Tile:
        t = Tile("Duration", hue, big=self._big)
        t.setToolTip("How long it runs - 0.1 s, 0.3 s, then whole seconds to 10 s, never "
                     "past their longest")
        t.clicked.connect(lambda _=False, o=op: self._open_picker(o + "_dur"))
        return t

    def _slider_column(self, op: str, hue: str):
        col = vbox(0, 2)
        top = small_label(big=self._big)
        top.setAlignment(Qt.AlignCenter)
        top.setToolTip("The top of the slider: their strongest")
        col.addWidget(top)
        s = slider(hue, 1, 100, self._big, vertical=True)
        s.setMinimumHeight(120)
        s.setToolTip(f"{op.capitalize()} Intensity")
        s.valueChanged.connect(lambda _v, o=op: self._strength_moved(o))
        col.addWidget(s, 1, Qt.AlignHCenter)
        self._sliders[op] = s
        if op == "shock":
            # Random's range: two handles where the one was
            self._lo = slider(hue, 1, 100, self._big)
            self._hi = slider(hue, 1, 100, self._big)
            for sl in (self._lo, self._hi):
                sl.valueChanged.connect(lambda _v: self._show_values())
            self._range = RangeSlider(hue, self._lo, self._hi, self._big)
            col.addWidget(self._range, 1, Qt.AlignHCenter)
        gauge = QLabel()
        gauge.setAlignment(Qt.AlignCenter)
        gauge.setToolTip(f"{op.capitalize()} Intensity")
        col.addWidget(gauge)
        self._max_lbls[op], self._gauges[op] = top, gauge
        set_quiet(s, 25 if op == "shock" else 50)
        if op == "shock":
            set_quiet(self._lo, 10)
            set_quiet(self._hi, 40)
        return col

    def _wire(self, button, op: str) -> None:
        button.clicked.connect(lambda _=False, o=op: self._tap(o))
        button.pressed.connect(lambda o=op: self._press(o))
        button.released.connect(lambda o=op: self._unpress(o))

    # -- narrow: Use Mode, STOP and Beep go under the columns
    def wide_width(self) -> int:
        """The width it needs unfolded -- CardGrid puts two side by side
        only when both get this much."""
        return self._wide

    def _fold(self, compact: bool) -> None:
        if compact == self._compact:
            return
        self._compact = compact
        stop = self._tiles["stop"]
        if compact:
            for t in self._center_tiles:
                self._center.removeWidget(t)
            # one even row under the columns: STOP as tall as the others
            stop.setMinimumHeight(TILE[self._big].height())
            self._foot.addStretch(1)
            for t in self._center_tiles:
                self._foot.addWidget(t, 0, Qt.AlignTop)
            self._foot.addStretch(1)
        else:
            while self._foot.count():
                self._foot.takeAt(0)
            stop.setMinimumHeight(round(TILE[self._big].height() * 1.35))
            for i, t in enumerate(self._center_tiles):
                self._center.insertWidget(i, t, 1 if t is stop else 0, Qt.AlignHCenter)
        for box in (self._center, self._body, self._foot, self.layout()):
            box.invalidate()            # or the old sizes stay cached
        self.updateGeometry()           # folded it is taller: the grid asks again

    def resizeEvent(self, event) -> None:  # noqa: N802
        self._fold(event.size().width() < self._wide)
        super().resizeEvent(event)

    def minimumSizeHint(self):  # noqa: N802
        """As narrow as it goes folded; as tall as it is now."""
        return QSize(self._narrow, self.layout().minimumSize().height())

    def recolour(self) -> None:
        """Paint the glyphs in the card's colours as they are now -- they
        are pixmaps, so a colour change (Appearance) has to redraw them."""
        v = theme.qss_vars()
        neon = theme.normalize_mode(theme.MODE) == "neon"
        size = QSize(20, 20) if self._big else QSize(14, 14)
        shock, vib = hue_color(self.hue), hue_color(self._vibrate_hue)
        t = self._tiles
        # filled in Vibrant: the glyph is ink there; Darker's is the hue
        t["shock"].set_glyph("bolt", v["ink"] if neon else shock)
        t["vibrate"].set_glyph("vibrate", v["ink"] if neon else vib)
        t["shock_dur"].set_glyph("clock", shock)
        t["vibrate_dur"].set_glyph("clock", vib)
        t["warn"].set_glyph("alert", v["warn"])
        t["use"].set_glyph(_USE_GLYPHS[USES.index(self._use)], v["txt"])
        t["stop"].set_glyph("stop", v["err"])
        t["beep"].set_glyph("bell", v["txt"])
        for button, kind, color in ((self._up, "up", shock), (self._dice_btn, "dice", shock),
                                    (self._down, "down", shock), (self._vup, "up", vib),
                                    (self._vdown, "down", vib)):
            button.setIcon(glyph_icon(kind, color, 14))
            button.setIconSize(size)
        px = 22 if self._big else 16
        for gauge in self._gauges.values():
            gauge.setPixmap(glyph_icon("gauge", v["muted"], px).pixmap(QSize(px, px)))

    # -- numbers
    def _cap(self, op: str) -> int:
        return max(1, self._caps[1] if op == "vibrate" else self._caps[0])

    def _to_fraction(self, op: str, v: int) -> float:
        cap = self._cap(op)
        return 1.0 if cap <= 1 else max(0.0, (v - 1) / (cap - 1))

    def _strength(self, op: str) -> int:
        """The strength this press uses -- a fresh pick in Random."""
        if op == "shock" and self._random:
            lo, hi = sorted((self._lo.value(), self._hi.value()))
            return random.randint(lo, hi)
        return self._sliders[op].value() if op in self._sliders else 1

    def _length(self, op: str) -> float:
        ms = self._dur[op]
        top = max(SHOCK_MIN_MS, self._caps[2])
        return 0.0 if top <= SHOCK_MIN_MS else (min(ms, top) - SHOCK_MIN_MS) / (top - SHOCK_MIN_MS)

    def _durations(self) -> List[int]:
        top = max(SHOCK_MIN_MS, self._caps[2])
        steps = [d for d in _DURATIONS_MS if d <= top]
        return steps + ([top] if top not in steps else [])

    def _warn_ms(self) -> int:
        span = WARNINGS[self._warn]
        return random.randint(*span) if span else 0

    def _warn_fraction(self) -> float:
        """The warning vibrates at the vibrate strength -- in Continuous,
        the one it had before (that slider starts at 0 there)."""
        v = self._sliders["vibrate"].value()
        if v <= 0 and self._before_cont:
            v = self._before_cont["vibrate"]
        return self._to_fraction("vibrate", max(1, v))

    def _show_values(self) -> None:
        # bare numbers on the tiles, as PiShock's; the slider's top says
        # their max (a party's title says its numbers are percent)
        t = self._tiles
        if self._random and self._use != "continuous":
            lo, hi = sorted((self._lo.value(), self._hi.value()))
            t["shock"].set_value(f"{lo}–{hi}")
        else:
            t["shock"].set_value(str(self._sliders["shock"].value()))
        t["vibrate"].set_value(str(self._sliders["vibrate"].value()))
        for op in ("shock", "vibrate"):
            t[op + "_dur"].set_value(f"{_secs(self._dur[op])} s")
            # a party's reads 100 (its title says percent): as narrow as a
            # friend's 60, so its columns line up with their cards
            self._max_lbls[op].setText(str(self._cap(op)))
        t["warn"].set_value(WARNING_NAMES[self._warn])
        t["use"].set_value(_USE_NAMES[USES.index(self._use)])

    def _show_controls(self) -> None:
        cont, tap = self._use == "continuous", self._use == "tap"
        t = self._tiles
        for key in ("shock", "vibrate", "beep"):
            t[key].setEnabled(not cont and not self._blocked)
        t["shock_dur"].setEnabled(tap)
        t["vibrate_dur"].setEnabled(tap)
        self._dice_btn.setEnabled(not cont)
        random_on = self._random and not cont
        self._sliders["shock"].setVisible(not random_on)
        self._range.setVisible(random_on)
        hold = f" - up to {self._hold_s:g} s at a time, then a break" if self._hold_s else ""
        t["use"].setToolTip(
            "Use Mode - Tap: a press is one operation of the set Duration. Remote: it "
            "runs while you hold the button. Continuous: the sliders drive it for as long "
            "as they're above 0" + hold + ".")
        self.recolour()
        self._show_values()

    def set_caps(self, caps: Optional[Tuple[int, int, int]], hold_s: float = 0.0) -> None:
        """(shock cap, vibrate cap, longest pulse ms) on their side. Before
        the first, the card stands in percent; then it starts where those
        percentages were."""
        caps = tuple(caps) if caps else PARTY_CAPS
        if caps == self._caps and hold_s == self._hold_s:
            return
        first = not self._caps_known and caps != PARTY_CAPS
        prev, self._caps, self._hold_s = self._caps, caps, hold_s
        self._caps_known = self._caps_known or caps != PARTY_CAPS
        sliders = dict(self._sliders, lo=self._lo, hi=self._hi)
        for key, s in sliders.items():
            op = "vibrate" if key == "vibrate" else "shock"
            cap, old = self._cap(op), max(1, prev[1] if op == "vibrate" else prev[0])
            v = round(s.value() * cap / old) if first else s.value()
            s.blockSignals(True)
            s.setMaximum(cap)
            s.setValue(min(max(s.minimum(), v), cap))
            s.blockSignals(False)
        if self._before_cont:
            for op, v in list(self._before_cont.items()):
                cap, old = self._cap(op), max(1, prev[1] if op == "vibrate" else prev[0])
                self._before_cont[op] = min(max(1, round(v * cap / old) if first else v), cap)
        steps = self._durations()
        for op in self._dur:
            if self._dur[op] not in steps:
                self._dur[op] = min(steps, key=lambda d: abs(d - self._dur[op]))
        self._range.update()
        self._show_controls()

    def set_blocked(self, blocked: bool) -> None:
        """They paused all friends, or their Off is on: nothing would reach
        them, so Operate and Beep rest (STOP never does)."""
        if blocked != self._blocked:
            self._blocked = blocked
            self._show_controls()

    # -- the pickers
    def _open_picker(self, which: str) -> None:
        if self._picker is not None:
            try:
                self._picker.close_picker()
            except RuntimeError:
                pass
            self._picker = None
        big = self._big
        if which == "warn":
            opener = self._tiles["warn"]
            picker = Picker(self, opener, [(n, True) for n in _WARNING_PICKS], self._warn, 1,
                            self._warn_picked, self.hue, big, wide=True)
        elif which == "use":
            opener = self._tiles["use"]
            picker = Picker(self, opener, [(n, True) for n in _USE_PICKS],
                            USES.index(self._use), 1, self._mode_picked, "", big, wide=True)
        else:
            op = which[:-4]
            opener = self._tiles[which]
            steps = self._durations()
            options = [(_secs(d).lstrip("0") or "0", d in steps) for d in _DURATIONS_MS]
            extra = [d for d in steps if d not in _DURATIONS_MS]
            options += [(_secs(d).lstrip("0"), True) for d in extra]
            every = list(_DURATIONS_MS) + extra
            current = every.index(self._dur[op]) if self._dur[op] in every else -1
            picker = Picker(self, opener, options, current, 3,
                            lambda i, o=op, e=every: self._set_dur(o, e[i]),
                            self.hue if op == "shock" else self._vibrate_hue, big)
        self._picker = picker
        picker.destroyed.connect(lambda *_a, p=picker: self._picker_gone(p))
        picker.adjustSize()
        at = opener.mapTo(self, QPoint(0, 0))
        if which == "vibrate_dur":
            pos = QPoint(at.x() - picker.width() - 6, at.y())
        elif which == "use":
            pos = QPoint(at.x() + (opener.width() - picker.width()) // 2, at.y() + opener.height())
        else:
            pos = QPoint(at.x() + opener.width() + 6, at.y())
        picker.place(pos)

    def _picker_gone(self, picker) -> None:
        if self._picker is picker:
            self._picker = None

    def _set_dur(self, op: str, ms: int) -> None:
        self._dur[op] = ms
        self._show_values()

    # -- the user's hand
    def _mode_picked(self, i: int) -> None:
        self.release()
        was, self._use = self._use, USES[i]
        cont = self._use == "continuous"
        if cont and was != "continuous":
            # Continuous starts quiet; the strengths come back after it
            self._before_cont = {op: s.value() for op, s in self._sliders.items()}
        for op, s in self._sliders.items():
            s.blockSignals(True)
            s.setMinimum(0 if cont else 1)
            if cont:
                s.setValue(0)
            elif was == "continuous" and self._before_cont:
                s.setValue(self._before_cont[op])
            s.blockSignals(False)
        if not cont:
            self._before_cont = None
        self._show_controls()

    def _warn_picked(self, i: int) -> None:
        self._warn = i
        self._show_values()

    def _toggle_random(self) -> None:
        self._random = self._dice_btn.isChecked()
        if self._random and self._lo.value() >= self._hi.value():
            v = self._sliders["shock"].value()
            set_quiet(self._lo, max(1, v // 2))
            set_quiet(self._hi, max(v, 2))
        self._range.update()
        self._show_controls()

    def _strength_moved(self, op: str) -> None:
        self._show_values()
        v = self._sliders[op].value()
        if self._use == "continuous":
            # the slider is the control: above 0 it runs, at 0 it stops
            if op == "shock" and self._pending:
                if v > 0:
                    return                  # it starts at this when its warning ends
                self._warn_timer.stop()
                self._pending = ""
                self._holding = "shock"     # it is let go below
            if v > 0:
                if op == "shock" and self._holding != "shock" and self._warn:
                    self._start_warning(v)
                    return
                self._holding = op
                self._on_hold(op, self._to_fraction(op, v))
            elif self._holding == op:
                other = "vibrate" if op == "shock" else "shock"
                if self._sliders[other].value() > 0:
                    self._holding = ""
                    self._strength_moved(other)
                else:
                    self._holding = ""
                    self._on_release()
        elif self._holding == op and not (op == "shock" and self._random):
            self._on_hold(op, self._to_fraction(op, v))

    def _nudge(self, op: str, sign: int) -> None:
        step = sign * max(1, round(self._cap(op) * _NUDGE))
        if op == "shock" and self._random and self._use != "continuous":
            lo, hi = sorted((self._lo.value(), self._hi.value()))
            step = max(1 - lo, min(self._cap(op) - hi, step))     # the range moves whole
            set_quiet(self._lo, lo + step)
            set_quiet(self._hi, hi + step)
            self._range.update()
            self._show_values()
            return
        s = self._sliders[op]
        s.setValue(s.value() + step)

    def _start_warning(self, strength: int) -> None:
        """Remote / Continuous with a Warning: vibrate first, shock after."""
        self._pending, self._pending_v = "shock", strength
        self._holding = "vibrate"
        self._on_hold("vibrate", self._warn_fraction())
        self._warn_timer.start(max(1, self._warn_ms()))

    def _warned(self) -> None:
        if self._pending != "shock":
            return
        self._pending = ""
        v = self._sliders["shock"].value() if self._use == "continuous" else self._pending_v
        if v > 0:
            self._holding = "shock"
            self._on_hold("shock", self._to_fraction("shock", v))

    def _tap(self, op: str) -> None:
        if self._use != "tap" or self._blocked:
            return
        warn_ms = self._warn_ms() if op == "shock" else 0
        strength = self._strength(op) if op != "beep" else 1
        self._on_fire(op, self._to_fraction(op, strength) if op != "beep" else 0.0,
                      self._length(op if op != "beep" else "vibrate"),
                      warn_ms, self._warn_fraction())

    def _press(self, op: str) -> None:
        if self._use != "remote" or self._blocked:
            return
        if op == "shock" and self._warn:
            self._start_warning(self._strength("shock"))
            return
        self._holding = op
        strength = self._strength(op) if op != "beep" else 1
        self._on_hold(op, self._to_fraction(op, strength) if op != "beep" else 0.0)

    def _unpress(self, op: str) -> None:
        if self._use == "remote":
            self.release()

    def _stop(self) -> None:
        self._warn_timer.stop()
        self._holding = self._pending = ""
        if self._use == "continuous":
            for s in self._sliders.values():
                set_quiet(s, 0)
            self._show_values()
        self._on_stop()

    def stop(self) -> None:
        """Stop all (the section's button): as this card's own STOP."""
        self._stop()

    # -- the panel rebuilds (a toy connects, control mode ...)
    def release(self) -> None:
        """Let go of whatever this card holds (Remote or Continuous, a
        warning included): the card is about to go, or the mode changes."""
        self._warn_timer.stop()
        if self._holding or self._pending:
            self._holding = self._pending = ""
            self._on_release()

    def settings(self) -> dict:
        """How the card is set, for the card that replaces it."""
        sliders = dict(self._sliders, lo=self._lo, hi=self._hi)
        return {"use": self._use, "warn": self._warn, "random": self._random,
                "dur": dict(self._dur), "values": {k: sl.value() for k, sl in sliders.items()},
                "before": dict(self._before_cont) if self._before_cont else None}

    def restore(self, st: dict) -> None:
        """Set up like the card this one replaces (after set_caps). A
        Continuous card comes back quiet: its hold was let go."""
        self._use = st["use"]
        self._warn = st["warn"]
        self._random = st["random"]
        self._dice_btn.setChecked(self._random)
        self._dur.update(st["dur"])
        self._before_cont = dict(st["before"]) if st.get("before") else None
        cont = self._use == "continuous"
        sliders = dict(self._sliders, lo=self._lo, hi=self._hi)
        for key, value in st["values"].items():
            sl = sliders[key]
            if key in self._sliders:
                sl.setMinimum(0 if cont else 1)
                if cont:
                    value = 0
            set_quiet(sl, min(max(value, sl.minimum()), sl.maximum()))
        self._range.update()
        self._show_controls()
