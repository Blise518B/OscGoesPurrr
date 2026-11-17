# Project: OscGoesPurrr — toys-first edition (`release/lite`)

A VRChat OSC → haptic router for Buttplug.io toys via Intiface. Python
3.10+, PySide6 UI, Windows-first, with a Linux AppImage since 2026-10-05
(ARCHITECTURE.md § "Linux" has the few places the code differs).

**This branch is the public, shareable build.** The other haptic
backends — main's SteamVR tracker haptics, DG-Lab Coyote, The Handy —
live on `main` and are deliberately *not* here.
Don't re-add one on a whim: the point of this branch is a small surface
a stranger can install and understand. If a backend genuinely needs to
come back, follow ARCHITECTURE.md § "How to add a new haptic backend"
and port it from `main` rather than reinventing it.

**PSVR2 headset rumble came back (2026-11-14, Blise's ask)**, ported
from `main` (`psvr2_capi.py` / `psvr2_engine.py` / `psvr2_router.py`,
`controllers/psvr2_facade.py`, `ui/views/psvr2.py`): one page of its own
with its own headset icon, `feature_psvr2` **off by default**, offered
in "What are you here for?" and Settings → Features, Windows only (the
user's own PSVR2Toolkit, never bundled). Off, VRChat quiet and its own anti-stuck (the PSVR2 page's Contact card)
hold for it, and the engine is the last gate (a
level not re-sent plays nothing).

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
out, never spin boxes (they were cut off). **Each shocker has its own On /
Off (Blise's ask, 2026-10-28: only the ones in use):** an Off card stays
where it is, greyed out with a grey frame, its switch the one thing lit
(his call: not folded, not moved). Off is enforced in the engine --
`set_shockers_off`: stopped at once, every send refused, and
`shockers()` / `shocker_ids()` leave it out, so behaviours skip it (its
chips grey), friends and the web remote never see it (their slots are
numbered among the shockers in use), Home's row leaves it out;
`all_shockers()` is the page's list. Remembered (`shockers_off`).

**OpenShock joined it (2026-10-07, Blise's ask)**: the same hub link also
speaks OpenShock firmware (`openshock_serial.py` — PiShock's 2023 / Lite
hubs reflashed, or a DIY ESP32 board), picked by whichever firmware
answers the handshake. OpenShock keeps no shocker list over serial, so the
page holds one (model + transmitter id; Beep pairs a collar). The page and
sidebar entry are called **Shockers**; the code, the feature key and
`pishock_settings.json` keep the `pishock` name. Still USB only — no
PiShock or OpenShock cloud API.

**The shockers after friends' reviews (Blise's calls, 2026-11-14).** Keep
these true (the engine is still the last gate for all of them):
* **Holds are per source** (`hold` / `release(..., source=)`: the rules
  router, each friend, Me, each web-remote browser): the strongest plays,
  **kind first -- any shock beats any vibrate, any vibrate any beep** ("the
  shockers have priority") -- then level; one source letting go ends only
  its hold, and one that stops topping up for `HOLD_SOURCE_TTL_S` stops
  counting. Caps, arming, the longest hold and the rest after it stay per
  shocker for every source together. A new caller passes a `source`.
  Your own behaviours pick among themselves the same way, kind first
  (`pishock_router._stronger`, Blise's call 2026-11-16; an unarmed shock
  ranks as the vibrate it becomes), and so does a pulse taking over a
  running one in the engine (2026-11-17: "a shock should always take over
  vibration or beeping") -- the run cap and the rests still hold for it.
* **Shock / Vibrate / Beep per shocker** (`set_ops_off`, `op_allowed`,
  `shocker_ops_off`): a switched-off action is refused whoever sends it and
  stops at once if running. `SHOCK_OFF_AS_VIBRATE = False` is his call: a
  shock with Shock off is dropped, never sent as a vibrate. A friend's
  panel greys what they can't do, with the reason
  (`remote_protocol.shocker_why` / `can_warn`, from `st`'s `sop` / `soff`),
  never hides it; the web remote says it word for word. A shock due a
  warning on a shocker that can't warn (Vibrate and Beep both off) is held
  back and logged.
* **No per-friend share** (removed, Blise's call 2026-11-17: "all friends
  should be able to do the same thing" -- Friends is about friends, and your
  own limits live on the Shockers page): every friend, a group, Me and the
  web remote get the same -- each shocker's own caps, switches, arming and
  timing. The only split is your avatar vs friends, through *Separate limits
  for friends*; nothing is customized per friend. Don't bring one back; an
  old `share` in `friends.json` is dropped on load, and a test build's
  `fw` / `nc` in `st` are ignored.
* **Arming asks, on Home and on the page alike** (`shocker_switches.py`,
  `ARM_ASKS_FROM`): "Arm shocks? Yes / No" in the switch's own place (never a
  popup), back to off after `ARM_ASK_S`; off never asks. Red words beside
  it say Shocks armed / Shocks not armed (role `alert`, no hex). Both places
  draw from the one setting in `settings/pishock.py` and keep no copy.
* **Limits read as limits:** boxed under *Limits*, every label "Up to …"
  except "At least a rest of" and "Then a forced break of"; nothing on that
  box sends.
* **Separate limits for friends** (Blise's call, 2026-11-17; `separate_limits`,
  **off by default**): one switch in the Every shocker card's Limits box.
  Off is the one set and one count for everyone, exactly as before. On, the
  timing -- rest after a pulse, longest hold, forced break -- comes twice,
  each with its own values *and* its own count: your avatar
  (`GROUP_AVATAR`: behaviours, ShockOSC's, your avatar menu through Me, the
  page's tests) and friends (`GROUP_FRIENDS`: every friend, Me on the page,
  the web remote). The engine keeps an `_Account` per group on each shocker,
  written together while off; switching off joins them the strict way. The
  caps come twice too (Blise's call, same day): friends' own max shock, max
  vibrate and longest pulse, hub-wide, which only ever lower each shocker's
  own for `GROUP_FRIENDS` -- min(the shocker's, the friends') in
  `PiShockEngine._caps_of`, so the engine is the gate; your avatar keeps
  each shocker's own. Arming and the switches stay shared. The friends' set
  starts as a copy (the hub's timing, each cap the highest any shocker has,
  so switching on lowers nobody), friends are told their own caps (`slim`)
  and longest hold, and switching it on or raising a friends' value asks on
  Ctrl+Z. A new shocker caller passes its `group` (`shock_group` for Me).

**A modified client gains nothing (Blise's rule, 2026-11-16:** "it should
for sure be corrected to the safe limits"**).** Whatever a friend's OGP, a
web-remote browser or the avatar menu's OSC sends that OGP itself never
would is corrected on the receiving side to the app's own limits, or
refused and logged. Keep these true: every reader cleans every field and
never raises (infinities and huge numbers included); a warning is a
vibration (a beep only where Vibrate is off) of at least
`remote_protocol.WARN_MIN_MS`, and it plays in full before its shock; a
friend's pulse passes the shocker's own longest pulse as `run_cap_ms` (the
engine's rules are for every source: a run of stronger pulses can't outlast
one longest pulse, nothing goes in during the rest after the longest hold,
a hold waits out a pulse and its rest); how often a
sender may make your shockers or avatar act, or change your toy cards
(`CARDS`: a change costs one, a top-up nothing; Me isn't budgeted, its loop
isn't throttled), is `inbound_rate`'s budget per sender, checked first, and
letting go is never limited (past the cards' budget only it lands, counted,
and never as Sync with others' newest); shock ids are kept per sender; a browser that sends what only an OGP sends is not listened to.
A new message or field gets the same treatment, plus a test in
`tests/test_receiver_clamps.py`. **YOLO is the exception by design**
(Blise's call, 2026-11-16: "it's supposed to cause some chaos"): with it on,
a friend may set any avatar parameter, `OGP/*` and `ShockOsc/*` included --
don't take those out of `settable()`; the shocker engine's caps still hold.

**ShockOSC (2026-11-14, a friend's ask):** an avatar's `ShockOsc/`
parameters set up in one click on the Shockers page (`shockosc.py`,
`controllers/shockosc_facade.py`, `ui/views/pishock_shockosc.py`): a touch
becomes a Contact with *Touch for at least* (`hold_ms`), the instant ones a
pulse-once Contact, the continuous ones a Continuous, a PhysBone the **Pull**
kind (`pulls`). Names verified against ShockOSC 3.2.0's source; it is
**AGPL-3.0 -- names only, never its code**. Keep these true: its behaviours
start with a new behaviour's own values (`settings.pishock.new_rule_values`)
-- but a touch keeps ShockOSC's `TOUCH_HOLD_MS` (0.25 s, his call 2026-11-17:
a brush does nothing) --
and the avatar's `_Config` settings and those behaviours' values are one
value each, kept in step both ways (`controllers/shockosc_sync.py`; Blise's
call, 2026-11-16: "we don't have like two separate settings") -- `_All` is
the default each group follows unless the avatar has the group's own, OGP
first after an avatar load, never an echo, YOLO friends may set them;
Paused (a group's, or the global one as a kill switch) stops whatever those
behaviours are running at once, like Stop, and switches them Off; `_Next*`
only ever make the next action gentler; a strength of 0 sends nothing; and
nothing from the avatar reaches past the engine's caps; the feedback (`shockosc_feedback.py`) comes
from `PiShockEngine.activity()`, counts only shocks, sends changes only and
is woken by the engine, never polled.

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
right now, and Sync with others is the toy owner's call alone (Blise's call,
2026-11-17: *Sync friends* on their Friends page, on by default, for every
friend, the web remote and Me; a sender's own say is ignored): on,
everyone driving shares one set of toy cards and the receiver plays only
the newest change, once; off, each drives on their own (highest wins).
Their panels hear it as one bit in `st` (`sep`) and show SYNCED /
SEPARATE, read-only. The
newest is decided on versions the receiver vouches for
(`friends_receive._sync_version`, 2026-11-17): honest numbers pass as they
are, but only a real change on the cards gets past the newest, so a sender
saying "newer" without one takes nothing. It
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
never name it to real friends. **Groups (Blise's calls, 2026-10-29):** a
group's panel shows only its members, as chips with an ×, never a list of
every friend (it gets long) -- members come by dragging a row from the
list onto the group's row or its members box, Me included; and a group
with Me in it is how the avatar menu drives you and a friend at once (its
old Both of us submenu and `OGP/Both/*` are gone). The list's toy / bolt / remote column icons
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
strength and the owner's SYNCED / SEPARATE (`assets/remote-toys.js`), PiShock's panel
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

**Friends linked to VRChat accounts (2026-11-14, Blise's calls)**
(`vrcx_friends.py`, `controllers/friends_vrchat.py`,
`ui/views/friends_account.py`): a friend's panel picks their VRChat account
from your instance or from VRCX, or a chip is dragged onto their row; the
VRChat name sits *under* the nickname, smaller and muted. Keep these true:
stored on this PC only, by `usr_` id (`vrc` / `vrc_name` in `friends.json`),
**never sent to anyone**, and the system log never names the account;
VRCX's database is read-only, only on the Import click, its list kept in
memory; reading VRChat's log is the Friends page's own opt-in (`friends_vrc_log`,
off), apart from People statistics' consent, though one `LogWatcher`
(PeopleFacade) serves both; one account per friend. **Only friends in my
instance** (`controllers/friends_instance.py`; `instance_only`, a friend's
`anywhere`, the web remote's `anyway`, all off by default) builds on it and
**fails closed**: with the log off nobody is here, an unlinked friend is not
here, Me always is; a refused friend or browser is held like Pause (zero at
once) and logged. Your own log decides -- nothing new on the link but one
bit, `nh` in `st`, so their panel says *Not here*: never an instance, world,
id or name. **Pop out** (`ui/views/friends_window.py`) is one window that
follows the page's pick, never reopens by itself at launch, opens no popup
inside, and keeps its title `OscGoesPurrr · Control` (overlays find it by
it); **↻ / Check all** dial outside the background budget but at most once
per friend per `CHECK_GAP_S`.

**The log, per person (2026-11-14, Blise's ask)** (`event_log.py`,
`controllers/log_facade.py`, the Log page after Statistics, shown while
Friends or the Shockers are on): one record per event -- who, kind, op,
direction, level, why held back -- from `_friends_note(text, who=..., kind=...,
...)` (pass who and what; `{who}` in the text becomes the name) and the
shocker router's `report=` ("Your avatar"). Keep these true: one JSON Lines
file per day in `<settings>/event_log/`, **never a `.json`** (settings
backups copy every `.json`), kept `KEEP_DAYS` (30); `add()` never touches the
disk (its own writer thread); **never sent** -- friends see only their own
panel. **Statistics count it** (`stats_events.py`, sealed and pure;
`controllers/stats_events_facade.py`, `ui/views/statistics_whom.py`): every
shock / vibrate / beep that reached you, per shocker and per source, friends'
drive time and Avatar Remote sets, from the log's events -- no second
record of its own. Only what came *in*; friends' names kept unless *Keep
friends' names* is off (`stats_friend_names`, his call: kept by default);
never sent. A new shocker rule kind appends `behaviour_name(kind, rule)` to
its records, so statistics and the log can name it.

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
reads its `avatars/*.json`, never writes them. **Your avatar's menu drives
the board too (Blise's design, 2026-10-29):** OscGoesPurrr ▸ Avatar Remote
has seven Toggles and seven Radials (`OGP/Remote/*`, in the Self and Both
prefabs), each a *slot* a control or a whole category takes -- the small
circle in a card's or category's top bar opens a radial like VRChat's,
Back at the top and 1-7 clockwise (`ui/views/param_slots.py`, in the
window, never a popup). A slot holds one thing, a thing can take several;
toggles take toggles and hold buttons, radials sliders and steppers; per
preset (`param_board` `slots`); your own menu ignores locks (they're for
friends). Menu and board agree OGP first like the Friends menu
(`controllers/params_menu.py`).

**Height on the Avatar Remote (2026-11-14, Blise's calls)**: VRChat's
`/avatar/eyeheight` as one compact Height box under the categories
(`avatar_height.py`, `controllers/height_facade.py`,
`ui/views/param_height.py`). It comes with a friend's AVATAR switch (no fourth
switch) and has its own On / Off, on by default; Grow glides, Right away
jumps; it **stays** where a friend put it (not a held control). Keep these
true: the range starts at VRChat's menu range (0.2-5 m), nothing outside
0.1-100 m is ever sent, and a friend can't widen it; sent on change at a
gentle rate; greyed while the world forbids scaling; Pause all, locks and
Only friends in my instance gate it like any set (`_params_blocked(peer)`);
the eyeheight keys are never parameters (`param_filters.NOT_PARAMETERS`: off
the lists and YOLO); your menu drives it from a Radial slot (`HEIGHT_SLOT`),
so the prefab didn't change; the web remote's box is 1-to-1. **Dragging a
control back to the list removes it** (own board only): a control goes at
once with an Undo, a whole category asks first, and each is one reversible
action (`BoardBook.take_control` / `take_category` -> `put_back`) that
Ctrl+Z takes over.

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
set, plus the README / site / What's new lines, in a release of their own
-- each suit has its own anti-stuck (since 2026-11-17, see *Anti-stuck per
device* below). Contacts are shared both ways by default (Blise's
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
dashed amber rings on her for what's missing. **Haptic trackers joined
the page (2026-11-07, Blise's ask: "support the trackers like Haptic
Pancake")** -- see below. She's ChatGPT-drawn line art
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

**Haptic trackers (2026-11-07, Blise's calls)** buzz SteamVR trackers that
have a motor: a Vive Tracker with a Haptic Pancake on its pogo pins, a
Tundra with a Tundra Tapper, a controller set up as a tracker
(`tracker_engine.py` through OpenVR as a *background* app -- it never starts
SteamVR; `tracker_spots.py`; fed by `suits_router.py`; on the Suits page as
blue pucks). `feature_trackers`, **off by default**. They sit on **Haptic
Pancake's nine spots** -- head, chest, hips, elbows, knees, feet -- each
following **Pancake's parameter names** by default (`HapticHips`,
`HapticFootLeft` ...) so a Pancake avatar works with no setup; a spot can
follow several (strongest wins). A tracker goes where its **role in
SteamVR's Manage Trackers** puts it (read from `steamvr.vrsettings`); one
without a usable role is listed under the chips with Buzz and *Place on
her*, the next click on a spot puts it there (`placed` in
`suits_settings.json`, by serial). Keep these true: the engine is the last
gate -- a level not re-sent for `LEVEL_TTL_S` plays nothing, each spot's
**Top** (default 80 %: Pancake's guide warns a plain motor overloads the
Vive Tracker's pin at full) can't be widened, paused refuses everything;
Off / VRChat quiet / the trackers' own anti-stuck hold as for the suits; only
GenericTracker devices -- never OGP's own toy devices, never Standable's
virtual ones. **Haptic Pancake is GPL-3** (and main's old SteamVR engine
was adapted from it): this one was written from the documented timings
(Vive: value 50 every 50 ms; Tundra: microseconds, every 4 ms) -- learn
from it, never copy its code. OpenVR loads only when the switch is on.

The other SteamVR piece this branch carries is display-only: Settings →
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

**Ctrl+Z / Ctrl+Y anywhere (Blise's ask, 2026-11-14):** one history of the
last five settings changes for the whole app (`settings_history.py`,
`ui/history_keys.py`, `controllers/history_facade.py`). It records where
settings are *saved* -- every `settings/_base.py` store tracks itself -- so
like the wheel guard, **a new setting gets undo for free**. Only saves right
after the user's own input are steps (a friend, the avatar menu, OSC or a
timer never is); nothing that already happened is undone. A new setting
that isn't one (a fold, a seen flag, a window place) goes in its store's
`history_ignore` or app settings' `NOT_SETTINGS`; one that **loosens
shocker safety, widens what a friend or the web remote may do, or raises a
limit goes in that store's `history_asks`**, so the undo asks as doing it by
hand would. A shocker behaviour coming back doesn't ask (his call: "No,
caps are enough"). A store whose engine must hear about an undo: one line
in `HistoryFacade._history_hooks`.

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

**The guided tour (2026-11-14, a friend's ask)** runs on help mode's
drawing (`ui/tour.py`, `ui/views/tour.py`, `controllers/tour_facade.py`), its
steps in `ui/tour_steps.py` next to `page_steps` -- where a page step says
it, the tour step *is* that step (`from_page`), so the gallery, Help and the
tour tell one story. A new install gets it after "What are you here for?",
an older one is offered it once as a bar (`tour_offered`), never again by
itself; Help and Getting started run it again. Keep these true: it moves on
when the real thing happens, only the lit control takes clicks, it **never
writes a setting** (arming is look-only), and help mode and the tour take
turns. Change a page, bring its tour steps along -- `tests/test_tour.py`
finds every step's control on the real pages.

**"What are you here for?" (Blise's ask, 2026-10-27)** picks the features
someone uses: a new install asks it at its first launch, an older one once
on the update that brings it, then never again by itself (Settings →
Features → *Choose what you use…*). Each choice is a feature switch
(`src/interests.py`); it starts from the switches as they are, so nobody
loses one they use, and Skip changes nothing. A new feature switch gets a
choice there too -- `tests/test_interests.py` fails without one. Features
is the first card in Settings.

**Off while you're away (2026-11-14, a friend's ask; Blise's calls):** while
VRChat's `AFK`, GoGo Loco's AFK button (it sets `VRCEmote` = 101; GoGo Loco
has no AFK parameter of its own) or a parameter you picked is on, everything
is held off (`away_off.py`, `controllers/away_facade.py`, Settings → Safety). **On by default.** It is the same Off as `OGP/Off`, *held*
(`ModeManager.held_off`), so the user's own switch is never touched and
everything comes back by itself: gate output on `is_output_off()` (switch or
hold), show the switch with `is_off_switch_on()`. **It holds only while
VRChat runs** ("It should just be active if you're actually AFK within VR
chat and no other time"): VRChat closing (`osc_status` False -- mDNS gone or
two failed health checks, never the 10 s quiet monitor, which fires while
you stand still AFK) lets go, and the store's leftover values don't count
until VRChat says them anew. Event-driven, off every routing path.

**Low latency is load-bearing too.** This is a real-time haptics router:
minimizing OSC-in → device-out latency is a first-class priority. Don't
add queue hops, fixed delays, or ack-blocking waits to any routing /
engine / dispatch path; prefer direct dispatch, fire-and-forget sends,
waking on change over polling, and per-feature send caps for hardware
safety. On Windows a wait shorter than ~16 ms is only kept by a
high-resolution timer (`precise_alarm.py`, `time.sleep`): a QTimer past
Qt's 16 precise ones, `Event.wait` and asyncio's timeouts all round up to
the 15.6 ms clock step (measured 2026-11-13). The routing tick keeps a
steady beat on purpose -- its speed / punch maths measure change per tick.
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
with its "Take me there" buttons; it doesn't scroll, so a release's page
holds about ten two-line items -- group by area past that), commit, run
`tools\release.bat`. It runs the tests, builds the exe, then publishes **one
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

**The demo has the 0.14 pages too (Blise's ask, 2026-10-28):** Friends,
Shockers and My Avatar Remote (`docs/assets/demo-friends.js`,
`demo-shockers.js`, `demo-avatar.js`, loaded by `demo-pages.js`; styles in
`demo-pages.css`), the sidebar with the app's icons (`demo-icons.js`, written
by `tools/make_demo_icons.py` from `ui/icons.py` -- rerun it, never edit),
Home as Devices (the getting-started strip, two-line toy rows with the
Touch / Penetration chips that open the toy's card on the Toys page, the
shocker row's Arm shocks with its question and red words, a PSVR2 row while
that switch is on), the Toys page (Scan now, the toy server, the cards, SPS
Sources and Tuning tools folded), the Log page (`demo-log.js`, one log the
Friends page writes to), and Settings → Features first, each with its icon
(a switch hides its page, as in the app). A friend's panel
there is the web remote's own pieces, and their styles live in one shared
file, `docs/assets/remote-panel.css`, scoped under `.rpanel` (the site's own
`.btn` / `.head` / `p` rules would leak in otherwise) -- remote.html links it
too, so change the panel's look there, once. Your own row ("you") is the
app's Me: its levels reach the demo's toys through demo.js `setDrive`, the
app's `_apply_friend_drive` rule (your strength, Off, each toy's band;
Override replaces); its shockers are the Shockers page's, its board My
Avatar Remote's. A demo friend has nobody at the other end, and the page
says so in its intro (only toys, the shocker hub, the suits, the headset,
friends, VRChat's log and VRChat are simulated). **Suits joined it (2026-11-11, Blise's ask: a
bHaptics vest as the example):** `docs/assets/demo-suits.js`, its sidebar
entry shown while Settings → Features has a suit on. The demo's PC has a
TactSuit Pro vest connected with bHaptics switched on -- like the shockers
and Avatar Remote, on in the demo though a new install starts them off --
and OWO switched off, My OWO connected for whoever switches it on
(`#demo=suits` switches both on). Each suit switched on has its Home row
under the shocker hub (home_devices.py's words, On / Off and the sharing
switch), and each frame its Tell VRChat card. Her drawings are copied from
`src/Images/suits` into `docs/assets/demo/suit-*.png` and tinted with the
accent, every dot and patch at `body_view.PLACES` (ported, so new drawings
or dots mean re-porting). The avatar has the vest, head and four front OWO
contacts; nothing on it touches the suits, so only a held dot and a part's
Feel it reach Right now. The haptic trackers aren't in the demo yet. The
demo's sidebar scrolls when it runs out of room, as the app's does.
Change one of these pages in the app → bring its demo page along and
compare with `tools/app_shots.py --dump <dir> --size 1100x2600`.

**The user guide (2026-11-14, Blise's pick: Docusaurus, after osc.toys and
docs.vrcft.io)** lives in `guide/` (pinned Docusaurus, local search only,
the site's tokens.css and Aldrich; Neon / Midnight on the colour toggle) and
is committed built in `docs/guide/`, served at /OscGoesPurrr/guide/.
Change a page in `guide/docs/`, then run `tools/build_guide.py` (windowless)
and commit both; `tests/test_guide_build.py` fails while docs/guide/ is
older than guide/. Screenshots come from `tools/make_guide_images.py`
(app_shots' demo window), never mock-ups -- change a page of the app,
re-render its shots. Every path in `guide/docusaurus.config.js` stays
relative: Docusaurus puts the config into the public JavaScript, and an
absolute path would publish this PC's folders. Bring the guide along when a
feature changes, like the site.

**The VRCFury menu prefabs** (`docs/unity/OscGoesPurrr-VRCFury.unitypackage`,
Option A in `docs/VRCHAT_MENU.md`) are attached to every release under that
fixed name by `release.bat` (Blise's ask, 2026-10-28: more visible), so
`releases/latest/download/OscGoesPurrr-VRCFury.unitypackage` is the link
everything uses -- the README's "Your avatar's menu" section, the release
notes' Install section, the site, and the app: Settings → VRChat menu (right
after Features: whether the worn avatar has each part, live), the Friends
page's tip and an optional fourth step in Home's Getting started (it never
holds the card open). The links live in `ui/views/avatar_menu.py`. They are
built, never edited by hand -- three in one package (Blise's call,
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
package duplicates every asset instead of updating it). The shocker
Vibrate buttons are labelled **Shocker vibrate** (Blise's call,
2026-10-28: "Vibrate" read as the toys'); the parameters keep their names.

**The avatar menu and the app agree, OGP first (Blise's call,
2026-10-28).** A Friends menu change drives the picked friend through the
same `set_friend_*` setters as the page (`source="menu"`), so the page
shows it live; a change on the page -- the picked friend's All their toys
card (level, auto mode, speed, range, Override) or their strength -- is
sent to the menu's own parameters (`friends_menu._menu_follow`), never one
the menu just sent. After an avatar load VRChat's replayed values are
answered with OGP's (`_menu_send`, also on every OSC (re)connect through
`_send_ogp_state_out`), as for your own controls.

**"It's connected" avatar parameters (Blise's calls, 2026-11-05):** every
toy, the bHaptics suit and each part you have, the OWO suit, and the
shockers (any, and each one) send a Bool that is true while it's connected
(`controllers/presence_facade.py`). **All on by default**, under fixed
names an avatar asset can be built against -- `OGP/ToyConnected`,
`OGP/<ToyName>Connected`, `OGP/BHapticsConnected`,
`OGP/BHaptics<Part>Connected`, `OGP/OWOConnected`, `OGP/ShockerConnected`,
`OGP/Shocker<n>Connected` (n = the card's place on the Shockers page),
`OGP/PSVR2Connected` -- each renamable and switchable where its device is
set up (the Toys page's toy card, Settings → Connection Settings, the Suits
page, the Shockers page's hub and shocker cards, the PSVR2 page). Don't rename a default: assets rely on them.

**SPS 3 (2026-11-13, after OscGoesBrrr v2.1.31-34):** VRCFury 1.1443.0
renamed the zones to `OGB/Socket/...` / `OGB/Plug/...` and measures depth
with VRChat's contact-receiver extras; `parameter_store` stores them as
`Orf` / `Pen` and `sps3_zone.py` reads the new contacts (ARCHITECTURE.md §
Brain). Keep these true: `OGB/Enabled` rides the presence beat next to
`OGB_ENABLED` (without it such an avatar's plug and socket touch receivers
stay off); touch on an SPS 3 avatar is its closeness in the Depth channel
**plus** VRChat's hand speed struck into the Speed channel, mixed by the
chain's Combine (Blise's call: both, not OGB's speed-only); older avatars
behave exactly as before. OscGoesBrrr is GPL-3 since v2.1.34: learn from
it, never copy its code.

**Toys keep their place (Blise's ask, 2026-10-28):** connected toys are in
the order they connected (`intiface_facade.get_connected_toys_in_order`;
a newcomer goes last), each with its number in its row's corner, and
friends get them in that order -- so the menu's Which toys 1-4 are Home's
1-4. Never sort them by name again.

**The sidebar's order (Blise's call, 2026-11-17):** Home, Friends, then the
devices in Home's own order -- Toys, Shockers, Suits, PSVR2 -- then My
Avatar Remote, Statistics, Log; Help's tiles follow it (`view_names` and
the nav list in `ui_components.py`, the demo's `NAV` in `demo.js`).

**Toys have a page; Home is the overview (Blise's call, 2026-11-14):**
the detail lives on each device's own page, Home shows every device at a
glance with its quick switches. The **Toys** page (`ui/views/toys.py`, gated by
`feature_intiface`) holds the toy cards and
their chains, Scan now, the toy server and the SPS Sources and Tuning tools
folds -- SPS Sources is no longer a Tools page. Home keeps Getting started,
Devices + Test all and a row per device ending in ›; a toy's row opens its
card on the Toys page (`open_toy_card`). One builder makes both a toy's
bars (`device_frame._build_toy_bar`), so anything added to one reaches the
other; the modes and total strength stay in the sidebar. **Who a toy
feels** is a true 2×2 per chain -- touch / penetration × self / others
(`contact_filters.py`, `motor_N_cK_<pair>`), migrated without loss with a
`modes.json` backup kept -- shown as four chips on the toy's bar (they set
the active mode only, the default nobody overruled) and in each chain's
Input stage.

**Anti-stuck per device, Sleep per toy (2026-11-17, Blise's calls).** No one
global anti-stuck: the toys (Toys page, `toy_antistuck_*`), the bHaptics
suit, the OWO suit, the haptic trackers (Suits page) and the PSVR2 (its
Contact card) each have their own switch and timers (`antistuck.py`); a
file without its block starts as a copy of the toys' values, once. Each
toy's bar has Sleep over Anti-stuck beside the chips: Sleep is that toy
alone in the stroke-counter wake, session-only (the sidebar's Sleep still
sleeps every toy and lights every chip); a toy's Anti-stuck is a rig key in
its wiring, on by default, counting only while the toys' is on. Keep these
true: switching any anti-stuck off or lengthening a timer asks on Ctrl+Z
(`history_asks`); the timers are sliders, never spin boxes; friends' drives
are not held back by a sleeping toy or one without anti-stuck. Settings'
card is **Safety** (Off while you're away + a button to each page).

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
