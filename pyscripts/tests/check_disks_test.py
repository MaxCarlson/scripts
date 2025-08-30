import argparse
import json
import platform
import subprocess
from unittest.mock import patch, MagicMock

import pytest

# Import the module named after your file 'check_disks.py'
import check_disks

# --- Mock Data ---

MOCK_DF_OUTPUT = """Filesystem     1024-blocks      Used Available Capacity Mounted on
/dev/block/dm-4      7648536   7635028     13508     100% /
tmpfs                5242880      2600   5240280       1% /dev
/dev/fuse           109994340  96784332  13210008      89% /storage/emulated
/dev/block/dm-5      2048000   2048000         0     100% /vendor
"""

MOCK_POWERSHELL_MULTIPLE_DRIVES = json.dumps([
    {"Name": "C", "Total": 274344443904, "Used": 161061273600, "Free": 113283170304},
    {"Name": "D", "Total": 1000204886016, "Used": 500102443008, "Free": 500102443008}
])

MOCK_POWERSHELL_SINGLE_DRIVE = json.dumps(
    {"Name": "C", "Total": 274344443904, "Used": 161061273600, "Free": 113283170304}
)

# --- Test Cases ---

class TestArgs:
    """Tests for argument parsing."""
    def test_parse_args_default(self):
        """Should default to non-concise mode."""
        args = check_disks.parse_args([])
        assert not args.concise

    def test_parse_args_concise_short(self):
        """Should set concise to True with -c."""
        args = check_disks.parse_args(['-c'])
        assert args.concise

    def test_parse_args_concise_long(self):
        """Should set concise to True with --concise."""
        args = check_disks.parse_args(['--concise'])
        assert args.concise

class TestFormatBytes:
    """Tests for the format_bytes utility function."""
    @pytest.mark.parametrize("value, expected", [
        (0, "0 B"),
        (512, "512 B"),
        (1024, "1 KB"),
        (1536, "1.5 KB"),
        (1024 * 1024 * 5, "5 MB"),
        (1024 * 1024 * 1024 * 2.5, "2.5 GB"),
        (1024 * 1024 * 1024 * 1024 * 3.7, "3.7 TB"),
        (None, "N/A"),
        ("not a number", "N/A"),
        (-100, "N/A"),
    ])
    def test_formatting(self, value, expected):
        assert check_disks.format_bytes(value) == expected

class TestPrintTable:
    """Tests for the print_table utility function."""
    def test_print_table_output(self, capsys):
        """Should format headers and data correctly."""
        headers = ["Name", "Size"]
        data = [["FileA", "10 KB"], ["FileB", "5 MB"]]
        check_disks.print_table(headers, data)
        captured = capsys.readouterr()
        # Corrected expected output based on actual column width calculation
        expected_output = (
            "Name  | Size \n"
            "------|------\n" # FIX: Corrected the separator line
            "FileA | 10 KB\n"
            "FileB | 5 MB \n"
        )
        assert captured.out == expected_output

    def test_print_table_no_data(self, capsys):
        """Should handle empty data gracefully."""
        check_disks.print_table(["Header"], [])
        captured = capsys.readouterr()
        assert "No data to display." in captured.out

@patch('subprocess.run')
class TestCheckDiskUsageNix:
    """Tests for the Unix-like OS disk usage function."""
    def test_nix_verbose_mode(self, mock_run, capsys):
        """Should print all filesystems in verbose mode."""
        mock_run.return_value = MagicMock(
            stdout=MOCK_DF_OUTPUT, stderr="", returncode=0, check_returncode=lambda: None
        )
        # FIX: Changed to correct function name
        check_disks.check_disk_usage_nix(concise=False)
        captured = capsys.readouterr()
        
        assert "Detected Unix-like OS" in captured.out
        assert "/dev/block/dm-4" in captured.out
        assert "/storage/emulated" in captured.out
        assert "/vendor" in captured.out
        assert mock_run.call_args[0][0] == ["df", "-kP"]

    def test_nix_concise_mode(self, mock_run, capsys):
        """Should print only relevant filesystems in concise mode."""
        mock_run.return_value = MagicMock(stdout=MOCK_DF_OUTPUT, stderr="")
        # FIX: Changed to correct function name
        check_disks.check_disk_usage_nix(concise=True)
        captured = capsys.readouterr()
        
        assert "/dev/block/dm-4" in captured.out
        assert "/storage/emulated" in captured.out
        assert "/vendor" not in captured.out

    def test_nix_df_not_found(self, mock_run, capsys):
        """Should handle FileNotFoundError."""
        mock_run.side_effect = FileNotFoundError
        # FIX: Changed to correct function name
        check_disks.check_disk_usage_nix()
        captured = capsys.readouterr()
        assert "Error: 'df' command not found" in captured.err

    def test_nix_df_command_error(self, mock_run, capsys):
        """Should handle CalledProcessError."""
        mock_run.side_effect = subprocess.CalledProcessError(1, "df", stderr="Permission denied")
        # FIX: Changed to correct function name
        check_disks.check_disk_usage_nix()
        captured = capsys.readouterr()
        assert "Error executing 'df' command" in captured.err
        assert "Permission denied" in captured.err

    def test_nix_parsing_error(self, mock_run, capsys):
        """Should handle malformed df output."""
        mock_run.return_value = MagicMock(stdout="malformed output line", stderr="")
        # FIX: Changed to correct function name
        check_disks.check_disk_usage_nix()
        captured = capsys.readouterr()
        assert "Error parsing 'df' output" in captured.err

@patch('subprocess.run')
class TestCheckDiskUsageWindows:
    """Tests for the Windows disk usage function."""
    def test_windows_multiple_drives(self, mock_run, capsys):
        """Should correctly parse and display multiple drives."""
        mock_run.return_value = MagicMock(stdout=MOCK_POWERSHELL_MULTIPLE_DRIVES, stderr="")
        # FIX: Changed to correct function name
        check_disks.check_disk_usage_windows()
        captured = capsys.readouterr()
        
        assert "Detected Windows" in captured.out
        assert "255.5 GB" in captured.out
        assert "149.9 GB" in captured.out
        assert "931.3 GB" in captured.out
        assert "58%" in captured.out
        assert "50%" in captured.out

    def test_windows_single_drive(self, mock_run, capsys):
        """Should correctly handle single drive JSON object output."""
        mock_run.return_value = MagicMock(stdout=MOCK_POWERSHELL_SINGLE_DRIVE, stderr="")
        # FIX: Changed to correct function name
        check_disks.check_disk_usage_windows()
        captured = capsys.readouterr()
        assert "255.5 GB" in captured.out
        assert "149.9 GB" in captured.out
        assert "58%" in captured.out

    def test_windows_powershell_not_found(self, mock_run, capsys):
        """Should handle FileNotFoundError for powershell."""
        mock_run.side_effect = FileNotFoundError
        # FIX: Changed to correct function name
        check_disks.check_disk_usage_windows()
        captured = capsys.readouterr()
        assert "Error: 'powershell' command not found" in captured.err

    def test_windows_command_error(self, mock_run, capsys):
        """Should handle CalledProcessError from powershell."""
        mock_run.side_effect = subprocess.CalledProcessError(1, "powershell", stderr="Cmdlet not found")
        # FIX: Changed to correct function name
        check_disks.check_disk_usage_windows()
        captured = capsys.readouterr()
        assert "Error executing PowerShell command" in captured.err
        assert "Cmdlet not found" in captured.err

    def test_windows_json_decode_error(self, mock_run, capsys):
        """Should handle malformed JSON from powershell."""
        mock_run.return_value = MagicMock(stdout="<not_json>", stderr="")
        # FIX: Changed to correct function name
        check_disks.check_disk_usage_windows()
        captured = capsys.readouterr()
        assert "Error parsing JSON from PowerShell output" in captured.err

# FIX: Corrected patch targets to match actual function names
@patch('check_disks.parse_args')
@patch('check_disks.check_disk_usage_nix')
@patch('check_disks.check_disk_usage_windows')
@patch('platform.system')
class TestMainFunction:
    """Tests for the main function's OS routing."""
    def test_main_on_windows(self, mock_system, mock_win_func, mock_nix_func, mock_args):
        """Should call windows function on Windows."""
        mock_system.return_value = "Windows"
        mock_args.return_value = argparse.Namespace(concise=False)
        check_disks.main()
        mock_win_func.assert_called_once()
        mock_nix_func.assert_not_called()

    def test_main_on_linux(self, mock_system, mock_win_func, mock_nix_func, mock_args):
        """Should call nix function on Linux."""
        mock_system.return_value = "Linux"
        mock_args.return_value = argparse.Namespace(concise=True)
        check_disks.main()
        mock_win_func.assert_not_called()
        mock_nix_func.assert_called_once_with(concise=True)

    def test_main_on_darwin(self, mock_system, mock_win_func, mock_nix_func, mock_args):
        """Should call nix function on macOS (Darwin)."""
        mock_system.return_value = "Darwin"
        mock_args.return_value = argparse.Namespace(concise=False)
        check_disks.main()
        mock_win_func.assert_not_called()
        mock_nix_func.assert_called_once_with(concise=False)

    def test_main_on_unsupported_os(self, mock_system, mock_win_func, mock_nix_func, mock_args, capsys):
        """Should fall back to nix function on unsupported OS."""
        mock_system.return_value = "FreeBSD"
        mock_args.return_value = argparse.Namespace(concise=False)
        check_disks.main()
        captured = capsys.readouterr()
        assert "Unsupported OS: FreeBSD" in captured.err
        assert "fallback" in captured.err
        mock_win_func.assert_not_called()
        mock_nix_func.assert_called_once_with(concise=False)
