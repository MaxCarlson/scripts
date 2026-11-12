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


def _normalized_help(parser: argparse.ArgumentParser) -> str:
    return " ".join(parser.format_help().split())


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
    help_text = _normalized_help(_run_parser(build_parser(["run", "--help"])))

    assert "--workers" in help_text
    assert "--max-workers" in help_text
    assert "--image-workers" in help_text
    assert "run optimize --help" in help_text
    assert "run benchmark --help" in help_text
    assert "run config --help" in help_text
    assert "--backend" not in help_text
    assert "--retry-wait" not in help_text
    assert "--cookies" not in help_text


def test_optimize_and_config_help_expose_relevant_options() -> None:
    optimize_help = _normalized_help(
        _run_parser(build_parser(["run", "optimize", "--help"]))
    )
    config_help = _normalized_help(
        _run_parser(build_parser(["run", "optimize", "config", "--help"]))
    )

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


def test_top_level_commands_are_compacted_and_include_covers() -> None:
    parser = build_parser()
    subparsers = next(
        action
        for action in parser._actions
        if isinstance(action, argparse._SubParsersAction)
    )
    choices = set(subparsers.choices.keys())

    expected = {
        "run",
        "audit",
        "repair",
        "clean",
        "covers",
        "kavita",
        "archive",
        "status",
        "retry",
        "auth",
        "favorites",
        "compress",
        "lock",
        "tui",
    }
    assert choices == expected
    assert "covers" in parser.format_help()


def test_compacted_and_legacy_commands_parse_identically(tmp_path) -> None:
    parser = build_parser()

    # Repair suite: canonical subcommands, direct flag inference, and legacy aliases
    r_batch = parser.parse_args(["repair", "batch", "-r", str(tmp_path / "r.json")])
    r_infer_batch = parser.parse_args(["repair", "-r", str(tmp_path / "r.json")])
    assert r_batch.command == r_infer_batch.command == "repair"
    assert r_batch.repair_command == r_infer_batch.repair_command == "batch"

    r_pages = parser.parse_args(["repair", "pages", "-u", "https://nhentai.net/g/1/", "-d", str(tmp_path)])
    r_infer_pages = parser.parse_args(["repair", "-u", "https://nhentai.net/g/1/", "-d", str(tmp_path)])
    r_legacy_pages = parser.parse_args(["repair-pages", "-u", "https://nhentai.net/g/1/", "-d", str(tmp_path)])
    assert r_pages.repair_command == r_infer_pages.repair_command == r_legacy_pages.repair_command == "pages"

    r_loose = parser.parse_args(["repair", "loose", "-d", str(tmp_path), "-n"])
    r_legacy_loose = parser.parse_args(["repair-loose", "-d", str(tmp_path), "-n"])
    assert r_loose.repair_command == r_legacy_loose.repair_command == "loose"
    assert r_loose.dry_run and r_legacy_loose.dry_run

    r_patch = parser.parse_args(["repair", "hdporncomics", "-f"])
    r_legacy_patch = parser.parse_args(["patch-hdporncomics", "-f"])
    assert r_patch.repair_command == r_legacy_patch.repair_command == "hdporncomics"
    assert r_patch.apply and r_legacy_patch.apply

    # Clean: canonical top-level and legacy partials clean / cleanup
    c_direct = parser.parse_args(["clean", "-d", str(tmp_path), "-F"])
    c_legacy = parser.parse_args(["partials", "clean", "-d", str(tmp_path), "-F"])
    c_cleanup = parser.parse_args(["partials", "cleanup", "-d", str(tmp_path), "-F"])
    assert c_direct.command == c_legacy.command == c_cleanup.command == "clean"
    assert c_direct.files_only and c_legacy.files_only and c_cleanup.files_only

    # Kavita assign: unified selector and legacy assign-*
    k_name = parser.parse_args(["kavita", "assign", "-n", "Series", "-c", "Col", "-K", "http://kavita"])
    k_legacy_name = parser.parse_args(["kavita", "assign-name", "-n", "Series", "-c", "Col", "-Z", "http://kavita"])
    assert k_name.kavita_command == k_legacy_name.kavita_command == "assign"
    assert k_name.name == k_legacy_name.name == ["Series"]

    # Status / inspect unification
    s_probe = parser.parse_args(["status", "-u", "https://manga18fx.com/manga/a/"])
    s_legacy = parser.parse_args(["inspect", "-u", "https://manga18fx.com/manga/a/"])
    assert s_probe.command == s_legacy.command == "status"
    assert s_probe.url == s_legacy.url == ["https://manga18fx.com/manga/a/"]


def test_run_scratch_short_flag_does_not_collide_in_config_mode(tmp_path) -> None:
    normal_args = build_parser(["run"]).parse_args(
        ["run", "-u", "https://manga18fx.com/manga/a/", "-d", str(tmp_path), "-S", str(tmp_path / "scratch")]
    )
    config_args = build_parser(["run", "config"]).parse_args(
        ["run", "config", "-u", "https://manga18fx.com/manga/a/", "-d", str(tmp_path), "-S", str(tmp_path / "scratch")]
    )
    assert normal_args.scratch_dir == tmp_path / "scratch"
    assert config_args.scratch_dir == tmp_path / "scratch"
    assert config_args.kavita_api_key_env == "KAVITA_API_KEY"


def test_archive_help_exposes_all_options_without_config_keyword() -> None:
    parser = build_parser(["archive", "--help"])
    subparsers = next(
        action
        for action in parser._actions
        if isinstance(action, argparse._SubParsersAction)
    )
    help_text = _normalized_help(subparsers.choices["archive"])
    assert "--filter" in help_text
    assert "--export" in help_text
    assert "--no-ui" in help_text
    assert "--json" in help_text
