# engine_base.py
# Shared *cold-path* connection lifecycle for a thread-driven sealed engine,
# ported from the full edition (`main`), where every reconnecting backend
# shares it. Here only the PSVR2 headset uses it; the shocker hub, the suits
# and the trackers keep their own small supervisors.
#
# It holds the boilerplate -- a connected flag, a last error, an
# auto-connect gate, a state-change callback, start()/stop(), and a backoff
# reconnect loop -- so an engine only implements its transport via
# `_open()` / `_close()` / `_available`.
#
# CRITICAL: this base governs the COLD path only -- connect / reconnect /
# disconnect. It never sits on an engine's hot send path; each engine's
# actual device output stays entirely on the subclass. See ARCHITECTURE.md
# "Latency budget".
#
# (main also has an asyncio flavour for the Coyote's Bluetooth link; nothing
# in this edition needs it, so it was left out.)

import threading
from typing import Callable, Optional


# ======================================================================
# Thread-driven
# ======================================================================

class ReconnectingEngine:
    """Cold-path connection supervisor for a thread-driven sealed engine.

    Owns the connected/last_error flags, the auto-connect gate, the
    state-change callback, start()/stop(), and a backoff reconnect loop.
    Subclasses implement the transport:

      * ``_available`` (property) — is the transport usable (lib importable)?
      * ``_open()``  — establish ONE connection; set ``self._connected = True``
        on success and do any per-connection setup (e.g. spawn a recv thread).
        Raise on failure. Do NOT notify — the loop notifies once after success.
      * ``_close()`` — tear down the live connection; idempotent.

    Public surface (primitive-only, keeps the sealed-box rule): ``is_connected``,
    ``is_available``, ``last_error``, ``set_auto_connect_getter``,
    ``set_state_callback``, ``start``, ``stop``, ``manual_connect``.
    """

    def __init__(self, name: str, *,
                 backoff_start: float = 1.0,
                 backoff_max: float = 10.0,
                 backoff_factor: float = 1.5,
                 sleep: Optional[Callable[[float], None]] = None):
        self._name = name
        self._stop = threading.Event()
        self._conn_thread: Optional[threading.Thread] = None
        self._connected = False
        self._last_error: Optional[str] = None
        self._auto_connect_getter: Callable[[], bool] = lambda: False
        self._state_callback: Optional[Callable[[], None]] = None
        self._backoff_start = backoff_start
        self._backoff_max = backoff_max
        self._backoff_factor = backoff_factor
        # Serializes every _open() attempt (manual button vs reconnect loop)
        # so two callers can never open concurrent connections.
        self._connect_lock = threading.Lock()
        # True while a manual_connect() session is live: the reconnect loop
        # must not tear such a link down just because auto-connect is off.
        self._manual_hold = False
        # Injectable so the reconnect loop is testable without real time.
        # Default is a stop-aware wait so stop() interrupts any backoff sleep.
        self._sleep = sleep if sleep is not None else self._stop_aware_sleep

    def _stop_aware_sleep(self, seconds: float) -> None:
        self._stop.wait(seconds)

    # ---- Public status ------------------------------------------------
    @property
    def is_connected(self) -> bool:
        return self._connected

    @property
    def is_available(self) -> bool:
        return self._available

    @property
    def last_error(self) -> Optional[str]:
        return self._last_error

    def set_auto_connect_getter(self, fn: Callable[[], bool]) -> None:
        self._auto_connect_getter = fn or (lambda: False)

    def set_state_callback(self, fn: Optional[Callable[[], None]]) -> None:
        """Register a callback fired (from background threads) whenever the
        connection state changes. Must be cheap and threadsafe — typically it
        posts a message onto the controller's thread queue."""
        self._state_callback = fn

    # ---- Lifecycle ----------------------------------------------------
    def start(self) -> None:
        old = self._conn_thread
        if old is not None and old.is_alive():
            if not self._stop.is_set():
                return  # supervisor already running
            # A stopping thread is still draining — give it a moment. If it
            # is wedged inside a blocking _open(), the fresh stop event below
            # guarantees it can never be revived by our clear.
            old.join(timeout=1.0)
        # Fresh event per supervisor generation: the loop captures it at
        # entry, so a lingering old thread keeps seeing its own (set) event.
        self._stop = threading.Event()
        self._conn_thread = threading.Thread(
            target=self._reconnect_loop, daemon=True,
            name=f"{self._name}Reconnect")
        self._conn_thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._manual_hold = False
        try:
            self._close()
        except Exception:
            pass

    def manual_connect(self) -> bool:
        """One-shot blocking connect — for the UI 'Connect' button. Returns
        True if connected (already or freshly). A manual session is latched:
        the reconnect loop will not tear it down while auto-connect is off."""
        if not self._available:
            self._last_error = self._unavailable_reason
            return False
        with self._connect_lock:
            if self._connected:
                self._manual_hold = True
                return True
            try:
                self._open()
            except Exception as e:
                self._last_error = str(e)
                self._connected = False
                return False
            if self._stop.is_set():
                # stop() raced our open — don't hand back a live link that
                # no supervisor will ever manage or close again.
                try:
                    self._close()
                except Exception:
                    pass
                return False
            self._last_error = None
            self._manual_hold = True
            self._notify_state_change()
            return True

    def _reconnect_loop(self) -> None:
        stop = self._stop  # bound to this supervisor generation
        backoff = self._backoff_start
        while not stop.is_set():
            if not self._available:
                self._sleep(5.0)
                continue
            if not self._auto_connect_getter():
                # Auto-connect disabled: drop links the LOOP opened, but keep
                # a manual_connect() session alive until it drops on its own.
                if self._connected:
                    if not self._manual_hold:
                        with self._connect_lock:
                            if self._connected and not self._manual_hold:
                                try:
                                    self._close()
                                except Exception:
                                    pass
                else:
                    self._manual_hold = False  # manual session ended
                self._sleep(1.0)
                continue
            if self._connected:
                self._sleep(1.0)
                continue
            try:
                with self._connect_lock:
                    if not self._connected:
                        self._open()
                        self._last_error = None
                        self._manual_hold = False  # loop-owned link
                        self._notify_state_change()
                backoff = self._backoff_start
                if stop.is_set() and self._connected:
                    # stop() raced our open — tear the fresh link down.
                    try:
                        self._close()
                    except Exception:
                        pass
                    break
            except Exception as e:
                self._last_error = str(e)
                self._connected = False
                self._sleep(backoff)
                backoff = min(backoff * self._backoff_factor, self._backoff_max)

    def _notify_state_change(self) -> None:
        cb = self._state_callback
        if cb is None:
            return
        try:
            cb()
        except Exception:
            pass

    # ---- Subclass hooks ----------------------------------------------
    @property
    def _available(self) -> bool:
        """Override when the transport library may be missing."""
        return True

    @property
    def _unavailable_reason(self) -> str:
        return f"{self._name} transport unavailable"

    def _open(self) -> None:
        raise NotImplementedError

    def _close(self) -> None:
        pass


