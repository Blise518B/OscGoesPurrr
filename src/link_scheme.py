"""Registers ogp:// as OGP's link type, so a clicked invite opens OGP.

Windows: HKCU\\Software\\Classes\\ogp — the user's own part of the
registry, no admin rights, the way Discord and Steam register theirs.
Linux (the AppImage): a small desktop entry for the x-scheme-handler/ogp
type. Only for the built app: a run from source has no single file to
point at. Re-registered at every start, so a moved exe follows.
"""

import os
import subprocess
import sys
from typing import Callable

SCHEME = "ogp"            # the one place it is spelled (friend_links, link_handoff)
_DESKTOP_NAME = "oscgoespurrr-links.desktop"


def windows_command(exe: str) -> str:
    return f'"{exe}" "%1"'


def desktop_entry(appimage: str) -> str:
    return ("[Desktop Entry]\n"
            "Type=Application\n"
            "Name=OscGoesPurrr friend links\n"
            f'Exec="{appimage}" %u\n'
            "NoDisplay=true\n"
            "MimeType=x-scheme-handler/ogp;\n")


def register(log: Callable[[str], None] = lambda m: None) -> bool:
    """True when ogp:// now opens this OGP."""
    try:
        if sys.platform == "win32":
            return _register_windows(log)
        appimage = os.environ.get("APPIMAGE", "")
        if sys.platform.startswith("linux") and appimage:
            return _register_linux(appimage, log)
    except Exception as e:
        log(f"Friends: couldn't register invite links ({type(e).__name__}: {e})")
    return False


def _register_windows(log) -> bool:
    if not getattr(sys, "frozen", False):
        return False
    import winreg
    exe = os.path.abspath(sys.executable)
    command = windows_command(exe)
    base = rf"Software\Classes\{SCHEME}"
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, base + r"\shell\open\command") as key:
            if winreg.QueryValueEx(key, "")[0] == command:
                return True
    except OSError:
        pass
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, base) as key:
        winreg.SetValueEx(key, "", 0, winreg.REG_SZ, "URL:OscGoesPurrr friend link")
        winreg.SetValueEx(key, "URL Protocol", 0, winreg.REG_SZ, "")
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, base + r"\DefaultIcon") as key:
        winreg.SetValueEx(key, "", 0, winreg.REG_SZ, f'"{exe}",0')
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, base + r"\shell\open\command") as key:
        winreg.SetValueEx(key, "", 0, winreg.REG_SZ, command)
    log("Friends: invite links (ogp://) now open this OGP")
    return True


def _register_linux(appimage: str, log) -> bool:
    apps = os.path.join(os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share"),
                        "applications")
    os.makedirs(apps, exist_ok=True)
    path = os.path.join(apps, _DESKTOP_NAME)
    entry = desktop_entry(appimage)
    try:
        with open(path, encoding="utf-8") as fh:
            if fh.read() == entry:
                return True
    except OSError:
        pass
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(entry)
    subprocess.run(["xdg-mime", "default", _DESKTOP_NAME, "x-scheme-handler/ogp"],
                   check=False, timeout=5, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    log("Friends: invite links (ogp://) now open this OGP")
    return True
