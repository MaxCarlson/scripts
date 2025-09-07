# code_tools Module

The `code_tools` module provides a suite of utilities designed to enhance code manipulation, analysis, and search workflows. It offers language-aware functionalities for extracting, replacing, and validating code blocks, and integrates with external tools like `ripgrep` for powerful code exploration.

## Purpose

To offer a collection of specialized tools for developers and power users to:
*   Programmatically interact with code files.
*   Extract meaningful code blocks from various programming languages and data formats.
*   Automate code refactoring tasks.
*   Perform advanced code searches with contextual output.
*   Identify common syntax errors related to brace matching.

## Key Files and Submodules

*   **`__init__.py`**: The package initializer, exposing the main components of the `code_tools` module.

*   **`func_replacer.py`**: A script that enables the replacement of specific code entities (functions, classes, or general blocks) within a target file. It intelligently identifies the block to be replaced, handles indentation, and can create backups of the original file. It relies on the `rgcodeblock_lib` for its language-aware block detection capabilities.

*   **`rgcodeblock_cli.py`**: A command-line interface tool that extends the functionality of `ripgrep` (`rg`). For every match found by `ripgrep`, this tool attempts to extract and display the entire enclosing code block (e.g., the function, class, or JSON object) where the match occurred. It supports syntax highlighting of the matched text and provides language-specific extraction logic.

*   **`rgcodeblock_lib/`**: A core subpackage containing the foundational logic for language-aware code analysis.
    *   **`rgcodeblock_lib/__init__.py`**: Exposes the key components of the `rgcodeblock_lib` for use by other scripts.
    *   **`rgcodeblock_lib/extractors.py`**: Implements various strategies for extracting code blocks based on programming language. This includes AST (Abstract Syntax Tree) parsing for Python, brace counting for C-style languages, and specialized logic for JSON, YAML, XML, Ruby, and Lua. It defines the `Block` dataclass to represent extracted code segments.
    *   **`rgcodeblock_lib/language_defs.py`**: Contains definitions for various programming languages, mapping file extensions to language types and providing metadata about their block extraction methods.

*   **`unpaired_finder.py`**: A utility script designed to scan text files for unpaired or mismatched braces (`{}`, `[]`, `()`). It reports the line and column numbers of any detected issues, helping to quickly pinpoint syntax errors.

## Functionality Highlights

*   **Language-Aware Code Block Extraction**: Automatically identifies and extracts logical code units (functions, classes, JSON objects, XML elements, etc.) based on the file type.
*   **Code Block Replacement**: Facilitates precise modification of code files by replacing identified blocks with new content.
*   **Contextual Code Search**: Enhances `ripgrep` results by showing the full code block surrounding a match, providing immediate context.
*   **Syntax Validation**: Helps in debugging by locating unpaired or mismatched braces in code or configuration files.

## Dependencies

*   **`ripgrep` (`rg`)**: Required for `rgcodeblock_cli.py` to perform fast, pattern-based code searches.
*   **`pyperclip` (optional)**: Used by `func_replacer.py` to read new code content directly from the system clipboard. If not installed, content must be provided via a file.
*   **`PyYAML` (optional)**: Required by `rgcodeblock_lib/extractors.py` for robust YAML code block extraction. If not installed, YAML processing will be limited or skipped.
*   **`lxml` (optional)**: Required by `rgcodeblock_lib/extractors.py` for robust XML code block extraction. If not installed, XML processing will be limited or skipped.

## Usage

Each script within `code_tools` is designed to be run from the command line. Refer to the individual script files for detailed argument usage (e.g., `python func_replacer.py --help`).

Example of `rgcodeblock_cli.py` usage:
```bash
rgcodeblock_cli "my_function" src/my_module.py
```

Example of `func_replacer.py` usage:
```bash
# Replace 'my_function' in 'my_file.py' with content from 'new_code.py'
func_replacer my_file.py -s new_code.py -n my_function
```
