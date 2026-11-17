"""PiShock settings: every value cleaned in and out, so a hand-edited file
can't hand the router a malformed or unsafe rule."""

import json

import pishock_limits
from settings.pishock import PiShockSettingsManager


def test_defaults_are_conservative():
    s = PiShockSettingsManager()
    assert s.get_auto_connect() is False
    assert s.get_limits()["max_intensity"] == 30
    assert all(s.get_rules(k) == [] for k in ("continuous", "triggers", "impacts"))


def test_add_edit_delete_rules():
    s = PiShockSettingsManager()
    assert s.add_rule("triggers") == 0
    s.set_rule("triggers", 0, {"param": "/avatar/parameters/Tap", "mode": "hold",
                                "intensity": 250, "op": "zap", "shocker": "12"})
    rule = s.get_rules("triggers")[0]
    assert rule["param"] == "Tap"
    assert rule["mode"] == "hold"
    assert rule["intensity"] == 100
    assert rule["op"] == "vibrate"
    assert rule["shockers"] == [12]
    s.delete_rule("triggers", 0)
    assert s.get_rules("triggers") == []


def test_new_impact_starts_with_three_rising_tiers():
    s = PiShockSettingsManager()
    s.add_rule("impacts")
    tiers = s.get_rules("impacts")[0]["tiers"]
    assert [t["intensity"] for t in tiers] == sorted(t["intensity"] for t in tiers)
    assert len(tiers) == 3


def test_continuous_min_and_max_are_ordered():
    s = PiShockSettingsManager()
    s.add_rule("continuous")
    s.set_rule("continuous", 0, {"min_int": 60, "max_int": 10, "threshold": 5})
    rule = s.get_rules("continuous")[0]
    assert (rule["min_int"], rule["max_int"]) == (10, 60)
    assert rule["threshold"] == 0.99


def test_limits_are_stored_clamped():
    s = PiShockSettingsManager()
    s.set_limit("max_intensity", 900)
    s.set_limit("cooldown_s", -3)
    s.set_limit("continuous", "sneaky")          # not a limit: ignored
    s.set_limit("a_setting_from_next_year", 5)   # nor anything else that isn't
    lim = s.get_limits()
    assert lim["max_intensity"] == 100
    assert lim["cooldown_s"] == 0.1
    assert isinstance(s.settings["continuous"], list)
    assert "a_setting_from_next_year" not in s.settings


def test_a_hand_edited_file_is_cleaned_on_read():
    path = PiShockSettingsManager.FILE_PATH
    with open(path, "w", encoding="utf-8") as fh:
        json.dump({"max_intensity": "lots", "triggers": [{"intensity": "x"}, 7],
                   "impacts": "broken"}, fh)
    s = PiShockSettingsManager()
    assert s.get_limits()["max_intensity"] == 30
    assert [r["intensity"] for r in s.get_rules("triggers")] == [20]
    assert s.get_rules("impacts") == []


def test_infinite_or_huge_numbers_fall_back_instead_of_breaking_the_page():
    """json reads 1e999 as inf and a 400-digit number as an int no float
    holds; both used to raise OverflowError, so the Shockers feature failed
    to start. Now they fall back like any other garbage."""
    inf, huge = float("inf"), int("9" * 400)
    path = PiShockSettingsManager.FILE_PATH
    with open(path, "w", encoding="utf-8") as fh:
        json.dump({"max_intensity": inf, "max_pulse_ms": -inf, "cooldown_s": huge,
                   "triggers": [{"intensity": inf, "duration_ms": huge, "shocker": inf}],
                   "continuous": [{"min_int": -inf, "max_int": huge, "threshold": huge}],
                   "impacts": [{"tiers": [{"intensity": huge}], "shocker": -inf}],
                   "openshock_shockers": [{"id": inf}, {"id": huge}, {"id": 7}]}, fh)
    s = PiShockSettingsManager()
    lim = s.get_limits()
    for key in ("max_intensity", "max_vibrate", "max_pulse_ms", "cooldown_s"):
        assert lim[key] == pishock_limits.default(key), key
    trigger = s.get_rules("triggers")[0]
    assert (trigger["intensity"], trigger["duration_ms"], trigger["shockers"]) == (20, 500, [])
    cont = s.get_rules("continuous")[0]
    assert (cont["min_int"], cont["max_int"], cont["threshold"]) == (5, 30, 0.0)
    impact = s.get_rules("impacts")[0]
    assert impact["tiers"][0]["intensity"] == 20 and impact["shockers"] == []
    assert [x["id"] for x in s.get_openshock_shockers()] == [7]


def test_openshock_shockers_get_unique_random_ids():
    s = PiShockSettingsManager()
    assert s.get_openshock_shockers() == []
    for _ in range(3):
        s.add_openshock_shocker()
    shockers = s.get_openshock_shockers()
    ids = [x["id"] for x in shockers]
    assert len(set(ids)) == 3
    assert all(1 <= i <= 65535 for i in ids)
    assert all(x["model"] == "caixianlin" for x in shockers)


def test_an_openshock_id_another_entry_has_is_refused():
    s = PiShockSettingsManager()
    s.add_openshock_shocker()
    s.add_openshock_shocker()
    first, second = s.get_openshock_shockers()
    s.set_openshock_shocker(1, {**second, "id": first["id"], "name": "Ankle"})
    after = s.get_openshock_shockers()[1]
    assert after["id"] == second["id"]
    assert after["name"] == "Ankle"
    s.set_openshock_shocker(1, {**after, "id": 1234, "model": "petrainer"})
    assert s.get_openshock_shockers()[1]["id"] == 1234
    s.delete_openshock_shocker(0)
    assert [x["id"] for x in s.get_openshock_shockers()] == [1234]


def test_the_openshock_list_is_not_a_limit():
    s = PiShockSettingsManager()
    s.set_limit("openshock_shockers", "sneaky")
    assert s.get_openshock_shockers() == []



def test_the_vibrate_cap_starts_where_the_shock_cap_is():
    path = PiShockSettingsManager.FILE_PATH
    with open(path, "w", encoding="utf-8") as fh:
        json.dump({"max_intensity": 45}, fh)
    s = PiShockSettingsManager()
    assert s.get_limits()["max_vibrate"] == 45          # an older file: unchanged feel
    s.set_limit("max_vibrate", 90)
    assert s.get_limits() == {**s.get_limits(), "max_intensity": 45, "max_vibrate": 90}
    s.set_limit("max_vibrate", 500)
    assert s.get_limits()["max_vibrate"] == 100


def test_shocker_names_are_cleaned_kept_and_given_back():
    from settings.pishock import PiShockSettingsManager
    s = PiShockSettingsManager()
    s.set_shocker_name(24325, "  My   collar  ")
    s.set_shocker_name(24326, "x" * 80)
    assert s.get_shocker_names() == {"24325": "My collar", "24326": "x" * 40}
    s.set_limit("shocker_names", {"1": "nope"})            # not a limit
    again = PiShockSettingsManager()
    assert again.get_shocker_names() == {"24325": "My collar", "24326": "x" * 40}
    again.set_shocker_name(24326, "")                      # empty: its id again
    assert again.get_shocker_names() == {"24325": "My collar"}


def test_friends_may_use_them_by_default_and_it_is_kept():
    s = PiShockSettingsManager()
    assert s.get_friends_may_use() is True
    s.set_friends_may_use(False)
    assert PiShockSettingsManager().get_friends_may_use() is False
    s.set_limit("friends_may_use", True)            # never through the limits
    assert s.get_friends_may_use() is False


def test_on_off_is_on_by_default_and_kept():
    s = PiShockSettingsManager()
    assert s.get_enabled() is True
    s.set_enabled(False)
    assert PiShockSettingsManager().get_enabled() is False
    s.set_limit("enabled", True)                    # never through the limits
    assert s.get_enabled() is False


def test_each_shocker_keeps_its_own_limits():
    # Blise's call (2026-10-28): max shock / vibrate / longest pulse per
    # shocker; one without its own takes the hub-wide ones
    s = PiShockSettingsManager()
    s.set_shocker_limit(24325, "max_intensity", 12)
    s.set_shocker_limit("24325", "max_pulse_ms", 99999)        # clamped
    s.set_shocker_limit(24325, "cooldown_s", 0.0)               # shared: not per shocker
    assert s.get_shocker_limits() == {"24325": {"max_intensity": 12, "max_pulse_ms": 15000}}
    assert s.shocker_limits_for(24325) == {"max_intensity": 12, "max_vibrate": 30,
                                           "max_pulse_ms": 15000}
    assert s.shocker_limits_for(24326) == {"max_intensity": 30, "max_vibrate": 30,
                                           "max_pulse_ms": 1000}
    assert PiShockSettingsManager().get_shocker_limits()["24325"]["max_intensity"] == 12


def test_arm_shocks_is_remembered():
    s = PiShockSettingsManager()
    assert s.get_armed() is False                     # a new install starts disarmed
    s.set_armed(True)
    assert PiShockSettingsManager().get_armed() is True


def test_an_older_rule_reads_its_one_shocker_as_a_list(tmp_path):
    with open(PiShockSettingsManager.FILE_PATH, "w", encoding="utf-8") as fh:
        json.dump({"triggers": [{"param": "A", "shocker": 12}, {"param": "B", "shocker": "all"},
                                {"param": "C", "shockers": [3, 3, "x", 4]}]}, fh)
    s = PiShockSettingsManager()
    assert [r["shockers"] for r in s.get_rules("triggers")] == [[12], "all", [3, 4]]


def test_touch_zones_start_with_an_example_that_stays_gone_once_deleted():
    s = PiShockSettingsManager()
    example = s.get_rules("zones")
    assert len(example) == 1 and example[0]["enabled"] is False
    assert [z["param"] for z in example[0]["zones"]] == ["Contact/Neck", "Contact/ThighL",
                                                         "Contact/ThighR"]
    s.delete_rule("zones", 0)
    assert PiShockSettingsManager().get_rules("zones") == []


def test_a_shocker_switched_off_is_remembered_and_junk_is_dropped():
    s = PiShockSettingsManager()
    assert s.get_shockers_off() == []                   # every shocker starts in use
    s.set_shocker_on(24326, False)
    s.set_shocker_on("24325", False)
    s.set_shocker_on(24325, True)
    assert s.get_shockers_off() == [24326]
    assert PiShockSettingsManager().get_shockers_off() == [24326]   # remembered
    path = PiShockSettingsManager.FILE_PATH
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    data["shockers_off"] = [24326, "x", -1, 24326, 7]
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh)
    assert PiShockSettingsManager().get_shockers_off() == [7, 24326]


def test_each_shockers_shock_vibrate_and_beep_are_remembered():
    s = PiShockSettingsManager()
    assert s.get_shocker_ops_off() == {}                 # all three on, every shocker
    s.set_shocker_op(24325, "shock", False)
    s.set_shocker_op("24325", "beep", False)
    s.set_shocker_op(24326, "vibrate", False)
    s.set_shocker_op(24326, "vibrate", True)             # back on: no entry left
    s.set_shocker_op(24325, "zap", False)                # not an op
    assert s.get_shocker_ops_off() == {"24325": ["shock", "beep"]}
    assert PiShockSettingsManager().get_shocker_ops_off() == {"24325": ["shock", "beep"]}
    path = PiShockSettingsManager.FILE_PATH
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    data["shocker_ops_off"] = {"24325": ["beep", "x", "shock"], "bad": ["shock"], "7": "shock"}
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh)
    assert PiShockSettingsManager().get_shocker_ops_off() == {"24325": ["shock", "beep"]}


def test_separate_limits_for_friends_start_off_and_as_a_copy_of_the_hubs():
    s = PiShockSettingsManager()
    assert s.get_separate_limits() is False
    s.set_limit("max_hold_s", 25.0)
    s.set_shocker_limit(24325, "max_intensity", 60)         # one shocker above the hub's 30
    s.set_separate_limits(True)                            # first time: a copy of now
    # the timing the hub's, each cap the highest any shocker has: nobody lowered
    assert s.get_friend_limits() == {"max_intensity": 60, "max_vibrate": 30,
                                     "max_pulse_ms": 1000, "cooldown_s": 0.5,
                                     "max_hold_s": 25.0, "hold_rest_s": 2.0}
    s.set_shocker_limit(24325, "max_intensity", 90)        # a copy: it doesn't follow
    assert s.get_friend_limits()["max_intensity"] == 60
    s.set_friend_limit("max_hold_s", 60.0)
    s.set_limit("max_hold_s", 5.0)                         # the hub's own moves on its own
    s.set_separate_limits(False)
    s.set_separate_limits(True)                            # back on: theirs are kept
    again = PiShockSettingsManager()
    assert again.get_separate_limits() is True and again.get_friend_limits()["max_hold_s"] == 60.0


def test_the_friends_set_is_clamped_and_takes_the_caps_and_the_timing():
    s = PiShockSettingsManager()
    s.set_separate_limits(True)
    s.set_friend_limit("max_hold_s", 1e9)
    s.set_friend_limit("cooldown_s", float("inf"))
    s.set_friend_limit("max_intensity", 1e9)
    s.set_friend_limit("max_pulse_ms", 1234.7)
    s.set_friend_limit("armed", True)                      # nothing but the limits
    lim = s.get_friend_limits()
    assert lim["max_hold_s"] == pishock_limits.RANGES["max_hold_s"][1]
    assert lim["cooldown_s"] == pishock_limits.RANGES["cooldown_s"][1]
    assert lim["max_intensity"] == pishock_limits.RANGES["max_intensity"][1]
    assert lim["max_pulse_ms"] == 1234 and isinstance(lim["max_pulse_ms"], int)
    assert set(lim) == set(pishock_limits.FRIEND_KEYS)
    assert s.get_armed() is False


def test_a_friends_set_from_before_the_caps_gets_them_when_switched_on():
    s = PiShockSettingsManager()
    s.settings["friend_limits"] = {"max_hold_s": 40.0}    # timing only, as on 2026-11-17
    s.settings["separate_limits"] = False
    s.set_limit("max_intensity", 45)
    s.set_separate_limits(True)
    stored = s.settings["friend_limits"]
    assert stored["max_hold_s"] == 40.0 and stored["max_intensity"] == 45
    assert set(stored) == set(pishock_limits.FRIEND_KEYS)
