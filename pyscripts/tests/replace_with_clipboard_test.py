import sys
import pytest
from pathlib import Path
from unittest import mock
import re # For ANSI code stripping

# Mock clipboard_utils BEFORE importing the script under test
mock_clipboard_utils_rwc_module = mock.MagicMock()
sys.modules['cross_platform.clipboard_utils'] = mock_clipboard_utils_rwc_module

import replace_with_clipboard # Import the script to be tested

# --- Helper Functions for Assertions ---
ANSI_ESCAPE_REGEX = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')

def strip_ansi_codes(s: str) -> str:
    return ANSI_ESCAPE_REGEX.sub('', s)

def normalize_for_assertion(raw_text: str) -> str:
    """Strips ANSI codes, replaces newlines with spaces, and collapses multiple spaces."""
    cleaned_from_ansi = strip_ansi_codes(raw_text)
    s = cleaned_from_ansi.replace('\n', ' ')
    return " ".join(s.split()).strip()

def assert_message_in_output(
    raw_captured_out: str, 
    text_before_path: str, 
    path_obj: Path,
    text_after_path: str
):
    """
    Asserts that a message (composed of text_before_path, a representation of path_obj, 
    and text_after_path) is present in the normalized version of raw_captured_out.
    Handles Rich Console's path wrapping by comparing space-collapsed path strings.
    """
    normalized_out = normalize_for_assertion(raw_captured_out)
    
    # Find text_before_path
    idx_before = normalized_out.find(text_before_path)
    assert idx_before != -1, \
        f"'{text_before_path}' not found in normalized output: '{normalized_out}'"
    
    path_start_index_in_norm = idx_before + len(text_before_path)

    # Find text_after_path, starting search *after* where text_before_path ended
    idx_text_after = normalized_out.find(text_after_path, path_start_index_in_norm)
    assert idx_text_after != -1, \
        f"'{text_after_path}' not found after '{text_before_path}' (from index {path_start_index_in_norm}) in normalized output: '{normalized_out}'"

    # Extract the path string as it appears in the normalized output
    path_as_printed_and_normalized = normalized_out[path_start_index_in_norm : idx_text_after]

    original_path_str = str(path_obj)

    # Compare the space-collapsed versions.
    # This handles cases where Rich wrapped str(path_obj) with newlines,
    # and normalize_for_assertion turned those newlines into spaces within the path's representation.
    expected_path_collapsed = original_path_str.replace(" ", "")
    actual_path_collapsed = path_as_printed_and_normalized.replace(" ", "")

    assert actual_path_collapsed == expected_path_collapsed, \
        f"Path mismatch after collapsing spaces.\n" \
        f"  Expected (original path, collapsed): '{expected_path_collapsed}'\n" \
        f"  Got (from output, collapsed): '{actual_path_collapsed}'\n" \
        f"  Path as printed & normalized in output: '{path_as_printed_and_normalized}'\n" \
        f"  Original path str from Path object: '{original_path_str}'\n" \
        f"  Full normalized output for context: '{normalized_out}'"

# --- Fixtures ---
@pytest.fixture
def mock_get_clipboard_rwc(monkeypatch):
    mock_get = mock.Mock()
    monkeypatch.setattr(replace_with_clipboard, 'get_clipboard', mock_get)
    return mock_get

@pytest.fixture
def rwc_runner(monkeypatch): 
    def run(args_list):
        full_argv = ["replace_with_clipboard.py"] + args_list
        monkeypatch.setattr(sys, "argv", full_argv)
        args = replace_with_clipboard.parser.parse_args(args_list) 
        replace_with_clipboard.replace_or_print_clipboard(args.file, args.no_stats)
    return run

# --- Test Cases ---
def test_print_to_stdout_no_args(mock_get_clipboard_rwc, capsys, rwc_runner, monkeypatch):
    mock_get_clipboard_rwc.return_value = "hello from clipboard"
    mock_stdout_write = mock.Mock()
    monkeypatch.setattr(sys.stdout, 'write', mock_stdout_write)

    with pytest.raises(SystemExit) as e:
         rwc_runner(["--no-stats"])
    assert e.value.code == 0
    mock_stdout_write.assert_called_once_with("hello from clipboard")
    
    captured_stderr_raw = capsys.readouterr().err
    normalized_stderr = normalize_for_assertion(captured_stderr_raw)
    assert "replace_with_clipboard.py Statistics" not in normalized_stderr

def test_replace_new_file(mock_get_clipboard_rwc, tmp_path, capsys, rwc_runner):
    mock_get_clipboard_rwc.return_value = "new file content"
    test_file = tmp_path / "test_new.txt" 

    with pytest.raises(SystemExit) as e:
        rwc_runner([str(test_file), "--no-stats"])
    assert e.value.code == 0
    assert test_file.read_text() == "new file content\n"
    
    raw_captured_out = capsys.readouterr().out
    assert_message_in_output(raw_captured_out, "File '", test_file, "' does not exist. Creating new file.")
    assert_message_in_output(raw_captured_out, "Replaced contents of '", test_file, "' with clipboard data.")
    
    normalized_out = normalize_for_assertion(raw_captured_out)
    assert "replace_with_clipboard.py Statistics" not in normalized_out
    
    raw_captured_err = capsys.readouterr().err 
    normalized_err = normalize_for_assertion(raw_captured_err)
    assert "replace_with_clipboard.py Statistics" not in normalized_err

def test_replace_overwrites_existing_file(mock_get_clipboard_rwc, tmp_path, capsys, rwc_runner):
    mock_get_clipboard_rwc.return_value = "overwritten content"
    test_file = tmp_path / "existing_test.txt"
    test_file.write_text("original content") 

    with pytest.raises(SystemExit) as e:
        rwc_runner([str(test_file), "--no-stats"])
    assert e.value.code == 0
    assert test_file.read_text() == "overwritten content\n"
    
    raw_captured_out = capsys.readouterr().out
    normalized_out_for_substring_check = normalize_for_assertion(raw_captured_out)
    assert "does not exist. Creating new file." not in normalized_out_for_substring_check
    
    assert_message_in_output(raw_captured_out, "Replaced contents of '", test_file, "' with clipboard data.")
    
    assert "replace_with_clipboard.py Statistics" not in normalized_out_for_substring_check

def test_clipboard_empty_aborts_file_mode(mock_get_clipboard_rwc, tmp_path, capsys, rwc_runner):
    mock_get_clipboard_rwc.return_value = "" 
    test_file = tmp_path / "test_empty_cb.txt"
    with pytest.raises(SystemExit) as e:
        rwc_runner([str(test_file), "--no-stats"])
    assert e.value.code == 1
    
    raw_captured_stderr = capsys.readouterr().err
    normalized_stderr = normalize_for_assertion(raw_captured_stderr)
    assert "Clipboard is empty. Aborting." in normalized_stderr
    assert not test_file.exists() 

def test_clipboard_empty_aborts_stdout_mode(mock_get_clipboard_rwc, capsys, rwc_runner, monkeypatch):
    mock_get_clipboard_rwc.return_value = ""
    mock_stdout_write = mock.Mock()
    monkeypatch.setattr(sys.stdout, 'write', mock_stdout_write)
    with pytest.raises(SystemExit) as e:
        rwc_runner(["--no-stats"]) 
    assert e.value.code == 1
    mock_stdout_write.assert_not_called()

    raw_captured_stderr = capsys.readouterr().err
    normalized_stderr = normalize_for_assertion(raw_captured_stderr)
    assert "Clipboard is empty. Aborting." in normalized_stderr

def test_stats_output_file_mode(mock_get_clipboard_rwc, tmp_path, capsys, rwc_runner):
    mock_get_clipboard_rwc.return_value = "content for stats"
    test_file = tmp_path / "stats_file.txt"
    with pytest.raises(SystemExit) as e:
        rwc_runner([str(test_file)]) 
    assert e.value.code == 0
    
    raw_captured_out = capsys.readouterr().out
    normalized_out = normalize_for_assertion(raw_captured_out)
    assert "replace_with_clipboard.py Statistics" in normalized_out
    assert "File Action" in normalized_out 
    assert "Created new file" in normalized_out 

def test_stats_output_stdout_mode(mock_get_clipboard_rwc, capsys, rwc_runner, monkeypatch):
    mock_get_clipboard_rwc.return_value = "content for stats print"
    mock_stdout_write = mock.Mock() 
    monkeypatch.setattr(sys.stdout, 'write', mock_stdout_write)

    with pytest.raises(SystemExit) as e:
        rwc_runner([]) 
    assert e.value.code == 0
    
    mock_stdout_write.assert_called_once_with("content for stats print")
    raw_captured_stderr = capsys.readouterr().err
    normalized_stderr = normalize_for_assertion(raw_captured_stderr)
    assert "replace_with_clipboard.py Statistics" in normalized_stderr
    assert "Operation Mode" in normalized_stderr 
    assert "Print to stdout" in normalized_stderr
