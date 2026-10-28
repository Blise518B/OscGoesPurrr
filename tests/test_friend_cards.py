"""The Friends panel's toy and shocker cards (toy_card.py, shocker_card.py): what each mode sends, and the
grid / columns that follow the window's width. Headless, against a real
QApplication (like test_home_view)."""

import sys

import pytest
from PySide6.QtWidgets import QApplication, QLabel

from ui.layout_helpers import CardGrid, SideBySide
from ui.views.card_parts import CARD_MIN_W
from ui.views.shocker_card import ShockerCard
from ui.views.toy_card import ToyCard


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication(sys.argv[:1])


def toy_card():
    sent = {"level": [], "pattern": [], "override": []}
    card = ToyCard("Edge", "Lovense Edge 2", "pink",
                   on_level=sent["level"].append,
                   on_override=sent["override"].append,
                   on_pattern=lambda *p: sent["pattern"].append(p))
    return card, sent


def test_a_new_toy_card_starts_off_and_only_asks_for_a_mode(qapp):
    card, _sent = toy_card()
    card.show()
    assert card._mode == "off"
    assert card._hint.isVisible() and not card._level_row.isVisible()
    # Higher / Override are there from the start: a card that grew them
    # when its toy started pushed its row out of line
    assert card._over_box.isVisible()
    card.hide()


def test_direct_control_sends_the_level_and_off_stops_it(qapp):
    card, sent = toy_card()
    card._pick("linear")
    card._level_s.setValue(400)
    assert sent["level"][-1] == pytest.approx(0.4)
    card._pick("off")
    assert sent["level"][-1] == 0.0 and sent["pattern"][-1][0] == ""
    card._pick("linear")
    assert sent["level"][-1] == pytest.approx(0.4)      # Direct control remembers


def test_an_auto_mode_replaces_the_level(qapp):
    card, sent = toy_card()
    card._pick("linear")
    card._level_s.setValue(700)
    card._pick("square")
    assert sent["level"][-1] == 0.0                      # the mode is the level now
    assert sent["pattern"][-1][0] == "square"


def test_oscillate_swings_around_the_level(qapp):
    card, sent = toy_card()
    card._pick("linear")
    card._level_s.setValue(600)
    card._pick("osc")
    card._depth_s.setValue(100)
    wave, _period, lo, hi = sent["pattern"][-1]
    assert wave == "osc" and (lo, hi) == pytest.approx((0.5, 0.7))
    card._level_s.setValue(950)                          # near the top: clipped
    assert sent["pattern"][-1][3] == 1.0


def test_status_brings_the_card_in_line(qapp):
    card, sent = toy_card()
    card.set_state(0.0, True, ("heart", 1.0, 0.1, 0.6), 0.3)
    assert card._mode == "heart" and card._over.button(1).isChecked()
    card.set_state(0.5, False, None, 0.3)
    assert card._mode == "linear" and card._level == pytest.approx(0.5)
    assert sent == {"level": [], "pattern": [], "override": []}   # nothing echoed back


def shocker_card():
    calls = []
    card = ShockerCard("Collar", "yellow",
                       on_fire=lambda *a: calls.append(("fire",) + a),
                       on_hold=lambda *a: calls.append(("hold",) + a),
                       on_release=lambda: calls.append(("release",)),
                       on_stop=lambda: calls.append(("stop",)))
    card.set_caps((40, 80, 2000))
    return card, calls


def test_tap_sends_ops_within_their_caps_and_pishock_warnings(qapp):
    card, calls = shocker_card()
    card._sliders["shock"].setValue(40)
    card._tap("shock")
    assert calls[-1][:2] == ("fire", "shock") and calls[-1][2] == 1.0 and calls[-1][4] == 0
    card._warn_picked(2)                                 # Mid: 3-6 s of vibration first
    card._tap("shock")
    assert 3000 <= calls[-1][4] <= 6000
    card._tap("vibrate")
    assert calls[-1][1] == "vibrate" and calls[-1][4] == 0   # warnings are for shocks
    assert card._durations() == [100, 300, 1000, 2000]       # PiShock's lengths, up to theirs


def test_the_duration_picker_offers_pishocks_lengths_up_to_theirs(qapp):
    card, _calls = shocker_card()
    card.show()
    card._open_picker("shock_dur")
    qapp.processEvents()
    picker = card._picker
    assert [b.text() for b in picker.buttons][:4] == [".1", ".3", "1", "2"]
    assert [b.isEnabled() for b in picker.buttons][:5] == [True, True, True, True, False]
    assert not picker.isWindow()            # over the card: a VR overlay of the window shows it
    picker.buttons[2].click()
    assert card._dur["shock"] == 1000 and card._tiles["shock_dur"].value() == "1 s"
    assert card._picker is None or not card._picker.isVisible()
    card.hide()


def test_random_picks_a_strength_inside_its_range_every_shock(qapp):
    card, calls = shocker_card()
    card._dice_btn.setChecked(True)
    card._toggle_random()
    card._lo.setValue(10)
    card._hi.setValue(20)
    picks = set()
    for _ in range(60):
        card._tap("shock")
        picks.add(round(calls[-1][2] * 39) + 1)
    assert picks <= set(range(10, 21)) and len(picks) > 3
    assert card._tiles["shock"].value() == "10–20"
    card._nudge("shock", +1)                             # ⇈ moves the whole range
    assert (card._lo.value(), card._hi.value()) == (12, 22)


def test_remote_runs_while_held(qapp):
    card, calls = shocker_card()
    card._mode_picked(1)
    card._tap("shock")
    assert calls == []                                   # a press is not a tap here
    card._press("vibrate")
    card._unpress("vibrate")
    assert [c[0] for c in calls] == ["hold", "release"] and calls[0][1] == "vibrate"
    assert not card._tiles["shock_dur"].isEnabled()      # Remote: no Duration


def test_remote_with_a_warning_vibrates_first_then_shocks_while_held(qapp):
    card, calls = shocker_card()
    card._mode_picked(1)
    card._warn_picked(1)                                 # Small: 1-3 s
    card._press("shock")
    assert calls[-1][:2] == ("hold", "vibrate") and card._warn_timer.isActive()
    card._warned()                                       # the warning's time is up
    assert calls[-1][:2] == ("hold", "shock")
    card._unpress("shock")
    assert calls[-1] == ("release",)
    # let go during the warning: no shock comes after it
    card._press("shock")
    card._unpress("shock")
    card._warned()
    assert calls[-1] == ("release",) and not card._warn_timer.isActive()


def test_continuous_is_the_sliders(qapp):
    card, calls = shocker_card()
    card._mode_picked(2)
    assert not card._tiles["shock"].isEnabled() and card._sliders["shock"].value() == 0
    assert not card._tiles["beep"].isEnabled() and not card._dice_btn.isEnabled()
    card._sliders["vibrate"].setValue(40)
    assert calls[-1][:2] == ("hold", "vibrate")
    card._sliders["vibrate"].setValue(0)
    assert calls[-1] == ("release",)
    card._mode_picked(0)                                 # back to Tap: the strengths return
    assert card._sliders["shock"].value() > 0 and card._sliders["vibrate"].value() > 0


def test_continuous_with_a_warning_vibrates_before_the_shock_starts(qapp):
    card, calls = shocker_card()
    card._warn_picked(3)
    card._mode_picked(2)
    card._sliders["shock"].setValue(20)
    assert calls[-1][:2] == ("hold", "vibrate")
    card._sliders["shock"].setValue(25)                  # during the warning: nothing yet
    assert calls[-1][:2] == ("hold", "vibrate")
    card._warned()
    assert calls[-1][:2] == ("hold", "shock")
    assert calls[-1][2] == pytest.approx(24 / 39)        # where the slider is now
    card._sliders["shock"].setValue(0)
    assert calls[-1] == ("release",)


def test_paused_rests_operate_but_never_stop(qapp):
    card, calls = shocker_card()
    card.set_blocked(True)
    card._tap("shock")
    assert calls == [] and not card._tiles["shock"].isEnabled()
    assert card._tiles["stop"].isEnabled()
    card._stop()
    assert calls == [("stop",)]


def test_a_party_drives_all_one_at_random_or_one_after_the_other(qapp):
    from ui.views.shock_party import ShockParty
    sent = []
    party = ShockParty("Party", "yellow",
                       on_fire=lambda pairs, *a: sent.append(("fire", pairs) + a),
                       on_hold=lambda pairs, *a: sent.append(("hold", pairs) + a),
                       on_release=lambda pairs: sent.append(("release", pairs)),
                       on_stop=lambda pairs: sent.append(("stop", pairs)))
    party.set_targets([("a", 0, "A · Collar", "cyan"), ("a", 1, "A · Thigh", "cyan"),
                       ("b", 0, "B · Collar", "blue")])
    assert party.ticked() == [("a", 0), ("a", 1), ("b", 0)]    # a new one comes in ticked
    party.card._tap("shock")
    assert sent[-1][1] == [("a", 0), ("a", 1), ("b", 0)]       # Sync
    assert sent[-1][4] == 300                                  # real ms: PiShock's 0.3 s
    party._mode_picked(1)                                      # Random
    for _ in range(20):
        party.card._tap("shock")
        assert len(sent[-1][1]) == 1 and sent[-1][1][0] in party.ticked()
    party._mode_picked(2)                                      # Round Robin
    party._make_next(("b", 0))
    got = []
    for _ in range(4):
        party.card._tap("vibrate")
        got.append(sent[-1][1][0])
    assert got == [("b", 0), ("a", 0), ("a", 1), ("b", 0)]
    # one press, one pick: a hold and its release go to the same shocker
    party.card._mode_picked(1)
    party.card._press("vibrate")
    held = sent[-1][1]
    party.card._unpress("vibrate")
    assert sent[-1] == ("release", held)
    party._tick(("a", 1), False)
    assert party.ticked() == [("a", 0), ("b", 0)]
    party.card._stop()
    assert sent[-1][0] == "stop" and len(sent[-1][1]) == 3     # STOP stops every one


def test_grids_and_columns_follow_the_width(qapp):
    cards = [QLabel(str(i)) for i in range(3)]
    grid = CardGrid(cards)
    grid.resize(2 * CARD_MIN_W + 20, 300)
    grid.show()
    qapp.processEvents()
    assert grid._cols == 2
    grid.resize(CARD_MIN_W + 20, 300)
    qapp.processEvents()
    assert grid._cols == 1
    grid.hide()

    seen = []
    row = SideBySide(QLabel("list"), QLabel("panel"), 1000, lambda s, w: seen.append(s))
    row.resize(1200, 200)
    row.show()
    qapp.processEvents()
    row.resize(700, 200)
    qapp.processEvents()
    assert seen[-1] is True and row._stacked
    row.hide()


def test_a_card_that_goes_lets_go_of_its_hold(qapp):
    # The panel rebuilds (a toy connects, control mode): a Remote press in
    # progress must not keep their shocker running with no button left.
    card, calls = shocker_card()
    card._mode_picked(1)                                 # Remote
    card._press("vibrate")
    assert calls[-1][0] == "hold"
    card.release()
    assert calls[-1] == ("release",)
    n = len(calls)
    card.release()                                       # nothing held: nothing sent
    assert len(calls) == n


def test_a_rebuilt_card_starts_where_the_old_one_was(qapp):
    old, _ = shocker_card()
    old._mode_picked(1)                                  # Remote
    old._warn_picked(2)                                  # Mid warning
    old._dice_btn.click()                                # Random
    old._lo.setValue(5)
    old._hi.setValue(30)
    old._sliders["vibrate"].setValue(60)
    old._set_dur("shock", 1000)
    new, calls = shocker_card()
    new.restore(old.settings())
    assert new.settings() == old.settings()
    assert calls == []                                   # restoring sends nothing


def test_a_continuous_card_comes_back_quiet(qapp):
    old, _ = shocker_card()
    old._mode_picked(2)                                  # Continuous
    old._sliders["vibrate"].setValue(30)
    new, calls = shocker_card()
    new.restore(old.settings())
    assert new._sliders["vibrate"].value() == 0 and calls == []


def test_scrolling_the_page_over_a_slider_never_moves_it(qapp):
    from PySide6.QtCore import QPoint, QPointF, Qt
    from PySide6.QtGui import QWheelEvent
    card, calls = shocker_card()
    s = card._sliders["shock"]
    before = s.value()
    ev = QWheelEvent(QPointF(5, 5), QPointF(5, 5), QPoint(0, 0), QPoint(0, 120),
                     Qt.NoButton, Qt.NoModifier, Qt.NoScrollPhase, False)
    s.wheelEvent(ev)
    assert s.value() == before and not ev.isAccepted()  # the page scrolls instead
    assert calls == []


def test_building_a_card_never_opens_a_window(qapp):
    # A label shown before it had a parent opened as a window of its own:
    # a small box flashed every time a group was picked.
    from PySide6.QtCore import QEvent, QObject
    from PySide6.QtWidgets import QWidget
    from ui.views.param_cards import ParamCard, ParamCategory
    from ui.views.shock_party import ShockParty

    opened = []

    class Spy(QObject):
        def eventFilter(self, obj, ev):
            if ev.type() == QEvent.Show and isinstance(obj, QWidget) and obj.isWindow():
                opened.append(type(obj).__name__)
            return False

    spy = Spy()
    qapp.installEventFilter(spy)
    try:
        n = lambda *a, **k: None
        for big in (False, True):
            ToyCard("Edge", "Lovense Edge 2", "pink", n, n, n, big=big)
            ShockerCard("1 · Collar", "yellow", n, n, n, n, big=big, party_box=True)
            party = ShockParty("Party", "yellow", n, n, n, n, big=big)
            party.set_targets([("a", 0, "A · Collar", "cyan")])
        box = ParamCategory({"id": "c", "name": "Outfit", "color": "green", "locked": True},
                            editable=False)
        box.add_card(ParamCard({"id": "k", "param": "P", "ptype": "Bool", "kind": "toggle",
                                "label": "P", "cat": "c"}, editable=False))
        box.finalize()
        qapp.processEvents()
    finally:
        qapp.removeEventFilter(spy)
    assert opened == []


def test_a_card_is_never_squeezed_under_its_own_minimum(qapp):
    cards = [shocker_card()[0] for _ in range(2)]
    need = cards[0].wide_width()
    assert need > CARD_MIN_W                    # a shocker needs more than a toy
    grid = CardGrid(cards)
    grid.resize(2 * CARD_MIN_W + 20, 400)       # two toys would fit, two shockers don't
    grid.show()
    qapp.processEvents()
    assert grid._cols == 1
    grid.resize(2 * need + 20, 400)
    qapp.processEvents()
    assert grid._cols == 2
    assert all(c.width() >= need for c in cards)
    grid.hide()


def test_a_narrow_shocker_card_folds_its_middle_under_the_columns(qapp):
    card, _calls = shocker_card()
    wide = card.wide_width()
    assert card.minimumSizeHint().width() < wide           # it can go narrower
    card.resize(wide - 40, 500)
    card.show()
    qapp.processEvents()
    stop = card._tiles["stop"]
    assert card._compact and card._foot.indexOf(stop) >= 0   # as PiShock's Party panel
    card.resize(wide + 40, 500)
    qapp.processEvents()
    assert not card._compact and card._center.indexOf(stop) >= 0
    card.hide()


def test_cards_keep_their_own_height(qapp):
    short, tall = QLabel("short"), QLabel("tall")
    tall.setMinimumHeight(300)
    grid = CardGrid([short, tall], min_card_w=100)
    grid.resize(400, 400)
    grid.show()
    qapp.processEvents()
    assert grid._cols == 2 and short.height() < 100      # not stretched to its neighbour
    grid.hide()
