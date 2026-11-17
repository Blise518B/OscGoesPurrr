"""Anti-stuck per kind of device (Blise's ask, 2026-11-17: "No one global
anti-stuck, because some of them may want different settings").

Pinned here: the settings module cleans whatever a file holds; each suit,
the trackers and the PSVR2 keep their own block, which a file without one
starts as a copy of the toys' (so an update changes nothing anyone set) --
once; each toy's own switch is a rig fact in its wiring; and every store's
Ctrl+Z asks before an undo or redo switches an anti-stuck off or makes it
wait longer."""

import json

import pytest

import antistuck
import settings_history as sh
from settings.psvr2 import PSVR2SettingsManager
from settings.suits import ANTISTUCK_KINDS, SuitsSettingsManager


class Clock:
    def __init__(self):
        self.t = 100.0

    def __call__(self):
        return self.t

    def tick(self, s=5.0):
        self.t += s


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def hist(clock):
    h = sh.SettingsHistory(clock=clock)
    old = sh.activate(h)
    yield h
    sh.activate(old)


TOYS_OFF = {"enabled": False, "active_s": 4, "peaked_s": 30}


# ---- the module -------------------------------------------------------------

class TestClean:
    def test_defaults_are_on_one_and_ten_seconds(self):
        assert antistuck.clean(None) == {"enabled": True, "active_s": 1, "peaked_s": 10}
        assert antistuck.DEFAULTS == {"enabled": True, "active_s": 1, "peaked_s": 10}

    @pytest.mark.parametrize("bad", ["x", None, float("inf"), float("nan"), 10 ** 400, [3]])
    def test_a_broken_timer_falls_back(self, bad):
        assert antistuck.clean({"active_s": bad})["active_s"] == 1

    def test_timers_stay_in_range_and_whole(self):
        got = antistuck.clean({"active_s": 0, "peaked_s": 9999})
        assert got["active_s"] == antistuck.SECONDS_MIN
        assert got["peaked_s"] == antistuck.SECONDS_MAX
        assert antistuck.clean({"active_s": 2.6})["active_s"] == 3

    def test_only_a_real_false_switches_it_off(self):
        assert antistuck.clean({"enabled": False})["enabled"] is False
        assert antistuck.clean({"enabled": 0})["enabled"] is True      # not a bool
        assert antistuck.clean({"enabled": "no"})["enabled"] is True

    def test_from_app_reads_the_toys_keys(self):
        settings = {"toy_antistuck_enabled": False, "toy_antistuck_active_s": 4}
        assert antistuck.from_app(lambda k, d: settings.get(k, d)) == {
            "enabled": False, "active_s": 4, "peaked_s": 10}

    def test_a_toys_own_switch(self):
        assert antistuck.toy_on({}) and antistuck.toy_on(None)
        assert antistuck.toy_on({antistuck.TOY_KEY: True})
        assert not antistuck.toy_on({antistuck.TOY_KEY: False})

    def test_changed_sets_only_what_it_knows(self):
        got = antistuck.changed(antistuck.DEFAULTS, peaked_s=20, colour="red")
        assert got == {"enabled": True, "active_s": 1, "peaked_s": 20}


class TestLoosens:
    def test_off_and_longer_waits_loosen(self):
        on = dict(antistuck.DEFAULTS)
        assert antistuck.loosens(on, dict(on, enabled=False)) == ["switches it off"]
        assert len(antistuck.loosens(on, dict(on, active_s=5, peaked_s=20))) == 2

    def test_on_and_shorter_waits_dont(self):
        on = dict(antistuck.DEFAULTS, active_s=5, peaked_s=20)
        assert antistuck.loosens(dict(on, enabled=False), on) == []
        assert antistuck.loosens(on, dict(antistuck.DEFAULTS)) == []

    def test_timers_moved_while_it_is_off_dont_ask(self):
        off = dict(antistuck.DEFAULTS, enabled=False)
        assert antistuck.loosens(off, dict(off, active_s=60)) == []


# ---- the suits' store -------------------------------------------------------

class TestSuitsStore:
    def test_a_new_file_starts_as_the_toys_were(self):
        s = SuitsSettingsManager()
        s.seed_antistuck(TOYS_OFF)
        for kind in ANTISTUCK_KINDS:
            assert s.antistuck(kind) == TOYS_OFF

    def test_a_file_from_before_gets_the_toys_values_once(self):
        path = SuitsSettingsManager.FILE_PATH
        old = SuitsSettingsManager().snapshot()
        for kind in ANTISTUCK_KINDS:
            old[kind].pop("antistuck")
        path.write_text(json.dumps(old), encoding="utf-8")
        s = SuitsSettingsManager()
        s.seed_antistuck(TOYS_OFF)
        assert s.antistuck("owo") == TOYS_OFF
        s.seed_antistuck(dict(antistuck.DEFAULTS))          # not again
        assert s.antistuck("owo") == TOYS_OFF
        again = SuitsSettingsManager()                      # it was saved
        again.seed_antistuck(dict(antistuck.DEFAULTS))
        assert again.antistuck("trackers") == TOYS_OFF

    def test_a_file_with_its_own_keeps_it(self):
        s = SuitsSettingsManager()
        s.seed_antistuck(dict(antistuck.DEFAULTS))
        s.set_antistuck("owo", active_s=3)
        again = SuitsSettingsManager()
        again.seed_antistuck(TOYS_OFF)
        assert again.antistuck("owo")["active_s"] == 3
        assert again.antistuck("bhaptics") == antistuck.DEFAULTS

    def test_each_kind_is_its_own(self):
        s = SuitsSettingsManager()
        s.seed_antistuck(dict(antistuck.DEFAULTS))
        s.set_antistuck("bhaptics", enabled=False)
        s.set_antistuck("trackers", peaked_s=25)
        assert s.antistuck("bhaptics")["enabled"] is False
        assert s.antistuck("owo") == antistuck.DEFAULTS
        assert s.antistuck("trackers")["peaked_s"] == 25
        s.set_antistuck("nonsense", enabled=False)          # ignored

    def test_other_changes_keep_it(self):
        s = SuitsSettingsManager()
        s.seed_antistuck(dict(antistuck.DEFAULTS))
        s.set_antistuck("bhaptics", active_s=7)
        s.set_bhaptics_option("follow_owo", False)
        s.place_tracker("LHR-1", "hips")
        s.set_antistuck("trackers", enabled=False)
        s.set_owo_option("frequency", 40)
        assert s.antistuck("bhaptics")["active_s"] == 7
        assert s.antistuck("trackers")["enabled"] is False

    def test_a_hand_edited_block_is_cleaned(self):
        path = SuitsSettingsManager.FILE_PATH
        data = SuitsSettingsManager().snapshot()
        data["owo"]["antistuck"] = {"enabled": "yes", "active_s": 1e9, "peaked_s": -4}
        path.write_text(json.dumps(data), encoding="utf-8")
        got = SuitsSettingsManager().antistuck("owo")
        assert got == {"enabled": True, "active_s": antistuck.SECONDS_MAX,
                       "peaked_s": antistuck.SECONDS_MIN}

    def test_the_snapshot_the_router_gets_carries_each(self):
        snap = SuitsSettingsManager().snapshot()
        for kind in ANTISTUCK_KINDS:
            assert snap[kind]["antistuck"] == antistuck.DEFAULTS


# ---- the PSVR2's store ------------------------------------------------------

class TestPSVR2Store:
    def test_a_new_file_starts_as_the_toys_were(self):
        s = PSVR2SettingsManager()
        s.seed_antistuck(TOYS_OFF)
        assert s.get_antistuck() == TOYS_OFF

    def test_a_file_from_before_gets_the_toys_values_once(self):
        path = PSVR2SettingsManager.FILE_PATH
        old = dict(PSVR2SettingsManager().settings)
        old.pop("antistuck")
        path.write_text(json.dumps(old), encoding="utf-8")
        s = PSVR2SettingsManager()
        s.seed_antistuck(TOYS_OFF)
        assert s.get_antistuck() == TOYS_OFF
        again = PSVR2SettingsManager()
        again.seed_antistuck(dict(antistuck.DEFAULTS))
        assert again.get_antistuck() == TOYS_OFF

    def test_its_own_changes(self):
        s = PSVR2SettingsManager()
        s.seed_antistuck(dict(antistuck.DEFAULTS))
        s.set_antistuck(enabled=False, peaked_s=15)
        assert PSVR2SettingsManager().get_antistuck() == {
            "enabled": False, "active_s": 1, "peaked_s": 15}


# ---- Ctrl+Z asks before it loosens -----------------------------------------

class TestUndoAsks:
    def test_the_toys_switched_back_off_asks(self, hist, clock, monkeypatch, tmp_path):
        import settings.app as app_mod
        monkeypatch.setattr(app_mod, "APP_SETTINGS_FILE", tmp_path / "app_settings.json")
        app = app_mod.AppSettingsManager()
        app.set("toy_antistuck_enabled", False)
        clock.tick()
        app.set("toy_antistuck_enabled", True)      # by hand: back on
        clock.tick()
        asked = []

        def ask(asks, text, answer):
            asked.extend(a.text for a in asks)
            return answer(False)
        hist.undo(ask)
        assert asked == ["Toys' anti-stuck: switches it off"]
        assert app.get("toy_antistuck_enabled") is True        # No: kept

    def test_a_shorter_wait_undone_asks_and_a_longer_one_doesnt(self, hist, clock,
                                                                 monkeypatch, tmp_path):
        import settings.app as app_mod
        monkeypatch.setattr(app_mod, "APP_SETTINGS_FILE", tmp_path / "app_settings.json")
        app = app_mod.AppSettingsManager()
        app.set("toy_antistuck_peaked_s", 30)
        clock.tick()
        assert hist.undo().status == sh.DONE       # 30 -> 10: tighter, no question
        assert app.get("toy_antistuck_peaked_s") == 10
        r = hist.redo()                            # 10 -> 30: looser, asks; no way to ask
        assert r.status == sh.BLOCKED and "100%" in r.text

    def test_a_toys_own_switch_off_asks(self, hist, clock):
        from config_manager import ModeManager
        mm = ModeManager()
        mm.update_device_config("Lush", "motor_count", 1)
        mm.save_profiles()
        clock.tick()
        mm.update_device_config("Lush", antistuck.TOY_KEY, False)
        mm.save_profiles()
        clock.tick()
        mm.update_device_config("Lush", antistuck.TOY_KEY, True)
        mm.save_profiles()
        clock.tick()
        r = hist.undo()                            # back to off: asks
        assert r.status == sh.BLOCKED and "anti-stuck off for Lush" in r.text
        assert antistuck.toy_on(mm.wiring["Lush"])

    def test_a_suits_switched_back_off_asks(self, hist, clock):
        s = SuitsSettingsManager()
        s.set_antistuck("owo", enabled=False)
        clock.tick()
        s.set_antistuck("owo", enabled=True)
        clock.tick()
        r = hist.undo()
        assert r.status == sh.BLOCKED and "OWO anti-stuck: switches it off" in r.text
        assert s.antistuck("owo")["enabled"] is True

    def test_the_headsets_switched_back_off_asks(self, hist, clock):
        s = PSVR2SettingsManager()
        s.set_antistuck(enabled=False)
        clock.tick()
        s.set_antistuck(enabled=True)
        clock.tick()
        r = hist.undo()
        assert r.status == sh.BLOCKED and "PSVR2 anti-stuck: switches it off" in r.text
        assert s.get_antistuck()["enabled"] is True


# ----------------------------------------------------------------------
# The box's switch says what it is (Blise, 2026-11-17: "it would be better
# if it says off if it's off, and it should say on if it's on")
# ----------------------------------------------------------------------

@pytest.fixture(scope="module")
def qapp():
    import sys
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication(sys.argv[:1])


def _box(qapp, values, **kw):
    from ui.views.antistuck_box import AntiStuckBox
    store = dict(values)
    return AntiStuckBox("Suit's anti-stuck", "a suit", lambda: dict(store),
                        lambda **ch: store.update(ch), **kw), store


def test_in_a_card_titled_anti_stuck_the_switch_says_on_or_off(qapp):
    box, store = _box(qapp, dict(antistuck.DEFAULTS), switch_text="On")
    assert box.switch.text() == "On"
    box.switch.click()
    assert store["enabled"] is False and box.switch.text() == "Off"
    box.switch.click()
    assert box.switch.text() == "On"
    box.refresh(dict(antistuck.DEFAULTS, enabled=False))      # the store says off
    assert box.switch.text() == "Off"


def test_a_switch_that_names_itself_keeps_its_name(qapp):
    box, _store = _box(qapp, dict(antistuck.DEFAULTS, enabled=False))
    assert box.switch.text() == "Anti-stuck"
    box.switch.click()
    assert box.switch.text() == "Anti-stuck"


def test_every_switch_labelled_on_says_off_while_off(qapp):
    from ui.widgets import ToggleSwitch
    sw = ToggleSwitch("On")
    assert sw.text() == "Off"                  # made unchecked
    wide = sw.sizeHint().width()
    sw.setChecked(True)
    assert sw.text() == "On" and sw.sizeHint().width() == wide    # nothing shifts
    other = ToggleSwitch("Connect when the app starts")
    other.setChecked(True)
    other.setChecked(False)
    assert other.text() == "Connect when the app starts"
