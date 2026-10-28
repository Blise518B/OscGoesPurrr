"""The Avatar Remote page's Edit dialog for one control: its label, the kind
of control (what fits the parameter's type), Invert for a Bool, the range
of a slider / stepper, and an Int toggle's or hold button's two values."""

from typing import Any, Dict, Optional

from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox, QFormLayout, QLabel,
    QLineEdit, QSpinBox, QWidget,
)

import param_board as pb
from ui.text_helpers import html_escape

KIND_CHOICES = {
    "Bool": [("Toggle switch", "toggle"), ("Hold button", "button")],
    "Int": [("Number stepper", "int"), ("Slider", "slider"),
            ("Toggle switch", "toggle"), ("Hold button", "button")],
    "Float": [("Slider", "slider")],
}

# An Int toggle / button sends a value instead of true / false; the labels
# say which moment each value belongs to.
_SWITCH_VALUE_LABELS = {
    "toggle": ("Value when ON", "Value when OFF"),
    "button": ("Value while held", "Value on release"),
}


class ControlDialog(QDialog):

    def __init__(self, parent: QWidget, param: str, ptype: str,
                 existing: Optional[Dict[str, Any]] = None, suggested_on: int = 1) -> None:
        super().__init__(parent)
        self.setWindowTitle("Edit control" if existing else "Add control")
        self.setMinimumWidth(360)
        existing = existing or {}
        form = QFormLayout(self)
        form.setSpacing(10)
        head = QLabel(f"<b>{html_escape(param)}</b> <span style='font-weight:400'>({ptype})</span>")
        form.addRow(head)

        self.label_edit = QLineEdit(existing.get("label") or param.split("/")[-1])
        form.addRow("Label", self.label_edit)

        self.kind_combo = QComboBox()
        for text, kind in KIND_CHOICES.get(ptype, [("Slider", "slider")]):
            self.kind_combo.addItem(text, kind)
        idx = self.kind_combo.findData(existing.get("kind"))
        if idx >= 0:
            self.kind_combo.setCurrentIndex(idx)
        form.addRow("Control", self.kind_combo)

        self.invert_check: Optional[QCheckBox] = None
        if ptype == "Bool":
            self.invert_check = QCheckBox("Invert - ON sends the parameter OFF (and the other way)")
            self.invert_check.setChecked(bool(existing.get("invert")))
            form.addRow("", self.invert_check)

        self.min_spin = QDoubleSpinBox(decimals=2, minimum=-9999, maximum=9999)
        self.max_spin = QDoubleSpinBox(decimals=2, minimum=-9999, maximum=9999)
        self.min_spin.setValue(float(existing.get("min", 0)))
        self.max_spin.setValue(float(existing.get("max", 1 if ptype == "Float" else pb.INT_MAX)))
        form.addRow("Min", self.min_spin)
        form.addRow("Max", self.max_spin)

        self._ptype, self._form = ptype, form
        self.on_spin = QSpinBox(minimum=pb.INT_MIN, maximum=pb.INT_MAX)
        self.off_spin = QSpinBox(minimum=pb.INT_MIN, maximum=pb.INT_MAX)
        self.on_spin.setValue(int(existing.get("on", suggested_on)))
        self.off_spin.setValue(int(existing.get("off", 0)))
        self.on_spin.setToolTip(f"What {param} is set to while the control is on.\n"
                                "Several toggles on one number work like VRChat's "
                                "menu: Outfit = 1, Outfit = 2, ...")
        self.off_spin.setToolTip(f"What {param} goes back to (usually 0).")
        form.addRow(_SWITCH_VALUE_LABELS["toggle"][0], self.on_spin)
        form.addRow(_SWITCH_VALUE_LABELS["toggle"][1], self.off_spin)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)
        self.kind_combo.currentIndexChanged.connect(self._update_rows)
        self._update_rows()

    def _int_switch(self) -> bool:
        return self._ptype == "Int" and self.kind_combo.currentData() in ("toggle", "button")

    def _update_rows(self) -> None:
        kind = self.kind_combo.currentData()
        ranged = kind in ("slider", "int")
        self._form.setRowVisible(self.min_spin, ranged)
        self._form.setRowVisible(self.max_spin, ranged)
        switch = self._int_switch()
        self._form.setRowVisible(self.on_spin, switch)
        self._form.setRowVisible(self.off_spin, switch)
        if switch:
            on_text, off_text = _SWITCH_VALUE_LABELS[kind]
            self._form.labelForField(self.on_spin).setText(on_text)
            self._form.labelForField(self.off_spin).setText(off_text)
        self.adjustSize()

    def result_dict(self) -> Dict[str, Any]:
        kind = self.kind_combo.currentData()
        out: Dict[str, Any] = {"label": self.label_edit.text().strip(), "kind": kind}
        if kind in ("slider", "int"):
            out["min"] = self.min_spin.value()
            out["max"] = self.max_spin.value()
        if self._int_switch():
            out["on"] = self.on_spin.value()
            out["off"] = self.off_spin.value()
        if self.invert_check is not None:
            out["invert"] = self.invert_check.isChecked()
        return out
