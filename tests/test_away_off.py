"""Off while you're away: VRChat's AFK, GoGo Loco's AFK button and picked
parameters hold everything off -- the same Off as OGP/Off -- without
touching the user's own Off switch, and let go by themselves.

Three layers: the pure sources (away_off.py), the controller mixin on a
real ModeManager (controllers/away_facade.py with the modes facade, as
OscGoesPurrrApp composes them), and the settings round-trip through the
real AppSettingsManager on tmp_path."""

import json
import queue
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import away_off
import config_manager
from config_manager import ModeManager
from controllers import away_facade
from controllers.away_facade import AwayFacade
from controllers.modes_facade import ModesFacade
from controllers.osc_facade import OscFacade
from parameter_store import ParameterStore

from test_modes_core import _StubKnownDevices, _StubSettings  # noqa: E402


# ---------------------------------------------------------------------------
# The sources
# ---------------------------------------------------------------------------

def _settings(**over):
    s = dict(away_off.DEFAULTS)
    s.update(over)
    return lambda key, default=None: s.get(key, default)


class TestDefaults:
    def test_on_by_default_with_both_built_in_sources(self):
        assert away_off.DEFAULTS == {
            "away_off_enabled": True, "away_off_vrchat_afk": True,
            "away_off_gogo_afk": True, "away_off_params": []}

    def test_the_app_settings_carry_the_same_defaults(self):
        from settings.app import DEFAULT_APP_SETTINGS
        for key, value in away_off.DEFAULTS.items():
            assert DEFAULT_APP_SETTINGS[key] == value

    def test_the_parameters_are_vrchats_and_gogo_locos(self):
        # VRChat's built-in; GoGo Loco 1.8.6's AFK button sets VRCEmote 101.
        assert away_off.VRCHAT_AFK_PARAMETER == "AFK"
        assert (away_off.GOGO_AFK_PARAMETER, away_off.GOGO_AFK_VALUE) == ("VRCEmote", 101)

    def test_default_sources(self):
        sources = away_off.compile_sources(_settings())
        assert [(n, label) for n, label, _t in sources] == [
            ("AFK", "AFK"), ("VRCEmote", "GoGo Loco AFK")]
        assert away_off.watched(sources) == frozenset({"AFK", "VRCEmote"})


class TestSources:
    def test_switched_off_watches_nothing(self):
        assert away_off.compile_sources(_settings(away_off_enabled=False,
                                                  away_off_params=["Mine"])) == ()

    def test_each_built_in_source_can_be_left_out(self):
        only_gogo = away_off.compile_sources(_settings(away_off_vrchat_afk=False))
        assert away_off.watched(only_gogo) == {"VRCEmote"}
        only_afk = away_off.compile_sources(_settings(away_off_gogo_afk=False))
        assert away_off.watched(only_afk) == {"AFK"}

    def test_picked_parameters_follow_the_built_ins(self):
        sources = away_off.compile_sources(_settings(
            away_off_params=["/avatar/parameters/MyOff", "Other"]))
        assert [n for n, _l, _t in sources] == ["AFK", "VRCEmote", "MyOff", "Other"]

    def test_clean_params(self):
        assert away_off.clean_params(
            ["/avatar/parameters/A", " B ", "", "A", 5, None, "/C"]) == ["A", "B", "C"]
        assert away_off.clean_params("not a list") == []
        assert away_off.clean_params(None) == []


class TestHolding:
    sources = away_off.compile_sources(_settings(away_off_params=["Mine"]))

    def _held(self, **values):
        return away_off.holding(self.sources, values)

    def test_nothing_on_holds_nothing(self):
        assert self._held() == ()
        assert self._held(AFK=False, VRCEmote=0, Mine=False) == ()

    def test_vrchats_afk(self):
        assert self._held(AFK=True) == ("AFK",)

    def test_gogo_locos_afk_is_vrcemote_101_only(self):
        assert self._held(VRCEmote=101) == ("GoGo Loco AFK",)
        assert self._held(VRCEmote=101.0) == ("GoGo Loco AFK",)
        for other in (0, 1, 7, 100, 102, True):
            assert self._held(VRCEmote=other) == ()

    @pytest.mark.parametrize("value,on", [
        (True, True), (False, False), (1, True), (3, True), (0, False),
        (-1, False), (0.4, True), (0.0, False), (float("nan"), False),
        ("yes", False), (None, False),
    ])
    def test_a_picked_parameter_is_on_while_true_or_above_zero(self, value, on):
        assert (self._held(Mine=value) == ("Mine",)) is on

    def test_several_at_once_in_order(self):
        assert self._held(Mine=True, AFK=True, VRCEmote=101) == (
            "AFK", "GoGo Loco AFK", "Mine")

    def test_a_label_counts_once(self):
        sources = away_off.compile_sources(_settings(away_off_params=["AFK"]))
        assert away_off.holding(sources, {"AFK": True}) == ("AFK",)

    def test_status_text(self):
        assert away_off.status_text(()) == ""
        assert away_off.status_text(("AFK",)) == "AFK: everything off"
        assert away_off.status_text(("AFK", "Mine")) == "AFK, Mine: everything off"


# ---------------------------------------------------------------------------
# The hold, on a real ModeManager
# ---------------------------------------------------------------------------

@pytest.fixture
def isolated(monkeypatch, tmp_path):
    monkeypatch.setattr(config_manager, "MODES_FILE", tmp_path / "modes.json")
    for name in ("AppSettingsManager", "SpsSourceManager"):
        monkeypatch.setattr(config_manager, name, _StubSettings)
    monkeypatch.setattr(config_manager, "KnownDevicesRegistry", _StubKnownDevices)
    # A store of the test's own, never the app-wide one.
    fresh = ParameterStore()
    monkeypatch.setattr(away_facade, "store", fresh)
    return fresh


class _StubMotorRouter:
    def __init__(self):
        self.resets = 0

    def reset_outputs(self):
        self.resets += 1


class _StubOsc:
    is_connected = True

    def __init__(self):
        self.sent = []

    def send_parameter(self, address, value, **kwargs):
        self.sent.append((address, value))


class _StubUI:
    def __init__(self):
        self.held = []
        self.refreshes = 0

    def show_away_hold(self, text):
        self.held.append(text)

    def refresh_output_controls(self):
        self.refreshes += 1

    def update_osc_status(self, is_connected, port=None):
        pass


class _Host(ModesFacade, AwayFacade, OscFacade):
    def __init__(self, mm):
        self.mode_manager = mm
        self.ui = _StubUI()
        self.logs = []
        self.osc_manager = _StubOsc()
        self.motor_router = _StubMotorRouter()
        self._muted_devices = set()
        self.thread_queue = queue.Queue()
        self.recalcs = 0

    def log_message(self, msg):
        self.logs.append(msg)

    def get_app_setting(self, key, default=None):
        return self.mode_manager.app_settings.get(key, default)

    def force_recalculate(self, dispatch_direct=False):
        self.recalcs += 1

    # The VRChat side: a packet writes the store, then the callback runs
    # (vrchat_osc's order), then the GUI thread drains the queue.
    def packet(self, store, name, value):
        store.update_parameter(name, value)
        self.on_osc_message(name, value)
        self.drain()

    def drain(self):
        while not self.thread_queue.empty():
            msg_type, data = self.thread_queue.get_nowait()
            if msg_type == "away_check":
                self._away_check()
            elif msg_type == "osc_status" and not data[0]:
                self._away_vrchat_gone()        # main.process_async_queue

    # VRChat closing, as VRChatOSCManager._handle_disconnect does it: the
    # status notice through the callback, then on_disconnected's queue
    # message. The store keeps that session's values.
    def vrchat_closes(self):
        self.on_osc_message("SYS/OSCQuery_Status",
                            "VRChat disconnected (VRChat mDNS service removed). Waiting...")
        self.thread_queue.put(("osc_status", (False, 9001)))
        self.drain()

    # VRChat coming back: connected, then the store rebuilt from its live
    # OSCQuery tree (vrchat_osc._do_fetch_all_parameters).
    def vrchat_returns(self, store, **params):
        self.thread_queue.put(("osc_status", (True, 9001)))
        contents = {k: {"VALUE": [v]} for k, v in params.items()}
        store.rebuild_from_json({"CONTENTS": {"avatar": {"CONTENTS": {
            "parameters": {"CONTENTS": contents}}}}})
        self.on_osc_message("SYS/OSCQuery_Status",
                            f"Loaded {len(params)} total parameters")
        self.drain()


@pytest.fixture
def host(isolated):
    h = _Host(ModeManager())
    h._away_init()
    return h


def _off_sent(h):
    return [v for a, v in h.osc_manager.sent if a == "/avatar/parameters/OGP/Off"]


class TestHold:
    def test_afk_holds_everything_off(self, host, isolated):
        host.set_strength(0.7)
        resets = host.motor_router.resets
        host.packet(isolated, "AFK", True)
        assert host.is_output_off() is True           # shockers, friends' shocks
        assert host.get_master_scale() == 0.0         # toys, suits, trackers, drives
        assert host.get_away_reasons() == ("AFK",)
        assert host.get_away_status_text() == "AFK: everything off"
        assert host.motor_router.resets == resets + 1  # pushed to hardware now
        assert host.ui.held[-1] == "AFK: everything off"
        assert "AFK: everything off" in host.logs

    def test_your_own_off_switch_is_never_touched(self, host, isolated):
        host.packet(isolated, "AFK", True)
        assert host.is_off_switch_on() is False
        assert host.mode_manager.output_off is False
        assert _off_sent(host) == []                  # the menu's OGP/Off stays
        host.packet(isolated, "AFK", False)
        assert host.is_off_switch_on() is False
        assert _off_sent(host) == []

    def test_release_brings_back_exactly_the_previous_state(self, host, isolated):
        host.set_strength(0.7)
        host.set_sleep_active(True)
        host.packet(isolated, "AFK", True)
        host.packet(isolated, "AFK", False)
        assert host.is_output_off() is False
        assert host.get_master_scale() == 0.7
        assert host.get_strength() == 0.7
        assert host.is_sleep_active() is True
        assert host.get_away_reasons() == ()
        assert host.ui.held[-1] == ""
        assert host.logs[-1] == "AFK over — everything is back as it was"

    def test_an_off_switch_that_was_on_stays_on_after(self, host, isolated):
        host.set_strength(0.7)
        host.set_output_off(True)
        host.packet(isolated, "AFK", True)
        host.packet(isolated, "AFK", False)
        assert host.is_off_switch_on() is True
        assert host.is_output_off() is True
        assert host.get_master_scale() == 0.0

    def test_switching_your_off_off_while_held_stays_silent(self, host, isolated):
        host.set_strength(0.7)
        host.set_output_off(True)
        host.packet(isolated, "AFK", True)
        host.set_output_off(False)
        assert host.get_master_scale() == 0.0          # still away
        assert "stays off" in host.logs[-1] and "AFK" in host.logs[-1]
        host.packet(isolated, "AFK", False)
        assert host.get_master_scale() == 0.7          # the switch's new state

    def test_gogo_locos_afk_button(self, host, isolated):
        host.packet(isolated, "VRCEmote", 101)
        assert host.get_away_reasons() == ("GoGo Loco AFK",)
        host.packet(isolated, "VRCEmote", 0)
        assert host.is_output_off() is False

    def test_an_emote_is_not_afk(self, host, isolated):
        host.packet(isolated, "VRCEmote", 3)
        assert host.is_output_off() is False

    def test_several_sources_hold_until_the_last_clears(self, host, isolated):
        host.add_away_param("MyOff")
        host.set_strength(0.6)
        host.packet(isolated, "AFK", True)
        host.packet(isolated, "MyOff", True)
        assert host.get_away_reasons() == ("AFK", "MyOff")
        host.packet(isolated, "AFK", False)
        assert host.get_away_reasons() == ("MyOff",)
        assert host.get_master_scale() == 0.0
        assert host.ui.held[-1] == "MyOff: everything off"
        host.packet(isolated, "MyOff", False)
        assert host.get_master_scale() == 0.6
        assert host.is_off_switch_on() is False

    def test_a_repeat_changes_nothing(self, host, isolated):
        host.packet(isolated, "AFK", True)
        logs, resets = len(host.logs), host.motor_router.resets
        host.packet(isolated, "AFK", True)
        assert len(host.logs) == logs
        assert host.motor_router.resets == resets

    def test_a_store_reload_without_the_parameter_lets_go(self, host, isolated):
        # A picked parameter the new avatar doesn't have: the store's
        # reload drops it, and its status notice re-checks.
        host.add_away_param("OldAvatar/Off")
        host.packet(isolated, "OldAvatar/Off", True)
        assert host.is_output_off() is True
        isolated.rebuild_from_json({"CONTENTS": {"avatar": {"CONTENTS": {
            "parameters": {"CONTENTS": {"AFK": {"VALUE": [False]}}}}}}})
        host.on_osc_message("SYS/OSCQuery_Status", "Loaded 1 total parameters")
        host.drain()
        assert host.is_output_off() is False

    def test_a_store_reload_while_afk_holds(self, host, isolated):
        isolated.rebuild_from_json({"CONTENTS": {"avatar": {"CONTENTS": {
            "parameters": {"CONTENTS": {"AFK": {"VALUE": [True]}}}}}}})
        host.on_osc_message("SYS/OSCQuery_Status", "Loaded 1 total parameters")
        host.drain()
        assert host.get_away_reasons() == ("AFK",)


class TestVRChatCloses:
    """Blise's call (2026-11-14): "It should just be active if you're
    actually AFK within VR chat and no other time." VRChat closing (the OSC
    layer's disconnect, never a quiet stretch) lets every source go; when
    VRChat comes back, only what it says anew can hold again."""

    def test_closing_vrchat_lets_go(self, host, isolated):
        host.set_strength(0.7)
        host.packet(isolated, "AFK", True)
        resets = host.motor_router.resets
        host.vrchat_closes()
        assert host.is_output_off() is False
        assert host.get_master_scale() == 0.7
        assert host.get_away_reasons() == ()
        assert host.ui.held[-1] == ""
        assert host.motor_router.resets == resets + 1
        assert host.logs[-1] == ("VRChat is gone: AFK over — everything is "
                                 "back as it was")

    def test_every_source_lets_go(self, host, isolated):
        host.add_away_param("MyOff")
        host.packet(isolated, "AFK", True)
        host.packet(isolated, "VRCEmote", 101)
        host.packet(isolated, "MyOff", 1)
        assert host.get_away_reasons() == ("AFK", "GoGo Loco AFK", "MyOff")
        host.vrchat_closes()
        assert host.get_away_reasons() == ()
        assert host.is_output_off() is False

    def test_your_own_off_switch_is_untouched(self, host, isolated):
        host.packet(isolated, "AFK", True)
        host.vrchat_closes()
        assert host.is_off_switch_on() is False
        assert _off_sent(host) == []
        # ...and one that was on stays on.
        host.set_output_off(True)
        host.packet(isolated, "AFK", True)
        host.vrchat_closes()
        assert host.is_off_switch_on() is True
        assert host.is_output_off() is True

    def test_back_without_afk_holds_nothing(self, host, isolated):
        host.packet(isolated, "AFK", True)
        host.vrchat_closes()
        host.vrchat_returns(isolated, AFK=False, VRCEmote=0)
        assert host.get_away_reasons() == ()
        assert host.is_output_off() is False

    def test_back_and_still_afk_holds_again(self, host, isolated):
        host.packet(isolated, "AFK", True)
        host.vrchat_closes()
        host.vrchat_returns(isolated, AFK=True)
        assert host.get_away_reasons() == ("AFK",)
        assert host.is_output_off() is True

    def test_the_last_sessions_values_dont_come_back(self, host, isolated):
        # The store still says AFK; nothing re-reads it into a hold before
        # VRChat speaks -- not a settings change, not the OSC log's notices.
        host.packet(isolated, "AFK", True)
        host.vrchat_closes()
        assert isolated.get_values({"AFK"}) == {"AFK": True}
        host.set_away_switch("gogo_afk", False)
        host.on_osc_message("SYS/OSCQuery_Status", "[OSC] VRChat mDNS Added: x")
        host.on_osc_message("SYS/OSCQuery_Status", "Waiting for VRChat mDNS discovery...")
        host.drain()
        assert host.get_away_reasons() == ()

    def test_a_packet_from_the_returning_vrchat_counts_at_once(self, host, isolated):
        # Before the store's reload, a live packet is VRChat's word -- for
        # that parameter only; the others' old values still don't count.
        host.add_away_param("MyOff")
        host.packet(isolated, "MyOff", True)
        host.packet(isolated, "AFK", True)
        host.vrchat_closes()
        host.packet(isolated, "AFK", False)
        assert host.get_away_reasons() == ()
        host.packet(isolated, "AFK", True)
        assert host.get_away_reasons() == ("AFK",)
        host.packet(isolated, "MyOff", True)
        assert host.get_away_reasons() == ("AFK", "MyOff")

    def test_a_quiet_stretch_or_one_missed_check_keeps_the_hold(self, host, isolated):
        # VRChat sends nothing while you stand still AFK, and one health
        # check can miss on a busy PC: neither is VRChat closing. Only the
        # disconnect itself (osc_status False) lets go.
        host.packet(isolated, "AFK", True)
        for line in (
            "[OSC] WARNING: VRChat says connected but we've received 0 "
            "packets DIRECTLY from it in the last 30.0s",
            "[OSC] attempting OSCQuery re-poll to nudge VRChat...",
            "[OSC] health-check exception: ReadTimeout (consecutive=1)",
            "VRChat disconnected (VRChat mDNS service removed). Waiting...",
        ):
            host.on_osc_message("SYS/OSCQuery_Status", line)
            host.drain()
            assert host.get_away_reasons() == ("AFK",), line
        assert host.is_output_off() is True

    def test_the_disconnect_button_lets_go(self, host, isolated):
        host.packet(isolated, "AFK", True)
        host.toggle_osc_connection()                # connected → Disconnect
        assert host.get_away_reasons() == ()
        assert host.is_output_off() is False

    def test_closing_while_nothing_holds_changes_nothing(self, host, isolated):
        logs, resets = len(host.logs), host.motor_router.resets
        host.vrchat_closes()
        assert len(host.logs) == logs
        assert host.motor_router.resets == resets

    def test_switched_on_after_vrchat_came_back_afk(self, host, isolated):
        # The reload counts even while the card is off: switching it on
        # afterwards holds from VRChat's live values.
        host.set_away_switch("enabled", False)
        host.vrchat_closes()
        host.vrchat_returns(isolated, AFK=True)
        host.set_away_switch("enabled", True)
        assert host.get_away_reasons() == ("AFK",)

    def test_main_lets_go_on_the_disconnect_only(self):
        import inspect
        import main
        src = inspect.getsource(main.OscGoesPurrrApp.process_async_queue)
        assert src.count("self._away_vrchat_gone()") == 1
        branch = src.index('"VRChat OSC Disconnected. Waiting for VRChat to come back..."')
        assert src.index("self._away_vrchat_gone()") > branch
        assert src.index("self._away_vrchat_gone()") < src.index(
            'elif msg_type == "ui_slider_update"')


class TestSettingsTakeEffectAtOnce:
    def test_switching_it_off_while_held_lets_go(self, host, isolated):
        host.packet(isolated, "AFK", True)
        host.set_away_switch("enabled", False)
        assert host.is_output_off() is False
        host.packet(isolated, "AFK", True)             # ignored while off
        assert host.is_output_off() is False
        host.set_away_switch("enabled", True)           # still AFK: holds now
        assert host.get_away_reasons() == ("AFK",)

    def test_leaving_out_vrchats_afk(self, host, isolated):
        host.packet(isolated, "AFK", True)
        host.set_away_switch("vrchat_afk", False)
        assert host.is_output_off() is False
        host.set_away_switch("gogo_afk", False)
        host.packet(isolated, "VRCEmote", 101)
        assert host.is_output_off() is False

    def test_an_unknown_switch_is_ignored(self, host):
        host.set_away_switch("off_switch", False)
        assert host.get_away_settings()["enabled"] is True

    def test_adding_a_parameter_that_is_already_on_holds_now(self, host, isolated):
        isolated.update_parameter("MyOff", True)
        assert host.add_away_param("MyOff") is True
        assert host.get_away_reasons() == ("MyOff",)
        host.remove_away_param("MyOff")
        assert host.is_output_off() is False

    def test_add_refuses_blanks_and_repeats(self, host):
        assert host.add_away_param("/avatar/parameters/MyOff") is True
        assert host.add_away_param("MyOff") is False
        assert host.add_away_param("  ") is False
        assert host.get_away_params() == ["MyOff"]

    def test_get_away_settings(self, host):
        host.add_away_param("A")
        host.set_away_switch("gogo_afk", False)
        assert host.get_away_settings() == {
            "enabled": True, "vrchat_afk": True, "gogo_afk": False, "params": ["A"]}


class TestOscThread:
    def test_an_unwatched_packet_queues_nothing(self, host):
        host.on_osc_message("VelocityX", 0.3)
        assert host.thread_queue.empty()

    def test_a_watched_packet_queues_one_check(self, host):
        host.on_osc_message("AFK", True)
        host.on_osc_message("AFK", False)
        host.on_osc_message("VRCEmote", 4)
        assert host.thread_queue.qsize() == 1
        assert host.thread_queue.get_nowait() == ("away_check", None)

    def test_after_a_check_the_next_packet_queues_again(self, host):
        host.on_osc_message("AFK", True)
        host.drain()
        host.on_osc_message("AFK", False)
        assert host.thread_queue.qsize() == 1

    def test_switched_off_the_osc_thread_does_nothing(self, host):
        host.set_away_switch("enabled", False)
        host.on_osc_message("AFK", True)
        host.on_osc_message("SYS/OSCQuery_Status", "Loaded 3 total parameters")
        assert host.thread_queue.empty()

    def test_a_picked_parameter_is_watched(self, host):
        host.add_away_param("MyOff")
        host.on_osc_message("MyOff", True)
        assert host.thread_queue.qsize() == 1

    def test_the_main_queue_drain_handles_it(self):
        import inspect
        import main
        assert issubclass(main.OscGoesPurrrApp, AwayFacade)
        src = inspect.getsource(main.OscGoesPurrrApp.process_async_queue)
        assert 'msg_type == "away_check"' in src and "self._away_check()" in src
        assert "self._away_init()" in inspect.getsource(
            main.OscGoesPurrrApp._setup_components)


class TestTheShockersObeyIt:
    """The shocker router reads the controller's is_output_off: a hold
    ends every shocker at once, like Off."""

    def test_the_router_ends_everything(self, host, isolated):
        from pishock_router import PiShockRouter

        class _Eng:
            is_connected = True
            is_paused = False

            def __init__(self):
                self.ended = 0

            def end_all(self):
                self.ended += 1

            def shocker_ids(self):
                return [1]

        eng = _Eng()
        router = PiShockRouter(eng, get_rules=lambda: {}, is_output_off=host.is_output_off)
        router._stale.is_stale = lambda: False
        router.tick()                                   # live: not silenced
        host.packet(isolated, "AFK", True)
        router.tick()
        assert eng.ended == 1


class TestFriendsHeldBack:
    """A friend's shock while you're away is held back, and the log says
    why (the same check as Off)."""

    def _blocked(self, host):
        from controllers.friends_receive import FriendsReceiveMixin

        f = FriendsReceiveMixin()
        f._friend_perms = {"p": (True, True, True)}
        f.get_feature_enabled = lambda key: True
        f.friends_settings = type("S", (), {"get_paused": lambda self: False})()
        f.is_output_off = host.is_output_off
        f.is_off_switch_on = host.is_off_switch_on
        f.get_away_reasons = host.get_away_reasons
        eng = type("E", (), {"is_connected": True})()
        return f._shock_blocked("p", eng)

    def test_away(self, host, isolated):
        assert self._blocked(host) is None
        host.packet(isolated, "AFK", True)
        assert self._blocked(host) == "everything is off (AFK)"

    def test_your_own_off_still_says_off(self, host, isolated):
        host.set_output_off(True)
        host.packet(isolated, "AFK", True)
        assert self._blocked(host) == "Off is on"


# ---------------------------------------------------------------------------
# Settings round-trip through the real AppSettingsManager
# ---------------------------------------------------------------------------

class TestSettingsRoundTrip:
    def _manager(self, monkeypatch, path):
        import settings.app as app_settings
        monkeypatch.setattr(app_settings, "APP_SETTINGS_FILE", str(path))
        return app_settings.AppSettingsManager()

    def test_a_new_install_starts_on(self, monkeypatch, tmp_path):
        m = self._manager(monkeypatch, tmp_path / "app_settings.json")
        sources = away_off.compile_sources(m.get)
        assert away_off.watched(sources) == {"AFK", "VRCEmote"}

    def test_an_older_install_gets_it_on(self, monkeypatch, tmp_path):
        path = tmp_path / "app_settings.json"
        path.write_text('{"auto_connect": false}', encoding="utf-8")
        m = self._manager(monkeypatch, path)
        assert m.get("away_off_enabled") is True
        assert m.get("away_off_params") == []

    def test_choices_survive_a_restart(self, monkeypatch, tmp_path):
        path = tmp_path / "app_settings.json"
        m = self._manager(monkeypatch, path)
        m.set("away_off_gogo_afk", False)
        m.set("away_off_params", ["MyOff", "Other"])
        again = self._manager(monkeypatch, path)
        sources = away_off.compile_sources(again.get)
        assert [n for n, _l, _t in sources] == ["AFK", "MyOff", "Other"]
        on_disk = json.loads(path.read_text(encoding="utf-8"))
        assert on_disk["away_off_params"] == ["MyOff", "Other"]

    def test_switched_off_survives_a_restart(self, monkeypatch, tmp_path):
        path = tmp_path / "app_settings.json"
        self._manager(monkeypatch, path).set("away_off_enabled", False)
        assert away_off.compile_sources(self._manager(monkeypatch, path).get) == ()

    def test_through_the_facade(self, monkeypatch, tmp_path, isolated):
        import settings.app as app_settings
        path = tmp_path / "app_settings.json"
        monkeypatch.setattr(app_settings, "APP_SETTINGS_FILE", str(path))
        monkeypatch.setattr(config_manager, "AppSettingsManager",
                            app_settings.AppSettingsManager)
        h = _Host(ModeManager())
        h._away_init()
        h.add_away_param("MyOff")
        h.set_away_switch("vrchat_afk", False)
        h2 = _Host(ModeManager())
        h2._away_init()
        assert h2.get_away_settings() == {
            "enabled": True, "vrchat_afk": False, "gogo_afk": True, "params": ["MyOff"]}
        assert h2._away_watch == {"VRCEmote", "MyOff"}

    def test_the_hold_itself_is_never_remembered(self, isolated):
        mm = ModeManager()
        mm.set_held_off(True)
        assert ModeManager().held_off is False


# ---------------------------------------------------------------------------
# Settings → Toy Safety: the card
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def qapp():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication(sys.argv[:1])


class _CardController:
    def __init__(self):
        self.app = {}
        self.away = {"enabled": True, "vrchat_afk": True, "gogo_afk": True}
        self.params = ["MyOff"]
        self.calls = []

    def get_app_setting(self, key, default=None):
        return self.app.get(key, default)

    def set_app_setting(self, key, value):
        self.app[key] = value

    def get_away_settings(self):
        return dict(self.away, params=list(self.params))

    def set_away_switch(self, which, on):
        self.calls.append((which, on))
        self.away[which] = on

    def get_away_params(self):
        return list(self.params)

    def add_away_param(self, name):
        self.params.append(name)
        return True

    def remove_away_param(self, name):
        self.params.remove(name)


def _card_host(ctl):
    from PySide6.QtWidgets import QLabel
    from ui.views.settings import SettingsMixin

    class Host(SettingsMixin):
        def __init__(self, controller):
            self.controller = controller

        def _explain(self, target, title, body):
            from ui.tooltips import explain
            explain(target, title, body)

        def _muted_label(self, text):
            return QLabel(text)

        def _repolish(self, widget):
            pass

    h = Host(ctl)
    h._card = h._build_toy_safety_card()
    return h


def _chip_names(h):
    from PySide6.QtWidgets import QFrame, QLabel
    flow = h._away_chips_flow
    names = []
    for i in range(flow.count()):
        w = flow.itemAt(i).widget()
        if isinstance(w, QFrame) and w.objectName() == "chip":
            names.append(w.findChild(QLabel).text())
    return names


class TestCard:
    def test_seeds_from_the_controller(self, qapp):
        h = _card_host(_CardController())
        assert h.away_off_toggle.isChecked()
        assert h.away_vrchat_toggle.isChecked()
        assert h.away_gogo_toggle.isChecked()
        assert _chip_names(h) == ["MyOff"]

    def test_switches_reach_the_controller_once(self, qapp):
        ctl = _CardController()
        h = _card_host(ctl)
        assert ctl.calls == []                     # seeding doesn't save
        h.away_gogo_toggle.setChecked(False)
        h.away_off_toggle.setChecked(False)
        assert ctl.calls == [("gogo_afk", False), ("enabled", False)]

    def test_the_sources_hide_while_it_is_off(self, qapp):
        ctl = _CardController()
        ctl.away["enabled"] = False
        h = _card_host(ctl)
        h._card.show()
        assert h.away_vrchat_toggle.isVisibleTo(h._card) is False
        h.away_off_toggle.setChecked(True)
        assert h.away_vrchat_toggle.isVisibleTo(h._card) is True
        h._card.hide()

    def test_a_chips_x_takes_it_out(self, qapp):
        from PySide6.QtWidgets import QPushButton
        ctl = _CardController()
        h = _card_host(ctl)
        chip = h._away_chips_flow.itemAt(0).widget()
        chip.findChild(QPushButton).click()
        assert ctl.params == []
        assert _chip_names(h) == []

    def test_a_pick_is_added(self, qapp, monkeypatch):
        import ui.views.settings as settings_view
        ctl = _CardController()
        h = _card_host(ctl)
        monkeypatch.setattr(settings_view, "open_osc_variable_picker",
                            lambda parent, on_pick, **kw: on_pick("Other"))
        h.window = None
        h._pick_away_param()
        assert _chip_names(h) == ["MyOff", "Other"]


# ---------------------------------------------------------------------------
# ModeManager: the hold beside the switch
# ---------------------------------------------------------------------------

class TestModeManager:
    def test_held_off_silences_without_the_switch(self, isolated):
        mm = ModeManager()
        mm.set_strength(0.5, save=False)
        assert mm.set_held_off(True) is True
        assert mm.set_held_off(True) is False          # edge-triggered
        assert mm.output_off is False
        assert mm.is_silenced() is True
        assert mm.get_master_scale() == 0.0
        assert mm.set_held_off(False) is True
        assert mm.get_master_scale() == 0.5

    def test_switch_and_hold_are_independent(self, isolated):
        mm = ModeManager()
        mm.set_output_off(True)
        mm.set_held_off(True)
        mm.set_held_off(False)
        assert mm.output_off is True
        assert mm.get_master_scale() == 0.0
