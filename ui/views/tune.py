"""Tune view — single-motor focused workspace.

After Cut 8 of the chain-inlined-tuning redesign (see
CHAIN_INLINED_TUNING.md § "Phased delivery"), Tune's role is just:

* A sidebar destination that lets the user focus on one motor at a
  time, without toy-bar chrome cluttering the view.
* The same `MotorChainListWidget` Device Routing embeds — including
  the simulator panel (Cut 7d), per-stage mini-graphs (Cut 6c),
  per-stage colour + subtitle (Cut 7f/g), valve indicator (Cut 7h),
  and the optional `▸ Overview` six-trace disclosure (Cut 8a).

Everything that used to live in this file — the pattern preset
player, the source picker, the send-to-toy switch, the big six-trace
graph, the legend, the stages-strip sparklines — is now owned by the
wrapper. The view shrank from ~730 lines to ~140.

Mixin for ui_components.OscGoesPurrrUI."""

from typing import Any, Dict, Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox, QLabel, QPushButton, QVBoxLayout, QWidget,
)

from constants import BTN_HEIGHT_SMALL
from ui.layout_helpers import vbox as _vbox, hbox as _hbox
from ui.widgets import ToggleSwitch
from ui.motor_signal_chain import MotorChainListWidget as _MotorChainListWidget


class TuneMixin:

    # ----------------------------------------------------------
    # View construction
    # ----------------------------------------------------------

    def _build_tune_view(self, parent_layout: QVBoxLayout) -> None:
        """Title row + motor picker + embedded chain widget. The chain
        widget owns everything else (editors, graphs, simulator)."""
        # Title row with the Help Mode toggle — same pattern as
        # Device Routing's header. The toggle is global state shared
        # between the two views (persisted in app_settings); flipping
        # it here also flips badge visibility in Device Routing.
        title_row = QWidget()
        title_lay = _hbox(0, 8)
        title_row.setLayout(title_lay)
        title_lay.addStretch(1)
        title = QLabel("Tune")
        title.setObjectName("viewTitle")
        title.setAlignment(Qt.AlignHCenter)
        title_lay.addWidget(title)
        title_lay.addStretch(1)

        help_toggle = ToggleSwitch("Help Mode")
        help_toggle.setChecked(
            bool(self.controller.get_app_setting("help_mode_enabled", False))
        )

        def on_help_toggled(checked):
            self.controller.set_app_setting("help_mode_enabled", bool(checked))
            self._set_help_badges_visible(bool(checked))

        help_toggle.toggled.connect(on_help_toggled)
        title_lay.addWidget(help_toggle)
        parent_layout.addWidget(title_row)

        # Per-view state — kept on the mixin so handlers can find each
        # other. `chain_widget` is the embedded MotorChainListWidget;
        # rebuilt whenever the motor picker changes selection.
        self._tune_widgets: Dict[str, Any] = {
            "motor_combo": None,
            "chain_container": None,
            "chain_container_lay": None,
            "chain_widget": None,
            "current_selection": None,  # (device_name, motor_idx) or None
        }

        # ---- Toolbar row: motor picker + refresh button ----
        toolbar = QWidget()
        tb_lay = _hbox(0, 12)
        toolbar.setLayout(tb_lay)

        tb_lay.addWidget(QLabel("Motor:"))
        motor_combo = QComboBox()
        motor_combo.setMinimumWidth(220)
        tb_lay.addWidget(motor_combo)
        self._tune_widgets["motor_combo"] = motor_combo

        tb_lay.addStretch(1)
        refresh_btn = QPushButton("Refresh motors")
        refresh_btn.setFixedHeight(BTN_HEIGHT_SMALL)
        refresh_btn.setProperty("role", "secondary")
        refresh_btn.clicked.connect(self._tune_refresh_motor_list)
        tb_lay.addWidget(refresh_btn)
        parent_layout.addWidget(toolbar)

        # ---- Embedded chain widget container ----
        # MotorChainListWidget rebuilds itself when the motor changes,
        # so we keep an empty container here and swap the child on
        # selection change. Stretch=1 so the chain card gets all
        # remaining space below the toolbar.
        chain_container = QWidget()
        chain_container.setObjectName("tuneChainContainer")
        cc_lay = _vbox(0, 0)
        chain_container.setLayout(cc_lay)
        placeholder = QLabel(
            "Select a motor above to open its chain editor."
        )
        placeholder.setProperty("muted", "true")
        placeholder.setAlignment(Qt.AlignHCenter)
        self._repolish(placeholder)
        cc_lay.addWidget(placeholder)
        self._tune_widgets["chain_container"] = chain_container
        self._tune_widgets["chain_container_lay"] = cc_lay
        parent_layout.addWidget(chain_container, 1)

        # ---- Wire handlers ----
        def on_motor_changed(idx: int) -> None:
            data = motor_combo.itemData(idx)
            if data is None:
                self._tune_set_selection(None, None)
                return
            device_name, motor_idx = data
            self._tune_set_selection(device_name, motor_idx)
        motor_combo.currentIndexChanged.connect(on_motor_changed)

        # Initial population.
        self._tune_refresh_motor_list()

    # ----------------------------------------------------------
    # Helpers
    # ----------------------------------------------------------

    def _tune_refresh_motor_list(self) -> None:
        """Rebuild the motor picker from the active profile. Called
        on first build and via the Refresh button. Preserves the
        previous selection if still valid."""
        combo: Optional[QComboBox] = self._tune_widgets.get("motor_combo")
        if combo is None:
            return
        prev = combo.currentData()
        combo.blockSignals(True)
        try:
            combo.clear()
            profile = self.controller.get_active_profile_dict() or {}
            for device_name in sorted(profile.keys(), key=str.lower):
                cfg = profile[device_name]
                motor_count = int(cfg.get("motor_count", 1))
                for motor_idx in range(motor_count):
                    label = f"{device_name} · Motor {motor_idx}"
                    combo.addItem(label, (device_name, motor_idx))
            if combo.count() == 0:
                combo.addItem("(no toys in active profile)", None)
            if prev is not None:
                for i in range(combo.count()):
                    if combo.itemData(i) == prev:
                        combo.setCurrentIndex(i)
                        break
        finally:
            combo.blockSignals(False)
        # Always re-apply selection so the embedded widget matches the
        # combo (handles first build + profile-content changes).
        data = combo.currentData()
        if data is None:
            self._tune_set_selection(None, None)
        else:
            self._tune_set_selection(data[0], data[1])

    def _tune_set_selection(self, device_name: Optional[str],
                            motor_idx: Optional[int]) -> None:
        """Swap the embedded chain widget for the newly-selected
        motor. Tear down the previous widget so its router
        subscriptions are released."""
        self._tune_widgets["current_selection"] = (
            None if device_name is None else (device_name, motor_idx)
        )
        cc_lay: QVBoxLayout = self._tune_widgets["chain_container_lay"]
        if cc_lay is None:
            return
        # Clear existing children.
        while cc_lay.count():
            item = cc_lay.takeAt(0)
            w = item.widget()
            if w is not None:
                w.setParent(None)
                w.deleteLater()
        self._tune_widgets["chain_widget"] = None
        if device_name is None or motor_idx is None:
            placeholder = QLabel(
                "Select a motor above to open its chain editor."
            )
            placeholder.setProperty("muted", "true")
            placeholder.setAlignment(Qt.AlignHCenter)
            self._repolish(placeholder)
            cc_lay.addWidget(placeholder)
            return
        motor_kind = self._tune_lookup_motor_kind(device_name, motor_idx)
        chain_widget = _MotorChainListWidget(
            self, device_name, motor_idx, motor_kind
        )
        cc_lay.addWidget(chain_widget)
        self._tune_widgets["chain_widget"] = chain_widget

    def _tune_lookup_motor_kind(self, device_name: str,
                                motor_idx: int) -> Optional[str]:
        """Resolve `motor_kinds[motor_idx]` from the active profile so
        the embedded chain widget can render the right Output editor
        (linear actuator vs. vibrate motor)."""
        try:
            active = self.controller.get_active_profile_dict() or {}
            dev_cfg = active.get(device_name, {}) if isinstance(active, dict) else {}
            kinds = dev_cfg.get("motor_kinds") if isinstance(dev_cfg, dict) else None
            if isinstance(kinds, (list, tuple)) and 0 <= motor_idx < len(kinds):
                return kinds[motor_idx]
        except Exception:
            pass
        return None
