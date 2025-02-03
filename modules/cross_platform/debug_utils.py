import inspect
import sys
import platform
import os
import datetime
import glob

# --- Configuration ---
DEFAULT_CONSOLE_VERBOSITY = "Debug"
DEFAULT_LOG_VERBOSITY = "Warning"  # Log only more important messages by default
DEFAULT_LOG_DIR = os.path.expanduser("~/logs")
MAX_LOG_FILE_SIZE_KB = 128         # Max size per log file in KB
MAX_TOTAL_LOG_SIZE_MB = 512        # Max total size for all logs in MB
MAX_LOG_FILES = 20                 # Maximum number of log files to keep per directory
LOG_FILE_EXTENSION = ".log"

# --- Global Variables ---
_console_verbosity_level = DEFAULT_CONSOLE_VERBOSITY
_log_verbosity_level = DEFAULT_LOG_VERBOSITY
_log_dir = DEFAULT_LOG_DIR
_log_file_enabled = False          # Indicates if file logging is enabled
_current_log_filepath = None       # Path to the currently active log file

# --- Utility Functions ---
def set_console_verbosity(level: str = DEFAULT_CONSOLE_VERBOSITY) -> None:
    """Set the global verbosity level for console output."""
    global _console_verbosity_level
    _console_verbosity_level = _validate_verbosity_level(level, "console")

def set_log_verbosity(level: str = DEFAULT_LOG_VERBOSITY) -> None:
    """Set the global verbosity level for file logging."""
    global _log_verbosity_level
    _log_verbosity_level = _validate_verbosity_level(level, "log")

def set_log_directory(filepath: str = DEFAULT_LOG_DIR) -> None:
    """Set the directory where log files will be stored."""
    global _log_dir
    _log_dir = os.path.expanduser(filepath)

def enable_file_logging() -> None:
    """Enable logging to file."""
    global _log_file_enabled, _current_log_filepath
    print("[Debug] Enabling file logging...")  # Debug print; can be removed if not desired
    _log_file_enabled = True
    _current_log_filepath = _initialize_log_file()
    print(f"[Debug] Current log file: {_current_log_filepath}")

def disable_file_logging() -> None:
    """Disable logging to file."""
    global _log_file_enabled, _current_log_filepath
    _log_file_enabled = False
    _current_log_filepath = None

def _validate_verbosity_level(level: str, target_type: str) -> str:
    """Validate verbosity level and raise ValueError if invalid."""
    verbosity_levels = ["Verbose", "Debug", "Information", "Warning", "Error", "Critical"]
    level_capitalized = level.capitalize()
    if level_capitalized not in verbosity_levels:
        raise ValueError(f"Invalid {target_type} verbosity level: '{level}'. Must be one of {verbosity_levels}")
    return level_capitalized

def _is_at_verbosity_level(channel: str, verbosity_level: str) -> bool:
    """Check if a channel is at or above the given verbosity level."""
    verbosity_levels = ["Verbose", "Debug", "Information", "Warning", "Error", "Critical"]
    current_index = verbosity_levels.index(verbosity_level)
    channel_index = verbosity_levels.index(channel.capitalize())
    return channel_index >= current_index

def _get_log_filename_prefix() -> str:
    """
    Determine a log filename prefix based on the git repository name
    or fallback to a default name.
    """
    try:
        import git
        repo = git.Repo('.', search_parent_directories=True)
        repo_name = os.path.basename(repo.working_dir)
        return repo_name
    except Exception:
        return "cross_platform_log"

def _initialize_log_file() -> str:
    """Initialize and return the log file path, handling rotation and cleanup."""
    log_prefix = _get_log_filename_prefix()
    caller_filename = os.path.splitext(os.path.basename(inspect.stack()[2].filename))[0]
    date_str = datetime.date.today().isoformat()

    log_dir = os.path.join(_log_dir, log_prefix or caller_filename)
    log_filename = f"{date_str}{LOG_FILE_EXTENSION}" if log_prefix else f"{caller_filename}_{date_str}{LOG_FILE_EXTENSION}"

    os.makedirs(log_dir, exist_ok=True)
    log_filepath = os.path.join(log_dir, log_filename)

    # Rotate log file if too large
    if os.path.exists(log_filepath) and os.path.getsize(log_filepath) > MAX_LOG_FILE_SIZE_KB * 1024:
        _rotate_logs(log_dir, log_filename)

    _cleanup_old_logs(log_dir)
    return log_filepath

def _rotate_logs(log_dir: str, current_log_filename: str) -> None:
    """Rotate the current log file."""
    base, ext = os.path.splitext(current_log_filename)
    timestamp = datetime.datetime.now().strftime("%H%M%S")
    rotated_filename = f"{base}_{timestamp}{ext}"
    current_filepath = os.path.join(log_dir, current_log_filename)
    rotated_filepath = os.path.join(log_dir, rotated_filename)
    try:
        if os.path.exists(current_filepath):
            os.rename(current_filepath, rotated_filepath)
    except Exception as e:
        print(f"[Warning] Log rotation failed: {e}")

def _cleanup_old_logs(log_dir: str) -> None:
    """Cleanup old log files if necessary."""
    log_files = sorted(
        [entry for entry in os.scandir(log_dir) if entry.is_file() and entry.name.endswith(LOG_FILE_EXTENSION)],
        key=lambda entry: entry.stat().st_mtime
    )
    total_size = sum(entry.stat().st_size for entry in log_files)
    max_total_bytes = MAX_TOTAL_LOG_SIZE_MB * 1024 * 1024

    files_to_delete = []
    # Delete oldest files if total size exceeds limit
    while total_size > max_total_bytes and log_files:
        oldest = log_files.pop(0)
        files_to_delete.append(oldest)
        total_size -= oldest.stat().st_size

    # Also enforce a maximum number of log files
    if len(log_files) + len(files_to_delete) > MAX_LOG_FILES:
        excess = (len(log_files) + len(files_to_delete)) - MAX_LOG_FILES
        files_to_delete.extend(log_files[:excess])

    for entry in files_to_delete:
        try:
            os.remove(entry.path)
            print(f"[Debug] Deleted old log file: {entry.name}")
        except Exception as e:
            print(f"[Warning] Failed to delete old log file {entry.name}: {e}")

def write_debug(message: str = "", channel: str = "Debug", condition: bool = True,
                output_stream: str = "stdout", location_channels=None) -> None:
    """
    Write a debug message to console and, if enabled, to the log file.
    Parameters:
      - message: The debug message.
      - channel: One of ("Verbose", "Debug", "Information", "Warning", "Error", "Critical").
      - condition: If False, the message will not be processed.
      - output_stream: "stdout" or "stderr".
      - location_channels: If True, always show caller location; if list, only for specified channels.
    """
    if not condition:
        return

    channel_cap = channel.capitalize()
    global _current_log_filepath

    output_message = message

    # Determine whether to include caller location
    show_location = False
    if isinstance(location_channels, bool):
        show_location = location_channels
    elif isinstance(location_channels, list):
        show_location = channel_cap in location_channels

    if show_location:
        caller = inspect.stack()[1]
        output_message = f"[{caller.filename}:{caller.lineno}] {message}"

    # Color mapping for terminal output (if supported)
    color_map = {
        "Error": "\033[91m", "Warning": "\033[93m", "Verbose": "\033[90m",
        "Information": "\033[96m", "Debug": "\033[92m", "Critical": "\033[95m"
    }
    reset_color = "\033[0m"
    supports_color = sys.stdout.isatty() and platform.system() != "Windows"
    color = color_map.get(channel_cap, "") if supports_color else ""
    formatted_message = f"{color}[{channel_cap}]{reset_color} {output_message}" if color else f"[{channel_cap}] {output_message}"

    # Console output
    stream = sys.stdout if output_stream.lower() == "stdout" else sys.stderr
    if _is_at_verbosity_level(channel_cap, _console_verbosity_level):
        print(formatted_message, file=stream)

    # File logging
    if _log_file_enabled and _is_at_verbosity_level(channel_cap, _log_verbosity_level):
        if not _current_log_filepath:
            _current_log_filepath = _initialize_log_file()
        try:
            with open(_current_log_filepath, "a") as log_file:
                log_file.write(f"[{channel_cap}] {output_message}\n")
        except Exception as e:
            print(f"[Error] Failed to write to log file {_current_log_filepath}: {e}")

