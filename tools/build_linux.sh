#!/usr/bin/env bash
# ===========================================================================
#  Build the Linux release: dist/OscGoesPurrr-Linux-x86_64.AppImage
#  (+ its .zsync, for AppImage update tools).
#
#  GitHub Actions runs this for every published release
#  (.github/workflows/linux.yml) and attaches both files to it; the Windows
#  exe still comes from tools\release.bat. It runs the same on any x86_64
#  Linux with Python 3.10+ (python3-venv), git, curl, and -- unless the
#  engine binary is already in place -- Rust, pkg-config, libdbus-1-dev
#  and libudev-dev.
#
#  1. The built-in Intiface engine, compiled from exactly the Buttplug
#     commit THIRD_PARTY_NOTICES.md names (its notice promises that), with
#     the Windows engine's Cargo.lock (tools/intiface-engine-Cargo.lock).
#     Skipped when src/intiface-engine/intiface-engine already exists --
#     CI restores it from its cache.
#  2. A venv with the pinned dependencies, and the test suite.
#  3. PyInstaller, --onedir: the AppImage is already the single file, and a
#     onedir inside it starts in a second instead of unpacking ~200 MB to
#     /tmp on every launch.
#  4. The AppDir, packed by appimagetool with GitHub update information.
#
#  Environment: PYTHON (default python3), OGP_BUILD (the b<n> build
#  number; default: from the public commit's "Build <n>" line, else the
#  git commit count), SKIP_TESTS=1.
# ===========================================================================
set -euo pipefail
cd "$(dirname "$0")/.."

APP=OscGoesPurrr
ARCH=x86_64
REPO_SLUG="Blise518B|OscGoesPurrr"
OUT_NAME="$APP-Linux-$ARCH.AppImage"
WORK=_linux_build
PY=${PYTHON:-python3}
ENGINE=src/intiface-engine/intiface-engine

say() { printf '\n=== %s ===\n' "$*"; }
die() { printf '[ERROR] %s\n' "$*" >&2; exit 1; }

[ "$(uname -m)" = "$ARCH" ] || die "this builds the $ARCH AppImage; this machine is $(uname -m)"
mkdir -p "$WORK" dist

# ---- 1. Intiface engine --------------------------------------------------
if [ ! -f "$ENGINE" ]; then
    COMMIT=$(grep -oE 'buttplug/tree/[0-9a-f]{40}' THIRD_PARTY_NOTICES.md | head -n1 | cut -d/ -f3)
    [ -n "$COMMIT" ] || die "THIRD_PARTY_NOTICES.md names no Buttplug commit"
    say "Building intiface-engine at Buttplug $COMMIT"
    SRC="$WORK/buttplug"
    if [ ! -d "$SRC/.git" ]; then
        git init -q "$SRC"
        git -C "$SRC" remote add origin https://github.com/buttplugio/buttplug
    fi
    git -C "$SRC" fetch -q --depth 1 origin "$COMMIT"
    git -C "$SRC" checkout -q --detach FETCH_HEAD
    # Buttplug doesn't commit a Cargo.lock. This is the one the Windows
    # engine was built with (make_third_party_notices.py keeps the copy in
    # step), so both engines carry the same crate versions the notice lists.
    cp tools/intiface-engine-Cargo.lock "$SRC/Cargo.lock"
    # Keep build-machine paths out of the binary, like the Windows build.
    CARGO_HOME_DIR=${CARGO_HOME:-$HOME/.cargo}
    SRC_ABS=$(cd "$SRC" && pwd)
    export RUSTFLAGS="--remap-path-prefix=$CARGO_HOME_DIR=/cargo --remap-path-prefix=$SRC_ABS=/buttplug --remap-path-prefix=$HOME=/home"
    export CFLAGS="-ffile-prefix-map=$CARGO_HOME_DIR=/cargo -ffile-prefix-map=$HOME=/home"
    (cd "$SRC" && cargo build --release --locked --bin intiface-engine)
    install -m 755 "$SRC/target/release/intiface-engine" "$ENGINE"
fi
chmod 755 "$ENGINE"
"$ENGINE" --version || die "the engine binary does not run"

# ---- 2. venv, dependencies, tests ----------------------------------------
say "Python dependencies"
VENV="$WORK/venv"
[ -x "$VENV/bin/python" ] || "$PY" -m venv "$VENV"
VPY="$VENV/bin/python"
"$VPY" -m pip install -q --upgrade pip
"$VPY" -m pip install -q -r requirements.txt -r requirements-dev.txt pyinstaller -c constraints.txt

if [ "${SKIP_TESTS:-}" != "1" ]; then
    say "Tests"
    # test_site_ports.py checks the website's JavaScript against the Python
    # number for number; glibc's maths rounds a few hues of near-greys
    # differently from Windows', so it only holds where release.bat runs
    # it. The website isn't part of this build.
    QT_QPA_PLATFORM=offscreen "$VPY" -m pytest -q -p no:cacheprovider \
        --ignore=tests/test_site_ports.py
fi

# ---- 3. PyInstaller ------------------------------------------------------
say "PyInstaller"
rm -f src/_version_baked.py
trap 'rm -f src/_version_baked.py' EXIT
if [ -z "${OGP_BUILD:-}" ]; then
    # release.bat writes the build number into the public commit, so the
    # AppImage shows the same b<n> as the exe of that release.
    OGP_BUILD=$(git log -1 --format=%B 2>/dev/null | sed -n 's/^Build \([0-9][0-9]*\)$/\1/p' | head -n1 || true)
fi
OGP_BUILD="$OGP_BUILD" "$VPY" - <<'EOF'
import os, sys
sys.path.insert(0, "src")
from version import __version__ as v, _SHORT_HASH as h, build_number
b = int(os.environ.get("OGP_BUILD") or build_number())
with open("src/_version_baked.py", "w", encoding="utf-8") as fh:
    fh.write(f"VERSION = {v!r}\nSHORT_HASH = {h!r}\nBUILD = {b!r}\n")
print(f"Version {v} b{b}")
EOF

ROOT=$(pwd)
rm -rf "$WORK/pyi-dist"
# pystray is the Windows tray; Linux uses Qt's (main.py imports it only
# on Windows). The SteamVR driver is a Windows DLL and stays out. Python's
# readline/curses modules would pull in GPL readline; the app has no
# console to use them.
"$VPY" -m PyInstaller --noconfirm --log-level WARN \
    --onedir --windowed --name "$APP" \
    --distpath "$WORK/pyi-dist" --workpath "$WORK/pyi-work" --specpath "$WORK" \
    --exclude-module pystray --exclude-module readline \
    --exclude-module curses --exclude-module _curses \
    --add-data "$ROOT/src/Images:Images" \
    --add-data "$ROOT/LICENSE:." \
    --add-data "$ROOT/THIRD_PARTY_NOTICES.md:." \
    --add-data "$ROOT/src/intiface-engine:intiface-engine" \
    src/main.py

# ---- 4. AppImage ---------------------------------------------------------
say "AppImage"
APPDIR="$WORK/AppDir"
rm -rf "$APPDIR"
mkdir -p "$APPDIR/usr/lib"
cp -a "$WORK/pyi-dist/$APP" "$APPDIR/usr/lib/$APP"
INTERNAL="$APPDIR/usr/lib/$APP/_internal"
# --add-data copies files without their exec bit, and the AppImage is a
# read-only mount where the app can't add it back.
chmod 755 "$INTERNAL/intiface-engine/intiface-engine"

# Libraries every desktop has, where the system's own copy has to win
# over the build machine's older one:
#   libstdc++ / libgcc_s - the system's GPU drivers load into our process
#     and need its newer libstdc++; an older one in front of it breaks them;
#   OpenSSL - an older OpenSSL can reject the system's config (Fedora's
#     crypto policies) and then HTTPS, the update check, fails;
#   fontconfig / freetype / expat - an older fontconfig misreads a newer
#     system's font configuration.
for lib in libstdc++.so.6 libgcc_s.so.1 libssl.so.3 libcrypto.so.3 \
           libfontconfig.so.1 libfreetype.so.6 libexpat.so.1; do
    rm -f "$INTERNAL/$lib"
done
# Qt's GTK3 theme would load the system's GTK next to our older GLib, a
# classic AppImage crash on GNOME. The app draws its own theme anyway.
rm -f "$INTERNAL/PySide6/Qt/plugins/platformthemes/libqgtk3.so"

# The system libraries that stay in come from this machine's packages:
# list them in the bundled notice and carry each package's copyright file.
NOTICE="$INTERNAL/THIRD_PARTY_NOTICES.md"
if command -v dpkg >/dev/null; then
    DISTRO=$(. /etc/os-release && echo "$PRETTY_NAME")
    {
        echo
        echo "## System libraries in the Linux AppImage"
        echo
        echo "Qt and Python need these libraries, which the AppImage carries from $DISTRO."
        echo "Each package's copyright and license text is inside the AppImage at"
        echo "\`usr/share/doc/<package>/copyright\` (the Debian source is at https://launchpad.net/ubuntu/+source/<source>)."
        echo
        echo "| Library | Package | Source | Version |"
        echo "|---|---|---|---|"
    } >> "$NOTICE"
    for f in "$INTERNAL"/*.so*; do
        lib=$(basename "$f")
        # Libraries from wheels (PySide6, Pillow, Python itself) aren't
        # packages here; their own notices above cover them.
        pkg=$(dpkg -S "*/$lib" 2>/dev/null | grep -v ' /usr/share/' | head -n1 | cut -d: -f1 || true)
        case "$pkg" in ""|*,*) continue ;; esac
        src=$(dpkg-query -W -f='${source:Package}' "$pkg" 2>/dev/null) || continue
        ver=$(dpkg-query -W -f='${Version}' "$pkg" 2>/dev/null) || continue
        echo "| $lib | $pkg | $src | $ver |" >> "$NOTICE"
        if [ -f "/usr/share/doc/$pkg/copyright" ]; then
            mkdir -p "$APPDIR/usr/share/doc/$pkg"
            cp "/usr/share/doc/$pkg/copyright" "$APPDIR/usr/share/doc/$pkg/copyright"
        fi
    done
fi

cat > "$APPDIR/AppRun" <<'EOF'
#!/bin/sh
HERE="$(dirname "$(readlink -f "$0")")"
exec "$HERE/usr/lib/OscGoesPurrr/OscGoesPurrr" "$@"
EOF
chmod 755 "$APPDIR/AppRun"

cat > "$APPDIR/$APP.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=$APP
Comment=VRChat OSC to toys, through Intiface
Exec=$APP
Icon=$APP
Categories=Utility;
Terminal=false
EOF

"$VPY" - "$APPDIR/$APP.png" <<'EOF'
import sys
from PIL import Image
ico = Image.open("src/Images/OGP_Icon.ico").ico
icon = ico.getimage(max(ico.sizes()))      # the .ico's own 256 px drawing
icon.convert("RGBA").resize((256, 256), Image.LANCZOS).save(sys.argv[1])
EOF
ln -sf "$APP.png" "$APPDIR/.DirIcon"

TOOL="$WORK/appimagetool-$ARCH.AppImage"
if [ ! -x "$TOOL" ]; then
    curl -fsSL -o "$TOOL" "https://github.com/AppImage/appimagetool/releases/download/continuous/appimagetool-$ARCH.AppImage"
    chmod 755 "$TOOL"
fi
rm -f "dist/$OUT_NAME" "dist/$OUT_NAME.zsync" "$OUT_NAME.zsync"
# Extract-and-run: works without FUSE (containers, some CI runners).
APPIMAGE_EXTRACT_AND_RUN=1 ARCH=$ARCH "$TOOL" --no-appstream \
    -u "gh-releases-zsync|$REPO_SLUG|latest|$OUT_NAME.zsync" \
    "$APPDIR" "dist/$OUT_NAME"
# appimagetool writes the .zsync into the current folder.
[ -f "$OUT_NAME.zsync" ] && mv "$OUT_NAME.zsync" dist/
chmod 755 "dist/$OUT_NAME"

say "Done"
ls -l "dist/$OUT_NAME" dist/"$OUT_NAME".zsync 2>/dev/null || true
