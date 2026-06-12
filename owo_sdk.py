# owo_sdk.py
# Guarded loader for the official OWO .NET SDK (OWO.dll) via pythonnet.
#
# OWO has no documented pure-Python protocol; the proven path (see
# github.com/shadorki/vrc-owo-suit) is to load the vendor's OWO.dll through
# pythonnet's CLR bridge. ALL of that — the optional `clr` import, the
# Assembly load, and the OWOGame namespace — is isolated here so owo_engine.py
# stays a normal sealed engine and the rest of the app never imports clr.
#
# Both the binary and pythonnet are OPTIONAL: nothing imports this at module
# load except owo_engine (which only calls is_available()), so the app runs
# fine without either. Drop OWO.dll into owo-sdk/ and `pip install pythonnet`
# to enable the backend (see owo-sdk/PLACE_OWO_DLL_HERE.txt).

import os
import sys

# The 10 muscle groups the OWO suit exposes (OWOGame.Muscle enum members).
MUSCLE_NAMES = [
    "Pectoral_R", "Pectoral_L",
    "Abdominal_R", "Abdominal_L",
    "Arm_R", "Arm_L",
    "Dorsal_R", "Dorsal_L",
    "Lumbar_R", "Lumbar_L",
]

# Populated by load(): the OWOGame SDK objects + a {name: Muscle} map.
OWO = None
SensationsFactory = None
Muscle = None
ConnectionState = None
GameAuth = None
MUSCLES = {}

_LOADED = False
_ATTEMPTED = False
_LOAD_ERROR = None


def _dll_path() -> str:
    """owo-sdk/OWO.dll next to the source, or under the PyInstaller bundle."""
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, "owo-sdk", "OWO.dll")


def load() -> bool:
    """Attempt to load pythonnet + OWO.dll once. Returns True on success.
    Caches the (single) attempt so the reconnect loop doesn't re-import clr
    every tick — relaunch the app after installing the prerequisites."""
    global _LOADED, _ATTEMPTED, _LOAD_ERROR
    global OWO, SensationsFactory, Muscle, ConnectionState, GameAuth, MUSCLES
    if _LOADED:
        return True
    if _ATTEMPTED:
        return False
    _ATTEMPTED = True

    try:
        import clr  # noqa: F401  (pythonnet)
    except Exception:
        _LOAD_ERROR = "pythonnet not installed (pip install pythonnet)"
        return False

    path = _dll_path()
    if not os.path.exists(path):
        _LOAD_ERROR = f"OWO.dll not found — place it at {path}"
        return False

    try:
        from System.Reflection import Assembly
        Assembly.UnsafeLoadFrom(path)
        from OWOGame import (
            OWO as _OWO, SensationsFactory as _SF, Muscle as _M,
            ConnectionState as _CS, GameAuth as _GA,
        )
        OWO, SensationsFactory, Muscle = _OWO, _SF, _M
        ConnectionState, GameAuth = _CS, _GA
        MUSCLES = {n: getattr(_M, n) for n in MUSCLE_NAMES if hasattr(_M, n)}
        _LOADED = True
        return True
    except Exception as e:
        _LOAD_ERROR = f"OWO SDK load failed: {e}"
        return False


def is_available() -> bool:
    return _LOADED or load()


def load_error():
    return _LOAD_ERROR
