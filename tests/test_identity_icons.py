"""The toy / shocker / Avatar Remote / Friends / Suits icons
(ui/icons.identity_icon): each in its colour, a blank for anything else,
and every IdentityMark redrawn when the colour picker moves its colour.
The pages that are no kind of thing (ui/icons.page_icon) wear the
sidebar's text tone, so every sidebar entry has an icon."""

import sys

import pytest
from PySide6.QtCore import QSize
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication

import constants
from ui import theme
from ui.icons import ICON_NAMES, identity_color, identity_icon, page_icon
from ui.widgets import IdentityMark


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication(sys.argv[:1])


def colours(icon, size=20):
    img = icon.pixmap(QSize(size, size), 1.0).toImage().convertToFormat(QImage.Format_ARGB32)
    out = set()
    for y in range(img.height()):
        for x in range(img.width()):
            c = img.pixelColor(x, y)
            if c.alpha() == 255:
                out.add(c.name())
    return out


def test_each_icon_is_drawn_in_its_colour_and_anything_else_is_blank(qapp):
    assert colours(identity_icon("toys")) == {theme.hue(theme.FRIEND_TOYS_HUE).lower()}
    assert colours(identity_icon("shock")) == {theme.hue(theme.FRIEND_SHOCK_HUE).lower()}
    assert colours(identity_icon("params")) == {constants.COLOR_ACCENT.lower()}
    assert colours(identity_icon("friends")) == {theme.hue(theme.FRIENDS_HUE).lower()}
    assert colours(identity_icon("suits")) == {theme.hue(theme.SUITS_HUE).lower()}
    assert colours(identity_icon("web")) == {theme.hue(theme.FRIENDS_HUE).lower()}   # part of Friends
    assert colours(identity_icon("")) == set()


def test_the_other_pages_wear_the_sidebars_tone(qapp):
    for what in ("stats", "sps", "inspector", "diagnostics", "log", "settings", "help"):
        assert colours(page_icon(what)) == {constants.COLOR_MUTED.lower()}, what
    # a kind of thing keeps its own colour there, anything else is blank
    assert colours(page_icon("shock")) == colours(identity_icon("shock"))
    assert colours(page_icon("nothing")) == set()


def test_every_sidebar_entry_has_an_icon(qapp):
    from ui_components import OscGoesPurrrUI
    entries = ("Friends", "My Avatar Remote", "Shockers", "Suits", "Statistics",
               "SPS Sources", "OSC Inspector", "OSC Diagnostics", "System Log",
               "Settings", "Help")
    for name in entries:
        what = OscGoesPurrrUI._NAV_ICONS[name]
        assert what in ICON_NAMES and colours(page_icon(what)), name


def test_marks_follow_the_colour_picker(qapp, monkeypatch):
    mark = IdentityMark("params", 20)
    monkeypatch.setattr(constants, "COLOR_ACCENT", "#3399ff")
    assert identity_color("params") == "#3399ff"
    IdentityMark.redraw_all()
    assert colours(mark._icon) == {"#3399ff"}
