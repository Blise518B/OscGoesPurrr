# owo_engine.py
# Sealed OWO engine: the last gate before an EMS sensation reaches a person.
# OGP talks to the My OWO app (owo_link.py), which applies the user's own
# per-muscle calibration and drives the suit over Bluetooth; 100 % here is
# the user's calibrated maximum for that muscle.
#
# Every send goes through here, so nothing -- a buggy router, a test button,
# a hand-edited settings file -- gets past these rules:
#   * intensity is capped per muscle and overall at the user's ceilings,
#     which can't be set above ABSOLUTE_MAX;
#   * paused (the page's Stop) sends a stop and refuses every send;
#   * Off, the feature switch, VRChat going quiet and exit end everything
#     with a stop, sent twice;
#   * the OGP/Test floor is never applied to EMS.
#
# Sensations are short pulses that run out on their own (SENSATION_S), the
# way the vrc-owo-suit bridge drives the suit: one datagram per active muscle,
# its level as the sensation's intensity, re-sent every RESEND_S while held.
# A real change wakes the sender at once (the first send after idle never
# waits); back-to-back changes are spaced by MIN_SEND_GAP_S. If OGP dies the
# suit stops within one pulse.

import math
import threading
import time
from typing import Any, Callable, Dict, Optional

import owo_link
from owo_link import MUSCLES

ABSOLUTE_MAX = 100
SENSATION_S = 0.3
RESEND_S = 0.25            # < SENSATION_S, so a held muscle never gaps
MIN_SEND_GAP_S = 0.05
TEST_MAX = 20              # the page's Test button never goes above this
DEFAULT_FREQUENCY = 50

_RECONNECT_EVERY_S = 3.0
_POLL_S = 0.2
_CONNECT_TIMEOUT_S = 0.8


def _clamp_int(value, lo: int, hi: int, default: int) -> int:
    try:
        f = float(value)
    except (TypeError, ValueError):
        return default
    if not math.isfinite(f):
        return default
    return max(lo, min(hi, int(f)))


class OwoEngine:
    """Sealed: primitive public methods, all state private. Threadsafe."""

    def __init__(self, link_factory: Optional[Callable[[], Any]] = None,
                 log: Optional[Callable[[str], None]] = None):
        self._link_factory = link_factory or owo_link.OwoLink
        self._log = log or (lambda _m: None)
        self._state_callback: Callable[[], None] = lambda: None

        self._lock = threading.RLock()
        self._link = None
        self._host_setting = ""
        self._game_id = "0"
        self._want = False
        self._paused = False
        self._last_error = ""
        self._connect_lock = threading.Lock()

        self._active: Dict[str, int] = {}        # what the router wants
        self._frequency = DEFAULT_FREQUENCY
        self._caps: Dict[str, int] = {m: ABSOLUTE_MAX for m in MUSCLES}
        self._global_max = ABSOLUTE_MAX
        self._sending: Dict[str, int] = {}       # what went out last, after caps

        self._wake = threading.Event()
        self._stop_evt = threading.Event()
        self._supervisor: Optional[threading.Thread] = None
        self._sender: Optional[threading.Thread] = None

    # ---- status -------------------------------------------------------
    @property
    def is_connected(self) -> bool:
        return self._link is not None

    def status_snapshot(self) -> Dict[str, Any]:
        link = self._link
        with self._lock:
            sending = dict(self._sending)
        return {
            "connected": link is not None,
            "host": getattr(link, "host", None) if link is not None else None,
            "wanted": self._want,
            "paused": self._paused,
            "error": self._last_error,
            "active": sending,
            "frequency": self._frequency,
        }

    def set_state_callback(self, fn: Optional[Callable[[], None]]) -> None:
        """Called from background threads when the connection or pause
        state changes. Must be cheap and thread-safe."""
        self._state_callback = fn or (lambda: None)

    # ---- configuration -------------------------------------------------
    def set_host(self, host: str) -> None:
        """A fixed app address; blank = this PC first, then the network."""
        self._host_setting = str(host or "").strip()

    def set_game_id(self, game_id: str) -> None:
        self._game_id = str(game_id or "").strip() or "0"

    def set_caps(self, per_muscle: Dict[str, int], global_max: int) -> None:
        """User ceilings, clamped to ABSOLUTE_MAX so a hand-edited settings
        file can't widen them. A muscle missing from the map keeps the
        overall ceiling."""
        g = _clamp_int(global_max, 0, ABSOLUTE_MAX, 0)
        caps = {}
        for m in MUSCLES:
            caps[m] = _clamp_int((per_muscle or {}).get(m, g), 0, ABSOLUTE_MAX, 0)
        with self._lock:
            self._global_max = g
            self._caps = caps
        self._wake.set()

    def _capped(self, muscle: str, intensity: int) -> int:
        return max(0, min(intensity, self._caps.get(muscle, 0), self._global_max, ABSOLUTE_MAX))

    # ---- hot path (router thread) ----------------------------------------
    def set_active(self, muscles: Dict[str, int], frequency: int) -> None:
        """The muscles to hold now ({name: 0..100}) and the frequency. Garbage
        and non-finite values are dropped, never raised -- an exception here
        would leave the router's previous map re-sending."""
        new_active: Dict[str, int] = {}
        for name, value in (muscles or {}).items():
            if name not in owo_link.MUSCLE_INDEX:
                continue
            iv = _clamp_int(value, 0, ABSOLUTE_MAX, 0)
            if iv > 0:
                new_active[name] = iv
        freq = _clamp_int(frequency, 1, 100, DEFAULT_FREQUENCY)
        with self._lock:
            changed = new_active != self._active or freq != self._frequency
            self._active = new_active
            self._frequency = freq
        if changed:
            self._wake.set()

    def test_pulse(self, muscle: str, intensity: int = 10, duration_s: float = SENSATION_S) -> bool:
        """One short sensation on one muscle, from the page's Test button.
        Capped at TEST_MAX and the user's ceilings; refused while paused."""
        link = self._link
        if link is None or self._paused or muscle not in owo_link.MUSCLE_INDEX:
            return False
        with self._lock:
            level = self._capped(muscle, min(TEST_MAX, _clamp_int(intensity, 0, TEST_MAX, 0)))
            freq = self._frequency
        if level <= 0:
            return False
        micro = owo_link.sensation_text(freq, duration_s, level)
        return link.send(owo_link.build_sensation(self._game_id, micro, {muscle: 100}))

    def end_all(self) -> None:
        """Nothing held any more; a stop goes out twice."""
        with self._lock:
            self._active = {}
            self._sending = {}
        self._send_stop()
        self._wake.set()

    def set_paused(self, paused: bool) -> None:
        with self._lock:
            self._paused = bool(paused)
            if self._paused:
                self._active = {}
                self._sending = {}
        if paused:
            self._send_stop()
        self._wake.set()
        self._notify()

    @property
    def is_paused(self) -> bool:
        return self._paused

    # ---- lifecycle (cold path) -------------------------------------------
    def start(self, auto_connect: bool) -> None:
        self._want = bool(auto_connect)
        if self._supervisor is not None and self._supervisor.is_alive():
            return
        self._stop_evt = threading.Event()
        self._supervisor = threading.Thread(target=self._supervise, args=(self._stop_evt,),
                                            daemon=True, name="OWOSupervisor")
        self._sender = threading.Thread(target=self._send_loop, args=(self._stop_evt,),
                                        daemon=True, name="OWOSend")
        self._supervisor.start()
        self._sender.start()

    def stop(self) -> None:
        self._want = False
        self.disconnect()
        self._stop_evt.set()
        self._wake.set()
        for t in (self._supervisor, self._sender):
            if t is not None and t is not threading.current_thread():
                t.join(timeout=2.0)
        self._supervisor = self._sender = None

    def connect(self) -> None:
        """Look for My OWO now and stay connected."""
        self._want = True
        self._last_error = ""
        if self._supervisor is None or not self._supervisor.is_alive():
            self.start(True)
        else:
            threading.Thread(target=self._try_connect, daemon=True, name="OWOConnect").start()

    def disconnect(self) -> None:
        self._want = False
        link = self._link
        self.end_all()
        if link is not None:
            link.send(owo_link.build_unavailable(self._game_id))
        self._drop_link()
        self._notify()

    # ---- threads ----------------------------------------------------------
    def _supervise(self, stop: threading.Event) -> None:
        next_try = 0.0
        while not stop.is_set():
            link = self._link
            if link is None:
                if self._want and time.monotonic() >= next_try:
                    self._try_connect()
                    next_try = time.monotonic() + _RECONNECT_EVERY_S
                stop.wait(_POLL_S)
                continue
            msg = link.poll(_POLL_S)
            if msg == owo_link.APP_CLOSED and link is self._link:
                self._on_lost("My OWO closed")

    def _try_connect(self) -> None:
        if not self._connect_lock.acquire(blocking=False):
            return
        try:
            if self._link is not None or not self._want:
                return
            candidates = ([self._host_setting] if self._host_setting
                          else [owo_link.LOCALHOST, owo_link.BROADCAST])
            try:
                link = self._link_factory()
            except Exception as e:  # noqa: BLE001
                self._last_error = f"network error: {e}"
                return
            host = link.connect(candidates, self._game_id, _CONNECT_TIMEOUT_S)
            if host is None or not self._want:
                link.close()
                if self._want:
                    self._last_error = ("My OWO didn't answer at " + self._host_setting
                                        if self._host_setting else
                                        "My OWO not found (is the app open, on this PC or the same network?)")
                return
            with self._lock:
                self._link = link
                self._sending = {}
            self._last_error = ""
            self._log(f"OWO: connected to My OWO at {host}")
            self._notify()
            self._wake.set()
        finally:
            self._connect_lock.release()

    def _send_loop(self, stop: threading.Event) -> None:
        last_send = -1e18
        had_active = False
        while not stop.is_set():
            link = self._link
            with self._lock:
                active = {m: self._capped(m, v) for m, v in self._active.items()}
                active = {m: v for m, v in active.items() if v > 0}
                freq = self._frequency
                paused = self._paused
            if link is not None and active and not paused:
                # Real time, not the injectable clock: this paces the network.
                gap = time.monotonic() - last_send
                if gap < MIN_SEND_GAP_S:
                    time.sleep(MIN_SEND_GAP_S - gap)
                    continue        # re-read: the newest map goes out
                ok = True
                for muscle, level in active.items():
                    micro = owo_link.sensation_text(freq, SENSATION_S, level)
                    ok = link.send(owo_link.build_sensation(self._game_id, micro, {muscle: 100})) and ok
                with self._lock:
                    self._sending = active
                last_send = time.monotonic()
                had_active = True
                if not ok:
                    self._on_lost("send failed")
            elif had_active:
                had_active = False
                with self._lock:
                    self._sending = {}
                if link is not None:
                    # Release edge: end the pulse now instead of letting it
                    # run out its tail.
                    link.send(owo_link.build_stop(self._game_id))
            self._wake.wait(RESEND_S)
            self._wake.clear()

    # ---- helpers ------------------------------------------------------------
    def _send_stop(self) -> None:
        link = self._link
        if link is None:
            return
        stop = owo_link.build_stop(self._game_id)
        link.send(stop)
        link.send(stop)

    def _drop_link(self) -> None:
        with self._lock:
            link, self._link = self._link, None
            self._sending = {}
        if link is not None:
            link.close()

    def _on_lost(self, reason: str) -> None:
        self._drop_link()
        self._last_error = reason
        self._log(f"OWO: {reason}")
        self._notify()

    def _notify(self) -> None:
        try:
            self._state_callback()
        except Exception:  # noqa: BLE001
            pass
