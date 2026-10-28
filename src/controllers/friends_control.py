"""Friends, part 2: controlling them -- your levels, auto modes, Override,
held shockers, shocks and their strength slider, for one friend or for
everyone picked on the page (a group). Called from the page (GUI thread)
and from the avatar menu (friends_menu, OSC thread); every value is swapped
in whole (copy-on-write), and `_friends_cmd_for` -- on the link's thread --
reads what is set and builds the cmd each friend gets.

Mixed into FriendsFacade; see friends_facade.py for what the host has.
"""

import time
from typing import Any, Dict, List, Optional, Tuple

import friend_patterns
import remote_protocol as proto
from controllers.friends_common import op_text, unit

_STRENGTH_RESEND_S = 3.0     # a strength change rides the next cmds this long


class FriendsControlMixin:
    """Mixin: what you do to friends."""

    # ------------------------------------------------------------------
    # Everyone picked at once (a group's panel, the menu)
    # ------------------------------------------------------------------

    def set_targets_level(self, value: float) -> None:
        for peer in self._friends_targets():
            self.set_friend_level(peer, proto.ALL_TOYS, value)

    def set_targets_strength(self, value: float) -> None:
        for peer in self._friends_targets():
            self.set_friend_strength(peer, value)

    def set_targets_override(self, on: bool) -> None:
        for peer in self._friends_targets():
            self.set_friend_override(peer, proto.ALL_TOYS, on)

    def set_targets_pattern(self, wave: str, period: float = 2.0,
                            lo: float = 0.0, hi: float = 1.0) -> None:
        for peer in self._friends_targets():
            self.set_friend_pattern(peer, proto.ALL_TOYS, wave, period, lo, hi)

    def targets_shock(self, slots: List[int], intensity: float, length: float,
                      op: str = "shock", warn_ms: int = 0, warn_intensity: float = 0.0) -> int:
        """One operation to everyone selected who allows it. Returns how
        many it went to."""
        sent = 0
        for peer in self._friends_targets():
            sent += bool(self.friend_shock(peer, slots, intensity, length, op, warn_ms, warn_intensity))
        if not sent:
            self._friends_note(f"{op.capitalize()} not sent - nobody selected allows it, "
                               "or no shocker is ticked")
        return sent

    def targets_hold(self, slots: List[int], op: str, intensity: float) -> None:
        for peer in self._friends_targets():
            self.friend_hold(peer, slots, op, intensity)

    def targets_release(self, slots: List[int]) -> None:
        for peer in self._friends_targets():
            self.friend_release(peer, slots)

    def targets_stop(self, slots: List[int]) -> None:
        for peer in self._friends_targets():
            self.friend_stop(peer, slots)

    # ------------------------------------------------------------------
    # A party (PiShock's Party Mode): shockers picked one by one, maybe of
    # several friends -- the page decides which of them each press drives
    # ------------------------------------------------------------------

    @staticmethod
    def _party_slots(pairs: List[Tuple[str, int]]) -> Dict[str, List[int]]:
        by_peer: Dict[str, List[int]] = {}
        for peer, slot in pairs:
            by_peer.setdefault(peer, []).append(int(slot))
        return by_peer

    def party_shock(self, pairs: List[Tuple[str, int]], op: str, intensity: float,
                    length_ms: int, warn_ms: int = 0, warn_intensity: float = 0.0) -> int:
        """One operation to those shockers. The length is real time, each
        shocker's own longest pulse at most; the strength a part of each
        one's caps. Returns how many friends it went to."""
        sent = 0
        for peer, slots in self._party_slots(pairs).items():
            st = self._status_of(peer)
            # shockers with different longest pulses need lengths of their own
            by_length: Dict[float, List[int]] = {}
            for slot in slots:
                top = max(proto.SHOCK_MIN_MS, proto.shocker_caps(st, slot)[2])
                ms = max(proto.SHOCK_MIN_MS, min(int(length_ms), top))
                length = 0.0 if top <= proto.SHOCK_MIN_MS else (ms - proto.SHOCK_MIN_MS) / (
                    top - proto.SHOCK_MIN_MS)
                by_length.setdefault(round(length, 3), []).append(slot)
            went = False
            for length, group in by_length.items():
                went |= bool(self.friend_shock(peer, group, intensity, length, op, warn_ms,
                                               warn_intensity))
            sent += went
        if not sent:
            self._friends_note(f"{op.capitalize()} not sent - nobody in the party allows it "
                               "right now")
        return sent

    def party_hold(self, pairs: List[Tuple[str, int]], op: str, intensity: float) -> None:
        for peer, slots in self._party_slots(pairs).items():
            self.friend_hold(peer, slots, op, intensity)

    def party_release(self, pairs: List[Tuple[str, int]]) -> None:
        for peer, slots in self._party_slots(pairs).items():
            self.friend_release(peer, slots)

    def party_stop(self, pairs: List[Tuple[str, int]]) -> None:
        for peer, slots in self._party_slots(pairs).items():
            self.friend_stop(peer, slots)

    # ------------------------------------------------------------------
    # One friend
    # ------------------------------------------------------------------

    # ------------------------------------------------------------------
    # Sync with others: one panel per friend among those who sync
    # ------------------------------------------------------------------

    def _sync_on(self, peer: str) -> bool:
        f = self.friends_settings.get_friend(peer)
        return bool(f.get("sync", True)) if f is not None else False

    def _panel_changed(self, peer: str) -> None:
        """A change of yours to their toy cards: past the newest version
        you have seen, so it wins over the others' older ones."""
        if self._sync_on(peer):
            self._my_pseq = {**self._my_pseq, peer: self._my_pseq.get(peer, 0) + 1}

    def set_friend_sync(self, peer: str, on: bool) -> None:
        """Sync with others: share one set of toy cards for this friend
        with everyone else who syncs -- or drive on your own (the highest
        level wins, as between friends who don't)."""
        self.friends_settings.set_sync(peer, on)
        # joining takes the shared panel as it stands; leaving keeps yours
        self._my_pseq = {**self._my_pseq, peer: 0}
        self.friends_link.push_cmd(peer)
        self._friends_note(f"You {'share one panel with the others' if on else 'drive on your own'}"
                           f" on {self._friend_nick(peer)}'s toys", key=("sync", peer))

    def _friend_panel_in(self, peer: str, msg: Dict[str, Any]) -> None:
        """Their OGP's shared panel (the link's thread): newer than yours,
        or the same version won by someone else -- take it as your own."""
        got = proto.read_panel(msg)
        if got is None or not self._sync_on(peer):
            return
        seq, levels, override, patterns = got
        mine = self._my_pseq.get(peer, 0)
        if seq < mine:
            return                          # yours is newer: on its way to them
        now_mine = proto.read_panel(proto.make_panel(
            mine, self._my_levels.get(peer, {}), self._my_override.get(peer, ()),
            self._my_patterns.get(peer)))
        self._my_pseq = {**self._my_pseq, peer: seq}
        if now_mine is not None and now_mine[1:] == (levels, override, patterns):
            return
        self._my_levels = {**self._my_levels, peer: dict(levels)}
        self._my_override = {**self._my_override, peer: set(override)}
        self._my_patterns = {**self._my_patterns, peer: dict(patterns)}
        self.friends_link.push_cmd(peer)
        self.thread_queue.put(("friends", ("refresh", None)))

    def _friend_others_in(self, peer: str, msg: Dict[str, Any]) -> None:
        names = proto.read_others(msg)
        if names != self._friend_others.get(peer, []):
            self._friend_others = {**self._friend_others, peer: names}
            self.thread_queue.put(("friends", ("refresh", None)))

    # ------------------------------------------------------------------
    # One friend's cards
    # ------------------------------------------------------------------

    def set_friend_level(self, peer: str, toy: str, value: float) -> None:
        """Your level for one of the friend's toys, or proto.ALL_TOYS."""
        v = unit(value)
        levels = dict(self._my_levels.get(peer, {}))
        was = any(x > 0 for x in levels.values())
        if v > 0:
            levels[str(toy)] = v
        else:
            levels.pop(str(toy), None)
        self._my_levels = {**self._my_levels, peer: levels}
        self._panel_changed(peer)
        self.friends_link.push_cmd(peer)
        now = any(x > 0 for x in levels.values())
        if now != was:
            self._friends_note(f"You {'started' if now else 'stopped'} driving "
                               f"{self._friend_nick(peer)}'s toys")

    def set_friend_override(self, peer: str, toy: str, on: bool) -> None:
        """Override: while you drive this toy (or all of them), your level
        replaces their own output instead of the higher of the two winning.
        Their Off, Pause, strength and the toy's max still hold."""
        toys = set(self._my_override.get(peer, ()))
        (toys.add if on else toys.discard)(str(toy))
        self._my_override = {**self._my_override, peer: toys}
        self._panel_changed(peer)
        self.friends_link.push_cmd(peer)
        what = "all their toys" if toy == proto.ALL_TOYS else toy
        self._friends_note(f"You {'override' if on else 'no longer override'} "
                           f"{self._friend_nick(peer)}'s own output on {what}",
                           key=("ovr", peer, toy))

    def set_friend_pattern(self, peer: str, toy: str, wave: str, period: float = 2.0,
                           lo: float = 0.0, hi: float = 1.0) -> None:
        """An auto mode for one toy (or proto.ALL_TOYS) that their OGP plays
        by itself; wave "" switches it off."""
        pats = dict(self._my_patterns.get(peer, {}))
        clean = friend_patterns.clean(wave, period, lo, hi) if wave else None
        was = pats.get(str(toy))
        if clean is None:
            pats.pop(str(toy), None)
        else:
            pats[str(toy)] = clean
        self._my_patterns = {**self._my_patterns, peer: pats}
        self._panel_changed(peer)
        self.friends_link.push_cmd(peer)
        what = "all their toys" if toy == proto.ALL_TOYS else toy
        if clean is None:
            if was is not None:
                self._friends_note(f"You stopped the auto mode on {self._friend_nick(peer)}'s {what}")
        elif was is None or was[0] != clean[0]:
            self._friends_note(f"You started {friend_patterns.LABELS[clean[0]]} on "
                               f"{self._friend_nick(peer)}'s {what}", key=("pat", peer, toy))

    def friend_hold(self, peer: str, slots: List[int], op: str, intensity: float) -> None:
        """Hold: those shockers run while you hold the button (within their
        max hold and rest); friend_release lets go."""
        if op not in proto.OPS:
            return
        holds = dict(self._my_holds.get(peer, {}))
        for slot in slots:
            if 0 <= int(slot) < proto.MAX_SHOCKERS:
                holds[int(slot)] = (op, unit(intensity))
        self._my_holds = {**self._my_holds, peer: holds}
        self.friends_link.push_cmd(peer)

    def friend_release(self, peer: str, slots: List[int]) -> None:
        holds = {k: v for k, v in self._my_holds.get(peer, {}).items() if k not in set(slots)}
        self._my_holds = {**self._my_holds, peer: holds}
        self.friends_link.push_cmd(peer)

    def friend_stop(self, peer: str, slots: List[int]) -> None:
        """Stop: those shockers end now on their side, a warned shock
        included, and your holds there let go."""
        self.friend_release(peer, slots)
        msg = proto.make_stop(proto.new_id(), slots)
        if msg["slots"]:
            self.friends_link.send_event(peer, msg)
            self._friends_note(f"You stopped {self._friend_nick(peer)}'s shockers",
                               key=("stp", peer))

    def set_friend_strength(self, peer: str, value: float) -> None:
        v = unit(value)
        self._my_seq = max(self._my_seq + 1, int(time.time() * 1000))
        self._my_strength = {**self._my_strength, peer: (self._my_seq, v, time.monotonic())}
        self.friends_link.push_cmd(peer)
        self._friends_note(f"You set {self._friend_nick(peer)}'s strength to {round(v * 100)} %",
                           key=("str-out", peer))

    def friend_shock(self, peer: str, slots: List[int], intensity: float, length: float,
                     op: str = "shock", warn_ms: int = 0, warn_intensity: float = 0.0) -> bool:
        """One operation -- shock, vibrate or beep -- on those shocker
        slots, with `warn_ms` of warning vibration first (PiShock's
        Warning; 0 for none). Intensity and length are 0..1 of THEIR caps."""
        st = self._status_of(peer)
        if not st.get("allow_shock") or not slots or op not in proto.OPS:
            return False
        msg = proto.make_shock(proto.new_id(), slots, intensity, length,
                               op, "vibrate" if warn_ms > 0 else "", warn_intensity, warn_ms)
        self.friends_link.send_event(peer, msg)
        names = [st["shockers"][s] for s in msg["slots"] if s < len(st["shockers"])]
        shock_cap, vib_cap, top = proto.shocker_caps(st, msg["slots"][0] if msg["slots"] else 0)
        lvl, ms = proto.shock_values(msg["int"], msg["len"],
                                     shock_cap if op == "shock" else vib_cap, top)
        first = f"{warn_ms / 1000:.1f} s warning, then " if msg.get("warn") else ""
        what = op_text(op, lvl, st.get("armed"), "their ")
        self._friends_note(f"You → {self._friend_nick(peer)}: {first}{what} · {ms / 1000:.1f} s"
                           f" on {', '.join(names) or 'no shocker'}")
        return True

    def set_friend_levels_watch(self, peer: Optional[str]) -> None:
        """Whose panel the page shows now (None: nobody's, a group's, or
        the page is hidden). GUI thread. Only that friend's OGP sends their
        toys' live levels -- for the cards' meters."""
        self._lw_peer = peer or None
        if peer:
            self._lw_was = self._lw_was | {peer}

    # ------------------------------------------------------------------
    # What the link sends each friend -- the link's thread
    # ------------------------------------------------------------------

    def _friends_levels_watch_more_for(self, peer: str) -> Dict[str, Dict[str, Any]]:
        """Says "watching" (``lw``) to the friend whose panel is open,
        repeated like a status; "not any more" to one who had it open."""
        if peer == self._lw_peer:
            return {"lw": proto.LEVELS_WATCH}
        if peer in self._lw_was:
            return {"lw": proto.LEVELS_UNWATCH}
        return {}

    def _friends_cmd_for(self, peer: str) -> Optional[Dict[str, Any]]:
        if peer not in self._friend_perms:
            return None
        s = self._my_strength.get(peer)
        strength = (s[0], s[1]) if s and time.monotonic() - s[2] < _STRENGTH_RESEND_S else None
        return proto.make_cmd(self._my_levels.get(peer, {}), strength,
                              self._my_override.get(peer, ()), self._my_patterns.get(peer),
                              self._my_holds.get(peer),
                              syn=self._my_pseq.get(peer, 0) if self._sync_on(peer) else None)
