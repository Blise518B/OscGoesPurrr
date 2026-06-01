"""VRChat-impersonating network layer for the simulator.

Pretends to be a VRChat client on the loopback network so OscGoesPurrr
discovers it via the same mDNS + OSCQuery path it uses with the real
game. Exposes a callback-based API the UI layer subscribes to.

Wire protocol mirrors what `vrchat_osc.py` reads:

  1. We advertise `_oscjson._tcp.local.` as `VRChat-Client-Sim-XXXX...`
     so OGP's mDNS browser picks us up (its filter is `"VRChat" in name`).
  2. We run an HTTP OSCQuery server that responds to:
       ?HOST_INFO       → JSON with our OSC_PORT
       /                → full tree
       /avatar/parameters → parameters subtree (what OGP polls on connect)
       /avatar/change   → current avatar id node
  3. We listen for inbound UDP OSC on the port we advertised.
  4. We browse `_osc._udp.local.` to find OGP's listening port, then
     send UDP OSC at it for every avatar-parameter change.
"""

from __future__ import annotations

import json
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any, Callable, Dict, List, Optional, Tuple

from pythonosc.dispatcher import Dispatcher
from pythonosc.osc_server import ThreadingOSCUDPServer
from pythonosc.udp_client import SimpleUDPClient
from zeroconf import ServiceBrowser, ServiceInfo, ServiceStateChange, Zeroconf

from . import sim_avatar


_SERVICE_BASE = "VRChat-Client-Sim"
_AVATAR_PARAM_PREFIX = "/avatar/parameters/"

# Re-send current params to the active target this often (seconds). Real VRChat
# streams OSC continuously; apps like OSC Goes Brrr only leave their
# "waiting for first packet" state once a UDP packet actually arrives, so an
# idle simulator that sent only on change would never connect them.
_HEARTBEAT_INTERVAL_S = 1.0


def _random_suffix(n: int = 6) -> str:
    import random
    chars = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
    return "".join(random.choice(chars) for _ in range(n))


class _OSCQueryHandler(BaseHTTPRequestHandler):
    """HTTP handler bound to a VRChatSimNetwork instance via the `server`
    attribute (set when the server is instantiated)."""

    def do_GET(self):  # noqa: N802 — stdlib API
        net: "VRChatSimNetwork" = self.server.network  # type: ignore[attr-defined]
        raw = self.path or ""
        # HOST_INFO either as query string or path segment.
        if "HOST_INFO" in raw.upper():
            self._send_json(net.host_info())
            return
        path_only = raw.split("?", 1)[0]
        if path_only in ("/", "", "/index"):
            self._send_json(net.root_tree())
            return
        sub = sim_avatar.get_subtree(net.root_tree(), path_only)
        if sub is not None:
            self._send_json(sub)
            return
        self.send_response(404)
        self.send_header("Content-type", "application/json")
        self.end_headers()
        self.wfile.write(b'{"error":"not found"}')

    def _send_json(self, payload: Any) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-type", "application/json")
        self.send_header("Pragma", "no-cache")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):  # silence stdlib's stderr spam
        pass


class _SimHTTPServer(HTTPServer):
    """HTTPServer subclass that carries a back-pointer to its owning
    network object so request handlers can reach the live OSCQuery tree."""

    def __init__(self, addr, handler_cls, network: "VRChatSimNetwork"):
        super().__init__(addr, handler_cls)
        self.network = network


class VRChatSimNetwork:
    """The full VRChat-side network impersonation.

    Lifecycle:
        net = VRChatSimNetwork(...)
        net.start()                  # mDNS, HTTP, UDP listen all come up
        net.set_avatar(preset)       # build the tree from an AvatarPreset
        net.set_param("OGB/Orf/...", 0.8)  # live param push to OGP
        ...
        net.stop()
    """

    def __init__(
        self,
        on_targets_changed: Optional[Callable[[List[str]], None]] = None,
        on_target_changed: Optional[Callable[[Optional[str]], None]] = None,
        on_inbound_osc: Optional[Callable[[str, Tuple[Any, ...]], None]] = None,
        on_status: Optional[Callable[[str], None]] = None,
    ) -> None:
        self._on_targets_changed = on_targets_changed or (lambda _t: None)
        self._on_target_changed = on_target_changed or (lambda _l: None)
        self._on_inbound_osc = on_inbound_osc or (lambda _a, _v: None)
        self._on_status = on_status or (lambda _m: None)

        self._zeroconf: Optional[Zeroconf] = None
        self._http_server: Optional[_SimHTTPServer] = None
        self._http_thread: Optional[threading.Thread] = None
        self._osc_server: Optional[ThreadingOSCUDPServer] = None
        self._osc_thread: Optional[threading.Thread] = None
        self._dispatcher: Optional[Dispatcher] = None
        self._browser: Optional[ServiceBrowser] = None
        self._osc_browser: Optional[ServiceBrowser] = None
        self._service_info_json: Optional[ServiceInfo] = None
        self._service_info_udp: Optional[ServiceInfo] = None

        self._osc_listen_port: int = 0
        self._http_listen_port: int = 0
        self._service_name: str = ""

        # Universal targeting: any OSC app that advertises OSCQuery/_osc (not
        # just OGP) is discovered and listed; the user picks one, or enters a
        # manual host:port for apps that only listen on the fixed VRChat port.
        # `_discovered` maps an instance label -> (ip, port); the active target
        # is the single SimpleUDPClient we send avatar data to.
        self._discovered: Dict[str, Tuple[str, int]] = {}
        self._target_client: Optional[SimpleUDPClient] = None
        self._target_label: Optional[str] = None
        self._user_selected = False  # True once the user picks explicitly
        self._target_lock = threading.Lock()

        # Heartbeat thread: re-streams current param values to the active
        # target so receivers reliably get their "first packet" (and stay
        # alive) even when no signal is being driven. See _heartbeat_loop.
        self._stop_heartbeat = threading.Event()
        self._heartbeat_thread: Optional[threading.Thread] = None

        # The current avatar's OSCQuery root + the {short_name: (type, value)} map.
        # Both protected by _tree_lock since the HTTP handler and UI thread
        # both read/write them.
        self._avatar: Optional[sim_avatar.AvatarPreset] = None
        self._params: Dict[str, Tuple[str, Any]] = {}
        self._root: Dict[str, Any] = {
            "NAME": "VRChat-Client-Sim",
            "OSC_IP": "127.0.0.1",
            "OSC_PORT": 0,
            "OSC_TRANSPORT": "UDP",
        }
        self._tree_lock = threading.Lock()

    # -------------------------------------------------------------- lifecycle
    def start(self) -> None:
        self._zeroconf = Zeroconf()
        self._bind_udp()
        self._start_http()
        self._advertise()
        self._start_browsers()
        self._start_heartbeat()
        self._on_status(
            f"Listening on OSC UDP 127.0.0.1:{self._osc_listen_port}, "
            f"HTTP 127.0.0.1:{self._http_listen_port} as {self._service_name}"
        )

    def stop(self) -> None:
        self._stop_heartbeat.set()
        # Browsers / zeroconf
        try:
            if self._browser is not None:
                self._browser.cancel()
        except Exception:
            pass
        try:
            if self._osc_browser is not None:
                self._osc_browser.cancel()
        except Exception:
            pass
        try:
            if self._zeroconf is not None:
                try:
                    self._zeroconf.unregister_all_services()
                except Exception:
                    pass
                self._zeroconf.close()
        except Exception:
            pass
        # HTTP
        try:
            if self._http_server is not None:
                self._http_server.shutdown()
                self._http_server.server_close()
        except Exception:
            pass
        # UDP OSC
        try:
            if self._osc_server is not None:
                self._osc_server.shutdown()
                self._osc_server.server_close()
        except Exception:
            pass
        # Target client socket
        with self._target_lock:
            client = self._target_client
            self._target_client = None
        self._close_client(client)

    # -------------------------------------------------------------- bindings
    def _bind_udp(self) -> None:
        # Choose a free loopback port and bind a python-osc dispatcher to it.
        self._dispatcher = Dispatcher()
        self._dispatcher.set_default_handler(self._on_udp)
        self._osc_server = ThreadingOSCUDPServer(("127.0.0.1", 0), self._dispatcher)
        self._osc_listen_port = self._osc_server.server_address[1]
        self._osc_thread = threading.Thread(
            target=self._osc_server.serve_forever, daemon=True, name="VRSim-UDP"
        )
        self._osc_thread.start()

    def _start_http(self) -> None:
        # Loopback-only HTTP phonebook — same trick as the real OGP does for
        # itself; loopback bypasses Windows Firewall completely.
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("127.0.0.1", 0))
            self._http_listen_port = s.getsockname()[1]
        self._http_server = _SimHTTPServer(
            ("127.0.0.1", self._http_listen_port), _OSCQueryHandler, self
        )
        self._http_thread = threading.Thread(
            target=self._http_server.serve_forever, daemon=True, name="VRSim-HTTP"
        )
        self._http_thread.start()
        with self._tree_lock:
            self._root["OSC_PORT"] = self._osc_listen_port

    def _advertise(self) -> None:
        assert self._zeroconf is not None
        suffix = _random_suffix()
        self._service_name = f"{_SERVICE_BASE}-{suffix}"
        host = f"{self._service_name}.local."
        addr = socket.inet_aton("127.0.0.1")

        # _oscjson._tcp.local. — what OGP's browser keys on.
        self._service_info_json = ServiceInfo(
            "_oscjson._tcp.local.",
            f"{self._service_name}._oscjson._tcp.local.",
            addresses=[addr],
            port=self._http_listen_port,
            properties={"version": b"1.0"},
            server=host,
        )
        # _osc._udp.local. — published the same way real VRChat does, so
        # tools that browse the UDP form see us too.
        self._service_info_udp = ServiceInfo(
            "_osc._udp.local.",
            f"{self._service_name}._osc._udp.local.",
            addresses=[addr],
            port=self._osc_listen_port,
            properties={"version": b"1.0"},
            server=host,
        )
        try:
            self._zeroconf.register_service(self._service_info_json)
            self._zeroconf.register_service(self._service_info_udp)
        except Exception as exc:
            self._on_status(f"mDNS register failed: {type(exc).__name__}: {exc}")

    def _start_browsers(self) -> None:
        assert self._zeroconf is not None
        # Browse both service types so we can find any OSC target (OGP or
        # otherwise) regardless of which one it advertises first.
        self._osc_browser = ServiceBrowser(
            self._zeroconf, "_osc._udp.local.", handlers=[self._on_service_change]
        )
        self._browser = ServiceBrowser(
            self._zeroconf, "_oscjson._tcp.local.", handlers=[self._on_service_change]
        )

    # ------------------------------------------------------------- heartbeat
    def _start_heartbeat(self) -> None:
        self._stop_heartbeat.clear()
        self._heartbeat_thread = threading.Thread(
            target=self._heartbeat_loop, daemon=True, name="VRSim-Heartbeat"
        )
        self._heartbeat_thread.start()

    def _heartbeat_loop(self) -> None:
        """Re-blast current param values (without /avatar/change) to the active
        target on a low-rate timer. Mirrors VRChat's continuous stream so a
        receiver reliably leaves "waiting for first packet" once it is up, and
        stays connected while idle. It does NOT touch the bench's input trace,
        so latency measurement is unaffected (that keys on the signal driver)."""
        while not self._stop_heartbeat.wait(_HEARTBEAT_INTERVAL_S):
            with self._target_lock:
                active = self._target_client is not None
            if active:
                self._blast_avatar_state(skip_change=True)

    # ------------------------------------------------------------- discovery
    @staticmethod
    def _instance_label(name: str, service_type: str) -> str:
        """The advertised instance name without its `.<service_type>` suffix,
        so the same app seen via `_osc._udp` and `_oscjson._tcp` dedupes to one
        entry in the target list."""
        suffix = "." + service_type
        return name[:-len(suffix)] if name.endswith(suffix) else name

    def _is_self(self, name: str) -> bool:
        """True if `name` is our own mDNS advertisement (avoids self-targeting)."""
        return bool(self._service_name) and self._service_name in name

    @staticmethod
    def _close_client(client: Optional[SimpleUDPClient]) -> None:
        """Close a UDP client's socket so re-targeting doesn't leak sockets."""
        if client is not None:
            try:
                client._sock.close()
            except Exception:
                pass

    def _on_service_change(
        self,
        zeroconf: Zeroconf,
        service_type: str,
        name: str,
        state_change: ServiceStateChange,
    ) -> None:
        # Skip our OWN advertisement; treat every other OSCQuery/_osc service as
        # a candidate target, so the simulator drives ANY VRChat-OSC consumer
        # (OGP, OSC Goes Brrr, …), not just OscGoesPurrr.
        if self._is_self(name):
            return
        label = self._instance_label(name, service_type)
        if state_change == ServiceStateChange.Added:
            info = zeroconf.get_service_info(service_type, name)
            if info is None:
                return
            port: Optional[int] = None
            if service_type == "_osc._udp.local.":
                port = info.port  # the app's OSC receive port — what we send to
            elif service_type == "_oscjson._tcp.local.":
                # OSCQuery-only advert: read HOST_INFO to learn the OSC port.
                port = self._fetch_host_info_port(info.port)
            if port:
                self._add_discovered(label, "127.0.0.1", int(port))
        elif state_change == ServiceStateChange.Removed:
            self._remove_discovered(label)

    def _fetch_host_info_port(self, http_port: int) -> Optional[int]:
        """Fetch an app's OSCQuery HOST_INFO and return its OSC_PORT (or None)."""
        import urllib.request  # lazy — keeps it off import time

        url = f"http://127.0.0.1:{http_port}/?HOST_INFO"
        try:
            with urllib.request.urlopen(url, timeout=1.5) as resp:
                if resp.status != 200:
                    return None
                data = json.loads(resp.read().decode("utf-8"))
            port = data.get("OSC_PORT")
            return port if isinstance(port, int) and port > 0 else None
        except Exception as exc:
            self._on_status(f"HOST_INFO fetch failed: {type(exc).__name__}: {exc}")
            return None

    # --------------------------------------------------------- target tracking
    def _add_discovered(self, label: str, ip: str, port: int) -> None:
        with self._target_lock:
            self._discovered[label] = (ip, port)
            names = sorted(self._discovered)
            # Auto-pick the first target found if the user hasn't chosen one,
            # so the common single-app case connects with no extra click.
            auto = not self._user_selected and self._target_client is None
        self._on_status(f"Discovered OSC target: {label} ({ip}:{port})")
        self._on_targets_changed(names)
        if auto:
            self.select_target(label)

    def _remove_discovered(self, label: str) -> None:
        with self._target_lock:
            existed = self._discovered.pop(label, None) is not None
            names = sorted(self._discovered)
            was_active = self._target_label == label
        if not existed:
            return
        self._on_status(f"OSC target vanished: {label}")
        self._on_targets_changed(names)
        if was_active:
            self.clear_target()

    def discovered_targets(self) -> List[str]:
        with self._target_lock:
            return sorted(self._discovered)

    def active_target_label(self) -> Optional[str]:
        with self._target_lock:
            return self._target_label

    def select_target(self, label: str, user: bool = False) -> bool:
        """Send avatar data to a discovered target. False if the label is gone."""
        with self._target_lock:
            endpoint = self._discovered.get(label)
            if endpoint is None:
                return False
            ip, port = endpoint
            old = self._target_client
            self._target_client = SimpleUDPClient(ip, port)
            self._target_label = label
            if user:
                self._user_selected = True
        self._close_client(old)
        self._on_status(f"Targeting {label} ({ip}:{port})")
        self._on_target_changed(label)
        # Push the avatar id + every known parameter so the target's cache is
        # hot without waiting for its debounced HTTP refetch.
        self._blast_avatar_state()
        return True

    def set_manual_target(self, host: str, port: int) -> None:
        """Send to an explicit host:port (e.g. the fixed VRChat port 9000) for
        apps that don't advertise OSCQuery over mDNS."""
        label = f"Manual {host}:{int(port)}"
        with self._target_lock:
            old = self._target_client
            self._target_client = SimpleUDPClient(host, int(port))
            self._target_label = label
            self._user_selected = True
        self._close_client(old)
        self._on_status(f"Targeting {label}")
        self._on_target_changed(label)
        self._blast_avatar_state()

    def clear_target(self) -> None:
        with self._target_lock:
            old = self._target_client
            self._target_client = None
            self._target_label = None
        if old is not None:
            self._close_client(old)
            self._on_status("Target cleared")
            self._on_target_changed(None)

    # ---------------------------------------------------------------- inbound
    def _on_udp(self, address: str, *args: Any) -> None:
        try:
            self._on_inbound_osc(address, args)
        except Exception as exc:
            self._on_status(f"inbound callback failed: {type(exc).__name__}: {exc}")

    # ---------------------------------------------------------- avatar state
    def set_avatar(self, preset: sim_avatar.AvatarPreset) -> None:
        """Rebuild the OSCQuery tree from a fresh avatar preset and tell the target."""
        params = sim_avatar.build_params(preset)
        with self._tree_lock:
            self._avatar = preset
            self._params = params
            self._root = sim_avatar.build_oscquery_root(
                name="VRChat-Client-Sim",
                osc_ip="127.0.0.1",
                osc_port=self._osc_listen_port,
                avatar_id=preset.avatar_id,
                params=params,
            )
        self._on_status(f"Avatar set: {preset.display_name} ({preset.avatar_id})")
        # Tell the target an avatar swap happened — apps debounce + re-poll.
        self._send_osc("/avatar/change", preset.avatar_id)
        # Then send all the initial parameter values so OGP has fresh data
        # right away. The real VRChat does this on avatar load too.
        self._blast_avatar_state(skip_change=True)

    def current_avatar(self) -> Optional[sim_avatar.AvatarPreset]:
        with self._tree_lock:
            return self._avatar

    def current_params(self) -> Dict[str, Tuple[str, Any]]:
        with self._tree_lock:
            return dict(self._params)

    def set_param(self, short_name: str, value: Any) -> None:
        """Update one avatar parameter both in the OSCQuery tree (for any
        future HTTP poll) and over UDP (for live routing). No-op on
        unknown names."""
        with self._tree_lock:
            entry = self._params.get(short_name)
            if entry is None:
                return
            type_code, _ = entry
            self._params[short_name] = (type_code, value)
            sim_avatar.update_value(
                self._root, f"{_AVATAR_PARAM_PREFIX}{short_name}", value
            )
        self._send_osc(f"{_AVATAR_PARAM_PREFIX}{short_name}", value)

    def _blast_avatar_state(self, skip_change: bool = False) -> None:
        """Fire every known parameter at the active target via UDP. Used right
        after selecting a target or an avatar swap so the receiver's cache is
        hot without waiting for its debounced HTTP refetch."""
        with self._tree_lock:
            avatar = self._avatar
            params = dict(self._params)
        if avatar is None:
            return
        if not skip_change:
            self._send_osc("/avatar/change", avatar.avatar_id)
        for short_name, (type_code, value) in params.items():
            self._send_osc(f"{_AVATAR_PARAM_PREFIX}{short_name}", value)

    def resend_all(self) -> None:
        """Public re-blast trigger — UI calls this when the user clicks
        the 'Resend All Params' button."""
        self._blast_avatar_state()

    # ---------------------------------------------------------------- sending
    def _send_osc(self, address: str, value: Any) -> None:
        with self._target_lock:
            client = self._target_client
        if client is None:
            return
        try:
            # python-osc accepts native bool/float/int/str. Booleans encode as
            # the T/F type tag, which receivers decode the same way as a >0.5
            # float — matches real VRChat behaviour.
            client.send_message(address, value)
        except Exception as exc:
            self._on_status(f"send_osc failed: {type(exc).__name__}: {exc}")

    # ------------------------------------------------------------- HTTP/HOST
    def host_info(self) -> Dict[str, Any]:
        """The HOST_INFO doc — OGP reads this to learn our OSC_PORT."""
        return {
            "NAME": "VRChat-Client-Sim",
            "EXTENSIONS": {
                "ACCESS": True,
                "CLIPMODE": False,
                "RANGE": True,
                "TYPE": True,
                "VALUE": True,
            },
            "OSC_IP": "127.0.0.1",
            "OSC_PORT": self._osc_listen_port,
            "OSC_TRANSPORT": "UDP",
        }

    def root_tree(self) -> Dict[str, Any]:
        """Snapshot of the full OSCQuery root (safe to serialise on the HTTP
        thread without holding the tree lock for the duration of the dump)."""
        with self._tree_lock:
            # json.dumps will deep-walk anyway; making a shallow copy of the
            # outer dict is enough to drop the lock without races.
            return dict(self._root)

    # ----------------------------------------------------------------- debug
    def listen_info(self) -> Dict[str, Any]:
        """Status snapshot for the UI footer."""
        with self._target_lock:
            target = self._target_label
        return {
            "service_name": self._service_name,
            "osc_listen_port": self._osc_listen_port,
            "http_listen_port": self._http_listen_port,
            "target": target,
        }
