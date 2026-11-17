"""The OSC Inspector's Debug recording card (ui/views/sessions.py): one
button that starts a session with every contact packet and stops it again,
and the controller method behind it."""

import json
import sys

import pytest
from PySide6.QtWidgets import QApplication, QLabel, QWidget

from controllers.sessions_facade import SessionsFacade
from parameter_store import ParameterStore
from session_logger import SessionLogger
from ui.views.sessions import SessionsMixin


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication(sys.argv[:1])


class FakeController:
    def __init__(self):
        self.active = None
        self.raw = False
        self.calls = []

    def get_session_logging_status(self):
        return {"settings": {"enabled": True, "raw_contacts": self.raw},
                "active": self.active, "sessions_dir": "C:/tmp/sessions"}

    def start_debug_recording(self):
        self.calls.append("start")
        self.raw = True
        self.active = {"id": "session_x", "duration_s": 75,
                       "file_size_bytes": 3 * 1024 * 1024}
        return "session_x"

    def stop_session_logging(self):
        self.calls.append("stop")
        self.active = None

    def open_sessions_folder(self):
        self.calls.append("open")
        return True


class HostUI(SessionsMixin):
    def __init__(self, controller, window):
        self.controller = controller
        self.window = window
        self.logs = []

    def _explain(self, target, title, text):
        pass

    def log_message(self, msg):
        self.logs.append(msg)


def _card(qapp):
    ctrl = FakeController()
    host = HostUI(ctrl, QWidget())
    card = host._build_debug_recording_card()
    return ctrl, host, card


def test_starts_and_stops_a_recording(qapp):
    ctrl, host, _card_widget = _card(qapp)
    assert host.debug_rec_btn.text() == "\u25cf Start recording"
    assert host.debug_rec_label.text() == "Not recording"
    host.debug_rec_btn.click()
    assert ctrl.calls == ["start"]
    assert host.debug_rec_btn.text() == "\u25a0 Stop recording"
    assert "1:15" in host.debug_rec_label.text()
    assert "3.0 MB" in host.debug_rec_label.text()
    host.debug_rec_btn.click()
    assert ctrl.calls == ["start", "stop"]
    assert host.debug_rec_btn.text() == "\u25cf Start recording"


def test_a_session_without_contacts_offers_to_add_them(qapp):
    ctrl, host, _ = _card(qapp)
    ctrl.active = {"id": "session_auto", "duration_s": 5, "file_size_bytes": 10}
    host._debug_rec_refresh()
    assert host.debug_rec_btn.text() == "\u25cf Record contacts too"
    host.debug_rec_btn.click()
    assert ctrl.calls == ["start"]          # adds them, doesn't stop it


def test_a_failing_controller_is_logged_not_raised(qapp):
    ctrl, host, _ = _card(qapp)

    def boom():
        raise RuntimeError("disk full")
    ctrl.start_debug_recording = boom
    host.debug_rec_btn.click()
    assert host.logs and "disk full" in host.logs[0]


# ------------------------------------------------------------- facade

class _Host(SessionsFacade):
    def __init__(self):
        self.logs = []

    def log_message(self, msg):
        self.logs.append(msg)


@pytest.fixture
def host(tmp_path, monkeypatch):
    import controllers.sessions_facade as sf
    import settings.sessions as ss
    monkeypatch.setattr(ss, "SESSIONS_SETTINGS_FILE",
                        str(tmp_path / "sessions_settings.json"))
    monkeypatch.setattr(sf, "SESSIONS_DIR", tmp_path / "sessions")
    store = ParameterStore()
    monkeypatch.setattr(sf, "store", store)
    h = _Host()
    h._session_init_components()
    h._session_logger = SessionLogger(tmp_path / "sessions")
    h._store = store
    yield h
    h.stop_session_logging()


def _raw_lines(tmp_path):
    f = next((tmp_path / "sessions").glob("session_*.jsonl"))
    return [json.loads(x) for x in f.read_text(encoding="utf-8").splitlines()
            if '"raw"' in x]


def test_start_debug_recording_switches_everything_on(host, tmp_path):
    sid = host.start_debug_recording()
    assert sid and host.is_session_logging_active()
    s = host.get_session_settings()
    assert s["enabled"] and s["raw_contacts"]
    host._store.update_parameter("OGB/Plug/T/DepthOthers", 0.5)
    host.stop_session_logging()
    assert [x["a"] for x in _raw_lines(tmp_path)] == ["OGB/Plug/T/DepthOthers"]


def test_a_running_session_just_gains_the_contacts(host, tmp_path):
    first = host.start_session_logging()
    host._store.update_parameter("OGB/Plug/T/DepthOthers", 0.1)   # no raw yet
    assert host.start_debug_recording() == first
    host._store.update_parameter("OGB/Plug/T/DepthOthers", 0.2)
    host.stop_session_logging()
    assert [x["v"] for x in _raw_lines(tmp_path)] == [0.2]
