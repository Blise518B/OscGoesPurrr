"""Standalone Bluetooth probe for bHaptics suits, vests and sleeves.

Run this before trusting the slot tables in src/bhaptics_models.py: it finds
the suit, lists what it exposes, and buzzes one motor slot at a time so you
can say where each one sits. No app imports, no UI -- just `bleak`.

    python tools/bhaptics_probe.py scan [--seconds 10]
    python tools/bhaptics_probe.py gatt <name-or-address>
    python tools/bhaptics_probe.py walk <name-or-address> [--level 3] [--hold 0.4] [--slots 0-39]
    python tools/bhaptics_probe.py walk <name-or-address> --interactive
    python tools/bhaptics_probe.py hold <name-or-address> [--level 3] [--seconds 3]
    python tools/bhaptics_probe.py timing <name-or-address> [--writes 100]

`<name-or-address>` is a Bluetooth address or the start of the advertised
name (e.g. TactSuitPro, TactSuitAirOnyx, Tactosy2_L).

Close the bHaptics Player first: a suit takes one Bluetooth connection.

What the protocol is (SenseShift's constants, checked against three other
implementations, and the bHaptics Player's own logs): service 6e400001-...,
write without response.
  * TactSuit Pro and Air: 40 bytes on 6e400014-..., one byte per motor,
    0..100; only bytes 0-31 are motors (32 slots to walk).
  * Older vests (X40, X16, Tactot): 20 bytes on 6e40000a-... = 40 slots of
    0..15, two per byte, the even slot in the high half.
  * Sleeves, head, hands and feet: one byte per motor, 0..100, on 6e40000a.

`walk --interactive` waits for Enter after each slot and takes a note
("front top left", "nothing", ...); the notes are saved as JSON under
%LOCALAPPDATA%\\OscGoesPurrr\\bhaptics_probe\\ for building the slot table.
Every command ends by writing all-zero twice, Ctrl+C included.
"""

import argparse
import asyncio
import json
import os
import statistics
import sys
import time
from pathlib import Path

try:
    from bleak import BleakClient, BleakScanner
except ImportError:
    print("This probe needs the 'bleak' package (pip install bleak).")
    sys.exit(2)

MOTOR_CHAR = "6e40000a-b5a3-f393-e0a9-e50e24dcca9e"
GRID_MOTOR_CHAR = "6e400014-b5a3-f393-e0a9-e50e24dcca9e"
NAMED_CHARS = {
    "6e400002-b5a3-f393-e0a9-e50e24dcca9e": "motor (legacy)",
    "6e400003-b5a3-f393-e0a9-e50e24dcca9e": "serial number",
    "6e400005-b5a3-f393-e0a9-e50e24dcca9e": "config",
    "6e400007-b5a3-f393-e0a9-e50e24dcca9e": "version",
    "6e400008-b5a3-f393-e0a9-e50e24dcca9e": "battery",
    "6e40000a-b5a3-f393-e0a9-e50e24dcca9e": "motor",
    "6e40000b-b5a3-f393-e0a9-e50e24dcca9e": "tactsuit monitor",
    "6e40000c-b5a3-f393-e0a9-e50e24dcca9e": "audio-to-haptic config",
    "6e40000d-b5a3-f393-e0a9-e50e24dcca9e": "audio-to-haptic theme",
    "6e40000e-b5a3-f393-e0a9-e50e24dcca9e": "motor mapping",
    "6e40000f-b5a3-f393-e0a9-e50e24dcca9e": "signature pattern",
    "6e400014-b5a3-f393-e0a9-e50e24dcca9e": "motor (Pro / Air)",
}
# Never touched by this probe: writing the DFU control point reboots the
# device into its firmware updater.
DFU_SERVICE = "0000fe59-0000-1000-8000-00805f9b34fb"

NAME_PREFIXES = ("TactSuit", "Tactot", "Tactosy", "Tactal", "TactGlove", "Tactvisor")

# Plain (one byte per motor) devices by name prefix -> motor count. Anything
# not listed here and not a vest is refused by `walk` until it's added.
PLAIN_MOTORS = (
    ("Tactosy2", 6),
    ("TactosyH", 3),
    ("TactosyF", 3),
    ("Tactal", 6),
    ("Tactvisor", 4),
)
VEST_SLOTS = 40
# Vests driven one byte per motor on their own characteristic.
GRID_PREFIXES = ("TactSuitPro", "TactSuitAir")
GRID_MOTORS = 32
GRID_FRAME_BYTES = 40

RESULTS_DIR = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "OscGoesPurrr" / "bhaptics_probe"


# ---- frames --------------------------------------------------------------

def vest_frame(levels):
    """40 levels 0..15 -> the 20-byte vest frame (even slot in the high half)."""
    lv = (list(levels) + [0] * VEST_SLOTS)[:VEST_SLOTS]
    return bytes(
        (max(0, min(15, int(lv[i * 2]))) << 4) | max(0, min(15, int(lv[i * 2 + 1])))
        for i in range(VEST_SLOTS // 2)
    )


def plain_frame(levels, count):
    """Per-motor levels 0..100 -> one byte each."""
    lv = (list(levels) + [0] * count)[:count]
    return bytes(max(0, min(100, int(v))) for v in lv)


class Layout:
    """How to talk to one device: the frame builder and its slot count."""

    def __init__(self, name):
        self.name = name or ""
        self.vest = self.name.startswith(("TactSuit", "Tactot"))
        self.grid = self.name.startswith(GRID_PREFIXES)
        self.char = GRID_MOTOR_CHAR if self.grid else MOTOR_CHAR
        self.count = GRID_MOTORS if self.grid else VEST_SLOTS
        if not self.vest:
            self.count = next(
                (n for prefix, n in PLAIN_MOTORS if self.name.startswith(prefix)), 0)

    @property
    def known(self):
        return self.count > 0

    def frame(self, levels):
        if self.grid:
            return plain_frame(levels, self.count) + bytes(GRID_FRAME_BYTES - self.count)
        return vest_frame(levels) if self.vest else plain_frame(levels, self.count)

    def level(self, vest_level):
        """The probe's --level is on the old vest's 0..15 scale; scale it for
        the per-motor devices so 3 feels about the same on all."""
        return vest_level if self.vest and not self.grid else round(vest_level * 100 / 15)

    def zero(self):
        return self.frame([0] * self.count)


# ---- finding the device ---------------------------------------------------

def _looks_bhaptics(name):
    return bool(name) and name.startswith(NAME_PREFIXES)


async def find(target, seconds=10.0):
    """Resolve a name prefix or address to (BLEDevice, advertised name)."""
    print(f"Looking for {target!r} ({seconds:.0f} s) ...", flush=True)
    want = target.lower()
    found = await BleakScanner.discover(timeout=seconds, return_adv=True)
    for address, (dev, adv) in found.items():
        name = adv.local_name or dev.name or ""
        if address.lower() == want or (name and name.lower().startswith(want)):
            return dev, name
    return None, ""


# ---- commands ---------------------------------------------------------------

async def cmd_scan(seconds):
    print(f"Scanning {seconds:.0f} s ...", flush=True)
    found = await BleakScanner.discover(timeout=seconds, return_adv=True)
    rows = []
    for address, (dev, adv) in found.items():
        name = adv.local_name or dev.name or ""
        if _looks_bhaptics(name):
            rows.append((name, address, adv.rssi))
    if not rows:
        print("No bHaptics device found. Is it switched on, and is the Player closed?")
        return 1
    for name, address, rssi in sorted(rows):
        layout = Layout(name)
        kind = f"vest, {layout.count} slots" if layout.vest else (
            f"{layout.count} motors" if layout.known else "unknown layout")
        print(f"  {name:<24} {address}  rssi {rssi}  ({kind})")
    return 0


async def cmd_gatt(target):
    dev, name = await find(target)
    if dev is None:
        print("Not found.")
        return 1
    print(f"Connecting to {name} ({dev.address}) ...", flush=True)
    async with BleakClient(dev, timeout=20.0) as client:
        for service in client.services:
            note = "  (firmware updater -- never written)" if service.uuid == DFU_SERVICE else ""
            print(f"[service] {service.uuid}  {service.description}{note}")
            for char in service.characteristics:
                label = NAMED_CHARS.get(char.uuid, "")
                props = ",".join(char.properties)
                print(f"  [char] {char.uuid}  {props}  {label}")
                if "read" in char.properties and service.uuid != DFU_SERVICE:
                    try:
                        val = await client.read_gatt_char(char)
                        text = "".join(chr(b) if 32 <= b < 127 else "." for b in val)
                        print(f"         = {val.hex(' ')}  {text!r}")
                    except Exception as e:  # noqa: BLE001 -- report and carry on
                        print(f"         read failed: {e}")
    return 0


def _parse_slots(spec, count):
    out = []
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            a, b = part.split("-", 1)
            out.extend(range(int(a), int(b) + 1))
        else:
            out.append(int(part))
    return [s for s in out if 0 <= s < count]


async def _write(client, layout, data):
    await client.write_gatt_char(layout.char, data, response=False)


async def _all_zero(client, layout):
    for _ in range(2):
        try:
            await _write(client, layout, layout.zero())
        except Exception:  # noqa: BLE001 -- best effort on the way out
            pass
        await asyncio.sleep(0.05)


async def cmd_walk(target, level, hold, slots_spec, interactive):
    dev, name = await find(target)
    if dev is None:
        print("Not found.")
        return 1
    layout = Layout(name)
    if not layout.known:
        print(f"{name}: no layout known for this model yet. Add it to PLAIN_MOTORS.")
        return 1
    slots = _parse_slots(slots_spec or f"0-{layout.count - 1}", layout.count)
    lvl = layout.level(level)
    notes = {}
    print(f"Connecting to {name} ({dev.address}) ...", flush=True)
    async with BleakClient(dev, timeout=20.0) as client:
        try:
            await _all_zero(client, layout)
            for slot in slots:
                levels = [0] * layout.count
                levels[slot] = lvl
                if interactive:
                    await asyncio.to_thread(input, f"Slot {slot:2d}: Enter to buzz ")
                else:
                    print(f"Slot {slot:2d}", flush=True)
                await _write(client, layout, layout.frame(levels))
                await asyncio.sleep(hold)
                await _write(client, layout, layout.zero())
                if interactive:
                    note = await asyncio.to_thread(
                        input, "         where did you feel it? (blank = nothing, r = repeat) ")
                    while note.strip().lower() == "r":
                        await _write(client, layout, layout.frame(levels))
                        await asyncio.sleep(hold)
                        await _write(client, layout, layout.zero())
                        note = await asyncio.to_thread(input, "         where? ")
                    notes[slot] = note.strip() or "nothing"
                else:
                    await asyncio.sleep(0.3)
        finally:
            await _all_zero(client, layout)
    if notes:
        RESULTS_DIR.mkdir(parents=True, exist_ok=True)
        path = RESULTS_DIR / f"walk_{name}_{time.strftime('%Y%m%d_%H%M%S')}.json"
        path.write_text(json.dumps({
            "name": name, "level": lvl, "hold_s": hold,
            "slots": {str(k): v for k, v in notes.items()},
        }, indent=2), encoding="utf-8")
        print(f"Saved {path}")
    return 0


async def cmd_hold(target, level, seconds):
    """One frame, then silence: does the device keep buzzing on its own?"""
    dev, name = await find(target)
    if dev is None:
        print("Not found.")
        return 1
    layout = Layout(name)
    if not layout.known:
        print(f"{name}: no layout known for this model yet.")
        return 1
    print(f"Connecting to {name} ({dev.address}) ...", flush=True)
    async with BleakClient(dev, timeout=20.0) as client:
        try:
            levels = [layout.level(level)] * layout.count
            print(f"One frame on every motor, then nothing for {seconds:.1f} s.")
            print("Watch whether it keeps buzzing the whole time or stops by itself.", flush=True)
            await _write(client, layout, layout.frame(levels))
            started = time.monotonic()
            await asyncio.sleep(seconds)
            print(f"Sending zero after {time.monotonic() - started:.2f} s.")
        finally:
            await _all_zero(client, layout)
    return 0


async def cmd_timing(target, writes):
    """Back-to-back zero frames: how long a write-without-response call takes."""
    dev, name = await find(target)
    if dev is None:
        print("Not found.")
        return 1
    layout = Layout(name)
    if not layout.known:
        print(f"{name}: no layout known for this model yet.")
        return 1
    print(f"Connecting to {name} ({dev.address}) ...", flush=True)
    async with BleakClient(dev, timeout=20.0) as client:
        times = []
        try:
            zero = layout.zero()
            for _ in range(writes):
                t0 = time.perf_counter()
                await _write(client, layout, zero)
                times.append((time.perf_counter() - t0) * 1000.0)
        finally:
            await _all_zero(client, layout)
    if times:
        times.sort()
        p95 = times[min(len(times) - 1, int(len(times) * 0.95))]
        print(f"{len(times)} writes: mean {statistics.mean(times):.2f} ms, "
              f"median {statistics.median(times):.2f} ms, p95 {p95:.2f} ms, "
              f"max {times[-1]:.2f} ms")
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("scan")
    p.add_argument("--seconds", type=float, default=10.0)

    p = sub.add_parser("gatt")
    p.add_argument("target")

    p = sub.add_parser("walk")
    p.add_argument("target")
    p.add_argument("--level", type=int, default=3, help="vest scale 0..15 (default 3)")
    p.add_argument("--hold", type=float, default=0.4)
    p.add_argument("--slots", default="", help="e.g. 0-19 or 3,7,12 (default: all)")
    p.add_argument("--interactive", action="store_true")

    p = sub.add_parser("hold")
    p.add_argument("target")
    p.add_argument("--level", type=int, default=3)
    p.add_argument("--seconds", type=float, default=3.0)

    p = sub.add_parser("timing")
    p.add_argument("target")
    p.add_argument("--writes", type=int, default=100)

    args = ap.parse_args()
    level = max(1, min(8, getattr(args, "level", 3)))  # the probe never goes past half
    try:
        if args.cmd == "scan":
            return asyncio.run(cmd_scan(args.seconds))
        if args.cmd == "gatt":
            return asyncio.run(cmd_gatt(args.target))
        if args.cmd == "walk":
            return asyncio.run(cmd_walk(args.target, level, args.hold, args.slots, args.interactive))
        if args.cmd == "hold":
            return asyncio.run(cmd_hold(args.target, level, args.seconds))
        if args.cmd == "timing":
            return asyncio.run(cmd_timing(args.target, args.writes))
    except KeyboardInterrupt:
        print("\nStopped.")
        return 130
    return 2


if __name__ == "__main__":
    sys.exit(main())
