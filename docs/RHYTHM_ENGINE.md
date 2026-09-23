# Rhythm Engine: Lock the Stroke, Synthesize the Feel

A planned alternative routing path for the Buttplug backend that stops
*filtering* the messy VRChat motion signal and instead *estimates the
rhythm* underneath it, then **resynthesizes a clean, deliberately nicer
output waveform** locked to that rhythm.

**Status:** design / brainstorm. Not scheduled, not committed, nothing
built. The output feel-model below is well pinned down; the analysis
method (how we actually detect the rhythm) is deliberately left open —
see "Detecting the rhythm". Treat this as the captured shape of the
idea, not a build spec.

**Where it lives.** This is *not* a sealed hardware engine in the
`ARCHITECTURE.md` sense (despite the name). It is a **router-side
analyzer + transform** — a stateful sibling to
`motor_router.GameDeviceLengthDetector`, owned by the router, feeding
the existing `HapticEngine` through the existing facade. It changes no
engine/router/facade boundaries.

---

## Why now

VRChat OSC contact/proximity data is noisy, jittery, irregularly
sampled, and occasionally dropped — and the current motor signal chain
(`MOTOR_SIGNAL_CHAIN.md`: Depth/Speed → Combine → Activity Gate →
Smoothing) fights that noise *subtractively*. Every stage either
averages the signal or gates it. The problem is structural, not a
tuning miss:

> Low-pass smoothing and per-stroke crispness are the **same knob**
> pulled in opposite directions. The more you smooth out the jitter,
> the more you blunt the actual stroke and add latency. You cannot
> tune your way out of it as long as you treat the signal as
> "truth + noise to subtract."

The reframe: treat the OSC stream not as a signal to clean, but as
**noisy evidence of a periodic process with hidden parameters**.
Estimate those parameters (tempo, phase, depth, amplitude), then run a
clean oscillator from them. The output is **generated, not filtered**,
so it can be perfectly smooth *and* perfectly crisp at the same time —
it was never made of the noise to begin with.

This is a known and powerful pattern under other names: a **phase-locked
loop** (lock a clean local oscillator to a noisy input clock),
**beat/tempo tracking** in music software (estimate tempo + beat phase,
then ride through missing onsets), and **adaptive frequency
oscillators** (Hopf / Righetti–Ijspeert — an oscillator that entrains
to the dominant frequency of an arbitrary periodic drive). "Lock onto
it instead of chasing it" is the whole move.

---

## Scope decisions (locked)

* **Vibrator-first; output is a single scalar.** Most users are on
  vibrators. The linear actuators in scope are exposed only as
  rotation/speed devices (no absolute-position control), so *every*
  output we care about is the same shape: one value in `[0, 1]` over
  time. No spatial mirroring, no position reproduction. The rhythm
  engine emits one clean intensity envelope and the existing routing
  fans it out identically — a vibrator's intensity or a rotator's
  speed, one code path.
* **Reinterpret, don't reproduce.** The detected rhythm is used as a
  *tempo + phase reference* to drive a deliberately **nicer** waveform,
  not to faithfully replay the measured motion. Decoupling "what the
  rhythm is" from "what it feels like" is the entire point.
* **Opt-in switch now, candidate default later.** Ships behind a user
  toggle, default **off**. If it proves better, it becomes the default
  — but it must always degrade safely first (see Fallback) so making it
  default can only help.
* **Confidence-gated crossfade to today's chain.** The switch enables
  the engine; *underneath* it, an automatic confidence crossfade blends
  between the synthesized rhythm output and today's filtered output.
  Low confidence **or** an unstable/erratic rhythm → fall back to the
  current behavior (not silence). The two switches are independent.

---

## What "the rhythm" is

The estimator's job is to recover a handful of latent parameters from
the depth signal and keep them updated every tick:

| Parameter | Meaning | Drives |
|---|---|---|
| **frequency** | strokes per second (~0.3–4 Hz typical, can spike) | tempo of the synth + overall level |
| **phase** | where in the current stroke we are, `[0, 1)` | the synth waveform's position; prediction |
| **amplitude / swing** | trough-to-peak range of the stroke | dynamic-range expansion |
| **center / avg depth** | where the stroke band sits, `[0, 1]` | overall level (deep = stronger) |
| **confidence + stability** | is this a real, steady rhythm? | the crossfade / fallback |

The signal we analyze is the **depth** signal — the router's `d_raw` /
new-pen insertion amount — because that's what oscillates. The existing
`s_raw` (speed) is its derivative (it peaks at mid-stroke), useful as an
onset cue but a poor phase reference.

---

## The feel model

This is the heart of the feature and the part that's fully decided. The
output is built in two layers: a **per-cycle waveform** (the shape you
feel each stroke) modulated by an **overall level** (how loud the whole
thing is right now).

```
output(t) = level · shape(phase ; expanded_swing)

  where  level = base · f_tempo(frequency) · f_depth(center)
```

### Layer 1 — the waveform (shape)

The synthesized per-cycle shape, driven at the detected `frequency` and
`phase`. Reuses the parametric generator that already exists:
`mixer.sample_pattern()` (`WAVEFORMS = sine / square / triangle /
sawtooth`). This is the primary **feel surface** and where most tuning
time will go.

* A pure **sine is symmetric** — on a vibrator you literally cannot
  feel in from out. If "feel the difference between in and out" matters,
  an **asymmetric** envelope (sharp rise / soft fall, à la the sawtooth)
  bakes direction into the loudness itself.
* Candidate shapes: a symmetric **swell**, a **directional ramp**
  (in-stroke louder than out), or a **percussive accent** (a pulse at
  full insertion — the "beat"). Custom envelopes are an open question.

### Layer 2 — dynamic-range expansion (contrast)

The user-described keystone: *"if I'm only using 20% of the wave,
expand it to 50% so you feel a better difference between in and out."*
This is **rhythm-locked dynamic-range expansion** — the inverse of an
audio compressor. It is only safe **because** the cycle is locked: we
know the trough and peak, so we can stretch the swing around the
cycle's own min/max instead of amplifying raw jitter.

Mechanism (per the decision: **floor + multiplier**):

1. Track an adaptive per-cycle envelope — the trough and peak of the
   depth signal over the last few strokes.
2. **Floor:** guarantee a minimum output contrast/width, so even a
   genuinely shallow-but-real stroke reads clearly.
3. **Multiplier:** above the floor, scale the natural swing by a gain so
   bigger strokes stay proportionally bigger (expressiveness preserved).

> **Two different floors — do not conflate them.**
> * The **gate floor** (below) decides *whether there is a real stroke
>   at all*; below it, the engine doesn't run — this is what stops us
>   amplifying noise into phantom strokes.
> * The **expansion floor** here applies *only after* we've decided the
>   stroke is real, guaranteeing a minimum legible contrast.
>
> Gate first ("is this real?"), then floor-plus-multiply the contrast.

### Layer 3 — overall level (loudness)

Two independent drivers scale the whole output, on top of the waveform:

* **Tempo → intensity.** Faster rhythm feels stronger. `f_tempo` rises
  with detected `frequency`.
* **Average depth → intensity.** A stroke oscillating in the 10–30%
  depth band should feel **weaker** than one in the 80–100% band, even
  at the same tempo and swing. `f_depth` rises with the stroke's
  **center** (band position), distinct from its **width** (which feeds
  expansion in Layer 2).

So: deep + fast = loud and punchy; shallow + slow = gentle — while the
per-stroke contrast stays legible at every level thanks to expansion.

---

## Confidence and fallback

The engine must know when it *doesn't* have a rhythm and get out of the
way. A rhythm engine that keeps pulsing after the partner stopped, or
that imposes a beat on a slow grind, feels uncanny — worse than the
noise it replaced.

**Confidence** is not just instantaneous periodicity strength; it must
include **stability over time**. A "rhythm" whose frequency/phase keeps
jumping (e.g. octave flips, constant pace changes, repositioning) is not
locked and should be treated as low-confidence.

**Fallback triggers (either one):**

1. Low confidence — no clear periodic structure (paused, still,
   non-rhythmic grind).
2. Instability — a rhythm is present but changing too much to lock.

**Fallback behavior:** crossfade to **today's filtered output** (the
existing chain), not silence. Reverting to current behavior in the bad
cases is exactly what makes "promote to default" safe — when confident,
it's better; when not, it's no worse than today. The synthesized
oscillator should also **spin down gracefully** rather than coast
forever when the rhythm dies.

---

## Detecting the rhythm (open — _Pending_)

The analysis method is unresolved. The non-obvious constraint that picks
the method: **VRChat OSC arrives at jittery, non-uniform intervals with
dropouts** (the whole reason `GameDeviceLengthDetector` exists). That
rules some classic methods in and others out.

* **FFT / autocorrelation** — assume a uniform time grid (must resample
  first) and need 2–3 cycles of history before they're confident.
  (Aside: the **Lomb–Scargle periodogram** was built by astronomers for
  exactly "unevenly-sampled noisy periodic data" — the FFT's cousin that
  doesn't need a uniform grid.)
* **Adaptive oscillator / PLL** and **Kalman filter with an oscillator
  state-model** — *eat irregular timing natively*: predict the phase
  forward by whatever `dt` elapsed, correct when a sample arrives. A
  dropout just means "don't correct" and the oscillator coasts. **This
  family is the natural fit for our data** — the thing that breaks the
  others is a non-issue here. A Kalman/EKF version also yields the
  confidence/stability signal from its covariance for free.

**Known hazard — octave errors.** PLLs and autocorrelation famously lock
onto half or double the true rate (the tempo-halving bug in every beat
tracker). Needs explicit handling.

---

## Bonus: prediction (optional enhancement)

Once locked, the oscillator **knows where the next stroke peak will be
before it happens** — something no reactive filter can do. That lets us
fire the toy command *slightly ahead* of the predicted peak to cancel
Bluetooth + motor spin-up latency, so a percussive accent actually lands
*on the beat*. Most valuable for the "pulse at full insertion" feel.
Not required for v1; a natural follow-on once the lock is solid.

---

## Architecture fit

Three things make this less of a leap than it sounds — the bones already
exist:

* **Precedent for a router-owned analyzer.** `GameDeviceLengthDetector`
  is already a small *stateful* estimator the "stateless" router owns
  (the router is stateless re: profiles/hardware, not re: signal
  history). A `RhythmEstimator` is its sibling — same pattern, lives
  next to it.
* **The generator and the manual twin already exist.**
  `mixer.sample_pattern()` is the parametric oscillator; the Cut 7
  simulator (`CHAIN_INLINED_TUNING.md`) already drives a motor from a
  freq/amp/waveform via `_chain_value_providers`. **The rhythm engine is
  that simulator with an *estimator* setting the knobs from live motion
  instead of a human.**
* **The crossfade has a home.** The motor router already supports up to
  two chains per motor with a `merge` op (`_MAX_CHAINS_PER_MOTOR`,
  `mixer.merge_chains`). The confidence crossfade between "rhythm chain"
  and "filtered chain" is conceptually that same parallel-chain merge,
  weighted by confidence.

```
              ┌──────────────── existing signal chain ────────────────┐
  d_raw ──────┤  Depth/Speed → Combine → Activity Gate → Smoothing    ├──→ filtered ─┐
 (depth over  └────────────────────────────────────────────────────────┘             │
  time)                                                                                ├─→ Output
              ┌──────────────────── rhythm chain ──────────────────────┐              │  (confidence
   history ──▶┤  Rhythm Estimator → (freq, phase, swing, center, conf)  ├──→ rhythm ───┘   crossfade)
              │            → Resynth (Layers 1–3 above)                  │
              └─────────────────────────────────────────────────────────┘
                                  conf ────────────────────────────────────► weights the crossfade
```

**Offline development is already possible — this is the big de-risker.**
The session logger (`SESSION_LOGGING.md`, the `_session_broadcast` /
`set_session_broadcast` machinery) already records real motion traces.
So we can **capture genuinely messy VRChat motion once, then build and
tune the entire estimator + feel-model against recordings in pure-Python
tests — no VRChat, no hardware, sandbox-friendly.** The hardest, most
iterative part can be developed and regression-tested offline.

**Relationship to the audio-reactive roadmap item.** This is the
SPS-side analog of the planned audio engine: motion-rhythm detection
where audio routing does onset/beat detection on sound. They're
independent sources but share the "estimate a periodic structure, drive
output from it" DNA. Worth keeping the two designs aware of each other.

---

## Phased delivery (proposed)

1. **Capture.** Record real, messy SPS motion traces via the existing
   session logger across a range of behaviors (slow, fast, pausing,
   shallow, deep, erratic).
2. **Estimator, offline.** Build `RhythmEstimator` as pure functions;
   validate frequency/phase/confidence tracking against the recordings
   with pytest. No hardware.
3. **Feel model, offline.** Implement Layers 1–3; render synthesized
   output from the estimates and compare against the raw traces.
4. **Live behind the flag.** Wire it as an opt-in routing mode with the
   confidence crossfade to the existing chain. Default off.
5. **Tune on hardware.** The subjective "feels good" pass — real toys,
   real human in the loop. Iterate waveform palette and the floor /
   multiplier / tempo / depth constants.
6. **Consider default.** Only once it's clearly better-when-confident
   and safe-when-not.

---

## Open questions

* **Analysis method** — adaptive oscillator / PLL vs. Kalman oscillator
  vs. autocorrelation / Lomb–Scargle. Leaning oscillator-family for the
  irregular-sampling reasons above. _Unresolved._
* **Octave-error handling** — how to detect and reject half/double-rate
  locks.
* **Waveform palette** — is the existing sine/square/triangle/sawtooth
  set enough, or do we want custom/asymmetric "feel" envelopes (swell /
  directional ramp / percussive accent)?
* **Tuning surface** — which of the floor, expansion multiplier,
  `f_tempo`, `f_depth`, confidence thresholds, and crossfade time are
  user-facing vs. baked constants? (Lean: baked sane defaults first, a
  hidden Advanced panel only if needed — same philosophy as the
  speed-detector constants in `motor_router`.)
* **Prediction in v1?** — latency-compensated "fire ahead of the beat,"
  or defer until the lock is proven.
* **Switch granularity** — global mode toggle vs. per-profile vs.
  per-motor.
