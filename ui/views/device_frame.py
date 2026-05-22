"""Per-device toy frames: motor rows, blend sliders, variable picker.

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
    icon_no_battery as _icon_no_battery,
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


class DeviceFrameMixin:

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
            full_frame = self.device_ui_frames.get(device_name, {})
            is_connected = device_name in connected_names
            # The connect dot in the bar carries the ✓/⚠ signal now;
            # the name label just shows the name with a role-based tint.
            status_label.setText(device_name)
            status_label.setProperty("role", "success" if is_connected else "alert")
            dot = full_frame.get("connect_dot")
            if dot is not None:
                self._apply_connect_dot(dot, is_connected)
            if not is_connected:
                # Drop back to the no-battery glyph; the last-known level
                # can't be trusted once the device is gone.
                battery_label = full_frame.get("battery_label")
                if battery_label is not None:
                    self._show_no_battery_glyph(battery_label)
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
        """Phase 1 toy frame: collapsed-by-default bar with click-to-expand
        body. The bar holds quick-status + Mute/Test; the expanded body
        holds per-motor cards in a Listening To / Mix two-column layout."""

        card = QFrame()
        card.setObjectName("card")
        card_lay = _vbox(0, 0)
        card.setLayout(card_lay)

        # ---- Collapsed bar (always visible) ----
        bar = QWidget()
        bar.setObjectName("toyBar")
        bar.setCursor(Qt.PointingHandCursor)
        bar_lay = _hbox(8, 8)
        bar.setLayout(bar_lay)

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
        bar_lay.addWidget(icon_button)

        # Green/red dot replaces the old ✓/⚠ text prefix on the name.
        connect_dot = QFrame()
        connect_dot.setObjectName("connectDot")
        connect_dot.setFixedSize(12, 12)
        self._apply_connect_dot(connect_dot, is_connected)
        bar_lay.addWidget(connect_dot, 0, Qt.AlignVCenter)

        name_label = QLabel(device_name)
        name_label.setObjectName("deviceName")
        name_label.setProperty("role", "success" if is_connected else "alert")
        self._repolish(name_label)
        bar_lay.addWidget(name_label)

        bar_lay.addStretch(1)

        # Battery defaults to the no-battery glyph; a real battery_update
        # event replaces it with "🔋 NN%" via update_battery_label.
        battery_label = QLabel("")
        battery_label.setMinimumWidth(70)
        battery_label.setAlignment(Qt.AlignVCenter | Qt.AlignLeft)
        self._show_no_battery_glyph(battery_label)
        bar_lay.addWidget(battery_label)

        # One mini-bar per motor — glance-while-collapsed visibility.
        mini_bar_strip = QWidget()
        mini_strip_lay = _hbox(0, 3)
        mini_bar_strip.setLayout(mini_strip_lay)
        mini_bars: List = []
        for _ in range(motor_count):
            mb = _RainbowMeter(maximum=1000)
            mb.setFixedHeight(10)
            mb.setMinimumWidth(56)
            mini_strip_lay.addWidget(mb)
            mini_bars.append(_ProgressProxy(mb))
        bar_lay.addWidget(mini_bar_strip)

        # Mute = per-toy soft-mute, session-only. Engine target is forced
        # to 0 while held; the meter keeps showing real mixer output.
        mute_btn = QPushButton("Mute")
        mute_btn.setCheckable(True)
        mute_btn.setFixedHeight(BTN_HEIGHT_SMALL)
        mute_btn.setChecked(self.controller.is_device_muted(device_name))
        self._apply_mute_btn_style(mute_btn)

        def on_mute_toggled(checked, n=device_name, btn=mute_btn):
            self.controller.set_device_muted(n, bool(checked))
            self._apply_mute_btn_style(btn)

        mute_btn.toggled.connect(on_mute_toggled)
        bar_lay.addWidget(mute_btn)

        # Test = fixed 0.3s @ 0.5 pulse — distinct from Simple Mode's
        # test_toy, which keeps its 1.0s/0.4 timing.
        test_btn = QPushButton("Test")
        test_btn.setFixedHeight(BTN_HEIGHT_SMALL)
        test_btn.setProperty("role", "secondary")
        test_btn.clicked.connect(
            lambda _=False, n=device_name: self.controller.test_device(n)
        )
        bar_lay.addWidget(test_btn)

        expand_caret = QLabel("▾")
        expand_caret.setObjectName("expandCaret")
        expand_caret.setFixedWidth(18)
        expand_caret.setAlignment(Qt.AlignCenter)
        bar_lay.addWidget(expand_caret)

        card_lay.addWidget(bar)

        # ---- Expanded body (hidden by default) ----
        body = QWidget()
        body.setObjectName("toyBody")
        body_lay = _vbox(12, 12)
        body.setLayout(body_lay)
        body.setVisible(False)

        motor_vars: List[Dict[str, Any]] = []
        for motor_idx in range(motor_count):
            motor_kind = (motor_kinds[motor_idx]
                          if motor_kinds and motor_idx < len(motor_kinds) else None)
            motor_card, motor_var = self._build_motor_card(
                device_name, motor_idx, osc_addresses, motor_kind
            )
            body_lay.addWidget(motor_card)
            motor_vars.append(motor_var)

        # Delete moved inside the body so it can't be hit by mistake on
        # the narrow bar.
        delete_button = QPushButton("Delete device")
        delete_button.setFixedHeight(BTN_HEIGHT_SMALL)
        delete_button.setProperty("role", "danger")
        delete_button.clicked.connect(
            lambda _=False, n=device_name: self.controller.delete_stored_device(n)
        )
        delete_row = QWidget()
        delete_row_lay = _hbox(0, 0)
        delete_row.setLayout(delete_row_lay)
        delete_row_lay.addStretch(1)
        delete_row_lay.addWidget(delete_button)
        delete_row_lay.addStretch(1)
        body_lay.addWidget(delete_row)

        card_lay.addWidget(body)

        # Click anywhere on the bar (except on its own buttons, which
        # consume their clicks) toggles the body. Buttons in the bar get
        # their events first via normal child-first dispatch; QLabels and
        # the bar background propagate up to this handler.
        def toggle_expand():
            expanded = not body.isVisible()
            body.setVisible(expanded)
            expand_caret.setText("▴" if expanded else "▾")

        def on_bar_press(ev):
            if ev.button() == Qt.LeftButton:
                toggle_expand()
                ev.accept()
            else:
                QWidget.mousePressEvent(bar, ev)
        bar.mousePressEvent = on_bar_press

        layout = self.unified_devices_layout
        if layout is not None:
            insert_pos = max(layout.count() - 1, 0)
            layout.insertWidget(insert_pos, card)

        return {
            "frame": card,
            "status_label": name_label,
            "battery_label": battery_label,
            "delete_button": delete_button,
            "icon_button": icon_button,
            "connect_dot": connect_dot,
            "mini_bars": mini_bars,
            "motors": motor_vars,
        }

    # ----------------------------------------------------------
    # Phase 1 toy-frame helpers
    # ----------------------------------------------------------

    def _apply_connect_dot(self, dot_widget: QFrame, is_connected: bool) -> None:
        """Style the small connection-state dot in the toy bar."""
        color = COLOR_SUCCESS if is_connected else COLOR_ALERT
        dot_widget.setStyleSheet(
            f"background-color: {color}; border-radius: 6px;"
        )

    def _apply_mute_btn_style(self, btn: QPushButton) -> None:
        """Reflect the button's checked state in its text + role."""
        muted = btn.isChecked()
        btn.setText("Muted" if muted else "Mute")
        btn.setProperty("role", "danger" if muted else "secondary")
        self._repolish(btn)

    def _show_no_battery_glyph(self, label: QLabel) -> None:
        """Reset a battery slot to the painted no-battery glyph."""
        label.setPixmap(_icon_no_battery().pixmap(20, 20))

    def _build_motor_card(self, device_name: str, motor_idx: int,
                          osc_addresses: dict,
                          motor_kind: Optional[str]) -> "tuple[QFrame, dict]":
        """Build one motor card with the Listening To / Mix two-column
        layout. Returns (widget, motor_var_dict)."""
        card = QFrame()
        card.setObjectName("motorBlock")
        card_lay = _vbox(10, 8)
        card.setLayout(card_lay)

        # Free clarity: classify the motor in the header so users can
        # tell "Motor 0" apart from "Motor 1" without guessing.
        if motor_kind in ("linear", "linear-d"):
            kind_suffix = " · Thrust (linear)"
        elif motor_kind == "vibrate":
            kind_suffix = " · Vibrate"
        else:
            kind_suffix = ""
        header = QLabel(f"Motor {motor_idx}{kind_suffix}")
        header.setObjectName("motorCardHeader")
        hf = header.font(); hf.setBold(True)
        header.setFont(hf)
        card_lay.addWidget(header)

        cols = QWidget()
        cols_lay = _hbox(0, 16)
        cols.setLayout(cols_lay)

        listen_col = self._build_listening_to_column(
            device_name, motor_idx, osc_addresses
        )
        cols_lay.addWidget(listen_col, 1)

        mix_col = self._build_mix_column(device_name, motor_idx)
        cols_lay.addWidget(mix_col, 0, Qt.AlignTop)

        card_lay.addWidget(cols)

        # Output stays visible in Phase 1 (becomes a collapsible
        # disclosure in Phase 2 when it has more knobs to host).
        if motor_kind in ("linear", "linear-d"):
            card_lay.addWidget(self._build_linear_output_row(device_name, motor_idx))

        # The bar's mini-bar gives the glance view; this full-width
        # vibe meter inside the expanded card gives the detail view.
        vibe_meter = _RainbowMeter(maximum=1000)
        card_lay.addWidget(vibe_meter)

        return card, {"vibe_meter": _ProgressProxy(vibe_meter)}

    def _build_listening_to_column(self, device_name: str, motor_idx: int,
                                   osc_addresses: dict) -> QWidget:
        """Zone selector + collapsible zone panel, OSC address chips,
        interaction filter toggles. Reads/writes the same profile keys
        as before."""
        col = QWidget()
        col_lay = _vbox(0, 8)
        col.setLayout(col_lay)

        header = QLabel("LISTENING TO")
        header.setObjectName("columnHeader")
        hf = header.font(); hf.setBold(True)
        header.setFont(hf)
        col_lay.addWidget(header)

        current_zones = self.controller.get_profile_config(
            device_name, f"motor_{motor_idx}_zones", "All SPS"
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
        col_lay.addWidget(zone_btn)

        zone_panel = QFrame()
        zone_panel.setObjectName("zonePanel")
        zone_panel_lay = _vbox(8, 4)
        zone_panel.setLayout(zone_panel_lay)
        zone_panel.setVisible(False)
        col_lay.addWidget(zone_panel)

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
            # touches the individual zone selections.
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

        zone_btn.clicked.connect(
            lambda _=False, tog=toggle_zone_panel: tog()
        )

        # Custom OSC addresses (chips + Add Variable).
        raw_entry = osc_addresses.get(str(motor_idx), [])
        if isinstance(raw_entry, str):
            addresses_list = [raw_entry] if raw_entry.strip() else []
        elif isinstance(raw_entry, list):
            addresses_list = [a for a in raw_entry if isinstance(a, str)]
        else:
            addresses_list = []
        self._setup_motor_address_row(col_lay, device_name, motor_idx, addresses_list)

        # Interaction filter toggles.
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
        col_lay.addWidget(filter_row)

        return col

    def _build_mix_column(self, device_name: str, motor_idx: int) -> QWidget:
        """Today's Position↔Speed subcard, rebranded as MIX. Phase 2 will
        replace the subcard's contents with the real
        Depth/Speed/Combine/Smoothing mixer UI."""
        col = QWidget()
        col_lay = _vbox(0, 8)
        col.setLayout(col_lay)

        header = QLabel("MIX")
        header.setObjectName("columnHeader")
        hf = header.font(); hf.setBold(True)
        header.setFont(hf)
        col_lay.addWidget(header)

        col_lay.addWidget(self._build_speed_blend_subcard(device_name, motor_idx))
        return col

    def _build_linear_output_row(self, device_name: str,
                                 motor_idx: int) -> QFrame:
        """Mode/Idle controls for linear actuators."""
        frame = QFrame()
        frame.setObjectName("outputBlock")
        lay = _vbox(8, 6)
        frame.setLayout(lay)

        header = QLabel("OUTPUT")
        header.setObjectName("columnHeader")
        hf = header.font(); hf.setBold(True)
        header.setFont(hf)
        lay.addWidget(header)

        row = QWidget()
        row_lay = _hbox(0, 12)
        row.setLayout(row_lay)

        row_lay.addWidget(QLabel("Mode:"))
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
        row_lay.addWidget(mode_group)

        row_lay.addSpacing(12)
        row_lay.addWidget(QLabel("Idle:"))
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
        row_lay.addWidget(idle_group)
        row_lay.addStretch(1)
        lay.addWidget(row)

        return frame

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
    # Position ↔ Speed blend slider (per motor + Simple Mode)
    # ----------------------------------------------------------

    def _make_blend_slider_row(self, initial_blend: float,
                               on_change: Callable[[float], None]) -> QWidget:
        """Horizontal slider that picks a Position↔Speed blend in [0.0, 1.0].

        Layout: "Position" — slider — "Speed" — readout. `on_change` fires on
        every value change with the new blend; persistence and recalculation
        are the caller's responsibility (matches the per-motor + Simple Mode
        save paths, which differ in where they persist).
        """
        host = QWidget()
        row = _hbox(0, 8)
        host.setLayout(row)

        pos_label = QLabel("Position")
        pos_label.setProperty("muted", "true")
        self._repolish(pos_label)
        row.addWidget(pos_label)

        slider = QSlider(Qt.Horizontal)
        slider.setRange(0, 100)
        clamped = max(0.0, min(1.0, float(initial_blend)))
        slider.setValue(int(round(clamped * 100)))
        row.addWidget(slider, 1)

        spd_label = QLabel("Speed")
        spd_label.setProperty("muted", "true")
        self._repolish(spd_label)
        row.addWidget(spd_label)

        readout = QLabel("")
        readout.setMinimumWidth(96)
        readout.setProperty("muted", "true")
        self._repolish(readout)
        row.addWidget(readout)

        def render(v: int):
            spd_pct = int(v)
            pos_pct = 100 - spd_pct
            readout.setText(f"Pos {pos_pct}% · Spd {spd_pct}%")

        def on_value_changed(v: int):
            render(v)
            on_change(v / 100.0)

        render(slider.value())
        slider.valueChanged.connect(on_value_changed)
        return host

    # Per-motor speed-blend sub-card (Position↔Speed slider + debug tuning).
    # Returned as a QFrame so the caller can drop it anywhere in a layout.
    _SPEED_TUNING_SPECS = (
        # (key, label, range_lo, range_hi, step, decimals, tooltip)
        ("speed_gain", "Gain",
         0.0, 50.0, 0.1, 2,
         "How aggressively raw motion maps to output. Higher = saturates "
         "on smaller strokes."),
        ("speed_input_deadband", "Input deadband",
         0.0, 0.5, 0.005, 3,
         "Per-tick |Δposition| below this is treated as jitter. Raise if "
         "static contacts still output nonzero speed; lower for more "
         "sensitivity to slow strokes."),
        ("speed_output_cutoff", "Output cutoff",
         0.0, 0.95, 0.01, 2,
         "Smoothed signals below this snap to true zero so the toy fully "
         "stops between strokes."),
        ("speed_decay_tau", "Decay τ (s)",
         0.01, 5.0, 0.01, 2,
         "How long the speed signal sustains after motion stops. Higher = "
         "smoother, lower = more responsive to each individual stroke."),
    )

    def _build_speed_blend_subcard(self, device_name: str, motor_idx: int) -> QFrame:
        card = QFrame()
        card.setObjectName("speedCard")
        card.setFixedWidth(290)
        lay = _vbox(10, 8)
        card.setLayout(lay)

        header = QLabel("Position ↔ Speed")
        hf = header.font(); hf.setBold(True)
        header.setFont(hf)
        lay.addWidget(header)
        lay.addWidget(self._muted_label(
            "Blend SPS depth with motion-derived speed. Left = pure "
            "position, right = pure speed."
        ))

        current_blend = self.controller.get_profile_config(
            device_name, f"motor_{motor_idx}_speed_blend", 0.0
        )

        def on_blend_changed(val: float, dn=device_name, idx=motor_idx):
            self.controller.update_device_config(
                dn, f"motor_{idx}_speed_blend", float(val)
            )
            self.controller.save_profiles()
            if hasattr(self.controller, 'force_recalculate'):
                self.controller.force_recalculate()

        lay.addWidget(self._make_blend_slider_row(
            float(current_blend or 0.0), on_blend_changed
        ))

        # ---- Debug tuning knobs (global, affects every motor + Simple Mode) ----
        divider = QFrame()
        divider.setObjectName("separator")
        lay.addWidget(divider)

        tuning_label = QLabel("Tuning (debug)")
        tlf = tuning_label.font(); tlf.setBold(True)
        tuning_label.setFont(tlf)
        lay.addWidget(tuning_label)
        lay.addWidget(self._muted_label(
            "Shared across all motors. Tweak to taste; we'll bake the final "
            "values in later."
        ))

        tuning = {}
        if hasattr(self.controller, "get_speed_tuning"):
            try:
                tuning = self.controller.get_speed_tuning() or {}
            except Exception:
                tuning = {}

        for key, label, lo, hi, step, decimals, tooltip in self._SPEED_TUNING_SPECS:
            row = _hbox(0, 8)
            lbl = QLabel(label)
            lbl.setMinimumWidth(110)
            row.addWidget(lbl)

            spin = QDoubleSpinBox()
            spin.setRange(lo, hi)
            spin.setSingleStep(step)
            spin.setDecimals(decimals)
            spin.setValue(float(tuning.get(key, 0.0)))
            spin.setToolTip(tooltip)
            row.addWidget(spin, 1)

            def on_value_changed(val, k=key):
                self._on_speed_tuning_edited(k, float(val))

            spin.valueChanged.connect(on_value_changed)
            self._speed_tuning_spins.setdefault(key, []).append(spin)
            lay.addLayout(row)

        reset_btn = QPushButton("Reset to defaults")
        reset_btn.setProperty("role", "secondary")
        reset_btn.setFixedHeight(BTN_HEIGHT_SMALL)
        reset_btn.setToolTip(
            "Revert Gain, Input deadband, Output cutoff and Decay τ to "
            "the built-in defaults."
        )
        reset_btn.clicked.connect(self._on_speed_tuning_reset)
        lay.addWidget(reset_btn)

        return card

    def _on_speed_tuning_edited(self, key: str, value: float) -> None:
        """Persist the user's tuning edit through the controller and mirror
        the post-clamp value back into every sibling spinbox so all motor
        cards show the same number."""
        snapshot = {}
        if hasattr(self.controller, "set_speed_tuning_value"):
            try:
                snapshot = self.controller.set_speed_tuning_value(key, value) or {}
            except Exception:
                snapshot = {}
        applied = float(snapshot.get(key, value))
        self._sync_speed_tuning_spinbox(key, applied)

    def _on_speed_tuning_reset(self) -> None:
        """Call the controller's reset facade and push the returned snapshot
        into every spinbox on every motor card."""
        if not hasattr(self.controller, "reset_speed_tuning"):
            return
        try:
            snapshot = self.controller.reset_speed_tuning() or {}
        except Exception:
            snapshot = {}
        for key, value in snapshot.items():
            self._sync_speed_tuning_spinbox(key, float(value))

    def _sync_speed_tuning_spinbox(self, key: str, value: float) -> None:
        """Write `value` into every registered spinbox for `key` without
        re-firing their valueChanged signals — used by both the edit-sync
        path and the Reset button."""
        for spin in self._speed_tuning_spins.get(key, []):
            if abs(spin.value() - value) < 10 ** -spin.decimals():
                continue
            spin.blockSignals(True)
            try:
                spin.setValue(value)
            finally:
                spin.blockSignals(False)

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
            cleaned = strip_param_prefix(new_addr)
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

    def _set_motor_levels(self, device_name: str, motor_idx: int, value: float):
        """Drive both the per-motor vibe meter inside the expanded card
        and the matching mini-bar in the collapsed toy bar."""
        if device_name not in self.device_ui_frames:
            return
        frame_data = self.device_ui_frames[device_name]
        motors = frame_data.get("motors", [])
        mini_bars = frame_data.get("mini_bars", [])
        if 0 <= motor_idx < len(motors):
            motors[motor_idx]["vibe_meter"].set(value)
            if 0 <= motor_idx < len(mini_bars):
                mini_bars[motor_idx].set(value)
        elif motor_idx == -1:
            for mv in motors:
                mv["vibe_meter"].set(value)
            for mb in mini_bars:
                mb.set(value)

    def update_device_visuals(self, device_name: str, motor_idx: int, value: float):
        """Programmatic motor-value update. With the legacy intensity
        slider gone this is identical to update_motor_vibe; kept distinct
        because only this path runs inside the controller's
        _is_updating_ui guard."""
        self._set_motor_levels(device_name, motor_idx, value)

    def update_motor_vibe(self, device_name: str, motor_idx: int, value: float):
        """Live mixer-output meter update — called by the router on every
        tick."""
        self._set_motor_levels(device_name, motor_idx, value)

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
