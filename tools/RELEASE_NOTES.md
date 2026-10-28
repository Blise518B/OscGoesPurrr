## Install

**Windows:** download **OscGoesPurrr-Windows.exe** below and run it. That's the
whole install — one file, no setup wizard, no Python, no separate Intiface
Central. Windows will show a blue "Windows protected your PC" box the first
time, because the exe isn't code-signed (a certificate costs a few hundred a
year). Click **More info → Run anyway**.

**Linux (x86_64):** download **OscGoesPurrr-Linux-x86_64.AppImage** below, make
it executable (`chmod +x`, or *Allow executing* in its Properties) and run it.
It's built by GitHub a few minutes after this release appears.

Already running an older version? Don't download anything — it'll offer the
update itself at launch.

## What's new

<!-- Replace this section before each release. Keep it short and concrete:
     what changed, and what a user would notice. -->

- **Friends.** Link with other OGP users over the internet: send an invite
  link in Discord, they click it and you're linked. A friend you allow can
  drive your toys (by hand, with an auto mode, or overriding what your
  avatar does), move your strength and fire your shockers, and you theirs.
  Several friends can drive one person and share one set of toy cards
  (**Sync with others**). Groups, a big Control mode for VR, everything
  logged. No account and no server: the two PCs talk directly. Your
  strength, Off, each toy's maximum and your shocker limits always hold, and
  **Pause all** stops every friend at once. You're always on your own list,
  so you can try a friend's panel on your own toys.
- **Web remote.** For someone without OGP: **Copy web remote link** (right
  under ＋ Add a friend) and whoever opens it gets a friend's panel in their
  browser — no install, no account. Toys from the start; your shockers and
  your avatar's board only once you tick them on its row in your list,
  where you also see who's on, kick someone or switch it off. Every rule a
  friend has holds for it too.
- **Shockers.** A PiShock hub over USB (no cloud), or one running OpenShock
  firmware. A card per shocker with its own max shock, max vibrate and
  longest pulse; drag a shocker onto the behaviours that should drive it —
  continuous, contact and impact rules, and **Touch zones** where each
  contact drives its own shockers. Shocks stay vibrates until you arm them,
  and nothing can widen the limits. Friends get PiShock's own panel, with
  Party Mode. Off until you switch it on.
- **Avatar Remote.** VRC Parameter Relay's board, built in: toggles, hold
  buttons, sliders and steppers for your avatar's parameters, in coloured
  categories, per avatar and preset. Friends you allow can use the board of
  the avatar you wear, from their Friends page. Boards made in the Relay
  import with one click. Off until you switch it on.
- **Pick what you use.** OGP asks once what you have and want and shows
  those pages; Settings → Features → *Choose what you use…* asks again.
- **Show me around.** Press F1 on any page (or *Show me around* in the
  status bar): its steps on top, and whatever you point at explains itself.
  Clicks change nothing while it's on.
- **Your avatar's menu.** One VRCFury prefab to drag onto your avatar:
  strength, mode, Off, Sleep, Test and a Friends submenu — your own
  controls, the friends' ones, or both.
- **Stats per person.** Tag who a session was with, or a stretch of it, and
  see everyone ranked; optionally tagged for you from VRChat's log when you
  are alone with one other person. Opt-in thrust counters for your avatar.
- **Colours.** Pick a colour and the colours that mean something (the pink of
  the live signal, a toy's own colour…) move out of its way; Settings →
  Appearance → Other colours sets each one yourself.
- **Smaller things.** The scroll wheel never changes a setting — it scrolls
  the page, even from VR. Home lists your shocker hub with your toys, with
  an On / Off switch. Toys are looked for every 5 seconds while none is
  connected (Scan now on Home). The built-in toy server no longer takes
  Bluetooth serial gadgets (MeshCore radios, ESP32 boards, some watches) for
  Lovense toys. Opening OGP twice asks whether to switch to the open window.
  The window comes back maximized if you left it so.

**Coming from an alpha?** Since alpha.11: the Shockers page is cards with
per-shocker limits, behaviours you drag shockers onto, Touch zones, and Arm
shocks stays as you left it; the web remote gets the whole friend's panel;
F1 shows you around. The Suits page is gone for now: the bHaptics and OWO
suits come back in a release of their own, and your suit settings are kept.

More on the website: https://blise518b.github.io/OscGoesPurrr/
