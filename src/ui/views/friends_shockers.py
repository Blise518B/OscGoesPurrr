"""Friends view, the shockers on the control panel: a friend's (one card
per shocker and, once two or more are ticked for Party, the Party panel
over them -- shock_party.py) or everyone's in a group (the Party panel
alone, over every member's shockers). Over the cards, a strip says what
reaches them: armed (shocks are real), not armed (a shock arrives as a
vibration), paused or Off.

The cards are PiShock's own panel (shocker_card.py) or OpenShock's card
(openshock_card.py), as the section's "Shocker buttons" switch says -- one
app setting for every panel (shocker_layout.py; PiShock by default,
Blise's call 2026-11-15). Both take the same calls, so nothing below cares
which; each layout keeps its own memory of how its cards were set.
Part of FriendsMixin (friends.py), with friends_panel.py."""

from typing import Any, Dict, List, Optional, Set, Tuple

from PySide6.QtWidgets import QFrame, QLabel, QPushButton, QWidget

import shocker_layout
from remote_protocol import (OPS, WARN_OFF_WHY, can_warn, display_name, shocker_caps,
                             shocker_ops, shocker_why)
from ui.layout_helpers import hbox
from ui.theme import FRIEND_SHOCK_HUE as _SHOCK, friend_hue
from ui.views.card_parts import bigger, segmented
from ui.views.openshock_card import OpenShockCard
from ui.views.shock_party import ShockParty
from ui.views.shocker_card import ShockerCard

_CARDS = {shocker_layout.PISHOCK: ShockerCard, shocker_layout.OPENSHOCK: OpenShockCard}
LAYOUT_TITLE = "Shocker buttons"
LAYOUT_TIP = ("Whose shocker buttons you drive with here: PiShock's panel (the default) or "
              "OpenShock's card with its Live control. It only changes how the buttons look - "
              "every press sends the same, and their caps, arming and each shocker's "
              "switches hold either way. One setting for every friend's panel, "
              "yours (Me) and every group's, remembered.")

# their shockers while only friends in their VRChat instance may drive them
# and you aren't in it (their status says so -- never where they are)
NOT_HERE_SHOCKERS = "they only let friends in their VRChat instance drive them"


def their_caps(theirs: Dict[str, Any], slot: int = -1):
    """((shock cap, vibrate cap, longest pulse ms), max hold s) from a
    friend's status -- one shocker's own (`slot`), or their hub-wide."""
    return shocker_caps(theirs, slot), float(theirs.get("max_hold_s") or 0.0)


def their_rules(theirs: Dict[str, Any], slots) -> Tuple[set, Dict[str, str], bool]:
    """(ops you may send, why an op -- or "warn" -- isn't there, a warning
    can play) on a friend's shockers -- one slot's, or what any of `slots`
    lets through (a party: each receiver drops what its switches don't
    allow)."""
    slots = list(slots)
    ops = set()
    for slot in slots:
        ops |= set(shocker_ops(theirs, slot))
    pairs = [(theirs, slot) for slot in slots]
    warn_ok = _warn_ok(pairs)
    return ops, _reasons(pairs, ops, warn_ok), warn_ok


def _warn_ok(pairs) -> bool:
    """A warning can play on any of `pairs` (status, slot) -- or there are
    none to say otherwise."""
    return not pairs or any(can_warn(theirs, slot) for theirs, slot in pairs)


def _reasons(pairs, ops, warn_ok: bool = True) -> Dict[str, str]:
    """Why each op outside `ops` is greyed: the one reason when all of
    `pairs` (status, slot) say the same, else that none of them lets you;
    and Warning's, when no warning can play."""
    out: Dict[str, str] = {} if warn_ok else {"warn": WARN_OFF_WHY}
    for op in OPS:
        if op in ops or not pairs:
            continue
        said = {shocker_why(theirs, slot, op) for theirs, slot in pairs} - {""}
        out[op] = said.pop() if len(said) == 1 else f"None of them lets you {op}"
    return out


class FriendsShockersMixin:

    def _shock_memory(self, which: Optional[str] = None) -> Dict[Any, Any]:
        """How the shocker cards and parties were set, across rebuilds --
        this window's own, one memory per layout (`which`, else the one
        the panel shows now)."""
        if "_shocker_memory" not in vars(self):
            self._shocker_memory = {}
        return self._shocker_memory.setdefault(which or self._shocker_buttons(), {})

    # ---- whose buttons -----------------------------------------

    def _shocker_buttons(self) -> str:
        """The layout the panel is built in (friends_panel._rebuild_panel
        reads it from the status)."""
        return shocker_layout.clean(getattr(self, "_shocker_layout", None))

    def _card_class(self) -> type:
        return _CARDS[self._shocker_buttons()]

    def _layout_switch(self, head) -> QWidget:
        """"Shocker buttons: PiShock | OpenShock" in the shocker section's
        header, where someone driving looks for it. A pick saves the one
        setting; the panel is rebuilt in the other layout."""
        box = QWidget()
        row = hbox(0, 6)
        box.setLayout(row)
        big = self._friends_big
        lbl = bigger(QLabel(LAYOUT_TITLE), big)
        lbl.setProperty("muted", "true")
        row.addWidget(lbl)
        seg, group = segmented([shocker_layout.NAMES[x] for x in shocker_layout.LAYOUTS], _SHOCK,
                               lambda i: self._layout_picked(shocker_layout.LAYOUTS[i]), big)
        group.button(shocker_layout.LAYOUTS.index(self._shocker_buttons())).setChecked(True)
        seg.setObjectName("shockerLayout")
        row.addWidget(seg)
        box.setObjectName("shockerLayoutSwitch")
        box.group = group
        self._explain(box, LAYOUT_TITLE, LAYOUT_TIP)
        head.addWidget(box)
        self._panel_w["layout_switch"] = box
        return box

    def _layout_picked(self, name: str) -> None:
        if name != self._shocker_buttons():
            self.controller.set_shocker_layout(name)

    # ---- what reaches them -------------------------------------

    def _shock_state(self) -> QFrame:
        strip = QFrame()
        strip.setObjectName("shockState")
        strip.setProperty("tone", "")
        if self._friends_big:
            strip.setProperty("big", "true")
        row = hbox(0, 8)
        row.setContentsMargins(12, 6, 12, 6)
        strip.setLayout(row)
        strip.head, strip.rest = QLabel(""), QLabel("")
        strip.head.setObjectName("stateHead")
        strip.rest.setWordWrap(True)
        row.addWidget(strip.head)
        row.addWidget(strip.rest, 1)
        self._explain(strip, "What reaches them",
                      "Armed: their shocks are real. Not armed: a shock arrives as a "
                      "vibration. Paused or Off: nothing reaches them until they switch it "
                      "back. Every strength and length here is a part of their own caps - "
                      "you can't go past them.")
        return strip

    def _set_shock_state(self, strip: QFrame, tone: str, head: str, rest: str) -> None:
        if strip.head.text() != head:
            strip.head.setText(head)
        rest = f"·  {rest}" if rest else ""
        if strip.rest.text() != rest:
            strip.rest.setText(rest)
        if strip.property("tone") != tone:
            strip.setProperty("tone", tone)
            self._repolish(strip)
            for lbl in (strip.head, strip.rest):
                self._repolish(lbl)

    def _stop_all_button(self, on_click) -> QPushButton:
        b = QPushButton("Stop all")
        b.setProperty("role", "danger")
        b.setProperty("size", "small")
        if self._friends_big:
            b.setProperty("big", "true")
        b.setToolTip("Every one of their shockers stops now")
        b.clicked.connect(lambda _=False: on_click())
        return b

    def _new_party(self, title: str) -> ShockParty:
        c = self.controller
        return ShockParty(
            title, _SHOCK,
            on_fire=lambda pairs, op, it, ms, wms, wi: c.party_shock(pairs, op, it, ms, wms, wi),
            on_hold=lambda pairs, op, it: c.party_hold(pairs, op, it),
            on_release=lambda pairs: c.party_release(pairs),
            on_stop=lambda pairs: c.party_stop(pairs),
            on_ticks=lambda ticked: self._party_ticked(ticked),
            big=self._friends_big, card_cls=self._card_class())

    # ---- the panel rebuilds ------------------------------------

    def _keep_shockers(self) -> None:
        """The cards are about to go: nothing they hold may keep running,
        and the cards that replace them start where they were (in the
        layout they were built in)."""
        w = self._panel_w
        memory = self._shock_memory(w.get("layout"))
        for i, card in enumerate(w.get("shockers") or []):
            card.release()
            memory[(w.get("kind"), w.get("id"), i)] = card.settings()
        party = w.get("party")
        if party is not None:
            party.release()
            memory[("party", w.get("kind"), w.get("id"))] = party.settings()

    # ---- one friend --------------------------------------------

    def _build_friend_shockers(self, fid: str, theirs: Dict[str, Any]) -> None:
        """Their shockers: only while they let you use them -- their
        Shockers switch for you, and their own On and Share with friends
        on Home. Any of those off and the section isn't there at all."""
        w, c = self._panel_w, self.controller
        names = theirs["shockers"]
        cls = self._card_class()
        w["layout"] = self._shocker_buttons()
        lay, head = self._friends_section("THEIR SHOCKERS", _SHOCK)
        self._layout_switch(head)
        # OpenShock's card has no STOP of its own (pressing a running button
        # again stops it), so its panel keeps Stop all even for one shocker
        if len(names) > 1 or (names and cls is OpenShockCard):
            head.addWidget(self._stop_all_button(
                lambda: [card.stop() for card in w.get("shockers") or []]))
        w["state"] = self._shock_state()
        lay.addWidget(w["state"])
        if not names:
            lay.addWidget(self._muted_label(
                "They allow you their shockers, but none is connected right now."))
            return
        kept = self._shock_memory().get(("party", "friend", fid)) or {}
        ticked: Set[Tuple[str, int]] = set(kept.get("ticked") or ())
        party: Optional[ShockParty] = None
        if len(names) > 1:
            party = self._new_party("Party")
            party.set_targets([(fid, i, f"{i + 1} · {n}", _SHOCK) for i, n in enumerate(names)],
                              ticked)
            if kept:
                party.restore(kept)
            lay.addWidget(party)
            # shown only once it has a parent: before, it would open as a
            # window of its own for a moment
            party.setVisible(bool(party.ticked()))
        w["party"] = party
        cards: List[QWidget] = []
        for i, n in enumerate(names):
            card = cls(
                f"{i + 1} · {n}", _SHOCK,
                on_fire=lambda op, it, ln, wms, wi, s=i: c.friend_shock(fid, [s], it, ln, op, wms, wi),
                on_hold=lambda op, it, s=i: c.friend_hold(fid, [s], op, it),
                on_release=lambda s=i: c.friend_release(fid, [s]),
                on_stop=lambda s=i: c.friend_stop(fid, [s]),
                big=self._friends_big, party_box=party is not None)
            card.set_caps(*their_caps(theirs, i))
            card.set_rules(*their_rules(theirs, [i]))
            st = self._shock_memory().get(("friend", fid, i))
            if st is not None:
                card.restore(st)
            if card.party_box is not None:
                card.party_box.setChecked((fid, i) in ticked)
                card.party_box.toggled.connect(
                    lambda on, pair=(fid, i): self._card_party_ticked(pair, on))
            cards.append(card)
        w["shockers"] = cards
        lay.addWidget(self._cards_grid(cards))

    def _card_party_ticked(self, pair: Tuple[str, int], on: bool) -> None:
        party = self._panel_w.get("party")
        if party is None:
            return
        ticked = set(party.ticked())
        (ticked.add if on else ticked.discard)(pair)
        party.set_ticked(ticked)
        self._party_ticked(ticked)

    def _party_ticked(self, ticked: Set[Tuple[str, int]]) -> None:
        """The party's ticks changed (its list or a card's Party box): the
        cards show the same, and a friend's party shows while one is ticked."""
        w = self._panel_w
        party = w.get("party")
        if party is None:
            return
        for i, card in enumerate(w.get("shockers") or []):
            box = card.party_box
            if box is not None and box.isChecked() != ((w.get("id"), i) in ticked):
                box.blockSignals(True)
                box.setChecked((w.get("id"), i) in ticked)
                box.blockSignals(False)
        if w.get("kind") == "friend":
            if not ticked:
                party.release()
            party.setVisible(bool(ticked))
        kept = dict(self._shock_memory().get(("party", w.get("kind"), w.get("id"))) or {})
        kept.update(party.settings())
        self._shock_memory()[("party", w.get("kind"), w.get("id"))] = kept

    def _update_friend_shockers(self, f: Dict[str, Any]) -> None:
        w, theirs = self._panel_w, f["theirs"]
        blocked = bool(theirs.get("paused") or theirs.get("off"))
        for i, card in enumerate(w.get("shockers") or []):
            card.set_caps(*their_caps(theirs, i))
            card.set_rules(*their_rules(theirs, [i]))
            card.set_blocked(blocked)
        party = w.get("party")
        if party is not None:
            party.card.set_rules(*their_rules(theirs, range(len(theirs.get("shockers") or []))))
            party.card.set_blocked(blocked)
        strip = w.get("state")
        if strip is None:
            return
        if theirs.get("not_here"):
            self._set_shock_state(strip, "", "Not here", NOT_HERE_SHOCKERS)
        elif theirs.get("paused"):
            self._set_shock_state(strip, "", "Paused", "they paused all friends - nothing "
                                                       "reaches them")
        elif theirs.get("off"):
            self._set_shock_state(strip, "", "Off", "their Off is on - nothing reaches them")
        elif theirs["armed"]:
            self._set_shock_state(strip, "armed", "⚠  ARMED", "shocks are real")
        else:
            self._set_shock_state(strip, "", "Not armed", "a shock arrives as a vibration")

    # ---- a group -----------------------------------------------

    def _build_group_shockers(self) -> None:
        w = self._panel_w
        w["layout"] = self._shocker_buttons()
        lay, head = self._friends_section("EVERYONE'S SHOCKERS", _SHOCK)
        self._layout_switch(head)
        w["state"] = self._shock_state()
        lay.addWidget(w["state"])
        party = self._new_party("Everyone")
        kept = self._shock_memory().get(("party", "group", w["id"]))
        w["party_kept"] = kept
        if kept:
            party.restore(kept)
        w["party"] = party
        w["shockers"] = []
        lay.addWidget(party)

    def _update_group_shockers(self, st: Dict[str, Any], members: List[Dict[str, Any]]) -> None:
        w = self._panel_w
        party = w.get("party")
        if party is None:
            return
        targets = []
        for f in members:
            theirs = f["theirs"]
            if not f["linked"] or not theirs or not theirs.get("allow_shock"):
                continue
            hue = friend_hue(st["friends"].index(f))
            nick = display_name(f["nick"], f["id"])
            for i, n in enumerate(theirs.get("shockers") or []):
                targets.append((f["id"], i, f"{nick} · {n}", hue))
        # what any of them lets through (each receiver drops the rest)
        ops, pairs = set(), []
        for f in members:
            theirs = f["theirs"]
            if f["linked"] and theirs and theirs.get("allow_shock"):
                slots = range(len(theirs.get("shockers") or []))
                ops |= their_rules(theirs, slots)[0]
                pairs += [(theirs, slot) for slot in slots]
        if not targets:
            ops = set(OPS)
        warn_ok = _warn_ok(pairs)
        party.card.set_rules(ops, _reasons(pairs, ops, warn_ok), warn_ok)
        kept = w.pop("party_kept", None)
        if kept is not None:
            # first time: the ticks it had, or every one of them
            old = set(kept.get("ticked") or ())
            party.set_targets(targets, old if old else {(p, s) for p, s, _l, _h in targets})
        else:
            party.set_targets(targets)
        allowed = [f for f in members if f["theirs"] and f["theirs"].get("allow_shock")]
        armed = [display_name(f["nick"], f["id"]) for f in allowed if f["theirs"].get("armed")]
        strip = w.get("state")
        if not allowed:
            self._set_shock_state(strip, "", "Nobody here", "allows you their shockers right now")
        elif armed:
            self._set_shock_state(strip, "armed", f"⚠  {len(armed)} of {len(allowed)} ARMED",
                                  "real shocks for " + ", ".join(armed))
        else:
            self._set_shock_state(strip, "", "Not armed",
                                  "their shocks arrive as vibrations")
