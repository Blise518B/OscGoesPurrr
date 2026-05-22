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


class BHapticsMixin:

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
