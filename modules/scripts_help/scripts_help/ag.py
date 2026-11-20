"""Python-first `ag` command discovery across registered commands, live shell inventories, and PATH."""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
from pathlib import Path
from typing import Any, Sequence

from scripts_help._repo_root import find_repo_root
from scripts_help.command_registry import (
    SCHEMA_VERSION,
    CommandEntry,
    detect_collisions,
    load_command_registry,
)


def _load_shell_inventory(path: Path | None) -> list[CommandEntry]:
    """Load live shell aliases/functions exported by a thin shell adapter."""
    if path is None or not path.is_file():
        return []
    try:
        raw = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return []

    if isinstance(raw, dict):
        items = raw.get("items", [])
        default_source = str(raw.get("shell", "shell"))
    elif isinstance(raw, list):
        items = raw
        default_source = "shell"
    else:
        return []

    entries: list[CommandEntry] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name", "")).strip()
        if not name:
            continue
        kind = str(item.get("kind", "shell_alias")).strip()
        source = str(item.get("source", default_source)).strip()
        definition = str(item.get("definition", "")).strip()
        entries.append(
            CommandEntry(
                name=name,
                program_id=f"shell:{source}:{name}",
                invoked_name=name,
                kind=kind,
                source=source,
                target=definition,
                description=definition,
                shell_adapter_required=True,
            )
        )
    return entries


def _discover_path_executables(path_env: str | None = None) -> list[CommandEntry]:
    """Discover executable files on PATH (optional)."""
    env_path = path_env if path_env is not None else os.environ.get("PATH", "")
    seen: set[str] = set()
    entries: list[CommandEntry] = []
    pathext = (
        tuple(ext.lower() for ext in os.environ.get("PATHEXT", ".EXE;.CMD;.BAT;.PS1").split(";") if ext)
        if os.name == "nt"
        else ()
    )

    for dir_str in env_path.split(os.pathsep):
        if not dir_str:
            continue
        d = Path(dir_str)
        if not d.is_dir():
            continue
        try:
            children = sorted(d.iterdir(), key=lambda p: p.name.lower())
        except OSError:
            continue
        for child in children:
            if not child.is_file():
                continue
            if os.name == "nt":
                if child.suffix.lower() not in pathext:
                    continue
                name = child.stem
            else:
                if not os.access(child, os.X_OK):
                    continue
                name = child.name
            key = name.lower() if os.name == "nt" else name
            if key in seen:
                continue
            seen.add(key)
            entries.append(
                CommandEntry(
                    name=name,
                    program_id=f"command:{name}",
                    invoked_name=name,
                    kind="executable",
                    source="path",
                    target=str(child),
                    description=f"PATH executable: {child}",
                )
            )
    return entries


def detect_silver_searcher_collision(
    repo_root: Path | None = None,
    path_env: str | None = None,
) -> str | None:
    """Return path to an external `ag` binary on PATH if it collides with our `ag`."""
    env_path = path_env if path_env is not None else os.environ.get("PATH", "")
    for dir_str in env_path.split(os.pathsep):
        if not dir_str:
            continue
        found = shutil.which("ag", path=dir_str)
        if not found:
            continue
        found_path = Path(found)
        if repo_root is not None:
            try:
                resolved = found_path.resolve()
                for toolkit_dir in (repo_root / ".venv", repo_root / "bin"):
                    if str(resolved).lower().startswith(str(toolkit_dir.resolve()).lower()):
                        found = None
                        break
            except OSError:
                pass
        if found is None:
            continue
        return str(found_path)
    return None


def _kind_matches(entry_kind: str, requested_type: str | None) -> bool:
    if not requested_type or requested_type == "all":
        return True
    req = requested_type.lower()
    ek = entry_kind.lower()
    if req == "alias":
        return ek in ("alias", "shell_alias")
    if req == "function":
        return ek in ("function", "shell_function")
    return ek == req


def search_ag(
    pattern: str,
    *,
    entries: Sequence[CommandEntry],
    case_sensitive: bool = False,
    command_type: str | None = None,
    source: str | None = None,
) -> list[CommandEntry]:
    """Match pattern against command name and target definition (case-insensitive regex by default)."""
    flags = 0 if case_sensitive else re.IGNORECASE
    try:
        rx = re.compile(pattern, flags)
    except re.error:
        rx = re.compile(re.escape(pattern), flags)

    matches: list[CommandEntry] = []
    for entry in entries:
        if not _kind_matches(entry.kind, command_type):
            continue
        if source and source != "all" and entry.source.lower() != source.lower():
            continue
        if rx.search(entry.name) or rx.search(entry.target):
            matches.append(entry)
    return sorted(matches, key=lambda e: (e.name.lower(), e.source, e.kind))


def _format_table(matches: Sequence[CommandEntry], *, verbose: bool = False) -> str:
    if not matches:
        return ""
    if verbose:
        headers = ("Name", "Kind", "Source", "Definition", "ProgramId")
        rows = [(m.name, m.kind, m.source, m.target, m.program_id) for m in matches]
    else:
        headers = ("Name", "Definition")
        rows = [(m.name, m.target) for m in matches]

    widths = [len(h) for h in headers]
    for row in rows:
        for idx, val in enumerate(row):
            widths[idx] = max(widths[idx], min(len(val), 80))

    def _fmt_row(vals: tuple[str, ...]) -> str:
        parts = []
        for idx, val in enumerate(vals):
            if idx == len(vals) - 1:
                parts.append(val)
            else:
                parts.append(val.ljust(widths[idx]))
        return "  ".join(parts)

    lines = [
        _fmt_row(headers),
        "  ".join("-" * w for w in widths),
    ]
    for row in rows:
        lines.append(_fmt_row(row))
    return "\n".join(lines)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ag",
        description="Search registered Python commands, live shell aliases/functions, and optional PATH executables.",
    )
    parser.add_argument(
        "pattern",
        nargs="?",
        default="",
        help="Regex pattern to match against command name or definition (default: match all).",
    )
    parser.add_argument(
        "-s", "--case-sensitive",
        action="store_true",
        help="Use case-sensitive regex matching (default: case-insensitive).",
    )
    parser.add_argument(
        "-t", "--type",
        dest="command_type",
        default="all",
        choices=("all", "alias", "function", "console_script", "python_file", "shell_script", "executable"),
        help="Filter by command type/kind (default: all).",
    )
    parser.add_argument(
        "-S", "--source",
        default="all",
        help="Filter by source (e.g. pwsh, bash, zsh, scripts_manifest, pyproject, path).",
    )
    parser.add_argument(
        "-x", "--executables",
        action="store_true",
        help="Include executables discovered on PATH.",
    )
    parser.add_argument(
        "-i", "--shell-inventory",
        default=None,
        help="Path to JSON file containing live shell aliases/functions (or set AG_SHELL_INVENTORY_FILE).",
    )
    parser.add_argument(
        "-j", "--json",
        action="store_true",
        help="Emit structured JSON output.",
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Show Kind, Source, and ProgramId columns in table output.",
    )
    parser.add_argument(
        "-c", "--check-collisions",
        action="store_true",
        help="Include registry/PATH collision report.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    try:
        repo_root = find_repo_root()
    except RuntimeError:
        repo_root = None

    entries: list[CommandEntry] = []
    if repo_root is not None:
        entries.extend(load_command_registry(repo_root))

    inv_path_str = args.shell_inventory or os.environ.get("AG_SHELL_INVENTORY_FILE")
    if inv_path_str:
        entries.extend(_load_shell_inventory(Path(inv_path_str)))

    if args.executables:
        entries.extend(_discover_path_executables())

    matches = search_ag(
        args.pattern,
        entries=entries,
        case_sensitive=args.case_sensitive,
        command_type=args.command_type,
        source=args.source,
    )

    silver_searcher = detect_silver_searcher_collision(repo_root=repo_root)
    collisions = (
        detect_collisions(entries, repo_root=repo_root, check_path=True)
        if args.check_collisions
        else []
    )

    if args.json:
        payload: dict[str, Any] = {
            "schema_version": SCHEMA_VERSION,
            "pattern": args.pattern,
            "count": len(matches),
            "matches": [m.to_dict() for m in matches],
            "silver_searcher_collision": silver_searcher,
        }
        if args.check_collisions:
            payload["collisions"] = [c.to_dict() for c in collisions]
        print(json.dumps(payload, indent=2))
        return 0

    if silver_searcher:
        print(
            f"[WARNING] External `ag` (Silver Searcher or similar) detected on PATH at: {silver_searcher}",
            file=sys.stderr,
        )

    table = _format_table(matches, verbose=args.verbose)
    if table:
        print(table)
    else:
        print(f"No commands matched pattern: {args.pattern!r}")

    if args.check_collisions and collisions:
        print("\nCollisions detected:", file=sys.stderr)
        for c in collisions:
            print(f"  - [{c.collision_type}] {c.name}: {c.details}", file=sys.stderr)

    return 0


if __name__ == "__main__":
    sys.exit(main())
