# tests/replace_with_clipboard_test.py
import sys
import pytest
from pathlib import Path
from unittest import mock

mock_clipboard_utils_rwc = mock.MagicMock()
sys.modules['cross_platform.clipboard_utils'] = mock_clipboard_utils_rwc

import replace_with_clipboard

@pytest.fixture
def mock_get_clipboard_rwc(monkeypatch):
    mock_get = mock.Mock()
    monkeypatch.setattr(replace_with_clipboard, 'get_clipboard', mock_get)
    return mock_get

@pytest.fixture
def rwc_runner(monkeypatch): # Runner for replace_with_clipboard.py
    def run(args_list):
        full_argv = ["replace_with_clipboard.py"] + args_list
        monkeypatch.setattr(sys, "argv", full_argv)
        args = replace_with_clipboard.parser.parse_args(args_list) 
        replace_with_clipboard.replace_or_print_clipboard(args.file, args.no_stats)
    return run

def test_print_to_stdout_no_args(mock_get_clipboard_rwc, capsys, rwc_runner, monkeypatch):
    mock_get_clipboard_rwc.return_value = "hello from clipboard"
    mock_stdout_write = mock.Mock()
    monkeypatch.setattr(sys.stdout, 'write', mock_stdout_write)

    with pytest.raises(SystemExit) as e:
         rwc_runner(["--no-stats"]) # Pass --no-stats
    assert e.value.code == 0
    mock_stdout_write.assert_called_once_with("hello from clipboard")
    captured_stderr = capsys.readouterr().err
    assert "replace_with_clipboard.py Statistics" not in captured_stderr

def test_replace_file_with_arg(mock_get_clipboard_rwc, tmp_path, capsys, rwc_runner):
    mock_get_clipboard_rwc.return_value = "new file content"
    test_file = tmp_path / "test.txt"

    with pytest.raises(SystemExit) as e:
        rwc_runner([str(test_file), "--no-stats"]) # Pass --no-stats
    assert e.value.code == 0
    assert test_file.read_text() == "new file content\n"
    captured_out = capsys.readouterr().out # User messages go to stdout
    normalized_out = " ".join(captured_out.split())
    assert f"Replaced contents of '{str(test_file)}' with clipboard data." in normalized_out
    assert "replace_with_clipboard.py Statistics" not in captured_out

def test_clipboard_empty_aborts_file_mode(mock_get_clipboard_rwc, tmp_path, capsys, rwc_runner):
    mock_get_clipboard_rwc.return_value = "" 
    test_file = tmp_path / "test.txt"
    with pytest.raises(SystemExit) as e:
        rwc_runner([str(test_file), "--no-stats"])
    assert e.value.code == 1
    captured_stderr = capsys.readouterr().err
    assert "Clipboard is empty. Aborting." in captured_stderr

def test_clipboard_empty_aborts_stdout_mode(mock_get_clipboard_rwc, capsys, rwc_runner, monkeypatch):
    mock_get_clipboard_rwc.return_value = ""
    mock_stdout_write = mock.Mock()
    monkeypatch.setattr(sys.stdout, 'write', mock_stdout_write)
    with pytest.raises(SystemExit) as e:
        rwc_runner(["--no-stats"])
    assert e.value.code == 1
    mock_stdout_write.assert_not_called()
    captured_stderr = capsys.readouterr().err
    assert "Clipboard is empty. Aborting." in captured_stderr

def test_replace_creates_new_file_if_not_exists(mock_get_clipboard_rwc, tmp_path, capsys, rwc_runner):
    mock_get_clipboard_rwc.return_value = "content for new file"
    test_file = tmp_path / "newly_created.txt"
    assert not test_file.exists()
    with pytest.raises(SystemExit) as e:
        rwc_runner([str(test_file), "--no-stats"])
    assert e.value.code == 0
    assert test_file.exists()
    assert test_file.read_text() == "content for new file\n"
    captured_out = capsys.readouterr().out
    normalized_out = " ".join(captured_out.split())
    assert f"File '{str(test_file)}' does not exist. Creating new file." in normalized_out
    assert "Replaced contents of" in normalized_out
