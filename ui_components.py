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
    Qt, QTimer, Signal, QObject, QEvent, QSize
)
from PySide6.QtGui import (
    QFont, QColor, QTextCharFormat, QTextCursor, QFontDatabase, QIcon, QPalette
)
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QLabel, QPushButton, QCheckBox, QLineEdit, QSlider, QProgressBar,
    QFrame, QScrollArea, QTextEdit, QPlainTextEdit, QSizePolicy, QSpacerItem,
    QDialog, QMessageBox, QTreeWidget, QTreeWidgetItem, QHeaderView,
    QButtonGroup, QStackedWidget,
)

from constants import *
from parameter_store import store


# ============================================================
# Helpers
# ============================================================

_TK_GEOM_RE = re.compile(r"^\s*(\d+)x(\d+)(?:\+(-?\d+)\+(-?\d+))?\s*$")


def _parse_tk_geometry(geom: str):
    """Parse a Tkinter-style geometry string into (w, h, x, y).
    Returns None on failure. x/y may be None when not present."""
    if not geom:
        return None
    m = _TK_GEOM_RE.match(geom)
    if not m:
        return None
    w, h = int(m.group(1)), int(m.group(2))
    x = int(m.group(3)) if m.group(3) is not None else None
    y = int(m.group(4)) if m.group(4) is not None else None
    return (w, h, x, y)


def _format_tk_geometry(w: int, h: int, x: int, y: int) -> str:
    return f"{w}x{h}+{x}+{y}"


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
    background-color: {COLOR_SURFACE};
    color: {COLOR_TEXT};
}}
QPushButton[role="secondary"]:hover {{
    background-color: {COLOR_SURFACE_HOVER};
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
    background-color: {COLOR_SURFACE};
    color: {COLOR_TEXT};
}}
QPushButton[role="profileIdle"]:hover {{
    background-color: {COLOR_SURFACE_HOVER};
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
    background-color: {COLOR_SURFACE_HOVER};
}}

QLineEdit, QTextEdit, QPlainTextEdit {{
    background-color: {COLOR_BG};
    color: {COLOR_TEXT};
    border: 1px solid {COLOR_SURFACE};
    border-radius: 4px;
    padding: 4px 6px;
    selection-background-color: {COLOR_PRIMARY};
}}
QTextEdit, QPlainTextEdit {{
    font-family: "Consolas", "Courier New", monospace;
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
    background-color: {COLOR_SURFACE};
}}
QCheckBox::indicator:checked {{
    background-color: {COLOR_PRIMARY};
    border-color: {COLOR_PRIMARY};
}}
QCheckBox::indicator:hover {{
    border-color: {COLOR_PRIMARY_HOVER};
}}
QCheckBox[role="switch"]::indicator {{
    width: 32px;
    height: 16px;
    border-radius: 8px;
}}
QCheckBox[role="switch"]::indicator:checked {{
    background-color: {COLOR_SUCCESS};
    border-color: {COLOR_SUCCESS};
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
"""


# ============================================================
# Cross-thread invocation helper
# ============================================================

class _Invoker(QObject):
    """Lives on the UI thread. Other threads can ask it to run callables
    by emitting signals — signals are thread-safe and queued."""

    _invoke = Signal(int, object)  # (delay_ms, callable)

    def __init__(self):
        super().__init__()
        self._invoke.connect(self._on_invoke, Qt.QueuedConnection)

    def schedule(self, delay_ms: int, func: Callable) -> None:
        self._invoke.emit(int(delay_ms), func)

    def _on_invoke(self, delay_ms: int, func: Callable) -> None:
        if delay_ms <= 0:
            func()
        else:
            QTimer.singleShot(delay_ms, func)


# ============================================================
# Main window subclass that intercepts the X button
# ============================================================

class _MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self._close_handler: Optional[Callable] = None
        self._allow_close = False

    def set_close_handler(self, cb: Callable) -> None:
        self._close_handler = cb

    def allow_close(self) -> None:
        self._allow_close = True

    def closeEvent(self, event):
        if self._allow_close or self._close_handler is None:
            event.accept()
            return
        # Hand control to the controller; it decides hide vs quit.
        try:
            self._close_handler()
        except Exception:
            event.accept()
            return
        event.ignore()


# ============================================================
# Small layout helpers
# ============================================================

def _vbox(margin=0, spacing=6) -> QVBoxLayout:
    lay = QVBoxLayout()
    lay.setContentsMargins(margin, margin, margin, margin)
    lay.setSpacing(spacing)
    return lay


def _hbox(margin=0, spacing=6) -> QHBoxLayout:
    lay = QHBoxLayout()
    lay.setContentsMargins(margin, margin, margin, margin)
    lay.setSpacing(spacing)
    return lay


def _clear_layout(layout):
    """Remove and destroy every child of `layout`."""
    if layout is None:
        return
    while layout.count():
        item = layout.takeAt(0)
        w = item.widget()
        if w is not None:
            w.setParent(None)
            w.deleteLater()
        else:
            sub = item.layout()
            if sub is not None:
                _clear_layout(sub)
                sub.deleteLater()


class _Card(QFrame):
    """QFrame styled as a rounded card."""

    def __init__(self, dark_bg: bool = False, parent=None):
        super().__init__(parent)
        self.setObjectName("cardDark" if dark_bg else "card")


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
        self.osc_auto_connect_checkbox: Optional[QCheckBox] = None
        self.auto_connect_checkbox: Optional[QCheckBox] = None

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

        # Main content area (stacked views)
        self.main_stack = QStackedWidget()
        root_layout.addWidget(self.main_stack, 1)

        # Build all views into the stack.
        view_names = ["Dashboard", "Device Routing", "Network & Debug",
                      "System Log", "Settings", "Help"]
        builders = {
            "Dashboard": self._build_dashboard_view,
            "Device Routing": self._build_device_routing_view,
            "Network & Debug": self._build_network_debug_view,
            "System Log": self._build_system_log_view,
            "Settings": self._build_settings_view,
            "Help": self._build_help_view,
        }
        for name in view_names:
            page = QWidget()
            page_lay = _vbox(20, 12)
            page.setLayout(page_lay)
            builders[name](page_lay)
            self.views[name] = page
            self.main_stack.addWidget(page)

        self.window.setCentralWidget(root)
        self.select_view("Dashboard")

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

        nav_buttons = ["Dashboard", "Device Routing", "Network & Debug",
                       "System Log", "Settings", "Help"]
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

        self.osc_auto_connect_checkbox = QCheckBox("Auto Connect")
        self.osc_auto_connect_checkbox.setChecked(
            bool(self.controller.get_app_setting("auto_connect_osc", True))
        )
        self.osc_auto_connect_checkbox.toggled.connect(
            lambda _=False: self.controller.toggle_osc_auto_connect()
        )
        lay.addWidget(self.osc_auto_connect_checkbox, alignment=Qt.AlignHCenter)
        lay.addSpacing(8)

        # Separator
        sep = QFrame()
        sep.setObjectName("separator")
        lay.addWidget(sep)
        lay.addSpacing(8)

        # --- Intiface Central Section ---
        lay.addWidget(self._sidebar_section_title("Intiface Central"))

        self.status_label = QLabel("Status: Disconnected")
        self.status_label.setProperty("role", "alert")
        self.status_label.setAlignment(Qt.AlignHCenter)
        lay.addWidget(self.status_label)

        self.connection_button = QPushButton("Connect to Intiface")
        self.connection_button.setMinimumHeight(BTN_HEIGHT_LARGE)
        self.connection_button.clicked.connect(self.controller.connect_to_intiface)
        lay.addWidget(self.connection_button)

        self.auto_connect_checkbox = QCheckBox("Auto Connect")
        self.auto_connect_checkbox.setChecked(
            bool(self.controller.get_app_setting("auto_connect", True))
        )
        self.auto_connect_checkbox.toggled.connect(
            lambda _=False: self.controller.toggle_auto_connect()
        )
        lay.addWidget(self.auto_connect_checkbox, alignment=Qt.AlignHCenter)
        lay.addSpacing(8)

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
        pm = self.controller.profile_manager
        active = self.controller.get_active_profile_info() \
            if hasattr(self.controller, "get_active_profile_info") \
            else {"kind": "global", "name": pm.current_profile}

        # ---- Active banner ----
        if self.profile_active_label is not None:
            kind_label = "Avatar" if active["kind"] == "avatar" else "Global"
            self.profile_active_label.setText(
                f"Active profile: {kind_label} · {active['name']}"
            )

        # ---- Current avatar label ----
        if self.current_avatar_label is not None:
            avatar_id = pm.current_avatar_id or ""
            if avatar_id:
                self.current_avatar_label.setText(f"Current avatar: {_truncate(avatar_id, 28)}")
            else:
                self.current_avatar_label.setText("Current avatar: (not detected)")

        # ---- Clipboard-aware paste buttons ----
        has_clip = pm.has_clipboard()
        src = pm.get_clipboard_source_name() or ""
        for btn in (self.global_paste_btn, self.avatar_paste_btn):
            if btn is None:
                continue
            btn.setEnabled(has_clip)
            btn.setText(f"📥 Paste (from '{_truncate(src, 18)}')" if has_clip else "📥 Paste")

        # ---- Avatar 'New' button availability ----
        if self.avatar_new_btn is not None:
            if pm.current_avatar_id:
                self.avatar_new_btn.setEnabled(True)
                self.avatar_new_btn.setText(
                    f"+ New Avatar Profile (binds to {_truncate(pm.current_avatar_id, 16)})"
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
            total = len(pm.avatar_profiles)
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

        pm = self.controller.profile_manager
        names = list(pm.profiles.keys())
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
            )
            self.global_profile_list_layout.addWidget(row)

    def _build_avatar_profile_rows(self, active: dict):
        """Show only profiles bound to the *current* avatar (typically 0–1
        rows). The rest live in the Avatar Profile Manager dialog so the
        Dashboard stays uncluttered when you have many avatars."""
        if self.avatar_profile_list_layout is None:
            return
        _clear_layout(self.avatar_profile_list_layout)

        pm = self.controller.profile_manager
        current_avatar = pm.current_avatar_id or ""
        all_names = list(pm.avatar_profiles.keys())
        relevant = [
            n for n in all_names
            if pm.avatar_bindings.get(n, "") == current_avatar and current_avatar
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
                bound_id = pm.avatar_bindings.get(name, "")
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
                )
                self.avatar_profile_list_layout.addWidget(row)


    def _make_profile_row(self, name: str, on_activate, on_rename,
                          on_copy, on_delete, can_delete: bool = True,
                          is_active: bool = False, is_selected: bool = False,
                          meta_text: str = "",
                          bound_avatar_id: str = "", bound_is_current: bool = False,
                          show_bind: bool = False,
                          extra_actions: Optional[list] = None) -> QWidget:
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
                        width: int = 34):
            b = QPushButton(text)
            b.setFixedSize(width, 34)
            b.setProperty("role", role)
            b.setToolTip(tooltip)
            b.setEnabled(enabled)
            b.clicked.connect(lambda _=False: cb())
            return b

        rlay.addWidget(make_action("✎", "Rename", on_rename))
        rlay.addWidget(make_action("📋", "Copy to clipboard", on_copy))
        rlay.addWidget(make_action(
            "🗑", "Delete", on_delete,
            role="danger" if can_delete else "secondary",
            enabled=can_delete,
        ))
        for (label, tooltip, cb) in (extra_actions or []):
            rlay.addWidget(make_action(label, tooltip, cb, width=110))
        return row

    def _open_avatar_profile_manager(self):
        """Modal viewer + editor for every avatar profile, regardless of which
        avatar is currently loaded. Shows binding info and offers rename /
        copy / delete plus a 'Bind to current avatar' shortcut."""
        pm = self.controller.profile_manager
        dlg = QDialog(self.window)
        dlg.setWindowTitle("Avatar Profile Manager")
        dlg.resize(720, 520)
        dlg.setModal(True)

        lay = _vbox(14, 8)
        dlg.setLayout(lay)

        title = QLabel("Avatar Profile Manager")
        title.setObjectName("sectionTitle")
        lay.addWidget(title)

        cur_id = pm.current_avatar_id or "(not detected)"
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
            active = self.controller.get_active_profile_info()
            names = list(pm.avatar_profiles.keys())
            if not names:
                empty = QLabel("No avatar profiles. Close this dialog and create one from the Dashboard.")
                empty.setProperty("muted", "true")
                self._repolish(empty)
                host_lay.addWidget(empty)
                return
            for name in names:
                bound_id = pm.avatar_bindings.get(name, "")
                is_active = (active["kind"] == "avatar" and name == active["name"])
                # "Activating" from this dialog rebinds the profile to the
                # current avatar (the only way to make an avatar profile go
                # live without changing avatars).
                row = self._make_profile_row(
                    name=name,
                    is_selected=is_active,
                    is_active=is_active,
                    bound_avatar_id=bound_id,
                    bound_is_current=bool(bound_id and bound_id == pm.current_avatar_id),
                    on_activate=lambda n=name: (
                        self.controller.bind_avatar_profile_to_current(n),
                        rebuild(),
                    ),
                    on_rename=lambda n=name: self._dialog_rename_avatar(dlg, n, rebuild),
                    on_copy=lambda n=name: (
                        self.controller.copy_profile("avatar", n),
                        rebuild(),
                    ),
                    on_delete=lambda n=name: self._dialog_delete_avatar(dlg, n, rebuild),
                    can_delete=True,
                    show_bind=True,
                    extra_actions=[(
                        "↻ Bind to current",
                        "Rebind this profile to the currently-loaded avatar",
                        lambda n=name: (
                            self.controller.bind_avatar_profile_to_current(n),
                            rebuild(),
                        ),
                    )] if pm.current_avatar_id else [],
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
        pm = self.controller.profile_manager
        if kind == "global" and len(pm.profiles) <= 1:
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
        pm = self.controller.profile_manager
        source = pm.profiles if kind == "global" else pm.avatar_profiles
        if current_name not in source:
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

        ok = QPushButton("✓")
        ok.setFixedSize(32, 34)
        ok.setProperty("role", "")
        ok.setToolTip("Confirm")
        ok.clicked.connect(lambda _=False: commit())
        row_layout.addWidget(ok)

        no = QPushButton("✗")
        no.setFixedSize(32, 34)
        no.setProperty("role", "secondary")
        no.setToolTip("Cancel")
        no.clicked.connect(lambda _=False: cancel())
        row_layout.addWidget(no)

        entry.setFocus()

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
    # Network & Debug view
    # ----------------------------------------------------------

    def _build_network_debug_view(self, parent_layout: QVBoxLayout):
        title = QLabel("Network & Debug")
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

        self.osc_debugger_button = QPushButton("Start OSC Debugger")
        self.osc_debugger_button.setMinimumHeight(40)
        self.osc_debugger_button.clicked.connect(self.controller.toggle_osc_debugger)
        parent_layout.addWidget(self.osc_debugger_button)

        # Container for the inspector
        inspector_card = _Card(dark_bg=True)
        inspector_lay = _vbox(10, 6)
        inspector_card.setLayout(inspector_lay)

        info = QLabel("Live OSC Variables (toggle to start)")
        info.setProperty("muted", "true")
        info.setAlignment(Qt.AlignHCenter)
        inspector_lay.addWidget(info)

        self.osc_search_entry = QLineEdit()
        self.osc_search_entry.setPlaceholderText(
            "Search parameters (e.g., Orifice, Touch, Float)..."
        )
        inspector_lay.addWidget(self.osc_search_entry)

        self.debugger_textbox = QTextEdit()
        self.debugger_textbox.setReadOnly(True)
        self.debugger_textbox.setLineWrapMode(QTextEdit.NoWrap)
        font = QFont("Consolas")
        font.setStyleHint(QFont.Monospace)
        font.setPointSize(10)
        self.debugger_textbox.setFont(font)
        inspector_lay.addWidget(self.debugger_textbox, 1)

        parent_layout.addWidget(inspector_card, 1)

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
        self.network_bind_switch = QCheckBox()
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

        self.auto_refresh_var = QCheckBox("Auto Refresh Devices")
        self.auto_refresh_var.setChecked(
            bool(self.controller.get_app_setting("auto_refresh", True))
        )
        self.auto_refresh_var.toggled.connect(
            lambda _=False: self.controller.toggle_auto_refresh()
        )
        conn_lay.addWidget(self.auto_refresh_var)

        self.auto_connect_var = QCheckBox("Auto Connect (Intiface)")
        self.auto_connect_var.setChecked(
            bool(self.controller.get_app_setting("auto_connect", True))
        )
        self.auto_connect_var.toggled.connect(
            lambda _=False: self.controller.toggle_auto_connect()
        )
        conn_lay.addWidget(self.auto_connect_var)

        self.osc_auto_connect_var = QCheckBox("Auto Connect (VRChat OSC)")
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

        hide_console = QCheckBox("Hide Terminal Console")
        hide_console.setProperty("role", "switch")
        hide_console.setChecked(
            bool(self.controller.get_app_setting("hide_console", True))
        )

        def on_hide_console(checked):
            self.controller.set_app_setting("hide_console", bool(checked))
            self.controller.apply_console_visibility()

        hide_console.toggled.connect(on_hide_console)
        ql_lay.addWidget(hide_console)

        tray = QCheckBox("Minimize to System Tray")
        tray.setProperty("role", "switch")
        tray.setChecked(
            bool(self.controller.get_app_setting("minimize_to_tray", False))
        )
        tray.toggled.connect(
            lambda checked: self.controller.set_app_setting("minimize_to_tray", bool(checked))
        )
        ql_lay.addWidget(tray)

        parent_layout.addWidget(ql_card)
        parent_layout.addStretch(1)

    def _bold_label(self, text: str) -> QLabel:
        lbl = QLabel(text)
        f = lbl.font(); f.setBold(True)
        lbl.setFont(f)
        return lbl

    # ----------------------------------------------------------
    # Help view
    # ----------------------------------------------------------

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

        section("Profiles — what they are", """
A profile is a complete bundle of toy settings, selectable on the Dashboard. The currently-selected profile is the one the haptic engine uses for routing OSC parameters to motor outputs.

  • Click a profile tile to switch to it.
  • Click the pencil (✎) to rename it.
  • Click the trash (🗑) to delete it (disabled when only one profile remains).
  • Click "+ New Profile" to add another. There is no fixed cap.
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

        section("Real-Time OSC Inspector", """
Network & Debug → Real-Time OSC Inspector shows every OSC parameter your avatar is broadcasting. Useful for finding the exact name of a parameter before mapping it to a motor.
""")

        section("Where settings live on disk", """
%APPDATA%\\OscGoesPurrr\\
  • profiles.json         — per-profile device settings
  • known_devices.json    — global toy list (name, motor count, motor kinds)
  • app_settings.json     — global app preferences
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
        # Sync haptic engine flag (preserves prior behaviour).
        if hasattr(self.controller, 'haptic_engine') and self.controller.haptic_engine:
            self.controller.haptic_engine.is_connected = connected

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
                all_sps_cb = QCheckBox("All SPS (match any zone — overrides selections below)")
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
                    cb = QCheckBox(zone)
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

            zone_btn.clicked.connect(lambda _=False: toggle_zone_panel())

            # Interaction filter checkboxes
            filter_row = QWidget()
            filter_lay = _hbox(0, 12)
            filter_row.setLayout(filter_lay)

            def make_filter_cb(label, key, default):
                cb = QCheckBox(label)
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
            "motors": motor_vars,
        }

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

        show_all = QCheckBox("Include non-avatar parameters (OGB/SPS, system, etc.)")
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
        if self.debugger_textbox is None:
            return
        sb = self.debugger_textbox.verticalScrollBar()
        scroll_pos = sb.value()

        if isinstance(data, list):
            html_parts = []
            for entry in data:
                if not isinstance(entry, tuple):
                    continue
                if len(entry) == 3:
                    addr_prefix, val_str, color = entry
                else:
                    # (text, color) fallback
                    addr_prefix, color = entry
                    val_str = ""
                safe_addr = _html_escape(addr_prefix)
                safe_val = _html_escape(val_str)
                line = (
                    f'<span style="color:{COLOR_TEXT_MUTED}; white-space:pre">{safe_addr}</span>'
                    f'<span style="color:{color}">{safe_val}</span><br>'
                )
                html_parts.append(line)
            html = f'<pre style="margin:0; font-family:Consolas,monospace;">{"".join(html_parts)}</pre>'
            self.debugger_textbox.setHtml(html)
        else:
            self.debugger_textbox.setPlainText(str(data))

        sb.setValue(scroll_pos)

    # ----------------------------------------------------------
    # Stored / discovered device list builders
    # ----------------------------------------------------------

    def build_stored_devices_ui(self):
        controller = self.controller

        connected_names = controller.get_connected_device_names()
        # The "active" profile is whichever ProfileManager resolves right
        # now — an avatar profile bound to the current VRChat avatar, or
        # the selected global profile as a fallback.
        active_profile = controller.profile_manager.get_active_profile_dict() or {}
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


# ============================================================
# Slider / progress wrappers that accept floats 0.0-1.0 like CTk.
# ============================================================

class _SliderProxy:
    def __init__(self, slider: QSlider):
        self._slider = slider

    def set(self, value: float):
        v = max(0, min(1000, int(round(float(value) * 1000))))
        # blockSignals so programmatic updates don't echo back through the controller.
        self._slider.blockSignals(True)
        self._slider.setValue(v)
        self._slider.blockSignals(False)

    def get(self) -> float:
        return self._slider.value() / 1000.0


class _ProgressProxy:
    def __init__(self, bar: QProgressBar):
        self._bar = bar

    def set(self, value: float):
        v = max(0, min(1000, int(round(float(value) * 1000))))
        self._bar.setValue(v)

    def get(self) -> float:
        return self._bar.value() / 1000.0


def _truncate(text: str, max_chars: int) -> str:
    """Return text shortened to `max_chars` with an ellipsis."""
    if text is None:
        return ""
    text = str(text)
    if len(text) <= max_chars:
        return text
    return text[: max(0, max_chars - 1)] + "…"


def _html_escape(s: str) -> str:
    return (
        s.replace("&", "&amp;")
         .replace("<", "&lt;")
         .replace(">", "&gt;")
         .replace(" ", "&nbsp;")
    )
