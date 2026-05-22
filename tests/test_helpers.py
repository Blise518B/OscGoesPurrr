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


