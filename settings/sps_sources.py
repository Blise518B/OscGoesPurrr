"""Global registry of user-defined synthetic SPS sources.

Stored outside profiles (like known_devices.json) so the sources a user
builds are available to every profile and to both the Buttplug and
bHaptics routers. Each record is normalised through
`sps_source.normalize_source_def` on the way in, so the on-disk shape
stays consistent regardless of who wrote it. See sps_source.py for the
field semantics."""

import json
import os
from typing import Any, Dict, List, Optional

from utilities import atomic_write_json
from sps_source import normalize_source_def

from ._paths import SPS_SOURCES_FILE


class SpsSourceManager:
    """Storage-only registry of synthetic SPS sources. Picker-shaped views
    (grouped by Orf/Pen, etc.) are derived in the controller facade — this
    class only loads, saves, and mutates the canonical list."""

    SCHEMA_VERSION = 1

    def __init__(self):
        self.sources: List[Dict[str, Any]] = []
        self._load()

    # ------------------------------------------------------------------
    # Load / save
    # ------------------------------------------------------------------

    def _load(self) -> None:
        if os.path.exists(SPS_SOURCES_FILE):
            try:
                with open(SPS_SOURCES_FILE, 'r') as f:
                    loaded = json.load(f)
            except (json.JSONDecodeError, IOError) as e:
                print(f"SPS sources load error: {e}")
                loaded = None
            if isinstance(loaded, dict):
                raw = loaded.get("sources", [])
                self.sources = [
                    normalize_source_def(s) for s in raw
                    if isinstance(s, dict) and str(s.get("name", "")).strip()
                ]
                return
        self.sources = []

    def save(self) -> None:
        payload = {"schema": self.SCHEMA_VERSION, "sources": self.sources}
        try:
            atomic_write_json(SPS_SOURCES_FILE, payload, indent=2)
        except OSError as e:
            print(f"SPS sources save error: {e}")

    # ------------------------------------------------------------------
    # Reads
    # ------------------------------------------------------------------

    def list_sources(self) -> List[Dict[str, Any]]:
        """Every stored source (copies, safe to mutate)."""
        return [dict(s) for s in list(self.sources)]

    def get_source(self, name: str) -> Optional[Dict[str, Any]]:
        for s in list(self.sources):
            if s.get("name") == name:
                return dict(s)
        return None

    def get_source_map(self, enabled_only: bool = True) -> Dict[str, Dict[str, Any]]:
        """`name -> definition` for router resolution. Disabled sources are
        excluded by default so a toggled-off source contributes nothing to
        any motor or bHaptics dot.

        Iterates a list snapshot — the bHaptics router calls this from its
        own poll thread while the UI thread may be editing the registry."""
        out: Dict[str, Dict[str, Any]] = {}
        for s in list(self.sources):
            if enabled_only and not s.get("enabled", True):
                continue
            name = s.get("name")
            if name:
                out[name] = dict(s)
        return out

    # ------------------------------------------------------------------
    # Writes
    # ------------------------------------------------------------------

    def add_or_update_source(self, defn: Dict[str, Any]) -> Optional[str]:
        """Insert or replace a source, matched by name. Returns the stored
        name, or None when the definition has no usable name."""
        record = normalize_source_def(defn)
        name = record["name"]
        if not name:
            return None
        idx = self._index_of(name)
        if idx >= 0:
            self.sources[idx] = record
        else:
            self.sources.append(record)
        self.save()
        return name

    def delete_source(self, name: str) -> bool:
        idx = self._index_of(name)
        if idx < 0:
            return False
        del self.sources[idx]
        self.save()
        return True

    def rename_source(self, old: str, new: str) -> bool:
        new = str(new or "").strip()
        if not new or self._index_of(old) < 0:
            return False
        if new != old and self._index_of(new) >= 0:
            return False
        self.sources[self._index_of(old)]["name"] = new
        self.save()
        return True

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _index_of(self, name: str) -> int:
        for i, s in enumerate(self.sources):
            if s.get("name") == name:
                return i
        return -1
