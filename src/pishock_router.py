# pishock_router.py
# Turns the PiShock page's rules into engine calls.
#
#   * continuous — a float parameter above its threshold holds the shocker at
#     a strength scaled between the rule's min and max;
#   * triggers   — a bool contact either pulses once per contact or holds
#     while it stays on, at a fixed strength;
#   * impacts    — a group of OnEnter receivers (different Min Velocity on
#     the avatar); of the tiers that fired, the strongest picks the pulse;
#   * zones      — Touch zones: several bool contacts, each a trigger of its
#     own on its own shockers (the neck the collar, a thigh its shocker);
#   * pulls      — a PhysBone: its held op while grabbed, and a let-go with
#     any stretch pulses once, the strength by the stretch at the let-go
#     (ShockOSC's PhysBone, shockosc.py).
#
# A pulse trigger may want its contact held a while first (`hold_ms`,
# ShockOSC's touch): it fires on the tick the contact has stayed on that
# long, once per touch -- a check against the tick's clock, never a wait.
#
# A behaviour on a ShockOSC parameter (`ShockOsc/<Group>...`) keeps its
# ShockOSC group: after the group's shock it rests the behaviour's own
# `rest_ms` (the avatar's CooldownTime, kept in step by shockosc_sync.py),
# during which the group's behaviours do nothing, and the avatar's
# `_NextIntensity` / `_NextDuration` may make its next action gentler
# (never stronger or longer). The avatar's Paused stops a group like Stop
# (stop_shockosc): a pulse of its still playing is ended at once, and its
# behaviours -- switched Off by the sync -- hold nothing from that tick. A
# strength of 0 sends nothing, whatever the kind; the engine caps every
# send again whatever this asks.
#
# Every rule drives the shockers dropped on it ("all", or a list of ids;
# none dropped, it drives nothing).
#
# Contacts are read as rising edges from parameter_store's per-key counters,
# not as current values: an OnEnter receiver can be True for one VRChat frame,
# which a poll that only looks at the value misses more often than not.
#
# Latency: the thread polls at ~100 Hz, and the controller also wakes it the
# moment a watched parameter arrives (notify(), called on the OSC receive
# thread), so a contact goes out on the same packet. A hard hit's receivers
# can still land either side of a tick; the engine lets a stronger pulse
# replace a running one, so the harder tier wins either way. Nothing here
# delays a send.
#
# Per shocker, the strongest behaviour wins, the kind first -- any shock over
# any vibrate over any beep, then the level (Blise's call, 2026-11-16: the
# shockers have priority, as between sources in the engine; an unarmed shock
# ranks as the vibrate it becomes) -- and pulses go out before holds so a
# pulse owns the shocker for its length. Off, Stop or a lost link end
# everything; VRChat going silent ends what the rules started. The engine
# says what each pulse sent (pishock_engine.Sent): the log gets it beside
# what the behaviour asked. The rules hold as one source (SOURCE) and only
# ever let go of their own holds -- a friend may be holding the same
# shocker too (friends_receive), and the engine plays the stronger.

import threading
import time
from typing import Any, Callable, Dict, List, NamedTuple, Optional, Tuple

import shockosc
from parameter_store import ParameterStore, store
from pishock_engine import Sent, went_out
from polling import PollingThread
from router_base import StaleSignalMonitor

POLL_S = 0.01
# How the rules' holds are named to the engine, apart from friends' holds.
SOURCE = "rules"
_OP_RANK = {"beep": 0, "vibrate": 1, "shock": 2}


# A behaviour's name in the log and Statistics: its kind (the Shockers page's
# card title) plus its zone or its label. A label left at the kind's own
# default says nothing, so the contact it reads names it instead.
KIND_LABELS = {"zones": "Touch zones", "triggers": "Contact", "continuous": "Continuous",
               "impacts": "Impact", "pulls": "Pull"}
_DEFAULT_NAMES = {"zones": {"touch zones"}, "triggers": {"trigger", "contact"},
                  "continuous": {"continuous"}, "impacts": {"impact"}, "pulls": {"pull"}}
NAME_MAX = 48


def _place(param: Any) -> str:
    """Where a contact is, from its parameter: its last part ("Contact/Neck"
    -> "Neck")."""
    return str(param or "").strip().strip("/").rsplit("/", 1)[-1].strip()


def behaviour_name(kind: str, rule: Dict[str, Any], zone_param: Any = None) -> str:
    """How one of the Shockers page's behaviours is named where it fired:
    "Touch zones · Neck" (a Touch zones card names the zone that fired),
    "Contact · Spank" (a card's own label), "Continuous · Prox" (a card
    still called by its kind: the contact it reads; a Pull: its PhysBone)."""
    head = KIND_LABELS.get(kind, kind.capitalize() or "Behaviour")
    label = " ".join(str(rule.get("name") or "").split())
    if kind == "zones":
        place = _place(zone_param)
        lead = label or head
        out = f"{lead} · {place}" if place else lead
    elif label and label.casefold() not in _DEFAULT_NAMES.get(kind, set()):
        out = f"{head} · {label}"
    else:
        param = rule.get("param")
        if kind == "impacts":
            param = next((t.get("param") for t in rule.get("tiers") or ()
                          if t.get("param")), "")
        place = _place(param)
        out = f"{head} · {place}" if place else head
    return out[:NAME_MAX]


def map_intensity(value: float, threshold: float, lo: int, hi: int) -> int:
    """Map a value in (threshold, 1] linearly onto [lo, hi]."""
    span = max(1e-6, 1.0 - threshold)
    frac = max(0.0, min(1.0, (value - threshold) / span))
    return max(1, min(100, int(round(lo + frac * (hi - lo)))))


def _as_float(value) -> float:
    if value is True:
        return 1.0
    if value is False or value is None:
        return 0.0
    try:
        v = float(value)
    except (TypeError, ValueError):
        return 0.0
    return v if v == v else 0.0


def _stronger(a: Optional[Tuple[int, str]], b: Tuple[int, str], armed: bool = True) -> bool:
    """Is candidate `b` (intensity, op, ...) stronger than `a`? The kind
    first -- any shock beats any vibrate, any vibrate any beep -- then the
    level. Not `armed`, a shock ranks as the vibrate it goes out as."""
    if a is None:
        return True
    return _rank(b, armed) > _rank(a, armed)


def _rank(c: Tuple[int, str], armed: bool) -> Tuple[int, int]:
    op = "vibrate" if c[1] == "shock" and not armed else c[1]
    return _OP_RANK.get(op, 0), c[0]


class _Pulse(NamedTuple):         # a contact pulsing once (Contact, a Touch zone)
    key: str
    intensity: int
    op: str
    which: Any
    duration: int
    hold_ms: int                     # held this long first (0: on the edge)
    group: Optional[str]             # its ShockOSC group, if it is ShockOSC's
    rest_ms: int                     # the group's rest after its shock
    name: str                        # behaviour_name: for the log and Statistics


class _Hold(NamedTuple):          # a contact held ("While touching")
    key: str
    intensity: int
    op: str
    which: Any
    group: Optional[str]
    name: str


class _Cont(NamedTuple):          # Continuous
    key: str
    threshold: float
    lo: int
    hi: int
    op: str
    which: Any
    group: Optional[str]
    name: str


class _Impact(NamedTuple):
    tiers: Tuple[Tuple[str, int], ...]
    op: str
    which: Any
    duration: int
    group: Optional[str]
    name: str
    rest_ms: int = 0


class _Pull(NamedTuple):          # a PhysBone
    grab: str                        # <param>_IsGrabbed
    stretch: str                     # <param>_Stretch
    op: str                          # on a let-go with stretch
    held_op: str                     # while held ("none": nothing)
    lo: int
    hi: int
    duration: int
    which: Any
    group: Optional[str]
    name: str
    rest_ms: int = 0


class _Compiled:
    """Rules flattened for the tick: parameter keys canonicalised the way
    the store keys them, disabled / empty rules dropped. A rule no shocker
    is dropped on yet is still watched (the page shows what its contact
    sees while you set it up) but drives nothing. `groups`: the ShockOSC
    groups the rules are on, whose _Next... (`cfg_keys`) the tick reads."""

    def __init__(self, rules: Dict[str, List[Dict[str, Any]]]):
        canon = ParameterStore._canon_param_key
        self.continuous: List[_Cont] = []
        self.hold_triggers: List[_Hold] = []
        self.pulse_triggers: List[_Pulse] = []
        self.impacts: List[_Impact] = []
        self.pulls: List[_Pull] = []
        keys = set()
        groups: Dict[str, str] = {}

        def note(param: str) -> Optional[str]:
            g = shockosc.group_of_rule(param)
            if g is not None:
                groups.setdefault(shockosc.group_key(g), g)
            return g

        for r in rules.get("continuous", []):
            if r.get("enabled") and r.get("param"):
                key = canon(r["param"])
                keys.add(key)
                group = note(r["param"])
                if r["shockers"]:
                    self.continuous.append(_Cont(key, r["threshold"], r["min_int"],
                                                 r["max_int"], r["op"], r["shockers"], group,
                                                 behaviour_name("continuous", r)))
        # a Touch zone is a trigger of its own: its contact, its shockers
        triggers = [(r, behaviour_name("triggers", r))
                    for r in rules.get("triggers", []) if r.get("enabled")]
        for r in rules.get("zones", []):
            if r.get("enabled"):
                triggers += [(dict(r, param=z["param"], shockers=z["shockers"], hold_ms=0),
                              behaviour_name("zones", r, z["param"]))
                             for z in r.get("zones", [])]
        for r, name in triggers:
            if r.get("param"):
                key = canon(r["param"])
                keys.add(key)
                group = note(r["param"])
                if not r["shockers"]:
                    continue
                if r["mode"] == "hold":
                    self.hold_triggers.append(_Hold(key, r["intensity"], r["op"],
                                                    r["shockers"], group, name))
                else:
                    self.pulse_triggers.append(_Pulse(
                        key, r["intensity"], r["op"], r["shockers"], r["duration_ms"],
                        int(r.get("hold_ms") or 0), group, int(r.get("rest_ms") or 0), name))
        for r in rules.get("impacts", []):
            tiers = tuple((canon(t["param"]), t["intensity"])
                          for t in r.get("tiers", []) if t.get("param"))
            if r.get("enabled") and tiers:
                keys.update(k for k, _ in tiers)
                found = [g for g in (note(t["param"]) for t in r["tiers"] if t.get("param"))
                         if g is not None]
                if r["shockers"]:
                    self.impacts.append(_Impact(tiers, r["op"], r["shockers"],
                                                r["duration_ms"], found[0] if found else None,
                                                behaviour_name("impacts", r)))
        for r in rules.get("pulls", []):
            if r.get("enabled") and r.get("param"):
                grab = canon(r["param"] + "_" + shockosc.IS_GRABBED)
                stretch = canon(r["param"] + "_" + shockosc.STRETCH)
                keys.update((grab, stretch))
                group = note(r["param"])
                if r["shockers"]:
                    self.pulls.append(_Pull(grab, stretch, r["op"], r["held_op"], r["min_int"],
                                            r["max_int"], r["duration_ms"], r["shockers"],
                                            group, behaviour_name("pulls", r),
                                            int(r.get("rest_ms") or 0)))
        self.keys = frozenset(keys)
        self.groups = tuple(groups.values())
        self.cfg_keys = (frozenset(canon(k) for k in shockosc.watched_params(self.groups))
                         if self.groups else frozenset()) - self.keys
        self.read = self.keys | self.cfg_keys
        # each PhysBone once, however many Pulls are on it
        self.bones = tuple(dict.fromkeys((p.grab, p.stretch) for p in self.pulls))


_NO_NEXT = shockosc.NextValues()
_NEG_INF = -1e18


def pull_intensity(stretch: float, lo: int, hi: int) -> int:
    """A Pull's strength for a stretch (0-1): from `lo` at none to `hi` at
    full, as ShockOSC's range mode reads its PhysBone."""
    s = max(0.0, min(1.0, stretch))
    return max(1, min(100, int(round(lo + s * (hi - lo)))))


class PiShockRouter(PollingThread):

    def __init__(self, engine,
                 get_rules: Callable[[], Dict[str, List[Dict[str, Any]]]],
                 is_output_off: Callable[[], bool],
                 clock: Callable[[], float] = time.monotonic,
                 poll_s: float = POLL_S,
                 report: Optional[Callable[..., None]] = None):
        super().__init__("PiShockRouter")
        self.engine = engine
        self._get_rules = get_rules
        self._is_output_off = is_output_off
        self._clock = clock
        self._poll_s = poll_s
        # For the log (your avatar's behaviours): report(what, sid, op,
        # level, ms) after the sends -- "pulse" for one that went out (with
        # sent=, what the engine sent: Sent), "hold" when a hold starts,
        # "let-go" when it ends (its strongest level and how long). Called
        # on this thread; it must be quick.
        self._report = report
        self._hold_log: Dict[int, List[Any]] = {}   # sid -> [since, op, strongest]
        self._wake = threading.Event()
        self._compiled = _Compiled({})
        self._keys: frozenset = frozenset()
        self._last_rises: Dict[str, int] = {}
        self._silenced = True
        self._held: set = set()     # shockers the rules hold right now
        self._ours: set = set()     # ...or held / pulsed since the last silence
        self._stale = StaleSignalMonitor()
        self._live_values: Dict[str, float] = {}
        # a touch that must be held first: key -> when it started, and the
        # pulse triggers (by place) that already fired for it
        self._touch_since: Dict[str, float] = {}
        self._touch_fired: Dict[str, set] = {}
        # each PhysBone: grab key -> (held at the last tick, its stretch then)
        self._bones: Dict[str, Tuple[bool, float]] = {}
        # ShockOSC groups: group key -> (when its last shock ends, the rest
        # after it, s) -- the rest blocks the group
        self._sosc_rest: Dict[str, Tuple[float, float]] = {}
        # each shocker's last pulse from the rules: sid -> (its ShockOSC
        # group key or None, when it ends)
        self._playing: Dict[int, Tuple[Optional[str], float]] = {}
        # ShockOSC groups their avatar paused, to stop on the next tick (any
        # thread appends; None = every group)
        self._sosc_stops: List[Optional[frozenset]] = []
        self.rules_changed()

    # ---- controller-facing --------------------------------------------
    def rules_changed(self) -> None:
        """Recompile after the page edits a rule (GUI thread). The tick
        reads `_compiled` once per pass, so the swap is atomic for it."""
        try:
            compiled = _Compiled(self._get_rules() or {})
        except Exception as e:
            print(f"[PiShock] rule compile failed: {e}")
            compiled = _Compiled({})
        self._compiled = compiled
        self._keys = compiled.keys
        self._touch_fired = {}           # places changed: a touch starts afresh

    def notify(self, address: str) -> None:
        """OSC receive thread: wake the tick now if this is a watched key."""
        if ParameterStore._canon_param_key(address) in self._keys:
            self._wake.set()

    def live_values(self) -> Dict[str, float]:
        return dict(self._live_values)

    def stop_shockosc(self, groups=None) -> None:
        """Any thread: the avatar paused these ShockOSC groups (None: every
        one), like Stop for them -- a pulse of theirs still playing ends at
        once (the shocker is stopped: the engine can't tell one pulse's
        source from another's), on the tick this wakes. Their holds go with
        the behaviours switched Off; other sources' holds go on."""
        self._sosc_stops.append(None if groups is None else
                                frozenset(shockosc.group_key(g) for g in groups))
        self._wake.set()

    def shockosc_rests(self) -> Dict[str, Tuple[float, float]]:
        """ShockOSC groups resting after a shock (their behaviours' rest,
        the avatar's CooldownTime): group key -> (when the shock ends, the
        rest after it in s), on the router's clock (the feedback reads it)."""
        return dict(self._sosc_rest)

    def stop(self) -> None:
        super().stop()
        self._wake.set()

    # ---- loop ---------------------------------------------------------
    def _run(self) -> None:
        while not self._stop.is_set():
            self._wake.wait(self._poll_s)
            self._wake.clear()
            if self._stop.is_set():
                break
            try:
                self.tick()
            except Exception as e:
                print(f"[PiShock][Router] tick error: {e}")

    def tick(self) -> None:
        compiled = self._compiled
        keys = compiled.read
        values, rises = store.read_watched(keys) if keys else ({}, {})
        # Edges since the last tick. A key seen for the first time sets its
        # baseline without firing, so enabling a rule (or starting up) never
        # replays contacts that happened before.
        edges = {k for k, n in rises.items()
                 if n > self._last_rises.get(k, n)}
        self._last_rises = rises
        self._live_values = {k: _as_float(v) for k, v in values.items()
                             if k in compiled.keys}
        nxt = (shockosc.read_next(values, compiled.groups) if compiled.groups
               else _NO_NEXT)

        engine = self.engine
        stale = self._stale.is_stale()
        halt = (not engine.is_connected or engine.is_paused
                or self._is_output_off())
        if halt or stale:
            if not self._silenced:
                if halt:
                    engine.end_all()        # Off, Stop, a lost link: everything
                else:
                    # VRChat went quiet: what its contacts started ends. A
                    # friend's hold on the same hub isn't VRChat's to end.
                    for sid in self._ours:
                        engine.end(sid)
                self._silenced = True
                self._held, self._ours = set(), set()
                # a touch, a grab under way: gone with the silence
                self._touch_since, self._touch_fired, self._bones = {}, {}, {}
                self._sosc_stops.clear()            # everything ended already
                self._log_holds({})
            return
        self._silenced = False

        shockers = engine.shocker_ids()
        if not shockers:
            return
        now = self._clock()
        self._shockosc_rested(now)
        self._shockosc_stopped(now)

        def targets(which, op):
            """The shockers a rule names, of those on the hub now -- less
            those whose switch for `op` is off: the engine would refuse it
            there, and another behaviour's op that is on should win."""
            named = shockers if which == "all" else [sid for sid in which if sid in shockers]
            return [sid for sid in named if engine.op_allowed(sid, op)]

        def blocked(group) -> bool:
            """A ShockOSC group resting after its shock."""
            if group is None:
                return False
            rest = self._sosc_rest.get(shockosc.group_key(group))
            return rest is not None and now < rest[0] + rest[1]

        # (intensity, op, duration, ShockOSC group, behaviour, its rest) and
        # (intensity, op, behaviour): the behaviour that won rides along for
        # the log and Statistics, after the sends
        pulses: Dict[int, Tuple[int, str, int, Optional[str], str, int]] = {}
        holds: Dict[int, Tuple[int, str, str]] = {}
        armed = bool(getattr(engine, "is_armed", True))

        def pulse(which, intensity, op, duration, group, name, rest_ms=0):
            if group is not None:
                # the avatar's _NextIntensity / _NextDuration: only ever less
                intensity = nxt.strength(group, intensity)
                duration = nxt.length(group, duration)
            if intensity < 1:
                return              # a strength of 0 sends nothing
            for sid in targets(which, op):
                if _stronger(pulses.get(sid), (intensity, op), armed):
                    pulses[sid] = (intensity, op, duration, group, name, rest_ms)

        def hold(which, intensity, op, name):
            if intensity < 1:
                return              # a strength of 0 sends nothing
            for sid in targets(which, op):
                if _stronger(holds.get(sid), (intensity, op), armed):
                    holds[sid] = (intensity, op, name)

        for place, p in enumerate(compiled.pulse_triggers):
            if self._touched(p, place, values, edges, now) and not blocked(p.group):
                pulse(p.which, p.intensity, p.op, p.duration, p.group, p.name, p.rest_ms)
        for p in compiled.impacts:
            fired = [i for k, i in p.tiers if k in edges]
            if fired and not blocked(p.group):
                pulse(p.which, max(fired), p.op, p.duration, p.group, p.name, p.rest_ms)

        for p in compiled.continuous:
            v = _as_float(values.get(p.key))
            if v > p.threshold and p.hi >= 1 and not blocked(p.group):
                hold(p.which, map_intensity(v, p.threshold, p.lo, p.hi), p.op, p.name)
        for p in compiled.hold_triggers:
            if _as_float(values.get(p.key)) > 0.0 and not blocked(p.group):
                hold(p.which, p.intensity, p.op, p.name)

        bones = self._read_bones(compiled.bones, values, edges)
        for p in compiled.pulls:
            held, stretch, let_go = bones[p.grab]
            if blocked(p.group):
                continue            # a let-go meanwhile is gone, as in ShockOSC
            if held and p.held_op != "none":
                if p.hi >= 1:
                    hold(p.which, pull_intensity(stretch, p.lo, p.hi), p.held_op, p.name)
            elif let_go > 0.0 and p.hi >= 1:
                pulse(p.which, pull_intensity(let_go, p.lo, p.hi), p.op, p.duration, p.group,
                      p.name, p.rest_ms)

        fired = []                  # (sid, the pulse asked, what went out)
        for sid, p in pulses.items():
            sent = went_out(engine.pulse(sid, p[1], p[0], p[2]), p[1], p[0], p[2])
            if sent is not None:
                fired.append((sid, p, sent))
        for sid, (intensity, op, duration, group, _name, rest_ms), sent in fired:
            # whose pulse is playing on it now (a ShockOSC group's Paused
            # stops it: stop_shockosc)
            self._playing[sid] = (None if group is None else shockosc.group_key(group),
                                  now + sent.duration_ms / 1000.0)
            if group is not None:
                self._shockosc_fired(group, op, sent.duration_ms, now, rest_ms)
        for sid, (intensity, op, _name) in holds.items():
            engine.hold(sid, op, intensity, source=SOURCE)
        # Let go only of what the rules held: a friend's hold or warning on
        # another (or the same) shocker is theirs, not the rules' to end.
        for sid in self._held - holds.keys():
            engine.release(sid, source=SOURCE)
        self._held = set(holds)
        self._ours |= self._held | pulses.keys()
        # The log, after every send went out
        if self._report is not None:
            for sid, (intensity, op, duration, _group, name, _rest), sent in fired:
                self._tell("pulse", sid, op, intensity, duration, name, sent)
            self._log_holds(holds)

    # ---- a touch held first, a PhysBone, ShockOSC's groups ----------------
    def _touched(self, p: "_Pulse", place: int, values, edges, now: float) -> bool:
        """Does this pulse trigger fire this tick? On the contact's edge --
        or, when it wants the contact held first (`hold_ms`; a ShockOSC
        touch's is the avatar's HoldTime, kept in step), on the tick it has
        been on that long, once per touch."""
        wait_ms = p.hold_ms
        key = p.key
        if wait_ms <= 0:
            return key in edges
        if key in edges:
            # a fresh touch (a re-touch inside one tick counts as one too)
            self._touch_since[key] = now
            self._touch_fired[key] = set()
        if _as_float(values.get(key)) <= 0.0:
            self._touch_since.pop(key, None)
            self._touch_fired.pop(key, None)
            return False
        since = self._touch_since.get(key)
        fired = self._touch_fired.setdefault(key, set())
        if since is None or place in fired or (now - since) * 1000.0 < wait_ms:
            return False
        fired.add(place)
        return True

    def _read_bones(self, bones, values, edges) -> Dict[str, Tuple[bool, float, float]]:
        """Each PhysBone this tick: grab key -> (held now, its stretch, the
        stretch it was let go at -- 0 when it wasn't, or had none). The
        let-go's stretch is the last one seen while held: VRChat may reset
        the stretch in the same tick as the let-go."""
        out = {}
        for grab, stretch_key in bones:
            was, last = self._bones.get(grab, (False, 0.0))
            held = _as_float(values.get(grab)) > 0.0
            stretch = max(0.0, min(1.0, _as_float(values.get(stretch_key))))
            let_go = 0.0
            if held:
                last = stretch
            elif was or grab in edges:
                let_go = stretch if stretch > 0.0 else last
                last = 0.0
            self._bones[grab] = (held, last)
            out[grab] = (held, stretch, let_go)
        return out

    def _shockosc_fired(self, group: str, op: str, duration_ms: int,
                        now: float, rest_ms: int) -> None:
        """A ShockOSC group's shock went out: the group rests its
        behaviour's rest after it (ShockOSC's CooldownTime) -- the shockers'
        own rest after a pulse holds anyway, in the engine."""
        if op != "shock" or rest_ms <= 0:
            return
        gkey = shockosc.group_key(group)
        until = now + duration_ms / 1000.0
        ends, _old = self._sosc_rest.get(gkey, (_NEG_INF, 0.0))
        self._sosc_rest[gkey] = (max(ends, until), rest_ms / 1000.0)

    def _shockosc_stopped(self, now: float) -> None:
        """The avatar paused ShockOSC groups (stop_shockosc): their pulses
        still playing end now."""
        while self._sosc_stops:
            keys = self._sosc_stops.pop(0)
            for sid, (gkey, until) in list(self._playing.items()):
                if gkey is not None and until > now and (keys is None or gkey in keys):
                    self.engine.end(sid)
                    del self._playing[sid]

    def _shockosc_rested(self, now: float) -> None:
        """Rests that are over go."""
        for gkey in [g for g, (ends, rest) in self._sosc_rest.items() if now >= ends + rest]:
            del self._sosc_rest[gkey]

    def _log_holds(self, holds: Dict[int, Tuple[int, str, str]]) -> None:
        """The log: a rules' hold starting, and ending (with its strongest
        level, how long it ran and the behaviour that held it then)."""
        if self._report is None:
            return
        now = self._clock()
        for sid in list(self._hold_log):
            if sid not in holds:
                since, op, top, name = self._hold_log.pop(sid)
                self._tell("let-go", sid, op, top, int((now - since) * 1000), name)
        for sid, (intensity, op, name) in holds.items():
            entry = self._hold_log.get(sid)
            if entry is None:
                self._hold_log[sid] = [now, op, intensity, name]
                self._tell("hold", sid, op, intensity, None, name)
            elif intensity > entry[2]:
                entry[2], entry[3] = intensity, name

    def _tell(self, what: str, sid: int, op: str, level: int, ms: Optional[int],
              rule: str = "", sent: Optional[Sent] = None) -> None:
        """`level` / `ms` as the behaviour asked; for a pulse `sent` is what
        went out (the engine's caps, its longest pulse and the run's)."""
        try:
            if sent is None:
                self._report(what, sid, op, level, ms, rule=rule)
            else:
                self._report(what, sid, op, level, ms, rule=rule, sent=sent)
        except Exception as e:
            print(f"[PiShock][Router] log failed: {e}")
