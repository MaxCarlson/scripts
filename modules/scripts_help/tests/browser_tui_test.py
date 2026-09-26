"""Focused tests for the structure-first scripts-help browser."""

from __future__ import annotations

import sys
from pathlib import Path

_MOD_ROOT = Path(__file__).resolve().parents[2] / "scripts_help"
if str(_MOD_ROOT.parent) not in sys.path:
    sys.path.insert(0, str(_MOD_ROOT.parent))

from scripts_help.help_parser import format_argument, parse_help_text  # noqa: E402
from scripts_help.inventory import build_categories  # noqa: E402
from scripts_help.tui import MenuEntry, filter_entries  # noqa: E402


def test_parse_argparse_options_and_subcommands() -> None:
    text = """usage: demo [-h] [-v] {scan,run} ...

positional arguments:
  {scan,run}
    scan                Scan files
    run                 Run the tool

options:
  -h, --help            show this help message and exit
  -v, --verbose         enable verbose output
"""
    parsed = parse_help_text(text)

    assert [(arg.short, arg.long) for arg in parsed.arguments] == [
        ("-h", "--help"),
        ("-v", "--verbose"),
    ]
    assert [sub.name for sub in parsed.subcommands] == ["scan", "run"]
    assert parsed.subcommands[0].description == "Scan files"


def test_parse_click_style_commands() -> None:
    text = """Usage: demo [OPTIONS] COMMAND [ARGS]...

Options:
  -q, --quiet  Suppress normal output.
  --json       Emit JSON.

Commands:
  clean  Clean generated files.
  sync   Synchronize state.
"""
    parsed = parse_help_text(text)

    assert parsed.arguments[0].short == "-q"
    assert parsed.arguments[0].long == "--quiet"
    assert parsed.arguments[1].short is None
    assert parsed.arguments[1].long == "--json"
    assert [sub.name for sub in parsed.subcommands] == ["clean", "sync"]


def test_format_argument_always_places_short_before_long() -> None:
    parsed = parse_help_text(
        "options:\n  --output PATH, -o PATH    Destination file.\n"
    )
    assert format_argument(parsed.arguments[0]).startswith("-o  --output")
    assert format_argument(parsed.arguments[0]).endswith("Destination file.")


def test_filter_entries_preserves_original_numbers() -> None:
    entries = [
        MenuEntry(1, "alpha", "first utility", object(), "modules/alpha"),
        MenuEntry(12, "beta", "second utility", object(), "modules/beta"),
        MenuEntry(27, "gamma", "third utility", object(), "modules/gamma"),
    ]

    filtered = filter_entries(entries, "beta")

    assert [entry.number for entry in filtered] == [12]


def test_filter_entries_matches_description_and_path() -> None:
    entries = [
        MenuEntry(1, "alpha", "image converter", object(), "modules/alpha"),
        MenuEntry(2, "beta", "network helper", object(), "pyscripts/beta.py"),
    ]

    assert [entry.number for entry in filter_entries(entries, "network")] == [2]
    assert [entry.number for entry in filter_entries(entries, "pyscripts")] == [2]


def test_inventory_uses_runtime_structure_and_readme_description(tmp_path: Path) -> None:
    module = tmp_path / "modules" / "demo"
    module.mkdir(parents=True)
    (module / "pyproject.toml").write_text(
        '[project]\nname = "demo"\nversion = "1.2.3"\ndescription = "Short project description."\n',
        encoding="utf-8",
    )
    (module / "README.md").write_text(
        "# Demo\n\nA longer README paragraph explaining what Demo does and why it exists.\n",
        encoding="utf-8",
    )

    pyscripts = tmp_path / "pyscripts"
    pyscripts.mkdir()
    (pyscripts / "thing.py").write_text(
        '"""Standalone thing utility."""\n',
        encoding="utf-8",
    )

    categories = {category.key: category for category in build_categories(tmp_path)}

    assert "modules" in categories
    assert "pyscripts" in categories
    demo = next(item for item in categories["modules"].items if item.path == "modules/demo")
    assert demo.version == "1.2.3"
    assert demo.long_description.startswith("A longer README paragraph")


def test_inventory_discovers_shell_and_powershell_groups(tmp_path: Path) -> None:
    (tmp_path / "shell-scripts").mkdir()
    (tmp_path / "shell-scripts" / "clean.sh").write_text(
        "#!/usr/bin/env bash\n# Clean generated files.\n",
        encoding="utf-8",
    )
    (tmp_path / "pwsh").mkdir()
    (tmp_path / "pwsh" / "clean.ps1").write_text(
        "# Clean generated files on Windows.\n",
        encoding="utf-8",
    )

    categories = {category.key: category for category in build_categories(tmp_path)}

    assert [item.path for item in categories["shell"].items] == ["shell-scripts/clean.sh"]
    assert [item.path for item in categories["powershell"].items] == ["pwsh/clean.ps1"]
