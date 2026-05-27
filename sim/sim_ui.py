"""PySide6 UI for the VRChat simulator.

A small window that lets you drive every avatar parameter OscGoesPurrr
cares about: SPS zone touch / penetration sliders, an automated thrust
animator, and a bHaptics contact dot grid. The UI is rebuilt each time
the avatar dropdown changes so panels always match the active preset's
zone list.
"""

from __future__ import annotations

import math
import os
import sys
import time
from typing import Any, Dict, List, Optional, Tuple

from PySide6.QtCore import Qt, QObject, QTimer, Signal
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QApplication, QComboBox, QDoubleSpinBox, QFrame, QGridLayout,
    QHBoxLayout, QLabel, QMainWindow, QPlainTextEdit, QPushButton,
    QScrollArea, QSizePolicy, QSlider, QTabWidget, QVBoxLayout, QWidget,
)

from . import sim_avatar
from .sim_network import VRChatSimNetwork
from .sim_style import GLOBAL_QSS


# Windows groups taskbar entries by AppUserModelID. Setting a distinct ID
# before any window is shown stops the simulator from sharing a taskbar slot
# (and icon) with the main OscGoesPurrr app when both are running.
_SIM_APP_USER_MODEL_ID = "OscGoesPurrr.Simulator"


def _sim_icon_path() -> Optional[str]:
    """Resolve OGP_Sim_Icon.ico for both source-tree and PyInstaller --onefile
    layouts. Returns None if the file genuinely isn't present so callers can
    fall back rather than crash."""
    if getattr(sys, "frozen", False):
        base = getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
    else:
        # sim/sim_ui.py → project root is one directory up.
        base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    candidate = os.path.join(base, "Images", "OGP_Sim_Icon.ico")
    return candidate if os.path.exists(candidate) else None


# ---------------------------------------------------------------- thread bridge

class _SignalBridge(QObject):
    """Marshals network-thread callbacks onto the Qt main thread.

    Network code calls plain Python callbacks; these wrap a Qt signal so
    the actual slot runs on the GUI thread (Qt's queued connections handle
    the hop). Without this every network event would touch widgets from
    a background thread → crashes on first paint.
    """
    status_changed = Signal(str)
    ogp_discovered = Signal(int)
    ogp_lost = Signal()
    inbound_osc = Signal(str, tuple)


# ----------------------------------------------------------------- helpers

def _make_card(header: str, subheader: str = "") -> Tuple[QFrame, QVBoxLayout]:
    """Build a styled card frame with header + (optional) subheader. Returns
    (card_frame, body_layout) — append content widgets to the body layout."""
    card = QFrame()
    card.setObjectName("card")
    outer = QVBoxLayout(card)
    outer.setContentsMargins(14, 12, 14, 12)
    outer.setSpacing(6)

    title = QLabel(header)
    title.setObjectName("cardHeader")
    outer.addWidget(title)

    if subheader:
        sub = QLabel(subheader)
        sub.setObjectName("cardSubheader")
        outer.addWidget(sub)

    return card, outer


def _slider_row(label: str, on_change) -> Tuple[QWidget, QSlider, QLabel]:
    """Build a labelled 0..1 float slider that calls `on_change(float)`.

    Labels are narrower than before (90px) so the slider track stays as long
    as possible inside a half-width card. The value readout uses tabular
    digits so the column doesn't jitter as the value scrolls."""
    wrapper = QWidget()
    row = QHBoxLayout(wrapper)
    row.setContentsMargins(0, 0, 0, 0)
    row.setSpacing(8)
    lab = QLabel(label)
    lab.setObjectName("sliderLabel")
    lab.setMinimumWidth(72)
    val_lab = QLabel("0.00")
    val_lab.setObjectName("sliderValue")
    val_lab.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
    slider = QSlider(Qt.Orientation.Horizontal)
    slider.setRange(0, 1000)
    slider.setValue(0)

    def _emit(v: int) -> None:
        f = v / 1000.0
        val_lab.setText(f"{f:.2f}")
        on_change(f)

    slider.valueChanged.connect(_emit)
    row.addWidget(lab)
    row.addWidget(slider, 1)
    row.addWidget(val_lab)
    return wrapper, slider, val_lab


# ---------------------------------------------------------------- signal gen

# Match the main app's set of shapes verbatim (mixer.py:279) so the
# vocabulary is identical across both UIs. Keep "sine" first — it's what the
# Play button defaults to and the most common test case.
WAVEFORMS = ("sine", "square", "triangle", "sawtooth")

# Frequency / amplitude bounds copied from ui/motor_signal_chain.py:1961-1973
# so the spinbox steps match the main app's signal-generator panel. Step is
# 0.05 — fine enough to dial in without click-spamming.
_FREQ_MIN, _FREQ_MAX, _FREQ_STEP = 0.05, 5.0, 0.05
_AMP_MIN, _AMP_MAX, _AMP_STEP = 0.0, 1.0, 0.05


def _sample_pattern(waveform: str, freq_hz: float, amp: float, t_s: float) -> float:
    """Compute one sample of a parametric signal — pure function, no state.

    Verbatim port of mixer.sample_pattern() (mixer.py:282-321). Kept inline
    instead of imported so the sim stays decoupled from the main app per
    the run_sim.bat contract. Output range is [0, amp]: `d_raw` is unsigned
    by convention in the main app, so the sim mirrors that.
    """
    if freq_hz <= 0.0:
        return 0.0
    phase = (float(freq_hz) * float(t_s)) % 1.0
    if waveform == "sine":
        return float(amp) * (0.5 + 0.5 * math.sin(2.0 * math.pi * phase))
    if waveform == "square":
        return float(amp) if phase < 0.5 else 0.0
    if waveform == "triangle":
        if phase < 0.5:
            return float(amp) * (2.0 * phase)
        return float(amp) * (2.0 * (1.0 - phase))
    if waveform == "sawtooth":
        return float(amp) * phase
    return 0.0


class _SignalGenerator(QObject):
    """Drives a target QSlider with one of the WAVEFORMS shapes. The slider
    is what visually moves and (via its existing valueChanged signal) what
    sends OSC downstream — the generator just nudges the slider value at
    ~30 Hz. This means the user sees the animation in the same widget they
    were manually dragging, and there is exactly one OSC code path
    regardless of whether the value came from a drag or the generator.
    """

    def __init__(self, target_slider: QSlider, parent: QObject = None) -> None:
        super().__init__(parent)
        self._slider = target_slider
        self._timer = QTimer(self)
        self._timer.setInterval(33)  # ~30 Hz
        self._timer.timeout.connect(self._tick)
        self._t0: float = 0.0

        self.freq: float = 1.4
        self.amp: float = 1.0
        self.waveform: str = "sine"

    @property
    def running(self) -> bool:
        return self._timer.isActive()

    def start(self) -> None:
        self._t0 = time.monotonic()
        self._timer.start()
        # Lock the slider while we drive it — a manual drag would just be
        # overwritten on the next tick anyway, so disable it to make the
        # "auto" mode visually obvious.
        self._slider.setEnabled(False)

    def stop(self) -> None:
        self._timer.stop()
        self._slider.setEnabled(True)
        # Snap back to 0 so the zone goes idle. Without this the motor
        # would freeze at whatever phase we stopped on, which is rarely
        # what the user wants when they hit Stop.
        self._slider.setValue(0)

    def _tick(self) -> None:
        t = time.monotonic() - self._t0
        v = _sample_pattern(self.waveform, self.freq, self.amp, t)
        # QSlider is integer-only; the row helpers use 0..1000 to encode 0..1.
        self._slider.setValue(int(round(v * 1000)))


def _build_signal_panel(generator: _SignalGenerator) -> Tuple[QHBoxLayout, QHBoxLayout, QPushButton]:
    """Build the two compact rows that drive a `_SignalGenerator` — shape
    combo + freq/amp spinboxes on row one, Play/Stop toggle on row two.

    Returns `(controls_row, button_row, play_btn)`. The caller is responsible
    for adding `play_btn` to whatever action row it wants (we hand it back
    so a sibling Reset button can sit next to it). Spinboxes and combo write
    straight into the generator's public fields so the changes apply on the
    next tick without restarting the timer.
    """
    ctrl = QHBoxLayout()
    ctrl.setSpacing(6)
    ctrl.setContentsMargins(0, 0, 0, 0)

    shape_lab = QLabel("Shape:")
    shape_lab.setObjectName("sliderLabel")
    ctrl.addWidget(shape_lab)
    shape_combo = QComboBox()
    shape_combo.addItems(list(WAVEFORMS))
    shape_combo.setCurrentText(generator.waveform)
    shape_combo.currentTextChanged.connect(lambda s: setattr(generator, "waveform", s))
    ctrl.addWidget(shape_combo)

    freq_spin = QDoubleSpinBox()
    freq_spin.setRange(_FREQ_MIN, _FREQ_MAX)
    freq_spin.setSingleStep(_FREQ_STEP)
    freq_spin.setDecimals(2)
    freq_spin.setSuffix(" Hz")
    freq_spin.setValue(generator.freq)
    freq_spin.valueChanged.connect(lambda v: setattr(generator, "freq", float(v)))
    ctrl.addWidget(freq_spin)

    amp_spin = QDoubleSpinBox()
    amp_spin.setRange(_AMP_MIN, _AMP_MAX)
    amp_spin.setSingleStep(_AMP_STEP)
    amp_spin.setDecimals(2)
    amp_spin.setPrefix("Amp ")
    amp_spin.setValue(generator.amp)
    amp_spin.valueChanged.connect(lambda v: setattr(generator, "amp", float(v)))
    ctrl.addWidget(amp_spin)
    ctrl.addStretch(1)

    button_row = QHBoxLayout()
    button_row.setSpacing(6)
    button_row.setContentsMargins(0, 0, 0, 0)
    play_btn = QPushButton("▶ Play")
    play_btn.setCheckable(True)

    def _toggle(on: bool) -> None:
        if on:
            generator.start()
            play_btn.setText("■ Stop")
        else:
            generator.stop()
            play_btn.setText("▶ Play")

    play_btn.toggled.connect(_toggle)
    button_row.addWidget(play_btn)
    return ctrl, button_row, play_btn


# ----------------------------------------------------------------- zone panels

class _OrificePanel(QFrame):
    """Carded orifice panel — exposes only the inputs the main app actually
    consumes off an /OGB/Orf/<name>/ zone:

      * Touch  — sends TouchOthers + auto-asserts TouchOthersClose
                 (matches motor_router.py:362 which gates touch on Close)
      * Insertion — sends legacy PenOthers + auto-asserts PenOthersClose
                 (motor_router.py:388–395; legacy is simpler than new-pen
                  for manual control because it skips depth calibration)
      * Frot   — sends FrotOthers (no gate on orifice side per :399)
      * Animate Thrust — toggles the new-pen Root/Tip oscillator so the
                 depth-detector code path (motor_router.py:25–110, 302–333)
                 also gets exercised end-to-end
      * Reset  — zeros every suffix this panel ever writes

    Self-side parameters (TouchSelf, PenSelf, etc.) are intentionally
    hidden — motor_router defaults `motor_<idx>_self=False` so the main
    app ignores them in the default config. Surface them later if a
    real test-case ever needs them.
    """

    def __init__(self, net: VRChatSimNetwork, zone_name: str) -> None:
        super().__init__()
        self.setObjectName("card")
        self.net = net
        self.zone = zone_name
        self.prefix = f"OGB/Orf/{zone_name}"
        self._build()

    def _build(self) -> None:
        col = QVBoxLayout(self)
        col.setContentsMargins(14, 12, 14, 12)
        col.setSpacing(6)

        header = QLabel(f"Orifice — {self.zone}")
        header.setObjectName("cardHeader")
        col.addWidget(header)

        # Keep references to every slider so Reset can zero them visually —
        # each slider's valueChanged signal already sends the corresponding
        # OSC zero downstream, so Reset doesn't need any explicit OSC writes.
        touch_widget, self._touch_slider, _ = _slider_row("Touch", self._set_touch)
        col.addWidget(touch_widget)

        # The signal generator drives the Insertion slider — its existing
        # valueChanged → _set_pen wiring is what sends OSC, so we don't
        # need a parallel write path through the generator.
        insertion_widget, self._insertion_slider, _ = _slider_row("Insertion", self._set_pen)
        col.addWidget(insertion_widget)

        frot_widget, self._frot_slider, _ = _slider_row(
            "Frot", lambda v: self.net.set_param(f"{self.prefix}/FrotOthers", v)
        )
        col.addWidget(frot_widget)

        self.generator = _SignalGenerator(self._insertion_slider, self)
        ctrl_row, button_row, self._play_btn = _build_signal_panel(self.generator)
        col.addLayout(ctrl_row)

        reset_btn = QPushButton("Reset")
        reset_btn.setProperty("role", "secondary")
        reset_btn.clicked.connect(self._reset)
        button_row.addWidget(reset_btn)
        button_row.addStretch(1)
        col.addLayout(button_row)

    # ---- slider handlers ----

    def _set_touch(self, v: float) -> None:
        """Drive TouchOthers + auto-assert TouchOthersClose. The main app
        won't fire haptics unless Close=true (motor_router.py:362), so a
        single slider would otherwise be silently inert."""
        self.net.set_param(f"{self.prefix}/TouchOthersClose", v > 0.0)
        self.net.set_param(f"{self.prefix}/TouchOthers", v)

    def _set_pen(self, v: float) -> None:
        """Drive legacy PenOthers + auto-assert PenOthersClose. We use
        legacy here (not new-pen Root/Tip) because legacy is a direct
        float — no length-calibration warm-up needed before haptics fire."""
        self.net.set_param(f"{self.prefix}/PenOthersClose", v > 0.0)
        self.net.set_param(f"{self.prefix}/PenOthers", v)

    def _reset(self) -> None:
        # Untoggling Play stops the generator and lets it re-enable + zero
        # the insertion slider itself (see _SignalGenerator.stop()). The
        # remaining sliders' valueChanged handlers send the OSC zeroes.
        if self.generator.running:
            self._play_btn.setChecked(False)
        self._touch_slider.setValue(0)
        self._insertion_slider.setValue(0)
        self._frot_slider.setValue(0)


class _PenetratorPanel(QFrame):
    """Carded penetrator panel — exposes the inputs the main app reads off
    an /OGB/Pen/<name>/ zone (motor_router.py:403–422):

      * Insertion — PenOthers (raw float; penetrators don't get new-pen)
      * Frot      — FrotOthers + auto-asserts FrotOthersClose
                    (motor_router.py:419 gates frot on Close for penetrators)
      * Animate Thrust / Reset

    No touch sliders — penetrators don't receive Touch* in the router.
    No self-side sliders — same `motor_<idx>_self=False` default as orifices.
    """

    def __init__(self, net: VRChatSimNetwork, zone_name: str) -> None:
        super().__init__()
        self.setObjectName("card")
        self.net = net
        self.zone = zone_name
        self.prefix = f"OGB/Pen/{zone_name}"
        self._build()

    def _build(self) -> None:
        col = QVBoxLayout(self)
        col.setContentsMargins(14, 12, 14, 12)
        col.setSpacing(6)

        header = QLabel(f"Penetrator — {self.zone}")
        header.setObjectName("cardHeader")
        col.addWidget(header)

        insertion_widget, self._insertion_slider, _ = _slider_row(
            "Insertion", lambda v: self.net.set_param(f"{self.prefix}/PenOthers", v)
        )
        col.addWidget(insertion_widget)
        frot_widget, self._frot_slider, _ = _slider_row("Frot", self._set_frot)
        col.addWidget(frot_widget)

        self.generator = _SignalGenerator(self._insertion_slider, self)
        ctrl_row, button_row, self._play_btn = _build_signal_panel(self.generator)
        col.addLayout(ctrl_row)

        reset_btn = QPushButton("Reset")
        reset_btn.setProperty("role", "secondary")
        reset_btn.clicked.connect(self._reset)
        button_row.addWidget(reset_btn)
        button_row.addStretch(1)
        col.addLayout(button_row)

    def _set_frot(self, v: float) -> None:
        """Drive FrotOthers + auto-assert FrotOthersClose on the penetrator
        side (motor_router.py:419 requires Close=true)."""
        self.net.set_param(f"{self.prefix}/FrotOthersClose", v > 0.0)
        self.net.set_param(f"{self.prefix}/FrotOthers", v)

    def _reset(self) -> None:
        if self.generator.running:
            self._play_btn.setChecked(False)
        self._insertion_slider.setValue(0)
        self._frot_slider.setValue(0)


# ----------------------------------------------------------- bHaptics grid

class _BHapticsGrid(QFrame):
    """A clickable dot grid for one bHaptics position. Each cell toggles the
    bHaptics_<Slot>_<N>_bool parameter."""

    # Grid shapes mirror bhaptics_router._GRID_LAYOUTS so the simulator
    # presents the dots in the same layout the main app shows them.
    _LAYOUTS = {
        "Head":      (6, 1),
        "VestFront": (4, 5),
        "VestBack":  (4, 5),
        "ForearmL":  (2, 3),
        "ForearmR":  (2, 3),
        "HandL":     (3, 1),
        "HandR":     (3, 1),
        "FootL":     (3, 1),
        "FootR":     (3, 1),
    }

    def __init__(self, net: VRChatSimNetwork, position: str, slot: str, count: int) -> None:
        super().__init__()
        self.setObjectName("card")
        title = position.replace("Vest", "Vest ").replace("Forearm", "Forearm ").replace("Hand", "Hand ").replace("Foot", "Foot ")
        self._title = title.strip()
        self.net = net
        self.position = position
        self.slot = slot
        self.count = count
        self._buttons: List[QPushButton] = []
        self._build()

    def _build(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(14, 12, 14, 12)
        outer.setSpacing(8)

        header = QLabel(f"bHaptics — {self._title}")
        header.setObjectName("cardHeader")
        outer.addWidget(header)

        grid = QGridLayout()
        grid.setSpacing(4)
        cols, _rows = self._LAYOUTS.get(self.position, (self.count, 1))
        for n in range(1, self.count + 1):
            idx = n - 1
            r, c = divmod(idx, cols)
            btn = QPushButton(str(n))
            btn.setCheckable(True)
            btn.setProperty("role", "dot")
            btn.setFixedSize(34, 34)
            btn.toggled.connect(self._dot_handler(n))
            self._buttons.append(btn)
            grid.addWidget(btn, r, c)
        outer.addLayout(grid)

        row = QHBoxLayout()
        row.setSpacing(6)
        all_on = QPushButton("All On")
        all_off = QPushButton("All Off")
        all_off.setProperty("role", "secondary")
        pulse = QPushButton("Pulse")
        pulse.setProperty("role", "secondary")
        all_on.clicked.connect(lambda: self._set_all(True))
        all_off.clicked.connect(lambda: self._set_all(False))
        pulse.clicked.connect(self._pulse)
        row.addWidget(all_on)
        row.addWidget(all_off)
        row.addWidget(pulse)
        row.addStretch(1)
        outer.addLayout(row)

    def _dot_handler(self, n: int):
        def _on(checked: bool) -> None:
            self.net.set_param(f"bHaptics_{self.slot}_{n}_bool", bool(checked))
        return _on

    def _set_all(self, on: bool) -> None:
        for btn in self._buttons:
            btn.setChecked(on)  # toggled signal fires the OSC send

    def _pulse(self) -> None:
        self._set_all(True)
        QTimer.singleShot(400, lambda: self._set_all(False))


# ----------------------------------------------------------- main window

class SimulatorMainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("VRChat Simulator — OscGoesPurrr test rig")
        self.resize(1100, 760)

        icon_path = _sim_icon_path()
        if icon_path is not None:
            icon = QIcon(icon_path)
            self.setWindowIcon(icon)
            app = QApplication.instance()
            if app is not None:
                app.setWindowIcon(icon)

        self.bridge = _SignalBridge()
        self.net = VRChatSimNetwork(
            on_ogp_discovered=lambda port: self.bridge.ogp_discovered.emit(port),
            on_ogp_lost=lambda: self.bridge.ogp_lost.emit(),
            on_inbound_osc=lambda a, v: self.bridge.inbound_osc.emit(a, tuple(v)),
            on_status=lambda m: self.bridge.status_changed.emit(m),
        )
        self.bridge.status_changed.connect(self._on_status)
        self.bridge.ogp_discovered.connect(self._on_ogp_discovered)
        self.bridge.ogp_lost.connect(self._on_ogp_lost)
        self.bridge.inbound_osc.connect(self._on_inbound_osc)

        self._build_ui()
        self.net.start()
        info = self.net.listen_info()
        self._status_label.setText(
            f"Service: {info['service_name']}  ·  "
            f"OSC UDP {info['osc_listen_port']}  ·  "
            f"HTTP {info['http_listen_port']}  ·  "
            f"Waiting for OscGoesPurrr…"
        )
        # Apply the default avatar so the panels populate immediately.
        self._apply_avatar_index(0)

    # ----------------------------------------------------------- construction

    def _build_ui(self) -> None:
        central = QWidget()
        central.setObjectName("root")
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(8)

        # Top bar — avatar selector + status
        bar = QHBoxLayout()
        bar.setSpacing(8)
        title = QLabel("Avatar:")
        title.setObjectName("sectionTitle")
        bar.addWidget(title)
        self._avatar_combo = QComboBox()
        for p in sim_avatar.AVATAR_PRESETS:
            self._avatar_combo.addItem(p.display_name, userData=p.avatar_id)
        self._avatar_combo.currentIndexChanged.connect(self._apply_avatar_index)
        bar.addWidget(self._avatar_combo, 1)
        self._reblast_btn = QPushButton("Resend All Params")
        self._reblast_btn.setProperty("role", "secondary")
        self._reblast_btn.clicked.connect(self.net.resend_all)
        bar.addWidget(self._reblast_btn)
        root.addLayout(bar)

        self._status_label = QLabel("Starting…")
        self._status_label.setObjectName("statusBar")
        root.addWidget(self._status_label)

        # Tabs
        self._tabs = QTabWidget()
        root.addWidget(self._tabs, 1)

        # SPS tab — scrollable, two-column card grid
        self._sps_scroll = QScrollArea()
        self._sps_scroll.setWidgetResizable(True)
        self._sps_host = QWidget()
        self._sps_layout = QGridLayout(self._sps_host)
        self._sps_layout.setContentsMargins(8, 8, 8, 8)
        self._sps_layout.setHorizontalSpacing(10)
        self._sps_layout.setVerticalSpacing(10)
        self._sps_scroll.setWidget(self._sps_host)
        self._tabs.addTab(self._sps_scroll, "SPS Zones")

        # bHaptics tab — scrollable, two-column card grid
        self._bh_scroll = QScrollArea()
        self._bh_scroll.setWidgetResizable(True)
        self._bh_host = QWidget()
        self._bh_layout = QGridLayout(self._bh_host)
        self._bh_layout.setContentsMargins(8, 8, 8, 8)
        self._bh_layout.setHorizontalSpacing(10)
        self._bh_layout.setVerticalSpacing(10)
        self._bh_scroll.setWidget(self._bh_host)
        self._tabs.addTab(self._bh_scroll, "bHaptics Contacts")

        # Inbound OSC log
        log_host = QWidget()
        log_layout = QVBoxLayout(log_host)
        log_layout.setContentsMargins(8, 8, 8, 8)
        self._log = QPlainTextEdit()
        self._log.setReadOnly(True)
        self._log.setMaximumBlockCount(2000)
        log_layout.addWidget(self._log, 1)
        log_actions = QHBoxLayout()
        clear_btn = QPushButton("Clear")
        clear_btn.setProperty("role", "secondary")
        clear_btn.clicked.connect(self._log.clear)
        log_actions.addWidget(clear_btn)
        log_actions.addStretch(1)
        log_layout.addLayout(log_actions)
        self._tabs.addTab(log_host, "Inbound OSC (from OGP)")

    # ----------------------------------------------------- avatar switching

    def _apply_avatar_index(self, idx: int) -> None:
        if idx < 0 or idx >= len(sim_avatar.AVATAR_PRESETS):
            return
        preset = sim_avatar.AVATAR_PRESETS[idx]
        self.net.set_avatar(preset)
        self._rebuild_zone_panels(preset)
        self._rebuild_bhaptics_panels(preset)

    # Two cards per row keeps each slider track around half-window-width —
    # long enough to be precise, short enough to read at a glance. Three+
    # makes the cards narrow enough that slider labels start truncating.
    _CARDS_PER_ROW = 2

    def _clear_layout(self, layout) -> None:
        while layout.count() > 0:
            item = layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.setParent(None)
                w.deleteLater()
            else:
                child = item.layout()
                if child is not None:
                    self._clear_layout(child)

    def _empty_label(self, text: str) -> QLabel:
        lab = QLabel(text)
        lab.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lab.setObjectName("statusBar")
        lab.setMinimumHeight(120)
        return lab

    def _place_grid_card(self, grid: QGridLayout, idx: int, widget: QWidget) -> None:
        row, col = divmod(idx, self._CARDS_PER_ROW)
        widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        grid.addWidget(widget, row, col)

    def _rebuild_zone_panels(self, preset: sim_avatar.AvatarPreset) -> None:
        self._clear_layout(self._sps_layout)
        if not preset.sps_zones:
            # Span the empty notice across both columns.
            self._sps_layout.addWidget(
                self._empty_label("This avatar has no SPS zones. Pick another preset."),
                0, 0, 1, self._CARDS_PER_ROW,
            )
            return
        idx = 0
        for zone in preset.sps_zones:
            if zone.kind == "Orf":
                panel = _OrificePanel(self.net, zone.name)
            elif zone.kind == "Pen":
                panel = _PenetratorPanel(self.net, zone.name)
            else:
                continue
            self._place_grid_card(self._sps_layout, idx, panel)
            idx += 1
        # Make both columns share width evenly.
        for c in range(self._CARDS_PER_ROW):
            self._sps_layout.setColumnStretch(c, 1)

    def _rebuild_bhaptics_panels(self, preset: sim_avatar.AvatarPreset) -> None:
        self._clear_layout(self._bh_layout)
        if not preset.bhaptics_positions:
            self._bh_layout.addWidget(
                self._empty_label("This avatar has no bHaptics contacts. Pick another preset."),
                0, 0, 1, self._CARDS_PER_ROW,
            )
            return
        by_position = {pos: (slot, count) for pos, slot, count in sim_avatar.BHAPTICS_DEVICES}
        idx = 0
        for pos in preset.bhaptics_positions:
            slot_count = by_position.get(pos)
            if slot_count is None:
                continue
            slot, count = slot_count
            grid = _BHapticsGrid(self.net, pos, slot, count)
            self._place_grid_card(self._bh_layout, idx, grid)
            idx += 1
        for c in range(self._CARDS_PER_ROW):
            self._bh_layout.setColumnStretch(c, 1)

    # --------------------------------------------------------- status callbacks

    def _on_status(self, msg: str) -> None:
        self._log.appendPlainText(f"[status] {msg}")

    def _on_ogp_discovered(self, port: int) -> None:
        info = self.net.listen_info()
        self._status_label.setText(
            f"Service: {info['service_name']}  ·  "
            f"OSC UDP {info['osc_listen_port']}  ·  "
            f"HTTP {info['http_listen_port']}  ·  "
            f"Connected to OscGoesPurrr on 127.0.0.1:{port}"
        )

    def _on_ogp_lost(self) -> None:
        info = self.net.listen_info()
        self._status_label.setText(
            f"Service: {info['service_name']}  ·  "
            f"OSC UDP {info['osc_listen_port']}  ·  "
            f"HTTP {info['http_listen_port']}  ·  "
            "OscGoesPurrr advertisement vanished — waiting…"
        )

    def _on_inbound_osc(self, address: str, args: tuple) -> None:
        if not args:
            arg_repr = "(none)"
        elif len(args) == 1:
            arg_repr = repr(args[0])
        else:
            arg_repr = repr(args)
        self._log.appendPlainText(f"{address}  ←  {arg_repr}")

    # ------------------------------------------------------------- shutdown

    def closeEvent(self, event) -> None:  # noqa: N802 — Qt API
        try:
            self.net.stop()
        finally:
            super().closeEvent(event)


def run() -> int:
    # On Windows, set a distinct AppUserModelID before the first window is
    # created. Without this, the taskbar treats the simulator as part of the
    # generic "Python" group (in source-tree runs) or shares a slot with the
    # main OscGoesPurrr app (when both --onefile exes are running).
    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
                _SIM_APP_USER_MODEL_ID
            )
        except Exception:
            pass

    app = QApplication.instance() or QApplication([])
    # Apply the shared OGP-style theme. Doing it on the QApplication propagates
    # to every widget the window builds afterwards.
    app.setStyleSheet(GLOBAL_QSS)
    icon_path = _sim_icon_path()
    if icon_path is not None:
        app.setWindowIcon(QIcon(icon_path))
    win = SimulatorMainWindow()
    win.show()
    return app.exec()
