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
and a Friends submenu to drive whoever you picked in OGP. Import it into your
avatar's Unity project (it needs VRCFury), drag one of its three prefabs onto
your avatar and upload. [Setup guide](https://github.com/Blise518B/OscGoesPurrr/blob/main/docs/VRCHAT_MENU.md)

Already running an older version? Don't download anything — it'll offer the
update itself at launch.

## What's new

<!-- Replace this section before each release. Keep it short and concrete:
     what changed, and what a user would notice. -->

A small update to 0.14.0, mostly from the first days of people using it.

- **Toys keep their place.** A toy that connects joins the end of the list
  instead of pushing the others down, and every toy shows its number in its
  corner. Friends see your toys in that order, so the avatar menu's toys 1–4
  are the same 1–4 on both sides.
- **Switch a shocker off.** Each shocker card on the Shockers page has its own
  On / Off. An Off shocker stays where it is, greyed out, and does nothing:
  it stops at once, behaviours skip it, and friends and the web remote no
  longer see it. Remembered across launches.
- **Your avatar menu and OGP agree.** Driving a friend from your avatar's
  Friends submenu (level, mode, speed, range, Override, strength) shows on
  the Friends page as you do it, and a change you make in OGP goes back to
  the menu. When an avatar loads, OGP's values win over the ones VRChat
  replays.
- **"Shocker vibrate".** The menu's shocker Vibrate buttons are now called
  Shocker vibrate, so they don't read as the toys'. Import the new
  **OscGoesPurrr-VRCFury.unitypackage** below to get it; your parameters
  don't change.
- **Find your avatar menu.** Settings → **VRChat menu** shows whether the
  avatar you wear has OGP's menu and links the prefab and its guide; Home's
  Getting started has it as an optional step. Every release now carries the
  prefab.
- **Friends, tidied.** ＋ Add a friend opens as one card with its own + / −.
  A friend with a single toy gets that toy's card instead of an extra "All
  their toys". Sync with others explains itself plainly: you see what the
  others driving that friend see.
- **Smaller things.** OscGoesPurrr and Blise518B in the status bar open the
  project and its author on GitHub. The website's working copy of the app now
  has the Friends, Shockers and My Avatar Remote pages to click through.

**Coming from 0.13 or older?** 0.14.0 brought Friends, the web remote,
Shockers, Avatar Remote and more:
[the 0.14.0 notes](https://github.com/Blise518B/OscGoesPurrr/releases/tag/v0.14.0).

More on the website: https://blise518b.github.io/OscGoesPurrr/
