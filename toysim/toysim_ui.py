"""PySide6 UI for the standalone Intiface toy simulator.

A small window that registers one or more fully virtual Lovense toys with
Intiface Central's Device Websocket Server. Each toy shows up in Intiface's
device list and OscGoesPurrr drives it through its normal Buttplug path — so
you can exercise OGP's haptic output with no hardware powered on.

Per toy the window shows: connection state, a live 0..1 bar per motor (driven
by the commands OGP sends), a battery slider (the value answered to Intiface's
``Battery;`` poll), and a raw command/response log.

Threading mirrors `sim/sim_ui.py`: the websocket transport calls plain Python
callbacks from its worker thread; a per-toy `_ToyBridge` wraps Qt signals so
the slots that touch widgets always run on the GUI thread.
"""

from __future__ import annotations

from typing import List, Optional, Tuple

from PySide6.QtCore import Qt, QObject, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QApplication, QComboBox, QFrame, QHBoxLayout, QLabel, QLineEdit,
    QMainWindow, QPlainTextEdit, QProgressBar, QPushButton, QSlider,
    QTabWidget, QVBoxLayout, QWidget,
)

from .lovense_device import DEFAULT_WSDM_URL, LovenseToy
from .lovense_protocol import (
    DEFAULT_WS_IDENTIFIER, MODELS, LovenseModel, LovenseProtocol,
    random_address,
)


# One-time Intiface wiring the user must do before any toy will connect. Shown
# as a banner so the setup step travels with the tool instead of a README.
_SETUP_HINT = (
    "One-time Intiface setup:   "
    "1) Settings → enable “Device Websocket Server” (default port 54817).   "
    "2) Register this identifier in Intiface's user device config file "
    "buttplug-user-device-config-v4.json — under user_configs → protocols → "
    "lovense → communication add  {\"websocket\": {\"name\": \"OGPSim\"}}  "
    "(the name must match the Identifier field below, exactly), then restart "
    "the Intiface server.   3) Connect OscGoesPurrr to Intiface, then “Add Toy”."
)


def _h_separator() -> QFrame:
    line = QFrame()
    line.setFrameShape(QFrame.Shape.HLine)
    line.setFrameShadow(QFrame.Shadow.Sunken)
    return line


# ---------------------------------------------------------------- thread bridge

class _ToyBridge(QObject):
    """Marshals one toy's worker-thread callbacks onto the Qt main thread."""
    levels = Signal(list)          # List[Tuple[int, float]]
    log = Signal(str)
    state = Signal(bool, object)   # (connected, error_or_None)


# ------------------------------------------------------------------- toy tab

class _ToyTab(QWidget):
    """One virtual toy: its protocol, its websocket transport, and the widgets
    that display what OGP is doing to it."""

    def __init__(self, model: LovenseModel, url: str, identifier: str) -> None:
        super().__init__()
        self.model = model
        self.proto = LovenseProtocol(model, random_address(), ws_identifier=identifier)
        self.bridge = _ToyBridge()
        self.toy = LovenseToy(
            self.proto,
            url=url,
            on_levels=lambda u: self.bridge.levels.emit(u),
            on_log=lambda m: self.bridge.log.emit(m),
            on_state=lambda c, e: self.bridge.state.emit(c, e),
        )
        self._bars: List[QProgressBar] = []
        self._build()

        self.bridge.levels.connect(self._on_levels)
        self.bridge.log.connect(self._on_log)
        self.bridge.state.connect(self._on_state)
        self.toy.start()

    # ----------------------------------------------------------- construction
    def _build(self) -> None:
        col = QVBoxLayout(self)

        header = QLabel(
            f"{self.model.name}   ·   DeviceType “{self.model.device_type}”"
            f"   ·   addr {self.proto.address}"
        )
        header.setFont(QFont("", 10, QFont.Weight.Bold))
        col.addWidget(header)

        self._state_label = QLabel("Connecting…")
        self._state_label.setStyleSheet("color: #9A9AB8;")
        col.addWidget(self._state_label)

        col.addWidget(_h_separator())

        # One read-only level bar per motor, driven by decoded commands.
        for feat in self.model.features:
            row = QHBoxLayout()
            lab = QLabel(f"{feat.label}  ({feat.kind})")
            lab.setMinimumWidth(170)
            bar = QProgressBar()
            bar.setRange(0, 1000)
            bar.setValue(0)
            bar.setTextVisible(True)
            bar.setFormat("%p%")
            row.addWidget(lab)
            row.addWidget(bar, 1)
            col.addLayout(row)
            self._bars.append(bar)

        col.addWidget(_h_separator())

        # Battery — the value answered to Intiface's periodic Battery; poll.
        batt_row = QHBoxLayout()
        batt_lab = QLabel("Battery")
        batt_lab.setMinimumWidth(170)
        self._batt = QSlider(Qt.Orientation.Horizontal)
        self._batt.setRange(0, 100)
        self._batt.setValue(self.proto.battery_pct)
        self._batt_val = QLabel(f"{self.proto.battery_pct}%")
        self._batt_val.setMinimumWidth(40)
        self._batt_val.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self._batt.valueChanged.connect(self._on_battery)
        batt_row.addWidget(batt_lab)
        batt_row.addWidget(self._batt, 1)
        batt_row.addWidget(self._batt_val)
        col.addLayout(batt_row)

        col.addWidget(_h_separator())

        # Raw command/response log.
        self._log = QPlainTextEdit()
        self._log.setReadOnly(True)
        self._log.setMaximumBlockCount(2000)
        self._log.setFont(QFont("Consolas", 9))
        col.addWidget(self._log, 1)

    # --------------------------------------------------------------- slots
    def _on_battery(self, v: int) -> None:
        self.toy.set_battery(v)
        self._batt_val.setText(f"{v}%")

    def _on_levels(self, updates: List[Tuple[int, float]]) -> None:
        for idx, level in updates:
            if 0 <= idx < len(self._bars):
                self._bars[idx].setValue(int(round(level * 1000)))

    def _on_log(self, msg: str) -> None:
        self._log.appendPlainText(msg)

    def _on_state(self, connected: bool, err: object) -> None:
        if connected:
            self._state_label.setText("●  Connected to Intiface WSDM")
            self._state_label.setStyleSheet("color: #3FB950;")
        else:
            tail = f"  —  {err}" if err else ""
            self._state_label.setText(f"○  Disconnected{tail}")
            self._state_label.setStyleSheet("color: #C9504A;")
            for bar in self._bars:
                bar.setValue(0)

    # ------------------------------------------------------------- shutdown
    def shutdown(self) -> None:
        self.toy.stop()


# ----------------------------------------------------------- main window

class ToySimMainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Intiface Toy Simulator — OscGoesPurrr test rig")
        self.resize(760, 640)
        self._build_ui()

    def _build_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)

        hint = QLabel(_SETUP_HINT)
        hint.setWordWrap(True)
        hint.setStyleSheet(
            "background: #2D2A3E; color: #C9C7E0; padding: 8px; border-radius: 6px;"
        )
        root.addWidget(hint)

        # Model + connection config row.
        cfg = QHBoxLayout()
        cfg.addWidget(QLabel("Model:"))
        self._model_combo = QComboBox()
        for m in MODELS:
            n = len(m.features)
            self._model_combo.addItem(
                f"{m.name}  ({n} motor{'s' if n != 1 else ''})", userData=m
            )
        cfg.addWidget(self._model_combo, 1)
        cfg.addWidget(QLabel("Identifier:"))
        self._id_edit = QLineEdit(DEFAULT_WS_IDENTIFIER)
        self._id_edit.setMaximumWidth(140)
        cfg.addWidget(self._id_edit)
        root.addLayout(cfg)

        url_row = QHBoxLayout()
        url_row.addWidget(QLabel("WSDM URL:"))
        self._url_edit = QLineEdit(DEFAULT_WSDM_URL)
        url_row.addWidget(self._url_edit, 1)
        self._add_btn = QPushButton("Add Toy")
        self._add_btn.clicked.connect(self._add_toy)
        self._remove_btn = QPushButton("Remove Current Toy")
        self._remove_btn.clicked.connect(self._remove_current)
        url_row.addWidget(self._add_btn)
        url_row.addWidget(self._remove_btn)
        root.addLayout(url_row)

        self._tabs = QTabWidget()
        root.addWidget(self._tabs, 1)

        self._empty = QLabel("No virtual toys yet — pick a model and click “Add Toy”.")
        self._empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty.setStyleSheet("color: #9A9AB8; padding: 40px;")
        root.addWidget(self._empty)
        self._sync_empty()

    # ---------------------------------------------------------------- actions
    def _add_toy(self) -> None:
        model: LovenseModel = self._model_combo.currentData()
        if model is None:
            return
        url = self._url_edit.text().strip() or DEFAULT_WSDM_URL
        identifier = self._id_edit.text().strip() or DEFAULT_WS_IDENTIFIER
        tab = _ToyTab(model, url, identifier)
        idx = self._tabs.addTab(tab, f"{model.name} · {tab.proto.address[:4]}")
        self._tabs.setCurrentIndex(idx)
        self._sync_empty()

    def _remove_current(self) -> None:
        idx = self._tabs.currentIndex()
        if idx < 0:
            return
        tab = self._tabs.widget(idx)
        self._tabs.removeTab(idx)
        if isinstance(tab, _ToyTab):
            tab.shutdown()
            tab.deleteLater()
        self._sync_empty()

    def _sync_empty(self) -> None:
        has_toys = self._tabs.count() > 0
        self._tabs.setVisible(has_toys)
        self._empty.setVisible(not has_toys)
        self._remove_btn.setEnabled(has_toys)

    # ------------------------------------------------------------- shutdown
    def closeEvent(self, event) -> None:  # noqa: N802 — Qt API
        try:
            for i in range(self._tabs.count()):
                w = self._tabs.widget(i)
                if isinstance(w, _ToyTab):
                    w.shutdown()
        finally:
            super().closeEvent(event)


def run() -> int:
    app = QApplication.instance() or QApplication([])
    win = ToySimMainWindow()
    win.show()
    return app.exec()
