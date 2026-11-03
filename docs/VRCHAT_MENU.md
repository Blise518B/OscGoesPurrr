# VRChat expression-menu control (OGP/*)

Everything you reach for mid-session is drivable from inside VRChat — how
strong it runs, how you're wired up, panic silence, sleep, and an "is
everything connected?" test pulse. No alt-tabbing out of VR.

| Parameter      | Type  | Values | Meaning                                   |
|----------------|-------|--------|-------------------------------------------|
| `OGP/Strength` | Float | 0–1    | Global output multiplier — scales toys, trackers, suits and e-stim together. This is the "a bit softer tonight" knob; it never touches your tuning. |
| `OGP/Mode`     | Int   | 0–3    | Active routing: 0 Combined, 1 Separate, 2 Custom 1, 3 Custom 2 (slot order — renaming modes in the app doesn't change the numbers) |
| `OGP/Off`      | Bool  | toggle | Panic silence. Everything stops instantly whatever the strength says; toggle off and your level returns untouched. |
| `OGP/Sleep`    | Bool  | toggle | Makes toys hard to wake: every chain's Wake stage switches to the stroke counter, so nothing plays until three full strokes land within six seconds. Buttplug toys only — no other backend has a Wake stage. |
| `OGP/Test`     | Bool  | held   | While held, every connected motor runs at a low fixed level (~20%) — enough to confirm the link without being a surprise. |

### Avatar Remote (`OGP/Remote/*`)

Your avatar board's controls in the menu itself: **Avatar Remote ▸** has
seven **Toggles** and seven **Radials**, and each one is a *slot* you give
a control — or a whole category — on the app's *My Avatar Remote* page: the
small circle in a card's (or a category's) top bar opens a radial like
VRChat's, Back at the top and 1–7 around it. A slot holds one thing; one
thing can sit in several slots. Toggles take toggles and hold buttons,
Radials take sliders and steppers; a category's slot drives every control
in it that fits. The menu drives the board of the avatar you're wearing
(its active preset), and its toggles and radials follow the board — on
while any of a slot's controls is ON, a radial where its first control
is. VRChat can't show the names (they're baked in at upload), so the menu
says *Toggle 1*–*7* and *Radial 1*–*7*; the page shows what has each.

| Parameter                     | Type  | Values | Meaning |
|-------------------------------|-------|--------|---------|
| `OGP/Remote/Toggle1`–`7`      | Bool  | toggle | On / off for the slot's control(s); a hold button is held while it's on. |
| `OGP/Remote/Radial1`–`7`      | Float | 0–1    | The slot's slider(s) or stepper(s), across each one's own min..max. |

### Friends (`OGP/Friend/*`)

The menu's **Friends** submenu acts on whatever you have picked on the
app's Friends page: one friend, or a group of friends (make one under
*Groups* and drag friends from the list into it; a friend can be in
several) — your first friend starts picked. Each friend only gets what they
allow you (their toys and shockers boxes for you). To drive **you and a
friend at once**, drag yourself (the top row of the list) into a group with
them: you're a member like any friend, so your own toys and shockers follow
the menu too — through your own shocker page, your caps and arming hold,
and Pause all friends pauses you as well. All unsynced, so 0 sync bits. The
Friends page tells you when the avatar you're wearing has this menu.

**Toys ▸**

| Parameter                  | Type  | Values | Meaning |
|----------------------------|-------|--------|---------|
| `OGP/Friend/Level`         | Float | 0–1    | Direct control of the toys picked under *Which toys*. Moving it ends an auto mode (Oscillate swings around it instead) — their card in the app switches to Direct control. Their toy runs at the higher of this and whatever their own avatar does (or yours alone with *Override*), scaled by their strength and inside each toy's own output band. |
| `OGP/Friend/Mode`          | Int   | 0–8    | *Auto mode*: 0 none, then Sine, Square, Triangle, Saw, Random, Heartbeat, Build-up, Oscillate. Plays on their side by itself. |
| `OGP/Friend/Speed`         | Float | 0–1    | How fast the auto mode runs (0 slow, 1 fast). |
| `OGP/Friend/Range`         | Float | 0–1    | How high the auto mode goes — for Oscillate, how deep it swings around Level. |
| `OGP/Friend/Override`      | Bool  | toggle | Your level replaces their own output on those toys while you drive them. |
| `OGP/Friend/Toy1`–`4`      | Bool  | toggle | *Which toys*: their toy 1–4 in the order their card lists them. All on (the default) means every toy they have. |
| `OGP/Friend/StopToys`      | Bool  | button | Level 0 and the auto mode off. |
| `OGP/Friend/Strength`      | Float | 0–1    | *Their strength* (in Friends itself): their strength slider, top left in their app — it moves on their screen too. Whoever moves it last wins. |

**Shockers ▸** — like PiShock's own controls, always inside their caps and
only a vibrate for anyone who hasn't armed shocks this session.

| Parameter                  | Type  | Values | Meaning |
|----------------------------|-------|--------|---------|
| `OGP/Friend/Shock`, `Vibrate`, `Beep` | Bool | button | One operation per press on the ticked shockers (the menu calls Vibrate *Shocker vibrate*). |
| `OGP/Friend/StopShock`     | Bool  | button | Stops their shockers now, a waiting warned shock included. |
| `OGP/Friend/ShockStrength` | Float | 0–1    | How strong, as a part of *their* cap: 1 is the strongest they allow (shocks under their shock cap, vibrates under their vibrate cap). |
| `OGP/Friend/ShockLength`   | Float | 0–1    | How long, as a part of their longest allowed pulse. |
| `OGP/Friend/Warning`       | Bool  | toggle | PiShock's Small warning: 1–3 s of vibration before each shock. |
| `OGP/Friend/Shocker1`–`4`  | Bool  | toggle | *Which shockers*: their shocker 1–4 in the order their card lists them. All on by default. |

(The old *Both of us ▸* submenu and its `OGP/Both/*` parameters are gone
after 0.14.1: a group with you and your friend in it does the same, and the
app no longer listens to them. An avatar that still has them keeps a dead
folder until you drag in the newer prefab.)

The app sets Level and Mode back on your avatar when it ends an auto mode or
stops (so the menu shows what's going on); for ~2 s after an avatar load the
Friends menu is ignored (VRChat replays defaults then, not your hand).

**Modes are routings, not intensities.** Switching mode changes which parts
of your avatar drive which motors — every socket combined onto one toy,
each socket driving its own, or whatever you set the two Custom slots to.
It does not change how strong anything is; that's `OGP/Strength` alone.

**Off and Sleep are session-only.** Neither survives an app restart, on
purpose: launching into silence, or into a sleep gate nobody remembers
arming, just reads as a broken app.

The sync is two-way for all four control parameters: changing something in
the app pushes it back to VRChat so your menu stays correct, and after
every avatar load or OSC reconnect the app re-asserts its whole current
state (for ~2 s after an avatar load it *ignores* incoming values, because
VRChat replays stale saved ones then — the app is the source of truth, so
an avatar swap can never yank your settings).

## Option A — VRCFury prefab (easiest)

Needs [VRCFury](https://vrcfury.com) in your avatar project (Creator
Companion → Manage Project → add VRCFury).

1. Download
   [`OscGoesPurrr-VRCFury.unitypackage`](unity/OscGoesPurrr-VRCFury.unitypackage)
   and drag it into Unity's Project window (or *Assets → Import Package →
   Custom Package*).
2. Drag **one** of the three prefabs from the new `Assets/OGP` folder onto
   your avatar in the Hierarchy — anywhere inside it:
   * **OscGoesPurrr Menu** — both: your own controls (Strength, Off,
     Sleep, Test, Modes, Avatar Remote) and the Friends menu, in one
     *OscGoesPurrr* submenu.
   * **OscGoesPurrr Menu (Self)** — only your own controls (Avatar Remote
     included).
   * **OscGoesPurrr Menu (Friends)** — only the Friends menu (Toys,
     Shockers, Their strength), as an *OGP Friends* submenu.

   (The files they use, icons included, are in `Assets/OGP/Menu`; leave
   them there.)

That's it. When you upload (or press Play), VRCFury adds the parameters —
unsynced, so 0 sync bits, and under their own names so the app can reach
them — and the submenu, every control with its own icon. Your avatar's own
menu and parameter files are never edited, so taking it out again is
deleting the object.

The submenu lands in your root menu. To put it inside another submenu
instead, select the prefab and type that submenu's name into the *Prefix*
field of its Full Controller.

If you used Option B on this avatar before, remove the "OscGoesPurrr"
submenu it added to your expressions menu. Otherwise VRCFury merges both
into one submenu and you get every control twice. The parameters it added
can stay.

A newer version of the package imports over the old one and updates it in
place; the prefab on your avatar picks the change up.

## Option B — one-click installer (no VRCFury needed)

1. Copy [`docs/unity/OGP_MenuInstaller.cs`](unity/OGP_MenuInstaller.cs) into
   your avatar project, anywhere under `Assets/` (e.g.
   `Assets/OscGoesPurrr/Editor/`).
2. Select your avatar in the Hierarchy.
3. Run **Tools → OscGoesPurrr → Install VRChat Menu**.

That's it — it adds all the parameters (unsynced, 0 sync bits), builds the
"OscGoesPurrr" submenu (a strength radial, Off, Sleep, the Test button, a
Modes submenu and a Friends submenu), and links it into your expressions
menu. Re-running
it later is safe (it updates in place, never duplicates), it never mutates
SDK-shipped default assets (it clones them into `Assets/OscGoesPurrr/`
instead), and it works the same on VRCFury-managed and plain avatars — it
edits the avatar descriptor's own assets, which VRCFury preserves at build
time.

## Option C — manual setup (plain Unity, ~10 minutes, no FX layer needed)

Because these parameters only talk to OSC — they don't drive any
animations — you don't need an animator controller at all. Two assets:

1. **Expression Parameters** (your avatar descriptor → Expressions →
   Parameters asset). All of these are **Saved: off, Synced: off** —
   unsynced parameters cost 0 sync bits, OSC works fine with them, and the
   app re-asserts every value on avatar load anyway:
   * `OGP/Strength` — type **Float**, default `0.85`.
   * `OGP/Mode` — type **Int**, default `0`.
   * `OGP/Off` — type **Bool**, default off.
   * `OGP/Sleep` — type **Bool**, default off.
   * `OGP/Test` — type **Bool**, default off.

2. **Expressions Menu**: create a submenu (e.g. "OscGoesPurrr") and add
   eight controls:
   * One **Radial Puppet** bound to `OGP/Strength` (as its *Rotation*
     parameter). Name it "Strength".
   * Four **Toggle** controls, all bound to parameter `OGP/Mode`, with
     Value = `0`…`3`. Suggested names/icons: 🔗 Combined, 🔀 Separate,
     🃏 Custom 1, 🎲 Custom 2. Because they share one Int they behave like
     radio buttons — tapping a mode switches to it.
   * One **Toggle** bound to `OGP/Off` — name it something you'll find
     fast in a hurry. This is the panic button.
   * One **Toggle** bound to `OGP/Sleep`.
   * One **Button** control bound to `OGP/Test` — a Button (not Toggle) is
     momentary: the pulse runs only while you hold it.

For Avatar Remote, add `OGP/Remote/Toggle1`–`7` (Bool) and
`OGP/Remote/Radial1`–`7` (Float), and a submenu with two submenus of its
own: seven Toggles (Value `1`) and seven Radial Puppets.

For the Friends submenu, add the `OGP/Friend/*` parameters from the
tables at the top the same way (Toy1–4 and Shocker1–4 default **on**,
Speed `0.5`, Range `1`, Strength `0.85`, ShockStrength `0.25`, ShockLength
`0.1`, the rest off or 0) and lay them out as the tables do: radials for
the Floats, Buttons for the buttons, Toggles for the toggles, and for *Auto
mode* eight Toggles on `OGP/Friend/Mode` with Value `1`–`8`. A menu holds 8
controls at most, so Toys, Shockers, Auto mode, Which toys and Which
shockers are submenus of their own.

Upload, and you're done. (If you'd rather not click through Unity
inspectors, use Option A or B above — same result.)

## Showing on your avatar which toys are connected

The app can also tell your avatar whether a toy is connected, so the
avatar can light an icon, swap a material or switch an object on. These
are plain **Bool** parameters you name yourself; both kinds are off until
you switch them on.

| What | Where to switch it on | Default name | True while |
|---|---|---|---|
| Any toy | Settings → Connection Settings → *Tell VRChat while any toy is connected* | `OGP/ToyConnected` | at least one toy is connected |
| One toy | Home → open the toy → *Tell VRChat while this toy is connected* | `OGP/<ToyName>Connected` | that toy is connected |

Add a Bool with the same name to your avatar's Expression Parameters
(unsynced is fine if only you need to see it; synced if others should),
and drive whatever you like from it in your FX layer. Two toys given the
same name share one parameter — true while either is connected.

The app sends the values again every time you change avatar or VRChat
reconnects, and sets them all to false when you close it, so an avatar is
never left showing a toy that is gone. If your parameter is a Float or
Int instead of a Bool it receives 1 and 0.

## Thrust counters for a counter display

Settings → Connection Settings → *Send thrust counters to VRChat* (off
until you switch it on) sends three counters as **Int** parameters — the
same numbers as the Statistics page:

| Counter | Parameter | Counts | Digits |
|---|---|---|---|
| Total | `OGP/Thrusts/Total` | every thrust on record | `/D1` … `/D7` |
| Session | `OGP/Thrusts/Session` | since the app started | `/D1` … `/D5` |
| Pace | `OGP/Thrusts/PerMin` | thrusts in the last 60 seconds | `/D1` … `/D3` |

An avatar Int holds 0 to 255, so the plain parameter stops at 255 (enough
for "more than 50 per minute" in an animator). For a number display use
the digits: each is an Int 0–9, `/D1` the ones, `/D2` the tens, and so on
— `OGP/Thrusts/Total/D3` is the hundreds of the total. A number with more
digits than its counter has shows all nines.

Add only the parameters your asset uses. Unsynced is enough when only you
need to see it; synced costs 8 bits per Int.

Like the parameters above, everything is sent again when you change avatar
or VRChat reconnects, and only changes go out in between (at most once a
second). The pace goes to 0 when you close the app or switch the counters
off. With Usage statistics off (Settings → Features) there is nothing to
count, so nothing is sent.

## Troubleshooting

* **Nothing happens when you tap the menu** — VRChat caches a per-avatar
  OSC config that whitelists parameters. If you added the parameters to an
  avatar you've used before, close VRChat, delete
  `%USERPROFILE%\AppData\LocalLow\VRChat\VRChat\OSC\` (just the folder —
  it regenerates), and reload the avatar.
* **The menu is out of step with the app** — make sure OSC is connected
  (sidebar pill); the app re-sends the whole control set on every change,
  avatar change, and reconnect.
* **Everything is silent and Off is not on** — check the strength radial;
  a puppet parked at 0 is silence that looks like a bug.
* **Sleep seems dead** — that's the point: it takes three full strokes
  inside six seconds before anything plays. An accidental brush can't
  trigger it.
* **Switching modes did nothing** — modes are routings. If both modes
  route the same motors from the same zones, they feel identical; set them
  apart on Home → the toy → the motor's chain → Input.
