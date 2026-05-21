import fnmatch
import math
import time
from typing import Dict, List, Tuple, Any, Optional, Set
from utilities import normalize_osc_value
from parameter_store import store as _global_store

_GLOB_CHARS = frozenset("*?[")


def _has_glob(addr: str) -> bool:
    return any(c in _GLOB_CHARS for c in addr)


def _clean_custom_addr(addr: str) -> str:
    """Strip VRChat's `/avatar/parameters/` prefix or a bare leading slash so
    the address matches the parameter_store's normalized keys."""
    if addr.startswith("/avatar/parameters/"):
        return addr[len("/avatar/parameters/"):]
    if addr.startswith("/"):
        return addr[1:]
    return addr


def _classify_zone_path(path: str) -> Optional[Tuple[str, str]]:
    """Standalone version of `ParameterStore._classify_zone` for the rare
    fallback when the global store isn't reachable (tests)."""
    parts = path.split("/", 3)
    if len(parts) >= 3 and parts[0] == "OGB":
        category = parts[1]
        zone_name = parts[2]
        if category in ("Orifice", "Orf"):
            return ("Orf", zone_name)
        if category in ("Penetrator", "Pen"):
            return ("Pen", zone_name)
    return None


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

    # Speed-blend default tuning (still exposed as class-level constants so
    # callers/tests can reference the factory defaults, but the live values
    # live on the instance and are overridable via `apply_speed_tuning`).
    #
    # `speed_input_deadband` is applied to the per-tick |Δposition| BEFORE
    # dividing by dt. VRChat avatar parameters jitter even on a static
    # contact, so without an input gate the smoothed speed signal never
    # reaches zero in pure-speed mode.
    #
    # `speed_gain` scales the noise-gated raw speed into the 0–1 range.
    # Realistic in-VRChat thrusts oscillate over a fraction of the full
    # insertion range, so the gain is tuned so a moderate stroke saturates.
    #
    # `speed_decay_tau` is the exponential decay time-constant of the
    # smoothed signal, so motion sustains briefly between strokes.
    #
    # `speed_output_cutoff` snaps decayed output to true zero once it
    # falls below this threshold (otherwise exponential decay only
    # asymptotes toward 0 and the toy keeps quietly humming).
    DEFAULT_SPEED_INPUT_DEADBAND = 0.005
    DEFAULT_SPEED_GAIN = 0.75
    DEFAULT_SPEED_DECAY_TAU = 0.30
    DEFAULT_SPEED_OUTPUT_CUTOFF = 0.02

    SPEED_TUNING_KEYS = (
        "speed_input_deadband",
        "speed_gain",
        "speed_decay_tau",
        "speed_output_cutoff",
    )

    def __init__(self) -> None:
        # Tracks last calculated outputs to prevent flooding the UI/hardware thread.
        self.last_outputs: Dict[tuple, float] = {}
        # Live tuning — overridable at runtime via apply_speed_tuning. Bounds
        # are enforced when values come in so a bad input can't break the
        # math (e.g. decay_tau must stay strictly positive).
        self.speed_input_deadband = self.DEFAULT_SPEED_INPUT_DEADBAND
        self.speed_gain = self.DEFAULT_SPEED_GAIN
        self.speed_decay_tau = self.DEFAULT_SPEED_DECAY_TAU
        self.speed_output_cutoff = self.DEFAULT_SPEED_OUTPUT_CUTOFF
        # Per-motor speed-tracker keyed by (device_name, motor_idx).
        # Value is (last_time_s, last_position, smoothed_speed). A reserved
        # ("__simple_mode__", 0) key is used by Simple Mode.
        self._speed_state: Dict[Tuple[str, int], Tuple[float, float, float]] = {}
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
        addr_legacy_key = f"motor_{motor_idx}_zone"
        osc_addresses = config.get("osc_addresses", {})
        raw_entry = osc_addresses.get(str(motor_idx))
        zones_str = config.get(addr_zone_key, config.get(addr_legacy_key, ""))

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

    def _apply_speed_blend(
        self,
        key: Tuple[str, int],
        position: float,
        blend: float,
    ) -> float:
        """Blend a raw position signal with its derived speed signal, weighted
        by `blend` (0.0 = pure position, 1.0 = pure speed). State for the
        smoothed speed is kept per `key` so motors don't cross-contaminate.

        The tracker is updated even when blend == 0 so that flipping the
        slider mid-session doesn't start from a stale position delta.
        """
        now = time.monotonic()
        prev = self._speed_state.get(key)
        if prev is None:
            # First sample for this motor — no derivative yet.
            self._speed_state[key] = (now, position, 0.0)
            speed_smoothed = 0.0
        else:
            last_t, last_pos, last_speed = prev
            dt = now - last_t
            if dt <= 0:
                # Clock didn't move — reuse last smoothed value as-is.
                speed_smoothed = last_speed
            else:
                # Input deadband: |Δposition| below `speed_input_deadband` is
                # treated as static jitter, so a static contact with sub-1%
                # OSC noise contributes nothing to speed. Subtracting the
                # deadband (instead of hard-gating) keeps the response
                # continuous as movements grow past the threshold.
                delta = abs(position - last_pos)
                if delta <= self.speed_input_deadband:
                    raw_speed = 0.0
                else:
                    raw_speed = (delta - self.speed_input_deadband) / dt
                speed_signal = raw_speed * self.speed_gain
                if speed_signal > 1.0:
                    speed_signal = 1.0
                # Exponential decay: smoothed value attacks instantly on
                # rising edge and falls off with time-constant `speed_decay_tau`.
                tau = self.speed_decay_tau if self.speed_decay_tau > 1e-4 else 1e-4
                decay = math.exp(-dt / tau)
                speed_smoothed = max(speed_signal, last_speed * decay)
            self._speed_state[key] = (now, position, speed_smoothed)

        # Output deadzone: snap to true 0 once the smoothed signal decays
        # below the cutoff, otherwise the exponential tail keeps a tiny
        # output alive forever. Above the cutoff, rescale [cutoff, 1] back
        # into [0, 1] so there's no visible step at the threshold.
        cutoff = self.speed_output_cutoff
        if speed_smoothed <= cutoff:
            output_speed = 0.0
        else:
            denom = max(1.0 - cutoff, 1e-6)
            output_speed = (speed_smoothed - cutoff) / denom
            if output_speed > 1.0:
                output_speed = 1.0

        if blend <= 0.0:
            return position
        if blend >= 1.0:
            return output_speed
        return (1.0 - blend) * position + blend * output_speed

    def apply_speed_tuning(self, **overrides: Any) -> Dict[str, float]:
        """Update one or more speed-tuning knobs at runtime.

        Each value is coerced to float and clamped into a safe range so the
        UI can pass user input straight through without sanitising it
        first. Returns the post-clamp snapshot so callers (and the saver)
        always persist what's actually in use.
        """
        for key, raw in overrides.items():
            try:
                v = float(raw)
            except (TypeError, ValueError):
                continue
            if key == "speed_input_deadband":
                self.speed_input_deadband = max(0.0, min(0.5, v))
            elif key == "speed_gain":
                self.speed_gain = max(0.0, min(50.0, v))
            elif key == "speed_decay_tau":
                # Strictly positive — exp(-dt/tau) blows up at tau→0.
                self.speed_decay_tau = max(0.01, min(5.0, v))
            elif key == "speed_output_cutoff":
                self.speed_output_cutoff = max(0.0, min(0.95, v))
        return self.get_speed_tuning()

    def get_speed_tuning(self) -> Dict[str, float]:
        return {
            "speed_input_deadband": self.speed_input_deadband,
            "speed_gain": self.speed_gain,
            "speed_decay_tau": self.speed_decay_tau,
            "speed_output_cutoff": self.speed_output_cutoff,
        }

    @classmethod
    def get_speed_tuning_defaults(cls) -> Dict[str, float]:
        """Factory defaults for the speed-blend tuning knobs. Used by the
        Reset button to revert without depending on app_settings state."""
        return {
            "speed_input_deadband": cls.DEFAULT_SPEED_INPUT_DEADBAND,
            "speed_gain": cls.DEFAULT_SPEED_GAIN,
            "speed_decay_tau": cls.DEFAULT_SPEED_DECAY_TAU,
            "speed_output_cutoff": cls.DEFAULT_SPEED_OUTPUT_CUTOFF,
        }

    @staticmethod
    def _coerce_blend(raw: Any) -> float:
        try:
            blend = float(raw)
        except (TypeError, ValueError):
            return 0.0
        if blend < 0.0:
            return 0.0
        if blend > 1.0:
            return 1.0
        return blend

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
        target_val = 0.0

        compiled = self._compile_motor_config(
            profile_dict if profile_dict is not None else config,
            device_name, motor_idx, config,
        )

        # --- 1. Custom Override Addresses --------------------------------------------
        # Literal addresses get an O(1) dict lookup; globs fall back to the
        # fnmatch sweep over all params. Each contribution feeds max().
        for literal in compiled["literals"]:
            param_val = all_params.get(literal)
            if param_val is None:
                continue
            try:
                v = float(param_val)
            except (ValueError, TypeError):
                continue
            cand = normalize_osc_value(v)
            if cand > target_val:
                target_val = cand

        if compiled["globs"]:
            for param_name, param_val in all_params.items():
                if not any(fnmatch.fnmatch(param_name, g) for g in compiled["globs"]):
                    continue
                try:
                    v = float(param_val)
                except (ValueError, TypeError):
                    continue
                cand = normalize_osc_value(v)
                if cand > target_val:
                    target_val = cand

        # --- 2. SPS Zones ------------------------------------------------------------
        if compiled["has_zone_filter"]:
            is_all_sps = compiled["is_all_sps"]
            allowed_zone_set = compiled["allowed_zones"]
            best = target_val
            for zone_type, zone_name in zones:
                if is_all_sps or zone_name in allowed_zone_set:
                    contribution = self._zone_contribution(zone_type, zone_name, config, motor_idx, all_params)
                    if contribution > best:
                        best = contribution
            target_val = best

        # --- 3. Position ↔ Speed blend ----------------------------------------------
        # The slider is stored per-motor in the profile; 0.0 keeps the legacy
        # position-only behavior. The tracker is updated unconditionally so a
        # later slider change picks up from a current sample.
        blend = self._coerce_blend(config.get(f"motor_{motor_idx}_speed_blend", 0.0))
        return self._apply_speed_blend((device_name, motor_idx), target_val, blend)

    _SIMPLE_MODE_SPEED_KEY: Tuple[str, int] = ("__simple_mode__", 0)

    def compute_simple_mode_value(
        self,
        all_params: Dict[str, Any],
        zones: Optional[Set[Tuple[str, str]]] = None,
        speed_blend: float = 0.0,
    ) -> float:
        """Simple-mode max: return the strongest contribution across every
        detected SPS zone, ignoring per-toy profile config. Touch + pen from
        others are allowed; self-contact is excluded so the user doesn't get
        unexpected output from their own contacts firing the gates.

        `speed_blend` mirrors the per-motor Position↔Speed slider but applies
        globally because Simple Mode pushes the same value to every motor.
        """
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
        return self._apply_speed_blend(
            self._SIMPLE_MODE_SPEED_KEY, best, self._coerce_blend(speed_blend)
        )

    def reevaluate_simple_mode(
        self,
        device_motor_counts: Dict[str, int],
        all_params: Dict[str, Any],
        zones: Optional[Set[Tuple[str, str]]] = None,
        speed_blend: float = 0.0,
    ) -> List[Tuple[str, float, int]]:
        """Simple-mode routing: push the same global SPS max value to every
        connected device's every motor. Returns only entries whose target
        value changed (same debounce semantics as `reevaluate_state`)."""
        zones = self._get_zone_tuples(all_params, zones)
        value = self.compute_simple_mode_value(
            all_params, zones=zones, speed_blend=speed_blend
        )
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
        # Clearing speed state too prevents a stale Δposition spike the next
        # tick when the user flips a mode change (a routing switch can leave
        # the last-seen position arbitrarily far from the new computation).
        self._speed_state.clear()

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
