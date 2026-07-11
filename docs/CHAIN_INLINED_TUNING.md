# Chain-Inlined Tuning

Successor to `MOTOR_SIGNAL_CHAIN.md` (the original signal-chain
redesign through Cut 5). Collapses the Tune view's "watch the signal
move" affordances into the chain widget itself: per-stage mini-graphs
below each stage editor, a wrapper-level simulator with parametric
(frequency / amplitude / waveform) input generation, and an optional
collapsible six-trace overview. Tune's dedicated view shrinks to
near-zero — its mix-card embedding was already the chain widget, and
this redesign moves the rest of the value (graphs, simulator) into
the wrapper.

**Why now.** The 1:1 promise from MOTOR_SIGNAL_CHAIN.md — "one
editing surface, two contexts" — has a logical conclusion. If the
controls are the same in two views, the two views are conceptually
one. Inlining the live traces and the simulator into the chain
widget gives tuning a single home: the same card where you set
gains, curves, and the gate is also the card where you see them
work. No more "edit here, watch there, switch back."

Two consequences worth landing up front:

1. **Per-chain speed state.** Today's speed detector lives at the
   motor level — one `last_position` + one `smoothed_speed` shared
   across chains, because both chains see the same `d_raw`. The
   moment we let the simulator drive only one chain at a time (the
   Drive-mask feature below), the two chains see different `d_raw`
   streams and each needs its own speed history. The refactor is
   small (move two floats into per-chain state, call
   `_derive_speed_signal` once per chain), but load-bearing for both
   the Drive mask and for honest per-stage graphs.

2. **Tune's dedicated graphs become a wrapper feature.** The
   six-trace overview moves to the wrapper as an optional `▸ Overview`
   disclosure (off by default). Tune's separate stages strip and
   mix-card embedding become a single passthrough that just opens
   the wrapper for one motor.

Conceptually affected:

* `motor_router.py` — per-chain speed state; per-(motor, chain)
  intermediates subscription model; Drive-mask support on the input
  override; deletion of the single-subscription `set_tune_*` path
  once Cut 8 lands.
* `mixer.py` — new `sample_pattern(freq_hz, amp, waveform, t_s)`
  primitive for the parametric simulator.
* `tune_pattern_generator.py` — **deleted in Cut 7.** Preset zoo
  replaced by the parametric sampler.
* `ui/motor_signal_chain.py` — per-stage mini-graphs below each
  stage editor; chain widget subscribes to its own intermediates;
  wrapper gains the simulator panel and the optional overview
  graph.
* `ui/views/tune.py` — shrinks dramatically in Cut 8. Becomes a
  motor picker + the embedded wrapper (which is already what
  Device Routing is, minus toy-level chrome).
* `controllers/tune_facade.py` — `tune_start_pattern` / `tune_get_status`
  reshape around the parametric sampler.

This redesign does **not** change the chains-list schema from Cut 5
(`mix.<motor> = {chains: [...], merge}`). Storage stays stable.

---

## The chain visual after Cut 6/7/8

Single-chain motor:

```
┌ Motor 0 · Thrust ──────────────────────────────────────────────┐
│ ▸ Simulated input                                              │
│                                                                │
│ [Input] → [Depth] ↘                                            │
│                    [Combine] → [Gate] → [Smoothing]            │
│         [Speed] ↗               → [Zero cut] → [Output]        │
│                                                                │
│  ▾ Depth                              ←  active stage          │
│    Gain: [1.00]   Curve: [linear ▾]   Param: [—]               │
│    ┌──────────────────────────────────────────────────────┐    │
│    │  · · · · · · ·  d_raw                                │    │
│    │       ────────  d_shaped (= d_raw at gain=1, linear) │    │
│    └──────────────────────────────────────────────────────┘    │
│                                                                │
│  ████░░░░░░  vibe meter                                        │
│                                                                │
│  ▸ Overview (all six traces)                                   │
└────────────────────────────────────────────────────────────────┘
```

Two-chain motor — wrapper renders both per-chain widgets with the
Merge picker between them, and the simulator panel up top gains a
Drive selector:

```
┌ Motor 0 · Thrust ──────────────────────────────────────────────┐
│ ▾ Simulated input                                              │
│   Frequency: [1.0 Hz]   Amplitude: [1.00]   Waveform: [Sine ▾] │
│   Drive: [Both ▾]    [▶ Play]  [■ Stop]    ☐ Send to toy       │
│                                                                │
│  [Chain 1 widget — has its own per-stage graph]                │
│                                                                │
│  Merge chains: [Add] [●Max] [Multiply]                         │
│                                                                │
│  [Chain 2 widget — has its own per-stage graph]                │
│  [✕ Remove Chain 2]                                            │
│                                                                │
│  ▸ Overview (all six traces)                                   │
└────────────────────────────────────────────────────────────────┘
```

---

## Per-chain speed state

`MotorRouter._motor_state[(device, motor)]` reshape:

Before (Cut 1–5):

```python
{
    "last_time":      -1.0,
    "last_position":  0.0,   # motor-level: shared by both chains
    "smoothed_speed": 0.0,   # motor-level
    "chains": [
        {"smoothed_output": 0.0, "activity_meter": 0.0,
         "gate_open": False, "below_since": None},
        # ...
    ],
}
```

After (Cut 6):

```python
{
    "last_time": -1.0,                # motor-level: dt is shared
    "chains": [
        {
            "last_position":   0.0,   # ← moves here
            "smoothed_speed":  0.0,   # ← moves here
            "smoothed_output": 0.0,
            "activity_meter":  0.0,
            "gate_open":       False,
            "below_since":     None,
        },
        # ...
    ],
}
```

`last_time` stays motor-level because `dt` is identical for both
chains (they tick together). `last_position` and `smoothed_speed`
move into per-chain state because each chain sees its own `d_raw`
depending on the Drive mask.

`_derive_speed_signal` becomes per-chain — it takes the chain's
state dict instead of the motor's. `_calculate_motor_target` calls
it once per chain inside the chain loop.

`reset_outputs` still calls `self._motor_state.clear()` — the per-
chain reset falls out of the wholesale clear.

---

## Per-(motor, chain) intermediates subscription

Today's router has a single subscription slot:

```python
self._tune_subscription: Optional[Tuple[str, int, int]]
self._tune_emit_callback: Optional[Callable]
```

For inlined per-stage graphs, every visible chain widget needs its
own live trace feed. Multiple subscribers, keyed by `(device, motor,
chain_idx)`.

New API on `MotorRouter`:

```python
def subscribe_intermediates(
    self,
    device: str, motor: int, chain: int,
    callback: Callable[[Dict[str, Any]], None],
) -> None:
    """Add a callback for one (motor, chain). Multiple subscribers
    per key allowed (chain widget + Tune overview may both watch
    chain 0 of motor 0)."""

def unsubscribe_intermediates(
    self,
    device: str, motor: int, chain: int,
    callback: Callable[[Dict[str, Any]], None],
) -> None:
    """Remove a previously registered callback. No-op if not found."""

def has_intermediates_subscribers(self) -> bool:
    """Used by main.py's routing tick to keep ticking when any
    chain widget is watching (replaces has_tune_subscription)."""
```

Internal state:

```python
self._intermediates_subscribers: Dict[
    Tuple[str, int, int], List[Callable[[Dict[str, Any]], None]]
] = {}
```

The router's per-tick emit walks `chain_emits` and fires the
matching callbacks for each `(device, motor, chain_idx)` key. Zero
cost when the dict is empty.

**Legacy compatibility.** `set_tune_subscription` /
`set_tune_emit_callback` / `clear_tune_subscription` stay around in
Cut 6 as thin adapters around the new API:

* `set_tune_subscription(dev, motor, chain=0)` →
  `subscribe_intermediates(dev, motor, chain, self._legacy_tune_cb)`
* `clear_tune_subscription()` →
  `unsubscribe_intermediates(..., self._legacy_tune_cb)`

This keeps `controllers/tune_facade.py` and `ui/views/tune.py`
working without surgery until Cut 8 retires them.

---

## Per-stage graph trace mapping

Each chain widget builds one TraceGraph below the active stage's
editor. The graph is constructed lazily on first stage activation
(matches the existing lazy editor pages). When a different stage
is opened, the graph rebuilds with that stage's trace set.

Trace IDs are stable; widgets read the same emit dict the router
broadcasts. Style follows the existing Tune trace conventions
(solid for raw, dashed for shaped, dotted for post-mix, bold for
final).

| Stage     | Trace IDs shown                  | Why                                 |
|-----------|----------------------------------|-------------------------------------|
| Input     | `d_raw`                          | What this chain is being fed.       |
| Depth     | `d_raw`, `d_shaped`              | Curve + gain effect at a glance.    |
| Speed     | `s_raw`, `s_shaped`              | Same idea for the speed channel.    |
| Combine   | `d_shaped`, `s_shaped`, `mixed`  | Both channels and their merge.      |
| Gate      | `mixed`, `gated`                 | What the gate let through.          |
|           | (activity meter visual stays)    |                                     |
| Smoothing | `gated`, `smoothed`              | Envelope's effect on the gate step. |
| Zero cut  | `smoothed`, `out`                | The tail being cut to silence.      |
| Output    | `out`                            | Final chain output.                 |

`smoothed` is the post-smoothing, pre-zero-cut value; `out` is the
chain's final output (identical while the zero cut is disabled or
the input is live). For single-chain motors, `out` = the motor
target. For two-chain motors, `out` = this chain's per-chain output
(pre-merge).
The merged-final is available in the wrapper-level overview graph
and as the vibe-meter value at the bottom of each chain.

Graph dimensions: ~60 px tall, full editor width. Window length:
3 s (matches the old per-motor mini-graph in Cuts 1–4).

---

## Simulator panel

One simulator per motor, owned by `MotorChainListWidget`. Positioned
at the top of the wrapper, collapsed (`▸ Simulated input`) by
default. When expanded, all the controls below appear in a
horizontal row.

**Controls:**

* **Frequency** — `QDoubleSpinBox`, 0.05–5.0 Hz, step 0.05, 2
  decimals, suffix ` Hz`. Default 1.0.
* **Amplitude** — `QDoubleSpinBox`, 0.0–1.0, step 0.05, 2
  decimals. Default 1.0.
* **Waveform** — `QComboBox`: `sine`, `square`, `triangle`,
  `sawtooth`. Default `sine`.
* **Drive** — `QComboBox`: `Both`, `Chain 1 only`, `Chain 2 only`.
  Hidden when the motor has only one chain. Default `Both`.
* **Play / Stop** — buttons. Mutually exclusive disabled state
  (Play disabled while running, Stop disabled while idle).
* **Send to toy** — `ToggleSwitch`. Default OFF (safety carryover
  from today's Tune view).

When the simulator is running:

* `MotorChainListWidget` registers a `_tune_value_provider` against
  the router for each chain in the Drive mask. The provider is a
  closure capturing `(start_time, freq, amp, waveform)`; on each
  call it computes `sample_pattern(freq, amp, waveform, now -
  start_time)` and returns the value.
* Chains not in the Drive mask see live `d_raw` as normal — the
  provider returns `None` for them, falling through to the live
  compute path.
* When Send-to-toy is OFF, the engine should NOT receive the chain's
  output. Either: (a) the router masks the motor's final output to
  0 while simulator is running with Send-to-toy off, or (b) the
  controller suppresses the engine call. Option (a) is cleaner —
  one flag on the router, no controller awareness needed. Picked.

Stopping the simulator clears the per-chain providers and resets the
Send-to-toy mask. Pattern resets to phase 0 each Play (no resume).

**Pattern math** — `mixer.sample_pattern(freq_hz, amp, waveform, t_s)`:

```python
def sample_pattern(freq_hz, amp, waveform, t_s):
    """Periodic [0, amp] signal at frequency freq_hz, shape `waveform`.
    All waveforms are normalised so a full cycle spans [0, amp] in
    output (not [-amp, +amp]) — d_raw is unsigned by convention."""
    phase = (freq_hz * t_s) % 1.0  # [0, 1) within one cycle
    if waveform == "sine":
        # sin(2πφ) ∈ [-1, 1] → shifted/scaled to [0, 1]
        return amp * (0.5 + 0.5 * math.sin(2.0 * math.pi * phase))
    if waveform == "square":
        return amp if phase < 0.5 else 0.0
    if waveform == "triangle":
        # /\ peak at φ=0.5
        return amp * (2.0 * phase if phase < 0.5 else 2.0 * (1.0 - phase))
    if waveform == "sawtooth":
        # / ramp 0→amp over the cycle
        return amp * phase
    return 0.0  # unknown waveform → silence
```

Pure function, easy to unit-test. No state.

---

## Drive-mask semantics

The simulator's `Drive` selector maps to which chains' input is
overridden:

| Selector       | Chain 0 input | Chain 1 input |
|----------------|---------------|---------------|
| Both           | simulated     | simulated     |
| Chain 1 only   | simulated     | live          |
| Chain 2 only   | live          | simulated     |

For single-chain motors, the `Drive` selector is hidden — the only
option is `Both` (which is equivalent to `Chain 1 only` when there's
only chain 0).

**Router-side implementation** — replace `_tune_value_provider:
Optional[Callable[[], Optional[float]]]` with a per-chain provider
map:

```python
self._tune_value_providers: Dict[
    Tuple[str, int, int],            # (device, motor, chain_idx)
    Callable[[], Optional[float]],   # returns simulated d_raw or None
] = {}
```

In `_calculate_motor_target`, for each chain:

```python
provider = self._tune_value_providers.get((device_name, motor_idx, chain_idx))
sim_d_raw = provider() if provider is not None else None
chain_d_raw = sim_d_raw if sim_d_raw is not None else live_d_raw
```

`chain_d_raw` is what feeds the chain's `_derive_speed_signal`,
`apply_curve`, and so on. Different chains can have different
`chain_d_raw` values on the same tick.

Wrapper's "Play" handler:

```python
def _on_simulator_play(self):
    chain_mask = self._resolve_drive_mask()  # set of chain indices
    start = time.monotonic()
    freq, amp, waveform = self._read_simulator_controls()
    for chain_idx in chain_mask:
        self._controller.subscribe_simulator(
            self._device_name, self._motor_idx, chain_idx,
            lambda s=start, f=freq, a=amp, w=waveform:
                sample_pattern(f, a, w, time.monotonic() - s),
        )
```

(The `subscribe_simulator` facade method is a thin wrapper around
`motor_router.set_chain_value_provider(dev, motor, chain, provider)`.)

---

## Optional six-trace overview

Bottom of `MotorChainListWidget`, behind a `▸ Overview` disclosure.
Off by default per the locked decision (Q1). When expanded:

* Single `TraceGraph` widget at full wrapper width, ~120 px tall.
* Trace set matches today's Tune big graph:
  `d_raw`, `s_raw`, `d_shaped`, `s_shaped`, `mixed`, `out`.
* For two-chain motors, the overview shows **chain 0's traces** by
  default (preserves the single-chain behaviour). A small chain
  picker `[Chain 1 ▾]` next to the disclosure header lets the user
  switch which chain the overview observes.
* Window: 6 s (longer than per-stage mini-graphs so the user can
  see envelope behaviour at a glance).

The wrapper registers its own subscription against the router for
the displayed chain. When the user switches the picker, the
subscription rebinds.

Off by default means zero traces, zero subscription, zero cost when
the user hasn't asked for the view.

---

## Send-to-toy safety mask

A motor-level flag on the router:

```python
self._toy_output_suppressed: Set[Tuple[str, int]] = set()
```

`subscribe_simulator(dev, motor, chain, provider, send_to_toy)` and
`unsubscribe_simulator(dev, motor, chain)` manage entries.

In the controller's update loop (where the router's per-motor target
is forwarded to the engine), check:

```python
if (device_name, motor_idx) in router._toy_output_suppressed:
    # Drop on the floor — simulator is running and the user has
    # Send-to-toy off.
    return
```

(The clean version is a facade method `should_send_to_toy(dev, motor)
-> bool` so the controller doesn't reach into router internals.)

When the user toggles Send-to-toy ON mid-simulation, the entry is
removed from the suppressed set; the next tick's value flows to the
toy.

---

## Phased delivery

1. **Cut 6 — per-chain speed state + per-(motor, chain) subscription.**
   * Move `last_position` and `smoothed_speed` into per-chain state.
     Speed detector takes the chain's state dict.
   * Add `subscribe_intermediates` / `unsubscribe_intermediates`
     to the router. Internal subscriber dict. Legacy
     `set_tune_subscription` adapts to the new API.
   * Per-stage mini-graphs in `MotorSignalChainWidget`: one graph
     below the active stage editor, trace set per the table above,
     subscribed against the router via the new API. Graph rebuilds
     on stage change.
   * Tests: per-chain speed independence; subscriber API
     subscribe / unsubscribe; per-stage graph receives expected
     traces.

2. **Cut 7 — parametric simulator + Drive mask.**
   * `mixer.sample_pattern(freq, amp, waveform, t)` pure function.
     Replaces `tune_pattern_generator.py` (deleted) and its
     `_TUNE_PATTERNS` constants.
   * Router: per-chain `_tune_value_providers` dict; `set_chain_value_provider` /
     `clear_chain_value_provider`. The single `_tune_value_provider`
     attribute goes away.
   * Router: motor-level Send-to-toy suppression set;
     `should_send_to_toy(dev, motor)` facade.
   * Controller facade adapters: `subscribe_simulator`,
     `unsubscribe_simulator` (orchestrate provider + suppression).
   * Wrapper-level simulator panel (collapsed by default).
   * Tests: each waveform produces expected samples; Drive mask
     routes correctly (chain 0 simulated, chain 1 live, and vice
     versa); Send-to-toy suppression works.

3. **Cut 8 — overview disclosure + Tune view shrink.**
   * `▸ Overview` disclosure at the bottom of
     `MotorChainListWidget`, with chain picker for two-chain motors.
   * `ui/views/tune.py`: delete the local stages strip, the local
     pattern picker (now in the wrapper), the local source picker
     (ditto), and the legacy `_tune_*` subscription path. What's
     left: motor picker + embedded `MotorChainListWidget`.
   * `controllers/tune_facade.py`: simplify in line with the view
     shrink. The simulator facade calls move here.
   * `tune_pattern_generator.py` deleted.
   * The router's legacy `set_tune_subscription` /
     `set_tune_emit_callback` / `_tune_value_provider` attributes
     are removed; their sole remaining caller (Tune view) has been
     rewritten to use the new APIs.

Each cut leaves the codebase functional. Cut 6 ships the per-stage
graphs immediately; Cut 7 makes them more useful with a real
parametric simulator; Cut 8 is pure cleanup.

---

## Open questions / explicit non-decisions

* **Pattern phase reset on Play.** Locked: each Play starts the
  sampler at `t=0`. No "resume from where you stopped." Simpler
  semantics and matches every other periodic-signal generator.
* **Drive picker for single-chain motors.** Hidden. Single-chain
  motors only have one valid target.
* **Overview graph for two-chain motors.** Locked: defaults to
  chain 0, picker lets the user switch to chain 1. No "show both
  chains overlaid" mode — that's six traces × two chains = visual
  noise.
* **Send-to-toy default OFF.** Locked. The user has to opt in to
  hardware output during tuning.
* **What happens if a chain's gate closes while the simulator is
  driving it?** Same thing that happens during live operation:
  output goes to 0 (after fall_ms smoothing). The simulator
  doesn't bypass the gate; tuning the gate's response *is* a
  reason to drive the chain with the simulator.
