"""Dispatcher-safe wrapper for the development-ledger record command."""

from __future__ import annotations

import sys
from collections.abc import Sequence

from development_ledger.cli import main as ledger_main


def main(argv: Sequence[str] | None = None) -> int:
    """Record validation evidence without masking the dispatcher's prior failures.

    The existing ``record`` command returns 1 after successfully writing evidence
    when normalized tests contain failures or errors. A repository dispatcher has
    already preserved those failures, so this adapter maps only that successful
    record result to zero. Plan, parse, Git, duplicate-event, and write failures
    continue to return their original nonzero result.
    """

    arguments = list(sys.argv[1:] if argv is None else argv)
    result = ledger_main(["record", *arguments])
    return 0 if result == 1 else result


if __name__ == "__main__":
    raise SystemExit(main())
