"""Touch / Penetration x Self / Others -- the contact 2x2 every chain
carries (friends' reviews, 2026-11-14).

What it promises:
* the old two pairs (Touch / Penetration, Self / Others) turn into the four
  switches once, at load, and every chain keeps hearing exactly what it
  heard -- touch-self = touch AND self, and so on;
* the router reads each (kind, source) pair on its own, so a chain can take
  touch from you but penetration only from others -- which the old pairs
  could not say;
* a typed chain answers only its own kind's two switches.
"""

import json

import pytest

import config_manager
import contact_filters as cf
from config_manager import ModeManager, is_routing_key
from motor_router import MotorRouter


# ------------------------------------------------------------- the module

class TestPairsAndTypes:
    def test_four_pairs_and_their_defaults(self):
        assert cf.PAIRS == ("touch_self", "touch_others",
                            "pen_self", "pen_others")
        # The old defaults: Touch and Penetration on, Self off, Others on.
        assert cf.DEFAULTS == cf.pairs_from_legacy(True, True, False, True)

    def test_a_pair_is_on_when_its_kind_and_its_source_were(self):
        assert cf.pairs_from_legacy(True, False, True, True) == {
            "touch_self": True, "touch_others": True,
            "pen_self": False, "pen_others": False}
        assert cf.pairs_from_legacy(True, True, False, True) == {
            "touch_self": False, "touch_others": True,
            "pen_self": False, "pen_others": True}

    @pytest.mark.parametrize("ctype, pairs", [
        ("touch", ("touch_self", "touch_others")),
        ("penetration", ("pen_self", "pen_others")),
        ("custom", cf.PAIRS),
        ("", cf.PAIRS),
        ("nonsense", cf.PAIRS),
    ])
    def test_a_typed_chain_answers_only_its_own_kind(self, ctype, pairs):
        assert cf.pairs_for_type(ctype) == pairs

    def test_routing_keys_stay_per_mode(self):
        for chain in (None, 0, 3):
            for pair in cf.PAIRS:
                assert is_routing_key(cf.key(0, chain, pair))
        assert cf.key(1, 2, "pen_self") == "motor_1_c2_pen_self"
        assert cf.key(1, None, "pen_self") == "motor_1_pen_self"

    def test_resolve_chain_then_motor_then_default(self):
        cfg = {}
        get = cfg.get
        assert cf.resolve(get, 0, 1, "touch_self") is False       # default
        cfg["motor_0_touch_self"] = True
        assert cf.resolve(get, 0, 1, "touch_self") is True        # motor's
        cfg["motor_0_c1_touch_self"] = False
        assert cf.resolve(get, 0, 1, "touch_self") is False       # chain's
        assert cf.resolve(get, 0, 0, "touch_self") is True        # sibling


class TestChipState:
    def test_all_on_all_off_and_half(self):
        assert cf.chip_state([True, True]) == "on"
        assert cf.chip_state([False]) == "off"
        assert cf.chip_state([True, False, True]) == "half"

    def test_no_chain_answering_means_no_state(self):
        assert cf.chip_state([]) is None


# ---------------------------------------------------------- the migration

def _hears(per_dev, motor, chain, ctype):
    """What a chain hears after migration, read as the router does."""
    router = MotorRouter()
    return router._chain_filters(per_dev, motor, chain, ctype)[:4]


def _heard_before(old, motor, chain, ctype):
    """What the chain heard under the old two pairs: its key, the motor's,
    the old default; a typed chain took its own kind from its type."""
    def val(s, d):
        for k in (f"motor_{motor}_c{chain}_{s}", f"motor_{motor}_{s}"):
            if k in old:
                return bool(old[k])
        return d
    touch, pen = val("touch", True), val("pen", True)
    if ctype == "touch":
        touch, pen = True, False
    elif ctype == "penetration":
        touch, pen = False, True
    s, o = val("self", False), val("others", True)
    return (touch and s, touch and o, pen and s, pen and o)


class TestMigration:
    def test_nothing_old_is_left_alone(self):
        per_dev = {"motor_0_zones": "All SPS", "motor_0_touch_self": True}
        before = dict(per_dev)
        assert cf.migrate_routing(per_dev, {0: ["penetration", "touch"]}) is False
        assert per_dev == before

    def test_motor_level_pairs_become_the_motors_2x2(self):
        per_dev = {"motor_0_zones": "Mouth", "motor_0_self": True,
                   "motor_0_pen": False}
        assert cf.migrate_routing(per_dev, {}) is True
        assert per_dev == {
            "motor_0_zones": "Mouth",
            "motor_0_touch_self": True, "motor_0_touch_others": True,
            "motor_0_pen_self": False, "motor_0_pen_others": False,
        }

    def test_old_keys_are_dropped_and_it_is_idempotent(self):
        per_dev = {"motor_0_c1_others": False, "motor_0_touch": True}
        cf.migrate_routing(per_dev, {0: ["penetration", "touch"]})
        assert not any(k.endswith(("_touch", "_pen", "_self", "_others"))
                       and not k.endswith(tuple("_" + p for p in cf.PAIRS))
                       for k in per_dev)
        after = dict(per_dev)
        assert cf.migrate_routing(per_dev, {0: ["penetration", "touch"]}) is False
        assert per_dev == after

    @pytest.mark.parametrize("old", [
        {},
        {"motor_0_self": True},
        {"motor_0_others": False},
        {"motor_0_touch": False},
        {"motor_0_pen": False, "motor_0_self": True},
        {"motor_0_c1_others": False},
        {"motor_0_c0_self": True, "motor_0_others": False},
        {"motor_0_c0_touch": False, "motor_0_c1_pen": False},
        {"motor_0_touch": False, "motor_0_c1_self": True},
        {"motor_0_c2_pen": False, "motor_0_c2_self": True},
    ])
    @pytest.mark.parametrize("types", [
        ["penetration", "touch"],
        ["custom"],
        ["custom", "touch", "penetration"],
        [],
    ])
    def test_every_chain_hears_what_it_heard(self, old, types):
        """Lossless where it counts: the router hears the same contact on
        every chain, typed or custom, before and after."""
        per_dev = dict(old)
        cf.migrate_routing(per_dev, {0: types} if types else {})
        chains = max(len(types), 3)
        for chain in range(chains):
            ctype = types[chain] if chain < len(types) else "custom"
            assert _hears(per_dev, 0, chain, ctype) == \
                _heard_before(old, 0, chain, ctype), (old, types, chain)

    def test_a_typed_chain_keeps_its_own_kind_even_if_stored_off(self):
        """A Touch chain ignored a stored Touch-off (its type decided), so
        it still hears touch afterwards."""
        per_dev = {"motor_0_touch": False, "motor_0_self": True}
        cf.migrate_routing(per_dev, {0: ["touch"]})
        assert _hears(per_dev, 0, 0, "touch") == (True, True, False, False)

    def test_a_new_chain_added_later_still_follows_the_motor(self):
        per_dev = {"motor_0_self": True}
        cf.migrate_routing(per_dev, {0: ["custom"]})
        # Chain 4 never existed at migration time: the motor's 2x2.
        assert _hears(per_dev, 0, 4, "custom") == (True, True, True, True)

    def test_a_scope_that_already_has_the_2x2_keeps_it(self):
        per_dev = {"motor_0_c0_touch_self": True, "motor_0_c0_self": False}
        cf.migrate_routing(per_dev, {0: ["custom"]})
        assert per_dev["motor_0_c0_touch_self"] is True
        assert "motor_0_c0_self" not in per_dev

    def test_chain_types_from_feel(self):
        feel = {"0": {"chains": [{"type": "penetration"}, {"type": "touch"}]},
                "1": {"chains": [{}]}, "x": {}, "2": "junk"}
        assert cf.chain_types_from_feel(feel) == {
            0: ["penetration", "touch"], 1: [""]}
        assert cf.chain_types_from_feel(None) == {}


# ---------------------------------------------------- ModeManager at load

class _StubSettings:
    def __init__(self, *a, **kw):
        self.settings = {}

    def get(self, key, default=None):
        return self.settings.get(key, default)

    def set(self, key, value):
        self.settings[key] = value


class _StubKnownDevices:
    def __init__(self, *a, **kw):
        self.devices = {}

    def register(self, name, motor_count, motor_kinds=None):
        self.devices[name] = {"motor_count": motor_count}
        return True

    def all(self):
        return dict(self.devices)


@pytest.fixture
def isolated(monkeypatch, tmp_path):
    monkeypatch.setattr(config_manager, "MODES_FILE", tmp_path / "modes.json")
    for name in ("AppSettingsManager", "SpsSourceManager"):
        monkeypatch.setattr(config_manager, name, _StubSettings)
    monkeypatch.setattr(config_manager, "KnownDevicesRegistry",
                        _StubKnownDevices)
    return tmp_path


def _old_modes_json():
    return {
        "schema": 4,
        "wiring": {"Toy": {"motor_count": 1}},
        "feel": {"Toy": {"0": {"chains": [{"type": "penetration"},
                                          {"type": "touch"}],
                               "merge": "max"}}},
        "modes": [
            {"name": "Combined", "icon": "x",
             "routing": {"Toy": {"motor_0_self": True,
                                 "motor_0_c1_others": False,
                                 "osc_addresses": {}}}},
            {"name": "Separate", "icon": "y",
             "routing": {"Toy": {"motor_0_pen": False}}},
        ],
        "active_mode": 0,
    }


class TestModeManagerMigratesOnLoad:
    def test_every_mode_is_migrated_and_saved_once_with_a_copy(self, isolated):
        path = isolated / "modes.json"
        path.write_text(json.dumps(_old_modes_json()), "utf-8")
        mm = ModeManager()
        r0 = mm.modes[0]["routing"]["Toy"]
        r1 = mm.modes[1]["routing"]["Toy"]
        assert "motor_0_self" not in r0 and "motor_0_pen" not in r1
        # Combined: self on for the motor, chain 1 (touch) ignores others.
        assert r0["motor_0_touch_self"] is True
        assert r0["motor_0_c1_touch_others"] is False
        # Separate: penetration was off -- but chain 0 is a Penetration
        # chain, which never read that switch, so it still hears it.
        assert r1["motor_0_pen_others"] is False
        assert r1["motor_0_c0_pen_others"] is True
        # Saved, and the old file kept beside it.
        saved = json.loads(path.read_text("utf-8"))
        assert "motor_0_self" not in saved["modes"][0]["routing"]["Toy"]
        copies = list(isolated.glob("modes.json.before-contact-2x2-*.bak"))
        assert len(copies) == 1
        assert "motor_0_self" in copies[0].read_text("utf-8")
        # The next launch has nothing left to do: no second copy.
        ModeManager()
        assert len(list(isolated.glob("modes.json.before-contact-2x2-*.bak"))) == 1

    def test_the_active_view_carries_the_2x2(self, isolated):
        (isolated / "modes.json").write_text(json.dumps(_old_modes_json()), "utf-8")
        mm = ModeManager()
        view = mm.get_active_profile_dict()["Toy"]
        assert view["motor_0_touch_self"] is True
        assert "motor_0_self" not in view


# ------------------------------------------------------------- the router

def _cfg(**pairs):
    """A motor's 2x2, all off but what the test switches on."""
    cfg = {f"motor_0_{p}": False for p in cf.PAIRS}
    cfg.update({f"motor_0_{p}": v for p, v in pairs.items()})
    return cfg


# One socket with all four kinds of contact at once, each a different
# level, so the level heard says which pair let it through.
LEGACY = {
    "OGB/Orf/Z/TouchSelfClose": True, "OGB/Orf/Z/TouchSelf": 0.2,
    "OGB/Orf/Z/TouchOthersClose": True, "OGB/Orf/Z/TouchOthers": 0.4,
    "OGB/Orf/Z/PenSelf": 0.6,
    "OGB/Orf/Z/PenOthersClose": True, "OGB/Orf/Z/PenOthers": 0.8,
}
SPS3 = {
    "OGB/Orf/Z/DepthRadius": 0.5,           # marks the zone as SPS 3
    "OGB/Orf/Z/TouchSelf": 0.2, "OGB/Orf/Z/TouchOthers": 0.4,
}
TOUCH_ZONE = {"OGB/Touch/H/Self": 0.3, "OGB/Touch/H/Others": 0.7}


class TestRouterHearsEachPairAlone:
    @pytest.mark.parametrize("pair, level", [
        ("touch_self", 0.2), ("touch_others", 0.4),
        ("pen_self", 0.6), ("pen_others", 0.8),
    ])
    def test_one_pair_on_hears_only_that_contact(self, pair, level):
        out = MotorRouter()._zone_contribution(
            "Orf", "Z", _cfg(**{pair: True}), 0, LEGACY)
        assert out == pytest.approx(level)

    def test_nothing_on_hears_nothing(self):
        assert MotorRouter()._zone_contribution("Orf", "Z", _cfg(), 0, LEGACY) == 0.0

    def test_touch_from_me_but_penetration_only_from_others(self):
        """The case the old two pairs could not say."""
        cfg = _cfg(touch_self=True, pen_others=True)
        router = MotorRouter()
        only = {k: v for k, v in LEGACY.items() if "PenOthers" not in k}
        # Your own penetration (0.6) is not heard, your own touch is.
        assert router._zone_contribution("Orf", "Z", cfg, 0, only) == \
            pytest.approx(0.2)
        assert router._zone_contribution("Orf", "Z", cfg, 0, LEGACY) == \
            pytest.approx(0.8)

    @pytest.mark.parametrize("pair, level", [
        ("touch_self", 0.2), ("touch_others", 0.4),
    ])
    def test_sps3_touch_pairs(self, pair, level):
        level_out, _speed = MotorRouter()._zone_level_and_speed(
            "Orf", "Z", _cfg(**{pair: True}), 0, SPS3)
        assert level_out == pytest.approx(level)

    @pytest.mark.parametrize("pair, level", [
        ("touch_self", 0.3), ("touch_others", 0.7),
        ("pen_self", 0.0), ("pen_others", 0.0),
    ])
    def test_touch_zones_answer_the_touch_pairs_only(self, pair, level):
        out = MotorRouter()._zone_contribution(
            "Touch", "H", _cfg(**{pair: True}), 0, TOUCH_ZONE)
        assert out == pytest.approx(level)


class TestTypedChainsReadOnlyTheirOwnPairs:
    def test_a_touch_chain_ignores_the_penetration_pairs(self):
        cfg = _cfg(touch_others=True, pen_self=True, pen_others=True)
        assert MotorRouter()._chain_filters(cfg, 0, 0, "touch") == \
            (False, True, False, False, True, False)

    def test_a_penetration_chain_ignores_the_touch_pairs(self):
        cfg = _cfg(touch_self=True, touch_others=True, pen_self=True)
        assert MotorRouter()._chain_filters(cfg, 0, 0, "penetration") == \
            (False, False, True, False, False, True)

    def test_a_custom_chain_reads_all_four(self):
        cfg = _cfg(touch_self=True, pen_others=True)
        assert MotorRouter()._chain_filters(cfg, 0, 0, "custom") == \
            (True, False, False, True, True, True)

    def test_a_chains_own_key_wins_over_the_motors(self):
        cfg = _cfg(touch_others=True)
        cfg["motor_0_c1_touch_others"] = False
        router = MotorRouter()
        assert router._chain_filters(cfg, 0, 0, "touch")[1] is True
        assert router._chain_filters(cfg, 0, 1, "touch")[1] is False

    def test_nothing_stored_means_the_defaults(self):
        assert MotorRouter()._chain_filters({}, 0, 0, "custom")[:4] == \
            tuple(cf.DEFAULTS[p] for p in cf.PAIRS)
