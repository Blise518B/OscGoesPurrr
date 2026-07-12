# settings_snapshots.py
# Sealed launch-time settings backups. main.py calls make_snapshot()
# exactly ONCE per launch, before ModeManager loads (so a schema
# migration can never eat the only copy of the pre-migration files);
# there is deliberately no background process, watcher, or timer.
#
# Layout on disk:
#   <appdata>/backups/<YYYYMMDD-HHMMSS>[-N]/   one dir per snapshot
#       app_settings.json, profiles.json, ...  every top-level *.json
#
# Failure model: fully defensive. Any OSError prints and returns
# None/False — a broken backup must never take the app down with it.

import os
import shutil
import time
from pathlib import Path
from typing import Dict, List, Optional

BACKUPS_DIRNAME = "backups"
_TS_FORMAT = "%Y%m%d-%H%M%S"

# Top-level *.json files that live in AppData but are NOT settings.
# stats.json is the user's lifetime usage history — "restore my settings
# from Tuesday" must never silently rewind a week of statistics.
_EXCLUDE = frozenset({"stats.json"})


def _is_snapshot_name(name: str) -> bool:
    """True only for names this module itself generates (timestamp with
    an optional "-N" collision suffix). Pruning must never touch a
    user-created keepsake dir inside backups/."""
    for candidate in (name, name.rsplit("-", 1)[0]):
        try:
            time.strptime(candidate, _TS_FORMAT)
            return True
        except ValueError:
            continue
    return False


def make_snapshot(appdata_dir, keep: int = 5,
                  now_ts: Optional[float] = None) -> Optional[str]:
    """Copy every top-level *.json in `appdata_dir` into a fresh
    `backups/<timestamp>/` dir, then prune the oldest snapshots beyond
    `keep`. Subdirectories (sessions/, backups/ itself) are never
    descended into. Returns the new snapshot's path, or None when there
    was nothing to copy or anything went wrong."""
    try:
        base = Path(appdata_dir)
        # Top-level settings files only — the glob can't match the
        # sessions/ or backups/ dirs, and is_file() drops any oddly
        # named directory that would.
        files = sorted(p for p in base.glob("*.json")
                       if p.is_file() and p.name not in _EXCLUDE)
        if not files:
            return None
        ts = float(now_ts) if now_ts is not None else time.time()
        stamp = time.strftime(_TS_FORMAT, time.localtime(ts))
        backups = base / BACKUPS_DIRNAME
        backups.mkdir(parents=True, exist_ok=True)
        dest = backups / stamp
        suffix = 2
        while dest.exists():  # same-second relaunch → "-2", "-3", ...
            dest = backups / f"{stamp}-{suffix}"
            suffix += 1
        dest.mkdir()
        for f in files:
            shutil.copy2(f, dest / f.name)
        _prune(backups, keep)
        return str(dest)
    except OSError as e:
        print(f"[snapshots] snapshot failed: {e}")
        return None


def _prune(backups: Path, keep: int) -> None:
    """Delete the oldest snapshot dirs beyond `keep`. Name order is
    chronological (zero-padded timestamp names; a "-N" collision suffix
    sorts after its base stamp). ONLY dirs whose names this module
    generated are counted or deleted — the help text invites users into
    the folder, and a hand-renamed "0-golden-config" keepsake must
    neither be rmtree'd nor crowd real snapshots out of the quota."""
    snaps = sorted((p for p in backups.iterdir()
                    if p.is_dir() and _is_snapshot_name(p.name)),
                   key=lambda p: p.name)
    excess = max(0, len(snaps) - max(0, int(keep)))
    for old in snaps[:excess]:
        shutil.rmtree(old, ignore_errors=True)


def _snapshot_ts(p: Path) -> float:
    """Best-effort epoch timestamp for a snapshot dir: parsed from the
    name (with or without the "-N" collision suffix), falling back to
    the dir's mtime."""
    name = p.name
    for candidate in (name, name.rsplit("-", 1)[0]):
        try:
            return time.mktime(time.strptime(candidate, _TS_FORMAT))
        except ValueError:
            continue
    try:
        return p.stat().st_mtime
    except OSError:
        return 0.0


def list_snapshots(appdata_dir) -> List[Dict]:
    """All snapshots as [{"name", "path", "ts"}, ...], newest first.
    Empty list when there are none (or on any error)."""
    out: List[Dict] = []
    try:
        backups = Path(appdata_dir) / BACKUPS_DIRNAME
        if not backups.is_dir():
            return []
        for p in backups.iterdir():
            if p.is_dir():
                out.append({"name": p.name, "path": str(p),
                            "ts": _snapshot_ts(p)})
        # Same-second collisions tiebreak on name, so "-2" (made later)
        # still lists before its base stamp.
        out.sort(key=lambda d: (d["ts"], d["name"]), reverse=True)
    except OSError as e:
        print(f"[snapshots] list failed: {e}")
        return []
    return out


def restore_snapshot(appdata_dir, name: str) -> bool:
    """Copy snapshot `name`'s files back over `appdata_dir`. Only files
    that exist in the snapshot are touched — settings files added by a
    newer build survive a restore untouched. Returns False for an
    unknown/hostile name, an empty snapshot, or any OSError.

    All-or-nothing: a naive copy loop that dies on file N would leave a
    silent MIX of old and new settings on disk (safety-relevant — e-stim
    limits could quietly revert while everything else stays current). So:
    every snapshot file is read into memory first (any read failure
    aborts before disk is touched), each live file's current bytes are
    stashed, writes go through a temp file + atomic os.replace, and a
    mid-sequence write failure rolls the already-replaced files back."""
    try:
        name = str(name or "")
        # A snapshot name is always a single path component; refuse
        # anything that could escape the backups dir.
        if not name or name in (".", "..") or "/" in name or "\\" in name:
            return False
        base = Path(appdata_dir)
        snap = base / BACKUPS_DIRNAME / name
        if not snap.is_dir():
            return False
        files = [p for p in snap.glob("*.json")
                 if p.is_file() and p.name not in _EXCLUDE]
        if not files:
            return False

        # Phase 1 — read everything up front: snapshot contents and the
        # current live bytes (for rollback). No disk mutation yet.
        payloads = {f.name: f.read_bytes() for f in files}
        originals = {}
        for fname in payloads:
            live = base / fname
            originals[fname] = live.read_bytes() if live.exists() else None

        # Phase 2 — atomic per-file swaps, with best-effort rollback if
        # any single swap fails.
        def _atomic_write(target: Path, data: bytes) -> None:
            tmp = target.with_name(target.name + ".tmp-restore")
            with open(tmp, "wb") as fh:
                fh.write(data)
                fh.flush()
                try:
                    os.fsync(fh.fileno())
                except OSError:
                    pass
            os.replace(tmp, target)

        done: List[str] = []
        try:
            for fname, data in payloads.items():
                _atomic_write(base / fname, data)
                done.append(fname)
        except OSError as e:
            print(f"[snapshots] restore failed on {fname!r} ({e}) — "
                  f"rolling back {len(done)} already-restored file(s)")
            for rb in done:
                try:
                    if originals[rb] is None:
                        (base / rb).unlink(missing_ok=True)
                    else:
                        _atomic_write(base / rb, originals[rb])
                except OSError as rb_err:
                    print(f"[snapshots] ROLLBACK FAILED for {rb!r}: "
                          f"{rb_err} — restore that file by hand from "
                          f"{snap}")
            return False
        return True
    except OSError as e:
        print(f"[snapshots] restore failed: {e}")
        return False
