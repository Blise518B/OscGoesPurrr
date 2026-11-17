"""An OpenShockCard is OpenShock's own shocker card, for one of a friend's
shockers (or a party of them -- shock_party.py), laid out the way
OpenShock's web app has it (its Classic control and Live control, compared
2026-11-15; read for names, order and behaviour, none of its code used), so
someone used to OpenShock is at home -- the Friends panel's other face
(shocker_layout.py; Blise's call, 2026-11-15, PiShock's panel stays the
default):

    1 · Collar                       [Party] [LIVE]
       ◔ 40%   ◷ 5 s                     (Max Intensity, Max Duration)
      ( Intensity )   ( Duration )        two round dials
      [   🔊   ]  [   〰   ]  [   ⚡   ]     Sound · Vibrate · Shock

  * Intensity and Duration go with every button, as OpenShock's: one
    Intensity for Vibrate and Shock (each stops at its own cap), the
    Duration from 0.3 s in tenths up to their longest pulse.
  * A press sends one operation of the Duration; the button stays lit
    while it runs, and pressing it again stops it (OpenShock's Stop).
  * LIVE (in the corner, as OpenShock's) swaps the dials for Live control:
    pick Sound, Vibrate or Shock, then hold and drag on the pad -- the
    strength follows your finger, top = their strongest, until you let go.
    It holds the shocker like PiShock's Remote mode: sent on change, over
    the friend link as a hold, and the receiver's engine still caps it,
    ends it after their longest hold and rests it; it stops once the
    updates stop.
  * Their shocker's switches (`set_rules`): an op switched off there greys
    its button with the reason, said under the name too. OpenShock has no
    Warning button of its own, so nothing else changes.

Same contract as ShockerCard, so the panel, Party Mode and Me take either:
on_fire(op, intensity, length, warn_ms, warn_intensity), on_hold(op,
intensity), on_release(), on_stop(); strengths 0..1 of the RECEIVER's caps
(`set_caps`; a party keeps PARTY_CAPS: percent of each one's and real
seconds up to 10 s). Both layouts send the same message for the same press.
"""

from typing import Callable, Dict, Optional, Tuple

from PySide6.QtCore import QSize, Qt, QTimer
from PySide6.QtWidgets import QCheckBox, QFrame, QLabel, QPushButton, QWidget

import shocker_layout as layout
from ui import theme
from ui.icons import glyph_icon
from ui.layout_helpers import hbox, vbox
from ui.views.card_parts import bigger, hue_color
from ui.views.openshock_parts import Dial, LivePad
from ui.views.shocker_card import PARTY_CAPS

_GLYPHS = {"beep": "sound", "vibrate": "waves", "shock": "bolt"}
_TIPS = {
    "beep": "Sound: a beep for the Duration",
    "vibrate": "Vibrate at the Intensity for the Duration",
    "shock": "Shock at the Intensity for the Duration",
}
_LIVE_TIPS = {
    "beep": "Sound: Live control beeps while you hold the pad",
    "vibrate": "Vibrate: Live control vibrates at the strength under your finger",
    "shock": "Shock: Live control shocks at the strength under your finger",
}
_RUNNING_TIP = "Running - press it again to stop it"
_LIVE_TIP = ("Live control: hold and drag on the pad, and the strength follows your finger "
             "until you let go - top is their strongest. It holds the shocker like PiShock's "
             "Remote mode: their caps, longest hold and the rest after it still hold, and it "
             "stops when you let go or the link goes quiet.")


def _secs(ms: int) -> str:
    return f"{ms / 1000:g}"


class OpenShockCard(QFrame):
    """OpenShock's shocker card (see the module's notes)."""

    def __init__(self, title: str, hue: str,
                 on_fire: Callable[[str, float, float, int, float], None],
                 on_hold: Callable[[str, float], None],
                 on_release: Callable[[], None],
                 on_stop: Callable[[], None],
                 big: bool = False, vibrate_hue: str = "pink", party_box: bool = False):
        super().__init__()
        self.hue, self._vibrate_hue, self._big = hue, vibrate_hue, big
        self._on_fire, self._on_hold, self._on_release, self._on_stop = (
            on_fire, on_hold, on_release, on_stop)
        self._caps: Tuple[int, int, int] = PARTY_CAPS            # shock, vibrate, ms
        self._caps_known = False
        self._hold_s = 0.0
        self._blocked = False
        self._ops = {"shock", "vibrate", "beep"}
        self._why: Dict[str, str] = {}
        self._warn_ok = True
        self._active = ""                      # a pressed op still running
        self._live = False
        self._live_op = layout.LIVE_DEFAULT_OP
        self._holding = ""                     # what Live control holds right now
        self._active_timer = QTimer(self)
        self._active_timer.setSingleShot(True)
        self._active_timer.timeout.connect(self._ran_out)
        self.setObjectName("friendCard")
        self.setProperty("hue", hue)
        self.setProperty("layout", layout.OPENSHOCK)
        bigger(self, big)
        lay = vbox(10 if big else 8, 8 if big else 6)
        self.setLayout(lay)

        head = hbox(0, 6)
        name = bigger(QLabel(title), big)
        name.setObjectName("friendCardName")
        name.setTextFormat(Qt.PlainText)            # their shocker's name, never markup
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
        self.live_tag = bigger(QPushButton("LIVE"), big)
        self.live_tag.setProperty("role", "liveTag")
        self.live_tag.setCheckable(True)
        self.live_tag.setCursor(Qt.PointingHandCursor)
        self.live_tag.toggled.connect(self._live_toggled)
        head.addWidget(self.live_tag)
        lay.addLayout(head)
        # why a button is greyed, said once under the name (a VR pointer
        # that can't hover sees it too) -- as the PiShock card does
        self._why_line = bigger(QLabel(""), big)
        self._why_line.setObjectName("cardHint")
        self._why_line.setProperty("muted", "true")
        self._why_line.setWordWrap(True)
        self._why_line.setVisible(False)
        lay.addWidget(self._why_line)

        # Max Intensity, Max Duration: their caps, OpenShock's limits line
        limits = hbox(0, 12)
        limits.addStretch(1)
        self._lim_icons: Dict[str, QLabel] = {}
        self._lim_text: Dict[str, QLabel] = {}
        for key, tip in (("int", "Max Intensity: the strongest you may send on this shocker - "
                                 "its own cap on their side"),
                         ("dur", "Max Duration: their longest pulse")):
            icon, text = QLabel(), bigger(QLabel(""), big)
            text.setProperty("muted", "true")
            box = QWidget()
            row = hbox(0, 4)
            box.setLayout(row)
            row.addWidget(icon)
            row.addWidget(text)
            box.setToolTip(tip)
            limits.addWidget(box)
            self._lim_icons[key], self._lim_text[key] = icon, text
        limits.addStretch(1)
        lay.addLayout(limits)

        # Classic: the two dials and the three buttons
        self._classic = QWidget()
        cl = vbox(0, 8 if big else 6)
        self._classic.setLayout(cl)
        dials = hbox(0, 8)
        dials.addStretch(1)
        self.intensity = Dial("Intensity", hue, 1, 100, 1, layout.INTENSITY_DEFAULT, big=big)
        self.intensity.setToolTip("Intensity: how strong Vibrate and Shock are - up to their "
                                  "max, each stopping at its own")
        lo, hi = layout.duration_range(PARTY_CAPS[2])
        self.duration = Dial("Duration", hue, lo, hi, layout.DURATION_STEP_MS,
                             layout.DURATION_DEFAULT_MS, fmt=_secs, big=big)
        self.duration.setToolTip("Duration: how long a press runs, in seconds - from 0.3 s "
                                 "up to their longest pulse")
        for d in (self.intensity, self.duration):
            d.valueChanged.connect(lambda _v: self._show_values())
            dials.addWidget(d)
        dials.addStretch(1)
        cl.addLayout(dials)
        self.buttons: Dict[str, QPushButton] = {}
        row = hbox(0, 8)
        for op in layout.OS_OPS:
            b = self._op_button(op)
            b.setCheckable(True)            # lit while its press runs
            b.clicked.connect(lambda _=False, o=op: self._press(o))
            self.buttons[op] = b
            row.addWidget(b, 1)
        cl.addLayout(row)
        lay.addWidget(self._classic)

        # Live control: what it plays, and the pad
        self._live_box = QWidget()
        ll = vbox(0, 8 if big else 6)
        self._live_box.setLayout(ll)
        self.live_types: Dict[str, QPushButton] = {}
        row = hbox(0, 8)
        for op in layout.OS_OPS:
            b = self._op_button(op)
            b.setCheckable(True)
            b.clicked.connect(lambda _=False, o=op: self._live_pick(o))
            self.live_types[op] = b
            row.addWidget(b, 1)
        ll.addLayout(row)
        self.pad = LivePad(self._op_hue(self._live_op), self._live_level, self._live_let_go, big=big)
        self.pad.setToolTip(_LIVE_TIP)
        ll.addWidget(self.pad)
        self._live_box.setVisible(False)
        lay.addWidget(self._live_box)
        lay.addStretch(1)

        self.recolour()
        self._show_controls()
        self._wide = lay.minimumSize().width()

    # -- building
    def _op_hue(self, op: str) -> str:
        return {"shock": self.hue, "vibrate": self._vibrate_hue}.get(op, "")

    def _op_button(self, op: str) -> QPushButton:
        b = bigger(QPushButton(), self._big)
        b.setProperty("role", "osButton")
        b.setProperty("hue", self._op_hue(op))
        b.setCursor(Qt.PointingHandCursor)
        b.setAccessibleName(layout.OP_NAMES[op])
        return b

    def wide_width(self) -> int:
        """The width it needs -- CardGrid puts two side by side only when
        both get this much."""
        return self._wide

    def minimumSizeHint(self):  # noqa: N802
        return QSize(self._wide, self.layout().minimumSize().height())

    def recolour(self) -> None:
        """Paint the glyphs in the card's colours as they are now (they are
        pixmaps, so a colour change has to redraw them)."""
        v = theme.qss_vars()
        px = 22 if self._big else 18
        for op in layout.OS_OPS:
            for group in (self.buttons, self.live_types):
                b = group[op]
                hue = self._op_hue(op)
                color = v["dim"] if not b.isEnabled() else (hue_color(hue) if hue else v["txt"])
                kind = "stop" if group is self.buttons and op == self._active else _GLYPHS[op]
                if kind == "stop" and b.isEnabled():
                    color = v["err"]
                b.setIcon(glyph_icon(kind, color, 20))
                b.setIconSize(QSize(px, px))
        small = 18 if self._big else 14
        for key, kind in (("int", "gauge"), ("dur", "clock")):
            self._lim_icons[key].setPixmap(glyph_icon(kind, v["muted"], small).pixmap(
                QSize(small, small)))
        self.intensity.update()
        self.duration.update()
        self.pad.update()

    # -- numbers
    def _cap(self, op: str) -> int:
        return max(1, self._caps[1] if op == "vibrate" else self._caps[0])

    def _strength(self, op: str) -> int:
        """The Intensity as it lands on this op: never past its own cap."""
        return min(self.intensity.value(), self._cap(op))

    def _length(self) -> float:
        return layout.length_fraction(self.duration.value(), self._caps[2])

    def _show_values(self) -> None:
        shock, vib = self._cap("shock"), self._cap("vibrate")
        text = f"{shock}%" if shock == vib else f"Shock {shock}% · Vibrate {vib}%"
        for key, t in (("int", text), ("dur", f"{_secs(self._caps[2])} s")):
            if self._lim_text[key].text() != t:
                self._lim_text[key].setText(t)

    def _show_controls(self) -> None:
        ops, blocked = self._ops, self._blocked
        for op in layout.OS_OPS:
            ok = op in ops and not blocked
            why = self._why.get(op, "") if op not in ops else ""
            for group, tips in ((self.buttons, _TIPS), (self.live_types, _LIVE_TIPS)):
                b = group[op]
                b.setEnabled(ok)
                tip = why or tips[op]
                if group is self.buttons and op == self._active:
                    tip = _RUNNING_TIP
                if b.toolTip() != tip:
                    b.setToolTip(tip)
            self.live_types[op].setChecked(op == self._live_op)
            self.buttons[op].setChecked(op == self._active)
        self.intensity.setEnabled(bool({"shock", "vibrate"} & ops))
        self.duration.setEnabled(bool(ops))
        if self.live_tag.toolTip() != _LIVE_TIP:
            self.live_tag.setToolTip(_LIVE_TIP)
        self.pad.setEnabled(self._live_op in ops and not blocked)
        self.pad.set_hue(self._op_hue(self._live_op))
        self.pad.set_cap(self._cap(self._live_op) if self._live_op != "beep" else 100)
        lines = list(dict.fromkeys(self._why[op] for op in ("shock", "vibrate", "beep")
                                   if op not in ops and self._why.get(op)))
        text = ". ".join(lines) + ("." if lines else "")
        if self._why_line.text() != text:
            self._why_line.setText(text)
        self._why_line.setVisible(bool(text))
        if self._live_box.isHidden() == self._live:
            # Classic <-> Live control: the card changes height, and the
            # grid it sits in has to hear it (as the PiShock card's fold)
            self._classic.setVisible(not self._live)
            self._live_box.setVisible(self._live)
            self.layout().invalidate()
            self.updateGeometry()
        self.recolour()
        self._show_values()

    def set_caps(self, caps: Optional[Tuple[int, int, int]], hold_s: float = 0.0) -> None:
        """(shock cap, vibrate cap, longest pulse ms) on their side. Before
        the first, the card stands in percent; then the Intensity starts
        where that percentage was."""
        caps = tuple(caps) if caps else PARTY_CAPS
        if caps == self._caps and hold_s == self._hold_s:
            return
        first = not self._caps_known and caps != PARTY_CAPS
        prev, self._caps, self._hold_s = self._caps, caps, hold_s
        self._caps_known = self._caps_known or caps != PARTY_CAPS
        top, old = max(self._cap("shock"), self._cap("vibrate")), max(1, prev[0], prev[1])
        v = self.intensity.value()
        self.intensity.setRange(1, top)
        self.intensity.setValue(round(v * top / old) if first else v)
        lo, hi = layout.duration_range(caps[2])
        self.duration.setRange(lo, hi)
        self._show_controls()

    def set_rules(self, ops, why: Optional[Dict[str, str]] = None,
                  warn_ok: bool = True) -> None:
        """What that shocker's own switches let you do -- the PiShock
        card's contract: the ops you may send, whether a warning can play
        there, and `why` an op isn't there."""
        ops, warn_ok = set(ops), bool(warn_ok)
        why = {k: text for k, text in (why or {}).items()
               if text and (k not in ops if k != "warn" else not warn_ok)}
        if (ops, why, warn_ok) == (self._ops, self._why, self._warn_ok):
            return
        self._ops, self._why, self._warn_ok = ops, why, warn_ok
        if self._holding and self._holding not in ops:
            self.release()
        self._show_controls()

    def set_blocked(self, blocked: bool) -> None:
        """They paused all friends, or their Off is on: nothing would reach
        them, so the buttons and the pad rest."""
        if blocked != self._blocked:
            self._blocked = blocked
            if blocked:
                self.release()
            self._show_controls()

    # -- the hand: Classic
    def _press(self, op: str) -> None:
        if self._blocked or op not in self._ops:
            return
        if op == self._active:
            self._stop()                     # pressed again: OpenShock's Stop
            return
        if op == "beep":
            self._on_fire("beep", 0.0, self._length(), 0, 0.0)
        else:
            strength = self._strength(op)
            warn_fraction = layout.to_fraction(min(strength, self._cap("vibrate")),
                                               self._cap("vibrate"))
            self._on_fire(op, layout.to_fraction(strength, self._cap(op)), self._length(),
                          0, warn_fraction)
        self._active = op
        self._active_timer.start(max(1, self.duration.value()))
        self._show_controls()

    def _ran_out(self) -> None:
        if self._active:
            self._active = ""
            self._show_controls()

    def _stop(self) -> None:
        self._active_timer.stop()
        self._active = ""
        if self._holding:
            self._holding = ""
            self.pad.let_go(quiet=True)
        self._on_stop()
        self._show_controls()

    # -- the hand: Live control
    def _live_toggled(self, on: bool) -> None:
        if not on:
            self.release()
        self._live = on
        self._show_controls()

    def _live_pick(self, op: str) -> None:
        if op not in self._ops:
            self._show_controls()
            return
        self._live_op = op
        # the pad tops out at this op's cap now (a finger on it moves with
        # that, and _live_level sends it) ...
        self._show_controls()
        if self._holding and self._holding != op and self.pad.strength() > 0:
            # ... else still holding: it plays the new one at once
            self._holding = op
            self._on_hold(op, self._live_fraction(self.pad.strength()))

    def _live_fraction(self, strength: int) -> float:
        if self._live_op == "beep":
            return 0.0
        return layout.to_fraction(min(strength, self._cap(self._live_op)), self._cap(self._live_op))

    def _live_level(self, strength: int) -> None:
        """The pad's strength changed (sent on change, like a toy level)."""
        op = self._live_op
        if self._blocked or op not in self._ops or not self._live:
            return
        if strength <= 0:
            if self._holding:
                self._holding = ""
                self._on_release()
            return
        self._holding = op
        self._on_hold(op, self._live_fraction(strength))

    def _live_let_go(self) -> None:
        if self._holding:
            self._holding = ""
            self._on_release()

    def live(self) -> bool:
        return self._live

    # -- the panel
    def stop(self) -> None:
        """Stop all (the section's button): this shocker stops now."""
        self._stop()

    def release(self) -> None:
        """Let go of whatever Live control holds: the card is about to go,
        Live control ends, or their rules changed."""
        self.pad.let_go(quiet=True)
        if self._holding:
            self._holding = ""
            self._on_release()

    def settings(self) -> dict:
        """How the card is set, for the card that replaces it."""
        return {"layout": layout.OPENSHOCK, "intensity": self.intensity.value(),
                "duration": self.duration.value(), "live": self._live,
                "live_op": self._live_op}

    def restore(self, st: dict) -> None:
        """Set up like the card this one replaces (after set_caps). Live
        control comes back on, but nothing held: its hold was let go."""
        if st.get("layout") != layout.OPENSHOCK:
            return                           # a PiShock card's: start fresh
        self.intensity.setValue(st.get("intensity", layout.INTENSITY_DEFAULT))
        self.duration.setValue(st.get("duration", layout.DURATION_DEFAULT_MS))
        self._live_op = st.get("live_op", layout.LIVE_DEFAULT_OP)
        if st.get("live"):
            self.live_tag.setChecked(True)
        self._show_controls()
