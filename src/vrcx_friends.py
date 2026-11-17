"""Your VRChat friends, read from VRCX's database -- read-only, on request.

VRCX (the VRChat companion app) keeps an SQLite database at
``%APPDATA%\\VRCX\\VRCX.sqlite3`` (``~/.config/VRCX`` on Linux). Its friend
list is one table per VRChat account that has logged in to VRCX, named
after that account's user id without its ``_`` and dashes::

    usr<32 hex digits>_friend_log_current (user_id, display_name,
                                           trust_level, friend_number)

(checked against a real VRCX database, 2026-11-14). We read only
``user_id`` and ``display_name`` from those tables, of every account in
the file, and nothing else.

The rules (the Friends page's VRChat account picker is the only caller):

* only when the user clicks *Import from VRCX* -- never at launch, never in
  the background;
* a read-only connection (an SQLite URI with ``mode=ro``): nothing is ever
  written, and no journal is created next to VRCX's file;
* VRCX may hold the file open while it runs -- a reader is fine beside it,
  and a moment when it's locked is a "busy, try again", never a wait that
  freezes the window;
* what comes back stays in memory: nothing here writes a file or a log
  line with anyone's name or id.

Sealed: no Qt, no threads.
"""

import os
import re
import sqlite3
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import quote

from vrchat_log import clean_display_name, clean_user_id

# VRCX's friend tables (one per VRChat account that logged in to VRCX).
_TABLE_RE = re.compile(r"^usr[0-9a-fA-F]{32}_friend_log_current$")
# How long to wait for a lock VRCX holds before saying it's busy.
_BUSY_TIMEOUT_S = 0.5


def default_path() -> Optional[Path]:
    """Where VRCX keeps its database on this system (may not exist)."""
    if sys.platform == "win32":
        base = os.environ.get("APPDATA")
        return Path(base) / "VRCX" / "VRCX.sqlite3" if base else None
    return Path.home() / ".config" / "VRCX" / "VRCX.sqlite3"


def installed(path: Optional[Path] = None) -> bool:
    """Whether VRCX's database is on this PC (a look at the folder, nothing
    read)."""
    path = default_path() if path is None else path
    try:
        return bool(path) and Path(path).is_file()
    except OSError:
        return False


def _ro_uri(path: Path) -> str:
    return "file:" + quote(Path(path).resolve().as_posix(), safe="/:") + "?mode=ro"


def read_friends(path: Optional[Path] = None) -> Dict[str, Any]:
    """Your VRChat friends as VRCX knows them.

    Returns ``{"state": ..., "friends": [(user id, display name)]}``, the
    friends by name, each id once. ``state`` is ``ok``; ``missing`` (no
    VRCX on this PC); ``busy`` (VRCX has the file locked right now); ``none``
    (VRCX is there but has no friend list yet -- never logged in); or
    ``error`` (unreadable), with ``error`` saying why. Never raises."""
    path = default_path() if path is None else Path(path)
    if not path or not installed(path):
        return {"state": "missing", "friends": []}
    try:
        con = sqlite3.connect(_ro_uri(path), uri=True, timeout=_BUSY_TIMEOUT_S)
    except sqlite3.Error as e:
        return {"state": "error", "friends": [], "error": str(e)}
    try:
        tables = [r[0] for r in con.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'")
            if _TABLE_RE.match(str(r[0] or ""))]
        found: Dict[str, str] = {}
        for table in tables:
            # the table's name is checked against _TABLE_RE above: safe to quote in
            for uid, name in con.execute(
                    f'SELECT user_id, display_name FROM "{table}"'):
                uid, name = clean_user_id(uid), clean_display_name(name)
                if uid and name and uid not in found:
                    found[uid] = name
    except sqlite3.OperationalError as e:
        text = str(e).lower()
        state = "busy" if ("locked" in text or "busy" in text) else "error"
        return {"state": state, "friends": [], "error": str(e)}
    except sqlite3.Error as e:
        return {"state": "error", "friends": [], "error": str(e)}
    finally:
        con.close()
    if not tables:
        return {"state": "none", "friends": []}
    friends: List[Tuple[str, str]] = sorted(found.items(), key=lambda kv: kv[1].casefold())
    return {"state": "ok", "friends": friends}
