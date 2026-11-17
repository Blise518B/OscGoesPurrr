"""Widget tests for Home -- the landing page, the overview for everything
-- and the Toys page, where each toy's card with its signal chains is.

What the pages promise: every remembered toy is listed on both, connected
ones first in their identity hue and offline ones in a grey outline with
the live-only controls taken away; each bar says what drives the toy; a
toy's row on Home is its bar alone and opens its card on the Toys page;
and the tuning tools stay folded until asked for.

Widget tests run headless against a real QApplication (same pattern as
test_output_controls_view). The mixins are exercised on a minimal host,
mirroring how OscGoesPurrrUI composes them.
"""

import sys

import pytest

from PySide6.QtCore import QEvent, QPoint
from PySide6.QtGui import QHelpEvent
from PySide6.QtWidgets import QApplication, QLabel, QVBoxLayout, QWidget

from ui import theme
from ui.views.dashboard import DashboardMixin
from ui.views.device_frame import DeviceFrameMixin
from ui.views.home import HomeMixin
from ui.views.toys import ToysMixin


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
        self.muted = {}
        self.tested = []
        self.deleted = []

    def get_app_setting(self, key, default=None):
        return self.settings.get(key, default)

    def set_app_setting(self, key, value):
        self.settings[key] = value

    def get_feature_enabled(self, key):
        return self.features.get(key, True)

    def get_avatar_menu(self):
        return getattr(self, "avatar_menu", {})

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

    def is_device_muted(self, name):
        return self.muted.get(name, False)

    def set_device_muted(self, name, muted):
        self.muted[name] = muted

    def test_device(self, name):
        self.tested.append(name)

    def delete_stored_device(self, name):
        self.deleted.append(name)

    def trigger_purr_check(self):
        self.purr_checks += 1

    def get_toy_connected_param(self, device):
        return self.toy_params.get(device, (False, f"OGP/{device}Connected"))

    def set_toy_connected_param(self, device, enabled, name):
        self.toy_params[device] = (enabled, name)

    # Sleep: the sidebar's for every toy, a toy's own (session-only)
    sleep_all = False

    def is_sleep_active(self):
        return self.sleep_all

    def is_toy_sleep_on(self, name):
        return name in getattr(self, "sleeping", set())

    def set_toy_sleep(self, name, on):
        sleeping = self.__dict__.setdefault("sleeping", set())
        (sleeping.add if on else sleeping.discard)(name)

    # anti-stuck: the toys' (app settings) and each toy's own (its wiring)
    def get_toys_antistuck(self):
        import antistuck
        return antistuck.from_app(self.get_app_setting)

    def set_toys_antistuck(self, **changes):
        import antistuck
        new = antistuck.changed(self.get_toys_antistuck(), **changes)
        for field, key in antistuck.TOY_KEYS.items():
            if field in changes:
                self.settings[key] = new[field]

    def is_toy_antistuck_on(self, name):
        import antistuck
        return antistuck.toy_on(self.profiles.get(name))

    def set_toy_antistuck(self, name, on):
        import antistuck
        self.profiles.setdefault(name, {})[antistuck.TOY_KEY] = bool(on)


class _Host(HomeMixin, ToysMixin, DeviceFrameMixin, DashboardMixin):
    """Minimal stand-in for OscGoesPurrrUI: the state the mixins share,
    and Home and the Toys page built into a parent that keeps them alive
    (one under the other; select_view only notes where it was sent)."""

    def __init__(self, controller):
        self.controller = controller
        self.window = QWidget()
        self.nav_buttons = {}
        self.main_stack = None
        self.intiface_sidebar_section = None
        self.device_ui_frames = {}
        self.stored_device_frames = {}
        self.unified_devices_layout = None
        self.home_list_layout = None
        self.selected = []
        page_lay = QVBoxLayout(self.window)
        home, toys = QWidget(), QWidget()
        page_lay.addWidget(home)
        page_lay.addWidget(toys)
        self.views = {"Home": home, "Toys": toys}
        self._build_home_view(QVBoxLayout(home))
        self._build_toys_view(QVBoxLayout(toys))
        self.build_stored_devices_ui()
        self.update_stored_devices_ui()

    def select_view(self, name):
        self.selected.append(name)

    def _repolish(self, widget):
        widget.style().unpolish(widget)
        widget.style().polish(widget)

    def hue(self, name):
        return self.device_ui_frames[name]["frame"].property("hue")

    def row(self, name):
        """The toy's row on Home (its bar's widgets, and "frame")."""
        return self.device_ui_frames[name]["home"]

    def order(self):
        """The Toys page's cards, top to bottom."""
        lay = self.unified_devices_layout
        by_frame = {d["frame"]: n for n, d in self.device_ui_frames.items()}
        return [by_frame[lay.itemAt(i).widget()] for i in range(lay.count())
                if lay.itemAt(i).widget() in by_frame]

    def home_order(self):
        """Home's toy rows, top to bottom."""
        lay = self.home_list_layout
        by_frame = {d["home"]["frame"]: n for n, d in self.device_ui_frames.items()}
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

    def test_a_toy_that_connects_goes_after_the_ones_already_there(self, qapp):
        """Connection order, not the alphabet (Blise's ask, 2026-10-28): the
        first toy keeps place 1 -- its colour and the number in its corner
        -- when another connects."""
        ctl = FakeController(_toys(), connected={"Charlie"})
        ctl.live = ["Charlie"]
        ctl.get_connected_toys_in_order = lambda: [n for n in ctl.live if n in ctl.connected]
        h = _Host(ctl)
        assert h.order() == ["Charlie", "Alpha", "Bravo"] and h.hue("Charlie") == theme.toy_hue(0)
        ctl.connected.add("Alpha")
        ctl.live.append("Alpha")
        h.update_stored_devices_ui()
        assert h.order() == ["Charlie", "Alpha", "Bravo"]
        assert (h.hue("Charlie"), h.hue("Alpha")) == (theme.toy_hue(0), theme.toy_hue(1))
        numbers = [h.device_ui_frames[n]["frame"]._number for n in ("Charlie", "Alpha", "Bravo")]
        assert numbers == [1, 2, 0]                     # an offline toy has none

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
        the next. A card starts open (Blise's ask, 2026-11-16)."""
        from PySide6.QtCore import Qt
        from PySide6.QtTest import QTest
        from PySide6.QtWidgets import QLabel
        frame = host.device_ui_frames["Bravo"]["frame"]
        bar = frame.findChild(QWidget, "toyBar")
        caret = bar.findChild(QLabel, "expandCaret")
        body = frame.findChild(QWidget, "toyBody")
        assert caret.text() == "▾" and not body.isHidden()
        host.window.show()                    # the bar toggles on isVisible
        QTest.mouseClick(bar, Qt.LeftButton)
        assert caret.text() == "▸" and body.isHidden()
        QTest.mouseClick(bar, Qt.LeftButton)
        assert caret.text() == "▾" and not body.isHidden()
        host.window.hide()

    def test_a_card_opens_on_its_motors_chains_each_folded(self, host):
        """The Toys page shows every motor's chains without a click, each
        as its folded bar, under the motor's name; a chain opens on its
        own click."""
        from ui.motor_signal_chain import (
            MotorChainListWidget, MotorSignalChainWidget, _ChainFoldBar)
        host.window.show()
        QApplication.processEvents()
        body = host.device_ui_frames["Bravo"]["body"]
        lists = body.findChildren(MotorChainListWidget)
        assert len(lists) == 2                                   # two motors
        bars = [b for b in body.findChildren(_ChainFoldBar) if b.isVisible()]
        assert len(bars) == 2 and all("▸" == b._arrow.text() for b in bars)
        assert not any(w.isVisible() for w in body.findChildren(MotorSignalChainWidget))
        heads = [w.text() for w in body.findChildren(QLabel, "motorLabel") if w.isVisible()]
        assert heads == ["Motor 0", "Motor 1"]
        assert all(b.toolTip().startswith("<b>Signal chain</b>") for b in bars)
        bars[0].clicked.emit(0)
        QApplication.processEvents()
        assert sum(w.isVisible() for w in body.findChildren(MotorSignalChainWidget)) == 1
        host.window.hide()

    def test_one_and_two_motor_toys_share_a_meter_column(self, host):
        one = host.device_ui_frames["Charlie"]["mini_bar_strip"]
        two = host.device_ui_frames["Bravo"]["mini_bar_strip"]
        assert one.maximumWidth() == two.maximumWidth() == one.minimumWidth()

    def test_no_toys_yet_says_what_to_do(self, qapp):
        from PySide6.QtWidgets import QLabel
        empty = _Host(FakeController({}, connected=()))
        for page in (empty.unified_devices_frame, empty.home_list_frame):
            texts = [w.text() for w in page.findChildren(QLabel)]
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

    def test_dont_show_again_folds_it_to_a_line_of_lights(self, fresh):
        assert fresh._setup_strip.isHidden()
        fresh._setup_hide_btn.click()
        assert fresh.controller.settings["home_setup_compact"] is True
        assert fresh._setup_card.isHidden()
        assert not fresh._setup_strip.isHidden()
        lights = fresh._setup_strip.lights
        assert [n.text() for _d, n in lights.values()] == [
            "Toy on", "VRChat connected", "Avatar has SPS", "Avatar menu"]

    def test_the_lights_follow_the_steps_and_stay_when_all_are_green(self, fresh):
        def lit(key):
            return "solid" not in fresh._setup_strip.lights[key][0].styleSheet()
        fresh._set_setup_compact(True)
        assert not any(lit(k) for k in ("toy", "osc", "zones"))
        c = fresh.controller
        c.connected.add("Alpha")
        fresh._refresh_setup_checklist()
        assert lit("toy") and not lit("osc")
        c.osc_ok = c.zones_ok = True
        fresh._refresh_setup_checklist()
        assert all(lit(k) for k in ("toy", "osc", "zones"))
        assert not fresh._setup_strip.isHidden()    # a status line now
        assert fresh._setup_card.isHidden()

    def test_folded_for_good_across_launches(self, qapp):
        ctl = FakeController({}, connected=())
        ctl.osc_ok = ctl.zones_ok = False
        ctl.settings["home_setup_compact"] = True
        host = _Host(ctl)
        assert host._setup_card.isHidden()
        assert not host._setup_strip.isHidden()

    def test_a_click_on_the_line_opens_the_card_again(self, fresh):
        from PySide6.QtCore import Qt
        from PySide6.QtTest import QTest
        c = fresh.controller
        c.connected.add("Alpha")
        c.osc_ok = c.zones_ok = True
        fresh._set_setup_compact(True)
        QTest.mouseClick(fresh._setup_strip, Qt.LeftButton)
        assert c.settings["home_setup_compact"] is False
        assert fresh._setup_strip.isHidden()
        # everything is green, yet the card you asked for stays
        assert not fresh._setup_card.isHidden()

    def test_the_avatar_menu_is_an_optional_step_that_never_holds_the_card(self, fresh):
        """OGP's menu in the avatar: its own row with the prefab's links and
        a light on the folded line, ticked once the avatar has either part
        -- but the card still leaves when the three real steps are done."""
        from ui.views.avatar_menu import PREFAB_URL, GUIDE_URL
        mark, title, detail = fresh._setup_menu_row
        assert title.text().startswith("Optional") and mark.text() == "○"
        assert PREFAB_URL in detail.text() and GUIDE_URL in detail.text()
        c = fresh.controller
        c.connected.add("Alpha")
        c.osc_ok = c.zones_ok = True
        fresh._refresh_setup_checklist()
        assert fresh._setup_card.isHidden()             # the menu isn't required
        c.avatar_menu = {"known": True, "self": False, "friends": True}
        fresh._set_setup_compact(True)
        assert mark.text() == "✓" and detail.isHidden()
        assert "solid" not in fresh._setup_strip.lights["menu"][0].styleSheet()

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
        """It is a set-and-forget safety default with a card of its own under
        Toy server, not one of the folded tuning tools."""
        from ui.widgets import ToggleSwitch
        labels = [t.text() for t in host._tuning_tools.findChildren(ToggleSwitch)]
        assert "Anti-stuck" not in labels
        assert host._toys_antistuck_card.isAncestorOf(host._toys_antistuck)

    def test_the_graph_toggle_is_no_longer_called_overview(self, host):
        assert host._signal_graph_toggle.text() == "Signal graph"


class TestSafetyInSettings:
    """Settings → Safety (Toy Safety until 2026-11-17): Off while you're
    away, and buttons to each device's own anti-stuck -- no switch of its
    own any more."""

    class _SettingsHost(DeviceFrameMixin):
        def __init__(self, controller, views=("Toys", "Suits", "PSVR2")):
            from ui.views.settings import SettingsMixin
            self.controller = controller
            self.shown, self.selected = set(views), []
            for name in ("_build_toy_safety_card", "_refresh_antistuck_links"):
                setattr(self, name, getattr(SettingsMixin, name).__get__(self))
            self._ANTISTUCK_PAGES = SettingsMixin._ANTISTUCK_PAGES
            self.card = self._build_toy_safety_card()

        def _feature_allows_view(self, name):
            return name in self.shown

        def select_view(self, name):
            self.selected.append(name)

        def _repolish(self, widget):
            pass

    def test_it_is_called_safety_and_has_no_anti_stuck_of_its_own(self, qapp):
        from PySide6.QtWidgets import QLabel, QSlider
        from ui.widgets import ToggleSwitch
        h = self._SettingsHost(FakeController())
        assert "Safety" in [l.text() for l in h.card.findChildren(QLabel)]
        assert "Toy Safety" not in [l.text() for l in h.card.findChildren(QLabel)]
        assert not [t for t in h.card.findChildren(ToggleSwitch) if t.text() == "Anti-stuck"]
        assert not h.card.findChildren(QSlider)
        assert h.controller.settings == {}          # building it writes nothing

    def test_a_button_opens_each_page_that_has_one(self, qapp):
        h = self._SettingsHost(FakeController(), views=("Toys", "PSVR2"))
        links = h._antistuck_links
        assert set(links) == {"Toys", "Suits", "PSVR2"}
        assert not links["Toys"].isHidden() and not links["PSVR2"].isHidden()
        assert links["Suits"].isHidden()            # no suit switched on
        links["PSVR2"].click()
        assert h.selected == ["PSVR2"]
        h.shown.add("Suits")
        h._refresh_antistuck_links()
        assert not links["Suits"].isHidden()

    def test_it_explains_where_anti_stuck_went(self, qapp):
        h = self._SettingsHost(FakeController())
        tip = h._antistuck_links["Toys"].parentWidget().toolTip()
        assert "Anti-stuck" in tip and "Toys page" in tip and "PSVR2" in tip


class TestToysAntiStuck:
    """The toys' anti-stuck on the Toys page, under Toy server: on by
    default, its timers sliders, hidden while it is off."""

    def test_on_by_default_with_the_shipped_timeouts(self, host):
        box = host._toys_antistuck
        assert box.switch.isChecked()
        assert box.active_slider.value() == 1
        assert box.peaked_slider.value() == 10
        assert host.controller.settings == {}       # building it writes nothing

    def test_changes_reach_the_app_settings_the_router_reads(self, host):
        box = host._toys_antistuck
        box.peaked_slider.slider.setValue(box.peaked_slider._to_slider(25))
        box.peaked_slider.flush()
        box.switch.setChecked(False)
        assert host.controller.settings == {
            "toy_antistuck_enabled": False, "toy_antistuck_peaked_s": 25}

    def test_the_timeouts_hide_while_it_is_off(self, host):
        box = host._toys_antistuck
        assert not box.times.isHidden()
        box.switch.setChecked(False)
        assert box.times.isHidden()
        host.controller.settings["toy_antistuck_enabled"] = True
        box.refresh()                               # Ctrl+Z, say: shown again
        assert box.switch.isChecked() and not box.times.isHidden()

    def test_never_a_spin_box(self, host):
        from PySide6.QtWidgets import QAbstractSpinBox
        assert not host._toys_antistuck.findChildren(QAbstractSpinBox)

    def test_every_control_explains_itself(self, host):
        from ui.help_mode import find_control
        box = host._toys_antistuck
        for w in (box.switch, box.active_slider, box.peaked_slider):
            assert w.toolTip().startswith("<b>Toys&#x27; anti-stuck</b>")
        host.window.show()
        assert find_control([host.views["Toys"]], "Toys' anti-stuck") is box.switch
        host.window.hide()


class TestToySleepAndAntiStuckChips:
    """Each toy's own Sleep and Anti-stuck (Blise's ask, 2026-11-17): two
    chips stacked beside the Touch / Penetration ones, on Home's row and the
    Toys page's card alike."""

    @staticmethod
    def _looks(data):
        return {k: (c.isEnabled(), c.property("state"))
                for k, c in data["safety_chips"].items()}

    def test_both_bars_have_them_sleep_off_and_anti_stuck_on(self, host):
        for data in (host.device_ui_frames["Bravo"], host.row("Bravo")):
            assert [c.text() for c in data["safety_chips"].values()] == ["Sleep", "Anti-stuck"]
            assert self._looks(data) == {"sleep": (True, "off"), "antistuck": (True, "on")}

    def test_sleep_puts_just_that_toy_to_sleep_and_both_bars_say_so(self, host):
        host.row("Bravo")["safety_chips"]["sleep"].click()
        assert host.controller.is_toy_sleep_on("Bravo")
        assert not host.controller.is_toy_sleep_on("Charlie")
        assert self._looks(host.device_ui_frames["Bravo"])["sleep"] == (True, "on")
        assert self._looks(host.row("Charlie"))["sleep"] == (True, "off")
        host.device_ui_frames["Bravo"]["safety_chips"]["sleep"].click()
        assert not host.controller.is_toy_sleep_on("Bravo")
        assert self._looks(host.row("Bravo"))["sleep"] == (True, "off")

    def test_the_sidebars_sleep_lights_every_toys_chip(self, host):
        host.controller.sleep_all = True
        host.refresh_output_controls = getattr(host, "refresh_output_controls")
        host._refresh_safety_chips()
        for name in ("Alpha", "Bravo", "Charlie"):
            for data in (host.device_ui_frames[name], host.row(name)):
                assert self._looks(data)["sleep"] == (False, "held")
        host.controller.sleep_all = False
        host._refresh_safety_chips()
        assert self._looks(host.row("Bravo"))["sleep"] == (True, "off")

    def test_anti_stuck_off_for_one_toy_is_remembered_in_its_wiring(self, host):
        import antistuck
        host.row("Charlie")["safety_chips"]["antistuck"].click()
        assert host.controller.profiles["Charlie"][antistuck.TOY_KEY] is False
        assert self._looks(host.device_ui_frames["Charlie"])["antistuck"] == (True, "off")
        assert self._looks(host.row("Bravo"))["antistuck"] == (True, "on")

    def test_greyed_while_the_toys_anti_stuck_is_off(self, host):
        host._toys_antistuck.switch.setChecked(False)
        for data in (host.device_ui_frames["Bravo"], host.row("Bravo")):
            assert self._looks(data)["antistuck"] == (False, "off")
        host._toys_antistuck.switch.setChecked(True)
        assert self._looks(host.row("Bravo"))["antistuck"] == (True, "on")

    def test_they_ride_with_the_contact_chips_in_every_arrangement(self, host):
        from ui.views.device_frame import _BAR_ARRANGEMENTS
        data = host.device_ui_frames["Bravo"]

        def line(w):
            return next(i for i, l in enumerate(data["bar_lines"]) if l.indexOf(w) >= 0)
        for mode, rows in _BAR_ARRANGEMENTS:
            host._arrange_toy_bar(data, mode, rows)
            assert line(data["safety_box"]) == line(data["chips_box"]), (mode, rows)
            grid = data["safety_box"].layout()
            where = [grid.getItemPosition(grid.indexOf(c))[:2]
                     for c in data["safety_chips"].values()]
            assert where == ([(0, 0), (1, 0)] if rows else [(0, 0), (0, 1)])

    def test_an_offline_toy_keeps_them(self, host):
        off = host.device_ui_frames["Alpha"]
        assert not off["safety_box"].isHidden()
        assert self._looks(off) == {"sleep": (True, "off"), "antistuck": (True, "on")}

    def test_each_explains_itself(self, host):
        chips = host.row("Bravo")["safety_chips"]
        assert "Sleep (this toy)" in chips["sleep"].toolTip()
        assert "three full strokes" in chips["sleep"].toolTip()
        assert "Anti-stuck (this toy)" in chips["antistuck"].toolTip()


class TestToyFeatureOff:
    def test_the_toy_list_steps_aside_for_a_note(self, host):
        host.controller.features["feature_intiface"] = False
        host.apply_feature_visibility()
        assert host.devices_container_frame.isHidden()
        assert not host._home_toys_off_note.isHidden()
        assert not host._feature_allows_view("Toys")      # the page goes too
        host.controller.features["feature_intiface"] = True
        host.apply_feature_visibility()
        assert not host.devices_container_frame.isHidden()
        assert host._home_toys_off_note.isHidden()
        assert host._feature_allows_view("Toys")


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


class TestContactChips:
    """Touch / Penetration x Self / Others on each toy's bar: a chip sets
    its pair on every chain of the toy that hears that kind (active mode),
    shows half lit while they disagree, and is greyed when none does."""

    @pytest.fixture
    def chips_host(self, qapp):
        typed = {"0": {"chains": [{"type": "penetration"}, {"type": "touch"}],
                       "merge": "max"}}
        toys = {
            "Duo": {"motor_count": 1, "mix": typed},
            "Touchy": {"motor_count": 1,
                       "mix": {"0": {"chains": [{"type": "touch"}]}}},
            "Twin": {"motor_count": 2},            # two custom chains
        }
        return _Host(FakeController(toys, connected=set(toys)))

    @staticmethod
    def _chips(host, name):
        return host.device_ui_frames[name]["contact_chips"]

    def _states(self, host, name):
        return {p: (c.property("state") if c.isEnabled() else None)
                for p, c in self._chips(host, name).items()}

    def test_four_chips_after_the_zones_summary(self, chips_host):
        data = chips_host.device_ui_frames["Duo"]
        assert list(data["contact_chips"]) == [
            "touch_self", "touch_others", "pen_self", "pen_others"]
        box = data["chips_box"]
        assert all(c.parentWidget() is box for c in data["contact_chips"].values())
        for line in data["bar_lines"]:
            at = line.indexOf(data["zones_label"])
            if at >= 0:
                assert line.indexOf(box) == at + 1          # right after it
                break
        else:
            raise AssertionError("the zones summary is on no line")

    def test_a_fresh_toy_shows_the_defaults(self, chips_host):
        assert self._states(chips_host, "Duo") == {
            "touch_self": "off", "touch_others": "on",
            "pen_self": "off", "pen_others": "on"}

    def test_a_chip_sets_its_pair_on_the_chains_of_its_kind_only(self, chips_host):
        c = chips_host.controller
        self._chips(chips_host, "Duo")["touch_others"].click()
        duo = c.profiles["Duo"]
        assert duo["motor_0_c1_touch_others"] is False      # the Touch chain
        assert "motor_0_c0_touch_others" not in duo         # Penetration: no
        assert self._states(chips_host, "Duo")["touch_others"] == "off"
        self._chips(chips_host, "Duo")["pen_self"].click()
        assert duo["motor_0_c0_pen_self"] is True
        assert "motor_0_c1_pen_self" not in duo
        assert self._states(chips_host, "Duo")["pen_self"] == "on"

    def test_half_lit_while_the_chains_disagree_and_a_click_agrees_on(self, chips_host):
        c = chips_host.controller
        c.update_device_config("Twin", "motor_1_c0_touch_self", True)
        chips_host._refresh_toy_summaries()
        chip = self._chips(chips_host, "Twin")["touch_self"]
        assert chip.property("state") == "half"
        chip.click()
        assert c.profiles["Twin"]["motor_0_c0_touch_self"] is True
        assert c.profiles["Twin"]["motor_1_c0_touch_self"] is True
        assert chip.property("state") == "on"
        chip.click()                                    # all on -> all off
        assert c.profiles["Twin"]["motor_0_c0_touch_self"] is False
        assert chip.property("state") == "off"

    def test_a_touch_only_toy_greys_its_penetration_chips(self, chips_host):
        chips = self._chips(chips_host, "Touchy")
        assert chips["touch_self"].isEnabled() and chips["touch_others"].isEnabled()
        assert not chips["pen_self"].isEnabled()
        assert not chips["pen_others"].isEnabled()

    def test_a_change_elsewhere_reaches_the_chips_on_the_next_refresh(self, chips_host):
        chips_host.controller.update_device_config("Duo", "motor_0_c1_touch_self", True)
        chips_host._refresh_toy_summaries()
        assert self._states(chips_host, "Duo")["touch_self"] == "on"

    def test_each_chip_explains_itself(self, chips_host):
        tip = self._chips(chips_host, "Duo")["pen_others"].toolTip()
        assert "Penetration from others" in tip and "Half lit" in tip


class TestInputStageContactSwitches:
    """The toy's Input stage shows the same four switches per chain."""

    @pytest.fixture
    def duo(self, qapp):
        typed = {"0": {"chains": [{"type": "penetration"}, {"type": "touch"}],
                       "merge": "max"}}
        return _Host(FakeController({"Duo": {"motor_count": 1, "mix": typed}},
                                    connected={"Duo"}))

    def _switches(self, host, chain_idx, chain_type):
        from ui.widgets import ToggleSwitch
        col = host._build_listening_to_column("Duo", 0, {}, chain_idx=chain_idx,
                                              chain_type=chain_type)
        host._keep = col
        return {s.objectName()[len("contact_"):]: s
                for s in col.findChildren(ToggleSwitch)
                if s.objectName().startswith("contact_")}

    def test_four_switches_the_other_kind_greyed_on_a_typed_chain(self, duo):
        sw = self._switches(duo, 1, "touch")
        assert set(sw) == {"touch_self", "touch_others", "pen_self", "pen_others"}
        assert sw["touch_self"].isEnabled() and sw["touch_others"].isEnabled()
        assert not sw["pen_self"].isEnabled() and not sw["pen_others"].isEnabled()
        assert not sw["touch_self"].isChecked() and sw["touch_others"].isChecked()

    def test_a_custom_chain_has_all_four(self, duo):
        sw = self._switches(duo, 0, "custom")
        assert all(s.isEnabled() for s in sw.values())

    def test_a_switch_writes_its_chain_and_lights_the_chip(self, duo):
        sw = self._switches(duo, 1, "touch")
        sw["touch_self"].setChecked(True)
        assert duo.controller.profiles["Duo"]["motor_0_c1_touch_self"] is True
        chip = duo.device_ui_frames["Duo"]["contact_chips"]["touch_self"]
        assert chip.property("state") == "on"

    def test_a_chip_click_moves_an_open_input_stage(self, duo):
        sw = self._switches(duo, 1, "touch")
        duo.device_ui_frames["Duo"]["contact_chips"]["touch_others"].click()
        assert not sw["touch_others"].isChecked()


class TestToyBarWraps:
    """Blise's ask (2026-11-16): one line while it fits -- the name, the
    Touch and Penetration chips as two rows, the battery, meters, Mute and
    Test, all centred -- and only when the room runs out the name line
    with the chips under it, then the battery and meters on a line of
    their own. Decided by the room the bar has; never a sideways
    scrollbar. Home's row and the Toys page's card alike."""

    def _place(self, host, width, name="Bravo", home=False):
        host.window.resize(width, 900)
        host.window.show()
        for _ in range(6):        # resizes, re-arranges, scrollbars settle
            QApplication.processEvents()
        data = host.device_ui_frames[name]
        return (data["home"] if home else data)

    @staticmethod
    def _line_of(data, key):
        w = data[key]
        return next(i for i, line in enumerate(data["bar_lines"]) if line.indexOf(w) >= 0)

    @staticmethod
    def _room(data):
        m = data["bar"].layout().contentsMargins()
        return data["bar"].width() - m.left() - m.right()

    def _place_for(self, host, arrangement, name="Bravo"):
        """A window that gives the bar room for `arrangement` and for no
        wider one: as little as the window allows above what it needs.
        Worked out from the bar's own needs, so it holds whatever the font
        (Linux's stand-in for Segoe UI fit one line at 1100 px, CI 0.16.0)."""
        from ui.views.device_frame import _BAR_ARRANGEMENTS
        data = self._place(host, 1700, name=name)
        need = host._toy_bar_need(data, *arrangement)
        wider = [host._toy_bar_need(data, *a)
                 for a in _BAR_ARRANGEMENTS[:_BAR_ARRANGEMENTS.index(arrangement)]]
        below = min(wider, default=10 ** 6)         # the room where a wider one fits
        assert need < below, (arrangement, need, wider)
        for _ in range(4):                  # a scrollbar coming or going moves the room
            have = self._room(data)
            if need <= have < below:
                break
            data = self._place(host, host.window.width() + need - have, name=name)
        assert need <= self._room(data) < below, (arrangement, need, below, self._room(data))
        return data

    @staticmethod
    def _first_fit(host, data):
        from ui.views.device_frame import _BAR_ARRANGEMENTS
        m = data["bar"].layout().contentsMargins()
        room = data["bar"].width() - m.left() - m.right()
        return next(((mode, rows) for mode, rows in _BAR_ARRANGEMENTS
                     if host._toy_bar_need(data, mode, rows) <= room), ("three", True))

    @pytest.mark.parametrize("home", [False, True])
    def test_the_widest_arrangement_that_fits_is_taken(self, host, home):
        data = self._place(host, 1700, home=home)
        assert data["bar_mode"] == ("wide", True)
        for width in (1300, 1000, 860, 700):
            data = self._place(host, width, home=home)
            assert data["bar_mode"] == self._first_fit(host, data), width
        data = self._place(host, 1700, home=home)
        assert data["bar_mode"] == ("wide", True)        # and back
        host.window.hide()

    def test_each_arrangements_lines(self, host):
        data = host.device_ui_frames["Bravo"]
        host._arrange_toy_bar(data, "wide", True)
        assert {self._line_of(data, k) for k in (
            "name_label", "zones_label", "chips_box", "battery_label",
            "mini_bar_strip", "mute_button", "test_button")} == {0}
        host._arrange_toy_bar(data, "two", False)
        for key in ("name_label", "battery_label", "mini_bar_strip",
                    "mute_button", "test_button"):
            assert self._line_of(data, key) == 0, key
        assert self._line_of(data, "chips_box") == self._line_of(data, "zones_label") == 1
        host._arrange_toy_bar(data, "three", True)
        assert self._line_of(data, "mute_button") == 0
        assert self._line_of(data, "battery_label") == 1
        assert self._line_of(data, "chips_box") == 2
        # the widest first: one line is narrower than two only while the
        # chips' block of two rows saves more than the second line costs
        assert host._toy_bar_need(data, "three", True) < host._toy_bar_need(data, "two", False)

    def test_what_fits_never_depends_on_what_is_shown(self, host):
        """The room each arrangement needs is the same whichever one the bar
        shows now -- or a bar at the edge would flip back and forth."""
        from ui.views.device_frame import _BAR_ARRANGEMENTS
        data = host.device_ui_frames["Bravo"]
        seen = []
        for mode, rows in _BAR_ARRANGEMENTS:
            host._arrange_toy_bar(data, mode, rows)
            seen.append([host._toy_bar_need(data, m, r) for m, r in _BAR_ARRANGEMENTS])
        assert all(s == seen[0] for s in seen)

    def test_wide_chips_are_two_rows_with_the_captions_in_a_column(self, host):
        data = self._place(host, 1700)
        grid = data["chips_box"].layout()
        caps = data["chip_captions"]
        chips = data["contact_chips"]

        def cell(w):
            r, c, _rs, _cs = grid.getItemPosition(grid.indexOf(w))
            return r, c
        assert cell(caps["Touch"]) == (0, 0) and cell(caps["Penetration"]) == (1, 0)
        assert cell(chips["touch_self"]) == (0, 1) and cell(chips["pen_others"]) == (1, 2)
        assert caps["Touch"].x() == caps["Penetration"].x()
        assert chips["touch_self"].x() == chips["pen_self"].x()
        # under the name on one row while that fits there ...
        data = self._place_for(host, ("two", False))
        assert data["bar_mode"] == ("two", False)
        assert cell(caps["Penetration"]) == (0, 3) and cell(chips["pen_others"]) == (0, 5)
        # ... else under the name on two rows, Sleep over Anti-stuck beside them
        data = self._place_for(host, ("two", True))
        assert data["bar_mode"] == ("two", True)
        assert cell(caps["Penetration"]) == (1, 0)
        safety = data["safety_box"].layout()
        sleep, stuck = data["safety_chips"]["sleep"], data["safety_chips"]["antistuck"]
        assert safety.getItemPosition(safety.indexOf(sleep))[:2] == (0, 0)
        assert safety.getItemPosition(safety.indexOf(stuck))[:2] == (1, 0)
        host.window.hide()

    def test_wide_everything_is_centred_on_the_one_line(self, host):
        data = self._place(host, 1700)
        bar = data["bar"]
        mid = bar.height() / 2
        for key in ("name_label", "chips_box", "battery_label", "mute_button", "test_button"):
            w = data[key]
            assert abs(w.geometry().center().y() - mid) <= 2, key
        host.window.hide()

    def test_an_offline_row_follows_the_same_rule(self, host):
        """Its battery, meters, Mute and Test are gone, so its one line is
        shorter -- and the same rule keeps it there longer."""
        data = self._place(host, 1700, name="Alpha")
        assert data["bar_mode"] == ("wide", True)
        live = host.device_ui_frames["Bravo"]
        assert host._toy_bar_need(data, "wide", True) < host._toy_bar_need(live, "wide", True)
        for width in (1000, 800):
            data = self._place(host, width, name="Alpha")
            assert data["bar_mode"] == self._first_fit(host, data), width
        host.window.hide()

    @pytest.mark.parametrize("width", [1700, 1100, 960, 860, 700, 560])
    def test_no_bar_is_wider_than_its_place(self, host, width):
        """No sideways scrollbar: every bar fits the width it is given."""
        self._place(host, width)
        for data in host.device_ui_frames.values():
            for one in host._toy_bars(data):
                bar = one["bar"]
                m = bar.layout().contentsMargins()
                room = bar.width() - m.left() - m.right()
                assert host._toy_bar_need(one, *one["bar_mode"]) <= room or \
                    one["bar_mode"] == ("three", True)
                assert bar.width() <= bar.parentWidget().width()
        host.window.hide()


def test_a_toy_that_connects_wears_its_colour_on_its_name_too(qapp):
    """The name's colour comes from the bar's hue through an ancestor
    selector, so it has to be polished again when the hue changes: a toy
    that connected after the page was styled kept the offline grey (the
    headless renders showed white names)."""
    from PySide6.QtGui import QColor, QPalette
    ctl = FakeController(_toys(), connected={"Charlie"})
    ctl.live = ["Charlie"]
    ctl.get_connected_toys_in_order = lambda: [n for n in ctl.live if n in ctl.connected]
    h = _Host(ctl)
    h.window.setStyleSheet(theme.build_qss())
    ctl.connected.add("Alpha")
    ctl.live.append("Alpha")
    h.update_stored_devices_ui()
    hue = theme.toy_hue(1)
    want = QColor(theme.PALETTE[hue][0])
    for bar in (h.device_ui_frames["Alpha"], h.row("Alpha")):
        name = bar["name_label"]
        name.ensurePolished()
        assert name.palette().color(QPalette.WindowText) == want


class TestHomeIsTheOverview:
    """Home's row for a toy is its bar alone -- the same live state as its
    card on the Toys page -- and a click on it opens that card (Blise's
    call, 2026-11-14: Home is the overview, the detail lives on each
    device's page)."""

    def test_every_toy_has_a_row_on_home_in_the_same_order_and_hue(self, host):
        assert host.home_order() == host.order() == ["Bravo", "Charlie", "Alpha"]
        for name in ("Bravo", "Charlie", "Alpha"):
            row = host.row(name)["frame"]
            assert row.property("hue") == host.hue(name)
            assert row._number == host.device_ui_frames[name]["frame"]._number

    def test_a_row_is_the_bar_alone_and_says_a_click_goes_somewhere(self, host):
        row = host.row("Bravo")
        assert row["frame"].findChild(QWidget, "toyBody") is None
        assert row["caret"].text() == "›"
        assert host.device_ui_frames["Bravo"]["caret"].text() == "▾"   # open
        # the quick switches are all there
        assert set(row["contact_chips"]) == {
            "touch_self", "touch_others", "pen_self", "pen_others"}
        for key in ("mute_button", "test_button", "battery_label", "mini_bar_strip"):
            assert row[key] is not None, key

    def test_a_click_on_a_row_opens_the_toy_at_its_card(self, host):
        from PySide6.QtCore import Qt
        from PySide6.QtTest import QTest
        host.window.show()
        card = host.device_ui_frames["Charlie"]
        card["set_expanded"](False)              # folded away on the page
        host.device_ui_frames["Bravo"]["set_expanded"](False)
        QTest.mouseClick(host.row("Charlie")["bar"], Qt.LeftButton)
        assert host.selected == ["Toys"]
        assert not card["body"].isHidden() and card["caret"].text() == "▾"
        # the others stay as they were
        assert host.device_ui_frames["Bravo"]["body"].isHidden()
        host.window.hide()

    def test_its_buttons_keep_their_own_clicks(self, host):
        host.row("Bravo")["test_button"].click()
        assert host.selected == []

    def test_the_row_scrolls_its_card_into_view(self, host):
        host.window.resize(900, 700)
        host.window.show()
        QApplication.processEvents()
        host.open_toy_card("Alpha")
        QApplication.processEvents()
        host._scroll_to_toy("Alpha")
        bar = host._toys_list_scroll.verticalScrollBar()
        card = host.device_ui_frames["Alpha"]["frame"]
        inner = host._toys_list_scroll.widget()
        top = card.mapTo(inner, QPoint(0, 0)).y()
        assert bar.value() == min(bar.maximum(), max(0, top - 4))
        host.window.hide()

    def test_offline_and_battery_reach_both_bars(self, host):
        for bar in (host.device_ui_frames["Alpha"], host.row("Alpha")):
            assert bar["test_button"].isHidden() and not bar["offline_pill"].isHidden()
        host.update_battery_label("Bravo", 0.42)
        assert host.row("Bravo")["battery_label"].text() == "🔋 42%"
        assert host.device_ui_frames["Bravo"]["battery_label"].text() == "🔋 42%"
        host.controller.connected.add("Alpha")
        host.update_stored_devices_ui()
        assert not host.row("Alpha")["test_button"].isHidden()
        assert host.row("Alpha")["offline_pill"].isHidden()

    def test_the_meters_move_on_both(self, host):
        host.update_motor_vibe("Bravo", 1, 0.5)
        assert host.row("Bravo")["mini_bars"][1].get() == 0.5
        assert host.device_ui_frames["Bravo"]["mini_bars"][1].get() == 0.5
        host.update_motor_vibe("Bravo", -1, 0.25)
        assert [m.get() for m in host.row("Bravo")["mini_bars"]] == [0.25, 0.25]

    def test_mute_on_one_bar_shows_on_the_other(self, host):
        row_mute = host.row("Bravo")["mute_button"]
        card_mute = host.device_ui_frames["Bravo"]["mute_button"]
        row_mute.click()
        assert host.controller.muted == {"Bravo": True}
        assert card_mute.isChecked() and card_mute.text() == "Muted"
        card_mute.click()
        assert host.controller.muted == {"Bravo": False}
        assert not row_mute.isChecked() and row_mute.text() == "Mute"

    def test_a_chip_on_home_paints_the_card_too(self, host):
        chip = host.row("Bravo")["contact_chips"]["touch_self"]
        card_chip = host.device_ui_frames["Bravo"]["contact_chips"]["touch_self"]
        assert chip.property("state") == card_chip.property("state") == "off"
        chip.click()
        assert host.controller.profiles["Bravo"]["motor_0_c0_touch_self"] is True
        assert chip.property("state") == card_chip.property("state") == "on"

    def test_the_zones_summary_reaches_both(self, host):
        host.controller.update_device_config("Charlie", "motor_0_zones", "Mouth")
        host._refresh_toy_summaries()
        assert host.row("Charlie")["zones_label"].text() == "Mouth"
        assert host.device_ui_frames["Charlie"]["zones_label"].text() == "Mouth"

    def test_home_keeps_test_all_and_the_toys_page_the_detail(self, host):
        from ui.views.click_bars import FoldHeader
        home, toys = host.views["Home"], host.views["Toys"]
        assert home.isAncestorOf(host._test_all_button)
        assert not home.findChildren(FoldHeader)
        assert {f.findChild(QLabel, "cardHeader").text()
                for f in toys.findChildren(FoldHeader)} == {"SPS Sources", "Tuning tools"}
        assert toys.isAncestorOf(host._toy_scan_btn)
        assert toys.isAncestorOf(host._toy_server_card)
        assert toys.isAncestorOf(host.device_ui_frames["Bravo"]["frame"])
        assert home.isAncestorOf(host.row("Bravo")["frame"])

    def test_a_forgotten_toy_leaves_both(self, host):
        row = host.row("Alpha")["frame"]
        host.remove_device_frame("Alpha")
        QApplication.processEvents()
        assert "Alpha" not in host.device_ui_frames
        assert host.home_list_layout.indexOf(row) < 0


class TestCardFoot:
    """Blise's critique (2026-11-17): the avatar parameters and Delete device
    took half a card. The chains own it now; those wait in one small line at
    its very bottom -- a closed Avatar parameters fold saying how many are
    on, and Delete device as words in the danger colour at its right end."""

    def _rows(self, host, name):
        from ui.widgets import ToggleSwitch
        fold = host.device_ui_frames[name]["params_fold"]
        return [t.text() for t in fold.findChildren(ToggleSwitch)]

    def test_the_line_comes_last_after_every_motors_chains(self, host):
        from ui.widgets import ToggleSwitch
        data = host.device_ui_frames["Bravo"]
        lay = data["body"].layout()
        widgets = [lay.itemAt(i).widget() for i in range(lay.count())
                   if lay.itemAt(i).widget() is not None]
        assert widgets[-1] is data["foot"]
        # no parameter row sits between the motors any more
        for w in widgets[:-1]:
            assert not [t for t in w.findChildren(ToggleSwitch) if "VRChat" in t.text()], w

    def test_the_fold_is_closed_and_holds_every_parameter_row(self, host):
        data = host.device_ui_frames["Bravo"]
        assert data["params_fold"].isHidden()
        assert self._rows(host, "Bravo") == [
            "Mirror motor 0 to VRChat parameter", "Mirror motor 1 to VRChat parameter",
            "Tell VRChat while this toy is connected"]
        assert self._rows(host, "Charlie") == [
            "Mirror to VRChat parameter", "Tell VRChat while this toy is connected"]
        data["params_button"].click()
        assert not data["params_fold"].isHidden()
        assert data["params_button"].text().startswith("▾")
        data["params_button"].click()
        assert data["params_fold"].isHidden()

    def test_folded_it_says_how_many_are_on(self, host):
        from ui.widgets import ToggleSwitch
        data = host.device_ui_frames["Charlie"]
        assert data["params_count"].text() == "none on"
        switches = data["params_fold"].findChildren(ToggleSwitch)
        switches[-1].setChecked(True)                   # Tell VRChat
        assert data["params_count"].text() == "1 on"
        switches[0].setChecked(True)                    # Mirror
        assert data["params_count"].text() == "2 on"
        assert host.controller.toy_params["Charlie"][0] is True

    def test_the_name_boxes_are_small_and_line_up(self, host):
        from PySide6.QtWidgets import QLineEdit
        edits = host.device_ui_frames["Bravo"]["params_fold"].findChildren(QLineEdit)
        assert len(edits) == 3
        assert {e.maximumWidth() for e in edits} == {host._TOY_PARAM_EDIT_MAX}
        host.window.resize(1700, 900)
        host.window.show()
        host.device_ui_frames["Bravo"]["params_open"](True)
        for _ in range(4):
            QApplication.processEvents()
        assert len({e.mapTo(host.window, QPoint(0, 0)).x() for e in edits}) == 1
        host.window.hide()

    def test_delete_device_is_words_at_the_end_of_the_line(self, host):
        data = host.device_ui_frames["Bravo"]
        btn = data["delete_button"]
        assert btn.property("role") == "dangerText"
        line = data["foot"].layout().itemAt(0).layout()
        assert line.indexOf(btn) == line.count() - 1
        host.update_stored_devices_ui()                 # the heartbeat leaves it so
        assert btn.property("role") == "dangerText"
        btn.click()
        assert host.controller.deleted == ["Bravo"]
