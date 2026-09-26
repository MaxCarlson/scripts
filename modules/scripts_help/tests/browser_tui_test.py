"""Focused tests for the structure-first scripts-help browser."""

from __future__ import annotations

import sys
from pathlib import Path

_MOD_ROOT = Path(__file__).resolve().parents[2] / "scripts_help"
if str(_MOD_ROOT.parent) not in sys.path:
    sys.path.insert(0, str(_MOD_ROOT.parent))

from scripts_help.help_parser import format_argument, parse_help_text  # noqa: E402
from scripts_help.inventory import HelpItem, build_categories  # noqa: E402
from scripts_help.tui import (  # noqa: E402
    MenuEntry,
    _resolve_help_command,
    _run_help,
    _select_menu,
    filter_entries,
)


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
        '[project]\n'
        'name = "demo"\n'
        'version = "1.2.3"\n'
        'description = "Short project description."\n'
        '\n'
        '[project.scripts]\n'
        'demo = "demo.cli:main"\n',
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
    assert demo.help_cmd == ("demo", "--help")
    assert demo.entrypoint == "demo.cli:main"
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


class _FakeReader:
    def __init__(self, keys: list[str]) -> None:
        self.keys = iter(keys)

    def read(self, timeout=None) -> str:
        return next(self.keys)


def _menu_entries(count: int = 12) -> list[MenuEntry]:
    return [
        MenuEntry(index, f"item-{index}", f"description {index}", index)
        for index in range(1, count + 1)
    ]


def test_menu_accepts_multi_digit_number(monkeypatch) -> None:
    monkeypatch.setattr("scripts_help.tui._write_screen", lambda *_args, **_kwargs: None)
    monkeypatch.setattr("scripts_help.tui._terminal_size", lambda: (100, 30))
    reader = _FakeReader(["1", "2"])

    selected = _select_menu(
        reader,
        "Items",
        "",
        _menu_entries(),
        allow_search=True,
    )

    assert selected is not None
    assert selected.number == 12


def test_menu_enter_commits_pending_number(monkeypatch) -> None:
    monkeypatch.setattr("scripts_help.tui._write_screen", lambda *_args, **_kwargs: None)
    monkeypatch.setattr("scripts_help.tui._terminal_size", lambda: (100, 30))
    reader = _FakeReader(["1", "ENTER"])

    selected = _select_menu(
        reader,
        "Items",
        "",
        _menu_entries(),
        allow_search=True,
    )

    assert selected is not None
    assert selected.number == 1


def test_search_escape_keeps_filter_then_second_escape_clears(monkeypatch) -> None:
    monkeypatch.setattr("scripts_help.tui._write_screen", lambda *_args, **_kwargs: None)
    monkeypatch.setattr("scripts_help.tui._terminal_size", lambda: (100, 30))
    entries = [
        MenuEntry(1, "alpha", "", "alpha"),
        MenuEntry(2, "beta", "", "beta"),
    ]
    # /b filters to beta. First Esc exits search editing while retaining "b".
    # Second Esc clears "b". Down then selects beta from the full list.
    reader = _FakeReader(["/", "b", "ESC", "ESC", "DOWN", "ENTER"])

    selected = _select_menu(reader, "Items", "", entries, allow_search=True)

    assert selected is not None
    assert selected.payload == "beta"


def test_inventory_infers_argparse_help_for_unregistered_python_script(tmp_path: Path) -> None:
    pyscripts = tmp_path / "pyscripts"
    pyscripts.mkdir()
    (pyscripts / "demo.py").write_text(
        '"""Demo utility."""\n'
        "import argparse\n"
        "def main():\n"
        "    argparse.ArgumentParser().parse_args()\n"
        'if __name__ == "__main__":\n'
        "    main()\n",
        encoding="utf-8",
    )

    categories = {category.key: category for category in build_categories(tmp_path)}
    demo = next(item for item in categories["pyscripts"].items if item.path == "pyscripts/demo.py")

    assert demo.help_cmd == ("python", "pyscripts/demo.py", "--help")


def test_run_help_uses_declared_entrypoint_from_src_layout(tmp_path: Path) -> None:
    package = tmp_path / "modules" / "demo" / "src" / "demo"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text("", encoding="utf-8")
    (package / "cli.py").write_text(
        "import argparse\n"
        "def main():\n"
        "    parser = argparse.ArgumentParser(prog='demo')\n"
        "    sub = parser.add_subparsers(dest='command')\n"
        "    scan = sub.add_parser('scan')\n"
        "    scan.add_argument('-v', '--verbose', action='store_true', "
        "help='Enable verbose output.')\n"
        "    parser.parse_args()\n",
        encoding="utf-8",
    )
    item = HelpItem(
        name="demo",
        path="modules/demo",
        description="demo",
        long_description="demo",
        help_cmd=("demo", "--help"),
        version="1.0.0",
        entrypoint="demo.cli:main",
    )

    command = _resolve_help_command(item, tmp_path, ("scan",))
    output, executed = _run_help(item, tmp_path, ("scan",))

    assert command == executed
    assert command[0] == sys.executable
    assert command[1] == "-c"
    assert str(tmp_path / "modules" / "demo" / "src") in command[2]
    assert "-v, --verbose" in output
    assert "Enable verbose output." in output
