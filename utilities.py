import ctypes
import json
import math
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Union


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


def relaunch_self() -> None:
    """Spawn a fresh copy of the running app — the frozen exe when
    bundled, `python main.py` in dev — with the same arguments and
    working directory.

    Must be called only AFTER the Qt event loop has exited and the
    clean shutdown has run, so the new instance never races this one
    for the OSC/UDP ports or the mDNS advertisement. Best-effort: a
    failed spawn just leaves the app closed, exactly like a normal
    quit."""
    try:
        if getattr(sys, "frozen", False):
            cmd = [sys.executable] + sys.argv[1:]
        else:
            cmd = [sys.executable, os.path.abspath(sys.argv[0])] + sys.argv[1:]
        subprocess.Popen(cmd, cwd=os.getcwd(), close_fds=True)
    except Exception:
        pass


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
    """Returns a 64x64 PIL Image for the system tray icon.

    Loads OGP_Icon.ico from the bundled resource path (works both during
    development and when frozen by PyInstaller). Falls back to a
    programmatic placeholder if the file cannot be read.

    `tint` (optional "#RRGGBB" hex) overlays a small filled activity dot
    in the bottom-right quadrant with a slightly darker outline — the
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
                image = src.resize((64, 64)).convert("RGB")
    except Exception:
        image = None

    if image is None:
        from PIL import Image, ImageDraw
        image = Image.new("RGB", (64, 64), color=(30, 30, 30))
        dc = ImageDraw.Draw(image)
        dc.ellipse((16, 16, 48, 48), fill=(147, 112, 219))

    if tint:
        try:
            from PIL import ImageDraw
            r, g, b = _hex_rgb(str(tint))
            outline = (int(r * 0.6), int(g * 0.6), int(b * 0.6))
            dc = ImageDraw.Draw(image)
            # ~22 px dot in the bottom-right quadrant of the 64px canvas.
            dc.ellipse((40, 40, 62, 62), fill=(r, g, b),
                       outline=outline, width=1)
        except Exception:
            pass
    return image