"""Tests for the outgoing OSC value coercion and the OGB-parity
presence heartbeat contract (vrchat_osc.coerce_outgoing_value /
OGB_ENABLED_ADDRESS). Pure: no sockets, no zeroconf."""

from vrchat_osc import OGB_ENABLED_ADDRESS, coerce_outgoing_value


class TestCoerceOutgoingValue:
    def test_declared_float_casts(self):
        assert coerce_outgoing_value(1, 'f') == 1.0
        assert isinstance(coerce_outgoing_value(True, 'f'), float)

    def test_declared_int_casts(self):
        assert coerce_outgoing_value(0.9, 'i') == 0

    def test_declared_bool_casts(self):
        assert coerce_outgoing_value(1, 'T') is True
        assert coerce_outgoing_value(0, 'F') is False

    def test_unknown_declared_type_passes_through(self):
        assert coerce_outgoing_value("x", 's') == "x"

    def test_undeclared_bool_stays_bool(self):
        # OGB sends bool params OSC-typed (T/F). isinstance(True, int) is
        # True in Python, so the bare int→float fallback used to degrade
        # an undeclared bool (e.g. the OGB_ENABLED heartbeat before the
        # avatar's OSCQuery tree is fetched) to a 1.0 float.
        v = coerce_outgoing_value(True, None)
        assert v is True
        v = coerce_outgoing_value(False, None)
        assert v is False

    def test_undeclared_int_becomes_float(self):
        v = coerce_outgoing_value(3, None)
        assert v == 3.0 and isinstance(v, float) and not isinstance(v, bool)

    def test_undeclared_float_passes_through(self):
        assert coerce_outgoing_value(0.42, None) == 0.42


class TestOgbEnabledContract:
    def test_address_matches_ogb(self):
        # OscGoesBrrr sends the bare parameter name 'OGB_ENABLED' under
        # /avatar/parameters/ (OscConnection.OGB_ENABLED_PARAM). Avatars
        # gate their haptic senders / visuals on exactly this address.
        assert OGB_ENABLED_ADDRESS == "/avatar/parameters/OGB_ENABLED"
