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

## VRChat Integration

- **Profile switching from the VRChat Expressions menu.**
  Map an integer avatar parameter (e.g. `/avatar/parameters/PurrProfile`)
  to profile slots so the active profile can be changed in-game without
  alt-tabbing. Configurable parameter name; out-of-range values ignored.
- **SPS priority layering.**
  While SPS contacts are actively firing, dim or mute the regular touch
  zones so the SPS sensation isn't drowned out by background contact
  hits. Per-profile toggle with a dim-amount slider.
- **Per-input max-value clamp.**
  Per-OSC-parameter ceiling (0.0–1.0) so a single zone or contact can't
  push a motor to full output. Lets users cap noisy or overly-eager
  inputs without rewriting the whole routing.

## Reliability & Lifecycle

- **Stuck-value safety cutoff.**
  If an OSC float input stays exactly static for ~2 s (configurable),
  treat it as a stuck/frozen sender and force the corresponding motors
  to 0 until the value changes again.  Prevents motors running forever
  when VRChat or an avatar param hangs. if its at 1.0 maybe have it ramp down slowly because it could also mean all the way in.
- **SteamVR-aware shutdown.**
  Detect when SteamVR exits and either auto-quit OscGoesPurrr or at
  minimum send 0 to every connected device and stop output. User
  setting to pick which behavior.

## UI Modes

- **Mini-Mode / VR companion window.**
  A compact, always-on-top layout showing only the essentials (active
  profile, vibe meters, master toggle) for use as a desktop overlay
  while in VR. Toggle from the main window; remembers its own size and
  position.

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
