"""Which shocker buttons your Friends panel shows: PiShock's own panel or
OpenShock's (Blise's call, 2026-11-15: "By default, it should be the
PiShock layout, but if you want to change it, you can put it into the
OpenShock layout").

One app setting (`SETTING_KEY` in app_settings.json) for every panel at
once -- a friend's, your own Me row's, a group's -- and a layout is only a
face: both cards send the very same messages for the same press, over the
friend path, and the receiver's PiShockEngine stays the last gate (caps,
arming, the share, each shocker's switches, warn-first, the longest hold
and the rest). The web remote has the same switch, remembered in the
browser (docs/assets/remote-proto.js mirrors this module, and
tests/test_web_remote.py holds the two together).

OpenShock's numbers below are its web app's (OpenShock/Frontend, the
Classic control module and Live control, AGPL-3.0 -- read for its names,
order and behaviour only, none of its code is used): one Intensity
(default 25) and one Duration (0.3 s to 30 s in tenths, default 1 s) for
Sound, Vibrate and Shock, in that order; Live control picks one of the
three and follows a finger on a pad, top = their strongest. Here the top
of everything is the RECEIVER's own caps, so the Duration stops at their
longest pulse."""

import math
from typing import Any, Tuple

from remote_protocol import SHOCK_MIN_MS

SETTING_KEY = "shocker_layout"
PISHOCK = "pishock"
OPENSHOCK = "openshock"
LAYOUTS = (PISHOCK, OPENSHOCK)
NAMES = {PISHOCK: "PiShock", OPENSHOCK: "OpenShock"}
DEFAULT = PISHOCK

# OpenShock's control numbers (ControlConstants in its web app)
INTENSITY_DEFAULT = 25
DURATION_DEFAULT_MS = 1000
DURATION_MIN_MS = 300
DURATION_STEP_MS = 100
# its three buttons, in its order, and their names there
OS_OPS = ("beep", "vibrate", "shock")
OP_NAMES = {"beep": "Sound", "vibrate": "Vibrate", "shock": "Shock"}
LIVE_DEFAULT_OP = "vibrate"            # what Live control starts on, as OpenShock's
LIVE_STEP = 0.05                       # an arrow key moves the pad this much


def clean(value: Any) -> str:
    """A stored layout, or the default for anything else."""
    return value if value in LAYOUTS else DEFAULT


def js_round(x: float) -> int:
    """Round half up, as JavaScript's Math.round -- the web remote's copy
    must land on the same numbers."""
    return int(math.floor(x + 0.5))


def to_fraction(strength: int, cap: int) -> float:
    """A strength 1..cap as the 0..1 of the receiver's cap a message
    carries -- the PiShock card's own maths (ShockerCard._to_fraction)."""
    cap = max(1, int(cap))
    return 1.0 if cap <= 1 else max(0.0, (int(strength) - 1) / (cap - 1))


def length_fraction(ms: int, top: int) -> float:
    """A length in ms as the 0..1 of their longest pulse a message carries
    -- the PiShock card's own maths (ShockerCard._length)."""
    top = max(SHOCK_MIN_MS, int(top))
    if top <= SHOCK_MIN_MS:
        return 0.0
    return (min(int(ms), top) - SHOCK_MIN_MS) / (top - SHOCK_MIN_MS)


def duration_range(top: int) -> Tuple[int, int]:
    """(shortest, longest) the Duration dial offers: OpenShock's 0.3 s up
    to their longest pulse -- shorter than 0.3 s, just theirs."""
    hi = max(SHOCK_MIN_MS, int(top))
    return min(DURATION_MIN_MS, hi), hi


def snap_duration(ms: float, top: int) -> int:
    """`ms` on the dial's tenths, inside duration_range."""
    lo, hi = duration_range(top)
    steps = js_round((float(ms) - lo) / DURATION_STEP_MS)
    return max(lo, min(hi, lo + steps * DURATION_STEP_MS))


def live_strength(y: float, cap: int) -> int:
    """Live control: the pad's point, `y` 0 at the top .. 1 at the bottom,
    as a strength 0..cap -- 0 lets go (OpenShock sends an intensity of 0
    there; here nothing is held)."""
    y = max(0.0, min(1.0, float(y)))
    return max(0, min(int(cap), js_round((1.0 - y) * max(0, int(cap)))))
