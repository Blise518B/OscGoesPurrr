# Motor Card Redesign: Signal Chain Layout

Successor to `ROUTING_REDESIGN.md` (now shipped). Replaces the per-motor
Mix subcard with an explicit, left-to-right signal-flow diagram and
collapses the per-channel knob set down to the minimum that earns its
keep. Tune view is rebuilt to mirror the new Device Routing motor card
1:1 so there is exactly one editing surface for the chain, rendered in
two contexts.

**Why now.** The current motor card stacks two channel sub-cards (Depth
+ Speed), a combine row, a conditional modulator-range panel, a
smoothing panel, a Reset-to-defaults button, a 3 s trace mini-graph,
and a linear-actuator output block. On a 2-motor linear toy that is
roughly 60 interactive widgets in one expanded card. The Mix subcard
is *also* embedded verbatim in the Tune view (`tune.py` calls
`self._build_mix_subcard` directly), so every knob has an identical
twin elsewhere — Device Routing carries the same controls as Tune but
without the live multi-trace graph that makes them tunable. The
overcomplication is real and the duplication is literal.

This redesign reshapes the per-motor editor around a visible signal
chain. The chain *is* the simplification: when controls look like the
pipeline they form, the user no longer has to hold the mixer's model
in their head.

Conceptually affected:

* `motor_router.py` — drop modulate-mode logic; add `multiply` to the
  combine policies; add the activity-gate stage; per-channel config
  shrinks to `gain + curve + curve_param`.
* `ui/views/device_frame.py` — motor card rewritten around the chain
  diagram; per-channel "More" expanders removed.
* `ui/views/tune.py` — embeds the same chain widget; loses its own
  separate copy of the per-channel editor.
* New: `ui/motor_signal_chain.py` — the chain widget itself, shared
  between Device Routing and Tune.
* `config_manager.py` — schema simplification (see "Storage" below).
  No migration shims; this is still pre-release.

This redesign does **not** change the engine/router/facade boundaries
documented in `ARCHITECTURE.md`. The chain is rendered in the UI; the
router still owns the math.

---

## The chain

```
Input ─→ Depth (gain + curve) ─↘
     │   Speed (gain + curve) ─→ Combine ─→ Wake ─→ Envelope ─→ …
     │   Punch (hit detector) ─↗           (gate) (smooth+texture)

… ─→ Zero cut ─→ Output
```

Nine logical stages, left to right:

1. **Input** — what the motor listens to.
2. **Depth** — instantaneous magnitude path, gained + shaped.
3. **Speed** — derivative path, gained + shaped. **Directional**: a
   gain for the inward stroke and one for the outward, over a shared
   curve and fall-off.
4. **Punch** — attack-transient path: a fast stroke spikes a short hit
   that decays quickly; merges max-wins with the combined signal. Also
   **directional**, but the outward hit ships muted.
5. **Combine** — how Depth and Speed are merged.
6. **Wake** — the activity gate, in one of two interchangeable modes
   (chosen by `wake.mode`): **Activity** (an analog activity meter that
   wakes on sustained movement) or **Strokes** (the sleep gate: silent
   until enough full strokes land inside a window, disarms after a
   quiet timeout). Merges the pre-merge Gate + Arming stages.
7. **Envelope** — how the level moves over time, split into two
   clearly-labelled halves: a post-combine rise/fall **Smoothing**
   envelope (the calm half) plus an optional downward-only **Texture**
   wobble on held levels (the lively half). The config keys stay
   `smoothing` and `texture`; only the card merges them.
8. **Zero cut** — final override: input at zero snaps the output
   to silence instantly. It reads the chain's *raw* input (`chain_d_raw`,
   pre-curve, pre-gain, pre-Combine), not anything downstream — and that
   input is the max-wins aggregate of everything the motor listens to, so
   the cut fires only once every mapped zone, SPS source and variable is
   at/below the threshold. One source that idles high holds it off.
9. **Output** — toy motor (vibrate or linear).

Depth, Speed and Punch run in parallel from a shared Input. Wake gates
the combined signal — in Activity mode its meter charges from the raw
depth and/or speed-detector signals (`wake.source`), never from Punch.
Envelope's smoothing sits **after** the
gate so Wake's open/close transitions get rounded into the envelope and
the toy never clicks on/off; its texture runs **after** smoothing (before
it, smoothing would iron the wobble back out).

---

## Per-stage details

### Chain types — one chain per kind of contact

A motor ships with **two chains**: one for penetration, one for touch.
They are different sensations and want different tuning — a stroke with
depth and velocity behind it versus a hand brushing past — and sharing
one chain meant every setting was a compromise between them.

`chain["type"]` is `"penetration"` | `"touch"` | `"custom"`, and it
decides the touch/pen interaction filters, so the two can never drift
out of sync by hand. **Absent reads as `custom`**, which honours the
explicit filter keys — exactly how every chain behaved before types
existed, so a hand-written config never changes feel on its own.

The shipped presets differ deliberately:

| | Penetration | Touch |
|---|---|---|
| depth gain | 0.38 | 0.62 |
| speed gain / fall-off | 0.41 / 350 ms | 0.22 / 180 ms |
| punch | 1.32 | **off** |
| wake | activity | **off** |
| smoothing rise/fall | 120 / 200 ms | 45 / 260 ms |

Touch leans on depth, drops the punch accent (a brush is not a thrust),
runs a calmer speed channel with a shorter tail, and attacks faster so a
passing hand registers instead of being smoothed into nothing. Wake is
off because a gate you have to wake defeats the point of a light touch.
They merge **max-wins**: whichever contact is happening drives the toy,
and the two never sum into something neither asked for.

**Existing motors keep their tuning.** A motor configured before the
split has one chain holding whatever compromise its owner landed on;
that chain is kept exactly as-is and becomes the Penetration chain, and
a fresh Touch chain is added beside it. Nothing already dialled in is
touched — only the half that never had its own settings is new. The
second chain inherits the Output band, which is per-toy calibration
rather than feel. This runs from the device seeder and is idempotent, so
it needs no schema version to hang off.

### Per-chain routing

Zones and the interaction filters are resolved **per chain**, under
`motor_<m>_c<c>_<suffix>` (e.g. `motor_0_c1_zones`). The shape still
starts with `motor_` and ends with a known suffix, so `is_routing_key()`
keeps classifying them as mode-local without changes — a chain's input
belongs to the mode, like every other routing choice.

A chain with no key of its own **falls back to the motor's**, so a chain
that has never been customised behaves exactly as the motor did before
it was split out. Only once a value is written per chain do the two
diverge.

Consequence in the router: `_compute_d_raw_from_inputs` runs **once per
chain** rather than once per motor, each with its own compiled config
and filter set. `live_d_raw` remains the max across chains for the
usage statistics and the stroke counter, which are statements about the
*motor's* input.

**Ducking (optional).** A Touch chain can opt to *duck* -- fade out
while the Penetration chain on the same motor has something inside, and
fade back over `duck.release_ms` once the pen leaves. A hand at the same
orifice mid-stroke is nearly always incidental, and under a max merge
its proximity floors every stroke trough; ducking keeps penetration
clean and, as a side effect, a touch value that freezes during
penetration never reaches the toy. It is audio-mixer ducking, not a
gate: a fast fixed attack, a tunable release, no clicks. The sidechain
source is the loudest penetration-type chain's *raw input*, taken before
the simulator's provider override so simulating never ducks the chain
being tuned. Penetration-type chains ignore the flag. **Off by
default** -- OSC Goes Brrr takes the plain max of every source, so off
is parity and on is a taste call; the toggle lives on the Touch chain's
Input stage.

**Anti-stuck is per chain.** It detected on that motor-level max at
first, and the split turned that into a hole: with the Touch chain's
input frozen and the Penetration chain still moving, the max kept
changing, the fuse kept resetting, and the frozen touch value rode the
merge as a floor until everything went quiet — only then did the
timeout even start. (Pre-split this was masked by the wake gate: a
frozen input has no speed, so the activity meter drained and closed the
gate within a couple of seconds. The Touch preset ships wake off, which
exposed the gap.) Each chain now tracks its own input staleness and
fades its own contribution — a stuck chain drops out of the merge while
a live sibling keeps driving, and the moment the frozen parameter
actually changes again the chain returns instantly. The fade lands
after the Output stage, so a faded chain reaches true 0 rather than its
calibration floor, and it carries into the contact stream, so the
param-out mirror stops reporting contact from an input that froze.

### Input

The mapping stage. Identical in function to today's "LISTENING TO"
column.

Editor contents:

* **Zone selector** button → expandable zone panel (All SPS toggle +
  per-zone toggles, populated from `parameter_store.get_detected_zones`).
* **Custom OSC addresses** — chip list + "Add Variable" → existing
  variable picker dialog.
* **Interaction filters** — `Touch` / `Penetration` / `Self` /
  `Others` toggles.

No changes vs. today's mapping surface; just renamed and grouped under
the diagram's first stage.

### Depth channel

Reads raw input magnitude.

Editor contents:

* **Gain** — `QDoubleSpinBox`, 0.0–2.0, step 0.05, default 1.0.
* **Curve** — dropdown: `linear` / `power` / `s_curve`. Default
  `linear`.
* **Param** — `QDoubleSpinBox`, hidden when curve is `linear`, range
  follows curve kind (matches today's behavior: power 0.3–3.0,
  s_curve 1–8 integer).

Stored at `mix.<motor>.depth.{gain, curve, curve_param}`.

**Removed from current Depth:** `enabled` flag (set gain to 0 if you
want it off), `mode` (additive/modulate — replaced by Combine=Multiply),
`min_remap` / `max_remap` (use Gain).

### Speed channel

Reads `d/dt` of the input — **signed**, so the two stroke directions
are separable.

Editor contents, split into two labelled halves plus a shared block:

* **In — going deeper** → **Gain**, same shape as Depth. Scales
  movement while depth is *increasing*.
* **Out — pulling back** → **Gain**. The same for movement while depth
  is *decreasing*.
* **Both directions** → **Curve**, **Param**, **Fall-off (ms)**
  (`QDoubleSpinBox`, 10–2000, step 50, default 300 — how long the
  signal keeps ringing after movement stops; lower = snappier cut-off,
  higher = lingering tail). These shape *how* speed responds, not which
  way you moved, so they are shared.

The collapsed card carries both gains as two labelled quick sliders
(`In` / `Out`); the balance between them is the knob you reach for most,
so it does not live behind an expand.

Stored at `mix.<motor>.speed.{gain, gain_out, curve, curve_param,
decay_ms}`.

**`gain_out` is optional, and absent means "follow `gain`".** The
shipped default omits it deliberately — writing `gain_out: 1.0` would
pin the outward half, so every later edit of `gain` alone would silently
produce an asymmetric chain. It is also what makes the split invisible
to a chain tuned before it existed: speed always fired both ways, it
just could not tell them apart.

**Internal model.** Two peak-hold rings, one per direction, sharing the
fall-off tau; only the direction actually travelled receives a strike,
the other rings down. `max(in, out)` reproduces the pre-split single-|Δ|
ring *exactly* — each ring is `max(signal, prev × decay)`, so the max
over both is the max over the whole history, and the output cutoff is
monotonic so applying it per ring then taking the max is the same as the
reverse. That combined value is what still feeds Wake's `speed`/`both`
sources and the Speed card's raw trace.

Two rings rather than one because a shared accumulator would let the
out-stroke stomp the in-stroke's decay tail at a direction change —
precisely when an asymmetric tuning is supposed to be audible.

**Removed from current Speed:** `enabled` flag, `mode`,
`input_deadband`, `output_cutoff`, `decay_tau`. The first two of
those become invisible constants inside the speed detector (see
"Speed-detector constants" below); `decay_tau` came back as the
user-facing **Fall-off** knob (`decay_ms`) after field tuning showed
the fixed 300 ms tail reads as "the toy keeps going after I
stopped".

### Punch

Attack-transient detector — the third parallel source next to Depth
and Speed. A fast stroke spikes a short hit on top of the sustained
level, then decays. The hit merges max-wins with the combined
Depth/Speed signal — an accent, never a duck. Slow repositioning is
ignored in both directions.

Directional, same shape as Speed. Editor contents:

* **In — the thrust** → **Gain**, `QDoubleSpinBox`, 0.0–2.0, step
  0.05, default 0.0. Fires when depth rises fast.
* **Out — the pull** → **Gain**, same range, default 0.0. Fires when
  depth falls fast.
* **Decay (ms)** — `QDoubleSpinBox`, 30–1000, step 10, default 120.
  Shared: how long a hit rings out in either direction.

**Both gains 0 = off** — no enable flag; the stage is skipped entirely
(while still tracking its position memory, so enabling it mid-motion
reads no phantom rise), matching the channels' "set gain to 0"
convention.

Stored at `mix.<motor>.punch.{gain, gain_out, decay_ms}`.

**`punch.gain_out` defaults to `0.0`, NOT to `gain`** — the opposite of
Speed, and deliberately. Punch used to discard falling edges outright
("pull-out is not a punch"), so the outward hit is a genuinely new
signal; defaulting it on would add a pull-out accent to every existing
chain unasked. Speed's outward half already existed and merely could not
be addressed, which is why it follows instead.

Each direction keeps its own envelope, so the pull-out half of a stroke
never cuts the thrust's hit short.

### Combine

How the two channel outputs merge.

Editor contents:

* Segmented control — `Add` / `Max` / `Multiply`. Default `Max`
  (current behavior).

Stored at `mix.<motor>.combine`.

`Multiply` replaces the per-channel `modulate` mode. Math is symmetric
and commutative; channels no longer carry an asymmetric flag. Edge
case: if either channel is 0, output is 0 — the diagram makes this
visible, no hidden bypass.

The `modulator_range` panel and the at-most-one-modulate cross-channel
rule both go away.

### Wake

The activity gate — one stage that merges the pre-merge Gate + Arming
stages into two interchangeable modes, chosen by the mode toggle. One
mode runs at a time. **Off by default** — a new always-on gate would
silently change every existing profile's feel.

Editor contents:

* **Enable** — toggle. Off by default.
* **Mode** — segmented `Activity` / `Strokes`. Stored at
  `mix.<motor>.wake.mode`.
* *Activity-mode params* (shown when mode = Activity):
  * **Source** — segmented `Depth` / `Speed` / `Both` (stored at
    `wake.source` as `"depth"` / `"speed"` / `"both"`, default
    `"both"`). What charges the activity meter: raw insertion depth
    (presence keeps it awake), the raw speed detector (velocity only —
    tiny fast jiggles can wake it), or their product (movement *while
    actually inserted* — a shallow flutter can't trigger it). Punch is
    deliberately never a source: its whole job is exaggerating small
    movements, which would make the gate hair-triggered.
  * **Wake threshold** — `QDoubleSpinBox`, 0.0–1.0, step 0.01.
    Activity-meter level at which the gate opens.
  * **Sleep delay** — `QDoubleSpinBox`, 0.0–10.0 s, step 0.1. How
    long activity must stay below threshold before the gate closes.
  * **Build-up (s)** — `QDoubleSpinBox`, 0.01–10.0 s, step 0.1,
    default 0.05. The meter's attack tau: how long sustained movement
    takes to charge the activity meter. High values demand a few
    seconds of motion before waking instead of opening on a twitch.
  * **Decay (s)** — `QDoubleSpinBox`, 0.01–10.0 s, step 0.1, default
    0.5. The meter's release tau: how long the charged meter drains
    once movement stops.
  * A thin horizontal activity meter with a tick at `wake_threshold`.
* *Strokes-mode params* (shown when mode = Strokes):
  * **Thrusts** — spinbox, 1–10, default 3.
  * **Window (s)** — spinbox, 1–30, default 6.
  * **Disarm after (s)** — spinbox, 5–600, default 45.

Stored at `mix.<motor>.wake.{enabled, mode, source, wake_threshold,
sleep_delay_s, attack_s, release_s, thrusts, window_s, disarm_after_s}`.
`wake` is the only shape the router reads; a chain with no `wake` block
is treated as disabled (pass-through).

**Activity mode — internal model:**

* An activity meter `A ∈ [0, 1]` rises with the `wake.source` signal
  (default: depth × speed) as an asymmetric
  EMA. Time constants are per-chain knobs with conservative defaults
  (they were hidden constants until the field-tuning pass found that
  a fixed 50 ms attack lets a single twitch spike the meter over the
  threshold — there was no way to require *sustained* movement):
  * `wake.attack_s` — default 0.05 (50 ms), fast rise so new movement
    registers immediately. Raise it to make the gate charge slowly.
  * `wake.release_s` — default 0.50 (500 ms), slow decay so brief
    stillness does not instantly drop the meter below threshold.
    Raise it to make the activity "budget" coast across pauses.
  Both are clamped to [0.01, 10.0] s by the router. The meter is
  clamped to `[0, 1]` (anti-windup).
* Gate state: open when `A ≥ wake_threshold`. Once open, closes after
  `A` has stayed below `wake_threshold` continuously for
  `sleep_delay_s` seconds.

**Strokes mode.** The sleep gate. Output stays silent until the
partner lands `thrusts` full strokes inside `window_s` seconds; once
armed it stays armed while strokes keep coming, and disarms after
`disarm_after_s` seconds of quiet. An accidental brush can never wake
the motor — this is what makes it safe to wear while sleeping.

**The 🌙 Sleep toggle.** The global Sleep toggle (sidebar /
`OGP/Sleep`) forces EVERY chain into strokes mode for the session:
`MotorRouter.SLEEP_WAKE_OVERRIDE` — enabled, 3 thrusts, 6 s window,
45 s disarm. It is applied at READ time in `_calculate_motor_target`,
so nothing is written to the stored chain and switching Sleep off
restores the user's real wake settings exactly. Toggling either way
resets each chain's wake state, so the new algorithm never inherits
the other's credit (a pre-charged activity meter must not count as
strokes, and a woken motor must not stay open under a gate that never
authorised it).

**Placement.** Wake gates the combined signal between Combine and
Envelope. The combined value is multiplied by the gate state (0 or 1)
*before* Envelope's smoothing, so a gate close (falling, `fall_ms`) or
open (rising, `rise_ms`) is rounded by the rise/fall knobs the user
already tuned — no separate gate-smoothing settings exist.

**Why the activity meter reuses the depth/speed primitives, not a
separate integrator.** "Activity" is built from the same raw depth and
raw speed-detector signals the rest of the chain uses — a separate
detector would drift apart from them over time, and reusing them keeps
the meter in the same units the user sees in Tune's traces. The gate's
input is per-input (avatar motion); its knobs are per-motor, so two
motors on the same toy can have different wake/sleep settings while
seeing identical activity. Punch feeds no wake path in either mode —
a speed-only source is as twitch-sensitive as Punch itself, which is
why `"both"` (depth-weighted movement) is the default.

**Visual.** The Wake stage card shows a thin valve indicator that
flips open/closed with the gate; the expanded editor's activity meter
(Activity mode) reads like a VU meter with a threshold mark.

### Envelope

How the level moves over time. One card split into two
clearly-labelled halves — **Smoothing** (the calm half) and
**Texture** (the lively half) — separated by a divider, each with a
plain-language one-line description that bolds its own knob names. The
config keys stay `smoothing` and `texture` separately.

**Smoothing** — post-mix rise/fall envelope follower. Editor contents:

* **Rise (ms)** — `QDoubleSpinBox`, 0–2000, step 10, default 50.
* **Fall (ms)** — `QDoubleSpinBox`, 0–2000, step 10, default 20.

Stored at `mix.<motor>.smoothing.{rise_ms, fall_ms}`. De-jitters the
signal and shapes the macro attack/release; the same knobs round
Wake's open/close transitions.

**Texture** — post-smoothing wobble so a held level feels alive instead
of sitting dead flat. The modulation is downward-only — the output
never exceeds the smoothed level — and the smoothing envelope tracks
the pre-texture value so the wobble never feeds back into itself. Editor
contents:

* **Enable** — toggle. Off by default.
* **Amount (%)** — spinbox, 0–90 %, default 25 (stored as 0.0–0.9).
* **Rate (Hz)** — `QDoubleSpinBox`, 0.2–8.0, step 0.1, default 2.0.
* **Faster with movement** — toggle, default off (config key
  `follow_speed`). Scales the wobble *rate* up with the speed signal so
  faster motion means a faster wobble.
* **Depth vs movement** — segmented `Off` / `Stronger` / `Weaker`
  (config key `depth_follow` = `"off"` / `"up"` / `"down"`, default
  `"off"`). Scales the wobble *depth* by the same speed signal:
  **Stronger** deepens the wobble the faster you move; **Weaker** gives
  full grain at rest and fades it out under motion — the movement itself
  already carries the life, so the cosmetic wobble backs off instead of
  fighting it. **Off** keeps a constant depth. Inert while holding still
  (movement 0 → both directions collapse to the base amount).

Stored at `mix.<motor>.texture.{enabled, amount, rate_hz,
follow_speed, depth_follow}`.

**Why texture comes after smoothing.** Ahead of the smoothing stage the
envelope follower would simply iron the wobble back out; placing texture
last preserves it while still riding under the smoothed level.

### Output

The toy motor. Every kind gets the level block; the rest depends on
motor kind. Both controls are **per chain**, stored at
`mix.<motor>.chains[i].output.{gain, min, max}`.

**Every motor:**

* **Gain** — a ×0.00–2.00 multiplier on this chain's output, applied
  before the range below. Balances one chain against its sibling on a
  two-chain motor, and one toy against the rest of the rig: pull down
  the motor that always reads stronger and the global strength slider
  stays meaningful across every device. Above ×1.00 boosts, but the
  result still stops at the range's maximum.

* **Range** — the toy's usable output band, two 0–100 % spinboxes
  (default 0–100 %, i.e. inert). It **remaps rather than clips**:

  ```
  x = clamp(chain_out × gain × strength, 0, 1)
  out = 0                        if x ≤ 0.01   (_OUTPUT_SILENCE_EPS)
        min + x × (max − min)    otherwise
  ```

  So with 20–80 %, an input of 1 % lands at 20.6 %, 50 % at 50 %, and
  100 % at 80 %. A motor that doesn't start turning until a fifth of the
  way up skips that dead zone without losing any input resolution, and
  one that rattles near the top is capped without flattening the top of
  its travel. The two spinboxes bound each other live, so the band can
  never be inverted from the UI.

  **Silence is exempt.** Under the epsilon the output is 0, never the
  floor — the minimum means "the level this toy starts moving at", not
  "this toy is never off". That is also what keeps Off silent through a
  floored chain: master scale 0 drives `x` under the epsilon.

  **The strength slider is applied before the band**, inside this stage
  (see ARCHITECTURE.md § "The merged active view") — otherwise a 20 %
  floor at strength 0.5 would reach the toy as 10 %, straight back in
  the dead zone. The consequence is deliberate: strength rides *within*
  the band and can no longer push a floored chain below its minimum.
  Off and the per-toy mute still silence it completely.

  **The OGP/Test pulse rides the band too.** The connectivity pulse
  injects a fixed level (`OGP_TEST_LEVEL`, 0.2) rather than routing one,
  so it is remapped per motor through
  `MotorRouter.map_into_output_band()` before it reaches the engine — on
  both emit paths (the activation push in `modes_facade`, and the
  per-tick floor in `intiface_facade`). Otherwise a motor whose band
  starts above 20 % would take the pulse straight into its dead zone and
  read as a dead toy, which is the one thing that check exists to rule
  out. The band used is `(max of the chains' minimums, max of their
  maximums)`: it describes the physical motor, so an uncalibrated sibling
  chain sitting at 0 must not drag the pulse back down. Zero still maps
  to zero, so releasing the pulse leaves nothing humming.

  **Merge interaction.** Each chain's band caps its own output, and the
  merged value is additionally clamped to the highest ceiling any chain
  allows — `add` would otherwise sum two capped chains past both, and
  the ceiling is a statement about the hardware. `multiply` can still
  land under a floor; an attenuating merge is asking for exactly that.

  This is hardware **calibration**, not intensity. It lives in the
  shared feel layer and so holds across every routing mode — how hard a
  motor hits is a property of the hardware, not of how it happens to be
  wired up right now. A chain with a narrowed band shows `20–80%` as its
  collapsed-card subtitle (a trimmed gain shows `×0.70`) instead of the
  motor kind, because an unexplained quiet toy is worth more than three
  characters of "vib".

  The chain's own Output mini-graph draws this stage's result, so it
  reflects the gain, the strength and the band — but it is still
  pre-merge. The motor card's vibe meter shows the merged final value.

**Vibrate motor:**

* Gain + Range + the vibe meter (read-only).

**Linear motor:**

* **Mode** — segmented `Position` / `Speed`.
* **Idle** — segmented `Hold` / `Rest`.
* **Stroke setup** — `▸` expander, collapsed by default for existing
  toys, auto-expanded on first-add of a new linear toy:
  * Min position (0.0–1.0)
  * Max position (0.0–1.0)
  * Resting position (0.0–1.0)
  * Resting time (0.0–60.0 s)
* Vibe meter (read-only).

Storage keys otherwise unchanged.

**Downstream of the chain** nothing scales the value any further on the
Buttplug path — the global `strength` is folded into the Output stage
above so the range band can sit downstream of it, and dispatch only
zeroes (Off, per-toy mute, send-to-toy suppression) or applies the
OGP/Test floor. The other backends still take their `strength` multiply
at their own dispatch. See ARCHITECTURE.md § "The merged active view".

**Wake × linear actuator.** The chain is motor-kind agnostic — when
the gate closes mid-stroke on a linear toy, the combined value goes
to 0. For `Mode = Position` this means the actuator returns to
position 0 (clamped by `min_pos`); for `Mode = Speed` it means
stroking stops. Both are correct: a closed gate should produce no
further motion, and the linear actuator's stroke setup defines what
"no motion" means physically. There is no special-case bypass of the
gate for linear toys.

---

## Visual layout: stages strip with inline editor

The chain is rendered as a Tune-style stages strip — compact,
left-to-right, always visible. Click any stage to expand its editor
inline below. One editor open at a time. Active stage gets a green
border (reuses the `tuneStageCard[active="true"]` QSS rule).

```
┌ Motor 0 · Thrust (linear) ──────────────────────────────────────┐
│                                                                 │
│  [Input] ─→ [Depth] ↘                                           │
│             [Speed] ─→ [Combine] ─→ [Wake] ─→ [Envelope] ─→ …   │
│             [Punch] ↗                                           │
│  … ─→ [Zero cut] ─→ [Output]                                    │
│                                                                 │
│  ▼ Input                                                        │
│    Zones:   [Select Zones (3 enabled) ▾]                        │
│    OSC:     chip · chip   [+ Add Variable]                      │
│    Filters: Touch · Penetration · Self · Others                 │
│                                                                 │
│  ████░░░░░░  vibe meter                                         │
└─────────────────────────────────────────────────────────────────┘
```

The diagram solves the width problem: stages are small clickable
boxes, the editor floats below at full card width. The chain is
always readable; the editor only consumes space for the stage being
touched.

Card header carries:

* `Motor N · <kind>` label.
* `Reset to defaults` button (scoped to this motor's full mix block).

Per-motor mini trace graph is **gone**. Users who want to see the
chain working open Tune.

---

## Tune view, 1:1 with Device Routing

The Tune view re-uses the exact same chain widget. Same diagram, same
stage editors, same storage path. Tune adds — and only adds:

* Motor picker (lists every motor in the active profile).
* Source picker (Simulated / Live VRChat) with pattern dropdown,
  Play/Stop, Send-to-toy safety switch.
* Six-trace live graph (Raw depth, Raw speed, Depth influence, Speed
  influence, Post-mix, Final output) — observation only, not editing.
* The stages strip becomes the chain diagram itself (no duplication).

**Concretely:** factor the chain widget into `ui/motor_signal_chain.py`.
Both `ui/views/device_frame.py` and `ui/views/tune.py` embed it. There
is no second editing surface anywhere. Tune is "Device Routing's
motor card + observation tools."

This resolves the literal `_build_mix_subcard` duplication problem
from the previous redesign by removing one editor entirely rather
than keeping two in sync.

---

## Speed-detector constants

The current per-motor "More" knobs on Speed (`input_deadband`,
`output_cutoff`, `decay_tau`) were workarounds for not having a
proper activity gate. With the gate in place, they no longer need to
be per-motor tunable.

Bake them as constants inside the speed detector:

* `_SPEED_INPUT_DEADBAND = 0.005` (current default)
* `_SPEED_OUTPUT_CUTOFF = 0.02` (current default)
* `_SPEED_DECAY_TAU_S = 0.30` (fallback default — see below)

The small `input_deadband` is kept (not exposed) so the activity
meter operates in "real motion" units rather than "noise + motion"
units. Without it, the gate's wake-threshold knob would have a
mysterious noise floor the user discovers by trial.

The decay tau turned out to need per-chain tuning after all: a fixed
300 ms tail keeps the speed channel (and anything fed by it) running
visibly after movement stops. It is exposed as the Speed stage's
**Fall-off (ms)** knob (`speed.decay_ms`, clamp 10–2000 ms);
`_SPEED_DECAY_TAU_S` remains as the fallback when the field is
missing. Deadband and cutoff stay baked — if a need to retune those
surfaces, they move to a single hidden Advanced panel in Settings,
not back into the per-motor card.

---

## Storage (clean break)

Pre-release. No migration. Existing profiles with the old per-motor
mix block get reset to defaults on first load against the new schema;
users re-tune from scratch.

New per-motor `mix` block. Ships from Cut 1 as a list of chains —
always length 1 in cuts 1–4 — so Cut 5 (optional secondary chain)
is purely additive with no schema migration:

```python
{
    "chains": [
        {
            "depth": {"gain": 1.0, "curve": "linear", "curve_param": 1.0},
            "speed": {"gain": 1.0, "curve": "linear", "curve_param": 1.0,
                      "decay_ms": 300.0},
            # Attack transients: a fast thrust in spikes a short hit
            # that decays quickly and merges max-wins with the
            # combined signal. gain 0 = off.
            "punch": {"gain": 0.0, "decay_ms": 120.0},
            "combine": "max",                  # "add" | "max" | "multiply"
            # Wake — the activity gate, one of two modes (`mode`):
            #   "activity": analog meter, wakes on sustained movement
            #     (wake_threshold / sleep_delay_s / attack_s / release_s);
            #     `source` picks what charges the meter — raw depth, the
            #     raw speed detector, or depth × speed (never Punch).
            #   "strokes": sleep gate, silent until `thrusts` full strokes
            #     land inside `window_s`; disarms after `disarm_after_s`.
            "wake": {
                "enabled": False,
                "mode": "activity",            # "activity" | "strokes"
                "source": "both",              # "depth" | "speed" | "both"
                "wake_threshold": 0.05,
                "sleep_delay_s": 0.5,
                "attack_s": 0.05,
                "release_s": 0.5,
                "thrusts": 3,
                "window_s": 6.0,
                "disarm_after_s": 45.0,
            },
            "smoothing": {"rise_ms": 50.0, "fall_ms": 20.0},
            # Envelope's Texture half: post-smoothing downward-only wobble
            # on held levels; rate can follow the speed signal.
            "texture": {"enabled": False, "amount": 0.25,
                        "rate_hz": 2.0, "follow_speed": False},
            # Final override: input at/below threshold (plug removed)
            # snaps the chain output to 0 instantly instead of riding
            # the smoothing fall tail / speed ring down.
            "zerocut": {"enabled": False, "threshold": 0.0},
        },
    ],
    "merge": "max",  # only meaningful when len(chains) > 1
}
```

Storage paths in the per-stage sections above (`mix.<motor>.depth.…`,
`mix.<motor>.gate.…`, etc.) refer to `chains[0]` in cuts 1–4; the
router and UI treat the single chain as the only chain unless
`len(chains) > 1`.

Gone from the previous schema: `<channel>.enabled`, `<channel>.mode`,
`depth.min_remap`, `depth.max_remap`, `speed.input_deadband`,
`speed.output_cutoff`, `speed.decay_tau`, `modulator_range`. Renamed:
`smoothing.attack_ms` → `smoothing.rise_ms`, `smoothing.release_ms`
→ `smoothing.fall_ms`.

Linear actuator block (motor-level, outside `mix`) keeps its current
keys: `motor_N_linear_mode`, `motor_N_linear_idle`, `motor_N_min_pos`,
`motor_N_max_pos`, `motor_N_resting_pos`, `motor_N_resting_time_s`.

---

## Phased delivery

1. **Cut 1 — schema + router math.** New per-motor mix schema in
   `motor_router.DEFAULT_MIX_CONFIG`. Drop modulate logic; add
   `multiply` combine op; add the activity-gate stage between
   combine and smoothing. Bake speed-detector constants. Unit tests
   for: each combine op; gate state machine (closed-open transition
   at threshold; close after sleep delay); gate observes pre-channel
   speed signal; smoothing applied to gated signal.
2. **Cut 2 — shared chain widget.** Build `ui/motor_signal_chain.py`
   with the stages strip, inline editor, activity meter visual.
   Storage round-trips through the same facade calls as today.
3. **Cut 3 — Device Routing motor card.** Replace the current Mix
   column / per-channel cards / smoothing panel / mini-graph with
   the new widget. Listening To column survives (becomes the Input
   stage editor). Linear OUTPUT block becomes the Output stage editor.
4. **Cut 4 — Tune view.** Drop Tune's own copy of the mix editor;
   embed the chain widget. Stages strip becomes the chain diagram
   (the two were already conceptually the same — now they are
   literally the same widget). Multi-trace graph and pattern player
   stay as observation tools.

Each cut is independently testable. Cuts 3 and 4 share the widget
from Cut 2; Cut 3 ships the Device Routing change first, Cut 4
brings Tune into alignment.

5. **Cut 5 — optional secondary chain (deferred).** Per-motor support
   for a second parallel chain that merges into the same output.
   See the "Future: optional secondary chain" section below. Deferred
   intentionally: the single-chain redesign should ship and bake
   first, so we can tell whether the second chain is actually needed
   or whether passthrough configuration of the first chain covers
   the realistic use cases.

---

## Open questions / explicit non-decisions

* **Multiply + zero channel.** If `combine = multiply` and one
  channel is 0, output is 0 regardless of the other. The diagram
  makes this visible; no hidden bypass. Locked as-is.
* **Wake default off.** Existing tuned profiles stay silent on the
  gate (both Wake modes default disabled). Users opt in per motor.
  Locked.
* **Curves stay.** Power and s_curve shape *feel* in a way gain
  can't reproduce; keeping them costs one tiny dropdown per channel.
  Locked.
* **Modulator mode gone.** Replaced by Combine=Multiply.
  Out-of-scope features (one-sided LFO, ring modulation, etc.) are
  not addressed by this redesign and are not blockers.
* **Per-motor activity-gate input.** The gate observes a per-input
  signal (avatar motion). Two motors on the same toy listening to
  the same zones see identical activity but can have different
  thresholds. Flagged for future review if a real use case wants
  per-motor activity sources.

---

## Future: optional secondary chain

After the single-chain redesign ships (cuts 1–4), each motor may
optionally hold a second chain that runs in parallel with the first
and merges into the same physical output. Realistic use case: zone
interactions through the full mixer *and* a direct passthrough
source (e.g., a manual override slider, a calibration parameter) on
the same motor.

This is **deferred to Cut 5** — not part of the initial redesign.
The minimum version of "feed a parameter directly to output" is
already achievable with one chain configured as: gain 1.0, curve
linear, Wake disabled, smoothing 0/0 ms. The case where a second
chain genuinely earns its keep is when you want the heavily-processed
behavior *and* the raw behavior simultaneously on the same motor,
which is real but rarer than it first sounds.

### Design

* Each motor holds a list of chains, length 1 by default, **capped
  at 2.** Resist the temptation to allow N — two handles every
  realistic main+override use case; three becomes a configuration
  maze and the diagram stops fitting on a card.
* Chains are structurally identical — both have the full Input →
  Depth/Speed/Punch → Combine → Wake → Envelope → Zero cut pipeline.
  There is no
  "primary" vs "secondary" template; the second chain just gets
  configured differently if the user wants passthrough behavior.
* Merge at output: configurable op (`add` / `max` / `multiply`),
  default `max`. The `merge` field on the `mix` block is hidden in
  the UI when `len(chains) == 1`.
* Single "+ Add chain" button on the motor card toggles the second
  chain on. The card grows vertically with a second diagram below
  the first. A "✕ Remove" button on the second chain takes it back
  to length 1.
* Tune view gains a chain picker alongside its motor picker — or
  stacks both chains and lets the user click which one to focus on.

### Why the schema already supports it

The Cut 1 schema is already `{chains: [...], merge: "max"}` with
the list always length 1. The router treats `chains[0]` as the only
chain unless `len(chains) > 1`. Cut 5 is then purely additive:

* Router: iterate over all chains, merge their outputs with `merge`.
* UI: wrap the existing chain widget in a list container, add the
  merge picker, update Tune.
* Storage: no migration needed — appending to the list is a no-op
  for older code paths because they index `chains[0]` only.

This is the only "future-proofing" decision baked into the design.
Everywhere else, the rule is "ship the simplest thing that solves
today's problem and don't pre-build for hypothetical needs." The
list shape earns its early adoption because the alternative —
reshaping the per-motor mix block later — would force a migration
in a codebase whose explicit policy is "no migration shims."
