# OscGoesPurrr 🐾

**Your VRChat avatar's touches, on your toys.**

OscGoesPurrr reads the contacts on your avatar and turns every touch into
smooth, real-time output on your Bluetooth toys — Lovense, We-Vibe, Kiiroo
and anything else [Buttplug.io](https://buttplug.io/) supports.

<p align="center">
  <a href="https://github.com/Blise518B/OscGoesPurrr/releases/latest/download/OscGoesPurrr-Windows.exe">
    <img src="docs/assets/download-badge.svg" alt="Download for Windows — OscGoesPurrr-Windows.exe, latest release">
  </a><br>
  <sub>More on the <a href="https://blise518b.github.io/OscGoesPurrr/">website</a> ·
  every version on the <a href="https://github.com/Blise518B/OscGoesPurrr/releases">Releases</a> page</sub>
</p>

## Getting started

1. **Download and run it.** One file, nothing to install — Intiface is
   built in.
2. Windows shows a blue *"Windows protected your PC"* box the first time
   (the exe isn't code-signed). Click **More info → Run anyway**.
3. **Switch your toy on** and start VRChat with **OSC enabled**
   (Action menu → Options → OSC).
4. Press **Test all** on the Overview. If you feel it, you're set.

You'll need an avatar with **OGB / SPS contacts** — the standard toy setup.
New versions install themselves: the app lets you know when there's one.

## What you get

- 🔌 **Just works** — finds VRChat and your toys by itself. No IPs, no ports.
- 🎚️ **One strength bar** — turn everything up or down without touching
  your tuning.
- 💤 **Off and Sleep** — instant silence, or only wake for real strokes.
- 🔀 **Four routing modes** — pick which parts of your avatar drive which
  toy.
- 🎮 **Control it in-game** — strength, mode, Off and Sleep from your
  avatar's menu ([setup guide](docs/VRCHAT_MENU.md)).
- 🎯 **Feels right** — a signal chain per contact, so each toy feels like
  *that* toy.
- 💡 **Explains itself** — hover over anything in the app to see what it
  does.

## Coming later

SteamVR trackers, bHaptics and OWO suits, e-stim and The Handy are in the
works. See the [roadmap](https://blise518b.github.io/OscGoesPurrr/#roadmap).

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
