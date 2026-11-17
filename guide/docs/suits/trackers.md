---
title: Haptic trackers
description: SteamVR trackers with a motor buzz from your avatar's contacts, using Haptic Pancake's names.
---

# Haptic trackers

A SteamVR tracker with a motor can buzz from your avatar's contacts: a Vive
Tracker with a **Haptic Pancake** on its pins, a Tundra with a **Tundra
Tapper**, or a controller set up as a tracker.

Switch it on first: Settings → Features → **Trackers — vibrating trackers
through SteamVR**, or tick **Trackers that vibrate** in *What are you here
for?*. It's off by default. OGP never starts SteamVR itself.

## Nine spots

Trackers sit on Haptic Pancake's nine spots, and each spot follows Haptic
Pancake's parameter name by default. So an avatar set up for Haptic Pancake
works as it is.

| Spot | Parameter |
|---|---|
| Head | `HapticHead` |
| Chest | `HapticChest` |
| Hips | `HapticHips` |
| Right elbow, Left elbow | `HapticElbowRight`, `HapticElbowLeft` |
| Right knee, Left knee | `HapticKneeRight`, `HapticKneeLeft` |
| Right foot, Left foot | `HapticFootRight`, `HapticFootLeft` |

A spot can follow several parameters: the strongest wins.

## Where a tracker goes

- A tracker goes where its **role in SteamVR's Manage Trackers** puts it, as a
  blue puck on the Suits page's body.
- A tracker without a usable role is listed under the chips with **Buzz** (to
  find which one it is) and **Place on her**: the next click on a spot puts it
  there.

## Limits

- Each spot's **Top** starts at 80 %: Haptic Pancake's guide warns that a plain
  motor overloads the Vive Tracker's pin at full.
- A level that isn't sent again soon plays nothing.
- Off, VRChat going silent, [Off while away](../settings/away.md) and the
  trackers' own [anti-stuck](../toys/toy-safety.md) (under her, after the
  trackers, with its own times) hold the trackers like the suits.

Only real trackers buzz: never OGP's own toy entries in SteamVR, never virtual
trackers.
