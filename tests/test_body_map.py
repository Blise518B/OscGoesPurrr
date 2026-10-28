"""body_map is the one body both suits read, so its rules are pinned here:
every input schema lands on the right node, self / others can be told apart,
the suits share contacts both ways (and can be told not to), muscles take the
strongest node in their patch, zone routes land on both suits, and garbage
reads as nothing."""

import math

import body_map as bm


def frame_value(frame, pos, i):
    return frame[pos][i]


def test_official_package_keys_land_on_their_node():
    r = bm.read_body({"bOSC/v2/VestFront/3/others": True,
                      "bOSC/v2/VestBack/19/self": True,
                      "bOSC/v2m/ForearmL/5/others": True})
    assert r.others_touch["VestFront"][3] == 1.0
    assert r.self_touch["VestBack"][19] == 1.0
    assert r.others_touch["ForearmL"][5] == 1.0
    assert sum(r.others_touch["VestFront"]) == 1.0


def test_legacy_schemas_count_as_any_touch():
    r = bm.read_body({"bHaptics_Vest_Front_1_bool": True,
                      "bHaptics_Arm_Right_6_bool": 1,
                      "bHaptics_Head_2_bool": 0.2,            # truthy only above 0.5
                      "bOSC_v1_VestBack_20": 0.4})
    assert r.any_touch["VestFront"][0] == 1.0
    assert r.any_touch["ForearmR"][5] == 1.0
    assert r.any_touch["Head"][1] == 0.0
    assert math.isclose(r.any_touch["VestBack"][19], 0.4)


def test_react_to_filters_self_and_others_but_never_legacy():
    r = bm.read_body({"bOSC/v2/VestFront/0/self": True,
                      "bOSC/v2/VestFront/1/others": True,
                      "bHaptics_Vest_Front_3_bool": True})
    both = bm.bhaptics_frame(r, bm.REACT_BOTH)
    others = bm.bhaptics_frame(r, bm.REACT_OTHERS)
    mine = bm.bhaptics_frame(r, bm.REACT_SELF)
    assert both["VestFront"][:3] == (1.0, 1.0, 1.0)
    assert others["VestFront"][:3] == (0.0, 1.0, 1.0)
    assert mine["VestFront"][:3] == (1.0, 0.0, 1.0)


def test_owo_contacts_spread_onto_the_bhaptics_suit():
    r = bm.read_body({"owo_suit_Pectoral_L": True})
    region_pos, cells = bm.OWO_REGIONS["Pectoral_L"]
    shared = bm.bhaptics_frame(r, follow_owo=True)
    alone = bm.bhaptics_frame(r, follow_owo=False)
    assert all(shared[region_pos][i] == 1.0 for i in cells)
    assert sum(shared[region_pos]) == len(cells)
    assert sum(alone[region_pos]) == 0.0


def test_bhaptics_contacts_drive_the_matching_owo_muscle():
    pos, cells = bm.OWO_REGIONS["Lumbar_R"]
    idx = cells[-1]
    r = bm.read_body({f"bOSC/v2/{pos}/{idx}/others": True})
    shared = bm.owo_levels(r, follow_bhaptics=True)
    alone = bm.owo_levels(r, follow_bhaptics=False)
    assert shared["Lumbar_R"] == 1.0
    assert sum(shared.values()) == 1.0
    assert sum(alone.values()) == 0.0


def test_owo_levels_respect_react_to_for_bhaptics_contacts():
    pos, cells = bm.OWO_REGIONS["Arm_L"]
    r = bm.read_body({f"bOSC/v2/{pos}/{cells[0]}/self": True})
    assert bm.owo_levels(r, bm.REACT_OTHERS)["Arm_L"] == 0.0
    assert bm.owo_levels(r, bm.REACT_SELF)["Arm_L"] == 1.0


def test_owo_package_values_are_kept_as_floats():
    r = bm.read_body({"owo_suit_Abdominal_R": 0.35, "owo_suit_Dorsal_L": False})
    levels = bm.owo_levels(r)
    assert math.isclose(levels["Abdominal_R"], 0.35)
    assert levels["Dorsal_L"] == 0.0
    assert set(levels) == set(bm.MUSCLES)


def test_a_muscle_takes_its_strongest_node():
    frame = bm.empty_frame()
    pos, cells = bm.OWO_REGIONS["Pectoral_R"]
    vals = list(frame[pos])
    vals[cells[0]] = 0.2
    vals[cells[1]] = 0.7
    frame[pos] = tuple(vals)
    assert math.isclose(bm.owo_muscles(frame)["Pectoral_R"], 0.7)
    assert bm.owo_muscles(frame)["Pectoral_L"] == 0.0


def test_muscle_patches_tile_the_vest_without_overlap():
    for panel in ("VestFront", "VestBack"):
        cells = [c for (pos, cs) in bm.OWO_REGIONS.values() if pos == panel for c in cs]
        assert sorted(cells) == list(range(20)), panel


def test_zone_routes_land_on_both_suits():
    params = {"OGB/Orf/Mouth/TouchOthers": 0.8}
    routes = [{"enabled": True, "zone": "Mouth", "zone_type": "Orf",
               "filters": ["TouchOthers"], "region": "Abdominal_L", "gain": 1.0}]
    r = bm.read_body(params, routes)
    pos, cells = bm.OWO_REGIONS["Abdominal_L"]
    frame = bm.bhaptics_frame(r, follow_owo=False)
    assert all(math.isclose(frame[pos][i], 0.8) for i in cells)
    assert math.isclose(bm.owo_levels(r, follow_bhaptics=False)["Abdominal_L"], 0.8)


def test_zone_route_gain_whole_device_and_disabled():
    params = {"OGB/Orf/Hips/PenOthers": 0.5, "OGB/Orf/Hips/PenOthersClose": True}
    routes = [
        {"enabled": True, "zone": "Hips", "filters": ["PenOthers"], "region": "VestBack", "gain": 1.5},
        {"enabled": False, "zone": "Hips", "filters": ["PenOthers"], "region": "Head"},
        {"enabled": True, "zone": "Hips", "filters": ["PenOthers"], "region": "Tail"},
    ]
    r = bm.read_body(params, routes)
    assert all(math.isclose(v, 0.75) for v in r.routes["VestBack"])
    assert sum(r.routes["Head"]) == 0.0


def test_a_synthetic_source_can_drive_a_route():
    sources = {"Grind": {"name": "Grind", "zone_type": "Orf", "enabled": True,
                         "proximity": ["Contact/Rub"], "max_value": 1.0}}
    routes = [{"enabled": True, "zone": "Grind", "region": "ForearmR"}]
    r = bm.read_body({"Contact/Rub": 0.6}, routes, sources)
    assert all(math.isclose(v, 0.6) for v in r.routes["ForearmR"])


def test_garbage_reads_as_nothing():
    r = bm.read_body({"bOSC/v2/VestFront/0/others": float("nan"),
                      "bOSC/v2/VestFront/1/others": "yes",
                      "bOSC/v2/VestFront/2/others": -1,
                      "bOSC/v2/VestFront/3/others": 7.0,
                      "owo_suit_Arm_R": None,
                      "bOSC/v2/VestFront/99/others": True,
                      "unrelated": True},
                     routes=[None, "x", {"zone": "", "region": "Head"}])
    assert r.others_touch["VestFront"][:4] == (0.0, 0.0, 0.0, 1.0)
    assert not any(r.owo.values())


def test_bhaptics_dots_scale_and_disable():
    frame = bm.empty_frame()
    frame["VestFront"] = (1.0, 0.5) + (0.0,) * 18
    devices = {"VestFront": {"enabled": True, "intensity": 80},
               "VestBack": {"enabled": False, "intensity": 100}}
    dots = bm.bhaptics_dots(frame, devices, 0.5)
    assert dots["VestFront"][:2] == [40, 20]
    assert dots["VestBack"] == [0] * 20
    assert dots["Head"] == [0] * 6                   # missing config: on at 100
    assert bm.bhaptics_dots(frame, devices, 0.0)["VestFront"] == [0] * 20
    assert bm.bhaptics_dots(frame, devices, float("nan"))["VestFront"] == [0] * 20
    assert len(dots) == len(bm.POSITIONS)


def test_detection():
    params = {"bOSC/v2/ForearmL/0/self": False, "bHaptics_Head_1_bool": False,
              "owo_suit_Arm_L": 0.0, "Other": 1}
    assert bm.detected_positions(params) == {"ForearmL", "Head"}
    assert bm.detected_owo(params) == {"Arm_L"}


def test_names_and_layouts():
    assert bm.grid_layout("VestFront") == (4, 5)
    assert bm.grid_layout("ForearmR") == (2, 3)
    assert bm.display_name("VestBack") == "Vest back"
    assert bm.display_name("Pectoral_L") == "Left chest"
    assert set(bm.REGIONS) == set(bm.NODE_COUNTS) | set(bm.MUSCLES)
    assert len(bm.MUSCLES) == 10


def test_every_position_is_in_exactly_one_part_group():
    grouped = [p for _k, _n, positions in bm.PART_GROUPS for p in positions]
    assert sorted(grouped) == sorted(bm.NODE_COUNTS)
    assert bm.group_of("ForearmL") == "arms"
    assert bm.positions_of(["vest", "head"]) == ("Head", "VestFront", "VestBack")
    assert bm.positions_of([]) == ()
