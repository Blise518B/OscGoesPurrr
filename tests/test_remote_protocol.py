"""The Friends link's messages: everything a friend sends is cleaned before
it is used, and nothing we send outgrows one datagram."""

import remote_protocol as proto


def test_nick_is_cleaned_and_cut():
    assert proto.clean_nick("  Blise   518  ") == "Blise 518"
    assert proto.clean_nick("a\x00b\nc") == "ab c"
    assert len(proto.clean_nick("x" * 100)) == proto.NICK_MAX
    assert proto.clean_nick(None) == ""


def test_decode_rejects_garbage():
    assert proto.decode(b"not json") is None
    assert proto.decode(b"[1, 2]") is None
    assert proto.decode(b'{"no": "type"}') is None
    assert proto.decode(b'\xff\xfe') is None
    assert proto.decode(proto.encode({"t": "ping"})) == {"t": "ping"}


def test_status_round_trip():
    msg = proto.make_status([("Lovense Hush", 1), ("Edge", 2)], {"Edge": 0.4},
                            0.8, False, False, True, True, ["Collar"], True, 40, 2000)
    st = proto.read_status(proto.decode(proto.encode(msg)))
    assert st["toys"] == [("Lovense Hush", 1), ("Edge", 2)]
    assert st["outputs"] == {"Lovense Hush": 0.0, "Edge": 0.4}
    assert st["strength"] == 0.8
    assert st["allow_toys"] and st["allow_shock"]
    assert st["shockers"] == ["Collar"] and st["armed"]
    assert (st["max_intensity"], st["max_pulse_ms"]) == (40, 2000)


def test_status_hides_shockers_from_a_friend_who_may_not_shock():
    msg = proto.make_status([], {}, 1.0, False, False, True, False, ["Collar"], True, 40, 2000)
    assert "shk" not in msg and "armed" not in msg and "lim" not in msg
    assert proto.read_status(msg)["shockers"] == []


def test_status_always_fits_one_datagram():
    toys = [("T" * 80 + str(i), 4) for i in range(40)]
    msg = proto.make_status(toys, {n: 0.5 for n, _ in toys}, 1.0, False, False,
                            True, True, ["S" * 80] * 10, False, 100, 15000)
    assert len(proto.encode(msg)) <= proto.MAX_DATAGRAM
    assert len(msg["toys"]) <= proto.MAX_TOYS
    assert len(msg["shk"]) <= proto.MAX_SHOCKERS


def test_status_values_are_clamped():
    st = proto.read_status({"t": "st", "toys": [["A", 1]], "out": {"A": 7}, "str": -3,
                            "lim": {"int": 999, "ms": -5}})
    assert st["outputs"]["A"] == 1.0
    assert st["strength"] == 0.0
    assert st["max_intensity"] == 100 and st["max_pulse_ms"] == 0


def test_cmd_round_trip_and_zero_levels_dropped():
    msg = proto.make_cmd({proto.ALL_TOYS: 0.3, "Edge": 0.9, "Hush": 0.0}, (17, 0.5))
    assert "Hush" not in msg["lvl"]
    levels, strength = proto.read_cmd(proto.decode(proto.encode(msg)))
    assert levels == {proto.ALL_TOYS: 0.3, "Edge": 0.9}
    assert strength == (17, 0.5)


def test_cmd_cleans_hostile_values():
    levels, strength = proto.read_cmd({"t": "cmd", "lvl": {"A": "nan", "B": 5, "C": -1},
                                       "str": ["x", 0.5]})
    assert levels == {"B": 1.0}
    assert strength is None


def test_drive_takes_the_higher_of_all_toys_and_the_toy():
    levels = {proto.ALL_TOYS: 0.3, "Edge": 0.9}
    assert proto.drive_for(levels, "Edge") == 0.9
    assert proto.drive_for(levels, "Hush") == 0.3
    assert proto.drive_for({}, "Hush") == 0.0


def test_shock_round_trip_and_bad_slots():
    msg = proto.make_shock("abc", [0, 2, 2, 9], 0.5, 0.25)
    assert msg["slots"] == [0, 2]
    assert proto.read_shock(msg) == {"id": "abc", "slots": [0, 2], "int": 0.5, "len": 0.25,
                                     "op": "shock", "warn": "", "wi": 0.0, "wms": 0}
    assert proto.read_shock({"t": "shk", "id": "x", "slots": [7], "int": 1, "len": 1}) is None
    assert proto.read_shock({"t": "shk", "slots": [0], "int": 1, "len": 1}) is None


def test_shock_values_land_inside_the_receivers_caps():
    assert proto.shock_values(0.0, 0.0, 40, 2000) == (1, proto.SHOCK_MIN_MS)
    assert proto.shock_values(1.0, 1.0, 40, 2000) == (40, 2000)
    level, ms = proto.shock_values(0.5, 0.5, 40, 2000)
    assert 1 <= level <= 40 and proto.SHOCK_MIN_MS <= ms <= 2000
    # A receiver with tiny caps never gets more than them.
    assert proto.shock_values(1.0, 1.0, 1, 50) == (1, proto.SHOCK_MIN_MS)



def test_cmd_carries_override_auto_modes_and_holds():
    msg = proto.make_cmd({"Edge": 0.5}, None, override={"Edge"},
                         patterns={"*": ("sine", 2.0, 0.1, 0.9), "Hush": ("bogus", 1, 0, 1)},
                         holds={1: ("vibrate", 0.4), 9: ("shock", 1.0), 0: ("zap", 1.0)})
    assert proto.drives(msg)
    over, pats, holds = proto.read_cmd_more(proto.decode(proto.encode(msg)))
    assert over == {"Edge"}
    assert pats == {"*": ("sine", 2.0, 0.1, 0.9)}
    assert holds == {1: ("vibrate", 0.4)}
    assert not proto.drives(proto.make_cmd({}, None, override={"Edge"}))
    assert proto.drives(proto.make_cmd({}, None, patterns={"*": ("saw", 1, 0, 1)}))


def test_shock_ops_warnings_and_stop():
    msg = proto.make_shock("a1", [0], 0.5, 0.5, op="vibrate", warn="vibrate",
                           warn_intensity=0.3, warn_ms=4200)
    got = proto.read_shock(proto.decode(proto.encode(msg)))
    assert (got["op"], got["warn"], got["wi"], got["wms"]) == ("vibrate", "vibrate", 0.3, 4200)
    long = proto.make_shock("a2", [0], 0.5, 0.5, warn="vibrate", warn_ms=60000)
    assert proto.read_shock(long)["wms"] == proto.WARN_MAX_MS
    assert proto.read_shock({**msg, "op": "zap"}) is None
    assert proto.read_shock({**msg, "warn": "zap"})["warn"] == ""
    stop = proto.read_stop(proto.make_stop("s1", [3, 1, 9]))
    assert stop == {"id": "s1", "slots": [1, 3]}
    assert proto.read_stop({"t": "stp", "id": "x", "slots": []}) is None


def test_status_tells_the_vibrate_cap_and_hold():
    st = proto.read_status(proto.make_status([], {}, 1.0, False, False, True, True,
                                             ["Collar"], True, 40, 2000, 80, 10.0))
    assert (st["max_vibrate"], st["max_hold_s"]) == (80, 10.0)
    old = proto.read_status(proto.make_status([], {}, 1.0, False, False, True, True,
                                              ["Collar"], True, 40, 2000))
    assert old["max_vibrate"] == 40


def test_a_cmd_never_outgrows_one_datagram():
    # Eight long toy names, each with a level, an override and an auto mode:
    # past one datagram the named toys give way, "all toys" stays.
    names = [f"Lovense Toy Number {i} With A Long Name"[:proto.TOY_NAME_MAX] for i in range(8)]
    levels = {proto.ALL_TOYS: 0.5, **{n: 0.4 for n in names}}
    patterns = {proto.ALL_TOYS: ("sine", 2.0, 0.1, 0.9), **{n: ("square", 1.0, 0.0, 1.0) for n in names}}
    msg = proto.make_cmd(levels, (5, 0.7), override=[proto.ALL_TOYS, *names], patterns=patterns,
                         holds={0: ("vibrate", 0.5)})
    assert len(proto.encode(msg)) <= proto.MAX_DATAGRAM
    assert msg["lvl"][proto.ALL_TOYS] == 0.5 and msg["pat"][proto.ALL_TOYS][0] == "sine"
    assert msg["hold"] and msg["str"] == [5, 0.7]


def test_ids_and_codes_are_hex():
    assert proto.valid_id("ab" * 32) and not proto.valid_id("AB" * 32)
    assert not proto.valid_id("ab" * 31) and not proto.valid_id("zz" * 32)
    assert proto.clean_id(" AB" * 32) == "ab" * 32
    assert proto.valid_code("0123456789abcdef") and not proto.valid_code("0123")


def test_toy_batteries_travel_as_whole_percent_for_listed_toys_only():
    msg = proto.make_status([("Lush", 1), ("Edge", 2)], {}, 1.0, False, False, True, False,
                            [], False, 0, 0,
                            batteries={"Lush": 0.824, "Edge": None, "Gone": 0.5})
    assert msg["bat"] == {"Lush": 82}
    st = proto.read_status(proto.decode(proto.encode(msg)))
    assert st["batteries"] == {"Lush": 82}
    st = proto.read_status({"t": "st", "toys": [["Lush", 1]], "bat": {"Lush": 400}})
    assert st["batteries"] == {"Lush": 100}
    assert proto.read_status({"t": "st", "toys": [["Lush", 1]]})["batteries"] == {}


def test_batteries_never_push_the_status_past_one_datagram():
    toys = [(f"Toy with a long name number {i:02d}", 2) for i in range(proto.MAX_TOYS)]
    msg = proto.make_status(toys, {n: 0.5 for n, _ in toys}, 1.0, False, False, True, True,
                            ["Collar"], True, 40, 2000,
                            batteries={n: 0.5 for n, _ in toys})
    assert len(proto.encode(msg)) <= proto.MAX_DATAGRAM
    assert set(msg.get("bat", {})) <= {n for n, _ in msg["toys"]}


# --- sync with others: syn, oth, pnl -----------------------------------------

def test_a_cmd_says_its_panel_version_only_while_it_syncs():
    assert proto.read_syn(proto.make_cmd({"*": 0.5}, None, syn=7)) == 7
    assert proto.read_syn(proto.make_cmd({"*": 0.5}, None)) is None
    for junk in (True, "x", None, [1]):
        assert proto.read_syn({"t": "cmd", "syn": junk}) is None


def test_the_shared_panel_goes_round_trip():
    msg = proto.make_panel(12, {"*": 0.4, "Edge": 0.9}, {"Edge"}, {"Edge": ("sine", 2.0, 0.1, 0.8)})
    assert msg["t"] == "pnl" and len(proto.encode(msg)) <= proto.MAX_DATAGRAM
    seq, levels, override, patterns = proto.read_panel(msg)
    assert seq == 12 and levels == {"*": 0.4, "Edge": 0.9} and override == {"Edge"}
    assert patterns["Edge"][0] == "sine"
    assert proto.read_panel({"t": "pnl"}) is None


def test_who_else_drives_is_names_cleaned_and_capped():
    msg = proto.make_others([f"  Friend {i}  " for i in range(12)] + [""])
    names = proto.read_others(msg)
    assert names[0] == "Friend 0" and len(names) == proto.MAX_OTHERS
    assert proto.read_others({"t": "oth", "n": "nope"}) == []


def test_each_shockers_own_caps_ride_the_status():
    st = proto.read_status(proto.make_status(
        [], {}, 1.0, False, False, True, True, ["Collar", "Thigh"], True, 40, 2000,
        max_vibrate=60, shocker_caps=[(40, 60, 2000), (10, 20, 500)]))
    assert st["shocker_caps"] == [(40, 60, 2000), (10, 20, 500)]
    assert proto.shocker_caps(st, 1) == (10, 20, 500)
    # a copy that sends none: every shocker has the hub-wide caps
    old = proto.read_status(proto.make_status(
        [], {}, 1.0, False, False, True, True, ["Collar"], True, 40, 2000, max_vibrate=60))
    assert old["shocker_caps"] == [] and proto.shocker_caps(old, 0) == (40, 60, 2000)
