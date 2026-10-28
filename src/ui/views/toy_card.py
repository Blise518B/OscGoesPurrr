"""Compact cards for the Friends panel: one per toy, one per shocker.

A ToyCard drives one of a friend's toys (or all of them). Its modes: Off
(the toy at 0 -- the card then only asks you to pick a mode), Direct
control (the level you set), the auto modes (Sine, Square,
Triangle, Saw, Random, Heartbeat, Build-up) with speed and a low-high
range, and Oscillate (a swing around your level, as deep as you set). While
an auto mode plays, a small graph shows what it sends and what their toy
does. Higher / Override decides how your level meets their own output.

Cards only draw and call back with primitive values; the Friends view wires
those to the controller. Strengths go out as 0..1 of the RECEIVER's caps;
a card that knows those caps (`set_caps`) shows the real numbers, one that
doesn't (a group: everyone's caps differ) shows percentages. `big` makes
everything larger for control mode (VR).
"""

import time
from collections import deque
from typing import Callable, Optional, Tuple

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, QTimer
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QButtonGroup, QFrame, QLabel, QPushButton, QWidget

import friend_patterns
from ui import lovense_icons
from ui import theme
from ui.icons import wave_icon
from ui.layout_helpers import FlowLayout, hbox, vbox
from remote_protocol import ALL_TOYS
from ui.views.card_parts import (
    bigger, fmt_period, hue_color, period_to_slider, segmented, set_quiet, slider,
    slider_to_period, small_label,
)
from ui.widgets import RainbowMeter

_DEFAULT_PERIOD = {"sine": 2.0, "square": 1.0, "triangle": 2.0, "saw": 2.0,
                   "random": 1.5, "heart": 1.0, "build": 30.0, "osc": 2.0}
_MODES = ("off", "linear") + friend_patterns.WAVES
_FIRST_ROW = ("off", "linear", "random")      # a bit bigger, above the waves
_GRAPH_S = 6.0


class _Graph(QWidget):
    """The last few seconds of what you send -- the level their toy gets
    (their strength, Off and the toy's max aside; no chain, no smoothing).
    Ticks only while shown."""

    def __init__(self, sample: Callable[[], float], hue: str, big: bool):
        super().__init__()
        self._sample, self._hue = sample, hue
        self._hist: deque = deque()
        self.setFixedHeight(64 if big else 42)
        self._timer = QTimer(self)
        self._timer.setInterval(33)
        self._timer.timeout.connect(self._tick)

    def showEvent(self, event) -> None:
        self._hist.clear()
        self._timer.start()
        super().showEvent(event)

    def hideEvent(self, event) -> None:
        self._timer.stop()
        super().hideEvent(event)

    def _tick(self) -> None:
        now = time.monotonic()
        self._hist.append((now, self._sample()))
        while self._hist and now - self._hist[0][0] > _GRAPH_S:
            self._hist.popleft()
        self.update()

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(theme.CHROME["well"]))
        p.drawRoundedRect(QRectF(0, 0, w, h), 6, 6)
        if len(self._hist) < 2:
            return
        now = self._hist[-1][0]

        def xy(t, val):
            return QPointF(w - 2 - (now - t) / _GRAPH_S * (w - 4), h - 3 - val * (h - 6))

        path = QPainterPath()
        for i, (t, val) in enumerate(self._hist):
            pt = xy(t, max(0.0, min(1.0, val)))
            path.lineTo(pt) if i else path.moveTo(pt)
        p.setPen(QPen(QColor(hue_color(self._hue)), 2.0))
        p.setBrush(Qt.NoBrush)
        p.drawPath(path)


class ToyCard(QFrame):
    """One toy of a friend's (or "all their toys"): Off / Linear / auto
    modes / Oscillate, Higher / Override."""

    def __init__(self, toy: str, title: str, hue: str,
                 on_level: Callable[[float], None],
                 on_override: Callable[[bool], None],
                 on_pattern: Callable[[str, float, float, float], None],
                 meter: bool = True, big: bool = False):
        super().__init__()
        self.toy, self.hue = toy, hue
        self._big = big
        self._on_level, self._on_override, self._on_pattern = on_level, on_override, on_pattern
        self._mode = "off"
        self._level = 0.0                       # Direct control's level, kept while other modes run
        self._period, self._lo, self._hi = 2.0, 0.2, 0.8
        self._center, self._depth = 0.5, 0.2    # Oscillate
        self._shown = None                      # what _show_mode last drew
        self._t0 = self._ts = time.monotonic()
        self._ph0 = 0.0
        self.setObjectName("friendCard")
        self.setProperty("hue", hue)
        bigger(self, big)
        lay = vbox(12 if big else 8, 8 if big else 4)
        self.setLayout(lay)

        head = hbox(0, 6)
        key = lovense_icons.detect_toy_key(title) if toy != ALL_TOYS else None
        pix = lovense_icons.load_pixmap(key, size=32 if big else 22, circular=True) if key else None
        if pix is not None:
            icon = QLabel()
            icon.setPixmap(pix)
            head.addWidget(icon)
        name = bigger(QLabel(title), big)
        name.setObjectName("friendCardName")
        name.setTextFormat(Qt.PlainText)        # their toy's name, never markup
        head.addWidget(name)
        self._out = small_label(big=big)
        head.addWidget(self._out)
        self._battery = small_label(big=big)
        self._battery.setToolTip("Their toy's battery")
        self._battery.hide()
        head.addWidget(self._battery)
        head.addStretch(1)
        seg, self._over = segmented(["Higher", "Override"], hue,
                               lambda i: self._on_override(i == 1), big)
        self._over_box = seg
        seg.setToolTip("Higher: whichever is higher, their own output (SPS, contacts) "
                       "or yours, wins. Override: while you drive this, yours "
                       "replaces theirs. Their Off, Pause, strength and the "
                       "toy's max still hold.")
        head.addWidget(seg)
        lay.addLayout(head)

        self._hint = small_label("Select a waveform to begin", big=big)
        lay.addWidget(self._hint)

        # Direct control's level -- Oscillate swings around it
        self._level_row = QWidget()
        row = hbox(0, 6)
        self._level_row.setLayout(row)
        self._level_s = slider(hue, big=big)
        self._level_lbl = small_label("0 %", muted=False, big=big)
        self._level_lbl.setMinimumWidth(44 if big else 36)
        self._level_lbl.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self._level_s.valueChanged.connect(self._level_moved)
        row.addWidget(self._level_s, 1)
        row.addWidget(self._level_lbl)
        lay.addWidget(self._level_row)

        # Oscillate's depth
        self._depth_row, self._depth_s, self._depth_lbl = self._slider_row("depth", 0, 500, big)
        self._depth_s.valueChanged.connect(self._depth_moved)
        lay.addWidget(self._depth_row)

        # an auto mode's low-high range
        self._range = QWidget()
        row = hbox(0, 6)
        self._range.setLayout(row)
        self._lo_s, self._hi_s = slider(hue, big=big), slider(hue, big=big)
        self._range_lbl = small_label(big=big)
        self._range_lbl.setMinimumWidth(62)
        self._range_lbl.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        for label, s in (("low", self._lo_s), ("high", self._hi_s)):
            row.addWidget(small_label(label, big=big))
            row.addWidget(s, 1)
            s.valueChanged.connect(self._range_moved)
        row.addWidget(self._range_lbl)
        lay.addWidget(self._range)

        self._chips = QButtonGroup(self)
        self._chips.setExclusive(True)
        rows = {}
        for key in ("main", "waves"):
            box = QWidget()
            flow = FlowLayout(margin=0, h_spacing=3, v_spacing=3)
            box.setLayout(flow)
            rows[key] = (box, flow)
        for i, mode in enumerate(_MODES):
            first = mode in _FIRST_ROW
            b = QPushButton({"off": "Off", "linear": " Direct control", "random": " Random"}.get(mode, ""))
            b.setCheckable(True)
            b.setProperty("role", "chip")
            b.setProperty("hue", hue)
            if first:
                b.setProperty("row", "main")
            bigger(b, big)
            if mode != "off":
                b.setIconSize(QSize(30, 20) if big else QSize(22, 14))
            tip = {"off": "Off: their toy at 0",
                   "linear": "Direct control: the level you set with the slider"}.get(
                mode, f"Auto mode: {friend_patterns.LABELS.get(mode, mode)}")
            if mode == "osc":
                tip = "Oscillate: a swing around the level you set, as deep as you set"
            b.setToolTip(tip)
            b.setCursor(Qt.PointingHandCursor)
            self._chips.addButton(b, i)
            rows["main" if first else "waves"][1].addWidget(b)
        self._chips.button(_MODES.index("off")).setChecked(True)
        self._chips.idClicked.connect(lambda i: self._pick(_MODES[i]))
        lay.addWidget(rows["main"][0])
        lay.addWidget(rows["waves"][0])

        self._speed_row, self._speed_s, self._speed_lbl = self._slider_row("speed", 0, 1000, big)
        self._speed_s.setInvertedAppearance(True)       # right = faster
        self._speed_s.setInvertedControls(True)
        self._speed_s.valueChanged.connect(self._speed_moved)
        lay.addWidget(self._speed_row)

        self._graph = _Graph(self._graph_sample, hue, big)
        self._graph.setToolTip("What you send: the level their toy gets, straight - no "
                               "chain or smoothing on their side (their strength, Off and "
                               "the toy's max still apply)")
        lay.addWidget(self._graph)

        self._meter = None
        if meter:
            self._meter = RainbowMeter(maximum=1000)
            self._meter.setFixedHeight(6 if big else 4)
            self._meter.setToolTip("What this toy is doing on their side right now")
            lay.addWidget(self._meter)
        self.recolour()
        self._show_mode()

    def _slider_row(self, label: str, lo: int, hi: int, big: bool):
        box = QWidget()
        row = hbox(0, 6)
        box.setLayout(row)
        row.addWidget(small_label(label, big=big))
        s = slider(self.hue, lo, hi, big)
        row.addWidget(s, 1)
        val = small_label(big=big)
        val.setMinimumWidth(62)
        val.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        row.addWidget(val)
        return box, s, val

    # -- what the mode plays (also on this side, for the graph)
    def _pattern(self) -> Optional[Tuple[str, float, float, float]]:
        if self._mode in ("off", "linear"):
            return None
        if self._mode == "osc":
            lo = max(0.0, self._center - self._depth)
            hi = min(1.0, self._center + self._depth)
            return friend_patterns.clean("osc", self._period, lo, hi)
        return friend_patterns.clean(self._mode, self._period, self._lo, self._hi)

    def _graph_sample(self) -> float:
        pat = self._pattern()
        if pat is None:
            return self._level if self._mode == "linear" else 0.0
        now = time.monotonic()
        phase = self._ph0 + (now - self._t0) / pat[1]
        return friend_patterns.level(pat, now - self._ts, phase)

    def _restart_cycle(self) -> None:
        self._t0 = self._ts = time.monotonic()
        self._ph0 = 0.0

    def _keep_cycle(self, new_period: float) -> None:
        now = time.monotonic()
        self._ph0 += (now - self._t0) / max(0.01, self._period)
        self._t0 = now
        self._period = new_period

    # -- the user's hand
    def _pick(self, mode: str) -> None:
        was = self._mode
        self._mode = mode
        if mode == "off":
            self._on_pattern("", self._period, 0.0, 0.0)
            self._on_level(0.0)
        elif mode == "linear":
            self._on_pattern("", self._period, 0.0, 0.0)
            self._on_level(self._level)
        else:
            if mode != was:
                self._period = _DEFAULT_PERIOD.get(mode, 2.0)
                self._restart_cycle()
                if mode == "osc":
                    self._center = self._level if self._level > 0 else 0.5
            self._on_level(0.0)          # the mode is the level now
            self._send_pattern()
        self._show_mode()

    def _level_moved(self, x: int) -> None:
        v = x / 1000.0
        self._level_lbl.setText(f"{round(v * 100)} %")
        if self._mode == "osc":
            self._center = v
            self._send_pattern()
            return
        self._level = v
        if self._mode == "linear":
            self._on_level(v)

    def _depth_moved(self, x: int) -> None:
        self._depth = x / 1000.0
        self._depth_lbl.setText(f"± {round(self._depth * 100)} %")
        self._send_pattern()

    def _range_moved(self, _x: int) -> None:
        self._lo, self._hi = self._lo_s.value() / 1000.0, self._hi_s.value() / 1000.0
        lo, hi = sorted((self._lo, self._hi))
        self._range_lbl.setText(f"{round(lo * 100)}–{round(hi * 100)} %")
        self._send_pattern()

    def _speed_moved(self, x: int) -> None:
        self._keep_cycle(slider_to_period(x))
        self._speed_lbl.setText(fmt_period(self._period))
        self._send_pattern()

    def _send_pattern(self) -> None:
        pat = self._pattern()
        if pat is not None:
            self._on_pattern(*pat)

    # -- showing state
    def recolour(self) -> None:
        """Paint the mode icons in the card's colour as it is now -- they
        are pixmaps, so a colour change (Appearance) has to redraw them."""
        big, color = self._big, hue_color(self.hue)
        for i, mode in enumerate(_MODES):
            if mode != "off":
                self._chips.button(i).setIcon(
                    wave_icon(mode, color, 30 if big else 22, 20 if big else 14))

    def _signature(self) -> tuple:
        return (self._mode, self._level, self._period, self._lo, self._hi,
                self._center, self._depth)

    def _show_mode(self) -> None:
        self._shown = self._signature()
        mode = self._mode
        auto = mode not in ("off", "linear")
        self._hint.setVisible(mode == "off")
        # Higher / Override stay put whatever the mode: a card that grew a
        # header row when its toy started knocked its neighbours out of line
        self._level_row.setVisible(mode in ("linear", "osc"))
        self._depth_row.setVisible(mode == "osc")
        self._range.setVisible(auto and mode != "osc")
        self._speed_row.setVisible(auto)
        self._graph.setVisible(auto)
        if self._meter is not None:
            self._meter.setVisible(mode == "linear")
        set_quiet(self._level_s, round((self._center if mode == "osc" else self._level) * 1000))
        self._level_lbl.setText(f"{round((self._center if mode == 'osc' else self._level) * 100)} %")
        set_quiet(self._depth_s, round(self._depth * 1000))
        self._depth_lbl.setText(f"± {round(self._depth * 100)} %")
        set_quiet(self._lo_s, round(self._lo * 1000))
        set_quiet(self._hi_s, round(self._hi * 1000))
        self._range_lbl.setText(f"{round(self._lo * 100)}–{round(self._hi * 100)} %")
        set_quiet(self._speed_s, period_to_slider(self._period))
        self._speed_lbl.setText(fmt_period(self._period))

    def set_battery(self, pct: Optional[int]) -> None:
        """Their toy's battery in percent, or None (it reports none)."""
        text = "" if pct is None else f"🔋 {int(pct)} %"
        if self._battery.text() != text:
            self._battery.setText(text)
            # low: in the warning colour, like Home's
            low = "true" if pct is not None and pct <= 20 else "false"
            if self._battery.property("low") != low:
                self._battery.setProperty("low", low)
                self._battery.style().unpolish(self._battery)
                self._battery.style().polish(self._battery)
        self._battery.setVisible(pct is not None)

    def busy(self) -> bool:
        return any(s.isSliderDown() for s in
                   (self._level_s, self._depth_s, self._lo_s, self._hi_s, self._speed_s))

    def set_state(self, level: float, override: bool, pattern, output: Optional[float]) -> None:
        """What the controller says is set (and what the toy does) --
        without echoing it back, and never under the user's hand."""
        if output is not None:
            text = f"out {round(output * 100)} %"
            if self._out.text() != text:
                self._out.setText(text)
            if self._meter is not None:
                self._meter.setValue(round(output * 1000))
        if self.busy():
            return
        btn = self._over.button(1 if override else 0)
        if not btn.isChecked():
            btn.setChecked(True)
        if pattern:
            mode = pattern[0]
            if mode != self._mode:
                self._restart_cycle()
            self._period = pattern[1]
            if mode == "osc":
                self._center = (pattern[2] + pattern[3]) / 2
                self._depth = (pattern[3] - pattern[2]) / 2
            else:
                self._lo, self._hi = pattern[2], pattern[3]
        elif level > 0:
            mode, self._level = "linear", level
        elif self._mode in ("off", "linear"):
            mode = self._mode
            if mode == "linear":
                self._level = level
        else:
            mode = "linear"                    # an auto mode ended elsewhere
        self._mode = mode
        chip = self._chips.button(_MODES.index(mode))
        if not chip.isChecked():
            chip.setChecked(True)
        if self._signature() != self._shown:      # the page refreshes often
            self._show_mode()
