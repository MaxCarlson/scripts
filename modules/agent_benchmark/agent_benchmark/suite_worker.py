"""Detached worker for an already-authorized suite run."""

from __future__ import annotations

import argparse
from pathlib import Path

from .suite import execute_pending


def main() -> int:
    parser = argparse.ArgumentParser(prog="agent-bench-suite-worker")
    parser.add_argument("run_dir", type=Path)
    parser.add_argument("-x", "--execute", action="store_true", required=True,
                        help="Carry the parent CLI's explicit execution authorization")
    parser.add_argument("--retry-invalid", action="store_true")
    args = parser.parse_args()
    try:
        execute_pending(args.run_dir, execute=args.execute, retry_invalid=args.retry_invalid)
    finally:
        (args.run_dir / "launcher.lock").unlink(missing_ok=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
