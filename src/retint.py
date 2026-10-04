"""Recolour what is already in memory.

Every module copies its colours when it is imported -- `from constants
import COLOR_ACCENT`, a class-level `QColor(...)`, a default argument, a
dict of trace styles -- and every widget may have copied some when it was
built. Changing the app's colour while it runs means finding those copies.
Rather than teaching 150 call sites to look their colour up each time,
this walks what exists and swaps one hex for another by VALUE, given a
`{old: new}` mapping that `ui/theme.set_accent_hue` guarantees is
unambiguous (accent_shift.unique_table).

    modules(mapping)   every app module's globals, its classes' attributes
                       and its functions' default arguments -- once per
                       colour change, a few milliseconds
    instance(obj, m)   one object's own attributes (a widget, say)
    text(s, m)         a stylesheet or rich-text string

Qt-free by import: QColor / QPen / QBrush are recognised by their type
name, so `constants.py` -- and the router that imports it -- never pull Qt
in through here.

A value is only ever replaced when it IS an old colour. Each container is
visited once per call, however many names point at it, so nothing is
turned twice.
"""
from __future__ import annotations

import re
import sys
import types
from typing import Any, Dict, Optional, Set

_HEX = re.compile(r"#[0-9a-fA-F]{6}\b")
# The modules that hold colours: `constants`, everything under `ui`, and
# the three that paint outside it (the window shell, the tray icon, the
# title-bar tint). Named rather than found by path, because a frozen build
# has no source folder to look in; tests/test_live_colour.py fails when a
# module outside this list starts using colours. The token sources
# (theme_tokens) and the maths (accent_shift) are deliberately not here.
COLOUR_MODULES = frozenset({
    "constants", "ui_components", "utilities", "main", "__main__"})
COLOUR_PACKAGES = ("ui",)
_DEPTH = 4


def text(s: str, mapping: Dict[str, str]) -> str:
    """`s` with every old hex swapped for its new one."""
    if not s or "#" not in s:
        return s
    return _HEX.sub(lambda m: mapping.get(m.group(0).lower(), m.group(0)), s)


def _qcolor(color: Any, mapping: Dict[str, str]) -> bool:
    """Turn a QColor in place (alpha kept). True when it changed."""
    try:
        new = mapping.get(color.name().lower())
        if new is None:
            return False
        alpha = color.alpha()
        color.setRgb(int(new[1:3], 16), int(new[3:5], 16), int(new[5:7], 16), alpha)
        return True
    except Exception:
        return False


def _value(v: Any, mapping: Dict[str, str], seen: Set[int], depth: int):
    """Return (changed, new value). Strings and tuples come back as new
    objects; QColors, dicts, lists and sets are changed in place."""
    if isinstance(v, str):
        if len(v) == 7 and v[0] == "#":
            new = mapping.get(v.lower())
            if new is not None:
                return True, new
        return False, v
    kind = type(v).__name__
    if kind == "QColor":
        _qcolor(v, mapping)
        return False, v
    if kind in ("QPen", "QBrush"):
        try:
            c = v.color()
            if _qcolor(c, mapping):
                v.setColor(c)
        except Exception:
            pass
        return False, v
    if depth <= 0:
        return False, v
    if isinstance(v, tuple):
        if not v or len(v) > 64:
            return False, v
        out, changed = [], False
        for item in v:
            c, n = _value(item, mapping, seen, depth - 1)
            changed = changed or c
            out.append(n)
        if not changed:
            return False, v
        try:
            return True, (type(v)(*out) if hasattr(v, "_fields") else type(v)(out))
        except Exception:
            return False, v
    if isinstance(v, (dict, list)):
        if id(v) in seen or len(v) > 4096:
            return False, v
        seen.add(id(v))
        items = v.items() if isinstance(v, dict) else enumerate(v)
        for key, item in list(items):
            c, n = _value(item, mapping, seen, depth - 1)
            if c:
                try:
                    v[key] = n
                except Exception:
                    pass
        return False, v
    return False, v


def _defaults(fn: Any, mapping: Dict[str, str], seen: Set[int]) -> None:
    """Default arguments are bound when the function is defined:
    `def icon(color=COLOR_ACCENT)` keeps the old colour for ever otherwise."""
    fn = getattr(fn, "__func__", fn)
    if not isinstance(fn, types.FunctionType) or id(fn) in seen:
        return
    seen.add(id(fn))
    if fn.__defaults__:
        c, new = _value(fn.__defaults__, mapping, seen, 1)
        if c:
            fn.__defaults__ = new
    if fn.__kwdefaults__:
        _value(fn.__kwdefaults__, mapping, seen, 1)


def _namespace(owner: Any, mapping: Dict[str, str], seen: Set[int],
               skip=frozenset()) -> None:
    """One module's or one class's own names."""
    try:
        names = list(vars(owner).items())
    except TypeError:
        return
    for name, v in names:
        if name.startswith("__") or name in skip:
            continue
        if isinstance(v, (types.FunctionType, staticmethod, classmethod)):
            _defaults(v, mapping, seen)
            continue
        c, new = _value(v, mapping, seen, _DEPTH)
        if c:
            try:
                setattr(owner, name, new)
            except Exception:
                pass


def instance(obj: Any, mapping: Dict[str, str],
             seen: Optional[Set[int]] = None) -> None:
    """One object's own attributes -- the colours a widget copied into
    itself when it was built."""
    d = getattr(obj, "__dict__", None)
    if not d or not mapping:
        return
    seen = set() if seen is None else seen
    for name, v in list(d.items()):
        if isinstance(v, types.FunctionType):
            continue
        c, new = _value(v, mapping, seen, _DEPTH)
        if c:
            try:
                setattr(obj, name, new)
            except Exception:
                pass


def is_colour_module(name: str) -> bool:
    return name in COLOUR_MODULES or name.split(".")[0] in COLOUR_PACKAGES


def _colour_modules():
    for name, mod in list(sys.modules.items()):
        if mod is not None and is_colour_module(name):
            yield mod


def modules(mapping: Dict[str, str]) -> None:
    """Every imported colour-holding module: its globals, the attributes
    of the classes it defines, and the default arguments of its functions
    and methods."""
    if not mapping:
        return
    seen: Set[int] = set()
    for mod in _colour_modules():
        skip = getattr(mod, "__retint_skip__", frozenset())
        _namespace(mod, mapping, seen, skip)
        for v in list(vars(mod).values()):
            if isinstance(v, type) and getattr(v, "__module__", None) == mod.__name__:
                if id(v) not in seen:
                    seen.add(id(v))
                    _namespace(v, mapping, seen)
