"""Per-motor signal-chain widget — the user-facing surface for the
Input → Depth/Speed → Combine → Gate → Smoothing → Output pipeline.

Embedded in two contexts (intentionally — see MOTOR_SIGNAL_CHAIN.md
§ "Tune view, 1:1 with Device Routing"):
  * Device Routing motor card (Cut 3) — primary editing surface.
  * Tune view (Cut 4) — same editing surface plus the multi-trace
    graph and pattern player overlay.

There is exactly one editor per stage; clicking a stage in the strip
swaps the inline editor below. Storage round-trips through the
controller facade calls the rest of the UI already uses
(`get_profile_config`, `update_device_config`, `save_profiles`,
`force_recalculate`).

The widget reads the per-motor `mix` block in the chains-list shape
locked in Cut 1 (`mix.<motor>.chains[0].…`). Cuts 1–4 always have
exactly one chain; Cut 5 (optional secondary chain) wraps this
widget in a list container without touching its internals."""

from __future__ import annotations

import copy
import time
from typing import Any, Callable, Dict, List, Optional, Tuple

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QColor, QPainter, QPen, QBrush, QFont
from PySide6.QtWidgets import (
    QFrame, QWidget, QLabel, QPushButton, QComboBox, QDoubleSpinBox,
    QButtonGroup, QStackedWidget, QSizePolicy,
)

from constants import (
    BTN_HEIGHT_SMALL, COLOR_SUCCESS, COLOR_ALERT, COLOR_TEXT,
    COLOR_SURFACE, COLOR_SURFACE_HOVER,
)
from ui.layout_helpers import vbox as _vbox, hbox as _hbox
from ui.widgets import ToggleSwitch, RainbowMeter as _RainbowMeter, ProgressProxy as _ProgressProxy
from ui.trace_graph import TraceGraph as _TraceGraph
from mixer import sample_pattern as _sample_pattern, WAVEFORMS as _WAVEFORMS


# ----------------------------------------------------------
# Storage helpers — read/write the per-motor `mix.chains[0]` block.
# Mirrors the pattern in device_frame.py's _get_mix_field /
# _update_mix_field but scoped to the new chains-list schema.
# ----------------------------------------------------------

def _default_chain() -> Dict[str, Any]:
    """Fresh copy of the canonical single-chain default. Imported
    lazily so this module doesn't drag motor_router into UI startup."""
    from motor_router import MotorRouter
    return copy.deepcopy(MotorRouter.DEFAULT_MIX_CONFIG["chains"][0])


def _default_mix() -> Dict[str, Any]:
    from motor_router import MotorRouter
    return copy.deepcopy(MotorRouter.DEFAULT_MIX_CONFIG)


# Cap on chains per motor — matches motor_router._MAX_CHAINS_PER_MOTOR.
# Duplicated here so the UI can enforce the cap without importing the
# router on startup.
MAX_CHAINS_PER_MOTOR = 2

# Valid merge operations for combining multiple chains' outputs.
_MERGE_OPS = ("add", "max", "multiply")


def _read_per_motor(controller, device_name: str,
                    motor_idx: int) -> Dict[str, Any]:
    """Return the per-motor mix block (the dict that holds `chains`
    and `merge`), falling back to a fresh default when missing or
    malformed. Internal helper for the chain-list helpers below."""
    mix_root = controller.get_profile_config(device_name, "mix", {}) or {}
    if not isinstance(mix_root, dict):
        return _default_mix()
    per_motor = mix_root.get(str(motor_idx))
    if not isinstance(per_motor, dict):
        return _default_mix()
    return per_motor


def _read_chain(controller, device_name: str, motor_idx: int,
                chain_idx: int = 0) -> Dict[str, Any]:
    """Pull one chain dict for a motor, falling back to the canonical
    default when the profile is missing or malformed. `chain_idx=0`
    addresses the primary chain (single-chain motors); `chain_idx=1`
    is the optional secondary chain (Cut 5)."""
    per_motor = _read_per_motor(controller, device_name, motor_idx)
    chains = per_motor.get("chains")
    if (isinstance(chains, list)
            and 0 <= chain_idx < len(chains)
            and isinstance(chains[chain_idx], dict)):
        return chains[chain_idx]
    return _default_chain()


def _get_chain_count(controller, device_name: str, motor_idx: int) -> int:
    """How many chains this motor has in its profile (1 or 2). A
    missing or malformed `chains` list counts as 1 — the router
    falls back to a single default chain, and the UI mirrors that."""
    per_motor = _read_per_motor(controller, device_name, motor_idx)
    chains = per_motor.get("chains")
    if not isinstance(chains, list) or not chains:
        return 1
    return min(len(chains), MAX_CHAINS_PER_MOTOR)


def _get_merge_op(controller, device_name: str, motor_idx: int) -> str:
    """Read the merge op (`add` / `max` / `multiply`). Only meaningful
    when chain count > 1; falls back to `max` (the default) otherwise."""
    per_motor = _read_per_motor(controller, device_name, motor_idx)
    op = per_motor.get("merge")
    return op if op in _MERGE_OPS else "max"


def _write_per_motor(controller, device_name: str, motor_idx: int,
                     per_motor: Dict[str, Any]) -> None:
    """Internal: write the per-motor mix block back and trigger
    save + recalc. Used by every helper that mutates the structure."""
    mix_root = copy.deepcopy(
        controller.get_profile_config(device_name, "mix", {}) or {}
    )
    if not isinstance(mix_root, dict):
        mix_root = {}
    mix_root[str(motor_idx)] = per_motor
    controller.update_device_config(device_name, "mix", mix_root)
    if hasattr(controller, "save_profiles"):
        controller.save_profiles()
    if hasattr(controller, "force_recalculate"):
        controller.force_recalculate()


def _ensure_chain_at(per_motor: Dict[str, Any], chain_idx: int) -> Dict[str, Any]:
    """Grow `per_motor["chains"]` if needed so chain_idx is in bounds.
    Returns the chain dict at chain_idx. Caps at MAX_CHAINS_PER_MOTOR."""
    template = _default_mix()
    if not isinstance(per_motor.get("chains"), list) or not per_motor["chains"]:
        per_motor["chains"] = copy.deepcopy(template["chains"])
    if per_motor.get("merge") not in _MERGE_OPS:
        per_motor["merge"] = template["merge"]
    chains = per_motor["chains"]
    while len(chains) <= chain_idx and len(chains) < MAX_CHAINS_PER_MOTOR:
        chains.append(_default_chain())
    # Clamp to the cap — silently drop a third chain if a hand-edited
    # profile asked for one.
    if len(chains) > MAX_CHAINS_PER_MOTOR:
        del chains[MAX_CHAINS_PER_MOTOR:]
    safe_idx = min(chain_idx, len(chains) - 1)
    if not isinstance(chains[safe_idx], dict):
        chains[safe_idx] = _default_chain()
    chain = chains[safe_idx]
    # Backfill chain top-level keys (defensive against partial writes).
    for tk, tv in template["chains"][0].items():
        if tk not in chain:
            chain[tk] = copy.deepcopy(tv)
    return chain


def _update_chain_field(controller, device_name: str, motor_idx: int,
                        chain_idx: int,
                        path: Tuple[str, ...], value: Any) -> None:
    """Update a nested field inside `chains[chain_idx]` for the
    motor, creating missing parents from defaults. Writes the full
    `mix` block back via the controller facade, then asks the router
    to recompute."""
    per_motor = copy.deepcopy(
        _read_per_motor(controller, device_name, motor_idx)
    )
    chain = _ensure_chain_at(per_motor, chain_idx)
    cursor: Any = chain
    for k in path[:-1]:
        sub = cursor.get(k)
        if not isinstance(sub, dict):
            sub = {}
            cursor[k] = sub
        cursor = sub
    cursor[path[-1]] = value
    _write_per_motor(controller, device_name, motor_idx, per_motor)


def _reset_chain_to_defaults(controller, device_name: str, motor_idx: int,
                             chain_idx: int = 0) -> None:
    """Replace `chains[chain_idx]` with a fresh default chain. Other
    chains on the same motor and other motors on the same device are
    untouched. Falls through to the whole-mix reset if the motor has
    no `mix` entry at all yet."""
    per_motor = copy.deepcopy(
        _read_per_motor(controller, device_name, motor_idx)
    )
    template = _default_mix()
    if not isinstance(per_motor.get("chains"), list) or not per_motor["chains"]:
        per_motor["chains"] = copy.deepcopy(template["chains"])
    if per_motor.get("merge") not in _MERGE_OPS:
        per_motor["merge"] = template["merge"]
    chains = per_motor["chains"]
    if 0 <= chain_idx < len(chains):
        chains[chain_idx] = _default_chain()
    _write_per_motor(controller, device_name, motor_idx, per_motor)


def _add_chain(controller, device_name: str, motor_idx: int) -> bool:
    """Append a new default chain to this motor. Returns True if a
    chain was added, False if the cap was already reached."""
    per_motor = copy.deepcopy(
        _read_per_motor(controller, device_name, motor_idx)
    )
    template = _default_mix()
    if not isinstance(per_motor.get("chains"), list) or not per_motor["chains"]:
        per_motor["chains"] = copy.deepcopy(template["chains"])
    if per_motor.get("merge") not in _MERGE_OPS:
        per_motor["merge"] = template["merge"]
    if len(per_motor["chains"]) >= MAX_CHAINS_PER_MOTOR:
        return False
    per_motor["chains"].append(_default_chain())
    _write_per_motor(controller, device_name, motor_idx, per_motor)
    return True


def _remove_chain(controller, device_name: str, motor_idx: int,
                  chain_idx: int) -> bool:
    """Remove `chains[chain_idx]` from this motor. Refuses to drop
    below one chain (motors always have at least one). Returns True
    if a chain was removed, False otherwise."""
    per_motor = copy.deepcopy(
        _read_per_motor(controller, device_name, motor_idx)
    )
    chains = per_motor.get("chains")
    if not isinstance(chains, list) or len(chains) <= 1:
        return False
    if not (0 <= chain_idx < len(chains)):
        return False
    chains.pop(chain_idx)
    _write_per_motor(controller, device_name, motor_idx, per_motor)
    return True


def _set_merge_op(controller, device_name: str, motor_idx: int,
                  op: str) -> None:
    """Set the merge op for combining multiple chains' outputs.
    Silently ignored when `op` is not one of the supported ops."""
    if op not in _MERGE_OPS:
        return
    per_motor = copy.deepcopy(
        _read_per_motor(controller, device_name, motor_idx)
    )
    template = _default_mix()
    if not isinstance(per_motor.get("chains"), list) or not per_motor["chains"]:
        per_motor["chains"] = copy.deepcopy(template["chains"])
    per_motor["merge"] = op
    _write_per_motor(controller, device_name, motor_idx, per_motor)


# Stage IDs — kept short and stable; used as both the QStackedWidget
# page key and the active-stage marker on the stages strip.
STAGE_INPUT = "input"
STAGE_DEPTH = "depth"
STAGE_SPEED = "speed"
STAGE_COMBINE = "combine"
STAGE_GATE = "gate"
STAGE_SMOOTHING = "smoothing"
STAGE_OUTPUT = "output"

_STAGE_ORDER = (
    STAGE_INPUT, STAGE_DEPTH, STAGE_SPEED,
    STAGE_COMBINE, STAGE_GATE, STAGE_SMOOTHING, STAGE_OUTPUT,
)

_STAGE_LABELS = {
    STAGE_INPUT:     "Input",
    STAGE_DEPTH:     "Depth",
    STAGE_SPEED:     "Speed",
    STAGE_COMBINE:   "Combine",
    STAGE_GATE:      "Gate",
    STAGE_SMOOTHING: "Smoothing",
    STAGE_OUTPUT:    "Output",
}

_CURVE_KINDS = ("linear", "power", "s_curve")
_COMBINE_OPS = ("add", "max", "multiply")


# Per-stage trace specifications for the inlined per-stage mini-graphs
# (Cut 6). Mapping is documented in CHAIN_INLINED_TUNING.md §
# "Per-stage graph trace mapping". Each entry is (trace_id, color,
# style_dict) — same shape as TraceGraph's traces argument.
#
# Trace styles mirror Tune's six-trace graph for visual continuity:
#   * raw signals (d_raw / s_raw): solid, lighter tints
#   * shaped signals (d_shaped / s_shaped): dashed
#   * mixed (post-combine): dotted purple
#   * gated (post-gate, pre-smooth): solid yellow
#   * out (post-smooth chain output): bold green

_TRACE_STYLE = {
    "d_raw":    ("#88AAFF", {"width": 1.6}),
    "s_raw":    ("#FFBB88", {"width": 1.6}),
    "d_shaped": ("#3366FF", {"width": 1.8, "dash": "dash"}),
    "s_shaped": ("#FF7733", {"width": 1.8, "dash": "dash"}),
    "mixed":    ("#C040FF", {"width": 1.6, "dash": "dot"}),
    "gated":    ("#FFCC00", {"width": 1.6}),
    "out":      (COLOR_SUCCESS, {"width": 2.0}),
}

_STAGE_TRACES: Dict[str, Tuple[str, ...]] = {
    STAGE_INPUT:     ("d_raw",),
    STAGE_DEPTH:     ("d_raw", "d_shaped"),
    STAGE_SPEED:     ("s_raw", "s_shaped"),
    STAGE_COMBINE:   ("d_shaped", "s_shaped", "mixed"),
    STAGE_GATE:      ("mixed", "gated"),
    STAGE_SMOOTHING: ("gated", "out"),
    STAGE_OUTPUT:    ("out",),
}

_STAGE_GRAPH_WINDOW_S = 3.0


# Per-stage "level" trace — which value drives that stage's card
# border colour. Each stage picks the signal that flows OUT of it
# so the colour reflects what the stage is currently contributing.
_STAGE_LEVEL_TRACE: Dict[str, str] = {
    STAGE_INPUT:     "d_raw",
    STAGE_DEPTH:     "d_shaped",
    STAGE_SPEED:     "s_shaped",
    STAGE_COMBINE:   "mixed",
    STAGE_GATE:      "gated",
    STAGE_SMOOTHING: "out",
    STAGE_OUTPUT:    "out",
}

# Stage card border lerp endpoints. Low (idle) is dark purple,
# matching the indigo canvas; high (saturated) is vivid pink so a
# motor at full pulls visual attention. Hex chosen for readable
# contrast on the surface-hover background.
_STAGE_BORDER_LOW = "#5030A0"   # dark purple
_STAGE_BORDER_HIGH = "#FF40A0"  # vivid pink

# Only repaint the card border when the level has changed by at
# least this much, to keep the stylesheet churn well below the
# router's 90Hz tick.
_STAGE_BORDER_EPSILON = 0.02

# Subtitle refresh cadence — picks up external profile edits
# without a notification path. 1.5 s is fine because the only edits
# that change subtitle content also come from THIS widget's own
# controls (gain spinboxes, curve combos, etc.), which the user
# expects to see reflected on the next stage click; external profile
# rewrites already destroy + rebuild the widget. Slower interval
# reduces polling without changing perceived responsiveness.
_STAGE_SUBTITLE_REFRESH_MS = 1500


# Overview disclosure trace set (Cut 8a). Six traces matching the
# old Tune view big graph; styles inherit from _TRACE_STYLE so the
# visual language stays consistent.
_OVERVIEW_TRACE_IDS: Tuple[str, ...] = (
    "d_raw", "s_raw", "d_shaped", "s_shaped", "mixed", "out",
)
_OVERVIEW_WINDOW_S = 6.0
_OVERVIEW_GRAPH_HEIGHT = 120


# Simulator Drive modes — labels match the dropdown UI. The mode
# string is stored verbatim in `_sim_state["drive"]` so the panel's
# combo can round-trip without translation.
_DRIVE_BOTH = "Both"
_DRIVE_CHAIN_1 = "Chain 1 only"
_DRIVE_CHAIN_2 = "Chain 2 only"
_DRIVE_MODES = (_DRIVE_BOTH, _DRIVE_CHAIN_1, _DRIVE_CHAIN_2)


# Per-motor-kind display strings. One source of truth for the three
# UI surfaces that need to talk about a continuous motor's role:
#   * Motor card title suffix (after "Motor N · ")
#   * Output stage editor's "drives the X" note
#   * Output stage card subtitle (three letters)
# Kinds come from haptic_engine._FEATURE_PRIORITY. Linear actuators
# get a fundamentally different Output editor and aren't in this
# table — they're special-cased in each call site.
class _KindDisplay:
    __slots__ = ("suffix", "output_phrase", "subtitle")

    def __init__(self, suffix: str, output_phrase: str, subtitle: str) -> None:
        self.suffix = suffix
        self.output_phrase = output_phrase
        self.subtitle = subtitle


_KIND_DISPLAY: Dict[str, _KindDisplay] = {
    "vibrate":     _KindDisplay("Vibrate",   "vibration intensity",   "vib"),
    "constrict":   _KindDisplay("Contract",  "contraction strength",  "con"),
    "oscillate":   _KindDisplay("Oscillate", "oscillation intensity", "osc"),
    "rotate":      _KindDisplay("Rotate",    "rotation speed",        "rot"),
    "spray":       _KindDisplay("Spray",     "spray output",          "spr"),
    "temperature": _KindDisplay("Heat",      "heater temperature",    "tmp"),
    "led":         _KindDisplay("LED",       "LED brightness",        "led"),
}
_DEFAULT_KIND_DISPLAY = _KIND_DISPLAY["vibrate"]


def _trace_spec(trace_id: str) -> Tuple[str, str, dict]:
    """Build a TraceGraph trace tuple `(id, color, style)` for one
    trace id. Falls back to a neutral color for unknown ids."""
    color, style = _TRACE_STYLE.get(trace_id, (COLOR_TEXT, {}))
    return (trace_id, color, style)


# ----------------------------------------------------------
# Activity meter — paints the gate's activity level + threshold tick.
# ----------------------------------------------------------

class ActivityMeter(QFrame):
    """Thin horizontal bar showing activity meter value with a tick
    mark at wake_threshold. Color flips between gate-open (success
    green) and gate-closed (alert red) so the user can see at a
    glance why output is or isn't passing."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._value = 0.0
        self._threshold = 0.05
        self._open = False
        self.setMinimumHeight(14)
        self.setMaximumHeight(14)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

    def set_value(self, value: float) -> None:
        v = max(0.0, min(1.0, float(value)))
        if v != self._value:
            self._value = v
            self.update()

    def set_threshold(self, threshold: float) -> None:
        t = max(0.0, min(1.0, float(threshold)))
        if t != self._threshold:
            self._threshold = t
            self.update()

    def set_open(self, is_open: bool) -> None:
        b = bool(is_open)
        if b != self._open:
            self._open = b
            self.update()

    def paintEvent(self, _ev) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, False)
        w = self.width()
        h = self.height()
        # Background trough.
        p.fillRect(0, 0, w, h, QColor("#1b1b2a"))
        # Fill bar — gate-open colour over the value's portion of the width.
        fill_color = QColor(COLOR_SUCCESS) if self._open else QColor(COLOR_ALERT)
        fill_w = int(w * self._value)
        if fill_w > 0:
            p.fillRect(0, 0, fill_w, h, fill_color)
        # Threshold tick — narrow vertical line.
        tx = int(w * self._threshold)
        pen = QPen(QColor("#e0e0f0"))
        pen.setWidth(2)
        p.setPen(pen)
        p.drawLine(tx, 0, tx, h)
        p.end()


# ----------------------------------------------------------
# ValveIndicator — animated open/closed bar for the gate stage card.
# ----------------------------------------------------------

class ValveIndicator(QFrame):
    """Thin horizontal bar that fills from left (closed) to right
    (open) when the gate flips on, and drains the other way when
    it flips off. Smoothly animated via a 16 ms timer that lerps
    the current position toward the binary target.

    Sits on the Gate stage card in the stages strip; gives an
    at-a-glance "did the gate just trigger?" signal without
    expanding the stage editor (where the full ActivityMeter
    lives)."""

    # ~6 frames at 16 ms = ~100 ms full transition. Slow enough that
    # the eye registers the slide, fast enough that the gate's
    # state-change is read as immediate.
    _LERP_PER_TICK = 0.15
    _TICK_MS = 16

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._target: float = 0.0
        self._current: float = 0.0
        self.setMinimumHeight(6)
        self.setMaximumHeight(6)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        # Animation timer — parented to self so it dies with the widget.
        # Starts paused; ticks while _current is moving toward _target.
        self._anim_timer = QTimer(self)
        self._anim_timer.setInterval(self._TICK_MS)
        self._anim_timer.timeout.connect(self._tick)

    def set_open(self, is_open: bool) -> None:
        """Set the target state. The cursor animates toward 0 or 1;
        idempotent calls (already at target) are no-ops."""
        target = 1.0 if is_open else 0.0
        if target == self._target:
            return
        self._target = target
        if not self._anim_timer.isActive():
            self._anim_timer.start()

    def _tick(self) -> None:
        if abs(self._current - self._target) < 0.005:
            # Snap exact + stop the timer to save battery.
            self._current = self._target
            self._anim_timer.stop()
            self.update()
            return
        # Linear lerp — eye reads it as smooth at this duration; an
        # easing curve would be more code without a visible benefit.
        if self._current < self._target:
            self._current = min(self._target, self._current + self._LERP_PER_TICK)
        else:
            self._current = max(self._target, self._current - self._LERP_PER_TICK)
        # Stop the timer the same tick the lerp lands at the target
        # so the next tick doesn't fire just to no-op. Tolerance check
        # rather than `==` so future tweaks to `_LERP_PER_TICK` that
        # break exact divisibility don't leave a phantom-active timer.
        if abs(self._current - self._target) < 1e-9:
            self._current = self._target
            self._anim_timer.stop()
        self.update()

    def paintEvent(self, _ev) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, False)
        w = self.width()
        h = self.height()
        # Track (closed) — dim purple.
        p.fillRect(0, 0, w, h, QColor("#1b1b2a"))
        # Fill (open) — success green; width follows the animated
        # current position so opens and closes are equally visible.
        fill_w = int(w * self._current)
        if fill_w > 0:
            p.fillRect(0, 0, fill_w, h, QColor(COLOR_SUCCESS))
        p.end()


# ----------------------------------------------------------
# MotorSignalChainWidget — the main per-motor surface.
# ----------------------------------------------------------

class MotorSignalChainWidget(QFrame):
    """Stages strip + inline stage editor + per-stage mini-graphs +
    vibe meter for one motor (or one chain of a two-chain motor).

    Embeds via:
        widget = MotorSignalChainWidget(ui, device_name, motor_idx, motor_kind)
        parent_layout.addWidget(widget)

    The `ui` argument is the OscGoesPurrrUI mixin instance — used for
    shared helpers (`_make_help_badge`, `_repolish`,
    `_build_listening_to_column`, `_open_variable_picker`). The
    widget never reaches into private profile state on its own; all
    reads/writes go through `ui.controller`.

    Public API:
        set_motor_value(value)  → drives the vibe meter
        teardown()              → unsubscribes from router intermediates

    Activity-meter updates are driven by the widget's own
    intermediates subscription — no external setter needed.

    Live trace data flows from the router's per-(motor, chain)
    intermediates subscription. The router callback fires from the
    routing thread; the widget's `intermediates` signal queues the
    payload onto the UI thread where `_handle_intermediates` pushes
    samples into whichever stage's mini-graph has been built so far.
    Stage editors and their graphs are constructed lazily on first
    activation."""

    # Class-level Qt signal so the router's hot-path callback can
    # emit cross-thread to the UI thread safely (Qt.QueuedConnection
    # is the default for cross-thread emit).
    intermediates = Signal(dict)

    def __init__(self, ui, device_name: str, motor_idx: int,
                 motor_kind: Optional[str] = None,
                 chain_idx: int = 0,
                 parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._ui = ui
        self._controller = ui.controller
        self._device_name = device_name
        self._motor_idx = motor_idx
        self._motor_kind = motor_kind
        self._chain_idx = int(chain_idx)
        self._is_linear = motor_kind in ("linear", "linear-d")

        self.setObjectName("motorBlock")
        root = _vbox(10, 8)
        self.setLayout(root)

        # ---- Card header: title + Reset button ------------------------
        header_row = _hbox(0, 8)
        # When wrapped in a multi-chain layout (Cut 5) the title gains
        # a "Chain N" suffix so the user can tell the two stacks apart.
        # Single-chain motors omit it for backward visual familiarity.
        # Title suffix per buttplug.io OutputType — looked up from
        # the shared _KIND_DISPLAY table. Linear actuators are
        # special-cased because they get a structurally different
        # Output editor, not just a different label.
        title_text = f"Motor {motor_idx}"
        if self._is_linear:
            title_text += " · Thrust (linear)"
        else:
            info = _KIND_DISPLAY.get(motor_kind)
            if info is not None:
                title_text += f" · {info.suffix}"
        if self._chain_idx > 0:
            title_text += f" · Chain {self._chain_idx + 1}"
        title = QLabel(title_text)
        title.setObjectName("motorCardHeader")
        tf = title.font(); tf.setBold(True)
        title.setFont(tf)
        header_row.addWidget(title)
        header_row.addStretch(1)
        reset_btn = QPushButton("Reset to defaults")
        reset_btn.setFixedHeight(BTN_HEIGHT_SMALL)
        reset_btn.setToolTip(
            "Wipe every setting in THIS chain (channels, curves, "
            "combine, gate, smoothing) back to the built-in defaults. "
            "Other chains on the same motor are untouched."
        )
        reset_btn.clicked.connect(self._on_reset_clicked)
        header_row.addWidget(reset_btn)
        root.addLayout(header_row)

        # ---- Stages strip --------------------------------------------
        self._stage_cards: Dict[str, QFrame] = {}
        # Subtitle labels under each card title; refreshed on a timer.
        self._stage_subtitles: Dict[str, QLabel] = {}
        # Last-applied border level per stage; gates stylesheet churn.
        self._stage_last_level: Dict[str, float] = {}
        # Optional valve indicator on the gate stage card only.
        self._stage_valve: Optional[ValveIndicator] = None
        self._active_stage: str = STAGE_INPUT
        root.addWidget(self._build_stages_strip())

        # ---- Editor stack --------------------------------------------
        # One QStackedWidget page per stage. Pages are built lazily on
        # first activation; until then the page is an empty placeholder
        # so the stack always has all seven indices populated.
        self._editor_stack = QStackedWidget()
        self._editor_pages: Dict[str, QWidget] = {}
        self._editor_built: Dict[str, bool] = {sid: False for sid in _STAGE_ORDER}
        for sid in _STAGE_ORDER:
            placeholder = QWidget()
            self._editor_pages[sid] = placeholder
            self._editor_stack.addWidget(placeholder)
        root.addWidget(self._editor_stack)

        # ---- Vibe meter ----------------------------------------------
        self._vibe_meter = _RainbowMeter(maximum=1000)
        self._vibe_proxy = _ProgressProxy(self._vibe_meter)
        root.addWidget(self._vibe_meter)

        # Activity meter widget (lives inside the Gate stage editor;
        # driven from this widget's own intermediates subscription
        # below — set_activity(...) is a no-op shim for backward compat).
        self._activity_meter: Optional[ActivityMeter] = None

        # Per-stage mini-graphs (Cut 6). Built lazily alongside their
        # editor pages in `_build_editor_for`. Keyed by stage id.
        self._stage_graphs: Dict[str, _TraceGraph] = {}

        # Activate Input by default — it's where users start a new motor.
        self._activate_stage(STAGE_INPUT)

        # Stage card subtitle refresh — picks up external profile
        # edits without a notification path. Parented to self so the
        # timer dies with the widget. Tick interval is intentionally
        # slow (500ms); subtitles are at-a-glance text, not live data.
        self._subtitle_timer = QTimer(self)
        self._subtitle_timer.setInterval(_STAGE_SUBTITLE_REFRESH_MS)
        self._subtitle_timer.timeout.connect(self._refresh_stage_subtitles)
        self._subtitle_timer.start()

        # Subscribe to per-(motor, chain) intermediates so the
        # mini-graphs and activity meter receive live data. The signal
        # bridge ensures cross-thread safety: router's callback runs
        # on the routing thread, `emit` queues onto the UI thread
        # where `_handle_intermediates` is invoked.
        self.intermediates.connect(self._handle_intermediates)
        self._intermediates_callback = self.intermediates.emit
        self._intermediates_subscribed = False
        router = getattr(self._controller, "motor_router", None)
        if router is not None and hasattr(router, "subscribe_intermediates"):
            try:
                router.subscribe_intermediates(
                    self._device_name, self._motor_idx, self._chain_idx,
                    self._intermediates_callback,
                )
                self._intermediates_subscribed = True
            except Exception:
                # Defensive — never let a hookup glitch crash widget
                # construction. The chain still works without live
                # graphs; the user just sees empty traces.
                pass

    # ------------------------------------------------------------ public

    def set_motor_value(self, value: float) -> None:
        """Drive the vibe meter. Called from the router's per-tick
        update path. No-op when the meter has been deleted (widget
        tear-down)."""
        try:
            self._vibe_proxy.set(float(value))
        except RuntimeError:
            # Underlying C++ widget already destroyed.
            pass

    # ------------------------------------------------------------ stages

    def _build_stages_strip(self) -> QWidget:
        """The clickable stage row. Depth and Speed are stacked
        vertically in a single column to convey their parallelism;
        every other stage is a single card. Arrow labels separate
        adjacent stages so the chain reads left-to-right."""
        host = QWidget()
        lay = _hbox(0, 6)
        host.setLayout(lay)

        def add(stage_id: str) -> None:
            card = self._make_stage_card(stage_id)
            self._stage_cards[stage_id] = card
            lay.addWidget(card)

        def add_arrow() -> None:
            arrow = QLabel("→")
            af = arrow.font(); af.setPointSize(14); af.setBold(True)
            arrow.setFont(af)
            arrow.setAlignment(Qt.AlignCenter)
            arrow.setFixedWidth(20)
            arrow.setProperty("muted", "true")
            self._ui._repolish(arrow)
            lay.addWidget(arrow)

        add(STAGE_INPUT)
        add_arrow()

        # Depth + Speed in a parallel column.
        ds = QWidget()
        ds_lay = _vbox(0, 4)
        ds.setLayout(ds_lay)
        depth_card = self._make_stage_card(STAGE_DEPTH)
        speed_card = self._make_stage_card(STAGE_SPEED)
        self._stage_cards[STAGE_DEPTH] = depth_card
        self._stage_cards[STAGE_SPEED] = speed_card
        ds_lay.addWidget(depth_card)
        ds_lay.addWidget(speed_card)
        lay.addWidget(ds)

        add_arrow()
        add(STAGE_COMBINE)
        add_arrow()
        add(STAGE_GATE)
        add_arrow()
        add(STAGE_SMOOTHING)
        add_arrow()
        add(STAGE_OUTPUT)
        lay.addStretch(1)
        return host

    def _make_stage_card(self, stage_id: str) -> QFrame:
        card = QFrame()
        card.setObjectName("tuneStageCard")
        card.setCursor(Qt.PointingHandCursor)
        card.setProperty("active", "false")
        card.setMinimumWidth(86)
        lay = _vbox(8, 2)
        card.setLayout(lay)

        title = QLabel(_STAGE_LABELS[stage_id])
        title.setAlignment(Qt.AlignHCenter)
        tf = title.font(); tf.setBold(True)
        title.setFont(tf)
        lay.addWidget(title)

        # Subtitle — one short line summarising the most diagnostic
        # setting for this stage so the user can read the chain
        # at-a-glance without expanding each editor. Refreshed by
        # `_refresh_stage_subtitles` on a timer.
        subtitle = QLabel(self._summary_for_stage(stage_id))
        subtitle.setAlignment(Qt.AlignHCenter)
        sf = subtitle.font()
        sf.setPointSize(max(7, sf.pointSize() - 1))
        subtitle.setFont(sf)
        subtitle.setProperty("muted", "true")
        self._ui._repolish(subtitle)
        lay.addWidget(subtitle)
        self._stage_subtitles[stage_id] = subtitle

        # Valve indicator — only on the Gate stage card. Animates
        # forward when the gate opens, backward when it closes;
        # complements the full ActivityMeter that lives in the gate
        # editor (visible when the stage is expanded).
        if stage_id == STAGE_GATE:
            valve = ValveIndicator()
            lay.addWidget(valve)
            self._stage_valve = valve

        def on_press(ev, sid=stage_id) -> None:
            if ev.button() == Qt.LeftButton:
                self._activate_stage(sid)
                ev.accept()
            else:
                QFrame.mousePressEvent(card, ev)
        card.mousePressEvent = on_press
        return card

    # ----- Stage card subtitle + colour helpers (Cut 7f / 7g) ------

    def _summary_for_stage(self, stage_id: str) -> str:
        """Return the at-a-glance subtitle string for a stage card.
        Reads from the current profile; cheap dict navigation, no
        deep copies. Empty-string return is rendered as one space
        so the layout doesn't collapse when there's nothing to say."""
        chain = _read_chain(
            self._controller, self._device_name, self._motor_idx, self._chain_idx
        )
        if stage_id == STAGE_INPUT:
            # Source count = zones + custom OSC addresses for this motor.
            active = self._controller.get_active_profile_dict() or {}
            dev = active.get(self._device_name, {}) if isinstance(active, dict) else {}
            zone_str = str(dev.get(f"motor_{self._motor_idx}_zones", "") or "")
            zones = [z.strip() for z in zone_str.split(",")
                     if z.strip() and z.strip() != "None"]
            osc_root = dev.get("osc_addresses", {}) if isinstance(dev, dict) else {}
            raw = osc_root.get(str(self._motor_idx), []) if isinstance(osc_root, dict) else []
            if isinstance(raw, str):
                raw = [raw] if raw else []
            if not isinstance(raw, list):
                raw = []
            total = len(zones) + len(raw)
            return f"{total} src" if total else "—"
        if stage_id in (STAGE_DEPTH, STAGE_SPEED):
            cfg = chain.get(stage_id, {}) if isinstance(chain, dict) else {}
            gain = float(cfg.get("gain", 1.0))
            curve = str(cfg.get("curve", "linear"))
            prefix = "" if curve == "linear" else f"{curve[0]} "
            return f"{prefix}×{gain:.2g}"
        if stage_id == STAGE_COMBINE:
            return str(chain.get("combine", "max"))
        if stage_id == STAGE_GATE:
            gate = chain.get("gate", {}) if isinstance(chain, dict) else {}
            if not gate.get("enabled", False):
                return "off"
            return f"≥{float(gate.get('wake_threshold', 0.05)):.2g}"
        if stage_id == STAGE_SMOOTHING:
            sm = chain.get("smoothing", {}) if isinstance(chain, dict) else {}
            rise = float(sm.get("rise_ms", 50))
            fall = float(sm.get("fall_ms", 20))
            return f"↑{rise:.0f}/↓{fall:.0f}ms"
        if stage_id == STAGE_OUTPUT:
            # 3-char subtitle. Linear is special-cased; everything
            # else reads from the shared _KIND_DISPLAY table, with
            # _DEFAULT_KIND_DISPLAY ("vib") for any kind the table
            # doesn't know yet.
            if self._is_linear:
                return "lin"
            info = _KIND_DISPLAY.get(self._motor_kind, _DEFAULT_KIND_DISPLAY)
            return info.subtitle
        return ""

    def _refresh_stage_subtitles(self) -> None:
        """Timer slot — re-reads each stage's summary and writes it
        back to the subtitle label. Guards against destroyed labels
        from rebuilds."""
        for stage_id, label in list(self._stage_subtitles.items()):
            try:
                label.setText(self._summary_for_stage(stage_id))
            except RuntimeError:
                self._stage_subtitles.pop(stage_id, None)

    @staticmethod
    def _lerp_purple_pink(level: float) -> QColor:
        """Lerp the dark-purple→vivid-pink border color by `level`
        in [0, 1]. Out-of-range values clamp."""
        t = max(0.0, min(1.0, float(level)))
        lo = QColor(_STAGE_BORDER_LOW)
        hi = QColor(_STAGE_BORDER_HIGH)
        r = int(lo.red()   + (hi.red()   - lo.red())   * t)
        g = int(lo.green() + (hi.green() - lo.green()) * t)
        b = int(lo.blue()  + (hi.blue()  - lo.blue())  * t)
        return QColor(r, g, b)

    def _apply_stage_card_color(self, stage_id: str, level: float) -> None:
        """Update the stage card's border colour to reflect the
        signal level at that stage. Skips the write when the change
        is below `_STAGE_BORDER_EPSILON` to keep stylesheet churn off
        the hot path. The active-stage selector keeps its green
        border via the inline override below."""
        card = self._stage_cards.get(stage_id)
        if card is None:
            return
        last = self._stage_last_level.get(stage_id, -1.0)
        if abs(level - last) < _STAGE_BORDER_EPSILON:
            return
        self._stage_last_level[stage_id] = level
        color = self._lerp_purple_pink(level)
        # Per-widget stylesheet overrides the global tuneStageCard
        # rules for this widget only. We re-include the bg / radius
        # / padding values so the override is self-contained.
        try:
            card.setStyleSheet(
                f"QFrame#tuneStageCard {{"
                f"  background-color: {COLOR_SURFACE_HOVER};"
                f"  border-radius: 8px;"
                f"  border: 1px solid {color.name()};"
                f"  padding: 4px;"
                f"}}"
                f"QFrame#tuneStageCard[active=\"true\"] {{"
                f"  border: 1px solid {COLOR_SUCCESS};"
                f"  background-color: {COLOR_SURFACE};"
                f"}}"
                f"QFrame#tuneStageCard:hover {{"
                f"  background-color: {COLOR_SURFACE};"
                f"}}"
            )
        except RuntimeError:
            self._stage_cards.pop(stage_id, None)

    def _activate_stage(self, stage_id: str) -> None:
        """Highlight the clicked stage and swap the editor to its
        page. Builds the page on first activation so a card the user
        never opens never pays the construction cost."""
        if stage_id not in _STAGE_ORDER:
            return
        self._active_stage = stage_id
        # Repolish the strip — only the newly-active card flips on.
        for sid, card in self._stage_cards.items():
            card.setProperty("active", "true" if sid == stage_id else "false")
            self._ui._repolish(card)
        if not self._editor_built[stage_id]:
            page = self._build_editor_for(stage_id)
            # Swap the placeholder for the real page at the same index.
            idx = _STAGE_ORDER.index(stage_id)
            old = self._editor_stack.widget(idx)
            self._editor_stack.removeWidget(old)
            old.setParent(None)
            self._editor_stack.insertWidget(idx, page)
            self._editor_pages[stage_id] = page
            self._editor_built[stage_id] = True
        self._editor_stack.setCurrentIndex(_STAGE_ORDER.index(stage_id))

    def _build_editor_for(self, stage_id: str) -> QWidget:
        """Build the editor page for `stage_id` and attach the
        stage's mini-graph below it. The graph receives live samples
        from `_handle_intermediates` once the intermediates
        subscription is wired (which happens in __init__)."""
        if stage_id == STAGE_INPUT:
            inner = self._build_input_editor()
        elif stage_id == STAGE_DEPTH:
            inner = self._build_channel_editor("depth", "Depth")
        elif stage_id == STAGE_SPEED:
            inner = self._build_channel_editor("speed", "Speed")
        elif stage_id == STAGE_COMBINE:
            inner = self._build_combine_editor()
        elif stage_id == STAGE_GATE:
            inner = self._build_gate_editor()
        elif stage_id == STAGE_SMOOTHING:
            inner = self._build_smoothing_editor()
        elif stage_id == STAGE_OUTPUT:
            inner = self._build_output_editor()
        else:
            return QWidget()
        # Drop any stale graph reference from a previous build of
        # this stage (Reset-to-defaults rebuilds editor pages).
        self._stage_graphs.pop(stage_id, None)
        graph = self._make_stage_graph(stage_id)
        if graph is None:
            return inner
        # Wrap: editor on top, graph below.
        host = QFrame()
        host.setObjectName("stageEditorHost")
        lay = _vbox(0, 6)
        host.setLayout(lay)
        lay.addWidget(inner)
        lay.addWidget(graph)
        self._stage_graphs[stage_id] = graph
        return host

    def _make_stage_graph(self, stage_id: str) -> Optional[_TraceGraph]:
        """Build the TraceGraph for a stage's mapped traces. Returns
        None for stages with no traces (none today — every stage in
        _STAGE_TRACES has at least one trace)."""
        trace_ids = _STAGE_TRACES.get(stage_id, ())
        if not trace_ids:
            return None
        traces = [_trace_spec(tid) for tid in trace_ids]
        graph = _TraceGraph(traces=traces, window_s=_STAGE_GRAPH_WINDOW_S)
        graph.setFixedHeight(60)
        return graph

    def _handle_intermediates(self, payload: Dict[str, Any]) -> None:
        """Slot — runs on the UI thread (cross-thread emit auto-queues
        via Qt.QueuedConnection). Pushes samples to every built stage
        graph, refreshes the activity meter, updates the per-stage
        border colors (Cut 7f), and drives the valve indicator on the
        gate stage card (Cut 7h)."""
        try:
            t_s = float(payload.get("t_ms", 0.0)) / 1000.0
        except (TypeError, ValueError):
            return
        # Push per-stage graph samples.
        for stage_id, graph in list(self._stage_graphs.items()):
            try:
                for trace_id in _STAGE_TRACES.get(stage_id, ()):
                    v = payload.get(trace_id)
                    if v is None:
                        continue
                    try:
                        fv = float(v)
                    except (TypeError, ValueError):
                        continue
                    graph.push_sample(trace_id, t_s, fv)
            except RuntimeError:
                # C++ widget gone between dispatch and slot. Drop the
                # ref so we stop trying to push to it.
                self._stage_graphs.pop(stage_id, None)
        # Activity meter (gate editor, when expanded).
        if self._activity_meter is not None:
            try:
                self._activity_meter.set_value(
                    float(payload.get("activity", 0.0))
                )
                self._activity_meter.set_open(
                    bool(payload.get("gate_open", False))
                )
            except (TypeError, ValueError, RuntimeError):
                pass
        # Per-stage border colour lerp — picks the level trace per
        # stage from the mapping table. Cheap because the apply
        # method short-circuits when the change is below epsilon.
        for stage_id, trace_id in _STAGE_LEVEL_TRACE.items():
            v = payload.get(trace_id)
            if v is None:
                continue
            try:
                level = float(v)
            except (TypeError, ValueError):
                continue
            self._apply_stage_card_color(stage_id, level)
        # Valve indicator on the gate stage card — slides the bar
        # forward on open, back on close. Animation handles the
        # interpolation; we just set the target.
        if self._stage_valve is not None:
            try:
                self._stage_valve.set_open(
                    bool(payload.get("gate_open", False))
                )
            except RuntimeError:
                self._stage_valve = None

    def teardown(self) -> None:
        """Unsubscribe from the router so its dispatcher stops trying
        to push payloads at a widget about to be destroyed. The
        wrapper (`MotorChainListWidget._rebuild`) calls this before
        deleteLater'ing each chain widget."""
        if not self._intermediates_subscribed:
            return
        router = getattr(self._controller, "motor_router", None)
        if router is not None and hasattr(router, "unsubscribe_intermediates"):
            try:
                router.unsubscribe_intermediates(
                    self._device_name, self._motor_idx, self._chain_idx,
                    self._intermediates_callback,
                )
            except Exception:
                pass
        self._intermediates_subscribed = False

    # ------------------------------------------------------------ editors

    def _build_input_editor(self) -> QWidget:
        """Reuses the existing _build_listening_to_column on the UI
        mixin — same zone selector / OSC chips / interaction filter
        controls the user already knows. Wrapped here so the chain
        widget owns the editor frame."""
        host = QFrame()
        host.setObjectName("stageEditor")
        lay = _vbox(8, 8)
        host.setLayout(lay)
        # Pull osc_addresses for this motor from the active profile so
        # the chip list seeds correctly on first build.
        active = self._controller.get_active_profile_dict() or {}
        dev_cfg = active.get(self._device_name, {}) if isinstance(active, dict) else {}
        osc_addresses = dev_cfg.get("osc_addresses", {}) if isinstance(dev_cfg, dict) else {}
        listen_col = self._ui._build_listening_to_column(
            self._device_name, self._motor_idx, osc_addresses or {}
        )
        lay.addWidget(listen_col)
        return host

    def _build_channel_editor(self, channel_key: str, label: str) -> QWidget:
        """Depth / Speed editor — gain spinbox + curve combo + param
        spinbox. The `enabled`, `mode`, and channel-specific "More"
        knobs from the old schema are gone (see MOTOR_SIGNAL_CHAIN.md
        § "Per-stage details")."""
        host = QFrame()
        host.setObjectName("stageEditor")
        lay = _vbox(10, 8)
        host.setLayout(lay)

        header = QLabel(label)
        hf = header.font(); hf.setBold(True)
        header.setFont(hf)
        lay.addWidget(header)

        chain = _read_chain(self._controller, self._device_name, self._motor_idx, self._chain_idx)
        cfg = chain.get(channel_key, {}) if isinstance(chain, dict) else {}

        # Gain.
        gain_row = _hbox(0, 8)
        gain_row.addWidget(QLabel("Gain:"))
        gain_spin = QDoubleSpinBox()
        gain_spin.setRange(0.0, 2.0)
        gain_spin.setSingleStep(0.05)
        gain_spin.setDecimals(2)
        gain_spin.setValue(float(cfg.get("gain", 1.0)))
        gain_spin.valueChanged.connect(
            lambda v, ck=channel_key: _update_chain_field(
                self._controller, self._device_name, self._motor_idx, self._chain_idx,
                (ck, "gain"), float(v),
            )
        )
        gain_row.addWidget(gain_spin)
        gain_row.addStretch(1)
        lay.addLayout(gain_row)

        # Curve + param.
        curve_row = _hbox(0, 8)
        curve_row.addWidget(QLabel("Curve:"))
        curve_combo = QComboBox()
        curve_combo.addItems(list(_CURVE_KINDS))
        curr_curve = str(cfg.get("curve", "linear"))
        if curr_curve in _CURVE_KINDS:
            curve_combo.setCurrentText(curr_curve)
        curve_row.addWidget(curve_combo)

        param_label = QLabel("Param:")
        curve_row.addWidget(param_label)
        param_spin = QDoubleSpinBox()
        param_spin.setSingleStep(0.1)
        param_spin.setDecimals(2)
        param_spin.setRange(0.3, 8.0)
        param_spin.setValue(float(cfg.get("curve_param", 1.0)))
        curve_row.addWidget(param_spin)
        curve_row.addStretch(1)

        def sync_param_range(curve_text: str) -> None:
            if curve_text == "linear":
                param_label.setEnabled(False)
                param_spin.setEnabled(False)
            elif curve_text == "power":
                param_label.setEnabled(True)
                param_spin.setEnabled(True)
                param_spin.setRange(0.3, 3.0)
                param_spin.setDecimals(2)
                param_spin.setSingleStep(0.1)
            else:  # s_curve
                param_label.setEnabled(True)
                param_spin.setEnabled(True)
                param_spin.setRange(1.0, 8.0)
                param_spin.setDecimals(0)
                param_spin.setSingleStep(1.0)
        sync_param_range(curve_combo.currentText())

        def on_curve_changed(text: str, ck=channel_key) -> None:
            _update_chain_field(
                self._controller, self._device_name, self._motor_idx, self._chain_idx,
                (ck, "curve"), text,
            )
            sync_param_range(text)

        def on_param_changed(val: float, ck=channel_key) -> None:
            _update_chain_field(
                self._controller, self._device_name, self._motor_idx, self._chain_idx,
                (ck, "curve_param"), float(val),
            )
        curve_combo.currentTextChanged.connect(on_curve_changed)
        param_spin.valueChanged.connect(on_param_changed)
        lay.addLayout(curve_row)
        return host

    def _build_combine_editor(self) -> QWidget:
        """Combine policy — segmented Add / Max / Multiply."""
        host = QFrame()
        host.setObjectName("stageEditor")
        lay = _vbox(10, 8)
        host.setLayout(lay)

        header = QLabel("Combine")
        hf = header.font(); hf.setBold(True)
        header.setFont(hf)
        lay.addWidget(header)

        chain = _read_chain(self._controller, self._device_name, self._motor_idx, self._chain_idx)
        current = str(chain.get("combine", "max"))
        if current not in _COMBINE_OPS:
            current = "max"

        row = _hbox(0, 12)
        row.addWidget(QLabel("Op:"))
        group = QButtonGroup(host)
        group.setExclusive(True)
        buttons: Dict[str, QPushButton] = {}
        for op in _COMBINE_OPS:
            btn = QPushButton(op.capitalize())
            btn.setCheckable(True)
            btn.setFixedHeight(BTN_HEIGHT_SMALL)
            btn.setChecked(op == current)
            group.addButton(btn)
            buttons[op] = btn
            row.addWidget(btn)
        row.addStretch(1)

        def apply_styles() -> None:
            for op, btn in buttons.items():
                btn.setProperty("role", "segActive" if btn.isChecked() else "segIdle")
                self._ui._repolish(btn)
        apply_styles()

        def on_clicked(_=False) -> None:
            new_op = next(op for op, btn in buttons.items() if btn.isChecked())
            _update_chain_field(
                self._controller, self._device_name, self._motor_idx, self._chain_idx,
                ("combine",), new_op,
            )
            apply_styles()
        for btn in buttons.values():
            btn.clicked.connect(on_clicked)
        lay.addLayout(row)

        # One-line hint about Multiply's "zero kills output" semantics —
        # the diagram makes it visible but a hint is cheap insurance.
        hint = QLabel(
            "Add: sum of channels (clamped). Max: louder wins. "
            "Multiply: either channel at 0 → output 0."
        )
        hint.setProperty("muted", "true")
        hint.setWordWrap(True)
        self._ui._repolish(hint)
        lay.addWidget(hint)
        return host

    def _build_gate_editor(self) -> QWidget:
        """Activity gate — enable toggle + wake threshold + sleep
        delay + the activity meter visual."""
        host = QFrame()
        host.setObjectName("stageEditor")
        lay = _vbox(10, 8)
        host.setLayout(lay)

        header = QLabel("Activity gate")
        hf = header.font(); hf.setBold(True)
        header.setFont(hf)
        lay.addWidget(header)

        explain = QLabel(
            "Sidechain valve. Observes the speed detector's output; "
            "opens when activity crosses Wake threshold; closes after "
            "activity stays below threshold for Sleep delay seconds. "
            "Off by default."
        )
        explain.setProperty("muted", "true")
        explain.setWordWrap(True)
        self._ui._repolish(explain)
        lay.addWidget(explain)

        chain = _read_chain(self._controller, self._device_name, self._motor_idx, self._chain_idx)
        gate_cfg = chain.get("gate", {}) if isinstance(chain, dict) else {}

        # Enable toggle.
        enable_cb = ToggleSwitch("Enable")
        enable_cb.setChecked(bool(gate_cfg.get("enabled", False)))
        enable_cb.toggled.connect(
            lambda v: _update_chain_field(
                self._controller, self._device_name, self._motor_idx, self._chain_idx,
                ("gate", "enabled"), bool(v),
            )
        )
        lay.addWidget(enable_cb)

        # Wake threshold.
        wt_row = _hbox(0, 8)
        wt_row.addWidget(QLabel("Wake threshold:"))
        wt_spin = QDoubleSpinBox()
        wt_spin.setRange(0.0, 1.0)
        wt_spin.setSingleStep(0.01)
        wt_spin.setDecimals(2)
        wt_spin.setValue(float(gate_cfg.get("wake_threshold", 0.05)))
        wt_spin.valueChanged.connect(self._on_wake_threshold_changed)
        wt_row.addWidget(wt_spin)
        wt_row.addStretch(1)
        lay.addLayout(wt_row)

        # Sleep delay.
        sd_row = _hbox(0, 8)
        sd_row.addWidget(QLabel("Sleep delay (s):"))
        sd_spin = QDoubleSpinBox()
        sd_spin.setRange(0.0, 10.0)
        sd_spin.setSingleStep(0.1)
        sd_spin.setDecimals(1)
        sd_spin.setValue(float(gate_cfg.get("sleep_delay_s", 0.5)))
        sd_spin.valueChanged.connect(
            lambda v: _update_chain_field(
                self._controller, self._device_name, self._motor_idx, self._chain_idx,
                ("gate", "sleep_delay_s"), float(v),
            )
        )
        sd_row.addWidget(sd_spin)
        sd_row.addStretch(1)
        lay.addLayout(sd_row)

        # Activity meter visual.
        meter_label = QLabel("Activity")
        meter_label.setProperty("muted", "true")
        self._ui._repolish(meter_label)
        lay.addWidget(meter_label)
        meter = ActivityMeter()
        meter.set_threshold(float(gate_cfg.get("wake_threshold", 0.05)))
        lay.addWidget(meter)
        self._activity_meter = meter
        return host

    def _on_wake_threshold_changed(self, val: float) -> None:
        """Spinbox is the canonical store; the activity meter visual
        mirrors it so the tick mark moves with the user's edit even
        before live data flows in."""
        _update_chain_field(
            self._controller, self._device_name, self._motor_idx, self._chain_idx,
            ("gate", "wake_threshold"), float(val),
        )
        if self._activity_meter is not None:
            try:
                self._activity_meter.set_threshold(float(val))
            except RuntimeError:
                pass

    def _build_smoothing_editor(self) -> QWidget:
        """Rise / fall envelope follower. Same math as the old
        Phase 2 smoothing block, just renamed for clarity."""
        host = QFrame()
        host.setObjectName("stageEditor")
        lay = _vbox(10, 8)
        host.setLayout(lay)

        header = QLabel("Smoothing")
        hf = header.font(); hf.setBold(True)
        header.setFont(hf)
        lay.addWidget(header)

        explain = QLabel(
            "Post-gate envelope follower. Rise controls how fast the "
            "output ramps up; Fall how fast it decays. Same knobs "
            "round the gate's open/close transitions."
        )
        explain.setProperty("muted", "true")
        explain.setWordWrap(True)
        self._ui._repolish(explain)
        lay.addWidget(explain)

        chain = _read_chain(self._controller, self._device_name, self._motor_idx, self._chain_idx)
        sm_cfg = chain.get("smoothing", {}) if isinstance(chain, dict) else {}

        row = _hbox(0, 8)
        row.addWidget(QLabel("Rise:"))
        rise_spin = QDoubleSpinBox()
        rise_spin.setRange(0.0, 2000.0)
        rise_spin.setSingleStep(10.0)
        rise_spin.setDecimals(0)
        rise_spin.setSuffix(" ms")
        rise_spin.setValue(float(sm_cfg.get("rise_ms", 50.0)))
        rise_spin.valueChanged.connect(
            lambda v: _update_chain_field(
                self._controller, self._device_name, self._motor_idx, self._chain_idx,
                ("smoothing", "rise_ms"), float(v),
            )
        )
        row.addWidget(rise_spin)
        row.addSpacing(12)
        row.addWidget(QLabel("Fall:"))
        fall_spin = QDoubleSpinBox()
        fall_spin.setRange(0.0, 2000.0)
        fall_spin.setSingleStep(10.0)
        fall_spin.setDecimals(0)
        fall_spin.setSuffix(" ms")
        fall_spin.setValue(float(sm_cfg.get("fall_ms", 20.0)))
        fall_spin.valueChanged.connect(
            lambda v: _update_chain_field(
                self._controller, self._device_name, self._motor_idx, self._chain_idx,
                ("smoothing", "fall_ms"), float(v),
            )
        )
        row.addWidget(fall_spin)
        row.addStretch(1)
        lay.addLayout(row)
        return host

    def _build_output_editor(self) -> QWidget:
        """For vibrate motors, the Output editor is informational only
        (the vibe meter lives at the card bottom, always visible). For
        linear actuators, this is where Mode / Idle / Stroke setup
        live."""
        host = QFrame()
        host.setObjectName("stageEditor")
        lay = _vbox(10, 8)
        host.setLayout(lay)

        header = QLabel("Output")
        hf = header.font(); hf.setBold(True)
        header.setFont(hf)
        lay.addWidget(header)

        if not self._is_linear:
            # Continuous-output actuator — the chain's post-smoothing
            # value drives whichever physical effect the buttplug.io
            # OutputType describes. Phrase looked up from the shared
            # _KIND_DISPLAY table; unknown kinds fall back to the
            # vibrate phrasing.
            info = _KIND_DISPLAY.get(self._motor_kind, _DEFAULT_KIND_DISPLAY)
            note = QLabel(
                f"Continuous output — final post-smoothing value drives "
                f"the {info.output_phrase}. Use the meter below the "
                f"chain to see the live output."
            )
            note.setProperty("muted", "true")
            note.setWordWrap(True)
            self._ui._repolish(note)
            lay.addWidget(note)
            return host

        # Linear actuator controls — Mode + Idle + stroke setup.
        ctrl = self._controller
        dev = self._device_name
        midx = self._motor_idx

        def get_cfg(key: str, default: Any) -> Any:
            return ctrl.get_profile_config(dev, f"motor_{midx}_{key}", default)

        def set_cfg(key: str, value: Any) -> None:
            ctrl.update_device_config(dev, f"motor_{midx}_{key}", value)
            if hasattr(ctrl, "save_profiles"):
                ctrl.save_profiles()
            if hasattr(ctrl, "update_linear_motor_config"):
                ctrl.update_linear_motor_config(dev, midx)

        # Mode segmented.
        mode_row = _hbox(0, 12)
        mode_row.addWidget(QLabel("Mode:"))
        current_mode = get_cfg("linear_mode", "position")
        mode_group = self._make_segmented(
            options=("Position", "Speed"),
            current="Speed" if current_mode == "speed" else "Position",
            on_change=lambda val: set_cfg("linear_mode", val.lower()),
        )
        mode_row.addWidget(mode_group)
        mode_row.addSpacing(12)
        mode_row.addWidget(QLabel("Idle:"))
        current_idle = get_cfg("linear_idle", "rest")
        idle_group = self._make_segmented(
            options=("Hold", "Rest"),
            current="Hold" if current_idle == "hold" else "Rest",
            on_change=lambda val: set_cfg("linear_idle", val.lower()),
        )
        mode_row.addWidget(idle_group)
        mode_row.addStretch(1)
        lay.addLayout(mode_row)

        # Stroke setup expander.
        stroke_btn = QPushButton("▸ Stroke setup")
        stroke_btn.setFixedHeight(BTN_HEIGHT_SMALL)
        stroke_btn.setProperty("role", "secondary")
        stroke_panel = QFrame()
        stroke_panel.setObjectName("moreSection")
        stroke_lay = _vbox(8, 4)
        stroke_panel.setLayout(stroke_lay)
        stroke_panel.setVisible(False)

        knob_specs = (
            ("min_pos",        "Min position:",     0.0, 1.0,  0.05, 2, 0.0),
            ("max_pos",        "Max position:",     0.0, 1.0,  0.05, 2, 1.0),
            ("resting_pos",    "Resting position:", 0.0, 1.0,  0.05, 2, 0.0),
            ("resting_time_s", "Resting time (s):", 0.0, 60.0, 0.5,  2, 3.0),
        )
        for key, label, lo, hi, step, decimals, default in knob_specs:
            krow = _hbox(0, 8)
            krow.addWidget(QLabel(label))
            spin = QDoubleSpinBox()
            spin.setRange(lo, hi)
            spin.setSingleStep(step)
            spin.setDecimals(decimals)
            try:
                spin.setValue(float(get_cfg(key, default)))
            except (TypeError, ValueError):
                spin.setValue(default)
            spin.valueChanged.connect(
                lambda v, k=key: set_cfg(k, float(v))
            )
            krow.addWidget(spin)
            krow.addStretch(1)
            stroke_lay.addLayout(krow)

        def toggle_stroke() -> None:
            new_state = not stroke_panel.isVisible()
            stroke_panel.setVisible(new_state)
            stroke_btn.setText("▾ Stroke setup" if new_state else "▸ Stroke setup")
        stroke_btn.clicked.connect(toggle_stroke)
        lay.addWidget(stroke_btn)
        lay.addWidget(stroke_panel)
        return host

    def _make_segmented(self, options: Tuple[str, ...], current: str,
                        on_change: Callable[[str], None]) -> QWidget:
        """Two-or-three-button segmented control — same shape as
        device_frame's _make_segmented (kept local so the widget
        doesn't reach into the mixin's helpers)."""
        host = QWidget()
        h = _hbox(0, 2)
        host.setLayout(h)
        group = QButtonGroup(host)
        group.setExclusive(True)

        buttons: List[QPushButton] = []
        for opt in options:
            b = QPushButton(opt)
            b.setCheckable(True)
            b.setFixedHeight(24)
            b.setChecked(opt == current)
            group.addButton(b)
            h.addWidget(b)
            buttons.append(b)

        def apply_styles() -> None:
            for btn in buttons:
                btn.setProperty("role", "segActive" if btn.isChecked() else "segIdle")
                self._ui._repolish(btn)
        apply_styles()

        def on_clicked(btn: QPushButton) -> None:
            apply_styles()
            on_change(btn.text())

        group.buttonClicked.connect(on_clicked)
        return host

    # ------------------------------------------------------------ reset

    def _on_reset_clicked(self) -> None:
        """Wipe THIS chain's settings back to defaults — not the whole
        motor. Single-chain motors are unchanged in behaviour; the
        secondary chain (Cut 5) can be reset independently of the
        primary. After the reset, rebuild every already-constructed
        editor page so spinboxes show the new values."""
        _reset_chain_to_defaults(
            self._controller, self._device_name, self._motor_idx,
            self._chain_idx,
        )
        # Re-create any built editor pages so their spinboxes refresh.
        for sid, was_built in list(self._editor_built.items()):
            if not was_built:
                continue
            idx = _STAGE_ORDER.index(sid)
            old = self._editor_stack.widget(idx)
            self._editor_stack.removeWidget(old)
            old.setParent(None)
            new_page = self._build_editor_for(sid)
            self._editor_stack.insertWidget(idx, new_page)
            self._editor_pages[sid] = new_page
        # Re-activate the previously-active stage so the stack shows it.
        self._activate_stage(self._active_stage)


# ----------------------------------------------------------
# MotorChainListWidget — Cut 5 wrapper for 1-or-2 chains.
# ----------------------------------------------------------

class MotorChainListWidget(QFrame):
    """Container that holds one or two `MotorSignalChainWidget`s for
    a single motor, plus the +Add / Remove controls and the merge
    picker between chains. Per the design lock in
    MOTOR_SIGNAL_CHAIN.md § "Future: optional secondary chain",
    chains are capped at 2.

    Single-chain motors render exactly like today (one chain widget
    + a small "+ Add chain" button below). Two-chain motors show
    both chain widgets stacked with a merge picker between them and
    a "Remove this chain" button next to each.

    Public API (same shape as MotorSignalChainWidget — both
    Device Routing and Tune talk to the wrapper the same way they
    used to talk to the single widget):
        set_motor_value(value)  → routes to every chain's vibe meter

    Activity-meter and per-stage trace updates are driven by each
    chain widget's own router subscription — no wrapper-level fan-out
    needed for those signals.
    """

    def __init__(self, ui, device_name: str, motor_idx: int,
                 motor_kind: Optional[str] = None,
                 parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._ui = ui
        self._controller = ui.controller
        self._device_name = device_name
        self._motor_idx = motor_idx
        self._motor_kind = motor_kind

        # Cut 7 simulator state — survives _rebuild because the
        # wrapper itself isn't rebuilt; only its children are. The
        # closures registered as chain providers capture this dict by
        # reference so live UI control changes propagate without
        # restarting the simulator.
        self._sim_state: Dict[str, Any] = {
            "freq":         1.0,
            "amp":          1.0,
            "waveform":     "sine",
            "drive":        _DRIVE_BOTH,
            "send_to_toy":  False,
            "start_time":   0.0,
            "running":      False,
        }
        self._sim_expanded: bool = False
        # Mutated in place (never reassigned) so the destroyed-signal
        # cleanup closure below can hold a stable reference.
        self._sim_active_chain_idxs: List[int] = []
        # Per-rebuild widget refs — repopulated each `_rebuild`.
        self._sim_play_btn: Optional[QPushButton] = None
        self._sim_stop_btn: Optional[QPushButton] = None
        self._sim_status_label: Optional[QLabel] = None

        # Cut 8a Overview state. Off by default — the per-stage
        # mini-graphs in each chain card cover most of what the user
        # needs; the overview is an opt-in "show me everything at
        # once". Subscription only lives while expanded.
        self._overview_expanded: bool = False
        self._overview_chain_idx: int = 0
        self._overview_graph: Optional[_TraceGraph] = None
        self._overview_subscriber: Optional[Callable[[Dict[str, Any]], None]] = None
        self._overview_subscribed_key: Optional[Tuple[str, int, int]] = None

        # Don't paint our own border — the chain widgets already have
        # the motorBlock style. The wrapper is just a layout container.
        self._chain_widgets: List["MotorSignalChainWidget"] = []
        self._root_lay = _vbox(0, 10)
        self.setLayout(self._root_lay)
        self._rebuild()

        # Hard-stop the simulator if the wrapper is destroyed before
        # the user clicks Stop (e.g. toy deleted, profile switched).
        # Capture refs by value/by-reference; the closure must not
        # touch `self` because the Python wrapper may be partially
        # finalised at destroyed-signal time.
        router_ref = getattr(self._controller, "motor_router", None)
        dev_ref = self._device_name
        motor_ref = self._motor_idx
        sim_state_ref = self._sim_state
        active_idxs_ref = self._sim_active_chain_idxs

        # Overview subscriber state — captured by reference so the
        # destroyed-signal closure can tear it down without touching
        # `self`. A list holding (cb, key) tuples is mutated in place
        # by the subscribe/unsubscribe helpers.
        overview_sub_ref: List[Tuple[Callable, Tuple[str, int, int]]] = []
        self._overview_destroy_handle = overview_sub_ref

        def _on_destroyed(*_args) -> None:
            sim_state_ref["running"] = False
            if router_ref is None:
                return
            for chain_idx in list(active_idxs_ref):
                try:
                    router_ref.clear_chain_value_provider(
                        dev_ref, motor_ref, chain_idx
                    )
                except Exception:
                    pass
            try:
                router_ref.unsuppress_toy_output(dev_ref, motor_ref)
            except Exception:
                pass
            # Overview unsubscribe.
            for cb, (d, m, c) in list(overview_sub_ref):
                try:
                    router_ref.unsubscribe_intermediates(d, m, c, cb)
                except Exception:
                    pass
            overview_sub_ref.clear()

        self.destroyed.connect(_on_destroyed)

    # ------------------------------------------------------------ public

    def set_motor_value(self, value: float) -> None:
        """Drive every chain widget's vibe meter with the merged final
        motor target. Each chain widget shows the same value because
        the router emits only the merged output through the existing
        per-motor update path; per-chain output broadcast is a future
        iteration's job."""
        for w in self._chain_widgets:
            try:
                w.set_motor_value(value)
            except RuntimeError:
                pass

    # ------------------------------------------------------------ build

    def _rebuild(self) -> None:
        """Tear down and reconstruct the wrapper's contents based on
        the current chain count in the profile. Called from __init__
        and after every add/remove. Cheap because the chain widgets
        are stateless — they re-read from the profile on construction.

        The simulator is stopped first so any in-flight chain
        providers / toy suppression don't leak past a chain-count
        change. The user has to click Play again after add/remove.

        Subscriptions on outgoing chain widgets are torn down before
        their C++ peers die so the router's per-tick dispatcher stops
        trying to push samples to widgets about to be destroyed."""
        # Stop any running simulator before tearing down UI; this
        # also clears chain providers and toy-output suppression so
        # the new layout starts from a clean slate.
        self._stop_simulator(refresh_ui=False)
        # Drop stale per-rebuild widget refs so _refresh_sim_button_state
        # treats them as not-yet-built until the new panel is added.
        self._sim_play_btn = None
        self._sim_stop_btn = None
        self._sim_status_label = None
        # Unsubscribe the overview before its TraceGraph dies in the
        # layout-clear loop. Otherwise the next subscribe in the new
        # panel short-circuits because the subscriber attribute is
        # still non-None.
        self._unsubscribe_overview()
        self._overview_graph = None
        # Tear down intermediates subscriptions before deleting.
        for w in self._chain_widgets:
            try:
                w.teardown()
            except (RuntimeError, AttributeError):
                pass
        # Clear existing children.
        while self._root_lay.count():
            item = self._root_lay.takeAt(0)
            w = item.widget()
            if w is not None:
                w.setParent(None)
                w.deleteLater()
            else:
                lay = item.layout()
                if lay is not None:
                    # Layouts inserted via addLayout: detach and drop.
                    while lay.count():
                        sub = lay.takeAt(0)
                        sw = sub.widget()
                        if sw is not None:
                            sw.setParent(None)
                            sw.deleteLater()
        self._chain_widgets.clear()

        # Simulator panel always at the top (Cut 7).
        self._root_lay.addWidget(self._build_simulator_panel())

        n = _get_chain_count(self._controller, self._device_name, self._motor_idx)
        n = max(1, min(n, MAX_CHAINS_PER_MOTOR))
        # Clamp the overview chain index if a remove dropped it
        # below the new count.
        if self._overview_chain_idx >= n:
            self._overview_chain_idx = 0
        for chain_idx in range(n):
            if chain_idx > 0:
                # Merge picker sits between chains. Only meaningful
                # when there are 2+; hidden by virtue of the loop
                # condition for single-chain motors.
                self._root_lay.addWidget(self._build_merge_row())
            chain_widget = MotorSignalChainWidget(
                self._ui, self._device_name, self._motor_idx,
                self._motor_kind, chain_idx=chain_idx,
            )
            self._chain_widgets.append(chain_widget)
            self._root_lay.addWidget(chain_widget)
            # Remove button only when the motor has more than one
            # chain — never let the user delete the only chain.
            if n > 1:
                self._root_lay.addWidget(self._build_remove_row(chain_idx))
        if n < MAX_CHAINS_PER_MOTOR:
            self._root_lay.addWidget(self._build_add_row())

        # Overview disclosure last (Cut 8a). Off-by-default; the
        # panel rebuilds with the current expanded state and
        # re-subscribes if necessary.
        self._root_lay.addWidget(self._build_overview_panel(n))

    def _build_merge_row(self) -> QWidget:
        """Horizontal separator with `Merge: [Add] [Max] [Multiply]`.
        Sits between chain widgets when n > 1. Hidden for n == 1."""
        host = QFrame()
        host.setObjectName("chainMergeRow")
        lay = _hbox(0, 8)
        host.setLayout(lay)
        label = QLabel("Merge chains:")
        lf = label.font(); lf.setBold(True)
        label.setFont(lf)
        lay.addWidget(label)

        current = _get_merge_op(
            self._controller, self._device_name, self._motor_idx
        )
        group = QButtonGroup(host)
        group.setExclusive(True)
        buttons: Dict[str, QPushButton] = {}
        for op in _MERGE_OPS:
            btn = QPushButton(op.capitalize())
            btn.setCheckable(True)
            btn.setFixedHeight(BTN_HEIGHT_SMALL)
            btn.setChecked(op == current)
            group.addButton(btn)
            buttons[op] = btn
            lay.addWidget(btn)

        def apply_styles() -> None:
            for op, b in buttons.items():
                b.setProperty("role", "segActive" if b.isChecked() else "segIdle")
                self._ui._repolish(b)
        apply_styles()

        def on_clicked(_=False) -> None:
            new_op = next(op for op, b in buttons.items() if b.isChecked())
            _set_merge_op(
                self._controller, self._device_name, self._motor_idx, new_op
            )
            apply_styles()
        for b in buttons.values():
            b.clicked.connect(on_clicked)

        lay.addStretch(1)
        return host

    def _build_remove_row(self, chain_idx: int) -> QWidget:
        """Right-aligned 'Remove this chain' button. Only added when
        n > 1; clicking it shrinks the list back to one chain and
        rebuilds the wrapper."""
        host = QWidget()
        lay = _hbox(0, 0)
        host.setLayout(lay)
        lay.addStretch(1)
        btn = QPushButton(f"✕ Remove Chain {chain_idx + 1}")
        btn.setFixedHeight(BTN_HEIGHT_SMALL)
        btn.setProperty("role", "danger")
        btn.clicked.connect(lambda _=False, c=chain_idx: self._on_remove_chain(c))
        lay.addWidget(btn)
        return host

    def _build_add_row(self) -> QWidget:
        """Centered '+ Add chain' button shown when n < cap."""
        host = QWidget()
        lay = _hbox(0, 0)
        host.setLayout(lay)
        lay.addStretch(1)
        btn = QPushButton("+ Add chain")
        btn.setFixedHeight(BTN_HEIGHT_SMALL)
        btn.setProperty("role", "secondary")
        btn.setToolTip(
            "Add a second parallel signal chain on this motor. Both "
            "chains process the same input independently; their "
            "outputs combine via the Merge op."
        )
        btn.clicked.connect(self._on_add_chain)
        lay.addWidget(btn)
        lay.addStretch(1)
        return host

    # ------------------------------------------------------------ handlers

    def _on_add_chain(self) -> None:
        if _add_chain(self._controller, self._device_name, self._motor_idx):
            self._rebuild()

    def _on_remove_chain(self, chain_idx: int) -> None:
        if _remove_chain(self._controller, self._device_name,
                         self._motor_idx, chain_idx):
            self._rebuild()

    # ------------------------------------------------------------ simulator panel (Cut 7)

    def _build_simulator_panel(self) -> QWidget:
        """Top-of-wrapper collapsible panel with the parametric
        simulator controls. Header is a clickable disclosure; body
        holds frequency / amplitude / waveform / drive (when 2 chains)
        / play / stop / send-to-toy."""
        panel = QFrame()
        panel.setObjectName("simulatorPanel")
        lay = _vbox(8, 6)
        panel.setLayout(lay)

        # --- Header: ▸/▾ disclosure + title + status indicator ---
        header = QWidget()
        header.setCursor(Qt.PointingHandCursor)
        header_lay = _hbox(0, 6)
        header.setLayout(header_lay)
        disclosure = QLabel("▾" if self._sim_expanded else "▸")
        disclosure.setFixedWidth(14)
        header_lay.addWidget(disclosure)
        title = QLabel("Simulated input")
        tf = title.font(); tf.setBold(True)
        title.setFont(tf)
        header_lay.addWidget(title)
        header_lay.addStretch(1)
        status_label = QLabel(
            "● Playing" if self._sim_state["running"] else ""
        )
        status_label.setProperty("role", "success")
        self._ui._repolish(status_label)
        header_lay.addWidget(status_label)
        self._sim_status_label = status_label
        lay.addWidget(header)

        # --- Body: controls. Hidden when collapsed. ---
        body = QFrame()
        body.setObjectName("simulatorBody")
        body_lay = _vbox(6, 6)
        body.setLayout(body_lay)
        body.setVisible(self._sim_expanded)

        # Row 1: frequency + amplitude + waveform
        r1 = _hbox(0, 12)
        r1.addWidget(QLabel("Frequency:"))
        freq_spin = QDoubleSpinBox()
        freq_spin.setRange(0.05, 5.0)
        freq_spin.setSingleStep(0.05)
        freq_spin.setDecimals(2)
        freq_spin.setSuffix(" Hz")
        freq_spin.setValue(float(self._sim_state["freq"]))
        freq_spin.valueChanged.connect(self._on_sim_freq_changed)
        r1.addWidget(freq_spin)
        r1.addSpacing(8)
        r1.addWidget(QLabel("Amplitude:"))
        amp_spin = QDoubleSpinBox()
        amp_spin.setRange(0.0, 1.0)
        amp_spin.setSingleStep(0.05)
        amp_spin.setDecimals(2)
        amp_spin.setValue(float(self._sim_state["amp"]))
        amp_spin.valueChanged.connect(self._on_sim_amp_changed)
        r1.addWidget(amp_spin)
        r1.addSpacing(8)
        r1.addWidget(QLabel("Waveform:"))
        wf_combo = QComboBox()
        wf_combo.addItems(list(_WAVEFORMS))
        if self._sim_state["waveform"] in _WAVEFORMS:
            wf_combo.setCurrentText(self._sim_state["waveform"])
        wf_combo.currentTextChanged.connect(self._on_sim_waveform_changed)
        r1.addWidget(wf_combo)
        r1.addStretch(1)
        body_lay.addLayout(r1)

        # Row 2: drive (when 2 chains) + play / stop + send-to-toy
        r2 = _hbox(0, 12)
        n_chains = _get_chain_count(
            self._controller, self._device_name, self._motor_idx
        )
        if n_chains > 1:
            r2.addWidget(QLabel("Drive:"))
            drive_combo = QComboBox()
            drive_combo.addItems(list(_DRIVE_MODES))
            if self._sim_state["drive"] in _DRIVE_MODES:
                drive_combo.setCurrentText(self._sim_state["drive"])
            else:
                drive_combo.setCurrentText(_DRIVE_BOTH)
                self._sim_state["drive"] = _DRIVE_BOTH
            drive_combo.currentTextChanged.connect(self._on_sim_drive_changed)
            r2.addWidget(drive_combo)
            r2.addSpacing(8)

        play_btn = QPushButton("▶ Play")
        play_btn.setFixedHeight(BTN_HEIGHT_SMALL)
        play_btn.clicked.connect(self._on_sim_play)
        r2.addWidget(play_btn)
        self._sim_play_btn = play_btn

        stop_btn = QPushButton("■ Stop")
        stop_btn.setFixedHeight(BTN_HEIGHT_SMALL)
        stop_btn.setProperty("role", "secondary")
        stop_btn.clicked.connect(self._on_sim_stop)
        r2.addWidget(stop_btn)
        self._sim_stop_btn = stop_btn

        r2.addSpacing(12)
        send_cb = ToggleSwitch("Send to toy")
        send_cb.setChecked(bool(self._sim_state["send_to_toy"]))
        send_cb.toggled.connect(self._on_sim_send_to_toy_changed)
        r2.addWidget(send_cb)
        r2.addStretch(1)
        body_lay.addLayout(r2)

        lay.addWidget(body)

        # Header toggles the body. mousePressEvent on the header
        # widget; buttons/spinboxes inside the body consume their own
        # clicks so toggling there doesn't fire.
        def on_press(ev, body=body, disclosure=disclosure) -> None:
            if ev.button() == Qt.LeftButton:
                self._sim_expanded = not self._sim_expanded
                body.setVisible(self._sim_expanded)
                disclosure.setText("▾" if self._sim_expanded else "▸")
                ev.accept()
            else:
                QWidget.mousePressEvent(header, ev)
        header.mousePressEvent = on_press

        self._refresh_sim_button_state()
        return panel

    # ------------------------------------------------------------ simulator handlers

    def _on_sim_freq_changed(self, v: float) -> None:
        # Closures registered as chain providers read `self._sim_state`
        # by reference, so updating the dict propagates live without
        # restarting the simulator.
        self._sim_state["freq"] = float(v)

    def _on_sim_amp_changed(self, v: float) -> None:
        self._sim_state["amp"] = float(v)

    def _on_sim_waveform_changed(self, text: str) -> None:
        if text in _WAVEFORMS:
            self._sim_state["waveform"] = str(text)

    def _on_sim_drive_changed(self, text: str) -> None:
        # Drive mask change while running needs re-registration —
        # the previously-registered chains may no longer be in the
        # new mask, and new chains may need providers. Stop+start.
        if text not in _DRIVE_MODES:
            return
        was_running = self._sim_state["running"]
        if was_running:
            self._stop_simulator()
        self._sim_state["drive"] = str(text)
        if was_running:
            self._start_simulator()

    def _on_sim_send_to_toy_changed(self, checked: bool) -> None:
        self._sim_state["send_to_toy"] = bool(checked)
        # Apply immediately if the simulator is currently running;
        # otherwise the flag just stays set until the next Play.
        if self._sim_state["running"]:
            self._apply_send_to_toy_suppression()

    def _on_sim_play(self) -> None:
        if self._sim_state["running"]:
            return
        self._start_simulator()

    def _on_sim_stop(self) -> None:
        self._stop_simulator()

    # ------------------------------------------------------------ simulator engine

    def _resolve_drive_chains(self) -> List[int]:
        """Translate the Drive selector value into a list of chain
        indices that should receive the simulated signal. Chains
        beyond the motor's current count are silently dropped."""
        drive = self._sim_state["drive"]
        n = _get_chain_count(
            self._controller, self._device_name, self._motor_idx
        )
        if drive == _DRIVE_CHAIN_1:
            return [0] if n >= 1 else []
        if drive == _DRIVE_CHAIN_2:
            return [1] if n >= 2 else []
        # _DRIVE_BOTH (default for single-chain motors too)
        return list(range(n))

    def _start_simulator(self) -> None:
        router = getattr(self._controller, "motor_router", None)
        if router is None or not hasattr(router, "set_chain_value_provider"):
            return
        self._sim_state["start_time"] = time.monotonic()
        self._sim_state["running"] = True
        # Register one provider closure per chain in the Drive mask.
        # Each closure captures `_sim_state` by reference so live UI
        # changes propagate. The closure also self-aborts if
        # `running` flips to False — defensive against a race between
        # _stop_simulator and the router's hot path.
        target_chains = self._resolve_drive_chains()
        # Mutate in place so the destroyed-signal closure sees the
        # current list of registered chains.
        self._sim_active_chain_idxs.clear()
        self._sim_active_chain_idxs.extend(target_chains)
        sim_state = self._sim_state

        def _make_provider() -> Callable[[], Optional[float]]:
            def _provider() -> Optional[float]:
                if not sim_state["running"]:
                    return None
                t = time.monotonic() - sim_state["start_time"]
                return _sample_pattern(
                    sim_state["freq"], sim_state["amp"],
                    sim_state["waveform"], t,
                )
            return _provider

        for chain_idx in target_chains:
            try:
                router.set_chain_value_provider(
                    self._device_name, self._motor_idx,
                    chain_idx, _make_provider(),
                )
            except Exception:
                pass
        self._apply_send_to_toy_suppression()
        self._refresh_sim_button_state()

    def _stop_simulator(self, refresh_ui: bool = True) -> None:
        """Clear chain providers and unsuppress toy output. Idempotent
        — safe to call when the simulator isn't running. `refresh_ui`
        guards against touching widget refs that are about to be
        destroyed by a parent rebuild."""
        self._sim_state["running"] = False
        router = getattr(self._controller, "motor_router", None)
        if router is not None:
            for chain_idx in list(self._sim_active_chain_idxs):
                try:
                    router.clear_chain_value_provider(
                        self._device_name, self._motor_idx, chain_idx
                    )
                except Exception:
                    pass
            try:
                router.unsuppress_toy_output(
                    self._device_name, self._motor_idx
                )
            except Exception:
                pass
        # Mutate in place — destroyed-signal closure holds a ref.
        self._sim_active_chain_idxs.clear()
        if refresh_ui:
            self._refresh_sim_button_state()

    def _apply_send_to_toy_suppression(self) -> None:
        """Push the wrapper's Send-to-toy flag through to the router's
        suppression set. Called on Play and on Send-to-toy toggle
        while running."""
        router = getattr(self._controller, "motor_router", None)
        if router is None:
            return
        if self._sim_state["send_to_toy"]:
            try:
                router.unsuppress_toy_output(
                    self._device_name, self._motor_idx
                )
            except Exception:
                pass
        else:
            try:
                router.suppress_toy_output(
                    self._device_name, self._motor_idx
                )
            except Exception:
                pass

    # ------------------------------------------------------------ overview (Cut 8a)

    def _build_overview_panel(self, chain_count: int) -> QWidget:
        """Bottom-of-wrapper collapsible 6-trace graph. Header has
        a disclosure caret and (for two-chain motors) a chain picker
        so the user can choose which chain the overview observes.
        Off by default — the graph and its subscription are only
        materialised when expanded."""
        panel = QFrame()
        panel.setObjectName("chainOverviewPanel")
        lay = _vbox(6, 4)
        panel.setLayout(lay)

        # --- Header: disclosure + title + (optional) chain picker ---
        header = QWidget()
        header_lay = _hbox(0, 6)
        header.setLayout(header_lay)
        disclosure = QLabel("▾" if self._overview_expanded else "▸")
        disclosure.setFixedWidth(14)
        header_lay.addWidget(disclosure)
        title = QLabel("Overview")
        tf = title.font(); tf.setBold(True)
        title.setFont(tf)
        header_lay.addWidget(title)
        hint = QLabel("(all six traces)")
        hint.setProperty("muted", "true")
        self._ui._repolish(hint)
        header_lay.addWidget(hint)
        header_lay.addStretch(1)

        if chain_count > 1:
            chain_combo = QComboBox()
            for i in range(chain_count):
                chain_combo.addItem(f"Chain {i + 1}")
            chain_combo.setCurrentIndex(self._overview_chain_idx)
            chain_combo.currentIndexChanged.connect(
                self._on_overview_chain_changed
            )
            header_lay.addWidget(chain_combo)

        # Header is clickable to toggle expansion. Children that
        # consume their own clicks (the chain combo) won't trigger
        # this — Qt dispatches mousePressEvent to the deepest widget
        # under the cursor first.
        header.setCursor(Qt.PointingHandCursor)

        # --- Body: the big graph, hidden when collapsed ---
        body = QFrame()
        body.setObjectName("chainOverviewBody")
        body_lay = _vbox(0, 0)
        body.setLayout(body_lay)
        body.setVisible(self._overview_expanded)

        if self._overview_expanded:
            graph = self._make_overview_graph()
            body_lay.addWidget(graph)
            self._overview_graph = graph
            self._subscribe_overview()
        else:
            self._overview_graph = None

        def on_header_press(ev, body=body, disclosure=disclosure) -> None:
            if ev.button() == Qt.LeftButton:
                self._toggle_overview(body, disclosure, body_lay)
                ev.accept()
            else:
                QWidget.mousePressEvent(header, ev)
        header.mousePressEvent = on_header_press

        lay.addWidget(header)
        lay.addWidget(body)
        return panel

    def _make_overview_graph(self) -> _TraceGraph:
        """Build the 6-trace TraceGraph. Traces use the same styles
        as the per-stage mini-graphs so the visual language matches."""
        traces = [_trace_spec(tid) for tid in _OVERVIEW_TRACE_IDS]
        graph = _TraceGraph(traces=traces, window_s=_OVERVIEW_WINDOW_S)
        graph.setFixedHeight(_OVERVIEW_GRAPH_HEIGHT)
        return graph

    def _toggle_overview(self, body: QWidget, disclosure: QLabel,
                         body_lay) -> None:
        """Flip the disclosure state, build/destroy the graph, and
        wire the router subscription accordingly."""
        self._overview_expanded = not self._overview_expanded
        if self._overview_expanded:
            graph = self._make_overview_graph()
            body_lay.addWidget(graph)
            self._overview_graph = graph
            self._subscribe_overview()
        else:
            self._unsubscribe_overview()
            # Tear down the now-orphan graph widget.
            for i in reversed(range(body_lay.count())):
                item = body_lay.itemAt(i)
                w = item.widget() if item is not None else None
                if w is not None:
                    w.setParent(None)
                    w.deleteLater()
            self._overview_graph = None
        body.setVisible(self._overview_expanded)
        disclosure.setText("▾" if self._overview_expanded else "▸")

    def _on_overview_chain_changed(self, index: int) -> None:
        """Rebind the subscription to the newly-selected chain."""
        new_idx = max(0, int(index))
        if new_idx == self._overview_chain_idx:
            return
        was_subscribed = self._overview_subscriber is not None
        if was_subscribed:
            self._unsubscribe_overview()
        self._overview_chain_idx = new_idx
        if self._overview_expanded and was_subscribed:
            # Clear the graph so the new chain's trace doesn't start
            # mid-window against the old chain's history.
            if self._overview_graph is not None:
                try:
                    self._overview_graph.clear()
                except (RuntimeError, AttributeError):
                    pass
            self._subscribe_overview()

    def _subscribe_overview(self) -> None:
        """Register an intermediates callback for the currently-
        selected overview chain. Idempotent — no-ops if already
        subscribed."""
        if self._overview_subscriber is not None:
            return
        router = getattr(self._controller, "motor_router", None)
        if router is None or not hasattr(router, "subscribe_intermediates"):
            return
        key = (self._device_name, self._motor_idx, self._overview_chain_idx)
        cb = self._make_overview_callback()
        try:
            router.subscribe_intermediates(key[0], key[1], key[2], cb)
            self._overview_subscriber = cb
            self._overview_subscribed_key = key
            # Keep the destroyed-signal cleanup informed.
            self._overview_destroy_handle.append((cb, key))
        except Exception:
            self._overview_subscriber = None
            self._overview_subscribed_key = None

    def _unsubscribe_overview(self) -> None:
        """Remove the current overview subscription if any. Safe to
        call repeatedly."""
        if self._overview_subscriber is None:
            return
        router = getattr(self._controller, "motor_router", None)
        key = self._overview_subscribed_key
        cb = self._overview_subscriber
        self._overview_subscriber = None
        self._overview_subscribed_key = None
        # Drop the matching entry from the destroyed-signal tracker
        # so duplicate teardowns don't try to unsubscribe twice.
        try:
            self._overview_destroy_handle.remove((cb, key))
        except ValueError:
            pass
        if router is None or key is None or not hasattr(router, "unsubscribe_intermediates"):
            return
        try:
            router.unsubscribe_intermediates(key[0], key[1], key[2], cb)
        except Exception:
            pass

    def _make_overview_callback(self) -> Callable[[Dict[str, Any]], None]:
        """Build a callback that pushes the six overview traces onto
        the overview graph. The callback runs on the routing thread
        (router fires from inside _calculate_motor_target); pushing
        a sample to a TraceGraph in PySide6 is thread-safe enough
        for this use case (the paint thread is separate and reads
        the trace buffer with locking)."""
        # Capture graph by closure so the callback can no-op when
        # the graph has been destroyed (between rebuilds).
        def _cb(payload: Dict[str, Any]) -> None:
            graph = self._overview_graph
            if graph is None:
                return
            try:
                t_s = float(payload.get("t_ms", 0.0)) / 1000.0
            except (TypeError, ValueError):
                return
            for trace_id in _OVERVIEW_TRACE_IDS:
                v = payload.get(trace_id)
                if v is None:
                    continue
                try:
                    fv = float(v)
                except (TypeError, ValueError):
                    continue
                try:
                    graph.push_sample(trace_id, t_s, fv)
                except RuntimeError:
                    # C++ TraceGraph gone; the unsubscribe path will
                    # clear the closure shortly.
                    return
        return _cb

    # ------------------------------------------------------------ simulator panel (Cut 7)

    def _refresh_sim_button_state(self) -> None:
        """Sync Play/Stop enabled state and the status label with the
        simulator's running flag. No-ops cleanly when called before
        the panel's widgets exist (or after they've been destroyed
        mid-rebuild)."""
        running = bool(self._sim_state["running"])
        if self._sim_play_btn is not None:
            try:
                self._sim_play_btn.setEnabled(not running)
            except RuntimeError:
                self._sim_play_btn = None
        if self._sim_stop_btn is not None:
            try:
                self._sim_stop_btn.setEnabled(running)
            except RuntimeError:
                self._sim_stop_btn = None
        if self._sim_status_label is not None:
            try:
                self._sim_status_label.setText("● Playing" if running else "")
            except RuntimeError:
                self._sim_status_label = None
