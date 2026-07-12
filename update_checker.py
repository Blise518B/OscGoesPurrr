# update_checker.py
# Sealed one-shot GitHub release check. No state, no retries, no threads
# of its own — the controller spawns a daemon thread around
# check_for_update() and routes the result through thread_queue.
#
# Failure model: this module must NEVER raise and NEVER block startup.
# Any problem — requests not installed, network down, GitHub rate limit,
# malformed JSON, junk version tags — collapses to a plain None so the
# caller can decide whether to mention it (manual check) or stay silent
# (the automatic launch check).

from typing import Optional, Tuple

try:
    import requests
    _REQUESTS_AVAILABLE = True
except Exception:
    requests = None  # type: ignore
    _REQUESTS_AVAILABLE = False


GITHUB_LATEST_RELEASE_URL = (
    "https://api.github.com/repos/Blise518B/OscGoesPurrr/releases/latest"
)


def _parse_version(s) -> Optional[Tuple[int, ...]]:
    """Parse a version string into a comparable tuple of ints.

    Tolerates a leading "v"/"V" ("v1.2.3") and build suffixes after the
    numeric core ("1.2.51-dev(3)" compares as (1, 2, 51)). Anything that
    doesn't yield at least one dotted integer — junk, empty, None —
    returns None. Pure; exposed for tests.
    """
    if not isinstance(s, str):
        return None
    s = s.strip()
    if s[:1] in ("v", "V"):
        s = s[1:]
    # Keep only the dotted numeric prefix: dev/branch suffixes ("-dev(3)",
    # "+build") never take part in the comparison.
    for sep in ("-", "+", " "):
        s = s.split(sep, 1)[0]
    if not s:
        return None
    try:
        return tuple(int(part) for part in s.split("."))
    except ValueError:
        return None


def _pad(a: Tuple[int, ...], b: Tuple[int, ...]):
    """Right-pad the shorter tuple with zeros so "1.2" == "1.2.0"."""
    n = max(len(a), len(b))
    return a + (0,) * (n - len(a)), b + (0,) * (n - len(b))


def check_for_update(current_version: str,
                     timeout_s: float = 5.0) -> Optional[dict]:
    """Ask GitHub for the latest release and compare it to ours.

    Returns {"available": bool, "latest": str, "url": str} — `latest` is
    the release tag without its leading "v", `url` the release page —
    or None on ANY failure (no network, rate-limited, junk tag, junk
    current version, requests missing). Blocking (one HTTPS round-trip,
    bounded by `timeout_s`); call it off the GUI thread.
    """
    if requests is None:
        return None
    try:
        resp = requests.get(
            GITHUB_LATEST_RELEASE_URL,
            timeout=timeout_s,
            headers={
                # Bare API requests without a UA get rejected by GitHub.
                "Accept": "application/vnd.github+json",
                "User-Agent": "OscGoesPurrr-update-check",
            },
        )
        if getattr(resp, "status_code", 0) != 200:
            return None
        payload = resp.json()
        if not isinstance(payload, dict):
            return None
        tag = str(payload.get("tag_name") or "")
        url = str(payload.get("html_url") or "")
        latest = _parse_version(tag)
        current = _parse_version(current_version)
        if latest is None or current is None:
            return None
        latest_p, current_p = _pad(latest, current)
        return {
            "available": latest_p > current_p,
            "latest": tag[1:] if tag[:1] in ("v", "V") else tag,
            "url": url,
        }
    except Exception:
        # Deliberately broad: a failed update check must never surface
        # as anything but "no result".
        return None
