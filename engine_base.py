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
from concurrent.futures import TimeoutError as FutureTimeoutError
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
        self._reconnect_task: Optional[asyncio.Task] = None
        self._connected = False
        self._last_error: Optional[str] = None
        self._auto_connect_getter: Callable[[], bool] = lambda: False
        self._state_callback: Optional[Callable[[], None]] = None
        self._backoff_start = backoff_start
        self._backoff_max = backoff_max
        self._backoff_factor = backoff_factor
        self._ready = threading.Event()
        # Mirrors the thread flavour: serializes _open() attempts on the
        # engine loop, and latches manual sessions against auto-teardown.
        # The lock is (re)created per loop generation in _run_loop — an
        # asyncio.Lock pins itself to the loop it first WAITS on and can
        # never migrate, so a __init__-built lock would raise
        # "bound to a different event loop" after a stop()/start() cycle.
        self._connect_lock: Optional[asyncio.Lock] = None
        self._manual_hold = False
        # True from stop() until the next start() spawns a fresh loop, so
        # start() can tell "already running" apart from "still draining".
        self._stopping = False

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
        old = self._loop_thread
        if old is not None and old.is_alive():
            if not self._stopping:
                return  # supervisor already running
            # A stop is draining (a BLE teardown can take seconds). Wait for
            # the old loop thread so this start() can't be silently no-op'd
            # — otherwise a quick feature off/on left the engine permanently
            # dead ("engine is not running").
            old.join(timeout=5.0)
        self._stopping = False
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
        # Per-generation primitives: both pin to THIS loop, so a lingering
        # previous generation can never contaminate or be revived by them.
        self._stop_evt = asyncio.Event()
        self._connect_lock = asyncio.Lock()
        self._reconnect_task = loop.create_task(self._reconnect_loop())
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
        self._stopping = True
        # Capture THIS generation's primitives: if a new start() spawns a
        # fresh loop before the queued shutdown runs, the old teardown must
        # not set the new generation's stop event or cancel its task.
        stop_evt = self._stop_evt
        task = self._reconnect_task
        try:
            loop.call_soon_threadsafe(
                lambda: asyncio.ensure_future(self._stop_async(stop_evt, task)))
        except Exception:
            pass

    async def _stop_async(self, stop_evt: Optional[asyncio.Event],
                          task: Optional[asyncio.Task]) -> None:
        if stop_evt is not None:
            stop_evt.set()
        self._manual_hold = False
        # Cancel the reconnect task so it isn't destroyed mid-sleep when the
        # loop stops (avoids the "Task was destroyed but it is pending" spew).
        if task is not None and not task.done():
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass
        await self._safe_close()
        # Stop the loop we are actually running on — self._loop may already
        # point at a newer generation.
        asyncio.get_running_loop().stop()

    def manual_connect(self, timeout: float = 15.0) -> bool:
        """One-shot blocking connect — for the UI 'Connect' button. Same
        contract as ReconnectingEngine.manual_connect: returns True if
        connected (already or freshly), and latches the manual session so the
        reconnect loop won't tear it down while auto-connect is off."""
        if not self._available:
            self._last_error = self._unavailable_reason
            return False
        if self._connected:
            self._manual_hold = True
            return True
        loop = self._loop
        if loop is None or not loop.is_running():
            self._last_error = f"{self._name} engine is not running"
            return False
        fut = None
        try:
            fut = asyncio.run_coroutine_threadsafe(
                self._manual_connect_async(), loop)
            return bool(fut.result(timeout=timeout))
        except FutureTimeoutError:
            # Cancel the attempt: without this the coroutine keeps running
            # and can silently connect + latch AFTER we reported failure.
            if fut is not None:
                fut.cancel()
            self._last_error = f"{self._name} connect timed out"
            return False
        except Exception as e:
            self._last_error = str(e)
            return False

    async def _manual_connect_async(self) -> bool:
        async with self._connect_lock:
            if self._connected:
                self._manual_hold = True
                return True
            try:
                await self._open()
            except Exception as e:
                self._last_error = str(e)
                self._connected = False
                return False
            if self._stop_evt is not None and self._stop_evt.is_set():
                # stop() raced our open — don't hand back a live link the
                # supervisor will never manage again.
                await self._safe_close()
                return False
            self._last_error = None
            self._manual_hold = True
            self._notify_state_change()
            return True

    async def _reconnect_loop(self) -> None:
        backoff = self._backoff_start
        while self._stop_evt is None or not self._stop_evt.is_set():
            if not self._available:
                await asyncio.sleep(5.0)
                continue
            if not self._auto_connect_getter():
                # Auto-connect disabled: drop links the LOOP opened, but keep
                # a manual_connect() session alive until it drops on its own.
                if self._connected:
                    if not self._manual_hold:
                        async with self._connect_lock:
                            if self._connected and not self._manual_hold:
                                await self._safe_close()
                else:
                    self._manual_hold = False  # manual session ended
                await asyncio.sleep(1.0)
                continue
            if self._connected:
                await asyncio.sleep(1.0)
                continue
            try:
                async with self._connect_lock:
                    if not self._connected:
                        await self._open()
                        self._last_error = None
                        self._manual_hold = False  # loop-owned link
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
        Holds no reference to the future (errors are handled inside `coro`).
        Closes the coroutine when the loop is unavailable so it never dies
        with a "never awaited" RuntimeWarning."""
        loop = self._loop
        if loop is None or not loop.is_running():
            # Covers stopped-but-not-yet-closed too: scheduling onto a
            # merely-stopped loop "succeeds" but the callback never runs and
            # the coroutine dies un-awaited. (is_running() is a benign race
            # — worst case the except below closes the coroutine instead.)
            coro.close()
            return
        try:
            asyncio.run_coroutine_threadsafe(coro, loop)
        except Exception:
            try:
                coro.close()
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

    @property
    def _unavailable_reason(self) -> str:
        return f"{self._name} transport unavailable"

    async def _open(self) -> None:
        raise NotImplementedError

    async def _close(self) -> None:
        pass
