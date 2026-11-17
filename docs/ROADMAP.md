# OscGoesPurrr — Roadmap

A loose list of features we want to land, grouped by theme.
Order within a group is rough priority, not a hard sequence.

**Scope note.** This is the toys-first edition. PiShock / OpenShock, the
bHaptics and OWO suits, haptic trackers and PSVR2 rumble have come back;
bringing back the other haptic backends -- DG-Lab Coyote, The Handy -- is
its own line item, and the seams they were built against are
all still here (see ARCHITECTURE.md, "How to add a new haptic backend").
Items below assume the toy path unless they say otherwise.

**Suits, next steps.**
- The bHaptics dot -> motor tables measured on real suits
  (`tools/bhaptics_probe.py walk --interactive`), per model.
- OWO straight over Bluetooth, without My OWO: a research track in
  `tools/owo_ble/` (capture what My OWO sends, decode, replay). Only once
  it's understood -- and with calibration and caps inside OGP -- does it
  replace the My OWO path.
- TactGlove, the suits in SteamVR's device list, and friends driving
  your suits (Friends page).

## Next up: from friends' reviews (2026-11-14)

Still being collected. Each idea below says what was asked, what OGP
has today, the change, and the calls still open. They're grouped by
theme; the build order is this table, so it can be reshuffled without
renumbering anything. Size is relative: S < M < L. Status says
where each one is: Building (a session is on it), Merged (in release/lite),
Released (in a public release).

| # | Idea | Size | Why here | Status |
|---|---|---|---|---|
| 1 | [Everything off while AFK, plus your own Off parameter](#everything-off-while-afk-plus-your-own-off-parameter-s) | S | Safety; reuses Off | Released in 0.16.0 (merged 2026-11-14) |
| 2 | [Several people on one shocker: strongest wins](#several-people-on-one-shocker-strongest-wins-s-m) | S-M | A flaw found while checking the limits | Released in 0.16.0 (merged 2026-11-14) |
| 3 | [Shock, vibrate and beep switched off separately; per-friend limits](#shock-vibrate-and-beep-switched-off-separately-per-friend-limits-m) | M | Safety, in the engine | Released in 0.16.0 (merged 2026-11-14); the per-friend limits were removed before it (2026-11-17) |
| 4 | [The shocker limits read as limits](#the-shocker-limits-read-as-limits-s) | S | Clarity, small | Released in 0.16.0 (merged 2026-11-14) |
| 5 | [Arm and Share: one switch each, on Home](#arm-and-share-one-switch-each-on-home-s-m) | S-M | Overview from Home | Released in 0.16.0 (merged 2026-11-14) |
| 6 | [The version number links to GitHub](#the-version-number-links-to-github-s) | S | A one-liner | Released in 0.16.0 (merged 2026-11-14) |
| 7 | [Remove an Avatar Remote control by dragging it back to the list](#remove-an-avatar-remote-control-by-dragging-it-back-to-the-list-s) | S | Small | Released in 0.16.0 (merged 2026-11-14) |
| 8 | [Check whether a friend is online, now](#check-whether-a-friend-is-online-now-s) | S | Small | Released in 0.16.0 (merged 2026-11-14) |
| 9 | [Filters in the Add Variable picker](#filters-in-the-add-variable-picker-s-m) | S-M | Easier setup, one shared picker | Released in 0.16.0 (merged 2026-11-14) |
| 10 | [Touch / Penetration × Self / Others on each toy's bar](#touch--penetration--self--others-on-each-toys-bar-on-home-m) | M | Easier setup | Released in 0.16.0 (merged 2026-11-14) |
| 11 | [Shockers understand ShockOSC's parameters](#shockers-understand-shockoscs-parameters-m) | M | Easier setup | Released in 0.16.0 (merged 2026-11-14) |
| 12 | [Link each friend to their VRChat account](#link-each-friend-to-their-vrchat-account-m) | M | Friends; 13 builds on it | Released in 0.16.0 (merged 2026-11-14) |
| 13 | [Friends: only people in your instance](#friends-only-people-in-your-instance-m) | M | After 12 | Released in 0.16.0 (merged 2026-11-14) |
| 14 | [Control mode in its own window](#control-mode-in-its-own-window-m) | M | Friends, VR | Released in 0.16.0 (merged 2026-11-14) |
| 15 | [OpenShock's layout for the shocker panel, and Live control](#openshocks-layout-for-the-shocker-panel-and-live-control-m-l) | M-L | Friends; after 2 and 3 | Released in 0.16.0 (merged 2026-11-15) |
| 16 | [Height on the Avatar Remote](#height-on-the-avatar-remote-like-the-osc-scaler-tools-m) | M | Friends' fun; VRChat has the OSC for it | Released in 0.16.0 (merged 2026-11-14) |
| 17 | [A log per person, and a Log page](#a-log-per-person-and-a-log-page-m) | M | Friends; 18 counts its events | Released in 0.16.0 (merged 2026-11-14) |
| 18 | [Statistics for everything, shocks included](#statistics-for-everything-shocks-included-who-and-when-m) | M | Records; uses 12's names and 17's events | Released in 0.16.0 (merged 2026-11-14) |
| 19 | [A Toys page; Home becomes the hub](#a-toys-page-home-becomes-the-hub-l) | L | Moves controls around | Released in 0.16.0 (merged 2026-11-14) |
| 20 | [A guided first-launch tour](#a-guided-first-launch-tour-l) | L | After 19, which moves what it points at | Released in 0.16.0 (merged 2026-11-14) |
| 21 | [PSVR2 headset rumble back](#psvr2-headset-rumble-back-m-a-port) | M | A port from `main`; fits any time | Released in 0.16.0 (merged 2026-11-14) |
| 22 | [Global vs per-avatar settings](#global-vs-per-avatar-settings-advanced-off-by-default-design-first) | ? | Rough; design talk first | After 0.16.0, high priority (Blise, 2026-11-16) |
| 23 | [Ctrl+Z undoes your last changes, anywhere](#ctrlz-undoes-your-last-changes-anywhere-m-l) | M-L | Touches every settings store; after wave 2 | Released in 0.16.0 (merged 2026-11-14) |
| 24 | [Toy rows stacked and centred; the Toys page unfolded](#toy-rows-stacked-and-centred-the-toys-page-unfolded-s-m) | S-M | Blise's review of the pictures, 2026-11-16 | Released in 0.16.0 (merged 2026-11-16) |
| 25 | [The rest and run cap for every source; the log says what was cut](#the-rest-and-run-cap-for-every-source-the-log-says-what-was-cut-s-m) | S-M | Safety; from the modified-client audit | Released in 0.16.0 (merged 2026-11-16) |
| 26 | [ShockOSC's settings and OGP's behaviours: one set of values](#shockoscs-settings-and-ogps-behaviours-one-set-of-values-m) | M | After 11 | Released in 0.16.0 (merged 2026-11-16) |
| 27 | [Separate limits for your avatar and for friends](#separate-limits-for-your-avatar-and-for-friends-m) | M | After 25; design to confirm | Released in 0.16.0 (merged 2026-11-17) |
| 28 | [Sync with others: the newest real change wins](#sync-with-others-the-newest-real-change-wins-s) | S | A modified app could keep the shared cards | Released in 0.16.0 (merged 2026-11-17) |

Each one that ships brings the usual along: What's new, README, the
site and its demo, `ui/page_steps.py`, the web remote where a friend's
panel changes, and a choice in "What are you here for?" if it adds a
feature switch.

### Safety and the shockers

#### Everything off while AFK, plus your own Off parameter (S)

**Asked:** when VRChat says you're AFK (its built-in `AFK`, or GoGo
Loco's own AFK), switch every device off. Also a parameter of your own
choosing that switches everything off.

**Today:** `OGP/Off` from the avatar menu holds all output off, and the
toys, shockers, suits and friends already obey it (`is_output_off`).
Nothing reads `AFK`.

**Change:**
- Settings → Toy Safety gets an "Off while you're away" card with three
  sources: VRChat's `AFK`; GoGo Loco's AFK (read its exact name off an
  avatar); and "Also off while", a list of parameters you pick with the
  picker.
- They hold the same Off as `OGP/Off` without changing that switch's
  state. Friends' drives are held as with Off, and the status bar says
  why ("AFK: everything off").

**Decided (2026-11-14):** "Off while you're away" starts switched on.
When AFK ends, everything comes back by itself: it's a held Off, and your
own Off switch is never touched. It holds only while VRChat runs: when
VRChat closes, every away reason lets go ("It should just be active if
you're actually AFK within VR chat and no other time").

#### Several people on one shocker: strongest wins (S-M)

**Found while checking the limits.** The engine keeps one hold per
shocker and takes whichever source wrote last. So when two friends (or a
friend and your own Continuous behaviour) hold one shocker at 30 and 50,
it keeps switching between the two levels instead of taking the stronger
one. And when one of them lets go, the other's hold stops for a moment
too, until its next tick. Your own behaviours already take the strongest
among themselves (`pishock_router`); the mix-up is between sources. This
comes from reading `pishock_engine.hold / release` and
`friends_receive._pump_friend_holds`; no test pins it yet.

**Change:** the engine keeps each source's hold apart (router, menu, each
friend, web remote, Party Mode), and the shocker plays the strongest. A
source's release ends only its own hold. Caps, longest hold and rest
stay per shocker, as now. A test with two friends holding one shocker
pins it.

**Decided (2026-11-14):** a held shock always beats a held vibrate,
whatever their levels ("the shockers have priority"); among holds of the
same kind, the strongest wins. Any vibrate also beats any beep.
**Open:** your own Shockers behaviours still pick among themselves by
level first, before the engine sees them (`pishock_router._stronger`), so
a Touch zone's vibrate at 40 beats another behaviour's shock at 30. Same
rule there?

#### Shock, vibrate and beep switched off separately; per-friend limits (M)

**Asked:** turn shock, beep and vibrate off separately. The follow-up
question was whether limits apply per person or to everyone combined.

**Today, the answer: per shocker, for everyone combined.** No limit is
per person.
- **Max shock / max vibrate / longest pulse:** each shocker has its own,
  and everyone lands under the same ceiling: your behaviours, the avatar
  menu, every friend, the web remote. A friend sends a fraction of your
  ceiling (`slim`).
- **Rest after a pulse, longest hold, break:** shared by the whole hub.
  After anyone's pulse, that shocker rests for everyone, you included (a
  stronger pulse may still cut in). Holds by several people count as one
  hold, and when it runs out the shocker rests for everyone.
- **Per friend, today:** only on/off. Each friend's Shockers switch, plus
  Share with friends and On for all of them.

The rest of today: a shocker has one On / Off, and shocks turn into
vibrates until armed. PiShock's own per-share limits (each action
switchable, a max per friend, a forced warning) were left open when the
friend panel was built.

**Change:**
- Three switches per shocker: Shock, Vibrate, Beep. They are enforced in
  `PiShockEngine` like Off: a switched-off action is refused. Friends'
  panels and the web remote grey that button, and a behaviour that uses
  it greys its chip. Remembered.
- Per friend, PiShock's share limits: which actions they may use, their
  own max intensity and longest pulse (always under the shocker's
  ceiling, never above it), and "always warn first". Group and web
  remote rows get the same.

**Decided (2026-11-14):** (a) the switches are per shocker. (b) A
switched-off action is greyed out on the sender's side (a friend's panel,
Party Mode, the web remote), so it can't be pressed: "it shouldn't even
appear, or it should be greyed out". It never turns into a vibrate, and
anything that still arrives is dropped. (c) Rest after a pulse stays
shared by everyone. (d) A shock that is due a warning ("always warn first",
or asked for) on a shocker that can't warn, because Vibrate and Beep are
both off, is held back there and logged. The sender's Warn button greys
out, with a hover saying why, and so does Shock where warn-first applies.

**Reversed (2026-11-17):** the per-friend share is gone again, everywhere
(friend, group, web remote). Blise: "The friends menu should be about the
friends and not about my own things." Every friend gets each shocker's own
limits and switches from the Shockers page; the switches above stay.

#### The shocker limits read as limits (S)

**Asked:** on the Shockers page, make it clear the sliders set limits;
they don't operate the shocker.

**Today:** each shocker card has max shock / max vibrate / longest
pulse, and the hub card has rest / longest hold / break, all as sliders
with the number written out.

**Change:**
- Group them under a "Limits" heading with a ceiling icon, and add one
  sentence: "The most anything may send: friends, behaviours, the menu.
  Nothing is sent from here."
- Name them "Up to …".
- Keep the buttons that do send something (Beep, Vibrate) visibly apart
  from them.

**Decided (2026-11-14):** every limit reads "Up to …" except the two
minimums, "At least a rest of" and "Then a forced break of".
**Open:** fold the limits closed once they're set?

#### Arm and Share: one switch each, on Home (S-M)

**Asked:** arming and sharing should be the same switch wherever they
show, and sit on Home's shocker row. That way you don't arm and share in
several places, and Home gives the overview.

**Today:** Arm shocks is on the Shockers page. "Share with friends" (one
switch for all friends) and On / Off are on Home's shocker row. Each
friend also has their own Shockers switch on Friends, and the web remote
has its own.

**Change:**
- Home's shocker row gets Arm next to Share and On / Off. The Shockers
  page shows the very same switches: one setting, changed anywhere, shown
  everywhere.
- One explanation says how the switches stack: On (the hub) → Armed
  (real shocks) → Shared (friends at all) → each friend's own switch.

**Decided (2026-11-14):** arming asks "Arm shocks? Yes / No" on Home
and on the Shockers page alike (in the switch's place, back to off after
5 s), and both places show a red "Shocks armed" / "Shocks not armed" next
to the switch.

### Setting up

#### Filters in the Add Variable picker (S-M)

**Asked:** + Add Variable lists every parameter on the avatar, and most
of them are noise. Hide the well-known system and asset parameters by
default, with filter switches at the top of the picker.

**Today:** one shared picker, `ui/osc_variable_picker.py`, used by a toy
motor's + Add Variable, SPS Sources and the Shockers behaviours. Its only
filter is "Include non-avatar parameters (OGB/SPS, system, etc.)".
`remote_params.BUILTINS` already lists VRChat's own parameters, for the
friend's board.

**Change:**
- One pure module (say `param_filters.py`): named groups, each a set of
  exact names, prefixes and suffixes, tested without a window.
  `remote_params.BUILTINS` moves into it.
- The groups, hidden by default:
  - *VRChat's own*: AFK, Viseme, Voice, Gesture*, Velocity*, AngularY,
    Upright, Grounded, Seated, TrackingType, VRMode, MuteSelf, InStation,
    Earmuffs, IsOnFriendsList, Scale* / EyeHeight*, AvatarVersion, IsLocal,
    PreviewMode, IsAnimatorEnabled.
  - *GoGo Loco* (`Go/…`).
  - *Face tracking*: VRCFaceTracking (`FT/…`, `v2/…`, its binary bit
    parameters, `*TrackingActive`) and OSCmooth's (`OSCm/…`).
  - *VRCFury internals*: what its Parameter Compressor and other
    builders generate.
  - *Physics assets*: Marshmallow PB and similar.
  - *PhysBone states*: `…_IsGrabbed`, `…_IsPosed`, `…_Angle`,
    `…_Stretch`, `…_Squish`. In the Shockers picker they stay visible,
    because ShockOSC uses them.
  - *OGP's own* (`OGP/…`), and *SPS* (`OGB/…`, `VFH/…`, `TPS_Internal/…`),
    which takes over today's switch.
- *VRCFury toggles* (`VF<n>_…`): a filter you can switch on, shown by
  default.
- **Layout:** a taller dialog. Under the search box, a row of chips, one
  per group with its count ("Face tracking · 142"); a lit chip hides its
  group, and *Show everything* turns them all off. The chips are
  remembered once for every picker.
- **Nothing is lost:** a parameter that is already mapped is never
  hidden, and a search also finds hidden parameters, listed under "Hidden
  by filters".
- Read the exact names off real avatars before shipping (an avatar with
  GoGo Loco, VRCFT, OSCmooth and Marshmallow PB, from VRChat's OSC
  config folder) and pin them in tests.

**Decided (2026-11-14):** VRCFury toggles are shown by default; one
click on their chip hides them.

#### Touch / Penetration × Self / Others on each toy's bar on Home (M)

**Asked:** four quick switches behind the toy's name on Home: touch
self, touch others, penetrate self, penetrate others. That way the common
change needs no digging. When the window is small, a toy's bar can take
two lines to fit them.

**Today:** the same choice is four switches per chain, inside a toy's
Input stage ("Listening To" in `device_frame.py`): Touch, Penetration,
Self, Others. They are two independent pairs, saved per chain and per mode
(`motor_N_cK_touch / pen / self / others`), and a typed chain takes
Touch / Penetration from its type. The router already checks each
(type, source) pair (`motor_router._chain_filters`).

**Change:**
- Four chips on the toy bar, after the name and its zones summary. A chip
  sets its pair on every chain of the toy in the active mode. While the
  chains disagree, the chip shows half lit, and a click makes them all
  agree.
- Everything stays on one line while it fits. Below a width, the chips
  and the zones summary drop to a second line; icon, name, battery,
  meters, Mute and Test stay on the first.
- **Data:** the four the friend described make a 2×2, which can say "touch
  from myself, but penetration only from others". Two independent pairs
  can't say that. The proposal is to store the 2×2 per chain, migrated
  from the pairs without loss (touch-self = touch ∧ self …), and to show
  the same four in the Input stage. The router change is small, because it
  already tests each pair.
- A typed chain only answers the chips of its own type. A toy with only
  touch chains greys its two penetration chips.

**Decided (2026-11-14):** a true 2×2, stored per chain and migrated
without loss. Two lines at the default width are fine: Home becomes the
overview for everything, and the detail moves to the Toys page (19). **Open:** should a chip change only the active mode, like
the Input stage does today (the default if nobody says otherwise), or
every mode?

#### Shockers understand ShockOSC's parameters (M)

**Asked:** listen to the parameters ShockOSC (OpenShock's VRChat app)
uses by default, and have presets or filters that put them first. An
avatar already set up for ShockOSC should then need little setup.

**Today:** the Shockers behaviours (Touch zones, Contact, Continuous,
Impact) take any parameter through the same picker, and nothing knows
ShockOSC's names.

**ShockOSC's names** come from its README and OpenShock's wiki; check
them against ShockOSC's source before building. Every parameter starts
with `ShockOsc/`, followed by a group name the user types, one group per
shocker:
- `ShockOsc/<Group>` (bool): a contact or a PhysBone. A shock after the
  hold time.
- `_IShock` / `_IVibrate` / `_ISound` (bool): at once, no hold time.
- `_CShock` / `_CVibrate` / `_CSound` (float 0-1): continuous, scaled to
  the limits.
- `_Stretch` / `_IsGrabbed`: written by PhysBones. A pull's stretch on
  release sets the strength.
- `_NextIntensity` / `_NextDuration` (float): override the next action.
- `ShockOsc/_All…`: every shocker at once.
- `ShockOsc/_Config/_All/…`: Paused, Intensity, Min/MaxIntensity,
  Duration, Min/MaxDuration, ModeIntensity, ModeDuration, CooldownTime,
  HoldTime.
- Sent back to the avatar: `<Group>_Active`, `_Cooldown`,
  `_CooldownPercentage`, `_DurationRemaining`, `_Intensity`,
  `ShockOsc/_Any_Active`, `_Any_Cooldown`.
- ShockOSC publishes no avatar prefab. Its setups are made by hand from
  the wiki, so there are no stock contacts to copy.

**Change:**
- In the Shockers behaviours, the picker lists `ShockOsc/…` parameters
  first, under "ShockOSC".
- When the worn avatar has `ShockOsc/` parameters, a card offers to set
  them up in one go:
  - `<Group>` becomes a Contact.
  - `_IShock` / `_IVibrate` / `_ISound` become a Contact that pulses once
    with that action.
  - `_CShock` / `_CVibrate` become a Continuous behaviour.
  - Each group takes the shocker with its name, or one you drop on it.
    `_All` takes every shocker.
- OGP sends the feedback parameters, so a ShockOSC avatar's visuals work.
- The safety rules don't move: everything goes through `PiShockEngine`,
  shocks stay vibrates until armed, and nothing from the avatar
  (`_Config/*`, `_NextIntensity`) can choose outside OGP's caps.
- Learn from ShockOSC; never copy its code. The parameter names are an
  interface.

**Open (the session starts from the safe side):** (a) the avatar's
`_Config/_All/*` values are honoured only where they're stricter (lower
strength or duration, longer cooldown, always within OGP's caps), and
`Paused` stops the avatar's ShockOSC behaviours. (b) The PhysBone pull
becomes a "Pull" kind only if ShockOSC's own semantics need it.

### Small touches

#### The version number links to GitHub (S)

**Asked:** clicking the version number at the bottom of the window
should take you to OGP's GitHub page too.

**Today:** the status bar says "OscGoesPurrr v0.15.1 · made by
Blise518B". The name links to the repository and Blise518B to his
profile, but the version is plain text (`theme.status_tag_html`).

**Change:** the version links too.

**Open:** to the repository, like the name, or to this version's release
notes (`releases/tag/v<VERSION>`)?

#### Remove an Avatar Remote control by dragging it back to the list (S)

**Asked:** on the Avatar Remote, delete a control by dragging it back to
the parameter list.

**Today:** you make a control by dragging a parameter from the list into
a category (or double-clicking it). You remove one with the card's own
remove. The list only lets things drag out of it (`DragOnly`).

**Change:**
- The parameter list accepts a dropped card and removes that control.
  While a card hovers over the list, it lights up with "Drop to remove".
- A whole category dropped there asks first.
- Only on your own board; a friend's board is for looking and pressing.

**Decided (2026-11-14):** a control goes at once, with a short Undo for
now; a whole category asks first. The removal is one reversible action,
so the app-wide Ctrl+Z (23) can take it over.

### Avatar Remote

#### Height on the Avatar Remote, like the OSC scaler tools (M)

**Asked:** change someone's height from the Avatar Remote, the way Height
Shift OSC does. The tools of that kind (VRChat OSC Scaler, the
Remote/Local Scaling Tool, both on Booth) all use VRChat's OSC avatar
scaling.

**How VRChat does it** (docs.vrchat.com, "OSC Avatar Scaling"):
- `/avatar/eyeheight` is a float in metres that can be read and written.
  It sits outside `/avatar/parameters/`, and VRChat sends it back on every
  change, from you, a world or an avatar switch.
- Writes reach from 0.01 m to 10,000 m, past the menu's slider. VRChat
  warns that under 0.1 m or over 100 m can break things.
- A world can forbid it: `/avatar/eyeheightscalingallowed` is false then,
  and writes are ignored. A world's own limits win over what you set: you
  get your value back, then the world's. `/avatar/eyeheightmin` / `max`
  report those limits.
- VRChat has a bug report about the view jittering while the height
  glides over OSC.

**Today:** the Avatar Remote only sets avatar parameters. VRChat's own
`ScaleFactor` / `EyeHeight*` parameters can't be set
(`remote_params.BUILTINS`), and nothing in OGP sends or reads
`/avatar/eyeheight`.

**Decided (2026-11-14):**
- **It stays.** When a friend stops or leaves, your height stays where
  they put it. It isn't a held control.
- **It comes with the AVATAR switch**, with no fourth switch per friend.
  On top of that, the Height box has its own switch on the Avatar Remote
  page, for anyone who doesn't want their height touched. It's on by
  default; you switch it off there.
- **Both ways to change it:** *Grow* (glides there) and *Right away*
  (jumps).
- **Compact:** one box, only the controls it needs.

**Change:**
- A **Height** box on your board, below the categories and in its own
  section, with the same frame as a category box. Its top bar has the
  box's On / Off switch. Off: friends and the web remote don't see it, and
  nothing they send changes your height.
- Inside, only:
  - your height right now, live from VRChat's own messages;
  - one slider between your lowest and highest height;
  - *Grow* / *Right away* as two buttons;
  - Reset (back to your own height).
- Behind the box's ⋯, the lowest and highest height. By default that's
  VRChat's own menu range (0.2-5 m), never past the safe 0.1-100 m, and a
  friend can't widen it. Also there: how fast Grow goes, kept gentle
  enough to avoid VRChat's jitter.
- While the world doesn't allow scaling, the box greys out and says so.
- Sent on change only, at a gentle rate.
- **Friends:** a friend with your AVATAR switch on gets the same box on
  their copy of your board, while its switch is on. Pause all holds, and
  so do locks (a locked box is look-only). Your own avatar menu can drive
  it from a radial slot, and the web remote follows (1-to-1).

### Friends

#### Check whether a friend is online, now (S)

**Asked:** a manual refresh button for whether a friend is online.

**Today:** offline friends are retried in the background, and all of them
share one budget: one try per `BACKGROUND_GAP_S` (10 s), fewest failures
first. With a long list, a friend who just came online can take a while
to show. The budget is what keeps the link light on n0's free relays.

**Change:**
- A ↻ on an offline friend's row, and a "check everyone now" for the
  list, dial at once, outside the background budget.
- It has its own limit, so the link stays light even with a lot of
  clicking: one try per friend per ~10 s. The button says "checking…"
  until the friend answers or the try gives up.

**Open:** a button per row, one for the whole list, or both?

#### Link each friend to their VRChat account (M)

**Asked:** see who's in your instance and assign them to the friends
you've added, plus a button that imports your friends' names from VRCX.
In short, an easy way to say "this OGP friend is that VRChat person".

**Today:** an OGP friend is a key plus the nickname they chose, and
nothing ties them to a VRChat account. `vrchat_log.py` already reads
who's in your instance from VRChat's log, names and `usr_` ids included
(opt-in, for People statistics). Nothing reads VRCX.

**Change:**
- Each friend's panel gets a "VRChat account" field. You pick from the
  people in your instance right now (from the log) or from your VRChat
  friends imported from VRCX. It's stored locally by `usr_` id (display
  names change) and never sent to anyone.
- A quick way, like groups: the people in your instance as chips you
  drag onto a friend's row.
- **Import from VRCX:** a button that reads VRCX's database
  (`%APPDATA%\VRCX\VRCX.sqlite3`, its friend list: display name and user
  id) read-only, only on that click, and never writes to it. Check the
  table names against a real VRCX database first. Without VRCX
  installed, the button says so.
- **Once linked:**
  - the friend's row shows "in your instance" while they are;
  - People statistics and the friend list use one name for one person;
  - the instance-only option below can check locally.

**Decided (2026-11-14):** their VRChat name goes below the OGP nickname,
smaller and dimmer; a row may grow a little for it.

#### Friends: only people in your instance (M)

**Asked:** an option that lets only people in the same VRChat instance
control you. OGP reads the instance id for everyone.

**Today:** `vrchat_log.py` already reads VRChat's log (opt-in) and sees
both your instance (`Joining wrld_…:<instance>`) and who is in it. Friends
can drive you from anywhere.

**Change:**
- It builds on the link above. With "Only friends in my instance" on
  (Friends page, off by default), OGP checks locally whether a friend's
  linked VRChat account is in your instance, using your own log. Your
  location never leaves your PC, and nothing new goes over the link.
- A friend who isn't in your instance shows "not here" on their row.
  Their drive is refused like Pause (zero at once if they leave
  mid-session), and it's logged.
- An unlinked friend counts as not here, and their row points you to
  linking them. Your own Me row is exempt.

**Decided (2026-11-14, his "go on" on the proposed defaults):** (a) your
own log is enough; nothing new goes over the link. (b) The web remote is
blocked while this is on, unless its own "Allow the web remote anyway"
switch is on (off by default). (c) Each friend has "Allow from anywhere",
off by default.

#### Control mode in its own window (M)

**Asked:** control mode can be its own window.

**Today:** the Friends panel's Control mode fills the page with big cards
for VR (`friends_panel.py`).

**Change:**
- A Pop out button in control mode opens a separate window with just
  that panel, big.
- Its size and position are remembered, it can stay on top, and closing
  it puts the panel back into the page.
- A VR overlay (XSOverlay, OVR Toolkit, Desktop+) can then capture just
  that window. Its pickers stay inside it, because an overlay doesn't
  show popup windows.
- It shares its bones with the Mini-Mode / VR companion window further
  down this list.

**Decided (2026-11-14):** one window that follows the friend picked on
the page. It never reopens by itself at launch, only when you click Pop
out.

#### OpenShock's layout for the shocker panel, and Live control (M-L)

**Asked:** an option to show the shocker panel in OpenShock's layout
(today it's PiShock's own). You choose the default your friends see, and
each of them can change it for themselves only. Plus OpenShock's live
control.

**Today:** a friend's shockers are PiShock's own panel and Party Mode
(`ui/views/shocker_card.py`, `shocker_parts.py`, `shock_party.py`),
kept at parity with docs.pishock.com. The web remote has the same panel
(`assets/remote-shockers.js`).

**Change:**
- A second panel at parity with OpenShock's own shocker card (compare
  with OpenShock's web app before building).
- **Default for others:** Shockers page → "Friends see: PiShock /
  OpenShock", sent with your status. A sensible default follows the
  hub's firmware.
- **Local override:** each viewer has "Show as: their choice / PiShock /
  OpenShock" for themselves, per friend or for all.
- **Live control**, OpenShock's real-time mode: hold and drag, and the
  strength follows your finger until you let go. In OGP it's a pad that
  sends its level on change over the friend link, like toy levels. The
  receiver's engine still enforces caps, longest hold and rest, and the
  shocker stops when updates stop. Over serial, OpenShock firmware takes
  repeated commands; check whether PiShock's hub does too.
- The web remote follows (the page stays 1-to-1 with the app's panel).

**Decided (2026-11-15):** a simple switch, "Shocker buttons: PiShock |
OpenShock", **PiShock by default** ("if you want to change it, you can put
it into the OpenShock layout"), one setting for every panel, on the
friend's and Me's shocker panels and the web remote. The owner's "Friends
see" default is left out for now. Live control comes with the OpenShock
layout, in the friend panel only.

### Records

#### A log per person, and a Log page (M)

**Asked:** a better log. It still scrolls by as things happen, but it can
also show one line per person with the last thing they did; a click
unfolds what that person did. When several people drive you, it's then
easy to see who did what. The log should last longer, with a page of its
own to look through who did what, person by person.

**Today:** `friends_facade._friends_note` keeps lines of (time, text),
with the person's name written into the text, not stored as who did it.
A slider drag is one line (`_COALESCE_S`). The Friends page shows them in
a 130 px text box (`ui/views/friends.py`, `_build_friends_log_card`).
They are kept in memory and the system log only, so they're gone when
the app closes.

**Change:**
- **Entries know who and what:** time, who (a friend, Me, a web remote
  guest, a group), what (toys, a shock / vibrate / beep with its level
  and shocker, an Avatar Remote set, the link coming and going), and why,
  if it was held back. The callers of `_friends_note` pass who and what,
  and the text is written from them. The same entries feed Statistics
  (18), so the event record is built once.
- **The Friends page's log card** has two views:
  - *As it happens* (the default): today's scrolling lines.
  - *By person*: a row per person with their last action and how long
    ago. ▸ unfolds that person's recent history. Shocks stand out.
- **A Log page:**
  - filters by person, by kind (toys, shocks, Avatar Remote, link) and by
    time, plus a search;
  - kept on disk for a while (30 days by default), one JSON Lines file
    per day in OGP's data folder, never a `.json` (settings backups copy
    every `.json`);
  - a Clear button.
- It's never sent to anyone: friends see only their own panel. A web
  remote guest shows the way the Web remote row names them.

**Decided (2026-11-14):** the Log page is its own sidebar entry, with
filters to choose whose actions you see and analyze who did what. Taken
as defaults: 30 days, and your own avatar's behaviours as their own
person, which a filter can hide.

#### Statistics for everything, shocks included, who and when (M)

**Asked:** statistics for everything, shocks included, with who did it
and when.

**Today:** Statistics count active time, each toy's on-time, each zone's
contact time and thrusts, with session timelines, a heatmap / calendar,
and People (who you were with, from the VRChat log). Shocks, vibrates,
beeps, the suits, the trackers and friends' drives aren't counted. The
Friends page logs what friends do, but only live.

**Change:**
- Per session and lifetime: shocks, vibrates and beeps (how many, the
  strongest, total seconds), per shocker and by source. The sources are
  your avatar's behaviours (which one), the avatar menu, each friend by
  name, the web remote and Party Mode. Also the suits' and trackers'
  on-time, friends' drive time on your toys, and friends' Avatar Remote
  sets.
- The session timeline marks each shock: when, how strong, from whom (on
  hover).
- A "From whom" breakdown next to People. It counts the log's events (17)
  rather than keeping its own record.
- It stays local, like all statistics, and is never sent to friends.

**Decided (2026-11-14, his "go on" on the proposed default):** friends'
names are kept, with a switch to leave them out.

### Pages and first launch

#### A Toys page; Home becomes the hub (L)

**Asked:** shockers and suits have their own pages, but toys don't. Give
toys a page of their own, with the chains, modes and every advanced
setting, and make Home the hub of quick settings for everything.

**Today:** Home holds all of the toys. Each toy's bar opens into its
chains, and the modes grid, SPS Sources and the signal graph are there
too. The shocker hub's and the suits' rows on Home only open their pages.

**Change:**
- A new sidebar entry, **Toys** (the capsule, in pink), right after Home.
  It holds the toy cards with their chains, the modes, SPS Sources, the
  Intiface connection and scan, and the signal graph.
- Home keeps Getting started, total strength and one row per device
  (toys, the shocker hub, the suits) with its quick switches: the toy
  chips, and the shockers' Arm / Share / On. A click on a row opens that
  device on its own page.
- Everything that points at Home's toys comes along: `page_steps`, Help,
  the site's demo, `tools/app_shots.py`, the VRChat group gallery, What's
  new's "Take me there" targets, README and tooltips.

**Decided (2026-11-14):** Home becomes the overview for everything, and
the detailed settings move to each device's own page. A toy's row on Home
may take two lines for its chips. The mode buttons and Test all stay on
Home as quick actions. Once the Toys page exists, decide what each haptic
module's quick actions on Home are.

#### A guided first-launch tour (L)

**Asked:** the first launch walks someone through it for real. They add a
toy, and the tour then lights up where to click: "choose your SPS sources
here", "these are the important settings". It can be run again later.

**Today:** "What are you here for?" opens at the first launch, Getting
started has three ticks on Home, and help mode (F1) explains a page:
numbered steps on a strip and a light on whatever the pointer rests on.
Help mode swallows clicks.

**Change:**
- A tour built on help mode's drawing (dim, ring, bubble). The lit
  control can be clicked, and the tour moves on when the real thing
  happens: a toy connects, its card opens, a zone is picked. Each step
  says what it waits for.
- The path, after "What are you here for?":
  1. Connect (the engine scans, or the toy is switched on).
  2. The toy appears, lit.
  3. Open it, then Select Zones ("your SPS sources").
  4. The four toy chips.
  5. Test, then total strength.
  6. Optionally, the avatar menu prefab.
  Then a short branch for each feature picked: Shockers, Friends, Avatar
  Remote.
- You can skip at any step. Run it again from Help ("Take the tour") or
  from Getting started.
- With no toy yet, the step says what to check (toy on, Bluetooth,
  Intiface on a phone) and waits, or *Continue without a toy* moves on.
- The steps live next to `page_steps`, so the gallery, Help and the tour
  tell one story.

**Decided (2026-11-14, his "go on" on the proposed default):** new
installs get it after "What are you here for?"; existing installs are
offered it once, on the update that brings it.

### Backends

#### PSVR2 headset rumble back (M, a port)

**Asked:** add the PSVR2 haptics back.

**Today:** it lives on `main`: `psvr2_capi.py` (a ctypes binding to the
PSVR2Toolkit C API's headset rumble, `psvr2_toolkit_set_hmd_rumble`,
0-25 Hz), `psvr2_engine.py`, `psvr2_router.py`,
`controllers/psvr2_facade.py`, `settings/psvr2.py`, `ui/views/psvr2.py`
and its tests. This edition left it out on purpose.

**Change:**
- Port it from `main` following ARCHITECTURE.md § "How to add a new
  haptic backend", rather than rewriting it.
- `feature_psvr2`, off by default, with a choice in "What are you here
  for?".
- Off, AFK and Toy Safety's anti-stuck hold for it. It gets an "It's
  connected" parameter (`OGP/PSVR2Connected`) and a Home row.
- Windows only, like the toolkit, so the Linux build hides it. The DLL
  comes with the user's PSVR2Toolkit and is never bundled; check its
  licence for the notices.
- CLAUDE.md's "deliberately not here" line changes with it.

**Decided (2026-11-14):** a page of its own with its own headset icon,
off by default, offered in "What are you here for?" and Settings →
Features. Its blue, shared with the second toy's colour on Home, is fine.
"Connect whenever SteamVR runs" starts on once the feature is on, and
every Settings → Features row shows its page's icon.

### Across the app

#### Ctrl+Z undoes your last changes, anywhere (M-L)

**Asked** (Blise, 2026-11-14, answering row 7's Undo question): one
Ctrl+Z for the whole app. Whatever you changed, Ctrl+Z takes it back, with
a history of the last five things you did.

**Today:** there's no undo. Row 7 brings a short Undo for one removed
Avatar Remote control.

**Change:**
- One history for the whole window: the last five changes. Ctrl+Z steps
  back through them wherever you are, and Ctrl+Y steps forward again; a
  new change after an undo drops what could still be redone.
- Changes are recorded where settings are saved, not in each widget, so a
  new setting gets undo for free, like the wheel guard. That covers toys'
  chains and modes, the Shockers page, Avatar Remote boards, Friends'
  list and groups, and Settings.
- The status bar says what was undone, e.g. "Undid: removed Ears from
  the Avatar Remote".
- Only settings. Nothing that already happened is undone: a shock, a
  toy's level, a friend's drive, a sent message.
- An undo that would arm shocks, switch a shocker or an action back on,
  or raise a limit goes through the same ask as doing it by hand.

**Decided (2026-11-14):** Ctrl+Y redoes what Ctrl+Z took back ("I think
that would not really make it much more complicated"), and there's one
history for the whole app, as he described it. A shocker behaviour that
comes back through undo or redo doesn't ask ("No, caps are enough"):
arming and the caps still hold.

**When:** after wave 2 is merged, because it touches every settings store
those sessions are changing.

### From the review of 2026-11-16

Blise's calls on the open questions: shock comes first among your own
behaviours too; OpenShock's layout keeps Stop all with one shocker; one
VRChat account per friend is fine (a friend with two PCs is two friends);
Ctrl+Z's extra asks stay; **YOLO may set `OGP/*` and `ShockOsc/*`** ("that's
what YOLO mode is for... it's supposed to cause some chaos"); per-avatar
settings (22) after 0.16.0, high on the list; no release before he has
tested more. And (2026-11-17): the toy chips change the active mode only;
a shock always takes over a playing vibrate or beep; the toy card's Delete
and avatar-parameter rows get small and move to the bottom.

#### Toy rows stacked and centred; the Toys page unfolded (S-M)

**Asked:** on Home, a toy row's Touch Self / Others and Penetration Self /
Others sit on top of each other, with the icon and name, the battery,
meters, Mute and Test centred vertically beside them; only when the
window gets too narrow does the row fall back to two lines. The Toys page
is where you tune precisely, so its cards open unfolded, showing each
motor's Touch and Penetration chains; each chain stays folded. Also: Home's
shocker row fits at 860 px, and the VRChat group gallery no longer stops
at the Suits card.

#### The rest and run cap for every source; the log says what was cut (S-M)

**Asked:** the rest after the longest hold and the run cap on chained
stronger pulses apply to everyone, your own behaviours included, and a
hold right after a pulse waits for that pulse's rest. The log shows the
value that was asked and, under it, what it was cut to and why. With a
friend's Toys switch off, their shocker holds still work while Shockers
is on.

#### ShockOSC's settings and OGP's behaviours: one set of values (M)

**Asked:** a ShockOSC setup starts from the Shockers page's own defaults,
and every ShockOSC setting with an OGP equivalent (strength, length,
cooldown, hold time, paused) is one value: the avatar's menu changes the
behaviour, the page changes the avatar's parameter. The shocker caps still
can't be widened.

#### Separate limits for your avatar and for friends (M)

**Asked:** an option to give your avatar's own behaviours and remote
senders (friends, the web remote) separate limits, so a friend's shocks
don't use up the rest your own small haptic shocks need. Default: the same
limits for both, as today. **His calls (2026-11-17):** one switch, off by
default. Off: one set of limits, as today. On: the longest hold, the rest
and the forced break come twice, "Your avatar" (behaviours, ShockOSC, your
menu) and "Friends" (friends, Me, the web remote), each with its own values
and its own count. Strength and pulse caps stay one per shocker.

#### Sync with others: the newest real change wins (S)

**Found:** the shared toy cards play the change with the highest number,
and the sender picks the number, so a modified app can say "newest"
forever and keep the cards. **Proposal:** the receiver orders the changes
itself, by when a real change arrived. **His call (2026-11-17):** yes, "but
only if you're 100% sure that it will have no false positive or negative
  impacts" -- shipped only when every honest case behaves as today.
Built, it behaves as today in every honest case but two, both better: a
friend whose cards are a moment behind no longer undoes a newer change,
and an old web-remote page after a restart joins the cards as they are.
**He took those (2026-11-17)** and it was merged. Open: card changes have
no rate budget of their own yet (shocks, Stops and Avatar Remote sets do).

### Later: needs a design talk

#### Global vs per-avatar settings (advanced, off by default; design first)

**Asked (rough):** some settings apply to all avatars, others to one
avatar. Perhaps a switch at the top of a page between "global" and "this
avatar". Off by default, as an advanced feature.

**Today:** part of this exists. A mode holds what each toy listens to
(zones, variables, filters), and Settings → Modes → "Remember mode per
avatar" (off by default) brings back each avatar's last mode when it
loads. Chain shaping, strength and everything else are global.

**Proposal to discuss:** Settings → Advanced → "Per-avatar settings". With
it on, a page with avatar-dependent settings gets a strip at the top:
"Editing: All avatars / <avatar name>". A change made under "this avatar"
becomes an override for that avatar, with a small mark on it and a reset
back to the global value.
- Candidates for per-avatar: what each toy listens to (zones, variables,
  the four chips), the shocker behaviours' contacts, the suits' contact
  map.
- Never per-avatar: caps, arming, strength limits, friends.

**Open:** is "Remember mode per avatar" already most of it, made more
visible? Ask the friend which settings they actually want per avatar
before designing more.

## Haptics Features

- **Manual pattern mode.**
  A library of pre-baked vibration patterns the user can trigger
  manually (button, hotkey, OSC param) for the case where SPS isn't
  working but they still want stimulation. Should coexist with normal
  routing — pattern playback wins while active, then routing resumes.
  _Becomes much cheaper once "Audio-reactive routing" lands the
  source-aware merging into `HapticEngine` (see below)._

- **Audio-reactive Intiface routing.**
  Use the audio coming out of VRChat (game music, video player, world
  ambience) to drive toy vibration, separately from SPS contact
  routing. Lives behind its own "Audio" tab so it doesn't tangle with
  the main routing UI.

  **End-game vision:** detect the currently-playing VRCDN / video
  player URL inside the world and listen to *that specific stream*, so
  toy reactivity isn't polluted by voice chat, menu sounds, or world
  ambience. Inspiration: VRCX's log-tailing pattern.

  **Design decisions (locked):**
  * Multi-band analysis (bass / mid / treble) with configurable
    weights, attack/release smoothing, master multiplier. No
    beat/onset detection in v1 — start simple.
  * Target-backend checkboxes — Intiface-only today, but the
    architecture allows expansion as backends return.
  * Phase 3 dependency path = **zero-extra-install via Win11 process
    audio capture** (UWP-style). User does not have to install
    VB-Audio Cable or any virtual audio sink. Win11-only feature; on
    Win10 we fall back to "system loopback + voice-mic filter" (Phase
    2 alone).

  **Open architectural decision — multi-source motor merging:**
  Audio routing means a second writer to `HapticEngine.update_target()`.
  Today's engine is last-writer-wins which doesn't compose. Three
  candidates discussed:

  * **Option 1 — Per-toy exclusive assignment** ("this toy is `main`,
    that toy is `audio`"). Zero engine refactor. Each router skips
    toys not assigned to it. Simpler to reason about; can't have a toy
    respond to SPS *and* audio simultaneously.
  * **Option 2 — Source-aware max-wins** (recommended at design-time
    but not yet committed). `HapticEngine._device_targets` becomes
    `Dict[(d,m), Dict[source, (value, last_touch_ts)]]`, effective
    target = `max(v for (v,t) in <map>.values() if now - t < STALE)`.
    `update_target(device, motor, value, source="default")` adds the
    source kwarg with a default so existing callers don't change.
    Source-stale decay (~500 ms) prevents stuck values when a source
    dies. Makes future **Manual pattern mode** and **SPS priority
    layering** roadmap items almost free — they become new sources.
  * **Option 3 — Hybrid (per-toy subscribed sources + max-wins).**
    Each toy declares which sources it listens to. Most flexible, most
    UI. Over-engineered for v1.

  Pick this before writing any of the engine code below. _Pending._

  **Phased delivery:**

  **Phase 1 — Loopback engine + Audio tab.**
  * New `audio_engine.py` — sealed-box engine, owns a capture thread
    using `pyaudiowpatch` (WASAPI loopback) at ~22050 Hz mono.
    Continuously fills a ring buffer; computes RMS per band every
    ~10 ms; stores latest band levels behind a lock. Primitive-only
    public API (`start()`, `stop()`, `set_input_device(id)`,
    `snapshot() -> {bass, mid, treble, peak}`).
  * New `audio_router.py` — stateless calculator polled at
    `ROUTER_POLL_RATE_MS`. Reads `audio_engine.snapshot()`, applies
    weights/smoothing/master, computes 0–1 intensity, writes to
    `HapticEngine` via whichever merging path Option 1/2/3 lands.
  * New `controllers/audio_facade.py` — `AudioFacade` mixin composed
    into `OscGoesPurrrApp`. UI-facing methods: `get_audio_status()`,
    `set_audio_enabled()`, `set_audio_input_device()`,
    `set_audio_band_weights()`, `set_audio_smoothing()`,
    `set_audio_master_multiplier()`, `set_audio_target_toy()` /
    `set_audio_target_backend()` (signature depends on merging
    option).
  * New `AudioSettingsManager` in `config_manager.py`, persisted to
    `%APPDATA%\OscGoesPurrr\audio_settings.json`.
  * New `audio_settings.json` schema:
    ```json
    {
      "enabled": false,
      "input_device_id": null,
      "band_weights": {"bass": 0.7, "mid": 0.5, "treble": 0.3},
      "attack_ms": 30,
      "release_ms": 200,
      "master_multiplier": 1.0,
      "target_backends": {"intiface": true},
      "target_toys": { /* shape depends on merging option */ }
    }
    ```
  * New "Audio" sidebar view in `ui_components.py`: device picker,
    band weight sliders, smoothing spinboxes, master multiplier,
    target-backend checkboxes, target-toy assignment list, live RMS
    meter for visual feedback.
  * New dependency: `pyaudiowpatch>=0.2.12` in `requirements.txt`.
  * Update `ARCHITECTURE.md`'s engine family list to include audio.

  **Phase 2 — Voice/menu filter.**
  * Tap the Windows microphone level (e.g., `pyaudiowpatch` on the
    default input device, peak detection, no transcription needed).
  * When mic peak > threshold for > N ms, pause audio routing output
    (or scale to 0) so the menu/voice sounds don't drive toys while
    the user is talking.
  * Configurable threshold + hold time on the Audio tab.
  * Cheap win that removes ~80% of "menu sounds triggered the toy"
    false positives.

  **Phase 3 — VRChat video URL isolation (Win11+).**
  * Watch `%USERPROFILE%\AppData\LocalLow\VRChat\VRChat\output_log.txt`
    for video player URL events (USharpVideo / ProTV / etc. log lines
    when a stream starts). Use a tailing reader that re-opens on log
    rotation, same pattern VRCX uses.
  * When a URL is detected, spawn a hidden sidecar (`mpv --no-video`
    or `yt-dlp -o -` piped to a silent decoder) that opens the same
    URL.
  * Use the Win11 process audio capture API (UWP / WinRT
    `AudioGraph` + `AudioPlaybackConnection`, or
    `IAudioClient3::InitializeSharedAudioStream` with a process-loopback
    activator) to capture **only** that sidecar's audio output by PID.
    Python binding: see `pywinrt` or the C++ shim approach used by
    [AudioCaptureSample][win11-pac] (link to be filled in when
    investigating). No virtual audio cable needed; nothing else for
    the user to install.
  * Switch the audio engine's input source from system loopback to the
    sidecar-PID capture whenever a stream is active. Fall back to
    Phase 2 loopback + mic filter when no stream is detected or on
    Win10.

  [win11-pac]: https://github.com/microsoft/Windows-classic-samples
    (Win11 process audio capture — fill in real link during build)

- **Rhythm engine: tempo-locked resynthesis.**
  Stop *filtering* the noisy VRChat motion signal and instead *estimate
  the stroke rhythm* underneath it, then resynthesize a clean,
  deliberately nicer output waveform locked to that tempo + phase. The
  output is generated, not filtered, so it can be smooth and crisp at
  once — the inverse of the smoothing-vs-crispness wall the current
  signal chain hits. The SPS-side analog of the audio-reactive item
  above (motion-rhythm detection vs. audio-onset detection).

  **Scope decisions (locked):**
  * Vibrator-first; output is a single `[0, 1]` scalar (linears are
    speed-only here), fanned out by the existing routing unchanged.
  * Reinterpret, don't reproduce — rhythm is a tempo/phase reference
    for a designed feel-waveform, with rhythm-locked dynamic-range
    **expansion** (floor + multiplier) so shallow strokes read clearly.
  * Overall level scales with tempo (faster = stronger) **and** average
    depth (deep strokes stronger than shallow).
  * Opt-in switch, default off; candidate default later. Confidence
    crossfade falls back to today's filtered chain when the rhythm is
    absent or unstable.

  **Open:** the detection method itself (adaptive oscillator / PLL vs.
  Kalman vs. autocorrelation / Lomb–Scargle) — leaning oscillator-family
  because it handles VRChat's irregular OSC sampling natively. Estimator
  + feel-model are developable and testable **offline** against
  session-logger recordings (no hardware). Full design in
  [`RHYTHM_ENGINE.md`](RHYTHM_ENGINE.md). _Pending._

## Networking & Multiplayer

- **Remote-control contacts.**
  Allow another VRChat player to drive the local user's toys by
  touching contacts with reserved names (e.g. `OGP/Remote/*`). Needs an
  allow-list so randoms can't grief, plus a kill-switch.

## VRChat Integration

- **Profile switching from the VRChat Expressions menu.**
  Map an integer avatar parameter (e.g. `/avatar/parameters/PurrProfile`)
  to profile slots so the active profile can be changed in-game without
  alt-tabbing. Configurable parameter name; out-of-range values ignored.
- **SPS priority layering.**
  While SPS contacts are actively firing, dim or mute the regular touch
  zones so the SPS sensation isn't drowned out by background contact
  hits. Per-profile toggle with a dim-amount slider.
- **Per-input max-value clamp.**
  Per-OSC-parameter ceiling (0.0–1.0) so a single zone or contact can't
  push a motor to full output. Lets users cap noisy or overly-eager
  inputs without rewriting the whole routing.
- **In-world leaderboard display.** _Planned, not designed yet._
  A display in VRChat (a shader on the avatar or a prop) showing the
  top 10 people by thrusts with you, from the per-person statistics.
  The hard part is the shader: OSC can only set avatar parameters, and
  an Int parameter holds 0–255, so names and counts would have to be
  streamed a slot at a time (row, character index, character code) into
  a shader that keeps them, e.g. in a custom render texture. Local-only
  parameters are enough for you to see it; letting others see it means
  synced parameters, which costs sync bits and bandwidth, so a slow
  trickle at most. Builds on the People statistics and the thrust
  counter parameters (both built 2026-10-08).

## Reliability & Lifecycle

- **VR-session-aware shutdown.**
  Detect when the VR runtime exits and either auto-quit OscGoesPurrr or
  at minimum send 0 to every connected device and stop output. User
  setting to pick which behavior.

- **Code signing.**
  The unsigned exe means every new user meets a SmartScreen warning on
  first run, which is exactly the wrong first impression for this kind
  of app. Worth pricing an OV/EV certificate once there are enough
  users to justify it.

## UI Modes

- **Mini-Mode / VR companion window.**
  A compact, always-on-top layout showing only the essentials (active
  profile, vibe meters, master toggle) for use as a desktop overlay
  while in VR. Toggle from the main window; remembers its own size and
  position.

---

_Not in scope here:_ bug fixes, refactors, or anything already tracked
in commits/PRs.

_For shipped features, see [README.md](../README.md) and the in-app Help
panel._
