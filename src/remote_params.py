"""The Friends link's avatar-parameter messages: a friend's board of your
avatar (the Avatar Remote page, param_board.py) and what they do on it.

Light on n0's relays like the rest of the link -- nothing of this goes out
until a friend actually has your board open:

  * ``st.prm``  (you -> each friend allowed, inside the status) -- that you
    share a board: its version ``b`` ("" while you wear nothing), ``y``
    when YOLO is on, ``stop`` while you paused all friends (their page shows
    the board paused; nothing they send gets through anyway), ``a`` -- a
    short key of the avatar you wear (`avatar_key`), also in the board:
    a friend's page never shows another avatar's board as yours.
  * ``pw``      (friend -> you, a state slot) -- "I'm looking at your board
    and have version ``b``" (``y``: with YOLO's every-parameter list open),
    or ``off``. Refreshed every STATE_REFRESH_S; WATCH_STALE_S without one
    and they aren't watching any more.
  * ``pbd``     (you -> a watcher, over a stream: it is too big for a
    datagram) -- the board: categories, controls, the parameters whose
    values follow (``keys``), with YOLO the rest of the parameters
    (``all``). Sent when a watcher has another version, and again when it
    changes.
  * ``pv``      (you -> a watcher, state slots ``pv0`` ``pv1`` ...) -- the
    values of ``keys``, as many per datagram as fit. Only changes go out
    (plus the link's refresh); ``w`` changes whenever a watch starts, so a
    returning watcher gets them at once.
  * ``pst``     (friend -> you, an event sent a few times) -- set a control
    (``c``) or, with YOLO, a parameter (``p``) to ``v``. ``id`` only ever
    grows per friend: a copy, or one older than what already landed, is
    dropped.
  * ``ph``      (friend -> you, a state slot) -- the hold buttons they hold
    right now, sent every SEND_S while any is held. A hold whose friend
    stops saying so for HOLD_STALE_S is let go.

Values travel as numbers: a Bool as 1/0, a Float to two decimals (enough
for a slider; jitter below that is no change), null for one not known.
"""

import hashlib
import json
import math
from typing import Any, Dict, List, Optional, Tuple

import param_board as pb
import remote_protocol as proto

MAX_BLOB = 256 * 1024
MAX_CONTROLS = 400
MAX_CATEGORIES = 40
MAX_ALL = 1500
NAME_MAX = 200
WATCH_STALE_S = 25.0
HOLD_STALE_S = proto.DRIVE_STALE_S
CHUNK_BYTES = proto.MAX_DATAGRAM - 80      # room for the slot's own fields

# VRChat drives these itself: setting one over OSC does nothing, and the
# motion ones change every frame -- not worth a datagram. Never offered to
# a friend's YOLO list.
BUILTINS = frozenset({
    "IsLocal", "PreviewMode", "Viseme", "Voice", "GestureLeft", "GestureRight",
    "GestureLeftWeight", "GestureRightWeight", "AngularY", "VelocityX", "VelocityY",
    "VelocityZ", "VelocityMagnitude", "Upright", "Grounded", "Seated", "AFK",
    "TrackingType", "VRMode", "MuteSelf", "InStation", "Earmuffs", "IsOnFriendsList",
    "AvatarVersion", "IsAnimatorEnabled", "ScaleModified", "ScaleFactor",
    "ScaleFactorInverse", "EyeHeightAsMeters", "EyeHeightAsPercent",
})


def settable(name: str) -> bool:
    """A parameter a friend's YOLO list may offer."""
    return name not in BUILTINS and not name.startswith("OGB/")


# --- what you share --------------------------------------------------------------

def public_board(board: Optional[Dict[str, Any]], avatar_name: str,
                 types: Dict[str, str], yolo: bool, avatar: str = "") -> Dict[str, Any]:
    """The ``pbd`` for a board (None: nothing worn). Without its version --
    `with_version` adds that."""
    cats, ctl = [], []
    if board is not None:
        for c in board["categories"][:MAX_CATEGORIES]:
            cats.append({"id": c["id"], "name": c["name"], "color": c["color"],
                         "locked": bool(c["locked"])})
        ids = {c["id"] for c in cats}
        for c in board["controls"]:
            if len(ctl) >= MAX_CONTROLS:
                break
            if c.get("cat") not in ids:
                continue
            out = {k: c[k] for k in ("id", "param", "ptype", "kind", "label", "cat")}
            for k in ("min", "max", "on", "off"):
                if k in c:
                    out[k] = c[k]
            if c.get("invert"):
                out["invert"] = True
            ctl.append(out)
    keys = list(dict.fromkeys(c["param"] for c in ctl))
    msg: Dict[str, Any] = {"t": "pbd", "name": str(avatar_name)[:pb.AVATAR_NAME_MAX],
                           "cats": cats, "ctl": ctl, "keys": keys, "nb": len(keys)}
    if avatar:
        msg["a"] = str(avatar)
    if yolo and board is not None:
        rest = sorted(n for n, p in types.items() if p in pb.PTYPES and settable(n))[:MAX_ALL]
        msg["all"] = [[n, types[n]] for n in rest]
        msg["keys"] = keys + [n for n in rest if n not in set(keys)]
    return msg


def version(board_msg: Dict[str, Any]) -> str:
    """A short fingerprint of what a board message holds."""
    body = json.dumps(board_msg, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.blake2b(body.encode("utf-8"), digest_size=6).hexdigest()


def with_version(board_msg: Dict[str, Any]) -> Dict[str, Any]:
    return dict(board_msg, b=version(board_msg))


def avatar_key(avatar_id: str) -> str:
    """A short key for the avatar worn: the same avatar, the same key --
    without handing its id around."""
    if not avatar_id:
        return ""
    return hashlib.blake2b(str(avatar_id).encode("utf-8"), digest_size=4).hexdigest()


def _key(value: Any) -> str:
    return value if isinstance(value, str) and len(value) <= 16 else ""


def make_prm(ver: str, yolo: bool, stop: bool, avatar: str = "") -> Dict[str, Any]:
    out: Dict[str, Any] = {"b": str(ver)}
    if yolo:
        out["y"] = 1
    if stop:
        out["stop"] = 1
    if avatar:
        out["a"] = str(avatar)
    return out


def read_prm(raw: Any) -> Optional[Dict[str, Any]]:
    if not isinstance(raw, dict):
        return None
    ver = raw.get("b")
    return {"ver": ver if isinstance(ver, str) and len(ver) <= 32 else "",
            "yolo": bool(raw.get("y")), "stop": bool(raw.get("stop")),
            "avatar": _key(raw.get("a"))}


# --- the board, received ----------------------------------------------------------

def _num(value: Any) -> Optional[float]:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


def read_board(msg: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """A friend's ``pbd``, cleaned -- None when it isn't one."""
    if msg.get("t") != "pbd" or not isinstance(msg.get("b"), str):
        return None
    cats = []
    for c in (msg.get("cats") or [])[:MAX_CATEGORIES]:
        if not isinstance(c, dict) or not c.get("id"):
            continue
        cats.append({"id": str(c["id"])[:32], "name": str(c.get("name") or "")[:pb.NAME_MAX],
                     "color": c.get("color") if c.get("color") in pb.CATEGORY_HUES else "green",
                     "locked": bool(c.get("locked"))})
    ids = {c["id"] for c in cats}
    ctl = []
    for raw in (msg.get("ctl") or [])[:MAX_CONTROLS]:
        if not isinstance(raw, dict) or raw.get("ptype") not in pb.PTYPES:
            continue
        c = {"id": str(raw.get("id") or "")[:32], "param": str(raw.get("param") or "")[:NAME_MAX],
             "ptype": raw["ptype"], "kind": raw.get("kind"),
             "label": str(raw.get("label") or raw.get("param") or "")[:pb.LABEL_MAX],
             "cat": str(raw.get("cat") or "")}
        if not c["id"] or not c["param"] or c["cat"] not in ids \
                or c["kind"] not in pb.KINDS_FOR_PTYPE[c["ptype"]]:
            continue
        for k in ("min", "max"):
            v = _num(raw.get(k))
            if v is not None:
                c[k] = v
        if pb.is_int_switch(c):
            c["on"], c["off"] = pb.int_switch_values(raw)
        if c["ptype"] == "Bool" and raw.get("invert"):
            c["invert"] = True
        ctl.append(c)
    keys = [str(k)[:NAME_MAX] for k in (msg.get("keys") or [])[:MAX_CONTROLS + MAX_ALL]
            if isinstance(k, str)]
    all_ = []
    for item in (msg.get("all") or [])[:MAX_ALL]:
        if isinstance(item, list) and len(item) == 2 and item[1] in pb.PTYPES \
                and isinstance(item[0], str):
            all_.append((item[0][:NAME_MAX], item[1]))
    try:
        nb = max(0, min(len(keys), int(msg.get("nb", len(keys)))))
    except (TypeError, ValueError):
        nb = len(keys)
    return {"ver": msg["b"][:32], "name": str(msg.get("name") or "")[:pb.AVATAR_NAME_MAX],
            "avatar": _key(msg.get("a")),
            "categories": cats, "controls": ctl, "keys": keys, "n_board": nb,
            "all": all_ if "all" in msg else None}


# --- values -------------------------------------------------------------------------

def _wire(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, bool):
        return 1 if value else 0
    if isinstance(value, int):
        return value
    v = _num(value)
    return None if v is None else round(v, 2)


def make_values(ver: str, epoch: int, values: List[Any]) -> List[Dict[str, Any]]:
    """``pv`` messages for a run of values (in ``keys`` order), each one
    a datagram."""
    out: List[Dict[str, Any]] = []
    chunk: List[Any] = []
    start, size = 0, 0
    for i, value in enumerate(values):
        w = _wire(value)
        n = len(json.dumps(w)) + 1
        if chunk and size + n > CHUNK_BYTES:
            out.append({"t": "pv", "b": ver, "w": epoch, "o": start, "x": chunk})
            chunk, start, size = [], i, 0
        chunk.append(w)
        size += n
    if chunk or not out:
        out.append({"t": "pv", "b": ver, "w": epoch, "o": start, "x": chunk})
    return out


def read_values(msg: Dict[str, Any], board: Dict[str, Any]) -> Dict[str, Any]:
    """{param: value} out of a ``pv`` for `board` (nothing when it is for
    another version), each value as its parameter's type."""
    if msg.get("b") != board.get("ver"):
        return {}
    try:
        start = int(msg.get("o", 0))
    except (TypeError, ValueError):
        return {}
    keys = board["keys"]
    types = {c["param"]: c["ptype"] for c in board["controls"]}
    types.update({n: p for n, p in (board.get("all") or [])})
    out = {}
    for i, raw in enumerate(msg.get("x") or []):
        at = start + i
        if at < 0 or at >= len(keys):
            break
        name = keys[at]
        ptype = types.get(name)
        if raw is None or ptype is None:
            out[name] = None
            continue
        v = _num(raw)
        if v is None:
            continue
        out[name] = (v != 0) if ptype == "Bool" else int(round(v)) if ptype == "Int" else v
    return out


# --- what a friend does -------------------------------------------------------------

def make_watch(have: str, yolo_open: bool, retry: int = 0) -> Dict[str, Any]:
    """`retry` -- while a newer board hasn't come, a number that changes
    every few seconds, so the watch goes out again and the board with it."""
    msg: Dict[str, Any] = {"t": "pw", "b": str(have)}
    if yolo_open:
        msg["y"] = 1
    if retry:
        msg["r"] = int(retry)
    return msg


WATCH_OFF = {"t": "pw", "off": 1}


def read_watch(msg: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """{have, yolo} -- or None for "not watching any more"."""
    if msg.get("off"):
        return None
    have = msg.get("b")
    return {"have": have if isinstance(have, str) else "", "yolo": bool(msg.get("y"))}


def make_set(seq: int, value: Any, control: str = "", param: str = "") -> Dict[str, Any]:
    msg: Dict[str, Any] = {"t": "pst", "id": int(seq), "v": _wire(value)}
    if control:
        msg["c"] = str(control)[:32]
    else:
        msg["p"] = str(param)[:NAME_MAX]
    return msg


def read_set(msg: Dict[str, Any]) -> Optional[Tuple[int, str, str, float]]:
    """(seq, control id, parameter name, value) -- one of the two names
    empty -- or None."""
    try:
        seq = int(msg.get("id"))
    except (TypeError, ValueError):
        return None
    v = _num(msg.get("v"))
    control = str(msg.get("c") or "")[:32]
    param = str(msg.get("p") or "")[:NAME_MAX]
    if v is None or bool(control) == bool(param):
        return None
    return seq, control, param, v


def make_holds(ids) -> Dict[str, Any]:
    return {"t": "ph", "h": sorted(str(i)[:32] for i in ids)[:MAX_CONTROLS]}


def read_holds(msg: Dict[str, Any]) -> List[str]:
    return [str(i)[:32] for i in (msg.get("h") or [])[:MAX_CONTROLS] if isinstance(i, str)]
