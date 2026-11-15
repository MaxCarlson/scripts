"""Console entrypoint target for `proc-stats`."""

from __future__ import annotations

import sys
from typing import Optional, Sequence

from .process_watch.cli import main as _main


def main(argv: Optional[Sequence[str]] = None) -> int:
    return _main(argv)


if __name__ == "__main__":
    sys.exit(main())
