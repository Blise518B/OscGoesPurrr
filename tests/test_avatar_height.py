"""Height on the Avatar Remote (docs/ROADMAP.md, Blise's calls 2026-11-14):
VRChat's /avatar/eyeheight, like the OSC scaler tools.

The box's range and clamping (never past the safe 0.1-100 m, a friend never
past your lowest / highest), Grow (a gentle glide) / Right away / Reset
(your own height: what VRChat said before anyone changed it), the gentle
send rate, the box's switch and lock, a world that forbids scaling, VRChat's
echo, a friend's path end to end (Pause all, logged, it stays where they
put it), the avatar menu's radial slot, and the page's and friend's boxes."""

import math

import pytest

import avatar_height as ah
import param_board as pb
import param_filters as pf
import remote_params as rp
from parameter_store import store
from test_params_facade import OWNER, WATCHER, build, pair, wire


class FakeClock:
    def __init__(self, start=0.0):
        self.t = float(start)

    def now(self):
        return self.t

    def advance(self, seconds):
        self.t += float(seconds)


def control(clock=None):
    clock = clock or FakeClock(100.0)
    return ah.HeightControl(clock=clock.now), clock


# --- the settings: range and clamping --------------------------------------------

def test_the_range_is_vrchats_menu_range_out_of_the_box_and_never_past_the_safe_one():
    s = ah.clean_settings(None)
    assert (s["on"], s["locked"], s["lo"], s["hi"]) == (True, False, 0.2, 5.0)
    assert s["double_s"] == ah.DOUBLE_S_DEFAULT
    wide = ah.clean_settings({"lo": 0.001, "hi": 5000, "double_s": 0.01, "on": "yes"})
    assert (wide["lo"], wide["hi"], wide["double_s"]) == (0.1, 100.0, ah.DOUBLE_S_MIN)
    assert wide["on"] is True                              # junk keeps the default
    crossed = ah.clean_settings({"lo": 3.0, "hi": 1.0})
    assert crossed["hi"] >= crossed["lo"] * ah.MIN_RATIO - 1e-9
    junk = ah.clean_settings({"lo": "x", "hi": float("nan"), "double_s": None})
    assert (junk["lo"], junk["hi"]) == (0.2, 5.0)


def test_moving_one_end_past_the_other_pushes_it_along():
    s = ah.clean_settings(None)
    up = ah.with_range(s, lo=8.0)
    assert up["lo"] == 8.0 and up["hi"] == pytest.approx(8.8)
    down = ah.with_range(s, hi=0.15)
    assert down["hi"] == 0.15 and down["lo"] <= 0.15 / ah.MIN_RATIO + 1e-9
    assert down["lo"] >= ah.SAFE_MIN
    assert ah.with_range(s, hi=1e6)["hi"] == ah.SAFE_MAX


def test_the_slider_is_a_log_scale():
    assert ah.to_slider(2.0, 1.0, 4.0) == pytest.approx(0.5)      # equal factors, equal steps
    assert ah.from_slider(0.5, 1.0, 4.0) == pytest.approx(2.0)
    assert ah.to_slider(0.01, 0.2, 5.0) == 0.0 and ah.to_slider(99, 0.2, 5.0) == 1.0
    assert ah.from_slider(-3, 0.2, 5.0) == pytest.approx(0.2)
    assert ah.from_slider(7, 0.2, 5.0) == pytest.approx(5.0)
    assert ah.to_slider(None, 0.2, 5.0) is None
    for x in (0.0, 0.1, 0.37, 0.5, 0.99, 1.0):
        assert ah.to_slider(ah.from_slider(x, 0.2, 5.0), 0.2, 5.0) == pytest.approx(x)
    assert ah.fmt(1.625) in ("1.62 m", "1.63 m") and ah.fmt(None) == "–"
    assert ah.fmt(42.0) == "42.0 m" and ah.fmt_speed(4.0) == "×2 in 4 s"


def test_grow_moves_by_a_factor_and_never_overshoots():
    assert ah.glide_step(1.0, 4.0, 4.0, 4.0) == pytest.approx(2.0)   # doubles in double_s
    assert ah.glide_step(4.0, 1.0, 2.0, 4.0) == pytest.approx(4.0 / math.sqrt(2))
    assert ah.glide_step(1.0, 1.1, 10.0, 4.0) == 1.1                 # lands, never past
    assert ah.glide_step(1.0, 2.0, 0.0, 4.0) == 1.0
    assert ah.glide_seconds(1.0, 8.0, 4.0) == pytest.approx(12.0)


def test_the_height_keys_are_never_avatar_parameters():
    assert ah.KEYS == pf.NOT_PARAMETERS
    for key in ah.KEYS:
        assert not rp.settable(key)                                  # never in YOLO's list
        assert pf.group_of(key) == pf.VRCHAT                          # hidden in pickers


# --- HeightControl -----------------------------------------------------------------

def test_vrchats_word_is_your_height_and_your_own_until_a_write_of_ours():
    c, clock = control()
    c.heard(ah.KEY_HEIGHT, 1.62)
    assert (c.height, c.own) == (1.62, 1.62)
    assert c.jump(2.5) == 2.5
    c.heard(ah.KEY_HEIGHT, 2.5)                    # our own write, echoed
    assert (c.height, c.own) == (2.5, 1.62)
    clock.advance(ah.OURS_S + 0.1)
    c.heard(ah.KEY_HEIGHT, 1.9)                    # you, in VRChat's own menu
    assert (c.height, c.own) == (1.9, 1.9)
    c.avatar_changed()
    assert c.own is None
    c.heard(ah.KEY_HEIGHT, 1.3)                    # the new avatar's own
    assert c.own == 1.3
    c.heard(ah.KEY_HEIGHT, "nope")
    c.heard(ah.KEY_HEIGHT, -1)
    assert c.height == 1.3


def test_right_away_keeps_a_gentle_rate_and_the_newest_wins():
    c, clock = control()
    assert c.jump(1.0) == 1.0
    clock.advance(0.03)
    assert c.jump(1.5) is None                     # too soon: held back ...
    assert c.jump(1.7) is None                     # ... the newest one
    assert c.tick() is None                        # not yet half a gap on
    clock.advance(0.05)
    assert c.tick() == 1.7
    assert c.tick() is None                        # sent once
    clock.advance(ah.SEND_GAP_S + 0.01)
    assert c.jump(1000.0) == ah.SAFE_MAX           # never past what VRChat supports
    clock.advance(ah.SEND_GAP_S + 0.01)
    assert c.jump(0.0001) == ah.SAFE_MIN           # nor under it
    assert c.jump(0) is None and c.jump(-2) is None and c.jump(float("nan")) is None


def test_grow_glides_there_gently_and_stops_there():
    c, clock = control()
    c.heard(ah.KEY_HEIGHT, 1.0)
    c.double_s = 4.0
    assert c.grow(4.0) is None                     # the tick sends the steps
    sent = []
    for _ in range(200):
        clock.advance(0.1)
        out = c.tick()
        if out is not None:
            sent.append(out)
        c.heard(ah.KEY_HEIGHT, out or c.height)
        if not c.state()["gliding"]:
            break
    assert sent[-1] == 4.0 and 80 <= len(sent) <= 81    # 8 s for two doublings, ten a second
    assert all(b > a for a, b in zip(sent, sent[1:]))
    assert max(b / a for a, b in zip(sent, sent[1:])) < 1.02     # small steps
    assert c.own == 1.0                            # the glide's echoes were ours


def test_reset_is_your_own_height_right_away():
    c, clock = control()
    assert c.reset() is None                       # not known yet
    c.heard(ah.KEY_HEIGHT, 1.62)
    c.jump(3.0)
    clock.advance(0.5)
    assert c.reset() == 1.62


def test_a_world_that_forbids_scaling_refuses_and_stops_a_glide():
    c, clock = control()
    c.heard(ah.KEY_HEIGHT, 1.0)
    c.grow(3.0, by="pal")
    assert c.heard(ah.KEY_ALLOWED, False) is True
    assert not c.state()["gliding"]
    clock.advance(1.0)
    assert c.jump(2.0) is None and c.grow(2.0) is None and c.tick() is None
    assert c.heard(ah.KEY_ALLOWED, False) is False          # no change, nothing to tell
    c.heard(ah.KEY_ALLOWED, True)
    assert c.jump(2.0) == 2.0
    c.heard(ah.KEY_MIN, 0.5)
    c.heard(ah.KEY_MAX, 2.5)
    assert (c.world_min, c.world_max) == (0.5, 2.5)


def test_pause_stops_only_a_friends_glide():
    c, _clock = control()
    c.heard(ah.KEY_HEIGHT, 1.0)
    c.grow(3.0)                                    # yours
    assert not c.stop_friends() and c.state()["gliding"]
    c.grow(3.0, by="pal")
    assert c.stop_friends() and not c.state()["gliding"]


# --- the controller: you, a friend, the menu ----------------------------------------

def heights_sent(host):
    return [v for name, v in host.osc_manager.sent if name == "eyeheight"]


def ready(**kw):
    """An owner wearing an avatar, VRChat saying 1.62 m; a friend watching."""
    owner, watcher = pair(**kw)
    clock = FakeClock(500.0)
    owner._height._clock = clock.now
    owner._height_on_osc(ah.KEY_HEIGHT, 1.62)
    build(owner)
    watcher.set_friend_params_watch(OWNER)
    wire(owner, watcher)
    return owner, watcher, clock


def test_you_go_right_away_inside_your_range():
    owner, _watcher, clock = ready()
    assert owner.height_go(9.0, ah.NOW)
    assert heights_sent(owner) == [5.0]            # your highest
    clock.advance(1.0)
    owner.height_set_option("lo", 0.5)
    owner.height_go(0.01, ah.NOW)
    assert heights_sent(owner)[-1] == 0.5
    assert owner.get_height_status()["lo"] == 0.5
    assert not owner.height_go("x", ah.NOW) and not owner.height_go(1.0, "fly")


def test_grow_reaches_vrchat_from_the_params_tick():
    owner, _watcher, clock = ready()
    owner.height_set_option("double_s", 1.0)
    owner.height_go(3.24, ah.GROW)
    assert heights_sent(owner) == []
    for _ in range(20):
        clock.advance(0.1)
        owner._params_tick()
    sent = heights_sent(owner)
    assert sent[-1] == pytest.approx(3.24) and len(sent) == 10       # one doubling in 1 s


def test_a_friend_sees_the_box_and_your_height_and_sets_it_inside_your_range():
    owner, watcher, clock = ready()
    theirs = watcher.get_friend_board(OWNER)
    assert theirs["board"]["height"] == {"lo": 0.2, "hi": 5.0, "locked": False, "allowed": True}
    assert theirs["height"] == 1.62
    owner._height_on_osc(ah.KEY_HEIGHT, 1.7)       # VRChat's echo, on to the friend
    wire(owner, watcher, rounds=1)
    assert watcher.get_friend_board(OWNER)["height"] == 1.7
    assert watcher.friend_height(OWNER, ah.NOW, 50.0)
    wire(owner, watcher, rounds=1)
    assert heights_sent(owner) == [5.0]            # they can't widen your range
    assert "Pal set your height to 5.00 m" in owner.notes()
    assert "You set Pal's height to 5.00 m" in watcher.notes()


def test_a_friends_raw_height_past_your_range_is_clamped_on_your_side():
    owner, watcher, clock = ready()
    watcher.friends_link.send_event(OWNER, rp.make_height_set(10 ** 15, ah.NOW, 80.0))
    wire(owner, watcher, rounds=1)
    assert heights_sent(owner) == [5.0]


def test_it_stays_where_they_put_it_when_they_leave():
    owner, watcher, clock = ready()
    watcher.friend_height(OWNER, ah.NOW, 3.0)
    wire(owner, watcher, rounds=1)
    owner._height_on_osc(ah.KEY_HEIGHT, 3.0)
    owner._params_drop_friend(WATCHER)             # they went offline
    for _ in range(5):
        clock.advance(1.0)
        owner._params_tick()
    assert heights_sent(owner) == [3.0] and owner._height.height == 3.0


def test_a_friends_grow_and_reset():
    owner, watcher, clock = ready()
    watcher.friend_height(OWNER, ah.GROW, 3.24)
    wire(owner, watcher, rounds=1)
    assert owner._height.state()["gliding"] and owner._height.state()["by"] == WATCHER
    assert "Pal grew you to 3.24 m" in owner.notes()
    clock.advance(0.5)
    watcher.friend_height(OWNER, ah.RESET)
    wire(owner, watcher, rounds=1)
    assert heights_sent(owner)[-1] == 1.62 and not owner._height.state()["gliding"]
    assert "Pal put your height back to 1.62 m" in owner.notes()


def test_a_copy_or_an_older_height_is_dropped():
    owner, watcher, clock = ready()
    watcher.friend_height(OWNER, ah.NOW, 2.0)
    clock.advance(1.0)
    watcher.friend_height(OWNER, ah.NOW, 3.0)
    watcher.friends_link.events = list(reversed(watcher.friends_link.events))
    wire(owner, watcher, rounds=1)
    assert heights_sent(owner) == [3.0]


def test_off_friends_dont_see_it_and_nothing_they_send_lands():
    owner, watcher, clock = ready()
    owner.height_set_option("on", False)
    wire(owner, watcher)
    assert watcher.get_friend_board(OWNER)["board"]["height"] is None
    assert not watcher.friend_height(OWNER, ah.NOW, 2.0)
    watcher.friends_link.send_event(OWNER, rp.make_height_set(10 ** 15, ah.NOW, 2.0))
    wire(owner, watcher, rounds=1)
    assert heights_sent(owner) == []
    assert owner.height_go(2.0, ah.NOW)            # your own box still works
    assert heights_sent(owner) == [2.0]
    owner.height_set_option("on", True)
    wire(owner, watcher)
    assert watcher.get_friend_board(OWNER)["board"]["height"] is not None


def test_locked_pause_and_a_forbidding_world_refuse_a_friend():
    owner, watcher, clock = ready()
    seq = [10 ** 15]

    def raw(v):
        seq[0] += 1
        watcher.friends_link.send_event(OWNER, rp.make_height_set(seq[0], ah.NOW, v))
        wire(owner, watcher, rounds=1)
        clock.advance(1.0)

    owner.height_set_option("locked", True)
    wire(owner, watcher)
    assert watcher.get_friend_board(OWNER)["board"]["height"]["locked"]
    assert not watcher.friend_height(OWNER, ah.NOW, 2.0)          # refused on their side ...
    raw(2.0)                                                      # ... and on yours
    owner.height_set_option("locked", False)
    owner.set_friends_paused(True)
    raw(2.1)
    owner.set_friends_paused(False)
    owner._height_on_osc(ah.KEY_ALLOWED, False)
    owner._params_tick()                                          # friends hear of it
    wire(owner, watcher)
    assert watcher.get_friend_board(OWNER)["board"]["height"]["allowed"] is False
    raw(2.2)
    assert heights_sent(owner) == []


def test_a_friend_outside_your_instance_is_refused_like_any_set():
    """"Only friends in my instance" (row 13): its `_params_blocked(peer)`
    and `_params_refused` cover your height like any Avatar Remote set."""
    owner, watcher, clock = ready()
    said = []
    owner._params_blocked = lambda peer=None: peer == WATCHER
    owner._params_refused = lambda peer, what: said.append((peer, what))
    watcher.friend_height(OWNER, ah.NOW, 2.0)
    wire(owner, watcher, rounds=1)
    assert heights_sent(owner) == [] and said == [(WATCHER, "set your height")]


def test_pause_all_stops_a_glide_a_friend_started():
    owner, watcher, clock = ready()
    watcher.friend_height(OWNER, ah.GROW, 4.0)
    wire(owner, watcher, rounds=1)
    assert owner._height.state()["gliding"]
    owner.set_friends_paused(True)
    assert not owner._height.state()["gliding"]


def test_without_their_avatar_switch_a_friend_gets_no_box():
    owner, watcher, clock = ready()
    owner.set_friend_permission(WATCHER, "params", False)
    wire(owner, watcher)
    watcher.friends_link.send_event(OWNER, rp.make_height_set(10 ** 15, ah.NOW, 2.0))
    wire(owner, watcher, rounds=1)
    assert heights_sent(owner) == []


def test_the_height_keys_stay_off_the_parameter_list():
    owner, _watcher, clock = ready()
    for key, value in ((ah.KEY_HEIGHT, 1.62), (ah.KEY_ALLOWED, True), (ah.KEY_MIN, 0.2)):
        store.update_parameter(key, value)          # the OSC layer stores what it hears
    owner._params_sync_types(force=True)
    assert not set(owner.params_param_list()) & ah.KEYS


def test_settings_are_kept_and_cleaned(tmp_path):
    from settings.param_boards import ParamBoardsSettingsManager
    owner, _watcher, clock = ready()
    owner.height_set_option("hi", 12.0)
    owner.height_set_option("locked", True)
    again = ParamBoardsSettingsManager()
    assert again.get_height()["hi"] == 12.0 and again.get_height()["locked"] is True
    with pytest.raises(ValueError):
        owner.height_set_option("speed", 1)


def test_vrchat_gone_forgets_the_height():
    owner, _watcher, clock = ready()
    owner._params_vrchat_gone()
    st = owner.get_height_status()
    assert st["height"] is None and st["own"] is None


def test_the_osc_layer_hands_vrchats_height_to_the_box():
    from controllers.osc_facade import OscFacade
    import queue

    class Stub(OscFacade):
        def __init__(self):
            self.thread_queue = queue.Queue()
            self.heard = []

        def _height_on_osc(self, address, value):
            self.heard.append((address, value))

    stub = Stub()
    stub.on_osc_message("avatar/eyeheight", 1.5)
    stub.on_osc_message("avatar/eyeheightscalingallowed", False)
    stub.on_osc_message("Hoodie", True)
    assert stub.heard == [("avatar/eyeheight", 1.5), ("avatar/eyeheightscalingallowed", False)]


# --- the avatar menu: a radial slot -----------------------------------------------

def test_a_radial_slot_drives_your_height_and_follows_it():
    owner, _watcher, clock = ready()
    assert owner.params_edit_quiet("toggle_slot", "radial", 2, pb.HEIGHT_SLOT)
    assert not owner._params_book.toggle_slot("toggle", 0, pb.HEIGHT_SLOT)   # a radial only
    assert owner._slot_map["OGP/Remote/Radial3"] == ("height", [])
    assert pb.slot_label(owner._params_book.board, pb.HEIGHT_SLOT) == "Height"
    owner.height_set_option("locked", True)        # your own menu ignores the lock
    owner._params_menu_on_osc("OGP/Remote/Radial3", 0.5)
    assert heights_sent(owner) == [pytest.approx(1.0)]       # halfway 0.2..5 on a log scale
    owner._height_on_osc(ah.KEY_HEIGHT, 5.0)       # a friend made you 5 m
    owner._slot_hand_t.clear()
    owner._params_menu_follow()
    assert ("Radial3", 1.0) in owner.osc_manager.sent


# --- the page and a friend's box ---------------------------------------------------

def test_the_page_has_the_box_and_drives_vrchat(qapp):
    from test_params_page import page, pump
    host, ui, root = page(qapp)
    box = ui._params_height
    assert box.isVisible() and box.slot_dot is not None and box.switch.isChecked()
    host._height_on_osc(ah.KEY_HEIGHT, 1.6)
    ui.refresh_params_live()
    assert box.now_lbl.text() == "1.60 m"
    assert ah.from_slider(box.slider.value() / 1000, 0.2, 5.0) == pytest.approx(1.6, rel=0.01)
    box.slider.setValue(1000)                      # your highest
    box.now_btn.click()
    assert heights_sent(host) == [5.0]
    box.switch.click()
    assert host.params_settings.get_height()["on"] is False
    ui.refresh_params_live()
    assert "friends don't see" in box.note.text()
    host._height_on_osc(ah.KEY_ALLOWED, False)
    ui.refresh_params_live()
    assert not box.body.isEnabled() and "doesn't allow" in box.note.text()
    box.menu_btn.click()
    pump(qapp)
    assert box.options.isVisible()
    hi_slider, hi_label = box.opt_rows["hi"]
    hi_slider.setValue(round(ah.to_slider(10.0, ah.SAFE_MIN, ah.SAFE_MAX) * 1000))
    assert host.params_settings.get_height()["hi"] == pytest.approx(10.0, rel=0.01)
    assert hi_label.text().endswith(" m")
    root.hide()


@pytest.mark.parametrize("folded_out", [False, True])
def test_the_page_gives_the_box_room_for_a_wrapped_note(qapp, folded_out):
    """Blise's screenshot (2026-11-17): with "Waiting for VRChat ..." under
    it the box was drawn at its own width but given the height it needs
    at the column's -- the note wrapped once more and Grow / Right away /
    Reset were cut off at the bottom."""
    from test_params_page import page, pump
    host, ui, root = page(qapp)
    box = ui._params_height
    box.show_state(None, 0.2, 5.0, usable=False,
                   note="Waiting for VRChat - your height shows once it's running.")
    if folded_out:
        box.menu_btn.click()
    pump(qapp)
    assert box.height() >= box.layout().totalHeightForWidth(box.width())
    for btn in (box.grow_btn, box.now_btn, box.reset_btn):
        bottom = btn.mapTo(box, btn.rect().bottomLeft()).y()
        assert bottom < box.note.geometry().top()       # the note under the buttons, not on them
    root.hide()


def test_the_page_puts_the_box_in_a_radial_slot(qapp):
    from test_params_page import page, pump
    host, ui, root = page(qapp)
    box = ui._params_height
    box.slot_dot.click()
    pump(qapp)
    picker = ui._params_slot_picker
    assert picker is not None and picker.isVisible() and picker.key == pb.HEIGHT_SLOT
    ui._params_slot_picked("radial", 0, pb.HEIGHT_SLOT)
    assert box.slot_dot.text() == "1"
    picker.close_picker()
    root.hide()


def test_a_friends_box_follows_their_height_and_a_locked_one_is_look_only(qapp):
    import ui_components as uc
    from PySide6.QtWidgets import QWidget
    from test_params_page import _BoardStub, _their_board
    from ui.layout_helpers import vbox
    theirs = _their_board(False)
    board = dict(theirs["board"], height={"lo": 0.2, "hi": 5.0, "locked": False,
                                          "allowed": True})
    stub = _BoardStub(dict(theirs, board=board, height=1.4))
    asked = []
    stub.friend_height = lambda peer, mode, v=None: asked.append((mode, v))
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
    box = b["height"]
    assert box is not None and box.slot_dot is None and box.switch is None
    assert box.now_lbl.text() == "1.40 m" and box.body.isEnabled()
    box.slider.setValue(1000)
    box.grow_btn.click()
    box.reset_btn.click()
    assert asked == [(ah.GROW, pytest.approx(5.0)), (ah.RESET, None)]
    locked = dict(board, height=dict(board["height"], locked=True))
    stub.theirs = dict(stub.theirs, board=locked)
    ui._update_friend_board()
    assert b["height"] is box                      # in place, not rebuilt
    assert not box.body.isEnabled() and not box.lock_lbl.isHidden()


@pytest.fixture(scope="module")
def qapp():
    import sys
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication(sys.argv[:1])


@pytest.fixture(autouse=True)
def _empty_store_after():
    yield
    store.rebuild_from_json({})
