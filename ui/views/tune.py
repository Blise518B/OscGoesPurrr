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


# Phase 3.5 signal-flow stages strip. Each tuple is
# (stage_id, label, sparkline_trace_ids, focus_trace_ids).
# `sparkline_trace_ids` are what the small per-stage TraceGraph
# renders; `focus_trace_ids` are which traces stay visible in the big
# graph when the user clicks the stage card. They overlap in most
# cases — the distinction lets future stages add inputs to the
# sparkline that they wouldn't pin in the big graph.
_TUNE_STAGES: List[Tuple[str, str, Tuple[str, ...], Tuple[str, ...]]] = [
    ("raw",       "Raw input",   ("d_raw", "s_raw"),       ("d_raw", "s_raw")),
    ("channels",  "Depth/Speed", ("d_shaped", "s_shaped"), ("d_shaped", "s_shaped")),
    ("mix",       "Mix",         ("mixed",),               ("mixed",)),
    ("smoothing", "Smoothing",   ("mixed", "out"),         ("mixed", "out")),
    ("output",    "Output",      ("out",),                 ("out",)),
]


class TuneMixin:

    # ----------------------------------------------------------
    # View construction
    # ----------------------------------------------------------

    def _build_tune_view(self, parent_layout: QVBoxLayout):
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
        tb_lay.addWidget(self._make_help_badge(
            "Source",
            "<b>Simulated</b> injects a synthetic value directly into "
            "the selected motor's d_raw, bypassing zones and OSC. "
            "<b>Live VRChat</b> uses real avatar parameters through "
            "the normal routing pipeline."
        ))
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
        pr_lay.addWidget(self._make_help_badge(
            "Patterns",
            "Pre-made waveforms for testing the mixer. <b>Slow / "
            "Medium / Fast strokes</b> are pure sines. "
            "<b>Fast-in / slow-out</b> exercises asymmetric attack. "
            "<b>Burst</b> tests the post-mix envelope follower's "
            "response to step inputs; <b>Trapezoidal burst</b> is a "
            "more realistic stroke shape with gradual edges. "
            "<b>Tease</b> modulates the carrier amplitude with a "
            "random walk. Switching while playing hot-swaps."
        ))
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
        sr_lay.addWidget(self._make_help_badge(
            "Send to toy",
            "Safety switch. With this <b>OFF</b> (default), the "
            "engine receives 0 for the selected motor even though "
            "the mixer keeps computing — the trace graph still "
            "shows real values but no physical movement happens. "
            "Turn <b>ON</b> to feel what the mixer is producing."
        ))
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

        # ---- Signal-flow stages strip ----
        # Horizontal row of small live sparklines, one per mixer stage
        # (Raw -> Channels -> Mix -> Smoothing -> Output). Clicking a
        # card focuses the main graph on that stage's input/output
        # traces; a "Show all" button restores the default visibility.
        stages_strip = self._build_tune_stages_strip()
        parent_layout.addWidget(stages_strip)

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
        legend_header_row = QWidget()
        lhr = _hbox(0, 6)
        legend_header_row.setLayout(lhr)
        legend_header = QLabel("Traces")
        lhf = legend_header.font(); lhf.setBold(True)
        legend_header.setFont(lhf)
        lhr.addWidget(legend_header)
        lhr.addWidget(self._make_help_badge(
            "Traces",
            "Toggle individual lines in the main graph. "
            "<b>Raw</b> = the router's input before shaping. "
            "<b>Influence</b> = post-curve, post-gain (dashed). "
            "<b>Post-mix</b> = combined value before smoothing "
            "(dotted, off by default). "
            "<b>Final output</b> = what the engine receives, after "
            "the envelope follower (bold green)."
        ))
        lhr.addStretch(1)
        legend_lay.addWidget(legend_header_row)
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

        # Hot-swap the playing pattern when the user picks a different
        # one from the dropdown — only if something's currently playing,
        # so just browsing the list doesn't auto-start. The pattern
        # generator handles in-flight switches under its own lock.
        def on_pattern_changed(_idx):
            status = self.controller.tune_get_status()
            if not status.get("pattern_running"):
                return
            pattern_id = pattern_combo.currentData()
            if pattern_id:
                self.controller.tune_start_pattern(str(pattern_id))
        pattern_combo.currentIndexChanged.connect(on_pattern_changed)

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
    # Phase 3.5 signal-flow stages strip
    # ----------------------------------------------------------

    def _build_tune_stages_strip(self) -> QWidget:
        """Horizontal row of small per-stage sparklines that visualize
        the signal chain Raw -> Channels -> Mix -> Smoothing -> Output.
        Each card is clickable: a click focuses the main graph on the
        stage's input/output traces and highlights the card."""
        host = QFrame()
        host.setObjectName("tuneStagesStrip")
        host_lay = _vbox(0, 4)
        host.setLayout(host_lay)

        header_row = QWidget()
        hr_lay = _hbox(0, 8)
        header_row.setLayout(hr_lay)
        header = QLabel("Signal flow")
        hf = header.font(); hf.setBold(True)
        header.setFont(hf)
        hr_lay.addWidget(header)
        hr_lay.addWidget(self._make_help_badge(
            "Signal flow",
            "Small sparklines of each mixer stage's output over the "
            "last ~1 second. Click a stage card to focus the main "
            "graph on just that stage's input/output traces — useful "
            "for tuning one part of the chain in isolation. "
            "<b>Show all traces</b> restores the default visibility."
        ))
        hr_lay.addStretch(1)
        show_all_btn = QPushButton("Show all traces")
        show_all_btn.setFixedHeight(BTN_HEIGHT_SMALL)
        show_all_btn.setProperty("role", "secondary")
        show_all_btn.clicked.connect(self._tune_reset_trace_visibility)
        hr_lay.addWidget(show_all_btn)
        host_lay.addWidget(header_row)

        strip = QWidget()
        strip_lay = _hbox(0, 4)
        strip.setLayout(strip_lay)

        # Reset the stage refs each time the strip rebuilds.
        self._tune_widgets["stages"] = {}

        last_idx = len(_TUNE_STAGES) - 1
        for idx, (stage_id, label, spark_trace_ids, focus_trace_ids) in enumerate(_TUNE_STAGES):
            card = self._build_tune_stage_card(stage_id, label, spark_trace_ids)
            strip_lay.addWidget(card, 1)
            if idx < last_idx:
                arrow = QLabel("→")
                arrow.setAlignment(Qt.AlignCenter)
                arrow.setProperty("muted", "true")
                af = arrow.font(); af.setPointSize(max(af.pointSize() + 4, 14))
                arrow.setFont(af)
                self._repolish(arrow)
                strip_lay.addWidget(arrow)
        host_lay.addWidget(strip)
        return host

    def _build_tune_stage_card(self, stage_id: str, label: str,
                               spark_trace_ids: Tuple[str, ...]) -> QFrame:
        card = QFrame()
        card.setObjectName("tuneStageCard")
        card.setCursor(Qt.PointingHandCursor)
        card.setProperty("active", "false")
        card.setMinimumWidth(110)
        lay = _vbox(8, 4)
        card.setLayout(lay)

        title = QLabel(label)
        title.setAlignment(Qt.AlignHCenter)
        tf = title.font(); tf.setBold(True)
        title.setFont(tf)
        lay.addWidget(title)

        # Sparkline: 1-second window, traces colored to match the big
        # graph so the two views read as the same chain.
        spark_traces = []
        for trace_id in spark_trace_ids:
            color, style = self._tune_trace_spec_for_id(trace_id)
            spark_traces.append((trace_id, color, style))
        spark = _TraceGraph(traces=spark_traces, window_s=1.0)
        spark.setFixedHeight(46)
        lay.addWidget(spark)

        # Whole card clickable. Buttons inside would consume their own
        # clicks, but we have only labels and a sub-widget here, so the
        # mousePressEvent fires on every left click in the card area.
        def on_press(ev, sid=stage_id):
            if ev.button() == Qt.LeftButton:
                self._tune_focus_stage(sid)
                ev.accept()
            else:
                QFrame.mousePressEvent(card, ev)
        card.mousePressEvent = on_press

        self._tune_widgets["stages"][stage_id] = {
            "card": card,
            "graph": spark,
            "trace_ids": tuple(spark_trace_ids),
        }
        return card

    def _tune_trace_spec_for_id(self, trace_id: str) -> Tuple[str, dict]:
        """Look up the color + style dict for a trace by id. Falls back
        to a neutral color if a stage references an unknown trace."""
        for t_id, _label, color, _vis, style in _TUNE_TRACES:
            if t_id == trace_id:
                return color, style
        return COLOR_TEXT, {}

    def _tune_focus_stage(self, stage_id: str) -> None:
        """Show only the focused stage's traces in the big graph and
        sync the legend checkboxes to match. Highlights the active card."""
        spec = next((s for s in _TUNE_STAGES if s[0] == stage_id), None)
        if spec is None:
            return
        _id, _label, _spark, focus_ids = spec
        focus_set = set(focus_ids)
        self._tune_set_traces_visible(
            {t_id: (t_id in focus_set) for t_id, *_ in _TUNE_TRACES}
        )
        self._tune_highlight_active_stage(stage_id)

    def _tune_reset_trace_visibility(self) -> None:
        """Restore the default per-trace visibility from _TUNE_TRACES
        and clear any active stage highlight."""
        self._tune_set_traces_visible(
            {t_id: default_vis
             for t_id, _label, _color, default_vis, _style in _TUNE_TRACES}
        )
        self._tune_highlight_active_stage(None)

    def _tune_set_traces_visible(self, visibility: Dict[str, bool]) -> None:
        graph = self._tune_widgets.get("graph") if hasattr(self, "_tune_widgets") else None
        checkboxes = (self._tune_widgets.get("trace_checkboxes", {})
                      if hasattr(self, "_tune_widgets") else {})
        for t_id, vis in visibility.items():
            if graph is not None:
                graph.set_trace_visible(t_id, bool(vis))
            cb = checkboxes.get(t_id)
            if cb is not None:
                cb.blockSignals(True)
                try:
                    cb.setChecked(bool(vis))
                finally:
                    cb.blockSignals(False)

    def _tune_highlight_active_stage(self, active_id: Optional[str]) -> None:
        stages = self._tune_widgets.get("stages", {})
        for sid, refs in stages.items():
            card = refs.get("card")
            if card is None:
                continue
            card.setProperty("active", "true" if sid == active_id else "false")
            self._repolish(card)

    # ----------------------------------------------------------
    # Trace ingestion (called from main.py's queue drainer)
    # ----------------------------------------------------------

    def update_tune_trace(self, trace: Dict[str, Any]) -> None:
        """Receive one intermediates record from the router and push
        each value into its trace on the big graph AND every matching
        stage sparkline. No-op when the trace is for a different motor
        than the user has selected (the router only subscribes one
        motor at a time, so this is mostly defensive against in-flight
        messages from a just-changed selection)."""
        if not hasattr(self, "_tune_widgets"):
            return
        graph = self._tune_widgets.get("graph")
        if graph is None:
            return
        selection = self._tune_widgets.get("current_selection")
        if selection is None:
            return
        if (trace.get("device"), trace.get("motor")) != selection:
            return
        # Convert t_ms to seconds for the graph's window math.
        t_s = float(trace.get("t_ms", 0.0)) / 1000.0
        stages = self._tune_widgets.get("stages", {})
        for trace_id in ("d_raw", "s_raw", "d_shaped", "s_shaped", "mixed", "out"):
            v = trace.get(trace_id)
            if v is None:
                continue
            try:
                fv = float(v)
            except (TypeError, ValueError):
                continue
            graph.push_sample(trace_id, t_s, fv)
            for refs in stages.values():
                if trace_id in refs.get("trace_ids", ()):
                    refs["graph"].push_sample(trace_id, t_s, fv)
