"""suits_settings.json feeds the last gate before EMS reaches a person, so a
hand-edited file must never widen it: every value is cleaned on load and on
every set. Also: the defaults (OWO never connects by itself, its ceiling
starts at 60), and the zone routes."""

import json

import body_map
from settings.suits import OWO_ABSOLUTE_MAX, SuitsSettingsManager


def test_defaults(tmp_path):
    s = SuitsSettingsManager()
    snap = s.snapshot()
    assert snap["bhaptics"]["auto_connect"] is True
    assert snap["owo"]["auto_connect"] is False
    assert snap["owo"]["global_max"] == 60
    assert set(snap["bhaptics"]["devices"]) == set(body_map.NODE_COUNTS)
    assert set(snap["owo"]["muscles"]) == set(body_map.MUSCLES)
    assert snap["routes"] == []


def test_a_hand_edited_file_cannot_widen_anything():
    path = SuitsSettingsManager.FILE_PATH
    with open(path, "w", encoding="utf-8") as f:
        json.dump({
            "owo": {"global_max": 9999, "frequency": -4, "react_to": "everyone",
                    "muscles": {"Arm_L": {"max": 500}, "Tail": {"max": 100}}},
            "bhaptics": {"devices": {"VestFront": {"intensity": "loud"}}, "react_to": 3},
            "routes": [{"region": "Moon", "filters": ["TouchOthers", "Psychic"], "gain": 1e9},
                       "garbage"],
        }, f)
    s = SuitsSettingsManager()
    o = s.owo()
    assert o["global_max"] == OWO_ABSOLUTE_MAX
    assert o["frequency"] == 1
    assert o["react_to"] == body_map.REACT_BOTH
    assert o["muscles"]["Arm_L"]["max"] == OWO_ABSOLUTE_MAX
    assert "Tail" not in o["muscles"]
    b = s.bhaptics()
    assert b["devices"]["VestFront"]["intensity"] == 100
    assert b["react_to"] == body_map.REACT_BOTH
    r = s.routes()
    assert r[0]["region"] == "VestFront"
    assert r[0]["filters"] == ["TouchOthers"]
    assert r[0]["gain"] == 4.0
    assert len(r) == 2


def test_huge_or_infinite_numbers_fall_back_instead_of_breaking_the_load():
    """json reads a 400-digit number as an int no float holds and 1e999 as
    inf: both fall back to that value's default -- never to a ceiling. The
    big int used to raise OverflowError while loading, which set the whole
    file aside as .bak and lost every other suit setting and route."""
    inf, huge = float("inf"), int("9" * 400)
    path = SuitsSettingsManager.FILE_PATH
    with open(path, "w", encoding="utf-8") as f:
        json.dump({
            "owo": {"global_max": huge, "frequency": -huge,
                    "muscles": {"Arm_L": {"max": huge}, "Arm_R": {"max": inf}}},
            "bhaptics": {"devices": {"VestFront": {"intensity": huge}}},
            "routes": [{"gain": huge}, {"gain": -inf}],
        }, f)
    s = SuitsSettingsManager()
    o = s.owo()
    assert (o["global_max"], o["frequency"]) == (60, 50)
    assert o["muscles"]["Arm_L"]["max"] == o["muscles"]["Arm_R"]["max"] == 100
    assert s.bhaptics()["devices"]["VestFront"]["intensity"] == 100
    assert [r["gain"] for r in s.routes()] == [1.0, 1.0]


def test_setters_clean_and_save():
    s = SuitsSettingsManager()
    s.set_owo_option("global_max", 300)
    s.set_owo_option("host", "  192.168.1.9 ")
    s.set_owo_option("nonsense", 1)
    s.set_owo_muscle("Lumbar_R", max=-5, enabled=False)
    s.set_bhaptics_device("ForearmL", intensity=55.4, enabled=False)
    s.set_bhaptics_option("react_to", "others")
    again = SuitsSettingsManager()
    assert again.owo()["global_max"] == OWO_ABSOLUTE_MAX
    assert again.owo()["host"] == "192.168.1.9"
    assert again.owo()["muscles"]["Lumbar_R"] == {"enabled": False, "max": 0}
    assert again.bhaptics()["devices"]["ForearmL"] == {"enabled": False, "intensity": 55}
    assert again.bhaptics()["react_to"] == "others"
    assert "nonsense" not in again.owo()


def test_on_off_is_on_by_default_kept_and_only_set_on_its_own():
    """Home's On / Off: only the facade's stop / resume set it (they pause
    the engine with it), never the generic option setters."""
    s = SuitsSettingsManager()
    assert s.bhaptics()["enabled"] is True and s.owo()["enabled"] is True
    s.set_owo_option("enabled", False)
    s.set_bhaptics_option("enabled", False)
    assert s.bhaptics()["enabled"] is True and s.owo()["enabled"] is True
    s.set_owo_enabled(False)
    s.set_bhaptics_enabled(False)
    again = SuitsSettingsManager()
    assert again.bhaptics()["enabled"] is False and again.owo()["enabled"] is False


def test_routes_add_set_delete():
    s = SuitsSettingsManager()
    i = s.add_route()
    s.set_route(i, {"zone": "Mouth", "zone_type": "Orf", "filters": ["PenOthers"],
                    "region": "Abdominal_L", "gain": 0.5})
    assert s.routes()[i]["region"] == "Abdominal_L"
    s.set_route(9, {"zone": "x"})            # out of range: ignored
    s.delete_route(i)
    assert s.routes() == []


def test_you_have_starts_with_a_vest_and_keeps_only_known_parts():
    from settings.suits import _clean_bhaptics
    assert SuitsSettingsManager().bhaptics()["have"] == ["vest"]
    assert _clean_bhaptics({"have": []})["have"] == []
    assert _clean_bhaptics({"have": ["head", "tail", "vest", 3]})["have"] == ["vest", "head"]
    assert _clean_bhaptics({"have": "vest"})["have"] == ["vest"]


def test_a_part_that_connects_is_added_to_what_you_have():
    s = SuitsSettingsManager()
    assert s.add_bhaptics_have(["VestFront", "VestBack"]) == []
    assert s.add_bhaptics_have(["ForearmL", "Head", "Nonsense"]) == ["Sleeves", "Head"]
    assert SuitsSettingsManager().bhaptics()["have"] == ["vest", "arms", "head"]
    s.set_bhaptics_option("have", ["feet"])
    assert SuitsSettingsManager().bhaptics()["have"] == ["feet"]
