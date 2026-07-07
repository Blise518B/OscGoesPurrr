"""Settings page and Help page.

Mixin for ui_components.OscGoesPurrrUI. Relies on attributes initialised
by OscGoesPurrrUI.__init__ (self.controller, self.invoker, etc.)."""

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


class SettingsMixin:

    # ----------------------------------------------------------
    # Settings view
    # ----------------------------------------------------------

    def _build_settings_view(self, parent_layout: QVBoxLayout):
        title = QLabel("Application Settings")
        title.setObjectName("viewTitle")
        title.setAlignment(Qt.AlignHCenter)
        parent_layout.addWidget(title)

        # Two tabs: the existing settings cards live under "General"
        # unchanged; the session-logger UI lives under "Sessions". Same
        # rebinding trick as the bHaptics view — `parent_layout` is
        # repointed at the General tab's layout so the existing
        # parent_layout.addWidget(...) calls below keep working without
        # any rename.
        from PySide6.QtWidgets import QTabWidget as _QTabWidget
        tabs = _QTabWidget()
        general_tab = QWidget()
        general_lay = _vbox(10, 8)
        general_tab.setLayout(general_lay)
        sessions_tab = QWidget()
        sessions_lay = _vbox(10, 8)
        sessions_tab.setLayout(sessions_lay)
        tabs.addTab(general_tab, "General")
        tabs.addTab(sessions_tab, "Sessions")
        parent_layout.addWidget(tabs)

        # SessionsMixin renders the Sessions tab content; General keeps
        # the original card stack.
        self._build_sessions_panel(sessions_lay)
        parent_layout = general_lay

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
        switch_lay.addWidget(self._make_help_badge(
            "OSC network bind",
            "<b>0.0.0.0</b> listens on every network interface — required "
            "when VRChat runs on another device (e.g. a standalone "
            "headset) and the safe default on a home network. "
            "<b>127.0.0.1</b> only accepts traffic from this PC — pick it "
            "on untrusted networks when VRChat runs locally. Restart the "
            "app after changing."
        ))
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

        # ---- Intiface Engine Card ----
        # How the Buttplug toy server is provided: the built-in engine we
        # bundle and launch ourselves (default — nothing else to run), or an
        # external Intiface Central the user starts separately.
        ife_card = _Card()
        ife_lay = _vbox(20, 6)
        ife_card.setLayout(ife_lay)

        hdr = QLabel("Intiface Engine")
        hdr.setObjectName("cardHeader")
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
        parent_layout.addWidget(ife_card)

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
        ql_lay.addWidget(self._muted_label(
            "Holds ogp_debug.log, ogp_crash.log and intiface_engine.log. Zip "
            "these if you need to report a crash or a toy that won't connect."
        ))

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

        # One row per controller feature flag — the flag map is the source
        # of truth so a new backend can't be forgotten here (the four newer
        # backends were missing from this card even though their toggles
        # were fully plumbed). Labeled keys keep this curated order; any
        # flag the controller grows later still gets a row (raw key label).
        _feature_labels = {
            "feature_intiface":         "Intiface toy communication (Buttplug.io)",
            "feature_bhaptics":         "bHaptics integration",
            "feature_steamvr_haptics":  "SteamVR tracker haptics",
            "feature_steamvr_battery":  "SteamVR battery → OSC broadcast",
            "feature_pishock":          "PiShock shock / vibrate events",
            "feature_coyote":           "DG-Lab Coyote e-stim",
            "feature_owo":              "OWO suit EMS",
            "feature_handy":            "The Handy stroker (cloud)",
            "feature_osc_inspector":    "OSC Inspector (debug view)",
        }
        try:
            flag_keys = list(self.controller.get_feature_flags().keys())
        except Exception:
            flag_keys = list(_feature_labels.keys())
        ordered = [k for k in _feature_labels if k in flag_keys]
        ordered += [k for k in flag_keys if k not in _feature_labels]
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

        # Show toys as virtual SteamVR devices — registers a small bundled
        # OpenVR driver so connected toys appear in SteamVR's device strip.
        try:
            _toys_status = self.controller.get_steamvr_toys_status()
        except Exception:
            _toys_status = {"supported": False, "enabled": False}
        if _toys_status.get("supported"):
            self.steamvr_show_toys_check = ToggleSwitch("Show toys in SteamVR (Joke)")
            self.steamvr_show_toys_check.setChecked(bool(_toys_status.get("enabled")))
            self.steamvr_show_toys_check.toggled.connect(self._on_steamvr_show_toys_toggled)
            svr_lay.addWidget(self.steamvr_show_toys_check)
            self.steamvr_show_toys_hint = self._muted_label(
                "Adds the user's connected toys to SteamVR's device list with "
                "their name, battery, and icon. Restart SteamVR after enabling."
            )
            svr_lay.addWidget(self.steamvr_show_toys_hint)

            # Manual reinstall button — useful if the DLL was rebuilt with a
            # fix and you want to recopy it without flipping the feature off.
            self.steamvr_toys_reinstall_btn = QPushButton("Reinstall toy driver")
            self.steamvr_toys_reinstall_btn.setProperty("role", "secondary")
            self.steamvr_toys_reinstall_btn.clicked.connect(self._on_steamvr_toys_reinstall_clicked)
            svr_lay.addWidget(self.steamvr_toys_reinstall_btn)

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

        section("SPS Sources — synthetic contact zones", """
The SPS Sources tab lets you build a "virtual" SPS zone out of raw VRChat contact receivers, for spots your avatar doesn't expose as an OGB zone. Each source combines:

  • Proximity — one or more proximity receivers. The loudest one wins.
  • Activation — binary gate contacts. The proximity only counts while at least one activation contact is firing, so you can pin the signal to a very specific spot. Leave empty for no gate.
  • Velocity — binary on-enter contacts. While any of them fires, the output is multiplied by the "Velocity ×" amount (a thrust/speed boost).
  • Max value — caps the raw proximity before the multiplier is applied.

Type all the contact parameter names comma-separated (the /avatar/parameters/ prefix is optional). Each source you define then appears — by its name — in the Device Routing zone picker (under "Custom Sources") and in the bHaptics Cross-Routing picker, where it routes exactly like an auto-detected zone. The sources are global (shared by every profile).
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

        section("PiShock", """
Fires PiShock shock / vibrate / beep events from avatar contacts. Unlike the continuous backends, a shock is a discrete event: a zone fires once when its contact strength crosses the threshold, then must re-arm by dropping below threshold − hysteresis before it can fire again.

Transports:
  • serial — a PiShock hub plugged into this PC over USB (COM port + shocker ID). Lowest latency, works offline.
  • cloud  — the PiShock web API (username, API key, share code).

Per-zone rules (Source → Trigger → Output folds):
  • Source: an OGB zone or synthetic SPS source plus interaction filters. The fold's ring and number show the live contact strength.
  • Trigger: op (shock / vibrate / beep), threshold, hysteresis.
  • Output: intensity range (contact strength at fire time maps min→max), duration, per-zone cooldown, optional Sustain that re-fires every Cadence seconds while held.

Safety is layered: the engine hard-caps intensity / duration / interval on EVERY fire (settings can only lower the caps), each zone has its own cooldown, and a global sliding-window rate limit stops multiple zones ganging up. Test with vibrate first; keep Auto Connect off until you trust the config.
""")

        section("DG-Lab Coyote", """
Drives a DG-Lab Coyote 3.0 e-stim unit over Bluetooth LE directly from this PC (no phone app needed; requires a BLE adapter and pip install bleak).

Setup: Scan, pick the device to fill in its address, Apply. Set the hardware soft strength limits LOW before first connecting — they are written to the device itself, so no routing config or bug can exceed them.

Channels A and B each route independently (Source → Shaping → Output folds):
  • Source: OGB zone / synthetic source + interaction filters, with a live strength ring.
  • Shaping: strength below the threshold outputs nothing; above it, (strength − threshold) × gain sets the level.
  • Output: max strength scales onto the channel's 0-200 range (still capped by the hardware soft limit); waveform frequency / intensity set the pulse texture.

The status card shows live battery and the current A/B strengths.
""")

        section("OWO Suit", """
Maps avatar contacts onto OWO muscle-group sensations (the suit's ten muscles, Pectoral through Lumbar).

Requirements: the My OWO phone app on the same Wi-Fi (use 'Scan Game' to pair), plus the OWO SDK on this PC — pip install pythonnet and drop OWO.dll into the owo-sdk folder. Without those the backend shows as unavailable.

Per-muscle routing (Source → Shaping → Output folds):
  • Source: OGB zone / synthetic source + interaction filters, with a live strength ring.
  • Shaping: threshold + gain, same math as the Coyote channels.
  • Output: max intensity caps the muscle's 0-100 sensation level.

Sensation frequency (Connection card) sets the texture suit-wide — low feels like slow thumps, high like a dense buzz; per-muscle intensity stays separate.
""")

        section("Real-Time OSC Inspector", """
OSC Inspector shows every OSC parameter your avatar is broadcasting. It starts automatically when you open the page and stops when you leave — useful for finding the exact name of a parameter before mapping it to a motor / tracker / bHaptics zone.

Two views are stacked:
  • Top: the in-place QTableWidget (preserves scroll position across refreshes).
  • Bottom: a legacy HTML view kept as a diagnostic — if the top freezes but the bottom ticks, the bug is in the table update path; if both freeze, the OSC pipeline upstream is the suspect.

Both consume the same data, so they stay in lockstep.
""")

        section("Help Mode — in-place explanations", """
Flip the "Help Mode" toggle in the sidebar (or in the Device Routing header) and small "?" badges appear next to controls all over the app — zone pickers, gate knobs, safety caps, fold headers, connection sections. Click a badge for a short explanation of exactly that control, then click anywhere else to dismiss it. Turn the toggle off to hide every badge again; the layout doesn't shift either way.
""")

        section("Where settings live on disk", """
%APPDATA%\\OscGoesPurrr\\
  • profiles.json            — per-profile device settings
  • known_devices.json       — global toy list (name, motor count, motor kinds)
  • app_settings.json        — global app preferences
  • steamvr_settings.json    — autostart, patterns, per-tracker config, battery interval
  • bhaptics_settings.json   — Player endpoint, per-device enable + intensity, anti-stuck
  • pishock_settings.json    — transport, credentials, safety caps, zone rules
  • coyote_settings.json     — device address, hardware soft limits, channel configs
  • owo_settings.json        — connection, sensation frequency, per-muscle configs
  • sessions_settings.json   — session-logger preferences
""")

        inner_lay.addStretch(1)
