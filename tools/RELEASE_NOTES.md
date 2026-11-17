**New: [the user guide](https://blise518b.github.io/OscGoesPurrr/guide/)** — every page of OscGoesPurrr in
detail, with pictures and a search.

## Install

**Windows:** download **[OscGoesPurrr-Windows.exe](https://github.com/Blise518B/OscGoesPurrr/releases/latest/download/OscGoesPurrr-Windows.exe)**
below and run it. That's the whole install — one file, no setup wizard, no
Python, no separate Intiface Central. Windows will show a blue "Windows
protected your PC" box the first time, because the exe isn't code-signed (a
certificate costs a few hundred a year). Click **More info → Run anyway**.

**Linux (x86_64):** download **[OscGoesPurrr-Linux-x86_64.AppImage](https://github.com/Blise518B/OscGoesPurrr/releases/latest/download/OscGoesPurrr-Linux-x86_64.AppImage)**
below, make it executable (`chmod +x`, or *Allow executing* in its
Properties) and run it. It's built by GitHub a few minutes after this release
appears.

**Your avatar's menu (optional):** **[OscGoesPurrr-VRCFury.unitypackage](https://github.com/Blise518B/OscGoesPurrr/releases/latest/download/OscGoesPurrr-VRCFury.unitypackage)**
below puts OGP's controls into your avatar's own menu: strength, Off, Sleep,
modes, Avatar Remote's toggles and radials, and a Friends submenu to drive
whoever you picked in OGP. Import it into your avatar's Unity project (it
needs VRCFury), drag one of its three prefabs onto your avatar and upload.
[Setup guide](https://github.com/Blise518B/OscGoesPurrr/blob/main/docs/VRCHAT_MENU.md).
**It hasn't changed since 0.15.0:** if you imported that one, there's
nothing to do — the new Height box goes into one of the Avatar Remote
radials it already has.

Already running an older version? Don't download anything — it'll offer the
update itself at launch.

## What's new

<!-- Replace this section before each release. Keep it short and concrete:
     what changed, and what a user would notice. -->

Built from friends' reviews: toys get a page of their own, the shockers get
a switch per action, friends can be tied to their VRChat accounts, and a guided tour, Ctrl+Z and *Off while you're away* work
across the app. New guide: https://blise518b.github.io/OscGoesPurrr/guide/

**Highlights**

- **Toys have a page of their own**, and Home is the overview of every
  device, with four chips per toy for who it feels.
- **A guided tour** on the first launch, and any time from Help.
- **Ctrl+Z / Ctrl+Y** undo and redo your last five changes, on any page.
- **Off while you're away:** everything holds off while VRChat says you're
  AFK. On by default.
- **Shock, Vibrate and Beep switch off per shocker**, for your behaviours
  and every friend alike.
- **ShockOSC avatars set up in one click**, plus a new **Pull** behaviour.
- **Friends linked to their VRChat accounts**, and an option to let only
  friends in your instance drive you.
- **Height on the Avatar Remote**, for you and the friends you allow.
- **A Log page** of who did what, and **Statistics for every shock**.
- **PSVR2 headset rumble**, on Windows, and **trackers that vibrate**
  (Haptic Pancake, Tundra Tapper).
- **Toys react faster:** about 3 ms from VRChat to the toy instead of 15.

**Safety, plainly.** A shock is a vibrate until you arm shocks, and arming
asks first, wherever you do it. Every friend gets each shocker's own limits
from the Shockers page, an avatar's ShockOSC settings only ever make them
stricter, never looser, and a Ctrl+Z that would loosen one asks first. An
action you switched off never fires, whoever sends it.

### Toys and Home

- **The Toys page**, under Friends in the sidebar: each toy's card with
  its signal chains, Scan now and when it looks next, the toy server's
  status (built in, or your Intiface Central and where), SPS Sources (no
  longer a page under Tools) and the tuning tools. **Home** shows every
  device at a glance — each toy, the shocker hub, the suits, the headset —
  with its quick switches and Test all. Click a toy's row to open its card on
  the Toys page. None of your settings change.
- **Who a toy feels.** Each toy's row has four chips — Touch from yourself,
  Touch from others, Penetration from yourself, Penetration from others —
  that set every chain of the toy in the mode you're in (half lit while its
  chains disagree; a click makes them agree). They're four separate choices
  now, so a toy can take touch from you and penetration only from others;
  each chain's Input stage has the same four. Your settings carry over
  exactly, and a copy of the old `modes.json` is kept beside it.
- **Sleep and anti-stuck, per toy and per device.** Each toy's row has two
  more chips beside Touch and Penetration: **Sleep** puts just that toy to
  sleep (three full strokes wake it, as with the sidebar's Sleep, which
  still sleeps them all), and **Anti-stuck** can leave one toy out of the
  cutoff that stops a frozen contact. Anti-stuck itself is now per device:
  the toys' is on the Toys page, each suit's and the trackers' on the Suits
  page, the headset's on the PSVR2 page, each with its own timers. They
  start with the settings you had. Settings' Toy Safety card is now
  **Safety**, with Off while you're away and a button to each.
- **A tidier parameter picker.** Wherever you pick a parameter, the
  well-known ones you'd never map hide behind chips: VRChat's own, GoGo
  Loco, face tracking, VRCFury internals, physics assets, PhysBone states,
  OGP's own and SPS. VRCFury toggles stay listed until you click their chip.
  A parameter you already use is never hidden, a search still finds the
  hidden ones (under *Hidden by filters*), and *Show everything* lifts the
  lot. The Shockers' picker lists ShockOSC's parameters first and keeps
  PhysBone states.
- **Faster.** OGP's toy engine now sends each change the moment it comes,
  and the routing beat keeps time; Windows had stretched both waits to its
  15.6 ms clock step.

### Across the app

- **Guided tour.** A new install gets it right after "What are you here
  for?"; an updated one is offered it once. It lights what to click, one
  real step at a time — your toy on Home, its card, Select Zones (your SPS
  sources), the chips, Test and total strength, the avatar menu — then a
  short part for each thing you use (shockers, friends, Avatar Remote,
  suits, the headset). It waits for you to do each step, lets you skip any,
  and never changes a setting by itself. *Help → Take the tour* or Getting
  started runs it again.
- **Ctrl+Z / Ctrl+Y.** One history of your last five changes, for the whole
  app: toys' chains and modes, the Shockers page, Avatar Remote boards,
  friends and groups, Settings. The status bar says what was undone. Only
  your own changes count — a friend, your avatar's menu or OSC moving
  something is never a step — and nothing that already happened is undone
  (a shock, a toy's level, a message). An undo that would arm shocks,
  switch a shocker or an action back on, widen what a friend may do or
  raise a limit asks first, as doing it by hand would.
- **Off while you're away** (Settings → Safety, on by default). While
  VRChat says you're AFK — its own AFK, or GoGo Loco's AFK button — or a
  parameter you picked is on, everything holds off: toys, shockers, suits,
  trackers, the headset and every friend's drive. It's the same Off as
  `OGP/Off`, held for you, so your own Off switch isn't touched and it all
  comes back by itself. The status bar says why ("AFK: everything off").
  It holds only while VRChat runs: closing VRChat lets go.
- **"It's connected" for every device.** Besides the toys, the shockers (any,
  and each one), the bHaptics suit and each of its parts, the OWO suit and
  the headset now tell your avatar while they're connected, each as a Bool.
  All are on by default now, the toys' too, under fixed names an avatar can
  be built against (`OGP/ToyConnected`, `OGP/ShockerConnected`,
  `OGP/BHapticsConnected` …); rename or switch each off where its device is
  set up.
- The version in the status bar links to OGP's GitHub page, like its name,
  and every row in Settings → Features has its page's icon.

### Shockers

- **Shock, Vibrate and Beep, each its own switch** (*Allowed* on each
  shocker card). One switched off never fires on that shocker, whoever sends
  it — your behaviours, friends, the web remote, your avatar's menu — and
  switching it off stops it at once. It never turns into a vibrate instead.
  A behaviour using it greys that shocker's chip.
- **Friends see what they can't do, and why.** On their panel, in Party Mode
  and on the web remote, an action you switched off is greyed, with the
  reason under the shocker's name ("Shock is switched off on their side").
  Where no warning can play — Vibrate and Beep both off — Warning is greyed.
  Anything that still arrives is held back and logged.
- **Arm shocks on Home.** Home's shocker row has Arm shocks, Share with
  friends and On; the Shockers page has the same switches, so flipping one
  flips both. Arming asks first in both places — "Arm shocks? Yes / No" in
  the switch's place, off again after 5 s without an answer — and red words
  beside it always say *Shocks armed* or *Shocks not armed*. Hover any of
  them for how they stack: On → Arm shocks → Share with friends → each
  friend's own Shockers switch.
- **Limits read as limits.** A shocker's and the hub's sliders sit under
  *Limits*, each "Up to …" (or "At least a rest of", "Then a forced break
  of"), with "Nothing is sent from here"; the Test buttons are set apart.
- **Several people on one shocker.** When you, a friend and someone on your
  web remote hold one shocker at once, the strongest hold plays steadily — a
  shock always beats a vibrate, a vibrate a beep — instead of flipping
  between them, and one letting go no longer cuts the others for a moment.
  Caps, arming, the longest hold and the rest after it count for all of
  them together (unless Separate limits for friends, below, is on).
- **A shock takes over.** A shock always takes over a running vibrate or
  beep on that shocker, whatever their strengths, and a vibrate a beep. Your
  own behaviours pick among themselves the same way, kind first, then
  strength; a shock that isn't armed counts as the vibrate it becomes.
- **The rests hold for everyone.** The rest after a pulse and the forced
  break after the longest hold now apply to friends, the web remote and your
  avatar alike, and a hold waits until a pulse and its rest are over. Pulses
  taking over one another never run longer together than one longest pulse.
- **Separate limits for friends** (off by default; a switch in the *Every
  shocker* card's Limits). On, friends — Me and the web remote too — get
  limits of their own: *Up to* a shock strength, vibrate strength and pulse
  that only ever lower each shocker's own for them, and a rest, longest hold
  and forced break counted apart from your avatar's, so a friend's long hold
  never holds back your contact shocks. Your avatar keeps each shocker's
  own. Friends' panels show the caps they get. It starts as a copy of your
  current values, so switching it on changes nothing until you move one.
- **ShockOSC avatars.** An avatar set up for ShockOSC (OpenShock's VRChat
  app) gets a card on the Shockers page, and one click sets up its groups:
  a touch becomes a Contact that shocks after 0.25 s, as in ShockOSC; the
  instant ones a Contact that pulses once; the continuous ones a
  Continuous; a PhysBone a Pull — each on the shocker with its group's name,
  or one you drop on it. OGP sends ShockOSC's feedback parameters (Active,
  Cooldown, Intensity …), so the avatar's lights and countdowns follow what
  your shockers really do. The avatar's own ShockOSC settings only ever make
  things gentler: less strength, shorter, a longer rest, or Paused.
- **New behaviour: Pull**, for any PhysBone: something while it's held, and
  one pulse when it's let go, the harder the pull the stronger.
- **Contact: Touch for at least** — a brush shorter than that does nothing.

### Friends

- **Link a friend to their VRChat account** in their panel's new *VRChat
  account* field: pick from the people in your instance (switch on *Read
  VRChat's log* under your friends list) or from your VRChat friends in VRCX
  (*Import from VRCX*), or drag someone from *In your VRChat instance* onto
  their row. Their VRChat name shows under their nickname, with "in your
  instance" while they are. The link stays on your PC, kept by their VRChat
  user id so a new display name doesn't break it, and is never sent to them
  or anyone. VRCX's file is only read, only when you click.
- **Only friends in my instance** (off by default): only friends whose
  linked account is in your VRChat instance right now may drive you. It's
  checked against your own log, so your location never leaves your PC.
  Anyone else shows "not here", is refused like Pause (back to zero at once
  if they leave mid-drive) and is logged; their panel says *Not here*. An
  unlinked friend counts as not here, your own Me row always counts, and a
  friend can be allowed from anywhere. The web remote is kept out too,
  unless its *Allow the web remote anyway* is on. With *Read VRChat's log*
  off, nobody counts as here.
- **Pop out.** A friend's or a group's control panel, big as in Control
  mode, in a window of its own, so a VR overlay (XSOverlay, OVR Toolkit,
  Desktop+) can show just that. It follows whoever you pick on the Friends
  page, keeps working with OGP's main window minimized or in the tray,
  remembers its size and place, can stay on top, and opens no popup window.
  Close it, or press *Back into the page*, and the panel goes back.
- **Check now.** A friend who shows offline has a ↻ on their row, and the
  list has ↻ *Check all*: both look for them right now instead of waiting
  for OGP's next look in the background. Each friend is looked for at most
  once every 10 seconds, however often you click, to keep the link light.
- **OpenShock's buttons, and Live control.** *Shocker buttons: PiShock |
  OpenShock*, at the top of a friend's shockers, swaps PiShock's panel for
  OpenShock's card — on every friend's panel, your own row's and a group's:
  Intensity and Duration dials, Sound / Vibrate / Shock, and LIVE for Live
  control, where the strength follows your finger on a pad until you let
  go. PiShock's panel stays the default, OGP remembers your pick, and the
  web remote has the same switch. Only the buttons change: the same press
  sends the same thing, and their limits, arming and switches decide what
  arrives. Live control holds the shocker like Remote mode, so their longest
  hold and the rest after it still apply.
- **A log per person.** The Friends page's log can show one row per person —
  what they did last and how long ago — and a click unfolds what they did,
  shocks standing out.
- **Sync with others is yours to choose.** One switch on your Friends page,
  *Sync friends* next to *Pause all*, decides whether everyone driving your
  toys — friends, the web remote and you — shares one set of toy cards (the
  default) or each drives on their own. It's no longer on each friend's
  panel: theirs says SYNCED or SEPARATE beside +1 OTHER.
- **The newest change, decided on your side.** Your OGP decides which change
  to the shared toy cards is the newest, so a modified app can't keep them
  by claiming to be newer, and a friend whose cards were a moment behind no
  longer undoes someone else's change. How fast anyone may change your toy
  cards is limited too — far above what OGP or the web remote send while you
  drag a slider — and stopping a toy is never held back.
- **A modified app gains nothing.** Whatever a friend's OGP, a browser on
  your web remote or your avatar's menu sends that OGP itself never would
  is corrected to your limits when it arrives, or refused and logged.
- What a friend sees of all this — greyed actions and why, *Not here*, your
  Height box — needs 0.16.0 on their side too. An older OGP just doesn't
  show it, and your side still refuses whatever isn't allowed.

### Avatar Remote

- **Height.** A Height box under your categories: your height in VRChat
  right now, one slider between your lowest and highest, *Grow* (glides
  there), *Right away* (jumps) and *Reset*. Behind its ⋯, the range — VRChat's
  own menu range (0.2–5 m) out of the box, never past 0.1–100 m, which a
  friend can't widen — and how fast Grow goes. Friends with your AVATAR
  switch on, and the web remote, get the same box; its own switch takes it
  away from them, and a lock makes it look-only. Your height stays where
  they put it. One of your avatar menu's radials can drive it. While a world
  doesn't allow scaling, the box greys and says so.
- **Drag a control back to the list** to remove it: it goes at once, with an
  Undo; a whole category asks first. Ctrl+Z takes it back too.

### Records

- **A Log page**, after Statistics in the sidebar while Friends or the
  Shockers are on: who did what, kept for 30
  days, filtered by person, by kind (toys, shocks, Avatar Remote, the link,
  switches) and by time, with a search and a Clear button. Your own
  avatar's shocker behaviours are in it as *Your avatar*, and one pick hides
  them. Where OGP sent less than was asked, a muted line under the entry says
  what went out and why ("Cut to 1.0 s: your longest pulse"). It stays on
  your PC and is never sent to anyone.
- **Statistics for everything.** A new *From whom* card counts every shock,
  vibrate and beep that reached your shockers — how many, the strongest, how
  long — per shocker and per person: your avatar's behaviours one by one,
  what you sent from your avatar's menu or Party Mode, each friend and each
  web remote guest, plus how long friends drove your toys and how many
  Avatar Remote controls they set. A session's timeline marks each shock
  (hover for when, how strong and from whom), and suits and haptic trackers
  get their on-time. Friends' names are kept unless you switch *Keep
  friends' names* off; *Forget names* folds the ones already kept.

### Haptic trackers

- **Trackers that vibrate**, on the Suits page: a Vive Tracker with a Haptic
  Pancake, a Tundra with a Tundra Tapper, or a controller set up as a
  tracker buzzes from your avatar's contacts. They sit on Haptic Pancake's
  nine spots (head, chest, hips, elbows, knees, feet), each following
  Pancake's parameter name, so an avatar set up for it works as it is. A
  tracker goes where its role in SteamVR's Manage Trackers puts it, or
  where you click. Each spot's Top starts at 80 %, and the trackers have
  their own anti-stuck. Off until you switch it on in Settings → Features;
  OGP never starts SteamVR itself.

### PSVR2 headset rumble

- **On a page of its own.** Your PlayStation VR2 headset's rumble from a
  contact on your avatar, through PSVR2Toolkit's experimental builds (the
  ones with its C API) — which needs a jailbroken headset. OGP never bundles
  the toolkit; it uses yours. Off until you switch it on in Settings →
  Features (or "What are you here for?"); then it connects whenever SteamVR
  runs. Off, Off while you're away and its own anti-stuck hold for it,
  it has a Home row and an `OGP/PSVR2Connected` parameter. Windows only.

### Fixes and debugging

- **Avatar Remote's menu slots.** Picking a slot in the circle's radial did
  nothing in 0.15: the picker closed before it took the click. It takes now,
  and its caption no longer overlaps (already in 0.15.2).
- **Debug recording** (OSC Inspector page): one click records a session with
  every contact packet VRChat sent, for a bug report; *Record raw contacts
  (debug)* in Settings → Sessions does the same for every recorded session.

**Coming from 0.14 or older?** 0.15.0 brought the haptic suits and Intiface on
your phone: [the 0.15.0 notes](https://github.com/Blise518B/OscGoesPurrr/releases/tag/v0.15.0).

More on the website: https://blise518b.github.io/OscGoesPurrr/
