# Project: OscGoesPurrr — toys-only edition (`release/lite`)

A VRChat OSC → haptic router for Buttplug.io toys via Intiface. Python
3.10+, PySide6 UI, Windows-first, with a Linux AppImage since 2026-10-05
(ARCHITECTURE.md § "Linux" has the few places the code differs).

**This branch is the public, shareable build.** The seven other haptic
backends — SteamVR tracker haptics, bHaptics, PiShock, DG-Lab Coyote,
OWO, The Handy, PSVR2 rumble — live on `main` and are deliberately *not*
here. Don't re-add one on a whim: the point of this branch is a small
surface a stranger can install and understand. If a backend genuinely
needs to come back, follow ARCHITECTURE.md § "How to add a new haptic
backend" and port it from `main` rather than reinventing it.

The one SteamVR piece this branch does carry is display-only: Settings →
"Show toys in SteamVR" (on by default; off takes the driver out of
SteamVR again; a PC without SteamVR is never touched) lists the connected
toys in SteamVR's device strip through the toy driver in
`src/steamvr_toy_driver/`.
They are TrackingReference devices with no valid pose, so they can never
be picked up as trackers — keep it that way (a toy that turned into a
full-body tracker would wreck someone's FBT).

Read [`README.md`](README.md) for the feature overview and
[`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) for the layered design
(sealed engines / stateless routers / controller mixins). The four
anti-tangling rules in ARCHITECTURE.md are load-bearing — don't break
them.

**Low latency is load-bearing too.** This is a real-time haptics router:
minimizing OSC-in → device-out latency is a first-class priority. Don't
add queue hops, fixed delays, or ack-blocking waits to any routing /
engine / dispatch path; prefer direct dispatch, fire-and-forget sends,
fast (~60 Hz) polling, and per-feature send caps for hardware safety.
See ARCHITECTURE.md § "Latency budget" before touching a hot path.

## Layout

The app's code lives in `src/` (flat modules plus the `controllers`,
`settings` and `ui` packages; `main.py` is the entry point). Running
`python src/main.py` puts `src/` on the path, `pytest.ini` does the same
for the tests, and PyInstaller does it for the build — so imports stay
flat (`import motor_router`). Build/release scripts, the Test Bench and
the generators are in `tools/`; the website and technical docs in
`docs/`. Scripts in `tools/` `cd` to the repo root first; `dist\` and
`venv\` stay at the root.

## Versions and releases

`VERSION` in `src/version.py` is hand-set and **must** match the release tag
(`VERSION = "0.9.0"` ships as `v0.9.0`). The in-app update check compares
the running version against the newest tag on
`Blise518B/OscGoesPurrr`, so the two disagreeing means either silent
missed updates or an endless "update available" nag.

To publish: bump `VERSION`, update `tools/RELEASE_NOTES.md` and the in-app
notes in `src/whats_new.py` (the window a user sees once after updating,
with its "Take me there" buttons), commit, run `tools\release.bat`. It runs the tests, builds the exe, then publishes **one
squashed commit** to the `public` remote's `main` — this branch's files,
stacked on the previous public release, authored with the GitHub noreply
address — tags it, and creates the GitHub release with the exe attached.
That attached `.exe` is the asset `updater.pick_exe_asset` looks for; no
asset means no one-click update. It is always uploaded as
`OscGoesPurrr-Windows.exe` — never a versioned name — because the README's
Download button and the website link to
`releases/latest/download/OscGoesPurrr-Windows.exe`.

**The Linux AppImage is built by GitHub, not by release.bat** (Blise's
ask 2026-10-05, "the way VRC Parameter Relay does it"). The public commit
carries `.github/workflows/linux.yml`; the release `release.bat` creates
triggers it, and it runs `tools/build_linux.sh` on Ubuntu 22.04 and
attaches `OscGoesPurrr-Linux-x86_64.AppImage` + `.zsync` to the same
release a few minutes later — again a fixed name, for the README/site
links and `pick_exe_asset` on Linux. The workflow can also be re-run by
hand from the Actions tab with a tag. It builds the engine from the commit
`THIRD_PARTY_NOTICES.md` names with `tools/intiface-engine-Cargo.lock`
(Buttplug commits no lock file; the notices generator copies yours), so
regenerate the notices after every engine rebuild or the two engines
drift apart. The public commit also carries a `Build <n>` line so the
AppImage shows the exe's `b<n>`. To build or test it on this PC, run the
script in an Ubuntu 22.04 container (Docker Desktop is installed) — it
needs the repo copied into the container's own disk, not a Windows bind
mount, or the Rust build crawls.

**Never push this branch itself to `public`.** Its history carries a
personal email on every commit and the full history of the backends this
edition leaves out. The public repo only ever receives the squashed
release commits, and this repo's `user.email` is set to the noreply
address so new commits don't carry the personal one either.

The website (`docs/index.html`, GitHub Pages from `/docs` on the public
`main`) ships with every release, so update it in the same change as the
feature: "What it does" lists only what this branch ships, "Not in this
edition yet" is the roadmap — move an item up when it lands here. Colours
come from `docs/assets/tokens.css` (a copy of `_hub\design\tokens.css`);
never retype a hex. `tools/make_site_images.py` redraws its images from the
icon.

**The site shows the real thing (Blise's rule, 2026-10-04): mostly factual,
a few slogans, no marketing filler and nothing animated for show.** The
window under the headline is a working copy of the app
(`docs/assets/demo.css` + `demo.js`, in the app's own pixel sizes, built
against screenshots of the real UI), and every moving plot on the page is
the app's actual signal chain: `docs/assets/ogp-chain.js` is a port of
`src/motor_router.py` and `ogp-accent.js` of `src/accent_shift.py`, both
checked against the Python number for number (`tools/site_ports/`, and
`tests/test_site_ports.py` fails when a port drifts — it needs `node` and
skips without it). So: change the chain maths, the preset, the stage
cards' summary strings or the colour maths → bring the port along until
that test passes again; change how Home, the chain
editor, Settings → Appearance or Statistics look → bring the demo back in
line and compare it with a fresh render of the app.

**License:** MIT, like the other 518 repos; keep public mentions of it to
one line. Everything the exe bundles keeps its own license, listed in
`THIRD_PARTY_NOTICES.md` — generated by `tools/make_third_party_notices.py`
from the venv and the engine checkout, bundled into the exe, shown from
Help → License. Regenerate it whenever `requirements.txt` changes or the
engine is rebuilt; the tests fail when a dependency is missing from it. The
engine links `evalexpr` (AGPL-3.0), so its notice names the exact Buttplug
commit it was built from — keep that true. The AppImage also carries
Ubuntu system libraries (Qt's X11 ones, GLib, D-Bus …): `build_linux.sh`
appends them to the AppImage's own copy of the notices and packs each
package's copyright file, and it leaves out the ones the system's copy must
win (libstdc++, OpenSSL, fontconfig — see the script).

The self-updater (`updater.py`) only works for a frozen `--onefile`
build on Windows, and for the AppImage on Linux (a `--onedir` build inside;
the AppImage file is what gets swapped). Anything that changes how either
is packaged (a `--onedir` exe, an installer, a renamed asset) needs
`is_self_updatable()` and `pick_exe_asset()` revisited in the same change.

Anything that starts a **new instance** of the one-file exe — the updater's
relaunch, `utilities.relaunch_self()` after a settings restore — must
pass `PYINSTALLER_RESET_ENVIRONMENT=1`
(`utilities.fresh_instance_env()`). Without it the child inherits the
`_PYI_*` variables, reuses the exiting parent's `_MEI` folder and dies on
its first compiled import ("No module named
'pydantic_core._pydantic_core'" — v0.10.0 did exactly that). On Linux the
new instance is started from `$APPIMAGE` (`utilities.running_appimage()`),
never `sys.executable`, whose mount disappears with the old process.

## Cloud sandbox caveat

If you are running in a Linux cloud sandbox (e.g. the mobile Claude
Code app), you **cannot launch the app**. `src/main.py` requires Windows
plus local hardware: Intiface (bundled engine or Intiface Central) for
toys, and OSC traffic from a running VRChat instance. None of that
exists in the sandbox.

What you **can** do in the sandbox:

- Read and edit any source file.
- Run the test suite: `pip install -r requirements-dev.txt && pytest`.
  Tests are pure-Python and do not need hardware.
- Type-check, lint, refactor.
- Commit and push back to GitHub for the user to pull on Windows.

Do not try to invoke `python src/main.py`, `run.bat`, or `tools\build_OGP.bat` in
the sandbox — they will fail and waste time. State the limitation and
hand the work back if a change genuinely needs a live run.

## Running tests

```
pip install -r requirements-dev.txt
pytest
```

`pytest.ini` treats warnings as errors (except a known
`websocket` `DeprecationWarning`). Tests live under `tests/`.

## Commit & PR style

When drafting commit messages and PR descriptions:

- Describe only the code change and the reason for it.
- Do not mention Claude, AI, "generated with", "co-authored", or this
  tool anywhere in the subject, body, or trailers.
- Treat all code as human-authored; the diff and history speak for
  themselves.
- Keep the subject line under ~70 characters; use the body for the
  "why" when it isn't obvious from the diff.
