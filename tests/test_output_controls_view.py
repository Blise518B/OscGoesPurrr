"""Widget tests for the sidebar control block — the four mode buttons,
the total output strength bar and the Off / Sleep buttons.

The sidebar is the only way to reach the global multiplier from the
desktop app, so the wiring that matters is: user input reaches the
controller exactly once, and a change made anywhere else (the VRChat
menu) repaints the block without echoing back.

Widget tests run headless against a real QApplication (same pattern as
test_backend_views_common). The mixin is exercised standalone on a
minimal host, mirroring how OscGoesPurrrUI composes it.
"""

import sys

import pytest

from PySide6.QtWidgets import QApplication, QLabel, QVBoxLayout, QWidget

from ui.views.dashboard import DashboardMixin


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication(sys.argv[:1])


class FakeController:
    """Stands in for OscGoesPurrrApp's modes facade."""

    def __init__(self):
        self.strength = 0.85
        self.off = False
        self.sleep = False
        self.strength_calls = []
        self.off_calls = []
        self.sleep_calls = []
        self.switches = []

    # --- the facade surface the card is allowed to touch ---
    def get_strength(self):
        return self.strength

    def set_strength(self, value):
        self.strength_calls.append(value)
        self.strength = value

    def is_output_off(self):
        return self.off

    def set_output_off(self, active):
        self.off_calls.append(active)
        self.off = active

    def is_sleep_active(self):
        return self.sleep

    def set_sleep_active(self, active):
        self.sleep_calls.append(active)
        self.sleep = active

    def get_modes_info(self):
        return [
            {"index": 0, "name": "Combined", "icon": "A", "active": True},
            {"index": 1, "name": "Separate", "icon": "B", "active": False},
            {"index": 2, "name": "Custom 1", "icon": "C", "active": False},
            {"index": 3, "name": "Custom 2", "icon": "D", "active": False},
        ]

    def switch_mode(self, index):
        self.switches.append(index)


class _Host(DashboardMixin):
    """Minimal stand-in for OscGoesPurrrUI: just the helpers the sidebar
    block calls.

    `_roots` keeps every built widget tree alive for the test's duration.
    Without it Qt collects the C++ side as soon as the local parent goes
    out of scope and every later access raises — in the real app these
    live in the window's persistent widget tree.
    """

    def __init__(self, controller):
        self.controller = controller
        self._roots = []

    def _explain(self, target, title, body):
        from ui.tooltips import explain
        explain(target, title, body)

    def _muted_label(self, text):
        return QLabel(text)

    def _repolish(self, widget):
        pass

    def build_sidebar_block(self):
        self._roots.append(self._build_mode_grid())
        return self


@pytest.fixture
def host(qapp):
    return _Host(FakeController()).build_sidebar_block()


class TestBuilds:
    def test_block_builds(self, host):
        assert len(host.mode_grid_buttons) == 4
        assert host.sidebar_strength_slider is not None
        assert host.sidebar_off_button.isCheckable()
        assert host.sidebar_sleep_button.isCheckable()

    def test_seeds_from_the_controller(self, host):
        assert host.sidebar_strength_slider.value() == 850
        assert host.sidebar_strength_label.text() == "85%"


class TestLayout:
    """What the sidebar block promises the user: one block of equal
    targets, and a strength bar big enough to grab without aiming."""

    def test_off_and_sleep_are_the_mode_buttons_size(self, host):
        mode_h = {b.height() if b.height() > 0 else b.maximumHeight()
                  for b in host.mode_grid_buttons}
        assert len(mode_h) == 1
        assert host.sidebar_off_button.maximumHeight() ==             host.mode_grid_buttons[0].maximumHeight()
        assert host.sidebar_sleep_button.maximumHeight() ==             host.mode_grid_buttons[0].maximumHeight()

    def test_the_strength_bar_is_labelled_and_tall(self, host):
        from PySide6.QtWidgets import QLabel
        labels = [w.text() for w in host._roots[0].findChildren(QLabel)]
        assert "Total output strength" in labels
        assert host.sidebar_strength_slider.maximumHeight() >= 30


class TestExplanations:
    """Every control in the block explains itself on hover -- the app has
    no separate help mode to switch on."""

    def test_every_control_has_one(self, host):
        for w in (host.mode_grid_buttons
                  + [host.sidebar_strength_slider, host.sidebar_off_button,
                     host.sidebar_sleep_button]):
            assert w.toolTip(), w.text() if hasattr(w, "text") else w

    def test_modes_explain_renaming_and_the_vrchat_parameter(self, host):
        tip = host.mode_grid_buttons[0].toolTip()
        assert "Right-click" in tip and "OGP/Mode" in tip

    def test_a_renamed_mode_retitles_its_tip(self, host):
        infos = host.controller.get_modes_info()
        infos[1]["name"] = "Bedtime"
        host.controller.get_modes_info = lambda: infos
        host._refresh_mode_buttons()
        assert "<b>Bedtime</b>" in host.mode_grid_buttons[1].toolTip()

    def test_off_and_sleep_name_their_vrchat_parameters(self, host):
        assert "OGP/Off" in host.sidebar_off_button.toolTip()
        assert "OGP/Sleep" in host.sidebar_sleep_button.toolTip()


class TestUserInput:
    def test_dragging_the_slider_sets_strength_once(self, host):
        host.sidebar_strength_slider.setValue(400)
        assert host.controller.strength_calls == [0.4]

    def test_buttons_reach_the_controller(self, host):
        host.sidebar_off_button.setChecked(True)
        host.sidebar_sleep_button.setChecked(True)
        assert host.controller.off_calls == [True]
        assert host.controller.sleep_calls == [True]

    def test_mode_buttons_switch(self, host):
        host.mode_grid_buttons[2].click()
        assert host.controller.switches == [2]


class TestRefreshFromController:
    """The VRChat menu path: the controller changes the value, then calls
    refresh_output_controls. It must repaint without calling back — an
    echo here would fight the menu for control of the value."""

    def test_repaints_without_echoing(self, host):
        host.controller.strength = 0.25
        host.controller.off = True
        host.controller.sleep = True
        host.refresh_output_controls()
        assert host.sidebar_strength_slider.value() == 250
        assert host.sidebar_strength_label.text() == "25%"
        assert host.sidebar_off_button.isChecked() is True
        assert host.sidebar_sleep_button.isChecked() is True
        assert host.controller.strength_calls == []
        assert host.controller.off_calls == []
        assert host.controller.sleep_calls == []

    def test_survives_a_controller_without_the_facade(self, qapp):
        # The controller calls this during early startup, before the
        # facade methods (or the widgets) necessarily exist.
        host = _Host(object())
        host.refresh_output_controls()   # must not raise
