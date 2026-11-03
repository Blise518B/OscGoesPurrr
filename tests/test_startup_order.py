"""What runs before the window exists (main.OscGoesPurrrApp._setup_components).

Two of a friend's reports (2026-11-03), both from startup order: Friends
logged through the UI before there was one when its network library didn't
load, which raised and stopped Friends' setup halfway; and the UI asked for
the statistics' session list before statistics were set up."""
import inspect

import main


class _UI:
    def __init__(self):
        self.lines = []

    def log_message(self, message):
        self.lines.append(message)


def _app():
    app = main.OscGoesPurrrApp.__new__(main.OscGoesPurrrApp)
    app.ui = None
    return app


def test_a_line_logged_before_the_window_exists_waits_for_it():
    app = _app()
    app.log_message("Friends: the network library didn't load (no iroh)")  # must not raise
    app.log_message("second")
    app.ui = _UI()
    app._flush_log_before_ui()
    assert app.ui.lines == ["Friends: the network library didn't load (no iroh)", "second"]
    app._flush_log_before_ui()                       # shown once, not twice
    assert len(app.ui.lines) == 2
    app.log_message("after")                         # with a window: straight in
    assert app.ui.lines[-1] == "after"


def test_flushing_with_nothing_logged_is_fine():
    app = _app()
    app.ui = _UI()
    app._flush_log_before_ui()
    assert app.ui.lines == []


def _setup_source():
    return inspect.getsource(main.OscGoesPurrrApp._setup_components)


def test_statistics_are_set_up_before_the_ui_that_reads_them():
    src = _setup_source()
    assert src.index("self._stats_init()") < src.index("OscGoesPurrrUI(self)")
    assert src.count("self._stats_init()") == 1


def test_the_early_lines_are_shown_right_after_the_ui_is_built():
    src = _setup_source()
    ui_at = src.index("self.ui = OscGoesPurrrUI(self)")
    assert src.index("self._flush_log_before_ui()") > ui_at
    # ...before anything else uses the window
    between = src[ui_at:src.index("self._flush_log_before_ui()")]
    assert "self.ui." not in between.replace("self.ui = OscGoesPurrrUI(self)", "")


def test_every_init_before_the_ui_comes_first():
    """The inits the UI reads while it is built (and Friends, which logs)
    all run before it."""
    src = _setup_source()
    ui_at = src.index("OscGoesPurrrUI(self)")
    for init in ("_steamvr_toys_init", "_pishock_init", "_suits_init", "_params_init",
                 "_friends_init", "_stats_init"):
        assert src.index(f"self.{init}()") < ui_at, init
