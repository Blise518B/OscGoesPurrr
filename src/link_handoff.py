"""ogp:// links reach the OGP that is already running.

Clicking an invite link starts a new OGP with the link on its command line.
If one is already running, the new one only hands the link over and quits
— through a local named pipe (a Unix socket on Linux), one per user, that
the running OGP listens on. A launch without a link that finds one running
asks whether to switch to it (SHOW brings it to the front) or open a second
window anyway (main.py) -- it is not a lock.
"""

import getpass
import os
import sys
import threading
import time
from multiprocessing.connection import Client, Listener
from typing import Callable, Optional

from link_scheme import SCHEME

AUTHKEY = b"oscgoespurrr-links"
PREFIX = f"{SCHEME}:"
PING = f"{SCHEME}:ping"   # "anyone listening?" -- never a link
SHOW = f"{SCHEME}:show"   # "come to the front" -- never a link
MAX_LINK = 512            # bytes; plain bytes on the pipe, never pickles


def default_address() -> str:
    try:
        user = getpass.getuser()
    except Exception:
        user = "user"
    safe = "".join(c for c in user if c.isalnum()) or "user"
    if sys.platform == "win32":
        return rf"\\.\pipe\OscGoesPurrr-links-{safe}"
    base = os.environ.get("XDG_RUNTIME_DIR") or "/tmp"
    return os.path.join(base, f"oscgoespurrr-links-{safe}.sock")


def link_from_argv(argv) -> Optional[str]:
    """The ogp:// link OGP was started with, if any."""
    for arg in list(argv)[1:]:
        if str(arg).lower().startswith(PREFIX):
            return str(arg)
    return None


def send_to_running(link: str, address: Optional[str] = None,
                    timeout: float = 3.0) -> bool:
    """Hand `link` to a running OGP. False when none is listening -- or
    when it doesn't take the link within `timeout` (a hung OGP must not
    hang the launch that clicked the link)."""
    done = []

    def send() -> None:
        try:
            with Client(address or default_address(), authkey=AUTHKEY) as conn:
                conn.send_bytes(str(link).encode("utf-8")[:MAX_LINK])
            done.append(True)
        except Exception:
            pass

    t = threading.Thread(target=send, name="ogp-link-send", daemon=True)
    t.start()
    t.join(timeout)
    return bool(done)


def another_running(address: Optional[str] = None, settle_s: float = 1.5) -> bool:
    """Is another OGP open? It has to answer twice, `settle_s` apart: an
    OGP that is just closing (an update or a restore starting the new one)
    does not count."""
    if not send_to_running(PING, address, timeout=0.6):
        return False
    time.sleep(settle_s)
    return send_to_running(PING, address, timeout=0.6)


class LinkListener:
    """Hears links handed over by a newer launch; calls `on_link(link)` on
    its own thread."""

    def __init__(self, on_link: Callable[[str], None], address: Optional[str] = None,
                 log: Callable[[str], None] = lambda m: None):
        self._on_link = on_link
        self._address = address or default_address()
        self._log = log
        self._listener = None
        self._stopped = False

    def start(self) -> bool:
        if self._listener is not None:
            return True
        addr = self._address
        if sys.platform != "win32" and os.path.exists(addr) and not send_to_running(PING, addr):
            try:
                os.remove(addr)          # a socket left behind by a crash
            except OSError:
                pass
        try:
            self._listener = Listener(addr, authkey=AUTHKEY)
        except Exception as e:
            self._log(f"Friends: invite links can't be handed over ({type(e).__name__})")
            return False
        self._stopped = False
        threading.Thread(target=self._serve, name="ogp-links", daemon=True).start()
        return True

    def _serve(self) -> None:
        # Back to accept() after every link, and the stop check only after
        # it: stop() wakes accept() with a ping, which must find it waiting.
        while True:
            try:
                conn = self._listener.accept()
            except Exception:
                if self._stopped:
                    return
                time.sleep(0.2)
                continue
            if self._stopped:
                conn.close()
                return
            try:
                if conn.poll(2.0):
                    msg = conn.recv_bytes(MAX_LINK).decode("utf-8", "replace")
                    if (not self._stopped and msg.lower().startswith(PREFIX)
                            and msg != PING):
                        self._on_link(msg)
            except Exception as e:
                self._log(f"Friends: a handed-over link failed ({type(e).__name__})")
            finally:
                conn.close()

    def stop(self) -> None:
        if self._listener is None:
            return
        self._stopped = True
        send_to_running(PING, self._address, timeout=1.0)   # wake the accept()
        try:
            self._listener.close()
        except Exception:
            pass
        self._listener = None
