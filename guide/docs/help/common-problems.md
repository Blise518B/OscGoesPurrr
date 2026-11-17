---
title: Common problems and how to solve them
sidebar_label: Common problems
description: What goes wrong, why, and what to do.
---

# Common problems and how to solve them

Something not working? Find it below. Most of the time OGP already says
what's wrong: rest the mouse on the thing that looks off, or press
<kbd>F1</kbd>.

## Install

### "Windows protected your PC"

- **Cause:** the exe isn't code-signed, so Windows doesn't know it yet.
- **Solution:** click **More info → Run anyway**. Windows asks only the first
  time.

## Toys

### My toy isn't found

- **Cause:** a toy talks to one thing at a time. If its phone app (or another
  program) has it, OGP can't. Or this PC's Bluetooth is off.
- **Solution:** close the toy's own app, switch the toy off and on, and press
  **Scan now** on the Toys page. Check that Bluetooth is on. The sidebar's
  **Intiface** row should say **CONNECTED**.

### OGP doesn't see the Intiface Central on my phone

- **Cause:** OGP still uses its built-in engine, or the phone doesn't let
  others in.
- **Solution:** on the phone, switch on **Listen on all network interfaces**
  (and **Broadcast Server Info via mDNS** to be found without an address), and
  start the server. In OGP, Settings → Intiface Engine → switch off **Use
  built-in Intiface engine**, and type the phone's address if it isn't found.
  It needs Intiface Central 3.0 or newer. See
  [Where your toys connect](../toys/toy-server.md).

### My toy doesn't react when I'm touched

- **Cause:** the toy doesn't listen to that contact: its zones don't include
  it, or its chips leave out that kind of touch. A touch from yourself is off
  for a new toy.
- **Solution:** on Home, check the toy's four chips (Touch / Penetration from
  Self / Others). On the Toys page, open the toy's chain → **Input** →
  **Select Zones**, and pick **All SPS** or the zone. Make sure the toy isn't on
  **Mute**.

### Everything is silent, and Off isn't on

- **Cause:** total output strength is at 0 (a menu radial parked at 0 looks
  exactly like this), you're AFK in VRChat, or Sleep is on.
- **Solution:** check the strength slider. The status bar says
  **AFK: everything off** while you're away. Sleep waits for three full
  strokes.

### Sleep seems dead

- **Cause:** that's Sleep working: nothing plays until three full strokes land
  within six seconds, so a brush can't wake it.
- **Solution:** switch Sleep off for normal play.

### Switching modes did nothing

- **Cause:** modes are routings, not strengths. If two modes route the same
  motors from the same zones, they feel the same.
- **Solution:** set them apart on the Toys page → the toy → **Input**, with
  the mode you want to change active.

### One toy is much stronger than the rest

- **Cause:** toys differ.
- **Solution:** leave total strength alone. Trim that toy: Toys → the toy →
  its chain → **Output → Gain**. If it does nothing low down or is too much at
  the top, set **Output → Range**.

### A toy keeps running after my partner left

- **Cause:** VRChat sent the contact's last value and then nothing more.
- **Solution:** leave **Anti-stuck** on: the Toys page's, under Toy server,
  and the toy's own **Anti-stuck** chip on its bar. It stops a frozen value
  after 1 s, or eases off one held at 100 % after 10 s. The suits and the
  headset have their own on their pages.

## VRChat and your avatar

### The VRChat row doesn't say CONNECTED

- **Cause:** OSC is off in VRChat, or VRChat isn't running yet.
- **Solution:** in VRChat, **Action menu → Options → OSC → Enabled**. OGP
  finds VRChat by itself. **OSC Diagnostics**, under TOOLS in the sidebar,
  shows what OGP sees.

### "Avatar has SPS" stays grey

- **Cause:** the avatar you're wearing has no SPS (or OGB / TPS) contacts, or
  VRChat hasn't told OGP about it: OSC is off, or VRChat keeps an old list of
  the avatar's parameters from before you added SPS.
- **Solution:** wear an avatar with SPS sockets or plugs, with the VRChat row
  saying **CONNECTED**. Added SPS to an avatar you used before? Reset VRChat's
  list as in [The avatar menu does nothing](#the-avatar-menu-does-nothing).
  An SPS 3 avatar needs nothing else: OGP switches its receivers on. No SPS on
  the avatar? Build your own zones under
  [SPS Sources](../toys/toys-page.md#sps-sources).

### The avatar menu does nothing

- **Cause:** VRChat keeps an old list of each avatar's OSC parameters. An
  avatar you used before you added OGP's menu still has the old one.
- **Solution:** close VRChat, delete the folder
  `%USERPROFILE%\AppData\LocalLow\VRChat\VRChat\OSC\` (just that folder; VRChat
  makes it again), and load the avatar.

### Every control shows twice in my menu

- **Cause:** the avatar has both the VRCFury prefab and the older one-click
  installer's submenu, and VRCFury merged them.
- **Solution:** remove the "OscGoesPurrr" submenu the installer added to your
  expressions menu. Its parameters can stay.

### My menu has a "Both of us" folder that does nothing

- **Cause:** it's from an older prefab. Driving yourself and a friend at once
  is a group with you in it now.
- **Solution:** drag in the newer prefab. See
  [Groups and Me](../friends/groups-and-me.md#you-and-a-friend-at-once).

### The Height box is greyed out

- **Cause:** the world you're in forbids changing your height.
- **Solution:** nothing to fix: it works again in a world that allows it.

## Shockers

### My shocks arrive as vibrations

- **Cause:** shocks aren't armed. Until you arm them, every shock is a
  vibrate. The red words say **Shocks not armed**.
- **Solution:** switch on **Arm shocks** (Home's shocker row or the Shockers
  page) and answer **Yes**. Read [Arming and limits](../shockers/safety.md)
  first.

### A friend's Shock button is greyed

- **Cause:** the other side doesn't allow it: Shock is switched off on that
  shocker, or Vibrate is off there and they haven't armed (an unarmed shock
  goes out as a vibrate). The card says which.
- **Solution:** ask them. It's their call.

### The hub isn't found

- **Cause:** another program has the hub's port open (only one can), or the
  cable only charges.
- **Solution:** close other shocker apps, try another USB cable, and press
  **↻** next to the port.

### ShockOSC behaviours do nothing

- **Cause:** the avatar's ShockOSC settings say intensity 0, or Paused. They
  and the behaviours keep the same values, so the behaviours' strength is 0
  or they're switched off.
- **Solution:** turn the avatar's Intensity up or unpause it in its menu, or
  change the behaviours on the Shockers page: the avatar follows.

## Friends

### A friend shows offline

- **Cause:** they're offline, or OGP hasn't looked for them yet. It looks in
  the background, gently.
- **Solution:** press **↻** on their row, or **↻ Check all**.

### My second OGP window won't go online

- **Cause:** one OGP per PC goes online.
- **Solution:** use the first window.

### No friend can drive me

- **Cause:** **Pause all** is on; or **Only friends in my instance** is on
  while **Read VRChat's log** is off, so nobody is seen in your instance; or
  their switches are off.
- **Solution:** check the top of the Friends page and the friend's row. See
  [VRChat accounts and your instance](../friends/vrchat-accounts.md#only-friends-in-your-instance).

### A friend's panel says "Not here"

- **Cause:** they have **Only friends in my instance** on, and you're not in
  their VRChat instance (or they haven't linked you).
- **Solution:** join them in VRChat, or ask them to link your account or
  allow you from anywhere.

### The web remote link stopped working

- **Cause:** the link was replaced (New link…), switched off, or that browser
  was kicked.
- **Solution:** ask for the new link. A kicked browser can't come back with
  the old one.

## Suits and the headset

### My bHaptics suit won't connect

- **Cause:** the bHaptics Player is running. A suit takes one connection at a
  time.
- **Solution:** close the bHaptics Player, then press **Connect**. **Let go**
  hands the suit back to the Player later.

### PSVR2: Feel it is silent

- **Cause:** the headset isn't jailbroken (the commands go through, the motor
  never moves), or the toolkit isn't one of its experimental builds.
- **Solution:** see [PSVR2](../psvr2.md#what-you-need).

## Still stuck?

The **System Log** page (under TOOLS) has what OGP did and why. The
[issues on GitHub](https://github.com/Blise518B/OscGoesPurrr/issues) are the
place to ask.
