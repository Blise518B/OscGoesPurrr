"""PiShockEngine is the last gate before a shock reaches a person, so its
rules are pinned here against a fake USB link and a fake clock: caps,
arming, the rest between pulses (and the stronger-pulse exception), hold
chunking, the forced break, Stop."""

import pytest

import pishock_engine as pe
import pishock_limits
from pishock_engine import PiShockEngine


class FakeLink:
    def __init__(self, shockers=(111, 222), kind="pishock"):
        self.sent = []
        self.port = "COM9"
        self.is_open = True
        self.kind = kind
        self.on_info = None
        self._info = {"version": "3.1", "type": 3,
                      "shockers": [{"id": s, "paused": False} for s in shockers]}

    def set_openshock_shockers(self, shockers):
        # Like the real link: an OpenShock hub's list is the page's.
        if self.kind == "openshock":
            self._info["shockers"] = [{"id": s["id"], "paused": False}
                                      for s in shockers]
            if self.on_info is not None:
                self.on_info(dict(self._info))

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
    clock = Clock()
    link = FakeLink()
    eng = PiShockEngine(link_factory=lambda **_k: link, clock=clock)
    eng.set_port("COM9")
    eng._want_connected = True
    eng._try_connect()
    assert eng.is_connected
    eng.set_limits(max_intensity=50, max_pulse_ms=1000, cooldown_s=0.5,
                   max_hold_s=10.0, hold_rest_s=2.0)
    link.sent.clear()
    return eng, link, clock


def test_connect_reads_the_shockers(rig):
    eng, _link, _clock = rig
    assert eng.shocker_ids() == [111, 222]
    assert eng.firmware == "3.1"


def test_intensity_and_length_are_capped(rig):
    eng, link, _clock = rig
    eng.set_armed(True)
    link.sent.clear()
    assert eng.pulse(111, "shock", 90, 5000)
    assert link.sent == [(111, "shock", 50, 1000)]


def test_limits_cannot_be_widened_past_the_absolute_ceilings(rig):
    eng, _link, _clock = rig
    eng.set_limits(max_intensity=500, max_pulse_ms=10 ** 9, cooldown_s=0,
                   max_hold_s=0, hold_rest_s=0)
    lim = eng.limits()
    assert lim["max_intensity"] == pishock_limits.ABS_MAX_INTENSITY
    assert lim["max_pulse_ms"] == pishock_limits.ABS_MAX_PULSE_MS
    assert lim["cooldown_s"] == pishock_limits.ABS_MIN_COOLDOWN_S


def test_shock_vibrates_until_armed(rig):
    eng, link, clock = rig
    eng.pulse(111, "shock", 20, 300)
    assert link.sent[-1][1] == "vibrate"
    eng.set_armed(True)
    clock.t += 5
    eng.pulse(111, "shock", 20, 300)
    assert link.sent[-1][1] == "shock"


def test_disarming_ends_what_is_running(rig):
    eng, link, _clock = rig
    eng.set_armed(True)
    eng.pulse(111, "shock", 20, 1000)
    link.sent.clear()
    eng.set_armed(False)
    assert (111, "end") in link.sent


def test_rest_counts_from_the_end_of_the_pulse(rig):
    eng, link, clock = rig
    assert eng.pulse(111, "vibrate", 20, 1000)
    clock.t += 1.2              # pulse ended 0.2 s ago, rest is 0.5 s
    assert not eng.pulse(111, "vibrate", 20, 300)
    clock.t += 0.4
    assert eng.pulse(111, "vibrate", 20, 300)


def test_the_rest_is_per_shocker(rig):
    eng, _link, _clock = rig
    assert eng.pulse(111, "vibrate", 20, 300)
    assert eng.pulse(222, "vibrate", 20, 300)


def test_a_stronger_pulse_may_take_over_a_running_one(rig):
    eng, link, clock = rig
    assert eng.pulse(111, "vibrate", 10, 500)
    clock.t += 0.01
    assert eng.pulse(111, "vibrate", 40, 500)       # hard tier arrived late
    assert not eng.pulse(111, "vibrate", 40, 500)   # equal: no
    assert not eng.pulse(111, "vibrate", 20, 500)   # weaker: no
    assert [s[2] for s in link.sent] == [10, 40]


def test_nothing_goes_out_while_stopped(rig):
    eng, link, _clock = rig
    eng.set_paused(True)
    link.sent.clear()
    assert not eng.pulse(111, "vibrate", 20, 300)
    eng.hold(111, "vibrate", 20)
    assert link.sent == []
    eng.set_paused(False)
    assert eng.pulse(111, "vibrate", 20, 300)


def test_hold_sends_chunks_and_refreshes_them(rig):
    eng, link, clock = rig
    eng.hold(111, "vibrate", 20)
    assert link.sent == [(111, "vibrate", 20, pe.HOLD_CHUNK_MS)]
    clock.t += 0.05
    eng.hold(111, "vibrate", 20)            # same value, not due: nothing
    assert len(link.sent) == 1
    clock.t += pe.HOLD_REFRESH_S
    eng.hold(111, "vibrate", 20)            # due: top the chunk up
    assert len(link.sent) == 2


def test_hold_resends_when_the_strength_moves(rig):
    eng, link, clock = rig
    eng.hold(111, "vibrate", 20)
    clock.t += 0.01
    eng.hold(111, "vibrate", 30)            # inside the change gap
    assert len(link.sent) == 1
    clock.t += pe.HOLD_CHANGE_GAP_S
    eng.hold(111, "vibrate", 30)
    assert link.sent[-1] == (111, "vibrate", 30, pe.HOLD_CHUNK_MS)


def test_release_ends_a_running_hold_once(rig):
    eng, link, _clock = rig
    eng.hold(111, "vibrate", 20)
    eng.release(111)
    eng.release(111)
    assert link.sent[-1] == (111, "end")
    assert link.sent.count((111, "end")) == 1


def test_release_without_a_hold_sends_nothing(rig):
    eng, link, _clock = rig
    eng.release(111)
    assert link.sent == []


def test_a_hold_is_forced_to_rest(rig):
    eng, link, clock = rig
    eng.hold(111, "vibrate", 20)
    clock.t += 10.0
    eng.hold(111, "vibrate", 20)
    assert link.sent[-1] == (111, "end")
    clock.t += 1.0
    n = len(link.sent)
    eng.hold(111, "vibrate", 20)             # still resting
    assert len(link.sent) == n
    clock.t += 1.5
    eng.hold(111, "vibrate", 20)             # rest over: a fresh hold
    assert link.sent[-1] == (111, "vibrate", 20, pe.HOLD_CHUNK_MS)


def test_a_pulse_owns_the_shocker_over_a_hold(rig):
    eng, link, clock = rig
    eng.hold(111, "vibrate", 10)
    eng.pulse(111, "vibrate", 40, 500)
    link.sent.clear()
    clock.t += 0.3
    eng.hold(111, "vibrate", 10)             # pulse still running
    assert link.sent == []
    clock.t += 0.3
    eng.hold(111, "vibrate", 10)             # pulse over: hold resumes
    assert link.sent == [(111, "vibrate", 10, pe.HOLD_CHUNK_MS)]


def test_end_all_keeps_the_rest_after_a_cut_short_pulse(rig):
    eng, _link, clock = rig
    eng.pulse(111, "vibrate", 20, 1000)
    clock.t += 0.1
    eng.end_all()
    assert not eng.pulse(111, "vibrate", 20, 300)
    clock.t += 0.6
    assert eng.pulse(111, "vibrate", 20, 300)


def test_a_lost_link_stops_sending_and_reports(rig):
    eng, link, _clock = rig
    states = []
    eng.set_state_callback(lambda: states.append(eng.is_connected))
    eng._on_lost("read failed")
    assert not eng.is_connected
    assert "disconnected" in eng.last_error
    assert states == [False]
    assert not eng.pulse(111, "vibrate", 20, 300)


def test_unknown_op_or_shocker_is_refused(rig):
    eng, link, _clock = rig
    assert not eng.pulse(111, "explode", 20, 300)
    assert not eng.pulse(999, "vibrate", 20, 300)
    assert link.sent == []


# ---- an OpenShock hub ---------------------------------------------------

@pytest.fixture
def os_rig():
    clock = Clock()
    link = FakeLink(shockers=(), kind="openshock")
    logged = []

    def factory(**k):
        link.on_info = k["on_info"]
        return link

    eng = PiShockEngine(link_factory=factory, clock=clock, log=logged.append)
    eng.set_openshock_shockers([{"id": 4321, "model": "caixianlin", "name": "Neck"},
                                {"id": 77, "model": "petrainer", "name": ""}])
    eng.set_port("COM9")
    eng._want_connected = True
    eng._try_connect()
    link.sent.clear()
    logged.clear()
    return eng, link, clock, logged


def test_an_openshock_hub_drives_the_pages_list(os_rig):
    eng, link, _clock, _logged = os_rig
    assert eng.hub_kind == "openshock"
    assert eng.shocker_ids() == [4321, 77]
    assert eng.pulse(4321, "vibrate", 20, 300)
    assert link.sent == [(4321, "vibrate", 20, 300)]


def test_a_shocker_taken_off_the_list_is_stopped_and_dropped(os_rig):
    eng, link, _clock, _logged = os_rig
    eng.hold(77, "vibrate", 30)
    link.sent.clear()
    eng.set_openshock_shockers([{"id": 4321, "model": "caixianlin", "name": "Neck"}])
    assert link.sent == [(77, "end")]
    assert eng.shocker_ids() == [4321]
    assert not eng.pulse(77, "vibrate", 20, 300)


def test_hub_refusals_reach_the_log_but_not_every_send(os_rig):
    eng, _link, clock, logged = os_rig
    eng._on_hub_error("Failed to send command")
    eng._on_hub_error("Failed to send command")
    assert len(logged) == 1 and "E-Stop" in logged[0]
    clock.t += 6.0
    eng._on_hub_error("Failed to send command")
    assert len(logged) == 2



def test_vibrates_have_their_own_cap(rig):
    eng, link, clock = rig
    eng.set_limits(max_intensity=20, max_pulse_ms=1000, cooldown_s=0.5,
                   max_hold_s=10.0, hold_rest_s=2.0, max_vibrate=80)
    assert eng.limits()["max_vibrate"] == 80
    eng.set_armed(True)
    link.sent.clear()
    eng.pulse(111, "vibrate", 95, 300)
    eng.pulse(222, "shock", 95, 300)
    assert link.sent == [(111, "vibrate", 80, 300), (222, "shock", 20, 300)]


def test_an_unarmed_shock_vibrates_under_the_vibrate_cap(rig):
    eng, link, _clock = rig
    eng.set_limits(max_intensity=50, max_pulse_ms=1000, cooldown_s=0.5,
                   max_hold_s=10.0, hold_rest_s=2.0, max_vibrate=10)
    eng.pulse(111, "shock", 40, 300)
    assert link.sent[-1] == (111, "vibrate", 10, 300)


def test_without_a_vibrate_cap_vibrates_share_the_shock_cap(rig):
    eng, _link, _clock = rig
    assert eng.limits()["max_vibrate"] == 50


def test_one_shocker_can_be_stopped(rig):
    eng, link, clock = rig
    eng.pulse(111, "vibrate", 10, 1000)
    eng.hold(222, "vibrate", 10)
    link.sent.clear()
    eng.end(111)
    assert link.sent == [(111, "end")]
    assert 111 not in eng.output_snapshot() and 222 in eng.output_snapshot()


def test_a_flickering_hold_still_gets_its_forced_break(rig):
    # An input hovering around its threshold lets go for a tick now and
    # then; a let-go shorter than the rest doesn't restart the clock.
    eng, link, clock = rig
    for _ in range(10):
        eng.hold(111, "vibrate", 20)
        clock.t += 0.95
        eng.release(111)
        clock.t += 0.05
    eng.hold(111, "vibrate", 20)
    assert link.sent[-1] == (111, "end")     # 10 s in: forced to rest
    clock.t += 2.5
    eng.release(111)
    clock.t += 2.5                           # a real rest: a fresh clock
    eng.hold(111, "vibrate", 20)
    assert link.sent[-1] == (111, "vibrate", 20, pe.HOLD_CHUNK_MS)


def test_a_stop_never_lands_between_deciding_a_pulse_and_sending_it(rig):
    # Stop on the GUI thread while a pulse is being sent on another: the
    # Stop's `end` must reach the hub after the pulse, never before it.
    import threading
    eng, link, _clock = rig
    in_send, go_on = threading.Event(), threading.Event()
    plain = FakeLink.operate

    def slow_operate(self, sid, op, intensity, duration_ms):
        in_send.set()
        go_on.wait(2.0)                      # the write is under way...
        return plain(self, sid, op, intensity, duration_ms)

    link.operate = slow_operate.__get__(link)
    sender = threading.Thread(target=eng.pulse, args=(111, "vibrate", 20, 500))
    sender.start()
    assert in_send.wait(2.0)
    stopper = threading.Thread(target=eng.set_paused, args=(True,))
    stopper.start()
    stopper.join(0.1)
    assert stopper.is_alive()                # ...so the Stop waits for it
    go_on.set()
    sender.join(2.0)
    stopper.join(2.0)
    assert link.sent[0] == (111, "vibrate", 20, 500)
    assert (111, "end") in link.sent[1:]


def test_your_names_ride_on_every_shocker_list(rig):
    eng, _link, _clock = rig
    eng.set_shocker_names({"111": "Collar"})
    assert [s.get("name") for s in eng.shockers()] == ["Collar", None]
    assert eng.shocker_ids() == [111, 222]                 # ids untouched
    eng.set_shocker_names({})
    assert eng.shockers()[0].get("name") is None


def test_each_shocker_is_capped_by_its_own_limits(rig):
    eng, link, _clock = rig
    eng.set_armed(True)
    eng.set_shocker_limits({"111": {"max_intensity": 10, "max_pulse_ms": 400},
                            "bogus": {"max_intensity": 99}})
    link.sent.clear()
    assert eng.pulse(111, "shock", 90, 5000)
    assert eng.pulse(222, "shock", 90, 5000)
    assert link.sent == [(111, "shock", 10, 400), (222, "shock", 50, 1000)]
    assert eng.limits_for(111) == {"max_intensity": 10, "max_vibrate": 50, "max_pulse_ms": 400}
    # the hub-wide caps still reach what a shocker has no own value for
    eng.set_limits(max_intensity=20, max_pulse_ms=800, cooldown_s=0.5,
                   max_hold_s=10.0, hold_rest_s=2.0, max_vibrate=70)
    assert eng.limits_for(111) == {"max_intensity": 10, "max_vibrate": 70, "max_pulse_ms": 400}
    eng.set_shocker_limits({"111": {"max_intensity": 10 ** 9}})   # can't pass the ceiling
    assert eng.limits_for(111)["max_intensity"] == 100


def test_a_shocker_switched_off_gets_nothing_and_is_listed_to_nobody(rig):
    """Its card's Off (not in use): the engine refuses it every send, stops
    what it was doing, and the lists rules and friends read leave it out --
    the page's own list still has it, to switch it back on."""
    eng, link, clock = rig
    eng.set_armed(True)
    eng.hold(222, "vibrate", 20)
    link.sent.clear()
    eng.set_shockers_off([222, "junk"])
    assert (222, "end") in link.sent                    # stopped at once
    link.sent.clear()
    assert not eng.pulse(222, "shock", 30, 500)
    eng.hold(222, "vibrate", 20)
    assert link.sent == []
    assert eng.shocker_ids() == [111]
    assert [s["id"] for s in eng.shockers()] == [111]
    assert [(s["id"], s["off"]) for s in eng.all_shockers()] == [(111, False), (222, True)]
    assert eng.pulse(111, "shock", 30, 500)             # the other one is untouched
    eng.set_shockers_off([])
    clock.t += 5
    assert eng.pulse(222, "vibrate", 10, 500) and eng.shocker_ids() == [111, 222]
