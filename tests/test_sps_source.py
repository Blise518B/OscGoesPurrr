"""Tests for synthetic SPS sources.

Covers the pure evaluator (`sps_source.evaluate_sps_source`), the record
normaliser, the storage registry (`SpsSourceManager`), and end-to-end
resolution through both routers (motor + bHaptics).
"""

import pytest

from sps_source import evaluate_sps_source, normalize_source_def


# ============================================================ evaluator

def _src(**kw):
    """Build a source def, defaulting the structural fields so each test
    only specifies what it exercises."""
    base = {
        "name": "S", "zone_type": "Orf",
        "proximity": [], "activation": [], "velocity": [],
        "multiplier": 1.0, "max_value": 1.0, "enabled": True,
    }
    base.update(kw)
    return base


class TestEvaluator:
    def test_plain_proximity_passes_through(self):
        defn = _src(proximity=["p"])
        assert evaluate_sps_source(defn, {"p": 0.6}) == pytest.approx(0.6)

    def test_missing_proximity_is_silent(self):
        # No proximity param present => 0, even with the gate open.
        defn = _src(proximity=["p"], activation=["g"])
        assert evaluate_sps_source(defn, {"g": True}) == 0.0

    def test_multiple_proximity_max_wins(self):
        defn = _src(proximity=["a", "b"])
        assert evaluate_sps_source(defn, {"a": 0.3, "b": 0.7}) == pytest.approx(0.7)

    def test_activation_gate_blocks_when_none_firing(self):
        defn = _src(proximity=["p"], activation=["g"])
        assert evaluate_sps_source(defn, {"p": 0.9, "g": False}) == 0.0

    def test_activation_gate_or_semantics(self):
        # Any one activation firing opens the gate.
        defn = _src(proximity=["p"], activation=["g1", "g2"])
        assert evaluate_sps_source(defn, {"p": 0.5, "g1": False, "g2": True}) \
            == pytest.approx(0.5)

    def test_empty_activation_is_always_open(self):
        defn = _src(proximity=["p"], activation=[])
        assert evaluate_sps_source(defn, {"p": 0.5}) == pytest.approx(0.5)

    def test_max_value_clamps_raw_proximity(self):
        defn = _src(proximity=["p"], max_value=0.5)
        assert evaluate_sps_source(defn, {"p": 0.9}) == pytest.approx(0.5)

    def test_velocity_multiplier_applies_when_firing(self):
        defn = _src(proximity=["p"], velocity=["v"], multiplier=2.0)
        assert evaluate_sps_source(defn, {"p": 0.4, "v": True}) == pytest.approx(0.8)

    def test_velocity_multiplier_skipped_when_not_firing(self):
        defn = _src(proximity=["p"], velocity=["v"], multiplier=2.0)
        assert evaluate_sps_source(defn, {"p": 0.4, "v": False}) == pytest.approx(0.4)

    def test_multiplier_clamps_final_to_one(self):
        defn = _src(proximity=["p"], velocity=["v"], multiplier=3.0)
        assert evaluate_sps_source(defn, {"p": 0.8, "v": True}) == pytest.approx(1.0)

    def test_clamp_happens_before_multiplier(self):
        # max_value caps raw proximity (0.4), THEN ×2 = 0.8 — not 0.9×2.
        defn = _src(proximity=["p"], max_value=0.4, velocity=["v"], multiplier=2.0)
        assert evaluate_sps_source(defn, {"p": 0.9, "v": True}) == pytest.approx(0.8)

    def test_normalizes_0_255_range(self):
        defn = _src(proximity=["p"])
        assert evaluate_sps_source(defn, {"p": 255}) == pytest.approx(1.0)

    def test_malformed_def_is_zero(self):
        assert evaluate_sps_source(None, {"p": 1.0}) == 0.0
        assert evaluate_sps_source("nope", {"p": 1.0}) == 0.0


# ============================================================ normaliser

class TestNormalize:
    def test_strips_prefix_and_dedupes(self):
        out = normalize_source_def({
            "name": " G ",
            "proximity": ["/avatar/parameters/p", "p", "q"],
        })
        assert out["name"] == "G"
        assert out["proximity"] == ["p", "q"]

    def test_string_contact_becomes_list(self):
        out = normalize_source_def({"name": "G", "activation": "g"})
        assert out["activation"] == ["g"]

    def test_clamps_numerics_and_validates_type(self):
        out = normalize_source_def({
            "name": "G", "zone_type": "bogus",
            "max_value": 5.0, "multiplier": -2.0,
        })
        assert out["zone_type"] == "Orf"
        assert out["max_value"] == 1.0
        assert out["multiplier"] == 0.0

    def test_zone_type_pen_preserved(self):
        assert normalize_source_def({"name": "G", "zone_type": "Pen"})["zone_type"] == "Pen"

    def test_enabled_defaults_true(self):
        assert normalize_source_def({"name": "G"})["enabled"] is True


# ============================================================ registry

class TestSpsSourceManager:
    @pytest.fixture
    def manager(self, tmp_path, monkeypatch):
        import settings.sps_sources as sps_mod
        monkeypatch.setattr(sps_mod, "SPS_SOURCES_FILE", tmp_path / "sps_sources.json")
        return sps_mod.SpsSourceManager()

    def test_starts_empty(self, manager):
        assert manager.list_sources() == []

    def test_add_normalises_and_persists(self, manager, tmp_path, monkeypatch):
        manager.add_or_update_source({
            "name": "A",
            "proximity": ["/avatar/parameters/p"],
            "max_value": 2.0, "multiplier": -1.0,
        })
        src = manager.get_source("A")
        assert src["proximity"] == ["p"]
        assert src["max_value"] == 1.0
        assert src["multiplier"] == 0.0

        # A fresh manager reads the same file back.
        import settings.sps_sources as sps_mod
        reloaded = sps_mod.SpsSourceManager()
        assert reloaded.get_source("A") is not None

    def test_blank_name_rejected(self, manager):
        assert manager.add_or_update_source({"name": "   "}) is None
        assert manager.list_sources() == []

    def test_update_replaces_by_name(self, manager):
        manager.add_or_update_source({"name": "A", "max_value": 0.5})
        manager.add_or_update_source({"name": "A", "max_value": 0.9})
        assert len(manager.list_sources()) == 1
        assert manager.get_source("A")["max_value"] == 0.9

    def test_source_map_excludes_disabled(self, manager):
        manager.add_or_update_source({"name": "On", "enabled": True})
        manager.add_or_update_source({"name": "Off", "enabled": False})
        enabled = manager.get_source_map(enabled_only=True)
        assert "On" in enabled and "Off" not in enabled
        assert "Off" in manager.get_source_map(enabled_only=False)

    def test_rename_and_delete(self, manager):
        manager.add_or_update_source({"name": "A"})
        assert manager.rename_source("A", "B") is True
        assert manager.get_source("A") is None
        assert manager.get_source("B") is not None
        assert manager.delete_source("B") is True
        assert manager.list_sources() == []

    def test_rename_collision_rejected(self, manager):
        manager.add_or_update_source({"name": "A"})
        manager.add_or_update_source({"name": "B"})
        assert manager.rename_source("A", "B") is False


# ============================================================ router resolution

class TestMotorRouterResolution:
    def _profile(self, zones="G"):
        return {"Toy": {"motor_count": 1, "motor_0_zones": zones}}

    def _value(self, updates, device="Toy", motor=0):
        for d, v, m in updates:
            if d == device and m == motor:
                return v
        return None

    def test_selected_source_drives_motor(self, router):
        sources = {"G": _src(proximity=["C/prox"])}
        updates = router.reevaluate_state(
            self._profile("G"), {"C/prox": 0.6}, zones=set(), sps_sources=sources
        )
        assert self._value(updates) == pytest.approx(0.6)

    def test_unselected_source_contributes_nothing(self, router):
        sources = {"G": _src(proximity=["C/prox"])}
        updates = router.reevaluate_state(
            self._profile("SomethingElse"), {"C/prox": 0.6},
            zones=set(), sps_sources=sources,
        )
        # The motor selected a name that resolves to neither a zone nor a
        # source, so it emits 0 (no update, or an update of 0.0).
        assert (self._value(updates) or 0.0) == 0.0

    def test_activation_gate_through_router(self, router):
        sources = {"G": _src(proximity=["C/prox"], activation=["C/gate"])}
        params = {"C/prox": 0.6, "C/gate": False}
        updates = router.reevaluate_state(
            self._profile("G"), params, zones=set(), sps_sources=sources
        )
        assert (self._value(updates) or 0.0) == 0.0

    def test_no_source_map_is_safe(self, router):
        # sps_sources=None (default) must not raise and yields no synthetic
        # contribution.
        updates = router.reevaluate_state(
            self._profile("G"), {"C/prox": 0.6}, zones=set()
        )
        assert (self._value(updates) or 0.0) == 0.0


class TestBHapticsResolution:
    def test_entry_resolves_synthetic_source_ignoring_filters(self):
        from bhaptics_router import _sps_entry_strength
        # An entry with no filters would normally score 0; a synthetic
        # source short-circuits that and returns its evaluated value.
        entry = {"ogb_zone": "G", "filters": []}
        sources = {"G": _src(proximity=["C/prox"])}
        assert _sps_entry_strength(entry, {"C/prox": 0.5}, sources) == pytest.approx(0.5)

    def test_compute_mirror_dots_uses_source(self):
        from bhaptics_router import compute_sps_mirror_dots
        cfg = {
            "enabled": True,
            "entries": [{
                "name": "m", "ogb_zone": "G", "filters": [],
                "position": "VestFront", "dot_indices": [5],
                "gain": 1.0, "threshold": 0.0,
            }],
        }
        sources = {"G": _src(proximity=["C/prox"])}
        out = compute_sps_mirror_dots(
            cfg, {"C/prox": 0.5}, enabled_positions={"VestFront"},
            sps_sources=sources,
        )
        assert out.get("VestFront", {}).get(5) == pytest.approx(0.5)
