# suits_router.py
# One router for both suits: reads the avatar once per tick into a body
# frame (body_map.py) and hands each engine its own view of it -- bHaptics
# gets per-position dots, OWO gets per-muscle levels. Stateless apart from
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
# both suits: bHaptics zeroes, OWO gets a stop. The page's bHaptics test
# holds still play while VRChat is quiet (so the suit can be tried without
# it), never while Off.

import math
import threading
import time
from typing import Any, Callable, Dict, List, Optional, Tuple

import body_map
from parameter_store import ParameterStore, store
from polling import PollingThread
from router_base import StaleSignalMonitor
from utilities import strip_param_prefix

POLL_S = 1.0 / 60.0
# Below this a contact is noise, not a touch -- matters most for EMS.
OWO_DEAD_ZONE = 0.02
TEST_DOT_LEVEL = 30          # a held test dot, 0..100, unscaled


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
                 param_store: Optional[ParameterStore] = None):
        super().__init__("SuitsRouter")
        self.bhaptics = bhaptics
        self.owo = owo
        self._get_scale = get_master_scale
        self._get_sps = get_sps_sources or (lambda: None)
        self._clock = clock
        self._poll_s = poll_s
        self._store = param_store or store
        self._wake = threading.Event()
        self._stale = StaleSignalMonitor()
        self._config: Dict[str, Any] = {}
        self._bh_on = False
        self._owo_on = False
        self._silenced = True
        self._holds: Dict[Tuple[str, int], float] = {}     # (position, dot) -> until
        self._holds_lock = threading.Lock()
        self._live: Dict[str, Any] = {"frame": body_map.empty_frame(), "owo": {}}

    # ---- controller-facing --------------------------------------------
    def configure(self, config: Dict[str, Any], bhaptics_on: bool, owo_on: bool) -> None:
        """The settings snapshot and which suits are switched on (GUI
        thread). Swapped whole, so a tick never sees half an edit."""
        self._config = dict(config or {})
        self._bh_on = bool(bhaptics_on)
        self._owo_on = bool(owo_on)
        self._wake.set()

    def notify(self, address: str) -> None:
        """OSC receive thread: wake the tick now if the body reads this."""
        key = ParameterStore._canon_param_key(strip_param_prefix(address))
        if body_map.is_input_key(key):
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

    def tick(self) -> None:
        cfg = self._config
        bh_on = self._bh_on and self.bhaptics.is_connected
        owo_on = self._owo_on and self.owo.is_connected
        if not (bh_on or owo_on):
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
            self._live = {"frame": body_map.empty_frame(), "owo": {}}
        self._silenced = not live_contacts

        reading = None
        if live_contacts:
            try:
                sps = self._get_sps()
            except Exception:  # noqa: BLE001
                sps = None
            reading = body_map.read_body(self._store.get_all_parameters(),
                                         cfg.get("routes") or (), sps)

        if bh_on:
            bh = cfg.get("bhaptics") or {}
            if reading is not None:
                frame = body_map.bhaptics_frame(reading, bh.get("react_to", body_map.REACT_BOTH),
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
            if reading is not None:
                self._live = dict(self._live, frame=frame)

        if owo_on:
            ow = cfg.get("owo") or {}
            muscles: Dict[str, int] = {}
            levels: Dict[str, float] = {}
            if reading is not None:
                levels = body_map.owo_levels(reading, ow.get("react_to", body_map.REACT_BOTH),
                                             bool(ow.get("follow_bhaptics", True)))
                mcfg = ow.get("muscles") or {}
                for muscle, level in levels.items():
                    iv = owo_intensity(level, mcfg.get(muscle) or {}, scale)
                    if iv > 0:
                        muscles[muscle] = iv
            self.owo.set_active(muscles, ow.get("frequency", 50))
            if reading is not None:
                self._live = dict(self._live, owo=levels)
