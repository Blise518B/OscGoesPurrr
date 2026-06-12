"""Tests for the PiShock transport seam (pishock_connection + providers).

Hardware-free and library-free: the factory + op-code maps are pure, and the
providers are only driven down paths that don't need pyserial / requests
installed (mirrors test_intiface_connection.py)."""

from pishock_connection import (
    CLOUD_OP_CODES,
    MODE_CLOUD,
    MODE_SERIAL,
    OP_BEEP,
    OP_SHOCK,
    OP_VIBRATE,
    VALID_OPS,
    make_pishock_connection,
)
from pishock_cloud import PiShockCloudConnection
from pishock_serial import PiShockSerialConnection


class TestFactory:
    def test_serial_selected(self):
        c = make_pishock_connection(MODE_SERIAL)
        assert isinstance(c, PiShockSerialConnection)
        assert c.mode == MODE_SERIAL

    def test_cloud_selected(self):
        c = make_pishock_connection(MODE_CLOUD)
        assert isinstance(c, PiShockCloudConnection)
        assert c.mode == MODE_CLOUD

    def test_unknown_defaults_serial(self):
        # A malformed setting must never leave the engine without a transport.
        assert isinstance(make_pishock_connection("garbage"), PiShockSerialConnection)


class TestOpCodes:
    def test_cloud_codes(self):
        assert CLOUD_OP_CODES[OP_SHOCK] == 0
        assert CLOUD_OP_CODES[OP_VIBRATE] == 1
        assert CLOUD_OP_CODES[OP_BEEP] == 2

    def test_valid_ops(self):
        assert set(VALID_OPS) == {"shock", "vibrate", "beep"}


class TestSerialProvider:
    def test_status_label(self):
        assert "serial" in make_pishock_connection(MODE_SERIAL).status_label.lower()

    def test_prepare_without_port_is_false(self):
        c = make_pishock_connection(MODE_SERIAL)
        c.configure({"serial_port": "", "shocker_id": 1})
        # No port (or pyserial missing) -> not ready, never raises.
        assert c.prepare() is False

    def test_operate_without_open_is_silent(self):
        c = make_pishock_connection(MODE_SERIAL)
        c.configure({"serial_port": "", "shocker_id": 1})
        c.operate("shock", 10, 300)  # no port open -> no-op, no raise
        c.end()
        c.shutdown()


class TestCloudProvider:
    def test_status_label(self):
        assert "cloud" in make_pishock_connection(MODE_CLOUD).status_label.lower()

    def test_prepare_without_creds_is_false(self):
        c = make_pishock_connection(MODE_CLOUD)
        c.configure({"username": "", "apikey": "", "code": ""})
        assert c.prepare() is False
