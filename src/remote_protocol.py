"""The Friends link's messages: what two OGPs say to each other.

Pure (no network, no Qt) so every rule is unit-testable. `remote_link.py`
carries the bytes; `controllers/friends_facade.py` decides what they mean.

Every message is one JSON object in one QUIC datagram (at most
`MAX_DATAGRAM` bytes — iroh's path MTU leaves ~1160 usable). Datagrams can
be lost, so nothing here relies on one arriving:

  * ``st``   — "my state", from the person whose toys these are, when it
    changes. Toys, the strength slider, what this friend is allowed to do,
    the shockers and their caps -- and the toys' live output (``out``), but
    only to a friend who may drive them and has your panel open (``lw``):
    moving toys change it every tick, and nobody else looks at it.
  * ``lw``   — "I have your panel open", from the person controlling, while
    their page shows this friend's panel (``on``, repeated like a status),
    and once more without ``on`` when they look away. A watch not repeated
    for `WATCH_STALE_S` is over. An OGP older than `LEVELS_SINCE` never
    says it, and gets the live output as before.
  * ``cmd``  — "what I want", from the person controlling, at once (≤60 Hz)
    on every change and every 250 ms while it drives anything. A state, not
    an event: the newest ``cmd`` replaces the last, and a friend whose
    ``cmd`` stops arriving drops to zero (`DRIVE_STALE_S`). ``lvl`` — the
    levels set by hand; ``ovr`` — toys where this friend's level replaces
    the receiver's own output instead of the higher of the two winning;
    ``pat`` — auto modes ``[wave, period, low, high]`` the receiver plays
    by itself (`friend_patterns`); ``hold`` — shocker slots held down
    (``[op, intensity]``). ``str`` is an event carried in every ``cmd``:
    ``[seq, value]``, applied once per new ``seq``, so it survives a lost
    datagram without replaying an old value over a newer local change.
    ``syn`` — this controller shares one panel with the others who sync
    (``Sync with others``, on by default): the version of its panel, a
    counter that a change of its own raises past the newest it has seen.
  * ``oth``  — "who else drives me", from the person whose toys these are,
    to a friend who may drive them: the nicknames of the OTHER friends
    driving right now (``n``), so a panel can say "+1 other".
  * ``pnl``  — the shared panel, from the person whose toys these are, to
    each friend who syncs: the newest change among those who sync (``seq``
    and its ``lvl`` / ``ovr`` / ``pat``). Their OGP takes it as its own, so
    every synced panel shows -- and sends -- the same; only that newest one
    plays (controllers/friends_receive.py).
  * ``shk``  — one shocker operation (``op`` shock / vibrate / beep, an
    optional ``warn`` first), sent three times; the receiver acts on each
    ``id`` once. ``stp`` — stop those shockers now, the same way.
  * ``hello`` / ``wait`` / ``ping`` / ``pong`` — the link's own business.
    A browser on the web remote (docs/assets/remote.js) adds ``web`` to its
    hello and only ever sends ``lw`` and ``cmd`` levels.

Whatever arrives is cleaned before it is used: a friend's OGP is trusted to
be OGP, not to be correct.
"""

import json
import math
import random
import re
from typing import Any, Dict, List, Optional, Set, Tuple

import friend_patterns

ALPN = b"ogp/friends/1"
PROTOCOL_VERSION = 2      # in every hello; 2: ``lw``
LEVELS_SINCE = 2          # an OGP older than this gets the live output always
WATCH_STALE_S = 30.0      # an ``lw`` repeats every 10 s; this long without one, it's over
MAX_DATAGRAM = 1100
NICK_MAX = 24
TOY_NAME_MAX = 40
MAX_TOYS = 8
MAX_SHOCKERS = 4          # the four shocker slots
MAX_OTHERS = 8            # names an ``oth`` carries
DRIVE_STALE_S = 1.0       # a controller silent this long drives nothing
SHOCK_MIN_MS = 100        # the shortest pulse a Length of 0 asks for
OPS = ("shock", "vibrate", "beep")
WARNINGS = ("vibrate", "beep")
WARN_MS = 1000            # a warning's length when none is given
WARN_MAX_MS = 9000        # PiShock's Long warning tops out at 9 s


def clean_id(text: Any) -> str:
    """A pasted Friends ID as stored: no spaces, lower case."""
    return "".join(str(text or "").split()).lower()


def valid_id(text: Any) -> bool:
    """A Friends ID: 64 hex digits (an iroh endpoint ID as it prints)."""
    return _is_hex(text, 64)


def valid_code(text: Any) -> bool:
    """An invite link's code: 16 hex digits."""
    return _is_hex(text, 16)


def _is_hex(text: Any, n: int) -> bool:
    s = str(text or "")
    return len(s) == n and all(c in "0123456789abcdef" for c in s)


def display_name(nick: Any, peer: Any) -> str:
    """How a friend is called on the page and in the log: their nickname,
    or the start of their ID."""
    return clean_nick(nick) or f"{str(peer)[:8]}…"


def new_id() -> str:
    """An id for a one-off message (a shock, a Stop): the receiver acts on
    each id once, however many copies arrive."""
    return f"{random.getrandbits(48):012x}"


# An OGP version as a friend's hello says it ("0.14.0", "0.14.0-alpha.11").
_VERSION_RE = re.compile(r"\d{1,4}(?:\.\d{1,4}){1,3}(?:-[0-9A-Za-z.]{1,20})?")


def clean_version(text: Any) -> str:
    """A friend's OGP version, or "" for anything that isn't one (a build
    from before versions were sent says none)."""
    s = str(text or "").strip()
    return s if _VERSION_RE.fullmatch(s) else ""


def clean_nick(text: Any) -> str:
    """A nickname as shown: single-spaced, printable, at most NICK_MAX."""
    s = " ".join(str(text or "").split())
    s = "".join(ch for ch in s if ch.isprintable())
    return s[:NICK_MAX]


def _unit(value: Any) -> Optional[float]:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(v):
        return None
    return max(0.0, min(1.0, v))


def encode(msg: Dict[str, Any]) -> bytes:
    return json.dumps(msg, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def decode(data: bytes) -> Optional[Dict[str, Any]]:
    try:
        msg = json.loads(data)
    except (ValueError, UnicodeDecodeError):
        return None
    return msg if isinstance(msg, dict) and isinstance(msg.get("t"), str) else None


# --- st: the receiver's state ---------------------------------------------------

def make_status(toys: List[Tuple[str, int]], outputs: Dict[str, float],
                strength: float, off: bool, paused: bool,
                allow_toys: bool, allow_shock: bool,
                shockers: List[str], armed: bool,
                max_intensity: int, max_pulse_ms: int,
                max_vibrate: int = 0, max_hold_s: float = 0.0,
                prm: Optional[Dict[str, Any]] = None,
                batteries: Optional[Dict[str, float]] = None,
                shocker_caps: Optional[List[Tuple[int, int, int]]] = None) -> Dict[str, Any]:
    """Build an ``st`` that fits one datagram. Toy names are cut to
    TOY_NAME_MAX and the list to MAX_TOYS; shockers are only told to a
    friend who may use them. `prm` says you share an avatar board with
    this friend (remote_params.make_prm); `batteries` is each toy's
    battery, 0..1, for the toys that report one (whole percent on the
    wire: it changes every few minutes, never every tick).
    `shocker_caps` is each shocker's own (max shock, max vibrate, longest
    pulse ms), in the order of `shockers` (``slim``); the ``lim`` beside it
    is what a copy from before that reads (the highest of each)."""
    toys = [(str(n)[:TOY_NAME_MAX], max(1, int(m))) for n, m in toys[:MAX_TOYS]]
    names = {n for n, _ in toys}
    msg: Dict[str, Any] = {
        "t": "st",
        "toys": [[n, m] for n, m in toys],
        # two decimals: enough for a meter, and a fading output doesn't
        # count as a change every tick (the link only sends changes)
        "out": {n[:TOY_NAME_MAX]: round(float(v), 2) for n, v in outputs.items()
                if n[:TOY_NAME_MAX] in names},
        "str": round(float(strength), 3),
        "off": bool(off),
        "pause": bool(paused),
        "allow": {"toys": bool(allow_toys), "shock": bool(allow_shock)},
    }
    bat = {n[:TOY_NAME_MAX]: max(0, min(100, round(float(v) * 100)))
           for n, v in (batteries or {}).items() if n[:TOY_NAME_MAX] in names and v is not None}
    if bat:
        msg["bat"] = bat
    if allow_shock:
        msg["shk"] = [str(s)[:TOY_NAME_MAX] for s in shockers[:MAX_SHOCKERS]]
        msg["armed"] = bool(armed)
        msg["lim"] = {"int": int(max_intensity), "ms": int(max_pulse_ms),
                      "vib": int(max_vibrate or max_intensity),
                      "hold": round(float(max_hold_s), 1)}
        if shocker_caps:
            msg["slim"] = [[int(a), int(b), int(c)]
                           for a, b, c in shocker_caps[:len(msg["shk"])]]
    if prm is not None:
        msg["prm"] = dict(prm)
    # Belt and braces: never hand the link a datagram it can't send.
    while len(encode(msg)) > MAX_DATAGRAM and msg["toys"]:
        dropped = msg["toys"].pop()
        msg["out"].pop(dropped[0], None)
        msg.get("bat", {}).pop(dropped[0], None)
    return msg


def read_status(msg: Dict[str, Any]) -> Dict[str, Any]:
    """A friend's ``st``, cleaned for the page."""
    toys = []
    for item in (msg.get("toys") or [])[:MAX_TOYS]:
        if isinstance(item, list) and len(item) == 2:
            name = str(item[0])[:TOY_NAME_MAX]
            try:
                motors = max(1, min(16, int(item[1])))
            except (TypeError, ValueError):
                motors = 1
            toys.append((name, motors))
    out_raw = msg.get("out") if isinstance(msg.get("out"), dict) else {}
    outputs = {}
    for name, _ in toys:
        v = _unit(out_raw.get(name))
        outputs[name] = 0.0 if v is None else v
    allow = msg.get("allow") if isinstance(msg.get("allow"), dict) else {}
    lim = msg.get("lim") if isinstance(msg.get("lim"), dict) else {}
    bat_raw = msg.get("bat") if isinstance(msg.get("bat"), dict) else {}
    strength = _unit(msg.get("str"))
    return {
        "toys": toys,
        "outputs": outputs,
        "strength": 1.0 if strength is None else strength,
        "off": bool(msg.get("off")),
        "paused": bool(msg.get("pause")),
        "allow_toys": bool(allow.get("toys")),
        "allow_shock": bool(allow.get("shock")),
        "shockers": [str(s)[:TOY_NAME_MAX] for s in (msg.get("shk") or [])[:MAX_SHOCKERS]],
        "armed": bool(msg.get("armed")),
        "max_intensity": _int(lim.get("int"), 0, 0, 100),
        "max_pulse_ms": _int(lim.get("ms"), 0, 0, 15000),
        "max_vibrate": _int(lim.get("vib"), _int(lim.get("int"), 0, 0, 100), 0, 100),
        "max_hold_s": max(0.0, min(600.0, _float(lim.get("hold"), 0.0))),
        # each shocker's own caps, in the order of "shockers" ([] from a copy
        # that doesn't send them: the "max_*" above are every shocker's then)
        "shocker_caps": _read_caps(msg.get("slim"), len(msg.get("shk") or [])),
        # read by remote_params.read_prm: None when they share no board
        "prm": dict(msg["prm"]) if isinstance(msg.get("prm"), dict) else None,
        "batteries": {name: _int(bat_raw.get(name), 0, 0, 100) for name, _ in toys
                      if bat_raw.get(name) is not None},
    }


def _read_caps(raw: Any, count: int) -> List[Tuple[int, int, int]]:
    caps: List[Tuple[int, int, int]] = []
    for item in (raw if isinstance(raw, list) else [])[:min(count, MAX_SHOCKERS)]:
        if not isinstance(item, list) or len(item) != 3:
            return []                   # all of them or none, never out of step
        caps.append((_int(item[0], 1, 1, 100), _int(item[1], 1, 1, 100),
                     _int(item[2], SHOCK_MIN_MS, SHOCK_MIN_MS, 15000)))
    return caps if len(caps) == min(count, MAX_SHOCKERS) else []


def shocker_caps(status: Dict[str, Any], slot: int) -> Tuple[int, int, int]:
    """(max shock, max vibrate, longest pulse ms) of one of a friend's
    shockers: its own when their copy says, else their hub-wide ones."""
    own = status.get("shocker_caps") or []
    if 0 <= slot < len(own):
        return own[slot]
    shock = int(status.get("max_intensity") or 1)
    return (shock, int(status.get("max_vibrate") or shock),
            int(status.get("max_pulse_ms") or SHOCK_MIN_MS))


def read_version(msg: Dict[str, Any]) -> int:
    """The protocol version a ``hello`` says (0: none -- not even 1)."""
    return _int(msg.get("v"), 0, 0, 1_000_000)


# --- lw: "I have your panel open" -------------------------------------------------

LEVELS_WATCH = {"t": "lw", "on": 1}
LEVELS_UNWATCH = {"t": "lw"}


def read_levels_watch(msg: Dict[str, Any]) -> bool:
    return bool(msg.get("on"))


def _float(value: Any, default: float) -> float:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return default
    return v if math.isfinite(v) else default


def _int(value: Any, default: int, lo: int, hi: int) -> int:
    try:
        v = int(float(value))
    except (TypeError, ValueError):
        return default
    return max(lo, min(hi, v))


# --- cmd: what the controller wants ---------------------------------------------

ALL_TOYS = "*"


def make_cmd(levels: Dict[str, float], strength: Optional[Tuple[int, float]],
             override=(), patterns: Optional[Dict[str, Any]] = None,
             holds: Optional[Dict[int, Tuple[str, float]]] = None,
             syn: Optional[int] = None) -> Dict[str, Any]:
    lvl = {str(k)[:TOY_NAME_MAX]: round(float(v), 3) for k, v in levels.items() if v > 0.0}
    msg: Dict[str, Any] = {"t": "cmd", "lvl": dict(list(lvl.items())[:MAX_TOYS + 1])}
    if override:
        msg["ovr"] = sorted({str(k)[:TOY_NAME_MAX] for k in override})[:MAX_TOYS + 1]
    pat = {}
    for toy, raw in (patterns or {}).items():
        c = friend_patterns.clean(*raw) if raw else None
        if c is not None:
            pat[str(toy)[:TOY_NAME_MAX]] = [c[0], round(c[1], 2), round(c[2], 3), round(c[3], 3)]
    if pat:
        msg["pat"] = dict(list(pat.items())[:MAX_TOYS + 1])
    hold = {str(int(slot)): [op, round(max(0.0, min(1.0, float(v))), 3)]
            for slot, (op, v) in (holds or {}).items()
            if op in OPS and 0 <= int(slot) < MAX_SHOCKERS}
    if hold:
        msg["hold"] = hold
    if strength is not None:
        msg["str"] = [int(strength[0]), round(float(strength[1]), 3)]
    if syn is not None:
        msg["syn"] = max(0, int(syn))
    return _fit(msg)


def _fit(msg: Dict[str, Any]) -> Dict[str, Any]:
    """A cmd never outgrows one datagram (one that did would never be sent,
    and the friend's drive would just stop): past MAX_DATAGRAM the toys
    named last lose their auto mode, then their override, then their
    level -- "all toys" goes last."""
    for key in ("pat", "ovr", "lvl"):
        while len(encode(msg)) > MAX_DATAGRAM:
            part = msg.get(key)
            names = [k for k in (part or ()) if k != ALL_TOYS]
            if not names:
                break
            if isinstance(part, dict):
                del part[names[-1]]
            else:
                part.remove(names[-1])
            if not part:
                del msg[key]
    return msg


def drives(msg: Dict[str, Any]) -> bool:
    """A cmd that keeps something going -- a level, an auto mode or a held
    shocker -- has to keep arriving, or the receiver lets it go."""
    return bool(msg.get("lvl") or msg.get("pat") or msg.get("hold"))


def read_cmd(msg: Dict[str, Any]) -> Tuple[Dict[str, float], Optional[Tuple[int, float]]]:
    """(levels by toy name or ALL_TOYS, (seq, strength) or None)."""
    raw = msg.get("lvl") if isinstance(msg.get("lvl"), dict) else {}
    levels: Dict[str, float] = {}
    for key, value in list(raw.items())[:MAX_TOYS + 1]:
        v = _unit(value)
        if v:
            levels[str(key)[:TOY_NAME_MAX]] = v
    strength = None
    s = msg.get("str")
    if isinstance(s, list) and len(s) == 2:
        v = _unit(s[1])
        try:
            seq = int(s[0])
        except (TypeError, ValueError):
            seq = None
        if v is not None and seq is not None:
            strength = (seq, v)
    return levels, strength


def read_cmd_more(msg: Dict[str, Any]) -> Tuple[Set[str], Dict[str, Tuple[str, float, float, float]],
                                                 Dict[int, Tuple[str, float]]]:
    """(override toys, auto modes by toy, held shocker slots -> (op, intensity))."""
    raw = msg.get("ovr") if isinstance(msg.get("ovr"), list) else []
    override = {str(k)[:TOY_NAME_MAX] for k in raw[:MAX_TOYS + 1]}
    patterns: Dict[str, Tuple[str, float, float, float]] = {}
    raw = msg.get("pat") if isinstance(msg.get("pat"), dict) else {}
    for toy, value in list(raw.items())[:MAX_TOYS + 1]:
        if isinstance(value, list) and len(value) == 4:
            c = friend_patterns.clean(*value)
            if c is not None:
                patterns[str(toy)[:TOY_NAME_MAX]] = c
    holds: Dict[int, Tuple[str, float]] = {}
    raw = msg.get("hold") if isinstance(msg.get("hold"), dict) else {}
    for slot, value in list(raw.items())[:MAX_SHOCKERS]:
        try:
            slot = int(slot)
        except (TypeError, ValueError):
            continue
        if (0 <= slot < MAX_SHOCKERS and isinstance(value, list) and len(value) == 2
                and value[0] in OPS):
            v = _unit(value[1])
            if v is not None:
                holds[slot] = (value[0], v)
    return override, patterns, holds


def read_syn(msg: Dict[str, Any]) -> Optional[int]:
    """A cmd's panel version: None when its sender drives on their own."""
    raw = msg.get("syn")
    if isinstance(raw, bool) or raw is None:
        return None
    try:
        return max(0, int(raw))
    except (TypeError, ValueError):
        return None


# --- oth / pnl: who else drives, the shared panel -----------------------------

def make_others(names: List[str]) -> Dict[str, Any]:
    return {"t": "oth", "n": [clean_nick(n) for n in names][:MAX_OTHERS]}


def read_others(msg: Dict[str, Any]) -> List[str]:
    raw = msg.get("n") if isinstance(msg.get("n"), list) else []
    return [n for n in (clean_nick(x) for x in raw[:MAX_OTHERS]) if n]


def make_panel(seq: int, levels: Dict[str, float], override=(),
               patterns: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """The shared panel at version `seq`: a cmd's toy part, no more."""
    msg = make_cmd(levels, None, override, patterns)
    msg["t"] = "pnl"
    msg["seq"] = max(0, int(seq))
    return _fit(msg)


def read_panel(msg: Dict[str, Any]) -> Optional[Tuple[int, Dict[str, float], Set[str],
                                                        Dict[str, Tuple[str, float, float, float]]]]:
    """(seq, levels, override toys, auto modes), or None."""
    seq = read_syn({"syn": msg.get("seq")})
    if seq is None:
        return None
    levels, _ = read_cmd(msg)
    override, patterns, _ = read_cmd_more(msg)
    return seq, levels, override, patterns


def drive_for(levels: Dict[str, float], toy: str) -> float:
    """One controller's level for one toy: the all-toys level or the toy's
    own, whichever is higher."""
    return max(levels.get(ALL_TOYS, 0.0), levels.get(str(toy)[:TOY_NAME_MAX], 0.0))


# --- shk: one shock -------------------------------------------------------------

def make_shock(shock_id: str, slots: List[int], intensity: float, length: float,
               op: str = "shock", warn: str = "", warn_intensity: float = 0.0,
               warn_ms: int = WARN_MS) -> Dict[str, Any]:
    msg = {"t": "shk", "id": str(shock_id)[:16],
           "slots": sorted({int(s) for s in slots if 0 <= int(s) < MAX_SHOCKERS}),
           "int": round(max(0.0, min(1.0, float(intensity))), 3),
           "len": round(max(0.0, min(1.0, float(length))), 3)}
    if op != "shock" and op in OPS:
        msg["op"] = op
    if warn in WARNINGS:
        msg["warn"] = warn
        msg["wi"] = round(max(0.0, min(1.0, float(warn_intensity))), 3)
        msg["wms"] = max(100, min(WARN_MAX_MS, int(warn_ms)))
    return msg


def _slots(raw: Any) -> List[int]:
    """Shocker slots as sent: valid, each once, in order."""
    slots: List[int] = []
    for s in (raw if isinstance(raw, list) else [])[:MAX_SHOCKERS]:
        try:
            s = int(s)
        except (TypeError, ValueError):
            continue
        if 0 <= s < MAX_SHOCKERS and s not in slots:
            slots.append(s)
    return sorted(slots)


def read_shock(msg: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    sid = str(msg.get("id") or "")[:16]
    slots = _slots(msg.get("slots"))
    intensity, length = _unit(msg.get("int")), _unit(msg.get("len"))
    if not sid or not slots or intensity is None or length is None:
        return None
    op = msg.get("op", "shock")
    if op not in OPS:
        return None
    warn = msg.get("warn") if msg.get("warn") in WARNINGS else ""
    wi = _unit(msg.get("wi")) if warn else None
    wms = max(100, min(WARN_MAX_MS, _int(msg.get("wms"), WARN_MS, 0, WARN_MAX_MS))) if warn else 0
    return {"id": sid, "slots": slots, "int": intensity, "len": length,
            "op": op, "warn": warn, "wi": 0.0 if wi is None else wi, "wms": wms}


def make_stop(stop_id: str, slots: List[int]) -> Dict[str, Any]:
    return {"t": "stp", "id": str(stop_id)[:16],
            "slots": sorted({int(s) for s in slots if 0 <= int(s) < MAX_SHOCKERS})}


def read_stop(msg: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    sid = str(msg.get("id") or "")[:16]
    slots = _slots(msg.get("slots"))
    if not sid or not slots:
        return None
    return {"id": sid, "slots": slots}


def shock_values(intensity: float, length: float, max_intensity: int,
                 max_pulse_ms: int) -> Tuple[int, int]:
    """Map the controller's two radials onto the RECEIVER's own caps:
    Strength 0..1 → 1..max_intensity, Length 0..1 → SHOCK_MIN_MS..max_pulse_ms.
    The engine clamps again on the way out; this only decides where in the
    receiver's allowed range the radials land."""
    top = max(1, int(max_intensity))
    longest = max(SHOCK_MIN_MS, int(max_pulse_ms))
    level = max(1, min(top, int(round(1 + intensity * (top - 1)))))
    ms = int(round(SHOCK_MIN_MS + length * (longest - SHOCK_MIN_MS)))
    return level, max(SHOCK_MIN_MS, min(longest, ms))
