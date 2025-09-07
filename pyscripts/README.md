# pyscripts/ - A Collection of Python Utilities

This directory contains a diverse collection of Python scripts designed to automate various tasks, enhance command-line workflows, and provide system-level utilities. Each script is a standalone tool, often leveraging modern Python libraries like `rich` for enhanced console output and `psutil` for system interaction.

## Scripts Overview

Here's a summary of the main scripts available in this directory:

### Clipboard & Text Manipulation

*   **`append_clipboard.py`**: Appends the content of the system clipboard to a specified file. Useful for quickly logging or accumulating text.
    *   **Usage**: `python append_clipboard.py <file_path> [--no-stats]`
*   **`clipboard_diff.py`**: Diffs the content of the system clipboard against a specified file, displaying a colored unified diff and providing statistics. It also snapshots the last diff operation for potential reuse by other tools.
    *   **Usage**: `python clipboard_diff.py <file_path> [-c <context_lines>] [-t <similarity_threshold>] [-l <loc_diff_warn>] [--no-stats]`
*   **`clipboard_replace.py`**: Replaces a Python function or class definition within a specified file with content from the system clipboard. The name of the function/class to be replaced is automatically extracted from the clipboard content.
    *   **Usage**: `python clipboard_replace.py <python_file_path> [--no-stats]`
*   **`copy_buffer_to_clipboard.py`**: Copies the current terminal scrollback buffer to the system clipboard. Primarily designed for use within a `tmux` session.
    *   **Usage**: `python copy_buffer_to_clipboard.py [-f | --full] [--no-stats]`
*   **`copy_log_to_clipboard.py`**: Copies the last N lines from the current shell session's log file to the system clipboard. The log file is determined based on the `SHLVL` environment variable.
    *   **Usage**: `python copy_log_to_clipboard.py [-n <num_lines>] [--no-stats]`
*   **`copy_to_clipboard.py`**: Copies content from one or more specified files to the system clipboard with flexible formatting and appending options (raw, wrapped, whole-wrapped, append, smart append).
    *   **Usage**: `python copy_to_clipboard.py <FILE> [FILE...] [-r | -w | -W] [-f] [-a [-o]] [--no-stats]`
*   **`output_to_clipboard.py`**: Executes a shell command (or replays a command from history) and copies its combined standard output and standard error to the clipboard. Supports shell integration for aliases/functions and output wrapping.
    *   **Usage**: `python output_to_clipboard.py [-r N] [-w] [-a] [-s <shell>] [--no-stats] [--] [command [arg ...]]`
*   **`print_clipboard.py`**: Prints the current content of the system clipboard to the console. Offers options for colorizing the output and displaying a summary statistics table.
    *   **Usage**: `python print_clipboard.py [-c <style>] [-N]`
*   **`set_clipboard_text.py`**: Sets the content of the system clipboard from a provided string argument or from standard input. Supports appending text to the existing clipboard content.
    *   **Usage**: `python set_clipboard_text.py [-t <text>] [-a] [--no-stats]`

### File & Directory Management

*   **`deduplicator.py`**: A comprehensive tool for finding and managing duplicate files within a specified directory. Supports various criteria for identifying duplicates (exact hash, same name, same name and size) and different retention policies.
    *   **Usage**: `python deduplicator.py <directory> [-p <pattern>] [-n] [-s] [-a] [-r [<depth>]] [--new] [-d] [-x] [-b <backup_dir>] [-H]`
*   **`delete_files.py`**: Deletes files matching a specified pattern within a given base directory, with options for recursive search and a dry run.
    *   **Usage**: `python delete_files.py -p <pattern> [-s <source_directory>] [-r [<depth>]] [-d]`
*   **`file_kit.py`**: A versatile command-line utility for various file and disk management tasks, including finding files by size/date, duplicate detection, directory usage analysis (`du`), and disk free space reporting (`df`).
    *   **Usage**: `python file_kit.py <command> [options]` (e.g., `python file_kit.py largest -p . -t 5 --group images --csv`)
*   **`folder_matcher.py`**: Finds folders in a source directory that meet specific criteria (minimum number of files with a given extension) and then processes them by moving them to a target directory or deleting them if a matching folder already exists.
    *   **Usage**: `python folder_matcher.py <source_directory> <target_directory> --ext <extension> --num <min_count> [--delete]`
*   **`folder_similarity.py`**: Compares the similarity of folders between a source and a target directory based on the SHA-256 hashes of their contained files. Calculates Jaccard similarity and can optionally delete target folders above a certain similarity threshold.
    *   **Usage**: `python folder_similarity.py --sources <source_dir> --target <target_dir> [--delete <threshold_percent>] [--dry-run]`
*   **`folder_stats.py`**: Analyzes disk usage and file statistics within a directory, providing detailed breakdowns by file extension, identifying "hotspot" folders, and listing top files.
    *   **Usage**: `python folder_stats.py <directory> [-d <depth>] [-t] [-a] [-o <date_type>] [-x <exclude_glob>] [-s <sort_by>] [-r] [-l] [-e <ext>] [-k <num>] [-q <sort_by>] [-w] [-c <num>] [-m <depth>] [-z <num>] [-f <num>] [-F <scope>] [-n] [-p] [-i <interval>] [-y] [-g <min_size>]`
*   **`llm_project_parser.py`**: Parses a text file containing an LLM-generated output that describes a project's folder structure and file contents, and then recreates that structure and files in a specified output directory.
    *   **Usage**: `python llm_project_parser.py --input <input_file.txt> --output <output_directory> [--dry-run] [--verbose]`
*   **`repo_processor.py`**: A versatile tool for processing a source code repository (or any folder) by either zipping it up with customizable filtering or generating a detailed textual representation suitable for Large Language Models (LLMs).
    *   **Usage**: `python repo_processor.py <source_dir> -o <output.zip> --format zip [...]` or `python repo_processor.py <source_dir> -o <analysis.txt> --format llm [...]`
*   **`space_converter.py`**: Recursively converts indentation in source code files between 2-space and 4-space formats. It analyzes each line to determine its current indentation and converts it to the target format.
    *   **Usage**: `python space_converter.py <paths...> --to-spaces <2|4> [-r] [-d <depth>] [-n] [-i <exts...>] [-g] [-v]`
*   **`zip_for_llms.py`**: A comprehensive tool for packaging a source code repository for consumption by Large Language Models (LLMs). It can create a filtered ZIP archive, generate a consolidated text file, and optionally run Gemini CLI analysis on the filtered workspace.
    *   **Usage**: `python zip_for_llms.py <source_dir> [-o <output_path>] [-f] [-z] [...]`

### Git & Version Control

*   **`apply_git_diffs.py`**: Applies a `git diff` formatted patch to files. It can read diffs from the clipboard, terminal input, or a file.
    *   **Usage**: `python apply_git_diffs.py [-d <directory>] [-i <input_source>] [-o] [-n] [-l <log_level>] [-c <console_log_level>] [-e] [-g <log_dir>] [--help-format]`
*   **`git_review.py`**: A command-line utility for viewing historical file contents and diffs from a Git repository. It supports navigating through commit history, tracking renames, and outputting results to the console, clipboard, or files.
    *   **Usage**: `python git_review.py --show -n 3 <file_path>` or `python git_review.py --diff -r <commit_hash> --commit`
*   **`git_sync.py`**: Automates the synchronization of a Git repository and its submodules by performing `git add`, `git commit`, `git pull`, and `git push` operations. It provides interactive prompts and detailed logging.
    *   **Usage**: `python git_sync.py [<add_pattern>] [-v] [-d] [--submodules [<submodule1>...|all]] [--submodule-add-patterns <json>] [--submodule-branches <json>]`
*   **`github_repos_info.py`**: A comprehensive tool for listing and analyzing GitHub repositories, providing various statistics (commits, size, LOC, submodules) and offering both static command-line output and an interactive Text User Interface (TUI).
    *   **Usage**: `python github_repos_info.py [-i] [-u <user>] [-c] [--date] [-s] [-d] [--loc [--use-latest-branch]] [--history] [...]`

### System Monitoring & Utilities

*   **`monitor-disks.py`**: A real-time, cross-platform command-line utility for monitoring disk performance and I/O activity, including disk usage, read/write speeds, and process-level disk access.
    *   **Usage**: `python monitor-disks.py [-u <update_time_ms>] [-i <polling_interval_ms>] [-r <rolling_avg_ms>] [-d <drive_or_mount_point>]`
*   **`proc_stats.py`**: A real-time command-line utility for monitoring process statistics (CPU usage, memory, disk I/O) with interactive sorting and filtering capabilities.
    *   **Usage**: `python proc_stats.py [-n <num_procs>] [-g <glob_pattern>] [-s <sort_mode>] [-a <analysis_ms>] [-u <update_ms>]`
*   **`sysmon.py`**: A unified, real-time system monitoring tool for the command line, providing interactive views for CPU, Memory, Disk I/O, Network, and GPU statistics.
    *   **Usage**: `python sysmon.py [-t <top_n>] [-i <interval>] [-g <glob>] [-w <view>] [-S <sort>] [-u <units>] [--low-prio] [-v]`
*   **`unify_shell.py`**: A framework for creating and managing unified shell aliases and functions across different shell environments (Zsh, PowerShell, Bash, etc.). It uses YAML files as a single source of truth for definitions and can generate shell-specific shims or execute portable Python implementations.
    *   **Usage**: `python unify_shell.py run mkcd my_new_dir` or `python unify_shell.py generate --yaml ~/dotfiles/unified --zsh ~/.zsh_aliases`

### Video Processing

*   **`edit_video_file.py`**: A command-line utility for basic video processing tasks, primarily leveraging `ffmpeg` and `ffprobe`, including merging, cutting, and downscaling.
    *   **Usage**: `python edit_video_file.py merge -i <inputs> -o <output>` or `python edit_video_file.py cut -i <input> -x <start> <end> -o <output>`
*   **`video_processor.py`**: A multi-threaded video processing and analysis tool that leverages `ffmpeg` and `ffprobe` to re-encode videos, analyze their metadata, and display real-time progress in an interactive dashboard.
    *   **Usage**: `python video_processor.py stats -i <input_path> [...]` or `python video_processor.py process -i <input_path> -o <output_dir> [...]`
*   **`ytdlp_cleanup.py`**: A utility to clean up leftover partial or fragmented files (e.g., from `yt-dlp` or other downloaders) and identify duplicate full media files within a specified directory.
    *   **Usage**: `python ytdlp_cleanup.py -p <root_folder> [-r <recent_hours>] [-a <age_days>] [-e <media_exts...>] [-d] [-D | -n] [-v]`

### Other Utilities

*   **`check_pytests.py`**: Compares Python scripts with their corresponding pytest-style test files, summarizes test coverage, and suggests fixes for mismatches or orphaned tests.
    *   **Usage**: `python check_pytests.py [-s <script_dir>] [-t <test_dir>] [-d <depth>] [-x <exclude_patterns>]`
*   **`convert_repo_to_pdf.py`**: Converts a multi-language MDX (Markdown with JSX) repository into a single PDF document using Pandoc and Tectonic.
    *   **Usage**: `python convert_repo_to_pdf.py --source <repo_path> --output <output.pdf> [...]`
*   **`convert_repo_to_pdf_v2.py`**: An alternative version of the PDF conversion script, offering different options for PDF engine and handling of MDX imports.
    *   **Usage**: `python convert_repo_to_pdf_v2.py --source <repo_path> --output <output.pdf> [--engine <engine>] [...]`
*   **`get_file_type_from_releases.py`**: A command-line tool to search for specific file types (assets) within GitHub releases of a given repository using the `gh` CLI tool.
    *   **Usage**: `python get_file_type_from_releases.py --repo <owner/repo> --pattern <glob_pattern> [...]`
*   **`run_history_process.py`**: Fetches historical commands from Atuin (a shell history tool), extracts potential file paths from them, filters and selects a specific path, and then either prints that path or executes a command using it.
    *   **Usage**: `python run_history_process.py [-l <limit>] [-i <index>] [-p <pattern>] [-v] [command_template...]`
*   **`run_pattern.py`**: Executes an arbitrary shell command on all files matching a given pattern within the current directory or its subdirectories.
    *   **Usage**: `python run_pattern.py <command> [pre_flags] <pattern> [post_flags]`
*   **`run_with_history.py`**: Executes a given command using the Nth most recent file or directory path extracted from the shell history. If no command is provided, it lists the 10 most recent paths found in the history.
    *   **Usage**: `python run_with_history.py [-n <number>] [command [arg ...]]`
*   **`rgcode.py`**: Extends `ripgrep` (`rg`) by finding and displaying the *enclosing code block* for each match found. Supports various programming languages and data formats, highlighting the matched text.
    *   **Usage**: `python rgcode.py <pattern> [<path>] [-c <color_style>] [-C <context_lines>]`
*   **`unpaired_finder.py`**: Scans a text file to detect and report unpaired or mismatched braces (`{}`, `[]`, `()`).
    *   **Usage**: `python unpaired_finder.py <filepath>`

---
