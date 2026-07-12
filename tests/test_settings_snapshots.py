"""Tests for the launch-time settings snapshots (settings_snapshots.py).

Everything runs on tmp_path with injected `now_ts` values, so nothing
touches the real AppData directory or the wall clock.
"""

import json
from pathlib import Path

from settings_snapshots import (
    BACKUPS_DIRNAME, list_snapshots, make_snapshot, restore_snapshot,
)

# Arbitrary fixed epoch (integral so the strftime/strptime round trip
# through list_snapshots is exact).
TS0 = 1_750_000_000.0


def _write(dir_: Path, name: str, payload) -> Path:
    p = dir_ / name
    p.write_text(json.dumps(payload), encoding="utf-8")
    return p


# ---------------------------------------------------------------- make_snapshot

class TestMakeSnapshot:
    def test_copies_top_level_jsons_only(self, tmp_path):
        _write(tmp_path, "app_settings.json", {"a": 1})
        _write(tmp_path, "profiles.json", {"b": 2})
        (tmp_path / "notes.txt").write_text("not json, not copied")
        (tmp_path / "sessions").mkdir()
        _write(tmp_path / "sessions", "session1.json", {"skip": True})
        snap = make_snapshot(tmp_path, now_ts=TS0)
        assert snap is not None
        snap_dir = Path(snap)
        assert snap_dir.parent.name == BACKUPS_DIRNAME
        assert sorted(p.name for p in snap_dir.iterdir()) == [
            "app_settings.json", "profiles.json"]
        assert json.loads(
            (snap_dir / "app_settings.json").read_text()) == {"a": 1}

    def test_second_snapshot_never_recurses_into_backups(self, tmp_path):
        _write(tmp_path, "app_settings.json", {"a": 1})
        make_snapshot(tmp_path, now_ts=TS0)
        snap2 = make_snapshot(tmp_path, now_ts=TS0 + 60)
        assert sorted(p.name for p in Path(snap2).iterdir()) == [
            "app_settings.json"]

    def test_same_second_collision_appends_suffix(self, tmp_path):
        _write(tmp_path, "a.json", {})
        s1 = make_snapshot(tmp_path, now_ts=TS0)
        s2 = make_snapshot(tmp_path, now_ts=TS0)
        s3 = make_snapshot(tmp_path, now_ts=TS0)
        assert Path(s2).name == Path(s1).name + "-2"
        assert Path(s3).name == Path(s1).name + "-3"

    def test_prune_keeps_newest_keep(self, tmp_path):
        _write(tmp_path, "a.json", {})
        for i in range(7):
            make_snapshot(tmp_path, keep=5, now_ts=TS0 + i * 60)
        snaps = list_snapshots(tmp_path)
        assert len(snaps) == 5
        assert sorted(s["ts"] for s in snaps) == [
            TS0 + i * 60 for i in range(2, 7)]

    def test_empty_dir_returns_none(self, tmp_path):
        assert make_snapshot(tmp_path, now_ts=TS0) is None
        assert not (tmp_path / BACKUPS_DIRNAME).exists()

    def test_missing_dir_returns_none(self, tmp_path):
        assert make_snapshot(tmp_path / "nope", now_ts=TS0) is None


# ---------------------------------------------------------------- list_snapshots

class TestListSnapshots:
    def test_newest_first_with_fields(self, tmp_path):
        _write(tmp_path, "a.json", {})
        s1 = make_snapshot(tmp_path, now_ts=TS0)
        s2 = make_snapshot(tmp_path, now_ts=TS0 + 3600)
        snaps = list_snapshots(tmp_path)
        assert [s["name"] for s in snaps] == [Path(s2).name, Path(s1).name]
        assert snaps[0]["path"] == str(Path(s2))
        assert snaps[0]["ts"] == TS0 + 3600
        assert snaps[1]["ts"] == TS0

    def test_collision_suffix_lists_as_newer(self, tmp_path):
        # Two snapshots in the same second: the "-2" one was made later
        # and must list first.
        _write(tmp_path, "a.json", {})
        s1 = make_snapshot(tmp_path, now_ts=TS0)
        s2 = make_snapshot(tmp_path, now_ts=TS0)
        snaps = list_snapshots(tmp_path)
        assert [s["name"] for s in snaps] == [Path(s2).name, Path(s1).name]

    def test_empty_without_backups_dir(self, tmp_path):
        assert list_snapshots(tmp_path) == []


# ---------------------------------------------------------------- restore_snapshot

class TestRestoreSnapshot:
    def test_round_trip(self, tmp_path):
        f = _write(tmp_path, "app_settings.json", {"color_profile": "aurora"})
        snap = make_snapshot(tmp_path, now_ts=TS0)
        name = Path(snap).name
        # User breaks their config, and a newer build adds a file the
        # snapshot doesn't know about.
        _write(tmp_path, "app_settings.json", {"color_profile": "broken"})
        _write(tmp_path, "new_backend.json", {"added": "later"})
        assert restore_snapshot(tmp_path, name) is True
        assert json.loads(f.read_text()) == {"color_profile": "aurora"}
        # Only files that exist in the snapshot are touched.
        assert json.loads(
            (tmp_path / "new_backend.json").read_text()) == {"added": "later"}

    def test_unknown_name_is_false(self, tmp_path):
        _write(tmp_path, "a.json", {})
        make_snapshot(tmp_path, now_ts=TS0)
        assert restore_snapshot(tmp_path, "20000101-000000") is False

    def test_hostile_or_empty_names_are_false(self, tmp_path):
        _write(tmp_path, "a.json", {})
        make_snapshot(tmp_path, now_ts=TS0)
        assert restore_snapshot(tmp_path, "") is False
        assert restore_snapshot(tmp_path, None) is False
        assert restore_snapshot(tmp_path, "..") is False
        assert restore_snapshot(tmp_path, "../evil") is False
        assert restore_snapshot(tmp_path, "..\\evil") is False


# ---------------------------------------------------------------- review fixes

class TestStatsExcluded:
    def test_stats_json_is_neither_snapshotted_nor_restored(self, tmp_path):
        # stats.json is lifetime usage HISTORY, not settings — restoring
        # last week's config must never rewind a week of statistics.
        _write(tmp_path, "app_settings.json", {"a": 1})
        _write(tmp_path, "stats.json", {"lifetime": "precious"})
        snap = make_snapshot(tmp_path, now_ts=TS0)
        assert sorted(p.name for p in Path(snap).iterdir()) == [
            "app_settings.json"]
        # Even a hand-planted stats.json inside a snapshot dir stays out.
        _write(Path(snap), "stats.json", {"lifetime": "old"})
        _write(tmp_path, "stats.json", {"lifetime": "current"})
        name = Path(snap).name
        assert restore_snapshot(tmp_path, name) is True
        assert json.loads((tmp_path / "stats.json").read_text()) == {
            "lifetime": "current"}


class TestPruneScope:
    def test_foreign_dirs_survive_and_dont_crowd_the_quota(self, tmp_path):
        # The help text invites users into backups/ — a keepsake copy
        # they renamed must neither be rmtree'd (sorts first!) nor count
        # toward the keep=N quota.
        _write(tmp_path, "a.json", {})
        backups = tmp_path / BACKUPS_DIRNAME
        backups.mkdir()
        (backups / "0-golden-config").mkdir()
        _write(backups / "0-golden-config", "a.json", {"keep": "me"})
        (backups / "zzz-notes").mkdir()
        for i in range(4):
            make_snapshot(tmp_path, keep=3, now_ts=TS0 + i)
        assert (backups / "0-golden-config" / "a.json").exists()
        assert (backups / "zzz-notes").is_dir()
        real = [p.name for p in backups.iterdir()
                if p.name not in ("0-golden-config", "zzz-notes")]
        assert len(real) == 3   # quota counts real snapshots only


class TestRestoreAtomicity:
    def test_mid_restore_failure_rolls_back_to_original_state(
            self, tmp_path, monkeypatch):
        # A naive copy loop dying on file N left a silent MIX of old and
        # new settings (e-stim limits from last week, everything else
        # current). Now: pre-read + per-file atomic swap + rollback.
        _write(tmp_path, "a.json", {"live": "a"})
        _write(tmp_path, "b.json", {"live": "b"})
        _write(tmp_path, "c.json", {"live": "c"})
        snap = make_snapshot(tmp_path, now_ts=TS0)
        name = Path(snap).name
        for f in ("a.json", "b.json", "c.json"):
            _write(tmp_path, f, {"live": f + "-new"})

        import settings_snapshots as ss
        real_replace = ss.os.replace
        calls = {"n": 0}

        def flaky_replace(src, dst):
            calls["n"] += 1
            if calls["n"] == 2:
                raise OSError("simulated lock on the second file")
            return real_replace(src, dst)

        monkeypatch.setattr(ss.os, "replace", flaky_replace)
        assert restore_snapshot(tmp_path, name) is False
        monkeypatch.undo()
        # Disk is back to the pre-restore state — no old/new mix.
        for f in ("a.json", "b.json", "c.json"):
            assert json.loads((tmp_path / f).read_text()) == {
                "live": f + "-new"}, f

    def test_successful_restore_still_round_trips(self, tmp_path):
        _write(tmp_path, "a.json", {"v": 1})
        snap = make_snapshot(tmp_path, now_ts=TS0)
        _write(tmp_path, "a.json", {"v": 2})
        assert restore_snapshot(tmp_path, Path(snap).name) is True
        assert json.loads((tmp_path / "a.json").read_text()) == {"v": 1}
