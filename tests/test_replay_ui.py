"""Widget tests for the session-replay UI (the Replay card in the Sessions
panel) — combo population, Play/Stop wiring, and refresh_replay_status
driving the status line / progress bar / button state / global banner.

Runs headless against a real QApplication (same pattern as
test_backend_views_common). The panel is built against a duck-typed fake
controller implementing the replay + session-logger facade surface; the
UI helper methods the panel borrows from its sibling mixins
(`_muted_label`, `_make_help_badge`, `set_replay_banner`, `log_message`)
are stubbed on the host.
"""

import sys

import pytest

from PySide6.QtWidgets import QApplication, QVBoxLayout, QWidget, QLabel

from ui.views.sessions import SessionsMixin, _fmt_ms


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication(sys.argv[:1])


class FakeController:
    """Replay + session-logger facade surface the Sessions panel calls."""

    def __init__(self):
        self.sessions = [
            {"id": "session_2026-07-12_14-00-00",
             "started_at_unix": 1752328800.0, "duration_s": 90,
             "event_count": 1000, "size_bytes": 2048},
            {"id": "session_2026-07-11_09-30-00",
             "mtime_unix": 1752226200.0, "size_bytes": 512},
        ]
        self.replay = {"active": False, "session_id": "",
                       "position_ms": 0.0, "duration_ms": 0.0, "speed": 1.0}
        self.start_calls = []
        self.stop_calls = 0

    # --- session-logger surface (used while building the panel) ---
    def get_session_logging_status(self):
        return {"settings": {"enabled": True, "auto_start": False,
                             "retention": 20},
                "active": None, "sessions_dir": "C:/tmp/sessions"}

    def list_logged_sessions(self):
        return [dict(s) for s in self.sessions]

    # --- replay facade surface ---
    def get_replay_status(self):
        return dict(self.replay)

    def start_replay(self, session_id, speed=1.0):
        self.start_calls.append((session_id, speed))
        return True

    def stop_replay(self):
        self.stop_calls += 1


class HostUI(SessionsMixin):
    """Minimal composed-UI stand-in: SessionsMixin plus the helper methods
    it borrows from sibling mixins in the real OscGoesPurrrUI."""

    def __init__(self, controller, window):
        self.controller = controller
        self.window = window
        self.logs = []
        self.banner = None  # (active: bool, text: str)

    def _muted_label(self, text):
        return QLabel(text)

    def _make_help_badge(self, title, text):
        return QLabel("?")

    def log_message(self, msg):
        self.logs.append(msg)

    def set_replay_banner(self, active, text=""):
        self.banner = (bool(active), text)


def _build(controller):
    window = QWidget()
    host = HostUI(controller, window)
    page = QWidget()
    # Keep the page (and thus its child widgets) alive for the test — in
    # the real app the QStackedWidget owns it.
    host._page = page
    lay = QVBoxLayout(page)
    host._build_sessions_panel(lay)
    return host


# ============================================================ helpers

def test_fmt_ms_minutes_seconds():
    assert _fmt_ms(0) == "0:00"
    assert _fmt_ms(12000) == "0:12"
    assert _fmt_ms(90000) == "1:30"
    assert _fmt_ms(None) == "0:00"


# ============================================================ combo

class TestReplayComboPopulates:
    def test_combo_lists_sessions_with_id_in_itemdata(self, qapp):
        host = _build(FakeController())
        combo = host.replay_session_combo
        assert combo.count() == 2
        ids = [combo.itemData(i) for i in range(combo.count())]
        assert ids == ["session_2026-07-12_14-00-00",
                       "session_2026-07-11_09-30-00"]
        # Labels carry a human date + the id.
        assert "session_2026-07-12_14-00-00" in combo.itemText(0)

    def test_empty_list_disables_combo(self, qapp):
        ctrl = FakeController()
        ctrl.sessions = []
        host = _build(ctrl)
        combo = host.replay_session_combo
        assert combo.count() == 1
        assert combo.itemData(0) is None
        assert not combo.isEnabled()

    def test_refresh_button_repopulates(self, qapp):
        ctrl = FakeController()
        host = _build(ctrl)
        ctrl.sessions.append(
            {"id": "session_new", "mtime_unix": 1752400000.0})
        host._repopulate_replay_sessions()
        ids = [host.replay_session_combo.itemData(i)
               for i in range(host.replay_session_combo.count())]
        assert "session_new" in ids


# ============================================================ play / stop

class TestReplayPlayStop:
    def test_play_calls_start_replay_with_selected_id_and_speed(self, qapp):
        ctrl = FakeController()
        host = _build(ctrl)
        host.replay_session_combo.setCurrentIndex(0)
        # 0.5×=0, 1×=1, 2×=2, 4×=3 — pick 2×.
        host.replay_speed_combo.setCurrentIndex(2)
        host._on_replay_play()
        assert ctrl.start_calls == [("session_2026-07-12_14-00-00", 2.0)]

    def test_play_with_no_selection_is_noop(self, qapp):
        ctrl = FakeController()
        ctrl.sessions = []
        host = _build(ctrl)
        host._on_replay_play()
        assert ctrl.start_calls == []

    def test_stop_calls_stop_replay(self, qapp):
        ctrl = FakeController()
        host = _build(ctrl)
        host._on_replay_stop()
        assert ctrl.stop_calls == 1


# ============================================================ status refresh

class TestRefreshReplayStatus:
    def test_active_shows_banner_enables_stop_disables_play(self, qapp):
        ctrl = FakeController()
        host = _build(ctrl)
        ctrl.replay = {"active": True,
                       "session_id": "session_2026-07-12_14-00-00",
                       "position_ms": 12000, "duration_ms": 90000,
                       "speed": 2.0}
        host.refresh_replay_status()

        assert host.banner == (True, "▶ REPLAY — live OSC paused")
        assert host.replay_stop_btn.isEnabled()
        assert not host.replay_play_btn.isEnabled()
        assert host.replay_status_label.text() == (
            "▶ Replaying session_2026-07-12_14-00-00 — 0:12 / 1:30 (2×)")
        # Progress bar shown, position/duration → 12000/90000 * 1000.
        assert not host.replay_progress.isHidden()
        assert host.replay_progress.value() == 133

    def test_inactive_hides_banner_and_progress(self, qapp):
        ctrl = FakeController()
        host = _build(ctrl)
        # Flip active on then back off to prove the toggle both ways.
        ctrl.replay = {"active": True, "session_id": "s",
                       "position_ms": 1000, "duration_ms": 2000,
                       "speed": 1.0}
        host.refresh_replay_status()
        ctrl.replay = {"active": False, "session_id": "",
                       "position_ms": 0.0, "duration_ms": 0.0, "speed": 1.0}
        host.refresh_replay_status()

        assert host.banner == (False, "")
        assert host.replay_status_label.text() == "Not replaying"
        assert host.replay_progress.isHidden()
        assert not host.replay_stop_btn.isEnabled()
        # A session is selected, so Play is enabled when idle.
        assert host.replay_play_btn.isEnabled()

    def test_refresh_before_card_built_is_safe(self, qapp):
        # Fully getattr-guarded: refresh_replay_status must no-op if the
        # Sessions tab hasn't been built yet (early startup).
        host = HostUI(FakeController(), QWidget())
        host.refresh_replay_status()  # must not raise
