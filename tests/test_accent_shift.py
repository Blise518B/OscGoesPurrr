"""The colour picker: turning the app's green to another hue.

Two promises. Left alone, nothing changes -- the tokens come through
character for character. Turned, every colour stays as readable as the
green was: the accent on the dark surfaces, the ink on a filled accent,
the frame line on the background.
"""
import sys

import pytest

import accent_shift as A
import theme_tokens as T
from ui import theme


def _luminance(hex_color):
    s = hex_color.lstrip("#")
    r, g, b = (A._to_linear(int(s[i:i + 2], 16) / 255.0) for i in (0, 2, 4))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _contrast(a, b):
    hi, lo = sorted((_luminance(a), _luminance(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


ALL_TOKENS = sorted(set(T.NEON.values()) | set(T.MIDNIGHT.values())
                    | {tone for tri in T.PALETTE.values() for tone in tri})


class TestMaths:
    def test_every_token_survives_the_round_trip(self):
        for token in ALL_TOKENS:
            assert A.from_oklch(*A.to_oklch(token)) == token

    def test_no_turn_returns_the_token_itself(self):
        for token in ALL_TOKENS:
            assert A.shift_hex(token, 0.0) is token
        assert A.shift_tokens(T.NEON, 0.0) == T.NEON

    def test_the_house_green_is_no_turn(self):
        assert A.delta_for(None, T.NEON["accent"]) == 0.0

    def test_a_turn_lands_the_accent_on_the_asked_hue(self):
        for hue in (20, 95, 212, 263, 313, 357):
            delta = A.delta_for(hue, T.NEON["accent"])
            got = A.hue_of(A.shift_hex(T.NEON["accent"], delta))
            assert abs((got - hue + 180) % 360 - 180) < 2.0, (hue, got)

    def test_a_full_circle_comes_home(self):
        accent = T.NEON["accent"]
        assert A.shift_hex(accent, 360.0 % 360.0) == accent

    def test_greys_have_no_hue_to_turn(self):
        assert A.shift_hex("#808080", 120.0) == "#808080"

    def test_non_colour_values_pass_through(self):
        assert A.shift_tokens({"r": 12, "c": "#31f272"}, 90.0)["r"] == 12


class TestReadability:
    """Every hue on the slider, both modes: the pairs the UI leans on keep
    a contrast a person can read."""

    @pytest.mark.parametrize("mode", ["neon", "midnight"])
    def test_every_hue_stays_readable(self, mode):
        for hue in range(0, 360, 5):
            v = theme.accent_preview(float(hue), mode)
            where = f"{mode} hue {hue}"
            assert _contrast(v["accent"], v["bg"]) >= 6.0, where
            assert _contrast(v["accent"], v["tint"]) >= 4.2, where
            assert _contrast(v["ink"], v["accent"]) >= 6.0, where
            assert _contrast(v["txt"], v["bg"]) >= 10.0, where

    def test_surfaces_stay_dark_and_text_stays_light(self):
        base = T.NEON
        for hue in range(0, 360, 15):
            v = theme.accent_preview(float(hue), "neon")
            for key in ("bg", "panel", "card", "well", "txt", "muted", "dim"):
                was, now = A.to_oklch(base[key])[0], A.to_oklch(v[key])[0]
                assert abs(was - now) < 0.02, (hue, key)

    def test_turned_to_the_palettes_own_hues_it_matches_them(self):
        """Blue lands on a blue you would call the palette's blue -- the
        turn is not a pastel wash."""
        for name in ("blue", "purple", "pink"):
            target = T.PALETTE[name][0]
            got = theme.accent_preview(A.hue_of(target), "neon")["accent"]
            (L1, C1, _h1), (L2, C2, _h2) = A.to_oklch(target), A.to_oklch(got)
            assert abs(L1 - L2) < 0.08 and C2 > 0.6 * C1, (name, target, got)


class TestThemeHookup:
    def test_the_suite_runs_on_the_house_green(self):
        import constants as C
        assert C.UI_ACCENT_DELTA == 0.0
        assert theme.ACCENT_HUE is None
        assert theme.CHROME == dict(T.mode(theme.MODE))
        # The palette's green: its tokens, or one blue step beside them
        # (test_theme.TestModes has the why).
        for mine, token in zip(theme.PALETTE["green"], T.PALETTE["green"]):
            assert mine[:5] == token[:5]
            assert abs(int(mine[5:], 16) - int(token[5:], 16)) <= 1

    def test_presets_start_with_the_green_and_skip_error_and_warning_hues(self):
        names = [n for n, _h in theme.ACCENT_PRESETS]
        assert theme.ACCENT_PRESETS[0] == ("Green (default)", None)
        assert "Red" not in names and "Amber" not in names

    def test_same_accent_treats_none_as_the_green_only(self):
        assert theme.same_accent(None, None)
        assert not theme.same_accent(None, 150.0)
        assert theme.same_accent(359.9, 0.1)
        assert not theme.same_accent(10.0, 20.0)

    def test_a_chosen_hue_recolours_the_whole_sheet_in_a_fresh_process(self):
        """The palette is copied at import, so a colour applies on the next
        launch: start one with a hue and read its stylesheet."""
        import os
        import subprocess
        src = os.path.join(os.path.dirname(os.path.dirname(__file__)), "src")
        code = (
            "import sys; sys.path.insert(0, sys.argv[1]);"
            "import theme_tokens as T; from ui import theme; import constants as C;"
            "s = theme.build_qss('neon');"
            "print(T.NEON['accent'] in s, T.NEON['line'] in s,"
            " theme.CHROME['accent'] in s, C.COLOR_ACCENT == theme.CHROME['accent'],"
            " theme.PALETTE['pink'] == T.PALETTE['pink'],"
            " theme.PALETTE['green'] != T.PALETTE['green'],"
            " theme.NEON_CAT_BAR != '#1c8a3d')")
        env = dict(os.environ, OGP_UI_ACCENT="263", OGP_UI_MODE="neon")
        out = subprocess.run([sys.executable, "-c", code, src], env=env,
                             capture_output=True, text=True,
                             creationflags=0x08000000 if os.name == "nt" else 0)
        assert out.stdout.split() == ["False", "False", "True", "True",
                                      "True", "True", "True"], out.stderr


class TestPicker:
    """Settings → Appearance: a choice is applied as it is made (through
    the live theme, when the host has one) and saved once the picker
    rests. Nothing restarts."""

    @pytest.fixture(scope="class")
    def qapp(self):
        from PySide6.QtWidgets import QApplication
        return QApplication.instance() or QApplication(sys.argv[:1])

    class _Controller:
        def __init__(self):
            self.settings = {}
            self.restarts = 0

        def set_app_setting(self, key, value):
            self.settings[key] = value

        def request_restart(self):
            self.restarts += 1

    class _Live:
        def __init__(self):
            self.hues = []
            self.modes = []

        def set_hue(self, hue):
            self.hues.append(hue)
            return True

        def set_mode(self, mode):
            if self.modes[-1:] == [mode]:
                return False
            self.modes.append(mode)
            return True

    def _host(self):
        from ui.views.settings import SettingsMixin
        live = self._Live()

        class Host(SettingsMixin):
            def __init__(self, controller):
                self.controller = controller
                self.live_theme = live
                self.mode_row = self._build_ui_mode_row()
                self.widget = self._build_accent_picker()

            def _repolish(self, w):
                w.style().unpolish(w)
                w.style().polish(w)

            def _muted_label(self, text):
                from PySide6.QtWidgets import QLabel
                return QLabel(text)

            def _explain(self, target, title, text):
                from ui.tooltips import explain
                explain(target, title, text)

        return Host(self._Controller())

    def test_opens_on_the_colour_in_use_and_changes_nothing(self, qapp):
        h = self._host()
        assert h._accent_pick is None
        assert h._accent_slider.value() == round(theme.DEFAULT_ACCENT_HUE)
        assert h.live_theme.hues == [] and h.controller.settings == {}

    def test_a_preset_applies_at_once(self, qapp):
        h = self._host()
        _name, hue = theme.ACCENT_PRESETS[2]            # Blue
        h._accent_preset_buttons[2][0].click()
        assert h.live_theme.hues == [hue]
        assert h._accent_slider.value() == round(hue)

    def test_a_drag_is_coalesced_into_steps_the_app_can_keep_up_with(self, qapp):
        h = self._host()
        for v in (200, 210, 220, 230):                   # one drag, four pixels
            h._accent_slider.setValue(v)
        assert h.live_theme.hues == []                   # nothing yet...
        assert h._accent_live_timer.isActive()
        h._accent_live_timer.timeout.emit()              # ...then the latest
        assert h.live_theme.hues == [230.0]

    def test_the_sliders_green_spot_is_the_house_green(self, qapp):
        h = self._host()
        h._accent_slider.setValue(300)
        h._accent_slider.setValue(round(theme.DEFAULT_ACCENT_HUE))
        assert h._accent_pick is None

    def test_the_choice_is_saved_once_the_picker_rests_and_nothing_restarts(self, qapp):
        h = self._host()
        h._accent_preset_buttons[3][0].click()           # Purple
        assert h.controller.settings == {}               # not on every step
        assert h._accent_save_timer.isActive()
        h._accent_save_timer.timeout.emit()
        hue = theme.ACCENT_PRESETS[3][1]
        assert h.controller.settings == {"ui_accent_hue": round(hue, 1)}
        assert h.controller.restarts == 0

    def test_green_is_saved_as_null(self, qapp):
        h = self._host()
        h._accent_preset_buttons[3][0].click()
        h._accent_preset_buttons[0][0].click()           # Green (default)
        h._accent_save_timer.timeout.emit()
        assert h.controller.settings == {"ui_accent_hue": None}

    def test_the_pickers_own_swatches_are_left_alone_by_the_sweep(self, qapp):
        """They show colours that are not the current one, on purpose."""
        h = self._host()
        assert h._accent_slider.property("noRetint")
        assert all(b.property("noRetint") for b, _h in h._accent_preset_buttons)

    def test_the_mode_buttons_are_vibrant_and_darker_with_the_one_in_use_lit(
            self, qapp):
        h = self._host()
        assert [b.text() for b in h._ui_mode_buttons.values()] == \
            ["Vibrant", "Darker"]
        lit = [k for k, b in h._ui_mode_buttons.items()
               if b.property("role") == "segActive"]
        assert lit == [theme.MODE]

    def test_a_mode_click_switches_live_saves_and_never_restarts(self, qapp):
        h = self._host()
        h._ui_mode_buttons["midnight"].click()
        assert h.live_theme.modes == ["midnight"]
        assert h.controller.settings == {"ui_mode": "midnight"}
        assert h._ui_mode_buttons["midnight"].property("role") == "segActive"
        assert h._ui_mode_buttons["neon"].property("role") == "segIdle"
        assert h.controller.restarts == 0

    def test_clicking_the_mode_in_use_does_nothing(self, qapp):
        h = self._host()
        h._ui_mode_buttons["midnight"].click()
        h.controller.settings.clear()
        h._ui_mode_buttons["midnight"].click()
        assert h.live_theme.modes == ["midnight"] and h.controller.settings == {}

    def test_the_mode_row_explains_itself(self, qapp):
        h = self._host()
        tip = h._ui_mode_buttons["neon"].toolTip()
        assert "Vibrant" in tip and "Darker" in tip and "nothing restarts" in tip

    def test_every_control_explains_itself(self, qapp):
        h = self._host()
        assert "green" in h._accent_slider.toolTip()
        assert "restarts" in h._accent_slider.toolTip()   # "Nothing restarts"
        assert h._accent_preset_buttons[2][0].toolTip() == "Blue"
