"""PiShockRouter turns the page's rules into engine calls. Driven by
calling tick() against a fresh ParameterStore and a recording engine — no
thread, no hardware."""

import pytest

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

    def shocker_ids(self):
        return list(self.ids)

    def pulse(self, sid, op, intensity, duration_ms):
        self.calls.append(("pulse", sid, op, intensity, duration_ms))
        return True

    def hold(self, sid, op, intensity):
        self.calls.append(("hold", sid, op, intensity))

    def release(self, sid):
        self.calls.append(("release", sid))

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
