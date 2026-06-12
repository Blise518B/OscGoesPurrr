# coyote_engine.py
# Sealed DG-Lab Coyote 3.0 engine: direct BLE via bleak, on the async
# connection base. The hardware wants a B0 strength+waveform frame ~every
# 100 ms; this engine owns that cadence loop and wakes it early on a strength
# change (event-driven) so a contact edge reaches the device with near-zero
# added latency — the 100 ms cadence is the per-feature hardware send cap.
#
# All BLE I/O is isolated here; the 20-byte/7-byte wire encoding lives in the
# pure coyote_protocol module. Imports are guarded so the app (and tests) load
# without bleak installed.

import asyncio
from typing import Callable, List, Optional, Tuple

from engine_base import AsyncReconnectingEngine
from coyote_protocol import (
    BATTERY_UUID, NOTIFY_UUID, STRENGTH_MAX, WRITE_UUID,
    build_b0, decode_b1, encode_bf,
)

try:
    from bleak import BleakClient, BleakScanner
    _BLEAK_AVAILABLE = True
except Exception:
    BleakClient = None  # type: ignore
    BleakScanner = None  # type: ignore
    _BLEAK_AVAILABLE = False

B0_INTERVAL_S = 0.1   # device expects a frame ~every 100 ms


class CoyoteEngine(AsyncReconnectingEngine):
    """Drives a Coyote 3.0 over BLE. Public hot methods (`set_channel_strength`,
    `set_waveform`) are safe to call from the router thread — they update state
    and wake the engine-loop B0 sender via a threadsafe event."""

    def __init__(self, log: Optional[Callable[[str], None]] = None):
        super().__init__("Coyote")
        self._log = log or (lambda _m: None)
        self._device_addr = ""
        self._device_name = ""
        self._limit_a = 100
        self._limit_b = 100
        # Live output state (read by the B0 loop each frame).
        self._strength_a = 0
        self._strength_b = 0
        self._wave_a: Tuple[int, int] = (100, 100)   # (frequency, intensity)
        self._wave_b: Tuple[int, int] = (100, 100)
        self._seq = 0
        self._battery: Optional[int] = None
        self._client = None
        self._b0_task: Optional[asyncio.Task] = None
        self._change_evt: Optional[asyncio.Event] = None

    @property
    def _available(self) -> bool:
        return _BLEAK_AVAILABLE

    @property
    def battery(self) -> Optional[int]:
        return self._battery

    @property
    def strengths(self) -> Tuple[int, int]:
        return (self._strength_a, self._strength_b)

    # ---- config (from the facade/settings) ---------------------------
    def configure(self, *, address: str = "", name: str = "",
                  limit_a: int = 100, limit_b: int = 100,
                  wave_a: Optional[Tuple[int, int]] = None,
                  wave_b: Optional[Tuple[int, int]] = None) -> None:
        addr_changed = (address != self._device_addr) or (name != self._device_name)
        self._device_addr = str(address or "").strip()
        self._device_name = str(name or "").strip()
        self._limit_a = max(0, min(STRENGTH_MAX, int(limit_a)))
        self._limit_b = max(0, min(STRENGTH_MAX, int(limit_b)))
        if wave_a:
            self._wave_a = (int(wave_a[0]), int(wave_a[1]))
        if wave_b:
            self._wave_b = (int(wave_b[0]), int(wave_b[1]))
        # Apply new soft limits live if connected.
        if self._connected:
            self._submit(self._send_bf())
        # Force a reconnect to the new device if the target changed.
        if addr_changed and self._connected:
            self._connected = False

    # ---- hot path (callable from the router thread) ------------------
    def set_channel_strength(self, channel: str, value: int) -> None:
        value = max(0, min(STRENGTH_MAX, int(value)))
        if channel == "A":
            if self._strength_a == value:
                return
            self._strength_a = value
        elif channel == "B":
            if self._strength_b == value:
                return
            self._strength_b = value
        else:
            return
        self._wake()

    def set_waveform(self, channel: str, frequency: int, intensity: int) -> None:
        wave = (int(frequency), int(intensity))
        if channel == "A":
            self._wave_a = wave
        elif channel == "B":
            self._wave_b = wave
        self._wake()

    def set_strength_limits(self, limit_a: int, limit_b: int) -> None:
        self._limit_a = max(0, min(STRENGTH_MAX, int(limit_a)))
        self._limit_b = max(0, min(STRENGTH_MAX, int(limit_b)))
        if self._connected:
            self._submit(self._send_bf())

    def _wake(self) -> None:
        """Threadsafe nudge of the B0 loop so a change is sent immediately
        instead of waiting out the 100 ms cadence."""
        loop = self._loop
        evt = self._change_evt
        if loop is None or evt is None:
            return
        try:
            loop.call_soon_threadsafe(evt.set)
        except Exception:
            pass

    # ---- scanning (UI device picker) ---------------------------------
    def scan_devices(self, timeout: float = 6.0) -> List[Tuple[str, str]]:
        """Blocking BLE scan run on the engine loop. Returns [(name, address)].
        Empty if bleak is missing or the loop isn't running."""
        loop = self._loop
        if loop is None or not _BLEAK_AVAILABLE:
            return []
        try:
            fut = asyncio.run_coroutine_threadsafe(self._scan(timeout), loop)
            return fut.result(timeout=timeout + 4.0)
        except Exception as e:
            self._log(f"Coyote scan failed: {e}")
            return []

    async def _scan(self, timeout: float) -> List[Tuple[str, str]]:
        devices = await BleakScanner.discover(timeout=timeout)
        return [(d.name or "(unknown)", d.address) for d in devices]

    # ---- AsyncReconnectingEngine transport hooks ---------------------
    async def _open(self) -> None:
        target = await self._resolve_target()
        if target is None:
            raise RuntimeError("Coyote not found (set its BLE address or name)")
        client = BleakClient(target, disconnected_callback=self._on_disconnect)
        await client.connect()
        self._client = client
        try:
            await client.start_notify(NOTIFY_UUID, self._on_notify)
        except Exception:
            pass
        await self._read_battery(client)
        # Push hardware soft limits before any output frame.
        try:
            await client.write_gatt_char(WRITE_UUID, encode_bf(self._limit_a, self._limit_b), response=False)
        except Exception as e:
            self._log(f"Coyote BF write failed: {e}")
        self._connected = True
        self._change_evt = asyncio.Event()
        self._b0_task = asyncio.get_event_loop().create_task(self._b0_loop(client))

    async def _close(self) -> None:
        self._connected = False
        task = self._b0_task
        self._b0_task = None
        if task is not None:
            task.cancel()
        client = self._client
        self._client = None
        if client is not None:
            try:
                await client.disconnect()
            except Exception:
                pass

    async def _resolve_target(self):
        if self._device_addr:
            dev = await BleakScanner.find_device_by_address(self._device_addr, timeout=8.0)
            return dev or self._device_addr  # fall back to a direct address connect
        if self._device_name:
            return await BleakScanner.find_device_by_name(self._device_name, timeout=8.0)
        return None

    async def _b0_loop(self, client) -> None:
        """Send the current strengths/waveforms ~every 100 ms, waking early on
        a change so an edge isn't delayed by up to a full cadence."""
        try:
            while self._connected:
                frame = build_b0(self._next_seq(), self._strength_a, self._strength_b,
                                 self._wave_a, self._wave_b)
                try:
                    await client.write_gatt_char(WRITE_UUID, frame, response=False)
                except Exception as e:
                    self._log(f"Coyote B0 write failed: {e}")
                    self._connected = False
                    break
                try:
                    await asyncio.wait_for(self._change_evt.wait(), timeout=B0_INTERVAL_S)
                except asyncio.TimeoutError:
                    pass
                if self._change_evt is not None:
                    self._change_evt.clear()
        except asyncio.CancelledError:
            pass

    async def _send_bf(self) -> None:
        client = self._client
        if client is None:
            return
        try:
            await client.write_gatt_char(WRITE_UUID, encode_bf(self._limit_a, self._limit_b), response=False)
        except Exception as e:
            self._log(f"Coyote BF update failed: {e}")

    async def _read_battery(self, client) -> None:
        try:
            data = await client.read_gatt_char(BATTERY_UUID)
            if data:
                self._battery = int(data[0])
        except Exception:
            self._battery = None

    def _on_notify(self, _char, data: bytearray) -> None:
        parsed = decode_b1(bytes(data))
        if parsed is not None:
            # (seq, strength_a, strength_b) — device echoing applied strengths.
            self._battery = self._battery  # no-op; hook point for future use

    def _on_disconnect(self, _client) -> None:
        self._connected = False

    def _next_seq(self) -> int:
        self._seq = (self._seq + 1) & 0x0F
        return self._seq
