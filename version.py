# OscGoesPurrr - Dynamic Version Module
# Version is derived from the commit count on `main` (so it never shrinks
# when switching branches). On non-main branches, the branch name and the
# number of commits ahead of `main` are appended.
# Format: {base_version}.{main_commit_count}[-{branch}({ahead_of_main})]
# Examples:
#   1.0.51            (on main)
#   1.0.51-dev(3)     (on dev, 3 commits ahead of main)
#   1.0.51-fix-foo(2) (on fix/foo, slashes replaced with dashes)
#
# Frozen (PyInstaller) builds: build.bat writes `_version_baked.py` next to
# this module before running PyInstaller and removes it during cleanup. When
# that file is bundled into the exe, the import below short-circuits the git
# lookups — important because each subprocess.run on a --windowed exe would
# otherwise flash a console window at startup.

import re
import subprocess

BASE_VERSION = "1.1"
RELEASE_BRANCH = "main"


def _run_git(args: list[str]) -> str:
    # CREATE_NO_WINDOW keeps a console from flashing when this runs under a
    # parent process without a console (e.g. pythonw.exe). Defined as 0 on
    # non-Windows, where subprocess ignores creationflags anyway.
    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        result = subprocess.run(
            ["git", *args],
            capture_output=True,
            text=True,
            timeout=5,
            creationflags=creationflags,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except Exception:
        pass
    return ""


def _get_main_commit_count() -> int:
    # Prefer the local main ref; fall back to origin/main, then HEAD.
    for ref in (RELEASE_BRANCH, f"origin/{RELEASE_BRANCH}", "HEAD"):
        out = _run_git(["rev-list", "--count", ref])
        if out.isdigit():
            return int(out)
    return 0


def _get_current_branch() -> str:
    name = _run_git(["rev-parse", "--abbrev-ref", "HEAD"])
    # Detached HEAD returns "HEAD" — treat as no branch suffix.
    if not name or name == "HEAD":
        return ""
    return name


def _get_ahead_of_main() -> int:
    # Commits reachable from HEAD but not from main. Try local main, then origin/main.
    for ref in (RELEASE_BRANCH, f"origin/{RELEASE_BRANCH}"):
        out = _run_git(["rev-list", "--count", f"{ref}..HEAD"])
        if out.isdigit():
            return int(out)
    return 0


def _sanitize_branch(name: str) -> str:
    # Keep alnum, dot, underscore, dash; collapse everything else to a dash.
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", name).strip("-")
    return cleaned


def _get_git_short_hash() -> str:
    return _run_git(["rev-parse", "--short", "HEAD"])


def _resolve_from_git() -> tuple[str, str]:
    commit_count = _get_main_commit_count()
    branch = _get_current_branch()
    short_hash = _get_git_short_hash()

    if branch and branch != RELEASE_BRANCH:
        ahead = _get_ahead_of_main()
        suffix = f"-{_sanitize_branch(branch)}({ahead})"
    else:
        suffix = ""
    return f"{BASE_VERSION}.{commit_count}{suffix}", short_hash


try:
    from _version_baked import VERSION as __version__, SHORT_HASH as _SHORT_HASH
except ImportError:
    __version__, _SHORT_HASH = _resolve_from_git()

if _SHORT_HASH:
    __version_full__ = f"{__version__} ({_SHORT_HASH})"
else:
    __version_full__ = __version__
