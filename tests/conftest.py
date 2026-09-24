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


@pytest.fixture(autouse=True)
def _never_touch_real_appdata(monkeypatch, tmp_path):
    """Point every config path at tmp_path for EVERY test, before any
    test-local fixture gets a say.

    A test that forgets one path constant writes to the user's live
    `%APPDATA%\\OscGoesPurrr` — which has actually happened: renaming the
    live config file left one test module patching only the old constant,
    and a full suite run dropped a fixture device into the real config.
    Tests that need to assert on files still patch their own paths (this
    runs first, so those win); this is the floor, not the mechanism."""
    import config_manager
    for const, name in (("MODES_FILE", "modes.json"),):
        if hasattr(config_manager, const):
            monkeypatch.setattr(config_manager, const, tmp_path / name)
    # The SteamVR toy driver installs under %LOCALAPPDATA% and edits
    # SteamVR's openvrpaths.vrpath there — never the real ones.
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "localappdata"))


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
