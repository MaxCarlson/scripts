import argparse
import json

import pytest

from mangadl.backends import GalleryDlBackend
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


def test_run_parser_defaults_to_safe_worker_ceiling_and_stagger(tmp_path) -> None:
    args = build_parser().parse_args(
        [
            "run",
            "-u",
            "https://manga18fx.com/manga/example/",
            "-d",
            str(tmp_path / "out"),
            "-a",
            str(tmp_path / "archive.db"),
        ]
    )

    assert args.workers == 2
    assert args.max_workers == 4
    assert args.worker_start_delay == 2.0
    assert args.image_workers == 4


def test_dry_run_routes_without_writing(tmp_path, capsys, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        GalleryDlBackend,
        "score",
        lambda self, url: 100 if url == "https://nhentai.net/g/123/" else 0,
    )

    result = main(["run", "-u", "123", "-d", str(tmp_path / "out"), "-a", str(tmp_path / "archive.db"), "-n"])

    assert result == 0
    assert '"gallery-dl"' in capsys.readouterr().out
    assert not (tmp_path / "archive.db").exists()


def test_auto_tune_dry_run_reports_explicit_bounds(
    tmp_path,
    capsys,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("MANGADL_MAX_OUTER_WORKERS", raising=False)
    result = main(
        [
            "run",
            "-u",
            "https://manga18fx.com/manga/one/",
            "-u",
            "https://manga18fx.com/manga/two/",
            "-u",
            "https://manga18fx.com/manga/three/",
            "-u",
            "https://manga18fx.com/manga/four/",
            "-d",
            str(tmp_path / "out"),
            "-a",
            str(tmp_path / "archive.db"),
            "-T",
            "-W",
            "2:4",
            "-Y",
            "2:5",
            "-U",
            "1.5",
            "-n",
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    assert result == 0
    assert payload["max_workers"] == 4
    assert payload["worker_start_delay"] == 1.5
    assert payload["auto_tune"]["worker_range"] == {"minimum": 2, "maximum": 4}
    assert payload["auto_tune"]["image_worker_range"] == {"minimum": 2, "maximum": 5}


def test_auto_tune_range_cannot_exceed_configured_ceiling(tmp_path) -> None:
    with pytest.raises(SystemExit) as exc_info:
        main(
            [
                "run",
                "-u",
                "https://manga18fx.com/manga/example/",
                "-d",
                str(tmp_path / "out"),
                "-a",
                str(tmp_path / "archive.db"),
                "-T",
                "-W",
                "1:5",
                "-n",
            ]
        )

    assert exc_info.value.code == 2


def test_explicit_max_workers_override_allows_experimental_bound(tmp_path, capsys) -> None:
    result = main(
        [
            "run",
            "-u",
            "https://manga18fx.com/manga/example/",
            "-d",
            str(tmp_path / "out"),
            "-a",
            str(tmp_path / "archive.db"),
            "-m",
            "5",
            "-w",
            "5",
            "-n",
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    assert result == 0
    assert payload["requested_workers"] == 5
    assert payload["max_workers"] == 5


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


def test_inspect_reports_manga18fx_manhwa_classification(capsys) -> None:
    assert main(["inspect", "-u", "https://manga18fx.com/manga/title/", "-j"]) == 0
    output = capsys.readouterr().out
    assert '"backend": "manga18fx"' in output
    assert '"classification": "manhwa"' in output
