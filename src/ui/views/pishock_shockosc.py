"""Shockers view, the ShockOSC card: when the worn avatar has ShockOSC's
parameters (``ShockOsc/...``, shockosc.py), one card between the shockers
and the behaviours offers to set them all up in one click -- a row per
group with what it becomes and whom it drives (the shocker with its name,
every shocker for ``_All``, or one dropped on the row: the page's drag).
Nothing is set up without the click, and a second click adds nothing.
Below that, which of the avatar's ShockOSC settings are kept in step with
the behaviours (shockosc_sync.py).

Part of PiShockMixin (pishock.py). Everything goes through the controller
(get_shockosc_setup / shockosc_set_up); this draws widgets only.
"""

from typing import Any, Dict, Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QLabel, QPushButton, QWidget

from ui.layout_helpers import clear_layout, hbox as _hbox, vbox as _vbox
from ui.views.pishock_cards import ShockerDropZone, mini_button, state_pill

SHOCKOSC_HUE = "cyan"           # the behaviours' hue: it makes behaviours
# the live timer's ticks between two looks at the worn avatar (~3 s)
CHECK_EVERY = 20


# ShockOSC's setting -> what it is on the behaviours, for the card
SYNCED_WORDS = {"Intensity": "strength", "MinIntensity": "lowest strength",
                "MaxIntensity": "strength", "Duration": "length", "MaxDuration": "length",
                "CooldownTime": "rest after a shock", "HoldTime": "touch time",
                "Paused": "On / Off"}


def synced_text(synced) -> str:
    """Which of the avatar's ShockOSC settings are kept in step, in a line
    ("" for none)."""
    words = list(dict.fromkeys(SYNCED_WORDS[s] for s in synced or () if s in SYNCED_WORDS))
    if not words:
        return ""
    return ("Kept in step with your avatar's ShockOSC settings: " + ", ".join(words)
            + ". Change one in its menu or here, and the other follows.")


class PiShockShockOscMixin:

    _shockosc_key: tuple = ()
    _shockosc_ticks = 0

    def _build_pishock_shockosc_card(self) -> QFrame:
        card = QFrame()
        card.setObjectName("paramCard")
        card.setProperty("hue", SHOCKOSC_HUE)
        lay = _vbox(0, 6)
        lay.setContentsMargins(10, 8, 10, 10)
        card.setLayout(lay)

        top = _hbox(0, 6)
        top.addWidget(state_pill("SHOCKOSC", "info"))
        self._shockosc_title = QLabel("")
        self._shockosc_title.setObjectName("cardName")
        top.addWidget(self._shockosc_title, 1)
        self._shockosc_go = mini_button("Set up", role="primary")
        self._shockosc_go.clicked.connect(self._on_shockosc_set_up)
        self._explain(self._shockosc_go, "Set up ShockOSC",
                      "Adds a behaviour below for each of your avatar's ShockOSC parameters "
                      "that doesn't have one yet. A touch becomes a Contact that shocks, "
                      "_IShock / _IVibrate / _ISound a Contact that pulses once, _CShock / "
                      "_CVibrate / _CSound a Continuous, a PhysBone a Pull. They start with "
                      "the values a new behaviour starts with, and your avatar takes them. "
                      "Press it again and nothing more is added.")
        top.addWidget(self._shockosc_go)
        lay.addLayout(top)
        self._shockosc_intro = self._muted_label("")
        lay.addWidget(self._shockosc_intro)
        self._shockosc_rows = QWidget()
        self._shockosc_rows_lay = _vbox(0, 4)
        self._shockosc_rows.setLayout(self._shockosc_rows_lay)
        lay.addWidget(self._shockosc_rows)
        self._shockosc_settings = self._muted_label("")
        self._explain(self._shockosc_settings, "Your avatar's ShockOSC settings",
                      "Your avatar carries ShockOSC's settings, and the behaviours made from "
                      "its groups keep the same values: the menu changing one changes them "
                      "here, and changing them here changes the avatar's. A shocker's limits "
                      "still hold whatever either side says.")
        lay.addWidget(self._shockosc_settings)
        self._explain(card, "ShockOSC",
                      "Your avatar is set up for ShockOSC, OpenShock's VRChat app, and OGP "
                      "understands its parameters. Set them up here once; OGP also sends "
                      "the avatar ShockOSC's feedback (Active, Cooldown, Intensity ...) "
                      "from what the shockers really do.")
        # whom each group drives, as dropped on its row (kept across redraws)
        self._shockosc_chosen: Dict[str, Any] = {}
        self._shockosc_card = card
        card.hide()
        return card

    def refresh_pishock_shockosc(self) -> None:
        """Controller facade (after an avatar loads) and the page's own
        refreshes: redraw the card from get_shockosc_setup()."""
        card = getattr(self, "_shockosc_card", None)
        getter = getattr(self.controller, "get_shockosc_setup", None)
        if card is None or not callable(getter):
            return
        try:
            setup = getter()
        except Exception:
            return
        setup = setup if isinstance(setup, dict) else {}
        groups = setup.get("groups") or []
        choices = getattr(self, "_pishock_shocker_choices", ())
        off = getattr(self, "_pishock_shockers_off", frozenset())
        key = (tuple((g["name"], g["missing"], g["total"], tuple(g["makes"]),
                      str(g.get("suggested"))) for g in groups),
               tuple(setup.get("synced") or ()),
               choices, tuple(sorted(off)))
        if key == self._shockosc_key:
            return
        self._shockosc_key = key
        card.setVisible(bool(groups))
        if not groups:
            return
        missing = sum(g["missing"] for g in groups)
        if missing:
            self._shockosc_title.setText("Your avatar is set up for ShockOSC")
            self._shockosc_intro.setText(
                "Each group becomes behaviours below, driving the shocker with its name - "
                "or drop a shocker card's ⠿ on its row. OGP sends your avatar ShockOSC's "
                "feedback too.")
            self._shockosc_go.setText(f"Set up {missing} behaviour{'s' * (missing != 1)}")
        else:
            self._shockosc_title.setText("Your avatar's ShockOSC parameters are set up")
            self._shockosc_intro.setText(
                "Their behaviours are below, and OGP sends your avatar ShockOSC's feedback "
                "from what the shockers do.")
        self._shockosc_go.setVisible(bool(missing))
        clear_layout(self._shockosc_rows_lay)
        for g in groups:
            self._shockosc_rows_lay.addWidget(self._shockosc_row(g, choices, off))
        text = synced_text(setup.get("synced"))
        self._shockosc_settings.setText(text)
        self._shockosc_settings.setVisible(bool(text))

    def _shockosc_row(self, g: Dict[str, Any], choices, off) -> QWidget:
        row = QWidget()
        lay = _hbox(0, 8)
        row.setLayout(lay)
        name = QLabel(g["label"])
        name.setMinimumWidth(110)
        lay.addWidget(name)
        makes = QLabel(" · ".join(g["makes"]))
        makes.setProperty("muted", "true")
        makes.setWordWrap(True)
        lay.addWidget(makes, 1)
        self._explain(makes, g["label"],
                      "What this ShockOSC group becomes: a behaviour each, below.")
        if g["missing"]:
            group = g["name"]
            targets = self._shockosc_chosen.get(group, g.get("suggested") or [])
            zone = ShockerDropZone(targets, choices,
                                   lambda t, x=group: self._shockosc_chosen.__setitem__(x, t),
                                   off=off)
            zone.setMinimumWidth(220)
            lay.addWidget(zone, 1)
        else:
            done = state_pill("SET UP", "ok")
            self._explain(done, "Set up", "This group's behaviours are below.")
            lay.addWidget(done, 0, Qt.AlignVCenter)
        return row

    def _on_shockosc_set_up(self) -> None:
        setter = getattr(self.controller, "shockosc_set_up", None)
        if not callable(setter):
            return
        setter(dict(self._shockosc_chosen))
        self._shockosc_key = ()
        self._rebuild_pishock_rules()
        self.refresh_pishock_shockosc()

    def _shockosc_tick(self) -> None:
        """The page's live timer: a look at the worn avatar now and then
        (its parameters can arrive after the page was drawn)."""
        self._shockosc_ticks = (self._shockosc_ticks + 1) % CHECK_EVERY
        if self._shockosc_ticks == 0:
            self.refresh_pishock_shockosc()
