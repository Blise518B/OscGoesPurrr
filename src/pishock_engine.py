# pishock_engine.py
# Sealed shocker engine: the USB hub link's lifecycle plus the hot pulse /
# hold path, with the hard safety rules that are the last gate before a
# shock reaches a person. The hub runs PiShock's firmware or OpenShock's;
# the link speaks both (pishock_serial.py), and nothing here depends on
# which.
#
# Every send goes through here, so nothing — a buggy router, a test button,
# a hand-edited settings file — can get past these rules:
#   * intensity is capped at the user's ceilings -- one for shocks, its own
#     for vibrates, never above 100 -- and pulse length at the user's max
#     (never above 15 s); each shocker may have its own of these three, one
#     without takes the hub-wide ones;
#   * shock turns into vibrate until shocks are armed (the arming is the
#     user's, remembered across launches by the settings);
#   * a shocker rests `cooldown_s` after a pulse ends before the next one --
#     a pulse's or a hold's, whoever sends it -- except that a STRONGER pulse
#     may replace one that is still running, so a hard hit whose receivers
#     arrive a moment apart still lands at the strength of the hardest one.
#     Stronger is the kind first, as between holds (Blise's call, 2026-11-17:
#     "a shock should always take over vibration or beeping"): any shock
#     takes over a running vibrate or beep, any vibrate a beep, then a higher
#     level of the same kind -- an unarmed shock ranks as the vibrate it is.
#     Such a run of ever stronger pulses never lasts longer than one longest
#     pulse from when its first began (a caller may ask a shorter one:
#     `run_cap_ms`, a friend's own longest pulse);
#   * a continuous hold runs at most `max_hold_s`, then the shocker is forced
#     to rest `hold_rest_s` -- holds by several sources at once (the rules,
#     each friend, the web remote, a friend's warning) count as one hold,
#     and the rest is everyone's: no pulse goes in during it either;
#   * paused (the page's Stop) ends everything and refuses every send;
#   * a shocker switched off on its card (not in use) is stopped and gets
#     nothing, and shockers() / shocker_ids() -- what rules and friends see
#     -- leave it out;
#   * each shocker's Shock, Vibrate and Beep switch (set_ops_off): an op
#     switched off is refused there, whoever sends it, and one running when
#     it is switched off stops at once. A shock that isn't armed becomes a
#     vibrate first, so with Vibrate off it is refused too; what a shock
#     does with Shock off is SHOCK_OFF_AS_VIBRATE.
#
# Holds ("continuous") are sent as short overlapping chunks: the hub runs each
# operate for its duration and a new one for the same shocker takes over, so
# while a hold is live the engine re-sends every HOLD_REFRESH_S a chunk of
# HOLD_CHUNK_MS, and on release it sends `end`. If the link or the app dies
# mid-hold the shocker stops on its own within one chunk.
#
# Several sources may hold one shocker at once -- your rules, each friend,
# the web remote, a friend's warning -- each named by its `source`. The
# engine keeps each one's hold apart and plays the strongest -- any shock
# over any vibrate over any beep, then the highest level among those of the
# kind that plays (an unarmed shock counts as the vibrate it becomes) --
# every chunk capped as it goes out; a source
# letting go ends only its own hold, and one that stops topping its hold up
# stops counting within a chunk, as it would on its own. end / end_all,
# Stop, Off and a disarm still stop every source.
#
# Every source gets those rules (Blise's call, 2026-11-16: "it is for
# everything") -- your behaviours, ShockOSC's, the avatar menu, Me, friends,
# the web remote, the page's tests -- with nothing for a caller to remember.
#
# Separate limits for friends (Blise's call, 2026-11-17; off by default): the
# timing -- the rest after a pulse, the longest hold and the forced break --
# then comes twice, each with its own values AND its own accounting: one for
# your avatar (GROUP_AVATAR: your behaviours, ShockOSC's, your avatar menu,
# the page's tests) and one for friends (GROUP_FRIENDS: every friend, Me, the
# web remote), so a friend's long hold never blocks your contact shocks and
# the other way round. Each shocker keeps an `_Account` per group; with the
# switch off both are written together, so they are one. What is physically
# on the wire (a pulse running, its run, the hold chunk) is the shocker's
# own. Friends also get their own max shock, max vibrate and longest pulse
# then (Blise's call, same day): hub-wide values that only ever lower each
# shocker's own caps for GROUP_FRIENDS (`_caps_of`); your avatar keeps the
# shocker's own. Arming and the switches stay shared either way.
#
# pulse() returns what went out (`Sent`: the op after arming, the level after
# the caps, the length after the longest pulse and the run's), so the log can
# show what was asked and what was sent, and why they differ.
#
# What each shocker is doing (activity) feeds the avatar's ShockOSC feedback
# (shockosc_feedback.py): every write to the hub pokes the activity callback,
# so that wakes on change instead of polling.

import threading
import time
from dataclasses import dataclass, field, replace
from typing import Any, Callable, Dict, Hashable, List, Optional, Tuple

import pishock_serial
from pishock_limits import RANGES

OP_SHOCK = "shock"
OP_VIBRATE = "vibrate"
OP_BEEP = "beep"
VALID_OPS = (OP_SHOCK, OP_VIBRATE, OP_BEEP)

# A shock asked for on a shocker whose Shock switch is off: False drops it
# (refused, nothing reaches the shocker); True would send it as a vibrate,
# the way a shock that isn't armed goes out. Blise's call (2026-11-14):
# dropped, never a vibrate -- and the sender sees Shock greyed out with why
# (remote_protocol ``soff``), so nobody presses it in the first place.
SHOCK_OFF_AS_VIBRATE = False

HOLD_CHUNK_MS = 300
HOLD_REFRESH_S = 0.2
# A hold whose strength moves is re-sent at most this often (the first send
# after idle is never delayed).
HOLD_CHANGE_GAP_S = 0.05
# A source's hold that it hasn't topped up for this long no longer plays --
# the chunk it last asked for would have run out by now -- even while other
# sources keep the shocker going.
HOLD_SOURCE_TTL_S = HOLD_CHUNK_MS / 1000.0
# Strongest hold: the kind first -- any shock beats any vibrate, any vibrate
# any beep, whatever the levels (Blise's call, 2026-11-14: the shockers have
# priority) -- then the highest level within that kind.
_OP_RANK = {OP_BEEP: 0, OP_VIBRATE: 1, OP_SHOCK: 2}
# A capped pulse that would have less than this left is not sent at all.
MIN_RUN_ROOM_MS = 100
# Why a pulse went out shorter than asked (Sent.cut): the longest pulse, or
# a run of stronger pulses that took over one another reached it.
CUT_LONGEST, CUT_RUN = "longest", "run"
# Whose timing limits a send counts against (only apart while separate)
GROUP_AVATAR, GROUP_FRIENDS = "avatar", "friends"
GROUPS = (GROUP_AVATAR, GROUP_FRIENDS)

_RECONNECT_EVERY_S = 3.0
# A hub that refuses commands (OpenShock's E-Stop) says so on every send;
# the log hears about it at most this often.
_HUB_ERROR_LOG_EVERY_S = 5.0
_NEG_INF = -1e18


@dataclass
class _Account:
    """One group's timing on one shocker: the rest after its last pulse,
    its hold's clock and the forced break after it."""
    pulse_until: float = _NEG_INF       # its last pulse ends (ended) here
    hold_started: float = _NEG_INF
    rest_until: float = _NEG_INF        # resting after its longest hold
    released_at: float = _NEG_INF       # when its holds last let go


@dataclass
class _Shocker:
    pulse_started: float = _NEG_INF
    pulse_until: float = _NEG_INF       # the pulse on the wire ends here
    pulse_intensity: int = 0
    pulse_op: str = ""
    # when the running pulse's run began: a stronger pulse that takes over
    # keeps it (run_cap_ms counts from here)
    run_started: float = _NEG_INF
    # what each source wants held now: source -> (op, intensity, when it
    # last asked, its group), as asked -- arming and caps are applied as it
    # goes out
    holds: Dict[Hashable, Tuple[str, int, float, str]] = field(default_factory=dict)
    sent_op: Optional[str] = None       # what the last hold chunk carried
    sent_intensity: int = 0
    sent_at: float = _NEG_INF
    # each group's rests and hold clock (kept as one while not separate)
    acct: Dict[str, _Account] = field(default_factory=lambda: {g: _Account() for g in GROUPS})


@dataclass(frozen=True)
class Sent:
    """A pulse as it went out -- what pulse() returns when it did (None
    when a rule dropped it)."""
    op: str                 # after the shocker's switches and arming
    intensity: int          # after the shocker's ceiling for that op
    duration_ms: int        # after the longest pulse and the run's
    capped: bool = False    # the level asked was above that ceiling
    cut: str = ""           # "" / CUT_LONGEST / CUT_RUN: why it is shorter


def went_out(result: Any, op: str, intensity: int, duration_ms: int) -> Optional[Sent]:
    """pulse()'s result as a Sent: itself, or -- from a stand-in engine
    that only says True -- the pulse as asked; None when it didn't go."""
    if isinstance(result, Sent):
        return result
    return Sent(op, int(intensity), int(duration_ms)) if result else None


def _clamp_int(value, lo: int, hi: int, default: int) -> int:
    try:
        return max(lo, min(hi, int(value)))
    except (TypeError, ValueError, OverflowError):
        return default


def _clamp_float(value, lo: float, hi: float, default: float) -> float:
    try:
        v = float(value)
    except (TypeError, ValueError, OverflowError):
        return default
    if v != v:
        return default
    return max(lo, min(hi, v))


class PiShockEngine:
    """Drives the shockers paired to one USB hub. Public surface is
    primitive-only; the link, the shocker list and the per-shocker state
    are private."""

    def __init__(self,
                 link_factory: Optional[Callable[..., Any]] = None,
                 clock: Callable[[], float] = time.monotonic,
                 log: Optional[Callable[[str], None]] = None):
        self._link_factory = link_factory or pishock_serial.PiShockSerialLink
        self._clock = clock
        self._log = log or (lambda _m: None)
        self._state_callback: Callable[[], None] = lambda: None
        self._activity_callback: Callable[[], None] = lambda: None

        self._lock = threading.RLock()        # per-shocker hot-path state
        self._connect_lock = threading.Lock()  # one connect attempt at a time
        self._link = None
        self._connecting = False
        self._last_error: Optional[str] = None
        self._port_setting = ""                # "" = find the hub
        self._info: Dict[str, Any] = {}
        self._shockers: Dict[int, _Shocker] = {}
        self._os_shockers: List[Dict[str, Any]] = []
        self._names: Dict[str, str] = {}       # your names, by shocker id
        self._off: set = set()                 # switched off on their card, by id
        # each shocker's Shock / Vibrate / Beep switched off, by id -- only
        # the shockers that have one off
        self._ops_off: Dict[int, frozenset] = {}
        self._hub_error_logged_at = _NEG_INF

        self._want_connected = False
        self._supervisor: Optional[threading.Thread] = None
        self._stop = threading.Event()

        self._armed = False
        self._paused = False
        self._max_intensity = 30
        self._max_vibrate = 30
        self._max_pulse_ms = 1000
        self._cooldown_s = 0.5
        self._max_hold_s = 10.0
        self._hold_rest_s = 2.0
        # separate limits for friends: off, one set and one accounting; on,
        # friends keep to their own timing (cooldown, max hold, hold rest)
        self._separate = False
        self._friend_timing: Optional[Tuple[float, float, float]] = None
        # ... and friends' own (max shock, max vibrate, longest pulse ms):
        # each lowers a shocker's own cap for them, never raises it
        self._friend_caps: Optional[Tuple[int, int, int]] = None
        # a shocker's own caps by id -- only the ones it has
        self._shocker_own: Dict[int, Dict[str, int]] = {}

    # ---- status ------------------------------------------------------
    @property
    def is_available(self) -> bool:
        return pishock_serial.SERIAL_AVAILABLE

    @property
    def is_connected(self) -> bool:
        link = self._link
        return link is not None and link.is_open

    @property
    def is_connecting(self) -> bool:
        return self._connecting

    @property
    def last_error(self) -> Optional[str]:
        return self._last_error

    @property
    def port(self) -> str:
        link = self._link
        return link.port if link is not None else ""

    @property
    def hub_kind(self) -> str:
        """pishock_serial.PISHOCK / OPENSHOCK while connected, else ""."""
        link = self._link
        return link.kind if link is not None else ""

    @property
    def firmware(self) -> str:
        return str(self._info.get("version", ""))

    @property
    def board(self) -> str:
        return str(self._info.get("board", "") or "")

    @property
    def is_armed(self) -> bool:
        return self._armed

    @property
    def is_paused(self) -> bool:
        return self._paused

    def all_shockers(self) -> List[Dict[str, Any]]:
        """Every shocker on the hub, those switched off too (each with
        "off") -- for the Shockers page, where they are switched back on."""
        names, off = self._names, self._off
        return [dict(s, off=s.get("id") in off,
                     **({"name": names[str(s["id"])]} if str(s.get("id")) in names else {}))
                for s in self._info.get("shockers", [])]

    def shockers(self) -> List[Dict[str, Any]]:
        """The shockers in use: what rules, friends and Home see."""
        return [s for s in self.all_shockers() if not s["off"]]

    def shocker_ids(self) -> List[int]:
        return [s["id"] for s in self._info.get("shockers", []) if s["id"] not in self._off]

    def limits(self) -> Dict[str, Any]:
        return {
            "max_intensity": self._max_intensity,
            "max_vibrate": self._max_vibrate,
            "max_pulse_ms": self._max_pulse_ms,
            "cooldown_s": self._cooldown_s,
            "max_hold_s": self._max_hold_s,
            "hold_rest_s": self._hold_rest_s,
        }

    @property
    def separate_limits(self) -> bool:
        return self._separate

    def timing_for(self, group: str) -> Dict[str, float]:
        """The timing `group` keeps to now: cooldown_s, max_hold_s,
        hold_rest_s (the friends' own while limits are separate)."""
        cooldown, max_hold, rest = self._timing(group)
        return {"cooldown_s": cooldown, "max_hold_s": max_hold, "hold_rest_s": rest}

    def limits_for(self, shocker_id: int, group: str = GROUP_AVATAR) -> Dict[str, int]:
        """One shocker's caps as `group` gets them: its own, else the
        hub-wide ones -- for friends, lowered to their own while limits are
        separate."""
        shock, vib, ms = self._caps_of(shocker_id, group)
        return {"max_intensity": shock, "max_vibrate": vib, "max_pulse_ms": ms}

    def ops_off(self) -> Dict[int, List[str]]:
        """Each shocker's ops switched off on its card, by id (only the
        shockers with one off)."""
        return {sid: sorted(ops) for sid, ops in self._ops_off.items()}

    def op_allowed(self, shocker_id: int, op: str) -> bool:
        """Would `op` asked for on this shocker get past its Shock / Vibrate
        / Beep switches as things stand (arming included: a shock that isn't
        armed goes as a vibrate)? Says nothing of the link, Stop or the
        rest -- only what the switches refuse."""
        return op in VALID_OPS and self._switched(shocker_id, op) is not None

    def _caps_of(self, shocker_id: int, group: str = GROUP_AVATAR) -> Tuple[int, int, int]:
        """(max shock, max vibrate, longest pulse ms) for one shocker as
        `group` gets them: the shocker's own (else the hub-wide), and for
        friends while limits are separate the lower of that and theirs."""
        own = self._shocker_own.get(shocker_id) or {}
        caps = (own.get("max_intensity", self._max_intensity),
                own.get("max_vibrate", self._max_vibrate),
                own.get("max_pulse_ms", self._max_pulse_ms))
        if self._separate and group == GROUP_FRIENDS and self._friend_caps is not None:
            caps = tuple(min(c, f) for c, f in zip(caps, self._friend_caps))
        return caps

    def output_snapshot(self) -> Dict[int, Dict[str, Any]]:
        """What each shocker is doing right now (for the page's live row)."""
        now = self._clock()
        out: Dict[int, Dict[str, Any]] = {}
        with self._lock:
            for sid, st in self._shockers.items():
                if now < st.pulse_until:
                    out[sid] = {"kind": "pulse", "op": st.pulse_op,
                                "intensity": st.pulse_intensity}
                elif st.sent_op is not None:
                    out[sid] = {"kind": "hold", "op": st.sent_op,
                                "intensity": st.sent_intensity}
                elif any(now < a.rest_until for a in st.acct.values()):
                    out[sid] = {"kind": "rest", "op": "", "intensity": 0}
        return out

    def activity(self) -> Tuple[float, Dict[int, Dict[str, Any]]]:
        """``(now, {shocker id: ...})`` for the shockers in use: the last
        pulse as it went out (``op`` after arming, ``intensity`` after the
        caps, ``started`` / ``until`` on this clock -- `until` is cut short
        by a stop) and the hold running now (``hold_op`` / ``hold_intensity``:
        a chunk still on the hub, else None / 0), plus ``cooldown`` (s, the
        rest after a pulse). For the avatar's ShockOSC feedback."""
        now = self._clock()
        chunk_s = HOLD_CHUNK_MS / 1000.0
        with self._lock:
            out = {}
            for sid, st in self._shockers.items():
                if sid in self._off:
                    continue
                running = st.sent_op is not None and now - st.sent_at < chunk_s
                out[sid] = {"op": st.pulse_op, "intensity": st.pulse_intensity,
                            "started": st.pulse_started, "until": st.pulse_until,
                            "hold_op": st.sent_op if running else None,
                            "hold_intensity": st.sent_intensity if running else 0,
                            "cooldown": self._cooldown_s}
        return now, out

    # ---- configuration -----------------------------------------------
    def set_activity_callback(self, fn: Optional[Callable[[], None]]) -> None:
        """Called after every write to the hub (an operate or a stop), on
        whatever thread made it and inside the engine's lock: it must be
        quick and never call back into the engine -- setting an event."""
        self._activity_callback = fn or (lambda: None)

    def _poke(self) -> None:
        try:
            self._activity_callback()
        except Exception:
            pass

    def set_state_callback(self, fn: Optional[Callable[[], None]]) -> None:
        """Called from background threads whenever the connection state or
        shocker list changes. Must be cheap and thread-safe."""
        self._state_callback = fn or (lambda: None)

    def set_port(self, port: str) -> None:
        self._port_setting = str(port or "").strip()

    def set_shocker_names(self, names: Dict[str, str]) -> None:
        """Your names for the shockers (by id), over what the hub calls
        them -- every list of shockers carries them from here on."""
        self._names = {str(k): str(v) for k, v in (names or {}).items() if v}

    def set_openshock_shockers(self, shockers: List[Dict[str, Any]]) -> None:
        """The page's list for an OpenShock hub (id, model, name). A shocker
        taken off the list is stopped first, while the link still knows its
        model."""
        self._os_shockers = [dict(s) for s in shockers or []]
        link = self._link
        if link is None:
            return
        keep = {s.get("id") for s in self._os_shockers}
        if link.kind == pishock_serial.OPENSHOCK:
            with self._lock:
                gone = [sid for sid in self._shockers if sid not in keep]
                for sid in gone:
                    st = self._shockers[sid]
                    st.holds.clear()
                    st.sent_op = None
            for sid in gone:
                link.end(sid)
            if gone:
                self._poke()
        link.set_openshock_shockers(self._os_shockers)

    def set_limits(self, max_intensity, max_pulse_ms, cooldown_s,
                   max_hold_s, hold_rest_s, max_vibrate=None) -> None:
        """User caps, clamped to the absolute ceilings so a hand-edited
        settings file can't widen them. Without `max_vibrate`, vibrates
        share the shock cap."""
        self._max_intensity = _clamp_int(max_intensity, *RANGES["max_intensity"])
        self._max_vibrate = (self._max_intensity if max_vibrate is None
                             else _clamp_int(max_vibrate, *RANGES["max_vibrate"]))
        self._max_pulse_ms = _clamp_int(max_pulse_ms, *RANGES["max_pulse_ms"])
        self._cooldown_s = _clamp_float(cooldown_s, *RANGES["cooldown_s"])
        self._max_hold_s = _clamp_float(max_hold_s, *RANGES["max_hold_s"])
        self._hold_rest_s = _clamp_float(hold_rest_s, *RANGES["hold_rest_s"])

    def set_separate_limits(self, on: bool, friends: Optional[Dict[str, Any]] = None) -> None:
        """Separate limits for friends: on, friends keep to `friends`'
        timing (cooldown_s, max_hold_s, hold_rest_s -- clamped like the
        others) with an accounting of their own, and to its max_intensity,
        max_vibrate and max_pulse_ms as far as each shocker's own allow
        (one missing: no lower cap of theirs); off, everyone keeps to the
        one set. Switching off joins the two accountings the strict way --
        each rest as long as the longer -- so nothing slips out of a rest."""
        f = friends or {}
        timing = (_clamp_float(f.get("cooldown_s", self._cooldown_s), *RANGES["cooldown_s"]),
                  _clamp_float(f.get("max_hold_s", self._max_hold_s), *RANGES["max_hold_s"]),
                  _clamp_float(f.get("hold_rest_s", self._hold_rest_s), *RANGES["hold_rest_s"]))
        caps = tuple(_clamp_int(f.get(key, RANGES[key][1]), *RANGES[key])
                     for key in ("max_intensity", "max_vibrate", "max_pulse_ms"))
        with self._lock:
            self._friend_timing = timing
            self._friend_caps = caps
            was, self._separate = self._separate, bool(on)
            if was and not self._separate:
                for st in self._shockers.values():
                    self._join(st)

    @staticmethod
    def _join(st: "_Shocker") -> None:
        """Both groups' accountings as one, the stricter of each."""
        accts = [st.acct[g] for g in GROUPS]
        held = {h[3] for h in st.holds.values()}
        started = [st.acct[g].hold_started for g in GROUPS if g in held]
        one = _Account(pulse_until=max(a.pulse_until for a in accts),
                       hold_started=min(started) if started
                       else max(a.hold_started for a in accts),
                       rest_until=max(a.rest_until for a in accts),
                       released_at=max(a.released_at for a in accts))
        for g in GROUPS:
            st.acct[g] = replace(one)

    def set_shockers_off(self, ids) -> None:
        """The shockers switched off on their card. One newly off stops now
        (a hold or a pulse it was running), under the lock like a Stop."""
        off = set()
        for v in ids or ():
            try:
                off.add(int(v))
            except (TypeError, ValueError, OverflowError):
                continue
        with self._lock:
            newly = off - self._off
            self._off = off
            link = self._link
            for sid in newly:
                st = self._shockers.get(sid)
                if st is not None:
                    st.holds.clear()
                    st.sent_op = None
                    _cut(st, self._clock())
                if link is not None:
                    link.end(sid)
            if newly:
                self._poke()

    def set_ops_off(self, per_shocker: Dict[Any, Any]) -> None:
        """Each shocker's Shock / Vibrate / Beep switched off on its card, by
        id ({"24325": ["shock"]}). From then on an op switched off is refused
        on that shocker whoever sends it; a hold or a pulse of one that is
        running stops now, under the lock like an Off. The holds of the ops
        still on go on (their sources top them up as before)."""
        ops_by_id: Dict[int, frozenset] = {}
        for key, ops in (per_shocker or {}).items():
            try:
                sid = int(key)
            except (TypeError, ValueError, OverflowError):
                continue
            cleaned = frozenset(op for op in (ops if isinstance(ops, (list, tuple, set, frozenset))
                                              else ()) if op in VALID_OPS)
            if cleaned:
                ops_by_id[sid] = cleaned
        with self._lock:
            changed = {sid for sid in set(ops_by_id) | set(self._ops_off)
                       if ops_by_id.get(sid) != self._ops_off.get(sid)}
            self._ops_off = ops_by_id
            now = self._clock()
            link = self._link
            for sid in changed:
                st = self._shockers.get(sid)
                if st is None:
                    continue
                for source, (op, _level, _seen, _group) in list(st.holds.items()):
                    if self._switched(sid, op) != op:
                        del st.holds[source]
                running = now < st.pulse_until
                # what is on the wire now and may no longer go as it is
                stop = ((running and self._switched(sid, st.pulse_op) != st.pulse_op)
                        or (st.sent_op is not None
                            and self._switched(sid, st.sent_op) != st.sent_op))
                if stop:
                    st.sent_op = None
                    _cut(st, now)
                    if link is not None:
                        link.end(sid)
                    self._poke()

    def set_shocker_limits(self, per_shocker: Dict[Any, Dict[str, Any]]) -> None:
        """Each shocker's own caps, by id ({"24325": {"max_intensity": 20}});
        what one leaves out, it takes from the hub-wide caps. Clamped to the
        absolute ceilings like those, so a hand-edited file can't widen them."""
        own_by_id: Dict[int, Dict[str, int]] = {}
        for key, own in (per_shocker or {}).items():
            try:
                sid = int(key)
            except (TypeError, ValueError, OverflowError):
                continue
            own = own if isinstance(own, dict) else {}
            cleaned = {name: _clamp_int(own[name], *RANGES[name])
                       for name in ("max_intensity", "max_vibrate", "max_pulse_ms")
                       if name in own}
            if cleaned:
                own_by_id[sid] = cleaned
        self._shocker_own = own_by_id

    def set_armed(self, armed: bool) -> None:
        # Under the lock: a pulse being decided right now either goes out
        # before this (and the end_all below stops it) or sees the change.
        with self._lock:
            self._armed = bool(armed)
            if not self._armed:
                # A shock chunk already on the wire keeps running for its
                # duration; disarming must stop it now.
                self.end_all()

    def set_paused(self, paused: bool) -> None:
        with self._lock:
            self._paused = bool(paused)
            if self._paused:
                self.end_all()

    # ---- connection lifecycle (cold path) ----------------------------
    def start(self, want_connected: bool) -> None:
        """Start the supervisor that keeps the link up while it is wanted
        (auto-connect, or after the user pressed Connect)."""
        self._want_connected = bool(want_connected)
        if self._supervisor is not None and self._supervisor.is_alive():
            return
        self._stop = threading.Event()
        self._supervisor = threading.Thread(
            target=self._supervise, args=(self._stop,), daemon=True,
            name="PiShockSupervisor")
        self._supervisor.start()

    def stop(self) -> None:
        self._stop.set()
        self._want_connected = False
        self.end_all()
        self._drop_link()

    def connect(self) -> None:
        """Ask for the link. Returns at once; the supervisor connects on its
        own thread (the info handshake can take seconds)."""
        self._want_connected = True
        self._last_error = None
        if self._supervisor is None or not self._supervisor.is_alive():
            self.start(True)
        else:
            threading.Thread(target=self._try_connect, daemon=True,
                             name="PiShockConnect").start()

    def disconnect(self) -> None:
        self._want_connected = False
        self.end_all()
        self._drop_link()
        self._notify()

    def _supervise(self, stop: threading.Event) -> None:
        while not stop.is_set():
            if self._want_connected and not self.is_connected:
                self._try_connect()
            stop.wait(_RECONNECT_EVERY_S)

    def _try_connect(self) -> None:
        if not self._connect_lock.acquire(blocking=False):
            return  # an attempt is already running
        try:
            if self.is_connected or not self._want_connected:
                return
            if not self.is_available:
                self._last_error = "pyserial is not installed"
                return
            self._connecting = True
            self._notify()
            ports = ([self._port_setting] if self._port_setting
                     else pishock_serial.hub_candidates())
            if not ports:
                self._last_error = "no hub found on USB"
                return
            errors = []
            for port in ports:
                link = self._link_factory(on_info=self._on_info,
                                          on_lost=self._on_lost,
                                          on_error=self._on_hub_error)
                link.set_openshock_shockers(self._os_shockers)
                try:
                    info = link.open(port)
                except Exception as e:
                    errors.append(f"{port}: {e}")
                    continue
                if not self._want_connected or self._stop.is_set():
                    link.close()  # disconnect/stop raced the handshake
                    return
                with self._lock:
                    self._link = link
                    self._info = info
                    self._shockers = {s["id"]: _Shocker() for s in info["shockers"]}
                self._last_error = None
                ids = ", ".join(str(s["id"]) for s in info["shockers"]) or "none"
                name = pishock_serial.HUB_NAMES.get(link.kind, "Shocker")
                self._log(f"{name} hub connected on {port} "
                          f"(firmware {info.get('version') or '?'}, shockers {ids})")
                return
            self._last_error = "; ".join(errors)
        finally:
            self._connecting = False
            self._connect_lock.release()
            self._notify()

    def _drop_link(self) -> None:
        with self._lock:
            link, self._link = self._link, None
        if link is not None:
            link.close()

    def _on_info(self, info: Dict[str, Any]) -> None:
        with self._lock:
            self._info = dict(info)
            listed = {s["id"] for s in info.get("shockers", [])}
            for sid in list(self._shockers):
                if sid not in listed:
                    del self._shockers[sid]
            for sid in listed:
                self._shockers.setdefault(sid, _Shocker())
        self._notify()

    def _on_hub_error(self, message: str) -> None:
        now = self._clock()
        if now - self._hub_error_logged_at < _HUB_ERROR_LOG_EVERY_S:
            return
        self._hub_error_logged_at = now
        hint = (" - is the hub's E-Stop pressed?"
                if "failed to send" in message.lower() else "")
        self._log(f"Shocker hub refused a command ({message}){hint}")

    def _on_lost(self, reason: str) -> None:
        now = self._clock()
        with self._lock:
            self._link = None
            for st in self._shockers.values():
                st.sent_op = None
                st.holds.clear()
                _cut(st, now)
        self._last_error = f"hub disconnected ({reason})"
        self._log(f"Shocker {self._last_error}")
        self._poke()
        self._notify()

    def _notify(self) -> None:
        try:
            self._state_callback()
        except Exception:
            pass

    # ---- hot path ----------------------------------------------------
    def _effective_op(self, op: str) -> str:
        return OP_VIBRATE if op == OP_SHOCK and not self._armed else op

    def _switched(self, shocker_id: int, op: str) -> Optional[str]:
        """The op asked for on this shocker after its Shock / Vibrate / Beep
        switches: itself, None when they refuse it -- or, with Shock off and
        SHOCK_OFF_AS_VIBRATE, a vibrate. Arming is applied after this (by
        _effective_op), so what arming would turn it into must be on too."""
        off = self._ops_off.get(shocker_id)
        if not off:
            return op
        if op == OP_SHOCK and OP_SHOCK in off:
            if not SHOCK_OFF_AS_VIBRATE:
                return None
            op = OP_VIBRATE
        return None if self._effective_op(op) in off else op

    def _cap(self, op: str, shocker_id: int, group: str = GROUP_AVATAR) -> int:
        """The ceiling for an op that is about to go out on this shocker
        (after unarmed shocks became vibrates), as `group` gets it."""
        shock, vib, _ms = self._caps_of(shocker_id, group)
        return shock if op == OP_SHOCK else vib

    # Every send below is decided AND written under the lock, so the wire
    # sees things in the order they were decided: a Stop, an Off or a
    # disarm that lands while a pulse is being decided either comes first
    # (and the pulse sees it) or comes after it (and ends it). The write
    # itself doesn't block (the link times out after 0.1 s at worst).
    def _group(self, group: Any) -> str:
        return group if group in GROUPS else GROUP_AVATAR

    def _timing(self, group: str) -> Tuple[float, float, float]:
        """(rest after a pulse, longest hold, forced break) for `group`: the
        friends' own while limits are separate, else the one set."""
        if self._separate and group == GROUP_FRIENDS and self._friend_timing is not None:
            return self._friend_timing
        return self._cooldown_s, self._max_hold_s, self._hold_rest_s

    def _keys(self, group: str) -> Tuple[str, ...]:
        """The accountings a group's use is booked on: its own while limits
        are separate, both -- kept as one -- while they aren't."""
        return (group,) if self._separate else GROUPS

    def _may_hold(self, st: _Shocker, group: str, now: float) -> bool:
        """May `group`'s holds play now: not resting after its longest hold,
        nor after its last pulse."""
        a = st.acct[group]
        return now >= a.rest_until and now >= a.pulse_until + self._timing(group)[0]

    # Every send below is decided AND written under the lock, so the wire
    # sees things in the order they were decided: a Stop, an Off or a
    # disarm that lands while a pulse is being decided either comes first
    # (and the pulse sees it) or comes after it (and ends it). The write
    # itself doesn't block (the link times out after 0.1 s at worst).
    def pulse(self, shocker_id: int, op: str, intensity: int,
              duration_ms: int, *, run_cap_ms: Optional[int] = None,
              group: str = GROUP_AVATAR) -> Optional[Sent]:
        """One discrete operation. Returns what went out (`Sent`), None when
        a rule dropped it (not connected, paused, switched off, the rest
        after a pulse, the rest after the longest hold).

        A stronger pulse may take over a running one, but the run never
        lasts longer than one longest pulse from when its first began --
        or `run_cap_ms`, when a caller asks a shorter one.
        `group`: whose timing it counts against, and whose caps it gets
        (GROUP_AVATAR / GROUP_FRIENDS; the same while limits aren't
        separate)."""
        if op not in VALID_OPS:
            return None
        now = self._clock()
        with self._lock:
            link = self._link
            if link is None or self._paused or shocker_id in self._off:
                return None
            op = self._switched(shocker_id, op)
            if op is None:
                return None                 # switched off on its card
            op = self._effective_op(op)
            g = self._group(group)
            ceiling = self._cap(op, shocker_id, g)
            asked = _clamp_int(intensity, 1, 100, 1)
            intensity = min(asked, ceiling)
            longest = self._caps_of(shocker_id, g)[2]
            if run_cap_ms is not None:
                longest = _clamp_int(run_cap_ms, 1, longest, longest)
            asked_ms = _clamp_int(duration_ms, 1, 1 << 30, 300)
            st = self._shockers.get(shocker_id)
            if st is None:
                return None
            a = st.acct[g]
            running = now < st.pulse_until
            # the kind first, then the level (`op` and the running pulse's
            # are both after arming: an unarmed shock is the vibrate it is)
            upgrade = running and ((_OP_RANK[op], intensity)
                                   > (_OP_RANK.get(st.pulse_op, 0), st.pulse_intensity))
            if running and not upgrade:
                return None
            # its group's rest after its last pulse -- unless it takes over
            # that very pulse, still running
            if now < a.pulse_until + self._timing(g)[0] and not (upgrade and now < a.pulse_until):
                return None
            if now < a.rest_until:
                return None                 # resting after its longest hold
            room_ms, cut = longest, CUT_LONGEST
            if upgrade:
                room_ms = int((st.run_started - now) * 1000.0 + longest)
                if room_ms < MIN_RUN_ROOM_MS:
                    return None             # the run is as long as it may be
                cut = CUT_RUN if room_ms < longest else CUT_LONGEST
            duration_ms = min(asked_ms, room_ms)
            if not running:
                st.run_started = now
            st.pulse_started = now
            st.pulse_until = now + duration_ms / 1000.0
            for k in self._keys(g):
                st.acct[k].pulse_until = st.pulse_until
            st.pulse_intensity = intensity
            st.pulse_op = op
            # The pulse took the shocker over; a live hold re-sends once it
            # ends and its rest is over, instead of cutting it short.
            st.sent_op = None
            st.sent_at = _NEG_INF
            sent = link.operate(shocker_id, op, intensity, duration_ms)
            self._poke()
            if not sent:
                return None
            return Sent(op, intensity, duration_ms, capped=asked > ceiling,
                        cut=cut if duration_ms < asked_ms else "")

    def hold_free_in(self, shocker_id: int, group: str = GROUP_AVATAR) -> float:
        """Seconds until `group`'s hold may play on this shocker after the
        pulse running there and its group's rest after a pulse (0: now). The
        rest after the longest hold isn't in it: is_resting says that one."""
        now = self._clock()
        with self._lock:
            st = self._shockers.get(shocker_id)
            if st is None:
                return 0.0
            g = self._group(group)
            free = max(st.pulse_until, st.acct[g].pulse_until + self._timing(g)[0])
            return max(0.0, free - now)

    def is_resting(self, shocker_id: int, group: str = GROUP_AVATAR) -> bool:
        """`group` is resting after its longest hold on this shocker: nothing
        of its plays there, a pulse or a hold (while limits aren't separate,
        that is everyone)."""
        now = self._clock()
        with self._lock:
            st = self._shockers.get(shocker_id)
            return st is not None and now < st.acct[self._group(group)].rest_until

    def hold(self, shocker_id: int, op: str, intensity: int,
             source: Hashable = "", group: str = GROUP_AVATAR) -> None:
        """Keep `shocker_id` running at `intensity` until this `source`
        calls release(). Call it every tick while the source holds; it only
        writes when the strength changes or the running chunk needs topping
        up. Several sources may hold one shocker: the strongest plays.
        `group`: whose timing the hold counts against, and whose caps it
        gets."""
        if intensity <= 0 or op not in VALID_OPS:
            self.release(shocker_id, source)
            return
        now = self._clock()
        with self._lock:
            link = self._link
            if link is None or self._paused or shocker_id in self._off:
                return
            switched = self._switched(shocker_id, op)
            if switched is None:
                # switched off on its card: refused, and whatever this
                # source held before (another op) ends with it
                self.release(shocker_id, source)
                return
            op = switched
            st = self._shockers.get(shocker_id)
            g = self._group(group)
            if st is None or now < st.acct[g].rest_until:
                return
            _cooldown, max_hold, hold_rest = self._timing(g)
            keys = self._keys(g)
            a = st.acct[g]
            # A let-go shorter than the rest doesn't restart the clock: an
            # input flickering around its threshold, or one source handing
            # over to another, still gets the forced break.
            if (not any(h[3] in keys for h in st.holds.values())
                    and now - a.released_at >= hold_rest):
                for k in keys:
                    st.acct[k].hold_started = now
            if now - a.hold_started >= max_hold:
                # Forced break, for every source of the group (everyone's
                # while limits aren't separate): it rests, then a still-held
                # input starts a fresh hold. Another group's hold plays on.
                for src in [src for src, h in st.holds.items() if h[3] in keys]:
                    del st.holds[src]
                for k in keys:
                    st.acct[k].rest_until = now + hold_rest
                    st.acct[k].released_at = _NEG_INF
                self._replay(shocker_id, st, link, now)
                return
            st.holds[source] = (op, _clamp_int(intensity, 1, 100, 1), now, g)
            if now < st.pulse_until:
                return  # a pulse owns the shocker right now
            best = self._strongest_hold(shocker_id, st, now)
            if best is None:
                return  # its group rests after a pulse; nobody else holds
            op, intensity = best
            changed = (op != st.sent_op or intensity != st.sent_intensity)
            since = now - st.sent_at
            if since < HOLD_REFRESH_S and not (changed and since >= HOLD_CHANGE_GAP_S):
                return
            st.sent_op, st.sent_intensity, st.sent_at = op, intensity, now
            link.operate(shocker_id, op, intensity, HOLD_CHUNK_MS)
            self._poke()

    def _strongest_hold(self, shocker_id: int, st: _Shocker,
                        now: float) -> Optional[Tuple[str, int]]:
        """(op, intensity) the shocker's holds play: the strongest of the
        sources still topping theirs up whose group may hold now (not in a
        rest), as it would go out now -- arming and this shocker's caps
        applied (each source's group's), so an unarmed shock ranks as the
        vibrate it becomes. Any
        shock beats any vibrate (and any vibrate any beep); within a kind the
        highest level wins. None when none is."""
        best: Optional[Tuple[str, int]] = None
        allowed: Dict[str, bool] = {}
        for op, intensity, seen, group in st.holds.values():
            if now - seen > HOLD_SOURCE_TTL_S:
                continue
            if group not in allowed:
                allowed[group] = self._may_hold(st, group, now)
            if not allowed[group]:
                continue
            op = self._effective_op(op)
            intensity = _clamp_int(intensity, 1, self._cap(op, shocker_id, group), 1)
            if best is None or (_OP_RANK[op], intensity) > (_OP_RANK[best[0]], best[1]):
                best = (op, intensity)
        return best

    def _replay(self, shocker_id: int, st: _Shocker, link, now: float) -> None:
        """The holds changed under the chunk that is playing: the strongest
        still allowed takes over at once, or the shocker stops. Nothing while
        a pulse owns it."""
        if st.sent_op is None or now < st.pulse_until or link is None:
            return
        best = self._strongest_hold(shocker_id, st, now)
        if best is None:
            st.sent_op = None
            link.end(shocker_id)
        elif best != (st.sent_op, st.sent_intensity):
            st.sent_op, st.sent_intensity, st.sent_at = best[0], best[1], now
            link.operate(shocker_id, best[0], best[1], HOLD_CHUNK_MS)
        else:
            return
        self._poke()

    def release(self, shocker_id: int, source: Hashable = "") -> None:
        """This source let go: its hold ends, the others' go on (the
        strongest of them at once -- once a pulse and its rest are over).
        Cheap no-op when it held nothing."""
        with self._lock:
            st = self._shockers.get(shocker_id)
            if st is None or source not in st.holds:
                return
            now = self._clock()
            keys = self._keys(st.holds.pop(source)[3])
            if not any(h[3] in keys for h in st.holds.values()):
                for k in keys:
                    st.acct[k].released_at = now
            self._replay(shocker_id, st, self._link, now)

    def end(self, shocker_id: int) -> None:
        """Stop one shocker now -- a hold and a running pulse alike (a
        friend's Stop). Its cooldown still applies, as with end_all."""
        now = self._clock()
        with self._lock:
            st = self._shockers.get(shocker_id)
            if st is None:
                return
            st.holds.clear()
            st.sent_op = None
            _cut(st, now)
            for a in st.acct.values():
                a.released_at = now
            link = self._link
            if link is not None:
                link.end(shocker_id)
            self._poke()

    def end_all(self) -> None:
        """Stop every shocker now (Stop, Off, disarm, shutdown). A cut-short
        pulse still counts as ended now, so its cooldown still applies."""
        now = self._clock()
        with self._lock:
            for st in self._shockers.values():
                st.holds.clear()
                st.sent_op = None
                _cut(st, now)
                for a in st.acct.values():
                    a.released_at = now
            link = self._link
            if link is not None:
                for sid in list(self._shockers):
                    link.end(sid)
            self._poke()


def _cut(st: _Shocker, now: float) -> None:
    """A pulse cut short now (a stop, an Off): it counts as ended now on the
    wire and for every group -- its rest after it still comes."""
    st.pulse_until = min(st.pulse_until, now)
    for a in st.acct.values():
        a.pulse_until = min(a.pulse_until, now)
