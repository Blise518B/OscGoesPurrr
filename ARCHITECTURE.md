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
   `controller.mode_manager`, `controller.haptic_engine`,
   `controller.bhaptics_engine`, `controller.steamvr_engine`,
   `controller.osc_manager`, or any `*_router`). It MUST go through
   facade methods on the Controller
   (e.g. `controller.get_app_setting()`, `controller.update_device_target()`,
   `controller.switch_mode()`, `controller.get_modes_info()`,
   `controller.get_active_profile_dict()`,
   `controller.set_haptic_connected()`, `controller.get_steamvr_status()`,
   `controller.get_bhaptics_status()`,
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
   — `HapticEngine`, `BHapticsEngine`, `SteamVREngine`, plus the
   `SteamVRToyBridge` — is a sealed black box. Do not pass dictionaries between threads. The outside
   world communicates with each engine exclusively via its
   primitive-only facade and (where applicable) via the shared
   `thread_queue`.
   * `HapticEngine` exposes `update_target()`, `set_linear_config()`,
     `mark_connected()`, `set_connection_mode()`,
     `release_managed_server()`, `list_connected_device_names()`,
     `get_motor_count_map()`, `snapshot_discovered_devices()`,
     `async_start_scan()`, `async_connect()`, `async_disconnect()`,
     `async_purr_check()`, `async_test_device()`. It never exposes
     `buttplug_client` or `device.*` — those are private to the engine.
     The engine owns its `device_targets` memory and its `is_connected`
     flag (writers go through `mark_connected()`).
   * `BHapticsEngine` and `SteamVREngine` each follow the same pattern:
     primitive-only public methods, internal state stays internal.
     Their UI-facing call surface lives on the
     mixin classes in `controllers/` (see "The Traffic Cop" below).
   * `SteamVRToyBridge` exposes `set_devices()`, `update_battery()`,
     `start()`, `stop()`. Nothing else touches the TCP socket.
4. **Stateless Networking.** `vrchat_osc.py` does not own data. It only
   writes to `parameter_store.py`.

**Latency is the other load-bearing constraint.** This app turns VRChat
OSC into physical sensation in real time, so minimizing OSC-in →
device-out latency ranks alongside the boundaries above — not a
nice-to-have. Never add queue hops, fixed delays, smoothing *delay*, or
ack-blocking to a routing / engine / dispatch path. Read **§ "Latency
budget"** below before touching any hot path.

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
  facades that need to push values back to VRChat (tracker battery
  levels and the `bHaptics_Connected` bool).
* **Rule:** It is entirely memoryless. It parses incoming OSCQuery JSON
  and UDP packets and immediately dumps them into the Brain.

### 3. The Muscles — a family of sealed engines

The original "Muscle" was one engine. Today **seven** hardware backends live
side-by-side, all following the same sealed-box contract. The
controller fans incoming OSC state out to whichever engines have config.

The reconnecting backends share a *cold-path* connection supervisor in
`engine_base.py`: `ReconnectingEngine` (thread-driven — bHaptics, OWO,
PiShock-serial, Handy) and `AsyncReconnectingEngine` (owns its own asyncio loop
thread — Coyote). Both flavours expose the identical public surface (pinned by
a contract-parity test): connected flag, last-error, the auto-connect gate,
the state-change callback, `start()` / `stop()` / `manual_connect()`, and the
backoff reconnect loop, so each engine only implements its transport via
`_open()` / `_close()` / `_available`. A connect lock serializes every open
(manual button vs the loop), and `manual_connect()` latches a *manual hold*:
while auto-connect is off, the loop only tears down links it opened itself —
a user's Connect Now session survives until it drops on its own or the engine
stops. **Critical:** this base governs the cold path only (connect /
reconnect / disconnect) — it never sits on an engine's hot send path. Buttplug (`haptic_engine`) and SteamVR
(`steamvr_engine`) predate it and keep their own lifecycle.

* **`haptic_engine.py` — Buttplug.io toys.** Runs its own isolated
  `asyncio` event loop in a worker thread. Owns the
  `ButtplugClient`, the discovered-devices list, and the per-motor
  `device_targets` map. The async loop is bootstrapped from
  `main.start_async_loop()`. It does **not** know how the Buttplug server
  is provisioned — that is delegated to a swappable connection provider
  (see below), selected via `set_connection_mode()`.
  * **Intiface connection providers.** Two self-contained modules implement
    the same tiny contract (`prepare()` → ws URL, `shutdown()`,
    `terminate()`, `status_label`); `intiface_connection.py` is the seam
    that picks one via `make_intiface_connection(mode)`:
    * `intiface_external.py` — connect to a user-run Intiface Central
      (the original behavior; owns no server lifecycle).
    * `intiface_integrated.py` — spawn and supervise a bundled
      `intiface-engine` (hidden console, Windows Job Object kill-on-close,
      websocket-readiness probe) so everything runs in one program. This is
      the default, gated by the `use_integrated_intiface` app setting
      (Settings → Intiface Engine). The engine binary is not in the repo;
      it lives in `intiface-engine/` and is bundled by `build_OGP.bat`.
* **`steamvr_engine.py` — SteamVR tracker haptics.** Talks to OpenVR,
  enumerates trackers, fires `TriggerHapticPulse`. Paired with
  `steamvr_router.py` (the per-tick calculator) and
  `SteamVRBatteryBroadcaster` (publishes battery levels back to
  VRChat via the OSC facade).
* **`bhaptics_engine.py` — bHaptics suits / vests.** WebSocket client
  that talks to the bHaptics Player. Paired with `bhaptics_router.py`
  which translates v1 bHapticsOSC bool params into dot-mode frames.
* **`pishock_engine.py` — PiShock shock / vibrate / beep.** A
  `ReconnectingEngine` over a swappable transport (`pishock_connection.py`
  selects USB-serial or the pishock.com cloud HTTP API — same seam pattern as
  the Intiface providers). Discrete `fire(op, intensity, duration)` hot path
  with **hard safety caps re-clamped on every fire** (absolute intensity /
  duration ceilings + a min-interval cooldown) so no caller — a buggy router,
  a UI test button — can ever exceed them. Paired with `pishock_router.py`.
* **`coyote_engine.py` — DG-Lab Coyote 3.0 e-stim.** An
  `AsyncReconnectingEngine` driving the unit directly over BLE (`bleak`); the
  20-byte / 7-byte wire encoding lives in the pure `coyote_protocol.py`. Owns
  the ~100 ms B0 strength + waveform cadence loop and wakes it early on a
  strength change (asyncio event). Paired with `coyote_router.py`.
* **`owo_engine.py` — OWO suit muscle EMS.** A `ReconnectingEngine` over the
  vendor OWO .NET SDK, isolated behind `owo_sdk.py` (pythonnet + a vendored
  `OWO.dll`; both optional and guarded, so the app runs without them). Owns
  the sensation re-send cadence because OWO pulses expire (~0.3 s). Paired
  with `owo_router.py`.
* **`handy_engine.py` — The Handy stroker (Handy 2 / Pro 2).** A
  `ReconnectingEngine` over the official handyfeeling.com REST API v3
  (cloud-routed; firmware 4 devices). Two control modes straight from the
  first-party examples: HAMP (`/hamp/velocity`, level drives stroke speed —
  the default) and HDSP (`/hdsp/xpt` position+duration, fire-and-forget via
  `immediate_rsp`). The cloud API is rate limited (~240 req/min documented),
  so the engine owns a latest-wins send loop with a configurable per-command
  cap; the pure `HandySpeedPlanner` / `HandyPositionPlanner` decision cores
  decide WHAT to send and are unit-tested without network. Paired with
  `handy_router.py`.

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
  `last_outputs` debouncer. Reads `mode_manager.get_active_profile_dict()`
  against `ParameterStore.snapshot()` each tick; only fires a queue
  event when the target value actually changes.
* **`steamvr_router.py` — SteamVR tracker routing.** Same pattern,
  reads tracker-config dicts via a getter and emits haptic pulses
  through `SteamVREngine`.
* **`bhaptics_router.py` — bHaptics dot routing.** Translates the OGB /
  bHapticsOSC parameter shape into per-position dot intensity grids,
  with antistuck timers, and emits frames through `BHapticsEngine`.
* **`coyote_router.py` / `owo_router.py` / `handy_router.py` — level
  routing.** All map OGB zones (+ filters) to a per-output level, shaped by a
  per-output threshold / gain, then dispatch only changed targets. Coyote
  drives two A/B channels; OWO drives ten muscle groups (coalesced into one
  debounce key so the engine gets the whole active map); the Handy is a
  single-output stroker, so its router pushes one quantized 0-1 level and the
  engine decides what it means (HAMP velocity vs HDSP position).
* **`pishock_router.py` — PiShock discrete-event routing.** *Not* a level
  router: a shock fires a single (op, intensity, duration) event on a
  **rising edge**, with hysteresis re-arm, a per-zone cooldown, and a global
  sliding-window rate backstop — a second safety layer on top of the engine's
  hard caps. Its `decide_fire` / `map_intensity` / `RateLimiter` helpers are
  pure and unit-tested without a thread.

Each router lives next to its engine; none of them holds long-lived
hardware state. The continuous-level routers share `router_base.py`'s
`PollingRouter`: a debounced ~60 Hz poll loop where a subclass declares only
`compute_targets()` + `dispatch()`. The base also owns the **stale-signal
cutoff**: when no OSC packet has arrived for ~5 s (VRChat crashed or closed
mid-contact), every enabled output is pulled to its zero level once and the
router goes idle until traffic returns — the shared analogue of
motor_router's anti-stuck fuse and SteamVR's no-data fallback, so e-stim /
EMS / stroking can never latch on a frozen parameter snapshot. `steamvr_router`, `coyote_router`,
`owo_router`, and `handy_router` subclass it directly; `bhaptics_router` keeps its bespoke `_tick`
(anti-stuck ramp + raw/override snapshots don't fit the flat target model) but
still inherits the loop; `motor_router` stays fully separate (it's driven from
the UI thread via `force_recalculate`, not a poll thread); and `pishock_router`
keeps its own edge logic. The shared OGB / SPS zone→strength math lives in
`zone_strength.py` (pure functions), so every non-Buttplug router resolves a
zone — detected OGB or synthetic SPS source — identically.

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
    * `ui/views/` — one module per sidebar view (`overview`, `dashboard`,
      `device_frame`, `steamvr`, `bhaptics`, `sps_sources`, `sessions`,
      `diagnostics`, `settings`). Each builds its view and calls
      *only* controller facade methods.
    * `ui/motor_signal_chain.py` — the per-motor signal-chain widget
      (Input → Depth/Speed/Punch → Combine → Gate → Arming →
      Smoothing → Texture → Zero cut → Output), embedded in Device
      Routing's motor cards (see `docs/MOTOR_SIGNAL_CHAIN.md`).
    * `ui/trace_graph.py` — custom-painted scrolling time-series plot used
      by the chain mini-graphs and the chains' `▸ Overview` disclosure.
    * `ui/fold_strip.py` — the chain's visual language (collapsible fold
      cards joined by painted arrows, purple→pink activity rings)
      extracted into reusable `FoldCard` / `FoldStrip` widgets; the
      backend views build their per-item cards on it.
    * `ui/osc_variable_picker.py` — modal picker listing live avatar
      parameters from `parameter_store`, with search + manual entry.
    * `ui/help_mode.py` — toggle-driven `?` badges + popovers anchored to
      the controls they explain; badges live in every view, toggled from
      the sidebar (or the Device Routing header), and stage editors keep
      their explanations in badges instead of permanent labels.
    * `ui/flow_layout.py` — a `FlowLayout` port (PySide6 ships none) for
      the Overview tile grid.
* **Rule:** It only knows how to draw widgets. If the user clicks a
  button it fires an event to the Controller (`main.py`). It never
  executes hardware or file-saving logic itself. Swapping toolkits
  (back to Tk, forward to QML, anything else) should mean rewriting
  `ui_components.py` plus the `ui/` package, and nothing else. The
  sole sanctioned reach-out to backend code is reading
  `parameter_store.store` for live debug views.
* **Rule: hidden pages do no background work.** Every periodic UI
  refresher (status pollers, activity-ring ticks, the bHaptics grid
  pump) early-outs while its page isn't visible, the chain widgets'
  router trace subscriptions attach on `showEvent` and detach on
  `hideEvent`, and `select_view` refreshes a page once on arrival so
  it never shows stale data. New views must follow the same pattern.
  Signal processing never depends on this: the engines/routers run in
  their own threads, and `motor_router.needs_settling()` keeps the
  routing tick alive while any motor output is non-zero, so smoothing
  tails and the anti-stuck cutoff always complete no matter which
  page is on screen.

### 6. The Traffic Cop — `main.py` + the `controllers/` mixins

* **Role:** The Orchestrator / Controller.
* **Mechanism:** `OscGoesPurrrApp` in `main.py` boots the threads,
  holds the `mode_manager`, and routes data between layers. Its
  call surface is intentionally split:
  * `main.py` itself holds the core API — boot, queue draining, the
    routing tick, device config plumbing, feature flags,
    simple-mode, and OSC diagnostics.
  * Per-engine and per-subsystem facade mixins live under `controllers/`
    and are composed into `OscGoesPurrrApp` via multiple inheritance:
    * `controllers/intiface_facade.py` — `IntifaceFacade` (the
      Buttplug/Intiface surface: engine-loop bootstrap, manual +
      auto-connect lifecycle, device rescans, per-toy tests/mutes,
      linear-config sync, hot target dispatch)
    * `controllers/steamvr_facade.py` — `SteamVRFacade`
    * `controllers/steamvr_toys_facade.py` — `SteamVRToysFacade`
    * `controllers/bhaptics_facade.py` — `BHapticsFacade`
    * `controllers/pishock_facade.py` — `PiShockFacade`
    * `controllers/coyote_facade.py` — `CoyoteFacade`
    * `controllers/owo_facade.py` — `OwoFacade`
    * `controllers/handy_facade.py` — `HandyFacade`
    * `controllers/osc_facade.py` — `OscFacade` (VRChat OSC connection
      lifecycle + diagnostics)
    * `controllers/modes_facade.py` — `ModesFacade` (the six haptic
      modes: switching, metadata editing, device seeding, per-avatar
      memory, and the VRChat `OGP/Mode` / `OGP/Test` integration)
    * `controllers/sps_sources_facade.py` — `SpsSourcesFacade`
      (synthetic SPS source CRUD; the routers read the live source map)
    * `controllers/sessions_facade.py` — `SessionsFacade` (session-logger
      lifecycle — see "Session logging" below)
    * `controllers/stats_facade.py` — `StatsFacade` (usage statistics:
      owns the `StatsTracker`, samples usage at 1 Hz off the UI
      heartbeat, exposes `get_stats_snapshot()` / `reset_stats()`)
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

## Latency budget (load-bearing)

This app exists to make physical hardware react to VRChat **in real time**.
Perceived quality lives and dies on end-to-end latency — the time from an
OSC packet arriving to the device actually moving — so minimizing it is a
first-class design constraint, on par with the anti-tangling rules. The
standalone `testbench/` measures it (input edge → toy output on one clock);
use it to confirm a change didn't regress the Buttplug path.

**The shared hot path:** UDP OSC → `parameter_store` (event-driven write) →
a *router* (computes the target) → an *engine* (talks to hardware) →
device. Every stage that re-samples on its own timer, buffers, or blocks on
an ack adds latency. Keep each stage tight.

**Per-backend pipeline (current):**

* **Buttplug toys** (`motor_router` → `haptic_engine`). The routing tick
  (`ROUTER_POLL_RATE_MS`, ~60 Hz, gated by `_needs_recalculation`)
  dispatches **directly** to the engine via
  `force_recalculate(dispatch_direct=True)` — it does **not** route hot
  updates through `thread_queue` (that queue is the UI pump, drained only
  every `QUEUE_POLL_RATE_MS` = 50 ms, and carries status / device events
  *only*). The engine loop (`HAPTIC_POLL_RATE`, ~100 Hz) sends
  **fire-and-forget** (never awaits Intiface's ack), bounded by a
  per-feature cap (`HAPTIC_MAX_SEND_HZ`, ~60 Hz) so a real BLE toy isn't
  flooded. ≈27 ms end-to-end on the bench (was ≈60 ms). The per-feature
  send decisions (change gate, in-flight guard, caps, linear delta gate,
  duration sizing) live in the pure `send_gate.FeatureSendGate` so the
  invariants are unit-testable without a connection.
* **Linear / strokers** — same engine loop; fire-and-forget, with an
  in-flight guard keeping position commands strictly in order. Sends are
  capped at `LINEAR_MAX_SEND_HZ` (20 Hz) — lower than the vibrate cap
  because Buttplug Spec v4 servers coalesce strokers to one flush per
  device message gap anyway (The Handy: 50 ms per the official device
  config) — and the commanded `duration` is sized from the *real* gap
  since the last send (× overlap) so motion stays continuous at that
  cadence. The stroke physics still ticks every loop.
* **Per-motor VRChat param-out** (`motor_param_out.py` →
  `osc_manager.send_parameter`). Optional: a motor can mirror its computed
  0..1 output back to VRChat as an avatar parameter (drive a visual, not a
  toy). It rides the *same* change-debounced `updates` list inside
  `force_recalculate` — so it only sends on a real value change — and the
  send is a fire-and-forget UDP write on the producing thread (no queue hop,
  no ack), bounded by `send_parameter`'s per-address rate limit. The pure
  config→(address, value) mapping lives in `motor_param_out.py`; the
  controller owns the actual send. Active in full routing mode only (Simple
  Mode bypasses per-toy device config); independent of toy connection and
  per-toy mute, since it reflects the contact, not the device.
* **bHaptics** (`bhaptics_router` → `bhaptics_engine`). Router polls
  `parameter_store` at ~60 Hz (debounced — held contacts don't resubmit);
  the engine submit is a fire-and-forget `ws.send`.
* **SteamVR trackers** (`steamvr_router` → `steamvr_engine`). Router polls
  at ~60 Hz; each tracker's `_FeedbackThread` **wakes immediately** on a
  strength change (a `threading.Event`) instead of sleeping out its pulse
  interval. The sustain cadence / intensity model is unchanged — only a
  *changed* value pulses early. Floor is OpenVR's one-pulse-per-frame limit
  (~90 Hz).
* **Coyote** (`coyote_router` → `coyote_engine`). Router polls ~60 Hz
  (debounced via `PollingRouter`); the engine owns the ~100 ms B0 frame
  cadence (the hardware's send cap) and **wakes it early** on a strength
  change (an asyncio event), so a contact edge reaches the device with
  near-zero added latency. BLE writes are fire-and-forget (`response=False`).
* **OWO** (`owo_router` → `owo_engine`). Router polls ~60 Hz (debounced); the
  engine owns a ~0.25 s sensation re-send loop because OWO pulses expire at
  ~0.3 s. A changed muscle map **wakes the loop** (threading event, floored
  at a 50 ms send gap so a sweeping router can't flood the OWO app) so an
  edge is applied immediately; the cadence only keeps a held contact alive,
  and a release edge sends an explicit Stop instead of waiting out the tail.
* **PiShock** (`pishock_router` → `pishock_engine`). A *discrete-event*
  backend, not a level stream: the router polls ~60 Hz and fires one event on
  a rising edge, fire-and-forget. Here the per-feature send cap is a
  deliberate **safety** floor — a min-interval cooldown re-clamped inside
  `fire()` plus a global rate backstop in the router — so the device rate is
  intentionally bounded *for the human*, not for latency. The first edge after
  idle still fires immediately.
* **Handy** (`handy_router` → `handy_engine`). Router polls ~60 Hz (debounced,
  level quantized); the engine owns a latest-wins send loop because the
  transport is the handyfeeling **cloud** REST API (v3) with a documented
  ~240 req/min budget — here the send cap protects the *account quota*, not a
  BLE radio. The loop wakes early on a level change (threading event), the
  first command after a quiet gap goes immediately, and HTTP runs on the
  loop's own thread with `immediate_rsp` so nothing upstream ever blocks on
  the round-trip. Cloud RTT dominates this backend's end-to-end latency; the
  app-side budget rules still apply so we never add to it.

**The patterns (reach for these):**

1. **Direct dispatch** — hand a freshly computed value to the engine on the
   thread that produced it; don't bounce it through a slowly-drained queue.
2. **Fire-and-forget sends** — never `await` a device / server ack on the
   hot loop; dispatch it as a task (hold a strong ref; handle errors inside
   the task). One in-flight send per feature preserves order and prevents
   pile-up.
3. **Per-feature send cap** — keep the loop fast for latency, but throttle
   the *hardware* command rate so real BLE devices aren't flooded. The cap
   must only delay *consecutive* rapid changes, never the first change after
   idle (so step/edge latency is untouched).
4. **Fast, debounced polling** (~60 Hz) for router threads that can't be
   event-driven; debounce so a held value adds no traffic.
5. **Event-driven wake** for any sustain loop (e.g. the SteamVR pulse
   train): wake on change rather than waiting out the interval.

**Anti-patterns (do NOT):**

* Route hot haptic updates through `thread_queue` or any UI-polled queue
  (that hop cost ~25 ms average — it was the single biggest latency tax).
* `await` a per-command ack inside an engine loop (serializes every device
  and stalls the loop).
* Poll a router slower than ~60 Hz without a hardware reason.
* Put smoothing / debounce *delay* on the transport path — value *shaping*
  belongs in the mixer (`mixer.py` / `motor_router`), never in dispatch.

**Tuning constants** (`constants.py`): `ROUTER_POLL_RATE_MS` + the
`router_poll_rate_hz` setting (Buttplug tick), `HAPTIC_POLL_RATE` (engine
loop), `HAPTIC_MAX_SEND_HZ` (per-feature send cap). The bHaptics / SteamVR
router poll rates are constructor defaults (~16 ms).

---

## Mode model (`config_manager.py`)

The on-disk config file is `profiles.json` (v3 schema — the name stays
for continuity; v1/v2 profile files are migrated one-shot with a
`profiles.json.v2.bak` backup). The individual settings managers and
their file-path constants live in the `settings/` package (one module
per concern: `app.py`, `bhaptics.py`, `steamvr.py`, `pishock.py`,
`coyote.py`, `owo.py`, `handy.py`, `known_devices.py`, `sps_sources.py`,
`sessions.py`; paths in `_paths.py`). Most concerns share the
load-or-create-defaults / merge / atomic-save plumbing in
`settings/_base.py`'s `JsonSettingsManager` — a subclass declares only
`DEFAULTS` + `FILE_PATH` and (for nested structure) `_post_load()`. The
managers are re-exported from `config_manager.py` so existing `from
config_manager import X` callers keep working. `ModeManager` (in
`config_manager.py`) composes the stores below (the session-settings
manager is owned by `SessionsFacade` instead):

* **`wiring`** — one shared dict per device describing the rig:
  `motor_count`, `motor_kinds`, `osc_addresses`, zone assignments,
  interaction filters, param-out mapping, linear actuator envelope,
  icon override. Shared by every mode — edit once.
* **`modes`** — exactly six fixed slots (defaults: 🔇 Off, 🔈 Low,
  🔉 Medium, 🔊 High, 🌙 Sleep, 🃏 Custom; all renameable). Each mode
  carries its own per-device per-motor `mix` layer (the signal-chain
  *feel*), a `master_scale` (0–1 multiplier applied at every backend's
  final dispatch; Off ships 0.0 — the panic mode), a name, and an icon.
  Switchable from the sidebar grid, the Dashboard, or VRChat's
  expression menu (`OGP/Mode` Int; see `docs/VRCHAT_MENU.md`).
* **`avatar_last_mode`** — per-avatar memory of the last active mode;
  applied on avatar change only when the `avatar_modes_enabled` app
  setting is on.
* **`app_settings`** (`AppSettingsManager`) — UI-level toggles
  (`auto_refresh`, `auto_connect`, `bind_all_interfaces`, window
  geometry, console visibility, speed-tuning, feature flags…).
* **`steamvr_settings`** (`SteamVRSettingsManager`) — per-tracker
  configs, patterns, autostart / auto-connect, battery interval,
  no-data fallback.
* **`bhaptics_settings`** (`BHapticsSettingsManager`) — endpoint,
  auto-connect, per-position device configs, antistuck timings, the
  `bHaptics_Connected` OSC bool config.
* **`pishock_settings`** (`PiShockSettingsManager`) — transport mode
  (serial / cloud) + its connection fields, auto-connect, the user's safety
  caps (clamped again in the engine), the global rate backstop, and the
  per-zone rising-edge configs.
* **`coyote_settings`** (`CoyoteSettingsManager`) — BLE device address / name,
  auto-connect, per-channel A/B strength limits + waveform, and the per-channel
  zone routing.
* **`owo_settings`** (`OwoSettingsManager`) — OWO app connection (game id /
  IP), auto-connect, frequency, and the per-muscle zone routing.
* **`handy_settings`** (`HandySettingsManager`) — handyfeeling cloud
  credentials (connection key + API key), auto-connect, motion settings
  (control mode, slider stroke zone, speed cap, command-rate cap), and the
  single zone routing.
* **`known_devices`** (`KnownDevicesRegistry`) — global registry of
  every toy ever seen; the wiring store (and each mode's feel presets)
  are seeded from it.
* **`sps_sources`** (`SpsSourceManager`) — global registry of
  user-defined *synthetic SPS sources*: virtual contact zones assembled
  from raw VRChat receivers (proximity + activation gate + velocity
  multiplier + max-value clamp). Global, like `known_devices`, so a
  source is selectable in any mode. The pure evaluation math lives
  in `sps_source.py`; both `motor_router` and `bhaptics_router` resolve a
  selected source name against the map the controller passes in each
  tick, so a synthetic source routes exactly like a detected OGB zone.

### The merged active view (wiring + feel)

`get_active_profile_dict()` (name kept from the profile era) returns the
live `{device: merged config}` map: the wiring dicts with the active
mode's per-device `mix` installed **by reference** under the `"mix"`
key. Two identity guarantees are load-bearing:

* The top-level dict and every per-device dict are **never rebuilt** —
  a mode switch swaps only each device's `"mix"` value. The router's
  compiled-config cache keys on `id()`, so rebuilding the view per tick
  would recompile every motor at 60–90 Hz.
* Wiring keys may be mutated in place (call `save_profiles()`
  afterwards, as before); `"mix"` writes must go through
  `update_device_config(device, "mix", value)` so the active mode's
  store and the installed reference stay the same object.

`master_scale` is applied as one inline multiply at each backend's final
dispatch (toys: `update_device_target`; the polling routers take a
`get_master_scale` getter) — zero added latency. Any change that alters
output without changing router inputs (mode switch, scale edit, test
pulse) must call `ModesFacade._reset_output_caches()` so every router's
change-debounce re-dispatches on the next tick.

---

## Auxiliary modules

* `constants.py` — app-wide constants (`APP_NAME`, `INTIFACE_WS_URL`,
  `INTIFACE_ENGINE_DIRNAME`, `INTIFACE_ENGINE_STARTUP_GRACE_S`,
  default window geometry, OSC defaults).
* `intiface_connection.py` / `intiface_external.py` /
  `intiface_integrated.py` — the Buttplug-server connection providers and
  their selecting factory (see the haptic_engine entry above).
* `engine_base.py` / `router_base.py` / `zone_strength.py` — the shared base
  layer the newer backends build on: the cold-path connection supervisors
  (`ReconnectingEngine` / `AsyncReconnectingEngine`), the debounced
  `PollingRouter` poll loop, and the pure OGB / SPS zone→strength evaluator.
* `pishock_connection.py` / `pishock_serial.py` / `pishock_cloud.py` — the
  PiShock transports (USB-serial / pishock.com cloud) and their selecting
  factory, mirroring the Intiface seam so neither `serial` nor `requests` is
  imported until its mode is chosen.
* `coyote_protocol.py` — pure Coyote 3.0 BLE wire codec (B0 / B1 / BF
  frames + UUIDs); no I/O, trivially testable.
* `owo_sdk.py` — guarded one-shot loader for the vendor OWO .NET SDK via
  pythonnet, so the rest of the app never imports `clr`.
* `utilities.py` — small helpers (`value_to_hex_color`,
  `toggle_windows_console`, `create_default_icon`).
* `update_checker.py` — sealed one-shot GitHub release check
  (`check_for_update`); never raises, never blocks startup. The
  controller spawns a daemon thread around it and routes the result
  through `thread_queue` as an `update_checked` event.
* `settings_snapshots.py` — sealed launch-time settings backups:
  `make_snapshot` copies every top-level settings JSON into
  `backups/<timestamp>/` once per launch (before ModeManager loads,
  keeping the newest five), `list_snapshots` / `restore_snapshot` back
  the Settings → Quality of Life restore UI. No background process.
* `stats_tracker.py` — sealed usage-statistics accumulator: lifetime
  totals + per-session summaries (active time, thrusts, per-toy
  on-time, per-zone contact time) with atomic JSON persistence to
  `stats.json` and an injectable clock. Driven by
  `controllers/stats_facade.py` (`StatsFacade`), which samples toy
  outputs, zone contact, and the motor router's O(1) thrust counter at
  1 Hz off the UI heartbeat — never on a routing hot path.
* `version.py` — single source of truth for `__version__`.
* `settings/` — per-user settings managers, one JSON file per concern
  (see the Mode model section above).
* `tools/` — developer scripts, not loaded at runtime
  (`flatten_lovense_icons.py`, `generate_bhaptics_icons.py`,
  `generate_handy_icon.py`, `generate_sim_icon.py`).

---

## Session logging

VR sessions can be recorded to disk for offline analysis and feel
tuning. `session_logger.py` is the sealed-box `SessionLogger` engine;
`controllers/sessions_facade.py` (`SessionsFacade`) owns its lifecycle
plus its `SessionSettingsManager` (`settings/sessions.py`) and adapts the
routing thread's broadcast callbacks into the engine's primitive `log_*`
calls. The Sessions sidebar view (`ui/views/sessions.py`) drives it. Full
design + on-disk format: `docs/SESSION_LOGGING.md`.

---

## Developer tools / the test bench

`testbench/` is a standalone program — strictly **never imported by the app**
(it is a separate program, so the anti-tangling rules stop at that boundary).
It drives a known input signal into the live OGP app and reads the resulting
toy output on one `time.perf_counter` clock, to plot input vs output on a
shared timeline and benchmark end-to-end latency ("program delay"). It absorbs
the two former standalone sims as flat modules in the one package:

* `sim_network.py` + `sim_avatar.py` — VRChat impersonation (mDNS + OSCQuery +
  UDP OSC send; `VRChatSimNetwork` + avatar presets). Was the standalone `sim/`.
* `lovense_device.py` + `lovense_protocol.py` — Intiface/Lovense virtual toy
  (`LovenseToy` websocket transport + the pure `LovenseProtocol` decoder). Was
  the standalone `toysim/`.
* `bench.py` — the measurement core (clock, ring buffers, edge detection,
  latency pairing + stats); pure and thread-safe.
* `generators.py` / `plots.py` / `csv_export.py` / `style.py` / `app.py` —
  signal generators, pyqtgraph plots, CSV export, theme, and the unified window
  (Input / Output / Benchmark modes).

Run with `testbench/run_testbench.bat` (`python -m testbench`); build with
`testbench/build_testbench.bat`. Isolated tests live in `testbench/tests/`
(run via `pytest testbench`; not part of the root `tests/` suite). See
`testbench/README.md` for the Intiface / OGP setup.

---

## How to add a new haptic backend (the official pattern)

1. **Engine** — write `myhardware_engine.py` with a sealed-box class:
   primitive-only public methods, all state private. If it reconnects,
   subclass `ReconnectingEngine` / `AsyncReconnectingEngine` from
   `engine_base.py` and implement only `_open()` / `_close()` / `_available`
   — the connect / reconnect / backoff machinery is shared. Otherwise run
   your own loop / thread. Talk to the outside world via the shared
   `thread_queue` and/or a `state_callback`.
2. **Router** — write `myhardware_router.py` as a pure stateless
   calculator. If it maps zones to a continuous level, subclass
   `PollingRouter` from `router_base.py` (declare only `compute_targets()` +
   `dispatch()`); resolve OGB / SPS zones via
   `zone_strength.zone_filter_strength()` so a synthetic source routes like a
   detected zone. Discrete-event devices (e.g. a shock) keep their own
   rising-edge logic instead. Read the Brain (`parameter_store.snapshot()`)
   and the per-device configs via a getter passed in by the controller;
   debounce on `last_outputs`.
3. **Controller mixin** — add `controllers/myhardware_facade.py`
   containing a `MyHardwareFacade` mixin with the UI-facing methods
   (`get_myhardware_status()`, `set_myhardware_*()`). The mixin's
   docstring lists the host attributes it assumes.
4. **Compose** — add `MyHardwareFacade` to `OscGoesPurrrApp`'s base
   list in `main.py`. Instantiate the engine + router in
   `_setup_components()`.
5. **Settings** — add a `MyHardwareSettingsManager` in `settings/`
   (subclass `JsonSettingsManager` from `settings/_base.py`: declare
   `DEFAULTS` + `FILE_PATH`, override `_post_load()` for nested backfills),
   register its path in `settings/_paths.py`, re-export it from
   `config_manager.py`, and instantiate it on `ModeManager`.
6. **UI** — add a card / tab in `ui_components.py` that calls *only*
   the new facade methods. **Do not** import the engine or router from
   the UI.
7. **Latency** — hold the line (§ "Latency budget"): dispatch on the
   producing thread without queue hops, never `await` a device ack on the
   loop, poll / loop at ~60 Hz (or wake event-driven), and cap the
   *hardware* send rate only if the device needs it. A new backend that
   buffers or blocks on the hot path is a regression even if it "works".

Following this recipe means the four anti-tangling rules at the top of
this document and the latency budget all keep holding without anyone
having to re-audit them.
