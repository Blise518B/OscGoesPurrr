"""
vrchat_osc.py (v2.0 - Service Advertisement Edition)

Now acts as both an OSCQuery Client (finding VRChat) and an 
OSCQuery Service (advertising itself to VRChat).

Features added:
- Dynamic Port Allocation (using port 0)
- Zeroconf/mDNS Service Advertisement (_osc._udp.local)
- Automatic cleanup of registered services
"""

import time
import socket
import json
import threading
import requests
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Callable, Dict, Any

from pythonosc.udp_client import SimpleUDPClient
from pythonosc.dispatcher import Dispatcher
from pythonosc.osc_server import ThreadingOSCUDPServer
from pythonosc.osc_bundle_builder import OscBundleBuilder
from pythonosc.osc_message_builder import OscMessageBuilder
from zeroconf import ServiceBrowser, Zeroconf, ServiceStateChange, ServiceInfo

class OSCQueryHandler(BaseHTTPRequestHandler):
    """HTTP handler that serves the OSC phonebook JSON to VRChat."""
    def __init__(self, *args, osc_data=None, **kwargs):
        self.osc_data = osc_data
        super().__init__(*args, **kwargs)
    
    def do_GET(self):
        self.send_response(200)
        self.send_header('Content-type', 'application/json')
        self.end_headers()
        self.wfile.write(json.dumps(self.osc_data).encode('utf-8'))
    
    def log_message(self, format, *args):
        pass  # Suppress HTTP request spam in console


class VRChatOSCManager:
    def __init__(self, local_listen_port: int = 0, bind_all_interfaces: bool = True, rate_limit_hz: float = 20.0):
        self.zeroconf = Zeroconf()
        self.osc_client = None
        self.osc_server = None
        self.server_thread = None
        self.dispatcher = Dispatcher()
        self.dispatcher.set_default_handler(self._handle_incoming_osc)
        
        # Bind configuration
        self.bind_ip = "0.0.0.0" if bind_all_interfaces else "127.0.0.1"
        
        # Connection state
        self.vrc_ip = "127.0.0.1"
        self.vrc_osc_port = 9000
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
        self.global_osc_callback: Callable = None

    def start(self):
        """Starts the servers and mDNS advertisement."""
        self._setup_osc()
        self._start_discovery()

    @property
    def get_ports(self) -> dict:
        return {
            "target_ip": self.vrc_ip,
            "udp_send_port": self.vrc_osc_port,
            "http_oscquery_port": self.http_port,
            "local_listen_port": self.local_listen_port,
            "is_connected": self.is_connected
        }

    def _start_discovery(self):
        self.browser = ServiceBrowser(
            self.zeroconf, "_oscjson._tcp.local.", handlers=[self._on_service_state_change]
        )

    def _on_service_state_change(self, zeroconf: Zeroconf, service_type: str, name: str, state_change: ServiceStateChange):
        if state_change == ServiceStateChange.Added:
            info = zeroconf.get_service_info(service_type, name)
            if info and "VRChat" in name:
                self.http_port = info.port
                self.vrc_ip = "127.0.0.1" # Force localhost to prevent timeouts
                self._fetch_osc_ports()

    def _fetch_osc_ports(self):
        try:
            response = requests.get(f"http://{self.vrc_ip}:{self.http_port}/", timeout=2)
            if response.status_code == 200:
                data = response.json()
                self.vrc_osc_port = data.get('OSC Port', 9000)
                
                # Rebuild client with the newly discovered VRChat port
                self.osc_client = SimpleUDPClient(self.vrc_ip, self.vrc_osc_port)
                self.is_connected = True
                
                # CRITICAL FIX: Send ping via the SERVER socket so VRChat replies to the correct port
                ping_msg = OscMessageBuilder(address="/OscGoesPurrr/ping")
                ping_msg.add_arg(True)
                self.osc_server.socket.sendto(ping_msg.build().dgram, (self.vrc_ip, self.vrc_osc_port))
                
                self.poll_current_parameters()
                if self.on_connected:
                    self.on_connected(self.get_ports)
        except Exception as e:
            print(f"Failed to fetch OSCQuery data: {e}")

    def _setup_osc(self):
        """Initializes server and triggers mDNS advertisement."""
        # Setup Server (Listening)
        if self.osc_server:
            self.osc_server.shutdown()
            
        self.dispatcher.set_default_handler(self._handle_incoming_osc)
        
        # Bind to configured interface (0.0.0.0 for all, 127.0.0.1 for localhost only)
        self.osc_server = ThreadingOSCUDPServer((self.bind_ip, self.local_listen_port), self.dispatcher)
        
        # If we used port 0, retrieve the actual port the OS assigned us
        if self.local_listen_port == 0:
            self.local_listen_port = self.osc_server.server_address[1]
            
        self.server_thread = threading.Thread(target=self.osc_server.serve_forever, daemon=True)
        self.server_thread.start()
        
        # Setup Client (Sending)
        self.osc_client = SimpleUDPClient(self.vrc_ip, self.vrc_osc_port)

        # Start HTTP Phonebook server for VRChat OSC auto-discovery
        self._start_phonebook_server()

        # Advertise our presence so VRChat knows where to send data
        self._advertise_service()
    
    def _start_phonebook_server(self):
        """Start HTTP server that serves the OSC phonebook JSON (required by VRChat discovery)."""
        # 1. Find a free TCP port for the HTTP phonebook server
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind((self.bind_ip, 0))
            self.http_listen_port = s.getsockname()[1]
        
        # 2. Build the JSON phonebook data (flat structure matching OSCQuery spec)
        self.osc_data = {
            "NAME": "OscGoesPurrr",
            "OSC_IP": "0.0.0.0",
            "OSC_PORT": self.local_listen_port,
            "OSC_TRANSPORT": "UDP",
            "CONTENTS": {
                "avatar": {
                    "FULL_PATH": "/avatar",
                    "CONTENTS": {
                        "change": {
                            "FULL_PATH": "/avatar/change",
                            "TYPE": "s",
                            "ACCESS": 3
                        }
                    }
                }
            }
        }
        
        # 3. Start HTTP Server in a daemon thread
        self.http_server = HTTPServer(
            (self.bind_ip, self.http_listen_port),
            lambda *args, **kwargs: OSCQueryHandler(*args, osc_data=self.osc_data, **kwargs)
        )
        threading.Thread(target=self.http_server.serve_forever, daemon=True).start()
        print(f"📋 Phonebook HTTP server started on port {self.http_listen_port}")

    def _advertise_service(self):
        """Registers this app as an OSC service via mDNS (both UDP and TCP phonebook)."""
        # Register the UDP OSC service
        osc_service_name = "OscGoesPurrr._osc._udp.local."
        self.service_info = ServiceInfo(
            "_osc._udp.local.",
            osc_service_name,
            addresses=[socket.inet_aton("127.0.0.1")],
            port=self.local_listen_port,
            properties={"version": "1.0".encode('utf-8')},
            server="OscGoesPurrr.local."
        )
        print(f"📢 Advertising OSC Service: {osc_service_name} on port {self.local_listen_port}")
        self.zeroconf.register_service(self.service_info)
        
        # Register the HTTP JSON phonebook service (required for VRChat auto-discovery)
        json_service_name = "OscGoesPurrr._oscjson._tcp.local."
        self.service_info_json = ServiceInfo(
            "_oscjson._tcp.local.",
            json_service_name,
            addresses=[socket.inet_aton("127.0.0.1")],
            port=self.http_listen_port,
            properties={"version": "1.0".encode('utf-8')},
            server="OscGoesPurrr.local."
        )
        print(f"📢 Advertising OSCJSON Service: {json_service_name} on port {self.http_listen_port}")
        self.zeroconf.register_service(self.service_info_json)

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
        value = args[0] if args else 0.0

        # Fire global callback if it exists
        if self.global_osc_callback:
            try:
                self.global_osc_callback(address, value)
            except Exception as e:
                print(f"Global Callback Error ({address}): {e}")

        # Existing specific callback logic
        if address in self.parameter_callbacks:
            for callback in self.parameter_callbacks[address]:
                try:
                    callback(address, value)
                except Exception as e:
                    print(f"Callback Error ({address}): {e}")

    def stop(self):
        """Unregister services and shut down."""
        if self.service_info:
            print("Shutting down OSC advertisement...")
            self.zeroconf.unregister_all_services()
        self.zeroconf.close()
        if self.osc_server:
            self.osc_server.shutdown()
        if hasattr(self, 'http_server') and self.http_server:
            self.http_server.shutdown()
