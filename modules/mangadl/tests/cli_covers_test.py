from pathlib import Path

from mangadl.cli import build_parser


def test_covers_parser_defaults_to_dry_run(tmp_path: Path) -> None:
    args = build_parser(["covers"]).parse_args(
        ["covers", "-U", str(tmp_path), "-d", str(tmp_path)]
    )

    assert args.command == "covers"
    assert not args.apply
    assert not args.force
    assert not args.apply_kavita
    assert args.kavita_api_key_env == "KAVITA_API_KEY"


def test_run_help_exposes_cover_default_and_advanced_kavita_options() -> None:
    normal = build_parser(["run", "--help"])
    advanced = build_parser(["run", "config", "--help"])

    normal_run = next(
        action for action in normal._actions if action.dest == "command"
    ).choices["run"]
    advanced_run = next(
        action for action in advanced._actions if action.dest == "command"
    ).choices["run"]

    assert "--no-download-covers" in normal_run.format_help()
    assert "--apply-kavita-covers" not in normal_run.format_help()
    assert "--apply-kavita-covers" in advanced_run.format_help()
    assert "--kavita-path-map" in advanced_run.format_help()
