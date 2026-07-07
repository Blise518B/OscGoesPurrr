"""PiShock view: connection (serial/cloud), hard safety caps, and per-zone
discrete-event routing rules.

Mixin for ui_components.OscGoesPurrrUI. Calls only controller facade methods
(Law of Demeter). A shock device, so the view leads with the safety caps and
keeps auto-connect opt-in."""

from typing import Any, Dict, List

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QComboBox, QCheckBox, QDoubleSpinBox, QFrame, QLabel, QLineEdit,
    QPushButton, QScrollArea, QSpinBox, QVBoxLayout, QWidget,
)

from constants import BTN_HEIGHT_SMALL
from ui.fold_strip import FoldCard, FoldStrip
from ui.layout_helpers import vbox as _vbox, hbox as _hbox
from ui.views._backend_common import (
    on_zone_type_changed, populate_zone_combo, zone_signature,
)
from ui.widgets import (
    ToggleSwitch, Card as _Card, install_rainbow_scrollbars as _install_rainbow_scrollbars,
)

_OPS = ("shock", "vibrate", "beep")
_FILTERS = ("TouchSelf", "TouchOthers", "PenSelf", "PenOthers")


class PiShockMixin:

    _is_updating_pishock = False
    _pishock_zone_rows: List[Dict[str, Any]] = []

    def _build_pishock_view(self, parent_layout: QVBoxLayout):
        title = QLabel("PiShock")
        title.setObjectName("viewTitle")
        title.setAlignment(Qt.AlignHCenter)
        parent_layout.addWidget(title)

        parent_layout.addWidget(self._muted_label(
            "Fires PiShock shock / vibrate / beep events from avatar contacts.\n"
            "⚠ This drives a device that can shock you. Set conservative caps, "
            "test with vibrate first, and keep Auto Connect off until you trust "
            "your config. Every fire is hard-capped in the engine — settings can "
            "only lower the limits, never raise them."
        ))

        # ---- Status / connect ----
        status_card = _Card()
        slay = _vbox(14, 8)
        status_card.setLayout(slay)
        self.pishock_status_label = QLabel("PiShock: Unknown")
        f = self.pishock_status_label.font(); f.setBold(True); f.setPointSize(12)
        self.pishock_status_label.setFont(f)
        slay.addWidget(self.pishock_status_label)

        row = _hbox(0, 8)
        self.pishock_auto_connect_check = ToggleSwitch("Auto Connect (PiShock)")
        self.pishock_auto_connect_check.toggled.connect(self._on_pishock_auto_connect)
        row.addWidget(self.pishock_auto_connect_check)
        self.pishock_connect_btn = QPushButton("Connect Now")
        self.pishock_connect_btn.setMinimumHeight(BTN_HEIGHT_SMALL)
        self.pishock_connect_btn.clicked.connect(self._on_pishock_connect)
        row.addWidget(self.pishock_connect_btn)
        row.addStretch(1)
        for op in _OPS:
            tb = QPushButton(f"Test {op}")
            tb.setMinimumHeight(BTN_HEIGHT_SMALL)
            tb.clicked.connect(lambda _=False, o=op: self._on_pishock_test(o))
            row.addWidget(tb)
        slay.addLayout(row)
        parent_layout.addWidget(status_card)

        # ---- Transport ----
        t_card = _Card()
        tlay = _vbox(14, 6)
        t_card.setLayout(tlay)
        t_hdr = _hbox(0, 6)
        th = QLabel("Transport"); th.setObjectName("sectionTitle")
        t_hdr.addWidget(th)
        t_hdr.addWidget(self._make_help_badge(
            "Transport",
            "How fire commands reach the shocker. <b>serial</b>: a PiShock "
            "hub plugged into this PC over USB — enter its COM port and the "
            "shocker's ID (lowest latency, works offline). <b>cloud</b>: the "
            "PiShock web API — needs your username, API key, and the "
            "shocker's share code."
        ))
        t_hdr.addStretch(1)
        tlay.addLayout(t_hdr)
        mode_row = _hbox(0, 8)
        mode_row.addWidget(QLabel("Mode"))
        self.pishock_mode_combo = QComboBox()
        self.pishock_mode_combo.addItems(["serial", "cloud"])
        self.pishock_mode_combo.currentTextChanged.connect(self._on_pishock_mode)
        mode_row.addWidget(self.pishock_mode_combo)
        mode_row.addStretch(1)
        tlay.addLayout(mode_row)

        # Serial fields
        self.pishock_serial_panel = QWidget()
        ser = _hbox(0, 8)
        self.pishock_serial_panel.setLayout(ser)
        ser.addWidget(QLabel("COM port"))
        self.pishock_serial_port = QLineEdit()
        self.pishock_serial_port.setFixedWidth(110)
        ser.addWidget(self.pishock_serial_port)
        ser.addWidget(QLabel("Shocker ID"))
        self.pishock_shocker_id = QSpinBox()
        self.pishock_shocker_id.setRange(0, 999999)
        ser.addWidget(self.pishock_shocker_id)
        self.pishock_serial_apply_btn = QPushButton("Apply")
        self.pishock_serial_apply_btn.setMinimumHeight(BTN_HEIGHT_SMALL)
        self.pishock_serial_apply_btn.clicked.connect(self._on_pishock_serial_apply)
        ser.addWidget(self.pishock_serial_apply_btn)
        ser.addStretch(1)
        tlay.addWidget(self.pishock_serial_panel)

        # Cloud fields
        self.pishock_cloud_panel = QWidget()
        cl = _vbox(0, 6)
        self.pishock_cloud_panel.setLayout(cl)
        cl_row1 = _hbox(0, 8)
        cl_row1.addWidget(QLabel("Username"))
        self.pishock_username = QLineEdit(); self.pishock_username.setFixedWidth(140)
        cl_row1.addWidget(self.pishock_username)
        cl_row1.addWidget(QLabel("API Key"))
        self.pishock_apikey = QLineEdit(); self.pishock_apikey.setEchoMode(QLineEdit.Password)
        self.pishock_apikey.setFixedWidth(220)
        cl_row1.addWidget(self.pishock_apikey)
        clear_key_btn = QPushButton("Clear key")
        clear_key_btn.setMinimumHeight(BTN_HEIGHT_SMALL)
        clear_key_btn.setToolTip("Forget the stored API key.")
        clear_key_btn.clicked.connect(self._on_pishock_clear_apikey)
        cl_row1.addWidget(clear_key_btn)
        cl_row1.addStretch(1)
        cl.addLayout(cl_row1)
        cl_row2 = _hbox(0, 8)
        cl_row2.addWidget(QLabel("Share Code"))
        self.pishock_code = QLineEdit(); self.pishock_code.setFixedWidth(140)
        cl_row2.addWidget(self.pishock_code)
        cl_row2.addWidget(QLabel("Name"))
        self.pishock_name = QLineEdit(); self.pishock_name.setFixedWidth(160)
        cl_row2.addWidget(self.pishock_name)
        self.pishock_cloud_apply_btn = QPushButton("Apply")
        self.pishock_cloud_apply_btn.setMinimumHeight(BTN_HEIGHT_SMALL)
        self.pishock_cloud_apply_btn.clicked.connect(self._on_pishock_cloud_apply)
        cl_row2.addWidget(self.pishock_cloud_apply_btn)
        cl_row2.addStretch(1)
        cl.addLayout(cl_row2)
        tlay.addWidget(self.pishock_cloud_panel)
        parent_layout.addWidget(t_card)

        # ---- Safety caps ----
        cap_card = _Card()
        clay = _vbox(14, 6)
        cap_card.setLayout(clay)
        c_hdr = _hbox(0, 6)
        ch = QLabel("Safety caps"); ch.setObjectName("sectionTitle")
        c_hdr.addWidget(ch)
        c_hdr.addWidget(self._make_help_badge(
            "Safety caps",
            "Hard ceilings enforced inside the engine on EVERY fire, "
            "regardless of what a zone asks for. Settings here can only "
            "lower the limits, never raise them past the absolute caps "
            "shown below. Per-zone configs add their own thresholds and "
            "cooldowns on top — defense in depth."
        ))
        c_hdr.addStretch(1)
        clay.addLayout(c_hdr)
        self.pishock_caps_hint = self._muted_label("")
        clay.addWidget(self.pishock_caps_hint)
        cap_row = _hbox(0, 8)
        cap_row.addWidget(QLabel("Max intensity"))
        self.pishock_max_int = QSpinBox(); self.pishock_max_int.setRange(1, 100)
        self.pishock_max_int.valueChanged.connect(self._on_pishock_caps)
        cap_row.addWidget(self.pishock_max_int)
        cap_row.addWidget(QLabel("Max duration (ms)"))
        self.pishock_max_dur = QSpinBox(); self.pishock_max_dur.setRange(1, 15000)
        self.pishock_max_dur.setSingleStep(100)
        self.pishock_max_dur.valueChanged.connect(self._on_pishock_caps)
        cap_row.addWidget(self.pishock_max_dur)
        cap_row.addWidget(QLabel("Min interval (s)"))
        self.pishock_min_int = QDoubleSpinBox(); self.pishock_min_int.setRange(0.3, 60.0)
        self.pishock_min_int.setSingleStep(0.5); self.pishock_min_int.setDecimals(1)
        self.pishock_min_int.valueChanged.connect(self._on_pishock_caps)
        cap_row.addWidget(self.pishock_min_int)
        cap_row.addStretch(1)
        clay.addLayout(cap_row)
        rate_row = _hbox(0, 8)
        rate_row.addWidget(QLabel("Global rate: max"))
        self.pishock_rate_max = QSpinBox(); self.pishock_rate_max.setRange(1, 100)
        self.pishock_rate_max.valueChanged.connect(self._on_pishock_rate)
        rate_row.addWidget(self.pishock_rate_max)
        rate_row.addWidget(QLabel("events per"))
        self.pishock_rate_window = QDoubleSpinBox(); self.pishock_rate_window.setRange(0.1, 600.0)
        self.pishock_rate_window.setDecimals(1)
        self.pishock_rate_window.valueChanged.connect(self._on_pishock_rate)
        rate_row.addWidget(self.pishock_rate_window)
        rate_row.addWidget(QLabel("seconds"))
        rate_row.addWidget(self._make_help_badge(
            "Global rate backstop",
            "Sliding-window cap across ALL zones combined, so several "
            "zones firing at once can't gang up into a burst. Once the "
            "window is full, further fires are dropped until it slides "
            "clear — independent of each zone's own cooldown."
        ))
        rate_row.addStretch(1)
        clay.addLayout(rate_row)
        parent_layout.addWidget(cap_card)

        # ---- Zones ----
        z_card = _Card(dark_bg=True)
        zlay = _vbox(10, 6)
        z_card.setLayout(zlay)
        zhdr = _hbox(0, 8)
        zh = QLabel("Routing zones"); zh.setObjectName("sectionTitle")
        zhdr.addWidget(zh)
        zhdr.addStretch(1)
        add_btn = QPushButton("+ Add zone")
        add_btn.setMinimumHeight(BTN_HEIGHT_SMALL)
        add_btn.clicked.connect(self._on_pishock_zone_add)
        zhdr.addWidget(add_btn)
        zlay.addLayout(zhdr)
        scroll = QScrollArea(); scroll.setWidgetResizable(True)
        _install_rainbow_scrollbars(scroll)
        inner = QWidget()
        self.pishock_zone_layout = _vbox(8, 8)
        inner.setLayout(self.pishock_zone_layout)
        scroll.setWidget(inner)
        zlay.addWidget(scroll, 1)
        parent_layout.addWidget(z_card, 1)

        self._refresh_pishock_view()
        self._pishock_timer = QTimer(self.window)
        self._pishock_timer.setInterval(1500)
        self._pishock_timer.timeout.connect(self._refresh_pishock_status_only)
        self._pishock_timer.start()

        # Fast tick driving the zone cards' activity rings + arrows
        # (same cadence as the bHaptics debug grids). Short-circuits
        # when the view is hidden so it costs nothing in other tabs.
        self._pishock_level_timer = QTimer(self.window)
        self._pishock_level_timer.setInterval(100)
        self._pishock_level_timer.timeout.connect(self._refresh_pishock_levels)
        self._pishock_level_timer.start()

    # ---- refresh ----
    def _refresh_pishock_view(self):
        if not hasattr(self, "pishock_zone_layout"):
            return
        self._is_updating_pishock = True
        try:
            status = self.controller.get_pishock_status()
            self._apply_pishock_status(status, full=True)
            self._rebuild_pishock_zones(status.get("zones", []))
        finally:
            self._is_updating_pishock = False

    def _refresh_pishock_status_only(self):
        view = self.views.get("PiShock")
        if view is not None and not view.isVisible():
            return
        try:
            status = self.controller.get_pishock_status()
        except Exception:
            return
        self._is_updating_pishock = True
        try:
            self._apply_pishock_status(status, full=False)
        finally:
            self._is_updating_pishock = False
        # Fold newly detected zones/sources into the combos when the set
        # changes while the page is open (avatar loaded mid-visit).
        sig = zone_signature(self.controller)
        if sig != getattr(self, "_pishock_zone_sig", None):
            self._pishock_zone_sig = sig
            self._repopulate_pishock_zone_combos()

    def _apply_pishock_status(self, status: dict, full: bool):
        """`full=False` is the periodic tick: it may only touch the status
        label and the auto-connect toggle. The connection/config fields are
        Apply-gated — rewriting them from the store on a timer used to wipe
        whatever the user was typing (e.g. 'COM3' reset mid-keystroke)."""
        if not status.get("available"):
            self.pishock_status_label.setText(
                f"PiShock: {status.get('status_label','')} library missing")
            self.pishock_status_label.setProperty("role", "alert")
        elif status.get("connected"):
            self.pishock_status_label.setText(f"PiShock: connected ({status.get('status_label')})")
            self.pishock_status_label.setProperty("role", None)
        else:
            err = status.get("last_error") or "not connected"
            self.pishock_status_label.setText(f"PiShock: disconnected — {err}")
            self.pishock_status_label.setProperty("role", "alert")
        self.pishock_status_label.style().unpolish(self.pishock_status_label)
        self.pishock_status_label.style().polish(self.pishock_status_label)

        self.pishock_auto_connect_check.setChecked(bool(status.get("auto_connect")))
        if not full:
            return
        mode = status.get("mode", "serial")
        if self.pishock_mode_combo.currentText() != mode:
            self.pishock_mode_combo.setCurrentText(mode)
        self.pishock_serial_panel.setVisible(mode == "serial")
        self.pishock_cloud_panel.setVisible(mode == "cloud")

        if self.pishock_serial_port.text() != status.get("serial_port", ""):
            self.pishock_serial_port.setText(status.get("serial_port", ""))
        self.pishock_shocker_id.setValue(int(status.get("shocker_id", 0) or 0))
        if self.pishock_username.text() != status.get("username", ""):
            self.pishock_username.setText(status.get("username", ""))
        if self.pishock_code.text() != status.get("code", ""):
            self.pishock_code.setText(status.get("code", ""))
        if self.pishock_name.text() != status.get("name", "OscGoesPurrr"):
            self.pishock_name.setText(status.get("name", "OscGoesPurrr"))
        # The API key itself is never round-tripped into the UI; show
        # whether one is stored so an empty field reads as "kept", not
        # "missing" (Apply preserves the stored key when left blank).
        if status.get("has_apikey"):
            self.pishock_apikey.setPlaceholderText("•••••• (saved — blank keeps it)")
        else:
            self.pishock_apikey.setPlaceholderText("paste your PiShock API key")

        caps = status.get("caps", {})
        absolute = status.get("absolute", {})
        self.pishock_max_int.setValue(int(caps.get("max_intensity", 30)))
        self.pishock_max_dur.setValue(int(caps.get("max_duration_ms", 1000)))
        self.pishock_min_int.setValue(float(caps.get("min_interval_s", 1.0)))
        self.pishock_caps_hint.setText(
            f"Hard ceilings: intensity ≤ {absolute.get('max_intensity', 100)}, "
            f"duration ≤ {absolute.get('max_duration_ms', 15000)} ms, "
            f"interval ≥ {absolute.get('min_interval_s', 0.3)} s."
        )
        rate = status.get("global_rate", {})
        self.pishock_rate_max.setValue(int(rate.get("max_events", 6)))
        self.pishock_rate_window.setValue(float(rate.get("window_s", 10.0)))

    # ---- handlers ----
    def _on_pishock_auto_connect(self, checked: bool):
        if self._is_updating_pishock:
            return
        self.controller.set_pishock_auto_connect(bool(checked))

    def _on_pishock_connect(self):
        # Serial open / cloud validation can block for seconds — run it off
        # the Qt thread (which also hosts the Buttplug routing tick). The
        # transport controls are locked too so a mode flip can't swap the
        # provider under the in-flight open.
        self.run_ui_task(
            self.controller.pishock_connect_now,
            self._on_pishock_connect_done,
            buttons=[self.pishock_connect_btn, self.pishock_mode_combo,
                     self.pishock_serial_apply_btn, self.pishock_cloud_apply_btn],
        )

    def _on_pishock_connect_done(self, result):
        if isinstance(result, Exception):
            self.log_message(f"PiShock: connect failed — {result}")
        else:
            self.log_message("PiShock: connected" if result
                             else "PiShock: connect failed")
        # Status-only: this fires seconds after the click, when the user may
        # be typing again — a full refresh here would clobber their edits
        # (the exact bug the full/status-only split exists to prevent).
        self._refresh_pishock_status_only()

    def _on_pishock_test(self, op: str):
        self.controller.pishock_test_fire(op)

    def _on_pishock_mode(self, mode: str):
        if self._is_updating_pishock:
            return
        self.controller.set_pishock_mode(mode)
        self._refresh_pishock_view()

    def _on_pishock_serial_apply(self):
        self.controller.set_pishock_serial(
            self.pishock_serial_port.text().strip(), int(self.pishock_shocker_id.value()))
        self.log_message("PiShock: serial config applied")

    def _on_pishock_cloud_apply(self):
        # The API key is never shown back into the field, so after a restart
        # it is legitimately empty — an empty submit means "keep the stored
        # key", not "erase it" (use Clear key to erase).
        apikey = self.pishock_apikey.text().strip() or None
        self.controller.set_pishock_cloud(
            self.pishock_username.text().strip(), apikey,
            self.pishock_code.text().strip(), self.pishock_name.text().strip())
        self.pishock_apikey.clear()
        self.log_message("PiShock: cloud config applied"
                         + ("" if apikey else " (stored API key kept)"))
        self._refresh_pishock_view()

    def _on_pishock_clear_apikey(self):
        self.pishock_apikey.clear()
        self.controller.set_pishock_cloud(
            self.pishock_username.text().strip(), "",
            self.pishock_code.text().strip(), self.pishock_name.text().strip())
        self.log_message("PiShock: stored API key cleared")
        self._refresh_pishock_view()

    def _on_pishock_caps(self, *_):
        if self._is_updating_pishock:
            return
        self.controller.set_pishock_caps(
            int(self.pishock_max_int.value()), int(self.pishock_max_dur.value()),
            float(self.pishock_min_int.value()))

    def _on_pishock_rate(self, *_):
        if self._is_updating_pishock:
            return
        self.controller.set_pishock_global_rate(
            int(self.pishock_rate_max.value()), float(self.pishock_rate_window.value()))

    # ---- zones ----
    def _rebuild_pishock_zones(self, zones: list):
        self._pishock_zone_rows = []
        while self.pishock_zone_layout.count():
            item = self.pishock_zone_layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        if not zones:
            self.pishock_zone_layout.addWidget(self._muted_label(
                "No zones yet. Click '+ Add zone' to map an avatar contact to a "
                "shock / vibrate / beep."))
        else:
            for idx, zone in enumerate(zones):
                self.pishock_zone_layout.addWidget(
                    self._build_pishock_zone_card(idx, zone), 0, Qt.AlignLeft)
        self.pishock_zone_layout.addStretch(1)

    def _build_pishock_zone_card(self, idx: int, zone: Dict[str, Any]) -> QFrame:
        """One zone as a fold strip — Source → Trigger → Output — in the
        Device Routing chain's design language: collapsible folds joined
        by arrows, with activity rings charged by the live zone strength
        (see ui/fold_strip.py)."""
        card = _Card(); card.setMaximumWidth(860)
        lay = _vbox(12, 8); card.setLayout(lay)

        row1 = _hbox(0, 8)
        row1.addWidget(QLabel("Name"))
        name = QLineEdit(str(zone.get("name", ""))); name.setMinimumWidth(150)
        name.editingFinished.connect(lambda i=idx: self._push_pishock_zone(i))
        row1.addWidget(name)
        enabled = ToggleSwitch("Enabled"); enabled.setChecked(bool(zone.get("enabled", True)))
        enabled.toggled.connect(lambda _=False, i=idx: self._push_pishock_zone(i))
        row1.addWidget(enabled)
        row1.addStretch(1)
        del_btn = QPushButton("Delete"); del_btn.setMinimumHeight(BTN_HEIGHT_SMALL)
        del_btn.clicked.connect(lambda _=False, i=idx: self._on_pishock_zone_delete(i))
        row1.addWidget(del_btn)
        lay.addLayout(row1)

        strip = FoldStrip()

        # ---- Source fold: which contact feeds this zone ----
        src_fold = strip.add_fold(FoldCard("source", "Source", show_value=True))
        src_fold.add_header_widget(self._make_help_badge(
            "Source",
            "Which avatar contact feeds this zone: an OGB zone (or "
            "synthetic SPS source) plus the interaction filters that "
            "count (Touch/Pen × Self/Others). The live number and the "
            "glowing ring show the current 0–1 contact strength — the "
            "same value the router sees."
        ))
        se = src_fold.editor_layout
        st_row = _hbox(0, 8)
        st_row.addWidget(QLabel("Type"))
        ztype = QComboBox(); ztype.addItems(["Orf", "Pen"])
        ztype.setCurrentText(zone.get("zone_type", "Orf"))
        ztype.currentTextChanged.connect(
            lambda t, i=idx: self._on_pishock_ztype_changed(i, t))
        st_row.addWidget(ztype)
        st_row.addStretch(1)
        se.addLayout(st_row)
        sz_row = _hbox(0, 8)
        sz_row.addWidget(QLabel("Zone"))
        zname = QComboBox(); zname.setEditable(True); zname.setMinimumWidth(140)
        self._populate_pishock_zone_combo(zname, ztype.currentText())
        cur_zone = str(zone.get("ogb_zone", ""))
        if cur_zone and zname.findText(cur_zone) < 0:
            zname.addItem(cur_zone)
        zname.setEditText(cur_zone)
        zname.editTextChanged.connect(lambda _=None, i=idx: self._push_pishock_zone(i))
        sz_row.addWidget(zname, 1)
        se.addLayout(sz_row)
        filt: Dict[str, QCheckBox] = {}
        cur_f = set(zone.get("filters") or [])
        fl_rows = (_FILTERS[:2], _FILTERS[2:])
        for pair in fl_rows:
            fr = _hbox(0, 8)
            for fn in pair:
                cb = QCheckBox(fn); cb.setChecked(fn in cur_f)
                cb.toggled.connect(lambda _=False, i=idx: self._push_pishock_zone(i))
                fr.addWidget(cb); filt[fn] = cb
            fr.addStretch(1)
            se.addLayout(fr)

        # ---- Trigger fold: when the zone fires ----
        trg_fold = strip.add_fold(FoldCard("trigger", "Trigger"))
        trg_fold.add_header_widget(self._make_help_badge(
            "Trigger",
            "Rising-edge logic: the zone fires ONCE when strength crosses "
            "the threshold, then must re-arm by dropping below "
            "threshold − hysteresis before it can fire again. Larger "
            "hysteresis = needs a clearer release before re-arming. "
            "<b>Op</b> picks what fires: shock, vibrate, or beep — test "
            "with vibrate first."
        ))
        te = trg_fold.editor_layout
        op_row = _hbox(0, 8)
        op_row.addWidget(QLabel("Op"))
        op = QComboBox(); op.addItems(list(_OPS)); op.setCurrentText(zone.get("op", "shock"))
        op.currentTextChanged.connect(lambda _=None, i=idx: self._push_pishock_zone(i))
        op_row.addWidget(op)
        op_row.addStretch(1)
        te.addLayout(op_row)
        th_row = _hbox(0, 8)
        th_row.addWidget(QLabel("Threshold"))
        thr = QDoubleSpinBox(); thr.setRange(0.0, 1.0); thr.setSingleStep(0.05); thr.setDecimals(2)
        thr.setValue(float(zone.get("threshold", 0.5)))
        thr.valueChanged.connect(lambda _=None, i=idx: self._push_pishock_zone(i))
        th_row.addWidget(thr)
        th_row.addWidget(QLabel("Hysteresis"))
        hys = QDoubleSpinBox(); hys.setRange(0.0, 1.0); hys.setSingleStep(0.05); hys.setDecimals(2)
        hys.setValue(float(zone.get("hysteresis", 0.1)))
        hys.valueChanged.connect(lambda _=None, i=idx: self._push_pishock_zone(i))
        th_row.addWidget(hys)
        th_row.addStretch(1)
        te.addLayout(th_row)

        # ---- Output fold: what gets sent ----
        out_fold = strip.add_fold(FoldCard("output", "Output"))
        out_fold.add_header_widget(self._make_help_badge(
            "Output",
            "What a fire sends. Intensity maps the contact strength at "
            "fire time linearly onto the min→max range (harder contact = "
            "stronger event). <b>Min interval</b> is this zone's own "
            "cooldown between fires. <b>Sustain</b> re-fires every "
            "Cadence seconds while contact stays above the threshold "
            "instead of waiting for a fresh rising edge."
        ))
        oe = out_fold.editor_layout
        in_row = _hbox(0, 8)
        in_row.addWidget(QLabel("Intensity"))
        min_i = QSpinBox(); min_i.setRange(1, 100); min_i.setValue(int(zone.get("min_int", 1)))
        min_i.valueChanged.connect(lambda _=None, i=idx: self._push_pishock_zone(i))
        in_row.addWidget(min_i)
        in_row.addWidget(QLabel("→"))
        max_i = QSpinBox(); max_i.setRange(1, 100); max_i.setValue(int(zone.get("max_int", 30)))
        max_i.valueChanged.connect(lambda _=None, i=idx: self._push_pishock_zone(i))
        in_row.addWidget(max_i)
        in_row.addStretch(1)
        oe.addLayout(in_row)
        du_row = _hbox(0, 8)
        du_row.addWidget(QLabel("Duration (ms)"))
        dur = QSpinBox(); dur.setRange(1, 15000); dur.setSingleStep(100)
        dur.setValue(int(zone.get("duration_ms", 300)))
        dur.valueChanged.connect(lambda _=None, i=idx: self._push_pishock_zone(i))
        du_row.addWidget(dur)
        du_row.addWidget(QLabel("Min interval (s)"))
        minint = QDoubleSpinBox(); minint.setRange(0.3, 60.0); minint.setSingleStep(0.5); minint.setDecimals(1)
        minint.setValue(float(zone.get("min_interval_s", 1.0)))
        minint.valueChanged.connect(lambda _=None, i=idx: self._push_pishock_zone(i))
        du_row.addWidget(minint)
        du_row.addStretch(1)
        oe.addLayout(du_row)
        su_row = _hbox(0, 8)
        sustain = ToggleSwitch("Sustain (repeat while held)")
        sustain.setChecked(bool(zone.get("sustain", False)))
        sustain.toggled.connect(lambda _=False, i=idx: self._push_pishock_zone(i))
        su_row.addWidget(sustain)
        su_row.addWidget(QLabel("Cadence (s)"))
        cad = QDoubleSpinBox(); cad.setRange(0.3, 60.0); cad.setSingleStep(0.5); cad.setDecimals(1)
        cad.setValue(float(zone.get("cadence_s", 1.0)))
        cad.valueChanged.connect(lambda _=None, i=idx: self._push_pishock_zone(i))
        su_row.addWidget(cad)
        su_row.addStretch(1)
        oe.addLayout(su_row)

        lay.addWidget(strip)

        row = {
            "name": name, "enabled": enabled, "zone_type": ztype, "ogb_zone": zname,
            "filters": filt, "op": op, "threshold": thr, "hysteresis": hys,
            "min_int": min_i, "max_int": max_i, "duration_ms": dur,
            "min_interval_s": minint, "sustain": sustain, "cadence_s": cad,
            "strip": strip, "source_fold": src_fold,
            "trigger_fold": trg_fold, "output_fold": out_fold,
        }
        self._pishock_zone_rows.append(row)
        self._update_pishock_zone_subtitles(row)
        return card

    def _update_pishock_zone_subtitles(self, row: Dict[str, Any]) -> None:
        """Collapsed-fold summaries, derived from the row's widgets —
        same idea as the chain cards' per-stage subtitles."""
        try:
            zone_name = row["ogb_zone"].currentText().strip() or "—"
            row["source_fold"].set_subtitle(
                f"{row['zone_type'].currentText()} · {zone_name}")
            row["trigger_fold"].set_subtitle(
                f"{row['op'].currentText()} ≥ {float(row['threshold'].value()):.2f}")
            row["output_fold"].set_subtitle(
                f"{int(row['min_int'].value())}–{int(row['max_int'].value())}"
                f" · {int(row['duration_ms'].value())} ms")
        except RuntimeError:
            pass

    def _refresh_pishock_levels(self):
        """Fast tick: charge each zone card's activity rings + arrows
        from the live zone strength (the same number the router sees).
        Source always shows what's arriving; Trigger/Output only charge
        when the zone is enabled and the strength clears its threshold."""
        rows = self._pishock_zone_rows
        if not rows:
            return
        view = self.views.get("PiShock")
        if view is not None and not view.isVisible():
            return
        specs = []
        live_rows = []
        for row in rows:
            try:
                specs.append((
                    row["ogb_zone"].currentText(),
                    row["zone_type"].currentText(),
                    [fn for fn, cb in row["filters"].items() if cb.isChecked()],
                ))
                live_rows.append(row)
            except RuntimeError:
                continue
        try:
            strengths = self.controller.get_live_zone_strengths(specs)
        except Exception:
            return
        for row, strength in zip(live_rows, strengths):
            try:
                fired = (row["enabled"].isChecked()
                         and strength >= float(row["threshold"].value()))
                gated = strength if fired else 0.0
                row["strip"].set_levels([strength, gated, gated])
                row["source_fold"].set_value(strength)
                self._update_pishock_zone_subtitles(row)
            except RuntimeError:
                continue

    def _populate_pishock_zone_combo(self, combo: QComboBox, zone_type: str):
        populate_zone_combo(self.controller, combo, zone_type)

    def _on_pishock_ztype_changed(self, idx: int, new_type: str):
        if self._is_updating_pishock:
            return
        if idx < 0 or idx >= len(self._pishock_zone_rows):
            return
        row = self._pishock_zone_rows[idx]
        on_zone_type_changed(self.controller, row["ogb_zone"], new_type,
                             lambda: self._push_pishock_zone(idx))

    def _repopulate_pishock_zone_combos(self):
        """Page arrival: fold in zones detected while the page was hidden,
        keeping each combo's current selection."""
        for row in self._pishock_zone_rows:
            try:
                populate_zone_combo(self.controller, row["ogb_zone"],
                                    row["zone_type"].currentText())
            except RuntimeError:
                continue

    def _push_pishock_zone(self, idx: int):
        if self._is_updating_pishock:
            return
        if idx < 0 or idx >= len(self._pishock_zone_rows):
            return
        r = self._pishock_zone_rows[idx]
        zone = {
            "name": r["name"].text(),
            "enabled": r["enabled"].isChecked(),
            "zone_type": r["zone_type"].currentText(),
            "ogb_zone": r["ogb_zone"].currentText(),
            "filters": [fn for fn, cb in r["filters"].items() if cb.isChecked()],
            "op": r["op"].currentText(),
            "threshold": float(r["threshold"].value()),
            "hysteresis": float(r["hysteresis"].value()),
            "min_int": int(r["min_int"].value()),
            "max_int": int(r["max_int"].value()),
            "duration_ms": int(r["duration_ms"].value()),
            "min_interval_s": float(r["min_interval_s"].value()),
            "sustain": r["sustain"].isChecked(),
            "cadence_s": float(r["cadence_s"].value()),
        }
        try:
            self.controller.set_pishock_zone(idx, zone)
        except Exception as e:
            self.log_message(f"PiShock zone save failed: {e}")

    def _on_pishock_zone_add(self):
        zones = self.controller.get_pishock_zones()
        self.controller.set_pishock_zone(len(zones), {
            "name": f"Zone {len(zones) + 1}", "op": "vibrate",
            "filters": ["TouchSelf", "TouchOthers"],
        })
        self._refresh_pishock_view()

    def _on_pishock_zone_delete(self, idx: int):
        self.controller.delete_pishock_zone(idx)
        self._refresh_pishock_view()
