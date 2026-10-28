"""The Avatar Remote page's board model (param_board.py) and its file
(settings/param_boards.py) -- VRC Parameter Relay's logic_test and the
board half of its int_toggle_test, against OGP's port."""

import json

import param_board as pb
from settings.param_boards import SCRATCH_KEEP, ParamBoardsSettingsManager

AVATAR = "avtr_3f9a61c2-7b4e-4d2a-9c81-5e2d0b7a4f16"
OTHER = "avtr_8c47d05e-2f1b-4a96-b3e0-7d61c94a2e08"
TYPES = {"Hoodie": "Bool", "TailWag": "Bool", "GlowToggle": "Bool",
         "Brightness": "Float", "OutfitIndex": "Int"}


def worn(types=None):
    store = ParamBoardsSettingsManager()
    book = pb.BoardBook(store)
    book.avatar_changed(AVATAR)
    book.sync_params(dict(TYPES if types is None else types))
    return book, store


def test_board_categories_controls_and_locks():
    book, _ = worn()
    cats = book.board["categories"]
    assert len(cats) == 4                                         # a 2x2 grid
    assert [c["color"] for c in cats] == ["red", "green", "amber", "blue"]

    hoodie = book.add_control("Hoodie", "toggle", "Hoodie")
    bright = book.add_control("Brightness", "slider", "Brightness", 0, 1)
    glow = book.add_control("GlowToggle", "toggle", "Glow", category=cats[1]["id"])
    assert hoodie["cat"] == cats[0]["id"]                         # first category by default
    assert glow["cat"] == cats[1]["id"]

    assert book.rename_category(cats[0]["id"], "Toggles")
    assert not book.rename_category(cats[0]["id"], "Toggles")     # unedited: no save
    nsfw = book.add_category("NSFW")
    assert len(book.board["categories"]) == 5
    assert nsfw["color"] == "cyan"                    # the first colour not on the board

    assert book.move_control(hoodie["id"], nsfw["id"], 0)
    assert pb.find_control(book.board, hoodie["id"])["cat"] == nsfw["id"]
    assert book.move_control(bright["id"], cats[0]["id"], 0)

    assert book.set_category_locked(nsfw["id"], True)
    control, locked = book.live_control(hoodie["id"])
    assert control is hoodie and locked
    assert book.set_category_locked(nsfw["id"], False)
    assert book.live_control(hoodie["id"])[1] is False

    assert book.set_category_color(nsfw["id"], "red")
    assert not book.set_category_color(nsfw["id"], "hotpink")
    assert nsfw["color"] == "red"


def test_inverted_toggle_sends_the_flipped_value():
    book, _ = worn()
    inv = book.add_control("TailWag", "toggle", "NoWag", invert=True)
    assert inv["invert"] is True
    assert pb.send_value(inv, True) is False          # shown ON sends the parameter OFF
    assert pb.shows_on(inv, False)
    assert book.update_control(inv["id"], invert=False)
    assert pb.send_value(inv, True) is True


def test_slider_and_stepper_values_stay_in_range():
    book, _ = worn()
    bright = book.add_control("Brightness", "slider", vmin=0.2, vmax=0.8)
    assert pb.send_value(bright, 5) == 0.8
    assert pb.send_value(bright, -5) == 0.2
    assert pb.send_value(bright, "nope") is None
    assert pb.send_value(bright, float("nan")) is None
    step = book.add_control("OutfitIndex", "int", vmin=0, vmax=300)
    assert pb.send_value(step, 299.6) == 255                     # VRChat's Int range
    assert pb.send_value(step, 2.4) == 2


def test_persisted_and_reloaded():
    book, store = worn()
    hoodie = book.add_control("Hoodie", "toggle")
    nsfw = book.add_category("NSFW")
    book.move_control(hoodie["id"], nsfw["id"])
    book.rename_avatar("My Cool Avatar")
    again = ParamBoardsSettingsManager()                          # fresh from disk
    profile = again.load(AVATAR)
    preset = pb.active_preset(profile)
    assert len(preset["categories"]) == 5
    assert pb.find_control(preset, hoodie["id"])["cat"] == nsfw["id"]
    assert profile["name"] == "My Cool Avatar"
    assert profile["params"] == TYPES                             # for offline editing


def test_default_kinds_and_drop_index():
    assert pb.default_kind("Bool") == "toggle"
    assert pb.default_kind("Int") == "int"
    assert pb.default_kind("Float") == "slider"
    book, _ = worn()
    cat = book.board["categories"][0]["id"]
    a1 = book.add_control("Hoodie", "toggle", category=cat)
    a2 = book.add_control("GlowToggle", "toggle", category=cat, index=0)
    order = [c["id"] for c in book.board["controls"] if c["cat"] == cat]
    assert order.index(a2["id"]) < order.index(a1["id"])


def test_move_and_remove_categories():
    book, _ = worn()
    ids = [c["id"] for c in book.board["categories"]]
    assert book.move_category(ids[-1], ids[0])
    assert book.board["categories"][0]["id"] == ids[-1]
    assert not book.move_category(ids[0], ids[0])
    hoodie = book.add_control("Hoodie", "toggle", category=ids[2])
    assert book.remove_category(ids[2])
    assert pb.find_control(book.board, hoodie["id"])["cat"] == book.board["categories"][0]["id"]
    while len(book.board["categories"]) > 1:
        assert book.remove_category(book.board["categories"][-1]["id"])
    assert not book.remove_category(book.board["categories"][0]["id"])   # one always stays


def test_old_single_board_file_migrates():
    profile = pb.normalize_profile({"name": "Old", "controls": [
        {"id": "x1", "param": "P", "ptype": "Bool", "kind": "toggle", "label": "P"}]}, "avtr_bare")
    assert len(profile["presets"]) == 1
    preset = profile["presets"][0]
    assert len(preset["categories"]) == 4
    assert preset["controls"][0]["cat"] == preset["categories"][0]["id"]
    assert "controls" not in profile and "categories" not in profile


def test_presets():
    book, _ = worn()
    base = book.board["id"]
    book.add_control("Hoodie", "toggle")
    stream = book.add_preset("Stream")
    assert book.board["id"] == stream["id"] and book.board["controls"] == []
    assert book.rename_preset(stream["id"], "Streaming")
    assert book.switch_preset(base) and book.board["id"] == base
    cat0 = book.board["categories"][0]
    n = sum(1 for c in book.board["controls"] if c["cat"] == cat0["id"])
    assert book.copy_category_to_preset(cat0["id"], stream["id"])
    target = next(p for p in book.profile["presets"] if p["id"] == stream["id"])
    copied = target["categories"][-1]
    assert copied["name"] == cat0["name"] and copied["id"] != cat0["id"]
    copies = [c for c in target["controls"] if c["cat"] == copied["id"]]
    assert len(copies) == n
    assert all(c["id"] not in {x["id"] for x in book.board["controls"]} for c in copies)
    assert not book.copy_category_to_preset(cat0["id"], base)     # not into itself
    assert book.remove_preset(stream["id"])
    assert not book.remove_preset(book.board["id"])               # one always stays


def test_offline_avatars_and_the_worn_board():
    book, store = worn()
    hoodie = book.add_control("Hoodie", "toggle")
    book.rename_avatar("My Cool Avatar")
    entries = {e["avatar_id"]: e for e in book.list_avatars()}
    assert entries[AVATAR]["named"]
    assert book.is_live
    store.save(pb.normalize_profile({"name": "Other Ava"}, OTHER))
    assert book.open_avatar(OTHER)
    assert book.avatar_id == OTHER and not book.is_live
    added = book.add_control("Whatever", "toggle", "W")
    assert added is not None                                      # edited offline
    # friends keep seeing the worn avatar's board, not the open one
    assert pb.find_control(book.live_board(), hoodie["id"]) is not None
    assert book.live_control(added["id"]) == (None, False)
    assert book.live_control(hoodie["id"])[0]["id"] == hoodie["id"]
    assert book.open_avatar(AVATAR) and book.is_live
    assert book.live_board() is book.board


def test_edits_on_the_worn_board_while_another_is_open_are_one_copy():
    book, store = worn()
    book.add_control("Hoodie", "toggle")
    store.save(pb.normalize_profile({"name": "Other Ava"}, OTHER))
    book.open_avatar(OTHER)
    live = book.live_board()
    book.open_avatar(AVATAR)
    assert book.board is live


def test_int_toggles_number_themselves_and_switch_each_other_off():
    book, _ = worn({"Outfit": "Int", "Emote": "Int", "Gloves": "Int", "Brightness": "Float"})
    t1 = book.add_control("Outfit", "toggle", "Outfit 1")
    t2 = book.add_control("Outfit", "toggle", "Outfit 2")
    t3 = book.add_control("Outfit", "toggle", "Outfit 3")
    assert [t1["on"], t2["on"], t3["on"]] == [1, 2, 3]
    assert t1["ptype"] == "Int" and t1["off"] == 0
    assert pb.send_value(t2, True) == 2 and pb.send_value(t2, False) == 0
    assert pb.shows_on(t2, 2) and not pb.shows_on(t1, 2)
    wave = book.add_control("Emote", "button", "Wave", on=3)
    assert pb.send_value(wave, True) == 3 and pb.send_value(wave, False) == 0
    big = book.add_control("Gloves", "toggle", on=999, off=-5)
    assert (big["on"], big["off"]) == (255, 0)
    misfit = book.add_control("Brightness", "toggle")
    assert misfit["kind"] == "slider"                 # a kind that doesn't fit falls back
    assert book.update_control(t1["id"], kind="toggle", on=7, off=1)
    assert (t1["on"], t1["off"]) == (7, 1)


def test_bool_toggles_follow_an_avatar_whose_params_became_ints():
    book, _ = worn({"Hat": "Bool", "Gloves": "Bool"})
    hat = book.add_control("Hat", "toggle")
    gloves = book.add_control("Gloves", "toggle", invert=True)
    changed, retyped = book.sync_params({"Hat": "Int", "Gloves": "Int"})
    assert changed and retyped
    assert hat["ptype"] == "Int" and (hat["on"], hat["off"]) == (1, 0)
    assert gloves["ptype"] == "Int" and (gloves["on"], gloves["off"]) == (0, 1)
    assert "invert" not in gloves
    assert book.sync_params({"Hat": "Int", "Gloves": "Int"}) == (False, False)  # no loop
    assert pb.send_value(hat, True) == 1


def test_avatar_change_and_gone():
    book, _ = worn()
    assert not book.avatar_changed(AVATAR)                        # the same one again
    assert book.avatar_changed(OTHER)
    assert book.avatar_id == OTHER and book.is_live and book.types == {}
    book.avatar_gone()
    assert book.live_avatar_id is None and book.live_board() is None
    assert book.avatar_id == OTHER                                # the page stays


def test_values_for_yolo_stay_in_vrchats_ranges():
    assert pb.any_value("Float", 3) == 1.0
    assert pb.any_value("Float", -3) == -1.0
    assert pb.any_value("Int", 300) == 255
    assert pb.any_value("Bool", 1) is True
    assert pb.any_value("Float", "x") is None
    assert pb.any_value("Vector", 1) is None


def test_live_value_types():
    assert pb.ptype_of(True) == "Bool"
    assert pb.ptype_of(3) == "Int"
    assert pb.ptype_of(0.5) == "Float"
    assert pb.ptype_of("x") is None


def test_relay_boards_import_with_their_orange_as_amber():
    raw = {"avatar_id": AVATAR, "name": "Base V7", "params": {"Hoodie": "Bool"},
           "presets": [{"id": "p1", "name": "Default",
                        "categories": [{"id": "c1", "name": "Locomotion", "color": "yellow",
                                        "locked": True}],
                        "controls": [{"id": "k1", "param": "Hoodie", "ptype": "Bool",
                                      "kind": "toggle", "label": "Hoodie", "cat": "c1"}]}],
           "active_preset": "p1"}
    profile = pb.relay_profile(raw)
    cat = profile["presets"][0]["categories"][0]
    assert cat["color"] == "amber" and cat["locked"]
    assert raw["presets"][0]["categories"][0]["color"] == "yellow"   # the source untouched
    assert pb.relay_profile({"name": "no id"}) is None
    store = ParamBoardsSettingsManager()
    assert store.import_profiles([profile]) == (1, 0, 0)
    assert store.import_profiles([pb.relay_profile(raw)]) == (0, 0, 1)       # kept
    assert store.import_profiles([pb.relay_profile(raw)], replace=True) == (0, 1, 0)


def test_only_recent_scratch_avatars_are_kept(tmp_path):
    store = ParamBoardsSettingsManager()
    store.save(dict(pb.normalize_profile({"name": "Mine"}, "avtr_named"), seen=0))
    for i in range(SCRATCH_KEEP + 5):
        p = pb.normalize_profile({"params": {"A": "Bool"}}, f"avtr_{i:08x}")
        store.save(p)
    avatars = store.settings["avatars"]
    assert "avtr_named" in avatars
    assert sum(1 for aid in avatars if aid.startswith("avtr_0")) == SCRATCH_KEEP


def test_a_damaged_board_file_is_cleaned_on_load():
    path = ParamBoardsSettingsManager.FILE_PATH
    path.write_text(json.dumps({"avatars": {AVATAR: {"presets": [{"controls": [
        {"param": "X", "kind": "nonsense"}, "junk", {"kind": "toggle"}]}]}, "": {}},
        "yolo": "yes"}), "utf-8")
    store = ParamBoardsSettingsManager()
    profile = store.load(AVATAR)
    controls = profile["presets"][0]["controls"]
    assert len(controls) == 1 and controls[0]["kind"] == "slider"
    assert store.get_yolo() is True
    assert list(store.settings["avatars"]) == [AVATAR]


def test_an_avatar_you_never_named_wears_vrchats_name():
    """VRChat's name for it (from its OSC files) until you give it one --
    and it still counts as never named, so the menu and the pruning of
    worn-only avatars work as before."""
    book, store = worn()
    short = pb.short_avatar_name(AVATAR)
    assert book.avatar_name == short
    assert book.set_vrchat_name("  Moth   Girl ") is True
    assert book.avatar_name == "Moth Girl"
    assert book.set_vrchat_name("Moth Girl") is False         # nothing new
    assert book.profile["name"] == short
    entry = {e["avatar_id"]: e for e in store.list_profiles()}[AVATAR]
    assert entry == {"avatar_id": AVATAR, "name": "Moth Girl", "named": False}
    # leaving the field showing VRChat's name as it is renames nothing
    assert book.rename_avatar("Moth Girl") is False
    assert book.rename_avatar("Mine") is True and book.avatar_name == "Mine"
    # clearing your name falls back to VRChat's again
    assert book.rename_avatar("") is True and book.avatar_name == "Moth Girl"
    # kept with the avatar, for while VRChat is closed
    again = ParamBoardsSettingsManager()
    assert pb.display_name(again.load(AVATAR)) == "Moth Girl"
