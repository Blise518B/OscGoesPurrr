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
from ui.views.avatar_menu import AvatarMenuCard
from ui.views.settings_appearance import AppearanceMixin
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


class SettingsMixin(AppearanceMixin):

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
            "the toy server and hides the toy list on Home — only useful if "
            "you run the app purely to drive avatar parameters.",
        "feature_osc_router_518":
            "After a few hours VRChat can stop announcing itself to new OSC "
            "apps. With this on, the app automatically listens through a "
            "local OSC Router 518 when that happens, and switches back when "
            "VRChat recovers. Harmless if you don't run the router.",
        "feature_osc_inspector":
            "The OSC Inspector page, which lists every parameter your "
            "avatar sends. Off: the page is hidden and stops its work.",
        "feature_statistics":
            "Your sessions, charts and lifetime totals, kept only on this "
            "PC. Off: nothing is recorded any more and the Statistics page "
            "is hidden - what is recorded stays, for when you switch it back "
            "on. Delete statistics… (right below) deletes it.",
        "feature_friends":
            "Link with other OGP users over the internet: they may drive your "
            "toys or shockers if you allow it, and you theirs. Off: the "
            "Friends page is hidden and the link is closed - OGP then never "
            "contacts the servers that help two PCs find each other.",
        "feature_params":
            "Boards of controls for your avatar's parameters, per avatar - VRC "
            "Parameter Relay's board, inside OGP. On: the My Avatar Remote page "
            "appears, and friends you allow see the board of the avatar you "
            "wear and can use it. Off: the page is hidden and friends see "
            "nothing of it.",
        "feature_pishock":
            "A PiShock or OpenShock hub plugged into this PC by USB. On: the "
            "Shockers page appears in the sidebar. Off: the page is hidden, "
            "the hub is let go and nothing is sent to it.",
        "feature_bhaptics":
            "A bHaptics suit, sleeves or head, straight over Bluetooth — no "
            "bHaptics Player. On: the Suits page appears and OGP connects to "
            "it. Off: the suit is zeroed and let go, so the Player can have "
            "it again.",
        "feature_owo":
            "An OWO suit, through the My OWO app (which keeps your "
            "calibration). On: the Suits page appears; OGP connects when you "
            "press Connect. Off: OWO is stopped and My OWO is let go.",
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
        self._settings_tabs = tabs          # ui/views/whats_new.py jumps here

        # SessionsMixin renders the Sessions tab content; General keeps
        # the original card stack.
        self._build_sessions_panel(sessions_lay)
        parent_layout = general_lay

        # ---- Features Card ----
        # First (Blise's call, 2026-10-27): what the app shows at all. A
        # feature switched off hides its sidebar entry AND stops its
        # background thread, so the app doesn't pay for what it isn't using.
        parent_layout.addWidget(self._build_features_card())

        # ---- VRChat menu Card ----
        # Right after Features (Blise's ask, 2026-10-28): the avatar menu's
        # prefab and whether the avatar you're wearing has it, findable
        # without opening Friends (ui/views/avatar_menu.py).
        self._avatar_menu_card = AvatarMenuCard(
            lambda: self.controller.get_avatar_menu(), self._explain)
        parent_layout.addWidget(self._avatar_menu_card)

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
        def _on_auto_refresh(_=False) -> None:
            self.controller.toggle_auto_refresh()
            # The sidebar's Find toys button stands in while this is off.
            refresh = getattr(self, "refresh_link_buttons", None)
            if callable(refresh):
                refresh()

        self.auto_refresh_var.toggled.connect(_on_auto_refresh)
        conn_lay.addWidget(self.auto_refresh_var)
        self._explain(
            self.auto_refresh_var, "Auto refresh devices",
            "Keep looking for toys by itself, so one you switch on shows up "
            "without pressing anything: every few seconds while no toy is "
            "connected (how often: below), every 30 seconds while one is - "
            "a scan shares Bluetooth with a connected toy, so it waits. "
            "Off: a Find toys button appears in the sidebar instead.")
        scan_row = QWidget()
        scan_lay = _hbox(0, 8)
        scan_lay.setContentsMargins(
            ToggleSwitch._TRACK_W + ToggleSwitch._LABEL_SPACING, 0, 0, 0)
        scan_row.setLayout(scan_lay)
        scan_lay.addWidget(QLabel("While no toy is connected, look every"))
        self.toy_scan_spin = QSpinBox()
        self.toy_scan_spin.setRange(*TOY_SEARCH_RATE_RANGE)
        self.toy_scan_spin.setSuffix(" s")
        self.toy_scan_spin.setFixedWidth(86)
        self.toy_scan_spin.setValue(int(self.controller.get_toy_scan_interval()))
        self.toy_scan_spin.valueChanged.connect(
            lambda v: self.controller.set_toy_scan_interval(int(v)))
        scan_lay.addWidget(self.toy_scan_spin)
        scan_lay.addStretch(1)
        conn_lay.addWidget(scan_row)
        scan_row.setVisible(self.auto_refresh_var.isChecked())
        self.auto_refresh_var.toggled.connect(scan_row.setVisible)
        self._explain(
            self.toy_scan_spin, "How often to look",
            "While no toy is connected, a scan for toys starts this often - "
            "5 seconds by default, so a toy you switch on shows up almost at "
            "once. Each scan listens on Bluetooth for 2 seconds. Once a toy "
            "is connected, the app looks every 30 seconds instead.")

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
            "reconnecting if the link drops. Off: a Connect button appears "
            "in the sidebar instead.")

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
            "it up again when VRChat restarts. Off: a Connect button "
            "appears in the sidebar instead.")
        conn_lay.addWidget(self.osc_auto_connect_var)

        self.toy_sounds_toggle = ToggleSwitch("Sound when a toy connects or disconnects")
        self.toy_sounds_toggle.setChecked(bool(self.controller.get_toy_sounds_enabled()))
        self.toy_sounds_toggle.toggled.connect(
            lambda checked: self.controller.set_toy_sounds_enabled(bool(checked))
        )
        conn_lay.addWidget(self.toy_sounds_toggle)
        self._explain(
            self.toy_sounds_toggle, "Connect sounds",
            "A short chime going up when a toy connects, and going down "
            "when one drops — switched off, out of range or flat. Handy in "
            "VR, where you can't see this window. It plays on your PC's "
            "default sound output. Switching it on plays the connect chime "
            "once so you know what to listen for. On by default.")

        # Volume + Test, shown only while the switch is on: when they played
        # with the switch off, the chimes looked enabled when they weren't.
        # (Hidden rather than disabled: this theme doesn't dim disabled
        # labels or secondary buttons, so a disabled row still looks live.)
        snd_row = QWidget()
        snd_lay = _hbox(0, 8)
        # Indented to the switch's label, so the row reads as its own.
        snd_lay.setContentsMargins(
            ToggleSwitch._TRACK_W + ToggleSwitch._LABEL_SPACING, 0, 0, 0)
        snd_row.setLayout(snd_lay)
        snd_lay.addWidget(QLabel("Volume"))
        vol_slider = QSlider(Qt.Horizontal)
        vol_slider.setRange(0, 100)
        vol_slider.setSingleStep(5)
        vol_slider.setPageStep(10)
        vol_slider.setFixedWidth(260)
        vol_slider.setCursor(Qt.PointingHandCursor)
        vol_slider.setValue(int(self.controller.get_toy_sounds_volume()))
        snd_lay.addWidget(vol_slider)
        vol_value = QLabel(f"{vol_slider.value()}%")
        vol_value.setFixedWidth(40)
        vol_value.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        snd_lay.addWidget(vol_value)
        # Store (and play at the new level) once the slider settles, not
        # on every step of a drag or a wheel spin.
        vol_commit = QTimer(snd_row)
        vol_commit.setSingleShot(True)
        vol_commit.setInterval(300)
        vol_commit.timeout.connect(
            lambda: self.controller.set_toy_sounds_volume(vol_slider.value()))

        def _on_volume(v: int) -> None:
            vol_value.setText(f"{v}%")
            vol_commit.start()
        vol_slider.valueChanged.connect(_on_volume)

        def _on_test(_=False) -> None:
            # A level still waiting to be stored is stored first, quietly,
            # so the test plays exactly what the slider shows.
            if vol_commit.isActive():
                vol_commit.stop()
                self.controller.set_toy_sounds_volume(vol_slider.value(), preview=False)
            self.controller.test_toy_sounds()
        test_btn = QPushButton("Test")
        test_btn.setProperty("role", "secondary")
        test_btn.setCursor(Qt.PointingHandCursor)
        test_btn.clicked.connect(_on_test)
        snd_lay.addWidget(test_btn)
        snd_lay.addStretch(1)
        conn_lay.addWidget(snd_row)
        snd_row.setVisible(self.toy_sounds_toggle.isChecked())
        self.toy_sounds_toggle.toggled.connect(snd_row.setVisible)
        self.toy_sounds_volume_slider = vol_slider
        self._explain(
            snd_lay, "Connect sound volume",
            "How loud the chimes are, on top of your system volume. The "
            "chime plays at the new level when you stop moving the "
            "slider. <b>Test</b> plays the connect chime, then the "
            "disconnect one.")

        # The whole-rig "a toy is connected" avatar parameter. Each toy has
        # its own on its card (Home); this is the one for "any of them".
        getter = getattr(self.controller, "get_toy_presence_param", None)
        if callable(getter):
            any_on, any_param = getter()
            conn_lay.addWidget(self._build_connected_param_row(
                "Tell VRChat while any toy is connected", any_on, any_param,
                lambda on, name: self.controller.set_toy_presence_param(on, name),
                "Tell VRChat while any toy is connected",
                "Sends a Bool avatar parameter that is <b>true while at "
                "least one toy is connected</b> and false while none is "
                "— so your avatar can show that your toys are live. Add "
                "a Bool with this name to your avatar's parameters; the "
                "name is yours to change, or <b>Pick…</b> one your "
                "avatar already sends.<br><br>"
                "It is sent again whenever you change avatar, and goes "
                "false when you close the app. Each toy has its own switch "
                "for \"this toy is connected\": open the toy on Home."))

        # Thrust counters as avatar parameters, for a counter display.
        if callable(getattr(self.controller, "get_thrust_params_enabled", None)):
            self.thrust_params_toggle = ToggleSwitch("Send thrust counters to VRChat")
            self.thrust_params_toggle.setChecked(
                bool(self.controller.get_thrust_params_enabled()))
            self.thrust_params_toggle.toggled.connect(
                lambda checked: self.controller.set_thrust_params_enabled(bool(checked)))
            conn_lay.addWidget(self.thrust_params_toggle)
            self._explain(
                self.thrust_params_toggle, "Send thrust counters to VRChat",
                "Sends three counters as <b>Int</b> avatar parameters, for a "
                "counter on your avatar or a prop:<br>"
                "<b>OGP/Thrusts/Total</b> — every thrust on record<br>"
                "<b>OGP/Thrusts/Session</b> — since the app started<br>"
                "<b>OGP/Thrusts/PerMin</b> — thrusts in the last minute<br><br>"
                "An Int only holds 0 to 255, so each counter also goes out "
                "digit by digit: <b>/D1</b> is the ones, <b>/D2</b> the tens "
                "and so on — <b>OGP/Thrusts/Total/D1</b> to <b>/D7</b>, "
                "Session <b>/D1</b> to <b>/D5</b>, PerMin <b>/D1</b> to "
                "<b>/D3</b>. Add the ones your asset uses; keep them unsynced "
                "unless others should see them (each synced Int costs 8 "
                "bits).<br><br>"
                "The same numbers as the Statistics page, so it needs Usage "
                "statistics on. Sent again whenever you change avatar; the "
                "pace goes to 0 when you close the app. Off by default.")

        parent_layout.addWidget(conn_card)
        self._connection_card = conn_card

        # ---- Toy Safety Card ----
        self._toy_safety_card = self._build_toy_safety_card()
        parent_layout.addWidget(self._toy_safety_card)

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
        self.steamvr_toys_toggle.setChecked(
            bool(svr_status.get("enabled")) and bool(svr_status.get("supported")))
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
        if not svr_status.get("supported"):
            # The driver is a Windows DLL.
            self.steamvr_toys_note.setText("Windows only for now.")
            self.steamvr_toys_note.setVisible(True)
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
        if sys.platform != "win32":
            hide_console.setVisible(False)  # no console window to hide
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
            "window pops up (tick \"Don't remind me\" there to skip that "
            "version) and a link appears here and in the System Log. "
            "Nothing downloads or installs by itself."
        )
        upd_lay.addStretch(1)
        # The notes of the version in use -- they open by themselves once
        # after an update; this is how to see them again.
        news = getattr(self.controller, "get_whats_new", None)
        if callable(news) and news():
            news_btn = QPushButton("What's new")
            news_btn.setProperty("role", "secondary")
            news_btn.clicked.connect(lambda _=False: self.open_whats_new())
            self._explain(
                news_btn, "What's new",
                "What changed in this version, each with a button that "
                "takes you to it. Opens by itself once after an update.")
            upd_lay.addWidget(news_btn)
            self.whats_new_button = news_btn
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
            f"<b>{SETTINGS_DIR_DISPLAY}{os.sep}backups</b> (the newest five "
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
        # Two modes and one colour. Both apply while the app runs
        # (ui/live_theme.py) -- nothing on this card restarts anything.
        ap_card = _Card()
        ap_lay = _vbox(20, 8)
        ap_card.setLayout(ap_lay)
        ap_hdr = QLabel("Appearance")
        ap_hdr.setObjectName("sectionTitle")
        ap_lay.addWidget(ap_hdr)
        ap_lay.addWidget(self._build_ui_mode_row())
        ap_lay.addWidget(self._build_accent_picker())
        ap_lay.addWidget(self._build_identity_colours())
        parent_layout.addWidget(ap_card)
        self._appearance_card = ap_card

        parent_layout.addStretch(1)

        # This page's sections for the live colour sweep: the title, the
        # tab bar, each card and the Sessions tab -- so a colour picked
        # here runs down the page card by card instead of all at once.
        # (The cards are built once and never added to later.)
        style_root = getattr(self, "_style_root", None)
        if callable(style_root):
            style_root(title)
            style_root(tabs.tabBar())
            for i in range(general_lay.count()):
                style_root(general_lay.itemAt(i).widget())
            style_root(sessions_tab)

    def _build_features_card(self) -> QWidget:
        """Settings → Features, the first card on the page: one switch
        per feature, and the first-launch question to set them all."""
        feat_card = _Card()
        feat_lay = _vbox(20, 6)
        feat_card.setLayout(feat_lay)
        self._features_card = feat_card     # What's new's "Take me there"

        hdr = QLabel("Features")
        hdr.setObjectName("sectionTitle")
        feat_lay.addWidget(hdr)
        feat_lay.addWidget(self._muted_label(
            "Turn off features you don't need. Disabled features hide their sidebar "
            "entry and stop their background threads to save resources."
        ))
        # the first-launch question again (ui/views/interests.py)
        pick_row = _hbox(0, 8)
        pick = QPushButton("Choose what you use…")
        pick.setProperty("role", "secondary")
        pick.setCursor(Qt.PointingHandCursor)
        pick.clicked.connect(lambda _=False: self.open_interests())
        self._explain(pick, "Choose what you use",
                      "The question a new install starts with: tick what you "
                      "have and what you want, and the switches below follow. "
                      "Cancel leaves them as they are.")
        pick_row.addWidget(pick)
        pick_row.addStretch(1)
        feat_lay.addLayout(pick_row)

        # One row per controller feature flag — the flag map is the source
        # of truth, so a flag the controller grows later still gets a row
        # (raw key label). Labeled keys keep this curated order.
        _feature_labels = {
            "feature_intiface":         "Intiface toy communication (Buttplug.io)",
            "feature_osc_router_518":   "OSC Router 518 fallback (VRChat receive)",
            "feature_osc_inspector":    "OSC Inspector (debug view)",
            "feature_statistics":       "Usage statistics",
            "feature_pishock":          "Shockers — PiShock / OpenShock (USB)",
            "feature_bhaptics":         "bHaptics — suit and sleeves over Bluetooth",
            "feature_owo":              "OWO — EMS suit through the My OWO app",
            "feature_friends":          "Friends — control each other over the internet",
            "feature_params":           "Avatar Remote — avatar boards friends can use too",
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
                lambda checked, k=key: self._on_feature_toggled(k, bool(checked))
            )
            feat_lay.addWidget(tog)
            self.feature_toggles[key] = tog
            if key in self._FEATURE_TIPS:
                self._explain(tog, label, self._FEATURE_TIPS[key])
            if key == "feature_statistics":
                # off keeps them; this is what deletes them (on or off)
                row = _hbox(0, 8)
                row.setContentsMargins(
                    ToggleSwitch._TRACK_W + ToggleSwitch._LABEL_SPACING, 0, 0, 0)
                delete = QPushButton("Delete statistics…")
                delete.setProperty("role", "danger")
                delete.setProperty("size", "small")
                delete.clicked.connect(lambda _=False: self._on_delete_stats())
                self._explain(delete, "Delete statistics",
                              "Deletes everything recorded - sessions, charts, "
                              "lifetime totals, who each session was with. "
                              "Asks first. Works whether statistics are on or "
                              "off.")
                row.addWidget(delete)
                row.addStretch(1)
                feat_lay.addLayout(row)

        return feat_card

    def _sync_feature_toggles(self) -> None:
        """Bring the Features switches in line with the flags after they
        were set elsewhere (the question): quietly, nothing is set twice."""
        flags = self.controller.get_feature_flags()
        for key, tog in (getattr(self, "feature_toggles", None) or {}).items():
            if key in flags and tog.isChecked() != bool(flags[key]):
                tog.blockSignals(True)
                tog.setChecked(bool(flags[key]))
                tog.blockSignals(False)

    def _on_feature_toggled(self, key: str, checked: bool) -> None:
        """A Features switch was flipped. (Statistics off only stops
        recording; deleting them is its own button, which asks first.)"""
        self.controller.set_feature_enabled(key, checked)

    def _on_delete_stats(self) -> None:
        resp = QMessageBox.question(
            (getattr(self, "dialog_parent", None) or self.window), "Delete statistics",
            "Delete all statistics?\n\nEvery session, chart, lifetime total and "
            "who each session was with is deleted from this PC. This cannot "
            "be undone.",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if resp == QMessageBox.Yes:
            self.controller.delete_stats()

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

    def show_update_popup(self, latest: str, current: str, url: str,
                          can_install: bool = False) -> None:
        """Controller facade: a window in the middle of the app when the
        launch check finds a newer release, so nobody misses it. "Don't
        remind me" is per version — the next release pops up again. The
        quiet line in Settings stays either way."""
        if getattr(self, "_update_popup", None) is not None:
            return
        if (getattr(self, "_whats_new_dialog", None) is not None
                or getattr(self, "_interests_dialog", None) is not None):
            # One window at a time: the offer opens when "What's new" or
            # the question closes (ui/views/whats_new.py, interests.py).
            self._update_popup_waiting = (latest, current, url, can_install)
            return
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices

        dlg = QDialog((getattr(self, "dialog_parent", None) or self.window))
        dlg.setWindowTitle("Update available")
        dlg.setWindowModality(Qt.WindowModal)
        dlg.setMinimumWidth(460)
        lay = _vbox(20, 12)
        dlg.setLayout(lay)

        title = QLabel(f"OscGoesPurrr v{_html_escape(str(latest))} is out")
        title.setObjectName("sectionTitle")
        lay.addWidget(title)
        how = ("<b>Install now</b> downloads it, checks it and restarts the "
               "app — your settings stay as they are."
               if can_install else
               "Get the new exe from the release page.")
        body = QLabel(
            f"You're on v{_html_escape(str(current))}. "
            f'<a href="{_html_escape(str(url))}">See what\'s new</a>.<br><br>{how}')
        body.setWordWrap(True)
        body.setOpenExternalLinks(True)
        lay.addWidget(body)

        progress = QLabel("")
        progress.setVisible(False)
        lay.addWidget(progress)

        skip = QCheckBox(f"Don't remind me about v{latest} again")
        lay.addWidget(skip)

        row = _hbox(0, 8)
        row.addStretch(1)
        later = QPushButton("Later")
        later.setProperty("role", "secondary")
        later.clicked.connect(lambda _=False: dlg.reject())
        row.addWidget(later)
        page = QPushButton("Release page" if can_install else "Open release page")
        page.setProperty("role", "secondary" if can_install else "primary")

        def _open_page(_=False):
            QDesktopServices.openUrl(QUrl(str(url)))
            dlg.accept()
        page.clicked.connect(_open_page)
        row.addWidget(page)
        buttons = [later, page]
        if can_install:
            install = QPushButton("Install now")
            install.setProperty("role", "primary")

            def _install(_=False):
                for b in buttons:
                    b.setEnabled(False)
                skip.setEnabled(False)
                progress.setText("Starting download...")
                progress.setVisible(True)
                dlg.adjustSize()      # make room for the progress line
                self._on_install_update_clicked()
            install.clicked.connect(_install)
            row.addWidget(install)
            buttons.append(install)
            install.setDefault(True)
        lay.addLayout(row)

        def _closed(_result):
            if skip.isChecked():
                self.controller.set_app_setting("update_popup_skipped_version", str(latest))
            self._update_popup = None
            self._update_popup_progress = None
            self._update_popup_buttons = []
        dlg.finished.connect(_closed)

        self._update_popup = dlg
        self._update_popup_progress = progress
        self._update_popup_buttons = buttons
        # open(), not exec(): this runs from the queue pump, and a nested
        # event loop would re-enter it.
        dlg.open()

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
        mb = done / (1024.0 * 1024.0)
        if total > 0:
            pct = int(done * 100 / total)
            total_mb = total / (1024.0 * 1024.0)
            text = f"Downloading... {pct}%  ({mb:.1f} / {total_mb:.1f} MB)"
        else:
            text = f"Downloading... {mb:.1f} MB"
        # The Settings row and, when the install started there, the popup.
        for lbl in (getattr(self, "update_progress_label", None),
                    getattr(self, "_update_popup_progress", None)):
            if lbl is not None:
                lbl.setText(text)

    def show_update_failed(self) -> None:
        """Controller facade: the download or its verification failed and
        nothing was changed. Re-arm the button so the user can retry."""
        btn = getattr(self, "update_install_btn", None)
        if btn is not None:
            btn.setEnabled(True)
        for lbl in (getattr(self, "update_progress_label", None),
                    getattr(self, "_update_popup_progress", None)):
            if lbl is not None:
                lbl.setText("Download failed — nothing was changed.")
        for b in getattr(self, "_update_popup_buttons", None) or []:
            b.setEnabled(True)

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
            (getattr(self, "dialog_parent", None) or self.window), "Restore settings",
            f"Restore settings from {label}?\n\nCurrent settings will be "
            "replaced and the app restarts.",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if resp != QMessageBox.Yes:
            return
        if not self.controller.restore_settings_snapshot(str(name)):
            QMessageBox.warning(
                (getattr(self, "dialog_parent", None) or self.window), "Restore failed",
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

        # First the pages to be shown around (ui/views/help.py), then the
        # long texts, folded until asked for
        self._build_help_tour(inner_lay)
        fold = QPushButton("▸  Every part in detail")
        fold.setProperty("role", "ghost")
        fold.setCursor(Qt.PointingHandCursor)
        details = QWidget()
        details_lay = _vbox(0, 10)
        details.setLayout(details_lay)
        details.setVisible(False)

        def flip():
            details.setVisible(not details.isVisible())
            fold.setText(("▾" if details.isVisible() else "▸") + "  Every part in detail")
        fold.clicked.connect(flip)
        self._explain(fold, "Every part in detail",
                      "The manual: how modes, signal chains, shockers, suits, the "
                      "Avatar Remote and the rest work, and where settings live.")
        inner_lay.addWidget(fold, 0, Qt.AlignLeft)
        inner_lay.addWidget(details)

        def section(heading: str, body: str, into=None):
            card = _Card()
            lay = _vbox(15, 6)
            card.setLayout(lay)
            h = QLabel(heading)
            h.setObjectName("sectionTitle")
            lay.addWidget(h)
            b = QLabel(body.strip())
            b.setWordWrap(True)
            lay.addWidget(b)
            (into or details_lay).addWidget(card)
            return lay

        section("What this app does", """
OscGoesPurrr listens to VRChat OSC parameters once, then fans them out to independent output pipelines:

  • Home — your Bluetooth toys via Intiface / Buttplug.io
  • OSC Inspector — live read-out of every parameter your avatar broadcasts

Each section is self-contained: a failure in one never affects the others.
""")

        section("Home — your toys", """
Home is where the app opens. Every toy you have connected gets a row outlined in its own colour, showing what drives it in the active mode, its battery and a live meter per motor, with Mute and Test right there. Toys you've used before but that are switched off stay listed in a grey outline, so their setup is always reachable. Test all buzzes every connected toy at once.

Click a toy's bar to open it: each motor's signal chains appear in place (Input → Depth/Speed/Punch → Combine → Wake → Envelope → Zero cut → Output). Click any stage to edit it. Click the bar again to fold the toy away.

Tuning tools, at the bottom, holds the two things you only need while shaping a response: the input simulator and the signal graph. It stays folded until you open it and remembers how you left it.

Anti-stuck — the safety cutoff that stops a toy when a contact's value freezes (an avatar swap, a partner leaving) — is on by default and lives in Settings → Toy Safety.
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

If ONE toy always feels stronger than the rest, leave the slider alone and trim that motor instead: Home → the toy → its chain → Output → Gain. If instead a motor does nothing until it is well up its range, or gets unpleasant near the top, set Output → Range to the part it actually uses. Both are per-motor calibration and hold across every mode.
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

        section("Showing connected toys on your avatar", """
The app can tell your avatar whether a toy is connected, as a Bool avatar parameter — for a light, an icon, anything your avatar can switch on.

  • Any toy — Settings → Connection Settings → "Tell VRChat while any toy is connected". True while at least one toy is connected.
  • One toy — open the toy on Home → "Tell VRChat while this toy is connected". True while that toy is connected. It is the same in every mode.

Each has a name you can change; add a Bool with that name to your avatar's parameters. The values are sent again whenever you change avatar or VRChat reconnects, and all go false when you close the app. Setup details: docs/VRCHAT_MENU.md.
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

Type all the contact parameter names comma-separated (the /avatar/parameters/ prefix is optional). Each source you define then appears — by its name — in every toy's zone picker on Home (under "Custom Sources"), where it routes exactly like an auto-detected zone. The sources are global (shared by every mode).
""")

        section("Shockers over USB (PiShock / OpenShock)", """
Switch it on under Settings → Features, plug the hub into this PC by USB and press Connect on the Shockers page. No account and no internet: commands go straight down the cable, the moment your avatar's contact changes.

The hub can run PiShock's own firmware or OpenShock's (PiShock's 2023 and Lite hubs can be reflashed with it, and so can a DIY ESP32 board with a 433 MHz transmitter); the app tells which when it connects. A PiShock hub reports its shockers itself. OpenShock firmware keeps no list, so add each shocker on the page — its model and the ID it is paired to. To pair a collar, hold its power button until the light blinks fast and press Beep on its row. PiShock's own shocker is a CaiXianlin.

Three kinds of rule:
  • Continuous — a value (usually a proximity contact) runs the shocker while it is above the threshold, stronger the closer the contact.
  • Contact triggers — one on/off contact at a fixed strength: one pulse per touch, or running while touching.
  • Impact tiers — several OnEnter receivers on one spot, each with a different Min Velocity on the avatar. The strongest one that fired picks the strength, so a slap lands harder than a tap.

Safety: shocks go out as vibrates until you arm them, and arming switches itself off every launch. Max strength, max pulse length, a rest between pulses and a forced break after long continuous runs apply to every send. Stop all, the sidebar's Off, a lost cable and VRChat going silent all stop the shockers at once.
""")

        section("Suits (bHaptics and OWO)", """
Switch each suit on under Settings → Features; both share the Suits page and the same contacts on your avatar.

bHaptics: OGP talks to the suit, sleeves and head over Bluetooth itself — close the bHaptics Player first, because a suit takes one connection at a time. No pairing in Windows needed. "Let go" hands the suit back to the Player or a game. If OGP stops sending, the suit goes quiet within a quarter of a second.

OWO: OGP connects to the My OWO app the way a game does (on this PC first, then on your network). My OWO keeps your calibration and drives the suit; 100 % is the top of that calibration. The ceiling and each muscle's top cap every sensation, the Test button stays gentle, and Stop all, the sidebar's Off and VRChat going silent stop OWO at once.

Contacts: the official bHaptics avatar package (bOSC/v2), older bHapticsOSC setups and the OWO avatar package (owo_suit_…) all work. With sharing on, a bHaptics contact also plays the OWO muscle around it and an OWO contact plays its patch of the bHaptics suit. Zone routes send an OGB / SPS zone or a custom source to a part of the body, for both suits.
""")

        section("Avatar Remote — your avatar's board", """
VRC Parameter Relay's board, inside OGP. Switch it on under Settings → Features, wear an avatar, and open the parameter list on the right of the My Avatar Remote page: double-click a parameter, or drag it onto a category, to make a control. The kind is picked for its type — a toggle for a Bool, a stepper for an Int, a slider for a Float; ⋯ → Edit changes the label, the kind, the range or inverts a toggle (⇄, for a parameter whose logic is backwards).

An Int can be a toggle or a hold button too: each sets its own value (Outfit = 1, 2, 3 …, shown as =2 on the card), and they switch each other off like VRChat's own menu.

Drag cards by their ⠿ to move them, and categories by the ⠿ in their header. Each category has a colour and a 🔒: locked, friends can see it but not use it (you still can). Every avatar keeps its own board and can have several presets (the drop-down at the top; ⋯ next to it adds, renames and deletes them; a category's ⋯ copies it to another preset). Give an avatar a name and it stays in the ▾ list, so you can edit its board while you wear something else — ✎ OFFLINE then means nothing is sent.

Friends: everyone whose third box (AVATAR) is ticked in your friends list sees the board of the avatar you are wearing under your toys on their Friends page, and can use it — everything they do is logged. ⚡ YOLO gives them every parameter instead (VRChat's own, like Viseme, aside) and locks don't hold for them; it stays on until you turn it off. ■ STOP blocks everything they send until you press RESUME. Nothing is sent to a friend until they have your board open.

Already built boards in VRC Parameter Relay? Import from VRC Parameter Relay copies them all; the Relay's own files stay as they are.
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

For a whole page at once, press F1 (or Show me around in the status bar): the page's steps appear above it, and whatever you point at lights up with what it is. Clicks do nothing while it is on, so looking around never changes a setting. Esc leaves.
""")

        section("Where settings live on disk", f"""
{SETTINGS_DIR_DISPLAY}{os.sep}
  • modes.json               — the four routing modes + shared rig, feel and strength (schema v4)
  • known_devices.json       — global toy list (name, motor count, motor kinds)
  • app_settings.json        — global app preferences
  • sps_sources.json         — synthetic contact zones, shared by every mode
  • pishock_settings.json    — Shockers: port, safety limits, OpenShock shockers and rules
  • suits_settings.json      — Suits: bHaptics parts, OWO muscles and ceiling, zone routes
  • param_boards.json        — Avatar Remote: every avatar's boards, YOLO and STOP
  • sessions_settings.json   — session-logger preferences
  • stats.json, stats_hours.json, stats_sessions{os.sep}
                             — usage statistics (Settings → Features →
                               Usage statistics; off keeps them, Delete
                               statistics… deletes them)
""")

        license_lay = section("License", """
OscGoesPurrr is free and open source under the MIT license. It also uses other open-source projects, each under its own license — the button below lists them.
""", into=inner_lay)
        lic_btn = QPushButton("Show licenses…")
        lic_btn.setCursor(Qt.PointingHandCursor)
        lic_btn.clicked.connect(self._show_licenses)
        self._explain(lic_btn, "Show licenses",
                      "OscGoesPurrr's own license and every third-party component "
                      "this app carries, with the notices their licenses ask to be "
                      "passed on.")
        license_lay.addWidget(lic_btn, 0, Qt.AlignLeft)

        inner_lay.addStretch(1)

        # Sections for the live colour sweep: the title and each card (the
        # folded ones one by one, not their plain container). As one
        # section this page is the app's most expensive slice -- a dozen
        # long word-wrapped texts laid out again in one go.
        style_root = getattr(self, "_style_root", None)
        if callable(style_root):
            style_root(title)
            for i in range(inner_lay.count()):
                w = inner_lay.itemAt(i).widget()
                if w is details:
                    for j in range(details_lay.count()):
                        style_root(details_lay.itemAt(j).widget())
                else:
                    style_root(w)

    def _build_toy_safety_card(self) -> QWidget:
        """Anti-stuck, the safety cutoff for a frozen input. It is on by
        default and rarely touched, so it lives here rather than among
        Home's tuning tools."""
        card = _Card()
        lay = _vbox(20, 8)
        card.setLayout(lay)

        hdr = QLabel("Toy Safety")
        hdr.setObjectName("sectionTitle")
        lay.addWidget(hdr)
        lay.addWidget(self._muted_label(
            "VRChat only sends a value when it changes. If a contact stops "
            "updating — you swap avatar, your partner leaves, the link "
            "drops — its last value would keep a toy running. Anti-stuck "
            "notices a value that has frozen and stops the toy. On by "
            "default."
        ))

        self.toy_antistuck_check = ToggleSwitch("Anti-stuck")
        self.toy_antistuck_check.setChecked(
            bool(self.controller.get_app_setting("toy_antistuck_enabled", True))
        )
        lay.addWidget(self.toy_antistuck_check)

        # The two timeouts, shown only while the switch is on (hidden
        # rather than disabled, like the chime volume row above).
        times_row = QWidget()
        times_lay = _hbox(0, 8)
        # Indented to the switch's label, so the row reads as its own.
        times_lay.setContentsMargins(
            ToggleSwitch._TRACK_W + ToggleSwitch._LABEL_SPACING, 0, 0, 0)
        times_row.setLayout(times_lay)

        def seconds_spin(key: str, default: int) -> QSpinBox:
            spin = QSpinBox()
            spin.setRange(1, 600)
            spin.setSuffix("s")
            spin.setFixedWidth(86)
            spin.setValue(int(self.controller.get_app_setting(key, default)))
            return spin

        times_lay.addWidget(QLabel("Frozen part-way: stop after"))
        self.toy_antistuck_active_spin = seconds_spin("toy_antistuck_active_s", 1)
        times_lay.addWidget(self.toy_antistuck_active_spin)
        times_lay.addSpacing(14)
        times_lay.addWidget(QLabel("Held at 100%: ease off after"))
        self.toy_antistuck_peaked_spin = seconds_spin("toy_antistuck_peaked_s", 10)
        times_lay.addWidget(self.toy_antistuck_peaked_spin)
        times_lay.addStretch(1)
        lay.addWidget(times_row)
        times_row.setVisible(self.toy_antistuck_check.isChecked())
        self.toy_antistuck_check.toggled.connect(times_row.setVisible)

        self._explain(
            (self.toy_antistuck_check, times_lay), "Anti-stuck",
            "Safety cutoff for frozen inputs. VRChat only sends OSC on "
            "parameter change — if an SPS input stops updating (avatar "
            "swap, partner leaves, OSC routing loss), the last value "
            "would drive the toy forever.<br><br>"
            "A real tracked value between zero and one can never hold "
            "perfectly still — animation and IK jitter it constantly "
            "— so a value frozen <b>part-way</b> is cut quickly (1s by "
            "default). Only a value held at <b>100%</b> gets the longer "
            "fuse before a gentle ramp down, because all-the-way-in-and-"
            "held is a real state that genuinely sits at a constant 1.0."
        )

        # Connect AFTER seeding so the initial setValue/setChecked calls
        # don't echo straight back into app settings.
        self.toy_antistuck_check.toggled.connect(self._on_toy_antistuck_changed)
        self.toy_antistuck_active_spin.valueChanged.connect(
            self._on_toy_antistuck_changed)
        self.toy_antistuck_peaked_spin.valueChanged.connect(
            self._on_toy_antistuck_changed)
        return card

    def _on_toy_antistuck_changed(self, *_):
        """Persist the toy anti-stuck settings. The live routing
        tick reads them fresh each evaluation via the controller's
        `_get_toy_antistuck`, so the change takes effect on the next tick with
        no explicit recalc kick."""
        self.controller.set_app_setting(
            "toy_antistuck_enabled", bool(self.toy_antistuck_check.isChecked()))
        self.controller.set_app_setting(
            "toy_antistuck_active_s", int(self.toy_antistuck_active_spin.value()))
        self.controller.set_app_setting(
            "toy_antistuck_peaked_s", int(self.toy_antistuck_peaked_spin.value()))

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
        dlg = QDialog((getattr(self, "dialog_parent", None) or self.window))
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
