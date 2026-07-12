# OscGoesPurrr 🐾

A multi-backend haptic feedback router for VRChat. Reads your avatar's
OSC parameters and translates them into smooth output for Bluetooth
toys, SteamVR trackers, bHaptics suits, OWO suits, e-stim units
(PiShock, DG-Lab Coyote), The Handy, and the SteamVR overlay.

## ✨ Features

* **Buttplug.io toys via Intiface Central.** Auto-discovery, multi-zone
  routing, per-motor speed-blend tuning, linear-actuator support
  (Lovense Solace Pro, Gravity, OSR2…).
* **Drive a VRChat parameter as output.** Any motor in Device Routing can
  *also* mirror its computed value (0.0–1.0) back to VRChat as an avatar
  parameter, so the same contact that drives a toy can drive an avatar
  visual — a glow, a blendshape, a fill meter. Works even with no toy
  connected (it rides the same routing tick); enter the bare parameter
  name and the `/avatar/parameters/` prefix is added for you.
* **SteamVR tracker haptics.** Dispatches OSC values to any SteamVR
  device that supports `TriggerHapticPulse` (Tundra trackers, Vive
  trackers, etc.) with per-tracker patterns and a battery broadcaster
  that publishes tracker battery back to VRChat.
* **bHaptics suits / vests.** Translates v1 `bHapticsOSC` parameters
  (HerpDerpinstine schema) into dot-mode frames for the bHaptics
  Player. Antistuck timer, per-position enable, optional
  `bHaptics_Connected` bool back to VRChat.
* **PiShock.** Fire shock / vibrate / beep events from avatar contacts,
  over USB serial or the pishock.com cloud API. Rising-edge triggering
  with per-zone cooldowns and a global rate backstop, and **hard safety
  caps enforced in the engine** — settings can only ever lower the
  intensity / duration / interval limits, never raise them.
* **DG-Lab Coyote 3.0.** Drives a Coyote e-stim unit directly over
  Bluetooth (no phone app — just a BLE adapter), with independent A/B
  channel routing and strength ceilings enforced on the device itself.
* **OWO suits.** Maps avatar contacts onto OWO's ten muscle-group
  sensations for full-torso EMS feedback, via the OWO app over Wi-Fi.
  (Optional: needs `pythonnet` plus a vendored `OWO.dll` — see
  [`owo-sdk/`](owo-sdk/).)
* **The Handy (Handy 2 / Pro 2).** Drives the stroker through the
  official handyfeeling.com API (v3): contact strength sets the stroke
  speed (HAMP) or steers the slider position directly (HDSP), with a
  device-enforced stroke zone, a speed ceiling, and a command-rate cap
  sized to the cloud API's request budget. (A Handy also still works as
  a regular Buttplug.io toy over Bluetooth via Intiface.)
* **SteamVR Toy Driver.** Optional virtual-device bridge that makes
  your connected toys and configured bHaptics positions show up as
  trackers in SteamVR's device strip, complete with battery icons.
* **Auto-discovery.** VRChat is found via mDNS — no IP / port typing.
* **Shadow-state router.** Downloads the avatar's OSCQuery parameter
  list at connect time for flawless, debounced routing.
* **Multi-zone.** Bind a single motor to multiple OGB zones (Head,
  Tail, etc.) with simple checkbox menus.
* **Six haptic modes.** 🔇 Off · 🔈 Low · 🔉 Medium · 🔊 High ·
  🌙 Sleep · 🃏 Custom — each mode is a full *feel* preset (per-motor
  signal-chain settings + a master intensity), all renameable and
  editable. Off is the instant panic switch. Device wiring (toys,
  zones, OSC addresses) is shared, so you configure the rig once.
* **Switch modes from inside VRChat.** One local `OGP/Mode` Int on the
  expression menu drives the whole app, plus an `OGP/Test` button that
  pulses your gear at a low level to confirm everything's connected —
  see [`docs/VRCHAT_MENU.md`](docs/VRCHAT_MENU.md). Optionally, each
  avatar can remember its own last mode.
* **Real-time OSC debugger.** Inspector tab shows live parameter
  values and an OSC diagnostics view exposes packets handled,
  phonebook GETs, handler exceptions, etc.
* **Usage statistics.** A Statistics tab tracks lifetime totals —
  active time, thrust count, per-toy on-time, per-zone (socket / plug /
  touch) contact time — plus a summary of your last 20 sessions.
  Sampled once a second, completely off the haptic hot path, and
  resettable any time.
* **Session logging & replay.** Record a VR session's contact stream to
  disk as line-delimited JSON, then *replay* it back through the live
  router — the recorded motion drives your current mode and chains with
  no partner present, so you can feel and tune tweaks against real
  captured contact. Live VRChat input is paused while replaying, and the
  output still follows the active mode (the Off mode stays silent).
* **Quality of life.** A launch-time update check against GitHub
  releases (opt-out; one HTTPS request, notice only — nothing
  auto-installs), automatic settings snapshots at every launch (newest
  five kept, restorable from Settings → Quality of Life), a tray icon
  that glows with live output intensity while minimized to the tray,
  and an opt-in animated background drift for the gradient color
  profiles.

## 🚀 Installation

### Run from source

**Prerequisites:**
1. [Python 3.10+](https://www.python.org/downloads/).
2. *(Optional)* [Intiface Central](https://intiface.com/central/) — only
   needed if you switch off the built-in Intiface engine in
   Settings → Intiface Engine. By default OscGoesPurrr runs its own bundled
   `intiface-engine` (drop the binary into `intiface-engine/`; see that
   folder's note), so no separate launch is required for the Buttplug.io
   toy backend.
3. *(Optional)* [SteamVR](https://store.steampowered.com/app/250820/)
   — required for the SteamVR tracker, SteamVR Toy Driver, and
   battery-broadcaster features.
4. *(Optional)* [bHaptics Player](https://www.bhaptics.com/) — required
   for the bHaptics backend.
5. *(Optional)* A [PiShock](https://pishock.com/) — a USB cable for the
   serial transport, or a pishock.com account + share code for the cloud
   transport.
6. *(Optional)* A [DG-Lab Coyote 3.0](https://www.dungeon-lab.com/) plus a
   Bluetooth LE adapter — connects directly, no phone app needed.
7. *(Optional)* An [OWO suit](https://owogame.com/) with the *My OWO* phone
   app. The OWO backend also needs `pip install pythonnet` and a vendored
   `OWO.dll` dropped into [`owo-sdk/`](owo-sdk/); it is deliberately left out
   of the default install (see that folder's note).
8. *(Optional)* A [Handy 2 / Handy Pro 2](https://www.thehandy.com/) on
   Wi-Fi, linked to your Handy account. The native backend needs the device
   connection key (Handyverse app) and an API key (Application ID) from
   [user.handyfeeling.com](https://user.handyfeeling.com) — commands route
   through the official handyfeeling.com cloud API.

> Bluetooth (`bleak`), serial (`pyserial`), and cloud (`requests`) support
> install automatically with `requirements.txt`; their imports are guarded,
> so a missing library only disables its own backend. `pythonnet` is the lone
> exception — it is opt-in for OWO.

**Setup:**

1. Clone or download this repository.
2. Open a terminal in the folder and install dependencies:
   ```bash
   pip install -r requirements.txt -c constraints.txt
   ```
   (`constraints.txt` pins the exact versions the release was tested
   with; drop the `-c` flag if you deliberately want newer ones.)
3. Launch with one of:
   ```bash
   python main.py
   ```
   ```bash
   run.bat
   ```
   `run.bat` installs dependencies on first launch and re-runs the
   install automatically whenever `requirements.txt` or
   `constraints.txt` change.

### Prebuilt Windows executable

A standalone `.exe` is produced by `build_OGP.bat` (PyInstaller, one-file,
windowed). Built binaries live under `dist/`. Just double-click the
exe — no Python install required.

```bash
build_OGP.bat
```

## 🧭 Tour of the UI

Sidebar views (toggle from the left rail):

* **Dashboard** — connection status, OSC stats, current avatar,
  per-toy vibration meters.
* **Overview** — read-only unified card-grid of every connected or
  stored thing across all backends (toys, trackers, suit, system
  health), with chip filters per section. Click a tile to jump to its
  editor view.
* **Simple Mode** — stripped-down panel showing only "is OSC connected
  / which toys are live". On by default; toggle in Settings to reveal
  the full UI.
* **Device Routing** — the full per-toy / per-motor matrix: zone
  bindings, touch/pen/self/other filters, speed-blend tuning, linear
  actuator config, plus a per-motor "Mirror to VRChat parameter" toggle
  that sends the motor's output back to VRChat as an avatar parameter.
* **SPS Sources** — build *synthetic* SPS sources from raw VRChat
  contact receivers: a proximity receiver gated by "activation" binary
  contacts (so it only fires in a very specific spot), boosted by
  "velocity" on-enter contacts (a shared multiplier), and capped by a
  max value. Each source becomes selectable in the Device Routing zone
  picker and the bHaptics Cross-Routing picker, just like an
  auto-detected zone.
* **SteamVR Device Comms** — list of detected SteamVR trackers,
  per-tracker pattern + address config, autostart toggle, battery
  interval, no-data fallback.
* **bHaptics** — bHaptics Player connection, per-position device
  enables + intensity, antistuck timers, the connected-state OSC bool
  feature, plus a live click-to-test dot grid.
* **PiShock** — transport (serial / cloud) + connection setup,
  per-zone rising-edge configs (op, threshold, intensity range,
  duration, cooldown), the safety caps and global rate backstop, and a
  gently-capped test-fire button.
* **Coyote** — BLE device scan / pick, per-channel A/B strength limits
  and waveform, zone routing, plus live battery and strength readouts.
* **OWO** — OWO app connection (game id / IP), frequency, and
  per-muscle zone routing for the suit's ten muscle groups.
* **Handy** — handyfeeling.com connection (connection key + API key),
  control mode (stroke speed / position), stroke zone, command-rate
  cap, and the stroker's zone routing chain.
* **OSC Inspector** — live tree of every parameter currently in the
  cache (the "shadow state").
* **OSC Diagnostics** — packets-handled counter, phonebook GET log,
  handler exceptions, port info — for debugging silent-drop bugs.
* **System Log** — scrollback of everything logged this session.
* **Settings** — feature toggles, window/console behaviour, color
  profiles, speed-blend tuning, SteamVR Toy Driver
  install/uninstall.
* **Help** — short docs for each feature.

**Help Mode**: flip the toggle in the sidebar and small `?` badges
appear next to controls across every view — zone pickers, gate knobs,
safety caps, fold headers. Click a badge for a short in-place
explanation of exactly that control.

## 🎮 SteamVR Toy Driver

The toy driver is an optional C++ OpenVR driver that lives in
`steamvr_toy_driver/`. When enabled, it makes connected Buttplug toys
(and any configured bHaptics positions) appear as virtual trackers in
SteamVR's device strip with their own icons and battery indicators.

* Enable / disable from **Settings → SteamVR Toy Driver**.
* The first time you enable it, the installer copies the driver bundle
  into `%LOCALAPPDATA%\OpenVR\openvr.vrpaths`'s driver directory and
  registers it with SteamVR. Subsequent launches just connect the
  bridge socket.
* The Python side talks to the running driver over a localhost TCP
  socket (newline-JSON, port `24855`) — see
  [`steamvr_toy_driver/README.md`](steamvr_toy_driver/README.md) for
  the wire format.

## 📁 Where settings live

All user state is stored under `%APPDATA%\OscGoesPurrr\`:

* `profiles.json` — the six modes + shared device wiring (schema v3; a
  corrupt or older-format file is backed up to `.bak` and reset).
* `app_settings.json` — UI toggles, window geometry, speed-blend
  tuning, feature flags.
* `steamvr_settings.json` — per-tracker config + patterns.
* `bhaptics_settings.json` — bHaptics Player endpoint + per-position
  device configs + antistuck.
* `pishock_settings.json` — PiShock transport + connection, safety
  caps, global rate backstop, per-zone configs.
* `coyote_settings.json` — Coyote BLE device + per-channel limits,
  waveform, and zone routing.
* `owo_settings.json` — OWO app connection + frequency + per-muscle
  routing.
* `handy_settings.json` — Handy cloud credentials + motion settings +
  zone routing.
* `known_devices.json` — global registry of every toy ever seen.
* `sps_sources.json` — user-defined synthetic SPS sources.
* `stats.json` — lifetime usage statistics + recent-session summaries.

Delete a file to reset that subsystem to defaults; the app re-creates
it on next launch.

## 🧪 Developer tools

The **Test Bench** (`testbench/`) is a standalone program that exercises a live
VRChat-OSC haptics app — OscGoesPurrr or any other on the market (OSC Goes
Brrr, …) — without VRChat or real hardware, and benchmarks end-to-end latency.
It drives avatar OSC parameters into the target app (impersonating VRChat, with
a discovered-app picker + manual host:port) and reads the resulting toy output
(impersonating a Lovense toy on Intiface) on one clock, plotting input vs
output and measuring "program delay". Three modes:

* **Input** — drive avatar params only (impersonate VRChat).
* **Output** — watch a virtual toy's level only (impersonate a toy on Intiface).
* **Benchmark** — both, with edge-paired latency stats, a histogram, and CSV
  export.

It never imports the main app and needs no hardware powered on. Run
`testbench/run_testbench.bat` (`python -m testbench`); build with
`testbench/build_testbench.bat`. See
[`testbench/README.md`](testbench/README.md) for the one-time Intiface / OGP
setup.

The optional C++ SteamVR toy driver in `steamvr_toy_driver/` builds via
`steamvr_toy_driver/build_driver.bat` — see
[`steamvr_toy_driver/README.md`](steamvr_toy_driver/README.md).

## 🛠️ Contributing

Read [`ARCHITECTURE.md`](ARCHITECTURE.md) before adding a new haptic
backend. It documents the sealed-engine / stateless-router /
controller-mixin pattern that every existing backend follows, plus
the four anti-tangling rules that keep the layers separate.

Roadmap items live in [`ROADMAP.md`](ROADMAP.md).

## 📝 License

GPL-3.0-or-later. See [`LICENSE`](LICENSE).
