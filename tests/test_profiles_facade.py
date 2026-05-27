"""Tests for ProfilesFacade's motor_kinds refresh logic.

The facade is normally composed into OscGoesPurrrApp via multiple
inheritance. These tests instantiate it standalone with a minimal
stub class that only provides the attributes the refresh paths
touch (`profile_manager`, `log_message`). We test:

* `_seed_profile_with_known_devices` adds new toys to a profile.
* It refreshes motor_count + motor_kinds on EXISTING entries when
  the live known_devices cache disagrees (the Cut-followup fix
  for the Lovense Max pump label).
* It does NOT touch user-config fields (zones, OSC) on existing
  entries.
* `_refresh_avatar_profile_motor_facts` walks avatar profiles and
  applies the same refresh logic.
* Both return values reflect whether anything changed (the caller
  uses these to decide whether to save / rebuild UI)."""

import pytest


# ----------------------------------------------------------
# Stubs for the dependency surface the facade reaches into.
# ----------------------------------------------------------

class StubKnownDevices:
    """Minimal stand-in for KnownDevicesRegistry. `all()` returns
    the dict as the real one does."""

    def __init__(self, devices=None) -> None:
        self.devices = dict(devices or {})

    def all(self):
        return dict(self.devices)


class StubProfileManager:
    """Just enough surface for the facade's refresh paths.
    Doesn't persist anything — `save_profiles` only bumps a counter
    so tests can assert it was called."""

    def __init__(self, profiles=None, avatar_profiles=None, known=None) -> None:
        self.profiles = profiles or {}
        self.avatar_profiles = avatar_profiles or {}
        self.known_devices = StubKnownDevices(known)
        self.saved = 0

    def save_profiles(self) -> None:
        self.saved += 1


def _facade(profile_manager):
    """Compose ProfilesFacade with a tiny holder class so the mixin
    has the attributes it expects. `log_message` is a no-op."""
    from controllers.profiles_facade import ProfilesFacade

    class _Holder(ProfilesFacade):
        def __init__(self, pm):
            self.profile_manager = pm

        def log_message(self, msg):
            pass

    return _Holder(profile_manager)


# ============================================================ _seed_profile_with_known_devices


class TestSeedProfileAddsNewEntries:
    """When a known toy isn't in the profile yet, seed adds it with
    a full default config (motor_count, motor_kinds, osc_addresses,
    mix block)."""

    def test_new_toy_added_with_kinds(self):
        pm = StubProfileManager(
            profiles={"default": {}},
            known={"Max": {"motor_count": 2, "motor_kinds": ["vibrate", "constrict"]}},
        )
        app = _facade(pm)
        app._seed_profile_with_known_devices("default")
        assert "Max" in pm.profiles["default"]
        assert pm.profiles["default"]["Max"]["motor_kinds"] == ["vibrate", "constrict"]
        assert pm.profiles["default"]["Max"]["motor_count"] == 2
        # save_profiles fired because we added an entry.
        assert pm.saved >= 1

    def test_new_toy_gets_default_mix_block(self):
        from motor_router import MotorRouter
        pm = StubProfileManager(
            profiles={"default": {}},
            known={"Hush": {"motor_count": 1, "motor_kinds": ["vibrate"]}},
        )
        app = _facade(pm)
        app._seed_profile_with_known_devices("default")
        mix = pm.profiles["default"]["Hush"].get("mix")
        assert isinstance(mix, dict)
        # Per-motor default mix should be the canonical chains-list
        # shape from MotorRouter.DEFAULT_MIX_CONFIG.
        assert mix["0"]["chains"][0] == MotorRouter.DEFAULT_MIX_CONFIG["chains"][0]


class TestSeedProfileRefreshesExisting:
    """When the entry already exists, seed refreshes structural facts
    only (motor_count, motor_kinds). User-editable fields stay."""

    def test_stale_kinds_refreshed(self):
        # Profile thinks Max has two vibrate motors (old classification
        # before CONSTRICT was split out). known_devices has the fresh
        # classification.
        pm = StubProfileManager(
            profiles={"default": {"Max": {
                "motor_count": 2,
                "motor_kinds": ["vibrate", "vibrate"],
                "motor_0_zones": "Boob",  # user setting; must survive
            }}},
            known={"Max": {"motor_count": 2, "motor_kinds": ["vibrate", "constrict"]}},
        )
        app = _facade(pm)
        app._seed_profile_with_known_devices("default")
        entry = pm.profiles["default"]["Max"]
        assert entry["motor_kinds"] == ["vibrate", "constrict"]
        # User-editable field untouched.
        assert entry["motor_0_zones"] == "Boob"
        # Refresh triggered a save.
        assert pm.saved >= 1

    def test_motor_count_refreshed(self):
        pm = StubProfileManager(
            profiles={"default": {"Toy": {"motor_count": 1, "motor_kinds": ["vibrate"]}}},
            known={"Toy": {"motor_count": 3, "motor_kinds": ["vibrate", "vibrate", "vibrate"]}},
        )
        app = _facade(pm)
        app._seed_profile_with_known_devices("default")
        entry = pm.profiles["default"]["Toy"]
        assert entry["motor_count"] == 3

    def test_matching_kinds_no_save(self):
        pm = StubProfileManager(
            profiles={"default": {"Max": {"motor_count": 2, "motor_kinds": ["vibrate", "constrict"]}}},
            known={"Max": {"motor_count": 2, "motor_kinds": ["vibrate", "constrict"]}},
        )
        app = _facade(pm)
        app._seed_profile_with_known_devices("default")
        # No change, no save.
        assert pm.saved == 0

    def test_empty_known_devices_noop(self):
        pm = StubProfileManager(
            profiles={"default": {"Toy": {"motor_count": 1, "motor_kinds": ["vibrate"]}}},
            known={},
        )
        app = _facade(pm)
        app._seed_profile_with_known_devices("default")
        # Empty known_devices → early return; nothing changes.
        assert pm.saved == 0
        assert pm.profiles["default"]["Toy"]["motor_kinds"] == ["vibrate"]


# ============================================================ _refresh_avatar_profile_motor_facts


class TestAvatarProfileRefresh:
    """Avatar-bound profiles need their own refresh pass because the
    startup seed loop only iterates regular profiles."""

    def test_stale_kinds_refreshed(self):
        pm = StubProfileManager(
            avatar_profiles={
                "avtr_abc123": {"Max": {
                    "motor_count": 2,
                    "motor_kinds": ["vibrate", "vibrate"],
                }}
            },
            known={"Max": {"motor_count": 2, "motor_kinds": ["vibrate", "constrict"]}},
        )
        app = _facade(pm)
        changed = app._refresh_avatar_profile_motor_facts()
        assert changed is True
        assert pm.avatar_profiles["avtr_abc123"]["Max"]["motor_kinds"] == ["vibrate", "constrict"]
        assert pm.saved >= 1

    def test_returns_false_when_unchanged(self):
        pm = StubProfileManager(
            avatar_profiles={"avtr_abc123": {"Max": {
                "motor_count": 2, "motor_kinds": ["vibrate", "constrict"],
            }}},
            known={"Max": {"motor_count": 2, "motor_kinds": ["vibrate", "constrict"]}},
        )
        app = _facade(pm)
        assert app._refresh_avatar_profile_motor_facts() is False
        assert pm.saved == 0

    def test_user_fields_untouched(self):
        pm = StubProfileManager(
            avatar_profiles={"avtr_abc123": {"Max": {
                "motor_count": 2,
                "motor_kinds": ["vibrate", "vibrate"],
                "motor_0_touch": True,
                "motor_0_zones": "Tail",
            }}},
            known={"Max": {"motor_count": 2, "motor_kinds": ["vibrate", "constrict"]}},
        )
        app = _facade(pm)
        app._refresh_avatar_profile_motor_facts()
        entry = pm.avatar_profiles["avtr_abc123"]["Max"]
        assert entry["motor_0_touch"] is True
        assert entry["motor_0_zones"] == "Tail"

    def test_device_not_in_known_devices_skipped(self):
        # An avatar profile entry for a toy that's no longer in
        # known_devices (e.g. user "forgot" the toy via the UI but the
        # profile still references it) is left alone — refresh only
        # writes when the live registry has authoritative data.
        pm = StubProfileManager(
            avatar_profiles={"avtr_abc123": {"OldToy": {
                "motor_count": 1, "motor_kinds": ["vibrate"],
            }}},
            known={},
        )
        app = _facade(pm)
        changed = app._refresh_avatar_profile_motor_facts()
        assert changed is False
        assert pm.avatar_profiles["avtr_abc123"]["OldToy"]["motor_kinds"] == ["vibrate"]

    def test_empty_avatar_profiles_noop(self):
        pm = StubProfileManager(
            avatar_profiles={},
            known={"Max": {"motor_count": 2, "motor_kinds": ["vibrate", "constrict"]}},
        )
        app = _facade(pm)
        assert app._refresh_avatar_profile_motor_facts() is False
        assert pm.saved == 0

    def test_multiple_avatar_profiles_walked(self):
        pm = StubProfileManager(
            avatar_profiles={
                "avtr_one": {"Max": {"motor_count": 2, "motor_kinds": ["vibrate", "vibrate"]}},
                "avtr_two": {"Max": {"motor_count": 2, "motor_kinds": ["vibrate", "vibrate"]}},
            },
            known={"Max": {"motor_count": 2, "motor_kinds": ["vibrate", "constrict"]}},
        )
        app = _facade(pm)
        changed = app._refresh_avatar_profile_motor_facts()
        assert changed is True
        assert pm.avatar_profiles["avtr_one"]["Max"]["motor_kinds"] == ["vibrate", "constrict"]
        assert pm.avatar_profiles["avtr_two"]["Max"]["motor_kinds"] == ["vibrate", "constrict"]
        # One save covers all the changes (batched).
        assert pm.saved == 1
