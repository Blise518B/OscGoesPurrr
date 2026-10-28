"""The USB transport: the wire format, the info handshake, and that the
hub's secrets (Wi-Fi passwords, MAC, public IP, one-time key) never leave
the module."""

import json
import threading

import pytest

import pishock_serial as ps
from pishock_serial import PiShockSerialLink

RAW_INFO = {
    "version": "3.1.1.231119.1556", "type": 4, "connected": False,
    "clientId": 621, "wifi": "home-net", "server": "eu1.pishock.com",
    "macAddress": "0C:B8:15:AB:CD:EF",
    "shockers": [{"id": 420, "type": 1, "paused": False},
                 {"id": 421, "type": 1, "paused": True}],
    "networks": [{"ssid": "home-net", "password": "hunter2"}],
    "otk": "e71d7b27", "publicIp": "203.0.113.69", "ownerId": 6969,
}


class FakeSerial:
    """Answers {"cmd":"info"} with a TERMINALINFO line, like the hub."""

    def __init__(self, port, baud, timeout=None, write_timeout=None,
                 answer=True, fail_write=False):
        self.port = port
        self.written = []
        self.answer = answer
        self.fail_write = fail_write
        self._lines = [b"boot log line\n"]
        self._cv = threading.Condition()
        self.closed = False

    def write(self, data):
        if self.fail_write:
            raise OSError("device gone")
        self.written.append(data)
        if data == ps.encode_info() and self.answer:
            with self._cv:
                self._lines.append(ps.INFO_PREFIX + json.dumps(RAW_INFO).encode() + b"\n")
                self._cv.notify_all()

    def readline(self):
        with self._cv:
            if not self._lines:
                self._cv.wait(0.02)
            return self._lines.pop(0) if self._lines else b""

    def close(self):
        self.closed = True


def test_operate_line_matches_the_serial_api():
    line = ps.encode_operate(420, "shock", 20, 1000)
    assert line.endswith(b"\n")
    assert json.loads(line) == {"cmd": "operate", "value": {
        "id": 420, "op": "shock", "duration": 1000, "intensity": 20}}


def test_beep_and_end_carry_no_intensity():
    assert "intensity" not in json.loads(ps.encode_operate(1, "beep", 50, 300))["value"]
    assert json.loads(ps.encode_end(7)) == {"cmd": "operate", "value": {
        "id": 7, "op": "end", "duration": 0}}


def test_safe_info_keeps_only_the_shockers_and_firmware():
    info = ps.safe_info(RAW_INFO)
    assert info == {"version": "3.1.1.231119.1556", "type": 4, "shockers": [
        {"id": 420, "paused": False}, {"id": 421, "paused": True}]}
    flat = json.dumps(info)
    for secret in ("hunter2", "home-net", "0C:B8", "203.0.113", "e71d7b27", "6969"):
        assert secret not in flat


def test_safe_info_tolerates_junk():
    assert ps.safe_info("nope")["shockers"] == []
    assert ps.safe_info({"shockers": [{"id": "x"}, 5, {"id": "12"}]})["shockers"] == [
        {"id": 12, "paused": False}]


def test_open_waits_for_the_hub_to_identify_itself():
    got = []
    link = PiShockSerialLink(on_info=got.append, serial_factory=FakeSerial)
    info = link.open("COM7", handshake_timeout_s=2.0)
    try:
        assert [s["id"] for s in info["shockers"]] == [420, 421]
        assert link.is_open and link.port == "COM7"
        assert got and "networks" not in got[0]
        assert link.operate(420, "vibrate", 10, 300)
        assert link._ser.written[-1] == ps.encode_operate(420, "vibrate", 10, 300)
    finally:
        link.close()


def test_a_port_that_never_answers_is_refused_and_closed():
    made = []

    def factory(*a, **k):
        made.append(FakeSerial(*a, answer=False, **k))
        return made[-1]

    link = PiShockSerialLink(serial_factory=factory)
    with pytest.raises(RuntimeError, match="no PiShock"):
        link.open("COM3", handshake_timeout_s=0.3)
    assert made[0].closed
    assert not link.is_open


def test_a_failed_write_reports_the_link_lost():
    lost = []
    link = PiShockSerialLink(on_lost=lost.append, serial_factory=FakeSerial)
    link.open("COM7", handshake_timeout_s=2.0)
    link._ser.fail_write = True
    assert not link.operate(420, "vibrate", 10, 300)
    assert not link.is_open
    assert lost and "write failed" in lost[0]


def test_linux_permission_denied_says_which_group(monkeypatch):
    # A fresh Linux install doesn't put the user in the serial-port group.
    def refused(*a, **k):
        raise PermissionError(13, "Permission denied")

    monkeypatch.setattr(ps.sys, "platform", "linux")
    link = PiShockSerialLink(serial_factory=refused)
    with pytest.raises(RuntimeError, match="dialout"):
        link.open("/dev/ttyUSB0")
