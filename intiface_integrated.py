# OscGoesPurrr - Integrated Intiface connection provider
"""
The NEW Buttplug connection path: OscGoesPurrr spawns and supervises its own
bundled `intiface-engine` so the user never has to launch Intiface Central
separately — "everything in one program".

This is the "Integrated" half of the Intiface-mode toggle (the default). The
"External" half (connect to a user-run Intiface Central) lives in
intiface_external.py. Both satisfy the small connection-provider contract in
intiface_connection.py, so HapticEngine uses either interchangeably.

What this module owns (and the External provider does not):
  * locating the bundled `intiface-engine` binary (dev tree or PyInstaller
    _MEIPASS),
  * launching it with no flashing console window,
  * keeping it from being orphaned if OscGoesPurrr crashes (Windows Job
    Object with kill-on-close),
  * waiting until its websocket is actually serving before we dial it,
  * tearing it down on disconnect / app quit.

The binary itself is NOT checked into the repo (it's a per-platform native
executable). It is expected at `<INTIFACE_ENGINE_DIRNAME>/intiface-engine[.exe]`
and bundled into frozen builds via build_OGP.bat's --add-data. If it's missing,
prepare() raises a clear, actionable error and the user can drop the binary in
or flip the Settings toggle back to External mode.
"""

from __future__ import annotations

import asyncio
import subprocess
import sys
from pathlib import Path
from typing import Callable, List, Optional, Tuple
from urllib.parse import urlsplit

from constants import (
    INTIFACE_ENGINE_DIRNAME,
    INTIFACE_ENGINE_STARTUP_TIMEOUT_S,
    INTIFACE_WS_URL,
)

_IS_WINDOWS = sys.platform == "win32"
_ENGINE_EXE = "intiface-engine.exe" if _IS_WINDOWS else "intiface-engine"

# Flags passed besides --websocket-port, verified against intiface-engine
# v1.4.8 via `--help` and a live run:
#   --use-bluetooth-le : enable the BLE transport (the common case for toys).
#       NOTE: the engine's own --help mislabels every --use-* flag as
#       "turn off <x> device support", but they are opt-IN *enables* — a live
#       run with this flag logs "Including Bluetooth LE (btleplug) Device Comm
#       Manager Support" and "Bluetooth LE adapter found".
# The engine keeps serving until we terminate it (there is no --stay-open flag,
# and none is needed), so a transient websocket drop + auto-reconnect re-dials
# the same running engine. Power users who need more transports can append
# --use-serial, --use-hid, --use-lovense-dongle-serial, --use-xinput, etc.
# If a future engine build rejects a flag it exits immediately and prepare()
# surfaces the log tail; switching to External mode in Settings is the fallback.
_BASE_ENGINE_ARGS: List[str] = ["--use-bluetooth-le"]


# --------------------------------------------------------------------------- pure helpers


def _ws_host_port() -> Tuple[str, int]:
    """Host + port to bind/probe, derived from the single INTIFACE_WS_URL so
    integrated and external modes always agree on the endpoint."""
    parsed = urlsplit(INTIFACE_WS_URL)
    return (parsed.hostname or "127.0.0.1"), int(parsed.port or 12345)


def _resolve_engine_path() -> Path:
    """Absolute path to the bundled engine binary, whether running from source
    or from a PyInstaller --onefile bundle (mirrors the steamvr_toy_driver
    resolution pattern)."""
    if getattr(sys, "frozen", False):
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            return Path(meipass) / INTIFACE_ENGINE_DIRNAME / _ENGINE_EXE
    return Path(__file__).resolve().parent / INTIFACE_ENGINE_DIRNAME / _ENGINE_EXE


def _find_device_config(engine_dir: Path) -> Optional[Path]:
    """Optional: if the user dropped a buttplug device-config JSON next to the
    engine, pass it through. Absent by default (the engine ships built-in
    defaults), so integrated mode works with zero extra files."""
    try:
        for pattern in ("buttplug-device-config*.json", "device-config*.json"):
            for match in sorted(engine_dir.glob(pattern)):
                if match.is_file():
                    return match
    except OSError:
        pass
    return None


def _build_engine_args(port: int, engine_dir: Optional[Path] = None) -> List[str]:
    """CLI args (excluding the binary itself) for launching the engine on
    `port`. Pure + deterministic so it can be unit-tested without spawning."""
    args: List[str] = ["--websocket-port", str(int(port))] + list(_BASE_ENGINE_ARGS)
    if engine_dir is not None:
        cfg = _find_device_config(engine_dir)
        if cfg is not None:
            args += ["--device-config-file", str(cfg)]
    return args


def _engine_log_path() -> Path:
    """Where the engine's stdout/stderr is captured. Lazy import of the AppData
    path keeps this module import-light (the pure helpers above don't touch the
    filesystem, so tests can import freely)."""
    from settings._paths import APPDATA_DIR

    return APPDATA_DIR / "intiface_engine.log"


def _read_tail(path: Path, limit: int = 2000) -> str:
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            return f.read()[-limit:].strip() or "(engine produced no output)"
    except OSError:
        return "(no engine log available)"


# --------------------------------------------------------------------------- startup wait

# CRITICAL: we must NOT probe the websocket port with a raw socket. intiface-
# engine treats a bare TCP connection that doesn't complete a WebSocket
# handshake as a failed client session and SHUTS ITSELF DOWN ("Websocket server
# accept error: Protocol(HandshakeIncomplete)" -> "Breaking out of event loop in
# order to exit"). An earlier version of this module did exactly that and killed
# the engine ~0.7s after launch, before the real client could connect. The real
# Buttplug client (which performs a proper handshake and stays connected) must be
# the ONLY thing that ever connects to the engine.


async def _await_engine_startup(
    proc: "subprocess.Popen", log_path: Path, timeout: float
) -> None:
    """Wait out the engine's startup window WITHOUT opening a socket.

    The engine binds its websocket within a few hundred ms of launch, so we just
    confirm the process survives a short grace period. The real connect that
    follows is the actual readiness gate — if it races startup it merely gets
    connection-refused (no half-open handshake), and the caller's reconnect loop
    retries. Raises if the engine exits during the grace window.
    """
    loop = asyncio.get_event_loop()
    grace = min(2.0, max(0.5, timeout))
    deadline = loop.time() + grace
    while loop.time() < deadline:
        code = proc.poll()
        if code is not None:
            raise RuntimeError(
                f"intiface-engine exited during startup (code {code}). Log tail:\n"
                f"{_read_tail(log_path)}"
            )
        await asyncio.sleep(0.15)


# --------------------------------------------------------------------------- Windows job object


def _assign_to_job(proc: "subprocess.Popen"):
    """Put the engine process in a Windows Job Object configured to kill its
    members when the job handle closes. We hold that handle for the life of
    this provider, so if OscGoesPurrr exits — cleanly OR by crashing — Windows
    tears the engine down with us. Without this, a crash could orphan the
    engine and leave it holding the Bluetooth radio, blocking the next launch.

    Returns the job handle (to keep alive) or None if anything failed; callers
    treat None as "rely on explicit terminate() instead". No-op off Windows.
    """
    if not _IS_WINDOWS:
        return None
    try:
        import ctypes
        from ctypes import wintypes

        k32 = ctypes.WinDLL("kernel32", use_last_error=True)

        ULONG_PTR = ctypes.c_size_t

        class JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
            _fields_ = [
                ("PerProcessUserTimeLimit", ctypes.c_int64),
                ("PerJobUserTimeLimit", ctypes.c_int64),
                ("LimitFlags", wintypes.DWORD),
                ("MinimumWorkingSetSize", ctypes.c_size_t),
                ("MaximumWorkingSetSize", ctypes.c_size_t),
                ("ActiveProcessLimit", wintypes.DWORD),
                ("Affinity", ULONG_PTR),
                ("PriorityClass", wintypes.DWORD),
                ("SchedulingClass", wintypes.DWORD),
            ]

        class IO_COUNTERS(ctypes.Structure):
            _fields_ = [
                ("ReadOperationCount", ctypes.c_uint64),
                ("WriteOperationCount", ctypes.c_uint64),
                ("OtherOperationCount", ctypes.c_uint64),
                ("ReadTransferCount", ctypes.c_uint64),
                ("WriteTransferCount", ctypes.c_uint64),
                ("OtherTransferCount", ctypes.c_uint64),
            ]

        class JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
            _fields_ = [
                ("BasicLimitInformation", JOBOBJECT_BASIC_LIMIT_INFORMATION),
                ("IoInfo", IO_COUNTERS),
                ("ProcessMemoryLimit", ctypes.c_size_t),
                ("JobMemoryLimit", ctypes.c_size_t),
                ("PeakProcessMemoryUsed", ctypes.c_size_t),
                ("PeakJobMemoryUsed", ctypes.c_size_t),
            ]

        JobObjectExtendedLimitInformation = 9
        JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x2000

        k32.CreateJobObjectW.restype = wintypes.HANDLE
        k32.CreateJobObjectW.argtypes = [wintypes.LPVOID, wintypes.LPCWSTR]
        job = k32.CreateJobObjectW(None, None)
        if not job:
            return None

        info = JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
        info.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        k32.SetInformationJobObject.restype = wintypes.BOOL
        k32.SetInformationJobObject.argtypes = [
            wintypes.HANDLE,
            ctypes.c_int,
            wintypes.LPVOID,
            wintypes.DWORD,
        ]
        if not k32.SetInformationJobObject(
            job,
            JobObjectExtendedLimitInformation,
            ctypes.byref(info),
            ctypes.sizeof(info),
        ):
            k32.CloseHandle(job)
            return None

        k32.AssignProcessToJobObject.restype = wintypes.BOOL
        k32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
        if not k32.AssignProcessToJobObject(job, int(proc._handle)):
            k32.CloseHandle(job)
            return None
        return job
    except Exception:
        return None


def _close_job(job) -> None:
    """Close the job handle. On Windows this also kills the engine (kill-on-
    close), which is exactly what we want on teardown."""
    if not _IS_WINDOWS or not job:
        return
    try:
        import ctypes

        ctypes.WinDLL("kernel32", use_last_error=True).CloseHandle(job)
    except Exception:
        pass


# --------------------------------------------------------------------------- provider


class IntegratedIntifaceConnection:
    """Spawns and supervises the bundled intiface-engine, then hands back its
    websocket URL. Owns the subprocess + job handle + log file; exposes only
    the small connection-provider contract."""

    mode = "integrated"

    def __init__(self, log: Optional[Callable[[str], None]] = None) -> None:
        self._log = log if callable(log) else (lambda _m: None)
        self._proc: Optional[subprocess.Popen] = None
        self._job = None
        self._logf = None

    @property
    def status_label(self) -> str:
        return "Intiface (built-in)"

    async def prepare(self) -> str:
        _host, port = _ws_host_port()

        if self._proc is not None:
            if self._proc.poll() is None:
                # Already running — let the real client dial it. We deliberately
                # do NOT probe the socket (see _await_engine_startup): a probe
                # would make the engine exit.
                return INTIFACE_WS_URL
            # The engine exited since we last spawned it (this engine version
            # shuts down when its client disconnects). Release the stale job/log
            # handles before respawning so they don't leak across reconnects.
            self._log(
                f"Built-in Intiface engine had exited (code {self._proc.returncode}); "
                "restarting it."
            )
            self.terminate()

        engine = _resolve_engine_path()
        if not engine.is_file():
            raise FileNotFoundError(
                f"Built-in Intiface engine not found at '{engine}'. Place the "
                f"intiface-engine binary in the '{INTIFACE_ENGINE_DIRNAME}' "
                f"folder, or switch to External Intiface mode in "
                f"Settings → Intiface Engine."
            )

        log_path = _engine_log_path()
        self._log(f"Starting built-in Intiface engine on port {port} …")
        args = [str(engine)] + _build_engine_args(port, engine.parent)

        # CREATE_NO_WINDOW: keep the engine's console from flashing under a
        # --windowed (pythonw/PyInstaller) build, matching version.py's git
        # subprocess handling. Defined as 0 off Windows.
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        try:
            self._logf = open(log_path, "w", encoding="utf-8", errors="replace")
        except OSError:
            self._logf = None  # logging the engine is best-effort

        self._proc = subprocess.Popen(
            args,
            stdout=self._logf or subprocess.DEVNULL,
            stderr=subprocess.STDOUT,
            cwd=str(engine.parent),
            creationflags=creationflags,
        )
        self._job = _assign_to_job(self._proc)

        try:
            await _await_engine_startup(
                self._proc, log_path, INTIFACE_ENGINE_STARTUP_TIMEOUT_S
            )
        except BaseException:
            # Don't leave a half-started engine running if startup failed.
            self.terminate()
            raise

        self._log("Built-in Intiface engine is ready.")
        return INTIFACE_WS_URL

    async def shutdown(self) -> None:
        self.terminate()

    def terminate(self) -> None:
        """Stop the engine and release every resource we hold. Idempotent and
        safe to call from any thread (Popen.terminate/kill are thread-safe)."""
        proc, self._proc = self._proc, None
        job, self._job = self._job, None
        logf, self._logf = self._logf, None

        if proc is not None and proc.poll() is None:
            try:
                proc.terminate()
            except Exception:
                pass
            try:
                proc.wait(timeout=3)
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass
        # Closing the job handle kills any survivors (kill-on-close).
        _close_job(job)
        if logf is not None:
            try:
                logf.close()
            except Exception:
                pass
