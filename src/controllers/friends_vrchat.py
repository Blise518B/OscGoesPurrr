"""Friends: each friend linked to their VRChat account -- yours alone.

An OGP friend is a link ID and the nickname they chose. This part lets you
say which VRChat account they are, so OGP can tell when they're in your
instance, and People statistics and the friend list call them by one name.

Where the account comes from:

* **who's in your instance** -- read from VRChat's log on this PC
  (`vrchat_log.LogWatcher`, the one People statistics uses), behind the
  Friends page's own switch, `FRIENDS_LOG_KEY`, off by default: tagging
  sessions and linking friends are separate yeses. The people there show as
  chips you drag onto a friend's row, and in the friend's picker;
* **your VRChat friends in VRCX** -- *Import from VRCX* reads VRCX's
  database read-only, on that click only (`vrcx_friends.py`); the list stays
  in memory for this run, never in a file.

A link is the account's `usr_` id (display names change) and the name it
had, in the friend's entry in friends settings. It is never sent anywhere:
not over the Friends link, not to the web remote, not to the friend.

"In your instance" (`friend_in_instance`, `vrchat_log.in_instance`) uses
only your own log, and only while VRChat is running (its OSC is up) -- a
log VRChat left behind still lists who was there. The "only friends in my
instance" option builds on it.

One name for one person: the VRChat name a linked friend shows is the one
People statistics files that account under (the first it saw), else the
name it had when you linked them -- and People statistics, meeting a
linked account for the first time, takes that name (`_friends_vrc_link_name`).

Me and the Web remote row have no VRChat account.

Assumes the host has `self.friends_settings`, `self.mode_manager`, and
from PeopleFacade `_vrc_log_sync` / `_vrc_log_snapshot` and (optionally)
`stats_people`; `osc_manager` says whether VRChat is running.
"""

from typing import Any, Dict, List, Optional

import vrcx_friends
from controllers.people_facade import FRIENDS_LOG_KEY
from vrchat_log import clean_display_name, clean_user_id, in_instance

# How many names a picker list shows at most (type to find the rest)
PICK_LIMIT = 40


class FriendsVrchatMixin:
    """Mixin of FriendsFacade: friends linked to VRChat accounts."""

    def _friends_vrchat_init(self) -> None:
        # the last Import from VRCX: {"state", "friends": [(uid, name)]}, this run only
        self._vrcx: Dict[str, Any] = {"state": "", "friends": []}

    # ------------------------------------------------------------------
    # The log and VRChat
    # ------------------------------------------------------------------

    def get_friends_vrc_log(self) -> bool:
        modes = getattr(self, "mode_manager", None)
        return bool(modes is not None and modes.app_settings.get(FRIENDS_LOG_KEY, False))

    def set_friends_vrc_log(self, on: bool) -> None:
        """The Friends page's switch: read who's in your instance from
        VRChat's log."""
        on = bool(on)
        if on == self.get_friends_vrc_log():
            return
        self.mode_manager.app_settings.set(FRIENDS_LOG_KEY, on)
        sync = getattr(self, "_vrc_log_sync", None)
        if sync is not None:
            sync()
        self._friends_note("You switched on reading who's in your VRChat instance from its log"
                           if on else "You switched off reading who's in your VRChat instance")
        # only friends in your instance stays on: with the log off nobody can
        # be seen there, so no friend is (friends_instance.py)
        self._instance_refresh()

    def _vrchat_up(self) -> bool:
        osc = getattr(self, "osc_manager", None)
        return bool(osc is not None and getattr(osc, "is_connected", False))

    def _friends_vrc_snapshot(self) -> Optional[Dict[str, Any]]:
        """The log's snapshot while the Friends switch is on, else None."""
        if not self.get_friends_vrc_log():
            return None
        snap = getattr(self, "_vrc_log_snapshot", None)
        return snap() if snap is not None else None

    def _vrc_shown_name(self, uid: str, fallback: str = "") -> str:
        """The one name for a VRChat account: People statistics' (the first
        it saw), else the link's, else `fallback`."""
        people = getattr(self, "stats_people", None)
        known = getattr(people, "vrc_names", {}).get(uid) if people is not None and uid else ""
        return known or self._friends_vrc_link_name(uid) or clean_display_name(fallback)

    def _friends_vrc_link_name(self, uid: str) -> str:
        """The name a linked friend's VRChat account had when you linked
        them ("" when nobody is linked to it). PeopleFacade asks this."""
        if not uid:
            return ""
        for f in self.friends_settings.get_friends():
            if f.get("vrc") == uid:
                return f.get("vrc_name", "")
        return ""

    # ------------------------------------------------------------------
    # In your instance
    # ------------------------------------------------------------------

    def friend_in_instance(self, peer: str) -> bool:
        """Whether this friend's linked VRChat account is in your instance
        right now -- by your own log, with VRChat running. A friend with no
        account linked, Me, the web remote, or the log not read: no."""
        f = self.friends_settings.get_friend(str(peer or ""))
        if f is None:
            return False
        return in_instance(self._friends_vrc_snapshot(), f.get("vrc", ""), self._vrchat_up())

    def _friend_vrc_fields(self, peer: str, snap: Optional[Dict[str, Any]] = None,
                           up: bool = False) -> Dict[str, Any]:
        """A friend's entry's VRChat part for the page: `vrc` (the id),
        `vrc_name` (the one name) and `here` (in your instance)."""
        f = self.friends_settings.get_friend(peer) or {}
        uid = f.get("vrc", "")
        return {"vrc": uid,
                "vrc_name": self._vrc_shown_name(uid, f.get("vrc_name", "")) if uid else "",
                "here": in_instance(snap, uid, up)}

    def _vrchat_entry(self, snap: Optional[Dict[str, Any]] = None,
                      up: bool = False) -> Dict[str, Any]:
        """The page's VRChat part: the switch, what the log is doing, and
        who's in your instance -- each {id, name, friend} (`friend`: who is
        linked to them, or "")."""
        on = self.get_friends_vrc_log()
        if not on:
            state = "off"
        elif snap is None:
            state = "starting"
        elif snap.get("state") != "ok":
            state = snap.get("state", "starting")      # starting / no_log / reading
        elif not up:
            state = "no_vrchat"
        elif not snap.get("in_room"):
            state = "no_room"
        else:
            state = "ok"
        people = []
        if state == "ok":
            owner = {uid: fid for fid, uid in self.friends_settings.vrc_links().items()}
            for key, name in snap.get("others") or ():
                uid = clean_user_id(key)
                if uid:                 # an old log without ids can't be linked
                    people.append({"id": uid, "name": self._vrc_shown_name(uid, name),
                                   "friend": owner.get(uid, "")})
        return {"log": on, "state": state, "people": people,
                "vrcx": self._vrcx.get("state", ""), "vrcx_count": len(self._vrcx["friends"])}

    def _friends_vrchat_status(self) -> Dict[str, Any]:
        """Once per page refresh: the snapshot and whether VRChat runs,
        read once for every row."""
        return {"snap": self._friends_vrc_snapshot(), "up": self._vrchat_up()}

    # ------------------------------------------------------------------
    # Linking
    # ------------------------------------------------------------------

    def link_friend_vrchat(self, peer: str, user_id: str, name: str = "") -> bool:
        """Link a friend to a VRChat account (its `usr_` id; `name`, its
        display name now). Whoever had that account loses it. False for Me,
        the web remote, an example friend, or an id that isn't one."""
        uid = clean_user_id(user_id)
        f = self.friends_settings.get_friend(str(peer or ""))
        if not uid or f is None:
            return False
        name = clean_display_name(name) or self._vrc_shown_name(uid)
        before = {fid: u for fid, u in self.friends_settings.vrc_links().items() if u == uid}
        if not self.friends_settings.set_vrc_link(f["id"], uid, name):
            return False
        # the log names your friends, never a VRChat account (it reaches the
        # system log, which may be shared to report a bug)
        self._friends_note(f"You linked {self._friend_nick(f['id'])} to their VRChat account")
        for fid in before:
            if fid != f["id"]:
                self._friends_note(f"{self._friend_nick(fid)} is no longer linked to that "
                                   "VRChat account")
        self._instance_refresh()             # who is in your instance (friends_instance)
        return True

    def unlink_friend_vrchat(self, peer: str) -> None:
        f = self.friends_settings.get_friend(str(peer or ""))
        if f is None or not f.get("vrc"):
            return
        self.friends_settings.set_vrc_link(f["id"], "")
        self._friends_note(f"You unlinked {self._friend_nick(f['id'])} from their VRChat account")
        self._instance_refresh()             # unlinked: not in your instance

    # ------------------------------------------------------------------
    # VRCX
    # ------------------------------------------------------------------

    def vrcx_installed(self) -> bool:
        """VRCX's database is on this PC (nothing read)."""
        return vrcx_friends.installed()

    def import_vrcx_friends(self) -> Dict[str, Any]:
        """Read your VRChat friends from VRCX, read-only, now. {state,
        count}: state as `vrcx_friends.read_friends` says (ok / missing /
        busy / none / error). Kept for this run only."""
        got = vrcx_friends.read_friends()
        state = got.get("state", "error")
        if state == "ok":
            self._vrcx = {"state": "ok", "friends": list(got["friends"])}
        elif not self._vrcx["friends"]:
            self._vrcx = {"state": state, "friends": []}
        else:
            self._vrcx = {**self._vrcx, "state": state}     # keep the list you had
        n = len(self._vrcx["friends"])
        if state == "ok":
            self._friends_note(f"You imported {n} VRChat friend{'' if n == 1 else 's'} from VRCX")
        return {"state": state, "count": n}

    def get_vrchat_choices(self, query: str = "", limit: int = PICK_LIMIT) -> Dict[str, Any]:
        """What a friend's VRChat account picker offers: `instance` (who's in
        your instance) and `vrcx` (your imported VRCX friends), each
        [{id, name, friend}], matching `query` (part of a name, any case),
        the VRCX list cut at `limit` -- `vrcx_more` says how many more match.
        `state` / `log` / `vrcx_state` as the page's VRChat part."""
        st = self._friends_vrchat_status()
        entry = self._vrchat_entry(st["snap"], st["up"])
        q = " ".join(str(query or "").split()).casefold()
        owner = {uid: fid for fid, uid in self.friends_settings.vrc_links().items()}
        here = [p for p in entry["people"] if q in p["name"].casefold()]
        here_ids = {p["id"] for p in entry["people"]}
        found: List[Dict[str, Any]] = []
        more = 0
        for uid, name in self._vrcx["friends"]:
            shown = self._vrc_shown_name(uid, name)
            if uid in here_ids or (q and q not in shown.casefold() and q not in name.casefold()):
                continue
            if len(found) < max(0, int(limit)):
                found.append({"id": uid, "name": shown, "friend": owner.get(uid, "")})
            else:
                more += 1
        return {"log": entry["log"], "state": entry["state"], "instance": here,
                "vrcx": found, "vrcx_more": more, "vrcx_state": self._vrcx.get("state", ""),
                "vrcx_count": len(self._vrcx["friends"]), "vrcx_installed": self.vrcx_installed()}
