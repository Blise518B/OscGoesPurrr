"""Invite links: what OGP copies for a friend, and everything a friend may
paste back into Add a friend."""

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

import friend_links

NODE = shutil.which("node")
FRIEND_PAGE = Path(__file__).resolve().parent.parent / "docs" / "friend.html"

ID = "ab" * 32
CODE = "0123456789abcdef"


def test_web_and_app_links_read_back():
    for link in (friend_links.web_link(ID, CODE, "Space Fox.93"),
                 friend_links.app_link(ID, CODE, "Space Fox.93")):
        assert friend_links.parse(link) == {"id": ID, "code": CODE, "nick": "Space Fox.93"}


def test_the_link_points_at_the_site_page_and_hides_the_invite_after_the_hash():
    link = friend_links.web_link(ID, CODE, "Blise")
    page, payload = link.split("#", 1)
    assert page == friend_links.SITE_PAGE
    assert payload == f"{ID}.{CODE}.Blise"
    assert friend_links.app_link(ID, CODE, "Blise") == f"ogp://friend/{ID}.{CODE}.Blise"


def test_the_invite_is_the_link_and_a_note_under_it_and_parses():
    msg = friend_links.invite_message(ID, CODE, "Blise")
    assert msg == f"{friend_links.web_link(ID, CODE, 'Blise')}\n(Add Blise on OscGoesPurrr)"
    assert friend_links.parse(msg) == {"id": ID, "code": CODE, "nick": "Blise"}
    assert friend_links.invite_message(ID, CODE, "").endswith("\n(Add me on OscGoesPurrr)")


@pytest.mark.parametrize("nick", ["Blise", "Space Fox.93", "(x)!*'", "Mäuschen ♥"])
def test_a_pasted_invite_reads_back_however_it_was_glued(nick):
    """Whatever a friend pastes into Add a friend: the two lines as copied,
    joined by a browser (nothing or a space between, spaces then encoded),
    or the masked link older versions copied."""
    msg = friend_links.invite_message(ID, CODE, nick)
    url = friend_links.web_link(ID, CODE, nick)
    want = {"id": ID, "code": CODE, "nick": nick}
    for pasted in (msg, msg.replace("\n", ""), msg.replace("\n", " ").replace(" ", "%20"),
                   f"[Add {nick} on OscGoesPurrr]({url})"):
        assert friend_links.parse(pasted) == want


@pytest.mark.skipif(NODE is None, reason="node isn't installed")
@pytest.mark.parametrize("nick", ["Blise", "(x)!*'", "Mäuschen ♥"])
def test_the_invite_page_hands_the_app_the_link_without_the_note(nick):
    """docs/friend.html's script, run in node on a browser-joined paste:
    the ogp:// link it opens reads back to the same invite."""
    script = re.search(r"<script>(.*?)</script>", FRIEND_PAGE.read_text(encoding="utf-8"),
                       re.S).group(1)
    joined = friend_links.invite_message(ID, CODE, nick).replace("\n", "")
    fake = ("const els = {}; const document = {getElementById: (k) => els[k] || "
            "(els[k] = {hidden: true, textContent: '', href: ''}), title: ''};\n"
            f"const location = {{hash: {json.dumps('#' + joined.split('#', 1)[1].replace(' ', '%20'))},"
            " href: ''};\n" + script +
            "\nprocess.stdout.write(JSON.stringify([location.href, els.who.textContent]));")
    out = subprocess.run([NODE, "-e", fake], capture_output=True, text=True, check=True,
                         encoding="utf-8")
    app, who = json.loads(out.stdout)
    assert who == nick and app.startswith("ogp://friend/")
    assert friend_links.parse(app) == {"id": ID, "code": CODE, "nick": nick}


def test_a_bare_id_is_a_friend_request_without_a_code():
    assert friend_links.parse(f"  {ID.upper()}\n") == {"id": ID, "code": "", "nick": ""}


def test_odd_nicknames_survive_the_trip():
    for nick in ("a/b#c", "Mäuschen ♥", "(x)!*'", "dots.in.name"):
        got = friend_links.parse(friend_links.web_link(ID, CODE, nick))
        assert got["nick"] == nick and got["code"] == CODE


def test_junk_is_not_an_invite():
    for text in ("", "hello", "ab" * 31, "https://example.com/#" + ID,
                 f"ogp://friend/{'zz' * 32}.{CODE}.x"):
        assert friend_links.parse(text) is None


def test_a_cut_off_link_keeps_the_id_but_no_code():
    assert friend_links.parse(f"ogp://friend/{ID}.0123") == {"id": ID, "code": "", "nick": ""}
    assert friend_links.parse(f"ogp://friend/{ID}/") == {"id": ID, "code": "", "nick": ""}


def test_the_web_remote_link_is_its_own_page_and_no_invite():
    msg = friend_links.remote_message(ID, CODE, "Blise")
    url = friend_links.remote_link(ID, CODE, "Blise")
    # the link on its own line, so it pastes into a browser as well as a chat
    assert msg == f"{url}\n(Drive Blise's toys - OscGoesPurrr web remote)"
    assert url == f"https://blise518b.github.io/OscGoesPurrr/remote.html#{ID}.{CODE}.Blise"
    assert friend_links.parse(url) is None and friend_links.parse(msg) is None
