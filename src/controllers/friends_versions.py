"""Friends, part 7: whose OGP is newer.

Each OGP says its version in the link's hello (remote_link). The first time
in a launch a friend links with a NEWER one, you're told so you can't miss
it -- a window with the way to update, and an amber banner on the Friends page
-- because what they do may need what yours lacks (Blise's ask, 2026-10-27).
A friend on an OLDER one gets an OLD tag on their row and a line in the log,
so you can tell them. A build from before versions were sent says none and
counts as older.

Mixed into FriendsFacade; see friends_facade.py for what the host has.
"""

from typing import Any, Dict, Optional, Tuple

import update_checker
import updater
from version import VERSION

# where a newer OGP is, for someone who can't install it from here
RELEASES_URL = "https://github.com/Blise518B/OscGoesPurrr/releases"


class FriendsVersionsMixin:
    """Mixin: friends' OGP versions against yours."""

    def _friends_versions_init(self) -> None:
        self._friend_versions: Dict[str, str] = {}   # peer -> their version ("": says none)
        self._versions_told: set = set()              # peers logged this launch
        self._update_warned = False                   # the window: once a launch

    def _friend_version_state(self, peer: str) -> str:
        """"newer" / "older" / "same" than yours, "" while unknown."""
        if peer not in self._friend_versions:
            return ""
        theirs = self._friend_versions[peer]
        if not theirs:
            return "older"
        return {1: "newer", 0: "same", -1: "older"}.get(
            update_checker.compare_versions(theirs, VERSION), "")

    def _friends_behind(self) -> Optional[Dict[str, Any]]:
        """You're behind a friend this launch: the newest of theirs, and
        who has it. None while you aren't."""
        friends = self.friends_settings.friend_ids()
        newer = [(v, p) for p, v in self._friend_versions.items()
                 if p in friends and self._friend_version_state(p) == "newer"]
        if not newer:
            return None
        top = newer[0][0]
        for v, _p in newer[1:]:
            if update_checker.compare_versions(v, top) == 1:
                top = v
        return {"version": top, "mine": VERSION,
                "who": [self._friend_nick(p) for v, p in newer
                        if update_checker.compare_versions(v, top) == 0]}

    def _friend_version_heard(self, peer: str, theirs: str) -> None:
        """GUI thread: a friend's hello said their version (once a link,
        again only if it changes)."""
        self._friend_versions[peer] = theirs
        state = self._friend_version_state(peer)
        if state in ("", "same") or peer in self._versions_told:
            return
        self._versions_told.add(peer)
        nick = self._friend_nick(peer)
        if state == "older":
            self._friends_note(
                f"{nick} has an older OGP ({theirs or 'from before version checks'}) than "
                f"yours ({VERSION}) - what's new in yours may not reach them until they update")
            return
        self._friends_note(f"{nick} has a newer OGP ({theirs}) than yours ({VERSION}) - "
                           "update so everything they do works for you")
        if not self._update_warned:
            self._update_warned = True
            self.show_friends_update(nick, theirs)

    def show_friends_update(self, nick: str = "", theirs: str = "") -> None:
        """The window that says you're behind (the Friends banner's button
        opens it again). Without a name: the friend you're furthest behind."""
        behind = self._friends_behind()
        if not nick or not theirs:
            if behind is None:
                return
            nick, theirs = ", ".join(behind["who"]), behind["version"]
        ui = getattr(self, "ui", None)
        show = getattr(ui, "show_friend_update_warning", None) if ui is not None else None
        if show is not None:
            show(nick, theirs, VERSION, self._friends_update_offer(theirs), RELEASES_URL)

    def _friends_update_offer(self, theirs: str) -> Optional[Tuple[str, str]]:
        """(version, release page) when the launch check found a release
        this copy can install itself that is at least theirs; else None."""
        info = getattr(self, "_pending_update", None) or {}
        latest = str(info.get("latest", ""))
        if not (info.get("available") and info.get("asset") and updater.is_self_updatable()):
            return None
        at_least = update_checker.compare_versions(latest, theirs)
        if at_least is None or at_least < 0:
            return None
        return latest, str(info.get("url", "")) or RELEASES_URL

    def _friend_version_fields(self, peer: str) -> Dict[str, Any]:
        """What a friend's entry on the page says about their version."""
        return {"app": self._friend_versions.get(peer), "version": self._friend_version_state(peer)}
