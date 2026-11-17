"""Friends settings: your own nickname, your contact list, your groups of
friends and what each friend may do to you.

  * ``nickname``  — what your friends see you as. Required before the link
    goes online at all.
  * ``online``    — the Online switch: off, Friends uses no network at
    all (nobody can reach you, you reach nobody).
  * ``paused``    — "Pause all friends": nothing a friend sends reaches a
    toy or a shocker while it is on.
  * ``instance_only`` — "Only friends in my instance": while it is on, a
    friend whose linked VRChat account isn't in your instance (by your own
    log) is refused like Pause -- off by default
    (controllers/friends_instance.py).
  * ``sync``      — Sync with others: everyone driving your toys shares one
    set of toy cards and the newest change plays -- or, off, each drives
    on their own and the highest wins. Yours alone to choose, for every
    friend, the web remote and Me alike; on by default (Blise's call,
    2026-11-17). A friend's old per-friend ``sync`` is kept but no longer used.
  * ``friends``   — one entry per friend: ``id`` (their link ID), ``nick``
    (the nickname they gave themselves, refreshed whenever they connect),
    ``toys`` (they may drive your toys and move your strength slider) and
    ``shock`` (they may fire your shockers — on for a new friend, like
    toys, because that is what people link for; a shock still only shocks
    while you have armed shocks on the Shockers page this session, and
    always within your caps there) and ``params`` (they see your worn
    avatar's board from the Avatar Remote page and may use it -- on for a new
    friend too; a locked category stays look-only), and ``vrc`` /
    ``vrc_name``: the VRChat account you linked them to (its ``usr_`` id,
    since display names change, and the name it had then; "" for none).
    Yours alone: never sent over the link, to the web remote or anywhere
    else. One VRChat account belongs to one friend. ``anywhere``: "Allow
    from anywhere" -- this friend may drive you while "Only friends in my
    instance" is on and they aren't in it (off for a new friend).
  * ``groups``    — named sets of friends you control at once: ``id``,
    ``name``, ``members`` (friend IDs, and ``ME`` for you -- a group with
    you and a friend in it drives both of you; a friend can be in several
    groups).
  * ``selected``  — what the Friends page's control panel shows and the
    VRChat menu's Friends submenu acts on: ``{"kind": "friend"|"group",
    "id": ...}``.
  * ``unfriended`` — IDs you unfriended. When their OGP redials yours by
    itself it is told so and drops you, instead of asking to be your
    friend every session; asking on purpose (your ID pasted, your invite
    link) still reaches you. Adding them again takes them off.
  * ``invites``   — the codes in invite links you sent (``code``,
    ``kind``, ``expires`` — 0 for never — and ``uses``): whoever comes
    with a live one is accepted without asking you. A ``once`` link works
    for the first friend within a day; ``day`` / ``week`` for anyone within
    that time; ``forever`` until you close your links or get a new ID
    (INVITE_KINDS). The oldest go once there are MAX_INVITES.
  * ``web``       — your web remote: one link anyone can open in a browser
    to do what a friend can, no OGP needed (docs/remote.html). ``code`` is
    in the link ("" until you first copy it -- no Web remote row before),
    ``on`` lets browsers in, ``toys`` / ``shock`` / ``params`` are what
    everyone on it may do -- toys on, shockers and your avatar's board off
    until you tick them (Blise's call: anyone with the link gets them) --
    ``anyway``, "Allow the web remote anyway": a browser can't be in your
    instance, so "Only friends in my instance" blocks it unless this is on
    (off by default) -- and ``blocked`` the browsers you kicked.

Cleaned on the way in and on the way out, like every settings file."""

import secrets
import time
from typing import Any, Dict, List, Optional

import remote_protocol as proto
from vrchat_log import clean_display_name, clean_user_id

from ._base import JsonSettingsManager
from ._paths import FRIENDS_SETTINGS_FILE

ME = "__me__"        # you, the Friends list's Me row: a group may hold you too
MAX_FRIENDS = 32
MAX_GROUPS = 16
GROUP_NAME_MAX = 24
MAX_INVITES = 20
MAX_UNFRIENDED = 64
MAX_WEB_BLOCKED = 64
DAY_S = 24 * 3600
# kind -> (lifetime in seconds or None for no end, works only once)
INVITE_KINDS = {
    "once": (DAY_S, True),
    "day": (DAY_S, False),
    "week": (7 * DAY_S, False),
    "forever": (None, False),
}


def _clean_friend(entry: Any) -> Optional[Dict[str, Any]]:
    if not isinstance(entry, dict):
        return None
    fid = str(entry.get("id") or "").strip().lower()
    if not proto.valid_id(fid):
        return None
    try:
        added = float(entry.get("added", 0.0))
    except (TypeError, ValueError):
        added = 0.0
    vrc = clean_user_id(entry.get("vrc"))
    return {
        "id": fid,
        "nick": proto.clean_nick(entry.get("nick")),
        "toys": bool(entry.get("toys", True)),
        "shock": bool(entry.get("shock", True)),
        "params": bool(entry.get("params", True)),
        # Sync with others on their toy cards (the friend's panel)
        "sync": bool(entry.get("sync", True)),
        # (a "share" from before 2026-11-17 -- what they might do with your
        # shockers -- is left behind: every friend gets each shocker's own)
        "added": added,
        # their VRChat account (see the module docstring): never sent anywhere
        "vrc": vrc,
        "vrc_name": clean_display_name(entry.get("vrc_name")) if vrc else "",
        # "Allow from anywhere": they drive you while "Only friends in my
        # instance" is on and they aren't in it
        "anywhere": bool(entry.get("anywhere", False)),
    }


def _clean_group_name(text: Any) -> str:
    return " ".join(str(text or "").split())[:GROUP_NAME_MAX]


def _clean_web(raw: Any) -> Dict[str, Any]:
    raw = raw if isinstance(raw, dict) else {}
    code = str(raw.get("code") or "").lower()
    blocked = []
    for bid in raw.get("blocked") or []:
        bid = str(bid).strip().lower()
        if proto.valid_id(bid) and bid not in blocked:
            blocked.append(bid)
    return {
        "code": code if proto.valid_code(code) else "",
        "on": bool(raw.get("on", True)),
        "toys": bool(raw.get("toys", True)),
        "shock": bool(raw.get("shock", False)),
        "params": bool(raw.get("params", False)),
        # "Allow the web remote anyway" while only friends in your instance may
        "anyway": bool(raw.get("anyway", False)),
        "blocked": blocked[-MAX_WEB_BLOCKED:],
    }


_WHAT = {"toys": "drive your toys", "shock": "use your shockers",
         "params": "use your avatar's board"}


def history_asks(current: Dict[str, Any], target: Dict[str, Any]) -> list:
    """What an undo or redo from `current` to `target` must ask first
    (settings_history.py): anything that lets a friend -- or the web
    remote -- do more than now: Pause all friends lifted, Only friends in my
    instance switched off, a friend's Toys / Shockers / Avatar switched back
    on or their Allow from anywhere on, the web remote's link or switches
    back on or its Allow the web remote anyway on."""
    from settings_history import Ask, turned_on
    asks = []
    if current.get("paused") and not target.get("paused"):
        asks.append(Ask("confirm", "lets your friends drive you again (Pause all friends off)"))
    if current.get("instance_only") and not target.get("instance_only"):
        asks.append(Ask("confirm", "lets friends drive you from outside your VRChat instance "
                        "again (Only friends in my instance off)"))
    now = {f.get("id"): f for f in current.get("friends") or [] if isinstance(f, dict)}
    for f in target.get("friends") or []:
        old = now.get(f.get("id")) if isinstance(f, dict) else None
        if old is None:
            continue
        nick = f.get("nick") or "a friend"
        for what, words in _WHAT.items():
            if turned_on(old, f, (what,), True):
                asks.append(Ask("confirm", f"lets {nick} {words} again"))
        if turned_on(old, f, ("anywhere",)):
            asks.append(Ask("confirm", f"lets {nick} drive you from anywhere"))
    web_a, web_b = current.get("web") or {}, target.get("web") or {}
    if web_b.get("code") and turned_on(web_a, web_b, ("on",), True):
        asks.append(Ask("confirm", "lets browsers in on your web remote link again"))
    for what, words in _WHAT.items():
        if turned_on(web_a, web_b, (what,), what == "toys"):
            asks.append(Ask("confirm", f"lets the web remote {words}"))
    if turned_on(web_a, web_b, ("anyway",)):
        asks.append(Ask("confirm", "lets the web remote drive you while only friends in "
                        "your instance may"))
    return asks


class FriendsSettingsManager(JsonSettingsManager):
    HISTORY_KEY = "friends"
    HISTORY_LABEL = "Friends"

    # -- Ctrl+Z (settings_history.py) ------------------------------------------
    # Out of it: who is on the list at all (adding or unfriending a friend
    # talks to them -- that already happened), their own nicknames, invites,
    # the web remote's link and kicks, and what the page shows.

    @staticmethod
    def history_ignore(path, before, after) -> bool:
        if not path:
            return True
        head = path[0]
        if head in ("unfriended", "invites", "selected"):
            return True
        if head == "web" and len(path) >= 2 and path[1] in ("code", "blocked"):
            return True
        if head == "friends":
            return len(path) <= 2 or (len(path) >= 3 and path[2] in ("nick", "added"))
        return False

    @staticmethod
    def history_asks(current: Dict[str, Any], target: Dict[str, Any]) -> list:
        return history_asks(current, target)

    def history_describe(self, path) -> str:
        from settings_history import ById
        if not path:
            return ""
        head = path[0]
        if head == "friends" and len(path) >= 3 and isinstance(path[1], ById):
            f = self.get_friend(path[1].id) or {}
            nick = f.get("nick") or "a friend"
            what = {"toys": "Toys", "shock": "Shockers", "params": "Avatar",
                    "sync": "Sync with others",
                    "anywhere": "Allow from anywhere",
                    "vrc": "VRChat account", "vrc_name": "VRChat account"}.get(str(path[2]),
                                                                           str(path[2]))
            return f"{nick}'s {what}"
        if head == "groups" and len(path) >= 2:
            if isinstance(path[1], ById):
                g = self.get_group(path[1].id) or {}
                return f"group {g.get('name') or ''}".strip()
            return "your groups"
        if head == "web":
            return "the web remote" + (f"'s {path[1]}" if len(path) >= 2 else "")
        return {"nickname": "your nickname", "online": "Online",
                "paused": "Pause all friends",
                "instance_only": "Only friends in my instance",
                "sync": "Sync with others"}.get(str(head), "")

    DEFAULTS = {
        "nickname": "",
        "online": True,
        "paused": False,
        "instance_only": False,
        "sync": True,
        "friends": [],
        "groups": [],
        "selected": {},
        "invites": [],
        "unfriended": [],
        "web": {},
    }
    FILE_PATH = FRIENDS_SETTINGS_FILE

    def _post_load(self, loaded: Dict[str, Any]) -> None:
        self.settings["nickname"] = proto.clean_nick(self.settings.get("nickname"))
        self.settings["paused"] = bool(self.settings.get("paused"))
        self.settings["instance_only"] = bool(self.settings.get("instance_only"))
        self.settings["sync"] = bool(self.settings.get("sync", True))
        self.settings["online"] = bool(self.settings.get("online", True))
        friends, seen = [], set()
        for entry in self.settings.get("friends") or []:
            f = _clean_friend(entry)
            if f is not None and f["id"] not in seen:
                seen.add(f["id"])
                friends.append(f)
        self.settings["friends"] = friends[:MAX_FRIENDS]
        groups, gids = [], set()
        for g in self.settings.get("groups") or []:
            if not isinstance(g, dict):
                continue
            gid = str(g.get("id") or "")[:16]
            name = _clean_group_name(g.get("name"))
            if not gid or gid in gids or not name:
                continue
            gids.add(gid)
            members = [m for m in dict.fromkeys(str(m) for m in g.get("members") or [])
                       if m in seen or m == ME]
            groups.append({"id": gid, "name": name, "members": members})
        self.settings["groups"] = groups[:MAX_GROUPS]
        # Older files: "together" (several friends) or "active" (one).
        old = loaded.get("together")
        if not isinstance(old, list):
            old = [loaded["active"]] if isinstance(loaded.get("active"), str) else []
        old = [m for m in dict.fromkeys(str(m) for m in old) if m in seen]
        if "selected" not in loaded and old:
            if len(old) == 1:
                self.settings["selected"] = {"kind": "friend", "id": old[0]}
            else:
                gid = self._new_group_id()
                self.settings["groups"].append({"id": gid, "name": "Together", "members": old})
                self.settings["selected"] = {"kind": "group", "id": gid}
        self.settings.pop("together", None)
        self.settings.pop("me", None)       # "Add myself": you're always on the list now
        self.settings.pop("active", None)
        self.settings["selected"] = self._valid_selection(self.settings.get("selected"))
        self.settings["invites"] = self._live_invites(self.settings.get("invites"))
        gone = []
        for fid in self.settings.get("unfriended") or []:
            fid = str(fid).strip().lower()
            if proto.valid_id(fid) and fid not in seen and fid not in gone:
                gone.append(fid)
        self.settings["unfriended"] = gone[-MAX_UNFRIENDED:]
        self.settings["web"] = _clean_web(self.settings.get("web"))

    # nickname
    def get_nickname(self) -> str:
        return proto.clean_nick(self.settings.get("nickname"))

    def set_nickname(self, nick: str) -> str:
        self.settings["nickname"] = proto.clean_nick(nick)
        self._save()
        return self.settings["nickname"]

    # online
    def get_online(self) -> bool:
        return bool(self.settings.get("online", True))

    def set_online(self, online: bool) -> None:
        self.settings["online"] = bool(online)
        self._save()

    # pause
    def get_paused(self) -> bool:
        return bool(self.settings.get("paused"))

    def set_paused(self, paused: bool) -> None:
        self.settings["paused"] = bool(paused)
        self._save()

    # only friends in my instance
    def get_instance_only(self) -> bool:
        return bool(self.settings.get("instance_only"))

    def set_instance_only(self, on: bool) -> None:
        self.settings["instance_only"] = bool(on)
        self._save()

    # sync with others: one set of toy cards for everyone driving you
    def get_sync_all(self) -> bool:
        return bool(self.settings.get("sync", True))

    def set_sync_all(self, on: bool) -> None:
        self.settings["sync"] = bool(on)
        self._save()

    # friends
    def get_friends(self) -> List[Dict[str, Any]]:
        return [dict(f) for f in self.settings.get("friends") or []]

    def get_friend(self, fid: str) -> Optional[Dict[str, Any]]:
        for f in self.settings.get("friends") or []:
            if f["id"] == fid:
                return dict(f)
        return None

    def friend_ids(self) -> List[str]:
        return [f["id"] for f in self.settings.get("friends") or []]

    def _member_ids(self) -> set:
        """Who a group can hold: your friends, and you."""
        return set(self.friend_ids()) | {ME}

    def add_friend(self, fid: str, nick: str = "") -> bool:
        """Add (or refresh the nickname of) a friend. A new friend may drive
        your toys and fire your shockers; either switch turns off per
        friend."""
        f = _clean_friend({"id": fid, "nick": nick, "added": time.time()})
        if f is None:
            return False
        friends = self.settings.setdefault("friends", [])
        for existing in friends:
            if existing["id"] == f["id"]:
                if nick:
                    existing["nick"] = f["nick"]
                    self._save()
                return True
        if len(friends) >= MAX_FRIENDS:
            return False
        friends.append(f)
        self.settings["unfriended"] = [u for u in self.settings.get("unfriended") or []
                                       if u != f["id"]]
        if not self.settings.get("selected"):
            # your first friend: the panel and the menu work without picking
            self.settings["selected"] = {"kind": "friend", "id": f["id"]}
        self._save()
        return True

    def remove_friend(self, fid: str, unfriended: bool = True) -> None:
        """Take a friend off the list -- `unfriended` when you did it (see
        ``unfriended``), not when they unfriended you."""
        if unfriended and fid in self.friend_ids():
            gone = [u for u in self.settings.get("unfriended") or [] if u != fid]
            self.settings["unfriended"] = (gone + [fid])[-MAX_UNFRIENDED:]
        self.settings["friends"] = [f for f in self.settings.get("friends") or []
                                    if f["id"] != fid]
        for g in self.settings.get("groups") or []:
            g["members"] = [m for m in g["members"] if m != fid]
        self.settings["selected"] = self._valid_selection(self.settings.get("selected"))
        self._save()

    def get_unfriended(self) -> List[str]:
        return list(self.settings.get("unfriended") or [])

    def set_nick_of(self, fid: str, nick: str) -> None:
        for f in self.settings.get("friends") or []:
            if f["id"] == fid and f["nick"] != proto.clean_nick(nick):
                f["nick"] = proto.clean_nick(nick)
                self._save()

    def set_permission(self, fid: str, what: str, allowed: bool) -> None:
        if what not in ("toys", "shock", "params"):
            return
        for f in self.settings.get("friends") or []:
            if f["id"] == fid:
                f[what] = bool(allowed)
                self._save()

    def set_vrc_link(self, fid: str, user_id: str, name: str = "") -> bool:
        """Link a friend to their VRChat account (`user_id`, the `usr_` id;
        `name`, its display name when linked -- shown until something knows
        it better). "" unlinks. One VRChat account belongs to one friend:
        linking it here takes it off whoever had it. False when the friend
        or the id isn't one."""
        uid = clean_user_id(user_id)
        if user_id and not uid:
            return False
        friends = self.settings.get("friends") or []
        if not any(f["id"] == fid for f in friends):
            return False
        for f in friends:
            if f["id"] == fid:
                f["vrc"], f["vrc_name"] = uid, clean_display_name(name) if uid else ""
            elif uid and f.get("vrc") == uid:
                f["vrc"], f["vrc_name"] = "", ""
        self._save()
        return True

    def vrc_links(self) -> Dict[str, str]:
        """{friend id: their VRChat user id} for the friends linked."""
        return {f["id"]: f["vrc"] for f in self.settings.get("friends") or [] if f.get("vrc")}

    def set_anywhere(self, fid: str, on: bool) -> bool:
        """A friend's "Allow from anywhere". False when they aren't a friend."""
        for f in self.settings.get("friends") or []:
            if f["id"] == fid:
                if f.get("anywhere", False) != bool(on):
                    f["anywhere"] = bool(on)
                    self._save()
                return True
        return False

    def anywhere_ids(self) -> set:
        """The friends allowed from anywhere."""
        return {f["id"] for f in self.settings.get("friends") or [] if f.get("anywhere")}

    # groups
    def get_groups(self) -> List[Dict[str, Any]]:
        ids = self._member_ids()
        return [{"id": g["id"], "name": g["name"],
                 "members": [m for m in g["members"] if m in ids]}
                for g in self.settings.get("groups") or []]

    def get_group(self, gid: str) -> Optional[Dict[str, Any]]:
        return next((g for g in self.get_groups() if g["id"] == gid), None)

    def _new_group_id(self) -> str:
        taken = {g["id"] for g in self.settings.get("groups") or []}
        while True:
            gid = secrets.token_hex(4)
            if gid not in taken:
                return gid

    def add_group(self, name: str, members: Optional[List[str]] = None) -> Optional[str]:
        name = _clean_group_name(name)
        groups = self.settings.setdefault("groups", [])
        if not name or len(groups) >= MAX_GROUPS:
            return None
        ids = self._member_ids()
        gid = self._new_group_id()
        groups.append({"id": gid, "name": name,
                       "members": [m for m in dict.fromkeys(members or []) if m in ids]})
        self._save()
        return gid

    def rename_group(self, gid: str, name: str) -> None:
        name = _clean_group_name(name)
        for g in self.settings.get("groups") or []:
            if g["id"] == gid and name:
                g["name"] = name
                self._save()

    def delete_group(self, gid: str) -> None:
        self.settings["groups"] = [g for g in self.settings.get("groups") or []
                                   if g["id"] != gid]
        self.settings["selected"] = self._valid_selection(self.settings.get("selected"))
        self._save()

    def set_member(self, gid: str, fid: str, on: bool) -> None:
        if fid not in self._member_ids():
            return
        for g in self.settings.get("groups") or []:
            if g["id"] == gid:
                members = [m for m in g["members"] if m != fid]
                if on:
                    members.append(fid)
                g["members"] = members
                self._save()

    # what the panel shows and the VRChat menu acts on
    def _valid_selection(self, sel: Any) -> Dict[str, str]:
        ids = self.friend_ids()
        if isinstance(sel, dict):
            kind, sid = sel.get("kind"), str(sel.get("id") or "")
            if kind == "friend" and sid in ids:
                return {"kind": "friend", "id": sid}
            if kind == "group" and any(g["id"] == sid for g in self.settings.get("groups") or []):
                return {"kind": "group", "id": sid}
        return {"kind": "friend", "id": ids[0]} if ids else {}

    def get_selected(self) -> Dict[str, str]:
        return self._valid_selection(self.settings.get("selected"))

    def set_selected(self, kind: str, sid: str) -> bool:
        sel = self._valid_selection({"kind": kind, "id": sid})
        if sel.get("id") != sid:
            return False
        self.settings["selected"] = sel
        self._save()
        return True

    def targets(self) -> List[str]:
        """The friends the selection stands for: one friend, or a group's
        members."""
        sel = self.get_selected()
        if sel.get("kind") == "friend":
            return [sel["id"]]
        if sel.get("kind") == "group":
            g = self.get_group(sel["id"])
            return list(g["members"]) if g else []
        return []

    # invite links
    @staticmethod
    def _live_invites(raw: Any, now: Optional[float] = None) -> List[Dict[str, Any]]:
        now = time.time() if now is None else now
        out = []
        for inv in raw if isinstance(raw, list) else []:
            if not isinstance(inv, dict):
                continue
            code = str(inv.get("code") or "").lower()
            kind = inv.get("kind", "once")
            try:
                expires = float(inv.get("expires", 0))
                uses = max(0, int(inv.get("uses", 0)))
            except (TypeError, ValueError):
                continue
            if kind not in INVITE_KINDS or INVITE_KINDS[kind][0] is not None and expires <= now:
                continue
            if proto.valid_code(code):
                out.append({"code": code, "kind": kind,
                            "expires": expires if INVITE_KINDS[kind][0] is not None else 0.0,
                            "uses": uses})
        return out[-MAX_INVITES:]

    def new_invite(self, kind: str = "once", now: Optional[float] = None) -> str:
        if kind not in INVITE_KINDS:
            kind = "once"
        now = time.time() if now is None else now
        life = INVITE_KINDS[kind][0]
        code = secrets.token_hex(8)
        invites = self._live_invites(self.settings.get("invites"), now)
        invites.append({"code": code, "kind": kind,
                        "expires": now + life if life is not None else 0.0, "uses": 0})
        self.settings["invites"] = invites[-MAX_INVITES:]
        self._save()
        return code

    def invite_kind(self, code: str, now: Optional[float] = None) -> Optional[str]:
        """The kind of a live invite code, or None when it isn't one."""
        code = str(code or "").lower()
        for inv in self._live_invites(self.settings.get("invites"), now):
            if inv["code"] == code:
                return inv["kind"]
        return None

    def invite_valid(self, code: str, now: Optional[float] = None) -> bool:
        return self.invite_kind(code, now) is not None

    def use_invite(self, code: str) -> None:
        """Someone came with `code`: a once link is spent, others count."""
        code = str(code or "").lower()
        out = []
        for inv in self._live_invites(self.settings.get("invites")):
            if inv["code"] == code:
                if INVITE_KINDS[inv["kind"]][1]:
                    continue
                inv["uses"] += 1
            out.append(inv)
        self.settings["invites"] = out
        self._save()

    def get_invites(self) -> List[Dict[str, Any]]:
        """The live invites, without their codes: kind, expires, uses."""
        return [{k: inv[k] for k in ("kind", "expires", "uses")}
                for inv in self._live_invites(self.settings.get("invites"))]

    def close_invites(self) -> None:
        self.settings["invites"] = []
        self._save()

    def forget_everyone(self) -> None:
        """A new ID: no friends, groups, selection, invites or web remote left."""
        self.settings.update(friends=[], groups=[], selected={}, invites=[], unfriended=[],
                             web=_clean_web({}))
        self._save()

    # the web remote
    def get_web(self) -> Dict[str, Any]:
        web = _clean_web(self.settings.get("web"))
        return {**web, "blocked": list(web["blocked"])}

    def _set_web(self, **changes: Any) -> None:
        self.settings["web"] = _clean_web({**self.get_web(), **changes})
        self._save()

    def web_code(self, make: bool = False) -> str:
        """The code in your web remote link -- with `make`, a new one when
        there is none yet (the first copy, which also lets browsers in)."""
        code = self.get_web()["code"]
        if not code and make:
            code = secrets.token_hex(8)
            self._set_web(code=code, on=True)
        return code

    def new_web_code(self) -> str:
        """A new link: the old one stops working."""
        code = secrets.token_hex(8)
        self._set_web(code=code)
        return code

    def set_web_on(self, on: bool) -> None:
        self._set_web(on=bool(on))

    def set_web_permission(self, what: str, on: bool) -> None:
        """What everyone on the web remote may do: "toys", "shock" or "params"."""
        if what in ("toys", "shock", "params"):
            self._set_web(**{what: bool(on)})

    def set_web_anyway(self, on: bool) -> None:
        """"Allow the web remote anyway" while only friends in your instance may."""
        self._set_web(anyway=bool(on))

    def web_block(self, browser_id: str) -> None:
        blocked = [b for b in self.get_web()["blocked"] if b != browser_id]
        self._set_web(blocked=blocked + [str(browser_id).lower()])

    def forget_web(self) -> None:
        """No web remote: the link stops working and its row goes."""
        self.settings["web"] = _clean_web({})
        self._save()
