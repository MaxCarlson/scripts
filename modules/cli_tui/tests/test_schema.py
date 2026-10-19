from __future__ import annotations

import argparse
from pathlib import Path

from cli_tui.schema import CliCommand, introspect_parser


def test_introspect_flat_parser():
    parser = argparse.ArgumentParser(prog="mytool", description="A sample CLI tool")
    parser.add_argument("source", help="Source path")
    parser.add_argument(
        "-d",
        "--destination",
        type=Path,
        default=Path("."),
        help="Destination directory",
    )
    parser.add_argument("-w", "--workers", type=int, default=4, help="Worker count")
    parser.add_argument(
        "-f",
        "--format",
        choices=("webp", "jpeg", "png"),
        default="webp",
        help="Image format",
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="Verbose logging")
    parser.add_argument(
        "-S",
        "--sort",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Sort output",
    )
    parser.add_argument(
        "-q", "--quality", type=int, nargs="+", default=[85], help="Quality levels"
    )
    parser.add_argument("--secret", help=argparse.SUPPRESS)

    cmd = introspect_parser(parser)

    assert isinstance(cmd, CliCommand)
    assert cmd.name == "mytool"
    assert cmd.description == "A sample CLI tool"
    assert len(cmd.subcommands) == 0

    # Ensure suppressed flag is excluded
    assert not any(arg.dest == "secret" for arg in cmd.arguments)

    # Positional
    source_arg = next(arg for arg in cmd.arguments if arg.dest == "source")
    assert source_arg.is_positional
    assert source_arg.required
    assert source_arg.help == "Source path"

    # Optional destination
    dest_arg = next(arg for arg in cmd.arguments if arg.dest == "destination")
    assert not dest_arg.is_positional
    assert "-d" in dest_arg.flags
    assert "--destination" in dest_arg.flags
    assert dest_arg.default == Path(".")

    # Choices format
    fmt_arg = next(arg for arg in cmd.arguments if arg.dest == "format")
    assert fmt_arg.choices == ("webp", "jpeg", "png")
    assert fmt_arg.default == "webp"

    # BooleanOptionalAction
    sort_arg = next(arg for arg in cmd.arguments if arg.dest == "sort")
    assert sort_arg.action_type == "boolean_optional"
    assert sort_arg.default is True

    # Nargs +
    quality_arg = next(arg for arg in cmd.arguments if arg.dest == "quality")
    assert quality_arg.nargs == "+"
    assert quality_arg.default == [85]


def test_introspect_nested_subparsers():
    parser = argparse.ArgumentParser(prog="git")
    parser.add_argument("-C", "--directory", help="Run as if git was started in <path>")
    subparsers = parser.add_subparsers(dest="subcommand", required=True)

    remote = subparsers.add_parser("remote", help="Manage set of tracked repositories")
    remote_subparsers = remote.add_subparsers(dest="remote_subcommand")

    add_cmd = remote_subparsers.add_parser("add", help="Add a remote")
    add_cmd.add_argument("name", help="Remote name")
    add_cmd.add_argument("url", help="Remote URL")
    add_cmd.add_argument("-f", "--fetch", action="store_true", help="Fetch immediately")

    cmd = introspect_parser(parser)

    assert cmd.name == "git"
    assert "remote" in cmd.subcommands
    remote_cmd = cmd.subcommands["remote"]
    assert remote_cmd.help == "Manage set of tracked repositories"
    assert "add" in remote_cmd.subcommands

    add_node = remote_cmd.subcommands["add"]
    assert len(add_node.arguments) == 3
    assert any(a.dest == "name" and a.is_positional for a in add_node.arguments)
    assert any(a.dest == "url" and a.is_positional for a in add_node.arguments)
    assert any(a.dest == "fetch" and not a.is_positional for a in add_node.arguments)
