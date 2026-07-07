"""Tests for the OWO muscle mapping (owo_router.compute_muscle_intensity) and
the engine's hot-path active-set filtering.

Pure / SDK-free: owo_engine imports owo_sdk but never loads the CLR unless
connecting, so constructing the engine and exercising set_active needs no
pythonnet and no OWO.dll."""

from owo_router import compute_muscle_intensity


def _m(**kw):
    base = {"enabled": True, "threshold": 0.0, "gain": 1.0, "max_intensity": 100}
    base.update(kw)
    return base


class TestComputeMuscleIntensity:
    def test_disabled_is_zero(self):
        assert compute_muscle_intensity(_m(enabled=False), 1.0) == 0

    def test_empty_cfg_is_zero(self):
        assert compute_muscle_intensity({}, 1.0) == 0

    def test_full_maps_to_max(self):
        assert compute_muscle_intensity(_m(), 1.0) == 100

    def test_half_maps_to_half(self):
        assert compute_muscle_intensity(_m(), 0.5) == 50

    def test_max_intensity_caps(self):
        assert compute_muscle_intensity(_m(max_intensity=60), 1.0) == 60

    def test_threshold_deadband(self):
        assert compute_muscle_intensity(_m(threshold=0.5), 0.4) == 0

    def test_threshold_then_gain(self):
        # (0.6 - 0.2) * 1.0 = 0.4 -> 40
        assert compute_muscle_intensity(_m(threshold=0.2, gain=1.0), 0.6) == 40

    def test_gain_amplifies_and_clamps(self):
        assert compute_muscle_intensity(_m(gain=2.0), 0.6) == 100


class TestEngineSetActive:
    def test_set_active_filters_zeros(self):
        from owo_engine import OwoEngine
        eng = OwoEngine(get_game_id=lambda: "", get_ip=lambda: "")
        eng.set_active({"Pectoral_R": 50, "Arm_L": 0, "Lumbar_R": 80}, 90)
        with eng._state_lock:
            # Zero-intensity muscles are dropped; frequency is stored.
            assert eng._active == {"Pectoral_R": 50, "Lumbar_R": 80}
            assert eng._frequency == 90

    def test_set_active_clamps_intensity_to_100(self):
        # The engine is the last line of defense for the EMS suit: a buggy
        # caller must not be able to command an out-of-range intensity.
        from owo_engine import OwoEngine
        eng = OwoEngine(get_game_id=lambda: "", get_ip=lambda: "")
        eng.set_active({"Pectoral_R": 250}, 90)
        with eng._state_lock:
            assert eng._active == {"Pectoral_R": 100}

    def test_set_active_drops_garbage_and_nan(self):
        from owo_engine import OwoEngine
        eng = OwoEngine(get_game_id=lambda: "", get_ip=lambda: "")
        eng.set_active({"Pectoral_R": "abc", "Arm_L": float("nan"),
                        "Sacral": float("inf"), "Lumbar_R": 40}, 90)
        with eng._state_lock:
            assert eng._active == {"Lumbar_R": 40}

    def test_set_active_garbage_frequency_defaults_not_raises(self):
        from owo_engine import OwoEngine
        eng = OwoEngine(get_game_id=lambda: "", get_ip=lambda: "")
        eng.set_active({"Lumbar_R": 40}, float("nan"))
        with eng._state_lock:
            assert eng._frequency == 100
        eng.set_active({"Lumbar_R": 40}, "fast")
        with eng._state_lock:
            assert eng._frequency == 100

    def test_set_active_change_wakes_send_loop(self):
        from owo_engine import OwoEngine
        eng = OwoEngine(get_game_id=lambda: "", get_ip=lambda: "")
        eng.set_active({"Pectoral_R": 50}, 90)
        assert eng._wake_evt.is_set()        # change -> wake
        eng._wake_evt.clear()
        eng.set_active({"Pectoral_R": 50}, 90)
        assert not eng._wake_evt.is_set()    # identical map -> no wake

    def test_unavailable_without_sdk(self):
        from owo_engine import OwoEngine
        eng = OwoEngine(get_game_id=lambda: "", get_ip=lambda: "")
        # No pythonnet / OWO.dll in the test env -> not available, never raises.
        assert eng.is_available is False
