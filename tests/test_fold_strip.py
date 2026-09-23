"""Smoke tests for ui/fold_strip.py — the shared fold-card / arrow /
activity-ring design language extracted from the motor signal chain.

Importing the module fails fast on syntax errors or missing imports;
the colour-ramp tests pin the design endpoints so a refactor can't
silently drift the backend views away from the chain's look. Widget
behaviour (expansion, arrow painting) needs a live QApplication and is
exercised manually — the suite stays headless by convention."""


def test_module_imports():
    import ui.fold_strip as fs  # noqa: F401
    assert hasattr(fs, "FoldCard")
    assert hasattr(fs, "FoldStrip")
    assert hasattr(fs, "draw_arrow")


def test_border_ramp_matches_chain_endpoints():
    # The ring must charge between the chain's exact colours — idle
    # dark purple and saturated vivid pink — or the tabs stop reading
    # as one design.
    from ui.fold_strip import BORDER_HIGH, BORDER_LOW, activity_border_color
    assert activity_border_color(0.0).name().upper() == BORDER_LOW.upper()
    assert activity_border_color(1.0).name().upper() == BORDER_HIGH.upper()


def test_color_lerp_clamps_out_of_range():
    from PySide6.QtGui import QColor
    from ui.fold_strip import lerp_color
    lo, hi = QColor("#000000"), QColor("#FFFFFF")
    assert lerp_color(lo, hi, -1.0).name() == "#000000"
    assert lerp_color(lo, hi, 2.0).name() == "#ffffff"
    mid = lerp_color(lo, hi, 0.5)
    assert 126 <= mid.red() <= 128
