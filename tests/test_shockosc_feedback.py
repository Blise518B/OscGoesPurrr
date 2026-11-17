"""ShockOSC's feedback parameters from what the engine actually does
(shockosc_feedback.py): Active / DurationRemaining / Intensity while a
shock runs, Cooldown / CooldownPercentage through the rest after it, only
shocks counting (an unarmed shock is a vibrate), per group and as _Any --
and the sender: changes only, nothing while idle, a re-send after an
avatar change, everything back to resting when it lets go."""

import pytest

import shockosc_feedback as fb
from pishock_engine import PiShockEngine
from shockosc_feedback import ShockOscFeedback, compute


class FakeLink:
    def __init__(self, shockers=(1, 2)):
        self.sent = []
        self.port = "COM9"
        self.is_open = True
        self.kind = "pishock"
        self._info = {"version": "3.1", "shockers": [{"id": s, "paused": False}
                                                    for s in shockers]}

    def set_openshock_shockers(self, shockers):
        pass

    def open(self, port, handshake_timeout_s=6.0):
        return dict(self._info)

    def operate(self, sid, op, intensity, duration_ms):
        self.sent.append((sid, op, intensity, duration_ms))
        return True

    def end(self, sid):
        self.sent.append((sid, "end"))
        return True

    def close(self):
        self.is_open = False


class Clock:
    def __init__(self):
        self.t = 100.0

    def __call__(self):
        return self.t


@pytest.fixture
def rig():
    clock, link = Clock(), FakeLink()
    eng = PiShockEngine(link_factory=lambda **_k: link, clock=clock)
    eng.set_port("COM9")
    eng._want_connected = True
    eng._try_connect()
    eng.set_limits(max_intensity=60, max_pulse_ms=4000, cooldown_s=1.0,
                   max_hold_s=10.0, hold_rest_s=2.0)
    eng.set_armed(True)
    return eng, clock


def values(eng, groups, rests=None):
    now, act = eng.activity()
    return compute(groups, eng.shocker_ids(), act, now, rests)


def test_idle_is_all_resting(rig):
    eng, _clock = rig
    out, moving = values(eng, {"Collar": [1]})
    assert out == {"ShockOsc/Collar_Active": False, "ShockOsc/Collar_Cooldown": False,
                   "ShockOsc/Collar_CooldownPercentage": 0.0,
                   "ShockOsc/Collar_DurationRemaining": 0.0, "ShockOsc/Collar_Intensity": 0.0,
                   "ShockOsc/_Any_Active": False, "ShockOsc/_Any_Cooldown": False,
                   "ShockOsc/_Any_CooldownPercentage": 0.0,
                   "ShockOsc/_Any_DurationRemaining": 0.0, "ShockOsc/_Any_Intensity": 0.0}
    assert moving is False


def test_a_shock_runs_then_rests(rig):
    eng, clock = rig
    assert eng.pulse(1, "shock", 40, 2000)
    clock.t += 0.5
    out, moving = values(eng, {"Collar": [1], "Tail": [2]})
    assert out["ShockOsc/Collar_Active"] is True and moving
    assert out["ShockOsc/Collar_DurationRemaining"] == pytest.approx(0.75)
    assert out["ShockOsc/Collar_Intensity"] == pytest.approx(0.40)
    assert out["ShockOsc/Collar_Cooldown"] is False
    assert out["ShockOsc/Tail_Active"] is False            # another group's shocker
    assert out["ShockOsc/_Any_Active"] is True and out["ShockOsc/_Any_Intensity"] == 0.4
    clock.t += 1.75                                        # ended 0.25 s ago, 1 s rest
    out, moving = values(eng, {"Collar": [1]})
    assert out["ShockOsc/Collar_Active"] is False and out["ShockOsc/Collar_Cooldown"] is True
    assert out["ShockOsc/Collar_CooldownPercentage"] == pytest.approx(0.75)
    assert out["ShockOsc/Collar_Intensity"] == pytest.approx(0.40)   # kept through the rest
    assert out["ShockOsc/Collar_DurationRemaining"] == 0.0
    assert out["ShockOsc/_Any_Cooldown"] is True and moving
    clock.t += 1.0
    out, moving = values(eng, {"Collar": [1]})
    assert not out["ShockOsc/Collar_Cooldown"] and out["ShockOsc/Collar_Intensity"] == 0.0
    assert moving is False


def test_the_intensity_is_what_went_out_after_the_caps(rig):
    eng, _clock = rig
    eng.pulse(1, "shock", 95, 1000)                  # capped at 60
    out, _ = values(eng, {"Collar": [1]})
    assert out["ShockOsc/Collar_Intensity"] == pytest.approx(0.60)


def test_only_shocks_count(rig):
    eng, clock = rig
    eng.pulse(1, "vibrate", 40, 1000)
    out, moving = values(eng, {"Collar": [1]})
    assert not out["ShockOsc/Collar_Active"] and not out["ShockOsc/_Any_Active"]
    # a shock that isn't armed goes out as a vibrate: nothing lights up
    clock.t += 5
    eng.set_armed(False)
    eng.pulse(1, "shock", 40, 1000)
    out, _ = values(eng, {"Collar": [1]})
    assert not out["ShockOsc/Collar_Active"]


def test_a_held_shock_is_active_with_no_end(rig):
    eng, _clock = rig
    eng.hold(2, "shock", 30, source="friend")
    out, moving = values(eng, {"Tail": [2], "_All": "all"})
    assert out["ShockOsc/Tail_Active"] and out["ShockOsc/Tail_DurationRemaining"] == 1.0
    assert out["ShockOsc/Tail_Intensity"] == pytest.approx(0.30)
    assert out["ShockOsc/_All_Active"] and moving
    eng.release(2, source="friend")
    out, _ = values(eng, {"Tail": [2]})
    assert not out["ShockOsc/Tail_Active"]


def test_a_hold_nobody_tops_up_stops_counting_with_its_chunk(rig):
    eng, clock = rig
    eng.hold(2, "shock", 30, source="gone")     # ...and never again, never released
    clock.t += 0.2
    assert values(eng, {"Tail": [2]})[0]["ShockOsc/Tail_Active"]
    clock.t += 0.2                              # past the 0.3 s chunk: the hub stopped
    out, _ = values(eng, {"Tail": [2]})
    assert not out["ShockOsc/Tail_Active"]


def test_a_stop_ends_active_at_once(rig):
    eng, clock = rig
    eng.pulse(1, "shock", 40, 3000)
    clock.t += 0.2
    eng.end_all()
    out, _ = values(eng, {"Collar": [1]})
    assert not out["ShockOsc/Collar_Active"] and out["ShockOsc/Collar_Cooldown"]


def test_the_avatars_longer_rest_counts(rig):
    eng, clock = rig
    eng.pulse(1, "shock", 40, 1000)
    shock_end = clock.t + 1.0
    rests = {"collar": (shock_end, 5.0)}            # the router's, by group key
    clock.t += 3.0                                  # the engine's 1 s rest is over
    out, moving = values(eng, {"Collar": [1]}, rests)
    assert out["ShockOsc/Collar_Cooldown"] is True and moving
    assert out["ShockOsc/Collar_CooldownPercentage"] == pytest.approx(0.6)
    assert out["ShockOsc/_Any_Cooldown"] is True


def test_a_group_with_no_shocker_rests_and_any_counts_every_shocker(rig):
    eng, _clock = rig
    eng.pulse(2, "shock", 20, 1000)               # a friend's, say
    out, _ = values(eng, {"Glow": []})
    assert not out["ShockOsc/Glow_Active"] and out["ShockOsc/_Any_Active"]


def test_a_switched_off_shocker_isnt_listed(rig):
    eng, _clock = rig
    eng.pulse(2, "shock", 20, 1000)
    eng.set_shockers_off([2])
    out, _ = values(eng, {"_All": "all"})
    assert not out["ShockOsc/_All_Active"]


# --- the sender ------------------------------------------------------------------

class Sink:
    def __init__(self, up=True):
        self.sent = []
        self.up = up

    def __call__(self, name, value):
        if self.up:
            self.sent.append((name, value))
        return self.up


def sender(rig, sink, rests=dict):
    eng, _clock = rig
    return ShockOscFeedback(eng.activity, eng.shocker_ids, sink, get_rests=rests)


def test_nothing_without_groups(rig):
    sink = Sink()
    f = sender(rig, sink)
    assert f.tick() is False and sink.sent == []


def test_sends_once_then_only_changes(rig):
    eng, clock = rig
    sink = Sink()
    f = sender(rig, sink)
    f.set_groups({"Collar": [1]})
    f.tick()
    assert len(sink.sent) == 10                 # everything once
    sink.sent.clear()
    f.tick()
    assert sink.sent == []                      # idle: nothing
    eng.pulse(1, "shock", 40, 1000)
    assert f.tick() is True
    sent = dict(sink.sent)
    assert sent["ShockOsc/Collar_Active"] is True and sent["ShockOsc/_Any_Active"] is True
    assert "ShockOsc/Collar_Cooldown" not in sent          # unchanged: not re-sent
    sink.sent.clear()
    clock.t += 0.5
    f.tick()
    assert dict(sink.sent) == {"ShockOsc/Collar_DurationRemaining": 0.5,
                               "ShockOsc/_Any_DurationRemaining": 0.5}


def test_a_resend_after_an_avatar_change(rig):
    sink = Sink()
    f = sender(rig, sink)
    f.set_groups({"Collar": [1]})
    f.tick()
    sink.sent.clear()
    f.resend()
    f.tick()
    assert len(sink.sent) == 10


def test_a_link_down_sends_it_again_later(rig):
    sink = Sink(up=False)
    f = sender(rig, sink)
    f.set_groups({"Collar": [1]})
    f.tick()
    sink.up = True
    f.tick()
    assert len(sink.sent) == 10


def test_only_what_the_avatar_has(rig):
    sink = Sink()
    f = sender(rig, sink)
    f.set_groups({"Collar": [1]}, only={"ShockOsc/Collar_Active", "ShockOsc/_Any_Cooldown"})
    f.tick()
    assert {n for n, _v in sink.sent} == {"ShockOsc/Collar_Active", "ShockOsc/_Any_Cooldown"}


def test_a_group_gone_goes_back_to_resting_once(rig):
    eng, _clock = rig
    sink = Sink()
    f = sender(rig, sink)
    f.set_groups({"Collar": [1]})
    eng.pulse(1, "shock", 40, 1000)
    f.tick()
    sink.sent.clear()
    f.set_groups({})
    f.tick()
    sent = dict(sink.sent)
    assert sent["ShockOsc/Collar_Active"] is False and sent["ShockOsc/Collar_Intensity"] == 0.0
    assert "ShockOsc/Collar_Cooldown" not in sent         # was resting already
    sink.sent.clear()
    f.tick()
    assert sink.sent == []


def test_let_go_rests_everything(rig):
    eng, _clock = rig
    sink = Sink()
    f = sender(rig, sink)
    f.set_groups({"Collar": [1]})
    eng.pulse(1, "shock", 40, 1000)
    f.tick()
    sink.sent.clear()
    f.let_go()
    assert ("ShockOsc/Collar_Active", False) in sink.sent
    assert ("ShockOsc/_Any_Active", False) in sink.sent


def test_the_engine_wakes_it_on_every_write(rig):
    eng, _clock = rig
    woken = []
    eng.set_activity_callback(lambda: woken.append(1))
    eng.pulse(1, "shock", 40, 500)
    assert len(woken) == 1
    eng.hold(2, "vibrate", 20, source="x")
    eng.release(2, source="x")
    eng.end(1)
    assert len(woken) == 4


def test_the_thread_sleeps_until_woken(rig):
    import threading
    eng, _clock = rig
    ticks = []
    f = sender(rig, Sink())
    real = f.tick
    f.tick = lambda: (ticks.append(1), real())[1]
    f.set_groups({"Collar": [1]})
    f.start()
    try:
        deadline = threading.Event()
        deadline.wait(0.3)
        settled = len(ticks)
        assert settled >= 1                       # the groups' wake
        deadline.wait(0.3)
        assert len(ticks) == settled              # idle: no polling
        f.wake()
        deadline.wait(0.2)
        assert len(ticks) == settled + 1
    finally:
        f.stop()


def test_default_of():
    assert fb.default_of("ShockOsc/Collar_Active") is False
    assert fb.default_of("ShockOsc/_Any_CooldownPercentage") == 0.0
