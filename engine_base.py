# engine_base.py
# Shared *cold-path* connection-lifecycle for the sealed haptic engines.
#
# Every reconnecting engine (bHaptics WebSocket, OWO TCP listener, PiShock
# serial, Coyote BLE) repeats the same machinery: a connected flag, a last
# error, an auto-connect gate, a state-change callback, start()/stop(), and a
# backoff reconnect loop. That boilerplate lives here so each engine only
# implements its transport via `_open()` / `_close()` / `_available`.
#
# CRITICAL: this base governs the COLD path only — connect / reconnect /
# disconnect. It never sits on an engine's hot send path. Each engine's actual
# device output (submit_dot_frame, the B0 BLE frame, socket.send, serial write)
# stays entirely on the subclass and is never routed through here. See
# ARCHITECTURE.md "Latency budget".
#
# Two flavours share one contract:
#   * ReconnectingEngine       — thread-driven (bHaptics, OWO, PiShock-serial).
#   * AsyncReconnectingEngine  — asyncio-driven, owns its own loop thread
#                                (Coyote / bleak).

import asyncio
import threading
import time
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
                 sleep: Callable[[float], None] = time.sleep):
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
        # Injectable so the reconnect loop is testable without real time.
        self._sleep = sleep

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
        if self._conn_thread is not None and self._conn_thread.is_alive():
            return
        self._stop.clear()
        self._conn_thread = threading.Thread(
            target=self._reconnect_loop, daemon=True,
            name=f"{self._name}Reconnect")
        self._conn_thread.start()

    def stop(self) -> None:
        self._stop.set()
        try:
            self._close()
        except Exception:
            pass

    def manual_connect(self) -> bool:
        """One-shot blocking connect — for the UI 'Connect' button. Returns
        True if connected (already or freshly)."""
        if not self._available:
            self._last_error = self._unavailable_reason
            return False
        if self._connected:
            return True
        try:
            self._open()
            self._last_error = None
            self._notify_state_change()
            return True
        except Exception as e:
            self._last_error = str(e)
            self._connected = False
            return False

    def _reconnect_loop(self) -> None:
        backoff = self._backoff_start
        while not self._stop.is_set():
            if not self._available:
                self._sleep(5.0)
                continue
            if not self._auto_connect_getter():
                # Auto-connect disabled: drop any live link and idle.
                if self._connected:
                    try:
                        self._close()
                    except Exception:
                        pass
                self._sleep(1.0)
                continue
            if self._connected:
                self._sleep(1.0)
                continue
            try:
                self._open()
                self._last_error = None
                self._notify_state_change()
                backoff = self._backoff_start
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


# ======================================================================
# Asyncio-driven (owns its own event-loop thread)
# ======================================================================

class AsyncReconnectingEngine:
    """Cold-path connection supervisor for an asyncio-driven sealed engine.

    Same public surface and contract as ReconnectingEngine, but the reconnect
    loop is an asyncio task on an event loop the engine owns (a daemon thread).
    Subclasses implement async ``_open()`` / ``_close()`` and may start their
    own per-connection tasks (e.g. Coyote's ~100 ms B0 sender) inside ``_open``.

    Use ``self._loop`` + ``run_coroutine_threadsafe`` (helper
    ``self._submit(coro)``) to push hot commands from router threads onto the
    engine loop without blocking them.
    """

    def __init__(self, name: str, *,
                 backoff_start: float = 1.0,
                 backoff_max: float = 10.0,
                 backoff_factor: float = 1.5):
        self._name = name
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._loop_thread: Optional[threading.Thread] = None
        self._stop_evt: Optional[asyncio.Event] = None
        self._connected = False
        self._last_error: Optional[str] = None
        self._auto_connect_getter: Callable[[], bool] = lambda: False
        self._state_callback: Optional[Callable[[], None]] = None
        self._backoff_start = backoff_start
        self._backoff_max = backoff_max
        self._backoff_factor = backoff_factor
        self._ready = threading.Event()

    # ---- Public status (identical surface to the thread engine) -------
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
        self._state_callback = fn

    # ---- Lifecycle ----------------------------------------------------
    def start(self) -> None:
        if self._loop_thread is not None and self._loop_thread.is_alive():
            return
        self._ready.clear()
        self._loop_thread = threading.Thread(
            target=self._run_loop, daemon=True, name=f"{self._name}Loop")
        self._loop_thread.start()
        # Wait until the loop + reconnect task are live so callers can submit
        # work immediately after start() returns.
        self._ready.wait(timeout=5.0)

    def _run_loop(self) -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        self._loop = loop
        self._stop_evt = asyncio.Event()
        loop.create_task(self._reconnect_loop())
        self._ready.set()
        try:
            loop.run_forever()
        finally:
            try:
                loop.run_until_complete(loop.shutdown_asyncgens())
            except Exception:
                pass
            loop.close()

    def stop(self) -> None:
        loop = self._loop
        if loop is None:
            return
        try:
            loop.call_soon_threadsafe(
                lambda: asyncio.ensure_future(self._stop_async()))
        except Exception:
            pass

    async def _stop_async(self) -> None:
        if self._stop_evt is not None:
            self._stop_evt.set()
        await self._safe_close()
        loop = self._loop
        if loop is not None:
            loop.stop()

    async def _reconnect_loop(self) -> None:
        backoff = self._backoff_start
        while self._stop_evt is None or not self._stop_evt.is_set():
            if not self._available:
                await asyncio.sleep(5.0)
                continue
            if not self._auto_connect_getter():
                if self._connected:
                    await self._safe_close()
                await asyncio.sleep(1.0)
                continue
            if self._connected:
                await asyncio.sleep(1.0)
                continue
            try:
                await self._open()
                self._last_error = None
                self._notify_state_change()
                backoff = self._backoff_start
            except Exception as e:
                self._last_error = str(e)
                self._connected = False
                await asyncio.sleep(backoff)
                backoff = min(backoff * self._backoff_factor, self._backoff_max)

    async def _safe_close(self) -> None:
        try:
            await self._close()
        except Exception:
            pass

    def _submit(self, coro) -> None:
        """Fire-and-forget a coroutine onto the engine loop from another
        thread. Used by router threads to push hot commands without blocking.
        Holds no reference to the future (errors are handled inside `coro`)."""
        loop = self._loop
        if loop is None:
            return
        try:
            asyncio.run_coroutine_threadsafe(coro, loop)
        except Exception:
            pass

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
        return True

    async def _open(self) -> None:
        raise NotImplementedError

    async def _close(self) -> None:
        pass
