"""Tests for the per-feature send-rate gating in HapticEngine._can_send_now:
the default (vibrate) cap vs the lower linear cap. Buttplug Spec v4 servers
coalesce strokers to one flush per device message gap (The Handy: 50 ms), so
the linear path must pace itself at LINEAR_MAX_SEND_HZ instead of spamming
sends that would only be dropped — and would desync the commanded duration
from the device's real cadence. Pure: no connection, no threads."""

import queue

from constants import HAPTIC_MAX_SEND_HZ, LINEAR_MAX_SEND_HZ
from haptic_engine import HapticEngine


def _engine():
    return HapticEngine(queue.Queue())


KEY = ("Toy", 0)


class TestDefaultCap:
    def test_first_send_after_idle_is_immediate(self):
        eng = _engine()
        assert eng._can_send_now(KEY, 0.0) is True

    def test_consecutive_send_inside_interval_is_held(self):
        eng = _engine()
        eng._last_send_ms[KEY] = 1000.0
        inside = 1000.0 + (1000.0 / HAPTIC_MAX_SEND_HZ) / 2
        assert eng._can_send_now(KEY, inside) is False

    def test_send_after_interval_passes(self):
        eng = _engine()
        eng._last_send_ms[KEY] = 1000.0
        # Nudge past the interval boundary — the gap check is >=, but
        # 1000/60 isn't exactly representable in floats.
        after = 1000.0 + 1000.0 / HAPTIC_MAX_SEND_HZ + 0.01
        assert eng._can_send_now(KEY, after) is True

    def test_inflight_blocks_regardless_of_time(self):
        eng = _engine()
        eng._send_inflight[KEY] = True
        assert eng._can_send_now(KEY, 1e9) is False


class TestLinearCap:
    def test_linear_cap_is_20hz(self):
        assert LINEAR_MAX_SEND_HZ == 20
        assert _engine()._min_linear_send_interval_ms == 50.0

    def test_linear_gap_holds_where_default_would_send(self):
        # 25 ms after the last send: fine for a vibe (60 Hz cap = 16.7 ms gap),
        # held for a stroker (20 Hz cap = 50 ms gap).
        eng = _engine()
        eng._last_send_ms[KEY] = 1000.0
        now = 1025.0
        assert eng._can_send_now(KEY, now) is True
        assert eng._can_send_now(
            KEY, now, eng._min_linear_send_interval_ms) is False

    def test_linear_send_after_gap_passes(self):
        eng = _engine()
        eng._last_send_ms[KEY] = 1000.0
        assert eng._can_send_now(
            KEY, 1050.0, eng._min_linear_send_interval_ms) is True

    def test_linear_first_send_after_idle_is_immediate(self):
        # The cap only spaces consecutive sends — edge latency is untouched.
        eng = _engine()
        assert eng._can_send_now(
            KEY, 0.0, eng._min_linear_send_interval_ms) is True
