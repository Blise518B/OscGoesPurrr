"""The bridge that feeds the SteamVR toy driver (steamvr_toy_bridge.py).

A local TCP server stands in for the driver: the bridge must connect,
say hello, send the full toy list as one line of JSON, and resend it when
the list or a battery changes. Loopback only; no SteamVR needed.
"""

import json
import socket
import threading
import time

import pytest

import steamvr_toy_bridge as bridge_mod
from steamvr_toy_bridge import SteamVRToyBridge, ToyEntry


class _FakeDriver:
    """Accepts one bridge connection and collects the JSON lines it sends."""

    def __init__(self):
        self.srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.srv.bind(("127.0.0.1", 0))
        self.srv.listen(1)
        self.port = self.srv.getsockname()[1]
        self.lines = []
        self._stop = False
        self._t = threading.Thread(target=self._run, daemon=True)
        self._t.start()

    def _run(self):
        self.srv.settimeout(5)
        try:
            conn, _ = self.srv.accept()
        except OSError:
            return
        conn.settimeout(0.2)
        buf = b""
        while not self._stop:
            try:
                chunk = conn.recv(4096)
            except socket.timeout:
                continue
            except OSError:
                break
            if not chunk:
                break
            buf += chunk
            while b"\n" in buf:
                line, buf = buf.split(b"\n", 1)
                self.lines.append(json.loads(line))
        conn.close()

    def wait_for(self, pred, timeout=5.0):
        end = time.time() + timeout
        while time.time() < end:
            for msg in list(self.lines):
                if pred(msg):
                    return msg
            time.sleep(0.02)
        raise AssertionError(f"no matching message; got {self.lines}")

    def close(self):
        self._stop = True
        self.srv.close()


@pytest.fixture
def driver(monkeypatch):
    fake = _FakeDriver()
    monkeypatch.setattr(bridge_mod, "DRIVER_PORT", fake.port)
    yield fake
    fake.close()


def _devices(msg):
    return msg.get("type") == "set_devices"


def test_sends_hello_then_the_toy_list(driver):
    b = SteamVRToyBridge()
    b.RECONNECT_BACKOFF_S = 0.05
    b.set_devices([ToyEntry(serial="OGP_TOY_LOVENSE_GUSH", name="Lovense Gush",
                            icon_key="gush_2", icon_path="{oscgoespurrr}/icons/gush_2.png",
                            battery=0.82)])
    b.start()
    try:
        driver.wait_for(lambda m: m.get("type") == "hello")
        msg = driver.wait_for(_devices)
        assert msg["devices"] == [{
            "serial": "OGP_TOY_LOVENSE_GUSH", "name": "Lovense Gush", "battery": 0.82,
            "icon_key": "gush_2", "icon": "{oscgoespurrr}/icons/gush_2.png",
        }]
    finally:
        b.stop()


def test_battery_change_and_clearing_resend_the_list(driver):
    b = SteamVRToyBridge()
    b.RECONNECT_BACKOFF_S = 0.05
    b.set_devices([ToyEntry(serial="OGP_TOY_HUSH", name="Hush", battery=0.5)])
    b.start()
    try:
        driver.wait_for(_devices)
        b.update_battery("OGP_TOY_HUSH", 0.25)
        driver.wait_for(lambda m: _devices(m) and m["devices"]
                        and m["devices"][0]["battery"] == 0.25)
        b.clear_devices()
        driver.wait_for(lambda m: _devices(m) and m["devices"] == [])
    finally:
        b.stop()


def test_driver_listening_tells_whether_steamvr_has_the_driver(driver, monkeypatch):
    assert bridge_mod.driver_listening() is True
    closed = socket.socket()
    closed.bind(("127.0.0.1", 0))
    port = closed.getsockname()[1]
    closed.close()                       # nothing listens on this port now
    monkeypatch.setattr(bridge_mod, "DRIVER_PORT", port)
    assert bridge_mod.driver_listening() is False


def test_entry_clamps_battery_and_uses_forward_slashes():
    d = ToyEntry(serial="S", name="N", icon_path="C:\\x\\y.png", battery=3.0).to_dict()
    assert d["battery"] == 1.0
    assert d["icon"] == "C:/x/y.png"
    assert "icon_key" not in d
