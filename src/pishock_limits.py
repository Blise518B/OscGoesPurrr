"""The shocker limits in one table: the absolute ceilings no setting can
pass, and every limit's lowest, highest and default value. The engine
clamps to it on every send, the settings store keeps values inside it, and
the Shockers page offers exactly its range -- so the three never disagree.
"""

ABS_MAX_INTENSITY = 100
ABS_MAX_PULSE_MS = 15000
ABS_MIN_COOLDOWN_S = 0.1

# key: (lowest, highest, default)
RANGES = {
    "max_intensity": (1, ABS_MAX_INTENSITY, 30),
    "max_vibrate": (1, ABS_MAX_INTENSITY, 30),      # vibrates' own cap
    "max_pulse_ms": (100, ABS_MAX_PULSE_MS, 1000),
    "cooldown_s": (ABS_MIN_COOLDOWN_S, 3600.0, 0.5),
    "max_hold_s": (1.0, 600.0, 10.0),
    "hold_rest_s": (0.5, 600.0, 2.0),
}
WHOLE = frozenset({"max_intensity", "max_vibrate", "max_pulse_ms"})   # ints, the rest floats
# Each shocker has its own of these (Blise's call, 2026-10-28; a shocker
# without its own takes the hub-wide value); the timing rules are shared.
PER_SHOCKER = ("max_intensity", "max_vibrate", "max_pulse_ms")
SHARED = ("cooldown_s", "max_hold_s", "hold_rest_s")


def default(key: str):
    return RANGES[key][2]
