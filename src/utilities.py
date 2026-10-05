import ctypes
import json
import math
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Optional, Union


def atomic_write_json(path: Union[str, Path], data: Any, **dumps_kwargs) -> None:
    """Write `data` as JSON to `path` so a crash mid-write can't truncate the
    target. Writes to a sibling `.tmp` file, fsyncs, then `os.replace`s it
    onto the real path (atomic on every OS we ship to).

    `dumps_kwargs` are forwarded to `json.dumps` — pass `indent=2`, etc.

    The tmp file is placed in the same directory as the target so the replace
    stays on one filesystem (Windows `os.replace` cross-volume is an error).
    """
    target = Path(path)
    tmp = target.with_name(target.name + ".tmp")
    body = json.dumps(data, **dumps_kwargs)
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(body)
        f.flush()
        try:
            os.fsync(f.fileno())
        except OSError:
            # fsync isn't available on every Python build / FS; the replace
            # is still atomic, just a touch less durable.
            pass
    os.replace(tmp, target)


def normalize_osc_value(v: float) -> float:
    """Normalizes an incoming OSC float (0.0 to 1.0) or int (0 to 255) to a
    safe 0.0-1.0 range.

    Only genuine ints get the 0-255 byte rescale; a float slightly above 1.0
    saturates at 1.0 instead of collapsing to v/255. Non-finite (NaN/inf) and
    non-numeric values return 0.0 — this sits on the hot input path for
    custom addresses and SPS proximity, and NaN must never reach a device.
    """
    try:
        f = float(v)
    except (TypeError, ValueError):
        return 0.0
    if not math.isfinite(f):
        return 0.0
    if isinstance(v, int) and not isinstance(v, bool) and v > 1:
        f = f / 255.0
    return max(0.0, min(1.0, f))


def strip_param_prefix(addr: Any) -> str:
    """Normalise an OSC parameter address to the bare name used as a
    parameter_store key. Accepts full `/avatar/parameters/<x>` paths,
    bare names with a stray leading slash, or None.

    Stored form is always the bare name so the UI shows clean parameter
    names and the send path can re-add the prefix consistently.
    """
    s = str(addr or "").strip()
    if s.startswith("/avatar/parameters/"):
        s = s[len("/avatar/parameters/"):]
    return s.lstrip("/")


def _canon_zone_category(category: str):
    """Map an OGB/VFH category segment to the canonical zone type, or
    None when it isn't one. Long and short forms are both accepted
    (`Orifice`/`Orf`, `Penetrator`/`Pen`, `Touch`)."""
    if category in ("Orifice", "Orf"):
        return "Orf"
    if category in ("Penetrator", "Pen"):
        return "Pen"
    if category == "Touch":
        return "Touch"
    return None


def classify_ogb_zone(path: str):
    """Return `(zone_type, zone_name)` for an OGB-shaped path or None.
    Zone types are 'Orf' (orifice), 'Pen' (penetrator) or 'Touch'
    (VRCFury touch zone). Two wire forms are accepted, mirroring
    OscGoesBrrr's bridge parser:

      * ``OGB/<category>/<name>/<contact>`` — the standard form.
      * ``VFH/Zone/<category>/<name>/<contact>`` — the VRCFury Haptics
        zone form (touch zones ship this way on newer avatars).
    """
    parts = path.split("/", 4)
    if len(parts) >= 3 and parts[0] == "OGB":
        zone_type = _canon_zone_category(parts[1])
        if zone_type is not None and parts[2]:
            return (zone_type, parts[2])
    if len(parts) >= 4 and parts[0] == "VFH" and parts[1] == "Zone":
        zone_type = _canon_zone_category(parts[2])
        if zone_type is not None and parts[3]:
            return (zone_type, parts[3])
    return None

def _hex_rgb(hex_color: str):
    h = hex_color.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def value_to_hex_color(value: Any) -> str:
    """Convert a value to a hex color string for the OSC inspector.

    Numeric values interpolate across the active color profile's 2-stop
    value ramp (purple → hot pink on the default palette; gray → green
    on noir), matching the slider groove and intensity meters. Booleans
    map to the success accent (on) and the ramp's low end (off).
    """
    from constants import COLOR_SUCCESS, COLOR_VALUE_HI, COLOR_VALUE_LO
    if isinstance(value, bool):
        return COLOR_SUCCESS if value else COLOR_VALUE_LO
    if isinstance(value, (int, float)):
        f = max(0.0, min(1.0, float(value)))
        c0 = _hex_rgb(COLOR_VALUE_LO)
        c1 = _hex_rgb(COLOR_VALUE_HI)
        r = int(c0[0] + (c1[0] - c0[0]) * f)
        g = int(c0[1] + (c1[1] - c0[1]) * f)
        b = int(c0[2] + (c1[2] - c0[2]) * f)
        return f"#{r:02x}{g:02x}{b:02x}"
    return "#ffffff"


def running_appimage() -> Optional[str]:
    """Path of the AppImage this process was started from, or None.

    The Linux release is an AppImage: the runtime mounts it and runs the
    app from that mount, and names the file itself in $APPIMAGE. That
    file, not sys.executable, is what a restart starts and what an update
    replaces — the mount disappears the moment this process exits."""
    if sys.platform == "win32" or not getattr(sys, "frozen", False):
        return None
    path = os.environ.get("APPIMAGE", "")
    return path if path and os.path.isfile(path) else None


def relaunch_self() -> None:
    """Spawn a fresh copy of the running app — the AppImage or frozen exe
    when bundled, `python main.py` in dev — with the same arguments and
    working directory.

    Must be called only AFTER the Qt event loop has exited and the
    clean shutdown has run, so the new instance never races this one
    for the OSC/UDP ports or the mDNS advertisement. Best-effort: a
    failed spawn just leaves the app closed, exactly like a normal
    quit."""
    try:
        env = None
        appimage = running_appimage()
        if appimage:
            cmd = [appimage] + sys.argv[1:]
            env = fresh_instance_env()
        elif getattr(sys, "frozen", False):
            cmd = [sys.executable] + sys.argv[1:]
            env = fresh_instance_env()
        else:
            cmd = [sys.executable, os.path.abspath(sys.argv[0])] + sys.argv[1:]
        subprocess.Popen(cmd, cwd=os.getcwd(), close_fds=True, env=env)
    except Exception:
        pass


def fresh_instance_env() -> dict:
    """Environment for starting a NEW instance of this one-file exe.

    A child of a PyInstaller one-file app inherits its _PYI_* variables and
    reuses this process's unpacked _MEI folder — which is deleted as we
    exit, so the new instance dies on its first compiled import
    ("No module named 'pydantic_core._pydantic_core'"). This makes it
    unpack its own copy (PyInstaller >= 6.9)."""
    return dict(system_env(), PYINSTALLER_RESET_ENVIRONMENT="1")


def system_env() -> dict:
    """Environment for starting a program that is not part of this app —
    the file browser, a sound player, the Intiface engine.

    A frozen Linux build points LD_LIBRARY_PATH (and Qt's plugin path) at
    the libraries bundled inside it. A system program that inherits that
    loads our copies instead of its own: xdg-open opening Dolphin, itself a
    Qt app, can crash on our Qt plugins. PyInstaller keeps the original
    value as <NAME>_ORIG; put it back, and drop anything else that points
    into the bundle. Windows finds DLLs differently, so it gets the
    environment unchanged."""
    env = dict(os.environ)
    if sys.platform == "win32" or not getattr(sys, "frozen", False):
        return env
    bundle = getattr(sys, "_MEIPASS", "") or os.path.dirname(sys.executable)
    for key in [k for k in env if k.endswith("_ORIG")]:
        env[key[:-len("_ORIG")]] = env.pop(key)
    for key, value in list(env.items()):
        if key.startswith("_PYI") or (bundle and bundle in value):
            del env[key]
    return env


def open_folder(path: Union[str, Path]) -> None:
    """Show `path` in the system's file browser — Explorer, or whatever
    xdg-open picks on Linux. Raises on failure; the callers log it."""
    path = str(path)
    if sys.platform == "win32":
        os.startfile(path)  # type: ignore[attr-defined]
        return
    opener = "open" if sys.platform == "darwin" else "xdg-open"
    subprocess.Popen([opener, path], env=system_env(),
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                     stderr=subprocess.DEVNULL, start_new_session=True)


def process_alive(pid: int) -> bool:
    """True while a process with this id is running. Errs towards True when
    it can't tell, so a caller deciding whether a file is orphaned leaves it
    alone rather than taking over a running process's data."""
    try:
        pid = int(pid)
    except (TypeError, ValueError):
        return False
    if pid <= 0:
        return False
    if sys.platform == "win32":
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        STILL_ACTIVE = 259
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION,
                                      False, pid)
        if not handle:
            # 5 = access denied: it exists but belongs to someone else.
            return ctypes.GetLastError() == 5
        try:
            code = ctypes.c_ulong()
            if not kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
                return True
            return code.value == STILL_ACTIVE
        finally:
            kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except OSError:
        return True
    return True


def apply_window_frame_colors(hwnd: int,
                              border_hex: Any = None,
                              caption_hex: Any = None,
                              caption_text_hex: Any = None) -> None:
    """Tint the native window frame via Windows 11 DWM attributes.

    Any argument left None is not touched, so the purrple profile (all
    None) leaves the system frame exactly as it always was. Silently a
    no-op on Windows 10 and non-Windows — the attributes simply don't
    exist there and the call fails harmlessly.
    """
    if os.name != "nt" or not hwnd:
        return

    def _colorref(hex_color: str) -> int:
        r, g, b = _hex_rgb(hex_color)
        return (b << 16) | (g << 8) | r

    # DWMWA_BORDER_COLOR / DWMWA_CAPTION_COLOR / DWMWA_TEXT_COLOR
    for attr, hex_color in ((34, border_hex), (35, caption_hex),
                            (36, caption_text_hex)):
        if not hex_color:
            continue
        try:
            value = ctypes.c_int(_colorref(str(hex_color)))
            ctypes.windll.dwmapi.DwmSetWindowAttribute(
                ctypes.c_void_p(int(hwnd)), ctypes.c_uint(attr),
                ctypes.byref(value), ctypes.sizeof(value),
            )
        except Exception:
            return  # older Windows — leave the default frame

def toggle_windows_console(show: bool):
    """Hides or shows the Windows terminal console (Windows only)."""
    if os.name == 'nt':
        hwnd = ctypes.windll.kernel32.GetConsoleWindow()
        if hwnd:
            ctypes.windll.user32.ShowWindow(hwnd, 5 if show else 0)

def create_default_icon(tint: str = None):
    """Returns a 64x64 RGBA PIL Image for the system tray icon.

    Loads OGP_Icon.ico from the bundled resource path (works both during
    development and when frozen by PyInstaller), taking the .ico's own
    64 px drawing rather than shrinking the 256 one. Stays RGBA: the icon's
    corners around the eared frame are transparent, and flattening to RGB
    would paint them solid black in the tray. Falls back to a programmatic
    placeholder if the file cannot be read.

    `tint` (optional "#RRGGBB" hex) overlays a small filled activity dot
    in the empty gap between the ears, with a slightly darker outline — the
    controller's tray-glow heartbeat uses it to show live output
    intensity while minimized. Pure PIL; a bad tint value just skips
    the overlay.
    """
    image = None
    try:
        import sys
        from PIL import Image

        if getattr(sys, "frozen", False):
            icon_path = os.path.join(sys._MEIPASS, "Images", "OGP_Icon.ico")
        else:
            icon_path = os.path.join(os.path.dirname(__file__), "Images", "OGP_Icon.ico")

        if os.path.exists(icon_path):
            # Context manager: PIL keeps the file handle open lazily and
            # a GC'd unclosed FileIO raises a ResourceWarning.
            with Image.open(icon_path) as src:
                if (64, 64) in (src.info.get("sizes") or ()):
                    src.size = (64, 64)       # pick the .ico's 64 px frame
                image = src.convert("RGBA")
                if image.size != (64, 64):
                    image = image.resize((64, 64), Image.LANCZOS)
    except Exception:
        image = None

    if image is None:
        from PIL import Image, ImageDraw
        image = Image.new("RGBA", (64, 64), color=(30, 30, 30, 255))
        dc = ImageDraw.Draw(image)
        dc.ellipse((16, 16, 48, 48), fill=(147, 112, 219))

    if tint:
        try:
            from PIL import ImageDraw
            r, g, b = _hex_rgb(str(tint))
            outline = (int(r * 0.6), int(g * 0.6), int(b * 0.6))
            dc = ImageDraw.Draw(image)
            # 16 px dot in the empty gap between the ears -- clear of the
            # frame and the OGP letters, so it never hides either.
            dc.ellipse((24, 4, 40, 20), fill=(r, g, b, 255),
                       outline=outline + (255,), width=1)
        except Exception:
            pass
    return image


def png_bytes(image) -> bytes:
    """A PIL image as PNG file bytes — how the controller hands the tray
    icon to the UI without touching Qt itself."""
    import io
    buf = io.BytesIO()
    image.save(buf, "PNG")
    return buf.getvalue()