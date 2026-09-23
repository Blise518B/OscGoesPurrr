"""Tests for `GameDeviceLengthDetector` — the standalone calibration
state machine that figures out how long a VRChat penetrator is from
sequential root + tip proximity readings.

See ``PLAN.md`` Tier 4 for the punch-list.
"""

import pytest

from motor_router import GameDeviceLengthDetector


class TestInitialState:
    def test_length_starts_none(self):
        det = GameDeviceLengthDetector()
        assert det.get_length() is None

    def test_no_recent_samples(self):
        det = GameDeviceLengthDetector()
        assert det.recent_samples == []

    def test_no_bad_penetrating_sample(self):
        det = GameDeviceLengthDetector()
        assert det.bad_penetrating_sample is None


class TestSubRadiusClearing:
    def test_root_below_threshold_clears(self):
        det = GameDeviceLengthDetector()
        det.update(0.4, 0.7)
        det.update(0.4, 0.7)
        assert det.recent_samples  # populated
        det.update(0.005, 0.7)  # root < 0.01 → clear
        assert det.recent_samples == []

    def test_tip_below_threshold_clears(self):
        det = GameDeviceLengthDetector()
        det.update(0.4, 0.7)
        det.update(0.005, 0.7)
        det.recent_samples = [0.3, 0.3]  # force-set so the clear path is visible
        det.update(0.4, 0.005)  # tip < 0.01 → clear
        assert det.recent_samples == []
        assert det.bad_penetrating_sample is None


class TestThresholdIgnores:
    def test_root_above_0_95_ignored(self):
        det = GameDeviceLengthDetector()
        # Establish a calibration first
        for _ in range(5):
            det.update(0.3, 0.5)  # length 0.2
        prior = det.get_length()
        assert prior is not None

        # Now feed a high-root sample — function returns early before any
        # state mutation, so length stays exactly what it was.
        before_samples = list(det.recent_samples)
        det.update(0.97, 0.99)
        assert det.recent_samples == before_samples
        assert det.get_length() == prior

    def test_too_short_length_ignored(self):
        det = GameDeviceLengthDetector()
        det.update(0.5, 0.51)  # length 0.01 < 0.02 → ignored
        assert det.recent_samples == []
        assert det.get_length() is None

    def test_inverted_length_ignored(self):
        # tip < root means a negative length; should be ignored.
        det = GameDeviceLengthDetector()
        det.update(0.7, 0.5)
        assert det.recent_samples == []


class TestBadPenetratingSample:
    def test_tip_above_0_99_stores_bad_sample(self):
        det = GameDeviceLengthDetector()
        det.update(0.5, 1.0)  # tip > 0.99 → bad_penetrating_sample
        assert det.bad_penetrating_sample == pytest.approx(0.5)

    def test_bad_sample_only_grows(self):
        det = GameDeviceLengthDetector()
        det.update(0.5, 1.0)  # bad = 0.5
        det.update(0.3, 1.0)  # length 0.7 > 0.5 → bad = 0.7
        assert det.bad_penetrating_sample == pytest.approx(0.7)
        det.update(0.6, 1.0)  # length 0.4 < 0.7 → bad unchanged
        assert det.bad_penetrating_sample == pytest.approx(0.7)

    def test_under_four_samples_uses_bad(self):
        det = GameDeviceLengthDetector()
        det.update(0.4, 1.0)  # bad = 0.6
        det.update(0.5, 0.7)  # 1 normal sample (length 0.2)
        det.update(0.5, 0.7)  # 2 normal samples
        det.update(0.5, 0.7)  # 3 normal samples
        # < 4 normal samples — length should come from bad_penetrating_sample.
        assert det.get_length() == pytest.approx(0.6)


class TestNormalSamples:
    def test_normal_samples_accumulate(self):
        det = GameDeviceLengthDetector()
        for _ in range(3):
            det.update(0.5, 0.7)  # length 0.2
        assert len(det.recent_samples) == 3

    def test_samples_capped_at_max(self):
        det = GameDeviceLengthDetector()
        for _ in range(GameDeviceLengthDetector.MAX_SAMPLES + 5):
            det.update(0.5, 0.7)
        assert len(det.recent_samples) == GameDeviceLengthDetector.MAX_SAMPLES

    def test_four_samples_uses_closest_pair(self):
        det = GameDeviceLengthDetector()
        # Four samples; two of them are identical (length 0.2) so they're the
        # closest pair. The winner is the higher-index sample in sorted order.
        det.update(0.5, 0.7)  # length 0.2
        det.update(0.4, 0.6)  # length 0.2
        det.update(0.3, 0.6)  # length 0.3
        det.update(0.2, 0.6)  # length 0.4
        assert det.get_length() == pytest.approx(0.2)


class TestGarbageInput:
    def test_garbage_root_clears_samples(self):
        det = GameDeviceLengthDetector()
        det.update(0.5, 0.7)
        det.update("not a number", 0.7)
        assert det.recent_samples == []

    def test_none_input_clears_samples(self):
        det = GameDeviceLengthDetector()
        det.update(0.5, 0.7)
        det.update(None, 0.7)
        assert det.recent_samples == []
