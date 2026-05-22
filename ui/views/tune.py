"""Tune view (Phase 3): live multi-curve graph + Mix controls for a
single selected motor, with a Simulated/Live source picker and a
Send-to-toy safety switch.

Mixin for ui_components.OscGoesPurrrUI. Relies on attributes
initialised by OscGoesPurrrUI.__init__ (self.controller,
self.invoker, etc.) plus the methods inherited from DeviceFrameMixin
(_build_mix_subcard) and HelpMode bits."""

from typing import Any, Dict, List, Optional, Tuple

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QFrame, QHBoxLayout, QLabel, QPushButton,
    QScrollArea, QSizePolicy, QVBoxLayout, QWidget,
)

from constants import (
    BTN_HEIGHT_SMALL, COLOR_ALERT, COLOR_INPUT_BG, COLOR_SUCCESS, COLOR_TEXT,
)

from ui.layout_helpers import vbox as _vbox, hbox as _hbox
from ui.widgets import Card as _Card, ToggleSwitch
from ui.trace_graph import TraceGraph as _TraceGraph


# Six traces in display order. Each tuple is
# (id, label, color, default_visible, style_dict).
# - Raw values: solid, light tints.
# - Shaped values: dashed so they stay visible even when overlapping
#   the raw trace exactly (default gain=1, curve=linear makes shaped
#   numerically equal to raw).
# - Post-mix: dotted, off by default — overlaps Final when smoothing
#   is light, but the dot pattern shows what smoothing strips.
# - Final: solid bold green ("what the toy actually feels").
_TUNE_TRACES: List[Tuple[str, str, str, bool, dict]] = [
    ("d_raw",    "Raw depth",       "#88AAFF", True,  {"width": 1.6}),
    ("s_raw",    "Raw speed",       "#FFBB88", True,  {"width": 1.6}),
    ("d_shaped", "Depth influence", "#3366FF", True,  {"width": 1.8, "dash": "dash"}),
    ("s_shaped", "Speed influence", "#FF7733", True,  {"width": 1.8, "dash": "dash"}),
    ("mixed",    "Post-mix",        "#C040FF", False, {"width": 1.6, "dash": "dot"}),
    ("out",      "Final output",    COLOR_SUCCESS, True, {"width": 2.4}),
]


_SOURCE_SIMULATED = "simulated"
_SOURCE_LIVE = "live"


class TuneMixin:

    # ----------------------------------------------------------
    # View construction
    # ----------------------------------------------------------

    def _build_tune_view(self, parent_layout: QVBoxLayout):
        # Title row — Tune view doesn't get a Help Mode toggle yet; the
        # Phase 1 toggle in Device Routing's header controls the global
        # state for both views, but Tune's controls don't have badges
        # wired yet (incremental — badges land in a follow-up).
        title = QLabel("Tune")
        title.setObjectName("viewTitle")
        title.setAlignment(Qt.AlignHCenter)
        parent_layout.addWidget(title)

        # Cache widget refs so update_tune_trace and the source/motor
        # callbacks can find them later. Init on first view build.
        self._tune_widgets: Dict[str, Any] = {
            "graph": None,
            "motor_combo": None,
            "source_combo": None,
            "pattern_combo": None,
            "send_to_toy_toggle": None,
            "pattern_row": None,
            "send_row": None,
            "mix_container": None,
            "mix_container_lay": None,
            "trace_checkboxes": {},
            "current_selection": None,  # (device_name, motor_idx) or None
        }

        # ---- Toolbar row: motor picker + source picker ----
        toolbar = QWidget()
        tb_lay = _hbox(0, 12)
        toolbar.setLayout(tb_lay)

        tb_lay.addWidget(QLabel("Motor:"))
        motor_combo = QComboBox()
        motor_combo.setMinimumWidth(220)
        tb_lay.addWidget(motor_combo)
        self._tune_widgets["motor_combo"] = motor_combo

        tb_lay.addSpacing(20)
        tb_lay.addWidget(QLabel("Source:"))
        source_combo = QComboBox()
        source_combo.addItems(["Simulated", "Live VRChat"])
        tb_lay.addWidget(source_combo)
        self._tune_widgets["source_combo"] = source_combo

        tb_lay.addStretch(1)
        refresh_btn = QPushButton("Refresh motors")
        refresh_btn.setFixedHeight(BTN_HEIGHT_SMALL)
        refresh_btn.setProperty("role", "secondary")
        refresh_btn.clicked.connect(self._tune_refresh_motor_list)
        tb_lay.addWidget(refresh_btn)

        parent_layout.addWidget(toolbar)

        # ---- Simulated-only row: pattern picker + send-to-toy switch ----
        pattern_row = QWidget()
        pr_lay = _hbox(0, 12)
        pattern_row.setLayout(pr_lay)
        pr_lay.addWidget(QLabel("Pattern:"))
        pattern_combo = QComboBox()
        for pat in self.controller.tune_list_patterns():
            pattern_combo.addItem(self._tune_pattern_label(pat), pat)
        pr_lay.addWidget(pattern_combo)
        play_btn = QPushButton("▶ Play")
        play_btn.setFixedHeight(BTN_HEIGHT_SMALL)
        play_btn.setProperty("role", "secondary")
        pr_lay.addWidget(play_btn)
        stop_btn = QPushButton("■ Stop")
        stop_btn.setFixedHeight(BTN_HEIGHT_SMALL)
        stop_btn.setProperty("role", "secondary")
        pr_lay.addWidget(stop_btn)
        pr_lay.addStretch(1)
        self._tune_widgets["pattern_combo"] = pattern_combo
        self._tune_widgets["pattern_row"] = pattern_row
        parent_layout.addWidget(pattern_row)

        send_row = QWidget()
        sr_lay = _hbox(0, 12)
        send_row.setLayout(sr_lay)
        send_toggle = ToggleSwitch(
            "Send to toy  (OFF = graph only, no physical feedback)"
        )
        send_toggle.setChecked(
            bool(self.controller.tune_get_status().get("send_to_toy", False))
        )
        sr_lay.addWidget(send_toggle)
        sr_lay.addStretch(1)
        self._tune_widgets["send_to_toy_toggle"] = send_toggle
        self._tune_widgets["send_row"] = send_row
        parent_layout.addWidget(send_row)

        # Hint: simulator injects directly into the mixer's d_raw stage
        # for the selected motor only — bypasses zones, custom OSC
        # addresses, and the parameter store. Lets the user test mixer
        # behaviour with a known input without configuring zones.
        hint = QLabel(
            "Simulator injects its value directly into the selected "
            "motor's <b>d_raw</b> — no zone configuration required. "
            "Other motors are unaffected."
        )
        hint.setWordWrap(True)
        hint.setProperty("muted", "true")
        hint.setTextFormat(Qt.RichText)
        self._repolish(hint)
        self._tune_widgets["hint"] = hint
        parent_layout.addWidget(hint)

        # ---- Live multi-curve graph + per-trace legend ----
        graph = _TraceGraph(
            traces=[(t_id, color, style)
                    for t_id, _label, color, _vis, style in _TUNE_TRACES],
            window_s=3.0,
        )
        graph.setMinimumHeight(260)
        graph.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        # Apply default visibility from the spec.
        for t_id, _label, _color, vis, _style in _TUNE_TRACES:
            graph.set_trace_visible(t_id, vis)
        self._tune_widgets["graph"] = graph

        graph_with_legend = QWidget()
        gwl = _hbox(0, 10)
        graph_with_legend.setLayout(gwl)
        gwl.addWidget(graph, 1)

        # Legend column.
        legend = QFrame()
        legend.setObjectName("traceLegend")
        legend_lay = _vbox(8, 4)
        legend.setLayout(legend_lay)
        legend.setMinimumWidth(160)
        legend_header = QLabel("Traces")
        lhf = legend_header.font(); lhf.setBold(True)
        legend_header.setFont(lhf)
        legend_lay.addWidget(legend_header)
        for t_id, label, color, default_vis, style in _TUNE_TRACES:
            # Annotate the label with the line style so the legend
            # matches what's drawn on the graph.
            dash = style.get("dash", "solid")
            if dash == "dash":
                annotated = f"{label}  · · ·"
            elif dash == "dot":
                annotated = f"{label}  : : :"
            else:
                annotated = label
            cb = QCheckBox(annotated)
            cb.setChecked(default_vis)
            # Color the checkbox text via stylesheet so the legend doubles
            # as a colour key for the graph traces.
            cb.setStyleSheet(f"color: {color};")
            cb.toggled.connect(
                lambda checked, tid=t_id: self._tune_widgets["graph"].set_trace_visible(
                    tid, bool(checked)
                )
            )
            legend_lay.addWidget(cb)
            self._tune_widgets["trace_checkboxes"][t_id] = cb
        legend_lay.addStretch(1)
        gwl.addWidget(legend)
        parent_layout.addWidget(graph_with_legend, 1)

        # ---- Same Mix subcard the Device Routing motor card uses ----
        mix_container = QFrame()
        mix_container.setObjectName("tuneMixContainer")
        mc_lay = _vbox(8, 6)
        mix_container.setLayout(mc_lay)
        mix_placeholder = QLabel(
            "Select a motor above to see its Mix controls."
        )
        mix_placeholder.setProperty("muted", "true")
        self._repolish(mix_placeholder)
        mc_lay.addWidget(mix_placeholder)
        self._tune_widgets["mix_container"] = mix_container
        self._tune_widgets["mix_container_lay"] = mc_lay
        parent_layout.addWidget(mix_container)

        # ---- Wire up handlers (after all widgets exist) ----
        def on_motor_changed(idx: int):
            data = motor_combo.itemData(idx)
            if data is None:
                self._tune_set_selection(None, None)
                return
            device_name, motor_idx = data
            self._tune_set_selection(device_name, motor_idx)

        motor_combo.currentIndexChanged.connect(on_motor_changed)

        def on_source_changed(text: str):
            src = _SOURCE_LIVE if "Live" in text else _SOURCE_SIMULATED
            self.controller.tune_set_source(src)
            self._tune_apply_source_visibility(src)
        source_combo.currentTextChanged.connect(on_source_changed)

        play_btn.clicked.connect(self._tune_on_play)
        stop_btn.clicked.connect(self._tune_on_stop)

        def on_send_to_toy(checked):
            self.controller.tune_set_send_to_toy(bool(checked))
        send_toggle.toggled.connect(on_send_to_toy)

        # Initial population + visibility.
        self._tune_refresh_motor_list()
        self._tune_apply_source_visibility(_SOURCE_SIMULATED)

    # ----------------------------------------------------------
    # Helpers
    # ----------------------------------------------------------

    def _tune_pattern_label(self, pattern_id: str) -> str:
        """Human-readable label for a pattern id. Just title-cases the
        snake_case so we don't need a separate display-name map."""
        return pattern_id.replace("_", " ").title()

    def _tune_refresh_motor_list(self) -> None:
        """Rebuild the motor picker from the active profile. Called on
        first build and via the Refresh button."""
        combo: QComboBox = self._tune_widgets["motor_combo"]
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
            # Restore previous selection if still valid.
            if prev is not None:
                for i in range(combo.count()):
                    if combo.itemData(i) == prev:
                        combo.setCurrentIndex(i)
                        break
        finally:
            combo.blockSignals(False)
        # Always re-apply selection so router subscription matches the combo.
        data = combo.currentData()
        if data is None:
            self._tune_set_selection(None, None)
        else:
            self._tune_set_selection(data[0], data[1])

    def _tune_set_selection(self, device_name: Optional[str],
                            motor_idx: Optional[int]) -> None:
        """Wire the router subscription and rebuild the Mix subcard
        embedded below the graph to point at the new motor."""
        self.controller.tune_select_motor(device_name, motor_idx)
        self._tune_widgets["current_selection"] = (
            None if device_name is None else (device_name, motor_idx)
        )
        graph = self._tune_widgets.get("graph")
        if graph is not None:
            graph.clear()

        # Rebuild the embedded Mix subcard for the new motor.
        mc_lay: QVBoxLayout = self._tune_widgets["mix_container_lay"]
        if mc_lay is None:
            return
        while mc_lay.count():
            item = mc_lay.takeAt(0)
            w = item.widget()
            if w is not None:
                w.setParent(None)
                w.deleteLater()
        if device_name is None or motor_idx is None:
            placeholder = QLabel("Select a motor above to see its Mix controls.")
            placeholder.setProperty("muted", "true")
            self._repolish(placeholder)
            mc_lay.addWidget(placeholder)
            return
        # _build_mix_subcard returns (frame, mini_graph). The Tune view
        # ignores the mini_graph — we have the big graph instead.
        subcard, _mg = self._build_mix_subcard(device_name, motor_idx)
        mc_lay.addWidget(subcard)

    def _tune_apply_source_visibility(self, source: str) -> None:
        """Show/hide the pattern row, send-to-toy switch, and zone hint
        based on whether we're in Simulated or Live mode."""
        is_sim = (source == _SOURCE_SIMULATED)
        for key in ("pattern_row", "send_row", "hint"):
            w = self._tune_widgets.get(key)
            if w is not None:
                w.setVisible(is_sim)

    def _tune_on_play(self) -> None:
        combo: QComboBox = self._tune_widgets["pattern_combo"]
        if combo is None:
            return
        pattern_id = combo.currentData()
        if not pattern_id:
            return
        self.controller.tune_start_pattern(str(pattern_id))

    def _tune_on_stop(self) -> None:
        self.controller.tune_stop_pattern()

    # ----------------------------------------------------------
    # Trace ingestion (called from main.py's queue drainer)
    # ----------------------------------------------------------

    def update_tune_trace(self, trace: Dict[str, Any]) -> None:
        """Receive one intermediates record from the router and push
        each value into its trace on the graph. No-op when the trace
        is for a different motor than the user has selected (the router
        only subscribes one motor at a time, so this is mostly defensive
        against in-flight messages from a just-changed selection)."""
        graph = self._tune_widgets.get("graph") if hasattr(self, "_tune_widgets") else None
        if graph is None:
            return
        selection = self._tune_widgets.get("current_selection")
        if selection is None:
            return
        if (trace.get("device"), trace.get("motor")) != selection:
            return
        # Convert t_ms to seconds for the graph's window math.
        t_s = float(trace.get("t_ms", 0.0)) / 1000.0
        for trace_id in ("d_raw", "s_raw", "d_shaped", "s_shaped", "mixed", "out"):
            v = trace.get(trace_id)
            if v is None:
                continue
            try:
                graph.push_sample(trace_id, t_s, float(v))
            except (TypeError, ValueError):
                continue
