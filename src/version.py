# OscGoesPurrr - Version Module
#
# Public releases carry a hand-set version that matches their git tag:
# VERSION = "0.9.0" ships as the release tagged `v0.9.0`. The launch-time
# update check compares this string against the newest tag on GitHub, so
# the two MUST agree -- bump VERSION in the same commit you tag.
#
# Running from a checkout that is not the release branch appends the branch
# name and how many commits it sits ahead of that branch:
#   0.9.0              (on the release branch)
#   0.9.0-dev(3)       (on dev, 3 commits ahead)
# The suffix is cosmetic. update_checker._parse_version() stops at the
# first "-", so a suffixed build still compares as plain (0, 9, 0) and a
# dev checkout is never told it is out of date against its own release.
#
# Frozen (PyInstaller) builds: build_OGP.bat writes `_version_baked.py` next
# to this module before running PyInstaller and removes it during cleanup.
# When that file is bundled into the exe, the import below short-circuits
# the git lookups -- important because each subprocess.run on a --windowed
# exe would otherwise flash a console window at startup.

import re
import subprocess

VERSION = "0.10.0"
RELEASE_BRANCH = "release/lite"
# Branches that print a bare version. `release/lite` is where releases are
# cut; `main` is what a clone of the public repo is on (release.bat
# publishes each release there as a single squashed commit).
UNSUFFIXED_BRANCHES = (RELEASE_BRANCH, "main")


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


def _get_current_branch() -> str:
    name = _run_git(["rev-parse", "--abbrev-ref", "HEAD"])
    # Detached HEAD returns "HEAD" — treat as no branch suffix.
    if not name or name == "HEAD":
        return ""
    return name


def _get_ahead_of_release() -> int:
    # Commits reachable from HEAD but not from the release branch.
    for ref in (RELEASE_BRANCH, f"origin/{RELEASE_BRANCH}"):
        out = _run_git(["rev-list", "--count", f"{ref}..HEAD"])
        if out.isdigit():
            return int(out)
    return 0


def _commit_count() -> int:
    """Total commits on HEAD — the `b<n>` build number every 518 app shows
    beside its version. 0 when git isn't available."""
    out = _run_git(["rev-list", "--count", "HEAD"])
    return int(out) if out.isdigit() else 0


def _sanitize_branch(name: str) -> str:
    # Keep alnum, dot, underscore, dash; collapse everything else to a dash.
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", name).strip("-")
    return cleaned


def _resolve_from_git() -> tuple[str, str, int]:
    branch = _get_current_branch()
    short_hash = _run_git(["rev-parse", "--short", "HEAD"])
    build = _commit_count()

    if branch and branch not in UNSUFFIXED_BRANCHES:
        ahead = _get_ahead_of_release()
        suffix = f"-{_sanitize_branch(branch)}({ahead})"
    else:
        suffix = ""
    return f"{VERSION}{suffix}", short_hash, build


try:
    from _version_baked import (
        VERSION as __version__,
        SHORT_HASH as _SHORT_HASH,
        BUILD as _BUILD,
    )
except Exception:
    # Broad on purpose: a missing baked file (normal source-tree runs)
    # raises ImportError, but a truncated/corrupt one left behind by an
    # interrupted build raises SyntaxError/ValueError/ImportError. Either
    # way fall back to the live git lookup rather than letting
    # `import version` crash -- that would take down both the app at
    # startup and the build's own version query (which would then name the
    # exe "OscGoesPurrr_.exe").
    __version__, _SHORT_HASH, _BUILD = _resolve_from_git()

if _SHORT_HASH:
    __version_full__ = f"{__version__} ({_SHORT_HASH})"
else:
    __version_full__ = __version__


def build_number() -> int:
    """Commit count behind this build -- the `b<build>` every 518 app shows
    beside its version. 0 when git wasn't available at build time."""
    try:
        return int(_BUILD)
    except (TypeError, ValueError):
        return 0
