import inspect
import sys
import platform
import os
import datetime
import shutil
import glob

# --- Configuration ---
DEFAULT_CONSOLE_VERBOSITY = "Debug"
DEFAULT_LOG_VERBOSITY = "Warning"  # Log more important messages by default
DEFAULT_LOG_DIR = os.path.expanduser("~/logs")
MAX_LOG_FILE_SIZE_KB = 128  # Max size per log file in KB
MAX_TOTAL_LOG_SIZE_MB = 512  # Max total size for all logs in MB
MAX_LOG_FILES = 20 # Maximum number of log files to keep per directory
LOG_FILE_EXTENSION = ".log"

# --- Global Variables ---
_console_verbosity_level = DEFAULT_CONSOLE_VERBOSITY
_log_verbosity_level = DEFAULT_LOG_VERBOSITY
_log_dir = DEFAULT_LOG_DIR
_log_file_enabled = False # Flag to indicate if file logging is enabled
_current_log_filepath = None # Path to the currently active log file

# --- Utility Functions ---
def set_console_verbosity(level=DEFAULT_CONSOLE_VERBOSITY):
    """Set the global verbosity level for console output."""
    global _console_verbosity_level
    _console_verbosity_level = _validate_verbosity_level(level, "console")

def set_log_verbosity(level=DEFAULT_LOG_VERBOSITY):
    """Set the global verbosity level for file logging."""
    global _log_verbosity_level
    _log_verbosity_level = _validate_verbosity_level(level, "log")

def set_log_directory(filepath=DEFAULT_LOG_DIR):
    """Set the directory where log files will be stored."""
    global _log_dir
    _log_dir = os.path.expanduser(filepath) # Ensure user paths are expanded

def enable_file_logging():
    """Enable logging to file."""
    global _log_file_enabled, _current_log_filepath
    print("[Debug] Enabling file logging...") # ADDED DEBUG PRINT - ALREADY PRESENT
    _log_file_enabled = True
    _current_log_filepath = _initialize_log_file() # Initialize log file path
    print(f"[Debug] _current_log_filepath after enable_file_logging: {_current_log_filepath}") # ADDED DEBUG PRINT - CHECK VALUE AFTER INITIALIZATION

def disable_file_logging():
    """Disable logging to file."""
    global _log_file_enabled, _current_log_filepath
    _log_file_enabled = False
    _current_log_filepath = None

def _validate_verbosity_level(level, target_type):
    """Validate verbosity level and raise ValueError if invalid."""
    verbosity_levels = ["Verbose", "Debug", "Information", "Warning", "Error", "Critical"]
    level_capitalized = level.capitalize()
    if level_capitalized not in verbosity_levels:
        raise ValueError(f"Invalid {target_type} verbosity level: '{level}'. Must be one of {verbosity_levels}")
    return level_capitalized

def _is_at_verbosity_level(channel, verbosity_level):
    """Check if a channel is at or above the given verbosity level."""
    verbosity_levels = ["Verbose", "Debug", "Information", "Warning", "Error", "Critical"]
    current_level_index = verbosity_levels.index(verbosity_level)
    channel_level_index = verbosity_levels.index(channel.capitalize())
    return channel_level_index <= current_level_index

def _get_log_filename_prefix():
    """Determine the log filename prefix based on git repository or filename."""
    try:
        import git
        repo = git.Repo('.', search_parent_directories=True)
        repo_name = os.path.basename(repo.working_dir)
        return repo_name # Return repo_name directly for correct path joining later
    except ImportError:
        print("[Debug] GitPython ImportError in _get_log_filename_prefix") # ADDED DEBUG PRINT
        return None # GitPython not installed, fallback to filename based log
    except git.InvalidGitRepositoryError:
        print("[Debug] InvalidGitRepositoryError in _get_log_filename_prefix") # ADDED DEBUG PRINT
        return None # Not in a git repo, fallback to filename based log
    except Exception as e: # Catch any other git related errors
        print(f"[Debug] Exception in _get_log_filename_prefix: {e}") # ADDED DEBUG PRINT
        return None # Fallback if git detection fails
    print("[Debug] _get_log_filename_prefix completed successfully") # ADDED DEBUG PRINT - SUCCESS

def _initialize_log_file():
    """Initialize and return the log file path, creating directories and managing log rotation."""
    print("[Debug] _initialize_log_file started") # ADDED DEBUG PRINT - START
    log_prefix = _get_log_filename_prefix()
    calling_filename = os.path.splitext(os.path.basename(inspect.stack()[2].filename))[0] # Deeper stack for caller file
    date_str = datetime.date.today().isoformat()

    if log_prefix:
        log_dir = os.path.join(_log_dir, log_prefix)
        log_filename = f"{date_str}{LOG_FILE_EXTENSION}" # e.g., 2023-10-27.log
    else:
        log_dir = os.path.join(_log_dir, calling_filename) # Folder named after calling file
        log_filename = f"{calling_filename}_{date_str}{LOG_FILE_EXTENSION}" # e.g., my_script_2023-10-27.log

    os.makedirs(log_dir, exist_ok=True) # Create log directory if it doesn't exist
    log_filepath = os.path.join(log_dir, log_filename)
    print(f"[Debug] log_filepath after os.path.join: {log_filepath}") # ADDED DEBUG PRINT - FILEPATH

    if os.path.exists(log_filepath):
        if os.path.getsize(log_filepath) > MAX_LOG_FILE_SIZE_KB * 1024: # Check if log file is too large
            _rotate_logs(log_dir, log_filename) # Rotate logs if necessary

    _cleanup_old_logs(log_dir) # Clean up old logs if directory too large or too many files
    print(f"[Debug] _initialize_log_file returning: {log_filepath}") # ADDED DEBUG PRINT - RETURN VALUE
    return log_filepath

def _rotate_logs(log_dir, current_log_filename):
    """Rotate logs by renaming the current log file and creating a new one."""
    base, ext = os.path.splitext(current_log_filename)
    timestamp = datetime.datetime.now().strftime("%H%M%S") # HHMMSS timestamp for rotation
    rotated_filename = f"{base}_{timestamp}{ext}"
    current_filepath = os.path.join(log_dir, current_log_filename)
    rotated_filepath = os.path.join(log_dir, rotated_filename)

    if os.path.exists(current_filepath): # Check if file still exists before renaming (prevent FileNotFoundError)
        try:
            os.rename(current_filepath, rotated_filepath) # Rename current log
        except Exception as e:
            print(f"[Warning] Log rotation failed: {e}") # Non-critical failure
    else:
        print(f"[Warning] Current log file {current_filepath} not found, skipping rotation.")


def _cleanup_old_logs(log_dir):
    """Cleanup old logs if total size exceeds limit or too many files."""
    log_files = sorted(
        [f for f in os.scandir(log_dir) if f.is_file() and f.name.endswith(LOG_FILE_EXTENSION)],
        key=lambda f: f.stat().st_mtime # Sort by modification time (oldest first)
    )

    total_log_size_bytes = sum(f.stat().st_size for f in log_files)
    max_total_bytes = MAX_TOTAL_LOG_SIZE_MB * 1024 * 1024

    files_to_delete = []

    # --- Size-based cleanup ---
    # Delete oldest files if total size exceeds limit
    while total_log_size_bytes > max_total_bytes and log_files:
        oldest_file = log_files.pop(0)
        files_to_delete.append(oldest_file)
        total_log_size_bytes -= oldest_file.stat().st_size

    # --- Count-based cleanup ---
    # Delete files if number of log files exceeds limit (after size cleanup)
    if len(log_files) + len(files_to_delete) > MAX_LOG_FILES: # Check against original count + deleted
        num_excess_files = max(0, (len(log_files) + len(files_to_delete)) - MAX_LOG_FILES)
        files_to_delete.extend(log_files[:num_excess_files]) # Add oldest files to delete

    for file_entry in files_to_delete:
        try:
            os.remove(file_entry.path)
            print(f"[Debug] Deleted old log file: {file_entry.name}") # Debug message for cleanup
        except Exception as e:
            print(f"[Warning] Failed to delete old log file {file_entry.name}: {e}") # Non-critical warning


# --- Main Debug Function ---
def write_debug(message="", channel="Debug", condition=True, output_stream="stdout", location_channels=["Error", "Warning"]):
    """
    Enhanced Write-Debug function with verbosity control, file logging, log rotation,
    automatic file/line number (optional by channel), and stream control.

    Parameters:
    - message (str): The debug message to print.
    - channel (str): Type of message ("Error", "Warning", "Verbose", "Information", "Debug", "Critical").
    - condition (bool): If False, the message will not be processed or printed/logged. (Immediate kill switch)
    - output_stream (str): "stdout" or "stderr" to direct console output.
    - location_channels (list or bool or None): Channels to always show file/line.
      - True: Show for all channels. False/None: Show for none. List: Show for specified channels.
    """
    if not condition: # Immediate condition check at the very start
        return

    channel_upper = channel.capitalize()
    global _current_log_filepath # Explicitly declare _current_log_filepath as global

    output_message = message # ADDED - Unconditional definition to fix UnboundLocalError

    # --- Console Output Handling ---
    if _is_at_verbosity_level(channel_upper, _console_verbosity_level):
        # output_message = message # REMOVED - No longer needed here, defined unconditionally above
        show_location = False
        if isinstance(location_channels, bool):
            show_location = location_channels
        elif isinstance(location_channels, list):
            show_location = channel_upper in location_channels
        elif location_channels is None: # Explicitly handle None as no location
            show_location = False

        if show_location:
            caller = inspect.stack()[1] # Frame 1 is the caller of write_debug
            caller_file = caller.filename
            caller_line = caller.lineno
            output_message = f"[{caller_file}:{caller_line}] {message}"

        color_map = {
            "Error": "\033[91m", "Warning": "\033[93m", "Verbose": "\033[90m",
            "Information": "\033[96m", "Debug": "\033[92m", "Critical": "\033[95m"
        }
        reset_color = "\033[0m"
        supports_color = sys.stdout.isatty() and platform.system() != "Windows"
        color = color_map.get(channel_upper, "") if supports_color else ""
        formatted_message = f"{color}[{channel_upper}]{reset_color} {output_message}" if color else f"[{channel_upper}] {output_message}"

        stream = sys.stdout if output_stream.lower() == "stdout" else sys.stderr
        print(formatted_message, file=stream)

    # --- File Logging Handling ---
    if _log_file_enabled and _is_at_verbosity_level(channel_upper, _log_verbosity_level):
        if not _current_log_filepath: # Re-initialize log path if somehow lost
            print("[Debug] _current_log_filepath is None, re-initializing...")
            _current_log_filepath = _initialize_log_file()
        try:
            with open(_current_log_filepath, "a") as log_file:
                log_file.write(f"[{channel_upper}] {output_message}\n") # Use same output_message as console (with location if enabled)
        except Exception as e:
            print(f"[Error] Failed to write to log file {_current_log_filepath}: {e}") # Error to console if logging fails

# --- Example Usage ---
if __name__ == '__main__':
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
    set_log_directory("./custom_logs") # Relative path for example
    enable_file_logging() # Re-enable to use new directory

    write_debug("Warning message - console only (file logging disabled then re-enabled in new dir)", channel="Warning")

    print("\n--- Verbose messages in log (Debug log verbosity), Warning on console ---")
    write_debug("Verbose message - log only, not console", channel="Verbose") # Log only
    write_debug("Debug message - log only, not console", channel="Debug") # Log only
    write_debug("Warning message - console & log", channel="Warning") # Both

    print("\n--- Testing log rotation and cleanup (may need to run multiple times to trigger) ---")
    set_log_verbosity("Debug") # Log everything for rotation testing
    enable_file_logging()
    for i in range(200): # Generate enough log data to trigger rotation/cleanup
        write_debug(f"Test log message {i}", channel="Debug")

    print("\n--- Testing location_channels = None ---")
    write_debug("Error message with location hidden (location_channels=None)", channel="Error", location_channels=None)

    print("\n--- End of example, logs are in ~/logs or ./custom_logs ---")
