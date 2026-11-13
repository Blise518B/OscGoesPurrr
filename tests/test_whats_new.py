""""What's new" after an update.

Three layers, bottom up: the content and the rule for when it shows
(`whats_new.py`), the launch hook (`controllers/whats_new_facade.py`) and
the window with its "Take me there" jumps (`ui/views/whats_new.py`).
"""
import sys

import pytest

import whats_new
from update_checker import compare_versions


@pytest.fixture(scope="module")
def qapp():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication(sys.argv[:1])


# ---------------------------------------------------------------------------
# Content
# ---------------------------------------------------------------------------

class TestContent:
    def test_releases_are_versions_newest_first(self):
        versions = [r.version for r in whats_new.RELEASES]
        assert versions, "no release notes at all"
        for v in versions:
            assert compare_versions(v, v) == 0, f"{v!r} is not a version"
        for newer, older in zip(versions, versions[1:]):
            assert compare_versions(newer, older) == 1, (newer, older)

    def test_the_release_check_knows_the_three_cases(self, monkeypatch):
        """Notes are filed under the version they ship as. release.bat
        asks tools/check_whats_new.py before publishing: notes under a
        later version would never be shown (2, the release stops); none
        for this version is only worth a reminder (1)."""
        import importlib.util
        import os
        path = os.path.join(os.path.dirname(os.path.dirname(__file__)),
                            "tools", "check_whats_new.py")
        spec = importlib.util.spec_from_file_location("check_whats_new", path)
        tool = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(tool)
        item = whats_new.Item("T", "x")
        monkeypatch.setattr(whats_new, "RELEASES",
                            (whats_new.Release("0.12.0", (item,)),))
        assert tool.check("0.12.0") == 0
        assert tool.check("0.12.1") == 1
        assert tool.check("0.11.9") == 2
        assert tool.check("not a version") == 2
        monkeypatch.setattr(whats_new, "RELEASES", ())
        assert tool.check("0.12.0") == 1

    def test_every_item_says_something(self):
        for release in whats_new.RELEASES:
            assert release.items, release.version
            for item in release.items:
                assert item.title.strip() and item.text.strip()
                assert len(item.title) <= 40, item.title    # one line

    def test_every_target_is_a_place_the_window_can_open(self):
        from ui.views.whats_new import PLACES
        for release in whats_new.RELEASES:
            for item in release.items:
                assert item.target == "" or item.target in PLACES, item

    def test_every_icon_is_one_of_the_apps_own(self):
        """A change wears the icon its subject has everywhere -- toys,
        shockers, Avatar Remote, Friends ... (ui/icons) -- never one of
        its own."""
        from ui.icons import ICON_NAMES
        icons = set()
        for release in whats_new.RELEASES:
            for item in release.items:
                assert item.icon == "" or item.icon in ICON_NAMES, item
                icons.add(item.icon)
        assert {"toys", "shock", "params", "friends"} <= icons

    def test_the_colour_change_has_its_button(self):
        """The one this window was asked for: a jump to the colours."""
        notes = {r.version: r for r in whats_new.RELEASES}["0.12.0"]
        assert "appearance" in {item.target for item in notes.items}


# ---------------------------------------------------------------------------
# The rule
# ---------------------------------------------------------------------------

class TestRule:
    @pytest.fixture(autouse=True)
    def notes(self, monkeypatch):
        item = whats_new.Item("T", "x")
        monkeypatch.setattr(whats_new, "RELEASES", (
            whats_new.Release("0.14.0", (item,)),
            whats_new.Release("0.13.0", (item,)),
            whats_new.Release("0.12.0", (item,)),
        ))

    @staticmethod
    def _versions(releases):
        return [r.version for r in releases]

    def test_an_update_shows_what_came_since(self):
        got = whats_new.unseen_releases("0.12.0", "0.13.0")
        assert self._versions(got) == ["0.13.0"]

    def test_the_same_version_again_shows_nothing(self):
        assert whats_new.unseen_releases("0.13.0", "0.13.0") == []

    def test_an_install_older_than_the_marker_has_seen_nothing(self):
        got = whats_new.unseen_releases("", "0.12.0")
        assert self._versions(got) == ["0.12.0"]

    def test_a_build_never_shows_notes_from_its_future(self):
        assert whats_new.unseen_releases("", "0.11.1") == []
        assert self._versions(whats_new.releases_for("0.13.0")) == [
            "0.13.0", "0.12.0"]

    def test_several_skipped_updates_show_every_one_they_missed(self):
        """Someone jumping 0.11 -> 0.14 gets 0.13's and 0.12's news too,
        not only the newest few (the window pages through them)."""
        got = whats_new.unseen_releases("0.11.1", "0.14.0")
        assert self._versions(got) == ["0.14.0", "0.13.0", "0.12.0"]
        got = whats_new.unseen_releases("0.12.0", "0.14.0")
        assert self._versions(got) == ["0.14.0", "0.13.0"]

    def test_a_long_list_is_never_cut(self, monkeypatch):
        item = whats_new.Item("T", "x")
        many = tuple(whats_new.Release(f"0.{n}.0", (item,))
                     for n in range(30, 0, -1))
        monkeypatch.setattr(whats_new, "RELEASES", many)
        assert len(whats_new.unseen_releases("0.0.9", "0.30.0")) == 30
        assert len(whats_new.unseen_releases("", "0.30.0")) == 30
        assert len(whats_new.releases_for("0.30.0")) == 30

    def test_a_bug_fix_update_opens_no_old_news(self):
        """0.13.0 -> 0.13.1 with no notes of its own (a patch gets none):
        0.13.0's were shown already. The release after it still shows."""
        assert whats_new.unseen_releases("0.13.0", "0.13.1") == []
        assert self._versions(whats_new.unseen_releases(
            "0.13.1", "0.14.0")) == ["0.14.0"]

    def test_build_suffixes_do_not_matter(self):
        got = whats_new.unseen_releases("0.12.0", "0.13.0-test4")
        assert self._versions(got) == ["0.13.0"]
        assert whats_new.unseen_releases("0.13.0", "0.13.0-dev(3)") == []

    def test_a_junk_marker_counts_as_nothing_seen(self):
        got = whats_new.unseen_releases("not a version", "0.12.0")
        assert self._versions(got) == ["0.12.0"]
        for junk in ("", "not a version", "v", "1.x", "None"):
            got = whats_new.unseen_releases(junk, "0.14.0")
            assert self._versions(got) == ["0.14.0", "0.13.0", "0.12.0"], junk

    def test_a_final_release_stands_in_for_its_alphas(self, monkeypatch):
        item = whats_new.Item("T", "x")
        monkeypatch.setattr(whats_new, "RELEASES", (
            whats_new.Release("0.14.0", (item,)),
            whats_new.Release("0.14.0-alpha.2", (item,)),
            whats_new.Release("0.14.0-alpha.1", (item,)),
            whats_new.Release("0.13.0", (item,)),
        ))
        # from the last release, and from an alpha: the final's notes alone
        assert self._versions(whats_new.unseen_releases("0.13.0", "0.14.0")) == ["0.14.0"]
        assert self._versions(whats_new.unseen_releases(
            "0.14.0-alpha.1", "0.14.0")) == ["0.14.0"]
        assert self._versions(whats_new.releases_for("0.14.0")) == ["0.14.0", "0.13.0"]
        # an alpha build still has its own
        assert self._versions(whats_new.unseen_releases(
            "0.14.0-alpha.1", "0.14.0-alpha.2")) == ["0.14.0-alpha.2"]

    def test_a_downgrade_shows_nothing(self):
        assert whats_new.unseen_releases("0.14.0", "0.12.0") == []

    def test_plain_form_for_the_ui(self):
        plain = whats_new.as_plain([whats_new.Release(
            "1.0.0", (whats_new.Item("A", "b", "home", "toys"),
                      whats_new.Item("C", "d")))])
        assert plain == [("1.0.0", [("A", "b", "home", "toys"),
                                    ("C", "d", "", "")])]


# ---------------------------------------------------------------------------
# The launch hook
# ---------------------------------------------------------------------------

class _Settings:
    def __init__(self, fresh):
        self.created_fresh = fresh


class _ModeManager:
    def __init__(self, fresh):
        self.app_settings = _Settings(fresh)


class _Ui:
    def __init__(self):
        self.shown = []

    def show_whats_new(self, releases):
        self.shown.append(releases)


def _app(monkeypatch, version, seen=None, fresh=False, releases=None):
    import controllers.whats_new_facade as facade
    monkeypatch.setattr(facade, "__version__", version)
    item = whats_new.Item("T", "x", "home")
    monkeypatch.setattr(whats_new, "RELEASES", releases or (
        whats_new.Release("0.13.0", (item,)),
        whats_new.Release("0.12.0", (item,)),
    ))

    class App(facade.WhatsNewFacade):
        def __init__(self):
            self.mode_manager = _ModeManager(fresh)
            self.ui = _Ui()
            self.store = {} if seen is None else {whats_new.SEEN_KEY: seen}
            self.writes = 0

        def get_app_setting(self, key, default=None):
            return self.store.get(key, default)

        def set_app_setting(self, key, value):
            self.store[key] = value
            self.writes += 1

    return App()


class TestLaunch:
    def test_the_first_launch_after_an_update_shows_the_notes_once(
            self, monkeypatch):
        app = _app(monkeypatch, "0.12.0")            # updated from 0.11.x
        assert app.whats_new_on_launch() is True
        assert [v for v, _items in app.ui.shown[0]] == ["0.12.0"]
        assert app.store[whats_new.SEEN_KEY] == "0.12.0"
        assert app.whats_new_on_launch() is False    # next launch
        assert len(app.ui.shown) == 1

    def test_a_first_install_is_not_an_update(self, monkeypatch):
        app = _app(monkeypatch, "0.12.0", fresh=True)
        assert app.whats_new_on_launch() is False
        assert app.ui.shown == []
        # ...and it starts "up to date": the NEXT update shows its notes.
        assert app.store[whats_new.SEEN_KEY] == "0.12.0"

    def test_the_next_update_shows_only_its_own_notes(self, monkeypatch):
        app = _app(monkeypatch, "0.13.0", seen="0.12.0")
        assert app.whats_new_on_launch() is True
        assert [v for v, _items in app.ui.shown[0]] == ["0.13.0"]
        assert app.store[whats_new.SEEN_KEY] == "0.13.0"

    def test_nothing_new_writes_nothing(self, monkeypatch):
        app = _app(monkeypatch, "0.13.0", seen="0.13.0")
        assert app.whats_new_on_launch() is False
        assert app.writes == 0 and app.ui.shown == []

    def test_a_build_without_notes_leaves_the_marker_alone(self, monkeypatch):
        app = _app(monkeypatch, "0.11.1")
        assert app.whats_new_on_launch() is False
        assert app.store == {} and app.ui.shown == []

    def test_a_ui_without_the_window_is_survived(self, monkeypatch):
        app = _app(monkeypatch, "0.12.0")
        app.ui = object()
        assert app.whats_new_on_launch() is False

    def test_the_button_gets_every_release_as_primitives(self, monkeypatch):
        app = _app(monkeypatch, "0.13.0", seen="0.13.0")
        got = app.get_whats_new()
        assert [v for v, _items in got] == ["0.13.0", "0.12.0"]
        assert got[0][1] == [("T", "x", "home", "")]
        app = _app(monkeypatch, "0.15.0", seen="0.15.0", releases=_FOUR)
        assert [v for v, _items in app.get_whats_new()] == [
            "0.15.0", "0.14.0", "0.13.0", "0.12.0"]


_ITEM = whats_new.Item("T", "x", "home")
_FOUR = tuple(whats_new.Release(v, (_ITEM,))
              for v in ("0.15.0", "0.14.0", "0.13.0", "0.12.0"))


class TestLaunchAcrossReleases:
    """Updates that skip releases, bug-fix updates, and markers that say
    nothing useful -- against four releases of notes."""

    @staticmethod
    def _shown(app):
        return [v for v, _items in app.ui.shown[0]]

    def test_skipping_two_releases_shows_all_three_once(self, monkeypatch):
        app = _app(monkeypatch, "0.15.0", seen="0.12.0", releases=_FOUR)
        assert app.whats_new_on_launch() is True
        assert self._shown(app) == ["0.15.0", "0.14.0", "0.13.0"]
        assert app.store[whats_new.SEEN_KEY] == "0.15.0"
        assert app.whats_new_on_launch() is False
        assert len(app.ui.shown) == 1

    def test_a_bug_fix_update_shows_nothing(self, monkeypatch):
        """0.15.0 -> 0.15.1 with no notes of its own (Blise's rule for a
        patch): no window, and the marker stays on 0.15.0."""
        app = _app(monkeypatch, "0.15.1", seen="0.15.0", releases=_FOUR)
        assert app.whats_new_on_launch() is False
        assert app.ui.shown == [] and app.writes == 0
        assert app.store[whats_new.SEEN_KEY] == "0.15.0"

    def test_a_bug_fix_update_over_skipped_releases_shows_them(
            self, monkeypatch):
        app = _app(monkeypatch, "0.15.2", seen="0.13.0", releases=_FOUR)
        assert app.whats_new_on_launch() is True
        assert self._shown(app) == ["0.15.0", "0.14.0"]
        assert app.store[whats_new.SEEN_KEY] == "0.15.0"

    def test_a_fresh_install_shows_nothing_and_starts_up_to_date(
            self, monkeypatch):
        app = _app(monkeypatch, "0.15.0", fresh=True, releases=_FOUR)
        assert app.whats_new_on_launch() is False
        assert app.ui.shown == []
        assert app.store[whats_new.SEEN_KEY] == "0.15.0"
        # the next feature release shows only its own notes
        app2 = _app(monkeypatch, "0.16.0", seen="0.15.0", releases=(
            whats_new.Release("0.16.0", (_ITEM,)),) + _FOUR)
        assert app2.whats_new_on_launch() is True
        assert self._shown(app2) == ["0.16.0"]

    @pytest.mark.parametrize("seen", [None, "", "garbage", "v", "1.x.0"])
    def test_no_marker_or_a_garbage_one_shows_everything(
            self, monkeypatch, seen):
        """An install from before the window, or a marker nobody can read:
        every release this build has, then never again."""
        app = _app(monkeypatch, "0.15.0", seen=seen, releases=_FOUR)
        assert app.whats_new_on_launch() is True
        assert self._shown(app) == ["0.15.0", "0.14.0", "0.13.0", "0.12.0"]
        assert app.store[whats_new.SEEN_KEY] == "0.15.0"
        assert app.whats_new_on_launch() is False


class TestFreshInstallMarker:
    def test_no_settings_file_means_a_first_install(self, monkeypatch, tmp_path):
        import settings.app as app_settings
        path = tmp_path / "app_settings.json"
        monkeypatch.setattr(app_settings, "APP_SETTINGS_FILE", str(path))
        first = app_settings.AppSettingsManager()
        assert first.created_fresh is True and path.exists()
        assert first.get(whats_new.SEEN_KEY) == ""
        again = app_settings.AppSettingsManager()
        assert again.created_fresh is False

    def test_a_settings_file_from_an_older_version_reads_as_nothing_seen(
            self, monkeypatch, tmp_path):
        import settings.app as app_settings
        path = tmp_path / "app_settings.json"
        path.write_text('{"auto_connect": false}', encoding="utf-8")
        monkeypatch.setattr(app_settings, "APP_SETTINGS_FILE", str(path))
        manager = app_settings.AppSettingsManager()
        assert manager.created_fresh is False
        assert manager.get(whats_new.SEEN_KEY) == ""


# ---------------------------------------------------------------------------
# The window
# ---------------------------------------------------------------------------

NOTES = [("0.12.0", [
    ("Any colour you like", "Pick a colour.", "appearance"),
    ("Toys are found by themselves", "Nothing to press.", ""),
    ("Somewhere this build lacks", "No such page.", "elsewhere"),
])]


@pytest.fixture
def host(qapp, monkeypatch):
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import (
        QDialog, QFrame, QScrollArea, QTabWidget, QVBoxLayout, QWidget,
    )
    import ui.views.whats_new as view

    # Short beats, and windows that never reach the screen.
    monkeypatch.setattr(view, "_SPOT_BEATS", ((0, True), (20, False)))
    monkeypatch.setattr(view, "_SETTLE_MS", 0)

    def _quiet_open(self):
        self.setAttribute(Qt.WA_DontShowOnScreen, True)
        self.show()
    monkeypatch.setattr(QDialog, "open", _quiet_open)

    class Controller:
        def get_whats_new(self):
            return NOTES

    class Host(view.WhatsNewMixin):
        def __init__(self):
            self.controller = Controller()
            self.window = QWidget()
            self.selected = []
            self.offers = []
            scroll = QScrollArea()
            inner = QWidget()
            lay = QVBoxLayout(inner)
            self._settings_tabs = QTabWidget()
            general = QWidget()
            g = QVBoxLayout(general)
            filler = QFrame()
            filler.setFixedHeight(900)
            g.addWidget(filler)
            self._appearance_card = QFrame()
            self._appearance_card.setObjectName("card")
            self._appearance_card.setFixedHeight(120)
            g.addWidget(self._appearance_card)
            self._settings_tabs.addTab(general, "General")
            self._settings_tabs.addTab(QWidget(), "Sessions")
            self._settings_tabs.setCurrentIndex(1)
            lay.addWidget(self._settings_tabs)
            scroll.setWidget(inner)
            scroll.setWidgetResizable(True)
            scroll.resize(600, 300)
            self.views = {"Settings": scroll, "Home": QWidget()}

        def select_view(self, name):
            self.selected.append(name)

        def _repolish(self, w):
            w.style().unpolish(w)
            w.style().polish(w)

        def show_update_popup(self, *args):
            self.offers.append(args)

    return Host()


def _buttons(dlg, text):
    from PySide6.QtWidgets import QPushButton
    return [b for b in dlg.findChildren(QPushButton) if b.text() == text]


class TestWindow:
    def test_one_row_per_change_and_a_jump_only_where_there_is_a_place(
            self, host):
        from PySide6.QtWidgets import QLabel
        host.show_whats_new(NOTES)
        dlg = host._whats_new_dialog
        titles = [l.text() for l in dlg.findChildren(QLabel)
                  if l.objectName() == "newsTitle"]
        assert titles == [t for t, _x, _p in NOTES[0][1]]
        heads = [l.text() for l in dlg.findChildren(QLabel)
                 if l.objectName() == "sectionTitle"]
        assert heads == ["What's new in v0.12.0"]
        # One jump: the colour. No target, or a page this build lacks: none.
        assert len(_buttons(dlg, "Take me there")) == 1
        assert len(_buttons(dlg, "Got it")) == 1
        dlg.reject()

    def test_without_icons_there_is_no_icon_column(self, host):
        from ui.widgets import IdentityMark
        host.show_whats_new(NOTES)
        assert host._whats_new_dialog.findChildren(IdentityMark) == []
        host._whats_new_dialog.reject()

    def test_each_change_wears_its_icon_and_the_rest_a_blank(self, host):
        from ui.widgets import IdentityMark
        notes = [("0.14.0", [
            ("Shockers like PiShock's", "Bolt.", "", "shock"),
            ("Friends check versions", "Nothing of the three.", ""),
            ("Toys found faster", "Capsule.", "", "toys"),
        ])]
        host.show_whats_new(notes)
        marks = host._whats_new_dialog.findChildren(IdentityMark)
        # one per row, in order; the blank keeps the titles in one column
        assert [m.property("what") for m in marks] == ["shock", "", "toys"]
        assert len({m.mapTo(host._whats_new_dialog, m.rect().topLeft()).x()
                    for m in marks}) == 1
        host._whats_new_dialog.reject()

    def test_got_it_closes_and_the_window_can_open_again(self, host):
        host.show_whats_new(NOTES)
        _buttons(host._whats_new_dialog, "Got it")[0].click()
        assert host._whats_new_dialog is None and host.selected == []
        host.open_whats_new()                       # the Settings button
        assert host._whats_new_dialog is not None
        host._whats_new_dialog.reject()

    def test_only_one_window_at_a_time(self, host):
        host.show_whats_new(NOTES)
        first = host._whats_new_dialog
        host.show_whats_new(NOTES)
        assert host._whats_new_dialog is first
        first.reject()

    def test_nothing_to_tell_opens_nothing(self, host):
        host.show_whats_new([])
        host.show_whats_new([("0.12.0", [])])
        assert getattr(host, "_whats_new_dialog", None) is None

    def test_take_me_there_closes_opens_the_page_and_lights_the_card(
            self, host):
        from PySide6.QtTest import QTest
        host.show_whats_new(NOTES)
        _buttons(host._whats_new_dialog, "Take me there")[0].click()
        assert host._whats_new_dialog is None
        assert host.selected == ["Settings"]
        assert host._settings_tabs.currentIndex() == 0      # General
        card = host._appearance_card
        QTest.qWait(10)
        assert card.property("spot") == "true"
        assert host.views["Settings"].verticalScrollBar().value() > 0
        QTest.qWait(60)
        assert card.property("spot") == "false"

    def test_a_page_without_a_card_just_opens(self, host):
        assert host.reveal("home") is True
        assert host.selected == ["Home"]

    def test_an_unknown_place_goes_nowhere(self, host):
        assert host.reveal("nowhere") is False
        assert host.reveal("toy_safety") is True     # page there, card not
        assert host.selected == ["Settings"]

    def test_an_update_offer_waits_for_the_window_to_close(self, host):
        host.show_whats_new(NOTES)
        host._update_popup_waiting = ("0.13.0", "0.12.0", "url", True)
        _buttons(host._whats_new_dialog, "Got it")[0].click()
        from PySide6.QtTest import QTest
        QTest.qWait(10)
        assert host.offers == [("0.13.0", "0.12.0", "url", True)]
        assert host._update_popup_waiting is None

    def test_one_release_has_no_pager(self, host):
        host.show_whats_new(NOTES)
        dlg = host._whats_new_dialog
        assert _buttons(dlg, "Next →") == [] and _buttons(dlg, "← Back") == []
        dlg.reject()

    def test_the_lit_card_has_a_style_in_both_modes(self):
        from ui import theme
        for mode in ("neon", "midnight"):
            assert 'QFrame#card[spot="true"]' in theme.build_qss(mode)


class TestUpdateOfferWaits:
    def test_the_update_window_does_not_open_over_whats_new(self, qapp):
        from ui.views.settings import SettingsMixin

        class Host(SettingsMixin):
            def __init__(self):
                self._whats_new_dialog = object()        # it is open

        h = Host()
        h.show_update_popup("0.13.0", "0.12.0", "url", True)
        assert h._update_popup_waiting == ("0.13.0", "0.12.0", "url", True)
        assert getattr(h, "_update_popup", None) is None


# Three releases, the middle one the longest, the oldest with a jump.
PAGED = [
    ("0.15.0", [("Haptic suits", "Short.", "", "suits")]),
    ("0.14.0", [
        ("Friends", "Link with other OGP users over the internet. " * 4, "friends", "friends"),
        ("Shockers", "A PiShock or OpenShock hub over USB. " * 4, "", "shock"),
        ("Avatar Remote", "Buttons and sliders for your avatar. " * 4, "", "params"),
    ]),
    ("0.12.0", [("Any colour you like", "Pick a colour.", "appearance", "settings")]),
]


class TestPagedWindow:
    """An update that skipped releases: one page per release, newest
    first, Back / Next between them."""

    @staticmethod
    def _pages(dlg):
        from PySide6.QtWidgets import QStackedWidget
        return dlg.findChild(QStackedWidget, "newsPages")

    @staticmethod
    def _head(dlg):
        from PySide6.QtWidgets import QLabel
        page = TestPagedWindow._pages(dlg).currentWidget()
        return [l.text() for l in page.findChildren(QLabel)
                if l.objectName() == "sectionTitle"]

    @staticmethod
    def _count(dlg):
        from PySide6.QtWidgets import QLabel
        return dlg.findChild(QLabel, "newsCount").text()

    def test_every_release_gets_a_page_newest_first(self, host):
        host.show_whats_new(PAGED)
        dlg = host._whats_new_dialog
        pages = self._pages(dlg)
        assert pages.count() == 3 and pages.currentIndex() == 0
        assert self._head(dlg) == ["What's new in v0.15.0"]
        assert self._count(dlg) == "1 of 3"
        dlg.reject()

    def test_next_and_back_turn_the_pages(self, host):
        host.show_whats_new(PAGED)
        dlg = host._whats_new_dialog
        back, nxt = _buttons(dlg, "← Back")[0], _buttons(dlg, "Next →")[0]
        # nowhere to go back to on the first page
        assert back.isHidden() and not nxt.isHidden()
        nxt.click()
        assert self._head(dlg) == ["Before that, in v0.14.0"]
        assert self._count(dlg) == "2 of 3"
        assert not back.isHidden() and not nxt.isHidden()
        nxt.click()
        assert self._head(dlg) == ["Before that, in v0.12.0"]
        assert self._count(dlg) == "3 of 3"
        assert nxt.isHidden()
        nxt.click()                                 # past the end: stays
        assert self._pages(dlg).currentIndex() == 2
        back.click()
        back.click()
        assert self._head(dlg) == ["What's new in v0.15.0"]
        assert back.isHidden()
        dlg.reject()

    def test_the_window_and_its_buttons_stay_put_while_paging(self, host):
        """Every page has the room of the tallest, so Next stays under
        the pointer and nothing is cut off."""
        host.show_whats_new(PAGED)
        dlg = host._whats_new_dialog
        pages = self._pages(dlg)
        nxt, back = _buttons(dlg, "Next →")[0], _buttons(dlg, "← Back")[0]
        size, at = dlg.size(), nxt.mapTo(dlg, nxt.rect().topLeft())
        for i in range(pages.count()):
            need = pages.widget(i).layout().totalHeightForWidth(pages.width())
            assert need <= pages.height(), (i, need, pages.height())
        nxt.click()
        assert dlg.size() == size
        assert nxt.mapTo(dlg, nxt.rect().topLeft()) == at
        assert not back.isHidden()
        dlg.reject()

    def test_a_later_page_jumps_and_got_it_closes_from_any_page(self, host):
        host.show_whats_new(PAGED)
        dlg = host._whats_new_dialog
        _buttons(dlg, "Next →")[0].click()
        _buttons(dlg, "Next →")[0].click()
        # the jump on the oldest page works like any other
        page = self._pages(dlg).currentWidget()
        go = [b for b in _buttons(dlg, "Take me there")
              if b.parent() is not None and page.isAncestorOf(b)]
        assert len(go) == 1
        go[0].click()
        assert host._whats_new_dialog is None
        assert host.selected == ["Settings"]
        host.show_whats_new(PAGED)
        _buttons(host._whats_new_dialog, "Next →")[0].click()
        _buttons(host._whats_new_dialog, "Got it")[0].click()
        assert host._whats_new_dialog is None

    def test_the_settings_button_pages_through_everything(self, host):
        host.controller.get_whats_new = lambda: PAGED
        host.open_whats_new()
        assert self._pages(host._whats_new_dialog).count() == 3
        host._whats_new_dialog.reject()

    def test_the_real_notes_page_for_an_update_from_0_12(self, host):
        """The notes this build ships, as someone updating from 0.12.0
        meets them: 0.13.0's Linux news is no longer cut off."""
        got = whats_new.as_plain(whats_new.unseen_releases(
            "0.12.0", whats_new.RELEASES[0].version))
        assert "0.13.0" in [v for v, _items in got]
        host.show_whats_new(got)
        dlg = host._whats_new_dialog
        assert self._pages(dlg).count() == len(got)
        assert self._count(dlg) == f"1 of {len(got)}"
        dlg.reject()
