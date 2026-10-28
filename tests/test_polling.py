"""PollingThread's lifecycle: a thread switched off and straight back on
(within one sleep slice) must come back running, not stay dead."""

import time

from polling import PollingThread


class Loop(PollingThread):
    def __init__(self):
        super().__init__("TestLoop")
        self.ticks = 0

    def _run(self):
        while not self._stop.is_set():
            self.ticks += 1
            self._interruptible_sleep(0.05, slice_s=0.05)


def test_stop_then_start_at_once_keeps_it_running():
    loop = Loop()
    loop.start()
    time.sleep(0.02)
    loop.stop()
    loop.start()            # before the old loop has noticed the stop
    time.sleep(0.15)
    try:
        assert loop._thread.is_alive()
        before = loop.ticks
        time.sleep(0.15)
        assert loop.ticks > before
    finally:
        loop.stop()


def test_start_twice_is_one_thread():
    loop = Loop()
    loop.start()
    first = loop._thread
    loop.start()
    try:
        assert loop._thread is first
    finally:
        loop.stop()
