# OscGoesPurrr - finding Intiface Central on the network
"""
Finds Intiface servers on the local network by the mDNS service they
announce themselves: `_intiface_engine._tcp`. Intiface Central does that when
its Settings -> Show Advanced/Experimental Settings -> "Broadcast Server Info
via mDNS" is on (on phones since Central 3.1). The engine announces port
12345 and a `path=/` TXT record (crates/intiface_engine/src/mdns.rs).

Only listening, never knocking: an Intiface server takes exactly one TCP
connection and stops when it isn't a Buttplug handshake (see the note in
intiface_integrated.py), so a port probe or a sweep of the network would
switch off the very server we're looking for. The only thing that ever
connects to a found server is the real Buttplug client.

`IntifaceFinder` runs one zeroconf ServiceBrowser on its own threads (the
browser re-asks by itself, with growing gaps) and keeps what it has seen.
It is created only while OGP connects to an Intiface it doesn't run itself
and no address is typed, so the built-in engine's users never pay for it.
"""

from __future__ import annotations

import ipaddress
import threading
import time
from typing import Callable, Dict, List, Optional

SERVICE_TYPE = "_intiface_engine._tcp.local."

# How long a resolve may take (ms) -- runs on the browser's own thread.
_RESOLVE_TIMEOUT_MS = 1500


def instance_label(name: str) -> str:
    """'Intiface Ab12Cd._intiface_engine._tcp.local.' -> 'Intiface Ab12Cd'."""
    text = str(name or "")
    if text.endswith("." + SERVICE_TYPE):
        text = text[: -len(SERVICE_TYPE) - 1]
    return text.strip() or "Intiface"


def _usable_ipv4(addresses) -> List[str]:
    """The IPv4 addresses worth dialling, private (home network) ones first.
    Link-local (169.254.x) and loopback ones from another machine are no
    use from here."""
    out = []
    for raw in addresses or ():
        try:
            ip = ipaddress.ip_address(raw)
        except ValueError:
            continue
        if ip.version != 4 or ip.is_link_local or ip.is_loopback or ip.is_unspecified:
            continue
        out.append(ip)
    out.sort(key=lambda ip: (not ip.is_private, str(ip)))
    return [str(ip) for ip in out]


class IntifaceFinder:
    """Keeps the Intiface servers mDNS has shown, newest first.

    Thread-safe: zeroconf calls in on its own threads, the engine loop and
    the UI read `servers()`."""

    def __init__(self, zeroconf_factory: Optional[Callable[[], object]] = None,
                 log: Optional[Callable[[str], None]] = None) -> None:
        self._log = log if callable(log) else (lambda _m: None)
        self._lock = threading.Lock()
        self._found: Dict[str, Dict[str, object]] = {}
        self._zc = None
        self._browser = None
        self._closed = False
        self._factory = zeroconf_factory

    def start(self) -> bool:
        """Start browsing. False (and a log line) if mDNS can't be used here
        -- the typed address still works then."""
        try:
            from zeroconf import ServiceBrowser, Zeroconf
            self._zc = self._factory() if self._factory else Zeroconf()
            self._browser = ServiceBrowser(self._zc, SERVICE_TYPE,
                                           handlers=[self._on_change])
            return True
        except Exception as e:
            self._log(f"Can't look for Intiface on the network (mDNS): {e}")
            self.close()
            return False

    def _on_change(self, zeroconf, service_type, name, state_change) -> None:
        kind = getattr(state_change, "name", str(state_change))
        if kind == "Removed":
            with self._lock:
                self._found.pop(name, None)
            return
        if self._closed:
            return
        try:
            info = zeroconf.get_service_info(service_type, name, timeout=_RESOLVE_TIMEOUT_MS)
        except Exception:
            info = None
        if info is None:
            return
        try:
            addresses = info.parsed_addresses()
        except Exception:
            addresses = []
        hosts = _usable_ipv4(addresses)
        if not hosts:
            return
        self.add(name, hosts, int(info.port or 12345))

    def add(self, name: str, hosts: List[str], port: int) -> None:
        """Note one server (also how tests feed the finder)."""
        with self._lock:
            new = name not in self._found
            self._found[name] = {"name": instance_label(name), "hosts": list(hosts),
                                 "port": int(port), "seen": time.monotonic()}
        if new:
            self._log(f"Found {instance_label(name)} on your network "
                      f"({hosts[0]}:{int(port)}).")

    def servers(self) -> List[Dict[str, object]]:
        """[{name, host, port}], one per address, the newest server first."""
        with self._lock:
            entries = sorted(self._found.values(), key=lambda e: -float(e["seen"]))
        out = []
        for e in entries:
            for host in e["hosts"]:
                out.append({"name": e["name"], "host": host, "port": e["port"]})
        return out

    def close(self) -> None:
        """Stop browsing. Idempotent; blocks briefly while zeroconf closes."""
        self._closed = True
        browser, self._browser = self._browser, None
        zc, self._zc = self._zc, None
        if browser is not None:
            try:
                browser.cancel()
            except Exception:
                pass
        if zc is not None:
            try:
                zc.close()
            except Exception:
                pass
