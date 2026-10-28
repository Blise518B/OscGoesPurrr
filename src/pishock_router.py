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
#     own on its own shockers (the neck the collar, a thigh its shocker).
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
# Per shocker, the strongest hold wins (shock over vibrate over beep on a
# tie), and pulses go out before holds so a pulse owns the shocker for its
# length. Off, Stop or a lost link end everything; VRChat going silent ends
# what the rules started. The rules only ever let go of shockers they hold
# themselves -- a friend may be holding one too (friends_facade).

import threading
import time
from typing import Any, Callable, Dict, List, Optional, Tuple

from parameter_store import ParameterStore, store
from polling import PollingThread
from router_base import StaleSignalMonitor

POLL_S = 0.01
_OP_RANK = {"beep": 0, "vibrate": 1, "shock": 2}


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


def _stronger(a: Optional[Tuple[int, str]], b: Tuple[int, str]) -> bool:
    """Is candidate `b` (intensity, op, ...) stronger than `a`?"""
    if a is None:
        return True
    return (b[0], _OP_RANK.get(b[1], 0)) > (a[0], _OP_RANK.get(a[1], 0))


class _Compiled:
    """Rules flattened for the tick: parameter keys canonicalised the way
    the store keys them, disabled / empty rules dropped. A rule no shocker
    is dropped on yet is still watched (the page shows what its contact
    sees while you set it up) but drives nothing."""

    def __init__(self, rules: Dict[str, List[Dict[str, Any]]]):
        canon = ParameterStore._canon_param_key
        self.continuous = []
        self.hold_triggers = []
        self.pulse_triggers = []
        self.impacts = []
        keys = set()
        for r in rules.get("continuous", []):
            if r.get("enabled") and r.get("param"):
                key = canon(r["param"])
                keys.add(key)
                if r["shockers"]:
                    self.continuous.append((key, r["threshold"], r["min_int"],
                                            r["max_int"], r["op"], r["shockers"]))
        # a Touch zone is a trigger of its own: its contact, its shockers
        triggers = [r for r in rules.get("triggers", []) if r.get("enabled")]
        for r in rules.get("zones", []):
            if r.get("enabled"):
                triggers += [dict(r, param=z["param"], shockers=z["shockers"])
                             for z in r.get("zones", [])]
        for r in triggers:
            if r.get("param"):
                key = canon(r["param"])
                keys.add(key)
                if r["shockers"]:
                    entry = (key, r["intensity"], r["op"], r["shockers"], r["duration_ms"])
                    (self.hold_triggers if r["mode"] == "hold"
                     else self.pulse_triggers).append(entry)
        for r in rules.get("impacts", []):
            tiers = [(canon(t["param"]), t["intensity"])
                     for t in r.get("tiers", []) if t.get("param")]
            if r.get("enabled") and tiers:
                keys.update(k for k, _ in tiers)
                if r["shockers"]:
                    self.impacts.append((tiers, r["op"], r["shockers"], r["duration_ms"]))
        self.keys = frozenset(keys)


class PiShockRouter(PollingThread):

    def __init__(self, engine,
                 get_rules: Callable[[], Dict[str, List[Dict[str, Any]]]],
                 is_output_off: Callable[[], bool],
                 clock: Callable[[], float] = time.monotonic,
                 poll_s: float = POLL_S):
        super().__init__("PiShockRouter")
        self.engine = engine
        self._get_rules = get_rules
        self._is_output_off = is_output_off
        self._clock = clock
        self._poll_s = poll_s
        self._wake = threading.Event()
        self._compiled = _Compiled({})
        self._keys: frozenset = frozenset()
        self._last_rises: Dict[str, int] = {}
        self._silenced = True
        self._held: set = set()     # shockers the rules hold right now
        self._ours: set = set()     # ...or held / pulsed since the last silence
        self._stale = StaleSignalMonitor()
        self._live_values: Dict[str, float] = {}
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

    def notify(self, address: str) -> None:
        """OSC receive thread: wake the tick now if this is a watched key."""
        if ParameterStore._canon_param_key(address) in self._keys:
            self._wake.set()

    def live_values(self) -> Dict[str, float]:
        return dict(self._live_values)

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
        keys = compiled.keys
        values, rises = store.read_watched(keys) if keys else ({}, {})
        # Edges since the last tick. A key seen for the first time sets its
        # baseline without firing, so enabling a rule (or starting up) never
        # replays contacts that happened before.
        edges = {k for k, n in rises.items()
                 if n > self._last_rises.get(k, n)}
        self._last_rises = rises
        self._live_values = {k: _as_float(v) for k, v in values.items()}

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
            return
        self._silenced = False

        shockers = engine.shocker_ids()
        if not shockers:
            return

        def targets(which):
            """The shockers a rule names, of those on the hub now."""
            return shockers if which == "all" else [sid for sid in which if sid in shockers]

        pulses: Dict[int, Tuple[int, str, int]] = {}
        holds: Dict[int, Tuple[int, str]] = {}

        for key, intensity, op, which, duration in compiled.pulse_triggers:
            if key in edges:
                for sid in targets(which):
                    if _stronger(pulses.get(sid), (intensity, op)):
                        pulses[sid] = (intensity, op, duration)
        for tiers, op, which, duration in compiled.impacts:
            fired = [i for k, i in tiers if k in edges]
            if fired:
                intensity = max(fired)
                for sid in targets(which):
                    if _stronger(pulses.get(sid), (intensity, op)):
                        pulses[sid] = (intensity, op, duration)

        for key, threshold, lo, hi, op, which in compiled.continuous:
            v = _as_float(values.get(key))
            if v > threshold:
                cand = (map_intensity(v, threshold, lo, hi), op)
                for sid in targets(which):
                    if _stronger(holds.get(sid), cand):
                        holds[sid] = cand
        for key, intensity, op, which, _duration in compiled.hold_triggers:
            if _as_float(values.get(key)) > 0.0:
                for sid in targets(which):
                    if _stronger(holds.get(sid), (intensity, op)):
                        holds[sid] = (intensity, op)

        for sid, (intensity, op, duration) in pulses.items():
            engine.pulse(sid, op, intensity, duration)
        for sid, (intensity, op) in holds.items():
            engine.hold(sid, op, intensity)
        # Let go only of what the rules held: a friend's hold or warning on
        # another (or the same) shocker is theirs, not the rules' to end.
        for sid in self._held - holds.keys():
            engine.release(sid)
        self._held = set(holds)
        self._ours |= self._held | pulses.keys()
