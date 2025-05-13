#!/usr/bin/env python3
"""
Compare scripts and pytest-style tests, summarize coverage, and suggest fixes for mismatches.

New options:
  -d, --depth    Max folder depth to scan (0 = root only; 1 = one level deep; -1 = infinite [default])
  -x, --exclude  Space-separated list of files or folders (relative to script- or test-dir) to skip
"""

import sys
import re
import argparse
import difflib
from pathlib import Path

from rich.console import Console
from rich.table import Table
from rich.text import Text

console = Console()

TEST_AFFIXES = ("_test", "_tests")
TEST_PREFIX = "test_"


def strip_test_affixes(name: str) -> str:
    """Remove leading 'test_' or trailing '_test(s)' from a basename."""
    base = name
    if base.startswith(TEST_PREFIX):
        base = base[len(TEST_PREFIX):]
    for suffix in TEST_AFFIXES:
        if base.endswith(suffix):
            base = base[:-len(suffix)]
            break
    return base


def collect_py_files(root: Path, max_depth: int, exclude_abs: set[Path]) -> list[Path]:
    """
    Recursively collect .py files under `root`, skipping __pycache__,
    files under any path in exclude_abs, and obeying max_depth.
    """
    out = []
    root = root.resolve()

    for p in root.rglob("*.py"):
        # ignore __init__ and __pycache__
        if p.name == "__init__.py" or "__pycache__" in p.parts:
            continue

        rel = p.relative_to(root)
        depth = len(rel.parts) - 1
        if max_depth >= 0 and depth > max_depth:
            continue

        if any((ex in p.parents) or p == ex for ex in exclude_abs):
            continue

        out.append(p)
    return out


def main():
    parser = argparse.ArgumentParser(
        description="Match your .py scripts against pytest-style tests and suggest fixes."
    )
    parser.add_argument(
        "-s",
        "--script-dir",
        type=Path,
        default=Path.cwd(),
        help="Directory holding your scripts (default: cwd)",
    )
    parser.add_argument(
        "-t",
        "--test-dir",
        type=Path,
        help="Directory holding your tests (default: first of ./tests or ./test)",
    )
    parser.add_argument(
        "-d",
        "--depth",
        type=int,
        default=-1,
        help="Max depth (0=root only, 1=one subfolder, -1=infinite)",
    )
    parser.add_argument(
        "-x",
        "--exclude",
        nargs="+",
        default=[],
        help="List of files/folders to exclude (relative to script- or test-dir)",
    )
    args = parser.parse_args()

    script_dir = args.script_dir.resolve()
    if args.test_dir:
        test_dir = (script_dir / args.test_dir).resolve()
    else:
        for name in ("tests", "test"):
            candidate = script_dir / name
            if candidate.is_dir():
                test_dir = candidate.resolve()
                break
        else:
            console.print(f"[red]Error:[/] no ./tests or ./test in {script_dir}, and --test-dir not given")
            sys.exit(1)

    # build absolute exclude set
    exclude_abs: set[Path] = set()
    for ex in args.exclude:
        p = Path(ex)
        if p.is_absolute() and p.exists():
            exclude_abs.add(p.resolve())
        else:
            sp = (script_dir / ex).resolve()
            tp = (test_dir / ex).resolve()
            if sp.exists():
                exclude_abs.add(sp)
            if tp.exists():
                exclude_abs.add(tp)

    scripts = collect_py_files(script_dir, args.depth, exclude_abs)
    tests = collect_py_files(test_dir, args.depth, exclude_abs)

    # map basenames to paths
    script_map: dict[str, list[Path]] = {}
    for path in scripts:
        bn = path.stem
        script_map.setdefault(bn, []).append(path.relative_to(script_dir))

    test_map: dict[str, list[Path]] = {}
    for path in tests:
        bn = path.stem
        test_map.setdefault(bn, []).append(path.relative_to(script_dir))

    # summary table
    table = Table(title="Scripts vs. Tests", show_edge=False, box=None)
    table.add_column("Script", style="bold")
    table.add_column("Status", justify="center")
    table.add_column("Test Count", justify="right")
    table.add_column("Tests", overflow="fold")

    for script_bn, paths in script_map.items():
        patterns = {f"{TEST_PREFIX}{script_bn}"}
        patterns.update(f"{script_bn}{suffix}" for suffix in TEST_AFFIXES)

        matched = []
        for test_bn, tpaths in test_map.items():
            if test_bn in patterns:
                matched.extend(tpaths)

        status = "[green]✅[/]" if matched else "[red]❌[/]"
        table.add_row(
            ", ".join(str(p) for p in paths),
            status,
            str(len(matched)),
            ", ".join(str(p) for p in matched) or "-",
        )

    console.print(table)

    # find orphan tests
    orphan_bns = []
    for test_bn in test_map:
        if any(
            test_bn in {f"{TEST_PREFIX}{sb}", f"{sb}{suffix}"}
            for sb in script_map
            for suffix in TEST_AFFIXES
        ):
            continue
        orphan_bns.append(test_bn)

    if orphan_bns:
        console.print("\n[bold]Unmatched Tests[/]")
        for bn in orphan_bns:
            for rel_path in test_map[bn]:
                console.print(f"\n• [underline]{rel_path}[/]")
                if not (bn.startswith(TEST_PREFIX) or any(bn.endswith(sfx) for sfx in TEST_AFFIXES)):
                    console.print(Text("  ↳ Filename should start with 'test_' or end with '_test.py'", style="red"))

                base = strip_test_affixes(bn)
                suggestion = None
                if base in script_map:
                    suggestion = base
                else:
                    matches = difflib.get_close_matches(base, script_map.keys(), n=1, cutoff=0.6)
                    suggestion = matches[0] if matches else None

                if suggestion:
                    console.print(Text(f"  ↳ Likely intended script: {suggestion}.py", style="yellow"))
                    console.print(Text(f"    • Rename test → [bold]test_{suggestion}.py[/]", style="green"))
                else:
                    console.print(Text("  ↳ No good script match found via fuzzy matching.", style="dim"))

                full_test_path = test_dir / rel_path
                content = full_test_path.read_text(encoding="utf8")
                imports = set(
                    m.group(1)
                    for m in re.finditer(
                        r"^\s*(?:from|import)\s+([A-Za-z_][\w\.]*)",
                        content,
                        flags=re.MULTILINE,
                    )
                )
                if imports:
                    console.print(Text(f"  ↳ Imports detected: {', '.join(imports)}", style="dim"))
                else:
                    console.print(Text("  ↳ No imports detected.", style="dim"))
    else:
        console.print("\n[green]All tests have matching scripts![/]")


if __name__ == "__main__":
    main()

