"""Pytest fixtures shared across the router test suite.

The big one is `FakeClock`. `MotorRouter._calculate_motor_target` calls
`time.monotonic()` to compute the per-tick dt used by the speed
derivation and the post-mix envelope follower; that makes the timing
math non-deterministic in tests. We inject a clock through
`MotorRouter`'s optional `clock` kwarg so tests can advance time by
exact amounts and assert on the resulting smoothed signal.
"""

from typing import Callable

import pytest

from motor_router import MotorRouter


class FakeClock:
    """An advanceable monotonic clock.

    Use ``clock.now`` (the bound method) as ``MotorRouter(clock=...)`` and
    drive time forward with ``clock.advance(seconds)``.
    """

    def __init__(self, start: float = 0.0) -> None:
        self._t = float(start)

    def now(self) -> float:
        return self._t

    def advance(self, seconds: float) -> None:
        self._t += float(seconds)


@pytest.fixture
def clock() -> FakeClock:
    """A fresh FakeClock starting at t=0."""
    return FakeClock()


@pytest.fixture
def router(clock: FakeClock) -> MotorRouter:
    """A fresh MotorRouter wired to the test clock.

    Use this for any test that exercises router state. Tests that only
    cover pure module-level helpers (e.g. `_classify_zone_path`) don't
    need a router and can skip this fixture.
    """
    return MotorRouter(clock=clock.now)
