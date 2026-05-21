# OscGoesPurrr — AI Context & Architecture Documentation

## 🛑 CRITICAL AI DIRECTIVE: THE BOUNDARIES

This application follows an MVC / event-driven architecture across multiple
threads. Keeping the layers separate is the single most important rule —
the UI must remain swappable, and adding a new haptic backend must mean
adding files, not rewriting old ones.

**DO NOT TANGLE THESE LAYERS.** Before writing any code, adhere to the
following anti-tangling rules:

1. **The Law of Demeter.** The UI (`ui_components.py` and the `ui/`
   package) MUST NOT access backend services directly (e.g.
   `controller.profile_manager`, `controller.haptic_engine`,
   `controller.bhaptics_engine`, `controller.steamvr_engine`,
   `controller.hardware_monitor`, `controller.osc_manager`, or any
   `*_router`). It MUST go through facade methods on the Controller
   (e.g. `controller.get_app_setting()`, `controller.update_device_target()`,
   `controller.copy_profile()`, `controller.paste_profile_into()`,
   `controller.get_global_profile_names()`, `controller.get_active_profile_dict()`,
   `controller.set_haptic_connected()`, `controller.get_steamvr_status()`,
   `controller.get_bhaptics_status()`, `controller.get_hardware_monitor_status()`,
   `controller.get_steamvr_toys_status()`).
   This rule is fully enforced today — there are zero
   `controller.<service>.*` reads in `ui_components.py` or in the
   `ui/` package. New code MUST keep it that way: if the UI needs a
   piece of backend data, add a facade method on the controller (either
   in `main.py` or in the appropriate mixin under `controllers/`) and
   call that, never reach through the controller into the service. The
   one sanctioned exception is reading the global `parameter_store.store`
   (the Brain) — see the Brain section below.
2. **Visual Decoupling.** The Orchestrator (`main.py`) MUST NOT import
   or touch PySide6 / Qt widgets directly. It must not call
   `.setText()`, `.setValue()`, or any other Qt API in `main.py`. Pass
   primitive data to UI facade methods (`ui.update_device_visuals()`,
   `ui.update_osc_status()`, etc.) and let the UI handle the drawing.
3. **No Shared Hardware State (sealed engines).** Every hardware backend
   — `HapticEngine`, `BHapticsEngine`, `SteamVREngine`,
   `HardwareMonitorEngine`, plus the `SteamVRToyBridge` — is a sealed
   black box. Do not pass dictionaries between threads. The outside
   world communicates with each engine exclusively via its
   primitive-only facade and (where applicable) via the shared
   `thread_queue`.
   * `HapticEngine` exposes `update_target()`, `set_linear_config()`,
     `mark_connected()`, `list_connected_device_names()`,
     `get_motor_count_map()`, `snapshot_discovered_devices()`,
     `async_start_scan()`, `async_connect()`, `async_disconnect()`,
     `async_purr_check()`, `async_test_device()`. It never exposes
     `buttplug_client` or `device.*` — those are private to the engine.
     The engine owns its `device_targets` memory and its `is_connected`
     flag (writers go through `mark_connected()`).
   * `BHapticsEngine`, `SteamVREngine`, `HardwareMonitorEngine` each
     follow the same pattern: primitive-only public methods, internal
     state stays internal. Their UI-facing call surface lives on the
     mixin classes in `controllers/` (see "The Traffic Cop" below).
   * `SteamVRToyBridge` exposes `set_devices()`, `update_battery()`,
     `start()`, `stop()`. Nothing else touches the TCP socket.
4. **Stateless Networking.** `vrchat_osc.py` does not own data. It only
   writes to `parameter_store.py`.

---

## The Ecosystem

OscGoesPurrr is a small constellation of independent threads
communicating through a shared parameter store and a single
`thread_queue`. Originally a 5-part system; today the same pattern is
replicated per haptic backend.

### 1. The Brain (`parameter_store.py`)

* **Role:** Single Source of Truth.
* **Mechanism:** A thread-safe, global singleton (`store`) holding the
  flat parameter cache, the OGB-derived `detected_zones`, an
  incremental `_zone_tuples` set, a `packets_received` counter, and a
  monotonic `_version` that the routers use to short-circuit unchanged
  ticks.
* **Rule:** UDP and OSCQuery snapshot writes lock and mutate it. The UI
  and all routers read from it via `.copy()` semantics (or the atomic
  `snapshot()` getter) to prevent dictionary size-change exceptions.

### 2. The Eardrum (`vrchat_osc.py`)

* **Role:** Network listener.
* **Mechanism:** Handles mDNS discovery, runs the UDP server, and acts
  as an OSCQuery client *and* service (dynamic port, advertised via
  `_osc._udp.local`). Exposes an outbound `send_parameter()` for the
  facades that need to push values back to VRChat (battery levels,
  hardware-monitor stats, `bHaptics_Connected` bool).
* **Rule:** It is entirely memoryless. It parses incoming OSCQuery JSON
  and UDP packets and immediately dumps them into the Brain.

### 3. The Muscles — a family of sealed engines

The original "Muscle" was one engine. Today four hardware backends live
side-by-side, all following the same sealed-box contract. The
controller fans incoming OSC state out to whichever engines have config.

* **`haptic_engine.py` — Buttplug.io toys.** Runs its own isolated
  `asyncio` event loop in a worker thread. Owns the
  `ButtplugClient`, the discovered-devices list, and the per-motor
  `device_targets` map. The async loop is bootstrapped from
  `main.start_async_loop()`.
* **`steamvr_engine.py` — SteamVR tracker haptics.** Talks to OpenVR,
  enumerates trackers, fires `TriggerHapticPulse`. Paired with
  `steamvr_router.py` (the per-tick calculator) and
  `SteamVRBatteryBroadcaster` (publishes battery levels back to
  VRChat via the OSC facade).
* **`bhaptics_engine.py` — bHaptics suits / vests.** WebSocket client
  that talks to the bHaptics Player. Paired with `bhaptics_router.py`
  which translates v1 bHapticsOSC bool params into dot-mode frames.
* **`hardware_monitor.py` — CPU / RAM / GPU broadcaster.** A pure
  outbound engine: no router pair. Polls hardware on its own thread
  and pushes stats out as OSC parameters when enabled.

**Rule:** every engine owns its internal state. The outside world
communicates with each one *exclusively* through its primitive-only
public methods (and, where the engine has hot output, the
`thread_queue`).

### 4. The Stateless Routers

We do not use state machines to track interactions. Each router is a
pure, stateless calculator that reads the Brain and tells its engine
what to do.

* **`motor_router.py` — Buttplug routing.** Owns the speed-blend
  tuning math, the touch/pen/self/other filter, and the per-motor
  `last_outputs` debouncer. Reads `profile_manager.get_active_profile_dict()`
  against `ParameterStore.snapshot()` each tick; only fires a queue
  event when the target value actually changes.
* **`steamvr_router.py` — SteamVR tracker routing.** Same pattern,
  reads tracker-config dicts via a getter and emits haptic pulses
  through `SteamVREngine`.
* **`bhaptics_router.py` — bHaptics dot routing.** Translates the OGB /
  bHapticsOSC parameter shape into per-position dot intensity grids,
  with antistuck timers, and emits frames through `BHapticsEngine`.

Each router lives next to its engine; none of them holds long-lived
hardware state.

### 5. The Face — `ui_components.py` + the `ui/` package

* **Role:** The "dumb" View Layer.
* **Mechanism:** Renders the interface using **PySide6 / Qt** (a global
  `GLOBAL_QSS` stylesheet plus widget objects). Vector icons are drawn
  at runtime via `QPainter` so the app does not depend on emoji-font
  availability.
  * `ui_components.py` is the main `OscGoesPurrrUI` class — the
    controller-facing facade and the live update sinks.
  * The `ui/` subpackage contains the bits factored out so the main
    class isn't the only home for view-layer code:
    * `ui/widgets.py` — `Card`, `ToggleSwitch`, `RainbowMeter`,
      `RainbowScrollBar`, `MainWindow`, `BHapticsDotGrid`,
      `SliderProxy`, `ProgressProxy`, `Invoker`, scrollbar install.
    * `ui/icons.py` + `ui/lovense_icons.py` — `QPainter`-drawn vector
      icons and the Lovense-shape icon set.
    * `ui/geometry.py` — Tk-style geometry string parsing (kept for
      compat with on-disk settings written by older versions).
    * `ui/layout_helpers.py`, `ui/text_helpers.py` — small helpers.
* **Rule:** It only knows how to draw widgets. If the user clicks a
  button it fires an event to the Controller (`main.py`). It never
  executes hardware or file-saving logic itself. Swapping toolkits
  (back to Tk, forward to QML, anything else) should mean rewriting
  `ui_components.py` plus the `ui/` package, and nothing else. The
  sole sanctioned reach-out to backend code is reading
  `parameter_store.store` for live debug views.

### 6. The Traffic Cop — `main.py` + the `controllers/` mixins

* **Role:** The Orchestrator / Controller.
* **Mechanism:** `OscGoesPurrrApp` in `main.py` boots the threads,
  holds the `profile_manager`, and routes data between layers. Its
  call surface is intentionally split:
  * `main.py` itself holds the core API — boot, queue draining,
    Buttplug profile / device config, simple-mode, OSC diagnostics,
    profile copy/paste plumbing, etc.
  * Per-engine facade mixins live under `controllers/` and are
    composed into `OscGoesPurrrApp` via multiple inheritance:
    * `controllers/steamvr_facade.py` — `SteamVRFacade`
    * `controllers/steamvr_toys_facade.py` — `SteamVRToysFacade`
    * `controllers/bhaptics_facade.py` — `BHapticsFacade`
    * `controllers/hardware_monitor_facade.py` — `HardwareMonitorFacade`
  * Adding a new engine means: write the engine + router, write a new
    `controllers/<name>_facade.py` mixin, add it to `OscGoesPurrrApp`'s
    base list, expose UI methods on the mixin. **No changes to the UI's
    Demeter contract.**
* **Rule:** Acts as a Facade. It routes data between the Face, the
  Muscles, and the Brain without ever micromanaging *how* they do
  their jobs. Each mixin's docstring documents the host attributes it
  assumes.

### 7. The SteamVR Toy Driver (optional subsystem)

A C++ OpenVR driver lives under `steamvr_toy_driver/` and is installed
on demand into `<SteamVR>/drivers/`. When enabled it makes connected
Buttplug toys (and configured bHaptics positions) appear as virtual
trackers in SteamVR's device strip.

* `steamvr_manifest.py` — generates / writes the driver manifest.
* `steamvr_toy_driver_installer.py` — copies the driver bundle into
  SteamVR, manages enable/disable in `steamvrpaths.vrpath`.
* `steamvr_toy_bridge.py` — `SteamVRToyBridge`, a sealed-box TCP
  client that pushes the live toy list and battery levels over
  newline-JSON to the driver on `127.0.0.1:24855`.
* `controllers/steamvr_toys_facade.py` — owns init / install / sync /
  enable / disable from the controller side. The UI never touches the
  bridge or installer directly.

The whole subsystem is optional; the facade no-ops cleanly when the
feature is disabled.

---

## Profile model (`config_manager.py`)

The on-disk config file is `profiles.json` (v2 schema). `ProfileManager`
owns several sibling stores:

* **`profiles`** — global profiles, always available.
* **`avatar_profiles`** — profiles bound to a specific VRChat avatar id
  via `avatar_bindings` (`profile_name -> avtr_xxxx`).
* **`app_settings`** (`AppSettingsManager`) — UI-level toggles
  (`auto_refresh`, `auto_connect`, `bind_all_interfaces`, window
  geometry, console visibility, speed-tuning, feature flags…).
* **`steamvr_settings`** (`SteamVRSettingsManager`) — per-tracker
  configs, patterns, autostart / auto-connect, battery interval,
  no-data fallback.
* **`bhaptics_settings`** (`BHapticsSettingsManager`) — endpoint,
  auto-connect, per-position device configs, antistuck timings, the
  `bHaptics_Connected` OSC bool config.
* **`hardware_monitor_settings`** (`HardwareMonitorSettingsManager`) —
  enabled flag, OSC send toggles, poll rate, per-stat addresses.
* **`known_devices`** (`KnownDevicesRegistry`) — global registry of
  every toy ever seen; profiles inherit from it on first creation.

### Active-profile resolution

When an avatar loads, `ProfileManager.get_active_profile_info()` picks
the right profile using (in order) `avatar_last_choice` → first
matching binding → the global `Default` fallback. The active profile
dict is the live config the router reads and the UI writes to.
Mutating it in place is fine; just call `save_profiles()` afterwards.

### Copy / paste

All handled in `ProfileManager`:

* `copy_profile_to_clipboard(kind, name)` snapshots a deep copy into
  an in-memory clipboard tagged with `{kind, name, config}`.
* `paste_into_profile(target_kind, target_name)` overwrites an
  *existing* profile's contents with the clipboard, preserving the
  target's name and (for avatar profiles) its binding.
* `paste_profile(target_kind, avatar_id?)` creates a *new* profile
  from the clipboard with an auto-uniqued name.
* `clear_clipboard()` resets the clipboard without touching profiles.
* All mutations call `save_profiles()` so the v2 schema on disk stays
  in sync.

---

## Auxiliary modules

* `constants.py` — app-wide constants (`APP_NAME`, `INTIFACE_WS_URL`,
  default window geometry, OSC defaults).
* `utilities.py` — small helpers (`value_to_hex_color`,
  `toggle_windows_console`, `create_default_icon`).
* `version.py` — single source of truth for `__version__`.
* `tools/` — developer scripts, not loaded at runtime
  (`flatten_lovense_icons.py`, `generate_bhaptics_icons.py`).

---

## How to add a new haptic backend (the official pattern)

1. **Engine** — write `myhardware_engine.py` with a sealed-box class:
   primitive-only public methods, all state private. If async, run its
   own loop; otherwise its own thread. Talk to the outside world via
   the shared `thread_queue` and/or a `state_callback`.
2. **Router** — write `myhardware_router.py` as a pure stateless
   calculator. Read the Brain (`parameter_store.snapshot()`) and the
   per-device configs via a getter passed in by the controller. Debounce
   on `last_outputs`.
3. **Controller mixin** — add `controllers/myhardware_facade.py`
   containing a `MyHardwareFacade` mixin with the UI-facing methods
   (`get_myhardware_status()`, `set_myhardware_*()`). The mixin's
   docstring lists the host attributes it assumes.
4. **Compose** — add `MyHardwareFacade` to `OscGoesPurrrApp`'s base
   list in `main.py`. Instantiate the engine + router in
   `_setup_components()`.
5. **Settings** — add a `MyHardwareSettingsManager` to
   `config_manager.py`, owned by `ProfileManager`.
6. **UI** — add a card / tab in `ui_components.py` that calls *only*
   the new facade methods. **Do not** import the engine or router from
   the UI.

Following this recipe means the four anti-tangling rules at the top of
this document keep holding without anyone having to re-audit them.
