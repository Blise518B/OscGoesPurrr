"""The sidebar's two link rows -- VRChat and Intiface.

Both links come up, reconnect and recover by themselves, so each row is a
name and a status pill, and a button exists only while it has something to
do: Connect when a link is down and nothing will bring it up, Find toys
while the toy server is up. There is no Disconnect and no VRChat refresh.

The two status methods are exercised on a bare OscGoesPurrrUI (no window,
no controller wiring) carrying just the widgets they touch.
"""
import sys

import pytest

from PySide6.QtWidgets import QApplication, QLabel, QPushButton, QWidget

from ui_components import OscGoesPurrrUI, _LiveTipLabel


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication(sys.argv[:1])


class _Controller:
    def __init__(self):
        self.haptic = []
        self.settings = {}
        self.search_asks = 0

    def set_haptic_connected(self, connected):
        self.haptic.append(connected)

    def get_app_setting(self, key, default=None):
        return self.settings.get(key, default)

    def note_toy_search_wanted(self):
        self.search_asks += 1


@pytest.fixture
def ui(qapp):
    u = OscGoesPurrrUI.__new__(OscGoesPurrrUI)       # no window, no wiring
    u.controller = _Controller()
    u._keep = QWidget()
    u.osc_status_label = _LiveTipLabel("DISCONNECTED", u._keep)
    u.osc_connection_button = QPushButton("Connect", u._keep)
    u._osc_connect_row = QWidget(u._keep)
    u._osc_connect_row.setVisible(False)
    u.status_label = QLabel("DISCONNECTED", u._keep)
    u._toy_buttons_row = QWidget(u._keep)
    u.connection_button = QPushButton("Connect", u._toy_buttons_row)
    u.scan_toys_button = QPushButton("Find toys", u._toy_buttons_row)
    u.update_stored_devices_ui = lambda: None
    return u


class TestVRChatRow:
    def test_looking_for_vrchat_offers_nothing_to_press(self, ui):
        ui.update_osc_link_state("disconnected", None, listening=True)
        assert ui.osc_status_label.text() == "SEARCHING"
        assert "connects by itself" in ui.osc_status_label.toolTip()
        assert ui._osc_connect_row.isHidden()

    def test_connect_appears_only_while_nothing_is_listening(self, ui):
        ui.update_osc_link_state("disconnected", None, listening=False)
        assert ui.osc_status_label.text() == "DISCONNECTED"
        assert not ui._osc_connect_row.isHidden()
        ui.update_osc_link_state("disconnected", None, listening=True)
        assert ui._osc_connect_row.isHidden()

    @pytest.mark.parametrize("state,text", [
        ("waiting", "NO DATA"), ("live", "CONNECTED"),
        ("live_router", "CONNECTED (518)")])
    def test_a_link_that_is_up_has_no_button_at_all(self, ui, state, text):
        ui.update_osc_link_state(state, 9001, listening=True)
        assert ui.osc_status_label.text() == text
        assert ui._osc_connect_row.isHidden()
        # It never turns into a Disconnect.
        assert ui.osc_connection_button.text() == "Connect"

    def test_the_legacy_two_state_event_still_resolves(self, ui):
        """connect/disconnect events don't say whether the app is
        listening: connected counts as listening, disconnected as not --
        the 10 Hz poller corrects it on its next tick."""
        ui.update_osc_status(True, 9001)
        assert ui._osc_connect_row.isHidden()
        ui.update_osc_status(False)
        assert not ui._osc_connect_row.isHidden()


class TestIntifaceRow:
    def test_down_shows_connect_and_up_shows_nothing(self, ui):
        ui.update_connection_status(False, "")
        assert not ui.connection_button.isHidden()
        assert ui.scan_toys_button.isHidden()
        assert not ui._toy_buttons_row.isHidden()
        assert ui.status_label.text() == "DISCONNECTED"

        ui.update_connection_status(True, "ws://127.0.0.1:12345")
        assert ui.connection_button.isHidden()
        assert ui.scan_toys_button.isHidden()        # the app looks itself
        assert ui._toy_buttons_row.isHidden()        # ...so the row is gone
        assert ui.status_label.text() == "CONNECTED"
        # Never a Disconnect face.
        assert ui.connection_button.text() == "Connect"
        assert ui.controller.haptic == [False, True]

    def test_find_toys_stands_in_only_while_auto_refresh_is_off(self, ui):
        ui.update_connection_status(True, "ws://127.0.0.1:12345")
        ui.controller.settings["auto_refresh"] = False
        ui.refresh_link_buttons()
        assert not ui.scan_toys_button.isHidden()
        assert not ui._toy_buttons_row.isHidden()
        ui.controller.settings["auto_refresh"] = True
        ui.refresh_link_buttons()
        assert ui.scan_toys_button.isHidden()
        # And never while the toy server is down: there is nothing to scan.
        ui.controller.settings["auto_refresh"] = False
        ui.update_connection_status(False, "")
        assert ui.scan_toys_button.isHidden()

    def test_opening_the_window_asks_for_the_fast_search(self, ui):
        ui._on_window_activated()
        assert ui.controller.search_asks == 1


class TestToySearchPacing:
    """How often the app looks for toys: hard while none is connected and
    one is expected, at the old slow beat otherwise."""

    class _Engine:
        def __init__(self, names=()):
            self.names = list(names)
            self.is_connected = True

        def list_connected_device_names(self):
            return list(self.names)

    def _facade(self, names=()):
        from controllers.intiface_facade import IntifaceFacade

        class Host(IntifaceFacade):
            pass

        h = Host.__new__(Host)
        h.haptic_engine = self._Engine(names)
        return h

    def test_no_toy_and_one_expected_scans_every_five_seconds(self):
        import constants as C
        h = self._facade()
        h.note_toy_search_wanted()
        assert h._toy_scan_pause() == C.TOY_SEARCH_RATE_S - C.TOY_SCAN_SECONDS
        assert C.TOY_SEARCH_RATE_S == 5.0

    def test_a_connected_toy_keeps_the_slow_beat_whatever_is_asked(self):
        """Scanning shares the radio with the toy's own link; its latency
        comes first, so nothing speeds the scan up while one is live."""
        import constants as C
        h = self._facade(["Lush"])
        h.note_toy_search_wanted()
        assert h._toy_scan_pause() == C.AUTO_REFRESH_RATE_S

    def test_the_fast_search_ends_by_itself(self, monkeypatch):
        import constants as C
        import controllers.intiface_facade as mod
        now = [1000.0]
        monkeypatch.setattr(mod.time, "monotonic", lambda: now[0])
        h = self._facade()
        assert h._toy_scan_pause() == C.AUTO_REFRESH_RATE_S   # never asked
        h.note_toy_search_wanted()
        now[0] += C.TOY_SEARCH_WINDOW_S - 1
        assert h._toy_scan_pause() < C.AUTO_REFRESH_RATE_S
        now[0] += 2
        assert h._toy_scan_pause() == C.AUTO_REFRESH_RATE_S

    def test_losing_the_only_toy_starts_the_search_within_a_second(self, monkeypatch):
        """The loop ticks once a second and re-reads the pause, so a pause
        that shortens mid-wait takes effect at the next tick -- not after
        the rest of a 30 s sleep."""
        import asyncio
        import controllers.intiface_facade as mod

        h = self._facade(["Lush"])
        h.auto_refresh_enabled = True
        scans, ticks = [], [0]

        async def fake_scan():
            scans.append(ticks[0])
            if len(scans) >= 2:
                h.auto_refresh_enabled = False       # end the loop

        async def fake_sleep(_s):
            ticks[0] += 1
            if ticks[0] == 10:                       # ten seconds in...
                h.haptic_engine.names.clear()        # ...the only toy drops
                h.note_toy_search_wanted()

        h._async_start_scanning = fake_scan
        monkeypatch.setattr(mod.asyncio, "sleep", fake_sleep)
        asyncio.run(h._async_auto_refresh_loop())
        assert scans[0] == 10                         # at once, not at 30
        assert scans[1] == 13                         # then every 3 s rest


class TestListeningFacade:
    def test_reports_the_managers_flag(self):
        from controllers.osc_facade import OscFacade

        class Host(OscFacade):
            pass

        class Manager:
            is_listening = False

        h = Host()
        assert h.is_osc_listening() is False          # no manager yet
        h.osc_manager = Manager()
        assert h.is_osc_listening() is False          # built, never started
        h.osc_manager.is_listening = True
        assert h.is_osc_listening() is True
        h.osc_manager = None
        assert h.is_osc_listening() is False

    def test_the_manager_sets_the_flag_in_start_and_clears_it_in_stop(self):
        """Read off the source rather than run: start() opens mDNS sockets."""
        import inspect
        import vrchat_osc
        mgr = vrchat_osc.VRChatOSCManager
        assert "self.is_listening = False" in inspect.getsource(mgr.__init__)
        assert "self.is_listening = True" in inspect.getsource(mgr.start)
        assert "self.is_listening = False" in inspect.getsource(mgr.stop)
