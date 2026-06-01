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
        STAGE_COMBINE, STAGE_GATE, STAGE_SMOOTHING, STAGE_OUTPUT,
    )
    expected = (
        STAGE_INPUT, STAGE_DEPTH, STAGE_SPEED,
        STAGE_COMBINE, STAGE_GATE, STAGE_SMOOTHING, STAGE_OUTPUT,
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
    assert ctrl.saved >= 1
    assert ctrl.recalced >= 1

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
