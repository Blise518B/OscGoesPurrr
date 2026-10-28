"""Friends, part 7: the web remote -- one link anyone can open in a
browser to do what a friend can, no OGP needed (docs/remote.html).

The page is a Friends client (iroh in WebAssembly, tools/web_guest) with a
friend's whole panel: toy cards with their auto modes and Override, your
strength slider, PiShock's panel per shocker and Party Mode, your worn
avatar's board. Its hello says ``web`` and carries your web remote's code,
and it is let in as a web guest -- never a friend and never a contact
(nobody dials a browser), everyone on the link under one row, the Web
remote row, whose Toys / Shockers / Avatar switches say what all of them
may do: toys on, shockers and avatar off until you tick them (Blise's
call, 2026-10-28 -- anyone with the link gets them). Its messages take the
friends' own path, so every friend rule holds (Pause all friends, Off,
your strength, each toy's output band, zero when its updates stop, the
shocker engine's arming and caps, locked categories), and it is logged
like a friend. It never hears your friends' names: who else drives you
reaches it as a count.

Your link: Copy (the first copy makes it, and the row), New link (the old
one stops working and everyone on it is let go), On (off: nobody gets in,
everyone on it is let go), the three switches (for everyone on it), a kick
per browser (that browser can't come back with this link or a new one) and
Remove (the link and the row go).

Threads: `_web_invite_ok` runs on the link's thread; `_web_guests` and the
web guests' share of `_friend_perms` change under `_web_lock`, both swapped
whole like the facade's other copy-on-write dicts.

Mixed into FriendsFacade; see friends_facade.py for what the host has.
"""

import threading
from typing import Any, Dict, Optional

import friend_links
import remote_link
import remote_protocol as proto
from controllers.friends_common import FEATURE_KEY


class FriendsWebMixin:
    """Mixin: the web remote and its browsers."""

    def _friends_web_init(self) -> None:
        self._web_lock = threading.Lock()
        self._web_guests: Dict[str, str] = {}      # browser id -> nickname, while it's on
        self._web_selected = False                 # the Web remote row is picked

    # ------------------------------------------------------------------
    # The page
    # ------------------------------------------------------------------

    def _web_entry(self, peers: Dict[str, Dict[str, Any]], now: float) -> Optional[Dict[str, Any]]:
        """The Web remote row and panel -- None until you first copied the link."""
        web = self.friends_settings.get_web()
        if not web["code"]:
            return None
        guests = [{"id": gid, "nick": nick, "rtt": peers.get(gid, {}).get("rtt"),
                   "driving": self._is_driving(gid, now)}
                  for gid, nick in sorted(self._web_guests.items(), key=lambda kv: kv[1].lower())]
        return {"on": web["on"], "toys": web["toys"], "shock": web["shock"],
                "params": web["params"], "guests": guests,
                "driving": any(g["driving"] for g in guests), "selected": self._web_selected}

    def friends_web_link_message(self) -> str:
        """Your web remote link for the clipboard (the link, and what it is
        under it: friend_links.remote_message); the first one makes the link
        -- and the Web remote row."""
        my_id = self.friends_link.my_id
        if not my_id:
            return ""
        first = not self.friends_settings.web_code()
        code = self.friends_settings.web_code(make=True)
        if first:
            self._friends_rebuild_perms()
            self._friends_note("You made your web remote link - anyone who opens it in a "
                               "browser can drive your toys")
        else:
            self._friends_note("You copied your web remote link", key=("web-copy",))
        self._friends_refresh_ui()
        return friend_links.remote_message(my_id, code, self.friends_settings.get_nickname())

    def friends_web_new_link(self) -> None:
        """A new link: the old one stops working, everyone on it is let go."""
        if not self.friends_settings.web_code():
            return
        self.friends_settings.new_web_code()
        n = self._web_let_go_all(remote_link.WEB_CLOSED)
        self._friends_note("You made a new web remote link - the old one stopped working"
                           + (f" ({_browsers(n)} let go)" if n else ""))
        self._friends_refresh_ui()

    def set_friends_web_on(self, on: bool) -> None:
        on = bool(on)
        if on == self.friends_settings.get_web()["on"]:
            return
        self.friends_settings.set_web_on(on)
        if on:
            self._friends_note("Your web remote link works again")
        else:
            n = self._web_let_go_all(remote_link.WEB_CLOSED)
            self._friends_note("You switched your web remote off - nobody gets in"
                               + (f" ({_browsers(n)} let go)" if n else ""))
        self._friends_refresh_ui()

    def set_friends_web_permission(self, what: str, on: bool) -> None:
        """What everyone on the web remote may do: "toys", "shock" or
        "params" -- switched off, whatever they had going stops."""
        if what not in _WEB_LABELS:
            return
        on = bool(on)
        self.friends_settings.set_web_permission(what, on)
        self._friends_rebuild_perms()
        if not on:
            drop = getattr(self, "_params_drop_friend", None)
            for gid in list(self._web_guests):
                if what == "toys":
                    self._drop_drive(gid)
                elif what == "shock":
                    self._drop_shocks(gid)          # a warned shock never comes
                elif drop is not None:
                    drop(gid)                       # held buttons let go
        self._friends_note(f"Your web remote may {'now' if on else 'no longer'} "
                           f"{_WEB_LABELS[what]}")
        self._friends_refresh_ui()

    def friends_web_kick(self, gid: str) -> None:
        """Let one browser go for good: it can't come back."""
        nick = self._web_guests.get(gid)
        if nick is None:
            return
        self.friends_settings.web_block(gid)
        self._web_forget(gid)
        self.friends_link.drop(gid, remote_link.WEB_KICKED)
        self._friends_note(f"You kicked {nick} off your web remote - that browser can't "
                           "come back")
        self._friends_refresh_ui()

    def friends_web_remove(self) -> None:
        """No web remote any more: the link stops working, the row goes."""
        if not self.friends_settings.web_code():
            return
        n = self._web_let_go_all(remote_link.WEB_CLOSED)
        self.friends_settings.forget_web()
        self._web_selected = False
        self._friends_note("You removed your web remote - its link stopped working"
                           + (f" ({_browsers(n)} let go)" if n else ""))
        self._friends_refresh_ui()

    def _web_let_go_all(self, reason: bytes) -> int:
        gone = list(self._web_guests)
        for gid in gone:
            self._web_forget(gid)
            self.friends_link.drop(gid, reason)
        return len(gone)

    def _web_forget(self, gid: str) -> None:
        """A browser is off the web remote: nothing it sent drives anything."""
        with self._web_lock:
            self._web_guests = {k: v for k, v in self._web_guests.items() if k != gid}
        self._friends_rebuild_perms()
        self._drop_friend_state(gid)
        self._friend_driving.pop(gid, None)

    def _web_forget_all(self) -> None:
        """The link went down (offline, Friends off, a new ID)."""
        for gid in list(self._web_guests):
            self._web_forget(gid)

    def _web_perms(self) -> Dict[str, tuple]:
        """The web guests' share of `_friend_perms`: the Web remote row's
        Toys / Shockers / Avatar switches. Call with `_web_lock` held."""
        web = self.friends_settings.get_web()
        perms = (bool(web["toys"]), bool(web["shock"]), bool(web["params"]))
        return {gid: perms for gid in self._web_guests}

    def _web_nick(self, gid: str) -> Optional[str]:
        """How a web guest is called on the page and in the log, or None
        for anyone else."""
        nick = self._web_guests.get(gid)
        return None if nick is None else f"{nick} (web)"

    # ------------------------------------------------------------------
    # The link's thread
    # ------------------------------------------------------------------

    def _web_invite_ok(self, peer: str, code: str, nick: str) -> Optional[bool]:
        """None when `code` isn't your web remote's; else whether this
        browser gets in (it is a web guest from now on)."""
        web = self.friends_settings.get_web()
        if not web["code"] or code != web["code"]:
            return None
        if not web["on"] or peer in web["blocked"] or not self.get_feature_enabled(FEATURE_KEY):
            return False
        nick = proto.clean_nick(nick) or "Web guest"
        with self._web_lock:
            self._web_guests = {**self._web_guests, peer: nick}
            self._friend_perms = {**self._friend_perms, **self._web_perms()}
        self.thread_queue.put(("friends", ("web_joined", (peer, nick))))
        return True

    # ------------------------------------------------------------------
    # GUI thread (thread_queue)
    # ------------------------------------------------------------------

    def _web_on_queue(self, kind: str, data: Any) -> bool:
        """thread_queue messages about the web remote; False for any other."""
        if kind == "web_joined":
            gid, nick = data
            if gid in self._web_guests:
                self._friends_note(f"{nick} opened your web remote")
        elif kind == "web_left":
            gid, word = data
            nick = self._web_guests.get(gid)
            if nick is not None:
                self._web_forget(gid)
                why = {"bye": "closed the page", "timeout": "connection lost"}.get(word, "left")
                self._friends_note(f"{nick} left your web remote ({why})")
        elif kind == "web_nick":
            gid, nick = data
            nick = proto.clean_nick(nick)
            old = self._web_guests.get(gid)
            if old is not None and nick and nick != old:
                with self._web_lock:
                    self._web_guests = {**self._web_guests, gid: nick}
                self._friends_note(f"{old} (web) is now called {nick}")
        else:
            return False
        return True


def _browsers(n: int) -> str:
    return f"{n} browser{'' if n == 1 else 's'}"


_WEB_LABELS = {"toys": "drive your toys", "shock": "use your shockers",
               "params": "use your avatar's board"}
