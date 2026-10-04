"""Turn the app's green into another colour.

The 518 chrome is one hue -- the green -- at many lightnesses: the accent,
the frame line, the dark tint behind accent text, the faint cast in the
surfaces and the text. Rotating every one of those tokens by the same
angle recolours the whole UI and keeps what makes it read: which token is
brighter than which.

The rotation happens in OKLCH, where "the same lightness" means the same
to the eye. A plain HSV turn would not do: the accent green is a bright
colour, and the blue or red at that same HSV value is a dark one -- accent
text would stop being readable on the dark surfaces. Not every hue can be
as saturated as the green at the green's lightness either (there is no
blue that bright and that vivid), so a token that falls outside sRGB
first looks for the nearest lightness that can hold most of its
saturation, and only then gives saturation up.

Pure maths, no Qt and no project imports: `constants.py` runs this at
import, before anything else exists.
"""
from __future__ import annotations

import math
from functools import lru_cache
from typing import Dict, Mapping, Optional, Tuple

# How far a token's lightness may move (OKLab L, 0..1) to keep its
# saturation at the new hue, and how much of the saturation counts as
# "kept". The accent is the one token this matters for: at blue it lands
# near the palette's own vibrant blue instead of a washed-out pastel.
_L_SEARCH = 0.14
_L_STEP = 0.01
_KEEP_CHROMA = 0.8
# Below this chroma a colour is a grey and has no hue to turn.
_NEUTRAL_CHROMA = 1e-4


def _to_linear(c: float) -> float:
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def _to_srgb(c: float) -> float:
    return 12.92 * c if c <= 0.0031308 else 1.055 * (c ** (1 / 2.4)) - 0.055


def _cbrt(x: float) -> float:
    return math.copysign(abs(x) ** (1 / 3), x)


def to_oklch(hex_color: str) -> Tuple[float, float, float]:
    """`#rrggbb` -> (lightness 0..1, chroma, hue in degrees 0..360)."""
    s = hex_color.lstrip("#")
    r, g, b = (_to_linear(int(s[i:i + 2], 16) / 255.0) for i in (0, 2, 4))
    l_ = _cbrt(0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b)
    m_ = _cbrt(0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b)
    s_ = _cbrt(0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b)
    L = 0.2104542553 * l_ + 0.7936177850 * m_ - 0.0040720468 * s_
    a = 1.9779984951 * l_ - 2.4285922050 * m_ + 0.4505937099 * s_
    bb = 0.0259040371 * l_ + 0.7827717662 * m_ - 0.8086757660 * s_
    return L, math.hypot(a, bb), math.degrees(math.atan2(bb, a)) % 360.0


def _linear_rgb(L: float, C: float, h: float) -> Tuple[float, float, float]:
    a = C * math.cos(math.radians(h))
    b = C * math.sin(math.radians(h))
    l_ = (L + 0.3963377774 * a + 0.2158037573 * b) ** 3
    m_ = (L - 0.1055613458 * a - 0.0638541728 * b) ** 3
    s_ = (L - 0.0894841775 * a - 1.2914855480 * b) ** 3
    return (4.0767416621 * l_ - 3.3077115913 * m_ + 0.2309699292 * s_,
            -1.2684380046 * l_ + 2.6097574011 * m_ - 0.3413193965 * s_,
            -0.0041960863 * l_ - 0.7034186147 * m_ + 1.7076147010 * s_)


def _in_gamut(L: float, C: float, h: float) -> bool:
    return all(-1e-4 <= c <= 1.0 + 1e-4 for c in _linear_rgb(L, C, h))


def from_oklch(L: float, C: float, h: float) -> str:
    """(lightness, chroma, hue) -> `#rrggbb`, channels clamped to sRGB."""
    out = []
    for c in _linear_rgb(L, C, h):
        out.append(round(255 * min(1.0, max(0.0, _to_srgb(min(1.0, max(0.0, c)))))))
    return "#{:02x}{:02x}{:02x}".format(*out)


@lru_cache(maxsize=4096)
def max_chroma(L: float, h: float) -> float:
    """The most saturated colour sRGB can show at this lightness and hue."""
    lo, hi = 0.0, 0.4
    for _ in range(18):
        mid = (lo + hi) / 2
        if _in_gamut(L, mid, h):
            lo = mid
        else:
            hi = mid
    return lo


def hue_of(hex_color: str) -> float:
    """The OKLCH hue of a colour, in degrees."""
    return to_oklch(hex_color)[2]


def delta_for(target_hue: Optional[float], reference_hex: str) -> float:
    """Degrees to turn the chrome by so `reference_hex` (the accent) lands
    on `target_hue`. None -- the house green -- is no turn at all."""
    if target_hue is None:
        return 0.0
    return (float(target_hue) - hue_of(reference_hex)) % 360.0


@lru_cache(maxsize=1024)
def shift_hex(hex_color: str, delta: float) -> str:
    """One token turned by `delta` degrees. A zero turn returns the token
    untouched, character for character."""
    if not delta:
        return hex_color
    L, C, h = to_oklch(hex_color)
    if C < _NEUTRAL_CHROMA:
        return hex_color
    h = (h + delta) % 360.0
    if _in_gamut(L, C, h):
        return from_oklch(L, C, h)
    # Too saturated for this hue at this lightness: take the nearest
    # lightness that holds most of it...
    best_L, best_C = L, max_chroma(round(L, 4), round(h, 3))
    steps = int(round(_L_SEARCH / _L_STEP))
    for i in range(1, steps + 1):
        for sign in (-1, 1):
            L2 = round(min(0.99, max(0.01, L + sign * i * _L_STEP)), 4)
            c2 = max_chroma(L2, round(h, 3))
            if c2 >= _KEEP_CHROMA * C:
                return from_oklch(L2, min(C, c2), h)
            if c2 > best_C:
                best_L, best_C = L2, c2
    # ...and failing that, the most saturated it can be within reach.
    return from_oklch(best_L, min(C, best_C), h)


def shift_tokens(tokens: Mapping[str, str], delta: float) -> Dict[str, str]:
    """Every `#rrggbb` value of a token dict turned by `delta` degrees."""
    return {k: (shift_hex(v, delta) if isinstance(v, str) and v.startswith("#")
                else v)
            for k, v in tokens.items()}


def _nudge(hex_color: str, taken) -> str:
    """The nearest colour to `hex_color` that is not in `taken`: the blue
    channel stepped by one, then two, ... Nobody can see one step."""
    if hex_color not in taken:
        return hex_color
    r, g, b = (int(hex_color[i:i + 2], 16) for i in (1, 3, 5))
    for step in range(1, 256):
        for cand in (b + step, b - step):
            if 0 <= cand <= 255:
                out = "#{:02x}{:02x}{:02x}".format(r, g, cand)
                if out not in taken:
                    return out
    return hex_color


def unique_table(sources, delta: float, protected=(),
                 table: Optional[Dict[str, str]] = None) -> Dict[str, str]:
    """`{role: turned hex}` for `sources` -- a `{role: source hex}` mapping,
    or a plain list of hexes (each its own role) -- with every value
    different from every other and from `protected`.

    The running app is recoloured by VALUE -- "everything that is this
    green becomes that blue" -- so two roles must never share a colour
    (they could not be told apart again on the next change), and a turned
    token must never land on a colour that is not supposed to turn (it
    would be dragged along next time). Where two do collide -- by the
    maths, or because the tokens give two roles the same colour -- the
    later one steps one blue level aside.

    Pass an earlier `table` to extend it: its entries are kept as they are
    and only count as taken. A zero turn leaves every source untouched
    that collides with nothing."""
    out: Dict[str, str] = dict(table or {})
    taken = {v.lower() for v in out.values()}
    taken.update(p.lower() for p in protected)
    if isinstance(sources, Mapping):
        items = list(sources.items())
    else:
        items = [(src.lower(), src) for src in sources]
    for role, src in items:
        if role in out:
            continue
        src = src.lower()
        new = _nudge(shift_hex(src, delta) if delta else src, taken)
        out[role] = new
        taken.add(new)
    return out
