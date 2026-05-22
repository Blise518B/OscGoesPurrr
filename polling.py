"""PollingThread — daemon-thread skeleton shared by the routers and the
hardware monitor.

Each subclass implements `_run()` (the loop body). The base class owns the
threading lifecycle (start/stop, alive guard, stop event) and provides
`_interruptible_sleep()` so a slow tick interval can still shut down
promptly when `stop()` is called.
"""

import threading
import time
from typing import Optional


class PollingThread:
    """Daemon-thread skeleton for stateless polling loops.

    Subclasses MUST implement `_run()` and check `self._stop.is_set()` in
    the loop. Use `self._interruptible_sleep(seconds)` between ticks
    instead of `time.sleep()` so shutdown is responsive.
    """

    def __init__(self, name: str):
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._thread_name = name

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run, daemon=True, name=self._thread_name
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _run(self) -> None:
        raise NotImplementedError

    def _interruptible_sleep(self, total_s: float, slice_s: float = 0.1) -> None:
        """Sleep up to `total_s` seconds, returning early when stop() fires.
        Slices the wait so the main loop sees the stop signal within
        `slice_s` of it being raised, regardless of how long `total_s` is.
        """
        if total_s <= 0:
            return
        slept = 0.0
        while slept < total_s and not self._stop.is_set():
            step = min(slice_s, total_s - slept)
            time.sleep(step)
            slept += step
