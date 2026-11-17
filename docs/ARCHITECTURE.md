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
   — here, `HapticEngine`, `PiShockEngine`, `BHapticsEngine` and
   `OwoEngine` — is a sealed black box. Do not pass
   dictionaries between threads. The outside world communicates with each
   engine exclusively via its primitive-only facade and (where
   applicable) via the shared `thread_queue`.
   * `HapticEngine` exposes `update_target()`, `set_linear_config()`,
     `mark_connected()`, `set_connection_mode()`, `set_intiface_address()`,
     `get_intiface_link_info()`,
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
* **Rising edges:** the live UDP path also counts every bool
  False→True edge per key (`read_watched(keys)` returns the values and
  the counts for just those keys, under one lock). An OnEnter contact
  can be True for a single VRChat frame, so a poller that only reads the
  current value misses most of them; a router compares the counts
  against its last tick instead. OSCQuery snapshots never count.
* **Types:** the OSCQuery tree's type tag per parameter is kept
  (`get_param_types()`: Bool / Int / Float — as declared, else as the
  live value is) for the Avatar Remote page, whose controls must send the
  avatar's own type; `get_values(names)` reads a few values under one
  lock.
* **One key shape per zone:** `VFH/Zone/<cat>/...` is stored as
  `OGB/<cat>/...`, and SPS 3's renamed categories (VRCFury 1.1443.0,
  Nov 2026: `OGB/Socket/...`, `OGB/Plug/...`) as `OGB/Orf/...` /
  `OGB/Pen/...`, so zone lists, pickers and saved selections never see the
  difference; `sps3_zone.is_sps3_zone` tells the readers which contacts
  a zone has. An SPS 3 socket's plug length is derived here, on every
  packet (`sps3_zone.SocketPlugLengths`): an older plug's length can only
  be measured while it approaches, which a poller would miss. It is
  written back as `OGB/Orf/<id>/<DepthSelf|DepthOthers>_PlugLength`, so
  every reader -- and session replay -- just reads it.
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

This edition ships six hardware backends: Buttplug toys, and — each
behind a switch that is off by default — shockers (a PiShock or OpenShock
hub on USB), a bHaptics suit (straight over Bluetooth), an OWO suit
(through the My OWO app), haptic trackers (through SteamVR) and the PSVR2
headset's rumble (through PSVR2Toolkit). The full-featured build fans the same OSC
state out to eight of them side-by-side — SteamVR tracker haptics,
bHaptics, PiShock, DG-Lab Coyote, OWO, The Handy, PSVR2 — all following
the sealed-box contract below; the others are deliberately absent here
rather than shipped half-finished. What stays is the contract, so adding
one back is adding files (see "How to add a new haptic backend") — which
is how PiShock, the suits, the trackers and the PSVR2 headset came back.

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
      (the original behavior; owns no server lifecycle), on this PC or on
      another device on the network — a phone running Intiface Central
      with the toys paired to it. Where it is comes from the
      `intiface_address` app setting (`set_intiface_address()`): a typed
      `host:port`, or empty = found by itself, each attempt dialling the
      next of what mDNS shows (`intiface_discovery.py`, Intiface's own
      `_intiface_engine._tcp` announcement) and then 127.0.0.1, the one
      that last worked first. **Discovery only ever listens:** an Intiface
      server takes one TCP connection and stops when it isn't a Buttplug
      handshake (see `intiface_integrated.py`), so no port probe and no
      sweep of the network — the Buttplug client's connect is the only
      test of a guess. The mDNS finder runs only in this mode with no
      address typed, so the built-in engine's users never pay for it.
    * `intiface_integrated.py` — spawn and supervise a bundled
      `intiface-engine` (hidden console, a Windows Job Object or Linux
      parent-death signal so it dies with the app, websocket-readiness
      probe) so everything runs in one program. This is
      the default, gated by the `use_integrated_intiface` app setting
      (Settings → Intiface Engine). The engine binary is not in the repo;
      it lives in `src/intiface-engine/` and is bundled by `tools/build_OGP.bat`
      (Windows) and `tools/build_linux.sh` (Linux, which also builds it).
      Next to it, tracked, is the device list it is started with
      (`--device-config-file`): Buttplug's own list from the engine
      checkout without the Lovense match on the Nordic UART Service, which
      made the engine connect to every Bluetooth serial device in range.
      `tools/make_engine_device_config.py` writes it; regenerate it after
      every engine rebuild.

* **`pishock_engine.py` — shockers over USB (PiShock or OpenShock
  firmware).** The last gate before a
  shock reaches a person, so every send goes through it and its rules
  hold whatever the caller does: intensity and pulse length capped (the
  user's caps -- one for shocks, its own for vibrates -- never past 100 /
  15 s; each shocker may have its own of these three, `set_shocker_limits`,
  resolved against the hub-wide ones at every send), shock downgraded to
  vibrate until armed (remembered across launches since 2026-10-28:
  `armed` in `pishock_settings.json`, applied at init), a per-shocker rest after each
  pulse — except that a *stronger* pulse may take over one still
  running — and continuous holds limited to `max_hold_s` before a forced
  break (a let-go shorter than the break doesn't restart that clock).
  Every limit's range lives in one table, `pishock_limits.py`, which the
  engine, the settings store and the Shockers page all read. Each send is
  decided and written under the engine's lock, so a Stop or disarm can
  never land between deciding a pulse and sending it. Paused (the page's
  Stop all, Home's switch to Off, `set_paused`) refuses every send until
  Resume / On -- and unlike arming it is kept: `PiShockFacade` saves it
  as `enabled` in `pishock_settings.json` and pauses the engine again at
  the next launch. Only `pishock_stop_all` / `pishock_resume` change it,
  so the engine and the file never disagree. Each shocker has its own
  Shock, Vibrate and Beep switch (its card; `set_ops_off`, remembered as
  `shocker_ops_off`), enforced like a shocker's Off: an op switched off is
  refused on that shocker whoever sends it, and one running stops at once.
  An unarmed shock is a vibrate first, so with Vibrate off it is refused
  too; what a shock does with Shock off -- dropped, or sent as a vibrate --
  is the one constant `SHOCK_OFF_AS_VIBRATE` (dropped until Blise decides).
  `op_allowed` tells the rules router (a behaviour skips such a shocker)
  and the Friends status what gets through. Several sources may hold one
  shocker at once -- the rules router (`pishock_router.SOURCE`), each
  friend, Me and each browser on the web remote
  (`friends_receive.hold_source`), a friend's warning (`warning_source`)
  -- and the engine keeps each one's hold apart and plays the strongest:
  any shock over any vibrate over any beep whatever their levels (an
  unarmed shock counts as the vibrate it becomes), then the highest level
  of that kind, capped as it goes out. A
  source's `release` ends only its own hold (a weaker one still held takes
  over at once, no cut); one that stops topping its hold up stops counting
  after `HOLD_SOURCE_TTL_S` (one chunk), as it would alone. The longest
  hold, its forced break and the rest after a pulse stay per shocker for
  every source together; `end` / `end_all`, Stop, Off and a disarm stop
  them all -- and they hold for every source with nothing to pass (Blise's
  call, 2026-11-16: "it is for everything"): a stronger pulse taking over a
  running one can't stretch that run past one longest pulse from its start
  (`run_cap_ms` asks a shorter one: a friend's own longest pulse), no pulse
  goes in while the shocker rests after its longest hold, and a hold waits
  out a pulse and its rest (`hold_free_in`). `pulse` returns what went out
  (`Sent`: the op after arming, the level after the cap, the length after
  the longest pulse and the run's) or None, so the log can keep what was
  asked beside what was sent. A pulse taking over a running one ranks the
  kind first, like holds. With **Separate limits for friends** on, the
  timing (rest after a pulse, longest hold, forced break) is kept per group
  -- `GROUP_AVATAR` / `GROUP_FRIENDS`, an `_Account` each per shocker, passed
  as `group=` to `pulse` / `hold` -- with friends' own values
  (`set_separate_limits`); off, both accounts are written together, so they
  are one. Friends then also get their own max shock, max vibrate and
  longest pulse: `_caps_of(sid, group)` gives `GROUP_FRIENDS` the lower of
  the shocker's own and theirs (`limits_for(sid, group)` says it), so the
  engine caps a friend whatever the caller asked. What is on the wire and
  arming stay the shocker's.
  Holds go out as short overlapping chunks (`HOLD_CHUNK_MS`,
  refreshed every `HOLD_REFRESH_S`) with an `end` on release, so a dead
  app stops the shocker within one chunk; every indirect source (and
  OpenShock's firmware source) says a new operate for a shocker replaces
  the running one rather than queuing. A small supervisor thread keeps
  the link up while it is wanted (connect-on-start, or after Connect).
  `activity()` says what each shocker is doing -- its last pulse as it
  went out (op after arming, intensity after the caps, start and end) and
  the hold going out now -- and every write to the hub pokes
  `set_activity_callback`'s function (an `Event.set`, inside the lock):
  that is how ShockOSC's feedback (`shockosc_feedback.py`) wakes on change
  instead of polling.
  * `pishock_serial.py` is the transport: finds the hub by USB id
    (CH340 / CH9102 / CP210x, or Espressif's own USB) and confirms it with
    a handshake that asks both firmwares at once — PiShock's `info`, and
    OpenShock's `version` — then writes one line per operate
    (fire-and-forget, 100 ms write timeout), and a reader thread drains
    the hub's log and reports a vanished port. PiShock's info block
    carries the hub's Wi-Fi passwords, MAC and public IP; `safe_info()`
    keeps only the firmware and shocker list — never log the raw line.
  * `openshock_serial.py` is OpenShock's wire format: one
    `$rftransmit {model, id, type, intensity, durationMs}` line per send
    (`beep` → `sound`, `end` → `stop`). The `$` (no echo) is only
    understood from firmware 1.4.0 on — older firmware calls
    `$rftransmit` an unknown command — so the handshake asks a plain
    `version` and the prefix goes on only when the reported version
    allows it. The firmware replaces a running
    command for the same model + id (its RF task overwrites the
    sequence), so the hold chunks work unchanged. It keeps no shocker
    list over serial, so the page's list (model + transmitter id) is the
    list; a shocker taken off it is stopped before it is forgotten.
    OpenShock is only identified by a line only it prints (a `$SYS$|`
    reply or its boot banner), never by a bare `Version:` line. Its
    `$SYS$|Error|` replies (E-Stop pressed, say) reach the log, throttled.
    The firmware reads one line per 20 ms, so several shockers sent in
    one tick go out ~20 ms apart.

* **`bhaptics_engine.py` — the bHaptics suit over Bluetooth, no bHaptics
  Player.** Its own asyncio loop on a worker thread runs everything
  Bluetooth (`bleak`, behind `bhaptics_ble.py`'s radio / link interface so
  the engine never imports it — and never on the Qt GUI thread, where
  WinRT's apartment rules break bleak's callbacks). Scans by advertised
  name (`TactSuit*`, `Tactosy*`, `Tactal*`), connects without Windows
  pairing, keeps several devices at once, reads battery every minute. The
  router's `submit_frame(position, dots)` only stores the newest frame and
  wakes that device's writer: one write without response in flight per
  device, at most every `MIN_WRITE_GAP_S` (the first change after idle never
  waits; a burst collapses into its newest frame). A frame left non-zero
  with no submit for `FRAME_TTL_S` goes to zero — the job the Player's
  `durationMillis` used to do — and stop / release / Off / disconnect write
  all-zero twice. Paused (Home's switch to Off, `set_paused`) writes
  all-zero twice and drops every frame until it is switched on again; kept
  across restarts like the shockers' (`bhaptics.enabled` in
  `suits_settings.json`, set only by `bhaptics_stop_all` / `_resume`).
  A suit takes one connection, so `release()` lets it go
  (and stops reconnecting) for the Player or a game. The byte layout is
  `bhaptics_models.py` (pure), chosen per model from the advertised name:
  the TactSuit Pro and Air take 40 bytes on `6e400014`, one per motor,
  0..100, 32 motors in four groups of eight (the bHaptics Player's own
  frame, read off its logs); older vests take 20 bytes = 40 slots of 0..15
  on `6e40000a`, two per byte, even slot high; sleeves, head, hands, feet
  one byte per motor, 0..100. The engine opens each device on its model's
  characteristic. The avatar's five rows a side fold onto the Pro / Air's
  four (rows 2 and 3 share one). The protocol is unpublished (SenseShift's
  reverse engineering, checked against three other implementations, all
  GPL / LGPL — none of their code is in here); which side of each grid is
  the wearer's left is unverified until a model is checked on the suit
  (Suits page dots, or `tools/bhaptics_probe.py walk --interactive`).

* **`owo_engine.py` — the OWO suit, through the My OWO app.** EMS, so this
  is the last gate before current reaches a person, like the shocker
  engine: per-muscle and overall ceilings clamped to `ABSOLUTE_MAX` (100 %
  = the user's own calibrated max in My OWO), paused (the page's Stop all,
  Home's switch to Off -- kept across restarts as `owo.enabled`, set only by
  `owo_stop_all` / `owo_resume`) refuses every send, Off / feature off /
  VRChat quiet / exit send a stop twice, never the
  OGP/Test floor. Sensations are 0.3 s pulses re-sent every 0.25 s while a
  muscle is held — one datagram per muscle, its level as the intensity, as
  the vrc-owo-suit bridge does — woken early on a change, at most every
  50 ms. If OGP dies the suit stops within one pulse. `owo_link.py` speaks
  My OWO's UDP protocol natively (port 54020: `ping` → `okay`, AUTH →
  `pong`, then `<id>*SENSATION*…` / `*STOP`; the app says `OWO_Close` when
  it goes) — byte for byte what OWO's SDK sends, pinned by tests against a
  capture (`tools/owo_udp_capture.py`) and following OWO's MIT-licensed
  C++ SDK. No `OWO.dll`, no pythonnet.

* **`tracker_engine.py` — haptic trackers through SteamVR.** Joins a
  running SteamVR through OpenVR as a background app (never starts it;
  the binding loads only when `feature_trackers` is on). One thread does
  every OpenVR call: attaching (every `ATTACH_RETRY_S` while SteamVR is
  away), the device list every `SCAN_S` (GenericTracker devices only --
  not OGP's own toy devices, not Standable's virtual ones -- with battery
  and the role from `steamvr.vrsettings`), SteamVR's Quit (acknowledged),
  and the pulses: `TriggerHapticPulse` again every period while a level
  plays, the pulse length carrying the strength (`Timing`: Vive 50 every
  50 ms, Tundra up to 3999 µs every 4 ms, controllers up to 3999 µs every
  50 ms). The last gate: a level not re-sent for `LEVEL_TTL_S` plays
  nothing, each tracker's cap (`set_caps`, default 80 %) holds, paused
  refuses all. `set_levels` only stores and wakes the thread when a level
  rises, so a new touch pulses at once. `tracker_spots.py` (pure) holds
  Haptic Pancake's nine spots and parameter names and the role → spot map.

* **`psvr2_engine.py` — the PSVR2 headset's rumble motor.** Ported from
  the full edition, behind `feature_psvr2` (off by default, Windows only:
  `main.FEATURES_WINDOWS_ONLY`). It talks to the user's own PSVR2Toolkit
  through `psvr2_capi.py` (ctypes, the only file that touches the DLL,
  which is found through `%TEMP%\psvr2tk_capi_path.txt` and never
  bundled). The motor takes one byte, a frequency of 0-25 Hz (0 = off;
  the headset takes 1-9 as 10), so a level maps onto the user's band.
  `set_hmd_rumble` blocks until the driver acks (up to 5 s), so a
  latest-wins send thread owns every call, under a command cap that
  protects the headset's USB link and the toolkit's shared command ring.
  The register latches, so the engine is the last gate: a level not
  re-sent for `LEVEL_TTL_S` plays nothing, paused (Home's Off) holds 0,
  and stop / quit sends a last 0 that no in-flight send can overtake.
  The connect / reconnect loop is main's `engine_base.ReconnectingEngine`
  (the thread half only), and `_open` asks `get_driver_active()` because
  the toolkit's `init()` succeeds without SteamVR.

* **`remote_link.py` — the Friends link.** Other OGP users over the
  internet: QUIC between two PCs via iroh, dialled by public key (the ID a
  friend pastes), hole punching for a direct path and n0's free relays when
  that fails — nobody runs a server. A sealed engine like the others: its
  own asyncio loop on a worker thread, primitive methods in
  (`start`, `stop`, `pair_with`, `answer`, `set_contacts`, `set_nickname`,
  `push_cmd`, `send_event`, `drop`, `peers`, `forget_identity`), and
  `on_event(kind, peer, data)` out, called on its thread. Unlike the
  hardware engines it does hand dicts across threads — the messages in
  and out — so the rule here is: a dict is built fresh for the hand-over
  and nobody changes it afterwards. One connection's wire behaviour (what
  goes out when, keepalive, why it ended) is `remote_session.py`. A stop
  always stops, even before the link is online (`online()` waits for a
  home relay, which never answers without internet). One per process:
  the iroh bindings keep a single asyncio loop for every call — and one
  per PC: a second OGP window finds the first on the link pipe
  (`link_handoff`) and keeps Friends offline until it closes, since one ID
  online twice loses links. The identity key lives in `friends_key.bin`,
  never in a `.json`, so a settings backup restored on a second PC can't
  make it the same friend; **New ID** deletes it (`forget_identity`).
  * **Light on the network** (n0's relays are free; we stay a good
    guest). No polling of offline friends: an OGP that comes online dials
    each friend once, one per `DIAL_GAP_S`, and whoever comes online later
    dials us. Failed dials back off (`RETRY_S`, 10 s → then every 30 min; a
    pasted ID or invite `ASK_RETRY_S`, given up after `ASK_GIVE_UP` tries);
    a friend who closed OGP is next tried after 30 min, a dropped link is
    redialled at once. The retries of friends who weren't there share one
    budget, one per `BACKGROUND_GAP_S` (`_next_dial`: the fewest failed
    dials first), so the length of the list never adds to the traffic; the
    first round after coming online, a pasted ID and a dropped link don't
    wait for it. Nor does checking a friend now -- the Friends list's ↻ on
    an offline row and ↻ Check all (`check_now`): a click is its only
    trigger, it goes to the front of the dial queue (still `DIAL_GAP_S`
    apart), each friend at most once per `CHECK_GAP_S`, and the row says
    "checking…" until they say hello or the try gives up (`check_state`).
    A failed check leaves the background schedule as it was (no failure
    counted), only never sooner than `CHECK_GAP_S` away; one that stood in
    for a try due anyway counts as that try. A live link looks at `status_for` /
    `cmd_for` four times a second but sends only changes (plus `REPEATS`
    copies, the status every `STATE_REFRESH_S`) — except a `cmd` that
    drives toys, which goes every `SEND_S` because the receiver lets it go
    stale. Your toys' live levels change every tick while they move, so the
    status carries them only to a friend whose page shows your panel
    (`lw`, below) — to everyone else it stays unchanged and goes out every
    `STATE_REFRESH_S`. A ping only after `PING_S` of silence; `DEAD_S`
    without a word drops the link. Idle, a link sends a datagram every few
    seconds.
    The debug log (`debug=` → `ogp_debug.log` only) says how each link
    does: its path when it starts and every change (relay / direct / no
    working path), a quality line every `QUALITY_EVERY_S` and when it ends
    (round trip by QUIC and by OGP's own ping, datagrams in / out, QUIC's
    lost packets, why), the link loop running `LAG_WARN_S` late, building
    one friend's sends taking `SLOW_BUILD_S`; the facade adds the GUI
    tick's own hold-ups and a friend's drive going quiet (the Friends log
    says "dropped out … back after 1.3 s" instead of a stop / start pair).
    The Online switch (`friends.json` `online`) takes Friends off the
    network entirely.
  * **Pairing.** A pasted ID dials with `ask` in its `hello` and the other
    side is asked. An invite link (`friend_links.py`:
    `friend.html#<id>.<code>.<nick>` on the site → `ogp://friend/…`,
    registered by `link_scheme.py`, handed to a running OGP by
    `link_handoff.py`) carries a code in the `hello`; a live code
    (`once` / `day` / `week` / `forever`, settings `invites`) is accepted
    without asking. A clicked invite opens the Friends page; without a
    nickname (or with Friends off) a small window asks for one first
    (`prompt_friends_invite` → `accept_friends_invite`), and once linked
    the page shows that friend's panel. A browser on your **web remote**
    (`docs/remote.html`: a friend's panel -- `assets/remote.js` with
    `remote-toys.js`, `remote-shockers.js`, `remote-board.js` and the
    protocol port `remote-proto.js`, held against the Python by
    `tests/test_web_remote.py`; iroh compiled to WebAssembly from
    `tools/web_guest`, datagrams and the board's stream, always through a
    relay, since a browser can't send UDP) speaks the same protocol with
    `web` in its `hello`: your web
    remote's code (`friend_links.remote_link`, settings `web`) lets it in
    through `invite_ok` like an invite, any other is closed with
    `WEB_CLOSED` (`nolink`) and never asked about; `drop(peer, reason)`
    lets one go (`nolink`, or `kicked`). Unfriending closes the link with `removed`, and the
    other OGP drops you; an unfriended ID that redials by itself (no
    `ask`) is told `removed` again instead of becoming a request. A
    request nobody answers (or that is still open when OGP closes) ends
    `unanswered`, not `refused`: the asker asks again later.
  * `remote_protocol.py` is the wire format, pure and unit-tested: one JSON
    object per datagram. `st` (my toys, strength, what you may do, my
    shockers; the toys' live output only while you watch — your `lw`, sent
    while your page shows my panel, repeated like a status and stale after
    `WATCH_STALE_S`; an OGP older than protocol 2 gets it always; `pause`
    with `nh` when only friends in my instance may drive me and you aren't
    in it -- one bit, never where I am) and `cmd` (your levels for my toys — a state: a friend
    whose `cmd` stops arriving drives nothing after `DRIVE_STALE_S` — plus
    a strength change as `[seq, value]`, applied once per new seq) go when
    they change; `shk` (one shock) goes three times and is acted on once
    per id. **Several friends on one receiver** (Blise's ask, 2026-10-27):
    the receiver tells each friend who may drive its toys the nicknames
    of the *other* friends driving right now (`oth` → "+1 OTHER", names on
    hover; nothing while nobody else drives). **Sync with others is the
    receiver's choice alone** (Blise's call, 2026-11-17: one switch on its
    Friends page, `friends.json` `sync`, on by default, for every friend,
    the web remote and Me alike; a sender's own say is ignored). On,
    everyone driving shares one set of toy cards: every `cmd` carries
    `syn`, a version the sender's change raises past the newest it has
    seen (one without -- an older OGP whose own switch was off -- counts
    as saying the newest); the receiver plays only the newest change
    (`_sync_playing`: highest version, the first on a tie, then the peer
    id; "off" counts; a newest whose updates went stale hands over to the
    newest live one) and sends it back as `pnl` while two or more drive, to
    each that says a version, and each takes it as its own panel. Off,
    each drives on their own and the highest level wins; the order is
    kept all the while, so switching back on takes effect at once. Their
    panels hear the choice as one bit in `st` (`sep`, absent = synced, as
    an older receiver says) and show SYNCED / SEPARATE beside +1 OTHER. The version that counts is the one the receiver vouches for
    (`_sync_version`, 2026-11-17): an honest `syn` passes as it is, but it
    only gets past the newest with a real change -- cards that differ from
    the sender's last ones and from the shared panel's -- so a top-up,
    taking the shared panel or a value set again never takes it, and
    neither does a modified app's huge or rising number. Each sender's
    last version is remembered past a drop (a reconnect carries on); one
    never heard joins at the newest at most, unless no real change has
    landed since going online (a restart: as before). Versions stay
    comparable: a real change goes at most `SYNC_STEP` past the newest, and
    `pnl`'s `seq` is the highest anyone sent (at most `SYNC_SAY_AHEAD`
    past what is vouched for), never below the friend's own. Not ordered
    by arrival on purpose: every `cmd` carries the whole panel, and a
    friend whose cards haven't caught up would carry the old ones back
    over a newer change. Everything that arrives is cleaned before use, and a `cmd`
    never outgrows one datagram (`MAX_DATAGRAM`). An ID is 64 hex digits
    and an invite code 16 everywhere (`remote_protocol.valid_id` /
    `valid_code`).
  * Shocks from a friend go through `PiShockEngine` like every other
    shock — the receiver's caps, rest and arming all hold; a friend's
    strengths and lengths are parts of the receiver's own caps
    (`remote_protocol.shock_values`: shocks under the shock cap, vibrates
    under the vibrate cap). The friend's card is PiShock's own panel,
    laid out and named as PiShock's is (`ui/views/shocker_card.py`, its
    tiles, range slider and in-window pickers in `shocker_parts.py`):
    Tap (`pulse`), Remote and Continuous (the `cmd`'s `hold`, pumped into
    `hold` / `release` on the GUI tick and let go when it goes stale),
    Random (a min-max range, a fresh pick per shock, on the sender's side),
    a Small / Mid / Long warning — in Tap the `shk`'s `wms` (the receiver's
    GUI tick holds a vibrate that long, then sends the shock, checked
    again right then); in Remote and Continuous the sender's card holds a
    vibrate first and then the shock, so the receiver's hold rules apply
    to both — and STOP (`stp` → `end` for that shocker, a waiting warned
    shock dropped). PiShock's Party Mode (`ui/views/shock_party.py`, the
    facade's `party_*`) drives shockers picked one by one, of one friend
    or a whole group: Sync (all), Random (one per press) or Round Robin
    (one after the other); its lengths are real seconds, each friend's own
    longest pulse at most.
  * The card is one of two faces (`shocker_layout.py`, one app setting,
    PiShock by default; the shocker section's "Shocker buttons" switch):
    PiShock's panel above, or OpenShock's card (`ui/views/openshock_card.py`,
    its dials and Live control's pad in `openshock_parts.py`) -- Intensity
    and Duration, Sound / Vibrate / Shock as `pulse`, and Live control as
    the very `hold` Remote mode sends, on change. Both take the same
    callbacks and the same `set_caps` / `set_rules`, so the panel, Party
    Mode and the web remote (`remote-openshock.js`) don't care which; the
    same press sends the same message, and nothing about the receiver
    changes.
  * Every friend -- each group's members, Me, the web remote -- gets each
    shocker's own caps, switches and timing; there is no per-friend share
    (it was removed, Blise's call 2026-11-17: the Friends page is about
    friends, your limits live on the Shockers page). The friend's `st`
    carries each shocker's caps (`slim`, and `lim` for older copies), what
    may be sent on each (`sop`: its switches and arming) and what is
    switched off on its card (`soff`), so their panel greys what they
    can't do and says why. A test build's `fw` / `nc` (the share's
    "always warn first" and "taps only") are ignored either way; a copy
    from before `sop` reads none of it and the receiver refuses the rest.
  * The receiver never trusts the sender's panel (Blise's rule,
    2026-11-16: what a modified client sends is corrected to what OGP
    itself would send). Values: every reader cleans every field (a number
    that is no number -- NaN, an infinity, one too big for a float -- is
    none; a list that isn't one is empty), a warning is the vibration OGP's
    panels send (a beep only where Vibrate is off) of at least
    `remote_protocol.WARN_MIN_MS`, and a warning plays in full before
    its shock (it starts over once a pulse there and its rest are over;
    one during the rest after the longest hold is held back with its
    shock). Combinations: a friend's `pulse` carries `run_cap_ms` (the
    shocker's own longest pulse), so a chain of ever stronger pulses can't outlast it,
    and the engine minds every rest for every source. What was corrected
    is logged as asked, with what went out and why
    (`event_log.Event.correction`, muted under the entry). Rates
    (`inbound_rate.py`): a token bucket per sender for shocks, Stops that
    reach the hub, Avatar Remote sets, presses and height changes, and
    changes to the toy cards -- far above what OGP's own panels send,
    refused at the door and logged at most every few seconds; a letting-go
    is never rationed, a Stop past the budget still drops that sender's own
    warnings and holds. The toy cards are a state: a ``cmd`` costs one only
    when its levels, auto modes or Override differ from what last landed
    (OGP's link sends at most 64 changes a second, the web remote 94 at
    most measured; the budget is 150, 300 at once). Past it only its
    letting go lands (a toy stopped, an auto mode ended, Override off),
    counted on credit so it can't be used to change the cards faster, and
    never as a real change for Sync with others -- what was held back can't
    make anyone the newest. The rest lands with the sender's next cmd that
    finds the budget. Me isn't budgeted: its loop isn't throttled like the
    link, and only the avatar menu reaches it from outside. Each sender's
    shock ids are kept apart (one can't push another's out and get a copy
    taken as new), a friend's strength changes wait for the GUI one at a
    time (the newest wins), and a browser on the web remote that sends what
    only an OGP sends (`st`, `pnl`, `oth`, `pbd`, `pv`) is not listened to.
  * A friend's auto mode (`friend_patterns.py`: Sine, Square, Triangle,
    Saw, Random — the simulator's own `mixer.sample_pattern` — plus
    Heartbeat, Build-up and Oscillate, a sine around the friend's level)
    is three numbers in the `cmd`; the receiver plays it at the router's
    own rate (`friends_need_tick` keeps the routing tick running), so it
    costs the link nothing while it runs. On the sender's card
    (`ui/views/toy_card.py`; the shocker's is `shocker_card.py`, their
    shared parts `card_parts.py`) a toy is Off (0, the card only asks for
    a mode), Direct control (the slider) or an auto mode, with a small
    graph of what it sends and what their toy does. The panel stacks
    under the friends list in a half-width window, and Control mode
    shows only the picked friend or group, with big controls for VR.
    Pop out (`ui/views/friends_window.py`) moves that same panel, big,
    into a window of its own for a VR overlay to capture: one window that
    follows the pick, its size, place and Stay on top remembered, nothing
    in it that opens a popup, and closing it puts the panel back. It keeps
    the panel's refresh (and a friend's live levels and board) going while
    the main window is minimized, in the tray or on another page.
  * **Avatar boards** (the Avatar Remote page, shared with friends —
    `remote_params.py`, the wire format, pure and tested). Nothing goes
    out until a friend has your board open: your `st` only says that you
    share one (`prm`: its version, YOLO, `stop` while you paused all
    friends, and `a`, a short key of the worn avatar -- the board carries
    it too, so a friend's page shows "Getting their board…" rather than
    the old avatar's board after a change, and its `pw` asks again every
    `_ASK_AGAIN_S` until the new one is there). Their `pw` slot ("watching,
    I have version b") makes you send the board — too big for a datagram,
    so over a stream of its own (`RemoteLink.send_blob`, one message per
    uni stream, at most `MAX_BLOB`; only `pbd` is taken from a stream) —
    and again whenever it changes; then its values follow in `pv0`, `pv1`
    … slots, only the board's parameters (plus every settable one while
    their YOLO list is open), only on change and the usual refresh. Those
    slots come from `more_for(peer)`, sent by `send_state` like `st`
    (`remote_session.drives` / `refreshes` say which repeat). A set
    (`pst`) is an event sent a few times and applied once per id, never an
    older one; a hold button (`ph`) is a state the holder's OGP repeats
    every `SEND_S` while held, and the owner lets it go after
    `HOLD_STALE_S` without it — a dropped link can't leave a button
    pressed. A friend sees your *worn* avatar's active preset, never the
    one you are editing offline. Locks, YOLO, Pause all friends,
    their AVATAR switch and VRChat itself (nothing worn → no board)
    are all checked on the owner's side, from a snapshot
    (`_params_share`) the GUI thread swaps whole after each change; the
    set goes straight to VRChat from the link's thread, no queue hop.
    Your height rides along (the page's Height box, `avatar_height.py` /
    `controllers/height_facade.py`): the board carries the box (`ht`: your
    lowest and highest, `lk` locked, `no` while the world forbids
    scaling) only while its own switch is on, the first `pv` carries your
    height now (`h`), and a friend's `pht` (grow / now / reset, an event
    applied once per id like `pst`) is clamped to your range on your side
    -- through their AVATAR switch, Pause all, the box's lock and the
    world's say. It is not a held control: it stays where it was put.

* **Toys in SteamVR (display only, not a backend).** `controllers/
  steamvr_toys_facade.py` mirrors the connected toys — name, icon, battery
  — to a small OpenVR driver (`src/steamvr_toy_driver/`, C++) through
  `steamvr_toy_bridge.py`: newline JSON over `127.0.0.1:24855`, a full list
  on every change, fire-and-forget. On by default:
  `steamvr_toy_driver_installer.py` copies the driver to
  `%LOCALAPPDATA%\OscGoesPurrr\steamvr_driver` and adds it to
  `openvrpaths.vrpath` (leaving every other entry alone) only when SteamVR
  has run on the PC; switching off removes the entry again. Toys
  are TrackingReference devices with no valid pose, so nothing can bind
  them as trackers; a toy that goes away stays listed as disconnected
  until SteamVR restarts. Nothing here is on the haptics path.

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
  fuse (the toys' switch and timers from app settings, skipped for a toy
  whose own switch -- `antistuck.TOY_KEY` False in its wiring -- is off),
  and the per-motor `last_outputs` debouncer. Reads
  `mode_manager.get_active_profile_dict()` against `ParameterStore.snapshot()`
  each tick; only fires a queue event when the target value actually
  changes. It is driven from the UI thread via `force_recalculate`, not a
  poll thread.

* **`pishock_router.py` — shocker rules.** A ~100 Hz `PollingThread`
  that the controller also wakes the moment a watched parameter arrives
  (`OscFacade.on_osc_message` → `notify`), so a contact goes out on the
  same packet. Four rule kinds from the Shockers page: *continuous* (a
  float above a threshold holds the shocker, strength scaled by the
  value), *triggers* (a bool contact pulses once per edge or holds while
  on), *impacts* (OnEnter receivers with different Min Velocity; the
  strongest tier that fired picks the pulse), *zones* (Touch zones:
  several bool contacts, each a trigger of its own on its own shockers)
  and *pulls* (a PhysBone, read as `<param>_IsGrabbed` / `_Stretch`: its
  held op while grabbed, and a let-go with any stretch pulses once, the
  strength by the stretch at the let-go -- ShockOSC's PhysBone). A pulse
  trigger may want its contact held first (`hold_ms`): it fires on the
  tick the contact has stayed on that long, once per touch -- a check
  against the tick's clock, never a wait. A strength of 0 sends nothing,
  whatever the kind. A behaviour on a ShockOSC parameter (`shockosc.py`:
  `ShockOsc/<Group>...`) keeps its group: after the group's shock it rests
  the behaviour's own `rest_ms` (`shockosc_rests`), and the avatar's
  `<Group>_NextIntensity` / `_NextDuration` (read with the tick's one
  `read_watched`) may make its next action gentler, never stronger. The
  avatar's `_Config` settings never reach the router: they are the
  behaviours' own values, kept in step by `controllers/shockosc_sync.py`
  (below) -- except that the avatar's Paused stops a group like Stop:
  `stop_shockosc` (any thread, wakes the tick) ends a pulse of that group
  still playing at once (`engine.end` -- the engine can't tell one
  pulse's source from another's), and its behaviours, switched Off by
  the sync just before, hold nothing from that tick; other sources' holds
  go on. The engine caps every send again.
  Every rule drives the shockers dropped on it -- `shockers`, "all" or a
  list of ids; none dropped, it is still watched (the page shows what its
  contact sees) but drives nothing. Contacts are read as
  rising edges from the store's counters. Per shocker the strongest hold
  wins, pulses go before holds; Off, Stop, a lost link and a stale
  signal end everything once.

* **`suits_router.py` + `body_map.py` — both suits from one body**
  (and the haptic trackers: each placed tracker gets the strongest of the
  parameters its spot follows, through the same anti-stuck gate, Off and
  VRChat-quiet silence, re-sent every tick -- `tracker_spot_levels`).
  `body_map.read_body()` (pure) reads every suit input in one parameter
  snapshot — the official bHaptics package (`bOSC/v2[m]/<Pos>/<n>/self|others`),
  older bHapticsOSC keys, the OWO package (`owo_suit_<Muscle>`) and zone
  routes (an OGB / SPS zone or synthetic source onto a body region) —
  into one frame on the bHaptics layout; each OWO muscle is the strongest
  node in its patch. The two suits share contacts both ways unless their
  "follows" switches say otherwise. `SuitsRouter` is a ~60 Hz
  `PollingThread` the OSC thread also wakes (`notify`), re-submits the
  bHaptics frames every tick (which keeps the engine's timeout from
  expiring a held contact) and hands OWO its muscle levels; strength
  scales both, Off and a stale signal silence both once. Stuck contacts
  get the toys' rule (`motor_router`'s thresholds) with each kind's own
  switch and timers -- the bHaptics suit's, the OWO suit's and the
  trackers' anti-stuck (`antistuck.py`), each a block in its section of
  the settings snapshot `configure` hands over: `_unstick` reads the body
  once per suit through that suit's own gate (its own timer set), timing
  each node of each input layer and each OWO muscle on its own, before
  they're mixed, so a frozen input is cut (part-way) or fades (held at the
  top) without silencing a live one under it.
* **`psvr2_router.py` — one contact onto the PSVR2 headset.** Ported from
  the full edition: a raw contact receiver (not an OGB zone) shaped by
  threshold and gain (`compute_psvr2_level`, pure) into the engine's 0..1
  level. Here it is a ~60 Hz `PollingThread` like `SuitsRouter` rather
  than main's debounced `PollingRouter`, because the engine plays nothing
  it isn't sent again: the level goes out every tick, zeros too. The OSC
  thread wakes it for its contact (`notify`); strength scales it, Off and
  a stale signal send 0, its own anti-stuck (`suits_router.stuck_factor`
  with the headset's switch and timers from `psvr2_settings.json`,
  `antistuck.py`) cuts a frozen contact, and the VR menu's OGP/Test floor
  rides on top only while output isn't Off.

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
  SPS 3 zones answer the same filter names from their new contacts
  (`sps3_zone`).
* **`sps3_zone.py`** — reading VRCFury's SPS 3 sockets and plugs: depth
  from `DepthSelf` / `DepthOthers` and the plug's length, touch without
  `Close` gates, and each touch's own speed, which `motor_router` strikes
  into the chain's Speed channel (docs/MOTOR_SIGNAL_CHAIN.md § Speed
  channel). Written from VRCFury's parameter names -- OscGoesBrrr reads
  the same ones but is GPL-3 since v2.1.34, so nothing is taken from it.
  `vrchat_osc` sends `OGB/Enabled` next to `OGB_ENABLED` on the 5 s
  presence beat and right after an avatar loads: an SPS 3 avatar keeps
  its plug and socket touch receivers off until an app sets it.

### 5. The Face — `ui_components.py` + the `ui/` package

* **Role:** The "dumb" View Layer.
* **Mechanism:** Renders the interface using **PySide6 / Qt** (a global
  `GLOBAL_QSS` stylesheet plus widget objects). Vector icons are drawn
  at runtime via `QPainter` so the app does not depend on emoji-font
  availability.
  * **Look:** the 518 design system. `theme_tokens.py` is a verbatim
    copy of `_hub\design\theme_tokens.py` and the only place a colour
    is spelled out; `constants.py` resolves the persisted mode
    (`ui_mode`: `neon`, the default, or `midnight` — the user reads
    them as **Vibrant** and **Darker**; Qt-free so the router can
    import it) into the `COLOR_*` names the app was written against;
    `ui/theme.py` builds the stylesheet from those tokens and declares
    OGP's semantic roles (live signal = pink, running = cyan,
    warnings = amber, errors = red).
  * **Mode and colour picker** (Settings → Appearance, `ui_mode` and
    `ui_accent_hue`): `accent_shift.py` turns every green token — the
    mode's chrome, the palette's green, the section-bar fill — by one
    angle in OKLCH, so the turned colours keep the green's lightness
    and contrast; the identity hues and the semantic roles keep theirs
    — except one the accent lands too close to (within
    `IDENTITY_MIN_GAP`, 20°): `accent_shift.identity_hues` moves it
    out of the way, the closest to where the green was, a second to
    where it stands out most (pick Pink and the pink turns green). Each
    identity colour can also be set by hand (Appearance → Other
    colours, `ui_identity_hues`), which always wins; the colours in
    play are `constants.IDENTITY_HUES`. A moved colour is turned the
    same way and keeps its own lightness, as does its Neon section bar.
    The website's demo runs the same move (`ogp-accent.js`
    `identityHues`, checked against the Python by
    `tools/site_ports/check_accent.py`). A turned colour is always
    computed from a token, never typed. Both the colour and the mode apply **while the app runs,
    with no lag spike** — nothing restarts — in three parts:
    * `theme.set_accent_hue()` / `theme.set_mode()` move the module
      state at once: the tokens, and — through `retint.py`, which swaps
      one hex for another by value — every `COLOR_*` copy, class-level
      `QColor` and default argument in the colour-holding modules.
      Swapping by value is safe because the table behind it
      (`theme._table`: role → colour, for a mode at a turn and the
      colours set by hand) gives **every role a colour of its own, in
      both modes**, and an identity tone only ever to its own role —
      its own tone, or none once it moved (`accent_shift.unique_table`;
      the identity colours are roles too, `pink.0` … and `bar.blue.0` …). The
      chrome is the tokens character for character at no turn; where
      the tokens give two roles one colour — Midnight's accent is the
      palette's green, Neon's frame line is the section bar's frame
      tone — the secondary role (the palette's green, the bar) sits one
      blue step beside its token, in both modes, so a mode switch can
      tell them apart. What a mode decides beyond its tokens (filled or
      tinted section bars, a toy frame's tone) is looked up by name
      when a stylesheet is built or a frame painted — never copy it
      into a widget.
    * `ui/live_theme.py` sweeps what is already on screen. The
      app-level stylesheet is set once at launch and never again —
      re-styling the whole app takes seconds, and the Qt loop also
      hosts the routing tick. Instead the UI registers **sections**
      (the sidebar, each page, each Settings card, and on Home and the
      Toys page each toy's bar and each motor's block); a change gives a section the
      new stylesheet as its own and retints the colours its widgets
      copied. Sections on screen go first, top to bottom, as a wave;
      the rest follow one per event-loop turn once the picker rests.
    * **Sections never contain one another** — Qt re-styles everything
      under a widget whose stylesheet changes. So a container that
      sections sit in must not be styled by QSS: the window ground and
      the toy frames paint themselves (`ui.widgets.Canvas`, `ToyFrame`).
      A new page or card that should follow the picker has to be
      registered (`_style_root`); a new module that uses colours has to
      be added to `retint.COLOUR_MODULES` (a test fails otherwise).
      Dialogs are parented to `ui.dialog_parent`, a zero-size section,
      so they open in the colour in use.
  * `ui_components.py` is the main `OscGoesPurrrUI` class — the
    controller-facing facade and the live update sinks.
  * The `ui/` subpackage contains the bits factored out so the main
    class isn't the only home for view-layer code:
    * `ui/widgets.py` — `Card`, `ToggleSwitch`, `RainbowMeter`,
      `RainbowScrollBar`, `MainWindow`, `SliderProxy`,
      `ProgressProxy`, `Invoker`, `IdentityMark` (an identity icon as a
      widget; every one redraws on a colour change), scrollbar install.
    * `ui/icons.py` + `ui/lovense_icons.py` — `QPainter`-drawn vector
      icons (the Friends cards' wave and glyph icons too) and the
      Lovense-shape icon set. `identity_icon` is the one icon per thing,
      wherever it shows (sidebar, Friends list heads and panel sections,
      "What are you here for?"): toys the pink capsule, shockers the
      yellow bolt, Avatar Remote the remote in the accent green; anything
      else gets a blank of the same size so a column of labels lines up.
    * `ui/geometry.py` — Tk-style geometry string parsing (kept for
      compat with on-disk settings written by older versions).
    * `ui/layout_helpers.py`, `ui/text_helpers.py` — small helpers
      (`layout_helpers` also has `CardGrid` and `SideBySide`, the layouts
      that follow the window's width).
    * `ui/stats_charts.py` — the Statistics page's custom-painted charts
      (session sparkline, weekday x hour heatmap, month calendar, the
      pre-timeline span charts) and the painting helpers they share;
      `ui/session_timeline.py` — one session's timeline; `ui/stats_widgets.py`
      — the page's session row, number tile and name field. Fed primitive
      data by the view; they read nothing.
    * `ui/theme_friends.py` — the Friends page's stylesheet rules, built
      with the rest by `theme.build_qss`; `ui/theme_params.py` the same
      for the Avatar Remote page's categories and cards (each category in
      its palette hue, so the colour picker turns them too; the Suits page
      borrows them in the orange), and `ui/theme_suits.py` the Suits
      page's own: its tags, chips and switches in bHaptics orange / OWO purple.
    * `ui/views/` — one module per sidebar view (`home`, `toys`,
      `pishock`, `suits`, `friends`, `params`, `sessions`, `statistics`,
      `diagnostics`, `settings`) — the bigger ones split into parts the view's mixin
      inherits: `pishock_rules` (the behaviour cards), `pishock_shockosc`
      (the ShockOSC card: while the worn avatar has ShockOSC's parameters,
      a row per group with what it becomes and whom it drives, and one
      Set up button) with `pishock_cards` (a
      card per shocker, the shared timing -- each with its ceilings boxed
      under a "Limits" heading, labelled "Up to ...", and the Test buttons,
      the only things that send, set apart under a line of their own -- and
      the drop zones shockers are dragged onto); `body_view` (the Suits page's painted body: a cat girl's
      front and back from `src/Images/suits` -- line art tinted in the accent,
      made by `tools/make_suit_figure.py` -- with every bHaptics dot placed in
      the drawing's own pixels and OWO's muscle patches around them) with
      `suits_cards` (the inspector's part, muscle and tracker cards that
      open with a line from her, the chips, the contact check's pills);
      `friends_list`, `friends_panel`, `friends_window` (the panel popped
      out into a window of its own), `friends_account` (a friend's VRChat
      account: the list's In your VRChat instance chips, dragged onto a
      row, the row's second line, the panel's field and its picker folded
      out in the panel -- chip boxes that size themselves to their rows),
      `friends_shockers` (a friend's or a group's shockers, PiShock's or
      OpenShock's buttons),
      `friends_board` (a friend's avatar board), `friends_vrc_tip`,
      `friends_update` (a friend's OGP is newer: the window and the banner);
      `param_cards` (the board's category boxes and control cards, with
      drag and drop — also drawn read-only for a friend's board) and
      `param_dialogs` (a control's Edit dialog); `statistics_people`, `statistics_session` —
      plus `device_frame` — each toy's card on the Toys page and its row
      on Home — `sps_sources` (a fold on the Toys page), `click_bars` (the
      fold bars) and `dashboard` —
      named for the page it used to build — which now holds the sidebar's
      control block (modes, the total output strength bar, Off / Sleep)
      and the Toys page's tuning-tools bar. Each builds its view and calls *only*
      controller facade methods. The app opens on Home, the overview for
      everything (Blise's call, 2026-11-14): a row per device with its
      quick switches, and a click on a row opens that device's own page.
      A toy's row is its bar alone -- connection, what drives it, the
      Touch / Penetration chips, battery, meters, Mute, Test -- and opens
      its card on the **Toys** page (`toys`, right after Home in the
      sidebar), which holds the detail: the same bar over the toy's
      signal chains -- the card open from the start, each motor's chains
      folded to one bar each (2026-11-16) -- Scan now, the toy server line,
      SPS Sources and the tuning tools. Both bars are built by
      `device_frame._build_toy_bar`, and every live update (connection,
      battery, meters, chips, Mute) reaches both (`_toy_bars`). A bar's
      widgets sit on up to three lines, arranged by the room the bar has
      (`_fit_toy_bar`): one line while it fits -- the chips as two rows,
      Touch above Penetration -- then the zones and chips under the name,
      then the battery and meters on a line of their own too. Every widget
      stays the bar's child (the lines are layouts inside its layout), the
      room each arrangement needs never depends on the one shown, and the
      bar's minimum width is 1 so the page never scrolls sideways; Home's
      device rows (`HomeDeviceRow._fit`) and the "Tell VRChat" / "Mirror to
      VRChat" rows (`_SwitchNameRow`) wrap the same way. The shocker
      hub, the suits and the headset have a row each in Home's list
      (`home_devices`): `device_frame._reorder_device_frames` is the one
      place that orders both lists -- on Home connected toys, the rows that
      are switched on and connected, the other toys, then the other rows
      under small dividers; on the Toys page the cards alone -- asking
      Home for its rows (`_toy_list_rows`) and touching a layout only
      when its order changed. The shocker row's Arm shocks, Share with
      friends and On / Off are the Shockers page's own switches
      (`shocker_switches`: their words, the hover paragraph on how they
      stack, and `ArmSwitch`, which asks "Arm shocks? Yes / No" in its own
      place -- never a popup, which a VR overlay wouldn't show -- where
      `ARM_ASKS_FROM` says (both places), falls back to off, and says
      Shocks armed / Shocks not armed beside it in the theme's red, from
      the setting): each flip goes
      to the facade, which posts `pishock_state`, and both places redraw
      from `get_pishock_status()` -- neither keeps a copy.
    * `ui/motor_signal_chain.py` — the per-motor signal-chain widget
      (Input → Depth/Speed/Punch → Combine → Wake → Envelope →
      Zero cut → Output; Wake merges the old Gate + Arming into one
      two-mode stage, Envelope pairs Smoothing + Texture as two halves),
      embedded in each toy card on the Toys page (see
      `MOTOR_SIGNAL_CHAIN.md`).
    * `ui/trace_graph.py` — custom-painted scrolling time-series plot used
      by the chain mini-graphs and the Tuning tools' signal graph.
    * `ui/fold_strip.py` — the chain's visual language (collapsible fold
      cards joined by painted arrows, purple→pink activity rings)
      extracted into reusable `FoldCard` / `FoldStrip` widgets.
    * `ui/osc_variable_picker.py` — modal picker listing live avatar
      parameters from `parameter_store`, with search + manual entry.
      Shared by the toy cards' motors, SPS Sources contacts and the
      Shockers behaviours. Its filter chips hide groups of well-known
      parameters -- VRChat's own, GoGo Loco, face tracking, VRCFury's
      internals and toggles, physics assets, PhysBone states, OGP's own,
      SPS -- defined in the pure `param_filters.py` (which also holds
      `BUILTINS` for `remote_params.settable`). The chips are one app
      setting (`picker_hidden_groups`) for every picker; a caller passes
      `mapped=` (never hidden), `settings=` (the controller), `keep=`
      (groups it always shows -- the Shockers' PhysBone states) and
      `first=` (groups listed before everything else under their own
      heading -- the Shockers' ShockOSC, `ShockOsc/...`, which the other
      pickers hide by default).
    * `ui/help_mode.py` — help mode ("Show me around": F1, the status
      bar's button, a Help card's Show me; `ui/views/help.py` wires it
      in). It explains the page on screen on the page itself: the page's
      steps from `ui/page_steps.py` on a strip above it, each step's
      control lit and numbered, and whatever the pointer rests on lit
      with its hover explanation's title and first sentence. Clicks do
      nothing while it is on (the sidebar's pages excepted), it reads
      nothing but the widgets' tooltips and the steps, and it only runs
      while on. `ui/page_steps.py` is shared with the VRChat gallery
      (`tools/make_vrc_group_images.py`), which stops when a step's
      control is gone.
    * `ui/tour.py` — the guided tour, on help mode's drawing (the dim,
      ring and `draw_bubble`): one step at a time from
      `ui/tour_steps.py` (switch your toy on, it lights up on Home, open
      it, Input, Select Zones, a zone, the chips, Test, total strength,
      the avatar menu, then a short branch per feature picked; where a
      page step says the same, the tour step *is* it, `from_page`). A step
      moves on when the real thing happens -- the window answers each
      step's `waits` (`ui/views/tour.py` `TourMixin.tour_waiter`, read
      from the window and the facade, never written) -- or on the strip's
      button (Next / Skip this step / Continue without a toy / Finish). The
      lit control (with the widgets explained alongside it) takes its
      click, the strip, scroll bars and the sidebar's pages too; every
      other click on the window is swallowed, and the tour itself never
      changes a setting. A step on another page first rings that page's
      sidebar entry. 60 ms looks, only while on; help mode and the tour
      take turns. When it starts by itself is
      `controllers/tour_facade.py` (below).
    * `ui/tooltips.py` — hover explanations, the app's in-place
      help: `explain(target, title, text)` puts a themed, word-wrapped
      tooltip on a widget, every widget in a layout, or a container whose
      plain children fall back to it through Qt's parent lookup. Every
      control carries one; the signal chain sets one per stage on the
      stage card (`_STAGE_TIPS`), so each knob inside inherits it. Tests
      open every stage and fail on a control without one.
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
  The same holds for the whole window: a page timer is connected through
  `ui.frame_clock.when_on_screen`, which skips it while the window is
  minimized or hidden to the tray, and the page catches up when the
  window comes back (`_on_window_restored`, the arrival refresh).
* **Rule: what moves with the signal repaints per frame, not per
  sample.** Meters and graphs get values at the router's rate; they store
  them at once and ask `ui.frame_clock.request(widget)` for the repaint:
  60 fps while OGP is focused, 20 fps while it isn't (never zero -- OGP
  is watched in VR overlays while VRChat has the focus), none while the
  window is minimized or in the tray. A live widget that fills its whole
  box sets `WA_OpaquePaintEvent` so its containers don't repaint under
  it; the toy bars' mini meters paint their rounded corners in the ground
  behind them (`RainbowMeter.set_ground`, the toy bar's hover tint or the
  toy frame's fill). Measured 2026-11-05, Home with two toys playing at
  90 Hz: ~1,540 paint events a second before, ~115 focused / ~50
  unfocused after; minimized or in the tray, none.
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
    * `controllers/pishock_facade.py` — `PiShockFacade` (owns the
      shocker settings, engine and router; `feature_pishock` starts and
      stops them; connect / arm / stop / test, the OpenShock shocker
      list and the rule CRUD the Shockers page calls), with
      `controllers/shockosc_facade.py` — `ShockOscFacade`, its base: the
      ShockOSC card's `get_shockosc_setup` / `shockosc_set_up` (the worn
      avatar's groups from VRChat's own list of its parameters; a second
      setup adds nothing; its behaviours start with `new_rule_values`,
      what a new behaviour of the kind starts with) and the feedback
      sender's groups -- those with behaviours and those the avatar shows,
      only the parameters it has -- re-sent after an avatar change or an
      OSC reconnect; and `controllers/shockosc_sync.py` —
      `ShockOscSyncMixin`, its base: ShockOSC's `_Config` settings and the
      behaviours' values as one value each, both ways (Blise's call,
      2026-11-16). `shockosc.address` says which avatar parameter a value
      goes with -- `_Config/_All/*` is the default every group follows, a
      group's own only when the avatar has it. A `_Config` value from
      VRChat (`OscFacade.on_osc_message` → `_shockosc_on_osc`, a queue put)
      or a friend's set (`ParamsFacade._params_send` →
      `_shockosc_heard_set`) changes every behaviour going with it, saved
      and redrawn (`"shockosc_rules"` on the queue); a page edit
      (`set_pishock_rule` → `_shockosc_rule_edited`) or an undo moves its
      partners and sends the parameter. OGP first after an avatar load
      (`_ogp_mode_guard_until`, as for OGP's own menu), recent sends
      ignored as echoes, the global Paused a kill switch; Paused going on
      also asks the router to stop at once what those behaviours run
    * `controllers/suits_facade.py` — `SuitsFacade` (owns the suits
      settings, both engines and the shared router; `feature_bhaptics` and
      `feature_owo` each start and stop their engine, the router runs while
      either is on; connect / let go / stop / test and the zone-route CRUD
      the Suits page calls)
    * `controllers/friends_facade.py` — `FriendsFacade`, in seven files:
      this one (lifecycle, the page, contacts, invites, groups, the log)
      inheriting `friends_control.py` (you driving friends),
      `friends_menu.py` (the avatar menu's Friends part),
      `friends_receive.py` (friends driving you), `friends_params.py`
      (a friend's avatar board: watching it, setting and holding its
      controls), `friends_me.py` (you, always first on your own list: a Me
      row, peer `ME`, whose panel is what a friend who may do everything
      sees and works on your own toys / shockers / avatar -- `MeLink` wraps
      the `RemoteLink` and hands what goes to ME straight back in,
      `_me_tick` feeds the status, drive and board values on the GUI tick;
      every friend rule holds, and ME is never named to real friends) and
      `friends_versions.py` (each hello carries the app's `VERSION`, the
      link reports it as a `version` event once a link and again only on a
      change; a friend's newer one opens `show_friend_update_warning` once
      a launch -- Update now when the launch update check found a release
      this copy can install that reaches theirs, else the release page --
      and puts `behind` in the status for the Friends banner; an older one,
      or none, is `version: "older"` on their entry, the row's OLD tag)
      and `friends_web.py` (the web remote: a browser that comes with your
      web remote's code is a web guest -- never a friend or a contact, so
      nobody dials it -- under one Web remote row, `WEB`; its share of
      `_friend_perms` is the row's Toys / Shockers / Avatar switches (toys
      on, the others off until ticked), its messages take a friend's own
      path, and its `oth` carries a count, never names; Copy / New link /
      On / the switches / Kick / Remove, `ui/views/friends_web_panel.py`)
      and `friends_vrchat.py` (each friend linked to their VRChat account,
      yours alone: the `usr_` id and the name it had in the friend's
      settings entry, never sent over the link or to the web remote; one
      account per friend; who's in your instance from the `vrchat_log`
      watcher PeopleFacade owns, behind the page's own switch
      `friends_vrc_log`; `friend_in_instance(peer)` -- `vrchat_log.in_instance`
      on your own log with VRChat's OSC up, unlinked = no -- is what "only
      friends in my instance" builds on; *Import from VRCX* through
      `vrcx_friends.py`, the list kept in memory for the run; the VRChat
      name shown is People statistics' for that account, else the link's,
      and People statistics tags a linked account with it the first time)
      and `friends_instance.py` (**Only friends in my instance**,
      `friends.json` `instance_only`, off by default: a friend whose linked
      account isn't in your instance by your own log -- unlinked, the log
      off or VRChat closed all count as not here -- is refused like Pause:
      `_not_here`, a frozenset swapped whole, is the one thing the receive
      path reads (`_friend_cmd_in`, `_shock_blocked`, the router's
      `get_friend_drive_mode`, `ParamsFacade._params_blocked(peer)`); it is
      recomputed on the GUI thread (`_instance_refresh`: every friends
      tick, which catches the log's snapshot and VRChat closing, and at
      once for a switch, a link or a contact) and, for a browser joining,
      under `_web_lock` on the link's thread. Whoever becomes not here has
      their drive dropped, warnings and holds let go and held avatar
      buttons released, logged with `op="not-here"` and `held`; a refused
      sender is said in the log once per `TELL_AGAIN_S` per thing tried.
      Me is exempt; a friend's `anywhere` exempts them; a web guest is
      blocked unless the web entry's `anyway`. Their `st` says what Pause
      says plus `nh` -- never your instance. Switching it on switches on
      `friends_vrc_log`; switching that off leaves it on and nobody is
      here),
      with what they share in
      `friends_common.py`. The list's column icons
      set a permission for every friend at once (`set_friend_permission_all`:
      off while any has it, then on). All together: the Friends
      page (nickname, the Online switch, contacts, per-friend toys /
      shockers boxes, groups of friends, the selection, Pause all friends,
      invite links, unfriending, New ID, the log; owns the `RemoteLink`
      and the `LinkListener`; `feature_friends`, on by default, but the
      link only goes online with a nickname). `OGP_FRIENDS_DEMO=1` adds
      `friends_demo.py`'s example friends to the page, never to the
      network or the router. Inbound: a
      friend's level becomes `get_friend_drive(device)`, which the router
      reads; their strength goes through `set_strength(source="friend")`;
      their shocks through the shocker engine. Outbound: the page's sliders
      and the VRChat menu's `OGP/Friend/*` (handled on the OSC thread, no
      queue hop) become `cmd`/`shk` — the menu's for whatever is picked on
      the page: one friend, or every member of a group. A group may hold
      you (`ME`, the list's Me row, dragged in like a friend), and that is
      how the menu drives you and a friend at once: you go through the Me
      row's local loop (`friends_me.py`), so every friend rule holds for
      you too -- Pause all, your shocker page's switches, arming and caps.
      (No separate *Both of us* path any more.) Whether the avatar
      wears the menu (`OGP/Strength` / `OGP/Friend/Level` in the
      parameter store) is `get_avatar_menu()`, shown at the page's foot
    * `controllers/height_facade.py` — `HeightMixin`, mixed into
      `ParamsFacade`: the Height box. VRChat's `/avatar/eyeheight` (and the
      world's `eyeheightscalingallowed` / `min` / `max`) reach it through
      one set lookup in `osc_facade.on_osc_message` -- never the parameter
      path -- into `avatar_height.HeightControl`, which owns the height, your
      own height (what Reset goes back to: the newest VRChat said that no
      write of ours caused), a glide and the send rate. A write goes
      straight to VRChat from whichever thread asked (page, friend's link,
      the menu's Radial on the OSC thread) unless one went out under
      0.1 s ago; the params tick sends what was held back and steps Grow.
      After an avatar change it asks VRChat's OSCQuery for the current
      values (`vrchat_osc.query_value`), as VRChat only sends them on a
      change.
    * `controllers/params_menu.py` — the avatar menu's Avatar Remote
      slots (`OGP/Remote/Toggle1-7`, `Radial1-7`), mixed into
      `ParamsFacade`: a slot is taken by a control or a category of the
      board (param_board `slots`, per preset); the OSC thread sends a
      slot's controls to VRChat from `_slot_map`, a snapshot the GUI
      thread swaps whole, and the params tick puts the menu where the
      board is (never VRChat's echo of what OGP set, never under your
      hand, OGP's values back after an avatar load).
    * `controllers/params_facade.py` — `ParamsFacade` (the Avatar Remote
      page, VRC Parameter Relay's board inside OGP: owns the
      `param_board.BoardBook` and its file, follows the worn avatar and
      its parameter types, sends a control's value to VRChat; edits come
      in through `params_edit(op, ...)` — a BoardBook method from a fixed
      list — and every change rebuilds what friends see; the owner's half
      of a friend's board: `_params_prm_for`, `_params_more_for`,
      `_params_on_watch` / `_on_set` / `_on_holds` on the link's thread;
      Import from VRC Parameter Relay; `feature_params`, off by default)
    * `controllers/stats_facade.py` — `StatsFacade` (usage statistics:
      owns the `StatsTracker`, the `StatsHistory` and the `StatsPeople`
      tag store, samples usage at 1 Hz off the UI heartbeat and keeps the
      last minute's thrusts for the live pace, exposes
      `get_stats_snapshot()`, `get_stats_sessions()`,
      `get_stats_session_detail()` (with the session's tags),
      `get_stats_patterns()`, `get_stats_month()`,
      `get_stats_fun_facts()` / `reset_stats()`). Its base,
      `controllers/stats_events_facade.py` — `StatsEventsMixin`, owns the
      `StatsEvents` store: the log's `on_add` listener only queues an
      entry (on whatever thread logs), `_stats_events_tick` counts the
      queue on the 1 Hz statistics tick and samples the suits' and
      trackers' on-time; `get_stats_from_whom(span)`, `get_stats_worn()`,
      the session page's `"shocks"` (counts + the timeline's marks, read
      from the log with `EventLog.window`), and the names switch
      (`get/set_stats_friend_names`, `forget_stats_friend_names`)
    * `controllers/people_facade.py` — `PeopleFacade` (who sessions were
      with: `tag_session()`, `tag_session_stretch()`,
      `remove_session_tag()`, `get_people_table()`, and the opt-in
      VRChat-log tagging — a `vrchat_log.LogWatcher` thread it starts
      and stops, read once a second off the heartbeat by `_people_tick()`;
      one watcher for two switches, People's and the Friends page's
      `friends_vrc_log`: it runs while either is on, and tags only while
      People's is)
    * `controllers/thrust_params_facade.py` — `ThrustParamsFacade` (the
      opt-in thrust counters: lifetime total, session count and live
      pace as avatar Int parameters, plain and digit by digit; only
      changes go out, everything again on link-up and avatar change)
    * `controllers/toy_sounds_facade.py` — `ToySoundsFacade` (the
      optional connect / disconnect chimes: diffs the engine's
      connected-toy list after `connection_status`, `devices_found` and
      `device_removed`, and chimes once per real change; plus the
      volume and the Settings page's Test)
    * `controllers/away_facade.py` — `AwayFacade` (Off while you're
      away, Settings → Safety, on by default: while VRChat's `AFK`,
      GoGo Loco's AFK button -- it sets `VRCEmote` to 101 -- or a picked
      parameter is on, `ModeManager.held_off` holds the same Off as
      `OGP/Off` without touching that switch; the sources are
      `away_off.py`. The OSC thread looks each address up in
      `_away_watch` and queues one `away_check` for a watched one (or the
      store's reload notice); the GUI thread reads the values from the
      store and starts or ends the hold, the status bar's amber pill
      saying why -- `show_away_hold`. VRChat closing lets go
      (`_away_vrchat_gone`, from `osc_status` False -- the OSCQuery mDNS
      record removed or two failed HTTP health checks -- and the
      Disconnect button; never the 10 s quiet monitor, which fires while
      you stand still AFK); after that only values VRChat sends anew, or
      the store's next live reload, count (`_away_fresh`). Nothing on a
      routing path)
    * `controllers/history_facade.py` — `HistoryFacade` (Ctrl+Z / Ctrl+Y,
      `settings_history.py`: `_history_init` makes the one history and
      makes it the active one first thing in `__init__`, before any store
      loads; `_history_hooks`, once every store exists and before the UI,
      gives each its re-apply hook -- the engine's caps and arming, the
      router's rules, friends' permissions, the toy cards rebuilt -- so an
      undo takes effect like the change by hand. The UI's surface:
      `history_set_input`, `history_boundary`, `history_undo` /
      `history_redo` (with the UI's way to ask and to replay a control),
      `history_undo_action`, `history_status`)
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
  (the `router_poll_rate_hz` setting, 90 Hz by default, gated by
  `_needs_recalculation`) sleeps (`ROUTER_IDLE_MS`, 10 Hz) while nothing
  moves -- no fresh OSC, every output at zero -- and the packet that ends
  the quiet wakes it at once (`main._wake_routing`, also called by
  friends' messages and every `force_recalculate`), so sleeping adds no
  latency, only fewer wakeups. It publishes "asleep" before its last look
  at the flag, so a packet landing in between is never missed.

  While awake it keeps a **steady beat**, not a tick per packet: the
  chain's speed and punch detectors divide each change by the time since
  the last tick, so ticks fired by unrelated packets (VRChat sends every
  parameter) would make a stroke read up to ~1.6× faster and change how
  every tuned chain feels. The beat comes from `precise_alarm.PreciseAlarm`
  -- a high-resolution waitable timer on a thread of its own, handing each
  beat to the UI thread -- never a QTimer: on Windows Qt keeps only 16
  timers to the millisecond per process and OGP runs more, so the routing
  tick's QTimer fell back to the 15.6 ms clock step and "90 Hz" ticked at
  64 Hz. Python's timed waits (`Event.wait`, `Condition.wait`, asyncio's
  timeouts) round to the same step; `time.sleep` and the waitable timer
  don't.

  It dispatches **directly** to the engine via
  `force_recalculate(dispatch_direct=True)` — it does **not** route hot
  updates through `thread_queue` (that queue is the UI pump, drained only
  every `QUEUE_POLL_RATE_MS` = 50 ms, and carries status / device events
  *only*). The engine is **event-driven**: `update_target` wakes its loop
  (`call_soon_threadsafe` on an `asyncio.Event`, once per pass however many
  targets change), and a finished send wakes it when a newer value waited
  behind it, so a new level leaves within a millisecond of the router
  setting it. Between changes it only times out -- `HAPTIC_POLL_RATE`
  while a linear toy's physics moves or a value is held back (a stop must
  go out even if nothing changes again), `HAPTIC_IDLE_RATE` otherwise. It
  sends **fire-and-forget** (never awaits Intiface's ack), bounded by a
  per-feature cap (`HAPTIC_MAX_SEND_HZ`, ~60 Hz) so a real BLE toy isn't
  flooded. Measured 2026-11-13 in the real app (fake Lovense on a private
  Intiface engine, no Bluetooth): packet → command at the toy was ≈15 ms
  median / 30 ms p95 while both stages polled, almost all of it two waits
  stretched to the 15.6 ms step; with the event-driven engine and the
  precise beat it is ≈3 ms median / ≈11 ms p95 (router → toy ≈0.8 ms; a
  packet while the router is awake waits for its next beat, one that ends
  a quiet stretch wakes it at once). The router's own maths is ≈0.1 ms a
  tick.
  The per-feature send decisions (change gate, in-flight guard, caps,
  linear delta gate, duration sizing) live in the pure
  `send_gate.FeatureSendGate` so the invariants are unit-testable without
  a connection.
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
* **A friend's level** (their OGP → `remote_link` → `FriendsFacade` →
  `motor_router` → `haptic_engine`). Datagrams, fire-and-forget, a change
  goes out at once (≤60 Hz per friend), and while any level is up the
  `cmd` repeats every 250 ms, which repairs a lost one. On arrival the facade swaps its drive table (no lock
  on the router's side) and sets `_needs_recalculation`, so the next
  routing tick (≤16 ms) picks it up — no queue hop. In the router it joins
  the motor's output at the end (`_apply_friend_drive`, fed by
  `get_friend_drive_mode` → `(level, override)`): the higher of the two
  wins — or, while a friend drives that toy with Override, theirs
  replaces it — scaled by the global strength (0 under Off) and remapped
  into the motor's output band, so a toy's own maximum still holds. ~3 ms
  one-way between two OGPs on one PC, plus the internet's round trip.
* **Shockers** (`pishock_router` → `pishock_engine` → USB serial). The
  router wakes on the OSC receive thread's packet for a watched key (no
  poll wait) and dispatches on its own thread; the engine writes one
  line to the port, fire-and-forget, no ack waited for (PiShock sends
  none; OpenShock's reply is only read for the log). OpenShock firmware
  polls its serial input every 20 ms, one line per poll.
  Holds are re-sent as chunks, change-gated to at most one per
  `HOLD_CHANGE_GAP_S` except the first after idle. ShockOSC adds nothing
  to this path: its `_Next...` are read with the tick's one
  `read_watched`, a touch's hold time is a clock check, its settings'
  sync runs on the GUI thread (a queue put from the OSC thread), and the
  feedback runs on its own thread, woken by an `Event.set` from the
  engine.

* **Suits** (`suits_router` → `bhaptics_engine` → Bluetooth, and →
  `owo_engine` → UDP → My OWO). The router wakes on the OSC packet for any
  key the body reads and dispatches on its own thread; `submit_frame` and
  `set_active` only store the newest value and wake the engine (one
  `call_soon_threadsafe` hop into the Bluetooth loop — bleak's own). Writes
  go without response; OWO datagrams are fire-and-forget, then My OWO's own
  Bluetooth hop.
* **PSVR2** (`psvr2_router` → `psvr2_engine` → PSVR2Toolkit's driver). The
  router wakes on its contact's packet and `set_level` only stores the
  value (waking the send thread when it changes). The one blocking call,
  `set_hmd_rumble` (the driver's ack, then a USB control transfer), lives
  on the engine's own latest-wins send thread under a command cap the
  hardware needs; the first change after a quiet gap goes at once.

Every other backend in the full edition (Coyote, Handy) obeys the same
shape: poll the store
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
  contact 2x2 (`motor_N[_cK]_touch_self / touch_others / pen_self /
  pen_others`, `contact_filters.py`; the old Touch / Penetration and Self /
  Others pairs are turned into it once at load, see
  MOTOR_SIGNAL_CHAIN.md § "Who a chain hears"), param-out — so a new per-motor tuning key
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
  `held_off` is the same silence held by something other than the user's
  switch ("Off while you're away", `controllers/away_facade.py`): it
  zeroes `get_master_scale()` and makes the facade's `is_output_off()`
  true -- what every output path obeys -- while `output_off`, the switch
  (`is_off_switch_on()`, the sidebar button, `OGP/Off`), is never touched,
  so letting go restores exactly the state before.
  `sleep_active` is read by `motor_router` each tick and swaps every
  chain's Wake stage for `MotorRouter.SLEEP_WAKE_OVERRIDE` (stroke
  counter: three strokes inside six seconds); nothing is written to the
  stored chain, so switching it off restores the user's real wake
  settings exactly. Buttplug-only — no other backend has a Wake stage.
  `sleeping_toys` is the same Sleep for one toy (its bar's Sleep chip):
  a set of toy names, session-only too, read by the router through
  `get_toy_sleep(name)`; a toy sleeps while either is on.
* **Anti-stuck per kind** (`antistuck.py`, 2026-11-17) — no one global
  switch: the toys keep `toy_antistuck_*` in app settings (the Toys page)
  plus each toy's own on / off as a rig key in its wiring; the bHaptics
  suit, the OWO suit and the trackers have a block each in
  `suits_settings.json`, the PSVR2 one in `psvr2_settings.json`. A file
  without its block starts as a copy of the toys' values once
  (`seed_antistuck`, from the facades' init), so an update changes
  nothing. Every store's `history_asks` asks before an undo switches one
  off or makes it wait longer.
* **`avatar_last_mode`** — per-avatar memory of the last active mode;
  applied on avatar change only when the `avatar_modes_enabled` app
  setting is on.
* **`app_settings`** (`AppSettingsManager`) — UI-level toggles
  (`auto_refresh`, `auto_connect`, `bind_all_interfaces`, window
  geometry, console visibility, speed-tuning, feature flags…).
* **`known_devices`** (`KnownDevicesRegistry`) — global registry of
  every toy ever seen; the wiring store (and each mode's feel presets)
  are seeded from it.
* **`pishock_settings`** (`PiShockSettingsManager`, owned by
  `PiShockFacade` like the session settings, file `pishock_settings.json`)
  — USB port, connect-on-start, the safety limits, the OpenShock
  shocker list (model + transmitter id, unique ids), your names for the
  hub's shockers, "Share with friends" (`friends_may_use`) and
  On / Off (`enabled`) -- either off, friends don't see the shockers at
  all (`allow_shock` false in their status) -- Arm shocks (`armed`,
  remembered across launches since 2026-10-28) and the rule lists
  (Touch zones, Contact -- with its `hold_ms` -- Continuous, Impact and
  Pull; Contact, Continuous and Pull keep a strength of 0 and a `rest_ms`
  for ShockOSC's CooldownTime; `NEW_RULES` / `new_rule_values` are what a
  new one starts with, the page's and the ShockOSC setup's alike;
  `add_rules` adds the setup's in one save, `set_rules` saves the sync's
  changes to several at once).
  Those three switches show on Home's shocker row and the Shockers page
  alike, both read from here. Global, not per mode: the rules name avatar
  parameters. Every value is cleaned on the way in and out; `set_limit`
  takes only the limits' own keys.
* **`suits_settings`** (`SuitsSettingsManager`, owned by `SuitsFacade`,
  file `suits_settings.json` — its own name: the full edition keeps
  separate bHaptics / OWO files in the same folder) — bHaptics On / Off,
  per-position on/strength, who it reacts to, whether it follows OWO's
  contacts, connect-on-start (on); OWO's On / Off, address, game id,
  frequency, per-muscle top, overall ceiling (starts at 60 %), whether it
  follows bHaptics' contacts, connect-on-start (off); the shared zone
  routes. Every value cleaned on the way in and out — it feeds the EMS
  gate. On / Off has its own setters (`set_bhaptics_enabled` /
  `set_owo_enabled`), never the generic option setters.
* **`param_boards`** (`ParamBoardsSettingsManager`, owned by
  `ParamsFacade`, file `param_boards.json`) — the Avatar Remote page: every
  avatar's profile (VRC Parameter Relay's shape), the last one open and
  YOLO (a `stop` from before 2026-10-27 is dropped on load). It is the store `param_board.BoardBook` loads from and saves
  to; a profile only ever worn (no name of its own, nothing on a board)
  is pruned past the `SCRATCH_KEEP` most recent. Cleaned on the way in.
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

* `shockosc.py` — ShockOSC's avatar parameter names (OpenShock's VRChat
  app, AGPL-3.0: the names are an interface, none of its code is here),
  split the way ShockOSC splits them; what the one-click setup makes of
  each group (`planned_rules`, `missing_rules`); `_NextIntensity` /
  `_NextDuration`, only ever less (`read_next` → `NextValues`); and which
  `_Config` parameter each behaviour value is kept in step with
  (`address`, `fields_of`) with the units turned both ways (`to_avatar`,
  `from_avatar`). Pure.
* `shockosc_feedback.py` — ShockOSC's feedback parameters (`_Active`,
  `_Cooldown`, `_CooldownPercentage`, `_DurationRemaining`, `_Intensity`,
  per group and as `_Any`) from the engine's `activity()`: only shocks
  count, as in ShockOSC. Its thread sleeps until the engine pokes it,
  ticks every 0.1 s while a shock runs or rests, and sends changes only.
* `constants.py` — app-wide constants (`APP_NAME`, `INTIFACE_WS_URL`,
  `INTIFACE_ENGINE_DIRNAME`, `INTIFACE_ENGINE_STARTUP_GRACE_S`,
  default window geometry, OSC defaults).
* `intiface_connection.py` / `intiface_external.py` /
  `intiface_integrated.py` — the Buttplug-server connection providers and
  their selecting factory (see the haptic_engine entry above).
  `intiface_discovery.py` is the external provider's mDNS finder for an
  Intiface Central elsewhere on the network (a zeroconf ServiceBrowser on
  `_intiface_engine._tcp`; listen-only, never a probe).
* `router_base.py` / `polling.py` / `zone_strength.py` — the shared base
  layer a level-routing backend builds on: the debounced `PollingRouter`
  poll loop over a daemon `PollingThread`, and the pure OGB / SPS
  zone→strength evaluator. See "The Stateless Routers" for which parts
  have a live caller in this edition.
* `avatar_height.py` — the Height box's pure part: VRChat's height
  addresses, the settings cleaned (your lowest / highest inside the safe
  0.1-100 m, VRChat's menu range 0.2-5 m out of the box, Grow's speed),
  the slider's log scale, a glide's steps (by a factor: doubling every
  `double_s`), and `HeightControl` (thread-safe; it never sends -- each
  call returns the height to write now). `param_filters.NOT_PARAMETERS`
  keeps its keys -- which the OSC layer stores like any address -- off the
  parameter lists and a friend's YOLO list.
* `param_board.py` — the Avatar Remote page's board model, VRC Parameter
  Relay's AppCore without OSC or sharing: per-avatar profiles (name,
  last parameter list, presets), categories, controls (toggle, hold
  button, slider, stepper; an Int as a toggle / button with its own ON /
  OFF values), what a control sends (`send_value`), YOLO's ranges
  (`any_value`), controls following a parameter whose type changed, and
  the Relay's file shape (`relay_profile` imports its `avatars/*.json`).
  Pure; `BoardBook` takes a store with `load` / `save` / `list_profiles`
  — `settings/param_boards.py`, one `param_boards.json` so the settings
  backups carry the boards (avatars only ever worn, never named and with
  nothing on a board are kept for the `SCRATCH_KEEP` most recent).
* `settings_history.py` — Ctrl+Z / Ctrl+Y: one history of the last five
  settings changes for the whole app, recorded where the stores SAVE,
  never in a widget. Every `settings/_base.py` manager tracks itself once
  loaded and reports each save (`settings_history.track` / `.saved`);
  `AppSettingsManager`, `ModeManager`, `SessionSettingsManager` and
  `SpsSourceManager` do the same by hand. The history diffs each save
  against the store's last saved copy (dicts key by key, lists of id'd
  dicts by id, equal-length lists of dicts place by place), so a new
  setting -- or a new store -- needs nothing to be undoable. A store may
  say what is no setting (`history_ignore`: window places, folds, the page
  or preset you're on, secrets, a friend's own nickname...), what an undo
  must ask first (`history_asks`), and a setting's name
  (`history_describe`). Saves within `COALESCE_S` are one step; only saves
  right after the user's own input count (the UI's gate), so a friend, the
  avatar menu or a timer is never a step. Undo writes the old values back
  through the store and its save, then the owning facade's hook puts them
  into effect (`controllers/history_facade.py`). A change that knows its
  own way back is an `action` (the Avatar Remote's drag-remove:
  `take_control` / `put_back`). Pure; `ui/history_keys.py` is the keys
  (one app filter, like the wheel guard; a text field keeps its own
  Ctrl+Z), the input tracker, replaying the step's own control first, and
  the asking -- Arm shocks' own question in the switch's place, a Yes /
  No on the window's line for the rest. Safety questions are the stores':
  arming, a shocker / an action / the hub / sharing back on, a limit
  loosened, a friend or the web remote allowed more, ⚡ YOLO, a category
  unlocked, OWO back on or a ceiling raised, PSVR2's command cap raised.
* `utilities.py` — small helpers (`value_to_hex_color`,
  `toggle_windows_console`, `create_default_icon`).
* `update_checker.py` — sealed one-shot GitHub release check
  (`check_for_update`); never raises, never blocks startup. The
  controller spawns a daemon thread around it and routes the result
  through `thread_queue` as an `update_checked` event.
* `whats_new.py` — the "What's new" notes (one entry per release, newest
  first: a title, a sentence or two, and optionally a place in the app)
  and the rule for when they show: once, at the first launch after an
  update (`whats_new_seen_version` in the app settings: the newest notes
  the running build carries), never on a first install. Every release
  newer than the marker shows, one page each with Back / Next, so an
  update that skips releases loses none of their news; a patch release
  with no entry of its own opens nothing.
  `controllers/whats_new_facade.py` is the launch hook;
  `ui/views/whats_new.py` draws the window and makes the "Take me there"
  jumps (`PLACES`: the page, and the card to scroll to and light up).
  Add a release's entry in the same change as its features. A test
  fails when an entry names a place that does not exist, and
  `release.bat` refuses to publish while the newest notes sit under a
  version later than `VERSION` (`tools/check_whats_new.py`) — they would
  never be shown.
* `interests.py` — "What are you here for?": one choice per public
  feature switch, under *what you have* and *what you want*, and the rule
  for an answer (only the switches that differ flip). Asked once at
  launch — a new install, or one from before the question
  (`interests_asked` in the app settings) — and "What's new" and an
  update offer wait for it to close; Settings → Features → *Choose what
  you use…* opens it again. `controllers/interests_facade.py` is the
  launch hook, `ui/views/interests.py` the window. A test fails on a
  public feature switch the question leaves out.
* `controllers/tour_facade.py` — when the guided tour (`ui/tour.py`)
  happens by itself: once (`tour_offered` in the app settings). A new
  install (`created_fresh`) starts it as "What are you here for?" closes
  (the window holds it while the question is open); an older install is
  offered it on the update that brings it, as a bar over the page (Take
  the tour / No thanks), never a window. After that only Help's and
  Getting started's *Take the tour* start it.
* `updater.py` — sealed self-update for the frozen single-exe build:
  streams the release asset, verifies it against the size and SHA-256
  GitHub reports, and hands the swap to a detached `.cmd` that waits for
  this process to exit before replacing the exe and relaunching it.
  On Linux the asset is the AppImage, swapped in place (Linux lets a
  running file be replaced) before the app restarts itself through
  `$APPIMAGE`.
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
* `stats_history.py` — sealed companion to the tracker that keeps the
  detail behind the Statistics charts: one timeline per session in
  10-second buckets (`stats_sessions/<id>.json`; the running one is
  `<id>.live.json`, rewritten about once a minute, and a `.live` file
  left by a killed run is closed at the next launch and handed to the
  tracker as a recovered session) plus active time and thrusts per
  local clock hour (`stats_hours.json`). Deliberately separate from
  `stats.json`: the full edition shares the AppData folder and rewrites
  that file with only the keys it knows. Its pure helpers (`dense`,
  `analyse`, `weekday_hour`, `month_days`, `fun_facts`) turn the stored
  data into what `ui/stats_charts.py` draws.
* `stats_gate.py` — the statistics' noise gate (`ActivityGate`). With a
  toy running everything counts; without one, a stroke only counts with
  a zone in contact (the thrust counter also fires on avatars nobody is
  touching), and contact and strokes are held back until they make a
  scene (20 thrusts with no pause over 10 s, or 60 s of contact within
  any 3 minutes), then count from 30 s before it until half an hour of
  quiet; anything less is dropped and never starts a session.
  `StatsFacade` runs every 1 Hz sample through it before the tracker
  and the history see it, and applies it after the fact
  (`stats_history.regate`) to timelines recorded under an older
  `GATE_VERSION`, discounting the tracker's totals to match and
  dropping totals-only sessions that couldn't have passed it.
* `stats_events.py` — sealed store of what Statistics counts from the
  log (`stats_events.json`, apart from `stats.json` for the same reason
  as the history), lifetime and per session (by the timeline's id): the
  shocks, vibrates and beeps that reached your shockers — how many, the
  strongest, the seconds they ran — in all, per shocker and per source
  (your avatar's behaviours by name, you through your menu or Party
  Mode, each friend, each web remote guest), what was held back,
  friends' drive time and Avatar Remote sets, and the suits' and
  trackers' on-time. Only numbers, never a second record of the events:
  the session timeline's marks are read from the log while it has them
  (`marks`). A hold counts when it starts and adds its seconds when it
  ends — past the hub's longest hold in on / rest cycles
  (`held_on_time`). With the names switch off a friend counts as "A
  friend" and a web guest as "Web remote"; `forget_names` folds the
  names kept. A shock alone still files its session: the facade
  `touch`es the running timeline's bucket (`stats_history.touch`, no
  active time).
* `stats_people.py` — sealed store of who each session was with
  (`stats_people.json`, apart from `stats.json` for the same reason as
  the history): tags for the whole session or for stretches of it, each
  with one or more names, plus the pure `credit()` that gives every
  person the active time, thrusts and peak pace inside their tags (two
  people on one stretch both get all of it). Finished sessions' credit
  is cached and dropped on any tag edit or re-gate; the People table is
  summed from the caches plus the running session.
* `vrchat_log.py` — who is in the VRChat instance, read from VRChat's
  own `output_log_*.txt` (join / leave / room lines). `InstanceTracker`
  is the pure parser; `LogWatcher` follows the newest log on a daemon
  thread and publishes an immutable snapshot, so a log of hundreds of MB
  is never read on the GUI thread (the routing tick's thread). Only runs
  while the People card's opt-in switch or the Friends page's (Read
  VRChat's log) is on. `in_instance(snap, user_id, vrchat_up)` is the
  pure "is this account in your instance" check, `here_ids(snap,
  vrchat_up)` the same for a whole friend list in one pass.
* `vrcx_friends.py` — your VRChat friends from VRCX's database
  (`%APPDATA%\VRCX\VRCX.sqlite3`, the `usr<id>_friend_log_current`
  tables: `user_id`, `display_name`), read-only through an SQLite
  `mode=ro` URI, only when *Import from VRCX* is clicked; a lock VRCX
  holds is "busy" after half a second, never a wait. Nothing it reads is
  written anywhere.
* `thrust_params.py` — pure helpers behind the thrust counters: the
  parameter names (`OGP/Thrusts/Total|Session|PerMin` plus `/D1`… digit
  Ints, since an avatar Int stops at 255) and `PaceWindow`, the thrusts
  of the last 60 s by each sample's own epoch (the activity gate
  releases held-back samples late).
* `stats_backfill.py` — pure, one-time estimate of the hours before the
  hourly history existed, so the charts don't start empty: each saved
  `stats.json` session's active time and thrusts are spread over the
  hours its toys were connected (read from `ogp_debug.log` and its
  rotations), and what the lifetime totals hold beyond those over the
  latest earlier runs with a toy connected. `StatsFacade` runs it once at
  launch; `StatsHistory` stores it apart from the measured hours (its
  presence marks it done, a reset leaves it empty) and the page labels
  estimated hours and days as such. It also keeps when each toy was
  connected during the saved sessions, which their list rows and pages
  draw in place of a timeline.
* `session_replay.py` — sealed JSONL parser that reconstructs a recorded
  session's full OGB contact stream (snapshot baselines + incremental
  deltas) into time-ordered frames. Driven by
  `controllers/replay_facade.py` (`ReplayFacade`), which locks live OSC
  at the `parameter_store` choke point (`set_input_locked`) and walks the
  frames on the GUI thread via `apply_replay_frame` + `force_recalculate`
  — so recorded motion runs through the *current* mode/chain settings for
  feel-tuning with no partner present.
* `toy_sounds.py` — the connect (low → high) and disconnect (high → low)
  chimes, synthesized in memory as WAVs at the user's 0–100 % volume
  (squared to amplitude, so the slider feels even) and played through
  Windows' `PlaySound` — on Linux through `pw-play` / `paplay` / `aplay` —
  on a short-lived daemon thread, so no caller waits on audio. Stdlib
  only. Driven by `controllers/toy_sounds_facade.py`; never on a routing
  path.
* `version.py` — single source of truth for `__version__`.
* `settings/` — per-user settings managers, one JSON file per concern
  (see the Mode model section above).
* `tools/` — developer scripts, not loaded at runtime
  (`flatten_lovense_icons.py`, `generate_sim_icon.py`).

### Linux

The Linux release is an AppImage (`OscGoesPurrr-Linux-x86_64.AppImage`)
that GitHub Actions builds for every release (`.github/workflows/linux.yml`
→ `tools/build_linux.sh`, on Ubuntu 22.04 so it runs on any newer
distro) and attaches next to the exe. Inside is a PyInstaller `--onedir`
build plus the built-in engine, compiled from the Buttplug commit the
notices name with `tools/intiface-engine-Cargo.lock`. The few places the
code differs:

* **Settings** live in `~/.config/OscGoesPurrr` (`settings/_paths.py`);
  help texts write the folder as `constants.SETTINGS_DIR_DISPLAY`.
* **System programs** — the file browser, the sound player, the engine —
  start with `utilities.system_env()`, which takes the bundle's
  `LD_LIBRARY_PATH` and Qt paths back out; a frozen build's environment
  would otherwise make them load our libraries instead of their own.
* **Restarts** go through `$APPIMAGE` (`utilities.running_appimage()`):
  the mount `sys.executable` lives in vanishes when the app exits.
* **Tray**: Qt's, via the UI facade (`show_tray_icon` …), because
  pystray's Linux backends need GTK bindings or an X11 tray. A desktop
  without a tray gets the window minimized, never hidden.
* **Windows only**: the SteamVR toy driver (a DLL; its toggle says so),
  the console toggle, and the PSVR2 headset (PSVR2Toolkit is Windows only:
  `feature_psvr2` is in `main.FEATURES_WINDOWS_ONLY`, so elsewhere it is
  off and missing from Settings → Features and "What are you here for?").
* **Bluetooth for the bHaptics suit**: bleak talks to BlueZ over D-Bus
  (`dbus-fast`, pure Python — nothing extra is bundled), so the host needs
  bluetoothd running, which it is on most desktops.

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

## The log (who did what)

`event_log.py` is the record and the store behind the Friends page's log
card and the Log page — and the record Statistics counts
(`stats_events.py`) rather than keep its own. One `Event` per thing that
happened: when, **who** (a
friend's or web remote guest's ID, Me, `g:<id>` for a group, `avatar` for
your own avatar's shocker behaviours, `you` on the page) with their name
right then and a `role`, **what** (`kind`: toys / shock / params / link /
settings; `op`; `dir` — `in` to you, `out` by you to them; `level`, `ms`,
the shockers `on`; for a hold, `asked` is what it plays — an unarmed
shock holds as a vibrate), `held`, why it was held back, and **`via`**,
what it came through where this PC knows it: your avatar's behaviour by
name (`pishock_router.behaviour_name`: its kind plus its zone or label,
"Touch zones · Neck"), or `menu` / `party` for what you sent from your
avatar menu or Party Mode (`friends_common.came_through`, a per-thread
marker the menu and Party Mode set; a warned shock keeps it). A friend's
own menu or Party Mode isn't said over the link, so theirs is "". The
line people read is `text`, written from it: callers of
`friends_facade._friends_note` pass who and what as keywords, with
`{who}` where the name goes.

* **Hot paths never wait for the disk.** `EventLog.add` (the link's
  thread, the PiShock router's, the GUI thread) appends under a lock and
  returns. The log's own writer thread (`start`) reads the history once,
  appends what came in every `FLUSH_S` and drops days past `KEEP_DAYS`. A
  keyed entry within `COALESCE_S` of the one before replaces it (a slider
  drag is one entry), and the writer holds the newest entry back while a
  drag may still change it, so a drag lands as one line.
* **Files:** `EVENT_LOG_DIR` (`event_log/` in the settings folder), one
  `YYYY-MM-DD.jsonl` per local day, 30 days. Never a `.json`: settings
  backups copy every top-level `.json`, and the log is no setting.
* `controllers/log_facade.py` (`LogFacade`) owns it: `_event_log_init`
  before the shockers (their router reports to it) and Friends,
  `_event_log_shutdown` at quit after both; the Log page's queries and
  Clear; `_log_avatar_shock`, which the PiShock router calls after its
  sends with what your avatar's rules fired (a pulse, a hold starting, a
  hold ending with its strongest level and length). A host without
  `LogFacade` (the Friends tests) gets a memory-only log.
* Views: `ui/views/log_people.py` (the "by person" rows, both pages),
  `ui/views/log_page.py`. It stays on this PC — nothing here is ever sent
  to a friend or the web remote.

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

The seams every backend was built against are all still here, so a
backend is added by adding files rather than by rewriting old ones (the
shockers and the suits came back this way).

1. **Engine** — write `myhardware_engine.py` with a sealed-box class:
   primitive-only public methods, all state private. Run your own loop /
   thread and talk to the outside world via the shared `thread_queue`
   and/or a `state_callback`. (The full edition shares a cold-path
   connect / reconnect / backoff supervisor in `engine_base.py` between
   its reconnecting backends. Here only the PSVR2 engine uses it -- its
   thread half came with that port; the shockers, the suits and the
   trackers keep their own small supervisors.)
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
