"""Friends: only people in your instance.

With **Only friends in my instance** on (the Friends page, off by default) a
friend may drive you only while their linked VRChat account is in your
VRChat instance -- by your own log (friends_vrchat.py,
`vrchat_log.here_ids`), with VRChat running. Everyone else is *not here*
and refused like Pause:

* toys: their drive stops at once, new levels and strength are refused;
* shockers: their warnings are cancelled and holds let go, every shock is
  held back (`_shock_blocked` says why);
* Avatar Remote: every set is refused, held buttons let go
  (`ParamsFacade._params_blocked`) -- whatever else sets your avatar for a
  friend goes through the same check.

That holds if they leave mid-session too, and every refusal is logged.

Who counts as not here: a friend with no VRChat account linked (their row
points to linking them), and everyone while the log isn't read or VRChat
isn't running. **Me** is exempt. A friend's **Allow from anywhere** exempts
them. A browser on the **web remote** can't be in an instance, so it is
blocked unless the Web remote panel's **Allow the web remote anyway** is on.

Your own log alone decides (Blise's call, 2026-11-14): nothing about your
instance goes over the link and your location never leaves your PC. A
refused friend or browser is sent what Pause sends (``pause``) plus one
bit, ``nh`` -- "you're not in my instance" -- so their panel can say why in
words that never name your friends or your location.

Switching it on switches on "Read VRChat's log", which it needs. Switching
the log off while it's on leaves it on: nobody can be seen in your instance
then, so everyone but Me and the friends allowed from anywhere is not here
-- a switch about reading a file never opens you up to everyone as a side
effect.

Low latency: nothing per packet beyond a set lookup. `_not_here` is a
frozenset swapped whole -- on the GUI thread whenever what it stands on
changes (the friends tick looks every _TICK_MS: the log's snapshot, VRChat
up or down; and right away for a switch, a link, a contact), and under
`_web_lock` by the link's thread when a browser joins. The receive path
only reads it.

Mixed into FriendsFacade; see friends_facade.py for what the host has.
"""

import time
from typing import Dict

from controllers.friends_common import ME
from event_log import IN, PARAMS, SETTINGS, SHOCK, TOYS
from vrchat_log import here_ids

# A refused friend who keeps sending is told in the log once per this, per
# thing they try -- their levels come several times a second.
TELL_AGAIN_S = 10.0


class FriendsInstanceMixin:
    """Mixin of FriendsFacade: only friends in your instance."""

    def _friends_instance_init(self) -> None:
        # who is refused for not being in your instance (link thread reads)
        self._not_here: frozenset = frozenset()
        # (peer, what they tried) -> when a refusal was last said in the log
        self._not_here_told: Dict[tuple, float] = {}

    # ------------------------------------------------------------------
    # The switches
    # ------------------------------------------------------------------

    def get_friends_instance_only(self) -> bool:
        return self.friends_settings.get_instance_only()

    def set_friends_instance_only(self, on: bool) -> None:
        """Only friends in your VRChat instance may drive you. On switches
        on reading VRChat's log too: it can't work without it."""
        on = bool(on)
        if on == self.get_friends_instance_only():
            return
        self.friends_settings.set_instance_only(on)
        if on and not self.get_friends_vrc_log():
            self.set_friends_vrc_log(True)
        self._friends_note("Only friends in your VRChat instance may drive you now" if on
                           else "Friends may drive you from anywhere again", kind=SETTINGS,
                           op="instance-only" if on else "anywhere")
        self._instance_refresh()

    def set_friend_anywhere(self, peer: str, on: bool) -> None:
        """A friend's "Allow from anywhere": they may drive you while only
        friends in your instance may, wherever they are."""
        if peer == ME or self._demo_of("friend", peer) is not None:
            return
        f = self.friends_settings.get_friend(peer)
        if f is None or bool(f.get("anywhere")) == bool(on):
            return
        self.friends_settings.set_anywhere(peer, bool(on))
        self._friends_note("{who} may drive you from anywhere" if on
                           else "{who} may drive you only from your VRChat instance",
                           who=peer, kind=SETTINGS, op="allow" if on else "deny")
        self._instance_refresh()

    def set_friends_web_anyway(self, on: bool) -> None:
        """"Allow the web remote anyway" while only friends in your instance
        may drive you: a browser can't be in one."""
        on = bool(on)
        if on == bool(self.friends_settings.get_web().get("anyway")):
            return
        self.friends_settings.set_web_anyway(on)
        self._friends_note("Your web remote may drive you while only friends in your "
                           "instance may" if on else
                           "Your web remote is blocked while only friends in your instance "
                           "may drive you", kind=SETTINGS, op="allow" if on else "deny")
        self._instance_refresh()
        self._friends_refresh_ui()

    # ------------------------------------------------------------------
    # Who is not here
    # ------------------------------------------------------------------

    def friend_not_here(self, peer: str) -> bool:
        """Refused right now for not being in your instance (any thread)."""
        return peer in self._not_here

    def _web_not_here(self) -> bool:
        """A browser on the web remote is refused right now."""
        return (self.friends_settings.get_instance_only()
                and not self.friends_settings.get_web().get("anyway"))

    def _instance_compute(self) -> frozenset:
        """Who is not here, from scratch. Call with `_web_lock` held."""
        s = self.friends_settings
        if not s.get_instance_only():
            return frozenset()
        here = here_ids(self._friends_vrc_snapshot(), self._vrchat_up())
        out = {f["id"] for f in s.get_friends()
               if not f.get("anywhere") and (not f.get("vrc") or f["vrc"].lower() not in here)}
        if not s.get_web().get("anyway"):
            out.update(self._web_guests)
        return frozenset(out)

    def _instance_refresh(self) -> None:
        """GUI thread: who is not here now -- and whatever someone who just
        became so had going stops (drive, warnings, holds, held buttons)."""
        with self._web_lock:
            new = self._instance_compute()
            old = self._not_here
            self._not_here = new
        if new != old:
            back = old - new
            if back:
                self._not_here_told = {k: v for k, v in self._not_here_told.items()
                                       if k[0] not in back}
            for peer in new - old:
                self._instance_stop(peer)
        # a level that raced the swap on the link's thread: gone by the next tick
        for peer in new.intersection(self._friend_drive):
            self._drop_drive(peer)
        if self._friend_holds:
            for peer in new.intersection(self._friend_holds):
                self._drop_shocks(peer)

    def _instance_stop(self, peer: str) -> None:
        """`peer` is not here any more: what they had going stops, and the
        log says what (only what they had going -- VRChat closing doesn't
        list every friend you have)."""
        now = time.monotonic()
        toys = self._is_driving(peer, now)
        with self._friend_lock:
            shocks = (any(k[0] == peer for k in self._holding)
                      or any(k[0] == peer for k in self._warnings)
                      or bool((self._friend_holds.get(peer) or ({},))[0]))
        # their held avatar buttons (ParamsFacade; no new press gets past
        # _params_blocked once they're in _not_here)
        held = getattr(self, "_params_held", None) or {}
        buttons = bool(held.get(peer))
        self._drop_drive(peer)
        self._drop_shocks(peer)
        if buttons:
            self._params_release(peer)
        why = self._not_here_why(peer)
        for going, kind, what in ((toys, TOYS, "their drive on your toys stopped"),
                                  (shocks, SHOCK, "your shockers let go"),
                                  (buttons, PARAMS, "your avatar's buttons let go")):
            if going:
                self._friends_note(f"{{who}}: {what} - {why}", who=peer, kind=kind,
                                   op="not-here", dir=IN, held=why)

    def _not_here_why(self, peer: str) -> str:
        """Why `peer` is refused, for the log (yours alone)."""
        if peer in self._web_guests:
            return "the web remote can't be in your VRChat instance"
        f = self.friends_settings.get_friend(peer) or {}
        if not f.get("vrc"):
            return "not in your VRChat instance (no VRChat account linked)"
        return "not in your VRChat instance"

    def _not_here_refused(self, peer: str, kind: str, what: str) -> bool:
        """True when `peer` is refused for not being here -- said in the log
        (`what` they tried: "drive your toys") once per TELL_AGAIN_S for
        each thing they try. Any thread; free while they aren't refused."""
        if peer not in self._not_here:
            return False
        now = time.monotonic()
        key = (peer, what)
        last = self._not_here_told.get(key)
        if last is None or now - last >= TELL_AGAIN_S:
            self._not_here_told = {**self._not_here_told, key: now}
            why = self._not_here_why(peer)
            self._friends_note(f"{{who}} tried to {what} - held back: {why}", who=peer,
                               kind=kind, op="not-here", dir=IN, held=why)
        return True

    # ------------------------------------------------------------------
    # The page
    # ------------------------------------------------------------------

    def _friend_here_fields(self, peer: str) -> Dict[str, object]:
        """A friend's entry's part for the page: `anywhere` (their exception)
        and `not_here` (refused now)."""
        f = self.friends_settings.get_friend(peer) or {}
        return {"anywhere": bool(f.get("anywhere")), "not_here": peer in self._not_here}

    def _instance_entry(self) -> Dict[str, object]:
        """The page's part: the switch, the web remote's own, and whether a
        browser on it is refused now."""
        web = self.friends_settings.get_web()
        on = self.friends_settings.get_instance_only()
        return {"on": on, "web_anyway": bool(web.get("anyway")),
                "web_blocked": on and not web.get("anyway")}
