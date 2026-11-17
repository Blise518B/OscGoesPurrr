"""Friends, part 4: what friends do to you. Their levels and auto modes
reach the router through `get_friend_drive_mode` (the GUI thread, every
routing tick); their shocks, holds, warnings and Stops go through your
PiShockEngine, so your caps, your rest after each pulse, your arming and
each shocker's Shock / Vibrate / Beep switches always hold -- a friend can
never widen them, and what each shocker allows on the Shockers page is what
every friend gets (the per-friend share was removed, Blise's call
2026-11-17). Me and the web remote hold to the same like any friend.
"Only friends in my instance" refuses whoever isn't in it like Pause
(`_not_here`, friends_instance.py): one set lookup on the way in.

Nothing here trusts the sender's panel (Blise's rule, 2026-11-16: what a
modified client sends is corrected to what OGP itself would send): a
warning is the vibration OGP's panels send (a beep only where Vibrate is
off), at least proto.WARN_MIN_MS long, and it plays in full before its shock
(it waits out a pulse and its rest); a pulse carries the shocker's own
longest pulse as the engine's `run_cap_ms` (the engine minds
every rest for every source); and how often they may make your shockers
act is a budget per sender (inbound_rate), checked before anything else --
cheap checks on values, no wait and no queue hop. So is how often they may
change your toy cards (`_cards_within_budget`): past it only what lets go
lands -- a toy stopped, an auto mode ended, Override off. A value corrected
on its way is logged as asked, with what went out and why (event_log's
`correction`). Sync with others is yours alone to choose (the Friends
page, `set_friends_sync`; Blise's call, 2026-11-17): on, everyone driving
you -- friends, the web remote, Me -- shares one set of toy cards and the
newest change plays, decided on the versions this OGP vouches for
(`_sync_version`), so saying "newer" without changing anything wins
nothing; off, each drives on their own and the highest wins. Whatever a
sender says about syncing is ignored.

Threads: cmds, shocks and Stops arrive on the link's thread; holds and
warnings run on the GUI tick (`_pump_friend_holds`). Each friend's hold
and each warning reaches the engine as a source of its own (`hold_source`,
`warning_source`): the engine plays the strongest, and one letting go
never cuts another's. `_friend_lock`
guards `_holding`, `_warnings` and `_friend_holds`, which both change.

Mixed into FriendsFacade; see friends_facade.py for what the host has.
"""

import time
from collections import deque
from typing import Any, Dict, List, Mapping, Optional, Tuple

import friend_patterns
import remote_protocol as proto
from pishock_engine import GROUP_AVATAR, GROUP_FRIENDS, went_out
from controllers.friends_common import (
    ME, Drive, came_through, coming_through, op_text, shocker_label,
)
from event_log import IN, SETTINGS, SHOCK, TOYS, VIA_MENU

# a sender's shock and Stop ids remembered, to drop their copies
_SEEN_PER_PEER = 64

# Sync with others (`_sync_version`): how far one real change may put its
# sender's version past the newest -- far more than OGP or a browser ever
# count between two cmds (one per action), and still 2^33 changes short of
# MAX_SEQ, so the numbers never run out.
SYNC_STEP = 2 ** 20
# how far past what this OGP vouches for a sender's number may be passed
# on in the shared panel (`pnl`'s seq) -- an honest one is a few re-sent
# values ahead at most
SYNC_SAY_AHEAD = 2 ** 19
SYNC_SEEN_MAX = 1024     # senders whose last version is remembered past a drop


class FriendsReceiveMixin:
    """Mixin: what friends do to you."""

    # who isn't in your instance while only friends in it may drive you
    # (FriendsInstanceMixin swaps it); nobody until it says otherwise
    _not_here: frozenset = frozenset()

    # ------------------------------------------------------------------
    # The router's hook -- GUI thread, every routing tick, per motor
    # ------------------------------------------------------------------

    def get_friend_drive(self, device_name: str) -> float:
        """The highest level any friend is driving this toy with right now
        (0..1, before your strength and the toy's output band)."""
        return self.get_friend_drive_mode(device_name)[0]

    def get_friend_drive_mode(self, device_name: str) -> tuple:
        """(level, override) for the router: the highest level any friend
        drives this toy with -- a hand-set level or an auto mode -- and
        whether one of them overrides your own output on it (only while
        they drive it)."""
        # getattr: the router is built (and may ask) before _friends_init
        drive = getattr(self, "_friend_drive", None) or {}
        if not drive:
            return 0.0, False
        now = time.monotonic()
        best, override = 0.0, False
        toy = str(device_name)[:proto.TOY_NAME_MAX]
        entries = []
        if not self.friends_settings.get_paused():
            # not in your instance: dropped when they became so, refused since
            # -- skipped here too, should a level have raced that
            blocked = self._not_here
            if blocked:
                drive = {p: d for p, d in drive.items() if p not in blocked}
            # synced: one panel, played once; separate: each plays on their own
            if self.friends_settings.get_sync_all():
                shared = _sync_playing(drive, now)
                entries = [shared] if shared is not None else []
            else:
                entries = [d for d in drive.values() if now - d.t <= proto.DRIVE_STALE_S]
        for d in entries:
            v = proto.drive_for(d.levels, toy)
            driving = v > 0.0
            for key in (toy, proto.ALL_TOYS):
                pat = d.pat.get(key)
                if pat is not None:
                    driving = True
                    v = max(v, friend_patterns.play(pat, now))
            if driving and (toy in d.ovr or proto.ALL_TOYS in d.ovr):
                override = True
            if v > best:
                best = v
        return best, override

    def friends_need_tick(self) -> bool:
        """An auto mode is playing: the router has to keep ticking for it."""
        drive = getattr(self, "_friend_drive", None)
        if not drive:
            return False
        now = time.monotonic()
        return any(d.pat and now - d.t <= proto.DRIVE_STALE_S for d in drive.values())

    def _is_driving(self, peer: str, now: float) -> bool:
        d = self._friend_drive.get(peer)
        return bool(d and now - d.t <= proto.DRIVE_STALE_S and d.drives())

    def _friends_sync_more_for(self, peer: str) -> Dict[str, Dict[str, Any]]:
        """For a friend who may drive your toys: who else drives them right
        now (``oth``) and, while you sync everyone and someone else drives
        too, the shared panel (``pnl``) -- to a sender that can take it (its
        ``cmd`` says a version). The link's thread. Light on the relays:
        nothing while nobody else drives (one empty ``oth`` when that ends),
        no panel for one driving alone. A browser on the web remote gets
        the count only: it never hears your friends' names."""
        perms = self._friend_perms.get(peer)
        if not perms or not perms[0]:
            return {}
        now = time.monotonic()
        drive = self._friend_drive
        others = sorted((self._friend_nick(q) for q in drive
                         if q != peer and q != ME and self._is_driving(q, now)), key=str.lower)
        if peer in getattr(self, "_web_guests", ()):
            others = ["someone"] * len(others)
        out: Dict[str, Dict[str, Any]] = {}
        if others or peer in self._oth_told:
            self._oth_told.add(peer)
            out["oth"] = proto.make_others(others)
        mine = drive.get(peer)
        newest = _sync_newest(drive)
        if (mine is not None and mine.syn is not None and len(drive) >= 2 and newest is not None
                and self.friends_settings.get_sync_all()):
            d = newest[1]
            out["pnl"] = proto.make_panel(_panel_seq(list(drive.values()), mine), d.levels, d.ovr,
                                          {k: v["p"] for k, v in d.pat.items()})
        return out

    # ------------------------------------------------------------------
    # Sync with others: yours alone to choose -- GUI thread
    # ------------------------------------------------------------------

    def get_friends_sync(self) -> bool:
        return self.friends_settings.get_sync_all()

    def set_friends_sync(self, on: bool) -> None:
        """Sync with others, for everyone driving your toys -- friends, the
        web remote, Me (Blise's call, 2026-11-17: only the one whose toys
        these are chooses): on, one set of toy cards and the newest change
        plays; off, each drives on their own and the highest wins. Their
        panels hear it in ``st`` (``sep``) and say it, read-only."""
        on = bool(on)
        if on == self.get_friends_sync():
            return
        self.friends_settings.set_sync_all(on)
        self._friends_sync_changed()
        self._friends_note("Everyone driving your toys shares one set of toy cards" if on
                           else "Everyone driving your toys drives on their own",
                           kind=SETTINGS, op="sync" if on else "separate")

    def _friends_sync_changed(self) -> None:
        """Sync with others switched, by hand or Ctrl+Z: the router plays
        it at once (the order is kept either way, `_friend_cmd_in`)."""
        self._needs_recalculation = True
        wake = getattr(self, "_wake_routing", None)   # the routing tick may sleep
        if wake is not None:
            wake()

    def _friends_st_for(self, peer: str) -> Optional[Dict[str, Any]]:
        """``st`` as it goes out (the link's thread, and Me's tick): the
        status, and whether you have everyone drive on their own -- one bit,
        nothing more (proto.mark_separate)."""
        return proto.mark_separate(self._friends_status_for(peer), not self.get_friends_sync())

    # ------------------------------------------------------------------
    # Sync with others: which change is the newest -- the link's thread
    # ------------------------------------------------------------------

    def _sync_version(self, peer: str, syn: int,
                      cards: Tuple[Dict[str, float], frozenset, Dict[str, Any]],
                      shared: Optional[Tuple[str, Drive]], may_change: bool = True) -> int:
        """The version of `peer`'s panel this OGP vouches for -- what decides
        the newest change, in place of the number they send (`syn`).

        An honest OGP or browser raises its number by one per action and
        takes the shared panel's when it catches up, so their numbers pass
        through as they are and the newest is decided as it always was. A
        number only gets past the newest with a real change: `cards` (levels,
        override toys, auto modes) that differ from what `peer` sent last
        AND from the shared panel's. Anything else -- a top-up, taking the
        shared panel, a value set to what it already was -- stays at the
        newest at most, so a sender that only says "newer" (a huge number, a
        rising one, a new web-remote identity) takes nothing.

        Remembered past a drop (`_sync_seen`): a friend who comes back -- a
        reconnect, Toys switched back on -- carries on from what they had.
        One never heard from joins as the panel stands -- after a restart,
        before anyone changed it, with its own number, as before.

        `may_change` False: cards that landed past the toy-card budget (only
        their letting go, `_cards_within_budget`) -- never a real change, so
        what was held back can't make anyone the newest. The newest letting
        go stays the newest, so it lands on the shared panel."""
        drive = self._friend_drive
        top = max((d.ver for p, d in drive.items() if p != peer), default=0)
        seen = self._sync_seen.get(peer)
        if seen is None:
            ver = min(syn, top + (SYNC_STEP if may_change and not self._sync_settled else 0))
        else:
            said, had, their_cards = seen
            shared_cards = _cards(shared[1]) if shared is not None else None
            if may_change and cards != their_cards and cards != shared_cards:   # a real change
                ver = min(syn, max(had, top) + SYNC_STEP)
                self._sync_settled = True
            elif syn == said:
                ver = had                       # a top-up: as it was
            else:
                ver = min(syn, max(had, top))   # never past the newest
        seen_now = self._sync_seen
        seen_now.pop(peer, None)
        seen_now[peer] = (syn, ver, cards)
        while len(seen_now) > SYNC_SEEN_MAX:
            del seen_now[next(iter(seen_now))]  # the longest unheard
        return ver

    def _drop_drive(self, peer: str) -> None:
        if peer in self._friend_drive:
            self._friend_drive = {k: v for k, v in self._friend_drive.items() if k != peer}
            self._needs_recalculation = True
            wake = getattr(self, "_wake_routing", None)   # the routing tick may sleep
            if wake is not None:
                wake()

    # ------------------------------------------------------------------
    # Their cmds, shocks and Stops -- the link's thread
    # ------------------------------------------------------------------

    def _friend_cmd_in(self, peer: str, msg: Dict[str, Any]) -> None:
        perms = self._friend_perms.get(peer)
        toys, shocks = bool(perms and perms[0]), bool(perms and perms[1])
        if not toys and not shocks:
            return
        if peer in self._not_here:
            self._not_here_cmd(peer, msg, toys)
            return
        if not toys:
            # Shockers on, Toys off: their holds (Remote, Continuous, Live
            # control) ride in the cmd too -- only those land. A strength
            # change of theirs is used up, as under Pause: it never lands
            # later, when Toys comes back on.
            _levels, strength = proto.read_cmd(msg)
            if strength is not None and strength[0] > self._friend_str_seq.get(peer, 0):
                self._friend_str_seq[peer] = strength[0]
            self._take_holds(peer, proto.read_cmd_more(msg)[2], time.monotonic())
            return
        levels, strength = proto.read_cmd(msg)
        override, patterns, holds = proto.read_cmd_more(msg)
        syn = proto.read_syn(msg)
        now = time.monotonic()
        old = self._friend_drive.get(peer)
        old_pat = old.pat if old is not None else {}
        levels, override, patterns, counted = self._cards_within_budget(
            peer, old, levels, override, patterns, now)
        # Synced, the shared panel's waves play on where they stand, so the
        # panel passing from one friend to another doesn't jump a cycle.
        # The order is kept whether you sync or not, so switching it on
        # takes effect at once.
        shared = _sync_newest(self._friend_drive)
        base: Mapping[str, Dict[str, Any]] = (shared[1].pat if shared is not None
                                              and self.friends_settings.get_sync_all() else {})
        pat = {toy: friend_patterns.anchor(
                   p, base.get(toy) if toy in base and base[toy]["p"][0] == p[0]
                   else old_pat.get(toy), now)
               for toy, p in patterns.items()}
        # a sender that says no version (an older OGP whose own switch was
        # off) is taken at its word as the newest: only a real change of its
        # cards gets it there, as for anyone
        ver = self._sync_version(peer, syn if syn is not None else proto.MAX_SEQ,
                                 (levels, frozenset(override), patterns), shared,
                                 may_change=counted)
        since = old.since if old is not None and old.ver == ver else now
        self._friend_drive = {**self._friend_drive,
                              peer: Drive(levels, now, frozenset(override), pat, syn, since, ver)}
        if (old is None or old.levels != levels or old.ovr != override or old.syn != syn
                or old.ver != ver
                or {k: v["p"] for k, v in old_pat.items()} != patterns):
            self._needs_recalculation = True
            wake = getattr(self, "_wake_routing", None)   # the routing tick may sleep
            if wake is not None:
                wake()
        self._take_holds(peer, holds, now)
        if strength is not None and strength[0] > self._friend_str_seq.get(peer, 0):
            self._friend_str_seq[peer] = strength[0]
            self._queue_strength(peer, strength[1])

    def _cards_within_budget(self, peer: str, old: Optional[Drive], levels: Dict[str, float],
                             override: set, patterns: Dict[str, Any], now: float,
                             ) -> Tuple[Dict[str, float], set, Dict[str, Any], bool]:
        """What of a cmd's toy cards lands, and whether it landed within
        the budget: (levels, override toys, auto modes, counted).

        A cmd is a state, so only a change costs anything: cards that differ
        from what last landed take one from `peer`'s budget
        (inbound_rate.CARDS -- far above what OGP or the web remote sends
        while a slider is dragged). Past it the change is held back, but its
        letting go lands at once, because letting go is never limited: a toy
        stopped (its level gone to 0), an auto mode ended, Override off. That
        is counted too (the budget may owe it), so stopping things one at a
        time can't be used to change the cards faster. What lands past the
        budget is never a real change for Sync with others (`counted`
        False, `_sync_version`). The rest arrives with the sender's next
        cmd that finds the budget again -- a cmd that drives repeats every
        remote_session.SEND_S. Said in the log at most every few seconds.

        Me is never budgeted: its loop on this PC isn't throttled like the
        link, and nothing from outside reaches it but the avatar menu (whose
        YOLO senders hold to inbound_rate.PARAMS)."""
        if peer == ME:
            return levels, override, patterns, True
        had_levels = old.levels if old is not None else {}
        had_ovr = old.ovr if old is not None else frozenset()
        had_pat = {k: v["p"] for k, v in old.pat.items()} if old is not None else {}
        if levels == had_levels and override == had_ovr and patterns == had_pat:
            return levels, override, patterns, True          # a top-up: free
        budget = self._card_budget
        if budget.take(peer, now):
            return levels, override, patterns, True
        let_go = ({k: v for k, v in had_levels.items() if k in levels},
                  set(had_ovr & override),
                  {k: p for k, p in had_pat.items() if k in patterns})
        if let_go != (levels, override, patterns):
            self._too_fast(peer, "toy changes", budget, kind=TOYS)
        if let_go != (had_levels, set(had_ovr), had_pat):
            budget.spend(peer, now)
        return let_go[0], let_go[1], let_go[2], False

    def _take_holds(self, peer: str, holds: Dict[int, Any], now: float) -> None:
        """A cmd's holds, for the GUI tick (_pump_friend_holds)."""
        if holds or peer in self._friend_holds:
            with self._friend_lock:
                self._friend_holds = {**self._friend_holds, peer: (holds, now)}

    def _queue_strength(self, peer: str, value: float) -> None:
        """A friend's strength change for the GUI thread. Only the newest
        per friend waits there: however fast new ones come, the queue holds
        one (OGP's own slider sends at most one a cmd; a flood would
        otherwise fill the GUI's queue and redraw the page for each)."""
        with self._str_lock:
            fresh = peer not in self._friend_str_pending
            self._friend_str_pending[peer] = value
        if fresh:
            self.thread_queue.put(("friends", ("strength", (peer, value))))

    def _not_here_cmd(self, peer: str, msg: Dict[str, Any], toys: bool = True) -> None:
        """A cmd from someone not in your instance: nothing of it lands --
        said in the log while it would have done something (of what their
        switches let them do: `toys` off, only their holds). A strength
        change they made meanwhile is used up, as under Pause: it never
        lands later, when they're back."""
        levels, strength = proto.read_cmd(msg)
        _override, patterns, holds = proto.read_cmd_more(msg)
        moved = strength is not None and strength[0] > self._friend_str_seq.get(peer, 0)
        if moved:
            self._friend_str_seq[peer] = strength[0]
        if toys and (levels or patterns or moved):
            self._not_here_refused(peer, TOYS, "drive your toys")
        if holds:
            self._not_here_refused(peer, SHOCK, "hold your shockers")

    def _first_time(self, peer: str, key: str) -> bool:
        """A shock's or a Stop's id seen for the first time from `peer` --
        its copies are not. Each sender's ids are kept apart, so one
        sending many can't push another's out of the list (and get a
        friend's copies taken for new shocks)."""
        seen = self._seen_shocks.get(peer)
        if seen is None:
            seen = self._seen_shocks.setdefault(peer, deque(maxlen=_SEEN_PER_PEER))
        if key in seen:
            return False
        seen.append(key)
        return True

    def _too_fast(self, peer: str, what: str, budget, kind: str = SHOCK) -> None:
        """`peer` sent `what` faster than OGP's own panels ever do
        (inbound_rate): refused at the door, said at most every few
        seconds."""
        if budget.say(peer, time.monotonic()):
            held = "sent faster than OGP sends"
            self._friends_note(f"{{who}} sent {what} too fast - held back", who=peer,
                               kind=kind, op="fast", dir=IN, held=held)

    def _friend_shock_in(self, peer: str, msg: Dict[str, Any]) -> None:
        shock = proto.read_shock(msg)
        if shock is None or not self._first_time(peer, shock["id"]):
            return
        op = shock["op"]
        if not self._shock_budget.take(peer, time.monotonic()):
            self._too_fast(peer, f"{op}s", self._shock_budget)
            return
        nick = self._friend_nick(peer)
        eng = getattr(self, "pishock_engine", None)
        why = self._shock_blocked(peer, eng)
        if why:
            self._friends_note(f"{{who}} tried to {op} you - held back: {why}",
                               key=("held", peer, op, why), who=peer, name=nick, kind=SHOCK,
                               op=op, dir=IN, held=why)
            return
        asked_warn, asked_wms = shock["warn"], int(shock["wms"])
        if shock["warn"]:
            # A warning as OGP's own panels send one, whatever came: a
            # vibration (a beep only where Vibrate is switched off, below)
            # of at least WARN_MIN_MS -- PiShock's shortest warning,
            # Small, starts there. A shorter one is stretched to it.
            shock = dict(shock, warn="vibrate",
                         wms=max(int(shock["wms"]), proto.WARN_MIN_MS))
        shockers = eng.shockers()
        targets = [shockers[slot] for slot in shock["slots"] if slot < len(shockers)]
        # Strength and length are parts of each shocker's OWN caps (as their
        # group gets them: friends' own while limits are separate): what a
        # friend asked for means the same on every shocker they picked.
        group = shock_group(peer, coming_through())
        fires = []
        for s in targets:
            lim = eng.limits_for(s["id"], group=group)
            level, ms = proto.shock_values(shock["int"], shock["len"],
                                           _op_cap(op, lim), lim["max_pulse_ms"])
            fires.append((s["id"], level, ms))
        if shock["warn"]:
            # PiShock's warning: the shocker vibrates for the warning's
            # length (a hold, so it may run past your longest pulse; your
            # max continuous time still holds), then the operation goes.
            # The GUI tick runs it (_pump_friend_holds). Vibrate switched off
            # on a shocker: it beeps instead; neither on: no warning can
            # play there, so its shock doesn't come either.
            until = time.monotonic() + shock["wms"] / 1000.0
            warned, unwarned = [], []
            with self._friend_lock:
                for slot in shock["slots"]:
                    if slot < len(shockers):
                        sid = shockers[slot]["id"]
                        wop = _warning_op(eng, sid, shock["warn"])
                        if wop is None:
                            unwarned.append(shocker_label(shockers[slot]))
                            continue
                        lim = eng.limits_for(sid, group=group)
                        wlevel = (proto.shock_values(shock["wi"], 0.0, _op_cap(wop, lim),
                                                     lim["max_pulse_ms"])[0]
                                  if wop == "vibrate" else 1)
                        fire = next(f for f in fires if f[0] == sid)
                        self._warnings[(peer, slot)] = {
                            "sid": sid, "op": wop, "level": wlevel,
                            "until": until, "ms": int(shock["wms"]), "fire": (op, [fire]),
                            "via": coming_through()}    # Me's menu / Party Mode
                        warned.append(shocker_label(shockers[slot]))
            if unwarned:
                held = "can't warn first, vibrate and beep are switched off there"
                self._friends_note(f"{{who}} tried to {op} you - held back on "
                                   f"{', '.join(unwarned)}: {held}", who=peer, name=nick,
                                   kind=SHOCK, op=op, dir=IN, on=unwarned, held=held)
            if warned:
                wms = int(shock["wms"])
                said, said_ms = asked_warn, asked_wms
                fixed = ("a vibration, OGP's shortest warning" if asked_warn != "vibrate"
                         and wms > asked_wms else "OGP's shortest warning" if wms > asked_wms
                         else "a vibration instead: OGP's warnings vibrate"
                         if asked_warn != "vibrate" else "")
                self._friends_note(f"{{who}}: {said} warning {said_ms / 1000:.1f} s, "
                                   f"then {op} - on {', '.join(warned)}", who=peer, name=nick,
                                   kind=SHOCK, op="warning", dir=IN, ms=wms, on=warned,
                                   asked=op, asked_ms=said_ms if said_ms != wms else None,
                                   fixed=fixed)
            return
        self._friend_shock_fire(peer, op, fires)

    def _friend_shock_fire(self, peer: str, op: str, fires: List[Tuple[int, int, int]]) -> None:
        """Send one friend's operation -- right away, or after its warning
        (everything is checked again at the moment it goes). `fires` is
        (shocker id, level, ms) for each shocker it goes to."""
        nick = self._friend_nick(peer)
        eng = getattr(self, "pishock_engine", None)
        why = self._shock_blocked(peer, eng)
        if why:
            self._friends_note(f"{{who}} tried to {op} you - held back: {why}",
                               key=("held", peer, op, why), who=peer, name=nick, kind=SHOCK,
                               op=op, dir=IN, held=why)
            return
        by_id = {s["id"]: s for s in eng.shockers()}
        group = shock_group(peer, coming_through())
        fired, switched = [], []     # fired: (name, level asked, ms asked, what went out)
        for i, asked_level, asked_ms in fires:
            if i not in by_id:
                continue
            if not eng.op_allowed(i, op):
                switched.append(shocker_label(by_id[i]))
                continue
            # the shocker's caps as they are now (they may have changed
            # during a warning), as their group gets them
            lim = eng.limits_for(i, group=group)
            level, ms = min(asked_level, _op_cap(op, lim)), min(asked_ms, lim["max_pulse_ms"])
            # A stronger pulse may take over a running one -- but a chain of
            # them never runs past the shocker's longest pulse (the engine
            # minds the rests, after a pulse and after the longest hold, for
            # everyone).
            sent = went_out(eng.pulse(i, op, level, ms, run_cap_ms=lim["max_pulse_ms"],
                                      group=group),
                            op, level, ms)
            if sent is not None:
                fired.append((shocker_label(by_id[i]), asked_level, asked_ms, sent))
        if switched:
            held = f"{op} is switched off there"
            self._friends_note(f"{{who}} tried to {op} you - held back on {', '.join(switched)}: "
                               f"{held}", who=peer, name=nick, kind=SHOCK, op=op, dir=IN,
                               on=switched, held=held)
        if not fired:
            if not switched:
                self._friends_note(f"{{who}} tried to {op} you - held back (stopped, or still "
                                   "resting)", key=("held", peer, op, "resting"), who=peer,
                                   name=nick, kind=SHOCK, op=op, dir=IN,
                                   held="stopped, or still resting")
            return
        armed = bool(eng.is_armed)
        # The line says what they asked; the record keeps what went out
        # (Statistics count that) and why it differs.
        asked_level = max(f[1] for f in fired)
        asked_ms = max(f[2] for f in fired)
        level = max(f[3].intensity for f in fired)
        ms = max(f[3].duration_ms for f in fired)
        what = op_text(op, asked_level, armed)
        names = [f[0] for f in fired]
        went = "vibrate" if op == "shock" and not armed else op
        fixed = _pulse_fixed(op, went, fired, level == asked_level and ms == asked_ms)
        beep = op == "beep"
        self._friends_note(f"{{who}}: {what} · {asked_ms / 1000:.1f} s on {', '.join(names)}",
                           who=peer, name=nick, kind=SHOCK, op=went, dir=IN,
                           level=None if beep else level, ms=ms, on=names,
                           asked=op if went != op else "",
                           asked_level=None if beep or asked_level == level else asked_level,
                           asked_ms=None if asked_ms == ms else asked_ms, fixed=fixed)

    def _shockers_shared(self) -> bool:
        """Your shockers are there for friends: the Shockers feature on and
        both of Home's switches -- On and Share with friends. Any of them
        off and no friend's shock gets through, and friends don't see your
        shockers at all (their panel drops the section)."""
        if not self.get_feature_enabled("feature_pishock"):
            return False
        s = getattr(self, "pishock_settings", None)
        return s is None or (s.get_friends_may_use() and s.get_enabled())

    def _shock_blocked(self, peer: str, eng) -> Optional[str]:
        perms = self._friend_perms.get(peer)
        if not perms or not perms[1]:
            return "shocks from them are switched off"
        if not self._shockers_shared():
            s = getattr(self, "pishock_settings", None)
            return ("your shockers are switched off" if s is not None and not s.get_enabled()
                    else "your shockers aren't shared with friends")
        if self.friends_settings.get_paused():
            return "friends are paused"
        if peer in self._not_here:
            return self._not_here_why(peer)
        if self.is_output_off():
            reasons = getattr(self, "get_away_reasons", None)
            held = reasons() if callable(reasons) else ()
            switch = getattr(self, "is_off_switch_on", None)
            if held and not (callable(switch) and switch()):
                return f"everything is off ({', '.join(held)})"
            return "Off is on"
        if not self.get_feature_enabled("feature_pishock") or eng is None:
            return "the Shockers page is off"
        if not eng.is_connected:
            return "no shocker hub connected"
        return None

    def _friend_stop_in(self, peer: str, msg: Dict[str, Any]) -> None:
        """A friend's Stop: those shockers end now, their warned shocks and
        holds there are dropped. Anyone linked may stop -- it only ever
        makes things quieter."""
        stop = proto.read_stop(msg)
        if stop is None or not self._first_time(peer, "stp" + stop["id"]):
            return
        slots = set(stop["slots"])
        with self._friend_lock:
            for slot in slots:
                self._warnings.pop((peer, slot), None)     # its shock never comes
                self._holding.pop((peer, slot), None)
            holds = self._friend_holds.get(peer)
            if holds:
                self._friend_holds = {**self._friend_holds,
                                      peer: ({k: v for k, v in holds[0].items() if k not in slots},
                                             holds[1])}
        eng = getattr(self, "pishock_engine", None)
        if eng is None or not getattr(eng, "is_connected", False):
            return
        if not self._stop_budget.take(peer, time.monotonic()):
            # their own warnings and holds are gone (above); the hub heard a
            # Stop of theirs moments ago -- a flood never keeps its line busy
            self._too_fast(peer, "Stops", self._stop_budget)
            return
        shockers = eng.shockers()
        names = []
        for slot in sorted(slots):
            if slot < len(shockers):
                eng.end(shockers[slot]["id"])
                names.append(shocker_label(shockers[slot]))
        if names:
            self._friends_note(f"{{who}} stopped {', '.join(names)}", key=("stp-in", peer),
                               who=peer, kind=SHOCK, op="stop", dir=IN, on=names)

    # ------------------------------------------------------------------
    # Holds and warnings -- the GUI tick
    # ------------------------------------------------------------------

    def _pump_friend_holds(self, now: float) -> None:
        """GUI tick: keep every friend's held shocker going (the engine
        tops a hold up itself, within your max hold and rest), and let go
        of the ones they released -- or that went quiet. Each friend holds
        as a source of their own: the engine plays the strongest of them,
        your rules' included, and one letting go never cuts another."""
        eng = getattr(self, "pishock_engine", None)
        want: Dict[tuple, tuple] = {}
        for peer, (holds, t) in list(self._friend_holds.items()):
            if now - t > proto.DRIVE_STALE_S:
                continue
            for slot, hold in holds.items():
                want[(peer, slot)] = hold
        if eng is None:
            return
        self._pump_warnings(eng, now)
        shockers = eng.shockers() if getattr(eng, "is_connected", False) else []
        with self._friend_lock:
            gone = [(key, self._holding.pop(key)) for key in list(self._holding) if key not in want]
        for key in list(self._hold_refused):
            if key not in want:
                del self._hold_refused[key]
        by_id = {s["id"]: s for s in shockers}
        for key, sid in gone:
            eng.release(sid, source=hold_source(*key))
            name = shocker_label(by_id[sid]) if sid in by_id else ""
            self._friends_note("{who} let go" + (f" of {name}" if name else ""),
                               key=("let-go", key), who=key[0], kind=SHOCK,
                               op="let-go", dir=IN, on=(name,) if name else ())
        for (peer, slot), (op, v) in want.items():
            src = hold_source(peer, slot)
            # an op switched off on that shocker is refused -- said once in
            # the log, not every tick
            why = None
            if slot < len(shockers) and not self._shock_blocked(peer, eng):
                sid = shockers[slot]["id"]
                if not eng.op_allowed(sid, op):
                    why = f"{op} is switched off there"
            else:
                why = ""                  # blocked as a whole: said where it is set
            if why is not None:
                with self._friend_lock:
                    held = self._holding.pop((peer, slot), None)
                if held is not None:
                    eng.release(held, source=src)
                if why and self._hold_refused.get((peer, slot)) != why:
                    self._hold_refused[(peer, slot)] = why
                    name = shocker_label(shockers[slot])
                    self._friends_note(f"{{who}} tried to hold {op} on {name} - held back: "
                                       f"{why}", who=peer, kind=SHOCK, op="hold", dir=IN,
                                       on=(name,), held=why, asked=op)
                continue
            self._hold_refused.pop((peer, slot), None)
            lim = eng.limits_for(sid, group=GROUP_FRIENDS)
            level = (proto.shock_values(v, 0.0, _op_cap(op, lim), lim["max_pulse_ms"])[0]
                     if op != "beep" else 1)
            with self._friend_lock:
                was = self._holding.get((peer, slot))
                self._holding[(peer, slot)] = sid
            if was is not None and was != sid:
                eng.release(was, source=src)   # the slot is another shocker now
            if was is None:
                name = shocker_label(shockers[slot])
                # `asked` is what the hold plays: an unarmed shock holds as
                # the vibrate the engine turns it into, under its ceiling
                armed = bool(eng.is_armed)
                plays = "vibrate" if op == "shock" and not armed else op
                played = level
                if plays != "beep":
                    played = min(level, int(lim["max_intensity"] if plays == "shock"
                                            else lim.get("max_vibrate", lim["max_intensity"])))
                self._friends_note(f"{{who}} is holding {op_text(op, level, armed)} on {name}",
                                   key=("hold", (peer, slot)), who=peer, kind=SHOCK,
                                   op="hold", dir=IN, level=played, on=(name,), asked=plays,
                                   asked_level=level if played != level else None,
                                   fixed=f"your {plays} limit" if played != level else "")
            eng.hold(sid, op, level, source=src, group=GROUP_FRIENDS)

    def _pump_warnings(self, eng, now: float) -> None:
        """A running warning vibrates until its time is up; then the
        operation it warned of goes (checked again right then). Each
        warning holds as a source of its own, so its end lets go of only
        itself -- not a hold on the same shocker.

        A warning plays in full before its shock: while a pulse runs on that
        shocker, and its rest after, no hold plays there (the engine), so
        the warning starts over once both are over. One that comes while
        the shocker rests after its longest hold is held back with its
        shock, as a shock without one would be."""
        with self._friend_lock:
            sids = {k: (w["sid"], shock_group(k[0], w.get("via", "")))
                    for k, w in self._warnings.items()}
        if not sids:
            return
        # asked outside the lock: the engine takes its own
        busy = {k: (eng.hold_free_in(sid, g), eng.is_resting(sid, g))
                for k, (sid, g) in sids.items()}
        with self._friend_lock:
            for k, w in self._warnings.items():
                wait = busy.get(k, (0.0, False))[0]
                if wait > 0.0:
                    w["until"] = max(w["until"], now + wait + w.get("ms", 0) / 1000.0)
            due = [(k, w) for k, w in self._warnings.items() if now >= w["until"]]
            running = [(k, w) for k, w in self._warnings.items() if now < w["until"]]
            resting = [(k, w) for k, w in running if busy.get(k, (0.0, False))[1]]
            for k, _w in due + resting:
                del self._warnings[k]
        for (peer, slot), w in resting:
            eng.release(w["sid"], source=warning_source(peer, slot))
            op = w["fire"][0]
            held = "still resting after the longest hold"
            self._friends_note(f"{{who}} tried to {op} you - held back: {held}",
                               key=("held", peer, op, "rest"), who=peer, kind=SHOCK, op=op,
                               dir=IN, held=held)
        resting_keys = {k for k, _w in resting}
        for (peer, slot), w in running:
            if (peer, slot) in resting_keys:
                continue
            if not self._shock_blocked(peer, eng):
                eng.hold(w["sid"], w["op"], w["level"], source=warning_source(peer, slot),
                         group=shock_group(peer, w.get("via", "")))
            else:
                eng.release(w["sid"], source=warning_source(peer, slot))
        for (peer, slot), w in due:
            eng.release(w["sid"], source=warning_source(peer, slot))
            with came_through(w.get("via", "")):
                self._friend_shock_fire(peer, *w["fire"])

    def _drop_shocks(self, peer: str) -> None:
        """A friend is gone: their warned shocks are cancelled and their
        holds let go."""
        eng = getattr(self, "pishock_engine", None)
        with self._friend_lock:
            held = [(self._warnings.pop(k)["sid"], warning_source(*k))
                    for k in list(self._warnings) if k[0] == peer]
            held += [(self._holding.pop(k), hold_source(*k))
                     for k in list(self._holding) if k[0] == peer]
            self._friend_holds = {k: v for k, v in self._friend_holds.items() if k != peer}
        if eng is not None:
            for sid, src in held:
                eng.release(sid, source=src)


def shock_group(peer: str, via: str) -> str:
    """Whose timing limits a shock counts against while they are separate
    (Blise's call, 2026-11-17): your own avatar menu's -- Me, through it --
    is your avatar's; every friend, Me on the page and the web remote are
    friends'."""
    return GROUP_AVATAR if peer == ME and via == VIA_MENU else GROUP_FRIENDS


def hold_source(peer: str, slot: int) -> tuple:
    """How a friend's hold on one of your shockers is named to the engine:
    each friend (Me, a browser on the web remote) holds apart from the
    others and from your rules."""
    return ("friend", peer, slot)


def warning_source(peer: str, slot: int) -> tuple:
    """A friend's warning before their shock: a hold of its own, apart from
    their hold on the same shocker."""
    return ("warning", peer, slot)


def _pulse_fixed(op: str, went: str, fired: List[tuple], same: bool) -> str:
    """Why a friend's pulse went out with less than they asked, for the
    log's muted line: `fired` is (name, level asked, ms asked, Sent) per
    shocker. "" when it went as asked. `same`: the strongest and longest
    went as asked -- only some shockers got less, so they are named.
    The limits are always your shockers' own, whoever sent it."""
    lowered = [f for f in fired if op != "beep" and f[3].intensity < f[1]]
    cut = [f for f in fired if f[3].duration_ms < f[2]]
    why = []
    if lowered:
        # an unarmed shock is a vibrate, under your vibrate ceiling
        why.append(f"your {went} limit")
    if cut:
        why.append("your longest pulse")
    if not why:
        return ""
    if same:
        names = list(dict.fromkeys(f[0] for f in lowered + cut))
        return f"less on {', '.join(names)}: {', '.join(why)}"
    return ", ".join(why)


def _warning_op(eng, shocker_id: int, wanted: str) -> Optional[str]:
    """The op a warning plays on this shocker: the one asked for, the other
    of vibrate / beep when that one is switched off on its card, None when
    both are."""
    other = "beep" if wanted == "vibrate" else "vibrate"
    for op in (wanted, other):
        if eng.op_allowed(shocker_id, op):
            return op
    return None


def _op_cap(op: str, lim: Dict[str, Any]) -> int:
    """The receiver's own ceiling for an op: shocks their shock cap,
    vibrates their vibrate cap."""
    if op == "shock":
        return int(lim["max_intensity"])
    return int(lim.get("max_vibrate", lim["max_intensity"]))


# --- those who sync share one panel ---------------------------------------------

def _cards(d: Drive) -> Tuple[Dict[str, float], frozenset, Dict[str, Any]]:
    """What one who syncs has on their toy cards, as a cmd reads."""
    return d.levels, d.ovr, {k: v["p"] for k, v in d.pat.items()}


def _panel_seq(syncing: List[Drive], mine: Drive) -> int:
    """The version the shared panel says to `mine`'s sender: the highest
    any of them sent -- what their OGP and browser take as theirs, so their
    next change is newer than every one so far -- but never far past what
    this OGP vouches for (a huge number never reaches the honest panels),
    and never below their own (or their panel would stop following). One
    that says no version counts as far as it is vouched for."""
    return max([min(d.syn if d.syn is not None else proto.MAX_SEQ, d.ver + SYNC_SAY_AHEAD)
                for d in syncing] + [mine.syn])


def _sync_newest(drive: Mapping[str, Drive]) -> Optional[Tuple[str, Drive]]:
    """The newest change among everyone driving: the highest version this
    OGP vouches for (`_sync_version`), the first to send it on a tie, the
    peer id when they came at the very same instant."""
    best = None
    for peer, d in drive.items():
        key = (d.ver, -d.since, peer)
        if best is None or key > best[0]:
            best = (key, peer, d)
    return (best[1], best[2]) if best is not None else None


def _sync_playing(drive: Mapping[str, Drive], now: float) -> Optional[Drive]:
    """What the shared panel plays: the newest change -- nothing when that
    is "off". When the one who made it stopped sending (their updates go
    stale like anyone's), the newest of the others who sync still do."""
    newest = _sync_newest(drive)
    if newest is None or not newest[1].drives():
        return None
    if now - newest[1].t <= proto.DRIVE_STALE_S:
        return newest[1]
    live = [(d.ver, -d.since, peer, d) for peer, d in drive.items()
            if now - d.t <= proto.DRIVE_STALE_S and d.drives()]
    return max(live, key=lambda x: x[:3])[3] if live else None
