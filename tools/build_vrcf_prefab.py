"""Build docs/unity/OscGoesPurrr-VRCFury.unitypackage -- the VRCFury prefabs
that put the OGP menu on an avatar when one is dragged onto it: Both (your
own controls and the Friends menu), Self only and Friends only, with the
icons in docs/unity/icons/ (tools/make_menu_icons.py).

Unity does the work. This copies tools/unity/ (the builder and its asmdef)
and docs/unity/OGP_MenuInstaller.cs (the menu and parameters both share)
into a throwaway Editor folder of an avatar project that has the VRChat SDK
and VRCFury, runs the builder headless and takes the folder out again. The
builder exports the package, imports it back and runs VRChat's upload
preprocess on test avatars; its report is printed at the end, and the
committed package is only replaced when every check passed.

Run from the project root:
    venv\\Scripts\\python.exe tools\\build_vrcf_prefab.py "C:\\path\\to\\AvatarProject"

The project must be closed in Unity and must not have Assets/OGP (the
folder the package brings) -- a scratch copy is best. The package
is committed, so a release never depends on this script; re-run it whenever
the menu or parameters in OGP_MenuInstaller.cs change.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from PIL import Image

REPO = Path(__file__).resolve().parent.parent
ICON = REPO / "src" / "Images" / "OGP_Icon.ico"
ICONS = REPO / "docs" / "unity" / "icons"
SOURCES = (
    REPO / "tools" / "unity" / "OgpVrcfPrefabBuilder.cs",
    REPO / "tools" / "unity" / "OscGoesPurrr.PrefabBuild.asmdef",
    REPO / "docs" / "unity" / "OGP_MenuInstaller.cs",
)
DST = REPO / "docs" / "unity" / "OscGoesPurrr-VRCFury.unitypackage"
METHOD = "OscGoesPurrr.Build.OgpVrcfPrefabBuilder.BuildFromCommandLine"
TEMP_FOLDER = "OGP_PrefabBuild_Temp"   # under the project's Assets/
PACKAGE_FOLDER = "OGP"   # where the package lands: Assets/OGP
NEEDS = ("com.vrcfury.vrcfury", "com.vrchat.avatars")
TIMEOUT_S = 30 * 60   # a first open of a big avatar project imports for a while


def fail(message: str) -> None:
    print(f"error: {message}")
    sys.exit(1)


def editor_version(project: Path) -> str:
    text = (project / "ProjectSettings" / "ProjectVersion.txt").read_text()
    for line in text.splitlines():
        if line.startswith("m_EditorVersion:"):
            return line.split(":", 1)[1].strip()
    fail(f"no m_EditorVersion in {project}\\ProjectSettings\\ProjectVersion.txt")


def find_unity(version: str) -> Path:
    if os.environ.get("UNITY_EXE"):
        return Path(os.environ["UNITY_EXE"])
    roots = [Path(os.environ.get("ProgramFiles", r"C:\Program Files"))
             / "Unity" / "Hub" / "Editor"]
    # Unity Hub's "install location" setting, when editors live elsewhere.
    extra = (Path(os.environ.get("APPDATA", "")) / "UnityHub"
             / "secondaryInstallPath.json")
    if extra.is_file():
        try:
            path = json.loads(extra.read_text(encoding="utf-8"))
            if path:
                roots.append(Path(path))
        except ValueError:
            pass
    for root in roots:
        exe = root / version / "Editor" / "Unity.exe"
        if exe.is_file():
            return exe
    fail(f"Unity {version} not found under {', '.join(map(str, roots))} "
         "(or set UNITY_EXE)")


def is_open_in_unity(project: Path) -> bool:
    # A running editor keeps Temp/UnityLockfile open without sharing it.
    lock = project / "Temp" / "UnityLockfile"
    if not lock.exists():
        return False
    try:
        with open(lock, "a"):
            return False
    except PermissionError:
        return True


def write_icon(path: Path) -> None:
    with Image.open(ICON) as ico:
        biggest = max(ico.ico.sizes())
        ico.ico.getimage(biggest).convert("RGBA").save(path)


def main() -> None:
    # The report quotes the menu's emoji; a Windows console is cp1252.
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if len(sys.argv) != 2:
        fail("usage: build_vrcf_prefab.py <Unity avatar project>")
    project = Path(sys.argv[1]).resolve()
    assets = project / "Assets"
    if not assets.is_dir():
        fail(f"{project} is not a Unity project")
    missing = [name for name in NEEDS if not (project / "Packages" / name).is_dir()]
    if missing:
        fail(f"{project} lacks {', '.join(missing)}")
    if (assets / PACKAGE_FOLDER).exists():
        fail(f"{assets}\\{PACKAGE_FOLDER} already exists -- build in a project "
             "without it (the builder deletes that folder when it is done)")
    if is_open_in_unity(project):
        fail(f"{project} is open in Unity; close it first")
    unity = find_unity(editor_version(project))

    work = Path(tempfile.mkdtemp(prefix="ogp_vrcf_prefab_"))
    icon = work / "OGP_MenuIcon.png"
    package = work / DST.name
    report = work / "report.txt"
    log = work / "unity.log"
    write_icon(icon)

    temp = assets / TEMP_FOLDER
    editor = temp / "Editor"
    editor.mkdir(parents=True)
    for src in SOURCES:
        shutil.copy2(src, editor / src.name)

    print(f"building with {unity}\n  in {project}\n  log {log}")
    try:
        result = subprocess.run(
            [str(unity), "-batchmode", "-nographics",
             "-projectPath", str(project),
             "-executeMethod", METHOD,
             "-logFile", str(log),
             "-ogpOut", str(package),
             "-ogpIcon", str(icon),
             "-ogpIcons", str(ICONS),
             "-ogpReport", str(report)],
            timeout=TIMEOUT_S,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        code = result.returncode
    except subprocess.TimeoutExpired:
        code = None
    finally:
        shutil.rmtree(temp, ignore_errors=True)
        Path(str(temp) + ".meta").unlink(missing_ok=True)
        # Only there if the builder stopped half-way; it was not there
        # before (checked above).
        shutil.rmtree(assets / PACKAGE_FOLDER, ignore_errors=True)
        (assets / f"{PACKAGE_FOLDER}.meta").unlink(missing_ok=True)

    if report.is_file():
        print(report.read_text(encoding="utf-8"))
    else:
        errors = [line for line in log.read_text(encoding="utf-8", errors="replace")
                  .splitlines() if "error CS" in line or "Exception" in line]
        print("the builder wrote no report; from the Unity log:")
        print("\n".join(errors[:30]) or "  (nothing that looks like an error)")
    if code is None:
        fail(f"Unity did not finish within {TIMEOUT_S // 60} minutes")
    if code != 0:
        fail(f"Unity exited with {code}; {DST.name} left unchanged")
    shutil.copy2(package, DST)
    print(f"wrote {DST.relative_to(REPO)} ({DST.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
