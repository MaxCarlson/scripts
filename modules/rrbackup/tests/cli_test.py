"""Tests for the transitional RRBackup CLI.

These tests cover the current public surface while the hierarchical ``backup`` CLI is
implemented. They intentionally avoid user configuration, external services, and mocks
of ``Path.open`` that can change TOML binary/text semantics.
"""

from __future__ import annotations

import argparse
from collections.abc import Iterable

import pytest

from rrbackup.cli import CLI_CONFIGURATION_ERROR_EXIT, build_parser, main


@pytest.mark.unit
class TestBuildParser:
    """Cover global parser behavior."""

    def test_parser_created(self) -> None:
        parser = build_parser()

        assert isinstance(parser, argparse.ArgumentParser)
        assert parser.prog == "rrb"

    @pytest.mark.parametrize("option", ["--version", "-V"])
    def test_version_flags(self, option: str, capsys: pytest.CaptureFixture[str]) -> None:
        parser = build_parser()

        with pytest.raises(SystemExit) as exc_info:
            parser.parse_args([option])

        assert exc_info.value.code == 0
        assert "rrb" in capsys.readouterr().out

    @pytest.mark.parametrize(
        ("arguments", "attribute", "expected"),
        [
            (["--config", "/tmp/config.toml", "list"], "config", "/tmp/config.toml"),
            (["-c", "/tmp/config.toml", "list"], "config", "/tmp/config.toml"),
            (["--verbose", "list"], "verbose", True),
            (["-v", "list"], "verbose", True),
        ],
    )
    def test_global_flags(
        self,
        arguments: list[str],
        attribute: str,
        expected: object,
    ) -> None:
        args = build_parser().parse_args(arguments)

        assert getattr(args, attribute) == expected

    def test_invalid_command_exits_nonzero(self) -> None:
        with pytest.raises(SystemExit) as exc_info:
            build_parser().parse_args(["invalid-command"])

        assert exc_info.value.code != 0


@pytest.mark.unit
class TestSetupCommand:
    """Cover legacy setup command parsing."""

    def test_setup_command_parsed(self) -> None:
        args = build_parser().parse_args(["setup"])

        assert args.cmd == "setup"
        assert callable(args.func)

    @pytest.mark.parametrize(
        ("arguments", "attribute", "expected"),
        [
            (["setup", "--password-file", "/tmp/pwd.txt"], "password_file", "/tmp/pwd.txt"),
            (["setup", "-p", "/tmp/pwd.txt"], "password_file", "/tmp/pwd.txt"),
            (["setup", "--remote-check"], "remote_check", True),
            (["setup", "-r"], "remote_check", True),
            (["setup", "--wizard"], "wizard", True),
            (["setup", "-w"], "wizard", True),
        ],
    )
    def test_setup_flags(
        self,
        arguments: list[str],
        attribute: str,
        expected: object,
    ) -> None:
        args = build_parser().parse_args(arguments)

        assert getattr(args, attribute) == expected


@pytest.mark.unit
class TestListCommand:
    """Cover snapshot-list command parsing."""

    def test_list_command_parsed(self) -> None:
        args = build_parser().parse_args(["list"])

        assert args.cmd == "list"

    def test_list_filters_and_short_forms(self) -> None:
        args = build_parser().parse_args(
            [
                "list",
                "-P",
                "/home",
                "--path",
                "/data",
                "-t",
                "daily",
                "--tag",
                "important",
                "-H",
                "desktop",
            ]
        )

        assert args.path == ["/home", "/data"]
        assert args.tag == ["daily", "important"]
        assert args.host == "desktop"


@pytest.mark.unit
class TestBackupCommand:
    """Cover legacy backup command parsing."""

    def test_backup_requires_set(self) -> None:
        with pytest.raises(SystemExit):
            build_parser().parse_args(["backup"])

    @pytest.mark.parametrize("option", ["--set", "-s"])
    def test_set_option(self, option: str) -> None:
        args = build_parser().parse_args(["backup", option, "documents"])

        assert args.set == "documents"

    @pytest.mark.parametrize("option", ["--dry-run", "-n"])
    def test_dry_run_option(self, option: str) -> None:
        args = build_parser().parse_args(["backup", "-s", "documents", option])

        assert args.dry_run is True

    def test_repeatable_overrides_and_raw_restic_arg(self) -> None:
        args = build_parser().parse_args(
            [
                "backup",
                "-s",
                "documents",
                "-t",
                "pre-upgrade",
                "--tag",
                "manual",
                "-e",
                "*.tmp",
                "--exclude",
                "*.log",
                "-x=--verbose",
            ]
        )

        assert args.tag == ["pre-upgrade", "manual"]
        assert args.exclude == ["*.tmp", "*.log"]
        assert args.extra == ["--verbose"]


@pytest.mark.unit
class TestSimpleCommands:
    """Cover no-argument command registration."""

    @pytest.mark.parametrize("command", ["stats", "check", "prune", "progress"])
    def test_command_parsed(self, command: str) -> None:
        args = build_parser().parse_args([command])

        assert args.cmd == command
        assert callable(args.func)


@pytest.mark.unit
class TestConfigSubcommands:
    """Cover configuration command registration and options."""

    def test_init(self) -> None:
        args = build_parser().parse_args(["config", "init", "-f"])

        assert args.cmd == "config"
        assert args.config_cmd == "init"
        assert args.force is True

    def test_wizard(self) -> None:
        args = build_parser().parse_args(["config", "wizard", "-i"])

        assert args.config_cmd == "wizard"
        assert args.initialize_repo is True

    def test_show(self) -> None:
        args = build_parser().parse_args(["config", "show", "-e"])

        assert args.config_cmd == "show"
        assert args.effective is True

    def test_list_sets(self) -> None:
        args = build_parser().parse_args(["config", "list-sets"])

        assert args.config_cmd == "list-sets"

    def test_add_set(self) -> None:
        args = build_parser().parse_args(
            [
                "config",
                "add-set",
                "-n",
                "photos",
                "-i",
                "/home/pics",
                "--include",
                "/data/photos",
                "-e",
                "*.tmp",
                "-t",
                "important",
                "-S",
                "daily 03:00",
                "-M",
                "50",
            ]
        )

        assert args.config_cmd == "add-set"
        assert args.name == "photos"
        assert args.include == ["/home/pics", "/data/photos"]
        assert args.exclude == ["*.tmp"]
        assert args.tag == ["important"]
        assert args.schedule == "daily 03:00"
        assert args.max_snapshots == 50

    def test_remove_set(self) -> None:
        args = build_parser().parse_args(["config", "remove-set", "-n", "old-set"])

        assert args.config_cmd == "remove-set"
        assert args.name == "old-set"

    def test_set_values(self) -> None:
        args = build_parser().parse_args(
            [
                "config",
                "set",
                "-r",
                "/new/repo",
                "-P",
                "/new/pwd.txt",
                "-R",
                "/usr/local/bin/restic",
            ]
        )

        assert args.config_cmd == "set"
        assert args.repo_url == "/new/repo"
        assert args.password_file == "/new/pwd.txt"
        assert args.restic_bin == "/usr/local/bin/restic"

    def test_retention_values(self) -> None:
        args = build_parser().parse_args(
            [
                "config",
                "retention",
                "-L",
                "5",
                "-D",
                "7",
                "-W",
                "4",
                "-M",
                "12",
                "-Y",
                "10",
            ]
        )

        assert args.config_cmd == "retention"
        assert args.keep_last == 5
        assert args.keep_daily == 7
        assert args.keep_weekly == 4
        assert args.keep_monthly == 12
        assert args.keep_yearly == 10

    @pytest.mark.parametrize(
        ("option", "attribute"),
        [("-u", "use_defaults"), ("--use-defaults", "use_defaults"), ("-X", "clear"), ("--clear", "clear")],
    )
    def test_retention_flags(self, option: str, attribute: str) -> None:
        args = build_parser().parse_args(["config", "retention", option])

        assert getattr(args, attribute) is True


@pytest.mark.unit
class TestMainFunction:
    """Cover dispatch and stable error boundaries."""

    def test_no_arguments_exits_nonzero(self) -> None:
        with pytest.raises(SystemExit) as exc_info:
            main([])

        assert exc_info.value.code != 0

    def test_list_dispatches_with_loaded_config(
        self,
        mocker,
        temp_dir,
        sample_config_dict,
    ) -> None:
        import tomli_w

        config_file = temp_dir / "test.toml"
        config_file.write_text(tomli_w.dumps(sample_config_dict), encoding="utf-8")
        mocked_list = mocker.patch("rrbackup.cli.list_snapshots")
        mocker.patch("rrbackup.config.shutil.which", return_value="restic")

        result = main(["-c", str(config_file), "list"])

        assert result == 0
        mocked_list.assert_called_once()

    def test_missing_config_returns_stable_error(
        self,
        temp_dir,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        missing_config = temp_dir / "missing.toml"

        result = main(["-c", str(missing_config), "list"])

        assert result == CLI_CONFIGURATION_ERROR_EXIT
        assert "Config file not found" in capsys.readouterr().err


def _iter_parsers(parser: argparse.ArgumentParser) -> Iterable[argparse.ArgumentParser]:
    """Yield a parser and all nested subparsers."""
    yield parser
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            for child in action.choices.values():
                yield from _iter_parsers(child)


@pytest.mark.unit
def test_every_public_long_option_has_a_short_form() -> None:
    """Enforce the repository's short-plus-long option convention recursively."""
    for parser in _iter_parsers(build_parser()):
        for action in parser._actions:
            public_options = [option for option in action.option_strings if option != "--help"]
            long_options = [option for option in public_options if option.startswith("--")]
            if not long_options:
                continue

            short_options = [
                option
                for option in public_options
                if option.startswith("-") and not option.startswith("--")
            ]
            assert short_options, (
                f"{parser.prog}: {', '.join(long_options)} has no short option"
            )
