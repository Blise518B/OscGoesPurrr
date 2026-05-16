import os
import ctypes
from typing import Any


def normalize_osc_value(v: float) -> float:
    """Normalizes an incoming OSC float (0.0 to 1.0) or int (0 to 255) to a safe 0.0-1.0 range."""
    return max(0.0, min(1.0, v if v <= 1.0 else v / 255.0))

def value_to_hex_color(value: Any) -> str:
    """Convert a value to a hex color string for the debugger UI."""
    if isinstance(value, bool):
        return "#00ff00" if value else "#ff0000"
    if isinstance(value, (int, float)):
        f = max(0.0, min(1.0, float(value)))
        if f <= 0.5:
            t = f / 0.5
            r = 255
            g = int(t * 255)
        else:
            t = (f - 0.5) / 0.5
            r = int(255 * (1 - t))
            g = 255
        return f"#{r:02x}{g:02x}00"
    return "#ffffff"

def toggle_windows_console(show: bool):
    """Hides or shows the Windows terminal console (Windows only)."""
    if os.name == 'nt':
        hwnd = ctypes.windll.kernel32.GetConsoleWindow()
        if hwnd:
            ctypes.windll.user32.ShowWindow(hwnd, 5 if show else 0)

def create_default_icon():
    """Returns a 64x64 PIL Image for the system tray icon.

    Loads OGP_Icon.ico from the bundled resource path (works both during
    development and when frozen by PyInstaller). Falls back to a
    programmatic placeholder if the file cannot be read.
    """
    try:
        import sys
        from PIL import Image

        if getattr(sys, "frozen", False):
            icon_path = os.path.join(sys._MEIPASS, "Images", "OGP_Icon.ico")
        else:
            icon_path = os.path.join(os.path.dirname(__file__), "Images", "OGP_Icon.ico")

        if os.path.exists(icon_path):
            return Image.open(icon_path).resize((64, 64)).convert("RGB")
    except Exception:
        pass

    from PIL import Image, ImageDraw
    image = Image.new("RGB", (64, 64), color=(30, 30, 30))
    dc = ImageDraw.Draw(image)
    dc.ellipse((16, 16, 48, 48), fill=(147, 112, 219))
    return image