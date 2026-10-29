"""PiShockFacade: nothing runs while the feature is off (its default), the
UI's status/rule calls work without a hub, and rule edits reach the
router."""

import queue

from controllers.pishock_facade import FEATURE_KEY, PiShockFacade


class Host(PiShockFacade):
    def __init__(self, feature_on=False):
        self.thread_queue = queue.Queue()
        self.logged = []
        self._features = {FEATURE_KEY: feature_on}

    def is_output_off(self):
        return False

    def get_feature_enabled(self, key):
        return self._features.get(key, True)

    def log_message(self, msg):
        self.logged.append(msg)


def test_feature_off_starts_nothing():
    host = Host()
    host._pishock_init()
    try:
        assert host.pishock_router._thread is None
        assert host.pishock_engine._supervisor is None
        st = host.get_pishock_status()
        assert st["connected"] is False
        assert st["armed"] is False
        assert st["auto_connect"] is False
    finally:
        host._pishock_shutdown()


def test_rule_edits_reach_the_router():
    host = Host()
    host._pishock_init()
    try:
        idx = host.add_pishock_rule("triggers")
        rule = host.get_pishock_rules("triggers")[idx]
        rule["param"] = "Contact/Boop"
        host.set_pishock_rule("triggers", idx, rule)
        assert "Contact/Boop" in host.pishock_router._keys
        host.delete_pishock_rule("triggers", idx)
        assert "Contact/Boop" not in host.pishock_router._keys
    finally:
        host._pishock_shutdown()


def test_testing_without_a_hub_only_says_so():
    host = Host()
    host._pishock_init()
    try:
        assert host.pishock_test("vibrate") is False
        assert any("connect" in m for m in host.logged)
    finally:
        host._pishock_shutdown()


def test_limits_are_pushed_to_the_engine():
    host = Host()
    host._pishock_init()
    try:
        host.set_pishock_limit("max_intensity", 12)
        assert host.pishock_engine.limits()["max_intensity"] == 12
    finally:
        host._pishock_shutdown()


def test_feature_on_starts_the_router():
    host = Host(feature_on=True)
    host._pishock_init()
    try:
        assert host.pishock_router._thread is not None
        assert host.pishock_router._thread.is_alive()
    finally:
        host._pishock_shutdown()
    host.pishock_router._thread.join(timeout=1.0)
    assert not host.pishock_router._thread.is_alive()


def test_openshock_list_edits_reach_the_engine():
    host = Host()
    host._pishock_init()
    try:
        idx = host.add_openshock_shocker()
        sid = host.get_openshock_shockers()[idx]["id"]
        assert [s["id"] for s in host.pishock_engine._os_shockers] == [sid]
        st = host.get_pishock_status()
        assert st["openshock_shockers"][0]["id"] == sid
        assert st["hub_kind"] == ""
        host.delete_openshock_shocker(idx)
        assert host.pishock_engine._os_shockers == []
    finally:
        host._pishock_shutdown()


def test_testing_one_shocker_without_a_hub_only_says_so():
    host = Host()
    host._pishock_init()
    try:
        assert host.pishock_test("beep", 1234) is False
    finally:
        host._pishock_shutdown()


def test_the_home_sharing_switch_is_kept_and_drops_what_friends_sent():
    host = Host()
    host._pishock_init()
    dropped, notes = [], []
    host._friend_perms = {"a": (True, True, True), "b": (True, False, True)}
    host._drop_shocks = dropped.append
    host._friends_note = notes.append
    try:
        assert host.get_pishock_status()["friends_may_use"] is True
        host.set_pishock_friends_may_use(False)
        assert host.get_pishock_status()["friends_may_use"] is False
        assert dropped == ["a", "b"]
        assert notes == ["Your shockers are no longer shared with friends"]
        host.set_pishock_friends_may_use(False)          # no change, no note
        assert len(notes) == 1
        host.set_pishock_friends_may_use(True)
        assert notes[-1] == "Friends may use your shockers again"
    finally:
        host._pishock_shutdown()


def test_switched_off_stays_off_after_a_restart():
    host = Host()
    host._pishock_init()
    try:
        host.pishock_stop_all()
        assert host.get_pishock_status()["paused"] is True
    finally:
        host._pishock_shutdown()
    again = Host()
    again._pishock_init()                  # the next launch
    try:
        assert again.get_pishock_status()["paused"] is True
        again.pishock_resume()
        assert again.pishock_settings.get_enabled() is True
    finally:
        again._pishock_shutdown()


def test_arm_shocks_is_remembered_across_launches():
    # Blise's call (2026-10-28): it used to switch itself off every launch
    host = Host()
    host._pishock_init()
    try:
        host.set_pishock_armed(True)
    finally:
        host._pishock_shutdown()
    again = Host()
    again._pishock_init()
    try:
        assert again.pishock_engine.is_armed is True
        assert again.get_pishock_status()["armed"] is True
        again.set_pishock_armed(False)
    finally:
        again._pishock_shutdown()
    third = Host()
    third._pishock_init()
    try:
        assert third.pishock_engine.is_armed is False
    finally:
        third._pishock_shutdown()


def test_a_shockers_own_limit_reaches_the_engine():
    host = Host()
    host._pishock_init()
    try:
        host.set_pishock_shocker_limit(24325, "max_intensity", 7)
        assert host.pishock_engine.limits_for(24325)["max_intensity"] == 7
        assert host.pishock_engine.limits_for(1)["max_intensity"] == 30
    finally:
        host._pishock_shutdown()


def test_a_shocker_switched_off_reaches_the_engine_and_the_status():
    host = Host()
    host._pishock_init()
    try:
        host.set_pishock_shocker_on(24326, False)
        assert 24326 in host.pishock_engine._off
        st = host.get_pishock_status()
        assert st["shockers_off"] == [24326] and "all_shockers" in st
        assert any("not in use" in m for m in host.logged)
        host.set_pishock_shocker_on(24326, True)
        assert host.pishock_engine._off == set()
    finally:
        host._pishock_shutdown()
