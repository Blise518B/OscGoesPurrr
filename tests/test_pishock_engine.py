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


def test_a_pulse_owns_the_shocker_over_a_hold_then_its_rest(rig):
    eng, link, clock = rig                   # rest after a pulse 0.5 s
    eng.hold(111, "vibrate", 10)
    eng.pulse(111, "vibrate", 40, 500)
    link.sent.clear()
    clock.t += 0.3
    eng.hold(111, "vibrate", 10)             # pulse still running
    assert link.sent == []
    clock.t += 0.3
    eng.hold(111, "vibrate", 10)             # pulse over, its rest not yet
    assert link.sent == []
    clock.t += 0.45
    eng.hold(111, "vibrate", 10)             # rest over: hold resumes
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


# ---- several sources holding one shocker ---------------------------------
# The rules, the avatar menu, each friend, the web remote and a friend's
# warning each hold on their own; the shocker plays the strongest, and one
# of them letting go ends only its own hold. Caps, the longest hold and the
# rest after it stay the shocker's, for all of them together.

def _levels(link, sid=111):
    return [s[2] for s in link.sent if s[0] == sid and s[1] != "end"]


def test_two_sources_on_one_shocker_play_the_stronger(rig):
    eng, link, clock = rig
    for _ in range(20):                      # both tick, a little apart
        eng.hold(111, "vibrate", 30, source="friend:a")
        clock.t += 0.05
        eng.hold(111, "vibrate", 45, source="friend:b")
        clock.t += 0.05
    sent = _levels(link)
    assert sent[0] == 30                     # a came first
    assert set(sent[1:]) == {45}             # then b's, steadily -- no flip-flop
    assert (111, "end") not in link.sent


def test_one_source_letting_go_leaves_the_others_hold_running(rig):
    eng, link, clock = rig
    eng.hold(111, "vibrate", 30, source="rules")
    clock.t += 0.1
    eng.hold(111, "vibrate", 45, source="friend:a")
    assert _levels(link)[-1] == 45
    link.sent.clear()
    clock.t += 0.01
    eng.release(111, source="friend:a")      # the stronger lets go
    assert link.sent == [(111, "vibrate", 30, pe.HOLD_CHUNK_MS)]   # at once, no cut
    clock.t += 0.1
    eng.hold(111, "vibrate", 30, source="rules")
    assert (111, "end") not in link.sent
    eng.release(111, source="rules")         # the last one lets go: now it ends
    assert link.sent[-1] == (111, "end")
    assert 111 not in eng.output_snapshot()


def test_the_weaker_letting_go_changes_nothing(rig):
    eng, link, clock = rig
    eng.hold(111, "vibrate", 45, source="friend:a")
    eng.hold(111, "vibrate", 20, source="friend:b")
    link.sent.clear()
    eng.release(111, source="friend:b")
    eng.release(111, source="friend:b")      # twice, or one that never held
    eng.release(111, source="friend:c")
    assert link.sent == []
    assert eng.output_snapshot()[111]["intensity"] == 45


def test_a_shock_beats_a_vibrate_at_the_same_strength(rig):
    eng, link, clock = rig
    eng.set_armed(True)
    eng.hold(111, "vibrate", 30, source="friend:a")
    clock.t += 0.1
    eng.hold(111, "shock", 30, source="rules")
    clock.t += 0.1
    eng.hold(111, "vibrate", 30, source="friend:a")
    assert link.sent[-1] == (111, "shock", 30, pe.HOLD_CHUNK_MS)



def test_any_held_shock_beats_any_vibrate_whatever_the_levels(rig):
    # Blise's call (2026-11-14): the shockers have priority. A shock at 30
    # plays over a vibrate at 40, steadily, and only once the shock lets go
    # does the vibrate take over.
    eng, link, clock = rig
    eng.set_armed(True)
    eng.hold(111, "vibrate", 40, source="friend:a")
    clock.t += 0.05
    eng.hold(111, "shock", 30, source="rules")
    for _ in range(10):
        clock.t += 0.05
        eng.hold(111, "vibrate", 40, source="friend:a")
        clock.t += 0.05
        eng.hold(111, "shock", 30, source="rules")
    after = link.sent[1:]
    assert link.sent[0] == (111, "vibrate", 40, pe.HOLD_CHUNK_MS)
    assert after and set(after) == {(111, "shock", 30, pe.HOLD_CHUNK_MS)}
    eng.release(111, source="friend:a")          # the vibrate going changes nothing
    assert link.sent[-1] == (111, "shock", 30, pe.HOLD_CHUNK_MS)
    eng.hold(111, "vibrate", 40, source="friend:a")
    clock.t += 0.05
    eng.release(111, source="rules")             # the shock going hands over, no end
    assert link.sent[-1] == (111, "vibrate", 40, pe.HOLD_CHUNK_MS)
    assert not any(s[1] == "end" for s in link.sent)


def test_among_shocks_the_strongest_wins(rig):
    eng, link, clock = rig
    eng.set_armed(True)
    eng.hold(111, "shock", 20, source="friend:a")
    clock.t += 0.1
    eng.hold(111, "vibrate", 50, source="friend:b")
    clock.t += 0.1
    eng.hold(111, "shock", 35, source="rules")
    assert link.sent[-1] == (111, "shock", 35, pe.HOLD_CHUNK_MS)
    assert all(s[1] == "shock" for s in link.sent)


def test_an_unarmed_shock_ranks_as_the_vibrate_it_becomes(rig):
    # Unarmed, the shock goes out as a vibrate at 30, so the vibrate at 40
    # is the stronger of the two; armed, the shock wins.
    eng, link, clock = rig
    eng.hold(111, "vibrate", 40, source="friend:a")
    clock.t += 0.1
    eng.hold(111, "shock", 30, source="rules")
    clock.t += 0.1
    eng.hold(111, "vibrate", 40, source="friend:a")
    assert set(link.sent) == {(111, "vibrate", 40, pe.HOLD_CHUNK_MS)}
    eng.set_armed(True)
    clock.t += 0.1
    eng.hold(111, "vibrate", 40, source="friend:a")
    clock.t += 0.1
    eng.hold(111, "shock", 30, source="rules")
    assert link.sent[-1] == (111, "shock", 30, pe.HOLD_CHUNK_MS)


def test_any_vibrate_beats_any_beep(rig):
    eng, link, clock = rig
    eng.hold(111, "beep", 50, source="friend:a")
    clock.t += 0.1
    eng.hold(111, "vibrate", 10, source="friend:b")
    clock.t += 0.1
    eng.hold(111, "beep", 50, source="friend:a")
    assert link.sent[-1] == (111, "vibrate", 10, pe.HOLD_CHUNK_MS)

def test_every_source_is_capped_and_unarmed_shocks_vibrate(rig):
    eng, link, clock = rig
    eng.set_limits(max_intensity=20, max_pulse_ms=1000, cooldown_s=0.5,
                   max_hold_s=10.0, hold_rest_s=2.0, max_vibrate=25)
    eng.hold(111, "shock", 90, source="friend:a")        # not armed
    clock.t += 0.1
    eng.hold(111, "vibrate", 90, source="friend:b")
    clock.t += 0.3
    eng.hold(111, "shock", 90, source="friend:a")
    assert set(link.sent) == {(111, "vibrate", 25, pe.HOLD_CHUNK_MS)}


def test_a_lowered_cap_holds_for_holds_already_running(rig):
    eng, link, clock = rig
    eng.hold(111, "vibrate", 50, source="friend:a")
    eng.set_limits(max_intensity=15, max_pulse_ms=1000, cooldown_s=0.5,
                   max_hold_s=10.0, hold_rest_s=2.0)
    clock.t += 0.1
    eng.hold(111, "vibrate", 5, source="friend:b")       # a's 50 is no longer allowed
    assert link.sent[-1] == (111, "vibrate", 15, pe.HOLD_CHUNK_MS)


def test_a_source_that_went_quiet_stops_counting(rig):
    # One that stops topping its hold up (without letting go) ends within a
    # chunk, as it would with nobody else holding -- another source's ticks
    # don't keep it alive.
    eng, link, clock = rig
    eng.hold(111, "vibrate", 45, source="friend:a")
    for _ in range(5):
        clock.t += 0.125
        eng.hold(111, "vibrate", 20, source="rules")
    assert _levels(link) == [45, 45, 20, 20]  # a's, topped up once, then the rules'
    assert pe.HOLD_SOURCE_TTL_S * 1000 <= pe.HOLD_CHUNK_MS


def test_the_longest_hold_counts_every_source_together(rig):
    eng, link, clock = rig                   # max hold 10 s, rest 2 s
    t0 = clock.t
    while clock.t - t0 < 6.0:                # a holds for 6 s ...
        eng.hold(111, "vibrate", 20, source="friend:a")
        if clock.t - t0 >= 4.0:              # ... b joins at 4 s
            eng.hold(111, "vibrate", 30, source="friend:b")
        clock.t += 0.1
    eng.release(111, source="friend:a")
    while clock.t - t0 < 9.9:                # b alone: still the same hold
        eng.hold(111, "vibrate", 30, source="friend:b")
        assert link.sent[-1] != (111, "end")
        clock.t += 0.1
    clock.t = t0 + 10.0
    eng.hold(111, "vibrate", 30, source="friend:b")
    assert link.sent[-1] == (111, "end")     # 10 s since a began: rest
    n = len(link.sent)
    clock.t += 1.0
    for src in ("friend:a", "friend:b", "rules", "warning:c:0"):
        eng.hold(111, "vibrate", 40, source=src)         # everyone rests
    assert len(link.sent) == n
    assert eng.output_snapshot()[111]["kind"] == "rest"
    clock.t += 1.5
    eng.hold(111, "vibrate", 40, source="rules")         # rest over: a fresh hold
    assert link.sent[-1] == (111, "vibrate", 40, pe.HOLD_CHUNK_MS)


def test_handing_a_hold_over_doesnt_restart_the_clock(rig):
    # One lets go and another takes over within the rest: one hold, still
    # forced to rest 10 s after the first began.
    eng, link, clock = rig
    t0 = clock.t
    while clock.t - t0 < 5.0:
        eng.hold(111, "vibrate", 20, source="friend:a")
        clock.t += 0.1
    eng.release(111, source="friend:a")
    clock.t += 0.5
    while clock.t - t0 < 10.0:
        eng.hold(111, "vibrate", 20, source="friend:b")
        clock.t += 0.1
    eng.hold(111, "vibrate", 20, source="friend:b")
    assert link.sent[-1] == (111, "end")


def test_end_end_all_pause_and_off_stop_every_source(rig):
    eng, link, clock = rig

    def both():
        eng.hold(111, "vibrate", 30, source="friend:a")
        eng.hold(111, "vibrate", 40, source="rules")

    for stop in (lambda: eng.end(111), eng.end_all,
                 lambda: eng.set_paused(True), lambda: eng.set_shockers_off([111])):
        eng.set_paused(False)
        eng.set_shockers_off([])
        clock.t += 3.0
        both()
        assert 111 in eng.output_snapshot()
        link.sent.clear()
        stop()
        assert (111, "end") in link.sent
        assert eng.output_snapshot().get(111, {}).get("kind") != "hold"
        link.sent.clear()
        eng.release(111, source="friend:a")  # nothing left to let go of
        eng.release(111, source="rules")
        assert link.sent == []


def test_a_hold_without_a_source_is_one_hold_as_before(rig):
    eng, link, clock = rig
    eng.hold(111, "vibrate", 20)
    clock.t += 0.1
    eng.hold(111, "vibrate", 30)              # the same source moving
    eng.release(111)
    assert link.sent[-1] == (111, "end")


# ---- each shocker's Shock / Vibrate / Beep switch -------------------------
# Enforced here like a shocker's Off: an op switched off is refused whoever
# sends it, and one running when it is switched off stops at once.

def test_an_op_switched_off_is_refused_on_that_shocker_only(rig):
    eng, link, clock = rig
    eng.set_armed(True)
    link.sent.clear()
    eng.set_ops_off({"111": ["shock", "junk"], "bad": ["beep"]})
    assert eng.ops_off() == {111: ["shock"]}
    assert not eng.op_allowed(111, "shock") and eng.op_allowed(111, "vibrate")
    assert not eng.pulse(111, "shock", 30, 500)
    eng.hold(111, "shock", 30, source="friend:a")
    assert link.sent == []
    assert eng.pulse(222, "shock", 30, 500)              # the other one still shocks
    assert eng.pulse(111, "vibrate", 30, 500)            # and this one still vibrates
    assert link.sent == [(222, "shock", 30, 500), (111, "vibrate", 30, 500)]


def test_switching_an_op_off_stops_it_now_and_keeps_the_others_holds(rig):
    eng, link, clock = rig
    eng.set_armed(True)
    eng.hold(111, "shock", 40, source="friend:a")
    eng.hold(111, "vibrate", 20, source="rules")
    assert link.sent[-1][1] == "shock"
    link.sent.clear()
    eng.set_ops_off({111: ["shock"]})
    assert link.sent == [(111, "end")]                    # the shock stops at once
    clock.t += 0.1
    eng.hold(111, "vibrate", 20, source="rules")          # the vibrate goes on
    eng.hold(111, "shock", 40, source="friend:a")         # the shock stays refused
    assert link.sent[-1] == (111, "vibrate", 20, pe.HOLD_CHUNK_MS)
    assert all(s[1] != "shock" for s in link.sent)


def test_a_pulse_running_when_its_op_is_switched_off_stops(rig):
    eng, link, clock = rig
    assert eng.pulse(111, "beep", 1, 1000)
    link.sent.clear()
    eng.set_ops_off({111: ["vibrate"]})                   # not the beep: it runs on
    assert link.sent == []
    eng.set_ops_off({111: ["vibrate", "beep"]})
    assert link.sent == [(111, "end")]


def test_an_unarmed_shock_with_vibrate_off_is_refused(rig):
    """A shock that isn't armed goes out as a vibrate: with Vibrate off it
    has nowhere to go."""
    eng, link, _clock = rig
    eng.set_ops_off({111: ["vibrate"]})
    assert not eng.op_allowed(111, "shock")
    assert not eng.pulse(111, "shock", 30, 500)
    eng.set_armed(True)
    assert eng.op_allowed(111, "shock") and eng.pulse(111, "shock", 30, 500)


def test_a_shock_with_shock_off_follows_the_one_decision(rig, monkeypatch):
    """Blise's open call (b) is one constant: dropped by default, or sent as
    a vibrate like an unarmed shock."""
    eng, link, clock = rig
    eng.set_armed(True)
    eng.set_ops_off({111: ["shock"]})
    assert pe.SHOCK_OFF_AS_VIBRATE is False
    assert not eng.pulse(111, "shock", 30, 500) and link.sent == []
    monkeypatch.setattr(pe, "SHOCK_OFF_AS_VIBRATE", True)
    assert eng.pulse(111, "shock", 30, 500)
    assert link.sent == [(111, "vibrate", 30, 500)]
    eng.set_ops_off({111: ["shock", "vibrate"]})          # and nowhere to go at all
    clock.t += 5
    assert not eng.pulse(111, "shock", 30, 500)


def test_the_switches_never_widen_a_cap_or_skip_arming(rig):
    eng, link, clock = rig
    eng.set_ops_off({111: ["beep"]})
    assert eng.pulse(111, "shock", 99, 9000)              # not armed: a vibrate, capped
    assert link.sent == [(111, "vibrate", 50, 1000)]


# --- the rules hold for every source (Blise's call, 2026-11-16) ------------------

def test_a_run_of_stronger_pulses_from_anyone_never_outlasts_the_longest_pulse(rig):
    eng, link, clock = rig                   # longest pulse 1 s, rest 0.5 s
    assert eng.pulse(111, "vibrate", 10, 1000)               # nothing passed: the caller's own
    clock.t += 0.6
    sent = eng.pulse(111, "vibrate", 20, 1000)               # takes over: 0.4 s left
    assert link.sent[-1] == (111, "vibrate", 20, 400)
    assert (sent.duration_ms, sent.cut) == (400, pe.CUT_RUN)
    clock.t += 0.35
    assert eng.pulse(111, "vibrate", 30, 1000) is None       # 50 ms left: none


def test_a_shorter_run_cap_is_kept_and_a_longer_one_widens_nothing(rig):
    eng, link, clock = rig
    sent = eng.pulse(111, "vibrate", 10, 1000, run_cap_ms=600)
    assert link.sent[-1] == (111, "vibrate", 10, 600) and sent.cut == pe.CUT_LONGEST
    clock.t += 2.0
    eng.pulse(111, "vibrate", 10, 1000, run_cap_ms=5000)
    assert link.sent[-1] == (111, "vibrate", 10, 1000)


def test_no_pulse_goes_in_during_the_rest_after_the_longest_hold_whoever_sends_it(rig):
    eng, link, clock = rig                   # longest hold 10 s, then 2 s of rest
    eng.hold(111, "vibrate", 10)
    clock.t += 10.0
    eng.hold(111, "vibrate", 10)             # the longest hold: a forced rest
    assert eng.is_resting(111)
    clock.t += 1.0
    assert eng.pulse(111, "vibrate", 10, 300) is None
    clock.t += 1.1
    assert not eng.is_resting(111)
    assert eng.pulse(111, "vibrate", 10, 300)


def test_a_hold_right_after_a_pulse_waits_for_its_rest_whoever_holds(rig):
    eng, link, clock = rig                   # rest after a pulse 0.5 s
    eng.pulse(111, "vibrate", 30, 300)
    link.sent.clear()
    clock.t += 0.4                           # the pulse is over, its rest isn't
    eng.hold(111, "vibrate", 10, source="rules")
    eng.hold(111, "vibrate", 10, source=("friend", "x", 0))
    assert link.sent == []
    assert eng.hold_free_in(111) == pytest.approx(0.4)
    clock.t += 0.45
    eng.hold(111, "vibrate", 10, source="rules")
    assert link.sent == [(111, "vibrate", 10, pe.HOLD_CHUNK_MS)]
    assert eng.hold_free_in(111) == 0.0


def test_a_pulse_says_what_went_out(rig):
    eng, _link, clock = rig                  # ceiling 50, longest 1 s, not armed
    sent = eng.pulse(111, "shock", 80, 3000)
    assert sent == pe.Sent("vibrate", 50, 1000, capped=True, cut=pe.CUT_LONGEST)
    clock.t += 2.0
    assert eng.pulse(111, "vibrate", 20, 300) == pe.Sent("vibrate", 20, 300)


def test_went_out_takes_a_stand_in_engines_true_as_the_pulse_asked():
    assert pe.went_out(True, "beep", 1, 300) == pe.Sent("beep", 1, 300)
    assert pe.went_out(False, "beep", 1, 300) is None
    assert pe.went_out(None, "beep", 1, 300) is None


# --- a shock always takes over a vibrate or a beep (Blise's call, 2026-11-17) ----------

def test_a_shock_takes_over_a_running_vibrate_whatever_the_levels(rig):
    eng, link, clock = rig
    eng.set_armed(True)
    assert eng.pulse(111, "vibrate", 50, 800)
    clock.t += 0.1
    assert eng.pulse(111, "shock", 5, 800)                   # however weak
    clock.t += 0.1
    assert not eng.pulse(111, "vibrate", 50, 800)            # a vibrate never takes over a shock
    assert [(s[1], s[2]) for s in link.sent] == [("vibrate", 50), ("shock", 5)]


def test_a_vibrate_takes_over_a_running_beep_and_a_beep_nothing(rig):
    eng, link, clock = rig
    assert eng.pulse(111, "beep", 50, 800)
    clock.t += 0.1
    assert eng.pulse(111, "vibrate", 1, 800)
    clock.t += 0.1
    assert not eng.pulse(111, "beep", 50, 800)
    assert [s[1] for s in link.sent] == ["beep", "vibrate"]


def test_an_unarmed_shock_takes_over_only_as_the_vibrate_it_is(rig):
    eng, link, clock = rig                                    # not armed
    assert eng.pulse(111, "vibrate", 30, 800)
    clock.t += 0.1
    assert not eng.pulse(111, "shock", 10, 800)              # a vibrate 10: weaker
    assert eng.pulse(111, "shock", 40, 800)                  # a vibrate 40: stronger
    assert [(s[1], s[2]) for s in link.sent] == [("vibrate", 30), ("vibrate", 40)]


def test_a_take_over_by_kind_keeps_the_run_cap(rig):
    eng, link, clock = rig                                    # longest pulse 1 s
    eng.set_armed(True)
    assert eng.pulse(111, "vibrate", 50, 1000)
    clock.t += 0.6
    sent = eng.pulse(111, "shock", 5, 1000)
    assert link.sent[-1] == (111, "shock", 5, 400) and sent.cut == pe.CUT_RUN


# --- separate limits for friends (Blise's call, 2026-11-17) --------------------------

FRIENDS = pe.GROUP_FRIENDS


def test_off_a_friends_longest_hold_rests_your_avatar_too(rig):
    eng, _link, clock = rig                   # longest hold 10 s, then 2 s of break
    eng.hold(111, "vibrate", 10, source="f", group=FRIENDS)
    clock.t += 10.0
    eng.hold(111, "vibrate", 10, source="f", group=FRIENDS)  # the forced break
    assert eng.is_resting(111, FRIENDS) and eng.is_resting(111)   # one count for everyone
    clock.t += 0.5
    assert eng.pulse(111, "vibrate", 10, 300) is None


def test_on_a_friends_longest_hold_never_blocks_your_contact_shocks(rig):
    eng, link, clock = rig
    eng.set_separate_limits(True, {"cooldown_s": 0.5, "max_hold_s": 10.0, "hold_rest_s": 2.0})
    eng.hold(111, "vibrate", 10, source="f", group=FRIENDS)
    clock.t += 10.0
    eng.hold(111, "vibrate", 10, source="f", group=FRIENDS)  # their forced break
    assert eng.is_resting(111, FRIENDS) and not eng.is_resting(111)
    clock.t += 0.5
    assert eng.pulse(111, "vibrate", 10, 300)                # your avatar's goes
    n = len(link.sent)
    clock.t += 1.0
    eng.hold(111, "vibrate", 10, source="f", group=FRIENDS)  # theirs still rests
    assert len(link.sent) == n


def test_on_your_avatars_hold_plays_on_through_a_friends_forced_break(rig):
    eng, link, clock = rig                    # yours: longest hold 10 s
    eng.set_separate_limits(True, {"max_hold_s": 5.0})
    for _ in range(30):
        eng.hold(111, "vibrate", 30, source="f", group=FRIENDS)   # the stronger, it plays
        eng.hold(111, "vibrate", 10, source="rules")
        clock.t += 0.2
    assert eng.is_resting(111, FRIENDS)
    assert link.sent[-1][:3] == (111, "vibrate", 10)          # yours took over at once
    assert (111, "end") not in link.sent


def test_on_friends_keep_to_their_own_timing(rig):
    eng, _link, clock = rig                   # yours: a rest of 0.5 s after a pulse
    eng.set_separate_limits(True, {"cooldown_s": 3.0})
    assert eng.timing_for(FRIENDS)["cooldown_s"] == 3.0
    assert eng.timing_for(pe.GROUP_AVATAR)["cooldown_s"] == 0.5
    assert eng.pulse(111, "vibrate", 10, 300, group=FRIENDS)
    clock.t += 1.0
    assert eng.pulse(111, "vibrate", 10, 300, group=FRIENDS) is None   # their 3 s
    assert eng.pulse(111, "vibrate", 10, 300)                          # yours is over


def test_the_friends_set_is_clamped_like_the_others(rig):
    eng, _link, _clock = rig
    eng.set_separate_limits(True, {"cooldown_s": 10 ** 400, "max_hold_s": 1e9,
                                   "hold_rest_s": -5})
    lim = eng.timing_for(FRIENDS)
    assert lim["max_hold_s"] == pishock_limits.RANGES["max_hold_s"][1]
    assert lim["hold_rest_s"] == pishock_limits.RANGES["hold_rest_s"][0]
    assert lim["cooldown_s"] == 0.5          # no number at all: yours, the stricter


# friends' own caps while separate (Blise's call, 2026-11-17): they only ever
# lower a shocker's own, for friends; your avatar keeps the shocker's own

FRIEND_CAPS = {"max_intensity": 20, "max_vibrate": 15, "max_pulse_ms": 400}


def test_on_a_friend_is_capped_at_the_friends_values_your_avatar_is_not(rig):
    eng, link, clock = rig                    # every shocker: 50, a pulse of 1 s
    eng.set_armed(True)
    eng.set_separate_limits(True, FRIEND_CAPS)
    sent = eng.pulse(111, "shock", 100, 5000, group=FRIENDS)
    assert (sent.intensity, sent.duration_ms, sent.capped) == (20, 400, True)
    assert sent.cut == pe.CUT_LONGEST
    clock.t += 2.0
    sent = eng.pulse(111, "vibrate", 100, 5000, group=FRIENDS)
    assert (sent.intensity, sent.duration_ms) == (15, 400)
    clock.t += 2.0
    sent = eng.pulse(111, "shock", 100, 5000)                     # your avatar
    assert (sent.intensity, sent.duration_ms) == (50, 1000)
    assert eng.limits_for(111, FRIENDS) == FRIEND_CAPS
    assert eng.limits_for(111) == {"max_intensity": 50, "max_vibrate": 50,
                                   "max_pulse_ms": 1000}
    assert link.sent[-1][:4] == (111, "shock", 50, 1000)


def test_on_a_friends_hold_plays_at_most_the_friends_value(rig):
    eng, link, _clock = rig
    eng.set_separate_limits(True, FRIEND_CAPS)
    eng.hold(111, "vibrate", 100, source="f", group=FRIENDS)
    assert link.sent[-1][:3] == (111, "vibrate", 15)
    eng.hold(222, "vibrate", 100, source="rules")                 # your avatar's: its own
    assert link.sent[-1][:3] == (222, "vibrate", 50)


def test_a_friends_cap_never_raises_a_shockers_own(rig):
    eng, _link, _clock = rig
    eng.set_shocker_limits({111: {"max_intensity": 10, "max_pulse_ms": 300}})
    eng.set_separate_limits(True, {"max_intensity": 80, "max_vibrate": 80,
                                   "max_pulse_ms": 15000})
    assert eng.limits_for(111, FRIENDS) == {"max_intensity": 10, "max_vibrate": 50,
                                            "max_pulse_ms": 300}
    assert eng.limits_for(222, FRIENDS) == {"max_intensity": 50, "max_vibrate": 50,
                                            "max_pulse_ms": 1000}


def test_off_friends_have_the_shockers_own_caps_one_set_for_everyone(rig):
    eng, _link, _clock = rig
    eng.set_separate_limits(False, FRIEND_CAPS)                  # remembered, not used
    assert eng.limits_for(111, FRIENDS) == eng.limits_for(111)
    sent = eng.pulse(111, "vibrate", 100, 5000, group=FRIENDS)
    assert (sent.intensity, sent.duration_ms) == (50, 1000)
    eng.set_separate_limits(True, {})                            # on, no caps of theirs
    assert eng.limits_for(111, FRIENDS) == eng.limits_for(111)


def test_the_friends_caps_are_clamped_like_the_others(rig):
    eng, _link, _clock = rig
    eng.set_separate_limits(True, {"max_intensity": 10 ** 400, "max_vibrate": -5,
                                   "max_pulse_ms": "x"})
    lim = eng.limits_for(111, FRIENDS)
    assert lim["max_intensity"] == 50                            # the shocker's own
    assert lim["max_vibrate"] == pishock_limits.RANGES["max_vibrate"][0]
    assert lim["max_pulse_ms"] <= 1000


def test_switching_separate_limits_off_keeps_every_rest_running(rig):
    eng, _link, clock = rig
    eng.set_separate_limits(True, {})
    eng.hold(111, "vibrate", 10, source="f", group=FRIENDS)
    clock.t += 10.0
    eng.hold(111, "vibrate", 10, source="f", group=FRIENDS)  # friends rest 2 s
    assert not eng.is_resting(111)
    eng.set_separate_limits(False)                           # one count again: the stricter
    assert eng.is_resting(111) and eng.is_resting(111, FRIENDS)
    clock.t += 0.5
    assert eng.pulse(111, "vibrate", 10, 300) is None


def test_switching_separate_limits_on_keeps_a_rest_already_running(rig):
    eng, _link, clock = rig
    eng.hold(111, "vibrate", 10, source="rules")
    clock.t += 10.0
    eng.hold(111, "vibrate", 10, source="rules")             # everyone rests 2 s
    eng.set_separate_limits(True, {})
    assert eng.is_resting(111) and eng.is_resting(111, FRIENDS)
