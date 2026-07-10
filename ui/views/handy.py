"""The Handy view: cloud connection (connection key + handyfeeling API key),
motion settings (control mode, slider stroke zone, send cadence), and the
single zone → stroker routing chain.

Mixin for ui_components.OscGoesPurrrUI. Calls only controller facade methods.
The Handy 2 / Pro 2 (firmware 4) is cloud-controlled via the official
handyfeeling.com REST API v3; the device must be on Wi-Fi."""

from typing import Any, Dict

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDoubleSpinBox, QLabel, QLineEdit,
    QPushButton, QVBoxLayout,
)

from constants import BTN_HEIGHT_SMALL
from ui.fold_strip import FoldCard, FoldStrip
from ui.layout_helpers import vbox as _vbox, hbox as _hbox
from ui.views._backend_common import (
    on_zone_type_changed, populate_zone_combo, zone_signature,
)
from ui.widgets import ToggleSwitch, Card as _Card

_FILTERS = ("TouchSelf", "TouchOthers", "PenSelf", "PenOthers")
_MODES = (("speed", "Stroke speed (HAMP)"), ("position", "Position (HDSP)"))


class HandyMixin:

    _is_updating_handy = False
    _handy_row: Dict[str, Any] = {}

    def _build_handy_view(self, parent_layout: QVBoxLayout):
        # Guard: initial setValue() calls during construction fire the same
        # signals as user edits; don't push half-built state at the controller.
        self._is_updating_handy = True
        title = QLabel("The Handy")
        title.setObjectName("viewTitle")
        title.setAlignment(Qt.AlignHCenter)
        parent_layout.addWidget(title)

        parent_layout.addWidget(self._muted_label(
            "Drives a Handy 2 / Handy Pro 2 stroker from avatar contacts via the\n"
            "official handyfeeling.com API (v3). The device must be on Wi-Fi and "
            "linked to your Handy account; commands route through the cloud.\n"
            "You need the connection key (Handyverse app) and an API key "
            "(Application ID) from user.handyfeeling.com."
        ))

        # ---- Status / connect ----
        status_card = _Card()
        slay = _vbox(14, 8)
        status_card.setLayout(slay)
        self.handy_status_label = QLabel("Handy: Unknown")
        f = self.handy_status_label.font(); f.setBold(True); f.setPointSize(12)
        self.handy_status_label.setFont(f)
        slay.addWidget(self.handy_status_label)
        row = _hbox(0, 8)
        self.handy_auto_check = ToggleSwitch("Auto Connect (Handy)")
        self.handy_auto_check.toggled.connect(self._on_handy_auto)
        row.addWidget(self.handy_auto_check)
        self.handy_connect_btn = QPushButton("Connect Now")
        self.handy_connect_btn.setMinimumHeight(BTN_HEIGHT_SMALL)
        self.handy_connect_btn.clicked.connect(self._on_handy_connect)
        row.addWidget(self.handy_connect_btn)
        row.addStretch(1)
        slay.addLayout(row)
        parent_layout.addWidget(status_card)

        # ---- Connection ----
        conn_card = _Card()
        clay = _vbox(14, 6)
        conn_card.setLayout(clay)
        c_hdr = _hbox(0, 6)
        chh = QLabel("Connection"); chh.setObjectName("sectionTitle")
        c_hdr.addWidget(chh)
        c_hdr.addWidget(self._make_help_badge(
            "Handy connection",
            "<b>Connection key</b> identifies your device — it's shown in "
            "the Handyverse app / onboarding. <b>API key</b> is the "
            "handyfeeling.com Application ID from your account at "
            "user.handyfeeling.com; API v3 requires it on every request. "
            "Both stay on this PC."
        ))
        c_hdr.addStretch(1)
        clay.addLayout(c_hdr)
        conn_row = _hbox(0, 8)
        conn_row.addWidget(QLabel("Connection key"))
        self.handy_conn_key = QLineEdit(); self.handy_conn_key.setFixedWidth(130)
        # The connection key is the secret that CONTROLS the device — anyone
        # who reads it off a stream/screenshot can pair to it. Mask it like
        # the API key (reveal-while-editing so typing is still checkable).
        self.handy_conn_key.setEchoMode(QLineEdit.PasswordEchoOnEdit)
        conn_row.addWidget(self.handy_conn_key)
        conn_row.addWidget(QLabel("API key"))
        self.handy_api_key = QLineEdit(); self.handy_api_key.setFixedWidth(220)
        self.handy_api_key.setEchoMode(QLineEdit.Password)
        conn_row.addWidget(self.handy_api_key)
        conn_apply = QPushButton("Apply"); conn_apply.setMinimumHeight(BTN_HEIGHT_SMALL)
        conn_apply.clicked.connect(self._on_handy_conn_apply)
        conn_row.addWidget(conn_apply)
        conn_row.addStretch(1)
        clay.addLayout(conn_row)
        parent_layout.addWidget(conn_card)

        # ---- Motion ----
        m_card = _Card()
        mlay = _vbox(14, 6)
        m_card.setLayout(mlay)
        m_hdr = _hbox(0, 6)
        mhh = QLabel("Motion"); mhh.setObjectName("sectionTitle")
        m_hdr.addWidget(mhh)
        m_hdr.addWidget(self._make_help_badge(
            "Motion",
            "<b>Stroke speed</b> mode (HAMP): the device strokes on its own; "
            "contact strength sets how fast. <b>Position</b> mode (HDSP): "
            "contact strength steers the slider position directly. "
            "<b>Stroke zone</b> limits how far the slider travels (0 = "
            "bottom, 1 = top) and is enforced by the device in every mode. "
            "<b>Commands/s</b> caps how many cloud requests are sent — the "
            "official API budget is about 240 per minute (4/s)."
        ))
        m_hdr.addStretch(1)
        mlay.addLayout(m_hdr)
        mode_row = _hbox(0, 8)
        mode_row.addWidget(QLabel("Mode"))
        self.handy_mode = QComboBox()
        for _key, label in _MODES:
            self.handy_mode.addItem(label)
        self.handy_mode.currentIndexChanged.connect(self._on_handy_motion)
        mode_row.addWidget(self.handy_mode)
        mode_row.addWidget(QLabel("Stroke zone"))
        self.handy_stroke_min = QDoubleSpinBox()
        self.handy_stroke_min.setRange(0.0, 1.0); self.handy_stroke_min.setSingleStep(0.05)
        self.handy_stroke_min.setDecimals(2)
        self.handy_stroke_min.valueChanged.connect(self._on_handy_motion)
        mode_row.addWidget(self.handy_stroke_min)
        mode_row.addWidget(QLabel("to"))
        self.handy_stroke_max = QDoubleSpinBox()
        self.handy_stroke_max.setRange(0.0, 1.0); self.handy_stroke_max.setSingleStep(0.05)
        self.handy_stroke_max.setDecimals(2); self.handy_stroke_max.setValue(1.0)
        self.handy_stroke_max.valueChanged.connect(self._on_handy_motion)
        mode_row.addWidget(self.handy_stroke_max)
        mode_row.addStretch(1)
        mlay.addLayout(mode_row)
        rate_row = _hbox(0, 8)
        rate_row.addWidget(QLabel("Commands/s"))
        self.handy_cmd_hz = QDoubleSpinBox()
        self.handy_cmd_hz.setRange(0.5, 15.0); self.handy_cmd_hz.setSingleStep(0.5)
        self.handy_cmd_hz.setDecimals(1); self.handy_cmd_hz.setValue(4.0)
        self.handy_cmd_hz.valueChanged.connect(self._on_handy_motion)
        rate_row.addWidget(self.handy_cmd_hz)
        self.handy_invert = QCheckBox("Invert position")
        self.handy_invert.setToolTip(
            "Position mode: by default stronger contact pulls the slider down; "
            "invert to pull it up instead.")
        self.handy_invert.toggled.connect(self._on_handy_motion)
        rate_row.addWidget(self.handy_invert)
        rate_row.addStretch(1)
        mlay.addLayout(rate_row)
        parent_layout.addWidget(m_card)

        # ---- Routing (single chain, fold-strip design language) ----
        r_card = _Card(dark_bg=True)
        rlay = _vbox(10, 6)
        r_card.setLayout(rlay)
        rh = QLabel("Routing"); rh.setObjectName("sectionTitle")
        rlay.addWidget(rh)
        rlay.addWidget(self._build_handy_zone_card())
        rlay.addStretch(1)
        parent_layout.addWidget(r_card, 1)

        self._is_updating_handy = False
        self._refresh_handy_view()
        self._handy_timer = QTimer(self.window)
        self._handy_timer.setInterval(1500)
        self._handy_timer.timeout.connect(self._refresh_handy_status_only)
        self._handy_timer.start()

        # Fast tick driving the routing card's activity rings + arrows.
        self._handy_level_timer = QTimer(self.window)
        self._handy_level_timer.setInterval(100)
        self._handy_level_timer.timeout.connect(self._refresh_handy_levels)
        self._handy_level_timer.start()

    def _build_handy_zone_card(self):
        """The one routed output as a fold strip — Source → Shaping →
        Output — in the Device Routing chain's design language (see
        ui/fold_strip.py)."""
        card = _Card(); card.setMaximumWidth(860)
        lay = _vbox(10, 6); card.setLayout(lay)
        row1 = _hbox(0, 8)
        t = QLabel("Stroker"); tf = t.font(); tf.setBold(True); t.setFont(tf)
        t.setMinimumWidth(110)
        row1.addWidget(t)
        enabled = ToggleSwitch("Enabled")
        enabled.toggled.connect(lambda _=False: self._push_handy_zone())
        row1.addWidget(enabled)
        row1.addStretch(1)
        lay.addLayout(row1)

        strip = FoldStrip()

        # ---- Source fold ----
        src_fold = strip.add_fold(FoldCard("source", "Source", show_value=True))
        src_fold.add_header_widget(self._make_help_badge(
            "Source",
            "Which avatar contact drives the stroker: an OGB zone (or "
            "synthetic SPS source) plus the interaction filters that "
            "count. The live number and the glowing ring show the current "
            "0–1 contact strength."
        ))
        se = src_fold.editor_layout
        st_row = _hbox(0, 8)
        st_row.addWidget(QLabel("Type"))
        ztype = QComboBox(); ztype.addItems(["Orf", "Pen"])
        ztype.currentTextChanged.connect(self._on_handy_ztype_changed)
        st_row.addWidget(ztype)
        st_row.addStretch(1)
        se.addLayout(st_row)
        sz_row = _hbox(0, 8)
        sz_row.addWidget(QLabel("Zone"))
        zname = QComboBox(); zname.setEditable(True); zname.setMinimumWidth(130)
        zname.editTextChanged.connect(lambda _=None: self._push_handy_zone())
        sz_row.addWidget(zname, 1)
        se.addLayout(sz_row)
        filt: Dict[str, QCheckBox] = {}
        for pair in (_FILTERS[:2], _FILTERS[2:]):
            fr = _hbox(0, 8)
            for fn in pair:
                cb = QCheckBox(fn)
                cb.toggled.connect(lambda _=False: self._push_handy_zone())
                fr.addWidget(cb); filt[fn] = cb
            fr.addStretch(1)
            se.addLayout(fr)

        # ---- Shaping fold ----
        shp_fold = strip.add_fold(FoldCard("shaping", "Shaping"))
        shp_fold.add_header_widget(self._make_help_badge(
            "Shaping",
            "Strength below the threshold outputs nothing; above it, "
            "(strength − threshold) × gain sets the level. Use the "
            "threshold to ignore grazing contact and the gain to control "
            "how fast the stroker ramps once past it."
        ))
        he = shp_fold.editor_layout
        th_row = _hbox(0, 8)
        th_row.addWidget(QLabel("Threshold"))
        thr = QDoubleSpinBox(); thr.setRange(0.0, 1.0); thr.setSingleStep(0.05); thr.setDecimals(2)
        thr.valueChanged.connect(lambda _=None: self._push_handy_zone())
        th_row.addWidget(thr)
        th_row.addWidget(QLabel("Gain"))
        gain = QDoubleSpinBox(); gain.setRange(0.0, 5.0); gain.setSingleStep(0.1); gain.setDecimals(2)
        gain.valueChanged.connect(lambda _=None: self._push_handy_zone())
        th_row.addWidget(gain)
        th_row.addStretch(1)
        he.addLayout(th_row)

        # ---- Output fold ----
        out_fold = strip.add_fold(FoldCard("output", "Output"))
        out_fold.add_header_widget(self._make_help_badge(
            "Output",
            "<b>Max speed</b> caps the stroke speed (0–1) in speed mode no "
            "matter how strong the contact gets — the hardware safety "
            "ceiling. In position mode the shaped level steers the slider "
            "within the stroke zone instead."
        ))
        oe = out_fold.editor_layout
        ms_row = _hbox(0, 8)
        ms_row.addWidget(QLabel("Max speed"))
        maxv = QDoubleSpinBox(); maxv.setRange(0.0, 1.0); maxv.setSingleStep(0.05); maxv.setDecimals(2)
        maxv.setValue(1.0)
        maxv.valueChanged.connect(self._on_handy_motion)
        ms_row.addWidget(maxv)
        ms_row.addStretch(1)
        oe.addLayout(ms_row)

        lay.addWidget(strip)

        self._handy_row = {
            "enabled": enabled, "zone_type": ztype, "ogb_zone": zname,
            "filters": filt, "threshold": thr, "gain": gain, "max_velocity": maxv,
            "strip": strip, "source_fold": src_fold,
            "shaping_fold": shp_fold, "output_fold": out_fold,
        }
        self._update_handy_zone_subtitles()
        return card

    def _update_handy_zone_subtitles(self) -> None:
        """Collapsed-fold summaries derived from the row's widgets."""
        row = self._handy_row
        try:
            zone_name = row["ogb_zone"].currentText().strip() or "—"
            row["source_fold"].set_subtitle(
                f"{row['zone_type'].currentText()} · {zone_name}")
            row["shaping_fold"].set_subtitle(
                f"≥ {float(row['threshold'].value()):.2f}"
                f" · ×{float(row['gain'].value()):.2f}")
            mode = "speed" if self.handy_mode.currentIndex() == 0 else "position"
            row["output_fold"].set_subtitle(
                f"{mode} · max {float(row['max_velocity'].value()):.2f}")
        except RuntimeError:
            pass

    def _refresh_handy_levels(self):
        """Fast tick: charge the routing card's activity rings + arrows.
        Source shows the live zone strength; Shaping/Output mirror the
        router's shaping math (`compute_handy_level`)."""
        row = self._handy_row
        if not row:
            return
        view = self.views.get("Handy")
        if view is not None and not view.isVisible():
            return
        try:
            spec = [(
                row["ogb_zone"].currentText(),
                row["zone_type"].currentText(),
                [fn for fn, cb in row["filters"].items() if cb.isChecked()],
            )]
        except RuntimeError:
            return
        try:
            strengths = self.controller.get_live_zone_strengths(spec)
        except Exception:
            return
        strength = strengths[0] if strengths else 0.0
        try:
            thr = float(row["threshold"].value())
            gain = float(row["gain"].value())
            if not row["enabled"].isChecked() or strength <= thr:
                shaped = 0.0
            else:
                shaped = max(0.0, min(1.0, (strength - thr) * gain))
            drive = shaped * float(row["max_velocity"].value())
            row["strip"].set_levels([strength, shaped, drive])
            row["source_fold"].set_value(strength)
            self._update_handy_zone_subtitles()
        except RuntimeError:
            return

    # ---- refresh ----
    def _refresh_handy_view(self):
        if not self._handy_row:
            return
        self._is_updating_handy = True
        try:
            status = self.controller.get_handy_status()
            self._apply_handy_status(status, full=True)
        finally:
            self._is_updating_handy = False

    def _refresh_handy_status_only(self):
        view = self.views.get("Handy")
        if view is not None and not view.isVisible():
            return
        try:
            status = self.controller.get_handy_status()
        except Exception:
            return
        self._is_updating_handy = True
        try:
            self._apply_handy_status(status, full=False)
        finally:
            self._is_updating_handy = False
        # Fold newly detected zones/sources into the combo when the set
        # changes while the page is open (avatar loaded mid-visit).
        sig = zone_signature(self.controller)
        if sig != getattr(self, "_handy_zone_sig", None):
            self._handy_zone_sig = sig
            self._repopulate_handy_zone_combos()

    def _apply_handy_status(self, status: dict, full: bool):
        extras = status.get("extras") or {}
        if not status.get("available"):
            self.handy_status_label.setText(
                f"Handy: unavailable — {status.get('last_error') or 'requests not installed'}")
            self.handy_status_label.setProperty("role", "alert")
        elif status.get("connected"):
            fw = extras.get("fw_version")
            suffix = f" — fw {fw}" if fw else ""
            # Cloud RTT dominates this backend's feel: surface it (and the
            # request budget) so "it feels laggy" is diagnosable at a glance.
            # The engine reports rtt_ms only while requests are actually
            # flowing, so the whole segment vanishes on an idle link rather
            # than freezing a stale sample on screen.
            rtt = extras.get("rtt_ms")
            if rtt is not None:
                spm = extras.get("sends_per_min") or 0
                suffix += f" · cloud RTT ~{int(rtt)} ms · {int(spm)}/240 req/min"
            if extras.get("fw_update_required"):
                suffix += " (firmware update required!)"
            self.handy_status_label.setText(f"Handy: connected{suffix}")
            self.handy_status_label.setProperty("role", None)
        else:
            err = status.get("last_error") or "not connected"
            self.handy_status_label.setText(f"Handy: disconnected — {err}")
            self.handy_status_label.setProperty("role", "alert")
        self.handy_status_label.style().unpolish(self.handy_status_label)
        self.handy_status_label.style().polish(self.handy_status_label)

        self.handy_auto_check.setChecked(bool(status.get("auto_connect")))
        if not full:
            return
        conn = status.get("connection", {})
        if self.handy_conn_key.text() != conn.get("connection_key", ""):
            self.handy_conn_key.setText(conn.get("connection_key", ""))
        if self.handy_api_key.text() != conn.get("api_key", ""):
            self.handy_api_key.setText(conn.get("api_key", ""))
        motion = status.get("motion", {})
        self.handy_mode.setCurrentIndex(
            1 if motion.get("mode") == "position" else 0)
        self.handy_stroke_min.setValue(float(motion.get("stroke_min", 0.0)))
        self.handy_stroke_max.setValue(float(motion.get("stroke_max", 1.0)))
        self.handy_cmd_hz.setValue(float(motion.get("max_cmd_hz", 4.0)))
        self.handy_invert.setChecked(bool(motion.get("invert", False)))
        row = self._handy_row
        row["max_velocity"].setValue(float(motion.get("max_velocity", 1.0)))
        c = status.get("zone", {})
        row["enabled"].setChecked(bool(c.get("enabled", False)))
        row["zone_type"].setCurrentText(c.get("zone_type", "Orf"))
        self._populate_handy_zone_combo(row["ogb_zone"], c.get("zone_type", "Orf"))
        zone = str(c.get("ogb_zone", ""))
        if zone and row["ogb_zone"].findText(zone) < 0:
            row["ogb_zone"].addItem(zone)
        row["ogb_zone"].setEditText(zone)
        cur_f = set(c.get("filters") or [])
        for fn, cb in row["filters"].items():
            cb.setChecked(fn in cur_f)
        row["threshold"].setValue(float(c.get("threshold", 0.0)))
        row["gain"].setValue(float(c.get("gain", 1.0)))

    # ---- handlers ----
    def _on_handy_auto(self, checked: bool):
        if self._is_updating_handy:
            return
        self.controller.set_handy_auto_connect(bool(checked))

    def _on_handy_connect(self):
        # Two cloud HTTPS round-trips (up to ~20 s on a bad network) — keep
        # them off the Qt thread (which also hosts the Buttplug routing tick).
        self.run_ui_task(
            self.controller.handy_connect_now,
            self._on_handy_connect_done,
            buttons=[self.handy_connect_btn],
        )

    def _on_handy_connect_done(self, result):
        if isinstance(result, Exception):
            self.log_message(f"Handy: connect failed — {result}")
        else:
            self.log_message("Handy: connected" if result
                             else "Handy: connect failed")
        # Status-only: this fires seconds after the click — a full refresh
        # here would rewrite fields the user may be editing by now.
        self._refresh_handy_status_only()

    def _on_handy_conn_apply(self):
        self.controller.set_handy_connection(
            self.handy_conn_key.text().strip(), self.handy_api_key.text().strip())
        self.log_message("Handy: connection settings applied")

    def _on_handy_motion(self, *_):
        if self._is_updating_handy:
            return
        mode = _MODES[self.handy_mode.currentIndex()][0]
        try:
            self.controller.set_handy_motion({
                "mode": mode,
                "stroke_min": float(self.handy_stroke_min.value()),
                "stroke_max": float(self.handy_stroke_max.value()),
                "max_velocity": float(self._handy_row["max_velocity"].value()),
                "max_cmd_hz": float(self.handy_cmd_hz.value()),
                "invert": bool(self.handy_invert.isChecked()),
            })
        except Exception as e:
            self.log_message(f"Handy motion save failed: {e}")

    def _push_handy_zone(self):
        if self._is_updating_handy:
            return
        row = self._handy_row
        if not row:
            return
        cfg = {
            "enabled": row["enabled"].isChecked(),
            "zone_type": row["zone_type"].currentText(),
            "ogb_zone": row["ogb_zone"].currentText(),
            "filters": [fn for fn, cb in row["filters"].items() if cb.isChecked()],
            "threshold": float(row["threshold"].value()),
            "gain": float(row["gain"].value()),
        }
        try:
            self.controller.set_handy_zone(cfg)
        except Exception as e:
            self.log_message(f"Handy zone save failed: {e}")

    def _populate_handy_zone_combo(self, combo: QComboBox, zone_type: str):
        populate_zone_combo(self.controller, combo, zone_type)

    def _on_handy_ztype_changed(self, new_type: str):
        if self._is_updating_handy:
            return
        row = self._handy_row
        if not row:
            return
        on_zone_type_changed(self.controller, row["ogb_zone"], new_type,
                             self._push_handy_zone)

    def _repopulate_handy_zone_combos(self):
        """Page arrival: fold in zones detected while the page was hidden,
        keeping the combo's current selection."""
        row = self._handy_row
        if not row:
            return
        try:
            populate_zone_combo(self.controller, row["ogb_zone"],
                                row["zone_type"].currentText())
        except RuntimeError:
            pass
