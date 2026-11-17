"""The app's links into the user guide (src/guide_links.py): every page of
the app has one, and each one is a page the built guide really has
(docs/guide/, what GitHub Pages serves) -- a renamed or moved guide page
fails here instead of opening GitHub's 404 for someone."""

import os
import re

import pytest

import guide_links

REPO = os.path.join(os.path.dirname(__file__), os.pardir)
BUILT = os.path.join(REPO, "docs", "guide")


def _view_names():
    with open(os.path.join(REPO, "src", "ui_components.py"), encoding="utf-8") as f:
        src = f.read()
    block = re.search(r"view_names = \[(.*?)\]", src, re.S).group(1)
    return re.findall(r'"([^"]+)"', block)


def test_every_page_of_the_app_has_a_guide_page():
    missing = [v for v in _view_names() if v not in guide_links.PAGES]
    assert not missing, f"add these to guide_links.PAGES: {missing}"


@pytest.mark.parametrize("page, path", sorted(guide_links.PAGES.items()))
def test_each_link_is_a_page_the_built_guide_has(page, path):
    assert path.endswith("/") and not path.startswith("/")
    assert os.path.isfile(os.path.join(BUILT, *path.strip("/").split("/"), "index.html")), (
        f"{page}: docs/guide/{path} isn't a built page")


def test_the_address_is_where_docusaurus_builds_it():
    with open(os.path.join(REPO, "guide", "docusaurus.config.js"), encoding="utf-8") as f:
        config = f.read()
    url = re.search(r"url:\s*'([^']+)'", config).group(1)
    base = re.search(r"baseUrl:\s*'([^']+)'", config).group(1)
    assert guide_links.GUIDE_URL == url + base


def test_an_unknown_page_opens_the_guides_start():
    assert guide_links.page_url("Nope") == guide_links.GUIDE_URL
    assert guide_links.page_url() == guide_links.GUIDE_URL
    assert guide_links.page_url("Shockers") == guide_links.GUIDE_URL + "shockers/"
