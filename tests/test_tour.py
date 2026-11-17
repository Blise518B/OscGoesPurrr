"""The guided tour (ui/tour.py; its steps ui/tour_steps.py, the window's side
ui/views/tour.py, the launch hook controllers/tour_facade.py) -- row 20 of
the friends' review (2026-11-14).

What it promises: the first launch walked through for real, on help mode's
drawing -- a toy connects, it lights up on Home, its card opens, its Input,
Select Zones ("your SPS sources"), a zone picked, the four chips, Test,
total strength, the avatar menu, then a short branch for each feature
picked. Each step moves on when the real thing happens and says what it
waits for; the lit control takes its click, nothing else on the window
does; the tour never changes a setting by itself; any step can be skipped,
the tour ended (End tour, Esc) and run again (Help, Getting started); with
no toy it says what to check and waits, or Continue without a toy leaves
the toy's steps out. A new install gets it after "What are you here for?",
an older one is offered it once.

The end-to-end run is the real Home and Toys pages (the mixins, as in
test_home_view) with a fake toy connecting part-way, a sidebar with the
pages and total strength, and stand-in pages for Settings and Shockers
(their real controls are checked against the steps at the bottom).
"""

import sys

import pytest

from PySide6.QtCore import QEvent, QPoint, Qt
from PySide6.QtGui import QHelpEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import (QApplication, QFrame, QHBoxLayout, QLabel, QPushButton, QSlider,
                               QStackedWidget, QVBoxLayout, QWidget)

import interests
from controllers.tour_facade import OFFERED_KEY, TourFacade
from settings.app import DEFAULT_APP_SETTINGS
from ui import page_steps, tour_steps
from ui.help_mode import find_control, visible_rect
from ui.tooltips import explain
from ui.tour import NOT_ON_SCREEN, REFIND_TICKS, Tour
from ui.views.dashboard import DashboardMixin
from ui.views.device_frame import DeviceFrameMixin
from ui.views.help import HelpMixin
from ui.views.home import HomeMixin
from ui.views.interests import InterestsMixin
from ui.views.toys import ToysMixin
from ui.views.tour import TAKE_TOUR_TITLE, TourMixin

from test_toys_page import ToysController


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication(sys.argv[:1])


def pump(ms: int = 0) -> None:
    QApplication.processEvents()
    if ms:
        QTest.qWait(ms)


# ----------------------------------------------------------------------
# The steps
# ----------------------------------------------------------------------

class TestSteps:
    def test_every_step_says_what_where_and_what_it_waits_for(self):
        keys = [s.key for s in tour_steps.TOUR]
        assert len(keys) == len(set(keys))
        for s in tour_steps.TOUR:
            assert s.label and s.hint and s.targets and s.waiting, s.key
            assert len(s.label) <= 36, s.label                  # a few words
            assert s.waits in tour_steps.WAITS, s.key
            assert s.scope in tour_steps.SCOPES, s.key

    def test_it_follows_the_asked_path(self):
        """1 connect, 2 the toy lit on Home, 3 open it, Input, Select Zones, a
        zone, 4 the chips, 5 Test then strength, 6 the avatar menu."""
        assert [s.key for s in tour_steps.TOUR[:9]] == [
            "connect", "toy", "input", "zones", "pick", "chips", "test", "strength", "menu"]
        assert tour_steps.step("toy").page == "Home"
        assert tour_steps.step("zones").label == "Select Zones: your SPS sources"
        assert tour_steps.TOUR[-1].key == "done"

    def test_where_a_page_step_says_it_the_tour_says_the_same(self):
        """One story: Help's walk-through, the gallery and the tour."""
        pairs = {"chips": ("Home", "Choose who it feels"),
                 "strength": ("Home", "One strength for all"),
                 "shockers": ("Shockers", "Plug in your hub"),
                 "arm": ("Shockers", "Arm shocks"),
                 "separate": ("Shockers", "Separate limits for friends"),
                 "suits": ("Suits", "Watch every touch land"),
                 "psvr2": ("PSVR2", "Start SteamVR with the toolkit"),
                 "friends_add": ("Friends", "Add a friend"),
                 "remote": ("My Avatar Remote", "Wear your avatar")}
        for key, (page, label) in pairs.items():
            mine = tour_steps.step(key)
            theirs = next(s for s in page_steps.for_page(page) if s.label == label)
            assert (mine.label, mine.hint) == (theirs.label, theirs.hint), key
            assert theirs.target in mine.targets, key

    def test_a_branch_for_each_feature_with_a_page(self):
        branches = {s.branch: s for s in tour_steps.TOUR if s.branch}
        assert set(branches) == {"Shockers", "Suits", "PSVR2", "Friends", "Avatar Remote"}
        picked = set(interests.features())
        for s in tour_steps.TOUR:
            assert s.needs in ("", "toy", "suits") or s.needs in picked, s.key

    def test_the_shockers_branch_asks_before_arming_and_shows_the_limits(self):
        arm = tour_steps.step("arm")
        assert arm.waits == "next"           # the tour never arms; the switch asks first
        assert "Arm shocks?" in arm.targets  # its question, in the switch's place
        assert tour_steps.step("limits").targets == ("Limits",)

    def test_with_no_toy_it_says_what_to_check(self):
        s = tour_steps.step("connect")
        assert s.button == "Continue without a toy"
        for word in ("switched on", "phone app", "Bluetooth", "Intiface"):
            assert word in s.more, word


# ----------------------------------------------------------------------
# The engine on a small window
# ----------------------------------------------------------------------

STEPS = (
    tour_steps.TourStep("one", "A", "Press it", "It does a thing.", ("Press it",), "click",
                        "Waiting for a click on Press it"),
    tour_steps.TourStep("two", "B", "Look here", "Over there.", ("Look here",), "next",
                        "Next moves on", button="Next"),
    tour_steps.TourStep("gone", "A", "Nowhere", "Not on this page.", ("Nowhere",), "next",
                        "Next moves on", button="Next"),
    tour_steps.TourStep("end", "", "That's it", "Bye.", ("Side thing",), "next",
                        "Finish ends it", button="Finish"),
)


class SmallHost:
    """A sidebar (two page buttons, a thing) and two pages."""

    def __init__(self):
        self.root = QWidget()
        lay = QHBoxLayout(self.root)
        side = QWidget()
        side_lay = QVBoxLayout(side)
        self.nav = {n: QPushButton(n) for n in ("A", "B")}
        for btn in self.nav.values():
            side_lay.addWidget(btn)
        self.side_thing = QPushButton("Side thing")
        side_lay.addWidget(self.side_thing)
        lay.addWidget(side)
        content = QWidget()
        content_lay = QVBoxLayout(content)
        self.stack = QStackedWidget()
        content_lay.addWidget(self.stack)
        lay.addWidget(content, 1)
        self.pages = {}
        self.clicks = {"press": 0, "other": 0}
        for name in ("A", "B"):
            page = QWidget()
            page_lay = QVBoxLayout(page)
            self.pages[name] = page
            self.stack.addWidget(page)
            self.nav[name].clicked.connect(lambda _=False, p=page: self.stack.setCurrentWidget(p))
            if name == "A":
                self.press = QPushButton("Press it")
                explain(self.press, "Press it", "Does a thing.")
                self.press.clicked.connect(lambda: self._count("press"))
                self.other = QPushButton("Something else")
                self.other.clicked.connect(lambda: self._count("other"))
                page_lay.addWidget(self.press)
                page_lay.addWidget(self.other)
            else:
                self.look = QLabel("Look here")
                page_lay.addWidget(self.look)
        self.finished = []
        self.tour = Tour(self.root, self.stack, self, steps=STEPS)
        self.root.setAttribute(Qt.WA_DontShowOnScreen, True)
        self.root.resize(900, 600)
        self.root.show()
        pump()

    def _count(self, what):
        self.clicks[what] += 1

    # the host's answers
    def tour_page(self, name):
        return self.pages.get(name)

    def tour_nav(self, name):
        return self.nav.get(name)

    def tour_applies(self, step, no_toy):
        return True

    def tour_scopes(self, step):
        return [self.pages[step.page]] if step.page else [self.root]

    def tour_fill(self, target):
        return target

    def tour_waiter(self, step):
        return lambda: False

    def tour_passthrough(self, w):
        return any(w is b for b in self.nav.values())

    def tour_finished(self, how):
        self.finished.append(how)

    def start(self):
        self.tour.start()
        self.tour._timer.stop()          # the test looks by hand
        pump()


@pytest.fixture
def small(qapp):
    h = SmallHost()
    yield h
    h.tour.stop()
    h.root.close()


class TestEngine:
    def test_the_strip_goes_above_the_pages_and_leaves_with_it(self, small):
        small.start()
        lay = small.stack.parentWidget().layout()
        assert small.tour.strip.isVisible() and small.tour.overlay.isVisible()
        assert lay.indexOf(small.tour.strip) == lay.indexOf(small.stack) - 1
        small.tour.end()
        assert not small.tour.strip.isVisible() and not small.tour.overlay.isVisible()
        assert small.finished == ["ended"]

    def test_it_lights_the_control_and_says_what_it_waits_for(self, small):
        small.start()
        assert small.tour.lit() == [small.press]
        assert small.tour._rect == visible_rect(small.press, small.root)
        title, hint, _more, waiting = small.tour.bubble_lines()
        assert (title, hint, waiting) == ("Press it", "It does a thing.",
                                          "Waiting for a click on Press it")
        assert small.tour.progress() == (1, 4)
        assert "1 of 4" in small.tour.strip.title.where

    def test_only_the_lit_control_takes_a_click_and_it_moves_on(self, small):
        small.start()
        QTest.mouseClick(small.other, Qt.LeftButton)
        assert small.clicks["other"] == 0                     # swallowed
        QTest.mouseClick(small.press, Qt.LeftButton)
        assert small.clicks["press"] == 1                     # let through
        small.tour._tick()
        assert small.tour.step.key == "two"

    def test_a_step_on_another_page_rings_its_sidebar_entry_first(self, small):
        small.start()
        small.tour.next()                                     # skip: to "two", on B
        assert small.tour.phase == "nav" and small.tour.lit() == [small.nav["B"]]
        assert small.tour.bubble_lines()[0] == "Open B"
        assert small.tour.bubble_lines()[3] == "Waiting for B to open"
        QTest.mouseClick(small.nav["B"], Qt.LeftButton)       # the sidebar keeps its clicks
        small.tour._tick()
        assert small.tour.phase == "here" and small.tour.lit() == [small.look]

    def test_a_control_not_on_screen_says_so(self, small):
        small.start()
        small.tour._go(2)                                     # "gone", on A
        small.tour._tick()
        assert small.tour.lit() is None
        assert NOT_ON_SCREEN in small.tour.bubble_lines()[2]

    def test_skip_any_step_finish_at_the_end(self, small):
        small.start()
        for _ in range(3):
            small.tour.next()
        assert small.tour.step.key == "end"
        assert small.tour.strip.main.text() == "Finish"
        QTest.mouseClick(small.tour.strip.main, Qt.LeftButton)   # the strip keeps its clicks
        assert not small.tour.active and small.finished == ["done"]

    def test_escape_ends_it_and_tooltips_wait(self, small):
        small.start()
        tip = QHelpEvent(QEvent.ToolTip, QPoint(5, 5), small.other.mapToGlobal(QPoint(5, 5)))
        assert small.tour.eventFilter(small.other, tip) is True
        QTest.keyClick(small.other, Qt.Key_Escape)
        assert not small.tour.active and small.finished == ["ended"]
        assert small.tour.eventFilter(small.other, tip) is False
        QTest.mouseClick(small.other, Qt.LeftButton)          # clicks work again
        assert small.clicks["other"] == 1


# ----------------------------------------------------------------------
# End to end: Home and Toys, a toy connecting
# ----------------------------------------------------------------------

ALL_FEATURES = ("feature_intiface", "feature_pishock", "feature_friends", "feature_params",
                "feature_psvr2", "feature_bhaptics", "feature_owo", "feature_trackers",
                "feature_statistics", "feature_osc_inspector")


class Ctl(ToysController):
    """Home's and the Toys page's fake controller; it keeps every write, so
    a test can tell the tour never wrote one itself."""

    def __init__(self, features=("feature_intiface",)):
        super().__init__({}, connected=())
        self.features = {k: k in features for k in ALL_FEATURES}
        self.writes = []
        self.skipped = 0

    def get_feature_enabled(self, key):
        return bool(self.features.get(key, False))

    def get_detected_zones(self):
        return {"Orifices": ["Pussy"], "Penetrators": [], "Touch": ["Chest"]}

    def get_sps_source_names_flat(self):
        return []

    def update_device_config(self, device, key, value):
        self.writes.append((device, key, value))
        super().update_device_config(device, key, value)

    def set_app_setting(self, key, value):
        self.writes.append(("app", key, value))
        super().set_app_setting(key, value)

    def skip_interests(self):
        self.skipped += 1

    def connect_toy(self, name, motors=1):
        self.profiles[name] = {"motor_count": motors}
        self.connected.add(name)


class Host(TourMixin, HelpMixin, InterestsMixin, HomeMixin, ToysMixin, DeviceFrameMixin,
           DashboardMixin):
    """OscGoesPurrrUI in small: a sidebar (pages, total strength), the real
    Home and Toys pages, Settings and Shockers stand-ins, the real Help card."""

    PAGES = ("Home", "Toys", "Shockers", "Settings", "Help")

    def __init__(self, controller):
        self.controller = controller
        self.window = QWidget()
        self._root_widget = self.window
        self.dialog_parent = None
        self.intiface_sidebar_section = None
        self.device_ui_frames, self.stored_device_frames = {}, {}
        self.unified_devices_layout = self.home_list_layout = None
        lay = QHBoxLayout(self.window)
        side = QWidget()
        side_lay = QVBoxLayout(side)
        self.sidebar_frame = side
        self.nav_buttons = {}
        for name in self.PAGES:
            btn = QPushButton(name)
            explain(btn, name, f"The {name} page.")
            btn.clicked.connect(lambda _=False, n=name: self.select_view(n))
            side_lay.addWidget(btn)
            self.nav_buttons[name] = btn
        # as the real sidebar: a heading and the slider, explained once
        strength = QWidget()
        strength_lay = QVBoxLayout(strength)
        self.strength_head = QLabel("Total output strength")
        self.sidebar_strength_slider = QSlider(Qt.Horizontal)
        self.sidebar_strength_slider.setRange(0, 1000)
        self.sidebar_strength_slider.setValue(700)
        explain((self.strength_head, self.sidebar_strength_slider), "Total output strength",
                "One multiplier.")
        strength_lay.addWidget(self.strength_head)
        strength_lay.addWidget(self.sidebar_strength_slider)
        side_lay.addWidget(strength)
        lay.addWidget(side)
        content = QWidget()
        content_lay = QVBoxLayout(content)
        self.main_stack = QStackedWidget()
        content_lay.addWidget(self.main_stack)
        lay.addWidget(content, 1)
        self.views = {}
        for name in self.PAGES:
            page = QWidget()
            self.views[name] = page
            self.main_stack.addWidget(page)
        self._build_home_view(QVBoxLayout(self.views["Home"]))
        self._build_toys_view(QVBoxLayout(self.views["Toys"]))
        self.prefabs = self._stand_in("Settings", [("Get the menu prefabs", QPushButton)])
        (self.hub_connect, self.arm, self.armed, self.limits,
         self.separate) = self._stand_in("Shockers", [
            ("Connect", QPushButton), ("Arm shocks", QPushButton),
            ("Shocks armed or not", QLabel), ("Limits", QFrame),
            ("Separate limits for friends", QPushButton)])
        self._build_help_tour(QVBoxLayout(self.views["Help"]))
        self.build_stored_devices_ui()
        self.update_stored_devices_ui()
        self.window.setAttribute(Qt.WA_DontShowOnScreen, True)
        self.window.resize(1300, 1000)
        self.window.show()
        self.select_view("Home")
        pump()

    def _stand_in(self, page, controls):
        lay = QVBoxLayout(self.views[page])
        made = []
        for title, kind in controls:
            w = kind(title) if kind is not QFrame else kind()
            if kind is QFrame:
                w.setMinimumSize(200, 40)
            explain(w, title, f"{title}, explained.")
            lay.addWidget(w)
            made.append(w)
        lay.addStretch(1)
        return made if len(made) > 1 else made[0]

    def select_view(self, name):
        self.main_stack.setCurrentWidget(self.views[name])
        if name == "Home":
            self._refresh_home_dynamic()

    def _repolish(self, widget):
        widget.style().unpolish(widget)
        widget.style().polish(widget)

    # ---- driving it ------------------------------------------------------
    @property
    def tour(self):
        return self._tour_obj

    def look(self, ms=0):
        """What the tour's 60 ms timer does for a few beats (the test ticks
        by hand)."""
        pump(ms)
        for _ in range(REFIND_TICKS + 2):
            self.tour._tick()
            pump()

    def lit(self):
        return self.tour.lit() or []

    def key(self):
        return self.tour.step.key if self.tour.step is not None else None

    def toy(self, name="Lush"):
        return self.device_ui_frames[name]

    def toy_connects(self, name="Lush", motors=1):
        self.controller.connect_toy(name, motors)
        self.build_stored_devices_ui()
        self.update_stored_devices_ui()
        self._refresh_home_dynamic()


@pytest.fixture
def make_host(qapp):
    made = []

    def make(features=("feature_intiface",)):
        h = Host(Ctl(features))
        made.append(h)
        return h
    yield make
    for h in made:
        tour = getattr(h, "_tour_obj", None)
        if tour is not None:
            tour.stop()
        h.window.close()
    pump()


def start(host, how="getting started"):
    if how == "getting started":
        QTest.mouseClick(host._setup_tour_btn, Qt.LeftButton)
    else:
        host.start_tour()
    host.tour._timer.stop()              # the test looks by hand
    host.look()


class TestEndToEnd:
    def test_from_switching_the_toy_on_to_finish(self, make_host):
        host = make_host(("feature_intiface", "feature_pishock"))
        ctl = host.controller
        start(host)
        tour = host.tour
        assert tour.active and host.key() == "connect"
        # 1. no toy yet: it lights Getting started's step and waits
        assert host.lit()[0].text() == "Switch your toy on"
        assert host.tour.bubble_lines()[3] == "Waiting for a toy to connect"
        for _ in range(5):
            host.look()
        assert host.key() == "connect"
        QTest.mouseClick(host._test_all_button, Qt.LeftButton)     # not lit: nothing
        assert ctl.purr_checks == 0

        # 2. a toy connects: it is lit on Home
        host.toy_connects("Lush")
        host.look()
        assert host.key() == "toy"
        row = host.toy()["home"]
        assert host.lit() == [row["bar"]]

        # 3. a click on it opens its card on the Toys page...
        QTest.mouseClick(row["name_label"], Qt.LeftButton)
        host.look(50)
        assert host.main_stack.currentWidget() is host.views["Toys"]
        assert host.toy()["body"].isVisible()
        assert host.key() == "input"
        card = host.toy()["frame"]
        # ... its chain, folded as the card opens (2026-11-16), lit first ...
        (chain,) = host.lit()
        assert card.isAncestorOf(chain)
        assert chain.toolTip().startswith(f"<b>{tour_steps.CHAIN}</b>")
        QTest.mouseClick(chain, Qt.LeftButton)
        host.look(400)
        host.look(400)
        assert host.key() == "input"
        (input_card,) = host.lit()
        assert card.isAncestorOf(input_card) and input_card.toolTip().startswith("<b>Input</b>")

        # ... its Input ...
        QTest.mouseClick(input_card, Qt.LeftButton)
        host.look(400)
        assert host.key() == "zones"
        (zone_btn,) = host.lit()
        assert zone_btn.text().startswith("Select Zones")

        # ... Select Zones: your SPS sources ...
        QTest.mouseClick(zone_btn, Qt.LeftButton)
        host.look(50)
        assert host.key() == "pick"
        (panel,) = host.lit()
        assert panel.objectName() == "zonePanel" and panel.isVisible()

        # ... and a zone picked
        chest = next(w for w in panel.findChildren(QWidget)
                     if hasattr(w, "isChecked") and w.text() == "Chest")
        QTest.mouseClick(chest, Qt.LeftButton)
        host.look()
        assert any(k.endswith("zones") and "Chest" in v for _d, k, v in ctl.writes)
        assert host.key() == "chips"

        # 4. the four chips
        chips = host.toy()["contact_chips"]
        assert set(host.lit()) == set(chips.values())
        QTest.mouseClick(next(iter(chips.values())), Qt.LeftButton)
        host.look()
        assert host.key() == "test"

        # 5. Test, then total strength
        assert host.lit() == [host.toy()["test_button"]]
        QTest.mouseClick(host.toy()["test_button"], Qt.LeftButton)
        host.look()
        assert ctl.tested == ["Lush"]
        assert host.key() == "strength"
        # the heading and its slider light as one, and the slider takes the click
        assert host.lit() == [host.strength_head, host.sidebar_strength_slider]
        slider = host.sidebar_strength_slider
        QTest.mouseClick(slider, Qt.LeftButton, Qt.NoModifier,
                         QPoint(slider.width() - 3, slider.height() // 2))
        host.look()
        assert slider.value() != 700

        # 6. the avatar menu, on Settings: its sidebar entry first
        assert host.key() == "menu"
        assert tour.phase == "nav" and host.lit() == [host.nav_buttons["Settings"]]
        QTest.mouseClick(host.nav_buttons["Settings"], Qt.LeftButton)
        host.look()
        assert host.lit() == [host.prefabs]
        assert tour.strip.main.text() == "Next"
        QTest.mouseClick(tour.strip.main, Qt.LeftButton)
        host.look()

        # the Shockers branch (picked): the hub, arming (it asks first), the limits
        assert host.key() == "shockers"
        QTest.mouseClick(host.nav_buttons["Shockers"], Qt.LeftButton)
        host.look()
        assert host.lit() == [host.hub_connect]
        tour.next()
        host.look()
        assert host.key() == "arm" and host.lit() == [host.arm, host.armed]
        tour.next()
        host.look()
        assert host.key() == "limits" and host.lit() == [host.limits]
        tour.next()
        host.look()
        assert host.key() == "separate" and host.lit() == [host.separate]
        tour.next()
        host.look()

        # Friends, the avatar remote, suits, PSVR2: not picked, not shown
        assert host.key() == "done"
        assert host.lit() == [host.nav_buttons["Help"]]
        assert tour.strip.main.text() == "Finish"
        QTest.mouseClick(tour.strip.main, Qt.LeftButton)
        assert not tour.active and not tour.strip.isVisible()

    def test_it_never_changes_a_setting_by_itself(self, make_host):
        host = make_host(("feature_intiface", "feature_pishock", "feature_friends"))
        ctl = host.controller
        start(host)
        host.toy_connects("Lush")
        for _ in range(3):
            for _ in range(4):
                host.look()
            host.tour.next()                  # skipping through every step
        while host.tour.active:
            host.look()
            host.tour.next()
        assert ctl.writes == []
        assert host.sidebar_strength_slider.value() == 700

    def test_a_toy_already_connected_skips_to_it(self, make_host):
        """Run again with a toy on: what already happened is done."""
        host = make_host()
        host.toy_connects("Lush")
        start(host)
        assert host.key() == "toy"
        assert host.lit() == [host.toy()["home"]["bar"]]

    def test_no_toy_continue_without_one_leaves_the_toys_steps_out(self, make_host):
        host = make_host()
        start(host)
        tour = host.tour
        assert tour.strip.main.text() == "Continue without a toy"
        _t, _h, more, _w = tour.bubble_lines()
        assert "Bluetooth" in more and "Intiface" in more
        QTest.mouseClick(tour.strip.main, Qt.LeftButton)
        host.look()
        assert tour.no_toy and host.key() == "strength"
        assert tour.progress() == (2, 4)          # after connect: strength, the menu, the end
        host.toy_connects("Lush")                 # a toy now changes nothing
        host.look()
        assert host.key() == "strength"

    def test_the_tour_with_toys_switched_off(self, make_host):
        host = make_host(("feature_friends",))
        start(host)
        assert host.key() == "menu"

    def test_skip_any_step_end_and_run_it_again_from_help(self, make_host):
        host = make_host()
        start(host)
        tour = host.tour
        assert tour.strip.main.text() == "Continue without a toy"
        host.toy_connects("Lush")
        host.look()
        assert host.key() == "toy" and tour.strip.main.text() == "Skip this step"
        QTest.mouseClick(tour.strip.main, Qt.LeftButton)
        host.look()
        assert host.key() == "input"
        QTest.mouseClick(tour.strip.end, Qt.LeftButton)
        assert not tour.active
        # Help's Take the tour starts it again, from the start
        host.select_view("Help")
        pump()
        btn = find_control([host.views["Help"]], TAKE_TOUR_TITLE)
        assert btn is not None
        QTest.mouseClick(btn, Qt.LeftButton)
        tour._timer.stop()
        host.look()
        assert tour.active and host.key() == "toy"
        assert host.main_stack.currentWidget() is host.views["Home"]

    def test_take_the_tour_while_it_runs_is_just_another_unlit_click(self, make_host):
        host = make_host()
        start(host)
        host.toy_connects("Lush")
        host.look()
        assert host.key() == "toy"
        QTest.mouseClick(host._setup_tour_btn, Qt.LeftButton)
        assert host.key() == "toy"

    def test_help_mode_and_the_tour_take_turns(self, make_host):
        host = make_host()
        start(host)
        host.toggle_help_mode()
        assert host._help_mode.active and not host.tour.active
        host.start_tour()
        assert host.tour.active and not host._help_mode.active
        host.tour.stop()

    def test_the_toy_steps_follow_the_toy_that_connected(self, make_host):
        """Two remembered toys, one connects: that one is lit."""
        host = make_host()
        host.controller.profiles["Edge"] = {"motor_count": 2}
        host.build_stored_devices_ui()
        host.update_stored_devices_ui()
        start(host)
        assert host.key() == "connect"
        host.toy_connects("Lush")
        host.look()
        assert host.lit() == [host.toy("Lush")["home"]["bar"]]


class TestStartingIt:
    def test_a_new_install_gets_it_once_the_question_closes(self, make_host):
        host = make_host()
        host.show_interests([("WHAT YOU HAVE", [("feature_intiface", "Toys", "hint", True)])],
                            True)
        host.start_tour()                         # the facade, while the question is up
        assert getattr(host, "_tour_obj", None) is None and host._tour_waiting
        host._interests_dialog.reject()           # Skip
        pump(20)
        assert host.tour.active and host.key() == "connect"
        host.tour.stop()

    def test_an_older_install_is_offered_it_in_the_window(self, make_host):
        host = make_host()
        host.offer_tour()
        bar = host._tour_invite
        lay = host.main_stack.parentWidget().layout()
        assert bar.isVisible() and lay.indexOf(bar) == lay.indexOf(host.main_stack) - 1
        assert bar.isWindow() is False            # inside the window, never a popup
        QTest.mouseClick(bar.dismiss, Qt.LeftButton)
        assert not bar.isVisible() and getattr(host, "_tour_obj", None) is None
        host.offer_tour()
        QTest.mouseClick(bar.take, Qt.LeftButton)
        assert not bar.isVisible() and host.tour.active
        host.tour.stop()

    def test_getting_started_and_help_both_offer_it(self, make_host):
        host = make_host()
        assert host._setup_tour_btn.text() == TAKE_TOUR_TITLE
        assert host._setup_card.isAncestorOf(host._setup_tour_btn)
        host.select_view("Help")
        pump()
        assert find_control([host.views["Help"]], TAKE_TOUR_TITLE) is not None


class _App(TourFacade):
    class _Settings:
        def __init__(self, fresh):
            self.created_fresh = fresh

    class _MM:
        def __init__(self, fresh):
            self.app_settings = _App._Settings(fresh)

    class _UI:
        def __init__(self):
            self.calls = []

        def start_tour(self):
            self.calls.append("start")

        def offer_tour(self):
            self.calls.append("offer")

    def __init__(self, fresh, offered=None):
        self.mode_manager = self._MM(fresh)
        self.settings = {} if offered is None else {OFFERED_KEY: offered}
        self.ui = self._UI()

    def get_app_setting(self, key, default=None):
        return self.settings.get(key, default)

    def set_app_setting(self, key, value):
        self.settings[key] = value


class TestAtLaunch:
    def test_a_new_install_starts_it(self):
        app = _App(fresh=True)
        assert app.tour_on_launch() == "start"
        assert app.ui.calls == ["start"] and app.settings[OFFERED_KEY] is True

    def test_an_older_install_is_offered_it_once(self):
        app = _App(fresh=False)
        assert app.tour_on_launch() == "offer"
        assert app.ui.calls == ["offer"]
        assert app.tour_on_launch() == ""         # never again by itself
        assert app.ui.calls == ["offer"]

    def test_never_again_once_it_was(self):
        app = _App(fresh=True, offered=True)
        assert app.tour_on_launch() == "" and app.ui.calls == []

    def test_the_setting_starts_unoffered(self):
        assert DEFAULT_APP_SETTINGS[OFFERED_KEY] is False

    def test_main_hands_it_out_after_the_question_and_whats_new(self):
        import inspect
        import main
        src = inspect.getsource(main.OscGoesPurrrApp.run) if hasattr(
            main.OscGoesPurrrApp, "run") else inspect.getsource(main)
        at = src.index("self.tour_on_launch()")
        assert src.index("self.interests_on_launch()") < at
        assert src.index("self.whats_new_on_launch()") < at
        assert issubclass(main.OscGoesPurrrApp, TourFacade)


# ----------------------------------------------------------------------
# The steps' controls on the real pages (a test fails when one is gone)
# ----------------------------------------------------------------------

def _found(scopes, step):
    for target in step.targets:
        names = (target,) if isinstance(target, str) else target
        got = [find_control(scopes, n) for n in names]
        if None not in got:
            return got
    return None


class TestRealPages:
    def test_settings_has_the_menu_prefabs(self, qapp):
        from ui.views import avatar_menu
        card = avatar_menu.AvatarMenuCard(lambda: {}, lambda w, t, x: explain(w, t, x))
        card.show()
        try:
            pump()
            assert _found([card], tour_steps.step("menu")) is not None
        finally:
            card.close()

    def test_the_shockers_page_has_its_steps(self, qapp):
        import test_pishock_page
        ui, root = test_pishock_page.page(qapp)
        root.resize(1100, 1600)
        root.show()
        try:
            pump()
            for key in ("shockers", "arm", "limits", "separate"):
                assert _found([root], tour_steps.step(key)) is not None, key
        finally:
            root.close()

    def test_the_friends_page_has_its_steps(self, qapp):
        import test_friends_window
        app = test_friends_window.App(qapp)
        try:
            for key in ("friends", "friends_add"):
                assert _found([app.ui.views["Friends"]], tour_steps.step(key)) is not None, key
        finally:
            app.done()

    def test_the_suits_page_has_its_steps(self, qapp):
        import test_suits_view
        host = test_suits_view._Host(test_suits_view.FakeController())
        host.window.resize(1300, 1400)
        host.window.show()
        try:
            pump()
            for key in ("suits", "suit_connect"):
                assert _found([host.window], tour_steps.step(key)) is not None, key
        finally:
            host.window.close()

    def test_the_avatar_remote_page_has_its_steps(self, qapp):
        import test_params_page
        from parameter_store import store
        _host, _ui, root = test_params_page.page(qapp)
        try:
            for key in ("remote", "remote_board"):
                assert _found([root], tour_steps.step(key)) is not None, key
        finally:
            root.close()
            store.rebuild_from_json({})

    def test_the_sidebar_has_help(self):
        import ui_components
        assert "Help" in ui_components.OscGoesPurrrUI._NAV_TIPS
        assert tour_steps.step("done").targets == ("Help",)
