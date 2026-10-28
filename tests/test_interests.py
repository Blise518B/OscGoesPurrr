""""What are you here for?" -- asked once, to pick the features someone uses.

Three layers, bottom up: the choices and the rule (`interests.py`), the
launch hook (`controllers/interests_facade.py`) and the window, with what
waits for it (`ui/views/interests.py`).
"""
import sys

import pytest

import interests


@pytest.fixture(scope="module")
def qapp():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication(sys.argv[:1])


# ---------------------------------------------------------------------------
# The choices
# ---------------------------------------------------------------------------

class TestChoices:
    def test_every_public_feature_switch_is_asked(self):
        """A feature the Settings page offers has a choice here too, so
        a new feature is never left out of the question."""
        import main
        from ui.views.settings import SettingsMixin
        public = set(main.OscGoesPurrrApp.FEATURE_KEYS) - SettingsMixin._HIDDEN_FEATURES
        assert set(interests.features()) == public

    def test_a_feature_not_offered_yet_is_off_and_not_asked(self):
        """FEATURES_NOT_YET (the suits, for now): off whatever was saved,
        not in the flags Settings and the question are built from, and a
        switch flipped anyway changes nothing."""
        import main
        app = main.OscGoesPurrrApp.__new__(main.OscGoesPurrrApp)
        saved = {"feature_bhaptics": True, "feature_owo": True, "feature_friends": True}
        app.get_app_setting = lambda key, default=None: saved.get(key, default)
        app.set_app_setting = lambda key, value: saved.__setitem__(key, value)
        app.ui = None
        app._apply_feature_state = lambda key, on: pytest.fail(f"{key} applied")
        assert main.OscGoesPurrrApp.FEATURES_NOT_YET == {"feature_bhaptics", "feature_owo"}
        for key in main.OscGoesPurrrApp.FEATURES_NOT_YET:
            assert app.get_feature_enabled(key) is False
            assert key not in app.get_feature_flags()
            app.set_feature_enabled(key, False)
            assert saved[key] is True
        assert app.get_feature_flags()["feature_friends"] is True

    def test_each_switch_is_asked_once(self):
        assert len(interests.features()) == len(set(interests.features()))

    def test_every_choice_says_something_short(self):
        for group in interests.GROUPS:
            assert group.title.strip() and group.choices
            for c in group.choices:
                assert c.title.strip() and c.hint.strip()
                assert len(c.title) <= 40, c.title          # one line
                assert len(c.hint) <= 70, c.hint

    def test_an_answer_flips_only_what_differs(self):
        current = {"feature_intiface": True, "feature_pishock": False,
                   "feature_friends": True}
        picked = {"feature_intiface": True, "feature_pishock": True,
                  "feature_friends": False}
        assert interests.changes(current, picked) == {
            "feature_pishock": True, "feature_friends": False}

    def test_what_the_answer_leaves_out_stays(self):
        assert interests.changes({"feature_pishock": True}, {}) == {}
        # ...and a key the question doesn't ask is never set
        assert interests.changes({}, {"feature_osc_router_518": False}) == {}


# ---------------------------------------------------------------------------
# The launch hook
# ---------------------------------------------------------------------------

class _Ui:
    def __init__(self):
        self.shown = []

    def show_interests(self, groups, at_launch):
        self.shown.append((groups, at_launch))


def _app(asked=None, flags=None):
    import controllers.interests_facade as facade

    class App(facade.InterestsFacade):
        def __init__(self):
            self.ui = _Ui()
            self.store = {} if asked is None else {interests.ASKED_KEY: asked}
            self.flags = dict(flags or {k: k == "feature_intiface"
                                        for k in interests.features()})
            self.set_calls = []
            self.logs = []

        def get_app_setting(self, key, default=None):
            return self.store.get(key, default)

        def set_app_setting(self, key, value):
            self.store[key] = value

        def get_feature_flags(self):
            return dict(self.flags)

        def set_feature_enabled(self, key, on):
            self.set_calls.append((key, on))
            self.flags[key] = on

        def log_message(self, msg):
            self.logs.append(msg)

    return App()


class TestLaunch:
    def test_a_new_or_older_install_is_asked_once(self):
        app = _app()                        # no marker: new, or from before
        assert app.interests_on_launch() is True
        groups, at_launch = app.ui.shown[0]
        assert at_launch is True
        assert [g for g, _items in groups] == [g.title for g in interests.GROUPS]

    def test_once_answered_it_is_not_asked_again(self):
        app = _app(asked=True)
        assert app.interests_on_launch() is False
        assert app.ui.shown == []

    def test_it_starts_from_the_switches_as_they_are(self):
        app = _app()
        got = {f: on for _g, items in app.get_interests() for f, _t, _h, on in items}
        assert got == app.flags

    def test_an_answer_sets_what_changed_and_remembers(self):
        app = _app()
        picked = dict(app.flags, feature_pishock=True, feature_intiface=True)
        app.set_interests(picked)
        assert app.set_calls == [("feature_pishock", True)]
        assert app.store[interests.ASKED_KEY] is True
        assert app.logs == ["Features picked: pishock on"]
        assert app.interests_on_launch() is False

    def test_skip_changes_nothing_and_remembers(self):
        app = _app()
        app.skip_interests()
        assert app.set_calls == [] and app.store[interests.ASKED_KEY] is True

    def test_a_ui_without_the_window_is_survived(self):
        app = _app()
        app.ui = object()
        assert app.interests_on_launch() is False
        assert interests.ASKED_KEY not in app.store

    def test_the_app_has_it_and_asks_before_whats_new(self):
        import inspect
        import main
        from controllers.interests_facade import InterestsFacade
        assert issubclass(main.OscGoesPurrrApp, InterestsFacade)
        src = inspect.getsource(main.OscGoesPurrrApp)
        assert "self.interests_on_launch(), self.whats_new_on_launch()" in src


class TestMarker:
    def test_a_new_install_has_not_been_asked(self, monkeypatch, tmp_path):
        import settings.app as app_settings
        monkeypatch.setattr(app_settings, "APP_SETTINGS_FILE",
                            str(tmp_path / "app_settings.json"))
        assert app_settings.AppSettingsManager().get(interests.ASKED_KEY) is False

    def test_an_install_from_before_the_question_has_not_been_asked(
            self, monkeypatch, tmp_path):
        import settings.app as app_settings
        path = tmp_path / "app_settings.json"
        path.write_text('{"auto_connect": false}', encoding="utf-8")
        monkeypatch.setattr(app_settings, "APP_SETTINGS_FILE", str(path))
        assert app_settings.AppSettingsManager().get(interests.ASKED_KEY) is False


# ---------------------------------------------------------------------------
# The window
# ---------------------------------------------------------------------------

GROUPS = [
    ("WHAT YOU HAVE", [("feature_intiface", "Toys", "Buttplug", True),
                       ("feature_pishock", "A shocker", "USB", False)]),
    ("WHAT YOU WANT", [("feature_friends", "Friends", "Internet", True)]),
]


@pytest.fixture
def host(qapp, monkeypatch):
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QDialog, QWidget
    import ui.views.interests as view

    def _quiet_open(self):
        self.setAttribute(Qt.WA_DontShowOnScreen, True)
        self.show()
    monkeypatch.setattr(QDialog, "open", _quiet_open)

    class Controller:
        def __init__(self):
            self.answers = []
            self.skips = 0

        def get_interests(self):
            return GROUPS

        def set_interests(self, picked):
            self.answers.append(picked)

        def skip_interests(self):
            self.skips += 1

    class Host(view.InterestsMixin):
        def __init__(self):
            self.controller = Controller()
            self.window = QWidget()
            self.news = []
            self.offers = []
            self.synced = 0

        def show_whats_new(self, releases):
            self.news.append(releases)

        def show_update_popup(self, *args):
            self.offers.append(args)

        def _sync_feature_toggles(self):
            self.synced += 1

    return Host()


def _buttons(dlg, text):
    from PySide6.QtWidgets import QPushButton
    return [b for b in dlg.findChildren(QPushButton) if b.text() == text]


def _boxes(dlg):
    from PySide6.QtWidgets import QCheckBox
    return {b.text(): b for b in dlg.findChildren(QCheckBox)}


class TestWindow:
    def test_one_box_per_choice_ticked_as_the_switch_is(self, host):
        from PySide6.QtWidgets import QLabel
        host.show_interests(GROUPS, True)
        dlg = host._interests_dialog
        boxes = _boxes(dlg)
        assert {t: b.isChecked() for t, b in boxes.items()} == {
            "Toys": True, "A shocker": False, "Friends": True}
        caps = [l.text() for l in dlg.findChildren(QLabel)
                if l.objectName() == "listDivider"]
        assert caps == ["WHAT YOU HAVE", "WHAT YOU WANT"]
        assert _buttons(dlg, "Skip") and _buttons(dlg, "Done")
        dlg.reject()

    def test_done_sends_every_tick(self, host):
        host.show_interests(GROUPS, True)
        dlg = host._interests_dialog
        _boxes(dlg)["A shocker"].setChecked(True)
        _boxes(dlg)["Friends"].setChecked(False)
        _buttons(dlg, "Done")[0].click()
        assert host.controller.answers == [{
            "feature_intiface": True, "feature_pishock": True,
            "feature_friends": False}]
        assert host.controller.skips == 0
        assert host._interests_dialog is None and host.synced == 1

    def test_a_hint_ticks_its_box(self, host):
        from PySide6.QtCore import Qt
        from PySide6.QtTest import QTest
        from ui.views.interests import _Hint
        host.show_interests(GROUPS, True)
        dlg = host._interests_dialog
        hint = [h for h in dlg.findChildren(_Hint) if h.text() == "USB"][0]
        QTest.mouseClick(hint, Qt.LeftButton)
        assert _boxes(dlg)["A shocker"].isChecked()
        dlg.reject()

    def test_skip_or_closing_at_launch_is_an_answer(self, host):
        host.show_interests(GROUPS, True)
        _buttons(host._interests_dialog, "Skip")[0].click()
        host.show_interests(GROUPS, True)
        host._interests_dialog.reject()                 # the window's ×
        assert host.controller.skips == 2 and host.controller.answers == []

    def test_from_settings_cancel_changes_nothing(self, host):
        host.open_interests()
        dlg = host._interests_dialog
        assert not _buttons(dlg, "Skip")
        _buttons(dlg, "Cancel")[0].click()
        assert host.controller.skips == 0 and host.controller.answers == []

    def test_only_one_window_at_a_time(self, host):
        host.show_interests(GROUPS, True)
        first = host._interests_dialog
        host.show_interests(GROUPS, True)
        assert host._interests_dialog is first
        first.reject()

    def test_whats_new_waits_for_the_question(self, qapp, host, monkeypatch):
        """At launch the question opens first; the notes open after it."""
        from PySide6.QtTest import QTest
        from ui.views.whats_new import WhatsNewMixin
        host.show_interests(GROUPS, True)
        notes = [("0.14.0", [("A", "b", "")])]
        WhatsNewMixin.show_whats_new(host, notes)       # the real one: it waits
        assert getattr(host, "_whats_new_dialog", None) is None
        assert host._whats_new_waiting == notes
        _buttons(host._interests_dialog, "Done")[0].click()
        QTest.qWait(10)
        assert host.news == [notes] and host._whats_new_waiting is None

    def test_an_update_offer_waits_for_the_question(self, host):
        from PySide6.QtTest import QTest
        host.show_interests(GROUPS, True)
        host._update_popup_waiting = ("0.15.0", "0.14.0", "url", True)
        _buttons(host._interests_dialog, "Skip")[0].click()
        QTest.qWait(10)
        assert host.offers == [("0.15.0", "0.14.0", "url", True)]

    def test_the_update_window_does_not_open_over_the_question(self, qapp):
        from ui.views.settings import SettingsMixin

        class Host(SettingsMixin):
            def __init__(self):
                self._interests_dialog = object()       # it is open

        h = Host()
        h.show_update_popup("0.15.0", "0.14.0", "url", True)
        assert h._update_popup_waiting == ("0.15.0", "0.14.0", "url", True)
