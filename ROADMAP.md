# OscGoesPurrr — Roadmap

A loose list of features we want to land, grouped by theme.
Order within a group is rough priority, not a hard sequence.

## Haptics Features

- **Routing redesign: per-motor mixer, UI refresh, live tuning.**
  Full overhaul of Device Routing — collapsed-by-default toy cards,
  a new two-channel depth/speed mixer with per-channel gain / curve /
  modulate-other modes, Help Mode for in-context parameter
  explanations, and a new Tune tab with a live multi-curve graph and
  simulated input patterns for offline tuning. Phased: UI shell →
  mixer math → Tune tab. See [`ROUTING_REDESIGN.md`](ROUTING_REDESIGN.md).

- **SPS → bHaptics zone mirror.**
  When an OGB SPS contact fires (Boob, Tummy, etc.), also pulse a
  configured subset of bHaptics dots so the suit reinforces what the
  toy is feeling. Defaults that ship out of the box:

  | OGB zone | bHaptics target | Dots |
  |---|---|---|
  | Boob (chest) | VestFront | 5, 6, 9, 10 (center-upper) |
  | Tummy        | VestFront | 13, 14, 17, 18 (center-lower) |
  | Booty        | VestBack  | (TBD — pick equivalent center-lower indices) |
  | Crotch       | VestFront | 17, 18, 19 (belt line, lower) |
  | Tail         | VestBack  | (TBD) |
  | Head         | Head      | all 6 dots |

  **VestFront grid reference** (4 cols × 5 rows, indexed left-to-right
  top-to-bottom — see `bhaptics_router._GRID_LAYOUTS`):
  ```
  Row 0:  0  1  2  3   ← upper chest / collarbone
  Row 1:  4  5  6  7   ← chest (boobs)
  Row 2:  8  9 10 11   ← lower chest / solar plexus
  Row 3: 12 13 14 15   ← tummy
  Row 4: 16 17 18 19   ← lower tummy / belt
  ```
  VestBack uses the same 4×5 layout.

  **Design decisions (locked):**
  * Hybrid mapping: built-in defaults + user-editable table on a
    "Cross-Routing" sub-tab inside the bHaptics view.
  * OGB zone source = **picker** populated from
    `parameter_store.get_detected_zones()`, not fuzzy name matching.
  * Stacking with the existing bHapticsOSC v1 layer = **max-wins per
    dot** (same merging policy `motor_router` uses for multi-zone).
  * Per-entry **gain** (0–2× multiplier) + **threshold** (deadband
    below) so each mirror can be tuned independently.
  * Filters per entry: which OGB interaction types fire it
    (`TouchSelf`, `TouchOthers`, `PenSelf`, `PenOthers`) — mirrors the
    same checkbox set the main router exposes.

  **Implementation notes:**
  * Extend `bhaptics_router.py` with a second input layer; merge with
    the v1 OSC layer before the final frame is built (so anti-stuck
    and manual-override paths keep working unchanged).
  * Add `BHapticsSettingsManager.get_sps_mirror()` /
    `set_sps_mirror_entry()` / `delete_sps_mirror_entry()` in
    `config_manager.py`. Persist as a `sps_mirror` field on
    `bhaptics_settings.json`:
    ```json
    {
      "sps_mirror": {
        "enabled": false,
        "entries": [
          {
            "name": "Boob",
            "ogb_zone": "Boob",
            "zone_type": "Orf",
            "filters": ["TouchSelf", "TouchOthers", "PenSelf", "PenOthers"],
            "position": "VestFront",
            "dot_indices": [5, 6, 9, 10],
            "gain": 1.0,
            "threshold": 0.0
          }
        ]
      }
    }
    ```
  * New facade methods on `controllers/bhaptics_facade.py`. UI stays
    inside `_build_bhaptics_view()` (no new top-level tab).

- **Manual pattern mode.**
  A library of pre-baked vibration patterns the user can trigger
  manually (button, hotkey, OSC param) for the case where SPS isn't
  working but they still want stimulation. Should coexist with normal
  routing — pattern playback wins while active, then routing resumes.
  _Becomes much cheaper once "Audio-reactive routing" lands the
  source-aware merging into `HapticEngine` (see below)._

- **Audio-reactive Intiface routing.**
  Use the audio coming out of VRChat (game music, video player, world
  ambience) to drive toy vibration, separately from SPS contact
  routing. Lives behind its own "Audio" tab so it doesn't tangle with
  the main routing UI.

  **End-game vision:** detect the currently-playing VRCDN / video
  player URL inside the world and listen to *that specific stream*, so
  toy reactivity isn't polluted by voice chat, menu sounds, or world
  ambience. Inspiration: VRCX's log-tailing pattern.

  **Design decisions (locked):**
  * Multi-band analysis (bass / mid / treble) with configurable
    weights, attack/release smoothing, master multiplier. No
    beat/onset detection in v1 — start simple.
  * Target-backend checkboxes (Intiface, bHaptics, SteamVR) — defaults
    to Intiface-only but the architecture allows expansion.
  * Phase 3 dependency path = **zero-extra-install via Win11 process
    audio capture** (UWP-style). User does not have to install
    VB-Audio Cable or any virtual audio sink. Win11-only feature; on
    Win10 we fall back to "system loopback + voice-mic filter" (Phase
    2 alone).

  **Open architectural decision — multi-source motor merging:**
  Audio routing means a second writer to `HapticEngine.update_target()`.
  Today's engine is last-writer-wins which doesn't compose. Three
  candidates discussed:

  * **Option 1 — Per-toy exclusive assignment** ("this toy is `main`,
    that toy is `audio`"). Zero engine refactor. Each router skips
    toys not assigned to it. Simpler to reason about; can't have a toy
    respond to SPS *and* audio simultaneously.
  * **Option 2 — Source-aware max-wins** (recommended at design-time
    but not yet committed). `HapticEngine._device_targets` becomes
    `Dict[(d,m), Dict[source, (value, last_touch_ts)]]`, effective
    target = `max(v for (v,t) in <map>.values() if now - t < STALE)`.
    `update_target(device, motor, value, source="default")` adds the
    source kwarg with a default so existing callers don't change.
    Source-stale decay (~500 ms) prevents stuck values when a source
    dies. Makes future **Manual pattern mode** and **SPS priority
    layering** roadmap items almost free — they become new sources.
  * **Option 3 — Hybrid (per-toy subscribed sources + max-wins).**
    Each toy declares which sources it listens to. Most flexible, most
    UI. Over-engineered for v1.

  Pick this before writing any of the engine code below. _Pending._

  **Phased delivery:**

  **Phase 1 — Loopback engine + Audio tab.**
  * New `audio_engine.py` — sealed-box engine, owns a capture thread
    using `pyaudiowpatch` (WASAPI loopback) at ~22050 Hz mono.
    Continuously fills a ring buffer; computes RMS per band every
    ~10 ms; stores latest band levels behind a lock. Primitive-only
    public API (`start()`, `stop()`, `set_input_device(id)`,
    `snapshot() -> {bass, mid, treble, peak}`).
  * New `audio_router.py` — stateless calculator polled at
    `ROUTER_POLL_RATE_MS`. Reads `audio_engine.snapshot()`, applies
    weights/smoothing/master, computes 0–1 intensity, writes to
    `HapticEngine` via whichever merging path Option 1/2/3 lands.
  * New `controllers/audio_facade.py` — `AudioFacade` mixin composed
    into `OscGoesPurrrApp`. UI-facing methods: `get_audio_status()`,
    `set_audio_enabled()`, `set_audio_input_device()`,
    `set_audio_band_weights()`, `set_audio_smoothing()`,
    `set_audio_master_multiplier()`, `set_audio_target_toy()` /
    `set_audio_target_backend()` (signature depends on merging
    option).
  * New `AudioSettingsManager` in `config_manager.py`, persisted to
    `%APPDATA%\OscGoesPurrr\audio_settings.json`.
  * New `audio_settings.json` schema:
    ```json
    {
      "enabled": false,
      "input_device_id": null,
      "band_weights": {"bass": 0.7, "mid": 0.5, "treble": 0.3},
      "attack_ms": 30,
      "release_ms": 200,
      "master_multiplier": 1.0,
      "target_backends": {"intiface": true, "bhaptics": false, "steamvr": false},
      "target_toys": { /* shape depends on merging option */ }
    }
    ```
  * New "Audio" sidebar view in `ui_components.py`: device picker,
    band weight sliders, smoothing spinboxes, master multiplier,
    target-backend checkboxes, target-toy assignment list, live RMS
    meter for visual feedback.
  * New dependency: `pyaudiowpatch>=0.2.12` in `requirements.txt`.
  * Update `ARCHITECTURE.md`'s engine family list to include audio.

  **Phase 2 — Voice/menu filter.**
  * Tap the Windows microphone level (e.g., `pyaudiowpatch` on the
    default input device, peak detection, no transcription needed).
  * When mic peak > threshold for > N ms, pause audio routing output
    (or scale to 0) so the menu/voice sounds don't drive toys while
    the user is talking.
  * Configurable threshold + hold time on the Audio tab.
  * Cheap win that removes ~80% of "menu sounds triggered the toy"
    false positives.

  **Phase 3 — VRChat video URL isolation (Win11+).**
  * Watch `%USERPROFILE%\AppData\LocalLow\VRChat\VRChat\output_log.txt`
    for video player URL events (USharpVideo / ProTV / etc. log lines
    when a stream starts). Use a tailing reader that re-opens on log
    rotation, same pattern VRCX uses.
  * When a URL is detected, spawn a hidden sidecar (`mpv --no-video`
    or `yt-dlp -o -` piped to a silent decoder) that opens the same
    URL.
  * Use the Win11 process audio capture API (UWP / WinRT
    `AudioGraph` + `AudioPlaybackConnection`, or
    `IAudioClient3::InitializeSharedAudioStream` with a process-loopback
    activator) to capture **only** that sidecar's audio output by PID.
    Python binding: see `pywinrt` or the C++ shim approach used by
    [AudioCaptureSample][win11-pac] (link to be filled in when
    investigating). No virtual audio cable needed; nothing else for
    the user to install.
  * Switch the audio engine's input source from system loopback to the
    sidecar-PID capture whenever a stream is active. Fall back to
    Phase 2 loopback + mic filter when no stream is detected or on
    Win10.

  [win11-pac]: https://github.com/microsoft/Windows-classic-samples
    (Win11 process audio capture — fill in real link during build)

## Networking & Multiplayer

- **Remote-control contacts.**
  Allow another VRChat player to drive the local user's toys by
  touching contacts with reserved names (e.g. `OGP/Remote/*`). Needs an
  allow-list so randoms can't grief, plus a kill-switch.

## VRChat Integration

- **Profile switching from the VRChat Expressions menu.**
  Map an integer avatar parameter (e.g. `/avatar/parameters/PurrProfile`)
  to profile slots so the active profile can be changed in-game without
  alt-tabbing. Configurable parameter name; out-of-range values ignored.
- **SPS priority layering.**
  While SPS contacts are actively firing, dim or mute the regular touch
  zones so the SPS sensation isn't drowned out by background contact
  hits. Per-profile toggle with a dim-amount slider.
- **Per-input max-value clamp.**
  Per-OSC-parameter ceiling (0.0–1.0) so a single zone or contact can't
  push a motor to full output. Lets users cap noisy or overly-eager
  inputs without rewriting the whole routing.

## Reliability & Lifecycle

- **Stuck-value safety cutoff.**
  If an OSC float input stays exactly static for ~2 s (configurable),
  treat it as a stuck/frozen sender and force the corresponding motors
  to 0 until the value changes again. Prevents motors running forever
  when VRChat or an avatar param hangs. If it's at 1.0 maybe have it
  ramp down slowly because it could also mean all the way in.
  _Note:_ bHaptics and SteamVR backends already have their own
  anti-stuck handling; this item is specifically for the Buttplug
  router.
- **SteamVR-aware shutdown.**
  Detect when SteamVR exits and either auto-quit OscGoesPurrr or at
  minimum send 0 to every connected device and stop output. User
  setting to pick which behavior.

## UI Modes

- **Mini-Mode / VR companion window.**
  A compact, always-on-top layout showing only the essentials (active
  profile, vibe meters, master toggle) for use as a desktop overlay
  while in VR. Toggle from the main window; remembers its own size and
  position.

---

_Not in scope here:_ bug fixes, refactors, or anything already tracked
in commits/PRs.

_For shipped features, see [README.md](README.md) and the in-app Help
panel._
