import fnmatch
import math
import re
import time
from typing import Callable, Dict, List, Tuple, Any, Optional, Set
from utilities import normalize_osc_value, strip_param_prefix, classify_ogb_zone
from parameter_store import store as _global_store
from mixer import (
    apply_curve, combine, smooth, activity_meter, activity_gate, merge_chains,
)
from sps_source import evaluate_sps_source

_GLOB_CHARS = frozenset("*?[")


def _has_glob(addr: str) -> bool:
    return any(c in _GLOB_CHARS for c in addr)


# Module-level aliases so existing call sites and tests keep importing
# `_clean_custom_addr` / `_classify_zone_path`. The real implementations
# live in utilities.py.
_clean_custom_addr = strip_param_prefix
_classify_zone_path = classify_ogb_zone


class GameDeviceLengthDetector:
    """Calibrates the in-world length of a penetrator from successive readings of its
    root and tip proximity sensors (`Pen*NewRoot` / `Pen*NewTip`).

    Mirrors the OscGoesBrrr `GameDeviceLengthDetector` (src/main/GameDevice.ts).
    The length is the largest reliable `tipProx - rootProx` we observed while the
    penetrator was within the receiver's radius but not yet bottomed out, with a
    small recent-sample window and a "closest-pair" median to reject mismeasurements
    caused by OSC delivering the two values at different times.
    """

    MAX_SAMPLES = 8

    def __init__(self) -> None:
        self.length: Optional[float] = None
        self.recent_samples: List[float] = []
        self.bad_penetrating_sample: Optional[float] = None

    def update(self, root_prox: Any, tip_prox: Any) -> None:
        try:
            root = float(root_prox)
            tip = float(tip_prox)
        except (TypeError, ValueError):
            # Missing data
            self.bad_penetrating_sample = None
            self._save_sample(None)
            return

        if root < 0.01 or tip < 0.01:
            # Nobody in radius — clear recorded length
            self.bad_penetrating_sample = None
            self._save_sample(None)
            return

        if root > 0.95:
            # Nearly impossible (root would have to be at the center of the orifice).
            # Keep whatever length we previously recorded.
            return

        # Receiver sphere is 1m, so this is the length of the exposed penetrator in meters.
        length = tip - root
        if length < 0.02:
            # Too short / inverted — keep previous length
            return

        if tip > 0.99:
            # Tip is fully inside the orifice. Only use this as a length sample if
            # we don't have anything better — the actual length might be longer.
            if self.bad_penetrating_sample is None or length > self.bad_penetrating_sample:
                self.bad_penetrating_sample = length
                self._update_length_from_samples()
        else:
            self._save_sample(length)

    def _save_sample(self, sample: Optional[float]) -> None:
        if sample is None:
            self.recent_samples.clear()
        else:
            self.recent_samples.insert(0, sample)
            if len(self.recent_samples) > self.MAX_SAMPLES:
                self.recent_samples = self.recent_samples[: self.MAX_SAMPLES]
        self._update_length_from_samples()

    def _update_length_from_samples(self) -> None:
        if len(self.recent_samples) < 4:
            self.length = self.bad_penetrating_sample
            return

        # Find the two samples closest to each other; one of them is the winner.
        # Stray samples come from receiving only root OR tip in a tick.
        sorted_samples = sorted(self.recent_samples)
        smallest_diff = 1.0
        winner_idx = -1
        for i in range(1, len(sorted_samples)):
            diff = abs(sorted_samples[i] - sorted_samples[i - 1])
            if diff < smallest_diff:
                smallest_diff = diff
                winner_idx = i
        if winner_idx >= 0:
            self.length = sorted_samples[winner_idx]
        else:
            self.length = self.recent_samples[0]

    def get_length(self) -> Optional[float]:
        return self.length


class MotorRouter:
    """Stateless routing engine that translates the user's profile + the VRChat
    Shadow State (parameter cache) into motor target values.

    The calculation now mirrors OscGoesBrrr's `BridgeOutput.getRelevantSources` and
    `GameDevice.getSources` logic so that for OGB orifices, motor strength tracks
    actual insertion depth rather than the raw proximity, which jumps to 1.0 the
    moment the penetrator tip enters the receiver radius.
    """

    # Internal scale applied to the raw (|Δposition|/dt) speed signal
    # before clamping. Realistic in-VRChat thrusts oscillate over a
    # fraction of the full insertion range, so this value is tuned so
    # a moderate stroke saturates.
    _SPEED_NORMALIZATION = 0.75

    # Speed-detector constants. Previously per-motor knobs; baked here
    # because the activity gate (a per-motor knob) covers the user-
    # facing "ignore micro-movement" problem these used to address.
    # See docs/MOTOR_SIGNAL_CHAIN.md § "Speed-detector constants".
    # The decay tau is the exception: it sets how long the speed
    # channel keeps ringing after movement stops, which users *do*
    # need to tune per chain (a long tail reads as "the toy keeps
    # going after I stopped"). `speed.decay_ms` in the chain config
    # overrides it; this constant is only the fallback default.
    _SPEED_INPUT_DEADBAND = 0.005
    _SPEED_OUTPUT_CUTOFF = 0.02
    _SPEED_DECAY_TAU_S = 0.30
    # Clamp bounds for the per-chain `speed.decay_ms` knob. The floor
    # keeps the detector usable: OSC position updates arrive in bursts,
    # so a near-zero decay would zero the channel between packets and
    # turn steady stroking into flicker.
    _SPEED_DECAY_MS_MIN = 10.0
    _SPEED_DECAY_MS_MAX = 2000.0

    # --- Anti-stuck safety cutoff (per resolved input) -----------------
    # VRChat OSC only fires on parameter change, so a frozen SPS proximity
    # (avatar swap, partner leaves, OSC routing loss) would otherwise drive
    # a motor at its last value forever. Two-timer model, parity with the
    # SteamVR backend (steamvr_engine._clear_stuck): a mid-range value stuck
    # for the active timeout is almost always a dropped stream and is cut
    # hard; a saturated (~100%) value gets a longer fuse then a gentle ramp,
    # since "all the way in and held" is a legitimate state we don't want to
    # kill abruptly. Detection is on the motor's combined d_raw; the cut is
    # applied as a multiplier on the FINAL output so the speed detector and
    # smoothing envelope are never perturbed — forcing d_raw->0 would spoof
    # a |Δ|/dt motion spike straight through the speed channel and could
    # make a stuck motor pulse *harder*. Timeouts come from app settings
    # (Device Routing → Anti-stuck card); these are only the hardcoded
    # detection thresholds.
    _ANTISTUCK_EPSILON = 0.001     # |Δd_raw| at or below this == "unchanged"
    _ANTISTUCK_SATURATED = 0.95    # d_raw at/above this is treated as peaked
    _ANTISTUCK_RAMP_S = 3.0        # saturated ramp-down duration after the fuse

    # Simple Mode anti-stuck: the stripped-down mode has no per-motor tuning,
    # so its cutoff is a single, non-adjustable flat timeout applied to the
    # one global SPS-max value — a value frozen this long is treated as a
    # dropped stream and forced to 0. No saturated-ramp distinction; Simple
    # Mode trades the full path's nuance for zero knobs.
    _SIMPLE_ANTISTUCK_S = 2.0

    # Cap on chains per motor (per the design lock in
    # docs/MOTOR_SIGNAL_CHAIN.md § "Future: optional secondary chain").
    # Profiles with more than this are silently truncated by the
    # router — UI also enforces the cap. Raising this is a design
    # decision, not a constant tweak.
    _MAX_CHAINS_PER_MOTOR = 2

    # Default per-motor mix config — used when a profile is missing
    # the `mix` block entirely (defensive fallback; the seeder writes
    # this on every known motor at profile creation).
    #
    # Ships from Cut 1 as a list of chains, always length 1 in cuts
    # 1–4, so Cut 5 (optional secondary chain) is purely additive
    # with no schema migration. See docs/MOTOR_SIGNAL_CHAIN.md § Storage
    # and § "Future: optional secondary chain".
    DEFAULT_MIX_CONFIG: Dict[str, Any] = {
        "chains": [
            {
                "depth": {"gain": 1.0, "curve": "linear", "curve_param": 1.0},
                "speed": {"gain": 1.0, "curve": "linear", "curve_param": 1.0,
                          "decay_ms": 300.0},
                # Punch — third parallel source next to Depth and Speed: an
                # attack-transient detector that spikes on a fast RISE in
                # depth (a sharp thrust in) and decays quickly, adding a
                # crisp hit on top of the sustained level. gain 0 = off.
                "punch": {"gain": 0.0, "decay_ms": 120.0},
                "combine": "max",
                # Wake — the activity gate: nothing plays until real
                # contact is detected, two interchangeable ways (one runs
                # at a time, chosen by `mode`):
                #   "activity" — an analog activity meter; wakes on
                #     sustained movement above `wake_threshold`, sleeps
                #     `sleep_delay_s` after it stops (attack/release taus
                #     shape how fast the meter fills / drains).
                #   "strokes" — a discrete stroke counter (the sleep
                #     gate); stays silent until `thrusts` full in-out
                #     strokes land within `window_s`, stays awake while
                #     they keep coming, disarms after `disarm_after_s`
                #     quiet. Accidental brushes can't wake it.
                "wake": {
                    "enabled": False,
                    "mode": "activity",
                    "wake_threshold": 0.05,
                    "sleep_delay_s": 0.5,
                    "attack_s": 0.05,
                    "release_s": 0.5,
                    "thrusts": 3,
                    "window_s": 6.0,
                    "disarm_after_s": 45.0,
                },
                "smoothing": {"rise_ms": 50.0, "fall_ms": 20.0},
                # Texture — post-smoothing wobble so a held level has grain
                # instead of sitting flat. Downward-only modulation (never
                # exceeds the smoothed level); rate can follow the speed
                # signal so faster motion means faster grain.
                "texture": {"enabled": False, "amount": 0.25,
                            "rate_hz": 2.0, "follow_speed": False},
                # Zero cut — the chain's final stage. When the chain's raw
                # input sits at/below `threshold` (plug removed → contact
                # proximity 0), the output snaps to 0 instantly instead of
                # riding the smoothing fall tail / speed-ring decay down.
                "zerocut": {"enabled": False, "threshold": 0.0},
            },
        ],
        # Only meaningful when len(chains) > 1; harmless otherwise.
        "merge": "max",
    }

    # --- Punch tuning -------------------------------------------------
    # A depth rise of this many full-ranges per second counts as a
    # full-strength hit (a firm thrust covers the full range in ~0.3 s).
    _PUNCH_FULL_RATE_PER_S = 3.0
    # Rises slower than this are ignored entirely — OSC float jitter and
    # slow repositioning must not tick the punch envelope.
    _PUNCH_MIN_RATE_PER_S = 0.35
    _PUNCH_DECAY_MS_MIN = 30.0
    _PUNCH_DECAY_MS_MAX = 1000.0

    # --- Arming (thrust detector) tuning --------------------------------
    # A depth swing must cover at least this much of the full range for
    # its reversal to count as one thrust — OSC jitter and shallow
    # accidental brushes never tick the counter.
    _THRUST_MIN_SWING = 0.15
    # Bookkeeping cap on remembered thrust timestamps (well above any
    # realistic `thrusts` requirement).
    _THRUST_TIMES_CAP = 32

    # --- Texture tuning -----------------------------------------------
    # Rate window: below ~0.2 Hz the wobble reads as drift, above ~8 Hz
    # it exceeds what the per-feature hardware send caps can express.
    _TEXTURE_RATE_HZ_MIN = 0.2
    _TEXTURE_RATE_HZ_MAX = 8.0
    # Amount is capped below 1.0 so the modulation trough can never park
    # the output at exactly zero — needs_settling() keys on output > 0,
    # and a zero-parked motor would stop ticking with the LFO frozen.
    _TEXTURE_AMOUNT_MAX = 0.9
    # Phase where sin == -1: the wobble applies zero attenuation there,
    # so activations start at full level (see the chain loop).
    _TEXTURE_PHASE_TOP = 1.5 * math.pi

    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        # `clock` is dependency-injected so tests can drive time deterministically.
        # Defaults to time.monotonic so production callers don't change.
        self._clock = clock
        # Tracks last calculated outputs to prevent flooding the UI/hardware thread.
        self.last_outputs: Dict[tuple, float] = {}
        # Always-on CONTACT-level thrust counter for the usage
        # statistics: one physical stroke = one count, however many
        # stored toys/motors ride it. The swing detector runs once per
        # routing pass on the max depth across all computed motors (see
        # reevaluate_state / reevaluate_simple_mode); drained via
        # consume_thrusts(). Plain int — see that method for threading.
        self.thrust_count: int = 0
        self._global_thrust_state: Dict[str, Any] = {}
        self._tick_max_draw: float = 0.0
        # Per-motor mixer state, keyed by (device_name, motor_idx). Each
        # value is a dict with `last_time`, `last_position`,
        # `smoothed_speed` (speed-derivation pipeline state) and
        # `smoothed_output` (post-mix envelope follower state). Lazily
        # created on first tick for any motor.
        self._motor_state: Dict[Tuple[str, int], Dict[str, float]] = {}
        # Per-(device, motor, chain) intermediates subscriber map
        # (Cut 6). Each chain widget registers its own callback so its
        # per-stage mini-graph can render that specific chain's traces
        # without piggybacking on the legacy Tune subscription. Zero
        # cost when nothing has subscribed — the per-tick emit walks
        # `chain_emits` and only fires callbacks for keys present in
        # this dict. Multiple subscribers per key are allowed (e.g.
        # chain widget + the wrapper's overview graph both watching
        # the same chain).
        self._intermediates_subscribers: Dict[
            Tuple[str, int, int],
            List[Callable[[Dict[str, Any]], None]],
        ] = {}
        # Session-logger broadcast hook. When set, fires once per motor
        # per tick (unlike the Tune subscription which is per-motor).
        # The session facade registers a callback while a session is
        # recording and clears it on stop, so the per-tick check is a
        # single `is not None` when nothing is listening.
        self._session_broadcast: Optional[
            Callable[[str, int, Dict[str, Any]], None]
        ] = None
        # Per-(device, motor, chain) input overrides (Cut 7). Each
        # entry is a callable returning either a simulated d_raw in
        # [0, 1] or None (fall through to live d_raw). The wrapper's
        # parametric simulator registers one entry per chain in its
        # Drive mask; per-chain providers take precedence over the
        # legacy `_tune_value_provider` so the new simulator can
        # coexist cleanly with the soon-to-die preset player.
        self._chain_value_providers: Dict[
            Tuple[str, int, int], Callable[[], Optional[float]],
        ] = {}

        # Per-motor "do not forward to engine" suppression set (Cut 7).
        # The wrapper toggles entries when the simulator's Send-to-toy
        # safety switch is off. Read by the controller's
        # update_device_target via `should_send_to_toy`.
        self._toy_output_suppressed: Set[Tuple[str, int]] = set()
        # Per-zone length detectors keyed by ("Orf"|"Pen", zone_name, "self"|"others").
        self._length_detectors: Dict[Tuple[str, str, str], GameDeviceLengthDetector] = {}
        # Compiled per-motor config cache.
        #   key: (id(profile_dict), device_name, motor_idx, profile_token)
        #   val: pre-parsed addresses/zone names so the per-tick hot path doesn't
        #        re-split strings or re-walk the raw config dict for every motor.
        # `profile_token` is an opaque marker (currently a snapshot of the keys
        # we actually read) so a profile mutation safely invalidates the cache.
        self._compiled_cfg: Dict[Tuple[int, str, int, tuple], Dict[str, Any]] = {}
        # Simple Mode anti-stuck state — Simple Mode pushes one global SPS-max
        # to every motor, so it needs only a single last-value / since-changed
        # pair, not the per-motor bookkeeping the full path keeps.
        self._simple_as_last_val: Optional[float] = None
        self._simple_as_since: float = -1.0

    # ------------------------------------------------------------------ helpers
    def _get_param(self, all_params: Dict[str, Any], path: str) -> Optional[float]:
        v = all_params.get(path)
        if v is None:
            return None
        try:
            return float(v)
        except (TypeError, ValueError):
            return None

    def _get_bool(self, all_params: Dict[str, Any], path: str) -> bool:
        v = all_params.get(path)
        if v is None:
            return False
        if isinstance(v, bool):
            return v
        try:
            return float(v) > 0.5
        except (TypeError, ValueError):
            return bool(v)

    def _get_length_detector(self, zone_type: str, zone_name: str, kind: str) -> GameDeviceLengthDetector:
        key = (zone_type, zone_name, kind)
        det = self._length_detectors.get(key)
        if det is None:
            det = GameDeviceLengthDetector()
            self._length_detectors[key] = det
        return det

    def _get_zone_tuples(self, all_params: Dict[str, Any],
                         zones_override: Optional[Set[Tuple[str, str]]] = None
                         ) -> Set[Tuple[str, str]]:
        """Return the set of (zone_type, zone_name) tuples present in the params.

        Prefers the precomputed set the caller passed in (from
        `parameter_store.snapshot()`), falling back to the global store, and
        finally to a direct scan of `all_params` when running standalone (tests).
        """
        if zones_override is not None:
            return zones_override
        try:
            return _global_store.get_zone_tuples()
        except Exception:
            pass
        # Test/standalone path — derive on the fly.
        out: Set[Tuple[str, str]] = set()
        for path in all_params.keys():
            zone = _classify_zone_path(path)
            if zone is not None:
                out.add(zone)
        return out

    def _update_length_detectors(self, all_params: Dict[str, Any],
                                 zones: Set[Tuple[str, str]]) -> None:
        """Refresh per-zone length calibrations from the live OSC parameters.

        Done once per re-evaluation regardless of the user's filter flags so the
        calibration stays accurate even while penetration is disabled.
        """
        for zone_type, zone_name in zones:
            # Only orifices actually receive new-pen proximity readings.
            if zone_type != "Orf":
                continue
            prefix = f"OGB/{zone_type}/{zone_name}"
            for kind, label in (("self", "Self"), ("others", "Others")):
                root = self._get_param(all_params, f"{prefix}/Pen{label}NewRoot")
                tip = self._get_param(all_params, f"{prefix}/Pen{label}NewTip")
                if root is None and tip is None:
                    continue
                det = self._get_length_detector(zone_type, zone_name, kind)
                det.update(root, tip)

    def _get_new_pen_amount(
        self,
        zone_type: str,
        zone_name: str,
        is_self: bool,
        all_params: Dict[str, Any],
    ) -> Optional[float]:
        """Return the OGB new-style insertion depth in [0,1], or None if the new-style
        proximity sensors aren't being driven by an avatar nearby.

        Mirrors `GameDevice.getNewPenAmount` from OscGoesBrrr.
        """
        label = "Self" if is_self else "Others"
        prefix = f"OGB/{zone_type}/{zone_name}"
        root = self._get_param(all_params, f"{prefix}/Pen{label}NewRoot")
        tip = self._get_param(all_params, f"{prefix}/Pen{label}NewTip")
        if root is None or tip is None:
            return None

        # No new-style penetrator is near; let the caller fall back to legacy.
        if root <= 0 and tip <= 0:
            return None

        # A new-style penetrator IS nearby — never fall back to legacy after this,
        # even if we can't yet compute a depth (return 0 instead of None).
        det = self._get_length_detector(zone_type, zone_name, "self" if is_self else "others")
        length = det.get_length()
        if length and tip > 0.99:
            exposed_length = 1.0 - root
            exposed_ratio = exposed_length / length
            return max(0.0, min(1.0, 1.0 - exposed_ratio))
        return 0.0

    # ----------------------------------------------------------- contributions
    def _zone_contribution(
        self,
        zone_type: str,
        zone_name: str,
        config: Dict[str, Any],
        motor_idx: int,
        all_params: Dict[str, Any],
    ) -> float:
        """Compute the haptic contribution from a single OGB zone, honouring the
        same `*Close` proximity gates and new-pen depth model as OscGoesBrrr.
        """
        allow_touch = config.get(f"motor_{motor_idx}_touch", True)
        allow_pen = config.get(f"motor_{motor_idx}_pen", True)
        allow_self = config.get(f"motor_{motor_idx}_self", False)
        allow_others = config.get(f"motor_{motor_idx}_others", True)

        prefix = f"OGB/{zone_type}/{zone_name}"
        contributions: List[float] = []

        # --- Touch zones (VRCFury touch zones — Self/Others proximity) ---------
        # Two proximity floats, no Close gates, no penetration semantics.
        # OGB parity: touch zones respond to the hands toggles only
        # (GameDevice maps ownHands→Self, otherHands→Others), so the pen
        # filter never contributes here. Both wire forms are read; max wins.
        if zone_type == "Touch":
            for p in (prefix, f"VFH/Zone/Touch/{zone_name}"):
                if allow_touch and allow_self:
                    v = self._get_param(all_params, f"{p}/Self")
                    if v is not None:
                        contributions.append(v)
                if allow_touch and allow_others:
                    v = self._get_param(all_params, f"{p}/Others")
                    if v is not None:
                        contributions.append(v)
            if not contributions:
                return 0.0
            return max(normalize_osc_value(v) for v in contributions)

        # --- Touch (gated by TouchSelfClose / TouchOthersClose) ----------------
        if allow_touch and allow_self:
            if self._get_bool(all_params, f"{prefix}/TouchSelfClose"):
                v = self._get_param(all_params, f"{prefix}/TouchSelf")
                if v is not None:
                    contributions.append(v)
        if allow_touch and allow_others:
            if self._get_bool(all_params, f"{prefix}/TouchOthersClose"):
                v = self._get_param(all_params, f"{prefix}/TouchOthers")
                if v is not None:
                    contributions.append(v)

        # --- Penetration (depth-aware for orifices, raw for plugs) -------------
        if zone_type == "Orf":
            # Socket: PenSelf — prefer new-pen depth, fall back to legacy PenSelf.
            if allow_pen and allow_self:
                new_amt = self._get_new_pen_amount(zone_type, zone_name, True, all_params)
                if new_amt is not None:
                    contributions.append(new_amt)
                else:
                    legacy = self._get_param(all_params, f"{prefix}/PenSelf")
                    if legacy is None:
                        legacy = self._get_param(all_params, f"{prefix}/PenetratingSelf")
                    if legacy is not None:
                        contributions.append(legacy)

            # Socket: PenOthers — prefer new-pen depth; legacy is gated by
            # PenOthersClose (default true when the param is absent).
            if allow_pen and allow_others:
                new_amt = self._get_new_pen_amount(zone_type, zone_name, False, all_params)
                if new_amt is not None:
                    contributions.append(new_amt)
                else:
                    close_path = f"{prefix}/PenOthersClose"
                    legacy_ok = (close_path not in all_params) or self._get_bool(all_params, close_path)
                    if legacy_ok:
                        legacy = self._get_param(all_params, f"{prefix}/PenOthers")
                        if legacy is None:
                            legacy = self._get_param(all_params, f"{prefix}/PenetratingOthers")
                        if legacy is not None:
                            contributions.append(legacy)

            # Socket: FrotOthers (raw, no close-gate for the orifice side).
            if allow_pen and allow_others:
                v = self._get_param(all_params, f"{prefix}/FrotOthers")
                if v is not None:
                    contributions.append(v)

        elif zone_type == "Pen":
            # Plug side: legacy raw values; new-pen depth is the orifice's job.
            if allow_pen and allow_self:
                v = self._get_param(all_params, f"{prefix}/PenSelf")
                if v is None:
                    v = self._get_param(all_params, f"{prefix}/PenetratingSelf")
                if v is not None:
                    contributions.append(v)
            if allow_pen and allow_others:
                v = self._get_param(all_params, f"{prefix}/PenOthers")
                if v is None:
                    v = self._get_param(all_params, f"{prefix}/PenetratingOthers")
                if v is not None:
                    contributions.append(v)
            # Plug: FrotOthers gated by FrotOthersClose.
            if allow_pen and allow_others:
                if self._get_bool(all_params, f"{prefix}/FrotOthersClose"):
                    v = self._get_param(all_params, f"{prefix}/FrotOthers")
                    if v is not None:
                        contributions.append(v)

        if not contributions:
            return 0.0
        return max(normalize_osc_value(v) for v in contributions)

    def _compile_motor_config(
        self,
        profile_dict: Dict[str, Any],
        device_name: str,
        motor_idx: int,
        config: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Pre-parse the per-motor config (custom address list split into
        literal vs glob buckets, allowed-zone names parsed out of the comma
        string) so the per-tick hot path doesn't redo this work for every
        connected motor.

        Cache key includes a `profile_token` built from the small set of
        fields we actually read, so an in-place edit to the profile dict
        (e.g. the user toggling a checkbox) safely invalidates the entry.
        """
        addr_zone_key = f"motor_{motor_idx}_zones"
        osc_addresses = config.get("osc_addresses", {})
        raw_entry = osc_addresses.get(str(motor_idx))
        zones_str = config.get(addr_zone_key, "")

        # Cheap fingerprint of the inputs that drive the compiled value.
        token = (
            id(osc_addresses) if isinstance(osc_addresses, dict) else None,
            len(raw_entry) if isinstance(raw_entry, (list, str)) else 0,
            raw_entry if isinstance(raw_entry, str) else (
                tuple(raw_entry) if isinstance(raw_entry, list) else ()
            ),
            zones_str,
        )
        cache_key = (id(profile_dict), device_name, motor_idx, token)
        cached = self._compiled_cfg.get(cache_key)
        if cached is not None:
            return cached

        if isinstance(raw_entry, str):
            custom_list = [raw_entry]
        elif isinstance(raw_entry, list):
            custom_list = raw_entry
        else:
            custom_list = []

        literals: List[str] = []
        globs: List[str] = []
        for custom_addr in custom_list:
            if not isinstance(custom_addr, str):
                continue
            cleaned = _clean_custom_addr(custom_addr.strip())
            if not cleaned:
                continue
            (globs if _has_glob(cleaned) else literals).append(cleaned)

        if isinstance(zones_str, str):
            allowed_zones = [
                z.strip() for z in zones_str.split(",")
                if z.strip() and z.strip() != "None"
            ]
        else:
            allowed_zones = []
        allowed_zone_set = set(allowed_zones)

        # Precompile the glob bucket into ONE alternation regex. The hot
        # loop used to call fnmatch.fnmatch per pattern per parameter per
        # tick (~1 µs each — with a 1000-param avatar and two globs that's
        # ~1.7 ms/tick on the dispatch thread); a single C-level match()
        # is an order of magnitude cheaper. IGNORECASE reproduces
        # fnmatch's Windows normcase behavior.
        glob_re = None
        if globs:
            try:
                glob_re = re.compile(
                    "|".join(fnmatch.translate(g) for g in globs),
                    re.IGNORECASE,
                )
            except re.error:
                glob_re = None  # pathological pattern: fall back to fnmatch

        compiled = {
            "literals": literals,
            "globs": globs,
            "glob_re": glob_re,
            "allowed_zones": allowed_zone_set,
            "is_all_sps": "All SPS" in allowed_zone_set,
            "has_zone_filter": bool(allowed_zone_set),
        }
        # Bound the cache so a long-running session with lots of profile
        # edits doesn't grow it forever. 256 entries covers a worst-case
        # of dozens of motors across several profiles.
        if len(self._compiled_cfg) > 256:
            self._compiled_cfg.clear()
        self._compiled_cfg[cache_key] = compiled
        return compiled

    @staticmethod
    def _make_chain_state() -> Dict[str, Any]:
        """Fresh per-chain state record. Each chain owns its own
        speed-detector history (`last_position`, `smoothed_speed`)
        because the simulator can drive different chains with
        different `d_raw` streams on the same tick — sharing speed
        state would couple them spuriously. See
        docs/CHAIN_INLINED_TUNING.md § "Per-chain speed state"."""
        return {
            "last_position":   0.0,
            "smoothed_speed":  0.0,
            "smoothed_output": 0.0,
            "activity_meter":  0.0,
            "gate_open":       False,
            "below_since":     None,
        }

    def _get_motor_state(self, key: Tuple[str, int]) -> Dict[str, Any]:
        """Return the lazily-initialised per-motor state dict.

        Motor-level state (shared across chains):
        * `last_time` (sentinel -1.0 = no prior tick) — dt is
          identical for both chains, so the timestamp is shared.

        Per-chain state lives in `state["chains"]`, a list of dicts
        with the per-chain speed detector (`last_position`,
        `smoothed_speed`), smoothing envelope (`smoothed_output`),
        and activity-gate state (`activity_meter`, `gate_open`,
        `below_since`). The list grows lazily via
        `_ensure_chain_state` when a motor's profile gains a second
        chain."""
        state = self._motor_state.get(key)
        if state is None:
            state = {
                "last_time": -1.0,
                "chains": [self._make_chain_state()],
                # Anti-stuck bookkeeping (motor-level — the cutoff acts on the
                # combined d_raw, not per chain). `as_last_draw` is the last
                # input value seen; `as_static_since` is the monotonic time it
                # last changed. The ramp is a pure function of elapsed time so
                # it needs no stored accumulator.
                "as_last_draw": None,
                "as_static_since": -1.0,
            }
            self._motor_state[key] = state
        return state

    def _ensure_chain_state(self, state: Dict[str, Any], n: int) -> None:
        """Grow `state["chains"]` to at least `n` entries with fresh
        defaults. Called once per tick before iterating the chains so
        a profile that just gained a second chain doesn't crash on
        first read."""
        chains = state.get("chains")
        if not isinstance(chains, list):
            chains = [self._make_chain_state()]
            state["chains"] = chains
        while len(chains) < n:
            chains.append(self._make_chain_state())

    def _get_mix_config(self, config: Dict[str, Any],
                        motor_idx: int) -> Dict[str, Any]:
        """Pull the per-motor `mix` block out of the device config, falling
        back to DEFAULT_MIX_CONFIG when keys are missing. The seeder writes
        a full block on every motor at profile creation, so on a clean
        install this returns the stored dict verbatim; the fallbacks
        protect against hand-edited or partially-migrated profiles."""
        mix_root = config.get("mix") if isinstance(config, dict) else None
        if isinstance(mix_root, dict):
            per_motor = mix_root.get(str(motor_idx))
        else:
            per_motor = None
        if not isinstance(per_motor, dict):
            return self.DEFAULT_MIX_CONFIG
        return per_motor

    def _derive_speed_signal(self, chain_state: Dict[str, Any],
                             position: float,
                             dt: float,
                             decay_tau_s: Optional[float] = None) -> float:
        """Compute the per-chain S_raw from |Δposition|/dt with the
        baked-in input deadband and output cutoff (see
        _SPEED_INPUT_DEADBAND / _SPEED_OUTPUT_CUTOFF). `decay_tau_s`
        is the per-chain fall-off time constant (from
        `speed.decay_ms`); None falls back to _SPEED_DECAY_TAU_S.
        Updates `chain_state["smoothed_speed"]` and
        `chain_state["last_position"]` in place. Returns the
        post-cutoff value in [0, 1] suitable for feeding into
        apply_curve.

        Rate independence: `decay_tau` is a wall-clock time constant.
        `decay = exp(-dt / decay_tau)` compensates for the elapsed
        interval, so the perceived decay envelope is identical at any
        router rate. raw_speed = (|delta| - deadband) / dt is also a
        per-second rate, directly comparable across sample rates.

        Per-chain — each chain in a multi-chain motor maintains its
        own speed history because the simulator's Drive mask can feed
        different `d_raw` streams to different chains on the same
        tick (docs/CHAIN_INLINED_TUNING.md § "Per-chain speed state")."""
        last_pos = chain_state["last_position"]
        prev_smoothed = chain_state["smoothed_speed"]

        deadband = self._SPEED_INPUT_DEADBAND
        decay_tau = (self._SPEED_DECAY_TAU_S if decay_tau_s is None
                     else max(self._SPEED_DECAY_MS_MIN / 1000.0,
                              float(decay_tau_s)))
        cutoff = self._SPEED_OUTPUT_CUTOFF

        if dt <= 0.0:
            # First sample or clock didn't move — reuse last smoothed value.
            smoothed = prev_smoothed
        else:
            delta = abs(position - last_pos)
            if delta <= deadband:
                raw_speed = 0.0
            else:
                raw_speed = (delta - deadband) / dt
            signal = min(1.0, raw_speed * self._SPEED_NORMALIZATION)
            decay = math.exp(-dt / decay_tau)
            smoothed = max(signal, prev_smoothed * decay)

        chain_state["smoothed_speed"] = smoothed
        chain_state["last_position"] = position

        if smoothed <= cutoff:
            return 0.0
        denom = max(1.0 - cutoff, 1e-6)
        return min(1.0, (smoothed - cutoff) / denom)

    def _derive_punch_signal(self, chain_state: Dict[str, Any],
                             position: float,
                             dt: float,
                             decay_tau_s: float) -> float:
        """Attack-transient detector: the normalized RISE rate of depth
        strikes an impulse envelope that decays with `decay_tau_s`. Only
        rising edges count (pull-out is not a punch), and rises slower
        than _PUNCH_MIN_RATE_PER_S are ignored so OSC float jitter and
        slow repositioning never tick the envelope.

        Keeps its own `punch_last_d` memory — the speed detector's
        `last_position` is already advanced by the time punch runs, and
        speed measures |Δ| while punch needs the signed rise.

        Rate independence: rise/dt is a per-second rate and the decay is
        a wall-clock exp, so a thrust reads identically at any router
        poll rate. Returns the envelope in [0, 1] — the caller applies
        the chain's punch gain."""
        last_d = chain_state.get("punch_last_d", -1.0)
        env = float(chain_state.get("punch_env", 0.0))
        if dt > 0.0:
            env *= math.exp(-dt / max(1e-3, decay_tau_s))
            if last_d >= 0.0:
                rate = (position - last_d) / dt
                if rate >= self._PUNCH_MIN_RATE_PER_S:
                    strike = min(1.0, rate / self._PUNCH_FULL_RATE_PER_S)
                    if strike > env:
                        env = strike
        chain_state["punch_last_d"] = position
        chain_state["punch_env"] = env
        return env

    def _detect_thrust(self, chain_state: Dict[str, Any],
                       d_raw: float) -> bool:
        """Swing detector: returns True exactly once per completed
        in-stroke — when the depth signal reverses downward after a rise
        that covered at least _THRUST_MIN_SWING. Hysteresis is inherent:
        jitter smaller than the swing floor never flips the tracked
        direction, and the bottom turn (pull-out ending) never counts, so
        one full in-out cycle is exactly one thrust.

        Also the data source for the statistics thrust counter, which
        runs it against the MOTOR-level state dict — keep it pure
        state-dict math with no side channels so both callers stay
        independent."""
        ext = chain_state.get("thrust_ext")
        if ext is None:
            chain_state["thrust_ext"] = d_raw
            chain_state["thrust_base"] = d_raw
            chain_state["thrust_dir"] = 0
            return False
        direction = chain_state.get("thrust_dir", 0)
        base = chain_state.get("thrust_base", ext)
        if direction >= 0:
            if d_raw >= ext:
                chain_state["thrust_ext"] = d_raw
                if direction == 0 and d_raw - base >= self._THRUST_MIN_SWING:
                    chain_state["thrust_dir"] = 1
                return False
            if ext - d_raw >= self._THRUST_MIN_SWING:
                # Reversal down. Counts only if we were genuinely rising
                # and the rise itself covered a full swing.
                counted = (direction == 1
                           and ext - base >= self._THRUST_MIN_SWING)
                chain_state["thrust_dir"] = -1
                chain_state["thrust_base"] = ext
                chain_state["thrust_ext"] = d_raw
                return counted
            return False
        # direction == -1: riding a fall.
        if d_raw <= ext:
            chain_state["thrust_ext"] = d_raw
            return False
        if d_raw - ext >= self._THRUST_MIN_SWING:
            chain_state["thrust_dir"] = 1
            chain_state["thrust_base"] = ext
            chain_state["thrust_ext"] = d_raw
        return False

    @staticmethod
    def _wake_cfg(chain: Dict[str, Any]) -> Dict[str, Any]:
        """The chain's effective Wake config. Prefers the merged `wake`
        block; upgrades a legacy chain (separate `gate` / `arming`) on the
        fly so files saved before the merge keep working — if arming was
        enabled it maps to strokes mode (the stronger sleep gate wins),
        otherwise the activity gate."""
        if not isinstance(chain, dict):
            return {}
        w = chain.get("wake")
        if isinstance(w, dict):
            return w
        gate = chain.get("gate")
        gate = gate if isinstance(gate, dict) else {}
        arming = chain.get("arming")
        arming = arming if isinstance(arming, dict) else {}
        if not gate and not arming:
            return {}
        strokes = bool(arming.get("enabled", False))
        return {
            "enabled": strokes or bool(gate.get("enabled", False)),
            "mode": "strokes" if strokes else "activity",
            "wake_threshold": gate.get("wake_threshold", 0.05),
            "sleep_delay_s": gate.get("sleep_delay_s", 0.5),
            "attack_s": gate.get("attack_s", 0.05),
            "release_s": gate.get("release_s", 0.5),
            "thrusts": arming.get("thrusts", 3),
            "window_s": arming.get("window_s", 6.0),
            "disarm_after_s": arming.get("disarm_after_s", 45.0),
        }

    def _wake_activity(self, chain_state: Dict[str, Any], s_raw: float,
                       mixed: float, dt: float, now: float,
                       cfg: Dict[str, Any]):
        """Activity-meter gate: an analog meter fills with sustained
        movement (sidechained on s_raw) and opens the gate above
        `wake_threshold`, closing `sleep_delay_s` after motion stops.
        Returns (waked, open, meter)."""
        wake_threshold = self._coerce_float(
            cfg.get("wake_threshold", 0.05), 0.05, 0.0, 1.0)
        sleep_delay_s = self._coerce_float(
            cfg.get("sleep_delay_s", 0.5), 0.5, 0.0, 60.0)
        attack_s = self._coerce_float(
            cfg.get("attack_s", 0.05), 0.05, 0.01, 10.0)
        release_s = self._coerce_float(
            cfg.get("release_s", 0.5), 0.5, 0.01, 10.0)
        new_meter = activity_meter(
            chain_state["activity_meter"], s_raw, dt, attack_s, release_s)
        chain_state["activity_meter"] = new_meter
        new_open, new_below_since = activity_gate(
            bool(chain_state["gate_open"]), chain_state["below_since"],
            new_meter, now, wake_threshold, sleep_delay_s)
        chain_state["gate_open"] = new_open
        chain_state["below_since"] = new_below_since
        return (mixed if new_open else 0.0), new_open, new_meter

    def _wake_strokes(self, chain_state: Dict[str, Any], chain_d_raw: float,
                      mixed: float, dt: float, now: float,
                      cfg: Dict[str, Any]):
        """Stroke-counter gate (the sleep gate): silent until `thrusts`
        full in-out strokes land within `window_s`, armed while they keep
        coming, disarms after `disarm_after_s` quiet. Returns (waked,
        armed, progress) where progress is 0..1 toward arming."""
        need = int(self._coerce_float(cfg.get("thrusts", 3), 3.0, 1.0, 10.0))
        window_s = self._coerce_float(cfg.get("window_s", 6.0), 6.0, 1.0, 30.0)
        disarm_after_s = self._coerce_float(
            cfg.get("disarm_after_s", 45.0), 45.0, 5.0, 600.0)
        times = chain_state.setdefault("thrust_times", [])
        # Ticks stop entirely while every output is 0 (silent VRChat), so
        # this may be the first evaluation in hours: a swing's two halves
        # must not straddle a gap longer than the counting window, or a
        # pre-gap half-rise pairs with a post-gap fall into a phantom stroke.
        if dt > window_s:
            chain_state.pop("thrust_ext", None)
            chain_state.pop("thrust_base", None)
            chain_state.pop("thrust_dir", None)
        # Disarm FIRST, against the PRE-tick deadline. A stroke landing
        # after the deadline expired must count toward RE-arming (1 of N),
        # never extend the stale armed state — otherwise a single brush
        # hours later re-triggers a sleeping user's motor without the
        # required wake strokes.
        if bool(chain_state.get("armed", False)):
            prev_last_t = chain_state.get("last_thrust_t", -1.0)
            if prev_last_t < 0.0 or now - prev_last_t > disarm_after_s:
                chain_state["armed"] = False
                times.clear()
        if self._detect_thrust(chain_state, chain_d_raw):
            times.append(now)
            if len(times) > self._THRUST_TIMES_CAP:
                del times[0]
            chain_state["last_thrust_t"] = now
        while times and now - times[0] > window_s:
            times.pop(0)
        armed = bool(chain_state.get("armed", False))
        if not armed and len(times) >= need:
            armed = True
        chain_state["armed"] = armed
        progress = min(1.0, len(times) / need) if need > 0 else 0.0
        return (mixed if armed else 0.0), armed, progress

    @staticmethod
    def _wake_reset(chain_state: Dict[str, Any]) -> None:
        """Park BOTH wake algorithms at rest so a future enable (either
        mode) starts clean — a stale activity meter or a stale swing
        extremum must not leak a phantom wake on re-enable."""
        chain_state["activity_meter"] = 0.0
        chain_state["gate_open"] = False
        chain_state["below_since"] = None
        chain_state["armed"] = False
        for k in ("thrust_times", "thrust_ext", "thrust_base",
                  "thrust_dir", "last_thrust_t"):
            chain_state.pop(k, None)

    def _antistuck_factor(self, state: Dict[str, Any], d_raw: float,
                          now: float,
                          cfg: Optional[Dict[str, Any]]) -> float:
        """Return an output multiplier in [0, 1] for the per-motor anti-stuck
        cutoff, updating the motor's staleness bookkeeping in `state` in place.

        `1.0` means pass-through; a smaller value fades a frozen input toward
        0. `cfg` is the `{enabled, active_s, peaked_s}` dict threaded from app
        settings (None / disabled → always 1.0). See the `_ANTISTUCK_*`
        constants for the model rationale.

        Detection compares the raw input against the last-seen input, NOT the
        post-cutoff output — so once a stuck value is cut, it stays cut until
        VRChat actually sends a different value. The returned factor is meant
        to scale the motor's *final* output; callers must not feed a reduced
        d_raw back into the speed detector."""
        last = state.get("as_last_draw")
        if last is None or abs(d_raw - last) > self._ANTISTUCK_EPSILON:
            # Input moved (or first sample) — reset the fuse.
            state["as_last_draw"] = d_raw
            state["as_static_since"] = now

        if not cfg or not cfg.get("enabled"):
            # Hold the fuse reset while disabled so enabling the feature later
            # doesn't instantly fire on a value that was already static.
            state["as_static_since"] = now
            return 1.0

        # A value at/below the change epsilon is effectively off — nothing to
        # clear, and holding "0" forever is harmless.
        if d_raw <= self._ANTISTUCK_EPSILON:
            return 1.0

        since = state.get("as_static_since", now)
        elapsed = now - since
        if elapsed < 0.0:
            elapsed = 0.0

        if d_raw >= self._ANTISTUCK_SATURATED:
            # Saturated hold — longer fuse, then a gentle ramp rather than a
            # hard cut (it may legitimately mean "all the way in").
            peaked_s = self._coerce_float(cfg.get("peaked_s", 15.0), 15.0, 0.0, 600.0)
            if elapsed < peaked_s:
                return 1.0
            ramp = 1.0 - (elapsed - peaked_s) / self._ANTISTUCK_RAMP_S
            return max(0.0, min(1.0, ramp))

        # Mid-range hold — almost always a dropped stream; cut hard.
        active_s = self._coerce_float(cfg.get("active_s", 7.0), 7.0, 0.0, 600.0)
        return 0.0 if elapsed >= active_s else 1.0

    def _simple_antistuck(self, value: float, now: float) -> float:
        """Flat, non-adjustable anti-stuck for Simple Mode. Simple Mode emits
        one global SPS-max to every motor and exposes no tuning, so a single
        `_SIMPLE_ANTISTUCK_S`-second cutoff on that value is the whole feature:
        once the value sits unchanged that long it's treated as a frozen sender
        and forced to 0 until it moves again. Unlike the full Device Routing
        path there is no saturated-ramp distinction — a held value of any level
        dies at the flat timeout. Updates the global staleness bookkeeping in
        place; always on (Simple Mode has no enable toggle)."""
        last = self._simple_as_last_val
        if last is None or abs(value - last) > self._ANTISTUCK_EPSILON:
            # Moved (or first sample) — reset the fuse, pass through. Store the
            # true value so subsequent ticks compare against the real input,
            # not a post-cutoff 0.
            self._simple_as_last_val = value
            self._simple_as_since = now
            return value
        # Frozen. A value already at rest has nothing to clear.
        if value <= self._ANTISTUCK_EPSILON:
            return value
        if (now - self._simple_as_since) >= self._SIMPLE_ANTISTUCK_S:
            return 0.0
        return value

    def has_tune_subscription(self) -> bool:
        """True when any UI surface needs the routing tick to keep
        firing even with VRChat silent — covers per-(motor, chain)
        intermediates subscribers (Cut 6) and the parametric simulator
        (Cut 7), which needs ticks to advance its phase regardless of
        live input.

        Kept under the legacy name so main.py's tick loop doesn't
        need a rename — the broader semantics are correct."""
        return (bool(self._intermediates_subscribers)
                or bool(self._chain_value_providers))

    def needs_settling(self) -> bool:
        """True while any motor's last computed output is above zero —
        smoothing tails, gate closes, and the anti-stuck cutoff all
        need further ticks to finish settling after VRChat goes
        silent (OSC only fires on change, so there is no wake-up
        coming for a frozen input).

        This is a HARDWARE-SAFETY condition, deliberately independent
        of any UI subscription: the UI taps pause while their pages
        are hidden, but a driven motor must keep being recomputed
        until it has genuinely come to rest, no matter what page is
        on screen. Once every output sits at zero, idle ticks stop
        costing CPU again."""
        return any(v > 0.0 for v in self.last_outputs.values())

    def consume_thrusts(self) -> int:
        """Return the thrust count accumulated since the last call and
        zero it. Called at 1 Hz by the stats facade on the GUI thread —
        the same thread the routing tick increments on, and even if a
        caller ever moved off-thread these are plain int ops under the
        GIL, so the worst case is one tick's increment landing in the
        next drain instead of this one. Never blocks, never allocates."""
        n = self.thrust_count
        self.thrust_count = 0
        return n

    # ----------------------------------------------------------
    # Per-(motor, chain) intermediates subscribers (Cut 6).
    #
    # Each chain widget that wants per-stage mini-graphs registers a
    # callback against its (device, motor, chain_idx). The router
    # fires every subscriber that matches the chain being computed
    # on each tick. Multiple subscribers per key are allowed.
    # ----------------------------------------------------------

    def subscribe_intermediates(self, device_name: str, motor_idx: int,
                                chain_idx: int,
                                callback: Callable[[Dict[str, Any]], None]
                                ) -> None:
        """Register a callback to receive per-tick intermediates for
        one (device, motor, chain). Same callback registered twice
        for the same key is allowed but pointless — the dispatcher
        will fire it twice."""
        key = (str(device_name), int(motor_idx), int(chain_idx))
        self._intermediates_subscribers.setdefault(key, []).append(callback)

    def unsubscribe_intermediates(self, device_name: str, motor_idx: int,
                                  chain_idx: int,
                                  callback: Callable[[Dict[str, Any]], None]
                                  ) -> None:
        """Remove a previously-registered callback. No-op if the
        callback isn't currently registered for that key. Cleans up
        the list entry when it empties so `has_intermediates_subscribers`
        stays cheap."""
        key = (str(device_name), int(motor_idx), int(chain_idx))
        callbacks = self._intermediates_subscribers.get(key)
        if not callbacks:
            return
        try:
            callbacks.remove(callback)
        except ValueError:
            return
        if not callbacks:
            del self._intermediates_subscribers[key]

    def has_intermediates_subscribers(self) -> bool:
        """True when at least one chain widget has subscribed for its
        per-stage graph data."""
        return bool(self._intermediates_subscribers)

    def set_session_broadcast(self,
                              callback: Optional[
                                  Callable[[str, int, Dict[str, Any]], None]
                              ]) -> None:
        """Subscribe to *every* motor's intermediates per tick. Pass
        None to clear. Distinct from the Tune subscription (which is
        per-motor and gated by `_tune_subscription`).

        The callback is invoked from the routing thread inside
        `_compute_motor_target`, after the existing Tune emit. It
        receives `(device_name, motor_idx, intermediates_dict)` where
        the dict has `t_unix` (wall-clock seconds) plus d_raw, s_raw,
        d_shaped, s_shaped, mixed, out. The session facade computes
        relative t_ms from t_unix before logging.

        Exceptions raised inside the callback are swallowed so a
        misbehaving logger can never break the hot path."""
        self._session_broadcast = callback

    # ----------------------------------------------------------
    # Per-chain input overrides + toy-output suppression (Cut 7).
    # ----------------------------------------------------------

    def set_chain_value_provider(self, device_name: str, motor_idx: int,
                                 chain_idx: int,
                                 provider: Optional[
                                     Callable[[], Optional[float]]
                                 ]) -> None:
        """Register (or clear) a per-(motor, chain) `d_raw` override.
        The provider is called every tick when this motor is being
        computed; if it returns a non-None float, that value replaces
        the live `d_raw` for that chain only. Other chains on the
        same motor stay on live input.

        Pass `None` to clear the override for this chain."""
        key = (str(device_name), int(motor_idx), int(chain_idx))
        if provider is None:
            self._chain_value_providers.pop(key, None)
            return
        self._chain_value_providers[key] = provider

    def clear_chain_value_provider(self, device_name: str,
                                   motor_idx: int, chain_idx: int) -> None:
        """Convenience alias for `set_chain_value_provider(..., None)`."""
        self._chain_value_providers.pop(
            (str(device_name), int(motor_idx), int(chain_idx)), None
        )

    def has_chain_value_providers(self) -> bool:
        """True when any chain provider is registered. Used by the
        controller to keep ticking when the simulator is running
        even with VRChat silent (same role as
        `has_intermediates_subscribers`)."""
        return bool(self._chain_value_providers)

    def suppress_toy_output(self, device_name: str, motor_idx: int) -> None:
        """Mark this motor as "do not forward to engine". The wrapper's
        Send-to-toy safety toggle adds the entry while the simulator
        is running with the toggle off; the controller's
        `update_device_target` checks `should_send_to_toy` and drops
        the value. The router itself keeps computing so meters and
        traces still show the simulated signal."""
        self._toy_output_suppressed.add((str(device_name), int(motor_idx)))

    def unsuppress_toy_output(self, device_name: str, motor_idx: int) -> None:
        """Remove the suppression entry. No-op if not currently
        suppressed."""
        self._toy_output_suppressed.discard(
            (str(device_name), int(motor_idx))
        )

    def should_send_to_toy(self, device_name: str, motor_idx: int) -> bool:
        """True when the engine should receive this motor's target.
        False when the simulator has explicitly suppressed it
        (Send-to-toy off). The controller's `update_device_target`
        ANDs this with the per-toy mute check before forwarding to
        the engine."""
        return (str(device_name), int(motor_idx)) not in self._toy_output_suppressed

    @staticmethod
    def _coerce_float(value: Any, default: float,
                      lo: float = -1e9, hi: float = 1e9) -> float:
        """Defensive numeric coercion — bad values silently fall back to
        the default. Used for every mix-config field read so a malformed
        profile can't crash the router. Non-finite values take the
        default too: NaN passes both range checks unclamped, and a NaN
        threshold/gain would silently poison every comparison downstream
        (json round-trips bare NaN, so a corrupted profile can carry
        one)."""
        try:
            v = float(value)
        except (TypeError, ValueError):
            return default
        if not math.isfinite(v):
            return default
        if v < lo:
            return lo
        if v > hi:
            return hi
        return v

    def _compute_d_raw_from_inputs(
        self,
        compiled: Dict[str, Any],
        all_params: Dict[str, Any],
        config: Dict[str, Any],
        motor_idx: int,
        zones: Set[Tuple[str, str]],
        sps_sources: Optional[Dict[str, Any]] = None,
    ) -> float:
        """Max-wins combine of every input the motor listens to:
        - Literal custom OSC addresses (O(1) dict lookups)
        - Custom OSC address globs (fnmatch sweep)
        - SPS zone contributions (when the motor's zone filter is set)
        - Synthetic SPS sources (selected by name; evaluated from the
          `sps_sources` map the controller passes in each tick)
        Returns a value in [0, 1]. Pure function of its inputs — used
        by both live routing and as the fallback for the Tune view's
        input override."""
        d_raw = 0.0
        for literal in compiled["literals"]:
            param_val = all_params.get(literal)
            if param_val is None:
                continue
            # RAW value in: normalize_osc_value does its own coercion and
            # needs the original type to tell an int byte param (0-255,
            # rescaled) from a float (clamped). A float() pre-cast here
            # would defeat the rescale and saturate byte params to 1.0.
            cand = normalize_osc_value(param_val)
            if cand > d_raw:
                d_raw = cand

        if compiled["globs"]:
            glob_re = compiled.get("glob_re")
            for param_name, param_val in all_params.items():
                if glob_re is not None:
                    if glob_re.match(param_name) is None:
                        continue
                elif not any(fnmatch.fnmatch(param_name, g) for g in compiled["globs"]):
                    continue
                cand = normalize_osc_value(param_val)
                if cand > d_raw:
                    d_raw = cand

        if compiled["has_zone_filter"]:
            is_all_sps = compiled["is_all_sps"]
            allowed_zone_set = compiled["allowed_zones"]
            best = d_raw
            for zone_type, zone_name in zones:
                if is_all_sps or zone_name in allowed_zone_set:
                    contribution = self._zone_contribution(
                        zone_type, zone_name, config, motor_idx, all_params
                    )
                    if contribution > best:
                        best = contribution
            d_raw = best

        # Synthetic SPS sources — resolved by explicit name only (never
        # swept up by "All SPS"). A selected name that matches a defined
        # source contributes its evaluated value, max-wins like everything
        # else. Filter-agnostic: a synthetic source carries its own gating
        # logic, so the per-motor Touch/Pen/Self/Others flags don't apply.
        if sps_sources and compiled["allowed_zones"]:
            best = d_raw
            for name in compiled["allowed_zones"]:
                defn = sps_sources.get(name)
                if defn is None:
                    continue
                val = evaluate_sps_source(defn, all_params)
                if val > best:
                    best = val
            d_raw = best
        return d_raw

    # ------------------------------------------------------------------ public
    def _calculate_motor_target(
        self,
        device_name: str,
        motor_idx: int,
        config: Dict[str, Any],
        all_params: Dict[str, Any],
        zones: Set[Tuple[str, str]],
        profile_dict: Optional[Dict[str, Any]] = None,
        sps_sources: Optional[Dict[str, Any]] = None,
        antistuck: Optional[Dict[str, Any]] = None,
    ) -> float:
        compiled = self._compile_motor_config(
            profile_dict if profile_dict is not None else config,
            device_name, motor_idx, config,
        )

        # --- 1. live d_raw (per-chain overrides applied inside the
        # chain loop below via _chain_value_providers).
        live_d_raw = self._compute_d_raw_from_inputs(
            compiled, all_params, config, motor_idx, zones, sps_sources
        )

        # --- 2. Signal chain(s): per-channel shaping → combine → gate → smoothing ---
        # The per-motor `mix` block holds a list of chains (length 1
        # in cuts 1–4; up to 2 from Cut 5 onward) plus a `merge` op
        # that says how their outputs combine into the final motor
        # target. Each chain has independent gate + smoothing state;
        # the speed detector is shared because `|d/dt|` is a property
        # of the input.
        mix = self._get_mix_config(config, motor_idx)
        chains_cfg = mix.get("chains") if isinstance(mix, dict) else None
        if not isinstance(chains_cfg, list) or not chains_cfg:
            chains_cfg = self.DEFAULT_MIX_CONFIG["chains"]
        # Cap silently — UI also enforces the cap; this is the safety net.
        chains_cfg = chains_cfg[: self._MAX_CHAINS_PER_MOTOR]
        merge_op = str(mix.get("merge", "max")) if isinstance(mix, dict) else "max"

        state = self._get_motor_state((device_name, motor_idx))
        self._ensure_chain_state(state, len(chains_cfg))

        # Usage statistics: contribute this motor's live input to the
        # routing pass's max-depth track. The stroke detector itself
        # runs ONCE per pass on that max (see reevaluate_state) so one
        # physical stroke counts once, not once per stored toy-motor
        # riding the same contact. O(1).
        if live_d_raw > self._tick_max_draw:
            self._tick_max_draw = live_d_raw

        now = self._clock()
        last_t = state["last_time"]
        # last_time == -1.0 is the sentinel for "no prior tick"; otherwise
        # any monotonic value (including 0.0 from a FakeClock) is valid.
        dt = (now - last_t) if last_t >= 0.0 else 0.0

        # Per-chain compute. The fall-through to DEFAULT_MIX_CONFIG's
        # first chain on a malformed entry keeps a hand-edited profile
        # from crashing the router; the UI never writes non-dict chains.
        # Speed derivation also lives inside this loop now — each chain
        # owns its own speed history because the simulator can drive
        # different chains with different `d_raw` streams. In Cut 6,
        # before the parametric simulator (Cut 7) lands, both chains
        # always see the same `d_raw`, so their speed states converge.
        chain_emits: List[Dict[str, Any]] = []
        chain_outputs: List[float] = []
        for chain_idx, chain in enumerate(chains_cfg):
            if not isinstance(chain, dict):
                chain = self.DEFAULT_MIX_CONFIG["chains"][0]
            chain_state = state["chains"][chain_idx]

            # Per-chain input override (Cut 7). When the chain has no
            # provider registered, it sees the motor's live `d_raw`.
            chain_provider = self._chain_value_providers.get(
                (device_name, motor_idx, chain_idx)
            )
            chain_d_raw = live_d_raw
            if chain_provider is not None:
                try:
                    v = chain_provider()
                    if v is not None:
                        chain_d_raw = max(0.0, min(1.0, float(v)))
                except Exception:
                    pass

            depth = chain.get("depth", {}) if isinstance(chain, dict) else {}
            speed = chain.get("speed", {}) if isinstance(chain, dict) else {}

            # Per-chain speed fall-off: how long the speed channel keeps
            # ringing after movement stops. Stored in ms (UI units),
            # consumed as a tau in seconds.
            speed_decay_s = self._coerce_float(
                speed.get("decay_ms", self._SPEED_DECAY_TAU_S * 1000.0),
                self._SPEED_DECAY_TAU_S * 1000.0,
                self._SPEED_DECAY_MS_MIN, self._SPEED_DECAY_MS_MAX,
            ) / 1000.0
            s_raw = self._derive_speed_signal(
                chain_state, chain_d_raw, dt, speed_decay_s
            )

            d_shaped = apply_curve(
                chain_d_raw,
                str(depth.get("curve", "linear")),
                self._coerce_float(depth.get("curve_param", 1.0), 1.0),
            ) * self._coerce_float(depth.get("gain", 1.0), 1.0, 0.0, 2.0)
            s_shaped = apply_curve(
                s_raw,
                str(speed.get("curve", "linear")),
                self._coerce_float(speed.get("curve_param", 1.0), 1.0),
            ) * self._coerce_float(speed.get("gain", 1.0), 1.0, 0.0, 2.0)

            # Punch — third parallel source. Computed alongside depth and
            # speed, then merged max-wins AFTER the d/s combine op: an
            # impulse is an accent overlay, and folding it into "multiply"
            # would zero the whole chain between hits.
            punch_cfg = chain.get("punch", {}) if isinstance(chain, dict) else {}
            if not isinstance(punch_cfg, dict):
                punch_cfg = {}
            punch_gain = self._coerce_float(
                punch_cfg.get("gain", 0.0), 0.0, 0.0, 2.0
            )
            if punch_gain > 0.0:
                punch_decay_s = self._coerce_float(
                    punch_cfg.get("decay_ms", 120.0), 120.0,
                    self._PUNCH_DECAY_MS_MIN, self._PUNCH_DECAY_MS_MAX,
                ) / 1000.0
                punch = min(1.0, self._derive_punch_signal(
                    chain_state, chain_d_raw, dt, punch_decay_s
                ) * punch_gain)
            else:
                # Keep the memory tracking so enabling punch mid-motion
                # doesn't read the whole current depth as one giant rise.
                chain_state["punch_last_d"] = chain_d_raw
                chain_state["punch_env"] = 0.0
                punch = 0.0

            mixed = combine(d_shaped, s_shaped, str(chain.get("combine", "max")))
            if punch > mixed:
                mixed = punch

            # Wake — the activity gate. ONE stage, two interchangeable
            # algorithms (see DEFAULT_MIX_CONFIG's `wake` block): an analog
            # activity meter or a discrete stroke counter, `mode` picking
            # which. Placed BEFORE smoothing so waking attacks along the
            # chain's rise envelope and sleeping rides its fall — no hard
            # steps. Per-chain state so two chains on one motor can hold
            # different wake states.
            wake_cfg = self._wake_cfg(chain)
            wake_mode = str(wake_cfg.get("mode", "activity"))
            if not bool(wake_cfg.get("enabled", False)):
                self._wake_reset(chain_state)
                waked, wake_open_emit, wake_meter_emit = mixed, True, 0.0
            elif wake_mode == "strokes":
                waked, wake_open_emit, wake_meter_emit = self._wake_strokes(
                    chain_state, chain_d_raw, mixed, dt, now, wake_cfg)
            else:
                waked, wake_open_emit, wake_meter_emit = self._wake_activity(
                    chain_state, s_raw, mixed, dt, now, wake_cfg)

            smoothing = chain.get("smoothing", {}) if isinstance(chain, dict) else {}
            rise_ms = self._coerce_float(
                smoothing.get("rise_ms", 50.0), 50.0, 0.0, 2000.0
            )
            fall_ms = self._coerce_float(
                smoothing.get("fall_ms", 20.0), 20.0, 0.0, 2000.0
            )
            smoothed_chain = smooth(
                chain_state["smoothed_output"], waked, dt * 1000.0,
                rise_ms, fall_ms
            )

            # Texture — post-smoothing wobble so a held level has grain.
            # Downward-only: the output oscillates between the smoothed
            # level and (1 - amount) × level, never above it — texture is
            # cosmetic modulation and must not amplify. The smoothing
            # envelope state deliberately tracks the PRE-texture value so
            # the wobble never feeds back into its own envelope. While a
            # driven motor holds a level, needs_settling() keeps the tick
            # running (output stays > 0 — see _TEXTURE_AMOUNT_MAX), which
            # is what animates the LFO between OSC events.
            texture_cfg = chain.get("texture", {}) if isinstance(chain, dict) else {}
            if not isinstance(texture_cfg, dict):
                texture_cfg = {}
            textured_chain = smoothed_chain
            if bool(texture_cfg.get("enabled", False)) and smoothed_chain > 0.0:
                tx_amount = self._coerce_float(
                    texture_cfg.get("amount", 0.25), 0.25,
                    0.0, self._TEXTURE_AMOUNT_MAX,
                )
                tx_rate = self._coerce_float(
                    texture_cfg.get("rate_hz", 2.0), 2.0,
                    self._TEXTURE_RATE_HZ_MIN, self._TEXTURE_RATE_HZ_MAX,
                )
                if bool(texture_cfg.get("follow_speed", False)):
                    # Full-speed motion doubles the grain rate; the result
                    # stays inside the hardware-expressible window.
                    tx_rate = min(self._TEXTURE_RATE_HZ_MAX,
                                  tx_rate * (1.0 + max(0.0, min(1.0, s_shaped))))
                phase = (chain_state.get("texture_phase", self._TEXTURE_PHASE_TOP)
                         + math.tau * tx_rate * dt) % math.tau
                chain_state["texture_phase"] = phase
                textured_chain = smoothed_chain * (
                    1.0 - tx_amount * 0.5 * (1.0 + math.sin(phase))
                )
            else:
                # Park the phase where sin == -1 (zero attenuation) so the
                # next activation starts at full level — the attack lands
                # first, then the grain begins.
                chain_state["texture_phase"] = self._TEXTURE_PHASE_TOP

            # Zero cut — the chain's final stage. While the chain's own raw
            # input reads at/below the threshold (plug removed → proximity
            # 0), the output is forced to 0 *now*: the smoothing fall tail
            # and the speed channel's decay ring must not keep the motor
            # running against a contact that is no longer there. The
            # envelope is reset (not left to decay) so a re-insert attacks
            # from silence instead of resuming a half-decayed tail. Speed
            # state is deliberately untouched — its history is real input
            # physics, and while the cut holds, its ring is inaudible
            # anyway.
            smoothed_emit = smoothed_chain  # pre-cut, for the Smoothing trace
            textured_emit = textured_chain  # pre-cut, for the Texture trace
            zerocut = chain.get("zerocut", {}) if isinstance(chain, dict) else {}
            if not isinstance(zerocut, dict):
                # Hand-edited profile with e.g. `"zerocut": true` — treat
                # as disabled rather than crashing the hot loop.
                zerocut = {}
            if bool(zerocut.get("enabled", False)):
                zc_threshold = self._coerce_float(
                    zerocut.get("threshold", 0.0), 0.0, 0.0, 0.5
                )
                if chain_d_raw <= zc_threshold:
                    smoothed_chain = 0.0
                    textured_chain = 0.0
            # The smoothing envelope tracks the post-cut, PRE-texture value:
            # the cut resets it (re-insert attacks from silence) while the
            # texture wobble never feeds back into its own envelope.
            chain_state["smoothed_output"] = smoothed_chain

            chain_outputs.append(textured_chain)
            chain_emits.append({
                "d_raw":      chain_d_raw,
                "s_raw":      s_raw,
                "d_shaped":   d_shaped,
                "s_shaped":   s_shaped,
                "punch":      punch,
                "mixed":      mixed,
                # Wake stage: open (gate open / armed / disabled), a 0..1
                # meter (activity level, or progress toward arming in
                # strokes mode), and the post-wake signal.
                "wake_mode":  wake_mode,
                "wake_open":  wake_open_emit,
                "wake_meter": wake_meter_emit,
                "wake_out":   waked,
                "smoothed":   smoothed_emit,
                "textured":   textured_emit,
                "out":        textured_chain,
            })

        # Merge chain outputs into the final motor target. For a
        # single-chain motor this is a no-op pass-through; for two
        # chains it's the user's chosen op (add/max/multiply).
        final_out = merge_chains(chain_outputs, merge_op)

        # Anti-stuck safety cutoff — fade out a motor whose combined input
        # has been frozen too long (VRChat stops sending OSC on avatar swap /
        # partner leave / routing loss). Applied to the merged output so the
        # speed detector + smoothing state above stay honest; the factor is
        # 1.0 in the common case (input still moving, or feature disabled).
        as_factor = self._antistuck_factor(state, live_d_raw, now, antistuck)
        if as_factor < 1.0:
            final_out *= as_factor

        # Persist motor-level state. Per-chain `last_position` and
        # `smoothed_speed` were updated inside `_derive_speed_signal`;
        # only `last_time` is shared.
        state["last_time"] = now

        # Cut 6 per-(motor, chain) intermediates dispatch. Chain
        # widgets that want per-stage mini-graphs subscribe via
        # `subscribe_intermediates`; this loop fires their callbacks
        # with the same emit-dict shape the legacy Tune callback gets.
        # Zero cost when nothing is subscribed (empty dict short-
        # circuits the `if` below).
        if self._intermediates_subscribers:
            for chain_idx, emit in enumerate(chain_emits):
                key = (device_name, motor_idx, chain_idx)
                subscribers = self._intermediates_subscribers.get(key)
                if not subscribers:
                    continue
                payload = {
                    "type":      "tune_trace",
                    "device":    device_name,
                    "motor":     motor_idx,
                    "chain_idx": chain_idx,
                    "t_ms":      now * 1000.0,
                    "d_raw":     emit["d_raw"],
                    "s_raw":     emit["s_raw"],
                    "d_shaped":  emit["d_shaped"],
                    "s_shaped":  emit["s_shaped"],
                    "punch":      emit["punch"],
                    "mixed":      emit["mixed"],
                    "wake_mode":  emit["wake_mode"],
                    "wake_open":  emit["wake_open"],
                    "wake_meter": emit["wake_meter"],
                    "wake_out":   emit["wake_out"],
                    "smoothed":   emit["smoothed"],
                    "textured":   emit["textured"],
                    "out":        emit["out"],
                    "final_out":  final_out,
                }
                # Iterate over a copy so a subscriber that unsubscribes
                # itself inside its own callback doesn't corrupt the
                # iteration. Rare in practice but cheap to defend.
                for cb in list(subscribers):
                    try:
                        cb(payload)
                    except Exception:
                        # A misbehaving subscriber must never break
                        # the router's hot path.
                        pass

        # Session-logger broadcast — fires for EVERY motor every tick
        # (unlike Tune which is gated by a single subscription). Flat
        # fields preserve chain 0's per-stage values for backward
        # compatibility with SessionLogger.log_motor's six-field
        # signature; `chains` carries the full per-chain detail for
        # multi-chain-aware consumers; `out` is the merged final the
        # toy actually feels.
        if self._session_broadcast is not None:
            try:
                first = chain_emits[0] if chain_emits else {
                    "d_raw": 0.0, "s_raw": 0.0,
                    "d_shaped": 0.0, "s_shaped": 0.0, "mixed": 0.0,
                    "out": 0.0,
                }
                self._session_broadcast(device_name, motor_idx, {
                    "t_unix":    now,
                    "d_raw":     first["d_raw"],
                    "s_raw":     first["s_raw"],
                    "d_shaped":  first["d_shaped"],
                    "s_shaped":  first["s_shaped"],
                    "mixed":     first["mixed"],
                    "out":       final_out,
                    "chains":    chain_emits,
                    "merge":     merge_op,
                })
            except Exception:
                pass

        return final_out

    def compute_simple_mode_value(
        self,
        all_params: Dict[str, Any],
        zones: Optional[Set[Tuple[str, str]]] = None,
    ) -> float:
        """Simple-mode max: return the strongest contribution across every
        detected SPS zone, ignoring per-toy profile config. Touch + pen
        from others are allowed; self-contact is excluded so the user
        doesn't get unexpected output from their own contacts firing
        the gates.

        Phase 2 simplification: Simple Mode is now pure depth (no speed
        derivation, no curves, no smoothing). Users who want speed
        contribution or per-toy tuning use full Device Routing instead."""
        zones = self._get_zone_tuples(all_params, zones)
        self._update_length_detectors(all_params, zones)
        # Synthetic config: allow everything except self, mirroring the
        # default new-toy profile.
        cfg = {
            "motor_0_touch": True,
            "motor_0_pen": True,
            "motor_0_self": False,
            "motor_0_others": True,
        }
        best = 0.0
        for zone_type, zone_name in zones:
            contribution = self._zone_contribution(zone_type, zone_name, cfg, 0, all_params)
            if contribution > best:
                best = contribution
        return best

    def reevaluate_simple_mode(
        self,
        device_motor_counts: Dict[str, int],
        all_params: Dict[str, Any],
        zones: Optional[Set[Tuple[str, str]]] = None,
    ) -> List[Tuple[str, float, int]]:
        """Simple-mode routing: push the same global SPS max value to every
        connected device's every motor. Returns only entries whose target
        value changed (same debounce semantics as `reevaluate_state`).

        A fixed, non-adjustable 2 s stuck-value cutoff guards the single global
        value (see `_simple_antistuck`) — Simple Mode has no per-motor state or
        tuning, so it gets the flat-timeout version of the full path's
        anti-stuck safety net rather than the configurable two-timer model."""
        zones = self._get_zone_tuples(all_params, zones)
        value = self.compute_simple_mode_value(all_params, zones=zones)
        # Usage statistics: strokes count in Simple Mode too — the same
        # contact-level detector as the full path, fed the pre-antistuck
        # global value (anti-stuck fades outputs, not physical motion).
        if self._detect_thrust(self._global_thrust_state, value):
            self.thrust_count += 1
        value = self._simple_antistuck(value, self._clock())
        updates: List[Tuple[str, float, int]] = []
        for device_name, motor_count in device_motor_counts.items():
            for motor_idx in range(motor_count):
                state_key = (device_name, motor_idx)
                if self.last_outputs.get(state_key) != value:
                    self.last_outputs[state_key] = value
                    updates.append((device_name, value, motor_idx))
        return updates

    def reset_outputs(self) -> None:
        """Forget last-output debounce state so the next recalc treats every
        motor as changed. Used when switching routing modes so motors don't
        get stuck at the previous mode's last value."""
        self.last_outputs.clear()
        # Clearing motor state too prevents a stale Δposition spike the
        # next tick when the user flips a mode change (a routing switch
        # can leave the last-seen position arbitrarily far from the new
        # computation).
        self._motor_state.clear()
        # Reset the Simple Mode stuck-value fuse so a mode switch starts the
        # 2 s timer fresh rather than inheriting the previous value's age.
        self._simple_as_last_val = None
        self._simple_as_since = -1.0

    def forget_device(self, device_name: str) -> None:
        """Drop every trace of a deleted toy. Without this, its stale
        last_outputs entry (frozen at whatever it was when deleted) keeps
        needs_settling() true forever — the routing tick never idles
        again — and the stats facade keeps booking phantom on-time
        against a toy that no longer exists."""
        for key in [k for k in self.last_outputs if k[0] == device_name]:
            del self.last_outputs[key]
        for key in [k for k in self._motor_state if k[0] == device_name]:
            del self._motor_state[key]

    def reevaluate_state(
        self,
        active_profile: Dict[str, Any],
        all_params: Dict[str, Any],
        zones: Optional[Set[Tuple[str, str]]] = None,
        sps_sources: Optional[Dict[str, Any]] = None,
        antistuck: Optional[Dict[str, Any]] = None,
    ) -> List[Tuple[str, float, int]]:
        """Recalculate motor outputs for every configured device/motor based on the
        live Shadow State, returning only entries whose target value changed.

        `sps_sources` is the `name -> definition` map of enabled synthetic
        SPS sources (from the controller). A motor that selected a source by
        name picks up its evaluated value; None disables the feature.

        `antistuck` is the `{enabled, active_s, peaked_s}` config (from app
        settings) for the per-motor stuck-input safety cutoff; None disables
        it."""
        zones = self._get_zone_tuples(all_params, zones)
        # Refresh length calibrations first so all motor calculations see fresh state.
        self._update_length_detectors(all_params, zones)

        self._tick_max_draw = 0.0
        updates: List[Tuple[str, float, int]] = []
        for device_name, config in active_profile.items():
            motor_count = config.get("motor_count", 0)
            for motor_idx in range(motor_count):
                target_val = self._calculate_motor_target(
                    device_name, motor_idx, config, all_params,
                    zones=zones, profile_dict=active_profile,
                    sps_sources=sps_sources,
                    antistuck=antistuck,
                )

                state_key = (device_name, motor_idx)
                if self.last_outputs.get(state_key) != target_val:
                    self.last_outputs[state_key] = target_val
                    updates.append((device_name, target_val, motor_idx))
        # Usage statistics: one stroke = one count, measured on the
        # strongest contact this pass saw (each motor contributed its
        # live input in _calculate_motor_target).
        if self._detect_thrust(self._global_thrust_state, self._tick_max_draw):
            self.thrust_count += 1
        return updates
