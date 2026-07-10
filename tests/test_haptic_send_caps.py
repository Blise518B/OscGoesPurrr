"""Tests for the per-feature send-rate gating (FeatureSendGate.can_send):
the default (vibrate) cap vs the lower linear cap. Buttplug Spec v4 servers
coalesce strokers to one flush per device message gap (The Handy: 50 ms), so
the linear path must pace itself at LINEAR_MAX_SEND_HZ instead of spamming
sends that would only be dropped — and would desync the commanded duration
from the device's real cadence. Pure: no connection, no threads."""

import queue

from constants import HAPTIC_MAX_SEND_HZ, LINEAR_MAX_SEND_HZ
from send_gate import FeatureSendGate

DEFAULT_INTERVAL_MS = 1000.0 / HAPTIC_MAX_SEND_HZ
LINEAR_INTERVAL_MS = 1000.0 / LINEAR_MAX_SEND_HZ


def _gate():
    return FeatureSendGate(DEFAULT_INTERVAL_MS)


KEY = ("Toy", 0)


class TestEngineWiring:
    def test_engine_builds_gate_with_configured_caps(self):
        # The engine derives both cadences from the app constants; the gate
        # itself is cadence-agnostic, so pin the wiring here.
        from haptic_engine import HapticEngine

        eng = HapticEngine(queue.Queue())
        assert eng._send_gate.default_interval_ms == DEFAULT_INTERVAL_MS
        assert eng._min_linear_send_interval_ms == LINEAR_INTERVAL_MS


class TestDefaultCap:
    def test_first_send_after_idle_is_immediate(self):
        assert _gate().can_send(KEY, 0.0) is True

    def test_consecutive_send_inside_interval_is_held(self):
        gate = _gate()
        gate.last_send_ms[KEY] = 1000.0
        inside = 1000.0 + DEFAULT_INTERVAL_MS / 2
        assert gate.can_send(KEY, inside) is False

    def test_send_after_interval_passes(self):
        gate = _gate()
        gate.last_send_ms[KEY] = 1000.0
        # Nudge past the interval boundary — the gap check is >=, but
        # 1000/60 isn't exactly representable in floats.
        after = 1000.0 + DEFAULT_INTERVAL_MS + 0.01
        assert gate.can_send(KEY, after) is True

    def test_inflight_blocks_regardless_of_time(self):
        gate = _gate()
        gate.inflight[KEY] = True
        assert gate.can_send(KEY, 1e9) is False


class TestLinearCap:
    def test_linear_cap_is_20hz(self):
        assert LINEAR_MAX_SEND_HZ == 20
        assert LINEAR_INTERVAL_MS == 50.0

    def test_linear_gap_holds_where_default_would_send(self):
        # 25 ms after the last send: fine for a vibe (60 Hz cap = 16.7 ms gap),
        # held for a stroker (20 Hz cap = 50 ms gap).
        gate = _gate()
        gate.last_send_ms[KEY] = 1000.0
        now = 1025.0
        assert gate.can_send(KEY, now) is True
        assert gate.can_send(KEY, now, LINEAR_INTERVAL_MS) is False

    def test_linear_send_after_gap_passes(self):
        gate = _gate()
        gate.last_send_ms[KEY] = 1000.0
        assert gate.can_send(KEY, 1050.0, LINEAR_INTERVAL_MS) is True

    def test_linear_first_send_after_idle_is_immediate(self):
        # The cap only spaces consecutive sends — edge latency is untouched.
        assert _gate().can_send(KEY, 0.0, LINEAR_INTERVAL_MS) is True
