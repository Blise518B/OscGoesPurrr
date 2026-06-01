"""Entry point: ``python -m testbench`` launches the unified test bench.

The import is absolute (``testbench.app``) rather than relative so this same
file also works as the PyInstaller entry script — see build_testbench.bat,
which freezes this module with the repo root on the search path.
"""

import sys

from testbench.app import run


if __name__ == "__main__":
    sys.exit(run())
