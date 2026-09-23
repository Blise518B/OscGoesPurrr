# OscGoesPurrr - External Intiface connection provider
"""
The ORIGINAL Buttplug connection path: connect to an Intiface Central (or any
Buttplug websocket server) that the user has started themselves. This module
owns *nothing* about the server's lifecycle — it just hands back the websocket
URL and lets HapticEngine's Buttplug client dial it.

This is the "External" half of the Intiface-mode toggle. The "Integrated" half
(OscGoesPurrr spawns and supervises its own bundled engine) lives in
intiface_integrated.py. Both satisfy the small connection-provider contract
described in intiface_connection.py, so HapticEngine can use either
interchangeably without knowing which one it holds.
"""

from __future__ import annotations

from typing import Callable, Optional

from constants import INTIFACE_WS_URL


class ExternalIntifaceConnection:
    """Connect to a user-run Intiface Central. Stateless and side-effect-free:
    the user is responsible for having the server running, exactly as before
    this toggle existed."""

    mode = "external"

    def __init__(self, log: Optional[Callable[[str], None]] = None) -> None:
        # `log` is accepted for parity with the integrated provider (which has
        # real progress to report). External mode has nothing to announce, so
        # the callback is stored but effectively unused.
        self._log = log if callable(log) else (lambda _m: None)

    @property
    def status_label(self) -> str:
        # Matches the historical connection-status text so the UI reads
        # identically when the user is in external mode.
        return "Intiface"

    async def prepare(self) -> str:
        """Return the websocket URL to dial. No server is started here — if
        Intiface Central isn't running, the Buttplug client's connect() raises
        and the controller's auto-reconnect loop retries, just as it always
        did."""
        return INTIFACE_WS_URL

    async def shutdown(self) -> None:
        """Nothing to tear down — we never owned the server."""
        return None

    def terminate(self) -> None:
        """Sync teardown for the app-quit path. No-op in external mode."""
        return None
