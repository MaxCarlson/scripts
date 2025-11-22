#!/usr/bin/env python3
"""
autocorrect_manager.py

Generic ignore-list manager for shell autocorrect systems.

Currently used for:
- Zsh: manages patterns in an ignore file loaded into CORRECT_IGNORE.

Designed so other shells (e.g., PowerShell) can reuse it later by pointing
to a different ignore file and shell_type.
"""

import argparse
import fnmatch
import os
import sys
from typing import List, Tuple


def expand_default_file(shell_type: str) -> str:
    """
    Compute a default ignore file path based on the shell type.

    For now:
    - zsh  -> ~/zsh_autocorrect_ignore
    - pwsh -> ~/pwsh_autocorrect_ignore
    - other -> ~/autocorrect_ignore_<shell_type>
    """
    home = os.path.expanduser("~")
    if shell_type == "zsh":
        return os.path.join(home, "zsh_autocorrect_ignore")
    if shell_type in ("pwsh", "powershell"):
        return os.path.join(home, "pwsh_autocorrect_ignore")
    return os.path.join(home, f"autocorrect_ignore_{shell_type}")


def load_patterns(path: str) -> List[str]:
    """
    Load ignore patterns from file.

    - Ignores blank lines and lines starting with '#'.
    - Returns patterns in file order.
    """
    if not os.path.exists(path):
        return []

    patterns: List[str] = []
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                stripped = line.strip()
                if not stripped or stripped.startswith("#"):
                    continue
                patterns.append(stripped)
    except OSError as exc:
        print(f"Error: failed to read ignore file '{path}': {exc}", file=sys.stderr)
        sys.exit(1)

    return patterns


def save_patterns(path: str, patterns: List[str]) -> None:
    """
    Save patterns to file, one per line.

    Creates parent directories if necessary.
    """
    directory = os.path.dirname(path)
    if directory and not os.path.exists(directory):
        try:
            os.makedirs(directory, exist_ok=True)
        except OSError as exc:
            print(f"Error: failed to create directory '{directory}': {exc}", file=sys.stderr)
            sys.exit(1)

    try:
        with open(path, "w", encoding="utf-8") as f:
            for pattern in patterns:
                f.write(pattern + "\n")
    except OSError as exc:
        print(f"Error: failed to write ignore file '{path}': {exc}", file=sys.stderr)
        sys.exit(1)


def uniq_preserve_order(items: List[str]) -> List[str]:
    seen = set()
    result: List[str] = []
    for item in items:
        if item not in seen:
            seen.add(item)
            result.append(item)
    return result


def cmd_list(path: str, patterns: List[str]) -> int:
    """
    List patterns to stdout.
    """
    print(f"# Ignore file: {path}")
    if not patterns:
        print("# (no patterns)")
        return 0

    for pat in patterns:
        print(pat)
    return 0


def cmd_add(
    path: str,
    patterns: List[str],
    to_add: List[str],
    dry_run: bool,
) -> int:
    """
    Add one or more patterns to the ignore list.
    Patterns are taken literally (they may themselves contain globs).
    """
    if not to_add:
        print("Error: 'add' requires at least one PATTERN.", file=sys.stderr)
        return 2

    current = patterns[:]
    initial_set = set(current)
    new_items: List[str] = []

    for pattern in to_add:
        if pattern in initial_set:
            continue
        current.append(pattern)
        new_items.append(pattern)

    current = uniq_preserve_order(current)

    if dry_run:
        print(f"[DRY-RUN] Would add {len(new_items)} pattern(s) to '{path}':")
        for pat in new_items:
            print(f"  + {pat}")
        return 0

    if new_items:
        save_patterns(path, current)
        print(f"Added {len(new_items)} pattern(s) to '{path}':")
        for pat in new_items:
            print(f"  + {pat}")
    else:
        print("No new patterns added (all already present).")

    return 0


def compute_removals(
    current: List[str],
    to_remove: List[str],
    use_glob: bool,
) -> Tuple[List[str], List[str]]:
    """
    Compute which patterns will be removed and the new pattern list.

    Returns (new_patterns, removed_patterns).
    """
    if not to_remove:
        return current[:], []

    if not use_glob:
        remove_set = set(to_remove)

        new_patterns = [p for p in current if p not in remove_set]
        removed = [p for p in current if p in remove_set]
        return new_patterns, removed

    # glob mode: treat to_remove as fnmatch patterns that match existing entries
    removed_flags = [False] * len(current)

    for idx, value in enumerate(current):
        for pattern in to_remove:
            if fnmatch.fnmatch(value, pattern):
                removed_flags[idx] = True
                break

    new_patterns: List[str] = []
    removed: List[str] = []

    for idx, value in enumerate(current):
        if removed_flags[idx]:
            removed.append(value)
        else:
            new_patterns.append(value)

    return new_patterns, removed


def cmd_remove(
    path: str,
    patterns: List[str],
    to_remove: List[str],
    use_glob: bool,
    dry_run: bool,
) -> int:
    """
    Remove one or more patterns from the ignore list.

    - By default, removes exact matches.
    - With --use_glob/-g, uses fnmatch-style globbing against existing entries.
    """
    if not to_remove:
        print("Error: 'remove' requires at least one PATTERN.", file=sys.stderr)
        return 2

    new_patterns, removed = compute_removals(patterns, to_remove, use_glob)

    if dry_run:
        print(f"[DRY-RUN] Would remove {len(removed)} pattern(s) from '{path}':")
        for pat in removed:
            print(f"  - {pat}")
        if not removed:
            print("[DRY-RUN] No patterns would be removed (no matches).")
        return 0

    if not removed:
        print("No patterns removed (no matches).")
        return 0

    save_patterns(path, new_patterns)
    print(f"Removed {len(removed)} pattern(s) from '{path}':")
    for pat in removed:
        print(f"  - {pat}")

    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Manage shell autocorrect ignore lists (e.g. Zsh CORRECT_IGNORE) "
            "via a plain text file."
        )
    )

    parser.add_argument(
        "-s",
        "--shell_type",
        default="zsh",
        help=(
            "Shell type for which this ignore list is used "
            "(default: zsh). Used only to compute a default file path."
        ),
    )
    parser.add_argument(
        "-f",
        "--file_path",
        help=(
            "Path to the ignore file. If omitted, a default path is derived "
            "from --shell_type (e.g. ~/zsh_autocorrect_ignore)."
        ),
    )
    parser.add_argument(
        "-n",
        "--dry_run",
        action="store_true",
        help="Dry run: show what would change but do not modify the file.",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    # list
    list_parser = subparsers.add_parser(
        "list",
        help="List all patterns in the ignore file.",
    )
    list_parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Verbose listing (currently same as normal; reserved for future use).",
    )

    # add
    add_parser = subparsers.add_parser(
        "add",
        help="Add one or more patterns (commands) to the ignore file.",
    )
    add_parser.add_argument(
        "-a",
        "--add_patterns",
        nargs="+",
        metavar="PATTERN",
        help="Pattern(s) to add. May include globs (stored literally).",
    )

    # remove
    remove_parser = subparsers.add_parser(
        "remove",
        help="Remove pattern(s) from the ignore file (exact or glob-based).",
    )
    remove_parser.add_argument(
        "-r",
        "--remove_patterns",
        nargs="+",
        metavar="PATTERN",
        help="Pattern(s) to remove.",
    )
    remove_parser.add_argument(
        "-g",
        "--use_glob",
        action="store_true",
        help=(
            "Treat PATTERN as glob(s) and remove any existing entries that match. "
            "Without this, PATTERN must match entries exactly."
        ),
    )

    return parser


def main(argv: List[str]) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    shell_type: str = args.shell_type
    file_path: str

    if args.file_path:
        file_path = os.path.expanduser(args.file_path)
    else:
        file_path = expand_default_file(shell_type)

    patterns = load_patterns(file_path)

    if args.command == "list":
        return cmd_list(file_path, patterns)

    if args.command == "add":
        to_add = args.add_patterns or []
        return cmd_add(file_path, patterns, to_add, args.dry_run)

    if args.command == "remove":
        to_remove = args.remove_patterns or []
        use_glob = bool(getattr(args, "use_glob", False))
        return cmd_remove(file_path, patterns, to_remove, use_glob, args.dry_run)

    parser.error(f"Unknown command: {args.command}")
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

