"""UI helper modules.

Standalone widgets, vector icons, and small layout utilities extracted out
of `ui_components.py` so the monolithic `OscGoesPurrrUI` class is no longer
the only home for view-layer code. The main UI class still lives in
`ui_components.py`; it imports from here.

This package contains no controller / facade code — the architecture's
Rule 1 (the UI never reaches through `controller.<service>`) still applies
to everything in here.
"""

from .geometry import format_tk_geometry, parse_tk_geometry
from .layout_helpers import clear_layout, hbox, vbox
from .text_helpers import html_escape, truncate
from .icons import (
    icon_check,
    icon_copy,
    icon_cross,
    icon_paste,
    icon_pencil,
    icon_trash,
    new_icon_pixmap,
)
from .widgets import (
    BHapticsDotGrid,
    Card,
    Invoker,
    MainWindow,
    ProgressProxy,
    RainbowMeter,
    RainbowScrollBar,
    SliderProxy,
    ToggleSwitch,
    install_rainbow_scrollbars,
)

__all__ = [
    "format_tk_geometry",
    "parse_tk_geometry",
    "clear_layout",
    "hbox",
    "vbox",
    "html_escape",
    "truncate",
    "icon_check",
    "icon_copy",
    "icon_cross",
    "icon_paste",
    "icon_pencil",
    "icon_trash",
    "new_icon_pixmap",
    "BHapticsDotGrid",
    "Card",
    "Invoker",
    "MainWindow",
    "ProgressProxy",
    "RainbowMeter",
    "RainbowScrollBar",
    "SliderProxy",
    "ToggleSwitch",
    "install_rainbow_scrollbars",
]
