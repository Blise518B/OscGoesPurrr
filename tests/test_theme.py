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
    # The palette's green as the app wears it: its tokens, or one blue
    # step beside them (see TestModes.test_every_role_is_its_token...).
    out.update(v.lower() for v in theme.PALETTE["green"])
    return out


def _blue_steps(a: str, b: str) -> int:
    """How far apart two colours are, when only the blue channel differs
    (a large number otherwise)."""
    if a[:5].lower() != b[:5].lower():
        return 999
    return abs(int(a[5:7], 16) - int(b[5:7], 16))


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

    def test_the_user_reads_vibrant_and_darker(self):
        """The design system's names stay the stored ones; the labels are
        this app's."""
        assert theme.MODE_ORDER == ["neon", "midnight"]
        assert theme.MODE_LABELS == {"neon": "Vibrant", "midnight": "Darker"}

    def test_every_role_is_its_token_or_one_blue_step_beside_it(self):
        """The chrome is the tokens, character for character. The
        palette's green and the section bar share a colour with a chrome
        token in one mode (Midnight's accent IS the palette's green,
        Neon's line IS the bar's frame tone); so that a mode switch can
        tell them apart by value, they sit one blue step aside -- the same
        in both modes."""
        tables = {m: theme._table(0.0, m) for m in T.MODE_ORDER}
        for mode, table in tables.items():
            for key, token in T.MODES[mode].items():
                assert table[key] == token.lower(), (mode, key)
        sources = dict(zip(("green.0", "green.1", "green.2"), T.PALETTE["green"]))
        sources.update(zip(("bar.0", "bar.1"), theme._GREEN_BAR))
        for role, token in sources.items():
            values = {table[role] for table in tables.values()}
            assert len(values) == 1, role                   # mode-independent
            assert _blue_steps(values.pop(), token) <= 1, role

    def test_the_default_sheet_is_the_one_for_the_mode_in_use(self):
        assert theme.build_qss() == theme.build_qss(theme.MODE)
        assert theme.qss_vars() == theme.qss_vars(theme.MODE)

    def test_unknown_mode_falls_back_to_neon(self):
        assert theme.normalize_mode("purrple") == "neon"

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
                assert f'QWidget#toyBar[hue="{hue}"]' in sheet
            # The toy's FRAME is painted (it contains the toy's sections,
            # see ui/live_theme.py), so no rule may try to style it.
            assert "toyFrame" not in sheet
            for hue in set(theme.CHAIN_TYPE_HUES.values()):
                assert f'QFrame#chainFoldBar[hue="{hue}"]' in sheet
                assert f'QFrame#motorBlock[hue="{hue}"]' in sheet

    def test_an_offline_toy_is_outlined_in_dim_with_no_hue_fill(self):
        """Remembered but not connected: the disabled tone, never red and
        never one of the identity hues."""
        assert theme.OFFLINE_HUE not in theme.TOY_HUES
        off = theme.OFFLINE_HUE
        # Neon: the chrome's dim. Midnight: grey's mid, because dim would
        # outshine the mid-tone frames of the toys that ARE connected.
        edges = {"neon": theme.T.NEON["dim"],
                 "midnight": theme.PALETTE["grey"][1]}
        for mode, edge in edges.items():
            outline, ground = theme.toy_frame_colors(off, mode)
            assert outline == edge and ground is None
            assert outline not in theme.PALETTE["red"]
            sheet = theme.build_qss(mode)
            assert "dashed" not in sheet and "dotted" not in sheet

    def test_midnight_keeps_the_home_entry_framed(self):
        """Midnight's `line` is a near-invisible hairline; the Home entry
        would lose the frame that sets it apart."""
        sheet = theme.build_qss("midnight")
        i = sheet.index('QPushButton[role="navHome"] {')
        block = sheet[i:sheet.index("}", i)]
        assert f"border: 1px solid {theme.PALETTE['green'][1]}" in block
        assert theme.T.MIDNIGHT["line"] not in block

    def test_home_is_the_one_framed_nav_entry(self):
        sheet = theme.build_qss("neon")
        i = sheet.index('QPushButton[role="navHome"] {')
        block = sheet[i:sheet.index("}", i)]
        assert f"border: 1px solid {theme.T.NEON['line']}" in block
        j = sheet.index('QPushButton[role="nav"] {')
        assert "border: 1px solid transparent" in sheet[j:sheet.index("}", j)]

    def test_a_toy_is_a_thin_outline_in_its_hue_with_nothing_filled(self):
        """The lightweight toy row: the hue is the frame and the name.
        Neon outlines in the reference apps' brighter frame tone, Midnight
        in the hue's mid; neither fills the bar."""
        neon, mid = theme.build_qss("neon"), theme.build_qss("midnight")
        vib, mid_tone, _tint = theme.PALETTE["cyan"]
        fill, frame = theme.NEON_CAT_BARS["cyan"]
        assert theme.toy_frame_colors("cyan", "neon") == (
            frame, theme.T.NEON["panel"])
        assert theme.toy_frame_colors("cyan", "midnight") == (
            mid_tone, theme.T.MIDNIGHT["panel"])
        for sheet in (neon, mid):
            assert (f'QWidget#toyBar[hue="cyan"] QLabel#deviceName '
                    f'{{ color: {vib}; }}' in sheet)
            assert 'QWidget#toyBar[hue="cyan"] { background-color' not in sheet
            assert fill not in sheet
