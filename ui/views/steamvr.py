"""SteamVR Haptics view, pattern editors, and per-tracker cards.

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


class SteamVRMixin:

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
        _install_rainbow_scrollbars(scroll)
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

    def _on_steamvr_toys_reinstall_clicked(self):
        """Force a re-copy of the bundled driver DLL/manifest into the
        per-user folder and re-register the path. Used after rebuilding the
        C++ driver so the new bits land without toggling the whole feature
        off/on."""
        try:
            result = self.controller.reinstall_steamvr_toys_driver()
        except Exception as e:
            self.log_message(f"Reinstall failed: {e}")
            return
        if result.get("ok"):
            self.log_message(
                f"Toy driver reinstalled to: {result.get('dll')}\n"
                "Restart SteamVR for the updated DLL to take effect."
            )
            return
        kind = result.get("error_kind", "")
        if kind == "dll_locked":
            self.log_message(
                "Reinstall failed: SteamVR is currently using the existing toy "
                "driver DLL, so we can't overwrite it. Fully exit SteamVR "
                "(tray icon -> Exit), then click Reinstall again."
            )
        elif kind == "bundle_missing":
            self.log_message(
                "Reinstall failed: the bundled DLL is missing from this build "
                "of OscGoesPurrr. Rebuild the C++ driver (build_driver.bat) "
                "and then rebuild the OscGoesPurrr EXE (build_OGP.bat)."
            )
        elif kind == "register_failed":
            self.log_message(
                "Reinstall failed: could not update SteamVR's openvrpaths.vrpath. "
                "Check that you have write access to "
                "%LOCALAPPDATA%\\openvr\\openvrpaths.vrpath."
            )
        else:
            self.log_message(
                f"Reinstall failed ({kind or 'unknown'}). See log lines above."
            )

    def _on_steamvr_show_toys_toggled(self, checked: bool):
        if self._is_updating_steamvr:
            return
        try:
            status = self.controller.set_steamvr_toys_enabled(bool(checked))
        except Exception as e:
            self.log_message(f"SteamVR toys toggle failed: {e}")
            return
        if checked and status.get("install_failed"):
            # Most likely cause: this build of the app doesn't include a
            # compiled driver_oscgoespurrr.dll yet. The C++ driver has to be
            # built once via steamvr_toy_driver/build.bat and committed.
            self.log_message(
                "SteamVR toys: install FAILED — the bundled driver DLL is missing. "
                "This build of OscGoesPurrr was packaged without "
                "steamvr_toy_driver/bin/win64/driver_oscgoespurrr.dll. "
                "See steamvr_toy_driver/README.md for the one-time build steps."
            )
        elif checked and status.get("first_install"):
            self.log_message(
                "SteamVR toy driver installed. Restart SteamVR to see your toys "
                "in the device list."
            )
        elif checked:
            self.log_message(
                "SteamVR toys enabled. Restart SteamVR if this is the first launch "
                "after the driver was installed."
            )
        else:
            self.log_message("SteamVR toys disabled.")

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
        if hasattr(self, "steamvr_show_toys_check"):
            try:
                toys_status = self.controller.get_steamvr_toys_status()
            except Exception:
                toys_status = {}
            self.steamvr_show_toys_check.setChecked(bool(toys_status.get("enabled")))
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
        class_tag = QLabel(self._DEVICE_CLASS_LABEL.get(dev_class, dev_class.title()).upper())
        class_tag.setProperty("role", "pill")
        class_tag.setProperty("tone", "info")
        header.addWidget(class_tag)

        title = QLabel(f"{t.get('model', '?')}  ·  {serial}")
        tf = title.font(); tf.setBold(True); tf.setPointSize(11)
        title.setFont(tf)
        header.addWidget(title)
        header.addStretch(1)

        bat = t.get("battery")
        bat_pct: Optional[int] = None
        if bat is not None:
            try:
                bat_pct = int(float(bat) * 100)
            except Exception:
                bat_pct = None
        bat_label = QLabel(f"{bat_pct}%" if bat_pct is not None else "— %")
        bat_label.setProperty("role", "pill")
        # Tone reflects battery health so the eye picks it up at a glance.
        if bat_pct is None:
            bat_label.setProperty("tone", "info")
        elif bat_pct <= 20:
            bat_label.setProperty("tone", "err")
        elif bat_pct <= 40:
            bat_label.setProperty("tone", "warn")
        else:
            bat_label.setProperty("tone", "ok")
        header.addWidget(bat_label)

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
        battery_edit.setPlaceholderText("HMD_Battery  (leave blank to disable)")
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
            addr_edit.setPlaceholderText("MyParam;OtherParam")
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
            new_cfg["battery_osc_address"] = strip_param_prefix(battery_edit.text())
            if addr_edit is not None:
                addrs = [
                    strip_param_prefix(a)
                    for a in addr_edit.text().split(";")
                    if a.strip()
                ]
                addrs = [a for a in addrs if a]
                if not addrs:
                    addrs = ["..."]
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
