"""Unified OscGoesPurrr Test Bench — one window that drives a known input
signal into the live OGP app (impersonating VRChat over OSC) and reads the
resulting toy output (impersonating a Lovense toy on Intiface), on one clock.

Layout:

* **Status bar** — OGP discovery + Intiface WSDM connection.
* **Mode selector** — Input / Output / Benchmark (shows the relevant panels;
  the bench subsumes the former standalone VRChat-sim and toy-sim tools).
* **Input panel** — avatar preset, drive channel, waveform/freq/amp, Run/Stop,
  manual slider, single-step, pulse.
* **Output panel** — toy model + Intiface identifier/URL, Connect, watched
  motor, battery, a live level bar.
* **Benchmark panel** — thresholds, "Run benchmark (N cycles)", live stats,
  Export CSV.
* **Plots** — input-vs-output scrolling line plot + latency histogram.
* **Log** — OSC / command activity.

Timestamping: the input value is stamped with ``perf_counter`` at send time on
the UI thread; the toy output is stamped at receive time on the websocket
worker thread (before the Qt hop) so the measured latency is the true round
trip through OGP + Intiface. ``BenchEngine`` is thread-safe.
"""

from __future__ import annotations

import os
import sys
import time
from typing import Callable, List, Optional

from PySide6.QtCore import Qt, QObject, QTimer, Signal
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QApplication, QComboBox, QDoubleSpinBox, QFileDialog, QFormLayout,
    QGroupBox, QHBoxLayout, QLabel, QLineEdit, QMainWindow, QMessageBox,
    QPlainTextEdit, QProgressBar, QPushButton, QScrollArea, QSlider, QSpinBox,
    QSplitter, QVBoxLayout, QWidget,
)

from . import csv_export
from . import state
from .bench import BenchEngine
from .generators import (
    AMP_MAX, AMP_MIN, AMP_STEP, FREQ_MAX, FREQ_MIN, FREQ_STEP, WAVEFORMS,
    SignalDriver,
)
from .plots import LatencyHistogram, LivePlot
from .style import COLOR_LIVE, COLOR_SUCCESS, COLOR_TEXT_MUTED, GLOBAL_QSS
from . import sim_avatar
from .lovense_device import DEFAULT_WSDM_URL, LovenseToy
from .lovense_protocol import (
    DEFAULT_WS_IDENTIFIER, MODELS, LovenseModel, LovenseProtocol,
)
from .sim_network import VRChatSimNetwork

_APP_USER_MODEL_ID = "OscGoesPurrr.TestBench"
_CLOCK = time.perf_counter


def _icon_path() -> Optional[str]:
    """Resolve Images/OGP_Sim_Icon.ico for source-tree and --onefile layouts."""
    if getattr(sys, "frozen", False):
        base = getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
    else:
        base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    candidate = os.path.join(base, "Images", "OGP_Sim_Icon.ico")
    return candidate if os.path.exists(candidate) else None


# ----------------------------------------------------------------- drive channels
# A channel maps a 0..1 drive value to the OSC params OGP routes. Each is
# stateless; the auto-asserted *Close bool follows value>0, matching what the
# old VRChat sim sent (and what motor_router.py expects to gate on).

DriveFn = Callable[[VRChatSimNetwork, float], None]


def _orf_insertion(prefix: str) -> DriveFn:
    def drive(net: VRChatSimNetwork, v: float) -> None:
        net.set_param(f"{prefix}/PenOthersClose", v > 0.0)
        net.set_param(f"{prefix}/PenOthers", v)
    return drive


def _orf_touch(prefix: str) -> DriveFn:
    def drive(net: VRChatSimNetwork, v: float) -> None:
        net.set_param(f"{prefix}/TouchOthersClose", v > 0.0)
        net.set_param(f"{prefix}/TouchOthers", v)
    return drive


def _pen_insertion(prefix: str) -> DriveFn:
    def drive(net: VRChatSimNetwork, v: float) -> None:
        net.set_param(f"{prefix}/PenOthers", v)
    return drive


def _pen_frot(prefix: str) -> DriveFn:
    def drive(net: VRChatSimNetwork, v: float) -> None:
        net.set_param(f"{prefix}/FrotOthersClose", v > 0.0)
        net.set_param(f"{prefix}/FrotOthers", v)
    return drive


def channels_for_preset(preset: sim_avatar.AvatarPreset) -> List[tuple]:
    """Return ``[(label, DriveFn), ...]`` for an avatar preset's SPS zones."""
    out: List[tuple] = []
    for z in preset.sps_zones:
        if z.kind == "Orf":
            p = f"OGB/Orf/{z.name}"
            out.append((f"Orf {z.name} · Insertion (PenOthers)", _orf_insertion(p)))
            out.append((f"Orf {z.name} · Touch (TouchOthers)", _orf_touch(p)))
        elif z.kind == "Pen":
            p = f"OGB/Pen/{z.name}"
            out.append((f"Pen {z.name} · Insertion (PenOthers)", _pen_insertion(p)))
            out.append((f"Pen {z.name} · Frot (FrotOthers)", _pen_frot(p)))
    return out


# ---------------------------------------------------------------- thread bridge

class _Bridge(QObject):
    """Marshals network + websocket worker-thread callbacks onto the GUI thread."""
    targets_changed = Signal(list)    # List[str] discovered target labels
    target_changed = Signal(object)   # Optional[str] active target label
    status = Signal(str)
    toy_levels = Signal(list)        # List[Tuple[int, float]]
    toy_log = Signal(str)
    toy_state = Signal(bool, object)  # (connected, error_or_None)


# ------------------------------------------------------------------- main window

class TestBenchWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("OscGoesPurrr Test Bench — input vs output latency")
        self.resize(1240, 820)
        icon = _icon_path()
        if icon:
            self.setWindowIcon(QIcon(icon))

        self.bench = BenchEngine(clock=_CLOCK)
        self._watch_idx = 0
        self._channel: Optional[DriveFn] = None
        self.toy: Optional[LovenseToy] = None
        self._toy_model: Optional[LovenseModel] = None

        # Network (input side) — callbacks hop to the GUI thread via the bridge.
        self.bridge = _Bridge()
        self.net = VRChatSimNetwork(
            on_targets_changed=lambda names: self.bridge.targets_changed.emit(list(names)),
            on_target_changed=lambda label: self.bridge.target_changed.emit(label),
            on_inbound_osc=lambda a, v: self.bridge.toy_log.emit(f"target→ {a} {tuple(v)}"),
            on_status=lambda m: self.bridge.status.emit(m),
        )
        self.bridge.targets_changed.connect(self._on_targets_changed)
        self.bridge.target_changed.connect(self._on_target_changed)
        self.bridge.status.connect(lambda m: self._log(f"[net] {m}"))
        self.bridge.toy_levels.connect(self._on_toy_levels_ui)
        self.bridge.toy_log.connect(self._log)
        self.bridge.toy_state.connect(self._on_toy_state)

        # Signal driver (input side). Its sink does the OSC send + timestamp.
        self.driver = SignalDriver(self._emit_input, clock=_CLOCK, parent=self)

        self._build_ui()
        self.net.start()
        self._apply_avatar_index(0)
        self._apply_mode("Benchmark")

        # Plot/stats refresh on a GUI timer, decoupled from data arrival.
        self._refresh = QTimer(self)
        self._refresh.setInterval(50)  # 20 Hz plot
        self._refresh.timeout.connect(self._tick_refresh)
        self._refresh.start()
        self._refresh_count = 0

    # ----------------------------------------------------------- construction
    def _build_ui(self) -> None:
        central = QWidget()
        central.setObjectName("root")
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(8)

        # Status + mode row.
        bar = QHBoxLayout()
        self._target_status = QLabel("Target: none discovered")
        self._target_status.setObjectName("statusBar")
        self._toy_label = QLabel("Intiface: not connected")
        self._toy_label.setObjectName("statusBar")
        bar.addWidget(self._target_status, 1)
        bar.addWidget(self._toy_label, 1)
        bar.addWidget(QLabel("Mode:"))
        self._mode_combo = QComboBox()
        self._mode_combo.addItems(["Input", "Output", "Benchmark"])
        self._mode_combo.setCurrentText("Benchmark")
        self._mode_combo.currentTextChanged.connect(self._apply_mode)
        bar.addWidget(self._mode_combo)
        root.addLayout(bar)

        split = QSplitter(Qt.Orientation.Horizontal)
        # The controls live in a scroll area so a short window scrolls them
        # instead of squishing the rows (which clipped buttons/spinboxes).
        controls_scroll = QScrollArea()
        controls_scroll.setWidgetResizable(True)
        controls_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        controls_scroll.setWidget(self._build_controls())
        controls_scroll.setMinimumWidth(320)
        split.addWidget(controls_scroll)
        split.addWidget(self._build_plots())
        split.setStretchFactor(0, 0)
        split.setStretchFactor(1, 1)
        split.setSizes([440, 800])
        root.addWidget(split, 1)

        # Bottom log.
        self._log_view = QPlainTextEdit()
        self._log_view.setReadOnly(True)
        self._log_view.setMaximumBlockCount(2000)
        self._log_view.setFixedHeight(120)
        root.addWidget(self._log_view)

    def _build_controls(self) -> QWidget:
        host = QWidget()
        col = QVBoxLayout(host)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(8)
        col.addWidget(self._build_input_group())
        col.addWidget(self._build_output_group())
        col.addWidget(self._build_bench_group())
        col.addStretch(1)
        return host

    def _build_input_group(self) -> QGroupBox:
        g = QGroupBox("Input  (VRChat → target app)")
        self._in_group = g
        form = QFormLayout(g)

        # Where the avatar OSC goes. Any discovered VRChat-OSC consumer shows
        # up here (OGP, OSC Goes Brrr, …); pick one, or use a manual host:port
        # for apps that only listen on the fixed VRChat port (9000) without
        # advertising OSCQuery.
        self._target_combo = QComboBox()
        self._target_combo.setToolTip("OSC apps discovered on the network")
        self._target_combo.activated.connect(self._on_target_combo_activated)
        form.addRow("Target app", self._target_combo)

        manual = QHBoxLayout()
        self._host_edit = QLineEdit("127.0.0.1")
        self._port_spin = QSpinBox()
        self._port_spin.setRange(1, 65535)
        self._port_spin.setValue(9000)
        use_manual = QPushButton("Use")
        use_manual.setProperty("role", "secondary")
        use_manual.clicked.connect(self._use_manual_target)
        manual.addWidget(self._host_edit, 1)
        manual.addWidget(self._port_spin)
        manual.addWidget(use_manual)
        form.addRow("Manual host:port", manual)

        self._avatar_combo = QComboBox()
        for p in sim_avatar.AVATAR_PRESETS:
            self._avatar_combo.addItem(p.display_name, userData=p.avatar_id)
        self._avatar_combo.currentIndexChanged.connect(self._apply_avatar_index)
        form.addRow("Avatar", self._avatar_combo)

        self._channel_combo = QComboBox()
        self._channel_combo.currentIndexChanged.connect(self._apply_channel_index)
        form.addRow("Drive channel", self._channel_combo)

        self._wave_combo = QComboBox()
        self._wave_combo.addItems(list(WAVEFORMS))
        self._wave_combo.currentTextChanged.connect(
            lambda s: setattr(self.driver, "waveform", s))
        form.addRow("Waveform", self._wave_combo)

        self._freq_spin = QDoubleSpinBox()
        self._freq_spin.setRange(FREQ_MIN, FREQ_MAX)
        self._freq_spin.setSingleStep(FREQ_STEP)
        self._freq_spin.setDecimals(2)
        self._freq_spin.setSuffix(" Hz")
        self._freq_spin.setValue(self.driver.freq)
        self._freq_spin.valueChanged.connect(lambda v: setattr(self.driver, "freq", float(v)))
        form.addRow("Frequency", self._freq_spin)

        self._amp_spin = QDoubleSpinBox()
        self._amp_spin.setRange(AMP_MIN, AMP_MAX)
        self._amp_spin.setSingleStep(AMP_STEP)
        self._amp_spin.setDecimals(2)
        self._amp_spin.setValue(self.driver.amp)
        self._amp_spin.valueChanged.connect(lambda v: setattr(self.driver, "amp", float(v)))
        form.addRow("Amplitude", self._amp_spin)

        btns = QHBoxLayout()
        self._run_btn = QPushButton("▶ Run wave")
        self._run_btn.setCheckable(True)
        self._run_btn.toggled.connect(self._toggle_wave)
        step_btn = QPushButton("Step")
        step_btn.setProperty("role", "secondary")
        step_btn.clicked.connect(lambda: self.driver.step(self.driver.amp))
        pulse_btn = QPushButton("Pulse")
        pulse_btn.setProperty("role", "secondary")
        pulse_btn.clicked.connect(lambda: self.driver.pulse(self.driver.amp, 250))
        btns.addWidget(self._run_btn)
        btns.addWidget(step_btn)
        btns.addWidget(pulse_btn)
        form.addRow(btns)

        self._manual = QSlider(Qt.Orientation.Horizontal)
        self._manual.setRange(0, 1000)
        self._manual.valueChanged.connect(
            lambda i: self.driver.set_manual(i / 1000.0) if not self.driver.running else None)
        form.addRow("Manual", self._manual)
        return g

    def _build_output_group(self) -> QGroupBox:
        g = QGroupBox("Output  (Intiface virtual toy)")
        self._out_group = g
        form = QFormLayout(g)
        last = state.last_toy()  # restore the previous toy setup if any

        self._model_combo = QComboBox()
        for m in MODELS:
            n = len(m.features)
            self._model_combo.addItem(f"{m.name}  ({n} motor{'s' if n != 1 else ''})", userData=m)
        if last.get("model"):
            for i in range(self._model_combo.count()):
                m = self._model_combo.itemData(i)
                if m is not None and m.name == last["model"]:
                    self._model_combo.setCurrentIndex(i)
                    break
        form.addRow("Model", self._model_combo)

        self._id_edit = QLineEdit(last.get("identifier") or DEFAULT_WS_IDENTIFIER)
        form.addRow("Identifier", self._id_edit)
        self._url_edit = QLineEdit(last.get("url") or DEFAULT_WSDM_URL)
        form.addRow("WSDM URL", self._url_edit)

        self._connect_btn = QPushButton("Connect toy")
        self._connect_btn.setCheckable(True)
        self._connect_btn.toggled.connect(self._toggle_toy)
        form.addRow(self._connect_btn)

        self._feature_combo = QComboBox()
        self._feature_combo.currentIndexChanged.connect(self._apply_feature_index)
        form.addRow("Watched motor", self._feature_combo)

        self._level_bar = QProgressBar()
        self._level_bar.setRange(0, 1000)
        self._level_bar.setFormat("%p%")
        form.addRow("Live level", self._level_bar)
        return g

    def _build_bench_group(self) -> QGroupBox:
        g = QGroupBox("Benchmark  (end-to-end latency)")
        self._bench_group = g
        form = QFormLayout(g)

        self._in_thr = QDoubleSpinBox()
        self._in_thr.setRange(0.01, 1.0)
        self._in_thr.setSingleStep(0.05)
        self._in_thr.setValue(0.5)
        self._in_thr.valueChanged.connect(lambda v: self.bench.set_input_threshold(float(v)))
        form.addRow("Input edge ≥", self._in_thr)

        self._out_thr = QDoubleSpinBox()
        self._out_thr.setRange(0.01, 1.0)
        self._out_thr.setSingleStep(0.01)
        self._out_thr.setValue(0.05)
        self._out_thr.valueChanged.connect(lambda v: self.bench.set_output_threshold(float(v)))
        form.addRow("Output edge ≥", self._out_thr)

        self._cycles = QSpinBox()
        self._cycles.setRange(1, 1000)
        self._cycles.setValue(20)
        form.addRow("Cycles", self._cycles)

        runrow = QHBoxLayout()
        self._bench_btn = QPushButton("Run benchmark")
        self._bench_btn.clicked.connect(self._run_benchmark)
        reset_btn = QPushButton("Reset")
        reset_btn.setProperty("role", "secondary")
        reset_btn.clicked.connect(self._reset_bench)
        export_btn = QPushButton("Export CSV")
        export_btn.setProperty("role", "secondary")
        export_btn.clicked.connect(self._export_csv)
        runrow.addWidget(self._bench_btn)
        runrow.addWidget(reset_btn)
        runrow.addWidget(export_btn)
        form.addRow(runrow)

        self._stat_labels = {}
        for key, label in (
            ("count", "Samples"), ("mean_ms", "Mean"), ("median_ms", "Median"),
            ("p95_ms", "p95"), ("min_ms", "Min"), ("max_ms", "Max"),
            ("jitter_ms", "Jitter σ"), ("misses", "Misses"),
        ):
            lab = QLabel("—")
            self._stat_labels[key] = lab
            form.addRow(label, lab)
        return g

    def _build_plots(self) -> QWidget:
        host = QWidget()
        col = QVBoxLayout(host)
        col.setContentsMargins(0, 0, 0, 0)
        self.live_plot = LivePlot(window_s=8.0)
        self.hist = LatencyHistogram()
        col.addWidget(self.live_plot, 3)
        col.addWidget(self.hist, 2)
        return host

    # ----------------------------------------------------------- mode
    def _apply_mode(self, mode: str) -> None:
        self._in_group.setVisible(mode in ("Input", "Benchmark"))
        self._out_group.setVisible(mode in ("Output", "Benchmark"))
        self._bench_group.setVisible(mode == "Benchmark")
        self.hist.setVisible(mode == "Benchmark")

    # ----------------------------------------------------------- input wiring
    def _apply_avatar_index(self, idx: int) -> None:
        if idx < 0 or idx >= len(sim_avatar.AVATAR_PRESETS):
            return
        preset = sim_avatar.AVATAR_PRESETS[idx]
        self.net.set_avatar(preset)
        self._channels = channels_for_preset(preset)
        self._channel_combo.blockSignals(True)
        self._channel_combo.clear()
        for label, _fn in self._channels:
            self._channel_combo.addItem(label)
        self._channel_combo.blockSignals(False)
        if self._channels:
            self._channel_combo.setCurrentIndex(0)
            self._apply_channel_index(0)
        else:
            self._channel = None
            self._log("[input] avatar has no SPS zones to drive — pick another preset")

    def _apply_channel_index(self, idx: int) -> None:
        if 0 <= idx < len(getattr(self, "_channels", [])):
            self._channel = self._channels[idx][1]

    def _emit_input(self, value: float) -> None:
        """Sink for SignalDriver: send OSC then stamp the input sample."""
        t = _CLOCK()
        if self._channel is not None:
            self._channel(self.net, value)
        self.bench.record_input(t, value)

    def _toggle_wave(self, on: bool) -> None:
        if on:
            self.driver.start_wave()
            self._run_btn.setText("■ Stop wave")
            self._manual.setEnabled(False)
        else:
            self.driver.stop_wave()
            self._run_btn.setText("▶ Run wave")
            self._manual.setEnabled(True)

    # ----------------------------------------------------------- output wiring
    def _toggle_toy(self, on: bool) -> None:
        if on:
            model: LovenseModel = self._model_combo.currentData()
            if model is None:
                self._connect_btn.setChecked(False)
                return
            ident = self._id_edit.text().strip() or DEFAULT_WS_IDENTIFIER
            url = self._url_edit.text().strip() or DEFAULT_WSDM_URL
            # Stable per-model address so the virtual toy keeps ONE identity
            # across restarts — Intiface/OGB/OGP match toys by this serial, so a
            # random address each launch is what made it re-appear as new.
            proto = LovenseProtocol(model, state.toy_address(model.name),
                                    ws_identifier=ident)
            state.remember_toy(model.name, ident, url)
            self.toy = LovenseToy(
                proto, url=url,
                on_levels=self._on_toy_levels_worker,
                on_log=lambda m: self.bridge.toy_log.emit(f"toy: {m}"),
                on_state=lambda c, e: self.bridge.toy_state.emit(c, e),
            )
            self._toy_model = model
            self._rebuild_feature_combo(model)
            self.toy.start()
            self._connect_btn.setText("Disconnect toy")
            self._model_combo.setEnabled(False)
        else:
            if self.toy is not None:
                self.toy.stop()
                self.toy = None
            self._connect_btn.setText("Connect toy")
            self._model_combo.setEnabled(True)
            self._toy_label.setText("Intiface: not connected")

    def _rebuild_feature_combo(self, model: LovenseModel) -> None:
        self._feature_combo.blockSignals(True)
        self._feature_combo.clear()
        for i, feat in enumerate(model.features):
            self._feature_combo.addItem(f"{i}: {feat.label} ({feat.kind})", userData=i)
        self._feature_combo.blockSignals(False)
        self._watch_idx = 0
        self._feature_combo.setCurrentIndex(0)

    def _apply_feature_index(self, combo_idx: int) -> None:
        data = self._feature_combo.currentData()
        self._watch_idx = int(data) if data is not None else 0

    def _on_toy_levels_worker(self, updates) -> None:
        """Worker-thread callback: stamp + record the watched motor NOW."""
        t = _CLOCK()
        for idx, level in updates:
            if idx == self._watch_idx:
                self.bench.record_output(t, level)
        self.bridge.toy_levels.emit(list(updates))

    def _on_toy_levels_ui(self, updates) -> None:
        for idx, level in updates:
            if idx == self._watch_idx:
                self._level_bar.setValue(int(round(level * 1000)))

    def _on_toy_state(self, connected: bool, err: object) -> None:
        if connected:
            self._toy_label.setText("Intiface: ● connected")
            self._toy_label.setStyleSheet(f"color: {COLOR_SUCCESS};")
        else:
            tail = f" — {err}" if err else ""
            self._toy_label.setText(f"Intiface: ○ disconnected{tail}")
            self._toy_label.setStyleSheet(f"color: {COLOR_LIVE};")
            self._level_bar.setValue(0)

    # ----------------------------------------------------------- benchmark
    def _run_benchmark(self) -> None:
        if self.net.active_target_label() is None:
            QMessageBox.information(
                self, "No target selected",
                "Pick a target app (or set a manual host:port) so the input "
                "signal has somewhere to go.")
            return
        if self.toy is None:
            QMessageBox.information(
                self, "Connect a toy first",
                "Connect the virtual toy and make sure the target app is routing "
                "the chosen input channel to it before running the benchmark.")
            return
        self.bench.reset()
        freq = max(FREQ_MIN, float(self._freq_spin.value()))
        cycles = int(self._cycles.value())
        self.driver.waveform = "square"
        self._wave_combo.setCurrentText("square")
        if not self._run_btn.isChecked():
            self._run_btn.setChecked(True)  # starts the wave via _toggle_wave
        # Auto-stop after N cycles (+ half a cycle of slack for the last edge).
        duration_ms = int(((cycles + 0.5) / freq) * 1000)
        self._log(f"[bench] running {cycles} cycles @ {freq:.2f} Hz (~{duration_ms} ms)")
        QTimer.singleShot(duration_ms, self._finish_benchmark)

    def _finish_benchmark(self) -> None:
        if self._run_btn.isChecked():
            self._run_btn.setChecked(False)  # stops the wave
        s = self.bench.stats()
        self._log(
            f"[bench] done — {s['count']} samples, "
            f"mean {self._fmt(s['mean_ms'])}, p95 {self._fmt(s['p95_ms'])}, "
            f"misses {self.bench.misses()}")

    def _reset_bench(self) -> None:
        self.bench.reset()
        self._log("[bench] reset")

    def _export_csv(self) -> None:
        lat = self.bench.latencies_ms()
        if not lat:
            QMessageBox.information(self, "Nothing to export",
                                    "Run a benchmark first — no latencies recorded yet.")
            return
        base, _ = QFileDialog.getSaveFileName(self, "Export benchmark CSVs", "bench_run")
        if not base:
            return
        in_arr, out_arr = self.bench.snapshot()
        files = csv_export.export_all(
            base, in_arr, out_arr, lat, self.bench.stats(), self.bench.misses())
        self._log("[bench] wrote:\n  " + "\n  ".join(files))

    # ----------------------------------------------------------- refresh
    def _tick_refresh(self) -> None:
        in_arr, out_arr = self.bench.snapshot()
        self.live_plot.update_from(in_arr, out_arr)
        self._refresh_count += 1
        if self._refresh_count % 5 == 0:  # ~4 Hz for stats/histogram
            self._update_stats()

    def _update_stats(self) -> None:
        s = self.bench.stats()
        for key, lab in self._stat_labels.items():
            if key == "misses":
                lab.setText(str(self.bench.misses()))
            elif key == "count":
                lab.setText(str(s["count"]))
            else:
                lab.setText(self._fmt(s.get(key)))
        self.hist.update_from(self.bench.latencies_ms())

    @staticmethod
    def _fmt(ms: Optional[float]) -> str:
        return "—" if ms is None else f"{ms:.1f} ms"

    # ----------------------------------------------------------- targets
    def _on_target_combo_activated(self, idx: int) -> None:
        name = self._target_combo.itemText(idx)
        if name:
            self.net.select_target(name, user=True)

    def _use_manual_target(self) -> None:
        host = self._host_edit.text().strip() or "127.0.0.1"
        self.net.set_manual_target(host, int(self._port_spin.value()))

    def _on_targets_changed(self, names: list) -> None:
        cur = self.net.active_target_label()
        self._target_combo.blockSignals(True)
        self._target_combo.clear()
        self._target_combo.addItems(names)
        if cur in names:
            self._target_combo.setCurrentText(cur)
        self._target_combo.blockSignals(False)
        if not names:
            self._target_status.setText("Target: none discovered")
            self._target_status.setStyleSheet(f"color: {COLOR_TEXT_MUTED};")

    def _on_target_changed(self, label) -> None:
        if label:
            self._target_status.setText(f"Target: ● {label}")
            self._target_status.setStyleSheet(f"color: {COLOR_SUCCESS};")
            if self._target_combo.findText(label) >= 0:
                self._target_combo.blockSignals(True)
                self._target_combo.setCurrentText(label)
                self._target_combo.blockSignals(False)
        else:
            self._target_status.setText("Target: none")
            self._target_status.setStyleSheet(f"color: {COLOR_TEXT_MUTED};")

    # ----------------------------------------------------------- misc
    def _log(self, msg: str) -> None:
        self._log_view.appendPlainText(msg)

    def closeEvent(self, event) -> None:  # noqa: N802 — Qt API
        try:
            if self.toy is not None:
                self.toy.stop()
            self.net.stop()
        finally:
            super().closeEvent(event)


def run() -> int:
    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(_APP_USER_MODEL_ID)
        except Exception:
            pass
    app = QApplication.instance() or QApplication([])
    app.setStyleSheet(GLOBAL_QSS)
    icon = _icon_path()
    if icon:
        app.setWindowIcon(QIcon(icon))
    win = TestBenchWindow()
    win.show()
    return app.exec()
