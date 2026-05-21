# OscGoesPurrr SteamVR Toy Driver

A tiny C++ trampoline driver that adds the user's connected toys as virtual
tracked devices in SteamVR's device list, so they show up next to the HMD,
controllers, and trackers — purely for novelty.

The driver does almost nothing on its own. It:

1. Opens a localhost TCP listener on **`127.0.0.1:24855`** at startup.
2. Waits for the OscGoesPurrr Python app to connect over that socket.
3. Receives newline-delimited JSON messages telling it which toys exist,
   their names, batteries, and icon paths.
4. Reports each toy to SteamVR as a `TrackedDeviceClass_Other` with an
   identity pose, the supplied name, and the icon set as the device's
   "ready" / "standby" image.

When the Python app disconnects (or the user toggles the feature off), the
driver removes all virtual devices.

## File layout

    steamvr_toy_driver/
      src/                     C++ source
      include/                 vendored openvr_driver.h
      resources/               driver.vrdrivermanifest + a default icon
      bin/win64/               built driver_oscgoespurrr.dll lives here

The whole `steamvr_toy_driver/` tree is bundled with the PyInstaller build
and copied at runtime to:

    %LOCALAPPDATA%\OscGoesPurrr\steamvr_driver\oscgoespurrr\

The installer then patches
`%LOCALAPPDATA%\openvr\openvrpaths.vrpath` to add that path to
`external_drivers`. No UAC prompt, no writes inside Steam's directory.

## Building

Requires CMake ≥ 3.16 and either MSVC (Visual Studio 2019+) or clang-cl.

    cd steamvr_toy_driver
    cmake -B build -A x64
    cmake --build build --config Release

Output lands in `bin/win64/driver_oscgoespurrr.dll`. Commit the DLL — end
users should not be expected to compile anything.

## Protocol

Newline-delimited JSON, one message per line, server (driver) → client
(Python) and vice-versa. The Python app sends messages of the form:

    {"type": "hello", "version": 1}
    {"type": "set_devices", "devices": [
        {"serial": "OGP_LOVENSE_LUSH4_0001",
         "name": "Lush 4",
         "battery": 0.83,
         "icon": "C:\\...\\lush_4.png"},
        ...
    ]}

The driver replaces its full device list on every `set_devices` message.
This is dumb-simple — no diffing on the wire — and 50 devices fit
comfortably in a single TCP segment. The driver does NOT report serials
back to SteamVR as visible; SteamVR uses them as internal uniqueness keys.

Note: SteamVR only registers new device serials at driver `Init` time
(early in `vrserver` startup). Devices added after Init still appear, but
their slot in the device strip is allocated lazily by SteamVR. If the user
plugs in a new toy mid-session it shows up immediately; if SteamVR has
already filled all virtual slots it gracefully ignores extras.
