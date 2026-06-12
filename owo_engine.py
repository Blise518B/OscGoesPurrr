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

import threading
import time
from typing import Callable, Dict, Optional

from engine_base import ReconnectingEngine
import owo_sdk

RESEND_INTERVAL_S = 0.25   # < the ~0.3 s sensation duration, so output stays continuous
SENSATION_DURATION_S = 0.3


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

    @property
    def _available(self) -> bool:
        return owo_sdk.is_available()

    @property
    def _unavailable_reason(self) -> str:
        return owo_sdk.load_error() or "OWO SDK unavailable"

    # ---- hot path (called from the router thread) --------------------
    def set_active(self, muscle_intensities: Dict[str, int], frequency: int) -> None:
        with self._state_lock:
            self._active = {k: int(v) for k, v in muscle_intensities.items() if int(v) > 0}
            self._frequency = max(0, min(100, int(frequency)))

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
        while self._connected:
            with self._state_lock:
                active = dict(self._active)
                freq = self._frequency
            if active:
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
                except Exception as e:
                    self._log(f"OWO send failed: {e}")
                    self._connected = False
                    break
            time.sleep(RESEND_INTERVAL_S)
