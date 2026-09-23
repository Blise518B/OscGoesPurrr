# OscGoesPurrr — AI Context & Architecture Documentation

_Module paths below are relative to `src/`; scripts and the Test Bench
live in `tools/`._

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
   `controller.osc_manager`, `controller.motor_router`, or any other
   service). It MUST go through facade methods on the Controller
   (e.g. `controller.get_app_setting()`, `controller.update_device_target()`,
   `controller.switch_mode()`, `controller.get_modes_info()`,
   `controller.get_active_profile_dict()`,
   `controller.set_haptic_connected()`, `controller.get_intiface_status()`).
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
   — here, `HapticEngine` — is a sealed black box. Do not pass
   dictionaries between threads. The outside world communicates with each
   engine exclusively via its primitive-only facade and (where
   applicable) via the shared `thread_queue`.
   * `HapticEngine` exposes `update_target()`, `set_linear_config()`,
     `mark_connected()`, `set_connection_mode()`,
     `release_managed_server()`, `list_connected_device_names()`,
     `get_motor_count_map()`, `snapshot_discovered_devices()`,
     `async_start_scan()`, `async_connect()`, `async_disconnect()`,
     `async_purr_check()`, `async_test_device()`. It never exposes
     `buttplug_client` or `device.*` — those are private to the engine.
     The engine owns its `device_targets` memory and its `is_connected`
     flag (writers go through `mark_connected()`).
   * Any backend added later follows the same pattern: primitive-only
     public methods, internal state stays internal, UI-facing call
     surface on a mixin in `controllers/` (see "The Traffic Cop" below).
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
  facades that need to push values back to VRChat (the OGP menu control
  set, and any motor mirroring its value as an avatar parameter).
* **Rule:** It is entirely memoryless. It parses incoming OSCQuery JSON
  and UDP packets and immediately dumps them into the Brain.

#### The receive fallback (`osc_router_518.py`)

VRChat's mDNS **listener** dies after a few hours of gameplay: it keeps
announcing itself and keeps accepting our outbound sends, but it never
again discovers a freshly advertised app, so we receive nothing until
VRChat restarts. `Router518Fallback` can take the stream from a local OSC
relay instead. The relay isn't published yet — without one running, all
of this is a silent no-op, and the app neither shows nor mentions it.

The fallback runs on its own thread, re-reading a small `OscFlowState`
snapshot every 2 s:

* **Tier 0 (default)** — plain OSCQuery, VRChat pushes to us directly.
  The router is never contacted.
* **Tier 1 (automatic)** — when nothing has arrived *directly* from
  VRChat for 10 s after advertising (30 s for an already-established
  stream), subscribe our existing receive port at the local router
  (`127.0.0.1:18518`) and take VRChat's re-broadcast stream instead. The
  Tier 0 advertisement stays up, so when VRChat rediscovers us the direct
  stream resumes and we unsubscribe automatically.

**The direct/router split is load-bearing.** Router traffic arrives on the
same UDP port as VRChat's own, so `VRChatOSCManager` classifies every
datagram by source address (`_dispatch_incoming`) and the ladder watches
`seconds_since_direct_packet()` alone. If router traffic counted as
healthy discovery, Tier 1 would unsubscribe itself the instant it started
working, starve, re-subscribe, and oscillate forever. For the same reason
the silent-connection watchdog also judges on direct traffic — it must keep
trying to restore real discovery while Tier 1 carries the data.

A missing router is a silent no-op: this is the fallback, it must never
become a failure mode of its own. Gated by `feature_osc_router_518`.

### 3. The Muscles — a sealed engine

This edition ships one hardware backend. The full-featured build fans the
same OSC state out to eight of them side-by-side — SteamVR tracker
haptics, bHaptics, PiShock, DG-Lab Coyote, OWO, The Handy, PSVR2 — all
following the sealed-box contract below, and they are deliberately absent
here rather than shipped half-finished. What stays is the contract, so
adding one back is adding files (see "How to add a new haptic backend").

* **`haptic_engine.py` — Buttplug.io toys.** Runs its own isolated
  `asyncio` event loop in a worker thread. Owns the
  `ButtplugClient`, the discovered-devices list, and the per-motor
  `device_targets` map. The async loop is bootstrapped from
  `main.start_async_loop()`. It does **not** know how the Buttplug server
  is provisioned — that is delegated to a swappable connection provider,
  selected via `set_connection_mode()`.
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
      it lives in `src/intiface-engine/` and is bundled by `tools/build_OGP.bat`.

**Rule:** every engine owns its internal state. The outside world
communicates with each one *exclusively* through its primitive-only
public methods (and, where the engine has hot output, the
`thread_queue`).

### 4. The Stateless Routers

We do not use state machines to track interactions. Each router is a
pure, stateless calculator that reads the Brain and tells its engine
what to do.

* **`motor_router.py` — Buttplug routing.** Owns the signal-chain math
  (Wake, the Depth/Speed/Punch mix, smoothing, texture, zero cut, curves,
  the output gain + band), the touch/pen/self/other filter, the anti-stuck
  fuse, and the per-motor `last_outputs` debouncer. Reads
  `mode_manager.get_active_profile_dict()` against `ParameterStore.snapshot()`
  each tick; only fires a queue event when the target value actually
  changes. It is driven from the UI thread via `force_recalculate`, not a
  poll thread.

Two shared pieces outlive the backends that used to subclass them, and
are kept because they are the documented extension point for adding one
back:

* **`router_base.py`** — `PollingRouter`, a debounced ~60 Hz poll loop
  where a subclass declares only `compute_targets()` + `dispatch()`, over
  `polling.py`'s `PollingThread`. It also owns the **stale-signal cutoff**:
  when no OSC packet has arrived for ~5 s (VRChat crashed or closed
  mid-contact), every enabled output is pulled to its zero level once and
  the router goes idle until traffic returns. `PollingRouter` has no
  subclass in this edition; its `StaleSignalMonitor` is live —
  `controllers/stats_facade.py` uses it to stop counting active time when
  the signal dies.
* **`zone_strength.py`** — the pure OGB / SPS zone→strength math, so any
  router resolves a zone — detected OGB or synthetic SPS source —
  identically. Used today by the SPS-sources facade and the stats tracker.

### 5. The Face — `ui_components.py` + the `ui/` package

* **Role:** The "dumb" View Layer.
* **Mechanism:** Renders the interface using **PySide6 / Qt** (a global
  `GLOBAL_QSS` stylesheet plus widget objects). Vector icons are drawn
  at runtime via `QPainter` so the app does not depend on emoji-font
  availability.
  * **Look:** the 518 design system. `theme_tokens.py` is a verbatim
    copy of `_hub\design\theme_tokens.py` and the only place a colour
    is spelled out; `constants.py` resolves the persisted mode
    (`ui_mode`: Neon default / Midnight, Qt-free so the router can
    import it) into the `COLOR_*` names the app was written against;
    `ui/theme.py` builds the stylesheet from those tokens and declares
    OGP's semantic roles (live signal = pink, running = cyan,
    warnings = amber, errors = red). A mode switch persists and
    relaunches, because every module copies the colours at import.
  * `ui_components.py` is the main `OscGoesPurrrUI` class — the
    controller-facing facade and the live update sinks.
  * The `ui/` subpackage contains the bits factored out so the main
    class isn't the only home for view-layer code:
    * `ui/widgets.py` — `Card`, `ToggleSwitch`, `RainbowMeter`,
      `RainbowScrollBar`, `MainWindow`, `SliderProxy`,
      `ProgressProxy`, `Invoker`, scrollbar install.
    * `ui/icons.py` + `ui/lovense_icons.py` — `QPainter`-drawn vector
      icons and the Lovense-shape icon set.
    * `ui/geometry.py` — Tk-style geometry string parsing (kept for
      compat with on-disk settings written by older versions).
    * `ui/layout_helpers.py`, `ui/text_helpers.py` — small helpers.
    * `ui/views/` — one module per sidebar view (`overview`,
      `device_frame`, `sps_sources`, `sessions`, `statistics`,
      `diagnostics`, `settings`), plus `dashboard` — named for the page
      it used to build — which now holds the sidebar's control block
      (modes, the total output strength bar, Off / Sleep) and the Device
      Routing page. Each builds its view and calls *only* controller
      facade methods. The app opens on the Overview.
    * `ui/motor_signal_chain.py` — the per-motor signal-chain widget
      (Input → Depth/Speed/Punch → Combine → Wake → Envelope →
      Zero cut → Output; Wake merges the old Gate + Arming into one
      two-mode stage, Envelope pairs Smoothing + Texture as two halves),
      embedded in Device Routing's motor cards (see
      `MOTOR_SIGNAL_CHAIN.md`).
    * `ui/trace_graph.py` — custom-painted scrolling time-series plot used
      by the chain mini-graphs and the chains' `▸ Overview` disclosure.
    * `ui/fold_strip.py` — the chain's visual language (collapsible fold
      cards joined by painted arrows, purple→pink activity rings)
      extracted into reusable `FoldCard` / `FoldStrip` widgets.
    * `ui/osc_variable_picker.py` — modal picker listing live avatar
      parameters from `parameter_store`, with search + manual entry.
      Shared by Device Routing motors and SPS Sources contacts.
    * `ui/tooltips.py` — hover explanations, the app's only in-place
      help: `explain(target, title, text)` puts a themed, word-wrapped
      tooltip on a widget, every widget in a layout, or a container whose
      plain children fall back to it through Qt's parent lookup. Every
      control carries one; the signal chain sets one per stage on the
      stage card (`_STAGE_TIPS`), so each knob inside inherits it. Tests
      open every stage and fail on a control without one.
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
  refresher (status pollers, activity-ring ticks) early-outs while its
  page isn't visible, the chain widgets'
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
    * `controllers/osc_facade.py` — `OscFacade` (VRChat OSC connection
      lifecycle + diagnostics)
    * `controllers/modes_facade.py` — `ModesFacade` (the four routing
      modes: switching, metadata editing, device seeding, per-avatar
      memory, the global strength + Off/Sleep toggles, and the VRChat
      `OGP/Mode` / `OGP/Strength` / `OGP/Off` / `OGP/Sleep` / `OGP/Test`
      integration)
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

---

## Latency budget (load-bearing)

This app exists to make physical hardware react to VRChat **in real time**.
Perceived quality lives and dies on end-to-end latency — the time from an
OSC packet arriving to the device actually moving — so minimizing it is a
first-class design constraint, on par with the anti-tangling rules. The
standalone `tools/testbench/` measures it (input edge → toy output on one clock);
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
  device message gap anyway (50 ms for a typical stroker, per the
  official device config) — and the commanded `duration` is sized from the *real* gap
  since the last send (× overlap) so motion stays continuous at that
  cadence. The stroke physics still ticks every loop.
* **Per-motor VRChat param-out** (`motor_param_out.py` →
  `osc_manager.send_parameter`). Optional: a motor can mirror its computed
  0..1 output back to VRChat as an avatar parameter (drive a visual, not a
  toy). The send is a fire-and-forget UDP write on the producing thread (no
  queue hop, no ack), bounded by `send_parameter`'s per-address rate limit.
  The pure config→(address, value) mapping lives in `motor_param_out.py`;
  the controller owns the actual send. Independent of toy connection and
  per-toy mute, since it reflects the contact, not the device.

  It is fed by `MotorRouter.consume_contact_updates()`, **not** the
  `updates` list the toys ride. Two reasons, both consequences of the
  global strength moving upstream into the chain's Output stage:

  1. `updates` carries the toy's *drive* value — post-gain, post-strength,
     post-output-band. A visual driven from that would dim when the
     strength slider moved and jump to a toy's 20 % floor. The contact
     stream stops the chain one stage earlier (post-wake, post-zero-cut,
     post-smoothing, post-anti-stuck — everything that shapes the contact
     — but pre-Output).
  2. The two need separate change debouncing. In Off every toy value is
     pinned at 0, so `updates` goes empty while contact keeps moving;
     riding it would freeze the mirror exactly when the panic switch is
     on.
Every other backend in the full edition (bHaptics, SteamVR trackers,
Coyote, OWO, PiShock, Handy, PSVR2) obeys the same shape: poll the store
at ~60 Hz debounced, dispatch fire-and-forget on the producing thread, and
where the hardware, an account quota or the human needs a send cap, own it
in the engine with an event-driven early wake so the first change after
idle is never delayed.

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
5. **Event-driven wake** for any sustain loop: wake on change rather
   than waiting out the interval.

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
loop), `HAPTIC_MAX_SEND_HZ` (per-feature send cap). A `PollingRouter`
subclass takes its poll rate as a constructor default (~16 ms).

---

## Mode model (`config_manager.py`)

The on-disk config file is **`modes.json`** (v4 schema). The pre-v4 file,
`profiles.json`, is read exactly once — to seed `modes.json` on the first
launch after the split — and **never written again**.

*Why two filenames.* v4 restructured the file (four routing modes over a
shared rig + feel, replacing six feel-carrying modes). A pre-v4 build
meeting a v4 file cannot read the schema, so it renames the file aside
and starts from defaults — silently wiping every routing choice. Sharing
one filename across two schema versions means every alternation between
an old build and a new one destroys config, and since routing is the only
layer that moved, the visible symptom is "my input parameters and zone
selections don't save". Two names, no collision: an old build keeps
reading `profiles.json`, this one keeps reading `modes.json`, neither
touches the other's, and the two configs simply diverge.

Seeding takes a v3 `profiles.json` (six feel-carrying modes over shared
routing) and migrates it: the old **High** slot's chains become the
shared feel — it was the only slot holding the tuning at full scale, the
others were gain-scaled copies — the shared routing is copied into all
four new slots, and `strength` is seeded from whichever tier was active
so the upgrade is inaudible. A v4 `profiles.json` (written by a build
from before the rename) is adopted as-is. A `modes.json` that can't be
read is preserved aside as `modes.json.<reason>-<epoch>.bak` and replaced
with fresh defaults, never guessed at — the timestamp matters, because a
fixed `.bak` name is destroyed by the second rescue, which is exactly
when the first one is the only good copy left. The individual settings managers and
their file-path constants live in the `settings/` package (one module
per concern: `app.py`, `known_devices.py`, `sps_sources.py`,
`sessions.py`; paths in `_paths.py`). Most concerns share the
load-or-create-defaults / merge / atomic-save plumbing in
`settings/_base.py`'s `JsonSettingsManager` — a subclass declares only
`DEFAULTS` + `FILE_PATH` and (for nested structure) `_post_load()`. The
managers are re-exported from `config_manager.py` so existing `from
config_manager import X` callers keep working. `ModeManager` (in
`config_manager.py`) composes the stores below (the session-settings
manager is owned by `SessionsFacade` instead):

* **`wiring`** — one shared dict per device describing the rig:
  `motor_count`, `motor_kinds`, `icon_override`, the linear actuator
  envelope, per-motor `speed_blend`. Describes the hardware, so it is
  shared by every mode.
* **`feel`** — the per-device per-motor `mix` layer (the signal-chain
  config). **One copy for the whole app**: tune a chain once and every
  mode uses it. A chain that runs hot relative to the rig is trimmed with
  its own Output stage (`gain` in `[0, 2]`, plus the toy's usable
  `min`/`max` output band) — hardware calibration, not intensity.
* **`modes`** — exactly four routing slots (defaults: 🔗 Combined,
  🔀 Separate, 🃏 Custom 1, 🎲 Custom 2; all renameable). Each mode
  carries its own per-device `routing` block, a name, and an icon —
  nothing else. **A mode is a routing**: the same toys wired to the
  avatar differently (every socket combined onto one motor, each socket
  on its own, or anything between). What counts as routing is an explicit
  allowlist in `is_routing_key()` — `osc_addresses`, `motor_N_zones`, the
  four interaction filters, param-out — so a new per-motor tuning key
  defaults to *shared* rather than silently becoming mode-local.
  Switchable from the sidebar's mode buttons or VRChat's expression menu
  (`OGP/Mode` Int 0-3; see `VRCHAT_MENU.md`).
* **`strength`** — the global output multiplier in `[0, 1]`
  (default 0.85). The one knob for how strong everything runs; scales
  every backend at once. Persisted, but written through a **debounced**
  save — a slider drag and a VRChat radial puppet both produce a
  continuous stream of values, and serialising the whole profile per step
  is a real stutter.
* **`output_off` / `sleep_active`** — session-only toggles, deliberately
  **not persisted** (a fresh launch is never silently muted or asleep).
  `output_off` makes `get_master_scale()` return 0.0 — the panic silence.
  `sleep_active` is read by `motor_router` each tick and swaps every
  chain's Wake stage for `MotorRouter.SLEEP_WAKE_OVERRIDE` (stroke
  counter: three strokes inside six seconds); nothing is written to the
  stored chain, so switching it off restores the user's real wake
  settings exactly. Buttplug-only — no other backend has a Wake stage.
* **`avatar_last_mode`** — per-avatar memory of the last active mode;
  applied on avatar change only when the `avatar_modes_enabled` app
  setting is on.
* **`app_settings`** (`AppSettingsManager`) — UI-level toggles
  (`auto_refresh`, `auto_connect`, `bind_all_interfaces`, window
  geometry, console visibility, speed-tuning, feature flags…).
* **`known_devices`** (`KnownDevicesRegistry`) — global registry of
  every toy ever seen; the wiring store (and each mode's feel presets)
  are seeded from it.
* **`sps_sources`** (`SpsSourceManager`) — global registry of
  user-defined *synthetic SPS sources*: virtual contact zones assembled
  from raw VRChat receivers (proximity + activation gate + velocity
  multiplier + max-value clamp). Global, like `known_devices`, so a
  source is selectable in any mode. The pure evaluation math lives
  in `sps_source.py`; `motor_router` resolves a selected source name
  against the map the controller passes in each tick, so a synthetic
  source routes exactly like a detected OGB zone.

### The merged active view (rig + feel + routing)

`get_active_profile_dict()` (name kept from the profile era) returns the
live `{device: merged config}` map: the wiring dicts with the shared
`"mix"` installed **by reference** and the active mode's routing keys
copied in as flat keys. Three guarantees are load-bearing:

* The top-level dict and every per-device dict are **never rebuilt** — a
  mode switch mutates them in place. The router's compiled-config cache
  keys on `id()`, so rebuilding the view per tick would recompile every
  motor at 60–90 Hz.
* `_install_active_routing()` **clears every routing key before writing
  the new mode's**: a mode with no filter on a motor must leave it
  unfiltered, not inherit the last mode's. It also always installs
  `osc_addresses` (empty if unset) as a stable dict object, because
  `_compile_motor_config` caches on `id(osc_addresses)` and a missing key
  would hand it a fresh `{}` every tick.
* Rig keys may be mutated in place (call `save_profiles()` afterwards, as
  before); `"mix"` and routing writes must go through
  `update_device_config()`, which routes each key to the store that owns
  it — feel to the shared layer, routing to the ACTIVE mode.

The dispatch scale is applied as one inline multiply at each backend's
final dispatch (the polling routers take a `get_master_scale` getter) —
zero added latency, and it carries the strength as well as Off's silence.
**The Buttplug path is the exception**: `motor_router` takes the same
getter and applies the scale inside each chain's Output stage, because
that chain's minimum-output floor has to sit *downstream* of the strength
— a floor applied before a dispatch multiply would be scaled straight
back into the toy's dead zone. So every value the Buttplug dispatch
receives is already the toy's. `update_device_target` therefore no longer
multiplies; it still hard-zeroes on Off so the panic switch never waits
for a recompute, and it still applies the per-toy mute, the simulator's
send-to-toy suppression and the OGP/Test floor. Any change that
alters output without changing router inputs (mode switch, strength,
Off, Sleep, test pulse) must call `ModesFacade._reset_output_caches()`
so every router's change-debounce re-dispatches on the next tick —
`ModesFacade._apply_output_change()` does that plus a direct
recalculate.

---

## Auxiliary modules

* `constants.py` — app-wide constants (`APP_NAME`, `INTIFACE_WS_URL`,
  `INTIFACE_ENGINE_DIRNAME`, `INTIFACE_ENGINE_STARTUP_GRACE_S`,
  default window geometry, OSC defaults).
* `intiface_connection.py` / `intiface_external.py` /
  `intiface_integrated.py` — the Buttplug-server connection providers and
  their selecting factory (see the haptic_engine entry above).
* `router_base.py` / `polling.py` / `zone_strength.py` — the shared base
  layer a level-routing backend builds on: the debounced `PollingRouter`
  poll loop over a daemon `PollingThread`, and the pure OGB / SPS
  zone→strength evaluator. See "The Stateless Routers" for which parts
  have a live caller in this edition.
* `utilities.py` — small helpers (`value_to_hex_color`,
  `toggle_windows_console`, `create_default_icon`).
* `update_checker.py` — sealed one-shot GitHub release check
  (`check_for_update`); never raises, never blocks startup. The
  controller spawns a daemon thread around it and routes the result
  through `thread_queue` as an `update_checked` event.
* `updater.py` — sealed self-update for the frozen single-exe build:
  streams the release asset, verifies it against the size and SHA-256
  GitHub reports, and hands the swap to a detached `.cmd` that waits for
  this process to exit before replacing the exe and relaunching it.
  Verification happens before anything touches the installed exe, so a
  failed update changes nothing. `is_self_updatable()` is False from a
  source checkout, where the UI falls back to the release link.
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
* `session_replay.py` — sealed JSONL parser that reconstructs a recorded
  session's full OGB contact stream (snapshot baselines + incremental
  deltas) into time-ordered frames. Driven by
  `controllers/replay_facade.py` (`ReplayFacade`), which locks live OSC
  at the `parameter_store` choke point (`set_input_locked`) and walks the
  frames on the GUI thread via `apply_replay_frame` + `force_recalculate`
  — so recorded motion runs through the *current* mode/chain settings for
  feel-tuning with no partner present.
* `version.py` — single source of truth for `__version__`.
* `settings/` — per-user settings managers, one JSON file per concern
  (see the Mode model section above).
* `tools/` — developer scripts, not loaded at runtime
  (`flatten_lovense_icons.py`, `generate_sim_icon.py`).

---

## Session logging

VR sessions can be recorded to disk for offline analysis and feel
tuning. `session_logger.py` is the sealed-box `SessionLogger` engine;
`controllers/sessions_facade.py` (`SessionsFacade`) owns its lifecycle
plus its `SessionSettingsManager` (`settings/sessions.py`) and adapts the
routing thread's broadcast callbacks into the engine's primitive `log_*`
calls. The Sessions sidebar view (`ui/views/sessions.py`) drives it. Full
design + on-disk format: `SESSION_LOGGING.md`.

---

## Developer tools / the test bench

`tools/testbench/` is a standalone program — strictly **never imported by the app**
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

Run with `tools/testbench/run_testbench.bat` (`python -m testbench` from
`tools/`); build with `tools/testbench/build_testbench.bat`. Isolated tests
live in `tools/testbench/tests/`
(run via `pytest testbench`; not part of the root `tests/` suite). See
`tools/testbench/README.md` for the Intiface / OGP setup.

---

## How to add a new haptic backend (the official pattern)

This edition ships only the Buttplug backend, but the seams it was built
against are all still here, so a backend is added by adding files rather
than by rewriting old ones.

1. **Engine** — write `myhardware_engine.py` with a sealed-box class:
   primitive-only public methods, all state private. Run your own loop /
   thread and talk to the outside world via the shared `thread_queue`
   and/or a `state_callback`. (The full edition shares a cold-path
   connect / reconnect / backoff supervisor in `engine_base.py` between
   its reconnecting backends; with one backend left there was nothing to
   share, so it is not in this tree.)
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
   `_setup_components()`, and gate it behind a `feature_myhardware` flag
   in `FEATURE_KEYS` + `_apply_feature_state`.
5. **Settings** — add a `MyHardwareSettingsManager` in `settings/`
   (subclass `JsonSettingsManager` from `settings/_base.py`: declare
   `DEFAULTS` + `FILE_PATH`, override `_post_load()` for nested backfills),
   register its path in `settings/_paths.py`, re-export it from
   `config_manager.py`, and instantiate it on `ModeManager`.
6. **UI** — add a view mixin under `ui/views/` and register it in
   `ui_components.py`'s `view_names` / `builders` / `nav_buttons`. It must
   call *only* the new facade methods. **Do not** import the engine or
   router from the UI.
7. **Latency** — hold the line (§ "Latency budget"): dispatch on the
   producing thread without queue hops, never `await` a device ack on the
   loop, poll / loop at ~60 Hz (or wake event-driven), and cap the
   *hardware* send rate only if the device needs it. A new backend that
   buffers or blocks on the hot path is a regression even if it "works".

Following this recipe means the four anti-tangling rules at the top of
this document and the latency budget all keep holding without anyone
having to re-audit them.
