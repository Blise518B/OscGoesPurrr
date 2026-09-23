"""Hover explanations (ui/tooltips.py) -- the only in-place help the app
has, so the rules for where an explanation lands are pinned here."""

import pytest
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QHBoxLayout, QLabel, QPushButton, QVBoxLayout,
    QWidget,
)

from ui.tooltips import explain, tip_html


@pytest.fixture(scope="module", autouse=True)
def _app():
    return QApplication.instance() or QApplication([])


def test_tip_is_a_bold_title_over_the_body():
    html = tip_html("Sleep", "Needs <b>three</b> strokes.")
    assert html == "<b>Sleep</b><br>Needs <b>three</b> strokes."


def test_the_title_is_escaped_but_the_body_keeps_its_markup():
    html = tip_html("A < B", "<i>body</i>")
    assert html.startswith("<b>A &lt; B</b>")
    assert "<i>body</i>" in html


def test_a_widget_target_gets_the_tip():
    w = QPushButton("Off")
    explain(w, "Off", "Stops everything.")
    assert "Stops everything." in w.toolTip()


def test_a_layout_tips_every_widget_already_in_it():
    row = QHBoxLayout()
    label, box = QLabel("Duck"), QCheckBox()
    row.addWidget(label)
    row.addWidget(box)
    row.addStretch(1)
    explain(row, "Duck", "Goes quiet while the pen is in.")
    assert "Goes quiet" in label.toolTip()
    assert "Goes quiet" in box.toolTip()


def test_a_layout_never_overwrites_a_more_specific_tip():
    row = QHBoxLayout()
    pick = QPushButton("+")
    pick.setToolTip("Pick from live OSC parameters")
    row.addWidget(pick)
    explain(row, "Contacts", "Comma-separated receivers.")
    assert pick.toolTip() == "Pick from live OSC parameters"


def test_nested_layouts_are_reached():
    outer = QVBoxLayout()
    inner = QHBoxLayout()
    deep = QLabel("Gain:")
    inner.addWidget(deep)
    outer.addLayout(inner)
    explain(outer, "Gain", "Scales the channel.")
    assert "Scales the channel." in deep.toolTip()


def test_a_mixed_iterable_is_accepted():
    a, b = QLabel("a"), QLabel("b")
    row = QHBoxLayout()
    row.addWidget(b)
    explain((a, row), "Mixed", "Both.")
    assert "Both." in a.toolTip() and "Both." in b.toolTip()


def test_none_is_ignored():
    explain(None, "Nothing", "to do")


def test_a_container_tip_is_what_its_plain_children_fall_back_to():
    """Qt hands an unanswered tooltip request to the parent, so tipping a
    group's container covers its controls. The explanation must sit on
    the container itself -- not be copied into the children -- or a child
    with its own specific tip would lose it."""
    group = QWidget()
    lay = QHBoxLayout(group)
    plain, specific = QLabel("Sim"), QPushButton("Play")
    specific.setToolTip("Start the wave")
    lay.addWidget(plain)
    lay.addWidget(specific)
    explain(group, "Input simulator", "A synthetic wave.")
    assert "A synthetic wave." in group.toolTip()
    assert plain.toolTip() == ""
    assert specific.toolTip() == "Start the wave"
