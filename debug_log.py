# OscGoesPurrr - Durable debug logging
"""
File-based diagnostics so failures can be inspected after the fact. The GUI
ships as a --windowed build, so stderr, tracebacks, and thread crashes are
otherwise invisible — which is exactly why "the app randomly closed" leaves no
clue. This wires up persistent logging plus catch-all crash handlers.

`setup_logging()` is called once at process start (from main.py's __main__).
It writes to:

  * %APPDATA%/OscGoesPurrr/ogp_debug.log   — app log (rotating)
  * %APPDATA%/OscGoesPurrr/ogp_crash.log   — native-crash dumps (faulthandler)

and installs:

  * sys.excepthook        — uncaught exceptions on the main thread,
  * threading.excepthook  — uncaught exceptions on ANY other thread (the
                            asyncio worker, OSC, pystray …). This is the one
                            that catches a thread silently dying.
  * faulthandler          — native crashes (access violations) that aren't
                            Python exceptions at all.
  * an atexit marker      — so a clean shutdown is distinguishable from a crash.

Reading the result later:
  * ends with "process exiting (atexit)"      -> clean shutdown
  * ends with "UNCAUGHT (...)" + a traceback  -> Python exception crash
  * ogp_crash.log has a dump                   -> native crash
  * log just stops with none of the above     -> hard kill / C++ abort
"""

from __future__ import annotations

import atexit
import faulthandler
import logging
import logging.handlers
import os
import sys
import threading
from pathlib import Path

_LOGGER_NAME = "ogp"
_configured = False
_fault_file = None  # keep the faulthandler file handle alive for the process


def _log_dir() -> Path:
    # Lazy import keeps this module import-light for unit tests.
    from settings._paths import APPDATA_DIR

    return APPDATA_DIR


def log_path() -> Path:
    return _log_dir() / "ogp_debug.log"


def crash_path() -> Path:
    return _log_dir() / "ogp_crash.log"


def get_logger(name: str = "") -> logging.Logger:
    """Child logger under the shared "ogp" root, e.g. get_logger("engine")."""
    if not name:
        return logging.getLogger(_LOGGER_NAME)
    return logging.getLogger(f"{_LOGGER_NAME}.{name}")


def _flush() -> None:
    for h in logging.getLogger(_LOGGER_NAME).handlers:
        try:
            h.flush()
        except Exception:
            pass


def setup_logging(level: int = logging.INFO) -> Path:
    """Idempotent. Returns the debug log path."""
    global _configured, _fault_file
    if _configured:
        return log_path()
    _configured = True

    logger = logging.getLogger(_LOGGER_NAME)
    logger.setLevel(level)
    logger.propagate = False

    p = log_path()
    try:
        handler = logging.handlers.RotatingFileHandler(
            p, maxBytes=2_000_000, backupCount=3, encoding="utf-8"
        )
        handler.setFormatter(
            logging.Formatter(
                "%(asctime)s %(levelname)-7s [%(threadName)s] %(name)s: %(message)s"
            )
        )
        logger.addHandler(handler)
    except OSError:
        pass  # logging is best-effort and must never block startup

    # Native crash dumps (access violations etc.) -> companion file.
    try:
        _fault_file = open(crash_path(), "w", encoding="utf-8", errors="replace")
        faulthandler.enable(file=_fault_file, all_threads=True)
    except Exception:
        pass

    # Uncaught exceptions on the main thread.
    _prev_excepthook = sys.excepthook

    def _excepthook(exc_type, exc, tb):
        try:
            logger.critical("UNCAUGHT (main thread)", exc_info=(exc_type, exc, tb))
            _flush()
        except Exception:
            pass
        try:
            _prev_excepthook(exc_type, exc, tb)
        except Exception:
            pass

    sys.excepthook = _excepthook

    # Uncaught exceptions on every other thread (the key to "it just closed").
    if hasattr(threading, "excepthook"):
        _prev_threadhook = threading.excepthook

        def _threadhook(args):
            try:
                tname = getattr(getattr(args, "thread", None), "name", "?")
                logger.critical(
                    "UNCAUGHT (thread %s)",
                    tname,
                    exc_info=(args.exc_type, args.exc_value, args.exc_traceback),
                )
                _flush()
            except Exception:
                pass
            try:
                _prev_threadhook(args)
            except Exception:
                pass

        threading.excepthook = _threadhook

    @atexit.register
    def _on_exit():
        try:
            logger.info("process exiting (atexit) — clean shutdown path")
            _flush()
        except Exception:
            pass

    try:
        from version import __version_full__ as _ver
    except Exception:
        _ver = "?"
    logger.info("=" * 64)
    logger.info("OscGoesPurrr starting — version %s, pid %s", _ver, os.getpid())
    logger.info("python %s on %s", sys.version.split()[0], sys.platform)
    logger.info("debug log: %s", p)
    logger.info("crash log: %s", crash_path())
    _flush()
    return p


def install_asyncio_handler(loop) -> None:
    """Route unhandled asyncio exceptions (e.g. fire-and-forget task failures,
    which otherwise vanish into hidden stderr) into the debug log."""
    logger = get_logger("asyncio")

    def _handler(_loop, context):
        msg = context.get("message", "")
        exc = context.get("exception")
        if exc is not None:
            logger.error("loop exception: %s", msg, exc_info=exc)
        else:
            logger.error("loop exception: %s | %r", msg, context)
        _flush()

    try:
        loop.set_exception_handler(_handler)
    except Exception:
        pass
