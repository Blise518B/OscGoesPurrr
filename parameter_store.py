import threading
from typing import Dict, Any, List, Set, Tuple


class ParameterStore:
    """
    Central thread-safe repository for all VRChat avatar parameters and detected zones.
    Acts as the single source of truth for the Router and the UI.
    """
    def __init__(self):
        self.all_parameters: Dict[str, Any] = {}
        self.detected_zones: Dict[str, List[str]] = {"Orifices": [], "Penetrators": []}
        # Incrementally maintained zone tuple set the router consumes directly,
        # so per-tick recalc never re-walks all parameter keys (see motor_router).
        self._zone_tuples: Set[Tuple[str, str]] = set()
        # Monotonic counter bumped whenever the parameter table changes. Lets
        # the routing tick early-exit when nothing relevant happened since
        # last evaluation.
        self._version: int = 0
        # Total UDP-packet writes received since boot. Single best signal for
        # "is VRChat actually sending us anything right now?" — when this stops
        # advancing but `is_connected` is still True, we have a silent drop
        # (multi-OSC-client conflict, VRChat dropped us from its routing table,
        # mDNS advertisement lost, etc.). Surfaced in OSC diagnostics logging.
        self.packets_received: int = 0
        self.lock = threading.Lock()

    # The OSCQuery tree is rooted at avatar/parameters/* for VRChat avatars,
    # but the UDP handler stores parameters under their short name (the part
    # after /avatar/parameters/). Normalize JSON-dump keys the same way so the
    # initial snapshot and live UDP updates land on identical keys — otherwise
    # the Inspector shows stale duplicates that never refresh.
    _AVATAR_PARAM_PREFIX = "avatar/parameters/"

    @staticmethod
    def _classify_zone(path: str) -> "Tuple[str, str] | None":
        """Return `(zone_type, zone_name)` for an OGB-shaped path or None."""
        parts = path.split("/", 3)
        if len(parts) >= 3 and parts[0] == "OGB":
            category = parts[1]
            zone_name = parts[2]
            if category in ("Orifice", "Orf"):
                return ("Orf", zone_name)
            if category in ("Penetrator", "Pen"):
                return ("Pen", zone_name)
        return None

    def _refresh_zone_lists(self) -> None:
        """Rebuild the public Orifices/Penetrators name lists from `_zone_tuples`."""
        orifices = sorted({n for t, n in self._zone_tuples if t == "Orf"})
        penetrators = sorted({n for t, n in self._zone_tuples if t == "Pen"})
        self.detected_zones = {"Orifices": orifices, "Penetrators": penetrators}

    def _ensure_zone_tuples_locked(self) -> None:
        """Belt-and-suspenders: if `_zone_tuples` is empty but `all_parameters`
        has OGB-shaped paths, re-derive zones from the param cache and write
        the result back so callers see a coherent set.

        Why this exists: `_zone_tuples` is normally maintained incrementally
        by `update_parameter` and rebuilt by `rebuild_from_json`, both of
        which keep it in sync with `all_parameters`. But a window of
        inconsistency is observable in two cases:
          1. `rebuild_from_json` raises mid-parse — both stores were cleared
             before the parse, leaving the param cache half-populated and
             the zone set empty.
          2. A consumer reads the snapshot during the moment after avatar
             swap when the OSCQuery refetch fires `rebuild_from_json` to
             clear-and-repopulate; if anything during the rebuild path
             classifies into the zone set in an unexpected order.
        In either case the router would emit zero output for an "All SPS"
        selection even though the touch/proximity params are sitting in
        `all_parameters`. This method scans once on demand to recover.
        Caller MUST already hold `self.lock`."""
        if self._zone_tuples or not self.all_parameters:
            return
        derived: Set[Tuple[str, str]] = set()
        for path in self.all_parameters.keys():
            zone = self._classify_zone(path)
            if zone is not None:
                derived.add(zone)
        if derived:
            self._zone_tuples = derived
            self._refresh_zone_lists()

    def _parse_oscquery_node(self, node: dict, prefix: str = ""):
        """Recursively flattens the OSCQuery JSON tree."""
        if "CONTENTS" in node:
            for key, child in node["CONTENTS"].items():
                new_prefix = f"{prefix}/{key}" if prefix else key
                self._parse_oscquery_node(child, new_prefix)
        else:
            # Leaf node (actual parameter)
            val = 0.0
            if "VALUE" in node and isinstance(node["VALUE"], list) and len(node["VALUE"]) > 0:
                val = node["VALUE"][0]
            key = prefix
            if key.startswith(self._AVATAR_PARAM_PREFIX):
                key = key[len(self._AVATAR_PARAM_PREFIX):]
            self.all_parameters[key] = val

    def rebuild_from_json(self, data: dict) -> int:
        """
        Clears and rebuilds the entire parameter cache from a fresh VRChat OSCQuery JSON.
        Returns the total number of parameters loaded.
        """
        with self.lock:
            self.all_parameters.clear()
            self._zone_tuples.clear()
            self._parse_oscquery_node(data)

            for path in self.all_parameters.keys():
                zone = self._classify_zone(path)
                if zone is not None:
                    self._zone_tuples.add(zone)

            self._refresh_zone_lists()
            self._version += 1
            return len(self.all_parameters)

    def update_parameter(self, address: str, value: Any):
        """Updates a single parameter in real-time when a UDP packet arrives.

        Also keeps `_zone_tuples` current incrementally — only the first packet
        for a brand-new zone path rebuilds the public name lists, so the
        steady-state cost is one dict write plus one tuple-set membership check.
        """
        with self.lock:
            is_new_key = address not in self.all_parameters
            self.all_parameters[address] = value
            self._version += 1
            self.packets_received += 1
            if is_new_key:
                zone = self._classify_zone(address)
                if zone is not None and zone not in self._zone_tuples:
                    self._zone_tuples.add(zone)
                    self._refresh_zone_lists()

    def get_packets_received(self) -> int:
        """Total parameter writes since process start. Used by the watchdog
        to detect 'connected but silent' (VRChat thinks we're alive, no
        packets arriving — typically a multi-OSC-client routing problem)."""
        with self.lock:
            return self.packets_received

    def get_all_parameters(self) -> Dict[str, Any]:
        """Safely returns a copy of the current parameter state."""
        with self.lock:
            return self.all_parameters.copy()

    def snapshot(self) -> Tuple[Dict[str, Any], int, Set[Tuple[str, str]]]:
        """Atomic snapshot of `(params_copy, version, zone_tuples_copy)`.

        Routers prefer this over three separate getters so they read a
        single coherent picture per tick.
        """
        with self.lock:
            self._ensure_zone_tuples_locked()
            return (
                self.all_parameters.copy(),
                self._version,
                set(self._zone_tuples),
            )

    def get_version(self) -> int:
        """Monotonic counter — bumps on every write. Use to short-circuit
        recomputation when nothing changed since the last tick."""
        with self.lock:
            return self._version

    def get_zone_tuples(self) -> Set[Tuple[str, str]]:
        """Set of `(zone_type, zone_name)` tuples currently present. Maintained
        incrementally — O(1) per get instead of O(N params)."""
        with self.lock:
            self._ensure_zone_tuples_locked()
            return set(self._zone_tuples)

    def get_detected_zones(self) -> Dict[str, List[str]]:
        """Safely returns a copy of the detected zones."""
        with self.lock:
            self._ensure_zone_tuples_locked()
            return {
                "Orifices": list(self.detected_zones["Orifices"]),
                "Penetrators": list(self.detected_zones["Penetrators"])
            }


# Global Singleton instance to be imported by other modules
store = ParameterStore()
