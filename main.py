# OscGoesPurrr - Three-Pillar Threading Architecture
# Copyright (C) 2024-2025  OscGoesPurrr Contributors
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.
#
# SPDX-License-Identifier: GPL-3.0-or-later

# Three-Pillar Threading Architecture:
#
#   Pillar 1: Main thread - customtkinter mainloop() + UI updates
#   Pillar 2: Async thread - asyncio event loop for buttplug/OSC
#   Pillar 3: Queue-based communication between threads (threading-safe)

import customtkinter as ctk
import threading
import asyncio
import queue
from typing import Optional

# Third-party imports (at module level for proper virtual environment resolution)
from buttplug import ButtplugClient
from pythonosc.udp_client import SimpleUDPClient


class OscGoesPurrrApp:
    def __init__(self):
        # Initialize main window
        self.app = ctk.CTk()
        self.app.title("OscGoesPurrr")
        self.app.geometry("800x600")
        
        # Thread-safe communication queue (standard library, not asyncio)
        self.thread_queue: queue.Queue = queue.Queue()
        self.async_loop: asyncio.AbstractEventLoop = None
        
        # Buttplug and OSC clients
        self.buttplug_client: Optional[ButtplugClient] = None
        self.osc_client = None
        
        # GUI State
        self.status_label = None
        self.connection_button = None
        self.is_connected = False
        
        # Setup UI
        self.setup_ui()
        
    def setup_ui(self):
        """Create and arrange all GUI elements"""
        main_frame = ctk.CTkFrame(self.app, fg_color="transparent")
        main_frame.pack(expand=True, fill="both", padx=20, pady=20)
        
        # Title
        title_label = ctk.CTkLabel(
            main_frame,
            text="OscGoesPurrr",
            font=("Arial", 32, "bold"),
            text_color="#6B4EFF"
        )
        title_label.pack(pady=(0, 10))
        
        # Status Label
        self.status_label = ctk.CTkLabel(
            main_frame,
            text="Ready to connect",
            font=("Arial", 14),
            text_color="#888888"
        )
        self.status_label.pack(pady=10)
        
        # Connection Button
        self.connection_button = ctk.CTkButton(
            main_frame,
            text="Connect to Intiface",
            command=self.toggle_connection,
            font=("Arial", 16),
            height=50,
            fg_color="#6B4EFF",
            hover_color="#5A3DCC"
        )
        self.connection_button.pack(pady=20)
        
        # Log/Output Box
        log_frame = ctk.CTkFrame(main_frame, corner_radius=8)
        log_frame.pack(expand=True, fill="both", pady=(0, 10))
        
        self.log_text = ctk.CTkTextbox(
            log_frame,
            font=("Courier New", 12),
            state="disabled",
            fg_color="#1E1E2E"
        )
        self.log_text.pack(expand=True, fill="both", padx=10, pady=10)
        
    def start_async_loop(self):
        """Start the asyncio event loop in a separate thread"""
        def run_loop():
            # Create new event loop for this thread
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            
            self.async_loop = loop
            
            try:
                loop.run_until_complete(self.async_worker())
            finally:
                loop.close()
        
        # Start async thread
        self.async_thread = threading.Thread(target=run_loop, daemon=True)
        self.async_thread.start()
        
    def push_ui_update(self, message: str):
        """Push a UI update from the async thread to the main thread via queue"""
        self.thread_queue.put(("ui_update", message))
        
    def push_connection_status(self, connected: bool, server: str = ""):
        """Push connection status from async thread to main thread"""
        self.thread_queue.put(("connection_status", (connected, server)))
        
    def process_async_queue(self):
        """Process messages from queue (called from main thread)"""
        try:
            while True:
                # Use get_nowait() instead of tkinter getvar
                msg = self.thread_queue.get_nowait()
                
                if isinstance(msg, tuple):
                    msg_type, data = msg
                    
                    if msg_type == "ui_update":
                        self.log_message(data)
                    elif msg_type == "connection_status":
                        connected, server = data
                        self.update_connection_status(connected, server)
                        
        except queue.Empty:
            pass  # No more messages in queue
            
    def log_message(self, message: str):
        """Add a message to the log text box (main thread only)"""
        self.log_text.configure(state="normal")
        self.log_text.insert("end", f"> {message}\n")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")
        
    def update_connection_status(self, connected: bool, server: str):
        """Update connection UI elements (main thread only)"""
        self.is_connected = connected
        if connected:
            self.connection_button.configure(
                text=f"Disconnect from Intiface",
                fg_color="#FF5E57",
                hover_color="#DD4E46"
            )
            self.status_label.configure(
                text=f"Connected to Intiface ✓",
                text_color="#00C853"
            )
        else:
            self.connection_button.configure(
                text="Connect to Intiface",
                fg_color="#6B4EFF",
                hover_color="#5A3DCC"
            )
            self.status_label.configure(
                text="Ready to connect",
                text_color="#888888"
            )
            
    async def async_worker(self):
        """Main async worker for buttplug and OSC operations"""
        
        self.push_ui_update("Async thread started")
        
        try:
            # Initialize OSC client
            self.osc_client = SimpleUDPClient("localhost", 9000)
            self.push_ui_update("OSC client initialized (port 9000)")
            
            # Initialize Buttplug client
            self.buttplug_client = ButtplugClient("OscGoesPurrr")
            self.push_ui_update("Buttplug client created")
            
        except Exception as e:
            self.push_ui_update(f"Initialization error: {e}")
        
        # Main async loop - does NOT connect automatically
        while True:
            await asyncio.sleep(0.1)
    
    async def connect_to_intiface(self):
        """Connect to Intiface server (called from async thread)"""
        if not self.buttplug_client:
            self.push_ui_update("Buttplug client not initialized")
            return
            
        try:
            self.push_ui_update("Connecting to Intiface...")
            await self.buttplug_client.connect("ws://localhost:12345")
            self.push_ui_update("Connected to Intiface successfully")
            self.push_connection_status(True, "Intiface")
            
        except Exception as e:
            error_msg = f"Connection failed: {e}"
            self.push_ui_update(error_msg)
            self.push_connection_status(False, "")
        
    def trigger_connect_to_intiface(self):
        """Trigger connect_to_intiface from main thread using run_coroutine_threadsafe"""
        if self.async_loop:
            try:
                asyncio.run_coroutine_threadsafe(
                    self.connect_to_intiface(),
                    self.async_loop
                )
            except Exception as e:
                self.push_ui_update(f"Failed to trigger connection: {e}")
            
    def toggle_connection(self):
        """Handle connection button click"""
        if not self.is_connected:
            # Connect when clicked (if not already connected)
            self.trigger_connect_to_intiface()
        else:
            # Disconnect - for now just log it
            self.push_ui_update("Disconnect requested")
            self.push_connection_status(False, "")
            
    def run(self):
        """Start the Three-Pillar application"""
        # Start async loop in background thread
        self.start_async_loop()
        
        # Periodically check for UI updates from async thread
        def check_queue():
            self.process_async_queue()
            self.app.after(50, check_queue)  # Check every 50ms
            
        self.app.after(100, check_queue)
        
        # Run GUI mainloop on main thread
        self.app.mainloop()


if __name__ == "__main__":
    app = OscGoesPurrrApp()
    app.run()