"""The Toys page: every toy's card with its signal chains, SPS Sources, the
toy server and scan, and the tuning tools -- moved off Home, which became
the overview for everything (Blise's call, 2026-11-14).

Widget tests run headless against a real QApplication on the same minimal
host as test_home_view (Home and the Toys page built side by side)."""

import sys

import pytest

from PySide6.QtWidgets import QApplication, QWidget

from ui import page_steps
from ui.help_mode import find_control
from ui.views.toys import server_line, server_pill

from test_home_view import FakeController, _Host, _toys


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication(sys.argv[:1])


class ToysController(FakeController):
    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self.link = {"built_in": True, "looking": False}
        self.scan = {"up": True, "auto": True, "scanning": False, "next_in": 4}
        self.scans = 0
        self.connects = 0
        self.sources = []

    def get_intiface_link_status(self):
        return dict(self.link)

    def get_toy_scan_status(self):
        return dict(self.scan)

    def scan_for_toys(self):
        self.scans += 1

    def connect_to_intiface(self):
        self.connects += 1

    def get_sps_sources(self):
        return list(self.sources)


@pytest.fixture
def host(qapp):
    return _Host(ToysController(_toys(), connected={"Bravo", "Charlie"}))


# ----------------------------------------------------------------------
# The sidebar
# ----------------------------------------------------------------------

class _SidebarController:
    def get_modes_info(self):
        return [{"name": f"Mode {i}", "icon": "", "active": i == 0} for i in range(4)]

    def get_intiface_link_status(self):
        return {"built_in": True}

    def get_app_setting(self, key, default=None):
        return default

    def toggle_osc_connection(self):
        pass

    def connect_to_intiface(self):
        pass

    def scan_for_toys(self):
        pass

    def set_intiface_address(self, _text):
        return True, ""


@pytest.fixture
def sidebar(qapp):
    from ui.live_theme import LiveTheme
    from ui_components import OscGoesPurrrUI
    ui = OscGoesPurrrUI.__new__(OscGoesPurrrUI)          # no window, no wiring
    ui.controller = _SidebarController()
    ui.window = QWidget()
    ui.live_theme = LiveTheme(ui.window)
    ui.nav_buttons = {}
    ui.views = {}
    ui.main_stack = None
    ui.connection_button = ui.scan_toys_button = ui.status_label = None
    ui._keep = ui._build_sidebar()
    return ui


class TestSidebar:
    def test_the_sidebar_goes_home_friends_then_the_devices(self, sidebar):
        # Blise's call (2026-11-17): Friends after Home, then the devices in
        # Home's own order, then My Avatar Remote
        names = list(sidebar.nav_buttons)
        assert names[:7] == ["Home", "Friends", "Toys", "Shockers", "Suits", "PSVR2",
                             "My Avatar Remote"]

    def test_toys_wears_the_toys_icon(self, sidebar):
        from ui_components import OscGoesPurrrUI
        assert OscGoesPurrrUI._NAV_ICONS["Toys"] == "toys"   # the pink capsule
        assert not sidebar.nav_buttons["Toys"].icon().isNull()
        assert "Toys" in OscGoesPurrrUI._NAV_TIPS

    def test_sps_sources_is_no_page_of_its_own_any_more(self, sidebar):
        from ui_components import OscGoesPurrrUI
        assert "SPS Sources" not in sidebar.nav_buttons
        assert "SPS Sources" not in OscGoesPurrrUI._NAV_ICONS

    def test_the_toys_page_goes_with_the_toy_server_feature(self, host):
        assert host._FEATURE_VIEW_REQUIREMENTS["Toys"] == ("feature_intiface",)


# ----------------------------------------------------------------------
# The toy server line
# ----------------------------------------------------------------------

class TestToyServerWords:
    def test_built_in(self):
        assert server_line({"built_in": True}, True) == ("✓ Built in, on this PC", "ok")
        assert server_line({"built_in": True}, False) == ("Built in, not connected", "")

    def test_your_own_intiface_says_what_settings_says(self):
        text, accent = server_line({"built_in": False, "looking": True}, False)
        assert text == "Looking on this PC and your network…" and accent == ""
        text, accent = server_line({"built_in": False, "connected": True,
                                    "target": "192.168.1.50:12345",
                                    "target_name": "Pixel"}, True)
        assert text == "✓ Connected to Pixel at 192.168.1.50:12345" and accent == "ok"
        _text, accent = server_line({"built_in": False, "too_old": True,
                                     "target": "1.2.3.4:5"}, False)
        assert accent == "warn"

    def test_the_pill_is_the_sidebars(self):
        assert server_pill(True, False) == ("CONNECTED", "ok")
        assert server_pill(False, True) == ("SEARCHING", "off")
        assert server_pill(False, False) == ("DISCONNECTED", "off")


class TestToyServerCard:
    def test_connected_built_in(self, host):
        host._toy_server_connected = True
        host._refresh_toy_server()
        assert host._toy_server_pill.text() == "CONNECTED"
        assert host._toy_server_where.text() == "✓ Built in, on this PC"
        assert host._toy_server_connect.isHidden()

    def test_down_and_nothing_bringing_it_up_offers_connect(self, host):
        host._toy_server_connected = False
        host._refresh_toy_server()
        assert host._toy_server_pill.text() == "DISCONNECTED"
        assert not host._toy_server_connect.isHidden()
        host._toy_server_connect.click()
        assert host.controller.connects == 1

    def test_looking_for_your_own_intiface_offers_nothing_to_press(self, host):
        host._toy_server_connected = False
        host.controller.link = {"built_in": False, "looking": True}
        host._refresh_toy_server()
        assert host._toy_server_pill.text() == "SEARCHING"
        assert host._toy_server_connect.isHidden()
        assert "Looking" in host._toy_server_where.text()

    def test_intiface_settings_leads_to_settings(self, host):
        reveals = []
        host.reveal = lambda place: reveals.append(place) or True
        host._open_intiface_settings()
        assert reveals == ["intiface"]

    def test_every_part_explains_itself(self, host):
        for w in (host._toy_server_pill, host._toy_server_where,
                  host._toy_server_connect):
            assert w.toolTip().startswith("<b>")


# ----------------------------------------------------------------------
# Scan now, the folds
# ----------------------------------------------------------------------

class TestScanNow:
    def test_says_when_it_looks_next(self, host):
        host._refresh_toy_scan()
        assert host._toy_scan_lbl.text() == "Next scan in 4 s"
        host.controller.scan["auto"] = False
        host.controller.scan["next_in"] = None
        host._refresh_toy_scan()
        assert host._toy_scan_lbl.text() == "Looking for toys is off"

    def test_scan_now_looks(self, host):
        host._toy_scan_btn.click()
        assert host.controller.scans == 1
        assert host._toy_scan_lbl.text() == "Scanning…"

    def test_nothing_to_scan_with_while_the_server_is_down(self, host):
        host.controller.scan["up"] = False
        host._refresh_toy_scan()
        assert not host._toy_scan_btn.isEnabled()


class TestFolds:
    def test_sps_sources_is_folded_and_counts_them(self, host):
        assert host._sps_body.isHidden()
        host._refresh_sps_summary()
        assert host._sps_head.summary.text() == "Your own zones from any contact"
        host.controller.sources = [{"name": "Hip"}, {"name": "Neck"}]
        host._refresh_sps_summary()
        assert host._sps_head.summary.text() == "2 sources"
        host._sps_head.clicked.emit()
        assert not host._sps_body.isHidden()
        assert "toys_sps_open" not in host.controller.settings   # nothing saved

    def test_tuning_tools_keep_their_setting(self, host):
        """Its open / closed is remembered under its old name -- no setting
        was renamed by the move."""
        host._tuning_head.clicked.emit()
        assert host.controller.settings["home_tuning_tools_open"] is True


# ----------------------------------------------------------------------
# Every step finds its control on its page
# ----------------------------------------------------------------------

class TestSteps:
    @pytest.fixture
    def shown(self, qapp):
        ctl = ToysController(_toys(), connected={"Bravo", "Charlie"})
        ctl.settings["home_setup_compact"] = True      # the folded line's lights
        h = _Host(ctl)
        # the sidebar's strength bar lives in the sidebar, beside the pages
        h.window.layout().addWidget(h._build_mode_grid())
        h.window.resize(1200, 1600)
        h.window.show()
        # the card opened, on its motors' folded chains: a chain open
        from ui.motor_signal_chain import _ChainFoldBar
        h.device_ui_frames["Bravo"]["set_expanded"](True)
        QApplication.processEvents()
        bar = next(b for b in h.device_ui_frames["Bravo"]["body"].findChildren(_ChainFoldBar)
                   if b.isVisible())
        bar.clicked.emit(bar._chain_idx)
        QApplication.processEvents()
        yield h
        h.window.hide()

    @pytest.mark.parametrize("page", ["Home", "Toys"])
    def test_every_step_target_is_on_its_page(self, shown, page):
        steps = page_steps.for_page(page)
        assert steps
        scopes = [shown.views[page], shown.window]
        for step in steps:
            names = (step.target,) if isinstance(step.target, str) else step.target
            for name in names:
                found = find_control(scopes, name)
                assert found is not None, f"{page}: {step.label!r} -> {name!r}"

    def test_the_chips_step_lights_homes_row_not_the_card(self, shown):
        found = find_control([shown.views["Home"]], "Touch from yourself")
        assert shown.views["Home"].isAncestorOf(found)

    def test_home_no_longer_points_at_signal_chains(self):
        targets = set()
        for step in page_steps.for_page("Home"):
            targets.update((step.target,) if isinstance(step.target, str) else step.target)
        assert not targets & {"Input", "Depth", "Punch", "Output", "Scan now"}


# ----------------------------------------------------------------------
# What's new
# ----------------------------------------------------------------------

class TestWhatsNewTargets:
    def test_toys_is_a_place_and_the_toy_items_go_there(self):
        import whats_new
        from ui.views.whats_new import PLACES
        assert PLACES["toys"] == ("Toys", "")
        by_title = {i.title: i.target for r in whats_new.RELEASES for i in r.items}
        assert by_title["One Home page"] == "toys"         # its signal chains
        assert by_title["Toys found faster"] == "toys"     # Scan now
        assert by_title["Home keeps its order"] == "home"  # the rows' order
