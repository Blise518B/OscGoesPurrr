"""Shared base for the one-JSON-file settings managers.

Every concern under `settings/` persists a single JSON dict to a file in the
AppData directory, and the load-or-create-defaults / merge-with-defaults /
atomic-save dance is identical across them. This base owns that boilerplate so
a concrete manager only has to declare `DEFAULTS` + `FILE_PATH` and, when it
has nested structure or legacy fields to migrate, override `_post_load()`.

Adopting managers keep all their domain getters/setters; only the
load/save plumbing moves here. The contract a subclass relies on:

  * `self.settings` — the live dict (merged defaults + on-disk values).
  * `self._save()` — atomic write of `self.settings` to `FILE_PATH`.
  * `_post_load(loaded)` — called after a successful load+merge, with the raw
    on-disk dict, so the subclass can backfill nested defaults or migrate
    legacy keys. Mutate `self.settings` in place; call `self._save()` if you
    changed something that should persist immediately.
"""

import json
import os
from typing import Any, Dict

from utilities import atomic_write_json


class JsonSettingsManager:
    """Load/merge/atomic-save base for a single-JSON-file settings store.

    Subclasses set:
      * ``DEFAULTS`` — class dict of default values (deep-copied per instance).
      * ``FILE_PATH`` — the on-disk path (a ``pathlib.Path`` or str).
    and optionally override ``_post_load()`` for nested backfills / migrations.
    """

    DEFAULTS: Dict[str, Any] = {}
    FILE_PATH = None  # set by subclass to a Path/str

    def __init__(self) -> None:
        self.settings: Dict[str, Any] = {}
        self._load_or_create_defaults()

    # ------------------------------------------------------------------
    # Load / save
    # ------------------------------------------------------------------

    def _defaults_copy(self) -> Dict[str, Any]:
        """Deep copy of DEFAULTS so callers never mutate the class attribute.
        Defaults are JSON-safe by construction, so a json round-trip is the
        cheapest correct deep copy and avoids importing `copy`."""
        return json.loads(json.dumps(self.DEFAULTS))

    def _load_or_create_defaults(self) -> None:
        path = self.FILE_PATH
        if path and os.path.exists(path):
            try:
                with open(path, "r") as f:
                    loaded = json.load(f)
                if isinstance(loaded, dict):
                    # Top-level merge: defaults provide any missing keys, the
                    # on-disk values win for keys that are present.
                    self.settings = {**self._defaults_copy(), **loaded}
                    self._post_load(loaded)
                    return
            except (json.JSONDecodeError, IOError) as e:
                print(f"{type(self).__name__} load error: {e}, using defaults")
        # Missing / unreadable / non-dict: start from defaults and persist.
        self.settings = self._defaults_copy()
        self._save()

    def _post_load(self, loaded: Dict[str, Any]) -> None:
        """Hook: after a successful top-level merge, backfill nested defaults
        or migrate legacy fields. `self.settings` is the merged dict; `loaded`
        is the raw on-disk dict. Default is a no-op. Override and call
        ``self._save()`` if a migration changed persistable state."""
        pass

    def _save(self) -> None:
        if not self.FILE_PATH:
            return
        try:
            atomic_write_json(self.FILE_PATH, self.settings, indent=2)
        except OSError as e:
            print(f"{type(self).__name__} save error: {e}")

    # ------------------------------------------------------------------
    # Generic flat accessors
    # ------------------------------------------------------------------
    # Domain managers add their own typed getters/setters; these cover the
    # flat-key cases and keep simple managers boilerplate-free.

    def get(self, key: str, default: Any = None) -> Any:
        return self.settings.get(key, default)

    def set(self, key: str, value: Any) -> None:
        self.settings[key] = value
        self._save()
