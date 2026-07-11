"""Tests for the color-profile system in constants.py: every profile
must define the complete palette (a missing key would crash at import
for anyone who switches to it), values must be well-formed hex colors,
and the loader must fall back safely."""

import re

import constants


HEX_RE = re.compile(r"^#[0-9A-Fa-f]{6}$")

# Palette keys every profile must define ("label" is UI metadata).
REQUIRED_KEYS = {
    "PRIMARY", "PRIMARY_HOVER", "ALERT", "ALERT_HOVER", "SUCCESS",
    "LIVE", "LIVE_DIM", "WARNING", "WARNING_DIM", "SUCCESS_DIM",
    "ALERT_DIM", "BG", "SURFACE", "SURFACE_HOVER", "BUTTON",
    "BUTTON_HOVER", "INPUT_BG", "INPUT_BORDER", "INPUT_FOCUS",
    "TEXT", "TEXT_MUTED", "CHAIN_IDLE", "CHAIN_LIVE",
}


class TestProfiles:
    def test_default_profile_exists(self):
        assert constants.DEFAULT_COLOR_PROFILE in constants.COLOR_PROFILES

    def test_every_profile_defines_the_full_palette(self):
        for name, palette in constants.COLOR_PROFILES.items():
            missing = REQUIRED_KEYS - set(palette)
            assert not missing, f"profile {name!r} missing {sorted(missing)}"
            assert palette.get("label"), f"profile {name!r} has no label"

    def test_every_color_is_valid_hex(self):
        for name, palette in constants.COLOR_PROFILES.items():
            for key in REQUIRED_KEYS:
                v = palette[key]
                assert HEX_RE.match(v), f"{name}.{key} = {v!r} is not #RRGGBB"

    def test_purrple_palette_is_the_original_identity(self):
        # The default look must never drift when new profiles are added.
        p = constants.COLOR_PROFILES["purrple"]
        assert p["PRIMARY"] == "#7C4DFF"
        assert p["BG"] == "#0D0924"
        assert p["CHAIN_IDLE"] == "#5030A0"
        assert p["CHAIN_LIVE"] == "#FF40A0"

    def test_active_profile_resolved_and_exported(self):
        assert constants.COLOR_PROFILE in constants.COLOR_PROFILES
        active = constants.COLOR_PROFILES[constants.COLOR_PROFILE]
        # The flat module-level constants mirror the active palette.
        assert constants.COLOR_PRIMARY == active["PRIMARY"]
        assert constants.COLOR_BG == active["BG"]
        assert constants.COLOR_CHAIN_LIVE == active["CHAIN_LIVE"]

    def test_loader_never_raises(self):
        # Reads the real user settings file (or nothing); whatever it
        # finds, it must return a known profile name.
        assert constants._load_color_profile() in constants.COLOR_PROFILES
