# tests/debug_utils_test.py
import pytest
import sys
import os # Added import
from unittest.mock import patch, mock_open

from cross_platform.debug_utils import (
    write_debug,
    set_console_verbosity,
    _validate_verbosity_level,
    enable_file_logging,
    disable_file_logging,
    _initialize_log_file, # For testing its behavior if needed
    _get_log_filename_prefix # If testing git repo name logic
)

# To capture print statements to stdout/stderr
@pytest.fixture
def capsys_utf8(capsys):
    # Utility to read capsys output as UTF-8, good for special chars or colors
    class Capturer:
        def read(self):
            captured = capsys.readouterr()
            return captured.out, captured.err
    return Capturer()

def test_write_debug_stdout_debug_channel(capsys_utf8):
    set_console_verbosity("Debug")
    write_debug("Test debug message on Debug", channel="Debug", location_channels=False)
    out, err = capsys_utf8.read()
    assert "[Debug] Test debug message on Debug" in out.strip()

def test_write_debug_stdout_info_channel_when_verbose(capsys_utf8):
    set_console_verbosity("Verbose")
    write_debug("Test info message on Information", channel="Information", location_channels=False)
    out, err = capsys_utf8.read()
    assert "[Information] Test info message on Information" in out.strip()

def test_write_debug_stdout_filtered_by_verbosity(capsys_utf8):
    set_console_verbosity("Warning") # Only Warning, Error, Critical will print
    write_debug("This is a Debug message, should be filtered", channel="Debug")
    write_debug("This is an Info message, should be filtered", channel="Information")
    write_debug("This is a Warning message, should print", channel="Warning")
    out, err = capsys_utf8.read()
    assert "This is a Debug message, should be filtered" not in out
    assert "This is an Info message, should be filtered" not in out
    assert "[Warning] This is a Warning message, should print" in out

def test_write_debug_stderr(capsys_utf8):
    set_console_verbosity("Error")
    write_debug("Test error message", channel="Error", output_stream="stderr", location_channels=False)
    out, err = capsys_utf8.read()
    assert "[Error] Test error message" in err.strip()
    assert out == ""

def test_write_debug_with_condition(capsys_utf8):
    set_console_verbosity("Debug")
    write_debug("Should not print", channel="Debug", condition=False)
    out, err = capsys_utf8.read()
    assert "Should not print" not in out

def test_write_debug_with_location(capsys_utf8):
    set_console_verbosity("Debug")
    # The exact filename and line number will vary, so check for pattern
    write_debug("Message with location", channel="Debug", location_channels=True)
    out, err = capsys_utf8.read()
    assert "[Debug] [" in out # Start of location
    # Ensuring the correct filename based on typical behavior
    assert "debug_utils_test.py:" in out # Filename (corrected from 'test_debug_utils.py:')
    assert "] Message with location" in out # End of message

def test_invalid_verbosity_level_raises_valueerror():
    with pytest.raises(ValueError):
        _validate_verbosity_level("NotAVerbosityLevel", "console")

def test_valid_verbosity_levels():
    levels = ["Verbose", "Debug", "Information", "Warning", "Error", "Critical"]
    for level in levels:
        assert _validate_verbosity_level(level, "test") == level.capitalize()
        assert _validate_verbosity_level(level.lower(), "test") == level.capitalize()

# File logging tests (more involved due to file system interaction)
@patch("os.makedirs")
@patch("os.path.getsize")
@patch("os.rename") # For log rotation
@patch("os.scandir") # For log cleanup
@patch("os.remove") # For log cleanup
@patch("builtins.open", new_callable=mock_open)
@patch("cross_platform.debug_utils._get_log_filename_prefix", return_value="test_project")
def test_file_logging_writes_to_file(mock_prefix, mock_file, mock_remove, mock_scandir, mock_rename, mock_getsize, mock_makedirs, monkeypatch):
    # Setup for _initialize_log_file to succeed without actual FS impact
    mock_getsize.return_value = 0 # Simulate new/small log file
    # Mock scandir to return empty list to avoid cleanup complexities for this specific test
    mock_scandir.return_value = []

    # Ensure debug_utils globals are reset for this test
    monkeypatch.setattr("cross_platform.debug_utils._log_file_enabled", False)
    monkeypatch.setattr("cross_platform.debug_utils._current_log_filepath", None)

    set_console_verbosity("Critical") # Don't care about console output for this test
    enable_file_logging() # This will call _initialize_log_file

    log_message = "This should be logged to file."
    write_debug(log_message, channel="Warning") # Assuming default log verbosity is Warning or lower

    disable_file_logging() # Good practice to clean up state

    # Check if open was called with the log file path and message was written
    # _initialize_log_file determines the path, complex to assert exact path without more mocks
    # For simplicity, check that 'open' was called in append mode and write was attempted.
    # Ensure os.path.join and os.path.expanduser can be resolved if path is dynamic
    # In this case, pytest.approx might not be needed if the path components are fixed strings.
    # The error was NameError for 'os', so 'os.path.join' and 'os.path.expanduser' are the culprits.
    expected_log_dir = os.path.join(os.path.expanduser("~/logs"), "test_project")
    # The actual filename includes a date, so we might not be able to do an exact match on the full path
    # without also mocking datetime.date.today().
    # However, the error was NameError, not an assertion failure on the path itself.
    # The call to mock_file would be something like:
    # call(PosixPath('/home/user/logs/test_project/2025-05-17.log'), 'a')
    # For now, let's check the directory part was constructed as expected for the open call.
    
    # We need to find the call to open that involves the expected directory structure
    # and is opened in append mode 'a'.
    open_called_with_expected_pattern = False
    # The log filename includes the date, e.g., /path/to/logs/test_project/YYYY-MM-DD.log
    # For this test, it's simpler to check if mock_file was called with *any* path starting
    # with the directory and in append mode.
    for call_obj in mock_file.call_args_list:
        args, kwargs = call_obj
        # args[0] is the file path, args[1] is the mode
        if len(args) > 1 and isinstance(args[0], str) and args[0].startswith(expected_log_dir) and args[1] == "a":
            open_called_with_expected_pattern = True
            break
    assert open_called_with_expected_pattern, f"mock_open was not called with a path starting with {expected_log_dir} in append mode."


    # Get all write calls made to the mock_open file handle
    written_content = ""
    for call_args in mock_file().write.call_args_list:
        written_content += call_args[0][0] # call_args[0] is a tuple of args, [0][0] is the first arg

    assert f"[Warning] {log_message}" in written_content
    mock_makedirs.assert_called() # Check that log directory creation was attempted
