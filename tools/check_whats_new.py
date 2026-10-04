"""release.bat's look at the in-app "What's new" notes (src/whats_new.py).

The notes are filed under the version they ship as, and the window opens
once for every install that updates to it. So, for the version about to
be published:

    exit 0   it has notes -- updaters will be shown them
    exit 1   it has none -- nothing opens after this update (fine for a
             small fix, worth a second look for anything a user notices)
    exit 2   the newest notes sit under a LATER version -- they would
             never be shown; file them under this one or bump VERSION

Usage: python tools/check_whats_new.py <version>
"""
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "src"))

import whats_new  # noqa: E402
from update_checker import compare_versions  # noqa: E402


def check(version: str) -> int:
    if not whats_new.RELEASES:
        return 1
    order = compare_versions(whats_new.RELEASES[0].version, version)
    if order is None or order > 0:
        return 2
    return 0 if order == 0 else 1


if __name__ == "__main__":
    sys.exit(check(sys.argv[1] if len(sys.argv) > 1 else ""))
