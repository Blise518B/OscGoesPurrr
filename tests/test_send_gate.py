"""Tests for FeatureSendGate — the extracted decision core of the Buttplug
dispatch loop (haptic_engine.async_worker). Covers the change gate, the
linear min-delta gate, duration sizing from the measured send gap, the
record-on-grant / untouched-on-denial bookkeeping, and the lifecycle hooks
(clear on reconnect, forget_device on unplug). Pure: no connection, no
asyncio, no buttplug import."""

from send_gate import FeatureSendGate

KEY = ("Toy", 0)
OTHER = ("OtherToy", 1)

# Representative numbers, hard-coded so the math in each assertion is
# auditable at a glance. DELIBERATELY not the app constants (the gate is
# parameter-driven; only the two cap intervals happen to match). The
# engine's real wiring — constants.py values reaching the gate — is
# pinned by tests/test_haptic_send_caps.py::TestEngineWiring.
DEFAULT_MS = 1000.0 / 60.0   # continuous cap
LINEAR_MS = 50.0             # linear cap (20 Hz)
MIN_DELTA = 0.005
OVERLAP = 1.25
MAX_GAP_MS = 400.0


def _gate():
    return FeatureSendGate(DEFAULT_MS)


def _try_linear(gate, position, now_ms):
    return gate.try_linear(KEY, position, now_ms,
                           LINEAR_MS, MIN_DELTA, OVERLAP, MAX_GAP_MS)


class TestContinuousChangeGate:
    def test_first_nonzero_target_sends_immediately(self):
        gate = _gate()
        assert gate.try_continuous(KEY, 0.5, 1000.0) is True
        assert gate.last_sent[KEY] == 0.5
        assert gate.last_send_ms[KEY] == 1000.0

    def test_never_sent_zero_target_is_noise(self):
        # The server starts devices at rest; commanding 0 to a feature we
        # never drove would be a pointless BLE write.
        gate = _gate()
        assert gate.try_continuous(KEY, 0.0, 1000.0) is False
        assert KEY not in gate.last_sent

    def test_unchanged_target_is_suppressed(self):
        gate = _gate()
        gate.try_continuous(KEY, 0.5, 1000.0)
        assert gate.try_continuous(KEY, 0.5, 5000.0) is False

    def test_return_to_zero_is_a_change_and_sends(self):
        gate = _gate()
        gate.try_continuous(KEY, 0.5, 1000.0)
        assert gate.try_continuous(KEY, 0.0, 2000.0) is True
        assert gate.last_sent[KEY] == 0.0

    def test_denial_leaves_state_untouched_for_latest_wins(self):
        # Rate-capped denial must not record anything: the newest value is
        # retried on a later tick and the *original* send time still paces it.
        gate = _gate()
        gate.try_continuous(KEY, 0.3, 1000.0)
        inside = 1000.0 + DEFAULT_MS / 2
        assert gate.try_continuous(KEY, 0.9, inside) is False
        assert gate.last_sent[KEY] == 0.3
        assert gate.last_send_ms[KEY] == 1000.0
        after = 1000.0 + DEFAULT_MS + 0.01
        assert gate.try_continuous(KEY, 0.9, after) is True
        assert gate.last_sent[KEY] == 0.9

    def test_inflight_denies_and_release_grants(self):
        gate = _gate()
        gate.try_continuous(KEY, 0.3, 1000.0)
        gate.set_inflight(KEY, True)
        assert gate.try_continuous(KEY, 0.9, 5000.0) is False
        gate.set_inflight(KEY, False)
        assert gate.try_continuous(KEY, 0.9, 5000.0) is True

    def test_features_are_gated_independently(self):
        gate = _gate()
        gate.set_inflight(KEY, True)
        assert gate.try_continuous(OTHER, 0.4, 1000.0) is True


class TestLinearDeltaGate:
    def test_first_position_always_sends(self):
        # The resting seed must reach the device even if it's position 0.
        gate = _gate()
        assert _try_linear(gate, 0.0, 1000.0) is not None
        assert gate.last_sent[KEY] == 0.0

    def test_sub_delta_move_is_held_without_recording(self):
        gate = _gate()
        _try_linear(gate, 0.5, 1000.0)
        assert _try_linear(gate, 0.5 + MIN_DELTA / 2, 2000.0) is None
        # Not recorded: the reference stays the last SENT position, so a
        # slow creep eventually crosses the threshold instead of being
        # re-zeroed every tick and never sending.
        assert gate.last_sent[KEY] == 0.5
        assert _try_linear(gate, 0.5 + MIN_DELTA, 3000.0) is not None

    def test_rate_cap_holds_at_linear_cadence(self):
        gate = _gate()
        _try_linear(gate, 0.2, 1000.0)
        assert _try_linear(gate, 0.8, 1000.0 + LINEAR_MS / 2) is None
        assert _try_linear(gate, 0.8, 1000.0 + LINEAR_MS) is not None

    def test_inflight_holds_position_sends(self):
        # Stroke positions must never arrive out of order.
        gate = _gate()
        _try_linear(gate, 0.2, 1000.0)
        gate.set_inflight(KEY, True)
        assert _try_linear(gate, 0.8, 5000.0) is None


class TestLinearDurationSizing:
    def test_first_send_uses_nominal_cadence(self):
        gate = _gate()
        assert _try_linear(gate, 0.5, 1000.0) == round(LINEAR_MS * OVERLAP)

    def test_duration_overshoots_the_measured_gap(self):
        # 80 ms real gap * 1.25 overlap = 100 ms commanded move: the device
        # is still travelling when the next position lands (no "stepping").
        gate = _gate()
        _try_linear(gate, 0.2, 1000.0)
        assert _try_linear(gate, 0.8, 1080.0) == 100

    def test_post_idle_gap_is_clamped(self):
        # A long quiet stretch must not command a sluggish multi-second move.
        gate = _gate()
        _try_linear(gate, 0.2, 1000.0)
        assert _try_linear(gate, 0.8, 11000.0) == round(MAX_GAP_MS * OVERLAP)

    def test_send_at_exact_cap_boundary_sizes_from_nominal_gap(self):
        # The cap check is >=, so a send landing exactly on the boundary
        # grants — and its duration is sized from the 50 ms gap. (The
        # clamp floor itself is unreachable through the gate: can_send
        # guarantees the measured gap is never below the cap. It is
        # covered directly in test_haptic_actuators.)
        gate = _gate()
        _try_linear(gate, 0.2, 1000.0)
        assert (_try_linear(gate, 0.8, 1000.0 + LINEAR_MS)
                == round(LINEAR_MS * OVERLAP))


class TestLifecycle:
    def test_clear_forgets_last_sent_so_reconnect_resends(self):
        # After a reconnect the toy is physically at 0; an unchanged routed
        # target must be re-sent, not debounced against the dead session.
        gate = _gate()
        gate.try_continuous(KEY, 0.5, 1000.0)
        gate.set_inflight(KEY, True)
        gate.clear()
        assert gate.try_continuous(KEY, 0.5, 2000.0) is True

    def test_forget_device_only_drops_that_device(self):
        gate = _gate()
        gate.try_continuous(KEY, 0.5, 1000.0)
        gate.try_continuous(OTHER, 0.4, 1000.0)
        gate.set_inflight(KEY, True)
        gate.forget_device(KEY[0])
        assert KEY not in gate.last_sent
        assert KEY not in gate.last_send_ms
        assert KEY not in gate.inflight
        # The other device's pacing state is untouched.
        assert gate.last_sent[OTHER] == 0.4
        assert gate.try_continuous(OTHER, 0.4, 5000.0) is False
