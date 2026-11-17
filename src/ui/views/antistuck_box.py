"""Anti-stuck's switch and its two timers, for one kind of device.

Every kind has its own since 2026-11-17 (Blise's ask: "some of them may want
different settings"; antistuck.py): the toys on the Toys page, the bHaptics
and OWO suits in their frames on the Suits page, the haptic trackers in its
body card, the PSVR2 in its Contact card. One widget draws all of them, so
they read and behave alike: the switch, then -- indented under it and shown
only while it is on -- "Frozen part-way: stop after 1 s" and "Held at 100%:
ease off after 10 s", side by side or one under the other when narrow.
The timers are sliders with the value written out, never spin boxes
(Blise's rule for the card pages), on a logarithmic scale: a second apart
near the bottom, 1 s to 10 min.

It reads its values through `get()` -- or, on a page that already fetches a
status snapshot, is handed them (`refresh(values)`, `get=None`) -- and writes
every change through `set_(**changes)`; Ctrl+Z replays the switch or the
slider as by hand (ui/history_keys.py), and `refresh()` shows the store
again after anything else changed it."""

from typing import Any, Callable, Dict, Optional

from PySide6.QtWidgets import QWidget

import antistuck
from ui.layout_helpers import FlowLayout, vbox
from ui.theme import ACCENT_HUE
from ui.views.pishock_cards import ValueSlider
from ui.widgets import ToggleSwitch

#: A timer slider's width: room for its words and the value beside them.
SLIDER_W = 250


def seconds_text(v: float) -> str:
    """1 s, 45 s, 2 min, 2 min 30 s."""
    v = int(round(v))
    if v < 60:
        return f"{v} s"
    m, sec = divmod(v, 60)
    return f"{m} min" + (f" {sec} s" if sec else "")

#: What the box's hover explanation says about any kind; `what` names it.
WHY = ("VRChat only sends a value when it changes. If a contact stops "
       "updating -- you swap avatar, your partner leaves, the link drops -- "
       "its last value would keep {what} going. Anti-stuck notices a value "
       "that has frozen and stops it.<br><br>"
       "A real contact between zero and one never holds perfectly still -- "
       "animation and IK jitter it all the time -- so a value frozen "
       "<b>part-way</b> is cut quickly (1 s by default). One held at "
       "<b>100%</b> gets the longer wait, then eases off over 3 s, because "
       "all the way in and held is a real thing. A new value brings it back "
       "at once.<br><br>"
       "Each kind of device has its own: the toys on the Toys page, each "
       "suit and the trackers on the Suits page, the headset on its page. "
       "On by default.")


class AntiStuckBox(QWidget):
    """One kind's anti-stuck: a switch and its two timers."""

    def __init__(self, title: str, what: str,
                 get: Optional[Callable[[], Dict[str, Any]]],
                 set_: Callable[..., None],
                 explain: Optional[Callable[[Any, str, str], None]] = None,
                 extra: str = "", hue: str = ACCENT_HUE, stacked: bool = False,
                 switch_text: str = "Anti-stuck", parent=None):
        """`title` names it on hover and in Ctrl+Z's line ("Toys'
        anti-stuck"); `what` is what a frozen value would keep going ("a
        toy"); `extra` adds a sentence to the explanation; `hue` colours the
        sliders (the kind's own); `stacked`: in a narrow card, the two
        timers one under the other, each as wide as the card; `switch_text`:
        the switch's words -- "On" in a card already titled Anti-stuck, whose
        timers then take its whole width (no indent)."""
        super().__init__(parent)
        self.setObjectName("antiStuckBox")
        self._get, self._set = get, set_
        self._filling = False
        lay = vbox(0, 6)
        self.setLayout(lay)

        self.switch = ToggleSwitch(switch_text, self)
        indent = switch_text != "On"
        lay.addWidget(self.switch)

        # the timers, indented to the switch's words, only while it's on
        self.times = QWidget(self)
        times_lay = (vbox(0, 6) if stacked
                     else FlowLayout(margin=0, h_spacing=14, v_spacing=6))
        self.times.setLayout(times_lay)
        times_lay.setContentsMargins(
            ToggleSwitch._TRACK_W + ToggleSwitch._LABEL_SPACING if indent else 0, 0, 0, 0)
        start = self.values()
        self.active_slider = self._seconds_slider(
            "Frozen part-way: stop after", start["active_s"], hue, "active_s", stacked)
        self.peaked_slider = self._seconds_slider(
            "Held at 100%: ease off after", start["peaked_s"], hue, "peaked_s", stacked)
        for w in (self.active_slider, self.peaked_slider):
            times_lay.addWidget(w)
        lay.addWidget(self.times)

        if explain is not None:
            explain((self.switch, self.times, self.active_slider, self.peaked_slider), title,
                    WHY.format(what=what) + (f"<br><br>{extra}" if extra else ""))

        self.refresh()
        self.switch.toggled.connect(self._on_switch)

    def _seconds_slider(self, words: str, value: int, hue: str, field: str,
                        stacked: bool) -> ValueSlider:
        s = ValueSlider(words, antistuck.SECONDS_MIN, antistuck.SECONDS_MAX, value,
                        step=1, fmt=seconds_text, hue=hue, log=True,
                        on_change=lambda v, f=field: self._changed(**{f: int(round(v))}))
        s.setParent(self.times)
        if not stacked:
            s.setFixedWidth(SLIDER_W)       # side by side while they fit
        return s

    def values(self) -> Dict[str, Any]:
        """What `get()` says; the defaults without one (the page hands them
        in with `refresh`)."""
        if self._get is None:
            return dict(antistuck.DEFAULTS)
        try:
            return antistuck.clean(self._get())
        except Exception:  # noqa: BLE001
            return dict(antistuck.DEFAULTS)

    def refresh(self, values: Optional[Dict[str, Any]] = None) -> None:
        """Show what the store holds now -- `values`, else what `get()`
        says -- without writing it back."""
        if values is None and self._get is None:
            return
        v = antistuck.clean(values) if values is not None else self.values()
        self._filling = True
        try:
            if self.switch.isChecked() != v["enabled"]:
                self.switch.setChecked(v["enabled"])
            self.active_slider.set_value(v["active_s"])
            self.peaked_slider.set_value(v["peaked_s"])
        finally:
            self._filling = False
        self.times.setVisible(v["enabled"])

    def _on_switch(self, on: bool) -> None:
        self.times.setVisible(bool(on))
        self._changed(enabled=bool(on))

    def _changed(self, **changes) -> None:
        if not self._filling:
            self._set(**changes)

