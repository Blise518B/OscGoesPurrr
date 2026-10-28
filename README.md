# OscGoesPurrr 🐾

**All your VRChat haptics, in one app.**

OscGoesPurrr reads the contacts on your avatar and turns every touch into
smooth, real-time output on your Bluetooth toys — Lovense, We-Vibe, Kiiroo
and anything else [Buttplug.io](https://buttplug.io/) supports — and, if
you have them, on PiShock / OpenShock shockers.
Friends can drive them over the internet.

<p align="center">
  <a href="https://github.com/Blise518B/OscGoesPurrr/releases/latest/download/OscGoesPurrr-Windows.exe">
    <img src="docs/assets/download-badge.svg" alt="Download for Windows — OscGoesPurrr-Windows.exe, latest release">
  </a><br>
  <sub>On Linux? Get the <a href="https://github.com/Blise518B/OscGoesPurrr/releases/latest/download/OscGoesPurrr-Linux-x86_64.AppImage">AppImage</a> ·
  OGP in your avatar's menu: the <a href="#your-avatars-menu-optional">VRCFury prefab</a> ·
  more on the <a href="https://blise518b.github.io/OscGoesPurrr/">website</a> ·
  every version on the <a href="https://github.com/Blise518B/OscGoesPurrr/releases">Releases</a> page</sub>
</p>

## Getting started

1. **Download and run it.** One file, nothing to install — Intiface is
   built in.
2. Windows shows a blue *"Windows protected your PC"* box the first time
   (the exe isn't code-signed). Click **More info → Run anyway**.
3. **Tick what you'll use.** The app asks once what you have and want —
   toys, a shocker, friends … — and shows those pages. Settings →
   Features changes it later.
4. **Switch your toy on** and start VRChat with **OSC enabled**
   (Action menu → Options → OSC).
5. Press **Test all** on the Home page. If you feel it, you're set.

You'll need an avatar with **OGB / SPS contacts** — the standard toy setup.
New versions install themselves: the app lets you know when there's one.

**On Linux** it's one AppImage: make it executable (`chmod +x`, or
*Allow executing* in its Properties) and run it. Bluetooth needs BlueZ
running, which it is on most desktops.

## Your avatar's menu (optional)

OGP's controls can live in your avatar's own menu too, so you never leave
VRChat: strength, Off, Sleep, Test and the modes, and a **Friends** submenu
that drives whoever you picked in OGP — their toys, their shockers, or both
of you at once.

1. Download
   **[OscGoesPurrr-VRCFury.unitypackage](https://github.com/Blise518B/OscGoesPurrr/releases/latest/download/OscGoesPurrr-VRCFury.unitypackage)**
   and import it into your avatar's Unity project (it needs
   [VRCFury](https://vrcfury.com)).
2. Drag **one** of its prefabs onto your avatar: **OscGoesPurrr Menu**
   (everything), **(Self)** (only your own controls) or **(Friends)** (only
   the Friends submenu).
3. Upload. VRCFury adds the menu and the parameters (unsynced, 0 sync bits);
   your avatar's own menu files stay untouched.

OGP says on its Friends page whether the avatar you're wearing has the menu.
No VRCFury? The [setup guide](docs/VRCHAT_MENU.md) has a one-click installer
and the manual way.

## What you get

- 🔌 **Just works** — finds VRChat and your toys by itself. No IPs, no ports.
  A chime tells you when a toy connects or drops.
- 🎚️ **One strength bar** — turn everything up or down without touching
  your tuning.
- 💤 **Off and Sleep** — instant silence, or only wake for real strokes.
- 🔀 **Four routing modes** — pick which parts of your avatar drive which
  toy.
- 🎮 **Control it in-game** — strength, mode, Off and Sleep from your
  avatar's menu, and your friends' toys and shockers — one or several at
  once, or both of you together — from its Friends submenu: drag one
  VRCFury prefab onto your avatar ([see above](#your-avatars-menu-optional)).
  OGP tells you when your avatar has it.
- 🤝 **Friends** — link with other OGP users over the internet: paste an
  invite link into Discord, your friend clicks it and you're linked (a
  link works once, for a day, a week or until you close it; New ID
  unfriends everyone if one gets around). A friend can drive your toys —
  by hand, with an auto mode (sine, square, random, heartbeat, build-up,
  oscillate…)
  or overriding what your avatar does — move your strength slider and
  use your shockers from a small PiShock-style panel each (shock, vibrate,
  beep, hold, a warning first, stop), or all of it big in Control mode for
  VR — only what you switch on for them, every friend you
  allow at once, all of it logged. No account and no server: the two PCs
  talk directly. Your strength, Off, each toy's maximum and your shocker
  caps and arming still hold. No OGP on their side? Share your **web
  remote** link instead: whoever opens it gets a friend's whole panel in
  their browser -- your toys, and your shockers and avatar's board once
  you tick them -- everyone on it under one row you can switch off, kick
  from or replace with a new link.
- 🎛️ **Avatar Remote** — VRC Parameter Relay's board, built in: toggles,
  hold buttons, sliders and steppers for your avatar's parameters,
  dragged into coloured categories, per avatar and per preset (an Int can
  be several toggles, Outfit = 1, 2, 3, like VRChat's menu). Friends you
  allow see the board of the avatar you wear under your toys on their
  Friends page and can use it — lock a category to make it look-only,
  ⚡ YOLO hands them every parameter, Pause all friends blocks them all. Over the same
  direct link as everything else; nothing is sent until a friend looks.
  Boards made in VRC Parameter Relay import with one click. Off until you
  switch it on in Settings → Features.
- 🎯 **Feels right** — a signal chain per contact, so each toy feels like
  *that* toy.
- 📈 **Every session, charted** — click a session for its timeline: each
  toy's intensity, thrusts per minute, which zones were touched, and your
  hottest five minutes. Plus lifetime fun facts, a when-you-play heatmap
  and a month calendar. It all stays on your PC: one switch in Settings
  turns it off (keeping what's recorded), one button deletes it.
- 👥 **Stats per person** — tag who a session was with, the whole of it or
  a stretch dragged out on its timeline, and the People card ranks
  everyone by thrusts. Optionally the app tags it for you while you're
  alone in an instance with one other person (read from VRChat's own log).
- 🔢 **Thrust counters on your avatar** — the lifetime total, this
  session's count and the live pace per minute as Int parameters, digit
  by digit, for a counter display ([parameter list](docs/VRCHAT_MENU.md#thrust-counters-for-a-counter-display)).
- 💡 **Explains itself** — hover over anything in the app to see what it
  does. Press F1 (or *Show me around*) on any page for its steps on top,
  with whatever you point at lit up and named.
- 🎨 **Any colour you like** — one slider in Settings turns the whole app
  from green to the colour you pick, in a Vibrant or a Darker look. Both
  change while you watch.
- 🔋 **Toys in SteamVR** — your toys show up in SteamVR's device list
  with their battery. Just for show, never trackers; one switch in
  Settings turns it off. Windows only for now.
- ⚡ **PiShock / OpenShock over USB** — continuous, contact and impact
  rules straight down the cable, no account needed. Works with PiShock's
  own firmware and with OpenShock (a reflashed PiShock hub or a DIY ESP32
  board with CaiXianlin / Petrainer collars). Off until you switch it on
  in Settings → Features, and shocks stay vibrates until you arm them.

## Coming later

bHaptics and OWO suits, SteamVR trackers, DG-Lab Coyote e-stim and The
Handy are in the works.
See the [roadmap](https://blise518b.github.io/OscGoesPurrr/#roadmap).

## For developers

```bash
pip install -r requirements.txt -c constraints.txt
python src/main.py
```

Or just double-click `run.bat`. Tests: `pip install -r requirements-dev.txt`
then `pytest`. The code lives in `src/`, build and release scripts in
`tools/`, and how it all fits together in
[`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).

## License

[MIT](LICENSE). It also uses other open-source projects, each under its
own license ([list](THIRD_PARTY_NOTICES.md)).

<sub>Built with the help of AI.</sub>
