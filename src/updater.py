# updater.py
# Sealed self-update for the portable single-exe build. No Qt, no app
# imports, no state beyond what the caller passes in — the controller
# spawns a daemon thread around download_update() and routes progress and
# the result through thread_queue, exactly like update_checker.
#
# The shape of an update, end to end:
#   1. update_checker.check_for_update() finds a newer tag and the .exe
#      asset attached to that release.
#   2. download_update() streams the asset to %TEMP%, checking the size and
#      (when GitHub reports one) the SHA-256 digest before it is trusted.
#   3. apply_update() writes a tiny .cmd that waits for THIS process to
#      exit, swaps the new exe over the running one, relaunches it and
#      deletes itself. The app then quits normally.
#
# Failure model: nothing here may raise into the caller. Every function
# returns a plain result (None / False / a message) so a failed update is
# an inconvenience, never a crash — and never a half-replaced exe. The swap
# only ever happens after the download has been fully verified.
#
# Only meaningful for a frozen PyInstaller --onefile build. From a source
# checkout there is no single file to swap, so is_self_updatable() is False
# and the UI falls back to opening the release page.

import hashlib
import os
import subprocess
import sys
import tempfile
from typing import Callable, Optional

try:
    import requests
except Exception:
    requests = None  # type: ignore


# Streamed in 256 KiB blocks: big enough that a ~40 MB exe is a few hundred
# reads, small enough that the progress callback still feels live.
_CHUNK = 256 * 1024

# A release asset that is wildly bigger than the app has to be is a sign
# something is wrong (wrong asset picked up, a redirect to an HTML error
# page that lies about its length). 400 MB is far above a PySide6 onefile
# build and far below anything worth writing to a user's disk by surprise.
_MAX_ASSET_BYTES = 400 * 1024 * 1024

# Open handle on the liveness lock the swap helper waits for. Module-level
# so it survives apply_update() returning -- the whole point is that the
# OS, not us, closes it when this process finally goes away.
_lock_handle = None


def is_self_updatable() -> bool:
    """True when this process is a frozen single-file exe we can replace.

    PyInstaller sets `frozen`; `_MEIPASS` distinguishes a --onefile build
    (unpacked to a temp dir, exe is one self-contained file) from a
    --onedir build, where swapping one file would tear the app in half.
    """
    if not getattr(sys, "frozen", False):
        return False
    if not hasattr(sys, "_MEIPASS"):
        return False
    return os.path.isfile(sys.executable)


def current_exe_path() -> str:
    """Absolute path of the running exe (the file apply_update replaces)."""
    return os.path.abspath(sys.executable)


def _looks_like_our_asset(name: str) -> bool:
    name = (name or "").lower()
    return name.endswith(".exe") and "oscgoespurrr" in name


def pick_exe_asset(assets) -> Optional[dict]:
    """Choose the downloadable .exe from a release's asset list.

    Returns {"name", "url", "size", "sha256"} or None when the release has
    no exe attached (a source-only release, or one still uploading).
    `sha256` is None unless GitHub reported a digest for the asset.
    """
    if not isinstance(assets, (list, tuple)):
        return None
    for asset in assets:
        if not isinstance(asset, dict):
            continue
        name = str(asset.get("name") or "")
        if not _looks_like_our_asset(name):
            continue
        url = str(asset.get("browser_download_url") or "")
        if not url.lower().startswith("https://"):
            continue
        try:
            size = int(asset.get("size") or 0)
        except (TypeError, ValueError):
            size = 0
        digest = str(asset.get("digest") or "")
        sha256 = None
        if digest.lower().startswith("sha256:"):
            candidate = digest.split(":", 1)[1].strip().lower()
            if len(candidate) == 64:
                sha256 = candidate
        return {"name": name, "url": url, "size": size, "sha256": sha256}
    return None


def download_update(asset: dict,
                    progress: Optional[Callable[[int, int], None]] = None,
                    timeout_s: float = 30.0) -> Optional[str]:
    """Download a release asset to a temp file and verify it.

    `progress(done_bytes, total_bytes)` is called as the stream advances;
    total is 0 when the server sends no length. Returns the path to the
    verified file, or None on ANY failure — network, truncation, a size or
    digest mismatch, requests missing. A file that fails verification is
    deleted rather than left around to be run by accident.
    """
    if requests is None or not isinstance(asset, dict):
        return None
    url = str(asset.get("url") or "")
    if not url.lower().startswith("https://"):
        return None
    expected_size = int(asset.get("size") or 0)
    expected_sha = asset.get("sha256")
    if expected_size and expected_size > _MAX_ASSET_BYTES:
        return None

    tmp_path = None
    try:
        resp = requests.get(
            url, timeout=timeout_s, stream=True, allow_redirects=True,
            headers={"User-Agent": "OscGoesPurrr-updater"},
        )
        if getattr(resp, "status_code", 0) != 200:
            return None

        total = expected_size
        if not total:
            try:
                total = int(resp.headers.get("Content-Length") or 0)
            except (TypeError, ValueError):
                total = 0
        if total > _MAX_ASSET_BYTES:
            return None

        fd, tmp_path = tempfile.mkstemp(prefix="OscGoesPurrr_update_",
                                        suffix=".exe")
        hasher = hashlib.sha256()
        done = 0
        with os.fdopen(fd, "wb") as fh:
            for chunk in resp.iter_content(chunk_size=_CHUNK):
                if not chunk:
                    continue
                done += len(chunk)
                # Guard against a server that streams more than it declared
                # (or declared nothing) — never fill the user's disk.
                if done > _MAX_ASSET_BYTES:
                    raise ValueError("asset exceeded the size ceiling")
                hasher.update(chunk)
                fh.write(chunk)
                if progress is not None:
                    try:
                        progress(done, total)
                    except Exception:
                        pass

        # ---- verification. A mismatch here is the whole point of the
        # temp file: we have not touched the installed exe yet.
        if expected_size and done != expected_size:
            raise ValueError(f"size mismatch: got {done}, want {expected_size}")
        if expected_sha and hasher.hexdigest().lower() != expected_sha:
            raise ValueError("sha256 mismatch")
        if done <= 0:
            raise ValueError("empty download")

        return tmp_path
    except Exception:
        if tmp_path:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
        return None


# The swap script: wait for this process to die, replace the exe, relaunch.
#
# "Wait for this process to die" is done with a LOCK FILE, not with
# `tasklist`. Two approaches were tried on real Windows and rejected:
#
#   * `tasklist /FI "PID eq N" | find "N"` — inside a detached, console-less
#     process tasklist exits 0 and prints NOTHING, so `find` matches nothing
#     and the loop concludes the app has already exited. It then swaps and
#     relaunches under the live app, giving the user two running instances
#     fighting over the OSC ports and the Intiface engine. (A bare `find`
#     is separately wrong: Git/MSYS put a Unix `find` ahead of it on PATH.)
#   * "just retry `move` until it succeeds" — the move is not the gate it
#     looks like. Windows let us replace a running exe in testing, so the
#     move can succeed while the app is still up, with the same
#     two-instances result.
#
# The lock file has neither problem: `apply_update` holds an open handle on
# it, Windows refuses to delete a file held open like that, and the handle
# is released by the OS the instant the process ends — whether it exits
# cleanly, is killed, or crashes. `del` + `if exist` are a cmd builtin and
# need no PATH lookup, no pipeline and no console. If the lock never frees
# we do NOT swap: better a skipped update than two live instances.
#
# The delay is `ping -n 2`, not `-n 1 -w 500`. `-w` is a reply timeout, not
# a sleep: pinging loopback once returns instantly, so `-n 1` would burn
# the whole budget in milliseconds. `-n 2` waits ~1s between its two pings.
# `timeout /t` is not usable here — it fails outright when stdin is
# redirected, which it is for a detached process. Called by absolute path,
# because a `ping` that is not Windows' ping would silently remove the wait.
#
# The move still retries after the lock frees: Windows can hold the exe's
# handle briefly after the process object is gone, and an antivirus scan of
# the freshly downloaded file can add a second or two.
#
# Written with CRLF and run by cmd.exe, so it needs no Python at all — by
# the time it matters, our interpreter is gone.
_SWAP_CMD = r"""@echo off
setlocal
set "TARGET=%~1"
set "NEWEXE=%~2"
set "LOCK=%~3"
set "SYS=%SystemRoot%\System32"

rem ---- wait for the app to exit: its lock file cannot be deleted while
rem ---- it holds the handle open (~1s per try, up to ~90s)
set /a TRIES=0
:waitloop
del /q "%LOCK%" >nul 2>&1
if not exist "%LOCK%" goto swap
set /a TRIES+=1
if %TRIES% GEQ 90 goto stillrunning
"%SYS%\ping.exe" -n 2 127.0.0.1 >nul
goto waitloop

rem ---- replace the exe (~1s per try, up to ~30s)
:swap
set /a TRIES=0
:moveloop
move /y "%NEWEXE%" "%TARGET%" >nul 2>&1
if not errorlevel 1 goto relaunch
set /a TRIES+=1
if %TRIES% GEQ 30 goto failed
"%SYS%\ping.exe" -n 2 127.0.0.1 >nul
goto moveloop

:stillrunning
rem The app never let go. Change nothing and leave the download in place
rem rather than swapping the exe out from under a running instance.
echo OscGoesPurrr was still running, so the update was not installed.> "%~dp1OscGoesPurrr_update_failed.txt"
echo Quit it completely and run this file to update by hand:>> "%~dp1OscGoesPurrr_update_failed.txt"
echo %NEWEXE%>> "%~dp1OscGoesPurrr_update_failed.txt"
goto cleanup

:relaunch
start "" "%TARGET%"
goto cleanup

:failed
rem Tell the user where the download went rather than failing silently, and
rem put the note NEXT TO THE APP (%~dp1 is the target exe's folder) -- a
rem note left in our own temp directory is a note nobody ever reads.
echo Could not replace "%TARGET%".> "%~dp1OscGoesPurrr_update_failed.txt"
echo Close OscGoesPurrr and copy this file over it by hand:>> "%~dp1OscGoesPurrr_update_failed.txt"
echo %NEWEXE%>> "%~dp1OscGoesPurrr_update_failed.txt"
start "" "%TARGET%"

:cleanup
del "%~f0"
"""


def apply_update(downloaded_exe: str,
                 target_exe: Optional[str] = None) -> bool:
    """Hand the swap to a detached helper and return.

    The caller must quit the app immediately afterwards: until this process
    exits, Windows will not let the helper overwrite the exe, and the
    helper's retry budget is finite. Returns False (having changed nothing)
    if the helper could not be written or spawned.
    """
    if not downloaded_exe or not os.path.isfile(downloaded_exe):
        return False
    target = os.path.abspath(target_exe or current_exe_path())
    if not os.path.isfile(target):
        return False

    try:
        script_dir = tempfile.mkdtemp(prefix="OscGoesPurrr_swap_")
        script_path = os.path.join(script_dir, "apply_update.cmd")
        with open(script_path, "w", encoding="ascii", newline="\r\n") as fh:
            fh.write(_SWAP_CMD)
        # The liveness lock. Held open deliberately for the rest of this
        # process's life -- the module-level reference is what keeps it
        # from being closed by garbage collection, and the OS releases it
        # when we exit however we exit. See _SWAP_CMD's comment.
        lock_path = os.path.join(script_dir, "running.lock")
        global _lock_handle
        _lock_handle = open(lock_path, "w", encoding="ascii")
        _lock_handle.write("OscGoesPurrr is still running\n")
        _lock_handle.flush()
    except Exception:
        return False

    try:
        # DETACHED_PROCESS + no window: the helper has to outlive us, and a
        # console flashing up during a quit reads as a crash.
        creationflags = 0
        for flag in ("DETACHED_PROCESS", "CREATE_NEW_PROCESS_GROUP",
                     "CREATE_NO_WINDOW"):
            creationflags |= getattr(subprocess, flag, 0)
        # The helper's `start` hands its environment to the new exe. Without
        # the reset, that exe inherits our _PYI_* variables, looks for our
        # unpacked _MEI folder (gone by then — we have exited) and never
        # starts: the swap works but the app does not come back.
        env = dict(os.environ, PYINSTALLER_RESET_ENVIRONMENT="1")
        subprocess.Popen(
            ["cmd.exe", "/c", script_path, target, downloaded_exe, lock_path],
            creationflags=creationflags,
            close_fds=True,
            cwd=script_dir,
            env=env,
        )
        return True
    except Exception:
        try:
            os.unlink(script_path)
        except OSError:
            pass
        return False
