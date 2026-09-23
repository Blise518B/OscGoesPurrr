"""The 518 design system in OscGoesPurrr: every colour the app paints is a
token from theme_tokens.py (a verbatim copy of the hub file), the two
modes resolve correctly, and the painted widgets keep the geometry their
frames need."""
import os
import re

import pytest

import theme_tokens as T
import constants as C
from ui import theme

HEX = re.compile(r"#[0-9a-fA-F]{6}\b")


def _token_hexes():
    out = set()
    for mode in T.MODES.values():
        out.update(v.lower() for v in mode.values())
    for tri in T.PALETTE.values():
        out.update(v.lower() for v in tri)
    out.add(theme.NEON_CAT_BAR.lower())
    for fill, border in theme.NEON_CAT_BARS.values():
        out.update((fill.lower(), border.lower()))
    return out


class TestTokens:
    def test_the_copy_is_the_hub_file_when_the_hub_is_reachable(self):
        # The design hub sits two levels above this checkout on the
        # maintainer's machine; OGP_518_HUB overrides that. Anywhere else
        # the hub simply isn't there and the drift check skips.
        repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        hub_dir = os.environ.get("OGP_518_HUB") or os.path.join(
            repo, os.pardir, os.pardir, "_hub")
        hub = os.path.join(hub_dir, "design", "theme_tokens.py")
        if not os.path.exists(hub):
            pytest.skip("518 design hub not on this machine")
        here = os.path.join(repo, "src", "theme_tokens.py")
        # Compare decoded text, not raw bytes: with core.autocrlf=true git
        # hands the working tree CRLF while the hub file stays LF, which is
        # not drift. newline="" would preserve that difference, so let
        # universal newlines normalise both sides.
        with open(hub, encoding="utf-8") as a, open(here, encoding="utf-8") as b:
            assert a.read() == b.read(), "theme_tokens.py drifted from the hub copy"

    def test_neon_is_the_default(self):
        assert T.DEFAULT_MODE == "neon"

    def test_no_retired_hex_anywhere_in_the_tokens(self):
        assert not (_token_hexes() & {h.lower() for h in T.RETIRED})


class TestStylesheet:
    def test_every_hex_in_the_sheet_is_a_token(self):
        for mode in T.MODE_ORDER:
            sheet = theme.build_qss(mode)
            stray = theme.hexes_in(sheet) - _token_hexes()
            assert not stray, f"{mode}: non-token colours in the stylesheet: {stray}"

    def test_no_retired_hex_in_the_sheet(self):
        for mode in T.MODE_ORDER:
            assert not (theme.hexes_in(theme.build_qss(mode))
                        & {h.lower() for h in T.RETIRED})

    def test_neon_frames_in_the_line_and_midnight_in_the_hairline(self):
        neon, mid = theme.build_qss("neon"), theme.build_qss("midnight")
        assert T.NEON["line"] in neon and T.MIDNIGHT["line"] in mid
        assert f"border: 1px solid {T.NEON['line']}" in neon

    def test_one_filled_primary_and_ink_text_on_it(self):
        sheet = theme.build_qss("neon")
        assert f"background-color: {T.NEON['accent']}; border-color: {T.NEON['accent']};" in sheet
        # Never white on green: the filled primary reads in ink.
        i = sheet.index('QPushButton[role="primary"]')
        block = sheet[i:sheet.index("}", i)]
        assert T.NEON["ink"] in block and "#ffffff" not in block.lower()

    def test_disconnected_is_amber_not_red(self):
        sheet = theme.build_qss("neon")
        i = sheet.index('QLabel[role="pill"][tone="off"]')
        block = sheet[i:sheet.index("}", i)]
        assert T.PALETTE["amber"][0] in block
        assert T.PALETTE["red"][0] not in block

    def test_spin_arrows_point_at_bundled_assets(self):
        sheet = theme.build_qss("neon")
        assert "spin_arrow_up.svg" in sheet and "\\" not in sheet.split("spin_arrow_up.svg")[0][-120:]


class TestModes:
    def test_legacy_broker_alias_resolves_to_midnight(self):
        assert theme.normalize_mode("broker") == "midnight"

    def test_unknown_mode_falls_back_to_neon(self):
        assert theme.normalize_mode("purrple") == "neon"

    def test_other_mode_flips(self):
        assert theme.other_mode("neon") == "midnight"
        assert theme.other_mode("midnight") == "neon"
        assert theme.other_mode("broker") == "neon"

    def test_constants_are_qt_free_and_token_backed(self):
        import sys
        # constants must never drag Qt in (the router imports it).
        path = os.path.join(os.path.dirname(os.path.dirname(__file__)),
                            "src", "constants.py")
        with open(path, encoding="utf-8") as f:
            src = f.read()
        assert "PySide6" not in src
        assert C.COLOR_ACCENT == T.MODES[C.UI_MODE]["accent"]
        assert C.COLOR_LINE == T.MODES[C.UI_MODE]["line"]
        assert C.COLOR_LIVE == T.PALETTE["pink"][0]
        assert C.COLOR_ALERT == T.PALETTE["red"][0]
        assert C.COLOR_WARNING == T.PALETTE["amber"][0]
        assert C.COLOR_TEXT_ON_PRIMARY == T.MODES[C.UI_MODE]["ink"]


class TestTags:
    def test_status_tag_only_accents_the_name(self):
        html = theme.status_tag_html("OscGoesPurrr", "1.2.3")
        assert html.startswith("OscGoesPurrr v1.2.3 · made by ")
        assert html.count(T.MODES[C.UI_MODE]["accent"]) == 1
        assert "<b" in html and "Blise518B" in html

    def test_build_number_is_a_commit_count_not_the_version(self):
        # Public releases carry a hand-set VERSION ("0.9.0"), so the
        # `b<n>` build number is its own thing -- the commit count -- and
        # deliberately does NOT track any component of the version string.
        import version
        assert version.build_number() >= 0
        assert isinstance(version.build_number(), int)

    def test_version_parses_as_a_release_tag(self):
        # The launch-time update check compares __version__ against the
        # newest GitHub tag, so it has to survive _parse_version.
        import version
        import update_checker
        assert update_checker._parse_version(version.__version__) is not None
        assert version.__version__.startswith(version.VERSION)


class TestPaintedWidgets:
    @pytest.fixture(autouse=True)
    def _app(self):
        from PySide6.QtWidgets import QApplication
        self.app = QApplication.instance() or QApplication([])

    def test_toggle_hint_holds_the_whole_track(self):
        from ui.widgets import ToggleSwitch
        t = ToggleSwitch("Help Mode")
        h = t.sizeHint()
        assert h.height() >= ToggleSwitch._TRACK_H + 2   # room for the 1px frame
        assert h.width() >= ToggleSwitch._TRACK_W + ToggleSwitch._LABEL_SPACING

    def test_toggle_knob_is_ink_on_accent_never_white(self):
        from ui.widgets import ToggleSwitch
        assert ToggleSwitch._COLOR_KNOB_ON.name().lower() == T.MODES[C.UI_MODE]["ink"]
        assert ToggleSwitch._COLOR_ON.name().lower() == T.MODES[C.UI_MODE]["accent"]

    def test_meter_paints_without_error(self):
        from PySide6.QtGui import QPixmap
        from ui.widgets import RainbowMeter
        m = RainbowMeter(maximum=1000)
        m.resize(120, 8)
        m.setValue(600)
        pm = m.grab()
        assert not pm.isNull()

    def test_single_line_inputs_share_one_height(self):
        """The native style's stacked-arrow allowance made spinboxes 46px
        and line edits 42px next to 30px combos; the sheet pins them."""
        from PySide6.QtWidgets import (QSpinBox, QComboBox, QLineEdit,
                                       QWidget, QHBoxLayout)
        self.app.setStyleSheet(theme.build_qss("neon"))
        host = QWidget()
        row = QHBoxLayout(host)
        sb, cb, le = QSpinBox(), QComboBox(), QLineEdit("x")
        cb.addItem("Sine")
        for w in (sb, cb, le):
            row.addWidget(w)
        host.resize(400, 60)
        row.activate()
        # What a layout actually hands them (the sheet's max-height clamps
        # the spinbox's larger hint), not the raw size hints.
        heights = {w.height() for w in (sb, cb, le)}
        self._keep = host
        assert len(heights) == 1, heights
        assert 28 <= next(iter(heights)) <= 32, heights


class TestFlowLayout:
    @pytest.fixture(autouse=True)
    def _app(self):
        from PySide6.QtWidgets import QApplication
        self.app = QApplication.instance() or QApplication([])

    def _host(self, width):
        from PySide6.QtWidgets import QWidget
        from ui.layout_helpers import FlowLayout
        host = QWidget()
        flow = FlowLayout(margin=0, h_spacing=10, v_spacing=6)
        host.setLayout(flow)
        items = []
        for _ in range(3):
            w = QWidget()
            w.setFixedSize(150, 30)
            flow.addWidget(w)
            items.append(w)
        host.resize(width, 200)
        flow.setGeometry(host.rect())
        self._keep = host                 # the items die with their host
        return items

    def test_wide_host_keeps_one_row(self):
        items = self._host(600)
        assert len({w.geometry().y() for w in items}) == 1

    def test_narrow_host_wraps(self):
        items = self._host(340)          # two fit (150+10+150), the third wraps
        ys = [w.geometry().y() for w in items]
        assert ys[0] == ys[1] and ys[2] > ys[0]
        assert items[2].geometry().x() == 0


class TestIdentityHues:
    """Toys are group frames in a cycling identity hue; chains are cards in a
    type hue that no toy can wear, so structure and colour both say which
    box is which."""

    def test_toys_cycle_through_three_cool_hues(self):
        assert [theme.toy_hue(i) for i in range(5)] == ["cyan", "blue", "purple", "cyan", "blue"]

    def test_chain_hues_never_collide_with_toy_hues(self):
        assert not (set(theme.CHAIN_TYPE_HUES.values()) & set(theme.TOY_HUES))
        assert "green" not in theme.CHAIN_TYPE_HUES.values()   # the chrome hue

    def test_sheet_carries_a_variant_per_hue_in_both_modes(self):
        for mode in ("neon", "midnight"):
            sheet = theme.build_qss(mode)
            for hue in theme.TOY_HUES:
                assert f'QFrame#toyFrame[hue="{hue}"]' in sheet
                assert f'QWidget#toyBar[hue="{hue}"]' in sheet
            for hue in set(theme.CHAIN_TYPE_HUES.values()):
                assert f'QFrame#chainFoldBar[hue="{hue}"]' in sheet
                assert f'QFrame#motorBlock[hue="{hue}"]' in sheet

    def test_neon_bars_are_the_reference_fills_and_midnight_the_tints(self):
        neon, mid = theme.build_qss("neon"), theme.build_qss("midnight")
        assert theme.NEON_CAT_BARS["cyan"][0] in neon
        assert theme.PALETTE["cyan"][2] in mid          # tint fill
        assert theme.NEON_CAT_BARS["cyan"][0] not in mid
