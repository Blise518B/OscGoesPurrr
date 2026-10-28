"""OpenShock firmware on the hub link: the rftransmit line, the page's
shocker list, and telling the two firmwares apart at the handshake —
including not mistaking a PiShock that logs a "Version:" line for one."""

import json
import threading

import pytest

import openshock_serial as osfw
import pishock_serial as ps
from pishock_serial import PiShockSerialLink

VERSION_BLOCK = [b"\r\n", b"  Version:  1.5.2\r\n", b"    Build:  release\r\n",
                 b"   Commit:  abc1234\r\n", b"    Board:  Pishock-2023\r\n",
                 b"     Chip:  ESP32\r\n"]


class FakeOpenShock:
    """Answers like OpenShock firmware: an error for PiShock's info question,
    the version block for $version, a reply for every rftransmit."""

    def __init__(self, port, baud, timeout=None, write_timeout=None,
                 banner=False, answer=True, estop=False):
        self.port = port
        self.written = []
        self.answer = answer
        self.estop = estop
        self._lines = [b"[I] booting\r\n"]
        if banner:
            self._lines += [b"============== OPENSHOCK ==============\r\n"] + VERSION_BLOCK
        self._cv = threading.Condition()

    def write(self, data):
        self.written.append(data)
        out = []
        if data == ps.encode_info():
            out = [b'$SYS$|Error|Command "{"cmd":" not found\r\n']
        elif data == osfw.encode_version():
            out = VERSION_BLOCK
        elif data.startswith(b"$rftransmit"):
            out = [b"$SYS$|Error|Failed to send command\r\n" if self.estop
                   else b"$SYS$|Success|Command sent\r\n"]
        if self.answer:
            with self._cv:
                self._lines += out
                self._cv.notify_all()

    def readline(self):
        with self._cv:
            if not self._lines:
                self._cv.wait(0.02)
            return self._lines.pop(0) if self._lines else b""

    def close(self):
        pass


SHOCKERS = [{"id": 4321, "model": "caixianlin", "name": "Neck"},
            {"id": 77, "model": "petrainer998dr", "name": ""}]


def _open(factory=FakeOpenShock, **kw):
    link = PiShockSerialLink(serial_factory=factory, **kw)
    link.set_openshock_shockers(SHOCKERS)
    return link, link.open("COM5", handshake_timeout_s=2.0)


def test_rftransmit_line_matches_the_firmware():
    line = osfw.encode_rftransmit("caixianlin", 4321, "shock", 40, 300)
    assert line.startswith(b"$rftransmit ") and line.endswith(b"\n")
    assert json.loads(line[len(b"$rftransmit "):]) == {
        "model": "caixianlin", "id": 4321, "type": "shock",
        "intensity": 40, "durationMs": 300}


def test_beep_is_a_sound_without_strength_and_end_is_stop():
    beep = json.loads(osfw.encode_rftransmit("petrainer", 9, "beep", 50, 300)[12:])
    assert (beep["type"], beep["intensity"]) == ("sound", 0)
    stop = json.loads(osfw.encode_stop("caixianlin", 9)[12:])
    assert (stop["type"], stop["intensity"], stop["durationMs"]) == ("stop", 0, 0)


def test_values_are_kept_inside_the_firmwares_ranges():
    v = json.loads(osfw.encode_rftransmit("caixianlin", 99999, "vibrate", 500, 10 ** 6)[12:])
    assert (v["id"], v["intensity"], v["durationMs"]) == (65535, 100, 65535)


def test_the_shocker_list_is_cleaned():
    cleaned = osfw.clean_shockers([
        {"id": "12", "model": "nope", "name": " A "},
        {"id": 12, "model": "petrainer"},          # same id again: dropped
        {"id": 70000}, {"id": "x"}, "junk",
        {"id": 5, "model": "d80"},
    ])
    assert cleaned == [{"id": 12, "model": "caixianlin", "name": "A"},
                       {"id": 5, "model": "d80", "name": ""}]
    assert osfw.clean_shockers("broken") == []


def test_an_openshock_hub_is_recognised_and_driven():
    got = []
    link, info = _open(on_info=got.append)
    try:
        assert link.kind == ps.OPENSHOCK
        assert info["version"] == "1.5.2"
        assert [s["id"] for s in info["shockers"]] == [4321, 77]
        assert link.operate(4321, "vibrate", 25, 300)
        assert link._ser.written[-1] == osfw.encode_rftransmit(
            "caixianlin", 4321, "vibrate", 25, 300)
        assert link.end(77)
        assert link._ser.written[-1] == osfw.encode_stop("petrainer998dr", 77)
    finally:
        link.close()


def test_a_shocker_not_on_the_list_gets_nothing():
    link, _info = _open()
    try:
        before = len(link._ser.written)
        assert not link.operate(999, "vibrate", 25, 300)
        assert not link.end(999)
        assert len(link._ser.written) == before
    finally:
        link.close()


def test_the_boot_banner_alone_identifies_it():
    def factory(*a, **k):
        return FakeOpenShock(*a, banner=True, answer=False, **k)

    link, info = _open(factory)
    try:
        assert link.kind == ps.OPENSHOCK and info["version"] == "1.5.2"
    finally:
        link.close()


def test_the_board_name_arrives_and_list_edits_reach_the_engine():
    got = []
    link, _info = _open(on_info=got.append)
    try:
        deadline = threading.Event()
        for _ in range(50):
            if link.info.get("board"):
                break
            deadline.wait(0.02)
        assert link.info["board"] == "Pishock-2023"
        link.set_openshock_shockers(SHOCKERS[:1])
        assert [s["id"] for s in got[-1]["shockers"]] == [4321]
        assert not link.operate(77, "vibrate", 25, 300)
    finally:
        link.close()


def test_a_refused_command_is_reported():
    errors = []

    def factory(*a, **k):
        return FakeOpenShock(*a, estop=True, **k)

    link, _info = _open(factory, on_error=errors.append)
    try:
        link.operate(4321, "vibrate", 25, 300)
        for _ in range(50):
            if errors:
                break
            threading.Event().wait(0.02)
        assert errors == ["Failed to send command"]
    finally:
        link.close()


class PiShockThatLogsAVersion:
    """A port that prints a "Version:" line but nothing only OpenShock says."""

    def __init__(self, *a, **k):
        self._lines = [b"Version: 3.1.1\r\n"]

    def write(self, data):
        pass

    def readline(self):
        threading.Event().wait(0.01)
        return self._lines.pop(0) if self._lines else b""

    def close(self):
        pass


def test_a_version_line_alone_is_not_openshock():
    link = PiShockSerialLink(serial_factory=PiShockThatLogsAVersion)
    with pytest.raises(RuntimeError, match="no PiShock or OpenShock"):
        link.open("COM3", handshake_timeout_s=0.3)
    assert link.kind == ""


def test_only_firmware_1_4_and_later_gets_the_dollar_prefix():
    assert osfw.supports_automated("1.4.0")
    assert osfw.supports_automated("1.6.0-rc.1")
    assert osfw.supports_automated("v2.0.0")
    assert not osfw.supports_automated("1.3.0")
    assert not osfw.supports_automated("1.1.2")
    assert not osfw.supports_automated("")
    assert not osfw.supports_automated("dev")
    plain = osfw.encode_rftransmit("caixianlin", 1, "vibrate", 5, 300, automated=False)
    assert plain.startswith(b"rftransmit {")
    assert osfw.encode_stop("caixianlin", 1, automated=False).startswith(b"rftransmit {")
    assert osfw.encode_version() == b"version\n"


class FakeOldOpenShock(FakeOpenShock):
    """Firmware 1.3.0: no "$" prefix — "$rftransmit" is an unknown command."""

    def write(self, data):
        self.written.append(data)
        if data == osfw.encode_version():
            out = [b"  Version:  1.3.0\n", b"    Board:  Wemos-D1-Mini-ESP32\n"]
        elif data.startswith(b"rftransmit "):
            out = [b"$SYS$|Success|Command sent\n"]
        else:
            name = data.split(b" ", 1)[0].strip()
            out = [b'$SYS$|Error|Command "' + name + b'" not found\n']
        with self._cv:
            self._lines += out
            self._cv.notify_all()


def test_old_firmware_gets_plain_lines():
    errors = []
    link, info = _open(FakeOldOpenShock, on_error=errors.append)
    try:
        assert link.kind == ps.OPENSHOCK and info["version"] == "1.3.0"
        assert link.operate(4321, "vibrate", 25, 300)
        assert link._ser.written[-1] == osfw.encode_rftransmit(
            "caixianlin", 4321, "vibrate", 25, 300, automated=False)
        assert link.end(4321)
        assert link._ser.written[-1].startswith(b"rftransmit {")
        threading.Event().wait(0.1)
        assert errors == []
    finally:
        link.close()


def test_a_port_another_program_holds_says_so_on_windows(monkeypatch):
    # pyserial on Windows: SerialException("could not open port 'COM5':
    # PermissionError(13, 'Access is denied.', None, 5)"), no errno.
    def busy(*a, **k):
        raise OSError("could not open port 'COM5': PermissionError(13, "
                      "'Access is denied.', None, 5)")

    monkeypatch.setattr(ps.sys, "platform", "win32")
    link = PiShockSerialLink(serial_factory=busy)
    with pytest.raises(RuntimeError, match="in use by another program"):
        link.open("COM5")
