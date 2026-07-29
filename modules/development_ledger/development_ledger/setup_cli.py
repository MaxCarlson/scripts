"""Dedicated console entry point for repository setup."""

from __future__ import annotations

import sys
from collections.abc import Sequence

from development_ledger.cli import main as ledger_main


def main(argv: Sequence[str] | None = None) -> int:
    """Run the main CLI with the ``setup`` subcommand selected."""

    arguments = list(sys.argv[1:] if argv is None else argv)
    return ledger_main(["setup", *arguments])
