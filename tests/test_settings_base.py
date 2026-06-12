"""Tests for the JsonSettingsManager base (settings/_base.py).

Hardware-free and AppData-free: every manager under test points FILE_PATH at
a tmp_path file, so nothing touches the real settings directory. Covers the
load/merge/save plumbing that the concrete managers (bhaptics, steamvr, and
the new backends) now inherit instead of re-implementing.
"""

import json

from settings._base import JsonSettingsManager


def _mgr(tmp_path, defaults, post_load=None, name="FlatMgr"):
    """Build a one-off JsonSettingsManager subclass writing to tmp_path."""
    path = tmp_path / "settings.json"
    attrs = {"DEFAULTS": defaults, "FILE_PATH": path}
    if post_load is not None:
        attrs["_post_load"] = post_load
    cls = type(name, (JsonSettingsManager,), attrs)
    return cls, path


class TestLoadCreate:
    def test_missing_file_writes_defaults(self, tmp_path):
        cls, path = _mgr(tmp_path, {"a": 1, "b": 2})
        m = cls()
        assert m.settings == {"a": 1, "b": 2}
        # File was created on disk with the defaults.
        assert path.exists()
        assert json.loads(path.read_text()) == {"a": 1, "b": 2}

    def test_defaults_are_deep_copied(self, tmp_path):
        defaults = {"nested": {"x": 1}}
        cls, _ = _mgr(tmp_path, defaults)
        m = cls()
        m.settings["nested"]["x"] = 99
        # Mutating the instance must not bleed into the class default.
        assert defaults["nested"]["x"] == 1

    def test_load_merges_defaults_for_missing_keys(self, tmp_path):
        cls, path = _mgr(tmp_path, {"a": 1, "b": 2})
        path.write_text(json.dumps({"a": 10}))
        m = cls()
        # On-disk value wins for "a"; default fills the missing "b".
        assert m.settings == {"a": 10, "b": 2}

    def test_unknown_on_disk_keys_preserved(self, tmp_path):
        cls, path = _mgr(tmp_path, {"a": 1})
        path.write_text(json.dumps({"a": 5, "extra": "kept"}))
        m = cls()
        assert m.settings["a"] == 5
        # Forward-compat: keys we don't know about are not dropped.
        assert m.settings["extra"] == "kept"

    def test_corrupt_file_falls_back_to_defaults(self, tmp_path):
        cls, path = _mgr(tmp_path, {"a": 1})
        path.write_text("{ not valid json")
        m = cls()
        assert m.settings == {"a": 1}

    def test_non_dict_json_falls_back_to_defaults(self, tmp_path):
        cls, path = _mgr(tmp_path, {"a": 1})
        path.write_text(json.dumps([1, 2, 3]))
        m = cls()
        assert m.settings == {"a": 1}


class TestPostLoad:
    def test_post_load_backfills_without_clobbering(self, tmp_path):
        # Mirrors the bHaptics devices backfill: a nested dict gets new
        # defaults merged in while existing entries are preserved.
        def post_load(self, loaded):
            devs = {"Head": {"on": True}, "Vest": {"on": True}}
            devs.update(loaded.get("devices", {}) or {})
            self.settings["devices"] = devs

        cls, path = _mgr(tmp_path, {"devices": {}}, post_load=post_load)
        path.write_text(json.dumps({"devices": {"Head": {"on": False}}}))
        m = cls()
        # Existing Head entry preserved; new Vest default added.
        assert m.settings["devices"]["Head"] == {"on": False}
        assert m.settings["devices"]["Vest"] == {"on": True}

    def test_post_load_not_called_on_fresh_file(self, tmp_path):
        calls = []

        def post_load(self, loaded):
            calls.append(loaded)

        cls, _ = _mgr(tmp_path, {"a": 1}, post_load=post_load)
        cls()
        # A fresh install writes defaults without invoking the load hook.
        assert calls == []


class TestAccessors:
    def test_get_set_roundtrip(self, tmp_path):
        cls, path = _mgr(tmp_path, {"a": 1})
        m = cls()
        assert m.get("a") == 1
        assert m.get("missing", "fallback") == "fallback"
        m.set("a", 42)
        assert m.get("a") == 42
        # set() persists immediately.
        assert json.loads(path.read_text())["a"] == 42
