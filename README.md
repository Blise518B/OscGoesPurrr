# OscGoesPurrr 🐾

A multi-backend haptic feedback router for VRChat. Reads your avatar's
OSC parameters and translates them into smooth output for Bluetooth
toys, SteamVR trackers, bHaptics suits, and the SteamVR overlay.

## ✨ Features

* **Buttplug.io toys via Intiface Central.** Auto-discovery, multi-zone
  routing, per-motor speed-blend tuning, linear-actuator support
  (Lovense Solace Pro, Gravity, OSR2…).
* **SteamVR tracker haptics.** Dispatches OSC values to any SteamVR
  device that supports `TriggerHapticPulse` (Tundra trackers, Vive
  trackers, etc.) with per-tracker patterns and a battery broadcaster
  that publishes tracker battery back to VRChat.
* **bHaptics suits / vests.** Translates v1 `bHapticsOSC` parameters
  (HerpDerpinstine schema) into dot-mode frames for the bHaptics
  Player. Antistuck timer, per-position enable, optional
  `bHaptics_Connected` bool back to VRChat.
* **Hardware monitor.** Optional CPU / RAM / GPU / VRAM broadcaster —
  publishes live stats to VRChat avatar parameters so an HUD avatar can
  display them.
* **SteamVR Toy Driver.** Optional virtual-device bridge that makes
  your connected toys and configured bHaptics positions show up as
  trackers in SteamVR's device strip, complete with battery icons.
* **Auto-discovery.** VRChat is found via mDNS — no IP / port typing.
* **Shadow-state router.** Downloads the avatar's OSCQuery parameter
  list at connect time for flawless, debounced routing.
* **Multi-zone.** Bind a single motor to multiple OGB zones (Head,
  Tail, etc.) with simple checkbox menus.
* **Avatar-bound profiles.** Profiles can be pinned to a specific
  `avtr_*` id so loading an avatar auto-selects the right config; plus
  a global Default fallback.
* **Real-time OSC debugger.** Inspector tab shows live parameter
  values and an OSC diagnostics view exposes packets handled,
  phonebook GETs, handler exceptions, etc.

## 🚀 Installation

### Run from source

**Prerequisites:**
1. [Python 3.10+](https://www.python.org/downloads/).
2. [Intiface Central](https://intiface.com/central/) — required for
   the Buttplug.io toy backend.
3. *(Optional)* [SteamVR](https://store.steampowered.com/app/250820/)
   — required for the SteamVR tracker, SteamVR Toy Driver, and
   battery-broadcaster features.
4. *(Optional)* [bHaptics Player](https://www.bhaptics.com/) — required
   for the bHaptics backend.

**Setup:**

1. Clone or download this repository.
2. Open a terminal in the folder and install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
3. Launch with one of:
   ```bash
   python main.py
   ```
   ```bash
   run.bat
   ```
   `run.bat` will install/update dependencies first.

### Prebuilt Windows executable

A standalone `.exe` is produced by `build.bat` (PyInstaller, one-file,
windowed). Built binaries live under `dist/`. Just double-click the
exe — no Python install required.

```bash
build.bat
```

## 🧭 Tour of the UI

Sidebar views (toggle from the left rail):

* **Dashboard** — connection status, OSC stats, current avatar,
  per-toy vibration meters.
* **Simple Mode** — stripped-down panel showing only "is OSC connected
  / which toys are live". On by default; toggle in Settings to reveal
  the full UI.
* **Device Routing** — the full per-toy / per-motor matrix: zone
  bindings, touch/pen/self/other filters, speed-blend tuning, linear
  actuator config.
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
* **Hardware Monitor** — opt-in CPU / RAM / GPU broadcaster with live
  stats and per-stat OSC address config.
* **OSC Inspector** — live tree of every parameter currently in the
  cache (the "shadow state").
* **OSC Diagnostics** — packets-handled counter, phonebook GET log,
  handler exceptions, port info — for debugging silent-drop bugs.
* **System Log** — scrollback of everything logged this session.
* **Settings** — feature toggles, window/console behaviour, profile
  copy/paste, speed-blend tuning, SteamVR Toy Driver
  install/uninstall.
* **Help** — short docs for each feature.

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

* `profiles.json` — toy routing profiles + avatar bindings.
* `app_settings.json` — UI toggles, window geometry, speed-blend
  tuning, feature flags.
* `steamvr_settings.json` — per-tracker config + patterns.
* `bhaptics_settings.json` — bHaptics Player endpoint + per-position
  device configs + antistuck.
* `hardware_monitor_settings.json` — CPU/RAM/GPU broadcaster config.
* `known_devices.json` — global registry of every toy ever seen.
* `sps_sources.json` — user-defined synthetic SPS sources.

Delete a file to reset that subsystem to defaults; the app re-creates
it on next launch.

## 🛠️ Contributing

Read [`ARCHITECTURE.md`](ARCHITECTURE.md) before adding a new haptic
backend. It documents the sealed-engine / stateless-router /
controller-mixin pattern that every existing backend follows, plus
the four anti-tangling rules that keep the layers separate.

Roadmap items live in [`ROADMAP.md`](ROADMAP.md).

## 📝 License

GPL-3.0-or-later. See [`LICENSE`](LICENSE).
