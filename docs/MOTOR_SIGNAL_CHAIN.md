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
     │                          Combine ──┬─→ Smoothing ─→ Output
     │   Speed (gain + curve) ─↗          │
     │                                    ▲
     └─→ Activity Gate ───────── valve ───┘
                                  (open / closed)
```

Six logical stages, left to right:

1. **Input** — what the motor listens to.
2. **Depth** — instantaneous magnitude path, gained + shaped.
3. **Speed** — derivative path, gained + shaped.
4. **Combine** — how Depth and Speed are merged.
5. **Activity Gate** — sidechain valve that suppresses output when
   input movement is below threshold.
6. **Smoothing** — post-combine rise/fall envelope.
7. **Output** — toy motor (vibrate or linear).

Depth and Speed run in parallel from a shared Input. The Activity Gate
runs in parallel too — it observes raw activity directly off the Input
stage's speed detector and acts as a valve on the combined signal
between Combine and Smoothing. Smoothing sits **after** the gate so
gate transitions get rounded into the envelope and the toy never
clicks on/off.

---

## Per-stage details

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

Reads `|d/dt|` of the input.

Editor contents:

* **Gain** — same shape as Depth.
* **Curve** — same dropdown.
* **Param** — same.
* **Fall-off (ms)** — `QDoubleSpinBox`, 10–2000, step 50, default
  300. How long the speed signal keeps ringing after movement stops
  (the detector's peak-hold decay tau). Lower = snappier cut-off
  when stroking stops; higher = lingering tail.

Stored at `mix.<motor>.speed.{gain, curve, curve_param, decay_ms}`.

**Removed from current Speed:** `enabled` flag, `mode`,
`input_deadband`, `output_cutoff`, `decay_tau`. The first two of
those become invisible constants inside the speed detector (see
"Speed-detector constants" below); `decay_tau` came back as the
user-facing **Fall-off** knob (`decay_ms`) after field tuning showed
the fixed 300 ms tail reads as "the toy keeps going after I
stopped".

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

### Activity Gate

Sidechain valve. Observes the raw speed-detector signal (before
per-channel gain/curve) and gates the combined signal between Combine
and Smoothing.

Editor contents:

* **Enable** — toggle. **Off by default.** A new always-on gate would
  silently change every existing profile's feel.
* **Wake threshold** — `QDoubleSpinBox`, 0.0–1.0, step 0.01.
  Activity-meter level at which the gate opens.
* **Sleep delay** — `QDoubleSpinBox`, 0.0–10.0 s, step 0.1.
  How long activity must remain below threshold before the gate
  closes.
* **Build-up (s)** — `QDoubleSpinBox`, 0.01–10.0 s, step 0.1,
  default 0.05. The meter's attack tau: how long sustained movement
  takes to charge the activity meter. High values make the gate
  demand a few seconds of motion before waking instead of opening on
  the first twitch.
* **Decay (s)** — `QDoubleSpinBox`, 0.01–10.0 s, step 0.1, default
  0.5. The meter's release tau: how long the charged meter takes to
  drain once movement stops.

Stored at `mix.<motor>.gate.{enabled, wake_threshold, sleep_delay_s,
attack_s, release_s}`.

Internal model:

* An activity meter `A ∈ [0, 1]` rises with `|d/dt|` as an asymmetric
  EMA. Time constants are per-chain knobs with conservative defaults
  (they were hidden constants until the field-tuning pass found that
  a fixed 50 ms attack lets a single twitch spike the meter over the
  threshold — there was no way to require *sustained* movement):
  * `gate.attack_s` — default 0.05 (50 ms), fast rise so new movement
    registers immediately. Raise it to make the gate charge slowly.
  * `gate.release_s` — default 0.50 (500 ms), slow decay so brief
    stillness does not instantly drop the meter below threshold.
    Raise it to make the activity "budget" coast across pauses.
  Both are clamped to [0.01, 10.0] s by the router. The meter is
  clamped to `[0, 1]` (anti-windup).
* Gate state: open when `A ≥ wake_threshold`. Once open, closes after
  `A` has stayed below `wake_threshold` continuously for
  `sleep_delay_s` seconds.
* Output when gate is closed: 0 (the combined signal is multiplied by
  the gate state, which is 0 or 1 — *before* smoothing so the
  envelope rounds the transition).

**Smoothing applied to gate transitions.** The combined signal is
multiplied by the gate state (0 or 1) *before* the smoothing stage.
A gate close steps from `combined` to 0 — output is falling, so
`fall_ms` governs the slope. A gate open steps from 0 to `combined`
— output is rising, so `rise_ms` governs the slope. The user does
not need to think about this; the rise/fall knobs they already tuned
handle gate transitions automatically.

**Why this placement (sidechain, not inline).** Putting the gate in
parallel decouples sensitivity from feel tuning. Changing the depth
curve or speed gain does not accidentally retune what the gate
considers "active." The gate's input is per-input (avatar movement);
its tuning knobs are per-motor, so two motors on the same toy can
have different wake/sleep settings while seeing identical activity.

**Why the activity meter watches the speed detector, not a separate
integrator.** "Activity" and "speed" are the same primitive. Two
detectors would drift apart over time. Re-using the speed signal
means the activity meter operates in the same units the user sees in
Tune's Raw-speed trace.

**Visual.** The gate stage shows a thin horizontal activity meter
with a tick mark at `wake_threshold`. The gate symbol (a valve icon
or similar) flips open/closed when the bar crosses the line. Reads
like a VU meter with a threshold mark.

### Smoothing

Post-mix envelope follower. Today's `attack_ms` / `release_ms`,
renamed for clarity.

Editor contents:

* **Rise (ms)** — `QDoubleSpinBox`, 0–2000, step 10, default 50.
* **Fall (ms)** — `QDoubleSpinBox`, 0–2000, step 10, default 20.

Stored at `mix.<motor>.smoothing.{rise_ms, fall_ms}`. (Renamed from
`attack_ms` / `release_ms` on disk too.)

### Output

The toy motor. Editor contents depend on motor kind.

**Vibrate motor:**

* Just the vibe meter (read-only).

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

Storage keys unchanged.

**Gate × linear actuator.** The chain is motor-kind agnostic — when
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
│                      [Combine] ─→ [Smoothing] ─→ [Output]       │
│           [Speed] ↗      ▲                                      │
│                          │                                      │
│  [Activity Gate] ────────┘                                      │
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
            "combine": "max",                  # "add" | "max" | "multiply"
            "gate": {
                "enabled": False,
                "wake_threshold": 0.05,
                "sleep_delay_s": 0.5,
                "attack_s": 0.05,
                "release_s": 0.5,
            },
            "smoothing": {"rise_ms": 50.0, "fall_ms": 20.0},
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
* **Gate default off.** Existing tuned profiles stay silent on the
  gate. Users opt in per motor. Locked.
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
linear, gate disabled, smoothing 0/0 ms. The case where a second
chain genuinely earns its keep is when you want the heavily-processed
behavior *and* the raw behavior simultaneously on the same motor,
which is real but rarer than it first sounds.

### Design

* Each motor holds a list of chains, length 1 by default, **capped
  at 2.** Resist the temptation to allow N — two handles every
  realistic main+override use case; three becomes a configuration
  maze and the diagram stops fitting on a card.
* Chains are structurally identical — both have the full Input →
  Depth/Speed → Combine → Gate → Smoothing pipeline. There is no
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
