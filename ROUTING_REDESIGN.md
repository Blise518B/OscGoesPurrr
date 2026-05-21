# Routing Redesign: Per-Motor Mixer, UI Refresh, and Live Tuning

A planned overhaul of the Device Routing experience: a new per-motor
depth/speed mixer, a collapsed-by-default toy card with progressive
disclosure, a Help Mode for in-context parameter explanations, and a
new "Tune" tab with a live multi-curve graph and a simulated-input
mode for offline tuning.

**Why now.** The current "Position ↔ Speed" blend slider is a 1D mix
that normalizes — there is no way to dial both influences up or both
down, no way to shape either channel independently, and the four
debug tuning knobs (`speed_gain`, `speed_input_deadband`,
`speed_output_cutoff`, `speed_decay_tau`) are global so a single
"shared across all motors" value has to fit every toy. The UI also
exposes a legacy manual-intensity slider per motor that predates real
routing and confuses new users. This work lands a more expressive
mixer, promotes the tuning surface to per-motor, and rebuilds the UI
around progressive disclosure.

This redesign affects three files conceptually but touches more in
practice:

* `motor_router.py` — new mixer math, new intermediates surface for
  the graph
* `haptic_engine.py` — soft-mute support; per-motor linear physics
  config (currently uses `LINEAR_DEFAULTS` engine-wide)
* `ui_components.py` + `ui/` — full Device Routing view rewrite, new
  Tune tab, Help Mode overlay
* `config_manager.py` — schema additions (per-motor mixer fields,
  per-toy mute, removal of legacy speed-tuning from app-settings)

It does **not** change the engine/router/facade boundaries documented
in `ARCHITECTURE.md`. The new tune-mode pattern generator writes into
`parameter_store.store` the same way `vrchat_osc.py` does, so the
router never needs to know whether its input is live or simulated.

---

## Phased delivery

1. **Phase 1 — UI redesign.** Collapsed/expanded toy bar, motor
   cards stacked inside, per-channel "More" expanders, Help Mode,
   mute toggle, no-battery glyph. Existing math; existing storage.
   Removes the legacy intensity slider.
2. **Phase 2 — Mixer math rework.** Per-channel gain/curve/mode,
   modulate-other rule, combine policy, per-motor storage of all
   tuning. New mixer plugs into the UI shells built in Phase 1.
3. **Phase 3 — Tune tab.** Live multi-curve graph, per-curve
   visibility toggles, simulated input patterns, dry-run safety
   switch. Requires intermediates plumbing in `motor_router`.

Doing them in this order means the graph never has to be redrawn
mid-flight against shifting mixer semantics.

---

## Phase 1 — Device Routing UI redesign

### Goals

* Hide complexity by default. A new user opening the app should see
  a clean list of toys with the essentials only.
* Make tuning discoverable on demand. Click a toy to unfold its motor
  cards; click "More" inside a channel to reveal fine knobs.
* Remove dead UI. The manual variable-intensity slider on each motor
  is gone.

### Collapsed toy bar (default)

```
┌────────────────────────────────────────────────────────────────────┐
│ [icon] ● Lovense Edge 2  🔋 78%  [▓▓▓░░ vibe]  [⏻ Mute] [Test] [⌄]│
└────────────────────────────────────────────────────────────────────┘
```

Contents, left to right:

* **Product icon.** Existing Lovense icon override.
* **Connection dot.** Green when connected, red when stored-but-not-
  connected (replaces the `✓` / `⚠` text prefix).
* **Device name.**
* **Battery.** Existing `🔋 NN%`. If the device reports no battery,
  draw a custom "battery with slash" QPainter glyph (see
  `ui/icons.py` for the existing pattern). No Unicode 🪫 — too
  font-dependent.
* **Vibe meter.** Aggregate across motors: `max(motor_levels)`.
  Greyed out when muted.
* **⏻ Mute.** Per-toy soft-mute. When ON, the engine target for every
  motor on this toy is forced to 0; the mixer continues computing
  internally so the graph still shows real values. **Not persisted** —
  lives in controller memory only, cleared on app start and on profile
  switch. Mute is a session-level safety toggle, not a configured
  preference. If a toy should be permanently silent, remove it from
  the profile.
* **Test.** Short fixed pulse — 0.3 s at 0.5 intensity on every
  motor. Replaces the per-motor manual slider as the "is the toy
  alive?" check.
* **⌄ / ⌃.** Visual affordance for expand state; the whole bar is the
  click target.

### Expanded toy — motor cards stacked

```
┌────────────────────────────────────────────────────────────────────┐
│ [icon] ● Lovense Edge 2  🔋 78%  [▓▓▓░░ vibe]  [⏻ Mute] [Test] [⌃]│
├────────────────────────────────────────────────────────────────────┤
│  ┌─ Motor 0 · Thrust (linear) ──────────────────────────────────┐  │
│  │ LISTENING TO               │ MIX                             │  │
│  │  Zones [Crotch×][+]        │  ┌─DEPTH────┬─SPEED────┐        │  │
│  │  OSC   /avatar/.../crotch  │  │ Gain ▬●▬ │ Gain ▬●▬ │        │  │
│  │  ◉Touch ◉Pen ○Self ◉Others │  │ Curve∿   │ Curve∿   │        │  │
│  │                            │  │ Mode [+] │ Mode [+] │        │  │
│  │                            │  │ ▸ More   │ ▸ More   │        │  │
│  │                            │  └──────────┴──────────┘        │  │
│  │                            │  Combine: ( )Sum  (●)Max        │  │
│  │                            │  ▸ Output (Position/Speed, Idle…│  │
│  └────────────────────────────────────────────────────────────────┘ │
│                                                                     │
│  ┌─ Motor 1 · Vibrate ───────────────────────────────────────────┐  │
│  │ (same layout, no "Output" disclosure — vibrate has no physics)│  │
│  └────────────────────────────────────────────────────────────────┘ │
│                                                                     │
│                         [Delete device]                             │
└─────────────────────────────────────────────────────────────────────┘
```

Notes:

* **Motor cards are independent and always visible** once the toy is
  expanded. Not individually collapsible in v1; revisit when
  4-motor toys (OSR2) become a common case.
* **Motor card label** uses the feature kind that's already
  classified at connect time (`linear`, `vibrate`, etc.) — `Motor 0`
  becomes `Motor 0 · Thrust` or `Motor 0 · Vibrate`. Free clarity.
* **Listening To** holds inputs + filters (an input gate, not a
  mixer setting): zones, custom OSC addresses, Touch/Pen/Self/Others.
* **Mix** holds the new depth + speed channel UI (see Phase 2 for
  semantics; Phase 1 ships the shells with today's math).
* **Output** disclosure (linear-only) holds the linear physics
  knobs: physics model (Position-aware / Stroke-speed sine wave),
  idle behaviour (Hold / Rest), and — newly per-motor — min/max
  stroke, resting position, resting time, max strokes per second.
  Today these live in `LINEAR_DEFAULTS` and apply engine-wide; Phase
  2 promotes them per-motor.
* **Delete device** moves inside the expanded view so it can't be
  hit by accident on the narrow bar.

### Per-channel "More" expander

```
┌─SPEED ──────────────┐
│ Gain   ▬●▬          │
│ Curve  [∿]          │
│ Mode   [+/×]        │
│ ▾ More              │
│   Input deadband ●  │   ← was global; becomes per-motor
│   Output cutoff  ●  │
│   Decay τ        ●  │
│   [Reset channel]   │
└─────────────────────┘
```

The Depth channel's "More" exposes curve shape parameters
(power/exponent, S-curve midpoint) and the depth-side min/max remap.
Reset reverts that one channel on that one motor.

### Help Mode

A single toggle in the toolbar (or sidebar). When ON:

* A small `?` badge appears next to every knob, toggle, and section
  header in the Device Routing and Tune views.
* Clicking a `?` opens a small inline popover anchored to the
  control. Popover content: short text + a tiny diagram painted at
  runtime with QPainter — curve preview for "Curve", waveform for
  "Decay τ", before/after envelope for "Output cutoff", etc.
* Toggle OFF and all badges disappear; the layout does not reflow.

Why a mode toggle and not always-on tooltips: tooltips are
discovery-poor (users don't hover unless they know there's something
there), and the per-knob diagrams need more space than a tooltip
allows. Why not a dedicated Help tab: forces navigation and breaks
tuning flow.

### Storage (Phase 1)

**No migration**, same as Phase 2 — clean break.

* **Mute is not persisted.** The per-toy mute lives in controller
  memory only. App start: every toy unmuted. Profile switch:
  every toy unmuted. Read by the controller before forwarding router
  output to `haptic_engine.update_target()`. No field added to
  `profiles.json`.
* **Drop the legacy `motor_{i}_zone` (string) read-fallback.** Today
  the profile loader falls back to the old single-zone string when
  `motor_{i}_zones` (the list form) is missing. Remove that code
  path; manually strip any leftover `motor_{i}_zone` keys from local
  `profiles.json` as part of landing Phase 1.
* **Drop the per-motor manual-override field used by the legacy
  intensity slider** if it ever made it into `profiles.json`. Verify
  by grepping the codebase + the on-disk file before the PR — the
  slider may never have been persisted, in which case nothing to
  delete.

### Phase 1 open decisions

* **Test button behaviour.** 0.3 s pulse at 0.5? Ramp 0 → 1 → 0 over
  1 s? Hold-to-test (press and hold)? Recommend the simple fixed
  pulse for v1.
* **Per-curve visibility in the bar's vibe meter.** Currently
  proposed as `max(motors)`. Could also show one mini-bar per motor.
  Recommend max for simplicity until multi-motor toys are more
  common.

---

## Phase 2 — Mixer math rework

### Conceptual model

Two channels feed into the per-motor mixer. Each channel has:

| Field         | Type                          | Default     |
|---------------|-------------------------------|-------------|
| `enabled`     | bool                          | `true`      |
| `gain`        | float (0.0 – 2.0)             | `1.0`       |
| `curve`       | enum {linear, power, s_curve} | `linear`    |
| `curve_param` | float (depends on curve type) | `1.0`       |
| `mode`        | enum {additive, modulate}     | `additive`  |

Plus per-motor:

| Field             | Type                       | Default      |
|-------------------|----------------------------|--------------|
| `combine`         | enum {sum, max}            | `max`        |
| `modulator_range` | (min: 0.0–1.0, max: 0.0–2.0) | `(0.5, 1.5)` |

**Rule:** at most one channel can have `mode = modulate` at a time.
Setting one to `modulate` flips the other back to `additive` and
greys out its mode toggle.

### Math

Let `D_raw` = clamped raw depth signal, `S_raw` = derived motion-
speed signal (existing `speed_*` pipeline produces this).

Per channel: `X_shaped = curve(X_raw, curve_param) * gain`

Three resulting combination modes:

1. **Both additive.** `out = combine_op(D_shaped, S_shaped)` where
   `combine_op` is either `clamp(D_shaped + S_shaped, 0, 1)` or
   `max(D_shaped, S_shaped)` per the per-motor `combine` setting.
2. **Speed modulates depth.** `out = D_shaped *
   lerp(mod_min, mod_max, S_shaped)`. Depth is the carrier; speed
   gates it. With `mod_range = (0.5, 1.5)`: depth feels at 50% when
   there's no motion, 150% at full motion.
3. **Depth modulates speed.** `out = S_shaped *
   lerp(mod_min, mod_max, D_shaped)`. Symmetric.

Final `out` is clamped to `[0, 1]` before going to the engine.

The `lerp` form for modulators is intentional. `D * S` collapses to
zero whenever either input is zero — usually too harsh. The lerp
form gives the UX two intuitive endpoints ("at no input X, the
carrier feels at this fraction; at full input X, the carrier feels
at that fraction") which is easy to label and reason about.

### Storage (Phase 2)

The per-motor profile section gains a `mix` block:

```json
{
  "mix": {
    "depth": {
      "enabled": true,
      "gain": 1.0,
      "curve": "linear",
      "curve_param": 1.0,
      "mode": "additive",
      "min_remap": 0.0,
      "max_remap": 1.0
    },
    "speed": {
      "enabled": true,
      "gain": 1.0,
      "curve": "linear",
      "curve_param": 1.0,
      "mode": "additive",
      "input_deadband": 0.02,
      "output_cutoff": 0.05,
      "decay_tau": 0.4
    },
    "combine": "max",
    "modulator_range": [0.5, 1.5]
  }
}
```

**No migration.** The project has no external users yet, so this
redesign is treated as a clean break. When Phase 2 lands, the
following keys are removed outright with no compatibility shim:

* Global keys in `app_settings.json`: `speed_gain`,
  `speed_input_deadband`, `speed_output_cutoff`, `speed_decay_tau`.
* Per-motor key in every profile: `motor_{i}_speed_blend`.

**Action item when implementing:** as part of the Phase 2 PR,
delete the relevant entries from `%APPDATA%\OscGoesPurrr\app_settings.json`
and `profiles.json` on the dev machine, and make sure
`AppSettingsManager` / the profile loader silently ignore (do not
re-introduce) any of these keys if they're still present in an old
file. Hardcoded defaults in the new `mix` block become the only
source of truth.

### Linear physics (Output disclosure)

Promotes per-motor: `min_pos`, `max_pos`, `resting_pos`,
`resting_time_s`, `max_strokes_per_sec`. Stays global in
`LINEAR_DEFAULTS`: `max_v`, `max_a`, `duration_mult` (hardware-shape
parameters; users should not normally touch).

### Phase 2 open decisions

* **Curve types and parameters.** Locked candidates: `linear`,
  `power` (with exponent `0.3 – 3.0`), `s_curve` (with steepness
  parameter). Anything else (log, custom multi-point) is out of
  scope for v1.
* **Combine policy default.** `max` recommended over `sum` for
  consistency with the motor router's existing multi-zone merging
  ("max-wins per dot" — see ROADMAP's SPS-mirror entry) and to
  preserve dynamic range at high gains.
* **Whether `combine` is per-motor or per-toy.** Recommend per-motor
  for consistency with the rest of the Mix card.

---

## Phase 3 — Tune tab with live graph and simulated input

A new top-level sidebar view alongside Device Routing, OSC
Inspector, etc. Selects one motor at a time. Shows:

* A live multi-curve graph (last ~3 s, scrolling).
* The same Mix controls as the Device Routing motor card —
  identical state, identical layout — so edits there reflect
  instantly in the graph.
* A source picker: **Simulated** or **Live VRChat**.
* When Simulated: a pattern picker and a Send-to-toy safety switch.

### Curves shown

Five overlay traces, each independently toggleable on/off via a
legend on the side of the graph:

| Trace            | Source                                  | Default vis |
|------------------|-----------------------------------------|-------------|
| Raw depth        | `D_raw` from the Brain                  | on          |
| Raw speed        | `S_raw` from the speed-derivation pipe  | on          |
| Depth influence  | `D_shaped = curve(D_raw) * gain`        | on          |
| Speed influence  | `S_shaped = curve(S_raw) * gain`        | on          |
| **Final output** | post-combine, post-clamp                | on (bold)   |

Toggling traces off lets the user focus on a single setting — e.g.
turn off Raw and Final, leave only Depth influence visible while
adjusting the depth curve.

### Source: Simulated

A small library of patterns the user can replay endlessly to tune
against:

* **Slow stroke** — sine at ~0.4 Hz
* **Medium stroke** — sine at ~1 Hz
* **Fast stroke** — sine at ~2 Hz
* **Fast-in / slow-out** — asymmetric sawtooth (sharp rise, gentle
  fall)
* **Burst** — rectangular envelope, on for 1 s every 3 s
* **Tease** — random-walk-modulated sine

Each pattern is a small generator function that writes synthetic OGB
parameters into `parameter_store.store`. The router consumes them
exactly as if they came from VRChat, so the entire signal chain
behaves identically.

### Source: Live VRChat

Same graph, real OSC data. The pattern picker greys out. The
Send-to-toy switch is hidden (we never want to silently swallow live
output the user assumes is going to the toy).

### Safety: Send-to-toy switch (Simulated only)

When Simulated and **Send to toy = off**: the engine receives 0 for
the selected motor regardless of what the mixer produces. The graph
still shows real values. This lets users tune without physical
feedback and without accidentally surprising someone.

Default: off the first time the user opens Tune. The switch is
sticky per session.

### Architecture

Three new pieces:

1. **`tune_pattern_generator.py`** — runs on its own thread,
   produces synthetic parameter writes. Sealed-box: primitive-only
   public methods (`start(pattern_name, motor_targets)`, `stop()`,
   `list_patterns()`). Writes to `parameter_store.store` and
   nothing else.
2. **`motor_router.py` intermediates surface** — when the Tune tab
   is active, the router emits a debug record per tick on the
   `thread_queue` containing the five traces for the selected
   motor. Off by default — zero cost when the Tune tab is closed.
   Exact form: `{"type": "tune_trace", "device": "...", "motor":
   N, "t_ms": ..., "d_raw": ..., "s_raw": ..., "d_shaped": ...,
   "s_shaped": ..., "out": ...}`.
3. **`controllers/tune_facade.py`** — `TuneFacade` mixin composed
   into `OscGoesPurrrApp`. UI-facing methods: `tune_select_motor()`,
   `tune_set_source()`, `tune_start_pattern()`, `tune_stop_pattern()`,
   `tune_set_send_to_toy()`. The mixin owns the running pattern
   generator and the trace subscription.

The UI side is a `QtCharts`-or-`QPainter` widget that consumes the
trace queue. `QtCharts` is fine if the dependency is already
acceptable; otherwise a custom `QPainter` widget with a ring buffer
is straightforward and matches the project's "draw widgets ourselves"
approach already used for `RainbowMeter`.

### Phase 3 open decisions

* **Graph window length.** Default 3 s; could expose a zoom in the
  toolbar (1 s / 3 s / 10 s). Recommend ship with 3 s only.
* **Mini-graph in the Device Routing motor card.** Cheap to add a
  small total-output-only trace at the bottom of the Mix card.
  Tempting but adds visual noise to the routing UI. Skip for v1;
  add later if users ask.
* **Render tech.** `QtCharts` vs custom `QPainter` — defer to
  implementation time, no design implication.

---

## Out of scope

* **Audio-reactive routing.** Tracked in `ROADMAP.md`; lands as a
  third input source after this redesign. The mixer should not be
  generalized to N channels until that work begins — premature.
* **New haptic backends.** No changes to `BHapticsEngine` /
  `SteamVREngine`.
* **Profile schema overhaul.** This work adds fields; it does not
  restructure the profile format.

## Cross-references

* `ARCHITECTURE.md` — sealed engine / stateless router /
  controller-mixin pattern; the four anti-tangling rules; how to add
  a new sidebar view.
* `ROADMAP.md` — audio-reactive routing (later, related), SPS
  priority layering (later, may interact with the modulator math),
  per-input max-value clamp (could be absorbed into the mixer or
  stay separate).
* `haptic_engine.py` — `LinearActuator`, `StrokeSpeedActuator`,
  `LINEAR_DEFAULTS`.
* `motor_router.py` — current per-motor config keys, existing
  speed-derivation pipeline.
