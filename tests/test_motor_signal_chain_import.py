"""Smoke + behaviour tests for the motor signal-chain widget module.

Importing the module fails fast if there's a syntax error, missing
import, or typo in a class/function name. The storage-helper tests
exercise the read/write round-trip through a stub controller so the
chain_idx-aware schema (Cut 5) is validated without a live UI."""

import pytest


class StubController:
    """Minimal controller surface that motor_signal_chain helpers
    call. Records save/recalc counts so tests can assert side effects."""

    def __init__(self) -> None:
        self.profiles: dict = {}
        self.saved = 0
        self.recalced = 0

    def get_profile_config(self, device_name, key, default):
        return self.profiles.get(device_name, {}).get(key, default)

    def update_device_config(self, device_name, key, value):
        self.profiles.setdefault(device_name, {})[key] = value

    def save_profiles(self):
        self.saved += 1

    def force_recalculate(self):
        self.recalced += 1


def test_module_imports():
    import ui.motor_signal_chain as msc  # noqa: F401
    # The three main public symbols must exist.
    assert hasattr(msc, "MotorSignalChainWidget")
    assert hasattr(msc, "MotorChainListWidget")
    assert hasattr(msc, "ActivityMeter")
    assert msc.MAX_CHAINS_PER_MOTOR == 6


def test_stage_constants_are_unique_and_ordered():
    from ui.motor_signal_chain import (
        _STAGE_ORDER, _STAGE_LABELS,
        STAGE_INPUT, STAGE_DEPTH, STAGE_SPEED, STAGE_PUNCH,
        STAGE_COMBINE, STAGE_WAKE, STAGE_ENVELOPE, STAGE_ZEROCUT,
        STAGE_OUTPUT,
    )
    # Gate + Arming merged into Wake; Smoothing + Texture into Envelope.
    expected = (
        STAGE_INPUT, STAGE_DEPTH, STAGE_SPEED, STAGE_PUNCH,
        STAGE_COMBINE, STAGE_WAKE, STAGE_ENVELOPE, STAGE_ZEROCUT,
        STAGE_OUTPUT,
    )
    assert _STAGE_ORDER == expected
    # Every stage has a human-readable label.
    for sid in _STAGE_ORDER:
        assert sid in _STAGE_LABELS and _STAGE_LABELS[sid]
    # Stage IDs are unique.
    assert len(set(_STAGE_ORDER)) == len(_STAGE_ORDER)


def test_storage_helpers_round_trip():
    """Helpers read from and write back to a stand-in controller's
    in-memory profile dict. Verifies the chains-list shape is
    respected and that chain_idx defaults to 0 for backward compat."""
    from ui.motor_signal_chain import (
        _read_chain, _update_chain_field, _reset_chain_to_defaults,
        _default_chain, _default_mix,
    )

    ctrl = StubController()
    ctrl.profiles = {"DevX": {}}

    # First read on a fresh profile → default chain.
    chain = _read_chain(ctrl, "DevX", 0)
    assert chain == _default_chain()

    # Write a depth.gain change and read it back. chain_idx must be
    # passed explicitly under the Cut 5 signature.
    _update_chain_field(ctrl, "DevX", 0, 0, ("depth", "gain"), 0.42)
    chain = _read_chain(ctrl, "DevX", 0, 0)
    assert chain["depth"]["gain"] == 0.42
    # The recalc is live (the drag must stay responsive on the toy)...
    assert ctrl.recalced >= 1
    # ...but the DISK write is debounced — a slider drag used to fsync
    # profiles.json once per integer step. Nothing saved synchronously;
    # flushing the debouncer performs exactly the coalesced save.
    from ui import motor_signal_chain as _msc
    assert ctrl.saved == 0
    _msc._save_debouncer._flush()
    assert ctrl.saved == 1

    # The full mix block now exists in the chains-list shape.
    mix = ctrl.profiles["DevX"]["mix"]["0"]
    assert isinstance(mix.get("chains"), list)
    assert len(mix["chains"]) == 1
    assert mix["chains"][0]["depth"]["gain"] == 0.42
    assert mix.get("merge") in ("add", "max", "multiply")

    # Reset on chain 0 wipes that chain back to default; the rest of
    # the mix block (merge field) stays.
    _reset_chain_to_defaults(ctrl, "DevX", 0, 0)
    chain = _read_chain(ctrl, "DevX", 0)
    assert chain == _default_chain()


def test_update_chain_field_writes_nested_subfield():
    """Nested-path writes don't blow away sibling fields — a stage's
    keys must coexist after individual writes."""
    from ui.motor_signal_chain import _read_chain, _update_chain_field

    ctrl = StubController()
    _update_chain_field(ctrl, "DevY", 0, 0, ("smoothing", "rise_ms"), 120.0)
    _update_chain_field(ctrl, "DevY", 0, 0, ("smoothing", "fall_ms"), 60.0)
    _update_chain_field(ctrl, "DevY", 0, 0, ("texture", "enabled"), True)
    chain = _read_chain(ctrl, "DevY", 0)
    assert chain["smoothing"]["rise_ms"] == 120.0
    assert chain["smoothing"]["fall_ms"] == 60.0
    assert chain["texture"]["enabled"] is True


def test_update_wake_fields_write_without_clobbering_siblings():
    """Wake writes land under `wake` and accumulate — each one is a
    read-modify-write, so an earlier field must survive the next."""
    from ui.motor_signal_chain import (
        _read_chain, _update_wake_field, _update_chain_field,
    )
    ctrl = StubController()
    _update_chain_field(ctrl, "DevY", 0, 0, ("depth", "gain"), 0.4)
    _update_wake_field(ctrl, "DevY", 0, 0, "enabled", True)
    _update_wake_field(ctrl, "DevY", 0, 0, "mode", "strokes")
    _update_wake_field(ctrl, "DevY", 0, 0, "thrusts", 5)
    chain = _read_chain(ctrl, "DevY", 0)
    assert chain["wake"]["enabled"] is True
    assert chain["wake"]["mode"] == "strokes"
    assert chain["wake"]["thrusts"] == 5
    # A non-wake stage written before the wake edits is untouched.
    assert chain["depth"]["gain"] == 0.4


def test_read_wake_cfg_backfills_defaults():
    """_read_wake_cfg seeds the Wake card from the chain's `wake` block,
    backfilling the canonical defaults for any missing key."""
    from ui.motor_signal_chain import _read_wake_cfg
    merged = _read_wake_cfg({"wake": {"enabled": True, "mode": "strokes",
                                      "thrusts": 4}})
    assert merged["enabled"] is True
    assert merged["mode"] == "strokes"
    assert merged["thrusts"] == 4
    # Backfilled default keys present even though the input omitted them.
    assert "sleep_delay_s" in merged and "window_s" in merged
    # A pre-`source` config backfills the depth-weighted default.
    assert merged["source"] == "both"
    # A chain with no wake block reads as the canonical default.
    empty = _read_wake_cfg({})
    assert empty["enabled"] is False and empty["mode"] == "activity"
    assert empty["source"] == "both"


def test_wake_source_segmented_writes_config():
    """The Wake editor's Activity 'Source' segmented maps its buttons onto
    wake.source depth/speed/both."""
    _qt_app()
    from PySide6.QtWidgets import QPushButton
    from ui.motor_signal_chain import MotorSignalChainWidget, _read_chain
    ui = _SmokeUI(_SmokeController())
    w = MotorSignalChainWidget(ui, "DevX", 0, "vibrate")
    ed = w._build_wake_editor()
    btns = {b.text(): b for b in ed.findChildren(QPushButton)}
    assert {"Depth", "Speed", "Both"} <= set(btns)

    btns["Depth"].click()
    assert _read_chain(ui.controller, "DevX", 0, 0)["wake"]["source"] == "depth"
    btns["Speed"].click()
    assert _read_chain(ui.controller, "DevX", 0, 0)["wake"]["source"] == "speed"
    btns["Both"].click()
    assert _read_chain(ui.controller, "DevX", 0, 0)["wake"]["source"] == "both"
    w.teardown()


# ============================================================ Cut 5: chain list

def test_chain_count_defaults_to_one():
    """A profile without a `mix` block reports count = 1 — the
    router treats it as a single default chain, and the UI mirrors."""
    from ui.motor_signal_chain import _get_chain_count
    ctrl = StubController()
    assert _get_chain_count(ctrl, "DevZ", 0) == 1


def test_add_chain_grows_until_the_cap():
    """Adding chains grows the list up to MAX_CHAINS_PER_MOTOR, then the
    next add is refused. The cap is 6 so Touch and Penetration (the two
    a motor ships with) leave room for the other contact types."""
    from ui.motor_signal_chain import (
        _add_chain, _get_chain_count, MAX_CHAINS_PER_MOTOR,
    )
    ctrl = StubController()
    assert _get_chain_count(ctrl, "Dev", 0) == 1
    for expected in range(2, MAX_CHAINS_PER_MOTOR + 1):
        assert _add_chain(ctrl, "Dev", 0) is True
        assert _get_chain_count(ctrl, "Dev", 0) == expected
    assert _add_chain(ctrl, "Dev", 0) is False
    assert _get_chain_count(ctrl, "Dev", 0) == MAX_CHAINS_PER_MOTOR


def test_remove_chain_refuses_to_drop_below_one():
    """Single-chain motors stay single — remove on the only chain
    is a no-op so the user can't end up with zero chains."""
    from ui.motor_signal_chain import _remove_chain, _get_chain_count
    ctrl = StubController()
    assert _remove_chain(ctrl, "Dev", 0, 0) is False
    assert _get_chain_count(ctrl, "Dev", 0) == 1


def test_remove_chain_shrinks_to_one():
    from ui.motor_signal_chain import (
        _add_chain, _remove_chain, _get_chain_count,
    )
    ctrl = StubController()
    _add_chain(ctrl, "Dev", 0)
    assert _get_chain_count(ctrl, "Dev", 0) == 2
    assert _remove_chain(ctrl, "Dev", 0, 1) is True
    assert _get_chain_count(ctrl, "Dev", 0) == 1


def test_per_chain_writes_are_isolated():
    """Editing chain 1's depth.gain must not affect chain 0's, and
    vice versa. Round-trips through _update_chain_field with both
    chain indices."""
    from ui.motor_signal_chain import (
        _add_chain, _update_chain_field, _read_chain,
    )
    ctrl = StubController()
    _add_chain(ctrl, "Dev", 0)
    _update_chain_field(ctrl, "Dev", 0, 0, ("depth", "gain"), 0.3)
    _update_chain_field(ctrl, "Dev", 0, 1, ("depth", "gain"), 1.7)
    c0 = _read_chain(ctrl, "Dev", 0, 0)
    c1 = _read_chain(ctrl, "Dev", 0, 1)
    assert c0["depth"]["gain"] == 0.3
    assert c1["depth"]["gain"] == 1.7


def test_merge_op_round_trips():
    """The merge field accepts only add/max/multiply; reads default
    to 'max' when the field is absent or invalid."""
    from ui.motor_signal_chain import _get_merge_op, _set_merge_op
    ctrl = StubController()
    assert _get_merge_op(ctrl, "Dev", 0) == "max"
    _set_merge_op(ctrl, "Dev", 0, "add")
    assert _get_merge_op(ctrl, "Dev", 0) == "add"
    _set_merge_op(ctrl, "Dev", 0, "multiply")
    assert _get_merge_op(ctrl, "Dev", 0) == "multiply"
    # Garbage op silently ignored.
    _set_merge_op(ctrl, "Dev", 0, "garbage")
    assert _get_merge_op(ctrl, "Dev", 0) == "multiply"


def test_reset_chain_does_not_touch_other_chain():
    """Resetting chain 0 leaves chain 1 alone, and vice versa."""
    from ui.motor_signal_chain import (
        _add_chain, _update_chain_field, _reset_chain_to_defaults,
        _read_chain, _default_chain,
    )
    ctrl = StubController()
    _add_chain(ctrl, "Dev", 0)
    _update_chain_field(ctrl, "Dev", 0, 0, ("depth", "gain"), 0.3)
    _update_chain_field(ctrl, "Dev", 0, 1, ("depth", "gain"), 1.7)
    _reset_chain_to_defaults(ctrl, "Dev", 0, 0)
    c0 = _read_chain(ctrl, "Dev", 0, 0)
    c1 = _read_chain(ctrl, "Dev", 0, 1)
    assert c0 == _default_chain()
    assert c1["depth"]["gain"] == 1.7


# ============================================================ Cut 6: per-stage graph traces

def test_stage_trace_mapping_matches_doc():
    """Every stage has at least one trace and references only known
    trace ids. Locks the mapping from docs/CHAIN_INLINED_TUNING.md so a
    typo in the stage table breaks tests."""
    from ui.motor_signal_chain import (
        _STAGE_ORDER, _STAGE_TRACES, _TRACE_STYLE,
    )
    known_traces = set(_TRACE_STYLE.keys())
    for stage in _STAGE_ORDER:
        traces = _STAGE_TRACES.get(stage, ())
        assert len(traces) >= 1, f"stage {stage} has no traces"
        for tid in traces:
            assert tid in known_traces, f"unknown trace id '{tid}' in stage {stage}"


def test_trace_spec_returns_tuple_for_known_id():
    from ui.motor_signal_chain import _trace_spec
    spec = _trace_spec("d_raw")
    assert spec[0] == "d_raw"
    assert isinstance(spec[1], str)         # color
    assert isinstance(spec[2], dict)        # style


# ============================================================ Cut 7f: border color lerp

def test_stage_level_trace_mapping_complete():
    """Every stage has a level trace assigned for the border colour."""
    from ui.motor_signal_chain import _STAGE_ORDER, _STAGE_LEVEL_TRACE, _TRACE_STYLE
    known_traces = set(_TRACE_STYLE.keys())
    for stage in _STAGE_ORDER:
        assert stage in _STAGE_LEVEL_TRACE, f"stage {stage} has no level trace"
        assert _STAGE_LEVEL_TRACE[stage] in known_traces


def test_lerp_purple_pink_endpoints():
    """0 → low color, 1 → high color. Linear interpolation in between."""
    from PySide6.QtGui import QColor
    from ui.motor_signal_chain import (
        MotorSignalChainWidget, _STAGE_BORDER_LOW, _STAGE_BORDER_HIGH,
    )
    lo = QColor(_STAGE_BORDER_LOW)
    hi = QColor(_STAGE_BORDER_HIGH)
    at_zero = MotorSignalChainWidget._lerp_purple_pink(0.0)
    at_one = MotorSignalChainWidget._lerp_purple_pink(1.0)
    assert (at_zero.red(), at_zero.green(), at_zero.blue()) == (lo.red(), lo.green(), lo.blue())
    assert (at_one.red(), at_one.green(), at_one.blue()) == (hi.red(), hi.green(), hi.blue())


def test_lerp_purple_pink_clamps():
    """Out-of-range levels clamp to the endpoints, not extrapolate."""
    from PySide6.QtGui import QColor
    from ui.motor_signal_chain import (
        MotorSignalChainWidget, _STAGE_BORDER_LOW, _STAGE_BORDER_HIGH,
    )
    lo = QColor(_STAGE_BORDER_LOW)
    hi = QColor(_STAGE_BORDER_HIGH)
    below = MotorSignalChainWidget._lerp_purple_pink(-0.5)
    above = MotorSignalChainWidget._lerp_purple_pink(1.7)
    assert (below.red(), below.green(), below.blue()) == (lo.red(), lo.green(), lo.blue())
    assert (above.red(), above.green(), above.blue()) == (hi.red(), hi.green(), hi.blue())


def test_lerp_purple_pink_midpoint_is_between():
    """At t=0.5 the result is the channel-wise midpoint of the endpoints."""
    from PySide6.QtGui import QColor
    from ui.motor_signal_chain import (
        MotorSignalChainWidget, _STAGE_BORDER_LOW, _STAGE_BORDER_HIGH,
    )
    lo = QColor(_STAGE_BORDER_LOW)
    hi = QColor(_STAGE_BORDER_HIGH)
    mid = MotorSignalChainWidget._lerp_purple_pink(0.5)
    # ±1 fudge for int truncation in the lerp.
    assert abs(mid.red()   - (lo.red()   + hi.red())   // 2) <= 1
    assert abs(mid.green() - (lo.green() + hi.green()) // 2) <= 1
    assert abs(mid.blue()  - (lo.blue()  + hi.blue())  // 2) <= 1


# ============================================================ Cut 7h: valve indicator

def test_valve_indicator_default_state():
    """Fresh ValveIndicator starts at closed (position 0)."""
    # PySide6 widgets need a QApplication — fixture below.
    from PySide6.QtWidgets import QApplication
    import sys
    app = QApplication.instance() or QApplication(sys.argv)
    from ui.motor_signal_chain import ValveIndicator
    v = ValveIndicator()
    assert v._target == 0.0
    assert v._current == 0.0


def test_valve_indicator_set_open_changes_target():
    from PySide6.QtWidgets import QApplication
    import sys
    app = QApplication.instance() or QApplication(sys.argv)
    from ui.motor_signal_chain import ValveIndicator
    v = ValveIndicator()
    v.set_open(True)
    assert v._target == 1.0
    v.set_open(False)
    assert v._target == 0.0


def test_valve_indicator_idempotent_set_open():
    """Calling set_open with the same value twice is a no-op for the
    animation timer (no spurious restart)."""
    from PySide6.QtWidgets import QApplication
    import sys
    app = QApplication.instance() or QApplication(sys.argv)
    from ui.motor_signal_chain import ValveIndicator
    v = ValveIndicator()
    v.set_open(True)
    # Force the lerp to converge so the timer stops.
    while v._current != v._target:
        v._tick()
    # Now the timer should be inactive.
    assert not v._anim_timer.isActive()
    # Re-asserting the same target shouldn't restart it.
    v.set_open(True)
    assert not v._anim_timer.isActive()


# ============================================================ Cut 9: accordion strip


def _qt_app():
    """Shared QApplication for the widget tests (Qt needs one)."""
    from PySide6.QtWidgets import QApplication
    import sys
    return QApplication.instance() or QApplication(sys.argv)


def test_gain_slider_float_int_mapping():
    """The quick gain slider maps gain 0.0..2.0 onto the int track
    0..200 (1 step == 0.01) and clamps out-of-range gains."""
    _qt_app()
    from ui.motor_signal_chain import _GainSlider, _GAIN_SLIDER_MAX
    s = _GainSlider(1.0)
    assert s.maximum() == _GAIN_SLIDER_MAX
    assert s.value() == 100
    assert s.gain() == 1.0
    s.set_gain(0.5)
    assert s.value() == 50
    s.set_gain(1.5)
    assert s.value() == 150
    # Clamp above/below the 0..2 range.
    s.set_gain(5.0)
    assert s.value() == _GAIN_SLIDER_MAX
    s.set_gain(-1.0)
    assert s.value() == 0


def test_gain_slider_ticks_and_not_snapped_unless_dragging():
    """Tick marks render at 0.5/1.0/1.5. When the handle is NOT being
    dragged (programmatic / keyboard-style changes), values pass through
    un-snapped — even one sitting right next to a detent."""
    from PySide6.QtWidgets import QSlider
    _qt_app()
    from ui.motor_signal_chain import _GainSlider, _GAIN_TICK_INTERVAL
    s = _GainSlider(1.0)
    assert s.tickPosition() == QSlider.TicksBelow
    assert s.tickInterval() == _GAIN_TICK_INTERVAL
    # Not dragging → exact value kept, even an odd one or one near a detent.
    s.setValue(137)
    assert s.value() == 137
    assert abs(s.gain() - 1.37) < 1e-9
    s.setValue(103)            # 3 away from the 1.0 detent, but no drag
    assert s.value() == 103


def test_gain_slider_snaps_while_dragging():
    """While the handle is held (isSliderDown), a value within the snap
    radius of a detent sticks to it; values outside the radius are kept,
    so in-between gains are still reachable by drag."""
    _qt_app()
    from ui.motor_signal_chain import _GainSlider, _GAIN_SNAP_RADIUS
    s = _GainSlider(1.0)
    s.setSliderDown(True)
    s.setValue(100 + _GAIN_SNAP_RADIUS)      # just inside → snaps to 1.0
    assert s.value() == 100
    s.setValue(50 - _GAIN_SNAP_RADIUS)       # just inside → snaps to 0.5
    assert s.value() == 50
    s.setValue(80)                           # between detents → no snap
    assert s.value() == 80
    s.setValue(2)                            # near the bottom → snaps to 0
    assert s.value() == 0
    s.setSliderDown(False)


def test_gain_slider_emits_on_user_change_not_on_set_gain():
    """`set_gain` is silent (blockSignals); a value change emits the
    float gain so the parent can persist + mirror the spinbox."""
    _qt_app()
    from ui.motor_signal_chain import _GainSlider
    s = _GainSlider(1.0)
    seen = []
    s.gainChanged.connect(seen.append)
    s.set_gain(0.25)          # programmatic → no echo
    assert seen == []
    s.setValue(80)            # user-style change → emits
    assert seen and abs(seen[-1] - 0.8) < 1e-9


def test_gain_control_readout_tracks_value():
    """The inline readout shows ×<gain> and updates on both user drags
    and programmatic set_gain; set_gain stays silent (no echo)."""
    _qt_app()
    from ui.motor_signal_chain import _GainControl
    c = _GainControl(1.0)
    assert c._value.text() == "×1.00"
    assert c.gain() == 1.0
    seen = []
    c.gainChanged.connect(seen.append)
    # Programmatic set (spinbox mirror / reset): readout updates, silent.
    c.set_gain(0.5)
    assert c._value.text() == "×0.50"
    assert c.gain() == 0.5
    assert seen == []
    # User-style slider change: readout updates AND the signal fires.
    c._slider.setValue(150)
    assert c._value.text() == "×1.50"
    assert seen and abs(seen[-1] - 1.5) < 1e-9


def test_ms_slider_mapping_and_snap():
    """The smoothing delay slider's track is milliseconds directly; it
    clamps to the range and drag-snaps to the 100-ms detents."""
    _qt_app()
    from ui.motor_signal_chain import _MsSlider, _MS_SLIDER_MAX, _MS_SNAP_RADIUS
    s = _MsSlider(120)
    assert s.value() == 120
    assert s.ms() == 120
    s.set_ms(250)
    assert s.value() == 250
    s.set_ms(99999)                          # clamps to the max
    assert s.value() == _MS_SLIDER_MAX
    s.setSliderDown(True)
    s.setValue(200 + _MS_SNAP_RADIUS)        # inside radius → snaps to 200
    assert s.value() == 200
    s.setValue(160)                          # between detents → kept
    assert s.value() == 160
    s.setSliderDown(False)


def test_delay_control_readout():
    """The delay control shows "<ms>ms", updates on set_ms (silently), and
    emits msChanged on a user slider change."""
    _qt_app()
    from ui.motor_signal_chain import _DelayControl
    c = _DelayControl(50)
    assert c._value.text() == "50ms"
    assert c.ms() == 50
    seen = []
    c.msChanged.connect(seen.append)
    c.set_ms(120)                            # programmatic → silent
    assert c._value.text() == "120ms"
    assert seen == []
    c._slider.setValue(300)                  # user-style → emits
    assert c._value.text() == "300ms"
    assert seen and seen[-1] == 300


def test_stage_card_defaults_collapsed():
    """A fresh card is collapsed: editor not built, quick region shown,
    editor region hidden + zero-height, output number is the em-dash
    placeholder."""
    _qt_app()
    from ui.motor_signal_chain import _StageCard
    card = _StageCard("speed", "Speed", "Spd")
    assert card.editor_built() is False
    assert card.editor_region().isVisibleTo(card) is False
    assert card.quick_region().isVisibleTo(card) is True
    assert card.editor_region().maximumHeight() == 0
    assert card._out_label.text() == "—"


def test_stage_card_apply_state_transitions():
    """rail → short title, quick + number hidden; expanded → editor
    shown, full title; quick → quick + number shown, editor hidden."""
    _qt_app()
    from ui.motor_signal_chain import (
        _StageCard, _CARD_RAIL, _CARD_QUICK, _CARD_EXPANDED,
    )
    card = _StageCard("combine", "Combine", "Cmb")

    card.apply_state(_CARD_RAIL)
    assert card._title.text() == "Cmb"
    assert card._out_label.isVisibleTo(card) is False
    assert card.quick_region().isVisibleTo(card) is False
    assert card.editor_region().isVisibleTo(card) is False

    card.apply_state(_CARD_EXPANDED)
    assert card._title.text() == "Combine"
    assert card.editor_region().isVisibleTo(card) is True
    assert card.quick_region().isVisibleTo(card) is False

    card.apply_state(_CARD_QUICK)
    assert card._title.text() == "Combine"
    assert card.quick_region().isVisibleTo(card) is True
    assert card.editor_region().isVisibleTo(card) is False


def test_stage_card_output_number_format_and_gate():
    """Output number formats to 2dp, clamps to [0,1], and is gated so a
    sub-epsilon change doesn't rewrite the label."""
    _qt_app()
    from ui.motor_signal_chain import _StageCard
    card = _StageCard("output", "Output", "Out")
    card.set_output_number(0.42)
    assert card._out_label.text() == "0.42"
    # Sub-epsilon change is ignored (label unchanged).
    card.set_output_number(0.421)
    assert card._out_label.text() == "0.42"
    # A real change updates.
    card.set_output_number(0.5)
    assert card._out_label.text() == "0.50"
    # Clamp above 1.0.
    card.set_output_number(1.7)
    assert card._out_label.text() == "1.00"


# --- Full-widget smoke test (headless) --------------------------------
# The app can't be launched in CI/sandbox, so this drives the whole
# MotorSignalChainWidget through build → expand → live-data → collapse
# against a stub controller/UI. The QVariantAnimation never ticks
# without an event loop, so we settle it by hand via _on_anim_done.

class _SmokeRouter:
    def subscribe_intermediates(self, *a, **k):
        pass

    def unsubscribe_intermediates(self, *a, **k):
        pass


class _SmokeController:
    def __init__(self):
        self.profiles = {"DevX": {}}
        self.motor_router = _SmokeRouter()

    def get_profile_config(self, device, key, default=None):
        return self.profiles.get(device, {}).get(key, default)

    def update_device_config(self, device, key, value):
        self.profiles.setdefault(device, {})[key] = value

    def save_profiles(self):
        pass

    def force_recalculate(self):
        pass

    def get_active_profile_dict(self):
        return self.profiles


class _SmokeUI:
    def __init__(self, controller):
        self.controller = controller

    def _repolish(self, _w):
        pass

    def _build_listening_to_column(self, *_a, **_k):
        from PySide6.QtWidgets import QLabel
        return QLabel("listening")

    def _explain(self, target, title, text):
        # The real helper: the editors' explanations land as tooltips.
        from ui.tooltips import explain
        explain(target, title, text)


def test_widget_build_expand_intermediates_collapse():
    _qt_app()
    from ui.motor_signal_chain import MotorSignalChainWidget, STAGE_COMBINE

    ui = _SmokeUI(_SmokeController())
    w = MotorSignalChainWidget(ui, "DevX", 0, "vibrate")

    # Built collapsed: 7 horizontal slots, 9 stage cards (Depth+Speed+
    # Punch share a slot; Gate+Arming merged into Wake, Smoothing+Texture
    # into Envelope), nothing expanded.
    assert len(w._slots) == 7
    assert len(w._stage_cards) == 9
    assert w._active_stage is None
    # 7 slots interleaved with 6 flexible connector cells (connector before
    # every slot except the first) — the cells the stretching arrows are
    # drawn across.
    assert w._strip_lay.count() == 13
    # Input forks into Depth+Speed+Punch and they join into Combine: the
    # parallel ds slot (index 1) is registered with its three inner cards.
    assert w._strip_host._branch_index == 1
    assert len(w._strip_host._branch_cards) == 3
    # Envelope has a quick delay slider (like Depth/Speed's gain slider).
    assert w._delay_control is not None

    # Exercise the connector paint path (incl. the fork/join branch arrows)
    # headlessly — a geometry/paint crash (bad mapTo, polygon, etc.) raises.
    from PySide6.QtGui import QPixmap
    w._strip_host.resize(900, 160)
    w._strip_host.layout().activate()
    w._strip_host.render(QPixmap(w._strip_host.size()))

    # Expand Combine: editor builds lazily and the card flips to expanded.
    w._on_stage_clicked(STAGE_COMBINE)
    assert w._active_stage == STAGE_COMBINE
    combine = w._stage_cards[STAGE_COMBINE]
    assert combine.editor_built() is True
    assert combine.editor_region().isVisibleTo(combine) is True
    w._on_anim_done()  # settle the (un-ticked) animation

    # A live payload drives the per-stage output number (combine ← "mixed").
    w._handle_intermediates({"t_ms": 1000.0, "mixed": 0.5})
    assert combine._out_label.text() == "0.50"

    # Clicking the expanded card again collapses the strip.
    w._on_stage_clicked(STAGE_COMBINE)
    w._on_anim_done()
    assert w._active_stage is None

    w.teardown()


def test_output_stage_round_trips_through_the_helpers():
    """The Output stage (gain + the toy's usable band) lives inside each
    chain, so a two-chain motor can calibrate its halves separately."""
    from ui.motor_signal_chain import (
        _get_output_stage, _set_output_field, OUTPUT_GAIN_MAX,
    )
    ctrl = StubController()
    # Absent key reads as untouched: unity gain, full range.
    assert _get_output_stage(ctrl, "DevX", 0) == (1.0, 0.0, 1.0)
    _set_output_field(ctrl, "DevX", 0, 0, "gain", 0.6)
    _set_output_field(ctrl, "DevX", 0, 0, "min", 0.2)
    _set_output_field(ctrl, "DevX", 0, 0, "max", 0.8)
    assert _get_output_stage(ctrl, "DevX", 0) == (0.6, 0.2, 0.8)
    stored = ctrl.profiles["DevX"]["mix"]["0"]["chains"][0]["output"]
    assert stored == {"gain": 0.6, "min": 0.2, "max": 0.8}
    # Per chain, not per motor — and per motor, not per device.
    assert _get_output_stage(ctrl, "DevX", 0, 1) == (1.0, 0.0, 1.0)
    assert _get_output_stage(ctrl, "DevX", 1) == (1.0, 0.0, 1.0)
    # Clamped both ends; junk falls back to untouched rather than raising.
    _set_output_field(ctrl, "DevX", 0, 0, "gain", 99.0)
    assert _get_output_stage(ctrl, "DevX", 0)[0] == OUTPUT_GAIN_MAX
    _set_output_field(ctrl, "DevX", 0, 0, "gain", -5.0)
    assert _get_output_stage(ctrl, "DevX", 0)[0] == 0.0
    _set_output_field(ctrl, "DevX", 0, 0, "max", 7.0)
    assert _get_output_stage(ctrl, "DevX", 0)[2] == 1.0
    ctrl.profiles["DevX"]["mix"]["0"]["chains"][0]["output"]["gain"] = "loud"
    assert _get_output_stage(ctrl, "DevX", 0)[0] == 1.0
    # An inverted band reads as collapsed to the ceiling, matching the
    # router rather than emitting a negative span.
    ctrl.profiles["DevX"]["mix"]["0"]["chains"][0]["output"].update(
        {"min": 0.9, "max": 0.4})
    assert _get_output_stage(ctrl, "DevX", 0)[1:] == (0.4, 0.4)


def test_output_stage_editor_writes_and_labels_the_card():
    """Building the Output stage editor gives every motor kind the level
    block, and a calibrated chain advertises it on the collapsed card."""
    _qt_app()
    from ui.motor_signal_chain import (
        MotorSignalChainWidget, STAGE_OUTPUT, _get_output_stage,
        _set_output_field,
    )
    ui = _SmokeUI(_SmokeController())
    w = MotorSignalChainWidget(ui, "DevX", 0, "vibrate")
    # Untouched: the subtitle still describes the motor kind.
    assert w._summary_for_stage(STAGE_OUTPUT) == "vib"

    w._on_stage_clicked(STAGE_OUTPUT)
    w._on_anim_done()
    assert w._stage_cards[STAGE_OUTPUT].editor_built() is True

    w._build_output_level_block()   # builds without a live parent
    _set_output_field(ui.controller, "DevX", 0, 0, "gain", 0.7)
    assert _get_output_stage(ui.controller, "DevX", 0)[0] == 0.7
    # A trimmed chain says so — an unexplained quiet toy is worth more
    # than three characters of motor kind.
    assert w._summary_for_stage(STAGE_OUTPUT) == "×0.70"
    # A narrowed band wins the slot: it decides what the toy can reach.
    _set_output_field(ui.controller, "DevX", 0, 0, "min", 0.2)
    _set_output_field(ui.controller, "DevX", 0, 0, "max", 0.8)
    assert w._summary_for_stage(STAGE_OUTPUT) == "20–80%"


def test_output_range_spinboxes_cannot_be_inverted():
    """The two range spinboxes bound each other live, so the band can
    never be inverted from the UI — no silent clamp-on-save to explain."""
    _qt_app()
    from PySide6.QtWidgets import QDoubleSpinBox
    from ui.motor_signal_chain import (
        MotorSignalChainWidget, _get_output_stage, _set_output_field,
    )
    ui = _SmokeUI(_SmokeController())
    _set_output_field(ui.controller, "DevX", 0, 0, "min", 0.2)
    _set_output_field(ui.controller, "DevX", 0, 0, "max", 0.8)
    w = MotorSignalChainWidget(ui, "DevX", 0, "vibrate")
    block = w._build_output_level_block()
    spins = block.findChildren(QDoubleSpinBox)
    assert len(spins) == 2
    min_spin, max_spin = spins
    assert (min_spin.value(), max_spin.value()) == (20.0, 80.0)
    # Neither can cross the other.
    assert min_spin.maximum() == 80.0
    assert max_spin.minimum() == 20.0
    # Moving the ceiling drags the floor's headroom with it, and writes.
    max_spin.setValue(50.0)
    assert min_spin.maximum() == 50.0
    assert _get_output_stage(ui.controller, "DevX", 0)[2] == pytest.approx(0.5)
    # A floor pushed at the ceiling stops there rather than inverting.
    min_spin.setValue(90.0)
    assert min_spin.value() == 50.0
    assert _get_output_stage(ui.controller, "DevX", 0)[1] == pytest.approx(0.5)
    w.teardown()


def test_directional_stages_get_two_quick_sliders():
    """Speed and Punch are directional, so their collapsed cards carry a
    slider per stroke direction; Depth keeps its single one."""
    _qt_app()
    from ui.motor_signal_chain import (
        MotorSignalChainWidget, STAGE_DEPTH, STAGE_SPEED, STAGE_PUNCH,
    )
    ui = _SmokeUI(_SmokeController())
    w = MotorSignalChainWidget(ui, "DevX", 0, "vibrate")
    keys = set(w._gain_sliders)
    assert STAGE_DEPTH in keys
    assert f"{STAGE_DEPTH}|out" not in keys
    for stage in (STAGE_SPEED, STAGE_PUNCH):
        assert stage in keys, f"{stage} missing its inward slider"
        assert f"{stage}|out" in keys, f"{stage} missing its outward slider"
    w.teardown()


def test_gain_field_maps_sync_keys_to_config_fields():
    from ui.motor_signal_chain import MotorSignalChainWidget as W
    assert W._gain_field("speed") == ("speed", "gain")
    assert W._gain_field("speed|out") == ("speed", "gain_out")
    assert W._gain_field("punch|out") == ("punch", "gain_out")
    assert W._gain_field("depth") == ("depth", "gain")


def test_outward_quick_slider_writes_gain_out():
    """The two sliders must land in different config fields — a shared
    write would make them silently mirror each other."""
    _qt_app()
    from ui.motor_signal_chain import (
        MotorSignalChainWidget, STAGE_SPEED, _read_chain,
    )
    ui = _SmokeUI(_SmokeController())
    w = MotorSignalChainWidget(ui, "DevX", 0, "vibrate")
    w._gain_sliders[STAGE_SPEED]._slider.setValue(120)
    w._gain_sliders[f"{STAGE_SPEED}|out"]._slider.setValue(40)
    speed = _read_chain(ui.controller, "DevX", 0, 0)["speed"]
    assert speed["gain"] == pytest.approx(1.2)
    assert speed["gain_out"] == pytest.approx(0.4)
    w.teardown()


def test_speed_outward_slider_seeds_from_the_inward_gain():
    """An existing chain has no gain_out; the outward slider must open at
    the inward value, matching how the router reads it — not at 1.0."""
    _qt_app()
    from ui.motor_signal_chain import (
        MotorSignalChainWidget, STAGE_SPEED, STAGE_PUNCH,
        _update_chain_field,
    )
    ui = _SmokeUI(_SmokeController())
    _update_chain_field(ui.controller, "DevX", 0, 0, ("speed", "gain"), 0.35)
    w = MotorSignalChainWidget(ui, "DevX", 0, "vibrate")
    assert w._gain_sliders[f"{STAGE_SPEED}|out"].gain() == pytest.approx(0.35)
    # Punch is the opposite: its outward half is new, so it starts muted.
    assert w._gain_sliders[f"{STAGE_PUNCH}|out"].gain() == pytest.approx(0.0)
    w.teardown()


def test_directional_editors_register_both_spinboxes():
    """Expanding Speed or Punch builds a gain spinbox per direction, each
    two-way synced with its own quick slider."""
    _qt_app()
    from ui.motor_signal_chain import (
        MotorSignalChainWidget, STAGE_SPEED, STAGE_PUNCH, _read_chain,
    )
    ui = _SmokeUI(_SmokeController())
    w = MotorSignalChainWidget(ui, "DevX", 0, "vibrate")
    for stage in (STAGE_SPEED, STAGE_PUNCH):
        w._on_stage_clicked(stage)
        w._on_anim_done()
        assert stage in w._gain_spins
        assert f"{stage}|out" in w._gain_spins
        # The outward spinbox writes gain_out and mirrors its slider.
        w._gain_spins[f"{stage}|out"].setValue(0.75)
        assert _read_chain(ui.controller, "DevX", 0, 0)[stage]["gain_out"] \
            == pytest.approx(0.75)
        assert w._gain_sliders[f"{stage}|out"].gain() == pytest.approx(0.75)
        w._on_stage_clicked(stage)
        w._on_anim_done()
    w.teardown()


def test_directional_stage_traces_show_both_halves():
    """Each directional card draws its two shaped halves, not one merged
    line -- otherwise the asymmetry has to be inferred."""
    from ui.motor_signal_chain import (
        _STAGE_TRACES, _TRACE_STYLE, STAGE_SPEED, STAGE_PUNCH,
    )
    assert _STAGE_TRACES[STAGE_SPEED] == ("s_raw", "s_in_shaped", "s_out_shaped")
    assert _STAGE_TRACES[STAGE_PUNCH] == ("d_raw", "punch_in", "punch_out")
    for tid in ("s_in_shaped", "s_out_shaped", "punch_in", "punch_out"):
        assert tid in _TRACE_STYLE, f"{tid} has no style"
    # The two halves of a stage must be visually distinguishable.
    assert _TRACE_STYLE["s_in_shaped"][0] != _TRACE_STYLE["s_out_shaped"][0]
    assert _TRACE_STYLE["punch_in"][0] != _TRACE_STYLE["punch_out"][0]


class TestCollapsedQuickControls:
    """The collapsed card carries what you reach for mid-session; the
    expanded card keeps the full option set and the graph. Each control
    must write straight through to the chain."""

    @staticmethod
    def _widget():
        _qt_app()
        from ui.motor_signal_chain import MotorSignalChainWidget
        ui = _SmokeUI(_SmokeController())
        return ui, MotorSignalChainWidget(ui, "DevX", 0, "vibrate")

    def test_combine_button_cycles_through_the_ops(self):
        """One button, not three cells — clicking steps to the next op and
        the button relabels itself, so it is also the readout."""
        from ui.motor_signal_chain import (
            _read_chain, _COMBINE_OPS, _COMBINE_LABELS,
        )
        ui, w = self._widget()
        btn = w._combine_cycle
        assert btn is not None
        start = _read_chain(ui.controller, "DevX", 0, 0).get("combine", "max")
        order = list(_COMBINE_OPS)
        i = order.index(start)
        # A full lap returns to where it started, relabelling each step.
        for _ in range(len(order)):
            i = (i + 1) % len(order)
            btn.click()
            assert _read_chain(ui.controller, "DevX", 0, 0)["combine"] == order[i]
            assert btn.text() == _COMBINE_LABELS[order[i]]
        assert _read_chain(ui.controller, "DevX", 0, 0)["combine"] == start
        w.teardown()

    def test_combine_button_never_clips_any_label(self):
        """The pinned minimum must cover EVERY label, including the
        longest -- both clipping bugs came from sizing the button with
        hand-rolled font arithmetic that ignored the stylesheet's padding.
        Qt's sizeHint accounts for it, so the invariant is simply that the
        minimum is never smaller than the current label's hint.

        A constant minimum also means the card can't jump about as the
        button cycles."""
        from ui.motor_signal_chain import _COMBINE_OPS
        _ui, w = self._widget()
        btn = w._combine_cycle
        minimums = set()
        for _ in range(len(_COMBINE_OPS)):
            hint = btn.sizeHint()
            assert btn.minimumWidth() >= hint.width(), (
                f"{btn.text()!r} needs {hint.width()}px, "
                f"minimum is {btn.minimumWidth()}px -- would clip")
            assert btn.minimumHeight() >= hint.height(), (
                f"{btn.text()!r} needs {hint.height()}px tall, "
                f"minimum is {btn.minimumHeight()}px -- would clip "
                f"the descenders")
            minimums.add((btn.minimumWidth(), btn.minimumHeight()))
            btn.click()
        assert len(minimums) == 1, f"button resized while cycling: {minimums}"
        w.teardown()

    def test_combine_drops_its_now_redundant_subtitle(self):
        from ui.motor_signal_chain import STAGE_COMBINE
        _ui, w = self._widget()
        # The segmented control shows the op; a subtitle would repeat it.
        assert STAGE_COMBINE not in w._stage_subtitles
        w.teardown()

    def test_texture_toggles_from_the_envelope_card(self):
        from ui.motor_signal_chain import STAGE_ENVELOPE, _read_chain
        ui, w = self._widget()
        tog = w._quick_toggles[STAGE_ENVELOPE]
        assert tog.isChecked() is False           # ships off
        tog.setChecked(True)
        assert _read_chain(ui.controller, "DevX", 0, 0)["texture"]["enabled"] is True
        tog.setChecked(False)
        assert _read_chain(ui.controller, "DevX", 0, 0)["texture"]["enabled"] is False
        w.teardown()

    def test_zero_cut_toggles_from_the_card(self):
        from ui.motor_signal_chain import STAGE_ZEROCUT, _read_chain
        ui, w = self._widget()
        w._quick_toggles[STAGE_ZEROCUT].setChecked(True)
        assert _read_chain(ui.controller, "DevX", 0, 0)["zerocut"]["enabled"] is True
        w.teardown()

    def test_output_gain_slides_from_the_card(self):
        from ui.motor_signal_chain import _get_output_stage
        ui, w = self._widget()
        assert w._output_gain_quick is not None
        w._output_gain_quick._slider.setValue(140)      # 0..200 -> x0..2
        assert _get_output_stage(ui.controller, "DevX", 0)[0] == pytest.approx(1.4)
        w.teardown()

    def test_wake_quick_control_follows_the_mode(self):
        """Activity tunes a 0-1 threshold, Strokes an integer count --
        one widget cannot be both, so it is rebuilt on a mode change."""
        from ui.motor_signal_chain import (
            STAGE_WAKE, _read_chain, _update_wake_field,
        )
        ui, w = self._widget()
        # Default mode is activity -> writes wake_threshold.
        w._wake_quick._slider.setValue(30)              # 0..100 -> 0..1
        wake = _read_chain(ui.controller, "DevX", 0, 0)["wake"]
        assert wake["wake_threshold"] == pytest.approx(0.30)

        # Switch to strokes and rebuild: now it writes an integer count.
        _update_wake_field(ui.controller, "DevX", 0, 0, "mode", "strokes")
        w._rebuild_wake_quick(w._stage_cards[STAGE_WAKE])
        w._wake_quick._slider.setValue(4)               # 1..10 over 9 steps
        wake = _read_chain(ui.controller, "DevX", 0, 0)["wake"]
        assert wake["thrusts"] == 5
        assert isinstance(wake["thrusts"], int)
        w.teardown()

    def test_wake_valve_stays_last_after_a_rebuild(self):
        from ui.motor_signal_chain import STAGE_WAKE, ValveIndicator
        _ui, w = self._widget()
        card = w._stage_cards[STAGE_WAKE]
        w._rebuild_wake_quick(card)
        lay = card.quick_layout
        last = lay.itemAt(lay.count() - 1).widget()
        assert isinstance(last, ValveIndicator)
        w.teardown()

    def test_every_slot_including_sources_can_shrink(self):
        """Each slot must carry an EXPLICIT width floor, the Sources
        (Depth/Speed/Punch) container included.

        Qt regression trap: for a widget with a layout, an explicit
        minimum of 0 does not mean "may shrink" -- Qt falls back to the
        layout-derived minimumSizeHint, which for three stacked slider
        cards is ~208px. That is what left Sources as the one cluster in
        the row that would not narrow with the window while every other
        slot compressed."""
        from ui.motor_signal_chain import _CARD_COLLAPSED_MIN
        _ui, w = self._widget()
        for slot in w._slots:
            assert slot.minimumWidth() == _CARD_COLLAPSED_MIN, (
                "slot has no explicit floor, so Qt will use its "
                f"minimumSizeHint ({slot.minimumSizeHint().width()}px) "
                "and it will not shrink")
        # And the floor must actually bind: squeeze the strip and check
        # the Sources slot came down with everything else.
        w.resize(760, 300)
        w.show()
        w.layout().activate()
        w._strip_host.layout().activate()
        ds_w = w._ds_slot.width()
        assert ds_w < 200, f"Sources slot stuck at {ds_w}px"
        w.teardown()

    def test_gaps_yield_before_the_cards_do(self):
        """Priority order: the cards get the width they want, and the
        gaps take only what is left, bounded.

        Small is a size the arrows may REACH under pressure, not their
        normal state -- so a cramped row pins them at the floor and a
        roomy one opens them to the ceiling and stops, handing the rest
        back to the cards."""
        from ui.motor_signal_chain import _CONNECTOR_GAP, _CONNECTOR_GAP_MAX
        _ui, w = self._widget()
        w.show()

        def gaps_at(width):
            w.resize(width, 300)
            w.layout().activate()
            w._strip_host.resize(width, 200)
            w._strip_host.layout().activate()
            return [c.width() for c in w._connectors]

        tight = gaps_at(720)
        assert all(g == _CONNECTOR_GAP for g in tight), (
            f"cramped row should pin the gaps at the floor, got {tight}")
        roomy = gaps_at(1600)
        assert all(g == _CONNECTOR_GAP_MAX for g in roomy), (
            f"roomy row should open the gaps to the ceiling, got {roomy}")
        # ...and stop there, rather than swallowing the extra width.
        wider = gaps_at(2000)
        assert roomy == wider, "gaps kept growing past their ceiling"
        w.teardown()

    def test_slider_slots_claim_the_rows_slack(self):
        """The connector spacers are Expanding; without a matching stretch
        on the card slots every spare pixel became empty arrow gap."""
        from ui.motor_signal_chain import (
            _SLOT_STRETCH_GROWABLE, _SLOT_STRETCH_CONNECTOR,
        )
        _ui, w = self._widget()
        lay = w._strip_lay
        seen_growable = seen_connector = False
        for i in range(lay.count()):
            wd = lay.itemAt(i).widget()
            if wd is None:
                continue
            if wd in w._slots:
                if w._slot_wants_width(wd):
                    assert lay.stretch(i) == _SLOT_STRETCH_GROWABLE
                    seen_growable = True
            else:
                assert lay.stretch(i) == _SLOT_STRETCH_CONNECTOR
                seen_connector = True
        assert seen_growable and seen_connector
        w.teardown()


class TestElbowConnectors:
    """The fork/join legs route as right angles rather than diagonals, so
    the gaps between cards can collapse to almost nothing."""

    def test_arrowhead_fits_the_narrowest_gap(self):
        """A leg's head is drawn on the final segment, which at worst is
        one connector cell wide."""
        from ui.motor_signal_chain import _ELBOW_HEAD, _CONNECTOR_GAP
        assert 2 * _ELBOW_HEAD < _CONNECTOR_GAP, (
            "the arrowhead alone is wider than the narrowest gap it may "
            "be drawn in")

    def test_branch_legs_use_three_different_sides(self):
        """The three legs leave/arrive through three DIFFERENT sides of
        the shared card, not three heights of the same one: Input is
        exited top / right / bottom, Combine entered top / left /
        bottom."""
        _qt_app()
        from ui.motor_signal_chain import _StripHost
        host = _StripHost()
        out = [host._branch_side(i, 3, outgoing=True) for i in range(3)]
        assert out == ["top", "right", "bottom"]
        inn = [host._branch_side(i, 3, outgoing=False) for i in range(3)]
        assert inn == ["top", "left", "bottom"]
        # All distinct -- that is the whole point.
        assert len(set(out)) == 3 and len(set(inn)) == 3

    def test_arrowheads_point_into_the_side_they_arrive_at(self):
        """A leg arriving at Combine's top edge must point DOWN, and one
        arriving at its bottom edge UP -- otherwise the heads sit flat
        against a horizontal edge."""
        from ui.motor_signal_chain import _SIDE_ARRIVE, _SIDE_LEAVE
        assert _SIDE_ARRIVE["top"] == "down"
        assert _SIDE_ARRIVE["bottom"] == "up"
        assert _SIDE_ARRIVE["left"] == "right"
        # Leaving a side heads the opposite way to arriving at it.
        opposite = {"up": "down", "down": "up",
                    "left": "right", "right": "left"}
        for side in ("top", "bottom", "left", "right"):
            assert _SIDE_LEAVE[side] == opposite[_SIDE_ARRIVE[side]]

    def test_strip_stays_centred_when_a_stage_is_expanded(self):
        """Expanding used to switch the row to top alignment, which left
        the rails pinned up top while the parallel cards spread down --
        the fork/join legs then sprayed across the strip at unrelated
        heights. One centre line in both states keeps them meaningful."""
        from PySide6.QtCore import Qt
        from ui.motor_signal_chain import STAGE_WAKE
        _ui, w = TestCollapsedQuickControls._widget()
        w.show()
        w.resize(1200, 320)
        w.layout().activate()
        for stage in (None, STAGE_WAKE):
            w._on_stage_clicked(stage) if stage else None
            w._on_anim_done()
            lay = w._strip_lay
            for i in range(lay.count()):
                item = lay.itemAt(i)
                if item is not None and item.widget() in w._slots:
                    assert item.alignment() & Qt.AlignVCenter, (
                        f"slot not centred with active={stage}")
        w.teardown()

    def test_middle_leg_runs_flat(self):
        """The middle leg connects two cards whose centres are close but
        not equal; its anchor is pulled to the target's row so it draws
        as a straight line rather than a slight diagonal."""
        _qt_app()
        from PySide6.QtWidgets import QWidget
        from ui.motor_signal_chain import _StripHost
        host = _StripHost()
        host.resize(400, 300)
        card = QWidget(host)
        card.setGeometry(10, 40, 80, 160)      # spans y 40..200
        # A target row inside the card is honoured exactly.
        assert host._aligned_edge_anchor(card, "right", 150.0)[1] == 150.0
        # One outside is clamped back onto the edge, never off it.
        low = host._aligned_edge_anchor(card, "right", -500.0)[1]
        high = host._aligned_edge_anchor(card, "right", 5000.0)[1]
        assert 40 <= low <= 200 and 40 <= high <= 200
        assert low < high

    def test_elbow_paints_without_raising(self):
        """Qt prints exceptions from paintEvent and carries on, so a bad
        paint path passes every other test while drawing nothing. Drive
        the routine directly and let an exception fail the test."""
        _qt_app()
        from PySide6.QtGui import QPainter, QPixmap, QColor
        from ui.motor_signal_chain import _StripHost
        pm = QPixmap(200, 120)
        pm.fill()
        p = QPainter(pm)
        try:
            colour = QColor("#8899AA")
            # Every side-to-side routing the fork and join actually use.
            for leave, arrive in (("up", "right"), ("down", "right"),
                                  ("right", "right"), ("right", "down"),
                                  ("right", "up")):
                _StripHost._draw_route(p, (10, 60), (90, 25),
                                       leave, arrive, colour)
        finally:
            p.end()

    def test_full_strip_paints_without_raising(self):
        """Same guarantee for the real fork/join geometry."""
        _qt_app()
        from PySide6.QtGui import QPixmap
        from ui.motor_signal_chain import MotorSignalChainWidget
        raised = []
        import sys as _sys
        prev = _sys.excepthook
        _sys.excepthook = lambda *a: raised.append(a)
        try:
            w = MotorSignalChainWidget(_SmokeUI(_SmokeController()), "DevX",
                                       0, "vibrate")
            w.resize(1000, 220)
            w._strip_host.resize(1000, 180)
            w._strip_host.layout().activate()
            w._strip_host.render(QPixmap(w._strip_host.size()))
            w.teardown()
        finally:
            _sys.excepthook = prev
        assert not raised, f"paint raised: {raised[:1]}"


def test_smoothing_quick_slider_sets_both_rise_and_fall():
    """The Smoothing quick slider is one 'how smooth' knob — it writes the
    same delay to BOTH rise_ms and fall_ms."""
    _qt_app()
    from ui.motor_signal_chain import MotorSignalChainWidget, _read_chain
    ui = _SmokeUI(_SmokeController())
    w = MotorSignalChainWidget(ui, "DevX", 0, "vibrate")
    assert w._delay_control is not None
    w._on_delay_from_slider(200)
    chain = _read_chain(ui.controller, "DevX", 0, 0)
    assert chain["smoothing"]["rise_ms"] == 200.0
    assert chain["smoothing"]["fall_ms"] == 200.0
    w.teardown()


def test_texture_depth_follow_segmented_writes_config():
    """The Texture half's 'Depth vs movement' segmented maps its three
    buttons onto the depth_follow config values off/up/down."""
    _qt_app()
    from PySide6.QtWidgets import QPushButton
    from ui.motor_signal_chain import MotorSignalChainWidget, _read_chain
    ui = _SmokeUI(_SmokeController())
    w = MotorSignalChainWidget(ui, "DevX", 0, "vibrate")
    ed = w._build_envelope_editor()
    btns = {b.text(): b for b in ed.findChildren(QPushButton)}
    assert {"Off", "Stronger", "Weaker"} <= set(btns)

    btns["Weaker"].click()
    assert _read_chain(ui.controller, "DevX", 0, 0)["texture"]["depth_follow"] == "down"
    btns["Stronger"].click()
    assert _read_chain(ui.controller, "DevX", 0, 0)["texture"]["depth_follow"] == "up"
    btns["Off"].click()
    assert _read_chain(ui.controller, "DevX", 0, 0)["texture"]["depth_follow"] == "off"
    w.teardown()


def test_chain_subscription_follows_visibility():
    """The live-trace subscription is visibility-driven: a chain built
    hidden (collapsed toy card, non-current sidebar page) must not
    subscribe, showing subscribes, hiding unsubscribes - so off-screen
    chains cost the router zero dispatch work. Teardown stays
    idempotent on top of the hide-driven unsubscribe."""
    _qt_app()
    from ui.motor_signal_chain import MotorSignalChainWidget

    class _RecordingRouter:
        def __init__(self):
            self.subscribed = 0
            self.unsubscribed = 0

        def subscribe_intermediates(self, *a, **k):
            self.subscribed += 1

        def unsubscribe_intermediates(self, *a, **k):
            self.unsubscribed += 1

    ctrl = _SmokeController()
    router = _RecordingRouter()
    ctrl.motor_router = router
    w = MotorSignalChainWidget(_SmokeUI(ctrl), "DevX", 0, "vibrate")

    # Built hidden -> no subscription yet.
    assert router.subscribed == 0
    assert w._intermediates_subscribed is False

    w.show()
    assert router.subscribed == 1
    assert w._intermediates_subscribed is True

    w.hide()
    assert router.unsubscribed == 1
    assert w._intermediates_subscribed is False

    # Re-show resubscribes; teardown unsubscribes exactly once more.
    w.show()
    assert router.subscribed == 2
    w.teardown()
    assert router.unsubscribed == 2
    # Idempotent: neither a second teardown nor the eventual hide
    # double-unsubscribes.
    w.teardown()
    w.hide()
    assert router.unsubscribed == 2


class TestChainTypeUI:
    """A motor carries one chain per kind of contact, so the UI has to
    say which is which and let you change it."""

    @staticmethod
    def _widget(chain_idx=0):
        _qt_app()
        from ui.motor_signal_chain import MotorSignalChainWidget
        ui = _SmokeUI(_SmokeController())
        return ui, MotorSignalChainWidget(ui, "DevX", 0, "vibrate",
                                          chain_idx=chain_idx)

    def test_absent_type_reads_as_custom(self):
        from ui.motor_signal_chain import _get_chain_type
        ctrl = StubController()
        assert _get_chain_type(ctrl, "DevX", 0, 0) == "custom"

    def test_type_round_trips(self):
        from ui.motor_signal_chain import _get_chain_type, _update_chain_field
        ctrl = StubController()
        for value in ("touch", "penetration", "custom"):
            _update_chain_field(ctrl, "DevX", 0, 0, ("type",), value)
            assert _get_chain_type(ctrl, "DevX", 0, 0) == value

    def test_junk_type_falls_back_to_custom(self):
        from ui.motor_signal_chain import _get_chain_type, _update_chain_field
        ctrl = StubController()
        _update_chain_field(ctrl, "DevX", 0, 0, ("type",), "nonsense")
        assert _get_chain_type(ctrl, "DevX", 0, 0) == "custom"

    def test_card_is_named_by_its_type(self):
        """'Chain 2' says nothing about what drives it."""
        from ui.motor_signal_chain import _update_chain_field
        ui = _SmokeUI(_SmokeController())
        _qt_app()
        from ui.motor_signal_chain import MotorSignalChainWidget
        _update_chain_field(ui.controller, "DevX", 0, 0, ("type",), "touch")
        w = MotorSignalChainWidget(ui, "DevX", 0, "vibrate")
        titles = [lb.text() for lb in w.findChildren(
            __import__("PySide6.QtWidgets", fromlist=["QLabel"]).QLabel)
            if lb.objectName() == "motorCardHeader"]
        assert titles and "Touch" in titles[0], titles
        w.teardown()

    def test_type_selector_writes_and_rebuilds(self):
        from PySide6.QtWidgets import QPushButton
        from ui.motor_signal_chain import (
            STAGE_INPUT, _get_chain_type, CHAIN_TYPE_LABELS,
        )
        ui, w = self._widget()
        w._on_stage_clicked(STAGE_INPUT)
        w._on_anim_done()
        card = w._stage_cards[STAGE_INPUT]
        btns = {b.text(): b for b in card.findChildren(QPushButton)}
        assert set(CHAIN_TYPE_LABELS.values()) <= set(btns)
        btns["Touch"].click()
        assert _get_chain_type(ui.controller, "DevX", 0, 0) == "touch"
        w.teardown()


class TestChainFoldBar:
    """The super-compact face of a chain: two rows that identify it
    (name, tuning line) and show it live (stage pips, output meter)
    without opening it."""

    @staticmethod
    def _list_widget(n_chains=2, kind="vibrate"):
        _qt_app()
        from ui.motor_signal_chain import MotorChainListWidget, _add_chain
        ui = _SmokeUI(_SmokeController())
        from config_manager import preset_motor_mix
        ui.controller.profiles["DevX"] = {"mix": {"0": preset_motor_mix()}}
        for _ in range(max(0, n_chains - 2)):
            _add_chain(ui.controller, "DevX", 0)
        w = MotorChainListWidget(ui, "DevX", 0, kind)
        if n_chains != 2:
            w._rebuild()
        return ui, w

    def test_multi_chain_motor_starts_fully_folded(self):
        _ui, w = self._list_widget(2)
        assert len(w._fold_bars) == 2
        assert all(not cw.isVisibleTo(w) for cw in w._chain_widgets)

    def test_single_chain_motor_starts_open(self):
        _qt_app()
        from ui.motor_signal_chain import MotorChainListWidget
        ui = _SmokeUI(_SmokeController())          # no preset: one chain
        w = MotorChainListWidget(ui, "DevX", 0, "vibrate")
        assert len(w._fold_bars) == 1
        assert w._chain_widgets[0].isVisibleTo(w)

    def test_toggle_opens_one_and_leaves_the_other(self):
        _ui, w = self._list_widget(2)
        w._on_fold_toggled(1)
        assert not w._chain_widgets[0].isVisibleTo(w)
        assert w._chain_widgets[1].isVisibleTo(w)
        w._on_fold_toggled(1)
        assert not w._chain_widgets[1].isVisibleTo(w)

    def test_merge_picker_only_appears_beside_an_open_chain(self):
        from ui.motor_signal_chain import _get_chain_count  # noqa: F401
        _ui, w = self._list_widget(2)

        def merge_rows():
            n = 0
            for i in range(w._root_lay.count()):
                wd = w._root_lay.itemAt(i).widget()
                if wd is not None and wd.objectName() == "chainMergeRow":
                    n += 1
            return n

        assert merge_rows() == 0        # fully folded: tags, not pickers
        w._on_fold_toggled(0)
        assert merge_rows() == 1

    def test_display_name_prefers_type_then_custom_name(self):
        from ui.motor_signal_chain import (
            _chain_display_name, _update_chain_field,
        )
        ctrl = StubController()
        _update_chain_field(ctrl, "DevX", 0, 0, ("type",), "touch")
        assert _chain_display_name(ctrl, "DevX", 0, 0) == "Touch"
        # A stale name never shadows a type label.
        _update_chain_field(ctrl, "DevX", 0, 0, ("name",), "old label")
        assert _chain_display_name(ctrl, "DevX", 0, 0) == "Touch"
        _update_chain_field(ctrl, "DevX", 0, 0, ("type",), "custom")
        assert _chain_display_name(ctrl, "DevX", 0, 0) == "old label"
        _update_chain_field(ctrl, "DevX", 0, 0, ("name",), "  ")
        assert _chain_display_name(ctrl, "DevX", 0, 0) == "Chain 1"

    def test_summary_line_carries_input_and_tuning(self):
        from ui.motor_signal_chain import _chain_summary_line
        from config_manager import preset_motor_mix
        ctrl = StubController()
        ctrl.profiles["DevX"] = {"mix": {"0": preset_motor_mix()}}
        line = _chain_summary_line(ctrl, "DevX", 0, 0)
        assert "All SPS" in line          # what it listens to
        assert "d0.38" in line            # how it is tuned
        assert "wake 0.05" in line
        assert "cut" in line
        # The touch chain's line differs — that is how you tell them apart.
        touch_line = _chain_summary_line(ctrl, "DevX", 0, 1)
        assert "d0.62" in touch_line
        assert "wake" not in touch_line

    def test_remove_button_signal_removes_the_chain(self):
        from ui.motor_signal_chain import _get_chain_count
        ui, w = self._list_widget(3)
        assert _get_chain_count(ui.controller, "DevX", 0) == 3
        w._fold_bars[2].removeRequested.emit(2)
        assert _get_chain_count(ui.controller, "DevX", 0) == 2

    def test_bar_subscription_follows_visibility(self):
        _qt_app()
        from ui.motor_signal_chain import _ChainFoldBar

        class _RecordingRouter:
            def __init__(self):
                self.subs = 0
                self.unsubs = 0

            def subscribe_intermediates(self, *a, **k):
                self.subs += 1

            def unsubscribe_intermediates(self, *a, **k):
                self.unsubs += 1

        ctrl = _SmokeController()
        router = _RecordingRouter()
        ctrl.motor_router = router
        bar = _ChainFoldBar(_SmokeUI(ctrl), "DevX", 0, 0, 2, False, "max")
        assert router.subs == 0            # built hidden
        bar.show()
        assert router.subs == 1
        bar.hide()
        assert router.unsubs == 1
        bar.teardown()
        assert router.unsubs == 1          # idempotent

    def test_pips_dim_stages_that_are_off(self):
        """The preset touch chain ships with punch and wake off — its
        pips must say so."""
        _ui, w = self._list_widget(2)
        touch_bar = w._fold_bars[1]
        touch_bar._refresh_static()
        flags = touch_bar._pips._enabled
        # I D S P C W E Z O
        assert flags[3] is False           # Punch off
        assert flags[5] is False           # Wake off
        assert flags[1] is True            # Depth on
        pen_flags = w._fold_bars[0]._pips._enabled
        w._fold_bars[0]._refresh_static()
        assert w._fold_bars[0]._pips._enabled[3] is True   # pen punch on

    def test_live_payload_drives_meter_and_number(self):
        _ui, w = self._list_widget(2)
        bar = w._fold_bars[0]
        bar._on_intermediates({"d_raw": 0.5, "out": 0.42})
        assert bar._out_label.text() == "0.42"
        assert bar._meter_proxy.get() == pytest.approx(0.42, abs=0.01)

    def test_name_field_only_for_custom_chains(self):
        from PySide6.QtWidgets import QLineEdit
        from ui.motor_signal_chain import (
            MotorSignalChainWidget, _update_chain_field, _read_chain,
        )
        _qt_app()
        ui = _SmokeUI(_SmokeController())
        _update_chain_field(ui.controller, "DevX", 0, 0, ("type",), "custom")
        w = MotorSignalChainWidget(ui, "DevX", 0, "vibrate")
        ed = w._build_input_editor()

        def name_edits(host):
            # Spinboxes (the duck Release spinner) own an internal
            # QLineEdit; only bare line edits are Name fields.
            return [e for e in host.findChildren(QLineEdit)
                    if e.objectName() != "qt_spinbox_lineedit"]

        edits = name_edits(ed)
        assert edits, "custom chain should offer a Name field"
        edits[0].setText("Headpat")
        edits[0].editingFinished.emit()
        assert _read_chain(ui.controller, "DevX", 0, 0)["name"] == "Headpat"
        w.teardown()

        _update_chain_field(ui.controller, "DevX", 0, 0, ("type",), "touch")
        w2 = MotorSignalChainWidget(ui, "DevX", 0, "vibrate")
        ed2 = w2._build_input_editor()
        assert not name_edits(ed2), \
            "typed chains name themselves; no field"
        w2.teardown()


class TestPageLevelSimAndOverview:
    """The simulator and the overview moved from per-wrapper panels to
    one page-level bar; the wrapper keeps only the engine."""

    class _RecordingRouter:
        def __init__(self):
            self.providers = {}
            self.suppressed = set()
            self.subs = []
            self.unsubs = []

        def set_chain_value_provider(self, dev, motor, chain, provider):
            self.providers[(dev, motor, chain)] = provider

        def clear_chain_value_provider(self, dev, motor, chain):
            self.providers.pop((dev, motor, chain), None)

        def suppress_toy_output(self, dev, motor):
            self.suppressed.add((dev, motor))

        def unsuppress_toy_output(self, dev, motor):
            self.suppressed.discard((dev, motor))

        def subscribe_intermediates(self, dev, motor, chain, cb):
            self.subs.append((dev, motor, chain))

        def unsubscribe_intermediates(self, dev, motor, chain, cb):
            self.unsubs.append((dev, motor, chain))

    def _wrapper(self):
        _qt_app()
        from ui.motor_signal_chain import MotorChainListWidget
        from config_manager import preset_motor_mix
        ctrl = _SmokeController()
        ctrl.profiles["DevX"] = {"mix": {"0": preset_motor_mix()}}
        router = self._RecordingRouter()
        ctrl.motor_router = router
        return router, MotorChainListWidget(_SmokeUI(ctrl), "DevX", 0,
                                            "vibrate")

    def test_wrapper_no_longer_carries_sim_or_overview_panels(self):
        """The per-motor rows are gone — that is the space win."""
        import ui.motor_signal_chain as msc
        _r, w = self._wrapper()
        assert not hasattr(w, "_build_simulator_panel")
        assert not hasattr(w, "_build_overview_panel")
        w.teardown() if hasattr(w, "teardown") else None

    def test_overview_panel_subscribes_on_show_and_retargets(self):
        _qt_app()
        from ui.motor_signal_chain import ChainOverviewPanel
        router = self._RecordingRouter()
        ctrl = _SmokeController()
        ctrl.motor_router = router
        panel = ChainOverviewPanel(ctrl)
        panel.set_target("DevX", 0, 0)
        assert router.subs == []               # hidden: no feed
        panel.show()
        assert router.subs == [("DevX", 0, 0)]
        panel.set_target("DevX", 0, 1)         # retarget while visible
        assert router.unsubs == [("DevX", 0, 0)]
        assert router.subs[-1] == ("DevX", 0, 1)
        panel.hide()
        assert router.unsubs[-1] == ("DevX", 0, 1)
        panel.teardown()
        assert len(router.unsubs) == 2         # idempotent

    def test_summary_line_spells_out_zones_and_params(self):
        from ui.motor_signal_chain import (
            _chain_summary_line, _update_chain_field,
        )
        ctrl = StubController()
        from config_manager import preset_motor_mix
        ctrl.profiles["DevX"] = {
            "mix": {"0": preset_motor_mix()},
            "motor_0_zones": "Pussy, Ass, Tail",
            "osc_addresses": {"0": ["ToyA_0", "Custom/Prox"]},
        }
        line = _chain_summary_line(ctrl, "DevX", 0, 0)
        # Every zone written out, not "Pussy +2".
        assert "Pussy+Ass+Tail" in line
        # Custom parameters visible too.
        assert "@ToyA_0+Custom/Prox" in line


class TestTouchDuckUI:
    def _editor(self, chain_type):
        from ui.motor_signal_chain import (
            MotorSignalChainWidget, _update_chain_field,
        )
        _qt_app()
        ui = _SmokeUI(_SmokeController())
        _update_chain_field(ui.controller, "DevX", 0, 0, ("type",), chain_type)
        w = MotorSignalChainWidget(ui, "DevX", 0, "vibrate")
        return ui, w, w._build_input_editor()

    @staticmethod
    def _duck_toggle(host):
        from ui.widgets import ToggleSwitch
        for t in host.findChildren(ToggleSwitch):
            if "Duck" in t.text():
                return t
        return None

    def test_touch_chain_offers_the_toggle_and_it_persists(self):
        from ui.motor_signal_chain import _read_chain
        ui, w, ed = self._editor("touch")
        t = self._duck_toggle(ed)
        assert t is not None, "Touch chain Input stage should offer Duck"
        assert not t.isChecked()                  # off by default
        t.setChecked(True)
        assert _read_chain(ui.controller, "DevX", 0, 0)["duck"]["enabled"] is True
        w.teardown()

    def test_penetration_chain_has_no_toggle(self):
        _ui, w, ed = self._editor("penetration")
        assert self._duck_toggle(ed) is None
        w.teardown()

    def test_summary_line_mentions_it(self):
        from ui.motor_signal_chain import _chain_summary_line, _update_chain_field
        ctrl = StubController()
        from config_manager import preset_motor_mix
        ctrl.profiles["DevX"] = {"mix": {"0": preset_motor_mix()}}
        assert "duck" not in _chain_summary_line(ctrl, "DevX", 0, 1)
        _update_chain_field(ctrl, "DevX", 0, 1, ("duck", "enabled"), True)
        assert "duck" in _chain_summary_line(ctrl, "DevX", 0, 1)


class TestSimulatedInputToggle:
    """A chain opts into the simulator from its Input stage; the address it
    stores depends on its type, so the router can hand the wave through
    the chain's touch/pen filter."""

    def _editor(self, chain_type):
        from ui.motor_signal_chain import (
            MotorSignalChainWidget, _update_chain_field,
        )
        _qt_app()
        ui = _SmokeUI(_SmokeController())
        _update_chain_field(ui.controller, "DevX", 0, 0, ("type",), chain_type)
        w = MotorSignalChainWidget(ui, "DevX", 0, "vibrate")
        return ui, w, w._build_input_editor()

    @staticmethod
    def _toggle(host):
        from ui.widgets import ToggleSwitch
        for t in host.findChildren(ToggleSwitch):
            if "Simulated" in t.text():
                return t
        return None

    def test_penetration_chain_stores_the_pen_address_only(self):
        from constants import SIM_PEN_ADDRESS, SIM_TOUCH_ADDRESS
        ui, w, ed = self._editor("penetration")
        t = self._toggle(ed)
        assert t is not None and not t.isChecked()
        t.setChecked(True)
        addrs = ui.controller.get_profile_config("DevX", "osc_addresses", {})["0"]
        assert SIM_PEN_ADDRESS in addrs and SIM_TOUCH_ADDRESS not in addrs
        w.teardown()

    def test_touch_chain_stores_the_touch_address_and_off_removes_it(self):
        from constants import SIM_PEN_ADDRESS, SIM_TOUCH_ADDRESS
        from ui.motor_signal_chain import _set_motor_sim_listening
        ui, w, ed = self._editor("touch")
        t = self._toggle(ed)
        t.setChecked(True)
        addrs = ui.controller.get_profile_config("DevX", "osc_addresses", {})["0"]
        assert SIM_TOUCH_ADDRESS in addrs and SIM_PEN_ADDRESS not in addrs
        _set_motor_sim_listening(ui.controller, "DevX", 0, "touch", False)
        addrs = ui.controller.get_profile_config("DevX", "osc_addresses", {})["0"]
        assert SIM_TOUCH_ADDRESS not in addrs
        w.teardown()

    def test_summary_line_says_sim_not_the_raw_addresses(self):
        from constants import SIM_PEN_ADDRESS, SIM_TOUCH_ADDRESS
        from ui.motor_signal_chain import _chain_summary_line
        from config_manager import preset_motor_mix
        ctrl = StubController()
        ctrl.profiles["DevX"] = {
            "mix": {"0": preset_motor_mix()},
            "osc_addresses": {"0": ["ToyA_0", SIM_PEN_ADDRESS, SIM_TOUCH_ADDRESS]},
        }
        line = _chain_summary_line(ctrl, "DevX", 0, 0)
        assert "@ToyA_0+sim" in line and "OGP/Sim" not in line


def test_every_stage_and_every_knob_in_it_explains_itself():
    """Hover explanations are the app's only in-place help. Each stage
    card carries its stage's explanation, so the collapsed card and every
    knob in the opened editor show one -- a knob's own, more specific tip
    wins, otherwise Qt's parent lookup reaches the card's."""
    _qt_app()
    from PySide6.QtWidgets import (QAbstractButton, QAbstractSlider,
                                   QAbstractSpinBox, QComboBox, QLineEdit,
                                   QScrollBar)
    from ui.motor_signal_chain import MotorSignalChainWidget, _STAGE_TIPS

    def effective_tip(w):
        while w is not None:
            if w.toolTip():
                return w.toolTip()
            if w.isWindow():
                return ""
            w = w.parentWidget()
        return ""

    ui = _SmokeUI(_SmokeController())
    w = MotorSignalChainWidget(ui, "DevX", 0, "vibrate")
    assert set(_STAGE_TIPS) >= set(w._stage_cards)
    bare = []
    for stage, card in w._stage_cards.items():
        title, _text = _STAGE_TIPS[stage]
        assert f"<b>{title}</b>" in card.toolTip(), stage
        w._on_stage_clicked(stage)
        w._on_anim_done()
        for kind in (QAbstractButton, QAbstractSlider, QAbstractSpinBox,
                     QComboBox, QLineEdit):
            for ctl in card.findChildren(kind):
                if not isinstance(ctl, QScrollBar) and not effective_tip(ctl):
                    bare.append((stage, type(ctl).__name__))
    assert bare == []
