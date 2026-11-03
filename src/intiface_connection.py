# OscGoesPurrr - Intiface connection seam
"""
The seam between HapticEngine and the two interchangeable Buttplug-server
connection strategies:

  * intiface_external.py   — connect to a user-run Intiface Central (the
                             original behavior).
  * intiface_integrated.py — spawn + supervise a bundled intiface-engine so
                             everything lives in one program (the default).

HapticEngine never imports either concrete provider directly; it calls
`make_intiface_connection(mode)` and talks to the result through the tiny
`IntifaceConnection` contract below. Adding a third strategy later means adding
a module + a branch here — no engine surgery (ARCHITECTURE.md: "add files, not
rewrite").

This module deliberately avoids importing `buttplug`, so the providers and
factory stay unit-testable on a CI box without the hardware client installed.
"""

from __future__ import annotations

from typing import Callable, Optional, Protocol, runtime_checkable

from intiface_external import ExternalIntifaceConnection, normalize_address
from intiface_integrated import IntegratedIntifaceConnection

__all__ = ["MODE_INTEGRATED", "MODE_EXTERNAL", "IntifaceConnection",
           "make_intiface_connection", "normalize_address"]

# Valid mode strings, mirrored by the `use_integrated_intiface` app setting.
MODE_INTEGRATED = "integrated"
MODE_EXTERNAL = "external"


@runtime_checkable
class IntifaceConnection(Protocol):
    """What HapticEngine needs from a connection strategy. Both providers
    satisfy this structurally."""

    mode: str

    @property
    def status_label(self) -> str:
        """Human-readable backend name pushed to the UI on connect."""
        ...

    async def prepare(self) -> str:
        """Make the Buttplug server reachable and return the websocket URL to
        dial. May raise if the server can't be provisioned."""
        ...

    async def shutdown(self) -> None:
        """Async teardown of anything this provider owns."""
        ...

    def terminate(self) -> None:
        """Synchronous, immediate teardown for the app-quit path."""
        ...


def make_intiface_connection(
    mode: str, log: Optional[Callable[[str], None]] = None, address: str = ""
) -> IntifaceConnection:
    """Build the provider for `mode`. Unknown values fall back to the default
    (integrated) so a malformed setting can never leave the engine without a
    connection strategy. `address` is where an external Intiface runs ("" =
    find it by itself); the integrated engine is always this PC."""
    if mode == MODE_EXTERNAL:
        return ExternalIntifaceConnection(log=log, address=address)
    return IntegratedIntifaceConnection(log=log)
