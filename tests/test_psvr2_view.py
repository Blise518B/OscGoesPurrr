"""Widget tests for the PSVR2 page (ported from the full edition's, on this
edition's cards): it builds against the facade alone, its link pill says
each state, every value is a slider (never a spin box) that reaches the
controller in the right shape, the scroll wheel leaves them alone, and it
sits in the sidebar with the headset's icon behind its feature switch.

Runs headless; the backend itself needs a jailbroken PSVR2, so this is the
one automated check on the Qt wiring."""

import sys

import pytest

from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QWheelEvent
from PySide6.QtWidgets import (
    QAbstractSpinBox, QApplication, QSlider, QVBoxLayout, QWidget,
)

from ui import page_steps
from ui.views.device_frame import DeviceFrameMixin
from ui.views.psvr2 import PSVR2Mixin, link_text


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication(sys.argv[:1])


def _status(**over):
    st = {
        "feature": True, "available": True, "connected": True, "paused": False,
        "last_error": None, "auto_connect": True, "output_off": False,
        "output": {"min_hz": 10.0, "max_hz": 25.0, "max_cmd_hz": 10.0,
                   "keepalive_s": 0.0},
        "contact": {"enabled": True, "parameter": "HapticHead",
                    "threshold": 0.1, "gain": 1.5},
        "extras": {"driver_active": True, "level": 0.0, "rumble_hz": None,
                   "rtt_ms": None, "sends_per_min": 0, "slotless": False,
                   "paused": False, "dll_path": None},
    }
    st.update(over)
    return st


class FakeController:
    def __init__(self, **status):
        self.status = _status(**status)
        self.calls = []
        self.found = True

    def get_psvr2_status(self):
        return dict(self.status)

    def get_psvr2_live(self):
        return {"strength": 0.42, "level": 0.4, "rumble_hz": 16}

    def get_psvr2_contact_found(self):
        return self.found

    def get_device_connected_param(self, slot):
        return (True, f"OGP/{slot}Connected")

    def psvr2_stop_all(self):
        self.calls.append(("psvr2_stop_all",))
        self.status["paused"] = True

    def psvr2_resume(self):
        self.calls.append(("psvr2_resume",))
        self.status["paused"] = False

    def __getattr__(self, name):
        if name.startswith("__"):
            raise AttributeError(name)
        return lambda *a, **k: self.calls.append((name,) + a)


class _Host(PSVR2Mixin, DeviceFrameMixin):
    def __init__(self, controller):
        self.controller = controller
        self.window = QWidget()
        self.views = {}
        self._build_psvr2_view(QVBoxLayout(self.window))

    def _repolish(self, w):
        w.style().unpolish(w)
        w.style().polish(w)


def page(**status):
    return _Host(FakeController(**status))


# --- what the link says --------------------------------------------------------

def test_connected():
    text, tone, _line = link_text(_status())
    assert (text, tone) == ("Connected", "ok")


def test_a_silent_connected_headset_says_why():
    _t, _tone, line = link_text(_status())
    assert "jailbreak" in line


def test_the_driver_round_trip_shows_while_commands_flow():
    st = _status(extras={"rumble_hz": 18, "rtt_ms": 12.4, "sends_per_min": 30,
                         "slotless": True})
    _t, _tone, line = link_text(st)
    assert "Rumbling at 18 Hz" in line and "~12 ms" in line and "slot" in line


def test_no_toolkit():
    text, tone, line = link_text(_status(available=False, connected=False,
                                         last_error="PSVR2Toolkit not detected"))
    assert (text, tone) == ("PSVR2Toolkit not found", "err")
    assert line == "PSVR2Toolkit not detected"


def test_waiting_for_steamvr_or_not_connected():
    assert link_text(_status(connected=False))[:2] == ("Waiting for SteamVR", "run")
    assert link_text(_status(connected=False, auto_connect=False))[:2] == (
        "Not connected", "off")


def test_stopped():
    assert link_text(_status(paused=True))[:2] == ("Stopped", "warn")


# --- the page --------------------------------------------------------------------

def test_it_builds_and_fills_in(qapp):
    h = page()
    assert h._psvr2_pill.text() == "Connected"
    assert h._psvr2_param.text() == "HapticHead"
    assert h._psvr2_min.value() == 10 and h._psvr2_max.value() == 25
    assert h._psvr2_threshold.value() == pytest.approx(0.1)
    assert h._psvr2_gain.value() == pytest.approx(1.5)
    assert h._psvr2_auto.isChecked() and h._psvr2_on.isChecked()
    assert not h._psvr2_connect_btn.isVisibleTo(h.window)     # nothing to do
    assert h._psvr2_check.text() == "On your avatar"


def test_never_a_spin_box(qapp):
    """Values are sliders with the number written out (Blise's rule)."""
    h = page()
    assert not h.window.findChildren(QAbstractSpinBox)
    assert len(h.window.findChildren(QSlider)) == 8      # 6, and its anti-stuck's 2


def test_the_wheel_never_changes_a_setting(qapp):
    from ui.wheel_guard import WheelGuard
    QApplication.instance().installEventFilter(guard := WheelGuard())
    try:
        h = page()
        s = h._psvr2_max.slider
        before = s.value()
        ev = QWheelEvent(QPointF(5, 5), QPointF(5, 5), QPoint(0, 0), QPoint(0, -120),
                         Qt.NoButton, Qt.NoModifier, Qt.NoScrollPhase, False)
        QApplication.sendEvent(s, ev)
        assert s.value() == before
    finally:
        QApplication.instance().removeEventFilter(guard)


def test_a_slider_saves_its_own_key(qapp):
    h = page()
    h._psvr2_max.slider.setValue(h._psvr2_max._to_slider(18))
    h._psvr2_max.flush()
    assert ("set_psvr2_output", {"max_hz": 18.0}) in h.controller.calls
    h._psvr2_gain.slider.setValue(h._psvr2_gain._to_slider(2.0))
    h._psvr2_gain.flush()
    assert ("set_psvr2_contact", {"gain": 2.0}) in h.controller.calls


def test_the_contact_is_saved_bare(qapp):
    h = page()
    h._psvr2_param.setText("/avatar/parameters/Contact/HeadPat")
    h._psvr2_param.editingFinished.emit()
    assert ("set_psvr2_contact", {"parameter": "Contact/HeadPat"}) in h.controller.calls


def test_switches_reach_the_controller(qapp):
    h = page()
    h._psvr2_auto.setChecked(False)
    h._psvr2_on.setChecked(False)
    assert ("set_psvr2_auto_connect", False) in h.controller.calls
    assert ("set_psvr2_contact", {"enabled": False}) in h.controller.calls


def test_refreshing_sends_nothing_back(qapp):
    h = page()
    h.controller.calls.clear()
    h.controller.status["auto_connect"] = False
    h.controller.status["contact"] = dict(h.controller.status["contact"], enabled=False)
    h.refresh_psvr2_status()
    assert [c for c in h.controller.calls if c[0].startswith("set_")] == []


def test_stop_and_resume(qapp):
    h = page()
    h._psvr2_stop_btn.click()
    assert h.controller.calls[-1] == ("psvr2_stop_all",)
    assert h._psvr2_stop_btn.text() == "Resume"
    assert not h._psvr2_test_btn.isEnabled()
    h._psvr2_stop_btn.click()
    assert h.controller.calls[-1] == ("psvr2_resume",)
    assert h._psvr2_stop_btn.text() == "Stop"


def test_feel_it(qapp):
    h = page()
    h._psvr2_test_btn.click()
    assert ("psvr2_test_pulse",) in h.controller.calls


def test_connect_shows_only_while_it_has_something_to_do(qapp):
    h = page(connected=False)
    assert h._psvr2_connect_btn.isVisibleTo(h.window)
    h = page(connected=False, available=False)
    assert not h._psvr2_connect_btn.isVisibleTo(h.window)


def test_the_live_line(qapp):
    h = page()
    h._refresh_psvr2_live()
    assert h._psvr2_live.text() == "Contact 0.42  ·  16 Hz"


def test_the_contact_check(qapp):
    h = page()
    h.controller.found = False
    h.refresh_psvr2_status()
    assert h._psvr2_check.text() == "Not on your avatar"
    h.controller.found = None
    h.refresh_psvr2_status()
    assert h._psvr2_check.isHidden()


def test_the_steps_point_at_its_controls(qapp):
    """Help mode finds each step's control by its explanation's title, so
    every step's target is on the page (the gallery generator stops on a
    missing one)."""
    from ui.help_mode import find_control
    h = page()
    h.window.resize(900, 1200)
    h.window.show()
    try:
        steps = page_steps.for_page("PSVR2")
        assert steps
        for s in steps:
            for t in ((s.target,) if isinstance(s.target, str) else s.target):
                assert find_control([h.window], t) is not None, t
    finally:
        h.window.hide()


# --- in the app ----------------------------------------------------------------

def test_in_the_sidebar_with_the_headsets_icon():
    import inspect
    import ui_components
    from ui.views.dashboard import DashboardMixin
    src = inspect.getsource(ui_components.OscGoesPurrrUI)
    assert '"PSVR2": self._build_psvr2_view' in src
    assert ui_components.OscGoesPurrrUI._NAV_ICONS["PSVR2"] == "psvr2"
    assert "PSVR2" in ui_components.OscGoesPurrrUI._NAV_TIPS
    assert DashboardMixin._FEATURE_VIEW_REQUIREMENTS["PSVR2"] == ("feature_psvr2",)


def test_the_headset_is_an_identity_in_blue(qapp):
    from ui import icons, theme
    assert "psvr2" in icons.ICON_NAMES
    assert icons.IDENTITY_NAMES["psvr2"] == "PSVR2"
    assert icons.identity_color("psvr2") == theme.hue(theme.PSVR2_HUE)
    assert not icons.identity_icon("psvr2", 16).isNull()


def test_the_question_shows_the_headsets_icon():
    from ui.views import interests
    assert interests.FEATURE_ICONS["feature_psvr2"] == "psvr2"


def test_settings_features_wear_their_icons(qapp):
    """Settings → Features: each row has its page's icon, the headset's
    too, from the same map as the first-launch question."""
    from ui.views.interests import FEATURE_ICONS
    from ui.views.settings import SettingsMixin
    from ui.widgets import IdentityMark

    class _Ctl:
        def get_feature_flags(self):
            return {k: False for k in ("feature_intiface", "feature_pishock",
                                       "feature_psvr2", "feature_statistics")}

        def get_feature_enabled(self, key):
            return False

    class _S(SettingsMixin, DeviceFrameMixin):
        def __init__(self):
            self.controller = _Ctl()

        def _repolish(self, w):
            w.style().unpolish(w)
            w.style().polish(w)

    card = _S()._build_features_card()
    marks = sorted(m._what for m in card.findChildren(IdentityMark))
    assert marks == sorted(FEATURE_ICONS[k] for k in
                           ("feature_intiface", "feature_pishock",
                            "feature_psvr2", "feature_statistics"))
