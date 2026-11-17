"""Build the user guide (guide/, Docusaurus) into docs/guide/.

GitHub Pages serves /docs on the public main, so the built guide is
committed there and goes live at .../OscGoesPurrr/guide/ with the next
release, next to the website. This script:

  1. installs the guide's packages with `npm ci` (the pinned versions in
     guide/package-lock.json) when node_modules is missing or older than
     the lock file -- or always, with --ci;
  2. runs `docusaurus build` into guide/build/;
  3. replaces docs/guide/ with that build, and writes
     docs/guide/guide-sources.sha256: a hash of everything the build read
     (guide/ and the site files it takes: tokens.css, the icon, the font).

tests/test_guide_build.py compares that hash with the sources as they are,
so a guide changed without a rebuild fails the tests -- like the engine's
device list does.

No console windows: node and npm are started with CREATE_NO_WINDOW and
their output goes to guide/build.log (and to stdout when there is one).
Run it with the venv's Python (pythonw works too):

    venv\\Scripts\\pythonw.exe tools\\build_guide.py
    venv\\Scripts\\python.exe tools\\build_guide.py --check   # stale? exit 1

Needs Node 20 or newer. The screenshots are not made here: run
tools/make_guide_images.py first when a page of the app changed.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
GUIDE = REPO / "guide"
OUT = REPO / "docs" / "guide"
STAMP_NAME = "guide-sources.sha256"
LOG = GUIDE / "build.log"

# What the build reads from outside guide/ (docusaurus.config.js,
# plugins/tokens518.js): the site's colours, icon and font
SITE_INPUTS = ("docs/assets/tokens.css", "docs/assets/ogp-icon.svg", "docs/assets/fonts")

# Never sources: installed packages, Docusaurus' caches, the build, logs
SKIP_DIRS = {"node_modules", ".docusaurus", ".cache-loader", "build", "__pycache__"}
SKIP_FILES = {".DS_Store", "Thumbs.db"}
SKIP_SUFFIXES = (".log",)
# Hashed with CRLF read as LF, so a Windows checkout (core.autocrlf) and a
# Linux one agree
TEXT_SUFFIXES = {".md", ".mdx", ".js", ".jsx", ".ts", ".tsx", ".css", ".json", ".txt",
                 ".svg", ".html", ".yml", ".yaml", ".gitignore"}


# ---- the sources and their hash ---------------------------------------------

def source_files(repo: Path = REPO) -> list[Path]:
    """Every file the guide's build reads, sorted by its repo path."""
    out = []
    roots = [repo / "guide"] + [repo / p for p in SITE_INPUTS]
    for root in roots:
        if root.is_file():
            out.append(root)
            continue
        if not root.is_dir():
            continue
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS)
            for name in filenames:
                if name in SKIP_FILES or name.endswith(SKIP_SUFFIXES):
                    continue
                out.append(Path(dirpath) / name)
    return sorted(set(out), key=lambda p: p.relative_to(repo).as_posix())


def _content(path: Path) -> bytes:
    data = path.read_bytes()
    if path.suffix.lower() in TEXT_SUFFIXES or path.name == ".gitignore":
        data = data.replace(b"\r\n", b"\n")
    return data


def source_hash(repo: Path = REPO) -> str:
    """sha256 over every source file's repo path and content."""
    h = hashlib.sha256()
    for path in source_files(repo):
        data = _content(path)
        rel = path.relative_to(repo).as_posix().encode("utf-8")
        h.update(rel + b"\0" + str(len(data)).encode() + b"\0" + data)
    return h.hexdigest()


def stamped_hash(out: Path = OUT) -> str:
    """The hash docs/guide/ was built from ("" when there is none)."""
    try:
        first = (out / STAMP_NAME).read_text(encoding="utf-8").split()
    except OSError:
        return ""
    return first[0] if first else ""


def is_stale(repo: Path = REPO) -> bool:
    return stamped_hash(repo / "docs" / "guide") != source_hash(repo)


# ---- node, without a console window -----------------------------------------

def find_node() -> str:
    exe = shutil.which("node")
    if exe:
        return exe
    for guess in (r"C:\Program Files\nodejs\node.exe", "/usr/bin/node", "/usr/local/bin/node"):
        if os.path.isfile(guess):
            return guess
    raise SystemExit("node was not found: install Node 20 or newer (nodejs.org)")


def find_npm_cli(node: str) -> str:
    """npm's own JavaScript entry, run with node directly: no npm.cmd, so no
    cmd.exe in between."""
    base = Path(node).resolve().parent
    for cand in (base / "node_modules" / "npm" / "bin" / "npm-cli.js",
                 base.parent / "lib" / "node_modules" / "npm" / "bin" / "npm-cli.js"):
        if cand.is_file():
            return str(cand)
    raise SystemExit(f"npm-cli.js was not found next to {node}")


class Log:
    def __init__(self, path: Path):
        self.fh = open(path, "w", encoding="utf-8", errors="replace")

    def say(self, text: str) -> None:
        self.fh.write(text + "\n")
        self.fh.flush()
        if sys.stdout is not None:
            enc = getattr(sys.stdout, "encoding", None) or "utf-8"
            try:
                print(text.encode(enc, "replace").decode(enc), flush=True)
            except (OSError, ValueError):
                pass

    def run(self, args: list[str], cwd: Path) -> int:
        self.say("$ " + " ".join(Path(a).name if i == 0 else a for i, a in enumerate(args)))
        env = dict(os.environ)
        env.setdefault("NO_UPDATE_NOTIFIER", "1")
        env.setdefault("npm_config_update_notifier", "false")
        env.setdefault("npm_config_fund", "false")
        env.setdefault("npm_config_audit", "false")
        env["NO_COLOR"] = "1"           # plain text in the log
        env["FORCE_COLOR"] = "0"
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        proc = subprocess.Popen(args, cwd=str(cwd), env=env, stdin=subprocess.DEVNULL,
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                creationflags=flags)
        for raw in proc.stdout:
            self.say(raw.decode("utf-8", "replace").rstrip())
        return proc.wait()


def needs_install(guide: Path = GUIDE) -> bool:
    installed = guide / "node_modules" / ".package-lock.json"
    lock = guide / "package-lock.json"
    return not installed.is_file() or installed.stat().st_mtime < lock.stat().st_mtime


# ---- the build ----------------------------------------------------------------

def copy_build(build: Path, out: Path, digest: str) -> None:
    """docs/guide/ becomes the build, plus the stamp."""
    if not (build / "index.html").is_file():
        raise SystemExit(f"{build} has no index.html: the build did not finish")
    if out.exists():
        if out.resolve().parent != (REPO / "docs").resolve():
            raise SystemExit(f"refusing to replace {out}")
        shutil.rmtree(out)
    shutil.copytree(build, out)
    (out / STAMP_NAME).write_text(
        f"{digest}\n# sha256 of the guide's sources (guide/ and {', '.join(SITE_INPUTS)}),\n"
        "# written by tools/build_guide.py; tests/test_guide_build.py checks it\n",
        encoding="utf-8", newline="\n")


def build(ci: bool = False, install: bool = True) -> int:
    log = Log(LOG)
    started = time.monotonic()
    node = find_node()
    npm = find_npm_cli(node)
    if install and (ci or needs_install()):
        if log.run([node, npm, "ci", "--no-audit", "--no-fund"], GUIDE) != 0:
            log.say("npm ci failed")
            return 1
    digest = source_hash()
    docusaurus = GUIDE / "node_modules" / "@docusaurus" / "core" / "bin" / "docusaurus.mjs"
    if not docusaurus.is_file():
        log.say("Docusaurus isn't installed: run without --no-install")
        return 1
    if log.run([node, str(docusaurus), "build", "--out-dir", "build"], GUIDE) != 0:
        log.say("docusaurus build failed")
        return 1
    if source_hash() != digest:
        log.say("the sources changed during the build: run it again")
        return 1
    copy_build(GUIDE / "build", OUT, digest)
    log.say(f"docs/guide/ rebuilt ({sum(1 for _ in OUT.rglob('*.html'))} pages, "
            f"{time.monotonic() - started:.0f} s), sources {digest[:12]}")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--check", action="store_true",
                    help="only say whether docs/guide/ is older than its sources (exit 1 if so)")
    ap.add_argument("--ci", action="store_true", help="always run npm ci first")
    ap.add_argument("--no-install", action="store_true", help="never run npm ci")
    args = ap.parse_args(argv)
    if args.check:
        stale = is_stale()
        if sys.stdout is not None:
            print("docs/guide/ is older than guide/: run tools/build_guide.py" if stale
                  else "docs/guide/ is up to date")
        return 1 if stale else 0
    return build(ci=args.ci, install=not args.no_install)


if __name__ == "__main__":
    sys.exit(main())
