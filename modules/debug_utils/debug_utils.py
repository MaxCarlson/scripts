import inspect
import sys
import platform


def write_debug(message="", channel="Debug", condition=True, file_and_line=False):
    """
    Write-Debug function for Python.

    Parameters:
    - message (str): The debug message to print.
    - channel (str): The type of message ("Error", "Warning", "Verbose", "Information", "Debug").
    - condition (bool): If False, the message will not be printed.
    - file_and_line (bool): Include caller file and line number in the message.
    """
    # Validate and convert the condition
    if not condition:
        return

    # Prepare the message with optional caller information
    output_message = message
    if file_and_line:
        caller = inspect.stack()[1]
        caller_file = caller.filename
        caller_line = caller.lineno
        output_message = f"[{caller_file}:{caller_line}] {message}"

    # Define channel colors
    color_map = {
        "Error": "\033[91m",       # Red
        "Warning": "\033[93m",     # Yellow
        "Verbose": "\033[90m",     # Gray
        "Information": "\033[96m", # Cyan
        "Debug": "\033[92m"        # Green
    }
    reset_color = "\033[0m"

    # Only use colors if the platform supports it
    supports_color = sys.stdout.isatty() and platform.system() != "Windows"
    color = color_map.get(channel, "") if supports_color else ""
    reset = reset_color if supports_color else ""

    # Print the message with color
    if color:
        print(f"{color}{output_message}{reset}")
    else:
        print(output_message)
