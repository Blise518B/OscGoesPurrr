import threading
from typing import Dict, Any, List, Set, Tuple

from utilities import classify_ogb_zone


# OSCQuery's type tags -> the types the Avatar Remote page speaks
_TYPE_TAGS = {"T": "Bool", "F": "Bool", "i": "Int", "f": "Float"}


class ParameterStore:
    """
    Central thread-safe repository for all VRChat avatar parameters and detected zones.
    Acts as the single source of truth for the Router and the UI.
    """
    def __init__(self):
        self.all_parameters: Dict[str, Any] = {}
        self.detected_zones: Dict[str, List[str]] = {
            "Orifices": [], "Penetrators": [], "Touch": [],
        }
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
        # While True, live UDP/OSCQuery writes are dropped and only the
        # replay driver may write (via apply_replay_frame). This is the
        # single choke point that makes session replay "block real OSC
        # input" — the OSC threads keep running untouched; their writes
        # just no-op here, so a partner or a stray packet can't fight the
        # replayed motion. Toggled by the replay facade on the GUI thread.
        self._input_locked: bool = False
        # Per-key count of bool False->True edges seen on the live UDP path.
        # An OnEnter contact can be True for a single VRChat frame, so a
        # poller that only reads the current value misses most of them; a
        # router compares these counts against its last tick instead
        # (see pishock_router). Only bools count, and only live writes —
        # an OSCQuery snapshot re-reading a held contact is not an entry.
        self._rises: Dict[str, int] = {}
        # The OSCQuery tree's type tag per parameter ("T"/"F" Bool, "i"
        # Int, "f" Float) -- the Avatar Remote page's controls need to know
        # what to send. A parameter only ever seen live takes its value's.
        self._declared_types: Dict[str, str] = {}
        self.lock = threading.Lock()

    # The OSCQuery tree is rooted at avatar/parameters/* for VRChat avatars,
    # but the UDP handler stores parameters under their short name (the part
    # after /avatar/parameters/). Normalize JSON-dump keys the same way so the
    # initial snapshot and live UDP updates land on identical keys — otherwise
    # the Inspector shows stale duplicates that never refresh.
    _AVATAR_PARAM_PREFIX = "avatar/parameters/"

    # VRCFury Haptics zone params (`VFH/Zone/<cat>/<name>/<contact>`) carry
    # the same wire contract as `OGB/<cat>/<name>/<contact>` — OscGoesBrrr's
    # bridge parses the two forms into identical GameDevices. Normalizing on
    # ingest keeps ONE canonical key shape, so every zone evaluator (the
    # motor router's hot tick, the shared zone_filter_strength) reads only
    # OGB/ prefixes instead of paying a dual-prefix lookup per filter.
    _VFH_ZONE_PREFIX = "VFH/Zone/"

    @classmethod
    def _canon_param_key(cls, address: str) -> str:
        if address.startswith(cls._VFH_ZONE_PREFIX):
            return "OGB/" + address[len(cls._VFH_ZONE_PREFIX):]
        return address

    def _refresh_zone_lists(self) -> None:
        """Rebuild the public zone name lists from `_zone_tuples`."""
        orifices = sorted({n for t, n in self._zone_tuples if t == "Orf"})
        penetrators = sorted({n for t, n in self._zone_tuples if t == "Pen"})
        touch = sorted({n for t, n in self._zone_tuples if t == "Touch"})
        self.detected_zones = {
            "Orifices": orifices, "Penetrators": penetrators, "Touch": touch,
        }

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
            zone = classify_ogb_zone(path)
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
            key = self._canon_param_key(key)
            self.all_parameters[key] = val
            tag = node.get("TYPE")
            if isinstance(tag, str) and tag[:1] in _TYPE_TAGS:
                self._declared_types[key] = tag[:1]

    def set_input_locked(self, locked: bool) -> None:
        """Gate live writes. While locked, update_parameter and
        rebuild_from_json no-op (live OSC is ignored); apply_replay_frame
        still writes. Used by session replay."""
        with self.lock:
            self._input_locked = bool(locked)

    def apply_replay_frame(self, params: Dict[str, Any]) -> None:
        """Replace the OGB parameter set with a reconstructed replay frame,
        bypassing the input lock. `params` is the full OGB-key snapshot at
        one point in a recorded session (already reconstructed from the
        log's snapshot + deltas), so any OGB key absent from it has
        genuinely returned to rest and is dropped — otherwise a contact
        that ended mid-session would latch forever.

        packets_received is bumped so the routers' and stats' stale-signal
        monitors treat replay as a live stream. Non-OGB keys (avatar
        state, etc.) are left untouched — replay only drives contacts."""
        with self.lock:
            # Drop stale OGB keys not in this frame; keep everything else.
            for key in [k for k in self.all_parameters
                        if k.startswith("OGB/") and k not in params]:
                del self.all_parameters[key]
            new_zone = False
            for address, value in params.items():
                address = self._canon_param_key(address)
                if address not in self.all_parameters:
                    zone = classify_ogb_zone(address)
                    if zone is not None and zone not in self._zone_tuples:
                        self._zone_tuples.add(zone)
                        new_zone = True
                self.all_parameters[address] = value
            if new_zone:
                self._refresh_zone_lists()
            self._version += 1
            self.packets_received += 1

    def clear_ogb_params(self) -> None:
        """Drop every OGB-classified param (and its zones). Called when
        replay stops so contacts don't latch at their last replayed
        value."""
        with self.lock:
            for key in [k for k in self.all_parameters if k.startswith("OGB/")]:
                del self.all_parameters[key]
            self._zone_tuples.clear()
            self._refresh_zone_lists()
            self._version += 1

    def rebuild_from_json(self, data: dict) -> int:
        """
        Clears and rebuilds the entire parameter cache from a fresh VRChat OSCQuery JSON.
        Returns the total number of parameters loaded.
        """
        with self.lock:
            if self._input_locked:
                return len(self.all_parameters)
            self.all_parameters.clear()
            self._zone_tuples.clear()
            self._declared_types.clear()
            self._parse_oscquery_node(data)

            for path in self.all_parameters.keys():
                zone = classify_ogb_zone(path)
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
        address = self._canon_param_key(address)
        with self.lock:
            if self._input_locked:
                return  # session replay owns the store; drop live writes
            is_new_key = address not in self.all_parameters
            if value is True and self.all_parameters.get(address) is not True:
                self._rises[address] = self._rises.get(address, 0) + 1
            self.all_parameters[address] = value
            self._version += 1
            self.packets_received += 1
            if is_new_key:
                zone = classify_ogb_zone(address)
                if zone is not None and zone not in self._zone_tuples:
                    self._zone_tuples.add(zone)
                    self._refresh_zone_lists()

    def update_synthetic(self, address: str, value: Any) -> None:
        """A value the APP generates (the input simulator), not one that
        arrived from VRChat. Written like any parameter so routing and the
        inspector see it, but it counts no packet (the OSC liveness pill
        watches that counter), classifies no zone, and ignores the replay
        lock -- it is the user's own action."""
        address = self._canon_param_key(address)
        with self.lock:
            self.all_parameters[address] = value
            self._version += 1

    def remove_synthetic(self, address: str) -> None:
        """Drop a synthetic parameter again (the simulator stopped)."""
        address = self._canon_param_key(address)
        with self.lock:
            if address in self.all_parameters:
                del self.all_parameters[address]
                self._version += 1

    def get_packets_received(self) -> int:
        """Total parameter writes since process start. Used by the watchdog
        to detect 'connected but silent' (VRChat thinks we're alive, no
        packets arriving — typically a multi-OSC-client routing problem)."""
        with self.lock:
            return self.packets_received

    def has_parameters(self, *keys: str) -> Tuple[bool, ...]:
        """Whether each key is in the current avatar's parameters (no copy
        of the whole store) -- e.g. which parts of OGP's menu it carries."""
        with self.lock:
            return tuple(k in self.all_parameters for k in keys)

    def parameter_count(self) -> int:
        with self.lock:
            return len(self.all_parameters)

    def get_param_types(self) -> Dict[str, str]:
        """{name: "Bool" | "Int" | "Float"} for every parameter whose type
        is known: as OSCQuery declared it, else as its live value is."""
        with self.lock:
            out = {}
            for key, value in self.all_parameters.items():
                tag = self._declared_types.get(key)
                if tag is not None:
                    out[key] = _TYPE_TAGS[tag]
                elif isinstance(value, bool):
                    out[key] = "Bool"
                elif isinstance(value, int):
                    out[key] = "Int"
                elif isinstance(value, float):
                    out[key] = "Float"
            return out

    def get_values(self, names) -> Dict[str, Any]:
        """The current values of `names` (those the store has)."""
        with self.lock:
            params = self.all_parameters
            return {n: params[n] for n in names if n in params}

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

    def read_watched(self, keys) -> Tuple[Dict[str, Any], Dict[str, int]]:
        """`(values, rise_counts)` for just `keys`, under one lock hold.
        Keys never seen are absent from `values` and count 0 rises. For a
        router that watches a handful of parameters and would rather not
        copy the whole table every tick."""
        with self.lock:
            params = self.all_parameters
            rises = self._rises
            return ({k: params[k] for k in keys if k in params},
                    {k: rises.get(k, 0) for k in keys})

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
                "Penetrators": list(self.detected_zones["Penetrators"]),
                "Touch": list(self.detected_zones.get("Touch", [])),
            }


# Global Singleton instance to be imported by other modules
store = ParameterStore()
