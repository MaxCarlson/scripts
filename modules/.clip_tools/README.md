# .clip_tools Module

The `.clip_tools` module provides a unified command-line interface (CLI) for various clipboard-related workflows and system interactions. It aims to streamline common tasks involving clipboard content, file manipulation, and command execution within a terminal environment, particularly for users leveraging `tmux`.

## Features

This module consolidates functionalities previously found in separate scripts, offering a consistent interface for:

*   **`append`**: Appends the current clipboard content to a specified file. Useful for quickly logging or accumulating text.
*   **`diff`**: Compares the current clipboard content with the content of a specified file, displaying a unified diff. This is invaluable for reviewing changes or discrepancies.
*   **`replace-block`**: Designed for Python development, this command replaces a specific function or class definition within a Python file with the code block currently in the clipboard. It intelligently handles decorators and block indentation.
*   **`copy-buffer`**: Copies the scrollback buffer of a `tmux` pane to the clipboard. It can copy the entire buffer or intelligently extract content since the last "clear screen" event.
*   **`copy-log`**: Retrieves and copies the last N lines from the current shell session's log file to the clipboard. This is useful for sharing recent command history or output.
*   **`copy`**: A versatile command for copying content from one or more files to the clipboard. It supports:
    *   Raw concatenation of file contents.
    *   Individual wrapping of each file's content with a header (e.g., filename, path) and a code block.
    *   Wrapping all combined content in a single, marked block for structured pasting.
    *   Appending the new content to existing clipboard content, with smart handling for previously wrapped blocks.
*   **`paste`**: Pastes the current clipboard content. If a file path is provided, it overwrites the file with the clipboard's content. If no file is specified, it prints the clipboard content directly to standard output.
*   **`run`**: Executes a shell command and copies its combined standard output and standard error to the clipboard. It also supports replaying a command from the shell history (e.g., the last command executed), making it easy to capture the output of previous operations.

## Architecture

The module is built with a focus on modularity and adaptability:

*   **Backend Abstraction (`backends.py`)**: All interactions with external system components (clipboard, `tmux`, shell history) are routed through an adapter layer (`backends.py`). This design allows for easy integration with different underlying system utilities (e.g., `modules.system_tools` or `cross_platform` utilities) without modifying the core CLI logic.
*   **`argparse`**: The command-line interface is robustly handled using Python's `argparse` module, providing clear subcommands and options.
*   **`rich` Integration**: The `rich` library is used for enhanced and visually appealing console output, including formatted tables for statistics and colored diffs.
*   **Test Coverage**: The module includes a comprehensive suite of unit tests (`tests/` directory) to ensure the reliability and correctness of its various functionalities.

## Usage

The `clip_tools` module is primarily designed to be invoked as a command-line utility. Each feature is exposed as a subcommand. For detailed usage of each subcommand and its options, refer to the built-in help:

```bash
clip_tools --help
clip_tools <subcommand> --help
```