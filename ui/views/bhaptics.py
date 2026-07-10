"""bHaptics view, per-device cards, and dot-grid debug overlays.

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
from ui.fold_strip import FoldCard as _FoldCard, FoldStrip as _FoldStrip
from ui.views._backend_common import (
    on_zone_type_changed as _on_zone_type_changed,
    populate_zone_combo as _populate_zone_combo,
    run_connect_now as _run_connect_now,
)
from ui.widgets import (
    ToggleSwitch,
    Invoker as _Invoker,
    MainWindow as _MainWindow,
    Card as _Card,
    BHapticsDotGrid as _BHapticsDotGrid,
    BHapticsDotPicker as _BHapticsDotPicker,
    SliderProxy as _SliderProxy,
    ProgressProxy as _ProgressProxy,
    RainbowMeter as _RainbowMeter,
    install_rainbow_scrollbars as _install_rainbow_scrollbars,
)


class BHapticsMixin:

    # ----------------------------------------------------------
    # bHaptics view
    # ----------------------------------------------------------

    _is_updating_bhaptics = False

    # Per-position dot widgets, refreshed by _refresh_bhaptics_grids.
    # `_bhaptics_grids` holds the OUTPUT grid (post anti-stuck, post override —
    # what's actually sent to the device, and what the click-to-test interacts
    # with). `_bhaptics_raw_grids` holds the RAW input mirror.
    # `_bhaptics_strips` holds each device card's fold strip so the same
    # fast tick can charge the activity rings + arrows.
    _bhaptics_grids: Dict[str, "_BHapticsDotGrid"] = {}
    _bhaptics_raw_grids: Dict[str, "_BHapticsDotGrid"] = {}
    _bhaptics_strips: Dict[str, "_FoldStrip"] = {}

    # Tracks the last set of detected device positions so the device list
    # only rebuilds when the avatar's bHaptics-capable set actually changes.
    _bhaptics_last_detected: Optional[frozenset] = None

    def _build_bhaptics_view(self, parent_layout: QVBoxLayout):
        title = QLabel("bHaptics")
        title.setObjectName("viewTitle")
        title.setAlignment(Qt.AlignHCenter)
        parent_layout.addWidget(title)

        # The bHaptics view is split into two tabs: "Devices" holds the
        # existing v1-OSC plumbing (status, anti-stuck, connected-bool,
        # per-device cards) and "Cross-Routing" is the SPS-to-suit
        # mirror config. Both share the same engine + settings so their
        # outputs merge inside bhaptics_router (max-wins per dot).
        from PySide6.QtWidgets import QTabWidget as _QTabWidget
        tabs = _QTabWidget()
        devices_tab = QWidget()
        devices_lay = _vbox(10, 8)
        devices_tab.setLayout(devices_lay)
        cross_tab = QWidget()
        cross_lay = _vbox(10, 8)
        cross_tab.setLayout(cross_lay)
        tabs.addTab(devices_tab, "Devices")
        tabs.addTab(cross_tab, "Cross-Routing")
        parent_layout.addWidget(tabs)

        # Build the Cross-Routing tab content via the dedicated builder
        # (defined further down). The Devices tab is the existing
        # card-stack below; we rebind `parent_layout` to its layout so
        # the existing parent_layout.addWidget(...) calls keep working
        # without any per-card rename.
        self._build_bhaptics_cross_routing(cross_lay)
        parent_layout = devices_lay

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

        self.bhaptics_connect_btn = QPushButton("Connect Now")
        self.bhaptics_connect_btn.setMinimumHeight(BTN_HEIGHT_SMALL)
        self.bhaptics_connect_btn.clicked.connect(self._on_bhaptics_connect_clicked)
        action_row.addWidget(self.bhaptics_connect_btn)

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

        # ---- VRChat connected-bool card ----
        # When the bHaptics Player connects/disconnects we can flip a bool
        # avatar parameter so an animation reacts (e.g., show the suit
        # mesh). User picks the parameter name to match whatever their
        # avatar exposes; the /avatar/parameters/ prefix is added at send
        # time so the user just sees the bare name.
        oc_card = _Card()
        oc_lay = _vbox(14, 6)
        oc_card.setLayout(oc_lay)
        oc_hdr = QLabel("VRChat connected-state parameter")
        oc_hdr.setObjectName("sectionTitle")
        oc_lay.addWidget(oc_hdr)
        oc_lay.addWidget(self._muted_label(
            "Send a bool to a VRChat avatar parameter whenever the bHaptics Player connects or "
            "disconnects. Use it to auto-enable a suit-on animation. Re-sent on VRChat OSC "
            "reconnect and on /avatar/change so the value survives avatar reloads."
        ))
        oc_row = _hbox(0, 8)
        self.bhaptics_osc_connected_check = ToggleSwitch("Send connected-state bool")
        self.bhaptics_osc_connected_check.toggled.connect(self._on_bhaptics_osc_connected_changed)
        oc_row.addWidget(self.bhaptics_osc_connected_check)
        oc_row.addSpacing(16)
        oc_row.addWidget(QLabel("Parameter"))
        self.bhaptics_osc_connected_edit = QLineEdit()
        self.bhaptics_osc_connected_edit.setPlaceholderText("bHaptics_Connected")
        self.bhaptics_osc_connected_edit.setFixedWidth(220)
        self.bhaptics_osc_connected_edit.editingFinished.connect(self._on_bhaptics_osc_connected_changed)
        oc_row.addWidget(self.bhaptics_osc_connected_edit)
        oc_row.addStretch(1)
        oc_lay.addLayout(oc_row)
        parent_layout.addWidget(oc_card)

        # ---- Per-device cards ----
        list_card = _Card(dark_bg=True)
        llay = _vbox(10, 6)
        list_card.setLayout(llay)
        lh = QLabel("Devices")
        lh.setObjectName("sectionTitle")
        llay.addWidget(lh)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        _install_rainbow_scrollbars(scroll)
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
        # Only animate the debug dots while the page is on screen —
        # this 10 Hz pump (two engine snapshots + grid/strip updates)
        # is pure cost on any other page. select_view refreshes the
        # page on arrival so nothing looks stale.
        view = self.views.get("bHaptics")
        if view is not None and not view.isVisible():
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
        # Charge each card's fold strip: Input ring follows the hottest
        # raw dot, Routing/Output the hottest output dot (post anti-stuck
        # and overrides — what the suit actually feels).
        for pos, strip in self._bhaptics_strips.items():
            try:
                raw_vals = raw_snap.get(pos) or []
                out_vals = snap.get(pos) or []
                raw_max = max(raw_vals) / 100.0 if raw_vals else 0.0
                out_max = max(out_vals) / 100.0 if out_vals else 0.0
                strip.set_levels([raw_max, out_max, out_max])
            except RuntimeError:
                continue
        # Cross-Routing entry strips: Source ring = live zone strength;
        # Shaping/Output mirror the router's (strength − threshold) ×
        # gain shaping, zeroed while the master enable is off.
        rows = self._bhaptics_xroute_rows
        if rows:
            specs = []
            live_rows = []
            for row in rows:
                try:
                    specs.append((
                        row["ogb_zone"].currentText(),
                        row["zone_type"].currentText(),
                        [fn for fn, cb in row["filters"].items() if cb.isChecked()],
                    ))
                    live_rows.append(row)
                except RuntimeError:
                    continue
            try:
                strengths = self.controller.get_live_zone_strengths(specs)
            except Exception:
                return
            try:
                master_on = bool(self.bhaptics_xroute_enable_check.isChecked())
            except (AttributeError, RuntimeError):
                master_on = False
            for row, strength in zip(live_rows, strengths):
                try:
                    thr = float(row["threshold"].value())
                    gain = float(row["gain"].value())
                    if not master_on or strength <= thr:
                        shaped = 0.0
                    else:
                        shaped = max(0.0, min(1.0, (strength - thr) * gain))
                    row["strip"].set_levels([strength, shaped, shaped])
                    row["source_fold"].set_value(strength)
                    self._update_bhaptics_xroute_subtitles(row)
                except RuntimeError:
                    continue

    # ---- bHaptics handlers ----

    def _on_bhaptics_auto_connect_toggled(self, checked: bool):
        if self._is_updating_bhaptics:
            return
        self.controller.set_bhaptics_auto_connect(bool(checked))

    def _on_bhaptics_connect_clicked(self):
        # The websocket connect has a 2 s timeout — keep it off the Qt
        # thread (which also hosts the Buttplug routing tick).
        _run_connect_now(
            self, "bHaptics", self.controller.bhaptics_connect_now,
            self._refresh_bhaptics_status_only,
            buttons=[self.bhaptics_connect_btn],
            failed_hint=" (is the Player running?)",
        )

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

    def _on_bhaptics_osc_connected_changed(self, *_):
        if self._is_updating_bhaptics:
            return
        enabled = bool(self.bhaptics_osc_connected_check.isChecked())
        # Strip the prefix client-side so the controller's persisted form
        # matches what the user re-sees in the box (no leading slash).
        raw = self.bhaptics_osc_connected_edit.text()
        param = strip_param_prefix(raw) or "bHaptics_Connected"
        self.controller.set_bhaptics_osc_connected(enabled, param)
        if param != self.bhaptics_osc_connected_edit.text():
            self.bhaptics_osc_connected_edit.setText(param)

    def _refresh_bhaptics_status_only(self):
        view = self.views.get("bHaptics")
        if view is not None and not view.isVisible():
            return
        try:
            status = self.controller.get_bhaptics_status()
        except Exception:
            return
        self._is_updating_bhaptics = True
        try:
            self._apply_bhaptics_status(status, full=False)
            # Rebuild the device list only when the avatar's detected device
            # set actually changes (avatar swap, freshly-loaded params).
            # Doing this in the cheap status tick keeps the page responsive
            # to avatar changes without tearing down widgets every refresh.
            detected = frozenset(
                d["position"] for d in status.get("devices", []) if d.get("detected"))
            if detected != self._bhaptics_last_detected:
                self._bhaptics_last_detected = detected
                self._rebuild_bhaptics_device_list(status.get("devices", []))
        finally:
            self._is_updating_bhaptics = False

    def _refresh_bhaptics_view(self):
        if not hasattr(self, "bhaptics_device_list_layout"):
            return
        self._is_updating_bhaptics = True
        try:
            status = self.controller.get_bhaptics_status()
            self._apply_bhaptics_status(status, full=True)
            devices = status.get("devices", [])
            self._bhaptics_last_detected = frozenset(
                d["position"] for d in devices if d.get("detected")
            )
            self._rebuild_bhaptics_device_list(devices)
        finally:
            self._is_updating_bhaptics = False

    def _apply_bhaptics_status(self, status: dict, full: bool = True):
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

        self.bhaptics_auto_connect_check.setChecked(bool(status.get("auto_connect")))
        if not full:
            # Periodic tick: status + toggle only. The endpoint / OSC-param
            # fields are Apply-gated — rewriting them from the store on a
            # timer clobbers whatever the user is typing.
            return

        # Endpoint widgets — only set if value differs to avoid cursor jumps.
        host = status.get("host", "127.0.0.1")
        port = int(status.get("port", 15881))
        if self.bhaptics_host_edit.text() != host:
            self.bhaptics_host_edit.setText(host)
        if self.bhaptics_port_spin.value() != port:
            self.bhaptics_port_spin.setValue(port)

        oc_cfg = status.get("osc_connected") or {}
        if hasattr(self, "bhaptics_osc_connected_check"):
            self.bhaptics_osc_connected_check.setChecked(bool(oc_cfg.get("enabled", True)))
            current_param = (oc_cfg.get("param") or "bHaptics_Connected")
            if self.bhaptics_osc_connected_edit.text() != current_param:
                self.bhaptics_osc_connected_edit.setText(current_param)

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
        self._bhaptics_strips = {}
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
        """One device as a fold strip — Input → Routing → Output — in
        the Device Routing chain's design language (folds joined by
        arrows, activity rings charged by live dot levels; see
        ui/fold_strip.py). The two live dot grids stay permanently on
        display as non-expandable folds; the Routing fold in the middle
        opens into the enable + intensity editor."""
        position = d["position"]
        cfg = d.get("config", {})
        nodes = int(d.get("node_count", 0))

        card = _Card()
        # Cap card width so the device list reads as a column of compact
        # cards instead of stretching with the window. Wide enough for
        # the two dot-grid folds plus the routing fold between them.
        card.setMaximumWidth(640)
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

        strip = _FoldStrip()
        cols, rows = d.get("grid", (nodes, 1))

        # ---- Input fold: raw OSC mirror, always visible ----
        in_fold = strip.add_fold(_FoldCard("input", "Raw input", expandable=False))
        in_fold.add_header_widget(self._make_help_badge(
            "Raw input",
            "Mirror of the v1 bHaptics OSC values exactly as the avatar "
            "broadcasts them — before intensity scaling, anti-stuck, or "
            "test overrides. If a dot lights here but not on Output, "
            "something downstream is masking it (anti-stuck, disabled "
            "device, intensity at 0)."
        ))
        raw_grid = _BHapticsDotGrid(
            node_count=nodes, cols=int(cols), rows=int(rows), interactive=False
        )
        self._bhaptics_raw_grids[position] = raw_grid
        in_fold.quick_layout.addWidget(raw_grid, 0, Qt.AlignHCenter)

        # ---- Routing fold: enable + intensity ----
        rt_fold = strip.add_fold(_FoldCard("routing", "Routing"))
        rt_fold.add_header_widget(self._make_help_badge(
            "Routing",
            "Click to edit. <b>Enabled</b> gates the whole device; "
            "<b>Intensity</b> scales every dot's strength (100% = "
            "pass-through). Applies to both the v1 OSC layer and "
            "Cross-Routing entries targeting this device."
        ))
        enabled = ToggleSwitch("Enabled")
        enabled.setChecked(bool(cfg.get("enabled", True)))
        rt_fold.editor_layout.addWidget(enabled)
        intensity_row = _hbox(0, 8)
        intensity_row.addWidget(QLabel("Intensity"))
        slider = QSlider(Qt.Horizontal)
        slider.setRange(0, 100)
        slider.setValue(int(cfg.get("intensity", 100)))
        slider.setMinimumWidth(120)
        slider.setMaximumWidth(240)
        intensity_row.addWidget(slider, 1)
        intensity_label = QLabel(f"{slider.value()}%")
        intensity_label.setMinimumWidth(40)
        intensity_row.addWidget(intensity_label)
        rt_fold.editor_layout.addLayout(intensity_row)

        # ---- Output fold: what's actually sent (anti-stuck applied,
        # click-and-hold a dot to test-fire it) ----
        out_fold = strip.add_fold(_FoldCard("output", "Output", expandable=False))
        out_fold.add_header_widget(self._make_help_badge(
            "Output",
            "What the suit actually feels: after intensity scaling, "
            "anti-stuck ramping, and manual overrides, with Cross-Routing "
            "entries max-merged in. <b>Click and hold any dot</b> to fire "
            "it at 100% as a debug test."
        ))
        grid = _BHapticsDotGrid(node_count=nodes, cols=int(cols), rows=int(rows))
        self._bhaptics_grids[position] = grid
        out_fold.quick_layout.addWidget(grid, 0, Qt.AlignHCenter)

        lay.addWidget(strip)
        self._bhaptics_strips[position] = strip

        # Debug: click-and-hold a dot on the output grid to fire it at 100%.
        # Routed through the controller so the router can max-merge it with
        # the live OSC output. The raw grid stays non-interactive — it only
        # mirrors what's actually coming in over OSC.
        grid.dotPressed.connect(lambda idx, pos=position: self.controller.set_bhaptics_manual_dot(pos, idx, 100))
        grid.dotReleased.connect(lambda idx, pos=position: self.controller.set_bhaptics_manual_dot(pos, idx, None))

        def update_subtitle():
            rt_fold.set_subtitle(
                f"{'on' if enabled.isChecked() else 'off'}"
                f" · {slider.value()}%")
        update_subtitle()

        def push(_=None):
            if self._is_updating_bhaptics:
                return
            intensity_label.setText(f"{slider.value()}%")
            update_subtitle()
            self.controller.set_bhaptics_device(position, {
                "enabled": enabled.isChecked(),
                "intensity": int(slider.value()),
            })

        enabled.toggled.connect(push)
        slider.valueChanged.connect(push)
        return card

    # ----------------------------------------------------------
    # Cross-Routing sub-tab (SPS -> bHaptics mirror)
    # ----------------------------------------------------------
    #
    # The user defines entries that mirror OGB SPS contacts (Touch/Pen)
    # onto specific bHaptics dot indices. Each entry is independent and
    # max-merges with the v1 OSC layer inside bhaptics_router. There are
    # no baked-in suggestions — entries start empty and the user picks
    # zones from whatever the current avatar is broadcasting.

    _is_updating_bhaptics_xroute = False
    _bhaptics_xroute_rows: List[Dict[str, Any]] = []
    _bhaptics_xroute_positions: List[str] = []
    # position -> (cols, rows, node_count); fed to each row's picker so
    # the grid matches the chosen device layout.
    _bhaptics_xroute_geom: Dict[str, tuple] = {}

    def _build_bhaptics_cross_routing(self, parent_layout: QVBoxLayout):
        parent_layout.addWidget(self._muted_label(
            "Mirror OGB SPS contacts (Touch / Pen) into bHaptics dots. Each "
            "entry maps one avatar zone + filter to a set of dots on one "
            "device. Output max-merges with the regular bHapticsOSC layer — "
            "whichever signal is strongest at any dot wins."
        ))

        # Master enable + add row
        top_row = _hbox(0, 8)
        self.bhaptics_xroute_enable_check = ToggleSwitch("Enable Cross-Routing")
        self.bhaptics_xroute_enable_check.toggled.connect(
            self._on_bhaptics_xroute_enable_changed
        )
        top_row.addWidget(self.bhaptics_xroute_enable_check)
        top_row.addStretch(1)
        refresh_btn = QPushButton("Refresh zones")
        refresh_btn.setMinimumHeight(BTN_HEIGHT_SMALL)
        refresh_btn.setToolTip(
            "Re-read the avatar's detected SPS zones and refresh the "
            "zone pickers below."
        )
        refresh_btn.clicked.connect(self._rebuild_bhaptics_xroute_entries)
        top_row.addWidget(refresh_btn)
        add_btn = QPushButton("+ Add entry")
        add_btn.setMinimumHeight(BTN_HEIGHT_SMALL)
        add_btn.clicked.connect(self._on_bhaptics_xroute_add)
        top_row.addWidget(add_btn)
        parent_layout.addLayout(top_row)

        # Cache the device-position list + per-position geometry once.
        # Prefer the live engine report; fall back to the hard-coded
        # table if the status call ever fails so the picker is never
        # empty. Geometry feeds the per-row dot picker — when the user
        # changes the position combo we reconfigure the picker to the
        # new device's (cols, rows, node_count).
        positions: List[str] = []
        geom: Dict[str, tuple] = {}
        try:
            devices = self.controller.get_bhaptics_status().get("devices", []) or []
            for d in devices:
                pos = d.get("position")
                if not pos:
                    continue
                positions.append(pos)
                cols, rows = d.get("grid", (1, 1))
                geom[pos] = (int(cols), int(rows), int(d.get("node_count", 0)))
        except Exception:
            positions = []
        if not positions:
            fallback_grids = {
                "Head": (6, 1), "VestFront": (4, 5), "VestBack": (4, 5),
                "ForearmL": (2, 3), "ForearmR": (2, 3),
                "HandL": (3, 1), "HandR": (3, 1),
                "FootL": (3, 1), "FootR": (3, 1),
            }
            for pos, _slot, count in self._bhaptics_device_table_fallback():
                positions.append(pos)
                c, r = fallback_grids.get(pos, (count, 1))
                geom[pos] = (c, r, count)
        self._bhaptics_xroute_positions = positions
        self._bhaptics_xroute_geom = geom

        # Scroll area for entries
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        _install_rainbow_scrollbars(scroll)
        inner = QWidget()
        self.bhaptics_xroute_list_layout = _vbox(8, 8)
        inner.setLayout(self.bhaptics_xroute_list_layout)
        scroll.setWidget(inner)
        parent_layout.addWidget(scroll, 1)

        self._rebuild_bhaptics_xroute_entries()

    @staticmethod
    def _bhaptics_device_table_fallback():
        """Static fallback so the position picker still has a sane list
        even before the engine reports devices."""
        return [
            ("Head", None, 6),
            ("VestFront", None, 20),
            ("VestBack", None, 20),
            ("ForearmL", None, 6),
            ("ForearmR", None, 6),
            ("HandL", None, 3),
            ("HandR", None, 3),
            ("FootL", None, 3),
            ("FootR", None, 3),
        ]

    def _rebuild_bhaptics_xroute_entries(self):
        """Tear down + rebuild the entry list from the persisted config.
        Called on view init, after add/delete, and when the user hits
        Refresh (which also re-reads detected zones)."""
        if not hasattr(self, "bhaptics_xroute_list_layout"):
            return
        self._is_updating_bhaptics_xroute = True
        try:
            cfg = self.controller.get_bhaptics_sps_mirror()
            self.bhaptics_xroute_enable_check.setChecked(
                bool(cfg.get("enabled", False))
            )
            self._bhaptics_xroute_rows = []
            while self.bhaptics_xroute_list_layout.count():
                item = self.bhaptics_xroute_list_layout.takeAt(0)
                w = item.widget()
                if w is not None:
                    w.deleteLater()
            entries = cfg.get("entries", []) or []
            if not entries:
                self.bhaptics_xroute_list_layout.addWidget(self._muted_label(
                    "No entries yet. Click '+ Add entry' to map an OGB SPS "
                    "zone onto one or more bHaptics dots."
                ))
            else:
                for idx, entry in enumerate(entries):
                    card = self._build_bhaptics_xroute_entry_card(idx, entry)
                    self.bhaptics_xroute_list_layout.addWidget(card, 0, Qt.AlignLeft)
            self.bhaptics_xroute_list_layout.addStretch(1)
        finally:
            self._is_updating_bhaptics_xroute = False

    def _build_bhaptics_xroute_entry_card(self, idx: int,
                                          entry: Dict[str, Any]) -> QFrame:
        """One Cross-Routing entry as a fold strip — Source → Shaping →
        Output — in the Device Routing chain's design language, with
        activity rings charged by the live zone strength (see
        ui/fold_strip.py)."""
        card = _Card()
        card.setMaximumWidth(860)
        lay = _vbox(12, 6)
        card.setLayout(lay)

        # --- Row 1: name + delete ---
        row1 = _hbox(0, 8)
        row1.addWidget(QLabel("Name"))
        name_edit = QLineEdit(str(entry.get("name", "")))
        name_edit.setPlaceholderText("Mirror")
        name_edit.setMinimumWidth(180)
        name_edit.editingFinished.connect(
            lambda i=idx: self._push_bhaptics_xroute_entry(i)
        )
        row1.addWidget(name_edit)
        row1.addStretch(1)
        del_btn = QPushButton("Delete")
        del_btn.setMinimumHeight(BTN_HEIGHT_SMALL)
        del_btn.clicked.connect(lambda _=False, i=idx: self._on_bhaptics_xroute_delete(i))
        row1.addWidget(del_btn)
        lay.addLayout(row1)

        # Fold strip — Source → Shaping → Output, same design language
        # as the other backend cards (see ui/fold_strip.py).
        strip = _FoldStrip()

        # ---- Source fold: which contact to mirror ----
        src_fold = strip.add_fold(_FoldCard("source", "Source", show_value=True))
        src_fold.add_header_widget(self._make_help_badge(
            "Cross-routing source",
            "The avatar contact to mirror: an OGB zone (or synthetic SPS "
            "source) plus the interaction filters that count. The "
            "strongest matching filter's 0–1 value drives the selected "
            "dots each tick."
        ))
        se = src_fold.editor_layout
        st_row = _hbox(0, 8)
        st_row.addWidget(QLabel("Type"))
        ztype_combo = QComboBox()
        ztype_combo.addItems(["Orf", "Pen"])
        cur_ztype = str(entry.get("zone_type", "Orf"))
        ztype_combo.setCurrentText(cur_ztype if cur_ztype in ("Orf", "Pen") else "Orf")
        ztype_combo.currentTextChanged.connect(
            lambda _t, i=idx: self._on_bhaptics_xroute_ztype_changed(i)
        )
        st_row.addWidget(ztype_combo)
        st_row.addStretch(1)
        se.addLayout(st_row)

        sz_row = _hbox(0, 8)
        sz_row.addWidget(QLabel("Zone"))
        zone_combo = QComboBox()
        zone_combo.setEditable(True)
        zone_combo.setMinimumWidth(160)
        _populate_zone_combo(self.controller, zone_combo,
                             ztype_combo.currentText())
        cur_zone = str(entry.get("ogb_zone", ""))
        if cur_zone and zone_combo.findText(cur_zone) < 0:
            zone_combo.addItem(cur_zone)
        zone_combo.setEditText(cur_zone)
        zone_combo.editTextChanged.connect(
            lambda _t, i=idx: self._push_bhaptics_xroute_entry(i)
        )
        sz_row.addWidget(zone_combo, 1)
        se.addLayout(sz_row)

        filter_checks: Dict[str, QCheckBox] = {}
        cur_filters = set(entry.get("filters") or [])
        for pair in (("TouchSelf", "TouchOthers"), ("PenSelf", "PenOthers")):
            fr = _hbox(0, 8)
            for fname in pair:
                cb = QCheckBox(fname)
                cb.setChecked(fname in cur_filters)
                cb.toggled.connect(
                    lambda _checked=False, i=idx: self._push_bhaptics_xroute_entry(i)
                )
                fr.addWidget(cb)
                filter_checks[fname] = cb
            fr.addStretch(1)
            se.addLayout(fr)

        # ---- Shaping fold: threshold + gain ----
        shp_fold = strip.add_fold(_FoldCard("shaping", "Shaping"))
        shp_fold.add_header_widget(self._make_help_badge(
            "Gain & Threshold",
            "Contact strength below the threshold is ignored; above it, "
            "the signal is scaled by the gain before hitting the dots. "
            "Raise the threshold to ignore grazing contact, raise the "
            "gain to make light contact hit harder."
        ))
        he = shp_fold.editor_layout
        gt_row = _hbox(0, 8)
        gt_row.addWidget(QLabel("Threshold"))
        thresh_spin = QDoubleSpinBox()
        thresh_spin.setRange(0.0, 1.0)
        thresh_spin.setSingleStep(0.05)
        thresh_spin.setDecimals(2)
        try:
            thresh_spin.setValue(float(entry.get("threshold", 0.0)))
        except (TypeError, ValueError):
            thresh_spin.setValue(0.0)
        thresh_spin.valueChanged.connect(
            lambda _v, i=idx: self._push_bhaptics_xroute_entry(i)
        )
        gt_row.addWidget(thresh_spin)
        gt_row.addWidget(QLabel("Gain"))
        gain_spin = QDoubleSpinBox()
        gain_spin.setRange(0.0, 2.0)
        gain_spin.setSingleStep(0.05)
        gain_spin.setDecimals(2)
        try:
            gain_spin.setValue(float(entry.get("gain", 1.0)))
        except (TypeError, ValueError):
            gain_spin.setValue(1.0)
        gain_spin.valueChanged.connect(
            lambda _v, i=idx: self._push_bhaptics_xroute_entry(i)
        )
        gt_row.addWidget(gain_spin)
        gt_row.addStretch(1)
        he.addLayout(gt_row)

        # ---- Output fold: device position + dot selection ----
        out_fold = strip.add_fold(_FoldCard("output", "Output"))
        out_fold.add_header_widget(self._make_help_badge(
            "Dot picker",
            "Which motors on the chosen device this entry drives — the "
            "grid mirrors the device's physical layout; click dots to "
            "toggle them. The text box is a comma-separated 0-based "
            "fallback that stays in sync (handy for copy/paste)."
        ))
        oe = out_fold.editor_layout
        po_row = _hbox(0, 8)
        po_row.addWidget(QLabel("Position"))
        pos_combo = QComboBox()
        pos_combo.addItems(self._bhaptics_xroute_positions)
        cur_pos = str(entry.get("position", "VestFront"))
        if cur_pos and pos_combo.findText(cur_pos) < 0:
            pos_combo.addItem(cur_pos)
        pos_combo.setCurrentText(cur_pos)
        # The currentTextChanged handler both reconfigures the picker
        # (drops out-of-range dots silently) and pushes the entry.
        pos_combo.currentTextChanged.connect(
            lambda _t, i=idx: self._on_bhaptics_xroute_position_changed(i)
        )
        po_row.addWidget(pos_combo)

        po_row.addStretch(1)
        # Tiny count read-out updates from the picker's selectionChanged.
        dot_count_lbl = QLabel("0 dots")
        dot_count_lbl.setProperty("role", "muted")
        po_row.addWidget(dot_count_lbl)
        oe.addLayout(po_row)

        # --- Row 4: visual dot picker (mirrors the chosen device's
        # physical layout) + comma-separated text fallback for
        # power users and paste support. The two stay in sync. ---
        pick_row = _hbox(0, 8)
        pick_row.addWidget(QLabel("Dots"))
        picker = _BHapticsDotPicker()
        cols, rows, node_count = self._bhaptics_xroute_geom.get(
            pos_combo.currentText(), (1, 1, 0)
        )
        picker.set_device(cols, rows, node_count)
        picker.set_selection(entry.get("dot_indices") or [])
        pick_row.addWidget(picker, 0, Qt.AlignTop)

        dots_edit = QLineEdit(self._fmt_dot_indices(picker.selection()))
        dots_edit.setPlaceholderText("e.g. 5, 6, 9, 10")
        dots_edit.setMinimumWidth(140)
        dots_edit.setToolTip(
            "Comma-separated 0-based dot indices. Edits here sync to the "
            "picker above; the picker is the easier surface for most users."
        )

        def _on_picker_changed(_=None, i=idx):
            # Picker updated the selection -> mirror into the line edit
            # without triggering its editingFinished handler, then push.
            sel = picker.selection()
            dots_edit.blockSignals(True)
            try:
                dots_edit.setText(self._fmt_dot_indices(sel))
            finally:
                dots_edit.blockSignals(False)
            dot_count_lbl.setText(f"{len(sel)} dot{'s' if len(sel) != 1 else ''}")
            self._push_bhaptics_xroute_entry(i)

        def _on_text_changed(i=idx):
            # User typed into the text box -> parse, reflect in picker,
            # rewrite the cleaned form back into the box (e.g. dedupe,
            # drop garbage), and push the entry.
            parsed = self._parse_dot_indices(dots_edit.text())
            picker.blockSignals(True)
            try:
                picker.set_selection(parsed)
            finally:
                picker.blockSignals(False)
            cleaned = self._fmt_dot_indices(picker.selection())
            if cleaned != dots_edit.text():
                dots_edit.blockSignals(True)
                try:
                    dots_edit.setText(cleaned)
                finally:
                    dots_edit.blockSignals(False)
            dot_count_lbl.setText(
                f"{len(picker.selection())} dot"
                f"{'s' if len(picker.selection()) != 1 else ''}"
            )
            self._push_bhaptics_xroute_entry(i)

        picker.selectionChanged.connect(_on_picker_changed)
        dots_edit.editingFinished.connect(_on_text_changed)
        # Initial count label
        n = len(picker.selection())
        dot_count_lbl.setText(f"{n} dot{'s' if n != 1 else ''}")

        pick_col = _vbox(0, 4)
        pick_col.addWidget(dots_edit)
        pick_col.addStretch(1)
        pick_row.addLayout(pick_col, 1)
        oe.addLayout(pick_row)

        lay.addWidget(strip)

        # Store widget refs so the push handler can read them by index.
        # `picker` is the canonical dot-selection source; `dot_indices`
        # is the synced text shadow we keep for tooltip / paste support.
        row = {
            "name": name_edit,
            "zone_type": ztype_combo,
            "ogb_zone": zone_combo,
            "filters": filter_checks,
            "position": pos_combo,
            "picker": picker,
            "dot_indices": dots_edit,
            "dot_count_label": dot_count_lbl,
            "gain": gain_spin,
            "threshold": thresh_spin,
            "strip": strip, "source_fold": src_fold,
            "shaping_fold": shp_fold, "output_fold": out_fold,
        }
        self._bhaptics_xroute_rows.append(row)
        self._update_bhaptics_xroute_subtitles(row)
        return card

    def _update_bhaptics_xroute_subtitles(self, row: Dict[str, Any]) -> None:
        """Collapsed-fold summaries derived from the row's widgets."""
        try:
            zone_name = row["ogb_zone"].currentText().strip() or "—"
            row["source_fold"].set_subtitle(
                f"{row['zone_type'].currentText()} · {zone_name}")
            row["shaping_fold"].set_subtitle(
                f"≥ {float(row['threshold'].value()):.2f}"
                f" · ×{float(row['gain'].value()):.2f}")
            sel = row["picker"].selection()
            row["output_fold"].set_subtitle(
                f"{row['position'].currentText()}"
                f" · {len(sel)} dot{'s' if len(sel) != 1 else ''}")
        except RuntimeError:
            pass

    @staticmethod
    def _fmt_dot_indices(values) -> str:
        try:
            return ", ".join(str(int(v)) for v in values)
        except (TypeError, ValueError):
            return ""

    @staticmethod
    def _parse_dot_indices(text: str) -> List[int]:
        out: List[int] = []
        for chunk in (text or "").replace(";", ",").split(","):
            chunk = chunk.strip()
            if not chunk:
                continue
            try:
                v = int(chunk)
            except ValueError:
                continue
            if v >= 0:
                out.append(v)
        return sorted(set(out))

    def _push_bhaptics_xroute_entry(self, idx: int):
        """Gather every field of row `idx` and push it through the
        controller. The settings layer clamps + coerces each field, so
        we only need to dump what the user typed."""
        if self._is_updating_bhaptics_xroute:
            return
        if idx < 0 or idx >= len(self._bhaptics_xroute_rows):
            return
        row = self._bhaptics_xroute_rows[idx]
        filters = [name for name, cb in row["filters"].items() if cb.isChecked()]
        # Picker is the canonical dot source — the text field is just a
        # synced shadow. Reading the picker means a half-typed list in
        # the line edit can't reach the router before editingFinished
        # has cleaned it up.
        picker = row.get("picker")
        if picker is not None:
            dot_indices = list(picker.selection())
        else:
            dot_indices = self._parse_dot_indices(row["dot_indices"].text())
        entry = {
            "name":        row["name"].text(),
            "zone_type":   row["zone_type"].currentText(),
            "ogb_zone":    row["ogb_zone"].currentText(),
            "filters":     filters,
            "position":    row["position"].currentText(),
            "dot_indices": dot_indices,
            "gain":        float(row["gain"].value()),
            "threshold":   float(row["threshold"].value()),
        }
        try:
            self.controller.set_bhaptics_sps_mirror_entry(idx, entry)
        except Exception as e:
            self.log_message(f"bHaptics SPS mirror save failed: {e}")

    def _on_bhaptics_xroute_enable_changed(self, checked: bool):
        if self._is_updating_bhaptics_xroute:
            return
        self.controller.set_bhaptics_sps_mirror_enabled(bool(checked))

    def _on_bhaptics_xroute_add(self):
        cfg = self.controller.get_bhaptics_sps_mirror()
        entries = cfg.get("entries", []) or []
        new_entry = {
            "name":        f"Mirror {len(entries) + 1}",
            "zone_type":   "Orf",
            "ogb_zone":    "",
            "filters":     ["TouchSelf", "TouchOthers"],
            "position":    "VestFront",
            "dot_indices": [],
            "gain":        1.0,
            "threshold":   0.0,
        }
        self.controller.set_bhaptics_sps_mirror_entry(len(entries), new_entry)
        self._rebuild_bhaptics_xroute_entries()

    def _on_bhaptics_xroute_delete(self, idx: int):
        self.controller.delete_bhaptics_sps_mirror_entry(idx)
        self._rebuild_bhaptics_xroute_entries()

    def _on_bhaptics_xroute_position_changed(self, idx: int):
        """User picked a different target device. Reconfigure that
        row's picker to the new device's grid (which silently drops
        any selected dots that no longer fit) and update the count
        readout + line edit to match. Then push the entry."""
        if idx < 0 or idx >= len(self._bhaptics_xroute_rows):
            return
        row = self._bhaptics_xroute_rows[idx]
        picker = row.get("picker")
        new_pos = row["position"].currentText()
        if picker is not None:
            cols, rows, node_count = self._bhaptics_xroute_geom.get(
                new_pos, (1, 1, 0)
            )
            picker.blockSignals(True)
            try:
                picker.set_device(cols, rows, node_count)
            finally:
                picker.blockSignals(False)
            # set_device may have dropped out-of-range dots; re-sync
            # the line edit + count label so the UI shows the truth.
            sel = picker.selection()
            cleaned = self._fmt_dot_indices(sel)
            dots_edit = row.get("dot_indices")
            if dots_edit is not None and dots_edit.text() != cleaned:
                dots_edit.blockSignals(True)
                try:
                    dots_edit.setText(cleaned)
                finally:
                    dots_edit.blockSignals(False)
            count_lbl = row.get("dot_count_label")
            if count_lbl is not None:
                count_lbl.setText(f"{len(sel)} dot{'s' if len(sel) != 1 else ''}")
        self._push_bhaptics_xroute_entry(idx)

    def _on_bhaptics_xroute_ztype_changed(self, idx: int):
        """User flipped the entry's Orf/Pen toggle. The shared handler
        clears the zone selection (the previous type's name can't be
        valid for the new type), repopulates the dropdown from the new
        type's lists, and pushes the now-blank-zone entry — same
        convention as the PiShock / Coyote / OWO / Handy views. (The
        old hand-rolled version meant to blank the zone too, but Qt's
        addItems auto-selected the new list's first item into the edit
        text, silently saving a zone the user never picked.)"""
        if idx < 0 or idx >= len(self._bhaptics_xroute_rows):
            return
        row = self._bhaptics_xroute_rows[idx]
        _on_zone_type_changed(
            self.controller, row["ogb_zone"], row["zone_type"].currentText(),
            lambda: self._push_bhaptics_xroute_entry(idx),
        )
