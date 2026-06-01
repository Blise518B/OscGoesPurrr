"""Tiny persistent state for the bench — a stable virtual-toy identity.

The Lovense handshake carries an `address` (the toy's serial / fake MAC).
Intiface, OGB and OGP all key their per-device config on that serial, so if it
changes every launch the toy shows up as a brand-new device and has to be
re-routed each time. We therefore persist one address PER MODEL and reuse it,
so reconnecting "Lovense Hush" always presents the same Hush.

Stored as JSON at %APPDATA%/OscGoesPurrr/testbench_state.json (override the path
with the OGP_TESTBENCH_STATE env var, used by the tests). Best-effort: any I/O
error degrades to in-memory-only behaviour rather than crashing the bench.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Dict

from .lovense_protocol import random_address


def _path() -> Path:
    override = os.environ.get("OGP_TESTBENCH_STATE")
    if override:
        return Path(override)
    base = os.environ.get("APPDATA") or os.path.expanduser("~")
    return Path(base) / "OscGoesPurrr" / "testbench_state.json"


def _load() -> Dict:
    try:
        return json.loads(_path().read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save(state: Dict) -> None:
    try:
        p = _path()
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(state, indent=2), encoding="utf-8")
    except Exception:
        pass  # config persistence is best-effort; never break the bench


def toy_address(model_name: str) -> str:
    """Return a stable 12-hex address for this model, generating + persisting
    one the first time so the virtual toy keeps a consistent identity."""
    state = _load()
    addrs = state.setdefault("toy_addresses", {})
    addr = addrs.get(model_name)
    if not addr:
        addr = random_address()
        addrs[model_name] = addr
        _save(state)
    return addr


def remember_toy(model_name: str, identifier: str, url: str) -> None:
    """Persist the last-used toy setup so the UI can restore it next launch."""
    state = _load()
    state["last_toy"] = {"model": model_name, "identifier": identifier, "url": url}
    _save(state)


def last_toy() -> Dict:
    """The last-used {model, identifier, url}, or {} if none saved."""
    lt = _load().get("last_toy")
    return lt if isinstance(lt, dict) else {}
