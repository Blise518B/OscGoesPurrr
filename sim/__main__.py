"""Entry point: `python -m sim` launches the VRChat simulator window."""

import sys

from .sim_ui import run


if __name__ == "__main__":
    sys.exit(run())
