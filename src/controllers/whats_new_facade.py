""""What's new" after an update -- the controller side.

At launch: if this build is newer than the last one whose notes this
install has shown, hand the notes to the UI once and remember the version.
A first install is not an update -- its notes are marked as seen without a
window (the Getting started card is what a newcomer needs). An install
that predates this feature has no marker at all, which reads as "seen
nothing": its first launch on a build with notes shows them.

The content and the rule live in `whats_new.py`; the window in
`ui/views/whats_new.py`.

Sealed-box rules: the UI calls these methods and gets primitives.
"""

from __future__ import annotations

import whats_new
from version import __version__


class WhatsNewFacade:
    """Mixin: the "What's new" window. Composed into OscGoesPurrrApp.

    Assumes the host has `self.mode_manager.app_settings`,
    `get_app_setting` / `set_app_setting` and `self.ui`.
    """

    def whats_new_on_launch(self) -> bool:
        """Show the notes of the releases this install has not seen yet.
        True when a window was opened. Called once, after the main window
        is up."""
        settings = self.mode_manager.app_settings
        seen = str(self.get_app_setting(whats_new.SEEN_KEY, "") or "")
        fresh = bool(getattr(settings, "created_fresh", False))
        releases = [] if fresh else whats_new.unseen_releases(seen, __version__)
        newest = whats_new.releases_for(__version__)
        # Remember the newest notes this build has, shown or not: a first
        # install starts "up to date", and nothing is shown twice.
        if newest and newest[0].version != seen:
            self.set_app_setting(whats_new.SEEN_KEY, newest[0].version)
        if not releases:
            return False
        show = getattr(self.ui, "show_whats_new", None)
        if not callable(show):
            return False
        show(whats_new.as_plain(releases))
        return True

    def get_whats_new(self) -> list:
        """The newest release notes this build carries, for the "What's
        new" button: `[(version, [(title, text, target), ...]), ...]`."""
        return whats_new.as_plain(whats_new.releases_for(__version__))
