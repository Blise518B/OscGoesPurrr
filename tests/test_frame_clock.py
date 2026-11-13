"""The live meters and graphs repaint once per screen frame, slower while OGP
isn't focused and not at all while its window is minimized or in the tray
(ui/frame_clock.py); page timers skip their work off screen; Home's mini
meters paint their own ground so the toy frame behind them stays put."""

import sys
import time

import pytest
from PySide6.QtCore import QEventLoop, Qt, QTimer
from PySide6.QtGui import QColor, QGuiApplication
from PySide6.QtWidgets import QApplication, QWidget

from ui import frame_clock, theme
from ui.widgets import MainWindow, RainbowMeter


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication(sys.argv[:1])


def pump(ms):
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


def counted(widget):
    """Record the clock's update() calls on `widget`."""
    calls = []
    widget.update = lambda *a: calls.append(time.monotonic())
    return calls


@pytest.fixture
def shown(qapp):
    win = QWidget()
    win.resize(200, 60)
    child = QWidget(win)
    child.resize(100, 20)
    win.show()
    pump(20)
    frame_clock.wake()                      # a test before may have left it resting
    yield win, child
    win.close()


def test_requests_repaint_once_with_the_next_frame(shown):
    _win, child = shown
    calls = counted(child)
    for _ in range(5):                      # the router's pushes inside one frame
        frame_clock.request(child)
    assert calls == []                      # not at once
    pump(frame_clock.FrameClock.frame_ms() + 40)
    assert len(calls) == 1


def test_no_repaint_while_minimized_or_hidden(shown):
    win, child = shown
    calls = counted(child)
    win.showMinimized()
    frame_clock.request(child)
    pump(frame_clock.FrameClock.frame_ms() + 40)
    assert calls == []
    win.showNormal()
    win.hide()
    frame_clock.request(child)
    pump(frame_clock.FrameClock.frame_ms() + 40)
    assert calls == []


def test_rests_off_screen_and_wakes_when_back(shown):
    win, child = shown
    clock = frame_clock.clock()
    win.showMinimized()
    frame_clock.request(child)
    pump(frame_clock.FrameClock.frame_ms() + 40)
    frame_clock.request(child)               # resting: no timer for nothing
    assert not clock._timer.isActive()
    win.showNormal()                         # the app's MainWindow calls wake()
    frame_clock.wake()
    calls = counted(child)
    frame_clock.request(child)
    pump(frame_clock.FrameClock.frame_ms() + 40)
    assert len(calls) == 1


def test_frame_rate_follows_focus(qapp, monkeypatch):
    monkeypatch.setattr(QGuiApplication, "applicationState",
                        staticmethod(lambda: Qt.ApplicationActive))
    assert frame_clock.FrameClock.frame_ms() == round(1000 / frame_clock.FOCUSED_FPS)
    monkeypatch.setattr(QGuiApplication, "applicationState",
                        staticmethod(lambda: Qt.ApplicationInactive))
    # Slower, never stopped: OGP is watched in VR overlays while VRChat
    # has the focus.
    assert frame_clock.FrameClock.frame_ms() == round(1000 / frame_clock.UNFOCUSED_FPS)
    assert 0 < frame_clock.UNFOCUSED_FPS < frame_clock.FOCUSED_FPS


def test_page_timers_skip_their_work_off_screen(shown):
    win, child = shown
    ran = []
    tick = frame_clock.when_on_screen(child, lambda: ran.append(1))
    tick()
    win.showMinimized()
    tick()
    win.showNormal()
    win.hide()
    tick()
    assert ran == [1]

    class Host:                              # a view mixin: `window` is the main window
        window = win
    win.show()
    frame_clock.when_on_screen(Host(), lambda: ran.append(2))()
    assert ran == [1, 2]


def test_main_window_reports_coming_back(qapp):
    win = MainWindow()
    back = []
    win.set_restore_handler(lambda: back.append(1))
    win.show()
    pump(10)
    back.clear()
    win.showMinimized()
    pump(10)
    win.showNormal()
    pump(10)
    assert back == [1]                       # from minimized
    win.hide()
    win.show()
    pump(10)
    assert back == [1, 1]                    # from the tray
    win.allow_close()
    win.close()


def test_meter_value_is_read_back_at_once(qapp):
    m = RainbowMeter(maximum=1000)
    m.setValue(420)
    assert m.value() == 420


def test_meter_with_a_ground_paints_its_corners(qapp):
    m = RainbowMeter(maximum=1000)
    m.resize(56, 10)
    assert not m.testAttribute(Qt.WA_OpaquePaintEvent)
    m.set_ground(lambda: "#123456")
    assert m.testAttribute(Qt.WA_OpaquePaintEvent)
    m.setValue(500)
    img = m.grab().toImage()
    assert img.pixelColor(0, 0) == QColor("#123456")              # a rounded corner
    assert img.pixelColor(m.width() - 1, m.height() - 1) == QColor("#123456")
    m.set_ground(None)
    assert not m.testAttribute(Qt.WA_OpaquePaintEvent)


def test_meter_repaints_when_the_pointer_enters_or_leaves_its_ground(qapp):
    """An opaque meter is left out when the bar behind it repaints its
    hover tint: the bar's Enter / Leave must repaint the meter itself, or
    a meter standing still keeps the old ground in its corners."""
    from PySide6.QtCore import QEvent, QPointF
    from PySide6.QtGui import QEnterEvent
    bar = QWidget()
    m = RainbowMeter(parent=bar)
    m.set_ground(lambda: "#123456", hover_of=bar)
    calls = counted(m)
    QApplication.sendEvent(bar, QEnterEvent(QPointF(1, 1), QPointF(1, 1), QPointF(1, 1)))
    QApplication.sendEvent(bar, QEvent(QEvent.Leave))
    assert len(calls) == 2


def test_toy_bar_ground_follows_hover_and_the_frame():
    from ui.views.device_frame import _toy_bar_ground

    class Bar:
        hovered = False

        def underMouse(self):
            return self.hovered

    class Card:
        fill = "#0f1a14"

        def ground(self):
            return self.fill

    bar, card = Bar(), Card()
    assert _toy_bar_ground(bar, card) == "#0f1a14"
    bar.hovered = True                       # theme.py: QWidget#toyBar:hover
    assert _toy_bar_ground(bar, card) == theme.CHROME["hover"]
    bar.hovered, card.fill = False, None     # an offline toy's frame has no fill
    assert _toy_bar_ground(bar, card) == theme.CHROME["bg"]
