"""An avatar's name, from VRChat's own OSC files.

VRChat's OSC never says what the worn avatar is called -- only its id. But
for every avatar it has loaded with OSC on, it keeps a config file,
``OSC\\usr_<you>\\Avatars\\<avatar id>.json`` in its folder
(``%LOCALAPPDATA%Low\\VRChat\\VRChat``; on Linux inside the Proton prefix,
vrchat_log.log_dirs), and that file starts with the avatar's name::

    {"id": "avtr_…", "name": "…", "hash": …, "parameters": [ … ]}

So My Avatar Remote can call an avatar by its name instead of a piece of
its id -- reading only the file's first few KB: the name comes before the
parameter list, which can run to hundreds of KB. The Suits page's contact
check reads that list (avatar_parameters): every parameter the avatar has,
touched or not, cached until the file changes. Nothing is written.
"""

import json
import re
from pathlib import Path
from typing import Dict, FrozenSet, List, Optional, Tuple

import vrchat_log

# An avatar id is "avtr_" and a UUID; anything else (a local test build's
# id, junk) has no file, and must not reach the glob below.
_ID_RE = re.compile(r"^avtr_[0-9a-fA-F-]{8,64}$")
_NAME_RE = re.compile(r'"name"\s*:\s*("(?:[^"\\]|\\.)*")')
_HEAD_BYTES = 4096
NAME_MAX = 80


def osc_dirs(base_dirs: Optional[List[Path]] = None) -> List[Path]:
    """VRChat's OSC folders on this system (candidates, may not exist)."""
    return [Path(d) / "OSC"
            for d in (vrchat_log.log_dirs() if base_dirs is None else base_dirs)]


def _avatar_file(avatar_id: str, base_dirs: Optional[List[Path]]) -> Optional[Tuple[float, Path]]:
    """(mtime, path) of the avatar's file -- the newest, with several VRChat
    accounts on the PC -- or None."""
    aid = str(avatar_id or "").strip()
    if not _ID_RE.match(aid):
        return None
    best = None
    for osc in osc_dirs(base_dirs):
        try:
            for f in osc.glob(f"usr_*/Avatars/{aid}.json"):
                mtime = f.stat().st_mtime
                if best is None or mtime > best[0]:
                    best = (mtime, f)
        except OSError:
            continue
    return best


_params_cache: Dict[Path, Tuple[float, FrozenSet[str]]] = {}


def avatar_parameters(avatar_id: str,
                      base_dirs: Optional[List[Path]] = None) -> Optional[FrozenSet[str]]:
    """Every parameter name the avatar has, as VRChat's file lists them
    (`bOSC/v2/VestFront/0/self`, `owo_suit_Arm_L`, ...) -- None when there
    is no file to read (see avatar_name)."""
    best = _avatar_file(avatar_id, base_dirs)
    if best is None:
        return None
    mtime, path = best
    cached = _params_cache.get(path)
    if cached is not None and cached[0] == mtime:
        return cached[1]
    try:
        data = json.loads(path.read_bytes().decode("utf-8-sig", errors="replace"))
    except (OSError, ValueError):
        return None
    params = data.get("parameters") if isinstance(data, dict) else None
    names = frozenset(str(p["name"]) for p in params or ()
                      if isinstance(p, dict) and isinstance(p.get("name"), str))
    _params_cache[path] = (mtime, names)
    return names


def avatar_name(avatar_id: str, base_dirs: Optional[List[Path]] = None) -> str:
    """The avatar's name as VRChat has it; "" when there is no file for it
    (VRChat not on this PC, OSC never on with that avatar, a test build).
    With several VRChat accounts on the PC, the newest file wins."""
    best = _avatar_file(avatar_id, base_dirs)
    if best is None:
        return ""
    try:
        with open(best[1], "rb") as fh:
            head = fh.read(_HEAD_BYTES).decode("utf-8-sig", errors="replace")
    except OSError:
        return ""
    m = _NAME_RE.search(head)
    params_at = head.find('"parameters"')
    if m is None or 0 <= params_at < m.start():
        return ""           # no name of its own: never a parameter's
    try:
        name = json.loads(m.group(1))
    except ValueError:
        return ""
    return " ".join(str(name).split())[:NAME_MAX]
