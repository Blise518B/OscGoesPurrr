"""The user guide's addresses. The guide is built from `guide/` into
`docs/guide/` and served by GitHub Pages at /OscGoesPurrr/guide/.

Every place in the app that links the guide takes its address from here:
Help's Open the guide and each tile's Read more, help mode's strip, the
status bar's Guide and What's new (Blise's call, 2026-11-17: link the guide
where people will find it). `tests/test_guide_links.py` checks that every
page of the app has an entry and that each one is a page the built guide
really has. A new page of the app gets a line here.
"""

GUIDE_URL = "https://blise518b.github.io/OscGoesPurrr/guide/"

# A page of the app (its sidebar name) -> its page in the guide: a folder
# of docs/guide/, with the trailing slash GitHub Pages serves it under.
PAGES = {
    "Home": "toys/home/",
    "Friends": "friends/",
    "Toys": "toys/toys-page/",
    "Shockers": "shockers/",
    "Suits": "suits/",
    "PSVR2": "psvr2/",
    "My Avatar Remote": "avatar-remote/",
    "Statistics": "records/statistics/",
    "Log": "records/log/",
    "OSC Inspector": "help/common-problems/",
    "OSC Diagnostics": "help/common-problems/",
    "System Log": "help/common-problems/",
    "Settings": "settings/",
    "Help": "settings/help-and-tour/",
}


def page_url(page: str = "") -> str:
    """The guide's page for one of the app's pages; the guide's start for
    any other (or none)."""
    return GUIDE_URL + PAGES.get(page, "")
