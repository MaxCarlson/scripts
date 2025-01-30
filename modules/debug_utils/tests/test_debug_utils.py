import os
import tempfile
import pytest
import io
import sys
import platform
import shutil
import glob
import datetime
from contextlib import redirect_stdout, redirect_stderr
from unittest.mock import patch

from debug_utils import (
    write_debug,
    set_console_verbosity,
    set_log_verbosity,
    set_log_directory,
    enable_file_logging,
    disable_file_logging,
    DEFAULT_CONSOLE_VERBOSITY,
    DEFAULT_LOG_VERBOSITY,
    DEFAULT_LOG_DIR,
    MAX_LOG_FILE_SIZE_KB,
    MAX_TOTAL_LOG_SIZE_MB,
    MAX_LOG_FILES,
    LOG_FILE_EXTENSION
)

# --- Helper Functions ---
def read_log_file(log_filepath):
    """Helper function to read content of a log file."""
    if os.path.exists(log_filepath):
        with open(log_filepath, 'r') as f:
            return f.read()
    return None

def clear_log_directory(log_dir):
    """Helper function to clear a log directory for tests."""
    if os.path.exists(log_dir):
        shutil.rmtree(log_dir)

# --- Test Console Output ---
def test_write_debug_console_output(capsys):
    write_debug("Test message", channel="Debug")
    captured = capsys.readouterr()
    assert "[DEBUG] Test message" in captured.out
    assert captured.err == ""

def test_write_debug_console_output_stderr(capsys):
    write_debug("Error message to stderr", channel="Error", output_stream="stderr")
    captured = capsys.readouterr()
    assert "[ERROR] Error message to stderr" in captured.err
    assert captured.out == ""

def test_write_debug_console_verbosity_control(capsys):
    set_console_verbosity("Warning")
    write_debug("Debug message - should not show", channel="Debug")
    write_debug("Warning message - should show", channel="Warning")
    captured = capsys.readouterr()
    assert "[WARNING] Warning message - should show" in captured.out
    assert "[DEBUG] Debug message - should not show" not in captured.out
    set_console_verbosity(DEFAULT_CONSOLE_VERBOSITY) # Reset

def test_write_debug_console_color_output(capsys):
    # This test is a bit tricky to assert color codes directly portably.
    # We can check for *some* color code presence on systems that likely support it.
    if os.isatty(sys.stdout.fileno()) and platform.system() != "Windows": # Check if TTY and not Windows
        write_debug("Error message in color", channel="Error")
        captured = capsys.readouterr()
        assert "\033[91m[ERROR]\033[0m" in captured.out # Check for red color code for Error
    else: # If not a TTY or Windows, just check for non-colored output
        write_debug("Error message no color", channel="Error")
        captured = capsys.readouterr()
        assert "[ERROR] Error message no color" in captured.out

def test_write_debug_console_no_color_if_no_tty(capsys, monkeypatch): # Use monkeypatch for mocking in pytest
    # Simulate no TTY by patching sys.stdout.isatty to return False using monkeypatch
    monkeypatch.setattr(sys.stdout, 'isatty', lambda: False)
    write_debug("Error message no tty", channel="Error")
    captured = capsys.readouterr()
    assert "[ERROR] Error message no tty" in captured.out
    assert "\033[91m" not in captured.out # No color codes should be present

def test_write_debug_console_condition_false(capsys):
    write_debug("Conditional message", channel="Debug", condition=False)
    captured = capsys.readouterr()
    assert captured.out == "" # No output if condition is False

def test_write_debug_console_location_default_error_warning(capsys):
    write_debug("Error message with location", channel="Error")
    captured_error = capsys.readouterr().err + capsys.readouterr().out # Capture both to be safe if output goes to stderr
    assert "[test_debug_utils.py:" in captured_error # File and line number should be present for Error

    write_debug("Debug message no location by default", channel="Debug")
    captured_debug = capsys.readouterr()
    assert "[test_debug_utils.py:" not in captured_debug.out # No location for Debug by default

def test_write_debug_console_location_forced_true(capsys):
    write_debug("Debug message with location forced", channel="Debug", location_channels=True)
    captured = capsys.readouterr()
    assert "[test_debug_utils.py:" in captured.out # Location shown when forced True

def test_write_debug_console_location_forced_false(capsys):
    write_debug("Error message no location forced", channel="Error", location_channels=False)
    captured = capsys.readouterr()
    assert "[test_debug_utils.py:" not in captured.out # Location hidden when forced False

def test_write_debug_console_location_channel_list(capsys):
    write_debug("Info message with location for Info only", channel="Information", location_channels=["Information"])
    captured_info = capsys.readouterr()
    assert "[test_debug_utils.py:" in captured_info.out # Location shown for Info

    write_debug("Warning message no location - Info list only", channel="Warning", location_channels=["Information"])
    captured_warning = capsys.readouterr()
    assert "[test_debug_utils.py:" not in captured_warning.out # No location for Warning

def test_write_debug_console_location_channel_none(capsys):
    write_debug("Error message no location - location_channels=None", channel="Error", location_channels=None)
    captured = capsys.readouterr()
    assert "[test_debug_utils.py:" not in captured.out # Location hidden when location_channels=None

# --- Test File Logging ---
@pytest.fixture(scope="function")
def log_dir_fixture():
    """Fixture to create and cleanup a temporary log directory for each test."""
    temp_dir = tempfile.mkdtemp()
    set_log_directory(temp_dir)
    yield temp_dir
    clear_log_directory(temp_dir) # Cleanup after each test

def test_write_debug_file_logging_enabled(log_dir_fixture):
    enable_file_logging()
    write_debug("Logged message to file", channel="Warning")
    disable_file_logging() # Disable after test

    log_files = glob.glob(os.path.join(log_dir_fixture, "*", "*.log")) # Expect logs in subdir
    assert len(log_files) == 1
    log_filepath = log_files[0]
    log_content = read_log_file(log_filepath)
    assert "[WARNING] Logged message to file" in log_content

def test_write_debug_file_logging_disabled(log_dir_fixture):
    disable_file_logging()
    write_debug("Message - no log should be written", channel="Warning")
    log_files = glob.glob(os.path.join(log_dir_fixture, "*", "*.log"))
    assert not log_files # No log file should be created

def test_write_debug_file_log_verbosity_control(log_dir_fixture):
    set_log_verbosity("Error") # Only Error and Critical should be logged
    enable_file_logging()

    write_debug("Warning message - should NOT be logged", channel="Warning")
    write_debug("Error message - should be logged", channel="Error")

    disable_file_logging()

    log_files = glob.glob(os.path.join(log_dir_fixture, "*", "*.log"))
    assert len(log_files) == 1 # Only one log file expected
    log_filepath = log_files[0]
    log_content = read_log_file(log_filepath)
    assert "[ERROR] Error message - should be logged" in log_content
    assert "[WARNING] Warning message - should NOT be logged" not in log_content
    set_log_verbosity(DEFAULT_LOG_VERBOSITY) # Reset log verbosity

def test_write_debug_file_log_rotation(log_dir_fixture):
    enable_file_logging()
    original_max_size = MAX_LOG_FILE_SIZE_KB
    try:
        global MAX_LOG_FILE_SIZE_KB # Modify global constant for testing
        MAX_LOG_FILE_SIZE_KB = 1 # Set to a very small size for easy rotation test

        write_debug("Initial log message", channel="Debug") # Create initial log file
        log_files_before_rotation = glob.glob(os.path.join(log_dir_fixture, "*", "*.log"))
        assert len(log_files_before_rotation) == 1
        filepath_before_rotation = log_files_before_rotation[0]

        # Write enough content to trigger rotation
        long_message = "This is a long message to trigger log rotation. " * 200 # Exceeds 1KB easily
        write_debug(long_message, channel="Debug")

        log_files_after_rotation = glob.glob(os.path.join(log_dir_fixture, "*", "*.log"))
        assert len(log_files_after_rotation) == 2 # Expect two log files after rotation

        # Check that the original file has been renamed (rotated)
        rotated_file_exists = False
        for f in log_files_after_rotation:
            if f != filepath_before_rotation and filepath_before_rotation.split('.')[0] in f: # Check for filename pattern
                rotated_file_exists = True
                break
        assert rotated_file_exists

        # Check new log file contains the new message
        newest_log_file = max(log_files_after_rotation, key=os.path.getmtime) # Get newest file by modification time
        new_log_content = read_log_file(newest_log_file)
        assert "[DEBUG] " + long_message[:50] in new_log_content # Check part of long message is in new log

    finally:
        MAX_LOG_FILE_SIZE_KB = original_max_size # Restore original max size
        disable_file_logging()

def test_write_debug_file_log_cleanup_size_limit(log_dir_fixture):
    enable_file_logging()
    original_max_total_size = MAX_TOTAL_LOG_SIZE_MB
    try:
        global MAX_TOTAL_LOG_SIZE_MB # Modify global constant for testing
        MAX_TOTAL_LOG_SIZE_MB = 0.001 # Set very small total size (1KB)

        for i in range(5): # Create enough logs to exceed total size
            write_debug(f"Log message {i} to test cleanup", channel="Debug")

        disable_file_logging()
        log_files_after_cleanup = glob.glob(os.path.join(log_dir_fixture, "*", "*.log"))
        assert len(log_files_after_cleanup) < 5 # Some logs should be deleted due to size limit

    finally:
        MAX_TOTAL_LOG_SIZE_MB = original_max_total_size # Restore original max total size
        disable_file_logging()

def test_write_debug_file_log_cleanup_file_count_limit(log_dir_fixture):
    enable_file_logging()
    original_max_files = MAX_LOG_FILES
    try:
        global MAX_LOG_FILES # Modify global constant for testing
        MAX_LOG_FILES = 3 # Limit to 3 log files

        for i in range(5): # Create more logs than allowed
            write_debug(f"Log message {i} for file count test", channel="Debug")

        disable_file_logging()
        log_files_after_cleanup = glob.glob(os.path.join(log_dir_fixture, "*", "*.log"))
        assert len(log_files_after_cleanup) <= MAX_LOG_FILES # Should not exceed MAX_LOG_FILES count

    finally:
        MAX_LOG_FILES = original_max_files # Restore original max files count
        disable_file_logging()

def test_write_debug_file_logging_error_handling(log_dir_fixture, capsys):
    enable_file_logging()
    log_filepath_error = os.path.join(log_dir_fixture, "cannot_write", "debug.log") # Path that likely cannot be created due to "cannot_write" being a file
    set_log_directory(log_filepath_error) # Try to set log dir to a file path

    write_debug("Message - logging error expected", channel="Error") # This should trigger a logging error

    captured = capsys.readouterr()
    assert "[Error] Failed to write to log file" in captured.err # Error message to console expected
    disable_file_logging()
    set_log_directory(log_dir_fixture) # Reset log dir for other tests

# --- Test Configuration Functions ---
def test_set_console_verbosity_valid():
    set_console_verbosity("Information")
    assert _console_verbosity_level == "Information"
    set_console_verbosity(DEFAULT_CONSOLE_VERBOSITY) # Reset

def test_set_console_verbosity_invalid():
    with pytest.raises(ValueError):
        set_console_verbosity("InvalidLevel")

def test_set_log_verbosity_valid():
    set_log_verbosity("Verbose")
    assert _log_verbosity_level == "Verbose"
    set_log_verbosity(DEFAULT_LOG_VERBOSITY) # Reset

def test_set_log_verbosity_invalid():
    with pytest.raises(ValueError):
        set_log_verbosity("BadLevel")

def test_set_log_directory_valid(log_dir_fixture):
    set_log_directory(log_dir_fixture)
    assert _log_dir == log_dir_fixture

def test_enable_disable_file_logging():
    enable_file_logging()
    assert _log_file_enabled is True
    disable_file_logging()
    assert _log_file_enabled is False

# --- Test Git Repo Log Naming (Mock GitPython) ---
def test_write_debug_log_naming_git_repo_prefix(log_dir_fixture, monkeypatch): # Use monkeypatch for patching
    monkeypatch.setattr("debug_utils._get_log_filename_prefix", lambda: "my-git-repo") # Mock using lambda
    enable_file_logging()
    write_debug("Git repo log naming test", channel="Debug")
    disable_file_logging()

    log_files = glob.glob(os.path.join(log_dir_fixture, "my-git-repo", "*.log"))
    assert len(log_files) == 1
    log_filepath = log_files[0]
    assert "my-git-repo" in log_filepath # Log should be in subdir "my-git-repo"

def test_write_debug_log_naming_no_git_prefix(log_dir_fixture, monkeypatch): # Use monkeypatch
    monkeypatch.setattr("debug_utils._get_log_filename_prefix", lambda: None) # Mock to return None
    enable_file_logging()
    write_debug("No git repo log naming test", channel="Debug")
    disable_file_logging()

    log_files = glob.glob(os.path.join(log_dir_fixture, "*", "*.log")) # Should be in a file named folder
    assert len(log_files) == 1
    log_filepath = log_files[0]
    assert os.path.basename(os.path.dirname(log_filepath)) == "test_debug_utils" # Folder named after test file

# --- Test Edge Cases and Error Handling (Beyond File Logging Errors already tested) ---
def test_write_debug_invalid_channel(capsys):
    write_debug("Message with invalid channel", channel="BogusChannel") # Should default to Debug or Information usually
    captured = capsys.readouterr()
    assert "[BOGUSCHANNEL] Message with invalid channel" in captured.out # Should still print, even if channel is not in color map

# --- Run Example Usage to ensure no runtime errors ---
def test_example_usage_runs_without_error(capsys, log_dir_fixture):
    # Redirect output to capture and avoid polluting test output
    with redirect_stdout(io.StringIO()) as stdout, redirect_stderr(io.StringIO()) as stderr:
        if __name__ == '__main__': # Directly run example code block from debug_utils.py
            print("--- Initial State ---")
            write_debug("Default Debug message (console)", channel="Debug")
            write_debug("Warning message (console)", channel="Warning")

            print("\n--- Enable File Logging (Warning level for logs) ---")
            enable_file_logging() # Defaults to Warning level for file logs
            write_debug("Debug message - console only", channel="Debug") # Console only due to verbosity
            write_debug("Warning message - console & log", channel="Warning") # Both console and log
            write_debug("Error message - console & log", channel="Error") # Both console and log

            print("\n--- Set Console Verbosity to Warning, Log to Debug ---")
            set_console_verbosity("Warning") # Console shows Warning and above
            set_log_verbosity("Debug") # Logs Debug and above
            write_debug("Debug message - log only", channel="Debug") # Only in log file
            write_debug("Warning message - console & log", channel="Warning") # Both console and log
            write_debug("Info message - log only", channel="Information") # Only in log file
            write_debug("Error message - console & log", channel="Error") # Both console and log

            print("\n--- Critical message always shows and logs ---")
            write_debug("Critical message - console & log", channel="Critical") # Always shows/logs

            print("\n--- Disable File Logging, change log directory ---")
            disable_file_logging()
            set_log_directory(log_dir_fixture) # Use test fixture temp dir
            enable_file_logging() # Re-enable to use new directory

            write_debug("Warning message - console only (file logging disabled then re-enabled in new dir)", channel="Warning")

            print("\n--- Verbose messages in log (Debug log verbosity), Warning on console ---")
            write_debug("Verbose message - log only, not console", channel="Verbose") # Log only
            write_debug("Debug message - log only, not console", channel="Debug") # Log only
            write_debug("Warning message - console & log", channel="Warning") # Both

            print("\n--- Testing log rotation and cleanup (may need to run multiple times to trigger) ---")
            set_log_verbosity("Debug") # Log everything for rotation testing
            enable_file_logging()
            for i in range(50): # Reduced loop for testing
                write_debug(f"Test log message {i}", channel="Debug")

            print("\n--- Testing location_channels = None ---")
            write_debug("Error message with location hidden (location_channels=None)", channel="Error", location_channels=None)

            print("\n--- End of example, logs are in ~/logs or ./custom_logs ---")

    # Assert no exceptions were raised by checking for empty error capture
    assert stderr.getvalue() == ""
