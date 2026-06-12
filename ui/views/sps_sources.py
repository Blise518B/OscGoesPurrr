"""SPS Sources view — build user-defined synthetic SPS sources.

Mixin for ui_components.OscGoesPurrrUI. A synthetic source assembles raw
VRChat contact receivers into a single SPS-style signal:

  * proximity  — one or more proximity receivers (max-wins)
  * activation — binary gate contacts (OR); proximity only counts while
                 at least one is firing
  * velocity   — binary on-enter contacts; while any fires, the output is
                 multiplied by the shared multiplier
  * max value  — clamp on the raw proximity before the multiplier

The result shows up in the Device Routing zone picker and the bHaptics
Cross-Routing picker, so it routes exactly like an auto-detected SPS zone.
All persistence + math goes through the controller facade; this file only
draws widgets and forwards primitive values (Demeter rule).
"""

from typing import Any, Dict, List

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QLabel, QPushButton, QLineEdit,
    QFrame, QScrollArea, QComboBox, QDoubleSpinBox,
)

from constants import *
from utilities import strip_param_prefix
from ui.layout_helpers import vbox as _vbox, hbox as _hbox
from ui.osc_variable_picker import open_osc_variable_picker
from ui.widgets import (
    ToggleSwitch,
    Card as _Card,
    install_rainbow_scrollbars as _install_rainbow_scrollbars,
)


class SpsSourcesMixin:

    _is_updating_sps_sources = False
    _sps_source_rows: List[Dict[str, Any]] = []

    # ----------------------------------------------------------
    # View
    # ----------------------------------------------------------

    def _build_sps_sources_view(self, parent_layout: QVBoxLayout):
        parent_layout.addWidget(self._muted_label(
            "Build a synthetic SPS source from raw VRChat contact receivers. "
            "A proximity receiver provides the signal; 'activation' contacts "
            "gate it to a specific spot (the signal only counts while one is "
            "firing); 'velocity' on-enter contacts boost the output by the "
            "multiplier; and the max value caps the raw proximity. Each source "
            "becomes selectable in Device Routing and bHaptics Cross-Routing."
        ))

        top_row = _hbox(0, 8)
        top_row.addStretch(1)
        refresh_btn = QPushButton("Refresh")
        refresh_btn.setMinimumHeight(BTN_HEIGHT_SMALL)
        refresh_btn.setToolTip("Reload the source list from disk.")
        refresh_btn.clicked.connect(self._rebuild_sps_sources_entries)
        top_row.addWidget(refresh_btn)
        add_btn = QPushButton("+ Add source")
        add_btn.setMinimumHeight(BTN_HEIGHT_SMALL)
        add_btn.clicked.connect(self._on_sps_source_add)
        top_row.addWidget(add_btn)
        parent_layout.addLayout(top_row)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        _install_rainbow_scrollbars(scroll)
        inner = QWidget()
        self.sps_sources_list_layout = _vbox(8, 8)
        inner.setLayout(self.sps_sources_list_layout)
        scroll.setWidget(inner)
        parent_layout.addWidget(scroll, 1)

        # Live readout pump — only does work while this view is visible.
        self._sps_values_timer = QTimer()
        self._sps_values_timer.setInterval(150)
        self._sps_values_timer.timeout.connect(self._refresh_sps_source_values)
        self._sps_values_timer.start()

        self._rebuild_sps_sources_entries()

    # ----------------------------------------------------------
    # List rebuild
    # ----------------------------------------------------------

    def _rebuild_sps_sources_entries(self):
        """Tear down + rebuild the source cards from the persisted registry."""
        if not hasattr(self, "sps_sources_list_layout"):
            return
        self._is_updating_sps_sources = True
        try:
            self._sps_source_rows = []
            while self.sps_sources_list_layout.count():
                item = self.sps_sources_list_layout.takeAt(0)
                w = item.widget()
                if w is not None:
                    w.deleteLater()
            sources = self.controller.get_sps_sources()
            if not sources:
                self.sps_sources_list_layout.addWidget(self._muted_label(
                    "No sources yet. Click '+ Add source' to create one, then "
                    "fill in the contact parameter names from your avatar."
                ))
            else:
                for idx, src in enumerate(sources):
                    card = self._build_sps_source_card(idx, src)
                    self.sps_sources_list_layout.addWidget(card, 0, Qt.AlignLeft)
            self.sps_sources_list_layout.addStretch(1)
        finally:
            self._is_updating_sps_sources = False

    def _build_sps_source_card(self, idx: int, src: Dict[str, Any]) -> QFrame:
        card = _Card()
        card.setMaximumWidth(680)
        lay = _vbox(12, 8)
        card.setLayout(lay)

        # --- Row 1: enable + name + live readout + delete ---
        row1 = _hbox(0, 8)
        enable_cb = ToggleSwitch("On")
        enable_cb.setChecked(bool(src.get("enabled", True)))
        enable_cb.toggled.connect(lambda _v, i=idx: self._push_sps_source(i))
        row1.addWidget(enable_cb)

        name_edit = QLineEdit(str(src.get("name", "")))
        name_edit.setPlaceholderText("Source name")
        name_edit.setMinimumWidth(180)
        name_edit.editingFinished.connect(lambda i=idx: self._push_sps_source(i))
        row1.addWidget(name_edit, 1)

        value_label = QLabel("live: 0.00")
        value_label.setProperty("muted", "true")
        row1.addWidget(value_label)

        del_btn = QPushButton("Delete")
        del_btn.setMinimumHeight(BTN_HEIGHT_SMALL)
        del_btn.clicked.connect(lambda _=False, i=idx: self._on_sps_source_delete(i))
        row1.addWidget(del_btn)
        lay.addLayout(row1)

        # --- Row 2: type + max value + multiplier ---
        row2 = _hbox(0, 8)
        row2.addWidget(QLabel("Type"))
        type_combo = QComboBox()
        type_combo.addItem("Orifice (receiver)", "Orf")
        type_combo.addItem("Penetrator", "Pen")
        type_combo.setCurrentIndex(1 if src.get("zone_type") == "Pen" else 0)
        type_combo.currentIndexChanged.connect(
            lambda _i, i=idx: self._push_sps_source(i)
        )
        row2.addWidget(type_combo)
        row2.addSpacing(12)

        row2.addWidget(QLabel("Max value"))
        max_spin = QDoubleSpinBox()
        max_spin.setRange(0.0, 1.0)
        max_spin.setSingleStep(0.05)
        max_spin.setDecimals(2)
        try:
            max_spin.setValue(float(src.get("max_value", 1.0)))
        except (TypeError, ValueError):
            max_spin.setValue(1.0)
        max_spin.setToolTip("Ceiling clamp on the raw proximity, before the "
                            "velocity multiplier.")
        max_spin.valueChanged.connect(lambda _v, i=idx: self._push_sps_source(i))
        row2.addWidget(max_spin)
        row2.addWidget(self._make_help_badge(
            "Max value",
            "Ceiling clamp on the raw proximity signal, applied <b>before</b> "
            "the velocity multiplier. Use it when a receiver saturates too "
            "early — e.g. cap at 0.8 so only the deepest contact reads as "
            "full strength."
        ))
        row2.addSpacing(12)

        row2.addWidget(QLabel("Velocity ×"))
        mult_spin = QDoubleSpinBox()
        mult_spin.setRange(0.0, 10.0)
        mult_spin.setSingleStep(0.1)
        mult_spin.setDecimals(2)
        try:
            mult_spin.setValue(float(src.get("multiplier", 1.0)))
        except (TypeError, ValueError):
            mult_spin.setValue(1.0)
        mult_spin.setToolTip("Output is multiplied by this while ANY velocity "
                             "contact is firing.")
        mult_spin.valueChanged.connect(lambda _v, i=idx: self._push_sps_source(i))
        row2.addWidget(mult_spin)
        row2.addWidget(self._make_help_badge(
            "Velocity multiplier",
            "While ANY of the Velocity contacts below is firing, the "
            "source's output is multiplied by this. >1 boosts the signal "
            "during fast/entering contact; <1 dampens it; 1.0 disables the "
            "effect."
        ))
        row2.addStretch(1)
        lay.addLayout(row2)

        # --- Rows 3-5: contact lists (comma-separated bare param names) ---
        prox_edit = self._sps_contact_row(
            lay, "Proximity", src.get("proximity"),
            "Comma-separated receiver names, e.g. Contact/GSpotProx",
            idx,
            help_text=(
                "Proximity contacts",
                "The analog 0–1 signal. List one or more proximity receiver "
                "parameters from your avatar (comma-separated); when several "
                "fire at once, the <b>highest</b> value wins."
            ))
        act_edit = self._sps_contact_row(
            lay, "Activation", src.get("activation"),
            "Binary gate contacts (OR). Empty = always on.",
            idx,
            help_text=(
                "Activation contacts",
                "Binary gate. The proximity signal only counts while at "
                "least one of these contacts is firing — use it to pin the "
                "source to a very specific spot. Leave empty for "
                "always-on."
            ))
        vel_edit = self._sps_contact_row(
            lay, "Velocity", src.get("velocity"),
            "Binary on-enter contacts that apply the multiplier.",
            idx,
            help_text=(
                "Velocity contacts",
                "Binary on-enter contacts. While any of them fires, the "
                "output is multiplied by <b>Velocity ×</b> above — a cheap "
                "way to reward fast or fresh contact with a stronger "
                "signal."
            ))

        self._sps_source_rows.append({
            "orig_name": str(src.get("name", "")),
            "enabled": enable_cb,
            "name": name_edit,
            "type": type_combo,
            "max_value": max_spin,
            "multiplier": mult_spin,
            "proximity": prox_edit,
            "activation": act_edit,
            "velocity": vel_edit,
            "value_label": value_label,
        })
        return card

    def _sps_contact_row(self, parent_lay, label, value, placeholder, idx,
                         help_text=None):
        row = _hbox(0, 8)
        lbl = QLabel(label)
        lbl.setMinimumWidth(80)
        row.addWidget(lbl)
        if help_text is not None:
            row.addWidget(self._make_help_badge(*help_text))
        edit = QLineEdit(self._fmt_contacts(value))
        edit.setPlaceholderText(placeholder)
        edit.editingFinished.connect(lambda i=idx: self._push_sps_source(i))
        row.addWidget(edit, 1)
        pick = QPushButton("+")
        pick.setFixedHeight(BTN_HEIGHT_SMALL)
        pick.setProperty("role", "secondary")
        pick.setToolTip("Pick from live OSC parameters")
        pick.clicked.connect(
            lambda _=False, e=edit, i=idx: self._pick_sps_contact(e, i)
        )
        row.addWidget(pick)
        parent_lay.addLayout(row)
        return edit

    def _pick_sps_contact(self, edit, idx: int):
        """Open the shared OSC variable picker and append the chosen
        parameter to this contact field (comma-separated, de-duped)."""
        def on_pick(addr):
            cleaned = strip_param_prefix(addr)
            if not cleaned:
                return
            existing = self._parse_contacts(edit.text())
            if cleaned not in existing:
                existing.append(cleaned)
            self._is_updating_sps_sources = True
            try:
                edit.setText(", ".join(existing))
            finally:
                self._is_updating_sps_sources = False
            self._push_sps_source(idx)

        open_osc_variable_picker(
            self.window, on_pick, allow_wildcards=False,
            subtitle="Pick the contact receiver parameter (double-click to "
                     "add) or enter one manually.",
        )

    # ----------------------------------------------------------
    # Mutations
    # ----------------------------------------------------------

    def _on_sps_source_add(self):
        name = self._unique_sps_name()
        self.controller.add_or_update_sps_source({
            "name": name, "zone_type": "Orf",
            "max_value": 1.0, "multiplier": 1.0, "enabled": True,
        })
        self._rebuild_sps_sources_entries()

    def _on_sps_source_delete(self, idx: int):
        if idx < 0 or idx >= len(self._sps_source_rows):
            return
        self.controller.delete_sps_source(self._sps_source_rows[idx]["orig_name"])
        self._rebuild_sps_sources_entries()

    def _push_sps_source(self, idx: int):
        """Gather one card's widgets and persist it. Renames (name field
        changed) delete the old keyed record first; a blank or colliding
        new name reverts to the original so we never clobber a sibling."""
        if self._is_updating_sps_sources:
            return
        if idx < 0 or idx >= len(self._sps_source_rows):
            return
        row = self._sps_source_rows[idx]
        orig = row["orig_name"]
        name = row["name"].text().strip()

        if name != orig:
            existing = {s.get("name") for s in self.controller.get_sps_sources()}
            if not name or name in existing:
                self._is_updating_sps_sources = True
                try:
                    row["name"].setText(orig)
                finally:
                    self._is_updating_sps_sources = False
                name = orig

        defn = {
            "name": name,
            "zone_type": row["type"].currentData() or "Orf",
            "proximity": self._parse_contacts(row["proximity"].text()),
            "activation": self._parse_contacts(row["activation"].text()),
            "velocity": self._parse_contacts(row["velocity"].text()),
            "multiplier": float(row["multiplier"].value()),
            "max_value": float(row["max_value"].value()),
            "enabled": row["enabled"].isChecked(),
        }
        if orig and name != orig:
            self.controller.delete_sps_source(orig)
        self.controller.add_or_update_sps_source(defn)
        row["orig_name"] = name

    # ----------------------------------------------------------
    # Live readout
    # ----------------------------------------------------------

    def _refresh_sps_source_values(self):
        if not self._sps_source_rows:
            return
        try:
            if (self.main_stack is None
                    or self.main_stack.currentWidget() is not self.views.get("SPS Sources")):
                return
        except Exception:
            return
        try:
            values = self.controller.get_sps_source_values()
        except Exception:
            return
        for row in self._sps_source_rows:
            lbl = row.get("value_label")
            if lbl is None:
                continue
            v = values.get(row["orig_name"], 0.0)
            lbl.setText(f"live: {v:.2f}")

    # ----------------------------------------------------------
    # Helpers
    # ----------------------------------------------------------

    def _unique_sps_name(self, base: str = "New Source") -> str:
        existing = {s.get("name") for s in self.controller.get_sps_sources()}
        if base not in existing:
            return base
        i = 2
        while f"{base} {i}" in existing:
            i += 1
        return f"{base} {i}"

    @staticmethod
    def _fmt_contacts(value) -> str:
        if isinstance(value, str):
            return value
        if isinstance(value, (list, tuple)):
            return ", ".join(str(v) for v in value)
        return ""

    @staticmethod
    def _parse_contacts(text: str) -> List[str]:
        return [c.strip() for c in (text or "").replace(";", ",").split(",")
                if c.strip()]
