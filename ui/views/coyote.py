"""DG-Lab Coyote view: BLE device pick/connect, hardware soft strength limits,
and the two A/B channel routing configs.

Mixin for ui_components.OscGoesPurrrUI. Calls only controller facade methods.
e-stim, so auto-connect is opt-in and the hardware soft limits are front and
centre."""

from typing import Any, Dict

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QComboBox, QCheckBox, QDoubleSpinBox, QFrame, QLabel, QLineEdit,
    QPushButton, QSpinBox, QVBoxLayout,
)

from constants import BTN_HEIGHT_SMALL
from ui.fold_strip import FoldCard, FoldStrip
from ui.layout_helpers import vbox as _vbox, hbox as _hbox
from ui.views._backend_common import (
    on_zone_type_changed, populate_zone_combo, run_connect_now,
    zone_signature,
)
from ui.widgets import ToggleSwitch, Card as _Card

_FILTERS = ("TouchSelf", "TouchOthers", "PenSelf", "PenOthers")


class CoyoteMixin:

    _is_updating_coyote = False
    _coyote_channel_rows: Dict[str, Dict[str, Any]] = {}

    def _build_coyote_view(self, parent_layout: QVBoxLayout):
        title = QLabel("DG-Lab Coyote")
        title.setObjectName("viewTitle")
        title.setAlignment(Qt.AlignHCenter)
        parent_layout.addWidget(title)

        parent_layout.addWidget(self._muted_label(
            "Drives a DG-Lab Coyote 3.0 e-stim unit over Bluetooth (no phone "
            "app needed — a BLE adapter on this PC is required).\n"
            "⚠ e-stim device: set the hardware soft strength limits below before "
            "connecting, and start low. Limits are enforced on the device itself."
        ))

        # ---- Status / connect ----
        status_card = _Card()
        slay = _vbox(14, 8)
        status_card.setLayout(slay)
        self.coyote_status_label = QLabel("Coyote: Unknown")
        f = self.coyote_status_label.font(); f.setBold(True); f.setPointSize(12)
        self.coyote_status_label.setFont(f)
        slay.addWidget(self.coyote_status_label)
        self.coyote_live_label = self._muted_label("")
        slay.addWidget(self.coyote_live_label)

        row = _hbox(0, 8)
        self.coyote_auto_check = ToggleSwitch("Auto Connect (Coyote)")
        self.coyote_auto_check.toggled.connect(self._on_coyote_auto)
        row.addWidget(self.coyote_auto_check)
        self.coyote_connect_btn = QPushButton("Connect Now")
        self.coyote_connect_btn.setMinimumHeight(BTN_HEIGHT_SMALL)
        self.coyote_connect_btn.clicked.connect(self._on_coyote_connect)
        row.addWidget(self.coyote_connect_btn)
        row.addStretch(1)
        slay.addLayout(row)
        parent_layout.addWidget(status_card)

        # ---- Device ----
        dev_card = _Card()
        dlay = _vbox(14, 6)
        dev_card.setLayout(dlay)
        d_hdr = _hbox(0, 6)
        dh = QLabel("Device"); dh.setObjectName("sectionTitle")
        d_hdr.addWidget(dh)
        d_hdr.addWidget(self._make_help_badge(
            "Device",
            "Which Coyote to talk to over Bluetooth LE. <b>Scan</b> lists "
            "nearby BLE devices — pick yours to fill in the address, then "
            "<b>Apply</b>. The address is remembered, so future connects "
            "skip the scan."
        ))
        d_hdr.addStretch(1)
        dlay.addLayout(d_hdr)
        scan_row = _hbox(0, 8)
        self.coyote_scan_btn = QPushButton("Scan")
        self.coyote_scan_btn.setMinimumHeight(BTN_HEIGHT_SMALL)
        self.coyote_scan_btn.clicked.connect(self._on_coyote_scan)
        scan_row.addWidget(self.coyote_scan_btn)
        self.coyote_scan_combo = QComboBox()
        self.coyote_scan_combo.setMinimumWidth(260)
        self.coyote_scan_combo.activated.connect(self._on_coyote_pick)
        scan_row.addWidget(self.coyote_scan_combo, 1)
        dlay.addLayout(scan_row)
        addr_row = _hbox(0, 8)
        addr_row.addWidget(QLabel("Address"))
        self.coyote_addr = QLineEdit(); self.coyote_addr.setMinimumWidth(200)
        addr_row.addWidget(self.coyote_addr, 1)
        addr_row.addWidget(QLabel("Name"))
        self.coyote_name = QLineEdit(); self.coyote_name.setFixedWidth(120)
        addr_row.addWidget(self.coyote_name)
        dev_apply = QPushButton("Apply"); dev_apply.setMinimumHeight(BTN_HEIGHT_SMALL)
        dev_apply.clicked.connect(self._on_coyote_device_apply)
        addr_row.addWidget(dev_apply)
        dlay.addLayout(addr_row)
        parent_layout.addWidget(dev_card)

        # ---- Soft limits ----
        lim_card = _Card()
        llay = _vbox(14, 6)
        lim_card.setLayout(llay)
        l_hdr = _hbox(0, 6)
        lh = QLabel("Hardware soft strength limits"); lh.setObjectName("sectionTitle")
        l_hdr.addWidget(lh)
        l_hdr.addWidget(self._make_help_badge(
            "Hardware soft limits",
            "Per-channel ceilings written to the Coyote itself, enforced "
            "by the device — no routing config, bug, or stray signal can "
            "drive a channel past them. Set these LOW before first "
            "connecting and raise them gradually."
        ))
        l_hdr.addStretch(1)
        llay.addLayout(l_hdr)
        llay.addWidget(self._muted_label(
            "Per-channel ceilings (0-200) written to the device. Channel "
            "strength can never exceed these, even at full contact."))
        lim_row = _hbox(0, 8)
        lim_row.addWidget(QLabel("Channel A"))
        self.coyote_limit_a = QSpinBox(); self.coyote_limit_a.setRange(0, 200)
        self.coyote_limit_a.valueChanged.connect(self._on_coyote_limits)
        lim_row.addWidget(self.coyote_limit_a)
        lim_row.addWidget(QLabel("Channel B"))
        self.coyote_limit_b = QSpinBox(); self.coyote_limit_b.setRange(0, 200)
        self.coyote_limit_b.valueChanged.connect(self._on_coyote_limits)
        lim_row.addWidget(self.coyote_limit_b)
        lim_row.addStretch(1)
        llay.addLayout(lim_row)
        parent_layout.addWidget(lim_card)

        # ---- Channels ----
        self._coyote_channel_rows = {}
        for ch in ("A", "B"):
            parent_layout.addWidget(self._build_coyote_channel_card(ch))

        self._refresh_coyote_view()
        self._coyote_timer = QTimer(self.window)
        self._coyote_timer.setInterval(1000)
        self._coyote_timer.timeout.connect(self._refresh_coyote_status_only)
        self._coyote_timer.start()

        # Fast tick driving the channel cards' activity rings + arrows.
        # Short-circuits while the view is hidden.
        self._coyote_level_timer = QTimer(self.window)
        self._coyote_level_timer.setInterval(100)
        self._coyote_level_timer.timeout.connect(self._refresh_coyote_levels)
        self._coyote_level_timer.start()

    def _build_coyote_channel_card(self, ch: str) -> QFrame:
        """One channel as a fold strip — Source → Shaping → Output —
        in the Device Routing chain's design language (collapsible
        folds joined by arrows, activity rings charged by the live
        zone strength; see ui/fold_strip.py)."""
        card = _Card(); card.setMaximumWidth(860)
        lay = _vbox(12, 8); card.setLayout(lay)
        hdr = _hbox(0, 8)
        t = QLabel(f"Channel {ch}"); tf = t.font(); tf.setBold(True); tf.setPointSize(11); t.setFont(tf)
        hdr.addWidget(t)
        enabled = ToggleSwitch("Enabled")
        enabled.toggled.connect(lambda _=False, c=ch: self._push_coyote_channel(c))
        hdr.addWidget(enabled)
        hdr.addStretch(1)
        lay.addLayout(hdr)

        strip = FoldStrip()

        # ---- Source fold ----
        src_fold = strip.add_fold(FoldCard("source", "Source", show_value=True))
        src_fold.add_header_widget(self._make_help_badge(
            "Source",
            "Which avatar contact drives this channel: an OGB zone (or "
            "synthetic SPS source) plus the interaction filters that "
            "count. The live number and the glowing ring show the current "
            "0–1 contact strength."
        ))
        se = src_fold.editor_layout
        st_row = _hbox(0, 8)
        st_row.addWidget(QLabel("Type"))
        ztype = QComboBox(); ztype.addItems(["Orf", "Pen"])
        ztype.currentTextChanged.connect(
            lambda t, c=ch: self._on_coyote_ztype_changed(c, t))
        st_row.addWidget(ztype)
        st_row.addStretch(1)
        se.addLayout(st_row)
        sz_row = _hbox(0, 8)
        sz_row.addWidget(QLabel("Zone"))
        zname = QComboBox(); zname.setEditable(True); zname.setMinimumWidth(140)
        zname.editTextChanged.connect(lambda _=None, c=ch: self._push_coyote_channel(c))
        sz_row.addWidget(zname, 1)
        se.addLayout(sz_row)
        filt: Dict[str, QCheckBox] = {}
        for pair in (_FILTERS[:2], _FILTERS[2:]):
            fr = _hbox(0, 8)
            for fn in pair:
                cb = QCheckBox(fn)
                cb.toggled.connect(lambda _=False, c=ch: self._push_coyote_channel(c))
                fr.addWidget(cb); filt[fn] = cb
            fr.addStretch(1)
            se.addLayout(fr)

        # ---- Shaping fold ----
        shp_fold = strip.add_fold(FoldCard("shaping", "Shaping"))
        shp_fold.add_header_widget(self._make_help_badge(
            "Shaping",
            "Strength below the threshold outputs nothing; above it, "
            "(strength − threshold) × gain sets the drive level. Use the "
            "threshold to ignore grazing contact and the gain to control "
            "how fast intensity climbs once past it."
        ))
        he = shp_fold.editor_layout
        th_row = _hbox(0, 8)
        th_row.addWidget(QLabel("Threshold"))
        thr = QDoubleSpinBox(); thr.setRange(0.0, 1.0); thr.setSingleStep(0.05); thr.setDecimals(2)
        thr.valueChanged.connect(lambda _=None, c=ch: self._push_coyote_channel(c))
        th_row.addWidget(thr)
        th_row.addWidget(QLabel("Gain"))
        gain = QDoubleSpinBox(); gain.setRange(0.0, 5.0); gain.setSingleStep(0.1); gain.setDecimals(2)
        gain.valueChanged.connect(lambda _=None, c=ch: self._push_coyote_channel(c))
        th_row.addWidget(gain)
        th_row.addStretch(1)
        he.addLayout(th_row)

        # ---- Output fold ----
        out_fold = strip.add_fold(FoldCard("output", "Output"))
        out_fold.add_header_widget(self._make_help_badge(
            "Output",
            "<b>Max strength</b> scales the shaped 0–1 level onto the "
            "channel's 0–200 strength range (still capped by the hardware "
            "soft limit above). <b>Waveform freq / intensity</b> set the "
            "pulse waveform the channel plays while driven — frequency "
            "changes the texture of the sensation."
        ))
        oe = out_fold.editor_layout
        ms_row = _hbox(0, 8)
        ms_row.addWidget(QLabel("Max strength"))
        maxs = QSpinBox(); maxs.setRange(0, 200)
        maxs.valueChanged.connect(lambda _=None, c=ch: self._push_coyote_channel(c))
        ms_row.addWidget(maxs)
        ms_row.addStretch(1)
        oe.addLayout(ms_row)
        wf_row = _hbox(0, 8)
        wf_row.addWidget(QLabel("Waveform freq"))
        freq = QSpinBox(); freq.setRange(10, 240)
        freq.valueChanged.connect(lambda _=None, c=ch: self._push_coyote_channel(c))
        wf_row.addWidget(freq)
        wf_row.addWidget(QLabel("Waveform intensity"))
        wint = QSpinBox(); wint.setRange(0, 100)
        wint.valueChanged.connect(lambda _=None, c=ch: self._push_coyote_channel(c))
        wf_row.addWidget(wint)
        wf_row.addStretch(1)
        oe.addLayout(wf_row)

        lay.addWidget(strip)

        self._coyote_channel_rows[ch] = {
            "enabled": enabled, "zone_type": ztype, "ogb_zone": zname,
            "filters": filt, "threshold": thr, "gain": gain,
            "max_strength": maxs, "freq": freq, "intensity": wint,
            "strip": strip, "source_fold": src_fold,
            "shaping_fold": shp_fold, "output_fold": out_fold,
        }
        self._update_coyote_channel_subtitles(self._coyote_channel_rows[ch])
        return card

    def _update_coyote_channel_subtitles(self, row: Dict[str, Any]) -> None:
        """Collapsed-fold summaries derived from the row's widgets."""
        try:
            zone_name = row["ogb_zone"].currentText().strip() or "—"
            row["source_fold"].set_subtitle(
                f"{row['zone_type'].currentText()} · {zone_name}")
            row["shaping_fold"].set_subtitle(
                f"≥ {float(row['threshold'].value()):.2f}"
                f" · ×{float(row['gain'].value()):.2f}")
            row["output_fold"].set_subtitle(
                f"max {int(row['max_strength'].value())}"
                f" · {int(row['freq'].value())} Hz")
        except RuntimeError:
            pass

    def _refresh_coyote_levels(self):
        """Fast tick: charge the channel cards' activity rings + arrows.
        Source shows the live zone strength; Shaping/Output mirror the
        router's shaping math (`compute_channel_strength`) so the rings
        tell the truth about what the device would feel."""
        rows = self._coyote_channel_rows
        if not rows:
            return
        view = self.views.get("Coyote")
        if view is not None and not view.isVisible():
            return
        order = list(rows.keys())
        specs = []
        for ch in order:
            row = rows[ch]
            try:
                specs.append((
                    row["ogb_zone"].currentText(),
                    row["zone_type"].currentText(),
                    [fn for fn, cb in row["filters"].items() if cb.isChecked()],
                ))
            except RuntimeError:
                return
        try:
            strengths = self.controller.get_live_zone_strengths(specs)
        except Exception:
            return
        for ch, strength in zip(order, strengths):
            row = rows[ch]
            try:
                thr = float(row["threshold"].value())
                gain = float(row["gain"].value())
                if not row["enabled"].isChecked() or strength <= thr:
                    shaped = 0.0
                else:
                    shaped = max(0.0, min(1.0, (strength - thr) * gain))
                drive = shaped * (int(row["max_strength"].value()) / 200.0)
                row["strip"].set_levels([strength, shaped, drive])
                row["source_fold"].set_value(strength)
                self._update_coyote_channel_subtitles(row)
            except RuntimeError:
                continue

    # ---- refresh ----
    def _refresh_coyote_view(self):
        if not self._coyote_channel_rows:
            return
        self._is_updating_coyote = True
        try:
            status = self.controller.get_coyote_status()
            self._apply_coyote_status(status, full=True)
        finally:
            self._is_updating_coyote = False

    def _refresh_coyote_status_only(self):
        view = self.views.get("Coyote")
        if view is not None and not view.isVisible():
            return
        try:
            status = self.controller.get_coyote_status()
        except Exception:
            return
        self._is_updating_coyote = True
        try:
            self._apply_coyote_status(status, full=False)
        finally:
            self._is_updating_coyote = False
        # Fold newly detected zones/sources into the combos when the set
        # changes while the page is open (avatar loaded mid-visit).
        sig = zone_signature(self.controller)
        if sig != getattr(self, "_coyote_zone_sig", None):
            self._coyote_zone_sig = sig
            self._repopulate_coyote_zone_combos()

    def _apply_coyote_status(self, status: dict, full: bool):
        if not status.get("available"):
            self.coyote_status_label.setText("Coyote: bleak not installed — pip install bleak")
            self.coyote_status_label.setProperty("role", "alert")
        elif status.get("connected"):
            self.coyote_status_label.setText("Coyote: connected")
            self.coyote_status_label.setProperty("role", None)
        else:
            err = status.get("last_error") or "not connected"
            self.coyote_status_label.setText(f"Coyote: disconnected — {err}")
            self.coyote_status_label.setProperty("role", "alert")
        self.coyote_status_label.style().unpolish(self.coyote_status_label)
        self.coyote_status_label.style().polish(self.coyote_status_label)

        battery = status.get("battery")
        sa, sb = status.get("strengths", (0, 0))
        bat_txt = f"{battery}%" if battery is not None else "—"
        self.coyote_live_label.setText(f"Battery {bat_txt} · A={sa} B={sb}")

        self.coyote_auto_check.setChecked(bool(status.get("auto_connect")))
        if not full:
            return
        dev = status.get("device", {})
        if self.coyote_addr.text() != dev.get("address", ""):
            self.coyote_addr.setText(dev.get("address", ""))
        if self.coyote_name.text() != dev.get("name", ""):
            self.coyote_name.setText(dev.get("name", ""))
        lim = status.get("limits", {})
        self.coyote_limit_a.setValue(int(lim.get("limit_a", 100)))
        self.coyote_limit_b.setValue(int(lim.get("limit_b", 100)))
        chans = status.get("channels", {})
        for ch, row in self._coyote_channel_rows.items():
            c = chans.get(ch, {})
            row["enabled"].setChecked(bool(c.get("enabled", False)))
            row["zone_type"].setCurrentText(c.get("zone_type", "Orf"))
            self._populate_coyote_zone_combo(row["ogb_zone"], c.get("zone_type", "Orf"))
            zone = str(c.get("ogb_zone", ""))
            if zone and row["ogb_zone"].findText(zone) < 0:
                row["ogb_zone"].addItem(zone)
            row["ogb_zone"].setEditText(zone)
            cur_f = set(c.get("filters") or [])
            for fn, cb in row["filters"].items():
                cb.setChecked(fn in cur_f)
            row["threshold"].setValue(float(c.get("threshold", 0.0)))
            row["gain"].setValue(float(c.get("gain", 1.0)))
            row["max_strength"].setValue(int(c.get("max_strength", 100)))
            row["freq"].setValue(int(c.get("freq", 100)))
            row["intensity"].setValue(int(c.get("intensity", 100)))

    # ---- handlers ----
    def _on_coyote_auto(self, checked: bool):
        if self._is_updating_coyote:
            return
        self.controller.set_coyote_auto_connect(bool(checked))

    def _on_coyote_connect(self):
        # A BLE connect blocks for seconds — keep it off the Qt thread
        # (which also hosts the Buttplug routing tick).
        run_connect_now(
            self, "Coyote", self.controller.coyote_connect_now,
            self._refresh_coyote_status_only,
            buttons=[self.coyote_connect_btn],
        )

    def _on_coyote_scan(self):
        # The 6 s BLE discover used to freeze the whole app (the 'scanning…'
        # line below never even painted). Run it on a worker instead.
        self.log_message("Coyote: scanning for BLE devices…")
        self.run_ui_task(
            self.controller.coyote_scan_devices,
            self._on_coyote_scan_done,
            buttons=[self.coyote_scan_btn],
        )

    def _on_coyote_scan_done(self, result):
        if isinstance(result, Exception):
            self.log_message(f"Coyote: scan failed — {result}")
            return
        devices = result or []
        self.coyote_scan_combo.clear()
        for name, addr in devices:
            self.coyote_scan_combo.addItem(f"{name}  [{addr}]", addr)
        self.log_message(f"Coyote: found {len(devices)} device(s)")

    def _on_coyote_pick(self, _index: int):
        addr = self.coyote_scan_combo.currentData()
        if addr:
            self.coyote_addr.setText(str(addr))

    def _on_coyote_device_apply(self):
        self.controller.set_coyote_device(
            self.coyote_addr.text().strip(), self.coyote_name.text().strip())
        self.log_message("Coyote: device applied")

    def _on_coyote_limits(self, *_):
        if self._is_updating_coyote:
            return
        self.controller.set_coyote_limits(
            int(self.coyote_limit_a.value()), int(self.coyote_limit_b.value()))

    def _push_coyote_channel(self, ch: str):
        if self._is_updating_coyote:
            return
        row = self._coyote_channel_rows.get(ch)
        if not row:
            return
        cfg = {
            "enabled": row["enabled"].isChecked(),
            "zone_type": row["zone_type"].currentText(),
            "ogb_zone": row["ogb_zone"].currentText(),
            "filters": [fn for fn, cb in row["filters"].items() if cb.isChecked()],
            "threshold": float(row["threshold"].value()),
            "gain": float(row["gain"].value()),
            "max_strength": int(row["max_strength"].value()),
            "freq": int(row["freq"].value()),
            "intensity": int(row["intensity"].value()),
        }
        try:
            self.controller.set_coyote_channel(ch, cfg)
        except Exception as e:
            self.log_message(f"Coyote channel save failed: {e}")

    def _populate_coyote_zone_combo(self, combo: QComboBox, zone_type: str):
        populate_zone_combo(self.controller, combo, zone_type)

    def _on_coyote_ztype_changed(self, ch: str, new_type: str):
        if self._is_updating_coyote:
            return
        row = self._coyote_channel_rows.get(ch)
        if not row:
            return
        on_zone_type_changed(self.controller, row["ogb_zone"], new_type,
                             lambda: self._push_coyote_channel(ch))

    def _repopulate_coyote_zone_combos(self):
        """Page arrival: fold in zones detected while the page was hidden,
        keeping each combo's current selection."""
        for row in self._coyote_channel_rows.values():
            try:
                populate_zone_combo(self.controller, row["ogb_zone"],
                                    row["zone_type"].currentText())
            except RuntimeError:
                continue
