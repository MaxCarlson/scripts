#!/usr/bin/env python3
"""Bootstrap development-ledger instructions and docs in another repository."""

from __future__ import annotations

import sys

from development_ledger.cli import main


if __name__ == "__main__":
    raise SystemExit(main(["setup", *sys.argv[1:]]))
