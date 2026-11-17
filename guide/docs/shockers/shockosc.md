---
title: ShockOSC avatars
description: An avatar set up for ShockOSC needs one click, and its ShockOSC settings stay in step with OGP's.
---

# ShockOSC avatars

**ShockOSC** is OpenShock's VRChat app. An avatar set up for it carries
parameters starting with `ShockOsc/`, one group per shocker. OGP understands
them: such an avatar needs one click, and you don't run ShockOSC itself.

## Set it up

1. Wear the avatar, with VRChat's OSC on.
2. On the Shockers page, a card says **Your avatar is set up for ShockOSC**,
   with a row per group: what it becomes, and the shocker it drives.
3. Each group takes the shocker with its name. Drop another shocker on its
   row to change that. `_All` takes every shocker.
4. Press **Set up N behaviours**.

The behaviours land with the others, each with a grey **SHOCKOSC** tag. Run
the setup again after you change the avatar: it only adds what's missing.

| ShockOSC parameter | Becomes |
|---|---|
| `ShockOsc/<Group>` (a touch) | a [Contact](./behaviours.md#contact) that shocks once per touch |
| `_IShock` / `_IVibrate` / `_ISound` | a Contact that pulses once with that action |
| `_CShock` / `_CVibrate` / `_CSound` | a [Continuous](./behaviours.md#continuous) |
| `_IsGrabbed` / `_Stretch` (a PhysBone) | a [Pull](./behaviours.md#pull): vibrate while held, a shock on the let-go, as strong as the pull |

New behaviours start with the same values as a behaviour you add by hand
(a Contact 20 for 0.5 s, a Continuous and a Pull 5 to 30), except that a
touch shocks only once it has been held for **0.25 s**, as in ShockOSC, so a
brush does nothing. Change them like any other.

## Your avatar's ShockOSC settings

An avatar can carry ShockOSC's own settings (`ShockOsc/_Config/…`), often as
radials in its menu. **They and the behaviours keep the same values**: change
one in the avatar's menu and the behaviours change, shown on the page at once;
change a behaviour on the page and the avatar's setting changes too.

| ShockOSC setting | The behaviours' |
|---|---|
| **Intensity** (or **MaxIntensity** in its range mode) | Strength (a Continuous's and a Pull's top) |
| **MinIntensity** (range mode) | A Continuous's and a Pull's lowest strength |
| **Duration** (or **MaxDuration**) | Length |
| **CooldownTime** | **Rest after a shock**: after a shock from the group, its behaviours wait this long |
| **HoldTime** | A touch's **Touch for at least** |
| **Paused** | On / Off: Paused switches them off and stops at once whatever they're running, like Stop; it's sent once they're all off |

- `_All`'s settings are the ones every group follows, as in ShockOSC. A group
  goes with its own (`ShockOsc/_Config/Collar/…`) only when the avatar has
  them. So one Intensity radial moves every group's behaviours together, and
  changing one of them on the page changes the others with it.
- The avatar's **Paused** for `_All` is a kill switch: on, every ShockOSC
  behaviour goes off.
- When you switch avatars, OGP sends its values first. The avatar takes them,
  rather than OGP taking the avatar's saved ones.
- A friend with [YOLO](../avatar-remote/friends.md) on can set these too, like
  your own menu.
- `_NextIntensity` / `_NextDuration` only ever make the next action gentler.

Your [limits and arming](./safety.md) hold as always, whatever either side
says: a strength of 80 on a shocker capped at 25 sends 25. A strength of 0
sends nothing.

## Feedback to the avatar

OGP sends ShockOSC's feedback parameters back (**Active**, **Cooldown**,
**CooldownPercentage**, **DurationRemaining**, **Intensity**, per group and
`_Any`), so the avatar's lights and countdowns follow what the shockers really
do. Only real shocks count: an unarmed shock is a vibrate and lights nothing.

OGP's own [Off while you're away](../settings/away.md) stands in for ShockOSC's
"disable while AFK".
