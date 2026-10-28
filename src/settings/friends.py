"""Friends settings: your own nickname, your contact list, your groups of
friends and what each friend may do to you.

  * ``nickname``  — what your friends see you as. Required before the link
    goes online at all.
  * ``online``    — the Online switch: off, Friends uses no network at
    all (nobody can reach you, you reach nobody).
  * ``paused``    — "Pause all friends": nothing a friend sends reaches a
    toy or a shocker while it is on.
  * ``friends``   — one entry per friend: ``id`` (their link ID), ``nick``
    (the nickname they gave themselves, refreshed whenever they connect),
    ``toys`` (they may drive your toys and move your strength slider) and
    ``shock`` (they may fire your shockers — on for a new friend, like
    toys, because that is what people link for; a shock still only shocks
    while you have armed shocks on the Shockers page this session, and
    always within your caps there) and ``params`` (they see your worn
    avatar's board from the Avatar Remote page and may use it -- on for a new
    friend too; a locked category stays look-only).
  * ``groups``    — named sets of friends you control at once: ``id``,
    ``name``, ``members`` (friend IDs; a friend can be in several groups).
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
    and ``blocked`` the browsers you kicked.

Cleaned on the way in and on the way out, like every settings file."""

import secrets
import time
from typing import Any, Dict, List, Optional

import remote_protocol as proto

from ._base import JsonSettingsManager
from ._paths import FRIENDS_SETTINGS_FILE

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
    return {
        "id": fid,
        "nick": proto.clean_nick(entry.get("nick")),
        "toys": bool(entry.get("toys", True)),
        "shock": bool(entry.get("shock", True)),
        "params": bool(entry.get("params", True)),
        # Sync with others on their toy cards (the friend's panel)
        "sync": bool(entry.get("sync", True)),
        "added": added,
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
        "blocked": blocked[-MAX_WEB_BLOCKED:],
    }


class FriendsSettingsManager(JsonSettingsManager):
    DEFAULTS = {
        "nickname": "",
        "online": True,
        "paused": False,
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
                       if m in seen]
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

    def set_sync(self, fid: str, on: bool) -> None:
        for f in self.settings.get("friends") or []:
            if f["id"] == fid and f.get("sync", True) != bool(on):
                f["sync"] = bool(on)
                self._save()

    # groups
    def get_groups(self) -> List[Dict[str, Any]]:
        ids = set(self.friend_ids())
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
        ids = set(self.friend_ids())
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
        if fid not in self.friend_ids():
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

    def web_block(self, browser_id: str) -> None:
        blocked = [b for b in self.get_web()["blocked"] if b != browser_id]
        self._set_web(blocked=blocked + [str(browser_id).lower()])

    def forget_web(self) -> None:
        """No web remote: the link stops working and its row goes."""
        self.settings["web"] = _clean_web({})
        self._save()
