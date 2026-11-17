"""ShockOSC's feedback parameters, from what the shocker engine actually
does -- so an avatar built for ShockOSC lights up, counts down and shows
its cooldown with OGP driving the shockers (shockosc.py has the names).

Per group (``ShockOsc/<Group>_...``, ``_All`` = every shocker) and across
them all (``ShockOsc/_Any_...``), as ShockOSC means them -- only shocks
count, as there:

  * ``_Active`` (bool): a shock is running on one of the group's shockers
    -- a pulse until it ends, or a held shock.
  * ``_Cooldown`` (bool): its last shock ended and the rest after it hasn't
    -- the engine's rest after a pulse, or the longer one the avatar's
    ShockOSC settings ask (the router's `shockosc_rests`).
  * ``_CooldownPercentage`` (0-1): 1 as that rest begins, down to 0.
  * ``_DurationRemaining`` (0-1): what is left of the running shock, 1 to
    0 (a held shock has no end: 1).
  * ``_Intensity`` (0-1): the running shock's strength as it went out --
    kept through the rest after it, as ShockOSC does, then 0.

A shock that isn't armed goes out as a vibrate, so it lights nothing: the
avatar shows what the shocker felt. A group's shockers are those its
behaviours drive (shockosc_facade.py works that out on the main thread).

Not a hot path. The sender thread sleeps until the engine pokes it (every
write to the hub, PiShockEngine.set_activity_callback), then ticks every
TICK_S while something runs or rests, and only values that changed go out
-- nothing at all while the shockers are idle.
"""

import threading
import time
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Tuple

import shockosc
from polling import PollingThread

TICK_S = 0.1
_DEFAULTS = {shockosc.ACTIVE: False, shockosc.COOLDOWN: False, shockosc.COOLDOWN_PCT: 0.0,
             shockosc.DURATION_LEFT: 0.0, shockosc.INTENSITY: 0.0}


def _round(v: float) -> float:
    return round(max(0.0, min(1.0, v)), 3)


def _shocker_state(a: Mapping[str, Any], now: float) -> Dict[str, Any]:
    """One shocker's shock, from the engine's activity: active, its
    strength and what's left of it (0-1), and when its last shock pulse
    ended with the rest after it (None when it has had none)."""
    out = {"active": False, "intensity": 0, "left": 0.0, "ended": None, "rest": 0.0,
           "last": 0}
    if a.get("op") == "shock" and a.get("intensity", 0) > 0:
        started, until = a.get("started", now), a.get("until", now)
        out["last"] = int(a["intensity"])
        if now < until:
            out["active"], out["intensity"] = True, int(a["intensity"])
            span = until - started
            out["left"] = (until - now) / span if span > 0 else 0.0
        else:
            out["ended"], out["rest"] = until, float(a.get("cooldown") or 0.0)
    if a.get("hold_op") == "shock" and a.get("hold_intensity", 0) > 0:
        out["active"] = True
        out["intensity"] = max(out["intensity"], int(a["hold_intensity"]))
        out["left"] = 1.0
    return out


def _cooling(states: Iterable[Dict[str, Any]], rest: Optional[Tuple[float, float]],
             now: float) -> Tuple[float, int]:
    """(the rest's percentage left, the strength of the shock before it) --
    (0, 0) when nothing rests. The latest-ending of the engine's rests
    after a shock and the avatar's own (`rest`: shock end, seconds)."""
    best_end, best_pct, strength = now, 0.0, 0
    for st in states:
        if st["ended"] is not None and st["rest"] > 0:
            end = st["ended"] + st["rest"]
            if end > best_end:
                best_end, best_pct, strength = end, (end - now) / st["rest"], st["last"]
    if rest is not None and rest[1] > 0:
        end = rest[0] + rest[1]
        if end > best_end:
            best_end, best_pct = end, (end - now) / rest[1]
            strength = strength or max((st["last"] for st in states), default=0)
    return (best_pct, strength) if best_end > now else (0.0, 0)


def compute(groups: Mapping[str, Any], in_use: Iterable[int],
            activity: Mapping[int, Mapping[str, Any]], now: float,
            rests: Optional[Mapping[str, Tuple[float, float]]] = None,
            any_too: bool = True) -> Tuple[Dict[str, Any], bool]:
    """``({parameter: value}, moving)``: every feedback parameter for the
    `groups` (name -> the shockers its behaviours drive, ``"all"`` or ids)
    and, with `any_too`, ``_Any``; `moving` while a shock runs or rests
    (the sender keeps ticking). `rests`: the router's ShockOSC rests by
    group key."""
    rests = rests or {}
    in_use = list(in_use)
    states = {sid: _shocker_state(activity.get(sid, {}), now) for sid in in_use}
    out: Dict[str, Any] = {}
    moving = False

    def put(group: str, sids: List[int], rest) -> Tuple[bool, float, float, float, float]:
        mine = [states[s] for s in sids if s in states]
        active = [st for st in mine if st["active"]]
        pct, before = (0.0, 0) if active else _cooling(mine, rest, now)
        intensity = max((st["intensity"] for st in active), default=0) or before
        left = max((st["left"] for st in active), default=0.0)
        values = {shockosc.ACTIVE: bool(active), shockosc.COOLDOWN: pct > 0,
                  shockosc.COOLDOWN_PCT: _round(pct), shockosc.DURATION_LEFT: _round(left),
                  shockosc.INTENSITY: _round(intensity / 100.0)}
        for suffix, value in values.items():
            out[shockosc.param(group, suffix)] = value
        return bool(active), pct, max((st["intensity"] for st in active), default=0), left

    any_pct = 0.0
    for group, which in groups.items():
        sids = in_use if which == "all" else [s for s in which or () if s in states]
        active, pct, _strength, _left = put(group, sids, rests.get(shockosc.group_key(group)))
        any_pct = max(any_pct, pct)
        moving = moving or active or pct > 0
    # _Any: every shocker in use, whichever group (or a friend) shocked it
    every = list(states.values())
    active = [st for st in every if st["active"]]
    any_active = bool(active)
    any_strength = max((st["intensity"] for st in active), default=0)
    any_left = max((st["left"] for st in active), default=0.0)
    if not active:
        any_pct = max(any_pct, _cooling(every, None, now)[0])
    moving = moving or any_active or any_pct > 0
    if any_too:
        for suffix, value in {shockosc.ACTIVE: any_active, shockosc.COOLDOWN: any_pct > 0,
                              shockosc.COOLDOWN_PCT: _round(any_pct),
                              shockosc.DURATION_LEFT: _round(any_left),
                              shockosc.INTENSITY: _round(any_strength / 100.0)}.items():
            out[shockosc.param(shockosc.ANY, suffix)] = value
    return out, moving


def default_of(name: str) -> Any:
    """A feedback parameter's resting value (False / 0)."""
    parts = shockosc.split(name)
    return _DEFAULTS.get(parts[1], 0.0) if parts else 0.0


class ShockOscFeedback(PollingThread):
    """Sends the feedback while there is a group to send it for. The main
    thread sets the groups (`set_groups`) and asks a re-send after an
    avatar loads or OSC reconnects (`resend`); the engine wakes it."""

    def __init__(self, get_activity: Callable[[], Tuple[float, Dict[int, Dict[str, Any]]]],
                 get_in_use: Callable[[], List[int]],
                 send: Callable[[str, Any], bool],
                 get_rests: Callable[[], Dict[str, Tuple[float, float]]] = dict,
                 tick_s: float = TICK_S):
        super().__init__("ShockOscFeedback")
        self._get_activity = get_activity
        self._get_in_use = get_in_use
        self._send = send
        self._get_rests = get_rests
        self._tick_s = tick_s
        self._wake = threading.Event()
        self._groups: Dict[str, Any] = {}
        self._any = False
        self._only: Optional[frozenset] = None
        self._sent: Dict[str, Any] = {}
        self._resend = False
        self._lock = threading.Lock()       # one tick at a time (thread / main)

    # ---- main thread ----------------------------------------------------
    def set_groups(self, groups: Mapping[str, Any], any_too: bool = True,
                   only: Optional[Iterable[str]] = None) -> None:
        """The groups to send for (name -> their shockers), whether ``_Any``
        too, and -- when the avatar's parameter list is known -- `only`
        the parameters it has (nothing else goes out)."""
        self._groups = dict(groups or {})
        self._any = bool(any_too)
        self._only = None if only is None else frozenset(only)
        self.wake()

    def resend(self) -> None:
        """VRChat lost the values (an avatar loaded, OSC came back)."""
        self._resend = True
        self.wake()

    def wake(self) -> None:
        self._wake.set()

    def stop(self) -> None:
        super().stop()
        self._wake.set()

    def let_go(self) -> None:
        """Every value sent back to its resting value, now (the feature
        going off, quitting) -- then nothing more is sent."""
        self._groups, self._any = {}, False
        self.tick()

    # ---- the tick ---------------------------------------------------------
    def tick(self) -> bool:
        """Send what changed; True while something runs or rests."""
        with self._lock:
            if self._resend:
                self._resend = False
                self._sent = {}
            values, moving = {}, False
            if self._groups or self._any:
                now, activity = self._get_activity()
                values, moving = compute(self._groups, self._get_in_use(), activity, now,
                                         self._get_rests(), any_too=self._any)
                if self._only is not None:
                    values = {k: v for k, v in values.items() if k in self._only}
            sent = self._sent
            for name in [n for n in sent if n not in values]:
                # a group gone (its behaviours deleted, another avatar):
                # back to resting once
                rest = default_of(name)
                if sent[name] == rest or self._send(name, rest):
                    del sent[name]
            for name, value in values.items():
                if sent.get(name) != value and self._send(name, value):
                    sent[name] = value
            return moving

    def _run(self) -> None:
        moving = False
        while not self._stop.is_set():
            self._wake.wait(self._tick_s if moving else None)
            self._wake.clear()
            if self._stop.is_set():
                break
            try:
                moving = self.tick()
            except Exception as e:
                print(f"[ShockOSC] feedback tick failed: {e}")
                moving = False
