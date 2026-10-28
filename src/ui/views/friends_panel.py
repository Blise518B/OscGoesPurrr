"""Friends view, the control panel: what is picked in the list -- one
friend (a card per toy, PiShock's own panel per shocker) or a group (one
toy card, and PiShock's Party panel over everyone's shockers) -- and
Control mode, which makes it fill the window, everything big, for VR. The
shockers are friends_shockers.py. Part of FriendsMixin (friends.py)."""

import time
from typing import Any, Dict, List

from PySide6.QtCore import QSize, Qt
from PySide6.QtWidgets import QCheckBox, QFrame, QLabel, QLineEdit, QPushButton, QWidget

from remote_protocol import ALL_TOYS, display_name
from ui.icons import glyph_icon
from ui.layout_helpers import (
    CardGrid, FlowLayout as _FlowLayout, clear_layout, vbox as _vbox, hbox as _hbox,
)
from ui.theme import (FRIEND_SHOCK_HUE as _SHOCK, FRIEND_TOYS_HUE as _TOYS, FRIENDS_HUE,
                      PALETTE, friend_hue)
from ui.views.card_parts import CARD_MIN_W, set_quiet
from ui.views.friends_shockers import FriendsShockersMixin
from ui.views.friends_web_panel import FriendsWebPanelMixin
from ui.views.toy_card import ToyCard
from ui.widgets import IdentityMark, ToggleSwitch

# a section in this hue carries this icon (ui/icons.identity_icon)
_SECTION_ICONS = {_TOYS: "toys", _SHOCK: "shock", "accent": "params"}

PANEL_MAX_W = 800    # the control panel never stretches across a wide window
                     # (two shocker cards a row just fit)
BIG_CARD_MIN_W = 460  # control mode's cards (VR): two a row only when that fits


def _pct(v: float) -> str:
    return f"{round(v * 100)} %"


class FriendsPanelMixin(FriendsShockersMixin, FriendsWebPanelMixin):

    _panel_w: Dict[str, Any] = {}

    # ---- control mode: one friend or group, big (VR) -----------

    def _control_mode_button(self) -> QPushButton:
        on = self._friends_big
        b = QPushButton(" Exit control mode" if on else " Control mode")
        b.setProperty("role", "control")
        b.setIcon(glyph_icon("collapse" if on else "expand", PALETTE["cyan"][0], 16))
        b.setIconSize(QSize(16, 16))
        b.setCursor(Qt.PointingHandCursor)
        if on:
            b.setProperty("big", "true")
        b.clicked.connect(lambda _=False: self._set_friends_control(not on))
        self._explain(b, "Control mode",
                      "Just this friend or group, with big controls - for VR. "
                      "The sidebar, your friends list and the log step aside; "
                      "Esc or Exit control mode brings them back.")
        return b

    def _friends_recolour(self) -> None:
        """After a colour change (Appearance): the cards' glyphs and the
        Control mode button are pixmaps, painted again in today's colours."""
        w = getattr(self, "_panel_w", {}) or {}
        party = w.get("party")
        for card in (w.get("toys") or []) + (w.get("shockers") or []) + (
                [party.card] if party is not None else []):
            try:
                card.recolour()
            except RuntimeError:
                pass                      # rebuilt meanwhile
        button = w.get("control")
        if button is not None:
            try:
                on = self._friends_big
                button.setIcon(glyph_icon("collapse" if on else "expand", PALETTE["cyan"][0], 16))
            except RuntimeError:
                pass

    def _set_friends_control(self, on: bool) -> None:
        on = bool(on)
        if on == self._friends_big:
            return
        self._friends_big = on
        for w in (getattr(self, "sidebar_scroll", None), self._friends_title,
                  self._friends_intro, self._friends_list_card, self._friends_log_card):
            if w is not None:
                w.setVisible(not on)
        self._friends_right.setMaximumWidth(16777215 if on else PANEL_MAX_W)
        self._panel_card.setProperty("big", "true" if on else "false")
        self._repolish(self._panel_card)
        self._friends_panel_key = None
        self.refresh_friends()

    # ---- what is picked ----------------------------------------

    @staticmethod
    def _panel_key(st: Dict[str, Any]):
        sel = st["selected"]
        if sel.get("kind") == "friend":
            f = next((x for x in st["friends"] if x["id"] == sel["id"]), None)
            if f is None:
                return ("none",)
            t = f["theirs"]
            return ("friend", f["id"], f["nick"], f["linked"], friend_hue(st["friends"].index(f)),
                    None if t is None else (tuple(n for n, _ in t["toys"]), t["allow_toys"],
                                            t["allow_shock"], tuple(t["shockers"])))
        if sel.get("kind") == "group":
            g = next((x for x in st["groups"] if x["id"] == sel["id"]), None)
            if g is None:
                return ("none",)
            return ("group", g["id"], tuple(f["id"] for f in st["friends"]))
        if sel.get("kind") == "web" and st.get("web"):
            return ("web", tuple((g["id"], g["nick"]) for g in st["web"]["guests"]))
        return ("none",)

    def _rebuild_panel(self, st: Dict[str, Any]) -> None:
        self._keep_shockers()
        clear_layout(self._panel_lay)
        self._panel_w = {"strength_t": 0.0}
        sel = st["selected"]
        hue = ""
        if sel.get("kind") == "friend":
            ids = [f["id"] for f in st["friends"]]
            if sel["id"] in ids:
                hue = friend_hue(ids.index(sel["id"]))
        elif sel.get("kind") == "web":
            hue = FRIENDS_HUE
        self._panel_hue = hue
        if self._panel_card.property("hue") != hue:
            self._panel_card.setProperty("hue", hue)
            self._repolish(self._panel_card)
        if sel.get("kind") == "friend":
            f = next((x for x in st["friends"] if x["id"] == sel["id"]), None)
            if f is not None:
                self._build_friend_panel(f)
                return
        if sel.get("kind") == "group":
            g = next((x for x in st["groups"] if x["id"] == sel["id"]), None)
            if g is not None:
                self._build_group_panel(g, st)
                return
        if sel.get("kind") == "web" and st.get("web"):
            self._build_web_panel(st["web"], bool(st.get("params_on")))
            return
        self._panel_header("Control")
        self._panel_lay.addWidget(self._muted_label(
            "Add a friend on the left, then pick them - or a group - to control "
            "them here."))

    def _panel_header(self, title: str):
        row = _hbox(0, 8)
        hdr = QLabel(title)
        hdr.setObjectName("sectionTitle")
        hdr.setTextFormat(Qt.PlainText)            # a friend's or group's name
        if getattr(self, "_panel_hue", ""):
            hdr.setProperty("hue", self._panel_hue)
        row.addWidget(hdr)
        row.addStretch(1)
        self._panel_lay.addLayout(row)
        return row, hdr

    # ---- sections ----------------------------------------------

    def _friends_section(self, title: str, hue: str):
        """A frame in the hue of what it drives, its cards inside."""
        frame = QFrame()
        frame.setObjectName("friendSection")
        frame.setProperty("hue", hue)
        lay = _vbox(10, 8)
        frame.setLayout(lay)
        head = _hbox(0, 8)
        what = _SECTION_ICONS.get(hue)
        if what:
            head.addWidget(IdentityMark(what, 14))
            head.addSpacing(-2)
        micro = self._friends_micro(title, hue)
        if self._friends_big:
            micro.setProperty("big", "true")        # control mode: readable from VR
        head.addWidget(micro)
        head.addStretch(1)
        lay.addLayout(head)
        self._panel_lay.addWidget(frame)
        return lay, head

    def _strength_inline(self, head, initial: float, on_change) -> QWidget:
        """Their strength slider, small, in the toys section's header."""
        box = QWidget()
        row = _hbox(0, 6)
        box.setLayout(row)
        big = self._friends_big
        lbl = QLabel("Their strength")
        lbl.setProperty("muted", "true")
        row.addWidget(lbl)
        s = self._friends_slider()
        s.setFixedWidth(260 if big else 150)
        s.setValue(round(initial * 1000))
        val = QLabel(_pct(initial))
        val.setMinimumWidth(48 if big else 36)
        if big:
            for x in (lbl, s, val):
                x.setProperty("big", "true")
        val.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        s.valueChanged.connect(lambda x: (val.setText(_pct(x / 1000)), on_change(x / 1000)))
        row.addWidget(s)
        row.addWidget(val)
        head.addWidget(box)
        box.slider, box.value_label = s, val
        self._explain(box, "Their strength",
                      "Their own strength slider, top left in their OGP: it "
                      "scales everything their toys do. Whoever moves it last "
                      "wins.")
        return box

    def _cards_grid(self, cards: List[QWidget]) -> QWidget:
        """Two cards a row, one once two don't fit (bigger in control mode)."""
        return CardGrid(cards, min_card_w=BIG_CARD_MIN_W if self._friends_big else CARD_MIN_W,
                        gap=12 if self._friends_big else 8)

    # ---- one friend --------------------------------------------

    def _build_friend_panel(self, f: Dict[str, Any]) -> None:
        fid, w = f["id"], self._panel_w
        w["kind"], w["id"] = "friend", fid
        me = bool(f.get("me"))
        nick = display_name(f["nick"], fid) + (" (you)" if me else "")
        row, w["title"] = self._panel_header(nick)
        w["pill"] = self._friends_pill()
        row.addWidget(w["pill"])
        w["driving"] = self._friends_pill("DRIVING YOUR TOYS", "live")
        row.addWidget(w["driving"])
        # "+1 OTHER": who else drives their toys right now (their OGP says;
        # the names on hover)
        w["others"] = self._friends_pill("", "info")
        w["others"].setVisible(False)
        row.addWidget(w["others"])
        w["control"] = self._control_mode_button()
        row.addWidget(w["control"])
        title = w["title"]
        title.setContextMenuPolicy(Qt.CustomContextMenu)
        title.customContextMenuRequested.connect(
            lambda pos: self._friend_row_menu(fid, nick, title, pos, me))
        title.setToolTip("Right-click to take yourself off the list" if me
                         else "Right-click to unfriend")
        w["foot"] = (fid, nick, me)

        theirs = f["theirs"]
        if not f["linked"] or theirs is None:
            self._panel_lay.addWidget(self._muted_label(
                "Offline. You link by yourselves as soon as they open OGP."))
            self._panel_foot()
            return

        c = self.controller
        lay, head = self._friends_section("THEIR TOYS", _TOYS)
        if not theirs["allow_toys"]:
            lay.addWidget(self._muted_label("They haven't allowed you their toys."))
        else:
            def strength_changed(v: float) -> None:
                w["strength_t"] = time.monotonic()
                c.set_friend_strength(fid, v)

            sync = ToggleSwitch("Sync with others")
            sync.setChecked(bool(f.get("sync", True)))
            sync.toggled.connect(lambda on: c.set_friend_sync(fid, bool(on)))
            if self._friends_big:
                sync.setProperty("big", "true")
            if not me:                          # you on yourself: nobody to sync with
                head.addWidget(sync)
                head.addSpacing(10)
                w["sync"] = sync
            self._explain(sync, "Sync with others",
                          "On: everyone who drives this friend with Sync on shares one "
                          "set of toy cards. A level, auto mode or Override one of you "
                          "picks shows up on the others' panels too, and their toys play "
                          "it once - the newest change wins.<br><br>Off: your cards are "
                          "your own, and their toys follow whichever of you is higher. "
                          "Their strength slider is shared either way.")
            w["strength"] = self._strength_inline(head, theirs["strength"], strength_changed)
            cards = []
            # "All their toys" only while they have one to drive
            every = [(ALL_TOYS, "All their toys")] if theirs["toys"] else []
            for key, title in every + [(n, n) for n, _m in theirs["toys"]]:
                cards.append(ToyCard(
                    key, title, _TOYS,
                    on_level=lambda v, k=key: c.set_friend_level(fid, k, v),
                    on_override=lambda on, k=key: c.set_friend_override(fid, k, on),
                    on_pattern=lambda wv, pd, lo, hi, k=key: c.set_friend_pattern(fid, k, wv, pd, lo, hi),
                    meter=key != ALL_TOYS, big=self._friends_big))
            w["toys"] = cards
            lay.addWidget(self._cards_grid(cards))
            if not theirs["toys"]:
                lay.addWidget(self._muted_label("No toy connected on their side."))

        if theirs["allow_shock"]:
            self._build_friend_shockers(fid, theirs)
        self._build_friend_board(fid)
        self._panel_foot()

    def _panel_foot(self) -> None:
        """Out of the way, under the controls: unfriend this friend, or
        delete this group."""
        if self._friends_big:
            return
        w = self._panel_w
        row = _hbox(0, 8)
        row.addStretch(1)
        if w.get("kind") == "friend":
            fid, nick, me = w["foot"]
            if me:
                return                  # you're always on your own list
            b = QPushButton(f"Unfriend {nick}…")
            b.clicked.connect(lambda _=False: self._confirm_unfriend(fid, nick))
            self._explain(b, "Unfriend",
                          "Unlink them and take them off your list - their OGP takes "
                          "you off theirs. Right-click their name does the same.")
        else:
            gid = w["id"]
            b = QPushButton("Delete group")
            b.clicked.connect(lambda _=False: (self.controller.friends_delete_group(gid),
                                               self.refresh_friends()))
        b.setProperty("role", "ghost")
        b.setProperty("muted", "true")
        row.addWidget(b)
        self._panel_lay.addSpacing(6)
        self._panel_lay.addLayout(row)

    # ---- a group -----------------------------------------------

    def _build_group_panel(self, g: Dict[str, Any], st: Dict[str, Any]) -> None:
        gid, w = g["id"], self._panel_w
        w["kind"], w["id"] = "group", gid
        first = next((f for f in st["friends"] if f["id"] in g["members"] and f["theirs"]), None)
        w["strength0"] = first["theirs"]["strength"] if first is not None else 1.0
        row, w["title"] = self._panel_header(g["name"])
        w["control"] = self._control_mode_button()
        row.addWidget(w["control"])
        w["online"] = QLabel("")
        w["online"].setProperty("muted", "true")
        if self._friends_big:
            # control mode: just the controls (members are set outside it)
            self._panel_lay.addWidget(w["online"])
            self._build_group_controls(w)
            return

        row = _hbox(0, 8)
        row.addWidget(QLabel("Name"))
        name = QLineEdit(g["name"])
        name.setMaxLength(24)
        name.setMaximumWidth(220)
        name.editingFinished.connect(lambda: self.controller.friends_rename_group(gid, name.text()))
        w["name_edit"] = name
        row.addWidget(name)
        row.addStretch(1)
        self._panel_lay.addLayout(row)

        self._panel_lay.addWidget(self._friends_micro("MEMBERS"))
        box = QWidget()
        flow = _FlowLayout(margin=0, h_spacing=14, v_spacing=4)
        box.setLayout(flow)
        w["members"] = {}
        for f in st["friends"]:
            cb = QCheckBox(display_name(f["nick"], f["id"]))
            cb.setProperty("hue", friend_hue(st["friends"].index(f)))
            cb.setChecked(f["id"] in g["members"])
            cb.toggled.connect(lambda on, i=f["id"]: self.controller.set_group_member(gid, i, bool(on)))
            flow.addWidget(cb)
            w["members"][f["id"]] = cb
        self._panel_lay.addWidget(box)
        if not st["friends"]:
            self._panel_lay.addWidget(self._muted_label("Add friends first, then tick them here."))
        self._panel_lay.addWidget(w["online"])
        self._build_group_controls(w)
        self._panel_foot()

    def _build_group_controls(self, w: Dict[str, Any]) -> None:
        big = self._friends_big
        c = self.controller
        lay, head = self._friends_section("EVERYONE'S TOYS", _TOYS)
        # where it starts: the first member's own strength, as far as we know
        self._strength_inline(head, w.get("strength0", 1.0), lambda v: c.set_targets_strength(v))
        card = ToyCard(ALL_TOYS, "All their toys", _TOYS,
                       on_level=lambda v: c.set_targets_level(v),
                       on_override=lambda on: c.set_targets_override(on),
                       on_pattern=lambda wv, pd, lo, hi: c.set_targets_pattern(wv, pd, lo, hi),
                       meter=False, big=big)
        w["toys"] = [card]
        lay.addWidget(self._cards_grid([card]))
        if not big:
            lay.addWidget(self._muted_label(
                "Each friend only gets what they allow you. Pick a friend on the left "
                "for their toys one by one."))

        self._build_group_shockers()

    # ---- live values -------------------------------------------

    def _friends_levels_watch(self, peer: str) -> None:
        """A friend's toys' live levels come only while their panel is in
        view ("" for nobody): their OGP is told when that changes."""
        if peer != getattr(self, "_levels_watch_peer", ""):
            self._levels_watch_peer = peer
            self.controller.set_friend_levels_watch(peer or None)

    def _update_panel(self, st: Dict[str, Any]) -> None:
        w = self._panel_w
        self._update_friend_board()
        page = self.views.get("Friends") if hasattr(self, "views") else None
        seen = page is not None and page.isVisible()
        self._friends_levels_watch(w["id"] if seen and w.get("kind") == "friend" else "")
        if w.get("kind") == "friend":
            f = next((x for x in st["friends"] if x["id"] == w["id"]), None)
            if f is None:
                return
            if f["linked"]:
                rtt = f" · {f['rtt']:.0f} ms" if f["rtt"] is not None else ""
                self._friends_set_pill(w["pill"], f"ONLINE · {f['path']}{rtt}", "ok")
            else:
                self._friends_set_pill(w["pill"], "OFFLINE", "idle")
            w["driving"].setVisible(bool(f["driving_me"]))
            names = f.get("others") or []
            pill = w["others"]
            pill.setVisible(bool(names))
            if names:
                self._friends_set_pill(pill, f"+{len(names)} OTHER{'S' if len(names) > 1 else ''}",
                                       "info")
                tip = "Also driving their toys right now: " + ", ".join(names)
                if pill.toolTip() != tip:
                    pill.setToolTip(tip)
            sync = w.get("sync")
            if sync is not None and sync.isChecked() != bool(f.get("sync", True)):
                sync.blockSignals(True)
                sync.setChecked(bool(f.get("sync", True)))
                sync.blockSignals(False)
            theirs = f["theirs"]
            if theirs is None:
                return
            s = w.get("strength")
            if s is not None and not s.slider.isSliderDown() and time.monotonic() - w["strength_t"] > 1.0:
                v = round(theirs["strength"] * 1000)
                if s.slider.value() != v:
                    set_quiet(s.slider, v)
                    s.value_label.setText(_pct(theirs["strength"]))
            outs = theirs["outputs"]
            for card in w.get("toys") or []:
                if card.toy == ALL_TOYS:
                    out = max(outs.values()) if outs else 0.0
                else:
                    out = outs.get(card.toy, 0.0)
                card.set_state(f["my_levels"].get(card.toy, 0.0),
                               card.toy in f.get("my_override", ()),
                               f.get("my_patterns", {}).get(card.toy), out)
                if card.toy != ALL_TOYS:
                    card.set_battery((theirs.get("batteries") or {}).get(card.toy))
            self._update_friend_shockers(f)
        elif w.get("kind") == "group":
            g = next((x for x in st["groups"] if x["id"] == w["id"]), None)
            if g is None:
                return
            if w["title"].text() != g["name"]:
                w["title"].setText(g["name"])
            edit = w.get("name_edit")
            if edit is not None and not edit.hasFocus() and edit.text() != g["name"]:
                edit.setText(g["name"])
            for fid, cb in (w.get("members") or {}).items():
                f = next((x for x in st["friends"] if x["id"] == fid), None)
                label = display_name(f["nick"] if f else "", fid)
                if cb.text() != label:
                    cb.setText(label)
                if cb.isChecked() != (fid in g["members"]):
                    cb.blockSignals(True)
                    cb.setChecked(fid in g["members"])
                    cb.blockSignals(False)
            members = [f for f in st["friends"] if f["id"] in g["members"]]
            # what the group's card sent shows on it (every member got the same)
            if members:
                m = members[0]
                for card in w.get("toys") or []:
                    card.set_state(m["my_levels"].get(ALL_TOYS, 0.0),
                                   ALL_TOYS in m.get("my_override", ()),
                                   m.get("my_patterns", {}).get(ALL_TOYS), None)
            on = [display_name(f["nick"], f["id"]) for f in members if f["linked"]]
            text = (f"{len(on)} of {len(members)} online" + (f": {', '.join(on)}" if on else "")
                    if members else "No one in this group yet.")
            if w["online"].text() != text:
                w["online"].setText(text)
            self._update_group_shockers(st, members)
        elif w.get("kind") == "web":
            self._update_web_panel(st)
