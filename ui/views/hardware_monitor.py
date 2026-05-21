"""Hardware Monitor view (CPU/RAM/GPU OSC broadcaster).

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


class HardwareMonitorMixin:

    # ----------------------------------------------------------
    # Hardware Monitor view
    # ----------------------------------------------------------

    _is_updating_hwmon = False

    # Ordered list of stats shown on the page. Each tuple is
    # (key, label, value_formatter). The same keys map to OSC addresses
    # stored in HardwareMonitorSettingsManager.
    _HWMON_STATS = (
        ("cpu_percent",   "CPU",       "percent"),
        ("ram_used_gb",   "RAM Used",  "gb"),
        ("ram_total_gb",  "RAM Total", "gb"),
        ("gpu_percent",   "GPU",       "percent"),
        ("vram_used_gb",  "VRAM Used", "gb"),
        ("vram_total_gb", "VRAM Total","gb"),
    )

    def _build_hardware_monitor_view(self, parent_layout: QVBoxLayout):
        title = QLabel("Hardware Monitor")
        title.setObjectName("viewTitle")
        title.setAlignment(Qt.AlignHCenter)
        parent_layout.addWidget(title)

        parent_layout.addWidget(self._muted_label(
            "Broadcasts your system stats (CPU, RAM, GPU, VRAM) to VRChat over OSC so an avatar "
            "can display them. Percentages are sent as 0-1 floats; memory values are sent in GB. "
            "GPU stats currently require an NVIDIA GPU (NVML)."
        ))

        # ---- Master settings card ----
        cfg_card = _Card()
        cfg_lay = _vbox(14, 8)
        cfg_card.setLayout(cfg_lay)

        cfg_hdr = QLabel("Settings")
        cfg_hdr.setObjectName("sectionTitle")
        cfg_lay.addWidget(cfg_hdr)

        row1 = _hbox(0, 12)
        self.hwmon_enabled_check = ToggleSwitch("Enabled")
        self.hwmon_enabled_check.toggled.connect(self._on_hwmon_enabled_toggled)
        row1.addWidget(self.hwmon_enabled_check)

        self.hwmon_send_osc_check = ToggleSwitch("Send to VRChat (OSC)")
        self.hwmon_send_osc_check.toggled.connect(self._on_hwmon_send_osc_toggled)
        row1.addWidget(self.hwmon_send_osc_check)

        self.hwmon_gpu_enabled_check = ToggleSwitch("Read GPU (NVIDIA NVML)")
        self.hwmon_gpu_enabled_check.toggled.connect(self._on_hwmon_gpu_toggled)
        row1.addWidget(self.hwmon_gpu_enabled_check)

        row1.addStretch(1)
        cfg_lay.addLayout(row1)

        row2 = _hbox(0, 8)
        row2.addWidget(QLabel("Poll rate (s)"))
        self.hwmon_poll_rate_spin = QDoubleSpinBox()
        self.hwmon_poll_rate_spin.setRange(0.25, 60.0)
        self.hwmon_poll_rate_spin.setSingleStep(0.25)
        self.hwmon_poll_rate_spin.setDecimals(2)
        self.hwmon_poll_rate_spin.valueChanged.connect(self._on_hwmon_poll_rate_changed)
        row2.addWidget(self.hwmon_poll_rate_spin)

        row2.addSpacing(20)
        self.hwmon_status_label = QLabel("")
        self.hwmon_status_label.setStyleSheet(f"color: {COLOR_TEXT_MUTED};")
        row2.addWidget(self.hwmon_status_label)
        row2.addStretch(1)
        cfg_lay.addLayout(row2)

        parent_layout.addWidget(cfg_card)

        # ---- Live stats card ----
        stats_card = _Card()
        stats_lay = _vbox(14, 8)
        stats_card.setLayout(stats_lay)

        stats_hdr = QLabel("Live Stats")
        stats_hdr.setObjectName("sectionTitle")
        stats_lay.addWidget(stats_hdr)

        self.hwmon_gpu_name_label = QLabel("GPU: --")
        self.hwmon_gpu_name_label.setStyleSheet(f"color: {COLOR_TEXT_MUTED};")
        stats_lay.addWidget(self.hwmon_gpu_name_label)

        # Each stat gets a row with: name, value, progress bar (for %).
        grid = QGridLayout()
        grid.setHorizontalSpacing(14)
        grid.setVerticalSpacing(8)
        self.hwmon_value_labels: Dict[str, QLabel] = {}
        self.hwmon_progress_bars: Dict[str, QProgressBar] = {}
        for r, (key, label, kind) in enumerate(self._HWMON_STATS):
            name_lbl = QLabel(label)
            f = name_lbl.font(); f.setBold(True); name_lbl.setFont(f)
            grid.addWidget(name_lbl, r, 0)

            value_lbl = QLabel("--")
            value_lbl.setMinimumWidth(140)
            grid.addWidget(value_lbl, r, 1)
            self.hwmon_value_labels[key] = value_lbl

            if kind == "percent":
                pb = QProgressBar()
                pb.setRange(0, 100)
                pb.setValue(0)
                pb.setFixedHeight(14)
                grid.addWidget(pb, r, 2)
                self.hwmon_progress_bars[key] = pb
            else:
                # Spacer so the column lines up with the percent bars.
                grid.addWidget(QLabel(""), r, 2)

        stats_lay.addLayout(grid)
        parent_layout.addWidget(stats_card)

        # ---- OSC addresses card ----
        addr_card = _Card()
        addr_lay = _vbox(14, 6)
        addr_card.setLayout(addr_lay)

        addr_hdr = QLabel("OSC Output")
        addr_hdr.setObjectName("sectionTitle")
        addr_lay.addWidget(addr_hdr)

        addr_lay.addWidget(self._muted_label(
            "Set the avatar parameter name each stat is written to. Percent stats are normalised "
            "to 0-1; memory stats are sent in GB as floats. Untick a row to skip sending that stat."
        ))

        addr_grid = QGridLayout()
        addr_grid.setHorizontalSpacing(10)
        addr_grid.setVerticalSpacing(6)
        addr_grid.addWidget(QLabel("Stat"), 0, 0)
        addr_grid.addWidget(QLabel("Send"), 0, 1)
        addr_grid.addWidget(QLabel("Parameter Name"), 0, 2)
        addr_grid.addWidget(QLabel("Type"), 0, 3)
        addr_grid.addWidget(QLabel("Last Sent Value"), 0, 4)

        self.hwmon_addr_edits: Dict[str, QLineEdit] = {}
        self.hwmon_send_checks: Dict[str, QCheckBox] = {}
        self.hwmon_last_sent_labels: Dict[str, QLabel] = {}
        for r, (key, label, _kind) in enumerate(self._HWMON_STATS, start=1):
            addr_grid.addWidget(QLabel(label), r, 0)

            chk = QCheckBox()
            chk.toggled.connect(
                lambda checked, k=key: self._on_hwmon_send_toggle_changed(k, checked)
            )
            addr_grid.addWidget(chk, r, 1)
            self.hwmon_send_checks[key] = chk

            edit = QLineEdit()
            edit.editingFinished.connect(
                lambda k=key: self._on_hwmon_address_changed(k)
            )
            addr_grid.addWidget(edit, r, 2)
            self.hwmon_addr_edits[key] = edit

            # Type column — every stat is transmitted as a float.
            type_lbl = QLabel("float")
            type_lbl.setProperty("muted", "true")
            type_lbl.setAlignment(Qt.AlignCenter)
            addr_grid.addWidget(type_lbl, r, 3)

            # Last Sent Value column — updated on each refresh tick.
            sent_lbl = QLabel("--")
            sent_lbl.setAlignment(Qt.AlignCenter)
            sent_font = QFont("Consolas")
            sent_font.setStyleHint(QFont.Monospace)
            sent_lbl.setFont(sent_font)
            addr_grid.addWidget(sent_lbl, r, 4)
            self.hwmon_last_sent_labels[key] = sent_lbl

        addr_grid.setColumnStretch(2, 1)
        addr_lay.addLayout(addr_grid)
        parent_layout.addWidget(addr_card)

        parent_layout.addStretch(1)

        # Initial population + periodic refresh.
        self._refresh_hardware_monitor_view(full=True)
        self._hwmon_refresh_timer = QTimer(self.window)
        self._hwmon_refresh_timer.setInterval(500)
        self._hwmon_refresh_timer.timeout.connect(
            lambda: self._refresh_hardware_monitor_view(full=False)
        )
        self._hwmon_refresh_timer.start()

    # ---- Hardware monitor handlers ----

    def _on_hwmon_enabled_toggled(self, checked: bool):
        if self._is_updating_hwmon:
            return
        self.controller.set_hardware_monitor_enabled(bool(checked))

    def _on_hwmon_send_osc_toggled(self, checked: bool):
        if self._is_updating_hwmon:
            return
        self.controller.set_hardware_monitor_send_osc(bool(checked))

    def _on_hwmon_gpu_toggled(self, checked: bool):
        if self._is_updating_hwmon:
            return
        self.controller.set_hardware_monitor_gpu_enabled(bool(checked))

    def _on_hwmon_poll_rate_changed(self, value: float):
        if self._is_updating_hwmon:
            return
        self.controller.set_hardware_monitor_poll_rate(float(value))

    def _on_hwmon_send_toggle_changed(self, key: str, checked: bool):
        if self._is_updating_hwmon:
            return
        self.controller.set_hardware_monitor_send_toggle(key, bool(checked))

    def _on_hwmon_address_changed(self, key: str):
        if self._is_updating_hwmon:
            return
        edit = self.hwmon_addr_edits.get(key)
        if edit is None:
            return
        self.controller.set_hardware_monitor_address(key, edit.text().strip())

    def _refresh_hardware_monitor_view(self, full: bool = False):
        if not hasattr(self, "hwmon_value_labels"):
            return
        try:
            status = self.controller.get_hardware_monitor_status()
        except Exception:
            return
        stats = status.get("stats", {}) or {}
        settings = status.get("settings", {}) or {}

        # Live values + last-sent OSC payload
        last_sent = stats.get("last_sent_values", {}) or {}
        for key, _label, kind in self._HWMON_STATS:
            val = stats.get(key)
            lbl = self.hwmon_value_labels.get(key)
            if lbl is not None:
                if val is None:
                    lbl.setText("--")
                elif kind == "percent":
                    lbl.setText(f"{float(val):.1f} %")
                else:
                    lbl.setText(f"{float(val):.2f} GB")
            pb = self.hwmon_progress_bars.get(key)
            if pb is not None:
                try:
                    pb.setValue(max(0, min(100, int(round(float(val or 0))))))
                except (TypeError, ValueError):
                    pb.setValue(0)
            # Last Sent Value column — shows the actual OSC payload.
            sent_lbl = self.hwmon_last_sent_labels.get(key)
            if sent_lbl is not None:
                sent_val = last_sent.get(key)
                if sent_val is None:
                    sent_lbl.setText("--")
                else:
                    sent_lbl.setText(f"{float(sent_val):.4f}")

        # GPU name / status footer
        gpu_name = stats.get("gpu_name")
        backend = stats.get("gpu_backend", "none")
        if backend == "nvml" and gpu_name:
            self.hwmon_gpu_name_label.setText(f"GPU: {gpu_name} (NVML)")
            self.hwmon_gpu_name_label.setStyleSheet(f"color: {COLOR_SUCCESS};")
        elif not stats.get("has_nvml", False):
            self.hwmon_gpu_name_label.setText(
                "GPU: NVML not available (pip install nvidia-ml-py for NVIDIA GPUs)"
            )
            self.hwmon_gpu_name_label.setStyleSheet(f"color: {COLOR_TEXT_MUTED};")
        else:
            self.hwmon_gpu_name_label.setText("GPU: --")
            self.hwmon_gpu_name_label.setStyleSheet(f"color: {COLOR_TEXT_MUTED};")

        # Status line
        if not stats.get("has_psutil", True):
            self.hwmon_status_label.setText("psutil not installed — CPU/RAM unavailable")
            self.hwmon_status_label.setStyleSheet(f"color: {COLOR_ALERT};")
        elif stats.get("error"):
            self.hwmon_status_label.setText(f"Last error: {stats['error']}")
            self.hwmon_status_label.setStyleSheet(f"color: {COLOR_ALERT};")
        else:
            self.hwmon_status_label.setText("OK")
            self.hwmon_status_label.setStyleSheet(f"color: {COLOR_SUCCESS};")

        # Sync settings widgets (only on full refresh to avoid stomping
        # in-flight user edits to text fields).
        if full:
            self._is_updating_hwmon = True
            try:
                self.hwmon_enabled_check.setChecked(bool(settings.get("enabled", False)))
                self.hwmon_send_osc_check.setChecked(bool(settings.get("send_osc", True)))
                self.hwmon_gpu_enabled_check.setChecked(bool(settings.get("gpu_enabled", True)))
                self.hwmon_poll_rate_spin.setValue(float(settings.get("poll_rate_s", 2.0)))

                addresses = settings.get("addresses", {}) or {}
                toggles = settings.get("send_toggles", {}) or {}
                for key, _label, _kind in self._HWMON_STATS:
                    edit = self.hwmon_addr_edits.get(key)
                    if edit is not None and not edit.hasFocus():
                        edit.setText(str(addresses.get(key, "")))
                    chk = self.hwmon_send_checks.get(key)
                    if chk is not None:
                        chk.setChecked(bool(toggles.get(key, True)))
            finally:
                self._is_updating_hwmon = False
