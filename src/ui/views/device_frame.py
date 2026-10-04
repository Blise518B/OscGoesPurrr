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
    QGraphicsOpacityEffect,
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
    SliderProxy as _SliderProxy,
    ProgressProxy as _ProgressProxy,
    RainbowMeter as _RainbowMeter,
    ToyFrame as _ToyFrame,
    install_rainbow_scrollbars as _install_rainbow_scrollbars,
)
from ui.tooltips import explain as _explain_target
from ui import theme as _theme
from ui.motor_signal_chain import (
    MotorChainListWidget as _MotorChainListWidget,
    _get_chain_count,
)
from ui.osc_variable_picker import open_osc_variable_picker


# The toy icon in a bar: small enough that a row stays one compact line.
_TOY_ICON_PX = 26
# A motor's meter in a bar, and the gap between two of them.
_METER_PX = 56
_METER_GAP_PX = 3
# An offline toy's icon is faded to match its dimmed row.
_OFFLINE_ICON_OPACITY = 0.45


class DeviceFrameMixin:

    # ----------------------------------------------------------
    # Stored devices status
    # ----------------------------------------------------------

    def update_stored_devices_ui(self):
        connected_names = self.controller.get_connected_device_names()
        # Cache for the hot path: _set_motor_levels runs per changed motor
        # inside the routing tick and must not re-query the facade (a fresh
        # set built from the client's device map) every call. This 1 Hz
        # heartbeat + build_device_list_ui keep the cache current.
        self._connected_names_cache = frozenset(connected_names)
        for device_name, frame_data in self.stored_device_frames.items():
            status_label: Optional[QLabel] = frame_data.get("status_label")
            delete_button: Optional[QPushButton] = frame_data.get("delete_button")
            if status_label is None or delete_button is None:
                continue
            full_frame = self.device_ui_frames.get(device_name, {})
            is_connected = device_name in connected_names
            status_label.setText(device_name)
            self._apply_toy_connection(full_frame, is_connected)
            delete_button.setEnabled(True)
            delete_button.setProperty("role", "danger")
            self._repolish(delete_button)
        self._reorder_device_frames()
        # Test all has nothing to buzz while no toy is connected.
        test_all = getattr(self, "_test_all_button", None)
        if test_all is not None:
            test_all.setEnabled(bool(connected_names))

    def _apply_toy_connection(self, frame_data: dict, is_connected: bool) -> None:
        """Paint one toy card as live or offline. An offline toy -- one
        that is remembered but switched off or out of range -- keeps its
        card (grey outline, see _reorder_device_frames) so its setup stays
        reachable, but drops everything that only means something live:
        the battery, the meters, Mute and Test. Change-gated: this rides
        the 1 Hz stored-devices heartbeat."""
        if not frame_data or frame_data.get("connected") == is_connected:
            return
        frame_data["connected"] = is_connected
        dot = frame_data.get("connect_dot")
        if dot is not None:
            self._apply_connect_dot(dot, is_connected)
        name_label = frame_data.get("status_label")
        if name_label is not None:
            name_label.setProperty("role", "success" if is_connected else "")
            self._repolish(name_label)
        battery_label = frame_data.get("battery_label")
        if battery_label is not None and not is_connected:
            # Drop back to the no-battery glyph; the last-known level
            # can't be trusted once the device is gone.
            self._show_no_battery_glyph(battery_label)
        for key in ("battery_label", "mini_bar_strip", "mute_button",
                    "test_button"):
            w = frame_data.get(key)
            if w is not None:
                w.setVisible(is_connected)
        pill = frame_data.get("offline_pill")
        if pill is not None:
            pill.setVisible(not is_connected)
        icon = frame_data.get("icon_button")
        if icon is not None:
            effect = None
            if not is_connected:
                effect = QGraphicsOpacityEffect(icon)
                effect.setOpacity(_OFFLINE_ICON_OPACITY)
            icon.setGraphicsEffect(effect)

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
                    color = COLOR_ALERT
                battery_label.setText(f"🔋 {pct}%")
                battery_label.setStyleSheet(f"color: {color};")

    # ----------------------------------------------------------
    # Device card construction
    # ----------------------------------------------------------

    def _create_device_frame(self, device_name: str, is_connected: bool,
                             osc_addresses: dict, motor_count: int,
                             motor_kinds: Optional[List[str]] = None) -> dict:
        """One toy on Home: a collapsed-by-default bar with a click-to-expand
        body. The bar is the toy's overview (connection, what drives it,
        battery, a meter per motor, Mute/Test); the expanded body holds the
        per-motor signal chains."""

        # The toy is one thin frame outlined in its identity hue (assigned
        # by display position in _reorder_device_frames); the bar below is
        # unfilled, inset 3px so its hover tint sits inside the frame.
        card = _ToyFrame()
        card.setObjectName("toyFrame")
        card_lay = _vbox(3, 0)
        card.setLayout(card_lay)

        # ---- Collapsed bar (always visible) ----
        bar = QWidget()
        bar.setObjectName("toyBar")
        bar.setCursor(Qt.PointingHandCursor)
        bar_lay = _hbox(0, 8)
        bar_lay.setContentsMargins(8, 5, 8, 5)
        bar.setLayout(bar_lay)

        icon_button = QToolButton()
        icon_button.setObjectName("lovenseIcon")
        icon_button.setAutoRaise(True)
        icon_button.setIconSize(QSize(_TOY_ICON_PX, _TOY_ICON_PX))
        icon_button.setFixedSize(QSize(_TOY_ICON_PX + 4, _TOY_ICON_PX + 4))
        icon_button.setCursor(Qt.PointingHandCursor)
        icon_button.clicked.connect(
            lambda _=False, n=device_name, b=icon_button: self._on_lovense_icon_clicked(n, b)
        )
        self._apply_lovense_icon(device_name, icon_button)
        bar_lay.addWidget(icon_button)

        # Filled green dot = connected, hollow grey ring = offline.
        connect_dot = QFrame()
        connect_dot.setObjectName("connectDot")
        connect_dot.setFixedSize(12, 12)
        bar_lay.addWidget(connect_dot, 0, Qt.AlignVCenter)

        name_label = QLabel(device_name)
        name_label.setObjectName("deviceName")
        bar_lay.addWidget(name_label)

        # What drives this toy in the active mode ("All SPS", "3 zones");
        # kept current by _refresh_toy_summaries.
        zones_label = QLabel(self._toy_zones_summary(device_name, motor_count))
        zones_label.setObjectName("toyZones")
        self._explain(
            zones_label, "What drives this toy",
            "The avatar zones this toy listens to in the active mode, "
            "across all its motors and chains. Open the toy and click a "
            "chain's Input stage to change them.")
        bar_lay.addWidget(zones_label)

        bar_lay.addStretch(1)

        offline_pill = QLabel("OFFLINE")
        offline_pill.setProperty("role", "pill")
        offline_pill.setProperty("tone", "idle")
        self._explain(
            offline_pill, "Offline",
            "Switched off or out of range. Everything you set up for it is "
            "kept, and it comes back to life the moment it reconnects.")
        bar_lay.addWidget(offline_pill, 0, Qt.AlignVCenter)

        # Battery defaults to the no-battery glyph; a real battery_update
        # event replaces it with "🔋 NN%" via update_battery_label.
        battery_label = QLabel("")
        battery_label.setMinimumWidth(70)
        battery_label.setAlignment(Qt.AlignVCenter | Qt.AlignLeft)
        self._show_no_battery_glyph(battery_label)
        bar_lay.addWidget(battery_label)

        # One mini-bar per motor — glance-while-collapsed visibility. The
        # strip is as wide as two meters whatever the motor count (a lone
        # motor's meter fills it), so the battery column and the buttons
        # line up from one row to the next.
        mini_bar_strip = QWidget()
        mini_strip_lay = _hbox(0, _METER_GAP_PX)
        mini_bar_strip.setLayout(mini_strip_lay)
        slots = max(2, motor_count)
        mini_bar_strip.setFixedWidth(
            slots * _METER_PX + (slots - 1) * _METER_GAP_PX)
        mini_bars: List = []
        for _ in range(motor_count):
            mb = _RainbowMeter(maximum=1000)
            mb.setFixedHeight(10)
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
        self._explain(
            mute_btn, "Mute",
            "Silences just this toy. Its meter keeps moving so you can see "
            "what it would be doing; press again to bring it back. Stays "
            "muted when you switch modes, but not across a restart.")
        bar_lay.addWidget(mute_btn)

        # Test = fixed 0.3s @ 0.5 pulse on this toy's vibrate motors.
        test_btn = QPushButton("Test")
        test_btn.setFixedHeight(BTN_HEIGHT_SMALL)
        test_btn.setProperty("role", "secondary")
        test_btn.clicked.connect(
            lambda _=False, n=device_name: self.controller.test_device(n)
        )
        self._explain(
            test_btn, "Test",
            "A short buzz on this toy, so you can tell which toy is which. "
            "Only its vibrating motors take part — a stroker won't "
            "suddenly move.")
        bar_lay.addWidget(test_btn)

        # ▸ closed, ▾ open -- the same as the chain bars and Home's fold.
        expand_caret = QLabel("▸")
        expand_caret.setObjectName("expandCaret")
        expand_caret.setFixedWidth(18)
        expand_caret.setAlignment(Qt.AlignCenter)
        bar_lay.addWidget(expand_caret)

        card_lay.addWidget(bar)
        # The card's sections for the live colour sweep: the bar, each
        # motor's block and the rows under them. The frame around them is
        # painted (ToyFrame), so it needs none.
        self._style_root(bar)

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
            self._style_root(motor_card)
            motor_vars.append(motor_var)

        # This toy's own "I am connected" avatar parameter.
        getter = getattr(self.controller, "get_toy_connected_param", None)
        if callable(getter):
            enabled, param = getter(device_name)
            connected_row = self._build_connected_param_row(
                "Tell VRChat while this toy is connected", enabled, param,
                lambda on, name, n=device_name:
                    self.controller.set_toy_connected_param(n, on, name),
                "Tell VRChat while this toy is connected",
                "Sends a Bool avatar parameter that is <b>true while this "
                "toy is connected</b> and false while it isn't — so your "
                "avatar can light up, show an icon or switch something on "
                "for exactly this toy. Add a Bool with this name to your "
                "avatar's parameters; the name is yours to change, or "
                "<b>Pick…</b> one your avatar already sends.<br><br>"
                "It is the same in every mode. Two toys given the same name "
                "share the parameter: true while either is connected. "
                "Settings → Connection Settings has one more for "
                "\"any toy at all\".")
            body_lay.addWidget(connected_row)
            self._style_root(connected_row)

        # Delete moved inside the body so it can't be hit by mistake on
        # the narrow bar.
        delete_button = QPushButton("Delete device")
        delete_button.setFixedHeight(BTN_HEIGHT_SMALL)
        delete_button.setProperty("role", "danger")
        self._explain(
            delete_button, "Delete device",
            "Forgets this toy and everything set up for it, in every mode. "
            "If you switch it on again later it comes back as a new toy "
            "with default settings.")
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
        self._style_root(delete_row)

        card_lay.addWidget(body)

        # Click anywhere on the bar (except on its own buttons, which
        # consume their clicks) toggles the body. Buttons in the bar get
        # their events first via normal child-first dispatch; QLabels and
        # the bar background propagate up to this handler.
        def set_expanded(expanded: bool):
            body.setVisible(bool(expanded))
            expand_caret.setText("▾" if expanded else "▸")

        def toggle_expand():
            set_expanded(not body.isVisible())

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

        frame_data = {
            "frame": card,
            "status_label": name_label,
            "zones_label": zones_label,
            "battery_label": battery_label,
            "delete_button": delete_button,
            "icon_button": icon_button,
            "connect_dot": connect_dot,
            "offline_pill": offline_pill,
            "mini_bar_strip": mini_bar_strip,
            "mini_bars": mini_bars,
            "mute_button": mute_btn,
            "test_button": test_btn,
            "motors": motor_vars,
        }
        self._apply_toy_connection(frame_data, is_connected)
        return frame_data

    # ----------------------------------------------------------
    # Toy-frame helpers
    # ----------------------------------------------------------

    def _style_root(self, widget) -> None:
        """Register a section with the live colour sweep (ui/live_theme.py)
        so a colour change reaches it in its own small slice. A no-op on a
        host without one (the test hosts)."""
        live = getattr(self, "live_theme", None)
        if live is not None:
            live.add_root(widget)

    def _apply_connect_dot(self, dot_widget: QFrame, is_connected: bool) -> None:
        """Style the small connection-state dot in the toy bar. Offline is
        a hollow grey ring, not red: a toy that is switched off is not an
        error."""
        if is_connected:
            dot_widget.setStyleSheet(
                f"background-color: {COLOR_SUCCESS}; border-radius: 6px;")
        else:
            dot_widget.setStyleSheet(
                "background-color: transparent; "
                f"border: 2px solid {COLOR_DIM}; border-radius: 6px;")

    def _toy_zones_summary(self, device_name: str, motor_count: int) -> str:
        """One short phrase for what drives a toy in the active mode: the
        union of the zones its chains listen to. Reads each chain's zones
        the way the Input stage and the router do -- the chain's own key,
        falling back to the motor's, then to All SPS."""
        get = self.controller.get_profile_config
        missing = object()
        zones = set()
        for motor in range(max(int(motor_count), 0)):
            try:
                chains = _get_chain_count(self.controller, device_name, motor)
            except Exception:
                chains = 1
            for chain in range(chains):
                raw = get(device_name, f"motor_{motor}_c{chain}_zones", missing)
                if raw is missing:
                    raw = get(device_name, f"motor_{motor}_zones", "All SPS")
                zones.update(z.strip() for z in str(raw or "").split(",")
                             if z.strip() and z.strip() != "None")
        if not motor_count:
            return ""
        if "All SPS" in zones:
            return "All SPS"
        if not zones:
            return "Custom OSC only"
        if len(zones) == 1:
            return next(iter(zones))
        return f"{len(zones)} zones"

    def _refresh_toy_summaries(self) -> None:
        """Bring every toy bar's zone summary up to date. Zones belong to
        the active mode and are edited two clicks away on this same page,
        so Home's 2 Hz refresh re-reads them; unchanged text is left alone."""
        for device_name, data in self.device_ui_frames.items():
            label = data.get("zones_label")
            if label is None:
                continue
            try:
                text = self._toy_zones_summary(
                    device_name, len(data.get("motors", ())))
                if label.text() != text:
                    label.setText(text)
            except RuntimeError:
                pass  # card rebuilt meanwhile (device list changed)

    def _apply_mute_btn_style(self, btn: QPushButton) -> None:
        """Reflect the button's checked state in its text + role."""
        muted = btn.isChecked()
        btn.setText("Muted" if muted else "Mute")
        btn.setProperty("role", "danger" if muted else "secondary")
        self._repolish(btn)

    def _show_no_battery_glyph(self, label: QLabel) -> None:
        """Reset a battery slot to the painted no-battery glyph."""
        label.setPixmap(_icon_no_battery().pixmap(20, 20))

    def _explain(self, target, title: str, text: str) -> None:
        """Hover explanation for a control, a row or a group -- see
        ui/tooltips.py. The app has no separate help mode: resting the
        mouse on anything that has an explanation shows it."""
        _explain_target(target, title, text)

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
        # Registry for the page-level simulator / overview bar: the top
        # bar fans one set of sim parameters out to every live wrapper,
        # and the overview target combo lists them. Pruned lazily —
        # consumers drop entries whose C++ widget is gone.
        if not hasattr(self, "_chain_wrappers"):
            self._chain_wrappers = []
        self._chain_wrappers.append((device_name, motor_idx, chain_widget))
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
        # After the whole row exists, so the toggle, the name field and
        # Pick all carry it.
        self._explain(lay,
            "Mirror to VRChat parameter",
            "Also send this motor's output value (0.0–1.0) back to VRChat as "
            "an avatar parameter, so the same contact that drives the toy can "
            "drive an avatar visual (glow, blendshape, fill meter). Works even "
            "with no toy connected. Enter the bare parameter name "
            "(e.g. <b>TailWag</b>) or <b>Pick…</b> one your avatar is "
            "sending; the /avatar/parameters/ prefix is added for you."
        )

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

    def _build_connected_param_row(self, label: str, enabled: bool, name: str,
                                   on_change: Callable[[bool, str], None],
                                   tip_title: str, tip_text: str) -> QWidget:
        """`[switch] label   [parameter name] [Pick…]` -- one "tell VRChat
        while … is connected" setting, the same shape as the per-motor
        mirror row above. Used for each toy (its card) and for the
        whole-rig parameter (Settings). `on_change(enabled, bare name)`
        fires on every committed change; the row never sends anything
        itself."""
        row = QWidget()
        lay = _hbox(0, 8)
        row.setLayout(lay)

        toggle = ToggleSwitch(label)
        toggle.setChecked(bool(enabled))
        lay.addWidget(toggle)

        edit = QLineEdit()
        edit.setPlaceholderText("Avatar parameter name")
        edit.setText(strip_param_prefix(name))
        edit.setMinimumWidth(160)
        lay.addWidget(edit, 1)

        pick_btn = QPushButton("Pick…")
        pick_btn.setFixedHeight(BTN_HEIGHT_SMALL)
        pick_btn.setProperty("role", "secondary")
        lay.addWidget(pick_btn)
        self._explain(lay, tip_title, tip_text)

        def commit(*_a) -> None:
            bare = strip_param_prefix(edit.text())
            if edit.text() != bare:
                edit.blockSignals(True)
                edit.setText(bare)
                edit.blockSignals(False)
            on_change(bool(toggle.isChecked()), bare)

        def on_pick(picked: str) -> None:
            edit.setText(strip_param_prefix(picked))
            commit()

        toggle.toggled.connect(commit)
        edit.editingFinished.connect(commit)
        pick_btn.clicked.connect(lambda: self._open_variable_picker(on_pick))
        return row

    def _build_listening_to_column(self, device_name: str, motor_idx: int,
                                   osc_addresses: dict,
                                   chain_idx=None,
                                   chain_type: str = "") -> QWidget:
        """Zone selector + collapsible zone panel, OSC address chips,
        interaction filter toggles.

        With `chain_idx` set, the zone selection and the interaction
        filters are read and written PER CHAIN (`motor_0_c1_zones`), so a
        Touch chain and a Penetration chain on one motor can watch
        different zones and different contact. Reads fall back to the
        motor-level key when the chain has no opinion yet, matching the
        router, so the panel shows what is actually in effect rather than
        a blank. `chain_type` suppresses the Touch/Penetration toggles for
        a typed chain, where the type already decides them.

        Reads/writes the same profile keys
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
        self._explain(header_lay,
            "Listening To",
            "What this motor reacts to: detected zones, specific OSC "
            "parameter addresses, and per-interaction-type filters "
            "(Touch / Penetration / Self / Others).<br><br>"
            "<b>This is the one part of the chain that belongs to the "
            "active mode.</b> Editing it re-wires this motor in that mode "
            "only — that's what makes a mode a routing. Everything else on "
            "the chain (the shaping stages and the output trim) is shared "
            "by every mode."
        )
        header_lay.addStretch(1)
        col_lay.addWidget(header_row)

        _MISSING = object()

        def chain_key(suffix: str) -> str:
            """The key a write lands on: per-chain when we have one."""
            if chain_idx is None:
                return f"motor_{motor_idx}_{suffix}"
            return f"motor_{motor_idx}_c{int(chain_idx)}_{suffix}"

        def chain_read(suffix: str, default):
            """Per-chain value, falling back to the motor's — the same
            resolution the router does, so the panel never shows a
            setting the chain isn't actually running on."""
            if chain_idx is not None:
                val = self.controller.get_profile_config(
                    device_name, chain_key(suffix), _MISSING)
                if val is not _MISSING:
                    return val
            return self.controller.get_profile_config(
                device_name, f"motor_{motor_idx}_{suffix}", default)

        current_zones = chain_read("zones", "All SPS")
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
        self._explain(zone_row_lay,
            "Zone selector",
            "Which OGB zones drive this motor. <b>All SPS</b> matches "
            "any detected zone; individual toggles bind to specific "
            "orifices, penetrators or touch zones."
        )
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

            detected = self.controller.get_detected_zones()
            # Dedupe across the type buckets: the picker stores bare names,
            # so one name detected as two types must render ONE toggle (two
            # would desync — both write the same motor_N_zones entry).
            seen = set()
            fresh_zones = []
            for bucket in ("Orifices", "Penetrators", "Touch"):
                for name in detected.get(bucket, []):
                    if name not in seen:
                        seen.add(name)
                        fresh_zones.append(name)

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
                self.controller.update_device_config(dn, chain_key("zones"), new_val)
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

        def make_filter_cb(label, suffix, default):
            cb = ToggleSwitch(label)
            cb.setChecked(bool(chain_read(suffix, default)))

            def on_toggle(checked, sfx=suffix):
                self.controller.update_device_config(
                    device_name, chain_key(sfx), bool(checked))
                self.controller.save_profiles()
                if hasattr(self.controller, 'force_recalculate'):
                    self.controller.force_recalculate()

            cb.toggled.connect(on_toggle)
            return cb

        # A TYPED chain gets its touch/pen split from its type, so
        # offering the two toggles as well would be two controls fighting
        # over one decision. Self/Others stays a real choice either way.
        if chain_type in ("touch", "penetration"):
            kind = "touch" if chain_type == "touch" else "penetration"
            lbl = QLabel(f"Driven by <b>{kind}</b> contact")
            lbl.setProperty("muted", "true")
            self._repolish(lbl)
            filter_lay.addWidget(lbl)
        else:
            filter_lay.addWidget(make_filter_cb("Touch", "touch", True))
            filter_lay.addWidget(make_filter_cb("Penetration", "pen", True))
        filter_lay.addWidget(make_filter_cb("Self", "self", False))
        filter_lay.addWidget(make_filter_cb("Others", "others", True))
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
            button.setIconSize(QSize(_TOY_ICON_PX, _TOY_ICON_PX))
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
        result = _lovense_icons.pick_icon((getattr(self, "dialog_parent", None) or self.window), device_name, current_override)
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
        open_osc_variable_picker((getattr(self, "dialog_parent", None) or self.window), on_pick)

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
        # The controller returns the merged per-device map: the shared
        # wiring (toys, OSC addresses, zones, filters) overlaid with the
        # active mode's per-motor mix.
        active_profile = controller.get_active_profile_dict() or {}
        has_saved_devices = bool(active_profile)

        # If no saved devices and we already have frames (from build_device_list_ui),
        # don't clear — just refresh status.
        if not has_saved_devices and self.device_ui_frames:
            self.update_stored_devices_ui()
            return

        # Clear EVERYTHING from the layout — widgets AND spacers — then add
        # back exactly one trailing stretch. Skipping spacers here leaked
        # one stretch per rebuild (mode switches rebuild constantly from
        # the VR menu), and since cards insert before the LAST spacer, the
        # leaked ones accumulated ABOVE the cards, sinking them toward the
        # bottom of the scroll area.
        if self.unified_devices_layout is not None:
            while self.unified_devices_layout.count():
                item = self.unified_devices_layout.takeAt(0)
                w = item.widget() if item is not None else None
                if w is not None:
                    # Hide before detaching: a still-visible child reparented
                    # to None briefly realises as a top-level window (a flash).
                    w.hide()
                    w.setParent(None)
                    w.deleteLater()
            self.unified_devices_layout.addStretch(1)

        self.stored_device_frames.clear()
        self.device_ui_frames.clear()

        if not has_saved_devices:
            placeholder = QLabel(
                "No toys yet — switch one on and it shows up here by "
                "itself. It stays listed after that, even while it's off.")
            placeholder.setProperty("muted", "true")
            placeholder.setAlignment(Qt.AlignHCenter)
            self._repolish(placeholder)
            self._style_root(placeholder)
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
        # Device set changed — the wrapper registry the page-level
        # simulator/overview bar fans out to is about to be repopulated;
        # reset it so dead widgets don't linger, and refresh the overview
        # target combo afterwards (end of this method).
        self._chain_wrappers = []
        # Refresh the connected-name cache the motor
        # meters read on the routing tick.
        try:
            self._connected_names_cache = frozenset(
                self.controller.get_connected_device_names())
        except Exception:
            pass
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
        # The signal graph's target picker lists targets from the wrapper
        # registry rebuilt above.
        if hasattr(self, "_refresh_signal_graph_targets"):
            self._refresh_signal_graph_targets()

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

        live_position = 0
        for name in all_names:
            frame = self.device_ui_frames[name]["frame"]
            self.unified_devices_layout.insertWidget(stretch_index, frame)
            stretch_index += 1
            # Identity hue by display position among the CONNECTED toys:
            # three stacked read as three, a fourth starts the cycle over.
            # An offline toy wears no hue at all -- a grey outline -- and
            # does not use one up. The bar carries the property too because
            # QSS attribute selectors match the widget they are on, not its
            # ancestors.
            if name in connected_names:
                hue = _theme.toy_hue(live_position)
                live_position += 1
            else:
                hue = _theme.OFFLINE_HUE
            bar = frame.findChild(QWidget, "toyBar")
            for w in (frame, bar):
                if w is not None and w.property("hue") != hue:
                    w.setProperty("hue", hue)
                    self._repolish(w)
            frame.set_hue(hue)      # the frame paints itself (ToyFrame)

    # ----------------------------------------------------------
    # Programmatic value updates
    # ----------------------------------------------------------

    def _set_motor_levels(self, device_name: str, motor_idx: int, value: float):
        """Drive the per-motor MotorSignalChainWidget's vibe meter and
        the matching mini-bar in the collapsed toy bar.

        Phantom-update guard: the router still computes targets for
        every motor in the active profile, including stored-but-offline
        toys. The engine drops those values on the floor (the toy
        isn't there to receive them), but if the UI shows the meter
        moving anyway it reads as 'the toy is live' which is a lie.
        So when the device isn't currently connected, we force the
        displayed value to 0. Reads the event-refreshed cache — this
        runs per changed motor inside the routing tick, so it must not
        rebuild the connected-name set from the facade every call."""
        try:
            connected = getattr(self, "_connected_names_cache", None)
            if connected is None:
                connected = frozenset(
                    self.controller.get_connected_device_names())
                self._connected_names_cache = connected
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
