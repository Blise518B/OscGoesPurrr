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

## Option A — one-click installer (recommended)

1. Copy [`docs/unity/OGP_MenuInstaller.cs`](unity/OGP_MenuInstaller.cs) into
   your avatar project, anywhere under `Assets/` (e.g.
   `Assets/OscGoesPurrr/Editor/`).
2. Select your avatar in the Hierarchy.
3. Run **Tools → OscGoesPurrr → Install VRChat Menu**.

That's it — it adds all five parameters (unsynced, 0 sync bits), builds the
"OscGoesPurrr" submenu (a strength radial, four mode toggles, Off, Sleep
and the Test button), and links it into your expressions menu. Re-running
it later is safe (it updates in place, never duplicates), it never mutates
SDK-shipped default assets (it clones them into `Assets/OscGoesPurrr/`
instead), and it works the same on VRCFury-managed and plain avatars — it
edits the avatar descriptor's own assets, which VRCFury preserves at build
time.

## Option B — manual setup (plain Unity, ~10 minutes, no FX layer needed)

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

Upload, and you're done. (If you'd rather not click through Unity
inspectors, use Option A above — same result, one menu click.)

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
  apart in Device Routing → the motor's chain → Input.
