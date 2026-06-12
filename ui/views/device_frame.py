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
    QButtonGroup, QStackedWidget, QTableWidget, QTableWidgetItem,
    QAbstractItemView, QComboBox, QSpinBox, QDoubleSpinBox, QToolButton,
)
from ui import lovense_icons as _lovense_icons

from constants import *
from utilities import strip_param_prefix
from motor_param_out import param_out_keys

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
from ui.help_mode import HelpBadge as _HelpBadge
from ui.motor_signal_chain import MotorChainListWidget as _MotorChainListWidget
from ui.osc_variable_picker import open_osc_variable_picker


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
        # Mirror connection-state changes to Overview tiles.
        if hasattr(self, "_overview_refresh_connection_states"):
            self._overview_refresh_connection_states()

    def update_battery_label(self, device_name: str, level: float):
        if device_name in self.device_ui_frames:
            battery_label: Optional[QLabel] = self.device_ui_frames[device_name].get("battery_label")
            if battery_label is not None:
                pct = int(level * 100)
                if pct > 50:
                    color = COLOR_SUCCESS
                elif pct > 20:
                    color = COLOR_ALERT
                else:
                    color = "#FF4444"
                battery_label.setText(f"🔋 {pct}%")
                battery_label.setStyleSheet(f"color: {color};")
        # Mirror to Overview tile.
        if hasattr(self, "_overview_set_battery"):
            self._overview_set_battery(device_name, level)

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

    def _make_help_badge(self, title: str, text: str) -> "_HelpBadge":
        """Create a `?` badge and register it with the UI's Help Mode
        list. Badge starts in whatever visibility matches the current
        persisted help_mode_enabled app setting."""
        badge = _HelpBadge(title, text)
        if not hasattr(self, "_help_badges"):
            self._help_badges = []
        self._help_badges.append(badge)
        # Start hidden: the caller reparents the badge via addWidget() right
        # after this returns, but calling setVisible(True) while it's still
        # parentless would briefly realise it as a top-level window (a flash).
        # Real visibility is resolved by _set_help_badges_visible() once the
        # rebuild has parented every badge.
        badge.setVisible(False)
        # Dynamic rebuilds (zone add/delete, tracker refresh, lazily-built
        # stage editors) create badges while Help Mode is already ON.
        # Defer one event-loop turn — by then the caller has parented the
        # badge (no flash) — and apply the persisted state.
        if bool(self.controller.get_app_setting("help_mode_enabled", False)):
            def _apply(b=badge):
                try:
                    b.setVisible(True)
                except RuntimeError:
                    pass
            QTimer.singleShot(0, _apply)
        return badge

    def _set_help_badges_visible(self, visible: bool) -> None:
        """Show or hide every registered Help Mode badge. Dead refs
        (C++ widget destroyed on view rebuild) are pruned lazily."""
        if not hasattr(self, "_help_badges"):
            return
        visible = bool(visible)
        for badge in list(self._help_badges):
            try:
                badge.setVisible(visible)
            except RuntimeError:
                self._help_badges.remove(badge)

    def _register_help_mode_toggle(self, toggle) -> None:
        """Wire a Help Mode ToggleSwitch (there's one in the sidebar
        and one in the Device Routing header): seed it from the
        persisted app setting; flipping ANY registered toggle persists
        the state, shows/hides every badge app-wide, and silently
        mirrors the other toggles."""
        if not hasattr(self, "_help_mode_toggles"):
            self._help_mode_toggles = []
        self._help_mode_toggles.append(toggle)
        toggle.setChecked(
            bool(self.controller.get_app_setting("help_mode_enabled", False))
        )
        toggle.toggled.connect(self._on_help_mode_toggled)

    def _on_help_mode_toggled(self, checked: bool) -> None:
        checked = bool(checked)
        self.controller.set_app_setting("help_mode_enabled", checked)
        self._set_help_badges_visible(checked)
        for t in list(getattr(self, "_help_mode_toggles", ())):
            try:
                if t.isChecked() != checked:
                    t.blockSignals(True)
                    t.setChecked(checked)
                    t.blockSignals(False)
            except RuntimeError:
                self._help_mode_toggles.remove(t)

    def _build_motor_card(self, device_name: str, motor_idx: int,
                          osc_addresses: dict,
                          motor_kind: Optional[str]) -> "tuple[QFrame, dict]":
        """Build one motor card by instantiating MotorChainListWidget,
        which holds 1 or 2 MotorSignalChainWidget instances plus the
        +Add / Remove / Merge controls. Single-chain motors render
        the same way as Cut 1–4 (no visual change); two-chain motors
        gain a merge picker between the chain editors.

        The widget calls back into `self._build_listening_to_column`
        for the Input stage editor on each chain, so that mixin
        method stays load-bearing.

        Returns (card_widget, motor_var_dict). `motor_var["widget"]` is the
        chain widget itself (the live-meter target the rest of the UI drives
        via set_motor_value); the returned card wraps that chain widget plus
        the per-motor "mirror to VRChat parameter" output row beneath it."""
        chain_widget = _MotorChainListWidget(self, device_name, motor_idx, motor_kind)
        card = QWidget()
        card_lay = _vbox(0, 6)
        card.setLayout(card_lay)
        card_lay.addWidget(chain_widget)
        card_lay.addWidget(self._build_motor_param_out_row(device_name, motor_idx))
        return card, {"widget": chain_widget}

    def _build_motor_param_out_row(self, device_name: str,
                                   motor_idx: int) -> QWidget:
        """Compact 'mirror this motor's output to a VRChat avatar parameter'
        control. The motor's computed 0..1 value is sent back to VRChat (OSC
        out) so the same contact that drives the toy can also drive an avatar
        visual — a glow, a blendshape, a fill meter — in parallel with, or
        instead of, a physical toy. Persists the two per-motor profile keys the
        router reads via motor_param_out.resolve_param_out, mirroring the
        save + recalc pattern of the interaction-filter toggles."""
        enabled_key, address_key = param_out_keys(motor_idx)

        row = QWidget()
        lay = _hbox(0, 8)
        row.setLayout(lay)

        toggle = ToggleSwitch("Mirror to VRChat parameter")
        toggle.setChecked(
            bool(self.controller.get_profile_config(device_name, enabled_key, False))
        )
        lay.addWidget(toggle)
        lay.addWidget(self._make_help_badge(
            "Mirror to VRChat parameter",
            "Also send this motor's output value (0.0–1.0) back to VRChat as "
            "an avatar parameter, so the same contact that drives the toy can "
            "drive an avatar visual (glow, blendshape, fill meter). Works even "
            "with no toy connected. Enter the bare parameter name "
            "(e.g. <b>TailWag</b>); the /avatar/parameters/ prefix is added "
            "for you."
        ))

        addr_edit = QLineEdit()
        addr_edit.setPlaceholderText("Avatar parameter name (e.g. TailWag)")
        addr_edit.setText(strip_param_prefix(
            self.controller.get_profile_config(device_name, address_key, "")
        ))
        addr_edit.setMinimumWidth(160)
        lay.addWidget(addr_edit, 1)

        pick_btn = QPushButton("Pick…")
        pick_btn.setFixedHeight(BTN_HEIGHT_SMALL)
        pick_btn.setProperty("role", "secondary")
        lay.addWidget(pick_btn)

        def persist_address():
            name = strip_param_prefix(addr_edit.text())
            if addr_edit.text() != name:
                addr_edit.blockSignals(True)
                addr_edit.setText(name)
                addr_edit.blockSignals(False)
            self.controller.update_device_config(device_name, address_key, name)
            self.controller.save_profiles()

        def on_toggle(checked):
            self.controller.update_device_config(
                device_name, enabled_key, bool(checked)
            )
            self.controller.save_profiles()
            if hasattr(self.controller, 'force_recalculate'):
                self.controller.force_recalculate()

        def on_pick(picked: str):
            addr_edit.setText(strip_param_prefix(picked))
            persist_address()

        toggle.toggled.connect(on_toggle)
        addr_edit.editingFinished.connect(persist_address)
        pick_btn.clicked.connect(lambda: self._open_variable_picker(on_pick))

        return row

    def _build_listening_to_column(self, device_name: str, motor_idx: int,
                                   osc_addresses: dict) -> QWidget:
        """Zone selector + collapsible zone panel, OSC address chips,
        interaction filter toggles. Reads/writes the same profile keys
        as before."""
        col = QWidget()
        col_lay = _vbox(0, 8)
        col.setLayout(col_lay)

        header_row = QWidget()
        header_lay = _hbox(0, 6)
        header_row.setLayout(header_lay)
        header = QLabel("LISTENING TO")
        header.setObjectName("columnHeader")
        hf = header.font(); hf.setBold(True)
        header.setFont(hf)
        header_lay.addWidget(header)
        header_lay.addWidget(self._make_help_badge(
            "Listening To",
            "What this motor reacts to: detected zones, specific OSC "
            "parameter addresses, and per-interaction-type filters "
            "(Touch / Penetration / Self / Others)."
        ))
        header_lay.addStretch(1)
        col_lay.addWidget(header_row)

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

        zone_row = QWidget()
        zone_row_lay = _hbox(0, 6)
        zone_row.setLayout(zone_row_lay)
        zone_btn = QPushButton(zone_btn_text(zones_state["value"]))
        zone_btn.setProperty("role", "secondary")
        zone_row_lay.addWidget(zone_btn, 1)
        zone_row_lay.addWidget(self._make_help_badge(
            "Zone selector",
            "Which OGB zones drive this motor. <b>All SPS</b> matches "
            "any detected zone; individual toggles bind to specific "
            "orifices or penetrators."
        ))
        col_lay.addWidget(zone_row)

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

            try:
                custom_sources = list(self.controller.get_sps_source_names_flat() or [])
            except Exception:
                custom_sources = []

            if not fresh_zones and not custom_sources:
                lbl = QLabel(
                    "No zones detected yet.\n"
                    "Make sure VRChat is running and avatar loaded.\n"
                    "(Or define a synthetic source in the SPS Sources tab.)"
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

            if fresh_zones:
                sep_lbl = QLabel("─── Detected Zones ───")
                sep_lbl.setProperty("muted", "true")
                sep_lbl.setAlignment(Qt.AlignHCenter)
                self._repolish(sep_lbl)
                panel_lay.addWidget(sep_lbl)

                for zone in fresh_zones:
                    if zone == "None":
                        continue
                    cb = ToggleSwitch(zone)
                    cb.setChecked(zone in current_selected)
                    cb.toggled.connect(make_toggle(zone))
                    panel_lay.addWidget(cb)

            # Synthetic SPS sources (built in the SPS Sources tab). Selecting
            # one writes its name into motor_X_zones exactly like a detected
            # zone; the router resolves the name against the source map.
            if custom_sources:
                csep = QLabel("─── Custom Sources ───")
                csep.setProperty("muted", "true")
                csep.setAlignment(Qt.AlignHCenter)
                self._repolish(csep)
                panel_lay.addWidget(csep)

                for zone in custom_sources:
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

    # Mix-column and linear-output-row builders removed in Cut 3 —
    # MotorSignalChainWidget now owns both surfaces. See
    # docs/MOTOR_SIGNAL_CHAIN.md § "Per-stage details" for the new layout.

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

    # The Phase 2 mix subcard and its helpers (_build_mix_subcard,
    # _build_mix_channel_card, _build_depth_more_knobs,
    # _build_speed_more_knobs, _get_mix_field, _update_mix_field,
    # _reset_mix_to_defaults) lived here. Cut 4 removed them — Device
    # Routing now embeds ui/motor_signal_chain.py's
    # MotorSignalChainWidget, which owns its own storage round-trip
    # against the chains-list schema from Cut 1.

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
        """Thin wrapper over the shared OSC variable picker
        (ui/osc_variable_picker.py). Kept as a method so the existing call
        sites in this view stay unchanged."""
        open_osc_variable_picker(self.window, on_pick)

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
                    # Hide before detaching: a still-visible child reparented
                    # to None briefly realises as a top-level window (a flash).
                    w.hide()
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
        # Active-profile change can add/remove devices — rebuild the
        # Overview grid so its tile set matches.
        if hasattr(self, "rebuild_overview"):
            self.rebuild_overview()

        # Badges were created hidden (see _make_help_badge) to avoid a
        # parentless-top-level flash; now that the rebuild has parented them,
        # reveal them if Help Mode is on.
        self._set_help_badges_visible(
            controller.get_app_setting("help_mode_enabled", False)
        )

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
        # Newly-connected devices may not have been in the active
        # profile yet — rebuild the Overview grid so they get tiles.
        if hasattr(self, "rebuild_overview"):
            self.rebuild_overview()

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
        """Drive the per-motor MotorSignalChainWidget's vibe meter,
        the matching mini-bar in the collapsed toy bar, and the
        Overview tile's aggregate meter.

        Phantom-update guard: the router still computes targets for
        every motor in the active profile, including stored-but-offline
        toys. The engine drops those values on the floor (the toy
        isn't there to receive them), but if the UI shows the meter
        moving anyway it reads as 'the toy is live' which is a lie.
        So when the device isn't currently connected, we force the
        displayed value to 0."""
        try:
            connected = self.controller.get_connected_device_names()
            if device_name not in connected:
                value = 0.0
        except Exception:
            pass
        if device_name in self.device_ui_frames:
            frame_data = self.device_ui_frames[device_name]
            motors = frame_data.get("motors", [])
            mini_bars = frame_data.get("mini_bars", [])
            if 0 <= motor_idx < len(motors):
                widget = motors[motor_idx].get("widget")
                if widget is not None:
                    widget.set_motor_value(value)
                if 0 <= motor_idx < len(mini_bars):
                    mini_bars[motor_idx].set(value)
            elif motor_idx == -1:
                for mv in motors:
                    widget = mv.get("widget")
                    if widget is not None:
                        widget.set_motor_value(value)
                for mb in mini_bars:
                    mb.set(value)
        # Mirror to Overview tile (no-op when the view hasn't been
        # built yet or the device isn't on a tile).
        if hasattr(self, "_overview_set_motor_value"):
            self._overview_set_motor_value(device_name, motor_idx, value)

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
                    frame.hide()
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
                    frame.hide()
                    frame.setParent(None)
                    frame.deleteLater()
        self.device_ui_frames.clear()
        self.stored_device_frames.clear()

    def get_known_device_names(self) -> list:
        return list(self.device_ui_frames.keys())
