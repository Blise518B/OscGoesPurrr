"""OGP's taskbar button shows the cat however Windows looks it up
(utilities.set_window_class_icon): Qt gives its window class Windows'
generic program icon when the exe has no IDI_ICON1 -- python.exe, which
run.bat starts, never has -- and the taskbar falls back to the class icon
whenever it doesn't take the window's own. Blise saw that generic icon now
and then when running from source (2026-11-17)."""

import os
import sys

import pytest

import utilities

ICO = os.path.join(os.path.dirname(__file__), os.pardir, "src", "Images", "OGP_Icon.ico")


def test_nothing_to_set_without_a_window_or_an_icon(tmp_path):
    assert utilities.set_window_class_icon(0, ICO) is False
    assert utilities.set_window_class_icon(1234, str(tmp_path / "missing.ico")) is False
    # no such window: the icon loads, but nothing takes it
    assert utilities.set_window_class_icon(0x7FFF0, os.path.abspath(ICO)) is False


@pytest.mark.skipif(sys.platform != "win32", reason="the taskbar's class icon is Windows'")
def test_the_window_class_carries_the_cat():
    import ctypes
    from ctypes import wintypes

    from PySide6.QtWidgets import QApplication, QWidget
    app = QApplication.instance() or QApplication(sys.argv[:1])
    if app.platformName() != "windows":
        pytest.skip("Qt runs offscreen here: no real window to give an icon")
    user32 = ctypes.WinDLL("user32")
    user32.GetClassLongPtrW.restype = ctypes.c_void_p
    user32.GetClassLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int]
    user32.LoadIconW.restype = ctypes.c_void_p
    user32.LoadIconW.argtypes = [wintypes.HINSTANCE, ctypes.c_void_p]
    generic = user32.LoadIconW(None, ctypes.c_void_p(32512))       # IDI_APPLICATION
    w = QWidget()
    from PySide6.QtGui import QIcon
    w.setWindowIcon(QIcon(ICO))                  # Qt's "window with an icon" class
    hwnd = int(w.winId())
    assert utilities.set_window_class_icon(hwnd, os.path.abspath(ICO)) is True
    big = user32.GetClassLongPtrW(hwnd, -14)     # GCLP_HICON
    small = user32.GetClassLongPtrW(hwnd, -34)   # GCLP_HICONSM
    assert big and big != generic
    assert small and small != generic


def test_the_app_sets_it_right_before_the_window_shows():
    """ui_components' run() gives the class the icon it found, before
    show() -- a button already on the taskbar keeps what it was shown with."""
    import inspect

    import ui_components
    src = inspect.getsource(ui_components.OscGoesPurrrUI.run)
    assert src.index("_set_window_class_icon") < src.index("self.window.show()")
