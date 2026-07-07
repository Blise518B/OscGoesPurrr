"""Tests for the Handy engine's pure decision cores: the HAMP speed planner,
the HDSP position planner, velocity quantization, header building, and the
stroke-zone cleaner. No network, no threads — the planners are exactly the
part of the engine that decides WHAT to send; executing HTTP is the thin
layer around them."""

from handy_engine import (
    HandyEngine,
    HandyPositionPlanner,
    HandySpeedPlanner,
    _clean_stroke,
    build_headers,
    quantize_velocity,
)


class TestQuantizeVelocity:
    def test_full_level_full_cap(self):
        assert quantize_velocity(1.0, 1.0) == 1.0

    def test_cap_scales(self):
        assert quantize_velocity(1.0, 0.6) == 0.6

    def test_quantized_to_step(self):
        # 0.333 * 1.0 snaps to the nearest 0.01
        assert quantize_velocity(0.333, 1.0) == 0.33

    def test_clamps_and_survives_garbage(self):
        assert quantize_velocity(2.0, 1.0) == 1.0
        assert quantize_velocity(-1.0, 1.0) == 0.0
        assert quantize_velocity("x", 1.0) == 0.0


class TestSpeedPlanner:
    def test_first_contact_starts_then_sets_velocity(self):
        p = HandySpeedPlanner(idle_stop_s=5.0)
        assert p.step(0.5, 0.0) == ("hamp_start", None)
        # /hamp/start begins at velocity 0; the real speed follows.
        assert p.step(0.5, 0.2) == ("hamp_velocity", 0.5)

    def test_held_velocity_sends_nothing(self):
        p = HandySpeedPlanner()
        p.step(0.5, 0.0)
        p.step(0.5, 0.2)
        assert p.step(0.5, 0.4) is None

    def test_velocity_change_is_sent(self):
        p = HandySpeedPlanner()
        p.step(0.5, 0.0)
        p.step(0.5, 0.2)
        assert p.step(0.8, 0.4) == ("hamp_velocity", 0.8)

    def test_zero_parks_then_stops_after_grace(self):
        p = HandySpeedPlanner(idle_stop_s=5.0)
        p.step(0.5, 0.0)
        p.step(0.5, 0.2)
        assert p.step(0.0, 1.0) == ("hamp_velocity", 0.0)
        assert p.step(0.0, 3.0) is None              # inside the grace window
        assert p.step(0.0, 6.5) == ("hamp_stop", None)
        assert p.playing is False
        assert p.step(0.0, 10.0) is None             # stays quiet once stopped

    def test_contact_during_grace_cancels_stop(self):
        p = HandySpeedPlanner(idle_stop_s=5.0)
        p.step(0.5, 0.0)
        p.step(0.5, 0.2)
        p.step(0.0, 1.0)
        assert p.step(0.6, 2.0) == ("hamp_velocity", 0.6)
        assert p.step(0.0, 3.0) == ("hamp_velocity", 0.0)
        assert p.step(0.0, 7.0) is None              # grace restarted at t=3
        assert p.step(0.0, 8.5) == ("hamp_stop", None)

    def test_idle_from_the_start_sends_nothing(self):
        p = HandySpeedPlanner()
        assert p.step(0.0, 0.0) is None
        assert p.step(0.0, 100.0) is None


class TestPositionPlanner:
    def test_level_pulls_slider_down(self):
        # OGB convention: stronger contact = lower position.
        p = HandyPositionPlanner()
        cmd = p.step(1.0, 0.0)
        assert cmd[0] == "hdsp_move"
        assert cmd[1]["xp"] == 0.0

    def test_invert_pulls_slider_up(self):
        p = HandyPositionPlanner(invert=True)
        cmd = p.step(1.0, 0.0)
        assert cmd[1]["xp"] == 1.0

    def test_same_position_not_resent(self):
        p = HandyPositionPlanner()
        assert p.step(0.5, 0.0) is not None
        assert p.step(0.5, 250.0) is None
        assert p.step(0.501, 500.0) is None          # inside the jitter floor

    def test_duration_covers_send_gap_with_margin(self):
        p = HandyPositionPlanner()
        p.step(0.2, 0.0)
        cmd = p.step(0.8, 400.0)
        # 400 ms measured gap * 1.25 overlap = 500 ms commanded move.
        assert cmd[1]["t"] == 500

    def test_duration_clamped_after_idle_gap(self):
        p = HandyPositionPlanner()
        p.step(0.2, 0.0)
        cmd = p.step(0.8, 60_000.0)
        # The gap estimate is capped so a post-idle move isn't sluggish.
        assert cmd[1]["t"] == 1250


class TestHeadersAndStroke:
    def test_build_headers(self):
        h = build_headers(" abc123 ", "key-9")
        assert h["X-Connection-Key"] == "abc123"
        assert h["X-Api-Key"] == "key-9"

    def test_clean_stroke_clamps_and_orders(self):
        assert _clean_stroke({"stroke_min": 0.9, "stroke_max": 0.1}) == \
            {"min": 0.1, "max": 0.9}
        assert _clean_stroke({"stroke_min": -1, "stroke_max": 2}) == \
            {"min": 0.0, "max": 1.0}

    def test_clean_stroke_keeps_a_usable_window(self):
        out = _clean_stroke({"stroke_min": 0.5, "stroke_max": 0.5})
        assert out["max"] - out["min"] >= 0.05

    def test_clean_stroke_survives_garbage(self):
        assert _clean_stroke({"stroke_min": "x", "stroke_max": None}) == \
            {"min": 0.0, "max": 1.0}


class TestEngineHotPath:
    def _engine(self):
        return HandyEngine(
            get_connection_key=lambda: "",
            get_api_key=lambda: "",
            get_motion_config=lambda: {},
        )

    def test_set_level_clamps_and_stores(self):
        eng = self._engine()
        eng.set_level(2.0)
        with eng._state_lock:
            assert eng._level == 1.0
        eng.set_level(-0.5)
        with eng._state_lock:
            assert eng._level == 0.0
        eng.set_level("garbage")
        with eng._state_lock:
            assert eng._level == 0.0

    def test_open_without_keys_raises(self):
        import pytest
        eng = self._engine()
        with pytest.raises(RuntimeError, match="connection key"):
            eng._open()

    def test_plan_applies_stroke_zone_first(self):
        eng = self._engine()
        eng._stroke_dirty = True
        cmd = eng._plan_next({"stroke_min": 0.2, "stroke_max": 0.8}, 0.0)
        assert cmd == ("stroke", {"min": 0.2, "max": 0.8})

    def test_plan_mode_switch_stops_hamp_first(self):
        eng = self._engine()
        eng.set_level(0.5)
        assert eng._plan_next({"mode": "speed"}, 0.0) == ("hamp_start", None)
        assert eng._plan_next({"mode": "speed"}, 0.3)[0] == "hamp_velocity"
        # Switching to position mode: stop the alternating motion before
        # the first position command goes out.
        assert eng._plan_next({"mode": "position"}, 0.6) == ("hamp_stop", None)
        nxt = eng._plan_next({"mode": "position"}, 0.9)
        assert nxt[0] == "hdsp_move"


class TestRateLimitRollback:
    """A 429 drops the command AFTER _plan_next committed its bookkeeping.
    _rollback_plan must rewind that state so the next allowed send re-emits
    the lost command instead of silently losing it until the level changes."""

    def _engine(self):
        return HandyEngine(
            get_connection_key=lambda: "",
            get_api_key=lambda: "",
            get_motion_config=lambda: {},
        )

    def test_lost_velocity_is_replanned(self):
        eng = self._engine()
        eng.set_level(0.5)
        assert eng._plan_next({"mode": "speed"}, 0.0) == ("hamp_start", None)
        cmd = eng._plan_next({"mode": "speed"}, 0.1)
        assert cmd[0] == "hamp_velocity"
        eng._rollback_plan(cmd)                      # the send 429'd
        assert eng._plan_next({"mode": "speed"}, 0.2) == cmd  # re-emitted

    def test_lost_start_is_replanned(self):
        eng = self._engine()
        eng.set_level(0.5)
        cmd = eng._plan_next({"mode": "speed"}, 0.0)
        assert cmd == ("hamp_start", None)
        eng._rollback_plan(cmd)
        assert eng._plan_next({"mode": "speed"}, 0.1) == ("hamp_start", None)

    def test_lost_stop_still_stops_the_device(self):
        # Worst case from the review: velocity already 0, the final
        # hamp_stop 429s — without rollback the planner believed the device
        # was stopped and never tried again (stroker left in PLAY).
        eng = self._engine()
        eng.set_level(0.5)
        eng._plan_next({"mode": "speed"}, 0.0)       # hamp_start
        eng._plan_next({"mode": "speed"}, 0.1)       # hamp_velocity 0.5
        eng.set_level(0.0)
        eng._plan_next({"mode": "speed"}, 0.2)       # hamp_velocity 0.0
        cmd = eng._plan_next({"mode": "speed"}, 20.0)
        assert cmd == ("hamp_stop", None)            # idle grace elapsed
        eng._rollback_plan(cmd)                      # ...but it 429'd
        # The re-plan walks the stop sequence again: velocity 0, then stop.
        assert eng._plan_next({"mode": "speed"}, 21.0) == ("hamp_velocity", 0.0)
        assert eng._plan_next({"mode": "speed"}, 40.0) == ("hamp_stop", None)

    def test_lost_position_is_replanned(self):
        eng = self._engine()
        eng.set_level(0.8)
        cmd = eng._plan_next({"mode": "position"}, 0.0)
        assert cmd[0] == "hdsp_move"
        eng._rollback_plan(cmd)
        replay = eng._plan_next({"mode": "position"}, 0.5)
        assert replay[0] == "hdsp_move"
        assert replay[1]["xp"] == cmd[1]["xp"]

    def test_lost_stroke_zone_is_replanned(self):
        eng = self._engine()
        eng._stroke_dirty = True
        cmd = eng._plan_next({"stroke_min": 0.2, "stroke_max": 0.8}, 0.0)
        assert cmd[0] == "stroke"
        eng._rollback_plan(cmd)
        assert eng._stroke_dirty is True             # re-armed
