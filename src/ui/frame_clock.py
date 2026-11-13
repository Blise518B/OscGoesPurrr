"""One shared repaint clock for everything that moves with the signal.

The live meters and graphs get new values at the router's rate (90 Hz by
default) and used to repaint on every one. They now ask this clock
instead (`request(widget)`): it repaints each waiting widget once per
frame --

* `FOCUSED_FPS` while OGP is the active application,
* `UNFOCUSED_FPS` while another window has the focus. Never zero: OGP
  is watched in a VR overlay while VRChat has the focus, and a frozen
  overlay would be wrong. Windows doesn't say whether a window is
  covered, so "unfocused" is all there is to go on.
* nothing while the window is minimized or hidden to the tray. The
  widgets keep their newest value, and the window paints them all when
  it comes back.

Only the repaint waits; a widget stores its value at once, so reading it
back (and everything haptic) is unaffected. Measured 2026-11-05 on Home
with two toys playing at 90 Hz: ~1,540 paint events a second before,
~115 focused and ~50 unfocused after (the mini meters there also paint
their own ground, so the frame behind them stays put).
"""

import time
from typing import Callable, Dict

import shiboken6
from PySide6.QtCore import QObject, Qt, QTimer
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QWidget

FOCUSED_FPS = 60
UNFOCUSED_FPS = 20
# Off screen, the clock rests this long between looks instead of waking
# every frame to find nothing to paint; the window coming back wakes it.
REST_S = 0.5


def window_on_screen(widget: QWidget) -> bool:
    """Whether `widget`'s window is shown and not minimized -- the most
    Windows tells an app about being seen."""
    try:
        win = widget.window()
        return win.isVisible() and not win.isMinimized()
    except RuntimeError:            # the C++ widget is gone
        return False


def when_on_screen(host, fn: Callable[[], None]) -> Callable[[], None]:
    """`fn` for a page's periodic refresh timer, skipped while the window is
    minimized or hidden to the tray (ARCHITECTURE.md, "hidden pages do no
    background work"). `host` is a widget on the page, or the UI object
    whose `window` is the main window. The page catches up when the window
    comes back (OscGoesPurrrUI._on_window_restored)."""
    def tick() -> None:
        win = host if isinstance(host, QWidget) else getattr(host, "window", None)
        if isinstance(win, QWidget) and not window_on_screen(win):
            return
        fn()
    return tick


class FrameClock(QObject):
    """See the module docstring. One per application (`clock()`)."""

    def __init__(self) -> None:
        super().__init__()
        self._waiting: Dict[int, QWidget] = {}
        self._rest_until = 0.0
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setTimerType(Qt.PreciseTimer)
        self._timer.timeout.connect(self._flush)

    @staticmethod
    def frame_ms() -> int:
        active = QGuiApplication.applicationState() == Qt.ApplicationActive
        return int(round(1000.0 / (FOCUSED_FPS if active else UNFOCUSED_FPS)))

    def request(self, widget: QWidget) -> None:
        """Repaint `widget` with the next frame."""
        if self._rest_until and time.monotonic() < self._rest_until:
            return          # off screen: it shows its newest value when back
        self._waiting[id(widget)] = widget
        if not self._timer.isActive():
            self._timer.start(self.frame_ms())

    def wake(self) -> None:
        """The window is back on screen: stop resting at once."""
        self._rest_until = 0.0

    def _flush(self) -> None:
        waiting, self._waiting = self._waiting, {}
        shown = {}
        for w in waiting.values():
            if not shiboken6.isValid(w):
                continue
            win = w.window()
            key = id(win)
            if key not in shown:
                shown[key] = window_on_screen(win)
            if shown[key]:
                w.update()
        # Nothing it was asked for is on screen (minimized, in the tray):
        # rest instead of waking every frame for nothing.
        self._rest_until = (0.0 if any(shown.values()) or not shown
                            else time.monotonic() + REST_S)


_clock = None


def clock() -> FrameClock:
    global _clock
    if _clock is None or not shiboken6.isValid(_clock):
        _clock = FrameClock()
    return _clock


def request(widget: QWidget) -> None:
    """Repaint `widget` with the next frame (see the module docstring)."""
    clock().request(widget)


def wake() -> None:
    """A window came back on screen (MainWindow's restore)."""
    clock().wake()
