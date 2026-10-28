"""The window opens the way it was closed.

A maximized window has to come back maximized -- the plain "WxH+X+Y"
string the app used to save alone made it a normal window of the
screen's size, shifted a little to the side. The window state (Qt's own
save of place, size and maximized) is what is restored now; the string
stays the fallback for settings from older versions.
"""
import sys

import pytest

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QWidget

from ui_components import OscGoesPurrrUI


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication(sys.argv[:1])


class _Host:
    """The window facade of OscGoesPurrrUI on a bare window."""
    set_window_state = OscGoesPurrrUI.set_window_state
    get_window_state = OscGoesPurrrUI.get_window_state
    set_geometry = OscGoesPurrrUI.set_geometry
    get_geometry = OscGoesPurrrUI.get_geometry

    def __init__(self):
        self.window = QWidget()


def _avail():
    return QApplication.primaryScreen().availableGeometry()


class TestWindowState:
    def test_a_maximized_window_comes_back_maximized(self, qapp):
        old = _Host()
        old.window.setGeometry(40, 50, 400, 300)
        old.window.showMaximized()
        qapp.processEvents()
        state = old.get_window_state()
        old.window.close()
        assert state

        new = _Host()
        assert new.set_window_state(state) is True
        assert new.window.windowState() & Qt.WindowMaximized
        # ...and un-maximized it goes back to the size it had before
        assert new.window.normalGeometry().size() == old.window.normalGeometry().size()

    def test_a_normal_window_keeps_its_place_and_size(self, qapp):
        old = _Host()
        old.window.setGeometry(60, 70, 420, 310)
        old.window.show()
        qapp.processEvents()
        state = old.get_window_state()
        old.window.close()

        new = _Host()
        assert new.set_window_state(state) is True
        assert not new.window.windowState() & Qt.WindowMaximized
        assert new.window.geometry() == old.window.geometry()

    def test_nothing_or_junk_changes_nothing(self, qapp):
        host = _Host()
        assert host.set_window_state("") is False
        assert host.set_window_state("not base64 at all!") is False
        assert not host.window.windowState() & Qt.WindowMaximized

    def test_the_plain_string_saves_the_size_it_goes_back_to(self, qapp):
        host = _Host()
        host.window.setGeometry(80, 90, 430, 320)
        host.window.show()
        qapp.processEvents()
        normal = host.get_geometry()
        host.window.showMaximized()
        qapp.processEvents()
        assert host.get_geometry().split("+")[0] == normal.split("+")[0] == "430x320"
        host.window.close()


class TestOldSettings:
    def test_a_window_saved_screen_sized_was_maximized(self, qapp):
        """What a maximized window used to save: its full size."""
        a = _avail()
        host = _Host()
        host.set_geometry(f"{a.width()}x{a.height() - 22}+{a.x() + 14}+{a.y() - 6}")
        assert host.window.windowState() & Qt.WindowMaximized

    def test_a_smaller_window_stays_as_it_was(self, qapp):
        a = _avail()
        host = _Host()
        host.set_geometry(f"{a.width() // 2}x{a.height() // 2}+{a.x() + 10}+{a.y() + 10}")
        assert not host.window.windowState() & Qt.WindowMaximized
        assert host.window.size().width() == a.width() // 2
