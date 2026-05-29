"""PySide6 UI for the VRChat simulator.

A small window that lets you drive every avatar parameter OscGoesPurrr
cares about: SPS zone touch / penetration sliders, an automated thrust
animator, and a bHaptics contact dot grid. The UI is rebuilt each time
the avatar dropdown changes so panels always match the active preset's
zone list.
"""

from __future__ import annotations

import math
import time
from typing import Any, Dict, List, Optional, Tuple

from PySide6.QtCore import Qt, QObject, QTimer, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QFrame, QGridLayout, QGroupBox,
    QHBoxLayout, QLabel, QMainWindow, QPlainTextEdit, QPushButton,
    QScrollArea, QSizePolicy, QSlider, QTabWidget, QVBoxLayout, QWidget,
)

from . import sim_avatar
from .sim_network import VRChatSimNetwork


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

def _h_separator() -> QFrame:
    line = QFrame()
    line.setFrameShape(QFrame.Shape.HLine)
    line.setFrameShadow(QFrame.Shadow.Sunken)
    return line


def _slider_row(label: str, on_change) -> Tuple[QWidget, QSlider, QLabel]:
    """Build a labelled 0..1 float slider that calls `on_change(float)`."""
    wrapper = QWidget()
    row = QHBoxLayout(wrapper)
    row.setContentsMargins(0, 0, 0, 0)
    lab = QLabel(label)
    lab.setMinimumWidth(120)
    val_lab = QLabel("0.00")
    val_lab.setMinimumWidth(40)
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


def _close_toggle(label: str, on_change) -> QPushButton:
    btn = QPushButton(label)
    btn.setCheckable(True)
    btn.setMinimumWidth(110)
    btn.toggled.connect(lambda checked: on_change(bool(checked)))
    return btn


# ---------------------------------------------------------------- thrust anim

class _ThrustAnimator(QObject):
    """Drives PenOthersNewRoot / PenOthersNewTip in a sinusoidal stroke to
    simulate a partner thrusting into the orifice. Mirrors what OGB's depth
    detector expects: tip pinned at 1.0 (fully inside the receiver radius)
    while root oscillates between two depth points.
    """
    def __init__(self, net: VRChatSimNetwork, zone_name: str, parent: QObject = None) -> None:
        super().__init__(parent)
        self._net = net
        self._zone = zone_name
        self._timer = QTimer(self)
        self._timer.setInterval(33)  # ~30 Hz
        self._timer.timeout.connect(self._tick)
        self._t0: float = 0.0
        # Defaults tuned to feel realistic. Pen length 0.3 in normalised
        # OGB space, oscillating between depth ~0.25 and ~0.95.
        self.length: float = 0.30
        self.depth_min: float = 0.25
        self.depth_max: float = 0.95
        self.freq_hz: float = 1.4

    def start(self) -> None:
        self._t0 = time.monotonic()
        self._timer.start()

    def stop(self) -> None:
        self._timer.stop()
        # Park back at zero so the zone goes idle.
        self._net.set_param(f"OGB/Orf/{self._zone}/PenOthersNewRoot", 0.0)
        self._net.set_param(f"OGB/Orf/{self._zone}/PenOthersNewTip", 0.0)
        self._net.set_param(f"OGB/Orf/{self._zone}/PenOthersClose", False)

    @property
    def running(self) -> bool:
        return self._timer.isActive()

    def _tick(self) -> None:
        dt = time.monotonic() - self._t0
        phase = math.sin(2.0 * math.pi * self.freq_hz * dt)
        # Map [-1, 1] → [depth_min, depth_max]
        depth = self.depth_min + (self.depth_max - self.depth_min) * (0.5 + 0.5 * phase)
        # Convert depth ∈ [0, 1] into (root, tip) prox readings. Tip is
        # always 1.0 while fully inside the receiver radius.
        exposed = max(0.0, (1.0 - depth) * self.length)
        root = max(0.0, min(1.0, 1.0 - exposed))
        tip = 1.0
        prefix = f"OGB/Orf/{self._zone}"
        self._net.set_param(f"{prefix}/PenOthersNewRoot", root)
        self._net.set_param(f"{prefix}/PenOthersNewTip", tip)
        self._net.set_param(f"{prefix}/PenOthersClose", True)
        # Also drive legacy PenOthers so plugs and "Penis Only" avatars see
        # something meaningful too.
        self._net.set_param(f"{prefix}/PenOthers", depth)


# ----------------------------------------------------------------- zone panels

class _OrificePanel(QGroupBox):
    def __init__(self, net: VRChatSimNetwork, zone_name: str) -> None:
        super().__init__(f"Orifice — {zone_name}")
        self.net = net
        self.zone = zone_name
        self.prefix = f"OGB/Orf/{zone_name}"
        self._build()

    def _build(self) -> None:
        col = QVBoxLayout(self)

        # Touch — self
        row_self = QHBoxLayout()
        w, _, _ = _slider_row("Touch Self", lambda v: self.net.set_param(f"{self.prefix}/TouchSelf", v))
        row_self.addWidget(w, 1)
        row_self.addWidget(_close_toggle("Self Close", lambda v: self.net.set_param(f"{self.prefix}/TouchSelfClose", v)))
        col.addLayout(row_self)

        # Touch — others
        row_others = QHBoxLayout()
        w, _, _ = _slider_row("Touch Others", lambda v: self.net.set_param(f"{self.prefix}/TouchOthers", v))
        row_others.addWidget(w, 1)
        row_others.addWidget(_close_toggle("Others Close", lambda v: self.net.set_param(f"{self.prefix}/TouchOthersClose", v)))
        col.addLayout(row_others)

        col.addWidget(_h_separator())

        # Penetration — legacy
        col.addWidget(_slider_row("Pen Self (legacy)", lambda v: self.net.set_param(f"{self.prefix}/PenSelf", v))[0])
        row_pen_others = QHBoxLayout()
        w, _, _ = _slider_row("Pen Others (legacy)", lambda v: self.net.set_param(f"{self.prefix}/PenOthers", v))
        row_pen_others.addWidget(w, 1)
        row_pen_others.addWidget(_close_toggle("Pen Others Close", lambda v: self.net.set_param(f"{self.prefix}/PenOthersClose", v)))
        col.addLayout(row_pen_others)

        # New-pen depth (proximity-based)
        col.addWidget(_slider_row("Pen Others — NewRoot", lambda v: self.net.set_param(f"{self.prefix}/PenOthersNewRoot", v))[0])
        col.addWidget(_slider_row("Pen Others — NewTip", lambda v: self.net.set_param(f"{self.prefix}/PenOthersNewTip", v))[0])

        # Frot
        col.addWidget(_slider_row("Frot Others", lambda v: self.net.set_param(f"{self.prefix}/FrotOthers", v))[0])

        col.addWidget(_h_separator())

        # Quick action row
        actions = QHBoxLayout()
        self.animator = _ThrustAnimator(self.net, self.zone, self)
        self.thrust_btn = QPushButton("Animate Thrust")
        self.thrust_btn.setCheckable(True)
        self.thrust_btn.toggled.connect(self._toggle_thrust)
        actions.addWidget(self.thrust_btn)

        tap_btn = QPushButton("Tap (Others)")
        tap_btn.clicked.connect(self._tap_others)
        actions.addWidget(tap_btn)

        reset_btn = QPushButton("Reset")
        reset_btn.clicked.connect(self._reset)
        actions.addWidget(reset_btn)

        actions.addStretch(1)
        col.addLayout(actions)

    def _toggle_thrust(self, on: bool) -> None:
        if on:
            self.animator.start()
            self.thrust_btn.setText("Stop Thrust")
        else:
            self.animator.stop()
            self.thrust_btn.setText("Animate Thrust")

    def _tap_others(self) -> None:
        # Brief 1.0 touch pulse for half a second.
        self.net.set_param(f"{self.prefix}/TouchOthersClose", True)
        self.net.set_param(f"{self.prefix}/TouchOthers", 1.0)
        QTimer.singleShot(500, lambda: (
            self.net.set_param(f"{self.prefix}/TouchOthers", 0.0),
            self.net.set_param(f"{self.prefix}/TouchOthersClose", False),
        ))

    def _reset(self) -> None:
        # Stop animation and zero everything.
        if self.animator.running:
            self.thrust_btn.setChecked(False)
        for suffix, val in [
            ("TouchSelf", 0.0), ("TouchSelfClose", False),
            ("TouchOthers", 0.0), ("TouchOthersClose", False),
            ("PenSelf", 0.0), ("PenOthers", 0.0), ("PenOthersClose", False),
            ("PenOthersNewRoot", 0.0), ("PenOthersNewTip", 0.0),
            ("FrotOthers", 0.0),
        ]:
            self.net.set_param(f"{self.prefix}/{suffix}", val)


class _PenetratorAnimator(QObject):
    """Pen-side thrust simulation: oscillates PenOthers between two depth
    points to mimic the avatar's penis pumping into a partner. Simpler than
    the orifice animator because plugs don't use the new-pen proximity pair."""
    def __init__(self, net: VRChatSimNetwork, zone_name: str, parent: QObject = None) -> None:
        super().__init__(parent)
        self._net = net
        self._zone = zone_name
        self._timer = QTimer(self)
        self._timer.setInterval(33)
        self._timer.timeout.connect(self._tick)
        self._t0: float = 0.0
        self.depth_min: float = 0.20
        self.depth_max: float = 0.95
        self.freq_hz: float = 1.4

    def start(self) -> None:
        self._t0 = time.monotonic()
        self._timer.start()

    def stop(self) -> None:
        self._timer.stop()
        self._net.set_param(f"OGB/Pen/{self._zone}/PenOthers", 0.0)

    @property
    def running(self) -> bool:
        return self._timer.isActive()

    def _tick(self) -> None:
        dt = time.monotonic() - self._t0
        phase = math.sin(2.0 * math.pi * self.freq_hz * dt)
        depth = self.depth_min + (self.depth_max - self.depth_min) * (0.5 + 0.5 * phase)
        self._net.set_param(f"OGB/Pen/{self._zone}/PenOthers", depth)


class _PenetratorPanel(QGroupBox):
    def __init__(self, net: VRChatSimNetwork, zone_name: str) -> None:
        super().__init__(f"Penetrator — {zone_name}")
        self.net = net
        self.zone = zone_name
        self.prefix = f"OGB/Pen/{zone_name}"
        self._build()

    def _build(self) -> None:
        col = QVBoxLayout(self)
        col.addWidget(_slider_row("Touch Self", lambda v: self.net.set_param(f"{self.prefix}/TouchSelf", v))[0])
        col.addWidget(_slider_row("Touch Others", lambda v: self.net.set_param(f"{self.prefix}/TouchOthers", v))[0])
        col.addWidget(_h_separator())
        col.addWidget(_slider_row("Pen Self", lambda v: self.net.set_param(f"{self.prefix}/PenSelf", v))[0])
        col.addWidget(_slider_row("Pen Others", lambda v: self.net.set_param(f"{self.prefix}/PenOthers", v))[0])
        col.addWidget(_h_separator())
        row_frot = QHBoxLayout()
        w, _, _ = _slider_row("Frot Others", lambda v: self.net.set_param(f"{self.prefix}/FrotOthers", v))
        row_frot.addWidget(w, 1)
        row_frot.addWidget(_close_toggle("Frot Others Close", lambda v: self.net.set_param(f"{self.prefix}/FrotOthersClose", v)))
        col.addLayout(row_frot)

        actions = QHBoxLayout()
        self.animator = _PenetratorAnimator(self.net, self.zone, self)
        self.thrust_btn = QPushButton("Animate Thrust")
        self.thrust_btn.setCheckable(True)
        self.thrust_btn.toggled.connect(self._toggle_thrust)
        actions.addWidget(self.thrust_btn)

        reset_btn = QPushButton("Reset")
        reset_btn.clicked.connect(self._reset)
        actions.addWidget(reset_btn)
        actions.addStretch(1)
        col.addLayout(actions)

    def _toggle_thrust(self, on: bool) -> None:
        if on:
            self.animator.start()
            self.thrust_btn.setText("Stop Thrust")
        else:
            self.animator.stop()
            self.thrust_btn.setText("Animate Thrust")

    def _reset(self) -> None:
        if self.animator.running:
            self.thrust_btn.setChecked(False)
        for suffix, val in [
            ("TouchSelf", 0.0), ("TouchOthers", 0.0),
            ("PenSelf", 0.0), ("PenOthers", 0.0),
            ("FrotOthers", 0.0), ("FrotOthersClose", False),
        ]:
            self.net.set_param(f"{self.prefix}/{suffix}", val)


# ----------------------------------------------------------- bHaptics grid

class _BHapticsGrid(QGroupBox):
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
        title = position.replace("Vest", "Vest ").replace("Forearm", "Forearm ").replace("Hand", "Hand ").replace("Foot", "Foot ")
        super().__init__(f"bHaptics — {title.strip()}")
        self.net = net
        self.position = position
        self.slot = slot
        self.count = count
        self._buttons: List[QPushButton] = []
        self._build()

    def _build(self) -> None:
        outer = QVBoxLayout(self)
        grid = QGridLayout()
        cols, rows = self._LAYOUTS.get(self.position, (self.count, 1))
        for n in range(1, self.count + 1):
            idx = n - 1
            r, c = divmod(idx, cols)
            btn = QPushButton(str(n))
            btn.setCheckable(True)
            btn.setFixedSize(38, 38)
            btn.toggled.connect(self._dot_handler(n))
            self._buttons.append(btn)
            grid.addWidget(btn, r, c)
        outer.addLayout(grid)

        row = QHBoxLayout()
        all_on = QPushButton("All On")
        all_off = QPushButton("All Off")
        pulse = QPushButton("Pulse")
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
        for i, btn in enumerate(self._buttons, start=1):
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
        self.setCentralWidget(central)
        root = QVBoxLayout(central)

        # Top bar — avatar selector + status
        bar = QHBoxLayout()
        title = QLabel("Avatar:")
        title.setFont(QFont("", 10, QFont.Weight.Bold))
        bar.addWidget(title)
        self._avatar_combo = QComboBox()
        for p in sim_avatar.AVATAR_PRESETS:
            self._avatar_combo.addItem(p.display_name, userData=p.avatar_id)
        self._avatar_combo.currentIndexChanged.connect(self._apply_avatar_index)
        bar.addWidget(self._avatar_combo, 1)
        self._reblast_btn = QPushButton("Resend All Params")
        self._reblast_btn.clicked.connect(self.net.resend_all)
        bar.addWidget(self._reblast_btn)
        root.addLayout(bar)

        self._status_label = QLabel("Starting…")
        self._status_label.setStyleSheet("color: #9A9AB8;")
        root.addWidget(self._status_label)

        # Tabs
        self._tabs = QTabWidget()
        root.addWidget(self._tabs, 1)

        # SPS tab — scrollable
        self._sps_scroll = QScrollArea()
        self._sps_scroll.setWidgetResizable(True)
        self._sps_host = QWidget()
        self._sps_layout = QVBoxLayout(self._sps_host)
        self._sps_layout.addStretch(1)
        self._sps_scroll.setWidget(self._sps_host)
        self._tabs.addTab(self._sps_scroll, "SPS Zones")

        # bHaptics tab — scrollable
        self._bh_scroll = QScrollArea()
        self._bh_scroll.setWidgetResizable(True)
        self._bh_host = QWidget()
        self._bh_layout = QVBoxLayout(self._bh_host)
        self._bh_layout.addStretch(1)
        self._bh_scroll.setWidget(self._bh_host)
        self._tabs.addTab(self._bh_scroll, "bHaptics Contacts")

        # Inbound OSC log
        log_host = QWidget()
        log_layout = QVBoxLayout(log_host)
        self._log = QPlainTextEdit()
        self._log.setReadOnly(True)
        self._log.setMaximumBlockCount(2000)
        self._log.setFont(QFont("Consolas", 9))
        log_layout.addWidget(self._log, 1)
        log_actions = QHBoxLayout()
        clear_btn = QPushButton("Clear")
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

    def _clear_layout(self, layout) -> None:
        while layout.count() > 0:
            item = layout.takeAt(0)
            w = item.widget()
            if w is not None:
                # Hide before detaching: a still-visible child reparented to
                # None briefly realises as a top-level window (a flash).
                w.hide()
                w.setParent(None)
                w.deleteLater()
            else:
                child = item.layout()
                if child is not None:
                    self._clear_layout(child)

    def _rebuild_zone_panels(self, preset: sim_avatar.AvatarPreset) -> None:
        self._clear_layout(self._sps_layout)
        if not preset.sps_zones:
            empty = QLabel("This avatar has no SPS zones. Pick another preset.")
            empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
            empty.setStyleSheet("color: #9A9AB8; padding: 32px;")
            self._sps_layout.addWidget(empty)
            self._sps_layout.addStretch(1)
            return
        for zone in preset.sps_zones:
            if zone.kind == "Orf":
                panel = _OrificePanel(self.net, zone.name)
            elif zone.kind == "Pen":
                panel = _PenetratorPanel(self.net, zone.name)
            else:
                continue
            panel.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            self._sps_layout.addWidget(panel)
        self._sps_layout.addStretch(1)

    def _rebuild_bhaptics_panels(self, preset: sim_avatar.AvatarPreset) -> None:
        self._clear_layout(self._bh_layout)
        if not preset.bhaptics_positions:
            empty = QLabel("This avatar has no bHaptics contacts. Pick another preset.")
            empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
            empty.setStyleSheet("color: #9A9AB8; padding: 32px;")
            self._bh_layout.addWidget(empty)
            self._bh_layout.addStretch(1)
            return
        by_position = {pos: (slot, count) for pos, slot, count in sim_avatar.BHAPTICS_DEVICES}
        # Two columns per row to keep wide screens readable.
        row_layout: Optional[QHBoxLayout] = None
        per_row = 2
        for i, pos in enumerate(preset.bhaptics_positions):
            slot_count = by_position.get(pos)
            if slot_count is None:
                continue
            slot, count = slot_count
            if i % per_row == 0:
                row_layout = QHBoxLayout()
                self._bh_layout.addLayout(row_layout)
            grid = _BHapticsGrid(self.net, pos, slot, count)
            grid.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            row_layout.addWidget(grid)
        # Fill remainder of last row with stretch so cards don't get pulled wide.
        if row_layout is not None and (len(preset.bhaptics_positions) % per_row) != 0:
            row_layout.addStretch(1)
        self._bh_layout.addStretch(1)

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
    app = QApplication.instance() or QApplication([])
    win = SimulatorMainWindow()
    win.show()
    return app.exec()
