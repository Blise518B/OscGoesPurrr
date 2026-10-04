"""The sidebar's mode + output controls and Home's tuning-tools bar.

(The module keeps its historical name; the Dashboard page it was named
after is gone -- everything it held now lives in the sidebar, on Home
or in Settings.)

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
    QMenu, QInputDialog,
)
from ui import lovense_icons as _lovense_icons
from mixer import WAVEFORMS as _SIM_WAVEFORMS, sample_pattern as _sample_pattern
import time as _time

from constants import *
from parameter_store import store
from utilities import strip_param_prefix

from ui.geometry import parse_tk_geometry as _parse_tk_geometry
from ui.geometry import format_tk_geometry as _format_tk_geometry
from ui.layout_helpers import vbox as _vbox, hbox as _hbox, clear_layout as _clear_layout
from ui.layout_helpers import FlowLayout as _FlowLayout
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
    SliderProxy as _SliderProxy,
    ProgressProxy as _ProgressProxy,
    RainbowMeter as _RainbowMeter,
    install_rainbow_scrollbars as _install_rainbow_scrollbars,
)


class DashboardMixin:

    # ------------------------------------------------------------------
    # Tuning tools bar — Simulator · Signal graph
    # ------------------------------------------------------------------

    def _build_routing_top_bar(self) -> QWidget:
        """One compact bar holding the two tuning tools, as two groups in
        a flow layout: one row on a wide window, wrapping to two when the
        window is narrow -- never a horizontal scroll. Home shows it
        inside its Tuning tools fold.

        Grouped here rather than spread through the page because neither
        is a per-motor concern: the simulator drives EVERY motor's chains
        with one set of parameters, and the signal graph is one graph
        pointed at a chosen chain. (Anti-stuck used to sit here too; it is
        a set-and-forget safety default, so it lives in Settings.)"""
        card = _Card()
        flow = _FlowLayout(margin=0, h_spacing=22, v_spacing=8)
        flow.setContentsMargins(14, 10, 14, 10)
        card.setLayout(flow)

        def group() -> tuple:
            g = QWidget()
            gl = _hbox(0, 8)
            g.setLayout(gl)
            return g, gl

        # ---- Simulator (one instance, drives every motor) ----
        g_sim, row = group()
        self._explain(g_sim,
            "Input simulator",
            "Generates a synthetic input wave and publishes it as an input "
            "source. It reaches only the chains that turned on "
            "<b>Simulated input</b> in their Input stage — as a penetration "
            "on a Penetration chain, as a touch on a Touch chain — so you "
            "can tune one chain against it while everything else keeps "
            "hearing VRChat. <b>Random</b> wanders between quiet and "
            "intense sections with a different depth every stroke, like a "
            "real session. <b>Send to toy</b> off (the default) keeps the "
            "hardware silent on the listening motors — graphs and meters "
            "still move. Parameter changes apply live."
        )
        row.addWidget(QLabel("Sim"))
        self._sim_freq_spin = QDoubleSpinBox()
        self._sim_freq_spin.setRange(0.05, 10.0)
        self._sim_freq_spin.setSingleStep(0.1)
        self._sim_freq_spin.setDecimals(2)
        self._sim_freq_spin.setValue(1.0)
        self._sim_freq_spin.setSuffix(" Hz")
        self._sim_freq_spin.setFixedWidth(112)
        row.addWidget(self._sim_freq_spin)
        self._sim_amp_spin = QDoubleSpinBox()
        self._sim_amp_spin.setRange(0.0, 1.0)
        self._sim_amp_spin.setSingleStep(0.05)
        self._sim_amp_spin.setDecimals(2)
        self._sim_amp_spin.setValue(1.0)
        self._sim_amp_spin.setFixedWidth(84)
        row.addWidget(self._sim_amp_spin)
        self._sim_wave_combo = QComboBox()
        self._sim_wave_combo.addItems([w.capitalize() for w in _SIM_WAVEFORMS])
        self._sim_wave_combo.setFixedWidth(92)
        row.addWidget(self._sim_wave_combo)
        self._sim_send_toggle = ToggleSwitch("Send to toy")
        row.addWidget(self._sim_send_toggle)
        self._sim_play_btn = QPushButton("▶ Play")
        self._sim_play_btn.setCheckable(True)
        self._sim_play_btn.clicked.connect(self._on_sim_play_toggled)
        row.addWidget(self._sim_play_btn)
        # Live re-apply while running.
        self._sim_freq_spin.valueChanged.connect(self._reapply_simulation)
        self._sim_amp_spin.valueChanged.connect(self._reapply_simulation)
        self._sim_wave_combo.currentTextChanged.connect(
            self._reapply_simulation)
        self._sim_send_toggle.toggled.connect(self._reapply_simulation)
        flow.addWidget(g_sim)

        # ---- Signal graph (toggle + target; panel appears below the bar) ----
        g_ov, row = group()
        self._explain(g_ov,
            "Signal graph",
            "One six-trace graph (raw depth/speed, shaped, combined, "
            "final output) for the selected motor and chain. Appears "
            "under this bar while the toggle is on; costs nothing while "
            "it is off."
        )
        self._signal_graph_toggle = ToggleSwitch("Signal graph")
        self._signal_graph_toggle.toggled.connect(self._on_signal_graph_toggled)
        row.addWidget(self._signal_graph_toggle)
        self._signal_graph_target_combo = QComboBox()
        self._signal_graph_target_combo.setMinimumWidth(130)
        self._signal_graph_target_combo.currentIndexChanged.connect(
            self._on_signal_graph_target_changed)
        row.addWidget(self._signal_graph_target_combo)
        self._signal_graph_chain_combo = QComboBox()
        self._signal_graph_chain_combo.setMinimumWidth(96)
        self._signal_graph_chain_combo.currentIndexChanged.connect(
            self._on_signal_graph_target_changed)
        row.addWidget(self._signal_graph_chain_combo)
        flow.addWidget(g_ov)
        return card

    # ---- simulator: an input SOURCE, published as two parameters ----

    def _live_wrappers(self):
        """Yield (device, motor, wrapper) for every wrapper whose C++
        widget is still alive, pruning dead ones as a side effect."""
        alive = []
        for entry in getattr(self, "_chain_wrappers", []):
            _dev, _motor, w = entry
            try:
                w.objectName()          # raises when the C++ peer is gone
            except RuntimeError:
                continue
            alive.append(entry)
        self._chain_wrappers = alive
        return alive

    def _sim_targets(self):
        """(device, motor) pairs that listen to the simulator -- i.e. whose
        custom addresses carry one of its two addresses (set from a chain's
        Input stage). Only these are affected by Send to toy."""
        out = []
        for dev, motor, _w in self._live_wrappers():
            table = self.controller.get_profile_config(dev, "osc_addresses", {}) or {}
            raw = table.get(str(motor)) if isinstance(table, dict) else None
            if isinstance(raw, str):
                raw = [raw]
            if any(a in SIM_ADDRESSES for a in (raw or [])):
                out.append((dev, motor))
        return out

    def _on_sim_play_toggled(self, checked: bool) -> None:
        """Play publishes the wave as OGP/Sim/Pen and OGP/Sim/Touch on every
        tick; a chain that turned on `Simulated input` in its Input stage
        hears it through its type filter, every other chain keeps hearing
        VRChat. Stop removes the two parameters again."""
        if checked:
            self._sim_play_btn.setText("■ Stop")
            self._sim_t0 = _time.monotonic()
            timer = getattr(self, "_sim_timer", None)
            if timer is None:
                timer = QTimer(self.window)
                timer.setInterval(16)
                timer.timeout.connect(self._sim_tick)
                self._sim_timer = timer
            self._sim_ticks = 0
            timer.start()
            self._reapply_simulation()
            if not self._sim_targets() and hasattr(self, "set_status_message"):
                self.set_status_message(
                    "Simulator playing — turn on “Simulated input” in a chain's "
                    "Input stage to route it somewhere")
        else:
            self._sim_play_btn.setText("▶ Play")
            timer = getattr(self, "_sim_timer", None)
            if timer is not None:
                timer.stop()
            for addr in SIM_ADDRESSES:
                store.remove_synthetic(addr)
            self._sim_set_suppressed(set())

    def _sim_tick(self) -> None:
        t = _time.monotonic() - getattr(self, "_sim_t0", _time.monotonic())
        try:
            v = _sample_pattern(float(self._sim_freq_spin.value()),
                                float(self._sim_amp_spin.value()),
                                self._sim_wave_combo.currentText().lower(), t)
        except RuntimeError:
            return
        for addr in SIM_ADDRESSES:
            store.update_synthetic(addr, v)
        # Chains can opt in or out while it plays: refresh the Send-to-toy
        # suppression set about once a second.
        self._sim_ticks = getattr(self, "_sim_ticks", 0) + 1
        if self._sim_ticks % 60 == 0:
            self._reapply_simulation()

    def _reapply_simulation(self, *_a) -> None:
        """Send to toy OFF keeps the hardware silent on the motors that listen
        to the simulator (their graphs and meters still move); the wave's
        parameters are read live on every tick, so nothing else to push."""
        btn = getattr(self, "_sim_play_btn", None)
        if btn is None or not btn.isChecked():
            return
        send = bool(self._sim_send_toggle.isChecked())
        self._sim_set_suppressed(set() if send else set(self._sim_targets()))

    def _sim_set_suppressed(self, want) -> None:
        router = getattr(self.controller, "motor_router", None)
        have = getattr(self, "_sim_suppressed", set())
        if router is not None:
            for dev, motor in have - want:
                try:
                    router.unsuppress_toy_output(dev, motor)
                except Exception:
                    pass
            for dev, motor in want - have:
                try:
                    router.suppress_toy_output(dev, motor)
                except Exception:
                    pass
        self._sim_suppressed = set(want)

    # ---- signal graph plumbing ----

    def _refresh_signal_graph_targets(self) -> None:
        """Repopulate the target combo from the live wrapper registry.
        Called after every device-list rebuild. Preserves the current
        selection when the same target still exists."""
        combo = getattr(self, "_signal_graph_target_combo", None)
        if combo is None:
            return
        current = combo.currentData()
        combo.blockSignals(True)
        combo.clear()
        for dev, motor, _w in self._live_wrappers():
            combo.addItem(f"{dev} · M{motor}", (dev, motor))
        if current is not None:
            idx = combo.findData(current)
            if idx >= 0:
                combo.setCurrentIndex(idx)
        combo.blockSignals(False)
        self._refresh_signal_graph_chains()

    def _refresh_signal_graph_chains(self) -> None:
        from ui.motor_signal_chain import (
            _get_chain_count, _chain_display_name,
        )
        combo = getattr(self, "_signal_graph_chain_combo", None)
        target = self._signal_graph_target_combo.currentData() \
            if getattr(self, "_signal_graph_target_combo", None) else None
        if combo is None:
            return
        combo.blockSignals(True)
        combo.clear()
        if target is not None:
            dev, motor = target
            n = _get_chain_count(self.controller, dev, motor)
            for c in range(n):
                combo.addItem(
                    _chain_display_name(self.controller, dev, motor, c), c)
        combo.blockSignals(False)
        self._apply_signal_graph_target()

    def _on_signal_graph_target_changed(self, _idx: int) -> None:
        # Target combo changed → chain list may differ; chain combo
        # changed → just re-point the panel.
        sender = self.sender() if hasattr(self, "sender") else None
        if sender is getattr(self, "_signal_graph_target_combo", None):
            self._refresh_signal_graph_chains()
        else:
            self._apply_signal_graph_target()

    def _apply_signal_graph_target(self) -> None:
        panel = getattr(self, "_signal_graph_panel", None)
        if panel is None:
            return
        target = self._signal_graph_target_combo.currentData()
        if target is None:
            panel.set_target(None)
            return
        dev, motor = target
        chain = self._signal_graph_chain_combo.currentData()
        panel.set_target(dev, motor, int(chain or 0))

    def _on_signal_graph_toggled(self, checked: bool) -> None:
        panel = getattr(self, "_signal_graph_panel", None)
        if panel is None:
            return
        if checked:
            self._refresh_signal_graph_targets()
            self._apply_signal_graph_target()
        panel.setVisible(bool(checked))

    def refresh_output_controls(self) -> None:
        """Repaint the sidebar's strength bar and Off / Sleep buttons from
        the controller. Called whenever strength / Off / Sleep change from
        anywhere other than these widgets (the VRChat menu, mainly), and
        during early startup before the sidebar exists -- so every widget
        access is getattr-guarded."""
        ctl = self.controller
        if not hasattr(ctl, "get_strength"):
            return
        value = float(ctl.get_strength())
        proxy = getattr(self, "sidebar_strength_proxy", None)
        label = getattr(self, "sidebar_strength_label", None)
        if proxy is not None:
            try:
                proxy.set(value)   # blockSignals -- no echo back to the controller
                if label is not None:
                    label.setText(f"{value * 100:.0f}%")
            except RuntimeError:
                pass  # widget destroyed during a rebuild
        for attr, getter in (("sidebar_off_button", "is_output_off"),
                             ("sidebar_sleep_button", "is_sleep_active")):
            toggle = getattr(self, attr, None)
            if toggle is None:
                continue
            try:
                toggle.blockSignals(True)
                toggle.setChecked(bool(getattr(ctl, getter)()))
                toggle.blockSignals(False)
            except RuntimeError:
                pass

    # ------------------------------------------------------------------
    # Modes section helpers
    # ------------------------------------------------------------------

    def _refresh_mode_buttons(self):
        """Repaint the sidebar mode buttons from controller.get_modes_info()
        -- text and active highlight, updated in place. The controller calls
        this after every mode change, including during early startup before
        the buttons exist, so every widget access is guarded."""
        ctl = self.controller
        if not hasattr(ctl, "get_modes_info"):
            return
        infos = ctl.get_modes_info()
        for info, btn in zip(infos, getattr(self, "mode_grid_buttons", None) or []):
            try:
                name = info.get('name', '')
                btn.setText(f"{name}\n{info.get('icon', '')}")
                btn.setProperty("active", "true" if info.get("active") else "false")
                self._explain(btn, name, self._MODE_TIP)   # follows renames
                self._repolish(btn)
            except RuntimeError:
                pass  # widget destroyed during a rebuild

    def _dialog_rename_mode(self, index: int):
        """Tiny modal rename prompt. Modes are renamed rarely; a dialog
        beats rebuilding the row around an inline editor."""
        infos = self.controller.get_modes_info()
        current = ""
        if 0 <= index < len(infos):
            current = str(infos[index].get("name", ""))
        new_name, ok = QInputDialog.getText(
            (getattr(self, "dialog_parent", None) or self.window), "Rename Mode",
            f"New name for '{current}':",
            text=current,
        )
        if ok:
            new_name = (new_name or "").strip()
            if new_name and new_name != current:
                self.controller.rename_mode(index, new_name)

    # Hover explanations for the sidebar block. Kept together so the words
    # a first-time user reads are easy to review in one place.
    _MODE_TIP = (
        "A mode is a <b>routing</b> \u2014 which parts of your avatar drive "
        "which toys. Click to make this one live.<br><br>"
        "All four start out the same; what each does is up to you. Pick a "
        "mode, then open a toy on Home and set its zones \u2014 the Input "
        "stage always edits the live mode. Your tuning, your toys and the "
        "strength stay the same whichever mode is on.<br><br>"
        "<b>Right-click</b> to rename it or change its icon. From inside "
        "VRChat: the <b>OGP/Mode</b> parameter."
    )
    _STRENGTH_TIP = (
        "One multiplier on everything your toys receive \u2014 the knob for "
        "\"a bit softer tonight\". It never touches your tuning, so turning "
        "it back up restores exactly the feel you had.<br><br>"
        "From inside VRChat: the <b>OGP/Strength</b> radial.<br><br>"
        "If one toy always feels stronger than the rest, leave this alone "
        "and trim that toy instead: Home \u2192 the toy \u2192 its chain "
        "\u2192 Output \u2192 Gain."
    )
    _OFF_TIP = (
        "Panic silence. Every toy stops instantly, whatever the strength "
        "says; press it again and your previous level comes straight back. "
        "Not remembered across restarts.<br><br>"
        "From inside VRChat: <b>OGP/Off</b>."
    )
    _SLEEP_TIP = (
        "Makes your toys hard to wake: nothing plays until three full "
        "strokes land within six seconds, so a brush against a sleeping "
        "partner does nothing. Your own Wake settings are untouched and "
        "come straight back when you switch it off. Not remembered across "
        "restarts.<br><br>"
        "From inside VRChat: <b>OGP/Sleep</b>."
    )

    # Mode buttons and Off / Sleep share one height, so the sidebar reads
    # as one block of equal targets.
    _SIDEBAR_BTN_H = 44

    def _build_mode_grid(self) -> QWidget:
        """Sidebar control block, reachable from every page: the four
        routing modes, the total output strength bar and Off / Sleep.

        One grid, two columns: the mode buttons and Off / Sleep share its
        columns and height, so they are exactly the same size. The strength
        bar spans both columns and is deliberately large -- it is the
        control reached for mid-session, often without looking.
        _refresh_mode_buttons restyles the mode buttons in place;
        refresh_output_controls does the same for the bar and the toggles."""
        host = QWidget()
        grid = QGridLayout()
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(4)
        grid.setVerticalSpacing(4)
        host.setLayout(grid)

        # ---- Modes: rows 0-1 ----
        self.mode_grid_buttons = []
        ctl = self.controller
        infos = ctl.get_modes_info() if hasattr(ctl, "get_modes_info") else []
        for i, info in enumerate(infos):
            btn = QPushButton(
                f"{info.get('name', f'Mode {i}')}\n{info.get('icon', '')}"
            )
            btn.setProperty("role", "modeBtn")
            btn.setProperty("active", "true" if info.get("active") else "false")
            btn.setCursor(Qt.PointingHandCursor)
            btn.setFixedHeight(self._SIDEBAR_BTN_H)
            btn.clicked.connect(
                lambda _=False, i=i: self.controller.switch_mode(i)
            )
            btn.setContextMenuPolicy(Qt.CustomContextMenu)
            btn.customContextMenuRequested.connect(
                lambda _pos, i=i, b=btn: self._open_mode_menu(i, b)
            )
            self._explain(btn, info.get("name", f"Mode {i}"), self._MODE_TIP)
            grid.addWidget(btn, i // 2, i % 2)
            self.mode_grid_buttons.append(btn)

        # ---- Total output strength: rows 2-3 ----
        head = QWidget()
        head_lay = _hbox(0, 6)
        head.setLayout(head_lay)
        title = QLabel("Total output strength")
        title.setObjectName("strengthTitle")
        head_lay.addWidget(title, 1)
        self.sidebar_strength_label = QLabel("\u2014")
        self.sidebar_strength_label.setObjectName("strengthValue")
        self.sidebar_strength_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        head_lay.addWidget(self.sidebar_strength_label)
        grid.addWidget(head, 2, 0, 1, 2)

        self.sidebar_strength_slider = QSlider(Qt.Horizontal)
        self.sidebar_strength_slider.setObjectName("strengthSlider")
        self.sidebar_strength_slider.setRange(0, 1000)
        self.sidebar_strength_slider.setSingleStep(10)
        self.sidebar_strength_slider.setPageStep(100)
        self.sidebar_strength_slider.setFixedHeight(34)
        self.sidebar_strength_slider.setCursor(Qt.PointingHandCursor)
        self.sidebar_strength_proxy = _SliderProxy(self.sidebar_strength_slider)
        self.sidebar_strength_slider.valueChanged.connect(
            lambda v: self.controller.set_strength(v / 1000.0)
        )
        grid.addWidget(self.sidebar_strength_slider, 3, 0, 1, 2)
        self._explain((head, self.sidebar_strength_slider),
                      "Total output strength", self._STRENGTH_TIP)

        # ---- Off / Sleep: row 4, the mode buttons' size ----
        self.sidebar_off_button = QPushButton("Off")
        self.sidebar_off_button.setObjectName("sidebarOff")
        self.sidebar_sleep_button = QPushButton("Sleep")
        for col, (btn, setter, tip_title, tip) in enumerate((
                (self.sidebar_off_button, "set_output_off", "Off", self._OFF_TIP),
                (self.sidebar_sleep_button, "set_sleep_active", "Sleep",
                 self._SLEEP_TIP))):
            btn.setProperty("role", "modeBtn")
            btn.setCheckable(True)
            btn.setCursor(Qt.PointingHandCursor)
            btn.setFixedHeight(self._SIDEBAR_BTN_H)
            btn.toggled.connect(
                lambda checked, s=setter: getattr(self.controller, s)(bool(checked))
            )
            self._explain(btn, tip_title, tip)
            grid.addWidget(btn, 4, col)

        self.refresh_output_controls()
        return host

    def _open_mode_menu(self, index: int, anchor: QWidget) -> None:
        """Right-click menu on a sidebar mode button: rename, or pick an
        icon. (The Dashboard's per-mode rows used to carry these.)"""
        menu = QMenu(anchor)
        menu.addAction("Rename\u2026").triggered.connect(
            lambda _=False: self._dialog_rename_mode(index))
        icons = menu.addMenu("Icon")
        for icon in MODE_ICON_CHOICES:
            icons.addAction(icon).triggered.connect(
                lambda _=False, ic=icon: self.controller.set_mode_icon(index, ic))
        menu.exec(anchor.mapToGlobal(anchor.rect().bottomLeft()))

    # Sidebar entries gated by Settings → Features. A view is hidden if any
    # of its required feature flags is off.
    _FEATURE_VIEW_REQUIREMENTS = {
        "OSC Inspector":         ("feature_osc_inspector",),
        "Statistics":            ("feature_statistics",),
    }

    def _feature_allows_view(self, view_name: str) -> bool:
        reqs = self._FEATURE_VIEW_REQUIREMENTS.get(view_name)
        if not reqs:
            return True
        get = getattr(self.controller, "get_feature_enabled", None)
        if get is None:
            return True
        return all(bool(get(k)) for k in reqs)

    def apply_feature_visibility(self):
        """Re-evaluate sidebar visibility after a feature toggle changes:
        feature-gated pages disappear from the nav, the Intiface block and
        Home's toy list with the Intiface feature, and a page that just
        became hidden hands the view back to Home."""
        get = getattr(self.controller, "get_feature_enabled", None)
        toys_on = bool(get("feature_intiface")) if get else True
        if self.intiface_sidebar_section is not None:
            self.intiface_sidebar_section.setVisible(toys_on)
        # Home can't leave the nav the way Device Routing used to, so with
        # the toy server off its toy list and tuning tools step aside for
        # a one-line note instead.
        for attr, show in (("devices_container_frame", toys_on),
                           ("_tuning_tools", toys_on),
                           ("_home_toys_off_note", not toys_on)):
            w = getattr(self, attr, None)
            if w is not None:
                w.setVisible(show)
        for name, btn in self.nav_buttons.items():
            btn.setVisible(self._feature_allows_view(name))
        current = self.main_stack.currentWidget() if self.main_stack else None
        for name, page in self.views.items():
            if page is current:
                btn = self.nav_buttons.get(name)
                if btn is not None and not btn.isVisible():
                    self.select_view("Home")
                break
