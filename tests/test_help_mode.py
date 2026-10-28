"""Help mode (ui/help_mode.py) and the steps it shows (ui/page_steps.py).

What it promises: a page's steps go on a strip above it and light their
controls (a missing one says so); pointing at anything lights the control
whose explanation shows there, with a whole explained row lit as one;
while it is on, clicks do nothing -- except the sidebar's pages, which help
mode follows -- tooltips wait, and Esc leaves.
"""

import sys

import pytest

from PySide6.QtCore import QEvent, QPoint, Qt
from PySide6.QtGui import QHelpEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import (QApplication, QHBoxLayout, QLabel, QPushButton, QStackedWidget,
                               QVBoxLayout, QWidget)

from ui import page_steps
from ui.help_mode import HelpMode, find_control, split_tip, visible_rect
from ui.page_steps import Step
from ui.tooltips import explain, tip_html


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication(sys.argv[:1])


STEPS = (Step("Press Test all", "Every toy buzzes once.", "Test all"),
         Step("One strength for all", "Off silences everything.", "Total output strength"),
         Step("Open a toy", "Its signal chain.", "Nowhere on this page"))


class Window:
    """A sidebar (a page button, a strength control) and two pages, the
    first with an explained button, row and box."""

    def __init__(self):
        self.root = QWidget()
        lay = QHBoxLayout(self.root)
        side = QWidget()
        side_lay = QVBoxLayout(side)
        self.nav = QPushButton("Other page")
        self.strength = QPushButton("70 %")
        explain(self.strength, "Total output strength", "One multiplier on everything.")
        side_lay.addWidget(self.nav)
        side_lay.addWidget(self.strength)
        lay.addWidget(side)
        content = QWidget()
        content_lay = QVBoxLayout(content)
        self.stack = QStackedWidget()
        content_lay.addWidget(self.stack)
        lay.addWidget(content, 1)

        self.page = QWidget()
        page_lay = QVBoxLayout(self.page)
        self.test_all = QPushButton("Test all")
        explain(self.test_all, "Test all", "Buzzes every toy once. Then it stops.")
        self.clicks = 0
        self.test_all.clicked.connect(self._clicked)
        page_lay.addWidget(self.test_all)
        self.row = QWidget()
        row_lay = QHBoxLayout(self.row)
        self.row_label = QLabel("Arm shocks")
        self.row_switch = QPushButton("on")
        row_lay.addWidget(self.row_label)
        row_lay.addWidget(self.row_switch)
        explain(row_lay, "Arm shocks", "Until this is on, a shock is a vibrate.")
        page_lay.addWidget(self.row)
        self.box = QWidget()
        box_lay = QVBoxLayout(self.box)
        self.inner = QLabel("just a label")
        box_lay.addWidget(self.inner)
        explain(self.box, "Body", "Every contact, live.")
        page_lay.addWidget(self.box)
        self.other = QWidget()
        self.stack.addWidget(self.page)
        self.stack.addWidget(self.other)
        self.nav.clicked.connect(lambda: self.stack.setCurrentWidget(self.other))

        self.mode = HelpMode(
            self.root, self.stack,
            lambda page: ("Home", STEPS) if page is self.page else ("Other", ()),
            passthrough=lambda w: w is self.nav)
        self.root.setAttribute(Qt.WA_DontShowOnScreen, True)
        self.root.resize(900, 600)
        self.root.show()
        QApplication.processEvents()

    def _clicked(self):
        self.clicks += 1

    def start(self):
        self.mode.start()
        self.mode._timer.stop()          # the pointer is driven by hand here
        QApplication.processEvents()

    def point_at(self, w):
        self.mode.hover_at(w.mapTo(self.root, w.rect().center()))


@pytest.fixture
def win(qapp):
    w = Window()
    yield w
    w.mode.stop()
    w.root.close()


class TestReadingTheWindow:
    def test_a_bubble_shows_the_title_and_the_first_sentence(self, qapp):
        tip = tip_html("Arm shocks", "Until this is on, a shock goes out as a vibrate. "
                                     "Arming is remembered.")
        assert split_tip(tip) == ("Arm shocks", "Until this is on, a shock goes out as a vibrate.")
        assert split_tip(tip_html("Stop all / Resume", "<b>Stop</b> stops everything.")) == \
            ("Stop all / Resume", "Stop stops everything.")

    def test_a_control_is_found_by_its_explanation_then_by_what_it_says(self, win):
        assert find_control([win.page], "Test all") is win.test_all
        assert find_control([win.page], "just a label") is win.inner
        assert find_control([win.page], "Nowhere on this page") is None
        assert find_control([win.page, win.root], "Total output strength") is win.strength


class TestHelpMode:
    def test_the_strip_goes_above_the_pages_and_leaves_with_it(self, win):
        win.start()
        lay = win.stack.parentWidget().layout()
        assert win.mode.strip.isVisible()
        assert lay.indexOf(win.mode.strip) == lay.indexOf(win.stack) - 1
        assert win.mode.overlay.geometry() == win.root.rect()
        win.mode.stop()
        assert not win.mode.strip.isVisible() and not win.mode.overlay.isVisible()

    def test_each_step_lights_its_control_and_a_missing_one_says_so(self, win):
        win.start()
        assert [c.label for c in win.mode._chips] == [s.label for s in STEPS]
        assert [c.missing for c in win.mode._chips] == [False, False, True]
        assert win.mode.step_rect(0) == visible_rect(win.test_all, win.root)
        assert win.mode.step_rect(1) == visible_rect(win.strength, win.root)   # sidebar too
        assert win.mode.step_rect(2) is None

    def test_pointing_lights_the_control_whose_explanation_shows_there(self, win):
        win.start()
        win.point_at(win.inner)                       # no tip of its own: its box's
        assert win.mode.hovered() is win.box
        win.point_at(win.row_label)                   # a row explained once lights as one
        lit = win.mode._hover[1]
        assert lit.contains(visible_rect(win.row_switch, win.root))
        assert win.mode._hover[2:] == ("Arm shocks", "Until this is on, a shock is a vibrate.")

    def test_clicks_do_nothing_but_the_sidebar_pages_still_work(self, win):
        win.start()
        QTest.mouseClick(win.test_all, Qt.LeftButton)
        assert win.clicks == 0
        QTest.mouseClick(win.nav, Qt.LeftButton)
        assert win.stack.currentWidget() is win.other
        assert win.mode.page_name == "Other" and not win.mode._chips   # it followed
        win.mode.stop()
        win.stack.setCurrentWidget(win.page)
        QTest.mouseClick(win.test_all, Qt.LeftButton)
        assert win.clicks == 1

    def test_tooltips_wait_and_escape_leaves(self, win):
        win.start()
        tip = QHelpEvent(QEvent.ToolTip, QPoint(5, 5), win.test_all.mapToGlobal(QPoint(5, 5)))
        assert win.mode.eventFilter(win.test_all, tip) is True
        QTest.keyClick(win.test_all, Qt.Key_Escape)
        assert not win.mode.active
        assert win.mode.eventFilter(win.test_all, tip) is False


class TestPageSteps:
    def test_every_step_says_what_where_and_a_little_more(self):
        for page, steps in page_steps.STEPS.items():
            assert steps, page
            for step in steps:
                assert step.label and step.hint and step.target, (page, step)
                assert len(step.label) <= 32, step.label       # a few words

    def test_a_page_is_found_under_its_older_or_newer_name(self):
        assert page_steps.for_page("Avatar Remote") == page_steps.for_page("My Avatar Remote")
        assert page_steps.for_page("Avatar Remote")
        assert page_steps.for_page("Statistics") == ()
