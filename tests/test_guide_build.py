"""The user guide (guide/, Docusaurus) is committed built, in docs/guide/,
because GitHub Pages serves /docs on the public main. These tests catch a
guide changed without a rebuild: tools/build_guide.py stamps docs/guide/
with a hash of everything the build read (guide/ and the site files it
takes), and the hash of the sources as they are must match it.

Skipped without `node` (the guide can't be rebuilt there), like
test_site_ports.py. The hash itself needs no node; its own tests always run.
"""

import importlib.util
import re
import shutil
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
GUIDE_DOCS = REPO / "guide" / "docs"
BUILT = REPO / "docs" / "guide"


def _tool():
    path = REPO / "tools" / "build_guide.py"
    spec = importlib.util.spec_from_file_location("build_guide", path)
    tool = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(tool)
    return tool


@pytest.fixture(scope="module")
def tool():
    return _tool()


@pytest.fixture(scope="module")
def node():
    if shutil.which("node") is None:
        pytest.skip("node is not on PATH; the guide is built with it")


# ---- the built guide is the guide as it is ------------------------------------

def test_docs_guide_is_not_older_than_the_guide(node, tool):
    assert tool.stamped_hash(), "docs/guide/ has no stamp: run tools/build_guide.py"
    assert not tool.is_stale(), (
        "guide/ (or the site files it reads) changed since docs/guide/ was built: "
        "run tools/build_guide.py and commit docs/guide/")


def _route(md: Path) -> Path:
    """Where a page lands in the build: its slug, else its path."""
    text = md.read_text(encoding="utf-8")
    slug = re.search(r"^slug:\s*(\S+)\s*$", text.split("\n---", 1)[0], re.M)
    rel = slug.group(1).strip("/") if slug else md.relative_to(GUIDE_DOCS).with_suffix("").as_posix()
    return BUILT / rel / "index.html" if rel else BUILT / "index.html"


def test_every_page_is_in_the_build(node):
    pages = sorted(GUIDE_DOCS.rglob("*.md"))
    assert len(pages) > 20
    missing = [p.relative_to(REPO).as_posix() for p in pages if not _route(p).is_file()]
    assert not missing, f"not in docs/guide/: {missing} -- run tools/build_guide.py"


def test_the_build_loads_nothing_from_elsewhere(node):
    """No CDN, font service or analytics: every script and stylesheet the
    guide's pages load is its own."""
    html = (BUILT / "getting-started" / "index.html").read_text(encoding="utf-8")
    for tag in re.findall(r"<(?:script|link)\b[^>]*>", html):
        src = re.search(r'(?:src|href)="([^"]+)"', tag)
        if not src or "stylesheet" not in tag and "<script" not in tag:
            continue
        assert src.group(1).startswith("/OscGoesPurrr/guide/"), tag


def test_the_build_names_no_folder_of_this_pc(node):
    """Docusaurus puts its config into the pages' JavaScript: a path in it
    must be relative, or the guide publishes where it was built."""
    local = re.compile(rb"[A-Za-z]:[\\/]+(?:Users|DIY-Projects|Program Files)|/home/[a-z]")
    for path in BUILT.rglob("*"):
        if path.suffix in (".js", ".html", ".json", ".xml"):
            assert not local.search(path.read_bytes()), (
                f"{path.relative_to(REPO)} names a folder of this PC")


def test_the_site_links_to_the_guide():
    html = (REPO / "docs" / "index.html").read_text(encoding="utf-8")
    assert 'href="guide/"' in html


# ---- the hash ------------------------------------------------------------------

def _fake_repo(root: Path) -> Path:
    (root / "guide" / "docs").mkdir(parents=True)
    (root / "guide" / "docs" / "intro.md").write_bytes(b"# Hi\nthere\n")
    (root / "guide" / "node_modules" / "x").mkdir(parents=True)
    (root / "guide" / "node_modules" / "x" / "index.js").write_text("1")
    (root / "docs" / "assets" / "fonts").mkdir(parents=True)
    (root / "docs" / "assets" / "tokens.css").write_text(":root { --bg: #000; }")
    (root / "docs" / "assets" / "ogp-icon.svg").write_text("<svg/>")
    (root / "docs" / "assets" / "fonts" / "A.ttf").write_bytes(b"\x00\x01")
    return root


def test_a_changed_page_changes_the_hash(tool, tmp_path):
    repo = _fake_repo(tmp_path)
    before = tool.source_hash(repo)
    (repo / "guide" / "docs" / "intro.md").write_bytes(b"# Hi\nthere!\n")
    assert tool.source_hash(repo) != before


def test_the_site_files_it_reads_count_too(tool, tmp_path):
    repo = _fake_repo(tmp_path)
    before = tool.source_hash(repo)
    (repo / "docs" / "assets" / "tokens.css").write_text(":root { --bg: #111; }")
    assert tool.source_hash(repo) != before


def test_packages_caches_and_line_endings_dont_count(tool, tmp_path):
    repo = _fake_repo(tmp_path)
    before = tool.source_hash(repo)
    (repo / "guide" / "node_modules" / "x" / "index.js").write_text("2")
    (repo / "guide" / ".docusaurus").mkdir()
    (repo / "guide" / ".docusaurus" / "cache.json").write_text("{}")
    (repo / "guide" / "build.log").write_text("log")
    (repo / "guide" / "docs" / "intro.md").write_bytes(b"# Hi\r\nthere\r\n")
    assert tool.source_hash(repo) == before


def test_stale_until_stamped(tool, tmp_path):
    repo = _fake_repo(tmp_path)
    out = repo / "docs" / "guide"
    out.mkdir()
    assert tool.is_stale(repo)
    (out / tool.STAMP_NAME).write_text(tool.source_hash(repo) + "\n# note\n")
    assert not tool.is_stale(repo)
