"""Tests for the Coyote channel mapping (coyote_router.compute_channel_strength).

Pure: zone strength (0..1) -> channel strength (0-200) with threshold / gain /
max_strength shaping. No engine, no BLE."""

from coyote_router import compute_channel_strength


def _ch(**kw):
    base = {"enabled": True, "threshold": 0.0, "gain": 1.0, "max_strength": 100}
    base.update(kw)
    return base


class TestComputeChannelStrength:
    def test_disabled_is_zero(self):
        assert compute_channel_strength(_ch(enabled=False), 1.0) == 0

    def test_empty_cfg_is_zero(self):
        assert compute_channel_strength({}, 1.0) == 0

    def test_full_maps_to_max(self):
        assert compute_channel_strength(_ch(max_strength=100), 1.0) == 100

    def test_half_maps_to_half(self):
        assert compute_channel_strength(_ch(max_strength=100), 0.5) == 50

    def test_max_strength_scales(self):
        assert compute_channel_strength(_ch(max_strength=150), 1.0) == 150

    def test_clamped_to_200(self):
        assert compute_channel_strength(_ch(max_strength=999), 1.0) == 200

    def test_threshold_deadband(self):
        assert compute_channel_strength(_ch(threshold=0.5), 0.4) == 0

    def test_threshold_then_gain(self):
        # (0.6 - 0.2) * 1.0 = 0.4 -> *100 = 40
        assert compute_channel_strength(_ch(threshold=0.2, gain=1.0, max_strength=100), 0.6) == 40

    def test_gain_amplifies_and_clamps(self):
        # 0.6 * 2 = 1.2 -> clamp 1.0 -> 100
        assert compute_channel_strength(_ch(gain=2.0, max_strength=100), 0.6) == 100
