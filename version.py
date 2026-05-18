# OscGoesPurrr - Dynamic Version Module
# Version is derived from Git commit count on the current branch.
# Format: {base_version}.{commit_count}
# Example: 1.0.47 (if 47 commits exist)

BASE_VERSION = "1.1"

def _get_git_commit_count() -> int:
    """Return the number of commits on the current branch."""
    try:
        import subprocess
        result = subprocess.run(
            ["git", "rev-list", "--count", "HEAD"],
            capture_output=True,
            text=True,
            timeout=5
        )
        if result.returncode == 0:
            return int(result.stdout.strip())
    except Exception:
        pass
    return 0


def _get_git_short_hash() -> str:
    """Return the short commit hash of HEAD."""
    try:
        import subprocess
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            timeout=5
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except Exception:
        pass
    return ""


# Compute version at import time
_COMMIT_COUNT = _get_git_commit_count()
_SHORT_HASH = _get_git_short_hash()

__version__ = f"{BASE_VERSION}.{_COMMIT_COUNT}"

if _SHORT_HASH:
    __version_full__ = f"{__version__} ({_SHORT_HASH})"
else:
    __version_full__ = __version__