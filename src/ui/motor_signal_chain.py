"""Per-motor signal-chain widget — the user-facing surface for the
Input → Depth/Speed/Punch → Combine → Wake → Envelope → Zero cut →
Output pipeline (Wake merges the old Gate + Arming stages into one
two-mode stage; Envelope pairs Smoothing with the Texture wobble under
one card, split into two clearly-labelled halves).

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
    QRectF, QSize,
)
from PySide6.QtGui import (
    QColor, QFont, QFontMetrics, QPainter, QPainterPath, QPen, QBrush,
    QPolygonF,
)
from PySide6.QtWidgets import (
    QFrame, QWidget, QLabel, QLineEdit, QPushButton, QComboBox,
    QDoubleSpinBox, QButtonGroup, QSlider, QSizePolicy,
)

from constants import (
    BTN_HEIGHT_SMALL, COLOR_SUCCESS, COLOR_ALERT, COLOR_TEXT,
    COLOR_SURFACE, COLOR_SURFACE_HOVER, COLOR_TEXT_MUTED, COLOR_LIVE,
    COLOR_CHAIN_IDLE, COLOR_CHAIN_LIVE, COLOR_INPUT_BORDER,
    COLOR_WELL, COLOR_ACCENT, PALETTE,
    SIM_PEN_ADDRESS, SIM_TOUCH_ADDRESS, SIM_ADDRESSES,
)
from ui.layout_helpers import vbox as _vbox, hbox as _hbox
from ui import theme as _theme
from ui.widgets import ToggleSwitch, RainbowMeter as _RainbowMeter, ProgressProxy as _ProgressProxy
from ui.trace_graph import TraceGraph as _TraceGraph


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
MAX_CHAINS_PER_MOTOR = 6

# Valid merge operations for combining multiple chains' outputs.
_MERGE_OPS = ("add", "max", "multiply")

# Ceiling for the per-chain output gain. Mirrors
# MotorRouter._OUTPUT_GAIN_MAX (duplicated for the same reason as
# MAX_CHAINS_PER_MOTOR: the UI must not import the router at startup).
OUTPUT_GAIN_MAX = 2.0


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


def _get_chain_type(controller, device_name: str, motor_idx: int,
                    chain_idx: int = 0) -> str:
    """This chain's contact type: "penetration" | "touch" | "custom".

    Absent reads as "custom", which honours the explicit Touch/
    Penetration filters — how every chain behaved before types existed,
    so a hand-written config doesn't change feel on its own."""
    chain = _read_chain(controller, device_name, motor_idx, chain_idx)
    value = chain.get("type") if isinstance(chain, dict) else None
    value = str(value or "custom").lower()
    return value if value in CHAIN_TYPES else "custom"


def _chain_display_name(controller, device_name: str, motor_idx: int,
                        chain_idx: int = 0) -> str:
    """What a chain is CALLED, everywhere it is named: the fold bar, the
    card header, tooltips.

    Typed chains are named by their type ("Penetration" / "Touch") —
    that IS their identity, and letting a stale custom name shadow it
    would defeat the point of the label. A custom chain uses its
    user-given `name`, because "Custom" says nothing and "Chain 3" less;
    with several of them the name is the only way to remember which one
    does what. Unnamed customs fall back to "Chain N"."""
    ctype = _get_chain_type(controller, device_name, motor_idx, chain_idx)
    if ctype in ("touch", "penetration"):
        return CHAIN_TYPE_LABELS[ctype]
    chain = _read_chain(controller, device_name, motor_idx, chain_idx)
    name = chain.get("name") if isinstance(chain, dict) else None
    name = str(name or "").strip()
    return name if name else f"Chain {chain_idx + 1}"


def _clamp_num(value: Any, default: float, lo: float, hi: float) -> float:
    """Read a possibly-malformed profile number into a known-good range.
    NaN and non-numerics take the default."""
    try:
        v = float(value)
    except (TypeError, ValueError):
        return default
    if v != v:  # NaN
        return default
    return max(lo, min(hi, v))


def _get_output_stage(controller, device_name: str, motor_idx: int,
                      chain_idx: int = 0) -> Tuple[float, float, float]:
    """Read this chain's Output stage as `(gain, min, max)`.

    `gain` is the chain's own multiplier; `min`/`max` are the toy's
    usable output band, both in [0, 1]. An inverted band (min above max,
    only reachable by hand-editing) collapses to the ceiling — the same
    thing the router does with it."""
    chain = _read_chain(controller, device_name, motor_idx, chain_idx)
    cfg = chain.get("output") if isinstance(chain, dict) else None
    if not isinstance(cfg, dict):
        cfg = {}
    gain = _clamp_num(cfg.get("gain", 1.0), 1.0, 0.0, OUTPUT_GAIN_MAX)
    out_max = _clamp_num(cfg.get("max", 1.0), 1.0, 0.0, 1.0)
    out_min = _clamp_num(cfg.get("min", 0.0), 0.0, 0.0, 1.0)
    return gain, min(out_min, out_max), out_max


def _set_output_field(controller, device_name: str, motor_idx: int,
                      chain_idx: int, key: str, value: float) -> None:
    """Write one Output-stage field (`gain` / `min` / `max`) for this
    chain and persist it."""
    hi = OUTPUT_GAIN_MAX if key == "gain" else 1.0
    _update_chain_field(controller, device_name, motor_idx, chain_idx,
                        ("output", key), _clamp_num(value, 0.0, 0.0, hi))


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


def _read_wake_cfg(chain: Dict[str, Any]) -> Dict[str, Any]:
    """The chain's Wake config for seeding the Wake card's widgets, with
    the canonical wake defaults backfilled for any missing key so callers
    can read without further fallbacks."""
    from motor_router import MotorRouter
    out = copy.deepcopy(MotorRouter.DEFAULT_MIX_CONFIG["chains"][0]["wake"])
    if isinstance(chain, dict) and isinstance(chain.get("wake"), dict):
        out.update(chain["wake"])
    return out


def _update_wake_field(controller, device_name: str, motor_idx: int,
                       chain_idx: int, subkey: str, value: Any) -> None:
    """Write one `wake.<subkey>` field (see _update_wake_fields)."""
    _update_wake_fields(controller, device_name, motor_idx, chain_idx,
                        ((subkey, value),))


def _update_wake_fields(controller, device_name: str, motor_idx: int,
                        chain_idx: int, updates) -> None:
    """Write several `wake.<subkey>` fields in ONE read-modify-write pass —
    one write/recalc cycle for the whole gesture."""
    per_motor = copy.deepcopy(
        _read_per_motor(controller, device_name, motor_idx)
    )
    chain = _ensure_chain_at(per_motor, chain_idx)
    wake = chain.get("wake")
    if not isinstance(wake, dict):
        wake = {}
        chain["wake"] = wake
    for subkey, value in updates:
        wake[subkey] = value
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
STAGE_PUNCH = "punch"
STAGE_COMBINE = "combine"
# Wake merges the pre-merge Gate + Arming stages into one two-mode stage
# (mode "activity" = the old Gate, "strokes" = the old Arming/sleep gate).
STAGE_WAKE = "wake"
# Envelope pairs Smoothing + Texture under one card, split into two
# labelled halves; the config keys stay `smoothing` and `texture`
# separately (only the card merges).
STAGE_ENVELOPE = "envelope"
STAGE_ZEROCUT = "zerocut"
STAGE_OUTPUT = "output"

_STAGE_ORDER = (
    STAGE_INPUT, STAGE_DEPTH, STAGE_SPEED, STAGE_PUNCH,
    STAGE_COMBINE, STAGE_WAKE, STAGE_ENVELOPE, STAGE_ZEROCUT,
    STAGE_OUTPUT,
)

_STAGE_LABELS = {
    STAGE_INPUT:     "Input",
    STAGE_DEPTH:     "Depth",
    STAGE_SPEED:     "Speed",
    STAGE_PUNCH:     "Punch",
    STAGE_COMBINE:   "Combine",
    STAGE_WAKE:      "Wake",
    STAGE_ENVELOPE:  "Envelope",
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
    STAGE_PUNCH:     "Pch",
    STAGE_COMBINE:   "Cmb",
    STAGE_WAKE:      "Wake",
    STAGE_ENVELOPE:  "Env",
    STAGE_ZEROCUT:   "Cut",
    STAGE_OUTPUT:    "Out",
}


# One explanation per stage, set on the stage's card: hovering the collapsed
# card explains the stage, and every knob in its editor that has no more
# specific tip of its own falls back to it (Qt passes an unanswered tooltip
# request up to the parent). Headings with a fixed explanation use the same
# entry, so each stage's words live in exactly one place.
_STAGE_TIPS = {
    STAGE_INPUT: (
        "Input",
        "Where this chain's signal comes from: which of your avatar's zones "
        "it listens to, touch or penetration, from you or from others. "
        "Every stage after this one shapes what comes in here."),
    STAGE_DEPTH: (
        "Depth",
        "How deep the contact is \u2014 the steady part of the feel. Deeper "
        "or closer gives a stronger signal. Its gain and curve decide how "
        "depth turns into output."),
    STAGE_SPEED: (
        "Speed",
        "How fast the contact is moving \u2014 the lively part of the feel. "
        "Faster strokes give a stronger signal, which fades out once "
        "movement stops. Its gain, curve and fall-off decide how movement "
        "turns into output."),
    STAGE_PUNCH: (
        "Punch",
        "Attack transients: a fast stroke spikes a short hit on top "
        "of the sustained level, then decays. Merges max-wins with "
        "the Depth/Speed combine — an accent, never a duck. Slow "
        "repositioning is ignored in both directions.<br><br>"
        "<b>In</b> fires on a fast thrust inward, <b>Out</b> on a "
        "fast pull outward, with a gain each — the same two sliders "
        "as on the collapsed card. Out ships at ×0.00, so Punch "
        "behaves as a thrust-only accent until you raise it. Each "
        "direction keeps its own envelope, so the pull-out of a "
        "stroke never cuts the thrust's hit short. <b>Decay</b> is "
        "shared: it sets how long a hit rings out either way."),
    STAGE_COMBINE: (
        "Combine",
        "How the Depth and Speed channels merge into one signal. "
        "<b>Add</b>: sum of both, clamped to 1. <b>Max</b>: louder "
        "wins (the default). <b>Multiply</b>: the channels gate each "
        "other — either at 0 forces the output to 0, so the motor "
        "only runs while BOTH depth and movement are present."),
    STAGE_WAKE: (
        "Wake",
        "The activity gate — nothing plays until real contact is "
        "detected, in one of two interchangeable ways (pick with the "
        "mode toggle). <b>Activity</b>: an analog meter charges from "
        "the chosen <b>Source</b> and opens above <b>Wake "
        "threshold</b>, sleeping <b>Sleep delay</b> seconds after the "
        "source goes quiet (Build-up / Decay shape how fast the meter "
        "fills and drains). <b>Source</b> picks what charges it: "
        "<i>Depth</i> = insertion depth, so presence alone keeps it "
        "awake; <i>Speed</i> = movement only, so tiny fast jiggles can "
        "wake it; <i>Both</i> = movement while actually inserted — a "
        "shallow flutter can't trigger it (the default). Punch is "
        "deliberately never a source: it exaggerates small movements "
        "by design, which would make the gate hair-triggered. "
        "<b>Strokes</b>: the sleep gate — silent until <b>Thrusts</b> "
        "full strokes land inside <b>Window</b>, stays awake while they "
        "keep coming, disarms after the quiet timeout. An accidental "
        "brush can't wake Strokes mode; it's what makes 🌙 Sleep safe "
        "to wear while sleeping. Off by default."),
    STAGE_ENVELOPE: (
        "Envelope",
        "How the level moves over time, in two halves. <b>Smoothing</b> "
        "is the calm half: it softens the signal and rounds sharp "
        "jumps — <b>Rise</b> sets how fast it climbs, <b>Fall</b> how "
        "fast it eases back down, and the same knobs round the Wake "
        "gate's open/close. <b>Texture</b> is the lively half: a subtle "
        "downward-only wobble layered on top so a steady hold feels "
        "alive instead of dead flat — <b>Amount</b> is how deep the "
        "wobble and <b>Rate</b> how fast it cycles. Two knobs tie the "
        "wobble to your movement: <b>Faster with movement</b> speeds the "
        "rate up as you move, and <b>Depth vs movement</b> scales the "
        "depth — <i>Stronger</i> makes it deeper the faster you move, "
        "while <i>Weaker</i> gives full grain at rest and fades it out "
        "under motion (the movement itself already carries the life, so "
        "the wobble stops fighting it); <i>Off</i> keeps a steady, "
        "constant grain. Texture comes <i>after</i> smoothing on "
        "purpose — ahead of it, smoothing would just iron the wobble "
        "back out."),
    STAGE_ZEROCUT: (
        "Zero cut",
        "The chain's final override. While the raw input reads at or "
        "below <b>Zero threshold</b> (plug removed, contact gone), the "
        "output snaps to 0 <i>instantly</i> — cutting the Smoothing "
        "fall tail and the Speed channel's ring instead of letting "
        "them fade out against a contact that is no longer there. "
        "Re-inserting starts the chain fresh from silence. Off by "
        "default; leave the threshold at 0.00 unless your contact "
        "idles slightly above zero.<br><br>"
        "<b>It watches everything this motor listens to</b>, not one "
        "source — the loudest of its zones, SPS sources and mapped "
        "variables. So the cut fires only once they are <i>all</i> "
        "quiet, and a variable that idles high will hold it off. If "
        "the cut never seems to fire, check the Listening To column "
        "for a parameter that never reaches zero."),
    STAGE_OUTPUT: (
        "Output",
        "The last stage before the toy: a gain to balance this chain "
        "against your other toys, and a range that fits the chain's "
        "0\u2013100 % into what this toy can usefully do."),
}

_CURVE_KINDS = ("linear", "power", "s_curve")
_COMBINE_OPS = ("add", "max", "multiply")
# Collapsed-card labels for the combine cycle button. Only one shows at a
# time, so they can be spelled out.
_COMBINE_LABELS = {"add": "Add", "max": "Max", "multiply": "Multiply"}

# What kind of contact a chain is for. Duplicated from motor_router for
# the same reason as MAX_CHAINS_PER_MOTOR: the UI must not import the
# router at startup.
CHAIN_TYPES = ("penetration", "touch", "custom")
CHAIN_TYPE_LABELS = {"penetration": "Penetration", "touch": "Touch",
                     "custom": "Custom"}
# Accent colour per type, painted as a slim bar on the fold row so a
# stack of six chains is scannable by colour before any name is read.
# Penetration borrows the depth-trace blue, touch the outward-speed cyan.
# One hue per chain TYPE, from the hues no toy frame can wear (see
# ui.theme.CHAIN_TYPE_HUES): a chain is never mistaken for a toy.
CHAIN_TYPE_ACCENTS = {k: PALETTE[h][0] for k, h in _theme.CHAIN_TYPE_HUES.items()}
# Fold-row merge tags: how this chain joins the one above it.
_MERGE_TAGS = {"add": "+", "max": "∨", "multiply": "×"}


# Per-stage trace specifications for the inlined per-stage mini-graphs
# (Cut 6). Mapping is documented in docs/CHAIN_INLINED_TUNING.md §
# "Per-stage graph trace mapping". Each entry is (trace_id, color,
# style_dict) — same shape as TraceGraph's traces argument.
#
# Trace styles mirror Tune's six-trace graph for visual continuity:
#   * raw signals (d_raw / s_raw): solid, lighter tints
#   * shaped signals (d_shaped / s_shaped): dashed
#   * mixed (post-combine): dotted purple
#   * wake_meter (the Wake meter / arming progress): dotted yellow
#   * wake_out (post-wake signal): solid cyan
#   * out (post-smooth chain output): bold green

_TRACE_STYLE = {
    # One identity hue per stage, by what the signal IS: depth blue, speed
    # amber, punch pink (the live accent's spike), combined purple, the
    # wake meter yellow, post-wake / envelope cyan, texture grey, and the
    # chain's own output in the accent. Raw = solid, shaped = dashed.
    "d_raw":    (PALETTE["blue"][0],   {"width": 1.6}),
    "s_raw":    (PALETTE["amber"][0],  {"width": 1.6}),
    "d_shaped": (PALETTE["blue"][0],   {"width": 1.8, "dash": "dash"}),
    "s_shaped": (PALETTE["amber"][0],  {"width": 1.8, "dash": "dash"}),
    "punch":    (PALETTE["pink"][0],   {"width": 1.8, "dash": "dash"}),
    # Directional halves: inward keeps the stage's hue, outward takes the
    # cool complement so an asymmetric tuning is visible at a glance.
    "s_in_shaped":  (PALETTE["amber"][0],  {"width": 1.8, "dash": "dash"}),
    "s_out_shaped": (PALETTE["cyan"][0],   {"width": 1.8, "dash": "dash"}),
    "punch_in":     (PALETTE["pink"][0],   {"width": 1.8, "dash": "dash"}),
    "punch_out":    (PALETTE["purple"][0], {"width": 1.8, "dash": "dash"}),
    "mixed":    (PALETTE["purple"][0], {"width": 1.6, "dash": "dot"}),
    "wake_meter": (PALETTE["yellow"][0], {"width": 1.6, "dash": "dot"}),
    "wake_out":  (PALETTE["cyan"][0],  {"width": 1.6}),
    "smoothed": (PALETTE["cyan"][0],   {"width": 1.6, "dash": "dash"}),
    "textured": (PALETTE["grey"][0],   {"width": 1.6, "dash": "dot"}),
    "out":      (COLOR_ACCENT,         {"width": 2.2}),

}

_STAGE_TRACES: Dict[str, Tuple[str, ...]] = {
    STAGE_INPUT:     ("d_raw",),
    STAGE_DEPTH:     ("d_raw", "d_shaped"),
    STAGE_SPEED:     ("s_raw", "s_in_shaped", "s_out_shaped"),
    STAGE_PUNCH:     ("d_raw", "punch_in", "punch_out"),
    STAGE_COMBINE:   ("d_shaped", "s_shaped", "mixed"),
    STAGE_WAKE:      ("mixed", "wake_meter", "wake_out"),
    STAGE_ENVELOPE:  ("wake_out", "smoothed", "textured"),
    STAGE_ZEROCUT:   ("textured", "out"),
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
    STAGE_PUNCH:     "punch",
    STAGE_COMBINE:   "mixed",
    STAGE_WAKE:      "wake_out",
    STAGE_ENVELOPE:  "textured",
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
# Connector-cell width: floor and ceiling. The gaps carry no information,
# so they are the first thing to give up room when the row is tight — the
# floor is just an arrowhead and the two short stubs the elbow routing
# needs. But they are not meant to stay hairlines on a big window either,
# so they grow with the row up to the ceiling and then stop, handing
# everything beyond it to the cards. Small is a size they are ALLOWED to
# reach under pressure, not their permanent state.
_CONNECTOR_GAP = 16
_CONNECTOR_GAP_MAX = 52
# How the settled all-collapsed row splits its surplus (see
# `_claim_row_slack`). The connectors take NO stretch — they are sized by
# preference instead (see `_ConnectorCell`), so surplus beyond the gaps'
# preferred width lands entirely on the cards.
_SLOT_STRETCH_GROWABLE = 1
_SLOT_STRETCH_CONNECTOR = 0
# How far a fork/join anchor sits from the top and bottom of the shared
# card's edge, so the outer arrows clear its rounded corners.
_BRANCH_EDGE_INSET = 16
# Arrowhead half-width on a fork/join leg. Finer than _draw_arrow's,
# because these legs are short and a 5px head eats a 16px gap on its own.
_ELBOW_HEAD = 4.0
# Travel direction implied by a card side. Leaving one heads outward
# from the card; arriving at one heads inward toward it, which is also
# the direction the arrowhead points.
_SIDE_LEAVE = {"top": "up", "bottom": "down",
               "left": "left", "right": "right"}
_SIDE_ARRIVE = {"top": "down", "bottom": "up",
                "left": "right", "right": "left"}
_QWIDGETSIZE_MAX = 16_777_215  # Qt's QWIDGETSIZE_MAX; "unbounded" max width/height

# Gain quick-slider: integer track 0..200 maps to gain 0.0..2.0 (1 step
# == 0.01); tick marks render at 0.5/1.0/1.5.
_GAIN_SLIDER_MAX = 200
# Floor for the short sliders on cards that used to be compact (Wake,
# Output). Short enough that five extra controls still fit the row;
# _compute_target_widths grows them past this on any real window.
_MINI_SLIDER_MIN_W = 48
_GAIN_SLIDER_SCALE = 100.0
_GAIN_TICK_INTERVAL = 50      # ticks at track positions 50/100/150
# The gain slider stretches to whatever its row leaves after the tag and
# the value column; a hard minimum here (it was 130) made the row wider
# than its collapsed card, and Qt resolved that by laying the value label
# over the groove's end. Long sliders come from wide cards, not from
# a floor the card cannot honour.
_GAIN_SLIDER_MIN_W = _MINI_SLIDER_MIN_W
# One rule for every slider-with-value row (collapsed gain sliders, the
# delay slider, the Output/Wake value controls, the strength sliders):
#   [tag 26px] [slider, expanding] [gap 10px] [value 48px, right-aligned]
# all vertically centred on the groove. FIXED widths, so the value column
# lines up across stacked rows and the text can never spill onto the
# slider's end cap.
SLIDER_TAG_W = 26
SLIDER_VALUE_GAP = 10
SLIDER_VALUE_W = 48

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
        # Track: the well inside the frame line, like every other meter.
        p.fillRect(0, 0, w, h, QColor(COLOR_WELL))
        # Fill: accent while the gate is open, muted while it is closed --
        # a closed gate is a state, not an error.
        fill_color = QColor(COLOR_SUCCESS) if self._open else QColor(COLOR_TEXT_MUTED)
        fill_w = int((w - 2) * self._value)
        if fill_w > 0:
            p.fillRect(1, 1, fill_w, h - 2, fill_color)
        # Threshold tick — narrow vertical line.
        tx = int(w * self._threshold)
        pen = QPen(QColor(COLOR_TEXT))
        pen.setWidth(2)
        p.setPen(pen)
        p.drawLine(tx, 1, tx, h - 1)
        p.setPen(QPen(QColor(COLOR_INPUT_BORDER), 1))
        p.setBrush(Qt.NoBrush)
        p.drawRect(0, 0, w - 1, h - 1)
        p.end()


# ----------------------------------------------------------
# ValveIndicator — animated open/closed bar for the Wake stage card.
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
        # Track: the well inside the frame line, like every other meter.
        p.fillRect(0, 0, w, h, QColor(COLOR_WELL))
        # Fill (open) — accent; width follows the animated current
        # position so opens and closes are equally visible.
        fill_w = int((w - 2) * self._current)
        if fill_w > 0:
            p.fillRect(1, 1, fill_w, h - 2, QColor(COLOR_SUCCESS))
        p.setPen(QPen(QColor(COLOR_INPUT_BORDER), 1))
        p.setBrush(Qt.NoBrush)
        p.drawRect(0, 0, w - 1, h - 1)
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
    as `_GainSlider`, so it drops into the gain-sync wiring unchanged.

    `label` prefixes the row (Speed and Punch stack two of these, one per
    stroke direction). A labelled control also drops the slider's tick
    marks: two stacked rows would otherwise pay for two sets of ticks in
    a card that has to stay the height of its single-slider neighbour,
    and drag-snapping lives in `_GainSlider.setValue`, not in whether the
    detents are drawn."""

    gainChanged = Signal(float)

    def __init__(self, gain: float, parent: Optional[QWidget] = None,
                 label: str = "") -> None:
        super().__init__(parent)
        lay = _hbox(0, SLIDER_VALUE_GAP)
        self.setLayout(lay)
        if label:
            tag = QLabel(label)
            tag.setProperty("muted", "true")
            tf = tag.font()
            tf.setPointSize(max(7, tf.pointSize() - 1))
            tag.setFont(tf)
            tag.setFixedWidth(SLIDER_TAG_W)   # "In" / "Out" share one column
            lay.addWidget(tag, 0)
        self._slider = _GainSlider(gain)
        self._slider.setMinimumWidth(_GAIN_SLIDER_MIN_W)
        if label:
            self._slider.setTickPosition(QSlider.NoTicks)
        self._value = QLabel()
        self._value.setObjectName("gainValue")
        self._value.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self._value.setFixedWidth(SLIDER_VALUE_W)
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


class _ValueControl(QWidget):
    """A short slider over an arbitrary float range plus an inline
    readout — the collapsed-card control for stages whose quick knob
    isn't a gain: Wake's threshold, Output's chain gain.

    Deliberately narrower than `_GainControl`: those live on cards that
    were compact (40-60px) before gaining a control, and the strip has
    seven slots to fit across one row. The track is short but real, and
    `_compute_target_widths` hands these cards the row's surplus, so on
    any normal window they end up longer than this floor.

    `fmt` renders the readout (e.g. "0.05", "×0.70"); `scale` maps the
    integer track onto the value range, since QSlider is integer-only."""

    valueChanged = Signal(float)

    def __init__(self, value: float, lo: float, hi: float,
                 fmt: str = "{:.2f}", steps: int = 100,
                 parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._lo, self._hi, self._fmt = float(lo), float(hi), fmt
        self._steps = max(1, int(steps))
        lay = _hbox(0, SLIDER_VALUE_GAP)
        self.setLayout(lay)
        self._slider = QSlider(Qt.Horizontal)
        self._slider.setRange(0, self._steps)
        self._slider.setMinimumWidth(_MINI_SLIDER_MIN_W)
        self._slider.setTickPosition(QSlider.NoTicks)
        self._slider.setValue(self._to_track(value))
        self._value = QLabel()
        self._value.setObjectName("gainValue")
        self._value.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        # Wide enough for the bold "x0.00" so the text never spills
        # left over the slider's end cap.
        self._value.setFixedWidth(SLIDER_VALUE_W)
        lay.addWidget(self._slider, 1)
        lay.addWidget(self._value, 0)
        self._slider.valueChanged.connect(self._on_slider)
        self._sync_label()

    def _to_track(self, value: float) -> int:
        try:
            v = float(value)
        except (TypeError, ValueError):
            v = self._lo
        span = max(1e-9, self._hi - self._lo)
        frac = (v - self._lo) / span
        return max(0, min(self._steps, int(round(frac * self._steps))))

    def value(self) -> float:
        span = self._hi - self._lo
        return self._lo + (self._slider.value() / self._steps) * span

    def _sync_label(self) -> None:
        self._value.setText(self._fmt.format(self.value()))

    def _on_slider(self, _v: int) -> None:
        self._sync_label()
        self.valueChanged.emit(self.value())

    def set_value(self, value: float) -> None:
        """Set silently (mirroring an edit made in the expanded editor)."""
        self._slider.blockSignals(True)
        self._slider.setValue(self._to_track(value))
        self._slider.blockSignals(False)
        self._sync_label()


class _DelayControl(QWidget):
    """A smoothing-delay slider (ms) + inline readout for the collapsed
    Smoothing card. One slider sets BOTH rise and fall to the same delay —
    a single 'how smooth' knob; the expanded editor keeps them independent.
    Mirrors _GainControl's shape (`set_ms` / `ms` / `msChanged`)."""

    msChanged = Signal(int)

    def __init__(self, ms: float, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        lay = _hbox(0, SLIDER_VALUE_GAP)
        self.setLayout(lay)
        self._slider = _MsSlider(ms)
        self._slider.setMinimumWidth(_GAIN_SLIDER_MIN_W)
        self._value = QLabel()
        self._value.setObjectName("gainValue")
        self._value.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self._value.setFixedWidth(SLIDER_VALUE_W)
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

        # 5px, not 8: the QSS on #tuneStageCard already adds 4px of its
        # own padding, so 8 here meant ~12px of inset per side on cards
        # whose content is a slider row. Trimmed on the layout rather
        # than in the stylesheet because ui/fold_strip.py reuses the same
        # objectName for the backend strip and should not move with this.
        root = _vbox(5, 3)
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

class _ConnectorCell(QWidget):
    """The spacer a connector arrow is painted across.

    Sized by PREFERENCE rather than by stretch, which is what encodes
    "small is a size these may reach under pressure, not their normal
    state": the cell asks for `_CONNECTOR_GAP_MAX`, will shrink all the
    way to `_CONNECTOR_GAP` when the row is tight, and never grows past
    what it asked for. Because it takes no stretch, surplus beyond that
    preference goes to the cards instead — a wider window buys longer
    slider tracks, not wider empty gaps.

    Doing this with stretch factors instead gets the order backwards: the
    gaps keep a proportional share of the surplus even while the cards
    are pinned at their floor."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setMinimumWidth(_CONNECTOR_GAP)
        self.setMaximumWidth(_CONNECTOR_GAP_MAX)
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Minimum)

    def sizeHint(self) -> QSize:
        return QSize(_CONNECTOR_GAP_MAX, 0)

    def minimumSizeHint(self) -> QSize:
        return QSize(_CONNECTOR_GAP, 0)


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
        # Fork/join around the parallel Depth/Speed/Punch slot: Input forks
        # into every parallel source, and all join into Combine.
        # `_branch_index` is that slot's position in `_slots`;
        # `_branch_cards` is [depth, speed, punch].
        self._branch_index: int = -1
        self._branch_cards: List[QWidget] = []
        self._branch_levels: List[float] = []
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
        cb = getattr(self, "_on_resize", None)
        if cb is not None:
            try:
                cb()
            except RuntimeError:
                pass
        self.update()

    def paintEvent(self, _ev) -> None:
        if len(self._slots) < 2:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        has_branch = (0 <= self._branch_index < len(self._slots)
                      and len(self._branch_cards) >= 2)
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
                    # Fork: Input splits into the parallel sources, using
                    # three DIFFERENT sides of its own rectangle — top,
                    # right, bottom — one per branch. Each leg arrives on
                    # its target's left edge like every other connector.
                    for idx, card in enumerate(self._branch_cards):
                        side = self._branch_side(idx, n, outgoing=True)
                        dst = self._card_anchor(card, right=False)
                        src = (self._aligned_edge_anchor(a, side, dst[1])
                               if side in ("left", "right")
                               else self._edge_anchor(a, side))
                        self._draw_route(
                            p, src, dst, _SIDE_LEAVE[side], "right", color)
                elif has_branch and i == self._branch_index:
                    # Join: the sources merge into Combine through three
                    # different sides of ITS rectangle — top, left,
                    # bottom — so the outer arrowheads point down and up.
                    # Each is tinted by its own channel level.
                    for idx, card in enumerate(self._branch_cards):
                        lv = (self._branch_levels[idx]
                              if idx < len(self._branch_levels) else 0.0)
                        side = self._branch_side(idx, n, outgoing=False)
                        src = self._card_anchor(card, right=True)
                        tint = _lerp_color(_CONNECTOR_IDLE, _CONNECTOR_LIVE, lv)
                        dst = (self._aligned_edge_anchor(b, side, src[1])
                               if side in ("left", "right")
                               else self._edge_anchor(b, side))
                        self._draw_route(
                            p, src, dst, "right", _SIDE_ARRIVE[side], tint)
                else:
                    self._draw_arrow(p, self._card_anchor(a, right=True),
                                     self._card_anchor(b, right=False), color)
            except RuntimeError:
                continue
        p.end()

    def _card_anchor(self, w: QWidget, right: bool):
        """(x, y) in this host's coordinates for a card's connector anchor
        on its right or left edge: always the card's vertical middle, since
        every slot is centred on one line. mapTo handles nested cards —
        Depth/Speed live inside the ds container, not directly under the
        host."""
        tl = w.mapTo(self, QPoint(0, 0))
        x = tl.x() + (w.width() if right else 0)
        return (x, tl.y() + max(2, w.height()) // 2)

    def _branch_side(self, idx: int, n: int, outgoing: bool):
        """Which side of the SHARED card branch `idx` of `n` uses.

        Outgoing (the fork, on Input): top / right / bottom.
        Incoming (the join, on Combine): top / left / bottom.
        The first branch takes the top edge, the last the bottom, and
        everything between shares the vertical edge facing the row."""
        facing = "right" if outgoing else "left"
        if n <= 1:
            return facing
        if idx == 0:
            return "top"
        if idx == n - 1:
            return "bottom"
        return facing

    def _aligned_edge_anchor(self, w: QWidget, side: str, y: float):
        """Anchor on a card's LEFT or RIGHT edge, pulled to `y` so the leg
        runs perfectly flat instead of at a slight angle.

        The middle branch connects two cards whose vertical centres are
        close but not equal — Input is centred in its slot, Speed is the
        middle of three stacked cards — and a 20px drop over a long run
        reads as a wonky line next to the crisp right angles either side
        of it. Clamped into the card so the anchor can never slide off
        its own edge."""
        x, _ = self._edge_anchor(w, side)
        tl = w.mapTo(self, QPoint(0, 0))
        h = float(max(2, w.height()))
        lo = tl.y() + _BRANCH_EDGE_INSET
        hi = tl.y() + h - _BRANCH_EDGE_INSET
        if lo > hi:
            lo = hi = tl.y() + h / 2.0
        return (x, min(hi, max(lo, float(y))))

    def _edge_anchor(self, w: QWidget, side: str):
        """(x, y) at the middle of one named side of a card, in host
        coordinates. `side` is "left" / "right" / "top" / "bottom"."""
        tl = w.mapTo(self, QPoint(0, 0))
        x0, y0 = float(tl.x()), float(tl.y())
        ww, hh = float(max(2, w.width())), float(max(2, w.height()))
        if side == "left":
            return (x0, y0 + hh / 2.0)
        if side == "right":
            return (x0 + ww, y0 + hh / 2.0)
        if side == "top":
            return (x0 + ww / 2.0, y0)
        return (x0 + ww / 2.0, y0 + hh)          # bottom

    @classmethod
    def _draw_route(cls, p: QPainter, start, end,
                    leave: str, arrive: str, color: QColor) -> None:
        """Draw one fork/join leg as a single right-angled turn, leaving
        the source through the `leave` side and arriving at the target
        through the `arrive` side.

        This is what puts the three legs on three DIFFERENT sides of the
        shared card rather than three heights of the same one: Input is
        exited through its top, right and bottom edges, and Combine is
        entered through its top, left and bottom edges. The arrowhead
        rotates to match `arrive`, so the outer join legs point down and
        up into Combine's horizontal edges.

        One rule covers every case. If the line leaves through a
        horizontal edge it travels vertically first and turns once;
        if it arrives at one it travels horizontally first and turns
        once; if both ends are vertical edges it needs no turn at all.
        Corner placement therefore falls out of the two directions and
        never has to be guessed."""
        sx, sy = float(start[0]), float(start[1])
        ex, ey = float(end[0]), float(end[1])
        leave_vertical = leave in ("up", "down")
        arrive_vertical = arrive in ("up", "down")

        if leave_vertical:
            corner = (sx, ey)
        elif arrive_vertical:
            corner = (ex, sy)
        else:
            corner = None

        ah = _ELBOW_HEAD
        # Stop the stroke short of the tip so the head isn't drawn over.
        if arrive == "right":
            stop = (ex - 2.0 * ah, ey)
            head = [(ex, ey), (ex - 2.0 * ah, ey + ah), (ex - 2.0 * ah, ey - ah)]
        elif arrive == "left":
            stop = (ex + 2.0 * ah, ey)
            head = [(ex, ey), (ex + 2.0 * ah, ey + ah), (ex + 2.0 * ah, ey - ah)]
        elif arrive == "down":
            stop = (ex, ey - 2.0 * ah)
            head = [(ex, ey), (ex + ah, ey - 2.0 * ah), (ex - ah, ey - 2.0 * ah)]
        else:                                     # up
            stop = (ex, ey + 2.0 * ah)
            head = [(ex, ey), (ex + ah, ey + 2.0 * ah), (ex - ah, ey + 2.0 * ah)]

        pen = QPen(color)
        pen.setWidth(2)
        pen.setCapStyle(Qt.RoundCap)
        pen.setJoinStyle(Qt.RoundJoin)
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        path = QPainterPath(QPointF(sx, sy))
        if corner is not None:
            path.lineTo(QPointF(corner[0], corner[1]))
        path.lineTo(QPointF(stop[0], stop[1]))
        p.drawPath(path)

        p.setPen(Qt.NoPen)
        p.setBrush(QBrush(color))
        p.drawPolygon(QPolygonF([QPointF(x, y) for x, y in head]))

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
    shared helpers (`_explain`, `_repolish`,
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
        # The open chain is a card-level frame in its type hue.
        self.setProperty("hue", _theme.CHAIN_TYPE_HUES.get(
            _get_chain_type(self._controller, device_name, motor_idx,
                            self._chain_idx), "grey"))
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
        # Name the chain by what drives it. "Chain 2" says nothing; a
        # motor now carries one chain per kind of contact, and which is
        # which is the first thing you need to know when you open it.
        chain_type = _get_chain_type(
            self._controller, device_name, motor_idx, self._chain_idx)
        label = CHAIN_TYPE_LABELS.get(chain_type)
        if label and chain_type != "custom":
            title_text += f" · {label}"
        elif self._chain_idx > 0:
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
            "Wipe every setting in THIS chain (channels, curves, punch, "
            "combine, wake, envelope, zero cut) back to the built-in "
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
        # Optional valve indicator on the Wake stage card only.
        self._stage_valve: Optional[ValveIndicator] = None
        # Collapsed-card quick controls, kept so an edit made in the
        # expanded editor can mirror back onto them (and so Wake's can be
        # swapped when its mode changes).
        self._quick_toggles: Dict[str, ToggleSwitch] = {}
        self._wake_quick: Optional[_ValueControl] = None
        self._output_gain_quick: Optional[_ValueControl] = None
        self._combine_cycle: Optional[QPushButton] = None
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
        self._apply_strip_mode()

        # ---- Vibe meter ----------------------------------------------
        self._vibe_meter = _RainbowMeter(maximum=1000)
        self._vibe_proxy = _ProgressProxy(self._vibe_meter)
        root.addWidget(self._vibe_meter)

        # Activity meter widget (lives inside the Wake stage editor,
        # driven from this widget's own intermediates subscription below).
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
        self._connectors = []
        self._slot_for_stage = {}
        # The gaps are re-budgeted on every resize; cards get first call
        # on the width (see _apply_connector_widths).
        host._on_resize = self._apply_connector_widths

        def make_connector() -> QWidget:
            # Flexible spacer the connector arrow is painted across.
            # Expanding with only a minimum width, so it soaks up the row's
            # slack and lengthens as a neighbour expands while far siblings
            # squish — i.e. the arrows stretch. Transparent (no autofill)
            # so the parent-painted connector shows through.
            return _ConnectorCell()

        def add_slot(slot: QWidget) -> None:
            if self._slots:                       # connector before every
                cell = make_connector()           # slot except the first
                self._connectors.append(cell)
                lay.addWidget(cell)
            lay.addWidget(slot, 0, Qt.AlignVCenter)
            self._slots.append(slot)

        def add_card(stage_id: str) -> _StageCard:
            card = self._make_stage_card(stage_id)
            self._stage_cards[stage_id] = card
            if stage_id in _STAGE_TIPS:
                self._ui._explain(card, *_STAGE_TIPS[stage_id])
            return card

        # Input.
        in_card = add_card(STAGE_INPUT)
        add_slot(in_card)
        self._slot_for_stage[STAGE_INPUT] = in_card

        # Depth + Speed + Punch share one vertical slot — three parallel
        # sources that all merge in Combine.
        ds = QWidget()
        ds_lay = _vbox(0, 4)
        ds.setLayout(ds_lay)
        depth_card = add_card(STAGE_DEPTH)
        speed_card = add_card(STAGE_SPEED)
        punch_card = add_card(STAGE_PUNCH)
        # Inner cards follow the slot width (the slot is what animates),
        # so let them shrink to the rail width when the slot is squished.
        depth_card.setMinimumWidth(0)
        speed_card.setMinimumWidth(0)
        punch_card.setMinimumWidth(0)
        ds_lay.addWidget(depth_card)
        ds_lay.addWidget(speed_card)
        ds_lay.addWidget(punch_card)
        add_slot(ds)
        self._slot_for_stage[STAGE_DEPTH] = ds
        self._slot_for_stage[STAGE_SPEED] = ds
        self._slot_for_stage[STAGE_PUNCH] = ds
        self._ds_slot = ds

        for sid in (STAGE_COMBINE, STAGE_WAKE, STAGE_ENVELOPE,
                    STAGE_ZEROCUT, STAGE_OUTPUT):
            card = add_card(sid)
            add_slot(card)
            self._slot_for_stage[sid] = card

        host.set_slots(self._slots)
        # Input forks into Depth+Speed+Punch, and they join into Combine —
        # tell the host which slot holds the parallel cards so it draws
        # branch arrows.
        host.set_branch(self._slots.index(self._ds_slot),
                        [depth_card, speed_card, punch_card])
        # Split the row's spare width between the sliders and the arrows
        # instead of letting the arrows have all of it.
        self._claim_row_slack()
        # Establish every slot's width floor up front. _clear_slot_width
        # otherwise only runs when a collapse animation finishes, so a
        # strip that has never been expanded keeps the layout-derived
        # minimum — which is what pinned the Sources cluster at its full
        # width on first show.
        for slot in self._slots:
            self._clear_slot_width(slot)
        self._apply_connector_widths()

        # Wrap the host under a muted group-header legend so the strip
        # reads as three left-to-right clusters (Sources / Wake /
        # Shaping) between the Input and Output bookends. The legend is
        # decoupled from the accordion geometry — it never pins widths or
        # anchors connectors, so it can't perturb the animation.
        wrap = QWidget()
        wrap_lay = _vbox(0, 2)
        wrap.setLayout(wrap_lay)
        wrap_lay.addWidget(self._build_group_header_row())
        wrap_lay.addWidget(host)
        return wrap

    def _build_group_header_row(self) -> QWidget:
        """Muted section markers above the strip. The pipeline reads left
        to right as three clusters — Sources (Depth/Speed/Punch), Wake,
        and Shaping (Envelope, Zero cut) — with Input/Output as bookends.
        Purely a legend: evenly spread so the order is legible without
        pretending to pixel-align to the animating cards below."""
        row = QWidget()
        lay = _hbox(0, 0)
        row.setLayout(lay)
        # Leading gap roughly over the Input bookend.
        lay.addSpacing(_CARD_COLLAPSED_MIN)
        for text in ("Sources", "Wake", "Shaping"):
            lay.addStretch(1)
            lbl = QLabel(text.upper())
            lf = lbl.font()
            lf.setPointSize(max(7, lf.pointSize() - 1))
            lf.setBold(True)
            lbl.setFont(lf)
            lbl.setProperty("muted", "true")
            self._ui._repolish(lbl)
            lay.addWidget(lbl)
            lay.addStretch(1)
        return row

    def _make_stage_card(self, stage_id: str) -> _StageCard:
        """Build one accordion cell. Depth/Speed/Punch get a quick gain
        slider and Envelope a quick delay (ms) slider; the other (compact)
        stages stack their title over the output number and show the
        subtitle summary. Envelope also carries a texture summary line under
        its slider, and Wake its valve indicator. Clicking the card toggles
        its expansion via `_on_stage_clicked`."""
        is_slider = stage_id in (STAGE_DEPTH, STAGE_SPEED, STAGE_PUNCH,
                                 STAGE_ENVELOPE)
        card = _StageCard(
            stage_id, _STAGE_LABELS[stage_id],
            _STAGE_SHORT.get(stage_id, _STAGE_LABELS[stage_id][:4]),
            compact=not is_slider,
        )
        card.clicked.connect(self._on_stage_clicked)

        if stage_id in (STAGE_DEPTH, STAGE_SPEED, STAGE_PUNCH):
            # Quick gain control(s) on the collapsed card — Depth/Speed
            # default 1.0, Punch 0.0 (off). STAGE_* ids equal the config
            # keys, so the gain sync path writes the right nested field.
            #
            # Depth gets one slider; Speed and Punch get two, one per
            # stroke direction, because both are directional signals and
            # the balance between the halves is the thing you reach for
            # most often — burying it in the expanded editor would make
            # the common adjustment the slow one.
            chain = _read_chain(self._controller, self._device_name,
                                self._motor_idx, self._chain_idx)
            cfg = chain.get(stage_id, {}) if isinstance(chain, dict) else {}
            if not isinstance(cfg, dict):
                cfg = {}
            default_gain = 0.0 if stage_id == STAGE_PUNCH else 1.0
            try:
                seed_gain = float(cfg.get("gain", default_gain))
            except (TypeError, ValueError):
                seed_gain = default_gain

            directional = stage_id in (STAGE_SPEED, STAGE_PUNCH)
            if not directional:
                rows = ((stage_id, seed_gain, ""),)
            else:
                # Speed's outward half follows the inward gain when unset;
                # Punch's stays off. Same asymmetry the router applies.
                out_default = 0.0 if stage_id == STAGE_PUNCH else seed_gain
                try:
                    seed_out = float(cfg.get("gain_out", out_default))
                except (TypeError, ValueError):
                    seed_out = out_default
                rows = ((stage_id, seed_gain, "In"),
                        (stage_id + "|out", seed_out, "Out"))

            for sync_key, seed, row_label in rows:
                gain_ctrl = _GainControl(seed, label=row_label)
                gain_ctrl.gainChanged.connect(
                    lambda g, ck=sync_key: self._on_gain_from_slider(ck, g)
                )
                self._gain_sliders[sync_key] = gain_ctrl
                card.quick_layout.addWidget(gain_ctrl)
            card._wants_width = True
        elif stage_id == STAGE_ENVELOPE:
            chain = _read_chain(self._controller, self._device_name,
                                self._motor_idx, self._chain_idx)
            sm = chain.get("smoothing", {}) if isinstance(chain, dict) else {}
            if not isinstance(sm, dict):
                sm = {}
            try:
                seed = max(float(sm.get("rise_ms", 50.0)),
                           float(sm.get("fall_ms", 20.0)))
            except (TypeError, ValueError):
                seed = 50.0
            delay_ctrl = _DelayControl(seed)
            delay_ctrl.msChanged.connect(self._on_delay_from_slider)
            self._delay_control = delay_ctrl
            card.quick_layout.addWidget(delay_ctrl)
            # Texture summary line under the delay readout so the collapsed
            # Envelope card shows BOTH smoothing and texture at a glance.
            texture = QLabel(self._summary_for_stage(STAGE_ENVELOPE))
            texture.setAlignment(Qt.AlignHCenter)
            gf = texture.font()
            gf.setPointSize(max(7, gf.pointSize() - 1))
            texture.setFont(gf)
            texture.setProperty("muted", "true")
            self._ui._repolish(texture)
            card.quick_layout.addWidget(texture)
            self._stage_subtitles[STAGE_ENVELOPE] = texture
            # Texture on/off, right on the card: it's the half of Envelope
            # you A/B most while tuning, and it was two clicks away.
            card.quick_layout.addWidget(
                self._make_quick_toggle(
                    "Texture", ("texture", "enabled"),
                    bool(chain.get("texture", {}).get("enabled", False))
                    if isinstance(chain.get("texture"), dict) else False,
                    STAGE_ENVELOPE,
                )
            )
            card._wants_width = True
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
            self._add_compact_quick_control(stage_id, card)

        # Valve indicator — only on the Wake card. Animates open/closed;
        # complements the full ActivityMeter inside the expanded editor.
        if stage_id == STAGE_WAKE:
            valve = ValveIndicator()
            card.quick_layout.addWidget(valve)
            self._stage_valve = valve

        return card

    # ----- Collapsed-card quick controls --------------------------
    #
    # The rule: anything you reach for mid-session lives on the collapsed
    # card; the expanded card keeps the complete option set and the
    # graph. Discrete values get a toggle or a segmented picker (cheap in
    # width); continuous ones get a short slider, and those cards claim
    # the row's surplus via _slot_wants_width so the track grows on a
    # real window instead of the connectors eating the space.

    def _make_cycle_button(self, options: Tuple[str, ...], current: str,
                           on_change: Callable[[str], None],
                           labels: Optional[Dict[str, str]] = None
                           ) -> QPushButton:
        """One button that steps to the next option on each click, showing
        the current one as its text.

        For a small set of discrete choices on a collapsed card. A
        segmented control needs a cell per option, which on a strip that
        fits seven slots across one row means either a card several times
        its neighbours' width or buttons squeezed until the stylesheet's
        own padding clips their labels. One button costs one cell and
        stays legible, at the price of up to N-1 clicks to reach a
        specific value — fine for three options, and the expanded editor
        still offers them all at once.

        Sizing is derived from the font rather than guessed. The stock
        QPushButton padding (6px 14px) is most of a card on a seven-slot
        row, so this button carries objectName "stageCycleButton", whose
        QSS trims it to 1px 4px — the label then owns nearly the whole
        button and reaches the edges on a narrow window instead of being
        clipped early. Height is a MINIMUM computed from the font's own
        line height, never a fixed value: pinning it is what cropped the
        descenders regardless of width."""
        show = labels or {}
        opts = tuple(options)
        idx = {"i": opts.index(current) if current in opts else 0}

        btn = QPushButton(show.get(opts[idx["i"]], opts[idx["i"]]))
        btn.setObjectName("stageCycleButton")
        bf = btn.font()
        bf.setPointSize(max(7, bf.pointSize() - 1))
        btn.setFont(bf)
        btn.setProperty("role", "segActive")
        self._ui._repolish(btn)
        # Size from Qt's own sizeHint per label rather than from font
        # metrics plus a guessed inset. sizeHint already accounts for the
        # active stylesheet's padding and border radius, which hand
        # arithmetic does not — getting that wrong is what clipped the
        # label's sides and its descenders. Taking the max over every
        # option also stops the button resizing as it cycles.
        natural_w = natural_h = 0
        for opt in opts:
            btn.setText(show.get(opt, opt))
            hint = btn.sizeHint()
            natural_w = max(natural_w, hint.width())
            natural_h = max(natural_h, hint.height())
        btn.setText(show.get(opts[idx["i"]], opts[idx["i"]]))
        btn.setMinimumWidth(natural_w)
        btn.setMinimumHeight(natural_h)
        btn.setCursor(Qt.PointingHandCursor)

        def advance() -> None:
            idx["i"] = (idx["i"] + 1) % len(opts)
            value = opts[idx["i"]]
            btn.setText(show.get(value, value))
            on_change(value)

        btn.clicked.connect(advance)
        return btn

    def _make_quick_toggle(self, label: str, path: Tuple[str, str],
                           checked: bool, stage_id: str) -> QWidget:
        """A small on/off switch that writes one boolean chain field and
        refreshes that stage's subtitle."""
        tog = ToggleSwitch(label)
        tog.setChecked(bool(checked))
        tf = tog.font()
        tf.setPointSize(max(7, tf.pointSize() - 1))
        tog.setFont(tf)

        def on_toggled(v: bool) -> None:
            _update_chain_field(
                self._controller, self._device_name, self._motor_idx,
                self._chain_idx, path, bool(v),
            )
            self._refresh_subtitle(stage_id)

        tog.toggled.connect(on_toggled)
        self._quick_toggles[stage_id] = tog
        return tog

    def _add_compact_quick_control(self, stage_id: str,
                                   card: "_StageCard") -> None:
        """Attach the collapsed-card control for a compact stage.

        Input is deliberately left alone: its setting is a zone/address
        mapping, which has no meaningful one-widget form."""
        chain = _read_chain(self._controller, self._device_name,
                            self._motor_idx, self._chain_idx)

        if stage_id == STAGE_COMBINE:
            current = str(chain.get("combine", "max"))
            if current not in _COMBINE_OPS:
                current = "max"
            # One cycling button rather than three cells: three options do
            # not justify tripling the widest card on the row, and the
            # button doubles as the readout.
            btn = self._make_cycle_button(
                _COMBINE_OPS, current,
                lambda op: _update_chain_field(
                    self._controller, self._device_name, self._motor_idx,
                    self._chain_idx, ("combine",), op,
                ),
                labels=_COMBINE_LABELS,
            )
            self._combine_cycle = btn
            card.quick_layout.addWidget(btn, 0, Qt.AlignHCenter)
            # The button IS the readout — a subtitle would repeat it.
            sub = self._stage_subtitles.pop(STAGE_COMBINE, None)
            if sub is not None:
                sub.setParent(None)
                sub.deleteLater()
            return

        if stage_id == STAGE_ZEROCUT:
            zc = chain.get("zerocut", {}) if isinstance(chain, dict) else {}
            if not isinstance(zc, dict):
                zc = {}
            card.quick_layout.addWidget(self._make_quick_toggle(
                "Cut", ("zerocut", "enabled"),
                bool(zc.get("enabled", False)), STAGE_ZEROCUT,
            ))
            return

        if stage_id == STAGE_WAKE:
            # Mode-dependent: Activity tunes a 0..1 threshold, Strokes a
            # thrust count. One control cannot be both, so the card
            # rebuilds this when the mode changes (see _refresh_subtitle).
            self._rebuild_wake_quick(card)
            card._wants_width = True
            return

        if stage_id == STAGE_OUTPUT:
            gain, _lo, _hi = _get_output_stage(
                self._controller, self._device_name, self._motor_idx,
                self._chain_idx,
            )
            ctrl = _ValueControl(gain, 0.0, OUTPUT_GAIN_MAX,
                                 fmt="×{:.2f}", steps=200)
            ctrl.valueChanged.connect(
                lambda v: (
                    _set_output_field(
                        self._controller, self._device_name, self._motor_idx,
                        self._chain_idx, "gain", float(v)),
                    self._refresh_subtitle(STAGE_OUTPUT),
                )
            )
            self._output_gain_quick = ctrl
            card.quick_layout.addWidget(ctrl)
            card._wants_width = True
            return

    def _rebuild_wake_quick(self, card: "_StageCard") -> None:
        """(Re)build Wake's collapsed control for the current mode."""
        old = self._wake_quick
        if old is not None:
            try:
                card.quick_layout.removeWidget(old)
                old.setParent(None)
                old.deleteLater()
            except RuntimeError:
                pass
            self._wake_quick = None
        chain = _read_chain(self._controller, self._device_name,
                            self._motor_idx, self._chain_idx)
        wake = _read_wake_cfg(chain)
        if str(wake.get("mode", "activity")) == "strokes":
            try:
                seed = float(wake.get("thrusts", 3))
            except (TypeError, ValueError):
                seed = 3.0
            ctrl = _ValueControl(seed, 1.0, 10.0, fmt="{:.0f}×", steps=9)
            field = "thrusts"
            coerce = lambda v: int(round(v))            # noqa: E731
        else:
            try:
                seed = float(wake.get("wake_threshold", 0.05))
            except (TypeError, ValueError):
                seed = 0.05
            ctrl = _ValueControl(seed, 0.0, 1.0, fmt="{:.2f}", steps=100)
            field = "wake_threshold"
            coerce = float
        ctrl.valueChanged.connect(
            lambda v, f=field, c=coerce: (
                _update_wake_field(
                    self._controller, self._device_name, self._motor_idx,
                    self._chain_idx, f, c(v)),
                self._refresh_subtitle(STAGE_WAKE),
            )
        )
        self._wake_quick = ctrl
        if old is None:
            # First build — the valve indicator is appended after this
            # returns, so plain append lands us above it.
            card.quick_layout.addWidget(ctrl)
        else:
            # Rebuild (mode changed) — keep the valve last.
            card.quick_layout.insertWidget(
                max(0, card.quick_layout.count() - 1), ctrl)

    def _refresh_subtitle(self, stage_id: str) -> None:
        """Re-render one stage's subtitle after a quick-control edit."""
        label = self._stage_subtitles.get(stage_id)
        if label is None:
            return
        try:
            label.setText(self._summary_for_stage(stage_id) or " ")
        except RuntimeError:
            self._stage_subtitles.pop(stage_id, None)

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
        if stage_id == STAGE_PUNCH:
            pc = chain.get("punch", {}) if isinstance(chain, dict) else {}
            if not isinstance(pc, dict):
                pc = {}
            try:
                gain = float(pc.get("gain", 0.0))
            except (TypeError, ValueError):
                gain = 0.0
            if gain <= 0.0:
                return "off"
            try:
                decay = float(pc.get("decay_ms", 120.0))
            except (TypeError, ValueError):
                decay = 120.0
            return f"×{gain:.2g} · {decay:.0f} ms"
        if stage_id == STAGE_COMBINE:
            return str(chain.get("combine", "max"))
        if stage_id == STAGE_WAKE:
            # Summary reflects the active wake mode.
            wc = _read_wake_cfg(chain)
            if not wc.get("enabled", False):
                return "off"
            mode = str(wc.get("mode", "activity"))
            if mode == "strokes":
                try:
                    thrusts = float(wc.get("thrusts", 3))
                except (TypeError, ValueError):
                    thrusts = 3.0
                try:
                    window = float(wc.get("window_s", 6.0))
                except (TypeError, ValueError):
                    window = 6.0
                return f"{thrusts:.0f}× in {window:.0f}s"
            try:
                thr = float(wc.get("wake_threshold", 0.05))
            except (TypeError, ValueError):
                thr = 0.05
            return f"Activity · wake {thr:.2g}"
        if stage_id == STAGE_ENVELOPE:
            # Slider card: the delay readout already shows smoothing, so
            # this line carries only the Texture (wobble) half.
            tc = chain.get("texture", {}) if isinstance(chain, dict) else {}
            if not isinstance(tc, dict) or not tc.get("enabled", False):
                return "texture off"
            try:
                amount = float(tc.get("amount", 0.25))
            except (TypeError, ValueError):
                amount = 0.25
            try:
                rate = float(tc.get("rate_hz", 2.0))
            except (TypeError, ValueError):
                rate = 2.0
            return f"texture {amount * 100.0:.0f}% @ {rate:.1f}Hz"
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
            # A narrowed band or a trimmed gain says so — an unexplained
            # quiet toy is worth more than three characters of motor kind.
            # The band wins the slot when both are set: it is the one that
            # changes what the toy can reach at all. Untouched outputs keep
            # the kind subtitle: linear is special-cased, everything else
            # reads from the shared _KIND_DISPLAY table, with
            # _DEFAULT_KIND_DISPLAY ("vib") for any kind the table
            # doesn't know yet.
            gain, out_min, out_max = _get_output_stage(
                self._controller, self._device_name, self._motor_idx,
                self._chain_idx,
            )
            if out_min > 0.005 or out_max < 0.995:
                return f"{out_min * 100:.0f}–{out_max * 100:.0f}%"
            if abs(gain - 1.0) >= 0.005:
                return f"×{gain:.2f}"
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

        self._apply_strip_mode()

        self._accordion_anim.stop()
        self._accordion_anim.start()

    def _apply_strip_mode(self) -> None:
        """Vertically centre every slot, in both the all-collapsed and the
        expanded strip.

        Expanding a stage used to switch the row to top alignment, on the
        theory that a tall editor would otherwise drag the arrows down
        with it. What actually happened is that the rails stayed pinned to
        the top while the parallel cards spread down the row, so the
        fork/join legs sprayed across the strip at unrelated heights. One
        centre line keeps every connector meaningful in both states, and
        the tall card simply grows around it."""
        if self._strip_lay is not None:
            for slot in self._slots:
                try:
                    self._strip_lay.setAlignment(slot, Qt.AlignVCenter)
                except (RuntimeError, TypeError):
                    pass
        if self._strip_host is not None:
            try:
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
        naturally again, leaving every slot the same explicit floor.

        The floor has to be explicit — including on the Depth/Speed/Punch
        container, which used to be handed 0 on the theory that it should
        "defer to its inner cards' own minimums". It does, and that was
        the bug: for a widget with a layout, an explicit minimum of 0
        makes Qt fall back to the layout-derived minimumSizeHint, which
        for three stacked slider cards is ~208px. So the Sources cluster
        was the one slot in the row that could not shrink, while every
        other slot compressed to _CARD_COLLAPSED_MIN and clipped its
        contents as usual."""
        try:
            slot.setMinimumWidth(_CARD_COLLAPSED_MIN)
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

    def _apply_connector_widths(self) -> None:
        """Size the connector gaps by explicit priority: cards first.

        Neither stretch factors nor size preferences can express "the gaps
        yield before the cards do". Stretch hands the gaps a proportional
        share of the surplus even while the cards sit at their floor;
        preference has Qt shrink everything proportionally from its hint,
        so the gaps keep room the cards need. Both were tried.

        The rule instead: work out what the cards would like, and give the
        gaps only what is left over, bounded. Under pressure that lands at
        `_CONNECTOR_GAP` — an arrowhead and two stubs, which the elbow
        routing is designed to survive — and on a roomy window it reaches
        `_CONNECTOR_GAP_MAX` and stops, so the rest still goes to the
        cards.

        Only while everything is collapsed. With a stage expanded the
        widths are pinned per frame by `_compute_target_widths` and the
        gaps are deliberately elastic, so the arrows stretch as the card
        grows; fixing them here would fight that."""
        if not self._connectors or self._strip_host is None:
            return
        try:
            host_w = self._strip_host.contentsRect().width()
        except RuntimeError:
            return
        if host_w <= 0:
            return
        if self._active_stage is not None:
            # Expanded: hand the cells back their elastic range.
            for cell in self._connectors:
                try:
                    cell.setMinimumWidth(_CONNECTOR_GAP)
                    cell.setMaximumWidth(_QWIDGETSIZE_MAX)
                except RuntimeError:
                    continue
            return
        wanted = sum(self._slot_collapsed_width(s) for s in self._slots)
        spare = host_w - wanted
        gap = int(max(_CONNECTOR_GAP,
                      min(_CONNECTOR_GAP_MAX, spare / len(self._connectors))))
        for cell in self._connectors:
            try:
                cell.setFixedWidth(gap)
            except RuntimeError:
                continue

    def _claim_row_slack(self) -> None:
        """Let the slider-bearing slots compete with the connectors for
        the row's spare width.

        Called once after the strip is built. The connector spacers are
        Expanding while the card slots were Preferred, so Qt handed every
        surplus pixel to the gaps: on a wide window that is six stretches
        of empty arrow while each slider stays at its minimum. Marking the
        growable slots Expanding with a larger stretch share splits the
        surplus the other way round — the tracks get longer, the arrows
        stay readable, and a narrow window still collapses back to the
        natural widths because these are stretches, not minimums."""
        lay = self._strip_lay
        if lay is None:
            return
        for i in range(lay.count()):
            item = lay.itemAt(i)
            w = item.widget() if item is not None else None
            if w is None:
                continue
            if w in self._slots:
                if self._slot_wants_width(w):
                    try:
                        pol = w.sizePolicy()
                        pol.setHorizontalPolicy(QSizePolicy.Expanding)
                        w.setSizePolicy(pol)
                    except RuntimeError:
                        continue
                    lay.setStretch(i, _SLOT_STRETCH_GROWABLE)
            else:
                # A connector cell.
                lay.setStretch(i, _SLOT_STRETCH_CONNECTOR)

    def _slot_wants_width(self, slot: QWidget) -> bool:
        """True when a slot holds a card whose quick control gets better
        with more room — a slider. Toggles and segmented pickers are
        fixed-size, so handing them width would just pad them."""
        for stage_id, card in self._stage_cards.items():
            try:
                if (getattr(card, "_wants_width", False)
                        and self._slot_for_stage.get(stage_id) is slot):
                    return True
            except RuntimeError:
                continue
        return False

    def _compute_target_widths(self, target: Optional[str]) -> Dict[QWidget, int]:
        """Target width per slot. All-collapsed → each slot's natural
        width (the pins are released right after, so the settled row
        redistributes by stretch — see `_claim_row_slack`); one expanded →
        that slot takes the row minus thin rails for the others (clamped
        so it never underflows the editor)."""
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

    #: Sync keys are "<stage>" for the inward gain and "<stage>|out" for
    #: the outward one, so Speed and Punch can hold two independent
    #: slider/spinbox pairs in the same two dicts Depth uses for its one.
    @staticmethod
    def _gain_field(sync_key: str) -> Tuple[str, str]:
        """Split a sync key into the (config section, field) it writes."""
        if sync_key.endswith("|out"):
            return sync_key[:-4], "gain_out"
        return sync_key, "gain"

    def _on_gain_from_slider(self, sync_key: str, gain: float) -> None:
        """Quick-slider edit: persist + mirror onto the precise spinbox."""
        section, field = self._gain_field(sync_key)
        _update_chain_field(
            self._controller, self._device_name, self._motor_idx,
            self._chain_idx, (section, field), float(gain),
        )
        spin = self._gain_spins.get(sync_key)
        if spin is not None:
            try:
                spin.blockSignals(True)
                spin.setValue(float(gain))
                spin.blockSignals(False)
            except RuntimeError:
                self._gain_spins.pop(sync_key, None)

    def _on_gain_from_spin(self, sync_key: str, gain: float) -> None:
        """Precise-spinbox edit: persist + mirror onto the quick slider."""
        section, field = self._gain_field(sync_key)
        _update_chain_field(
            self._controller, self._device_name, self._motor_idx,
            self._chain_idx, (section, field), float(gain),
        )
        slider = self._gain_sliders.get(sync_key)
        if slider is not None:
            try:
                slider.set_gain(float(gain))
            except RuntimeError:
                self._gain_sliders.pop(sync_key, None)

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

        # One entry per connector, in slot order: Input→Sources (fork),
        # Sources→Combine (join), Combine→Wake, Wake→Envelope,
        # Envelope→Zero cut, Zero cut→Output.
        levels = [
            g(STAGE_INPUT),
            max(g(STAGE_DEPTH), g(STAGE_SPEED), g(STAGE_PUNCH)),
            g(STAGE_COMBINE),
            g(STAGE_WAKE),
            g(STAGE_ENVELOPE),
            g(STAGE_ZEROCUT),
        ]
        # Per-channel levels tint the three join arrows (Depth→Combine,
        # Speed→Combine, Punch→Combine) independently.
        branch_levels = [g(STAGE_DEPTH), g(STAGE_SPEED), g(STAGE_PUNCH)]
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
        elif stage_id == STAGE_PUNCH:
            inner = self._build_punch_editor()
        elif stage_id == STAGE_COMBINE:
            inner = self._build_combine_editor()
        elif stage_id == STAGE_WAKE:
            inner = self._build_wake_editor()
        elif stage_id == STAGE_ENVELOPE:
            inner = self._build_envelope_editor()
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
        Wake stage card (Cut 7h)."""
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
        # Activity meter (Wake editor, activity mode, when expanded). The
        # meter trace is `wake_meter`; `wake_open` flips its open/closed
        # colour. In strokes mode the meter is hidden, so an update here is
        # a harmless no-op paint.
        if self._activity_meter is not None:
            try:
                self._activity_meter.set_value(
                    float(payload.get("wake_meter", 0.0))
                )
                self._activity_meter.set_open(
                    bool(payload.get("wake_open", False))
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
        # Valve indicator on the Wake stage card — slides the bar
        # forward on open, back on close. Animation handles the
        # interpolation; we just set the target.
        if self._stage_valve is not None:
            try:
                self._stage_valve.set_open(
                    bool(payload.get("wake_open", False))
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
        chain_type = _get_chain_type(
            self._controller, self._device_name, self._motor_idx,
            self._chain_idx)

        # What kind of contact this chain is for. Touch and penetration
        # want different tuning, which is why they get a chain each --
        # this is where you say which one you are looking at.
        type_row = _hbox(0, 8)
        type_row.addWidget(QLabel("Driven by:"))
        type_row.addWidget(self._make_segmented(
            tuple(CHAIN_TYPE_LABELS[t] for t in CHAIN_TYPES),
            CHAIN_TYPE_LABELS.get(chain_type, "Custom"),
            lambda text: self._on_chain_type_changed(text),
        ))
        self._ui._explain(type_row,
            "Chain type",
            "Which contact feeds this chain. <b>Penetration</b> and "
            "<b>Touch</b> are different sensations that want different "
            "tuning, so a motor carries one chain for each and they are "
            "dialled in apart — the type decides which reaches this "
            "chain, so you never have to keep two filter toggles "
            "consistent by hand.<br><br>"
            "<b>Custom</b> hands the Touch/Penetration toggles back for "
            "a chain that should react to both, or to something you "
            "wire up yourself.<br><br>"
            "Zones and Self/Others below are set <i>per chain</i>: until "
            "you change them here they follow the motor's, so a chain "
            "you have not customised behaves exactly as the motor did."
        )
        type_row.addStretch(1)
        lay.addLayout(type_row)

        # Custom chains get a NAME. "Penetration" and "Touch" name
        # themselves; a custom chain is only findable in a folded stack
        # of six if the user can call it something ("Tail grab",
        # "Headpat"). Typed chains don't get the field — their type IS
        # their name, and a stale label shadowing it would mislead.
        if chain_type == "custom":
            name_row = _hbox(0, 8)
            name_row.addWidget(QLabel("Name:"))
            chain_cfg = _read_chain(self._controller, self._device_name,
                                    self._motor_idx, self._chain_idx)
            current_name = str(chain_cfg.get("name") or "") \
                if isinstance(chain_cfg, dict) else ""
            name_edit = QLineEdit(current_name)
            name_edit.setPlaceholderText(f"Chain {self._chain_idx + 1}")
            name_edit.setMaxLength(24)
            name_edit.setFixedWidth(160)
            name_edit.editingFinished.connect(
                lambda ed=name_edit: _update_chain_field(
                    self._controller, self._device_name, self._motor_idx,
                    self._chain_idx, ("name",), ed.text().strip(),
                )
            )
            name_row.addWidget(name_edit)
            name_row.addStretch(1)
            lay.addLayout(name_row)

        # Sidechain duck -- everything except a Penetration chain can opt
        # in (a penetration chain is the SOURCE, the router ignores the
        # flag on it). It sits on the Input stage because it is a
        # statement about when this chain's input counts, not about how
        # the signal is shaped.
        if chain_type != "penetration":
            chain_cfg = _read_chain(self._controller, self._device_name,
                                    self._motor_idx, self._chain_idx)
            duck_cfg = chain_cfg.get("duck") if isinstance(chain_cfg, dict) else None
            if not isinstance(duck_cfg, dict):
                duck_cfg = {}
            duck_row = _hbox(0, 8)
            duck_cb = ToggleSwitch("Duck while penetrating")
            duck_cb.setChecked(bool(duck_cfg.get("enabled", False)))
            duck_cb.toggled.connect(
                lambda v: _update_chain_field(
                    self._controller, self._device_name, self._motor_idx,
                    self._chain_idx, ("duck", "enabled"), bool(v),
                )
            )
            duck_row.addWidget(duck_cb)
            self._ui._explain(duck_row,
                "Duck while penetrating",
                "While the <b>Penetration</b> chain on this motor has "
                "something inside, this chain fades out; once the pen "
                "leaves it fades back over <b>Release</b>.<br><br>"
                "A hand at the same orifice mid-stroke is nearly always "
                "incidental -- gripping, bracing -- and under a max merge "
                "its proximity becomes a floor under every stroke trough, "
                "turning a rhythm into a rhythm-on-a-hum. Ducking keeps "
                "penetration clean and, as a side effect, means a touch "
                "value that freezes during penetration never reaches the "
                "toy at all.<br><br>"
                "OSC Goes Brrr does <i>not</i> do this -- it takes the "
                "plain max of every source -- so leave it off for parity, "
                "on for a cleaner stroke. Try both; it is a taste call. "
                "The simulator never ducks, so tuning a Touch chain "
                "under simulation shows the whole chain."
            )
            duck_row.addSpacing(8)
            duck_row.addWidget(QLabel("Release:"))
            duck_spin = _NoTrackSpin()
            duck_spin.setRange(0.0, 3000.0)
            duck_spin.setDecimals(0)
            duck_spin.setSingleStep(50.0)
            duck_spin.setSuffix(" ms")
            try:
                duck_spin.setValue(float(duck_cfg.get("release_ms", 400.0)))
            except (TypeError, ValueError):
                duck_spin.setValue(400.0)
            duck_spin.valueChanged.connect(
                lambda v: _update_chain_field(
                    self._controller, self._device_name, self._motor_idx,
                    self._chain_idx, ("duck", "release_ms"), float(v),
                )
            )
            duck_row.addWidget(duck_spin)
            duck_row.addStretch(1)
            lay.addLayout(duck_row)

        # Simulated input: listen to the page-level simulator (▶ Play in
        # the top bar) THROUGH this chain's type. Stored as the motor's
        # custom addresses OGP/Sim/Pen and/or OGP/Sim/Touch, which the
        # router only hands to chains whose filters accept that kind of
        # contact -- so the same Play drives a Penetration chain as a
        # penetration and a Touch chain as a touch.
        sim_row = _hbox(0, 8)
        sim_cb = ToggleSwitch("Simulated input")
        sim_cb.setChecked(_motor_listens_to_sim(
            self._controller, self._device_name, self._motor_idx, chain_type))
        sim_cb.toggled.connect(
            lambda v, t=chain_type: self._on_sim_input_toggled(bool(v), t))
        sim_row.addWidget(sim_cb)
        self._ui._explain(sim_row,
            "Simulated input",
            "Feed this chain from the <b>input simulator</b> in the page's "
            "top bar. Press <b>▶ Play</b> up there and this chain hears the "
            "wave -- as a <i>penetration</i> on a Penetration chain, as a "
            "<i>touch</i> on a Touch chain (a Custom chain gets whichever "
            "its filters allow). Chains without this on keep hearing "
            "VRChat. The simulator is a motor-level input, so its "
            "addresses (<b>OGP/Sim/Pen</b>, <b>OGP/Sim/Touch</b>) show up "
            "in the Listening To column and in the OSC Inspector while "
            "it plays."
        )
        sim_row.addStretch(1)
        lay.addLayout(sim_row)

        lay.addWidget(self._make_hrule())

        listen_col = self._ui._build_listening_to_column(
            self._device_name, self._motor_idx, osc_addresses or {},
            chain_idx=self._chain_idx, chain_type=chain_type,
        )
        lay.addWidget(listen_col)
        return host

    def _on_sim_input_toggled(self, on: bool, chain_type: str) -> None:
        """Persist the simulator address(es) for this chain's type on the
        motor, then rebuild the Input editor (deferred: the toggle that
        sent this signal lives in it) so the Listening To chips show it."""
        _set_motor_sim_listening(self._controller, self._device_name,
                                 self._motor_idx, chain_type, on)

        def _refresh() -> None:
            try:
                card = self._stage_cards.get(STAGE_INPUT)
                if card is not None and card.editor_built():
                    card.reset_editor()
                    self._stage_graphs.pop(STAGE_INPUT, None)
            except RuntimeError:
                pass
        QTimer.singleShot(0, _refresh)

    def _on_chain_type_changed(self, text: str) -> None:
        """Persist a new chain type and rebuild — the type changes what
        the Input panel offers (a typed chain hides the Touch/Penetration
        toggles it would otherwise contradict) and what the card is
        called."""
        value = next((t for t in CHAIN_TYPES
                      if CHAIN_TYPE_LABELS[t] == text), "custom")
        _update_chain_field(
            self._controller, self._device_name, self._motor_idx,
            self._chain_idx, ("type",), value,
        )
        # The frame follows the new type's hue.
        self.setProperty("hue", _theme.CHAIN_TYPE_HUES.get(value, "grey"))
        self.style().unpolish(self)
        self.style().polish(self)
        card = self._stage_cards.get(STAGE_INPUT)
        if card is not None and card.editor_built():
            card.reset_editor()
            self._stage_graphs.pop(STAGE_INPUT, None)
            if self._active_stage == STAGE_INPUT:
                self._animate_to(STAGE_INPUT)

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

        try:
            gain_in = float(cfg.get("gain", 1.0))
        except (TypeError, ValueError):
            gain_in = 1.0

        if channel_key != "speed":
            # Depth — one gain, unchanged.
            gain_row = self._make_gain_spin_row(channel_key, gain_in)
            self._ui._explain(gain_row,
                "Gain",
                "Multiplies this channel after the curve. 1.0 = unchanged, "
                "0 = silences the channel entirely, up to 2.0 = boost "
                "(clamped to 1.0 downstream). Same knob as the slider on "
                "the collapsed card."
            )
            lay.addLayout(gain_row)
        else:
            # Speed is directional — a gain per stroke direction over one
            # shared curve and fall-off below. An absent `gain_out` follows
            # `gain`, matching the router, so a chain tuned before the
            # split opens here looking symmetric because it *is*.
            try:
                gain_out = float(cfg.get("gain_out", gain_in))
            except (TypeError, ValueError):
                gain_out = gain_in

            lay.addWidget(self._make_subsection_header(
                "In — going deeper",
                "How loud movement is while depth is increasing. "
                "<b>Gain</b> multiplies this direction after the curve.",
            ))
            lay.addLayout(self._make_gain_spin_row(channel_key, gain_in))

            lay.addWidget(self._make_hrule())

            lay.addWidget(self._make_subsection_header(
                "Out — pulling back",
                "The same for movement while depth is decreasing. Set it "
                "below In for a rig that should push more than it pulls, "
                "or to 0.00 to react to the thrust only.",
            ))
            lay.addLayout(self._make_gain_spin_row(
                channel_key + "|out", gain_out))

            lay.addWidget(self._make_hrule())
            lay.addWidget(self._make_subsection_header(
                "Both directions",
                "The curve and fall-off below are shared — they shape "
                "<i>how</i> speed responds, not which way you moved.",
            ))

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
        self._ui._explain(curve_row,
            "Curve",
            "Reshapes the 0–1 signal before the gain. <b>linear</b>: "
            "unchanged. <b>power</b>: Param &lt;1 boosts light contact, "
            "&gt;1 suppresses it. <b>s_curve</b>: eases both ends and "
            "steepens the middle; Param is the iteration count — higher "
            "= sharper switch-like response."
        )
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
            self._ui._explain(fo_row,
                "Fall-off",
                "How quickly Speed dies down once movement stops — the "
                "detector holds its peak and decays with this time "
                "constant. Lower = snappier cut-off, higher = lingering "
                "tail."
            )
            fo_row.addStretch(1)
            lay.addLayout(fo_row)
        return host

    def _build_punch_editor(self) -> QWidget:
        """Punch — attack-transient gain + decay. Gain 0 = off."""
        host = QFrame()
        host.setObjectName("stageEditor")
        lay = _vbox(10, 8)
        host.setLayout(lay)

        hdr_row = _hbox(0, 6)
        header = QLabel("Punch")
        hf = header.font(); hf.setBold(True)
        header.setFont(hf)
        hdr_row.addWidget(header)
        self._ui._explain(hdr_row,
            *_STAGE_TIPS[STAGE_PUNCH]
        )
        hdr_row.addStretch(1)
        lay.addLayout(hdr_row)

        chain = _read_chain(self._controller, self._device_name,
                            self._motor_idx, self._chain_idx)
        pc_cfg = chain.get("punch", {}) if isinstance(chain, dict) else {}
        if not isinstance(pc_cfg, dict):
            pc_cfg = {}  # hand-edited profile — build from defaults
        try:
            pc_gain = float(pc_cfg.get("gain", 0.0))
        except (TypeError, ValueError):
            pc_gain = 0.0
        try:
            pc_decay = float(pc_cfg.get("decay_ms", 120.0))
        except (TypeError, ValueError):
            pc_decay = 120.0
        try:
            pc_gain_out = float(pc_cfg.get("gain_out", 0.0))
        except (TypeError, ValueError):
            pc_gain_out = 0.0

        # Two gains, one per stroke direction. Both 0 disables the stage
        # entirely. Two-way sync with the pair of quick sliders on the
        # collapsed card (same fields, same sync path as Depth/Speed).
        lay.addWidget(self._make_subsection_header(
            "In — the thrust",
            "Fires when depth rises fast. <b>Gain</b> scales the hit; "
            "0.00 mutes this direction.",
        ))
        lay.addLayout(self._make_gain_spin_row("punch", pc_gain))

        lay.addWidget(self._make_hrule())

        lay.addWidget(self._make_subsection_header(
            "Out — the pull",
            "Fires when depth falls fast. Off by default — raise it for "
            "a rig that should also react to the withdrawal.",
        ))
        lay.addLayout(self._make_gain_spin_row("punch|out", pc_gain_out))

        lay.addWidget(self._make_hrule())

        # Decay: how long the hit takes to ring out.
        dc_row = _hbox(0, 8)
        dc_row.addWidget(QLabel("Decay (ms):"))
        dc_spin = _NoTrackSpin()
        dc_spin.setRange(30.0, 1000.0)
        dc_spin.setSingleStep(10.0)
        dc_spin.setDecimals(0)
        dc_spin.setValue(pc_decay)
        dc_spin.valueChanged.connect(
            lambda v: _update_chain_field(
                self._controller, self._device_name, self._motor_idx, self._chain_idx,
                ("punch", "decay_ms"), float(v),
            )
        )
        dc_row.addWidget(dc_spin)
        dc_row.addStretch(1)
        lay.addLayout(dc_row)

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
        self._ui._explain(hdr_row,
            *_STAGE_TIPS[STAGE_COMBINE]
        )
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
        self._ui._explain(hdr_row,
            *_STAGE_TIPS[STAGE_ZEROCUT]
        )
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

    def _build_wake_editor(self) -> QWidget:
        """Wake — the merged activity gate. One stage, two interchangeable
        ways to gate (chosen by the mode toggle):
          * Activity — an analog meter charges with sustained movement and
            opens above Wake threshold, sleeping after motion stops (the
            old Gate stage).
          * Strokes — the sleep gate: silent until N full strokes land in
            the window, disarms after quiet (the old Arming stage). An
            accidental brush can't wake it; this is what makes 🌙 Sleep
            safe.
        Every write goes through _update_wake_field; initial values are
        seeded via _read_wake_cfg (canonical defaults backfilled)."""
        host = QFrame()
        host.setObjectName("stageEditor")
        lay = _vbox(10, 8)
        host.setLayout(lay)

        def _f(value, default):
            try:
                return float(value)
            except (TypeError, ValueError):
                return default

        hdr_row = _hbox(0, 6)
        header = QLabel("Wake")
        hf = header.font(); hf.setBold(True)
        header.setFont(hf)
        hdr_row.addWidget(header)
        self._ui._explain(hdr_row,
            *_STAGE_TIPS[STAGE_WAKE]
        )
        hdr_row.addStretch(1)
        lay.addLayout(hdr_row)

        wake_cfg = _read_wake_cfg(_read_chain(
            self._controller, self._device_name, self._motor_idx,
            self._chain_idx))
        mode = str(wake_cfg.get("mode", "activity"))
        if mode not in ("activity", "strokes"):
            mode = "activity"

        # Enable toggle.
        enable_cb = ToggleSwitch("Enable")
        enable_cb.setChecked(bool(wake_cfg.get("enabled", False)))
        enable_cb.toggled.connect(
            lambda v: _update_wake_field(
                self._controller, self._device_name, self._motor_idx,
                self._chain_idx, "enabled", bool(v),
            )
        )
        lay.addWidget(enable_cb)

        # The two param sections — built below, shown/hidden by mode.
        # Declared up front so the mode toggle's closure can flip them.
        activity_frame = QFrame()
        activity_frame.setObjectName("stageEditor")
        act_lay = _vbox(0, 8)
        activity_frame.setLayout(act_lay)
        strokes_frame = QFrame()
        strokes_frame.setObjectName("stageEditor")
        str_lay = _vbox(0, 8)
        strokes_frame.setLayout(str_lay)

        # Mode toggle: Activity / Strokes.
        mode_row = _hbox(0, 8)
        mode_row.addWidget(QLabel("Mode:"))

        def on_mode(val: str) -> None:
            m = ("strokes" if str(val).lower().startswith("stroke")
                 else "activity")
            _update_wake_field(
                self._controller, self._device_name, self._motor_idx,
                self._chain_idx, "mode", m,
            )
            activity_frame.setVisible(m == "activity")
            strokes_frame.setVisible(m == "strokes")
        mode_seg = self._make_segmented(
            ("Activity", "Strokes"),
            "Strokes" if mode == "strokes" else "Activity",
            on_mode,
        )
        mode_row.addWidget(mode_seg)
        mode_row.addStretch(1)
        lay.addLayout(mode_row)

        # ---- Activity params (the old Gate) ----
        # Source: what charges the activity meter. Depth / Speed / Both
        # (depth × speed); Punch is deliberately not on the menu — it
        # exaggerates tiny movements, which made the gate hair-triggered.
        source = str(wake_cfg.get("source", "both")).lower()
        if source not in ("depth", "speed", "both"):
            source = "both"
        _src_label = {"depth": "Depth", "speed": "Speed", "both": "Both"}
        _src_value = {"Depth": "depth", "Speed": "speed", "Both": "both"}
        src_row = _hbox(0, 8)
        src_row.addWidget(QLabel("Source:"))
        src_seg = self._make_segmented(
            ("Depth", "Speed", "Both"),
            _src_label[source],
            lambda text: _update_wake_field(
                self._controller, self._device_name, self._motor_idx,
                self._chain_idx, "source", _src_value.get(text, "both"),
            ),
        )
        src_row.addWidget(src_seg)
        src_row.addStretch(1)
        act_lay.addLayout(src_row)

        wt_row = _hbox(0, 8)
        wt_row.addWidget(QLabel("Wake threshold:"))
        wt_spin = _NoTrackSpin()
        wt_spin.setRange(0.0, 1.0)
        wt_spin.setSingleStep(0.01)
        wt_spin.setDecimals(2)
        wt_spin.setValue(_f(wake_cfg.get("wake_threshold", 0.05), 0.05))
        wt_spin.valueChanged.connect(self._on_wake_threshold_changed)
        wt_row.addWidget(wt_spin)
        wt_row.addStretch(1)
        act_lay.addLayout(wt_row)

        sd_row = _hbox(0, 8)
        sd_row.addWidget(QLabel("Sleep delay (s):"))
        sd_spin = _NoTrackSpin()
        sd_spin.setRange(0.0, 10.0)
        sd_spin.setSingleStep(0.1)
        sd_spin.setDecimals(1)
        sd_spin.setValue(_f(wake_cfg.get("sleep_delay_s", 0.5), 0.5))
        sd_spin.valueChanged.connect(
            lambda v: _update_wake_field(
                self._controller, self._device_name, self._motor_idx,
                self._chain_idx, "sleep_delay_s", float(v),
            )
        )
        sd_row.addWidget(sd_spin)
        sd_row.addStretch(1)
        act_lay.addLayout(sd_row)

        # Meter build-up: how long sustained movement takes to charge the
        # activity meter (attack tau). High values demand a few seconds of
        # motion before waking instead of opening on the first twitch.
        at_row = _hbox(0, 8)
        at_row.addWidget(QLabel("Build-up (s):"))
        at_spin = _NoTrackSpin()
        at_spin.setRange(0.01, 10.0)
        at_spin.setSingleStep(0.1)
        at_spin.setDecimals(2)
        at_spin.setValue(_f(wake_cfg.get("attack_s", 0.05), 0.05))
        at_spin.valueChanged.connect(
            lambda v: _update_wake_field(
                self._controller, self._device_name, self._motor_idx,
                self._chain_idx, "attack_s", float(v),
            )
        )
        at_row.addWidget(at_spin)
        at_row.addStretch(1)
        act_lay.addLayout(at_row)

        # Meter decay: how long the charged meter takes to drain once
        # movement stops (release tau). High values coast the "budget"
        # across brief pauses instead of bouncing below threshold.
        rl_row = _hbox(0, 8)
        rl_row.addWidget(QLabel("Decay (s):"))
        rl_spin = _NoTrackSpin()
        rl_spin.setRange(0.01, 10.0)
        rl_spin.setSingleStep(0.1)
        rl_spin.setDecimals(2)
        rl_spin.setValue(_f(wake_cfg.get("release_s", 0.5), 0.5))
        rl_spin.valueChanged.connect(
            lambda v: _update_wake_field(
                self._controller, self._device_name, self._motor_idx,
                self._chain_idx, "release_s", float(v),
            )
        )
        rl_row.addWidget(rl_spin)
        rl_row.addStretch(1)
        act_lay.addLayout(rl_row)

        # Activity meter visual.
        meter_label = QLabel("Activity")
        meter_label.setProperty("muted", "true")
        self._ui._repolish(meter_label)
        act_lay.addWidget(meter_label)
        meter = ActivityMeter()
        meter.set_threshold(_f(wake_cfg.get("wake_threshold", 0.05), 0.05))
        act_lay.addWidget(meter)
        self._activity_meter = meter

        # ---- Strokes params (the old Arming / sleep gate) ----
        th_row = _hbox(0, 8)
        th_row.addWidget(QLabel("Thrusts:"))
        th_spin = _NoTrackSpin()
        th_spin.setRange(1.0, 10.0)
        th_spin.setSingleStep(1.0)
        th_spin.setDecimals(0)
        th_spin.setValue(_f(wake_cfg.get("thrusts", 3), 3.0))
        th_spin.valueChanged.connect(
            lambda v: _update_wake_field(
                self._controller, self._device_name, self._motor_idx,
                self._chain_idx, "thrusts", int(v),
            )
        )
        th_row.addWidget(th_spin)
        th_row.addStretch(1)
        str_lay.addLayout(th_row)

        wn_row = _hbox(0, 8)
        wn_row.addWidget(QLabel("Window (s):"))
        wn_spin = _NoTrackSpin()
        wn_spin.setRange(1.0, 30.0)
        wn_spin.setSingleStep(1.0)
        wn_spin.setDecimals(0)
        wn_spin.setValue(_f(wake_cfg.get("window_s", 6.0), 6.0))
        wn_spin.valueChanged.connect(
            lambda v: _update_wake_field(
                self._controller, self._device_name, self._motor_idx,
                self._chain_idx, "window_s", float(v),
            )
        )
        wn_row.addWidget(wn_spin)
        wn_row.addStretch(1)
        str_lay.addLayout(wn_row)

        da_row = _hbox(0, 8)
        da_row.addWidget(QLabel("Disarm after (s):"))
        da_spin = _NoTrackSpin()
        da_spin.setRange(5.0, 600.0)
        da_spin.setSingleStep(5.0)
        da_spin.setDecimals(0)
        da_spin.setValue(_f(wake_cfg.get("disarm_after_s", 45.0), 45.0))
        da_spin.valueChanged.connect(
            lambda v: _update_wake_field(
                self._controller, self._device_name, self._motor_idx,
                self._chain_idx, "disarm_after_s", float(v),
            )
        )
        da_row.addWidget(da_spin)
        da_row.addStretch(1)
        str_lay.addLayout(da_row)

        # Parent the frames, THEN set visibility — setVisible(True) on a
        # still-parentless frame briefly realises it as a top-level window.
        lay.addWidget(activity_frame)
        lay.addWidget(strokes_frame)
        activity_frame.setVisible(mode == "activity")
        strokes_frame.setVisible(mode == "strokes")
        return host

    def _on_wake_threshold_changed(self, val: float) -> None:
        """Spinbox is the canonical store; the activity meter visual
        mirrors it so the tick mark moves with the user's edit even
        before live data flows in."""
        _update_wake_field(
            self._controller, self._device_name, self._motor_idx,
            self._chain_idx, "wake_threshold", float(val),
        )
        if self._activity_meter is not None:
            try:
                self._activity_meter.set_threshold(float(val))
            except RuntimeError:
                pass

    def _make_subsection_header(self, title: str, subtitle: str) -> QWidget:
        """A bold subsection title stacked over a muted, word-wrapped
        one-line description. Used inside stage editors that bundle two
        distinct sub-stages (Envelope's Smoothing + Texture) so each half
        names its own purpose in plain language — the subtitle may bold
        <b>knob names</b> so every control is explained right where it
        lives."""
        host = QWidget()
        col = _vbox(0, 2)
        host.setLayout(col)
        t = QLabel(title)
        tf = t.font(); tf.setBold(True)
        t.setFont(tf)
        col.addWidget(t)
        sub = QLabel(subtitle)
        sub.setWordWrap(True)
        sf = sub.font()
        sf.setPointSize(max(7, sf.pointSize() - 1))
        sub.setFont(sf)
        sub.setProperty("muted", "true")
        self._ui._repolish(sub)
        col.addWidget(sub)
        return host

    def _make_gain_spin_row(self, sync_key: str, value: float):
        """One precise "Gain:" spinbox row, two-way synced with the quick
        slider registered under the same `sync_key` (see `_gain_field` —
        "<stage>" writes `gain`, "<stage>|out" writes `gain_out`).

        Factored out because the directional stages need the identical row
        twice, once per stroke direction."""
        row = _hbox(0, 8)
        row.addWidget(QLabel("Gain:"))
        spin = _NoTrackSpin()
        spin.setRange(0.0, 2.0)
        spin.setSingleStep(0.05)
        spin.setDecimals(2)
        spin.setValue(float(value))
        # Connect AFTER setValue so the seed is silent.
        spin.valueChanged.connect(
            lambda v, sk=sync_key: self._on_gain_from_spin(sk, float(v))
        )
        self._gain_spins[sync_key] = spin
        row.addWidget(spin)
        row.addStretch(1)
        return row

    def _make_hrule(self) -> QFrame:
        """A thin full-width divider line — cleanly separates the two
        halves of a bundled stage editor (Smoothing │ Texture) into
        visually distinct blocks. Static, built once per expand, so an
        inline stylesheet is fine (no per-frame repolish churn)."""
        line = QFrame()
        line.setObjectName("stageDivider")
        line.setFixedHeight(1)
        line.setStyleSheet(f"background-color: {COLOR_INPUT_BORDER};")
        return line

    def _build_envelope_editor(self) -> QWidget:
        """Envelope — how the level moves over time, split into two
        clearly-labelled halves with a divider between them:
          * Smoothing (top, the calm half): a rise/fall envelope follower
            that softens the signal, de-jitters it, and rounds the Wake
            gate's open/close transitions.
          * Texture (below, the lively half): a subtle downward-only
            wobble so a held level feels alive instead of sitting dead
            flat (formerly labelled "Grain").
        Texture runs AFTER smoothing on purpose — ahead of it, smoothing
        would iron the wobble back out. The config keys stay `smoothing`
        and `texture` separately; only the card merges."""
        host = QFrame()
        host.setObjectName("stageEditor")
        lay = _vbox(10, 8)
        host.setLayout(lay)

        hdr_row = _hbox(0, 6)
        header = QLabel("Envelope")
        hf = header.font(); hf.setBold(True)
        header.setFont(hf)
        hdr_row.addWidget(header)
        self._ui._explain(hdr_row,
            *_STAGE_TIPS[STAGE_ENVELOPE]
        )
        hdr_row.addStretch(1)
        lay.addLayout(hdr_row)

        chain = _read_chain(self._controller, self._device_name,
                            self._motor_idx, self._chain_idx)

        # ============ Smoothing — the calm half ============
        lay.addWidget(self._make_subsection_header(
            "Smoothing",
            "The calm half — softens motion and evens out jitter. "
            "<b>Rise</b> = how fast the level climbs, <b>Fall</b> = how "
            "fast it eases back down. Higher = gentler and slower.",
        ))

        sm_cfg = chain.get("smoothing", {}) if isinstance(chain, dict) else {}
        if not isinstance(sm_cfg, dict):
            sm_cfg = {}
        try:
            sm_rise = float(sm_cfg.get("rise_ms", 50.0))
        except (TypeError, ValueError):
            sm_rise = 50.0
        try:
            sm_fall = float(sm_cfg.get("fall_ms", 20.0))
        except (TypeError, ValueError):
            sm_fall = 20.0

        row = _hbox(0, 8)
        row.addWidget(QLabel("Rise:"))
        rise_spin = _NoTrackSpin()
        rise_spin.setRange(0.0, 2000.0)
        rise_spin.setSingleStep(10.0)
        rise_spin.setDecimals(0)
        rise_spin.setSuffix(" ms")
        rise_spin.setValue(sm_rise)
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
        fall_spin.setValue(sm_fall)
        fall_spin.valueChanged.connect(
            lambda v: self._on_smoothing_spin_changed("fall_ms", float(v))
        )
        self._smoothing_spins["fall_ms"] = fall_spin
        row.addWidget(fall_spin)
        row.addStretch(1)
        lay.addLayout(row)

        # ---- clean divide between the two halves ----
        lay.addWidget(self._make_hrule())

        # ============ Texture — the lively half (formerly "Grain") ====
        lay.addWidget(self._make_subsection_header(
            "Texture",
            "The lively half — a subtle wobble so a held level feels "
            "alive, not flat. <b>Amount</b> = how deep the wobble, "
            "<b>Rate</b> = how fast. Optional; off by default.",
        ))

        tc_cfg = chain.get("texture", {}) if isinstance(chain, dict) else {}
        if not isinstance(tc_cfg, dict):
            tc_cfg = {}  # hand-edited profile — build from defaults
        try:
            tc_amount = float(tc_cfg.get("amount", 0.25))
        except (TypeError, ValueError):
            tc_amount = 0.25
        try:
            tc_rate = float(tc_cfg.get("rate_hz", 2.0))
        except (TypeError, ValueError):
            tc_rate = 2.0

        # Enable toggle.
        enable_cb = ToggleSwitch("Enable")
        enable_cb.setChecked(bool(tc_cfg.get("enabled", False)))
        enable_cb.toggled.connect(
            lambda v: _update_chain_field(
                self._controller, self._device_name, self._motor_idx,
                self._chain_idx, ("texture", "enabled"), bool(v),
            )
        )
        lay.addWidget(enable_cb)

        # Amount: stored 0..0.9, exposed as 0-90 %.
        am_row = _hbox(0, 8)
        am_row.addWidget(QLabel("Amount (%):"))
        am_spin = _NoTrackSpin()
        am_spin.setRange(0.0, 90.0)
        am_spin.setSingleStep(5.0)
        am_spin.setDecimals(0)
        am_spin.setValue(tc_amount * 100.0)
        am_spin.valueChanged.connect(
            lambda v: _update_chain_field(
                self._controller, self._device_name, self._motor_idx,
                self._chain_idx, ("texture", "amount"), float(v) / 100.0,
            )
        )
        am_row.addWidget(am_spin)
        am_row.addStretch(1)
        lay.addLayout(am_row)

        # Rate: texture wobble frequency.
        rt_row = _hbox(0, 8)
        rt_row.addWidget(QLabel("Rate (Hz):"))
        rt_spin = _NoTrackSpin()
        rt_spin.setRange(0.2, 8.0)
        rt_spin.setSingleStep(0.1)
        rt_spin.setDecimals(1)
        rt_spin.setValue(tc_rate)
        rt_spin.valueChanged.connect(
            lambda v: _update_chain_field(
                self._controller, self._device_name, self._motor_idx,
                self._chain_idx, ("texture", "rate_hz"), float(v),
            )
        )
        rt_row.addWidget(rt_spin)
        rt_row.addStretch(1)
        lay.addLayout(rt_row)

        # Faster with movement (config key `follow_speed`): the wobble RATE
        # scales up with the speed signal. Relabelled from "Follow speed" so
        # it reads as a clear pair with the depth control below — one ties
        # rate to movement, the other ties depth.
        follow_cb = ToggleSwitch("Faster with movement")
        follow_cb.setChecked(bool(tc_cfg.get("follow_speed", False)))
        follow_cb.toggled.connect(
            lambda v: _update_chain_field(
                self._controller, self._device_name, self._motor_idx,
                self._chain_idx, ("texture", "follow_speed"), bool(v),
            )
        )
        lay.addWidget(follow_cb)

        # Depth vs movement (config key `depth_follow`): scales the wobble
        # DEPTH by how fast you're moving. Off = constant; Stronger = deeper
        # as you move; Weaker = full at rest, fading out under motion.
        depth_follow = str(tc_cfg.get("depth_follow", "off")).lower()
        if depth_follow not in ("off", "up", "down"):
            depth_follow = "off"
        _df_label = {"off": "Off", "up": "Stronger", "down": "Weaker"}
        _df_value = {"Off": "off", "Stronger": "up", "Weaker": "down"}
        df_row = _hbox(0, 8)
        df_row.addWidget(QLabel("Depth vs movement:"))
        df_seg = self._make_segmented(
            ("Off", "Stronger", "Weaker"),
            _df_label[depth_follow],
            lambda text: _update_chain_field(
                self._controller, self._device_name, self._motor_idx,
                self._chain_idx, ("texture", "depth_follow"),
                _df_value.get(text, "off"),
            ),
        )
        df_row.addWidget(df_seg)
        df_row.addStretch(1)
        lay.addLayout(df_row)

        return host

    def _build_output_level_block(self) -> QWidget:
        """This chain's output level: a gain multiplier plus the toy's
        usable output band, in one block.

        **Gain** balances this chain against the other one (and against
        the rest of the rig — pull down a motor that always hits harder,
        so the global strength slider stays honest across every device).

        **Range** is CALIBRATION, and it remaps rather than clips: the
        chain's full 0–100 % still spreads across [min, max], so a toy
        whose motor doesn't start turning until 20 % can skip that dead
        zone without losing any input resolution, and one that gets
        unpleasant past 80 % can be capped without flattening the top of
        its travel. Silence is exempt — no input means no output, never
        the floor."""
        host = QFrame()
        host.setObjectName("outputLevelBlock")
        lay = _vbox(0, 6)
        host.setLayout(lay)

        gain, out_min, out_max = _get_output_stage(
            self._controller, self._device_name, self._motor_idx,
            self._chain_idx,
        )

        gain_row = _hbox(0, 8)
        gain_row.addWidget(QLabel("Gain:"))
        ctrl = _GainControl(gain)
        ctrl.gainChanged.connect(
            lambda g: _set_output_field(
                self._controller, self._device_name, self._motor_idx,
                self._chain_idx, "gain", float(g),
            )
        )
        gain_row.addWidget(ctrl, 1)
        self._ui._explain(gain_row,
            "Output gain",
            "Scales everything this chain puts out, the last thing before "
            "the range below. Leave it at ×1.00 unless this chain feels "
            "out of balance with your other toys — or, on a two-chain "
            "motor, with its sibling. Above ×1.00 boosts, but the result "
            "still stops at the range's maximum."
        )
        lay.addLayout(gain_row)

        # Range — two percent spinboxes. Each one bounds the other's
        # range live, so the band can never be inverted in the first place
        # (no silent clamp-on-save to explain afterwards).
        range_row = _hbox(0, 6)
        range_row.addWidget(QLabel("Range:"))

        min_spin = _NoTrackSpin()
        min_spin.setRange(0.0, 100.0)
        min_spin.setSingleStep(5.0)
        min_spin.setDecimals(0)
        min_spin.setSuffix(" %")
        min_spin.setValue(out_min * 100.0)

        max_spin = _NoTrackSpin()
        max_spin.setRange(0.0, 100.0)
        max_spin.setSingleStep(5.0)
        max_spin.setDecimals(0)
        max_spin.setSuffix(" %")
        max_spin.setValue(out_max * 100.0)

        min_spin.setMaximum(max_spin.value())
        max_spin.setMinimum(min_spin.value())

        def on_min(v: float) -> None:
            max_spin.setMinimum(float(v))
            _set_output_field(self._controller, self._device_name,
                              self._motor_idx, self._chain_idx,
                              "min", float(v) / 100.0)

        def on_max(v: float) -> None:
            min_spin.setMaximum(float(v))
            _set_output_field(self._controller, self._device_name,
                              self._motor_idx, self._chain_idx,
                              "max", float(v) / 100.0)

        min_spin.valueChanged.connect(on_min)
        max_spin.valueChanged.connect(on_max)

        range_row.addWidget(min_spin)
        range_row.addWidget(QLabel("–"))
        range_row.addWidget(max_spin)
        self._ui._explain(range_row,
            "Output range",
            "What this toy can usefully do. The chain's full 0–100 % is "
            "spread across this band instead of being cut off at either "
            "end, so you keep all the detail either way.\n\n"
            "Raise the minimum for a motor that just sits there humming "
            "below, say, 20 % — the moment there's any input at all it "
            "jumps straight to that level and works upward from there. "
            "Lower the maximum for one that gets uncomfortable or rattles "
            "near the top.\n\n"
            "No input still means no output: the floor only applies once "
            "the chain is actually producing something. The strength "
            "slider is applied before this, so the numbers are what the "
            "toy really receives — which also means strength can no "
            "longer push this chain below its minimum. Off and the "
            "per-toy mute still silence it completely.\n\n"
            "The VRChat menu's Test pulse is remapped into this range too, "
            "so a motor with a raised minimum still buzzes when you check "
            "it rather than sitting silently in its dead zone."
        )
        range_row.addStretch(1)
        lay.addLayout(range_row)
        return host

    def _build_output_editor(self) -> QWidget:
        """The motor's final stage: the output trim (every motor kind),
        plus Mode / Idle / Stroke setup for linear actuators."""
        host = QFrame()
        host.setObjectName("stageEditor")
        lay = _vbox(10, 8)
        host.setLayout(lay)

        hdr_row = _hbox(0, 6)
        header = QLabel("Output")
        hf = header.font(); hf.setBold(True)
        header.setFont(hf)
        hdr_row.addWidget(header)

        # Continuous-output actuator — the chain's post-smoothing value
        # drives whichever physical effect the buttplug.io OutputType
        # describes. Phrase looked up from the shared _KIND_DISPLAY table;
        # unknown kinds fall back to the vibrate phrasing.
        info = _KIND_DISPLAY.get(self._motor_kind, _DEFAULT_KIND_DISPLAY)
        self._ui._explain(hdr_row,
            "Output",
            f"The end of the chain — the final value drives the "
            f"{info.output_phrase}. Use the meter below the chain to see "
            f"the live output."
        )
        hdr_row.addStretch(1)
        lay.addLayout(hdr_row)

        lay.addWidget(self._build_output_level_block())

        if not self._is_linear:
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
        Depth/Speed/Punch quick gain sliders, and restore the expanded
        stage."""
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
        # Re-seed every registered quick slider, including the outward
        # halves of the directional stages (registered under "<stage>|out").
        for sync_key in list(self._gain_sliders):
            slider = self._gain_sliders.get(sync_key)
            if slider is None:
                continue
            section, field = self._gain_field(sync_key)
            cfg = chain.get(section, {}) if isinstance(chain, dict) else {}
            if not isinstance(cfg, dict):
                cfg = {}
            default_gain = 0.0 if section == STAGE_PUNCH else 1.0
            try:
                seed = float(cfg.get("gain", default_gain))
                if field == "gain_out":
                    # Speed's outward half follows the inward gain when
                    # unset; Punch's stays off.
                    out_default = 0.0 if section == STAGE_PUNCH else seed
                    seed = float(cfg.get("gain_out", out_default))
                slider.set_gain(seed)
            except (TypeError, ValueError):
                pass
            except RuntimeError:
                self._gain_sliders.pop(sync_key, None)
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

def _sim_addresses_for_type(chain_type: str) -> Tuple[str, ...]:
    """Which simulator address(es) a chain of this type listens to."""
    if chain_type == "penetration":
        return (SIM_PEN_ADDRESS,)
    if chain_type == "touch":
        return (SIM_TOUCH_ADDRESS,)
    return SIM_ADDRESSES


def _motor_osc_addresses(controller, device_name: str, motor_idx: int) -> List[str]:
    table = controller.get_profile_config(device_name, "osc_addresses", {}) or {}
    raw = table.get(str(motor_idx)) if isinstance(table, dict) else None
    if isinstance(raw, str):
        raw = [raw]
    return [a for a in (raw or []) if isinstance(a, str) and a.strip()]


def _motor_listens_to_sim(controller, device_name: str, motor_idx: int,
                          chain_type: str) -> bool:
    have = set(_motor_osc_addresses(controller, device_name, motor_idx))
    return all(a in have for a in _sim_addresses_for_type(chain_type))


def _set_motor_sim_listening(controller, device_name: str, motor_idx: int,
                             chain_type: str, on: bool) -> None:
    """Add or remove the simulator address(es) for `chain_type` in the
    motor's custom OSC addresses -- the same table the Listening To chips
    edit, written the same way."""
    table = controller.get_profile_config(device_name, "osc_addresses", {}) or {}
    table = dict(table) if isinstance(table, dict) else {}
    current = _motor_osc_addresses(controller, device_name, motor_idx)
    wanted = _sim_addresses_for_type(chain_type)
    if on:
        current = current + [a for a in wanted if a not in current]
    else:
        current = [a for a in current if a not in wanted]
    table[str(motor_idx)] = current
    controller.update_device_config(device_name, "osc_addresses", table)
    for hook in ("save_profiles", "force_recalculate"):
        fn = getattr(controller, hook, None)
        if callable(fn):
            try:
                fn()
            except Exception:
                pass


def _chain_summary_line(controller, device_name: str, motor_idx: int,
                        chain_idx: int) -> str:
    """The folded chain's identity in one muted line: what it listens to
    and how it is tuned. This is what lets a stack of six chains be told
    apart WITHOUT opening any of them — the live pips above it say what
    is happening now; this says what the chain IS."""
    chain = _read_chain(controller, device_name, motor_idx, chain_idx)
    if not isinstance(chain, dict):
        return " "
    bits: List[str] = []

    # Input: per-chain zones (motor fallback), then self/others flags.
    _MISSING = object()

    def routed(suffix, default):
        v = controller.get_profile_config(
            device_name, f"motor_{motor_idx}_c{chain_idx}_{suffix}", _MISSING)
        if v is _MISSING:
            v = controller.get_profile_config(
                device_name, f"motor_{motor_idx}_{suffix}", default)
        return v

    # Spell the selected inputs OUT — which sockets/penetrators, and
    # which custom parameters. In a folded stack the input is usually
    # what distinguishes two chains of the same type, so it earns the
    # room; the label elides from the right when the row runs out, and
    # the tuning bits after it are the more compressible half.
    zones = [z.strip() for z in str(routed("zones", "All SPS")).split(",")
             if z.strip() and z.strip() != "None"]
    if not zones:
        zone_txt = "no zones"
    elif "All SPS" in zones:
        rest = [z for z in zones if z != "All SPS"]
        zone_txt = "All SPS" + (" +" + "+".join(rest) if rest else "")
    else:
        zone_txt = "+".join(zones)
    so = ("S" if routed("self", False) else "") + \
         ("O" if routed("others", True) else "")
    bits.append(f"{zone_txt}·{so}" if so else f"{zone_txt}·—")
    # Custom OSC parameters mapped onto this motor (they feed every
    # chain — addresses are per-motor).
    osc_addresses = controller.get_profile_config(
        device_name, "osc_addresses", {}) or {}
    raw = osc_addresses.get(str(motor_idx)) \
        if isinstance(osc_addresses, dict) else None
    if isinstance(raw, str):
        raw = [raw]
    params = [a for a in (raw or []) if isinstance(a, str) and a.strip()]
    if any(a in SIM_ADDRESSES for a in params):
        params = [a for a in params if a not in SIM_ADDRESSES] + ["sim"]
    if params:
        bits.append("@" + "+".join(params))

    def num(section, key, default):
        try:
            return float(chain.get(section, {}).get(key, default))
        except (TypeError, ValueError, AttributeError):
            return default

    d = num("depth", "gain", 1.0)
    s_in = num("speed", "gain", 1.0)
    s_out = num("speed", "gain_out", s_in)
    bits.append(f"d{d:.2g}")
    bits.append(f"s{s_in:.2g}" if s_in == s_out else f"s{s_in:.2g}/{s_out:.2g}")
    p_in = num("punch", "gain", 0.0)
    p_out = num("punch", "gain_out", 0.0)
    if p_in > 0 or p_out > 0:
        bits.append(f"p{p_in:.2g}" if p_out == 0.0
                    else f"p{p_in:.2g}/{p_out:.2g}")
    bits.append(str(chain.get("combine", "max")))

    wake = chain.get("wake", {}) if isinstance(chain.get("wake"), dict) else {}
    if wake.get("enabled", False):
        if str(wake.get("mode", "activity")) == "strokes":
            bits.append(f"wake {num('wake', 'thrusts', 3):.0f}×")
        else:
            bits.append(f"wake {num('wake', 'wake_threshold', 0.05):.2g}")
    duck = chain.get("duck", {}) if isinstance(chain.get("duck"), dict) else {}
    if (duck.get("enabled", False)
            and str(chain.get("type", "")) != "penetration"):
        bits.append("duck")
    sm_r = num("smoothing", "rise_ms", 50.0)
    sm_f = num("smoothing", "fall_ms", 20.0)
    bits.append(f"{sm_r:.0f}/{sm_f:.0f}ms")
    tx = chain.get("texture", {})
    if isinstance(tx, dict) and tx.get("enabled", False):
        bits.append("tex")
    zc = chain.get("zerocut", {})
    if isinstance(zc, dict) and zc.get("enabled", False):
        bits.append("cut")
    out_gain, out_min, out_max = _get_output_stage(
        controller, device_name, motor_idx, chain_idx)
    if out_min > 0.005 or out_max < 0.995:
        bits.append(f"{out_min * 100:.0f}–{out_max * 100:.0f}%")
    elif abs(out_gain - 1.0) >= 0.005:
        bits.append(f"×{out_gain:.2f}")
    return "  ·  ".join(bits)


class _ElidedLabel(QLabel):
    """QLabel that elides its FULL text from the right instead of
    forcing the row wide or clipping mid-glyph. Elision happens by
    re-setting the visible text on resize, so QSS styling (the muted
    colour) keeps applying — a custom paintEvent would bypass it."""

    def __init__(self, text: str = "", parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._full = text
        pol = self.sizePolicy()
        pol.setHorizontalPolicy(QSizePolicy.Ignored)
        self.setSizePolicy(pol)
        self._apply()

    def set_full_text(self, text: str) -> None:
        if text == self._full:
            return
        self._full = text
        self._apply()

    def full_text(self) -> str:
        return self._full

    def resizeEvent(self, ev) -> None:
        super().resizeEvent(ev)
        self._apply()

    def _apply(self) -> None:
        fm = self.fontMetrics()
        avail = max(24, self.width() - 2)
        super().setText(fm.elidedText(self._full, Qt.ElideRight, avail))


class _StagePipStrip(QWidget):
    """Nine tiny letters — I D S P C W E Z O — one per stage, each lit by
    that stage's LIVE level (same lerp as the big cards' borders) and
    dimmed when the stage is switched off.

    One custom-painted widget rather than nine QLabels: levels arrive
    per routing tick, and restyling nine labels at 60 Hz is stylesheet
    churn for something a single update() repaints in one pass."""

    _LETTERS = ("I", "D", "S", "P", "C", "W", "E", "Z", "O")
    _STAGES = _STAGE_ORDER
    _CELL_W = 13

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._levels = [0.0] * len(self._STAGES)
        self._enabled = [True] * len(self._STAGES)
        self.setFixedHeight(16)
        self.setFixedWidth(len(self._LETTERS) * self._CELL_W + 2)
        self.setToolTip(
            "Live per-stage levels: Input · Depth · Speed · Punch · "
            "Combine · Wake · Envelope · Zero cut · Output. "
            "Dimmed = stage switched off.")

    def set_levels(self, payload: Dict[str, Any]) -> None:
        changed = False
        for i, stage in enumerate(self._STAGES):
            trace = _STAGE_LEVEL_TRACE.get(stage)
            try:
                lv = max(0.0, min(1.0, float(payload.get(trace, 0.0))))
            except (TypeError, ValueError):
                lv = 0.0
            # Quantize so idle jitter doesn't repaint every tick.
            lv = round(lv * 20) / 20.0
            if lv != self._levels[i]:
                self._levels[i] = lv
                changed = True
        if changed:
            self.update()

    def set_enabled_flags(self, flags: List[bool]) -> None:
        flags = list(flags)[:len(self._STAGES)]
        flags += [True] * (len(self._STAGES) - len(flags))
        if flags != self._enabled:
            self._enabled = flags
            self.update()

    def paintEvent(self, _ev) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        f = self.font()
        f.setPointSize(max(6, f.pointSize() - 2))
        f.setBold(True)
        p.setFont(f)
        h = self.height()
        for i, letter in enumerate(self._LETTERS):
            x = i * self._CELL_W
            if self._enabled[i]:
                color = MotorSignalChainWidget._lerp_purple_pink(
                    self._levels[i])
            else:
                color = QColor(COLOR_TEXT_MUTED)
                color.setAlpha(90)
            p.setPen(color)
            p.drawText(QRectF(x, 0, self._CELL_W, h),
                       Qt.AlignCenter, letter)
        p.end()


class _ChainFoldBar(QFrame):
    """The super-compact face of one chain: two short rows that carry as
    much of the chain as fits without opening it.

      * Row 1 is LIVE — the name (type-accented), how this chain merges
        into the stack, nine per-stage level pips, a full-width output
        meter, and the output number. The row stretches to use every
        pixel: the meter absorbs whatever width the labels don't need.
      * Row 2 is IDENTITY — a muted one-liner of what the chain listens
        to and how it is tuned, refreshed on a slow timer. With six
        chains stacked this line is how you find the one you want.

    Clicking anywhere on the bar toggles the chain open/closed (child
    buttons consume their own clicks). The bar owns its OWN router
    subscription, visibility-driven exactly like the chain widget's, so
    folded chains still show live data while costing nothing when the
    whole card is off-screen."""

    clicked = Signal(int)
    removeRequested = Signal(int)
    intermediates = Signal(dict)

    def __init__(self, ui, device_name: str, motor_idx: int,
                 chain_idx: int, n_chains: int, expanded: bool,
                 merge_op: str,
                 parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._ui = ui
        self._controller = ui.controller
        self._device_name = device_name
        self._motor_idx = motor_idx
        self._chain_idx = chain_idx
        self._subscribed = False
        self.setObjectName("chainFoldBar")
        self.setCursor(Qt.PointingHandCursor)
        # Two rows and NO more: without a fixed vertical policy the bars
        # absorb the wrapper's spare height (they used to share it with
        # the since-removed simulator and overview rows) and the compact
        # face stops being compact.
        pol = self.sizePolicy()
        pol.setVerticalPolicy(QSizePolicy.Fixed)
        self.setSizePolicy(pol)

        chain_type = _get_chain_type(self._controller, device_name, motor_idx,
                                     chain_idx)
        accent = CHAIN_TYPE_ACCENTS.get(chain_type, CHAIN_TYPE_ACCENTS["custom"])
        # The fold bar's frame takes the type hue's mid tone (QSS variant).
        self.setProperty("hue", _theme.CHAIN_TYPE_HUES.get(chain_type, "grey"))

        outer = _hbox(6, 8)
        self.setLayout(outer)

        bar = QFrame()
        bar.setFixedWidth(3)
        bar.setStyleSheet(f"background: {accent}; border-radius: 1px;")
        outer.addWidget(bar)

        col = _vbox(0, 1)
        outer.addLayout(col, 1)

        row1 = _hbox(0, 8)
        self._arrow = QLabel("▾" if expanded else "▸")
        self._arrow.setFixedWidth(12)
        row1.addWidget(self._arrow)

        self._name_label = QLabel(_chain_display_name(
            self._controller, device_name, motor_idx, chain_idx))
        nf = self._name_label.font()
        nf.setBold(True)
        self._name_label.setFont(nf)
        row1.addWidget(self._name_label)

        if chain_idx > 0:
            # How this chain joins the stack. The op is shared by the
            # whole motor, so the tag repeats — but a folded stack shows
            # no merge picker, and a repeated hint beats an invisible op.
            tag = QLabel(f"{_MERGE_TAGS.get(merge_op, '∨')} {merge_op}")
            tag.setProperty("muted", "true")
            tf = tag.font()
            tf.setPointSize(max(6, tf.pointSize() - 2))
            tag.setFont(tf)
            self._ui._repolish(tag)
            row1.addWidget(tag)

        self._pips = _StagePipStrip()
        row1.addWidget(self._pips)

        self._meter = _RainbowMeter(maximum=1000)
        self._meter.setFixedHeight(10)
        self._meter_proxy = _ProgressProxy(self._meter)
        row1.addWidget(self._meter, 1)      # the row's slack lands here

        self._out_label = QLabel("—")
        self._out_label.setObjectName("stageOutNum")
        self._out_label.setFixedWidth(38)
        self._out_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self._last_out = -1.0
        row1.addWidget(self._out_label)

        if n_chains > 1:
            x = QPushButton("✕")
            # stageCycleButton's QSS trims the default 6px/14px button
            # padding, which is wider than this whole button — without
            # it the glyph clips to nothing (same trap as the Combine
            # cycle button).
            x.setObjectName("stageCycleButton")
            x.setFixedSize(18, 18)
            x.setProperty("role", "danger")
            x.setToolTip("Remove this chain")
            x.clicked.connect(
                lambda _=False: self.removeRequested.emit(self._chain_idx))
            row1.addWidget(x)
        col.addLayout(row1)

        self._summary = _ElidedLabel(" ")
        self._summary.setProperty("muted", "true")
        sf = self._summary.font()
        sf.setPointSize(max(7, sf.pointSize() - 2))
        self._summary.setFont(sf)
        self._ui._repolish(self._summary)
        col.addWidget(self._summary)

        # Live plumbing: router callback → queued signal → UI slot.
        self.intermediates.connect(self._on_intermediates)
        self._callback = self.intermediates.emit

        # Identity line + stage on/off flags change rarely (config
        # edits), so a slow timer keeps them honest without touching the
        # config dict at tick rate.
        self._refresh_timer = QTimer(self)
        self._refresh_timer.setInterval(1000)
        self._refresh_timer.timeout.connect(self._refresh_static)
        self._refresh_static()

    # ---- live path ----

    def _on_intermediates(self, payload: Dict[str, Any]) -> None:
        try:
            self._pips.set_levels(payload)
            out = float(payload.get("out", 0.0))
            self._meter_proxy.set(out)
            if abs(out - self._last_out) >= 0.005:
                self._last_out = out
                self._out_label.setText(f"{out:.2f}")
        except RuntimeError:
            pass

    def _refresh_static(self) -> None:
        try:
            # Renaming a custom chain (or retyping one) happens in the
            # open editor below; the folded face follows on the next
            # tick of this timer rather than needing a rebuild.
            self._name_label.setText(_chain_display_name(
                self._controller, self._device_name, self._motor_idx,
                self._chain_idx))
            self._summary.set_full_text(_chain_summary_line(
                self._controller, self._device_name, self._motor_idx,
                self._chain_idx) or " ")
            chain = _read_chain(self._controller, self._device_name,
                                self._motor_idx, self._chain_idx)

            def g(sec, key, dflt):
                try:
                    return float(chain.get(sec, {}).get(key, dflt))
                except (TypeError, ValueError, AttributeError):
                    return dflt

            s_in = g("speed", "gain", 1.0)
            wake = chain.get("wake", {})
            zc = chain.get("zerocut", {})
            self._pips.set_enabled_flags([
                True,                                     # Input
                g("depth", "gain", 1.0) > 0.0,            # Depth
                s_in > 0.0 or g("speed", "gain_out", s_in) > 0.0,
                g("punch", "gain", 0.0) > 0.0
                or g("punch", "gain_out", 0.0) > 0.0,     # Punch
                True,                                     # Combine
                bool(isinstance(wake, dict)
                     and wake.get("enabled", False)),     # Wake
                True,                                     # Envelope
                bool(isinstance(zc, dict)
                     and zc.get("enabled", False)),       # Zero cut
                True,                                     # Output
            ])
        except RuntimeError:
            pass

    # ---- subscription lifecycle (mirrors MotorSignalChainWidget) ----

    def _subscribe(self) -> None:
        if self._subscribed:
            return
        router = getattr(self._controller, "motor_router", None)
        if router is not None and hasattr(router, "subscribe_intermediates"):
            try:
                router.subscribe_intermediates(
                    self._device_name, self._motor_idx, self._chain_idx,
                    self._callback)
                self._subscribed = True
            except Exception:
                pass
        self._refresh_timer.start()

    def _unsubscribe(self) -> None:
        self._refresh_timer.stop()
        if not self._subscribed:
            return
        self._subscribed = False
        router = getattr(self._controller, "motor_router", None)
        if router is not None and hasattr(router, "unsubscribe_intermediates"):
            try:
                router.unsubscribe_intermediates(
                    self._device_name, self._motor_idx, self._chain_idx,
                    self._callback)
            except Exception:
                pass

    def showEvent(self, ev) -> None:
        super().showEvent(ev)
        self._subscribe()

    def hideEvent(self, ev) -> None:
        super().hideEvent(ev)
        self._unsubscribe()

    def teardown(self) -> None:
        self._unsubscribe()

    def mousePressEvent(self, ev) -> None:
        if ev.button() == Qt.LeftButton:
            self.clicked.emit(self._chain_idx)
            ev.accept()
            return
        super().mousePressEvent(ev)


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


        # Which chains are OPEN. Session-only, preserved across
        # _rebuild. Default: a single-chain motor opens its one chain
        # (nothing to scan past); a multi-chain motor starts fully
        # folded — with a chain per contact type the folded stack IS
        # the overview, and you open the one you're working on.
        self._fold_open: Dict[int, bool] = {}
        self._fold_bars: List[_ChainFoldBar] = []


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
        # Tear down intermediates subscriptions before deleting.
        for w in self._chain_widgets:
            try:
                w.teardown()
            except (RuntimeError, AttributeError):
                pass
        for bar in self._fold_bars:
            try:
                bar.teardown()
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
        self._fold_bars.clear()

        n = _get_chain_count(self._controller, self._device_name, self._motor_idx)
        n = max(1, min(n, MAX_CHAINS_PER_MOTOR))
        merge_op = _get_merge_op(self._controller, self._device_name,
                                 self._motor_idx)
        prev_open = False
        for chain_idx in range(n):
            is_open = self._fold_open.get(chain_idx, n == 1)
            # The merge picker only appears next to an OPEN chain —
            # folded bars carry a compact merge tag instead, so a fully
            # folded stack spends no rows on an op nobody is editing.
            if chain_idx > 0 and (is_open or prev_open):
                self._root_lay.addWidget(self._build_merge_row())
            bar = _ChainFoldBar(
                self._ui, self._device_name, self._motor_idx,
                chain_idx, n, is_open, merge_op,
            )
            bar.clicked.connect(self._on_fold_toggled)
            bar.removeRequested.connect(self._on_remove_chain)
            self._fold_bars.append(bar)
            self._root_lay.addWidget(bar)
            chain_widget = MotorSignalChainWidget(
                self._ui, self._device_name, self._motor_idx,
                self._motor_kind, chain_idx=chain_idx,
            )
            self._chain_widgets.append(chain_widget)
            self._root_lay.addWidget(chain_widget)
            # A folded chain's widget stays built (cheap: it re-reads
            # config on construction anyway) but hidden — hideEvent
            # keeps its router subscription off, so a folded chain
            # costs one fold-bar feed and nothing else.
            chain_widget.setVisible(is_open)
            prev_open = is_open
        if n < MAX_CHAINS_PER_MOTOR:
            self._root_lay.addWidget(self._build_add_row())



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

    def _on_fold_toggled(self, chain_idx: int) -> None:
        """Open/close one chain and rebuild. Independent toggles, not an
        accordion — comparing two chains side by side is a real
        workflow, so opening one must not slam the other shut."""
        n = _get_chain_count(self._controller, self._device_name,
                             self._motor_idx)
        current = self._fold_open.get(chain_idx, n == 1)
        self._fold_open[chain_idx] = not current
        self._rebuild()

    def _on_add_chain(self) -> None:
        if _add_chain(self._controller, self._device_name, self._motor_idx):
            self._rebuild()

    def _on_remove_chain(self, chain_idx: int) -> None:
        if _remove_chain(self._controller, self._device_name,
                         self._motor_idx, chain_idx):
            self._rebuild()


# ----------------------------------------------------------
# ChainOverviewPanel — the PAGE-LEVEL six-trace overview.
# ----------------------------------------------------------

class ChainOverviewPanel(QFrame):
    """One overview for the whole Device Routing page, replacing the
    per-wrapper ▸ Overview row.

    The wrapper version paid for its flexibility: every motor carried a
    disclosure row whether or not anyone ever opened it, and the graph
    machinery was woven through the wrapper's rebuild/destroy paths.
    This panel exists once, its visibility IS its enablement (the page
    top bar shows it only while the Overview toggle is on), and the
    target — which device, motor and chain the graph observes — is set
    explicitly via `set_target`.

    Subscription lifecycle mirrors the chain widgets': subscribe on
    show, unsubscribe on hide, so a hidden panel costs the router
    nothing. Retargeting while visible rebinds and clears the graph so
    the new chain's trace doesn't start mid-window against the old
    chain's history."""

    intermediates = Signal(dict)

    def __init__(self, controller,
                 parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._controller = controller
        self._target: Optional[Tuple[str, int, int]] = None
        self._subscribed_key: Optional[Tuple[str, int, int]] = None
        lay = _vbox(6, 4)
        self.setLayout(lay)
        traces = [_trace_spec(tid) for tid in _OVERVIEW_TRACE_IDS]
        self._graph = _TraceGraph(traces=traces, window_s=_OVERVIEW_WINDOW_S)
        self._graph.setFixedHeight(_OVERVIEW_GRAPH_HEIGHT)
        lay.addWidget(self._graph)
        self.intermediates.connect(self._on_intermediates)
        self._callback = self.intermediates.emit

    def set_target(self, device_name: Optional[str], motor_idx: int = 0,
                   chain_idx: int = 0) -> None:
        """Point the graph at one chain (or None to blank it)."""
        new = (None if device_name is None
               else (str(device_name), int(motor_idx), int(chain_idx)))
        if new == self._target:
            return
        was = self._subscribed_key is not None
        self._unsubscribe()
        self._target = new
        try:
            self._graph.clear()
        except (RuntimeError, AttributeError):
            pass
        if (was or self.isVisible()) and new is not None:
            self._subscribe()

    def _on_intermediates(self, payload: Dict[str, Any]) -> None:
        try:
            t_s = float(payload.get("t_ms", 0.0)) / 1000.0
        except (TypeError, ValueError):
            return
        for trace_id in _OVERVIEW_TRACE_IDS:
            v = payload.get(trace_id)
            if v is None:
                continue
            try:
                self._graph.push_sample(trace_id, t_s, float(v))
            except (TypeError, ValueError, RuntimeError):
                return

    def _subscribe(self) -> None:
        if self._subscribed_key is not None or self._target is None:
            return
        router = getattr(self._controller, "motor_router", None)
        if router is None or not hasattr(router, "subscribe_intermediates"):
            return
        d, m, c = self._target
        try:
            router.subscribe_intermediates(d, m, c, self._callback)
            self._subscribed_key = self._target
        except Exception:
            pass

    def _unsubscribe(self) -> None:
        key = self._subscribed_key
        if key is None:
            return
        self._subscribed_key = None
        router = getattr(self._controller, "motor_router", None)
        if router is None or not hasattr(router, "unsubscribe_intermediates"):
            return
        try:
            router.unsubscribe_intermediates(key[0], key[1], key[2],
                                             self._callback)
        except Exception:
            pass

    def showEvent(self, ev) -> None:
        super().showEvent(ev)
        self._subscribe()

    def hideEvent(self, ev) -> None:
        super().hideEvent(ev)
        self._unsubscribe()

    def teardown(self) -> None:
        self._unsubscribe()
