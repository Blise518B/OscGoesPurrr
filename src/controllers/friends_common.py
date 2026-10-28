"""What the Friends facade's parts share (controllers/friends_*.py)."""

from typing import Any, Dict, FrozenSet, Mapping, NamedTuple, Optional

FEATURE_KEY = "feature_friends"
SELF = "__self__"           # you, for "Both of us": your own toys and shockers
ME = "__me__"               # you as a friend of yourself, the "Me" row (friends_me.py)
WEB = "__web__"             # the Web remote row: everyone on your web remote link (friends_web.py)


class Drive(NamedTuple):
    """What one sender drives your toys with: levels by toy name (or
    ALL_TOYS), when it last arrived, the toys it overrides your own output
    on, and the auto modes playing (friend_patterns.anchor records). `syn`
    -- its shared panel's version while it syncs with the others (None: on
    its own); `since` -- when that version first arrived (an equal version
    from two friends: the first one wins)."""
    levels: Dict[str, float]
    t: float
    ovr: FrozenSet[str] = frozenset()
    pat: Mapping[str, Dict[str, Any]] = {}
    syn: Optional[int] = None
    since: float = 0.0

    def drives(self) -> bool:
        """Asks for something: a level or an auto mode."""
        return bool(self.pat) or any(v > 0 for v in self.levels.values())


def unit(value: Any) -> float:
    """0..1, anything else (None, NaN, text) 0."""
    try:
        v = float(value)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, min(1.0, v)) if v == v else 0.0


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
