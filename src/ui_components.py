# OscGoesPurrr - UI Components Module (PySide6)
#
# Pure View layer. The controller talks to this class through a fixed facade
# (set_title, schedule_callback, run, update_*, etc.). Swapping toolkits
# means rewriting this file plus the `ui/` subpackage (widgets, icons,
# layout helpers) — and nothing else.

from typing import List, Optional, Dict, Any, Callable
import math
import os
import re
import sys
import time

from PySide6.QtCore import (
    Qt, QThread, QTimer, Signal, QObject, QEvent, QSize, QPointF, QRect, QRectF
)
from PySide6.QtGui import (
    QFont, QColor, QTextCharFormat, QTextCursor, QIcon, QLinearGradient,
    QPixmap, QPainter, QPen, QBrush, QPainterPath, QPolygonF, QPalette
)
from PySide6.QtWidgets import (
    QStatusBar,
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QLabel, QPushButton, QCheckBox, QLineEdit, QSlider, QProgressBar,
    QFrame, QScrollArea, QTextEdit, QPlainTextEdit, QSizePolicy, QSpacerItem,
    QDialog, QMessageBox, QTreeWidget, QTreeWidgetItem, QHeaderView,
    QButtonGroup, QStackedWidget, QTableWidget, QTableWidgetItem,
    QAbstractItemView, QComboBox, QSpinBox, QDoubleSpinBox, QToolButton,
)
from ui import lovense_icons as _lovense_icons

from constants import *
import constants as _constants
from parameter_store import store
from utilities import (
    apply_window_frame_colors as _apply_window_frame_colors,
    strip_param_prefix,
)

# Helper widgets, icons, layout utilities, text/geometry helpers extracted
# into the `ui` package. Aliased here to keep the old private names the
# rest of this file references (`_vbox`, `_icon_*`, `_Card`, etc.).
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
    icon_home as _icon_home,
)
from ui.widgets import (
    ToggleSwitch,
    Invoker as _Invoker,
    MainWindow as _MainWindow,
    Card as _Card,
    Canvas as _Canvas,
    SliderProxy as _SliderProxy,
    ProgressProxy as _ProgressProxy,
    RainbowMeter as _RainbowMeter,
    install_rainbow_scrollbars as _install_rainbow_scrollbars,
)
from ui.live_theme import LiveTheme as _LiveTheme

# View mixins extracted from this file (see step 4 of the structural
# refactor). Each mixin owns a coherent slice of the UI; this class
# composes them so external code keeps calling OscGoesPurrrUI(...).
from ui import theme as _theme
from version import __version__ as _APP_VERSION, build_number as _build_number
from ui.views.dashboard import DashboardMixin
from ui.views.diagnostics import DiagnosticsMixin
from ui.views.settings import SettingsMixin
from ui.views.sessions import SessionsMixin
from ui.views.device_frame import DeviceFrameMixin
from ui.views.home import HomeMixin
from ui.views.sps_sources import SpsSourcesMixin
from ui.views.statistics import StatisticsMixin
from ui.views.whats_new import WhatsNewMixin


# ============================================================
# Global QSS — built from the 518 tokens in ui/theme.py
# ============================================================

GLOBAL_QSS = _theme.build_qss()


# ============================================================
# OscGoesPurrrUI — the PySide6 view layer
# ============================================================

class _StatusLabel(QLabel):
    """Status-bar message: keeps the full text and elides from the right
    against its CURRENT width, so a message set before layout settles is
    not stuck short."""

    def __init__(self, parent=None):
        super().__init__("", parent)
        self._full = ""
        pol = self.sizePolicy()
        pol.setHorizontalPolicy(QSizePolicy.Ignored)
        self.setSizePolicy(pol)

    def set_full_text(self, text: str) -> None:
        self._full = text
        self._apply()

    def resizeEvent(self, ev) -> None:
        super().resizeEvent(ev)
        self._apply()

    def _apply(self) -> None:
        avail = max(40, self.width() - 4)
        self.setText(self.fontMetrics().elidedText(self._full, Qt.ElideRight, avail))


class _LiveTipLabel(QLabel):
    """A label whose tooltip is put together at the moment it is asked
    for, so it can carry live numbers without anything refreshing it."""

    def __init__(self, text: str = "", parent=None):
        super().__init__(text, parent)
        self.tip_fn: Optional[Callable[[], str]] = None

    def event(self, ev) -> bool:
        if ev.type() == QEvent.ToolTip and self.tip_fn is not None:
            try:
                self.setToolTip(self.tip_fn())
            except Exception:
                pass
        return super().event(ev)


class OscGoesPurrrUI(
    DashboardMixin,
    DiagnosticsMixin,
    SettingsMixin,
    SessionsMixin,
    DeviceFrameMixin,
    HomeMixin,
    SpsSourcesMixin,
    StatisticsMixin,
    WhatsNewMixin,
):
    """UI Component class — handles all GUI rendering and updates."""

    # ----------------------------------------------------------
    # Construction
    # ----------------------------------------------------------

    def __init__(self, controller, app_root=None):
        self.controller = controller

        # Bootstrap QApplication (singleton — re-use if one already exists).
        self.qapp: QApplication = QApplication.instance() or QApplication(sys.argv)
        if sys.platform.startswith("linux"):
            # Wayland docks find the window's icon through the .desktop file
            # of this name — the one the AppImage carries.
            self.qapp.setDesktopFileName(APP_NAME)
        _theme.install_fonts()
        self.qapp.setStyleSheet(GLOBAL_QSS)
        # Rich-text links (update notice, update window) in the accent, not
        # Qt's default blue — the stylesheet cannot reach them, the palette can.
        pal = self.qapp.palette()
        for role in (QPalette.Link, QPalette.LinkVisited):
            pal.setColor(role, QColor(_theme.CHROME["accent"]))
        self.qapp.setPalette(pal)

        # Main window (intercepts X-button close).
        self.window: _MainWindow = _MainWindow()
        self.window.setObjectName("root")
        # Explicit small minimum so the user can resize the window down — the
        # sidebar is fixed at SIDEBAR_WIDTH so we keep at least that plus a
        # bit of breathing room for the scrollable content area.
        self.window.setMinimumSize(SIDEBAR_WIDTH + 200, 360)
        self.window.resize(1100, 700)
        self.window.set_activate_handler(self._on_window_activated)
        # The colour picker's engine: the app-level stylesheet above is set
        # once and never again; a colour change is swept through the
        # sections registered with this, a slice per event-loop turn.
        self.live_theme = _LiveTheme(self.window)
        self.live_theme.on_change(self._after_colour_change)
        # Dialogs and message boxes are parented to this (invisible, zero
        # size) section instead of the window, so they open in the colour
        # in use rather than the one the app was launched with.
        self.dialog_parent = QWidget(self.window)
        self.dialog_parent.setFixedSize(0, 0)
        self.live_theme.add_root(self.dialog_parent)

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
        self.intiface_sidebar_section: Optional[QWidget] = None

        # Settings checkboxes (referenced by facade getters)
        self.auto_connect_var: Optional[QCheckBox] = None
        self.auto_refresh_var: Optional[QCheckBox] = None
        self.osc_auto_connect_var: Optional[QCheckBox] = None

        # Home's toy list
        self.devices_container_frame: Optional[QFrame] = None
        self.unified_devices_frame: Optional[QWidget] = None
        self.unified_devices_layout: Optional[QVBoxLayout] = None

        # Network & debug view
        self.sps_status_label: Optional[QLabel] = None
        self.osc_debugger_button: Optional[QPushButton] = None
        self.osc_search_entry: Optional[QLineEdit] = None
        self.debugger_table: Optional[QTableWidget] = None

        # System log
        self.log_text: Optional[QTextEdit] = None

        # Sidebar mode buttons, built by _build_mode_grid and repainted in
        # place by _refresh_mode_buttons whenever the active mode or its
        # metadata change.
        self.mode_grid_buttons: Optional[list] = None

        # Build the UI tree.
        self.setup_ui()

        # The 518 shell's bottom status bar: what just happened on the
        # left, the identity tag on the right.
        self._build_status_bar()

    # ----------------------------------------------------------
    # Top-level layout
    # ----------------------------------------------------------

    def setup_ui(self):
        # Painted, not styled: every section sits inside it (ui.widgets.Canvas).
        root = _Canvas()
        root.setObjectName("root")
        self._root_widget = root
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
        self.live_theme.add_root(sidebar_scroll)

        # Main content area (stacked views). Each page sits inside its own
        # QScrollArea so the window can shrink below the page's natural size
        # without Qt locking the central widget. Form-style pages also get a
        # max-width cap so they hug the left side on wide monitors instead of
        # stretching buttons across 4K — data-heavy pages (tables, logs,
        # the toy list) stay full-width.
        self.main_stack = QStackedWidget()
        # Global replay banner — a thin colored strip pinned above the
        # stacked views, shown whenever a session replay is active so the
        # user never forgets live OSC input is paused (see
        # set_replay_banner). Hidden by default; wrapping the stack in a
        # vertical container is the least-disruptive place to hang it.
        main_content = QWidget()
        main_content_lay = _vbox(0, 0)
        main_content.setLayout(main_content_lay)
        self.replay_banner_label = QLabel("")
        self.replay_banner_label.setObjectName("replayBanner")
        self.replay_banner_label.setAlignment(Qt.AlignCenter)
        self.replay_banner_label.setVisible(False)
        self.replay_banner_label.setStyleSheet(
            f"background: {COLOR_WARNING}; color: #101010; "
            f"font-weight: bold; padding: 6px; border-radius: 4px;"
        )
        main_content_lay.addWidget(self.replay_banner_label)
        main_content_lay.addWidget(self.main_stack, 1)
        root_layout.addWidget(main_content, 1)

        view_names = ["Home", "Statistics",
                      "SPS Sources",
                      "OSC Inspector", "OSC Diagnostics", "System Log",
                      "Settings", "Help"]
        builders = {
            "Home": self._build_home_view,
            "Statistics": self._build_statistics_view,
            "SPS Sources": self._build_sps_sources_view,
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
            # One section per page -- except those that register finer
            # ones themselves: Home (a toy's bar, a motor's block: its
            # page holds every toy), Settings (card by card, where the
            # colour is picked) and Help (card by card: long texts).
            if name not in ("Home", "Settings", "Help"):
                self.live_theme.add_root(wrapper)

        self.window.setCentralWidget(root)
        self._stretch_section_titles(root)


        # Hide feature-gated pages (and the Intiface block when that feature
        # is off), then open on Home -- every launch, whatever page was open
        # last time. It is the one page that shows the whole rig at a
        # glance, and where every toy is set up.
        self.apply_feature_visibility()
        self.select_view("Home")

    @staticmethod
    def _stretch_section_titles(root: QWidget) -> None:
        """Section titles are filled header bars (FFMPEG Studio's category
        bars). A title that shares a row with a help badge or a button was
        built as `[title][badge][stretch]`, which leaves the bar hugging
        its text; give the title the row's slack instead so every bar
        spans its card and the trailing controls sit at the right edge."""
        def owning_hbox(layout, widget):
            """The QHBoxLayout that directly holds `widget`, searching
            nested layouts (header rows are often a sub-layout of the
            card's vbox rather than a layout on their own widget)."""
            if layout is None:
                return None
            if isinstance(layout, QHBoxLayout) and layout.indexOf(widget) >= 0:
                return layout
            for i in range(layout.count()):
                item = layout.itemAt(i)
                sub = item.layout() if item is not None else None
                if sub is not None:
                    found = owning_hbox(sub, widget)
                    if found is not None:
                        return found
            return None

        for lbl in root.findChildren(QLabel, "sectionTitle"):
            parent = lbl.parentWidget()
            lay = owning_hbox(parent.layout() if parent is not None else None, lbl)
            if lay is None:
                continue
            for i in range(lay.count() - 1, -1, -1):
                item = lay.itemAt(i)
                if item is not None and item.spacerItem() is not None:
                    lay.removeItem(item)
            lay.setStretchFactor(lbl, 1)
            pol = lbl.sizePolicy()
            pol.setVerticalPolicy(QSizePolicy.Fixed)   # 27px bar, not the row's tallest
            lbl.setSizePolicy(pol)
            lay.setAlignment(lbl, Qt.AlignVCenter)

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
    # 518 shell: status bar
    # ----------------------------------------------------------

    def _build_status_bar(self) -> None:
        """Bottom status bar: `what just happened` on the left (the newest
        log line, elided), the identity tag on the right. Both zones are
        dim 11px; only `Blise518B` carries the accent."""
        bar = QStatusBar()
        bar.setSizeGripEnabled(False)
        self.status_message_label = _StatusLabel()
        self.status_message_label.setObjectName("statusMessage")
        bar.addWidget(self.status_message_label, 1)
        tag = QLabel(_theme.status_tag_html(
            getattr(_constants, "APP_NAME", "OscGoesPurrr"), _APP_VERSION))
        tag.setObjectName("statusTag")
        tag.setTextFormat(Qt.RichText)
        bar.addPermanentWidget(tag)
        self.window.setStatusBar(bar)
        self.live_theme.add_root(bar)
        self._status_message_full = ""

    def set_status_message(self, text: str) -> None:
        """Left zone of the status bar. One line; elided from the right."""
        lbl = getattr(self, "status_message_label", None)
        if lbl is None:
            return
        text = " ".join(str(text).split())
        self._status_message_full = text
        lbl.set_full_text(text)

    # ----------------------------------------------------------
    # Sidebar
    # ----------------------------------------------------------

    # What each page is for, shown when you rest the mouse on its entry.
    _NAV_TIPS = {
        "Home": "Your toys, live: what's connected, battery and output at "
                "a glance, with Test and Mute. Click a toy to set up which "
                "parts of your avatar drive it and how each motor responds.",
        "Statistics": "Your sessions with a timeline for each, lifetime "
                      "totals and fun facts, and when you play.",
        "SPS Sources": "Build your own contact zones out of raw VRChat "
                       "contact receivers, for spots the standard SPS "
                       "zones don't cover.",
        "OSC Inspector": "Every parameter your avatar is sending, live — "
                         "for finding a parameter's exact name.",
        "OSC Diagnostics": "Connection internals: which path the data takes, "
                           "packet counts, errors. For troubleshooting.",
        "System Log": "Everything the app has reported this session.",
        "Settings": "Connections, appearance, updates, settings backups and "
                    "session recording.",
        "Help": "The manual: how modes, signal chains and the rest fit "
                "together.",
    }

    def _build_sidebar(self) -> QFrame:
        sidebar = QFrame()
        sidebar.setObjectName("sidebar")
        # Tight spacing (3px) so the nav list + both connection panels fit
        # without a scroll area.
        lay = _vbox(10, 3)
        sidebar.setLayout(lay)

        # 518 headline: Aldrich title top-left, the version/build tag in
        # dim under it. (No Neon/Midnight toggle beside it: the mode is a
        # set-once choice and lives in Settings → Appearance.)
        head = QWidget()
        hl = _hbox(0, 6)
        head.setLayout(hl)
        title = QLabel("OscGoesPurrr")
        title.setObjectName("sidebarTitle")
        # The app name is a way home too, like a site's logo.
        title.setCursor(Qt.PointingHandCursor)
        title.mousePressEvent = lambda _ev: self.select_view("Home")
        hl.addWidget(title)
        hl.addStretch(1)
        lay.addSpacing(4)
        lay.addWidget(head)
        build_tag = QLabel(_theme.title_tag(_APP_VERSION, _build_number()))
        build_tag.setObjectName("buildTag")
        lay.addWidget(build_tag)
        lay.addSpacing(10)

        # Sidebar control block — the four routing modes, the global
        # strength slider and the Off / Sleep toggles, one tap from
        # anywhere. Kept compact on purpose: the sidebar has no scroll
        # area, so every extra pixel here squeezes the nav.
        lay.addWidget(self._build_mode_grid())
        lay.addSpacing(8)

        # Home is the landing page -- where the app opens and where the
        # toys are -- so it is the one entry that is framed, larger and
        # has an icon. The rest follow in the order they are reached for:
        # the everyday pages, the tools for digging into OSC, then
        # Settings and Help.
        def nav_button(name: str, role: str = "nav") -> QPushButton:
            btn = QPushButton(name)
            btn.setProperty("role", role)
            btn.setProperty("active", "false")
            btn.setCursor(Qt.PointingHandCursor)
            btn.clicked.connect(lambda _=False, n=name: self.select_view(n))
            if name in self._NAV_TIPS:
                self._explain(btn, name, self._NAV_TIPS[name])
            lay.addWidget(btn)
            self.nav_buttons[name] = btn
            return btn

        home = nav_button("Home", role="navHome")
        home.setIcon(_icon_home(COLOR_ACCENT))
        home.setIconSize(QSize(20, 20))
        # Drawn into a pixmap, so the colour picker has to redraw it.
        self.live_theme.on_change(
            lambda: home.setIcon(_icon_home(COLOR_ACCENT)))
        lay.addSpacing(2)
        for name in ("Statistics",):
            nav_button(name)
        # The same break before each of the two lower groups; the TOOLS
        # label sits tight above the group it names.
        lay.addSpacing(self._NAV_GROUP_GAP)
        tools = QLabel("TOOLS")
        tools.setObjectName("navGroup")
        lay.addWidget(tools)
        for name in ("SPS Sources", "OSC Inspector", "OSC Diagnostics",
                     "System Log"):
            nav_button(name)
        lay.addSpacing(self._NAV_GROUP_GAP)
        for name in ("Settings", "Help"):
            nav_button(name)

        # Stretch pushes the bottom section down
        lay.addStretch(1)

        # ===== Bottom status / connection block =====
        # Both links connect, reconnect and recover on their own, so each is
        # one quiet line: its name and the live status pill. A button shows
        # only when it has something to do -- Connect while a link is down
        # and nothing will bring it up by itself, Find toys while the toy
        # server is up. There is no Disconnect (quit the app, or use Off)
        # and no VRChat refresh (a silent link re-handshakes itself; the
        # manual buttons live on OSC Diagnostics).
        sep = QFrame()
        sep.setObjectName("separator")
        lay.addWidget(sep)
        lay.addSpacing(6)

        # --- VRChat OSC ---
        self.osc_status_label = _LiveTipLabel("DISCONNECTED")
        self.osc_status_label.setProperty("role", "pill")
        self.osc_status_label.setProperty("tone", "off")
        self.osc_status_label.setAlignment(Qt.AlignCenter)
        # The listening port, the packet count and the avatar ride in the
        # pill's tooltip (see _osc_pill_tip) instead of dedicated label
        # rows, to keep the sidebar compact. osc_port_label stays None.
        self._osc_pill_base_tip = "Listening on Port: --"
        self.osc_status_label.setToolTip(self._osc_pill_base_tip)
        self.osc_status_label.tip_fn = self._osc_pill_tip
        lay.addWidget(self._sidebar_link_row(
            "VRChat", self.osc_status_label,
            "VRChat OSC",
            "The link to VRChat's OSC bus — where every avatar contact "
            "signal comes from. The app waits for VRChat to appear "
            "(mDNS/OSCQuery discovery) before binding a port; hover the "
            "pill for the live port. A link that says connected but goes "
            "silent re-handshakes by itself within a minute; OSC "
            "Diagnostics has the manual buttons."
        ))

        # Only there while the app is NOT listening for VRChat -- auto
        # connect switched off in Settings, or the listener stopped.
        self.osc_connection_button = QPushButton("Connect")
        self.osc_connection_button.clicked.connect(self.controller.toggle_osc_connection)
        self._explain(
            self.osc_connection_button, "Connect to VRChat",
            "Starts listening for VRChat. You only see this while the app "
            "isn't listening by itself — with \"Auto Connect (VRChat OSC)\" "
            "switched off in Settings, or after the link stopped.")
        self._osc_connect_row = self._sidebar_link_buttons(
            self.osc_connection_button)
        self._osc_connect_row.setVisible(False)
        lay.addWidget(self._osc_connect_row)
        lay.addSpacing(4)

        # --- Intiface ---
        # Wrapped in a container so the whole block hides cleanly when the
        # Intiface feature is off.
        self.intiface_sidebar_section = QWidget()
        intiface_lay = _vbox(0, 3)
        self.intiface_sidebar_section.setLayout(intiface_lay)

        self.status_label = QLabel("DISCONNECTED")
        self.status_label.setProperty("role", "pill")
        self.status_label.setProperty("tone", "off")
        self.status_label.setAlignment(Qt.AlignCenter)
        intiface_lay.addWidget(self._sidebar_link_row(
            "Intiface", self.status_label,
            "Intiface",
            "The Buttplug.io server that talks to your Bluetooth toys. "
            "OscGoesPurrr runs its own copy, so there is nothing else to "
            "start. (To use a separately running Intiface Central "
            "instead, switch off the built-in engine in Settings.) It "
            "connects and reconnects by itself."
        ))

        # One button slot, mostly empty: Connect while the toy server is
        # down (normally a moment at launch; longer with auto connect off
        # or the engine missing); Find toys only with Auto Refresh Devices
        # off -- otherwise the app looks by itself (refresh_link_buttons).
        self.connection_button = QPushButton("Connect")
        self.connection_button.clicked.connect(self.controller.connect_to_intiface)
        self._explain(
            self.connection_button, "Connect to the toy server",
            "Normally automatic: the app starts its toy server and connects "
            "on launch, and reconnects if the link drops. You only need "
            "this with \"Auto Connect (Intiface)\" switched off in Settings, "
            "or after a failed start.")

        # A manual scan for toys powered on after connecting -- the stand-in
        # for the automatic search, so it is only offered while that is
        # switched off.
        self.scan_toys_button = QPushButton("Find toys")
        self._explain(
            self.scan_toys_button, "Find toys",
            "Looks for toys right now. You only see this with \"Auto "
            "Refresh Devices\" switched off in Settings — otherwise the app "
            "looks by itself.")
        self.scan_toys_button.setVisible(False)
        self.scan_toys_button.clicked.connect(self.controller.scan_for_toys)
        self._toy_buttons_row = self._sidebar_link_buttons(
            self.connection_button, self.scan_toys_button)
        intiface_lay.addWidget(self._toy_buttons_row)
        intiface_lay.addSpacing(4)

        lay.addWidget(self.intiface_sidebar_section)

        return sidebar

    def _sidebar_link_row(self, text: str, pill: QLabel, help_title: str,
                          help_text: str) -> QWidget:
        """`Name ........ [STATUS]` -- a link's name and its live status pill
        on one line. The name explains the link on hover."""
        row = QWidget()
        rl = _hbox(0, 6)
        rl.setContentsMargins(2, 0, 0, 0)
        row.setLayout(rl)
        title = QLabel(text)
        title.setObjectName("sidebarLinkTitle")
        self._explain(title, help_title, help_text)
        rl.addWidget(title)
        rl.addStretch(1)
        rl.addWidget(pill, 0, Qt.AlignVCenter)
        return row

    def _sidebar_link_buttons(self, *buttons: QPushButton) -> QWidget:
        """A link's rarely-needed buttons: small, quiet, sharing one row."""
        row = QWidget()
        rl = _hbox(0, 4)
        row.setLayout(rl)
        for btn in buttons:
            btn.setProperty("role", "sideSmall")
            btn.setFixedHeight(self._SIDEBAR_LINK_BTN_H)
            btn.setCursor(Qt.PointingHandCursor)
            rl.addWidget(btn, 1)
        return row

    _SIDEBAR_LINK_BTN_H = 26
    _NAV_GROUP_GAP = 10

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
        arrival_refreshers = {
            "Home": ("_refresh_home_dynamic",),
            "Statistics": ("_refresh_statistics_view",),
            "Settings": ("_refresh_sessions_view",
                         "_repopulate_replay_sessions"),
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
    # Global replay banner
    # ----------------------------------------------------------

    def set_replay_banner(self, active: bool, text: str = "") -> None:
        """Show or hide the global replay indicator strip above the main
        content. Called from refresh_replay_status(). Guarded for early
        startup — the label may not exist yet."""
        lbl = getattr(self, "replay_banner_label", None)
        if lbl is None:
            return
        try:
            if active:
                lbl.setText(text or "▶ REPLAY — live OSC paused")
                lbl.setVisible(True)
            else:
                lbl.setVisible(False)
        except RuntimeError:
            pass

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
        self.set_status_message(message)
        if self.log_text is not None:
            self.log_text.append(f"> {message}")
            sb = self.log_text.verticalScrollBar()
            sb.setValue(sb.maximum())

    # ----------------------------------------------------------
    # Connection status displays
    # ----------------------------------------------------------

    def _on_window_activated(self) -> None:
        """The user brought the window to the front. If a toy is missing
        they are probably waiting for it, so ask for the fast search -- the
        controller only acts on it while no toy is connected."""
        note = getattr(self.controller, "note_toy_search_wanted", None)
        if callable(note):
            note()

    def _after_colour_change(self) -> None:
        """The colour picker changed the tokens. Two things are neither a
        stylesheet nor a stored colour: rich-text links take theirs from
        the application palette (cheap to set -- unlike the app's
        stylesheet, it re-styles nothing), and the no-battery glyphs are
        pixmaps drawn in the text colour, which carries a trace of the
        accent's hue."""
        pal = self.qapp.palette()
        for role in (QPalette.Link, QPalette.LinkVisited):
            pal.setColor(role, QColor(_theme.CHROME["accent"]))
        self.qapp.setPalette(pal)
        for data in self.device_ui_frames.values():
            label = data.get("battery_label")
            try:
                if label is not None and not label.text():
                    self._show_no_battery_glyph(label)
            except RuntimeError:
                pass          # card rebuilt meanwhile

    def refresh_link_buttons(self) -> None:
        """Show each sidebar button only while it has something to do:
        Connect while the toy server is down; Find toys while it is up AND
        the app is not looking by itself (Auto Refresh Devices off)."""
        connected = bool(getattr(self, "_toy_server_connected", False))
        try:
            auto = bool(self.controller.get_app_setting("auto_refresh", True))
        except Exception:
            auto = True
        show_connect, show_find = not connected, connected and not auto
        if self.connection_button is not None:
            self.connection_button.setVisible(show_connect)
        if self.scan_toys_button is not None:
            self.scan_toys_button.setVisible(show_find)
        row = getattr(self, "_toy_buttons_row", None)
        if row is not None:
            row.setVisible(show_connect or show_find)

    def update_connection_status(self, connected: bool, server: str):
        # Sync haptic engine flag through the controller facade
        # (preserves prior behaviour without holding a reference to the engine).
        if hasattr(self.controller, 'set_haptic_connected'):
            self.controller.set_haptic_connected(connected)

        self._toy_server_connected = bool(connected)
        self.refresh_link_buttons()

        if self.status_label is not None:
            self.status_label.setProperty("role", "pill")
            if connected:
                self.status_label.setText("CONNECTED")
                self.status_label.setProperty("tone", "ok")
            else:
                self.status_label.setText("DISCONNECTED")
                self.status_label.setProperty("tone", "off")
            self._repolish(self.status_label)

        self.update_stored_devices_ui()

    def update_osc_status(self, is_connected: bool, port: int = None):
        """Legacy two-state entry point (connect/disconnect events). A fresh
        handshake paints "NO DATA", not "CONNECTED" — the liveness poller
        (main._refresh_debugger_ui_body) upgrades to green within a tick
        once packets are really arriving."""
        self.update_osc_link_state("waiting" if is_connected else "disconnected", port)

    #: Pill face per link state (osc_link_state module): text, tone, tooltip.
    _OSC_LINK_FACES = {
        "disconnected": ("DISCONNECTED", "off",
                         "Listening on Port: --"),
        "waiting": ("NO DATA", "warn",
                    "Handshake OK, but no OSC packets are arriving on port "
                    "{port}. VRChat's discovery has likely failed (its mDNS "
                    "listener dies mid-session) — the 518 router fallback "
                    "will carry the stream if the router is running."),
        "live": ("CONNECTED", "ok",
                 "Receiving live OSC from VRChat on port {port}."),
        "live_router": ("CONNECTED (518)", "ok",
                        "Receiving live OSC on port {port} via the OSC "
                        "Router 518 fallback — VRChat's direct push is down. "
                        "Direct is retried automatically every 5 min (it has "
                        "less latency); the pill switches to plain CONNECTED "
                        "the moment VRChat delivers directly again."),
    }

    #: Not connected, but the app is up and looking for VRChat: nothing for
    #: the user to press, so the pill says what it is waiting for.
    _OSC_SEARCHING_FACE = (
        "SEARCHING", "off",
        "Looking for VRChat. Start VRChat with OSC turned on (Action menu "
        "→ Options → OSC) and it connects by itself.")

    def update_osc_link_state(self, state: str, port: int = None,
                              listening: Optional[bool] = None):
        """Four-state truthful status pill. Yellow means exactly 'handshake
        but no data' — the failure that used to masquerade as CONNECTED.

        `listening` is whether the app is up and looking for VRChat by
        itself. Only when it is not (auto connect off, listener stopped)
        does the Connect button appear; callers that don't know leave it
        None and any state but 'disconnected' counts as listening."""
        if self.osc_status_label is None:
            return
        if listening is None:
            listening = state != "disconnected"
        if state == "disconnected" and listening:
            text, tone, tooltip = self._OSC_SEARCHING_FACE
        else:
            text, tone, tooltip = self._OSC_LINK_FACES.get(
                state, self._OSC_LINK_FACES["disconnected"])
        self.osc_status_label.setProperty("role", "pill")
        self.osc_status_label.setText(text)
        self.osc_status_label.setProperty("tone", tone)
        self._osc_pill_base_tip = tooltip.format(port=port or "--")
        self.osc_status_label.setToolTip(self._osc_pill_base_tip)
        row = getattr(self, "_osc_connect_row", None)
        if row is not None:
            row.setVisible(not listening)
        self._repolish(self.osc_status_label)

    def _osc_pill_tip(self) -> str:
        """The VRChat pill's tooltip, composed on hover: what the link
        state means, then the live packet count and the avatar VRChat
        last reported."""
        lines = [getattr(self, "_osc_pill_base_tip", "")]
        try:
            snap = self.controller.get_osc_status_snapshot() or {}
            lines.append(f"Packets received: {int(snap.get('packets', 0)):,}")
        except Exception:
            pass
        try:
            avatar = self.controller.get_current_avatar_id() or ""
        except Exception:
            avatar = ""
        lines.append("Avatar: " + (_html_escape(avatar) if avatar
                                   else "none reported yet"))
        return "<br>".join(line for line in lines if line)

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

    def minimize_window(self) -> None:
        self.window.showMinimized()

    # --- Tray icon (Linux). Windows keeps the controller's pystray icon;
    # --- pystray's Linux backends need GTK bindings or an X11 tray, and
    # --- Qt's speaks the StatusNotifier protocol KDE and GNOME's
    # --- AppIndicator extension use. Callbacks run on the GUI thread.

    def show_tray_icon(self, png: bytes, tooltip: str,
                       on_restore: Callable[[], None],
                       on_quit: Callable[[], None]) -> bool:
        """Show a tray icon (PNG bytes) with Show / Quit. False, changing
        nothing, when the desktop has no tray to show it in."""
        from PySide6.QtWidgets import QMenu, QSystemTrayIcon
        if not QSystemTrayIcon.isSystemTrayAvailable():
            return False
        if getattr(self, "_tray", None) is None:
            tray = QSystemTrayIcon(self.window)
            menu = QMenu()
            menu.addAction(f"Show {APP_NAME}",
                           lambda: self._tray_callback("restore"))
            menu.addAction("Quit", lambda: self._tray_callback("quit"))
            tray.setContextMenu(menu)
            tray.activated.connect(self._on_tray_activated)
            self._tray, self._tray_menu = tray, menu
        self._tray_callbacks = {"restore": on_restore, "quit": on_quit}
        self.set_tray_icon(png)
        self._tray.setToolTip(tooltip)
        self._tray.show()
        return True

    def set_tray_icon(self, png: bytes) -> None:
        tray = getattr(self, "_tray", None)
        if tray is None:
            return
        pixmap = QPixmap()
        if pixmap.loadFromData(png, "PNG"):
            tray.setIcon(QIcon(pixmap))

    def hide_tray_icon(self) -> None:
        tray = getattr(self, "_tray", None)
        if tray is not None:
            tray.hide()

    def _on_tray_activated(self, reason) -> None:
        from PySide6.QtWidgets import QSystemTrayIcon
        if reason in (QSystemTrayIcon.ActivationReason.Trigger,
                      QSystemTrayIcon.ActivationReason.DoubleClick):
            self._tray_callback("restore")

    def _tray_callback(self, which: str) -> None:
        callback = getattr(self, "_tray_callbacks", {}).get(which)
        if callable(callback):
            callback()

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
