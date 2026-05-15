# OSCgoesPurrr - AI Context & Architecture Documentation

## Project Overview
**OSCgoesPurrr** is a playful, high-performance, Python-based haptic feedback router for VRChat. It listens for OSC data from VRChat and translates it into vibration commands for Bluetooth haptic hardware via Intiface Central. 

It utilizes a highly robust "Shadow State" architecture to guarantee zero ghost-values, instant UI responsiveness, and crash-proof thread management.

## Core Tech Stack
* **UI:** `customtkinter` (Desktop-first, dark mode)
* **Haptics:** `buttplug` (Official Python Buttplug.io client for Intiface Central)
* **VRChat Input:** `python-osc` (UDP Server/Client) + `requests`
* **VRChat Discovery:** `zeroconf` (mDNS Service Advertisement & Discovery)
* **Persistence:** Standard Python `json` module for profiles.

---

## 1. The Global Brain: `parameter_store.py`
The application utilizes a Central Store pattern to decouple networking from logic and UI. 
* **The Shadow State:** Instead of guessing what parameters exist, the app downloads the entire VRChat OSCQuery JSON tree on boot and flattens it into a single dictionary (`all_parameters`).
* **Thread Safety:** This store uses `threading.Lock()`. UDP threads write to it constantly, while the UI and Router read from it via `.copy()` to prevent dictionary size-change crashes.

## 2. The Three-Pillar Threading Model
Combining synchronous UI (`customtkinter`) with asynchronous networking requires strict thread separation:

* **Pillar 1: Main Thread (UI & Routing)**
    * Runs `app.mainloop()`.
    * Handles all `customtkinter` rendering and user clicks.
    * Executes the Stateless Router (see below).
    * **Rule:** NEVER execute blocking network calls or `time.sleep()` here.
* **Pillar 2: Async Worker Thread (Hardware & Network)**
    * Runs the `asyncio` event loop for the `buttplug` client.
    * Runs the `python-osc` UDP server to listen for VRChat messages.
* **Pillar 3: The Thread Queue**
    * A standard `queue.Queue` bridges the pillars. The Main Thread drops vibration commands (`osc_haptic_update`) into the queue, and the Async Thread consumes them to command the toys.

---

## 3. The Stateless Router (`motor_router.py`)
We do not use state-machines or memory to track interactions. The router is a pure, stateless calculator. 
1. **Trigger:** An incoming UDP packet arrives, or the user clicks a UI checkbox.
2. **Evaluate:** The router takes the active UI profile and compares it against the master `ParameterStore` (The Shadow State).
3. **Calculate:** It sweeps the massive parameter list, applies the Touch/Penetration/Self/Others filters, and calculates the absolute `max()` value allowed for that specific motor.
4. **Debounce:** To prevent "Update Floods" (VRChat dumping 500 packets in a millisecond and freezing Tkinter), the router tracks `last_outputs` and only fires an event to the UI/Hardware queue if the target vibration value *actually changes*.

---

## 4. UI/UX Standards
* **Dynamic Menus:** Avoid hardcoded dropdowns. Use the `ParameterStore` to generate dynamic checkbox popups (e.g., the multi-zone selector) so the user can interact with their exact avatar setup.
* **Vibe Meters:** Use `CTkProgressBar` to visualize the final output sent to the toys.
* **Debugger:** The Network & Debug tab reflects the live `ParameterStore` state, allowing users to see exactly what VRChat is broadcasting in real-time.

## AI Assistant Instructions
When asked to implement a new feature:
1. Identify which "Pillar" the code belongs in.
2. Never allow the UI to memorize OSC states. Always read from `parameter_store.py`.
3. Use `.copy()` when iterating over global dictionaries to prevent thread collisions.
4. Do not hallucinate external libraries (like `PyQt` or `Pygame`); stick strictly to `customtkinter`.