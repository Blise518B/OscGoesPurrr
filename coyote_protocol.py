# coyote_protocol.py
# Pure encoder for the DG-Lab Coyote 3.0 BLE protocol (no I/O, no bleak).
# Isolated so the byte layout is independently unit-testable and any future
# protocol drift touches only this file.
#
# GATT (16-bit UUIDs expand against the BLE base UUID):
#   Service 0x180C  write 0x150A (cmd in, <=20 B)  notify 0x150B (resp, <=20 B)
#   Battery 0x180A  read/notify 0x1500 (1 B)
#
# B0 command (20 bytes, sent ~every 100 ms):
#   [0]      0xB0
#   [1]      seq(4 bits, hi) | modeA(2 bits) | modeB(2 bits)
#   [2]      channel A strength  (0-200)
#   [3]      channel B strength  (0-200)
#   [4:8]    channel A waveform frequency  x4  (10-240)
#   [8:12]   channel A waveform intensity  x4  (0-100)
#   [12:16]  channel B waveform frequency  x4  (10-240)
#   [16:20]  channel B waveform intensity  x4  (0-100)
#
# Strength-interpretation mode (2 bits per channel):
#   0b00 no change · 0b01 relative + · 0b10 relative - · 0b11 absolute set
#
# BF command (7 bytes): soft strength limits + freq/intensity balance. Sent on
# connect from settings so the device enforces a ceiling in hardware.

from typing import List, Sequence

# --- BLE UUIDs (full 128-bit form bleak expects) ---
_BASE = "0000{:04x}-0000-1000-8000-00805f9b34fb"
SERVICE_UUID = _BASE.format(0x180C)
WRITE_UUID = _BASE.format(0x150A)
NOTIFY_UUID = _BASE.format(0x150B)
BATTERY_SERVICE_UUID = _BASE.format(0x180A)
BATTERY_UUID = _BASE.format(0x1500)

# --- Strength modes ---
MODE_NOCHANGE = 0b00
MODE_INC = 0b01
MODE_DEC = 0b10
MODE_ABS = 0b11

# --- Ranges ---
STRENGTH_MAX = 200      # absolute device ceiling for channel strength
FREQ_MIN, FREQ_MAX = 10, 240
INTENSITY_MAX = 100


def _clamp(v: int, lo: int, hi: int) -> int:
    try:
        v = int(round(v))
    except (TypeError, ValueError):
        v = lo
    return max(lo, min(hi, v))


def _four(values: Sequence[int], lo: int, hi: int) -> List[int]:
    """Coerce a sequence into exactly 4 clamped bytes (pad with the last value
    or truncate). A single int broadcasts to all four."""
    if isinstance(values, (int, float)):
        values = [values] * 4
    vals = [int(v) for v in values][:4]
    while len(vals) < 4:
        vals.append(vals[-1] if vals else lo)
    return [_clamp(v, lo, hi) for v in vals]


def encode_b0(seq: int, mode_a: int, mode_b: int,
              strength_a: int, strength_b: int,
              freq_a: Sequence[int], intensity_a: Sequence[int],
              freq_b: Sequence[int], intensity_b: Sequence[int]) -> bytes:
    """Build the 20-byte B0 strength+waveform frame. All inputs are clamped to
    their valid ranges so the device never discards a channel for an
    out-of-range value."""
    seq &= 0x0F
    mode_a &= 0b11
    mode_b &= 0b11
    header = (seq << 4) | (mode_a << 2) | mode_b
    out = bytearray(20)
    out[0] = 0xB0
    out[1] = header
    out[2] = _clamp(strength_a, 0, STRENGTH_MAX)
    out[3] = _clamp(strength_b, 0, STRENGTH_MAX)
    out[4:8] = bytes(_four(freq_a, FREQ_MIN, FREQ_MAX))
    out[8:12] = bytes(_four(intensity_a, 0, INTENSITY_MAX))
    out[12:16] = bytes(_four(freq_b, FREQ_MIN, FREQ_MAX))
    out[16:20] = bytes(_four(intensity_b, 0, INTENSITY_MAX))
    return bytes(out)


def build_b0(seq: int, strength_a: int, strength_b: int,
             wave_a=(100, 100), wave_b=(100, 100),
             mode: int = MODE_ABS) -> bytes:
    """Convenience: absolute-set both channel strengths with a constant
    waveform per channel. `wave_*` is (frequency, intensity), broadcast to all
    four 25 ms sub-frames."""
    fa, ia = wave_a
    fb, ib = wave_b
    return encode_b0(seq, mode, mode, strength_a, strength_b,
                     fa, ia, fb, ib)


def encode_bf(limit_a: int, limit_b: int,
              freq_bal_a: int = 160, freq_bal_b: int = 160,
              intensity_bal_a: int = 0, intensity_bal_b: int = 0) -> bytes:
    """Build the 7-byte BF command: per-channel soft strength limits (0-200)
    plus frequency / intensity balance parameters. Sent on connect so the
    hardware enforces the ceiling even if a B0 asks for more."""
    return bytes([
        0xBF,
        _clamp(limit_a, 0, STRENGTH_MAX),
        _clamp(limit_b, 0, STRENGTH_MAX),
        _clamp(freq_bal_a, 0, 255),
        _clamp(freq_bal_b, 0, 255),
        _clamp(intensity_bal_a, 0, 255),
        _clamp(intensity_bal_b, 0, 255),
    ])


def decode_b1(data: bytes):
    """Parse a B1 notify response → (seq, strength_a, strength_b) or None."""
    if not data or len(data) < 4 or data[0] != 0xB1:
        return None
    return (data[1], data[2], data[3])
