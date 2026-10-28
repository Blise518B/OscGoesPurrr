"""The Avatar Remote page and its board pieces, headless against a real
QApplication -- VRC Parameter Relay's int_toggle_test desktop half, on
OGP's port: Int toggles behave like VRChat's radial menu, a clicked stepper
keeps following the avatar, the wheel never changes a value, leaving a
field unedited doesn't rebuild the board, and a friend's locked category
is look-only."""

import sys

import pytest
from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QWheelEvent
from PySide6.QtWidgets import QApplication, QMessageBox, QPushButton, QWidget

import param_board as pb
import ui_components as uc
from parameter_store import store
from test_params_facade import AVATAR, OWNER, WATCHER, Host, oscquery
from ui.layout_helpers import vbox
from ui.views.param_cards import ParamCard, ParamCategory


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication(sys.argv[:1])


@pytest.fixture(autouse=True)
def _empty_store_after():
    yield
    store.rebuild_from_json({})


def pump(qapp, n=5):
    for _ in range(n):
        qapp.processEvents()


def wheel(widget, ticks=4):
    for _ in range(ticks):
        ev = QWheelEvent(QPointF(10, 10), QPointF(widget.mapToGlobal(QPoint(10, 10))),
                         QPoint(0, 0), QPoint(0, -120), Qt.NoButton, Qt.NoModifier,
                         Qt.NoScrollPhase, False)
        QApplication.sendEvent(widget, ev)


def control(kind, ptype, **extra):
    return dict({"id": f"{kind}1", "param": "P", "ptype": ptype, "kind": kind,
                 "label": "P", "cat": "c"}, **extra)


# --- the cards ---------------------------------------------------------------

def test_int_toggles_light_up_one_at_a_time(qapp):
    cards = [ParamCard(control("toggle", "Int", on=v, off=0, id=f"t{v}")) for v in (1, 2, 3)]
    for card in cards:
        card.update_value(2)
    assert [c.switch.isChecked() for c in cards] == [False, True, False]
    assert cards[1].switch.text() == "ON"


def test_a_toggle_sends_what_it_shows_and_follows_the_avatar(qapp):
    card = ParamCard(control("toggle", "Bool", invert=True))
    sent = []
    card.set_value.connect(lambda cid, v: sent.append(v))
    card.update_value(False)                       # inverted: parameter off = shown ON
    assert card.switch.isChecked() and sent == []  # a value coming in sends nothing
    card.switch.click()
    assert sent == [False]


def test_a_hold_button_presses_and_lets_go(qapp):
    card = ParamCard(control("button", "Bool"))
    got = []
    card.hold.connect(lambda cid, down: got.append(down))
    card.push.pressed.emit()
    card.push.released.emit()
    assert got == [True, False]


def test_a_clicked_stepper_still_follows_the_avatar(qapp):
    card = ParamCard(control("int", "Int", min=0, max=10))
    card.show()
    card.spin.setFocus()
    card.update_value(5)                           # changed in the radial menu
    assert card.spin.value() == 5
    card.hide()


def test_the_wheel_over_a_stepper_or_slider_changes_nothing(qapp):
    sent = []
    step = ParamCard(control("int", "Int", min=0, max=10))
    slide = ParamCard(control("slider", "Float", min=0, max=1))
    for card in (step, slide):
        card.set_value.connect(lambda cid, v: sent.append(v))
        card.update_value(0.5 if card is slide else 3)
        card.show()
    wheel(step.spin)
    wheel(slide.slider)
    pump(qapp)
    assert step.spin.value() == 3 and sent == []
    step.hide()
    slide.hide()


def test_a_friends_locked_category_is_look_only(qapp):
    box = ParamCategory({"id": "c", "name": "Loco", "color": "amber", "locked": True},
                        editable=False)
    box.add_card(ParamCard(control("toggle", "Bool"), editable=False))
    box.finalize()
    assert not box.cards_host.isEnabled()
    assert not hasattr(box, "grip") and not box.acceptDrops()
    mine = ParamCategory({"id": "c", "name": "Loco", "color": "amber", "locked": True})
    mine.finalize()
    assert mine.cards_host.isEnabled()             # you can still use your own


# --- the page ------------------------------------------------------------------

def page(qapp):
    store.rebuild_from_json(oscquery({"Outfit": 0, "Hoodie": False, "Brightness": 0.5}))
    host = Host(OWNER, WATCHER)
    host._params_avatar_changed(AVATAR)
    ui = uc.OscGoesPurrrUI.__new__(uc.OscGoesPurrrUI)
    ui.controller = host
    ui.views = {}
    root = QWidget()
    ui.window = root
    lay = vbox(0, 0)
    root.setLayout(lay)
    ui._build_params_view(lay)
    host.ui = ui
    root.resize(1400, 900)
    root.show()
    pump(qapp)
    return host, ui, root


def test_the_page_drives_vrchat_and_int_toggles_switch_each_other(qapp):
    host, ui, root = page(qapp)
    t1 = host.params_edit("add_control", "Outfit", "toggle", "Outfit 1")
    t2 = host.params_edit("add_control", "Outfit", "toggle", "Outfit 2")
    assert (t1["on"], t2["on"]) == (1, 2)
    pump(qapp)
    ui._params_cards[t2["id"]].switch.click()
    assert host.osc_manager.sent == [("Outfit", 2)]
    ui.refresh_params_live()
    assert ui._params_cards[t2["id"]].switch.isChecked()
    assert not ui._params_cards[t1["id"]].switch.isChecked()
    ui._params_cards[t1["id"]].switch.click()
    ui.refresh_params_live()
    assert ui._params_cards[t1["id"]].switch.isChecked()
    assert not ui._params_cards[t2["id"]].switch.isChecked()
    root.hide()


def test_the_page_says_it_is_your_own_avatars_and_points_to_friends(qapp, monkeypatch):
    """The page is called My Avatar Remote: a friend's avatar is used from
    Friends, and its button there goes with the Friends page."""
    from ui.views.params import VIEW_NAME
    host, ui, root = page(qapp)
    assert VIEW_NAME == "My Avatar Remote"
    opened = []
    monkeypatch.setattr(ui, "select_view", opened.append, raising=False)
    ui._params_friends_btn.click()
    assert opened == ["Friends"]
    ui.nav_buttons, ui.main_stack, ui.intiface_sidebar_section = {}, None, None
    for friends_on in (False, True):
        monkeypatch.setattr(ui, "_feature_allows_view",
                            lambda name, on=friends_on: on or name != "Friends",
                            raising=False)
        ui.apply_feature_visibility()
        assert ui._params_friends_btn.isVisible() is friends_on
    root.hide()


def test_leaving_a_name_unedited_doesnt_rebuild(qapp, monkeypatch):
    host, ui, root = page(qapp)
    host.params_edit("add_control", "Hoodie", "toggle")
    pump(qapp)
    rebuilds = []
    monkeypatch.setattr(ui, "_params_rebuild", lambda: rebuilds.append(1))
    box = next(iter(ui._params_boxes.values()))
    box.name_edit.editingFinished.emit()
    ui._params_name.editingFinished.emit()
    pump(qapp)
    assert rebuilds == []
    root.hide()


def test_a_parameter_dropped_on_a_category_becomes_a_control_there(qapp):
    host, ui, root = page(qapp)
    cats = host._params_book.board["categories"]
    box = ui._params_boxes[cats[2]["id"]]
    box.param_dropped.emit("Brightness", "Float", cats[2]["id"], 0)
    pump(qapp)
    added = host._params_book.board["controls"][-1]
    assert (added["param"], added["kind"], added["cat"]) == ("Brightness", "slider", cats[2]["id"])
    assert added["id"] in ui._params_cards
    root.hide()


def test_yolo_asks_first(qapp, monkeypatch):
    host, ui, root = page(qapp)
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: QMessageBox.No)
    ui._params_yolo.setChecked(True)
    assert not host.params_settings.get_yolo() and not ui._params_yolo.isChecked()
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: QMessageBox.Yes)
    ui._params_yolo.setChecked(True)
    assert host.params_settings.get_yolo()
    root.hide()


def test_an_avatar_open_for_editing_shows_offline_and_its_saved_list(qapp):
    host, ui, root = page(qapp)
    host.params_settings.save(pb.normalize_profile(
        {"name": "Other", "params": {"Tail": "Bool"}}, "avtr_other"))
    host.params_open_avatar("avtr_other")
    pump(qapp)
    assert ui._params_live.text() == "✎ OFFLINE"
    assert list(ui._params_items) == ["Tail"]
    root.hide()


def test_locking_a_category_on_the_page_saves_without_a_rebuild(qapp, monkeypatch):
    host, ui, root = page(qapp)
    host.params_edit("add_control", "Hoodie", "toggle")
    pump(qapp)
    rebuilds = []
    monkeypatch.setattr(ui, "_params_rebuild", lambda: rebuilds.append(1))
    ver = host._params_share["ver"]
    cat = host._params_book.board["categories"][0]["id"]
    ui._params_boxes[cat].lock_btn.click()
    pump(qapp)
    assert rebuilds == []                               # no blink
    assert host._params_book.board["categories"][0]["locked"]
    assert host._params_share["ver"] != ver             # friends get it
    root.hide()


class _BoardStub:
    """A controller that shows one friend's board."""

    def __init__(self, theirs):
        self.theirs = theirs

    def get_friend_board(self, peer):
        return self.theirs

    def set_friend_params_watch(self, peer, yolo_open=False):
        pass


def _their_board(locked: bool, name: str = "Outfit"):
    import remote_params as rp
    preset = pb.normalize_preset({
        "categories": [{"id": "c", "name": name, "color": "green", "locked": locked}],
        "controls": [{"id": "k", "param": "Hoodie", "ptype": "Bool", "kind": "toggle",
                      "label": "Hoodie", "cat": "c"}]})
    board = rp.read_board(rp.with_version(rp.public_board(preset, "Base", {}, False)))
    return {"prm": {"ver": board["ver"], "yolo": False, "stop": False}, "board": board,
            "values": {"Hoodie": True}, "holds": set()}


def test_a_friends_lock_or_rename_changes_their_board_in_place(qapp):
    stub = _BoardStub(_their_board(False))
    ui = uc.OscGoesPurrrUI.__new__(uc.OscGoesPurrrUI)
    ui.controller = stub
    ui.views = {}
    ui._friends_big = False
    root = QWidget()
    ui._panel_lay = vbox(0, 0)
    root.setLayout(ui._panel_lay)
    ui._panel_w = {}
    ui._build_friend_board("f" * 64)
    ui._update_friend_board()
    b = ui._panel_w["board"]
    box, card = b["boxes"]["c"], b["cards"]["k"]
    assert box.cards_host.isEnabled()
    stub.theirs = _their_board(True, "Clothes")        # locked and renamed over there
    ui._update_friend_board()
    assert b["boxes"]["c"] is box and b["cards"]["k"] is card     # nothing rebuilt
    assert not box.cards_host.isEnabled() and box._title.text() == "Clothes"
    stub.theirs = _their_board(False, "Clothes")
    ui._update_friend_board()
    assert b["boxes"]["c"] is box and box.cards_host.isEnabled()


def test_the_parameter_list_drags_wider_and_keeps_its_width(qapp):
    host, ui, root = page(qapp)
    split, dock = ui._params_split, ui._params_dock
    assert dock.width() >= 300                      # starts at its usual width
    left, right = split.sizes()
    split.setSizes([left - 250, right + 250])       # the bar dragged left
    pump(qapp)
    ui._params_keep_dock_width()                    # what the bar's timer does
    assert host.get_app_setting("params_dock_w") == dock.width() >= right + 200
    root.hide()
    again_root = QWidget()                          # the next launch starts there
    ui2 = uc.OscGoesPurrrUI.__new__(uc.OscGoesPurrrUI)
    ui2.controller, ui2.views, ui2.window = host, {}, again_root
    lay = vbox(0, 0)
    again_root.setLayout(lay)
    ui2._build_params_view(lay)
    again_root.resize(1400, 900)
    again_root.show()
    pump(qapp)
    assert abs(ui2._params_dock.width() - dock.width()) <= 12
    again_root.hide()


def test_a_friends_every_parameter_list_can_show_all(qapp):
    import remote_params as rp
    preset = pb.normalize_preset({"categories": [], "controls": []})
    types = {f"Param{i:03d}": "Bool" for i in range(100)}
    board = rp.read_board(rp.with_version(rp.public_board(preset, "Base", types, True)))
    stub = _BoardStub({"prm": {"ver": board["ver"], "yolo": True, "stop": False, "avatar": ""},
                       "board": board, "values": {}, "holds": set()})
    ui = uc.OscGoesPurrrUI.__new__(uc.OscGoesPurrrUI)
    ui.controller, ui.views, ui._friends_big = stub, {}, False
    root = QWidget()
    ui._panel_lay = vbox(0, 0)
    root.setLayout(ui._panel_lay)
    ui._panel_w = {}
    ui._build_friend_board("f" * 64)
    b = ui._panel_w["board"]
    b["yolo_open"] = True
    ui._update_friend_board()
    assert len(b["yolo_rows"]) == 60
    show = next(w for w in root.findChildren(QPushButton) if w.text().startswith("Show all"))
    assert show.text() == "Show all 100"
    show.click()
    assert len(b["yolo_rows"]) == 100
