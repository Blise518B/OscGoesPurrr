# Project: OscGoesPurrr — toys-first edition (`release/lite`)

A VRChat OSC → haptic router for Buttplug.io toys via Intiface. Python
3.10+, PySide6 UI, Windows-first, with a Linux AppImage since 2026-10-05
(ARCHITECTURE.md § "Linux" has the few places the code differs).

**This branch is the public, shareable build.** The other haptic
backends — SteamVR tracker haptics, DG-Lab Coyote, The Handy, PSVR2
rumble — live on `main` and are deliberately *not* here.
Don't re-add one on a whim: the point of this branch is a small surface
a stranger can install and understand. If a backend genuinely needs to
come back, follow ARCHITECTURE.md § "How to add a new haptic backend"
and port it from `main` rather than reinventing it.

**PiShock is the one that came back (2026-09-24, Blise's ask)** — USB
serial only (`pishock_serial.py` / `pishock_engine.py` /
`pishock_router.py`, `controllers/pishock_facade.py`, `ui/views/pishock.py`),
never the cloud API. It sits behind `feature_pishock`, **off by default**,
so a stranger without a shocker never meets the page. The engine is the
last gate before a shock reaches a person: every send goes through it,
shocks are vibrates until armed, and its caps (shocks, and vibrates' own
since 2026-10-23) can't be widened from settings. Keep all of that true.
**Since 2026-10-28 (Blise's calls):** Arm shocks is *remembered* across
launches (it used to reset off every launch -- his reversal, so don't put
it back without asking); each shocker has its own max shock / max vibrate /
longest pulse (`pishock_limits.PER_SHOCKER`; one without takes the hub-wide
value) while rest / longest hold / break stay shared, and a friend's
fraction maps to the shocker it lands on (`st`'s `slim`); the Shockers page
is Avatar Remote's card design -- hub, a card per shocker, behaviour cards
(`ui/views/pishock_cards.py`, `pishock_rules.py`) that take shockers by
dragging a shocker card's ⠿ onto them, several per behaviour, none until
dropped -- with **Touch zones** (several contacts, each its own shockers)
and its switched-off example. Values are sliders with the number written
out, never spin boxes (they were cut off).

**OpenShock joined it (2026-10-07, Blise's ask)**: the same hub link also
speaks OpenShock firmware (`openshock_serial.py` — PiShock's 2023 / Lite
hubs reflashed, or a DIY ESP32 board), picked by whichever firmware
answers the handshake. OpenShock keeps no shocker list over serial, so the
page holds one (model + transmitter id; Beep pairs a collar). The page and
sidebar entry are called **Shockers**; the code, the feature key and
`pishock_settings.json` keep the `pishock` name. Still USB only — no
PiShock or OpenShock cloud API.

**Friends (2026-10-23, Blise's ask)** link two OGPs over the internet so
one can drive the other's toys and shockers (`remote_link.py` /
`remote_protocol.py`, `controllers/friends_facade.py`, `ui/views/friends.py`,
the menu's `OGP/Friend/*`). iroh, peer to peer with n0's free relays as the
fallback — no server of ours. `feature_friends` is on by default, but
nothing goes online until the user sets a nickname; after that the
page's Online switch is remembered, on by default (Blise's call,
2026-10-23 -- not offline at every launch). Keep these true: every
friend has a Toys and a Shockers switch (both on for a new friend —
Blise's call, 2026-10-23: "that's what people wanna do");
a friend's shock goes through `PiShockEngine` like every other (arming,
caps and rest still hold, a friend can never widen them); a friend's level
stays under the receiver's strength, Off and each toy's output band, and
drops to zero when their updates stop; everything a friend does is logged
on the Friends page. Several friends driving one person (Blise's calls,
2026-10-27): each sees "+1 OTHER" (names on hover) for the others driving
right now, and those with **Sync with others** on (per friend, on by
default) share one set of toy cards -- the receiver plays only the newest
change among them, once; Sync off drives on your own (highest wins). It
covers the toy cards only: strength is already the receiver's own slider,
and shocker buttons stay each person's. The identity key is `friends_key.bin`, never a `.json`
(settings backups copy every `.json`), and there is one `RemoteLink` per
process (the iroh bindings keep a single asyncio loop) and one online per
PC (a second OGP window stays offline). Keep the link light on n0's free
relays (Blise's ask, 2026-10-23): no polling offline friends, only changes
on a live link — ARCHITECTURE.md § `remote_link.py`. However many friends
(2026-10-28): your toys' live levels go only to a friend whose page shows
your panel (`lw`), and retries of offline friends share one budget
(`BACKGROUND_GAP_S`), so a long list adds no traffic. Invite links
(once / a day / a week / forever, clickable through `docs/friend.html`;
copied as the link with "(Add Blise on OscGoesPurrr)" on the line under
it, like the web remote's -- never a Discord masked link, his call
2026-10-28: it has to paste into a browser too), unfriending (the other side drops you too) and New ID
(unfriends everyone, kills every link) fold out of the list's one **＋ Add
a friend** button (Blise's call, 2026-10-27: not always on screen; it opens
by itself while you have no friend). **You're always on your own list**
(Blise's calls, 2026-10-27): a working "Me" row, first -- a friend who may
do everything, over a local loop instead of the network
(`controllers/friends_me.py`), with no way to remove it: keep every friend
rule holding for it (Pause all friends, the shockers' switches, caps), and
never name it to real friends. The list's toy / bolt / remote column icons
set that column for every friend (off first while any has it). **Versions
(Blise's ask, 2026-10-27):** each hello says the app's `VERSION`; the first
time in a launch a friend's is newer, you get a window with the way to
update and an amber banner on Friends; an older friend (or one that says
none) gets an OLD tag on their row (`controllers/friends_versions.py`,
`ui/views/friends_update.py`). **A friend's shockers are PiShock's own
panel (Blise's ask, 2026-10-28: "so people who are used to pishock feel at
home"):** its layout, names and choices (`ui/views/shocker_card.py`,
`shocker_parts.py`; Party Mode in `shock_party.py`, `friends_shockers.py`)
-- keep it at parity with docs.pishock.com's Shocker Interface and Party
Mode, and keep its pickers inside the window (a VR overlay capturing the
window doesn't show popup windows).

**The web remote (Blise's ask, 2026-10-28)** is a friend's panel in a
browser, for someone without OGP -- replacing the idea of a Cloudflare
tunnel like VRC Parameter Relay's share. One link per OGP
(`remote.html#<id>.<code>.<nick>`, *Copy web remote link (no OGP needed)*
right under *＋ Add a friend (they need OGP too)* -- never inside its fold,
his call: two separate things; it copies the link on its own line and
"(Drive Blise's toys - …)" under it, never a Discord masked link, so it
pastes straight into a browser too -- the page stops reading at the bracket,
`parseLink` in remote-proto.js, his call 2026-10-28), everyone on it under one **Web remote** row after Me (his
pick: one link, one row -- not a link per person); its panel has Copy, New
link, On, **Toys / Shockers / Avatar** switches for everyone on it, who's
on now with a Kick each, Remove. **The page is 1-to-1 with the app's friend
panel** (his ask, same day): toy cards with every mode, Override, their
strength and Sync with others (`assets/remote-toys.js`), PiShock's panel
per shocker with Party Mode (`assets/remote-shockers.js`), the worn
avatar's board with YOLO (`assets/remote-board.js`), on `assets/remote.js`
and the protocol port `assets/remote-proto.js` -- change the app's panel
or the Friends messages, bring the page along (`tests/test_web_remote.py`
runs the port in node against the Python and fails when they drift). It
runs iroh in WebAssembly (`tools/web_guest`, datagrams and the board's
stream, built by `tools/web_guest/build.py` into `docs/assets/web_guest/`
with its crates' notices), always through n0's relays; OGP lets it in as a
web guest (`controllers/friends_web.py`, `ui/views/friends_web_panel.py`).
Keep these true: toys start on, **shockers and avatar off until ticked**
(his call: anyone with the link gets them); its messages take a friend's
own path, so every friend rule holds (Pause all, Off, strength, output
band, the shocker engine's arming and caps, locked categories, zero when
its updates stop, logged); it is never a friend or a contact (nobody dials
a browser) and **never hears your friends' names** -- who else drives you
reaches it as a count (his call); a dead, replaced or switched-off link is
told `nolink` (never a friend request) and a kicked browser `kicked`, and
stays blocked. The wasm's iroh stays the one the Python bindings carry
(`iroh` 1.2.0 on PyPI is iroh 1.4.1). Building it needs a clang with a
WebAssembly backend (build.py's docstring says where to get one); the page
only works for others once it is on GitHub Pages (a release, or a
page-only commit on the public main when he asks for one).

**Sliders reach both ends (Blise's rule, 2026-10-28):** at the minimum and
the maximum the handle sits right at the end of the track -- no track,
ring or inset showing past it. The sidebar's total-strength bar lets its
ring hang outside the groove for that; a web page styles its range inputs
like the app (`docs/assets/demo.css`), never the browser's own.

**One icon per thing, the same everywhere (Blise's ask, 2026-10-27):**
toys = the capsule in pink, shockers = the bolt in yellow, Avatar Remote =
the remote in the accent green, and since 2026-10-28 Friends = two people
in cyan (as in the VRChat menu's icons) and Suits = the vest in orange --
`ui/icons.identity_icon` (and `ui.widgets.IdentityMark`, which redraws with
the colour picker). A new place that names one of the five uses that icon,
never its own. **Every sidebar entry has an icon (2026-10-28):** the pages
that are no kind of thing (Statistics, the tools, Settings' gear, Help) are
`ui/icons.page_icon` line art in the nav text's tone -- a colour stays the
sign of what something is. What's new items carry the same icons
(`whats_new.Item.icon`).

**Avatar Remote (2026-10-23, a friend's ask through Blise)** is VRC
Parameter Relay's board inside OGP -- the page is called Avatar Remote, the
code, `feature_params` and `param_boards.json` keep the params name (`param_board.py`, `settings/param_boards.py`,
`controllers/params_facade.py`, `ui/views/params.py` + `param_cards.py`),
shared over the Friends link instead of share links and a browser
(`remote_params.py`, `controllers/friends_params.py`,
`ui/views/friends_board.py`). `feature_params`, **off by default**. Keep
these true (Blise's calls): every friend has a third switch (AVATAR in the list),
**on** for a new friend; a friend sees your **worn** avatar's active
preset, never the one open for offline editing; **one** ⚡ YOLO switch for
everyone, asked before it goes on; a locked category is look-only for
friends; Pause all friends blocks every set and lets go of held buttons
(the page's own ■ STOP was removed, Blise's call 2026-10-27 -- each
friend's AVATAR switch and Pause cover it); a held button is let go when the holder's updates stop; nothing
is sent until a friend has your board open (the board over a stream once
and on change, then only changed values). Import from VRC Parameter Relay
reads its `avatars/*.json`, never writes them.

**The bHaptics and OWO suits came back together (2026-10-23, Blise's
ask)** on one **Suits** page, because they share the avatar's body
contacts: `body_map.py` reads every input (the bHaptics package
`bOSC/v2[m]/…/self|others`, older bHapticsOSC keys, the OWO package
`owo_suit_<Muscle>`, zone routes) into one body, `suits_router.py` feeds
both engines from it, `controllers/suits_facade.py`, `ui/views/suits.py`
+ `body_view.py`, `suits_settings.json`. Each suit has its own switch,
`feature_bhaptics` / `feature_owo`, **off by default**; the page shows
while either is on. **Hidden for 0.14.0 (Blise's call, 2026-10-28: ship
Friends, Avatar Remote and the shockers without them):**
`main.OscGoesPurrrApp.FEATURES_NOT_YET` keeps both switches off whatever
was saved and out of Settings and "What are you here for?", so the page,
Home's suit rows and the engines never come up; README and the site list
them under "Not in this edition yet". Bringing them back = emptying that
set, plus the README / site / What's new lines, in a release of their own. Contacts are shared both ways by default (Blise's
call) — each suit's "follows" switch turns that off. **The page is a body
(Blise's ask, 2026-10-28: "not just a bunch of list"):** a cat girl's
front and back ("since OGP purrs") with every bHaptics motor an orange dot
and OWO's muscles purple patches around them (`theme.BHAPTICS_HUE` /
`OWO_HUE`); a click sets the part / muscle up in the inspector beside her
(`suits_cards.py`), values are sliders, and only the bHaptics parts you
have show (**You have**, `body_map.PART_GROUPS`, a vest by default; a part
that newly connects ticks itself -- his ask, same day). A click on her opens
that thing's card beside her with a line to it (empty space closes it), and
each card says whether the worn avatar has its contacts: read from VRChat's
own list of the avatar's parameters (`vrchat_avatars.avatar_parameters`),
dashed amber rings on her for what's missing. **Vive tracker haptics will
come back** (his words, 2026-10-28): the page already draws their pucks in
blue (`body_view.TRACKERS`) and opens their card, but only once
`get_suits_status()` reports trackers -- nothing in this build does until
they're ported from main. She's ChatGPT-drawn line art
(`src/Images/suits`, from `tools/make_suit_figure.py`), tinted in the accent
at paint time -- never hand-drawn SVG people (he found those creepy). Every
dot is placed in the drawing's own pixels (`body_view.PLACES`), so new
drawings mean re-checking the dots. Keep these true:
* **bHaptics** talks Bluetooth itself (`bleak`, `bhaptics_ble.py` /
  `bhaptics_engine.py` / `bhaptics_models.py`) — never through the
  bHaptics Player, which must be closed (one connection per suit; Let go
  hands it back). A frame nobody re-submits for 250 ms goes to zero, and
  stop / release / Off write zero twice. **The frame depends on the
  model (2026-10-28):** the TactSuit Pro and Air take the Player's own
  32-motor frame — 40 bytes, one per motor, on `6e400014`, read off the
  Player's logs of Blise's suits — and a Pro fed the old X40 frame on
  `6e40000a` buzzes the wrong motors (his bug report). Older vests keep the
  X40 frame, sleeves / head / hands / feet their byte-per-motor one. A
  model is `verified` once pressing dots on the Suits page lands on the
  right motors (the logs settle the grid, not which side is the wearer's
  left); `tools/bhaptics_probe.py walk --interactive` measures it slot by slot.
* **OWO** goes through the My OWO app only (`owo_link.py`: its UDP
  protocol spoken natively, pinned against a capture of OWO's SDK —
  `tools/owo_udp_capture.py` — never `OWO.dll` / pythonnet). It's EMS:
  `owo_engine.py` is the last gate like the shocker engine — ceilings
  can't be widened from settings (100 % = the user's calibrated max in My
  OWO, overall ceiling starts at 60 %), Stop refuses every send, Off /
  feature off / VRChat quiet / exit send a stop twice, never the
  OGP/Test floor, auto-connect off by default, and the page's spin boxes
  ignore a scroll wheel that passes over them.
* Going **native over Bluetooth for OWO** is a separate research track
  (`tools/owo_ble/`, its own NOTES.md); it may only replace the My OWO path
  once the protocol is understood, with calibration and caps inside OGP.
* The vendors' protocols are unpublished and every reference
  implementation is GPL / LGPL: learn from them, never copy their code.

The one SteamVR piece this branch does carry is display-only: Settings →
"Show toys in SteamVR" (on by default; off takes the driver out of
SteamVR again; a PC without SteamVR is never touched) lists the connected
toys in SteamVR's device strip through the toy driver in
`src/steamvr_toy_driver/`.
They are TrackingReference devices with no valid pose, so they can never
be picked up as trackers — keep it that way (a toy that turned into a
full-body tracker would wreck someone's FBT).

**The bundled engine never takes a Bluetooth serial device for a toy
(2026-10-24, Blise's OK).** Buttplug's Lovense entry also matched on the
Nordic UART Service alone, so the engine connected to every MeshCore
radio, Espruino watch or ESP32 serial bridge in range, sent `DeviceType;`
and retried on every scan. OGP starts the engine with
`src/intiface-engine/buttplug-device-config-v4.json`, which is Buttplug's
list minus that one match, written by `tools/make_engine_device_config.py`
(tracked, bundled into both builds). It replaces the engine's built-in list, so
regenerate it after every engine rebuild (`rebuild_intiface_engine.bat`
does). `tests/test_engine_device_config.py` fails while it and the checkout
differ. Never hand-edit it, and don't patch the engine itself: the notices
promise an unmodified build. External mode (Intiface Central) keeps
Intiface's own list.

Read [`README.md`](README.md) for the feature overview and
[`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) for the layered design
(sealed engines / stateless routers / controller mixins). The four
anti-tangling rules in ARCHITECTURE.md are load-bearing — don't break
them.

**The scroll wheel never changes a setting (Blise's rule, 2026-10-27).**
Over any spin box, slider, dropdown or tab bar it scrolls the page instead,
even on a control just clicked -- one app-wide filter, `src/ui/wheel_guard.py`,
installed in `ui_components`, so new settings need nothing of their own (and
must not take the wheel back; a control that truly should, sets the
`wheelAdjusts` property). `tests/test_wheel_guard.py` pins it.

**Show me around -- help mode (Blise's ask, 2026-10-28).** F1, the status
bar's *Show me around* or a Help tile's *Show me* explains the page on
screen on the page itself (`ui/help_mode.py`, wired in by
`ui/views/help.py`): the page's steps from `ui/page_steps.py` on a strip
above it, and whatever the pointer rests on lit up with its hover
explanation's title and first sentence -- as little text as possible, so
an explanation's first sentence has to stand on its own. Clicks do nothing
while it is on (the sidebar's pages excepted), so looking around never
changes a setting. The steps are shared with the VRChat group gallery
(`tools/make_vrc_group_images.py`, real screenshots by `tools/app_shots.py`
on demo data), which stops when a step's control is gone -- change a page,
bring its steps along. The Help page opens with a tile per page; the long
manual is folded under *Every part in detail*.

**"What are you here for?" (Blise's ask, 2026-10-27)** picks the features
someone uses: a new install asks it at its first launch, an older one once
on the update that brings it, then never again by itself (Settings →
Features → *Choose what you use…*). Each choice is a feature switch
(`src/interests.py`); it starts from the switches as they are, so nobody
loses one they use, and Skip changes nothing. A new feature switch gets a
choice there too -- `tests/test_interests.py` fails without one. Features
is the first card in Settings.

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

A pre-release carries its stage in `VERSION` (`"0.14.0-alpha.1"`, `-beta.N`,
`-rc.N` → tag `v0.14.0-alpha.1`); release.bat publishes any version with a
`-` as a GitHub **pre-release**, which GitHub's "latest" (the updater, the
Download button) skips, and `update_checker.compare_versions` orders it
before its release so an alpha copy is offered the final one.

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
regenerate the notices (and the engine's device list) after every engine
rebuild or the two engines drift apart. The public commit also carries a `Build <n>` line so the
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

**The VRCFury menu prefabs** (`docs/unity/OscGoesPurrr-VRCFury.unitypackage`,
Option A in `docs/VRCHAT_MENU.md`, linked from the site and the Friends
page) are built, never edited by hand -- three in one package (Blise's call,
2026-10-23): *OscGoesPurrr Menu* (own controls + Friends ▸), *(Self)* and
*(Friends)*. Their icons are drawn by `tools/make_menu_icons.py` into
`docs/unity/icons/` in Blise's "Flat" style (white line art, the app's hues
for toys / shockers / friends / you); change an icon there, never by hand.
To build them, `tools/build_vrcf_prefab.py "<avatar project>"` runs
`tools/unity/OgpVrcfPrefabBuilder.cs` headless in a Unity project with the
VRChat SDK and VRCFury (closed in Unity; `C:\VR\AVI_Projects\BaseV7 - Claude
analysis` is the scratch one), exports the package, imports it back and runs
VRChat's upload preprocess on test avatars; the committed package is only
replaced when that passes (~3 min). Its menu and parameters come from
`docs/unity/OGP_MenuInstaller.cs`, so change them there and rebuild —
`tests/test_vrcf_prefab.py` fails when the package and the app's `OGP/*`
parameters disagree. Everything in it lands in `Assets/OGP` (Blise's call,
2026-10-22) — our own top-level folder, nothing outside it — with only the
prefab at its top and the menus, parameters and icon in `Assets/OGP/Menu`.
Two things must stay: `OGP/*` in the Full Controller's
global params (VRCFury renames every other parameter, and OSC reaches one
by name only), and the pinned GUIDs (with fresh ones, importing a newer
package duplicates every asset instead of updating it).

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
