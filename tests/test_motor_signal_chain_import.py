"""Smoke + behaviour tests for the motor signal-chain widget module.

Importing the module fails fast if there's a syntax error, missing
import, or typo in a class/function name. The storage-helper tests
exercise the read/write round-trip through a stub controller so the
chain_idx-aware schema (Cut 5) is validated without a live UI."""


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
    assert msc.MAX_CHAINS_PER_MOTOR == 2


def test_stage_constants_are_unique_and_ordered():
    from ui.motor_signal_chain import (
        _STAGE_ORDER, _STAGE_LABELS,
        STAGE_INPUT, STAGE_DEPTH, STAGE_SPEED,
        STAGE_COMBINE, STAGE_GATE, STAGE_SMOOTHING, STAGE_ZEROCUT,
        STAGE_OUTPUT,
    )
    expected = (
        STAGE_INPUT, STAGE_DEPTH, STAGE_SPEED,
        STAGE_COMBINE, STAGE_GATE, STAGE_SMOOTHING, STAGE_ZEROCUT,
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


def test_update_chain_field_writes_gate_subfield():
    """Nested-path writes don't blow away sibling fields — the
    activity gate's three keys must coexist after individual
    writes."""
    from ui.motor_signal_chain import _read_chain, _update_chain_field

    ctrl = StubController()
    _update_chain_field(ctrl, "DevY", 0, 0, ("gate", "enabled"), True)
    _update_chain_field(ctrl, "DevY", 0, 0, ("gate", "wake_threshold"), 0.2)
    _update_chain_field(ctrl, "DevY", 0, 0, ("gate", "sleep_delay_s"), 1.5)
    chain = _read_chain(ctrl, "DevY", 0)
    assert chain["gate"]["enabled"] is True
    assert chain["gate"]["wake_threshold"] == 0.2
    assert chain["gate"]["sleep_delay_s"] == 1.5


# ============================================================ Cut 5: chain list

def test_chain_count_defaults_to_one():
    """A profile without a `mix` block reports count = 1 — the
    router treats it as a single default chain, and the UI mirrors."""
    from ui.motor_signal_chain import _get_chain_count
    ctrl = StubController()
    assert _get_chain_count(ctrl, "DevZ", 0) == 1


def test_add_chain_grows_to_two_then_caps():
    """Adding a chain bumps count to 2; a second add is refused."""
    from ui.motor_signal_chain import _add_chain, _get_chain_count
    ctrl = StubController()
    assert _get_chain_count(ctrl, "Dev", 0) == 1
    assert _add_chain(ctrl, "Dev", 0) is True
    assert _get_chain_count(ctrl, "Dev", 0) == 2
    # Cap at MAX_CHAINS_PER_MOTOR — second add rejected.
    assert _add_chain(ctrl, "Dev", 0) is False
    assert _get_chain_count(ctrl, "Dev", 0) == 2


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


def test_strip_host_fanout_spreads_branches():
    """The fork/join fanout offsets the top channel up and the bottom down by
    _BRANCH_FANOUT (so the two arrows don't stack), and is zero for one."""
    from ui.motor_signal_chain import _StripHost, _BRANCH_FANOUT
    assert _StripHost._fanout(0, 1) == 0.0
    assert _StripHost._fanout(0, 2) == -_BRANCH_FANOUT   # top channel: up
    assert _StripHost._fanout(1, 2) == _BRANCH_FANOUT    # bottom channel: down


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

    def _make_help_badge(self, title, text):
        # Real badge widget, minus the registration/visibility plumbing
        # the full UI mixin provides — the editors just need a QWidget.
        from ui.help_mode import HelpBadge
        return HelpBadge(title, text)


def test_widget_build_expand_intermediates_collapse():
    _qt_app()
    from ui.motor_signal_chain import MotorSignalChainWidget, STAGE_COMBINE

    ui = _SmokeUI(_SmokeController())
    w = MotorSignalChainWidget(ui, "DevX", 0, "vibrate")

    # Built collapsed: 7 horizontal slots, 8 stage cards (Depth+Speed
    # share a slot; Zero cut sits between Smoothing and Output), nothing
    # expanded.
    assert len(w._slots) == 7
    assert len(w._stage_cards) == 8
    assert w._active_stage is None
    # Small mode by default → cards/arrows centred.
    assert w._strip_host._centered is True
    # 7 slots interleaved with 6 flexible connector cells (no trailing
    # stretch) — the cells are what the stretching arrows are drawn across.
    assert w._strip_lay.count() == 13
    # Input forks into Depth+Speed and they join into Combine: the parallel
    # ds slot (index 1) is registered with its two inner cards.
    assert w._strip_host._branch_index == 1
    assert len(w._strip_host._branch_cards) == 2
    # Smoothing has a quick delay slider (like Depth/Speed's gain slider).
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
    assert w._strip_host._centered is False     # expanded → top-aligned arrows
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
    assert w._strip_host._centered is True      # back to small/centred mode

    w.teardown()


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
