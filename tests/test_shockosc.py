"""shockosc.py: ShockOSC's parameter names as its source has them (3.2.0,
OpenShock/ShockOSC develop @ 97e4b47), the one-click setup's mapping (a
new behaviour's values), _Next... only ever less, and which avatar
parameter each behaviour value is kept in step with, units turned."""

import pytest

import shockosc as so
from settings.pishock import clean_continuous, clean_pull, clean_trigger, new_rule_values


# --- the names, pinned against ShockOSC's source ----------------------------------

def test_the_suffixes_are_shockoscs_own():
    # ShockOsc.cs ShockerParams: every suffix it reads, inputs and feedback
    assert set(so.INPUTS) | set(so.FEEDBACK) == {
        "", "Stretch", "IsGrabbed", "Cooldown", "Active", "Intensity", "CooldownPercentage",
        "DurationRemaining", "IShock", "IVibrate", "ISound", "CShock", "CVibrate", "CSound",
        "NextIntensity", "NextDuration"}
    assert so.PREFIX == "ShockOsc/" and so.ALL == "_All" and so.ANY == "_Any"


@pytest.mark.parametrize("name, parts", [
    ("ShockOsc/Collar", ("Collar", "")),
    ("ShockOsc/Collar_IShock", ("Collar", "IShock")),
    ("ShockOsc/Left Leg_CVibrate", ("Left Leg", "CVibrate")),
    ("ShockOsc/Tail_IsGrabbed", ("Tail", "IsGrabbed")),
    ("ShockOsc/Tail_Stretch", ("Tail", "Stretch")),
    ("ShockOsc/_All", ("_All", "")),                 # its underscore isn't a split
    ("ShockOsc/_All_ISound", ("_All", "ISound")),
    ("ShockOsc/_Any_Active", ("_Any", "Active")),
    ("ShockOsc/Collar_NextIntensity", ("Collar", "NextIntensity")),
    ("/avatar/parameters/ShockOsc/Collar_CooldownPercentage", ("Collar", "CooldownPercentage")),
])
def test_a_name_splits_as_shockosc_splits_it(name, parts):
    assert so.split(name) == parts


@pytest.mark.parametrize("name", [
    "ShockOsc/Tail_Angle", "ShockOsc/Tail_IsPosed", "ShockOsc/Tail_Squish",  # not ShockOSC's
    "ShockOsc/_Config/_All/Paused", "ShockOsc/_Config/Paused",               # settings
    "shockosc/Collar", "ShockOSC/Collar",           # the prefix is case-sensitive
    "ShockOsc/Collar_ishock",                       # ...and so is a suffix
    "ShockOsc/", "Collar", "MyShockOsc/Collar",
])
def test_anything_else_isnt_a_group_parameter(name):
    assert so.split(name) is None


def test_param_builds_the_names_back():
    assert so.param("Collar") == "ShockOsc/Collar"
    assert so.param("_All", so.C_SHOCK) == "ShockOsc/_All_CShock"
    assert so.config_param("_All", "Paused") == "ShockOsc/_Config/_All/Paused"


# --- what an avatar has -----------------------------------------------------------

AVATAR = [
    "ShockOsc/Collar", "ShockOsc/Collar_IShock", "ShockOsc/Collar_CVibrate",
    "ShockOsc/Collar_Active", "ShockOsc/Collar_Cooldown", "ShockOsc/Collar_Intensity",
    "ShockOsc/Tail_IsGrabbed", "ShockOsc/Tail_Stretch", "ShockOsc/Tail_Angle",
    "ShockOsc/_All_ISound", "ShockOsc/_Any_Active", "ShockOsc/_Config/_All/Intensity",
    "ShockOsc/Glow_Active",              # feedback only: lights, drives nothing
    "Contact/Headpat", "VF12_Hat",
]


def test_the_groups_an_avatar_drives():
    assert so.groups_on_avatar(AVATAR) == {
        "Collar": frozenset({"", "IShock", "CVibrate"}),
        "Tail": frozenset({"IsGrabbed", "Stretch"}),
        "_All": frozenset({"ISound"}),
    }
    assert so.feedback_groups_on_avatar(AVATAR) == {"Collar", "Glow", "_Any"}
    assert so.has_shockosc(AVATAR) and not so.has_shockosc(["Contact/Headpat"])


def test_a_group_spelled_two_ways_is_one_group():
    got = so.groups_on_avatar(["ShockOsc/Collar", "ShockOsc/collar_IShock"])
    assert got == {"Collar": frozenset({"", "IShock"})}


def test_a_group_takes_the_shocker_with_its_name():
    shockers = [(24325, "Left Leg"), (24326, "Collar")]
    assert so.suggested_shockers("collar", shockers) == [24326]
    assert so.suggested_shockers("LeftLeg", shockers) == [24325]     # spaces aside
    assert so.suggested_shockers("Tail", shockers) == []
    assert so.suggested_shockers("_All", shockers) == "all"
    assert so.label("_All") == "All shockers" and so.label("Tail") == "Tail"


# --- the one-click setup ----------------------------------------------------------

DEFAULTS = {kind: new_rule_values(kind) for kind in ("triggers", "continuous", "pulls")}


def test_each_parameter_becomes_its_behaviour():
    plan = so.planned_rules("Collar", {"", "IShock", "IVibrate", "ISound", "CShock",
                                       "CVibrate", "CSound", "IsGrabbed"}, [7], DEFAULTS)
    got = {(kind, r["param"]): r for kind, r in plan}
    touch = got[("triggers", "ShockOsc/Collar")]
    assert (touch["mode"], touch["op"]) == ("pulse", "shock")
    for suffix, op in (("IShock", "shock"), ("IVibrate", "vibrate"), ("ISound", "beep")):
        r = got[("triggers", f"ShockOsc/Collar_{suffix}")]
        assert (r["mode"], r["op"]) == ("pulse", op)
    for suffix, op in (("CShock", "shock"), ("CVibrate", "vibrate"), ("CSound", "beep")):
        assert got[("continuous", f"ShockOsc/Collar_{suffix}")]["op"] == op
    pull = got[("pulls", "ShockOsc/Collar")]
    assert (pull["op"], pull["held_op"]) == ("shock", "vibrate")
    assert all(r["shockers"] == [7] for r in got.values())
    assert len(plan) == 8


def test_the_setup_starts_with_a_new_behaviours_values():
    """Blise's call (2026-11-16): the same values as a new behaviour of the
    kind on the page -- taken from there, never kept twice."""
    plan = so.planned_rules("Collar", {"", "IShock", "CVibrate", "IsGrabbed"}, [7], DEFAULTS)
    for kind, rule in plan:
        own = {k: v for k, v in DEFAULTS[kind].items()
               if k not in ("name", "param", "op", "mode", "shockers")
               and not (rule["param"] == "ShockOsc/Collar" and k == "hold_ms")}
        assert {k: rule[k] for k in own} == own, kind
    touch = next(r for k, r in plan if r["param"] == "ShockOsc/Collar")
    assert (touch["intensity"], touch["duration_ms"], touch["hold_ms"], touch["rest_ms"]) == \
        (20, 500, so.TOUCH_HOLD_MS, 0)
    cont = next(r for k, r in plan if k == "continuous")
    assert (cont["min_int"], cont["max_int"]) == (5, 30)


def test_a_touch_waits_for_shockoscs_hold_time_so_a_brush_does_nothing():
    """Blise's call (2026-11-17): ShockOSC's 0.25 s for its touch; the
    instant ones still fire at once."""
    plan = so.planned_rules("Collar", {"", "IShock"}, [7], DEFAULTS)
    holds = {r["param"]: r["hold_ms"] for _k, r in plan}
    assert so.TOUCH_HOLD_MS == 250
    assert holds == {"ShockOsc/Collar": 250, "ShockOsc/Collar_IShock": 0}


def test_the_planned_behaviours_survive_the_settings_cleaners():
    clean = {"triggers": clean_trigger, "continuous": clean_continuous, "pulls": clean_pull}
    for kind, rule in so.planned_rules("_All", {"", "IShock", "CVibrate", "IsGrabbed"}, "all",
                                       DEFAULTS):
        cleaned = clean[kind](rule)
        assert {k: cleaned[k] for k in rule} == rule, kind


def test_stretch_alone_is_no_pull_and_next_alone_is_nothing():
    assert so.planned_rules("Tail", {"Stretch"}, [], DEFAULTS) == []
    assert so.planned_rules("Tail", {"NextIntensity", "NextDuration"}, [], DEFAULTS) == []


def test_a_second_setup_adds_nothing():
    plan = so.planned_rules("Collar", {"", "IShock", "CVibrate"}, [1], DEFAULTS)
    assert len(so.missing_rules(plan, {})) == 3
    rules = {"triggers": [r for k, r in plan if k == "triggers"],
             "continuous": [r for k, r in plan if k == "continuous"]}
    assert so.missing_rules(plan, rules) == []


def test_a_behaviour_made_by_hand_counts():
    plan = so.planned_rules("Collar", {"", "IShock"}, [1], DEFAULTS)
    rules = {"zones": [{"zones": [{"param": "ShockOsc/Collar", "shockers": [2]}]}],
             "continuous": [{"param": "ShockOsc/Collar_IShock"}]}     # another kind
    assert [r["param"] for _k, r in so.missing_rules(plan, rules)] == ["ShockOsc/Collar_IShock"]


def test_a_rules_group_and_what_it_is():
    assert so.group_of_rule("ShockOsc/Collar_CShock") == "Collar"
    assert so.group_of_rule("ShockOsc/Tail") == "Tail"
    assert so.group_of_rule("Contact/Headpat") is None
    assert so.is_touch("ShockOsc/Collar") and not so.is_touch("ShockOsc/Collar_IShock")
    plan = dict((r["param"] + k, so.describe(k, r)) for k, r in so.planned_rules(
        "Collar", {"", "ISound", "CShock", "IsGrabbed"}, [], DEFAULTS))
    assert sorted(plan.values()) == ["beep at once", "continuous shock", "pull", "touch"]


# --- _NextIntensity / _NextDuration: per action, only ever less ----------------------

def test_next_intensity_and_duration_only_lower_the_next_action():
    n = so.read_next({"ShockOsc/Collar_NextIntensity": 0.15,
                      "ShockOsc/Collar_NextDuration": 0.5}, ["Collar"])
    assert n.strength("Collar", 40) == 15 and n.length("Collar", 800) == 400
    assert n.strength("Other", 40) == 40
    n = so.read_next({"ShockOsc/Collar_NextIntensity": 0.9}, ["Collar"])     # never more
    assert n.strength("Collar", 40) == 40
    n = so.read_next({"ShockOsc/Collar_NextIntensity": 0.0,
                      "ShockOsc/Collar_NextDuration": "junk"}, ["Collar"])    # 0 = unset
    assert n.strength("Collar", 40) == 40 and n.length("Collar", 800) == 800
    assert so.watched_params(["Collar"]) == ["ShockOsc/Collar_NextIntensity",
                                            "ShockOsc/Collar_NextDuration"]


# --- one value each: which avatar parameter a behaviour's value goes with ------------

GLOBAL = {f"ShockOsc/_Config/_All/{s}" for s in (
    "Paused", "Intensity", "MaxIntensity", "MinIntensity", "Duration", "MaxDuration",
    "CooldownTime", "HoldTime")}


def has(names):
    return lambda n: n in names


def test_config_setting_names():
    assert so.config_setting("ShockOsc/_Config/_All/Intensity") == ("_All", "Intensity")
    assert so.config_setting("/avatar/parameters/ShockOsc/_Config/Collar/Paused") == \
        ("Collar", "Paused")
    assert so.config_setting("ShockOsc/_Config/Paused") == ("_All", "Paused")     # legacy
    assert so.config_setting("ShockOsc/_Config/a/b/c") is None
    assert so.config_setting("ShockOsc/Collar") is None


def test_a_group_follows_all_unless_the_avatar_has_its_own():
    a = has(GLOBAL)
    assert so.address("Collar", so.STRENGTH, a, {}) == "ShockOsc/_Config/_All/Intensity"
    own = has(GLOBAL | {"ShockOsc/_Config/Collar/Intensity"})
    assert so.address("Collar", so.STRENGTH, own, {}) == "ShockOsc/_Config/Collar/Intensity"
    assert so.address("Tail", so.STRENGTH, own, {}) == "ShockOsc/_Config/_All/Intensity"
    assert so.address("_All", so.STRENGTH, own, {}) == "ShockOsc/_Config/_All/Intensity"
    # the avatar says the group's own isn't in use: the global again
    off = {"ShockOsc/_Config/Collar/OverrideIntensity": False}
    assert so.address("Collar", so.STRENGTH, own, off) == "ShockOsc/_Config/_All/Intensity"
    # the hold time is global only; Paused falls back to the legacy kill switch
    assert so.address("Collar", so.HOLD, a, {}) == "ShockOsc/_Config/_All/HoldTime"
    legacy = has({"ShockOsc/_Config/Paused"})
    assert so.address("Collar", so.ON, legacy, {}) == "ShockOsc/_Config/Paused"
    assert so.address("Collar", so.REST, has(set()), {}) is None      # nothing to go with


def test_the_mode_picks_intensity_or_its_range():
    a = has(GLOBAL)
    rng = {"ShockOsc/_Config/_All/ModeIntensity": True, "ShockOsc/_Config/_All/ModeDuration": True}
    assert so.address("Collar", so.STRENGTH, a, rng) == "ShockOsc/_Config/_All/MaxIntensity"
    assert so.address("Collar", so.LOW, a, rng) == "ShockOsc/_Config/_All/MinIntensity"
    assert so.address("Collar", so.LENGTH, a, rng) == "ShockOsc/_Config/_All/MaxDuration"
    assert so.address("Collar", so.LOW, a, {}) is None          # fixed: no bottom
    # a mode it doesn't say: whichever it has
    only_top = has({"ShockOsc/_Config/_All/MaxIntensity"})
    assert so.address("Collar", so.STRENGTH, only_top, {}) == "ShockOsc/_Config/_All/MaxIntensity"


def test_what_of_a_behaviour_goes_with_the_avatar():
    assert set(so.fields_of("triggers", "ShockOsc/Collar")) == {
        so.STRENGTH, so.LENGTH, so.REST, so.HOLD, so.ON}
    assert so.HOLD not in so.fields_of("triggers", "ShockOsc/Collar_IShock")
    assert set(so.fields_of("continuous", "ShockOsc/Collar_CShock")) == {
        so.STRENGTH, so.LOW, so.REST, so.ON}
    assert set(so.fields_of("pulls", "ShockOsc/Tail")) == {
        so.STRENGTH, so.LOW, so.LENGTH, so.REST, so.ON}
    assert so.fields_of("triggers", "Contact/Boop") == {}
    assert so.fields_of("impacts", "ShockOsc/Collar") == {}


@pytest.mark.parametrize("setting, value, ogp, avatar", [
    ("Intensity", so.STRENGTH, 25, 0.25),
    ("MaxIntensity", so.STRENGTH, 100, 1.0),
    ("MinIntensity", so.LOW, 5, 0.05),
    ("Duration", so.LENGTH, 2000, 0.2),               # x 10 000 ms
    ("CooldownTime", so.REST, 5000, 0.05),            # x 100 000 ms
    ("HoldTime", so.HOLD, 250, 0.25),                 # x 1 000 ms
    ("Paused", so.ON, False, True),
])
def test_the_units_turn_both_ways(setting, value, ogp, avatar):
    name = f"ShockOsc/_Config/_All/{setting}"
    assert so.to_avatar(name, value, ogp) == pytest.approx(avatar)
    assert so.from_avatar(name, value, avatar) == ogp


def test_the_avatars_values_are_clamped_as_shockosc_clamps_them():
    d = "ShockOsc/_Config/_All/Duration"
    assert so.from_avatar(d, so.LENGTH, 0.0) == 300            # ShockOSC's floor
    assert so.from_avatar(d, so.LENGTH, 5.0) == 10000
    assert so.to_avatar(d, so.LENGTH, 15000) == 1.0            # OGP's 15 s: as far as it goes
    i = "ShockOsc/_Config/_All/Intensity"
    assert so.from_avatar(i, so.STRENGTH, 0.0) == 0            # 0 -- sends nothing
    assert so.from_avatar(i, so.STRENGTH, "lots") is None
    assert so.from_avatar("ShockOsc/_Config/_All/Paused", so.ON, "yes") is None


def test_a_strength_under_the_bottom_takes_the_bottom_along():
    pull = {"min_int": 20, "max_int": 40}
    assert so.with_value("pulls", pull, so.STRENGTH, 10) == {"min_int": 10, "max_int": 10}
    assert so.with_value("pulls", pull, so.LOW, 60) == {"min_int": 40, "max_int": 40}
    assert so.with_value("triggers", {"intensity": 5}, so.STRENGTH, 0) == {"intensity": 0}


def test_same_and_synced_settings():
    assert so.same(0.25, 0.2500001) and not so.same(0.25, 0.26)
    assert so.same(True, 1.0) and not so.same(False, True)
    assert so.synced_settings(GLOBAL | {"ShockOsc/_Config/_All/ModeIntensity",
                                        "ShockOsc/Collar"}) == [
        "Intensity", "MinIntensity", "MaxIntensity", "Duration", "MaxDuration",
        "CooldownTime", "HoldTime", "Paused"]
