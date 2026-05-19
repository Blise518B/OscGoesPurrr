# OSCgoesPurrr - AI Context & Architecture Documentation

## 🛑 CRITICAL AI DIRECTIVE: THE BOUNDARIES
This application follows an MVC / event-driven architecture across multiple
threads. Keeping the layers separate is the single most important rule —
the UI must remain swappable without touching backend code.

**DO NOT TANGLE THESE LAYERS.** Before writing any code, adhere to the
following anti-tangling rules:

1. **The Law of Demeter:** The UI (`ui_components.py`) MUST NOT access
   backend services directly (e.g. `controller.profile_manager` or
   `controller.haptic_engine`). It MUST go through Facade methods on the
   Controller (e.g. `controller.get_app_setting()`,
   `controller.update_device_target()`, `controller.copy_profile()`,
   `controller.paste_profile_into()`, `controller.get_global_profile_names()`,
   `controller.get_active_profile_dict()`, `controller.set_haptic_connected()`).
   This rule is fully enforced today — there are zero
   `controller.profile_manager.*` or `controller.haptic_engine.*` reads in
   `ui_components.py`. New code MUST keep it that way: if the UI needs a
   piece of backend data, add a facade method on the Controller and call
   that, never reach through the controller into the service. The one
   sanctioned exception is reading the global `parameter_store.store`
   (the Brain) — see the Brain section below.
2. **Visual Decoupling:** The Orchestrator (`main.py`) MUST NOT import or
   touch PySide6 / Qt widgets directly. It must not call `.setText()`,
   `.setValue()`, or any other Qt API in `main.py`. Pass primitive data
   to UI facade methods (`ui.update_device_visuals()`,
   `ui.update_osc_status()`, etc.) and let the UI handle the drawing.
3. **No Shared Hardware State:** `HapticEngine` is a sealed black box.
   Do not pass dictionaries between threads. `main.py` drops commands
   into the queue and uses the engine's primitive-only facade
   (`update_target()`, `set_linear_config()`, `mark_connected()`,
   `list_connected_device_names()`, `get_motor_count_map()`,
   `snapshot_discovered_devices()`, `async_start_scan()`,
   `async_connect()`, `async_disconnect()`, `async_purr_check()`,
   `async_test_device()`). It never reaches through
   `haptic_engine.buttplug_client` — the underlying buttplug.io client
   and `device.*` attributes are private to the engine. The engine
   manages its own internal `device_targets` memory and owns its
   `is_connected` flag (writers go through `mark_connected()`).
4. **Stateless Networking:** `vrchat_osc.py` does not own data. It only
   writes to `parameter_store.py`.

---

## The 5-Part Ecosystem

### 1. The Brain (`parameter_store.py`)
* **Role:** Single Source of Truth.
* **Mechanism:** A thread-safe, global singleton (`store`).
* **Rule:** UDP threads lock and write to it. The UI and Router threads
  read from it using `.copy()` semantics to prevent dictionary
  size-change exceptions.

### 2. The Eardrum (`vrchat_osc.py`)
* **Role:** Network listener.
* **Mechanism:** Handles mDNS discovery and runs the UDP server.
* **Rule:** It is entirely memoryless. It parses incoming OSCQuery JSON
  and UDP packets and immediately dumps them into the Brain.

### 3. The Muscle (`haptic_engine.py`)
* **Role:** Async hardware driver for Bluetooth toys (via Buttplug.io).
* **Mechanism:** Runs its own isolated `asyncio` event loop.
* **Rule:** It owns its internal state. The outside world communicates
  with it exclusively via `update_target()` and the `thread_queue`.

### 4. The Face (`ui_components.py`)
* **Role:** The "dumb" View Layer.
* **Mechanism:** Renders the interface using **PySide6 / Qt** (a global
  `GLOBAL_QSS` stylesheet plus widget objects). Vector icons are drawn
  at runtime via `QPainter` so the app does not depend on emoji-font
  availability.
* **Rule:** It only knows how to draw widgets. If the user clicks a
  button it fires an event to the Controller (`main.py`). It never
  executes hardware or file-saving logic itself. Swapping toolkits
  (back to Tk, forward to QML, anything else) should require rewriting
  this file only.

### 5. The Traffic Cop (`main.py`)
* **Role:** The Orchestrator / Controller.
* **Mechanism:** Boots the threads, holds the `profile_manager`, and
  delegates tasks.
* **Rule:** Acts as a Facade. It routes data between the Face, the
  Muscle, and the Brain without ever micromanaging *how* they do their
  jobs.

---

## The Stateless Router (`motor_router.py`)
We do not use state machines to track interactions. The router is a
pure, stateless calculator.

1. **Trigger:** An incoming UDP packet arrives, or the user clicks a UI
   checkbox.
2. **Evaluate:** It grabs the active profile dict
   (`profile_manager.get_active_profile_dict()`) and compares it
   against the master `ParameterStore` (the "shadow state").
3. **Calculate:** It sweeps the parameter list, applies the filters
   (Touch / Pen / Self / Others), and calculates the absolute `max()`
   vibration allowed.
4. **Debounce:** It tracks `last_outputs` and only fires an event to
   the UI/Hardware queue if the target vibration value *actually
   changes*, to prevent update floods.

---

## Profile model (`config_manager.py`)

* **Two pools** of profiles live side by side:
  * `profiles` — global profiles, always available.
  * `avatar_profiles` — profiles bound to a specific VRChat avatar id
    via `avatar_bindings` (`profile_name -> avtr_xxxx`).
* When an avatar loads, the resolver in
  `ProfileManager.get_active_profile_info()` picks the right profile
  using (in order) `avatar_last_choice` → first matching binding →
  the global `Default` fallback.
* The active profile dict is the live config the router reads and the
  UI writes to. Mutating it in place is fine; just call
  `save_profiles()` afterwards.
* **Copy / paste** is handled in `ProfileManager`:
  * `copy_profile_to_clipboard(kind, name)` snapshots a deep copy into
    an in-memory clipboard tagged with `{kind, name, config}`.
  * `paste_into_profile(target_kind, target_name)` overwrites an
    *existing* profile's contents with the clipboard, preserving the
    target's name and (for avatar profiles) its binding.
  * `paste_profile(target_kind, avatar_id?)` creates a *new* profile
    from the clipboard with an auto-uniqued name.
  * `clear_clipboard()` resets the clipboard without touching profiles.
  * All mutations call `save_profiles()` so the v2 schema on disk
    stays in sync.
