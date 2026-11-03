## Install

**Windows:** download **OscGoesPurrr-Windows.exe** below and run it. That's the
whole install — one file, no setup wizard, no Python, no separate Intiface
Central. Windows will show a blue "Windows protected your PC" box the first
time, because the exe isn't code-signed (a certificate costs a few hundred a
year). Click **More info → Run anyway**.

**Linux (x86_64):** download **OscGoesPurrr-Linux-x86_64.AppImage** below, make
it executable (`chmod +x`, or *Allow executing* in its Properties) and run it.
It's built by GitHub a few minutes after this release appears.

**Your avatar's menu (optional):** **OscGoesPurrr-VRCFury.unitypackage** below
puts OGP's controls into your avatar's own menu: strength, Off, Sleep, modes,
Avatar Remote's toggles and radials, and a Friends submenu to drive whoever you
picked in OGP. Import it into your avatar's Unity project (it needs VRCFury),
drag one of its three prefabs onto your avatar and upload. [Setup guide](https://github.com/Blise518B/OscGoesPurrr/blob/main/docs/VRCHAT_MENU.md)

Already running an older version? Don't download anything — it'll offer the
update itself at launch.

## What's new

<!-- Replace this section before each release. Keep it short and concrete:
     what changed, and what a user would notice. -->

The haptic suits arrive, and Intiface can now run on your phone.

- **Haptic suits.** A bHaptics suit, sleeves or head straight over
  Bluetooth — no bHaptics Player (close it: a suit takes one connection) —
  and an OWO suit through the My OWO app, which keeps your calibration. Both
  play your avatar's bHaptics and OWO contacts, and the Suits page draws them
  on a body: click a motor or a muscle for its card, which also says whether
  the avatar you wear has its contacts. Each suit has its own switch in
  Settings → Features, off by default. OWO is EMS, so OGP connects to it only
  when you press Connect and starts it capped at 60 %. Toy Safety's
  anti-stuck covers the suits too.
- **Intiface on your phone.** Toys paired with a phone, or Intiface Central
  on another PC? Switch off Settings → *Use built-in Intiface engine*, and
  OGP finds an Intiface Central that announces itself on your network or
  connects to the address you type. On the phone, turn on **Listen on all
  network interfaces** (and **Broadcast Server Info via mDNS** to be found
  without an address). The sidebar shows the address and whether Intiface
  answers there. It needs Intiface Central 3.0 or newer, and OGP says so
  when it finds an older one.
- **Avatar Remote in your avatar's menu.** Seven toggles and seven radials
  you hand out to controls or whole categories of your board: the small
  circle in a card's or category's top bar.
- **Friends groups by drag and drop.** Drag friends onto a group, yourself
  included. A group with you in it drives you and them at once from the
  avatar menu, so the menu's *Both of us* section is gone. Import the new
  **OscGoesPurrr-VRCFury.unitypackage** below for the Avatar Remote submenu
  and the groups.
- **Fixes.** Your avatar menu no longer logs, or holds back for later,
  changes to the toys of a friend who doesn't take them right now (their
  Toys switch off for you, or Pause all friends). Friends no longer stops
  setting itself up when its network library can't load, and the
  Statistics page has its session list from the start.

**Coming from 0.13 or older?** 0.14.0 brought Friends, the web remote,
Shockers, Avatar Remote and more:
[the 0.14.0 notes](https://github.com/Blise518B/OscGoesPurrr/releases/tag/v0.14.0).

More on the website: https://blise518b.github.io/OscGoesPurrr/
