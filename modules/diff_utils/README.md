# diff_utils Module

The `diff_utils` module provides a suite of tools for comparing files and directories, with specialized functionalities for Python code analysis and general directory synchronization. It aims to offer robust and flexible comparison capabilities for various use cases.

## Purpose

To offer a set of utilities for:
*   Comparing the structure, content, and metadata of two directories.
*   Identifying differences in Python code at the class, method, and function level.
*   Automating synchronization, copying, or deletion tasks based on comparison results.
*   Providing detailed and customizable reports of differences.

## Key Files and Classes

*   **`__init__.py`**: The package initializer, which exposes the `DirectoryDiff` class and defines the package version.

*   **`diff.py`**: This is the primary command-line interface (CLI) script for performing directory comparisons. It parses a wide range of arguments, allowing users to configure the comparison process with options such as:
    *   **Presets**: Predefined configurations (e.g., `basic`, `deep`, `sync-check`).
    *   **Ignore Patterns**: Exclude specific files or directories from comparison.
    *   **Dry Run**: Simulate actions without making actual changes.
    *   **Output Formats**: Display results in plain text, JSON, or colored output.
    *   **Checksum Algorithms**: Specify the algorithm for content comparison (e.g., MD5).
    *   **Case Sensitivity & Symlink Following**: Control comparison behavior.
    *   **Time Tolerance**: Allow for minor differences in modification times.
    *   **Operation Modes**: Perform `diff` (report only), `sync` (copy missing from source to destination), `copy` (update differing files in destination), or `delete` (delete identical source files).

*   **`dir_diff.py` (Class: `DirectoryDiff`)**: Implements the core logic for comparing two directories. It scans the directory structures, applies ignore filters, computes file checksums, and compares file content and metadata. It then populates a `diff_result` dictionary with lists of items that are only in the source, only in the destination, common to both, or have content/metadata differences. It also contains methods to `perform_actions` based on the chosen operation mode.

*   **`python_diff.py`**: A specialized CLI tool for comparing two Python files. It leverages Python's `ast` (Abstract Syntax Tree) module to perform a structural comparison, reporting differences in:
    *   **Classes**: Which classes are present in one file but not the other.
    *   **Methods**: Which member functions are missing within common classes.
    *   **Top-level Functions**: Which functions are present in one file but not the other.
    *   **Function Signatures**: Optionally, it can compare function and method signatures (based on argument names) to detect changes in API. It uses `standard_ui` for formatted output.

## Functionality Highlights

*   **Comprehensive Directory Comparison**: Beyond simple file presence, it delves into content and metadata differences.
*   **Flexible Filtering**: Allows fine-grained control over what is included or excluded from comparisons.
*   **Actionable Results**: Enables direct execution of synchronization, copy, or deletion operations based on the detected differences.
*   **Python Code Specific Analysis**: Provides a unique capability to understand structural changes within Python source files, which is more insightful than a line-by-line text diff for code.

## Dependencies

*   `cross_platform.debug_utils` and `cross_platform.system_utils`: Used by `diff.py` and `dir_diff.py` for logging and system interactions.
*   `standard_ui`: Used by `python_diff.py` for consistent and formatted console output.

## Usage

Each script within `diff_utils` is designed to be run from the command line. Refer to the individual script files for detailed argument usage (e.g., `python diff.py --help` or `python python_diff.py --help`).

Example of `diff.py` usage:
```bash
python diff.py --source /path/to/dir1 --destination /path/to/dir2 --preset deep --output-format colored
```

Example of `python_diff.py` usage:
```bash
python python_diff.py --file1 my_module_v1.py --file2 my_module_v2.py --fn-signature
```
