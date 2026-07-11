"""Per-motor signal-chain widget — the user-facing surface for the
Input → Depth/Speed → Combine → Gate → Smoothing → Zero cut → Output
pipeline.

Embedded in two contexts (intentionally — see docs/MOTOR_SIGNAL_CHAIN.md
§ "Tune view, 1:1 with Device Routing"):
  * Device Routing motor card (Cut 3) — primary editing surface.
  * Tune view (Cut 4) — same editing surface plus the multi-trace
    graph and pattern player overlay.

The strip is a horizontal accordion (Cut 9): each stage is a card that
shows a quick control + live output number when collapsed, and expands
in place — pushing its siblings into thin rails — to reveal its full
editor when clicked. Connectors between cards stretch with the motion.
Storage round-trips through the controller facade calls the rest of the
UI already uses (`get_profile_config`, `update_device_config`,
`save_profiles`, `force_recalculate`).

The widget reads the per-motor `mix` block in the chains-list shape
locked in Cut 1 (`mix.<motor>.chains[0].…`). Cuts 1–4 always have
exactly one chain; Cut 5 (optional secondary chain) wraps this
widget in a list container without touching its internals."""

from __future__ import annotations

import copy
import time
from typing import Any, Callable, Dict, List, Optional, Tuple

from PySide6.QtCore import (
    Qt, QTimer, Signal, QVariantAnimation, QEasingCurve, QPoint, QPointF,
    QRectF,
)
from PySide6.QtGui import (
    QColor, QFont, QFontMetrics, QPainter, QPen, QBrush, QPolygonF,
)
from PySide6.QtWidgets import (
    QFrame, QWidget, QLabel, QPushButton, QComboBox, QDoubleSpinBox,
    QButtonGroup, QSlider, QSizePolicy,
)

from constants import (
    BTN_HEIGHT_SMALL, COLOR_SUCCESS, COLOR_ALERT, COLOR_TEXT,
    COLOR_SURFACE, COLOR_SURFACE_HOVER, COLOR_TEXT_MUTED, COLOR_LIVE,
    COLOR_CHAIN_IDLE, COLOR_CHAIN_LIVE,
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


class _NoTrackSpin(QDoubleSpinBox):
    """QDoubleSpinBox whose valueChanged fires on commit (arrows, wheel,
    focus-out, Enter) instead of per typed keystroke. Every spinbox in the
    chain persists straight to profiles.json on valueChanged — typing
    "150" must not write the profile three times."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.setKeyboardTracking(False)


class _ProfileSaveDebouncer:
    """Coalesces per-slider-step profile saves into one disk write.

    `update_device_config` already mutated the live in-memory profile —
    the router reads that, so haptics react to a drag instantly. Only the
    PERSISTENCE (a full serialize + fsync'd atomic replace on the GUI
    thread) is deferred, landing once per gesture instead of once per
    integer step crossed. A pending save lost to app close is covered by
    the controller's close-time profile save."""

    INTERVAL_MS = 600

    def __init__(self) -> None:
        self._timer: Optional[QTimer] = None
        self._controller = None

    def schedule(self, controller) -> None:
        if not hasattr(controller, "save_profiles"):
            return
        self._controller = controller
        if self._timer is None:
            self._timer = QTimer()
            self._timer.setSingleShot(True)
            self._timer.setInterval(self.INTERVAL_MS)
            self._timer.timeout.connect(self._flush)
        self._timer.start()

    def _flush(self) -> None:
        controller, self._controller = self._controller, None
        if controller is None:
            return
        try:
            controller.save_profiles()
        except Exception:
            pass


_save_debouncer = _ProfileSaveDebouncer()


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
    # Apply + recalc are live (the drag stays responsive on the toy);
    # only the disk write is debounced — it used to fsync per slider step.
    _save_debouncer.schedule(controller)
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
    _update_chain_fields(controller, device_name, motor_idx, chain_idx,
                         ((path, value),))


def _update_chain_fields(controller, device_name: str, motor_idx: int,
                         chain_idx: int, updates) -> None:
    """Update several `(path, value)` fields inside `chains[chain_idx]`
    in ONE read-modify-write pass — a control that sets two fields per
    gesture (the delay slider writes rise_ms AND fall_ms) must not pay
    two full write/recalc cycles."""
    per_motor = copy.deepcopy(
        _read_per_motor(controller, device_name, motor_idx)
    )
    chain = _ensure_chain_at(per_motor, chain_idx)
    for path, value in updates:
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


# Stage IDs — kept short and stable; used as the per-stage card key
# and the active-stage marker on the accordion stages strip.
STAGE_INPUT = "input"
STAGE_DEPTH = "depth"
STAGE_SPEED = "speed"
STAGE_COMBINE = "combine"
STAGE_GATE = "gate"
STAGE_SMOOTHING = "smoothing"
STAGE_ZEROCUT = "zerocut"
STAGE_OUTPUT = "output"

_STAGE_ORDER = (
    STAGE_INPUT, STAGE_DEPTH, STAGE_SPEED,
    STAGE_COMBINE, STAGE_GATE, STAGE_SMOOTHING, STAGE_ZEROCUT,
    STAGE_OUTPUT,
)

_STAGE_LABELS = {
    STAGE_INPUT:     "Input",
    STAGE_DEPTH:     "Depth",
    STAGE_SPEED:     "Speed",
    STAGE_COMBINE:   "Combine",
    STAGE_GATE:      "Gate",
    STAGE_SMOOTHING: "Smoothing",
    STAGE_ZEROCUT:   "Zero cut",
    STAGE_OUTPUT:    "Output",
}

# Abbreviated titles shown when a card is squished to a thin rail
# (some other stage is expanded). Full labels would clip; these read
# cleanly at ~48px.
_STAGE_SHORT = {
    STAGE_INPUT:     "In",
    STAGE_DEPTH:     "Dep",
    STAGE_SPEED:     "Spd",
    STAGE_COMBINE:   "Cmb",
    STAGE_GATE:      "Gate",
    STAGE_SMOOTHING: "Smth",
    STAGE_ZEROCUT:   "Cut",
    STAGE_OUTPUT:    "Out",
}

_CURVE_KINDS = ("linear", "power", "s_curve")
_COMBINE_OPS = ("add", "max", "multiply")


# Per-stage trace specifications for the inlined per-stage mini-graphs
# (Cut 6). Mapping is documented in docs/CHAIN_INLINED_TUNING.md §
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
    # Post-smoothing, PRE zero cut — a lighter dashed green so the Zero
    # cut card can show the tail it is cutting against the final `out`.
    "smoothed": ("#7FD9A8", {"width": 1.6, "dash": "dash"}),
    "out":      (COLOR_SUCCESS, {"width": 2.0}),
}

_STAGE_TRACES: Dict[str, Tuple[str, ...]] = {
    STAGE_INPUT:     ("d_raw",),
    STAGE_DEPTH:     ("d_raw", "d_shaped"),
    STAGE_SPEED:     ("s_raw", "s_shaped"),
    STAGE_COMBINE:   ("d_shaped", "s_shaped", "mixed"),
    STAGE_GATE:      ("mixed", "gated"),
    STAGE_SMOOTHING: ("gated", "smoothed"),
    STAGE_ZEROCUT:   ("smoothed", "out"),
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
    STAGE_SMOOTHING: "smoothed",
    STAGE_ZEROCUT:   "out",
    STAGE_OUTPUT:    "out",
}

# Stage card border lerp endpoints. Low (idle) matches the canvas;
# high (saturated) pulls visual attention on a hot motor. Themed via
# the active color profile in constants.py (dark purple → vivid pink
# on the default palette).
_STAGE_BORDER_LOW = COLOR_CHAIN_IDLE
_STAGE_BORDER_HIGH = COLOR_CHAIN_LIVE

# Only repaint the card border when the level has changed by at
# least this much, to keep the stylesheet churn well below the
# router's 90Hz tick.
_STAGE_BORDER_EPSILON = 0.02


# ---- Accordion layout (Cut 9: inline-expand stages strip) ----------
# The stages strip is a horizontal accordion: clicking a card expands
# it in place to reveal its editor while the siblings squish to thin
# rails. Widths are animated; the connectors between cards stretch to
# stay attached.
_RAIL_WIDTH = 54              # squished sibling slot width (thin rail);
                              # sized so the 3-4 char short titles fit with
                              # the rail's zeroed side margins (apply_state)
_CARD_COLLAPSED_MIN = 68      # floor width for a card in the all-collapsed strip
                              # (low so the compact non-slider cards stay narrow)
_EXPANDED_MIN = 280           # floor width for the expanded card body
_CARD_EXPANDED_TARGET = 340   # preferred width for the expanded card body
_ACCORDION_ANIM_MS = 160      # expand/collapse duration (≈ overview.py's 150)
# The connectors live in flexible spacer cells between cards (min width
# _CONNECTOR_GAP, no max). Because the cards are pinned and the spacers
# absorb the row's slack, a connector lengthens as its neighbour expands
# and the far siblings squish — i.e. the arrows genuinely stretch.
_CONNECTOR_GAP = 18           # minimum connector-cell width
_HEADER_CENTER_Y = 17         # connector attach y when a stage is expanded
                              # (cards top-align, arrows ride the header row)
_BRANCH_FANOUT = 12           # vertical spread of the fork/join arrows at the
                              # shared (Input / Combine) end, so the two arrows
                              # don't start/arrive stacked on top of each other
_QWIDGETSIZE_MAX = 16_777_215  # Qt's QWIDGETSIZE_MAX; "unbounded" max width/height

# Gain quick-slider: integer track 0..200 maps to gain 0.0..2.0 (1 step
# == 0.01); tick marks render at 0.5/1.0/1.5.
_GAIN_SLIDER_MAX = 200
_GAIN_SLIDER_SCALE = 100.0
_GAIN_TICK_INTERVAL = 50      # ticks at track positions 50/100/150
_GAIN_SLIDER_MIN_W = 130      # min slider length so Depth/Speed get a long slider

# Magnetic snap: while the user DRAGS the handle, it sticks to these track
# positions (gain 0 / 0.5 / 1.0 / 1.5 / 2.0) when it lands within
# _GAIN_SNAP_RADIUS of one. Keyboard steps and programmatic sets (the
# precise spinbox / reset) pass through un-snapped, so any in-between value
# stays reachable.
_GAIN_DETENTS = (0, 50, 100, 150, 200)
_GAIN_SNAP_RADIUS = 8         # int track units (== 0.08 gain)

# Smoothing quick-slider: the track is milliseconds directly. One slider
# sets both rise and fall (a single "how smooth" delay); ticks + drag-snap
# every 100 ms. Values beyond the range are still settable in the editor.
_MS_SLIDER_MAX = 500
_MS_TICK_INTERVAL = 100
_MS_DETENTS = (0, 100, 200, 300, 400, 500)
_MS_SNAP_RADIUS = 15          # ms

# Output-number label churn gate — half the displayed precision (.2f).
_OUTPUT_NUM_EPSILON = 0.005

# Connector colours: idle grey (like the old "→" arrow) charging toward
# vivid pink with live signal. Reuses the border-lerp endpoints' feel.
_CONNECTOR_IDLE = QColor(COLOR_TEXT_MUTED)
_CONNECTOR_LIVE = QColor(_STAGE_BORDER_HIGH)


def _lerp_color(lo: QColor, hi: QColor, t: float) -> QColor:
    """Channel-wise lerp between two QColors by t in [0, 1] (clamped)."""
    t = max(0.0, min(1.0, float(t)))
    return QColor(
        int(lo.red()   + (hi.red()   - lo.red())   * t),
        int(lo.green() + (hi.green() - lo.green()) * t),
        int(lo.blue()  + (hi.blue()  - lo.blue())  * t),
    )

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
# Quick collapsed-card sliders — a shared snap base + a gain slider
# (Depth/Speed) and a smoothing-delay slider (Smoothing).
# ----------------------------------------------------------

class _SnapSlider(QSlider):
    """Horizontal integer-track slider with tick marks and drag-magnetic
    snap to a set of detents. While the user DRAGS the handle it sticks to
    a detent when it lands within the snap radius — easier to hit round
    values — but keyboard nudges and programmatic `set_raw` (blockSignals)
    pass through un-snapped, so any in-between value stays reachable. Domain
    subclasses add their own float/labelled API on top of `rawChanged`. The
    blockSignals echo-guard mirrors ui/widgets.py SliderProxy."""

    rawChanged = Signal(int)

    def __init__(self, vmax: int, tick_interval: int, detents, snap_radius: int,
                 single_step: int, page_step: int,
                 parent: Optional[QWidget] = None) -> None:
        super().__init__(Qt.Horizontal, parent)
        self._detents = tuple(int(d) for d in detents)
        self._snap_radius = int(snap_radius)
        self.setRange(0, int(vmax))
        self.setSingleStep(int(single_step))
        self.setPageStep(int(page_step))
        self.setTickPosition(QSlider.TicksBelow)
        self.setTickInterval(int(tick_interval))
        self.valueChanged.connect(self._on_value_changed)

    def _on_value_changed(self, v: int) -> None:
        # Magnetic snap only while dragging the handle (isSliderDown). The
        # snapped setValue re-enters this slot with the detent value, which
        # then emits. Keyboard steps and programmatic set_raw (blockSignals)
        # never reach here mid-snap, so fine values stay reachable.
        if self.isSliderDown():
            snapped = self._snap(v)
            if snapped != v:
                self.setValue(snapped)
                return
        self.rawChanged.emit(self.value())

    def _snap(self, v: int) -> int:
        for d in self._detents:
            if abs(v - d) <= self._snap_radius:
                return d
        return v

    def set_raw(self, raw: float) -> None:
        """Set the track value without echoing a change."""
        try:
            v = max(0, min(self.maximum(), int(round(float(raw)))))
        except (TypeError, ValueError):
            v = 0
        self.blockSignals(True)
        self.setValue(v)
        self.blockSignals(False)


class _GainSlider(_SnapSlider):
    """Quick gain control (Depth/Speed). Track 0..200 maps to gain
    0.0..2.0; tick marks + drag-snap at 0.5/1.0/1.5 (and 0/2)."""

    gainChanged = Signal(float)

    def __init__(self, gain: float, parent: Optional[QWidget] = None) -> None:
        super().__init__(_GAIN_SLIDER_MAX, _GAIN_TICK_INTERVAL, _GAIN_DETENTS,
                         _GAIN_SNAP_RADIUS, 5, 25, parent)
        self.set_gain(gain)
        self.rawChanged.connect(
            lambda v: self.gainChanged.emit(v / _GAIN_SLIDER_SCALE))

    def set_gain(self, gain: float) -> None:
        try:
            self.set_raw(float(gain) * _GAIN_SLIDER_SCALE)
        except (TypeError, ValueError):
            self.set_raw(_GAIN_SLIDER_MAX // 2)

    def gain(self) -> float:
        return self.value() / _GAIN_SLIDER_SCALE


class _MsSlider(_SnapSlider):
    """Quick smoothing-delay control (Smoothing). The track is milliseconds
    directly (0.._MS_SLIDER_MAX); tick marks + drag-snap every 100 ms."""

    msChanged = Signal(int)

    def __init__(self, ms: float, parent: Optional[QWidget] = None) -> None:
        super().__init__(_MS_SLIDER_MAX, _MS_TICK_INTERVAL, _MS_DETENTS,
                         _MS_SNAP_RADIUS, 10, 50, parent)
        self.set_ms(ms)
        self.rawChanged.connect(self.msChanged.emit)

    def set_ms(self, ms: float) -> None:
        self.set_raw(ms)

    def ms(self) -> int:
        return self.value()


class _GainControl(QWidget):
    """A `_GainSlider` plus an inline numeric readout (e.g. "×1.00") so
    the collapsed Depth/Speed card shows the current gain *setting* at a
    glance, distinct from the live output number in the card header. The
    readout always reflects the value — whether the user drags the slider
    or it's set programmatically (mirrored from the precise spinbox /
    reset). Exposes the same `set_gain` / `gain` / `gainChanged` surface
    as `_GainSlider`, so it drops into the gain-sync wiring unchanged."""

    gainChanged = Signal(float)

    def __init__(self, gain: float, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        lay = _hbox(0, 6)
        self.setLayout(lay)
        self._slider = _GainSlider(gain)
        self._slider.setMinimumWidth(_GAIN_SLIDER_MIN_W)
        self._value = QLabel()
        self._value.setObjectName("gainValue")
        self._value.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self._value.setMinimumWidth(42)   # steady width as digits change
        lay.addWidget(self._slider, 1)
        lay.addWidget(self._value, 0)
        self._slider.gainChanged.connect(self._on_slider)
        self._sync_label(self._slider.gain())

    def _on_slider(self, g: float) -> None:
        self._sync_label(g)
        self.gainChanged.emit(g)

    def set_gain(self, gain: float) -> None:
        """Set the slider (silently) and refresh the readout."""
        self._slider.set_gain(gain)
        self._sync_label(self._slider.gain())

    def gain(self) -> float:
        return self._slider.gain()

    def _sync_label(self, g: float) -> None:
        self._value.setText(f"×{g:.2f}")


class _DelayControl(QWidget):
    """A smoothing-delay slider (ms) + inline readout for the collapsed
    Smoothing card. One slider sets BOTH rise and fall to the same delay —
    a single 'how smooth' knob; the expanded editor keeps them independent.
    Mirrors _GainControl's shape (`set_ms` / `ms` / `msChanged`)."""

    msChanged = Signal(int)

    def __init__(self, ms: float, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        lay = _hbox(0, 6)
        self.setLayout(lay)
        self._slider = _MsSlider(ms)
        self._slider.setMinimumWidth(_GAIN_SLIDER_MIN_W)
        self._value = QLabel()
        self._value.setObjectName("gainValue")
        self._value.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self._value.setMinimumWidth(48)   # steady width ("500ms")
        lay.addWidget(self._slider, 1)
        lay.addWidget(self._value, 0)
        self._slider.msChanged.connect(self._on_slider)
        self._sync_label(self._slider.ms())

    def _on_slider(self, m: int) -> None:
        self._sync_label(m)
        self.msChanged.emit(int(m))

    def set_ms(self, ms: float) -> None:
        """Set the slider (silently) and refresh the readout."""
        self._slider.set_ms(ms)
        self._sync_label(self._slider.ms())

    def ms(self) -> int:
        return self._slider.ms()

    def _sync_label(self, m: int) -> None:
        self._value.setText(f"{int(m)}ms")


# ----------------------------------------------------------
# _StageCard — one accordion cell (header + quick region + editor).
# ----------------------------------------------------------

# Card display states, driven by the parent's active-stage choice.
_CARD_RAIL = "rail"          # thin sliver: short title only
_CARD_QUICK = "quick"        # collapsed: header + quick control + number
_CARD_EXPANDED = "expanded"  # full editor revealed


class _StageCard(QFrame):
    """A single clickable stage cell in the accordion strip. Owns three
    stacked regions in a vertical layout:

      * Header (always visible): bold stage title + a live output number.
      * Quick region (visible when collapsed): the at-a-glance control —
        a gain slider for Depth/Speed, the subtitle summary otherwise.
      * Editor region (built lazily, hidden until first expand): receives
        the full per-stage editor; its maximumHeight is animated on
        expand/collapse.

    Keeps objectName "tuneStageCard" so the existing QSS and the live
    `_apply_stage_card_color` per-widget border lerp keep working. Emits
    `clicked(stage_id)` on left-press; child sliders/spinboxes consume
    their own mouse events (Qt child-first dispatch), so dragging a
    control never toggles the card."""

    clicked = Signal(str)

    def __init__(self, stage_id: str, full_title: str, short_title: str,
                 compact: bool = False,
                 parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._stage_id = stage_id
        self._full = full_title
        self._short = short_title
        self._compact = compact
        self._last_out = -1.0

        self.setObjectName("tuneStageCard")
        self.setCursor(Qt.PointingHandCursor)
        self.setProperty("active", "false")
        self.setMinimumWidth(_CARD_COLLAPSED_MIN)

        root = _vbox(8, 4)
        self._root_lay = root
        self.setLayout(root)

        self._title = QLabel(full_title)
        tf = self._title.font(); tf.setBold(True)
        self._title.setFont(tf)
        # Rail mode renders inside ~_RAIL_WIDTH px: the layout's side
        # margins go to zero and the title drops a point so the short
        # label fits the sliver without clipping.
        self._font_full = QFont(tf)
        self._font_rail = QFont(tf)
        self._font_rail.setPointSize(max(7, tf.pointSize() - 1))
        self._out_label = QLabel("—")
        self._out_label.setObjectName("stageOutNum")
        if compact:
            # Compact (non-slider) cards stack the title over the number, so
            # the card is narrow (width = title) and a little taller — frees
            # horizontal room. Both centred.
            self._title.setAlignment(Qt.AlignHCenter)
            self._out_label.setAlignment(Qt.AlignHCenter)
            header = _vbox(0, 0)
            header.addWidget(self._title)
            header.addWidget(self._out_label)
        else:
            # Slider cards are wide anyway, so title + number sit side by side.
            self._out_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            header = _hbox(0, 6)
            header.addWidget(self._title)
            header.addStretch(1)
            header.addWidget(self._out_label)
        root.addLayout(header)

        # Quick region — collapsed content (populated by the parent).
        self._quick = QFrame()
        self._quick.setObjectName("stageQuick")
        self._quick_lay = _vbox(0, 2)
        self._quick.setLayout(self._quick_lay)
        root.addWidget(self._quick)

        # Editor region — built lazily, hidden + zero-height until expand.
        self._editor_region = QFrame()
        self._editor_region.setObjectName("stageEditorRegion")
        self._editor_lay = _vbox(0, 0)
        self._editor_region.setLayout(self._editor_lay)
        self._editor_region.setVisible(False)
        self._editor_region.setMaximumHeight(0)
        root.addWidget(self._editor_region)

        self._editor_built = False
        # Live activity ring — PAINTED over the QSS transparent border in
        # paintEvent instead of restyled per tick (see set_activity_color).
        self._activity_color: Optional[QColor] = None

    # ------------------------------------------------------------ basics
    @property
    def stage_id(self) -> str:
        return self._stage_id

    @property
    def quick_layout(self):
        return self._quick_lay

    def set_activity_color(self, color: QColor) -> None:
        """Charge the card's border ring. Cheap: stores the colour and
        repaints one frame — setStyleSheet here repolished the card's
        whole descendant subtree (labels, sliders, mounted editor) up to
        ~50×/s per card, synchronously inside the routing tick."""
        self._activity_color = color
        self.update()

    def paintEvent(self, event) -> None:
        super().paintEvent(event)  # QSS background / radius / base border
        color = self._activity_color
        if color is None or self.property("active") == "true":
            # No signal seen yet, or the QSS active rule owns the border
            # (the expanded card's green outline).
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(QPen(color, 1.0))
        p.setBrush(Qt.NoBrush)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        p.drawRoundedRect(r, 8.0, 8.0)
        p.end()

    def mousePressEvent(self, ev) -> None:
        if ev.button() == Qt.LeftButton:
            self.clicked.emit(self._stage_id)
            ev.accept()
        else:
            super().mousePressEvent(ev)

    # ------------------------------------------------------------ editor
    def editor_built(self) -> bool:
        return self._editor_built

    def editor_region(self) -> QFrame:
        return self._editor_region

    def quick_region(self) -> QFrame:
        return self._quick

    def mount_editor(self, widget: QWidget) -> None:
        self._editor_lay.addWidget(widget)
        self._editor_built = True

    def reset_editor(self) -> None:
        """Tear down the built editor so it rebuilds on next expand.
        Hide before reparent to avoid the brief top-level-window flash."""
        while self._editor_lay.count():
            item = self._editor_lay.takeAt(0)
            w = item.widget()
            if w is not None:
                w.hide()
                w.setParent(None)
                w.deleteLater()
        self._editor_built = False
        self._editor_region.setVisible(False)
        self._editor_region.setMaximumHeight(0)

    def set_editor_max_height(self, h: int) -> None:
        self._editor_region.setMaximumHeight(max(0, int(h)))

    # ------------------------------------------------------------ width
    def set_width_px(self, w: int) -> None:
        """Pin the card to an exact width (min == max) during animation."""
        w = max(0, int(w))
        self.setMinimumWidth(w)
        self.setMaximumWidth(w)

    def clear_width(self, floor: int) -> None:
        """Release the width pin so the card flows naturally again."""
        self.setMinimumWidth(floor)
        self.setMaximumWidth(_QWIDGETSIZE_MAX)

    # ------------------------------------------------------------ state
    def apply_state(self, state: str) -> None:
        """Set the card's collapsed/expanded/rail content visibility.
        Editor-height visibility during animation is managed separately
        by the parent; this sets the steady-state look. Rail mode also
        reclaims the layout's side margins and shrinks the title font —
        a _RAIL_WIDTH sliver minus border + QSS padding + 8px margins
        leaves ~22px of content, which clipped every 3-4 letter short
        title; with the margins folded away the titles fit."""
        if state == _CARD_RAIL:
            self._title.setText(self._short)
            self._title.setFont(self._font_rail)
            self._title.setAlignment(Qt.AlignHCenter)
            self._root_lay.setContentsMargins(0, 8, 0, 8)
            self._out_label.setVisible(False)
            self._quick.setVisible(False)
            self._editor_region.setVisible(False)
            return
        self._title.setFont(self._font_full)
        self._root_lay.setContentsMargins(8, 8, 8, 8)
        if self._compact:
            self._title.setAlignment(Qt.AlignHCenter)
        else:
            self._title.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        if state == _CARD_EXPANDED:
            self._title.setText(self._full)
            self._out_label.setVisible(True)
            self._quick.setVisible(False)
            self._editor_region.setVisible(True)
        else:  # _CARD_QUICK
            self._title.setText(self._full)
            self._out_label.setVisible(True)
            self._quick.setVisible(True)
            self._editor_region.setVisible(False)

    def set_output_number(self, value: float) -> None:
        """Update the live output number, gated to avoid per-tick churn."""
        try:
            v = max(0.0, min(1.0, float(value)))
        except (TypeError, ValueError):
            return
        if abs(v - self._last_out) < _OUTPUT_NUM_EPSILON:
            return
        self._last_out = v
        self._out_label.setText(f"{v:.2f}")


# ----------------------------------------------------------
# _StripHost — strip container that paints the stretching connectors.
# ----------------------------------------------------------

class _StripHost(QWidget):
    """Hosts the stage cards in a QHBoxLayout and paints the elastic
    connector arrows between adjacent slots in its own paintEvent.
    Because the connectors are computed from live child geometry every
    paint, and the parent triggers `update()` on each animation frame,
    they stretch/shrink with the gaps automatically as cards expand and
    siblings squish. Drawing in the parent (behind the child cards)
    means card backgrounds cleanly occlude any overrun."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._slots: List[QWidget] = []
        self._levels: List[float] = []
        # Fork/join around the parallel Depth/Speed slot: Input forks into
        # both channels, and both join into Combine. `_branch_index` is that
        # slot's position in `_slots`; `_branch_cards` is [depth, speed].
        self._branch_index: int = -1
        self._branch_cards: List[QWidget] = []
        self._branch_levels: List[float] = []
        # Small (all-collapsed) mode centres the arrows on each card's middle;
        # when a stage is expanded the cards top-align and arrows ride the
        # header row instead (so a tall editor doesn't drag the arrow down).
        self._centered: bool = True

    def set_centered(self, centered: bool) -> None:
        self._centered = bool(centered)

    def set_slots(self, slots: List[QWidget]) -> None:
        self._slots = list(slots)
        self._levels = [0.0] * max(0, len(self._slots) - 1)

    def set_branch(self, slot_index: int, branch_cards: List[QWidget]) -> None:
        """Mark the parallel slot (its index in `_slots`) whose incoming and
        outgoing connectors fork/join across its inner cards."""
        self._branch_index = int(slot_index)
        self._branch_cards = list(branch_cards)
        self._branch_levels = [0.0] * len(self._branch_cards)

    def set_connector_levels(self, levels: List[float]) -> None:
        self._levels = list(levels)

    def set_branch_levels(self, levels: List[float]) -> None:
        self._branch_levels = list(levels)

    def resizeEvent(self, ev) -> None:
        super().resizeEvent(ev)
        self.update()

    def paintEvent(self, _ev) -> None:
        if len(self._slots) < 2:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        has_branch = (0 <= self._branch_index < len(self._slots)
                      and len(self._branch_cards) == 2)
        for i in range(len(self._slots) - 1):
            try:
                a = self._slots[i]
                b = self._slots[i + 1]
                if not a.isVisible() or not b.isVisible():
                    continue
                if a.geometry().isEmpty() or b.geometry().isEmpty():
                    continue
                level = self._levels[i] if i < len(self._levels) else 0.0
                color = _lerp_color(_CONNECTOR_IDLE, _CONNECTOR_LIVE, level)
                n = len(self._branch_cards)
                if has_branch and i + 1 == self._branch_index:
                    # Fork: Input splits into Depth and Speed. Spread the two
                    # arrows' start points on Input's edge so they don't stack.
                    sx, scy = self._card_anchor(a, right=True)
                    for idx, card in enumerate(self._branch_cards):
                        start = (sx, scy + self._fanout(idx, n))
                        self._draw_arrow(
                            p, start, self._card_anchor(card, right=False),
                            color)
                elif has_branch and i == self._branch_index:
                    # Join: Depth and Speed merge into Combine. Spread the two
                    # arrows' arrival points on Combine's edge, and tint each
                    # by its own channel level.
                    dx, dcy = self._card_anchor(b, right=False)
                    for idx, card in enumerate(self._branch_cards):
                        lv = (self._branch_levels[idx]
                              if idx < len(self._branch_levels) else 0.0)
                        end = (dx, dcy + self._fanout(idx, n))
                        self._draw_arrow(
                            p, self._card_anchor(card, right=True), end,
                            _lerp_color(_CONNECTOR_IDLE, _CONNECTOR_LIVE, lv))
                else:
                    self._draw_arrow(p, self._card_anchor(a, right=True),
                                     self._card_anchor(b, right=False), color)
            except RuntimeError:
                continue
        p.end()

    def _card_anchor(self, w: QWidget, right: bool):
        """(x, y) in this host's coordinates for a card's connector anchor on
        its right or left edge. In small (centered) mode the anchor is the
        card's vertical middle; with a stage expanded it's the header row.
        mapTo handles nested cards — Depth/Speed live inside the ds container,
        not directly under the host."""
        tl = w.mapTo(self, QPoint(0, 0))
        x = tl.x() + (w.width() if right else 0)
        h = max(2, w.height())
        y = tl.y() + (h // 2 if self._centered
                      else min(_HEADER_CENTER_Y, h - 2))
        return (x, y)

    @staticmethod
    def _fanout(idx: int, n: int) -> float:
        """Vertical offset for branch `idx` of `n` at the shared fork/join
        endpoint: -_BRANCH_FANOUT for the top channel, +_BRANCH_FANOUT for the
        bottom, spread evenly between — so the arrows don't stack."""
        if n <= 1:
            return 0.0
        return ((idx / (n - 1)) - 0.5) * 2.0 * _BRANCH_FANOUT

    @staticmethod
    def _draw_arrow(p: QPainter, start, end, color: QColor) -> None:
        """Draw a directional arrow from start=(x,y) to end=(x,y) with the
        head pointing along the line, so angled fork/join arrows look right.
        Skips degenerate / too-short spans."""
        x1, y1 = float(start[0]), float(start[1])
        x2, y2 = float(end[0]), float(end[1])
        dx, dy = x2 - x1, y2 - y1
        length = (dx * dx + dy * dy) ** 0.5
        if length < 6.0:
            return
        ux, uy = dx / length, dy / length
        ah = 5.0
        base_x, base_y = x2 - ux * 2.0 * ah, y2 - uy * 2.0 * ah
        pen = QPen(color)
        pen.setWidth(2)
        pen.setCapStyle(Qt.RoundCap)
        p.setPen(pen)
        p.drawLine(QPointF(x1, y1), QPointF(base_x, base_y))
        # Arrowhead: tip at end, base corners perpendicular to direction.
        px, py = -uy, ux
        p.setPen(Qt.NoPen)
        p.setBrush(QBrush(color))
        head = QPolygonF([
            QPointF(x2, y2),
            QPointF(base_x + px * ah, base_y + py * ah),
            QPointF(base_x - px * ah, base_y - py * ah),
        ])
        p.drawPolygon(head)


# ----------------------------------------------------------
# MotorSignalChainWidget — the main per-motor surface.
# ----------------------------------------------------------

class MotorSignalChainWidget(QFrame):
    """Accordion stages strip with inline editors + per-stage mini-graphs
    + vibe meter for one motor (or one chain of a two-chain motor).

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
    expand."""

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
            "combine, gate, smoothing, zero cut) back to the built-in "
            "defaults. Other chains on the same motor are untouched."
        )
        reset_btn.clicked.connect(self._on_reset_clicked)
        header_row.addWidget(reset_btn)
        root.addLayout(header_row)

        # ---- Stages strip (inline-expand accordion, Cut 9) -----------
        self._stage_cards: Dict[str, _StageCard] = {}
        # Subtitle labels under non-Depth/Speed card titles; refreshed
        # on a timer. Depth/Speed show a gain slider instead, so they're
        # absent here (and thus skipped by _refresh_stage_subtitles).
        self._stage_subtitles: Dict[str, QLabel] = {}
        # Last-applied border level per stage; gates stylesheet churn and
        # feeds the connector colours.
        self._stage_last_level: Dict[str, float] = {}
        # Optional valve indicator on the gate stage card only.
        self._stage_valve: Optional[ValveIndicator] = None
        # Per-stage mini-graphs (Cut 6); built lazily in _build_editor_for.
        self._stage_graphs: Dict[str, _TraceGraph] = {}

        # Quick gain controls (slider + readout on the Depth/Speed cards)
        # and the precise gain spinboxes in their expanded editors — kept
        # in sync two-way.
        self._gain_sliders: Dict[str, _GainControl] = {}
        self._gain_spins: Dict[str, QDoubleSpinBox] = {}
        # Quick smoothing-delay control (Smoothing card) + the precise rise/
        # fall spinboxes in its expanded editor — kept in sync two-way.
        self._delay_control: Optional[_DelayControl] = None
        self._smoothing_spins: Dict[str, QDoubleSpinBox] = {}

        # Accordion geometry state. `_slots` is the ordered list of
        # horizontal cells (each a card, except Depth/Speed share one
        # container `_ds_slot`); `_slot_for_stage` maps a stage to its
        # cell. _active_stage = None means nothing is expanded (the
        # all-collapsed default).
        self._slots: List[QWidget] = []
        self._slot_for_stage: Dict[str, QWidget] = {}
        self._ds_slot: Optional[QWidget] = None
        self._strip_host: Optional[_StripHost] = None
        self._strip_lay = None
        self._last_connector_levels: List[float] = []
        self._last_branch_levels: List[float] = []
        self._active_stage: Optional[str] = None

        # One reusable animation drives every expand/collapse: a 0→1
        # progress the tick lerps into slot widths + the active editor's
        # height, then repaints the connectors. Mirrors the OutCubic
        # size-animation in ui/views/overview.py.
        self._accordion_anim = QVariantAnimation(self)
        self._accordion_anim.setStartValue(0.0)
        self._accordion_anim.setEndValue(1.0)
        self._accordion_anim.setDuration(_ACCORDION_ANIM_MS)
        self._accordion_anim.setEasingCurve(QEasingCurve.OutCubic)
        self._accordion_anim.valueChanged.connect(self._on_anim_tick)
        self._accordion_anim.finished.connect(self._on_anim_done)
        self._anim_from: Dict[QWidget, int] = {}
        self._anim_to: Dict[QWidget, int] = {}
        self._anim_editor_card: Optional[_StageCard] = None
        self._anim_editor_from = 0
        self._anim_editor_to = 0

        root.addWidget(self._build_stages_strip())
        # Start in small mode (nothing expanded): centre the cards + arrows.
        self._apply_strip_mode(True)

        # ---- Vibe meter ----------------------------------------------
        self._vibe_meter = _RainbowMeter(maximum=1000)
        self._vibe_proxy = _ProgressProxy(self._vibe_meter)
        root.addWidget(self._vibe_meter)

        # Activity meter widget (lives inside the Gate stage editor;
        # driven from this widget's own intermediates subscription
        # below — set_activity(...) is a no-op shim for backward compat).
        self._activity_meter: Optional[ActivityMeter] = None

        # No stage is expanded by default — the collapsed strip shows
        # each stage's title, quick control (gain slider on Depth/Speed),
        # and live output number. Clicking a card expands it in place.

        # Stage card subtitle refresh — picks up external profile
        # edits without a notification path. Parented to self so the
        # timer dies with the widget. Tick interval is intentionally
        # slow (500ms); subtitles are at-a-glance text, not live data.
        self._subtitle_timer = QTimer(self)
        self._subtitle_timer.setInterval(_STAGE_SUBTITLE_REFRESH_MS)
        self._subtitle_timer.timeout.connect(self._refresh_stage_subtitles)
        self._subtitle_timer.start()

        # Per-(motor, chain) intermediates feed the mini-graphs, the
        # activity meter, and the live border/connector colours. The
        # signal bridge ensures cross-thread safety: router's callback
        # runs on the routing thread, `emit` queues onto the UI thread
        # where `_handle_intermediates` is invoked.
        #
        # The subscription is VISIBILITY-DRIVEN (showEvent/hideEvent):
        # a chain hidden inside a collapsed toy card, or parked on a
        # non-current sidebar page, costs nothing — the router skips
        # the dispatch entirely and no cross-thread events queue. The
        # router fires per-tick (~90 Hz) per subscribed chain, so this
        # is the difference between "every chain in every profile
        # burns CPU forever" and "only what's on screen does".
        self.intermediates.connect(self._handle_intermediates)
        self._intermediates_callback = self.intermediates.emit
        self._intermediates_subscribed = False

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
        """The clickable accordion strip. Each stage is a `_StageCard`;
        Depth and Speed share one vertical slot to convey their
        parallelism. The host (`_StripHost`) paints the stretching
        connectors between slots — there are no arrow widgets. Slots are
        top-aligned so every card header lines up, keeping the connectors
        horizontal regardless of how tall the expanded card grows. A
        trailing stretch absorbs slack so the per-frame width pins never
        fight the layout."""
        host = _StripHost()
        lay = _hbox(0, 0)
        host.setLayout(lay)
        self._strip_host = host
        self._strip_lay = lay
        self._slots = []
        self._slot_for_stage = {}

        def make_connector() -> QWidget:
            # Flexible spacer the connector arrow is painted across.
            # Expanding with only a minimum width, so it soaks up the row's
            # slack and lengthens as a neighbour expands while far siblings
            # squish — i.e. the arrows stretch. Transparent (no autofill)
            # so the parent-painted connector shows through.
            sp = QWidget()
            sp.setMinimumWidth(_CONNECTOR_GAP)
            sp.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)
            return sp

        def add_slot(slot: QWidget) -> None:
            if self._slots:                       # connector before every
                lay.addWidget(make_connector())   # slot except the first
            lay.addWidget(slot, 0, Qt.AlignTop)
            self._slots.append(slot)

        def add_card(stage_id: str) -> _StageCard:
            card = self._make_stage_card(stage_id)
            self._stage_cards[stage_id] = card
            return card

        # Input.
        in_card = add_card(STAGE_INPUT)
        add_slot(in_card)
        self._slot_for_stage[STAGE_INPUT] = in_card

        # Depth + Speed share one vertical slot.
        ds = QWidget()
        ds_lay = _vbox(0, 4)
        ds.setLayout(ds_lay)
        depth_card = add_card(STAGE_DEPTH)
        speed_card = add_card(STAGE_SPEED)
        # Inner cards follow the slot width (the slot is what animates),
        # so let them shrink to the rail width when the slot is squished.
        depth_card.setMinimumWidth(0)
        speed_card.setMinimumWidth(0)
        ds_lay.addWidget(depth_card)
        ds_lay.addWidget(speed_card)
        add_slot(ds)
        self._slot_for_stage[STAGE_DEPTH] = ds
        self._slot_for_stage[STAGE_SPEED] = ds
        self._ds_slot = ds

        for sid in (STAGE_COMBINE, STAGE_GATE, STAGE_SMOOTHING,
                    STAGE_ZEROCUT, STAGE_OUTPUT):
            card = add_card(sid)
            add_slot(card)
            self._slot_for_stage[sid] = card

        host.set_slots(self._slots)
        # Input forks into Depth+Speed, and they join into Combine — tell the
        # host which slot is the parallel pair so it draws branch arrows.
        host.set_branch(self._slots.index(self._ds_slot), [depth_card, speed_card])
        return host

    def _make_stage_card(self, stage_id: str) -> _StageCard:
        """Build one accordion cell. Depth/Speed get a quick gain slider and
        Smoothing a quick delay (ms) slider; the other (compact) stages stack
        their title over the output number and show the subtitle summary. The
        gate also gets its valve indicator. Clicking the card toggles its
        expansion via `_on_stage_clicked`."""
        is_slider = stage_id in (STAGE_DEPTH, STAGE_SPEED, STAGE_SMOOTHING)
        card = _StageCard(
            stage_id, _STAGE_LABELS[stage_id],
            _STAGE_SHORT.get(stage_id, _STAGE_LABELS[stage_id][:4]),
            compact=not is_slider,
        )
        card.clicked.connect(self._on_stage_clicked)

        if stage_id in (STAGE_DEPTH, STAGE_SPEED):
            chain = _read_chain(self._controller, self._device_name,
                                self._motor_idx, self._chain_idx)
            cfg = chain.get(stage_id, {}) if isinstance(chain, dict) else {}
            gain_ctrl = _GainControl(float(cfg.get("gain", 1.0)))
            gain_ctrl.gainChanged.connect(
                lambda g, ck=stage_id: self._on_gain_from_slider(ck, g)
            )
            self._gain_sliders[stage_id] = gain_ctrl
            card.quick_layout.addWidget(gain_ctrl)
        elif stage_id == STAGE_SMOOTHING:
            chain = _read_chain(self._controller, self._device_name,
                                self._motor_idx, self._chain_idx)
            sm = chain.get("smoothing", {}) if isinstance(chain, dict) else {}
            seed = max(float(sm.get("rise_ms", 50.0)),
                       float(sm.get("fall_ms", 20.0)))
            delay_ctrl = _DelayControl(seed)
            delay_ctrl.msChanged.connect(self._on_delay_from_slider)
            self._delay_control = delay_ctrl
            card.quick_layout.addWidget(delay_ctrl)
        else:
            subtitle = QLabel(self._summary_for_stage(stage_id))
            subtitle.setAlignment(Qt.AlignHCenter)
            sf = subtitle.font()
            sf.setPointSize(max(7, sf.pointSize() - 1))
            subtitle.setFont(sf)
            subtitle.setProperty("muted", "true")
            self._ui._repolish(subtitle)
            card.quick_layout.addWidget(subtitle)
            self._stage_subtitles[stage_id] = subtitle

        # Valve indicator — only on the Gate card. Animates open/closed;
        # complements the full ActivityMeter inside the expanded editor.
        if stage_id == STAGE_GATE:
            valve = ValveIndicator()
            card.quick_layout.addWidget(valve)
            self._stage_valve = valve

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
        if stage_id == STAGE_ZEROCUT:
            zc = chain.get("zerocut", {}) if isinstance(chain, dict) else {}
            if not isinstance(zc, dict) or not zc.get("enabled", False):
                return "off"
            try:
                thr = float(zc.get("threshold", 0.0))
            except (TypeError, ValueError):
                thr = 0.0
            return f"≤{thr:.2g}→0"
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
        from rebuilds. Skips entirely while the chain is off-screen
        (collapsed toy card / another sidebar page)."""
        if not self.isVisible():
            return
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
        """Update the stage card's border colour to reflect the signal
        level at that stage. Skips the write when the change is below
        `_STAGE_BORDER_EPSILON`. The colour is PAINTED by the card
        (set_activity_color -> paintEvent) — the old per-tick
        setStyleSheet forced a full subtree repolish on every step, and
        it ran synchronously inside the routing tick. The active-stage
        selector keeps its green border via the global QSS rule."""
        card = self._stage_cards.get(stage_id)
        if card is None:
            return
        last = self._stage_last_level.get(stage_id, -1.0)
        if abs(level - last) < _STAGE_BORDER_EPSILON:
            return
        self._stage_last_level[stage_id] = level
        try:
            card.set_activity_color(self._lerp_purple_pink(level))
        except RuntimeError:
            self._stage_cards.pop(stage_id, None)

    # ------------------------------------------------ accordion expand

    def _on_stage_clicked(self, stage_id: str) -> None:
        """Toggle a stage: clicking the expanded card collapses the strip;
        clicking any other card expands it (and rails the rest)."""
        if stage_id not in _STAGE_ORDER:
            return
        if self._active_stage == stage_id:
            self._animate_to(None)
        else:
            self._animate_to(stage_id)

    def _animate_to(self, target: Optional[str]) -> None:
        """Drive the strip toward `target` expanded (or all-collapsed when
        None). Builds the target editor, sets each card's content state,
        captures width + editor-height from/to values, and (re)starts the
        shared animation. Safe to call mid-animation — it recaptures from
        the current widths so the motion redirects smoothly."""
        if self._strip_host is None:
            return
        prev = self._active_stage

        # Build the target editor up front so its height is measurable.
        if target is not None:
            self._ensure_editor(target)

        # Steady-state content (titles, quick vs editor visibility).
        self._apply_card_states(target)

        # Editor-height animation: expand the target's region from 0, or
        # collapse the previous one back to 0. Keep the animating editor
        # visible (and its quick region hidden) until the motion lands.
        self._anim_editor_card = None
        self._anim_editor_from = 0
        self._anim_editor_to = 0
        if target is not None:
            card = self._stage_cards.get(target)
            if card is not None:
                region = card.editor_region()
                region.setVisible(True)
                region.setMaximumHeight(_QWIDGETSIZE_MAX)
                target_h = max(0, region.sizeHint().height())
                region.setMaximumHeight(0)
                card.quick_region().setVisible(False)
                self._anim_editor_card = card
                self._anim_editor_to = target_h
        elif prev is not None:
            card = self._stage_cards.get(prev)
            if card is not None:
                region = card.editor_region()
                region.setVisible(True)
                card.quick_region().setVisible(False)
                self._anim_editor_card = card
                self._anim_editor_from = max(0, region.height())
                self._anim_editor_to = 0

        # Width from/to. Pin current widths first so the first frame starts
        # exactly where the cards are now (avoids a jump when leaving the
        # flexible all-collapsed state).
        self._anim_from = {slot: max(0, slot.width()) for slot in self._slots}
        self._anim_to = self._compute_target_widths(target)
        for slot in self._slots:
            self._set_slot_width(slot, self._anim_from[slot])

        # Active-card highlight (green border via the `active` property).
        self._active_stage = target
        for sid, card in self._stage_cards.items():
            card.setProperty("active", "true" if sid == target else "false")
            self._ui._repolish(card)

        # Small mode (nothing expanded) centres the cards; expanded top-aligns.
        self._apply_strip_mode(target is None)

        self._accordion_anim.stop()
        self._accordion_anim.start()

    def _apply_strip_mode(self, collapsed: bool) -> None:
        """Small (all-collapsed) mode vertically centres the cards, so the
        plain arrows run down the middle and the Input/Combine fork/join sit
        at the Depth↔Speed midpoint (symmetric). With a stage expanded the
        cards top-align so a tall editor doesn't drag the arrows down."""
        align = Qt.AlignVCenter if collapsed else Qt.AlignTop
        if self._strip_lay is not None:
            for slot in self._slots:
                try:
                    self._strip_lay.setAlignment(slot, align)
                except (RuntimeError, TypeError):
                    pass
        if self._strip_host is not None:
            try:
                self._strip_host.set_centered(collapsed)
                self._strip_host.update()
            except RuntimeError:
                pass

    def _apply_card_states(self, target: Optional[str]) -> None:
        """Set every card's collapsed/expanded/rail content. The expanded
        card shows its editor; the Depth/Speed sibling of an expanded
        channel stays a normal quick card; everything else in a non-active
        slot becomes a thin rail."""
        target_slot = self._slot_for_stage.get(target) if target else None
        for stage in _STAGE_ORDER:
            card = self._stage_cards.get(stage)
            if card is None:
                continue
            if target is None:
                state = _CARD_QUICK
            elif stage == target:
                state = _CARD_EXPANDED
            elif self._slot_for_stage.get(stage) is target_slot:
                state = _CARD_QUICK          # Depth/Speed sibling
            else:
                state = _CARD_RAIL
            card.apply_state(state)

    def _ensure_editor(self, stage_id: str) -> None:
        """Lazily build and mount a stage's editor into its card."""
        card = self._stage_cards.get(stage_id)
        if card is None or card.editor_built():
            return
        page = self._build_editor_for(stage_id)
        card.mount_editor(page)

    # ------------------------------------------------ accordion widths

    def _set_slot_width(self, slot: QWidget, w: int) -> None:
        try:
            slot.setMinimumWidth(max(0, int(w)))
            slot.setMaximumWidth(max(0, int(w)))
        except RuntimeError:
            pass

    def _clear_slot_width(self, slot: QWidget) -> None:
        """Release a slot's width pin so the all-collapsed strip flows
        naturally again. Card slots keep a sensible floor; the Depth/Speed
        container defers to its inner cards' own minimums."""
        try:
            slot.setMinimumWidth(
                0 if slot is self._ds_slot else _CARD_COLLAPSED_MIN
            )
            slot.setMaximumWidth(_QWIDGETSIZE_MAX)
        except RuntimeError:
            pass

    def _slot_collapsed_width(self, slot: QWidget) -> int:
        """Natural collapsed width for a slot (clamped to a tidy range)."""
        try:
            hint = slot.sizeHint().width()
        except RuntimeError:
            hint = _CARD_COLLAPSED_MIN
        return max(_CARD_COLLAPSED_MIN, min(hint, 180))

    def _rail_width_px(self) -> int:
        """Rail width adapted to the live font, so the short titles never
        clip regardless of DPI scaling or font substitution. _RAIL_WIDTH
        is the floor; the widest short title (plus the card's border +
        QSS padding + breathing room) can push it up a few px."""
        w = _RAIL_WIDTH
        for card in self._stage_cards.values():
            try:
                fm = QFontMetrics(card._font_rail)
                w = max(w, fm.horizontalAdvance(card._short) + 14)
            except RuntimeError:
                continue
        return w

    def _compute_target_widths(self, target: Optional[str]) -> Dict[QWidget, int]:
        """Target width per slot. All-collapsed → each slot's natural
        width; one expanded → that slot takes the row minus thin rails for
        the others (clamped so it never underflows the editor)."""
        out: Dict[QWidget, int] = {}
        if target is None:
            for slot in self._slots:
                out[slot] = self._slot_collapsed_width(slot)
            return out
        target_slot = self._slot_for_stage.get(target)
        rail_w = self._rail_width_px()
        n_rails = max(0, len(self._slots) - 1)
        n_conn = max(0, len(self._slots) - 1)
        host_w = self._strip_host.contentsRect().width()
        # Cards are pinned; the connector cells (min _CONNECTOR_GAP each)
        # take the remaining width, so the expanded card is a *bounded*
        # target rather than absorbing all the slack — that's what leaves
        # room for the connectors to stretch. Shrink the target only when
        # the row genuinely can't fit it.
        room = host_w - n_rails * rail_w - n_conn * _CONNECTOR_GAP - 4
        expanded = max(_EXPANDED_MIN, min(_CARD_EXPANDED_TARGET, room))
        for slot in self._slots:
            out[slot] = expanded if slot is target_slot else rail_w
        return out

    # ------------------------------------------------ accordion ticks

    def _on_anim_tick(self, value) -> None:
        """Lerp every slot width and the active editor's height by the
        eased progress `value` (0→1), then repaint the connectors against
        the new geometry."""
        try:
            t = float(value)
        except (TypeError, ValueError):
            return
        for slot in self._slots:
            a = self._anim_from.get(slot)
            b = self._anim_to.get(slot)
            if a is None or b is None:
                continue
            self._set_slot_width(slot, int(round(a + (b - a) * t)))
        if self._anim_editor_card is not None:
            h = (self._anim_editor_from
                 + (self._anim_editor_to - self._anim_editor_from) * t)
            try:
                self._anim_editor_card.set_editor_max_height(int(round(h)))
            except RuntimeError:
                self._anim_editor_card = None
        if self._strip_host is not None:
            try:
                self._strip_host.update()
            except RuntimeError:
                pass

    def _on_anim_done(self) -> None:
        """Snap to the final widths/heights and settle content state. Uses
        `_active_stage` (always the latest target) so a stale finish from a
        superseded run still lands on the current layout."""
        target = self._active_stage
        for slot in self._slots:
            b = self._anim_to.get(slot)
            if b is not None:
                self._set_slot_width(slot, b)
        # Editor height: release the expanded card to unbounded so later
        # natural growth works (e.g. Input's zone panel); hide a collapsed
        # editor and zero its height.
        if self._anim_editor_card is not None:
            try:
                if self._anim_editor_to <= 0:
                    self._anim_editor_card.set_editor_max_height(0)
                    self._anim_editor_card.editor_region().setVisible(False)
                else:
                    self._anim_editor_card.set_editor_max_height(_QWIDGETSIZE_MAX)
            except RuntimeError:
                pass
            self._anim_editor_card = None
        self._apply_card_states(target)
        # All-collapsed: drop the width pins so the strip is flexible.
        if target is None:
            for slot in self._slots:
                self._clear_slot_width(slot)
        if self._strip_host is not None:
            try:
                self._strip_host.update()
            except RuntimeError:
                pass

    # ------------------------------------------------ gain sync

    def _on_gain_from_slider(self, channel_key: str, gain: float) -> None:
        """Quick-slider edit: persist + mirror onto the precise spinbox."""
        _update_chain_field(
            self._controller, self._device_name, self._motor_idx,
            self._chain_idx, (channel_key, "gain"), float(gain),
        )
        spin = self._gain_spins.get(channel_key)
        if spin is not None:
            try:
                spin.blockSignals(True)
                spin.setValue(float(gain))
                spin.blockSignals(False)
            except RuntimeError:
                self._gain_spins.pop(channel_key, None)

    def _on_gain_from_spin(self, channel_key: str, gain: float) -> None:
        """Precise-spinbox edit: persist + mirror onto the quick slider."""
        _update_chain_field(
            self._controller, self._device_name, self._motor_idx,
            self._chain_idx, (channel_key, "gain"), float(gain),
        )
        slider = self._gain_sliders.get(channel_key)
        if slider is not None:
            try:
                slider.set_gain(float(gain))
            except RuntimeError:
                self._gain_sliders.pop(channel_key, None)

    def _on_delay_from_slider(self, ms: int) -> None:
        """Quick smoothing-delay slider edit: set BOTH rise and fall to the
        same delay (one write/recalc pass), and mirror the precise
        rise/fall spinboxes."""
        m = float(int(ms))
        _update_chain_fields(
            self._controller, self._device_name, self._motor_idx,
            self._chain_idx,
            ((("smoothing", "rise_ms"), m), (("smoothing", "fall_ms"), m)),
        )
        for key in ("rise_ms", "fall_ms"):
            spin = self._smoothing_spins.get(key)
            if spin is not None:
                try:
                    spin.blockSignals(True)
                    spin.setValue(m)
                    spin.blockSignals(False)
                except RuntimeError:
                    self._smoothing_spins.pop(key, None)

    def _on_smoothing_spin_changed(self, key: str, value: float) -> None:
        """Precise rise/fall spinbox edit: persist that field, then reflect
        the slower of the two on the quick delay slider."""
        _update_chain_field(
            self._controller, self._device_name, self._motor_idx,
            self._chain_idx, ("smoothing", key), float(value),
        )
        if self._delay_control is not None:
            chain = _read_chain(self._controller, self._device_name,
                                self._motor_idx, self._chain_idx)
            sm = chain.get("smoothing", {}) if isinstance(chain, dict) else {}
            mx = max(float(sm.get("rise_ms", 50.0)),
                     float(sm.get("fall_ms", 20.0)))
            try:
                self._delay_control.set_ms(mx)
            except RuntimeError:
                self._delay_control = None

    # ------------------------------------------------ connectors

    def _update_connector_levels(self) -> None:
        """Recompute the per-connector signal levels from the last-applied
        per-stage levels and repaint the strip only when they change."""
        if self._strip_host is None:
            return
        ll = self._stage_last_level

        def g(s: str) -> float:
            return max(0.0, min(1.0, ll.get(s, 0.0)))

        levels = [
            g(STAGE_INPUT),
            max(g(STAGE_DEPTH), g(STAGE_SPEED)),
            g(STAGE_COMBINE),
            g(STAGE_GATE),
            g(STAGE_SMOOTHING),
            g(STAGE_ZEROCUT),
        ]
        # Per-channel levels tint the two join arrows (Depth→Combine,
        # Speed→Combine) independently.
        branch_levels = [g(STAGE_DEPTH), g(STAGE_SPEED)]
        if (levels != self._last_connector_levels
                or branch_levels != self._last_branch_levels):
            self._last_connector_levels = levels
            self._last_branch_levels = branch_levels
            try:
                self._strip_host.set_connector_levels(levels)
                self._strip_host.set_branch_levels(branch_levels)
                self._strip_host.update()
            except RuntimeError:
                pass

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
        elif stage_id == STAGE_ZEROCUT:
            inner = self._build_zerocut_editor()
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
        # Per-stage border colour lerp + the live output number on each
        # card — both read the same per-stage level from the mapping
        # table. Cheap: the colour apply short-circuits below epsilon and
        # the number is epsilon-gated inside the card.
        for stage_id, trace_id in _STAGE_LEVEL_TRACE.items():
            v = payload.get(trace_id)
            if v is None:
                continue
            try:
                level = float(v)
            except (TypeError, ValueError):
                continue
            self._apply_stage_card_color(stage_id, level)
            card = self._stage_cards.get(stage_id)
            if card is not None:
                try:
                    card.set_output_number(level)
                except RuntimeError:
                    self._stage_cards.pop(stage_id, None)
        # Connector colours track the (epsilon-gated) per-stage levels.
        self._update_connector_levels()
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

    def _subscribe_intermediates(self) -> None:
        """Register the live-trace callback with the router. Idempotent;
        failures are swallowed (the chain still works without live
        graphs, the user just sees empty traces)."""
        if self._intermediates_subscribed:
            return
        router = getattr(self._controller, "motor_router", None)
        if router is not None and hasattr(router, "subscribe_intermediates"):
            try:
                router.subscribe_intermediates(
                    self._device_name, self._motor_idx, self._chain_idx,
                    self._intermediates_callback,
                )
                self._intermediates_subscribed = True
            except Exception:
                pass

    def _unsubscribe_intermediates(self) -> None:
        """Drop the live-trace callback. Idempotent."""
        if not self._intermediates_subscribed:
            return
        self._intermediates_subscribed = False
        router = getattr(self._controller, "motor_router", None)
        if router is not None and hasattr(router, "unsubscribe_intermediates"):
            try:
                router.unsubscribe_intermediates(
                    self._device_name, self._motor_idx, self._chain_idx,
                    self._intermediates_callback,
                )
            except Exception:
                pass

    def showEvent(self, ev) -> None:
        """(Re)subscribe when the chain actually comes on screen —
        page switched to Device Routing, toy card expanded, window
        restored. Pairs with hideEvent so off-screen chains are free."""
        super().showEvent(ev)
        self._subscribe_intermediates()

    def hideEvent(self, ev) -> None:
        """Pause the router feed while hidden (other page selected,
        toy card collapsed). The widgets keep their state; fresh data
        flows again on the next showEvent. The wrapper's ▸ Overview
        subscription pauses the same way in MotorChainListWidget."""
        super().hideEvent(ev)
        self._unsubscribe_intermediates()

    def teardown(self) -> None:
        """Unsubscribe from the router so its dispatcher stops trying
        to push payloads at a widget about to be destroyed. The
        wrapper (`MotorChainListWidget._rebuild`) calls this before
        deleteLater'ing each chain widget."""
        # Stop the accordion animation first so a late `finished`/tick
        # can't touch half-destroyed cards during teardown.
        try:
            self._accordion_anim.stop()
        except (RuntimeError, AttributeError):
            pass
        self._unsubscribe_intermediates()

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
        knobs from the old schema are gone (see docs/MOTOR_SIGNAL_CHAIN.md
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
        gain_spin = _NoTrackSpin()
        gain_spin.setRange(0.0, 2.0)
        gain_spin.setSingleStep(0.05)
        gain_spin.setDecimals(2)
        gain_spin.setValue(float(cfg.get("gain", 1.0)))
        # Two-way sync with the collapsed card's quick gain slider: both
        # write the same field; each mirrors the other (blockSignals
        # guards the echo). Connect AFTER setValue so the seed is silent.
        gain_spin.valueChanged.connect(
            lambda v, ck=channel_key: self._on_gain_from_spin(ck, float(v))
        )
        self._gain_spins[channel_key] = gain_spin
        gain_row.addWidget(gain_spin)
        gain_row.addWidget(self._ui._make_help_badge(
            "Gain",
            "Multiplies this channel after the curve. 1.0 = unchanged, "
            "0 = silences the channel entirely, up to 2.0 = boost "
            "(clamped to 1.0 downstream). Same knob as the slider on the "
            "collapsed card."
        ))
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
        param_spin = _NoTrackSpin()
        param_spin.setSingleStep(0.1)
        param_spin.setDecimals(2)
        param_spin.setRange(0.3, 8.0)
        param_spin.setValue(float(cfg.get("curve_param", 1.0)))
        curve_row.addWidget(param_spin)
        curve_row.addWidget(self._ui._make_help_badge(
            "Curve",
            "Reshapes the 0–1 signal before the gain. <b>linear</b>: "
            "unchanged. <b>power</b>: Param &lt;1 boosts light contact, "
            "&gt;1 suppresses it. <b>s_curve</b>: eases both ends and "
            "steepens the middle; Param is the iteration count — higher "
            "= sharper switch-like response."
        ))
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

        # Speed-only: fall-off. How long the speed signal keeps
        # ringing after movement stops — the detector holds its peak
        # and decays with this time constant, so a long fall-off
        # reads as "the toy keeps going after I stopped".
        if channel_key == "speed":
            fo_row = _hbox(0, 8)
            fo_row.addWidget(QLabel("Fall-off (ms):"))
            fo_spin = _NoTrackSpin()
            fo_spin.setRange(10.0, 2000.0)
            fo_spin.setSingleStep(50.0)
            fo_spin.setDecimals(0)
            fo_spin.setValue(float(cfg.get("decay_ms", 300.0)))
            fo_spin.valueChanged.connect(
                lambda v: _update_chain_field(
                    self._controller, self._device_name, self._motor_idx,
                    self._chain_idx, ("speed", "decay_ms"), float(v),
                )
            )
            fo_row.addWidget(fo_spin)
            fo_row.addWidget(self._ui._make_help_badge(
                "Fall-off",
                "How quickly Speed dies down once movement stops — the "
                "detector holds its peak and decays with this time "
                "constant. Lower = snappier cut-off, higher = lingering "
                "tail."
            ))
            fo_row.addStretch(1)
            lay.addLayout(fo_row)
        return host

    def _build_combine_editor(self) -> QWidget:
        """Combine policy — segmented Add / Max / Multiply."""
        host = QFrame()
        host.setObjectName("stageEditor")
        lay = _vbox(10, 8)
        host.setLayout(lay)

        hdr_row = _hbox(0, 6)
        header = QLabel("Combine")
        hf = header.font(); hf.setBold(True)
        header.setFont(hf)
        hdr_row.addWidget(header)
        hdr_row.addWidget(self._ui._make_help_badge(
            "Combine",
            "How the Depth and Speed channels merge into one signal. "
            "<b>Add</b>: sum of both, clamped to 1. <b>Max</b>: louder "
            "wins (the default). <b>Multiply</b>: the channels gate each "
            "other — either at 0 forces the output to 0, so the motor "
            "only runs while BOTH depth and movement are present."
        ))
        hdr_row.addStretch(1)
        lay.addLayout(hdr_row)

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

        return host

    def _build_zerocut_editor(self) -> QWidget:
        """Zero cut — enable toggle + zero threshold."""
        host = QFrame()
        host.setObjectName("stageEditor")
        lay = _vbox(10, 8)
        host.setLayout(lay)

        hdr_row = _hbox(0, 6)
        header = QLabel("Zero cut")
        hf = header.font(); hf.setBold(True)
        header.setFont(hf)
        hdr_row.addWidget(header)
        hdr_row.addWidget(self._ui._make_help_badge(
            "Zero cut",
            "The chain's final override. While the raw input reads at or "
            "below <b>Zero threshold</b> (plug removed, contact gone), the "
            "output snaps to 0 <i>instantly</i> — cutting the Smoothing "
            "fall tail and the Speed channel's ring instead of letting "
            "them fade out against a contact that is no longer there. "
            "Re-inserting starts the chain fresh from silence. Off by "
            "default; leave the threshold at 0.00 unless your contact "
            "idles slightly above zero."
        ))
        hdr_row.addStretch(1)
        lay.addLayout(hdr_row)

        chain = _read_chain(self._controller, self._device_name,
                            self._motor_idx, self._chain_idx)
        zc_cfg = chain.get("zerocut", {}) if isinstance(chain, dict) else {}
        if not isinstance(zc_cfg, dict):
            zc_cfg = {}  # hand-edited profile — build from defaults
        try:
            zc_threshold = float(zc_cfg.get("threshold", 0.0))
        except (TypeError, ValueError):
            zc_threshold = 0.0

        # Enable toggle.
        enable_cb = ToggleSwitch("Enable")
        enable_cb.setChecked(bool(zc_cfg.get("enabled", False)))
        enable_cb.toggled.connect(
            lambda v: _update_chain_field(
                self._controller, self._device_name, self._motor_idx, self._chain_idx,
                ("zerocut", "enabled"), bool(v),
            )
        )
        lay.addWidget(enable_cb)

        # Zero threshold: input at/below this counts as "not inserted".
        zt_row = _hbox(0, 8)
        zt_row.addWidget(QLabel("Zero threshold:"))
        zt_spin = _NoTrackSpin()
        zt_spin.setRange(0.0, 0.5)
        zt_spin.setSingleStep(0.01)
        zt_spin.setDecimals(2)
        zt_spin.setValue(zc_threshold)
        zt_spin.valueChanged.connect(
            lambda v: _update_chain_field(
                self._controller, self._device_name, self._motor_idx, self._chain_idx,
                ("zerocut", "threshold"), float(v),
            )
        )
        zt_row.addWidget(zt_spin)
        zt_row.addStretch(1)
        lay.addLayout(zt_row)

        return host

    def _build_gate_editor(self) -> QWidget:
        """Activity gate — enable toggle + wake threshold + sleep
        delay + the activity meter visual."""
        host = QFrame()
        host.setObjectName("stageEditor")
        lay = _vbox(10, 8)
        host.setLayout(lay)

        hdr_row = _hbox(0, 6)
        header = QLabel("Activity gate")
        hf = header.font(); hf.setBold(True)
        header.setFont(hf)
        hdr_row.addWidget(header)
        hdr_row.addWidget(self._ui._make_help_badge(
            "Activity gate",
            "Sidechain valve. Observes the speed detector's output; "
            "opens when activity crosses <b>Wake threshold</b>; closes "
            "after activity stays below threshold for <b>Sleep delay</b> "
            "seconds. <b>Build-up</b> / <b>Decay</b> set how slowly the "
            "activity meter itself charges with movement and drains in "
            "stillness — raise them to demand a few seconds of sustained "
            "motion instead of waking on a twitch. Off by default."
        ))
        hdr_row.addStretch(1)
        lay.addLayout(hdr_row)

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
        wt_spin = _NoTrackSpin()
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
        sd_spin = _NoTrackSpin()
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

        # Meter build-up: how long sustained movement takes to charge
        # the activity meter. High values make the gate demand a few
        # seconds of motion before waking instead of opening on the
        # first twitch.
        at_row = _hbox(0, 8)
        at_row.addWidget(QLabel("Build-up (s):"))
        at_spin = _NoTrackSpin()
        at_spin.setRange(0.01, 10.0)
        at_spin.setSingleStep(0.1)
        at_spin.setDecimals(2)
        at_spin.setValue(float(gate_cfg.get("attack_s", 0.05)))
        at_spin.valueChanged.connect(
            lambda v: _update_chain_field(
                self._controller, self._device_name, self._motor_idx, self._chain_idx,
                ("gate", "attack_s"), float(v),
            )
        )
        at_row.addWidget(at_spin)
        at_row.addStretch(1)
        lay.addLayout(at_row)

        # Meter decay: how long the charged meter takes to drain once
        # movement stops. High values keep the "budget" up across
        # brief pauses instead of bouncing below threshold.
        rl_row = _hbox(0, 8)
        rl_row.addWidget(QLabel("Decay (s):"))
        rl_spin = _NoTrackSpin()
        rl_spin.setRange(0.01, 10.0)
        rl_spin.setSingleStep(0.1)
        rl_spin.setDecimals(2)
        rl_spin.setValue(float(gate_cfg.get("release_s", 0.5)))
        rl_spin.valueChanged.connect(
            lambda v: _update_chain_field(
                self._controller, self._device_name, self._motor_idx, self._chain_idx,
                ("gate", "release_s"), float(v),
            )
        )
        rl_row.addWidget(rl_spin)
        rl_row.addStretch(1)
        lay.addLayout(rl_row)

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

        hdr_row = _hbox(0, 6)
        header = QLabel("Smoothing")
        hf = header.font(); hf.setBold(True)
        header.setFont(hf)
        hdr_row.addWidget(header)
        hdr_row.addWidget(self._ui._make_help_badge(
            "Smoothing",
            "Post-gate envelope follower. <b>Rise</b> controls how fast "
            "the output ramps up; <b>Fall</b> how fast it decays. The "
            "same knobs round the gate's open/close transitions, so no "
            "separate gate-smoothing settings exist."
        ))
        hdr_row.addStretch(1)
        lay.addLayout(hdr_row)

        chain = _read_chain(self._controller, self._device_name, self._motor_idx, self._chain_idx)
        sm_cfg = chain.get("smoothing", {}) if isinstance(chain, dict) else {}

        row = _hbox(0, 8)
        row.addWidget(QLabel("Rise:"))
        rise_spin = _NoTrackSpin()
        rise_spin.setRange(0.0, 2000.0)
        rise_spin.setSingleStep(10.0)
        rise_spin.setDecimals(0)
        rise_spin.setSuffix(" ms")
        rise_spin.setValue(float(sm_cfg.get("rise_ms", 50.0)))
        # Connect AFTER setValue so seeding is silent; the handler persists
        # and reflects the slower of rise/fall on the quick delay slider.
        rise_spin.valueChanged.connect(
            lambda v: self._on_smoothing_spin_changed("rise_ms", float(v))
        )
        self._smoothing_spins["rise_ms"] = rise_spin
        row.addWidget(rise_spin)
        row.addSpacing(12)
        row.addWidget(QLabel("Fall:"))
        fall_spin = _NoTrackSpin()
        fall_spin.setRange(0.0, 2000.0)
        fall_spin.setSingleStep(10.0)
        fall_spin.setDecimals(0)
        fall_spin.setSuffix(" ms")
        fall_spin.setValue(float(sm_cfg.get("fall_ms", 20.0)))
        fall_spin.valueChanged.connect(
            lambda v: self._on_smoothing_spin_changed("fall_ms", float(v))
        )
        self._smoothing_spins["fall_ms"] = fall_spin
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

        hdr_row = _hbox(0, 6)
        header = QLabel("Output")
        hf = header.font(); hf.setBold(True)
        header.setFont(hf)
        hdr_row.addWidget(header)

        if not self._is_linear:
            # Continuous-output actuator — the chain's post-smoothing
            # value drives whichever physical effect the buttplug.io
            # OutputType describes. Phrase looked up from the shared
            # _KIND_DISPLAY table; unknown kinds fall back to the
            # vibrate phrasing. Help Mode badge instead of permanent
            # text — there are no knobs here for vibrate motors.
            info = _KIND_DISPLAY.get(self._motor_kind, _DEFAULT_KIND_DISPLAY)
            hdr_row.addWidget(self._ui._make_help_badge(
                "Output",
                f"Continuous output — the final post-smoothing value "
                f"drives the {info.output_phrase}. Use the meter below "
                f"the chain to see the live output. No settings needed "
                f"for this motor kind."
            ))
            hdr_row.addStretch(1)
            lay.addLayout(hdr_row)
            return host
        hdr_row.addStretch(1)
        lay.addLayout(hdr_row)

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
            spin = _NoTrackSpin()
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
        primary. After the reset, tear down any built editors (they
        rebuild lazily with the fresh values on next expand), re-seed the
        Depth/Speed quick gain sliders, and restore the expanded stage."""
        _reset_chain_to_defaults(
            self._controller, self._device_name, self._motor_idx,
            self._chain_idx,
        )
        # Drop the precise-spinbox registries; rebuilt editors re-register.
        self._gain_spins.clear()
        self._smoothing_spins.clear()
        # Tear down any built editor so it rebuilds with the new values;
        # drop its stale mini-graph reference too.
        for sid in _STAGE_ORDER:
            card = self._stage_cards.get(sid)
            if card is None or not card.editor_built():
                continue
            card.reset_editor()
            self._stage_graphs.pop(sid, None)
        # Re-seed the collapsed quick controls from the defaults.
        chain = _read_chain(
            self._controller, self._device_name, self._motor_idx, self._chain_idx
        )
        for ck in (STAGE_DEPTH, STAGE_SPEED):
            slider = self._gain_sliders.get(ck)
            if slider is not None:
                cfg = chain.get(ck, {}) if isinstance(chain, dict) else {}
                try:
                    slider.set_gain(float(cfg.get("gain", 1.0)))
                except RuntimeError:
                    self._gain_sliders.pop(ck, None)
        if self._delay_control is not None:
            sm = chain.get("smoothing", {}) if isinstance(chain, dict) else {}
            try:
                self._delay_control.set_ms(max(float(sm.get("rise_ms", 50.0)),
                                               float(sm.get("fall_ms", 20.0))))
            except RuntimeError:
                self._delay_control = None
        # Restore the previously-expanded stage (rebuilds its editor) or
        # settle the collapsed strip.
        active = self._active_stage
        self._active_stage = None
        if active is not None:
            self._animate_to(active)
        else:
            self._apply_card_states(None)


# ----------------------------------------------------------
# MotorChainListWidget — Cut 5 wrapper for 1-or-2 chains.
# ----------------------------------------------------------

class MotorChainListWidget(QFrame):
    """Container that holds one or two `MotorSignalChainWidget`s for
    a single motor, plus the +Add / Remove controls and the merge
    picker between chains. Per the design lock in
    docs/MOTOR_SIGNAL_CHAIN.md § "Future: optional secondary chain",
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
                # Hide before detaching: a still-visible child reparented to
                # None briefly realises as a top-level window (a flash).
                w.hide()
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
                            sw.hide()
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

        # Row 1: frequency + amplitude + waveform
        r1 = _hbox(0, 12)
        r1.addWidget(QLabel("Frequency:"))
        freq_spin = _NoTrackSpin()
        freq_spin.setRange(0.05, 5.0)
        freq_spin.setSingleStep(0.05)
        freq_spin.setDecimals(2)
        freq_spin.setSuffix(" Hz")
        freq_spin.setValue(float(self._sim_state["freq"]))
        freq_spin.valueChanged.connect(self._on_sim_freq_changed)
        r1.addWidget(freq_spin)
        r1.addSpacing(8)
        r1.addWidget(QLabel("Amplitude:"))
        amp_spin = _NoTrackSpin()
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
        # Set visibility only after `body` is parented into `lay`: calling
        # setVisible(True) while it's still parentless makes Qt briefly realise
        # it as a top-level window, flashing a 640x480 box centre-screen.
        body.setVisible(self._sim_expanded)

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
        # Set visibility only after `body` is parented into `lay`: calling
        # setVisible(True) while it's still parentless makes Qt briefly realise
        # it as a top-level window, flashing a 640x480 box centre-screen.
        body.setVisible(self._overview_expanded)
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
                    w.hide()
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

    def showEvent(self, ev) -> None:
        """Resume the ▸ Overview feed when the wrapper comes back on
        screen (it pauses in hideEvent; the per-chain feeds do the
        same in MotorSignalChainWidget)."""
        super().showEvent(ev)
        if getattr(self, "_overview_expanded", False):
            self._subscribe_overview()

    def hideEvent(self, ev) -> None:
        """Pause the ▸ Overview feed while hidden — no router dispatch,
        no graph pushes, for a graph nobody can see."""
        super().hideEvent(ev)
        self._unsubscribe_overview()

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
