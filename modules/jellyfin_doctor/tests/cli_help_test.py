from __future__ import annotations

import argparse

import pytest
from jellyfin_doctor.cli import build_parser, parse_args

HELP_COMMANDS = [
    ["-h"],
    ["monitor", "-h"],
    ["monitor", "scan", "-h"],
    ["backup", "create", "-h"],
    ["reset", "full", "-h"],
    ["diagnose", "logs", "-h"],
]


@pytest.mark.parametrize("argv", HELP_COMMANDS)
def test_help_pages_exit_cleanly(argv: list[str], capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        parse_args(argv)
    assert exc.value.code == 0
    assert "usage:" in capsys.readouterr().out


def _walk_parsers(parser: argparse.ArgumentParser) -> list[argparse.ArgumentParser]:
    parsers = [parser]
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            for subparser in action.choices.values():
                parsers.extend(_walk_parsers(subparser))
    return parsers


def test_every_public_option_has_short_and_long_form() -> None:
    for parser in _walk_parsers(build_parser()):
        for action in parser._actions:
            options = action.option_strings
            if not options or action.dest == "help":
                continue
            assert any(option.startswith("-") and not option.startswith("--") for option in options), action.dest
            assert any(option.startswith("--") for option in options), action.dest


def test_nested_parse_sets_expected_commands() -> None:
    args = parse_args(["monitor", "scan", "-t", "1", "-j"])
    assert args.command == "monitor"
    assert args.monitor_command == "scan"
    assert args.timeout_minutes == 1
    assert args.json is True


