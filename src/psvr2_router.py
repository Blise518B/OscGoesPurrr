# psvr2_router.py
# Maps one VRChat contact receiver onto the PSVR2 headset's single rumble
# output (ported from the full edition). The headset motor is one scalar, so
# there is exactly one routed value.
#
# The source is a **raw contact receiver parameter**, not an OGB zone: pick
# the receiver straight off the avatar (the page lists the live parameters)
# and its 0-1 proximity value drives the headset. No zone type, no
# touch/pen filters -- a contact receiver already *is* the thing being
# touched. Shaping (threshold / gain) works as everywhere else, and the
# engine decides what the shaped level means (which rumble frequency inside
# the band).
#
# This edition's rules, matching what the suits get from suits_router:
#   * the level goes to the engine EVERY tick (zeros too): the engine plays
#     nothing it isn't sent again (psvr2_engine.LEVEL_TTL_S), so if this
#     thread dies the motor stops;
#   * Off (strength 0) and VRChat going quiet (StaleSignalMonitor, 10 s)
#     send 0;
#   * a stuck contact gets the toys' rule with the headset's own switch and
#     timers (its anti-stuck, on the PSVR2 page; antistuck.py): a level between 0
#     and 1 that sits exactly still for `active_s` is cut (a real contact
#     always jitters), one at the top fades after `peaked_s`; a new value
#     brings it back;
#   * the VR menu's OGP/Test floor (main's, for vibration backends) rides on
#     top only while output isn't Off -- like the suits, the headset plays
#     nothing while Off.
#
# Latency: the thread polls at ~60 Hz, and the controller wakes it the
# moment the contact's parameter arrives (notify(), on the OSC receive
# thread), so a touch goes out on the same packet. set_level only stores
# the value and wakes the engine's send thread.

import math
import threading
import time
from typing import Any, Callable, Dict, Optional, Tuple

from parameter_store import ParameterStore, store
from polling import PollingThread
from router_base import StaleSignalMonitor
from suits_router import STUCK_EPSILON, stuck_factor
from utilities import normalize_osc_value, strip_param_prefix

POLL_S = 1.0 / 60.0
IDLE_POLL_S = 0.5        # while the headset isn't connected
# Debounce granularity for the routed level. The engine quantizes again to a
# whole Hz (at most 26 distinct commands across the range), so this only has
# to be fine enough never to starve the engine of a perceptible change.
LEVEL_STEP = 0.02


def _seconds(value: Any, default: float) -> float:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return default
    return max(0.0, min(600.0, v)) if math.isfinite(v) else default


def contact_strength(parameter: Any, params: Dict[str, Any]) -> float:
    """Read one contact receiver's 0..1 value out of a parameter snapshot.

    `normalize_osc_value` does the coercion: genuine ints get the 0-255 byte
    rescale, floats saturate at 1.0, and NaN / inf / garbage become 0.0 —
    which matters, because `min(1.0, nan)` is 1.0 in CPython and a NaN
    reaching the mapper would command a full rumble. Pure.
    """
    name = str(parameter or "").strip()
    if not name:
        return 0.0
    raw = params.get(name)
    if raw is None:
        return 0.0
    return normalize_osc_value(raw)


def compute_psvr2_level(cfg: Dict[str, Any], strength01: float,
                        scale: float = 1.0) -> float:
    """Shape a 0..1 contact strength into the routed 0..1 level using the
    configured threshold / gain, quantized to LEVEL_STEP. `scale` is the
    sidebar's strength (0 while Off); applied pre-quantization so
    attenuation keeps full resolution, and scale=0 guarantees 0. Pure."""
    if not cfg or not cfg.get("enabled", False):
        return 0.0
    try:
        threshold = float(cfg.get("threshold", 0.0))
        gain = float(cfg.get("gain", 1.0))
        scale = float(scale)
    except (TypeError, ValueError):
        return 0.0
    if not (strength01 > threshold) or not scale > 0:     # also NaN
        return 0.0
    shaped = max(0.0, min(1.0, (strength01 - threshold) * gain * min(1.0, scale)))
    return round(round(shaped / LEVEL_STEP) * LEVEL_STEP, 4)


class PSVR2Router(PollingThread):

    def __init__(self, engine,
                 get_contact_config: Callable[[], Dict[str, Any]],
                 get_master_scale: Callable[[], float],
                 get_test_level: Optional[Callable[[], float]] = None,
                 get_antistuck: Optional[Callable[[], Optional[Dict[str, Any]]]] = None,
                 clock: Callable[[], float] = time.monotonic,
                 poll_s: float = POLL_S,
                 param_store: Optional[ParameterStore] = None):
        super().__init__("PSVR2Router")
        self.engine = engine
        self._get_cfg = get_contact_config
        self._get_scale = get_master_scale
        # The VR menu's Test floor (ModesFacade) and the headset's own
        # anti-stuck {enabled, active_s, peaked_s} (antistuck.py; None =
        # never cut).
        self._get_test = get_test_level or (lambda: 0.0)
        self._get_antistuck = get_antistuck or (lambda: None)
        self._clock = clock
        self._poll_s = poll_s
        self._store = param_store or store
        self._wake = threading.Event()
        self._stale = StaleSignalMonitor()
        self._key = ""                       # the contact's canonical name
        self._still: Optional[Tuple[float, float]] = None    # (level, since)
        self._live: Dict[str, float] = {"strength": 0.0, "level": 0.0}

    # ---- controller-facing --------------------------------------------
    def configure(self) -> None:
        """The contact changed (GUI thread): follow its new name."""
        cfg = self._get_cfg() or {}
        self._key = ParameterStore._canon_param_key(
            strip_param_prefix(cfg.get("parameter", "")))
        self._wake.set()

    def notify(self, address: str) -> None:
        """OSC receive thread: wake the tick now if this is the contact."""
        if self._key and ParameterStore._canon_param_key(
                strip_param_prefix(address)) == self._key:
            self._wake.set()

    def wake(self) -> None:
        """The headset came or went (any thread): tick now, at the new pace."""
        self._wake.set()

    def live(self) -> Dict[str, float]:
        """The contact's value (after its anti-stuck) and the level sent, for
        the page."""
        return dict(self._live)

    def stop(self) -> None:
        super().stop()
        self._wake.set()

    # ---- loop ---------------------------------------------------------
    def _run(self) -> None:
        while not self._stop.is_set():
            # no headset yet: nothing to send, so look twice a second, not 60
            self._wake.wait(self._poll_s if self.engine.is_connected else IDLE_POLL_S)
            self._wake.clear()
            if self._stop.is_set():
                break
            try:
                self.tick()
            except Exception as e:  # noqa: BLE001
                print(f"[PSVR2][Router] tick error: {e}")

    def _unstick(self, strength: float, now: float) -> float:
        """Anti-stuck's rule on the one contact: compared against what came
        in, never what went out, so a cut contact stays cut until VRChat
        sends a new value."""
        try:
            cfg = self._get_antistuck() or {}
        except Exception:  # noqa: BLE001
            cfg = {}
        if strength <= STUCK_EPSILON:
            self._still = None               # off: nothing held, timer forgotten
            return strength
        enabled = bool(cfg.get("enabled"))
        last = self._still
        if last is None or abs(strength - last[0]) > STUCK_EPSILON or not enabled:
            last = (strength, now)           # moved (or switched off): the fuse restarts
        self._still = last
        if not enabled:
            return strength
        return strength * stuck_factor(strength, max(0.0, now - last[1]),
                                       _seconds(cfg.get("active_s", 1.0), 1.0),
                                       _seconds(cfg.get("peaked_s", 10.0), 10.0))

    def tick(self) -> None:
        if not self.engine.is_connected:
            self._still = None
            self._live = {"strength": 0.0, "level": 0.0}
            return
        cfg = self._get_cfg() or {}
        try:
            scale = float(self._get_scale())
        except Exception:  # noqa: BLE001
            scale = 0.0
        if not math.isfinite(scale):
            scale = 0.0
        off = scale <= 0.0
        strength = level = 0.0
        if not off and not self._stale.is_stale():
            name = str(cfg.get("parameter") or "").strip()
            params = self._store.get_values((name,)) if name else {}
            strength = self._unstick(contact_strength(name, params), self._clock())
            level = compute_psvr2_level(cfg, strength, scale)
        else:
            self._still = None
        if not off and cfg.get("enabled"):
            # Gated on the contact being on, like main: an unset headset
            # doesn't buzz on the menu's connectivity pulse.
            try:
                test = float(self._get_test())
            except Exception:  # noqa: BLE001
                test = 0.0
            if test > 0.0:
                level = max(level, round(round(min(1.0, test) / LEVEL_STEP) * LEVEL_STEP, 4))
        # every tick, zeros too: the engine plays nothing not sent again
        self.engine.set_level(level)
        self._live = {"strength": strength, "level": level}
