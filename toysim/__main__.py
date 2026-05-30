"""Entry point: `python -m toysim` launches the toy-simulator window.

The import is absolute (`toysim.toysim_ui`) rather than relative so this same
file also works as the PyInstaller entry script — see toysim/build.bat, which
freezes this module with the repo root on the search path.
"""

import sys

from toysim.toysim_ui import run


if __name__ == "__main__":
    sys.exit(run())
