"""Your avatar's height over OSC -- the Avatar Remote page's Height box
(Blise's calls, 2026-11-14; docs/ROADMAP.md, "Height on the Avatar
Remote").

VRChat's side (docs.vrchat.com, "OSC Avatar Scaling"):

  * ``/avatar/eyeheight`` -- your eye height in metres. VRChat sends it on
    every change (yours, a world's, an avatar switch) and takes writes from
    0.01 m to 10,000 m -- past its menu's own slider. It only supports
    0.1-100 m: outside that it warns on the HUD and things may break.
  * ``/avatar/eyeheightmin`` / ``max`` -- the world's menu range (0.2 and
    5 m unless the world says otherwise). OSC writes aren't bound by it.
  * ``/avatar/eyeheightscalingallowed`` -- false while the world forbids
    scaling: writes are ignored then.
  * A world's Udon may still enforce its own limits: you hear your own
    value back first, then the world's.
  * VRChat has a bug report about the view jittering while the height
    glides over OSC -- hence a gentle Grow and a gentle send rate.

Everything here is pure: the settings cleaned, the slider's log scale (a
range of 0.1-100 m only works on one), a glide's steps, and
`HeightControl` -- one avatar's height as VRChat reports it, your own height
(what Reset goes back to), a glide and the gentle send rate. It never sends:
each call returns the height to write now (None: nothing). The controller
side is controllers/height_facade.py.
"""

import math
import threading
import time
from typing import Any, Dict, Optional

# The OSC addresses, and the same as the OSC layer hands them on (without
# their leading slash; they sit outside /avatar/parameters/).
EYE_HEIGHT = "/avatar/eyeheight"
KEY_HEIGHT = "avatar/eyeheight"
KEY_MIN = "avatar/eyeheightmin"
KEY_MAX = "avatar/eyeheightmax"
KEY_ALLOWED = "avatar/eyeheightscalingallowed"
KEYS = frozenset({KEY_HEIGHT, KEY_MIN, KEY_MAX, KEY_ALLOWED})

SAFE_MIN, SAFE_MAX = 0.1, 100.0      # what VRChat supports; nothing outside it is ever sent
MENU_MIN, MENU_MAX = 0.2, 5.0        # VRChat's own menu range: the box's range out of the box
MIN_RATIO = 1.1                      # the highest is at least this much above the lowest
SEND_GAP_S = 0.1                     # at most about ten writes a second
OURS_S = 1.5                         # what VRChat says this soon after a write is our echo
# Grow's speed: how long it takes to double (or halve) the height -- a
# height is a scale, so a glide moves by a factor, not by metres
DOUBLE_S_MIN, DOUBLE_S_MAX, DOUBLE_S_DEFAULT = 1.0, 30.0, 4.0

GROW, NOW, RESET = "grow", "now", "reset"
MODES = (GROW, NOW, RESET)

DEFAULTS: Dict[str, Any] = {"on": True, "locked": False, "lo": MENU_MIN, "hi": MENU_MAX,
                            "double_s": DOUBLE_S_DEFAULT}


def num(value: Any) -> Optional[float]:
    """A finite number, or None (a bool isn't one)."""
    if isinstance(value, bool):
        return None
    try:
        v = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return v if math.isfinite(v) else None


def clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def safe(value: float) -> float:
    """Inside what VRChat supports -- the last gate before a write."""
    return clamp(value, SAFE_MIN, SAFE_MAX)


def clean_settings(raw: Any) -> Dict[str, Any]:
    """The box's settings: its switch (on), its lock, the lowest and the
    highest height (inside 0.1-100 m, the highest at least MIN_RATIO above
    the lowest) and Grow's speed."""
    raw = raw if isinstance(raw, dict) else {}
    lo = num(raw.get("lo"))
    hi = num(raw.get("hi"))
    dbl = num(raw.get("double_s"))
    lo = clamp(lo if lo and lo > 0 else MENU_MIN, SAFE_MIN, SAFE_MAX / MIN_RATIO)
    hi = clamp(hi if hi and hi > 0 else MENU_MAX, lo * MIN_RATIO, SAFE_MAX)
    dbl = clamp(dbl if dbl else DOUBLE_S_DEFAULT, DOUBLE_S_MIN, DOUBLE_S_MAX)
    on = raw.get("on", True)
    return {"on": on if isinstance(on, bool) else True, "locked": bool(raw.get("locked")),
            "lo": round(lo, 3), "hi": round(hi, 3), "double_s": round(dbl, 2)}


def with_range(settings: Dict[str, Any], lo: Optional[float] = None,
               hi: Optional[float] = None) -> Dict[str, Any]:
    """`settings` with a new lowest and / or highest. Moving one past the
    other pushes the other along."""
    out = dict(settings)
    if lo is not None:
        out["lo"] = round(clamp(lo, SAFE_MIN, SAFE_MAX / MIN_RATIO), 3)
        out["hi"] = max(out["hi"], round(out["lo"] * MIN_RATIO, 3))
    if hi is not None:
        out["hi"] = round(clamp(hi, SAFE_MIN * MIN_RATIO, SAFE_MAX), 3)
        out["lo"] = min(out["lo"], round(out["hi"] / MIN_RATIO, 3))
    return clean_settings(out)


# --- the slider: a log scale --------------------------------------------------------

def to_slider(height: Optional[float], lo: float, hi: float) -> Optional[float]:
    """Where `height` sits between `lo` and `hi`, 0..1 -- equal steps are
    equal factors (1 m to 2 m is as far as 2 m to 4 m)."""
    if height is None or height <= 0 or lo <= 0 or hi <= lo:
        return None
    return (math.log(clamp(height, lo, hi)) - math.log(lo)) / (math.log(hi) - math.log(lo))


def from_slider(x: float, lo: float, hi: float) -> float:
    """The height at `x` (0..1) between `lo` and `hi` -- the ends exactly."""
    x = clamp(float(x), 0.0, 1.0)
    if x <= 0.0:
        return float(lo)
    if x >= 1.0:
        return float(hi)
    return math.exp(math.log(lo) + x * (math.log(hi) - math.log(lo)))


def fmt(height: Optional[float]) -> str:
    """"1.62 m" (a centimetre under 10 m, a decimetre past it) -- "–" unknown."""
    if height is None:
        return "–"
    return f"{height:.2f} m" if height < 10 else f"{height:.1f} m"


def fmt_speed(double_s: float) -> str:
    """Grow's speed, as said on the page: "×2 in 4 s"."""
    return f"×2 in {double_s:g} s"


# --- a glide ------------------------------------------------------------------------

def glide_step(current: float, target: float, dt: float, double_s: float) -> float:
    """One step of Grow: `dt` seconds' worth of moving from `current`
    toward `target`, by a factor -- doubling (or halving) every `double_s`
    seconds -- never past it."""
    if current <= 0 or target <= 0:
        return target
    step = math.log(2.0) * max(0.0, dt) / max(DOUBLE_S_MIN, double_s)
    a, b = math.log(current), math.log(target)
    if abs(b - a) <= step:
        return target
    return math.exp(a + step if b > a else a - step)


def glide_seconds(current: Optional[float], target: float, double_s: float) -> float:
    """How long Grow takes from `current` to `target`."""
    if current is None or current <= 0 or target <= 0:
        return 0.0
    return abs(math.log2(target / current)) * double_s


class HeightControl:
    """One avatar's height: what VRChat says (`height`), your own height
    (`own`: the newest VRChat said that no write of ours caused -- an
    avatar's own height after a switch, or one you set yourself in
    VRChat's menu -- what Reset goes back to), whether the world allows
    scaling, a glide (Grow) and the gentle send rate.

    Thread-safe: the page, a friend (the link's thread) and the avatar menu
    (the OSC thread) all reach it. It never sends -- `jump` / `reset` /
    `tick` return the height to write now, or None. `tick` (every ~100 ms)
    steps a glide and sends what a jump had to hold back."""

    ANY = object()

    def __init__(self, clock=time.monotonic):
        self._clock = clock
        self._lock = threading.Lock()
        self.height: Optional[float] = None
        self.own: Optional[float] = None
        self.allowed: Optional[bool] = None       # None: VRChat hasn't said
        self.world_min: Optional[float] = None
        self.world_max: Optional[float] = None
        self.double_s = DOUBLE_S_DEFAULT
        self.version = 0                          # changes with whatever the page shows
        self._glide: Optional[Dict[str, Any]] = None   # {at, to, t, by}
        self._pending: Optional[float] = None
        self._sent_t = -1e9

    # -- what VRChat says ------------------------------------------------------------

    def heard(self, key: str, value: Any) -> bool:
        """One of VRChat's height messages. True when whether the world
        allows scaling changed (friends see that)."""
        with self._lock:
            if key == KEY_HEIGHT:
                v = num(value)
                if v is None or v <= 0:
                    return False
                ours = (self._clock() - self._sent_t < OURS_S or self._glide is not None
                        or self._pending is not None)
                changed = v != self.height or (not ours and v != self.own)
                self.height = v
                if not ours:
                    self.own = v
                if changed:
                    self.version += 1
                return False
            if key == KEY_ALLOWED:
                allowed = bool(value) if isinstance(value, (bool, int, float)) else None
                if allowed is None or allowed == self.allowed:
                    return False
                self.allowed = allowed
                if not allowed:
                    self._glide, self._pending = None, None
                self.version += 1
                return True
            if key in (KEY_MIN, KEY_MAX):
                v = num(value)
                if v is None or v <= 0:
                    return False
                if key == KEY_MIN and v != self.world_min:
                    self.world_min = v
                    self.version += 1
                elif key == KEY_MAX and v != self.world_max:
                    self.world_max = v
                    self.version += 1
            return False

    def avatar_changed(self) -> None:
        """Another avatar: its own height is whatever VRChat says next."""
        with self._lock:
            self._glide, self._pending = None, None
            self._sent_t = -1e9
            self.own = None
            self.version += 1

    def gone(self) -> None:
        """VRChat closed: nothing is known any more."""
        with self._lock:
            self._glide, self._pending = None, None
            self.height = self.own = self.allowed = None
            self.world_min = self.world_max = None
            self._sent_t = -1e9
            self.version += 1

    # -- changing it -------------------------------------------------------------------

    def _blocked(self) -> bool:
        return self.allowed is False

    def _send_locked(self, value: float, now: float) -> float:
        self._sent_t = now
        return value

    def jump(self, height: float, by: Any = None) -> Optional[float]:
        """Right away. Ends a glide. Sent now unless a write went out less
        than SEND_GAP_S ago -- then `tick` sends it (the newest wins)."""
        h = num(height)
        with self._lock:
            if h is None or h <= 0 or self._blocked():
                return None
            h = safe(h)
            self._glide = None
            self.version += 1
            now = self._clock()
            if now - self._sent_t >= SEND_GAP_S:
                self._pending = None
                return self._send_locked(h, now)
            self._pending = h
            return None

    def grow(self, height: float, by: Any = None) -> Optional[float]:
        """Glide there, at `double_s` per doubling; `tick` sends the steps.
        Without a height to start from (VRChat hasn't said one), a jump."""
        h = num(height)
        with self._lock:
            if h is None or h <= 0 or self._blocked():
                return None
            h = safe(h)
            start = (self._glide["at"] if self._glide is not None
                     else self._pending if self._pending is not None
                     else self.height if self.height is not None else self.own)
            if start is None:
                start_none = True
            else:
                start_none = False
                self._pending = None
                self._glide = (None if abs(start - h) < 1e-6 else
                               {"at": safe(start), "to": h, "t": self._clock(), "by": by})
                self.version += 1
        if start_none:
            return self.jump(h, by)
        return None

    def reset(self, by: Any = None) -> Optional[float]:
        """Back to your own height, right away (None while it isn't known)."""
        own = self.own
        return None if own is None else self.jump(own, by)

    def stop(self, by: Any = ANY) -> bool:
        """End a glide (only one `by` started, unless ANY) where it is."""
        with self._lock:
            g = self._glide
            if g is None or (by is not HeightControl.ANY and g["by"] != by):
                return False
            self._glide = None
            self.version += 1
            return True

    def stop_friends(self) -> bool:
        """Pause all friends: a glide a friend started stops where it is."""
        with self._lock:
            g = self._glide
            if g is None or g["by"] is None:
                return False
            self._glide = None
            self.version += 1
            return True

    def tick(self) -> Optional[float]:
        """Every ~100 ms: what a jump held back, else a glide's next step."""
        with self._lock:
            now = self._clock()
            if now - self._sent_t < SEND_GAP_S / 2:
                return None
            if self._pending is not None:
                h, self._pending = self._pending, None
                return self._send_locked(h, now)
            g = self._glide
            if g is None:
                return None
            at = glide_step(g["at"], g["to"], now - g["t"], self.double_s)
            g["at"], g["t"] = at, now
            if at == g["to"]:
                self._glide = None
            self.version += 1
            return self._send_locked(safe(at), now)

    # -- what the page shows -----------------------------------------------------------

    def state(self) -> Dict[str, Any]:
        with self._lock:
            g = self._glide
            return {"height": self.height, "own": self.own, "allowed": self.allowed,
                    "world_min": self.world_min, "world_max": self.world_max,
                    "gliding": g is not None, "target": g["to"] if g is not None else None,
                    "by": g["by"] if g is not None else None, "version": self.version}
