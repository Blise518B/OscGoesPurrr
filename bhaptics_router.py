# bhaptics_router.py
# Polls the global parameter_store for bHaptics v1 OSC bool parameters and
# dispatches per-device dot-mode frames to the bHaptics Player.
#
# v1 OSC schema (HerpDerpinstine/bHapticsOSC v1.0.0, GPL3):
#   /avatar/parameters/bHaptics_<Slot>_{N}_bool   (bool, N is 1-based)
#
# Slot strings → bHaptics Player v2 position names:
#   Head             → Head        (6 nodes)
#   Vest_Front       → VestFront   (20)
#   Vest_Back        → VestBack    (20)
#   Arm_Left/Right   → ForearmL/R  (6)
#   Hand_Left/Right  → HandL/R     (3)
#   Foot_Left/Right  → FootL/R     (3)

import threading
import time
from typing import Any, Callable, Dict, List, Optional, Tuple

from parameter_store import store
from bhaptics_engine import BHapticsEngine, DeviceConfig, NODE_COUNTS
from router_base import PollingRouter
from zone_strength import truthy, zone_filter_strength


# (position, v1_slot, node_count)
_DEVICE_TABLE: List[Tuple[str, str, int]] = [
    ("Head",       "Head",        6),
    ("VestFront",  "Vest_Front",  20),
    ("VestBack",   "Vest_Back",   20),
    ("ForearmL",   "Arm_Left",    6),
    ("ForearmR",   "Arm_Right",   6),
    ("HandL",      "Hand_Left",   3),
    ("HandR",      "Hand_Right",  3),
    ("FootL",      "Foot_Left",   3),
    ("FootR",      "Foot_Right",  3),
]


def _store_key(slot: str, node_1based: int) -> str:
    """parameter_store key (short form — UDP handler strips the avatar/parameters/ prefix)."""
    return f"bHaptics_{slot}_{node_1based}_bool"


def _store_key_bosc_v1(position: str, node_1based: int) -> str:
    """Alternate v1 schema commonly seen on community avatars:

      /avatar/parameters/bOSC_v1_<Position><Node>   (float 0.0-1.0)

    Position uses the bHaptics SDK name verbatim (VestFront, ForearmL, etc.)
    instead of the underscore-separated slot form. Values are proximity
    floats from VRChat contact receivers rather than booleans."""
    return f"bOSC_v1_{position}_{node_1based}"


# _truthy kept as a module-level alias so this router's hot _tick (and any
# external importer) keeps working unchanged; the implementation now lives in
# zone_strength so every backend shares one definition.
_truthy = truthy


# ----------------------------------------------------------
# SPS -> bHaptics mirror compute
# ----------------------------------------------------------

def _sps_entry_strength(entry: Dict[str, Any],
                        params: Dict[str, Any],
                        sps_sources: Optional[Dict[str, Any]] = None) -> float:
    """Look up an SPS-mirror entry's OGB contact params and return the
    max value (0..1) across the entry's enabled filters. A filter is
    skipped when its companion `<filter>Close` key is present and
    false — same close-gate convention as motor_router. When the
    Close key is absent, the filter is treated as live (assume open).

    When the entry's zone name matches a synthetic SPS source (in the
    `sps_sources` map), that source's evaluated value is returned
    directly — synthetic sources carry their own gating, so the entry's
    filters / zone_type don't apply.

    Thin adapter over `zone_strength.zone_filter_strength`: the mirror
    entry just unpacks into the shared (zone, type, filters) call so
    bHaptics and the OWO / PiShock / Coyote routers all evaluate zones
    through one code path."""
    return zone_filter_strength(
        entry.get("ogb_zone"),
        entry.get("zone_type", "Orf"),
        entry.get("filters") or [],
        params,
        sps_sources,
    )


def compute_sps_mirror_dots(sps_cfg: Optional[Dict[str, Any]],
                            params: Dict[str, Any],
                            enabled_positions: Optional[set] = None,
                            sps_sources: Optional[Dict[str, Any]] = None,
                            ) -> Dict[str, Dict[int, float]]:
    """Project every enabled SPS-mirror entry onto its target dots.
    Returns `{position: {dot_index: intensity_0_1}}`. Multiple entries
    landing on the same dot merge via max-wins. Entries targeting a
    position that isn't in `enabled_positions` (when supplied) are
    dropped — matches the per-device enable toggle in the main router
    loop.

    Pure function: caller supplies the config and param snapshots so
    this is trivially unit-testable without the router's polling
    thread or engine."""
    if not isinstance(sps_cfg, dict) or not sps_cfg.get("enabled", False):
        return {}
    entries = sps_cfg.get("entries") or []
    if not entries:
        return {}
    out: Dict[str, Dict[int, float]] = {}
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        position = str(entry.get("position", "")).strip()
        if not position:
            continue
        if enabled_positions is not None and position not in enabled_positions:
            continue
        strength = _sps_entry_strength(entry, params, sps_sources)
        if strength <= 0.0:
            continue
        try:
            threshold = float(entry.get("threshold", 0.0))
        except (TypeError, ValueError):
            threshold = 0.0
        try:
            gain = float(entry.get("gain", 1.0))
        except (TypeError, ValueError):
            gain = 1.0
        if strength <= threshold:
            continue
        shaped = (strength - threshold) * gain
        if shaped <= 0.0:
            continue
        if shaped > 1.0:
            shaped = 1.0
        dot_indices = entry.get("dot_indices") or []
        for raw_idx in dot_indices:
            try:
                d = int(raw_idx)
            except (TypeError, ValueError):
                continue
            if d < 0:
                continue
            pos_map = out.setdefault(position, {})
            if shaped > pos_map.get(d, 0.0):
                pos_map[d] = shaped
    return out


class BHapticsRouter(PollingRouter):
    """Polls parameter_store and pushes per-device frames to the engine.

    Inherits the ~60 Hz poll loop (`_run`) from PollingRouter but keeps its own
    bespoke `_tick`: the anti-stuck ramp, the per-dot raw/override snapshots,
    and the zero-frame-on-disable don't fit the flat compute_targets/dispatch
    model, so `compute_targets`/`dispatch` are intentionally unused here."""

    def __init__(self,
                 engine: BHapticsEngine,
                 get_device_configs: Callable[[], Dict[str, DeviceConfig]],
                 poll_rate_s: float = 0.016,  # ~60 Hz: low-latency change detection (debounced, so holds don't spam the Player)
                 get_antistuck: Callable[[], Dict[str, float]] | None = None,
                 get_sps_mirror_config: Callable[[], Dict[str, Any]] | None = None,
                 get_sps_sources: Callable[[], Dict[str, Any]] | None = None):
        super().__init__("bHapticsRouter", engine, poll_rate_s=poll_rate_s)
        self.get_device_configs = get_device_configs
        # Returns {"enabled": bool, "hold_s": float, "ramp_s": float}.
        # Read on every tick so config changes apply live.
        self.get_antistuck = get_antistuck or (lambda: {"enabled": False, "hold_s": 2.0, "ramp_s": 2.0})
        # Returns the sps_mirror dict (see BHapticsSettingsManager) or
        # None. When None or `enabled=False`, the SPS layer contributes
        # nothing and the existing v1 OSC bool/float paths drive dots
        # unchanged. Read on every tick so live edits apply.
        self.get_sps_mirror_config = get_sps_mirror_config or (lambda: None)
        # Returns the enabled synthetic-SPS-source map (name -> definition)
        # or None. A Cross-Routing entry whose zone name matches a source
        # resolves to that source's evaluated value. Read every tick so
        # live edits to a source apply without a restart.
        self.get_sps_sources = get_sps_sources or (lambda: None)
        # Track last submitted dot tuple per device so we can debounce, and so
        # the debug UI can read what's currently being driven.
        self._last_dots: Dict[str, Tuple[int, ...]] = {}
        # Mirror of the per-tick raw values (pre anti-stuck, pre override) so
        # the debug UI can render a side-by-side raw-vs-output comparison.
        self._last_raw: Dict[str, Tuple[int, ...]] = {}
        # Anti-stuck bookkeeping (per device, per node):
        #   _raw_values   — the raw intensity (0-100) computed from OSC last tick
        #   _change_times — wall-clock time the raw value last actually changed
        # Both are sized lazily — first time we see a device we allocate count slots.
        self._raw_values: Dict[str, List[int]] = {}
        self._change_times: Dict[str, List[float]] = {}
        self._snapshot_lock = threading.Lock()
        # Manual debug overrides: {position: {dot_index_0based: intensity_0_100}}.
        # Set by the UI when the user click-holds a debug dot; merged with the
        # routed output via max-wins so the device fires even if no OSC param
        # is driving that node.
        self._overrides: Dict[str, Dict[int, int]] = {}
        self._overrides_lock = threading.Lock()

    def get_snapshot(self) -> Dict[str, List[int]]:
        """Return a copy of the current per-device dot intensity arrays.
        Used by the debug UI; safe to call from any thread."""
        with self._snapshot_lock:
            return {pos: list(dots) for pos, dots in self._last_dots.items()}

    def get_raw_snapshot(self) -> Dict[str, List[int]]:
        """Per-device raw OSC intensities (pre anti-stuck, pre manual override).
        Companion to get_snapshot() — paired they show input vs. driven output."""
        with self._snapshot_lock:
            return {pos: list(raw) for pos, raw in self._last_raw.items()}

    def set_manual_override(self, position: str, index: int, intensity) -> None:
        """Force a single dot to a fixed intensity (0..100), or pass None to
        clear. Used by the debug UI's click-to-test feature. Max-merges with
        the routed output, so triggering an override always wins."""
        with self._overrides_lock:
            slot = self._overrides.setdefault(position, {})
            if intensity is None:
                slot.pop(int(index), None)
                if not slot:
                    self._overrides.pop(position, None)
            else:
                slot[int(index)] = max(0, min(100, int(intensity)))

    def _tick(self):
        if not self.engine.is_connected:
            # Clear debounce so we re-submit immediately on reconnect, and
            # blank the debug snapshot + anti-stuck timers so we don't carry
            # phantom values across a disconnect.
            with self._snapshot_lock:
                if self._last_dots:
                    self._last_dots.clear()
                if self._last_raw:
                    self._last_raw.clear()
            self._raw_values.clear()
            self._change_times.clear()
            return
        params = store.get_all_parameters() or {}
        with self._overrides_lock:
            overrides = {pos: dict(slots) for pos, slots in self._overrides.items()}
        if not params and not overrides:
            return
        configs = self.get_device_configs()
        antistuck = self.get_antistuck()
        as_enabled = bool(antistuck.get("enabled", False))
        as_hold = max(0.0, float(antistuck.get("hold_s", 2.0)))
        as_ramp = max(0.01, float(antistuck.get("ramp_s", 2.0)))
        # Compute the SPS-mirror per-dot contribution once per tick;
        # the per-position loop folds it into `raw` alongside the v1
        # OSC bool/float values via max-wins. Empty dict when the
        # mirror is disabled or has no entries — costs nothing.
        sps_cfg = None
        try:
            sps_cfg = self.get_sps_mirror_config()
        except Exception:
            sps_cfg = None
        sps_sources = None
        try:
            sps_sources = self.get_sps_sources()
        except Exception:
            sps_sources = None
        enabled_positions = {
            pos for pos, cfg in (configs or {}).items() if cfg and cfg.enabled
        }
        sps_per_dot = compute_sps_mirror_dots(
            sps_cfg, params, enabled_positions, sps_sources
        )
        now = time.time()
        for position, slot, count in _DEVICE_TABLE:
            cfg = configs.get(position)
            pos_overrides = overrides.get(position) or {}
            if cfg is None or not cfg.enabled:
                # Disabled device contributes no OSC routing, so raw is zeros.
                zero_raw = tuple([0] * count)
                with self._snapshot_lock:
                    self._last_raw[position] = zero_raw
                # Device disabled: still honor manual debug overrides so the
                # click-to-test feature works without flipping the toggle.
                if pos_overrides:
                    dots = [int(pos_overrides.get(i, 0)) for i in range(count)]
                    tup = tuple(dots)
                    with self._snapshot_lock:
                        prev = self._last_dots.get(position)
                    if prev != tup:
                        with self._snapshot_lock:
                            self._last_dots[position] = tup
                        self.engine.submit_dot_frame(position, dots)
                    continue
                # If we previously submitted activity, push a zero frame once
                # to silence the device, then keep the zero snapshot.
                with self._snapshot_lock:
                    prev = self._last_dots.get(position)
                if prev and any(prev):
                    self.engine.submit_dot_frame(position, [0] * count)
                    with self._snapshot_lock:
                        self._last_dots[position] = tuple([0] * count)
                continue

            intensity = max(0, min(100, int(cfg.intensity)))

            # Lazily allocate per-device tracking arrays. Re-allocate if the
            # device's node_count somehow changes between ticks.
            raw_arr = self._raw_values.get(position)
            time_arr = self._change_times.get(position)
            if raw_arr is None or len(raw_arr) != count:
                raw_arr = [0] * count
                time_arr = [now] * count
                self._raw_values[position] = raw_arr
                self._change_times[position] = time_arr

            dots: List[int] = []
            raw_dots: List[int] = []
            for n in range(1, count + 1):
                # Two known v1 schemas are supported and combined per-node
                # (max wins). Both feed the same physical dot.
                #  1) HerpDerpinstine bHapticsOSC v1: bool, full intensity
                #     when true, off when false.
                #  2) bOSC_v1 community schema: float 0.0-1.0 from a contact
                #     receiver; scaled by the device's intensity setting.
                bool_val = params.get(_store_key(slot, n))
                float_val = params.get(_store_key_bosc_v1(position, n))

                from_bool = intensity if _truthy(bool_val) else 0

                from_float = 0
                if float_val is not None:
                    try:
                        f = max(0.0, min(1.0, float(float_val)))
                        from_float = int(round(f * intensity))
                    except (TypeError, ValueError):
                        from_float = 0

                # SPS-mirror layer (0..1 float, scaled by the device's
                # intensity setting the same way the v1 float layer is).
                sps_strength = sps_per_dot.get(position, {}).get(n - 1, 0.0)
                from_sps = int(round(sps_strength * intensity)) if sps_strength > 0 else 0

                raw = max(from_bool, from_float, from_sps)
                raw_dots.append(raw)

                # --- Anti-stuck ramp-down -----------------------------------
                # Track when raw last actually changed; if it sits unchanged
                # past hold_s, ramp the OUTPUT linearly to 0 over ramp_s.
                # The raw value itself is preserved so a real change resets
                # the timer and the dot springs back to its true level.
                idx = n - 1
                if raw != raw_arr[idx]:
                    raw_arr[idx] = raw
                    time_arr[idx] = now
                    out = raw
                elif as_enabled and raw > 0:
                    age = now - time_arr[idx]
                    if age <= as_hold:
                        out = raw
                    else:
                        ramp_t = age - as_hold
                        if ramp_t >= as_ramp:
                            out = 0
                        else:
                            scale = 1.0 - (ramp_t / as_ramp)
                            out = max(0, int(round(raw * scale)))
                else:
                    out = raw

                # Manual debug override: max-wins, bypasses anti-stuck.
                ov = pos_overrides.get(idx)
                if ov is not None and ov > out:
                    out = ov

                dots.append(out)

            tup = tuple(dots)
            raw_tup = tuple(raw_dots)
            with self._snapshot_lock:
                # Always refresh raw snapshot so the debug view tracks input
                # changes even when output is debounced (e.g., anti-stuck
                # holding output flat while raw varies).
                self._last_raw[position] = raw_tup
                prev = self._last_dots.get(position)
            if prev == tup:
                continue
            with self._snapshot_lock:
                self._last_dots[position] = tup
            self.engine.submit_dot_frame(position, dots)


def device_table() -> List[Tuple[str, str, int]]:
    """Exposes (position, v1_slot, node_count) tuples for the UI layer."""
    return list(_DEVICE_TABLE)


def detected_positions(params: Dict[str, object]) -> set:
    """Return the set of bHaptics positions for which at least one expected
    OSC parameter is present in the supplied param dict. Used by the UI to
    hide device cards the avatar doesn't actually wire up."""
    found = set()
    for position, slot, count in _DEVICE_TABLE:
        for n in range(1, count + 1):
            if _store_key(slot, n) in params or _store_key_bosc_v1(position, n) in params:
                found.add(position)
                break
    return found


# Display grid layout per device. Indices fill left-to-right, top-to-bottom
# starting at 0 — matches bHaptics dot-mode index ordering. The vest is shown
# in wearer-facing orientation so the front/back panels read like you're
# looking at the person wearing them.
_GRID_LAYOUTS: Dict[str, Tuple[int, int]] = {
    "Head":      (6, 1),
    "VestFront": (4, 5),
    "VestBack":  (4, 5),
    "ForearmL":  (2, 3),
    "ForearmR":  (2, 3),
    "HandL":     (3, 1),
    "HandR":     (3, 1),
    "FootL":     (3, 1),
    "FootR":     (3, 1),
}


def grid_layout(position: str) -> Tuple[int, int]:
    """(cols, rows) for the debug grid; defaults to a single row."""
    return _GRID_LAYOUTS.get(position, (NODE_COUNTS.get(position, 1), 1))


def display_name(position: str) -> str:
    return {
        "Head": "Head",
        "VestFront": "Vest Front",
        "VestBack": "Vest Back",
        "ForearmL": "Arm Left",
        "ForearmR": "Arm Right",
        "HandL": "Hand Left",
        "HandR": "Hand Right",
        "FootL": "Foot Left",
        "FootR": "Foot Right",
    }.get(position, position)
