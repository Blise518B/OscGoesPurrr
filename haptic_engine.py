# OscGoesPurrr - Haptic Engine Module (Pillar 2)
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

"""
HapticEngine - Async hardware interface for buttplug and OSC operations.
Isolated from UI logic to enable clean separation of concerns.
"""

import asyncio
from typing import Optional

from buttplug import ButtplugClient, DeviceOutputCommand, OutputType


class HapticEngine:
    """
    Async hardware engine for managing buttplug connections.
    
    This class is designed to run in its own async thread and communicate
    with the main UI thread via a queue-based message system.
    """
    
    def __init__(self, thread_queue, device_targets: dict, device_last_sent: dict):
        """
        Initialize the HapticEngine with shared data references.
        
        Args:
            thread_queue: Thread-safe queue for communication with main thread
            device_targets: Dict of (device_name, motor_index) -> target intensity
            device_last_sent: Dict of (device_name, motor_index) -> last sent intensity
        """
        self.thread_queue = thread_queue
        self.device_targets = device_targets
        self.device_last_sent = device_last_sent
        
        # Hardware clients - these will be set when async_worker runs
        self.buttplug_client: Optional[ButtplugClient] = None
        
        # Connection state
        self.is_connected = False
    
    def push_ui_update(self, message: str):
        """Push a UI update to the main thread via queue"""
        self.thread_queue.put(("ui_update", message))
    
    def push_connection_status(self, connected: bool, server: str = ""):
        """Push connection status to the main thread"""
        self.thread_queue.put(("connection_status", (connected, server)))
    
    def push_stored_devices_refresh(self):
        """Push stored devices refresh request to main thread"""
        self.thread_queue.put(("stored_devices_refresh", None))
    
    async def _async_set_vibration(self, intensity: float):
        """Set vibration intensity for all connected devices
        
        Args:
            intensity: Vibration intensity from 0.0 to 1.0
        """
        if not self.buttplug_client or not self.is_connected:
            return
            
        try:
            for device in self.buttplug_client.devices.values():
                if device.has_output(OutputType.VIBRATE):
                    await device.run_output(DeviceOutputCommand(OutputType.VIBRATE, intensity))
                    
        except Exception as e:
            self.push_ui_update(f"Vibration error: {e}")
    
    async def _async_purr_check(self):
        """Test all devices by setting them to 0.1, waiting 1 second, then 0"""
        if not self.buttplug_client or not self.is_connected:
            return
            
        try:
            self.push_ui_update(f"Running Purr-Check on {len(self.buttplug_client.devices)} devices.")
            
            # Set all devices to 0.1 intensity
            for device in self.buttplug_client.devices.values():
                if device.has_output(OutputType.VIBRATE):
                    await device.run_output(DeviceOutputCommand(OutputType.VIBRATE, 0.1))
            
            self.push_ui_update("Purr-Check: All devices at 0.1")
            
            # Wait for 1 second
            await asyncio.sleep(1.0)
            
            # Set all devices back to 0.0 intensity
            for device in self.buttplug_client.devices.values():
                if device.has_output(OutputType.VIBRATE):
                    await device.run_output(DeviceOutputCommand(OutputType.VIBRATE, 0.0))
            
            self.push_ui_update("Purr-Check: All devices at 0.0 - Test Complete")
            
        except Exception as e:
            self.push_ui_update(f"Purr-Check error: {e}")
    
    async def _async_connect(self):
        """Internal async method to connect to Intiface"""
        if not self.buttplug_client:
            return
            
        await self.buttplug_client.connect("ws://127.0.0.1:12345")
        
        # Start scanning for devices after connection
        await self.buttplug_client.start_scanning()
        await asyncio.sleep(2.0)  # Give Intiface time to find devices
        
        # Stop scanning and get device list
        await self.buttplug_client.stop_scanning()
        
        # Construct dictionary of found devices: {index: {"name": name, "motor_count": count}}
        found_devices = {}
        for device in self.buttplug_client.devices.values():
            # Detect motor count by counting vibration features
            try:
                features = device.get_features_with_output(OutputType.VIBRATE)
                motor_count = len(features)
                
                self.push_ui_update(f"Detected {motor_count} vibrate feature(s) for {device.name}")
                if hasattr(device, 'features'):
                    self.push_ui_update(f"  Full device features: {len(device.features)} total")
            except Exception as e:
                # Fallback to default of 1 motor
                motor_count = 1
                self.push_ui_update(f"Error detecting features for {device.name}: {e}")
            
            # Default to 1 if no vibration features found (shouldn't happen for vibe toys, but just in case)
            if motor_count == 0:
                motor_count = 1
            
            self.push_ui_update(f"Final motor count for {device.name}: {motor_count} motors")
            
            found_devices[device.index] = {
                "name": device.name,
                "motor_count": motor_count
            }
        
        # Update connection status before triggering UI rebuild (fixes race condition)
        self.is_connected = True
        self.push_connection_status(True, "Intiface")
        
        # Push message to refresh stored devices UI from main thread
        self.push_stored_devices_refresh()
        
        # Send found devices to main thread via queue
        self.thread_queue.put(("devices_found", found_devices))
        
        self.push_ui_update(f"Scan complete. Devices found: {len(self.buttplug_client.devices)}")
    
    async def _async_disconnect(self):
        """Internal async method to disconnect from Intiface"""
        if self.buttplug_client:
            try:
                await self.buttplug_client.disconnect()
            except Exception:
                pass
        self.is_connected = False
    
    async def async_worker(self, app_instance=None):
        """
        Main async worker for buttplug operations.
        
        This is the primary loop that runs in the async thread, polling
        device targets and sending updates at a controlled rate.
        
        Args:
            app_instance: Optional reference to OscGoesPurrrApp for buttplug client access
        """
        
        self.push_ui_update("Async thread started")
        
        try:
            # Initialize Buttplug client
            self.buttplug_client = ButtplugClient("OscGoesPurrr")
            self.push_ui_update("Buttplug client created")
            
        except Exception as e:
            self.push_ui_update(f"Initialization error: {e}")
        
        # Main async loop - Golden Loop, polls each device's intensity and sends (10Hz polling)
        while True:
            if self.is_connected and self.buttplug_client:
                # Iterate through each discovered device
                for device in self.buttplug_client.devices.values():
                    device_name = device.name
                    
                    # Get all vibration features for this device
                    vibration_features = device.get_features_with_output(OutputType.VIBRATE)
                    
                    # Iterate through all motors for this device and send updates if needed
                    for (d_name, motor_idx), target_intensity in list(self.device_targets.items()):
                        if d_name != device_name:
                            continue
                            
                        last_sent = self.device_last_sent.get((device_name, motor_idx), 0.0)
                        
                        if target_intensity != last_sent:
                            try:
                                if motor_idx == -1:
                                    # Global command to the whole device
                                    await device.run_output(DeviceOutputCommand(OutputType.VIBRATE, target_intensity))
                                elif 0 <= motor_idx < len(vibration_features):
                                    # Specific motor command
                                    feature = vibration_features[motor_idx]
                                    await feature.run_output(DeviceOutputCommand(OutputType.VIBRATE, target_intensity))
                                
                                self.device_last_sent[(device_name, motor_idx)] = target_intensity
                            except Exception as e:
                                self.push_ui_update(f"Vibration error for {device_name} motor {motor_idx}: {e}")
            
            await asyncio.sleep(0.1)  # Poll at 10Hz to avoid rate-limit crashes