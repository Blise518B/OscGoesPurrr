# pishock_connection.py
# Swappable-transport seam for PiShock, mirroring intiface_connection.py.
#
# A PiShock can be driven two ways and the user picks one (Settings → PiShock):
#   * serial — USB cable to the PiShock (low latency, local, ms-resolution).
#   * cloud  — pishock.com HTTP API (works anywhere, needs an account + share
#              code + internet; coarse 1-15 s duration, rate-limited).
#
# PiShockEngine never imports `serial` or `requests` directly; it builds a
# provider via make_pishock_connection(mode) and talks to it through the tiny
# PiShockConnection contract below. This keeps the seam (and the op-mapping)
# unit-testable on a box without either library installed, exactly like
# intiface_connection.py avoids importing `buttplug`.

from __future__ import annotations

from typing import Callable, Optional, Protocol, runtime_checkable

# Canonical operation names used throughout the app. Providers map these to
# whatever their transport speaks (serial uses the words; cloud uses ints).
OP_SHOCK = "shock"
OP_VIBRATE = "vibrate"
OP_BEEP = "beep"
VALID_OPS = (OP_SHOCK, OP_VIBRATE, OP_BEEP)

# Cloud HTTP Op integers (legacy apioperate): 0=shock, 1=vibrate, 2=beep.
CLOUD_OP_CODES = {OP_SHOCK: 0, OP_VIBRATE: 1, OP_BEEP: 2}

MODE_SERIAL = "serial"
MODE_CLOUD = "cloud"


@runtime_checkable
class PiShockConnection(Protocol):
    """What PiShockEngine needs from a transport. Both providers satisfy this
    structurally."""

    mode: str

    @property
    def status_label(self) -> str:
        """Human-readable transport name for the UI."""
        ...

    @property
    def is_available(self) -> bool:
        """True if the underlying library is importable / usable."""
        ...

    def configure(self, config: dict) -> None:
        """Update the transport's connection config (port + shocker id for
        serial; credentials + share code for cloud). Cheap; may trigger a
        reconnect on the next prepare()."""
        ...

    def prepare(self) -> bool:
        """Make the transport ready (open the serial port / validate creds).
        Returns True when usable. Must not raise — log and return False."""
        ...

    def operate(self, op: str, intensity: int, duration_ms: int) -> None:
        """Fire ONE discrete event at the configured target. Fire-and-forget:
        never blocks the caller on the wire (cloud POSTs on a worker thread).
        `op` is one of VALID_OPS; `intensity` 0-100; `duration_ms` in ms."""
        ...

    def end(self) -> None:
        """Stop any in-flight operation early (serial 'end'; best-effort/no-op
        on cloud)."""
        ...

    def shutdown(self) -> None:
        """Release the port / stop the worker thread. Idempotent."""
        ...


def make_pishock_connection(
    mode: str, log: Optional[Callable[[str], None]] = None
) -> "PiShockConnection":
    """Build the provider for `mode`. Unknown values fall back to serial so a
    malformed setting can never leave the engine without a transport. Imports
    the concrete providers lazily so this module (and its tests) load even when
    pyserial / requests are absent."""
    if mode == MODE_CLOUD:
        from pishock_cloud import PiShockCloudConnection
        return PiShockCloudConnection(log=log)
    from pishock_serial import PiShockSerialConnection
    return PiShockSerialConnection(log=log)
