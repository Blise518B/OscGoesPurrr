"""Style sheet + palette for the test bench.

The bench deliberately does not import from the main app (it is a stand-alone
tool) — instead this module mirrors the relevant slice of the app's
constants.py + GLOBAL_QSS so the bench looks like OGP without coupling the two
codebases. If the main app's palette is ever rebranded, copy the new values
across. (Inherited from the former standalone sim/ tool.)
"""

from __future__ import annotations


# --- Theme colours (mirror constants.py) -----------------------------------
COLOR_PRIMARY = "#7C4DFF"
COLOR_PRIMARY_HOVER = "#6A3DEC"
COLOR_ALERT = "#FF1150"
COLOR_ALERT_HOVER = "#DD0E45"
COLOR_SUCCESS = "#07FF77"
COLOR_LIVE = "#FF3D7F"
COLOR_LIVE_DIM = "#7A1E3F"
COLOR_WARNING = "#FF7300"

COLOR_BG = "#0D0924"
COLOR_SURFACE = "#1D1553"
COLOR_SURFACE_HOVER = "#2A2070"

COLOR_BUTTON = "#3A2C8C"
COLOR_BUTTON_HOVER = "#4D3CB3"

COLOR_INPUT_BG = "#1A1240"
COLOR_INPUT_BORDER = "#3A2C8C"
COLOR_INPUT_FOCUS = "#9A7BFF"

COLOR_TEXT = "#FFFFFF"
COLOR_TEXT_MUTED = "#9A9AB8"


# --- Global stylesheet -----------------------------------------------------
GLOBAL_QSS = f"""
* {{
    color: {COLOR_TEXT};
    font-family: "Segoe UI", Arial, sans-serif;
    font-size: 13px;
}}
QMainWindow, QWidget#root {{
    background-color: {COLOR_BG};
}}

/* Cards — one per SPS zone / bHaptics device. Rounded indigo surfaces with
   a subtle header. */
QFrame#card {{
    background-color: {COLOR_SURFACE};
    border-radius: 12px;
}}
QFrame#cardInner {{
    background: transparent;
    border: none;
}}
QLabel#cardHeader {{
    font-size: 14px;
    font-weight: bold;
    color: {COLOR_INPUT_FOCUS};
    background: transparent;
    padding: 0;
}}
QLabel#cardSubheader {{
    font-size: 11px;
    color: {COLOR_TEXT_MUTED};
    background: transparent;
}}
QLabel#statusBar {{
    color: {COLOR_TEXT_MUTED};
    padding: 2px 4px;
    background: transparent;
}}
QLabel#sectionTitle {{
    color: {COLOR_PRIMARY};
    font-size: 16px;
    font-weight: bold;
    background: transparent;
}}
QLabel#sliderValue {{
    color: {COLOR_INPUT_FOCUS};
    font-variant-numeric: tabular-nums;
    min-width: 36px;
    background: transparent;
}}
QLabel#sliderLabel {{
    color: {COLOR_TEXT};
    background: transparent;
}}

/* Buttons — primary is purple, secondary is the muted button surface. */
QPushButton {{
    background-color: {COLOR_PRIMARY};
    color: {COLOR_TEXT};
    border: none;
    padding: 6px 14px;
    border-radius: 6px;
}}
QPushButton:hover {{
    background-color: {COLOR_PRIMARY_HOVER};
}}
QPushButton:disabled {{
    color: {COLOR_TEXT_MUTED};
    background-color: {COLOR_SURFACE};
}}
QPushButton[role="secondary"] {{
    background-color: {COLOR_BUTTON};
}}
QPushButton[role="secondary"]:hover {{
    background-color: {COLOR_BUTTON_HOVER};
}}
QPushButton[role="danger"] {{
    background-color: {COLOR_ALERT};
}}
QPushButton[role="danger"]:hover {{
    background-color: {COLOR_ALERT_HOVER};
}}
/* Toggleable buttons (Animate Thrust). When checked, light up in the
   "live" pink so the user sees the running state at a glance. */
QPushButton:checked {{
    background-color: {COLOR_LIVE};
}}
QPushButton:checked:hover {{
    background-color: {COLOR_LIVE_DIM};
}}
/* bHaptics dot buttons — tiny squares with checked state in live pink. */
QPushButton[role="dot"] {{
    background-color: {COLOR_BUTTON};
    border-radius: 4px;
    padding: 0px;
}}
QPushButton[role="dot"]:hover {{
    background-color: {COLOR_BUTTON_HOVER};
}}
QPushButton[role="dot"]:checked {{
    background-color: {COLOR_LIVE};
}}

/* Combo boxes + spin boxes — input surface, lighter than the card behind. */
QComboBox, QDoubleSpinBox, QSpinBox, QAbstractSpinBox {{
    background-color: {COLOR_INPUT_BG};
    color: {COLOR_TEXT};
    border: 1px solid {COLOR_INPUT_BORDER};
    border-radius: 4px;
    padding: 4px 6px;
    selection-background-color: {COLOR_PRIMARY};
}}
QComboBox:hover, QDoubleSpinBox:hover, QSpinBox:hover, QAbstractSpinBox:hover {{
    border-color: {COLOR_INPUT_FOCUS};
}}
QComboBox::drop-down {{
    border: none;
    width: 18px;
}}
QComboBox QAbstractItemView {{
    background-color: {COLOR_INPUT_BG};
    color: {COLOR_TEXT};
    border: 1px solid {COLOR_INPUT_BORDER};
    selection-background-color: {COLOR_PRIMARY};
    selection-color: {COLOR_TEXT};
    outline: 0;
}}
/* Spinbox up/down arrows — solid surface so the white default doesn't leak
   through against the dark card. */
QDoubleSpinBox::up-button, QSpinBox::up-button,
QDoubleSpinBox::down-button, QSpinBox::down-button {{
    background-color: {COLOR_BUTTON};
    border: none;
    width: 14px;
}}
QDoubleSpinBox::up-button:hover, QSpinBox::up-button:hover,
QDoubleSpinBox::down-button:hover, QSpinBox::down-button:hover {{
    background-color: {COLOR_BUTTON_HOVER};
}}
QDoubleSpinBox::up-arrow, QSpinBox::up-arrow {{
    image: none;
    border-left: 4px solid transparent;
    border-right: 4px solid transparent;
    border-bottom: 5px solid {COLOR_TEXT};
    width: 0;
    height: 0;
}}
QDoubleSpinBox::down-arrow, QSpinBox::down-arrow {{
    image: none;
    border-left: 4px solid transparent;
    border-right: 4px solid transparent;
    border-top: 5px solid {COLOR_TEXT};
    width: 0;
    height: 0;
}}

/* Plain text edits (log tab) — input surface + monospace font. */
QPlainTextEdit {{
    background-color: {COLOR_INPUT_BG};
    color: {COLOR_TEXT};
    border: 1px solid {COLOR_INPUT_BORDER};
    border-radius: 4px;
    padding: 4px 6px;
    font-family: "Consolas", "Courier New", monospace;
    selection-background-color: {COLOR_PRIMARY};
}}

/* Tabs — purple text on the active tab, muted text otherwise. */
QTabWidget::pane {{
    border: none;
    background: transparent;
}}
QTabBar::tab {{
    background-color: {COLOR_SURFACE};
    color: {COLOR_TEXT_MUTED};
    padding: 8px 18px;
    border-top-left-radius: 8px;
    border-top-right-radius: 8px;
    margin-right: 2px;
}}
QTabBar::tab:selected {{
    background-color: {COLOR_BG};
    color: {COLOR_INPUT_FOCUS};
    font-weight: bold;
}}
QTabBar::tab:hover {{
    background-color: {COLOR_SURFACE_HOVER};
}}

/* Sliders — copy the main app's gradient groove trick. The full rainbow
   paints once across the entire groove and the "add-page" (unfilled side)
   covers the right portion with the bg colour, so colours stay at fixed
   positions on the track regardless of value. */
QSlider::groove:horizontal {{
    height: 6px;
    background: qlineargradient(
        x1:0, y1:0, x2:1, y2:0,
        stop:0 {COLOR_PRIMARY},
        stop:1 {COLOR_LIVE}
    );
    border-radius: 3px;
}}
QSlider::sub-page:horizontal {{
    background: transparent;
}}
QSlider::add-page:horizontal {{
    background: {COLOR_BG};
    border-radius: 3px;
}}
QSlider::handle:horizontal {{
    background: {COLOR_TEXT};
    width: 14px;
    margin: -6px 0;
    border-radius: 7px;
    border: 2px solid {COLOR_PRIMARY};
}}
QSlider::handle:horizontal:hover {{
    border-color: {COLOR_LIVE};
}}

/* Scroll areas — transparent so the dark window background shows through. */
QScrollArea {{
    border: none;
    background-color: transparent;
}}
QScrollArea > QWidget > QWidget {{
    background-color: transparent;
}}
QScrollBar {{
    background: transparent;
    border: none;
}}
QScrollBar:vertical {{
    width: 10px;
    background: {COLOR_BG};
}}
QScrollBar:horizontal {{
    height: 10px;
    background: {COLOR_BG};
}}
QScrollBar::handle {{
    background: {COLOR_SURFACE_HOVER};
    border-radius: 5px;
    min-height: 20px;
}}
QScrollBar::handle:hover {{
    background: {COLOR_BUTTON};
}}
QScrollBar::add-line, QScrollBar::sub-line {{
    background: transparent;
    border: none;
    height: 0;
    width: 0;
}}
QScrollBar::add-page, QScrollBar::sub-page {{
    background: transparent;
}}
"""
