# psvr2_capi.py
# Guarded ctypes binding for the PSVR2Toolkit C API (BnuuySolutions).
#
# The toolkit ships a plain `extern "C"` DLL (psvr2_toolkit_capi.dll), so the
# whole integration is stdlib ctypes — no build step, no new dependency. ALL
# of the ctypes surface is isolated here so psvr2_engine.py stays a normal
# sealed engine and the rest of the app never imports ctypes for this.
#
# Discovery mirrors the toolkit's own loader (psvr2tk_capi_loader.cpp): the
# toolkit writes its CAPI directory into `%TEMP%\psvr2tk_capi_path.txt`, and
# the client appends the DLL name and LoadLibrary's it. The file only exists
# once the toolkit has run, so a missing file is the normal "not installed"
# state, not an error.
#
# Everything is OPTIONAL: nothing imports this at module load except
# psvr2_engine (which only calls is_available()), so the app runs fine on a
# machine that has never seen a PSVR2.
#
# WHAT WE BIND, AND WHY IT'S ONLY THIS MUCH
# -----------------------------------------
# We drive the headset rumble motor only:
#
#   int psvr2_toolkit_set_hmd_rumble(uint8_t rumbleHz)   # 0-25, 0 = off
#
# The toolkit's own comment: the headset really does 10-25 Hz and takes
# 1-9 as 10, so a band floor under 10 only flattens the bottom of the range.
#
# Two properties of that call shape the engine above:
#
#  1. It does NOT require a claimed IPC slot. Unlike write_pcm() and
#     set_trigger_effect(), the toolkit's implementation skips the
#     `g_slot >= 0` guard, so headset rumble keeps working even when all 8
#     client slots are taken by other apps (a VRCFT module, a game mod). We
#     still call init() — it creates the shared-memory singleton — but we
#     treat RESULT_NO_SLOT as success.
#  2. It BLOCKS until the driver acknowledges (the toolkit pushes a command
#     into a shared ring buffer and spins on `isFulfilled`, up to 5 s), and
#     the driver turns each one into a USB control transfer to the headset.
#     So it must never be called from a router tick or the Qt thread — see
#     psvr2_engine's latest-wins send thread. ctypes releases the GIL for the
#     duration of the call, so a slow ack stalls only the calling thread.
#
# Requires a JAILBROKEN headset: the rumble motor is inert on a stock unit.
# The call still succeeds, so we cannot detect that from here.
#
# TOOLKIT VERSIONS (checked against BnuuySolutions/PSVR2Toolkit, 2026-11-14)
# -------------------------------------------------------------------------
# The CAPI ships only in the v1.0.0-experimental pre-releases (v0.2.1, the
# last stable one, predates it). Since experimental-2 (the 2026-08-12 "add
# more results" change):
#   * set_hmd_rumble returns a result: OK, DRIVER_INACTIVE, TIMEOUT (the
#     driver never acked), INVALID_PARAMETER (> 25 Hz -- we clamp first);
#   * init() succeeds without SteamVR running, so it no longer says whether
#     the driver is there -- the engine asks get_driver_active() itself.
# experimental-1's set_hmd_rumble returned void, which reads as junk in an
# int, so only the failure codes count as failures (rumble_failed()).

import ctypes
import os
import tempfile

# psvr2tk_capi.h
RESULT_OK = 0
RESULT_DRIVER_INACTIVE = -1
RESULT_NO_SLOT = -2
RESULT_TIMEOUT = -3
RESULT_INVALID_PARAMETER = -4

# What set_hmd_rumble can say went wrong. Anything else is success: an
# experimental-1 DLL returns nothing, so whatever is in the register shows.
_RUMBLE_FAILURES = {
    RESULT_DRIVER_INACTIVE: "the PSVR2 driver isn't running (SteamVR closed?)",
    RESULT_TIMEOUT: "the PSVR2 driver didn't answer",
    RESULT_INVALID_PARAMETER: "the toolkit refused the frequency",
}


def rumble_failed(result):
    """Why a set_hmd_rumble result is a failure, or None when it isn't."""
    try:
        return _RUMBLE_FAILURES.get(int(result))
    except (TypeError, ValueError):
        return None

# The toolkit's own test UI caps its rumble slider here; the wire field is a
# single byte, so clamp hard rather than trusting callers.
RUMBLE_HZ_MAX = 25

_PATH_FILE = "psvr2tk_capi_path.txt"
_DLL_NAME = "psvr2_toolkit_capi.dll"

# LOAD_WITH_ALTERED_SEARCH_PATH — resolve the DLL's own dependencies from its
# install directory, exactly as the toolkit's loader does.
_LOAD_WITH_ALTERED_SEARCH_PATH = 0x00000008

_lib = None
_ATTEMPTED = False
_LOAD_ERROR = None
_DLL_PATH = None


def _temp_dirs():
    """Candidate temp directories to look for the toolkit's path file in.

    The driver half runs inside SteamVR's vrserver.exe. That is normally the
    same user (same %TEMP%), but check the usual suspects rather than assume.
    """
    seen = []
    for d in (tempfile.gettempdir(),
              os.environ.get("TEMP"),
              os.environ.get("TMP"),
              r"C:\Windows\Temp"):
        if d and d not in seen:
            seen.append(d)
    return seen


def _find_dll():
    """Read the toolkit's path file and return the full DLL path, or None."""
    for temp_dir in _temp_dirs():
        try:
            path_file = os.path.join(temp_dir, _PATH_FILE)
            if not os.path.exists(path_file):
                continue
            with open(path_file, "r", encoding="utf-8", errors="replace") as f:
                dir_path = (f.readline() or "").strip()
        except OSError:
            continue
        if not dir_path:
            continue
        candidate = os.path.join(dir_path, _DLL_NAME)
        if os.path.exists(candidate):
            return candidate
    return None


def load() -> bool:
    """Attempt to locate and load the CAPI DLL. Returns True on success.

    A *missing* toolkit stays retryable: the path file only appears once the
    toolkit has run, so someone can perfectly reasonably install it while
    OscGoesPurrr is already open, and re-probing costs two os.path.exists
    calls on the engine's 5 s unavailable tick.

    A *failed load* latches instead — a broken or incompatible DLL will not
    fix itself, and retrying it forever would just spam. Relaunch the app
    after replacing it.
    """
    global _lib, _ATTEMPTED, _LOAD_ERROR, _DLL_PATH
    if _lib is not None:
        return True
    if _ATTEMPTED:
        return False

    if os.name != "nt":
        _ATTEMPTED = True
        _LOAD_ERROR = "PSVR2Toolkit is Windows-only"
        return False

    path = _find_dll()
    if not path:
        _LOAD_ERROR = ("PSVR2Toolkit not detected — install it and run it once "
                       "(it publishes its API path on first launch)")
        return False
    _ATTEMPTED = True

    try:
        lib = ctypes.CDLL(path, winmode=_LOAD_WITH_ALTERED_SEARCH_PATH)
        lib.psvr2_toolkit_init.restype = ctypes.c_int
        lib.psvr2_toolkit_init.argtypes = []
        lib.psvr2_toolkit_deinit.restype = None
        lib.psvr2_toolkit_deinit.argtypes = []
        lib.psvr2_toolkit_get_driver_active.restype = ctypes.c_bool
        lib.psvr2_toolkit_get_driver_active.argtypes = []
        lib.psvr2_toolkit_set_hmd_rumble.restype = ctypes.c_int
        lib.psvr2_toolkit_set_hmd_rumble.argtypes = [ctypes.c_uint8]
    except (OSError, AttributeError) as e:
        # OSError: DLL or a dependency failed to load (also the 32-bit Python
        # case). AttributeError: an export is missing — the CAPI is explicitly
        # WIP upstream, so a renamed symbol is a real possibility.
        _LOAD_ERROR = f"PSVR2 CAPI load failed: {e}"
        return False

    _lib = lib
    _DLL_PATH = path
    return True


def is_available() -> bool:
    return _lib is not None or load()


def load_error():
    return _LOAD_ERROR


def dll_path():
    return _DLL_PATH


# ---- API -------------------------------------------------------------
# Each raises RuntimeError when the DLL isn't loaded, so a caller that skipped
# is_available() fails loudly instead of silently no-op'ing.

def _lib_or_raise():
    if _lib is None:
        raise RuntimeError(_LOAD_ERROR or "PSVR2 CAPI not loaded")
    return _lib


def init() -> int:
    """Create the toolkit's shared-memory client and claim an IPC slot.

    Returns one of the RESULT_* codes. RESULT_NO_SLOT still leaves headset
    rumble usable (see the module docstring) — only RESULT_DRIVER_INACTIVE
    means nothing will work.
    """
    return int(_lib_or_raise().psvr2_toolkit_init())


def deinit() -> None:
    _lib_or_raise().psvr2_toolkit_deinit()


def get_driver_active() -> bool:
    """True while the patched PSVR2 driver holds its liveness mutex — i.e.
    SteamVR is running with PSVR2Toolkit installed."""
    return bool(_lib_or_raise().psvr2_toolkit_get_driver_active())


def set_hmd_rumble(rumble_hz: int) -> int:
    """Set the headset rumble frequency (0-25 Hz; 0 stops the motor) and
    return the toolkit's result (see rumble_failed()).

    BLOCKS until the driver acks — call only from the engine's send thread.
    """
    hz = max(0, min(RUMBLE_HZ_MAX, int(rumble_hz)))
    return int(_lib_or_raise().psvr2_toolkit_set_hmd_rumble(ctypes.c_uint8(hz)))
