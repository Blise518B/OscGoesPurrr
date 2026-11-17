"""Control mode in its own window, headless (ui/views/friends_window.py):
Pop out moves the Friends control panel into a window of its own, big;
closing that window -- or its Back into the page -- puts the panel back
where it was; its size, place and Stay on top are remembered; it follows
whoever is picked on the page; it keeps refreshing while the main window
is out of sight; and nothing in it opens a popup (a VR overlay that
captures the window wouldn't show one)."""

import sys

import pytest
from PySide6.QtCore import QPoint, QPointF, QRect, Qt
from PySide6.QtGui import QWheelEvent
from PySide6.QtWidgets import QApplication, QPushButton, QWidget

import ui_components as uc
from ui import wheel_guard
from ui.layout_helpers import vbox
from ui.views.friends_panel import PANEL_MAX_W
from ui.views.friends_window import ON_TOP_KEY, STATE_KEY, WINDOW_TITLE
from ui.views.toy_card import ToyCard

A, B = "a" * 64, "b" * 64


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication(sys.argv[:1])


def theirs(toys=("Lush",)):
    return {"toys": [(n, 1) for n in toys], "allow_toys": True, "allow_shock": False,
            "shockers": [], "armed": False, "max_intensity": 60, "max_vibrate": 80,
            "max_pulse_ms": 5000, "max_hold_s": 10.0, "strength": 1.0, "outputs": {},
            "paused": False, "off": False, "batteries": {}}


def friend(fid, nick, their=None):
    return {"id": fid, "nick": nick, "me": False, "toys": True, "shock": True,
            "params": True, "added": 0.0, "linked": their is not None, "path": "direct",
            "rtt": 20.0, "selected": False, "theirs": their, "my_levels": {},
            "driving_me": False, "others": [], "sync": True, "my_override": set(),
            "my_patterns": {}, "my_holds": {}}


class Ctl:
    """The Friends facade, answered from a status the test sets."""

    def __init__(self, settings=None):
        self.settings = {} if settings is None else settings
        self.features = {"feature_friends": True}
        self.selected = {"kind": "friend", "id": A}
        self.web = None
        self.calls = []

    def get_friends_status(self):
        return {"available": True, "enabled": True, "running": True, "online": True,
                "error": "", "my_id": "f" * 64, "nickname": "Blise", "paused": False,
                "requests": [], "asking": [],
                "friends": [friend(A, "Mika", theirs()), friend(B, "Kiko")],
                "groups": [{"id": "g1", "name": "Us", "members": [A, B]}],
                "selected": dict(self.selected), "online_switch": True,
                "avatar_menu": {"known": True, "self": True, "friends": True},
                "elsewhere": False, "pending_invite": "", "invites": [],
                "params_on": False, "behind": None, "web": self.web}

    def get_friends_log(self):
        return []

    def get_friend_board(self, fid):
        return None

    def get_app_setting(self, key, default=None):
        return self.settings.get(key, default)

    def set_app_setting(self, key, value):
        self.settings[key] = value

    def get_feature_enabled(self, key):
        return self.features.get(key, False)

    def set_friend_levels_watch(self, peer):
        self.calls.append(("levels_watch", peer))

    def set_friend_params_watch(self, peer, yolo=False):
        self.calls.append(("params_watch", peer))

    def __getattr__(self, name):
        if name.startswith("__"):
            raise AttributeError(name)
        return lambda *a, **k: None


class App:
    """The Friends page on a stand-in main window, as the app builds it."""

    def __init__(self, qapp, settings=None):
        ui = uc.OscGoesPurrrUI.__new__(uc.OscGoesPurrrUI)
        ui.controller = Ctl(settings)
        ui.window = QWidget()
        page = QWidget()
        lay = vbox(0, 0)
        page.setLayout(lay)
        ui.views = {"Friends": page}
        ui._build_friends_view(lay)
        ui._friends_live_timer.stop()        # the test ticks by hand
        main_lay = vbox(0, 0)
        ui.window.setLayout(main_lay)
        main_lay.addWidget(page)
        ui.window.resize(1300, 900)
        ui.window.show()
        qapp.processEvents()
        self.qapp, self.ui, self.ctl = qapp, ui, ui.controller

    @property
    def card(self):
        return self.ui._panel_card

    @property
    def win(self):
        return self.ui._friends_win

    def on_page(self) -> bool:
        return self.ui._friends_right.isAncestorOf(self.card)

    def pop_out(self):
        self.ui._panel_w["popout"].click()
        self.qapp.processEvents()
        return self.win

    def pick(self, kind, sid=None):
        self.ctl.selected = {"kind": kind, "id": sid} if sid else {"kind": kind}
        self.ui.refresh_friends()

    def done(self):
        if self.win is not None:
            self.win.close()
        self.ui.window.close()
        self.qapp.processEvents()


@pytest.fixture
def app(qapp):
    made = []

    def make(settings=None):
        made.append(App(qapp, settings))
        return made[-1]
    yield make
    for a in made:
        a.done()


def buttons(widget):
    return [b.text().strip() for b in widget.findChildren(QPushButton)]


def test_pop_out_moves_the_panel_into_its_own_window_big(app):
    a = app()
    assert a.on_page() and "Pop out" in buttons(a.card)
    win = a.pop_out()
    assert win.isVisible() and win.holds(a.card) and a.card.window() is win
    assert not a.on_page()
    assert win.windowTitle() == WINDOW_TITLE
    assert not win.testAttribute(Qt.WA_QuitOnClose)     # closing it never ends the app
    # big, as control mode: the panel's card and its toy cards
    assert a.ui._friends_big and a.card.property("big") == "true"
    toys = a.card.findChildren(ToyCard)
    assert toys and all(t._big for t in toys)
    # its header has neither Control mode nor Pop out: the window's bar has
    # Back into the page
    assert "control" not in a.ui._panel_w and "popout" not in a.ui._panel_w
    assert not {"Control mode", "Pop out"} & set(buttons(a.card))
    # where the panel was, the page says where it went
    away = a.ui._friends_away
    assert away.isVisible() and a.ui._friends_right.isAncestorOf(away)


@pytest.mark.parametrize("how", ["close", "bar", "page"])
def test_closing_the_window_puts_the_panel_back(app, how):
    a = app()
    rl = a.ui._friends_right.layout()
    where = rl.indexOf(a.card)
    win = a.pop_out()
    {"close": win.close, "bar": win.back.click,
     "page": a.ui._friends_away.back_btn.click}[how]()
    a.qapp.processEvents()
    assert not win.isVisible()
    assert a.on_page() and rl.indexOf(a.card) == where and a.card.isVisible()
    assert not a.ui._friends_popped and not a.ui._friends_big
    assert a.card.property("big") == "false"
    assert not a.ui._friends_away.isVisible()
    assert {"Control mode", "Pop out"} <= set(buttons(a.card))
    assert not any(t._big for t in a.card.findChildren(ToyCard))
    # ...and it pops out again
    assert a.pop_out() is win and win.holds(a.card)


def test_show_it_brings_the_window_back(app):
    a = app()
    win = a.pop_out()
    win.showMinimized()
    a.qapp.processEvents()
    a.ui._friends_away.show_btn.click()
    a.qapp.processEvents()
    assert win.isVisible() and not win.isMinimized()
    a.ui._friends_pop_out()                     # already out: just to the front
    assert win.holds(a.card)


def test_size_place_and_stay_on_top_are_remembered(app):
    settings = {}
    a = app(settings)
    a.pick("friend", B)              # offline: a small panel, for the test's small screen
    win = a.pop_out()
    win.setGeometry(60, 70, 460, 380)
    a.qapp.processEvents()
    where = win.geometry()
    assert where == QRect(60, 70, 460, 380)
    win.on_top.setChecked(True)
    a.qapp.processEvents()
    assert settings[ON_TOP_KEY] is True
    assert win.is_on_top() and win.isVisible()          # Qt hides it to change that
    assert win.geometry() == where                      # ...and it comes back as it was
    win.close()
    assert settings[STATE_KEY]

    b = app(settings)                                   # the next launch
    b.pick("friend", B)
    again = b.pop_out()
    assert again.geometry() == where
    assert again.is_on_top() and again.on_top.isChecked()
    again.on_top.setChecked(False)
    assert settings[ON_TOP_KEY] is False and not again.is_on_top()


def test_a_move_is_saved_once_it_rests(app):
    settings = {}
    a = app(settings)
    win = a.pop_out()
    settings.pop(STATE_KEY, None)
    win.move(210, 220)
    win._save_timer.timeout.emit()                      # it rested
    assert settings.get(STATE_KEY)


def test_it_follows_the_pick(app):
    a = app()
    win = a.pop_out()
    assert a.ui._panel_w["title"].text() == "Mika"
    a.pick("friend", B)
    assert a.ui._panel_w["title"].text() == "Kiko" and win.holds(a.card)
    a.pick("group", "g1")
    assert a.ui._panel_w["kind"] == "group" and a.ui._panel_w["title"].text() == "Us"
    assert "members" not in a.ui._panel_w               # control mode's group: just controls
    a.pick("none")
    assert "Friends page" in " ".join(lbl.text() for lbl in a.card.findChildren(
        type(a.ui._friends_intro)))


def test_it_keeps_going_while_the_main_window_is_out_of_sight(app):
    a = app()
    win = a.pop_out()
    a.ui.window.hide()                                  # in the tray
    a.qapp.processEvents()
    a.ctl.calls.clear()
    a.ctl.selected = {"kind": "friend", "id": B}
    a.ui._friends_tick()
    assert a.ui._panel_w["title"].text() == "Kiko"     # followed with the page unseen
    a.ctl.selected = {"kind": "friend", "id": A}
    a.ui._friends_tick()
    assert ("levels_watch", A) in a.ctl.calls          # Mika's live levels: you see them
    # back into the page with the main window still away: nobody watches
    win.close()
    a.ui._friends_tick()
    assert a.ctl.calls[-1] == ("levels_watch", None)


def test_from_control_mode_the_page_comes_back(app):
    a = app()
    a.ui._set_friends_control(True)
    assert a.ui._friends_list_card.isHidden()
    win = a.pop_out()
    assert not a.ui._friends_list_card.isHidden() and not a.ui._friends_log_card.isHidden()
    assert a.ui._friends_right.maximumWidth() == PANEL_MAX_W
    a.ui._set_friends_control(False)                    # Esc on the page: the window stays
    assert a.ui._friends_big and win.holds(a.card)
    win.close()
    assert not a.ui._friends_big and a.on_page()


def test_nothing_in_the_window_opens_a_popup(app):
    a = app()
    assert a.ui._panel_w["title"].contextMenuPolicy() == Qt.CustomContextMenu
    a.pop_out()
    assert a.ui._panel_w["title"].contextMenuPolicy() != Qt.CustomContextMenu
    # the web remote's New link / Remove ask in a window of their own: page only
    a.ctl.web = {"on": True, "toys": True, "shock": False, "params": False, "guests": [],
                 "driving": False}
    a.pick("web")
    assert a.ui._panel_w["kind"] == "web"
    assert "Copy link" in buttons(a.card)
    assert not {"New link…", "Remove web remote…"} & set(buttons(a.card))
    a.win.close()
    assert {"New link…", "Remove web remote…"} <= set(buttons(a.card))


def test_switching_friends_off_closes_the_window(app):
    a = app()
    win = a.pop_out()
    a.ctl.features["feature_friends"] = False
    a.ui._friends_tick()
    assert not win.isVisible() and a.on_page() and not a.ui._friends_popped


def test_the_wheel_never_changes_a_setting_in_there(app):
    qapp = QApplication.instance()
    had_guard = wheel_guard._guard is not None
    wheel_guard.install(qapp)
    try:
        a = app()
        a.pop_out()
        slider = a.ui._panel_w["strength"].slider
        before = slider.value()
        for _ in range(3):
            QApplication.sendEvent(slider, QWheelEvent(
                QPointF(5, 5), QPointF(slider.mapToGlobal(QPoint(5, 5))), QPoint(0, 0),
                QPoint(0, -120), Qt.NoButton, Qt.NoModifier, Qt.NoScrollPhase, False))
        a.qapp.processEvents()
        assert slider.value() == before
    finally:
        # The guard is app-wide: leave the app as this test found it, or
        # every later test's wheel events meet it too.
        if not had_guard and wheel_guard._guard is not None:
            qapp.removeEventFilter(wheel_guard._guard)
            wheel_guard._guard = None


def test_the_panel_is_never_cut_off(app):
    """The window is at least as wide as the big panel inside it -- never
    clipped, never scrolled sideways (a VR stick scrolls up and down)."""
    a = app()
    win = a.pop_out()
    win.resize(300, 500)                                # narrower than it can be
    a.qapp.processEvents()
    a.qapp.processEvents()
    need = win._body.minimumSizeHint().width()
    assert win.minimumWidth() > need and win.scroll.viewport().width() >= need
    assert not win.scroll.horizontalScrollBar().isVisible()
