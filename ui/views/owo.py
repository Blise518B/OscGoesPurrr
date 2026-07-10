"""OWO suit view: connection (game id / suit IP), global sensation frequency,
and per-muscle zone routing for the 10 muscle groups.

Mixin for ui_components.OscGoesPurrrUI. Calls only controller facade methods.
The suit needs the My OWO phone app running ('Scan Game'); this view drives
the PC side via the OWO SDK (pythonnet + OWO.dll, both optional)."""

from typing import Any, Dict

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QComboBox, QCheckBox, QDoubleSpinBox, QFrame, QLabel, QLineEdit,
    QPushButton, QScrollArea, QSpinBox, QVBoxLayout, QWidget,
)

from constants import BTN_HEIGHT_SMALL
from ui.fold_strip import FoldCard, FoldStrip
from ui.layout_helpers import vbox as _vbox, hbox as _hbox
from ui.views._backend_common import (
    on_zone_type_changed, populate_zone_combo, run_connect_now,
    zone_signature,
)
from ui.widgets import (
    ToggleSwitch, Card as _Card, install_rainbow_scrollbars as _install_rainbow_scrollbars,
)

_FILTERS = ("TouchSelf", "TouchOthers", "PenSelf", "PenOthers")
_MUSCLES = [
    "Pectoral_R", "Pectoral_L", "Abdominal_R", "Abdominal_L",
    "Arm_R", "Arm_L", "Dorsal_R", "Dorsal_L", "Lumbar_R", "Lumbar_L",
]


class OwoMixin:

    _is_updating_owo = False
    _owo_muscle_rows: Dict[str, Dict[str, Any]] = {}

    def _build_owo_view(self, parent_layout: QVBoxLayout):
        title = QLabel("OWO Suit")
        title.setObjectName("viewTitle")
        title.setAlignment(Qt.AlignHCenter)
        parent_layout.addWidget(title)

        parent_layout.addWidget(self._muted_label(
            "Maps avatar contacts onto OWO muscle-group sensations.\n"
            "Requires the My OWO phone app on the same Wi-Fi ('Scan Game'), plus "
            "the OWO SDK on this PC (pip install pythonnet + drop OWO.dll into "
            "owo-sdk/). Without those the backend shows as unavailable."
        ))

        # ---- Status / connect ----
        status_card = _Card()
        slay = _vbox(14, 8)
        status_card.setLayout(slay)
        self.owo_status_label = QLabel("OWO: Unknown")
        f = self.owo_status_label.font(); f.setBold(True); f.setPointSize(12)
        self.owo_status_label.setFont(f)
        slay.addWidget(self.owo_status_label)
        row = _hbox(0, 8)
        self.owo_auto_check = ToggleSwitch("Auto Connect (OWO)")
        self.owo_auto_check.toggled.connect(self._on_owo_auto)
        row.addWidget(self.owo_auto_check)
        self.owo_connect_btn = QPushButton("Connect Now")
        self.owo_connect_btn.setMinimumHeight(BTN_HEIGHT_SMALL)
        self.owo_connect_btn.clicked.connect(self._on_owo_connect)
        row.addWidget(self.owo_connect_btn)
        row.addStretch(1)
        slay.addLayout(row)
        parent_layout.addWidget(status_card)

        # ---- Connection / frequency ----
        conn_card = _Card()
        clay = _vbox(14, 6)
        conn_card.setLayout(clay)
        c_hdr = _hbox(0, 6)
        chh = QLabel("Connection"); chh.setObjectName("sectionTitle")
        c_hdr.addWidget(chh)
        c_hdr.addWidget(self._make_help_badge(
            "OWO connection",
            "Pairs with the suit through the My OWO phone app: open the "
            "app on the same Wi-Fi and use 'Scan Game'. <b>Suit IP</b> can "
            "stay blank for auto-discovery; set it if discovery is flaky "
            "on your network. <b>Game ID</b> is optional branding for the "
            "phone app's display."
        ))
        c_hdr.addStretch(1)
        clay.addLayout(c_hdr)
        conn_row = _hbox(0, 8)
        conn_row.addWidget(QLabel("Game ID"))
        self.owo_game_id = QLineEdit(); self.owo_game_id.setFixedWidth(120)
        self.owo_game_id.setPlaceholderText("(optional)")
        conn_row.addWidget(self.owo_game_id)
        conn_row.addWidget(QLabel("Suit IP"))
        self.owo_ip = QLineEdit(); self.owo_ip.setFixedWidth(130)
        self.owo_ip.setPlaceholderText("blank = auto-discover")
        conn_row.addWidget(self.owo_ip)
        conn_apply = QPushButton("Apply"); conn_apply.setMinimumHeight(BTN_HEIGHT_SMALL)
        conn_apply.clicked.connect(self._on_owo_conn_apply)
        conn_row.addWidget(conn_apply)
        conn_row.addStretch(1)
        clay.addLayout(conn_row)
        freq_row = _hbox(0, 8)
        freq_row.addWidget(QLabel("Sensation frequency"))
        self.owo_freq = QSpinBox(); self.owo_freq.setRange(0, 100)
        self.owo_freq.valueChanged.connect(self._on_owo_freq)
        freq_row.addWidget(self.owo_freq)
        freq_row.addWidget(self._make_help_badge(
            "Sensation frequency",
            "The frequency parameter (0–100) of the continuous sensation "
            "the suit plays, applied to all muscles. Lower values feel "
            "like slow thumps, higher like a dense buzz — intensity is "
            "controlled per-muscle below, this only sets the texture."
        ))
        freq_row.addStretch(1)
        clay.addLayout(freq_row)
        parent_layout.addWidget(conn_card)

        # ---- Muscles ----
        m_card = _Card(dark_bg=True)
        mlay = _vbox(10, 6)
        m_card.setLayout(mlay)
        mh = QLabel("Muscle groups"); mh.setObjectName("sectionTitle")
        mlay.addWidget(mh)
        scroll = QScrollArea(); scroll.setWidgetResizable(True)
        _install_rainbow_scrollbars(scroll)
        inner = QWidget()
        inner_lay = _vbox(6, 8)
        inner.setLayout(inner_lay)
        self._owo_muscle_rows = {}
        for name in _MUSCLES:
            inner_lay.addWidget(self._build_owo_muscle_card(name))
        inner_lay.addStretch(1)
        scroll.setWidget(inner)
        mlay.addWidget(scroll, 1)
        parent_layout.addWidget(m_card, 1)

        self._refresh_owo_view()
        self._owo_timer = QTimer(self.window)
        self._owo_timer.setInterval(1500)
        self._owo_timer.timeout.connect(self._refresh_owo_status_only)
        self._owo_timer.start()

        # Fast tick driving the muscle cards' activity rings + arrows.
        # Short-circuits while the view is hidden.
        self._owo_level_timer = QTimer(self.window)
        self._owo_level_timer.setInterval(100)
        self._owo_level_timer.timeout.connect(self._refresh_owo_levels)
        self._owo_level_timer.start()

    def _build_owo_muscle_card(self, name: str) -> QFrame:
        """One muscle as a fold strip — Source → Shaping → Output — in
        the Device Routing chain's design language (collapsible folds
        joined by arrows, activity rings charged by the live zone
        strength; see ui/fold_strip.py)."""
        card = _Card(); card.setMaximumWidth(860)
        lay = _vbox(10, 6); card.setLayout(lay)
        row1 = _hbox(0, 8)
        t = QLabel(name.replace("_", " ")); tf = t.font(); tf.setBold(True); t.setFont(tf)
        t.setMinimumWidth(110)
        row1.addWidget(t)
        enabled = ToggleSwitch("Enabled")
        enabled.toggled.connect(lambda _=False, n=name: self._push_owo_muscle(n))
        row1.addWidget(enabled)
        row1.addStretch(1)
        lay.addLayout(row1)

        strip = FoldStrip()

        # ---- Source fold ----
        src_fold = strip.add_fold(FoldCard("source", "Source", show_value=True))
        src_fold.add_header_widget(self._make_help_badge(
            "Source",
            "Which avatar contact drives this muscle: an OGB zone (or "
            "synthetic SPS source) plus the interaction filters that "
            "count. The live number and the glowing ring show the current "
            "0–1 contact strength."
        ))
        se = src_fold.editor_layout
        st_row = _hbox(0, 8)
        st_row.addWidget(QLabel("Type"))
        ztype = QComboBox(); ztype.addItems(["Orf", "Pen"])
        ztype.currentTextChanged.connect(
            lambda t, n=name: self._on_owo_ztype_changed(n, t))
        st_row.addWidget(ztype)
        st_row.addStretch(1)
        se.addLayout(st_row)
        sz_row = _hbox(0, 8)
        sz_row.addWidget(QLabel("Zone"))
        zname = QComboBox(); zname.setEditable(True); zname.setMinimumWidth(130)
        zname.editTextChanged.connect(lambda _=None, n=name: self._push_owo_muscle(n))
        sz_row.addWidget(zname, 1)
        se.addLayout(sz_row)
        filt: Dict[str, QCheckBox] = {}
        for pair in (_FILTERS[:2], _FILTERS[2:]):
            fr = _hbox(0, 8)
            for fn in pair:
                cb = QCheckBox(fn)
                cb.toggled.connect(lambda _=False, n=name: self._push_owo_muscle(n))
                fr.addWidget(cb); filt[fn] = cb
            fr.addStretch(1)
            se.addLayout(fr)

        # ---- Shaping fold ----
        shp_fold = strip.add_fold(FoldCard("shaping", "Shaping"))
        shp_fold.add_header_widget(self._make_help_badge(
            "Shaping",
            "Strength below the threshold outputs nothing; above it, "
            "(strength − threshold) × gain sets the muscle level. Use the "
            "threshold to ignore grazing contact and the gain to control "
            "how fast intensity climbs once past it."
        ))
        he = shp_fold.editor_layout
        th_row = _hbox(0, 8)
        th_row.addWidget(QLabel("Threshold"))
        thr = QDoubleSpinBox(); thr.setRange(0.0, 1.0); thr.setSingleStep(0.05); thr.setDecimals(2)
        thr.valueChanged.connect(lambda _=None, n=name: self._push_owo_muscle(n))
        th_row.addWidget(thr)
        th_row.addWidget(QLabel("Gain"))
        gain = QDoubleSpinBox(); gain.setRange(0.0, 5.0); gain.setSingleStep(0.1); gain.setDecimals(2)
        gain.valueChanged.connect(lambda _=None, n=name: self._push_owo_muscle(n))
        th_row.addWidget(gain)
        th_row.addStretch(1)
        he.addLayout(th_row)

        # ---- Output fold ----
        out_fold = strip.add_fold(FoldCard("output", "Output"))
        out_fold.add_header_widget(self._make_help_badge(
            "Output",
            "<b>Max intensity</b> scales the shaped 0–1 level onto the "
            "muscle's 0–100 sensation intensity — the hard ceiling for "
            "this muscle no matter how strong the contact gets."
        ))
        oe = out_fold.editor_layout
        mi_row = _hbox(0, 8)
        mi_row.addWidget(QLabel("Max intensity"))
        maxi = QSpinBox(); maxi.setRange(0, 100)
        maxi.valueChanged.connect(lambda _=None, n=name: self._push_owo_muscle(n))
        mi_row.addWidget(maxi)
        mi_row.addStretch(1)
        oe.addLayout(mi_row)

        lay.addWidget(strip)

        self._owo_muscle_rows[name] = {
            "enabled": enabled, "zone_type": ztype, "ogb_zone": zname,
            "filters": filt, "threshold": thr, "gain": gain, "max_intensity": maxi,
            "strip": strip, "source_fold": src_fold,
            "shaping_fold": shp_fold, "output_fold": out_fold,
        }
        self._update_owo_muscle_subtitles(self._owo_muscle_rows[name])
        return card

    def _update_owo_muscle_subtitles(self, row: Dict[str, Any]) -> None:
        """Collapsed-fold summaries derived from the row's widgets."""
        try:
            zone_name = row["ogb_zone"].currentText().strip() or "—"
            row["source_fold"].set_subtitle(
                f"{row['zone_type'].currentText()} · {zone_name}")
            row["shaping_fold"].set_subtitle(
                f"≥ {float(row['threshold'].value()):.2f}"
                f" · ×{float(row['gain'].value()):.2f}")
            row["output_fold"].set_subtitle(
                f"max {int(row['max_intensity'].value())}")
        except RuntimeError:
            pass

    def _refresh_owo_levels(self):
        """Fast tick: charge the muscle cards' activity rings + arrows.
        Source shows the live zone strength; Shaping/Output mirror the
        router's shaping math (`compute_muscle_intensity`)."""
        rows = self._owo_muscle_rows
        if not rows:
            return
        view = self.views.get("OWO")
        if view is not None and not view.isVisible():
            return
        order = list(rows.keys())
        specs = []
        for nm in order:
            row = rows[nm]
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
        for nm, strength in zip(order, strengths):
            row = rows[nm]
            try:
                thr = float(row["threshold"].value())
                gain = float(row["gain"].value())
                if not row["enabled"].isChecked() or strength <= thr:
                    shaped = 0.0
                else:
                    shaped = max(0.0, min(1.0, (strength - thr) * gain))
                drive = shaped * (int(row["max_intensity"].value()) / 100.0)
                row["strip"].set_levels([strength, shaped, drive])
                row["source_fold"].set_value(strength)
                self._update_owo_muscle_subtitles(row)
            except RuntimeError:
                continue

    # ---- refresh ----
    def _refresh_owo_view(self):
        if not self._owo_muscle_rows:
            return
        self._is_updating_owo = True
        try:
            status = self.controller.get_owo_status()
            self._apply_owo_status(status, full=True)
        finally:
            self._is_updating_owo = False

    def _refresh_owo_status_only(self):
        view = self.views.get("OWO")
        if view is not None and not view.isVisible():
            return
        try:
            status = self.controller.get_owo_status()
        except Exception:
            return
        self._is_updating_owo = True
        try:
            self._apply_owo_status(status, full=False)
        finally:
            self._is_updating_owo = False
        # Fold newly detected zones/sources into the combos when the set
        # changes while the page is open (avatar loaded mid-visit).
        sig = zone_signature(self.controller)
        if sig != getattr(self, "_owo_zone_sig", None):
            self._owo_zone_sig = sig
            self._repopulate_owo_zone_combos()

    def _apply_owo_status(self, status: dict, full: bool):
        if not status.get("available"):
            self.owo_status_label.setText(
                f"OWO: unavailable — {status.get('last_error') or 'SDK not loaded'}")
            self.owo_status_label.setProperty("role", "alert")
        elif status.get("connected"):
            self.owo_status_label.setText("OWO: connected")
            self.owo_status_label.setProperty("role", None)
        else:
            err = status.get("last_error") or "not connected"
            self.owo_status_label.setText(f"OWO: disconnected — {err}")
            self.owo_status_label.setProperty("role", "alert")
        self.owo_status_label.style().unpolish(self.owo_status_label)
        self.owo_status_label.style().polish(self.owo_status_label)

        self.owo_auto_check.setChecked(bool(status.get("auto_connect")))
        if not full:
            return
        conn = status.get("connection", {})
        if self.owo_game_id.text() != conn.get("game_id", ""):
            self.owo_game_id.setText(conn.get("game_id", ""))
        if self.owo_ip.text() != conn.get("ip", ""):
            self.owo_ip.setText(conn.get("ip", ""))
        self.owo_freq.setValue(int(status.get("frequency", 100)))
        muscles = status.get("muscles", {})
        for name, row in self._owo_muscle_rows.items():
            c = muscles.get(name, {})
            row["enabled"].setChecked(bool(c.get("enabled", False)))
            row["zone_type"].setCurrentText(c.get("zone_type", "Orf"))
            self._populate_owo_zone_combo(row["ogb_zone"], c.get("zone_type", "Orf"))
            zone = str(c.get("ogb_zone", ""))
            if zone and row["ogb_zone"].findText(zone) < 0:
                row["ogb_zone"].addItem(zone)
            row["ogb_zone"].setEditText(zone)
            cur_f = set(c.get("filters") or [])
            for fn, cb in row["filters"].items():
                cb.setChecked(fn in cur_f)
            row["threshold"].setValue(float(c.get("threshold", 0.0)))
            row["gain"].setValue(float(c.get("gain", 1.0)))
            row["max_intensity"].setValue(int(c.get("max_intensity", 100)))

    # ---- handlers ----
    def _on_owo_auto(self, checked: bool):
        if self._is_updating_owo:
            return
        self.controller.set_owo_auto_connect(bool(checked))

    def _on_owo_connect(self):
        # The SDK's AutoConnect LAN scan blocks for seconds — keep it off
        # the Qt thread (which also hosts the Buttplug routing tick).
        run_connect_now(
            self, "OWO", self.controller.owo_connect_now,
            self._refresh_owo_status_only,
            buttons=[self.owo_connect_btn],
        )

    def _on_owo_conn_apply(self):
        self.controller.set_owo_connection(
            self.owo_game_id.text().strip(), self.owo_ip.text().strip())
        self.log_message("OWO: connection settings applied")

    def _on_owo_freq(self, *_):
        if self._is_updating_owo:
            return
        self.controller.set_owo_frequency(int(self.owo_freq.value()))

    def _push_owo_muscle(self, name: str):
        if self._is_updating_owo:
            return
        row = self._owo_muscle_rows.get(name)
        if not row:
            return
        cfg = {
            "enabled": row["enabled"].isChecked(),
            "zone_type": row["zone_type"].currentText(),
            "ogb_zone": row["ogb_zone"].currentText(),
            "filters": [fn for fn, cb in row["filters"].items() if cb.isChecked()],
            "threshold": float(row["threshold"].value()),
            "gain": float(row["gain"].value()),
            "max_intensity": int(row["max_intensity"].value()),
        }
        try:
            self.controller.set_owo_muscle(name, cfg)
        except Exception as e:
            self.log_message(f"OWO muscle save failed: {e}")

    def _populate_owo_zone_combo(self, combo: QComboBox, zone_type: str):
        populate_zone_combo(self.controller, combo, zone_type)

    def _on_owo_ztype_changed(self, name: str, new_type: str):
        if self._is_updating_owo:
            return
        row = self._owo_muscle_rows.get(name)
        if not row:
            return
        on_zone_type_changed(self.controller, row["ogb_zone"], new_type,
                             lambda: self._push_owo_muscle(name))

    def _repopulate_owo_zone_combos(self):
        """Page arrival: fold in zones detected while the page was hidden,
        keeping each combo's current selection."""
        for row in self._owo_muscle_rows.values():
            try:
                populate_zone_combo(self.controller, row["ogb_zone"],
                                    row["zone_type"].currentText())
            except RuntimeError:
                continue
