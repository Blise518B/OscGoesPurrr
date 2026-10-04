"""Changing the app's colour -- and its mode -- while it runs.

Three layers, tested bottom up:

* the table that says what every green token is in a mode at a given
  turn -- one colour per role, never an identity hue, so the app can be
  recoloured by value;
* `retint`, which swaps the colours that modules, classes and widgets
  copied into themselves;
* `LiveTheme`, which sweeps a change through the app's sections.

Every test that turns the colour or switches the mode puts it back: the
tokens are module state shared by the whole test session.
"""
import os
import sys

import pytest

import accent_shift as A
import constants as C
import retint
import theme_tokens as T
from ui import theme


@pytest.fixture
def green_again():
    """Whatever a test turned the colour to, leave it the house green."""
    yield
    theme.set_accent_hue(None)
    assert C.COLOR_ACCENT == T.MODES[C.UI_MODE]["accent"]


@pytest.fixture
def mode_again(green_again):
    """Whatever mode a test switched to, leave the one it started in."""
    start = theme.MODE
    yield
    theme.set_mode(start)
    assert C.UI_MODE == theme.MODE == start


def _other_mode() -> str:
    return next(m for m in T.MODE_ORDER if m != theme.MODE)


def _near(a, b) -> bool:
    """Two colours (or tuples of them) that are the same, give or take
    the one blue step a shared colour is moved aside by."""
    if isinstance(a, str):
        a, b = (a,), (b,)
    return len(a) == len(b) and all(
        x[:5] == y[:5] and abs(int(x[5:], 16) - int(y[5:], 16)) <= 1
        for x, y in zip(a, b))


@pytest.fixture(scope="module")
def qapp():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication(sys.argv[:1])


class TestTable:
    def test_no_turn_is_the_tokens_themselves(self):
        table = theme._table(0.0)
        for key, token in T.mode(theme.MODE).items():
            assert table[key] == token
        assert _near(tuple(table[r] for r in C.GREEN_ROLES), T.PALETTE["green"])
        assert _near(tuple(table[r] for r in theme._BAR_ROLES), theme._GREEN_BAR)

    def test_a_mode_switch_only_changes_the_chrome(self):
        """The palette's green and the section bar are the same in both
        modes at every turn -- so the swap a mode switch makes never has
        to tell one of them from a chrome token that used to share its
        colour."""
        for hue in range(0, 360, 15):
            delta = A.delta_for(float(hue), T.NEON["accent"])
            neon, mid = theme._table(delta, "neon"), theme._table(delta, "midnight")
            assert set(neon) == set(mid)
            changed = {role for role in neon if neon[role] != mid[role]}
            assert changed <= set(T.NEON), (hue, changed)

    @pytest.mark.parametrize("mode", ["neon", "midnight"])
    def test_every_turn_gives_every_token_its_own_colour(self, mode):
        """Recolouring by value needs a one-to-one table: two tokens on one
        colour could not be told apart again on the next turn."""
        fixed = {tone for name, tri in T.PALETTE.items() if name != "green"
                 for tone in tri}
        for hue in range(0, 360, 3):
            table = theme._table(A.delta_for(float(hue), T.NEON["accent"]), mode)
            values = list(table.values())
            assert len(set(values)) == len(values), (mode, hue)
            assert not (set(values) & fixed), (mode, hue)

    def test_a_collision_steps_one_blue_level_aside(self):
        table = A.unique_table(["#112233", "#112233"[:-1] + "3"], 0.0)
        assert table == {"#112233": "#112233"}
        assert A._nudge("#112233", {"#112233"}) == "#112234"
        assert A._nudge("#1122ff", {"#1122ff"}) == "#1122fe"

    def test_extending_a_table_keeps_what_is_in_it(self):
        base = A.unique_table(["#31f272"], 90.0)
        more = A.unique_table(["#1c8a3d"], 90.0, table=base)
        assert more["#31f272"] == base["#31f272"] and "#1c8a3d" in more

    def test_constants_and_theme_agree_on_the_shared_tokens(self):
        for hue in (20.0, 150.0, 263.0, 313.0):
            delta = A.delta_for(hue, T.NEON["accent"])
            base, full = C.accent_table(delta), theme._table(delta)
            assert all(full[src] == cur for src, cur in base.items())


class TestRetint:
    M = {"#111111": "#aaaaaa", "#222222": "#bbbbbb"}

    def test_text_swaps_hexes_and_nothing_else(self):
        s = "color: #111111; border: 1px solid #333333; background: #222222;"
        assert retint.text(s, self.M) == \
            "color: #aaaaaa; border: 1px solid #333333; background: #bbbbbb;"
        assert retint.text("no colours", self.M) == "no colours"

    def test_strings_tuples_dicts_and_lists(self):
        class Box:
            pass
        b = Box()
        b.one = "#111111"
        b.other = "#333333"
        b.pair = ("#111111", ("#222222", 3))
        b.table = {"a": "#222222", "b": ["#111111", "keep"]}
        table_id = id(b.table)
        retint.instance(b, self.M)
        assert b.one == "#aaaaaa" and b.other == "#333333"
        assert b.pair == ("#aaaaaa", ("#bbbbbb", 3))
        assert b.table == {"a": "#bbbbbb", "b": ["#aaaaaa", "keep"]}
        assert id(b.table) == table_id          # containers change in place

    def test_a_shared_container_is_turned_once(self):
        """{A->B, B->C}: something visited twice would end up at C."""
        chain = {"#111111": "#222222", "#222222": "#333333"}

        class Box:
            pass
        shared = ["#111111"]
        a, b = Box(), Box()
        a.colours = b.colours = shared
        seen = set()
        retint.instance(a, chain, seen)
        retint.instance(b, chain, seen)
        assert shared == ["#222222"]

    def test_qt_colours_change_in_place_and_keep_their_alpha(self, qapp):
        from PySide6.QtGui import QBrush, QColor, QPen

        class Box:
            pass
        b = Box()
        b.colour = QColor("#111111")
        b.colour.setAlpha(90)
        b.pen = QPen(QColor("#222222"), 2.0)
        b.brush = QBrush(QColor("#111111"))
        b.untouched = QColor("#333333")
        colour = b.colour
        retint.instance(b, self.M)
        assert b.colour is colour
        assert colour.name() == "#aaaaaa" and colour.alpha() == 90
        assert b.pen.color().name() == "#bbbbbb" and b.pen.widthF() == 2.0
        assert b.brush.color().name() == "#aaaaaa"
        assert b.untouched.name() == "#333333"

    def test_modules_classes_and_default_arguments(self, monkeypatch):
        import types
        mod = types.ModuleType("ui.fake_colours")
        exec('''
COLOR = "#111111"
SOURCE = "#111111"
TONES = ("#111111", "#222222")
__retint_skip__ = frozenset({"SOURCE"})
def icon(color=COLOR, size=20):
    return color
class Painted:
    FILL = "#222222"
    def paint(self, pen="#111111"):
        return pen
''', mod.__dict__)
        mod.Painted.__module__ = mod.__name__
        monkeypatch.setitem(sys.modules, mod.__name__, mod)
        retint.modules(self.M)
        assert mod.COLOR == "#aaaaaa" and mod.TONES == ("#aaaaaa", "#bbbbbb")
        assert mod.SOURCE == "#111111"                  # a source is skipped
        assert mod.icon() == "#aaaaaa"                  # default argument
        assert mod.Painted.FILL == "#bbbbbb"
        assert mod.Painted().paint() == "#aaaaaa"

    def test_only_colour_modules_are_walked(self, monkeypatch):
        import types
        mod = types.ModuleType("motor_router_fake")
        mod.COLOR = "#111111"
        monkeypatch.setitem(sys.modules, mod.__name__, mod)
        retint.modules(self.M)
        assert mod.COLOR == "#111111"

    def test_every_module_that_uses_colours_is_on_the_list(self):
        """A frozen build has no source folder to find modules in, so the
        walker goes by name. A module that starts using colours has to be
        added to retint.COLOUR_MODULES, or the picker will miss it."""
        src = os.path.join(os.path.dirname(os.path.dirname(__file__)), "src")
        skip = {"theme_tokens", "accent_shift", "retint"}
        missing = []
        for folder, _dirs, files in os.walk(src):
            if "__pycache__" in folder or "steamvr_toy_driver" in folder:
                continue
            for name in files:
                if not name.endswith(".py"):
                    continue
                path = os.path.join(folder, name)
                rel = os.path.relpath(path, src)[:-3].replace(os.sep, ".")
                if rel.endswith(".__init__"):
                    rel = rel[:-len(".__init__")]
                if rel in skip:
                    continue
                with open(path, encoding="utf-8") as f:
                    body = f.read()
                if ("COLOR_" in body or "QColor" in body) \
                        and not retint.is_colour_module(rel):
                    missing.append(rel)
        assert not missing, missing


class TestSetAccentHue:
    def test_module_state_follows_and_comes_back(self, green_again):
        from ui.widgets import ToggleSwitch
        knob_on = ToggleSwitch._COLOR_ON
        mapping = theme.set_accent_hue(263.0)
        want = theme.accent_preview(263.0)
        assert mapping[T.MODES[C.UI_MODE]["accent"]] == want["accent"]
        assert C.COLOR_ACCENT == want["accent"] == theme.CHROME["accent"]
        assert C.COLOR_LINE == want["line"] and C.COLOR_SUCCESS == want["accent"]
        assert C.CHROME["tint"] == want["tint"]
        assert theme.PALETTE["green"] != T.PALETTE["green"]
        assert theme.PALETTE["pink"] == T.PALETTE["pink"]
        assert theme.ACCENT_HUE == 263.0 and C.UI_ACCENT_HUE == 263.0
        assert want["accent"] in theme.build_qss()
        # A class-level QColor is the same object, turned.
        assert ToggleSwitch._COLOR_ON is knob_on
        assert knob_on.name() == want["accent"]

        back = theme.set_accent_hue(None)
        assert back[want["accent"]] == T.MODES[C.UI_MODE]["accent"]
        assert theme.CHROME == dict(T.mode(theme.MODE))
        assert _near(theme.PALETTE["green"], T.PALETTE["green"])
        assert knob_on.name() == T.MODES[C.UI_MODE]["accent"]
        assert _near(theme.NEON_CAT_BARS["green"], theme._GREEN_BAR)

    def test_the_tokens_and_the_sources_are_never_rewritten(self, green_again):
        neon, palette = dict(T.NEON), dict(T.PALETTE)
        for hue in (20.0, 95.0, 263.0, None, 313.0):
            theme.set_accent_hue(hue)
        assert T.NEON == neon and T.PALETTE == palette
        assert theme._GREEN_BAR == ("#1c8a3d", "#36a35c")

    def test_the_same_colour_twice_is_no_change(self, green_again):
        assert theme.set_accent_hue(None) == {}
        assert theme.set_accent_hue(200.0)
        assert theme.set_accent_hue(200.0) == {}

    def test_a_walk_through_many_hues_lands_exactly_where_one_step_does(
            self, green_again):
        """Value-swapping is composed step by step while a slider is
        dragged; it must not drift."""
        for hue in range(0, 360, 7):
            theme.set_accent_hue(float(hue))
        theme.set_accent_hue(313.0)
        walked = (dict(theme.CHROME), theme.PALETTE["green"], C.COLOR_ACCENT)
        theme.set_accent_hue(None)
        theme.set_accent_hue(313.0)
        assert walked == (dict(theme.CHROME), theme.PALETTE["green"],
                          C.COLOR_ACCENT)


class TestSetMode:
    def test_module_state_follows_and_comes_back(self, mode_again):
        from ui.widgets import ToggleSwitch
        start, other = theme.MODE, _other_mode()
        knob_on = ToggleSwitch._COLOR_ON
        green, bars = theme.PALETTE["green"], dict(theme.NEON_CAT_BARS)

        mapping = theme.set_mode(other)
        want = T.MODES[other]
        assert mapping[T.MODES[start]["accent"]] == want["accent"]
        assert theme.MODE == C.UI_MODE == other
        assert theme.CHROME == dict(want) == C.CHROME
        assert C.COLOR_ACCENT == want["accent"] and C.COLOR_LINE == want["line"]
        assert C.COLOR_BG == want["bg"] and C.COLOR_TXT == want["txt"]
        assert theme.OK[0] == want["accent"]
        # A class-level QColor is the same object, switched.
        assert ToggleSwitch._COLOR_ON is knob_on
        assert knob_on.name() == want["accent"]
        # What is not chrome stays as it is.
        assert theme.PALETTE["green"] == green and theme.NEON_CAT_BARS == bars
        assert theme.PALETTE["pink"] == T.PALETTE["pink"]
        # The sheet and the painted toy frames follow by name.
        assert theme.build_qss() == theme.build_qss(other)
        assert theme.toy_frame_colors("cyan") == theme.toy_frame_colors("cyan", other)

        back = theme.set_mode(start)
        assert back[want["accent"]] == T.MODES[start]["accent"]
        assert theme.CHROME == dict(T.MODES[start]) == C.CHROME
        assert knob_on.name() == T.MODES[start]["accent"]
        assert theme.PALETTE["green"] == green

    def test_the_swap_is_one_to_one(self, mode_again):
        for hue in (None, 20.0, 150.0, 263.0, 313.0):
            theme.set_accent_hue(hue)
            for _there_and_back in range(2):
                mapping = theme.set_mode(_other_mode())
                assert len(set(mapping.values())) == len(mapping) == len(T.NEON)

    def test_the_mode_in_use_twice_is_no_change(self, mode_again):
        assert theme.set_mode(theme.MODE) == {}
        assert theme.set_mode(_other_mode())
        assert theme.set_mode(theme.MODE) == {}

    def test_a_legacy_name_is_understood(self, mode_again):
        theme.set_mode("neon")
        assert theme.set_mode("broker") and theme.MODE == "midnight"

    def test_modes_and_hues_in_any_order_land_where_a_fresh_start_does(
            self, mode_again):
        """Mode switches and colour changes are composed swap by swap;
        however they are mixed, the result is the table for that mode at
        that turn -- what a launch in it computes."""
        start, other = theme.MODE, _other_mode()
        for step in (other, 263.0, start, 20.0, other, 313.0, start, other):
            if isinstance(step, str):
                theme.set_mode(step)
            else:
                theme.set_accent_hue(step)
        delta = A.delta_for(313.0, T.NEON["accent"])
        want = theme._table(delta, other)
        assert theme.CHROME == {k: want[k] for k in T.NEON} == C.CHROME
        assert theme.PALETTE["green"] == tuple(want[r] for r in C.GREEN_ROLES)
        assert C.COLOR_ACCENT == want["accent"] and C.COLOR_TINT == want["tint"]
        assert C.COLOR_OK_TONES == (want["accent"], want["green.1"], want["green.2"])
        assert theme.build_qss() == theme.build_qss(other)

    def test_the_tokens_are_never_rewritten(self, mode_again):
        neon, midnight = dict(T.NEON), dict(T.MIDNIGHT)
        for _switch in range(3):
            theme.set_mode(_other_mode())
        assert T.NEON == neon and T.MIDNIGHT == midnight


class TestLiveTheme:
    """The sweep, on a small window: two sections and a widget in none."""

    @pytest.fixture
    def app(self, qapp, green_again):
        from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget
        from ui.live_theme import LiveTheme

        class App:
            pass
        a = App()
        a.window = QWidget()
        lay = QVBoxLayout(a.window)
        a.first, a.second = QWidget(), QWidget()
        lay.addWidget(a.first)
        lay.addWidget(a.second)
        a.loose = QLabel("between", a.window)
        a.dot = QLabel("", a.first)
        a.dot.setStyleSheet(f"background-color: {C.COLOR_ACCENT}; border-radius: 6px;")
        a.tag = QLabel(f'made by <b style="color:{C.COLOR_ACCENT}">B</b>', a.first)
        a.swatch = QLabel("", a.second)
        a.swatch.setStyleSheet(f"background: {C.COLOR_ACCENT};")
        a.swatch.setProperty("noRetint", True)
        a.second.cached = [C.COLOR_LINE, "#123456"]
        a.live = LiveTheme(a.window)
        a.live.add_root(a.first)
        a.live.add_root(a.second)
        a.green = C.COLOR_ACCENT
        return a

    def test_nothing_is_overridden_until_a_colour_is_picked(self, app):
        assert app.first.styleSheet() == "" and not app.live.busy()

    def test_a_change_reaches_every_section(self, app):
        assert app.live.set_hue(263.0)
        assert app.live.busy()
        app.live.finish()
        blue = theme.accent_preview(263.0)
        for root in (app.first, app.second):
            assert blue["accent"] in root.styleSheet()
            assert app.green not in root.styleSheet()
        # ...and what its widgets had copied into themselves.
        assert blue["accent"] in app.dot.styleSheet()
        assert blue["accent"] in app.tag.text()
        assert app.second.cached == [blue["line"], "#123456"]
        assert not app.live.busy()

    def test_a_widget_marked_noretint_keeps_what_it_shows(self, app):
        app.live.set_hue(263.0)
        app.live.finish()
        assert app.green in app.swatch.styleSheet()

    def test_back_to_green_restores_everything_exactly(self, app):
        dot, tag = app.dot.styleSheet(), app.tag.text()
        for hue in (263.0, 20.0, None):
            app.live.set_hue(hue)
            app.live.finish()
        assert app.dot.styleSheet() == dot and app.tag.text() == tag
        assert app.second.cached == [T.MODES[C.UI_MODE]["line"], "#123456"]
        # The override stays (clearing one makes Qt restore a stale font).
        assert app.green in app.first.styleSheet()

    def test_a_change_made_mid_sweep_is_not_lost(self, app):
        """Dragging the slider: the second colour arrives before the first
        has reached every section. Each section goes from wherever it is
        straight to the newest colour."""
        app.live.set_hue(263.0)
        app.live._apply(app.live._pending.pop(0))      # only one section done
        app.live.set_hue(313.0)
        app.live.finish()
        purple = theme.accent_preview(313.0)
        assert purple["accent"] in app.dot.styleSheet()
        assert app.second.cached[0] == purple["line"]

    def test_a_section_built_after_the_change_starts_in_the_new_colour(self, app):
        from PySide6.QtWidgets import QWidget
        app.live.set_hue(263.0)
        app.live.finish()
        late = QWidget(app.window)
        app.live.add_root(late)
        assert theme.accent_preview(263.0)["accent"] in late.styleSheet()

    def test_on_screen_sections_go_first_and_the_rest_wait_for_the_picker(
            self, app):
        from PySide6.QtWidgets import QApplication
        from PySide6.QtCore import Qt
        app.window.setAttribute(Qt.WA_DontShowOnScreen, True)
        app.window.show()
        app.second.hide()
        QApplication.processEvents()
        app.live.set_hue(263.0)
        assert app.live._take() is app.first           # the visible one
        assert app.live._take() is None                # picker not still yet
        app.live.finish()
        app.window.hide()

    def test_listeners_hear_about_a_change_once(self, app):
        heard = []
        app.live.on_change(lambda: heard.append(C.COLOR_ACCENT))
        app.live.set_hue(263.0)
        app.live.set_hue(263.0)                         # same colour: silence
        assert heard == [theme.accent_preview(263.0)["accent"]]
        app.live.finish()

    def test_a_mode_switch_is_the_same_sweep(self, app, mode_again):
        start, other = theme.MODE, _other_mode()
        line = C.COLOR_LINE
        assert app.live.set_mode(other)
        assert app.live.busy()
        app.live.finish()
        want = T.MODES[other]
        for root in (app.first, app.second):
            assert root.styleSheet() == theme.build_qss(other)
        assert want["accent"] in app.dot.styleSheet()
        assert app.green not in app.dot.styleSheet()
        assert want["accent"] in app.tag.text()
        assert app.second.cached == [want["line"], "#123456"]
        assert app.green in app.swatch.styleSheet()        # noRetint
        assert not app.live.set_mode(other)                # already there

        assert app.live.set_mode(start)
        app.live.finish()
        assert app.green in app.dot.styleSheet()
        assert app.second.cached == [line, "#123456"]

    def test_a_mode_switch_and_a_colour_mid_sweep_both_arrive(
            self, app, mode_again):
        other = _other_mode()
        app.live.set_mode(other)
        app.live._apply(app.live._pending.pop(0))      # only one section done
        app.live.set_hue(313.0)
        app.live.finish()
        want = theme.accent_preview(313.0, other)
        assert want["accent"] in app.dot.styleSheet()
        assert app.second.cached[0] == want["line"]
        for root in (app.first, app.second):
            assert root.styleSheet() == theme.build_qss(other)

    def test_listeners_hear_about_a_mode_switch(self, app, mode_again):
        heard = []
        app.live.on_change(lambda: heard.append(theme.MODE))
        other = _other_mode()
        app.live.set_mode(other)
        app.live.finish()
        assert heard == [other]

    def test_a_deleted_section_is_dropped_quietly(self, app):
        import shiboken6
        shiboken6.delete(app.second)
        app.live.set_hue(263.0)
        app.live.finish()
        assert theme.accent_preview(263.0)["accent"] in app.first.styleSheet()


class TestSectionsOnHome:
    """Home's sections must never sit inside one another: re-styling an
    outer one would re-style the inner ones with it — the lag spike the
    sections exist to avoid."""

    def test_no_section_contains_another(self, qapp, green_again):
        from ui.live_theme import LiveTheme
        from test_home_view import FakeController, _Host, _toys

        class LiveHost(_Host):
            @property
            def live_theme(self):
                if "_live" not in self.__dict__:
                    self._live = LiveTheme(self.window)
                return self._live

        host = LiveHost(FakeController(_toys(), connected={"Bravo", "Charlie"}))
        roots = host.live_theme._roots
        assert len(roots) >= 8
        ids = {id(r) for r in roots}
        for root in roots:
            parent = root.parentWidget()
            while parent is not None:
                assert id(parent) not in ids, (
                    f"{root.objectName() or root} sits inside another section")
                parent = parent.parentWidget()

    def test_a_toy_frame_is_painted_not_styled(self, qapp):
        from ui.widgets import Canvas, ToyFrame
        frame = ToyFrame()
        frame.set_hue("cyan")
        frame.resize(200, 48)
        assert not frame.grab().isNull() and frame.styleSheet() == ""
        assert not Canvas().grab().isNull()
