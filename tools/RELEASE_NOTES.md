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

A small update to 0.15.0: avatars built with the newest VRCFury work again, and
OGP sits quieter while nothing happens.

- **SPS 3 avatars.** VRCFury 1.1443.0 (10 November) changed how sockets and
  plugs report, so OGP found none on an avatar built with it. It reads them
  again: depth, touch and frot, and it switches the avatar's touch contacts
  on, which such an avatar now waits for. Touch also brings VRChat's own
  reading of how fast the hand moves, so a hand sliding along you is felt,
  not just one coming closer; each toy's Touch chain mixes it in through its
  Speed and Combine settings. Older avatars feel exactly as before.
- **Built with haptics off?** The OSC Inspector page says so when the avatar
  you wear was built with VRCFury's haptics switched off, and where to switch
  them back on.
- **Less CPU while idle.** With nothing playing, OGP's routing and its toy
  engine rest instead of waking about a hundred times a second, and Home's
  meters repaint once per frame: fewer times while OGP isn't focused, not at
  all while it's minimized.
- **VRChat stays connected.** A crashed VRChat can leave its network
  announcement behind for hours, and OGP kept dropping the working connection
  for it every 15 seconds or so. It now sticks with the VRChat that answers.
- **What's new, page by page.** Updating over several releases shows every
  release's notes, one page each, instead of only the newest two.

**Coming from 0.14 or older?** 0.15.0 brought the haptic suits and Intiface on
your phone: [the 0.15.0 notes](https://github.com/Blise518B/OscGoesPurrr/releases/tag/v0.15.0).

More on the website: https://blise518b.github.io/OscGoesPurrr/
