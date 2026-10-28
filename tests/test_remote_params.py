"""The avatar board's messages (remote_params.py): every datagram fits, a
board comes back as it went, junk is dropped, and values keep their
parameter's type."""

import param_board as pb
import remote_params as rp
import remote_protocol as proto


def board(n_controls=3):
    preset = pb.normalize_preset({
        "categories": [{"id": "c1", "name": "Outfit", "color": "pink", "locked": True}],
        "controls": [{"id": f"k{i}", "param": f"Param{i}", "ptype": "Float", "kind": "slider",
                      "cat": "c1", "min": 0, "max": 1} for i in range(n_controls)],
    })
    preset["controls"].append({"id": "t", "param": "Outfit", "ptype": "Int", "kind": "toggle",
                               "label": "Outfit 2", "cat": "c1", "on": 2, "off": 0})
    return preset


def test_a_board_comes_back_as_it_went():
    msg = rp.with_version(rp.public_board(board(), "Base V7", {}, yolo=False))
    got = rp.read_board(proto.decode(proto.encode(msg)))
    assert got["ver"] == msg["b"] and got["name"] == "Base V7"
    assert got["categories"] == [{"id": "c1", "name": "Outfit", "color": "pink", "locked": True}]
    toggle = pb.find_control(got, "t")
    assert (toggle["on"], toggle["off"]) == (2, 0)
    assert got["keys"] == ["Param0", "Param1", "Param2", "Outfit"] and got["all"] is None


def test_the_version_follows_the_board():
    a = rp.with_version(rp.public_board(board(), "A", {}, False))["b"]
    assert rp.with_version(rp.public_board(board(), "A", {}, False))["b"] == a
    assert rp.with_version(rp.public_board(board(), "B", {}, False))["b"] != a
    assert rp.with_version(rp.public_board(board(), "A", {"X": "Bool"}, True))["b"] != a


def test_yolo_lists_every_settable_parameter_after_the_board():
    types = {"Param0": "Float", "Hue": "Float", "Viseme": "Int", "OGB/Orf/x/PenSelf": "Float"}
    msg = rp.public_board(board(1), "A", types, yolo=True)
    assert msg["all"] == [["Hue", "Float"], ["Param0", "Float"]]
    assert msg["keys"] == ["Param0", "Outfit", "Hue"] and msg["nb"] == 2


def test_junk_controls_and_categories_are_dropped():
    msg = rp.with_version(rp.public_board(board(), "A", {}, False))
    msg["ctl"].append({"id": "x", "param": "P", "ptype": "Bool", "kind": "slider", "cat": "c1"})
    msg["ctl"].append({"id": "y", "param": "P", "ptype": "Bool", "kind": "toggle", "cat": "nope"})
    msg["ctl"].append("junk")
    msg["cats"].append({"name": "no id"})
    got = rp.read_board(msg)
    assert {c["id"] for c in got["controls"]} == {"k0", "k1", "k2", "t"}
    assert len(got["categories"]) == 1
    assert rp.read_board({"t": "pbd"}) is None


def test_values_fit_a_datagram_and_keep_their_types():
    many = board(300)
    msg = rp.with_version(rp.public_board(many, "A", {}, False))
    got = rp.read_board(msg)
    values = [0.123456] * 300 + [2]
    chunks = rp.make_values(got["ver"], 7, values)
    assert len(chunks) > 1
    assert all(len(proto.encode(c)) <= proto.MAX_DATAGRAM for c in chunks)
    out = {}
    for c in chunks:
        out.update(rp.read_values(proto.decode(proto.encode(c)), got))
    assert out["Param0"] == 0.12 and out["Param299"] == 0.12      # two decimals
    assert out["Outfit"] == 2 and isinstance(out["Outfit"], int)
    assert rp.read_values(dict(chunks[0], b="other"), got) == {}   # another version


def test_bools_travel_as_numbers_and_come_back_as_bools():
    preset = pb.normalize_preset({"categories": [{"id": "c", "name": "C"}], "controls": [
        {"id": "h", "param": "Hoodie", "ptype": "Bool", "kind": "toggle", "cat": "c"}]})
    got = rp.read_board(rp.with_version(rp.public_board(preset, "A", {}, False)))
    [chunk] = rp.make_values(got["ver"], 1, [True])
    assert chunk["x"] == [1]
    assert rp.read_values(chunk, got) == {"Hoodie": True}
    [chunk] = rp.make_values(got["ver"], 1, [None])
    assert rp.read_values(chunk, got) == {"Hoodie": None}


def test_sets_and_holds():
    assert rp.read_set(rp.make_set(5, True, control="k1")) == (5, "k1", "", 1.0)
    assert rp.read_set(rp.make_set(6, 0.5, param="Hue")) == (6, "", "Hue", 0.5)
    assert rp.read_set({"t": "pst", "id": 1, "v": 1}) is None              # neither
    assert rp.read_set({"t": "pst", "id": 1, "v": 1, "c": "a", "p": "b"}) is None   # both
    assert rp.read_set({"t": "pst", "id": "x", "v": 1, "c": "a"}) is None
    assert rp.read_set({"t": "pst", "id": 1, "v": "nan", "c": "a"}) is None
    assert rp.read_holds(rp.make_holds({"b", "a"})) == ["a", "b"]
    assert rp.read_holds({"t": "ph", "h": ["a", 3]}) == ["a"]


def test_watch_and_status_marks():
    assert rp.read_watch(rp.make_watch("abc", True)) == {"have": "abc", "yolo": True}
    assert rp.read_watch(rp.WATCH_OFF) is None
    assert rp.read_prm(rp.make_prm("v1", True, False)) == {"ver": "v1", "yolo": True, "stop": False,
                                                     "avatar": ""}
    assert rp.read_prm(None) is None
    st = proto.make_status([], {}, 1.0, False, False, True, True, [], False, 0, 0,
                           prm=rp.make_prm("v1", False, True))
    assert len(proto.encode(st)) <= proto.MAX_DATAGRAM
    assert rp.read_prm(proto.read_status(st)["prm"])["stop"] is True
    assert proto.read_status(proto.make_status([], {}, 1.0, False, False, True, True, [],
                                               False, 0, 0))["prm"] is None



def test_the_worn_avatar_rides_the_status_and_the_board():
    key = rp.avatar_key("avtr_0a202672-a05f-4198-8267-fe6dd0e4aa75")
    assert len(key) == 8 and key == rp.avatar_key("avtr_0a202672-a05f-4198-8267-fe6dd0e4aa75")
    assert rp.read_prm(rp.make_prm("v1", False, False, key))["avatar"] == key
    assert rp.read_prm(rp.make_prm("v1", False, False))["avatar"] == ""      # an older OGP
    board = rp.read_board(rp.with_version(rp.public_board(None, "Base", {}, False, key)))
    assert board["avatar"] == key
    assert rp.make_watch("v1", False, 7)["r"] == 7 and "r" not in rp.make_watch("v1", False)
