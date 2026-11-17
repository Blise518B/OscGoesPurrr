"""What the Friends facade's parts share (controllers/friends_*.py)."""

import math
import threading
from contextlib import contextmanager
from typing import Any, Dict, FrozenSet, Iterator, Mapping, NamedTuple, Optional

from settings.friends import ME     # you as a friend of yourself, the "Me" row (friends_me.py)

FEATURE_KEY = "feature_friends"
WEB = "__web__"             # the Web remote row: everyone on your web remote link (friends_web.py)

# What the action being handled came through (event_log.VIA_MENU / VIA_PARTY),
# per thread: the avatar menu runs on the OSC thread, the page on the GUI one.
_VIA = threading.local()


@contextmanager
def came_through(via: str) -> Iterator[None]:
    """Everything logged inside -- your entries to friends, and Me's on your
    own shockers, which come straight back in on this side -- came through
    `via` (the log entry's `via`, which Statistics counts by)."""
    was = getattr(_VIA, "v", "")
    _VIA.v = via
    try:
        yield
    finally:
        _VIA.v = was


def coming_through() -> str:
    """What the action being handled on this thread came through ("": the
    page, or not known)."""
    return getattr(_VIA, "v", "")


class Drive(NamedTuple):
    """What one sender drives your toys with: levels by toy name (or
    ALL_TOYS), when it last arrived, the toys it overrides your own output
    on, and the auto modes playing (friend_patterns.anchor records). `syn`
    -- its panel's version for Sync with others as it says it (None: it
    says none); `ver` -- the version this OGP vouches for, which decides
    the newest while you sync everyone (set for every sender, whether you
    sync or not: friends_receive._sync_version); `since` -- when that `ver`
    first arrived (an equal version from two friends: the first one
    wins)."""
    levels: Dict[str, float]
    t: float
    ovr: FrozenSet[str] = frozenset()
    pat: Mapping[str, Dict[str, Any]] = {}
    syn: Optional[int] = None
    since: float = 0.0
    ver: int = 0

    def drives(self) -> bool:
        """Asks for something: a level or an auto mode."""
        return bool(self.pat) or any(v > 0 for v in self.levels.values())


def unit(value: Any) -> float:
    """0..1, anything else (None, NaN, an infinity, text) 0."""
    try:
        v = float(value)
    except (TypeError, ValueError, OverflowError):
        return 0.0
    return max(0.0, min(1.0, v)) if math.isfinite(v) else 0.0


def shocker_label(s: Dict[str, Any]) -> str:
    return str(s.get("name") or f"Shocker {s.get('id')}")


def op_text(op: str, level: int, armed: bool, whose: str = "") -> str:
    """How an operation reads in the log: "beep", "shock 30" -- or, for a
    shock nobody armed, the vibrate it turns into."""
    if op == "beep":
        return "beep"
    if op == "shock" and not armed:
        return f"vibrate {level} ({whose}shocks aren't armed)"
    return f"{op} {level}"
