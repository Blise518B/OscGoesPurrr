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
    Qt, QTimer, Signal, QObject, QEvent, QSize, QPointF, QRectF
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
from utilities import strip_param_prefix

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
from ui.views.steamvr import SteamVRMixin
from ui.views.bhaptics import BHapticsMixin
from ui.views.hardware_monitor import HardwareMonitorMixin
from ui.views.device_frame import DeviceFrameMixin
from ui.views.tune import TuneMixin


# ============================================================
# Global QSS — maps the existing palette to Qt widgets
# ============================================================

GLOBAL_QSS = f"""
* {{
    color: {COLOR_TEXT};
    font-family: "Segoe UI", Arial, sans-serif;
    font-size: 13px;
}}
QMainWindow, QDialog, QWidget#root {{
    background-color: {COLOR_BG};
}}
QFrame#sidebar {{
    background-color: {COLOR_SURFACE};
    border: none;
}}
QFrame#card {{
    background-color: {COLOR_SURFACE};
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
    padding: 10px 14px;
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
    background-color: {COLOR_PRIMARY};
    color: {COLOR_TEXT};
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
    color: {COLOR_TEXT};
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
}}
QComboBox:hover, QSpinBox:hover, QDoubleSpinBox:hover, QAbstractSpinBox:hover {{
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
    color: white;
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
    SteamVRMixin,
    BHapticsMixin,
    HardwareMonitorMixin,
    DeviceFrameMixin,
    TuneMixin,
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
        self.osc_status_label: Optional[QLabel] = None
        self.osc_port_label: Optional[QLabel] = None
        self.osc_connection_button: Optional[QPushButton] = None
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
        # Legacy HTML-rendered inspector kept alongside the table for comparison.
        self.debugger_textbox: Optional[QTextEdit] = None

        # System log
        self.log_text: Optional[QTextEdit] = None

        # Dashboard
        self.testing_frame: Optional[QFrame] = None
        self.purr_check_button: Optional[QPushButton] = None
        # Profile-manager UI (built by _build_dashboard_view, rebuilt by
        # _refresh_profile_buttons whenever profiles/clipboard/avatar change).
        self.profile_active_label: Optional[QLabel] = None
        self.current_avatar_label: Optional[QLabel] = None
        self.global_profile_list_layout: Optional[QVBoxLayout] = None
        self.global_profile_list_host: Optional[QWidget] = None
        self.avatar_profile_list_layout: Optional[QVBoxLayout] = None
        self.avatar_profile_list_host: Optional[QWidget] = None
        self.global_paste_btn: Optional[QPushButton] = None
        self.avatar_paste_btn: Optional[QPushButton] = None
        self.avatar_new_btn: Optional[QPushButton] = None
        self.avatar_manage_btn: Optional[QPushButton] = None

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

        # Sidebar (fixed width)
        self.sidebar_frame = self._build_sidebar()
        self.sidebar_frame.setFixedWidth(SIDEBAR_WIDTH)
        root_layout.addWidget(self.sidebar_frame)

        # Main content area (stacked views). Each page sits inside its own
        # QScrollArea so the window can shrink below the page's natural size
        # without Qt locking the central widget. Form-style pages also get a
        # max-width cap so they hug the left side on wide monitors instead of
        # stretching buttons across 4K — data-heavy pages (tables, logs,
        # device routing) stay full-width.
        self.main_stack = QStackedWidget()
        root_layout.addWidget(self.main_stack, 1)

        view_names = ["Dashboard", "Simple Mode", "Device Routing", "Tune",
                      "SteamVR Device Comms", "bHaptics", "Hardware Monitor",
                      "OSC Inspector", "OSC Diagnostics", "System Log",
                      "Settings", "Help"]
        builders = {
            "Dashboard": self._build_dashboard_view,
            "Simple Mode": self._build_simple_mode_view,
            "Device Routing": self._build_device_routing_view,
            "Tune": self._build_tune_view,
            "SteamVR Device Comms": self._build_steamvr_view,
            "bHaptics": self._build_bhaptics_view,
            "Hardware Monitor": self._build_hardware_monitor_view,
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
        lay = _vbox(10, 6)
        sidebar.setLayout(lay)

        title = QLabel("OscGoesPurrr")
        title.setObjectName("sidebarTitle")
        title.setAlignment(Qt.AlignHCenter)
        lay.addSpacing(10)
        lay.addWidget(title)
        lay.addSpacing(20)

        nav_buttons = ["Dashboard", "Simple Mode", "Device Routing", "Tune",
                       "SteamVR Device Comms", "bHaptics", "Hardware Monitor",
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
        # --- VRChat OSC Section ---
        lay.addWidget(self._sidebar_section_title("VRChat OSC"))

        self.osc_status_label = QLabel("WAITING FOR VRCHAT")
        self.osc_status_label.setProperty("role", "pill")
        self.osc_status_label.setProperty("tone", "warn")
        self.osc_status_label.setAlignment(Qt.AlignCenter)
        lay.addWidget(self.osc_status_label, 0, Qt.AlignHCenter)

        self.osc_port_label = QLabel("Listening on Port: --")
        self.osc_port_label.setAlignment(Qt.AlignHCenter)
        lay.addWidget(self.osc_port_label)

        self.osc_connection_button = QPushButton("Connect to VRChat")
        self.osc_connection_button.setMinimumHeight(BTN_HEIGHT_LARGE)
        self.osc_connection_button.clicked.connect(self.controller.toggle_osc_connection)
        lay.addWidget(self.osc_connection_button)
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

        intiface_lay.addWidget(self._sidebar_section_title("Intiface Central"))

        self.status_label = QLabel("DISCONNECTED")
        self.status_label.setProperty("role", "pill")
        self.status_label.setProperty("tone", "err")
        self.status_label.setAlignment(Qt.AlignCenter)
        intiface_lay.addWidget(self.status_label, 0, Qt.AlignHCenter)

        self.connection_button = QPushButton("Connect to Intiface")
        self.connection_button.setMinimumHeight(BTN_HEIGHT_LARGE)
        self.connection_button.clicked.connect(self.controller.connect_to_intiface)
        intiface_lay.addWidget(self.connection_button)
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

    # ----------------------------------------------------------
    # Logging
    # ----------------------------------------------------------

    def log_message(self, message: str):
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
            self.osc_status_label.setText("VRCHAT CONNECTED")
            self.osc_status_label.setProperty("tone", "ok")
            if port and self.osc_port_label is not None:
                self.osc_port_label.setText(f"Listening on Port: {port}")
            if self.osc_connection_button is not None:
                self.osc_connection_button.setText("Disconnect VRChat")
                self.osc_connection_button.setProperty("role", "danger")
                self._repolish(self.osc_connection_button)
        else:
            self.osc_status_label.setText("WAITING FOR VRCHAT")
            self.osc_status_label.setProperty("tone", "warn")
            if self.osc_port_label is not None:
                self.osc_port_label.setText("Listening on Port: --")
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
            self.window.move(int(x), int(y))

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
