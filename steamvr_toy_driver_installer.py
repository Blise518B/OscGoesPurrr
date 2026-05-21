# steamvr_toy_driver_installer.py
# Lays out the OscGoesPurrr SteamVR toy driver into a per-user folder and
# registers it with SteamVR via %LOCALAPPDATA%\openvr\openvrpaths.vrpath.
# Crucially: no writes inside Steam's install directory, no UAC prompt.
#
# Layout we write at runtime:
#   %LOCALAPPDATA%\OscGoesPurrr\steamvr_driver\oscgoespurrr\
#       driver.vrdrivermanifest
#       bin\win64\driver_oscgoespurrr.dll
#       resources\driver.vrresources
#       resources\icons\<toy>.png   (copies of Images/lovense_icons/)
#
# Source files come from:
#   * The PyInstaller bundle's `_MEIPASS\steamvr_toy_driver\`  (frozen)
#   * The repo's `steamvr_toy_driver\` folder                  (dev)

from __future__ import annotations

import json
import os
import shutil
import sys
from pathlib import Path
from typing import Optional

from utilities import atomic_write_json


# ---- Locations -----------------------------------------------------------

DRIVER_DIRNAME = "oscgoespurrr"          # what SteamVR shows in the log

def _local_appdata() -> Path:
    base = os.environ.get("LOCALAPPDATA")
    if base:
        return Path(base)
    # Fallback for weird environments where LOCALAPPDATA is missing.
    return Path.home() / "AppData" / "Local"


def driver_install_root() -> Path:
    """Folder we lay the entire driver tree into. Per-user, no UAC."""
    return _local_appdata() / "OscGoesPurrr" / "steamvr_driver" / DRIVER_DIRNAME


def openvrpaths_file() -> Path:
    return _local_appdata() / "openvr" / "openvrpaths.vrpath"


def _bundle_root() -> Path:
    """Folder containing the source `steamvr_toy_driver/` tree, whether
    we're running from source or from a PyInstaller bundle."""
    if getattr(sys, "frozen", False):
        # PyInstaller --onefile extracts data files under sys._MEIPASS.
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            return Path(meipass) / "steamvr_toy_driver"
    return Path(__file__).resolve().parent / "steamvr_toy_driver"


def _icons_source_dir() -> Path:
    """Lovense icon PNGs shipped with the app.

    Prefer the pre-resized 64x64 versions in steamvr_toy_driver/icon_assets_64.
    SteamVR's Status window strip silently drops icons that exceed an
    internal size limit (~256px). Falls back to the full-size catalog if
    the resized assets aren't present (older builds / dev tree).
    """
    if getattr(sys, "frozen", False):
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            small = Path(meipass) / "steamvr_toy_driver" / "icon_assets_64"
            if small.is_dir():
                return small
            return Path(meipass) / "Images" / "lovense_icons"
    repo = Path(__file__).resolve().parent
    small = repo / "steamvr_toy_driver" / "icon_assets_64"
    if small.is_dir():
        return small
    return repo / "Images" / "lovense_icons"


# ---- Public API ----------------------------------------------------------

def is_supported() -> bool:
    """Driver is Windows-only (the DLL is built for win64). Other platforms
    silently disable the feature."""
    return sys.platform == "win32"


def driver_dll_path() -> Path:
    return driver_install_root() / "bin" / "win64" / "driver_oscgoespurrr.dll"


def icon_install_dir() -> Path:
    """Where we copy the per-toy PNGs so the driver can hand SteamVR a
    stable absolute path (the PyInstaller temp dir is not stable)."""
    return driver_install_root() / "resources" / "icons"


def resolve_installed_icon_path(icon_filename: Optional[str]) -> Optional[str]:
    """Given a bare `<key>.png` filename, return the absolute path of the
    icon as it lives in the installed driver folder, or None if the icon
    wasn't shipped. Used by the bridge so SteamVR loads from a path that
    survives Python process restart."""
    if not icon_filename:
        return None
    p = icon_install_dir() / icon_filename
    return str(p) if p.is_file() else None


def is_installed() -> bool:
    """True if the driver files are laid out and the openvrpaths entry exists."""
    if not is_supported():
        return False
    if not driver_dll_path().is_file():
        return False
    paths_file = openvrpaths_file()
    if not paths_file.is_file():
        return False
    try:
        data = json.loads(paths_file.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    target = str(driver_install_root())
    ext = data.get("external_drivers") or []
    return any(_paths_eq(p, target) for p in ext)


class InstallError(Exception):
    """Raised by install() with a kind discriminator so callers can show the
    right hint instead of a one-size-fits-all 'missing DLL' message."""
    def __init__(self, kind: str, message: str):
        super().__init__(message)
        self.kind = kind  # 'bundle_missing' | 'dll_locked' | 'copy_failed' | 'register_failed'


def _replace_file_handling_lock(src: Path, dst: Path) -> None:
    """Copy `src` over `dst`. If `dst` is currently loaded by another process
    (the common case: SteamVR has the driver DLL open), use the Windows
    rename-aside trick — renaming a locked file is allowed even when
    overwriting it isn't, so we move it out of the way, then write the new
    file, then try to delete the renamed-aside copy as best-effort cleanup.

    Raises OSError with errno=EBUSY if the file is locked AND can't be
    renamed aside (i.e. another process has it open with deny-rename
    semantics — vrserver doesn't, but this defends against future weirdness).
    """
    dst.parent.mkdir(parents=True, exist_ok=True)
    # Fast path: destination doesn't exist or isn't locked.
    try:
        shutil.copyfile(src, dst)
        return
    except PermissionError:
        pass  # fall through to the rename-aside path

    # Rename-aside path. Pick a stale suffix so a previously-aborted reinstall
    # doesn't leave .old1, .old2, ... lying around in a way that collides.
    stale = dst.with_name(dst.name + ".old")
    # Clean up any prior stale copy first (no-op if not loaded; ignore if it is).
    try:
        if stale.exists():
            stale.unlink()
    except OSError:
        pass
    # Rename the loaded DLL out of the way. THIS works while the file is open
    # on Windows; the loaded process keeps reading from the renamed handle.
    os.replace(dst, stale)
    # Now the original path is free — write the new file.
    shutil.copyfile(src, dst)
    # Best-effort: try to delete the stale copy. If the process still has it
    # open we can't, and that's fine — Windows will let us remove it next
    # time the process closes the handle.
    try:
        stale.unlink()
    except OSError:
        pass


def install(log=None) -> bool:
    """Lay out driver files and register the path with SteamVR. Idempotent.

    Returns True on success. On failure, logs a specific reason via `log`
    and raises nothing (returns False) so the UI can format a message.

    The richer `install_or_raise` variant surfaces the failure kind for
    UI prompts (so we can say "exit SteamVR and try again" specifically
    for the locked-DLL case instead of the generic 'missing' message).
    """
    _log = log if callable(log) else (lambda _m: None)
    try:
        install_or_raise(_log)
        return True
    except InstallError as e:
        _log(f"[steamvr-toys] install failed ({e.kind}): {e}")
        return False


def install_or_raise(_log) -> None:
    if not is_supported():
        raise InstallError("bundle_missing", "non-Windows platform; install skipped")

    src_root = _bundle_root()
    if not src_root.is_dir():
        raise InstallError("bundle_missing",
                           f"driver source folder missing in bundle: {src_root}")

    dst_root = driver_install_root()
    try:
        dst_root.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        raise InstallError("copy_failed",
                           f"could not create {dst_root}: {e}")

    # Copy the static driver tree (manifest, DLL, vrresources, default
    # settings). default.vrsettings pre-binds known Lovense product serials
    # to TrackerRole_Handed so SteamVR's auto-binder accepts the devices
    # into the Status window strip; without it, the "Not autobinding role"
    # log line fires and the device is filtered out of the visible strip.
    for relpath in (
        Path("driver.vrdrivermanifest"),
        Path("bin") / "win64" / "driver_oscgoespurrr.dll",
        Path("resources") / "driver.vrresources",
        Path("resources") / "settings" / "default.vrsettings",
    ):
        src = src_root / relpath
        dst = dst_root / relpath
        if not src.is_file():
            if str(relpath).endswith("driver_oscgoespurrr.dll"):
                raise InstallError("bundle_missing",
                                   f"DLL missing in bundle: {src}")
            continue
        try:
            _replace_file_handling_lock(src, dst)
        except PermissionError as e:
            raise InstallError("dll_locked",
                               f"cannot overwrite {dst} - SteamVR has it open: {e}")
        except OSError as e:
            raise InstallError("copy_failed",
                               f"copy failed {src} -> {dst}: {e}")

    # Copy icons (best-effort) — never raises.
    # First, nuke any stale SteamVR-cached versions (*.<8hexchars>.png).
    # SteamVR creates these on first load and prefers them over the source
    # PNGs forever after, so if the source ever changes (e.g. we ship
    # smaller icons in a later build) the strip keeps rendering the old
    # cached pixels until the cache files are deleted.
    import re
    cache_re = re.compile(r"\.[0-9a-f]{8}\.png$", re.IGNORECASE)
    icons_src = _icons_source_dir()
    icons_dst = icon_install_dir()
    if icons_dst.is_dir():
        for stale in icons_dst.glob("*.png"):
            if cache_re.search(stale.name):
                try:
                    stale.unlink()
                except OSError:
                    pass
    if icons_src.is_dir():
        try:
            icons_dst.mkdir(parents=True, exist_ok=True)
            for png in icons_src.glob("*.png"):
                try:
                    _replace_file_handling_lock(png, icons_dst / png.name)
                except OSError:
                    pass  # individual icon failures are non-fatal
        except OSError as e:
            _log(f"[steamvr-toys] icon copy partially failed: {e}")

    # Register path with SteamVR.
    if not _register_path(dst_root, _log):
        raise InstallError("register_failed",
                           "could not update openvrpaths.vrpath")
    _log(f"[steamvr-toys] driver installed at {dst_root}. "
         "Restart SteamVR to activate.")


def uninstall(log=None, remove_files: bool = False) -> bool:
    """Unregister the driver from openvrpaths.vrpath. Optionally delete the
    laid-out files too. Idempotent."""
    _log = log if callable(log) else (lambda _m: None)
    ok = _unregister_path(driver_install_root(), _log)
    if remove_files:
        try:
            if driver_install_root().is_dir():
                shutil.rmtree(driver_install_root(), ignore_errors=True)
        except OSError as e:
            _log(f"[steamvr-toys] cleanup failed: {e}")
    return ok


# ---- openvrpaths.vrpath surgery -----------------------------------------

def _paths_eq(a: str, b: str) -> bool:
    try:
        return Path(a).resolve(strict=False) == Path(b).resolve(strict=False)
    except (OSError, ValueError):
        return os.path.normcase(os.path.normpath(a)) == os.path.normcase(os.path.normpath(b))


def _register_path(driver_root: Path, log) -> bool:
    paths_file = openvrpaths_file()
    try:
        paths_file.parent.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        log(f"[steamvr-toys] cannot create {paths_file.parent}: {e}")
        return False

    data = _read_paths_file(paths_file, log)
    if data is None:
        # Brand-new file — SteamVR will rewrite the structure on next launch.
        data = {
            "config":   [str(_local_appdata() / "openvr")],
            "external_drivers": [],
            "jsonid":   "vrpathreg",
            "log":      [str(_local_appdata() / "openvr" / "logs")],
            "runtime":  [],
            "version":  1,
        }

    ext = data.get("external_drivers")
    if not isinstance(ext, list):
        ext = []
    target = str(driver_root)
    if not any(_paths_eq(p, target) for p in ext):
        ext.append(target)
    data["external_drivers"] = ext

    return _write_paths_file(paths_file, data, log)


def _unregister_path(driver_root: Path, log) -> bool:
    paths_file = openvrpaths_file()
    if not paths_file.is_file():
        return True
    data = _read_paths_file(paths_file, log)
    if data is None:
        return True
    ext = data.get("external_drivers") or []
    target = str(driver_root)
    filtered = [p for p in ext if not _paths_eq(p, target)]
    if len(filtered) == len(ext):
        return True  # already absent
    data["external_drivers"] = filtered
    return _write_paths_file(paths_file, data, log)


def _read_paths_file(path: Path, log) -> Optional[dict]:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    try:
        data = json.loads(text)
        if isinstance(data, dict):
            return data
    except ValueError as e:
        log(f"[steamvr-toys] openvrpaths.vrpath is malformed: {e}")
    return None


def _write_paths_file(path: Path, data: dict, log) -> bool:
    # Atomic so a crash mid-write can't corrupt openvrpaths.vrpath — a broken
    # one will brick SteamVR's boot. SteamVR's own writer formats with
    # indent=3 and a trailing newline; we keep the indent and let the lack
    # of a trailing newline ride (SteamVR doesn't require it).
    try:
        atomic_write_json(path, data, indent=3)
        return True
    except OSError as e:
        log(f"[steamvr-toys] could not write {path}: {e}")
        return False
