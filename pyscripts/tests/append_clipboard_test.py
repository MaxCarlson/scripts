import sys
import pytest
from pathlib import Path
from unittest import mock
import re # For ANSI code stripping

# Mock clipboard_utils BEFORE importing the script under test
mock_clipboard_utils_ac_module = mock.MagicMock()
sys.modules['cross_platform.clipboard_utils'] = mock_clipboard_utils_ac_module

import append_clipboard # Import the script to be tested

# --- Helper Functions for Assertions (copied from replace_with_clipboard_test.py for standalone use) ---
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
    
    idx_before = normalized_out.find(text_before_path)
    assert idx_before != -1, \
        f"'{text_before_path}' not found in normalized output: '{normalized_out}'"
    
    path_start_index_in_norm = idx_before + len(text_before_path)

    idx_text_after = normalized_out.find(text_after_path, path_start_index_in_norm)
    assert idx_text_after != -1, \
        f"'{text_after_path}' not found after '{text_before_path}' (from index {path_start_index_in_norm}) in normalized output: '{normalized_out}'"

    path_as_printed_and_normalized = normalized_out[path_start_index_in_norm : idx_text_after]
    original_path_str = str(path_obj)
    
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
def mock_get_clipboard_ac(monkeypatch): 
    mock_get = mock.Mock()
    monkeypatch.setattr(append_clipboard, 'get_clipboard', mock_get)
    return mock_get

@pytest.fixture
def ac_runner(monkeypatch): 
    def run(args_list):
        full_argv = ["append_clipboard.py"] + args_list
        monkeypatch.setattr(sys, "argv", full_argv)
        args = append_clipboard.parser.parse_args(args_list)
        append_clipboard.append_clipboard_to_file(args.file, args.no_stats)
    return run

# --- Test Cases ---
def test_append_to_existing_file(mock_get_clipboard_ac, tmp_path, capsys, ac_runner):
    mock_get_clipboard_ac.return_value = "appended content"
    test_file = tmp_path / "existing_append.txt"
    initial_content = "initial content"
    test_file.write_text(initial_content)

    with pytest.raises(SystemExit) as e:
        ac_runner([str(test_file), "--no-stats"])
    assert e.value.code == 0
    assert test_file.read_text() == f"{initial_content}\nappended content"

    captured = capsys.readouterr()
    raw_captured_out = captured.out
    assert_message_in_output(raw_captured_out, "Appended clipboard contents to '", test_file, "'.")
    
    normalized_out = normalize_for_assertion(raw_captured_out)
    assert "append_clipboard.py Statistics" not in normalized_out
    
    normalized_err = normalize_for_assertion(captured.err)
    assert "did not exist" not in normalized_err

def test_append_creates_new_file(mock_get_clipboard_ac, tmp_path, capsys, ac_runner):
    mock_get_clipboard_ac.return_value = "new file data"
    test_file = tmp_path / "new_append_file.txt"
    assert not test_file.exists()

    with pytest.raises(SystemExit) as e:
        ac_runner([str(test_file), "--no-stats"])
    assert e.value.code == 0
    assert test_file.exists()
    assert test_file.read_text() == "\nnew file data"

    captured = capsys.readouterr()
    raw_captured_out = captured.out
    assert_message_in_output(raw_captured_out, "Appended clipboard contents to '", test_file, "'.")

    raw_captured_err = captured.err
    assert_message_in_output(raw_captured_err, "Note: File '", test_file, "' did not exist, it will be created.")

def test_append_empty_clipboard_does_nothing_to_file(mock_get_clipboard_ac, tmp_path, capsys, ac_runner):
    mock_get_clipboard_ac.return_value = "" 
    test_file = tmp_path / "empty_clipboard_append.txt"
    initial_content = "original content for append"
    test_file.write_text(initial_content)

    with pytest.raises(SystemExit) as e:
        ac_runner([str(test_file), "--no-stats"])
    
    assert e.value.code == 0 
    assert test_file.read_text() == initial_content 

    captured = capsys.readouterr()
    normalized_out = normalize_for_assertion(captured.out)
    normalized_err = normalize_for_assertion(captured.err)

    assert "Clipboard is empty. Aborting." in normalized_err
    assert "Appended clipboard contents to" not in normalized_out

def test_stats_output_append(mock_get_clipboard_ac, tmp_path, capsys, ac_runner):
    mock_get_clipboard_ac.return_value = "stats test append"
    test_file = tmp_path / "stats_append.txt"
    
    with pytest.raises(SystemExit) as e:
        ac_runner([str(test_file)]) 
    assert e.value.code == 0
    
    raw_captured_out = capsys.readouterr().out
    normalized_out = normalize_for_assertion(raw_captured_out)
    assert "append_clipboard.py Statistics" in normalized_out
    assert "Successfully appended." in normalized_out 
    assert "File Action" in normalized_out 
    assert "Created new file" in normalized_out 

def test_get_clipboard_not_implemented_append(mock_get_clipboard_ac, tmp_path, capsys, ac_runner):
    mock_get_clipboard_ac.side_effect = NotImplementedError("Clipboard not available for append")
    test_file = tmp_path / "error_test_append.txt"

    with pytest.raises(SystemExit) as e:
        ac_runner([str(test_file), "--no-stats"])
    assert e.value.code == 1

    raw_captured_err = capsys.readouterr().err
    normalized_err = normalize_for_assertion(raw_captured_err)
    
    assert "[ERROR] Clipboard functionality (get_clipboard) not implemented." in normalized_err
    assert "Ensure clipboard utilities are installed and accessible." in normalized_err
