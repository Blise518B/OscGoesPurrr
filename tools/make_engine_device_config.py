"""Write the device list the bundled intiface-engine starts with:
src/intiface-engine/buttplug-device-config-v4.json.

It is Buttplug's own device config from the engine checkout
(_engine_build/buttplug, the commit THIRD_PARTY_NOTICES.md names), with one
change. Buttplug's Lovense entry also matches on the Nordic UART Service
alone. Any Bluetooth device that advertises that UUID passes, and it is the
standard "BLE serial" service: MeshCore radios, Espruino watches, ESP32
serial bridges. The engine connects to each one, sends Lovense's
`DeviceType;`, drops it and tries again on the next scan. A MeshCore radio
near Blise got 7-8 connects a minute, 2.4 s each, sharing the radio with the
toys (2026-10-24).

Lovense toys are found by their LVS- / LOVE- names and their own service
UUIDs anyway, so the UUID only leaves Lovense's *advertised* services. It
stays in Lovense's `services`, so a toy found by name still talks over it.

intiface_integrated passes the file with --device-config-file, and it
REPLACES the engine's built-in list. Regenerate it after every engine
rebuild (rebuild_intiface_engine.bat does); tests/test_engine_device_config.py
fails while it and the checkout differ. When Buttplug drops the match
itself, this script says so: then delete the file and this script.

Run from the project root:
    venv\\Scripts\\python.exe tools\\make_engine_device_config.py
"""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SOURCE = (REPO / "_engine_build" / "buttplug" / "crates" / "buttplug_server_device_config"
          / "build-config" / "buttplug-device-config-v4.json")
OUT = REPO / "src" / "intiface-engine" / "buttplug-device-config-v4.json"

NORDIC_UART_SERVICE = "6e400001-b5a3-f393-e0a9-e50e24dcca9e"
# protocol -> service UUIDs a device advertising them is NOT taken for it
NOT_BY_ADVERTISED_SERVICE = {"lovense": (NORDIC_UART_SERVICE,)}


def corrected(config: dict) -> dict:
    """`config` (Buttplug's device config) with NOT_BY_ADVERTISED_SERVICE
    applied. Raises ValueError when one of those UUIDs is no longer
    advertised for its protocol, so a Buttplug fix doesn't go unnoticed."""
    out = copy.deepcopy(config)
    for protocol, uuids in NOT_BY_ADVERTISED_SERVICE.items():
        removed = set()
        for comm in out["protocols"][protocol].get("communication") or []:
            btle = comm.get("btle")
            if not btle or "advertised_services" not in btle:
                continue
            keep = [u for u in btle["advertised_services"] if u.lower() not in uuids]
            removed |= {u.lower() for u in btle["advertised_services"]} - {u.lower() for u in keep}
            btle["advertised_services"] = keep
        missing = set(uuids) - removed
        if missing:
            raise ValueError(
                f"Buttplug's {protocol} entry no longer matches on {', '.join(sorted(missing))}: "
                "the engine's own list is fine now, so delete "
                f"{OUT.relative_to(REPO).as_posix()} and tools/make_engine_device_config.py")
    return out


def render(config: dict) -> str:
    """The file's text: the checkout's own layout (2-space indent, UTF-8),
    so a diff against Buttplug's file shows only the change."""
    return json.dumps(config, indent=2, ensure_ascii=False) + "\n"


def main() -> int:
    if not SOURCE.is_file():
        print(f"Engine checkout not found: {SOURCE}", file=sys.stderr)
        return 1
    config = json.loads(SOURCE.read_text(encoding="utf-8"))
    try:
        text = render(corrected(config))
    except ValueError as e:
        print(e, file=sys.stderr)
        return 1
    OUT.write_text(text, encoding="utf-8", newline="\n")
    version = config.get("version", {})
    print(f"Wrote {OUT.relative_to(REPO)} (device config {version.get('major')}.{version.get('minor')}, "
          f"Lovense no longer matched by the Nordic UART Service alone)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
