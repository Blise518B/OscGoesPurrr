"""Synthetic SPS sources facade mixin.

The UI builds / edits user-defined synthetic SPS sources only through these
methods, and the routers read the live source map through
`_get_sps_source_map`. The persisted registry lives on
`self.profile_manager.sps_sources` (a SpsSourceManager); the evaluation
math lives in sps_source.py.
"""

from typing import Any, Dict, List, Optional, Sequence, Tuple

from parameter_store import store
from sps_source import evaluate_sps_source
from zone_strength import zone_filter_strength


class SpsSourcesFacade:
    """Mixin: synthetic-SPS-source controller methods. Composed into
    OscGoesPurrrApp. Assumes the host has `self.profile_manager`."""

    # ------------------------------------------------------------------
    # Router-facing getter
    # ------------------------------------------------------------------

    def _get_sps_source_map(self) -> Dict[str, Dict[str, Any]]:
        """`name -> definition` of every ENABLED source. Passed into the
        motor and bHaptics routers each tick so a selected synthetic source
        name resolves to a live value."""
        return self.profile_manager.sps_sources.get_source_map(enabled_only=True)

    # ------------------------------------------------------------------
    # UI-facing reads
    # ------------------------------------------------------------------

    def get_sps_sources(self) -> List[Dict[str, Any]]:
        """Every stored source definition (copies), for the editor view."""
        return self.profile_manager.sps_sources.list_sources()

    def get_sps_source_names_flat(self) -> List[str]:
        """Flat list of all source names — for the Device Routing picker's
        'Custom Sources' section."""
        return [s["name"] for s in self.profile_manager.sps_sources.list_sources()
                if s.get("name")]

    def get_sps_source_names_by_type(self) -> Dict[str, List[str]]:
        """Names grouped as {"Orifices": [...], "Penetrators": [...]},
        mirroring get_detected_zones() so the bHaptics Cross-Routing picker
        can slot synthetic sources alongside auto-detected zones."""
        out: Dict[str, List[str]] = {"Orifices": [], "Penetrators": []}
        for s in self.profile_manager.sps_sources.list_sources():
            name = s.get("name")
            if not name:
                continue
            key = "Penetrators" if s.get("zone_type") == "Pen" else "Orifices"
            out[key].append(name)
        return out

    def get_sps_source_values(self) -> Dict[str, float]:
        """Evaluate every source against the current parameter snapshot —
        for the editor's live readout. Includes disabled sources so the
        user can see what a source *would* emit before enabling it."""
        params, _version, _zones = store.snapshot()
        out: Dict[str, float] = {}
        for s in self.profile_manager.sps_sources.list_sources():
            name = s.get("name")
            if name:
                out[name] = evaluate_sps_source(s, params)
        return out

    def get_live_zone_strengths(
        self,
        specs: Sequence[Tuple[Any, Any, Optional[List[str]]]],
    ) -> List[float]:
        """Evaluate a batch of `(zone_name, zone_type, filters)` specs
        against ONE parameter snapshot and return their 0..1 strengths.
        Same math the OWO / PiShock / Coyote / bHaptics routers run per
        tick (`zone_strength.zone_filter_strength`), exposed read-only so
        the backend views can paint live activity rings on their cards.
        Batch shape on purpose: one snapshot per UI tick, not per card."""
        if not specs:
            return []
        params = store.get_all_parameters() or {}
        sps = self._get_sps_source_map()
        out: List[float] = []
        for zone_name, zone_type, filters in specs:
            try:
                out.append(zone_filter_strength(
                    zone_name, zone_type, filters or [], params, sps))
            except Exception:
                out.append(0.0)
        return out

    # ------------------------------------------------------------------
    # UI-facing writes
    # ------------------------------------------------------------------

    def add_or_update_sps_source(self, defn: Dict[str, Any]) -> Optional[str]:
        name = self.profile_manager.sps_sources.add_or_update_source(defn)
        self._sps_sources_changed()
        return name

    def delete_sps_source(self, name: str) -> bool:
        ok = self.profile_manager.sps_sources.delete_source(name)
        if ok:
            self._sps_sources_changed()
        return ok

    def rename_sps_source(self, old: str, new: str) -> bool:
        ok = self.profile_manager.sps_sources.rename_source(old, new)
        if ok:
            self._sps_sources_changed()
        return ok

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _sps_sources_changed(self) -> None:
        """Push the new source map into the live routing immediately. The
        routers re-read the map every tick anyway, but a forced recalc
        means an edit applies without waiting for the next OSC packet."""
        recalc = getattr(self, "force_recalculate", None)
        if callable(recalc):
            try:
                recalc()
            except Exception:
                pass
