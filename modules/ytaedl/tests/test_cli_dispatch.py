"""Tests for ytaedl/cli.py top-level subcommand dispatcher."""

from __future__ import annotations

from unittest.mock import patch

from ytaedl.cli import main


class TestTopLevelHelp:
    def test_no_args_prints_help_and_returns_0(self, capsys):
        rc = main([])
        assert rc == 0
        out = capsys.readouterr().out
        assert "run" in out
        assert "worker" in out
        assert "cleanup" in out
        assert "urls" in out
        assert "archive" in out

    def test_help_flag_prints_help(self, capsys):
        rc = main(["--help"])
        assert rc == 0
        out = capsys.readouterr().out
        assert "subcommand" in out.lower() or "run" in out

    def test_short_help_flag(self, capsys):
        rc = main(["-h"])
        assert rc == 0

    def test_unknown_subcommand_returns_2(self, capsys):
        rc = main(["nonexistent"])
        assert rc == 2
        err = capsys.readouterr().err
        assert "nonexistent" in err


class TestSubcommandDispatch:
    def test_run_dispatches_to_run_main(self):
        with patch("ytaedl.manager.run_main", return_value=0) as mock_run:
            main(["run", "--help"])
        # run_main is called (even with --help, it's forwarded)
        mock_run.assert_called_once()

    def test_worker_dispatches_to_downloader_main(self):
        with patch("ytaedl.downloader.main", return_value=0) as mock_dl:
            main(["worker", "--help"])
        mock_dl.assert_called_once()

    def test_cleanup_dispatches_to_cleanup_main(self):
        with patch("ytaedl.cleanup_cli.main", return_value=0) as mock_cu:
            main(["cleanup"])
        mock_cu.assert_called_once_with([])

    def test_urls_dispatches_to_urlscan(self):
        with patch("ytaedl.urlscan.cli_main", return_value=0) as mock_urls:
            main(["urls", "--help"])
        mock_urls.assert_called_once_with(["--help"])

    def test_archive_dispatches_to_archive_builder(self):
        with patch("ytaedl.archive_builder.cli_main", return_value=0) as mock_arch:
            main(["archive", "--help"])
        mock_arch.assert_called_once_with(["--help"])

    def test_archive_validate_dispatches_through_archive_builder(self):
        with patch("ytaedl.archive_builder.cli_main", return_value=0) as mock_arch:
            main(["archive", "validate", "--no-ui"])
        mock_arch.assert_called_once_with(["validate", "--no-ui"])

    def test_remaining_args_forwarded_to_subcommand(self):
        with patch("ytaedl.cleanup_cli.main", return_value=0) as mock_cu:
            main(["cleanup", "partial", "-P", "B:/stars/", "--dry-run"])
        mock_cu.assert_called_once_with(["partial", "-P", "B:/stars/", "--dry-run"])

    def test_return_code_propagated(self):
        with patch("ytaedl.cleanup_cli.main", return_value=42):
            rc = main(["cleanup"])
        assert rc == 42
