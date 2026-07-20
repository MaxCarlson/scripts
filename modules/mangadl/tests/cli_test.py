import argparse

from mangadl.cli import build_parser, main


def test_all_public_options_have_short_and_long_forms() -> None:
    parser = build_parser()
    parsers = [parser]
    subparsers = next(action for action in parser._actions if isinstance(action, argparse._SubParsersAction))
    parsers.extend(subparsers.choices.values())
    for current in parsers:
        for action in current._actions:
            if not action.option_strings or action.dest == "help":
                continue
            assert any(option.startswith("--") for option in action.option_strings), action.dest
            assert any(
                option.startswith("-") and not option.startswith("--") for option in action.option_strings
            ), action.dest


def test_dry_run_routes_without_writing(tmp_path, capsys) -> None:
    result = main(["run", "-u", "123", "-d", str(tmp_path / "out"), "-a", str(tmp_path / "archive.db"), "-n"])
    assert result == 0
    assert '"gallery-dl"' in capsys.readouterr().out
    assert not (tmp_path / "archive.db").exists()


def test_repair_loose_defaults_to_dry_run_and_supports_explicit_mode(tmp_path, capsys) -> None:
    assert main(["repair-loose", "-d", str(tmp_path), "-N"]) == 0
    assert "DRY-RUN: 0 files across 0 galleries" in capsys.readouterr().out

    args = build_parser().parse_args(["repair-loose", "-d", str(tmp_path), "-n"])
    assert args.dry_run


def test_inspect_reports_hdporncomics_manhwa_classification(capsys) -> None:
    assert main(["inspect", "-u", "https://hdporncomics.com/manhwa/title/", "-j"]) == 0
    output = capsys.readouterr().out
    assert '"backend": "hdporncomics"' in output
    assert '"classification": "manhwa"' in output
