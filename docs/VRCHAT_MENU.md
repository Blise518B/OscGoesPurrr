# VRChat expression-menu control (OGP/Mode + OGP/Test)

OscGoesPurrr's six modes can be switched from inside VRChat via one avatar
parameter, and a second parameter gives you a "is everything connected?"
test pulse — no alt-tabbing out of VR.

| Parameter  | Type | Values | Meaning                                        |
|------------|------|--------|------------------------------------------------|
| `OGP/Mode` | Int  | 0–5    | Active mode: 0 Off, 1 Low, 2 Medium, 3 High, 4 Sleep, 5 Custom (slot order — renaming modes in the app doesn't change the numbers) |
| `OGP/Test` | Bool | held   | While held, toys / SteamVR trackers / bHaptics run at a low fixed level (~20%). PiShock, Coyote and OWO are **deliberately excluded** — a surprise shock is not a connectivity check. |

The sync is two-way: switching in the app pushes `OGP/Mode` back to VRChat
so your menu highlight stays correct, and after every avatar load or OSC
reconnect the app re-asserts its current mode (for ~2 s after an avatar
load it ignores incoming `OGP/Mode`, because VRChat replays stale saved
values then — the app is the source of truth, so an avatar swap can never
yank your mode).

## Setting it up (plain Unity, ~10 minutes, no FX layer needed)

Because these parameters only talk to OSC — they don't drive any
animations — you don't need an animator controller at all. Two assets:

1. **Expression Parameters** (your avatar descriptor → Expressions →
   Parameters asset):
   * Add `OGP/Mode` — type **Int**, default `2`, **Saved: off**,
     **Synced: off**. (Unsynced parameters cost 0 sync bits and OSC works
     fine with them; leave Saved off — the app remembers the mode and
     re-asserts it on avatar load anyway.)
   * Add `OGP/Test` — type **Bool**, default off, Saved: off, Synced: off.

2. **Expressions Menu**: create a submenu (e.g. "OscGoesPurrr") and add
   seven controls:
   * Six **Toggle** controls, all bound to parameter `OGP/Mode`, with
     Value = `0`…`5`. Suggested names/icons: 🔇 Off, 🔈 Low, 🔉 Medium,
     🔊 High, 🌙 Sleep, 🃏 Custom. Because they share one Int they behave
     like radio buttons — tapping a mode switches to it.
     Bonus: tapping the *active* toggle off resets the Int to `0`, which
     is **Off** — so "turn the current mode off" doubles as the panic
     button.
   * One **Button** control bound to `OGP/Test` — a Button (not Toggle) is
     momentary: the pulse runs only while you hold it.

Upload, and you're done. VRCFury users: a drag-and-drop prefab that adds
the parameters + menu automatically is planned; until then the manual
steps above work on any avatar, VRCFury-managed or not.

## Troubleshooting

* **Nothing happens when you tap the menu** — VRChat caches a per-avatar
  OSC config that whitelists parameters. If you added the parameters to an
  avatar you've used before, close VRChat, delete
  `%USERPROFILE%\AppData\LocalLow\VRChat\VRChat\OSC\` (just the folder —
  it regenerates), and reload the avatar.
* **The menu highlight is wrong after switching in the app** — make sure
  OSC is connected (sidebar pill); the app re-sends `OGP/Mode` on every
  switch, avatar change, and reconnect.
* **Sleep mode seems dead** — that's the point: its gate needs sustained
  strong contact before anything plays. Tune it in Device Routing while
  Sleep is the active mode.
