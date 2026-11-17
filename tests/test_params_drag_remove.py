"""Removing an Avatar Remote control by dragging it back to the parameter
list (friends' review, 2026-11-14): a control goes at once with a short
Undo in the window, a whole category asks first (in the window too -- a VR
overlay that captures the window doesn't show popups), Undo puts it back
exactly, menu slots included, and friends looking at the board get both.
Only your own board takes the drop."""

import copy

import pytest
from PySide6.QtCore import QMimeData, QPointF, Qt
from PySide6.QtGui import QDragEnterEvent, QDragLeaveEvent, QDragMoveEvent, QDropEvent
from PySide6.QtWidgets import (
    QApplication, QDialog, QInputDialog, QLabel, QMessageBox, QWidget,
)

import param_board as pb
import ui_components as uc
from test_param_board import OTHER, worn
from test_params_facade import OWNER, watched, wire
from test_params_page import _BoardStub, _their_board, page, pump, qapp  # noqa: F401 (fixture)
from ui.layout_helpers import vbox
from ui.views import param_remove
from ui.views.param_cards import (
    MIME_CATEGORY, MIME_CONTROL, MIME_PARAM, ParamCard, ParamCategory, ParamTree,
)


def filled():
    """A worn board with controls in two categories, slotted in the menu:
    Hoodie in Toggles 1 and 5, Brightness in Radials 2, the second
    category in Toggles 3 and Radials 3."""
    book, store = worn()
    cats = book.board["categories"]
    ids = {
        "hoodie": book.add_control("Hoodie", "toggle")["id"],
        "glow": book.add_control("GlowToggle", "toggle", "Glow")["id"],
        "bright": book.add_control("Brightness", "slider", category=cats[1]["id"])["id"],
        "tail": book.add_control("TailWag", "toggle", category=cats[1]["id"])["id"],
        "outfit": book.add_control("OutfitIndex", "int")["id"],
    }
    for menu, i, key in (("toggle", 0, "c:" + ids["hoodie"]), ("toggle", 4, "c:" + ids["hoodie"]),
                         ("radial", 1, "c:" + ids["bright"]), ("toggle", 2, "g:" + cats[1]["id"]),
                         ("radial", 2, "g:" + cats[1]["id"])):
        assert book.toggle_slot(menu, i, key)
    return book, store, ids


# --- the board ------------------------------------------------------------------

def test_a_taken_control_leaves_its_slots_and_undo_puts_it_back_exactly():
    book, store, ids = filled()
    before = copy.deepcopy(book.board)
    snap = book.take_control(ids["hoodie"])
    assert snap and pb.find_control(book.board, ids["hoodie"]) is None
    assert pb.slots_of(book.board, "c:" + ids["hoodie"]) == []      # out of Toggles 1 and 5
    again = pb.BoardBook(store)                                     # saved like any edit
    again.open_avatar(book.avatar_id)
    assert pb.find_control(again.board, ids["hoodie"]) is None
    assert book.put_back(snap)
    assert book.board == before                                     # its place, its slots
    again = pb.BoardBook(store)
    again.open_avatar(book.avatar_id)
    assert again.board == before
    assert not book.put_back(snap)                                  # it's already there
    assert book.take_control("nope") is None


def test_a_taken_category_takes_its_controls_and_undo_brings_them_all():
    book, _, ids = filled()
    cats = book.board["categories"]
    gone = cats[1]["id"]
    before = copy.deepcopy(book.board)
    snap = book.take_category(gone)
    assert snap and pb.find_category(book.board, gone) is None
    assert {c["id"] for c in book.board["controls"]} == {ids["hoodie"], ids["glow"], ids["outfit"]}
    assert pb.slots_of(book.board, "g:" + gone) == []
    assert pb.slots_of(book.board, "c:" + ids["bright"]) == []
    assert pb.slots_of(book.board, "c:" + ids["hoodie"]) == [("toggle", 0), ("toggle", 4)]
    assert book.put_back(snap)
    assert book.board == before


def test_the_last_category_is_emptied_not_removed():
    book, _ = worn()
    cats = book.board["categories"]
    for cat in cats[1:]:
        assert book.take_category(cat["id"])
    last = book.board["categories"][0]["id"]
    assert book.take_category(last) is None                         # nothing to do
    hoodie = book.add_control("Hoodie", "toggle")
    book.toggle_slot("toggle", 1, "g:" + last)
    before = copy.deepcopy(book.board)
    snap = book.take_category(last)
    assert snap and [c["id"] for c in book.board["categories"]] == [last]
    assert book.board["controls"] == [] and book.board["slots"]["toggle"][1] == "g:" + last
    assert book.put_back(snap)
    assert book.board == before and pb.find_control(book.board, hoodie["id"])


def test_undo_keeps_what_you_did_since():
    book, _, ids = filled()
    snap = book.take_control(ids["hoodie"])
    assert book.toggle_slot("toggle", 0, "c:" + ids["glow"])        # Toggles 1 went to Glow
    assert book.put_back(snap)
    assert book.board["slots"]["toggle"][0] == "c:" + ids["glow"]   # stays Glow's
    assert book.board["slots"]["toggle"][4] == "c:" + ids["hoodie"]
    # its category went in the meantime: it comes back in the first one
    snap = book.take_control(ids["bright"])
    cat = book.board["categories"][1]["id"]
    assert book.remove_category(cat)
    assert book.put_back(snap)
    assert pb.find_control(book.board, ids["bright"])["cat"] == book.board["categories"][0]["id"]


def test_undo_only_onto_the_board_it_came_off():
    book, store, ids = filled()
    snap = book.take_control(ids["glow"])
    book.add_preset("Second")                                       # another preset open
    assert not book.put_back(snap)
    assert pb.find_control(book.board, ids["glow"]) is None
    first = book.profile["presets"][0]["id"]
    assert book.switch_preset(first) and book.put_back(snap)
    snap = book.take_control(ids["glow"])
    store.save(pb.normalize_profile({"name": "Other"}, OTHER))
    book.open_avatar(OTHER)                                         # another avatar open
    assert not book.put_back(snap)
    assert not book.put_back(None) and not book.put_back({"avatar_id": OTHER})


# --- the controller: friends get it like any edit ---------------------------------

def test_friends_and_the_avatar_menu_follow_a_removal_and_its_undo():
    owner, watcher, ids = watched()
    owner.params_edit_quiet("toggle_slot", "toggle", 0, "c:" + ids["hoodie"])
    wire(owner, watcher)
    assert "OGP/Remote/Toggle1" in owner._slot_map
    snap = owner.params_edit("take_control", ids["hoodie"])
    wire(owner, watcher)
    theirs = {c["id"] for c in watcher.get_friend_board(OWNER)["board"]["controls"]}
    assert ids["hoodie"] not in theirs
    assert "OGP/Remote/Toggle1" not in owner._slot_map              # the menu slot is free
    assert owner.params_edit("put_back", snap)
    wire(owner, watcher)
    theirs = {c["id"] for c in watcher.get_friend_board(OWNER)["board"]["controls"]}
    assert ids["hoodie"] in theirs
    assert owner._slot_map["OGP/Remote/Toggle1"][1][0]["id"] == ids["hoodie"]


def test_a_category_removal_reaches_friends():
    owner, watcher, ids = watched()
    locked = owner._params_book.board["categories"][1]["id"]
    assert owner.params_edit("take_category", locked)
    wire(owner, watcher)
    board = watcher.get_friend_board(OWNER)["board"]
    assert locked not in {c["id"] for c in board["categories"]}
    assert ids["secret"] not in {c["id"] for c in board["controls"]}


# --- the list as a drop target ----------------------------------------------------

def _mime(kind, data):
    md = QMimeData()
    md.setData(kind, data.encode())
    return md


def _drag(tree, cls, md):
    at = tree.viewport().rect().center()
    ev = (cls(QPointF(at), Qt.MoveAction | Qt.CopyAction, md, Qt.LeftButton, Qt.NoModifier)
          if cls is QDropEvent else
          cls(at, Qt.MoveAction | Qt.CopyAction, md, Qt.LeftButton, Qt.NoModifier))
    QApplication.sendEvent(tree.viewport(), ev)
    return ev


def test_the_list_lights_up_for_what_it_takes_and_says_what_was_dropped(qapp):
    tree = ParamTree()
    tree.accept_removal(MIME_CONTROL, "Undo brings it back.")
    tree.resize(300, 400)
    tree.show()
    got = []
    tree.remove_dropped.connect(lambda mime, key: got.append((mime, key)))
    card = _mime(MIME_CONTROL, "abc123")
    assert _drag(tree, QDragEnterEvent, card).isAccepted()
    assert tree.drop_hint.isVisible()
    assert tree.drop_hint.text().startswith("Drop to remove")
    assert "Undo brings it back." in tree.drop_hint.text()
    assert tree.drop_hint.geometry() == tree.viewport().rect()
    assert _drag(tree, QDragMoveEvent, card).isAccepted()
    QApplication.sendEvent(tree.viewport(), QDragLeaveEvent())
    assert not tree.drop_hint.isVisible()
    _drag(tree, QDragEnterEvent, card)
    assert _drag(tree, QDropEvent, card).isAccepted()
    assert not tree.drop_hint.isVisible() and got == [(MIME_CONTROL, "abc123")]
    # a parameter dragged out of the list, or a category it wasn't told
    # about, passing over it: not taken, nothing lights up
    for other in (_mime(MIME_PARAM, "Hoodie\nBool"), _mime(MIME_CATEGORY, "c1")):
        assert not _drag(tree, QDragEnterEvent, other).isAccepted()
        assert not tree.drop_hint.isVisible()
        assert not _drag(tree, QDropEvent, other).isAccepted()
    assert got == [(MIME_CONTROL, "abc123")]
    tree.hide()


def test_a_friends_board_has_nothing_to_drag_back():
    """A friend's copy of your board is for looking and pressing: no
    grips, its cards start no drag, and it has no list to drop on."""
    card = ParamCard({"id": "k", "param": "P", "ptype": "Bool", "kind": "toggle",
                      "label": "P"}, editable=False)
    assert card._editable is False and card.slot_dot is None
    box = ParamCategory({"id": "c", "name": "Loco", "color": "amber"}, editable=False)
    assert not hasattr(box, "grip")
    ui = uc.OscGoesPurrrUI.__new__(uc.OscGoesPurrrUI)
    ui.controller, ui.views, ui._friends_big = _BoardStub(_their_board(False)), {}, False
    root = QWidget()
    ui._panel_lay = vbox(0, 0)
    root.setLayout(ui._panel_lay)
    ui._panel_w = {}
    ui._build_friend_board("f" * 64)
    ui._update_friend_board()
    assert root.findChildren(ParamTree) == []


# --- the page -----------------------------------------------------------------------

@pytest.fixture
def no_popups(monkeypatch):
    """Everything here happens in the window: any popup fails the test."""
    def popup(*_a, **_k):
        raise AssertionError("a popup window opened")
    for name in ("question", "warning", "information", "critical"):
        monkeypatch.setattr(QMessageBox, name, popup)
    monkeypatch.setattr(QMessageBox, "exec", popup)
    monkeypatch.setattr(QDialog, "exec", popup)
    monkeypatch.setattr(QInputDialog, "getText", popup)


def slotted_page(qapp):
    host, ui, root = page(qapp)
    hoodie = host.params_edit("add_control", "Hoodie", "toggle", "Hoodie")
    bright = host.params_edit("add_control", "Brightness", "slider", "Brightness")
    host.params_edit_quiet("toggle_slot", "toggle", 0, "c:" + hoodie["id"])
    host.params_edit_quiet("toggle_slot", "toggle", 3, "c:" + hoodie["id"])
    pump(qapp)
    return host, ui, root, hoodie, bright


def drop(ui, mime, key):
    tree = ui._params_tree
    md = _mime(mime, key)
    _drag(tree, QDragEnterEvent, md)
    assert tree.drop_hint.isVisible()
    _drag(tree, QDropEvent, md)


def test_a_card_dropped_on_the_list_goes_and_undo_brings_it_back(qapp, no_popups):
    host, ui, root, hoodie, _ = slotted_page(qapp)
    before = copy.deepcopy(host._params_book.board)
    ver = host._params_share["ver"]
    drop(ui, MIME_CONTROL, hoodie["id"])
    pump(qapp)
    assert pb.find_control(host._params_book.board, hoodie["id"]) is None   # at once
    assert hoodie["id"] not in ui._params_cards
    assert host._params_share["ver"] != ver                                 # friends get it
    strip = ui._params_remove_strip
    assert strip.isVisible() and strip.mode == "undo"
    assert strip.text.text() == "Removed “Hoodie”."
    assert strip.undo.isVisible() and not strip.yes.isVisible()
    strip.undo.click()
    pump(qapp)
    assert host._params_book.board == before                                # exactly, slots too
    card = ui._params_cards[hoodie["id"]]
    assert card.slot_dot.text() == "1·4"                                 # its two Toggles
    assert not strip.isVisible()
    root.hide()


def test_undo_is_offered_for_a_few_seconds_only(qapp, no_popups):
    host, ui, root, hoodie, _ = slotted_page(qapp)
    drop(ui, MIME_CONTROL, hoodie["id"])
    strip = ui._params_remove_strip
    assert 3 <= param_remove.UNDO_S <= 15
    assert strip._timer.isActive() and strip._timer.interval() == param_remove.UNDO_S * 1000
    strip._timer.timeout.emit()                                             # time's up
    assert not strip.isVisible()
    assert pb.find_control(host._params_book.board, hoodie["id"]) is None   # stays gone
    root.hide()


def test_a_category_dropped_on_the_list_asks_first(qapp, no_popups):
    host, ui, root, hoodie, bright = slotted_page(qapp)
    book = host._params_book
    cat = hoodie["cat"]
    host.params_edit_quiet("toggle_slot", "radial", 6, "g:" + cat)
    before = copy.deepcopy(book.board)
    drop(ui, MIME_CATEGORY, cat)
    pump(qapp)
    strip = ui._params_remove_strip
    assert strip.isVisible() and strip.mode == "ask"
    assert not strip._timer.isActive()                                      # waits for you
    name = book.board["categories"][0]["name"]
    assert strip.text.text() == f"Remove the category “{name}” and its 2 controls?"
    assert book.board == before                                             # nothing yet
    strip.no.click()                                                        # Keep
    assert not strip.isVisible() and book.board == before
    drop(ui, MIME_CATEGORY, cat)
    strip.yes.click()                                                       # Remove
    pump(qapp)
    assert pb.find_category(book.board, cat) is None and cat not in ui._params_boxes
    assert pb.find_control(book.board, bright["id"]) is None
    assert strip.mode == "undo" and strip.text.text() == f"Removed “{name}”."
    strip.undo.click()
    pump(qapp)
    assert book.board == before and cat in ui._params_boxes
    root.hide()


def test_an_empty_category_and_the_last_one_say_so(qapp, no_popups):
    host, ui, root = page(qapp)
    book = host._params_book
    strip = ui._params_remove_strip
    cats = book.board["categories"]
    drop(ui, MIME_CATEGORY, cats[3]["id"])
    assert strip.text.text() == f"Remove the empty category “{cats[3]['name']}”?"
    strip.yes.click()
    for cat in list(book.board["categories"][1:]):
        assert host.params_edit("take_category", cat["id"])
    last = book.board["categories"][0]["id"]
    pump(qapp)
    drop(ui, MIME_CATEGORY, last)
    assert strip.mode == "note" and "keeps one category" in strip.text.text()
    host.params_edit("add_control", "Hoodie", "toggle", category=last)
    pump(qapp)
    drop(ui, MIME_CATEGORY, last)
    assert strip.mode == "ask" and "last category" in strip.text.text()
    strip.yes.click()
    pump(qapp)
    assert [c["id"] for c in book.board["categories"]] == [last]
    assert book.board["controls"] == [] and strip.text.text().startswith("Emptied")
    root.hide()


def test_another_preset_or_avatar_lets_the_undo_go(qapp, no_popups):
    host, ui, root, hoodie, _ = slotted_page(qapp)
    strip = ui._params_remove_strip
    drop(ui, MIME_CONTROL, hoodie["id"])
    pump(qapp)
    assert strip.isVisible()
    host.params_edit("add_preset")                                          # another board open
    pump(qapp)
    assert not strip.isVisible()
    root.hide()


def test_the_page_takes_nothing_it_doesnt_know(qapp, no_popups):
    host, ui, root, hoodie, _ = slotted_page(qapp)
    before = copy.deepcopy(host._params_book.board)
    ui._params_tree.remove_dropped.emit(MIME_CONTROL, "nope")
    ui._params_tree.remove_dropped.emit(MIME_CATEGORY, "nope")
    ui._params_tree.remove_dropped.emit("application/x-something-else", hoodie["id"])
    pump(qapp)
    assert host._params_book.board == before
    assert not ui._params_remove_strip.isVisible()
    root.hide()


def test_a_drag_out_of_the_list_still_makes_a_control(qapp):
    """The list still lets parameters drag out (and isn't a place to move
    its rows about)."""
    _host, ui, root = page(qapp)
    tree = ui._params_tree
    assert tree.dragEnabled() and tree.acceptDrops()
    assert tree.viewport().acceptDrops()
    root.hide()


def test_the_list_hint_says_cards_can_go_back(qapp):
    _host, ui, root = page(qapp)
    texts = [w.text() for w in ui._params_dock.findChildren(QLabel)]
    assert any("Drag a control back here to remove it." in t for t in texts)
    root.hide()
