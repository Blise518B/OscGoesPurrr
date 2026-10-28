"""Suits view — a bHaptics suit over Bluetooth and an OWO suit through the
My OWO app, driven by one body.

Mixin for ui_components.OscGoesPurrrUI, shown while either suit's feature
(`feature_bhaptics`, `feature_owo`) is on (Settings → Features). Top to
bottom (Blise's ask, 2026-10-28: a picture of the body, not a list):

  * Body        — a cat girl's front and back with every bHaptics dot
                  (orange), OWO's muscle patches (purple) and the Vive
                  trackers (blue) on her, lit as they play (body_view.py).
                  Click one and its card opens beside her with a line to
                  it (Blise's ask, 2026-10-28) -- its switch, strength, a
                  button to feel it and whether your avatar has its
                  contacts (suits_cards.py); empty space closes them. The
                  chips under her list everything with its setting, and
                  the contact check what your avatar is missing. Press and
                  hold a dot to feel it;
  * bHaptics    — the parts you have (only those show on her; one that
                  connects is added by itself), the Bluetooth link (no
                  bHaptics Player), Let go, who the suit reacts to and
                  whether it follows OWO's contacts;
  * OWO         — My OWO's link, Stop all, the ceiling and frequency, who it
                  reacts to (EMS: everything is capped);
  * Zone routes — an OGB / SPS zone or a custom source onto a body region,
                  felt by both suits.

Trackers show only when get_suits_status() carries a "trackers" entry
({"feature", "spots": {key: {"enabled", "intensity", "contacts"}}}), which
nothing in this build does yet: the page is ready for tracker haptics to be
ported from main (the facade's set_tracker / tracker_test).

Everything goes through the controller's Suits facade (Demeter rule); this
file only draws widgets and forwards primitive values.
"""

from typing import Any, Dict, List

from PySide6.QtCore import QPoint, QPointF, Qt, QTimer
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QFrame, QLabel, QLineEdit, QPushButton, QVBoxLayout, QWidget,
)

import body_map
from constants import *
from ui.layout_helpers import clear_layout, hbox as _hbox, vbox as _vbox
from ui.theme import BHAPTICS_HUE, OWO_HUE, TRACKERS_HUE
from ui.views.body_view import TRACKER_NAMES, TRACKERS, BodyView
from ui.views.card_parts import segmented
from ui.views.param_cards import CARD_W
from ui.views.pishock_cards import ValueSlider, category_frame, state_pill
from ui.views.suits_cards import (
    INSPECTOR_W, CheckRow, ChipRow, MuscleCard, PartCard, Stage, Swatch, TrackerCard,
)
from ui.widgets import Card as _Card, ToggleSwitch

VIEW_NAME = "Suits"
COLUMN_TOP = 24          # the inspector column starts level with her, under FRONT / BACK

_REACT = (
    ("Everyone", body_map.REACT_BOTH),
    ("Others only", body_map.REACT_OTHERS),
    ("Me only", body_map.REACT_SELF),
)
_FILTER_LABELS = (
    ("TouchOthers", "Touch · others"),
    ("TouchSelf", "Touch · me"),
    ("PenOthers", "Pen · others"),
    ("PenSelf", "Pen · me"),
)


class SuitsMixin:

    _is_updating_suits = False
    _suit_route_count = -1

    # ----------------------------------------------------------
    # View
    # ----------------------------------------------------------

    def _build_suits_view(self, parent_layout: QVBoxLayout):
        title = QLabel(VIEW_NAME)
        title.setObjectName("viewTitle")
        title.setAlignment(Qt.AlignHCenter)
        parent_layout.addWidget(title)
        parent_layout.addWidget(self._muted_label(
            "Your bHaptics suit and your OWO suit, both from the same contacts on "
            "your avatar. Click a part of her to set it up."))

        self._suits_bs: Dict[str, Any] = {}
        self._suits_os: Dict[str, Any] = {}
        self._suits_parts_shown = tuple(p for p, _n in body_map.POSITIONS)   # You have
        self._suits_bh_shown = True
        self._suits_owo_on = True
        self._suits_spots: Dict[str, Dict[str, Any]] = {}     # trackers there are
        self._suits_contacts = None                           # {position: indices} or unknown
        self._suits_owo_contacts: set = set()
        self._suit_routes_parts = self._suits_parts_shown
        parent_layout.addWidget(self._build_suits_body_card())
        self._suits_bh_card = self._build_suits_bhaptics_frame()
        parent_layout.addWidget(self._suits_bh_card)
        self._suits_owo_card = self._build_suits_owo_frame()
        parent_layout.addWidget(self._suits_owo_card)
        parent_layout.addWidget(self._build_suits_routes_card())
        parent_layout.addStretch(1)

        self._suits_live_timer = QTimer()
        self._suits_live_timer.setInterval(150)
        self._suits_live_timer.timeout.connect(self._refresh_suits_live)
        self._suits_live_timer.start()

        self._rebuild_suit_routes()
        self.refresh_suits_status()

    def _suits_card(self, heading: str):
        card = _Card()
        lay = _vbox(20, 8)
        card.setLayout(lay)
        hdr_row = _hbox(0, 8)
        hdr = QLabel(heading)
        hdr.setObjectName("sectionTitle")
        hdr_row.addWidget(hdr)
        hdr_row.addStretch(1)
        lay.addLayout(hdr_row)
        return card, lay, hdr_row

    @staticmethod
    def _suits_small_card(title: str, hue: str, min_w: int = CARD_W):
        """Avatar Remote's card inside a suit's frame: a title, then rows."""
        card = QFrame()
        card.setObjectName("paramCard")
        card.setProperty("hue", hue)
        card.setMinimumWidth(min_w)
        lay = _vbox(0, 8)
        lay.setContentsMargins(12, 10, 10, 12)
        card.setLayout(lay)
        head = QLabel(title)
        head.setObjectName("paramLabel")
        lay.addWidget(head)
        return card, lay

    def _suits_button(self, text: str, role: str = "secondary") -> QPushButton:
        btn = QPushButton(text)
        btn.setMinimumHeight(BTN_HEIGHT_SMALL)
        btn.setProperty("role", role)
        return btn

    def _suits_react(self, hue: str, on_pick):
        """'Feel touches from' over a segmented switch (narrow enough for a
        one-column card); returns (the pair, the switch's group)."""
        box, group = segmented([label for label, _v in _REACT], hue,
                               lambda i: None if self._is_updating_suits
                               else on_pick(_REACT[i][1]))
        row = QWidget()
        rl = _vbox(0, 4)
        row.setLayout(rl)
        lbl = QLabel("Feel touches from")
        lbl.setProperty("muted", "true")
        rl.addWidget(lbl)
        rl.addWidget(box, 0, Qt.AlignLeft)
        return row, group

    @staticmethod
    def _suits_show_react(group, value) -> None:
        idx = next((i for i, (_l, v) in enumerate(_REACT) if v == value), 0)
        group.button(idx).setChecked(True)

    def _suits_set_pill(self, pill: QLabel, text: str, tone: str) -> None:
        pill.setText(text)
        pill.setProperty("tone", tone)
        self._repolish(pill)

    @staticmethod
    def _suits_wrap(text: str = "") -> QLabel:
        lbl = QLabel(text)
        lbl.setProperty("muted", "true")
        lbl.setWordWrap(True)
        return lbl

    # ---- Body ----------------------------------------------------

    def _build_suits_body_card(self) -> QFrame:
        card, lay, _hdr = self._suits_card("Body")
        self._suits_body = BodyView(
            on_hold=lambda pos, i, held: self.controller.bhaptics_hold_dot(pos, i, held),
            on_pick=lambda _part, _muscle, _tracker: self._suits_fill_inspector())
        self._explain(self._suits_body, "Body",
                      "Click a part of her and its settings open beside her. Orange dots "
                      "are bHaptics motors, purple patches OWO's muscles, blue pucks Vive "
                      "trackers; each lights up as it plays. Press and hold a dot to feel "
                      "it. A dashed amber ring: your avatar has no contact there. Front "
                      "and back are drawn as seen from outside.")

        self._suits_part_card = PartCard(
            on_enabled=lambda p, v: self.controller.set_bhaptics_device(p, enabled=v),
            on_strength=lambda p, v: self.controller.set_bhaptics_device(p, intensity=v),
            on_test=lambda p: self.controller.bhaptics_test(p))
        self._suits_muscle_card = MuscleCard(
            on_enabled=lambda m, v: self.controller.set_owo_muscle(m, enabled=v),
            on_top=lambda m, v: self.controller.set_owo_muscle(m, max=v),
            on_test=lambda m: self.controller.owo_test(m))
        self._suits_tracker_card = TrackerCard(
            on_enabled=lambda k, v: self.controller.set_tracker(k, enabled=v),
            on_strength=lambda k, v: self.controller.set_tracker(k, intensity=v),
            on_test=lambda k: self.controller.tracker_test(k))
        self._suits_pick_hint = self._suits_wrap(
            "Click a part of her to set it up. Press and hold a dot to feel it.")
        self._suits_pick_hint.setFixedWidth(INSPECTOR_W)
        side = _vbox(0, 10)
        # the cards open level with what was picked (_suits_align_column)
        self._suits_col_pad = QWidget()
        self._suits_col_pad.setFixedHeight(COLUMN_TOP)
        side.addWidget(self._suits_col_pad)
        for w in (self._suits_pick_hint, self._suits_part_card, self._suits_muscle_card,
                  self._suits_tracker_card):
            side.addWidget(w)
        side.addStretch(1)
        self._suits_stage = Stage(self._suits_body, side, self._suits_leader_lines)
        lay.addWidget(self._suits_stage)

        legend = QWidget()
        ll = _hbox(0, 6)
        legend.setLayout(ll)
        self._suits_legend: Dict[str, List[QWidget]] = {}
        for key, hue, shape, text in (
                (BHAPTICS_HUE, BHAPTICS_HUE, "dot", "bHaptics motor — press and hold to feel it"),
                (OWO_HUE, OWO_HUE, "patch", "OWO muscle — the dots inside it play it too"),
                (TRACKERS_HUE, TRACKERS_HUE, "puck", "Vive tracker"),
                ("missing", "amber", "missing", "not on your avatar")):
            swatch = Swatch(hue, shape)
            words = self._suits_wrap(text)
            words.setWordWrap(False)
            ll.addWidget(swatch)
            ll.addWidget(words)
            ll.addSpacing(14)
            self._suits_legend[key] = [swatch, words]
        ll.addStretch(1)
        lay.addWidget(legend)

        self._suits_parts_lbl = self._suits_wrap("bHaptics parts you have")
        lay.addWidget(self._suits_parts_lbl)
        self._suits_part_chips = ChipRow([p for p, _n in body_map.POSITIONS], BHAPTICS_HUE,
                                         self._on_suits_part_chip)
        lay.addWidget(self._suits_part_chips)
        self._suits_muscles_lbl = self._suits_wrap("OWO muscles")
        lay.addWidget(self._suits_muscles_lbl)
        self._suits_muscle_chips = ChipRow(body_map.MUSCLES, OWO_HUE, self._on_suits_muscle_chip)
        lay.addWidget(self._suits_muscle_chips)
        self._suits_trackers_lbl = self._suits_wrap("Vive trackers")
        lay.addWidget(self._suits_trackers_lbl)
        self._suits_tracker_chips = ChipRow([k for k, _n, _xy in TRACKERS], TRACKERS_HUE,
                                            self._on_suits_tracker_chip, labels=TRACKER_NAMES)
        lay.addWidget(self._suits_tracker_chips)
        self._explain(self._suits_part_chips, "bHaptics parts",
                      "Every part of the bHaptics suit you have, with its strength. Click "
                      "one to set it up beside her.")
        self._explain(self._suits_muscle_chips, "OWO muscles",
                      "Every OWO muscle with its top. Click one to set it up beside her.")
        self._explain(self._suits_tracker_chips, "Vive trackers",
                      "Every tracker that buzzes, with its strength. Click one to set it "
                      "up beside her.")

        self._suits_check_lbl = self._suits_wrap("Your avatar's contacts")
        lay.addWidget(self._suits_check_lbl)
        self._suits_check = CheckRow()
        lay.addWidget(self._suits_check)
        self._explain(self._suits_check, "Your avatar's contacts",
                      "Whether the avatar you're wearing has the contacts for what you "
                      "have: the bHaptics avatar package's for each part, OWO's for each "
                      "muscle, a tracker's own. Read from VRChat's list of the avatar's "
                      "parameters, so nothing needs touching first.")

        self._suits_now = QLabel("")
        self._suits_now.setProperty("role", "live")
        lay.addWidget(self._suits_now)
        self._explain(self._suits_now, "Right now", "What each suit is playing this moment.")
        return card

    def _on_suits_part_chip(self, part: str) -> None:
        self._suits_body.select(part, None, None)
        self._suits_fill_inspector()

    def _on_suits_muscle_chip(self, muscle: str) -> None:
        self._suits_body.select(None, muscle, None)
        self._suits_fill_inspector()

    def _on_suits_tracker_chip(self, key: str) -> None:
        self._suits_body.select(None, None, key)
        self._suits_fill_inspector()

    def _suits_fill_inspector(self) -> None:
        """Open a card for each thing picked on her (or in the chips), with
        its contact check; nothing picked shows the hint. A part you no
        longer have, or a tracker that's gone, is dropped from the pick."""
        body = self._suits_body
        (part, muscle), tracker = body.selection(), body.picked_tracker()
        part = part if self._suits_bh_shown and part in self._suits_parts_shown else None
        muscle = muscle if self._suits_owo_on else None
        tracker = tracker if tracker in self._suits_spots else None
        body.select(part, muscle, tracker)
        bs, os_ = self._suits_bs, self._suits_os
        contacts = self._suits_contacts
        follows = bool(os_.get("follow_bhaptics", True))
        if part:
            self._suits_part_card.show_part(part, (bs.get("devices") or {}).get(part) or {})
            self._suits_part_card.set_check(
                None if contacts is None else len(contacts.get(part) or ()))
        if muscle:
            position, cells = body_map.OWO_REGIONS[muscle]
            self._suits_muscle_card.show_muscle(
                muscle, (os_.get("muscles") or {}).get(muscle) or {},
                int(os_.get("global_max", 60)), follows,
                self._suits_bh_shown and position in self._suits_parts_shown)
            if contacts is None:
                self._suits_muscle_card.set_check(None)
            else:
                via = len(set(cells) & set(contacts.get(position) or ())) if follows else 0
                self._suits_muscle_card.set_check(muscle in self._suits_owo_contacts, via)
        if tracker:
            self._suits_tracker_card.show_tracker(tracker, TRACKER_NAMES[tracker],
                                                  self._suits_spots[tracker])
        self._suits_part_card.setVisible(bool(part))
        self._suits_muscle_card.setVisible(bool(muscle))
        self._suits_tracker_card.setVisible(bool(tracker))
        self._suits_pick_hint.setVisible(not (part or muscle or tracker))
        self._suits_part_chips.set_picked(part)
        self._suits_muscle_chips.set_picked(muscle)
        self._suits_tracker_chips.set_picked(tracker)
        self._suits_align_column(part, muscle, tracker)
        # the lines follow once the column has laid the cards out
        QTimer.singleShot(0, self._suits_stage.leaders.update)

    def _suits_align_column(self, part, muscle, tracker) -> None:
        """Move the open cards down so the first one sits level with what
        it is for -- its line runs short and level -- as far as they all
        still fit beside her."""
        body = self._suits_body
        picks = [(c, body.anchor(kind, name)) for c, kind, name in (
            (self._suits_part_card, "part", part),
            (self._suits_muscle_card, "muscle", muscle),
            (self._suits_tracker_card, "tracker", tracker)) if name]
        pad = COLUMN_TOP
        if picks and picks[0][1] is not None:
            used = sum(c.sizeHint().height() + 10 for c, _a in picks)
            pad = int(max(COLUMN_TOP, min(picks[0][1].y() - 22, body.height() - used)))
        self._suits_col_pad.setFixedHeight(pad)

    def _suits_leader_lines(self):
        """[(hue, start, end)] in the stage's coordinates: from each picked
        thing on her to the top of its card."""
        stage, body = self._suits_stage, self._suits_body
        (part, muscle), tracker = body.selection(), body.picked_tracker()
        origin = QPointF(body.mapTo(stage, QPoint(0, 0)))
        lines = []
        for kind, name, card, hue in (
                ("part", part, self._suits_part_card, BHAPTICS_HUE),
                ("muscle", muscle, self._suits_muscle_card, OWO_HUE),
                ("tracker", tracker, self._suits_tracker_card, TRACKERS_HUE)):
            if not name or not card.isVisibleTo(stage):
                continue
            start = body.anchor(kind, name)
            if start is None:
                continue
            corner = card.frame.mapTo(stage, QPoint(0, 0))
            lines.append((hue, origin + start, QPointF(corner.x(), corner.y() + 15)))
        return lines

    # ---- bHaptics ------------------------------------------------

    def _build_suits_bhaptics_frame(self) -> QFrame:
        frame, _root, flow, _head = category_frame("BHAPTICS", BHAPTICS_HUE, icon="suits")

        have, lay = self._suits_small_card("You have", BHAPTICS_HUE)
        self._bh_have = ChipRow(
            [key for key, _name, _p in body_map.PART_GROUPS], BHAPTICS_HUE,
            self._on_bh_have, labels={key: name for key, name, _p in body_map.PART_GROUPS})
        lay.addWidget(self._bh_have)
        lay.addWidget(self._suits_wrap(
            "Only these show on her. A part that connects is added by itself."))
        self._explain(have, "You have",
                      "The bHaptics parts you own: only their dots show on the body "
                      "and in the lists. A part that connects is added by itself.")
        flow.addWidget(have)

        link, lay = self._suits_small_card("Link", BHAPTICS_HUE, 2 * CARD_W + 10)
        row = _hbox(0, 8)
        self._bh_pill = state_pill("Not connected", "off")
        row.addWidget(self._bh_pill)
        self._explain(self._bh_pill, "Link",
                      "Whether OGP is talking to your suit over Bluetooth right "
                      "now, which parts are connected and their battery.")
        row.addStretch(1)
        self._bh_connect_btn = self._suits_button("Connect", "primary")
        self._bh_connect_btn.clicked.connect(self._on_bh_connect)
        row.addWidget(self._bh_connect_btn)
        self._explain(self._bh_connect_btn, "Connect",
                      "Look for your bHaptics suit, sleeves and head over "
                      "Bluetooth and connect them. Switch them on first, and "
                      "close the bHaptics Player: a suit takes one connection "
                      "at a time. No pairing in Windows needed.")
        self._bh_release_btn = self._suits_button("Let go")
        self._bh_release_btn.clicked.connect(self._on_bh_release)
        row.addWidget(self._bh_release_btn)
        self._explain(self._bh_release_btn, "Let go",
                      "Disconnect and stop reconnecting, so the bHaptics Player "
                      "or a game can use the suit. Connect takes it back.")
        lay.addLayout(row)
        self._bh_info = self._suits_wrap()
        lay.addWidget(self._bh_info)
        self._bh_auto = ToggleSwitch("Connect when the app starts")
        self._bh_auto.toggled.connect(
            lambda on: None if self._is_updating_suits
            else self.controller.set_bhaptics_option("auto_connect", bool(on)))
        lay.addWidget(self._bh_auto)
        self._explain(self._bh_auto, "Connect when the app starts",
                      "On by default: with the bHaptics switch on, OGP finds "
                      "the suit by itself.")
        flow.addWidget(link)

        touches, lay = self._suits_small_card("Touches", BHAPTICS_HUE)
        react_row, self._bh_react = self._suits_react(
            BHAPTICS_HUE, lambda v: self.controller.set_bhaptics_option("react_to", v))
        lay.addWidget(react_row)
        self._explain(react_row, "Feel touches from",
                      "The official bHaptics avatar package tells your own hands "
                      "apart from other people's. Older avatar setups don't, and "
                      "always count.")
        self._bh_follow = ToggleSwitch("Also feel OWO's contacts")
        self._bh_follow.toggled.connect(
            lambda on: None if self._is_updating_suits
            else self.controller.set_bhaptics_option("follow_owo", bool(on)))
        lay.addWidget(self._bh_follow)
        self._explain(self._bh_follow, "Also feel OWO's contacts",
                      "An avatar set up for OWO (owo_suit_… parameters) drives "
                      "the matching patch of the bHaptics suit too.")
        flow.addWidget(touches)
        return frame

    def _on_bh_have(self, group: str) -> None:
        self.controller.set_bhaptics_have(group, self._bh_have.chips[group].isChecked())
        self.refresh_suits_status()

    def _on_bh_connect(self) -> None:
        self.controller.bhaptics_connect()
        self.refresh_suits_status()

    def _on_bh_release(self) -> None:
        self.controller.bhaptics_release()
        self.refresh_suits_status()

    # ---- OWO -----------------------------------------------------

    def _build_suits_owo_frame(self) -> QFrame:
        frame, _root, flow, _head = category_frame("OWO", OWO_HUE, icon="suits")

        link, lay = self._suits_small_card("Link", OWO_HUE, 2 * CARD_W + 10)
        row = _hbox(0, 8)
        self._owo_pill = state_pill("Not connected", "off")
        row.addWidget(self._owo_pill)
        self._explain(self._owo_pill, "Link",
                      "Whether OGP is talking to the My OWO app. My OWO drives "
                      "the suit over Bluetooth and applies your calibration.")
        row.addStretch(1)
        self._owo_connect_btn = self._suits_button("Connect", "primary")
        self._owo_connect_btn.clicked.connect(self._on_owo_connect)
        row.addWidget(self._owo_connect_btn)
        self._explain(self._owo_connect_btn, "Connect",
                      "Find the My OWO app — on this PC first, then on your "
                      "network (the phone app works too) — and connect, the "
                      "way a game does.")
        self._owo_stop_btn = self._suits_button("Stop all", "danger")
        self._owo_stop_btn.clicked.connect(self._on_owo_stop)
        row.addWidget(self._owo_stop_btn)
        self._explain(self._owo_stop_btn, "Stop all / Resume",
                      "Ends every sensation now and keeps the suit quiet until "
                      "you press Resume - even after a restart. The same as the "
                      "OWO switch on Home. The sidebar's Off stops OWO too.")
        lay.addLayout(row)
        self._owo_info = self._suits_wrap()
        lay.addWidget(self._owo_info)
        self._owo_auto = ToggleSwitch("Connect when the app starts")
        self._owo_auto.toggled.connect(
            lambda on: None if self._is_updating_suits
            else self.controller.set_owo_option("auto_connect", bool(on)))
        lay.addWidget(self._owo_auto)
        self._explain(self._owo_auto, "Connect when the app starts",
                      "Off by default: OWO never connects unless you ask.")
        host_row = QWidget()
        hl = _hbox(0, 8)
        host_row.setLayout(hl)
        host_lbl = QLabel("My OWO at")
        host_lbl.setProperty("muted", "true")
        self._owo_host = QLineEdit()
        self._owo_host.setPlaceholderText("this PC, then the network")
        self._owo_host.editingFinished.connect(
            lambda: self.controller.set_owo_option("host", self._owo_host.text()))
        hl.addWidget(host_lbl)
        hl.addWidget(self._owo_host, 1)
        lay.addWidget(host_row)
        self._explain(host_row, "My OWO at",
                      "Leave empty to find the app by itself. Type the address "
                      "My OWO shows if it isn't found (another PC, or a "
                      "network that blocks broadcasts).")
        flow.addWidget(link)

        strength, lay = self._suits_small_card("Strength", OWO_HUE)
        self._owo_ceiling = ValueSlider(
            "Ceiling", 0, 100, 60, 1, lambda v: f"{v:.0f} %", hue=OWO_HUE,
            on_change=lambda v: self.controller.set_owo_option("global_max", int(v)))
        lay.addWidget(self._owo_ceiling)
        self._explain(self._owo_ceiling, "Ceiling", "No muscle goes above this. Starts at 60 %.")
        self._owo_freq = ValueSlider(
            "Frequency", 1, 100, 50, 1, lambda v: f"{v:.0f} Hz", hue=OWO_HUE,
            on_change=lambda v: self.controller.set_owo_option("frequency", int(v)))
        lay.addWidget(self._owo_freq)
        self._explain(self._owo_freq, "Frequency",
                      "How the sensation feels: low is a slow thump, high a fine buzz.")
        lay.addWidget(self._suits_wrap(
            "100 % is the top of your own calibration in My OWO. Nothing goes above "
            "the ceiling — whatever a contact, a setting or a test asks for."))
        flow.addWidget(strength)

        touches, lay = self._suits_small_card("Touches", OWO_HUE)
        react_row, self._owo_react = self._suits_react(
            OWO_HUE, lambda v: self.controller.set_owo_option("react_to", v))
        lay.addWidget(react_row)
        self._explain(react_row, "Feel touches from",
                      "For contacts that come from the bHaptics avatar package, "
                      "which tells your own hands apart from other people's.")
        self._owo_follow = ToggleSwitch("Also feel bHaptics' contacts")
        self._owo_follow.toggled.connect(
            lambda on: None if self._is_updating_suits
            else self.controller.set_owo_option("follow_bhaptics", bool(on)))
        lay.addWidget(self._owo_follow)
        self._explain(self._owo_follow, "Also feel bHaptics' contacts",
                      "A bHaptics avatar package drives OWO too: each muscle "
                      "feels the strongest bHaptics dot inside its patch.")
        flow.addWidget(touches)
        return frame

    def _on_owo_connect(self) -> None:
        st = self.controller.get_suits_status()["owo"]
        if st.get("connected") or st.get("wanted"):
            self.controller.owo_disconnect()
        else:
            self.controller.owo_connect()
        self.refresh_suits_status()

    def _on_owo_stop(self) -> None:
        if self.controller.get_suits_status()["owo"].get("paused"):
            self.controller.owo_resume()
        else:
            self.controller.owo_stop_all()
        self.refresh_suits_status()

    # ---- Zone routes -----------------------------------------------

    def _build_suits_routes_card(self) -> QFrame:
        card, lay, hdr_row = self._suits_card("Zone routes")
        add_btn = self._suits_button("+ Add route")
        add_btn.clicked.connect(self._on_suit_route_add)
        hdr_row.addWidget(add_btn)
        self._explain(add_btn, "Add route",
                      "Send an OGB / SPS zone, or one of your custom sources, to "
                      "a part of the body. Both suits feel it.")
        lay.addWidget(self._muted_label(
            "For avatars without a suit package: pick a zone and where it "
            "should land — a muscle's patch or a whole part."))
        self._suit_routes_body = _vbox(0, 8)
        lay.addLayout(self._suit_routes_body)
        return card

    def _suit_zone_names(self) -> List[str]:
        names: List[str] = []
        try:
            zones = self.controller.get_detected_zones() or {}
            for key in ("Orifices", "Penetrators", "Touch"):
                names += list(zones.get(key) or [])
            names += list(self.controller.get_sps_source_names_flat() or [])
        except Exception:
            pass
        seen, out = set(), []
        for n in names:
            if n and n not in seen:
                seen.add(n)
                out.append(n)
        return out

    def _rebuild_suit_routes(self) -> None:
        body = getattr(self, "_suit_routes_body", None)
        if body is None:
            return
        try:
            routes = self.controller.get_suit_routes()
        except Exception:
            routes = []
        self._suit_route_count = len(routes)
        self._suit_routes_parts = self._suits_parts_shown
        zones = self._suit_zone_names()
        self._is_updating_suits = True
        try:
            clear_layout(body)
            self._suit_route_rows: List[Dict[str, Any]] = []
            if not routes:
                body.addWidget(self._muted_label("None yet."))
            for idx, route in enumerate(routes):
                frame, row = self._build_suit_route_row(idx, route, zones)
                self._suit_route_rows.append(row)
                body.addWidget(frame)
        finally:
            self._is_updating_suits = False

    def _build_suit_route_row(self, idx: int, r: Dict[str, Any], zones: List[str]):
        frame = _Card(dark_bg=True)
        frame.setMaximumWidth(820)
        lay = _vbox(12, 6)
        frame.setLayout(lay)
        push = lambda *_a, i=idx: self._push_suit_route(i)  # noqa: E731

        on = ToggleSwitch("On")
        on.setChecked(bool(r.get("enabled", True)))
        on.toggled.connect(push)
        zone = QComboBox()
        zone.setEditable(True)
        zone.setMinimumWidth(160)
        for name in zones:
            zone.addItem(name)
        zone.setEditText(r.get("zone", ""))
        zone.lineEdit().setPlaceholderText("Zone or source")
        zone.lineEdit().editingFinished.connect(push)
        zone.activated.connect(push)
        ztype = QComboBox()
        for t in ("Orf", "Pen", "Touch"):
            ztype.addItem(t, t)
        ztype.setCurrentIndex(max(0, ztype.findData(r.get("zone_type", "Orf"))))
        ztype.currentIndexChanged.connect(push)
        region = QComboBox()
        # the muscles, then the bHaptics parts you have (and the one this
        # route already lands on, even if you've taken it off You have)
        current = r.get("region", "VestFront")
        for name in list(body_map.MUSCLES) + [p for p, _n in body_map.POSITIONS
                                              if p in self._suit_routes_parts or p == current]:
            region.addItem(body_map.display_name(name), name)
        region.setCurrentIndex(max(0, region.findData(r.get("region", "VestFront"))))
        region.currentIndexChanged.connect(push)
        to_lbl = QLabel("→")
        gain = ValueSlider("Gain", 0, 400, round(float(r.get("gain", 1.0)) * 100), 10,
                           lambda v: f"{v:.0f} %", hue=BHAPTICS_HUE, on_change=push)
        gain.setFixedWidth(190)
        delete = self._suits_button("Delete", "ghost")
        delete.clicked.connect(lambda _=False, i=idx: self._on_suit_route_delete(i))

        filters = {}
        filter_boxes = []
        for key, label in _FILTER_LABELS:
            box = QCheckBox(label)
            box.setChecked(key in (r.get("filters") or []))
            box.toggled.connect(push)
            filters[key] = box
            filter_boxes.append(box)

        lay.addWidget(self._pishock_flow([on, (zone, ztype), (to_lbl, region), gain, delete]))
        lay.addWidget(self._pishock_flow([tuple(filter_boxes)]))
        self._explain(zone, "Zone",
                      "An OGB / SPS zone your avatar has, or a custom source "
                      "(SPS Sources page). A custom source ignores the type and "
                      "the checkboxes.")
        self._explain(ztype, "Type", "Orifice, penetrator or touch zone.")
        self._explain((to_lbl, region), "Lands on",
                      "A muscle's patch (both suits feel it there) or a whole "
                      "part of the body.")
        self._explain(gain, "Gain",
                      "Scales the zone's strength: 200 % feels a light touch "
                      "twice as strongly (a full touch stays full).")
        self._explain(delete, "Delete", "Takes this route away.")
        return frame, {"on": on, "zone": zone, "type": ztype, "region": region,
                       "gain": gain, "filters": filters}

    def _push_suit_route(self, idx: int) -> None:
        if self._is_updating_suits:
            return
        rows = getattr(self, "_suit_route_rows", [])
        if not 0 <= idx < len(rows):
            return
        row = rows[idx]
        self.controller.set_suit_route(idx, {
            "enabled": row["on"].isChecked(),
            "zone": row["zone"].currentText().strip(),
            "zone_type": row["type"].currentData(),
            "filters": [k for k, box in row["filters"].items() if box.isChecked()],
            "region": row["region"].currentData(),
            "gain": row["gain"].value() / 100.0,
        })

    def _on_suit_route_add(self) -> None:
        self.controller.add_suit_route()
        self._rebuild_suit_routes()

    def _on_suit_route_delete(self, idx: int) -> None:
        self.controller.delete_suit_route(idx)
        self._rebuild_suit_routes()

    # ----------------------------------------------------------
    # Refresh
    # ----------------------------------------------------------

    def refresh_suits_status(self) -> None:
        """Controller facade: a link, a device list, a battery or a pause
        changed (also called on arrival and after the page's own clicks)."""
        pill = getattr(self, "_bh_pill", None)
        if pill is None:
            return
        try:
            st = self.controller.get_suits_status()
            detected = self.controller.get_suits_detected()
        except Exception:
            return
        bh, owo = st["bhaptics"], st["owo"]
        bh_on, owo_on = bool(bh.get("feature")), bool(owo.get("feature"))
        bs, os_ = bh.get("settings") or {}, owo.get("settings") or {}
        shown = body_map.positions_of(bs.get("have", body_map.DEFAULT_HAVE))
        dots = bh_on and bool(shown)            # any bHaptics dot on her at all
        trk = st.get("trackers") or {}
        spots = {k: dict(v) for k, v in (trk.get("spots") or {}).items()
                 if k in TRACKER_NAMES} if trk.get("feature") else {}
        self._suits_parts_shown, self._suits_bh_shown = shown, dots
        self._suits_owo_on, self._suits_spots = owo_on, spots
        self._suits_bh_card.setVisible(bh_on)
        self._suits_owo_card.setVisible(owo_on)
        for w in [self._suits_parts_lbl, self._suits_part_chips,
                  *self._suits_legend[BHAPTICS_HUE]]:
            w.setVisible(dots)
        for w in [self._suits_muscles_lbl, self._suits_muscle_chips,
                  *self._suits_legend[OWO_HUE]]:
            w.setVisible(owo_on)
        for w in [self._suits_trackers_lbl, self._suits_tracker_chips,
                  *self._suits_legend[TRACKERS_HUE]]:
            w.setVisible(bool(spots))
        self._suits_legend[OWO_HUE][1].setText(
            "OWO muscle — the dots inside it play it too" if dots
            else "OWO muscle — fills as it plays")

        devices = bh.get("devices") or []
        if not bh.get("available"):
            self._suits_set_pill(pill, "Bluetooth unavailable", "err")
        elif devices:
            self._suits_set_pill(pill, f"Connected · {len(devices)} "
                                       f"{'part' if len(devices) == 1 else 'parts'}", "ok")
        elif bh.get("scanning"):
            self._suits_set_pill(pill, "Looking…", "run")
        elif bh.get("released"):
            self._suits_set_pill(pill, "Let go", "idle")
        else:
            self._suits_set_pill(pill, "Not connected", "off")
        if devices:
            parts = []
            for d in devices:
                batt = f" · {d['battery']} %" if d.get("battery") is not None else ""
                parts.append(f"{d['label']}{batt}")
            info = "Connected: " + ", ".join(parts)
            if not all(d.get("verified") for d in devices):
                info += (". Which dot is which motor isn't checked on this model "
                         "yet — tell us if a touch lands in the wrong place.")
        else:
            info = bh.get("error") or "Switch the suit on and press Connect."
        self._bh_info.setText(info)
        self._bh_release_btn.setEnabled(bool(devices) or bool(bh.get("wanted")))

        if owo.get("paused"):
            self._suits_set_pill(self._owo_pill, "Stopped", "warn")
        elif owo.get("connected"):
            host = owo.get("host") or ""
            where = "this PC" if host in ("127.0.0.1", "localhost") else host
            self._suits_set_pill(self._owo_pill, f"Connected · My OWO on {where}", "ok")
        elif owo.get("wanted"):
            self._suits_set_pill(self._owo_pill, "Looking for My OWO…", "run")
        else:
            self._suits_set_pill(self._owo_pill, "Not connected", "off")
        self._owo_connect_btn.setText(
            "Disconnect" if owo.get("connected") or owo.get("wanted") else "Connect")
        self._owo_stop_btn.setText("Resume" if owo.get("paused") else "Stop all")
        self._owo_info.setText(owo.get("error") or (
            "Open My OWO with the suit connected there, then press Connect."
            if not owo.get("connected") else ""))
        self._owo_info.setVisible(bool(self._owo_info.text()))

        self._suits_bs, self._suits_os = bs, os_
        devices_cfg = bs.get("devices") or {}
        muscles_cfg = os_.get("muscles") or {}
        self._is_updating_suits = True
        try:
            self._bh_auto.setChecked(bool(bs.get("auto_connect")))
            self._suits_show_react(self._bh_react, bs.get("react_to"))
            self._bh_follow.setChecked(bool(bs.get("follow_owo")))
            self._owo_auto.setChecked(bool(os_.get("auto_connect")))
            if not self._owo_host.hasFocus():
                self._owo_host.setText(os_.get("host", ""))
            self._owo_ceiling.set_value(int(os_.get("global_max", 60)))
            self._owo_freq.set_value(int(os_.get("frequency", 50)))
            self._suits_show_react(self._owo_react, os_.get("react_to"))
            self._owo_follow.setChecked(bool(os_.get("follow_bhaptics")))
        finally:
            self._is_updating_suits = False
        part_vals = {p: (bool((devices_cfg.get(p) or {}).get("enabled", True)),
                         int((devices_cfg.get(p) or {}).get("intensity", 100)))
                     for p, _n in body_map.POSITIONS}
        muscle_vals = {m: (bool((muscles_cfg.get(m) or {}).get("enabled", True)),
                           int((muscles_cfg.get(m) or {}).get("max", 100)))
                       for m in body_map.MUSCLES}
        self._bh_have.set_checked(bs.get("have") or [])
        self._suits_part_chips.set_values(part_vals)
        self._suits_part_chips.set_shown(shown)
        self._suits_muscle_chips.set_values(muscle_vals)
        self._suits_tracker_chips.set_values(
            {k: (bool(v.get("enabled", True)), int(v.get("intensity", 100)))
             for k, v in spots.items()})
        self._suits_tracker_chips.set_shown(spots)
        self._suits_body.set_state(bh_on, owo_on,
                                   [p for p, (on, _v) in part_vals.items() if not on],
                                   [m for m, (on, _v) in muscle_vals.items() if not on],
                                   parts_shown=shown, trackers_shown=spots,
                                   trackers_off=[k for k, v in spots.items()
                                                 if not v.get("enabled", True)])
        self._suits_show_check(detected, shown if dots else (), owo_on, spots,
                               bool(os_.get("follow_bhaptics", True)))
        self._suits_fill_inspector()

        try:
            count = len(self.controller.get_suit_routes())
        except Exception:
            count = self._suit_route_count
        if count != self._suit_route_count or shown != self._suit_routes_parts:
            self._rebuild_suit_routes()

    def _suits_show_check(self, detected: Dict[str, Any], parts, owo_on: bool,
                          spots: Dict[str, Dict[str, Any]], follows: bool) -> None:
        """The contact check: does the avatar you're wearing have the
        contacts for what you have? Pills under her, amber rings on her."""
        source = detected.get("source") or ""
        contacts = {pos: tuple(i) for pos, i in (detected.get("contacts") or {}).items()}
        owo_have = set(detected.get("owo") or ())
        items, missing_dots, missing_muscles = [], {}, []

        def tone(found: int, total: int) -> str:
            return "ok" if found >= total else ("warn" if found else "err")

        if source:
            for key, name, positions in body_map.PART_GROUPS:
                mine = [pos for pos in positions if pos in parts]
                if not mine:
                    continue
                found = sum(len(contacts.get(pos) or ()) for pos in mine)
                total = sum(body_map.NODE_COUNTS[pos] for pos in mine)
                items.append((f"{name}  {found} / {total}", tone(found, total)))
                for pos in mine:
                    gone = set(range(body_map.NODE_COUNTS[pos])) - set(contacts.get(pos) or ())
                    if gone:
                        missing_dots[pos] = gone
            if owo_on:
                for muscle, (pos, cells) in body_map.OWO_REGIONS.items():
                    via = follows and set(cells) & set(contacts.get(pos) or ())
                    if muscle not in owo_have and not via:
                        missing_muscles.append(muscle)
                found = len(body_map.MUSCLES) - len(missing_muscles)
                items.append((f"OWO  {found} / {len(body_map.MUSCLES)}",
                              tone(found, len(body_map.MUSCLES))))
        missing_trackers = [k for k, v in spots.items()
                            if v.get("contacts") and not v["contacts"][0]]
        if spots and any(v.get("contacts") for v in spots.values()):
            found = len(spots) - len(missing_trackers)
            items.append((f"Trackers  {found} / {len(spots)}", tone(found, len(spots))))
        self._suits_contacts = contacts if source else None
        self._suits_owo_contacts = owo_have
        self._suits_body.set_missing(missing_dots, missing_muscles, missing_trackers)
        for w in self._suits_legend["missing"]:
            w.setVisible(bool(missing_dots or missing_muscles or missing_trackers))
        if source == "file":
            note = "Checked against every parameter of the avatar you're wearing."
        elif source == "osc":
            note = ("Checked against what VRChat has sent so far - change into the "
                    "avatar once with OSC on for its full list.")
        else:
            note = ("Wear your avatar in VRChat with OSC on, and this checks it has "
                    "the contacts for what you have.")
        self._suits_check.set_items(items, note)

    def _refresh_suits_live(self) -> None:
        try:
            if (self.main_stack is None
                    or self.main_stack.currentWidget() is not self.views.get(VIEW_NAME)):
                return
            live = self.controller.get_suits_live()
        except Exception:
            return
        self._suits_body.set_live(live.get("frame") or {}, live.get("owo") or {},
                                  live.get("trackers") or {})
        sending = live.get("owo_sending") or {}
        muscle = self._suits_muscle_card.muscle
        self._suits_muscle_card.show_level(sending.get(muscle) if muscle else None)
        dots = live.get("dots") or {}
        buzzing = sum(1 for frame in dots.values() for v in frame if v)
        parts = []
        if buzzing:
            parts.append(f"bHaptics: {buzzing} {'motor' if buzzing == 1 else 'motors'}")
        if sending:
            parts.append("OWO: " + ", ".join(
                f"{body_map.display_name(m)} {v} %" for m, v in sorted(sending.items())))
        self._suits_now.setText("Right now: " + (" · ".join(parts) if parts else "all quiet"))
