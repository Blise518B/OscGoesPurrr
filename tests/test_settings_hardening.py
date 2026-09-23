"""Regression tests for the settings-loader hardening.

The pattern under test: SETTERS always clamped, but LOADERS trusted the
file — so a hand-edited or corrupted JSON could crash app boot (bare int()
in a getter feeding engine config), kill a router tick (unvalidated nested
entry), or be silently clobbered with defaults (losing the user's tuning).

Every manager points FILE_PATH at tmp_path — nothing touches real AppData.
"""

import json

from settings._base import JsonSettingsManager


def _sub(base_cls, tmp_path, name):
    return type(name, (base_cls,), {"FILE_PATH": tmp_path / f"{name}.json"})


# ---------------------------------------------------------------- base


class TestBaseRecovery:
    def test_corrupt_json_is_backed_up_not_destroyed(self, tmp_path):
        cls = _sub(JsonSettingsManager, tmp_path, "CorruptMgr")
        cls.DEFAULTS = {"a": 1}
        path = cls.FILE_PATH
        path.write_text('{"a": 1,,,}')          # trailing-comma hand-edit
        m = cls()
        assert m.settings == {"a": 1}           # running on defaults
        backup = path.with_name(path.name + ".bak")
        assert backup.exists()                  # user's data preserved
        assert backup.read_text() == '{"a": 1,,,}'

    def test_raising_post_load_degrades_to_defaults_not_boot_crash(self, tmp_path):
        # A structurally-malformed (but valid-JSON) file used to propagate
        # a TypeError out of the manager constructor -> app boot loop.
        def bad_post_load(self, loaded):
            raise TypeError("devices is an int")

        cls = _sub(JsonSettingsManager, tmp_path, "PostLoadMgr")
        cls.DEFAULTS = {"a": 1}
        cls._post_load = bad_post_load
        cls.FILE_PATH.write_text(json.dumps({"a": 5, "devices": 3}))
        m = cls()                                # must not raise
        assert m.settings == {"a": 1}

    def test_non_dict_json_backed_up(self, tmp_path):
        cls = _sub(JsonSettingsManager, tmp_path, "ListMgr")
        cls.DEFAULTS = {"a": 1}
        cls.FILE_PATH.write_text(json.dumps([1, 2, 3]))
        m = cls()
        assert m.settings == {"a": 1}
        assert cls.FILE_PATH.with_name(cls.FILE_PATH.name + ".bak").exists()

    def test_degraded_load_backs_up_healthy_file_before_first_save(self, tmp_path):
        # A transient READ failure at boot runs the session on defaults;
        # the first later save (a settings edit, the quit-time save) must
        # preserve the possibly-healthy on-disk file before overwriting it
        # with the defaults-based state.
        cls = _sub(JsonSettingsManager, tmp_path, "DegMgr")
        cls.DEFAULTS = {"a": 1}
        cls.FILE_PATH.write_text(json.dumps({"a": 42}))
        m = cls()                          # healthy load
        m._degraded_load = True            # simulate boot-time read failure
        m.set("a", 2)                      # first save while degraded
        backup = cls.FILE_PATH.with_name(cls.FILE_PATH.name + ".bak")
        assert json.loads(backup.read_text()) == {"a": 42}   # preserved
        assert json.loads(cls.FILE_PATH.read_text())["a"] == 2
        m.set("a", 3)                      # later saves don't re-backup
        assert json.loads(backup.read_text()) == {"a": 42}
