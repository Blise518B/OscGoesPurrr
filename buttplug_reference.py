"""
buttplug_reference.py
A comprehensive cheat sheet and reference guide for the buttplug-py (v1.0.0+) library.

This file demonstrates:
1. Client initialization and connection.
2. Event handlers (Device Added / Removed).
3. Scanning for devices.
4. Checking device capabilities using Protocol v4 (OutputType).
5. Sending DeviceOutputCommand for vibration.
6. Clean disconnection.
"""

import asyncio
from buttplug import ButtplugClient, ButtplugClientWebsocketConnector, DeviceOutputCommand, OutputType

# ==========================================
# 1. EVENT HANDLERS
# ==========================================
# These functions trigger automatically when a device connects or disconnects
# while the scanner is running or the client is active.

def on_device_added(emitter, device):
    print(f"[EVENT] Device Connected: {device.name} (Index: {device.index})")

def on_device_removed(emitter, device):
    print(f"[EVENT] Device Disconnected: {device.name}")

# ==========================================
# 2. MAIN ASYNC EXECUTION
# ==========================================
async def main():
    # A. Initialize the Client
    # The name you provide here will show up in the Intiface Central UI.
    client = ButtplugClient("Qwen Coder Reference App")
    
    # Attach the event handlers
    client.device_added_handler += on_device_added
    client.device_removed_handler += on_device_removed

    # B. Connect to Intiface Central
    print("Connecting to Intiface Central...")
    try:
        # Standard local WebSocket connection to Intiface Central
        connector = ButtplugClientWebsocketConnector("ws://127.0.0.1:12345")
        await client.connect(connector)
        print("Successfully connected to Intiface Central!")
    except Exception as e:
        print(f"Failed to connect. Is Intiface Central running? Error: {e}")
        return

    # C. Scan for Devices
    print("Starting device scan...")
    await client.start_scanning()
    
    # You MUST wait while the scanner looks for Bluetooth/USB devices.
    # 2 to 5 seconds is usually enough for local connections.
    await asyncio.sleep(3.0)
    
    await client.stop_scanning()
    print("Scan complete.")

    # D. Interact with Discovered Devices
    if not client.devices:
        print("No devices found. Turn on a toy and try again.")
    else:
        print(f"Found {len(client.devices)} device(s). Testing capabilities...")
        
        # client.devices is a dictionary where values are the actual device objects
        for device in client.devices.values():
            print(f"\n--- Testing {device.name} ---")
            
            # -----------------------------------------------------
            # CAPABILITY: VIBRATION (v1.0.0+ Syntax)
            # -----------------------------------------------------
            if device.has_output(OutputType.VIBRATE):
                print(f"{device.name} supports Vibration. Pulsing at 50%...")
                
                # Intensity is a float from 0.0 to 1.0
                await device.run_output(DeviceOutputCommand(OutputType.VIBRATE, 0.5))
                await asyncio.sleep(1.0)
                
                # Stop vibration by sending 0.0
                await device.run_output(DeviceOutputCommand(OutputType.VIBRATE, 0.0))
            
            # -----------------------------------------------------
            # STOP ALL COMMAND (Failsafe)
            # -----------------------------------------------------
            print(f"Sending global stop to {device.name}...")
            await device.stop()

    # E. Clean Disconnect
    print("\nDisconnecting from Intiface Central...")
    await client.disconnect()
    print("Done.")

# ==========================================
# 3. SCRIPT ENTRY POINT
# ==========================================
if __name__ == "__main__":
    # Python 3.7+ standard way to run an async loop
    asyncio.run(main())