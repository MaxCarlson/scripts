"""Tests for rrbackup.cli module."""
from __future__ import annotations

import argparse
import sys

import pytest

from rrbackup.cli import build_parser, main


@pytest.mark.unit
class TestBuildParser:
    """Tests for build_parser function."""

    def test_parser_created(self):
        """Test parser is created successfully."""
        parser = build_parser()

        assert isinstance(parser, argparse.ArgumentParser)
        assert parser.prog == "rrb"

    def test_version_flag(self):
        """Test --version flag."""
        parser = build_parser()

        with pytest.raises(SystemExit) as exc_info:
            parser.parse_args(["--version"])

        assert exc_info.value.code == 0

    def test_version_short_flag(self):
        """Test -V short flag."""
        parser = build_parser()

        with pytest.raises(SystemExit):
            parser.parse_args(["-V"])

    def test_config_flag(self):
        """Test --config flag."""
        parser = build_parser()
        args = parser.parse_args(["--config", "/tmp/config.toml", "list"])

        assert args.config == "/tmp/config.toml"

    def test_config_short_flag(self):
        """Test -c short flag."""
        parser = build_parser()
        args = parser.parse_args(["-c", "/tmp/test.toml", "list"])

        assert args.config == "/tmp/test.toml"

    def test_verbose_flag(self):
        """Test --verbose flag."""
        parser = build_parser()
        args = parser.parse_args(["--verbose", "list"])

        assert args.verbose is True

    def test_verbose_short_flag(self):
        """Test -v short flag."""
        parser = build_parser()
        args = parser.parse_args(["-v", "list"])

        assert args.verbose is True


@pytest.mark.unit
class TestSetupCommand:
    """Tests for setup command."""

    def test_setup_command_parsed(self):
        """Test setup command is recognized."""
        parser = build_parser()
        args = parser.parse_args(["setup"])

        assert args.cmd == "setup"
        assert hasattr(args, "func")

    def test_setup_password_file_flag(self):
        """Test setup --password-file flag."""
        parser = build_parser()
        args = parser.parse_args(["setup", "--password-file", "/tmp/pwd.txt"])

        assert args.password_file == "/tmp/pwd.txt"

    def test_setup_password_file_short_flag(self):
        """Test setup -p short flag."""
        parser = build_parser()
        args = parser.parse_args(["setup", "-p", "/tmp/pwd.txt"])

        assert args.password_file == "/tmp/pwd.txt"

    def test_setup_remote_check_flag(self):
        """Test setup --remote-check flag."""
        parser = build_parser()
        args = parser.parse_args(["setup", "--remote-check"])

        assert args.remote_check is True

    def test_setup_remote_check_short_flag(self):
        """Test setup -r short flag."""
        parser = build_parser()
        args = parser.parse_args(["setup", "-r"])

        assert args.remote_check is True

    def test_setup_wizard_flag(self):
        """Test setup --wizard flag."""
        parser = build_parser()
        args = parser.parse_args(["setup", "--wizard"])

        assert args.wizard is True

    def test_setup_wizard_short_flag(self):
        """Test setup -w short flag."""
        parser = build_parser()
        args = parser.parse_args(["setup", "-w"])

        assert args.wizard is True


@pytest.mark.unit
class TestListCommand:
    """Tests for list command."""

    def test_list_command_parsed(self):
        """Test list command is recognized."""
        parser = build_parser()
        args = parser.parse_args(["list"])

        assert args.cmd == "list"

    def test_list_path_filter(self):
        """Test list --path filter."""
        parser = build_parser()
        args = parser.parse_args(["list", "--path", "/home/docs"])

        assert args.path == ["/home/docs"]

    def test_list_path_short_flag(self):
        """Test list -P short flag."""
        parser = build_parser()
        args = parser.parse_args(["list", "-P", "/data"])

        assert args.path == ["/data"]

    def test_list_path_multiple(self):
        """Test multiple --path filters."""
        parser = build_parser()
        args = parser.parse_args(["list", "-P", "/home", "-P", "/data"])

        assert args.path == ["/home", "/data"]

    def test_list_tag_filter(self):
        """Test list --tag filter."""
        parser = build_parser()
        args = parser.parse_args(["list", "--tag", "important"])

        assert args.tag == ["important"]

    def test_list_tag_short_flag(self):
        """Test list -t short flag."""
        parser = build_parser()
        args = parser.parse_args(["list", "-t", "daily"])

        assert args.tag == ["daily"]

    def test_list_host_filter(self):
        """Test list --host filter."""
        parser = build_parser()
        args = parser.parse_args(["list", "--host", "laptop"])

        assert args.host == "laptop"

    def test_list_host_short_flag(self):
        """Test list -H short flag."""
        parser = build_parser()
        args = parser.parse_args(["list", "-H", "desktop"])

        assert args.host == "desktop"


@pytest.mark.unit
class TestBackupCommand:
    """Tests for backup command."""

    def test_backup_requires_set(self):
        """Test backup command requires --set argument."""
        parser = build_parser()

        with pytest.raises(SystemExit):
            parser.parse_args(["backup"])

    def test_backup_set_flag(self):
        """Test backup --set flag."""
        parser = build_parser()
        args = parser.parse_args(["backup", "--set", "documents"])

        assert args.set == "documents"

    def test_backup_set_short_flag(self):
        """Test backup -s short flag."""
        parser = build_parser()
        args = parser.parse_args(["backup", "-s", "photos"])

        assert args.set == "photos"

    def test_backup_dry_run_flag(self):
        """Test backup --dry-run flag."""
        parser = build_parser()
        args = parser.parse_args(["backup", "-s", "docs", "--dry-run"])

        assert args.dry_run is True

    def test_backup_dry_run_short_flag(self):
        """Test backup -n short flag."""
        parser = build_parser()
        args = parser.parse_args(["backup", "-s", "docs", "-n"])

        assert args.dry_run is True

    def test_backup_extra_tags(self):
        """Test backup --tag for extra tags."""
        parser = build_parser()
        args = parser.parse_args(["backup", "-s", "docs", "-t", "pre-upgrade"])

        assert args.tag == ["pre-upgrade"]

    def test_backup_extra_excludes(self):
        """Test backup --exclude for extra exclusions."""
        parser = build_parser()
        args = parser.parse_args(["backup", "-s", "docs", "-e", "*.tmp", "-e", "*.log"])

        assert args.exclude == ["*.tmp", "*.log"]

    def test_backup_extra_args(self):
        """Test backup --extra for raw restic args."""
        parser = build_parser()
        args = parser.parse_args(["backup", "-s", "docs", "-x", "--verbose"])

        assert args.extra == ["--verbose"]


@pytest.mark.unit
class TestStatsCommand:
    """Tests for stats command."""

    def test_stats_command_parsed(self):
        """Test stats command is recognized."""
        parser = build_parser()
        args = parser.parse_args(["stats"])

        assert args.cmd == "stats"


@pytest.mark.unit
class TestCheckCommand:
    """Tests for check command."""

    def test_check_command_parsed(self):
        """Test check command is recognized."""
        parser = build_parser()
        args = parser.parse_args(["check"])

        assert args.cmd == "check"


@pytest.mark.unit
class TestPruneCommand:
    """Tests for prune command."""

    def test_prune_command_parsed(self):
        """Test prune command is recognized."""
        parser = build_parser()
        args = parser.parse_args(["prune"])

        assert args.cmd == "prune"


@pytest.mark.unit
class TestProgressCommand:
    """Tests for progress command."""

    def test_progress_command_parsed(self):
        """Test progress command is recognized."""
        parser = build_parser()
        args = parser.parse_args(["progress"])

        assert args.cmd == "progress"


@pytest.mark.unit
class TestMainFunction:
    """Tests for main() function."""

    def test_main_with_no_args_shows_help(self, mocker):
        """Test main() with no arguments shows help."""
        mocker.patch("sys.argv", ["rrb"])

        with pytest.raises(SystemExit) as exc_info:
            main()

        # Should exit with error code (missing required subcommand)
        assert exc_info.value.code != 0

    def test_main_with_list_command(self, mocker, temp_dir, sample_config_dict):
        """Test main() executes list command."""
        import tomli_w

        config_file = temp_dir / "test.toml"
        config_file.write_text(tomli_w.dumps(sample_config_dict), encoding="utf-8")

        # Mock subprocess
        mock_proc = mocker.MagicMock()
        mock_proc.stdout.readline = mocker.MagicMock(return_value=b"")
        mock_proc.wait = mocker.MagicMock(return_value=0)
        mocker.patch("subprocess.Popen", return_value=mock_proc)

        mock_file = mocker.mock_open()
        mocker.patch("pathlib.Path.open", mock_file)
        mocker.patch("shutil.which", return_value="/usr/bin/restic")

        result = main(["-c", str(config_file), "list"])

        assert result == 0

    def test_main_returns_error_code_on_failure(self, mocker, temp_dir):
        """Test main() returns non-zero on error."""
        missing_config = temp_dir / "missing.toml"

        result = main(["-c", str(missing_config), "list"])

        assert result != 0


@pytest.mark.unit
class TestCLIErrorHandling:
    """Tests for CLI error handling."""

    def test_invalid_command_shows_error(self):
        """Test invalid command shows error."""
        parser = build_parser()

        with pytest.raises(SystemExit):
            parser.parse_args(["invalid-command"])

    def test_missing_required_argument_shows_error(self):
        """Test missing required argument shows error."""
        parser = build_parser()

        with pytest.raises(SystemExit):
            # backup requires --set
            parser.parse_args(["backup"])

    def test_config_not_found_returns_error(self, mocker):
        """Test config file not found returns error code."""
        result = main(["-c", "/nonexistent.toml", "list"])

        assert result != 0


@pytest.mark.unit
class TestAllCommandsHaveShortFlags:
    """Verify all arguments have short flags (coding standard)."""

    def test_global_flags_have_short_forms(self):
        """Test global flags have short forms."""
        parser = build_parser()

        # Test version
        parser.parse_args(["--version"])  # Will exit
        # Test that -V works (already tested above)

        # Test config
        args = parser.parse_args(["-c", "test.toml", "list"])
        assert args.config == "test.toml"

        # Test verbose
        args = parser.parse_args(["-v", "list"])
        assert args.verbose is True

    def test_setup_flags_have_short_forms(self):
        """Test setup command flags have short forms."""
        parser = build_parser()

        args = parser.parse_args(["setup", "-p", "/pwd.txt", "-r"])
        assert args.password_file == "/pwd.txt"
        assert args.remote_check is True

    def test_list_flags_have_short_forms(self):
        """Test list command flags have short forms."""
        parser = build_parser()

        args = parser.parse_args(["list", "-P", "/path", "-t", "tag", "-H", "host"])
        assert args.path == ["/path"]
        assert args.tag == ["tag"]
        assert args.host == "host"

    def test_backup_flags_have_short_forms(self):
        """Test backup command flags have short forms."""
        parser = build_parser()

        args = parser.parse_args(["backup", "-s", "docs", "-n", "-t", "tag", "-e", "*.tmp", "-x", "--verbose"])
        assert args.set == "docs"
        assert args.dry_run is True
        assert args.tag == ["tag"]
        assert args.exclude == ["*.tmp"]
        assert args.extra == ["--verbose"]


@pytest.mark.unit
class TestConfigSubcommands:
    """Tests for config management subcommands."""

    def test_config_init_command(self):
        """Test config init subcommand."""
        parser = build_parser()
        args = parser.parse_args(["config", "init"])

        assert args.cmd == "config"
        assert args.config_cmd == "init"

    def test_config_init_force_flag(self):
        """Test config init --force flag."""
        parser = build_parser()
        args = parser.parse_args(["config", "init", "-f"])

        assert args.force is True

    def test_config_wizard_command(self):
        """Test config wizard subcommand."""
        parser = build_parser()
        args = parser.parse_args(["config", "wizard"])

        assert args.config_cmd == "wizard"

    def test_config_wizard_initialize_repo_flag(self):
        """Test config wizard --initialize-repo flag."""
        parser = build_parser()
        args = parser.parse_args(["config", "wizard", "-i"])

        assert args.initialize_repo is True

    def test_config_show_command(self):
        """Test config show subcommand."""
        parser = build_parser()
        args = parser.parse_args(["config", "show"])

        assert args.config_cmd == "show"

    def test_config_show_effective_flag(self):
        """Test config show --effective flag."""
        parser = build_parser()
        args = parser.parse_args(["config", "show", "-e"])

        assert args.effective is True

    def test_config_list_sets_command(self):
        """Test config list-sets subcommand."""
        parser = build_parser()
        args = parser.parse_args(["config", "list-sets"])

        assert args.config_cmd == "list-sets"

    def test_config_add_set_command(self):
        """Test config add-set subcommand."""
        parser = build_parser()
        args = parser.parse_args([
            "config", "add-set",
            "-n", "photos",
            "-i", "/home/pics",
            "-i", "/data/photos",
            "-e", "*.tmp",
            "-t", "important",
            "-S", "daily 03:00",
            "-M", "50"
        ])

        assert args.config_cmd == "add-set"
        assert args.name == "photos"
        assert args.include == ["/home/pics", "/data/photos"]
        assert args.exclude == ["*.tmp"]
        assert args.tag == ["important"]
        assert args.schedule == "daily 03:00"
        assert args.max_snapshots == 50

    def test_config_remove_set_command(self):
        """Test config remove-set subcommand."""
        parser = build_parser()
        args = parser.parse_args(["config", "remove-set", "-n", "old-set"])

        assert args.config_cmd == "remove-set"
        assert args.name == "old-set"

    def test_config_set_command(self):
        """Test config set subcommand."""
        parser = build_parser()
        args = parser.parse_args([
            "config", "set",
            "-r", "/new/repo",
            "-P", "/new/pwd.txt",
            "-R", "/usr/local/bin/restic"
        ])

        assert args.config_cmd == "set"
        assert args.repo_url == "/new/repo"
        assert args.password_file == "/new/pwd.txt"
        assert args.restic_bin == "/usr/local/bin/restic"

    def test_config_retention_command(self):
        """Test config retention subcommand."""
        parser = build_parser()
        args = parser.parse_args([
            "config", "retention",
            "-L", "5",
            "-D", "7",
            "-W", "4",
            "-M", "12",
            "-Y", "10"
        ])

        assert args.config_cmd == "retention"
        assert args.keep_last == 5
        assert args.keep_daily == 7
        assert args.keep_weekly == 4
        assert args.keep_monthly == 12
        assert args.keep_yearly == 10

    def test_config_retention_use_defaults_flag(self):
        """Test config retention --use-defaults flag."""
        parser = build_parser()
        args = parser.parse_args(["config", "retention", "-u"])

        assert args.use_defaults is True

    def test_config_retention_clear_flag(self):
        """Test config retention --clear flag."""
        parser = build_parser()
        args = parser.parse_args(["config", "retention", "-X"])

        assert args.clear is True
