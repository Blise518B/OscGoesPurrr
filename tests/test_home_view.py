"""Widget tests for Home -- the landing page that replaced Overview and
Device Routing.

What the page promises: every remembered toy is listed, connected ones
first in their identity hue and offline ones in a grey outline with the
live-only controls taken away; each bar says what drives the toy; and
the tuning tools stay folded until asked for.

Widget tests run headless against a real QApplication (same pattern as
test_output_controls_view). The mixins are exercised on a minimal host,
mirroring how OscGoesPurrrUI composes them.
"""

import sys

import pytest

from PySide6.QtCore import QEvent, QPoint
from PySide6.QtGui import QHelpEvent
from PySide6.QtWidgets import QApplication, QVBoxLayout, QWidget

from ui import theme
from ui.views.dashboard import DashboardMixin
from ui.views.device_frame import DeviceFrameMixin
from ui.views.home import HomeMixin


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication(sys.argv[:1])


class _Router:
    def subscribe_intermediates(self, *a, **k):
        pass

    def unsubscribe_intermediates(self, *a, **k):
        pass


class FakeController:
    """The slice of the controller facade Home is allowed to touch."""

    def __init__(self, profiles=None, connected=()):
        self.profiles = profiles if profiles is not None else {}
        self.connected = set(connected)
        self.settings = {}
        self.features = {}
        self.motor_router = _Router()
        self.purr_checks = 0
        self.osc_ok = True
        self.zones_ok = True
        self.toy_params = {}

    def get_app_setting(self, key, default=None):
        return self.settings.get(key, default)

    def set_app_setting(self, key, value):
        self.settings[key] = value

    def get_feature_enabled(self, key):
        return self.features.get(key, True)

    def get_setup_status(self):
        return {"osc": self.osc_ok, "zones": self.zones_ok,
                "toy": bool(self.connected)}

    def get_profile_config(self, device, key, default=None):
        return self.profiles.get(device, {}).get(key, default)

    def update_device_config(self, device, key, value):
        self.profiles.setdefault(device, {})[key] = value

    def save_profiles(self):
        pass

    def force_recalculate(self):
        pass

    def get_active_profile_dict(self):
        return self.profiles

    def get_connected_device_names(self):
        return set(self.connected)

    def get_device_motor_counts(self):
        return {}

    def is_device_muted(self, _name):
        return False

    def trigger_purr_check(self):
        self.purr_checks += 1

    def get_toy_connected_param(self, device):
        return self.toy_params.get(device, (False, f"OGP/{device}Connected"))

    def set_toy_connected_param(self, device, enabled, name):
        self.toy_params[device] = (enabled, name)


class _Host(HomeMixin, DeviceFrameMixin, DashboardMixin):
    """Minimal stand-in for OscGoesPurrrUI: the state the three mixins
    share, and the page built into a parent that keeps it alive."""

    def __init__(self, controller):
        self.controller = controller
        self.window = QWidget()
        self.views = {}
        self.nav_buttons = {}
        self.main_stack = None
        self.intiface_sidebar_section = None
        self.device_ui_frames = {}
        self.stored_device_frames = {}
        self.unified_devices_layout = None
        page_lay = QVBoxLayout(self.window)
        self._build_home_view(page_lay)
        self.build_stored_devices_ui()
        self.update_stored_devices_ui()

    def _repolish(self, widget):
        widget.style().unpolish(widget)
        widget.style().polish(widget)

    def hue(self, name):
        return self.device_ui_frames[name]["frame"].property("hue")

    def order(self):
        lay = self.unified_devices_layout
        by_frame = {d["frame"]: n for n, d in self.device_ui_frames.items()}
        return [by_frame[lay.itemAt(i).widget()] for i in range(lay.count())
                if lay.itemAt(i).widget() in by_frame]


def _toys():
    return {"Alpha": {"motor_count": 1}, "Bravo": {"motor_count": 2},
            "Charlie": {"motor_count": 1}}


@pytest.fixture
def host(qapp):
    return _Host(FakeController(_toys(), connected={"Bravo", "Charlie"}))


class TestToyList:
    def test_every_remembered_toy_is_listed_connected_first(self, host):
        assert host.order() == ["Bravo", "Charlie", "Alpha"]

    def test_connected_toys_wear_hues_and_offline_ones_do_not_use_one_up(self, host):
        assert host.hue("Bravo") == theme.toy_hue(0)
        assert host.hue("Charlie") == theme.toy_hue(1)
        assert host.hue("Alpha") == theme.OFFLINE_HUE

    def test_an_offline_toy_drops_its_live_only_controls(self, host):
        live = host.device_ui_frames["Bravo"]
        off = host.device_ui_frames["Alpha"]
        for key in ("battery_label", "mini_bar_strip", "mute_button",
                    "test_button"):
            assert not live[key].isHidden(), key
            assert off[key].isHidden(), key
        assert live["offline_pill"].isHidden()
        assert not off["offline_pill"].isHidden()

    def test_offline_is_grey_not_red(self, host):
        from constants import COLOR_ALERT, COLOR_DIM
        style = host.device_ui_frames["Alpha"]["connect_dot"].styleSheet()
        assert COLOR_DIM in style and COLOR_ALERT not in style

    def test_a_toy_that_reconnects_comes_back_to_life(self, host):
        host.controller.connected.add("Alpha")
        host.update_stored_devices_ui()
        data = host.device_ui_frames["Alpha"]
        assert host.hue("Alpha") == theme.toy_hue(0)      # sorts first now
        assert data["offline_pill"].isHidden()
        assert not data["test_button"].isHidden()
        host.controller.connected.discard("Alpha")
        host.update_stored_devices_ui()
        assert host.hue("Alpha") == theme.OFFLINE_HUE
        assert data["test_button"].isHidden()

    def test_test_all_reaches_the_controller(self, host):
        host._test_all_button.click()
        assert host.controller.purr_checks == 1

    def test_test_all_is_off_while_nothing_is_connected(self, host):
        assert host._test_all_button.isEnabled()
        host.controller.connected.clear()
        host.update_stored_devices_ui()
        assert not host._test_all_button.isEnabled()

    def test_the_caret_points_right_closed_and_down_open(self, host):
        """The same ▸ / ▾ as the chain bars and the Tuning tools fold --
        a down caret must never mean "closed" on one bar and "open" on
        the next."""
        from PySide6.QtCore import Qt
        from PySide6.QtTest import QTest
        from PySide6.QtWidgets import QLabel
        frame = host.device_ui_frames["Bravo"]["frame"]
        bar = frame.findChild(QWidget, "toyBar")
        caret = bar.findChild(QLabel, "expandCaret")
        body = frame.findChild(QWidget, "toyBody")
        assert caret.text() == "▸" and body.isHidden()
        host.window.show()                    # the bar toggles on isVisible
        QTest.mouseClick(bar, Qt.LeftButton)
        assert caret.text() == "▾" and not body.isHidden()
        QTest.mouseClick(bar, Qt.LeftButton)
        assert caret.text() == "▸" and body.isHidden()
        host.window.hide()

    def test_one_and_two_motor_toys_share_a_meter_column(self, host):
        one = host.device_ui_frames["Charlie"]["mini_bar_strip"]
        two = host.device_ui_frames["Bravo"]["mini_bar_strip"]
        assert one.maximumWidth() == two.maximumWidth() == one.minimumWidth()

    def test_no_toys_yet_says_what_to_do(self, qapp):
        from PySide6.QtWidgets import QLabel
        empty = _Host(FakeController({}, connected=()))
        texts = [w.text() for w in empty.unified_devices_frame.findChildren(QLabel)]
        assert any("switch one on" in t for t in texts)


class TestConnectedParameterRow:
    """Each toy's card carries its own "tell VRChat while this toy is
    connected" switch and parameter name."""

    def _row(self, host, name="Bravo"):
        from PySide6.QtWidgets import QLineEdit
        from ui.widgets import ToggleSwitch
        body = host.device_ui_frames[name]["frame"].findChild(QWidget, "toyBody")
        toggle = next(t for t in body.findChildren(ToggleSwitch)
                      if t.text() == "Tell VRChat while this toy is connected")
        edit = toggle.parentWidget().findChild(QLineEdit)
        return toggle, edit

    def test_it_opens_off_with_the_toys_default_name(self, host):
        toggle, edit = self._row(host)
        assert not toggle.isChecked()
        assert edit.text() == "OGP/BravoConnected"

    def test_switching_it_on_tells_the_controller_which_toy_and_name(self, host):
        toggle, _edit = self._row(host)
        toggle.setChecked(True)
        assert host.controller.toy_params["Bravo"] == (True, "OGP/BravoConnected")
        assert "Alpha" not in host.controller.toy_params

    def test_a_typed_name_is_reduced_to_the_bare_parameter(self, host):
        toggle, edit = self._row(host)
        edit.setText("/avatar/parameters/MyLight")
        edit.editingFinished.emit()
        assert edit.text() == "MyLight"
        assert host.controller.toy_params["Bravo"] == (False, "MyLight")

    def test_it_explains_itself(self, host):
        toggle, edit = self._row(host)
        assert "true while this toy is connected" in toggle.toolTip()
        assert edit.toolTip() == toggle.toolTip()


class TestGettingStarted:
    """The first-run card: says what you do NOT need, walks the three
    steps in the order you do them, and gets out of the way as they tick."""

    @pytest.fixture
    def fresh(self, qapp):
        ctl = FakeController({}, connected=())
        ctl.osc_ok = ctl.zones_ok = False
        return _Host(ctl)

    def _details(self, host):
        return {k: v[2] for k, v in host._setup_step_labels.items()}

    def test_it_says_intiface_is_built_in_and_what_bluetooth_it_needs(self, fresh):
        assert "don't need Intiface" in fresh._setup_lead.text()
        toy = self._details(fresh)["toy"].text()
        assert "Bluetooth" in toy and "4.0" in toy
        assert "phone app" in toy and "pair" in toy

    def test_steps_come_in_the_order_you_do_them(self, fresh):
        assert [k for k, _t, _d in fresh._SETUP_STEPS] == ["toy", "osc", "zones"]
        assert list(fresh._setup_step_labels) == ["toy", "osc", "zones"]

    def test_a_done_step_folds_to_its_ticked_title(self, fresh):
        details = self._details(fresh)
        assert not any(d.isHidden() for d in details.values())
        fresh.controller.connected.add("Alpha")
        fresh._refresh_setup_checklist()
        mark, _title, detail = fresh._setup_step_labels["toy"]
        assert mark.text() == "✓" and detail.isHidden()
        assert not details["osc"].isHidden()
        assert not fresh._setup_card.isHidden()

    def test_the_card_leaves_once_everything_is_ticked(self, fresh):
        c = fresh.controller
        c.connected.add("Alpha")
        c.osc_ok = c.zones_ok = True
        fresh._refresh_setup_checklist()
        assert fresh._setup_card.isHidden()
        c.osc_ok = False                      # VRChat closed: it comes back
        fresh._refresh_setup_checklist()
        assert not fresh._setup_card.isHidden()

    def test_with_the_built_in_engine_off_it_says_to_start_intiface(self, fresh):
        fresh.controller.settings["use_integrated_intiface"] = False
        fresh._refresh_setup_checklist()
        lead = fresh._setup_lead.text()
        assert "start Intiface Central yourself" in lead
        assert "don't need Intiface" not in lead


class TestZoneSummary:
    """The phrase on a toy's bar: the union of what its chains listen to,
    read the way the Input stage and the router read it."""

    def _summary(self, host, name="Bravo"):
        return host.device_ui_frames[name]["zones_label"].text()

    def test_untouched_toy_listens_to_everything(self, host):
        assert self._summary(host) == "All SPS"

    def test_motor_level_zones(self, host):
        c = host.controller
        c.update_device_config("Bravo", "motor_0_zones", "Pussy")
        c.update_device_config("Bravo", "motor_1_zones", "Pussy")
        host._refresh_toy_summaries()
        assert self._summary(host) == "Pussy"
        c.update_device_config("Bravo", "motor_1_zones", "Anal")
        host._refresh_toy_summaries()
        assert self._summary(host) == "2 zones"

    def test_a_chains_own_zones_win_over_the_motors(self, host):
        c = host.controller
        c.update_device_config("Charlie", "motor_0_zones", "Pussy")
        c.update_device_config("Charlie", "motor_0_c0_zones", "Mouth")
        host._refresh_toy_summaries()
        assert self._summary(host, "Charlie") == "Mouth"

    def test_no_zone_at_all_means_custom_osc_only(self, host):
        host.controller.update_device_config("Charlie", "motor_0_zones", "None")
        host._refresh_toy_summaries()
        assert self._summary(host, "Charlie") == "Custom OSC only"

    def test_all_sps_wins_over_a_named_zone(self, host):
        c = host.controller
        c.update_device_config("Bravo", "motor_0_zones", "All SPS, Pussy")
        c.update_device_config("Bravo", "motor_1_zones", "Anal")
        host._refresh_toy_summaries()
        assert self._summary(host) == "All SPS"


class TestTuningTools:
    def test_folded_on_a_first_launch(self, host):
        assert host._tuning_body.isHidden()

    def test_opening_it_is_remembered(self, host):
        host._tuning_head.clicked.emit()
        assert not host._tuning_body.isHidden()
        assert host.controller.settings["home_tuning_tools_open"] is True
        reopened = _Host(host.controller)
        assert not reopened._tuning_body.isHidden()
        host._tuning_head.clicked.emit()
        assert host._tuning_body.isHidden()
        assert host.controller.settings["home_tuning_tools_open"] is False

    def test_the_bar_says_what_is_switched_on_inside(self, host):
        summary = host._tuning_head.summary
        # Nothing running: it names what it holds.
        assert summary.text() == "Simulator · signal graph"
        host._signal_graph_toggle.setChecked(True)
        assert summary.text() == "Signal graph on"
        host._sim_play_btn.click()
        assert summary.text() == "Simulator playing · signal graph on"
        host._sim_play_btn.click()
        host._signal_graph_toggle.setChecked(False)
        assert summary.text() == "Simulator · signal graph"

    def test_anti_stuck_is_not_a_tuning_tool(self, host):
        """It is a set-and-forget safety default, so it lives in Settings;
        Home must not carry a second copy."""
        from PySide6.QtWidgets import QWidget as _W
        from ui.widgets import ToggleSwitch
        labels = [t.text() for t in host._tuning_tools.findChildren(ToggleSwitch)]
        assert "Anti-stuck" not in labels
        assert not hasattr(host, "toy_antistuck_check")

    def test_the_graph_toggle_is_no_longer_called_overview(self, host):
        assert host._signal_graph_toggle.text() == "Signal graph"


class TestToySafetyInSettings:
    """Anti-stuck's home: Settings → Toy Safety. On unless switched off."""

    class _SettingsHost(DeviceFrameMixin):
        def __init__(self, controller):
            from ui.views.settings import SettingsMixin
            self.controller = controller
            self._build = SettingsMixin._build_toy_safety_card.__get__(self)
            self._on_toy_antistuck_changed = (
                SettingsMixin._on_toy_antistuck_changed.__get__(self))
            self.card = self._build()

        def _repolish(self, widget):
            pass

    def test_on_by_default_with_the_shipped_timeouts(self, qapp):
        h = self._SettingsHost(FakeController())
        assert h.toy_antistuck_check.isChecked()
        assert h.toy_antistuck_active_spin.value() == 1
        assert h.toy_antistuck_peaked_spin.value() == 10
        # Building the card must not write anything back.
        assert h.controller.settings == {}

    def test_changes_reach_the_app_settings_the_router_reads(self, qapp):
        h = self._SettingsHost(FakeController())
        h.toy_antistuck_peaked_spin.setValue(25)
        h.toy_antistuck_check.setChecked(False)
        assert h.controller.settings == {
            "toy_antistuck_enabled": False,
            "toy_antistuck_active_s": 1,
            "toy_antistuck_peaked_s": 25,
        }

    def test_the_timeouts_hide_while_it_is_off(self, qapp):
        h = self._SettingsHost(FakeController())
        row = h.toy_antistuck_active_spin.parentWidget()
        assert not row.isHidden()
        h.toy_antistuck_check.setChecked(False)
        assert row.isHidden()

    def test_every_control_explains_itself(self, qapp):
        h = self._SettingsHost(FakeController())
        for w in (h.toy_antistuck_check, h.toy_antistuck_active_spin,
                  h.toy_antistuck_peaked_spin):
            assert "Anti-stuck" in w.toolTip()


class TestToyFeatureOff:
    def test_the_toy_list_steps_aside_for_a_note(self, host):
        host.controller.features["feature_intiface"] = False
        host.apply_feature_visibility()
        assert host.devices_container_frame.isHidden()
        assert host._tuning_tools.isHidden()
        assert not host._home_toys_off_note.isHidden()
        host.controller.features["feature_intiface"] = True
        host.apply_feature_visibility()
        assert not host.devices_container_frame.isHidden()
        assert host._home_toys_off_note.isHidden()


class TestLiveTipLabel:
    def test_the_tooltip_is_composed_when_it_is_asked_for(self, qapp):
        from ui_components import _LiveTipLabel
        calls = []

        def tip():
            calls.append(1)
            return f"packets: {len(calls)}"

        label = _LiveTipLabel("CONNECTED")
        label.tip_fn = tip
        assert calls == []                      # nothing polls it
        ev = QHelpEvent(QEvent.ToolTip, QPoint(1, 1), QPoint(1, 1))
        QApplication.sendEvent(label, ev)
        assert label.toolTip() == "packets: 1"
