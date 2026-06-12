"""Tests for the Coyote 3.0 BLE protocol encoder (coyote_protocol.py).

Pure byte-layout checks (golden-ish vectors) — no bleak, no hardware. These
pin the 20-byte B0 frame and 7-byte BF frame so any future drift is caught."""

from coyote_protocol import (
    MODE_ABS,
    STRENGTH_MAX,
    build_b0,
    decode_b1,
    encode_b0,
    encode_bf,
)


class TestEncodeB0:
    def test_length_is_20(self):
        assert len(encode_b0(0, MODE_ABS, MODE_ABS, 50, 60, 100, 80, 110, 90)) == 20

    def test_header_byte_is_b0(self):
        assert encode_b0(0, MODE_ABS, MODE_ABS, 0, 0, 10, 0, 10, 0)[0] == 0xB0

    def test_seq_and_modes_packed(self):
        f = encode_b0(5, 0b11, 0b10, 0, 0, 10, 0, 10, 0)
        assert f[1] == (5 << 4) | (0b11 << 2) | 0b10

    def test_strength_bytes(self):
        f = encode_b0(0, MODE_ABS, MODE_ABS, 50, 60, 10, 0, 10, 0)
        assert f[2] == 50 and f[3] == 60

    def test_strength_clamped(self):
        f = encode_b0(0, MODE_ABS, MODE_ABS, 999, 999, 10, 0, 10, 0)
        assert f[2] == STRENGTH_MAX and f[3] == STRENGTH_MAX

    def test_waveform_blocks_broadcast(self):
        f = encode_b0(0, MODE_ABS, MODE_ABS, 0, 0, 100, 80, 120, 90)
        assert list(f[4:8]) == [100, 100, 100, 100]
        assert list(f[8:12]) == [80, 80, 80, 80]
        assert list(f[12:16]) == [120, 120, 120, 120]
        assert list(f[16:20]) == [90, 90, 90, 90]

    def test_freq_clamped(self):
        f = encode_b0(0, MODE_ABS, MODE_ABS, 0, 0, 0, 0, 999, 0)
        assert f[4] == 10        # below min -> 10
        assert f[12] == 240      # above max -> 240

    def test_intensity_clamped(self):
        f = encode_b0(0, MODE_ABS, MODE_ABS, 0, 0, 10, 999, 10, 0)
        assert f[8] == 100

    def test_array_input_uses_four_entries(self):
        f = encode_b0(0, MODE_ABS, MODE_ABS, 0, 0, [10, 20, 30, 40], [1, 2, 3, 4], 10, 0)
        assert list(f[4:8]) == [10, 20, 30, 40]
        assert list(f[8:12]) == [1, 2, 3, 4]


class TestBuildB0:
    def test_absolute_mode_and_values(self):
        f = build_b0(1, 30, 40, wave_a=(100, 50), wave_b=(120, 60))
        assert (f[1] & 0x0F) == 0b1111      # both channels absolute
        assert f[2] == 30 and f[3] == 40
        assert f[4] == 100 and f[8] == 50
        assert f[12] == 120 and f[16] == 60


class TestEncodeBF:
    def test_length_is_7(self):
        assert len(encode_bf(100, 100)) == 7

    def test_header_and_limits(self):
        bf = encode_bf(80, 30)
        assert bf[0] == 0xBF
        assert bf[1] == 80 and bf[2] == 30

    def test_limits_clamped(self):
        bf = encode_bf(999, -5)
        assert bf[1] == STRENGTH_MAX and bf[2] == 0


class TestDecodeB1:
    def test_valid(self):
        assert decode_b1(bytes([0xB1, 3, 40, 50])) == (3, 40, 50)

    def test_wrong_header(self):
        assert decode_b1(bytes([0xB0, 0, 0, 0])) is None

    def test_too_short(self):
        assert decode_b1(bytes([0xB1, 1])) is None

    def test_empty(self):
        assert decode_b1(b"") is None
