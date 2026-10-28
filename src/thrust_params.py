"""Thrust counters for the avatar — the pure part.

Three counters can go out as avatar parameters (Settings → Connection
Settings → "Send thrust counters to VRChat"), for a counter display on an
avatar or a prop:

* ``OGP/Thrusts/Total``   — every thrust on record (Statistics' lifetime)
* ``OGP/Thrusts/Session`` — this session's, i.e. this app run's
* ``OGP/Thrusts/PerMin``  — thrusts in the last 60 seconds: the live pace

An avatar Int holds 0..255, so each counter goes out twice over: the plain
number (stops at 255 — enough for "more than X" in an animator) and its
digits, one Int 0..9 per place, ``/D1`` the ones, ``/D2`` the tens and so
on, the way heart-rate OSC apps feed digit displays. A number with more
digits than its counter has places shows all nines.

The numbers are the Statistics page's: what passed the activity gate
(stats_gate), so lone strokes with nothing touching never count.

Sealed: no Qt, no OSC, no clock reads. The controller
(controllers/thrust_params_facade.py) sends what `counter_values()` returns.
"""

from collections import deque
from typing import Deque, Dict, List, Tuple

PREFIX = "OGP/Thrusts/"

# (name, digit places). Total gets seven: a busy user passes 100,000 in a
# couple of months.
COUNTERS: Tuple[Tuple[str, int], ...] = (
    ("Total", 7),
    ("Session", 5),
    ("PerMin", 3),
)

# The live pace counts the thrusts of the last minute.
PACE_WINDOW_S = 60.0

# Largest value an avatar Int parameter holds.
INT_MAX = 255


def digits(value: int, places: int) -> List[int]:
    """`value`'s decimal digits, ones first, `places` of them. Negative
    reads as 0; too many digits reads as all nines."""
    n = max(0, int(value))
    cap = 10 ** places - 1
    if n > cap:
        n = cap
    out = []
    for _ in range(places):
        out.append(n % 10)
        n //= 10
    return out


def counter_params(name: str, value: int, places: int) -> Dict[str, int]:
    """One counter's parameters: the plain number and its digits."""
    v = max(0, int(value))
    base = PREFIX + name
    out = {base: min(v, INT_MAX)}
    for i, d in enumerate(digits(v, places), start=1):
        out[f"{base}/D{i}"] = d
    return out


def counter_values(total: int, session: int, per_min: int) -> Dict[str, int]:
    """Every counter parameter (bare names, no /avatar/parameters/) ->
    its Int value."""
    values = {"Total": total, "Session": session, "PerMin": per_min}
    out: Dict[str, int] = {}
    for name, places in COUNTERS:
        out.update(counter_params(name, values[name], places))
    return out


def parameter_names() -> List[str]:
    """Every parameter name the counters use, in display order."""
    return list(counter_values(0, 0, 0))


class PaceWindow:
    """Thrusts over the last `window_s` seconds. Samples carry their own
    epoch: the activity gate releases held-back samples late, and those
    must count at the time they happened, not when they were let through."""

    def __init__(self, window_s: float = PACE_WINDOW_S) -> None:
        self.window_s = float(window_s)
        self._samples: Deque[Tuple[float, int]] = deque()
        self._sum = 0

    def add(self, epoch: float, thrusts: int) -> None:
        n = int(thrusts)
        if n <= 0:
            return
        self._samples.append((float(epoch), n))
        self._sum += n

    def rate(self, now: float) -> int:
        """Thrusts with an epoch inside the last window (forgets older)."""
        edge = float(now) - self.window_s
        samples = self._samples
        # Released samples can arrive out of order by a few seconds; a
        # stale one stuck behind a newer one just waits a tick longer.
        while samples and samples[0][0] <= edge:
            self._sum -= samples.popleft()[1]
        return self._sum

    def reset(self) -> None:
        self._samples.clear()
        self._sum = 0
