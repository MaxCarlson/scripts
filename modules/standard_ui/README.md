# Standard UI - Rich-based Console UI Framework

`standard_ui` is a Python module that provides a standardized and visually appealing framework for console output, built upon the powerful `rich` library. It aims to offer consistent logging, progress reporting, and structured output across various scripts and modules, enhancing user experience and readability.

## Features

*   **Standardized Logging**: Provides `log_info`, `log_warning`, `log_error`, and `log_success` functions for consistent message formatting and coloring.
*   **Global Timer**: Tracks overall script execution time with `init_timer` and `print_global_elapsed`.
*   **Verbose Mode**: Allows suppressing `log_info` messages when verbosity is not desired.
*   **Section Context Manager**: The `section` context manager automatically prints bold headers and concise footers with elapsed time for logical blocks of operations.
*   **Structured Output**: Functions for printing formatted tables (`print_table`) and panels (`print_panel`).
*   **Progress Bars**: A `progress_bar` context manager for displaying minimal progress indicators for tasks.
*   **Command Execution Status**: `run_cmd_status` executes shell commands with a transient spinner, providing visual feedback.
*   **Argument Printing**: `print_parsed_args` neatly displays command-line arguments passed to a script.
*   **Compact Phases & Summary**: A `Phase` and `SetupSession` system for organizing multi-step processes and generating a concise end-of-run summary (similar to CMake output).
*   **Helper Functions**: Includes utilities like `blank` (print blank lines), `status_line` (print subtle status messages), `rule` (print horizontal rules), and `term_width` (get terminal width).

## Core Components

*   **`Console`**: The underlying `rich` console instance, configured with a custom theme for consistent styling.
*   **Logging Functions**: `log_info`, `log_warning`, `log_error`, `log_success`, `log_step`.
*   **`section` Context Manager**: For grouping related operations with clear start/end markers and elapsed time.
*   **`progress_bar` Context Manager**: For displaying task progress.
*   **`Phase` and `SetupSession`**: Classes for managing and summarizing multi-step processes, providing `ok`, `warn`, and `fail` statuses for individual steps.

## Installation

(Assuming Python 3 and `pip` are installed)

```bash
# Navigate to the module directory
cd /data/data/com.termux/files/home/scripts/modules/standard_ui

# Install required libraries
pip install rich
```

## Usage Examples

### Basic Logging

```python
from standard_ui import log_info, log_warning, log_error, log_success, set_verbose

set_verbose(True)
log_info("This is an informational message.")
log_warning("This is a warning message.")
log_error("This is an error message.")
log_success("This operation was successful!")
```

### Using Sections

```python
from standard_ui import section
import time

with section("Data Processing"):
    log_info("Starting data import...")
    time.sleep(1)
    log_info("Data imported.")

with section("Report Generation"):
    log_info("Generating PDF report...")
    time.sleep(2)
    log_success("Report generated.")
```

### Progress Bar

```python
from standard_ui import progress_bar
import time

with progress_bar("Downloading files", total=100) as (progress, task_id):
    for i in range(100):
        time.sleep(0.05)
        progress.update(task_id, advance=1)
```

### Setup Session and Phases

```python
from standard_ui import SetupSession, print_run_summary
import time

session = SetupSession(name="Project Build")

with session.phase("Dependency Check") as p:
    p.step("Checking Python version").ok()
    p.step("Checking required libraries").warn("Some libraries missing")

with session.phase("Code Compilation") as p:
    p.step("Compiling main module").ok()
    p.step("Compiling tests").fail("Syntax error in test_a.py")

print_run_summary(session)
```
