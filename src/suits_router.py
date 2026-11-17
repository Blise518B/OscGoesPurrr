# suits_router.py
# One router for both suits and the haptic trackers: reads the avatar once
# per tick into a body frame (body_map.py) and hands each engine its own
# view of it -- bHaptics gets per-position dots, OWO gets per-muscle levels,
# each placed tracker the strongest of the parameters its spot follows. Stateless apart from
# the silence latch and the page's test holds; the engines own pacing.
#
# Latency: the thread polls at ~60 Hz, and the controller also wakes it the
# moment a parameter the body reads arrives (notify(), on the OSC receive
# thread), so a contact goes out on the same packet. Nothing here waits on a
# device: submit_frame / set_active only store the newest value and wake the
# engine.
#
# Every tick re-submits the bHaptics frames, which is what keeps the
# engine's 250 ms frame timeout from expiring a held contact -- if this
# thread dies, the suit stops on its own.
#
# Off (strength 0) and VRChat going quiet (StaleSignalMonitor, 10 s) silence
# both suits and the trackers: bHaptics zeroes, OWO gets a stop, every
# tracker's level goes to 0. The page's bHaptics test
# holds still play while VRChat is quiet (so the suit can be tried without
# it), never while Off.
#
# Stuck contacts get the toys' rule (motor_router._antistuck_factor) with
# each kind's own switch and timers -- the bHaptics suit's, the OWO suit's
# and the trackers' anti-stuck on the Suits page (antistuck.py; each kind's
# block in the settings snapshot, so each has its own timers too) -- on each
# node of each input layer before they're mixed, so a frozen one can't hide
# a live one under it. VRChat sends a contact only when it changes, so a frozen sender
# (an avatar swap, the other person leaving, OSC lost) would otherwise hold
# its last level until VRChat goes quiet -- on OWO, that's EMS. A level
# between 0 and 1 that sits exactly still for `active_s` is cut (a real
# contact always jitters); one at the top -- a bool, "all the way in" --
# gets `peaked_s`, then fades out. A new value brings it back.

import math
import threading
import time
from typing import Any, Callable, Dict, List, Optional, Tuple

import body_map
from motor_router import MotorRouter
from parameter_store import ParameterStore, store
from polling import PollingThread
from router_base import StaleSignalMonitor
from utilities import strip_param_prefix

POLL_S = 1.0 / 60.0
# Below this a contact is noise, not a touch -- matters most for EMS.
OWO_DEAD_ZONE = 0.02
TEST_DOT_LEVEL = 30          # a held test dot, 0..100, unscaled

# The toys' anti-stuck thresholds, so the two never drift apart.
STUCK_EPSILON = MotorRouter._ANTISTUCK_EPSILON
STUCK_PEAKED = MotorRouter._ANTISTUCK_SATURATED
STUCK_RAMP_S = MotorRouter._ANTISTUCK_RAMP_S


def _seconds(value: Any, default: float) -> float:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return default
    return max(0.0, min(600.0, v)) if math.isfinite(v) else default


def stuck_factor(level: float, still_for: float, active_s: float, peaked_s: float) -> float:
    """How much of a level that has sat exactly still for `still_for`
    seconds still plays (0..1): a mid-range level is cut after `active_s`,
    one at the top fades over STUCK_RAMP_S after `peaked_s`."""
    if level >= STUCK_PEAKED:
        if still_for < peaked_s:
            return 1.0
        return max(0.0, min(1.0, 1.0 - (still_for - peaked_s) / STUCK_RAMP_S))
    return 0.0 if still_for >= active_s else 1.0


def _num(value: Any) -> float:
    if isinstance(value, bool):
        return 1.0 if value else 0.0
    try:
        v = float(value)
    except (TypeError, ValueError):
        return 0.0
    return v if math.isfinite(v) else 0.0


def tracker_inputs(params: Dict[str, Any], spots: Dict[str, Any]) -> Dict[str, float]:
    """Every avatar parameter a tracker spot follows -> its 0..1 value."""
    out: Dict[str, float] = {}
    for c in spots.values():
        for name in (c or {}).get("params") or ():
            out[name] = max(0.0, min(1.0, _num(params.get(name))))
    return out


def tracker_spot_levels(values: Dict[str, float], spots: Dict[str, Any],
                        scale: float) -> Dict[str, float]:
    """Each spot's 0..1 level: the strongest parameter it follows, times
    its strength and the sidebar's (the engine caps it again)."""
    out: Dict[str, float] = {}
    s = min(1.0, scale) if scale > 0 else 0.0
    for spot, c in spots.items():
        c = c or {}
        if not c.get("enabled", True) or not s:
            out[spot] = 0.0
            continue
        best = max((values.get(n, 0.0) for n in c.get("params") or ()), default=0.0)
        if best <= STUCK_EPSILON:
            out[spot] = 0.0
            continue
        intensity = max(0.0, min(100.0, _num(c.get("intensity", 100)))) / 100.0
        out[spot] = max(0.0, min(1.0, best * intensity * s))
    return out


def owo_intensity(level: float, muscle_cfg: Dict[str, Any], scale: float) -> int:
    """0..1 level -> 0..100 sensation intensity: scaled into the muscle's
    own top (its `max`) and by the global strength. The engine caps again."""
    if not muscle_cfg.get("enabled", True):
        return 0
    try:
        level = float(level)
        top = max(0.0, min(100.0, float(muscle_cfg.get("max", 100))))
    except (TypeError, ValueError):
        return 0
    if not math.isfinite(level) or level <= OWO_DEAD_ZONE or not scale > 0:
        return 0
    return max(0, min(100, int(round(min(1.0, level) * top * min(1.0, scale)))))


class SuitsRouter(PollingThread):

    def __init__(self, bhaptics, owo,
                 get_master_scale: Callable[[], float],
                 get_sps_sources: Optional[Callable[[], Optional[Dict[str, Any]]]] = None,
                 clock: Callable[[], float] = time.monotonic,
                 poll_s: float = POLL_S,
                 param_store: Optional[ParameterStore] = None,
                 trackers=None):
        super().__init__("SuitsRouter")
        self.bhaptics = bhaptics
        self.owo = owo
        self.trackers = trackers         # TrackerEngine, or None
        self._get_scale = get_master_scale
        self._get_sps = get_sps_sources or (lambda: None)
        # Anti-stuck's timers, one set per kind (each kind's own switch and
        # timers come with the settings snapshot): input -> (level, since)
        self._still: Dict[str, Dict[Tuple[Any, ...], Tuple[float, float]]] = {}
        self._clock = clock
        self._poll_s = poll_s
        self._store = param_store or store
        self._wake = threading.Event()
        self._stale = StaleSignalMonitor()
        self._config: Dict[str, Any] = {}
        self._bh_on = False
        self._owo_on = False
        self._trk_on = False
        self._tracker_keys: frozenset = frozenset()     # parameters the spots follow
        self._silenced = True
        self._holds: Dict[Tuple[str, int], float] = {}     # (position, dot) -> until
        self._holds_lock = threading.Lock()
        self._live: Dict[str, Any] = {"frame": body_map.empty_frame(), "owo": {}}

    # ---- controller-facing --------------------------------------------
    def configure(self, config: Dict[str, Any], bhaptics_on: bool, owo_on: bool,
                  trackers_on: bool = False) -> None:
        """The settings snapshot and which suits are switched on (GUI
        thread). Swapped whole, so a tick never sees half an edit. Its
        "trackers" holds the spots and "at" (serial -> spot) for every
        tracker that has a place."""
        self._config = dict(config or {})
        spots = (self._config.get("trackers") or {}).get("spots") or {}
        self._tracker_keys = frozenset(n for c in spots.values()
                                       for n in (c or {}).get("params") or ())
        self._bh_on = bool(bhaptics_on)
        self._owo_on = bool(owo_on)
        self._trk_on = bool(trackers_on)
        self._wake.set()

    def notify(self, address: str) -> None:
        """OSC receive thread: wake the tick now if the body reads this."""
        key = ParameterStore._canon_param_key(strip_param_prefix(address))
        if body_map.is_input_key(key) or key in self._tracker_keys:
            self._wake.set()

    def hold_dot(self, position: str, index: int, seconds: Optional[float]) -> None:
        """The page's test: hold one bHaptics dot for `seconds` (None lets
        go). Gentle and unscaled; refused when Off."""
        key = (str(position), int(index))
        with self._holds_lock:
            if seconds is None:
                self._holds.pop(key, None)
            else:
                self._holds[key] = self._clock() + max(0.0, float(seconds))
        self._wake.set()

    def hold_position(self, position: str, seconds: float) -> None:
        for i in range(body_map.NODE_COUNTS.get(position, 0)):
            self.hold_dot(position, i, seconds)

    def live(self) -> Dict[str, Any]:
        """What the body looks like right now, for the page."""
        return dict(self._live)

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
            except Exception as e:  # noqa: BLE001
                print(f"[Suits][Router] tick error: {e}")

    def _active_holds(self, now: float) -> Dict[str, List[int]]:
        out: Dict[str, List[int]] = {}
        with self._holds_lock:
            for key in [k for k, until in self._holds.items() if until <= now]:
                del self._holds[key]
            for (pos, i) in self._holds:
                n = body_map.NODE_COUNTS.get(pos)
                if n is not None and 0 <= i < n:
                    out.setdefault(pos, [0] * n)[i] = TEST_DOT_LEVEL
        return out

    def _gate(self, kind: str, now: float):
        """Anti-stuck's gate for one kind ("bhaptics", "owo", "trackers"),
        its switch and timers from the settings snapshot: a function
        (key, level) -> level, cut or fading, with its own timers --
        compared against what came in, never against what went out, so a
        cut input stays cut until VRChat sends a new value. Call `done()`
        once the tick's inputs went through it."""
        cfg = (self._config.get(kind) or {}).get("antistuck") or {}
        enabled = bool(cfg.get("enabled"))
        active_s = _seconds(cfg.get("active_s", 1.0), 1.0)
        peaked_s = _seconds(cfg.get("peaked_s", 10.0), 10.0)
        seen, fresh = self._still.get(kind) or {}, {}

        def gate(key: Tuple[Any, ...], v: float) -> float:
            if v <= STUCK_EPSILON:
                return v                    # off: nothing to hold, timer forgotten
            last = seen.get(key)
            if last is None or abs(v - last[0]) > STUCK_EPSILON or not enabled:
                last = (v, now)             # moved (or switched off): the fuse restarts
            fresh[key] = last
            return v * stuck_factor(v, max(0.0, now - last[1]), active_s, peaked_s) if enabled else v

        def done() -> None:
            self._still[kind] = fresh
        return gate, done

    def _unstick(self, kind: str, reading: body_map.BodyReading,
                 now: float) -> body_map.BodyReading:
        """The reading as one suit feels it: every stuck input cut or fading
        by that suit's anti-stuck. Each layer's node, and each OWO muscle,
        has its own timer."""
        gate, done = self._gate(kind, now)

        def frame(layer: str, f: body_map.Frame) -> body_map.Frame:
            return {pos: tuple(gate((layer, pos, i), v) for i, v in enumerate(vals))
                    for pos, vals in f.items()}

        out = body_map.BodyReading(
            self_touch=frame("self", reading.self_touch),
            others_touch=frame("others", reading.others_touch),
            any_touch=frame("any", reading.any_touch),
            owo={m: gate(("owo", m), v) for m, v in reading.owo.items()},
            routes=frame("route", reading.routes))
        done()
        return out

    def _unstick_values(self, kind: str, values: Dict[str, float],
                        now: float) -> Dict[str, float]:
        """The trackers' parameters, each through `kind`'s anti-stuck."""
        gate, done = self._gate(kind, now)
        out = {name: gate((kind, name), v) for name, v in values.items()}
        done()
        return out

    def tick(self) -> None:
        cfg = self._config
        bh_on = self._bh_on and self.bhaptics.is_connected
        owo_on = self._owo_on and self.owo.is_connected
        trk_on = self._trk_on and self.trackers is not None and self.trackers.is_alive
        if not (bh_on or owo_on or trk_on):
            self._silenced = True
            return
        try:
            scale = float(self._get_scale())
        except Exception:  # noqa: BLE001
            scale = 0.0
        if not math.isfinite(scale):
            scale = 0.0
        off = scale <= 0.0
        stale = self._stale.is_stale()
        live_contacts = not off and not stale

        if not live_contacts and not self._silenced:
            if bh_on:
                self.bhaptics.end_all()
            if owo_on:
                self.owo.end_all()
            self._live = {"frame": body_map.empty_frame(), "owo": {}, "trackers": {}}
        self._silenced = not live_contacts

        # what each one feels, through its own anti-stuck
        bh_reading = owo_reading = None
        trk_cfg = cfg.get("trackers") or {}
        trk_values: Dict[str, float] = {}
        if live_contacts:
            try:
                sps = self._get_sps()
            except Exception:  # noqa: BLE001
                sps = None
            params = self._store.get_all_parameters()
            now = self._clock()
            if bh_on or owo_on:
                body = body_map.read_body(params, cfg.get("routes") or (), sps)
                if bh_on:
                    bh_reading = self._unstick("bhaptics", body, now)
                if owo_on:
                    owo_reading = self._unstick("owo", body, now)
            if trk_on:
                trk_values = self._unstick_values(
                    "trackers", tracker_inputs(params, trk_cfg.get("spots") or {}), now)
        # (a kind not read this tick keeps its timers: a value that stayed
        # frozen meanwhile is still cut the moment it plays again)

        if trk_on:
            spot_levels = tracker_spot_levels(trk_values, trk_cfg.get("spots") or {},
                                              scale if live_contacts else 0.0)
            # every tick, even all zeros: the engine plays nothing not sent again
            self.trackers.set_levels({serial: spot_levels.get(spot, 0.0)
                                      for serial, spot in (trk_cfg.get("at") or {}).items()})
            self._live = dict(self._live, trackers=spot_levels)

        if bh_on:
            bh = cfg.get("bhaptics") or {}
            if bh_reading is not None:
                frame = body_map.bhaptics_frame(bh_reading, bh.get("react_to", body_map.REACT_BOTH),
                                                bool(bh.get("follow_owo", True)))
                dots = body_map.bhaptics_dots(frame, bh.get("devices") or {}, scale)
            else:
                frame = body_map.empty_frame()
                dots = {pos: [0] * n for pos, n in body_map.POSITIONS}
            if not off:
                for pos, held in self._active_holds(self._clock()).items():
                    dots[pos] = [max(a, b) for a, b in zip(dots[pos], held)]
            for pos in self.bhaptics.connected_positions():
                self.bhaptics.submit_frame(pos, dots.get(pos, ()))
            if bh_reading is not None:
                self._live = dict(self._live, frame=frame)

        if owo_on:
            ow = cfg.get("owo") or {}
            muscles: Dict[str, int] = {}
            levels: Dict[str, float] = {}
            if owo_reading is not None:
                levels = body_map.owo_levels(owo_reading, ow.get("react_to", body_map.REACT_BOTH),
                                             bool(ow.get("follow_bhaptics", True)))
                mcfg = ow.get("muscles") or {}
                for muscle, level in levels.items():
                    iv = owo_intensity(level, mcfg.get(muscle) or {}, scale)
                    if iv > 0:
                        muscles[muscle] = iv
            self.owo.set_active(muscles, ow.get("frequency", 50))
            if owo_reading is not None:
                self._live = dict(self._live, owo=levels)
