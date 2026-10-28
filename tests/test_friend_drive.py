"""A friend's level at the router's Output stage: it joins the motor's own
output (the higher wins) but still obeys the person's strength, Off and the
toy's own output band."""

import pytest

from motor_router import MotorRouter


def _cfg(band=None):
    chain = {
        "depth": {"gain": 1.0, "curve": "linear", "curve_param": 1.0},
        "speed": {"gain": 0.0, "curve": "linear", "curve_param": 1.0},
        "combine": "max",
        "gate": {"enabled": False, "wake_threshold": 0.05, "sleep_delay_s": 0.5},
        "smoothing": {"rise_ms": 0.0, "fall_ms": 0.0},
    }
    if band:
        chain["output"] = {"min": band[0], "max": band[1]}
    return {"motor_0_touch": True, "motor_0_pen": True, "motor_0_self": False,
            "motor_0_others": True, "osc_addresses": {"0": ["MyParam"]},
            "mix": {"0": {"chains": [chain], "merge": "max"}}}


def _router(clock, drive, scale=1.0):
    return MotorRouter(clock=clock.now, get_master_scale=lambda: scale,
                       get_friend_drive=lambda name: drive.get(name, 0.0))


def test_friend_level_drives_an_idle_toy(clock):
    r = _router(clock, {"dev": 0.5})
    assert r._calculate_motor_target("dev", 0, _cfg(), {}, zones=set()) == pytest.approx(0.5)


def test_the_higher_of_friend_and_own_signal_wins(clock):
    r = _router(clock, {"dev": 0.5})
    assert r._calculate_motor_target("dev", 0, _cfg(), {"MyParam": 0.7},
                                     zones=set()) == pytest.approx(0.7)
    r = _router(clock, {"dev": 0.9})
    assert r._calculate_motor_target("dev", 0, _cfg(), {"MyParam": 0.7},
                                     zones=set()) == pytest.approx(0.9)


def test_strength_scales_it_and_off_silences_it(clock):
    assert _router(clock, {"dev": 0.8}, 0.5)._calculate_motor_target(
        "dev", 0, _cfg(), {}, zones=set()) == pytest.approx(0.4)
    assert _router(clock, {"dev": 0.8}, 0.0)._calculate_motor_target(
        "dev", 0, _cfg(), {}, zones=set()) == 0.0


def test_the_toys_own_output_band_still_holds(clock):
    r = _router(clock, {"dev": 1.0})
    out = r._calculate_motor_target("dev", 0, _cfg(band=(0.2, 0.6)), {}, zones=set())
    assert out == pytest.approx(0.6)      # never past the toy's own maximum
    r = _router(clock, {"dev": 0.5})
    out = r._calculate_motor_target("dev", 0, _cfg(band=(0.2, 0.6)), {}, zones=set())
    assert out == pytest.approx(0.4)      # remapped into the band, like routed output


def test_a_broken_hook_never_breaks_routing(clock):
    def boom(_name):
        raise RuntimeError("nope")
    r = MotorRouter(clock=clock.now, get_friend_drive=boom)
    assert r._calculate_motor_target("dev", 0, _cfg(), {"MyParam": 0.7},
                                     zones=set()) == pytest.approx(0.7)



def test_override_replaces_the_toys_own_output(clock):
    r = MotorRouter(clock=clock.now, get_master_scale=lambda: 1.0,
                    get_friend_drive=lambda name: (0.3, True))
    assert r._calculate_motor_target("dev", 0, _cfg(), {"MyParam": 0.9},
                                     zones=set()) == pytest.approx(0.3)
    r = MotorRouter(clock=clock.now, get_master_scale=lambda: 1.0,
                    get_friend_drive=lambda name: (0.0, True))
    assert r._calculate_motor_target("dev", 0, _cfg(), {"MyParam": 0.9}, zones=set()) == 0.0
    r = MotorRouter(clock=clock.now, get_master_scale=lambda: 0.5,
                    get_friend_drive=lambda name: (0.8, True))
    assert r._calculate_motor_target("dev", 0, _cfg(band=(0.2, 0.6)), {"MyParam": 0.9},
                                     zones=set()) == pytest.approx(0.2 + 0.4 * 0.4)
