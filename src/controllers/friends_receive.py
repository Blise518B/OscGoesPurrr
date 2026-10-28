"""Friends, part 4: what friends do to you. Their levels and auto modes
reach the router through `get_friend_drive_mode` (the GUI thread, every
routing tick); their shocks, holds, warnings and Stops go through your
PiShockEngine, so your caps, your rest after each pulse and your arming
always hold -- a friend can never widen them.

Threads: cmds, shocks and Stops arrive on the link's thread; holds and
warnings run on the GUI tick (`_pump_friend_holds`). `_friend_lock`
guards `_holding`, `_warnings` and `_friend_holds`, which both change.

Mixed into FriendsFacade; see friends_facade.py for what the host has.
"""

import time
from typing import Any, Dict, List, Mapping, Optional, Tuple

import friend_patterns
import remote_protocol as proto
from controllers.friends_common import ME, SELF, Drive, op_text, shocker_label


class FriendsReceiveMixin:
    """Mixin: what friends do to you."""

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
        own = getattr(self, "_self_drive", None)
        if not drive and not own:
            return 0.0, False
        now = time.monotonic()
        best, override = 0.0, False
        toy = str(device_name)[:proto.TOY_NAME_MAX]
        entries = []
        if not self.friends_settings.get_paused():
            # on their own: each plays; those who sync: one panel, played once
            entries = [d for d in drive.values()
                       if d.syn is None and now - d.t <= proto.DRIVE_STALE_S]
            shared = _sync_playing(drive, now)
            if shared is not None:
                entries.append(shared)
        if own:
            entries.append(own)                         # Both of us, on you: never stale
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
        own = getattr(self, "_self_drive", None)
        if own and own.pat:
            return True
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
        now (``oth``) and, while they and someone else sync, the shared
        panel (``pnl``). The link's thread. Light on the relays: nothing
        while nobody else drives (one empty ``oth`` when that ends), no
        panel for a friend who syncs alone. A browser on the web remote
        gets the count only: it never hears your friends' names."""
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
        syncing = sum(1 for d in drive.values() if d.syn is not None)
        newest = _sync_newest(drive)
        if mine is not None and mine.syn is not None and syncing >= 2 and newest is not None:
            d = newest[1]
            out["pnl"] = proto.make_panel(d.syn, d.levels, d.ovr,
                                          {k: v["p"] for k, v in d.pat.items()})
        return out

    def _drop_drive(self, peer: str) -> None:
        if peer in self._friend_drive:
            self._friend_drive = {k: v for k, v in self._friend_drive.items() if k != peer}
            self._needs_recalculation = True

    # ------------------------------------------------------------------
    # Their cmds, shocks and Stops -- the link's thread
    # ------------------------------------------------------------------

    def _friend_cmd_in(self, peer: str, msg: Dict[str, Any]) -> None:
        perms = self._friend_perms.get(peer)
        if not perms or not perms[0]:
            return
        levels, strength = proto.read_cmd(msg)
        override, patterns, holds = proto.read_cmd_more(msg)
        syn = proto.read_syn(msg)
        now = time.monotonic()
        old = self._friend_drive.get(peer)
        old_pat = old.pat if old is not None else {}
        # One who syncs plays the shared panel's waves where they stand, so
        # the panel passing from one friend to another doesn't jump a cycle.
        shared = _sync_newest(self._friend_drive) if syn is not None else None
        base: Mapping[str, Dict[str, Any]] = shared[1].pat if shared is not None else {}
        pat = {toy: friend_patterns.anchor(
                   p, base.get(toy) if toy in base and base[toy]["p"][0] == p[0]
                   else old_pat.get(toy), now)
               for toy, p in patterns.items()}
        since = old.since if old is not None and old.syn == syn else now
        self._friend_drive = {**self._friend_drive,
                              peer: Drive(levels, now, frozenset(override), pat, syn, since)}
        if (old is None or old.levels != levels or old.ovr != override or old.syn != syn
                or {k: v["p"] for k, v in old_pat.items()} != patterns):
            self._needs_recalculation = True
        if holds or peer in self._friend_holds:
            with self._friend_lock:
                self._friend_holds = {**self._friend_holds, peer: (holds, now)}
        if strength is not None and strength[0] > self._friend_str_seq.get(peer, 0):
            self._friend_str_seq[peer] = strength[0]
            self.thread_queue.put(("friends", ("strength", (peer, strength[1]))))

    def _friend_shock_in(self, peer: str, msg: Dict[str, Any]) -> None:
        shock = proto.read_shock(msg)
        if shock is None or (peer, shock["id"]) in self._seen_shocks:
            return
        self._seen_shocks.append((peer, shock["id"]))
        nick = self._friend_nick(peer)
        eng = getattr(self, "pishock_engine", None)
        why = self._shock_blocked(peer, eng)
        op = shock["op"]
        if why:
            self._friends_note(f"{nick} tried to {op} you - held back: {why}")
            return
        shockers = eng.shockers()
        targets = [shockers[slot] for slot in shock["slots"] if slot < len(shockers)]
        # Strength and length are parts of each shocker's OWN caps: what a
        # friend asked for means the same on every shocker they picked.
        fires = []
        for s in targets:
            lim = eng.limits_for(s["id"])
            level, ms = proto.shock_values(shock["int"], shock["len"],
                                           _op_cap(op, lim), lim["max_pulse_ms"])
            fires.append((s["id"], level, ms))
        if shock["warn"]:
            # PiShock's warning: the shocker vibrates for the warning's
            # length (a hold, so it may run past your longest pulse; your
            # max continuous time still holds), then the operation goes.
            # The GUI tick runs it (_pump_friend_holds).
            until = time.monotonic() + shock["wms"] / 1000.0
            with self._friend_lock:
                for slot in shock["slots"]:
                    if slot < len(shockers):
                        sid = shockers[slot]["id"]
                        lim = eng.limits_for(sid)
                        wlevel = (proto.shock_values(shock["wi"], 0.0,
                                                     _op_cap(shock["warn"], lim),
                                                     lim["max_pulse_ms"])[0]
                                  if shock["warn"] == "vibrate" else 1)
                        fire = next(f for f in fires if f[0] == sid)
                        self._warnings[(peer, slot)] = {
                            "sid": sid, "op": shock["warn"], "level": wlevel,
                            "until": until, "fire": (op, [fire])}
            self._friends_note(f"{nick}: {shock['warn']} warning {shock['wms'] / 1000:.1f} s, then "
                               f"{op} - on {', '.join(shocker_label(s) for s in targets)}")
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
            self._friends_note(f"{nick} tried to {op} you - held back: {why}")
            return
        by_id = {s["id"]: s for s in eng.shockers()}
        fired = [(shocker_label(by_id[i]), level, ms) for i, level, ms in fires
                 if i in by_id and eng.pulse(i, op, level, ms)]
        if not fired:
            self._friends_note(f"{nick} tried to {op} you - held back (stopped, or still resting)")
            return
        what = op_text(op, max(f[1] for f in fired), eng.is_armed)
        ms = max(f[2] for f in fired)
        self._friends_note(f"{nick}: {what} · {ms / 1000:.1f} s on {', '.join(f[0] for f in fired)}")

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
        if peer != SELF:                   # Both of us on you: your own say-so
            perms = self._friend_perms.get(peer)
            if not perms or not perms[1]:
                return "shocks from them are switched off"
            if not self._shockers_shared():
                s = getattr(self, "pishock_settings", None)
                return ("your shockers are switched off" if s is not None and not s.get_enabled()
                        else "your shockers aren't shared with friends")
            if self.friends_settings.get_paused():
                return "friends are paused"
        if self.is_output_off():
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
        if stop is None or (peer, "stp" + stop["id"]) in self._seen_shocks:
            return
        self._seen_shocks.append((peer, "stp" + stop["id"]))
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
        shockers = eng.shockers()
        names = []
        for slot in sorted(slots):
            if slot < len(shockers):
                eng.end(shockers[slot]["id"])
                names.append(shocker_label(shockers[slot]))
        if names:
            self._friends_note(f"{self._friend_nick(peer)} stopped {', '.join(names)}")

    # ------------------------------------------------------------------
    # Holds and warnings -- the GUI tick
    # ------------------------------------------------------------------

    def _pump_friend_holds(self, now: float) -> None:
        """GUI tick: keep every friend's held shocker going (the engine
        tops a hold up itself, within your max hold and rest), and let go
        of the ones they released -- or that went quiet."""
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
        for key, sid in gone:
            eng.release(sid)
            self._friends_note(f"{self._friend_nick(key[0])} let go", key=("let-go", key))
        for (peer, slot), (op, v) in want.items():
            if slot >= len(shockers):
                continue
            sid = shockers[slot]["id"]
            lim = eng.limits_for(sid)
            if self._shock_blocked(peer, eng):
                with self._friend_lock:
                    held = self._holding.pop((peer, slot), None)
                if held is not None:
                    eng.release(held)
                continue
            level = (proto.shock_values(v, 0.0, _op_cap(op, lim), lim["max_pulse_ms"])[0]
                     if op != "beep" else 1)
            with self._friend_lock:
                new = (peer, slot) not in self._holding
                self._holding[(peer, slot)] = sid
            if new:
                self._friends_note(f"{self._friend_nick(peer)} is holding {op} {level} on "
                                   f"{shocker_label(shockers[slot])}", key=("hold", (peer, slot)))
            eng.hold(sid, op, level)

    def _pump_warnings(self, eng, now: float) -> None:
        """A running warning vibrates until its time is up; then the
        operation it warned of goes (checked again right then)."""
        with self._friend_lock:
            due = [(k, w) for k, w in self._warnings.items() if now >= w["until"]]
            running = [(k, w) for k, w in self._warnings.items() if now < w["until"]]
            for k, _w in due:
                del self._warnings[k]
        for (peer, _slot), w in running:
            if not self._shock_blocked(peer, eng):
                eng.hold(w["sid"], w["op"], w["level"])
        for (peer, _slot), w in due:
            eng.release(w["sid"])
            self._friend_shock_fire(peer, *w["fire"])

    def _drop_shocks(self, peer: str) -> None:
        """A friend is gone: their warned shocks are cancelled and their
        holds let go."""
        eng = getattr(self, "pishock_engine", None)
        with self._friend_lock:
            sids = [self._warnings.pop(k)["sid"] for k in list(self._warnings) if k[0] == peer]
            sids += [self._holding.pop(k) for k in list(self._holding) if k[0] == peer]
            self._friend_holds = {k: v for k, v in self._friend_holds.items() if k != peer}
        if eng is not None:
            for sid in sids:
                eng.release(sid)


def _op_cap(op: str, lim: Dict[str, Any]) -> int:
    """The receiver's own ceiling for an op: shocks their shock cap,
    vibrates their vibrate cap."""
    if op == "shock":
        return int(lim["max_intensity"])
    return int(lim.get("max_vibrate", lim["max_intensity"]))


# --- those who sync share one panel ---------------------------------------------

def _sync_newest(drive: Mapping[str, Drive]) -> Optional[Tuple[str, Drive]]:
    """The newest change among the friends who sync: the highest version,
    the first to send it on a tie."""
    best = None
    for peer, d in drive.items():
        if d.syn is None:
            continue
        key = (d.syn, -d.since, peer)
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
    live = [(d.syn, -d.since, peer, d) for peer, d in drive.items()
            if d.syn is not None and now - d.t <= proto.DRIVE_STALE_S and d.drives()]
    return max(live, key=lambda x: x[:3])[3] if live else None
