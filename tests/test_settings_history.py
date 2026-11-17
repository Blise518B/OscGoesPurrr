"""Ctrl+Z / Ctrl+Y for the whole app (settings_history.py): one history of
the last five settings changes, recorded where the stores save.

Covered here without Qt: the diff and the write-back; coalescing a drag
into one step; a new change dropping what could be redone; the five-step
limit; only the user's own saves counting; each store's round trip (what
it leaves out, what it writes back); the safety questions; and an action
with its own way back (the Avatar Remote's drag-remove, put back through
the history). test_history_keys.py has the keys, text fields and asking."""

import json

import pytest

import settings_history as sh
from settings_history import MISSING, ById, Change, SettingsHistory


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
    """The app's one history, active for the test (stores report to it)."""
    h = SettingsHistory(clock=clock)
    old = sh.activate(h)
    yield h
    sh.activate(old)


@pytest.fixture
def paths(monkeypatch, tmp_path):
    """Every settings file in tmp_path (conftest already moves the JSON
    managers' own)."""
    import settings.app as app_mod
    import settings.known_devices as kd_mod
    import settings.sessions as ses_mod
    import settings.sps_sources as sps_mod
    monkeypatch.setattr(app_mod, "APP_SETTINGS_FILE", tmp_path / "app_settings.json")
    monkeypatch.setattr(kd_mod, "KNOWN_DEVICES_FILE", tmp_path / "known_devices.json")
    monkeypatch.setattr(ses_mod, "SESSIONS_SETTINGS_FILE", tmp_path / "sessions_settings.json")
    monkeypatch.setattr(sps_mod, "SPS_SOURCES_FILE", tmp_path / "sps_sources.json")
    return tmp_path


class Store:
    """A minimal store: what any settings manager does."""
    HISTORY_KEY = "toy"
    HISTORY_LABEL = "Toy store"

    def __init__(self, **values):
        self.settings = dict(values)
        self.saves = 0
        sh.track(self)

    def set(self, key, value):
        self.settings[key] = value
        self._save()

    def _save(self):
        self.saves += 1
        sh.saved(self)


# ---------------------------------------------------------------------------
# diff and write-back
# ---------------------------------------------------------------------------

class TestDiff:
    def test_dicts_key_by_key(self):
        a = {"x": 1, "n": {"a": 1, "b": 2}}
        b = {"x": 1, "n": {"a": 5}, "y": [1]}
        got = {(c.path, json.dumps(c.before, default=str), json.dumps(c.after, default=str))
               for c in sh.diff(a, b)}
        assert {c.path for c in sh.diff(a, b)} == {("n", "a"), ("n", "b"), ("y",)}
        assert len(got) == 3

    def test_round_trip_both_ways(self):
        a = {"f": [{"id": "a", "on": True}, {"id": "b", "on": False}], "v": 3,
             "modes": [{"n": 1}, {"n": 2}]}
        b = {"f": [{"id": "b", "on": True}, {"id": "c", "on": True}], "v": 4,
             "modes": [{"n": 1}, {"n": 9}]}
        changes = sh.diff(a, b)
        live = sh.snapshot(a)
        assert sh.apply_changes(live, changes, undo=False) == []
        assert live == b
        assert sh.apply_changes(live, changes, undo=True) == []
        assert live == a

    def test_id_lists_by_id_and_order(self):
        a = [{"id": "a", "v": 1}, {"id": "b", "v": 2}]
        b = [{"id": "b", "v": 2}, {"id": "a", "v": 3}]
        paths = {c.path for c in sh.diff(a, b)}
        assert paths == {(ById("a"), "v"), (sh.ORDER,)}

    def test_writes_land_where_the_element_is_now(self):
        """A friend's permission changes back on whoever has that id, even
        after the list moved around."""
        ch = sh.diff({"f": [{"id": "a", "t": True}]}, {"f": [{"id": "a", "t": False}]})
        live = {"f": [{"id": "z", "t": True}, {"id": "a", "t": False}]}
        sh.apply_changes(live, ch, undo=True)
        assert live == {"f": [{"id": "z", "t": True}, {"id": "a", "t": True}]}

    def test_gone_places_are_reported_not_invented(self):
        ch = [Change(("f", ById("gone"), "t"), True, False)]
        live = {"f": []}
        assert sh.apply_changes(live, ch, undo=True) == ch
        assert live == {"f": []}

    def test_int_keys_in_live_dicts(self):
        live = {"m": {0: 5}}
        sh.put(live, Change(("m", "0"), 1, 5), want_before=True)
        assert live == {"m": {0: 1}}

    def test_replaced_element_keeps_its_identity(self):
        friend = {"id": "a", "t": True, "n": "x"}
        live = {"f": [friend]}
        sh.put(live, Change(("f", ById("a")), {"id": "a", "t": False}, MISSING), want_before=True)
        assert live["f"][0] is friend and friend == {"id": "a", "t": False}


# ---------------------------------------------------------------------------
# steps
# ---------------------------------------------------------------------------

class TestSteps:
    def test_a_save_is_a_step_and_undo_redo_round_trip(self, hist):
        s = Store(a=1)
        s.set("a", 2)
        assert hist.can_undo() and not hist.can_redo()
        r = hist.undo()
        assert r.status == sh.DONE and s.settings["a"] == 1
        assert r.text.startswith("Undid: ")
        r = hist.redo()
        assert r.status == sh.DONE and s.settings["a"] == 2
        assert r.text.startswith("Redid: ")

    def test_undo_saves_the_store_and_is_no_step_itself(self, hist):
        s = Store(a=1)
        s.set("a", 2)
        saves = s.saves
        hist.undo()
        assert s.saves == saves + 1
        assert not hist.can_undo() and hist.can_redo()

    def test_a_drag_is_one_step(self, hist, clock):
        s = Store(v=0)
        for v in range(1, 30):
            clock.tick(0.05)
            s.set("v", v)
        assert len(hist.steps()) == 1
        hist.undo()
        assert s.settings["v"] == 0

    def test_one_click_writing_several_keys_and_stores_is_one_step(self, hist, clock):
        s = Store(a=1, b=1)

        class Other(Store):
            HISTORY_KEY = "other"
        o = Other(c=1)
        s.set("a", 2)
        clock.tick(0.1)
        s.set("b", 2)
        clock.tick(0.1)
        o.set("c", 2)
        assert len(hist.steps()) == 1
        hist.undo()
        assert (s.settings, o.settings) == ({"a": 1, "b": 1}, {"c": 1})

    def test_pauses_and_new_controls_start_new_steps(self, hist, clock):
        s = Store(a=0)
        s.set("a", 1)
        clock.tick(sh.COALESCE_S + 0.1)
        s.set("a", 2)
        clock.tick(0.1)
        hist.boundary()                 # the user started on another control
        s.set("a", 3)
        assert len(hist.steps()) == 3

    def test_back_and_forth_within_a_step_is_no_step(self, hist, clock):
        s = Store(a=0)
        s.set("a", 1)
        clock.tick(0.1)
        s.set("a", 0)
        assert not hist.can_undo()

    def test_a_new_change_after_undo_drops_the_redo(self, hist, clock):
        s = Store(a=0)
        s.set("a", 1)
        clock.tick()
        s.set("a", 2)
        hist.undo()
        assert hist.can_redo()
        clock.tick()
        s.set("a", 5)
        assert not hist.can_redo()
        assert hist.redo().status == sh.NOTHING
        hist.undo()
        assert s.settings["a"] == 1

    def test_keeps_the_last_five(self, hist, clock):
        s = Store(a=0)
        for v in range(1, 9):
            clock.tick()
            s.set("a", v)
        assert len(hist.steps()) == sh.LIMIT == 5
        for _ in range(7):
            hist.undo()
        assert s.settings["a"] == 3          # five back from 8, no further
        assert hist.undo().status == sh.NOTHING
        assert len(hist.redoable()) == 5
        for _ in range(5):
            hist.redo()
        assert s.settings["a"] == 8

    def test_only_the_users_own_saves(self, hist, clock):
        s = Store(a=0)
        hist.gate = lambda: False           # a friend, the avatar menu, a timer
        s.set("a", 1)
        assert not hist.can_undo()
        hist.gate = lambda: True
        clock.tick()
        s.set("a", 2)
        hist.undo()
        assert s.settings["a"] == 1          # the friend's 1 stays

    def test_undo_leaves_other_keys_alone(self, hist, clock):
        s = Store(a=0, b=0)
        s.set("a", 1)
        hist.gate = lambda: False
        s.set("b", 7)                        # not the user's: no step
        hist.undo()
        assert s.settings == {"a": 0, "b": 7}

    def test_a_debounced_save_after_undo_is_no_step(self, hist, clock):
        """An editor that changed the live dict and saves later (the chain
        editor, 600 ms) finds nothing new after the undo."""
        s = Store(a=0)
        s.set("a", 1)
        hist.undo()
        clock.tick(0.1)
        s._save()
        assert not hist.can_undo() and hist.can_redo()

    def test_labels_come_from_the_ui_or_the_store(self, hist, clock):
        s = Store(volume=1)
        hist.context = lambda: {"label": "changed “Loudness”"}
        s.set("volume", 2)
        assert hist.undo().text == "Undid: changed “Loudness”"
        hist.context = lambda: {}
        clock.tick()
        s.set("volume", 3)
        assert hist.undo().text == "Undid: changed volume (Toy store)"

    def test_replay_first_then_the_store(self, hist, clock):
        s = Store(a=0, b=0)
        calls = []

        def replay(step, undo):
            calls.append(undo)
            s.settings["a"] = 0              # the control's own path did "a"
        hist.context = lambda: {"label": "x", "control": object()}
        s.set("a", 1)
        s.set("b", 1)
        hist.undo(replay=replay)
        assert calls == [True] and s.settings == {"a": 0, "b": 0}


# ---------------------------------------------------------------------------
# safety
# ---------------------------------------------------------------------------

class Guarded(Store):
    HISTORY_KEY = "guarded"

    @staticmethod
    def history_asks(current, target):
        out = []
        if sh.turned_on(current, target, ("armed",)):
            out.append(sh.Ask("arm", "arms shocks"))
        if sh.raised(current, target, ("max",)):
            out.append(sh.Ask("confirm", "raises max"))
        return out


class TestSafety:
    def test_undo_that_would_arm_asks_and_without_asking_is_not_done(self, hist):
        s = Guarded(armed=True)
        s.set("armed", False)
        r = hist.undo()
        assert r.status == sh.BLOCKED and "arms shocks" in r.text
        assert s.settings["armed"] is False and hist.can_undo()

    def test_yes_applies_no_keeps(self, hist):
        s = Guarded(armed=True)
        s.set("armed", False)
        asked = []

        def ask(asks, text, answer):
            asked.append((asks, answer))
            return True
        r = hist.undo(ask=ask)
        assert r.status == sh.ASKING and [a.kind for a in asked[0][0]] == ["arm"]
        assert s.settings["armed"] is False      # nothing until the answer
        assert asked[0][1](False).status == sh.CANCELLED
        assert s.settings["armed"] is False and hist.can_undo()
        hist.undo(ask=ask)
        assert asked[1][1](True).status == sh.DONE
        assert s.settings["armed"] is True and hist.can_redo()

    def test_redo_that_would_raise_a_limit_asks_too(self, hist):
        s = Guarded(max=50)
        s.set("max", 80)
        assert hist.undo().status == sh.DONE     # lowering never asks
        assert hist.redo().status == sh.BLOCKED
        assert s.settings["max"] == 50

    def test_an_ask_that_cant_be_put_up_is_blocked(self, hist):
        s = Guarded(armed=True)
        s.set("armed", False)
        r = hist.undo(ask=lambda *a: False)
        assert r.status == sh.BLOCKED and s.settings["armed"] is False

    def test_a_late_yes_after_the_history_moved_on_does_nothing(self, hist, clock):
        s = Guarded(armed=True, other=0)
        s.set("armed", False)
        held = []
        hist.undo(ask=lambda asks, text, answer: held.append(answer) or True)
        clock.tick()
        s.set("other", 1)                         # a new step on top
        assert held[0](True).status == sh.CANCELLED
        assert s.settings["armed"] is False


# ---------------------------------------------------------------------------
# actions: a change with its own way back
# ---------------------------------------------------------------------------

class TestActions:
    def test_an_actions_saves_are_part_of_it(self, hist):
        s = Store(items=["a", "b"])
        taken = {}

        def undo():
            s.set("items", taken["was"])
            return True

        def redo():
            s.set("items", ["b"])
            return True
        with hist.action() as act:
            taken["was"] = list(s.settings["items"])
            s.set("items", ["b"])
        act.done("removed a", undo, redo)
        assert len(hist.steps()) == 1 and hist.steps()[0].action is not None
        assert hist.undo().text == "Undid: removed a"
        assert s.settings["items"] == ["a", "b"] and not hist.can_undo()
        assert hist.redo().text == "Redid: removed a"
        assert s.settings["items"] == ["b"]

    def test_an_action_that_cant_be_undone_says_why_and_stays(self, hist):
        with hist.action() as act:
            pass
        act.done("removed a", lambda: "its board isn't open", lambda: True)
        r = hist.undo()
        assert r.status == sh.FAILED and "its board isn't open" in r.text
        assert hist.can_undo()

    def test_no_active_history_is_harmless(self):
        old = sh.activate(None)
        try:
            with sh.action() as act:
                pass
            act.done("x", lambda: True, lambda: True)
            Store(a=1).set("a", 2)
        finally:
            sh.activate(old)


# ---------------------------------------------------------------------------
# the real stores
# ---------------------------------------------------------------------------

class TestStores:
    def test_app_settings_round_trip_and_what_is_left_out(self, hist, paths, clock):
        from settings.app import AppSettingsManager
        app = AppSettingsManager()
        app.set("toy_antistuck_active_s", 3)
        clock.tick()
        app.set("window_state", "abc")            # where the window is
        app.set("home_setup_compact", True)       # a fold
        app.set("whats_new_seen_version", "9.9")  # what you were shown
        assert len(hist.steps()) == 1
        r = hist.undo()
        assert app.get("toy_antistuck_active_s") == 1
        assert app.get("window_state") == "abc"
        assert "Toys' anti-stuck" in r.text
        saved = json.loads((paths / "app_settings.json").read_text("utf-8"))
        assert saved["toy_antistuck_active_s"] == 1

    def test_modes_round_trip(self, hist, paths, clock):
        from config_manager import ModeManager
        mm = ModeManager()
        mm.update_device_config("Lush", "motor_count", 1)
        mm.update_device_config("Lush", "mix", {"0": {"gain": 1.0}})
        mm.save_profiles()
        hist.clear()
        clock.tick()
        mm.wiring["Lush"]["mix"]["0"]["gain"] = 0.4    # the chain editor, in place
        mm.set_strength(0.5)
        mm.save_profiles()
        clock.tick()
        mm.set_active_mode(2)
        assert len(hist.steps()) == 2
        hist.undo()
        assert mm.active_mode == 0
        assert mm.wiring["Lush"]["osc_addresses"] is not None   # layers installed
        hist.undo()
        assert mm.get_strength() == ModeManager.DEFAULT_STRENGTH
        assert mm.feel["Lush"]["0"]["gain"] == 1.0
        assert mm.wiring["Lush"]["mix"] is mm.feel["Lush"]      # still one copy
        hist.redo()
        assert mm.feel["Lush"]["0"]["gain"] == 0.4 and mm.get_strength() == 0.5

    def test_a_forgotten_toy_comes_back(self, hist, paths, clock):
        from config_manager import ModeManager
        mm = ModeManager()
        mm.known_devices.register("Lush", 1)
        mm.update_device_config("Lush", "motor_count", 1)
        mm.update_device_config("Lush", "mix", {"0": {"gain": 0.7}})
        mm.save_profiles()
        hist.clear()
        clock.tick()
        mm.delete_device("Lush")                 # Forget toy
        mm.known_devices.forget("Lush")
        hist.undo()
        assert mm.feel["Lush"]["0"]["gain"] == 0.7
        assert "Lush" in mm.known_devices.all()  # its card comes back

    def test_modes_new_toy_and_avatar_memory_are_no_steps(self, hist, paths):
        from config_manager import ModeManager
        mm = ModeManager()
        hist.clear()
        mm.update_device_config("Edge", "motor_count", 2)      # a toy seen first
        mm.avatar_last_mode["avtr_x"] = 1
        mm.save_profiles()
        assert not hist.can_undo()

    def test_pishock_round_trip_and_its_questions(self, hist, clock):
        from settings.pishock import PiShockSettingsManager
        s = PiShockSettingsManager()
        s.set_limit("max_intensity", 20)
        clock.tick()
        s.set_armed(True)
        clock.tick()
        s.set_armed(False)
        r = hist.undo()                       # would arm again
        assert r.status == sh.BLOCKED and "arms shocks" in r.text
        assert s.get_armed() is False
        answers = []
        assert hist.undo(ask=lambda a, t, ans: answers.append((a, ans)) or True).status \
            == sh.ASKING
        assert [x.kind for x in answers[0][0]] == ["arm"]
        answers[0][1](True)
        assert s.get_armed() is True
        assert hist.undo().status == sh.DONE  # disarming never asks
        assert s.get_armed() is False
        r = hist.undo()                       # the cap from 20 back to 30: raised
        assert r.status == sh.BLOCKED and "“Up to shock strength” to 30" in r.text
        assert s.get_limits()["max_intensity"] == 20

    def test_pishock_questions(self):
        from settings.pishock import history_asks
        base = {"armed": False, "enabled": True, "friends_may_use": True,
                "shockers_off": [], "shocker_ops_off": {}, "shocker_limits": {},
                "shocker_names": {"7": "Collar"}, "openshock_shockers": [],
                "max_intensity": 30, "max_vibrate": 30, "max_pulse_ms": 1000,
                "cooldown_s": 0.5, "max_hold_s": 10.0, "hold_rest_s": 2.0}

        def asks(cur, tgt):
            return [a.text for a in history_asks({**base, **cur}, {**base, **tgt})]
        assert asks({}, {}) == []
        assert asks({"armed": True}, {"armed": False}) == []
        assert asks({"shockers_off": [7]}, {}) == ["switches Collar back on"]
        assert asks({"shocker_ops_off": {"7": ["shock"]}}, {}) == \
            ["switches Collar's Shock back on"]
        assert asks({}, {"shocker_ops_off": {"7": ["shock"]}}) == []
        assert asks({"enabled": False}, {}) == ["switches your shockers back on"]
        assert asks({"friends_may_use": False}, {}) == \
            ["shares your shockers with friends again"]
        assert asks({}, {"max_intensity": 40}) == ["sets “Up to shock strength” to 40"]
        assert asks({}, {"max_intensity": 20}) == []
        assert asks({}, {"cooldown_s": 0.2}) == ["sets “At least a rest of” to 0.2 s"]
        assert asks({}, {"cooldown_s": 3.0}) == []
        assert asks({"shocker_limits": {"7": {"max_intensity": 10}}}, {}) == \
            ["sets Collar's “Up to shock strength” to 30"]
        # Separate limits for friends: switching it on loosens, and so does
        # raising a value in the friends' set while it is on
        assert asks({}, {"separate_limits": True}) == ["gives friends separate limits"]
        assert asks({"separate_limits": True}, {}) == []
        on = {"separate_limits": True}
        assert asks({**on, "friend_limits": {"max_hold_s": 10.0}},
                    {**on, "friend_limits": {"max_hold_s": 30.0}}) == \
            ["sets friends' “Up to a hold of” to 30 s"]
        assert asks({**on, "friend_limits": {"hold_rest_s": 2.0}},
                    {**on, "friend_limits": {"hold_rest_s": 1.0}}) == \
            ["sets friends' “Then a forced break of” to 1 s"]
        assert asks({**on, "friend_limits": {"max_hold_s": 30.0}},
                    {**on, "friend_limits": {"max_hold_s": 10.0}}) == []
        assert asks({}, {"cooldown_s": 3.0, "friend_limits": {"cooldown_s": 0.1}}) == []
        # the friends' own caps (2026-11-17): raising one asks, lowering never
        assert asks({**on, "friend_limits": {"max_intensity": 20}},
                    {**on, "friend_limits": {"max_intensity": 60}}) == \
            ["sets friends' “Up to shock strength” to 60"]
        assert asks({**on, "friend_limits": {"max_pulse_ms": 500}},
                    {**on, "friend_limits": {"max_pulse_ms": 2000}}) == \
            ["sets friends' “Up to a pulse of” to 2 s"]
        assert asks({**on, "friend_limits": {"max_vibrate": 60}},
                    {**on, "friend_limits": {"max_vibrate": 20}}) == []

    def test_friends_round_trip_and_what_is_left_out(self, hist, clock):
        from settings.friends import FriendsSettingsManager
        a = "a" * 64
        s = FriendsSettingsManager()
        s.add_friend(a, "Mika")                  # adding talks to them: no step
        assert not hist.can_undo()
        clock.tick()
        s.set_permission(a, "toys", False)
        clock.tick()
        s.set_nick_of(a, "Mika2")                # their own nickname
        s.set_selected("friend", a)              # what the page shows
        assert len(hist.steps()) == 1
        hist.undo()                              # toys back on: they get more
        assert s.get_friend(a)["toys"] is False
        hist.undo(ask=lambda asks, t, ans: ans(True) and True)
        assert s.get_friend(a)["toys"] is True
        assert s.get_friend(a)["nick"] == "Mika2"

    def test_friends_questions(self):
        from settings.friends import history_asks
        a = "a" * 64
        f = {"id": a, "nick": "Mika", "toys": True, "shock": True, "params": True}

        def asks(cur, tgt):
            return [x.text for x in history_asks(cur, tgt)]
        cur = {"friends": [{**f, "toys": False}], "paused": True, "web": {}}
        tgt = {"friends": [f], "paused": False, "web": {}}
        assert asks(cur, tgt) == ["lets your friends drive you again (Pause all friends off)",
                                  "lets Mika drive your toys again"]
        assert asks(tgt, cur) == []
        # a share left in an old file asks nothing: there's no share any more
        narrow = {**f, "share": {"max": 20}}
        assert asks({"friends": [narrow]}, {"friends": [f]}) == []
        assert asks({"web": {"shock": False}}, {"web": {"shock": True}}) == \
            ["lets the web remote use your shockers"]

    def test_param_boards_round_trip_and_what_is_left_out(self, hist, clock):
        import param_board as pb
        from settings.param_boards import ParamBoardsSettingsManager
        s = ParamBoardsSettingsManager()
        book = pb.BoardBook(s)
        book.avatar_changed("avtr_1")
        book.rename_avatar("Fox")                # its whole profile came: no step
        assert not hist.can_undo()
        clock.tick()
        cat = book.add_category("Ears")
        assert hist.can_undo()
        hist.undo()
        assert pb.find_category(book.board, cat["id"]) is None
        hist.redo()
        assert pb.find_category(book.board, cat["id"]) is not None
        clock.tick()
        s.set_last_avatar("avtr_2")              # which board is open
        book.set_vrchat_name("Fox in VRChat")    # what VRChat calls it
        assert len(hist.steps()) == 1

    def test_param_boards_unlock_asks(self, hist, clock):
        import param_board as pb
        from settings.param_boards import ParamBoardsSettingsManager
        s = ParamBoardsSettingsManager()
        book = pb.BoardBook(s)
        book.avatar_changed("avtr_1")
        book.rename_avatar("Fox")
        cat = book.board["categories"][0]
        clock.tick()
        book.set_category_locked(cat["id"], True)
        r = hist.undo()                          # unlocking: friends get more
        assert r.status == sh.BLOCKED and "unlocks" in r.text
        assert cat["locked"] is True

    def test_param_boards_yolo_asks(self, hist):
        from settings.param_boards import ParamBoardsSettingsManager
        s = ParamBoardsSettingsManager()
        s.set_yolo(True)
        hist.clear()
        s.set_yolo(False)
        r = hist.undo()
        assert r.status == sh.BLOCKED and "YOLO" in r.text and s.get_yolo() is False

    def test_suits_ceiling_asks(self, hist):
        from settings.suits import SuitsSettingsManager
        s = SuitsSettingsManager()
        s.set_owo_option("global_max", 40)
        r = hist.undo()                          # 40 back to 60: raises it
        assert r.status == sh.BLOCKED and "OWO" in r.text

    def test_psvr2_round_trip(self, hist):
        from settings.psvr2 import PSVR2SettingsManager
        s = PSVR2SettingsManager()
        s.set_auto_connect(False)
        hist.undo()
        assert s.get_auto_connect() is True

    def test_sessions_and_sps_round_trip(self, hist, paths, clock):
        from settings.sessions import SessionSettingsManager
        from settings.sps_sources import SpsSourceManager
        ses = SessionSettingsManager()
        ses.set_retention(5)
        hist.undo()
        assert ses.get_retention() == 20
        sps = SpsSourceManager()
        clock.tick()
        sps.add_or_update_source({"name": "Hand", "type": "Orf"})
        assert [x["name"] for x in sps.list_sources()] == ["Hand"]
        hist.undo()
        assert sps.list_sources() == []
        hist.redo()
        assert [x["name"] for x in sps.list_sources()] == ["Hand"]


# ---------------------------------------------------------------------------
# drag-remove (row 7) through the history
# ---------------------------------------------------------------------------

class Host:
    """Enough of the Params facade for params_edit."""

    def __init__(self, store):
        import param_board as pb
        self._params_book = pb.BoardBook(store)
        self.changed = 0

    def _params_changed(self):
        self.changed += 1


def _board_with_ears(hist):
    import param_board as pb
    from settings.param_boards import ParamBoardsSettingsManager
    s = ParamBoardsSettingsManager()
    host = Host(s)
    book = host._params_book
    book.avatar_changed("avtr_1")
    book.rename_avatar("Fox")
    book.add_control("Ears", "toggle", "Ears")
    book.add_control("Tail", "toggle", "Tail")
    hist.clear()
    return s, host, book, pb


def test_drag_remove_is_one_step_put_back_by_ctrl_z(hist, clock):
    from controllers.params_facade import ParamsFacade
    s, host, book, pb = _board_with_ears(hist)
    control = next(c for c in book.board["controls"] if c["label"] == "Ears")
    clock.tick()
    snap = ParamsFacade._params_take(host, "take_control", control["id"])
    assert snap and pb.find_control(book.board, control["id"]) is None
    steps = hist.steps()
    assert len(steps) == 1 and steps[0].action is not None and steps[0].action.key is snap
    r = hist.undo()
    assert r.text == "Undid: removed Ears from the Avatar Remote"
    assert [c["label"] for c in book.board["controls"]] == ["Ears", "Tail"]   # where it was
    saved = json.loads(s.FILE_PATH.read_text("utf-8"))
    assert any(c["label"] == "Ears" for p in saved["avatars"]["avtr_1"]["presets"]
               for c in p["controls"])
    r = hist.redo()
    assert r.status == sh.DONE and pb.find_control(book.board, control["id"]) is None
    hist.undo()                                    # the redone take's own snapshot
    assert pb.find_control(book.board, control["id"]) is not None


def test_a_whole_category_dragged_back(hist, clock):
    from controllers.params_facade import ParamsFacade
    s, host, book, pb = _board_with_ears(hist)
    cat = book.add_category("Extra")
    book.add_control("Wings", "toggle", "Wings", category=cat["id"])
    hist.clear()
    clock.tick()
    ParamsFacade._params_take(host, "take_category", cat["id"])
    assert hist.undo().text == "Undid: removed Extra from the Avatar Remote"
    assert pb.find_category(book.board, cat["id"]) is not None
    assert any(c["label"] == "Wings" for c in book.board["controls"])


def test_drag_remove_on_another_board_says_so_and_waits(hist, clock):
    from controllers.params_facade import ParamsFacade
    s, host, book, pb = _board_with_ears(hist)
    control = next(c for c in book.board["controls"] if c["label"] == "Ears")
    ParamsFacade._params_take(host, "take_control", control["id"])
    hist.gate = lambda: False                     # making a preset: not this test's step
    first = book.board["id"]
    book.add_preset("Other")
    assert book.board["id"] != first
    hist.gate = lambda: True
    r = hist.undo()
    assert r.status == sh.FAILED and "board again first" in r.text
    assert hist.can_undo()
    clock.tick()
    book.switch_preset(first)                     # which preset is open: no step
    assert hist.undo().status == sh.DONE
    assert pb.find_control(book.board, control["id"]) is not None


# ---------------------------------------------------------------------------
# the re-apply hooks: an undo reaches the engine like the change by hand
# ---------------------------------------------------------------------------

class _Recorder:
    def __init__(self, **attrs):
        self.calls = []
        self.__dict__.update(attrs)

    def __getattr__(self, name):
        if name.startswith("__"):
            raise AttributeError(name)
        return lambda *a, **k: self.calls.append((name, a))


def test_an_undone_arm_and_stop_reach_the_shocker_engine(hist, clock):
    import queue
    from controllers.history_facade import HistoryFacade
    from controllers.pishock_facade import PiShockFacade
    from settings.pishock import PiShockSettingsManager

    class Host(HistoryFacade, PiShockFacade):
        def log_message(self, m):
            self.logged.append(m)

    host = Host()
    host.logged = []
    host.thread_queue = queue.Queue()
    host.pishock_settings = PiShockSettingsManager()
    host.pishock_engine = _Recorder(is_armed=False, is_paused=False)
    host.pishock_router = _Recorder()
    host._friend_perms = {}
    hist.on_restored(host.pishock_settings, host._history_pishock_restored)
    s = host.pishock_settings
    s.set_armed(True)
    clock.tick()
    s.set_armed(False)
    clock.tick()
    host.pishock_stop_all()                      # Stop all, by hand
    host.pishock_engine.is_paused = True
    yes = lambda asks, text, answer: answer(True) is not None   # noqa: E731
    hist.undo(ask=yes)                           # back on: asked, yes
    assert ("set_paused", (False,)) in host.pishock_engine.calls
    assert ("rules_changed", ()) in host.pishock_router.calls
    hist.undo(ask=yes)                           # armed again: asked, yes
    assert ("set_armed", (True,)) in host.pishock_engine.calls
    assert "Shockers: shocks ARMED" in host.logged
    assert host.thread_queue.get_nowait() == ("pishock_state", None)    # page + Home redraw


# ---------------------------------------------------------------------------
# wave 3's settings: only friends in my instance, the Height box, the tour,
# statistics' names
# ---------------------------------------------------------------------------

def test_instance_only_questions():
    from settings.friends import history_asks
    a = "a" * 64
    f = {"id": a, "nick": "Mika", "toys": True, "shock": True, "params": True,
         "anywhere": False}

    def asks(cur, tgt):
        return [x.text for x in history_asks(cur, tgt)]
    assert asks({"instance_only": True}, {"instance_only": False}) == [
        "lets friends drive you from outside your VRChat instance again "
        "(Only friends in my instance off)"]
    assert asks({"instance_only": False}, {"instance_only": True}) == []
    assert asks({"friends": [f]}, {"friends": [{**f, "anywhere": True}]}) == \
        ["lets Mika drive you from anywhere"]
    assert asks({"friends": [{**f, "anywhere": True}]}, {"friends": [f]}) == []
    assert asks({"web": {"anyway": False}}, {"web": {"anyway": True}}) == \
        ["lets the web remote drive you while only friends in your instance may"]
    assert asks({"web": {"anyway": True}}, {"web": {"anyway": False}}) == []



def test_sync_with_others_is_an_ordinary_step_that_never_asks():
    """The owner's Sync with others (Blise's call, 2026-11-17): neither way
    loosens anything, so its undo just happens, named as the switch."""
    from settings.friends import FriendsSettingsManager, history_asks
    assert history_asks({"sync": True}, {"sync": False}) == []
    assert history_asks({"sync": False}, {"sync": True}) == []
    s = FriendsSettingsManager()
    assert s.get_sync_all() is True                       # on by default
    assert s.history_describe(("sync",)) == "Sync with others"


def test_height_box_questions():
    import avatar_height as ah
    from settings.param_boards import history_asks
    base = dict(ah.DEFAULTS)

    def asks(cur, tgt):
        return [x.text for x in history_asks({"height": {**base, **cur}},
                                             {"height": {**base, **tgt}})]
    assert asks({}, {}) == []
    assert asks({"on": False}, {"on": True}) == \
        ["switches the Height box on - friends you allow see it"]
    assert asks({"on": True}, {"on": False}) == []
    assert asks({"locked": True}, {"locked": False}) == ["unlocks the Height box for friends"]
    assert asks({"locked": False}, {"locked": True}) == []
    assert asks({"lo": 0.5, "hi": 3.0}, {"lo": 0.3, "hi": 3.0}) == \
        ["widens the Height box to 0.3-3 m"]
    assert asks({"lo": 0.5, "hi": 3.0}, {"lo": 0.5, "hi": 4.0}) == \
        ["widens the Height box to 0.5-4 m"]
    assert asks({"lo": 0.5, "hi": 3.0}, {"lo": 0.8, "hi": 2.0}) == []
    assert asks({"double_s": 8.0}, {"double_s": 2.0}) == []     # a faster Grow: no


def test_height_box_round_trip_asks_and_reaches_the_box(hist, clock):
    from controllers.history_facade import HistoryFacade
    from settings.param_boards import ParamBoardsSettingsManager

    class Height:
        double_s = 4.0
        stopped = 0

        def stop_friends(self):
            self.stopped += 1
            return True

    class Host(HistoryFacade):
        def __init__(self):
            self.params_settings = ParamBoardsSettingsManager()
            self._params_book = _Recorder()
            self._height = Height()
            self.changed = 0

        def _params_changed(self):
            self.changed += 1

    host = Host()
    s = host.params_settings
    hist.on_restored(s, host._history_params_restored)
    s.set_height({**s.get_height(), "double_s": 8.0})
    assert hist.undo().status == sh.DONE            # Grow speed: no question
    assert host._height.double_s == 4.0 and host.changed == 1
    clock.tick()
    s.set_height({**s.get_height(), "on": False})
    r = hist.undo()                                 # back on: friends see it
    assert r.status == sh.BLOCKED and s.get_height()["on"] is False
    hist.undo(ask=lambda asks, t, answer: answer(True) is not None)
    assert s.get_height()["on"] is True
    hist.redo()                                     # off again: never asks
    assert s.get_height()["on"] is False and host._height.stopped == 1


def test_the_tour_offer_is_no_step_statistics_names_are(hist, paths, clock):
    from settings.app import AppSettingsManager
    app = AppSettingsManager()
    app.set("tour_offered", True)
    assert not hist.can_undo()
    clock.tick()
    app.set("stats_friend_names", False)
    assert hist.undo().status == sh.DONE            # no question: names only
    assert app.get("stats_friend_names", True) is True


def test_undoing_allow_from_anywhere_reaches_who_is_not_here(hist, clock):
    """The restore does what the setters do: who is not here is worked out
    again, so a friend who loses Allow from anywhere stops at once."""
    from test_friends_facade import A
    from test_friends_vrchat import RIN, SAM, VHost
    from controllers.history_facade import HistoryFacade

    class Host(HistoryFacade, VHost):
        pass

    host = Host()
    host.befriend(A, shock=True)
    host.link_friend_vrchat(A, RIN, "Rin")
    host.set_friends_instance_only(True)
    host.here((SAM, "Sam"))                          # Alex (Rin) is elsewhere
    host._instance_refresh()
    assert host.friend_not_here(A)
    hist.on_restored(host.friends_settings, host._history_friends_restored)
    hist.clear()
    clock.tick()
    host.set_friend_anywhere(A, True)
    assert not host.friend_not_here(A)
    assert hist.undo().status == sh.DONE             # narrowing: no question
    assert host.friend_not_here(A)
    assert hist.redo().status == sh.BLOCKED          # widening asks
    assert host.friend_not_here(A)
    hist.redo(ask=lambda asks, t, answer: answer(True) is not None)
    assert not host.friend_not_here(A)
    host.set_friend_anywhere(A, False)
    clock.tick()
    host.set_friends_instance_only(False)
    assert not host.friend_not_here(A)
    assert hist.undo().status == sh.DONE             # instance-only back on: narrowing
    assert host.get_friends_instance_only() is True
    assert host.friend_not_here(A)                   # Alex is elsewhere: stopped again
    assert host.log_text().count("Only friends in your VRChat instance may drive you now") == 2
    assert hist.redo().status == sh.BLOCKED          # off again lets them in: asks
    assert host.get_friends_instance_only() is True
