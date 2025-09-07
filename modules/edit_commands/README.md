# edit_commands Module

The `edit_commands` module provides a powerful command-line utility to retrieve, modify, and re-execute previous shell commands. It offers flexible ways to transform historical commands using various pattern matching and replacement techniques, and provides control over how these modified commands are executed.

## Purpose

To empower users with the ability to:
*   Quickly access and manipulate their shell command history.
*   Apply complex transformations to commands (e.g., find-and-replace, glob-based changes, regex substitutions).
*   Re-run multiple commands, either sequentially or in parallel.
*   Preview command modifications before execution.

## Key Files and Submodules

*   **`cli.py`**: This is the main command-line interface (CLI) script and the primary entry point for the `edit_commands` functionality. It parses all user arguments, orchestrates the retrieval of shell history, applies the specified command modifications, and then initiates the execution of the processed commands.

*   **`core.py`**: Contains the fundamental logic for handling command history and applying modifications:
    *   `get_shell_history()`: Responsible for retrieving shell command history from various environments (PowerShell, Bash, Zsh).
    *   `parse_run_order()`: Interprets user-defined execution order (e.g., `[0]`, `[0, -1]`, `[1:5]`) to select specific commands from history.
    *   `process_command()`: Applies the requested transformations (Vim-style substitution, glob-based replacement, or regex-based replacement) to a given command string.

*   **`executor.py`**: Manages the execution of the modified commands. It supports both sequential and parallel execution (using threading) and includes options for a dry-run (to preview commands without executing) and forcing continuation even if individual commands fail.

*   **`edit_commands.py` (top-level) and `scripts/edit_commands.py`**: These files serve as simple wrappers that directly call the `main()` function from `cli.py`. They provide convenient executable entry points for the module.

## Functionality Highlights

*   **History Retrieval & Selection**: Accesses recent shell commands and allows selection by index or range.
*   **Advanced Command Modification**: Supports:
    *   **Vim-style Substitution**: `s/old_pattern/new_pattern/g` for quick find-and-replace.
    *   **Glob-based Replacement**: Replace parts of commands that match file system glob patterns.
    *   **Regex-based Replacement**: Apply powerful regular expression substitutions to command strings.
*   **Flexible Execution**: Commands can be run one by one or concurrently.
*   **Safety Features**: Includes a dry-run mode to review changes before they are applied, and an option to `force` execution even if some commands encounter errors.

## Usage

The `edit_commands` module is designed to be run from the command line, typically by executing `cli.py` or the top-level `edit_commands.py` script.

```bash
# Example: Modify the last command (index 0) to replace 'foo' with 'bar' and re-run
python -m modules.edit_commands.cli -m 1 -o '[0]' --vim 's/foo/bar/g'

# Example: Dry-run a regex replacement on the last 3 commands
python -m modules.edit_commands.cli -m 3 -o '[0:3]' --regex 'old_regex' --replace 'new_value' --dry-run

# Example: Re-run the last 5 commands in parallel, forcing continuation on errors
python -m modules.edit_commands.cli -m 5 -o '[0:5]' --parallel --force
```

For a full list of arguments and options, run:
```bash
python -m modules.edit_commands.cli --help
```
