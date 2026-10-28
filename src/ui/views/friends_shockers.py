"""Friends view, the shockers on the control panel: a friend's (one
PiShock-style card per shocker -- shocker_card.py -- and, once two or more
are ticked for Party, PiShock's Party panel over them -- shock_party.py) or
everyone's in a group (the Party panel alone, over every member's
shockers). Over the cards, a strip says what reaches them: armed (shocks
are real), not armed (a shock arrives as a vibration), paused or Off.
Part of FriendsMixin (friends.py), with friends_panel.py."""

from typing import Any, Dict, List, Optional, Set, Tuple

from PySide6.QtWidgets import QFrame, QLabel, QPushButton

from remote_protocol import display_name, shocker_caps
from ui.layout_helpers import hbox
from ui.theme import FRIEND_SHOCK_HUE as _SHOCK, friend_hue
from ui.views.shock_party import ShockParty
from ui.views.shocker_card import ShockerCard


def their_caps(theirs: Dict[str, Any], slot: int = -1):
    """((shock cap, vibrate cap, longest pulse ms), max hold s) from a
    friend's status -- one shocker's own (`slot`), or their hub-wide."""
    return shocker_caps(theirs, slot), float(theirs.get("max_hold_s") or 0.0)


class FriendsShockersMixin:

    def _shock_memory(self) -> Dict[Any, Any]:
        """How the shocker cards and parties were set, across rebuilds --
        this window's own."""
        if "_shocker_memory" not in vars(self):
            self._shocker_memory = {}
        return self._shocker_memory

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
            big=self._friends_big)

    # ---- the panel rebuilds ------------------------------------

    def _keep_shockers(self) -> None:
        """The cards are about to go: nothing they hold may keep running,
        and the cards that replace them start where they were."""
        memory, w = self._shock_memory(), self._panel_w
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
        lay, head = self._friends_section("THEIR SHOCKERS", _SHOCK)
        if len(names) > 1:
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
        cards: List[ShockerCard] = []
        for i, n in enumerate(names):
            card = ShockerCard(
                f"{i + 1} · {n}", _SHOCK,
                on_fire=lambda op, it, ln, wms, wi, s=i: c.friend_shock(fid, [s], it, ln, op, wms, wi),
                on_hold=lambda op, it, s=i: c.friend_hold(fid, [s], op, it),
                on_release=lambda s=i: c.friend_release(fid, [s]),
                on_stop=lambda s=i: c.friend_stop(fid, [s]),
                big=self._friends_big, party_box=party is not None)
            card.set_caps(*their_caps(theirs, i))
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
            card.set_blocked(blocked)
        party = w.get("party")
        if party is not None:
            party.card.set_blocked(blocked)
        strip = w.get("state")
        if strip is None:
            return
        if theirs.get("paused"):
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
        lay, _head = self._friends_section("EVERYONE'S SHOCKERS", _SHOCK)
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
