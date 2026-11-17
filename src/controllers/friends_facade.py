"""Friends facade mixin — other OGP users you link with over the internet:
they may drive your toys and shockers, you may drive theirs.

Behind `feature_friends` (on by default), and the link only goes online once
you have given yourself a nickname. What each friend may do is yours to
decide, per friend: a Toys switch (drive your toys, move your strength
slider) and a Shockers switch, both on for a new friend. Every friend with a switch
on can act at the same time:

  * Toys    — each friend sends a level for all your toys or for one toy;
    per toy the highest level of any friend wins. It enters the router at
    the Output stage (`get_friend_drive`), so your strength, your toy's
    output band and Off all still apply. A friend whose updates stop for
    `DRIVE_STALE_S` drives nothing.
  * Strength — a friend's change moves your own strength slider, exactly
    like the VRChat menu dial does; the latest change wins, theirs or yours.
  * Shocks  — a friend's shock goes through your PiShockEngine like every
    other shock: your caps, your rest after each pulse, and it is only a
    vibrate until you arm shocks on the Shockers page this session.

  * Avatar Remote — a third switch per friend: they see your worn avatar's
    board from the Avatar Remote page and may use it (ParamsFacade, the
    owner's half); you see theirs under their panel (friends_params.py).

"Pause all friends" and Off stop everything a friend sends; so does "Only
friends in my instance" for a friend who isn't in it (friends_instance.py).
Every action a friend takes on you, and every one you take on them, lands
in the page's log.

Five files: this one (the link, contacts, invites, groups, the log),
`friends_control.py` (you driving friends), `friends_menu.py` (the avatar
menu's Friends part), `friends_receive.py` (friends driving you) and
`friends_params.py` (a friend's avatar board), with what they share in
`friends_common.py`. Beside them: `friends_me.py` (you on your own list),
`friends_versions.py` (whose OGP is newer), `friends_web.py` (the web
remote: browsers on one link, toys only), `friends_vrchat.py` (each
friend linked to their VRChat account, yours alone) and
`friends_instance.py` (only friends in your instance).

Threads: `RemoteLink` calls `_friends_on_event` and builds its messages
(`_friends_status_for`, `_friends_cmd_for`) on its own thread. Everything
those touch is either swapped whole (copy-on-write dicts) or a snapshot the
GUI thread refreshes every `_TICK_MS`; settings change on the GUI thread
only, via `thread_queue`.

Assumes the host controller has `self.thread_queue`, `self.ui`,
`self.log_message`, `self.get_feature_enabled`, `self.is_output_off`,
`self.get_strength` / `self.set_strength`, and (optionally)
`self.haptic_engine`, `self.motor_router` and `self.pishock_engine`.
"""

import os
import sys
import threading
import time
from collections import deque
from typing import Any, Dict, List, Optional

import debug_log
import event_log
import friend_links
import friends_demo
import inbound_rate
import link_handoff
import link_scheme
import remote_link
import remote_protocol as proto
from controllers.friends_common import FEATURE_KEY, ME, WEB, coming_through, shocker_label
from event_log import LINK, SETTINGS, TOYS
from pishock_engine import GROUP_FRIENDS
from controllers.friends_control import FriendsControlMixin
from controllers.friends_instance import FriendsInstanceMixin
from controllers.friends_me import FriendsMeMixin, MeLink
from controllers.friends_menu import FriendsMenuMixin, MenuState
from controllers.friends_params import FriendsParamsMixin
from controllers.friends_receive import FriendsReceiveMixin
from controllers.friends_versions import FriendsVersionsMixin
from controllers.friends_vrchat import FriendsVrchatMixin
from controllers.friends_web import FriendsWebMixin
from settings._paths import FRIENDS_KEY_FILE
from settings.friends import FriendsSettingsManager

_TICK_MS = 100
_LOG_MAX = 200               # lines on the Friends page's log card
_BY_PERSON_FROM = 600        # the newest this many make the card's "by person"


class FriendsFacade(FriendsControlMixin, FriendsMenuMixin, FriendsReceiveMixin,
                    FriendsParamsMixin, FriendsMeMixin, FriendsVersionsMixin, FriendsWebMixin,
                    FriendsVrchatMixin, FriendsInstanceMixin):
    """Mixin: the Friends page's controller surface -- the link, contacts,
    invites, groups and the log here; driving friends, the avatar menu,
    what friends do to you and a friend's avatar board in its four
    parts."""

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def _friends_init(self) -> None:
        self.friends_settings = FriendsSettingsManager()
        # The log is one store for the app (LogFacade, its files and the Log
        # page); a host without one keeps it in memory only.
        if getattr(self, "event_log", None) is None:
            self.event_log = event_log.EventLog(None)
        self._friend_requests: Dict[str, str] = {}
        self._friend_status: Dict[str, Dict[str, Any]] = {}
        self._friend_drive: Dict[str, Any] = {}       # peer -> Drive
        self._friend_holds: Dict[str, Any] = {}       # peer -> ({slot: (op, v)}, t)
        self._holding: Dict[tuple, int] = {}          # (peer, slot) -> shocker id held
        # _friend_lock guards _holding, _warnings and _friend_holds: the link
        # thread and the GUI tick both change them.
        self._warnings: Dict[tuple, Dict[str, Any]] = {}   # (peer, slot) -> a warning running
        self._friend_lock = threading.Lock()
        self._friend_str_seq: Dict[str, int] = {}
        self._friend_driving: Dict[str, bool] = {}
        # each sender's recent shock / Stop ids, apart: one sending many
        # can't push another's out (and see that one's copies as new)
        self._seen_shocks: Dict[str, deque] = {}
        # how often each sender may make your shockers act (inbound_rate)
        self._shock_budget = inbound_rate.Budget(*inbound_rate.SHOCKS)
        self._stop_budget = inbound_rate.Budget(*inbound_rate.STOPS)
        # ... and change the toy cards (Me excepted: friends_receive)
        self._card_budget = inbound_rate.Budget(*inbound_rate.CARDS)
        # a friend's strength change waiting for the GUI thread: only the
        # newest one per friend is queued (friends_receive)
        self._friend_str_pending: Dict[str, float] = {}
        self._str_lock = threading.Lock()
        self._my_levels: Dict[str, Dict[str, float]] = {}
        self._my_override: Dict[str, set] = {}       # peer -> toys you override
        self._my_patterns: Dict[str, Dict[str, tuple]] = {}   # peer -> toy -> auto mode
        self._my_holds: Dict[str, Dict[int, tuple]] = {}      # peer -> slot -> (op, v)
        self._my_strength: Dict[str, Any] = {}        # peer -> (seq, value, t)
        self._my_seq = 0
        # Sync with others: your panel's version per friend, and who else
        # drives each friend (their OGP says, `oth`)
        self._my_pseq: Dict[str, int] = {}
        self._friend_others: Dict[str, List[str]] = {}
        self._oth_told: set = set()     # friends told someone else drives (link thread)
        # ... and as the one driven: each sender's last (version said,
        # version vouched for, cards) -- kept past a drop -- and whether a
        # real change has landed since going online (friends_receive's
        # _sync_version; the link's thread)
        self._sync_seen: Dict[str, tuple] = {}
        self._sync_settled = False
        # Your toys' live levels go only to a friend whose page shows your
        # panel (`lw`): whose panel yours shows, and who shows yours
        self._lw_peer: Optional[str] = None
        self._lw_was: set = set()                     # told "watching" this session
        self._level_watchers: Dict[str, float] = {}   # peer -> their last "watching"
        self._my_state: Dict[str, Any] = {}
        self._friend_perms: Dict[str, tuple] = {}
        # (peer, slot) -> why their hold there is refused, once told (GUI tick)
        self._hold_refused: Dict[tuple, str] = {}
        # Example friends next to the real ones (OGP_FRIENDS_DEMO=1): page
        # only, never the network, never a level for the router.
        self._demo = (friends_demo.FriendsDemo()
                      if os.environ.get(friends_demo.ENV) == "1" else None)
        self._friend_menu = MenuState()      # the avatar menu's Friends part
        self._avatar_has_friends_menu: Optional[bool] = None
        self._friends_tick_running = False
        self._invite_lock = threading.Lock()
        self._used_invites: set = set()
        self._pending_invite: Optional[Dict[str, str]] = None
        self._invite_nicks: Dict[str, str] = {}      # peer -> nick their invite link gave
        self._friends_params_init()
        self._friends_versions_init()
        self._friends_web_init()
        self._friends_vrchat_init()
        self._friends_instance_init()
        self._friends_rebuild_perms()
        log = lambda m: self.thread_queue.put(("ui_update", m))
        self._friend_dropped: Dict[str, float] = {}   # peer -> when their drive went quiet
        self._me_selected = False                     # the Me row is picked (friends_me)
        self._tick_at = 0.0
        self._tick_said = 0.0
        self.friends_link = MeLink(self, remote_link.RemoteLink(
            key_path=str(FRIENDS_KEY_FILE),
            log=log,
            on_event=self._friends_on_event,
            status_for=self._friends_st_for,
            cmd_for=self._friends_cmd_for,
            invite_ok=self._friends_invite_ok,
            more_for=self._friends_more_for,
            debug=self._friends_debug,
        ))
        # A clicked invite link starts a new OGP, which hands the link over
        # here and quits (link_handoff) -- listening whether or not Friends
        # is on, so a link never starts a second OGP next to this one. Only
        # the built app: ogp:// opens the exe / AppImage, never a source run.
        self._links_listener = None
        self._friends_elsewhere = False
        self._elsewhere_checked = 0.0
        if getattr(sys, "frozen", False):
            self._links_listener = link_handoff.LinkListener(
                on_link=lambda url: self.thread_queue.put(("friends", ("open_link", url))),
                log=log)
            self._friends_claim_pipe()
            if self.get_feature_enabled(FEATURE_KEY):
                link_scheme.register(log)
        if not remote_link.available():
            self.log_message(f"Friends: the network library didn't load ({remote_link.IROH_ERROR})")
        self._friends_maybe_start()

    def _friends_claim_pipe(self) -> None:
        """Another OGP window that already listens has the Friends ID
        online: this one stays offline (one ID online twice loses links)
        until that one closes -- e.g. the old window an update replaces."""
        self._friends_elsewhere = link_handoff.send_to_running(link_handoff.PING, timeout=0.5)
        if not self._friends_elsewhere:
            self._links_listener.start()

    def _friends_check_elsewhere(self) -> None:
        """Its own thread: is the other OGP window still holding the
        Friends ID? When it isn't, the GUI thread takes over."""
        if not link_handoff.send_to_running(link_handoff.PING, timeout=0.5):
            self.thread_queue.put(("friends", ("elsewhere_gone", None)))

    def _friends_ui_ready(self) -> None:
        """The UI exists: start the GUI-thread tick that snapshots this PC's
        state for friends and logs who started or stopped driving."""
        if self._friends_tick_running or getattr(self, "ui", None) is None:
            return
        self._friends_tick_running = True
        self.ui.schedule_callback(_TICK_MS, self._friends_tick)

    def _friends_maybe_start(self) -> None:
        link = getattr(self, "friends_link", None)
        if (link is None or link.running or not remote_link.available()
                or not self.get_feature_enabled(FEATURE_KEY)
                or not self.friends_settings.get_nickname()
                or not self.friends_settings.get_online()
                or getattr(self, "_friends_elsewhere", False)):
            return
        link.start(self.friends_settings.get_nickname(), self.friends_settings.friend_ids(),
                   unfriended=self.friends_settings.get_unfriended())

    def _friends_stop(self) -> None:
        link = getattr(self, "friends_link", None)
        if link is not None:
            link.stop()
        self._web_forget_all()                 # the browsers come back when you do
        for peer in set(self._friend_holds) | {k[0] for k in self._warnings}:
            self._drop_shocks(peer)
        self._friend_drive = {}
        self._friend_status = {}
        self._friend_requests = {}
        self._my_levels = {}
        self._my_override, self._my_patterns, self._my_holds = {}, {}, {}
        self._my_pseq, self._friend_others = {}, {}
        self._sync_seen, self._sync_settled = {}, False   # as after a restart
        self._level_watchers = {}
        for peer in set(self._their_boards) | set(self._my_param_holds):
            self._drop_their_board(peer)
        drop = getattr(self, "_params_drop_friend", None)
        if drop is not None:
            for peer in list(self._friend_perms):
                drop(peer)
        self._needs_recalculation = True
        wake = getattr(self, "_wake_routing", None)   # the routing tick may sleep
        if wake is not None:
            wake()

    def _friends_shutdown(self) -> None:
        listener = getattr(self, "_links_listener", None)
        if listener is not None:
            listener.stop()
        if getattr(self, "friends_link", None) is not None:
            self._friends_stop()

    def _friends_feature_changed(self, enabled: bool) -> None:
        if enabled:
            if getattr(sys, "frozen", False):
                link_scheme.register(lambda m: self.thread_queue.put(("ui_update", m)))
            self._friends_maybe_start()
        else:
            self._friends_stop()
            self.log_message("Friends off — the link is closed")
        self._friends_refresh_ui()

    # ------------------------------------------------------------------
    # The page
    # ------------------------------------------------------------------

    def get_friends_status(self) -> Dict[str, Any]:
        link = self.friends_link
        peers = link.peers()
        selected = self.friends_settings.get_selected()
        if self._me_selected:
            selected = {"kind": "friend", "id": ME}
        elif self._web_selected:
            selected = {"kind": "web", "id": WEB}
        status = self._friend_status
        now = time.monotonic()
        friends = [self._me_entry(peers, selected, now)]
        checks = link.check_state()               # the ↻: {peer: (checking, wait)}
        vrc = self._friends_vrchat_status()        # VRChat's log, read once (friends_vrchat)
        for f in self.friends_settings.get_friends():
            p = peers.get(f["id"], {})
            st = status.get(f["id"]) if p.get("linked") else None
            checking, check_wait = checks.get(f["id"], (False, 0.0))
            friends.append({
                **f,
                "nick": f["nick"] or p.get("nick") or "",
                "linked": bool(p.get("linked")),
                # being checked (↻), and when the next check may go
                "checking": bool(checking) and not p.get("linked"),
                "check_wait": check_wait,
                "path": p.get("path", ""),
                "rtt": p.get("rtt"),
                "selected": selected == {"kind": "friend", "id": f["id"]},
                "theirs": None if st is None else {k: v for k, v in st.items() if k != "t"},
                "my_levels": dict(self._my_levels.get(f["id"], {})),
                "driving_me": self._is_driving(f["id"], now),
                # the others driving them too (their OGP says)
                "others": list(self._friend_others.get(f["id"], [])) if p.get("linked") else [],
                **self._friend_version_fields(f["id"]),        # their OGP against yours
                **self._friend_vrc_fields(f["id"], **vrc),     # their VRChat account
                **self._friend_here_fields(f["id"]),           # only friends in your instance
            })
        groups = self.friends_settings.get_groups()
        demo = getattr(self, "_demo", None)
        if demo is not None:
            friends += demo.entries(self._my_levels, self._my_strength)
            groups = groups + [dict(g, members=list(g["members"])) for g in demo.groups]
            if demo.selected:
                selected = dict(demo.selected)
            for f in friends:
                f["selected"] = selected == {"kind": "friend", "id": f["id"]}
        for f in friends:
            f["my_override"] = set(self._my_override.get(f["id"], ()))
            f["my_patterns"] = dict(self._my_patterns.get(f["id"], {}))
            f["my_holds"] = dict(self._my_holds.get(f["id"], {}))
        asking = [{"id": pid, "nick": p.get("nick") or self._invite_nicks.get(pid, ""),
                   "declined": p.get("declined", False),
                   "waiting": p.get("waiting", False)}
                  for pid, p in peers.items()
                  if (p.get("asking") or p.get("declined")) and pid not in self.friends_settings.friend_ids()]
        return {
            "available": remote_link.available(),
            "enabled": self.get_feature_enabled(FEATURE_KEY),
            "running": link.running,
            "online": link.online,
            "error": link.error,
            "my_id": link.my_id,
            "nickname": self.friends_settings.get_nickname(),
            "paused": self.friends_settings.get_paused(),
            "sync_all": self.friends_settings.get_sync_all(),   # Sync with others: yours
            "requests": [{"id": k, "nick": v} for k, v in self._friend_requests.items()],
            "asking": asking,
            "friends": friends,
            "groups": groups,
            "selected": selected,
            "online_switch": self.friends_settings.get_online(),
            "avatar_menu": self.get_avatar_menu(),
            "elsewhere": self._friends_elsewhere,
            "pending_invite": (self._pending_invite or {}).get("nick")
                              or ("someone" if self._pending_invite else ""),
            "invites": self.friends_settings.get_invites(),
            "params_on": bool(self.get_feature_enabled("feature_params")),
            # your shockers exist here at all: what friends may do with them
            "shockers_on": bool(self.get_feature_enabled("feature_pishock")),
            # whose shocker buttons the panel shows (shocker_layout.py)
            "shocker_layout": self.get_shocker_layout(),
            "behind": self._friends_behind(),       # a friend's OGP is newer than yours
            "web": self._web_entry(peers, now),     # the Web remote row (None: no link yet)
            "vrchat": self._vrchat_entry(**vrc),    # who's in your instance (friends_vrchat)
            "instance": self._instance_entry(),     # only friends in it (friends_instance)
        }

    def get_friends_log(self) -> List[Dict[str, Any]]:
        """The Friends page's log, newest first: each entry's record
        (event_log.Event.as_dict -- t, text, who, name, kind, op ...).
        Your own avatar's behaviours are on the Log page only."""
        return [e.as_dict() for e in self.event_log.recent(_LOG_MAX, where=_friends_entry)]

    def get_friends_log_people(self) -> List[Dict[str, Any]]:
        """The log card's "by person": a row per person (friends, Me, web
        remote guests, groups), the one active most recently first, each
        with what they did last and their recent history."""
        now = time.time()
        recent = self.event_log.recent(_BY_PERSON_FROM, where=_friends_entry)
        return [p.as_dict(now) for p in event_log.by_person(
            recent, skip_roles=(event_log.ROLE_YOU,))]

    def set_friends_nickname(self, nick: str) -> str:
        """Required before the link goes online; can be changed, never
        emptied again."""
        if not proto.clean_nick(nick):
            return self.friends_settings.get_nickname()
        nick = self.friends_settings.set_nickname(nick)
        if self.friends_link.running:
            self.friends_link.set_nickname(nick)
        else:
            if self._pending_invite and not self.friends_settings.get_online():
                self.friends_settings.set_online(True)     # they clicked an invite
            self._friends_maybe_start()
        if self._pending_invite and self.friends_link.running:
            inv, self._pending_invite = self._pending_invite, None
            self._join_invite(inv)
        self._friends_refresh_ui()
        return nick

    @staticmethod
    def is_valid_friend_id(text: str) -> bool:
        return proto.valid_id(proto.clean_id(text))

    def friends_add(self, peer_id: str) -> str:
        """Ask the owner of `peer_id` to be friends -- or join the invite
        link pasted instead. Returns "" or why not."""
        inv = friend_links.parse(peer_id)
        if not self.friends_link.running and self._friends_elsewhere:
            return "Friends runs in your other OGP window - add them there."
        if inv is not None and inv["code"]:
            if not self.friends_link.running:
                return "Set your nickname first."
            return self._join_invite(inv)
        peer = inv["id"] if inv is not None else proto.clean_id(peer_id)
        if not self.friends_link.running:
            return "Set your nickname first."
        if peer == self.friends_link.my_id:
            return "That's your own ID - paste the one your friend sent you."
        if not proto.valid_id(peer):
            return "That isn't a whole ID. It is 64 letters and numbers."
        if peer in self.friends_settings.friend_ids():
            return "You're already friends."
        self.friends_link.pair_with(peer)
        self._friends_note("You asked {who} to be friends", who=peer,
                           name=proto.display_name("", peer), op="ask")
        return ""

    def friends_check_now(self, peer: Optional[str] = None) -> List[str]:
        """The Friends list's ↻: try reaching `peer` now -- with none, every
        friend who shows offline -- instead of waiting for the link's next
        try in the background. The link takes each friend at most once per
        remote_link.CHECK_GAP_S. Returns who a try went out for."""
        link = self.friends_link
        if not link.running or not link.online:
            return []
        ids = self.friends_settings.friend_ids()
        if peer is not None:
            ids = [peer] if peer in ids else []
        else:
            peers = link.peers()
            ids = [p for p in ids if not peers.get(p, {}).get("linked")]
        return link.check_now(ids) if ids else []

    def set_friends_online(self, online: bool) -> None:
        """The Online switch: off, Friends uses no network at all."""
        online = bool(online)
        if online == self.friends_settings.get_online():
            return
        self.friends_settings.set_online(online)
        if online:
            self._friends_maybe_start()
            self._friends_note("You went online", op="online")
        else:
            self._friends_stop()
            self._friends_note("You went offline - nobody can reach you until you're back",
                               op="offline")
        self._friends_refresh_ui()

    # --- invite links
    def friends_invite_message(self, kind: str = "once") -> str:
        """A fresh invite for the clipboard: the link to the invite page and
        who it is from under it (friend_links.invite_message). `kind` is how
        long and how often it works (once / day / week / forever,
        settings.friends.INVITE_KINDS)."""
        my_id = self.friends_link.my_id
        if not my_id:
            return ""
        if kind not in _INVITE_WORDS:
            kind = "once"
        code = self.friends_settings.new_invite(kind)
        self._friends_note(f"You made an invite link - {_INVITE_WORDS[kind]}", op="invite")
        return friend_links.invite_message(my_id, code, self.friends_settings.get_nickname())

    def friends_close_invites(self) -> None:
        """Every invite link you sent stops working; friends stay friends."""
        n = len(self.friends_settings.get_invites())
        self.friends_settings.close_invites()
        self._friends_note(f"You closed your invite links ({n})" if n else
                           "You closed your invite links", op="invite")
        self._friends_refresh_ui()

    def friends_reset_id(self) -> None:
        """A new Friends ID: every friend unlinked and forgotten, every
        invite link and the old ID dead. For a link that got out of hand."""
        n = len(self.friends_settings.friend_ids())
        self._menu_retarget(self.friends_settings.forget_everyone)
        self._web_selected = False                # the web remote link goes with the ID
        self._friends_contacts_changed()          # friends see "removed"
        self.friends_link.stop(timeout=5.0)
        self._friends_stop()
        if not self.friends_link.forget_identity():
            self._friends_note("Your old ID couldn't be dropped right now - try New ID again",
                               op="new-id")
        with self._invite_lock:
            self._used_invites = set()
        self._pending_invite = None
        self._invite_nicks = {}
        self._friends_rebuild_perms()
        self._friends_maybe_start()
        self._friends_note(f"You have a new ID - {n} friend{'' if n == 1 else 's'} unlinked; "
                           "your old ID and every invite link stopped working", op="new-id")
        self._friends_refresh_ui()

    def friends_open_link(self, link: str) -> None:
        """An invite link was clicked: show the Friends page and link up
        with whoever sent it (once a nickname is set). A second OGP that was
        told to switch to this one sends SHOW: just come to the front."""
        ui = getattr(self, "ui", None)
        if link == link_handoff.SHOW:
            if ui is not None:
                ui.show_window()
            return
        if ui is not None:
            if self.get_feature_enabled(FEATURE_KEY):
                ui.select_view("Friends")
            ui.show_window()
        inv = friend_links.parse(link)
        if inv is None:
            self._friends_note("That link isn't an OGP invite", op="invite")
            return
        who = proto.display_name(inv["nick"], inv["id"])
        if not self.get_feature_enabled(FEATURE_KEY) or not self.friends_settings.get_nickname():
            # One small window asks for the nickname (and switches Friends
            # on) -- answering it links you; nothing to find on the page.
            self._pending_invite = inv
            self._friends_note("{who} invited you - pick a nickname and you're linked",
                               who=inv["id"], name=who, op="invite", dir=event_log.IN)
            prompt = getattr(ui, "prompt_friends_invite", None) if ui is not None else None
            if prompt is not None:
                prompt(who, self.friends_settings.get_nickname(),
                       not self.get_feature_enabled(FEATURE_KEY))
        elif not self.friends_link.running:
            # Clicking an invite is wanting to link: go online for it.
            self._pending_invite = inv
            if not self.friends_settings.get_online():
                self.friends_settings.set_online(True)
                self._friends_note("You went online for the invite", op="online")
            self._friends_maybe_start()
            if self.friends_link.running:
                self._pending_invite = None
                self._join_invite(inv)
        else:
            self._pending_invite = None
            self._join_invite(inv)
        self._friends_refresh_ui()

    def accept_friends_invite(self, nick: str) -> str:
        """The invite window's Link up: switch Friends on if it was off, take
        the nickname and join the waiting invite. Returns "" or why not."""
        if not proto.clean_nick(nick):
            return "Type a nickname first."
        if not self.get_feature_enabled(FEATURE_KEY):
            self.set_feature_enabled(FEATURE_KEY, True)
        self.set_friends_nickname(nick)
        ui = getattr(self, "ui", None)
        if ui is not None:
            ui.select_view("Friends")
        return ""

    def _join_invite(self, inv: Dict[str, str]) -> str:
        who = proto.display_name(inv["nick"], inv["id"])
        if inv["id"] == self.friends_link.my_id:
            return "That's your own invite link - send it to a friend instead."
        if inv["id"] in self.friends_settings.friend_ids():
            self.set_friends_selected("friend", inv["id"])
            self._friends_note("You're already friends with {who}", who=inv["id"], op="invite")
            return ""
        self._invite_nicks[inv["id"]] = inv["nick"]       # also: open their panel once linked
        self.friends_link.pair_with(inv["id"], inv["code"])
        self._friends_note("Joining {who}'s invite…", who=inv["id"], name=who, op="invite")
        return ""

    def _friends_invite_ok(self, peer: str, code: str, nick: str) -> bool:
        """Link thread: someone came with an invite code. True (once) when
        it is one of ours and still fresh -- or your web remote's, and the
        browser may come in (friends_web.py)."""
        web = self._web_invite_ok(peer, code, nick)
        if web is not None:
            return web
        with self._invite_lock:
            kind = self.friends_settings.invite_kind(code)
            if kind is None or code in self._used_invites:
                return False
            if kind == "once":
                self._used_invites.add(code)
        self.thread_queue.put(("friends", ("invite_used", (peer, code, nick))))
        return True

    # --- contacts and what each may do
    def friends_answer(self, peer: str, accept: bool) -> None:
        nick = self._friend_requests.get(peer, "")
        if accept:
            self.friends_settings.add_friend(peer, nick)
            self._friends_contacts_changed()
            self._friends_note("You accepted {who} as a friend", who=peer,
                               name=proto.display_name(nick, peer), op="accept")
        else:
            self._friends_note("You declined {who}", who=peer,
                               name=proto.display_name(nick, peer), op="decline")
        self.friends_link.answer(peer, accept)

    def friends_remove(self, peer: str) -> None:
        if self._demo_of("friend", peer):
            self._friends_note("Example friends stay while OGP runs with OGP_FRIENDS_DEMO=1",
                               kind=SETTINGS)
            return
        nick = self._friend_nick(peer)
        self._menu_retarget(lambda: self.friends_settings.remove_friend(peer))
        self._friends_contacts_changed()
        self._drop_friend_state(peer)
        self._friends_note("You unfriended {who}", who=peer, name=nick, op="unfriend")
        self._friends_refresh_ui()

    def set_friend_permission(self, peer: str, what: str, allowed: bool) -> None:
        """`what` is "toys", "shock" or "params"."""
        label = {"toys": "your toys", "shock": "your shockers",
                 "params": "your avatar's board"}.get(what, what)
        demo = self._demo_of("friend", peer)
        if demo is not None:
            demo.perms[peer][_PERM_AT.get(what, 0)] = bool(allowed)
            self._friends_note(f"{{who}} (example) may {'now' if allowed else 'no longer'} "
                               f"control {label}", who=peer, name=demo.nick(peer),
                               kind=SETTINGS, op="allow" if allowed else "deny")
            return
        self.friends_settings.set_permission(peer, what, allowed)
        self._friends_rebuild_perms()
        if not allowed:
            if what == "toys":
                self._drop_drive(peer)
            elif what == "shock":
                self._drop_shocks(peer)       # a warned shock never comes
            else:
                drop = getattr(self, "_params_drop_friend", None)
                if drop is not None:
                    drop(peer)                # held buttons let go
        self._friends_note(f"{{who}} may {'now' if allowed else 'no longer'} control {label}",
                           who=peer, kind=SETTINGS, op="allow" if allowed else "deny")

    def set_friend_permission_all(self, what: str) -> Optional[bool]:
        """A column header: one permission for every friend at once -- off
        while any of them has it (the safe way first), else on. Returns the
        new state (None: nobody to change)."""
        ids = self.friends_settings.friend_ids()
        if not ids or what not in _PERM_AT:
            return None
        on = not any(bool((self.friends_settings.get_friend(i) or {}).get(what)) for i in ids)
        for peer in ids:
            self.friends_settings.set_permission(peer, what, on)
        self._friends_rebuild_perms()
        if not on:
            for peer in ids:
                if what == "toys":
                    self._drop_drive(peer)
                elif what == "shock":
                    self._drop_shocks(peer)
                else:
                    drop = getattr(self, "_params_drop_friend", None)
                    if drop is not None:
                        drop(peer)
        label = {"toys": "your toys", "shock": "your shockers",
                 "params": "your avatar's board"}[what]
        self._friends_note(f"Every friend may {'now' if on else 'no longer'} control {label}",
                           kind=SETTINGS, op="allow" if on else "deny")
        return on

    def set_friends_paused(self, paused: bool) -> None:
        self.friends_settings.set_paused(paused)
        self._needs_recalculation = True
        wake = getattr(self, "_wake_routing", None)   # the routing tick may sleep
        if wake is not None:
            wake()
        release = getattr(self, "_params_release_all", None)
        if paused and release is not None:
            release()                       # avatar buttons they hold let go
        self._friends_note("All friends paused - nothing they send reaches you" if paused
                           else "Friends resumed", kind=SETTINGS,
                           op="pause" if paused else "resume")

    # --- what the page's panel shows and the VRChat menu acts on: one
    # friend, or a group of them
    def set_friends_selected(self, kind: str, sid: str) -> None:
        """Pick a friend or a group. The menu's level moves with it rather
        than staying on whoever was picked before."""
        demo = getattr(self, "_demo", None)
        self._web_selected = kind == "web"
        if kind == "web":
            # the Web remote row: nothing to drive there, so the menu drives nobody
            self._me_selected = False
            if demo is not None:
                demo.selected = None
            return
        if kind == "friend" and sid == ME:
            self._me_selected = True
            if demo is not None:
                demo.selected = None
            return
        self._me_selected = False
        if demo is not None:
            if demo.has(kind, sid):
                demo.selected = {"kind": kind, "id": sid}
                return
            demo.selected = None
        if self.friends_settings.get_selected() == {"kind": kind, "id": sid}:
            return
        self._menu_retarget(lambda: self.friends_settings.set_selected(kind, sid))

    def friends_add_group(self, name: str) -> Optional[str]:
        gid = self.friends_settings.add_group(name)
        if gid:
            self._friends_note("You made the group {who}", who=event_log.group_key(gid),
                               kind=SETTINGS, op="group")
            self.set_friends_selected("group", gid)
        return gid

    def friends_rename_group(self, gid: str, name: str) -> None:
        demo = self._demo_of("group", gid)
        if demo is not None:
            name = " ".join(str(name).split())[:24]
            if name:
                demo.group(gid)["name"] = name
            return
        old = self._group_name(gid)
        self.friends_settings.rename_group(gid, name)
        if self._group_name(gid) != old:
            self._friends_note(f"Group {old} is now {{who}}", who=event_log.group_key(gid),
                               kind=SETTINGS, op="rename")

    def friends_delete_group(self, gid: str) -> None:
        demo = self._demo_of("group", gid)
        if demo is not None:
            demo.groups = [g for g in demo.groups if g["id"] != gid]
            demo.selected = None
            return
        name = self._group_name(gid)
        self._menu_retarget(lambda: self.friends_settings.delete_group(gid))
        self._friends_note("You deleted the group {who}", who=event_log.group_key(gid),
                           name=name, kind=SETTINGS, op="group")

    def set_group_member(self, gid: str, peer: str, on: bool) -> None:
        demo = self._demo_of("group", gid)
        if demo is not None:
            demo.set_member(gid, peer, on)
            return
        self._menu_retarget(lambda: self.friends_settings.set_member(gid, peer, on))
        self._friends_note(f"{{who}} {'joins' if on else 'leaves'} {self._group_name(gid)}",
                           who=peer, kind=SETTINGS, op="join" if on else "leave")

    def _friends_targets(self) -> List[str]:
        """Whoever is picked: one friend, or a group's members."""
        if self._me_selected:
            return [ME]
        if self._web_selected:
            return []
        demo = getattr(self, "_demo", None)
        if demo is not None and demo.selected:
            return demo.targets()
        return self.friends_settings.targets()

    def _group_name(self, gid: str) -> str:
        demo = self._demo_of("group", gid)
        g = demo.group(gid) if demo is not None else self.friends_settings.get_group(gid)
        return g["name"] if g else "?"

    # ------------------------------------------------------------------
    # Link events and what the link sends -- the link's thread
    # ------------------------------------------------------------------

    def _friends_on_event(self, kind: str, peer: str, data: Any) -> None:
        if peer in self._web_guests and kind != "message":
            # a browser on the web remote (friends_web.py): never a friend --
            # what it sends takes a friend's path, gated by its switches
            if kind == "unlinked":
                self._drop_friend_state(peer)       # its drive stops now
                self.thread_queue.put(("friends", ("web_left", (peer, data or ""))))
            elif kind == "nick":
                self.thread_queue.put(("friends", ("web_nick", (peer, data or ""))))
            self.thread_queue.put(("friends", ("refresh", None)))
            return
        if kind == "message":
            t = data.get("t")
            if t in _NEVER_FROM_A_BROWSER and peer in self._web_guests:
                # a browser is never driven by you: it has no status, shared
                # panel, "who else" or board to send -- one that does isn't
                # the web remote page, and none of it is taken
                self._web_refused(peer, t)
                return
            if t == "st":
                # with Sync with others as they have it (``sep``: their call)
                self._friend_status = {**self._friend_status,
                                       peer: {**proto.read_status(data), "t": time.monotonic(),
                                              "separate": proto.read_separate(data)}}
            elif t == "cmd":
                self._friend_cmd_in(peer, data)
            elif t == "pnl":
                self._friend_panel_in(peer, data)
            elif t == "lw":
                self._friend_levels_watch_in(peer, data)
            elif t == "oth":
                self._friend_others_in(peer, data)
            elif t == "shk":
                self._friend_shock_in(peer, data)
            elif t == "stp":
                self._friend_stop_in(peer, data)
            elif t == "pbd":
                self._their_board_in(peer, data)
            elif t == "pv":
                self._their_values_in(peer, data)
            elif t in _OWNER_KINDS:
                handler = getattr(self, _OWNER_KINDS[t], None)
                if handler is not None:
                    handler(peer, data)
            return
        if kind == "request":
            self._friend_requests = {**self._friend_requests, peer: data or ""}
            self._friends_note("{who} asks to be your friend", who=peer,
                               name=proto.display_name(data, peer), op="ask", dir=event_log.IN)
        elif kind == "request_over":
            self._friend_requests = {k: v for k, v in self._friend_requests.items() if k != peer}
        elif kind in ("linked", "nick", "removed", "version"):
            self.thread_queue.put(("friends", (kind, (peer, data or ""))))
        elif kind == "unlinked":
            self._drop_friend_state(peer)
            still = peer in self._friend_perms or self._demo_of("friend", peer) is not None
            if data != "removed" and still:     # unfriending says so itself, both ways
                word = {"bye": "closed OGP", "timeout": "connection lost"}.get(data, "disconnected")
                self._friends_note(f"{{who}} went offline ({word})", who=peer, op="offline")
        elif kind == "declined":
            self._friends_note("{who} declined", who=peer, op="decline")
        elif kind == "gave_up":
            self._friends_note("{who} never answered - ask again when they're online",
                               who=peer, op="ask")
        self.thread_queue.put(("friends", ("refresh", None)))

    def _friends_status_for(self, peer: str) -> Optional[Dict[str, Any]]:
        perms = self._friend_perms.get(peer)
        st = self._my_state
        if not perms or not st:
            return None
        prm_for = getattr(self, "_params_prm_for", None)
        # Their panel shows each shocker's own caps and switches -- the same
        # for every friend (the Shockers page's)
        # not in your instance: refused like Pause, and told that's why --
        # never where you are (friends_instance.py)
        not_here = peer in self._not_here
        return proto.make_status(
            st["toys"], st["outputs"] if self._sends_levels(peer, perms) else {},
            st["strength"], st["off"],
            self.friends_settings.get_paused() or not_here, perms[0],
            perms[1] and self._shockers_shared(),
            st["shockers"], st["armed"], st["max_intensity"], st["max_pulse_ms"],
            st.get("max_vibrate", 0) or st["max_intensity"], st.get("max_hold_s", 0.0),
            prm=prm_for(peer) if prm_for is not None else None,
            batteries=st.get("batteries"), shocker_caps=st.get("shocker_caps") or [],
            shocker_ops=st.get("shocker_ops") or [],
            shocker_off=st.get("shocker_off"), not_here=not_here)

    def _sends_levels(self, peer: str, perms: tuple) -> bool:
        """Your toys' live levels: moving toys change them every tick, which
        makes the status go out four times a second -- so only to a friend
        who may drive them and has your panel open, or whose older OGP
        can't say so (`lw`, protocol 2)."""
        if not perms[0]:
            return False
        if peer != ME:
            version = getattr(self.friends_link, "peer_version", None)
            if version is not None and version(peer) < proto.LEVELS_SINCE:
                return True
        t = self._level_watchers.get(peer)
        return t is not None and time.monotonic() - t < proto.WATCH_STALE_S

    def _friend_levels_watch_in(self, peer: str, msg: Dict[str, Any]) -> None:
        """A friend's page shows your panel now -- or stopped showing it."""
        if proto.read_levels_watch(msg):
            self._level_watchers = {**self._level_watchers, peer: time.monotonic()}
        elif peer in self._level_watchers:
            self._level_watchers = {k: v for k, v in self._level_watchers.items() if k != peer}

    def _friends_more_for(self, peer: str) -> Dict[str, Dict[str, Any]]:
        """Avatar boards: yours for a friend who has it open, your look at
        theirs, the buttons you hold on it."""
        out = self._friends_params_more_for(peer)
        mine = getattr(self, "_params_more_for", None)
        if mine is not None:
            out.update(mine(peer))
        out.update(self._friends_sync_more_for(peer))
        out.update(self._friends_levels_watch_more_for(peer))
        return out

    # ------------------------------------------------------------------
    # GUI thread
    # ------------------------------------------------------------------

    def _friends_on_queue(self, kind: str, data: Any) -> None:
        """thread_queue messages ("friends", (kind, data)) — GUI thread."""
        if self._web_on_queue(kind, data):
            pass
        elif kind == "linked":
            peer, nick = data
            if peer not in self.friends_settings.friend_ids():
                # We asked them, they accepted -- or their invite let us in.
                self.friends_settings.add_friend(peer, nick)
                self._friends_contacts_changed()
                if peer in self._invite_nicks:
                    self.set_friends_selected("friend", peer)    # their panel, ready to go
                self._friends_note("You and {who} are friends now", who=peer,
                                   name=proto.display_name(nick, peer), op="accept")
            elif nick:
                self.friends_settings.set_nick_of(peer, nick)
            self._friends_note("{who} is online", who=peer, op="online")
        elif kind == "nick":
            peer, nick = data
            old = self._friend_nick(peer)
            self.friends_settings.set_nick_of(peer, nick)
            if nick and nick != old:
                self._friends_note(f"{old} is now called {{who}}", who=peer, name=nick,
                                   op="rename")
        elif kind == "version":
            self._friend_version_heard(*data)
        elif kind == "removed":
            peer, _ = data
            if peer in self.friends_settings.friend_ids():
                nick = self._friend_nick(peer)
                self._menu_retarget(lambda: self.friends_settings.remove_friend(peer, unfriended=False))
                self._friends_contacts_changed()
                self._drop_friend_state(peer)
                self._friends_note("{who} unfriended you", who=peer, name=nick, op="unfriend",
                                   dir=event_log.IN)
        elif kind == "open_link":
            self.friends_open_link(data)
        elif kind == "elsewhere_gone" and self._friends_elsewhere:
            self._friends_claim_pipe()          # nobody listens now: no wait
            if not self._friends_elsewhere:
                self._friends_note("Your other OGP window closed - Friends runs here now",
                                   op="online")
                self._friends_maybe_start()
        elif kind == "invite_used":
            peer, code, nick = data
            self.friends_settings.use_invite(code)
            if peer not in self.friends_settings.friend_ids():
                self.friends_settings.add_friend(peer, nick)
                self._friends_contacts_changed()
                self._friends_note("{who} joined with your invite link - you're friends now",
                                   who=peer, name=proto.display_name(nick, peer), op="accept",
                                   dir=event_log.IN)
        elif kind == "strength":
            peer, value = data
            with self._str_lock:     # the newest that came meanwhile (friends_receive)
                value = self._friend_str_pending.pop(peer, value)
            perms = self._friend_perms.get(peer)
            if (perms and perms[0] and not self.friends_settings.get_paused()
                    and peer not in self._not_here):
                self.set_strength(value, source="friend")
                pct = round(value * 100)
                self._friends_note(f"{{who}} set your strength to {pct} %", key=("str-in", peer),
                                   who=peer, kind=TOYS, op="strength", dir=event_log.IN,
                                   level=pct)
        self._friends_refresh_ui()

    def _friends_debug(self, text: str) -> None:
        """The debug log only (ogp_debug.log): how the links are doing."""
        try:
            debug_log.get_logger("friends").info(text)
        except Exception:
            pass

    def _friends_tick(self) -> None:
        try:
            self._my_state = self._build_my_state()
            now = time.monotonic()
            # This tick runs on the GUI thread every _TICK_MS: a long gap means
            # the app itself was busy (friends' toys follow from here too).
            gap = now - self._tick_at if self._tick_at else 0.0
            self._tick_at = now
            if gap >= 1.0 and now - self._tick_said >= 10.0:
                self._tick_said = now
                self._friends_debug(f"Friends: the app was busy for {gap:.1f} s")
            self._instance_refresh()        # who is in your instance (friends_instance)
            self._pump_friend_holds(now)
            self._me_tick()
            self._note_avatar_menu()
            if self._friends_elsewhere and now - self._elsewhere_checked > 5.0:
                # off the GUI thread: a hung other window must not freeze this one
                self._elsewhere_checked = now
                threading.Thread(target=self._friends_check_elsewhere, daemon=True,
                                 name="friends-elsewhere").start()
            for peer in self.friends_settings.friend_ids() + list(self._web_guests):
                driving = self._is_driving(peer, now)
                if driving != self._friend_driving.get(peer, False):
                    self._friend_driving[peer] = driving
                    self._note_drive_change(peer, driving, now)
        except Exception as e:
            self.log_message(f"Friends tick failed: {e}")
        finally:
            ui = getattr(self, "ui", None)
            if ui is not None:
                ui.schedule_callback(_TICK_MS, self._friends_tick)

    def _note_drive_change(self, peer: str, driving: bool, now: float) -> None:
        """Started / stopped driving -- or, when their updates just stopped
        arriving while they drove, a drop-out (and how long it lasted)."""
        nick = self._friend_nick(peer)
        d = self._friend_drive.get(peer)
        if not driving and d is not None and (d.pat or any(v > 0 for v in d.levels.values())):
            # still driving as far as they know: nothing came for DRIVE_STALE_S
            self._friend_dropped[peer] = d.t
            self._friends_note(f"{{who}}'s control dropped out - nothing came for "
                               f"{proto.DRIVE_STALE_S:.0f} s (connection)", key=("drop", peer),
                               who=peer, name=nick, kind=TOYS, op="dropout", dir=event_log.IN)
            self._friends_debug(f"Friends: {nick}'s drive went quiet ({now - d.t:.1f} s "
                                "since their last update)")
            return
        quiet_since = self._friend_dropped.pop(peer, None)
        if driving and quiet_since is not None and d is not None:
            # the first update after the gap set d.t: the gap is d.t - quiet_since
            back = max(0.0, d.t - quiet_since)
            self._friends_note(f"{{who}}'s control is back after {back:.1f} s",
                               key=("drop", peer), who=peer, name=nick, kind=TOYS, op="back",
                               dir=event_log.IN, ms=round(back * 1000))
            self._friends_debug(f"Friends: {nick}'s drive is back after {back:.1f} s quiet")
            return
        self._friends_note(f"{{who}} {'started' if driving else 'stopped'} driving your toys",
                           who=peer, name=nick, kind=TOYS, op="start" if driving else "stop",
                           dir=event_log.IN)

    def _build_my_state(self) -> Dict[str, Any]:
        engine = getattr(self, "haptic_engine", None)
        counts: Dict[str, int] = {}
        if engine is not None and getattr(engine, "is_connected", False):
            try:
                counts = dict(engine.get_motor_count_map() or {})
            except Exception:
                counts = {}
        router = getattr(self, "motor_router", None)
        last = dict(getattr(router, "last_outputs", {}) or {}) if router is not None else {}
        outputs: Dict[str, float] = {}
        for (name, _motor), value in last.items():
            if name in counts:
                outputs[name] = max(outputs.get(name, 0.0), float(value or 0.0))
        shockers: List[str] = []
        caps: List[tuple] = []
        ops: List[int] = []         # what each one's switches let through now
        off: List[int] = []         # what is switched off on each one's card
        armed, max_int, max_ms, max_vib, max_hold = False, 0, 0, 0, 0.0
        eng = getattr(self, "pishock_engine", None)
        if eng is not None and self.get_feature_enabled("feature_pishock") and eng.is_connected:
            listed = eng.shockers()[:proto.MAX_SHOCKERS]
            shockers = [shocker_label(s) for s in listed]
            armed = bool(eng.is_armed)
            lim = eng.limits()
            # the friends' own longest hold while limits are separate
            timing = getattr(eng, "timing_for", None)
            max_hold = float((timing(GROUP_FRIENDS) if callable(timing) else lim)
                             .get("max_hold_s", 0.0))
            # each shocker's caps as friends get them (its own, lowered to
            # the friends' while limits are separate); the hub-wide "max_*"
            # a copy from before per-shocker caps reads are the highest
            for s in listed:
                own = eng.limits_for(s["id"], group=GROUP_FRIENDS)
                caps.append((int(own["max_intensity"]), int(own["max_vibrate"]),
                             int(own["max_pulse_ms"])))
                ops.append(proto.ops_mask([op for op in proto.OPS
                                           if eng.op_allowed(s["id"], op)]))
                off.append(proto.ops_mask(eng.ops_off().get(s["id"], ())))
            pick = caps or [(int(lim["max_intensity"]), int(lim.get("max_vibrate", 1)),
                             int(lim["max_pulse_ms"]))]
            max_int, max_vib, max_ms = (max(c[i] for c in pick) for i in range(3))
        batteries = getattr(self, "_toy_batteries", {}) or {}
        # your toys in Home's order (connection order): the menu's Which
        # toys 1-4 and their panel then number them as your Home does
        get_order = getattr(self, "get_connected_toys_in_order", None)
        rank = {n: i for i, n in enumerate((get_order() if callable(get_order) else None) or ())}
        return {
            "toys": sorted(counts.items(), key=lambda kv: (rank.get(kv[0], len(rank)), kv[0])),
            "batteries": {n: batteries[n] for n in counts if n in batteries},
            "outputs": outputs,
            "strength": float(self.get_strength()),
            "off": bool(self.is_output_off()),
            "shockers": shockers,
            "armed": armed,
            "max_intensity": max_int,
            "max_pulse_ms": max_ms,
            "max_vibrate": max_vib,
            "max_hold_s": max_hold,
            "shocker_caps": caps,
            "shocker_ops": ops,
            "shocker_off": off,
        }

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _friends_rebuild_perms(self) -> None:
        friends = self.friends_settings.get_friends()
        perms = {f["id"]: (f["toys"], f["shock"], f["params"]) for f in friends}
        perms[ME] = (True, True, True)          # you allow yourself everything
        with self._web_lock:
            perms.update(self._web_perms())     # browsers on the web remote: toys only
            self._friend_perms = perms
        # who may drive you may have changed: who is not here too
        self._instance_refresh()

    def _friends_contacts_changed(self) -> None:
        self._friends_rebuild_perms()
        self.friends_link.set_unfriended(self.friends_settings.get_unfriended())
        self.friends_link.set_contacts(self.friends_settings.friend_ids())

    def _drop_friend_state(self, peer: str) -> None:
        self._drop_drive(peer)
        self._drop_shocks(peer)
        self._drop_their_board(peer)
        drop = getattr(self, "_params_drop_friend", None)
        if drop is not None:
            drop(peer)
        self._friend_status = {k: v for k, v in self._friend_status.items() if k != peer}
        self._my_levels = {k: v for k, v in self._my_levels.items() if k != peer}
        self._my_strength = {k: v for k, v in self._my_strength.items() if k != peer}
        self._my_override = {k: v for k, v in self._my_override.items() if k != peer}
        self._my_patterns = {k: v for k, v in self._my_patterns.items() if k != peer}
        self._my_holds = {k: v for k, v in self._my_holds.items() if k != peer}
        self._my_pseq = {k: v for k, v in self._my_pseq.items() if k != peer}
        self._friend_others = {k: v for k, v in self._friend_others.items() if k != peer}
        self._oth_told.discard(peer)
        self._level_watchers = {k: v for k, v in self._level_watchers.items() if k != peer}

    def _demo_of(self, kind: str, sid: str):
        """The example friends (OGP_FRIENDS_DEMO=1) when `sid` is one of
        their friends or groups -- the page only, never the network."""
        demo = getattr(self, "_demo", None)
        return demo if demo is not None and demo.has(kind, sid) else None

    def _friend_nick(self, peer: str) -> str:
        if peer == ME:
            return "You (Me)"
        web = self._web_nick(peer)
        if web is not None:
            return web
        demo = self._demo_of("friend", peer)
        if demo is not None:
            return demo.nick(peer)
        f = self.friends_settings.get_friend(peer)
        if f and f["nick"]:
            return f["nick"]
        nick = self.friends_link.peers().get(peer, {}).get("nick") if hasattr(self, "friends_link") else ""
        return proto.display_name(nick or self._friend_requests.get(peer), peer)

    def _friends_note(self, text: str, key: Any = None, *, who: Optional[str] = None,
                      name: Optional[str] = None, role: Optional[str] = None,
                      kind: str = LINK, op: str = "", dir: str = "",
                      level: Optional[int] = None, ms: Optional[int] = None,
                      on: Any = (), held: str = "", asked: str = "",
                      via: Optional[str] = None, asked_level: Optional[int] = None,
                      asked_ms: Optional[int] = None, fixed: str = "") -> None:
        """One entry in the log (and a line in the system log): who did it
        (a peer's ID, Me, a web guest, event_log.group_key(gid); None: you
        on the page), what (`kind`, `op`, `dir` -- IN to you, OUT by you --
        `level`, `ms`, the shockers `on`), why it was held back, and what it
        came through (`via`; None: friends_common.came_through's, if any).
        A value corrected on its way out: `level` / `ms` are what went out,
        `asked_level` / `asked_ms` what was asked (the line says those) and
        `fixed` why (event_log.Event.correction).

        `text` is the line, with `{who}` where the person's name goes: the
        name comes from the record (`name`, else their nickname now). An
        entry with the same `key` within event_log.COALESCE_S replaces the
        one before it, so a slider drag is one entry."""
        if who is None or who == event_log.YOU:
            who, name, role = event_log.YOU, event_log.YOU_NAME, event_log.ROLE_YOU
        else:
            role = role or self._log_role(who)
            if name is None:
                name = (self._group_name(who[len(event_log.GROUP_PREFIX):])
                        if role == event_log.ROLE_GROUP else self._friend_nick(who))
        line = text.replace("{who}", name)
        ev = event_log.Event(time.time(), line, who, name, role, kind, op, dir, level, ms,
                             tuple(on or ()), held, asked,
                             coming_through() if via is None else via,
                             asked_level, asked_ms, fixed)
        if self.event_log.add(ev, key):
            fix = ev.correction
            self.thread_queue.put(("ui_update", f"Friends: {line}" + (f" ({fix})" if fix else "")))

    def _log_role(self, who: str) -> str:
        """What kind of person `who` is, for the log."""
        if who == ME:
            return event_log.ROLE_ME
        if who.startswith(event_log.GROUP_PREFIX):
            return event_log.ROLE_GROUP
        if who in getattr(self, "_web_guests", {}):
            return event_log.ROLE_WEB
        return event_log.ROLE_FRIEND

    def _friends_refresh_ui(self) -> None:
        ui = getattr(self, "ui", None)
        refresh = getattr(ui, "refresh_friends", None) if ui is not None else None
        if refresh is not None:
            refresh()


def _friends_entry(ev: "event_log.Event") -> bool:
    """On the Friends page's log: everyone but your own avatar's behaviours
    (those are on the Log page)."""
    return ev.role != event_log.ROLE_AVATAR


# A friend's messages about YOUR board, handled by ParamsFacade (``pht``:
# your height, its Height box -- height_facade.py).
_OWNER_KINDS = {"pw": "_params_on_watch", "pst": "_params_on_set", "ph": "_params_on_holds",
                "pht": "_height_on_set"}
_PERM_AT = {"toys": 0, "shock": 1, "params": 2}
# What only an OGP whose toys you drive sends -- never the web remote page
# (docs/assets/remote.js sends hello, lw, cmd, shk, stp, pw, pst, ph, pht).
_NEVER_FROM_A_BROWSER = frozenset({"st", "pnl", "oth", "pbd", "pv"})

_INVITE_WORDS = {
    "once": "it works once, within a day",
    "day": "anyone can join with it for a day",
    "week": "anyone can join with it for a week",
    "forever": "anyone can join with it until you close your links",
}
