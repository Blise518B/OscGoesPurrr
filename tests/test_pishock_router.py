"""PiShockRouter turns the page's rules into engine calls. Driven by
calling tick() against a fresh ParameterStore and a recording engine — no
thread, no hardware."""

import pytest

import pishock_engine
import pishock_router
import router_base
from parameter_store import ParameterStore
from pishock_router import PiShockRouter, map_intensity
from settings.pishock import clean_continuous, clean_impact, clean_trigger, clean_zones


class RecEngine:
    def __init__(self, shockers=(1, 2)):
        self.ids = list(shockers)
        self.is_connected = True
        self.is_paused = False
        self.calls = []
        self.sources = set()        # how the router named its holds
        self.ops_off = {}           # sid -> ops switched off on its card

    def shocker_ids(self):
        return list(self.ids)

    def op_allowed(self, sid, op):
        return op not in self.ops_off.get(sid, ())

    def pulse(self, sid, op, intensity, duration_ms):
        self.calls.append(("pulse", sid, op, intensity, duration_ms))
        return True

    def hold(self, sid, op, intensity, source=""):
        self.calls.append(("hold", sid, op, intensity))
        self.sources.add(source)

    def release(self, sid, source=""):
        self.calls.append(("release", sid))
        self.sources.add(source)

    def end(self, sid):
        self.calls.append(("end", sid))

    def end_all(self):
        self.calls.append(("end_all",))

    def active(self, kind):
        return [c for c in self.calls if c[0] == kind]


@pytest.fixture
def store(monkeypatch):
    s = ParameterStore()
    monkeypatch.setattr(pishock_router, "store", s)
    monkeypatch.setattr(router_base, "store", s)
    return s


def make(rules, engine=None, off=False):
    engine = engine or RecEngine()
    # a test rule that names no shocker means every one (the old default)
    def every(r):
        return r if "shocker" in r or "shockers" in r else {**r, "shockers": "all"}
    full = {"continuous": [clean_continuous(every(r)) for r in rules.get("continuous", [])],
            "triggers": [clean_trigger(every(r)) for r in rules.get("triggers", [])],
            "impacts": [clean_impact(every(r)) for r in rules.get("impacts", [])],
            "zones": [clean_zones(r) for r in rules.get("zones", [])]}
    state = {"off": off}
    router = PiShockRouter(engine, get_rules=lambda: full,
                           is_output_off=lambda: state["off"])
    return router, engine, state


def test_map_intensity_follows_the_value():
    assert map_intensity(0.0001, 0.0, 10, 50) == 10
    assert map_intensity(1.0, 0.0, 10, 50) == 50
    assert map_intensity(0.5, 0.0, 10, 50) == 30
    assert map_intensity(0.6, 0.2, 10, 50) == 30


def test_continuous_holds_while_above_threshold(store):
    router, eng, _ = make({"continuous": [
        {"param": "Prox", "threshold": 0.2, "min_int": 10, "max_int": 50,
         "shocker": 1}]})
    store.update_parameter("Prox", 0.6)
    router.tick()
    assert ("hold", 1, "vibrate", 30) in eng.calls
    assert ("release", 2) not in eng.calls       # other shocker untouched
    eng.calls.clear()
    store.update_parameter("Prox", 0.1)
    router.tick()
    assert ("release", 1) in eng.calls
    assert not eng.active("hold")


def test_a_pulse_trigger_fires_once_per_contact(store):
    router, eng, _ = make({"triggers": [
        {"param": "Tap", "intensity": 25, "duration_ms": 400, "op": "shock"}]})
    router.tick()                                  # baseline
    store.update_parameter("Tap", True)
    store.update_parameter("Tap", False)           # a one-frame pulse
    router.tick()
    assert sorted(eng.active("pulse")) == [("pulse", 1, "shock", 25, 400),
                                           ("pulse", 2, "shock", 25, 400)]
    eng.calls.clear()
    router.tick()
    assert not eng.active("pulse")


def test_contacts_before_the_first_tick_never_fire(store):
    store.update_parameter("Tap", True)
    store.update_parameter("Tap", False)
    router, eng, _ = make({"triggers": [{"param": "Tap"}]})
    router.tick()
    assert not eng.active("pulse")


def test_a_hold_trigger_runs_while_touching(store):
    router, eng, _ = make({"triggers": [
        {"param": "Grab", "mode": "hold", "intensity": 15, "shocker": 2}]})
    store.update_parameter("Grab", True)
    router.tick()
    assert ("hold", 2, "vibrate", 15) in eng.calls
    eng.calls.clear()
    store.update_parameter("Grab", False)
    router.tick()
    assert ("release", 2) in eng.calls


def test_impact_picks_the_strongest_tier_that_fired(store):
    router, eng, _ = make({"impacts": [{
        "shocker": 1, "duration_ms": 300,
        "tiers": [{"param": "Soft", "intensity": 10},
                  {"param": "Mid", "intensity": 25},
                  {"param": "Hard", "intensity": 45}]}]})
    router.tick()
    for p in ("Soft", "Mid"):                     # a medium hit
        store.update_parameter(p, True)
    router.tick()
    assert eng.active("pulse") == [("pulse", 1, "vibrate", 25, 300)]


def test_the_strongest_pulse_per_shocker_wins_across_rules(store):
    router, eng, _ = make({
        "triggers": [{"param": "Tap", "intensity": 20, "shocker": 1}],
        "impacts": [{"shocker": "all", "tiers": [{"param": "Hit", "intensity": 35}]}],
    })
    router.tick()
    store.update_parameter("Tap", True)
    store.update_parameter("Hit", True)
    router.tick()
    pulses = sorted(eng.active("pulse"))
    assert [(p[1], p[3]) for p in pulses] == [(1, 35), (2, 35)]


def test_the_strongest_hold_wins_and_shock_beats_vibrate_on_a_tie(store):
    router, eng, _ = make({
        "continuous": [{"param": "Prox", "min_int": 20, "max_int": 20, "op": "vibrate"}],
        "triggers": [{"param": "Grab", "mode": "hold", "intensity": 20, "op": "shock"}],
    }, engine=RecEngine(shockers=(1,)))
    store.update_parameter("Prox", 1.0)
    store.update_parameter("Grab", True)
    router.tick()
    assert eng.active("hold") == [("hold", 1, "shock", 20)]


def test_off_ends_everything_once_and_fires_nothing(store):
    router, eng, state = make({"triggers": [{"param": "Tap"}],
                               "continuous": [{"param": "Prox"}]})
    store.update_parameter("Prox", 1.0)
    router.tick()
    state["off"] = True
    eng.calls.clear()
    store.update_parameter("Tap", True)
    router.tick()
    router.tick()
    assert eng.calls == [("end_all",)]
    state["off"] = False
    eng.calls.clear()
    router.tick()                                # the contact during Off is gone
    assert not eng.active("pulse")


def test_a_rule_on_one_shocker_ignores_an_unknown_id(store):
    router, eng, _ = make({"triggers": [{"param": "Tap", "shocker": 999}]})
    router.tick()
    store.update_parameter("Tap", True)
    router.tick()
    assert not eng.active("pulse")


def test_disabled_rules_do_nothing(store):
    router, eng, _ = make({"triggers": [{"param": "Tap", "enabled": False}]})
    router.tick()
    store.update_parameter("Tap", True)
    router.tick()
    assert not eng.active("pulse")


def test_notify_wakes_only_for_watched_keys(store):
    router, _eng, _ = make({"triggers": [{"param": "Tap"}]})
    router.notify("SomethingElse")
    assert not router._wake.is_set()
    router.notify("Tap")
    assert router._wake.is_set()


def test_rules_changed_picks_up_edits(store):
    rules = {"continuous": [], "triggers": [], "impacts": []}
    eng = RecEngine()
    router = PiShockRouter(eng, get_rules=lambda: rules, is_output_off=lambda: False)
    router.tick()
    rules["triggers"] = [clean_trigger({"param": "Tap", "shockers": "all"})]
    router.rules_changed()
    router.tick()                                  # baseline for the new key
    store.update_parameter("Tap", True)
    router.tick()
    assert eng.active("pulse")


def test_the_rules_never_let_go_of_a_hold_that_isnt_theirs(store):
    # A friend holding shocker 2 (friends_facade calls the engine itself):
    # the rules' ticks must not end it, with or without rules of their own.
    router, eng, _ = make({"continuous": [{"param": "Prox", "threshold": 0.2,
                                           "shocker": 1}]})
    store.update_parameter("Prox", 0.6)
    router.tick()
    router.tick()
    assert ("release", 2) not in eng.calls
    eng.calls.clear()
    store.update_parameter("Prox", 0.1)
    router.tick()
    assert eng.calls == [("release", 1)]     # only its own
    eng.calls.clear()
    router.tick()
    assert eng.calls == []


def test_vrchat_going_quiet_ends_only_what_the_rules_started(store, monkeypatch):
    router, eng, _ = make({"continuous": [{"param": "Prox", "shocker": 1}]})
    store.update_parameter("Prox", 0.9)
    router.tick()
    eng.calls.clear()
    monkeypatch.setattr(router._stale, "is_stale", lambda: True)
    router.tick()
    router.tick()
    assert eng.calls == [("end", 1)]


def test_a_rule_drives_every_shocker_dropped_on_it_and_none_without(store):
    router, eng, state = make({"triggers": [
        {"param": "Tap", "intensity": 25, "duration_ms": 400, "op": "shock", "shockers": [2, 1]},
        {"param": "Boop", "intensity": 10, "duration_ms": 400, "op": "vibrate", "shockers": []}]})
    assert "Boop" in router._keys                     # watched, so the page sees it live
    router.tick()                                     # baseline
    for key in ("Tap", "Boop"):
        store.update_parameter(key, True)
        store.update_parameter(key, False)
    router.tick()
    assert sorted(eng.active("pulse")) == [("pulse", 1, "shock", 25, 400),
                                           ("pulse", 2, "shock", 25, 400)]


def test_touch_zones_fire_each_contacts_own_shockers(store):
    router, eng, _ = make({"zones": [{
        "enabled": True, "op": "vibrate", "intensity": 15, "duration_ms": 300,
        "zones": [{"param": "Neck", "shockers": [1]}, {"param": "Thigh", "shockers": [2]},
                  {"param": "Belly", "shockers": []}]}]})
    router.tick()                                     # baseline
    store.update_parameter("Thigh", True)
    store.update_parameter("Thigh", False)
    router.tick()
    assert eng.active("pulse") == [("pulse", 2, "vibrate", 15, 300)]


def test_the_rules_hold_as_a_source_of_their_own(store):
    router, eng, _ = make({"continuous": [{"param": "Prox", "threshold": 0.2, "shocker": 1}]})
    store.update_parameter("Prox", 0.6)
    router.tick()
    store.update_parameter("Prox", 0.1)
    router.tick()
    assert eng.active("hold") and eng.active("release")
    assert eng.sources == {pishock_router.SOURCE}


class _Hub:
    """A fake USB hub under the real engine."""

    def __init__(self):
        self.sent, self.port, self.is_open, self.kind = [], "COM9", True, "pishock"

    def set_openshock_shockers(self, _shockers):
        pass

    def open(self, _port, handshake_timeout_s=6.0):
        return {"version": "3.1", "type": 3,
                "shockers": [{"id": 1, "paused": False}, {"id": 2, "paused": False}]}

    def operate(self, sid, op, intensity, ms):
        self.sent.append((sid, op, intensity, ms))
        return True

    def end(self, sid):
        self.sent.append((sid, "end"))
        return True

    def close(self):
        self.is_open = False


def test_the_rules_and_a_friend_on_one_shocker_the_stronger_plays(store):
    # The real engine: a friend holds shocker 1 at 45 while a rule holds it
    # at 30. The friend's stays on (no flip-flop), and the rule letting go
    # never cuts it.
    import pishock_engine
    from pishock_engine import PiShockEngine
    clock, hub = {"t": 100.0}, _Hub()
    engine = PiShockEngine(link_factory=lambda **_k: hub, clock=lambda: clock["t"])
    engine.set_port("COM9")
    engine._want_connected = True
    engine._try_connect()
    engine.set_limits(max_intensity=50, max_pulse_ms=1000, cooldown_s=0.5,
                      max_hold_s=10.0, hold_rest_s=2.0)
    friend = ("friend", "a" * 64, 0)
    router, _eng, _ = make({"continuous": [
        {"param": "Prox", "threshold": 0.2, "min_int": 10, "max_int": 50, "shocker": 1}]},
        engine=engine)
    store.update_parameter("Prox", 0.6)          # the rule: 30
    for _ in range(10):
        engine.hold(1, "vibrate", 45, source=friend)
        router.tick()
        clock["t"] += 0.05
    levels = [s[2] for s in hub.sent if s[0] == 1]
    assert set(levels) == {45}
    store.update_parameter("Prox", 0.1)          # the rule lets go
    router.tick()
    clock["t"] += 0.25
    engine.hold(1, "vibrate", 45, source=friend)
    assert (1, "end") not in hub.sent
    assert hub.sent[-1] == (1, "vibrate", 45, pishock_engine.HOLD_CHUNK_MS)


def test_a_behaviour_skips_a_shocker_whose_op_is_switched_off(store):
    """The engine would refuse it there; another behaviour's op that is on
    wins that shocker instead."""
    engine = RecEngine()
    engine.ops_off = {1: {"shock"}}
    router, eng, _ = make({"triggers": [
        {"param": "Neck", "mode": "hold", "intensity": 40, "op": "shock"},
        {"param": "Thigh", "mode": "hold", "intensity": 20, "op": "vibrate"}]}, engine=engine)
    store.update_parameter("Neck", True)
    store.update_parameter("Thigh", True)
    router.tick()
    holds = {c[1]: (c[2], c[3]) for c in eng.active("hold")}
    assert holds == {1: ("vibrate", 20), 2: ("shock", 40)}


# --- your behaviours pick kind first (Blise's call, 2026-11-16) --------------------

def test_a_weak_shock_beats_a_strong_vibrate_among_your_behaviours(store):
    router, eng, _ = make({
        "triggers": [{"param": "Tap", "intensity": 10, "op": "shock"},
                     {"param": "Tap", "intensity": 90, "op": "vibrate"}],
    }, engine=RecEngine(shockers=(1,)))
    router.tick()
    store.update_parameter("Tap", True)
    router.tick()
    assert [(p[2], p[3]) for p in eng.active("pulse")] == [("shock", 10)]


def test_a_weak_shock_beats_a_strong_vibrate_held_too(store):
    router, eng, _ = make({
        "continuous": [{"param": "Prox", "min_int": 90, "max_int": 90, "op": "vibrate"}],
        "triggers": [{"param": "Grab", "mode": "hold", "intensity": 5, "op": "shock"}],
    }, engine=RecEngine(shockers=(1,)))
    store.update_parameter("Prox", 1.0)
    store.update_parameter("Grab", True)
    router.tick()
    assert eng.active("hold") == [("hold", 1, "shock", 5)]


def test_a_vibrate_beats_any_beep_among_your_behaviours(store):
    router, eng, _ = make({
        "triggers": [{"param": "Tap", "intensity": 100, "op": "beep"},
                     {"param": "Tap", "intensity": 1, "op": "vibrate"}],
    }, engine=RecEngine(shockers=(1,)))
    router.tick()
    store.update_parameter("Tap", True)
    router.tick()
    assert [p[2] for p in eng.active("pulse")] == ["vibrate"]


def test_an_unarmed_shock_ranks_as_the_vibrate_it_goes_out_as(store):
    eng = RecEngine(shockers=(1,))
    eng.is_armed = False
    router, eng, _ = make({
        "triggers": [{"param": "Tap", "intensity": 10, "op": "shock"},
                     {"param": "Tap", "intensity": 90, "op": "vibrate"}],
    }, engine=eng)
    router.tick()
    store.update_parameter("Tap", True)
    router.tick()
    assert [(p[2], p[3]) for p in eng.active("pulse")] == [("vibrate", 90)]


def test_the_router_hands_the_log_what_went_out(store):
    told = []
    eng = RecEngine(shockers=(1,))
    eng.pulse = lambda sid, op, i, ms: pishock_engine.Sent(op, 7, 250, capped=True,
                                                          cut=pishock_engine.CUT_RUN)
    router = PiShockRouter(eng, get_rules=lambda: {"triggers": [clean_trigger(
        {"param": "Tap", "intensity": 40, "duration_ms": 900, "op": "shock",
         "shockers": "all"})]},
        is_output_off=lambda: False, report=lambda *a, **k: told.append((a, k)))
    router.tick()
    store.update_parameter("Tap", True)
    router.tick()
    [(args, kw)] = told
    assert args[:5] == ("pulse", 1, "shock", 40, 900)            # what the behaviour asked
    assert (kw["sent"].intensity, kw["sent"].duration_ms) == (7, 250)   # what went out
