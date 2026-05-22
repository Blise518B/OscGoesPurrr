# Router test suite — working punch-list

Source: planned in conversation; see [`../ROADMAP.md`](../ROADMAP.md)
"Stateless router test suite" entry and
[`../ROUTING_REDESIGN.md`](../ROUTING_REDESIGN.md) for why this exists
(precondition for the routing redesign Phase 2 mixer math rework).

Tick a box as each test lands. Tests live in
[`test_helpers.py`](test_helpers.py) (module-level helpers) and
[`test_motor_router.py`](test_motor_router.py) (anything that needs a
`MotorRouter` instance).

## Tier 1 — fast wins, biggest behavioural coverage

### `_classify_zone_path` (module helper)
- [x] Recognises `OGB/Orifice/<name>` → `("Orf", name)`
- [x] Recognises `OGB/Orf/<name>` → `("Orf", name)`
- [x] Recognises `OGB/Penetrator/<name>` → `("Pen", name)`
- [x] Recognises `OGB/Pen/<name>` → `("Pen", name)`
- [x] Rejects non-OGB paths → `None`
- [x] Rejects unknown category under OGB → `None`

### `_clean_custom_addr` (module helper)
- [x] Strips `/avatar/parameters/` prefix
- [x] Strips bare leading `/`
- [x] Leaves prefix-free addresses alone
- [x] Empty string passes through unchanged

### `_coerce_blend` (static method)
- [x] Float in range → unchanged
- [x] `< 0` → 0
- [x] `> 1` → 1
- [x] `None` → 0
- [x] Bad string → 0

### `_compile_motor_config` (router method)
- [x] Splits custom addresses into literals vs globs
- [x] Cleans `/avatar/parameters/` from custom addresses
- [x] Parses comma-separated zone string into a set
- [x] Drops empty and `"None"` zone entries
- [x] Detects `"All SPS"` and exposes `is_all_sps`

### `_zone_contribution` filter matrix (router method)
- [x] `allow_touch=False` blocks both TouchSelf and TouchOthers
- [x] `allow_pen=False` blocks both PenSelf and PenOthers
- [x] `allow_self=False` excludes Self contributions
- [x] `allow_others=False` excludes Others contributions
- [x] `TouchSelfClose=False` gates out TouchSelf even when allowed
- [x] `TouchOthersClose=False` gates out TouchOthers even when allowed
- [x] `PenOthersClose` missing → defaults to true (legacy passes)
- [x] `PenOthersClose=False` blocks legacy `PenOthers`
- [x] Multiple contributions → max-wins
- [x] No contributions → returns `0.0`

## Tier 2 — speed-blend math (most exposed to the upcoming Phase 2 rework)

### `_apply_speed_blend` endpoints (router method, needs FakeClock)
- [x] `blend == 0` → returns position unchanged
- [x] `blend == 1` → returns derived speed only
- [x] `blend == 0.5` → linear interpolation of the two

### Speed signal — static input
- [x] Constant position over time → smoothed speed stays at 0 (deadband)
- [x] Sub-deadband jitter → smoothed speed stays at 0

### Speed signal — moving input
- [x] Step change in position → smoothed speed rises above 0
- [x] Larger step → larger smoothed speed (up to clamp at 1.0)

### Speed signal — decay
- [x] After motion stops, smoothed signal decays exponentially toward 0
- [x] Decay rate scales with `speed_decay_tau`

### Output cutoff
- [x] Smoothed value below `speed_output_cutoff` snaps to true 0
- [x] Smoothed value above cutoff is rescaled to `[0, 1]`
- [x] Smoothed value at exactly cutoff → 0

### `apply_speed_tuning` clamping
- [x] `speed_input_deadband` clamped to `[0, 0.5]`
- [x] `speed_gain` clamped to `[0, 50]`
- [x] `speed_decay_tau` clamped to `[0.01, 5.0]` (never zero — exp blows up)
- [x] `speed_output_cutoff` clamped to `[0, 0.95]`
- [x] Non-numeric input is silently ignored

## Tier 3 — integration

- [x] `_calculate_motor_target` end-to-end
- [x] `reevaluate_state` debouncing
- [x] `reevaluate_simple_mode` global value to all motors
- [x] `reset_outputs` clears both `last_outputs` and `_speed_state`

## Tier 4 — depth model

- [x] `GameDeviceLengthDetector` state machine
- [x] `_get_new_pen_amount` calibrated depth
- [x] `_update_length_detectors` Orf-only feeding

## Tier 5 — hardening

- [x] Compiled config cache invalidation on profile mutation
- [x] Compiled config cache bounded at 256 entries
- [x] Bad-type inputs handled gracefully everywhere

---

## Running the suite

From the repo root:

```
pip install -r requirements-dev.txt
pytest
```

Tests live in `tests/`. Config is in `pytest.ini` at the repo root.
