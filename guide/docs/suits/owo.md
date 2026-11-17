---
title: OWO
description: An OWO suit through the My OWO app, capped where you set it.
---

# OWO

OGP drives an OWO suit through the **My OWO** app, the way a game does. My
OWO keeps your calibration and drives the suit.

Switch it on first: Settings → Features → **OWO — EMS suit through the My
OWO app**, or tick **An OWO suit** in *What are you here for?*. It's off by
default. It's on the **Suits** page, next to bHaptics.

:::warning OWO is EMS
It moves your muscles with electric pulses. OGP caps everything, and starts
low: the **Ceiling** begins at 60 %.
:::

## Connect

1. Open **My OWO** and calibrate the suit there.
2. Press **Connect** on the OWO card. OGP looks for My OWO on this PC first,
   then on your network. **My OWO at** takes an address if it's elsewhere.

**Connect when the app starts** is off by default: OWO connects only when you
press Connect, until you switch that on.

## Limits

- 100 % is the top of your calibration in My OWO.
- **Ceiling** caps every sensation. It starts at 60 %, and can't go past what
  you set.
- Each muscle has its own **Top**.
- **Frequency** sets the pulse frequency.
- **Stop all** stops OWO at once and refuses everything until **Resume**.
- Off, VRChat going silent, [Off while away](../settings/away.md) and quitting
  OGP stop it too.
- Its own [anti-stuck](../toys/toy-safety.md), the **Anti-stuck** card in the
  OWO frame, cuts a contact that freezes, with its own times. Being EMS, keep
  it on unless you know why not.

## Contacts

The OWO avatar package's contacts (`owo_suit_…`) work with no setup. With
**Also feel bHaptics' contacts** on (the default), a bHaptics contact plays
the OWO muscle around it.

**Tell VRChat** sends `OGP/OWOConnected` while OGP is connected to My OWO.
