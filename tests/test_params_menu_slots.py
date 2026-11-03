"""The avatar menu's Avatar Remote slots (Blise's ask, 2026-10-29): seven
Toggles and seven Radials in your avatar's menu, each a slot a control --
or a whole category -- takes on the Avatar Remote page. The board keeps
them per preset; the menu drives the worn board straight from the OSC
thread; the menu follows the board, OGP first, without fighting your hand
or VRChat's echo; and the page's circle and radial picker set them."""

import time

import pytest
from PySide6.QtCore import QPointF

import param_board as pb
from test_param_board import worn
from test_params_facade import build, pair
from test_params_page import page, pump, qapp  # noqa: F401 (fixture)


# --- the board -----------------------------------------------------------------

def test_a_slot_holds_one_thing_and_a_thing_can_take_several():
    book, store = worn()
    hoodie = book.add_control("Hoodie", "toggle")
    glow = book.add_control("GlowToggle", "toggle")
    bright = book.add_control("Brightness", "slider")
    cat = book.board["categories"][1]["id"]
    assert book.toggle_slot("toggle", 0, "c:" + hoodie["id"])
    assert book.toggle_slot("toggle", 4, "c:" + hoodie["id"])        # the same toggle twice
    assert pb.slots_of(book.board, "c:" + hoodie["id"]) == [("toggle", 0), ("toggle", 4)]
    assert book.toggle_slot("toggle", 0, "c:" + glow["id"])          # taken from Hoodie
    assert pb.slots_of(book.board, "c:" + hoodie["id"]) == [("toggle", 4)]
    assert book.toggle_slot("toggle", 0, "c:" + glow["id"])          # its own again: freed
    assert book.board["slots"]["toggle"][0] is None
    assert not book.toggle_slot("toggle", 1, "c:" + bright["id"])    # a slider isn't a toggle
    assert not book.toggle_slot("radial", 7, "c:" + bright["id"])    # there are seven
    assert book.toggle_slot("radial", 1, "c:" + bright["id"])
    assert book.toggle_slot("toggle", 2, "g:" + cat)                 # a category takes both
    assert book.toggle_slot("radial", 2, "g:" + cat)
    again = pb.BoardBook(store)                                      # saved with the preset
    again.open_avatar(book.avatar_id)
    assert again.board["slots"] == book.board["slots"]


def test_slots_follow_their_controls_and_junk_is_dropped():
    book, _ = worn()
    hoodie = book.add_control("Hoodie", "toggle")
    outfit = book.add_control("OutfitIndex", "toggle")              # an Int toggle
    book.toggle_slot("toggle", 0, "c:" + hoodie["id"])
    book.toggle_slot("toggle", 1, "c:" + outfit["id"])
    book.update_control(outfit["id"], kind="slider")                # no toggle any more
    assert book.board["slots"]["toggle"][1] is None
    book.remove_control(hoodie["id"])
    assert book.board["slots"]["toggle"][0] is None
    cat = book.board["categories"][2]["id"]
    book.toggle_slot("radial", 3, "g:" + cat)
    book.remove_category(cat)
    assert book.board["slots"]["radial"][3] is None
    preset = pb.normalize_preset({"slots": {"toggle": ["c:nope", 5, None], "radial": "x"}})
    assert preset["slots"] == pb.no_slots()


def test_what_a_slot_sends_and_shows():
    slider = {"param": "B", "ptype": "Float", "kind": "slider", "min": 0.2, "max": 0.6}
    stepper = {"param": "N", "ptype": "Int", "kind": "int", "min": 0.0, "max": 10.0}
    inverted = {"param": "T", "ptype": "Bool", "kind": "toggle", "invert": True}
    assert pb.slot_send_value("radial", slider, 0.5) == pytest.approx(0.4)
    assert pb.slot_send_value("radial", stepper, 0.34) == 3
    assert pb.slot_send_value("radial", stepper, float("nan")) is None
    assert pb.slot_send_value("toggle", inverted, True) is False
    assert pb.slot_state("radial", [slider], {"B": 0.5}) == pytest.approx(0.75)
    assert pb.slot_state("radial", [slider], {}) is None
    hoodie = {"param": "H", "ptype": "Bool", "kind": "toggle"}
    assert pb.slot_state("toggle", [hoodie, inverted], {"H": False, "T": True}) is False
    assert pb.slot_state("toggle", [hoodie, inverted], {"H": True, "T": True}) is True


# --- the menu drives the worn board ---------------------------------------------

def slot_host():
    owner, _watcher = pair()
    ids = build(owner)
    owner.osc_manager.sent.clear()
    return owner, ids


def sent(h):
    out, h.osc_manager.sent = h.osc_manager.sent, []
    return out


def test_a_menu_toggle_drives_the_control_in_its_slot():
    h, ids = slot_host()
    assert h.params_edit_quiet("toggle_slot", "toggle", 0, "c:" + ids["hoodie"])
    h._params_menu_on_osc("OGP/Remote/Toggle1", True)
    assert sent(h) == [("Hoodie", True)]
    h._params_menu_on_osc("OGP/Remote/Toggle1", False)
    assert sent(h) == [("Hoodie", False)]
    h._params_menu_on_osc("OGP/Remote/Toggle2", True)               # a free slot
    assert sent(h) == []


def test_a_radial_spans_its_slider_and_a_toggle_holds_a_button():
    h, ids = slot_host()
    h.params_edit("update_control", ids["bright"], min=0.2, max=0.6)
    h.params_edit_quiet("toggle_slot", "radial", 2, "c:" + ids["bright"])
    h.params_edit_quiet("toggle_slot", "toggle", 6, "c:" + ids["wave"])
    h._params_menu_on_osc("OGP/Remote/Radial3", 0.5)
    h._params_menu_on_osc("OGP/Remote/Toggle7", True)
    h._params_menu_on_osc("OGP/Remote/Toggle7", False)
    out = sent(h)
    assert out[0][0] == "Brightness" and out[0][1] == pytest.approx(0.4)
    assert out[1:] == [("Emote", 3), ("Emote", 0)]                  # held, let go


def test_a_category_slot_drives_what_fits_even_a_locked_one():
    h, ids = slot_host()
    cats = h._params_book.board["categories"]
    h.params_edit_quiet("toggle_slot", "toggle", 0, "g:" + cats[0]["id"])
    h.params_edit_quiet("toggle_slot", "radial", 0, "g:" + cats[0]["id"])
    h.params_edit_quiet("toggle_slot", "toggle", 1, "g:" + cats[1]["id"])
    h._params_menu_on_osc("OGP/Remote/Toggle1", True)
    assert sent(h) == [("Hoodie", True), ("TailWag", False), ("Emote", 3)]   # No wag inverted
    h._params_menu_on_osc("OGP/Remote/Radial1", 1.0)
    assert sent(h) == [("Brightness", 1.0)]
    h._params_menu_on_osc("OGP/Remote/Toggle2", True)              # locked is for friends
    assert sent(h) == [("Secret", True)]


def test_nothing_while_avatar_remote_is_off():
    h, ids = slot_host()
    h.params_edit_quiet("toggle_slot", "toggle", 0, "c:" + ids["hoodie"])
    h._features["feature_params"] = False
    h._params_menu_on_osc("OGP/Remote/Toggle1", True)
    h._params_menu_follow()
    assert sent(h) == []


def test_the_menu_follows_the_board_ogp_first():
    h, ids = slot_host()
    h.params_edit_quiet("toggle_slot", "toggle", 0, "c:" + ids["hoodie"])
    h.params_edit_quiet("toggle_slot", "radial", 0, "c:" + ids["bright"])
    h._params_menu_follow()
    assert sorted(sent(h)) == [("Radial1", 0.5), ("Toggle1", False)]
    h._params_menu_follow()
    assert sent(h) == []                                           # nothing changed
    h.params_set_control(ids["hoodie"], True)                      # the page
    sent(h)
    h._params_menu_follow()
    assert sent(h) == [("Toggle1", True)]
    h._params_menu_on_osc("OGP/Remote/Toggle1", True)              # VRChat's echo of that
    assert sent(h) == []                                           # drives nothing


def test_the_menu_isnt_moved_under_your_hand():
    h, ids = slot_host()
    h.params_edit_quiet("toggle_slot", "radial", 0, "c:" + ids["bright"])
    h._params_menu_on_osc("OGP/Remote/Radial1", 0.3)               # you turn it
    sent(h)
    h.params_set_control(ids["bright"], 0.9)                       # something else moves it
    sent(h)
    h._params_menu_follow()
    assert sent(h) == []                                           # not while you're on it
    h._slot_hand_t["OGP/Remote/Radial1"] = time.monotonic() - 5
    h._params_menu_follow()
    assert sent(h) == [("Radial1", pytest.approx(0.9))]


def test_an_avatar_load_replay_is_answered_with_ogps():
    h, ids = slot_host()
    h.params_edit_quiet("toggle_slot", "toggle", 0, "c:" + ids["hoodie"])
    h._ogp_mode_guard_until = time.monotonic() + 5
    h._params_menu_on_osc("OGP/Remote/Toggle1", True)              # VRChat's saved value
    assert sent(h) == [("Toggle1", False)]                         # Hoodie stays, OGP's goes back
    h._params_menu_send()                                          # OSC (re)connect: all of them
    assert sent(h) == [("Toggle1", False)]


# --- the page --------------------------------------------------------------------

def test_the_circle_opens_the_radial_and_a_number_takes_the_slot(qapp):  # noqa: F811
    host, ui, root = page(qapp)
    hoodie = host.params_edit("add_control", "Hoodie", "toggle", "Hoodie")
    bright = host.params_edit("add_control", "Brightness", "slider", "Brightness")
    pump(qapp)
    card = ui._params_cards[hoodie["id"]]
    assert card.slot_dot.text() == "" and card.slot_dot.property("set") == "false"
    assert ui._params_cards[bright["id"]].slot_dot.menus == ("radial",)
    card.slot_dot.click()
    picker = ui._params_slot_picker
    assert picker.isVisible() and picker.key == "c:" + hoodie["id"]
    c = picker._centre()
    assert picker._hit(QPointF(c.x(), c.y() - 70)) == 0            # Back at the top
    assert picker._hit(QPointF(c.x() + 70, c.y())) == 2            # then 1-7 clockwise
    assert picker._hit(c) == -2
    picker._on_pick("toggle", 2, picker.key)
    assert host._params_book.board["slots"]["toggle"][2] == "c:" + hoodie["id"]
    assert card.slot_dot.text() == "3" and card.slot_dot.property("set") == "true"
    assert picker.isVisible()                                      # stays open for another
    card.slot_dot.click()                                          # its circle again: closed
    assert not picker.isVisible()
    box = next(iter(ui._params_boxes.values()))
    host.params_edit_quiet("toggle_slot", "radial", 1, box.slot_dot.key)
    host.params_edit_quiet("toggle_slot", "toggle", 0, box.slot_dot.key)
    assert box.slot_dot.text() == "T1·R2"
    root.hide()
