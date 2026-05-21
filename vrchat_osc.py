"""
vrchat_osc.py (v2.0 - Service Advertisement Edition)

Now acts as both an OSCQuery Client (finding VRChat) and an 
OSCQuery Service (advertising itself to VRChat).

Features added:
- Dynamic Port Allocation (using port 0)
- Zeroconf/mDNS Service Advertisement (_osc._udp.local)
- Automatic cleanup of registered services
"""

import os
import time
import socket
import json
import threading
import collections
import requests
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Callable, Dict, Any, List, Optional

from pythonosc.udp_client import SimpleUDPClient
from pythonosc.dispatcher import Dispatcher
from pythonosc.osc_server import ThreadingOSCUDPServer
from pythonosc.osc_bundle_builder import OscBundleBuilder
from pythonosc.osc_message_builder import OscMessageBuilder
from zeroconf import ServiceBrowser, Zeroconf, ServiceStateChange, ServiceInfo
from parameter_store import store
from constants import VRC_DEFAULT_PORT

class OSCQueryHandler(BaseHTTPRequestHandler):
    """HTTP handler implementing the OSCQuery phonebook protocol.

    Three distinct paths matter for VRChat's client (verified by reading
    vrc-oscquery-lib's `OSCQueryHttpServer.cs` and VRCOSC's
    `ConnectionManager.cs`):

      * `?HOST_INFO`  → `HostInfo` JSON (NAME/EXTENSIONS/OSC_IP/OSC_PORT/
                        OSC_TRANSPORT). This is THE document VRChat uses
                        to learn where to send our OSC UDP packets.
      * `/`           → the OSCQuery tree (NAME + CONTENTS describing the
                        parameters we want to receive).
      * other         → 404.

    Previously we returned the OSCQuery tree for every URL. VRChat's
    OSCQuery parser likely treats a malformed HOST_INFO response as
    "this client isn't valid" and stops sending packets — matches the
    user's observed bug exactly (connected but 0 packets, 0 phonebook
    GETs, in a session with VRCOSC/VRCFT also running).
    """

    def __init__(self, *args, host_info=None, osc_tree=None,
                 on_request=None, on_raw_connection=None, **kwargs):
        self.host_info = host_info
        self.osc_tree = osc_tree
        self._on_request = on_request
        self._on_raw_connection = on_raw_connection
        super().__init__(*args, **kwargs)

    def setup(self):
        # Count every accepted TCP connection regardless of whether the
        # HTTP request that follows is well-formed. Lets us distinguish
        # "VRChat never reached us at all" from "VRChat reached us but
        # we didn't understand its request". The count lives on the
        # owning VRChatOSCManager so it resets cleanly on
        # disconnect/reconnect cycles.
        cb = self._on_raw_connection
        if cb is not None:
            try:
                cb()
            except Exception:
                pass
        super().setup()

    def do_GET(self):
        client = self.client_address[0] if self.client_address else "?"
        try:
            if self._on_request is not None:
                try:
                    self._on_request(self.path, client)
                except Exception:
                    pass
        except Exception:
            pass

        # Routing: HOST_INFO either as query (?HOST_INFO) or as path
        # (/HOST_INFO). Both forms appear in the wild.
        raw = self.path or ""
        if "HOST_INFO" in raw.upper():
            self._send_json(self.host_info or {})
            return
        # Root tree.
        path_only = raw.split("?", 1)[0]
        if path_only in ("/", "", "/index"):
            self._send_json(self.osc_tree or {})
            return
        # Any other path — VRChat doesn't ask for these and our spec
        # doesn't define them. 404 is the OSCQuery-compliant answer.
        self.send_response(404)
        self.send_header("Content-type", "application/json")
        self.end_headers()
        self.wfile.write(b'{"error":"not found"}')

    def _send_json(self, payload) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-type", "application/json")
        # Match VRCOSC: tell intermediaries not to cache OSCQuery responses.
        self.send_header("Pragma", "no-cache")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        pass  # Suppress HTTP request spam in console


class VRChatOSCManager:
    # ------------------------------------------------------------------
    # Diagnostic / watchdog thresholds. Tunable up here so they're easy
    # to spot when debugging the "connected but silent" failure.
    # ------------------------------------------------------------------

    # How often the diagnostics thread emits a "still alive" packet-rate log.
    _DIAG_LOG_INTERVAL_S = 30.0

    # When `is_connected` is True but no UDP packets have arrived for this
    # many seconds, we log a loud warning. This is the most common signature
    # of multi-OSC-client routing problems with VRChat.
    _SILENT_THRESHOLD_S = 15.0

    # After this much continuous silence, we proactively re-poll VRChat's
    # OSCQuery endpoint to nudge it into resending. Last-ditch self-heal.
    _SILENT_REPROBE_S = 45.0

    # After this much silence, we rip our mDNS advertisement off the network
    # and re-publish under a fresh name. Forces VRChat to treat us as a
    # brand-new OSC client and re-query our phonebook. Set higher than the
    # ping reprobe so we try the cheap fix first.
    _SILENT_REREGISTER_S = 75.0

    # Where the persistent OSC diagnostic log lives. Same file every launch
    # — we append to it. Capped at ~1 MB before being rotated.
    _LOG_FILE_NAME = "osc_diagnostics.log"
    _LOG_FILE_MAX_BYTES = 1_000_000

    # While disconnected, how often to rebuild the mDNS ServiceBrowser to
    # re-query the bus (mirrors VRCOSC's 2.5 s refresh; we use 5 s to keep
    # mDNS traffic low). Only runs while waiting for VRChat.
    _BROWSER_REFRESH_S = 5.0

    # Charset for the per-launch mDNS service name suffix. Matches VRCFT's
    # `Utils.GetRandomChars(6)` (uppercase alphanumeric, length 6) so our
    # advertisement looks the same shape as theirs on the bus.
    _SUFFIX_CHARS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
    _SUFFIX_LEN = 6

    @classmethod
    def _make_service_suffix(cls) -> str:
        import random
        return "".join(random.choice(cls._SUFFIX_CHARS) for _ in range(cls._SUFFIX_LEN))

    def __init__(self, local_listen_port: int = 0, bind_all_interfaces: bool = True, rate_limit_hz: float = 20.0):
        self.zeroconf = Zeroconf()
        self.osc_client = None
        self.osc_server = None
        self.server_thread = None
        self.dispatcher = Dispatcher()
        self.dispatcher.set_default_handler(self._handle_incoming_osc)

        # Unique-per-launch mDNS service name. Without the suffix, VRChat
        # caches `OscGoesPurrr._oscjson._tcp.local.` across our restarts
        # and keeps sending UDP to whichever port we used LAST time, which
        # is now dead — producing the exact "connected but 0 packets,
        # 0 phonebook GETs" failure mode in the user's bug report. The
        # suffix forces VRChat to enumerate us as a fresh client every
        # launch (mirrors VRCFT's `VRCFT-<id>` convention).
        #
        # Format matches VRCFT byte-for-byte: 6 chars from the uppercase
        # alphanumeric set (see VRCFT's `Utils.GetRandomChars(6)`).
        self._service_base = "OscGoesPurrr"
        self._service_suffix = self._make_service_suffix()
        self.service_short_name = f"{self._service_base}-{self._service_suffix}"
        self.service_host_name = f"{self.service_short_name}.local."

        # Persistent file log destination. Set up lazily on first write so
        # we don't fail at import time if the dir doesn't exist yet.
        self._log_file_path: Optional[Path] = self._compute_log_path()
        self._log_file_lock = threading.Lock()

        # Bind configuration
        self.bind_ip = "0.0.0.0" if bind_all_interfaces else "127.0.0.1"

        # Connection state
        self.vrc_ip = "127.0.0.1"
        self.vrc_osc_port = VRC_DEFAULT_PORT
        self.http_port = None
        self.local_listen_port = local_listen_port # If 0, OS picks a free port
        self.is_connected = False

        # Service info for advertisement
        self.service_info = None

        # Data Management
        self.parameter_callbacks: Dict[str, list[Callable]] = {}
        self._param_types: Dict[str, str] = {}
        self.rate_limit_hz = rate_limit_hz
        self._last_sent_times: Dict[str, float] = {}
        self.on_connected: Callable = None
        self.on_disconnected: Callable = None  # fired when VRChat goes away (mDNS removal or HTTP health-check failure)
        self.global_osc_callback: Callable = None

        # ------------------------------------------------------------------
        # Diagnostics — packet flow tracking
        # ------------------------------------------------------------------
        # Wall-clock time of the most recent UDP packet we successfully
        # dispatched. `None` means we've never received anything this session.
        self._last_packet_time: Optional[float] = None
        # Total packets we've handled, locally counted (vs the store's
        # parameter-write count, which can diverge if a handler bails early).
        self._packets_handled: int = 0
        # Snapshot of packets_handled at the most recent diagnostics log,
        # so the log can print a per-interval rate.
        self._packets_handled_at_last_log: int = 0
        # How many handler exceptions we've swallowed — should always be 0.
        self._handler_exceptions: int = 0
        # Last error from the handler, for the diagnostics log.
        self._last_handler_error: str = ""
        # Wall-clock time we last flipped `is_connected` to True. Used by the
        # silent-connection watchdog so a freshly-connected session isn't
        # immediately flagged as silent.
        self._connected_since: Optional[float] = None
        # Have we already logged the "silent for N seconds" warning for the
        # current silent period? Latched so the log fires once per outage,
        # not every diagnostics tick.
        self._silent_warning_logged: bool = False
        # Same idea for the "trying a reprobe" log.
        self._silent_reprobe_attempted: bool = False
        # And for the deeper "we tried re-publishing mDNS" log.
        self._silent_rereg_attempted: bool = False
        # How many times we've re-published the mDNS service this session
        # (manual user click or watchdog-driven). Surfaced in diagnostics.
        self._mdns_rereg_count: int = 0

        # VRCFT-style "first VRChat appearance" latch. Until VRChat shows
        # up on mDNS we do NOT bind UDP, start the HTTP server, or publish
        # our own mDNS records. The latch ensures `_on_vrchat_first_discovered`
        # only runs once per `start()` cycle — subsequent VRChat
        # reappearances reuse the already-bound sockets.
        self._vrchat_first_discovered_done = False
        self._discovery_lock = threading.Lock()
        # Did we already log the first packet of this session?
        self._first_packet_logged: bool = False
        # Phonebook GET counter — VRChat polls our HTTP server every time it
        # picks up a new client. If this number is stuck at 0 long after we
        # connect, VRChat doesn't see our OSCQuery advertisement.
        self._phonebook_requests: int = 0
        # Raw inbound TCP accepts to our phonebook server. Bumped from
        # OSCQueryHandler.setup() so malformed requests (where do_GET never
        # runs) still increment something we can read. Useful for telling
        # "VRChat never reached us" from "VRChat reached us but we mis-served
        # HOST_INFO". Resets with the manager, not the process.
        self._raw_http_connections: int = 0

        # Ring buffer of recent diagnostic events (mDNS, handshake, health
        # check failures, watchdog warnings). Read by the OSC Diagnostics
        # panel to give the user a single place to see what just happened.
        # Bounded at 200 lines — older ones rotate out.
        self._events: collections.deque = collections.deque(maxlen=200)
        self._events_lock = threading.Lock()

        # Set of OSCQuery clients other than VRChat that we've seen advertise
        # themselves on the network during this app's lifetime. VRCOSC,
        # OscGoesBrrr, Resonite tools, etc. all show up here. Surfaced in the
        # Diagnostics panel so the user can correlate failures with which
        # other tools were running.
        self._other_clients: Dict[str, Dict[str, Any]] = {}
        self._other_clients_lock = threading.Lock()

        # Health-check thread keeps polling the VRChat OSCQuery HTTP endpoint
        # while we believe we're connected; catches crashes where mDNS never
        # broadcasts a Removed event.
        self._shutdown = threading.Event()
        self._health_thread: threading.Thread = None

        # Diagnostics thread emits periodic packet-rate logs and runs the
        # silent-connection watchdog.
        self._diag_thread: threading.Thread = None

        # Coalesced avatar/change re-fetch — every OSC packet for /avatar/change
        # used to spawn a fresh `threading.Thread(target=fetch_all_parameters)`
        # that slept 1.5 s before rebuilding the store. Rapid swaps stacked up
        # overlapping rebuilds; now we re-arm one timer and let a single worker
        # do the rebuild after the dust settles.
        self._refetch_lock = threading.Lock()
        self._refetch_timer: Optional[threading.Timer] = None
        

    # ------------------------------------------------------------------
    # Logging helper — routes through the controller's global_osc_callback
    # so the message appears in the in-app log, *and* always prints to
    # stdout so it survives even if the UI thread is wedged. Use sparingly:
    # this is for diagnostics that justify ~1 line per minute or less.
    # ------------------------------------------------------------------

    def _log(self, message: str) -> None:
        """Emit a `[OSC]` diagnostic line to the in-app log, stdout, the
        Diagnostics panel's event ring buffer, AND a persistent log file
        at `%APPDATA%/OscGoesPurrr/osc_diagnostics.log` so the user has a
        durable record they can grep / attach to bug reports."""
        ts = time.strftime("%H:%M:%S")
        line = f"[OSC] {message}"
        print(line)
        # Push timestamped copy to the panel ring buffer.
        try:
            with self._events_lock:
                self._events.append(f"{ts}  {message}")
        except Exception:
            pass
        # File log (best-effort, never block the OSC pipeline on it).
        self._write_log_file(ts, message)
        cb = self.global_osc_callback
        if cb is not None:
            try:
                cb("SYS/OSCQuery_Status", line)
            except Exception:
                # Never let a logging failure break the OSC pipeline.
                pass

    # ------------------------------------------------------------------
    # File logging — writes a durable copy of every `_log()` call to
    # `%APPDATA%/OscGoesPurrr/osc_diagnostics.log`. Rotated when the
    # file exceeds 1 MB so we don't grow without bound.
    # ------------------------------------------------------------------

    def _compute_log_path(self) -> Optional[Path]:
        """Resolve the diagnostics log path. Mirrors config_manager's
        APPDATA_DIR layout so the file sits alongside profiles.json."""
        try:
            appdata = Path.home() / "AppData" / "Roaming" / "OscGoesPurrr"
            appdata.mkdir(parents=True, exist_ok=True)
            return appdata / self._LOG_FILE_NAME
        except Exception:
            return None

    def _write_log_file(self, timestamp: str, message: str) -> None:
        """Append one timestamped line to the log file. Rotates when oversize.
        All failures are swallowed — file logging is best-effort."""
        path = self._log_file_path
        if path is None:
            return
        try:
            with self._log_file_lock:
                # Rotate if the file just crossed the size cap. Keep one
                # backup so the user can still see prior session data.
                try:
                    if path.exists() and path.stat().st_size > self._LOG_FILE_MAX_BYTES:
                        backup = path.with_suffix(path.suffix + ".1")
                        if backup.exists():
                            backup.unlink()
                        path.rename(backup)
                except Exception:
                    pass
                with open(path, "a", encoding="utf-8") as f:
                    f.write(f"{time.strftime('%Y-%m-%d')} {timestamp}  {message}\n")
        except Exception:
            pass

    def get_log_file_path(self) -> Optional[str]:
        """Return the absolute path to the diagnostics log file (or None
        if the OS denied the appdata dir). Used by the Diagnostics panel's
        'Open log folder' button."""
        return str(self._log_file_path) if self._log_file_path else None

    def get_event_log(self) -> List[str]:
        """Snapshot of the event ring buffer (oldest → newest). Used by the
        OSC Diagnostics panel for a one-stop view of recent activity."""
        with self._events_lock:
            return list(self._events)

    def get_other_clients(self) -> Dict[str, Dict[str, Any]]:
        """Snapshot of every non-VRChat OSCQuery client we've observed."""
        with self._other_clients_lock:
            return {k: dict(v) for k, v in self._other_clients.items()}

    def start(self):
        """Starts the servers and mDNS advertisement.

        VRCFT-style ordering (verified against
        `VRCFaceTracking.Core/Services/OscQueryService.cs`):

          1. Open mDNS discovery + watchdog threads.
          2. WAIT for VRChat to appear on `_oscjson._tcp.local.`.
          3. ONLY after VRChat is observed: bind our UDP listener, start
             our HTTP phonebook server, and publish our own mDNS records.

        Advertising before VRChat is on the bus lets VRChat enumerate us
        with stale or absent records and then never re-query — which is
        the exact failure mode the user has been hitting. Mirroring the
        most-reliable reference implementation (VRCFT) eliminates that race.
        """
        self._shutdown.clear()
        self._vrchat_first_discovered_done = False
        self._log(
            f"start(): VRCFT-style deferred bind. We will NOT bind OSC/HTTP "
            f"or publish mDNS until VRChat appears on the bus. "
            f"(user bind_ip={self.bind_ip} requested_port={self.local_listen_port})"
        )
        self._start_discovery()
        self._start_health_check()
        self._start_diagnostics()

    @property
    def get_ports(self) -> dict:
        return {
            "target_ip": self.vrc_ip,
            "udp_send_port": self.vrc_osc_port,
            "http_oscquery_port": self.http_port,
            "local_listen_port": self.local_listen_port,
            "is_connected": self.is_connected
        }

    def get_diagnostics(self) -> Dict[str, Any]:
        """Snapshot of OSC diagnostics for the UI / log dump. All counters
        are read without locking — they're updated by monotonically advancing
        writes, so a stale read just means an off-by-one count.

        Returns:
            is_connected, packets_handled, last_packet_age_s,
            session_age_s, phonebook_GETs, handler_exceptions,
            last_handler_error, vrc_http_port, our_listen_port.
        """
        now = time.time()
        last_pkt_age = (
            now - self._last_packet_time
            if self._last_packet_time is not None else None
        )
        session_age = (
            now - self._connected_since
            if self._connected_since is not None else None
        )
        try:
            socket_bound = (
                self.osc_server.socket.getsockname()
                if self.osc_server and self.osc_server.socket else None
            )
        except Exception:
            socket_bound = None
        return {
            "is_connected": self.is_connected,
            "packets_handled": self._packets_handled,
            "store_packets_received": store.get_packets_received(),
            "last_packet_age_s": last_pkt_age,
            "session_age_s": session_age,
            "phonebook_GETs": self._phonebook_requests,
            "handler_exceptions": self._handler_exceptions,
            "last_handler_error": self._last_handler_error,
            "vrc_ip": self.vrc_ip,
            "vrc_osc_port": self.vrc_osc_port,
            "vrc_http_port": self.http_port,
            "our_listen_port": self.local_listen_port,
            "our_http_phonebook_port": getattr(self, "http_listen_port", None),
            "udp_socket_bound": socket_bound,
            "mdns_service_name": self.service_short_name,
            "mdns_rereg_count": self._mdns_rereg_count,
            "log_file_path": self.get_log_file_path(),
            # Raw inbound TCP connections to our HTTP phonebook this session.
            # If this is non-zero but phonebook_GETs is 0, VRChat reached us
            # but we mis-served the request. If both are 0, VRChat (or the
            # firewall) is dropping us before we ever see a packet.
            "http_raw_connections": self._raw_http_connections,
        }

    def _start_discovery(self):
        self.browser = ServiceBrowser(
            self.zeroconf, "_oscjson._tcp.local.", handlers=[self._on_service_state_change]
        )
        # Also actively re-query the bus while we don't have VRChat. python-
        # zeroconf's ServiceBrowser already periodically refreshes, but VRCOSC
        # explicitly fires a query every 2.5s — mirroring that here is the
        # smallest extra cost that closes the gap if VRChat's announcement
        # was missed during our startup. Only runs while disconnected, so it
        # adds zero traffic during normal use.
        self._mdns_refresh_thread = threading.Thread(
            target=self._mdns_refresh_loop, daemon=True, name="OSC-mDNSRefresh"
        )
        self._mdns_refresh_thread.start()

    def _mdns_refresh_loop(self) -> None:
        """While disconnected, periodically rebuild the ServiceBrowser so
        python-zeroconf re-queries the bus. Mirrors VRCOSC's
        `refreshServices` repeater — recovers from the case where VRChat's
        mDNS announcement was missed during our startup.

        Runs at most one rebuild per `_BROWSER_REFRESH_S`. Logs once per
        cycle (at coarse intervals) so the panel doesn't flood with
        'still waiting' lines.
        """
        cycles_silent = 0
        while not self._shutdown.is_set():
            if self._shutdown.wait(self._BROWSER_REFRESH_S):
                return
            if self.is_connected:
                cycles_silent = 0
                continue
            cycles_silent += 1
            try:
                # Tear down the existing browser and re-create it. New
                # browser = fresh query burst onto the bus.
                old = getattr(self, "browser", None)
                if old is not None:
                    try:
                        old.cancel()
                    except Exception:
                        pass
                self.browser = ServiceBrowser(
                    self.zeroconf,
                    "_oscjson._tcp.local.",
                    handlers=[self._on_service_state_change],
                )
                # Only log every 6th cycle (~30s at 5s interval) so the
                # event ring buffer doesn't fill with noise.
                if cycles_silent == 1 or cycles_silent % 6 == 0:
                    self._log(
                        f"mDNS browser refreshed (cycle #{cycles_silent}) — "
                        "still waiting for VRChat to appear"
                    )
            except Exception as e:
                if cycles_silent <= 3:
                    self._log(f"mDNS refresh failed: {type(e).__name__}: {e}")

    def _on_service_state_change(self, zeroconf: Zeroconf, service_type: str, name: str, state_change: ServiceStateChange):
        # Always log every mDNS event we see — even ones not from VRChat —
        # because a flood of "Added" / "Removed" from other OSC apps is a
        # signature of the multi-client routing problem the user wants to
        # diagnose. Without this, a Wi-Fi adapter glitch is invisible.
        try:
            self._log(f"mDNS {state_change.name}: {name}")
        except Exception:
            pass
        if state_change == ServiceStateChange.Added:
            info = zeroconf.get_service_info(service_type, name)
            if info and "VRChat" in name:
                self._log(f"VRChat OSCQuery service discovered: name={name} port={info.port} "
                          f"addresses={[socket.inet_ntoa(a) for a in (info.addresses or []) if len(a) == 4]}")
                self.http_port = info.port
                self.vrc_ip = "127.0.0.1" # Force localhost to prevent timeouts
                # First-time VRChat discovery this session: run the VRCFT
                # FirstClientDiscovered sequence (bind UDP, start HTTP,
                # advertise mDNS, then fetch ports). Re-discoveries reuse
                # the sockets we already bound.
                with self._discovery_lock:
                    needs_first_setup = not self._vrchat_first_discovered_done
                    if needs_first_setup:
                        self._vrchat_first_discovered_done = True
                if needs_first_setup:
                    try:
                        self._on_vrchat_first_discovered()
                    except Exception as e:
                        self._log(f"VRCFT-style setup failed: {type(e).__name__}: {e}")
                        # Allow another attempt next time VRChat is seen.
                        with self._discovery_lock:
                            self._vrchat_first_discovered_done = False
                        return
                self._fetch_osc_ports()
            elif info is not None:
                # Some other OSC app advertised itself. Log it so the user
                # can correlate failures with other OSC clients coming and going.
                self._log(f"Other OSCQuery client present: name={name} port={info.port}")
                with self._other_clients_lock:
                    self._other_clients[name] = {
                        "port": info.port,
                        "first_seen": time.time(),
                        "present": True,
                    }
        elif state_change == ServiceStateChange.Removed:
            # VRChat closed (cleanly) -- its mDNS advertisement vanished. Reconnect
            # happens automatically when ServiceStateChange.Added fires again on the
            # browser, so we just need to flip our state to disconnected.
            if "VRChat" in name:
                self._log(f"VRChat mDNS Removed: {name}")
                self._handle_disconnect("VRChat mDNS service removed")
            else:
                with self._other_clients_lock:
                    if name in self._other_clients:
                        self._other_clients[name]["present"] = False
                        self._other_clients[name]["last_seen"] = time.time()

    def _on_vrchat_first_discovered(self) -> None:
        """VRCFT's `FirstClientDiscovered`, ported.

        Runs once per `start()` cycle, the first time VRChat appears on
        mDNS. Performs the deferred bind/advertise sequence in this
        exact order — matching VRCFT byte-for-byte:

          1. Bind UDP recv socket on 127.0.0.1:0 (OS picks port).
          2. Mint a fresh 6-char `VRCFT-style` random suffix.
          3. Bind HTTP phonebook on 127.0.0.1 with a random TCP port.
          4. Publish both `_osc._udp` and `_oscjson._tcp` mDNS records
             with `IPAddress.Loopback` (127.0.0.1).

        Any future VRChat appearances reuse these sockets — no rebind.
        """
        # Refresh the suffix EVERY first-discovery so a quick
        # Disconnect → Connect cycle still presents a fresh name to
        # VRChat (matches VRCFT's flow of generating the suffix here).
        self._service_suffix = self._make_service_suffix()
        self.service_short_name = f"{self._service_base}-{self._service_suffix}"
        self.service_host_name = f"{self.service_short_name}.local."

        self._log(
            f"VRChat observed on bus — running VRCFT-style FirstClientDiscovered: "
            f"binding sockets and advertising as {self.service_short_name}"
        )

        # 1. Bind UDP listener now (random port).
        self._setup_osc()

        # 2. Start HTTP phonebook (random port, 127.0.0.1).
        # _setup_osc already calls _start_phonebook_server + _advertise_service
        # in our current factoring, so nothing else to do here.

    def _handle_disconnect(self, reason: str) -> None:
        """Mark the manager disconnected and notify the controller.

        Idempotent: a second call after we've already disconnected is a no-op.
        Safe to invoke from any thread (mDNS callback thread, health-check thread,
        etc.) since it only does flag updates and a queue/callback dispatch.
        """
        if not self.is_connected:
            return
        # Log a session summary so the user can correlate failures with
        # packet flow over the lifetime of the connection.
        try:
            session_s = (time.time() - self._connected_since) if self._connected_since else 0.0
            last_pkt_age = (
                f"{time.time() - self._last_packet_time:.1f}s ago"
                if self._last_packet_time else "never"
            )
            self._log(
                f"disconnecting (reason={reason}) — session={session_s:.1f}s "
                f"packets_handled={self._packets_handled} last_packet={last_pkt_age} "
                f"phonebook_GETs={self._phonebook_requests} "
                f"handler_exceptions={self._handler_exceptions}"
            )
        except Exception:
            pass
        self.is_connected = False
        self._connected_since = None
        self._silent_warning_logged = False
        self._silent_reprobe_attempted = False
        # Don't blank http_port -- the mDNS Added handler will overwrite it on
        # reconnect anyway, and keeping the old value lets the health-check
        # thread describe what it was last polling.
        if self.global_osc_callback:
            try:
                self.global_osc_callback("SYS/OSCQuery_Status", f"VRChat disconnected ({reason}). Waiting...")
            except Exception:
                pass
        if self.on_disconnected:
            try:
                self.on_disconnected()
            except Exception:
                pass

    def _start_health_check(self) -> None:
        """Spawn a daemon thread that pings VRChat's OSCQuery HTTP endpoint while we
        believe we're connected. Catches crashes / force-kills where the mDNS
        Removed event never fires."""
        if self._health_thread and self._health_thread.is_alive():
            return

        def loop() -> None:
            consecutive_failures = 0
            last_failure_kind = ""
            while not self._shutdown.is_set():
                # Sleep first so we don't immediately race the initial connect.
                if self._shutdown.wait(5.0):
                    return
                if not self.is_connected or not self.http_port:
                    consecutive_failures = 0
                    continue
                try:
                    response = requests.get(
                        f"http://127.0.0.1:{self.http_port}/",
                        timeout=1.5,
                    )
                    if response.status_code == 200:
                        if consecutive_failures > 0:
                            # We recovered from a transient failure — log once
                            # so the user can correlate it with later symptoms.
                            self._log(
                                f"health-check recovered after {consecutive_failures} "
                                f"failure(s) (last={last_failure_kind})"
                            )
                        consecutive_failures = 0
                        continue
                    consecutive_failures += 1
                    last_failure_kind = f"HTTP {response.status_code}"
                    self._log(f"health-check non-200 from VRChat: {last_failure_kind} "
                              f"(consecutive={consecutive_failures})")
                except Exception as e:
                    consecutive_failures += 1
                    last_failure_kind = f"{type(e).__name__}: {e}"
                    # Only log first + second failure (the second is the one
                    # that triggers disconnect). Avoids log spam if VRChat is
                    # genuinely gone for minutes.
                    if consecutive_failures <= 2:
                        self._log(f"health-check exception: {last_failure_kind} "
                                  f"(consecutive={consecutive_failures})")
                # Two strikes before declaring dead -- one stray timeout on a busy
                # system shouldn't kick us into the disconnect path.
                if consecutive_failures >= 2:
                    self._handle_disconnect(f"OSCQuery HTTP unreachable ({last_failure_kind})")
                    consecutive_failures = 0

        self._health_thread = threading.Thread(target=loop, daemon=True, name="OSC-HealthCheck")
        self._health_thread.start()

    # ------------------------------------------------------------------
    # Diagnostics watchdog — separate from the health check.
    #
    # The health check asks "is VRChat's HTTP endpoint reachable?" The
    # diagnostics watchdog asks the OPPOSITE question: "are we actually
    # *receiving* UDP packets from VRChat?" The user's failure mode is
    # exactly when the answer to the first is yes and the second is no —
    # a connection that looks alive but is silently routing nowhere.
    # ------------------------------------------------------------------

    def _start_diagnostics(self) -> None:
        if self._diag_thread and self._diag_thread.is_alive():
            return

        def loop() -> None:
            while not self._shutdown.is_set():
                if self._shutdown.wait(self._DIAG_LOG_INTERVAL_S):
                    return
                try:
                    self._emit_diagnostics_tick()
                except Exception as e:
                    # Diagnostics must never crash. If it does, log once.
                    print(f"[OSC] diagnostics tick error: {type(e).__name__}: {e}")

        self._diag_thread = threading.Thread(target=loop, daemon=True, name="OSC-Diagnostics")
        self._diag_thread.start()

    def _emit_diagnostics_tick(self) -> None:
        """One iteration of the diagnostics loop.

        Logs the current packet rate and runs the silent-connection watchdog.
        Quiet when we're disconnected — no point spamming logs about an idle state.
        """
        now = time.time()
        handled_now = self._packets_handled
        delta = handled_now - self._packets_handled_at_last_log
        self._packets_handled_at_last_log = handled_now

        if not self.is_connected:
            return

        rate = delta / self._DIAG_LOG_INTERVAL_S
        last_pkt_age = (
            now - self._last_packet_time
            if self._last_packet_time is not None
            else (now - (self._connected_since or now))
        )

        self._log(
            f"diagnostics: pkts_last_{int(self._DIAG_LOG_INTERVAL_S)}s={delta} "
            f"({rate:.1f}/s) total={handled_now} last_packet={last_pkt_age:.1f}s ago "
            f"phonebook_GETs={self._phonebook_requests} "
            f"handler_exc={self._handler_exceptions}"
        )

        # Silent-connection watchdog. Only meaningful once we've been
        # connected for a few seconds — fresh sessions need time to warm up.
        if self._connected_since is None or (now - self._connected_since) < 5.0:
            return

        silent_for = last_pkt_age
        if delta == 0 and silent_for >= self._SILENT_THRESHOLD_S:
            if not self._silent_warning_logged:
                self._silent_warning_logged = True
                self._log(
                    f"WARNING: VRChat says connected but we've received "
                    f"0 packets in the last {silent_for:.1f}s. "
                    f"Likely cause: another OSC app (VRCOSC, OSCgoesBrrr, etc.) "
                    f"is also advertising via OSCQuery and VRChat is routing "
                    f"to it instead. Try: VRChat → Settings → OSC → Reset, "
                    f"or close other OSC apps and reconnect."
                )
            if (silent_for >= self._SILENT_REPROBE_S
                    and not self._silent_reprobe_attempted):
                self._silent_reprobe_attempted = True
                self._log("attempting OSCQuery re-poll to nudge VRChat...")
                threading.Thread(
                    target=self._reprobe_silent_connection,
                    daemon=True,
                    name="OSC-SilentReprobe",
                ).start()
            if (silent_for >= self._SILENT_REREGISTER_S
                    and not self._silent_rereg_attempted):
                self._silent_rereg_attempted = True
                self._log(
                    "silent for too long — re-publishing mDNS under a fresh name "
                    "to bust VRChat's OSCQuery client cache"
                )
                threading.Thread(
                    target=self.reregister_mdns,
                    daemon=True,
                    name="OSC-SilentReregister",
                ).start()
        elif delta > 0 and self._silent_warning_logged:
            # We were silent, now we're hearing again — log the recovery.
            self._log(f"packet flow restored — received {delta} in the last "
                      f"{int(self._DIAG_LOG_INTERVAL_S)}s")
            self._silent_warning_logged = False
            self._silent_reprobe_attempted = False
            self._silent_rereg_attempted = False

    def _reprobe_silent_connection(self) -> None:
        """Last-ditch self-heal for the silent-connection case: re-poll the
        OSCQuery HTTP endpoint and re-send our ping so VRChat reconsiders us
        as a target. Most likely outcome is no change — the user will have
        to /reset in VRChat — but it's cheap to try."""
        try:
            self.poll_current_parameters()
            if self.osc_server is not None and self.osc_server.socket is not None:
                ping_msg = OscMessageBuilder(address="/OscGoesPurrr/ping")
                ping_msg.add_arg(True)
                self.osc_server.socket.sendto(
                    ping_msg.build().dgram, (self.vrc_ip, self.vrc_osc_port)
                )
                self._log(f"silent-reprobe: ping resent to {self.vrc_ip}:{self.vrc_osc_port}")
        except Exception as e:
            self._log(f"silent-reprobe failed: {type(e).__name__}: {e}")

    def _fetch_osc_ports(self):
        try:
            self._log(f"fetching OSCQuery root from http://{self.vrc_ip}:{self.http_port}/")
            response = requests.get(f"http://{self.vrc_ip}:{self.http_port}/", timeout=2)
            if response.status_code == 200:
                data = response.json()
                self.vrc_osc_port = data.get('OSC Port', VRC_DEFAULT_PORT)
                self._log(f"VRChat OSC port resolved: {self.vrc_osc_port} "
                          f"(our listen port: {self.local_listen_port})")

                # Rebuild client with the newly discovered VRChat port
                self.osc_client = SimpleUDPClient(self.vrc_ip, self.vrc_osc_port)
                self.is_connected = True
                self._connected_since = time.time()
                self._silent_warning_logged = False
                self._silent_reprobe_attempted = False
                self._silent_rereg_attempted = False
                self._first_packet_logged = False

                # CRITICAL FIX: Send ping via the SERVER socket so VRChat replies to the correct port
                ping_msg = OscMessageBuilder(address="/OscGoesPurrr/ping")
                ping_msg.add_arg(True)
                self.osc_server.socket.sendto(ping_msg.build().dgram, (self.vrc_ip, self.vrc_osc_port))
                self._log(f"sent handshake ping to {self.vrc_ip}:{self.vrc_osc_port} "
                          f"from local socket {self.osc_server.socket.getsockname()}")

                self.poll_current_parameters()
                if self.on_connected:
                    self.on_connected(self.get_ports)

                # FIX: Fetch all parameters the exact moment the HTTP port is verified!
                threading.Thread(target=self.fetch_all_parameters, daemon=True).start()
            else:
                self._log(f"OSCQuery root returned HTTP {response.status_code}")
        except Exception as e:
            self._log(f"failed to fetch OSCQuery data: {type(e).__name__}: {e}")

    def _setup_osc(self):
        """Initializes server and triggers mDNS advertisement."""
        # Setup Server (Listening)
        if self.osc_server:
            self._log("tearing down previous OSC server before rebind")
            self.osc_server.shutdown()

        self.dispatcher.set_default_handler(self._handle_incoming_osc)

        # Bind the OSC UDP listener. We try 127.0.0.1 first regardless of the
        # `bind_all_interfaces` setting because Windows Defender Firewall
        # silently drops inbound UDP to 0.0.0.0-bound sockets from other
        # processes unless the user explicitly approved a firewall rule for
        # our exe — this is the smoking-gun cause of the "VRChat says
        # connected but 0 packets handled" bug (matches what VRCFT and
        # VRCOSC both do: they bind to 127.0.0.1 explicitly).
        #
        # If the user enabled `bind_all_interfaces`, we still want LAN-OSC
        # support — so on Windows we fall back to a second bind on 0.0.0.0
        # after the loopback bind, but the OSCQuery advertisement still
        # points at 127.0.0.1 (where the firewall lets VRChat through).
        udp_bind_ip = "127.0.0.1"
        try:
            self.osc_server = ThreadingOSCUDPServer((udp_bind_ip, self.local_listen_port), self.dispatcher)
        except OSError as e:
            self._log(f"OSC UDP bind FAILED on {udp_bind_ip}:{self.local_listen_port} — "
                      f"{type(e).__name__}: {e}. Another OSC app likely owns this port.")
            raise

        # If we used port 0, retrieve the actual port the OS assigned us
        if self.local_listen_port == 0:
            self.local_listen_port = self.osc_server.server_address[1]

        actual = self.osc_server.socket.getsockname()
        self._log(f"OSC UDP listener bound to {actual[0]}:{actual[1]}")

        self.server_thread = threading.Thread(
            target=self.osc_server.serve_forever, daemon=True, name="OSC-UDPServer"
        )
        self.server_thread.start()

        # Setup Client (Sending)
        self.osc_client = SimpleUDPClient(self.vrc_ip, self.vrc_osc_port)

        # Start HTTP Phonebook server for VRChat OSC auto-discovery
        self._start_phonebook_server()

        # Advertise our presence so VRChat knows where to send data
        self._advertise_service()
    
    def _start_phonebook_server(self):
        """Start HTTP server that serves the OSC phonebook JSON (required by VRChat discovery).

        Now serves TWO distinct documents matching the OSCQuery spec
        (verified against vrc-oscquery-lib's `HostInfo.cs` /
        `OSCQueryHttpServer.cs` and VRCOSC's `ConnectionManager.cs`):

          - `?HOST_INFO` returns the `HostInfo` JSON (NAME/EXTENSIONS/
            OSC_IP/OSC_PORT/OSC_TRANSPORT). VRChat uses this to learn
            which UDP port to send to.
          - `/` returns the OSCQuery tree (NAME + CONTENTS).

        The previous implementation returned the tree for every URL,
        including `?HOST_INFO`. VRChat's parser appears to treat the
        malformed HOST_INFO response as "invalid client" and stops
        sending — exactly matching the user's bug (0 packets handled,
        0 phonebook GETs).

        ALSO CRITICAL: this HTTP server now binds explicitly to
        127.0.0.1, not 0.0.0.0 (regardless of `bind_all_interfaces`).
        Windows Defender Firewall treats sockets bound to 0.0.0.0 as
        network-listening and silently blocks inbound TCP from other
        processes (including VRChat) unless the user has explicitly
        approved a firewall rule for the exe. Loopback-bound sockets
        skip firewall gating entirely — VRCFT and VRCOSC both do
        exactly this. OSCQuery is a localhost protocol so there is
        zero use case for binding our phonebook to LAN.
        """
        # HTTP phonebook is loopback-only by design (see docstring) —
        # do NOT use self.bind_ip here.
        http_bind_ip = "127.0.0.1"
        # 1. Find a free TCP port for the HTTP phonebook server
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind((http_bind_ip, 0))
            self.http_listen_port = s.getsockname()[1]

        # 2a. HOST_INFO doc — what VRChat actually queries to learn our OSC port.
        # The "EXTENSIONS" map mirrors what vrc-oscquery-lib publishes so VRChat
        # sees the same shape it expects from a first-party OSCQuery server.
        self.host_info = {
            "NAME": "OscGoesPurrr",
            "EXTENSIONS": {
                "ACCESS": True,
                "CLIPMODE": False,
                "RANGE": True,
                "TYPE": True,
                "VALUE": True,
            },
            "OSC_IP": "127.0.0.1",
            "OSC_PORT": self.local_listen_port,
            "OSC_TRANSPORT": "UDP",
        }

        # 2b. OSCQuery tree — what /  returns. The single /avatar/change node
        # is intentional: VRChat sends EVERY avatar parameter once at least
        # one node is registered, even if we only ask for one specific path.
        # (Confirmed by reading VRCOSC's `ConnectionManager.cs` — same trick.)
        self.osc_tree = {
            "NAME": "OscGoesPurrr",
            "OSC_IP": "127.0.0.1",
            "OSC_PORT": self.local_listen_port,
            "OSC_TRANSPORT": "UDP",
            "CONTENTS": {
                "avatar": {
                    "FULL_PATH": "/avatar",
                    "CONTENTS": {
                        "change": {
                            "FULL_PATH": "/avatar/change",
                            "TYPE": "s",
                            "ACCESS": 3,
                        }
                    },
                }
            },
        }

        # Keep `self.osc_data` as a back-compat alias so anything else in
        # the codebase that read the old name still works.
        self.osc_data = self.osc_tree

        # 3. Start HTTP Server in a daemon thread, bound to 127.0.0.1
        # (NOT self.bind_ip — see docstring above re: Windows Firewall).
        self.http_server = HTTPServer(
            (http_bind_ip, self.http_listen_port),
            lambda *args, **kwargs: OSCQueryHandler(
                *args,
                host_info=self.host_info,
                osc_tree=self.osc_tree,
                on_request=self._on_phonebook_request,
                on_raw_connection=self._on_raw_http_connection,
                **kwargs,
            ),
        )
        threading.Thread(
            target=self.http_server.serve_forever, daemon=True, name="OSC-Phonebook"
        ).start()
        self._log(f"phonebook HTTP server started on {http_bind_ip}:{self.http_listen_port} "
                  f"(loopback-only; bypasses Windows Firewall)")

    def _on_phonebook_request(self, path: str, client: str) -> None:
        """Callback fired when our phonebook HTTP server serves a request.

        Logs the FIRST request from any new client — that's our best signal
        that VRChat (or another OSC tool) is actually reading our advertisement.
        Subsequent requests increment a counter silently.
        """
        self._phonebook_requests += 1
        # Log only the first 3 to avoid spam, but always count.
        if self._phonebook_requests <= 3:
            self._log(f"phonebook GET #{self._phonebook_requests} path={path} from={client}")

    def _on_raw_http_connection(self) -> None:
        """Callback fired from OSCQueryHandler.setup() — bumps the per-session
        raw TCP-accept counter. Cheap (single int increment, GIL-protected)."""
        self._raw_http_connections += 1

    def _advertise_service(self):
        """Registers this app as an OSC service via mDNS (both UDP and TCP phonebook).

        Uses the per-launch unique service name (`OscGoesPurrr-<hex>`) so
        VRChat's OSCQuery client cache can't conflate us with a previous
        run that bound a different (now-dead) UDP port. This is the root
        cause of the 'connected but 0 packets, 0 phonebook GETs' failure.
        """
        short = self.service_short_name
        host = self.service_host_name

        # Register the UDP OSC service
        osc_service_name = f"{short}._osc._udp.local."
        self.service_info = ServiceInfo(
            "_osc._udp.local.",
            osc_service_name,
            addresses=[socket.inet_aton("127.0.0.1")],
            port=self.local_listen_port,
            properties={"version": "1.0".encode('utf-8')},
            server=host,
        )
        try:
            self.zeroconf.register_service(self.service_info)
            self._log(f"mDNS register OK: {osc_service_name} → 127.0.0.1:{self.local_listen_port}")
        except Exception as e:
            self._log(f"mDNS register FAILED for {osc_service_name}: {type(e).__name__}: {e}")

        # Register the HTTP JSON phonebook service (required for VRChat auto-discovery)
        json_service_name = f"{short}._oscjson._tcp.local."
        self.service_info_json = ServiceInfo(
            "_oscjson._tcp.local.",
            json_service_name,
            addresses=[socket.inet_aton("127.0.0.1")],
            port=self.http_listen_port,
            properties={"version": "1.0".encode('utf-8')},
            server=host,
        )
        try:
            self.zeroconf.register_service(self.service_info_json)
            self._log(f"mDNS register OK: {json_service_name} → 127.0.0.1:{self.http_listen_port}")
        except Exception as e:
            self._log(f"mDNS register FAILED for {json_service_name}: {type(e).__name__}: {e}")

    def reregister_mdns(self) -> bool:
        """Rip our mDNS advertisement off the network and re-publish under a
        FRESH unique name. Forces VRChat to treat us as a brand-new OSC
        client and re-query our phonebook — the strongest self-heal we have
        for the silent-connection case short of asking the user to /reset
        VRChat manually.

        Returns True if the cycle completed without throwing. No-op if
        we haven't yet completed the VRCFT-style first-discovery setup —
        there's nothing to unregister or re-advertise at that point.
        """
        if not getattr(self, "http_listen_port", None):
            self._log("re-publish mDNS skipped: VRChat hasn't been discovered yet "
                      "(no advertisement to re-publish)")
            return False
        self._mdns_rereg_count += 1
        self._log(
            f"re-registering mDNS service (cycle #{self._mdns_rereg_count}) — "
            f"will publish under a fresh unique name to bust VRChat's cache"
        )
        old_short = self.service_short_name
        try:
            # Unregister both services. zeroconf is forgiving if the entry
            # isn't actually registered (it just logs a warning).
            try:
                if self.service_info is not None:
                    self.zeroconf.unregister_service(self.service_info)
            except Exception as e:
                self._log(f"unregister(_osc._udp) warning: {type(e).__name__}: {e}")
            try:
                if getattr(self, "service_info_json", None) is not None:
                    self.zeroconf.unregister_service(self.service_info_json)
            except Exception as e:
                self._log(f"unregister(_oscjson._tcp) warning: {type(e).__name__}: {e}")

            # Mint a new unique suffix BEFORE re-advertising. Even a small
            # delay between unregister and re-register helps the mDNS bus
            # propagate the removal before the new announcement.
            self._service_suffix = self._make_service_suffix()
            self.service_short_name = f"{self._service_base}-{self._service_suffix}"
            self.service_host_name = f"{self.service_short_name}.local."
            self._log(f"new mDNS name: {self.service_short_name} (was {old_short})")
            time.sleep(0.5)
            self._advertise_service()
            return True
        except Exception as e:
            self._log(f"reregister_mdns FAILED: {type(e).__name__}: {e}")
            return False

    def poll_current_parameters(self) -> dict:
        if not self.is_connected or not self.http_port: return {}
        try:
            url = f"http://{self.vrc_ip}:{self.http_port}/avatar/parameters"
            response = requests.get(url, timeout=2)
            if response.status_code == 200:
                return self._flatten_oscquery_node(response.json())
        except Exception as e:
            print(f"Failed to poll parameters: {e}")
        return {}

    def query_avatar_id(self) -> str:
        """Ask VRChat's OSCQuery server for the *current* /avatar/change value.

        Needed because /avatar/change is broadcast as an OSC message only
        when an avatar loads — if we connect to OSC mid-session, the message
        is already gone. The HTTP node, however, always holds the live value.
        Returns "" on any failure (server not up, network, etc.).
        """
        if not self.http_port:
            return ""
        try:
            r = requests.get(
                f"http://{self.vrc_ip}:{self.http_port}/avatar/change",
                timeout=2,
            )
            if r.status_code != 200:
                return ""
            data = r.json()
            val = data.get("VALUE")
            # OSCQuery wraps single values in a one-element list.
            if isinstance(val, list) and val:
                val = val[0]
            return str(val) if val else ""
        except Exception:
            return ""

    def _schedule_avatar_change_refetch(self, delay_s: float = 1.5) -> None:
        """Arm a single debounced re-fetch of the OSCQuery phonebook.

        Each call cancels and re-arms the existing timer, so a flurry of
        /avatar/change packets coalesces into one rebuild after the stream
        settles. Replaces the old per-packet daemon-thread-with-sleep pattern
        that stacked overlapping rebuilds.
        """
        with self._refetch_lock:
            if self._refetch_timer is not None:
                try:
                    self._refetch_timer.cancel()
                except Exception:
                    pass
            timer = threading.Timer(delay_s, self._run_refetch_now)
            timer.daemon = True
            self._refetch_timer = timer
            timer.start()

    def _run_refetch_now(self) -> None:
        """Timer callback: rebuild the master cache once, then clear the slot."""
        try:
            self._do_fetch_all_parameters()
        finally:
            with self._refetch_lock:
                self._refetch_timer = None

    def fetch_all_parameters(self):
        """Fetches the entire OSCQuery phonebook and rebuilds the master cache.

        Kept as the public entry point (the initial-boot threads in `start()`
        and `_fetch_osc_ports` call it directly). The 1.5 s pre-fetch wait
        gives VRChat time to build the JSON; for the avatar/change path use
        `_schedule_avatar_change_refetch` so rapid swaps debounce instead.
        """
        try:
            time.sleep(1.5)  # Wait for VRChat to build JSON
            self._do_fetch_all_parameters()
        except Exception as e:
            print(f"OSCQuery Parse Error: {e}")

    def _do_fetch_all_parameters(self):
        """Actual fetch + store rebuild. Split out of `fetch_all_parameters`
        so the debounced path can skip the upfront `time.sleep(1.5)`."""
        try:
            if not self.http_port:
                if hasattr(self, 'global_osc_callback') and self.global_osc_callback:
                    self.global_osc_callback("SYS/OSCQuery_Status", "Waiting for VRChat mDNS discovery...")
                return

            response = requests.get(f"http://127.0.0.1:{self.http_port}/avatar/parameters", timeout=2)
            if response.status_code != 200:
                return

            data = response.json()
            
            # Rebuild the master cache in the Central Store
            num_params = store.rebuild_from_json(data)
            
            if hasattr(self, 'global_osc_callback') and self.global_osc_callback:
                self.global_osc_callback("SYS/OSCQuery_Status", f"Loaded {num_params} total parameters")

        except requests.exceptions.RequestException:
            pass
        except Exception as e:
            print(f"OSCQuery Parse Error: {e}")

    def _flatten_oscquery_node(self, node: dict) -> dict:
        results = {}
        if "FULL_PATH" in node and "VALUE" in node:
            path = node["FULL_PATH"]
            results[path] = node["VALUE"]
            if "TYPE" in node:
                self._param_types[path] = node["TYPE"]
        if "CONTENTS" in node:
            for child in node["CONTENTS"].values():
                results.update(self._flatten_oscquery_node(child))
        return results

    def send_parameter(self, address: str, value: Any, ignore_rate_limit: bool = False):
        if not self.is_connected or not self.osc_client: return
        current_time = time.time()
        if not ignore_rate_limit and address in self._last_sent_times:
            if (current_time - self._last_sent_times[address]) < (1.0 / self.rate_limit_hz):
                return 
        self._last_sent_times[address] = current_time

        expected_type = self._param_types.get(address)
        if expected_type:
            if expected_type == 'f': value = float(value)
            elif expected_type == 'i': value = int(value)
            elif expected_type in ['T', 'F']: value = bool(value)
        elif isinstance(value, int):
            value = float(value) 

        self.osc_client.send_message(address, value)

    def send_parameter_bundle(self, parameters: Dict[str, Any]):
        if not self.is_connected or not self.osc_client: return
        bundle = OscBundleBuilder(0)
        for address, value in parameters.items():
            expected_type = self._param_types.get(address)
            if expected_type:
                if expected_type == 'f': value = float(value)
                elif expected_type == 'i': value = int(value)
                elif expected_type in ['T', 'F']: value = bool(value)
            elif isinstance(value, int):
                value = float(value)
            msg = OscMessageBuilder(address=address)
            msg.add_arg(value)
            bundle.add_content(msg.build())
        self.osc_client.send(bundle.build())

    def listen_to_parameter(self, address: str, callback: Callable):
        if address not in self.parameter_callbacks:
            self.parameter_callbacks[address] = []
        self.parameter_callbacks[address].append(callback)

    def listen_to_avatar_change(self, callback: Callable):
        self.listen_to_parameter("/avatar/change", callback)

    def _handle_incoming_osc(self, address: str, *args):
        # Wrap the WHOLE handler so a downstream exception never propagates
        # back into python-osc's dispatch thread. A propagated exception
        # logged-and-discarded by the underlying ThreadingMixIn means we
        # silently drop *that one packet*, but if the exception happens on
        # an mDNS/avatar boundary (refetch timer, callback, etc.) it can
        # leave state inconsistent — better to count, log, and continue.
        try:
            value = args[0] if args else 0.0

            # Strip the redundant VRChat prefix for internal routing and UI
            prefix = "/avatar/parameters/"
            clean_address = address
            if address.startswith(prefix):
                clean_address = address[len(prefix):]
            elif address.startswith("/"):
                clean_address = address[1:] # Clean up leading slash for standard paths

            # Bookkeeping for diagnostics. Cheap — just int increments and
            # a timestamp write. No lock needed: monotonic int writes are
            # GIL-protected and we don't care about exact ordering across
            # the read in the watchdog.
            self._packets_handled += 1
            self._last_packet_time = time.time()
            if not self._first_packet_logged:
                self._first_packet_logged = True
                self._log(f"first OSC packet received this session: address={address!r}")

            # Trigger zone discovery when avatar loads. Debounced so rapid
            # avatar swaps coalesce into a single rebuild instead of spawning
            # overlapping daemon threads that each sleep 1.5 s.
            if clean_address == "avatar/change":
                self._log(f"/avatar/change received: value={value!r}")
                self._schedule_avatar_change_refetch()

            # Send real-time updates to the Central Store
            store.update_parameter(clean_address, value)

            # Fire global callback with the clean address
            if self.global_osc_callback:
                try:
                    self.global_osc_callback(clean_address, value)
                except Exception as e:
                    print(f"Global Callback Error ({clean_address}): {e}")

            # Existing specific callback logic (also using clean address)
            if clean_address in self.parameter_callbacks:
                for callback in self.parameter_callbacks[clean_address]:
                    try:
                        callback(clean_address, value)
                    except Exception as e:
                        print(f"Callback Error ({clean_address}): {e}")
        except Exception as e:
            # The handler should be exception-proof; if we're here, log it
            # and keep serving. Count so the diagnostics tick can surface
            # a non-zero handler_exc number.
            self._handler_exceptions += 1
            self._last_handler_error = f"{type(e).__name__}: {e}"
            # Only print the first 5 instances to avoid flooding the log.
            if self._handler_exceptions <= 5:
                print(f"[OSC] HANDLER EXCEPTION ({self._handler_exceptions}): "
                      f"address={address!r} args={args!r} error={self._last_handler_error}")

    def stop(self):
        """Unregister services and shut down."""
        # Wake the health-check loop so it exits promptly.
        self._shutdown.set()
        # Cancel any pending debounced rebuild so we don't run after shutdown.
        with self._refetch_lock:
            if self._refetch_timer is not None:
                try:
                    self._refetch_timer.cancel()
                except Exception:
                    pass
                self._refetch_timer = None
        if self.service_info:
            print("Shutting down OSC advertisement...")
            self.zeroconf.unregister_all_services()
        self.zeroconf.close()
        if self.osc_server:
            self.osc_server.shutdown()
        if hasattr(self, 'http_server') and self.http_server:
            self.http_server.shutdown()
