# OscGoesPurrr - UI Components Module (PySide6)
#
# Pure View layer. The controller talks to this class through a fixed facade
# (set_title, schedule_callback, run, update_*, etc.). Swapping toolkits
# means rewriting this file only.

from typing import List, Optional, Dict, Any, Callable
import os
import re
import sys

from PySide6.QtCore import (
    Qt, QTimer, Signal, QObject, QEvent, QSize, QPointF, QRectF
)
from PySide6.QtGui import (
    QFont, QColor, QTextCharFormat, QTextCursor, QFontDatabase, QIcon, QPalette,
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
)


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
    border-radius: 8px;
}}
QFrame#cardDark {{
    background-color: {COLOR_BG};
    border-radius: 8px;
}}
QFrame#chip {{
    background-color: {COLOR_SURFACE_HOVER};
    border-radius: 10px;
}}
QFrame#motorBlock {{
    background-color: {COLOR_SURFACE};
    border-radius: 6px;
}}
QFrame#zonePanel {{
    background-color: {COLOR_SURFACE_HOVER};
    border-radius: 4px;
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
}}
QLabel#deviceName {{
    font-size: 14px;
    font-weight: bold;
}}
QLabel#motorLabel {{
    font-weight: bold;
}}
QLabel[muted="true"] {{
    color: {COLOR_TEXT_MUTED};
}}
QLabel[role="success"] {{ color: {COLOR_SUCCESS}; }}
QLabel[role="alert"]   {{ color: {COLOR_ALERT}; }}

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
    font-size: 14px;
}}
QPushButton[role="nav"]:hover {{
    background-color: {COLOR_SURFACE_HOVER};
}}
QPushButton[role="nav"][active="true"] {{
    background-color: {COLOR_BG};
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
    background-color: {COLOR_PRIMARY};
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

QSlider::groove:horizontal {{
    height: 6px;
    background: {COLOR_SURFACE};
    border-radius: 3px;
}}
QSlider::sub-page:horizontal {{
    background: {COLOR_PRIMARY};
    border-radius: 3px;
}}
QSlider::handle:horizontal {{
    background: {COLOR_PRIMARY};
    width: 16px;
    margin: -6px 0;
    border-radius: 8px;
}}
QSlider::handle:horizontal:hover {{
    background: {COLOR_PRIMARY_HOVER};
}}

QProgressBar {{
    background: {COLOR_SURFACE};
    border: none;
    border-radius: 3px;
    text-align: center;
    color: transparent;
    max-height: 6px;
    min-height: 6px;
}}
QProgressBar::chunk {{
    background-color: {COLOR_PRIMARY};
    border-radius: 3px;
}}

QScrollArea {{
    border: none;
    background-color: transparent;
}}
QScrollArea > QWidget > QWidget {{
    background-color: transparent;
}}
QScrollBar:vertical {{
    background: {COLOR_BG};
    width: 10px;
    border: none;
}}
QScrollBar::handle:vertical {{
    background: {COLOR_SURFACE_HOVER};
    border-radius: 5px;
    min-height: 30px;
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0px;
}}
QScrollBar:horizontal {{
    background: {COLOR_BG};
    height: 10px;
    border: none;
}}
QScrollBar::handle:horizontal {{
    background: {COLOR_SURFACE_HOVER};
    border-radius: 5px;
    min-width: 30px;
}}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
    width: 0px;
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

class OscGoesPurrrUI:
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

        view_names = ["Dashboard", "Simple Mode", "Device Routing",
                      "SteamVR Device Comms", "bHaptics", "Hardware Monitor",
                      "OSC Inspector", "OSC Diagnostics", "System Log",
                      "Settings", "Help"]
        builders = {
            "Dashboard": self._build_dashboard_view,
            "Simple Mode": self._build_simple_mode_view,
            "Device Routing": self._build_device_routing_view,
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

        nav_buttons = ["Dashboard", "Simple Mode", "Device Routing",
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

        self.osc_status_label = QLabel("Status: Waiting for VRChat...")
        self.osc_status_label.setProperty("role", "alert")
        self.osc_status_label.setAlignment(Qt.AlignHCenter)
        lay.addWidget(self.osc_status_label)

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

        self.status_label = QLabel("Status: Disconnected")
        self.status_label.setProperty("role", "alert")
        self.status_label.setAlignment(Qt.AlignHCenter)
        intiface_lay.addWidget(self.status_label)

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
    # Dashboard view
    # ----------------------------------------------------------

    def _build_dashboard_view(self, parent_layout: QVBoxLayout):
        title = QLabel("Dashboard")
        title.setObjectName("viewTitle")
        title.setAlignment(Qt.AlignHCenter)
        parent_layout.addWidget(title)

        # ===== Profile manager card =====
        prof_card = _Card()
        prof_lay = _vbox(16, 10)
        prof_card.setLayout(prof_lay)

        # Active-profile banner (kind + name)
        self.profile_active_label = QLabel("Active profile: —")
        f = self.profile_active_label.font(); f.setBold(True); f.setPointSize(13)
        self.profile_active_label.setFont(f)
        prof_lay.addWidget(self.profile_active_label)

        prof_lay.addWidget(self._muted_label(
            "Profiles hold per-toy settings: SPS zones, OSC mappings, filters. "
            "Avatar profiles auto-activate when their bound avatar loads."
        ))

        # ---- Global section ----
        global_header = QLabel("Global Profiles")
        global_header.setObjectName("sectionTitle")
        prof_lay.addWidget(global_header)
        prof_lay.addWidget(self._muted_label(
            "Manually selected. Active when no avatar profile is bound."
        ))

        self.global_profile_list_host = QWidget()
        self.global_profile_list_layout = _vbox(0, 4)
        self.global_profile_list_host.setLayout(self.global_profile_list_layout)
        prof_lay.addWidget(self.global_profile_list_host)

        gfooter = QWidget()
        gflay = _hbox(0, 6)
        gfooter.setLayout(gflay)
        new_global = QPushButton("+ New Global Profile")
        new_global.setMinimumHeight(34)
        new_global.setProperty("role", "secondary")
        new_global.clicked.connect(self._add_new_profile)
        gflay.addWidget(new_global, 1)
        self.global_paste_btn = QPushButton("📥 Paste")
        self.global_paste_btn.setMinimumHeight(34)
        self.global_paste_btn.setProperty("role", "secondary")
        self.global_paste_btn.clicked.connect(lambda _=False: self.controller.paste_profile("global"))
        gflay.addWidget(self.global_paste_btn)
        prof_lay.addWidget(gfooter)

        # ---- Divider ----
        divider = QFrame()
        divider.setObjectName("separator")
        prof_lay.addSpacing(4)
        prof_lay.addWidget(divider)
        prof_lay.addSpacing(4)

        # ---- Avatar section ----
        avatar_header_row = QWidget()
        ahlay = _hbox(0, 8)
        avatar_header_row.setLayout(ahlay)
        avatar_header = QLabel("Avatar Profiles")
        avatar_header.setObjectName("sectionTitle")
        ahlay.addWidget(avatar_header)
        ahlay.addStretch(1)
        self.current_avatar_label = QLabel("Current avatar: (not detected)")
        self.current_avatar_label.setProperty("muted", "true")
        ahlay.addWidget(self.current_avatar_label)
        prof_lay.addWidget(avatar_header_row)

        prof_lay.addWidget(self._muted_label(
            "Bound to a VRChat avatar ID. The bound profile auto-activates "
            "when that avatar loads, taking precedence over the global selection."
        ))

        self.avatar_profile_list_host = QWidget()
        self.avatar_profile_list_layout = _vbox(0, 4)
        self.avatar_profile_list_host.setLayout(self.avatar_profile_list_layout)
        prof_lay.addWidget(self.avatar_profile_list_host)

        afooter = QWidget()
        aflay = _hbox(0, 6)
        afooter.setLayout(aflay)
        self.avatar_new_btn = QPushButton("+ New Avatar Profile (bind to current)")
        self.avatar_new_btn.setMinimumHeight(34)
        self.avatar_new_btn.setProperty("role", "secondary")
        self.avatar_new_btn.clicked.connect(lambda _=False: self.controller.create_avatar_profile())
        aflay.addWidget(self.avatar_new_btn, 1)
        self.avatar_paste_btn = QPushButton("📥 Paste")
        self.avatar_paste_btn.setMinimumHeight(34)
        self.avatar_paste_btn.setProperty("role", "secondary")
        self.avatar_paste_btn.clicked.connect(lambda _=False: self.controller.paste_profile("avatar"))
        aflay.addWidget(self.avatar_paste_btn)
        prof_lay.addWidget(afooter)

        # Manage-all button lives below the "+ New / Paste" row so the
        # Dashboard list can stay short (only profiles bound to the current
        # avatar) while still offering a single click to browse the full set.
        self.avatar_manage_btn = QPushButton("📂 Manage all avatar profiles")
        self.avatar_manage_btn.setMinimumHeight(30)
        self.avatar_manage_btn.setProperty("role", "secondary")
        self.avatar_manage_btn.clicked.connect(
            lambda _=False: self._open_avatar_profile_manager()
        )
        prof_lay.addWidget(self.avatar_manage_btn)

        parent_layout.addWidget(prof_card)

        # ===== Purr-check card =====
        self.testing_frame = _Card()
        tlay = _vbox(12, 8)
        self.testing_frame.setLayout(tlay)
        self.purr_check_button = QPushButton("Purr-Check (Test All)")
        self.purr_check_button.setMinimumHeight(40)
        self.purr_check_button.clicked.connect(self.controller.trigger_purr_check)
        tlay.addWidget(self.purr_check_button, alignment=Qt.AlignHCenter)
        parent_layout.addWidget(self.testing_frame)
        parent_layout.addStretch(1)

        # Initial render of both lists.
        self._refresh_profile_buttons()

    # ------------------------------------------------------------------
    # Profile section helpers
    # ------------------------------------------------------------------

    def _refresh_profile_buttons(self):
        """Rebuild both profile sections + update the active banner."""
        ctl = self.controller
        active = ctl.get_active_profile_info() \
            if hasattr(ctl, "get_active_profile_info") \
            else {"kind": "global", "name": ctl.get_current_global_profile_name()}

        # ---- Active banner ----
        if self.profile_active_label is not None:
            kind_label = "Avatar" if active["kind"] == "avatar" else "Global"
            self.profile_active_label.setText(
                f"Active profile: {kind_label} · {active['name']}"
            )

        # ---- Current avatar label ----
        if self.current_avatar_label is not None:
            avatar_id = ctl.get_current_avatar_id() or ""
            if avatar_id:
                self.current_avatar_label.setText(f"Current avatar: {_truncate(avatar_id, 28)}")
            else:
                self.current_avatar_label.setText("Current avatar: (not detected)")

        # ---- Clipboard-aware paste buttons ----
        has_clip = ctl.has_clipboard()
        src = ctl.get_clipboard_source_name() or ""
        for btn in (self.global_paste_btn, self.avatar_paste_btn):
            if btn is None:
                continue
            btn.setEnabled(has_clip)
            btn.setText(f"📥 Paste (from '{_truncate(src, 18)}')" if has_clip else "📥 Paste")

        # ---- Avatar 'New' button availability ----
        if self.avatar_new_btn is not None:
            avatar_id = ctl.get_current_avatar_id() or ""
            if avatar_id:
                self.avatar_new_btn.setEnabled(True)
                self.avatar_new_btn.setText(
                    f"+ New Avatar Profile (binds to {_truncate(avatar_id, 16)})"
                )
                self.avatar_new_btn.setToolTip("")
            else:
                self.avatar_new_btn.setEnabled(False)
                self.avatar_new_btn.setText("+ New Avatar Profile (no avatar detected)")
                self.avatar_new_btn.setToolTip(
                    "Load any avatar in VRChat first so the profile knows which avatar to bind to."
                )

        # ---- Manage-all button ----
        if self.avatar_manage_btn is not None:
            total = len(ctl.get_avatar_profile_names())
            self.avatar_manage_btn.setText(
                f"📂 Manage all avatar profiles ({total})"
            )
            self.avatar_manage_btn.setEnabled(total > 0)

        # ---- Rebuild rows ----
        self._build_global_profile_rows(active)
        self._build_avatar_profile_rows(active)

    # Backwards-compat alias for older internal callers.
    def _build_profile_slots(self):
        self._refresh_profile_buttons()

    def _build_global_profile_rows(self, active: dict):
        if self.global_profile_list_layout is None:
            return
        _clear_layout(self.global_profile_list_layout)

        names = self.controller.get_global_profile_names()
        can_delete = len(names) > 1
        for name in names:
            # Exactly one profile across both sections shows the highlight:
            # whichever the resolver currently considers active. Clicking
            # any global flips the override on, so the highlight follows.
            is_active = (active["kind"] == "global" and name == active["name"])
            row = self._make_profile_row(
                name=name,
                is_selected=is_active,
                is_active=is_active,
                on_activate=lambda n=name: self.controller.switch_profile(n),
                on_rename=lambda n=name: self._start_profile_rename("global", n),
                on_copy=lambda n=name: self.controller.copy_profile("global", n),
                on_delete=lambda n=name: self._confirm_profile_delete("global", n),
                can_delete=can_delete,
                kind="global",
            )
            self.global_profile_list_layout.addWidget(row)

    def _build_avatar_profile_rows(self, active: dict):
        """Show only profiles bound to the *current* avatar (typically 0–1
        rows). The rest live in the Avatar Profile Manager dialog so the
        Dashboard stays uncluttered when you have many avatars."""
        if self.avatar_profile_list_layout is None:
            return
        _clear_layout(self.avatar_profile_list_layout)

        ctl = self.controller
        current_avatar = ctl.get_current_avatar_id() or ""
        all_names = ctl.get_avatar_profile_names()
        relevant = [
            n for n in all_names
            if ctl.get_avatar_binding(n) == current_avatar and current_avatar
        ]

        if not relevant:
            if not current_avatar:
                msg = "No avatar detected — load any avatar in VRChat first."
            elif not all_names:
                msg = "No avatar profiles yet. Click '+ New Avatar Profile' above."
            else:
                msg = ("No profile bound to the current avatar. Create one above, "
                       "or open the manager below to bind an existing profile.")
            empty = QLabel(msg)
            empty.setProperty("muted", "true")
            empty.setWordWrap(True)
            self._repolish(empty)
            self.avatar_profile_list_layout.addWidget(empty)
        else:
            for name in relevant:
                bound_id = ctl.get_avatar_binding(name)
                is_active = (active["kind"] == "avatar" and name == active["name"])
                row = self._make_profile_row(
                    name=name,
                    is_selected=is_active,
                    is_active=is_active,
                    bound_avatar_id=bound_id,
                    bound_is_current=True,
                    on_activate=lambda n=name: self.controller.bind_avatar_profile_to_current(n),
                    on_rename=lambda n=name: self._start_profile_rename("avatar", n),
                    on_copy=lambda n=name: self.controller.copy_profile("avatar", n),
                    on_delete=lambda n=name: self._confirm_profile_delete("avatar", n),
                    can_delete=True,
                    show_bind=True,
                    kind="avatar",
                )
                self.avatar_profile_list_layout.addWidget(row)


    def _make_profile_row(self, name: str, on_activate, on_rename,
                          on_copy, on_delete, can_delete: bool = True,
                          is_active: bool = False, is_selected: bool = False,
                          meta_text: str = "",
                          bound_avatar_id: str = "", bound_is_current: bool = False,
                          show_bind: bool = False,
                          extra_actions: Optional[list] = None,
                          kind: str = "global",
                          on_after_paste: Optional[Callable] = None) -> QWidget:
        """Build a single profile row.

        Visual states:
          * `is_selected` controls the button highlight (purple). This is what
            the user clicked most recently — i.e. their *intent*.
          * `is_active` controls the leading dot (filled green vs hollow).
            This is what's actually driving haptics right now. For the global
            section these can diverge when an avatar profile overrides.

        `extra_actions` is a list of (label, tooltip, callback) appended to
        the end of the row — used by the manager dialog for the "Bind to
        current avatar" button.
        """
        row = QWidget()
        row.setProperty("profileName", name)
        rlay = _hbox(0, 6)
        row.setLayout(rlay)

        dot = QLabel("●" if is_active else "○")
        dot.setProperty("role", "success" if is_active else "muted")
        self._repolish(dot)
        rlay.addWidget(dot)

        name_btn = QPushButton(name)
        name_btn.setMinimumHeight(34)
        name_btn.setProperty(
            "role", "profileActive" if is_selected else "profileIdle"
        )
        name_btn.clicked.connect(lambda _=False: on_activate())
        rlay.addWidget(name_btn, 1)

        if meta_text:
            note = QLabel(meta_text)
            note.setProperty("muted", "true")
            self._repolish(note)
            rlay.addWidget(note)

        # Avatar-binding label (avatar section only)
        if show_bind:
            if bound_avatar_id:
                bind_text = f"🔗 {_truncate(bound_avatar_id, 18)}"
                if bound_is_current:
                    bind_text += "  (current)"
            else:
                bind_text = "(unbound)"
            meta = QLabel(bind_text)
            meta.setProperty("role", "success" if bound_is_current else "muted")
            meta.setMinimumWidth(150)
            self._repolish(meta)
            rlay.addWidget(meta)

        def make_action(text, tooltip, cb, role="secondary", enabled=True,
                        width: int = 34, icon: Optional[QIcon] = None):
            b = QPushButton(text if icon is None else "")
            b.setFixedSize(width, 34)
            b.setProperty("role", role)
            b.setToolTip(tooltip)
            b.setEnabled(enabled)
            if icon is not None:
                b.setIcon(icon)
                b.setIconSize(QSize(18, 18))
            b.clicked.connect(lambda _=False: cb())
            return b

        rlay.addWidget(make_action("", "Rename", on_rename, icon=_icon_pencil()))

        # Middle button is context-sensitive based on clipboard state:
        #   * empty clipboard  -> "Copy" (purple-secondary, two-sheets icon)
        #   * this row is the clipboard source -> green "Copied — click to
        #     cancel" using the same two-sheets icon on a success background
        #   * a different row is the source -> "Paste here" (clipboard+arrow
        #     icon) which overwrites this row with the clipboard contents
        ctl = self.controller
        has_clip = ctl.has_clipboard()
        clip_src_name = ctl.get_clipboard_source_name() if has_clip else None
        clip_src_kind = ctl.get_clipboard_source_kind() if has_clip else None
        is_clip_source = (
            clip_src_name == name and clip_src_kind == kind
        )

        def _paste_here(_n=name, _k=kind):
            self.controller.paste_profile_into(_k, _n)
            if on_after_paste is not None:
                on_after_paste()

        def _cancel_copy():
            self.controller.clear_clipboard()
            if on_after_paste is not None:
                on_after_paste()

        if not has_clip:
            rlay.addWidget(make_action(
                "", "Copy to clipboard", on_copy, icon=_icon_copy()
            ))
        elif is_clip_source:
            # Source row: not a paste target (pasting onto itself is a no-op).
            # Show a green "Copied" badge plus a small × to cancel.
            badge = QLabel("✓ Copied")
            badge.setProperty("role", "success")
            badge.setAlignment(Qt.AlignCenter)
            badge.setFixedHeight(34)
            badge.setStyleSheet(
                f"color: {COLOR_SUCCESS}; font-weight: bold; padding: 0 6px;"
            )
            badge.setToolTip(
                "This profile is on the clipboard — click paste on another "
                "row to overwrite it, or × to cancel."
            )
            self._repolish(badge)
            rlay.addWidget(badge)
            rlay.addWidget(make_action(
                "", "Cancel copy", _cancel_copy,
                role="secondary", icon=_icon_cross(COLOR_TEXT_MUTED),
            ))
        else:
            rlay.addWidget(make_action(
                "", f"Paste over '{name}' (overwrite with clipboard)",
                _paste_here, role="confirm", icon=_icon_paste(),
            ))
        trash_color = COLOR_TEXT if can_delete else COLOR_TEXT_MUTED
        rlay.addWidget(make_action(
            "", "Delete", on_delete,
            role="danger" if can_delete else "secondary",
            enabled=can_delete,
            icon=_icon_trash(trash_color),
        ))
        for (label, tooltip, cb) in (extra_actions or []):
            rlay.addWidget(make_action(label, tooltip, cb, width=110))
        return row

    def _open_avatar_profile_manager(self):
        """Modal viewer + editor for every avatar profile, regardless of which
        avatar is currently loaded. Shows binding info and offers rename /
        copy / delete plus a 'Bind to current avatar' shortcut."""
        ctl = self.controller
        dlg = QDialog(self.window)
        dlg.setWindowTitle("Avatar Profile Manager")
        dlg.resize(720, 520)
        dlg.setModal(True)

        lay = _vbox(14, 8)
        dlg.setLayout(lay)

        title = QLabel("Avatar Profile Manager")
        title.setObjectName("sectionTitle")
        lay.addWidget(title)

        cur_id = ctl.get_current_avatar_id() or "(not detected)"
        lay.addWidget(self._muted_label(
            f"Current avatar: {cur_id} — use ↻ to rebind a profile to it."
        ))

        # Scrollable rows
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        host = QWidget()
        host_lay = _vbox(0, 6)
        host.setLayout(host_lay)
        scroll.setWidget(host)
        lay.addWidget(scroll, 1)

        # Bottom: Close button
        btn_row = QWidget()
        btn_row_lay = _hbox(0, 6)
        btn_row.setLayout(btn_row_lay)
        btn_row_lay.addStretch(1)
        close = QPushButton("Close")
        close.clicked.connect(dlg.accept)
        btn_row_lay.addWidget(close)
        lay.addWidget(btn_row)

        # The manager mirrors the Dashboard's row helper. After any edit we
        # have to rebuild both the dialog list AND the Dashboard list, so
        # wrap the build step in a closure that reuses both.
        def rebuild():
            _clear_layout(host_lay)
            active = ctl.get_active_profile_info()
            names = ctl.get_avatar_profile_names()
            current_avatar = ctl.get_current_avatar_id() or ""
            if not names:
                empty = QLabel("No avatar profiles. Close this dialog and create one from the Dashboard.")
                empty.setProperty("muted", "true")
                self._repolish(empty)
                host_lay.addWidget(empty)
                return
            for name in names:
                bound_id = ctl.get_avatar_binding(name)
                is_active = (active["kind"] == "avatar" and name == active["name"])
                # "Activating" from this dialog rebinds the profile to the
                # current avatar (the only way to make an avatar profile go
                # live without changing avatars).
                row = self._make_profile_row(
                    name=name,
                    is_selected=is_active,
                    is_active=is_active,
                    bound_avatar_id=bound_id,
                    bound_is_current=bool(bound_id and bound_id == current_avatar),
                    on_activate=lambda n=name: (
                        ctl.bind_avatar_profile_to_current(n),
                        rebuild(),
                    ),
                    on_rename=lambda n=name: self._dialog_rename_avatar(dlg, n, rebuild),
                    on_copy=lambda n=name: (
                        ctl.copy_profile("avatar", n),
                        rebuild(),
                    ),
                    on_delete=lambda n=name: self._dialog_delete_avatar(dlg, n, rebuild),
                    can_delete=True,
                    show_bind=True,
                    kind="avatar",
                    on_after_paste=rebuild,
                    extra_actions=[(
                        "↻ Bind to current",
                        "Rebind this profile to the currently-loaded avatar",
                        lambda n=name: (
                            ctl.bind_avatar_profile_to_current(n),
                            rebuild(),
                        ),
                    )] if current_avatar else [],
                )
                host_lay.addWidget(row)
            host_lay.addStretch(1)

        rebuild()
        dlg.exec()

    def _dialog_rename_avatar(self, dlg: QDialog, current_name: str, rebuild):
        """Tiny rename prompt for use inside the manager dialog. Avoids
        inline-editing inside the scroll area for simplicity."""
        from PySide6.QtWidgets import QInputDialog
        new_name, ok = QInputDialog.getText(
            dlg, "Rename Avatar Profile",
            f"New name for '{current_name}':",
            text=current_name,
        )
        if ok:
            new_name = (new_name or "").strip()
            if new_name and new_name != current_name:
                self.controller.rename_avatar_profile(current_name, new_name)
        rebuild()

    def _dialog_delete_avatar(self, dlg: QDialog, name: str, rebuild):
        box = QMessageBox(dlg)
        box.setWindowTitle("Delete Avatar Profile")
        box.setText(f"Delete avatar profile '{name}'?")
        box.setInformativeText(
            "This removes the profile's saved per-toy settings.\n"
            "Your toys themselves remain."
        )
        box.setIcon(QMessageBox.Warning)
        del_btn = box.addButton("Delete", QMessageBox.DestructiveRole)
        box.addButton("Cancel", QMessageBox.RejectRole)
        box.exec()
        if box.clickedButton() is del_btn:
            self.controller.delete_avatar_profile(name)
        rebuild()

    def _add_new_profile(self):
        name = self.controller.create_profile()
        self._refresh_profile_buttons()
        self._start_profile_rename("global", name)

    def _confirm_profile_delete(self, kind: str, name: str):
        if kind == "global" and len(self.controller.get_global_profile_names()) <= 1:
            return
        box = QMessageBox(self.window)
        kind_word = "avatar profile" if kind == "avatar" else "profile"
        box.setWindowTitle(f"Delete {kind_word.title()}")
        box.setText(f"Delete {kind_word} '{name}'?")
        box.setInformativeText(
            "This removes the profile's saved per-toy settings.\n"
            "Your toys themselves remain."
        )
        box.setIcon(QMessageBox.Warning)
        del_btn = box.addButton("Delete", QMessageBox.DestructiveRole)
        box.addButton("Cancel", QMessageBox.RejectRole)
        box.exec()
        if box.clickedButton() is del_btn:
            if kind == "avatar":
                self.controller.delete_avatar_profile(name)
            else:
                self.controller.delete_profile(name)

    def _start_profile_rename(self, kind: str, current_name: str):
        """Replace the matching row's name button with an inline QLineEdit
        plus explicit ✓ / ✗ buttons. Avoids using `editingFinished` because
        it fires on stray focus changes (including the rebuild that happens
        when a commit succeeds), which used to silently revert the rename.
        """
        if not self.controller.profile_exists(kind, current_name):
            return
        layout = (self.global_profile_list_layout if kind == "global"
                  else self.avatar_profile_list_layout)
        if layout is None:
            return

        # Find the row widget with this profile name.
        target_row = None
        for i in range(layout.count()):
            item = layout.itemAt(i)
            row = item.widget() if item else None
            if row is not None and row.property("profileName") == current_name:
                target_row = row
                break
        if target_row is None:
            return
        row_layout = target_row.layout()
        if row_layout is None:
            return

        # Rebuild the row in place: leading dot + inline editor.
        _clear_layout(row_layout)

        dot = QLabel("✎")
        dot.setProperty("role", "muted")
        self._repolish(dot)
        row_layout.addWidget(dot)

        entry = QLineEdit(current_name)
        entry.setMinimumHeight(34)
        entry.selectAll()
        row_layout.addWidget(entry, 1)

        # One-shot guard so returnPressed + button clicks can't double-commit.
        state = {"done": False}

        def commit():
            if state["done"]:
                return
            state["done"] = True
            new_name = entry.text().strip()
            if not new_name or new_name == current_name:
                # No change → just rebuild the row.
                self._refresh_profile_buttons()
                return
            if kind == "avatar":
                self.controller.rename_avatar_profile(current_name, new_name)
            else:
                self.controller.rename_profile(current_name, new_name)

        def cancel():
            if state["done"]:
                return
            state["done"] = True
            self._refresh_profile_buttons()

        entry.returnPressed.connect(commit)
        # Escape cancels. We use a key-press event filter via a small lambda
        # subclass-free hack: connect to keyPressEvent via installEventFilter
        # on a dedicated object would be overkill — instead handle Escape
        # by listening through a child shortcut on the QLineEdit.
        from PySide6.QtGui import QKeySequence, QShortcut
        esc = QShortcut(QKeySequence("Escape"), entry)
        esc.activated.connect(cancel)

        ok = QPushButton("")
        ok.setFixedSize(34, 34)
        ok.setProperty("role", "confirm")
        ok.setToolTip("Confirm")
        ok.setIcon(_icon_check(COLOR_TEXT))
        ok.setIconSize(QSize(18, 18))
        ok.clicked.connect(lambda _=False: commit())
        row_layout.addWidget(ok)

        no = QPushButton("")
        no.setFixedSize(34, 34)
        no.setProperty("role", "cancel")
        no.setToolTip("Cancel")
        no.setIcon(_icon_cross(COLOR_TEXT))
        no.setIconSize(QSize(18, 18))
        no.clicked.connect(lambda _=False: cancel())
        row_layout.addWidget(no)

        entry.setFocus()

    # ----------------------------------------------------------
    # Simple Mode view
    # ----------------------------------------------------------

    def _build_simple_mode_view(self, parent_layout: QVBoxLayout):
        title = QLabel("Simple Mode")
        title.setObjectName("viewTitle")
        title.setAlignment(Qt.AlignHCenter)
        parent_layout.addWidget(title)

        # ===== Toggle card =====
        toggle_card = _Card()
        tlay = _vbox(14, 8)
        toggle_card.setLayout(tlay)

        self.simple_mode_toggle = ToggleSwitch("Enable Simple Mode")
        f = self.simple_mode_toggle.font(); f.setBold(True); f.setPointSize(13)
        self.simple_mode_toggle.setFont(f)
        self.simple_mode_toggle.setChecked(bool(self.controller.get_simple_mode()))
        self.simple_mode_toggle.toggled.connect(self._on_simple_mode_toggled)
        tlay.addWidget(self.simple_mode_toggle)

        tlay.addWidget(self._muted_label(
            "Routes every detected SPS source to every connected toy with no "
            "per-toy configuration. Profiles are ignored while this is on."
        ))

        self.simple_mode_status_label = QLabel("")
        self.simple_mode_status_label.setProperty("muted", "true")
        tlay.addWidget(self.simple_mode_status_label)

        hint = QLabel(
            "Tip: you can always come back to Simple Mode from Settings."
        )
        hint.setProperty("muted", "true")
        hint.setWordWrap(True)
        tlay.addWidget(hint)

        parent_layout.addWidget(toggle_card)

        # ===== Sources card =====
        src_card = _Card()
        slay = _vbox(14, 6)
        src_card.setLayout(slay)

        src_header = QLabel("SPS Sources")
        f = src_header.font(); f.setBold(True); f.setPointSize(12)
        src_header.setFont(f)
        slay.addWidget(src_header)
        slay.addWidget(self._muted_label("Detected from the active VRChat avatar."))

        sources_host = QWidget()
        self.simple_mode_sources_layout = _vbox(0, 3)
        sources_host.setLayout(self.simple_mode_sources_layout)
        slay.addWidget(sources_host)

        parent_layout.addWidget(src_card)

        # ===== Toys card =====
        toys_card = _Card()
        toylay = _vbox(14, 6)
        toys_card.setLayout(toylay)

        toys_header = QLabel("Connected Toys")
        f = toys_header.font(); f.setBold(True); f.setPointSize(12)
        toys_header.setFont(f)
        toylay.addWidget(toys_header)
        toylay.addWidget(self._muted_label("Battery and test pulse for every toy in range."))

        toys_host = QWidget()
        self.simple_mode_toys_layout = _vbox(0, 4)
        toys_host.setLayout(self.simple_mode_toys_layout)
        toylay.addWidget(toys_host)

        parent_layout.addWidget(toys_card)
        parent_layout.addStretch(1)

        # Initial paint.
        self.refresh_simple_mode_view(force=True)

    def _on_simple_mode_toggled(self, checked: bool):
        if hasattr(self.controller, "set_simple_mode"):
            self.controller.set_simple_mode(bool(checked))
        # Keep the two mirror checkboxes (Simple Mode panel + Settings) in
        # sync without re-firing the handler.
        for cb in (self.simple_mode_toggle, self.simple_mode_settings_toggle):
            if cb is not None and cb.isChecked() != bool(checked):
                cb.blockSignals(True)
                cb.setChecked(bool(checked))
                cb.blockSignals(False)
        self._apply_simple_mode_visibility()
        # Jump to a view that's actually visible in the new sidebar — the
        # Simple Mode entry disappears when the user turns it off, so we
        # land them on Dashboard rather than an orphaned page.
        if bool(checked):
            self.select_view("Simple Mode")
        else:
            self.select_view("Dashboard")
        self.refresh_simple_mode_view(force=True)

    # When Simple Mode is on, hide every advanced nav button — only
    # Simple Mode, Settings and Help remain. This is the "Just Works"
    # onboarding mode where the user shouldn't be surprised by SteamVR,
    # bHaptics, the OSC inspector, etc. before they've connected a toy.
    _SIMPLE_MODE_HIDDEN_VIEWS = (
        "Dashboard", "Device Routing", "SteamVR Device Comms",
        "bHaptics", "Hardware Monitor", "OSC Inspector", "System Log",
    )

    # Sidebar entries gated by Settings → Features. A view is hidden if any
    # of its required feature flags is off. "SteamVR Device Comms" is shown
    # when either haptics OR battery is enabled — both halves live in that
    # one view.
    _FEATURE_VIEW_REQUIREMENTS = {
        "bHaptics":              ("feature_bhaptics",),
        "Hardware Monitor":      ("feature_hardware_monitor",),
        "OSC Inspector":         ("feature_osc_inspector",),
        "SteamVR Device Comms":  ("feature_steamvr_haptics", "feature_steamvr_battery"),
        # Device Routing is entirely about Intiface toy motor mapping, so hide
        # it when the user has turned Intiface off.
        "Device Routing":        ("feature_intiface",),
    }

    def _feature_allows_view(self, view_name: str) -> bool:
        reqs = self._FEATURE_VIEW_REQUIREMENTS.get(view_name)
        if not reqs:
            return True
        get = getattr(self.controller, "get_feature_enabled", None)
        if get is None:
            return True
        # SteamVR view needs either half on; other views need their single flag.
        if view_name == "SteamVR Device Comms":
            return any(bool(get(k)) for k in reqs)
        return all(bool(get(k)) for k in reqs)

    def apply_feature_visibility(self):
        """Re-evaluate sidebar visibility after a feature toggle changes."""
        # Hide the Intiface connect block when that feature is off.
        if self.intiface_sidebar_section is not None:
            get = getattr(self.controller, "get_feature_enabled", None)
            on = bool(get("feature_intiface")) if get else True
            self.intiface_sidebar_section.setVisible(on)
        self._apply_simple_mode_visibility()

    def _apply_simple_mode_visibility(self):
        on = bool(getattr(self.controller, "get_simple_mode", lambda: False)())
        for name, btn in self.nav_buttons.items():
            if name == "Simple Mode":
                # Only present in the sidebar while Simple Mode is on.
                # When off, the user re-enables it from Settings.
                btn.setVisible(on)
                continue
            # Feature-gated views disappear entirely when their toggle is off,
            # regardless of Simple Mode state.
            if not self._feature_allows_view(name):
                btn.setVisible(False)
                continue
            if name in self._SIMPLE_MODE_HIDDEN_VIEWS:
                btn.setVisible(not on)
            else:
                btn.setVisible(True)
        # If the currently-shown view just got hidden, fall back to Dashboard
        # (or Simple Mode when that's the only visible option).
        current = self.main_stack.currentWidget() if self.main_stack else None
        if current is not None:
            for name, page in self.views.items():
                if page is current and not self.nav_buttons.get(name, None) is None:
                    btn = self.nav_buttons.get(name)
                    if btn is not None and not btn.isVisible():
                        fallback = "Simple Mode" if on else "Dashboard"
                        self.select_view(fallback)
                    break

    def _make_battery_label(self, level: Optional[float]) -> QLabel:
        lbl = QLabel("")
        lbl.setMinimumWidth(60)
        self._apply_battery_text(lbl, level)
        return lbl

    def _apply_battery_text(self, lbl: QLabel, level: Optional[float]):
        if level is None:
            lbl.setText("🔋 --")
            lbl.setStyleSheet(f"color: {COLOR_TEXT_MUTED};")
            return
        try:
            pct = int(float(level) * 100)
        except (TypeError, ValueError):
            lbl.setText("🔋 --")
            lbl.setStyleSheet(f"color: {COLOR_TEXT_MUTED};")
            return
        if pct > 50:
            color = COLOR_SUCCESS
        elif pct > 20:
            color = COLOR_ALERT
        else:
            color = "#FF4444"
        lbl.setText(f"🔋 {pct}%")
        lbl.setStyleSheet(f"color: {color};")

    def refresh_simple_mode_view(self, force: bool = False):
        """Rebuild source + toy lists when the underlying data has changed.
        Called from the periodic UI tick and after key controller events."""
        if self.simple_mode_sources_layout is None or self.simple_mode_toys_layout is None:
            return
        ctl = self.controller

        # Keep both mirror toggles in sync with the persisted flag.
        desired = bool(getattr(ctl, "get_simple_mode", lambda: False)())
        for cb in (self.simple_mode_toggle, self.simple_mode_settings_toggle):
            if cb is not None and cb.isChecked() != desired:
                cb.blockSignals(True)
                cb.setChecked(desired)
                cb.blockSignals(False)

        # ---- Status line ----
        if self.simple_mode_status_label is not None:
            if ctl.get_simple_mode():
                self.simple_mode_status_label.setText(
                    "Simple Mode is ON — Device Routing profiles are bypassed."
                )
                self.simple_mode_status_label.setStyleSheet(f"color: {COLOR_SUCCESS};")
            else:
                self.simple_mode_status_label.setText(
                    "Simple Mode is OFF — normal per-profile routing is active."
                )
                self.simple_mode_status_label.setStyleSheet(f"color: {COLOR_TEXT_MUTED};")

        # ---- Sources ----
        sources = ctl.get_simple_mode_sources() if hasattr(ctl, "get_simple_mode_sources") else {}
        orifices = tuple(sources.get("Orifices", []))
        penetrators = tuple(sources.get("Penetrators", []))
        sources_key = (orifices, penetrators)
        if force or sources_key != self._simple_mode_last_sources:
            self._simple_mode_last_sources = sources_key
            _clear_layout(self.simple_mode_sources_layout)
            if not orifices and not penetrators:
                lbl = QLabel("No SPS sources detected. Load an avatar with OGB zones.")
                lbl.setProperty("muted", "true")
                self._repolish(lbl)
                self.simple_mode_sources_layout.addWidget(lbl)
            else:
                if orifices:
                    h = QLabel("Orifices")
                    fh = h.font(); fh.setBold(True); h.setFont(fh)
                    self.simple_mode_sources_layout.addWidget(h)
                    for name in orifices:
                        self.simple_mode_sources_layout.addWidget(QLabel(f"  • {name}"))
                if penetrators:
                    h = QLabel("Penetrators")
                    fh = h.font(); fh.setBold(True); h.setFont(fh)
                    self.simple_mode_sources_layout.addWidget(h)
                    for name in penetrators:
                        self.simple_mode_sources_layout.addWidget(QLabel(f"  • {name}"))

        # ---- Toys ----
        toys = ctl.get_simple_mode_toys() if hasattr(ctl, "get_simple_mode_toys") else []
        toys_key = tuple((t["name"], t.get("motor_count", 0), t.get("connected", False)) for t in toys)
        if force or toys_key != self._simple_mode_last_toys:
            self._simple_mode_last_toys = toys_key
            _clear_layout(self.simple_mode_toys_layout)
            self.simple_mode_battery_labels.clear()
            if not toys:
                lbl = QLabel("No connected toys. Open Intiface and connect a device.")
                lbl.setProperty("muted", "true")
                self._repolish(lbl)
                self.simple_mode_toys_layout.addWidget(lbl)
            else:
                for toy in toys:
                    row = QFrame()
                    row.setObjectName("chip")
                    row_lay = _hbox(8, 8)
                    row.setLayout(row_lay)

                    name_lbl = QLabel(f"✓ {toy['name']}")
                    name_lbl.setProperty("role", "success")
                    self._repolish(name_lbl)
                    row_lay.addWidget(name_lbl, 1)

                    batt = self._make_battery_label(toy.get("battery"))
                    row_lay.addWidget(batt)
                    self.simple_mode_battery_labels[toy["name"]] = batt

                    test_btn = QPushButton("Test")
                    test_btn.setFixedHeight(BTN_HEIGHT_SMALL)
                    test_btn.setProperty("role", "secondary")
                    test_btn.clicked.connect(
                        lambda _=False, n=toy["name"]: self.controller.test_toy(n)
                    )
                    row_lay.addWidget(test_btn)

                    self.simple_mode_toys_layout.addWidget(row)
        else:
            # Refresh battery text on existing labels even if the toy list itself
            # is unchanged — battery_update messages may have moved values.
            for toy in toys:
                lbl = self.simple_mode_battery_labels.get(toy["name"])
                if lbl is not None:
                    self._apply_battery_text(lbl, toy.get("battery"))

    def update_simple_mode_battery(self, device_name: str, level: float):
        """Live battery push from the controller. No-op if the label hasn't
        been built yet (the next refresh tick will pick up the value from
        the controller's cache)."""
        lbl = self.simple_mode_battery_labels.get(device_name)
        if lbl is not None:
            self._apply_battery_text(lbl, level)

    # ----------------------------------------------------------
    # Device Routing view
    # ----------------------------------------------------------

    def _build_device_routing_view(self, parent_layout: QVBoxLayout):
        title = QLabel("Device Routing")
        title.setObjectName("viewTitle")
        title.setAlignment(Qt.AlignHCenter)
        parent_layout.addWidget(title)

        self.devices_container_frame = _Card(dark_bg=True)
        container_lay = _vbox(10, 6)
        self.devices_container_frame.setLayout(container_lay)
        parent_layout.addWidget(self.devices_container_frame, 1)

        header = QLabel("Toys")
        f = header.font(); f.setBold(True); f.setPointSize(12)
        header.setFont(f)
        header.setAlignment(Qt.AlignHCenter)
        container_lay.addWidget(header)

        # Scrollable list of device cards.
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        inner = QWidget()
        self.unified_devices_layout = _vbox(4, 8)
        self.unified_devices_layout.addStretch(1)
        inner.setLayout(self.unified_devices_layout)
        scroll.setWidget(inner)
        self.unified_devices_frame = inner
        container_lay.addWidget(scroll, 1)

    # ----------------------------------------------------------
    # OSC Inspector view
    # ----------------------------------------------------------

    def _build_network_debug_view(self, parent_layout: QVBoxLayout):
        title = QLabel("OSC Inspector")
        title.setObjectName("viewTitle")
        title.setAlignment(Qt.AlignHCenter)
        parent_layout.addWidget(title)

        # --- SPS Zones ---
        sps_card = _Card()
        sps_lay = _vbox(14, 6)
        sps_card.setLayout(sps_lay)

        sps_header = QLabel("Active Avatar SPS Zones")
        sps_header.setObjectName("cardHeader")
        sps_lay.addWidget(sps_header)

        self.sps_status_label = QLabel("Waiting for VRChat...")
        self.sps_status_label.setWordWrap(True)
        sps_lay.addWidget(self.sps_status_label)
        parent_layout.addWidget(sps_card)

        # --- OSC Inspector ---
        dbg_title = QLabel("Real-Time OSC Inspector")
        dbg_title.setObjectName("sectionTitle")
        dbg_title.setAlignment(Qt.AlignHCenter)
        parent_layout.addWidget(dbg_title)

        # Container for the inspector
        inspector_card = _Card(dark_bg=True)
        inspector_lay = _vbox(10, 6)
        inspector_card.setLayout(inspector_lay)

        self.osc_search_entry = QLineEdit()
        self.osc_search_entry.setPlaceholderText(
            "Search parameters (e.g., Orifice, Touch, Float)..."
        )
        inspector_lay.addWidget(self.osc_search_entry)

        self.debugger_table = QTableWidget(0, 2)
        self.debugger_table.setHorizontalHeaderLabels(["Parameter", "Value"])
        self.debugger_table.verticalHeader().setVisible(False)
        self.debugger_table.verticalHeader().setDefaultSectionSize(18)
        self.debugger_table.setShowGrid(False)
        self.debugger_table.setAlternatingRowColors(True)
        self.debugger_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.debugger_table.setSelectionMode(QAbstractItemView.NoSelection)
        self.debugger_table.setFocusPolicy(Qt.NoFocus)
        hdr = self.debugger_table.horizontalHeader()
        hdr.setSectionResizeMode(0, QHeaderView.Interactive)
        hdr.setSectionResizeMode(1, QHeaderView.Stretch)
        hdr.setCursor(Qt.SplitHCursor)
        self.debugger_table.setColumnWidth(0, 280)
        font = QFont("Consolas")
        font.setStyleHint(QFont.Monospace)
        font.setPointSize(10)
        self.debugger_table.setFont(font)
        inspector_lay.addWidget(self.debugger_table, 1)

        parent_layout.addWidget(inspector_card, 1)

        # ----- Legacy HTML view (kept beneath the table) -----------------
        # This is the pre-overhaul rendering: a QTextEdit re-rendered with
        # setHtml() on every tick. Useful as a diagnostic — if the table
        # above stops ticking but this one does, the regression is in the
        # table update path, not in the OSC pipeline.
        legacy_title = QLabel("Real-Time OSC Inspector (Legacy HTML View)")
        legacy_title.setObjectName("sectionTitle")
        legacy_title.setAlignment(Qt.AlignHCenter)
        parent_layout.addWidget(legacy_title)

        legacy_card = _Card(dark_bg=True)
        legacy_lay = _vbox(10, 6)
        legacy_card.setLayout(legacy_lay)

        self.debugger_textbox = QTextEdit()
        self.debugger_textbox.setReadOnly(True)
        self.debugger_textbox.setLineWrapMode(QTextEdit.NoWrap)
        legacy_font = QFont("Consolas")
        legacy_font.setStyleHint(QFont.Monospace)
        legacy_font.setPointSize(10)
        self.debugger_textbox.setFont(legacy_font)
        legacy_lay.addWidget(self.debugger_textbox, 1)

        parent_layout.addWidget(legacy_card, 1)

    # ----------------------------------------------------------
    # OSC Diagnostics view
    #
    # One-stop debug page for the "VRChat says connected but no
    # parameters arrive" failure mode. Shows live packet rate, all
    # port/socket bindings, every non-VRChat OSCQuery client we've seen
    # (the prime suspect when this happens), and a scrollable feed of
    # recent OSC events from the manager's ring buffer.
    # ----------------------------------------------------------

    def _build_osc_diagnostics_view(self, parent_layout: QVBoxLayout):
        title = QLabel("OSC Diagnostics")
        title.setObjectName("viewTitle")
        title.setAlignment(Qt.AlignHCenter)
        parent_layout.addWidget(title)

        intro = QLabel(
            "Live OSC connection diagnostics. If VRChat says we're connected "
            "but parameters are not updating, this page will tell you why. "
            "The most common cause is another OSC app (VRCOSC, OscGoesBrrr, "
            "etc.) that VRChat is routing to instead — those clients show up "
            "in the 'Other OSCQuery clients seen' card below."
        )
        intro.setWordWrap(True)
        intro.setProperty("muted", True)
        parent_layout.addWidget(intro)

        # --- Top row: live status + packet counters -------------------
        top_card = _Card()
        top_lay = _vbox(14, 8)
        top_card.setLayout(top_lay)

        header = QLabel("Live status")
        header.setObjectName("cardHeader")
        top_lay.addWidget(header)

        # Big status banner: green when packets are flowing, yellow when
        # connected but silent (the failure mode), red when disconnected.
        self.diag_status_banner = QLabel("—")
        font = self.diag_status_banner.font()
        font.setPointSize(16)
        font.setBold(True)
        self.diag_status_banner.setFont(font)
        self.diag_status_banner.setAlignment(Qt.AlignHCenter)
        top_lay.addWidget(self.diag_status_banner)

        # Grid of labelled counters. Stored on `self` so the refresh tick
        # can update each one in place without rebuilding the page.
        grid = QGridLayout()
        grid.setHorizontalSpacing(20)
        grid.setVerticalSpacing(6)

        def add_row(row: int, label_text: str, attr: str) -> None:
            lbl = QLabel(label_text)
            lbl.setProperty("muted", True)
            grid.addWidget(lbl, row, 0, Qt.AlignRight)
            value = QLabel("—")
            value_font = QFont("Consolas")
            value_font.setStyleHint(QFont.Monospace)
            value.setFont(value_font)
            grid.addWidget(value, row, 1, Qt.AlignLeft)
            setattr(self, attr, value)

        add_row(0, "Connection:", "diag_connection_lbl")
        add_row(1, "Session age:", "diag_session_age_lbl")
        add_row(2, "Packets handled:", "diag_packets_lbl")
        add_row(3, "Time since last packet:", "diag_last_pkt_lbl")
        add_row(4, "Phonebook GETs received:", "diag_phonebook_lbl")
        add_row(5, "Handler exceptions:", "diag_handler_exc_lbl")
        add_row(6, "Last handler error:", "diag_last_err_lbl")
        add_row(7, "mDNS service name:", "diag_mdns_name_lbl")
        add_row(8, "mDNS re-publishes:", "diag_mdns_rereg_lbl")
        add_row(9, "HTTP raw connections:", "diag_http_raw_lbl")
        top_lay.addLayout(grid)

        # Action buttons.
        btn_row = _hbox(0, 8)
        dump_btn = QPushButton("Dump diagnostics to log")
        dump_btn.setToolTip(
            "Write the full diagnostic dict to the System Log (sidebar) "
            "and the persistent file log."
        )
        dump_btn.clicked.connect(self.controller.log_osc_diagnostics)
        btn_row.addWidget(dump_btn)

        rehandshake_btn = QPushButton("Force re-handshake")
        rehandshake_btn.setProperty("role", "secondary")
        rehandshake_btn.setToolTip(
            "Re-poll VRChat's OSCQuery endpoint and resend our handshake "
            "ping. Try this FIRST when packets stop flowing."
        )
        rehandshake_btn.clicked.connect(self.controller.force_osc_rehandshake)
        btn_row.addWidget(rehandshake_btn)

        rereg_btn = QPushButton("Re-publish mDNS")
        rereg_btn.setProperty("role", "secondary")
        rereg_btn.setToolTip(
            "Unregister our mDNS advertisement and re-advertise under a fresh "
            "unique name. Forces VRChat to treat us as a brand-new OSC client. "
            "Try this if 'Force re-handshake' doesn't help."
        )
        rereg_btn.clicked.connect(self.controller.force_osc_reregister_mdns)
        btn_row.addWidget(rereg_btn)

        open_log_btn = QPushButton("Open log folder")
        open_log_btn.setProperty("role", "secondary")
        open_log_btn.setToolTip(
            "Open %APPDATA%/OscGoesPurrr in Explorer. The persistent OSC "
            "diagnostics log lives here as osc_diagnostics.log."
        )
        open_log_btn.clicked.connect(self.controller.open_osc_log_folder)
        btn_row.addWidget(open_log_btn)

        btn_row.addStretch(1)
        top_lay.addLayout(btn_row)

        parent_layout.addWidget(top_card)

        # --- Ports + socket binding ------------------------------------
        ports_card = _Card()
        ports_lay = _vbox(14, 6)
        ports_card.setLayout(ports_lay)
        ports_header = QLabel("Ports & sockets")
        ports_header.setObjectName("cardHeader")
        ports_lay.addWidget(ports_header)

        ports_grid = QGridLayout()
        ports_grid.setHorizontalSpacing(20)
        ports_grid.setVerticalSpacing(4)

        def add_port_row(row: int, label_text: str, attr: str) -> None:
            lbl = QLabel(label_text)
            lbl.setProperty("muted", True)
            ports_grid.addWidget(lbl, row, 0, Qt.AlignRight)
            value = QLabel("—")
            value_font = QFont("Consolas")
            value_font.setStyleHint(QFont.Monospace)
            value.setFont(value_font)
            ports_grid.addWidget(value, row, 1, Qt.AlignLeft)
            setattr(self, attr, value)

        add_port_row(0, "Our UDP listen port:", "diag_our_listen_lbl")
        add_port_row(1, "Our UDP socket bound to:", "diag_udp_bound_lbl")
        add_port_row(2, "Our HTTP phonebook port:", "diag_our_http_lbl")
        add_port_row(3, "VRChat OSC port:", "diag_vrc_osc_lbl")
        add_port_row(4, "VRChat OSCQuery HTTP port:", "diag_vrc_http_lbl")
        add_port_row(5, "VRChat IP:", "diag_vrc_ip_lbl")
        ports_lay.addLayout(ports_grid)

        parent_layout.addWidget(ports_card)

        # --- Other OSCQuery clients ------------------------------------
        clients_card = _Card()
        clients_lay = _vbox(14, 6)
        clients_card.setLayout(clients_lay)
        clients_header = QLabel("Other OSCQuery clients seen")
        clients_header.setObjectName("cardHeader")
        clients_lay.addWidget(clients_header)

        clients_note = QLabel(
            "Apps that advertised themselves on mDNS. VRChat may be sending "
            "your parameters to one of these instead of us. Close them and "
            "reconnect, or use VRChat → Settings → OSC → Reset."
        )
        clients_note.setWordWrap(True)
        clients_note.setProperty("muted", True)
        clients_lay.addWidget(clients_note)

        self.diag_clients_text = QPlainTextEdit()
        self.diag_clients_text.setReadOnly(True)
        clients_font = QFont("Consolas")
        clients_font.setStyleHint(QFont.Monospace)
        clients_font.setPointSize(10)
        self.diag_clients_text.setFont(clients_font)
        self.diag_clients_text.setMaximumHeight(140)
        self.diag_clients_text.setPlainText("(none seen yet)")
        clients_lay.addWidget(self.diag_clients_text)

        parent_layout.addWidget(clients_card)

        # --- Event log -------------------------------------------------
        events_card = _Card()
        events_lay = _vbox(14, 6)
        events_card.setLayout(events_lay)
        events_header = QLabel("Recent OSC events")
        events_header.setObjectName("cardHeader")
        events_lay.addWidget(events_header)

        events_note = QLabel(
            "Last 200 OSC manager events: mDNS state changes, handshake, "
            "health-check failures, silent-connection warnings."
        )
        events_note.setWordWrap(True)
        events_note.setProperty("muted", True)
        events_lay.addWidget(events_note)

        self.diag_events_text = QPlainTextEdit()
        self.diag_events_text.setReadOnly(True)
        events_font = QFont("Consolas")
        events_font.setStyleHint(QFont.Monospace)
        events_font.setPointSize(10)
        self.diag_events_text.setFont(events_font)
        events_lay.addWidget(self.diag_events_text, 1)

        parent_layout.addWidget(events_card, 1)

        # Track how many events we last rendered so the refresh tick
        # only redraws when new ones have arrived (cheap text equality
        # check would scan the whole buffer otherwise).
        self._diag_last_event_count = 0
        self._diag_last_clients_signature = None

    def refresh_osc_diagnostics_view(self) -> None:
        """Pulled by the main UI refresh tick. Idempotent — safe to call
        even when the panel hasn't been built yet (no-op if labels missing)."""
        if not getattr(self, "diag_status_banner", None):
            return

        # Only refresh the labels when the user is actually looking at
        # the page. Saves a controller call every 100 ms otherwise.
        current = self.main_stack.currentWidget() if self.main_stack else None
        if current is not self.views.get("OSC Diagnostics"):
            return

        diag = self.controller.get_osc_diagnostics() or {}
        if not diag:
            self.diag_status_banner.setText("OSC manager not running")
            self.diag_status_banner.setStyleSheet(f"color: {COLOR_TEXT_MUTED};")
            return

        is_conn = bool(diag.get("is_connected"))
        last_age = diag.get("last_packet_age_s")
        session_age = diag.get("session_age_s")
        pkts = int(diag.get("packets_handled", 0) or 0)
        phonebook = int(diag.get("phonebook_GETs", 0) or 0)
        handler_exc = int(diag.get("handler_exceptions", 0) or 0)

        # --- Banner ---------------------------------------------------
        if not is_conn:
            self.diag_status_banner.setText("✕  DISCONNECTED")
            self.diag_status_banner.setStyleSheet(f"color: {COLOR_ALERT};")
        elif last_age is None and pkts == 0:
            self.diag_status_banner.setText("⏳  CONNECTED — waiting for first packet…")
            self.diag_status_banner.setStyleSheet(f"color: {COLOR_TEXT};")
        elif last_age is not None and last_age > 15.0:
            self.diag_status_banner.setText(
                f"⚠  CONNECTED but SILENT for {last_age:.1f}s — VRChat is not sending us packets"
            )
            self.diag_status_banner.setStyleSheet("color: #FFB73D;")
        else:
            self.diag_status_banner.setText("✓  CONNECTED — packets flowing")
            self.diag_status_banner.setStyleSheet(f"color: {COLOR_SUCCESS};")

        # --- Live counters --------------------------------------------
        self.diag_connection_lbl.setText("connected" if is_conn else "disconnected")
        self.diag_session_age_lbl.setText(
            f"{session_age:.1f} s" if session_age is not None else "—"
        )
        self.diag_packets_lbl.setText(str(pkts))
        if last_age is None:
            self.diag_last_pkt_lbl.setText("never received any")
        else:
            self.diag_last_pkt_lbl.setText(f"{last_age:.1f} s")
        self.diag_phonebook_lbl.setText(str(phonebook))
        self.diag_handler_exc_lbl.setText(str(handler_exc))
        last_err = diag.get("last_handler_error") or "(none)"
        self.diag_last_err_lbl.setText(str(last_err))
        self.diag_mdns_name_lbl.setText(str(diag.get("mdns_service_name") or "—"))
        self.diag_mdns_rereg_lbl.setText(str(diag.get("mdns_rereg_count", 0)))
        self.diag_http_raw_lbl.setText(str(diag.get("http_raw_connections", 0)))

        # --- Ports ----------------------------------------------------
        self.diag_our_listen_lbl.setText(str(diag.get("our_listen_port") or "—"))
        bound = diag.get("udp_socket_bound")
        self.diag_udp_bound_lbl.setText(
            f"{bound[0]}:{bound[1]}" if bound else "—"
        )
        self.diag_our_http_lbl.setText(str(diag.get("our_http_phonebook_port") or "—"))
        self.diag_vrc_osc_lbl.setText(str(diag.get("vrc_osc_port") or "—"))
        self.diag_vrc_http_lbl.setText(str(diag.get("vrc_http_port") or "—"))
        self.diag_vrc_ip_lbl.setText(str(diag.get("vrc_ip") or "—"))

        # --- Other clients --------------------------------------------
        clients = self.controller.get_osc_other_clients() or {}
        signature = tuple(sorted(
            (k, v.get("present"), v.get("port")) for k, v in clients.items()
        ))
        if signature != self._diag_last_clients_signature:
            self._diag_last_clients_signature = signature
            if not clients:
                self.diag_clients_text.setPlainText("(none seen yet)")
            else:
                lines = []
                for name, info in clients.items():
                    state = "ACTIVE" if info.get("present") else "gone"
                    port = info.get("port")
                    lines.append(f"[{state:>6}]  {name}  port={port}")
                self.diag_clients_text.setPlainText("\n".join(lines))

        # --- Event log ------------------------------------------------
        events = self.controller.get_osc_event_log() or []
        if len(events) != self._diag_last_event_count:
            self._diag_last_event_count = len(events)
            self.diag_events_text.setPlainText("\n".join(events))
            # Keep the view scrolled to the bottom so the newest event is
            # always visible — like a live tail.
            scrollbar = self.diag_events_text.verticalScrollBar()
            scrollbar.setValue(scrollbar.maximum())

    # ----------------------------------------------------------
    # System Log view
    # ----------------------------------------------------------

    def _build_system_log_view(self, parent_layout: QVBoxLayout):
        title = QLabel("System Log")
        title.setObjectName("viewTitle")
        title.setAlignment(Qt.AlignHCenter)
        parent_layout.addWidget(title)

        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        font = QFont("Courier New")
        font.setStyleHint(QFont.Monospace)
        font.setPointSize(10)
        self.log_text.setFont(font)
        parent_layout.addWidget(self.log_text, 1)

    # ----------------------------------------------------------
    # Settings view
    # ----------------------------------------------------------

    def _build_settings_view(self, parent_layout: QVBoxLayout):
        title = QLabel("Application Settings")
        title.setObjectName("viewTitle")
        title.setAlignment(Qt.AlignHCenter)
        parent_layout.addWidget(title)

        # ---- Simple Mode Card ----
        # Settings is the always-visible escape hatch back to Simple Mode
        # when the user has turned it off and wants the stripped UI again.
        sm_card = _Card()
        sm_lay = _vbox(20, 6)
        sm_card.setLayout(sm_lay)
        hdr = QLabel("Simple Mode")
        hdr.setObjectName("cardHeader")
        sm_lay.addWidget(hdr)
        sm_lay.addWidget(self._muted_label(
            "Hides the advanced sidebar and routes every detected SPS source "
            "to every connected toy with no per-toy configuration."
        ))
        self.simple_mode_settings_toggle = ToggleSwitch("Enable Simple Mode")
        self.simple_mode_settings_toggle.setChecked(
            bool(getattr(self.controller, "get_simple_mode", lambda: False)())
        )
        self.simple_mode_settings_toggle.toggled.connect(self._on_simple_mode_toggled)
        sm_lay.addWidget(self.simple_mode_settings_toggle)
        parent_layout.addWidget(sm_card)

        # ---- Network Bind Card ----
        net_card = _Card()
        net_lay = _vbox(20, 6)
        net_card.setLayout(net_lay)

        hdr = QLabel("OSC Network Bind")
        hdr.setObjectName("cardHeader")
        net_lay.addWidget(hdr)
        desc = QLabel("Determines how VRChat discovers this application on your local network.")
        desc.setProperty("muted", "true")
        desc.setWordWrap(True)
        net_lay.addWidget(desc)

        bind_val = bool(self.controller.get_app_setting("bind_all_interfaces", True))
        switch_row = QWidget()
        switch_lay = _hbox(0, 10)
        switch_row.setLayout(switch_lay)
        switch_lay.addWidget(self._bold_label("127.0.0.1 (Strict)"))
        self.network_bind_switch = ToggleSwitch()
        self.network_bind_switch.setProperty("role", "switch")
        self.network_bind_switch.setChecked(bind_val)
        self.network_bind_switch.toggled.connect(
            lambda v: self.controller.toggle_network_bind(bool(v))
        )
        switch_lay.addWidget(self.network_bind_switch)
        switch_lay.addWidget(self._bold_label("0.0.0.0 (Recommended)"))
        switch_lay.addStretch(1)
        net_lay.addWidget(switch_row)

        warn = QLabel("* Requires application restart to apply changes.")
        warn.setProperty("role", "alert")
        net_lay.addWidget(warn)

        parent_layout.addWidget(net_card)

        # ---- Connection Settings Card ----
        conn_card = _Card()
        conn_lay = _vbox(20, 8)
        conn_card.setLayout(conn_lay)

        hdr = QLabel("Connection Settings")
        hdr.setObjectName("cardHeader")
        conn_lay.addWidget(hdr)

        self.auto_refresh_var = ToggleSwitch("Auto Refresh Devices")
        self.auto_refresh_var.setChecked(
            bool(self.controller.get_app_setting("auto_refresh", True))
        )
        self.auto_refresh_var.toggled.connect(
            lambda _=False: self.controller.toggle_auto_refresh()
        )
        conn_lay.addWidget(self.auto_refresh_var)

        self.auto_connect_var = ToggleSwitch("Auto Connect (Intiface)")
        self.auto_connect_var.setChecked(
            bool(self.controller.get_app_setting("auto_connect", True))
        )
        self.auto_connect_var.toggled.connect(
            lambda _=False: self.controller.toggle_auto_connect()
        )
        conn_lay.addWidget(self.auto_connect_var)

        self.osc_auto_connect_var = ToggleSwitch("Auto Connect (VRChat OSC)")
        self.osc_auto_connect_var.setChecked(
            bool(self.controller.get_app_setting("auto_connect_osc", True))
        )
        self.osc_auto_connect_var.toggled.connect(
            lambda _=False: self.controller.toggle_osc_auto_connect()
        )
        conn_lay.addWidget(self.osc_auto_connect_var)

        parent_layout.addWidget(conn_card)

        # ---- Quality of Life Card ----
        ql_card = _Card()
        ql_lay = _vbox(20, 8)
        ql_card.setLayout(ql_lay)

        hdr = QLabel("Quality of Life")
        hdr.setObjectName("cardHeader")
        ql_lay.addWidget(hdr)

        hide_console = ToggleSwitch("Hide Terminal Console")
        hide_console.setProperty("role", "switch")
        hide_console.setChecked(
            bool(self.controller.get_app_setting("hide_console", True))
        )

        def on_hide_console(checked):
            self.controller.set_app_setting("hide_console", bool(checked))
            self.controller.apply_console_visibility()

        hide_console.toggled.connect(on_hide_console)
        ql_lay.addWidget(hide_console)

        tray = ToggleSwitch("Minimize to System Tray")
        tray.setProperty("role", "switch")
        tray.setChecked(
            bool(self.controller.get_app_setting("minimize_to_tray", False))
        )
        tray.toggled.connect(
            lambda checked: self.controller.set_app_setting("minimize_to_tray", bool(checked))
        )
        ql_lay.addWidget(tray)

        parent_layout.addWidget(ql_card)

        # ---- Features Card ----
        # Lets the user turn off subsystems they don't need. Disabling a
        # feature hides its sidebar entry AND stops its background thread
        # so the app doesn't pay for what it isn't using.
        feat_card = _Card()
        feat_lay = _vbox(20, 6)
        feat_card.setLayout(feat_lay)

        hdr = QLabel("Features")
        hdr.setObjectName("cardHeader")
        feat_lay.addWidget(hdr)
        feat_lay.addWidget(self._muted_label(
            "Turn off features you don't need. Disabled features hide their sidebar "
            "entry and stop their background threads to save resources."
        ))

        feature_rows = (
            ("feature_intiface",         "Intiface toy communication (Buttplug.io)"),
            ("feature_bhaptics",         "bHaptics integration"),
            ("feature_hardware_monitor", "Hardware Monitor (CPU / RAM / GPU stats)"),
            ("feature_steamvr_haptics",  "SteamVR tracker haptics"),
            ("feature_steamvr_battery",  "SteamVR battery → OSC broadcast"),
            ("feature_osc_inspector",    "OSC Inspector (debug view)"),
        )

        self.feature_toggles: Dict[str, ToggleSwitch] = {}
        for key, label in feature_rows:
            tog = ToggleSwitch(label)
            tog.setChecked(bool(self.controller.get_feature_enabled(key)))
            tog.toggled.connect(
                lambda checked, k=key: self.controller.set_feature_enabled(k, bool(checked))
            )
            feat_lay.addWidget(tog)
            self.feature_toggles[key] = tog

        parent_layout.addWidget(feat_card)

        # ---- SteamVR Card ----
        svr_card = _Card()
        svr_lay = _vbox(20, 8)
        svr_card.setLayout(svr_lay)

        hdr = QLabel("SteamVR")
        hdr.setObjectName("cardHeader")
        svr_lay.addWidget(hdr)

        svr_lay.addWidget(self._muted_label(
            "Settings for the SteamVR Device Communication bridge."
        ))

        # Auto Connect — battery broadcaster also (re)scans SteamVR each tick.
        self.steamvr_auto_connect_check_settings = ToggleSwitch("Auto Connect (SteamVR)")
        try:
            _status = self.controller.get_steamvr_status()
            initial_auto = bool(_status.get("auto_connect"))
            initial_autostart = bool(_status.get("autostart"))
        except Exception:
            initial_auto = True
            initial_autostart = False
        self.steamvr_auto_connect_check_settings.setChecked(initial_auto)
        self.steamvr_auto_connect_check_settings.toggled.connect(self._on_steamvr_auto_connect_toggled)
        svr_lay.addWidget(self.steamvr_auto_connect_check_settings)

        # Start with SteamVR — registers the OpenVR app manifest.
        self.steamvr_autostart_check_settings = ToggleSwitch("Start with SteamVR")
        self.steamvr_autostart_check_settings.setChecked(initial_autostart)
        self.steamvr_autostart_check_settings.toggled.connect(self._on_steamvr_autostart_toggled)
        svr_lay.addWidget(self.steamvr_autostart_check_settings)

        # Manual Refresh — useful when auto-connect is off.
        refresh_row = _hbox(0, 8)
        svr_refresh_btn = QPushButton("Refresh SteamVR Devices")
        svr_refresh_btn.setMinimumHeight(BTN_HEIGHT_LARGE)
        svr_refresh_btn.clicked.connect(self._on_steamvr_refresh_clicked)
        refresh_row.addWidget(svr_refresh_btn)
        refresh_row.addStretch(1)
        svr_lay.addLayout(refresh_row)

        parent_layout.addWidget(svr_card)
        parent_layout.addStretch(1)

    def _bold_label(self, text: str) -> QLabel:
        lbl = QLabel(text)
        f = lbl.font(); f.setBold(True)
        lbl.setFont(f)
        return lbl

    # ----------------------------------------------------------
    # Help view
    # ----------------------------------------------------------

    # ----------------------------------------------------------
    # SteamVR Haptics view
    # ----------------------------------------------------------

    _STEAMVR_PATTERNS = ["None", "Constant", "Linear", "Sine", "Throb"]

    def _build_steamvr_view(self, parent_layout: QVBoxLayout):
        title = QLabel("SteamVR Device Communication")
        title.setObjectName("viewTitle")
        title.setAlignment(Qt.AlignHCenter)
        parent_layout.addWidget(title)

        parent_layout.addWidget(self._muted_label(
            "Two-way bridge between VRChat OSC and your SteamVR devices.\n"
            "• Incoming: OSC addresses below trigger haptic pulses on the matching tracker.\n"
            "• Outgoing: each device's battery level is published to its configured OSC address."
        ))

        # ---- Status / actions card ----
        status_card = _Card()
        slay = _vbox(14, 8)
        status_card.setLayout(slay)

        self.steamvr_status_label = QLabel("SteamVR: Unknown")
        f = self.steamvr_status_label.font(); f.setBold(True); f.setPointSize(12)
        self.steamvr_status_label.setFont(f)
        slay.addWidget(self.steamvr_status_label)

        self.steamvr_tracker_count_label = QLabel("Trackers: —")
        slay.addWidget(self.steamvr_tracker_count_label)

        action_row = _hbox(0, 8)
        action_row.addWidget(QLabel("Battery poll (s)"))
        self.steamvr_battery_interval_spin = QSpinBox()
        self.steamvr_battery_interval_spin.setRange(1, 600)
        self.steamvr_battery_interval_spin.setValue(5)
        self.steamvr_battery_interval_spin.valueChanged.connect(self._on_steamvr_battery_interval_changed)
        action_row.addWidget(self.steamvr_battery_interval_spin)

        action_row.addStretch(1)
        slay.addLayout(action_row)
        parent_layout.addWidget(status_card)

        # ---- Pattern config card (PROXIMITY + VELOCITY) ----
        pat_card = _Card()
        plat = _vbox(14, 8)
        pat_card.setLayout(plat)
        ph = QLabel("Vibration Patterns")
        ph.setObjectName("sectionTitle")
        plat.addWidget(ph)
        plat.addWidget(self._muted_label(
            "Two patterns combine per pulse: Proximity reacts to the raw value, "
            "Velocity reacts to how fast it changes. Final strength is the max of both."
        ))
        self.steamvr_pattern_widgets = []
        for idx, name in enumerate(["Proximity", "Velocity"]):
            row, widgets = self._build_steamvr_pattern_row(name, idx)
            self.steamvr_pattern_widgets.append(widgets)
            plat.addLayout(row)
        parent_layout.addWidget(pat_card)

        # ---- Anti-stuck card (two-timer model, VRC-Haptic-Pancake parity) ----
        as_card = _Card()
        aslay = _vbox(14, 8)
        as_card.setLayout(aslay)
        as_hdr = QLabel("Anti-stuck")
        as_hdr.setObjectName("sectionTitle")
        aslay.addWidget(as_hdr)
        aslay.addWidget(self._muted_label(
            "VRChat only sends OSC on parameter change. If the sender stops "
            "(avatar swap, partner leaves), the last value would vibrate "
            "forever. The active timeout clears mid-range stuck values; the "
            "peaked timeout clears saturated (100%) values, which usually "
            "represent a legitimate hold and get a longer fuse."
        ))
        as_row = _hbox(0, 8)
        self.steamvr_antistuck_check = ToggleSwitch("Enabled")
        self.steamvr_antistuck_check.toggled.connect(self._on_steamvr_antistuck_changed)
        as_row.addWidget(self.steamvr_antistuck_check)
        as_row.addSpacing(12)

        as_row.addWidget(QLabel("Active timeout (s)"))
        self.steamvr_antistuck_active_spin = QSpinBox()
        self.steamvr_antistuck_active_spin.setRange(1, 600)
        self.steamvr_antistuck_active_spin.setValue(7)
        self.steamvr_antistuck_active_spin.valueChanged.connect(self._on_steamvr_antistuck_changed)
        as_row.addWidget(self.steamvr_antistuck_active_spin)

        as_row.addWidget(QLabel("Peaked timeout (s)"))
        self.steamvr_antistuck_peaked_spin = QSpinBox()
        self.steamvr_antistuck_peaked_spin.setRange(1, 600)
        self.steamvr_antistuck_peaked_spin.setValue(15)
        self.steamvr_antistuck_peaked_spin.valueChanged.connect(self._on_steamvr_antistuck_changed)
        as_row.addWidget(self.steamvr_antistuck_peaked_spin)
        as_row.addStretch(1)
        aslay.addLayout(as_row)
        parent_layout.addWidget(as_card)

        # ---- Tracker list card ----
        list_card = _Card(dark_bg=True)
        llay = _vbox(10, 6)
        list_card.setLayout(llay)
        lh = QLabel("Trackers")
        lh.setObjectName("sectionTitle")
        llay.addWidget(lh)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        inner = QWidget()
        self.steamvr_tracker_list_layout = _vbox(6, 8)
        inner.setLayout(self.steamvr_tracker_list_layout)
        scroll.setWidget(inner)
        llay.addWidget(scroll, 1)
        parent_layout.addWidget(list_card, 1)

        # Populate from current state and arrange periodic refresh.
        self._refresh_steamvr_view()
        QTimer.singleShot(0, self._refresh_steamvr_view)
        self._steamvr_refresh_timer = QTimer(self.window)
        self._steamvr_refresh_timer.setInterval(2000)
        self._steamvr_refresh_timer.timeout.connect(self._refresh_steamvr_status_only)
        self._steamvr_refresh_timer.start()

    def _build_steamvr_pattern_row(self, label: str, idx: int):
        row = _hbox(0, 8)
        row.addWidget(QLabel(label + ":"))
        combo = QComboBox()
        combo.addItems(self._STEAMVR_PATTERNS)
        row.addWidget(combo)

        row.addWidget(QLabel("Min %"))
        spin_min = QSpinBox(); spin_min.setRange(0, 100)
        row.addWidget(spin_min)

        row.addWidget(QLabel("Max %"))
        spin_max = QSpinBox(); spin_max.setRange(0, 100)
        row.addWidget(spin_max)

        row.addWidget(QLabel("Speed"))
        spin_speed = QSpinBox(); spin_speed.setRange(1, 64)
        row.addWidget(spin_speed)
        row.addStretch(1)

        widgets = {"combo": combo, "min": spin_min, "max": spin_max, "speed": spin_speed}

        def emit(_=None):
            if self._is_updating_steamvr:
                return
            self.controller.set_steamvr_pattern(idx, {
                "pattern": combo.currentText(),
                "str_min": spin_min.value(),
                "str_max": spin_max.value(),
                "speed": spin_speed.value(),
            })

        combo.currentTextChanged.connect(emit)
        spin_min.valueChanged.connect(emit)
        spin_max.valueChanged.connect(emit)
        spin_speed.valueChanged.connect(emit)
        return row, widgets

    _is_updating_steamvr = False

    def _on_steamvr_refresh_clicked(self):
        count = self.controller.refresh_steamvr_trackers()
        self.log_message(f"SteamVR: refreshed, found {count} tracker(s)")
        self._refresh_steamvr_view()

    def _on_steamvr_autostart_toggled(self, checked: bool):
        if self._is_updating_steamvr:
            return
        self.controller.set_steamvr_autostart(bool(checked))

    def _on_steamvr_auto_connect_toggled(self, checked: bool):
        if self._is_updating_steamvr:
            return
        self.controller.set_steamvr_auto_connect(bool(checked))
        # Reflect immediately — a successful connect populates the device list.
        self._refresh_steamvr_view()

    def _on_steamvr_battery_interval_changed(self, value: int):
        if self._is_updating_steamvr:
            return
        self.controller.set_steamvr_battery_interval(float(value))

    def _on_steamvr_antistuck_changed(self, *_):
        if self._is_updating_steamvr:
            return
        self.controller.set_steamvr_no_data(
            self.steamvr_antistuck_check.isChecked(),
            int(self.steamvr_antistuck_active_spin.value()),
            int(self.steamvr_antistuck_peaked_spin.value()),
        )

    def _refresh_steamvr_status_only(self):
        # Cheap refresh: status bar only, no list rebuild.
        try:
            status = self.controller.get_steamvr_status()
        except Exception:
            return
        self._apply_steamvr_status(status)

    def _refresh_steamvr_view(self):
        if not hasattr(self, "steamvr_tracker_list_layout"):
            return
        self._is_updating_steamvr = True
        try:
            status = self.controller.get_steamvr_status()
            self._apply_steamvr_status(status)
            self._apply_steamvr_patterns(self.controller.get_steamvr_pattern_configs())
            self._rebuild_steamvr_tracker_list(status.get("trackers", []))
        finally:
            self._is_updating_steamvr = False

    def _apply_steamvr_status(self, status: dict):
        if not status.get("available"):
            self.steamvr_status_label.setText("SteamVR: openvr binding missing — pip install openvr")
            self.steamvr_status_label.setProperty("role", "alert")
        elif not status.get("alive"):
            self.steamvr_status_label.setText("SteamVR: not running (start SteamVR and click Refresh)")
            self.steamvr_status_label.setProperty("role", "alert")
        else:
            self.steamvr_status_label.setText("SteamVR: connected")
            self.steamvr_status_label.setProperty("role", None)
        self.steamvr_status_label.style().unpolish(self.steamvr_status_label)
        self.steamvr_status_label.style().polish(self.steamvr_status_label)

        trackers = status.get("trackers", [])
        counts = {"hmd": 0, "controller": 0, "tracker": 0}
        for t in trackers:
            counts[t.get("device_class", "tracker")] = counts.get(t.get("device_class", "tracker"), 0) + 1
        self.steamvr_tracker_count_label.setText(
            f"Devices: {len(trackers)}  ·  HMD {counts.get('hmd', 0)}  ·  Controllers {counts.get('controller', 0)}  ·  Trackers {counts.get('tracker', 0)}"
        )
        if hasattr(self, "steamvr_auto_connect_check_settings"):
            self.steamvr_auto_connect_check_settings.setChecked(bool(status.get("auto_connect")))
        if hasattr(self, "steamvr_autostart_check_settings"):
            self.steamvr_autostart_check_settings.setChecked(bool(status.get("autostart")))
        try:
            self.steamvr_battery_interval_spin.setValue(int(round(float(status.get("battery_interval_s", 5)))))
        except Exception:
            pass

        nd = status.get("no_data") or {}
        if hasattr(self, "steamvr_antistuck_check") and nd:
            try:
                self.steamvr_antistuck_check.setChecked(bool(nd.get("enabled", True)))
                active = int(nd.get("timeout_active_s", 7))
                peaked = int(nd.get("timeout_peaked_s", nd.get("timeout_s", 15)))
                if self.steamvr_antistuck_active_spin.value() != active:
                    self.steamvr_antistuck_active_spin.setValue(active)
                if self.steamvr_antistuck_peaked_spin.value() != peaked:
                    self.steamvr_antistuck_peaked_spin.setValue(peaked)
            except Exception:
                pass

    def _apply_steamvr_patterns(self, patterns):
        for idx, widgets in enumerate(self.steamvr_pattern_widgets):
            if idx >= len(patterns):
                break
            p = patterns[idx]
            name = p.get("pattern", "Linear")
            if name in self._STEAMVR_PATTERNS:
                widgets["combo"].setCurrentText(name)
            widgets["min"].setValue(int(p.get("str_min", 0)))
            widgets["max"].setValue(int(p.get("str_max", 80)))
            widgets["speed"].setValue(int(p.get("speed", 4)))

    def _rebuild_steamvr_tracker_list(self, trackers: list):
        # Wipe existing rows.
        while self.steamvr_tracker_list_layout.count():
            item = self.steamvr_tracker_list_layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()

        if not trackers:
            empty = self._muted_label(
                "No devices detected. Make sure SteamVR is running and your devices are powered on, then click Refresh."
            )
            self.steamvr_tracker_list_layout.addWidget(empty)
            return

        for t in trackers:
            self.steamvr_tracker_list_layout.addWidget(self._build_steamvr_tracker_card(t))
        self.steamvr_tracker_list_layout.addStretch(1)

    _DEVICE_CLASS_LABEL = {"hmd": "HMD", "controller": "Controller", "tracker": "Tracker"}

    def _build_steamvr_tracker_card(self, t: dict) -> QFrame:
        serial = t["serial"]
        cfg = t.get("config", {})
        dev_class = t.get("device_class", "tracker")
        supports_haptics = bool(t.get("supports_haptics", True))

        card = _Card()
        lay = _vbox(12, 6)
        card.setLayout(lay)

        # Header: class tag · model · serial · battery · pulse-test
        header = _hbox(0, 8)
        class_tag = QLabel(f"[{self._DEVICE_CLASS_LABEL.get(dev_class, dev_class.title())}]")
        cf = class_tag.font(); cf.setBold(True)
        class_tag.setFont(cf)
        header.addWidget(class_tag)

        title = QLabel(f"{t.get('model', '?')}  ·  {serial}")
        tf = title.font(); tf.setBold(True); tf.setPointSize(11)
        title.setFont(tf)
        header.addWidget(title)
        header.addStretch(1)

        bat = t.get("battery")
        bat_text = "Battery: —"
        if bat is not None:
            try:
                bat_text = f"Battery: {int(float(bat) * 100)}%"
            except Exception:
                pass
        header.addWidget(QLabel(bat_text))

        if supports_haptics:
            pulse_btn = QPushButton("Pulse Test")
            pulse_btn.setMinimumHeight(BTN_HEIGHT_SMALL)
            pulse_btn.clicked.connect(lambda _=False, s=serial: self.controller.pulse_steamvr_tracker(s))
            header.addWidget(pulse_btn)
        lay.addLayout(header)

        enabled = ToggleSwitch("Enabled")
        enabled.setChecked(bool(cfg.get("enabled", True)))
        lay.addWidget(enabled)

        # ---- Outgoing: battery OSC address (all device classes) ----
        out_row = _hbox(0, 6)
        out_row.addWidget(QLabel("Outgoing battery OSC address"))
        lay.addLayout(out_row)
        battery_edit = QLineEdit()
        battery_edit.setText(str(cfg.get("battery_osc_address", "")))
        battery_edit.setPlaceholderText("/avatar/parameters/HMD_Battery  (leave blank to disable)")
        lay.addWidget(battery_edit)

        # ---- Incoming: haptic OSC addresses (skip for HMD) ----
        addr_edit = None
        mult = None
        bat_thr = None
        if supports_haptics:
            in_row = _hbox(0, 6)
            in_row.addWidget(QLabel("Incoming haptic OSC addresses (separate with ; )"))
            lay.addLayout(in_row)
            addr_edit = QLineEdit()
            addr_edit.setText(";".join(cfg.get("address_list", [])))
            addr_edit.setPlaceholderText("/avatar/parameters/MyParam;/avatar/parameters/OtherParam")
            lay.addWidget(addr_edit)

            params_row = _hbox(0, 8)
            params_row.addWidget(QLabel("Multiplier"))
            mult = QDoubleSpinBox(); mult.setRange(0.0, 100.0); mult.setSingleStep(0.1)
            mult.setValue(float(cfg.get("multiplier_override", 1.0)))
            params_row.addWidget(mult)

            params_row.addWidget(QLabel("Battery threshold %"))
            bat_thr = QSpinBox(); bat_thr.setRange(0, 100)
            bat_thr.setValue(int(cfg.get("battery_threshold", 20)))
            params_row.addWidget(bat_thr)
            params_row.addStretch(1)
            lay.addLayout(params_row)
        else:
            lay.addWidget(self._muted_label("HMDs don't support haptic pulses — battery broadcast only."))

        def push(_=None):
            if self._is_updating_steamvr:
                return
            new_cfg = dict(cfg)
            new_cfg["enabled"] = enabled.isChecked()
            new_cfg["battery_osc_address"] = battery_edit.text().strip()
            if addr_edit is not None:
                addrs = [a.strip() for a in addr_edit.text().split(";") if a.strip()]
                if not addrs:
                    addrs = ["/avatar/parameters/..."]
                new_cfg["address_list"] = addrs
            if mult is not None:
                new_cfg["multiplier_override"] = float(mult.value())
            if bat_thr is not None:
                new_cfg["battery_threshold"] = int(bat_thr.value())
            self.controller.set_steamvr_tracker_config(serial, new_cfg)

        enabled.toggled.connect(push)
        battery_edit.editingFinished.connect(push)
        if addr_edit is not None:
            addr_edit.editingFinished.connect(push)
        if mult is not None:
            mult.valueChanged.connect(push)
        if bat_thr is not None:
            bat_thr.valueChanged.connect(push)
        return card

    # ----------------------------------------------------------
    # bHaptics view
    # ----------------------------------------------------------

    _is_updating_bhaptics = False

    # Per-position dot widgets, refreshed by _refresh_bhaptics_grids.
    # `_bhaptics_grids` holds the OUTPUT grid (post anti-stuck, post override —
    # what's actually sent to the device, and what the click-to-test interacts
    # with). `_bhaptics_raw_grids` holds the RAW input mirror.
    _bhaptics_grids: Dict[str, "_BHapticsDotGrid"] = {}
    _bhaptics_raw_grids: Dict[str, "_BHapticsDotGrid"] = {}

    # Tracks the last set of detected device positions so the device list
    # only rebuilds when the avatar's bHaptics-capable set actually changes.
    _bhaptics_last_detected: Optional[frozenset] = None

    def _build_bhaptics_view(self, parent_layout: QVBoxLayout):
        title = QLabel("bHaptics")
        title.setObjectName("viewTitle")
        title.setAlignment(Qt.AlignHCenter)
        parent_layout.addWidget(title)

        parent_layout.addWidget(self._muted_label(
            "Translates v1 bHapticsOSC avatar parameters into haptic frames sent to the bHaptics Player.\n"
            "Supported naming schemes (both auto-detected, max wins per dot):\n"
            "  • bHaptics_<Device>_<Node>_bool   (HerpDerpinstine v1, bool)   — e.g. bHaptics_Vest_Front_5_bool\n"
            "  • bOSC_v1_<Position><Node>          (community v1, float 0-1)  — e.g. bOSC_v1_VestFront_5"
        ))

        # ---- Status / endpoint card ----
        status_card = _Card()
        slay = _vbox(14, 8)
        status_card.setLayout(slay)

        self.bhaptics_status_label = QLabel("bHaptics: Unknown")
        f = self.bhaptics_status_label.font(); f.setBold(True); f.setPointSize(12)
        self.bhaptics_status_label.setFont(f)
        slay.addWidget(self.bhaptics_status_label)

        action_row = _hbox(0, 8)
        self.bhaptics_auto_connect_check = ToggleSwitch("Auto Connect (bHaptics)")
        self.bhaptics_auto_connect_check.toggled.connect(self._on_bhaptics_auto_connect_toggled)
        action_row.addWidget(self.bhaptics_auto_connect_check)

        connect_btn = QPushButton("Connect Now")
        connect_btn.setMinimumHeight(BTN_HEIGHT_SMALL)
        connect_btn.clicked.connect(self._on_bhaptics_connect_clicked)
        action_row.addWidget(connect_btn)

        action_row.addSpacing(16)
        action_row.addWidget(QLabel("Host"))
        self.bhaptics_host_edit = QLineEdit()
        self.bhaptics_host_edit.setFixedWidth(120)
        action_row.addWidget(self.bhaptics_host_edit)
        action_row.addWidget(QLabel("Port"))
        self.bhaptics_port_spin = QSpinBox()
        self.bhaptics_port_spin.setRange(1, 65535)
        action_row.addWidget(self.bhaptics_port_spin)
        apply_btn = QPushButton("Apply")
        apply_btn.setMinimumHeight(BTN_HEIGHT_SMALL)
        apply_btn.clicked.connect(self._on_bhaptics_endpoint_apply)
        action_row.addWidget(apply_btn)
        action_row.addStretch(1)
        slay.addLayout(action_row)
        parent_layout.addWidget(status_card)

        # ---- Anti-stuck card ----
        as_card = _Card()
        as_lay = _vbox(14, 6)
        as_card.setLayout(as_lay)
        as_hdr = QLabel("Anti-stuck")
        as_hdr.setObjectName("sectionTitle")
        as_lay.addWidget(as_hdr)
        as_lay.addWidget(self._muted_label(
            "When a dot's value hasn't changed for the hold time, ramp it down to 0 "
            "over the ramp time. Catches contacts that latch on and never release."
        ))
        as_row = _hbox(0, 8)
        self.bhaptics_antistuck_check = ToggleSwitch("Enabled")
        self.bhaptics_antistuck_check.toggled.connect(self._on_bhaptics_antistuck_changed)
        as_row.addWidget(self.bhaptics_antistuck_check)

        as_row.addSpacing(16)
        as_row.addWidget(QLabel("Hold (s)"))
        self.bhaptics_antistuck_hold_spin = QDoubleSpinBox()
        self.bhaptics_antistuck_hold_spin.setRange(0.1, 60.0)
        self.bhaptics_antistuck_hold_spin.setSingleStep(0.5)
        self.bhaptics_antistuck_hold_spin.setDecimals(1)
        self.bhaptics_antistuck_hold_spin.valueChanged.connect(self._on_bhaptics_antistuck_changed)
        as_row.addWidget(self.bhaptics_antistuck_hold_spin)

        as_row.addSpacing(8)
        as_row.addWidget(QLabel("Ramp (s)"))
        self.bhaptics_antistuck_ramp_spin = QDoubleSpinBox()
        self.bhaptics_antistuck_ramp_spin.setRange(0.1, 60.0)
        self.bhaptics_antistuck_ramp_spin.setSingleStep(0.5)
        self.bhaptics_antistuck_ramp_spin.setDecimals(1)
        self.bhaptics_antistuck_ramp_spin.valueChanged.connect(self._on_bhaptics_antistuck_changed)
        as_row.addWidget(self.bhaptics_antistuck_ramp_spin)
        as_row.addStretch(1)
        as_lay.addLayout(as_row)
        parent_layout.addWidget(as_card)

        # ---- Per-device cards ----
        list_card = _Card(dark_bg=True)
        llay = _vbox(10, 6)
        list_card.setLayout(llay)
        lh = QLabel("Devices")
        lh.setObjectName("sectionTitle")
        llay.addWidget(lh)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        inner = QWidget()
        self.bhaptics_device_list_layout = _vbox(6, 8)
        inner.setLayout(self.bhaptics_device_list_layout)
        scroll.setWidget(inner)
        llay.addWidget(scroll, 1)
        parent_layout.addWidget(list_card, 1)

        # Populate + periodic status refresh.
        self._refresh_bhaptics_view()
        self._bhaptics_refresh_timer = QTimer(self.window)
        self._bhaptics_refresh_timer.setInterval(1500)
        self._bhaptics_refresh_timer.timeout.connect(self._refresh_bhaptics_status_only)
        self._bhaptics_refresh_timer.start()

        # Fast grid refresh so the debug dots animate in near real-time.
        self._bhaptics_grid_timer = QTimer(self.window)
        self._bhaptics_grid_timer.setInterval(100)
        self._bhaptics_grid_timer.timeout.connect(self._refresh_bhaptics_grids)
        self._bhaptics_grid_timer.start()

    def _refresh_bhaptics_grids(self):
        if not self._bhaptics_grids:
            return
        try:
            snap = self.controller.get_bhaptics_snapshot()
            raw_snap = self.controller.get_bhaptics_raw_snapshot()
        except Exception:
            return
        for pos, raw_grid in self._bhaptics_raw_grids.items():
            raw_grid.set_values(raw_snap.get(pos))
        for pos, grid in self._bhaptics_grids.items():
            grid.set_values(snap.get(pos))

    # ---- bHaptics handlers ----

    def _on_bhaptics_auto_connect_toggled(self, checked: bool):
        if self._is_updating_bhaptics:
            return
        self.controller.set_bhaptics_auto_connect(bool(checked))

    def _on_bhaptics_connect_clicked(self):
        ok = self.controller.bhaptics_connect_now()
        self.log_message("bHaptics: connected" if ok else "bHaptics: connect failed (is the Player running?)")
        self._refresh_bhaptics_view()

    def _on_bhaptics_antistuck_changed(self, *_):
        if self._is_updating_bhaptics:
            return
        self.controller.set_bhaptics_antistuck(
            self.bhaptics_antistuck_check.isChecked(),
            float(self.bhaptics_antistuck_hold_spin.value()),
            float(self.bhaptics_antistuck_ramp_spin.value()),
        )

    def _on_bhaptics_endpoint_apply(self):
        host = self.bhaptics_host_edit.text().strip() or "127.0.0.1"
        port = int(self.bhaptics_port_spin.value())
        self.controller.set_bhaptics_endpoint(host, port)
        self.log_message(f"bHaptics: endpoint set to {host}:{port}")

    def _refresh_bhaptics_status_only(self):
        try:
            status = self.controller.get_bhaptics_status()
        except Exception:
            return
        self._apply_bhaptics_status(status)
        # Rebuild the device list only when the avatar's detected device set
        # actually changes (avatar swap, freshly-loaded params). Doing this in
        # the cheap status tick keeps the page responsive to avatar changes
        # without tearing down widgets every refresh.
        detected = frozenset(d["position"] for d in status.get("devices", []) if d.get("detected"))
        if detected != self._bhaptics_last_detected:
            self._bhaptics_last_detected = detected
            self._rebuild_bhaptics_device_list(status.get("devices", []))

    def _refresh_bhaptics_view(self):
        if not hasattr(self, "bhaptics_device_list_layout"):
            return
        self._is_updating_bhaptics = True
        try:
            status = self.controller.get_bhaptics_status()
            self._apply_bhaptics_status(status)
            devices = status.get("devices", [])
            self._bhaptics_last_detected = frozenset(
                d["position"] for d in devices if d.get("detected")
            )
            self._rebuild_bhaptics_device_list(devices)
        finally:
            self._is_updating_bhaptics = False

    def _apply_bhaptics_status(self, status: dict):
        if not status.get("available"):
            self.bhaptics_status_label.setText("bHaptics: websocket-client missing — pip install websocket-client")
            self.bhaptics_status_label.setProperty("role", "alert")
        elif status.get("connected"):
            self.bhaptics_status_label.setText(f"bHaptics Player: connected ({status.get('host')}:{status.get('port')})")
            self.bhaptics_status_label.setProperty("role", None)
        else:
            err = status.get("last_error") or "Player not reachable"
            self.bhaptics_status_label.setText(f"bHaptics Player: disconnected — {err}")
            self.bhaptics_status_label.setProperty("role", "alert")
        self.bhaptics_status_label.style().unpolish(self.bhaptics_status_label)
        self.bhaptics_status_label.style().polish(self.bhaptics_status_label)

        # Endpoint widgets — only set if value differs to avoid cursor jumps.
        host = status.get("host", "127.0.0.1")
        port = int(status.get("port", 15881))
        if self.bhaptics_host_edit.text() != host:
            self.bhaptics_host_edit.setText(host)
        if self.bhaptics_port_spin.value() != port:
            self.bhaptics_port_spin.setValue(port)
        self.bhaptics_auto_connect_check.setChecked(bool(status.get("auto_connect")))

        as_cfg = status.get("antistuck") or {}
        if hasattr(self, "bhaptics_antistuck_check"):
            self.bhaptics_antistuck_check.setChecked(bool(as_cfg.get("enabled", True)))
            try:
                hold = float(as_cfg.get("hold_s", 2.0))
                if abs(self.bhaptics_antistuck_hold_spin.value() - hold) > 0.001:
                    self.bhaptics_antistuck_hold_spin.setValue(hold)
            except Exception:
                pass
            try:
                ramp = float(as_cfg.get("ramp_s", 2.0))
                if abs(self.bhaptics_antistuck_ramp_spin.value() - ramp) > 0.001:
                    self.bhaptics_antistuck_ramp_spin.setValue(ramp)
            except Exception:
                pass

    def _rebuild_bhaptics_device_list(self, devices: list):
        # Drop stale grid references — the underlying widgets are about to be
        # deleted; clearing the dict prevents the fast timer from touching
        # already-deleted Qt objects.
        self._bhaptics_grids = {}
        self._bhaptics_raw_grids = {}
        while self.bhaptics_device_list_layout.count():
            item = self.bhaptics_device_list_layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()

        # Only render cards for devices the current avatar actually wires up.
        # Detection looks for any matching v1 OSC parameter in parameter_store.
        visible = [d for d in devices if d.get("detected")]

        if not visible:
            self.bhaptics_device_list_layout.addWidget(self._muted_label(
                "No bHaptics-capable devices detected on the current avatar.\n"
                "Load an avatar that broadcasts v1 bHaptics or bOSC_v1 parameters; cards appear automatically."
            ))
            return

        for d in visible:
            # Left-align so the maxWidth-capped cards sit flush instead of
            # centering with empty space on both sides.
            self.bhaptics_device_list_layout.addWidget(
                self._build_bhaptics_device_card(d), 0, Qt.AlignLeft
            )
        self.bhaptics_device_list_layout.addStretch(1)

    def _build_bhaptics_device_card(self, d: dict) -> QFrame:
        position = d["position"]
        cfg = d.get("config", {})
        nodes = int(d.get("node_count", 0))

        card = _Card()
        # Cap card width so the device list reads as a column of compact cards
        # instead of stretching with the window. The two side-by-side dot grids
        # are the widest required element (vest = ~220 px); 480 fits them plus
        # the intensity slider with comfortable padding.
        card.setMaximumWidth(480)
        lay = _vbox(12, 6)
        card.setLayout(lay)

        header = _hbox(0, 8)
        title = QLabel(f"{d.get('display_name', position)}")
        tf = title.font(); tf.setBold(True); tf.setPointSize(11)
        title.setFont(tf)
        header.addWidget(title)
        header.addWidget(QLabel(f"({nodes} nodes)"))
        header.addStretch(1)
        lay.addLayout(header)

        enabled = ToggleSwitch("Enabled")
        enabled.setChecked(bool(cfg.get("enabled", True)))
        lay.addWidget(enabled)

        intensity_row = _hbox(0, 8)
        intensity_row.addWidget(QLabel("Intensity"))
        slider = QSlider(Qt.Horizontal)
        slider.setRange(0, 100)
        slider.setValue(int(cfg.get("intensity", 100)))
        # Cap the slider so it doesn't blow the card width up on wide windows;
        # 240 px is plenty of resolution for a 0-100 control.
        slider.setMaximumWidth(240)
        intensity_row.addWidget(slider, 1)
        intensity_label = QLabel(f"{slider.value()}%")
        intensity_label.setMinimumWidth(40)
        intensity_row.addWidget(intensity_label)
        intensity_row.addStretch(1)
        lay.addLayout(intensity_row)

        # Live debug grids: dots colored red(0)→yellow(50)→green(100), laid out
        # in the same orientation as the physical bHaptics device. Two side-by-
        # side views — left is the raw OSC input, right is the actual output
        # after anti-stuck ramping and manual overrides. Comparing them makes
        # it obvious when anti-stuck is masking a real signal or when a test
        # override is winning over OSC.
        cols, rows = d.get("grid", (nodes, 1))
        grids_row = _hbox(0, 12)

        raw_col = _vbox(0, 4)
        raw_lbl = QLabel("Raw input")
        raw_lbl.setProperty("role", "muted")
        raw_lbl.setAlignment(Qt.AlignHCenter)
        raw_col.addWidget(raw_lbl)
        raw_grid = _BHapticsDotGrid(
            node_count=nodes, cols=int(cols), rows=int(rows), interactive=False
        )
        self._bhaptics_raw_grids[position] = raw_grid
        raw_col.addWidget(raw_grid, 0, Qt.AlignHCenter)
        grids_row.addLayout(raw_col)

        out_col = _vbox(0, 4)
        out_lbl = QLabel("Output (anti-stuck applied)")
        out_lbl.setProperty("role", "muted")
        out_lbl.setAlignment(Qt.AlignHCenter)
        out_col.addWidget(out_lbl)
        grid = _BHapticsDotGrid(node_count=nodes, cols=int(cols), rows=int(rows))
        self._bhaptics_grids[position] = grid
        out_col.addWidget(grid, 0, Qt.AlignHCenter)
        grids_row.addLayout(out_col)

        lay.addLayout(grids_row)

        # Debug: click-and-hold a dot on the output grid to fire it at 100%.
        # Routed through the controller so the router can max-merge it with
        # the live OSC output. The raw grid stays non-interactive — it only
        # mirrors what's actually coming in over OSC.
        grid.dotPressed.connect(lambda idx, pos=position: self.controller.set_bhaptics_manual_dot(pos, idx, 100))
        grid.dotReleased.connect(lambda idx, pos=position: self.controller.set_bhaptics_manual_dot(pos, idx, None))

        def push(_=None):
            if self._is_updating_bhaptics:
                return
            intensity_label.setText(f"{slider.value()}%")
            self.controller.set_bhaptics_device(position, {
                "enabled": enabled.isChecked(),
                "intensity": int(slider.value()),
            })

        enabled.toggled.connect(push)
        slider.valueChanged.connect(push)
        return card

    # ----------------------------------------------------------
    # Hardware Monitor view
    # ----------------------------------------------------------

    _is_updating_hwmon = False

    # Ordered list of stats shown on the page. Each tuple is
    # (key, label, value_formatter). The same keys map to OSC addresses
    # stored in HardwareMonitorSettingsManager.
    _HWMON_STATS = (
        ("cpu_percent",   "CPU",       "percent"),
        ("ram_used_gb",   "RAM Used",  "gb"),
        ("ram_total_gb",  "RAM Total", "gb"),
        ("gpu_percent",   "GPU",       "percent"),
        ("vram_used_gb",  "VRAM Used", "gb"),
        ("vram_total_gb", "VRAM Total","gb"),
    )

    def _build_hardware_monitor_view(self, parent_layout: QVBoxLayout):
        title = QLabel("Hardware Monitor")
        title.setObjectName("viewTitle")
        title.setAlignment(Qt.AlignHCenter)
        parent_layout.addWidget(title)

        parent_layout.addWidget(self._muted_label(
            "Broadcasts your system stats (CPU, RAM, GPU, VRAM) to VRChat over OSC so an avatar "
            "can display them. Percentages are sent as 0-1 floats; memory values are sent in GB. "
            "GPU stats currently require an NVIDIA GPU (NVML)."
        ))

        # ---- Master settings card ----
        cfg_card = _Card()
        cfg_lay = _vbox(14, 8)
        cfg_card.setLayout(cfg_lay)

        cfg_hdr = QLabel("Settings")
        cfg_hdr.setObjectName("sectionTitle")
        cfg_lay.addWidget(cfg_hdr)

        row1 = _hbox(0, 12)
        self.hwmon_enabled_check = ToggleSwitch("Enabled")
        self.hwmon_enabled_check.toggled.connect(self._on_hwmon_enabled_toggled)
        row1.addWidget(self.hwmon_enabled_check)

        self.hwmon_send_osc_check = ToggleSwitch("Send to VRChat (OSC)")
        self.hwmon_send_osc_check.toggled.connect(self._on_hwmon_send_osc_toggled)
        row1.addWidget(self.hwmon_send_osc_check)

        self.hwmon_gpu_enabled_check = ToggleSwitch("Read GPU (NVIDIA NVML)")
        self.hwmon_gpu_enabled_check.toggled.connect(self._on_hwmon_gpu_toggled)
        row1.addWidget(self.hwmon_gpu_enabled_check)

        row1.addStretch(1)
        cfg_lay.addLayout(row1)

        row2 = _hbox(0, 8)
        row2.addWidget(QLabel("Poll rate (s)"))
        self.hwmon_poll_rate_spin = QDoubleSpinBox()
        self.hwmon_poll_rate_spin.setRange(0.25, 60.0)
        self.hwmon_poll_rate_spin.setSingleStep(0.25)
        self.hwmon_poll_rate_spin.setDecimals(2)
        self.hwmon_poll_rate_spin.valueChanged.connect(self._on_hwmon_poll_rate_changed)
        row2.addWidget(self.hwmon_poll_rate_spin)

        row2.addSpacing(20)
        self.hwmon_status_label = QLabel("")
        self.hwmon_status_label.setStyleSheet(f"color: {COLOR_TEXT_MUTED};")
        row2.addWidget(self.hwmon_status_label)
        row2.addStretch(1)
        cfg_lay.addLayout(row2)

        parent_layout.addWidget(cfg_card)

        # ---- Live stats card ----
        stats_card = _Card()
        stats_lay = _vbox(14, 8)
        stats_card.setLayout(stats_lay)

        stats_hdr = QLabel("Live Stats")
        stats_hdr.setObjectName("sectionTitle")
        stats_lay.addWidget(stats_hdr)

        self.hwmon_gpu_name_label = QLabel("GPU: --")
        self.hwmon_gpu_name_label.setStyleSheet(f"color: {COLOR_TEXT_MUTED};")
        stats_lay.addWidget(self.hwmon_gpu_name_label)

        # Each stat gets a row with: name, value, progress bar (for %).
        grid = QGridLayout()
        grid.setHorizontalSpacing(14)
        grid.setVerticalSpacing(8)
        self.hwmon_value_labels: Dict[str, QLabel] = {}
        self.hwmon_progress_bars: Dict[str, QProgressBar] = {}
        for r, (key, label, kind) in enumerate(self._HWMON_STATS):
            name_lbl = QLabel(label)
            f = name_lbl.font(); f.setBold(True); name_lbl.setFont(f)
            grid.addWidget(name_lbl, r, 0)

            value_lbl = QLabel("--")
            value_lbl.setMinimumWidth(140)
            grid.addWidget(value_lbl, r, 1)
            self.hwmon_value_labels[key] = value_lbl

            if kind == "percent":
                pb = QProgressBar()
                pb.setRange(0, 100)
                pb.setValue(0)
                pb.setFixedHeight(14)
                grid.addWidget(pb, r, 2)
                self.hwmon_progress_bars[key] = pb
            else:
                # Spacer so the column lines up with the percent bars.
                grid.addWidget(QLabel(""), r, 2)

        stats_lay.addLayout(grid)
        parent_layout.addWidget(stats_card)

        # ---- OSC addresses card ----
        addr_card = _Card()
        addr_lay = _vbox(14, 6)
        addr_card.setLayout(addr_lay)

        addr_hdr = QLabel("OSC Output")
        addr_hdr.setObjectName("sectionTitle")
        addr_lay.addWidget(addr_hdr)

        addr_lay.addWidget(self._muted_label(
            "Set the avatar parameter name each stat is written to. Percent stats are normalised "
            "to 0-1; memory stats are sent in GB as floats. Untick a row to skip sending that stat."
        ))

        addr_grid = QGridLayout()
        addr_grid.setHorizontalSpacing(10)
        addr_grid.setVerticalSpacing(6)
        addr_grid.addWidget(QLabel("Stat"), 0, 0)
        addr_grid.addWidget(QLabel("Send"), 0, 1)
        addr_grid.addWidget(QLabel("Parameter Name"), 0, 2)
        addr_grid.addWidget(QLabel("Type"), 0, 3)
        addr_grid.addWidget(QLabel("Last Sent Value"), 0, 4)

        self.hwmon_addr_edits: Dict[str, QLineEdit] = {}
        self.hwmon_send_checks: Dict[str, QCheckBox] = {}
        self.hwmon_last_sent_labels: Dict[str, QLabel] = {}
        for r, (key, label, _kind) in enumerate(self._HWMON_STATS, start=1):
            addr_grid.addWidget(QLabel(label), r, 0)

            chk = QCheckBox()
            chk.toggled.connect(
                lambda checked, k=key: self._on_hwmon_send_toggle_changed(k, checked)
            )
            addr_grid.addWidget(chk, r, 1)
            self.hwmon_send_checks[key] = chk

            edit = QLineEdit()
            edit.editingFinished.connect(
                lambda k=key: self._on_hwmon_address_changed(k)
            )
            addr_grid.addWidget(edit, r, 2)
            self.hwmon_addr_edits[key] = edit

            # Type column — every stat is transmitted as a float.
            type_lbl = QLabel("float")
            type_lbl.setProperty("muted", "true")
            type_lbl.setAlignment(Qt.AlignCenter)
            addr_grid.addWidget(type_lbl, r, 3)

            # Last Sent Value column — updated on each refresh tick.
            sent_lbl = QLabel("--")
            sent_lbl.setAlignment(Qt.AlignCenter)
            sent_font = QFont("Consolas")
            sent_font.setStyleHint(QFont.Monospace)
            sent_lbl.setFont(sent_font)
            addr_grid.addWidget(sent_lbl, r, 4)
            self.hwmon_last_sent_labels[key] = sent_lbl

        addr_grid.setColumnStretch(2, 1)
        addr_lay.addLayout(addr_grid)
        parent_layout.addWidget(addr_card)

        parent_layout.addStretch(1)

        # Initial population + periodic refresh.
        self._refresh_hardware_monitor_view(full=True)
        self._hwmon_refresh_timer = QTimer(self.window)
        self._hwmon_refresh_timer.setInterval(500)
        self._hwmon_refresh_timer.timeout.connect(
            lambda: self._refresh_hardware_monitor_view(full=False)
        )
        self._hwmon_refresh_timer.start()

    # ---- Hardware monitor handlers ----

    def _on_hwmon_enabled_toggled(self, checked: bool):
        if self._is_updating_hwmon:
            return
        self.controller.set_hardware_monitor_enabled(bool(checked))

    def _on_hwmon_send_osc_toggled(self, checked: bool):
        if self._is_updating_hwmon:
            return
        self.controller.set_hardware_monitor_send_osc(bool(checked))

    def _on_hwmon_gpu_toggled(self, checked: bool):
        if self._is_updating_hwmon:
            return
        self.controller.set_hardware_monitor_gpu_enabled(bool(checked))

    def _on_hwmon_poll_rate_changed(self, value: float):
        if self._is_updating_hwmon:
            return
        self.controller.set_hardware_monitor_poll_rate(float(value))

    def _on_hwmon_send_toggle_changed(self, key: str, checked: bool):
        if self._is_updating_hwmon:
            return
        self.controller.set_hardware_monitor_send_toggle(key, bool(checked))

    def _on_hwmon_address_changed(self, key: str):
        if self._is_updating_hwmon:
            return
        edit = self.hwmon_addr_edits.get(key)
        if edit is None:
            return
        self.controller.set_hardware_monitor_address(key, edit.text().strip())

    def _refresh_hardware_monitor_view(self, full: bool = False):
        if not hasattr(self, "hwmon_value_labels"):
            return
        try:
            status = self.controller.get_hardware_monitor_status()
        except Exception:
            return
        stats = status.get("stats", {}) or {}
        settings = status.get("settings", {}) or {}

        # Live values + last-sent OSC payload
        last_sent = stats.get("last_sent_values", {}) or {}
        for key, _label, kind in self._HWMON_STATS:
            val = stats.get(key)
            lbl = self.hwmon_value_labels.get(key)
            if lbl is not None:
                if val is None:
                    lbl.setText("--")
                elif kind == "percent":
                    lbl.setText(f"{float(val):.1f} %")
                else:
                    lbl.setText(f"{float(val):.2f} GB")
            pb = self.hwmon_progress_bars.get(key)
            if pb is not None:
                try:
                    pb.setValue(max(0, min(100, int(round(float(val or 0))))))
                except (TypeError, ValueError):
                    pb.setValue(0)
            # Last Sent Value column — shows the actual OSC payload.
            sent_lbl = self.hwmon_last_sent_labels.get(key)
            if sent_lbl is not None:
                sent_val = last_sent.get(key)
                if sent_val is None:
                    sent_lbl.setText("--")
                else:
                    sent_lbl.setText(f"{float(sent_val):.4f}")

        # GPU name / status footer
        gpu_name = stats.get("gpu_name")
        backend = stats.get("gpu_backend", "none")
        if backend == "nvml" and gpu_name:
            self.hwmon_gpu_name_label.setText(f"GPU: {gpu_name} (NVML)")
            self.hwmon_gpu_name_label.setStyleSheet(f"color: {COLOR_SUCCESS};")
        elif not stats.get("has_nvml", False):
            self.hwmon_gpu_name_label.setText(
                "GPU: NVML not available (pip install nvidia-ml-py for NVIDIA GPUs)"
            )
            self.hwmon_gpu_name_label.setStyleSheet(f"color: {COLOR_TEXT_MUTED};")
        else:
            self.hwmon_gpu_name_label.setText("GPU: --")
            self.hwmon_gpu_name_label.setStyleSheet(f"color: {COLOR_TEXT_MUTED};")

        # Status line
        if not stats.get("has_psutil", True):
            self.hwmon_status_label.setText("psutil not installed — CPU/RAM unavailable")
            self.hwmon_status_label.setStyleSheet(f"color: {COLOR_ALERT};")
        elif stats.get("error"):
            self.hwmon_status_label.setText(f"Last error: {stats['error']}")
            self.hwmon_status_label.setStyleSheet(f"color: {COLOR_ALERT};")
        else:
            self.hwmon_status_label.setText("OK")
            self.hwmon_status_label.setStyleSheet(f"color: {COLOR_SUCCESS};")

        # Sync settings widgets (only on full refresh to avoid stomping
        # in-flight user edits to text fields).
        if full:
            self._is_updating_hwmon = True
            try:
                self.hwmon_enabled_check.setChecked(bool(settings.get("enabled", False)))
                self.hwmon_send_osc_check.setChecked(bool(settings.get("send_osc", True)))
                self.hwmon_gpu_enabled_check.setChecked(bool(settings.get("gpu_enabled", True)))
                self.hwmon_poll_rate_spin.setValue(float(settings.get("poll_rate_s", 2.0)))

                addresses = settings.get("addresses", {}) or {}
                toggles = settings.get("send_toggles", {}) or {}
                for key, _label, _kind in self._HWMON_STATS:
                    edit = self.hwmon_addr_edits.get(key)
                    if edit is not None and not edit.hasFocus():
                        edit.setText(str(addresses.get(key, "")))
                    chk = self.hwmon_send_checks.get(key)
                    if chk is not None:
                        chk.setChecked(bool(toggles.get(key, True)))
            finally:
                self._is_updating_hwmon = False

    def _build_help_view(self, parent_layout: QVBoxLayout):
        title = QLabel("Help & How It Works")
        title.setObjectName("viewTitle")
        title.setAlignment(Qt.AlignHCenter)
        parent_layout.addWidget(title)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        inner = QWidget()
        inner_lay = _vbox(0, 10)
        inner.setLayout(inner_lay)
        scroll.setWidget(inner)
        parent_layout.addWidget(scroll, 1)

        def section(heading: str, body: str):
            card = _Card()
            lay = _vbox(15, 6)
            card.setLayout(lay)
            h = QLabel(heading)
            h.setObjectName("sectionTitle")
            lay.addWidget(h)
            b = QLabel(body.strip())
            b.setWordWrap(True)
            lay.addWidget(b)
            inner_lay.addWidget(card)

        section("Overview — what this app does", """
OscGoesPurrr listens to VRChat OSC parameters once, then fans them out to four independent output pipelines:

  • Device Routing — Bluetooth toys via Intiface / Buttplug.io
  • SteamVR Device Communication — haptic pulses on Vive / Tundra trackers and Index controllers, plus outgoing battery OSC
  • bHaptics — vest / arms / head / hands / feet via the bHaptics Player
  • OSC Inspector — live read-out of every parameter your avatar broadcasts

Each section is self-contained: a failure in one (e.g. bHaptics Player not running) never affects the others.
""")

        section("Profiles — what they are", """
A profile is a complete bundle of toy settings, selectable on the Dashboard. The currently-selected profile is the one the haptic engine uses for routing OSC parameters to motor outputs.

  • Click a profile tile to switch to it.
  • Click the pencil (✎) to rename it.
  • Click the trash (🗑) to delete it (disabled when only one profile remains).
  • Click "+ New Profile" to add another. There is no fixed cap.

Profiles only affect the Device Routing (Buttplug) pipeline. SteamVR and bHaptics settings are global — they're about hardware, not avatars.
""")

        section("What is saved per profile vs. globally", """
Per profile (each profile keeps its own copy):
  • SPS zones selected for each motor (Pussy, Ass, Dick, etc., or "All SPS")
  • Custom OSC parameter addresses mapped to each motor
  • Interaction filters: Touch, Penetration, Self, Others
  • Linear-actuator mode (Position / Speed) and idle behaviour (Hold / Rest)

Global (shared by all profiles):
  • The list of known toys (every toy you've ever connected). New or empty profiles automatically inherit this list with default settings.
  • App settings: OSC network bind, auto-connect, auto-refresh, minimize-to-tray, hide-console, etc.
  • SteamVR tracker config, vibration patterns, autostart, battery-poll interval
  • bHaptics endpoint, per-device enable + intensity, anti-stuck timings
""")

        section("Switching profiles", """
Switching profiles instantly swaps the active routing rules. Every motor re-evaluates against the new profile's zones, filters and custom OSC addresses. The set of toys you see does not change — only their settings do.
""")

        section("Deleting a toy", """
The red "Delete" button on a toy card forgets that toy entirely — it is removed from every profile and from the global known-toys list. To use the toy again, simply reconnect it; it will be re-registered automatically.
""")

        section("Custom OSC addresses on a motor", """
Under each motor, the "+ Add Variable" button lets you map any number of OSC parameters to that motor. The motor's output is the maximum of all mapped parameters' normalized values (plus any contribution from selected SPS zones).

The picker shows live avatar parameters captured by the OSC inspector. Double-click a row to add it, or use the manual entry field. The × on each chip removes that mapping for the current profile only.
""")

        section("SteamVR Device Communication", """
A two-way bridge between VRChat OSC and your SteamVR devices.

Incoming (haptic pulses):
  • Each tracker has its own list of OSC addresses (semicolon-separated). When any of them goes above zero, the tracker vibrates.
  • Multiplier scales the per-tracker output. Pattern (None / Constant / Linear / Sine / Throb) shapes how the raw value drives the motor.
  • Two patterns combine per pulse: Proximity reacts to the raw value, Velocity reacts to how fast it changes. Final strength is the max of both.
  • Battery threshold silences a tracker once its battery drops below the given percent.
  • Tundra trackers use a microsecond-based pulse API with a ~4ms ceiling — the engine handles the workaround automatically.

Outgoing (battery OSC, VoltOSC-style):
  • Each device (HMD, controllers, trackers) has an "Outgoing battery OSC address" field. Leave blank to disable.
  • The configured battery-poll interval (default 5s) controls how often the value is sent.

Settings (Settings tab → SteamVR card):
  • Auto Connect (SteamVR): when on, the app keeps trying to reach SteamVR and picks up newly-connected devices automatically.
  • Start with SteamVR: registers an OpenVR app manifest so SteamVR auto-launches OscGoesPurrr.
  • Refresh SteamVR Devices: manual rescan, useful when auto-connect is off.

Filtered out: Standable virtual trackers (serials/models containing stndbl / STBL_) are skipped — they pollute the list without ever being haptic-capable. Base stations are also hidden.
""")

        section("bHaptics", """
Translates v1-style bHaptics OSC parameters from your avatar into haptic frames sent to the bHaptics Player over WebSocket (ws://127.0.0.1:15881/v2/feedbacks by default).

Supported OSC schemas (both auto-detected per node, max wins):
  • bHaptics_<Device>_<Node>_bool — HerpDerpinstine v1.0 bool form (e.g. bHaptics_Vest_Front_5_bool)
  • bOSC_v1_<Position>_<Node>     — community float form (e.g. bOSC_v1_VestFront_5, value 0.0-1.0)

Bool-schema dots fire at the per-device intensity setting; float-schema dots scale the intensity by the parameter value. The two combine per dot, so an avatar that mixes both schemas still works.

Live debug grid:
  • Each device card shows a grid of dots in the same physical layout as the bHaptics device.
  • Colors: red (off) → yellow (50%) → green (100%). Refreshes ~10 Hz.
  • Useful for confirming the right dots fire when you trigger contact zones in-world.

Anti-stuck ramp-down:
  • When a dot's value doesn't change for the configured "idle timeout" (default 2 s), it ramps down to zero over the configured "ramp duration" (default 2 s).
  • Prevents a stuck-on dot if VRChat or the sending app crashes mid-pulse.
  • Both numbers are editable in the bHaptics view header.

Auto-detection:
  • Only devices the loaded avatar actually broadcasts parameters for show up. Swap avatars and the card list updates within ~1.5 s.

Endpoint:
  • Host / Port are editable. "Apply" reconnects with the new endpoint. "Connect Now" forces a single connection attempt regardless of the auto-connect setting.
""")

        section("Real-Time OSC Inspector", """
OSC Inspector shows every OSC parameter your avatar is broadcasting. It starts automatically when you open the page and stops when you leave — useful for finding the exact name of a parameter before mapping it to a motor / tracker / bHaptics zone.

Two views are stacked:
  • Top: the in-place QTableWidget (preserves scroll position across refreshes).
  • Bottom: a legacy HTML view kept as a diagnostic — if the top freezes but the bottom ticks, the bug is in the table update path; if both freeze, the OSC pipeline upstream is the suspect.

Both consume the same data, so they stay in lockstep.
""")

        section("Where settings live on disk", """
%APPDATA%\\OscGoesPurrr\\
  • profiles.json            — per-profile device settings
  • known_devices.json       — global toy list (name, motor count, motor kinds)
  • app_settings.json        — global app preferences
  • steamvr_settings.json    — autostart, patterns, per-tracker config, battery interval
  • bhaptics_settings.json   — Player endpoint, per-device enable + intensity, anti-stuck
""")

        inner_lay.addStretch(1)

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
            if connected:
                self.status_label.setText("Status: Connected to Intiface")
                self.status_label.setProperty("role", "success")
            else:
                self.status_label.setText("Status: Disconnected")
                self.status_label.setProperty("role", "alert")
            self._repolish(self.status_label)

        self.update_stored_devices_ui()

    def update_osc_status(self, is_connected: bool, port: int = None):
        if self.osc_status_label is None:
            return
        if is_connected:
            self.osc_status_label.setText("Status: Connected to VRChat")
            self.osc_status_label.setProperty("role", "success")
            if port and self.osc_port_label is not None:
                self.osc_port_label.setText(f"Listening on Port: {port}")
            if self.osc_connection_button is not None:
                self.osc_connection_button.setText("Disconnect VRChat")
                self.osc_connection_button.setProperty("role", "danger")
                self._repolish(self.osc_connection_button)
        else:
            self.osc_status_label.setText("Status: Waiting for VRChat...")
            self.osc_status_label.setProperty("role", "alert")
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

    # ----------------------------------------------------------
    # Stored devices status
    # ----------------------------------------------------------

    def update_stored_devices_ui(self):
        connected_names = self.controller.get_connected_device_names()
        for device_name, frame_data in self.stored_device_frames.items():
            status_label: Optional[QLabel] = frame_data.get("status_label")
            delete_button: Optional[QPushButton] = frame_data.get("delete_button")
            if status_label is None or delete_button is None:
                continue
            if device_name in connected_names:
                status_label.setText(f"✓ {device_name}")
                status_label.setProperty("role", "success")
            else:
                status_label.setText(f"⚠ {device_name}")
                status_label.setProperty("role", "alert")
                battery_label = self.device_ui_frames.get(device_name, {}).get("battery_label")
                if battery_label is not None:
                    battery_label.setText("")
            delete_button.setEnabled(True)
            delete_button.setProperty("role", "danger")
            self._repolish(status_label)
            self._repolish(delete_button)
        self._reorder_device_frames()

    def update_battery_label(self, device_name: str, level: float):
        if device_name not in self.device_ui_frames:
            return
        battery_label: Optional[QLabel] = self.device_ui_frames[device_name].get("battery_label")
        if battery_label is None:
            return
        pct = int(level * 100)
        if pct > 50:
            color = COLOR_SUCCESS
        elif pct > 20:
            color = COLOR_ALERT
        else:
            color = "#FF4444"
        battery_label.setText(f"🔋 {pct}%")
        battery_label.setStyleSheet(f"color: {color};")

    # ----------------------------------------------------------
    # Device card construction
    # ----------------------------------------------------------

    def _create_device_frame(self, device_name: str, is_connected: bool,
                             osc_addresses: dict, motor_count: int,
                             motor_kinds: Optional[List[str]] = None) -> dict:
        """Create a card for a single device. Returns a dict with widget refs."""

        card = QFrame()
        card.setObjectName("card")
        card_lay = _vbox(8, 6)
        card.setLayout(card_lay)

        # Header row
        header = QWidget()
        header_lay = _hbox(0, 8)
        header.setLayout(header_lay)

        icon_button = QToolButton()
        icon_button.setObjectName("lovenseIcon")
        icon_button.setAutoRaise(True)
        icon_button.setIconSize(QSize(32, 32))
        icon_button.setFixedSize(QSize(38, 38))
        icon_button.setCursor(Qt.PointingHandCursor)
        icon_button.clicked.connect(
            lambda _=False, n=device_name, b=icon_button: self._on_lovense_icon_clicked(n, b)
        )
        self._apply_lovense_icon(device_name, icon_button)
        header_lay.addWidget(icon_button)

        status_icon = "✓" if is_connected else "⚠"
        name_label = QLabel(f"{status_icon} {device_name}")
        name_label.setObjectName("deviceName")
        name_label.setProperty("role", "success" if is_connected else "alert")
        self._repolish(name_label)
        header_lay.addWidget(name_label)

        battery_label = QLabel("")
        battery_label.setMinimumWidth(65)
        header_lay.addWidget(battery_label)
        header_lay.addStretch(1)

        delete_button = QPushButton("Delete")
        delete_button.setFixedHeight(BTN_HEIGHT_SMALL)
        delete_button.setProperty("role", "danger")
        delete_button.clicked.connect(
            lambda _=False, n=device_name: self.controller.delete_stored_device(n)
        )
        header_lay.addWidget(delete_button)
        card_lay.addWidget(header)

        # ---- Per-motor blocks ----
        motor_vars = []
        for motor_idx in range(motor_count):
            motor_frame = QFrame()
            motor_frame.setObjectName("motorBlock")
            mlay = _vbox(10, 6)
            motor_frame.setLayout(mlay)

            # Row: motor label + zone selector
            top_row = QWidget()
            top_lay = _hbox(0, 8)
            top_row.setLayout(top_lay)

            motor_label = QLabel(f"Motor {motor_idx}:")
            motor_label.setObjectName("motorLabel")
            top_lay.addWidget(motor_label)

            legacy_zone = self.controller.get_profile_config(
                device_name, f"motor_{motor_idx}_zone", "All SPS"
            )
            current_zones = self.controller.get_profile_config(
                device_name, f"motor_{motor_idx}_zones", legacy_zone or "All SPS"
            )

            zones_state = {"value": current_zones, "expanded": False}

            def zone_btn_text(value: str) -> str:
                parts = [z.strip() for z in value.split(",") if z.strip() and z.strip() != "None"]
                all_sps = "All SPS" in parts
                count = len([z for z in parts if z != "All SPS"])
                if all_sps and count:
                    return f"Select Zones (All SPS · {count} saved)"
                if all_sps:
                    return "Select Zones (All SPS)"
                if count:
                    return f"Select Zones ({count} enabled)"
                return "Select Zones..."

            zone_btn = QPushButton(zone_btn_text(zones_state["value"]))
            zone_btn.setProperty("role", "secondary")
            top_lay.addWidget(zone_btn, 1)
            mlay.addWidget(top_row)

            zone_panel = QFrame()
            zone_panel.setObjectName("zonePanel")
            zone_panel_lay = _vbox(8, 4)
            zone_panel.setLayout(zone_panel_lay)
            zone_panel.setVisible(False)
            mlay.addWidget(zone_panel)

            def build_zone_panel(dn=device_name, midx=motor_idx, state=zones_state,
                                 btn=zone_btn, panel=zone_panel, panel_lay=zone_panel_lay):
                _clear_layout(panel_lay)

                fresh_zones = []
                detected = self.controller.get_detected_zones()
                fresh_zones.extend(detected.get("Orifices", []))
                fresh_zones.extend(detected.get("Penetrators", []))

                if not fresh_zones:
                    lbl = QLabel(
                        "No zones detected yet.\n"
                        "Make sure VRChat is running and avatar loaded."
                    )
                    lbl.setProperty("role", "alert")
                    panel_lay.addWidget(lbl)
                    return

                current_selected = [z.strip() for z in state["value"].split(",") if z.strip()]

                def persist(new_val: str):
                    state["value"] = new_val
                    self.controller.update_device_config(dn, f"motor_{midx}_zones", new_val)
                    self.controller.save_profiles()
                    if hasattr(self.controller, 'force_recalculate'):
                        self.controller.force_recalculate()
                    btn.setText(zone_btn_text(new_val) + (" ▲" if state["expanded"] else ""))

                # All SPS is an additive override — toggling it on/off never
                # touches the individual zone selections, so the user can
                # temporarily switch to match-any and return to their saved set.
                all_sps_cb = ToggleSwitch("All SPS (match any zone — overrides selections below)")
                all_sps_cb.setChecked("All SPS" in current_selected)

                def on_all_sps(checked):
                    sel = [z.strip() for z in state["value"].split(",") if z.strip()]
                    sel = [z for z in sel if z != "All SPS"]
                    if checked:
                        sel.insert(0, "All SPS")
                    persist(", ".join(sel))

                all_sps_cb.toggled.connect(on_all_sps)
                panel_lay.addWidget(all_sps_cb)

                sep_lbl = QLabel("─── Detected Zones ───")
                sep_lbl.setProperty("muted", "true")
                sep_lbl.setAlignment(Qt.AlignHCenter)
                self._repolish(sep_lbl)
                panel_lay.addWidget(sep_lbl)

                def make_toggle(zone):
                    def _toggle(checked):
                        sel = [z.strip() for z in state["value"].split(",") if z.strip()]
                        if checked:
                            if zone not in sel and zone != "None":
                                sel.append(zone)
                        else:
                            if zone in sel:
                                sel.remove(zone)
                        persist(", ".join(sel))
                    return _toggle

                for zone in fresh_zones:
                    if zone == "None":
                        continue
                    cb = ToggleSwitch(zone)
                    cb.setChecked(zone in current_selected)
                    cb.toggled.connect(make_toggle(zone))
                    panel_lay.addWidget(cb)

            def toggle_zone_panel(state=zones_state, btn=zone_btn, panel=zone_panel,
                                  build=build_zone_panel):
                state["expanded"] = not state["expanded"]
                if state["expanded"]:
                    build()
                    panel.setVisible(True)
                    btn.setText(zone_btn_text(state["value"]) + " ▲")
                else:
                    panel.setVisible(False)
                    btn.setText(zone_btn_text(state["value"]))

            # Bind `toggle_zone_panel` via a default arg so each button keeps
            # its own iteration's closure. Without this, every motor's button
            # resolved the name `toggle_zone_panel` at click time and got the
            # LAST iteration's version — so clicking motor 0's "Select Zones"
            # expanded motor 1's panel and motor 0 was unreachable.
            zone_btn.clicked.connect(
                lambda _=False, tog=toggle_zone_panel: tog()
            )

            # Interaction filter checkboxes
            filter_row = QWidget()
            filter_lay = _hbox(0, 12)
            filter_row.setLayout(filter_lay)

            def make_filter_cb(label, key, default):
                cb = ToggleSwitch(label)
                cb.setChecked(
                    bool(self.controller.get_profile_config(device_name, key, default))
                )

                def on_toggle(checked, k=key):
                    self.controller.update_device_config(device_name, k, bool(checked))
                    self.controller.save_profiles()
                    if hasattr(self.controller, 'force_recalculate'):
                        self.controller.force_recalculate()

                cb.toggled.connect(on_toggle)
                return cb

            filter_lay.addWidget(make_filter_cb("Touch", f"motor_{motor_idx}_touch", True))
            filter_lay.addWidget(make_filter_cb("Penetration", f"motor_{motor_idx}_pen", True))
            filter_lay.addWidget(make_filter_cb("Self", f"motor_{motor_idx}_self", False))
            filter_lay.addWidget(make_filter_cb("Others", f"motor_{motor_idx}_others", True))
            filter_lay.addStretch(1)
            mlay.addWidget(filter_row)

            # Linear-actuator controls
            this_kind = motor_kinds[motor_idx] if (motor_kinds and motor_idx < len(motor_kinds)) else None
            if this_kind in ("linear", "linear-d"):
                lin_row = QWidget()
                lin_lay = _hbox(0, 8)
                lin_row.setLayout(lin_lay)

                lin_lay.addWidget(QLabel("Mode:"))
                current_mode = self.controller.get_profile_config(
                    device_name, f"motor_{motor_idx}_linear_mode", "position"
                )
                mode_group = self._make_segmented(
                    options=["Position", "Speed"],
                    current=("Speed" if current_mode == "speed" else "Position"),
                    on_change=lambda val, idx=motor_idx: (
                        self.controller.update_device_config(
                            device_name, f"motor_{idx}_linear_mode", val.lower()
                        ),
                        self.controller.save_profiles(),
                        self.controller.update_linear_motor_config(device_name, idx)
                        if hasattr(self.controller, "update_linear_motor_config") else None,
                    ),
                )
                lin_lay.addWidget(mode_group)

                lin_lay.addSpacing(12)
                lin_lay.addWidget(QLabel("Idle:"))
                current_idle = self.controller.get_profile_config(
                    device_name, f"motor_{motor_idx}_linear_idle", "rest"
                )
                idle_group = self._make_segmented(
                    options=["Hold", "Rest"],
                    current=("Hold" if current_idle == "hold" else "Rest"),
                    on_change=lambda val, idx=motor_idx: (
                        self.controller.update_device_config(
                            device_name, f"motor_{idx}_linear_idle", val.lower()
                        ),
                        self.controller.save_profiles(),
                        self.controller.update_linear_motor_config(device_name, idx)
                        if hasattr(self.controller, "update_linear_motor_config") else None,
                    ),
                )
                lin_lay.addWidget(idle_group)
                lin_lay.addStretch(1)
                mlay.addWidget(lin_row)

            # Custom OSC addresses
            raw_entry = osc_addresses.get(str(motor_idx), [])
            if isinstance(raw_entry, str):
                addresses_list = [raw_entry] if raw_entry.strip() else []
            elif isinstance(raw_entry, list):
                addresses_list = [a for a in raw_entry if isinstance(a, str)]
            else:
                addresses_list = []

            self._setup_motor_address_row(mlay, device_name, motor_idx, addresses_list)

            # Slider (intensity)
            slider = QSlider(Qt.Horizontal)
            slider.setRange(0, 1000)
            slider.setValue(0)
            slider.valueChanged.connect(
                lambda v, dn=device_name, idx=motor_idx:
                    self.controller.update_device_target(dn, v / 1000.0, idx)
            )
            mlay.addWidget(slider)

            # Vibe meter (read-only progress)
            vibe_meter = QProgressBar()
            vibe_meter.setRange(0, 1000)
            vibe_meter.setValue(0)
            vibe_meter.setTextVisible(False)
            vibe_meter.setFixedHeight(6)
            mlay.addWidget(vibe_meter)

            card_lay.addWidget(motor_frame)
            motor_vars.append({
                "slider": _SliderProxy(slider),
                "vibe_meter": _ProgressProxy(vibe_meter),
                "addresses": addresses_list,
            })

        # Insert at the end of the unified devices list (before the stretch).
        layout = self.unified_devices_layout
        if layout is not None:
            # stretch was added last by setup; insert before it
            insert_pos = max(layout.count() - 1, 0)
            layout.insertWidget(insert_pos, card)

        return {
            "frame": card,
            "status_label": name_label,
            "battery_label": battery_label,
            "delete_button": delete_button,
            "icon_button": icon_button,
            "motors": motor_vars,
        }

    # ----------------------------------------------------------
    # Lovense product icon (auto-detect + manual override)
    # ----------------------------------------------------------

    def _apply_lovense_icon(self, device_name: str, button: "QToolButton") -> None:
        """Refresh the icon button to reflect current override / auto-detect state."""
        override = self.controller.get_profile_config(device_name, "icon_override", None)
        key = _lovense_icons.resolve_key(device_name, override)
        pixmap = _lovense_icons.load_pixmap(key, size=32, circular=True) if key else None
        if pixmap is not None:
            button.setIcon(QIcon(pixmap))
            button.setIconSize(QSize(32, 32))
            tip = f"{_lovense_icons.display_name(key)} — click to change"
        else:
            button.setIcon(QIcon())
            button.setText("?")
            tip = "No icon — click to pick one"
        button.setToolTip(tip)

    def _on_lovense_icon_clicked(self, device_name: str, button: "QToolButton") -> None:
        current_override = self.controller.get_profile_config(
            device_name, "icon_override", None
        )
        result = _lovense_icons.pick_icon(self.window, device_name, current_override)
        if result is _lovense_icons.PICK_CANCELLED:
            return
        # PICK_AUTO  -> None ; PICK_NONE -> "" ; "<key>" -> "<key>"
        self.controller.update_device_config(device_name, "icon_override", result)
        if hasattr(self.controller, "save_profiles"):
            self.controller.save_profiles()
        self._apply_lovense_icon(device_name, button)

    def _make_segmented(self, options: List[str], current: str,
                        on_change: Callable[[str], None]) -> QWidget:
        """Two-or-three-button segmented control."""
        host = QWidget()
        h = _hbox(0, 2)
        host.setLayout(h)
        group = QButtonGroup(host)
        group.setExclusive(True)

        def apply_styles():
            for btn in group.buttons():
                btn.setProperty("role", "segActive" if btn.isChecked() else "segIdle")
                self._repolish(btn)

        def on_clicked(btn):
            apply_styles()
            on_change(btn.text())

        for opt in options:
            b = QPushButton(opt)
            b.setCheckable(True)
            b.setFixedHeight(24)
            b.setChecked(opt == current)
            group.addButton(b)
            h.addWidget(b)
        apply_styles()
        group.buttonClicked.connect(on_clicked)
        return host

    # ----------------------------------------------------------
    # Custom OSC address row (per motor)
    # ----------------------------------------------------------

    def _setup_motor_address_row(self, parent_layout: QVBoxLayout,
                                 device_name: str, motor_idx: int,
                                 addresses_list: list):
        container = QWidget()
        clay = _vbox(0, 4)
        container.setLayout(clay)

        chips_host = QWidget()
        chips_lay = _vbox(0, 2)
        chips_host.setLayout(chips_lay)
        clay.addWidget(chips_host)

        def persist():
            current = self.controller.get_profile_config(
                device_name, "osc_addresses", {}
            ) or {}
            if not isinstance(current, dict):
                current = {}
            current[str(motor_idx)] = list(addresses_list)
            self.controller.update_device_config(device_name, "osc_addresses", current)
            self.controller.save_profiles()
            if hasattr(self.controller, 'force_recalculate'):
                self.controller.force_recalculate()

        def render():
            _clear_layout(chips_lay)
            if not addresses_list:
                empty = QLabel(
                    "No addresses — click 'Add Variable' to map an OSC parameter."
                )
                empty.setProperty("muted", "true")
                self._repolish(empty)
                chips_lay.addWidget(empty)
                return
            for i, addr in enumerate(list(addresses_list)):
                chip = QFrame()
                chip.setObjectName("chip")
                ch_lay = _hbox(8, 4)
                chip.setLayout(ch_lay)
                lbl = QLabel(addr)
                ch_lay.addWidget(lbl, 1)
                rm = QPushButton("×")
                rm.setFixedSize(22, 20)
                rm.setProperty("role", "chipClose")
                rm.clicked.connect(
                    lambda _=False, idx=i: self._remove_motor_address(
                        addresses_list, idx, render, persist
                    )
                )
                ch_lay.addWidget(rm)
                chips_lay.addWidget(chip)

        def add_address(new_addr: str):
            cleaned = (new_addr or "").strip()
            if cleaned.startswith("/avatar/parameters/"):
                cleaned = cleaned[len("/avatar/parameters/"):]
            elif cleaned.startswith("/"):
                cleaned = cleaned[1:]
            if not cleaned or cleaned in addresses_list:
                return
            addresses_list.append(cleaned)
            render()
            persist()

        add_btn = QPushButton("+ Add Variable")
        add_btn.setFixedHeight(BTN_HEIGHT_SMALL)
        add_btn.setProperty("role", "secondary")
        add_btn.clicked.connect(lambda: self._open_variable_picker(add_address))
        clay.addWidget(add_btn)

        render()
        parent_layout.addWidget(container)

    @staticmethod
    def _remove_motor_address(lst, idx, render, persist):
        if 0 <= idx < len(lst):
            lst.pop(idx)
            render()
            persist()

    # ----------------------------------------------------------
    # Variable picker dialog
    # ----------------------------------------------------------

    def _open_variable_picker(self, on_pick: Callable[[str], None]):
        dlg = QDialog(self.window)
        dlg.setWindowTitle("Add OSC Variable")
        dlg.resize(560, 600)
        dlg.setModal(True)

        lay = _vbox(12, 6)
        dlg.setLayout(lay)

        title = QLabel("Add OSC Variable")
        title.setObjectName("sectionTitle")
        title.setAlignment(Qt.AlignHCenter)
        lay.addWidget(title)

        sub = QLabel(
            "Pick from live avatar parameters (double-click to add) or enter one manually."
        )
        sub.setProperty("muted", "true")
        sub.setAlignment(Qt.AlignHCenter)
        sub.setWordWrap(True)
        lay.addWidget(sub)

        search = QLineEdit()
        search.setPlaceholderText("Search avatar parameters...")
        lay.addWidget(search)

        show_all = ToggleSwitch("Include non-avatar parameters (OGB/SPS, system, etc.)")
        lay.addWidget(show_all)

        tree = QTreeWidget()
        tree.setColumnCount(2)
        tree.setHeaderLabels(["Parameter", "Value"])
        tree.setRootIsDecorated(False)
        tree.setAlternatingRowColors(False)
        tree.header().setStretchLastSection(False)
        tree.header().setSectionResizeMode(0, QHeaderView.Stretch)
        tree.header().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        lay.addWidget(tree, 1)

        empty_lbl = QLabel("No avatar parameters seen yet.")
        empty_lbl.setProperty("muted", "true")
        empty_lbl.setAlignment(Qt.AlignHCenter)
        empty_lbl.setVisible(False)
        lay.addWidget(empty_lbl)

        # Bottom card: manual entry + actions
        bottom = _Card()
        b_lay = _vbox(8, 6)
        bottom.setLayout(b_lay)

        b_lay.addWidget(self._muted_label(
            "Or add manually (wildcards allowed, e.g. OGB/Tail/*):"
        ))
        manual_row = QWidget()
        m_lay = _hbox(0, 6)
        manual_row.setLayout(m_lay)
        manual_entry = QLineEdit()
        manual_entry.setPlaceholderText("e.g. OGB/Tail/Touch")
        m_lay.addWidget(manual_entry, 1)
        manual_add = QPushButton("Add Manual")
        manual_add.setProperty("role", "secondary")
        m_lay.addWidget(manual_add)
        b_lay.addWidget(manual_row)

        action_row = QWidget()
        a_lay = _hbox(0, 6)
        action_row.setLayout(a_lay)
        a_lay.addStretch(1)
        add_selected_btn = QPushButton("Add Selected")
        a_lay.addWidget(add_selected_btn)
        b_lay.addWidget(action_row)

        lay.addWidget(bottom)

        # ---- behavior ----
        state = {"last_keys": None, "last_query": None, "last_filtered": ()}

        def is_avatar_param(addr: str) -> bool:
            return not addr.startswith("OGB/")

        def fmt(val):
            if isinstance(val, float):
                return f"{val:.2f}"
            return str(val)

        def rebuild(filtered, params):
            tree.clear()
            for key in filtered:
                item = QTreeWidgetItem([key, fmt(params.get(key, ""))])
                tree.addTopLevelItem(item)

        def update_values(filtered, params):
            for i in range(tree.topLevelItemCount()):
                item = tree.topLevelItem(i)
                key = item.text(0)
                item.setText(1, fmt(params.get(key, "")))

        def refresh():
            params = store.get_all_parameters()
            include_all = show_all.isChecked()
            if include_all:
                keys = tuple(sorted(params.keys()))
            else:
                keys = tuple(sorted(k for k in params.keys() if is_avatar_param(k)))
            query = search.text().strip().lower()

            keys_changed = keys != state["last_keys"]
            query_changed = query != state["last_query"]
            state["last_keys"] = keys
            state["last_query"] = query

            if not keys:
                tree.clear()
                empty_lbl.setVisible(True)
                state["last_filtered"] = ()
                return

            empty_lbl.setVisible(False)
            if keys_changed or query_changed:
                filtered = tuple(k for k in keys if not query or query in k.lower())
                state["last_filtered"] = filtered
                rebuild(filtered, params)
            else:
                update_values(state["last_filtered"], params)

        def add_and_close(addr: str):
            try:
                on_pick(addr)
            finally:
                dlg.accept()

        def add_selected_action():
            items = tree.selectedItems()
            if items:
                add_and_close(items[0].text(0))

        def submit_manual():
            text = manual_entry.get() if hasattr(manual_entry, "get") else manual_entry.text()
            text = (text or "").strip()
            if text:
                add_and_close(text)

        # Periodic value refresh while dialog is open.
        tick = QTimer(dlg)
        tick.setInterval(1500)
        tick.timeout.connect(refresh)
        tick.start()

        # Debounce search input.
        debounce = QTimer(dlg)
        debounce.setSingleShot(True)
        debounce.setInterval(180)
        debounce.timeout.connect(refresh)

        search.textChanged.connect(lambda _=None: debounce.start())
        show_all.toggled.connect(lambda _=False: refresh())

        tree.itemDoubleClicked.connect(lambda item, _col: add_and_close(item.text(0)))
        add_selected_btn.clicked.connect(add_selected_action)
        manual_entry.returnPressed.connect(submit_manual)
        manual_add.clicked.connect(submit_manual)

        refresh()
        search.setFocus()
        dlg.exec()

    def _muted_label(self, text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setProperty("muted", "true")
        # Word-wrap is critical — without it, long description blocks force
        # the page's minimum width to fit the full single-line text, which
        # prevents the window from shrinking and clips titles on narrow views.
        lbl.setWordWrap(True)
        self._repolish(lbl)
        return lbl

    # ----------------------------------------------------------
    # OSC debugger display
    # ----------------------------------------------------------

    def update_osc_debugger_button(self, is_running: bool):
        if self.osc_debugger_button is None:
            return
        if is_running:
            self.osc_debugger_button.setText("Stop OSC Debugger")
            self.osc_debugger_button.setProperty("role", "danger")
        else:
            self.osc_debugger_button.setText("Start OSC Debugger")
            self.osc_debugger_button.setProperty("role", "")
        self._repolish(self.osc_debugger_button)

    def update_debugger_display(self, data):
        # Render to both views: the table (default) and the legacy HTML box
        # underneath. They consume the same data so they stay in sync.
        self._update_debugger_table(data)
        self._update_debugger_textbox(data)

    def _update_debugger_textbox(self, data):
        """Legacy display: QTextEdit re-rendered via setHtml on every tick.
        Mirrors the pre-overhaul implementation (see git 471f158)."""
        box = self.debugger_textbox
        if box is None:
            return
        sb = box.verticalScrollBar()
        scroll_pos = sb.value()

        if isinstance(data, list):
            html_parts = []
            for entry in data:
                if not isinstance(entry, tuple):
                    continue
                if len(entry) == 3:
                    addr_prefix, val_str, color = entry
                else:
                    addr_prefix, color = entry
                    val_str = ""
                safe_addr = _html_escape(addr_prefix)
                safe_val = _html_escape(val_str)
                line = (
                    f'<span style="color:{COLOR_TEXT_MUTED}; white-space:pre">{safe_addr}&nbsp;:&nbsp;</span>'
                    f'<span style="color:{color}">{safe_val}</span><br>'
                )
                html_parts.append(line)
            html = f'<pre style="margin:0; font-family:Consolas,monospace;">{"".join(html_parts)}</pre>'
            box.setHtml(html)
        else:
            box.setPlainText(str(data))

        sb.setValue(scroll_pos)

    def _update_debugger_table(self, data):
        tbl = self.debugger_table
        if tbl is None:
            return

        if not isinstance(data, list):
            tbl.setRowCount(1)
            placeholder = QTableWidgetItem(str(data))
            placeholder.setForeground(QColor(COLOR_TEXT_MUTED))
            tbl.setItem(0, 0, placeholder)
            tbl.setItem(0, 1, QTableWidgetItem(""))
            return

        rows = []
        for entry in data:
            if not isinstance(entry, tuple):
                continue
            if len(entry) == 3:
                addr, val_str, color = entry
            else:
                addr, color = entry
                val_str = ""
            # Address was padded with ljust+ " : " for the old text view; strip
            # that trailing decoration so the table column owns its own layout.
            addr_clean = addr.rstrip()
            if addr_clean.endswith(":"):
                addr_clean = addr_clean[:-1].rstrip()
            rows.append((addr_clean, val_str, color))

        tbl.setUpdatesEnabled(False)
        # In-place update: resize row count, then overwrite text on existing
        # cells. We never call clear()/setHtml(), so the horizontal scrollbar
        # range and value are preserved by Qt itself.
        if tbl.rowCount() != len(rows):
            tbl.setRowCount(len(rows))
        muted = QColor(COLOR_TEXT_MUTED)
        for r, (addr, val_str, color) in enumerate(rows):
            addr_item = tbl.item(r, 0)
            if addr_item is None:
                addr_item = QTableWidgetItem()
                addr_item.setForeground(muted)
                tbl.setItem(r, 0, addr_item)
            if addr_item.text() != addr:
                addr_item.setText(addr)

            val_item = tbl.item(r, 1)
            if val_item is None:
                val_item = QTableWidgetItem()
                tbl.setItem(r, 1, val_item)
            if val_item.text() != val_str:
                val_item.setText(val_str)
            val_item.setForeground(QColor(color))
        tbl.setUpdatesEnabled(True)

    # ----------------------------------------------------------
    # Stored / discovered device list builders
    # ----------------------------------------------------------

    def build_stored_devices_ui(self):
        controller = self.controller

        connected_names = controller.get_connected_device_names()
        # The "active" profile is whichever ProfileManager resolves right
        # now — an avatar profile bound to the current VRChat avatar, or
        # the selected global profile as a fallback.
        active_profile = controller.get_active_profile_dict() or {}
        has_saved_devices = bool(active_profile)

        # If no saved devices and we already have frames (from build_device_list_ui),
        # don't clear — just refresh status.
        if not has_saved_devices and self.device_ui_frames:
            self.update_stored_devices_ui()
            return

        # Clear existing device cards from the layout (preserve the trailing stretch).
        if self.unified_devices_layout is not None:
            # Remove every widget item; rebuild stretch at the end.
            i = 0
            while i < self.unified_devices_layout.count():
                item = self.unified_devices_layout.itemAt(i)
                if item is None:
                    i += 1
                    continue
                w = item.widget()
                if w is not None:
                    self.unified_devices_layout.takeAt(i)
                    w.setParent(None)
                    w.deleteLater()
                else:
                    i += 1
            self.unified_devices_layout.addStretch(1)

        self.stored_device_frames.clear()
        self.device_ui_frames.clear()

        if not has_saved_devices:
            placeholder = QLabel("No saved toys yet. Connect devices to save them.")
            placeholder.setProperty("muted", "true")
            placeholder.setAlignment(Qt.AlignHCenter)
            self._repolish(placeholder)
            if self.unified_devices_layout is not None:
                self.unified_devices_layout.insertWidget(0, placeholder)
            return

        device_motor_counts = controller.get_device_motor_counts()
        all_devices = list(active_profile.keys())
        all_devices.sort(key=lambda name: (name not in connected_names, name.lower()))

        for device_name in all_devices:
            config = active_profile[device_name]
            is_connected = device_name in connected_names

            stored_motor_count = device_motor_counts.get(
                device_name, config.get("motor_count", 1)
            )

            osc_addresses = config.get("osc_addresses", {})
            if not osc_addresses and config.get("osc_address"):
                osc_addresses["0"] = [config.get("osc_address")]

            stored_motor_kinds = config.get("motor_kinds")

            frame_data = self._create_device_frame(
                device_name=device_name,
                is_connected=is_connected,
                osc_addresses=osc_addresses,
                motor_count=stored_motor_count,
                motor_kinds=stored_motor_kinds,
            )
            self.device_ui_frames[device_name] = frame_data

            if hasattr(controller, 'update_device_target'):
                controller.update_device_target(device_name, 0.0, -1)

            self.stored_device_frames[device_name] = {
                "frame": frame_data["frame"],
                "status_label": frame_data["status_label"],
                "delete_button": frame_data["delete_button"],
            }

    def build_device_list_ui(self, devices_dict: dict):
        controller = self.controller
        if not devices_dict:
            return

        device_motor_counts = controller.get_device_motor_counts()

        for index, device_info in devices_dict.items():
            if isinstance(device_info, dict):
                device_name = device_info.get("name", f"Device_{index}")
                motor_count = device_info.get("motor_count", 1)
            else:
                device_name = str(device_info)
                motor_count = 1

            actual_motor_count = device_motor_counts.get(device_name, motor_count)
            controller.log_message(
                f"DEBUG: {device_name} - devices_dict motor_count={motor_count}, "
                f"actual_motor_count={actual_motor_count}"
            )

            if device_name not in self.device_ui_frames:
                osc_addresses = {}
                for i in range(actual_motor_count):
                    suffix = f"_{i}" if actual_motor_count > 1 else ""
                    osc_addresses[str(i)] = [f"{device_name.replace(' ', '_')}{suffix}"]

                controller.update_device_config(device_name, "motor_count", motor_count)

                motor_kinds = device_info.get("motor_kinds") if isinstance(device_info, dict) else None

                frame_data = self._create_device_frame(
                    device_name=device_name,
                    is_connected=True,
                    osc_addresses=osc_addresses,
                    motor_count=actual_motor_count,
                    motor_kinds=motor_kinds,
                )
                self.device_ui_frames[device_name] = frame_data

                if hasattr(controller, 'update_device_target'):
                    controller.update_device_target(device_name, 0.0, -1)

                self.stored_device_frames[device_name] = {
                    "frame": frame_data["frame"],
                    "status_label": frame_data["status_label"],
                    "delete_button": frame_data["delete_button"],
                }

        controller.log_message(f"Connected devices: {len(devices_dict)}")
        self._reorder_device_frames()

    def _reorder_device_frames(self):
        if self.unified_devices_layout is None:
            return
        connected_names = self.controller.get_connected_device_names()
        all_names = list(self.device_ui_frames.keys())
        all_names.sort(key=lambda name: (name not in connected_names, name.lower()))

        # Take every device card out, then re-insert in sorted order.
        # Anything that isn't a tracked device card stays put.
        tracked_frames = {self.device_ui_frames[n]["frame"]: n for n in all_names}
        non_card_items: list = []
        i = 0
        while i < self.unified_devices_layout.count():
            item = self.unified_devices_layout.itemAt(i)
            if item is None:
                i += 1
                continue
            w = item.widget()
            if w is not None and w in tracked_frames:
                self.unified_devices_layout.takeAt(i)
            else:
                i += 1

        # Re-insert cards in order, before the trailing stretch (if any).
        # Find index of stretch.
        stretch_index = self.unified_devices_layout.count()
        for j in range(self.unified_devices_layout.count()):
            item = self.unified_devices_layout.itemAt(j)
            if item is not None and item.spacerItem() is not None:
                stretch_index = j
                break

        for name in all_names:
            self.unified_devices_layout.insertWidget(
                stretch_index, self.device_ui_frames[name]["frame"]
            )
            stretch_index += 1

    # ----------------------------------------------------------
    # Programmatic value updates
    # ----------------------------------------------------------

    def update_device_visuals(self, device_name: str, motor_idx: int, value: float):
        """Update both the slider and vibe meter (used by the ui_slider_update
        path, which is guarded by the controller's _is_updating_ui lock)."""
        if device_name not in self.device_ui_frames:
            return
        motors = self.device_ui_frames[device_name].get("motors", [])
        if 0 <= motor_idx < len(motors):
            motors[motor_idx]["slider"].set(value)
            motors[motor_idx]["vibe_meter"].set(value)
        elif motor_idx == -1:
            for mv in motors:
                mv["slider"].set(value)
                mv["vibe_meter"].set(value)

    def update_motor_vibe(self, device_name: str, motor_idx: int, value: float):
        """Meter-only update — leaves the user-facing slider alone."""
        if device_name not in self.device_ui_frames:
            return
        motors = self.device_ui_frames[device_name].get("motors", [])
        if 0 <= motor_idx < len(motors):
            motors[motor_idx]["vibe_meter"].set(value)

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
        g = self.window.geometry()
        return _format_tk_geometry(g.width(), g.height(), g.x(), g.y())

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

    # --- Device frame management ---
    def remove_device_frame(self, device_name: str) -> None:
        frame_data = self.stored_device_frames.pop(device_name, None)
        if frame_data:
            frame: Optional[QWidget] = frame_data.get("frame")
            if frame is not None:
                try:
                    frame.setParent(None)
                    frame.deleteLater()
                except Exception:
                    pass
        self.device_ui_frames.pop(device_name, None)

    def clear_device_caches(self) -> None:
        # Also tear down the actual widgets so a fresh build_stored_devices_ui
        # call doesn't leave orphan cards on screen.
        if self.unified_devices_layout is not None:
            for data in list(self.device_ui_frames.values()):
                frame = data.get("frame")
                if frame is not None:
                    frame.setParent(None)
                    frame.deleteLater()
        self.device_ui_frames.clear()
        self.stored_device_frames.clear()

    def get_known_device_names(self) -> list:
        return list(self.device_ui_frames.keys())

    # Backwards-compat alias (old code may have set self.app).
    @property
    def app(self):
        return self.window


# (_SliderProxy / _ProgressProxy / _truncate / _html_escape now live in
# `ui/widgets.py` and `ui/text_helpers.py`. The import-aliases at the top
# of this file preserve the underscore names.)
