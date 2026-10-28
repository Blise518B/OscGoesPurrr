"""Friend invite links: what OGP puts on your clipboard for a friend, and
how it reads one back.

An invite is your Friends ID plus a code (and your nickname, for
the page it opens). Discord only makes http(s) links clickable, so the link
you send points at a static page on OGP's website, and the page hands it to
the app as an ogp:// link (registered by link_scheme.py). Everything after
the # stays in the browser: the website never learns who invited whom.

    https://blise518b.github.io/OscGoesPurrr/friend.html#<id>.<code>.<nick>
    ogp://friend/<id>.<code>.<nick>

What OGP copies is the link on a line of its own with who it is from in
brackets under it -- "(Add Blise on OscGoesPurrr)" -- so it pastes into a
browser as well as any chat (Blise's call, 2026-10-28; it used to be a
Discord masked link, which only Discord understood). A browser joins the
two lines into one, so a link's nickname ends at the first character
`quote()` never leaves as it is (`_NICK`); friend.html and remote.html cut
it there too. `parse()` also takes a bare 64-character ID and the masked
link older versions copied ("[Add Blise on OscGoesPurrr](https://...)"),
so whatever a friend pastes into Add a friend works.

Your web remote link has the same shape on another page -- remote.html,
where a browser drives your toys without OGP (settings.friends ``web``):

    https://blise518b.github.io/OscGoesPurrr/remote.html#<id>.<code>.<nick>
    (Drive Blise's toys - OscGoesPurrr web remote)

-- copied as those two lines, so it pastes straight into a browser too.
It is not an invite: `parse()` doesn't take it.
"""

import re
from typing import Dict, Optional
from urllib.parse import quote, unquote

import remote_protocol as proto
from link_scheme import SCHEME

SITE_PAGE = "https://blise518b.github.io/OscGoesPurrr/friend.html"
REMOTE_PAGE = "https://blise518b.github.io/OscGoesPurrr/remote.html"


# What quote(safe="") leaves as it is -- the most a link's nickname is made
# of. Whatever got glued on after the link starts at the first other one.
_NICK = re.compile(r"[A-Za-z0-9_.~%-]*")


def _payload(peer_id: str, code: str, nick: str) -> str:
    return f"{peer_id}.{code}.{quote(proto.clean_nick(nick), safe='')}"


def web_link(peer_id: str, code: str, nick: str) -> str:
    return f"{SITE_PAGE}#{_payload(peer_id, code, nick)}"


def app_link(peer_id: str, code: str, nick: str) -> str:
    return f"{SCHEME}://friend/{_payload(peer_id, code, nick)}"


def invite_message(peer_id: str, code: str, nick: str) -> str:
    """Your invite for the clipboard: the link, and who it is from in
    brackets under it."""
    who = proto.clean_nick(nick) or "me"
    return f"{web_link(peer_id, code, nick)}\n(Add {who} on OscGoesPurrr)"


def remote_link(peer_id: str, code: str, nick: str) -> str:
    return f"{REMOTE_PAGE}#{_payload(peer_id, code, nick)}"


def remote_message(peer_id: str, code: str, nick: str) -> str:
    """Your web remote link for the clipboard, the way invites go: the link,
    and what it is in brackets under it (remote.html reads it with
    remote-proto.js `parseLink`)."""
    who = proto.clean_nick(nick)
    what = f"{who}'s toys" if who else "my toys"
    return f"{remote_link(peer_id, code, nick)}\n(Drive {what} - OscGoesPurrr web remote)"


def parse(text: str) -> Optional[Dict[str, str]]:
    """{"id", "code" ("" for a bare ID), "nick"} — or None when the text is
    neither an ID nor an invite link."""
    s = "".join(str(text or "").split())
    m = re.search(r"\]\((.+?)\)", s)          # a pasted Discord masked link
    if m:
        s = m.group(1)
    low = s.lower()
    if proto.valid_id(low):
        return {"id": low, "code": "", "nick": ""}
    if low.startswith(f"{SCHEME}://friend/"):
        payload = s[len(f"{SCHEME}://friend/"):]
    elif "#" in s and ("friend" in low.split("#", 1)[0]):
        payload = s.split("#", 1)[1]
    else:
        return None
    parts = payload.strip("/").split(".", 2)
    pid = parts[0].lower()
    if not proto.valid_id(pid):
        return None
    code = parts[1].lower() if len(parts) > 1 and proto.valid_code(parts[1].lower()) else ""
    nick = proto.clean_nick(unquote(_NICK.match(parts[2]).group())) if len(parts) > 2 else ""
    return {"id": pid, "code": code, "nick": nick}
