from __future__ import annotations

import argparse
import sys

try:
    # Optional: use argparse_enforcer if available
    from argparse_enforcer.enforcer import EnforcedArgumentParser as Parser
except Exception:
    Parser = argparse.ArgumentParser  # type: ignore

from .bootstrap import bootstrap, best_practices_text


def main(argv: list[str] | None = None) -> int:
    p = Parser(description="Bootstrap a best-practices Python environment (uv, pipx, micromamba)")
    p.add_argument("-v", "--verbose", action="store_true", help="Verbose output")
    p.add_argument("-p", "--print-best-practices", action="store_true", help="Show recommended workflows and usage")
    args = p.parse_args(argv)

    if args.print_best_practices:
        print(best_practices_text())
        return 0

    bootstrap(verbose=args.verbose)
    return 0


if __name__ == "__main__":
    sys.exit(main())
