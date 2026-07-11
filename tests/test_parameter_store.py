"""Tests for the ParameterStore (parameter_store.py) — the single source of
truth every router reads. Previously the one load-bearing module with zero
coverage. Fresh instances are constructed per test; the global singleton is
never touched.
"""

import pytest

from parameter_store import ParameterStore


def _oscquery_tree():
    """A miniature VRChat OSCQuery dump: nested CONTENTS, VALUE lists, the
    avatar/parameters/ prefix on parameter leaves, plus an OGB zone."""
    return {
        "CONTENTS": {
            "avatar": {
                "CONTENTS": {
                    "parameters": {
                        "CONTENTS": {
                            "Volume": {"VALUE": [0.25]},
                            "Seated": {"VALUE": [True]},
                            "OGB": {
                                "CONTENTS": {
                                    "Orf": {
                                        "CONTENTS": {
                                            "Booty": {
                                                "CONTENTS": {
                                                    "TouchSelf": {"VALUE": [0.5]},
                                                },
                                            },
                                        },
                                    },
                                },
                            },
                            "NoValue": {},          # leaf without VALUE
                        },
                    },
                    "change": {"VALUE": ["avtr_x"]},
                },
            },
        },
    }


class TestRebuildFromJson:
    def test_flattens_and_strips_avatar_prefix(self):
        s = ParameterStore()
        count = s.rebuild_from_json(_oscquery_tree())
        params = s.get_all_parameters()
        # Parameter leaves land under their BARE names — the same keys the
        # UDP handler writes — never the avatar/parameters/ prefixed form.
        assert params["Volume"] == 0.25
        assert params["Seated"] is True
        assert params["OGB/Orf/Booty/TouchSelf"] == 0.5
        assert "avatar/parameters/Volume" not in params
        assert count == len(params)

    def test_leaf_without_value_defaults_to_zero(self):
        s = ParameterStore()
        s.rebuild_from_json(_oscquery_tree())
        assert s.get_all_parameters()["NoValue"] == 0.0

    def test_detects_ogb_zones(self):
        s = ParameterStore()
        s.rebuild_from_json(_oscquery_tree())
        assert ("Orf", "Booty") in s.get_zone_tuples()
        assert s.get_detected_zones()["Orifices"] == ["Booty"]

    def test_rebuild_clears_previous_state(self):
        s = ParameterStore()
        s.update_parameter("OGB/Pen/Shaft/PenSelf", 0.9)
        s.rebuild_from_json(_oscquery_tree())
        params = s.get_all_parameters()
        assert "OGB/Pen/Shaft/PenSelf" not in params
        assert ("Pen", "Shaft") not in s.get_zone_tuples()

    def test_rebuild_bumps_version_but_not_packet_counter(self):
        s = ParameterStore()
        v0 = s.get_version()
        s.rebuild_from_json(_oscquery_tree())
        assert s.get_version() > v0
        # packets_received tracks live UDP traffic only — the stale-signal
        # cutoffs key off it, so a snapshot refetch must not look like
        # VRChat talking.
        assert s.get_packets_received() == 0


class TestUpdateParameter:
    def test_write_and_counters(self):
        s = ParameterStore()
        v0 = s.get_version()
        s.update_parameter("Volume", 0.7)
        assert s.get_all_parameters()["Volume"] == 0.7
        assert s.get_version() == v0 + 1
        assert s.get_packets_received() == 1
        s.update_parameter("Volume", 0.8)
        assert s.get_packets_received() == 2

    def test_new_ogb_key_registers_zone_incrementally(self):
        s = ParameterStore()
        s.update_parameter("OGB/Orf/Booty/TouchSelf", 0.4)
        assert ("Orf", "Booty") in s.get_zone_tuples()
        assert s.get_detected_zones()["Orifices"] == ["Booty"]
        # A repeat write to the same key must not duplicate the zone.
        s.update_parameter("OGB/Orf/Booty/TouchSelf", 0.6)
        assert s.get_detected_zones()["Orifices"] == ["Booty"]

    def test_non_ogb_key_adds_no_zone(self):
        s = ParameterStore()
        s.update_parameter("Volume", 1.0)
        assert s.get_zone_tuples() == set()

    def test_touch_zone_detected_from_both_wire_forms(self):
        s = ParameterStore()
        s.update_parameter("OGB/Touch/Head/Others", 0.4)
        s.update_parameter("VFH/Zone/Touch/Ears/Self", 0.2)
        assert ("Touch", "Head") in s.get_zone_tuples()
        assert ("Touch", "Ears") in s.get_zone_tuples()
        assert s.get_detected_zones()["Touch"] == ["Ears", "Head"]
        # The Orf/Pen lists stay untouched.
        assert s.get_detected_zones()["Orifices"] == []

    def test_vfh_keys_normalize_to_ogb_on_ingest(self):
        # VFH/Zone/<cat>/<name>/<contact> is the same wire contract as
        # OGB/<cat>/<name>/<contact>; the store keeps ONE canonical form
        # so every zone evaluator (which reads OGB/ prefixes on the hot
        # tick) can route VFH-form zones. A VFH-detected zone that no
        # evaluator could read would be a silent dead zone.
        s = ParameterStore()
        s.update_parameter("VFH/Zone/Orf/Boob/PenOthers", 0.8)
        params = s.get_all_parameters()
        assert params["OGB/Orf/Boob/PenOthers"] == 0.8
        assert "VFH/Zone/Orf/Boob/PenOthers" not in params
        assert ("Orf", "Boob") in s.get_zone_tuples()
        # Both forms land on the same key — latest write wins.
        s.update_parameter("OGB/Orf/Boob/PenOthers", 0.3)
        assert s.get_all_parameters()["OGB/Orf/Boob/PenOthers"] == 0.3


class TestSnapshotSemantics:
    def test_snapshot_returns_coherent_triple(self):
        s = ParameterStore()
        s.update_parameter("OGB/Pen/Shaft/PenOthers", 0.3)
        params, version, zones = s.snapshot()
        assert params["OGB/Pen/Shaft/PenOthers"] == 0.3
        assert version == s.get_version()
        assert ("Pen", "Shaft") in zones

    def test_returned_copies_do_not_alias_store_state(self):
        s = ParameterStore()
        s.update_parameter("Volume", 0.5)
        params, _, zones = s.snapshot()
        params["Injected"] = 1.0
        zones.add(("Orf", "Fake"))
        assert "Injected" not in s.get_all_parameters()
        assert ("Orf", "Fake") not in s.get_zone_tuples()
        detected = s.get_detected_zones()
        detected["Orifices"].append("Fake")
        assert "Fake" not in s.get_detected_zones()["Orifices"]


class TestZoneTupleRecovery:
    def test_ensure_zone_tuples_rederives_from_params(self):
        # The belt-and-suspenders path: params populated but the zone set
        # empty (e.g. a rebuild that raised mid-parse). Any zone getter
        # must recover the tuples from the parameter cache.
        s = ParameterStore()
        with s.lock:
            s.all_parameters["OGB/Orf/Booty/TouchSelf"] = 0.5
        assert ("Orf", "Booty") in s.get_zone_tuples()
        assert s.get_detected_zones()["Orifices"] == ["Booty"]
