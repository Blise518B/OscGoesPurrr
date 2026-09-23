"""Generate THIRD_PARTY_NOTICES.md: every piece of other people's software
the Windows exe carries, its license, and the notices it asks us to pass on.

OscGoesPurrr's own code is under the MIT license, but the exe also bundles the
Python runtime, PySide6/Qt, the Python packages in requirements.txt (and
what they pull in), the Aldrich font and the Buttplug intiface-engine with
the Rust crates compiled into it. Each keeps its own license; several
(BSD, MIT, Apache, LGPL) require their notice to travel with the binary.
The file is bundled into the exe and shown from Help -> License.

Sources, all read locally:
  * the venv's installed package metadata (license + license files),
  * the engine checkout in _engine_build/buttplug (its LICENSE, plus
    `cargo tree` for the crates in intiface-engine's Windows build).

Run from the project root after changing requirements.txt or rebuilding
the engine:
    venv\\Scripts\\python.exe tools\\make_third_party_notices.py
"""

from __future__ import annotations

import hashlib
import importlib.metadata as md
import os
import re
import subprocess
import sys
from pathlib import Path

from packaging.requirements import Requirement

REPO = Path(__file__).resolve().parent.parent
OUT = REPO / "THIRD_PARTY_NOTICES.md"
ENGINE = REPO / "_engine_build" / "buttplug"
FONT_OFL = REPO / "src" / "Images" / "fonts" / "Aldrich-OFL.txt"
QT_LICENSES = "https://doc.qt.io/qt-6/licenses-used-in-qt.html"

# Full, standard license texts, recognised by their opening line; each is
# printed once at the end instead of once per package that carries it.
STANDARD_TEXTS = (
    ("LGPL-3.0", "GNU LESSER GENERAL PUBLIC LICENSE", "Version 3"),
    ("LGPL-2.1", "GNU LESSER GENERAL PUBLIC LICENSE", "Version 2.1"),
    ("AGPL-3.0", "GNU AFFERO GENERAL PUBLIC LICENSE", "Version 3"),
    ("GPL-3.0", "GNU GENERAL PUBLIC LICENSE", "Version 3"),
    ("Apache-2.0", "Apache License", "Version 2.0"),
    ("MPL-2.0", "Mozilla Public License", "Version 2.0"),
)
TEXT_TITLES = {
    "LGPL-3.0": "GNU Lesser General Public License v3.0",
    "LGPL-2.1": "GNU Lesser General Public License v2.1",
    "AGPL-3.0": "GNU Affero General Public License v3.0",
    "GPL-3.0": "GNU General Public License v3.0 (the LGPL v3 builds on it)",
    "Apache-2.0": "Apache License 2.0",
    "MPL-2.0": "Mozilla Public License 2.0",
    "MIT": "MIT License",
}
MIT_TEXT = """\
Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE."""

# Not in requirements.txt, but PyInstaller's import analysis pulls them into
# the exe through other packages' optional imports (Pillow -> numpy, the
# setuptools runtime hook -> setuptools, packaging). List a built exe's
# third-party modules with PyInstaller's CArchiveReader/ZlibArchiveReader
# to re-check after a dependency change.
ALSO_BUNDLED = ("numpy", "packaging", "setuptools")

# PySide6's wheels only carry a pointer to Qt's commercial terms; the
# license OscGoesPurrr uses them under is the LGPL v3.
QT_FAMILY = {"pyside6", "pyside6-essentials", "pyside6-addons", "shiboken6"}


def _key(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def _standard_kind(text: str) -> str | None:
    head = " ".join(text.split()[:40])
    for kind, title, version in STANDARD_TEXTS:
        if title.lower() in head.lower() and version.lower() in head.lower():
            return kind
    return None


def _fence(text: str) -> str:
    return "```text\n" + text.strip("\n") + "\n```"


def python_packages() -> list[md.Distribution]:
    """requirements.txt, what it pulls in at runtime, and ALSO_BUNDLED."""
    roots = list(ALSO_BUNDLED)
    for line in (REPO / "requirements.txt").read_text(encoding="utf-8").splitlines():
        line = line.split("#", 1)[0].strip()
        if line:
            roots.append(Requirement(line).name)
    seen: dict[str, md.Distribution] = {}
    stack = list(roots)
    while stack:
        name = stack.pop()
        if _key(name) in seen:
            continue
        try:
            dist = md.distribution(name)
        except md.PackageNotFoundError:
            sys.exit(f"{name} is not installed in this venv -- install requirements.txt first")
        seen[_key(name)] = dist
        for req in dist.requires or ():
            r = Requirement(req)
            if r.marker is None or r.marker.evaluate({"extra": ""}):
                stack.append(r.name)
    return sorted(seen.values(), key=lambda d: d.metadata["Name"].lower())


def _license_of(dist: md.Distribution) -> str:
    if _key(dist.metadata["Name"]) in QT_FAMILY:
        return "LGPL-3.0-only"
    m = dist.metadata
    expr = m.get("License-Expression")
    if expr:
        return expr
    lic = (m.get("License") or "").strip()
    if lic and "\n" not in lic and len(lic) < 60:
        return lic
    classifiers = [c.split("::")[-1].strip() for c in m.get_all("Classifier") or ()
                   if c.startswith("License ::")]
    if classifiers:
        return ", ".join(classifiers)
    return lic.splitlines()[0][:60] if lic else "see notice"


def _source_of(dist: md.Distribution) -> str:
    m = dist.metadata
    urls = {}
    for entry in m.get_all("Project-URL") or ():
        label, _, url = entry.partition(",")
        urls[label.strip().lower()] = url.strip()
    for label in ("source", "source code", "repository", "code", "homepage", "home"):
        if label in urls:
            return urls[label]
    return m.get("Home-page") or f"https://pypi.org/project/{m['Name']}/"


def _license_files(dist: md.Distribution) -> list[str]:
    texts = []
    for f in dist.files or ():
        p = str(f)
        if ".dist-info" not in p:
            continue
        if re.search(r"(licen[cs]e|copying|notice)", Path(p).name, re.I) or "/licenses/" in p.replace("\\", "/"):
            try:
                texts.append(Path(dist.locate_file(f)).read_text(encoding="utf-8", errors="replace"))
            except OSError:
                pass
    return texts


def rust_crates() -> list[tuple[str, str, str, bool]]:
    """(crate, version, license, part_of_buttplug) for intiface-engine's
    Windows build. Crates from the Buttplug workspace itself are path
    dependencies; their license is the engine's own."""
    out = subprocess.run(
        ["cargo", "tree", "--offline", "-p", "intiface-engine",
         "--target", "x86_64-pc-windows-msvc", "-e", "normal",
         "--prefix", "none", "--no-dedupe", "-f", "{p}|{l}"],
        cwd=ENGINE, capture_output=True, text=True, check=True).stdout
    crates = set()
    for line in out.splitlines():
        if "|" not in line:
            continue
        pkg, lic = line.rsplit("|", 1)
        local = bool(re.search(r"\([A-Za-z]:[\\/]", pkg))
        pkg = re.sub(r"\s*\(.*\)\s*$", "", pkg).strip()   # drop local paths / git urls
        name, _, version = pkg.partition(" v")
        if name and name != "intiface-engine":
            crates.add((name, version, lic.strip() or "see crate", local))
    return sorted(crates)


def _mit_or_apache(expr: str) -> bool:
    """True when the crate can be taken under plain MIT or Apache-2.0."""
    if " AND " in expr:
        return False
    alts = re.split(r"\s+OR\s+|\s*/\s*", expr.replace("(", "").replace(")", ""))
    return any(a.strip() in ("MIT", "Apache-2.0") for a in alts)


def _crate_license_files(name: str, version: str, expr: str) -> list[str] | None:
    """The crate's own license/notice files from the local cargo registry,
    MIT's copy preferred when the crate offers MIT or Apache."""
    home = Path(os.environ.get("CARGO_HOME") or Path.home() / ".cargo")
    dirs = sorted((home / "registry" / "src").glob(f"*/{name}-{version}"))
    if not dirs:
        return None
    files = sorted(p for p in dirs[0].iterdir()
                   if p.is_file() and re.match(r"(licen[cs]e|copying|notice|copyright)", p.name, re.I))
    if _mit_or_apache(expr):
        mit = [p for p in files if "mit" in p.name.lower()]
        notice = [p for p in files if re.match(r"notice", p.name, re.I)]
        if mit:
            files = mit + notice
    return [p.read_text(encoding="utf-8", errors="replace") for p in files]


def engine_source() -> tuple[str, bool]:
    """The engine checkout's commit, and whether it has local changes."""
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ENGINE,
                          capture_output=True, text=True, check=True).stdout.strip()
    dirty = bool(subprocess.run(["git", "status", "--porcelain", "--untracked-files=no"],
                                cwd=ENGINE, capture_output=True, text=True, check=True).stdout.strip())
    return head, dirty


def main() -> int:
    if not (ENGINE / "Cargo.toml").exists():
        print(f"engine checkout not found at {ENGINE} -- see tools/rebuild_intiface_engine.bat",
              file=sys.stderr)
        return 1

    engine_ver = re.search(r'^version\s*=\s*"([^"]+)"',
                           (ENGINE / "crates" / "intiface_engine" / "Cargo.toml")
                           .read_text(encoding="utf-8"), re.M).group(1)
    try:
        pyi_ver = md.version("pyinstaller")
    except md.PackageNotFoundError:
        pyi_ver = "-"
    py_ver = ".".join(map(str, sys.version_info[:3]))
    dists = python_packages()
    crates = rust_crates()
    commit, dirty = engine_source()
    if dirty:
        print("warning: the engine checkout has local changes -- the notice says it is unmodified",
              file=sys.stderr)
    copyleft = sorted({(c, lic) for c, _, lic, local in crates
                       if not local and re.search(r"\bA?GPL", lic) and not _mit_or_apache(lic)})

    needed: dict[str, str] = {}          # standard texts to print at the end
    seen_text: dict[str, str] = {}       # hash -> first component carrying it
    rows = [
        ("Python", py_ver, "PSF-2.0", "https://www.python.org/"),
        ("intiface-engine (Buttplug)", engine_ver,
         "BSD-3-Clause" + "".join(f"; contains {c} under {lic}" for c, lic in copyleft),
         f"https://github.com/buttplugio/buttplug/tree/{commit}"),
        ("PyInstaller bootloader", pyi_ver, "GPL-2.0-or-later WITH Bootloader-exception",
         "https://github.com/pyinstaller/pyinstaller"),
        ("Aldrich font", "-", "OFL-1.1", "https://fonts.google.com/specimen/Aldrich"),
    ]
    rows += [(d.metadata["Name"], d.version, _license_of(d), _source_of(d)) for d in dists]

    notices: list[str] = []

    def add_notice(title: str, texts: list[str]):
        parts = []
        for text in texts:
            kind = _standard_kind(text)
            if kind:
                needed.setdefault(kind, text)
                parts.append(f"Licensed under the {TEXT_TITLES[kind]} -- full text below.")
                continue
            digest = hashlib.sha1(text.strip().encode()).hexdigest()
            if digest in seen_text:
                parts.append(f"Same notice as {seen_text[digest]}.")
                continue
            seen_text[digest] = title
            parts.append(_fence(text))
        if parts:
            notices.append(f"### {title}\n\n" + "\n\n".join(parts))

    py_license = Path(sys.base_prefix) / "LICENSE.txt"
    if py_license.exists():
        add_notice(f"Python {py_ver}", [py_license.read_text(encoding="utf-8", errors="replace")])
    add_notice(f"intiface-engine {engine_ver}", [(ENGINE / "LICENSE").read_text(encoding="utf-8")])
    add_notice("Aldrich font", [FONT_OFL.read_text(encoding="utf-8")])
    for d in dists:
        name = d.metadata["Name"]
        if _key(name) in QT_FAMILY:
            notices.append(
                f"### {name} {d.version}\n\nUsed under the GNU Lesser General Public License "
                f"v3.0 -- full text below. Qt itself includes further third-party components, "
                f"listed at {QT_LICENSES}. OscGoesPurrr's source is public, so you can run it "
                f"against any compatible PySide6 build of your own (README -> Running from source).")
            continue
        add_notice(f"{name} {d.version}", _license_files(d))

    # the Qt family and every LGPL v3 component need both GNU texts
    lgpl3 = [t for d in dists for t in _license_files(d) if _standard_kind(t) == "LGPL-3.0"]
    gpl3 = [t for d in dists for t in _license_files(d) if _standard_kind(t) == "GPL-3.0"]
    if lgpl3:
        needed.setdefault("LGPL-3.0", lgpl3[0])
    if gpl3:
        needed.setdefault("GPL-3.0", gpl3[0])
    if any("MIT" in lic for _, _, lic, _ in crates):
        needed.setdefault("MIT", MIT_TEXT)
    if any("Apache-2.0" in lic for _, _, lic, _ in crates) and "Apache-2.0" not in needed:
        print("warning: no Apache-2.0 text found among the Python packages", file=sys.stderr)

    # every third-party crate's own notice (the Buttplug workspace crates are
    # covered by the engine's LICENSE above)
    first_crate_notice = len(notices)
    missing = []
    for c, v, lic, local in crates:
        if local:
            continue
        texts = _crate_license_files(c, v, lic)
        if texts is None:
            missing.append(c)
        elif texts:
            add_notice(f"{c} {v} ({lic})", texts)
    crate_notices = notices[first_crate_notice:]
    del notices[first_crate_notice:]
    if missing:
        print(f"warning: no local source for {', '.join(missing)}", file=sys.stderr)

    lines = [
        "<!-- Generated by tools/make_third_party_notices.py: regenerate, don't edit. -->",
        "# Third-party notices",
        "",
        "OscGoesPurrr is [MIT](LICENSE)-licensed. It also includes these open-source",
        "projects, each under its own license.",
        "",
        "## What the exe contains",
        "",
        "| Component | Version | License | Source |",
        "|---|---|---|---|",
    ]
    lines += [f"| {n} | {v} | {lic} | {src} |" for n, v, lic, src in rows]
    lines += [
        "",
        "## Source for intiface-engine",
        "",
        "The bundled `intiface-engine.exe` is built, unmodified, from Buttplug commit",
        f"[`{commit[:12]}`](https://github.com/buttplugio/buttplug/tree/{commit})",
        "by this repository's `tools/rebuild_intiface_engine.bat`, which only adds compiler flags",
        "that strip build-machine paths. It runs as its own process next to OscGoesPurrr.",
    ]
    for c, lic in copyleft:
        lines += [
            "",
            f"It contains the `{c}` crate, licensed {lic}: that commit plus the build script",
            "are the complete corresponding source for the engine binary, and both stay",
            "publicly available at the links above.",
        ]
    lines += ["", "## Notices", ""]
    lines += ["\n\n".join(notices), ""]
    lines += [
        "## Rust crates inside intiface-engine",
        "",
        "intiface-engine is compiled with these crates. Where a crate offers a choice",
        "(`MIT OR Apache-2.0`), either applies. `buttplug*` crates are Buttplug's own and",
        "covered by the engine's license above; every other crate's notice follows the table.",
        "",
        "| Crate | Version | License |",
        "|---|---|---|",
    ]
    lines += [f"| {c} | {v} | {lic} |" for c, v, lic, _ in crates]
    lines += ["", "### Crate notices", ""]
    lines += ["\n\n".join(n.replace("### ", "#### ", 1) for n in crate_notices), ""]
    lines += ["", "## License texts", ""]
    for kind in ("LGPL-3.0", "GPL-3.0", "LGPL-2.1", "AGPL-3.0", "Apache-2.0", "MPL-2.0", "MIT"):
        if kind in needed:
            lines += [f"### {TEXT_TITLES[kind]}", "", _fence(needed[kind]), ""]

    OUT.write_text("\n".join(lines), encoding="utf-8", newline="\n")
    print(f"wrote {OUT.name}: {len(rows)} components, {len(crates)} crates, "
          f"{len(needed)} license texts")
    return 0


if __name__ == "__main__":
    sys.exit(main())
