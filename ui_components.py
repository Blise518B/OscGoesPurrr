# OscGoesPurrr - UI Components Module (PySide6)
#
# Pure View layer. The controller talks to this class through a fixed facade
# (set_title, schedule_callback, run, update_*, etc.). Swapping toolkits
# means rewriting this file plus the `ui/` subpackage (widgets, icons,
# layout helpers) — and nothing else.

from typing import List, Optional, Dict, Any, Callable
import os
import sys

from PySide6.QtCore import (
    Qt, QThread, QTimer, Signal, QObject, QEvent, QSize, QPointF, QRect, QRectF
)
from PySide6.QtGui import (
    QFont, QColor, QTextCharFormat, QTextCursor, QIcon,
    QPixmap, QPainter, QPen, QBrush, QPainterPath, QPolygonF
)
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QLabel, QPushButton, QCheckBox, QLineEdit, QSlider, QProgressBar,
    QFrame, QScrollArea, QTextEdit, QPlainTextEdit, QSizePolicy, QSpacerItem,
    QDialog, QMessageBox, QTreeWidget, QTreeWidgetItem, QHeaderView,
    QButtonGroup, QStackedWidget, QTableWidget, QTableWidgetItem,
    QAbstractItemView, QComboBox, QSpinBox, QDoubleSpinBox, QToolButton,
)
from ui import lovense_icons as _lovense_icons

from constants import *
from parameter_store import store
from utilities import (
    apply_window_frame_colors as _apply_window_frame_colors,
    strip_param_prefix,
)

# Helper widgets, icons, layout utilities, text/geometry helpers extracted
# into the `ui` package. Aliased here to keep the old private names the
# rest of this file references (`_vbox`, `_icon_*`, `_BHapticsDotGrid`, etc.).
from ui.geometry import parse_tk_geometry as _parse_tk_geometry
from ui.geometry import format_tk_geometry as _format_tk_geometry
from ui.layout_helpers import vbox as _vbox, hbox as _hbox, clear_layout as _clear_layout
from ui.text_helpers import truncate as _truncate, html_escape as _html_escape
from ui.icons import (
    new_icon_pixmap as _new_icon_pixmap,
    icon_pencil as _icon_pencil,
    icon_copy as _icon_copy,
    icon_paste as _icon_paste,
    icon_trash as _icon_trash,
    icon_check as _icon_check,
    icon_cross as _icon_cross,
)
from ui.widgets import (
    ToggleSwitch,
    Invoker as _Invoker,
    MainWindow as _MainWindow,
    Card as _Card,
    BHapticsDotGrid as _BHapticsDotGrid,
    SliderProxy as _SliderProxy,
    ProgressProxy as _ProgressProxy,
    RainbowMeter as _RainbowMeter,
    install_rainbow_scrollbars as _install_rainbow_scrollbars,
)

# View mixins extracted from this file (see step 4 of the structural
# refactor). Each mixin owns a coherent slice of the UI; this class
# composes them so external code keeps calling OscGoesPurrrUI(...).
from ui.views.dashboard import DashboardMixin
from ui.views.diagnostics import DiagnosticsMixin
from ui.views.settings import SettingsMixin
from ui.views.sessions import SessionsMixin
from ui.views.steamvr import SteamVRMixin
from ui.views.bhaptics import BHapticsMixin
from ui.views.pishock import PiShockMixin
from ui.views.coyote import CoyoteMixin
from ui.views.owo import OwoMixin
from ui.views.handy import HandyMixin
from ui.views.device_frame import DeviceFrameMixin
from ui.views.overview import OverviewMixin
from ui.views.sps_sources import SpsSourcesMixin
from ui.views.statistics import StatisticsMixin


# ============================================================
# Global QSS — maps the existing palette to Qt widgets
# ============================================================

def _image_url(name: str) -> str:
    """Absolute url() path for a bundled Images/ asset, usable inside
    the stylesheet. Resolves beside this file in dev and from the
    PyInstaller bundle when frozen (same logic as the window icon).
    QSS wants forward slashes, even on Windows."""
    if getattr(sys, "frozen", False):
        base = os.path.join(sys._MEIPASS, "Images")
    else:
        base = os.path.join(os.path.dirname(os.path.abspath(__file__)), "Images")
    return os.path.join(base, name).replace("\\", "/")


GLOBAL_QSS = f"""
* {{
    color: {COLOR_TEXT};
    font-family: "Segoe UI", Arial, sans-serif;
    font-size: 13px;
}}
QMainWindow, QDialog, QWidget#root {{
    background-color: {COLOR_BG_BRUSH};
}}
QFrame#sidebar {{
    background-color: {COLOR_SURFACE};
    border: none;
}}
QFrame#card {{
    background-color: {COLOR_SURFACE_BRUSH};
    border-radius: 12px;
}}
QFrame#cardDark {{
    background-color: {COLOR_BG};
    border-radius: 12px;
}}
QFrame#chip {{
    background-color: {COLOR_SURFACE_HOVER};
    border-radius: 10px;
}}
QFrame#motorBlock {{
    background-color: {COLOR_SURFACE};
    border-radius: 10px;
}}
QFrame#tuneStageCard {{
    background-color: {COLOR_SURFACE_HOVER};
    border-radius: 8px;
    border: 1px solid transparent;
    padding: 4px;
}}
QFrame#tuneStageCard[active="true"] {{
    border: 1px solid {COLOR_SUCCESS};
    background-color: {COLOR_SURFACE};
}}
QFrame#tuneStageCard:hover {{
    background-color: {COLOR_SURFACE};
}}
/* Accordion stage card sub-regions + live output number (Cut 9). */
QFrame#stageQuick, QFrame#stageEditorRegion {{
    background: transparent;
    border: none;
}}
QLabel#stageOutNum {{
    color: {COLOR_LIVE};
    font-weight: bold;
}}
QLabel#gainValue {{
    color: {COLOR_TEXT};
    font-weight: bold;
}}
QFrame#overviewTile {{
    background-color: {COLOR_SURFACE};
    border-radius: 10px;
    border: 1px solid transparent;
    padding: 4px;
}}
QFrame#overviewTile:hover {{
    background-color: {COLOR_SURFACE_HOVER};
    border-color: {COLOR_SUCCESS};
}}
QFrame#overviewTile:focus {{
    border-color: {COLOR_INPUT_FOCUS};
}}
QFrame#speedCard {{
    background-color: {COLOR_SURFACE_HOVER};
    border-radius: 8px;
}}
QFrame#zonePanel {{
    background-color: {COLOR_SURFACE_HOVER};
    border-radius: 6px;
}}
QFrame#separator {{
    background-color: {COLOR_SURFACE};
    max-height: 2px;
    min-height: 2px;
    border: none;
}}
QLabel {{
    background: transparent;
}}
QLabel#sidebarTitle {{
    color: {COLOR_PRIMARY};
    font-size: 22px;
    font-weight: bold;
}}
QLabel#viewTitle {{
    color: {COLOR_PRIMARY};
    font-size: 26px;
    font-weight: bold;
}}
QLabel#sectionTitle {{
    color: {COLOR_PRIMARY};
    font-size: 18px;
    font-weight: bold;
}}
QLabel#cardHeader {{
    font-size: 16px;
    font-weight: bold;
    color: {COLOR_INPUT_FOCUS};
}}
QLabel#deviceName {{
    font-size: 14px;
    font-weight: bold;
    color: {COLOR_TEXT};
}}
QLabel#motorLabel {{
    font-weight: bold;
    color: {COLOR_LIVE};
}}
/* Accent overrides for any header label — opt in per widget:
   lbl.setProperty("accent", "live"|"warn"|"ok"|"primary") */
QLabel[accent="live"]    {{ color: {COLOR_LIVE}; }}
QLabel[accent="warn"]    {{ color: {COLOR_WARNING}; }}
QLabel[accent="ok"]      {{ color: {COLOR_SUCCESS}; }}
QLabel[accent="primary"] {{ color: {COLOR_PRIMARY}; }}
QLabel[muted="true"] {{
    color: {COLOR_TEXT_MUTED};
}}
QLabel[role="success"] {{ color: {COLOR_SUCCESS}; }}
QLabel[role="alert"]   {{ color: {COLOR_ALERT}; }}
QLabel[role="warning"] {{ color: {COLOR_WARNING}; }}
QLabel[role="live"]    {{ color: {COLOR_LIVE}; }}

/* Pill badges — small status chips with a tinted fill and accent text.
   Usage: lbl.setProperty("role", "pill"); lbl.setProperty("tone", "ok"|"warn"|"err"|"live"|"info") */
QLabel[role="pill"] {{
    padding: 2px 10px;
    border-radius: 10px;
    font-size: 11px;
    font-weight: bold;
    background-color: {COLOR_SURFACE_HOVER};
    color: {COLOR_TEXT};
}}
QLabel[role="pill"][tone="ok"]   {{ background-color: {COLOR_SUCCESS_DIM}; color: {COLOR_SUCCESS}; }}
QLabel[role="pill"][tone="warn"] {{ background-color: {COLOR_WARNING_DIM}; color: {COLOR_WARNING}; }}
QLabel[role="pill"][tone="err"]  {{ background-color: {COLOR_ALERT_DIM};   color: {COLOR_ALERT}; }}
QLabel[role="pill"][tone="live"] {{ background-color: {COLOR_LIVE_DIM};    color: {COLOR_LIVE}; }}
QLabel[role="pill"][tone="info"] {{ background-color: {COLOR_SURFACE_HOVER}; color: {COLOR_INPUT_FOCUS}; }}

QPushButton {{
    background-color: {COLOR_PRIMARY_BRUSH};
    color: {COLOR_TEXT_ON_PRIMARY};
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
    color: {COLOR_TEXT};
}}
QPushButton[role="secondary"]:hover {{
    background-color: {COLOR_BUTTON_HOVER};
}}
QPushButton[role="danger"] {{
    background-color: {COLOR_ALERT};
    color: {COLOR_TEXT};
}}
QPushButton[role="danger"]:hover {{
    background-color: {COLOR_ALERT_HOVER};
}}
QPushButton[role="ghost"] {{
    background-color: transparent;
    color: {COLOR_TEXT};
    text-align: left;
    padding: 8px 14px;
}}
QPushButton[role="ghost"]:hover {{
    background-color: {COLOR_SURFACE_HOVER};
}}
QPushButton[role="nav"] {{
    background-color: transparent;
    color: {COLOR_TEXT};
    text-align: left;
    padding: 6px 14px;
    border-radius: 6px;
    border-left: 3px solid transparent;
    font-size: 14px;
}}
QPushButton[role="nav"]:hover {{
    background-color: {COLOR_SURFACE_HOVER};
}}
QPushButton[role="nav"][active="true"] {{
    background-color: {COLOR_BG};
    border-left: 3px solid {COLOR_PRIMARY};
    color: {COLOR_INPUT_FOCUS};
    font-weight: bold;
}}
QPushButton[role="profileActive"] {{
    background-color: {COLOR_PRIMARY_BRUSH};
    color: {COLOR_TEXT_ON_PRIMARY};
}}
QPushButton[role="profileActive"]:hover {{
    background-color: {COLOR_PRIMARY_HOVER};
}}
QPushButton[role="profileIdle"] {{
    background-color: {COLOR_BUTTON};
    color: {COLOR_TEXT};
}}
QPushButton[role="profileIdle"]:hover {{
    background-color: {COLOR_BUTTON_HOVER};
}}
/* Sidebar mode-grid buttons (two-line: name over icon). */
QPushButton[role="modeBtn"] {{
    background-color: {COLOR_BUTTON};
    color: {COLOR_TEXT};
    border: 1px solid {COLOR_INPUT_BORDER};
    border-radius: 6px;
    font-size: 11px;
    padding: 3px;
}}
QPushButton[role="modeBtn"]:hover {{
    background-color: {COLOR_BUTTON_HOVER};
}}
QPushButton[role="modeBtn"][active="true"] {{
    background-color: {COLOR_PRIMARY_BRUSH};
    color: {COLOR_TEXT_ON_PRIMARY};
    font-weight: bold;
}}
QPushButton[role="chipClose"] {{
    background-color: transparent;
    color: {COLOR_ALERT};
    font-weight: bold;
    padding: 0px 6px;
}}
QPushButton[role="chipClose"]:hover {{
    background-color: {COLOR_ALERT_HOVER};
    color: {COLOR_TEXT};
}}
QPushButton[role="segActive"] {{
    background-color: qlineargradient(
        x1:0, y1:0, x2:1, y2:0,
        stop:0 {COLOR_PRIMARY}, stop:1 {COLOR_LIVE}
    );
    color: {COLOR_TEXT_ON_PRIMARY};
    font-weight: bold;
}}
QPushButton[role="segIdle"] {{
    background-color: {COLOR_BUTTON};
}}
QPushButton[role="segIdle"]:hover {{
    background-color: {COLOR_BUTTON_HOVER};
}}

QPushButton[role="confirm"] {{
    background-color: {COLOR_SUCCESS};
    color: {COLOR_TEXT};
    font-weight: bold;
}}
QPushButton[role="confirm"]:hover {{
    background-color: #00E064;
}}
QPushButton[role="cancel"] {{
    background-color: {COLOR_ALERT};
    color: {COLOR_TEXT};
    font-weight: bold;
}}
QPushButton[role="cancel"]:hover {{
    background-color: {COLOR_ALERT_HOVER};
}}

QLineEdit, QTextEdit, QPlainTextEdit {{
    background-color: {COLOR_INPUT_BG};
    color: {COLOR_TEXT};
    border: 1px solid {COLOR_INPUT_BORDER};
    border-radius: 4px;
    padding: 4px 6px;
    selection-background-color: {COLOR_PRIMARY};
    selection-color: {COLOR_TEXT_ON_PRIMARY};
}}
QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus {{
    border: 1px solid {COLOR_INPUT_FOCUS};
}}
QTextEdit, QPlainTextEdit {{
    font-family: "Consolas", "Courier New", monospace;
}}
QComboBox, QSpinBox, QDoubleSpinBox, QAbstractSpinBox {{
    background-color: {COLOR_INPUT_BG};
    color: {COLOR_TEXT};
    border: 1px solid {COLOR_INPUT_BORDER};
    border-radius: 4px;
    padding: 4px 6px;
    selection-background-color: {COLOR_PRIMARY};
    selection-color: {COLOR_TEXT_ON_PRIMARY};
}}
QComboBox:hover, QSpinBox:hover, QDoubleSpinBox:hover, QAbstractSpinBox:hover {{
    border-color: {COLOR_INPUT_FOCUS};
}}
/* Spinbox up/down buttons, owned by the stylesheet on purpose: the
   Qt 6.7+ "windows11" base style paints the two arrows side by side
   and (with an app stylesheet active) its hit-testing doesn't match
   the painted arrows — the up arrow goes dead. Defining the
   subcontrols here makes QStyleSheetStyle compute layout, painting
   AND hit-testing from these same boxes, bypassing the broken native
   path and restoring the classic stacked buttons in the app theme.
   The arrows are pure-QSS border triangles (no image assets). */
QAbstractSpinBox {{
    padding-right: 20px;  /* reserve room for the button column */
}}
QAbstractSpinBox::up-button {{
    subcontrol-origin: border;
    subcontrol-position: top right;
    width: 18px;
    border-left: 1px solid {COLOR_INPUT_BORDER};
    border-top-right-radius: 3px;
    background: transparent;
}}
QAbstractSpinBox::down-button {{
    subcontrol-origin: border;
    subcontrol-position: bottom right;
    width: 18px;
    border-left: 1px solid {COLOR_INPUT_BORDER};
    border-bottom-right-radius: 3px;
    background: transparent;
}}
QAbstractSpinBox::up-button:hover, QAbstractSpinBox::down-button:hover {{
    background: {COLOR_BUTTON};
}}
QAbstractSpinBox::up-button:pressed, QAbstractSpinBox::down-button:pressed {{
    background: {COLOR_PRIMARY};
}}
QAbstractSpinBox::up-arrow {{
    image: url("{_image_url('spin_arrow_up.svg')}");
    width: 8px; height: 5px;
}}
QAbstractSpinBox::down-arrow {{
    image: url("{_image_url('spin_arrow_down.svg')}");
    width: 8px; height: 5px;
}}
QAbstractSpinBox::up-arrow:disabled, QAbstractSpinBox::up-arrow:off {{
    image: url("{_image_url('spin_arrow_up_dim.svg')}");
}}
QAbstractSpinBox::down-arrow:disabled, QAbstractSpinBox::down-arrow:off {{
    image: url("{_image_url('spin_arrow_down_dim.svg')}");
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
    selection-color: {COLOR_TEXT_ON_PRIMARY};
    outline: 0;
}}

QCheckBox {{
    background: transparent;
    spacing: 6px;
}}
QCheckBox::indicator {{
    width: 16px;
    height: 16px;
    border: 2px solid {COLOR_TEXT_MUTED};
    border-radius: 3px;
    background-color: {COLOR_INPUT_BG};
}}
QCheckBox::indicator:checked {{
    background-color: {COLOR_PRIMARY};
    border: 2px solid {COLOR_TEXT};
}}
QCheckBox::indicator:hover {{
    border-color: {COLOR_INPUT_FOCUS};
}}
QCheckBox[role="switch"]::indicator {{
    width: 32px;
    height: 16px;
    border-radius: 8px;
}}
QCheckBox[role="switch"]::indicator:checked {{
    background-color: {COLOR_SUCCESS};
    border: 2px solid {COLOR_TEXT};
}}

/* Static-gradient slider trick:
   The groove paints the FULL rainbow once across the whole track, then
   ::add-page (the unfilled side) covers the right portion with the bg
   color. This keeps the gradient at a fixed scale regardless of value,
   so each color always lives at the same position on the track. */
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

QProgressBar {{
    background: {COLOR_BG};
    border: none;
    border-radius: 4px;
    text-align: center;
    color: transparent;
    max-height: 8px;
    min-height: 8px;
}}
/* Default chunk: vertical 2-stop gradient (no horizontal stretch
   artifact since the gradient runs top→bottom; the bar can grow in
   width without distorting). */
QProgressBar::chunk {{
    border-radius: 4px;
    background-color: qlineargradient(
        x1:0, y1:0, x2:0, y2:1,
        stop:0 {COLOR_LIVE},
        stop:1 {COLOR_PRIMARY}
    );
}}
/* Tonal progress variants — set bar.setProperty("tone", "ok"|"warn"|"live"|"rainbow") */
QProgressBar[tone="ok"]::chunk {{
    background-color: qlineargradient(
        x1:0, y1:0, x2:0, y2:1,
        stop:0 {COLOR_SUCCESS}, stop:1 #04A04A
    );
}}
QProgressBar[tone="warn"]::chunk {{
    background-color: qlineargradient(
        x1:0, y1:0, x2:0, y2:1,
        stop:0 {COLOR_WARNING}, stop:1 {COLOR_ALERT}
    );
}}
QProgressBar[tone="live"]::chunk {{
    background-color: qlineargradient(
        x1:0, y1:0, x2:0, y2:1,
        stop:0 {COLOR_LIVE}, stop:1 {COLOR_PRIMARY}
    );
}}
/* Rainbow tone: horizontal 2-stop brand gradient (purple → hot pink). */
QProgressBar[tone="rainbow"]::chunk {{
    background-color: qlineargradient(
        x1:0, y1:0, x2:1, y2:0,
        stop:0 {COLOR_PRIMARY}, stop:1 {COLOR_LIVE}
    );
}}

QScrollArea {{
    border: none;
    background-color: transparent;
}}
QScrollArea > QWidget > QWidget {{
    background-color: transparent;
}}
/* Scrollbar painting is done by the RainbowScrollBar subclass — Qt's
   stylesheet style will hijack paintEvent if QSS sets background/handle
   visuals on QScrollBar, so we only specify sizing/track here. */
QScrollBar {{
    background: transparent;
    border: none;
}}
QScrollBar:vertical {{
    width: 10px;
}}
QScrollBar:horizontal {{
    height: 10px;
}}

QTreeWidget {{
    background-color: {COLOR_BG};
    alternate-background-color: {COLOR_SURFACE};
    color: {COLOR_TEXT};
    border: 1px solid {COLOR_SURFACE};
    font-family: "Consolas", "Courier New", monospace;
}}
QTreeWidget::item {{
    height: 22px;
}}
QTreeWidget::item:selected {{
    background-color: {COLOR_PRIMARY};
    color: {COLOR_TEXT_ON_PRIMARY};
}}
QHeaderView::section {{
    background-color: {COLOR_SURFACE};
    color: {COLOR_TEXT};
    padding: 4px;
    border: none;
    font-weight: bold;
}}
QHeaderView::section:horizontal:!last {{
    border-right: 2px solid {COLOR_BUTTON};
}}
QHeaderView::section:horizontal:!last:hover {{
    border-right: 2px solid {COLOR_PRIMARY};
    background-color: {COLOR_SURFACE_HOVER};
}}
QTableWidget {{
    background-color: {COLOR_BG};
    alternate-background-color: {COLOR_SURFACE};
    color: {COLOR_TEXT};
    border: 1px solid {COLOR_SURFACE};
    gridline-color: transparent;
}}
QTableWidget::item {{
    padding: 0px 6px;
}}
"""


# (ToggleSwitch / _Invoker / _MainWindow / _Card / _BHapticsDotGrid /
# layout + icon helpers were moved into `ui/widgets.py`, `ui/icons.py`,
# `ui/layout_helpers.py`, `ui/text_helpers.py`, `ui/geometry.py`. The
# import-aliases at the top of this file preserve the underscore names.)


# ============================================================
# OscGoesPurrrUI — the PySide6 view layer
# ============================================================

class OscGoesPurrrUI(
    DashboardMixin,
    DiagnosticsMixin,
    SettingsMixin,
    SessionsMixin,
    SteamVRMixin,
    BHapticsMixin,
    PiShockMixin,
    CoyoteMixin,
    OwoMixin,
    HandyMixin,
    DeviceFrameMixin,
    OverviewMixin,
    SpsSourcesMixin,
    StatisticsMixin,
):
    """UI Component class — handles all GUI rendering and updates."""

    # ----------------------------------------------------------
    # Construction
    # ----------------------------------------------------------

    def __init__(self, controller, app_root=None):
        self.controller = controller

        # Bootstrap QApplication (singleton — re-use if one already exists).
        self.qapp: QApplication = QApplication.instance() or QApplication(sys.argv)
        self.qapp.setStyleSheet(GLOBAL_QSS)

        # Main window (intercepts X-button close).
        self.window: _MainWindow = _MainWindow()
        self.window.setObjectName("root")
        # Explicit small minimum so the user can resize the window down — the
        # sidebar is fixed at SIDEBAR_WIDTH so we keep at least that plus a
        # bit of breathing room for the scrollable content area.
        self.window.setMinimumSize(SIDEBAR_WIDTH + 200, 360)
        self.window.resize(1100, 700)

        # Native frame tint (Windows 11 DWM). The purrple profile defines
        # no frame colors, so this block is skipped entirely and the system
        # frame stays exactly as before — the winId() call is inside the
        # guard on purpose, because it forces early native window creation
        # as a side effect. Noir claims the border/caption for its
        # green-on-black identity.
        if COLOR_WINDOW_BORDER or COLOR_WINDOW_CAPTION or COLOR_WINDOW_CAPTION_TEXT:
            _apply_window_frame_colors(
                int(self.window.winId()),
                COLOR_WINDOW_BORDER, COLOR_WINDOW_CAPTION,
                COLOR_WINDOW_CAPTION_TEXT,
            )

        # Set application icon for window title bar and taskbar.
        # Resolves correctly in development and when frozen by PyInstaller.
        try:
            if getattr(sys, "frozen", False):
                icon_path = os.path.join(sys._MEIPASS, "Images", "OGP_Icon.ico")
            else:
                icon_path = os.path.join(os.path.dirname(__file__), "Images", "OGP_Icon.ico")
            if os.path.exists(icon_path):
                icon = QIcon(icon_path)
                self.qapp.setWindowIcon(icon)
                self.window.setWindowIcon(icon)
        except Exception:
            pass

        # Cross-thread scheduler (used by schedule_callback /
        # schedule_on_main_thread when called from a non-UI thread).
        self._invoker = _Invoker()

        # ---- State that the controller reads via the facade ----
        self.device_ui_frames: Dict[str, dict] = {}
        self.stored_device_frames: Dict[str, dict] = {}

        # ---- Lazily-bound view widgets ----
        self.sidebar_frame: Optional[QFrame] = None
        self.main_stack: Optional[QStackedWidget] = None
        self.nav_buttons: Dict[str, QPushButton] = {}
        self.views: Dict[str, QWidget] = {}

        # Sidebar status widgets
        self.status_label: Optional[QLabel] = None
        self.connection_button: Optional[QPushButton] = None
        self.scan_toys_button: Optional[QPushButton] = None
        self.osc_status_label: Optional[QLabel] = None
        self.osc_port_label: Optional[QLabel] = None
        self.osc_connection_button: Optional[QPushButton] = None
        self.osc_refresh_button: Optional[QPushButton] = None
        self.intiface_sidebar_section: Optional[QWidget] = None

        # Settings checkboxes (referenced by facade getters)
        self.auto_connect_var: Optional[QCheckBox] = None
        self.auto_refresh_var: Optional[QCheckBox] = None
        self.osc_auto_connect_var: Optional[QCheckBox] = None

        # Device routing view
        self.devices_container_frame: Optional[QFrame] = None
        self.unified_devices_frame: Optional[QWidget] = None
        self.unified_devices_layout: Optional[QVBoxLayout] = None

        # Help Mode badge registry. Populated by _make_help_badge as
        # views are built; toggled in unison by _set_help_badges_visible.
        # Persisted state lives in app_settings["help_mode_enabled"].
        self._help_badges: list = []

        # Network & debug view
        self.sps_status_label: Optional[QLabel] = None
        self.osc_debugger_button: Optional[QPushButton] = None
        self.osc_search_entry: Optional[QLineEdit] = None
        self.debugger_table: Optional[QTableWidget] = None

        # System log
        self.log_text: Optional[QTextEdit] = None

        # Dashboard
        self.testing_frame: Optional[QFrame] = None
        self.purr_check_button: Optional[QPushButton] = None
        # Modes UI (dashboard rows + sidebar grid, built by
        # _build_dashboard_view / _build_mode_grid, repainted by
        # _refresh_mode_buttons whenever the active mode or its metadata
        # change).
        self.current_avatar_label: Optional[QLabel] = None
        self.mode_list_host: Optional[QWidget] = None
        self.mode_list_layout: Optional[QVBoxLayout] = None
        self.mode_grid_buttons: Optional[list] = None

        # Simple Mode view widgets
        self.simple_mode_toggle: Optional[QCheckBox] = None
        self.simple_mode_settings_toggle: Optional[QCheckBox] = None
        self.simple_mode_status_label: Optional[QLabel] = None
        self.simple_mode_sources_layout: Optional[QVBoxLayout] = None
        self.simple_mode_toys_layout: Optional[QVBoxLayout] = None
        # Battery labels keyed by device name so live battery_update messages
        # can refresh them without rebuilding the whole toy list.
        self.simple_mode_battery_labels: Dict[str, QLabel] = {}
        # Cached snapshot used to skip rebuilds when nothing changed.
        self._simple_mode_last_sources: Optional[tuple] = None
        self._simple_mode_last_toys: Optional[tuple] = None

        # Build the UI tree.
        self.setup_ui()

    # ----------------------------------------------------------
    # Top-level layout
    # ----------------------------------------------------------

    def setup_ui(self):
        root = QWidget()
        root.setObjectName("root")
        root_layout = _hbox(0, 0)
        root.setLayout(root_layout)

        # Sidebar (fixed width). The nav spacing and button padding are kept
        # tight (see _build_sidebar and the nav QSS) so the whole column fits
        # without scrolling at normal window heights — but the column is
        # wrapped in an as-needed scroll area so a short window (snapped
        # half-height, small laptop) clips nothing: without it, the
        # connect buttons at the bottom would be unreachable because the
        # window minimum height is far below the sidebar's natural height.
        self.sidebar_frame = self._build_sidebar()
        sidebar_scroll = QScrollArea()
        sidebar_scroll.setWidgetResizable(True)
        sidebar_scroll.setFrameShape(QFrame.NoFrame)
        sidebar_scroll.setFixedWidth(SIDEBAR_WIDTH)
        sidebar_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        sidebar_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        _install_rainbow_scrollbars(sidebar_scroll)
        sidebar_scroll.setWidget(self.sidebar_frame)
        root_layout.addWidget(sidebar_scroll)

        # Main content area (stacked views). Each page sits inside its own
        # QScrollArea so the window can shrink below the page's natural size
        # without Qt locking the central widget. Form-style pages also get a
        # max-width cap so they hug the left side on wide monitors instead of
        # stretching buttons across 4K — data-heavy pages (tables, logs,
        # device routing) stay full-width.
        self.main_stack = QStackedWidget()
        root_layout.addWidget(self.main_stack, 1)

        view_names = ["Dashboard", "Overview", "Statistics", "Simple Mode",
                      "Device Routing", "SPS Sources",
                      "SteamVR Device Comms", "bHaptics", "PiShock", "Coyote", "OWO",
                      "Handy",
                      "OSC Inspector", "OSC Diagnostics", "System Log",
                      "Settings", "Help"]
        builders = {
            "Dashboard": self._build_dashboard_view,
            "Overview": self._build_overview_view,
            "Statistics": self._build_statistics_view,
            "Simple Mode": self._build_simple_mode_view,
            "Device Routing": self._build_device_routing_view,
            "SPS Sources": self._build_sps_sources_view,
            "SteamVR Device Comms": self._build_steamvr_view,
            "bHaptics": self._build_bhaptics_view,
            "PiShock": self._build_pishock_view,
            "Coyote": self._build_coyote_view,
            "OWO": self._build_owo_view,
            "Handy": self._build_handy_view,
            "OSC Inspector": self._build_network_debug_view,
            "OSC Diagnostics": self._build_osc_diagnostics_view,
            "System Log": self._build_system_log_view,
            "Settings": self._build_settings_view,
            "Help": self._build_help_view,
        }
        for name in view_names:
            page = QWidget()
            page_lay = _vbox(20, 12)
            page.setLayout(page_lay)
            builders[name](page_lay)
            # self.views stores the *wrapper* (scroll area) that's actually
            # in the stack, since select_view / visibility checks compare
            # against main_stack.currentWidget().
            wrapper = self._wrap_page(name, page)
            self.views[name] = wrapper
            self.main_stack.addWidget(wrapper)

        self.window.setCentralWidget(root)

        # Simple Mode hides the advanced nav buttons. On boot, follow the
        # persisted setting — first-time users that enabled Simple Mode see
        # the stripped-down sidebar with Simple Mode pre-selected.
        # apply_feature_visibility() also hides the Intiface sidebar block
        # when that feature flag is off, so call it (it delegates to the
        # simple-mode pass).
        self.apply_feature_visibility()
        if bool(getattr(self.controller, "get_simple_mode", lambda: False)()):
            self.select_view("Simple Mode")
        else:
            self.select_view("Dashboard")

        # Every view is built now — apply the persisted Help Mode state
        # to ALL registered badges in one pass. (Badges are created
        # hidden; per-view builds can't do this because views built
        # later would be missed.)
        self._set_help_badges_visible(
            bool(self.controller.get_app_setting("help_mode_enabled", False))
        )

    # ----------------------------------------------------------
    # Page wrapping (scroll area + optional max-width left-align)
    # ----------------------------------------------------------

    def _wrap_page(self, name: str, page: QWidget) -> QScrollArea:
        """Wrap a built page widget in a QScrollArea so it can shrink below
        its natural width without locking the window above the page minimum.
        Content fills the full available viewport width — Qt's normal layout
        behaviour resizes the page to the scroll area's viewport, so cards
        and buttons grow to use the whole window."""
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        _install_rainbow_scrollbars(scroll)
        scroll.setWidget(page)
        return scroll

    # ----------------------------------------------------------
    # Sidebar
    # ----------------------------------------------------------

    def _build_sidebar(self) -> QFrame:
        sidebar = QFrame()
        sidebar.setObjectName("sidebar")
        # Tight spacing (3px) so the nav list + both connection panels fit
        # without a scroll area.
        lay = _vbox(10, 3)
        sidebar.setLayout(lay)

        title = QLabel("OscGoesPurrr")
        title.setObjectName("sidebarTitle")
        title.setAlignment(Qt.AlignHCenter)
        lay.addSpacing(6)
        lay.addWidget(title)
        lay.addSpacing(12)

        # Mode grid — the six haptic modes, one tap from anywhere. Kept
        # compact (2×3, ~44px buttons, 4px gaps) on purpose: the sidebar
        # has no scroll area, so every extra pixel here squeezes the nav.
        lay.addWidget(self._build_mode_grid())
        lay.addSpacing(8)

        nav_buttons = ["Dashboard", "Overview", "Statistics", "Simple Mode",
                       "Device Routing", "SPS Sources",
                       "SteamVR Device Comms", "bHaptics", "PiShock", "Coyote", "OWO",
                       "Handy",
                       "OSC Inspector", "OSC Diagnostics", "System Log",
                       "Settings", "Help"]
        for name in nav_buttons:
            btn = QPushButton(name)
            btn.setProperty("role", "nav")
            btn.setProperty("active", "false")
            btn.setCursor(Qt.PointingHandCursor)
            btn.clicked.connect(lambda _=False, n=name: self.select_view(n))
            lay.addWidget(btn)
            self.nav_buttons[name] = btn

        # Stretch pushes the bottom section down
        lay.addStretch(1)

        # ===== Bottom status / connection block =====
        # Global Help Mode toggle — lives in the always-visible sidebar
        # so the `?` badges scattered across every view can be turned on
        # from anywhere. Synced with the Device Routing header toggle.
        help_toggle = ToggleSwitch("Help Mode")
        self._register_help_mode_toggle(help_toggle)
        lay.addWidget(help_toggle, 0, Qt.AlignHCenter)
        lay.addSpacing(6)

        # --- VRChat OSC Section ---
        lay.addWidget(self._sidebar_section_row(
            "VRChat OSC",
            "VRChat OSC",
            "The link to VRChat's OSC bus — where every avatar contact "
            "signal comes from. The app waits for VRChat to appear "
            "(mDNS/OSCQuery discovery) before binding a port; hover the "
            "pill for the live port. <b>🔍 Refresh</b> re-handshakes a "
            "\"connected but silent\" link without a full reconnect."
        ))

        # Matches the Intiface pill exactly: "CONNECTED"/"DISCONNECTED" with the
        # same rounded pill styling and ok/err tones (set in update_osc_status).
        self.osc_status_label = QLabel("DISCONNECTED")
        self.osc_status_label.setProperty("role", "pill")
        self.osc_status_label.setProperty("tone", "err")
        self.osc_status_label.setAlignment(Qt.AlignCenter)
        # The listening port now rides in the pill's tooltip (set in
        # update_osc_status) instead of a dedicated label row, to keep the
        # sidebar compact. osc_port_label stays None.
        self.osc_status_label.setToolTip("Listening on Port: --")
        lay.addWidget(self.osc_status_label, 0, Qt.AlignHCenter)

        self.osc_connection_button = QPushButton("Connect to VRChat")
        self.osc_connection_button.setMinimumHeight(BTN_HEIGHT_LARGE)
        self.osc_connection_button.clicked.connect(self.controller.toggle_osc_connection)
        lay.addWidget(self.osc_connection_button)

        # Full-width refresh for the VRChat/OSC link: re-poll VRChat's OSCQuery
        # and re-handshake — recovers a "connected but silent" link without a
        # full disconnect/connect. Mirrors the Intiface refresh, same width as
        # the connect button.
        self.osc_refresh_button = QPushButton("🔍 Refresh")
        self.osc_refresh_button.setMinimumHeight(BTN_HEIGHT_LARGE)
        self.osc_refresh_button.setProperty("role", "secondary")
        self.osc_refresh_button.setToolTip("Re-poll VRChat and re-handshake the OSC link")
        self.osc_refresh_button.setCursor(Qt.PointingHandCursor)
        self.osc_refresh_button.clicked.connect(self.controller.force_osc_rehandshake)
        lay.addWidget(self.osc_refresh_button)
        lay.addSpacing(8)

        # --- Intiface Central Section ---
        # Wrapped in a container so the whole block (separator + title +
        # status + button) hides cleanly when the Intiface feature is off.
        self.intiface_sidebar_section = QWidget()
        intiface_lay = _vbox(0, 6)
        self.intiface_sidebar_section.setLayout(intiface_lay)

        sep = QFrame()
        sep.setObjectName("separator")
        intiface_lay.addWidget(sep)
        intiface_lay.addSpacing(8)

        intiface_lay.addWidget(self._sidebar_section_row(
            "Intiface Central",
            "Intiface Central",
            "The Buttplug.io server that talks to Bluetooth toys. Start "
            "the Intiface Central app first, then Connect. <b>🔍 "
            "Refresh</b> rescans for toys powered on after connecting "
            "(an automatic rescan also runs periodically)."
        ))

        self.status_label = QLabel("DISCONNECTED")
        self.status_label.setProperty("role", "pill")
        self.status_label.setProperty("tone", "err")
        self.status_label.setAlignment(Qt.AlignCenter)
        intiface_lay.addWidget(self.status_label, 0, Qt.AlignHCenter)

        self.connection_button = QPushButton("Connect to Intiface")
        self.connection_button.setMinimumHeight(BTN_HEIGHT_LARGE)
        self.connection_button.clicked.connect(self.controller.connect_to_intiface)
        intiface_lay.addWidget(self.connection_button)

        # Full-width refresh: rescan for toys powered on AFTER connecting. The
        # engine auto-rescans every AUTO_REFRESH_RATE_S; this triggers an
        # immediate scan. Same width as the connect button; disabled until
        # connected (the controller facade also no-ops while disconnected).
        self.scan_toys_button = QPushButton("🔍 Refresh")
        self.scan_toys_button.setMinimumHeight(BTN_HEIGHT_LARGE)
        self.scan_toys_button.setProperty("role", "secondary")
        self.scan_toys_button.setToolTip("Scan for new toys")
        self.scan_toys_button.setCursor(Qt.PointingHandCursor)
        self.scan_toys_button.setEnabled(False)
        self.scan_toys_button.clicked.connect(self.controller.scan_for_toys)
        intiface_lay.addWidget(self.scan_toys_button)
        intiface_lay.addSpacing(8)

        lay.addWidget(self.intiface_sidebar_section)

        return sidebar

    def _sidebar_section_title(self, text: str) -> QLabel:
        lbl = QLabel(text)
        f = lbl.font()
        f.setBold(True)
        f.setPointSize(11)
        lbl.setFont(f)
        lbl.setAlignment(Qt.AlignHCenter)
        return lbl

    def _sidebar_section_row(self, text: str, help_title: str,
                             help_text: str) -> QWidget:
        """Sidebar section title with a Help Mode `?` badge beside it."""
        row = QWidget()
        rl = _hbox(0, 4)
        row.setLayout(rl)
        rl.addStretch(1)
        rl.addWidget(self._sidebar_section_title(text))
        rl.addWidget(self._make_help_badge(help_title, help_text))
        rl.addStretch(1)
        return row

    # ----------------------------------------------------------
    # View switching
    # ----------------------------------------------------------

    def select_view(self, view_name: str):
        if view_name not in self.views or self.main_stack is None:
            return
        for name, btn in self.nav_buttons.items():
            btn.setProperty("active", "true" if name == view_name else "false")
            btn.style().unpolish(btn)
            btn.style().polish(btn)
        self.main_stack.setCurrentWidget(self.views[view_name])

        # OSC debugger should only run while the inspector page is visible.
        is_inspector = (view_name == "OSC Inspector")
        debugging = bool(getattr(self.controller, "is_debugging_osc", False))
        if is_inspector and not debugging:
            self.controller.toggle_osc_debugger()
        elif not is_inspector and debugging:
            self.controller.toggle_osc_debugger()

        # Pages pause their periodic refreshers while hidden (the
        # handlers early-out on isVisible) — run the page's refresher(s)
        # once on arrival so it never shows data older than one tick.
        # Now that setCurrentWidget has run, the visibility checks pass.
        # The backend pages also repopulate their zone dropdowns here so
        # zones detected while the page was hidden become selectable.
        arrival_refreshers = {
            "Overview": ("_refresh_overview_dynamic",),
            "Statistics": ("_refresh_statistics_view",),
            "SteamVR Device Comms": ("_refresh_steamvr_status_only",),
            "bHaptics": ("_refresh_bhaptics_status_only",),
            "PiShock": ("_refresh_pishock_status_only",
                        "_repopulate_pishock_zone_combos"),
            "Coyote": ("_refresh_coyote_status_only",
                       "_repopulate_coyote_zone_combos"),
            "OWO": ("_refresh_owo_status_only",
                    "_repopulate_owo_zone_combos"),
            "Handy": ("_refresh_handy_status_only",
                      "_repopulate_handy_zone_combos"),
            "Settings": ("_refresh_sessions_view",),
        }
        for name in arrival_refreshers.get(view_name, ()):
            fn = getattr(self, name, None)
            if callable(fn):
                try:
                    fn()
                except Exception:
                    # Arrival refresh is best-effort; the periodic tick
                    # lands within a second or two anyway.
                    pass

    # ----------------------------------------------------------
    # Sidebar backend status dots
    # ----------------------------------------------------------

    # (nav entry, controller status getter, truthy field). The user's core
    # scenario runs 2-3 backends at once; these dots are the ambient "what
    # is currently live?" signal without visiting each tab.
    _BACKEND_NAV_STATUS = (
        ("SteamVR Device Comms", "get_steamvr_status", "alive"),
        ("bHaptics", "get_bhaptics_status", "connected"),
        ("PiShock", "get_pishock_status", "connected"),
        ("Coyote", "get_coyote_status", "connected"),
        ("OWO", "get_owo_status", "connected"),
        ("Handy", "get_handy_status", "connected"),
    )

    def update_backend_nav_dots(self) -> None:
        """Paint a small connected/disconnected dot on each backend's nav
        button. Piggybacks on the controller's existing 1 Hz heartbeat (no
        new timer); the icon only changes when a backend's state flips, so
        the steady-state cost is seven cheap facade reads."""
        cache = getattr(self, "_nav_dot_state", None)
        if cache is None:
            cache = self._nav_dot_state = {}
        for name, getter_name, field in self._BACKEND_NAV_STATUS:
            btn = self.nav_buttons.get(name)
            if btn is None or btn.isHidden():
                continue  # feature off — no dot to maintain
            getter = getattr(self.controller, getter_name, None)
            ok = False
            if callable(getter):
                try:
                    ok = bool((getter() or {}).get(field))
                except Exception:
                    ok = False
            if cache.get(name) == ok:
                continue
            cache[name] = ok
            try:
                btn.setIcon(self._nav_dot_icon(ok))
                btn.setIconSize(QSize(8, 8))
            except RuntimeError:
                pass

    def _nav_dot_icon(self, ok: bool) -> QIcon:
        icons = getattr(self, "_nav_dot_icons", None)
        if icons is None:
            icons = self._nav_dot_icons = {}
        if ok not in icons:
            pm = QPixmap(8, 8)
            pm.fill(Qt.transparent)
            p = QPainter(pm)
            p.setRenderHint(QPainter.Antialiasing)
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(COLOR_SUCCESS) if ok else QColor(90, 90, 100))
            p.drawEllipse(0, 0, 8, 8)
            p.end()
            icons[ok] = QIcon(pm)
        return icons[ok]

    # ----------------------------------------------------------
    # Logging
    # ----------------------------------------------------------

    def log_message(self, message: str):
        # This sink is handed to the backend engines as their `log=` callback,
        # so it gets called from reconnect/send worker threads. Qt widgets may
        # only be touched on the GUI thread — marshal through the Invoker
        # when we're anywhere else (one queued hop for a log line is fine;
        # this is not a haptic path).
        if QThread.currentThread() is not self._invoker.thread():
            self._invoker.schedule(0, lambda m=message: self.log_message(m))
            return
        if self.log_text is not None:
            self.log_text.append(f"> {message}")
            sb = self.log_text.verticalScrollBar()
            sb.setValue(sb.maximum())

    # ----------------------------------------------------------
    # Connection status displays
    # ----------------------------------------------------------

    def update_connection_status(self, connected: bool, server: str):
        # Sync haptic engine flag through the controller facade
        # (preserves prior behaviour without holding a reference to the engine).
        if hasattr(self.controller, 'set_haptic_connected'):
            self.controller.set_haptic_connected(connected)

        if self.connection_button is not None:
            if connected:
                self.connection_button.setText("Disconnect from Intiface")
                self.connection_button.setProperty("role", "danger")
            else:
                self.connection_button.setText("Connect to Intiface")
                self.connection_button.setProperty("role", "")
            self._repolish(self.connection_button)

        if self.scan_toys_button is not None:
            # A manual rescan only makes sense once the server is up.
            self.scan_toys_button.setEnabled(connected)

        if self.status_label is not None:
            self.status_label.setProperty("role", "pill")
            if connected:
                self.status_label.setText("CONNECTED")
                self.status_label.setProperty("tone", "ok")
            else:
                self.status_label.setText("DISCONNECTED")
                self.status_label.setProperty("tone", "err")
            self._repolish(self.status_label)

        self.update_stored_devices_ui()

    def update_osc_status(self, is_connected: bool, port: int = None):
        if self.osc_status_label is None:
            return
        self.osc_status_label.setProperty("role", "pill")
        if is_connected:
            self.osc_status_label.setText("CONNECTED")
            self.osc_status_label.setProperty("tone", "ok")
            if port:
                self.osc_status_label.setToolTip(f"Listening on Port: {port}")
            if self.osc_connection_button is not None:
                self.osc_connection_button.setText("Disconnect VRChat")
                self.osc_connection_button.setProperty("role", "danger")
                self._repolish(self.osc_connection_button)
        else:
            self.osc_status_label.setText("DISCONNECTED")
            self.osc_status_label.setProperty("tone", "err")
            self.osc_status_label.setToolTip("Listening on Port: --")
            if self.osc_connection_button is not None:
                self.osc_connection_button.setText("Connect to VRChat")
                self.osc_connection_button.setProperty("role", "")
                self._repolish(self.osc_connection_button)
        self._repolish(self.osc_status_label)

    def _repolish(self, w: QWidget) -> None:
        w.style().unpolish(w)
        w.style().polish(w)

    # ============================================================
    # Framework-agnostic facade
    # ============================================================

    # --- Window lifecycle ---
    def set_title(self, text: str) -> None:
        self.window.setWindowTitle(text)

    def set_geometry(self, geometry: str) -> None:
        parsed = _parse_tk_geometry(geometry)
        if parsed is None:
            return
        w, h, x, y = parsed
        self.window.resize(int(w), int(h))
        if x is not None and y is not None:
            # Clamp against the current virtual desktop: a position saved on
            # a since-disconnected monitor must not restore the window fully
            # off-screen (negative coords for a left-of-primary monitor that
            # still exists remain valid — we only rescue invisible windows).
            x, y = int(x), int(y)
            visible = False
            for screen in QApplication.screens():
                avail = screen.availableGeometry()
                if avail.intersects(QRect(x, y, int(w), max(int(h), 1))):
                    visible = True
                    break
            if not visible:
                primary = QApplication.primaryScreen()
                if primary is not None:
                    avail = primary.availableGeometry()
                    x = max(avail.left(), min(x, avail.right() - int(w)))
                    y = max(avail.top(), min(y, avail.bottom() - 100))
            self.window.move(x, y)

    def get_geometry(self) -> str:
        # Width/height come from geometry() (client-area size, matches
        # resize()). x/y come from pos() (frame position, matches move()) —
        # mixing geometry().x()/y() with move() makes the window walk
        # down-and-right by the title-bar height on every restart.
        g = self.window.geometry()
        p = self.window.pos()
        return _format_tk_geometry(g.width(), g.height(), p.x(), p.y())

    def set_close_handler(self, callback) -> None:
        self.window.set_close_handler(callback)

    def schedule_callback(self, delay_ms: int, func) -> None:
        """Run `func` on the UI thread after `delay_ms` (thread-safe)."""
        self._invoker.schedule(delay_ms, func)

    def run_ui_task(self, work, on_done, buttons=(),
                    watchdog_ms: int = 30000) -> None:
        """Run blocking `work()` on a short-lived worker thread and deliver
        `on_done(result)` back on the UI thread.

        For button-triggered actions that block on I/O (manual connects,
        BLE scans): the Qt event loop must never stall on them — it hosts
        the Buttplug routing tick. Any widgets in `buttons` are disabled
        while the task runs and re-enabled with the result. Errors inside
        `work` are delivered as the exception object so `on_done` can
        format a message instead of the task dying silently.

        The watchdog re-enables the buttons even if `work` wedges forever
        (a dead COM port, a black-holing network) — a stuck task must not
        leave a dead Connect button for the rest of the session.
        """
        import threading as _threading

        def _set_enabled(enabled: bool) -> None:
            for b in buttons:
                try:
                    b.setEnabled(enabled)
                except RuntimeError:
                    pass  # widget deleted while the task ran

        _set_enabled(False)
        if watchdog_ms > 0:
            self._invoker.schedule(watchdog_ms, lambda: _set_enabled(True))

        def _deliver(result):
            _set_enabled(True)
            try:
                on_done(result)
            except Exception:
                # on_done is best-effort UI work; it must never propagate
                # into the Invoker slot.
                pass

        def _run():
            try:
                result = work()
            except Exception as e:
                result = e
            self._invoker.schedule(0, lambda r=result: _deliver(r))

        _threading.Thread(target=_run, daemon=True, name="UITask").start()

    def schedule_on_main_thread(self, func) -> None:
        self._invoker.schedule(0, func)

    def hide_window(self) -> None:
        self.window.hide()

    def show_window(self) -> None:
        # Thread-safe restore.
        self._invoker.schedule(0, lambda: (
            self.window.showNormal(),
            self.window.activateWindow(),
            self.window.raise_(),
        ))

    def run(self) -> None:
        self.window.show()
        self.qapp.exec()

    def shutdown(self) -> None:
        # Bypass the X-button interception when we explicitly quit.
        self.window.allow_close()
        self.window.close()
        self.qapp.quit()

    # --- Settings checkbox state ---
    def get_auto_connect_enabled(self) -> bool:
        cb = self.auto_connect_var
        return bool(cb.isChecked()) if cb is not None else False

    def get_auto_refresh_enabled(self) -> bool:
        cb = self.auto_refresh_var
        return bool(cb.isChecked()) if cb is not None else False

    def get_osc_auto_connect_enabled(self) -> bool:
        cb = self.osc_auto_connect_var
        return bool(cb.isChecked()) if cb is not None else False

    # --- OSC debugger ---
    def get_osc_search_query(self) -> str:
        if self.osc_search_entry is None:
            return ""
        return self.osc_search_entry.text().lower()

    def update_sps_status(self, text: str) -> None:
        if self.sps_status_label is not None:
            self.sps_status_label.setText(text)

    # Backwards-compat alias (old code may have set self.app).
    @property
    def app(self):
        return self.window


# (_SliderProxy / _ProgressProxy / _truncate / _html_escape now live in
# `ui/widgets.py` and `ui/text_helpers.py`. The import-aliases at the top
# of this file preserve the underscore names.)
