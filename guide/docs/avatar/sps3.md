---
title: SPS 3 avatars
description: Avatars built with VRCFury 1.1443.0 or newer use SPS 3. OGP reads them with no setup.
---

# SPS 3 avatars

VRCFury 1.1443.0 (November 2026) brought **SPS 3**. It renamed the zones'
parameters (`OGB/Socket/…` and `OGB/Plug/…`) and measures depth with VRChat's
newer contact receivers. OGP reads SPS 3 avatars as they are: nothing to set
up, and your zones show in a toy's **Select Zones** like before.

Older SPS, OGB and TPS avatars behave exactly as they always did.

## What's different with SPS 3

- **Touch** on an SPS 3 avatar is two things at once: how close the contact
  is, in the chain's **Depth** channel, plus VRChat's measured hand speed, in
  the **Speed** channel. The chain's **Combine** stage mixes them, as it does
  for penetration. So a still hand resting on you feels different from a
  stroking one.
- **Penetration depth** comes from the socket's depth contacts and the plug's
  length.

## Make sure the receivers are on

An SPS 3 avatar keeps its plug and socket touch receivers off until an app
switches them on with `OGB/Enabled`. OGP sends it every few seconds and right
after an avatar loads, next to the older `OGB_ENABLED`. You don't need to do
anything; if your zones never show, see
[Common problems](../help/common-problems.md#avatar-has-sps-stays-grey).
