"""Help output should identify the ytaedl version on every CLI surface."""

from __future__ import annotations

import pytest

import ytaedl
from ytaedl import archive_builder, cleanup_cli, cli, downloader, manager, urlscan
from ytaedl._cli_help import make_profile_parser


def _assert_version(text: str) -> None:
    assert f"ytaedl {ytaedl.__version__}" in text


def test_top_level_help_prints_version(capsys):
    assert cli.main(["-h"]) == 0
    _assert_version(capsys.readouterr().out)


def test_run_help_prints_version(capsys):
    with pytest.raises(SystemExit) as exc:
        manager.make_parser().parse_args(["-h"])
    assert exc.value.code == 0
    _assert_version(capsys.readouterr().out)


@pytest.mark.parametrize("profile", ["watcher", "grid", "webview", "disable"])
def test_run_profile_help_prints_version(profile, capsys):
    make_profile_parser(profile).print_help()
    _assert_version(capsys.readouterr().out)


def test_worker_help_prints_version(capsys):
    with pytest.raises(SystemExit) as exc:
        downloader.make_parser().parse_args(["-h"])
    assert exc.value.code == 0
    _assert_version(capsys.readouterr().out)


def test_cleanup_partial_help_prints_version(capsys):
    with pytest.raises(SystemExit) as exc:
        cleanup_cli.main(["partial", "-h"])
    assert exc.value.code == 0
    _assert_version(capsys.readouterr().out)


def test_cleanup_index_help_prints_version(capsys):
    with pytest.raises(SystemExit) as exc:
        cleanup_cli.main(["index", "-h"])
    assert exc.value.code == 0
    _assert_version(capsys.readouterr().out)


def test_urls_help_prints_version(capsys):
    with pytest.raises(SystemExit) as exc:
        urlscan.build_parser().parse_args(["-h"])
    assert exc.value.code == 0
    _assert_version(capsys.readouterr().out)


def test_archive_help_prints_version(capsys):
    with pytest.raises(SystemExit) as exc:
        archive_builder.build_parser().parse_args(["-h"])
    assert exc.value.code == 0
    _assert_version(capsys.readouterr().out)
