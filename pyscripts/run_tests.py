#!/usr/bin/env python3
"""
run_tests.py — Interactive pytest runner for the scripts repository.

Presents menus for verbosity and scope, then runs pytest.
"""
from __future__ import annotations

__version__ = "0.1.0"

import argparse
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# (label, pytest flags)
VERBOSITY_LEVELS: list[tuple[str, list[str]]] = [
    ("Minimal",  ["--tb=no",    "-q"]),
    ("Short",    ["--tb=short", "-q"]),
    ("Normal",   ["--tb=short"]),
    ("Verbose",  ["--tb=short", "-v"]),
    ("Full",     ["--tb=long",  "-v", "-s"]),
]

_A: dict[str, str] = {
    "bold":   "\033[1m",
    "cyan":   "\033[96m",
    "green":  "\033[92m",
    "yellow": "\033[93m",
    "gray":   "\033[90m",
    "reset":  "\033[0m",
}

def _c(color: str, text: str) -> str:
    return (_A.get(color, "") + text + _A["reset"]) if sys.stdout.isatty() else text


def _print_header(title: str) -> None:
    print()
    print(_c("bold", title))


def _pick_single(title: str, options: list[str]) -> int:
    _print_header(title)
    for i, opt in enumerate(options, 1):
        print(f"  {_c('cyan', f'{i:>2}')}.  {opt}")
    prompt = _c("yellow", f"  Choice [1-{len(options)}]: ")
    while True:
        try:
            val = int(input(prompt).strip()) - 1
            if 0 <= val < len(options):
                return val
        except (ValueError, EOFError):
            pass
        print(f"  Enter a number between 1 and {len(options)}.")


def _pick_multi(title: str, items: list[str]) -> list[int]:
    _print_header(title)
    for i, item in enumerate(items, 1):
        print(f"  {_c('cyan', f'{i:>3}')}.  {item}")
    prompt = _c("yellow", f"  Choice(s) [1-{len(items)}, space or comma separated]: ")
    while True:
        try:
            raw = input(prompt).strip()
            indices = [int(x) - 1 for x in raw.replace(",", " ").split()]
            if indices and all(0 <= i < len(items) for i in indices):
                return indices
        except (ValueError, EOFError):
            pass
        print(f"  Enter numbers between 1 and {len(items)}.")


def _discover_modules() -> list[str]:
    mods_dir = REPO_ROOT / "modules"
    return sorted(
        d.name for d in mods_dir.iterdir()
        if d.is_dir() and not d.name.startswith(("_", ".")) and (d / "tests").is_dir()
    )


def _discover_pyscripts() -> list[str]:
    tests_dir = REPO_ROOT / "pyscripts" / "tests"
    if not tests_dir.is_dir():
        return []
    return sorted(f.stem.removesuffix("_test") for f in tests_dir.glob("*_test.py"))


def _select_specific() -> list[str]:
    modules = _discover_modules()
    pyscripts = _discover_pyscripts()
    items = (
        [f"{_c('gray', '[module]  ')} {m}" for m in modules]
        + [f"{_c('gray', '[pyscript]')} {p}" for p in pyscripts]
    )
    if not items:
        print("  No testable modules or pyscripts discovered.")
        return ["modules/", "pyscripts/"]

    indices = _pick_multi("Select target(s):", items)

    n_mod = len(modules)
    paths: list[str] = []
    for i in indices:
        if i < n_mod:
            paths.append(f"modules/{modules[i]}")
        else:
            py_name = pyscripts[i - n_mod]
            test_file = REPO_ROOT / "pyscripts" / "tests" / f"{py_name}_test.py"
            paths.append(str(test_file.relative_to(REPO_ROOT)).replace("\\", "/"))
    return paths


def _resolve_scope(args: argparse.Namespace) -> list[str]:
    # CLI shortcuts bypass menus
    if args.modules or args.pyscripts:
        paths: list[str] = []
        for name in (args.modules or []):
            paths.append(f"modules/{name}")
        for name in (args.pyscripts or []):
            test_file = REPO_ROOT / "pyscripts" / "tests" / f"{name}_test.py"
            paths.append(str(test_file.relative_to(REPO_ROOT)).replace("\\", "/"))
        return paths

    scope_map = {
        "all":       ["modules/", "pyscripts/"],
        "modules":   ["modules/"],
        "pyscripts": ["pyscripts/"],
    }
    if args.scope in scope_map:
        return scope_map[args.scope]  # type: ignore[index]
    if args.scope == "specific":
        return _select_specific()

    # Interactive scope menu
    idx = _pick_single(
        "Test scope:",
        [
            "All              modules/ + pyscripts/",
            "Modules only     modules/",
            "Pyscripts only   pyscripts/",
            "Specific         choose from list",
        ],
    )
    return [
        ["modules/", "pyscripts/"],
        ["modules/"],
        ["pyscripts/"],
        None,  # type: ignore[list-item]
    ][idx] or _select_specific()


def main() -> None:
    p = argparse.ArgumentParser(
        prog="run-tests",
        description="Interactive pytest runner for the scripts repository.",
    )
    p.add_argument(
        "-V", "--verbosity",
        type=int, choices=range(1, len(VERBOSITY_LEVELS) + 1),
        metavar=f"1-{len(VERBOSITY_LEVELS)}",
        help=(
            "Pre-select verbosity, skipping the menu: "
            + ", ".join(f"{i+1}={name}" for i, (name, _) in enumerate(VERBOSITY_LEVELS))
        ),
    )
    p.add_argument(
        "-s", "--scope",
        choices=["all", "modules", "pyscripts", "specific"],
        help="Pre-select scope, skipping the menu",
    )
    p.add_argument(
        "-m", "--module", action="append", dest="modules", metavar="NAME",
        help="Target a specific module by name (repeatable; implies specific scope)",
    )
    p.add_argument(
        "-p", "--pyscript", action="append", dest="pyscripts", metavar="NAME",
        help="Target a specific pyscript by name (repeatable; implies specific scope)",
    )
    p.add_argument(
        "-n", "--dry-run", action="store_true",
        help="Print the pytest command without running it",
    )
    p.add_argument(
        "-q", "--quiet", action="store_true",
        help="Suppress the command echo before running",
    )
    args = p.parse_args()

    # Verbosity
    if args.verbosity:
        v_idx = args.verbosity - 1
    else:
        v_idx = _pick_single(
            "Verbosity level:",
            [f"{name:8}  pytest {' '.join(flags)}" for name, flags in VERBOSITY_LEVELS],
        )
    _, v_flags = VERBOSITY_LEVELS[v_idx]

    # Scope
    paths = _resolve_scope(args)

    cmd = ["pytest"] + v_flags + paths

    if not args.quiet:
        print()
        print(_c("green", ">> ") + _c("bold", " ".join(cmd)))
        print()

    if args.dry_run:
        return

    result = subprocess.run(cmd, cwd=str(REPO_ROOT))
    sys.exit(result.returncode)


if __name__ == "__main__":
    main()
