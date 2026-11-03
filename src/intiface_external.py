# OscGoesPurrr - External Intiface connection provider
"""
The ORIGINAL Buttplug connection path: connect to an Intiface Central (or any
Buttplug websocket server) that the user has started themselves. This module
owns *nothing* about the server's lifecycle — it just hands back the websocket
URL and lets HapticEngine's Buttplug client dial it.

That Intiface can be on this PC or on another device on the same network --
a phone running Intiface Central, with the toys paired to the phone. Two ways
to say where it is (Settings → Intiface Engine):

  * an address typed in (`intiface_address`: "192.168.1.50", "…:12345",
    "ws://…") -- always that one;
  * nothing typed (the default): found by itself. Each connect attempt dials
    the next of: the servers mDNS shows on the network (intiface_discovery.py,
    newest first), then this PC (ws://127.0.0.1:12345, the old behaviour).
    Taking turns means a wrong guess costs one attempt, never the link: a PC
    whose own Central announces itself but only listens locally still gets
    127.0.0.1 on the next turn. The one that last worked goes first.

Nothing here ever opens a socket to test a guess -- an Intiface server stops
after a connection that isn't a Buttplug handshake (intiface_integrated.py),
so the real client's connect is the only test.

This is the "External" half of the Intiface-mode toggle. The "Integrated" half
(OscGoesPurrr spawns and supervises its own bundled engine) lives in
intiface_integrated.py. Both satisfy the small connection-provider contract
described in intiface_connection.py, so HapticEngine can use either
interchangeably without knowing which one it holds.
"""

from __future__ import annotations

import asyncio
import ipaddress
import re
from typing import Any, Callable, Dict, List, Optional, Tuple
from urllib.parse import urlsplit

from constants import INTIFACE_WS_URL
from intiface_discovery import IntifaceFinder

DEFAULT_PORT = 12345

# A host name as people type them: "pixel-7", "phone.local", "my.host".
_HOSTNAME = re.compile(r"^(?=.{1,253}$)[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?"
                       r"(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?)*\.?$")

# The first look for a phone, when the finder has only just started: how long
# the first attempt may wait for an mDNS answer before trying this PC.
_FIRST_LOOK_S = 1.2


def normalize_address(text: Any) -> Optional[str]:
    """What the user typed -> the stored form, or None if it isn't an address.

    "" (nothing typed) stays "" -- find Intiface by itself. Otherwise
    "host:port" ("[v6]:port" for IPv6), with port 12345 when none is given;
    a "ws://" in front and a trailing "/" are dropped, "wss://" is kept."""
    raw = str(text if text is not None else "").strip()
    if not raw:
        return ""
    secure = False
    low = raw.lower()
    if low.startswith("wss://"):
        secure, raw = True, raw[6:]
    elif low.startswith("ws://"):
        raw = raw[5:]
    elif "://" in raw:
        return None                     # http://, https:// … aren't Buttplug
    raw = raw.rstrip("/")
    if not raw or any(c.isspace() for c in raw) or "/" in raw:
        return None
    try:
        parts = urlsplit("//" + raw)
        host = parts.hostname
        port = parts.port
    except ValueError:                  # a port out of range, a broken [v6]
        return None
    if not host or parts.username or parts.password:
        return None
    port = DEFAULT_PORT if port is None else port
    if not 0 < port < 65536:
        return None
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        ip = None
        if not _HOSTNAME.match(host):
            return None
    shown = f"[{host}]" if ip is not None and ip.version == 6 else host
    form = f"{shown}:{port}"
    return f"wss://{form}" if secure else form


def address_url(address: str) -> str:
    """A stored address (normalize_address's form) -> the URL to dial."""
    return address if address.startswith("wss://") else f"ws://{address}"


def _url_where(url: str) -> str:
    """ws://192.168.1.50:12345 -> '192.168.1.50:12345' for people."""
    for prefix in ("ws://", "wss://"):
        if url.startswith(prefix):
            return url[len(prefix):]
    return url


class ExternalIntifaceConnection:
    """Connect to a user-run Intiface Central, here or on the network. Owns
    no server; while no address is typed it owns the mDNS finder."""

    mode = "external"

    def __init__(self, log: Optional[Callable[[str], None]] = None,
                 address: str = "",
                 finder_factory: Optional[Callable[..., Any]] = None) -> None:
        self._log = log if callable(log) else (lambda _m: None)
        # A setting that doesn't parse (hand-edited file) means "find it".
        self.address = normalize_address(address) or ""
        self._finder_factory = finder_factory or IntifaceFinder
        self._finder = None
        self._finder_failed = False
        self._turn = 0
        self._good: Optional[str] = None
        self._target: Optional[Tuple[str, str]] = None
        self._said: set = set()

    @property
    def status_label(self) -> str:
        # Matches the historical connection-status text so the UI reads
        # identically when the user is in external mode.
        return "Intiface"

    async def prepare(self) -> str:
        """Return the websocket URL to dial. No server is started here — if
        nothing answers there, the Buttplug client's connect() raises and the
        controller's auto-reconnect loop retries (with the next guess, when
        none is typed)."""
        if self.address:
            target = (address_url(self.address), "")
        else:
            await self._ensure_finder()
            candidates = self._candidates()
            target = candidates[self._turn % len(candidates)]
            self._turn += 1
        self._target = target
        url, name = target
        if url not in self._said:       # once per place, not every retry
            self._said.add(url)
            self._log(f"Connecting to Intiface {self._where(url, name)}…")
        return url

    def note_connected(self) -> None:
        """The engine's word that the last URL worked: next time (a drop,
        a reconnect) it goes first."""
        if self._target is not None:
            self._good = self._target[0]
        self._turn = 0

    def _where(self, url: str, name: str) -> str:
        if url == INTIFACE_WS_URL:
            return "on this PC"
        if name:
            return f"at {_url_where(url)} ({name}, found on your network)"
        return f"at {_url_where(url)}"

    def _candidates(self) -> List[Tuple[str, str]]:
        out: List[Tuple[str, str]] = []
        seen = set()
        finder = self._finder
        for s in (finder.servers() if finder is not None else []):
            url = f"ws://{s['host']}:{s['port']}"
            if url not in seen:
                seen.add(url)
                out.append((url, str(s["name"])))
        if INTIFACE_WS_URL not in seen:
            out.append((INTIFACE_WS_URL, ""))
        good = [c for c in out if c[0] == self._good]
        return good + [c for c in out if c[0] != self._good]

    async def _ensure_finder(self) -> None:
        if self._finder is not None or self._finder_failed:
            return
        finder = self._finder_factory(log=self._log)
        loop = asyncio.get_running_loop()
        try:
            ok = await loop.run_in_executor(None, finder.start)
        except Exception:
            ok = False
        if not ok:
            self._finder_failed = True
            return
        self._finder = finder
        # On the first look, give a phone's answer a moment so the first
        # attempt goes to it rather than to this PC.
        waited = 0.0
        while waited < _FIRST_LOOK_S and not finder.servers():
            await asyncio.sleep(0.1)
            waited += 0.1

    def describe(self) -> Dict[str, Any]:
        """Primitives for Settings: what is typed, what is being dialled and
        what the network shows."""
        finder = self._finder
        found = [dict(s) for s in (finder.servers() if finder is not None else [])]
        url, name = self._target if self._target is not None else ("", "")
        return {
            "address": self.address,
            "auto": not self.address,
            "searching": finder is not None,
            "target": _url_where(url) if url else "",
            "target_local": url == INTIFACE_WS_URL,
            "target_name": name,
            "found": found,
        }

    def _drop_finder(self):
        finder, self._finder = self._finder, None
        return finder

    async def shutdown(self) -> None:
        """Stop looking for Intiface on the network -- we never owned a
        server."""
        finder = self._drop_finder()
        if finder is not None:
            loop = asyncio.get_running_loop()
            try:
                await loop.run_in_executor(None, finder.close)
            except Exception:
                pass

    def terminate(self) -> None:
        """Sync teardown for the app-quit path."""
        finder = self._drop_finder()
        if finder is not None:
            finder.close()
