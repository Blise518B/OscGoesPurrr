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
import shocker_layout
from controllers.friends_common import came_through, op_text, unit
from event_log import OUT, SHOCK, TOYS, VIA_PARTY

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
            why = "nobody selected allows it, or no shocker is ticked"
            self._friends_note(f"{op.capitalize()} not sent - {why}", kind=SHOCK, op=op,
                               dir=OUT, held=why)
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
        with came_through(VIA_PARTY):            # the log: from Party Mode
            return self._party_shock(pairs, op, intensity, length_ms, warn_ms, warn_intensity)

    def _party_shock(self, pairs: List[Tuple[str, int]], op: str, intensity: float,
                     length_ms: int, warn_ms: int, warn_intensity: float) -> int:
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
            why = "nobody in the party allows it right now"
            self._friends_note(f"{op.capitalize()} not sent - {why}", kind=SHOCK, op=op,
                               dir=OUT, held=why)
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
    # Sync with others: their call (Blise's, 2026-11-17) -- your panel
    # always says its version and takes their shared panel when it comes;
    # whether there is one is up to them (``sep`` in their ``st``)
    # ------------------------------------------------------------------

    def _panel_changed(self, peer: str) -> None:
        """A change of yours to their toy cards: past the newest version
        you have seen, so it wins over the others' older ones."""
        self._my_pseq = {**self._my_pseq, peer: self._my_pseq.get(peer, 0) + 1}

    def _friend_panel_in(self, peer: str, msg: Dict[str, Any]) -> None:
        """Their OGP's shared panel (the link's thread): newer than yours,
        or the same version won by someone else -- take it as your own.
        It only comes while they sync everyone."""
        got = proto.read_panel(msg)
        if got is None:
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

    def _takes_toys(self, peer: str) -> bool:
        """Their OGP takes your toy cards and strength right now. The page
        hides those when it doesn't; the avatar menu can still move them."""
        st = self._status_of(peer)
        return bool(st.get("allow_toys")) and not st.get("paused")

    def _toys_note(self, peer: str, text: str, key: Any = None, op: str = "") -> None:
        """A log line about their toys (`{who}` for their name), only if the
        change reaches them."""
        if self._takes_toys(peer):
            self._friends_note(text, key=key, who=peer, kind=TOYS, op=op, dir=OUT)

    def set_friend_level(self, peer: str, toy: str, value: float, source: str = "ui") -> None:
        """Your level for one of the friend's toys, or proto.ALL_TOYS.
        `source` "menu": it came from your avatar's menu (the menu then
        needn't hear it back)."""
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
        if source != "menu":
            self._menu_follow(peer, str(toy))
        now = any(x > 0 for x in levels.values())
        if now != was:
            self._toys_note(peer, f"You {'started' if now else 'stopped'} driving {{who}}'s toys",
                            op="start" if now else "stop")

    def set_friend_override(self, peer: str, toy: str, on: bool, source: str = "ui") -> None:
        """Override: while you drive this toy (or all of them), your level
        replaces their own output instead of the higher of the two winning.
        Their Off, Pause, strength and the toy's max still hold."""
        toys = set(self._my_override.get(peer, ()))
        (toys.add if on else toys.discard)(str(toy))
        self._my_override = {**self._my_override, peer: toys}
        self._panel_changed(peer)
        self.friends_link.push_cmd(peer)
        if source != "menu":
            self._menu_follow(peer, str(toy))
        what = "all their toys" if toy == proto.ALL_TOYS else toy
        self._toys_note(peer, f"You {'override' if on else 'no longer override'} "
                              f"{{who}}'s own output on {what}",
                        key=("ovr", peer, toy), op="override")

    def set_friend_pattern(self, peer: str, toy: str, wave: str, period: float = 2.0,
                           lo: float = 0.0, hi: float = 1.0, source: str = "ui") -> None:
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
        if source != "menu":
            self._menu_follow(peer, str(toy))
        what = "all their toys" if toy == proto.ALL_TOYS else toy
        if clean is None:
            if was is not None:
                self._toys_note(peer, f"You stopped the auto mode on {{who}}'s {what}",
                                op="pattern")
        elif was is None or was[0] != clean[0]:
            self._toys_note(peer, f"You started {friend_patterns.LABELS[clean[0]]} on "
                                  f"{{who}}'s {what}", key=("pat", peer, toy), op="pattern")

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
            self._friends_note("You stopped {who}'s shockers", key=("stp", peer), who=peer,
                               kind=SHOCK, op="stop", dir=OUT)

    def set_friend_strength(self, peer: str, value: float, source: str = "ui") -> None:
        """Their strength slider. Unlike a level it is one change, not a
        state, so one they don't take now is dropped: it mustn't land the
        moment they switch your Toys back on."""
        if not self._takes_toys(peer):
            return
        v = unit(value)
        self._my_seq = max(self._my_seq + 1, int(time.time() * 1000))
        self._my_strength = {**self._my_strength, peer: (self._my_seq, v, time.monotonic())}
        self.friends_link.push_cmd(peer)
        if source != "menu":
            self._menu_follow_strength(peer, v)
        pct = round(v * 100)
        self._friends_note(f"You set {{who}}'s strength to {pct} %", key=("str-out", peer),
                           who=peer, kind=TOYS, op="strength", dir=OUT, level=pct)

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
        armed = bool(st.get("armed"))
        what = op_text(op, lvl, armed, "their ")
        went = "vibrate" if op == "shock" and not armed else op
        self._friends_note(f"You → {{who}}: {first}{what} · {ms / 1000:.1f} s"
                           f" on {', '.join(names) or 'no shocker'}",
                           who=peer, kind=SHOCK, op=went, dir=OUT,
                           level=None if op == "beep" else lvl, ms=ms, on=names,
                           asked=op if went != op else "")
        return True

    # ------------------------------------------------------------------
    # The shocker buttons: PiShock's panel or OpenShock's -- one setting
    # for every panel (shocker_layout.py). Only a face: both layouts call
    # the same friend_* / party_* methods above.
    # ------------------------------------------------------------------

    def get_shocker_layout(self) -> str:
        """Whose shocker buttons the panels show: "pishock" (the default)
        or "openshock"."""
        get = getattr(self, "get_app_setting", None)
        return shocker_layout.clean(get(shocker_layout.SETTING_KEY, shocker_layout.DEFAULT)
                                    if get is not None else None)

    def set_shocker_layout(self, name: str) -> None:
        """Switch every panel's shocker buttons (remembered). Only how they
        look: nothing is sent, nothing loosens -- so its undo never asks."""
        name = shocker_layout.clean(name)
        if name == self.get_shocker_layout():
            return
        self.set_app_setting(shocker_layout.SETTING_KEY, name)
        self._friends_refresh_ui()

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
                              syn=self._my_pseq.get(peer, 0))
