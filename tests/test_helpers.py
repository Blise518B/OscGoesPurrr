"""Tier 1 tests for the pure module-level helpers on `motor_router.py`.
These never touch a MotorRouter instance or any clock — just parse
strings and classify zone paths.

See ``PLAN.md`` for the full punch-list.
"""

import pytest

from motor_router import (
    _classify_zone_path,
    _clean_custom_addr,
)
from utilities import create_default_icon, normalize_osc_value


# ---------------------------------------------------------------- normalize_osc_value

class TestNormalizeOscValue:
    def test_unit_floats_pass_through(self):
        assert normalize_osc_value(0.7) == pytest.approx(0.7)
        assert normalize_osc_value(0.0) == 0.0
        assert normalize_osc_value(1.0) == 1.0

    def test_float_above_one_saturates_not_collapses(self):
        # Regression: 1.2 used to get the int-255 rescale (-> 0.0047), a
        # discontinuous cliff for custom-address params bound to raw floats.
        assert normalize_osc_value(1.2) == 1.0

    def test_int_byte_range_rescales(self):
        assert normalize_osc_value(255) == 1.0
        assert normalize_osc_value(128) == pytest.approx(128 / 255.0)

    def test_negative_clamps_to_zero(self):
        assert normalize_osc_value(-0.3) == 0.0

    @pytest.mark.parametrize("bad", [float("nan"), float("inf"),
                                     float("-inf"), "garbage", None])
    def test_non_finite_and_garbage_are_zero(self, bad):
        # Regression: normalize_osc_value(nan) used to return exactly 1.0
        # (min(1.0, nan) keeps 1.0) — full power from one bad packet.
        assert normalize_osc_value(bad) == 0.0

    def test_bool_true_is_full(self):
        assert normalize_osc_value(True) == 1.0


# ---------------------------------------------------------------- _classify_zone_path

class TestClassifyZonePath:
    def test_orifice_long_form(self):
        assert _classify_zone_path("OGB/Orifice/Boob") == ("Orf", "Boob")

    def test_orifice_short_form(self):
        assert _classify_zone_path("OGB/Orf/Tail") == ("Orf", "Tail")

    def test_penetrator_long_form(self):
        assert _classify_zone_path("OGB/Penetrator/Shaft") == ("Pen", "Shaft")

    def test_penetrator_short_form(self):
        assert _classify_zone_path("OGB/Pen/Shaft") == ("Pen", "Shaft")

    def test_non_ogb_path_returns_none(self):
        assert _classify_zone_path("avatar/parameters/Foo") is None

    def test_unknown_category_returns_none(self):
        assert _classify_zone_path("OGB/Wibble/Whatever") is None

    def test_too_short_path_returns_none(self):
        # Need at least three segments: OGB / category / name
        assert _classify_zone_path("OGB/Orifice") is None

    def test_touch_zone(self):
        assert _classify_zone_path("OGB/Touch/Head/Others") == ("Touch", "Head")

    def test_vfh_zone_form(self):
        # VRCFury Haptics zone form (see OGB's bridge parser).
        assert _classify_zone_path("VFH/Zone/Touch/Head/Others") == ("Touch", "Head")
        assert _classify_zone_path("VFH/Zone/Orf/Boob/TouchOthers") == ("Orf", "Boob")


# ---------------------------------------------------------------- create_default_icon

class TestCreateDefaultIconTint:
    def test_tint_draws_the_dot_between_the_ears(self):
        # The tray-glow dot sits in the empty gap between the ears; its
        # center pixel must be exactly the requested tint.
        img = create_default_icon(tint="#FF0000")
        assert img.size == (64, 64)
        assert img.getpixel((32, 12)) == (255, 0, 0, 255)

    def test_the_dot_leaves_the_letters_alone(self):
        # It used to sit bottom-right, which on this icon is the P.
        plain = create_default_icon()
        tinted = create_default_icon(tint="#FF0000")
        for y in range(30, 64):
            for x in range(64):
                assert plain.getpixel((x, y)) == tinted.getpixel((x, y))

    def test_keeps_the_icons_transparency(self):
        # The eared frame leaves the canvas corners empty. Flattening to
        # RGB used to paint them solid black in the tray.
        img = create_default_icon()
        assert img.mode == "RGBA"
        assert img.getpixel((0, 63))[3] == 0      # bottom-left corner
        assert img.getpixel((12, 30))[3] != 0     # inside the frame

    def test_tinted_differs_from_plain(self):
        base = create_default_icon()
        tinted = create_default_icon(tint="#00FF00")
        assert base.size == tinted.size == (64, 64)
        assert base.tobytes() != tinted.tobytes()

    def test_bad_tint_is_harmless(self):
        img = create_default_icon(tint="not-a-color")
        assert img.size == (64, 64)

    def test_vfh_unknown_category_returns_none(self):
        assert _classify_zone_path("VFH/Zone/Wibble/X/Y") is None

    def test_vfh_too_short_returns_none(self):
        assert _classify_zone_path("VFH/Zone/Touch") is None


# --------------------------------------------------------------- _clean_custom_addr

class TestCleanCustomAddr:
    def test_strips_avatar_parameters_prefix(self):
        assert _clean_custom_addr("/avatar/parameters/Foo") == "Foo"

    def test_strips_bare_leading_slash(self):
        assert _clean_custom_addr("/Foo") == "Foo"

    def test_leaves_prefix_free_address_alone(self):
        assert _clean_custom_addr("OGB/Orf/Boob/TouchSelf") == "OGB/Orf/Boob/TouchSelf"

    def test_empty_string_passes_through(self):
        assert _clean_custom_addr("") == ""


