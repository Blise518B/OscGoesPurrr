"""OSC controller facade.

Mixin: VRChat OSC connection lifecycle + diagnostics. Composed into
OscGoesPurrrApp. Relies on `self.osc_manager`, `self.log_message`,
`self.ui`, `self.profile_manager`, `self.thread_queue`."""

import threading
from typing import Any, Dict, List

from vrchat_osc import VRChatOSCManager


class OscFacade:

    def get_osc_diagnostics(self) -> Dict[str, Any]:
        """Facade: dump VRChat OSC manager diagnostics. Empty dict when the
        manager isn't running yet. UI panels (or the user manually triggering
        a dump) can show this to debug the 'connected but silent' failure."""
        if not getattr(self, "osc_manager", None):
            return {}
        try:
            return self.osc_manager.get_diagnostics()
        except Exception as e:
            return {"error": f"{type(e).__name__}: {e}"}

    def log_osc_diagnostics(self) -> None:
        """Dump the OSC diagnostics dict to the in-app log on demand.
        Useful while reproducing the silent-connection bug."""
        diag = self.get_osc_diagnostics()
        if not diag:
            self.log_message("OSC diag: manager not running")
            return
        self.log_message(
            "OSC diag: " + ", ".join(f"{k}={v}" for k, v in diag.items())
        )

    def get_osc_event_log(self) -> List[str]:
        """Facade: snapshot of the OSC manager's event ring buffer."""
        mgr = getattr(self, "osc_manager", None)
        if mgr is None:
            return []
        try:
            return mgr.get_event_log()
        except Exception:
            return []

    def get_osc_other_clients(self) -> Dict[str, Dict[str, Any]]:
        """Facade: which non-VRChat OSCQuery clients have we seen this session."""
        mgr = getattr(self, "osc_manager", None)
        if mgr is None:
            return {}
        try:
            return mgr.get_other_clients()
        except Exception:
            return {}

    def force_osc_rehandshake(self) -> None:
        """Facade: manually fire a re-poll of VRChat's OSCQuery endpoint and
        a fresh handshake ping. Wired to the 'Force re-handshake' button on
        the OSC Diagnostics panel — try this when packets stop flowing and
        you don't want to flip Disconnect/Connect to test if VRChat will
        resume sending."""
        mgr = getattr(self, "osc_manager", None)
        if mgr is None:
            self.log_message("Force re-handshake: OSC manager not running")
            return
        self.log_message("Force re-handshake: re-polling VRChat OSCQuery...")
        try:
            mgr._reprobe_silent_connection()
        except Exception as e:
            self.log_message(f"Force re-handshake failed: {type(e).__name__}: {e}")

    def force_osc_reregister_mdns(self) -> None:
        """Facade: rip our mDNS advertisement and re-publish under a fresh
        unique name. The strongest non-destructive recovery for the
        'connected but silent' bug — forces VRChat's OSCQuery client cache
        to enumerate us as a brand-new client and re-query our phonebook.
        Wired to the 'Re-publish mDNS' button on the Diagnostics panel."""
        mgr = getattr(self, "osc_manager", None)
        if mgr is None:
            self.log_message("Re-publish mDNS: OSC manager not running")
            return
        self.log_message("Re-publish mDNS: unregistering and re-advertising under a fresh name...")
        try:
            ok = mgr.reregister_mdns()
            if ok:
                self.log_message("Re-publish mDNS: done. Wait ~5s for VRChat to re-query us.")
            else:
                self.log_message("Re-publish mDNS: completed with errors — see OSC Diagnostics log.")
        except Exception as e:
            self.log_message(f"Re-publish mDNS failed: {type(e).__name__}: {e}")

    def open_osc_log_folder(self) -> None:
        """Facade: open the directory containing the persistent OSC log file
        in the system file explorer. Wired to the 'Open log folder' button."""
        mgr = getattr(self, "osc_manager", None)
        path = mgr.get_log_file_path() if mgr is not None else None
        if not path:
            self.log_message("Open log folder: no log path available (appdata denied?)")
            return
        try:
            import os as _os
            import subprocess as _subp
            folder = _os.path.dirname(path)
            self.log_message(f"OSC log file: {path}")
            if _os.name == "nt":
                _os.startfile(folder)  # type: ignore[attr-defined]
            else:
                # Fallback for non-Windows; this app targets Windows but
                # keep it from crashing if someone runs it elsewhere.
                _subp.Popen(["xdg-open", folder])
        except Exception as e:
            self.log_message(f"Open log folder failed: {type(e).__name__}: {e}")
    
    def on_osc_message(self, address: str, value):
        """Acts as a trigger ping when new UDP data arrives. Sets a flag to batch rapid updates."""
        self._needs_recalculation = True
        # VRChat reports the freshly-loaded avatar's ID via /avatar/change.
        # The OSC layer strips the leading slash, so we see "avatar/change".
        if address == "avatar/change":
            self.thread_queue.put(("avatar_change", str(value) if value is not None else ""))

    def toggle_osc_connection(self):
        """Toggles the VRChat OSC connection on and off safely (non-blocking)."""
        if hasattr(self, 'osc_manager') and self.osc_manager and self.osc_manager.is_connected:
            # --- Disconnect Path ---
            self.log_message("Disconnecting VRChat OSC...")
            try:
                self.osc_manager.stop()
            except Exception:
                pass
            self.osc_manager.is_connected = False
            self.ui.update_osc_status(False)
        else:
            # --- Connect Path ---
            self.log_message("Starting VRChat OSC server...")
            self.ui.update_osc_status(False)  # Reset UI to waiting state
            
            # Rebuild manager for a clean socket state
            bind_all = self.profile_manager.app_settings.settings.get("bind_all_interfaces", True)
            self.osc_manager = VRChatOSCManager(local_listen_port=0, bind_all_interfaces=bind_all)
            self.osc_manager.global_osc_callback = self.on_osc_message
            self.osc_manager.on_connected = lambda ports: self.thread_queue.put(
                ("osc_status", (True, ports.get("local_listen_port")))
            )
            self.osc_manager.on_disconnected = lambda: self.thread_queue.put(
                ("osc_status", (False, self.osc_manager.local_listen_port if self.osc_manager else None))
            )
            
            # Run startup in a background thread to prevent UI lockup
            threading.Thread(target=self.osc_manager.start, daemon=True).start()


    def toggle_osc_auto_connect(self):
        """Handle OSC auto-connect checkbox toggle from UI"""
        if not self.ui.get_osc_auto_connect_enabled():
            # Checkbox unchecked - disable OSC auto connect
            self.profile_manager.app_settings.set("auto_connect_osc", False)
            self.log_message("VRChat OSC Auto connect disabled")
        else:
            # Checkbox checked - enable OSC auto connect
            self.profile_manager.app_settings.set("auto_connect_osc", True)
            self.log_message("VRChat OSC Auto connect enabled")
            # If OSC server is not running, start it
            if self.osc_manager:
                try:
                    self.osc_manager.start()
                except Exception:
                    pass  # Server may already be running
