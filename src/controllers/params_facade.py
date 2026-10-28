"""Params facade mixin — the Avatar Remote page (VRC Parameter Relay's
board, inside OGP) and your side of sharing it with friends.

Behind `feature_params` (Settings → Features, off by default). The page
builds boards of controls for your avatar parameters, per avatar
(param_board.BoardBook, kept in settings/param_boards.py); a control on the
worn avatar's board sends to VRChat as you use it.

Friends: everyone whose third switch (AVATAR) is on in the friends list (on
for a new friend) sees your *worn* avatar's active preset -- whatever you have open
here -- and may use it, except a locked category. With ⚡ YOLO they get
every parameter (VRChat's own built-ins aside) and locks don't hold for
them. "Pause all friends" blocks everything they send and lets go of what
they hold (the page's own ■ STOP is gone, Blise's call 2026-10-27: each
friend's AVATAR switch and Pause cover it). What goes
over the link, and when, is in remote_params.py: nothing until a friend
has your board open.

Threads: the link thread asks `_params_prm_for` / `_params_more_for` what
to send and hands over what friends sent (`_params_on_watch`,
`_params_on_set`, `_params_on_holds`). Those read `_params_share` -- a
snapshot the GUI thread swaps whole after every change -- and the
parameter store (locked), and send straight to VRChat (no queue hop). The
board itself is only touched on the GUI thread.

Assumes the host controller has `self.thread_queue`, `self.ui`,
`self.log_message`, `self.get_feature_enabled`, `self.osc_manager`,
`self.get_current_avatar_id`, and the Friends facade (`friends_link`,
`_friend_perms`, `friends_settings`, `_friends_note`, `_friend_nick`).
"""

import glob
import json
import os
import threading
import time
from typing import Any, Dict, List, Optional, Tuple

import param_board as pb
import remote_params as rp
import vrchat_avatars
from parameter_store import store
from settings.param_boards import ParamBoardsSettingsManager

FEATURE_KEY = "feature_params"
_TICK_MS = 100
_TYPES_EVERY_S = 1.0        # how often the worn avatar's parameter list is compared
_BLOB_RETRY_S = 3.0         # a watcher still on another version gets the board again
# ⚡ YOLO's every-parameter list: its values (past the board's own) are read
# at most this often for friends -- a fast-moving parameter in a list of
# hundreds must not go out four times a second. The board stays live.
_ALL_VALUES_S = 1.0
_OSC_TAGS = {"Bool": "T", "Int": "i", "Float": "f"}

# What the page may change on the book (params_edit) -- every one saves
# the avatar's profile and rebuilds what friends see.
_EDITS = frozenset({
    "rename_avatar", "add_control", "update_control", "remove_control", "move_control",
    "add_category", "move_category", "rename_category", "set_category_locked",
    "set_category_color", "remove_category", "add_preset", "rename_preset",
    "remove_preset", "switch_preset", "copy_category_to_preset",
})

_QUIET_EDITS = frozenset({"rename_category", "set_category_locked"})

_NO_SHARE = {"ver": "", "msg": None, "controls": {}, "types": {}, "keys": [],
             "n_board": 0, "yolo": False, "avatar": ""}


def relay_data_dir() -> str:
    """Where VRC Parameter Relay keeps its boards."""
    base = os.environ.get("APPDATA") or os.path.join(os.path.expanduser("~"), ".config")
    return os.path.join(base, "VRCParameterRelay", "avatars")


def read_relay_boards(folder: Optional[str] = None) -> List[Dict[str, Any]]:
    """The Relay's avatars/*.json as OGP profiles (read only -- its files
    are never touched)."""
    out = []
    for path in sorted(glob.glob(os.path.join(folder or relay_data_dir(), "*.json"))):
        try:
            with open(path, "r", encoding="utf-8") as fh:
                profile = pb.relay_profile(json.load(fh))
        except (OSError, ValueError):
            continue
        if profile is not None:
            out.append(profile)
    return out


class ParamsFacade:
    """Mixin: the Avatar Remote page's controller surface, and the owner's
    half of a friend's board."""

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def _params_init(self) -> None:
        self.params_settings = ParamBoardsSettingsManager()
        self._params_book = pb.BoardBook(self.params_settings,
                                         self.params_settings.get_last_avatar() or None)
        self._params_share: Dict[str, Any] = dict(_NO_SHARE)
        self._params_lock = threading.Lock()
        # guarded by _params_lock: the link thread and the GUI tick both change them
        self._params_watchers: Dict[str, Dict[str, Any]] = {}  # peer -> {have, yolo, t, epoch}
        self._params_epoch = 0
        self._params_blob_sent: Dict[str, Tuple[str, float]] = {}
        self._params_seen: Dict[tuple, int] = {}               # (peer, target) -> newest set id
        self._params_held: Dict[str, Dict[str, Any]] = {}      # peer -> {control id: control}
        self._params_held_t: Dict[str, float] = {}
        self._params_types_at = 0.0
        self._params_tick_running = False
        # the every-parameter list's values, one snapshot for every friend
        # watching: (board version, when, {name: value}) -- the link's thread
        self._params_rest: Tuple[str, float, Dict[str, Any]] = ("", 0.0, {})

    def _params_ui_ready(self) -> None:
        if self._params_tick_running or getattr(self, "ui", None) is None:
            return
        self._params_tick_running = True
        self._params_sync_avatar()
        self._params_rebuild_share()
        self.ui.schedule_callback(_TICK_MS, self._params_tick)

    def _params_feature_changed(self, enabled: bool) -> None:
        if not enabled:
            self._params_release_all()
            with self._params_lock:
                self._params_watchers = {}
        self._params_rebuild_share()
        self.log_message("Avatar Remote on" if enabled else
                         "Avatar Remote off - friends no longer see your avatar's board")
        self._params_refresh_ui(rebuild=True)

    def _params_shutdown(self) -> None:
        if hasattr(self, "_params_book"):
            self._params_release_all()

    def _params_enabled(self) -> bool:
        return bool(self.get_feature_enabled(FEATURE_KEY))

    # ------------------------------------------------------------------
    # The page
    # ------------------------------------------------------------------

    def get_params_status(self) -> Dict[str, Any]:
        book = self._params_book
        osc = getattr(self, "osc_manager", None)
        with self._params_lock:
            watchers = sorted(self._friend_nick(p) for p in self._params_watchers)
        return {
            "enabled": self._params_enabled(),
            "vrchat": bool(osc is not None and getattr(osc, "is_connected", False)),
            "avatar_id": book.avatar_id,
            "avatar_name": book.avatar_name,
            "live_avatar_id": book.live_avatar_id,
            "is_live": book.is_live,
            "board": book.board,
            "presets": book.list_presets(),
            "yolo": self.params_settings.get_yolo(),
            "watchers": watchers,
            "friends_on": bool(self.get_feature_enabled("feature_friends")),
        }

    def params_avatars(self) -> List[Dict[str, Any]]:
        return self._params_book.list_avatars()

    def params_param_list(self) -> Dict[str, str]:
        """{name: type} of the open avatar (its live list while it is worn)."""
        return self._params_book.params()

    def params_values(self, names=None) -> Dict[str, Any]:
        """Live values (only while the open avatar is worn)."""
        if not self._params_book.is_live:
            return {}
        if names is None:
            names = self._params_book.params().keys()
        return store.get_values(names)

    def params_next_on_value(self, param: str, exclude: Optional[str] = None) -> int:
        return self._params_book.next_on_value(param, exclude)

    def params_param_type(self, name: str) -> Optional[str]:
        return self._params_book.param_type(name)

    def params_edit(self, op: str, *args, **kwargs):
        """One board edit (`op` is a BoardBook method in _EDITS). Whatever
        it returns; a change is saved and reaches friends at once."""
        if op not in _EDITS:
            raise ValueError(f"not a board edit: {op}")
        result = getattr(self._params_book, op)(*args, **kwargs)
        if result:
            self._params_changed()
        return result

    def params_edit_quiet(self, op: str, *args):
        """An edit the page already shows (a category's new name, its lock):
        saved and passed on to friends, the page left as it is."""
        if op not in _QUIET_EDITS:
            raise ValueError(f"not a quiet board edit: {op}")
        result = getattr(self._params_book, op)(*args)
        if result:
            self._params_rebuild_share()
            self._params_refresh_ui()
        return result

    def params_open_avatar(self, avatar_id: str) -> None:
        book = self._params_book
        if book.open_avatar(avatar_id):
            if book.is_live:
                self._params_sync_types(force=True)
            self.params_settings.set_last_avatar(avatar_id)
            self._params_refresh_ui(rebuild=True)

    def params_set_control(self, control_id: str, value: Any) -> bool:
        """You used a control on the page: sent while its avatar is worn
        (an avatar open for editing sends nothing)."""
        book = self._params_book
        if not book.is_live:
            return False
        control = pb.find_control(book.board, control_id)
        if control is None:
            return False
        out = pb.send_value(control, value)
        return out is not None and self._params_send(control["param"], control["ptype"], out)

    def params_set_yolo(self, on: bool) -> None:
        if bool(on) == self.params_settings.get_yolo():
            return
        self.params_settings.set_yolo(on)
        self._params_note("⚡ YOLO on - friends get every parameter, locks don't hold for them"
                          if on else "⚡ YOLO off - friends get your board only")
        self._params_rebuild_share()
        self._params_refresh_ui()

    def params_resync(self) -> None:
        """⟳ Resync: the avatar and its parameters, fetched from VRChat again."""
        osc = getattr(self, "osc_manager", None)
        if osc is None or not getattr(osc, "is_connected", False):
            return
        threading.Thread(target=self._params_refetch, daemon=True, name="params-resync").start()

    def _params_refetch(self) -> None:
        osc = self.osc_manager
        try:
            osc._do_fetch_all_parameters()
        except Exception:
            pass
        avatar_id = osc.query_avatar_id()
        if avatar_id:
            self.thread_queue.put(("avatar_change", avatar_id))

    def params_relay_import_preview(self) -> Tuple[int, int]:
        """(boards found in VRC Parameter Relay, of those already here)."""
        found = read_relay_boards()
        return len(found), sum(1 for p in found if self.params_settings.has(p["avatar_id"]))

    def params_relay_import(self, replace: bool = False) -> Tuple[int, int, int]:
        added, replaced, kept = self.params_settings.import_profiles(read_relay_boards(), replace)
        book = self._params_book
        if book.avatar_id:                      # the open avatar may have been replaced
            book.profile = book._load(book.avatar_id)
            book.board = pb.active_preset(book.profile)
            book._live_profile = None
        self.log_message(f"Avatar Remote: imported {added + replaced} board"
                         f"{'' if added + replaced == 1 else 's'} from VRC Parameter Relay"
                         + (f", kept {kept} you already had here" if kept else ""))
        self._params_changed()
        return added, replaced, kept

    # ------------------------------------------------------------------
    # VRChat: the worn avatar, its parameters, sending
    # ------------------------------------------------------------------

    def _params_avatar_changed(self, avatar_id: str) -> None:
        """GUI thread: VRChat says which avatar is worn."""
        book = getattr(self, "_params_book", None)
        if book is not None and book.avatar_changed(avatar_id):
            # its name as VRChat has it, until you give it one
            book.set_vrchat_name(self._params_vrchat_name(book.live_avatar_id))
            self.params_settings.set_last_avatar(book.avatar_id)
            self._params_release_all()
            self._params_types_at = 0.0
            self._params_sync_types(force=True)
            self._params_rebuild_share()
            self._params_refresh_ui(rebuild=True)

    def _params_vrchat_name(self, avatar_id: str) -> str:
        """The avatar's name from VRChat's OSC files ("" when there is
        none): a few KB read, once per avatar change."""
        try:
            return vrchat_avatars.avatar_name(avatar_id)
        except Exception:
            return ""

    def _params_sync_avatar(self) -> None:
        avatar_id = ""
        get = getattr(self, "get_current_avatar_id", None)
        if get is not None:
            avatar_id = get()
        osc = getattr(self, "osc_manager", None)
        if avatar_id and osc is not None and getattr(osc, "is_connected", False):
            self._params_avatar_changed(avatar_id)

    def _params_vrchat_gone(self) -> None:
        """GUI thread: the OSC link to VRChat went away -- nothing is worn."""
        book = getattr(self, "_params_book", None)
        if book is None or book.live_avatar_id is None:
            return
        self._params_release_all()
        book.avatar_gone()
        self._params_rebuild_share()
        self._params_refresh_ui(rebuild=True)

    def _params_sync_types(self, force: bool = False) -> None:
        now = time.monotonic()
        if not force and now - self._params_types_at < _TYPES_EVERY_S:
            return
        self._params_types_at = now
        book = self._params_book
        if book.live_avatar_id is None:
            return
        listed, retyped = book.sync_params(store.get_param_types())
        if listed or retyped:
            self._params_rebuild_share()
            self._params_refresh_ui(rebuild=retyped or not book.is_live, params=listed)

    def _params_send(self, name: str, ptype: str, value: Any) -> bool:
        """One parameter to VRChat, now (any thread). Shown on the page at
        once; VRChat's echo confirms it."""
        osc = getattr(self, "osc_manager", None)
        if osc is None or not getattr(osc, "is_connected", False):
            return False
        try:
            osc.send_parameter(f"/avatar/parameters/{name}", value,
                               ignore_rate_limit=True, default_type=_OSC_TAGS.get(ptype))
        except Exception:
            return False
        store.update_synthetic(name, value)
        return True

    # ------------------------------------------------------------------
    # GUI thread: what friends see
    # ------------------------------------------------------------------

    def _params_changed(self) -> None:
        self._params_rebuild_share()
        self._params_refresh_ui(rebuild=True)

    def _params_rebuild_share(self) -> None:
        """The snapshot the link thread works from: the worn avatar's
        board as friends get it. A new version goes to every watcher."""
        book = self._params_book
        board = book.live_board() if self._params_enabled() else None
        yolo = self.params_settings.get_yolo()
        if board is None:
            share = dict(_NO_SHARE, yolo=yolo)
        else:
            profile = book.live_profile()
            key = rp.avatar_key(book.live_avatar_id or "")
            msg = rp.with_version(rp.public_board(board, profile["name"], book.types, yolo, key))
            cats = {c["id"]: c["locked"] for c in board["categories"]}
            share = {
                "ver": msg["b"], "msg": msg,
                "controls": {c["id"]: (dict(c), bool(cats.get(c["cat"])))
                             for c in board["controls"]},
                "types": dict(book.types), "keys": list(msg["keys"]), "n_board": msg["nb"],
                "yolo": yolo, "avatar": key,
            }
        old = self._params_share
        self._params_share = share
        if share["ver"] and share["ver"] != old.get("ver"):
            with self._params_lock:
                peers = list(self._params_watchers)
            for peer in peers:
                self._params_send_board(peer, share, time.monotonic())

    def _params_send_board(self, peer: str, share: Dict[str, Any], now: float) -> None:
        link = getattr(self, "friends_link", None)
        if link is None or share["msg"] is None:
            return
        self._params_blob_sent[peer] = (share["ver"], now)
        link.send_blob(peer, share["msg"])
        debug = getattr(self, "_friends_debug", None)
        if debug is not None:
            debug(f"Friends: sent {self._friend_nick(peer)} your board "
                  f"({share['msg'].get('name') or 'no name'}, version {share['ver']})")

    def _params_tick(self) -> None:
        try:
            self._params_sync_types()
            now = time.monotonic()
            stale = []
            with self._params_lock:
                for peer, w in list(self._params_watchers.items()):
                    if now - w["t"] > rp.WATCH_STALE_S:
                        del self._params_watchers[peer]
                        stale.append(peer)
                for peer, t in list(self._params_held_t.items()):
                    if now - t > rp.HOLD_STALE_S:
                        stale.append(peer)
            for peer in stale:
                self._params_release(peer)
            ui = getattr(self, "ui", None)
            live = getattr(ui, "refresh_params_live", None) if ui is not None else None
            if live is not None:
                live()
        except Exception as e:
            self.log_message(f"Avatar Remote tick failed: {e}")
        finally:
            ui = getattr(self, "ui", None)
            if ui is not None:
                ui.schedule_callback(_TICK_MS, self._params_tick)

    def _params_refresh_ui(self, rebuild: bool = False, params: bool = False) -> None:
        ui = getattr(self, "ui", None)
        refresh = getattr(ui, "refresh_params", None) if ui is not None else None
        if refresh is not None:
            refresh(rebuild=rebuild, params=params or rebuild)

    def _params_note(self, text: str, key: Any = None) -> None:
        note = getattr(self, "_friends_note", None)
        if note is not None:
            note(text, key=key)
        else:
            self.log_message(f"Avatar Remote: {text}")

    # ------------------------------------------------------------------
    # The link's thread: a friend and your board
    # ------------------------------------------------------------------

    def _params_allowed(self, peer: str) -> bool:
        perms = self._friend_perms.get(peer)
        return bool(perms and len(perms) > 2 and perms[2] and self._params_enabled())

    def _params_blocked(self) -> bool:
        """Pause all friends: nothing they send reaches your avatar."""
        return bool(self.friends_settings.get_paused())

    def _params_prm_for(self, peer: str) -> Optional[Dict[str, Any]]:
        """Inside your status to `peer`: that you share a board with them."""
        if not self._params_allowed(peer):
            return None
        share = self._params_share
        return rp.make_prm(share["ver"], share["yolo"], self._params_blocked(),
                           share.get("avatar", ""))

    def _params_more_for(self, peer: str) -> Dict[str, Dict[str, Any]]:
        """The values of your board for a friend who has it open."""
        with self._params_lock:
            w = self._params_watchers.get(peer)
            w = dict(w) if w is not None else None
        share = self._params_share
        if w is None or not share["ver"] or w["have"] != share["ver"] \
                or not self._params_allowed(peer):
            return {}
        live = bool(self._params_book.live_avatar_id)
        board_keys = share["keys"][:share["n_board"]]
        got = store.get_values(board_keys) if live else {}
        keys = board_keys
        if w["yolo"] and share["yolo"]:
            keys = share["keys"]
            ver, at, rest = self._params_rest
            now = time.monotonic()
            if ver != share["ver"] or now - at >= _ALL_VALUES_S:
                rest = store.get_values(keys[len(board_keys):]) if live else {}
                self._params_rest = (share["ver"], now, rest)
            got = {**rest, **got}
        msgs = rp.make_values(share["ver"], w["epoch"], [got.get(k) for k in keys])
        return {f"pv{i}": m for i, m in enumerate(msgs)}

    def _params_on_watch(self, peer: str, msg: Dict[str, Any]) -> None:
        w = rp.read_watch(msg)
        now = time.monotonic()
        with self._params_lock:
            if w is None or not self._params_allowed(peer):
                self._params_watchers.pop(peer, None)
                return
            cur = self._params_watchers.get(peer)
            if cur is None:
                self._params_epoch += 1
                epoch = self._params_epoch
            else:
                epoch = cur["epoch"]
            self._params_watchers[peer] = {"have": w["have"], "yolo": w["yolo"], "t": now,
                                           "epoch": epoch}
        share = self._params_share
        if share["ver"] and w["have"] != share["ver"]:
            last = self._params_blob_sent.get(peer)
            if last is None or last[0] != share["ver"] or now - last[1] > _BLOB_RETRY_S:
                self._params_send_board(peer, share, now)

    def _params_on_set(self, peer: str, msg: Dict[str, Any]) -> None:
        got = rp.read_set(msg)
        if got is None:
            return
        seq, cid, pname, raw = got
        key = (peer, cid or f"p:{pname}")
        with self._params_lock:
            if seq <= self._params_seen.get(key, -1):
                return                      # a copy, or older than what landed
            self._params_seen[key] = seq
        share = self._params_share
        if not share["ver"] or not self._params_allowed(peer) or self._params_blocked():
            return
        if cid:
            entry = share["controls"].get(cid)
            if entry is None:
                return
            control, locked = entry
            if locked or control["kind"] == "button":
                return                      # look-only; a button is held, not set
            value = pb.send_value(control, raw)
            name, ptype, label = control["param"], control["ptype"], control["label"]
        else:
            ptype = share["types"].get(pname)
            if not share["yolo"] or ptype is None or not rp.settable(pname):
                return
            value = pb.any_value(ptype, raw)
            name, label, control = pname, pname, None
        if value is None or not self._params_send(name, ptype, value):
            return
        what = _said(control, ptype, value)
        self._params_note(f"{self._friend_nick(peer)} {what.format(label=label)}"
                          + ("" if cid else " (YOLO)"), key=("prm-in", peer, key[1]))

    def _params_on_holds(self, peer: str, msg: Dict[str, Any]) -> None:
        ids = set(rp.read_holds(msg))
        share = self._params_share
        ok = bool(share["ver"]) and self._params_allowed(peer) and not self._params_blocked()
        now = time.monotonic()
        pressed, let_go = [], []
        with self._params_lock:
            held = dict(self._params_held.get(peer, {}))
            for cid in list(held):
                if cid not in ids or not ok:
                    let_go.append(held.pop(cid))
            if ok:
                for cid in ids - set(held):
                    entry = share["controls"].get(cid)
                    if entry is None or entry[1] or entry[0]["kind"] != "button":
                        continue
                    held[cid] = entry[0]
                    pressed.append(entry[0])
            if held:
                self._params_held[peer] = held
                self._params_held_t[peer] = now
            else:
                self._params_held.pop(peer, None)
                self._params_held_t.pop(peer, None)
        for control in let_go:
            self._params_press(control, False)
        for control in pressed:
            if self._params_press(control, True):
                self._params_note(f"{self._friend_nick(peer)} held your {control['label']}",
                                  key=("prm-in", peer, control["id"]))

    def _params_press(self, control: Dict[str, Any], down: bool) -> bool:
        value = pb.send_value(control, down)
        return value is not None and self._params_send(control["param"], control["ptype"], value)

    def _params_release(self, peer: str) -> None:
        """Let go of whatever `peer` holds (any thread)."""
        with self._params_lock:
            held = self._params_held.pop(peer, {})
            self._params_held_t.pop(peer, None)
        for control in held.values():
            self._params_press(control, False)

    def _params_release_all(self) -> None:
        with self._params_lock:
            peers = list(self._params_held)
        for peer in peers:
            self._params_release(peer)

    def _params_drop_friend(self, peer: str) -> None:
        """A friend went offline, was unfriended or lost the switch."""
        self._params_release(peer)
        with self._params_lock:
            self._params_watchers.pop(peer, None)
            self._params_seen = {k: v for k, v in self._params_seen.items() if k[0] != peer}
        self._params_blob_sent.pop(peer, None)


def _said(control: Optional[Dict[str, Any]], ptype: str, value: Any) -> str:
    """What a set did, for the log: "turned your {label} on" ..."""
    if ptype == "Bool" or (control is not None and pb.is_int_switch(control)):
        on = pb.shows_on(control, value) if control is not None else bool(value)
        return "turned your {label} " + ("on" if on else "off")
    if ptype == "Int":
        return "set your {label} to " + str(int(value))
    return "set your {label} to " + f"{float(value):.2f}"
