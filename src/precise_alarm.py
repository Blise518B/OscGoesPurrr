# OscGoesPurrr - an alarm that keeps to the millisecond
"""PreciseAlarm -- one pending ring at a time, on time, on its own thread.

Made for the routing tick (main.py), whose steady beat is what the router's
speed and punch detectors measure change against.

Why not a QTimer: on Windows, Qt keeps a timer to the millisecond only
through the system's multimedia timers, and a process gets 16 of those. Past
16 running timers, every new one falls back to Windows' 15.6 ms clock step.
OGP's pages run more than that, so the "90 Hz" routing tick really ticked at
64 Hz (measured 2026-11-13). Python's own timed waits (Event.wait,
Condition.wait, Lock.acquire) round to the same step. The one wait that keeps
time is a high-resolution waitable timer -- what time.sleep uses since Python
3.11 -- so on Windows the alarm is one of those, armed from any thread and
waited on by a thread of its own. Elsewhere (the Linux AppImage) a Condition's
timed wait is already precise.

`ring` runs on the alarm's thread: hand the work to where it belongs (the
routing tick posts itself to the UI thread with ui.schedule_callback). Pure
Python + ctypes, no Qt.
"""

import sys
import threading
import time
from typing import Callable, Optional

import debug_log


class PreciseAlarm:
    """`set(ms)` arms the alarm `ms` from now -- the newest call wins, as for
    a restarted single-shot timer; `cancel()` disarms it. The thread starts
    with the first `set`."""

    def __init__(self, ring: Callable[[], None], name: str = "OGP alarm") -> None:
        self._ring = ring
        self._name = name
        self._lock = threading.Lock()
        self._thread: Optional[threading.Thread] = None
        self._closed = False
        self._win = _WinTimer.make() if sys.platform == "win32" else None
        # The Condition variant's state (used where there is no _WinTimer).
        self._cond = threading.Condition(self._lock)
        self._due: Optional[float] = None

    # ------------------------------------------------------------------ API
    def set(self, delay_ms: float) -> None:
        if self._closed:
            return
        self._start()
        if self._win is not None:
            self._win.arm(delay_ms)
            return
        with self._cond:
            self._due = time.monotonic() + max(0.0, delay_ms) / 1000.0
            self._cond.notify()

    def cancel(self) -> None:
        if self._win is not None:
            self._win.disarm()
            return
        with self._cond:
            self._due = None
            self._cond.notify()

    def close(self) -> None:
        """Stop the thread for good (app exit). Idempotent."""
        self._closed = True
        if self._win is not None:
            self._win.stop()
        else:
            with self._cond:
                self._due = None
                self._cond.notify()

    # ------------------------------------------------------------- internals
    def _start(self) -> None:
        if self._thread is not None:
            return
        with self._lock:
            if self._thread is not None:
                return
            target = self._run_win if self._win is not None else self._run_cond
            self._thread = threading.Thread(target=target, name=self._name, daemon=True)
            self._thread.start()

    def _fire(self) -> None:
        try:
            self._ring()
        except Exception:
            debug_log.get_logger().exception("%s: ring failed", self._name)

    def _run_win(self) -> None:
        win = self._win
        while not self._closed:
            if not win.wait():
                break               # stopped, or the wait itself failed
            self._fire()
        win.close()

    def _run_cond(self) -> None:
        with self._cond:
            while not self._closed:
                if self._due is None:
                    self._cond.wait()
                    continue
                left = self._due - time.monotonic()
                if left > 0:
                    self._cond.wait(left)
                    continue
                self._due = None
                self._cond.release()
                try:
                    self._fire()
                finally:
                    self._cond.acquire()


class _WinTimer:
    """A high-resolution waitable timer plus a stop event (kernel32)."""

    _CREATE_HIGH_RESOLUTION = 0x00000002
    _TIMER_ALL_ACCESS = 0x1F0003
    _INFINITE = 0xFFFFFFFF

    @classmethod
    def make(cls) -> Optional["_WinTimer"]:
        try:
            return cls()
        except Exception:
            debug_log.get_logger().warning(
                "PreciseAlarm: no waitable timer, using a Condition", exc_info=True)
            return None

    def __init__(self) -> None:
        import ctypes
        from ctypes import wintypes
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.CreateWaitableTimerExW.argtypes = (
            ctypes.c_void_p, wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD)
        k32.CreateWaitableTimerExW.restype = wintypes.HANDLE
        k32.SetWaitableTimer.argtypes = (
            wintypes.HANDLE, ctypes.POINTER(ctypes.c_longlong), wintypes.LONG,
            ctypes.c_void_p, ctypes.c_void_p, wintypes.BOOL)
        k32.SetWaitableTimer.restype = wintypes.BOOL
        k32.CancelWaitableTimer.argtypes = (wintypes.HANDLE,)
        k32.CancelWaitableTimer.restype = wintypes.BOOL
        k32.CreateEventW.argtypes = (
            ctypes.c_void_p, wintypes.BOOL, wintypes.BOOL, wintypes.LPCWSTR)
        k32.CreateEventW.restype = wintypes.HANDLE
        k32.SetEvent.argtypes = (wintypes.HANDLE,)
        k32.SetEvent.restype = wintypes.BOOL
        k32.WaitForMultipleObjects.argtypes = (
            wintypes.DWORD, ctypes.POINTER(wintypes.HANDLE), wintypes.BOOL, wintypes.DWORD)
        k32.WaitForMultipleObjects.restype = wintypes.DWORD
        k32.CloseHandle.argtypes = (wintypes.HANDLE,)
        k32.CloseHandle.restype = wintypes.BOOL
        self._ctypes = ctypes
        self._k32 = k32
        # An auto-reset (synchronization) timer: each ring wakes one wait.
        timer = k32.CreateWaitableTimerExW(
            None, None, self._CREATE_HIGH_RESOLUTION, self._TIMER_ALL_ACCESS)
        if not timer:
            # Windows before 10 1803: a plain timer still beats a QTimer slot.
            timer = k32.CreateWaitableTimerExW(None, None, 0, self._TIMER_ALL_ACCESS)
        stop = k32.CreateEventW(None, True, False, None)   # manual reset
        if not timer or not stop:
            for h in (timer, stop):
                if h:
                    k32.CloseHandle(h)
            raise OSError(ctypes.get_last_error(), "CreateWaitableTimerExW / CreateEventW")
        self._timer, self._stop = timer, stop
        self._handles = (wintypes.HANDLE * 2)(timer, stop)
        self._closed = False

    def arm(self, delay_ms: float) -> None:
        # Relative due times are negative, in 100 ns steps; re-arming an
        # armed timer replaces its due time.
        due = self._ctypes.c_longlong(-max(1, int(delay_ms * 10_000)))
        self._k32.SetWaitableTimer(self._timer, self._ctypes.byref(due), 0, None, None, False)

    def disarm(self) -> None:
        self._k32.CancelWaitableTimer(self._timer)

    def wait(self) -> bool:
        """Block until the timer rings (True) or stop() (False). ctypes lets
        go of the GIL for the call."""
        r = self._k32.WaitForMultipleObjects(2, self._handles, False, self._INFINITE)
        return r == 0

    def stop(self) -> None:
        self._k32.SetEvent(self._stop)

    def close(self) -> None:
        if not self._closed:
            self._closed = True
            self._k32.CloseHandle(self._timer)
            self._k32.CloseHandle(self._stop)
