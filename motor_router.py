import fnmatch
import math
import time
from typing import Callable, Dict, List, Tuple, Any, Optional, Set
from utilities import normalize_osc_value, strip_param_prefix, classify_ogb_zone
from parameter_store import store as _global_store
from mixer import apply_curve, combine, smooth

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
    # before clamping. Matches the old user-tunable speed_gain default;
    # in Phase 2 it's fixed because the speed channel exposes its own
    # post-curve `gain` knob for the same purpose. Realistic in-VRChat
    # thrusts oscillate over a fraction of the full insertion range, so
    # this value is tuned so a moderate stroke saturates.
    _SPEED_NORMALIZATION = 0.75

    # Default per-motor mix config — used when a profile is missing
    # the `mix` block entirely (defensive fallback; the seeder writes
    # this on every known motor at profile creation).
    DEFAULT_MIX_CONFIG: Dict[str, Any] = {
        "depth": {
            "enabled": True,
            "gain": 1.0,
            "curve": "linear",
            "curve_param": 1.0,
            "mode": "additive",
            "min_remap": 0.0,
            "max_remap": 1.0,
        },
        "speed": {
            "enabled": True,
            "gain": 1.0,
            "curve": "linear",
            "curve_param": 1.0,
            "mode": "additive",
            # Speed-derivation knobs (formerly global speed_*).
            # Defaults preserve old behaviour.
            "input_deadband": 0.005,
            "output_cutoff": 0.02,
            "decay_tau": 0.30,
        },
        "combine": "max",
        "modulator_range": (0.5, 1.5),
        "smoothing": {
            "attack_ms": 50.0,
            # 20 ms release tau gives a perceptible decay-to-silent of
            # ~100 ms at the default 90 Hz tick: combined with the
            # mixer's 0.5 % snap-to-zero, the toy stops feeling the
            # signal within ~110 ms of the input dropping. Users who
            # want a longer drone bump this in Device Routing.
            "release_ms": 20.0,
        },
    }

    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        # `clock` is dependency-injected so tests can drive time deterministically.
        # Defaults to time.monotonic so production callers don't change.
        self._clock = clock
        # Tracks last calculated outputs to prevent flooding the UI/hardware thread.
        self.last_outputs: Dict[tuple, float] = {}
        # Per-motor mixer state, keyed by (device_name, motor_idx). Each
        # value is a dict with `last_time`, `last_position`,
        # `smoothed_speed` (speed-derivation pipeline state) and
        # `smoothed_output` (post-mix envelope follower state). Lazily
        # created on first tick for any motor.
        self._motor_state: Dict[Tuple[str, int], Dict[str, float]] = {}
        # Tune intermediates feed. Off by default — when nothing has set
        # both a subscription and a callback, the per-tick check is a
        # single None comparison. The Tune view (Phase 3) registers a
        # subscription via TuneFacade so it can render the six-trace
        # graph of d_raw / s_raw / d_shaped / s_shaped / mixed / out.
        self._tune_subscription: Optional[Tuple[str, int]] = None
        self._tune_emit_callback: Optional[Callable[[Dict[str, Any]], None]] = None
        # Tune input-override hook. When set and the subscribed motor is
        # being computed, the provider's return value replaces d_raw —
        # bypassing zones / custom addresses entirely. Lets the
        # simulator test the mixer's behaviour with a known clean
        # signal regardless of how the user's zone filter is configured.
        # Provider returns None to fall through to the normal d_raw
        # compute (e.g. when source = live VRChat, or simulated with no
        # pattern running).
        self._tune_value_provider: Optional[Callable[[], Optional[float]]] = None
        # Per-zone length detectors keyed by ("Orf"|"Pen", zone_name, "self"|"others").
        self._length_detectors: Dict[Tuple[str, str, str], GameDeviceLengthDetector] = {}
        # Compiled per-motor config cache.
        #   key: (id(profile_dict), device_name, motor_idx, profile_token)
        #   val: pre-parsed addresses/zone names so the per-tick hot path doesn't
        #        re-split strings or re-walk the raw config dict for every motor.
        # `profile_token` is an opaque marker (currently a snapshot of the keys
        # we actually read) so a profile mutation safely invalidates the cache.
        self._compiled_cfg: Dict[Tuple[int, str, int, tuple], Dict[str, Any]] = {}

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

        compiled = {
            "literals": literals,
            "globs": globs,
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

    def _get_motor_state(self, key: Tuple[str, int]) -> Dict[str, float]:
        """Return the lazily-initialised per-motor state dict. Holds the
        per-motor mixer's smoothing/derivation history between ticks.
        `last_time` starts at -1.0 as a sentinel so the first tick is
        treated as dt=0 regardless of the clock's starting value (tests
        often use a FakeClock that begins at 0.0)."""
        state = self._motor_state.get(key)
        if state is None:
            state = {
                "last_time": -1.0,
                "last_position": 0.0,
                "smoothed_speed": 0.0,
                "smoothed_output": 0.0,
            }
            self._motor_state[key] = state
        return state

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

    def _derive_speed_signal(self, state: Dict[str, float],
                             position: float,
                             speed_cfg: Dict[str, Any],
                             dt: float) -> float:
        """Compute the per-motor S_raw from |Δposition|/dt with the
        speed-channel's input_deadband, output_cutoff and decay_tau knobs.
        Updates `state["smoothed_speed"]` in place. Returns the post-
        cutoff value in [0, 1] suitable for feeding into apply_curve.

        Rate independence: `decay_tau` is a wall-clock time constant.
        `decay = exp(-dt / decay_tau)` compensates for the elapsed
        interval, so the perceived decay envelope is identical at any
        router rate. Never recalibrate decay_tau when the router's
        tick rate changes. raw_speed = (|delta| - deadband) / dt is
        also a per-second rate so it's directly comparable across
        sample rates."""
        last_pos = state["last_position"]
        prev_smoothed = state["smoothed_speed"]

        deadband_cfg = speed_cfg.get("input_deadband",
                                     self.DEFAULT_MIX_CONFIG["speed"]["input_deadband"])
        decay_tau_cfg = speed_cfg.get("decay_tau",
                                      self.DEFAULT_MIX_CONFIG["speed"]["decay_tau"])
        cutoff_cfg = speed_cfg.get("output_cutoff",
                                   self.DEFAULT_MIX_CONFIG["speed"]["output_cutoff"])
        try:
            deadband = max(0.0, min(0.5, float(deadband_cfg)))
        except (TypeError, ValueError):
            deadband = 0.005
        try:
            decay_tau = max(0.01, min(5.0, float(decay_tau_cfg)))
        except (TypeError, ValueError):
            decay_tau = 0.30
        try:
            cutoff = max(0.0, min(0.95, float(cutoff_cfg)))
        except (TypeError, ValueError):
            cutoff = 0.02

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

        state["smoothed_speed"] = smoothed

        if smoothed <= cutoff:
            return 0.0
        denom = max(1.0 - cutoff, 1e-6)
        return min(1.0, (smoothed - cutoff) / denom)

    def set_tune_emit_callback(self,
                               callback: Optional[Callable[[Dict[str, Any]], None]]
                               ) -> None:
        """Register (or clear) the callback that receives per-tick
        intermediates for the currently-subscribed motor. The Tune
        facade wires this to a thread_queue push so the UI thread can
        drain trace records in its existing queue-processing loop."""
        self._tune_emit_callback = callback

    def set_tune_subscription(self, device_name: str, motor_idx: int) -> None:
        """Subscribe the Tune view to one motor's intermediates feed.
        Cheap — only one motor is ever traced at a time, so the
        per-tick check is just `if subscription == (dev, idx)`."""
        self._tune_subscription = (str(device_name), int(motor_idx))

    def clear_tune_subscription(self) -> None:
        self._tune_subscription = None

    def has_tune_subscription(self) -> bool:
        """True when the Tune view is actively watching a motor — the
        controller's routing tick uses this to keep the tick firing
        even when VRChat is silent, so the trace graph stays current."""
        return self._tune_subscription is not None

    def set_tune_value_provider(self,
                                provider: Optional[Callable[[], Optional[float]]]
                                ) -> None:
        """Register a callable that supplies the simulated d_raw value
        for the subscribed motor each tick. Pass None to clear. When
        the provider returns None the router falls back to normal
        zone/address routing for that motor."""
        self._tune_value_provider = provider

    @staticmethod
    def _coerce_float(value: Any, default: float,
                      lo: float = -1e9, hi: float = 1e9) -> float:
        """Defensive numeric coercion — bad values silently fall back to
        the default. Used for every mix-config field read so a malformed
        profile can't crash the router."""
        try:
            v = float(value)
        except (TypeError, ValueError):
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
    ) -> float:
        """Max-wins combine of every input the motor listens to:
        - Literal custom OSC addresses (O(1) dict lookups)
        - Custom OSC address globs (fnmatch sweep)
        - SPS zone contributions (when the motor's zone filter is set)
        Returns a value in [0, 1]. Pure function of its inputs — used
        by both live routing and as the fallback for the Tune view's
        input override."""
        d_raw = 0.0
        for literal in compiled["literals"]:
            param_val = all_params.get(literal)
            if param_val is None:
                continue
            try:
                v = float(param_val)
            except (ValueError, TypeError):
                continue
            cand = normalize_osc_value(v)
            if cand > d_raw:
                d_raw = cand

        if compiled["globs"]:
            for param_name, param_val in all_params.items():
                if not any(fnmatch.fnmatch(param_name, g) for g in compiled["globs"]):
                    continue
                try:
                    v = float(param_val)
                except (ValueError, TypeError):
                    continue
                cand = normalize_osc_value(v)
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
    ) -> float:
        compiled = self._compile_motor_config(
            profile_dict if profile_dict is not None else config,
            device_name, motor_idx, config,
        )

        # --- 1. D_raw: custom override addresses + SPS zones (max-wins) ---
        # Phase 3 Tune view input override: when this is the subscribed
        # motor and the provider returns a value, use it as d_raw and
        # skip the normal compute. Lets the simulator test the mixer's
        # behaviour with a known clean signal regardless of how the
        # user's zone filter is configured. Other motors are unaffected.
        sim_d_raw: Optional[float] = None
        if (self._tune_value_provider is not None
                and self._tune_subscription == (device_name, motor_idx)):
            try:
                sim_d_raw = self._tune_value_provider()
            except Exception:
                sim_d_raw = None

        if sim_d_raw is not None:
            d_raw = max(0.0, min(1.0, float(sim_d_raw)))
        else:
            d_raw = self._compute_d_raw_from_inputs(
                compiled, all_params, config, motor_idx, zones
            )

        # --- 2. Mixer: per-channel shaping → combine → smoothing ---
        mix = self._get_mix_config(config, motor_idx)
        state = self._get_motor_state((device_name, motor_idx))

        now = self._clock()
        last_t = state["last_time"]
        # last_time == -1.0 is the sentinel for "no prior tick"; otherwise
        # any monotonic value (including 0.0 from a FakeClock) is valid.
        dt = (now - last_t) if last_t >= 0.0 else 0.0

        s_raw = self._derive_speed_signal(state, d_raw, mix["speed"], dt)

        depth = mix["depth"]
        speed = mix["speed"]
        d_shaped = apply_curve(
            d_raw,
            str(depth.get("curve", "linear")),
            self._coerce_float(depth.get("curve_param", 1.0), 1.0),
        ) * self._coerce_float(depth.get("gain", 1.0), 1.0, 0.0, 2.0)
        s_shaped = apply_curve(
            s_raw,
            str(speed.get("curve", "linear")),
            self._coerce_float(speed.get("curve_param", 1.0), 1.0),
        ) * self._coerce_float(speed.get("gain", 1.0), 1.0, 0.0, 2.0)

        mod_range = mix.get("modulator_range", (0.5, 1.5))
        try:
            mod_min = float(mod_range[0])
            mod_max = float(mod_range[1])
        except (TypeError, ValueError, IndexError):
            mod_min, mod_max = 0.5, 1.5

        mixed = combine(
            d_shaped, s_shaped,
            bool(depth.get("enabled", True)), str(depth.get("mode", "additive")),
            bool(speed.get("enabled", True)), str(speed.get("mode", "additive")),
            str(mix.get("combine", "max")),
            mod_min, mod_max,
        )

        smoothing = mix.get("smoothing", {})
        attack_ms = self._coerce_float(
            smoothing.get("attack_ms", 50.0), 50.0, 0.0, 2000.0
        )
        release_ms = self._coerce_float(
            smoothing.get("release_ms", 20.0), 20.0, 0.0, 2000.0
        )
        smoothed = smooth(
            state["smoothed_output"], mixed, dt * 1000.0, attack_ms, release_ms
        )

        # Persist per-tick state for the next call.
        state["smoothed_output"] = smoothed
        state["last_position"] = d_raw
        state["last_time"] = now

        # Emit Tune intermediates if subscribed. Zero cost when both
        # `_tune_subscription` and `_tune_emit_callback` are None.
        if (self._tune_subscription is not None
                and self._tune_emit_callback is not None
                and self._tune_subscription == (device_name, motor_idx)):
            try:
                self._tune_emit_callback({
                    "type": "tune_trace",
                    "device": device_name,
                    "motor": motor_idx,
                    "t_ms": now * 1000.0,
                    "d_raw": d_raw,
                    "s_raw": s_raw,
                    "d_shaped": d_shaped,
                    "s_shaped": s_shaped,
                    "mixed": mixed,
                    "out": smoothed,
                })
            except Exception:
                # A misbehaving Tune callback must never break the
                # router's hot path. Silently drop.
                pass

        return smoothed

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
        value changed (same debounce semantics as `reevaluate_state`)."""
        zones = self._get_zone_tuples(all_params, zones)
        value = self.compute_simple_mode_value(all_params, zones=zones)
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

    def reevaluate_state(
        self,
        active_profile: Dict[str, Any],
        all_params: Dict[str, Any],
        zones: Optional[Set[Tuple[str, str]]] = None,
    ) -> List[Tuple[str, float, int]]:
        """Recalculate motor outputs for every configured device/motor based on the
        live Shadow State, returning only entries whose target value changed."""
        zones = self._get_zone_tuples(all_params, zones)
        # Refresh length calibrations first so all motor calculations see fresh state.
        self._update_length_detectors(all_params, zones)

        updates: List[Tuple[str, float, int]] = []
        for device_name, config in active_profile.items():
            motor_count = config.get("motor_count", 0)
            for motor_idx in range(motor_count):
                target_val = self._calculate_motor_target(
                    device_name, motor_idx, config, all_params,
                    zones=zones, profile_dict=active_profile,
                )

                state_key = (device_name, motor_idx)
                if self.last_outputs.get(state_key) != target_val:
                    self.last_outputs[state_key] = target_val
                    updates.append((device_name, target_val, motor_idx))
        return updates
