"""An Intiface Central OGP doesn't run itself, on this PC or on a phone on
the same network: the controller's address box and status
(controllers/intiface_facade.py), the hint after a failed connect, and the
Settings card (ui/views/intiface_card.py). No sockets, no zeroconf."""
import sys

import pytest

import intiface_external
from controllers.intiface_facade import IntifaceFacade
from ui.views import intiface_card


@pytest.fixture(autouse=True)
def _short_first_look(monkeypatch):
    monkeypatch.setattr(intiface_external, "_FIRST_LOOK_S", 0.0)


@pytest.fixture(scope="module")
def qapp():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication(sys.argv[:1])


class _Engine:
    is_connected = False

    def __init__(self):
        self.address = None

    def set_intiface_address(self, address):
        self.address = address

    def get_intiface_link_info(self):
        return {"target": "192.168.1.50:12345", "target_name": "Intiface Ab12Cd",
                "found": [{"name": "Intiface Ab12Cd", "host": "192.168.1.50",
                           "port": 12345}]}


class _Host(IntifaceFacade):
    def __init__(self, built_in=False):
        self.settings = {"use_integrated_intiface": built_in}
        self.logs = []
        self.haptic_engine = _Engine()
        self.async_loop = None
        self.auto_connect_enabled = True

    def get_app_setting(self, key, default=None):
        return self.settings.get(key, default)

    def set_app_setting(self, key, value):
        self.settings[key] = value

    def log_message(self, message):
        self.logs.append(message)

    def get_feature_enabled(self, key):
        return True


def test_a_typed_address_is_stored_in_one_form_and_reaches_the_engine():
    host = _Host()
    assert host.set_intiface_address(" 192.168.1.50 ") == (True, "192.168.1.50:12345")
    assert host.settings["intiface_address"] == "192.168.1.50:12345"
    assert host.haptic_engine.address == "192.168.1.50:12345"
    assert host.get_intiface_address() == "192.168.1.50:12345"


def test_empty_means_find_it_by_itself():
    host = _Host()
    host.set_intiface_address("192.168.1.50")
    assert host.set_intiface_address("") == (True, "")
    assert host.haptic_engine.address == ""
    assert any("found by itself" in m for m in host.logs)


def test_a_wrong_address_changes_nothing_and_says_why():
    host = _Host()
    ok, why = host.set_intiface_address("http://192.168.1.50")
    assert not ok and "Not an address" in why
    assert "intiface_address" not in host.settings
    assert host.haptic_engine.address is None


def test_status_carries_the_engine_view_and_the_setting():
    host = _Host()
    host.set_intiface_address("192.168.1.50")
    st = host.get_intiface_link_status()
    assert st["built_in"] is False and st["connected"] is False
    assert st["address"] == "192.168.1.50:12345"
    assert st["target_name"] == "Intiface Ab12Cd"


def test_looking_only_while_ogp_tries_by_itself_for_your_own_intiface():
    host = _Host()
    assert host.get_intiface_link_status()["looking"] is True
    host.auto_connect_enabled = False                  # nothing tries any more
    assert host.get_intiface_link_status()["looking"] is False
    host.auto_connect_enabled = True
    host.haptic_engine.is_connected = True
    assert host.get_intiface_link_status()["looking"] is False
    assert _Host(built_in=True).get_intiface_link_status()["looking"] is False


def test_the_sidebar_section_tells_its_host_about_changes(qapp):
    status = {"built_in": False, "looking": True}
    changes = []
    info = intiface_card.IntifaceSidebarInfo(lambda: dict(status),
                                             on_change=lambda: changes.append(1))
    first = len(changes)
    info.refresh()
    assert len(changes) == first                       # nothing changed
    status["looking"] = False                          # auto connect switched off
    info.refresh()
    assert len(changes) == first + 1


class _Clock:
    def __init__(self):
        self.t = 100.0

    def __call__(self):
        return self.t


def _sidebar(status, applied=None):
    clock = _Clock()

    def set_address(text):
        if applied is not None:
            applied.append(text)
        if "!" in text:
            return False, "Not an address."
        status["address"] = text.strip()
        return True, text.strip()

    info = intiface_card.IntifaceSidebarInfo(lambda: dict(status), set_address=set_address,
                                             clock=clock)
    return info, clock


def test_enter_address_waits_for_the_search_to_have_found_nothing(qapp):
    status = {"built_in": False, "looking": True, "found": []}
    info, clock = _sidebar(status)
    assert info.enter_btn.isHidden()                   # just started looking
    clock.t += intiface_card.ENTER_GRACE_S - 1
    info.refresh()
    assert info.enter_btn.isHidden()
    clock.t += 1
    info.refresh()
    assert not info.enter_btn.isHidden()
    # Something announces itself: nothing to type any more.
    status["found"] = [{"name": "Intiface Pixel", "host": "192.168.1.50", "port": 12345}]
    info.refresh()
    assert info.enter_btn.isHidden()


def test_enter_address_opens_a_box_that_enter_applies_and_esc_closes(qapp):
    from PySide6.QtCore import Qt as _Qt, QEvent
    from PySide6.QtGui import QKeyEvent
    status = {"built_in": False, "looking": True, "address": "192.168.1.5:12345",
              "found": []}
    applied = []
    info, clock = _sidebar(status, applied)
    clock.t += intiface_card.ENTER_GRACE_S
    info.refresh()
    assert not info.enter_btn.isHidden()               # a typed address that doesn't answer
    info.enter_btn.click()
    assert not info.box.isHidden() and info.enter_btn.isHidden()
    assert info.box.text() == "192.168.1.5:12345"      # the one in use, to fix a typo
    info.box.setText("bad!")
    info.box.returnPressed.emit()
    assert not info.box.isHidden() and not info.box_error.isHidden()
    info.box.setText("192.168.1.50")
    info.box.returnPressed.emit()
    assert applied == ["bad!", "192.168.1.50"]
    assert info.box.isHidden()
    assert info.enter_btn.isHidden()                   # the new address gets its grace
    clock.t += intiface_card.ENTER_GRACE_S
    info.refresh()
    info.enter_btn.click()
    info.box.keyPressEvent(QKeyEvent(QEvent.KeyPress, _Qt.Key_Escape, _Qt.NoModifier))
    assert info.box.isHidden() and not info.enter_btn.isHidden()


def test_the_box_goes_once_connected(qapp):
    status = {"built_in": False, "looking": True, "found": []}
    info, clock = _sidebar(status)
    clock.t += intiface_card.ENTER_GRACE_S
    info.refresh()
    info.enter_btn.click()
    status.update(looking=False, connected=True, target="192.168.1.50:12345")
    info.refresh()
    assert info.box.isHidden() and info.enter_btn.isHidden()


def test_a_failed_connect_says_what_to_do_once_per_case():
    host = _Host()
    host.set_intiface_address("192.168.1.50")
    host.logs.clear()
    for _ in range(3):
        host._intiface_failure_hint(ConnectionError("refused"))
    hints = [m for m in host.logs if "Listen on all network interfaces" in m]
    assert len(hints) == 1 and "192.168.1.50:12345" in hints[0]

    class ButtplugHandshakeError(Exception):
        pass

    host._intiface_failure_hint(ButtplugHandshakeError("bad"))
    assert any("older than 3.0" in m for m in host.logs)


def test_an_intiface_older_than_3_is_named_as_such():
    """Blise's iPhone, Intiface Central 2.6.7: the hello times out (a bare
    TimeoutError), then the phone's server refuses. Both mean "too old",
    not "nothing answers"."""
    host = _Host()
    host.set_intiface_address("192.168.1.50")
    host.logs.clear()
    host._intiface_failure_hint(TimeoutError())
    old = [m for m in host.logs if "older than 3.0" in m]
    assert len(old) == 1 and "192.168.1.50:12345" in old[0]
    assert host.get_intiface_link_status()["too_old"] is True
    # its refusals afterwards don't turn it into "nothing answers"
    host._intiface_failure_hint(ConnectionRefusedError("refused"))
    assert not any("Nothing answers" in m for m in host.logs)
    assert host.get_intiface_link_status()["too_old"] is True
    # a new address starts over
    host.set_intiface_address("192.168.1.60")
    assert host.get_intiface_link_status()["too_old"] is False


def test_too_old_is_only_for_a_hello_that_went_wrong():
    from controllers.intiface_facade import IntifaceFacade as F
    assert F._intiface_too_old(TimeoutError())
    assert not F._intiface_too_old(ConnectionRefusedError("refused"))

    class ButtplugConnectorError(Exception):
        pass

    # a websocket that never opened is the connector's error, not a timeout
    assert not F._intiface_too_old(ButtplugConnectorError(
        "Failed to connect to ws://x: timed out during opening handshake"))


def test_too_old_reads_in_the_sidebar_and_on_the_card():
    st = {"built_in": False, "connected": False, "too_old": True, "looking": True,
          "address": "192.168.1.50:12345", "target": "192.168.1.50:12345", "found": []}
    address, text, accent = intiface_card.sidebar_lines(st)
    assert address == "192.168.1.50:12345" and "too old" in text and accent == "warn"
    text, role = intiface_card.status_text(st)
    assert "older than 3.0" in text and role == "warning"


def test_no_hint_while_the_built_in_engine_is_used():
    host = _Host(built_in=True)
    host._intiface_failure_hint(ConnectionError("refused"))
    assert host.logs == []


def test_status_lines():
    text, role = intiface_card.status_text(
        {"connected": True, "target": "192.168.1.50:12345", "target_name": "Intiface Ab"})
    assert role == "success" and text == "✓ Connected to Intiface Ab at 192.168.1.50:12345"
    text, role = intiface_card.status_text({"connected": True, "target": "127.0.0.1:12345",
                                            "target_local": True})
    assert "this PC" in text
    text, role = intiface_card.status_text({"address": "192.168.1.50:12345"})
    assert role == "" and "Trying 192.168.1.50:12345" in text
    text, _ = intiface_card.status_text(
        {"found": [{"name": "Intiface Ab", "host": "192.168.1.50", "port": 12345}]})
    assert "Found Intiface Ab at 192.168.1.50:12345" in text
    text, _ = intiface_card.status_text({})
    assert "Looking" in text


def test_the_card_shows_the_address_box_only_off_the_built_in_engine(qapp):
    status = {"built_in": True, "address": "", "found": []}
    calls = []

    def set_built_in(on):
        calls.append(("built_in", on))
        status["built_in"] = on

    def set_address(text):
        calls.append(("address", text))
        if "!" in text:
            return False, "That isn't an address."
        status["address"] = "192.168.1.50:12345"
        return True, "192.168.1.50:12345"

    explained = []
    card = intiface_card.IntifaceEngineCard(
        lambda: status, set_built_in, set_address, lambda w, t, x: explained.append(t))
    assert "Where Intiface runs" in explained
    assert card.toggle.isChecked() and card.external.isHidden()
    card.toggle.setChecked(False)
    assert ("built_in", False) in calls and not card.external.isHidden()
    assert "Listen on all network interfaces" in card.phone.text()
    assert "Looking" in card.state_label.text()

    card.address_edit.setText("192.168.1.50")
    card._on_address()
    assert card.address_edit.text() == "192.168.1.50:12345"
    assert card.error.isHidden()

    card.address_edit.setText("bad!")
    card._on_address()
    assert not card.error.isHidden() and "isn't an address" in card.error.text()


def test_sidebar_lines_show_the_address_and_what_is_there():
    assert intiface_card.sidebar_lines({"built_in": True}) is None
    off = {"built_in": False}
    assert intiface_card.sidebar_lines(dict(off, connected=True, target="192.168.1.50:12345",
                                            target_name="Intiface Pixel")) == (
        "192.168.1.50:12345", "✓ Intiface Pixel found", "ok")
    assert intiface_card.sidebar_lines(dict(off, connected=True, target="127.0.0.1:12345",
                                            target_local=True)) == (
        "127.0.0.1:12345", "✓ Intiface on this PC", "ok")
    # a typed address is only found once it answers
    assert intiface_card.sidebar_lines(dict(off, address="192.168.1.50:12345")) == (
        "192.168.1.50:12345", "No Intiface found there yet", "warn")
    found = [{"name": "Intiface Pixel", "host": "192.168.1.50", "port": 12345}]
    assert intiface_card.sidebar_lines(dict(off, found=found)) == (
        "192.168.1.50:12345", "✓ Intiface Pixel found, connecting…", "ok")
    address, text, accent = intiface_card.sidebar_lines(dict(off))
    assert address == "" and "Looking" in text and accent == ""


def test_the_sidebar_section_only_shows_off_the_built_in_engine(qapp):
    status = {"built_in": True}
    clicks = []
    info = intiface_card.IntifaceSidebarInfo(lambda: status, lambda: clicks.append(1))
    assert info.isHidden()
    status.update(built_in=False, address="192.168.1.50:12345")
    info.refresh()
    assert not info.isHidden()
    assert info.address.text() == "192.168.1.50:12345"
    assert info.found.text() == "No Intiface found there yet"
    assert info.found.property("accent") == "warn"
    status.update(connected=True, target="192.168.1.50:12345", target_name="Intiface Pixel")
    info.refresh()
    assert info.found.text() == "✓ Intiface Pixel found"
    assert info.found.property("accent") == "ok"
    from PySide6.QtCore import QPointF, Qt as _Qt, QEvent
    from PySide6.QtGui import QMouseEvent
    info.mouseReleaseEvent(QMouseEvent(QEvent.MouseButtonRelease, QPointF(3, 3), QPointF(3, 3),
                                       _Qt.LeftButton, _Qt.NoButton, _Qt.NoModifier))
    assert clicks == [1]
    status["built_in"] = True
    info.refresh()
    assert info.isHidden()


def test_a_card_whose_controller_cant_answer_still_builds(qapp):
    def broken():
        raise RuntimeError("no controller")
    card = intiface_card.IntifaceEngineCard(broken, lambda on: None,
                                            lambda t: (True, t))
    assert card.toggle.isChecked()          # built-in, the default
