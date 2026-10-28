"""The scroll wheel scrolls pages; it never changes a setting it passes
over (ui/wheel_guard.py) -- not even one you just clicked, which in VR is
the one the next scroll passes over."""

import sys

import pytest
from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QWheelEvent
from PySide6.QtWidgets import (
    QApplication, QComboBox, QScrollArea, QSlider, QSpinBox, QTabBar, QVBoxLayout, QWidget,
)

from ui import wheel_guard


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication(sys.argv[:1])
    wheel_guard.install(app)
    return app


def wheel(widget, ticks=3):
    for _ in range(ticks):
        ev = QWheelEvent(QPointF(5, 5), QPointF(widget.mapToGlobal(QPoint(5, 5))),
                         QPoint(0, 0), QPoint(0, -120), Qt.NoButton, Qt.NoModifier,
                         Qt.NoScrollPhase, False)
        QApplication.sendEvent(widget, ev)
    QApplication.processEvents()


def page(qapp):
    """A tall page in a scroll area, a control of each kind on it."""
    area = QScrollArea()
    area.setWidgetResizable(True)
    inner = QWidget()
    lay = QVBoxLayout(inner)
    spin, combo, slider, tabs = QSpinBox(), QComboBox(), QSlider(Qt.Horizontal), QTabBar()
    spin.setRange(0, 100)
    spin.setValue(50)
    combo.addItems(["a", "b", "c"])
    combo.setCurrentIndex(1)
    slider.setRange(0, 100)
    slider.setValue(50)
    tabs.addTab("One")
    tabs.addTab("Two")
    for w in (spin, combo, slider, tabs):
        lay.addWidget(w)
    lay.addSpacing(3000)
    area.setWidget(inner)
    area.resize(300, 300)
    area.show()
    qapp.processEvents()
    return area, spin, combo, slider, tabs


def test_the_wheel_over_a_control_scrolls_the_page_and_changes_nothing(qapp):
    area, spin, combo, slider, tabs = page(qapp)
    for w in (spin, combo, slider, tabs):
        wheel(w)
    assert (spin.value(), combo.currentIndex(), slider.value(), tabs.currentIndex()) == (50, 1, 50, 0)
    assert area.verticalScrollBar().value() > 0            # the page scrolled instead
    area.hide()


def test_not_even_a_control_just_clicked(qapp):
    area, spin, *_ = page(qapp)
    spin.setFocus()
    wheel(spin)
    assert spin.value() == 50
    area.hide()


def test_the_wheel_never_hands_out_focus(qapp):
    area, spin, *_ = page(qapp)
    assert spin.focusPolicy() == Qt.StrongFocus
    area.hide()


def test_scroll_bars_and_a_control_that_asks_keep_the_wheel(qapp):
    area, spin, *_ = page(qapp)
    spin.setProperty(wheel_guard.WHEEL_ADJUSTS, True)
    spin.setFocus()
    wheel(spin)
    assert spin.value() != 50
    bar = area.verticalScrollBar()
    before = bar.value()
    wheel(bar)
    assert bar.value() != before
    area.hide()
