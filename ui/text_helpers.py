"""Tiny string helpers used by labels and the OSC inspector."""


def truncate(text: str, max_chars: int) -> str:
    """Return text shortened to `max_chars` with an ellipsis."""
    if text is None:
        return ""
    text = str(text)
    if len(text) <= max_chars:
        return text
    return text[: max(0, max_chars - 1)] + "…"


def html_escape(s: str) -> str:
    return (
        s.replace("&", "&amp;")
         .replace("<", "&lt;")
         .replace(">", "&gt;")
         .replace(" ", "&nbsp;")
    )
