# Vendored OpenVR driver header

This folder needs `openvr_driver.h` from Valve's OpenVR SDK to build the
driver. It is **not** committed because it's third-party and large.

Fetch it once before building:

    curl -L -o openvr_driver.h https://raw.githubusercontent.com/ValveSoftware/openvr/master/headers/openvr_driver.h

(Or download the SDK zip from https://github.com/ValveSoftware/openvr and
copy `headers/openvr_driver.h` here.)

The header is BSD-3 licensed and is API-stable across SteamVR releases —
fetching the master branch is safe.
