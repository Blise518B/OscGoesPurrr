"""Settings page and Help page.

Mixin for ui_components.OscGoesPurrrUI. Relies on attributes initialised
by OscGoesPurrrUI.__init__ (self.controller, self.invoker, etc.)."""

from typing import List, Optional, Dict, Any, Callable
import os
import sys
import time

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
    QColorDialog,
)
from ui import lovense_icons as _lovense_icons

from constants import *
from parameter_store import store
from utilities import strip_param_prefix

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
from ui import theme as _theme
from ui.widgets import (
    ToggleSwitch,
    Invoker as _Invoker,
    MainWindow as _MainWindow,
    Card as _Card,
    SliderProxy as _SliderProxy,
    ProgressProxy as _ProgressProxy,
    RainbowMeter as _RainbowMeter,
    install_rainbow_scrollbars as _install_rainbow_scrollbars,
)


class SettingsMixin:

    # ----------------------------------------------------------
    # Settings view
    # ----------------------------------------------------------

    # Flags with no row yet. The OSC Router 518 fallback ships switched on
    # (a silent no-op when no router runs), but the router itself isn't
    # public yet, so the app doesn't offer or mention it until it is.
    _HIDDEN_FEATURES = frozenset({"feature_osc_router_518"})

    # What switching each feature off actually does.
    _FEATURE_TIPS = {
        "feature_intiface":
            "Everything to do with toys. Off: the app stops talking to "
            "the toy server and hides Device Routing — only useful if "
            "you run the app purely to drive avatar parameters.",
        "feature_osc_router_518":
            "After a few hours VRChat can stop announcing itself to new OSC "
            "apps. With this on, the app automatically listens through a "
            "local OSC Router 518 when that happens, and switches back when "
            "VRChat recovers. Harmless if you don't run the router.",
        "feature_osc_inspector":
            "The OSC Inspector page, which lists every parameter your "
            "avatar sends. Off: the page is hidden and stops its work.",
    }

    def _build_settings_view(self, parent_layout: QVBoxLayout):
        title = QLabel("Application Settings")
        title.setObjectName("viewTitle")
        title.setAlignment(Qt.AlignHCenter)
        parent_layout.addWidget(title)

        # Two tabs: the existing settings cards live under "General"
        # unchanged; the session-logger UI lives under "Sessions". Same
        # rebinding trick as the other views — `parent_layout` is
        # repointed at the General tab's layout so the existing
        # parent_layout.addWidget(...) calls below keep working without
        # any rename.
        from PySide6.QtWidgets import QTabWidget as _QTabWidget
        tabs = _QTabWidget()
        general_tab = QWidget()
        general_lay = _vbox(0, 8)
        general_tab.setLayout(general_lay)
        sessions_tab = QWidget()
        sessions_lay = _vbox(0, 8)
        sessions_tab.setLayout(sessions_lay)
        tabs.addTab(general_tab, "General")
        tabs.addTab(sessions_tab, "Sessions")
        parent_layout.addWidget(tabs)

        # SessionsMixin renders the Sessions tab content; General keeps
        # the original card stack.
        self._build_sessions_panel(sessions_lay)
        parent_layout = general_lay

        # ---- Modes Card ----
        # The per-avatar memory used to sit on the Dashboard's Modes card.
        # The modes themselves live in the sidebar; this is set-and-forget,
        # so it lives here.
        modes_card = _Card()
        modes_lay = _vbox(20, 6)
        modes_card.setLayout(modes_lay)
        hdr = QLabel("Modes")
        hdr.setObjectName("sectionTitle")
        modes_lay.addWidget(hdr)
        self.avatar_modes_toggle = ToggleSwitch("Remember mode per avatar")
        self.avatar_modes_toggle.setChecked(
            bool(self.controller.get_app_setting("avatar_modes_enabled", False))
        )
        self.avatar_modes_toggle.toggled.connect(
            lambda checked: self.controller.set_app_setting(
                "avatar_modes_enabled", bool(checked))
        )
        modes_lay.addWidget(self.avatar_modes_toggle)
        self._explain(
            self.avatar_modes_toggle,
            "Remember mode per avatar",
            "When ON, each avatar switches back to the mode it last used "
            "as it loads — handy when your avatars have different "
            "socket layouts. When OFF, the current mode simply carries "
            "across avatar changes.",
        )
        parent_layout.addWidget(modes_card)

        # ---- Network Bind Card ----
        net_card = _Card()
        net_lay = _vbox(20, 6)
        net_card.setLayout(net_lay)

        hdr = QLabel("OSC Network Bind")
        hdr.setObjectName("sectionTitle")
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
        self._explain(switch_lay,
            "OSC network bind",
            "<b>0.0.0.0</b> listens on every network interface — required "
            "when VRChat runs on another device (e.g. a standalone "
            "headset) and the safe default on a home network. "
            "<b>127.0.0.1</b> only accepts traffic from this PC — pick it "
            "on untrusted networks when VRChat runs locally. Restart the "
            "app after changing."
        )
        switch_lay.addStretch(1)
        net_lay.addWidget(switch_row)

        warn = QLabel("* Requires application restart to apply changes.")
        warn.setProperty("role", "warning")   # a warning, not an error
        net_lay.addWidget(warn)

        parent_layout.addWidget(net_card)

        # ---- Connection Settings Card ----
        conn_card = _Card()
        conn_lay = _vbox(20, 8)
        conn_card.setLayout(conn_lay)

        hdr = QLabel("Connection Settings")
        hdr.setObjectName("sectionTitle")
        conn_lay.addWidget(hdr)

        self.auto_refresh_var = ToggleSwitch("Auto Refresh Devices")
        self.auto_refresh_var.setChecked(
            bool(self.controller.get_app_setting("auto_refresh", True))
        )
        self.auto_refresh_var.toggled.connect(
            lambda _=False: self.controller.toggle_auto_refresh()
        )
        conn_lay.addWidget(self.auto_refresh_var)
        self._explain(
            self.auto_refresh_var, "Auto refresh devices",
            "Look for newly switched-on toys every so often, so a toy you "
            "turn on later shows up by itself. Off: only the sidebar's "
            "Refresh looks for new toys.")

        self.auto_connect_var = ToggleSwitch("Auto Connect (Intiface)")
        self.auto_connect_var.setChecked(
            bool(self.controller.get_app_setting("auto_connect", True))
        )
        self.auto_connect_var.toggled.connect(
            lambda _=False: self.controller.toggle_auto_connect()
        )
        conn_lay.addWidget(self.auto_connect_var)
        self._explain(
            self.auto_connect_var, "Auto connect (Intiface)",
            "Connect to the toy server when the app starts, and keep "
            "reconnecting if the link drops. Off: connect with the "
            "sidebar's button instead.")

        self.osc_auto_connect_var = ToggleSwitch("Auto Connect (VRChat OSC)")
        self.osc_auto_connect_var.setChecked(
            bool(self.controller.get_app_setting("auto_connect_osc", True))
        )
        self.osc_auto_connect_var.toggled.connect(
            lambda _=False: self.controller.toggle_osc_auto_connect()
        )
        self._explain(
            self.osc_auto_connect_var, "Auto connect (VRChat OSC)",
            "Start listening for VRChat as soon as the app opens, and pick "
            "it up again when VRChat restarts. Off: connect with the "
            "sidebar's button instead.")
        conn_lay.addWidget(self.osc_auto_connect_var)

        parent_layout.addWidget(conn_card)

        # ---- Intiface Engine Card ----
        # How the Buttplug toy server is provided: the built-in engine we
        # bundle and launch ourselves (default — nothing else to run), or an
        # external Intiface Central the user starts separately.
        ife_card = _Card()
        ife_lay = _vbox(20, 6)
        ife_card.setLayout(ife_lay)

        hdr = QLabel("Intiface Engine")
        hdr.setObjectName("sectionTitle")
        ife_lay.addWidget(hdr)
        ife_lay.addWidget(self._muted_label(
            "Built-in mode runs a bundled Intiface engine for you, so you don't "
            "have to launch Intiface Central separately. Turn this off to "
            "connect to your own running Intiface Central instead. Changing this "
            "reconnects automatically."
        ))
        self.intiface_integrated_toggle = ToggleSwitch("Use built-in Intiface engine")
        self.intiface_integrated_toggle.setChecked(
            bool(self.controller.get_app_setting("use_integrated_intiface", True))
        )
        self.intiface_integrated_toggle.toggled.connect(
            lambda checked: self.controller.set_intiface_integrated(bool(checked))
        )
        ife_lay.addWidget(self.intiface_integrated_toggle)
        self._explain(
            self.intiface_integrated_toggle, "Built-in Intiface engine",
            "<b>On</b> (recommended): the app runs its own toy server, so "
            "there is nothing else to install or start. <b>Off</b>: connect "
            "to an Intiface Central you start yourself instead. Switching "
            "reconnects on its own.")
        parent_layout.addWidget(ife_card)

        # ---- SteamVR Card ----
        # Just for fun: connected toys appear in SteamVR's device list
        # through a small bundled driver. Off by default.
        svr_card = _Card()
        svr_lay = _vbox(20, 6)
        svr_card.setLayout(svr_lay)

        hdr = QLabel("SteamVR")
        hdr.setObjectName("sectionTitle")
        svr_lay.addWidget(hdr)
        svr_lay.addWidget(self._muted_label(
            "Show your connected toys in SteamVR's device list, with their "
            "icon and battery — just for fun. They are never used as "
            "trackers, so full-body tracking is untouched."
        ))
        try:
            svr_status = self.controller.get_steamvr_toys_status()
        except Exception:
            svr_status = {"supported": False, "enabled": False}
        self.steamvr_toys_toggle = ToggleSwitch("Show toys in SteamVR")
        self.steamvr_toys_toggle.setChecked(bool(svr_status.get("enabled")))
        self.steamvr_toys_toggle.setEnabled(bool(svr_status.get("supported")))
        self.steamvr_toys_toggle.toggled.connect(self._on_steamvr_toys_toggled)
        svr_lay.addWidget(self.steamvr_toys_toggle)
        self._explain(
            self.steamvr_toys_toggle, "Show toys in SteamVR",
            "Adds every connected toy to SteamVR's device list, next to your "
            "headset and controllers, with its icon and battery level. On by "
            "default.<br><br>"
            "It works through a small SteamVR driver the app installs itself "
            "— no admin rights, nothing inside Steam's folder. Toys are listed "
            "as devices that are never tracked, so VRChat and full-body "
            "tracking ignore them.<br><br>"
            "<b>Off</b> takes the toys out of the list and the driver out of "
            "SteamVR.")
        self.steamvr_toys_note = self._muted_label("")
        self.steamvr_toys_note.setVisible(False)
        svr_lay.addWidget(self.steamvr_toys_note)
        parent_layout.addWidget(svr_card)

        # ---- Quality of Life Card ----
        ql_card = _Card()
        ql_lay = _vbox(20, 8)
        ql_card.setLayout(ql_lay)

        hdr = QLabel("Quality of Life")
        hdr.setObjectName("sectionTitle")
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
        self._explain(
            hide_console, "Hide terminal console",
            "Hides the black text window that runs alongside the app. Turn "
            "it off only when you want to watch the raw output while "
            "troubleshooting.")

        tray = ToggleSwitch("Minimize to System Tray")
        tray.setProperty("role", "switch")
        tray.setChecked(
            bool(self.controller.get_app_setting("minimize_to_tray", False))
        )
        tray.toggled.connect(
            lambda checked: self.controller.set_app_setting("minimize_to_tray", bool(checked))
        )
        ql_lay.addWidget(tray)
        self._explain(
            tray, "Minimize to system tray",
            "Closing the window keeps the app running in the tray — "
            "its icon glows with the current output. Quit from the tray "
            "icon's menu.")

        # Routing rate — how often the router re-evaluates motor
        # targets. Time-constant math (decay / attack / release) is
        # wall-clock-based so this is purely a CPU-vs-fidelity knob;
        # changing it doesn't require re-tuning any per-channel values.
        rate_row = QWidget()
        rate_lay = _hbox(0, 8)
        rate_row.setLayout(rate_lay)
        rate_label = QLabel("Routing rate:")
        rate_lay.addWidget(rate_label)
        rate_combo = QComboBox()
        rate_presets = [
            (30, "30 Hz (lowest CPU)"),
            (60, "60 Hz"),
            (90, "90 Hz (default, headset-matched)"),
            (120, "120 Hz (high-fidelity)"),
        ]
        for hz, label in rate_presets:
            rate_combo.addItem(label, hz)
        current_hz = int(self.controller.get_app_setting("router_poll_rate_hz", 90))
        for i in range(rate_combo.count()):
            if rate_combo.itemData(i) == current_hz:
                rate_combo.setCurrentIndex(i)
                break
        rate_combo.currentIndexChanged.connect(
            lambda idx: self.controller.set_app_setting(
                "router_poll_rate_hz", int(rate_combo.itemData(idx))
            )
        )
        rate_lay.addWidget(rate_combo)
        rate_lay.addStretch(1)
        ql_lay.addWidget(rate_row)
        self._explain(
            rate_lay, "Routing rate",
            "How many times a second every motor is recalculated. 90 Hz "
            "keeps pace with most headsets; higher is smoother but uses "
            "more CPU. Your tuning feels the same at any rate.")
        ql_lay.addWidget(self._muted_label(
            "How often the router re-evaluates motors. Time constants "
            "(decay, attack, release) are wall-clock-based so changing "
            "this never requires re-tuning your channels."
        ))

        # Open the AppData folder that holds the debug / crash / engine logs,
        # so the user can grab them for troubleshooting in one click.
        logs_btn = QPushButton("📂 Open logs folder")
        logs_btn.setProperty("role", "secondary")
        logs_btn.clicked.connect(lambda _=False: self.controller.open_logs_folder())
        ql_lay.addWidget(logs_btn)
        self._explain(
            logs_btn, "Open logs folder",
            "Opens the folder with the app's log files. Zip them up if you "
            "need to report a crash or a toy that won't connect.")
        ql_lay.addWidget(self._muted_label(
            "Holds ogp_debug.log, ogp_crash.log and intiface_engine.log. Zip "
            "these if you need to report a crash or a toy that won't connect."
        ))

        # --- Update checker ---
        upd_row = QWidget()
        upd_lay = _hbox(0, 6)
        upd_row.setLayout(upd_lay)
        upd_toggle = ToggleSwitch("Check for updates at launch")
        upd_toggle.setChecked(
            bool(self.controller.get_app_setting("update_check_enabled", True))
        )
        upd_toggle.toggled.connect(
            lambda checked: self.controller.set_app_setting(
                "update_check_enabled", bool(checked))
        )
        upd_lay.addWidget(upd_toggle)
        self._explain(upd_lay,
            "Update check",
            "Asks GitHub once at launch whether a newer OscGoesPurrr "
            "release exists — a single HTTPS request; nothing is sent "
            "about you or your setup. When a newer version is found, a "
            "link appears here and in the System Log. Nothing downloads "
            "or installs by itself."
        )
        upd_lay.addStretch(1)
        upd_btn = QPushButton("Check for updates now")
        upd_btn.setProperty("role", "secondary")
        upd_btn.clicked.connect(
            lambda _=False: self.controller.check_for_updates_now())
        self._explain(
            upd_btn, "Check for updates now",
            "Asks GitHub right away whether there's a newer version. If "
            "there is, a Download and install button appears here.")
        upd_lay.addWidget(upd_btn)
        ql_lay.addWidget(upd_row)

        # Filled by show_update_notice() when a newer release exists.
        self.update_notice_label = QLabel("")
        self.update_notice_label.setOpenExternalLinks(True)
        self.update_notice_label.setWordWrap(True)
        self.update_notice_label.setVisible(False)
        ql_lay.addWidget(self.update_notice_label)

        # Install row — only shown when the running build can actually
        # replace itself (a frozen single-exe) AND the release carries a
        # downloadable exe. From source there is nothing to swap, so the
        # notice above stays a plain link.
        self.update_install_row = QWidget()
        upd_install_lay = _hbox(0, 8)
        self.update_install_row.setLayout(upd_install_lay)
        self.update_install_btn = QPushButton("Download and install")
        self.update_install_btn.clicked.connect(
            lambda _=False: self._on_install_update_clicked())
        upd_install_lay.addWidget(self.update_install_btn)
        self.update_progress_label = QLabel("")
        upd_install_lay.addWidget(self.update_progress_label, 1)
        self.update_install_row.setVisible(False)
        ql_lay.addWidget(self.update_install_row)

        # --- Settings backups (launch snapshots) ---
        bk_row = QWidget()
        bk_lay = _hbox(0, 8)
        bk_row.setLayout(bk_lay)
        bk_lay.addWidget(QLabel("Settings backups:"))
        self.snapshot_combo = QComboBox()
        self._populate_snapshot_combo()
        bk_lay.addWidget(self.snapshot_combo, 1)
        bk_restore_btn = QPushButton("Restore")
        bk_restore_btn.setProperty("role", "secondary")
        bk_restore_btn.clicked.connect(
            lambda _=False: self._on_restore_snapshot_clicked())
        bk_lay.addWidget(bk_restore_btn)
        self._explain(bk_lay,
            "Settings backups",
            "Every launch, all settings files are snapshotted into "
            "<b>%APPDATA%\\OscGoesPurrr\\backups</b> (the newest five "
            "are kept). <b>Restore</b> copies a snapshot back over the "
            "current settings and restarts the app — the escape hatch "
            "when a config change or an update went wrong. Restores are "
            "all-or-nothing (a failure changes nothing), and your usage "
            "statistics are never part of a snapshot — restoring old "
            "settings can't rewind your lifetime stats."
        )
        ql_lay.addWidget(bk_row)

        parent_layout.addWidget(ql_card)

        # ---- Appearance Card ----
        # The 518 design system ships two modes. The palette is copied into
        # every module (and the generated stylesheet) at import time, so a
        # switch applies on the next launch rather than live.
        ap_card = _Card()
        ap_lay = _vbox(14, 8)
        ap_card.setLayout(ap_lay)
        ap_hdr = QLabel("Appearance")
        ap_hdr.setObjectName("sectionTitle")
        ap_lay.addWidget(ap_hdr)
        ap_row = _hbox(0, 8)
        ap_row.addWidget(QLabel("Mode:"))
        current_mode = _theme.normalize_mode(
            self.controller.get_app_setting("ui_mode", _theme.MODE))
        self._mode_buttons = {}

        def _pick_mode(key: str) -> None:
            if key == current_mode:
                self._appearance_note.setText("This mode is already active.")
                return
            self.controller.set_app_setting("ui_mode", key)
            self._appearance_note.setText(
                f"Applying {_theme.MODE_LABELS.get(key, key)} — restarting…")
            QTimer.singleShot(200, self.controller.request_restart)

        for key in _theme.MODE_ORDER:
            btn = QPushButton(_theme.MODE_LABELS.get(key, key))
            btn.setProperty("role", "segActive" if key == current_mode else "segIdle")
            btn.setCursor(Qt.PointingHandCursor)
            btn.clicked.connect(lambda _=False, k=key: _pick_mode(k))
            ap_row.addWidget(btn)
            self._mode_buttons[key] = btn
        self._explain(ap_row,
            "Neon / Midnight",
            "<b>Neon</b> outlines every card and chip in the frame green; "
            "<b>Midnight</b> uses a near-invisible hairline so cards float. "
            "Same shapes, spacing and type in both — only the chrome swaps. "
            "The ◐ button beside the app title switches too. Changing mode "
            "restarts OscGoesPurrr so every widget repaints."
        )
        ap_row.addStretch(1)
        ap_lay.addLayout(ap_row)
        self._appearance_note = self._muted_label(
            "Neon is the default. Switching restarts the app — takes a second."
        )
        ap_lay.addWidget(self._appearance_note)
        parent_layout.addWidget(ap_card)

        # ---- Features Card ----
        # Lets the user turn off subsystems they don't need. Disabling a
        # feature hides its sidebar entry AND stops its background thread
        # so the app doesn't pay for what it isn't using.
        feat_card = _Card()
        feat_lay = _vbox(20, 6)
        feat_card.setLayout(feat_lay)

        hdr = QLabel("Features")
        hdr.setObjectName("sectionTitle")
        feat_lay.addWidget(hdr)
        feat_lay.addWidget(self._muted_label(
            "Turn off features you don't need. Disabled features hide their sidebar "
            "entry and stop their background threads to save resources."
        ))

        # One row per controller feature flag — the flag map is the source
        # of truth, so a flag the controller grows later still gets a row
        # (raw key label). Labeled keys keep this curated order.
        _feature_labels = {
            "feature_intiface":         "Intiface toy communication (Buttplug.io)",
            "feature_osc_router_518":   "OSC Router 518 fallback (VRChat receive)",
            "feature_osc_inspector":    "OSC Inspector (debug view)",
        }
        try:
            flag_keys = list(self.controller.get_feature_flags().keys())
        except Exception:
            flag_keys = list(_feature_labels.keys())
        ordered = [k for k in _feature_labels if k in flag_keys]
        ordered += [k for k in flag_keys if k not in _feature_labels]
        ordered = [k for k in ordered if k not in self._HIDDEN_FEATURES]
        feature_rows = tuple((k, _feature_labels.get(k, k)) for k in ordered)

        self.feature_toggles: Dict[str, ToggleSwitch] = {}
        for key, label in feature_rows:
            tog = ToggleSwitch(label)
            tog.setChecked(bool(self.controller.get_feature_enabled(key)))
            tog.toggled.connect(
                lambda checked, k=key: self.controller.set_feature_enabled(k, bool(checked))
            )
            feat_lay.addWidget(tog)
            self.feature_toggles[key] = tog
            if key in self._FEATURE_TIPS:
                self._explain(tog, label, self._FEATURE_TIPS[key])

        parent_layout.addWidget(feat_card)
        parent_layout.addStretch(1)

    def _bold_label(self, text: str) -> QLabel:
        lbl = QLabel(text)
        f = lbl.font(); f.setBold(True)
        lbl.setFont(f)
        return lbl

    # ----------------------------------------------------------
    # Update notice (controller facade)
    # ----------------------------------------------------------

    def show_update_notice(self, latest: str, url: str,
                           can_install: bool = False) -> None:
        """Controller facade: surface an available release in the Quality
        of Life card. Called from the queue pump on the GUI thread.

        `can_install` is the controller's verdict on whether this build can
        replace itself with the release's exe. When False the notice is
        just a link — the user downloads it themselves."""
        lbl = getattr(self, "update_notice_label", None)
        if lbl is None:
            return
        safe_latest = _html_escape(str(latest))
        safe_url = _html_escape(str(url))
        lbl.setText(
            f"Update available: <b>v{safe_latest}</b> — "
            f'<a href="{safe_url}">open releases page</a>'
        )
        lbl.setVisible(True)
        row = getattr(self, "update_install_row", None)
        if row is not None:
            row.setVisible(bool(can_install))

    def _on_install_update_clicked(self) -> None:
        """Disable the button for the duration so a second click can't
        start a competing download, then hand off to the controller."""
        btn = getattr(self, "update_install_btn", None)
        if btn is not None:
            btn.setEnabled(False)
        lbl = getattr(self, "update_progress_label", None)
        if lbl is not None:
            lbl.setText("Starting download...")
        self.controller.download_and_install_update()

    def show_update_progress(self, done: int, total: int) -> None:
        """Controller facade: paint download progress. `total` is 0 when
        the server sent no length, in which case we can only show how much
        has arrived so far."""
        lbl = getattr(self, "update_progress_label", None)
        if lbl is None:
            return
        mb = done / (1024.0 * 1024.0)
        if total > 0:
            pct = int(done * 100 / total)
            total_mb = total / (1024.0 * 1024.0)
            lbl.setText(f"Downloading... {pct}%  ({mb:.1f} / {total_mb:.1f} MB)")
        else:
            lbl.setText(f"Downloading... {mb:.1f} MB")

    def show_update_failed(self) -> None:
        """Controller facade: the download or its verification failed and
        nothing was changed. Re-arm the button so the user can retry."""
        btn = getattr(self, "update_install_btn", None)
        if btn is not None:
            btn.setEnabled(True)
        lbl = getattr(self, "update_progress_label", None)
        if lbl is not None:
            lbl.setText("Download failed — nothing was changed.")

    # ----------------------------------------------------------
    # Settings backups (launch snapshots)
    # ----------------------------------------------------------

    def _populate_snapshot_combo(self) -> None:
        """Fill the Settings-backups combo from the controller facade,
        newest first. Labels are human-formatted timestamps; the raw
        snapshot name rides in the item data."""
        combo = getattr(self, "snapshot_combo", None)
        if combo is None:
            return
        combo.clear()
        try:
            snaps = self.controller.get_settings_snapshots() or []
        except Exception:
            snaps = []
        for snap in snaps:
            try:
                label = time.strftime(
                    "%Y-%m-%d %H:%M:%S",
                    time.localtime(float(snap.get("ts", 0))))
            except (TypeError, ValueError, OverflowError, OSError):
                label = str(snap.get("name", "?"))
            combo.addItem(label, snap.get("name"))
        if combo.count() == 0:
            combo.addItem("No backups yet", None)
            combo.setEnabled(False)
        else:
            combo.setEnabled(True)

    def _on_restore_snapshot_clicked(self) -> None:
        combo = getattr(self, "snapshot_combo", None)
        if combo is None:
            return
        name = combo.currentData()
        if not name:
            return
        label = combo.currentText()
        resp = QMessageBox.question(
            self.window, "Restore settings",
            f"Restore settings from {label}?\n\nCurrent settings will be "
            "replaced and the app restarts.",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if resp != QMessageBox.Yes:
            return
        if not self.controller.restore_settings_snapshot(str(name)):
            QMessageBox.warning(
                self.window, "Restore failed",
                "That backup could not be restored — see the System Log "
                "for details.")

    def _build_help_view(self, parent_layout: QVBoxLayout):
        title = QLabel("Help & How It Works")
        title.setObjectName("viewTitle")
        title.setAlignment(Qt.AlignHCenter)
        parent_layout.addWidget(title)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        _install_rainbow_scrollbars(scroll)
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
            return lay

        section("Overview — what this app does", """
OscGoesPurrr listens to VRChat OSC parameters once, then fans them out to independent output pipelines:

  • Device Routing — Bluetooth toys via Intiface / Buttplug.io
  • OSC Inspector — live read-out of every parameter your avatar broadcasts

Each section is self-contained: a failure in one never affects the others.
""")

        section("Modes — what they are", """
A mode is a ROUTING: which parts of your avatar drive which motors. There are four — Combined, Separate, Custom 1 and Custom 2 by default, all renameable. Exactly one is active at a time; the mode buttons sit at the top of the sidebar, on every page. Right-click one to rename it or change its icon.

Switch modes to change how you're wired up, not how strong it is:

  • Combined — every socket feeding one motor.
  • Separate — each socket driving its own motor.
  • Custom 1 / 2 — anything in between; set them up however you like.

Each mode stores every motor's Input stage: its SPS zones, custom OSC parameter addresses, interaction filters (Touch, Penetration, Self, Others) and param-out mapping. Everything else — the signal-chain feel, the toys themselves — is shared, so you tune it once.
""")

        section("Strength, Off and Sleep", """
How strong everything runs is the Total output strength bar in the sidebar — one multiplier on everything your toys receive. It does not touch your tuning, so turning it back up restores exactly the feel you had.

Beside it are two toggles. Neither is remembered across restarts, deliberately — launching into silence, or into a sleep gate nobody remembers arming, just reads as a broken app.

  • Off — panic silence. Everything stops instantly whatever the slider says; switch it back off and your level returns untouched.
  • Sleep — makes your toys hard to wake: every chain's Wake stage switches to the stroke counter, so nothing plays until three full strokes land within six seconds. A brush against a sleeping partner does nothing. Your own Wake settings are untouched and come straight back. Buttplug toys only — no other backend has a Wake stage.

If ONE toy always feels stronger than the rest, leave the slider alone and trim that motor instead: Device Routing → its chain → Output → Gain. If instead a motor does nothing until it is well up its range, or gets unpleasant near the top, set Output → Range to the part it actually uses. Both are per-motor calibration and hold across every mode.
""")

        section("What is saved per mode vs. shared", """
Per mode (each of the four modes keeps its own copy):
  • Each motor's Input stage: SPS zones, custom OSC parameter addresses, interaction filters (Touch, Penetration, Self, Others), mirror-to-VRChat param-out

Shared by all modes (edit once, applies everywhere):
  • Every motor's signal-chain settings (Depth/Speed/Punch mix, Wake, smoothing, texture, zero cut, curves) and its Output gain + range
  • The global strength slider
  • The list of known toys (every toy you've ever connected), their motor counts and kinds, linear-actuator mode and idle behaviour
  • App settings: OSC network bind, auto-connect, auto-refresh, minimize-to-tray, hide-console, etc.
""")

        section("Switching modes", """
Switch from the mode buttons at the top of the sidebar, or in VR via a VRChat expression menu bound to the OGP/Mode Int parameter (0-3) — setup guide in docs/VRCHAT_MENU.md. Switching instantly re-wires every motor's input; the set of toys, their feel and the strength do not change.

The optional "Remember mode per avatar" setting (Settings → Modes) restores the mode each avatar last used when it loads — useful when different avatars have different socket layouts. Per-toy mutes survive mode switches.
""")

        section("Deleting a toy", """
The red "Delete" button on a toy card forgets that toy entirely — it is removed from the wiring and every mode, and from the global known-toys list. To use the toy again, simply reconnect it; it will be re-registered automatically.
""")

        section("Custom OSC addresses on a motor", """
Under each motor, the "+ Add Variable" button lets you map any number of OSC parameters to that motor. The motor's output is the maximum of all mapped parameters' normalized values (plus any contribution from selected SPS zones).

The picker shows live avatar parameters captured by the OSC inspector. Double-click a row to add it, or use the manual entry field. The × on each chip removes that mapping from the shared wiring — it applies in every mode.
""")

        section("SPS Sources — synthetic contact zones", """
The SPS Sources tab lets you build a "virtual" SPS zone out of raw VRChat contact receivers, for spots your avatar doesn't expose as an OGB zone. Each source combines:

  • Proximity — one or more proximity receivers. The loudest one wins.
  • Activation — binary gate contacts. The proximity only counts while at least one activation contact is firing, so you can pin the signal to a very specific spot. Leave empty for no gate.
  • Velocity — binary on-enter contacts. While any of them fires, the output is multiplied by the "Velocity ×" amount (a thrust/speed boost).
  • Max value — caps the raw proximity before the multiplier is applied.

Type all the contact parameter names comma-separated (the /avatar/parameters/ prefix is optional). Each source you define then appears — by its name — in the Device Routing zone picker (under "Custom Sources"), where it routes exactly like an auto-detected zone. The sources are global (shared by every mode).
""")

        section("Real-Time OSC Inspector", """
OSC Inspector shows every OSC parameter your avatar is broadcasting. It starts automatically when you open the page and stops when you leave — useful for finding the exact name of a parameter before mapping it to a motor.

Two views are stacked:
  • Top: the in-place QTableWidget (preserves scroll position across refreshes).
  • Bottom: a legacy HTML view kept as a diagnostic — if the top freezes but the bottom ticks, the bug is in the table update path; if both freeze, the OSC pipeline upstream is the suspect.

Both consume the same data, so they stay in lockstep.
""")

        section("Hover explanations", """
Rest the mouse on a control, a heading or a button for a moment and its explanation pops up on its own — the modes, the strength bar, Off and Sleep, every stage of a signal chain, the zone pickers, the connection buttons. Move the mouse away and it disappears. There is nothing to switch on first.
""")

        section("Where settings live on disk", """
%APPDATA%\\OscGoesPurrr\\
  • modes.json               — the four routing modes + shared rig, feel and strength (schema v4)
  • known_devices.json       — global toy list (name, motor count, motor kinds)
  • app_settings.json        — global app preferences
  • sps_sources.json         — synthetic contact zones, shared by every mode
  • sessions_settings.json   — session-logger preferences
""")

        license_lay = section("License", """
OscGoesPurrr is free and open source under the MIT license. It also uses other open-source projects, each under its own license — the button below lists them.
""")
        lic_btn = QPushButton("Show licenses…")
        lic_btn.setCursor(Qt.PointingHandCursor)
        lic_btn.clicked.connect(self._show_licenses)
        self._explain(lic_btn, "Show licenses",
                      "OscGoesPurrr's own license and every third-party component "
                      "this app carries, with the notices their licenses ask to be "
                      "passed on.")
        license_lay.addWidget(lic_btn, 0, Qt.AlignLeft)

        inner_lay.addStretch(1)

    def _on_steamvr_toys_toggled(self, checked: bool):
        """Switch toys-in-SteamVR and say what happens next."""
        try:
            status = self.controller.set_steamvr_toys_enabled(bool(checked))
        except Exception as e:
            self.log_message(f"SteamVR toys: {e}")
            return
        kind = status.get("error_kind", "")
        if not checked:
            text = ("Off — your toys leave SteamVR's device list, and the "
                    "driver is taken out of SteamVR.")
        elif kind == "no_steamvr":
            text = ("SteamVR isn't installed on this PC, so there's nowhere "
                    "to show your toys yet.")
        elif kind == "dll_locked":
            text = ("SteamVR is using an older version of the driver, so it "
                    "couldn't be updated. Close SteamVR, then switch this off "
                    "and on again.")
        elif kind:
            text = "The SteamVR driver couldn't be installed — the System Log says why."
        elif status.get("driver_loaded"):
            text = "On — connected toys appear in SteamVR's device list."
        else:
            text = ("On — your toys appear in SteamVR's device list from its "
                    "next start. If SteamVR is running right now, restart it "
                    "once.")
        self.steamvr_toys_note.setText(text)
        self.steamvr_toys_note.setVisible(True)

    def _show_licenses(self):
        """LICENSE and THIRD_PARTY_NOTICES.md, as bundled with this build."""
        texts = []
        for name in ("LICENSE", "THIRD_PARTY_NOTICES.md"):
            try:
                with open(_theme.bundle_path(name), encoding="utf-8") as fh:
                    texts.append(fh.read())
            except OSError:
                texts.append(f"{name} is missing from this build — it is also in the "
                             f"project's GitHub repository.")
        dlg = QDialog(self.window)
        dlg.setWindowTitle("Licenses")
        dlg.resize(920, 720)
        lay = _vbox(12, 8)
        dlg.setLayout(lay)
        view = QPlainTextEdit()
        view.setReadOnly(True)
        view.setLineWrapMode(QPlainTextEdit.NoWrap)
        mono = QFont("Cascadia Mono")
        mono.setStyleHint(QFont.Monospace)
        view.setFont(mono)
        view.setPlainText(("\n\n" + "─" * 78 + "\n\n").join(texts))
        lay.addWidget(view, 1)
        close = QPushButton("Close")
        close.clicked.connect(dlg.accept)
        lay.addWidget(close, 0, Qt.AlignRight)
        dlg.exec()
