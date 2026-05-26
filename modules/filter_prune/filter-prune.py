#!/usr/bin/env python3
"""Compatibility wrapper for running the package CLI as a script."""

from __future__ import annotations

from filter_prune.cli import main


if __name__ == "__main__":
    raise SystemExit(main())
