"""Module entry point for `python -m vm_lab`."""

from __future__ import annotations

import sys

from vm_lab.cli import main

if __name__ == "__main__":
    sys.exit(main())
