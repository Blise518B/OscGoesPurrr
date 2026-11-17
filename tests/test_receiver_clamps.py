"""What a modified client gains on the receiving OGP: nothing.

Blise's rule (2026-11-16): whatever a friend's OGP, a web remote browser or
anything on the avatar menu's OSC sends that OGP itself never would is
corrected to the app's own safe limits on the receiving side -- or refused
and logged. Each test is named the way the hostile message reads; values,
combinations and rates alike. (What the engine, the router and the readers
already corrected before is listed in the session's report, with where.)
"""

import math
import time

import pytest

import avatar_height as ah
import inbound_rate
import remote_params as rp
import remote_protocol as proto
from constants import OGP_FRIEND_LEVEL_PARAMETER
from controllers.friends_common import unit
from pishock_engine import PiShockEngine
from test_avatar_height import ready
from test_friends_facade import A, B, Host, _HubLink, cmd, real_shocker_host
from test_params_facade import OWNER, WATCHER, _empty_store_after, watched  # noqa: F401

G = "e" * 64            # a browser on the web remote


def shock_host():
    h = Host()
    h.befriend(A, shock=True)
    return h


def raw_shock(**fields):
    """A ``shk`` as a modified client might write it, past make_shock's own
    cleaning."""
    msg = {"t": "shk", "id": "x1", "slots": [0], "int": 0.5, "len": 0.5}
    msg.update(fields)
    return msg


# --- warnings -------------------------------------------------------------------

def test_a_100_ms_warning_is_stretched_to_1_s():
    h = shock_host()
    h._friends_on_event("message", A, raw_shock(warn="vibrate", wi=0.5, wms=100))
    t0 = time.monotonic()
    w = h._warnings[(A, 0)]
    assert w["until"] - t0 == pytest.approx(proto.WARN_MIN_MS / 1000, abs=0.05)
    h._pump_friend_holds(t0 + 0.5)
    assert h.pishock_engine.pulses == []                 # half a second in: still warning
    assert h.pishock_engine.holds[-1][1] == "vibrate"
    h._pump_friend_holds(t0 + 1.05)
    assert h.pishock_engine.pulses                       # then the shock
    [e] = [e for e in h.event_log.recent() if e.op == "warning"]
    assert "vibrate warning 0.1 s" in e.text             # what they sent ...
    assert (e.ms, e.asked_ms) == (1000, 100)             # ... and what played
    assert e.correction == "Stretched to 1.0 s: OGP's shortest warning"


def test_a_1_ms_warning_is_stretched_to_1_s_too():
    h = shock_host()
    h._friends_on_event("message", A, raw_shock(warn="vibrate", wi=0.5, wms=1))
    assert h._warnings[(A, 0)]["until"] - time.monotonic() > 0.9


def test_a_shock_without_a_warning_gets_none_added():
    # OGP's panels warn for 1-9 s or not at all; with no per-friend share
    # (2026-11-17) nothing makes a friend warn first
    h = shock_host()
    h._friends_on_event("message", A, raw_shock(op="shock"))
    assert (A, 0) not in h._warnings
    assert h.pishock_engine.pulses and h.pishock_engine.pulses[0][1] == "shock"
    assert not [e for e in h.event_log.recent() if e.op == "warning"]


def test_a_beep_warning_plays_as_a_vibration_where_vibrate_is_on():
    h = shock_host()
    h._friends_on_event("message", A, raw_shock(warn="beep", wi=0.5, wms=2000))
    assert h._warnings[(A, 0)]["op"] == "vibrate"
    [e] = [e for e in h.event_log.recent() if e.op == "warning"]
    assert "beep warning 2.0 s" in e.text
    assert e.correction == "A vibration instead: OGP's warnings vibrate"


def test_a_beep_warning_still_beeps_where_vibrate_is_switched_off():
    h = shock_host()
    h.pishock_engine.switched = {11: {"vibrate"}}
    h._friends_on_event("message", A, raw_shock(warn="beep", wi=0.5, wms=2000))
    assert h._warnings[(A, 0)]["op"] == "beep"


def _hold(h, peer, t0, ks):
    """GUI ticks 100 ms apart, `peer` saying their holds every tick."""
    for k in ks:
        holds, _t = h._friend_holds[peer]
        h._friend_holds = {**h._friend_holds, peer: (holds, t0 + 0.1 * k)}
        h._pump_friend_holds(t0 + 0.1 * k)


def test_a_held_shock_after_a_held_beep_plays_at_once():
    # no warning is forced into a hold (that was a per-friend share's)
    h = shock_host()
    eng = h.pishock_engine
    t0 = time.monotonic()
    h._friends_on_event("message", A, proto.make_cmd({}, None, holds={0: ("beep", 1.0)}))
    _hold(h, A, t0, range(3))
    h._friends_on_event("message", A, proto.make_cmd({}, None, holds={0: ("shock", 1.0)}))
    _hold(h, A, t0, [3])
    assert eng.holds[-1][1] == "shock"


# --- the shocker's own rules, however the pulses come ------------------------------

def _sent_with_times(h, link, clock, messages, step):
    """Hand `messages` over `step` s apart: (time, what the hub got) for
    each one that went out."""
    out = []
    for msg in messages:
        n = len(link.sent)
        h._friends_on_event("message", A, msg)
        out += [(clock["t"], s) for s in link.sent[n:]]
        clock["t"] += step
    return out


def test_a_chain_of_ever_stronger_shocks_never_outlasts_their_longest_pulse():
    h, eng, link, clock = real_shocker_host()                # longest pulse 2 s, rest 1 s
    h.befriend(A, shock=True)
    start = clock["t"]
    chain = [proto.make_shock(f"c{k}", [0], 0.1 + 0.09 * k, 1.0, op="vibrate")
             for k in range(6)]                     # 100.0 .. 102.5 s
    sent = _sent_with_times(h, link, clock, chain, 0.5)
    assert len(sent) >= 3                                # it did take over, stronger
    ends = [t + s[3] / 1000 for t, s in sent]
    assert max(ends) <= start + 2.0 + 1e-6               # but never past 2 s from its start
    assert [s[2] for _t, s in sent] == sorted(s[2] for _t, s in sent)
    assert "held back" in h.log_text()                   # the rest of the chain waited
    clock["t"] = start + 2.5                             # inside the rest after it
    n = len(link.sent)
    h._friends_on_event("message", A, proto.make_shock("late", [0], 1.0, 1.0, op="vibrate"))
    assert len(link.sent) == n


def test_your_own_rules_chain_no_longer_than_the_longest_pulse_either():
    # Blise's call (2026-11-16): the engine's rules are for every source --
    # a caller that passes nothing gets the shocker's own longest pulse
    _h, eng, link, clock = real_shocker_host()               # longest pulse 2 s
    assert eng.pulse(11, "vibrate", 10, 2000)
    clock["t"] += 1.5
    sent = eng.pulse(11, "vibrate", 20, 2000)
    assert link.sent[-1] == (11, "vibrate", 20, 500)
    assert (sent.duration_ms, sent.cut) == (500, "run")
    clock["t"] += 0.45
    assert eng.pulse(11, "vibrate", 30, 2000) is None        # 50 ms left: none


def test_a_capped_take_over_gets_only_the_room_left_and_none_when_there_is_none():
    _h, eng, link, clock = real_shocker_host()
    assert eng.pulse(11, "vibrate", 10, 2000, run_cap_ms=2000)
    clock["t"] += 1.5
    assert eng.pulse(11, "vibrate", 20, 2000, run_cap_ms=2000)
    assert link.sent[-1] == (11, "vibrate", 20, 500)     # the half second left
    clock["t"] += 0.45
    assert not eng.pulse(11, "vibrate", 30, 2000, run_cap_ms=2000)   # 50 ms: none


def test_a_tap_during_the_rest_after_the_longest_hold_is_refused():
    h, eng, link, clock = real_shocker_host()                # longest hold 10 s, rest 2 s
    h.befriend(A, shock=True)
    eng.hold(11, "vibrate", 10, source="rules")
    clock["t"] += 10.0
    eng.hold(11, "vibrate", 10, source="rules")            # its longest hold: a forced rest
    assert link.sent[-1] == (11, "end")
    clock["t"] += 0.5
    n = len(link.sent)
    h._friends_on_event("message", A, proto.make_shock("r1", [0], 0.5, 0.5, op="vibrate"))
    assert len(link.sent) == n                             # that rest is everyone's
    assert "held back" in h.log_text()
    clock["t"] += 2.0
    h._friends_on_event("message", A, proto.make_shock("r2", [0], 0.5, 0.5, op="vibrate"))
    assert link.sent[-1][1] == "vibrate"


def test_friends_pulses_carry_the_shockers_own_longest_pulse_as_the_run_cap():
    h = shock_host()
    h.pishock_engine.own = {11: {"max_pulse_ms": 1200}}       # the Collar's own: 1.2 s
    h._friends_on_event("message", A, proto.make_shock("k1", [0], 0.5, 0.5, op="vibrate"))
    assert h.pishock_engine.rules == [{"run_cap_ms": 1200, "group": "friends"}]


# --- a warning plays in full, whatever runs on the shocker --------------------------

def test_a_warning_waits_out_a_pulse_and_its_rest_then_plays_in_full_before_its_shock():
    h, eng, link, clock = real_shocker_host()                # rest after a pulse 1 s
    h.befriend(A, shock=True)
    h.befriend(B, shock=True)
    h._friends_on_event("message", B, proto.make_shock("p1", [0], 0.5, 0.5, op="vibrate"))
    assert link.sent[-1][3] == 1050                          # Sam's pulse, then 1 s of rest
    h._friends_on_event("message", A, proto.make_shock(
        "w1", [0], 0.5, 0.0, op="vibrate", warn="vibrate", warn_intensity=0.5, warn_ms=1000))
    t0 = time.monotonic()
    went = []
    for k in range(40):
        clock["t"] = 100.0 + 0.1 * k
        n = len(link.sent)
        h._pump_friend_holds(t0 + 0.1 * k)
        went += [(0.1 * k, s) for s in link.sent[n:]]
    went = [(t, s) for t, s in went if len(s) == 4]           # the operates
    chunks = [t for t, s in went if s[1] == "vibrate" and s[3] == 300]
    pulses = [t for t, s in went if s[3] == proto.SHOCK_MIN_MS]
    assert chunks[0] >= 2.05 - 1e-9          # not before Sam's pulse and its rest were over
    assert pulses[0] - chunks[0] >= 1.0 - 1e-9               # then a warning in full first


def test_a_warning_during_the_rest_after_the_longest_hold_is_held_back_with_its_shock():
    h, eng, link, clock = real_shocker_host()                # longest hold 10 s, rest 2 s
    h.befriend(A, shock=True)
    eng.hold(11, "vibrate", 10, source="rules")
    clock["t"] += 10.0
    eng.hold(11, "vibrate", 10, source="rules")              # the forced rest
    n = len(link.sent)
    h._friends_on_event("message", A, proto.make_shock(
        "w2", [0], 0.5, 0.5, op="vibrate", warn="vibrate", warn_intensity=0.5, warn_ms=1000))
    t0 = time.monotonic()
    for k in range(15):
        clock["t"] += 0.1
        h._pump_friend_holds(t0 + 0.1 * k)
    assert len(link.sent) == n and (A, 0) not in h._warnings
    assert "still resting after the longest hold" in h.log_text()


# --- what was asked, what went out, and why ------------------------------------

def _last(h, op):
    return next(e for e in h.event_log.recent() if e.op == op)


def test_a_take_over_cut_to_their_longest_pulse_is_logged_as_asked_with_the_cut():
    h, eng, link, clock = real_shocker_host()                # longest pulse 2 s
    h.befriend(A, shock=True)
    h._friends_on_event("message", A, proto.make_shock("c1", [0], 0.2, 1.0, op="vibrate"))
    clock["t"] += 1.5
    h._friends_on_event("message", A, proto.make_shock("c2", [0], 0.8, 1.0, op="vibrate"))
    assert link.sent[-1][3] == 500
    e = _last(h, "vibrate")
    assert "2.0 s" in e.text and (e.ms, e.asked_ms) == (500, 2000)
    assert e.correction == "Cut to 0.5 s: your longest pulse"


def test_an_unarmed_shock_lowered_to_your_vibrate_ceiling_is_logged_as_asked():
    h, eng, link, clock = real_shocker_host()
    eng.set_limits(max_intensity=40, max_pulse_ms=2000, cooldown_s=1.0, max_hold_s=10.0,
                   hold_rest_s=2.0, max_vibrate=10)                      # not armed
    h.befriend(A, shock=True)
    h._friends_on_event("message", A, proto.make_shock("u1", [0], 1.0, 0.0, op="shock"))
    assert link.sent[-1][:3] == (11, "vibrate", 10)
    e = _last(h, "vibrate")
    assert "vibrate 40 (shocks aren't armed)" in e.text
    assert (e.level, e.asked_level) == (10, 40)
    assert e.correction == "Lowered to 10: your vibrate limit"


def test_a_friends_pulse_that_went_as_asked_has_no_line_under_it():
    h, _eng, _link, _clock = real_shocker_host()
    h.befriend(A, shock=True)
    h._friends_on_event("message", A, proto.make_shock("ok", [0], 0.5, 0.5, op="vibrate"))
    e = _last(h, "vibrate")
    assert (e.asked_level, e.asked_ms, e.correction) == (None, None, "")


def test_why_a_pulse_got_less_names_your_limit_and_only_the_shockers_it_hit():
    from controllers.friends_receive import _pulse_fixed
    from pishock_engine import Sent
    fired = [("Collar", 40, 2000, Sent("vibrate", 40, 500, cut="run")),
             ("Thigh", 30, 2000, Sent("vibrate", 30, 2000))]
    assert _pulse_fixed("vibrate", "vibrate", fired, True) == "less on Collar: your longest pulse"
    assert _pulse_fixed("vibrate", "vibrate", fired[:1], False) == "your longest pulse"
    unarmed = [("Collar", 40, 300, Sent("vibrate", 10, 300, capped=True))]
    assert _pulse_fixed("shock", "vibrate", unarmed, False) == "your vibrate limit"
    assert _pulse_fixed("beep", "beep", [("Collar", 9, 300, Sent("beep", 1, 300))], False) == ""


# --- a friend with only Shockers on (Toys off) ---------------------------------------

def test_a_friend_with_only_shockers_on_can_hold_your_shocker():
    h = Host()
    h.befriend(A, toys=False, shock=True)
    h._friends_on_event("message", A, proto.make_cmd({"Lush": 1.0}, (5, 0.2),
                                                     holds={0: ("vibrate", 0.5)}))
    h._pump_friend_holds(time.monotonic())
    assert h.pishock_engine.holds and h.pishock_engine.holds[-1][1] == "vibrate"
    assert h.get_friend_drive("Lush") == 0.0                 # their toys part lands nowhere
    assert _strength_queued(h) == []


def _strength_queued(h):
    return [d for k, d in list(h.thread_queue.queue) if k == "friends" and d[0] == "strength"]


def test_a_shockers_only_friends_strength_change_never_lands_later():
    h = Host()
    h.befriend(A, toys=False, shock=True)
    h._friends_on_event("message", A, proto.make_cmd({}, (5, 0.2)))
    h.befriend(A, toys=True, shock=True)                     # Toys back on
    h._friends_on_event("message", A, proto.make_cmd({}, (5, 0.2)))   # the same change again
    assert _strength_queued(h) == []                         # used up while Toys was off


def test_a_friend_with_toys_and_shockers_off_lands_nothing():
    h = Host()
    h.befriend(A, toys=False, shock=False)
    h._friends_on_event("message", A, proto.make_cmd({"Lush": 1.0}, None,
                                                     holds={0: ("vibrate", 0.5)}))
    assert A not in h._friend_holds and A not in h._friend_drive


# --- rates ----------------------------------------------------------------------------

def test_two_hundred_shocks_at_once_reach_the_engine_only_the_burst_and_are_said_once():
    h = shock_host()
    for k in range(200):
        h._friends_on_event("message", A, proto.make_shock(f"f{k}", [0], 0.5, 0.5, op="vibrate"))
    burst = inbound_rate.SHOCKS[1]
    assert burst <= len(h.pishock_engine.pulses) <= burst + 3
    assert h.log_text().count("too fast") == 1


def test_copies_of_one_shock_spend_nothing():
    h = shock_host()
    msg = proto.make_shock("same", [0], 0.5, 0.5, op="vibrate")
    for _ in range(100):
        h._friends_on_event("message", A, msg)
    for k in range(inbound_rate.SHOCKS[1] - 1):
        h._friends_on_event("message", A, proto.make_shock(f"n{k}", [0], 0.5, 0.5, op="vibrate"))
    assert len(h.pishock_engine.pulses) == inbound_rate.SHOCKS[1]
    assert "too fast" not in h.log_text()


def test_two_hundred_stops_at_once_reach_the_hub_only_the_burst():
    h = shock_host()
    for k in range(200):
        h._friends_on_event("message", A, proto.make_stop(f"s{k}", [0]))
    burst = inbound_rate.STOPS[1]
    assert burst <= len(h.pishock_engine.ended) <= burst + 3
    assert h.log_text().count("too fast") == 1


def test_a_stop_past_the_budget_still_drops_their_own_warning():
    h = shock_host()
    for k in range(inbound_rate.STOPS[1]):
        h._friends_on_event("message", A, proto.make_stop(f"s{k}", [0]))
    h._friends_on_event("message", A, raw_shock(id="w", warn="vibrate", wi=0.5, wms=3000))
    assert (A, 0) in h._warnings
    h._friends_on_event("message", A, proto.make_stop("last", [0]))
    assert (A, 0) not in h._warnings                     # their shock never comes


def test_another_friends_many_shock_ids_cant_make_a_late_copy_of_yours_count_again():
    h = shock_host()
    h.befriend(B, shock=True)
    mine = proto.make_shock("same", [0], 0.5, 0.5, op="vibrate")
    h._friends_on_event("message", A, mine)
    for k in range(300):
        h._friends_on_event("message", B, proto.make_shock(f"b{k}", [1], 0.5, 0.5,
                                                           op="vibrate"))
    h._friends_on_event("message", A, mine)              # Alex's copy, arriving late
    assert [p for p in h.pishock_engine.pulses if p[0] == 11] == [(11, "vibrate", 20, 1050)]


def test_a_thousand_strength_changes_at_once_queue_one_and_the_newest_lands():
    h = Host()
    h.befriend(A)
    for k in range(1, 1001):
        h._friends_on_event("message", A, cmd({}, (k, k / 1000)))
    queued = [d for kind, d in list(h.thread_queue.queue)
              if kind == "friends" and d[0] == "strength"]
    assert len(queued) == 1
    h.drain()
    assert h.strength_calls == [(1.0, "friend")]
    h._friends_on_event("message", A, cmd({}, (1001, 0.2)))   # the next one queues again
    h.drain()
    assert h.strength_calls[-1] == (0.2, "friend")


def test_two_hundred_avatar_sets_at_once_reach_vrchat_only_the_burst():
    owner, _watcher, ids = watched()
    for k in range(200):
        owner._friends_on_event("message", WATCHER,
                                rp.make_set(k + 1, (k % 10) / 10, control=ids["bright"]))
    sent = [v for name, v in owner.osc_manager.sent if name == "Brightness"]
    burst = inbound_rate.PARAMS[1]
    assert burst <= len(sent) <= burst + 3
    assert sum("too fast" in t for t in owner.notes()) == 1


def test_a_flood_of_button_presses_is_rationed_but_letting_go_never_is():
    owner, _watcher, ids = watched()
    for k in range(200):
        held = [ids["wave"]] if k % 2 == 0 else []
        owner._friends_on_event("message", WATCHER, rp.make_holds(held))
    presses = [v for name, v in owner.osc_manager.sent if name == "Emote" and v == 3]
    burst = inbound_rate.PARAMS[1]
    assert burst <= len(presses) <= burst + 3
    assert owner.osc_manager.sent[-1] == ("Emote", 0)    # let go: never held back
    assert WATCHER not in owner._params_held


def test_a_flood_of_height_changes_is_rationed():
    owner, _watcher, _clock = ready()
    for k in range(200):
        owner._friends_on_event("message", WATCHER,
                                rp.make_height_set(10 ** 15 + k, ah.NOW, 1.0 + k / 100))
    assert sum("too fast" in t for t in owner.notes()) == 1


def test_the_budget_refills_with_time():
    b = inbound_rate.Budget(10.0, 2)
    assert b.take("p", 0.0) and b.take("p", 0.0) and not b.take("p", 0.0)
    assert b.take("p", 0.1) and not b.take("p", 0.1)
    assert b.say("p", 0.0) and not b.say("p", 4.9) and b.say("p", 5.0)
    b.forget("p")
    assert b.take("p", 0.2) and b.take("p", 0.2)


# --- the web remote --------------------------------------------------------------------

@pytest.mark.parametrize("msg", [
    {"t": "st", "toys": [["Edge", 1]], "allow": {"toys": True, "shock": True}},
    {"t": "pnl", "seq": 5, "lvl": {"*": 1.0}},
    {"t": "oth", "n": ["Sam"]},
    {"t": "pbd", "b": "v1", "cats": [], "ctl": [], "keys": []},
    {"t": "pv", "b": "v1", "w": 1, "o": 0, "x": [1]},
])
def test_a_browser_sending_what_only_an_ogp_sends_is_not_listened_to(msg):
    h = Host()
    h._web_guests = {G: "Guest"}
    said = []
    h._friends_debug = said.append
    h._friends_on_event("message", G, dict(msg))
    h._friends_on_event("message", G, dict(msg))
    assert G not in h._friend_status and G not in h._their_boards
    assert G not in h._my_levels and G not in h._friend_others
    assert len(said) == 1 and msg["t"] in said[0]


# --- numbers that aren't any ------------------------------------------------------------

def test_an_infinite_level_is_no_level():
    for junk in (float("inf"), float("-inf"), float("nan"), 10 ** 400):
        assert unit(junk) == 0.0


def test_an_infinite_level_from_your_avatar_menu_drives_your_friend_with_nothing():
    h = Host()
    h.befriend(A)
    h.friends_settings.set_selected("friend", A)
    h._friends_on_osc(OGP_FRIEND_LEVEL_PARAMETER, float("inf"))
    assert h._my_levels[A] == {}


def test_a_panel_version_past_what_a_browser_counts_is_capped():
    assert proto.read_syn({"syn": 10 ** 30}) == proto.MAX_SEQ
    assert proto.read_syn({"syn": float("inf")}) is None
    assert proto.read_panel({"seq": 10 ** 30})[0] == proto.MAX_SEQ


GARBAGE = [None, True, -1, 10 ** 400, float("inf"), float("-inf"), float("nan"), "x",
           [], {}, [1, "a", None], {"a": [1]}, [[None, 1e400, "x"]]]


def _mutations(value, depth=2):
    """`value` with garbage put in at every place, `depth` levels down."""
    for g in GARBAGE:
        yield g
    if depth <= 0:
        return
    if isinstance(value, dict):
        for k, v in value.items():
            for m in _mutations(v, depth - 1):
                yield {**value, k: m}
    elif isinstance(value, list):
        for i, v in enumerate(value):
            for m in _mutations(v, depth - 1):
                yield value[:i] + [m] + value[i + 1:]


def _variants(msg):
    for key, value in msg.items():
        if key == "t":
            continue
        for m in _mutations(value):
            yield {**msg, key: m}


FRIEND_MESSAGES = [
    proto.make_cmd({"*": 0.5, "Edge": 0.4}, (1, 0.5), override=["*"],
                   patterns={"*": ("sine", 2.0, 0.0, 1.0)}, holds={0: ("vibrate", 0.5)}, syn=3),
    proto.make_shock("g", [0, 1], 0.5, 0.5, "shock", "vibrate", 0.5, 2000),
    proto.make_stop("g", [0]),
    {"t": "st", "toys": [["Edge", 1]], "out": {"Edge": 0.5}, "str": 0.5, "off": False,
     "pause": False, "allow": {"toys": True, "shock": True}, "shk": ["Collar"], "armed": True,
     "lim": {"int": 40, "ms": 2000, "vib": 40, "hold": 10}, "slim": [[40, 40, 2000]],
     "sop": [7], "soff": [0], "fw": 1, "nc": 1, "bat": {"Edge": 50},
     "prm": {"b": "v1", "y": 1, "a": "k"}},
    proto.make_panel(2, {"*": 0.5}, ["*"], {"*": ("sine", 2.0, 0.0, 1.0)}),
    proto.make_others(["Sam"]),
    {"t": "lw", "on": 1},
]


@pytest.mark.parametrize("msg", FRIEND_MESSAGES, ids=lambda m: m["t"])
def test_garbage_anywhere_in_a_friends_message_never_breaks_the_receiver(msg):
    h = Host()
    h.befriend(A, toys=True, shock=True)
    h.friends_settings.set_selected("friend", A)
    n = 0
    for variant in _variants(msg):
        if variant.get("id") == msg.get("id"):
            variant = {**variant, "id": f"v{n}"}        # a new one each time, not a copy
        h._shock_budget = inbound_rate.Budget(1e9, 10 ** 9)   # past the door every time
        h._stop_budget = inbound_rate.Budget(1e9, 10 ** 9)
        h._friends_on_event("message", A, variant)
        h._pump_friend_holds(time.monotonic())
        h._pump_friend_holds(time.monotonic() + 10.0)    # warnings run out: their shocks go
        level, _override = h.get_friend_drive_mode("Edge")
        assert math.isfinite(level) and 0.0 <= level <= 1.0
        n += 1
    assert n >= len(GARBAGE)
    for p in h.pishock_engine.pulses:                    # whatever got through is in range
        assert 1 <= p[2] <= 40 and 1 <= p[3] <= 2000
    for _sid, _op, level in h.pishock_engine.holds:
        assert 1 <= level <= 40


PARAMS_READERS = [
    (rp.read_set, rp.make_set(7, 0.5, control="c1")),
    (rp.read_set, rp.make_set(8, 0.5, param="Hue")),
    (rp.read_holds, rp.make_holds(["c1", "c2"])),
    (rp.read_height_set, rp.make_height_set(9, ah.NOW, 1.5)),
    (rp.read_watch, rp.make_watch("v1", True, 3)),
    (rp.read_board, {"t": "pbd", "b": "v1", "name": "Moth",
                     "cats": [{"id": "k", "name": "Main", "color": "green"}],
                     "ctl": [{"id": "c1", "param": "Hue", "ptype": "Float", "kind": "slider",
                              "label": "Hue", "cat": "k", "min": 0, "max": 1}],
                     "keys": ["Hue"], "nb": 1, "all": [["Hue", "Float"]],
                     "ht": {"lo": 0.5, "hi": 2.0}}),
]


@pytest.mark.parametrize("reader,msg", PARAMS_READERS, ids=lambda x: getattr(x, "__name__", ""))
def test_garbage_anywhere_in_an_avatar_remote_message_is_cleaned_or_dropped(reader, msg):
    for variant in _variants(msg):
        out = reader(variant)
        if reader is rp.read_set and out is not None:
            assert math.isfinite(out[3])
        if reader is rp.read_height_set and out is not None and out[2] is not None:
            assert math.isfinite(out[2]) and out[2] > 0


def test_garbage_in_a_friends_board_values_is_dropped():
    board = rp.read_board(PARAMS_READERS[-1][1])
    msg = {"t": "pv", "b": "v1", "w": 1, "o": 0, "x": [0.5], "h": 1.6}
    for variant in _variants(msg):
        for value in rp.read_values(variant, board).values():
            assert value is None or isinstance(value, bool) or math.isfinite(value)
        h = rp.read_height(variant)
        assert h is None or (math.isfinite(h) and ah.SAFE_MIN <= h <= ah.SAFE_MAX)


def test_a_status_with_garbage_never_breaks_your_page():
    st = FRIEND_MESSAGES[3]
    for variant in _variants(st):
        got = proto.read_status(variant)
        assert 0 <= got["max_intensity"] <= 100 and 0 <= got["max_pulse_ms"] <= 15000
        assert 0.0 <= got["strength"] <= 1.0 and 0.0 <= got["max_hold_s"] <= 600.0
        assert len(got["toys"]) <= proto.MAX_TOYS and len(got["shockers"]) <= proto.MAX_SHOCKERS


def test_the_engine_takes_no_infinity_for_a_number():
    clock, link = {"t": 100.0}, _HubLink()
    eng = PiShockEngine(link_factory=lambda **_k: link, clock=lambda: clock["t"])
    eng.set_port("COM9")
    eng._want_connected = True
    eng._try_connect()
    eng.set_limits(max_intensity=40, max_pulse_ms=2000, cooldown_s=1.0,
                   max_hold_s=10.0, hold_rest_s=2.0)
    assert eng.pulse(11, "vibrate", float("inf"), float("inf"))
    assert link.sent[-1] == (11, "vibrate", 1, 300)      # neither a level nor a length
    clock["t"] += 5.0
    assert eng.pulse(11, "vibrate", 10 ** 400, 10 ** 400)
    assert link.sent[-1] == (11, "vibrate", 40, 2000)    # a number: up to the caps


# --- separate limits for friends: whose count a shock is ------------------------------

def test_your_avatar_menus_shock_on_yourself_counts_as_your_avatars_and_the_rest_as_friends():
    from controllers.friends_common import ME
    from controllers.friends_receive import shock_group
    from event_log import VIA_MENU, VIA_PARTY
    from pishock_engine import GROUP_AVATAR, GROUP_FRIENDS
    assert shock_group(ME, VIA_MENU) == GROUP_AVATAR
    assert shock_group(ME, "") == GROUP_FRIENDS                # Me on the page
    assert shock_group(ME, VIA_PARTY) == GROUP_FRIENDS
    assert shock_group(A, VIA_MENU) == GROUP_FRIENDS           # never a friend's


def test_a_friends_hold_counts_against_friends_limits():
    h = shock_host()
    h._friends_on_event("message", A, proto.make_cmd({}, None, holds={0: ("vibrate", 0.5)}))
    calls = []
    h.pishock_engine.hold = lambda sid, op, lvl, source="", group="avatar": calls.append(group)
    h._pump_friend_holds(time.monotonic())
    assert calls == ["friends"]


def test_friends_are_told_their_own_longest_hold_while_limits_are_separate():
    h, eng, _link, _clock = real_shocker_host()               # longest hold 10 s
    h.befriend(A, shock=True)
    assert h._build_my_state()["max_hold_s"] == 10.0
    eng.set_separate_limits(True, {"max_hold_s": 42.0})
    assert h._build_my_state()["max_hold_s"] == 42.0


# --- the friends' own caps while limits are separate (Blise's call, 2026-11-17) -------

FRIEND_CAPS = {"max_intensity": 10, "max_vibrate": 8, "max_pulse_ms": 500}


def test_a_friend_lands_at_the_friends_caps_and_your_avatar_menu_at_the_shockers_own():
    from controllers.friends_common import ME, came_through
    from event_log import VIA_MENU
    h, eng, link, _clock = real_shocker_host()               # every shocker: 40, 2 s
    h.befriend(A, shock=True)
    eng.set_armed(True)
    eng.set_separate_limits(True, FRIEND_CAPS)
    h._friends_on_event("message", A, proto.make_shock("f1", [0], 1.0, 1.0, op="shock"))
    assert link.sent[-1][:4] == (11, "shock", 10, 500)
    with came_through(VIA_MENU):                             # you, from your avatar's menu
        h._friends_on_event("message", ME, proto.make_shock("m1", [1], 1.0, 1.0, op="shock"))
    assert link.sent[-1][:4] == (22, "shock", 40, 2000)


def test_the_engine_holds_a_friend_to_the_friends_caps_whatever_the_receiver_asks():
    """The engine is the last gate: even asked at your avatar's caps, a
    friend's pulse and hold go out at the friends'."""
    from pishock_engine import PiShockEngine
    h, eng, link, clock = real_shocker_host()
    h.befriend(A, shock=True)
    eng.set_armed(True)
    eng.set_separate_limits(True, FRIEND_CAPS)
    own = PiShockEngine.limits_for
    eng.limits_for = lambda sid, group="avatar": own(eng, sid)      # a receiver that forgot
    h._friends_on_event("message", A, proto.make_shock("f2", [0], 1.0, 1.0, op="shock"))
    assert link.sent[-1][:4] == (11, "shock", 10, 500)
    h._friends_on_event("message", A, proto.make_cmd({}, None, holds={1: ("vibrate", 1.0)}))
    h._pump_friend_holds(time.monotonic())
    assert link.sent[-1][:3] == (22, "vibrate", 8)


def test_friends_are_told_the_lower_caps_they_get():
    h, eng, _link, _clock = real_shocker_host()
    h.befriend(A, shock=True)
    eng.set_shocker_limits({22: {"max_intensity": 5}})
    assert h._build_my_state()["shocker_caps"] == [(40, 40, 2000), (5, 40, 2000)]
    eng.set_separate_limits(True, FRIEND_CAPS)
    h._my_state = h._build_my_state()
    st = proto.read_status(proto.decode(proto.encode(h._friends_status_for(A))))
    assert st["shocker_caps"] == [(10, 8, 500), (5, 8, 500)]   # theirs, never above a shocker's
    assert (st["max_intensity"], st["max_vibrate"], st["max_pulse_ms"]) == (10, 8, 500)
    eng.set_separate_limits(False, FRIEND_CAPS)
    assert h._build_my_state()["shocker_caps"] == [(40, 40, 2000), (5, 40, 2000)]


# --- Sync with others: saying "newer" without changing anything --------------------

from controllers.friends_receive import SYNC_SEEN_MAX                    # noqa: E402
from test_sync_with_others import ALL, R, Room, hand_clock                     # noqa: E402,F401


def lying_cmd(levels, syn):
    """A cmd from a modified OGP: its panel version written by hand."""
    return {"t": "cmd", "lvl": dict(levels), "syn": syn}


def honest_and_a_liar():
    """Alex's honest OGP; Sam's OGP, modified, is heard only through
    `room.recv`."""
    room = Room(A)
    room.recv.befriend(B)
    return room


def test_a_huge_sync_version_cannot_keep_the_shared_toy_cards(hand_clock):
    room = honest_and_a_liar()

    def sam():
        room.recv._friends_on_event("message", B, lying_cmd({ALL: 1.0}, 2 ** 80))

    sam()
    room.tick()
    assert room.playing == pytest.approx(1.0)        # nobody had set anything yet
    room.app[A].set_friend_level(R, ALL, 0.2)
    for _ in range(20):
        sam()
        room.tick()
    assert room.playing == pytest.approx(0.2) and room.owner() == A
    assert room.app[A]._my_pseq[R] < 2 ** 32           # the huge number never reached Alex


def test_an_ever_rising_sync_version_with_the_same_cards_takes_nothing(hand_clock):
    room = honest_and_a_liar()
    room.tick()
    room.app[A].set_friend_level(R, ALL, 0.2)
    room.tick(2)
    for n in range(1, 200):
        room.recv._friends_on_event("message", B, lying_cmd({ALL: 1.0}, 10 ** 6 * n))
        room.tick()
        assert room.owner() == A
    assert room.playing == pytest.approx(0.2)


def test_a_sender_changing_its_cards_every_message_is_newest_only_like_a_hand_on_a_slider(hand_clock):
    room = honest_and_a_liar()
    room.tick()
    room.app[A].set_friend_level(R, ALL, 0.2)
    room.tick(2)
    room.recv._friends_on_event("message", B, lying_cmd({ALL: 0.5}, proto.MAX_SEQ))
    for n in range(1, 50):
        level = round(0.5 + n / 200, 3)
        room.recv._friends_on_event("message", B, lying_cmd({ALL: level}, proto.MAX_SEQ))
        assert room.playing == pytest.approx(level)    # each change plays, as a slider's
    assert room.recv._friend_drive[B].ver < 2 ** 30    # nowhere near running out the numbers
    room.tick()
    room.app[A].set_friend_level(R, ALL, 0.1)          # once Sam's stop changing ...
    room.tick(2)
    room.recv._friends_on_event("message", B, lying_cmd({ALL: 0.745}, proto.MAX_SEQ))
    assert room.playing == pytest.approx(0.1)          # ... Alex's change stays


def test_a_new_web_remote_identity_with_a_huge_version_cannot_retake_the_cards(hand_clock):
    room = Room(A)
    code = room.recv.friends_settings.web_code()
    room.tick()
    room.app[A].set_friend_level(R, ALL, 0.2)
    room.tick(2)
    for digit in "123456":
        guest = digit * 64
        room.recv._friends_invite_ok(guest, code, "Kim")
        room.recv._friends_on_event("message", guest, lying_cmd({ALL: 1.0}, proto.MAX_SEQ))
        assert room.owner() == A and room.playing == pytest.approx(0.2)


def test_switching_sync_off_and_on_every_message_takes_no_shared_cards(hand_clock):
    room = honest_and_a_liar()
    room.tick()
    room.app[A].set_friend_level(R, ALL, 0.2)
    room.tick(2)
    for n in range(20):
        msg = lying_cmd({ALL: 1.0}, proto.MAX_SEQ)
        if n % 2:
            del msg["syn"]                               # "on my own" -- then back
        room.recv._friends_on_event("message", B, msg)
        assert room.owner() == A
        room.back(A)
        assert room.panel(A) == {ALL: 0.2}


def test_honest_panels_keep_following_each_other_beside_a_huge_sync_version(hand_clock):
    C = "7" * 64
    room = Room(A, C)
    room.recv.befriend(B)

    def sam():
        room.recv._friends_on_event("message", B, lying_cmd({ALL: 1.0}, proto.MAX_SEQ))

    sam()
    room.tick()
    for who, level in ((A, 0.2), (C, 0.4), (A, 0.6)):
        room.app[who].set_friend_level(R, ALL, level)
        for _ in range(2):
            sam()
            room.tick()
        assert room.playing == pytest.approx(level)
        assert room.panel(A) == room.panel(C) == {ALL: level}
    assert max(room.app[p]._my_pseq[R] for p in (A, C)) < 2 ** 32


def test_a_flood_of_new_identities_keeps_what_is_remembered_bounded():
    h = Host()
    cards = ({ALL: 1.0}, frozenset(), {})
    for i in range(SYNC_SEEN_MAX + 50):
        h._sync_version(f"{i:064x}", proto.MAX_SEQ, cards, None)
    assert len(h._sync_seen) == SYNC_SEEN_MAX
    assert f"{0:064x}" not in h._sync_seen and f"{SYNC_SEEN_MAX + 49:064x}" in h._sync_seen


# --- rates: the toy cards ---------------------------------------------------------------

from test_friends_facade import me_host                                        # noqa: E402

# The most changes to the toy cards an honest sender makes in any one second:
# OGP's link at most 60 pushes (remote_session.CMD_HZ) plus its 4 ticks --
# measured 62 while a slider was dragged at 1000 steps a second -- and the
# web remote 94, measured with a hand wiggling a slider through zero at 3 to
# 30 Hz (its letting-go copies land after newer cmds).
OGP_MOST = 64
WEB_MOST = 94


def card_host():
    h = Host()
    h.befriend(A)
    return h


def cards_of(h, peer=A):
    d = h._friend_drive[peer]
    return dict(d.levels), set(d.ovr), {k: v["p"] for k, v in d.pat.items()}


def flood(h, keep=None, override=(), patterns=None):
    """Changes as fast as a modified client can send them, past the burst:
    Lush moving on every one, the rest of the cards as given."""
    for k in range(inbound_rate.CARDS[1] + 100):
        levels = {**(keep or {}), "Lush": round(0.1 + (k % 80) / 100, 3)}
        h._friends_on_event("message", A, proto.make_cmd(levels, None, override, patterns))


def test_a_flood_of_toy_card_changes_lands_only_the_burst_and_is_said_once(hand_clock):
    h = card_host()
    landed = 0
    for k in range(2000):
        level = round(0.1 + (k % 800) / 1000, 3)
        h._friends_on_event("message", A, cmd({"Lush": level}))
        landed += h._friend_drive[A].levels == {"Lush": level}
    burst = inbound_rate.CARDS[1]
    assert burst <= landed <= burst + 3
    assert h.log_text().count("too fast") == 1


def test_a_change_held_back_lands_with_their_next_cmd_once_the_budget_is_back(hand_clock):
    h = card_host()
    flood(h)
    last = {"Lush": 0.95}
    h._friends_on_event("message", A, cmd(last))
    assert h._friend_drive[A].levels != last
    hand_clock[0] += 0.1                                 # their next top-up, a moment later
    h._friends_on_event("message", A, cmd(last))
    assert h._friend_drive[A].levels == last


def test_top_ups_and_copies_of_the_same_cards_spend_nothing(hand_clock):
    h = card_host()
    same = cmd({"Lush": 0.5})
    for _ in range(5000):
        h._friends_on_event("message", A, same)
    landed = 0
    for k in range(inbound_rate.CARDS[1] - 1):
        level = round(0.1 + (k % 300) / 1000, 3)
        h._friends_on_event("message", A, cmd({"Lush": level}))
        landed += h._friend_drive[A].levels == {"Lush": level}
    assert landed == inbound_rate.CARDS[1] - 1
    assert "too fast" not in h.log_text()


def test_a_toy_stopped_past_the_budget_stops_at_once(hand_clock):
    h = card_host()
    flood(h, keep={"Edge": 0.6})
    lush = h._friend_drive[A].levels["Lush"]
    h._friends_on_event("message", A, cmd({"Lush": lush}))        # Edge to 0
    assert h._friend_drive[A].levels == {"Lush": lush}
    h._friends_on_event("message", A, cmd({}))                    # everything to 0
    assert h._friend_drive[A].levels == {}
    assert h.get_friend_drive("Lush") == 0.0 and h.get_friend_drive("Edge") == 0.0


def test_override_off_and_an_ended_auto_mode_land_past_the_budget(hand_clock):
    h = card_host()
    wave = {"Edge": ("sine", 2.0, 0.0, 1.0)}
    flood(h, override=("Lush", "Edge"), patterns=wave)
    lush = h._friend_drive[A].levels["Lush"]
    h._friends_on_event("message", A, proto.make_cmd({"Lush": lush}, None, ("Lush",), wave))
    assert cards_of(h)[1] == {"Lush"}                             # Override off on Edge
    h._friends_on_event("message", A, proto.make_cmd({"Lush": lush}, None, ("Lush",), {}))
    assert cards_of(h)[2] == {}                                   # the auto mode ended


def test_a_cmd_that_stops_one_toy_and_raises_another_past_the_budget_lands_only_the_stop(hand_clock):
    h = card_host()
    flood(h, keep={"Edge": 0.6})
    lush = h._friend_drive[A].levels["Lush"]
    h._friends_on_event("message", A, cmd({"Lush": min(1.0, lush + 0.05), "Gush": 1.0}))
    assert h._friend_drive[A].levels == {"Lush": lush}            # Edge stopped, nothing raised
    assert h.log_text().count("too fast") == 1


def test_stopping_toys_one_at_a_time_cant_change_the_cards_past_the_budget(hand_clock):
    h = card_host()
    many = {f"Toy{i}": 0.5 for i in range(proto.MAX_TOYS)}
    flood(h, keep=many)
    lush = h._friend_drive[A].levels["Lush"]
    left = dict(many)
    while left:                                                   # each one lets go: it lands
        left.pop(next(iter(left)))
        h._friends_on_event("message", A, cmd({**left, "Lush": lush}))
        assert h._friend_drive[A].levels == {**left, "Lush": lush}
    hand_clock[0] += 2 / inbound_rate.CARDS[0]                    # two changes' worth later ...
    h._friends_on_event("message", A, cmd({"Lush": 0.99}))
    assert h._friend_drive[A].levels == {"Lush": lush}            # ... the stops are still owed
    hand_clock[0] += (proto.MAX_TOYS + 1) / inbound_rate.CARDS[0]
    h._friends_on_event("message", A, cmd({"Lush": 0.99}))
    assert h._friend_drive[A].levels == {"Lush": 0.99}


def drag(h, clock, per_s, seconds):
    """A hand on a slider, as fast as an honest sender ever sends: a new
    level every 1 / `per_s` s. True when every change landed."""
    ok = True
    for k in range(int(per_s * seconds)):
        level = round(0.05 + (k % 900) / 1000, 3)
        h._friends_on_event("message", A, cmd({"Lush": level}))
        ok = ok and h._friend_drive[A].levels == {"Lush": level}
        clock[0] += 1.0 / per_s
    return ok


def test_an_ogp_dragging_a_slider_as_fast_as_its_link_sends_is_never_held_back(hand_clock):
    h = card_host()
    assert drag(h, hand_clock, OGP_MOST, 30)
    assert "too fast" not in h.log_text()


def test_the_web_remote_wiggling_a_slider_through_zero_is_never_held_back(hand_clock):
    h = card_host()
    assert drag(h, hand_clock, WEB_MOST, 30)
    assert "too fast" not in h.log_text()


def test_what_a_link_stalled_for_three_seconds_hands_over_at_once_all_lands(hand_clock):
    h = card_host()
    assert drag(h, hand_clock, WEB_MOST, 5)              # dragging ...
    hand_clock[0] += 3.0                                 # ... held up for 3 s ...
    landed = True
    for k in range(3 * WEB_MOST):                        # ... then all of it at once
        level = round(0.05 + (k % 900) / 1000, 3)
        h._friends_on_event("message", A, cmd({"Lush": level}))
        landed = landed and h._friend_drive[A].levels == {"Lush": level}
    assert landed and "too fast" not in h.log_text()
    hand_clock[0] += 1.0 / WEB_MOST
    assert drag(h, hand_clock, WEB_MOST, 5)              # and it carries on


def test_your_own_row_is_never_held_back_however_fast_your_hand(hand_clock):
    h, me = me_host()
    for k in range(3000):                                # a 1000 Hz mouse for three seconds
        level = round(0.1 + (k % 800) / 1000, 3)
        h.set_friend_level(me, ALL, level)
        assert h._friend_drive[me].levels == {ALL: level}
    assert "too fast" not in h.log_text()


def test_the_budget_lets_go_on_credit_and_waits_until_it_is_paid_back():
    b = inbound_rate.Budget(10.0, 2)
    assert b.take("p", 0.0) and b.take("p", 0.0) and not b.take("p", 0.0)
    b.spend("p", 0.0)
    b.spend("p", 0.0)                                    # owing two
    assert not b.take("p", 0.25)                         # 2.5 back: still short
    assert b.take("p", 0.5)
    for _ in range(100):
        b.spend("p", 1.0)                                # owing at most a burst
    assert not b.take("p", 1.25) and b.take("p", 1.5)


# Sync with others: what the budget holds back never becomes the newest

def sam_floods(room, n):
    """Sam's modified OGP: a change on every message, a version written by hand."""
    for k in range(n):
        room.recv._friends_on_event("message", B, lying_cmd({ALL: round(0.3 + (k % 60) / 100, 3)},
                                                            proto.MAX_SEQ))


def test_changes_held_back_by_the_budget_never_make_their_sender_the_newest(hand_clock):
    room = honest_and_a_liar()
    room.tick()
    sam_floods(room, inbound_rate.CARDS[1] + 50)
    room.tick()                                           # Alex's panel catches up ...
    room.app[A].set_friend_level(R, ALL, 0.2)            # ... and Alex changes it after
    room.tick(2)
    assert room.owner() == A
    for k in range(100):                                  # Sam's budget is spent
        room.recv._friends_on_event("message", B, lying_cmd({ALL: round(0.4 + k / 1000, 3)},
                                                            proto.MAX_SEQ))
        assert room.owner() == A and room.playing == pytest.approx(0.2)


def test_the_newest_letting_go_past_the_budget_stops_the_shared_toys(hand_clock):
    room = honest_and_a_liar()
    room.app[A].set_friend_level(R, ALL, 0.2)
    room.tick(2)
    sam_floods(room, inbound_rate.CARDS[1] + 50)
    assert room.owner() == B
    room.recv._friends_on_event("message", B, lying_cmd({}, proto.MAX_SEQ))
    assert room.playing == 0.0


def test_letting_go_past_the_budget_never_brings_old_values_back_onto_the_shared_cards(hand_clock):
    room = honest_and_a_liar()
    room.tick()
    for k in range(inbound_rate.CARDS[1] + 50):          # Sam, modified: Edge high, Gush on
        levels = {"Edge": 0.9, "Gush": 0.5, "Lush": round(0.1 + (k % 60) / 100, 3)}
        room.recv._friends_on_event("message", B, lying_cmd(levels, proto.MAX_SEQ))
    room.tick()                                           # Alex's panel catches up ...
    room.app[A].set_friend_level(R, "Edge", 0.2)         # ... and Alex turns Edge down
    room.tick(2)
    assert room.owner() == A and room.recv.get_friend_drive("Edge") == pytest.approx(0.2)
    lush = room.recv._friend_drive[B].levels["Lush"]
    room.recv._friends_on_event("message", B, lying_cmd({"Edge": 0.9, "Lush": lush}, proto.MAX_SEQ))
    assert "Gush" not in room.recv._friend_drive[B].levels         # Sam's letting go landed ...
    assert room.owner() == A                                       # ... but takes nothing
    assert room.recv.get_friend_drive("Edge") == pytest.approx(0.2)


def alex_drags_past_the_budget(room):
    for k in range(inbound_rate.CARDS[1] + 20):          # one OGP's cmds, all at once
        room.app[A].set_friend_level(R, ALL, round(0.1 + (k % 50) / 100, 3))
        room.send(A)
    held = room.app[A]._my_levels[R]
    assert room.recv._friend_drive[A].levels != held
    return held


def test_a_held_back_change_lands_with_its_own_version_and_still_loses_to_a_newer_one(hand_clock):
    room = Room(A, B)
    room.tick()
    held = alex_drags_past_the_budget(room)
    room.back(B)
    room.app[B].set_friend_level(R, ALL, 0.9)            # Sam changes it after
    room.send(B)
    hand_clock[0] += 0.25
    room.send(A)                                          # Alex's held-back change lands now ...
    assert room.recv._friend_drive[A].levels == held
    assert room.owner() == B and room.playing == pytest.approx(0.9)   # ... older than Sam's
    room.tick(2)
    assert room.panel(A) == room.panel(B) == {ALL: 0.9}


def test_a_held_back_change_nobody_changed_since_takes_the_cards_when_it_lands(hand_clock):
    room = Room(A, B)
    room.tick()
    held = alex_drags_past_the_budget(room)
    hand_clock[0] += 0.25
    room.tick(2)
    assert room.owner() == A and room.playing == pytest.approx(held[ALL])
    assert room.panel(B) == held
