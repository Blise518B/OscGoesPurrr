"""Auto modes for a friend's toy: every shape stays in 0..1 and every
level between the friend's low and high."""

import pytest

import friend_patterns as fp


@pytest.mark.parametrize("wave", fp.WAVES)
def test_every_wave_stays_in_its_range(wave):
    pat = fp.clean(wave, 1.5, 0.2, 0.7)
    seen = [fp.level(pat, t / 37.0, t / 37.0 / 1.5) for t in range(600)]
    assert min(seen) >= 0.2 - 1e-9 and max(seen) <= 0.7 + 1e-9
    assert max(seen) - min(seen) > 0.2          # it actually moves


def test_cleaning():
    assert fp.clean("nope", 1, 0, 1) is None
    assert fp.clean("sine", "x", 0, 1) is None
    assert fp.clean("sine", float("nan"), 0, 1) is None
    assert fp.clean("sine", 0.001, 1.5, -1) == ("sine", fp.PERIOD_MIN_S, 0.0, 1.0)
    assert fp.clean("square", 999, 0.9, 0.1) == ("square", fp.PERIOD_MAX_S, 0.1, 0.9)


def test_square_and_build_shapes():
    assert fp.shape("square", 0.25, 0, 1) == 1.0 and fp.shape("square", 0.75, 0, 1) == 0.0
    assert fp.shape("build", 0.1, 0, 1) < fp.shape("build", 0.8, 0, 1)
    assert fp.shape("build", 0.97, 0, 1) == 0.0     # the drop
    assert fp.shape("heart", 0.5, 0, 1) == 0.0      # the rest between beats
