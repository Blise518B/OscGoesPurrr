"""The PSVR2 headset in the app: its feature switch (off by default, Windows
only), the controller facade (Home's On / Off, the test buzz, Off holding
everything back), its "It's connected" avatar parameter and its Home row.

Never the real toolkit: the engine runs on test_psvr2_engine's fake CAPI,
so no test can reach a headset (the real binding would read the user's
%TEMP% and load their PSVR2Toolkit)."""

import queue
import time

import pytest

import main
from controllers import presence_facade as tp
from controllers.psvr2_facade import FEATURE_PSVR2, PSVR2Facade
from psvr2_engine import PSVR2Engine
from test_psvr2_engine import _FakeCapi
from ui.views.home_devices import psvr2_row


class Host(PSVR2Facade):
    def __init__(self, features=(), scale=1.0, capi=None):
        self.features = set(features)
        self.scale = scale
        self.thread_queue = queue.Queue()
        self.logs = []
        self.capi = capi or _FakeCapi()

    def _psvr2_new_engine(self, **kw):
        return PSVR2Engine(capi=self.capi, **kw)

    def get_feature_enabled(self, key):
        return key in self.features

    def get_master_scale(self):
        return self.scale

    def log_message(self, msg):
        self.logs.append(msg)


def _wait_for(cond, timeout=3.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if cond():
            return True
        time.sleep(0.01)
    return False


# --- the feature switch ----------------------------------------------------

class TestFeatureSwitch:
    def test_off_by_default(self):
        assert "feature_psvr2" in main.OscGoesPurrrApp.FEATURE_KEYS
        assert "feature_psvr2" in main.OscGoesPurrrApp._FEATURE_DEFAULT_OFF

    def _app(self, monkeypatch, platform, saved):
        monkeypatch.setattr(main.sys, "platform", platform)
        app = main.OscGoesPurrrApp.__new__(main.OscGoesPurrrApp)
        app.get_app_setting = lambda key, default=None: saved.get(key, default)
        app.set_app_setting = lambda key, value: saved.__setitem__(key, value)
        app.ui = None
        app.applied = []
        app._apply_feature_state = lambda key, on: app.applied.append((key, on))
        app.presence_sync = lambda force=False: None
        return app

    def test_windows_offers_it(self, monkeypatch):
        saved = {}
        app = self._app(monkeypatch, "win32", saved)
        assert app.get_feature_flags()["feature_psvr2"] is False
        app.set_feature_enabled("feature_psvr2", True)
        assert app.get_feature_enabled("feature_psvr2") is True
        assert app.applied == [("feature_psvr2", True)]

    def test_linux_hides_it(self, monkeypatch):
        """PSVR2Toolkit is Windows only: elsewhere the switch is off
        whatever was saved, missing from Settings and "What are you here
        for?", and flipping it changes nothing."""
        saved = {"feature_psvr2": True}
        app = self._app(monkeypatch, "linux", saved)
        assert app.get_feature_enabled("feature_psvr2") is False
        assert "feature_psvr2" not in app.get_feature_flags()
        app.set_feature_enabled("feature_psvr2", False)
        assert saved["feature_psvr2"] is True and app.applied == []
        # ...and the rest stay offered
        assert "feature_trackers" in app.get_feature_flags()

    def test_the_question_skips_it_on_linux(self, monkeypatch):
        from controllers.interests_facade import InterestsFacade
        app = self._app(monkeypatch, "linux", {})
        picked = [f for _t, choices in InterestsFacade.get_interests(app)
                  for f, *_rest in choices]
        assert "feature_psvr2" not in picked and "feature_trackers" in picked


# --- the facade ------------------------------------------------------------

class TestFacade:
    def test_nothing_starts_while_the_feature_is_off(self):
        h = Host()
        h._psvr2_init()
        assert h.capi.init_calls == 0
        assert h.get_psvr2_status()["feature"] is False

    def test_the_feature_joins_and_lets_go(self):
        h = Host()
        h._psvr2_init()
        h._psvr2_feature_changed(True)
        try:
            assert _wait_for(lambda: h.psvr2_engine.is_connected)
        finally:
            h._psvr2_feature_changed(False)
        assert not h.psvr2_engine.is_connected
        assert h.capi.deinit_calls >= 1
        assert any("PSVR2 off" in m for m in h.logs)

    def test_off_on_home_is_remembered(self):
        h = Host()
        h._psvr2_init()
        h.psvr2_stop_all()
        assert h.psvr2_engine.is_paused
        h2 = Host()
        h2._psvr2_init()                    # the next launch: still off
        assert h2.psvr2_engine.is_paused
        h2.psvr2_resume()
        assert not h2.psvr2_engine.is_paused
        h3 = Host()
        h3._psvr2_init()
        assert not h3.psvr2_engine.is_paused

    def test_a_state_change_reaches_the_controllers_queue(self):
        h = Host()
        h._psvr2_init()
        h.psvr2_stop_all()
        assert ("psvr2_state", None) in list(h.thread_queue.queue)

    def test_the_test_buzz_is_held_back_while_output_is_off(self):
        h = Host(features={FEATURE_PSVR2}, scale=0.0)
        h._psvr2_init()
        h.psvr2_engine._start_send_thread = lambda: None
        h.psvr2_engine._open()
        assert h.psvr2_test_pulse() is False
        assert any("output is Off" in m for m in h.logs)
        h.scale = 1.0
        assert h.psvr2_test_pulse() is True
        h.psvr2_stop_all()
        assert h.psvr2_test_pulse() is False
        h.psvr2_engine.stop()

    def test_status_says_what_the_page_needs(self):
        h = Host(scale=0.0)
        h._psvr2_init()
        st = h.get_psvr2_status()
        for key in ("available", "connected", "paused", "last_error",
                    "auto_connect", "output", "extras"):
            assert key in st
        assert st["output_off"] is True
        assert st["output"]["min_hz"] == 10.0
        assert st["antistuck"] == {"enabled": True, "active_s": 1, "peaked_s": 10}

    def test_its_own_anti_stuck_starts_as_the_toys_and_the_router_reads_it(self):
        """The headset's anti-stuck is its own (antistuck.py): a file
        without one starts with the toys' switch and times, and the router
        reads the headset's, not the toys'."""
        h = Host()
        h._get_toy_antistuck = lambda: {"enabled": False, "active_s": 4, "peaked_s": 30}
        h._psvr2_init()
        assert h.get_psvr2_antistuck() == {"enabled": False, "active_s": 4, "peaked_s": 30}
        h.set_psvr2_antistuck(enabled=True, active_s=2)
        assert h.psvr2_router._get_antistuck() == {
            "enabled": True, "active_s": 2, "peaked_s": 30}
        h.psvr2_engine.stop()


# --- "It's connected" ------------------------------------------------------

class _PresenceHost(tp.PresenceFacade):
    def __init__(self, features):
        import test_presence as p
        self.mode_manager = p._Modes(())
        self.mode_manager.app_settings.values[tp.ANY_ENABLED_KEY] = False
        self.osc_manager = p._Osc()
        self.haptic_engine = p._Engine()
        self.features = set(features)

        class _Eng:
            is_connected = False
        self.psvr2_engine = _Eng()

    def get_feature_enabled(self, key):
        return key in self.features

    def take(self):
        out, self.osc_manager.sent = self.osc_manager.sent, []
        return out


P = "/avatar/parameters/"


class TestConnectedParameter:
    def test_its_fixed_name(self):
        h = _PresenceHost({FEATURE_PSVR2})
        assert h.get_device_connected_param(tp.SLOT_PSVR2) == (True, "OGP/PSVR2Connected")

    def test_it_follows_the_headset(self):
        h = _PresenceHost({FEATURE_PSVR2})
        h.presence_on_devices_changed()
        assert h.take() == [(P + "OGP/PSVR2Connected", False)]
        h.psvr2_engine.is_connected = True
        h.presence_on_devices_changed()
        assert h.take() == [(P + "OGP/PSVR2Connected", True)]

    def test_only_while_the_feature_is_on(self):
        h = _PresenceHost(())
        h.psvr2_engine.is_connected = True
        h.presence_on_devices_changed()
        assert h.take() == []

    def test_switching_the_feature_off_clears_it_once(self):
        h = _PresenceHost({FEATURE_PSVR2})
        h.psvr2_engine.is_connected = True
        h.presence_on_devices_changed()
        h.take()
        h.features.clear()
        h.presence_sync()
        assert h.take() == [(P + "OGP/PSVR2Connected", False)]


# --- Home's row ------------------------------------------------------------

class TestHomeRow:
    def test_connected(self):
        s = psvr2_row({"connected": True, "paused": False, "extras": {"rumble_hz": None}})
        assert s["up"] and s["pill"] is None and s["share"] is None
        assert s["summary"] == "Connected through PSVR2Toolkit" and s["icon"] == "psvr2"

    def test_says_how_fast_it_rumbles(self):
        s = psvr2_row({"connected": True, "extras": {"rumble_hz": 18}})
        assert s["summary"] == "PSVR2Toolkit · rumbling at 18 Hz"

    def test_switched_off_is_grey_but_connected(self):
        s = psvr2_row({"connected": True, "paused": True, "extras": {}})
        assert s["connected"] and not s["up"] and not s["enabled"]

    def test_offline_says_why(self):
        s = psvr2_row({"connected": False, "available": False,
                       "last_error": "PSVR2Toolkit not detected"})
        assert s["pill"] == ("OFFLINE", "idle")
        assert s["summary"] == "PSVR2Toolkit not detected"
        assert psvr2_row({"connected": False, "auto_connect": True})["summary"] \
            == "Waiting for SteamVR…"
