import argparse

import pytest

from mangadl.cli import build_parser
from mangadl.cli_structure import normalize_command_shape


def _run_parser(parser: argparse.ArgumentParser) -> argparse.ArgumentParser:
    subparsers = next(
        action
        for action in parser._actions
        if isinstance(action, argparse._SubParsersAction)
    )
    return subparsers.choices["run"]


def test_command_shape_normalizes_run_modes_and_config() -> None:
    optimize = normalize_command_shape(["run", "optimize", "config", "-i", "urls.txt"])
    benchmark = normalize_command_shape(["run", "benchmark", "-i", "urls.txt"])
    normal_config = normalize_command_shape(["run", "config", "-i", "urls.txt"])
    archive = normalize_command_shape(["archive", "config", "-a", "archive.db"])

    assert optimize.run_mode == "optimize"
    assert optimize.advanced_config
    assert optimize.argv[:2] == ("run", "-i")
    assert benchmark.run_mode == "benchmark"
    assert not benchmark.advanced_config
    assert normal_config.run_mode == "normal"
    assert normal_config.advanced_config
    assert archive.archive_config
    assert archive.argv[:2] == ("archive", "-a")


def test_normal_run_help_hides_expert_options_and_advertises_modes() -> None:
    help_text = _run_parser(build_parser(["run", "--help"])).format_help()

    assert "--workers" in help_text
    assert "--image-workers" in help_text
    assert "run optimize --help" in help_text
    assert "run benchmark --help" in help_text
    assert "run config --help" in help_text
    assert "--backend" not in help_text
    assert "--retry-wait" not in help_text
    assert "--cookies" not in help_text


def test_optimize_and_config_help_expose_relevant_options() -> None:
    optimize_help = _run_parser(build_parser(["run", "optimize", "--help"])).format_help()
    config_help = _run_parser(
        build_parser(["run", "optimize", "config", "--help"])
    ).format_help()

    assert "--min-workers" in optimize_help
    assert "--max-image-workers" in optimize_help
    assert "--evaluation" in optimize_help
    assert "run optimize config --help" in optimize_help
    assert "--backend" not in optimize_help
    assert "--backend" in config_help
    assert "--worker-start-delay" in config_help


def test_new_runs_do_not_accept_manual_run_ids(tmp_path) -> None:
    parser = build_parser(["run"])

    with pytest.raises(SystemExit):
        parser.parse_args(
            [
                "run",
                "-u",
                "https://manga18fx.com/manga/example/",
                "-d",
                str(tmp_path / "out"),
                "-a",
                str(tmp_path / "archive.db"),
                "-R",
                "manual-id",
            ]
        )
