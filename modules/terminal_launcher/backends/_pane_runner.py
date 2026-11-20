"""Shell-free relay used to preserve child argv across WT's command grammar."""

from __future__ import annotations

import base64
import json
import subprocess
import sys
from collections.abc import Callable, Sequence


def run_payload(encoded: str, runner: Callable[..., subprocess.CompletedProcess] = subprocess.run) -> int:
    """Decode a launch payload and run its argv without shell interpretation."""
    padding = "=" * (-len(encoded) % 4)
    argv, cwd = json.loads(base64.urlsafe_b64decode(encoded + padding))
    if not isinstance(argv, list) or not argv or not all(isinstance(arg, str) for arg in argv):
        raise ValueError("payload must contain a non-empty string argument vector")
    if cwd is not None and not isinstance(cwd, str):
        raise ValueError("payload cwd must be a string or null")
    return runner(argv, cwd=cwd, shell=False, check=False).returncode


def main(args: Sequence[str] | None = None) -> int:
    values = list(sys.argv[1:] if args is None else args)
    if len(values) != 1:
        return 2
    try:
        return run_payload(values[0])
    except (ValueError, TypeError, json.JSONDecodeError):
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
