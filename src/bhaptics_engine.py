# bhaptics_engine.py
# Sealed bHaptics engine: OGP talks to the suit, sleeves and head over
# Bluetooth itself -- no bHaptics Player. Outside callers use the public
# methods only; the Bluetooth detail stays in bhaptics_ble.py and the byte
# layout in bhaptics_models.py.
#
# Threads: one asyncio loop on its own thread runs everything Bluetooth
# (scan, connect, writes, battery). The router calls submit_frame() from its
# thread; that only stores the frame and wakes the device's writer, so the
# hot path has no queue -- each device keeps its newest frame and nothing
# else.
#
# Per device:
#   * a write goes out without response the moment a frame changes, at most
#     one in flight, and at most every MIN_WRITE_GAP_S (the first change
#     after idle never waits; a burst is coalesced into its newest frame);
#   * a frame left non-zero with no submit for FRAME_TTL_S goes to zero, so a
#     stalled router can't leave a motor running -- the job the Player's
#     `durationMillis` did before;
#   * stop, release, Off and disconnect write all-zero twice;
#   * paused (Home's switch to Off) writes all-zero twice and ignores every
#     frame until it is switched on -- the router, a test and a held dot
#     alike. The facade keeps it across restarts (suits_settings.json).
#
# A suit takes one Bluetooth connection: while the bHaptics Player holds it,
# it doesn't advertise and the scan finds nothing. release() lets go so the
# Player or a game can have it, until connect() is pressed again.

import asyncio
import threading
import time
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

import bhaptics_models as models
from bhaptics_models import NODE_COUNTS

MIN_WRITE_GAP_S = 0.02      # ~50 writes/s per device
FRAME_TTL_S = 0.25
_WATCHDOG_EVERY_S = 0.05
_SCAN_S = 4.0
_RESCAN_EVERY_S = 3.0
_BATTERY_EVERY_S = 60.0
_STOP_WAIT_S = 2.0


class _Device:
    def __init__(self, link, binding: models.Binding):
        self.link = link
        self.binding = binding
        self.wake = asyncio.Event()
        self.last_sent: Optional[bytes] = None
        self.last_write = -1e18
        self.battery: Optional[int] = None
        self.task: Optional[asyncio.Task] = None


def _clean_dots(position: str, dots) -> Tuple[int, ...]:
    count = NODE_COUNTS[position]
    out = []
    for i in range(count):
        try:
            v = float(dots[i])
        except (IndexError, TypeError, ValueError):
            v = 0.0
        out.append(int(max(0.0, min(100.0, v))) if v == v else 0)
    return tuple(out)


class BHapticsEngine:
    """Sealed: primitive public methods, all state private. Threadsafe."""

    def __init__(self, radio_factory: Optional[Callable[[], Any]] = None,
                 clock: Callable[[], float] = time.monotonic,
                 log: Optional[Callable[[str], None]] = None):
        if radio_factory is None:
            import bhaptics_ble
            radio_factory = bhaptics_ble.BleakRadio
        self._radio = radio_factory()
        self._clock = clock
        self._log = log or (lambda _m: None)
        self._state_callback: Callable[[], None] = lambda: None

        self._lock = threading.Lock()
        self._frames: Dict[str, Tuple[int, ...]] = {}
        self._frame_at: Dict[str, float] = {}

        # Loop-thread state (only touched on the loop, except the snapshot
        # copies below, which are swapped under _lock).
        self._devices: Dict[str, _Device] = {}
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._thread: Optional[threading.Thread] = None
        self._scan_now: Optional[asyncio.Event] = None

        self._want = False
        self._released = False
        self._paused = False
        self._scanning = False
        self._last_error = ""
        self._snapshot: List[Dict[str, Any]] = []

    # ---- status -------------------------------------------------------
    @property
    def is_available(self) -> bool:
        return bool(getattr(self._radio, "available", True))

    @property
    def is_connected(self) -> bool:
        with self._lock:
            return bool(self._snapshot)

    def connected_positions(self) -> Set[str]:
        with self._lock:
            return {p for d in self._snapshot for p in d["positions"]}

    def status_snapshot(self) -> Dict[str, Any]:
        with self._lock:
            devices = [dict(d) for d in self._snapshot]
        error = self._last_error
        if not self.is_available:
            error = getattr(self._radio, "unavailable_reason", "") or "Bluetooth unavailable"
        return {
            "available": self.is_available,
            "wanted": self._want,
            "released": self._released,
            "paused": self._paused,
            "scanning": self._scanning,
            "error": error,
            "devices": devices,
        }

    def output_snapshot(self) -> Dict[str, Tuple[int, ...]]:
        """The newest frame per position (what the devices are told)."""
        with self._lock:
            return dict(self._frames)

    def set_state_callback(self, fn: Optional[Callable[[], None]]) -> None:
        """Called from the loop thread when devices, scanning or the error
        change. Must be cheap and thread-safe."""
        self._state_callback = fn or (lambda: None)

    # ---- hot path (router thread) --------------------------------------
    def submit_frame(self, position: str, dots) -> None:
        """Newest dots (0..100) for one position. Cheap when unchanged: the
        router calls it every tick, which also keeps the TTL from expiring
        a held frame."""
        if position not in NODE_COUNTS:
            return
        frame = _clean_dots(position, dots)
        now = self._clock()
        with self._lock:
            if self._paused:
                return
            changed = self._frames.get(position) != frame
            self._frames[position] = frame
            self._frame_at[position] = now
        if changed:
            self._call_soon(self._wake_for, position)

    def end_all(self) -> None:
        """Every position to zero now, written twice (Off, Stop, feature
        off)."""
        now = self._clock()
        with self._lock:
            for p in list(self._frames):
                self._frames[p] = (0,) * NODE_COUNTS[p]
                self._frame_at[p] = now
        self._run_soon(self._zero_all)

    def set_paused(self, paused: bool) -> None:
        """Off (Home's switch): everything to zero (twice) and nothing new
        until it is switched on again."""
        with self._lock:
            self._paused = bool(paused)
        if paused:
            self.end_all()
        try:
            self._state_callback()
        except Exception:  # noqa: BLE001
            pass

    @property
    def is_paused(self) -> bool:
        return self._paused

    # ---- lifecycle (cold path) -------------------------------------------
    def start(self, auto_connect: bool) -> None:
        """Start the Bluetooth thread. With auto_connect it scans for
        devices straight away and keeps reconnecting them."""
        self._want = bool(auto_connect) and not self._released
        if self._thread is not None and self._thread.is_alive():
            self._kick_scan()
            return
        loop = asyncio.new_event_loop()
        ready = threading.Event()
        self._loop = loop
        self._thread = threading.Thread(target=self._thread_main, args=(loop, ready),
                                        daemon=True, name="bHapticsBLE")
        self._thread.start()
        ready.wait(2.0)

    def stop(self) -> None:
        """Zero everything, drop every device, end the thread."""
        self._want = False
        loop, thread = self._loop, self._thread
        if loop is None or thread is None:
            return
        try:
            fut = asyncio.run_coroutine_threadsafe(self._shutdown(), loop)
            fut.result(timeout=_STOP_WAIT_S)
        except Exception:  # noqa: BLE001 -- best effort; the thread ends below
            pass
        try:
            loop.call_soon_threadsafe(loop.stop)
        except RuntimeError:
            pass
        thread.join(timeout=_STOP_WAIT_S)
        self._loop = None
        self._thread = None
        self._publish()

    def connect(self) -> None:
        """Look for devices now and keep them connected."""
        self._want = True
        self._released = False
        self._last_error = ""
        if self._thread is None or not self._thread.is_alive():
            self.start(True)
        else:
            self._kick_scan()

    def release(self) -> None:
        """Let go of every device (zeroed first) and stop reconnecting, so
        the bHaptics Player or a game can take the suit."""
        self._want = False
        self._released = True
        self._run_soon(self._drop_all)

    # ---- loop thread -----------------------------------------------------
    def _thread_main(self, loop: asyncio.AbstractEventLoop, ready: threading.Event) -> None:
        asyncio.set_event_loop(loop)
        self._scan_now = asyncio.Event()
        loop.create_task(self._supervise())
        loop.create_task(self._watchdog())
        ready.set()
        try:
            loop.run_forever()
        finally:
            tasks = asyncio.all_tasks(loop)
            for t in tasks:
                t.cancel()
            loop.run_until_complete(asyncio.gather(*tasks, return_exceptions=True))
            loop.run_until_complete(loop.shutdown_asyncgens())
            loop.close()

    def _call_soon(self, fn, *args) -> None:
        loop = self._loop
        if loop is None:
            return
        try:
            loop.call_soon_threadsafe(fn, *args)
        except RuntimeError:
            pass  # loop closing

    def _run_soon(self, coro_fn) -> None:
        """Schedule a coroutine on the loop without waiting. The coroutine is
        only created once the loop is known to be up, so a stopped engine
        never leaves one un-awaited."""
        loop = self._loop
        if loop is None or loop.is_closed():
            return
        try:
            loop.call_soon_threadsafe(lambda: loop.create_task(coro_fn()))
        except RuntimeError:
            pass

    def _kick_scan(self) -> None:
        def _set():
            if self._scan_now is not None:
                self._scan_now.set()
        self._call_soon(_set)

    def _wake_for(self, position: str) -> None:
        for dev in self._devices.values():
            if position in dev.binding.positions:
                dev.wake.set()

    async def _supervise(self) -> None:
        battery_due = 0.0
        while True:
            if self._want and not self._devices and self.is_available:
                await self._scan_and_open()
            now = self._clock()
            if self._devices and now >= battery_due:
                battery_due = now + _BATTERY_EVERY_S
                await self._read_batteries()
            try:
                await asyncio.wait_for(self._scan_now.wait(), _RESCAN_EVERY_S)
                self._scan_now.clear()
                if self._want and self.is_available:
                    await self._scan_and_open()
            except asyncio.TimeoutError:
                pass

    async def _scan_and_open(self) -> None:
        self._scanning = True
        self._publish()
        try:
            found = await self._radio.discover(_SCAN_S)
        except Exception as e:  # noqa: BLE001
            self._last_error = f"Bluetooth scan failed: {e}"
            found = []
        finally:
            self._scanning = False
        for item in found:
            if not self._want or item.address in self._devices:
                continue
            binding = models.bind(item.name)
            if binding is None:
                continue
            try:
                link = await self._radio.open(
                    item, lambda a=item.address: self._call_soon(self._lost, a, "disconnected"),
                    motor_char=binding.model.motor_char)
            except Exception as e:  # noqa: BLE001
                self._last_error = f"{item.name}: {e}"
                self._log(f"bHaptics: couldn't connect to {item.name} ({e})")
                continue
            if not self._want:      # released while connecting
                await link.close()
                continue
            dev = _Device(link, binding)
            self._devices[item.address] = dev
            dev.task = asyncio.get_running_loop().create_task(self._writer(dev))
            dev.wake.set()          # send the current frame (usually zero)
            self._last_error = ""
            self._log(f"bHaptics: connected {item.name}")
            try:
                dev.battery = await link.read_battery()
            except Exception:  # noqa: BLE001
                dev.battery = None
        if not found and self._want and not self._devices:
            self._last_error = "No bHaptics device found (is it on, and the bHaptics Player closed?)"
        self._publish()

    async def _read_batteries(self) -> None:
        changed = False
        for dev in list(self._devices.values()):
            try:
                level = await dev.link.read_battery()
            except Exception:  # noqa: BLE001
                continue
            if level != dev.battery:
                dev.battery = level
                changed = True
        if changed:
            self._publish()

    def _frame_for(self, dev: _Device) -> bytes:
        with self._lock:
            frames = {p: self._frames.get(p, ()) for p in dev.binding.positions}
        return models.encode(dev.binding, frames)

    async def _writer(self, dev: _Device) -> None:
        while True:
            await dev.wake.wait()
            dev.wake.clear()
            gap = MIN_WRITE_GAP_S - (self._clock() - dev.last_write)
            if gap > 0:
                await asyncio.sleep(gap)    # a burst collapses into its newest frame
            data = self._frame_for(dev)
            if data == dev.last_sent:
                continue
            try:
                await dev.link.write(data)
            except Exception as e:  # noqa: BLE001
                self._lost(dev.link.address, f"write failed: {e}")
                return
            dev.last_sent = data
            dev.last_write = self._clock()

    async def _watchdog(self) -> None:
        while True:
            await asyncio.sleep(_WATCHDOG_EVERY_S)
            for position in self._expire_stale(self._clock()):
                self._wake_for(position)

    def _expire_stale(self, now: float) -> List[str]:
        """Zero every non-zero frame nobody has submitted for FRAME_TTL_S."""
        expired = []
        with self._lock:
            for position, at in self._frame_at.items():
                frame = self._frames.get(position)
                if frame and any(frame) and now - at > FRAME_TTL_S:
                    self._frames[position] = (0,) * NODE_COUNTS[position]
                    expired.append(position)
        return expired

    async def _write_zero_twice(self, dev: _Device) -> None:
        zero = models.zero_frame(dev.binding)
        for _ in range(2):
            try:
                await dev.link.write(zero)
            except Exception:  # noqa: BLE001 -- best effort
                return
        dev.last_sent = zero
        dev.last_write = self._clock()

    async def _zero_all(self) -> None:
        for dev in list(self._devices.values()):
            await self._write_zero_twice(dev)

    async def _drop_all(self) -> None:
        devices = list(self._devices.values())
        self._devices.clear()
        for dev in devices:
            if dev.task is not None:
                dev.task.cancel()
            await self._write_zero_twice(dev)
            await dev.link.close()
        self._publish()

    async def _shutdown(self) -> None:
        with self._lock:
            for p in list(self._frames):
                self._frames[p] = (0,) * NODE_COUNTS[p]
        await self._drop_all()

    def _lost(self, address: str, reason: str) -> None:
        dev = self._devices.pop(address, None)
        if dev is None:
            return
        if dev.task is not None and dev.task is not asyncio.current_task():
            dev.task.cancel()
        self._last_error = f"{dev.link.name} {reason}"
        self._log(f"bHaptics: {dev.link.name} {reason}")
        loop = self._loop
        if loop is not None:
            loop.create_task(dev.link.close())
        self._publish()

    def _publish(self) -> None:
        snapshot = [{
            "address": addr,
            "name": dev.link.name,
            "label": dev.binding.model.label,
            "model": dev.binding.model.key,
            "positions": list(dev.binding.positions),
            "battery": dev.battery,
            "verified": dev.binding.model.verified,
        } for addr, dev in self._devices.items()]
        with self._lock:
            self._snapshot = snapshot
        try:
            self._state_callback()
        except Exception:  # noqa: BLE001
            pass
