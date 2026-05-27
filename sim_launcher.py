"""PyInstaller entry point for the VRChat simulator.

`sim/__main__.py` uses a relative import (`from .sim_ui import run`), which
fails when PyInstaller targets a script directly because there is no parent
package context. This launcher imports the module under its absolute name so
the same code path works under `python -m sim` (via __main__.py) and inside
the frozen --onefile exe (via this file).

The file lives at the project root so PyInstaller's bundled-resource path
(sys._MEIPASS) lines up with the source-tree layout for `Images/` lookups.
"""

import sys

from sim.sim_ui import run


if __name__ == "__main__":
    sys.exit(run())
