"""PiShock's Party Mode on the Friends panel: one combined shocker panel
(a ShockerCard in percent and real seconds) for the shockers ticked in its
list -- several of one friend's, or everyone's in a group -- and how a press
picks among them, as PiShock has it:

  * Sync -- all of them at once;
  * Random -- one of them, picked anew for every press;
  * Round Robin -- one after the other; the one that's next is marked, and
    a click on a name makes it next (so you choose who gets it).

It only draws and calls back with (peer, slot) pairs; the view wires those
to the controller's party_* calls."""

import random
from typing import Callable, List, Optional, Sequence, Set, Tuple

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QCheckBox, QFrame, QLabel, QPushButton, QWidget

from remote_protocol import SHOCK_MIN_MS
from ui.layout_helpers import FlowLayout, hbox, vbox
from ui.views.card_parts import bigger, segmented
from ui.views.shocker_card import PARTY_CAPS, ShockerCard

Pair = Tuple[str, int]                       # (friend id, their shocker slot)
MODES = ("sync", "random", "robin")


class ShockParty(QFrame):
    """See the module's notes. `targets` are (peer, slot, label, hue);
    on_fire(pairs, op, intensity, length_ms, warn_ms, warn_intensity),
    on_hold(pairs, op, intensity), on_release(pairs), on_stop(pairs).
    `on_ticks(ticked)` tells the view when the ticks change (it keeps them,
    and a friend's cards show them too)."""

    def __init__(self, title: str, hue: str,
                 on_fire: Callable[[List[Pair], str, float, int, int, float], None],
                 on_hold: Callable[[List[Pair], str, float], None],
                 on_release: Callable[[List[Pair]], None],
                 on_stop: Callable[[List[Pair]], None],
                 on_ticks: Optional[Callable[[Set[Pair]], None]] = None,
                 big: bool = False):
        super().__init__()
        self.setObjectName("partyFrame")
        self._fire_cb, self._hold_cb, self._release_cb, self._stop_cb = (
            on_fire, on_hold, on_release, on_stop)
        self._on_ticks = on_ticks
        self._big, self._hue = big, hue
        self._mode = "sync"
        self._targets: List[Tuple[str, int, str, str]] = []
        self._ticked: Set[Pair] = set()
        self._next = 0                     # Round Robin: index into ticked()
        self._held: List[Pair] = []        # who the press in progress drives
        lay = vbox(0, 8 if big else 6)
        self.setLayout(lay)
        head = hbox(0, 6)
        head.addStretch(1)
        self.title = bigger(QLabel(title), big)
        self.title.setObjectName("friendCardName")
        head.addWidget(self.title)
        # the strengths are each one's own: say so once, here (the sliders
        # read 100 at the top, like a friend's read their max)
        unit = bigger(QLabel("·  strengths in % of each one's max"), big)
        unit.setProperty("muted", "true")
        head.addWidget(unit)
        head.addStretch(1)
        lay.addLayout(head)
        self.card = ShockerCard("", hue, self._fire, self._hold, self._release, self._stop,
                                big=big)
        self.card.set_caps(PARTY_CAPS)
        lay.addWidget(self.card)
        row = hbox(0, 8)
        seg, self._mode_group = segmented(["Sync", "Random", "Round Robin"], hue,
                                          self._mode_picked, big)
        seg.setToolTip("Sync: all of them at once.\nRandom: one of them, picked anew "
                       "every press.\nRound Robin: one after the other - the next one is "
                       "marked; click a name to make it next.")
        row.addStretch(1)
        row.addWidget(seg)
        row.addStretch(1)
        lay.addLayout(row)
        self._list = QWidget()
        self._flow = FlowLayout(margin=0, h_spacing=14, v_spacing=4)
        self._list.setLayout(self._flow)
        lay.addWidget(self._list)
        self._boxes: List[QCheckBox] = []
        self._nexts: List[QPushButton] = []

    # -- who's in it
    def set_targets(self, targets: Sequence[Tuple[str, int, str, str]],
                    ticked: Optional[Set[Pair]] = None) -> None:
        """The shockers it can drive, (peer, slot, label, hue) -- and which
        are ticked (None: as they were; a new one comes in ticked)."""
        targets = list(targets)
        if ticked is None:
            old = {(p, s) for p, s, _l, _h in self._targets}
            ticked = {(p, s) for p, s, _l, _h in targets
                      if (p, s) in self._ticked or (p, s) not in old}
        ticked = {pair for pair in ticked if any(pair == (p, s) for p, s, _l, _h in targets)}
        if targets == self._targets and ticked == self._ticked:
            return
        self._targets, self._ticked = targets, set(ticked)
        while self._flow.count():
            item = self._flow.takeAt(0)
            if item.widget() is not None:
                item.widget().deleteLater()
        self._boxes, self._nexts = [], []
        for peer, slot, label, hue in targets:
            box = QWidget()
            bl = hbox(0, 2)
            box.setLayout(bl)
            cb = bigger(QCheckBox(label), self._big)
            cb.setProperty("hue", hue)
            cb.setChecked((peer, slot) in self._ticked)
            cb.toggled.connect(lambda on, pair=(peer, slot): self._tick(pair, on))
            nxt = bigger(QPushButton("▶"), self._big)
            nxt.setProperty("role", "mini")
            nxt.setProperty("hue", self._hue)
            nxt.setCheckable(True)
            nxt.setToolTip("Round Robin: this one is next - click another name to make it next")
            nxt.setCursor(Qt.PointingHandCursor)
            nxt.clicked.connect(lambda _=False, pair=(peer, slot): self._make_next(pair))
            bl.addWidget(nxt)
            bl.addWidget(cb)
            self._flow.addWidget(box)
            self._boxes.append(cb)
            self._nexts.append(nxt)
        self._show()

    def set_ticked(self, ticked: Set[Pair]) -> None:
        self.set_targets(self._targets, ticked)

    def ticked(self) -> List[Pair]:
        return [(p, s) for p, s, _l, _h in self._targets if (p, s) in self._ticked]

    def _tick(self, pair: Pair, on: bool) -> None:
        if on:
            self._ticked.add(pair)
        else:
            self._ticked.discard(pair)
        self._show()
        if self._on_ticks is not None:
            self._on_ticks(set(self._ticked))

    def _make_next(self, pair: Pair) -> None:
        if pair not in self._ticked:
            for cb, (p, s, _l, _h) in zip(self._boxes, self._targets):
                if (p, s) == pair:
                    cb.setChecked(True)          # ticks it (and tells the view)
        ticked = self.ticked()
        if pair in ticked:
            self._next = ticked.index(pair)
        self._show()

    def _mode_picked(self, i: int) -> None:
        self.card.release()
        self._mode = MODES[i]
        self._show()

    def _show(self) -> None:
        ticked = self.ticked()
        n = len(ticked)
        self.title.setText(f"Party · {n} shocker{'' if n == 1 else 's'}")
        robin = self._mode == "robin"
        nxt = ticked[self._next % n] if n else None
        for b, (p, s, _l, _h) in zip(self._nexts, self._targets):
            b.setVisible(robin)
            b.setChecked((p, s) == nxt)
        self.card.setEnabled(n > 0)

    # -- which of them a press drives
    def _pick(self) -> List[Pair]:
        ticked = self.ticked()
        if not ticked:
            return []
        if self._mode == "random":
            return [random.choice(ticked)]
        if self._mode == "robin":
            pair = ticked[self._next % len(ticked)]
            self._next = (self._next + 1) % len(ticked)
            self._show()
            return [pair]
        return ticked

    @staticmethod
    def _ms(length: float) -> int:
        """The card's length (0..1 of PiShock's 10 s) in milliseconds."""
        return round(SHOCK_MIN_MS + length * (PARTY_CAPS[2] - SHOCK_MIN_MS))

    def _fire(self, op, intensity, length, warn_ms, warn_intensity) -> None:
        pairs = self._pick()
        if pairs:
            self._fire_cb(pairs, op, intensity, self._ms(length), warn_ms, warn_intensity)

    def _hold(self, op, intensity) -> None:
        if not self._held:
            self._held = self._pick()      # one press, one pick (a warning included)
        if self._held:
            self._hold_cb(self._held, op, intensity)

    def _release(self) -> None:
        held, self._held = self._held, []
        if held:
            self._release_cb(held)

    def _stop(self) -> None:
        self._held = []
        pairs = [(p, s) for p, s, _l, _h in self._targets]
        if pairs:
            self._stop_cb(pairs)          # STOP stops every one of them

    # -- the panel
    def stop(self) -> None:
        self.card.stop()

    def release(self) -> None:
        self.card.release()

    def settings(self) -> dict:
        return {"card": self.card.settings(), "mode": self._mode, "ticked": set(self._ticked),
                "next": self._next}

    def restore(self, st: dict) -> None:
        self.card.restore(st["card"])
        self._mode = st["mode"]
        self._mode_group.button(MODES.index(self._mode)).setChecked(True)
        self._next = st.get("next", 0)
        self._show()
