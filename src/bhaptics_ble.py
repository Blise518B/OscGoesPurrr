# bhaptics_ble.py
# The Bluetooth side of the bHaptics engine: `bleak`, behind a tiny radio /
# link interface so bhaptics_engine.py never imports it and tests can hand
# the engine a fake. Every coroutine here runs on the engine's own asyncio
# thread -- never the Qt GUI thread, where WinRT's apartment rules break
# bleak's callbacks.
#
# The import is guarded: without bleak the Suits page just says so.

from dataclasses import dataclass
from typing import Any, Callable, List, Optional

from bhaptics_models import BATTERY_CHAR, MOTOR_CHAR, NAME_PREFIXES

try:
    from bleak import BleakClient, BleakScanner
    _BLEAK_ERROR = ""
except Exception as e:  # noqa: BLE001 -- any import failure means "no Bluetooth"
    BleakClient = BleakScanner = None  # type: ignore[assignment]
    _BLEAK_ERROR = f"bleak is not installed ({e.__class__.__name__})"

CONNECT_TIMEOUT_S = 15.0


@dataclass
class Found:
    """One advertising bHaptics device from a scan."""
    address: str
    name: str
    handle: Any = None      # the backend's device object; connecting by it is faster


class BleakLink:
    """One connected device."""

    def __init__(self, client, motor_char, battery_char, found: Found):
        self._client = client
        self._motor = motor_char
        self._battery = battery_char
        self.address = found.address
        self.name = found.name

    @property
    def is_connected(self) -> bool:
        try:
            return bool(self._client.is_connected)
        except Exception:  # noqa: BLE001
            return False

    async def write(self, data: bytes) -> None:
        """Fire and forget: write without response, never wait for an ack."""
        await self._client.write_gatt_char(self._motor, data, response=False)

    async def read_battery(self) -> Optional[int]:
        if self._battery is None:
            return None
        data = await self._client.read_gatt_char(self._battery)
        return int(data[0]) if data else None

    async def close(self) -> None:
        try:
            await self._client.disconnect()
        except Exception:  # noqa: BLE001 -- already gone is fine
            pass


class BleakRadio:
    """Scans for bHaptics devices and opens links to them."""

    @property
    def available(self) -> bool:
        return BleakScanner is not None

    @property
    def unavailable_reason(self) -> str:
        return _BLEAK_ERROR

    async def discover(self, timeout: float) -> List[Found]:
        found = await BleakScanner.discover(timeout=timeout, return_adv=True)
        out = []
        for address, (dev, adv) in found.items():
            name = adv.local_name or dev.name or ""
            if name.startswith(NAME_PREFIXES):
                out.append(Found(address, name, dev))
        return out

    async def open(self, found: Found, on_lost: Callable[[], None],
                   motor_char: str = MOTOR_CHAR) -> BleakLink:
        """Connect and find the motor characteristic this model is driven
        through (the Pro / Air have their own, bhaptics_models)."""
        client = BleakClient(found.handle or found.address,
                             disconnected_callback=lambda _c: on_lost(),
                             timeout=CONNECT_TIMEOUT_S)
        await client.connect()
        try:
            motor = client.services.get_characteristic(motor_char)
            if motor is None:
                raise RuntimeError(f"no bHaptics motor characteristic ({motor_char[:8]})")
            battery = client.services.get_characteristic(BATTERY_CHAR)
        except Exception:
            await client.disconnect()
            raise
        return BleakLink(client, motor, battery, found)
