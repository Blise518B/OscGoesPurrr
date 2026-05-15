# OSCgoesPurrr - AI Context & Architecture Documentation

## 🛑 CRITICAL AI DIRECTIVE: THE BOUNDARIES
This application recently underwent a massive refactoring to eliminate "Shared Mutable State" and UI coupling. It strictly follows an MVC/Event-Driven architecture across multiple threads. 

**DO NOT TANGLE THESE LAYERS.** Before writing any code, you must adhere to the following anti-tangling rules:
1. **The Law of Demeter:** The UI (`ui_components.py`) MUST NOT access backend services directly (e.g., `controller.profile_manager` or `controller.haptic_engine`). It MUST use the Facade methods provided in `main.py` (e.g., `controller.get_app_setting()`, `controller.update_device_target()`).
2. **Visual Decoupling:** The Orchestrator (`main.py`) MUST NOT import or touch `customtkinter` widgets directly. Do not use `.set()` or `.insert()` in `main.py`. Pass primitive data to `ui.update_device_visuals()` and let the UI handle the drawing.
3. **No Shared Hardware State:** `HapticEngine` is a sealed black box. Do not pass dictionaries between threads. `main.py` drops commands into the queue, and `HapticEngine` manages its own internal `device_targets` memory.
4. **Stateless Networking:** `vrchat_osc.py` does not own data. It only writes to `parameter_store.py`.

---

## The 5-Part Ecosystem

### 1. The Brain (`parameter_store.py`)
* **Role:** Single Source of Truth.
* **Mechanism:** A thread-safe, global singleton (`store`). 
* **Rule:** UDP threads lock and write to it. The UI and Router threads read from it using `.copy()` to prevent dictionary size-change exceptions. 

### 2. The Eardrum (`vrchat_osc.py`)
* **Role:** Network listener.
* **Mechanism:** Handles mDNS discovery and runs the UDP Server.
* **Rule:** It is entirely memoryless. It parses incoming OSCQuery JSON and UDP packets and immediately dumps them into the Brain.

### 3. The Muscle (`haptic_engine.py`)
* **Role:** Async hardware driver for Bluetooth toys (via Buttplug.io).
* **Mechanism:** Runs its own isolated `asyncio` event loop. 
* **Rule:** It owns its internal state. The outside world communicates with it exclusively via `update_target()` and the `thread_queue`.

### 4. The Face (`ui_components.py`)
* **Role:** The "Dumb" View Layer.
* **Mechanism:** Renders the `customtkinter` interface.
* **Rule:** It only knows how to draw widgets. If a user clicks a button, it fires an event to the Controller (`main.py`). It never executes hardware or file-saving logic itself.

### 5. The Traffic Cop (`main.py`)
* **Role:** The Orchestrator / Controller.
* **Mechanism:** Boots the threads, holds the `profile_manager`, and delegates tasks.
* **Rule:** Acts as a Facade. It routes data between the Face, the Muscle, and the Brain without ever micromanaging *how* they do their jobs.

---

## The Stateless Router (`motor_router.py`)
We do not use state-machines to track interactions. The router is a pure, stateless calculator. 
1. **Trigger:** An incoming UDP packet arrives, or the user clicks a UI checkbox.
2. **Evaluate:** It grabs the active UI profile and compares it against the master `ParameterStore` (The Shadow State).
3. **Calculate:** It sweeps the parameter list, applies the filters (Touch/Pen/Self/Others), and calculates the absolute `max()` vibration allowed.
4. **Debounce:** It tracks `last_outputs` and only fires an event to the UI/Hardware queue if the target vibration value *actually changes* to prevent Tkinter update floods.