# OSCgoesPurrr - AI Context & Architecture Documentation

## Project Overview
**OSCgoesPurrr** is a playful, high-performance, Python-based haptic feedback router for VRChat. It acts as a superior successor to tools like OSCGB. It listens for OSC data from VRChat (like depth or proximity parameters) and translates them into vibration commands for Bluetooth haptic hardware via Intiface Central.

## Core Tech Stack
* **UI:** `customtkinter` (Desktop-first, VR-friendly with a "Mini-Mode")
* **Haptics:** `buttplug` (Official Python Buttplug.io client for Intiface Central)
* **VRChat Input:** `python-osc` (UDP Server/Client)
* **VRChat Parameter Scanning:** `vrc-osc-query` (For auto-detecting SPS setups)
* **Persistence:** Standard Python `json` module for saving/loading user profiles.

---

## 1. The "Three-Pillar" Threading Architecture
**CRITICAL AI DIRECTIVE:** This application combines a synchronous blocking UI (`customtkinter`) with asynchronous networking (`buttplug`, `python-osc`). You MUST strictly adhere to the following thread separation.

* **Pillar 1: Main Thread (UI)**
    * Runs `app.mainloop()`.
    * Strictly for rendering `customtkinter` widgets and handling user clicks.
    * **Rule:** NEVER execute blocking network calls or `time.sleep()` here.
* **Pillar 2: Async Worker Thread (Logic)**
    * A separate `threading.Thread` running an `asyncio` event loop.
    * Handles the OSC Server and the Buttplug WebSocket connection.
    * **Rule:** NEVER attempt to update a `customtkinter` widget directly from this thread. It will crash the application.
* **Pillar 3: The Bridge (Communication)**
    * **Async -> UI:** Use a standard `queue.Queue()`. The async thread calls `queue.put()`, and the UI thread polls it using `app.after(50, process_queue)`.
    * **UI -> Async:** Use `asyncio.run_coroutine_threadsafe(coroutine(), async_loop)` to send commands (like button clicks) into the background loop.

---

## 2. Hardware API Rules (buttplug-py v1.0.0+)
When writing haptic code, strictly follow the modern `buttplug-py` Protocol v4 API:
* **Imports:** You must import `DeviceOutputCommand` and `OutputType` alongside the client. 
* **Scanning:** `await client.start_scanning()`, followed by `await asyncio.sleep(2.0)`, then `await client.stop_scanning()`.
* **Capability Check:** Check if a device vibrates using `if device.has_output(OutputType.VIBRATE):` (Do NOT use `allowed_messages` or `hasattr`).
* **Vibrating:** Send commands using `await device.run_output(DeviceOutputCommand(OutputType.VIBRATE, intensity))`. Intensity must be a float between `0.0` and `1.0`.

---

## 3. Multi-Motor Device Support
OscGoesPurrr supports devices with multiple vibration motors (e.g., Lovense Gemini):

* **Motor Count Detection:** Uses `device.get_features_with_output(OutputType.VIBRATE)` to count all vibration-capable features.
* **Per-Motor Control:** Devices with 2+ motors display individual sliders and progress bars for each motor:
  - "Motor 0:", "Motor 1:" labels appear above each control pair
  - Each slider controls only its assigned motor via `feature.run_output()`
  - All Motors option still available using `device.run_output()` (sends to all features)
* **State Storage:** Uses tuple keys `(device_name, motor_index)` where:
  - `-1` = all motors
  - `0+` = specific motor index

---

## 3a. Multi-Device Support (Two of the Same Toy)

When using two toys of the exact same model (e.g., two Lovense Hush devices), there is a critical distinction to understand:

**Device Identity Limitation:**
* **No Unique Identifiers:** Bluetooth hardware MAC addresses are intentionally hidden by Windows, macOS, and WebBluetooth for privacy protection. Intiface Central scrubs these identifiers before passing devices to your Python app.
* **Identical Names:** Two of the same toy will both appear with `device.name == "Lovense Hush"` (or whatever the model name is).
* **Temporary Indexes:** Intiface assigns temporary device.index values (0, 1, etc.) that reset every time Intiface Central restarts.

**The Solution: Custom Names in Intiface Central**
If you want to use two of the same toy simultaneously (e.g., one for each hand), follow these steps:

1. Connect both toys to **Intiface Central**
2. Navigate to the **Devices** tab
3. Click on each toy and assign a **Custom Name**:
   - Example: `"Left Hush"` and `"Right Hush"`
   - Or: `"Main Toy"` and `"Secondary Toy"`
4. Intiface saves these preferences locally
5. When OscGoesPurrr requests devices, Intiface passes the custom names as `device.name`

Because your profile system uses `device.name` as the unique key for saving/loading OSC parameters, the two toys will now be stored separately in `profiles.json`.

**Note:** This is a platform-level limitation, not an app bug. The solution requires configuring the devices inside Intiface Central before launching OscGoesPurrr.

## 4. The "Golden Loop" (Haptic Logic Pipeline)
When processing an incoming OSC float from VRChat, it must pass through this mathematical pipeline before hitting the hardware:

1.  **Raw Input:** Capture the float (0.0 to 1.0).
2.  **Mode Logic:**
    * *Depth Mode:* Direct 1:1 mapping (or optionally squared for a natural curve).
    * *Velocity Mode:* `Velocity = abs(Current_Depth - Previous_Depth) / Delta_Time`.
    * *Hybrid Mode:* `Intensity = (Weight_1 * Depth) + (Weight_2 * Velocity)`.
3.  **Add Touch Zones:** If the active profile has enabled auxiliary contact zones, add their values multiplied by their specific multipliers. Clamp the final sum to `1.0`.
4.  **Signal Smoothing (EMA):** Apply an Exponential Moving Average to prevent motor stutter, especially in Velocity mode. 
    * `Output_now = (alpha * Input_new) + ((1 - alpha) * Output_last)`
    * *(Note: The UI slider for "Smoothing" controls the inverse of alpha).*
5.  **Stuck Detection (Safety):** Track `last_val` and `last_change_time`. If an exact high-precision float (e.g., 0.012739) remains static for `> 2.0` seconds, force the output to `0.0` to kill runaway vibrations.

---

## 5. UI/UX Standards
* **Theme:** Use `customtkinter` dark mode. Visually emphasize active states with purples/pinks.
* **Dynamic Views:** The UI features a "Compact/Mini-Mode" toggle via `pack_forget()`, stripping away advanced settings to show only a Profile Switcher, a "Purr-Check" (Test All) button, and the Vibe Meters.
* **Vibe Meters:** Use `CTkProgressBar` to visualize the *final smoothed output* of the Golden Loop for each device in real-time.

## AI Assistant Instructions
When asked to implement a new feature:
1.  Identify which "Pillar" the code belongs in.
2.  Ensure thread safety.
3.  Do not hallucinate API calls for `buttplug-py`; use only the documented commands above.
4.  Keep methods modular so they can be easily tested.