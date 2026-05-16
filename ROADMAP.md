# OscGoesPurrr — Roadmap

A loose list of features we want to land, grouped by theme.
Order within a group is rough priority, not a hard sequence.

## UI & Visual Polish

- **Distinct surface colors for interactive widgets.**
  Dropdowns, search fields, and pickers currently blend into the window
  background. Give them a slightly different surface tint so the user can
  see at a glance what's clickable.
- **Higher-contrast checkboxes.**
  When checked, the border should still be a different color from the
  fill — right now the whole box collapses into one color and the
  affordance disappears.
- **Copy/Paste button visual feedback.**
  When the user presses a "Copy" button on a profile/device row, all other
  available Copy buttons should transform into "Paste" buttons, giving clear
  visual feedback about where to interact next.
- **Better iconography.**
  - Green ✓ / red ✗ for confirm/cancel (current ones are low contrast).
  - Edit pencil with stronger outline.
  - Copy icon as two overlapping sheets (clearer than the single 📋 emoji).
  - Trash icon as a trapezoid-style can (more recognizable than the
    current emoji glyph at small sizes).

## Onboarding

- **"Just Works" mode (first launch).**
  Hide all configuration. Automatically map every detected SPS zone to
  every connected toy with sensible defaults. Single toggle in Settings
  to enable advanced mode and reveal the full UI.

## Haptics Features

- **Depth vs in/out-velocity slider for SPS sockets/plugs.**
  Per-zone choice between "intensity tracks penetration depth" (current
  behavior) and "intensity tracks insertion/extraction velocity". Each
  feels very different and there's no clear winner across hardware.
- **Manual pattern mode.**
  A library of pre-baked vibration patterns the user can trigger
  manually (button, hotkey, OSC param) for the case where SPS isn't
  working but they still want stimulation. Should coexist with normal
  routing — pattern playback wins while active, then routing resumes.

## Networking & Multiplayer

- **Remote-control contacts.**
  Allow another VRChat player to drive the local user's toys by
  touching contacts with reserved names (e.g. `OGP/Remote/*`). Needs an
  allow-list so randoms can't grief, plus a kill-switch.

## Hardware Integrations

- **Haptic Pancake integration (Vive/Tundra trackers).**
  Wire in the existing
  [Haptic Pancake](https://github.com/) project so SteamVR trackers can
  receive the same routed signals as buttplug devices. Optional, in its
  own tab.
- **bHaptics integration.**
  Same idea — route to bHaptics suits/vests when enabled. Optional
  toggle in Settings so users who don't own the hardware aren't
  bothered.

---

_Not in scope here:_ bug fixes, refactors, or anything already tracked
in commits/PRs.
