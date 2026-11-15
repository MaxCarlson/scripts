"""Module entrypoint for `python -m procwatch`."""

from __future__ import annotations

import sys

from procwatch.cli import main

if __name__ == "__main__":
    sys.exit(main())
