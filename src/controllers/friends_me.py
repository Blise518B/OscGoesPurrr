"""Friends, part 6: you, as a friend of yourself.

A "Me" row, always at the top of the friends list, whose panel is exactly what a
friend with everything allowed sees -- and works, through the same path a
friend's would: your levels and auto modes reach your toys through the
router like anyone's (Pause all friends, your strength and Off hold), your
shocks go through PiShockEngine (Home's On / Off and Share with friends,
your arming and caps hold), your avatar board through the Avatar Remote
owner side. Nothing goes over the network: `MeLink` hands whatever is sent
to ME straight back in on this side, and `_me_tick` (the GUI tick) feeds
the status, the drive and the board's values the link would repeat.

ME is not SELF: SELF is the avatar menu's "Both of us" on your own toys,
with its own rules; ME is a friend like any other, only local.

Mixed into FriendsFacade; see friends_facade.py for what the host has.
"""

from typing import Any, Dict, Optional

import remote_protocol as proto
from controllers.friends_common import ME


class MeLink:
    """The Friends link, with you on it: what goes to ME comes straight
    back in -- no network. Everything else is the real link's."""

    def __init__(self, host, link):
        self._host = host
        self._link = link

    def __getattr__(self, name):
        return getattr(self._link, name)

    def peers(self) -> Dict[str, Dict[str, Any]]:
        out = dict(self._link.peers())
        out[ME] = {"linked": True, "nick": self._host.friends_settings.get_nickname(),
                   "path": "this PC", "rtt": None}
        return out

    def push_cmd(self, peer: str) -> None:
        if peer == ME:
            self._host._me_send_cmd()
        else:
            self._link.push_cmd(peer)

    def send_event(self, peer: str, msg: Dict[str, Any], repeat: int = 3) -> None:
        if peer == ME:
            self._host._me_in(msg)
        else:
            self._link.send_event(peer, msg, repeat)

    def send_blob(self, peer: str, msg: Dict[str, Any]) -> None:
        if peer == ME:
            self._host._me_in(msg)
        else:
            self._link.send_blob(peer, msg)


class FriendsMeMixin:
    """Mixin: the Me row."""

    def _me_in(self, msg: Optional[Dict[str, Any]]) -> None:
        """A message to ME, received as if from ME (cleaned the same way)."""
        if msg:
            self._friends_on_event("message", ME, proto.decode(proto.encode(msg)))

    def _me_send_cmd(self) -> None:
        self._me_in(self._friends_cmd_for(ME))

    def _me_tick(self) -> None:
        """GUI tick: what the link would send between two OGPs -- the status,
        the drive (kept fresh like a friend's), who else drives, the board's
        watch and values."""
        self._me_in(self._friends_status_for(ME))
        self._me_in(self._friends_cmd_for(ME))
        for msg in self._friends_more_for(ME).values():
            self._me_in(msg)

    def _me_entry(self, peers: Dict[str, Dict[str, Any]], selected: Dict[str, str],
                  now: float) -> Dict[str, Any]:
        """The Me row for the page, shaped like a friend's."""
        st = self._friend_status.get(ME)
        nick = self.friends_settings.get_nickname() or "You"
        return {
            "id": ME, "nick": nick, "me": True, "toys": True, "shock": True, "params": True,
            "added": 0.0, "linked": True, "path": "this PC", "rtt": None,
            "selected": selected == {"kind": "friend", "id": ME},
            "theirs": None if st is None else {k: v for k, v in st.items() if k != "t"},
            "my_levels": dict(self._my_levels.get(ME, {})),
            "driving_me": self._is_driving(ME, now),
            "others": list(self._friend_others.get(ME, [])),
            "sync": False,
        }
