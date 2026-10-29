"""Your avatar's menu (ui/views/avatar_menu.py): one pair of links for every
place that offers the prefab, and the Settings card that says whether the
avatar you're wearing has it."""
import sys

import pytest

from ui.views import avatar_menu


@pytest.fixture(scope="module")
def qapp():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication(sys.argv[:1])


def test_the_prefab_comes_from_the_newest_release_under_its_fixed_name():
    # release.bat attaches it under this name to every release
    assert avatar_menu.PREFAB_URL == ("https://github.com/Blise518B/OscGoesPurrr/releases/"
                                      "latest/download/OscGoesPurrr-VRCFury.unitypackage")
    html = avatar_menu.links_html("#123")
    assert avatar_menu.PREFAB_URL in html and avatar_menu.GUIDE_URL in html


def test_has_menu_needs_vrchat_to_have_said_and_either_part():
    assert not avatar_menu.has_menu({})
    assert not avatar_menu.has_menu({"known": False, "self": True})
    assert avatar_menu.has_menu({"known": True, "self": False, "friends": True})
    assert not avatar_menu.has_menu({"known": True, "self": False, "friends": False})


def test_the_card_says_what_the_avatar_has(qapp):
    menu = {}
    explained = []
    card = avatar_menu.AvatarMenuCard(lambda: menu, lambda w, t, x: explained.append(t))
    assert {"Get the menu prefabs", "How to add it"} <= set(explained)
    assert not card.note.isHidden() and "VRChat" in card.note.text()
    menu.update(known=True, self=True, friends=False)
    card.refresh(force=True)
    assert card.note.isHidden()
    own, friends = card.rows["self"], card.rows["friends"]
    assert own[0].text() == "✓" and "on the avatar you're wearing" in own[1].text()
    assert friends[0].text() == "○" and "not on the avatar" in friends[1].text()


def test_a_card_that_cant_ask_says_it_doesnt_know(qapp):
    def broken():
        raise RuntimeError("no controller")
    card = avatar_menu.AvatarMenuCard(broken)
    assert not card.note.isHidden()


def test_the_friends_tip_offers_the_same_links(qapp):
    from ui.views.friends_vrc_tip import VrchatMenuTip
    tip = VrchatMenuTip()
    tip.set_state({"known": True, "friends": False})
    assert avatar_menu.PREFAB_URL in tip.text()
