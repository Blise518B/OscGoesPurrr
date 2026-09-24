# OscGoesPurrr SteamVR toy driver

A small SteamVR driver that lists the user's connected toys in SteamVR's
device list (the status window strip), with their name, icon and battery —
the "Show toys in SteamVR" setting (on by default). Just for fun.

Toys are registered as **TrackingReference** devices with no valid pose, no
tracker role and an input profile without inputs. SteamVR shows them, but
no app — VRChat's full-body tracking included — can ever use one as a body
tracker or bind input to it.

## How it fits together

1. SteamVR loads the driver and it listens on `127.0.0.1:24855` — one
   listening socket for the driver's whole life, serving one app at a time.
2. OscGoesPurrr connects (`src/steamvr_toy_bridge.py`) and sends the toy
   list whenever it changes, plus a heartbeat every 30 s. When the app
   comes back (setting switched on again, app restarted) its toys are
   reported connected again, in the same SteamVR slots.
3. New toys are added to SteamVR; toys that leave the list — disconnected,
   the setting switched off, the app closed — are reported disconnected,
   which takes them off the strip. (SteamVR has no way to remove a device.)

`src/steamvr_toy_driver_installer.py` copies the driver to
`%LOCALAPPDATA%\OscGoesPurrr\steamvr_driver\oscgoespurrr\` and adds that
folder to `external_drivers` in `%LOCALAPPDATA%\openvr\openvrpaths.vrpath` —
no admin rights, nothing written inside Steam's folder. It does that at
launch while the setting is on (the default) — but only once SteamVR has
run on the PC (`openvrpaths.vrpath` exists); otherwise nothing is touched.
It re-copies the files whenever the app carries a different driver than
the installed one; SteamVR loads the new one on its next start. Switching
the setting off removes the `external_drivers` entry again, so SteamVR
stops loading the driver.

## Protocol

Newline-delimited JSON from the app to the driver:

    {"type": "hello", "version": 1}
    {"type": "set_devices", "devices": [
        {"serial": "OGP_TOY_LOVENSE_GUSH", "name": "Lovense Gush",
         "icon_key": "gush_2", "icon": "{oscgoespurrr}/icons/gush_2.png",
         "battery": 0.82}
    ]}

`set_devices` is always the full list. `icon_key` is set as the device's
model number, which SteamVR matches against `resources/driver.vrresources`
to pick the toy's icon.

## Presentation settings

`resources/settings/default.vrsettings` holds `toy_device_class` (4 =
TrackingReference), `toy_pose_valid` (false) and `toy_render_model` (none),
read once when SteamVR starts. They exist to test other presentations
without a rebuild; the shipped values are the safe ones.

Hovering a toy in SteamVR's status window says "Searching... This base
station is not currently tracking any devices". That is SteamVR's own text
for a base station without a pose, and it is the price of never being a
tracker: the other device classes are headset, controller and tracker, all
of which apps use for input or tracking. Reporting the tracking result as
"running OK" while the pose stays invalid does not change the text (tried
2026-09-24).

## Building

Needs Visual Studio Build Tools (C++ workload) and CMake. Run
`fetch_header.bat` once for `include/openvr_driver.h`, then
`build_driver.bat`. The DLL lands in `bin/win64/` and is committed, so
building the app never needs a C++ toolchain. After a rebuild, check the
DLL contains no build-machine paths before releasing.
