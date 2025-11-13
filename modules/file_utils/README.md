# file_utils Module

The `file_utils` module provides a comprehensive set of Python utilities for managing files and directories. It offers functionalities for identifying and handling duplicate files, organizing files based on various criteria, and merging the contents of multiple files with advanced filtering and transformation options.

## Purpose

To offer a robust and flexible toolkit for:
*   Efficiently finding and managing duplicate files within a specified directory.
*   Automating the organization of files into structured subdirectories.
*   Consolidating content from multiple files with fine-grained control over what is included and how it is transformed.
*   Providing essential file-related helper functions.

## Key Files and Classes

*   **`__init__.py`**: The package initializer, which exposes the primary functions from its submodules, making them directly accessible when `file_utils` is imported. This includes `find_duplicates`, `delete_files`, `summarize_statistics`, `organize_files`, `merge_files`, `calculate_file_hash`, and `write_debug`.

*   **`duplicate_finder.py`**: Contains the core logic for identifying duplicate files. It can perform comparisons based on file content (using SHA-256 hashes for accuracy) or simply by file name. It also includes functions to delete the detected duplicate files and to generate a summary of the duplicate removal process, including total files scanned, unique files, and total size deleted.

*   **`file_manager.py`**: This script acts as a top-level orchestrator for file management tasks. It parses command-line arguments to determine whether to find and delete duplicates or to organize files, then calls the appropriate functions from `duplicate_finder.py` and `file_organizer.py`.

*   **`file_organizer.py`**: Provides the `organize_files` function, which automates the sorting of files within a given directory. Files can be organized into subdirectories based on their file type (extension) or their creation date.

*   **`file_utils.py`**: This file contains the powerful `merge_files` function. This utility allows users to combine the contents of multiple files from a base folder into a single output. It supports a wide array of options, including:
    *   **Glob Patterns**: Specify which files to include (e.g., `*.log`).
    *   **Output File**: Direct merged content to a file or stdout.
    *   **Line Filtering**: Include only lines matching a regex pattern or within a specific line range.
    *   **Content Extraction**: Define start and end patterns to extract specific sections from files.
    *   **Headers**: Include file headers in the merged output.
    *   **Order**: Reverse the order of files before merging.
    *   **Encoding**: Specify character encoding for file reading.
    *   **Transformations**: Apply Vim-like substitutions to lines during merging.

*   **`utils.py`**: A collection of general utility functions used across the module. Key functions include `calculate_file_hash` (which computes the SHA-256 hash of a file) and a basic `write_debug` function for logging messages.

## Functionality Highlights

*   **Duplicate Management**: Comprehensive tools to identify, report, and remove duplicate files, helping to reclaim disk space.
*   **Automated File Organization**: Simplifies file management by automatically sorting files into logical categories.
*   **Advanced File Merging**: Offers highly customizable options for concatenating file contents, making it suitable for tasks like log analysis, code review, or documentation generation.

## Dependencies

*   `cross_platform.debug_utils`: Used by `utils.py` (and thus indirectly by other scripts) for logging and debugging purposes.

## Usage

CLI entry points installed:

- `file-util` — primary command
- `fu` — short alias
- `fsu` — alternate short alias

Each script within `file_utils` is designed to be run from the command line. Refer to the individual script files for detailed argument usage (e.g., `python file_manager.py --help` or `python file_utils.py --help`). For the lister/replace CLI, use one of the installed entry points, e.g. `fsu -h`.

Example of `file_manager.py` usage (finding and deleting duplicates):
```bash
python -m modules.file_utils.file_manager --dir /path/to/my/files --use-hashes --dry-run
```

Example of `file_utils.py` usage (merging log files):
```bash
python -m modules.file_utils.file_utils /var/log/nginx --glob_pattern "access.log*" --output_file merged_access.log --include_headers
```
