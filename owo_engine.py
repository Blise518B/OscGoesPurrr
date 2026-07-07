# owo_engine.py
# Sealed OWO suit engine. Connection lifecycle via ReconnectingEngine; the
# OWO .NET SDK detail stays behind owo_sdk. The suit only talks to the My OWO
# phone app (mandatory vendor bridge); this engine's "connection" is the SDK's
# AutoConnect/Connect to that app over the LAN.
#
# OWO sensations are short pulses (~0.3 s) that expire, so a held contact must
# be re-sent on a cadence. The router pushes the active muscle→intensity map on
# change (debounced); this engine owns the re-send loop, mirroring how the
# Coyote engine owns its B0 cadence.

import math
import threading
import time
from typing import Callable, Dict, Optional

from engine_base import ReconnectingEngine
import owo_sdk

RESEND_INTERVAL_S = 0.25   # < the ~0.3 s sensation duration, so output stays continuous
SENSATION_DURATION_S = 0.3
MIN_SEND_GAP_S = 0.05      # wake-on-change floor so a 60 Hz router can't flood the app


class OwoEngine(ReconnectingEngine):
    def __init__(self,
                 get_game_id: Callable[[], str],
                 get_ip: Callable[[], str],
                 log: Optional[Callable[[str], None]] = None):
        super().__init__("OWO")
        self._get_game_id = get_game_id
        self._get_ip = get_ip
        self._log = log or (lambda _m: None)
        self._active: Dict[str, int] = {}     # muscle name -> intensity (0-100)
        self._frequency = 100
        self._state_lock = threading.Lock()
        self._send_thread: Optional[threading.Thread] = None
        # Wakes the cadence loop early on a real map/frequency change so a
        # contact edge doesn't wait out the 0.25 s re-send interval
        # (ARCHITECTURE.md latency pattern #5: event-driven wake).
        self._wake_evt = threading.Event()

    @property
    def _available(self) -> bool:
        return owo_sdk.is_available()

    @property
    def _unavailable_reason(self) -> str:
        return owo_sdk.load_error() or "OWO SDK unavailable"

    # ---- hot path (called from the router thread) --------------------
    def set_active(self, muscle_intensities: Dict[str, int], frequency: int) -> None:
        # The engine is the last line of defense for an EMS suit: clamp
        # intensity to 0-100 here (like frequency) regardless of the caller,
        # and drop garbage/non-finite values instead of raising (int(inf)
        # raises OverflowError, int(nan) ValueError — neither may escape
        # into the router's dispatch, where the exception would leave the
        # PREVIOUS map re-sending forever behind a committed debounce key).
        new_active: Dict[str, int] = {}
        for k, v in muscle_intensities.items():
            try:
                f = float(v)
            except (TypeError, ValueError):
                continue
            if not math.isfinite(f):
                continue
            iv = int(f)
            if iv > 0:
                new_active[k] = min(100, iv)
        try:
            f = float(frequency)
            new_freq = max(0, min(100, int(f))) if math.isfinite(f) else 100
        except (TypeError, ValueError):
            new_freq = 100
        with self._state_lock:
            changed = (new_active != self._active
                       or new_freq != self._frequency)
            self._active = new_active
            self._frequency = new_freq
        if changed:
            self._wake_evt.set()

    # ---- ReconnectingEngine transport hooks --------------------------
    def _open(self) -> None:
        if not owo_sdk.is_available():
            raise RuntimeError(owo_sdk.load_error() or "OWO SDK unavailable")
        owo = owo_sdk.OWO
        game_id = (self._get_game_id() or "").strip()
        auth = owo_sdk.GameAuth.Create()
        if game_id:
            auth = auth.WithId(game_id)
        owo.Configure(auth)
        ip = (self._get_ip() or "").strip()
        if ip:
            owo.Connect(ip)
        else:
            owo.AutoConnect()
        if owo.ConnectionState != owo_sdk.ConnectionState.Connected:
            raise RuntimeError("OWO not connected (open the My OWO app and 'Scan Game')")
        self._connected = True
        self._start_send_thread()

    def _close(self) -> None:
        self._connected = False  # the send thread exits on this
        if owo_sdk.is_available() and owo_sdk.OWO is not None:
            try:
                owo_sdk.OWO.Stop()
            except Exception:
                pass
            try:
                owo_sdk.OWO.Disconnect()
            except Exception:
                pass

    # ---- cadence sender ----------------------------------------------
    def _start_send_thread(self) -> None:
        t = threading.Thread(target=self._send_loop, daemon=True, name="OWOSend")
        self._send_thread = t
        t.start()

    def _send_loop(self) -> None:
        last_send = 0.0
        had_active = False
        while self._connected:
            with self._state_lock:
                active = dict(self._active)
                freq = self._frequency
            if active:
                # A wake-on-change edge goes out immediately after idle; only
                # consecutive rapid changes are spaced by the minimum gap.
                gap = time.monotonic() - last_send
                if gap < MIN_SEND_GAP_S:
                    time.sleep(MIN_SEND_GAP_S - gap)
                try:
                    owo = owo_sdk.OWO
                    factory = owo_sdk.SensationsFactory
                    for name, intensity in active.items():
                        muscle = owo_sdk.MUSCLES.get(name)
                        if muscle is None or intensity <= 0:
                            continue
                        sensation = factory.Create(
                            freq, SENSATION_DURATION_S, int(intensity), 0, 0, 0)
                        owo.Send(sensation, muscle)
                    last_send = time.monotonic()
                    had_active = True
                except Exception as e:
                    self._log(f"OWO send failed: {e}")
                    self._connected = False
                    break
            elif had_active:
                # Release edge: end the current pulse now instead of letting
                # it run out its ~0.3 s tail.
                had_active = False
                try:
                    owo_sdk.OWO.Stop()
                except Exception:
                    pass
            self._wake_evt.wait(timeout=RESEND_INTERVAL_S)
            self._wake_evt.clear()
