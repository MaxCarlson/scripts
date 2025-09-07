import sys
import os
import json
import re  # For ANSI code stripping
import types
import pytest
from pathlib import Path
from unittest import mock

# -----------------------------------------------------------------------------
# Shared helpers
# -----------------------------------------------------------------------------
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
        f"'{text_after_path}' not found after '{text_before_path}' " \
        f"(from index {path_start_index_in_norm}) in normalized output: '{normalized_out}'"

    path_as_printed_and_normalized = normalized_out[path_start_index_in_norm:idx_text_after]
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


# -----------------------------------------------------------------------------
# Test setup: provide a fake cross_platform.clipboard_utils for imports
# -----------------------------------------------------------------------------
# Create a package stub for cross_platform so submodule imports work reliably.
sys.modules.setdefault("cross_platform", types.ModuleType("cross_platform"))

# This MagicMock module is used by both replace_with_clipboard and clipboard_diff.
mock_clipboard_utils_rwc_module = mock.MagicMock()
sys.modules['cross_platform.clipboard_utils'] = mock_clipboard_utils_rwc_module
# Also attach the submodule on the package stub (not strictly required, but tidy)
setattr(sys.modules["cross_platform"], "clipboard_utils", mock_clipboard_utils_rwc_module)

# Import modules under test
import replace_with_clipboard
import clipboard_diff


# -----------------------------------------------------------------------------
# Fixtures for the original replace_with_clipboard tests
# -----------------------------------------------------------------------------
@pytest.fixture
def mock_get_clipboard_rwc(monkeypatch):
    """
    For the classic RWC tests we patch replace_with_clipboard.get_clipboard directly.
    (This leaves clipboard_diff free to use the submodule's MagicMock.)
    """
    mock_get = mock.Mock()
    monkeypatch.setattr(replace_with_clipboard, 'get_clipboard', mock_get)
    return mock_get

@pytest.fixture
def rwc_runner(monkeypatch):
    """
    Test helper that parses args and calls the main function in replace_with_clipboard.
    NOTE: Our updated function signature supports (file, no_stats, from_last_cld=False),
    and we only pass the first two in the legacy cases here.
    """
    def run(args_list):
        full_argv = ["replace_with_clipboard.py"] + args_list
        monkeypatch.setattr(sys, "argv", full_argv)
        args = replace_with_clipboard.parser.parse_args(args_list)
        replace_with_clipboard.replace_or_print_clipboard(args.file, args.no_stats)
    return run


# -----------------------------------------------------------------------------
# Original replace_with_clipboard tests (unchanged behavior)
# -----------------------------------------------------------------------------
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


# -----------------------------------------------------------------------------
# New: --from-last-cld tests (merged here)
# These use the MagicMock module to feed clipboard content to clipboard_diff,
# and rely on CLIPBOARD_STATE_DIR to isolate snapshot files.
# -----------------------------------------------------------------------------
@pytest.fixture
def tmp_state_dir(tmp_path, monkeypatch):
    d = tmp_path / "state"
    d.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("CLIPBOARD_STATE_DIR", str(d))
    return d

def test_from_last_cld_infers_file_path(tmp_path, tmp_state_dir):
    # Prepare a file and run cld to create the snapshot
    target = tmp_path / "target.txt"
    target.write_text("old\n", encoding="utf-8")

    # Seed clipboard for CLD
    mock_clipboard_utils_rwc_module.get_clipboard.return_value = "newcontent\n"

    # Run CLD (no stats)
    with pytest.raises(SystemExit):
        clipboard_diff.diff_clipboard_with_file(str(target), context_lines=3,
                                                similarity_threshold=0.5,
                                                loc_diff_warning_threshold=50,
                                                no_stats=True)

    # Verify snapshot exists
    meta = json.loads((tmp_state_dir / "last_cld.json").read_text(encoding="utf-8"))
    assert meta["file_path"].endswith("target.txt")

    # Now run RWC with --from-last-cld and no FILE → should overwrite saved file
    with pytest.raises(SystemExit) as e:
        replace_with_clipboard.replace_or_print_clipboard(None, True, True)
    assert e.value.code == 0

    assert target.read_text(encoding="utf-8") == "newcontent\n"

def test_from_last_cld_with_explicit_other_file(tmp_path, tmp_state_dir):
    saved_file = tmp_path / "saved.txt"
    other_file = tmp_path / "other.txt"
    saved_file.write_text("hello\n", encoding="utf-8")
    other_file.write_text("xxx\n", encoding="utf-8")

    # Seed clipboard for CLD snapshot
    mock_clipboard_utils_rwc_module.get_clipboard.return_value = "snapshot_data"

    with pytest.raises(SystemExit):
        clipboard_diff.diff_clipboard_with_file(str(saved_file), context_lines=3,
                                                similarity_threshold=0.5,
                                                loc_diff_warning_threshold=50,
                                                no_stats=True)

    # Now replace OTHER using saved snapshot (explicit FILE overrides the meta file path)
    with pytest.raises(SystemExit) as e:
        replace_with_clipboard.replace_or_print_clipboard(str(other_file), True, True)
    assert e.value.code == 0

    assert other_file.read_text(encoding="utf-8") == "snapshot_data\n"
    assert saved_file.read_text(encoding="utf-8") == "hello\n"  # unchanged

def test_from_last_cld_missing_snapshot_errors(tmp_path, tmp_state_dir, capsys):
    # Ensure no snapshot files exist
    meta = tmp_state_dir / "last_cld.json"
    clip = tmp_state_dir / "last_cld_clipboard.txt"
    if meta.exists(): meta.unlink()
    if clip.exists(): clip.unlink()

    with pytest.raises(SystemExit) as e:
        replace_with_clipboard.replace_or_print_clipboard(None, False, True)
    assert e.value.code == 1
    err = capsys.readouterr().err
    assert "No saved clipboard snapshot" in err

def test_from_last_cld_missing_saved_file_path_errors(tmp_path, tmp_state_dir, capsys):
    # Create an invalid meta with no file_path but a clipboard file
    bad_meta = {"file_path": None, "timestamp_utc": "now"}
    (tmp_state_dir / "last_cld_clipboard.txt").write_text("data", encoding="utf-8")
    (tmp_state_dir / "last_cld.json").write_text(json.dumps(bad_meta), encoding="utf-8")

    with pytest.raises(SystemExit) as e:
        replace_with_clipboard.replace_or_print_clipboard(None, False, True)
    assert e.value.code == 1
    err = capsys.readouterr().err
    assert "No saved file path from the last `cld` run" in err
