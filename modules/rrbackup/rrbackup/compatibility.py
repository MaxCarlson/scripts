"""Compatibility dispatcher for historical ``rrb`` and ``rrbackup`` commands."""

from __future__ import annotations

import sys
from typing import List, Optional, Sequence, Tuple

from . import application

_GLOBAL_VALUE_OPTIONS = {
    "-c",
    "--config",
    "--config-path",
    "--config_path",
    "-R",
    "--repository",
    "--repository-path",
    "-p",
    "--password-file",
    "--password_file",
    "-x",
    "--restic-executable",
    "--restic_executable",
}

_LEGACY_DIRECT_COMMANDS = {
    "setup",
    "list",
    "ls",
    "snapshots",
    "backup",
    "stats",
    "check",
    "prune",
    "progress",
}

_LEGACY_CONFIG_COMMANDS = {
    "init",
    "wizard",
    "show",
    "list-sets",
    "add-set",
    "remove-set",
    "set",
    "retention",
}


def _split_global_prefix(argv: Sequence[str]) -> Tuple[List[str], List[str]]:
    prefix: List[str] = []
    values = list(argv)
    index = 0
    while index < len(values) and values[index].startswith("-"):
        option = values[index]
        prefix.append(option)
        index += 1
        if option in _GLOBAL_VALUE_OPTIONS and index < len(values):
            prefix.append(values[index])
            index += 1
    return prefix, values[index:]


def should_use_legacy(argv: Sequence[str]) -> bool:
    """Return whether the historical parser must preserve command semantics."""

    _, remainder = _split_global_prefix(argv)
    if not remainder:
        return False
    command = remainder[0]
    if command in _LEGACY_DIRECT_COMMANDS:
        return True
    return (
        command == "config"
        and len(remainder) > 1
        and remainder[1] in _LEGACY_CONFIG_COMMANDS
    )


def main(argv: Optional[Sequence[str]] = None) -> int:
    """Dispatch old commands safely while exposing the canonical hierarchy."""

    values = list(sys.argv[1:] if argv is None else argv)
    if should_use_legacy(values):
        from .cli import main as legacy_main

        return int(legacy_main(values))
    return int(application.main(values))


if __name__ == "__main__":
    raise SystemExit(main())
