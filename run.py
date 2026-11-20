"""Isolated launcher entrypoint for hermes-icon."""

import sys
from pathlib import Path

SRC_DIR = str(Path(__file__).resolve().parent / "src")
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

from hermes_icon.cli import main

if __name__ == "__main__":
    sys.exit(main())
