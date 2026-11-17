"""PiShockRouter and ShockOSC: a touch that must be held first, the Pull (a
PhysBone's let-go), a ShockOSC group's rest after its shock (the
behaviour's own rest_ms), _Next... only ever less, and a strength of 0
sending nothing. The avatar's _Config reaches the behaviours through the
sync (test_shockosc_sync.py), never the router. Driven tick by tick
against a fresh store, a recording engine and a fake clock."""

import pytest

import pishock_router
import router_base
from parameter_store import ParameterStore
from pishock_router import PiShockRouter, pull_intensity
from settings.pishock import clean_continuous, clean_pull, clean_trigger


class RecEngine:
    def __init__(self, shockers=(1, 2)):
        self.ids = list(shockers)
        self.is_connected = True
        self.is_paused = False
        self.calls = []

    def shocker_ids(self):
        return list(self.ids)

    def op_allowed(self, sid, op):
        return True

    def pulse(self, sid, op, intensity, duration_ms):
        self.calls.append(("pulse", sid, op, intensity, duration_ms))
        return True

    def hold(self, sid, op, intensity, source=""):
        self.calls.append(("hold", sid, op, intensity))

    def release(self, sid, source=""):
        self.calls.append(("release", sid))

    def end(self, sid):
        self.calls.append(("end", sid))

    def end_all(self):
        self.calls.append(("end_all",))

    def active(self, kind):
        return [c for c in self.calls if c[0] == kind]


class Clock:
    def __init__(self):
        self.t = 50.0

    def __call__(self):
        return self.t


@pytest.fixture
def store(monkeypatch):
    s = ParameterStore()
    monkeypatch.setattr(pishock_router, "store", s)
    monkeypatch.setattr(router_base, "store", s)
    return s


def make(rules, shockers=(1,)):
    full = {"triggers": [clean_trigger({"shockers": "all", **r}) for r in rules.get("triggers", [])],
            "continuous": [clean_continuous({"shockers": "all", **r})
                           for r in rules.get("continuous", [])],
            "pulls": [clean_pull({"shockers": "all", **r}) for r in rules.get("pulls", [])]}
    eng, clock = RecEngine(shockers), Clock()
    router = PiShockRouter(eng, get_rules=lambda: full, is_output_off=lambda: False, clock=clock)
    router.tick()                        # baseline
    return router, eng, clock


def step(router, clock, dt=0.01):
    clock.t += dt
    router.tick()


# --- a touch held first ------------------------------------------------------------

def test_a_touch_held_long_enough_fires_once(store):
    router, eng, clock = make({"triggers": [
        {"param": "Neck", "op": "shock", "intensity": 20, "duration_ms": 500, "hold_ms": 250}]})
    store.update_parameter("Neck", True)
    step(router, clock)
    for _ in range(20):                  # 0.2 s: not yet
        step(router, clock)
    assert not eng.active("pulse")
    for _ in range(10):                  # past 0.25 s
        step(router, clock)
    assert eng.active("pulse") == [("pulse", 1, "shock", 20, 500)]
    for _ in range(100):                 # still held: no second shock
        step(router, clock)
    assert len(eng.active("pulse")) == 1
    store.update_parameter("Neck", False)
    step(router, clock)
    store.update_parameter("Neck", True)  # a fresh touch, counted from the tick it's seen
    step(router, clock)
    step(router, clock, 0.3)
    assert len(eng.active("pulse")) == 2


def test_a_brush_shorter_than_the_hold_does_nothing(store):
    router, eng, clock = make({"triggers": [{"param": "Neck", "hold_ms": 250}]})
    store.update_parameter("Neck", True)
    step(router, clock, 0.1)
    store.update_parameter("Neck", False)
    step(router, clock, 0.5)
    store.update_parameter("Neck", True)
    store.update_parameter("Neck", False)   # one frame, inside a tick
    step(router, clock, 0.5)
    assert not eng.active("pulse")


def test_without_a_hold_time_a_contact_fires_on_its_edge_as_before(store):
    router, eng, clock = make({"triggers": [{"param": "Tap", "intensity": 15}]})
    store.update_parameter("Tap", True)
    store.update_parameter("Tap", False)
    step(router, clock)
    assert eng.active("pulse") == [("pulse", 1, "vibrate", 15, 500)]


# --- the Pull --------------------------------------------------------------------

def test_pull_intensity_follows_the_stretch():
    assert pull_intensity(0.0, 10, 50) == 10
    assert pull_intensity(1.0, 10, 50) == 50
    assert pull_intensity(0.5, 10, 50) == 30
    assert pull_intensity(4.0, 10, 50) == 50


def test_a_pull_vibrates_while_held_and_shocks_on_the_let_go(store):
    router, eng, clock = make({"pulls": [
        {"param": "Tail", "min_int": 10, "max_int": 50, "duration_ms": 700}]})
    store.update_parameter("Tail_IsGrabbed", True)
    store.update_parameter("Tail_Stretch", 0.25)
    step(router, clock)
    assert eng.active("hold") == [("hold", 1, "vibrate", 20)]
    store.update_parameter("Tail_Stretch", 0.75)
    step(router, clock)
    assert eng.active("hold")[-1] == ("hold", 1, "vibrate", 40)
    eng.calls.clear()
    store.update_parameter("Tail_IsGrabbed", False)
    step(router, clock)
    # the strength from the stretch at the let-go, the shock its own length
    assert eng.active("pulse") == [("pulse", 1, "shock", 40, 700)]
    assert ("release", 1) in eng.calls
    eng.calls.clear()
    step(router, clock)
    assert not eng.active("pulse")       # once


def test_a_let_go_without_stretch_does_nothing(store):
    router, eng, clock = make({"pulls": [{"param": "Tail", "held_op": "none"}]})
    store.update_parameter("Tail_IsGrabbed", True)
    step(router, clock)
    assert not eng.active("hold")        # nothing while held
    store.update_parameter("Tail_IsGrabbed", False)
    step(router, clock)
    assert not eng.active("pulse")


def test_a_stretch_reset_with_the_let_go_still_counts(store):
    router, eng, clock = make({"pulls": [{"param": "Tail", "min_int": 10, "max_int": 50}]})
    store.update_parameter("Tail_IsGrabbed", True)
    store.update_parameter("Tail_Stretch", 1.0)
    step(router, clock)
    store.update_parameter("Tail_Stretch", 0.0)      # VRChat snaps it back...
    store.update_parameter("Tail_IsGrabbed", False)  # ...in the same tick
    step(router, clock)
    assert eng.active("pulse") == [("pulse", 1, "shock", 50, 500)]


# --- ShockOSC groups: the rest after a shock, _Next..., strength 0 -----------------

def test_the_avatars_config_no_longer_reaches_the_router(store):
    """The avatar's ShockOSC settings are kept in step with the behaviours'
    own values by the sync (shockosc_sync.py) -- the router reads only the
    behaviours, so a stale value VRChat holds can't fight them."""
    router, eng, clock = make({"triggers": [
        {"param": "ShockOsc/Collar_IShock", "op": "shock", "intensity": 40}]})
    store.update_parameter("ShockOsc/_Config/_All/Intensity", 0.05)
    store.update_parameter("ShockOsc/_Config/_All/Paused", True)
    store.update_parameter("ShockOsc/Collar_IShock", True)
    step(router, clock)
    assert eng.active("pulse") == [("pulse", 1, "shock", 40, 500)]
    assert not any(k.startswith("ShockOsc/_Config/") for k in router._compiled.read)


def test_next_values_soften_and_shorten_the_next_action_only(store):
    router, eng, clock = make({"triggers": [
        {"param": "ShockOsc/Collar_IShock", "op": "shock", "intensity": 40,
         "duration_ms": 3000}],
        "continuous": [{"param": "ShockOsc/Collar_CVibrate", "op": "vibrate",
                        "min_int": 10, "max_int": 60}]})
    store.update_parameter("ShockOsc/Collar_NextIntensity", 0.25)
    store.update_parameter("ShockOsc/Collar_NextDuration", 0.5)
    store.update_parameter("ShockOsc/Collar_IShock", True)
    store.update_parameter("ShockOsc/Collar_CVibrate", 1.0)
    step(router, clock)
    assert eng.active("pulse") == [("pulse", 1, "shock", 25, 1500)]
    eng.calls.clear()
    store.update_parameter("ShockOsc/Collar_NextIntensity", 0.9)       # never more
    store.update_parameter("ShockOsc/Collar_IShock", False)
    step(router, clock, 2.0)
    store.update_parameter("ShockOsc/Collar_IShock", True)
    step(router, clock)
    assert eng.active("pulse") == [("pulse", 1, "shock", 40, 1500)]
    assert ("hold", 1, "vibrate", 60) in eng.calls                      # continuous ignores Next


@pytest.mark.parametrize("rules, value", [
    ({"triggers": [{"param": "Tap", "intensity": 0}]}, ("Tap", True)),
    ({"triggers": [{"param": "Tap", "intensity": 0, "mode": "hold"}]}, ("Tap", True)),
    ({"continuous": [{"param": "Prox", "min_int": 0, "max_int": 0}]}, ("Prox", 1.0)),
    ({"pulls": [{"param": "Tail", "min_int": 0, "max_int": 0, "held_op": "vibrate"}]},
     ("Tail_IsGrabbed", True)),
])
def test_a_strength_of_0_sends_nothing(store, rules, value):
    router, eng, clock = make(rules)
    store.update_parameter(*value)
    store.update_parameter("Tail_Stretch", 0.5)
    step(router, clock)
    store.update_parameter(value[0], False)
    step(router, clock)
    assert not eng.active("pulse") and not eng.active("hold")


def test_a_groups_rest_after_its_shock_is_the_behaviours_own(store):
    router, eng, clock = make({"triggers": [
        {"param": "ShockOsc/Collar_IShock", "op": "shock", "duration_ms": 1000,
         "rest_ms": 5000},
        {"param": "ShockOsc/Collar_IVibrate", "op": "vibrate", "rest_ms": 5000},
        {"param": "ShockOsc/Tail_IShock", "op": "shock"}]}, shockers=(1, 2))
    store.update_parameter("ShockOsc/Collar_IShock", True)
    step(router, clock)
    assert len(eng.active("pulse")) == 2
    assert router.shockosc_rests()["collar"] == (pytest.approx(clock.t + 1.0), 5.0)
    eng.calls.clear()
    store.update_parameter("ShockOsc/Collar_IVibrate", True)     # the group rests...
    store.update_parameter("ShockOsc/Tail_IShock", True)         # ...another doesn't
    step(router, clock, 2.0)
    assert [c[2] for c in eng.active("pulse")] == ["shock", "shock"]   # only Tail's
    eng.calls.clear()
    store.update_parameter("ShockOsc/Collar_IVibrate", False)
    step(router, clock, 4.5)                                      # 6.5 s after: rested
    store.update_parameter("ShockOsc/Collar_IVibrate", True)
    step(router, clock)
    assert [c[2] for c in eng.active("pulse")] == ["vibrate", "vibrate"]
    assert "collar" not in router.shockosc_rests()


def test_only_a_shock_rests_the_group_and_no_rest_is_the_shockers_own(store):
    router, eng, clock = make({"triggers": [
        {"param": "ShockOsc/Collar_IVibrate", "op": "vibrate", "rest_ms": 5000},
        {"param": "ShockOsc/Tail_IShock", "op": "shock", "rest_ms": 0}]})
    store.update_parameter("ShockOsc/Collar_IVibrate", True)
    store.update_parameter("ShockOsc/Tail_IShock", True)
    step(router, clock)
    assert router.shockosc_rests() == {}


def test_a_behaviour_on_another_parameter_has_no_group_rest(store):
    router, eng, clock = make({"triggers": [
        {"param": "Contact/Boop", "op": "shock", "rest_ms": 9000}]})
    store.update_parameter("Contact/Boop", True)
    step(router, clock)
    assert router.shockosc_rests() == {}


def test_only_next_is_watched_for_shockosc_behaviours(store):
    router, _eng, _clock = make({"triggers": [{"param": "Contact/Boop"}]})
    assert router._compiled.cfg_keys == frozenset()
    router, _eng, _clock = make({"triggers": [{"param": "ShockOsc/Collar"}]})
    assert router._compiled.cfg_keys == {"ShockOsc/Collar_NextIntensity",
                                         "ShockOsc/Collar_NextDuration"}
    assert "ShockOsc/Collar_NextIntensity" not in router._keys     # no wake for these
    assert "ShockOsc/Collar" in router._keys


def map_level(v, lo, hi):
    return pishock_router.map_intensity(v, 0.0, lo, hi)


# --- the avatar's Paused stops a group like Stop ------------------------------------

def test_paused_ends_a_pulse_of_that_group_still_playing_at_once(store):
    router, eng, clock = make({"triggers": [
        {"param": "ShockOsc/Collar_IShock", "op": "shock", "duration_ms": 3000,
         "shockers": [1]},
        {"param": "ShockOsc/Tail_IShock", "op": "shock", "duration_ms": 3000,
         "shockers": [2]},
        {"param": "Contact/Boop", "op": "vibrate", "duration_ms": 3000, "shockers": [3]}]},
        shockers=(1, 2, 3))
    for p in ("ShockOsc/Collar_IShock", "ShockOsc/Tail_IShock", "Contact/Boop"):
        store.update_parameter(p, True)
    step(router, clock)
    assert len(eng.active("pulse")) == 3
    eng.calls.clear()
    router.stop_shockosc({"collar"})                  # a group's own Paused
    assert router._wake.is_set()                      # the tick runs now
    step(router, clock, 0.5)
    assert eng.active("end") == [("end", 1)]          # Collar's only, at once
    eng.calls.clear()
    router.stop_shockosc(None)                        # the global kill switch
    step(router, clock)
    assert eng.active("end") == [("end", 2)]          # every ShockOSC group, not Boop's
    eng.calls.clear()
    router.stop_shockosc(None)
    step(router, clock)
    assert eng.active("end") == []                    # nothing of theirs left playing


def test_paused_leaves_a_pulse_that_has_ended_or_was_replaced(store):
    router, eng, clock = make({"triggers": [
        {"param": "ShockOsc/Collar_IShock", "op": "shock", "duration_ms": 500},
        {"param": "Contact/Boop", "op": "shock", "intensity": 60, "duration_ms": 3000}]})
    store.update_parameter("ShockOsc/Collar_IShock", True)
    step(router, clock)
    store.update_parameter("Contact/Boop", True)      # your own behaviour, after it
    step(router, clock)
    eng.calls.clear()
    router.stop_shockosc(None)
    step(router, clock)
    assert eng.active("end") == []                    # Boop's pulse plays on
    clock.t += 5
    router.stop_shockosc(None)
    step(router, clock)
    assert eng.active("end") == []


def test_paused_stops_from_the_same_tick_the_behaviours_go_off(store):
    rules = {"continuous": [clean_continuous({"param": "ShockOsc/Collar_CShock",
                                              "op": "shock", "shockers": "all"})],
             "triggers": [], "pulls": []}
    eng, clock = RecEngine((1,)), Clock()
    router = PiShockRouter(eng, get_rules=lambda: rules, is_output_off=lambda: False,
                           clock=clock)
    router.tick()
    store.update_parameter("ShockOsc/Collar_CShock", 1.0)
    step(router, clock)
    assert eng.active("hold")
    eng.calls.clear()
    # the sync: Off first, then the stop
    rules["continuous"] = [dict(rules["continuous"][0], enabled=False)]
    router.rules_changed()
    router.stop_shockosc({"Collar"})
    step(router, clock)
    assert eng.calls == [("release", 1)]              # its own hold; others' holds go on
