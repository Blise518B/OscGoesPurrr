"""bhaptics_models builds the bytes the suit gets, so the layout is pinned
here: the Pro / Air 32-motor frame (one byte per motor, its own
characteristic), the older 40-slot vest frame (two slots per byte, even slot
high), the dot -> slot tables, the 0..100 -> 0..15 scaling, plain devices,
and which advertised names bind to which positions."""

import math

import bhaptics_models as m


def test_pack_vest_puts_the_even_slot_in_the_high_half():
    levels = [0] * 40
    levels[0] = 15
    levels[1] = 1
    levels[39] = 7
    frame = m.pack_vest(levels)
    assert len(frame) == 20
    assert frame[0] == 0xF1
    assert frame[19] == 0x07
    assert frame[1:19] == bytes(18)


def test_pack_vest_clamps_and_pads():
    assert m.pack_vest([99, -4]) == bytes([0xF0]) + bytes(19)


def test_slot_tables_cover_all_forty_slots_once():
    slots = list(m.VEST_FRONT_SLOTS) + list(m.VEST_BACK_SLOTS)
    assert sorted(slots) == list(range(40))


def test_vest_levels_follow_the_tables():
    front = [0] * 20
    back = [0] * 20
    front[0] = 100
    back[19] = 100
    levels = m.vest_levels({"VestFront": front, "VestBack": back})
    assert levels[m.VEST_FRONT_SLOTS[0]] == 15
    assert levels[m.VEST_BACK_SLOTS[19]] == 15
    assert sum(1 for v in levels if v) == 2


def test_levels_round_from_percent():
    assert m._to_level(100, 15) == 15
    assert m._to_level(50, 15) == 8      # 7.5 rounds up
    assert m._to_level(3, 15) == 0       # too faint for one vest step
    assert m._to_level(250, 15) == 15
    assert m._to_level(-5, 15) == 0
    assert m._to_level(math.nan, 15) == 0
    assert m._to_level("loud", 15) == 0


def test_bind_vests_serve_both_panels():
    for name, key in (("TactSuitPro", "pro"), ("TactSuitAirOnyx", "air"),
                      ("TactSuitAirAsh", "air"), ("TactSuitX40", "x40"),
                      ("TactSuitX16", "x16"), ("TactSuitSomething", "vest")):
        b = m.bind(name)
        assert b is not None and b.model.key == key, name
        assert b.positions == ("VestFront", "VestBack")
        assert b.model.vest


def test_bind_plain_devices_by_side():
    assert m.bind("Tactosy2_L").positions == ("ForearmL",)
    assert m.bind("Tactosy2_R").positions == ("ForearmR",)
    assert m.bind("TactosyH_R").positions == ("HandR",)
    assert m.bind("TactosyF_L").positions == ("FootL",)
    assert m.bind("Tactal_").positions == ("Head",)


def test_bind_refuses_strangers():
    assert m.bind(None) is None
    assert m.bind("") is None
    assert m.bind("OWO000000000000") is None
    assert m.bind("LVS-Lush") is None


def test_pro_and_air_take_the_grid_frame_on_their_own_characteristic():
    for name in ("TactSuitPro", "TactSuitAirOnyx", "TactSuitAirAsh"):
        model = m.bind(name).model
        assert model.grid, name
        assert model.motor_char == m.GRID_MOTOR_CHAR
    for name in ("TactSuitX40", "TactSuitX16", "Tactot", "Tactosy2_L"):
        model = m.bind(name).model
        assert not model.grid, name
        assert model.motor_char == m.MOTOR_CHAR


def test_grid_tables_reach_all_32_motors_and_nothing_past_them():
    used = set(m.GRID_FRONT_BYTES) | set(m.GRID_BACK_BYTES)
    assert used == set(range(32))
    assert not set(m.GRID_FRONT_BYTES) & set(m.GRID_BACK_BYTES)


def test_grid_layout_matches_the_players_groups():
    # four groups of eight: front cols 0-1, back cols 0-1, back cols 2-3,
    # front cols 2-3; each row by row, two a row
    assert m.GRID_FRONT_BYTES[0] == 0          # front, top row, column 0
    assert m.GRID_FRONT_BYTES[1] == 1
    assert m.GRID_FRONT_BYTES[2] == 24         # front, top row, column 2
    assert m.GRID_FRONT_BYTES[3] == 25
    assert m.GRID_FRONT_BYTES[4] == 2          # second row
    assert m.GRID_BACK_BYTES[0] == 8
    assert m.GRID_BACK_BYTES[3] == 17
    assert m.GRID_BACK_BYTES[19] == 23         # back, bottom row, column 3


def test_grid_folds_five_avatar_rows_onto_four_motor_rows():
    # rows 2 and 3 of the avatar share the third motor row; the rest are 1:1
    col0 = [m.GRID_FRONT_BYTES[r * 4] for r in range(5)]
    assert col0 == [0, 2, 4, 4, 6]


def test_encode_grid_vest():
    vest = m.bind("TactSuitPro")
    frame = m.encode(vest, {"VestFront": [100] + [0] * 19, "VestBack": [0] * 19 + [40]})
    assert len(frame) == 40
    assert frame[0] == 100
    assert frame[23] == 40
    assert sum(1 for b in frame if b) == 2
    # two dots on one motor keep the stronger; garbage reads as zero
    front = [0] * 20
    front[8], front[12] = 30, 70
    assert m.encode(vest, {"VestFront": front})[4] == 70
    assert m.encode(vest, {"VestFront": ["x", float("nan")] + [250] + [0] * 17})[:2] == bytes(2)
    assert m.encode(vest, {"VestFront": [0, 0, 250]})[24] == 100


def test_encode_vest_and_plain():
    vest = m.bind("TactSuitX40")
    frame = m.encode(vest, {"VestFront": [100] + [0] * 19})
    assert len(frame) == 20
    assert m.vest_levels({"VestFront": [100] + [0] * 19}).count(15) == 1

    arm = m.bind("Tactosy2_R")
    assert m.encode(arm, {"ForearmR": [0, 50, 100, 120, -1, 7]}) == bytes([0, 50, 100, 100, 0, 7])
    assert m.encode(arm, {}) == bytes(6)


def test_zero_frames():
    assert m.zero_frame(m.bind("TactSuitAirOnyx")) == bytes(40)
    assert m.zero_frame(m.bind("TactSuitX40")) == bytes(20)
    assert m.zero_frame(m.bind("TactosyH_L")) == bytes(3)
