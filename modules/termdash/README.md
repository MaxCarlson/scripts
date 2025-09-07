# TermDash - Terminal Dashboard Library

TermDash is a robust, thread-safe Python library designed for creating persistent, multi-line, in-place terminal dashboards. It allows for dynamic display of information with a co-existing scrolling log region, making it ideal for monitoring long-running processes or real-time data.

## Features

*   **In-place Rendering**: Updates content directly in the terminal without continuous scrolling.
*   **Multi-line Display**: Organize information across multiple lines.
*   **Thread-Safe**: Designed for concurrent updates from different threads.
*   **Column Alignment**: Automatically aligns columns across all dashboard lines for readability.
*   **Customizable Components**:
    *   `Stat`: A single named metric with formatting and coloring options.
    *   `Line`: A collection of `Stat` objects, forming a single row in the dashboard.
    *   `AggregatedLine`: Aggregates numeric stats from multiple source `Line` objects.
*   **Terminal Resizing**: Gracefully handles terminal window resizing.
*   **Logging Integration**: Can integrate with Python's logging system to display log messages alongside the dashboard.
*   **Utility Functions**: Includes helpers for human-readable byte formatting, time formatting (HH:MM:SS), and string clipping.

## Core Components

*   **`TermDash`**: The main class that manages the dashboard. It handles rendering, updates, and terminal interactions.
*   **`Line`**: Represents a single row in the dashboard, composed of `Stat` objects.
*   **`Stat`**: Represents a single data point or metric within a `Line`.
*   **`AggregatedLine`**: A specialized `Line` that can sum or average `Stat` values from other `Line` objects.

## Usage (Conceptual)

To use TermDash, you typically:

1.  Initialize a `TermDash` instance.
2.  Create `Stat` objects for your metrics.
3.  Group `Stat` objects into `Line` objects.
4.  Add `Line` objects to your `TermDash` instance.
5.  Start the dashboard context manager.
6.  Update `Stat` values as needed; TermDash will automatically re-render.

```python
# Example (conceptual)
from termdash import TermDash, Line, Stat
import time

with TermDash() as td:
    # Create stats
    cpu_stat = Stat("CPU", 0.0, format_string="{:.1f}%", color=lambda v: "0;32" if v < 80 else "0;31")
    mem_stat = Stat("Mem", 0.0, format_string="{:.1f}MiB")

    # Create a line
    system_line = Line("System", stats=[cpu_stat, mem_stat])

    # Add the line to the dashboard
    td.add_line("system_info", system_line)

    # Update stats in a loop
    for i in range(100):
        td.update_stat("system_info", "CPU", i * 0.5)
        td.update_stat("system_info", "Mem", i * 2.5)
        time.sleep(0.1)
```

## `ytdlp_parser.py`

This module provides a lightweight parser for `yt-dlp` console output. It's designed to extract structured information from the raw text output of `yt-dlp` downloads, such as metadata, progress, completion status, and errors. While not a core component of the dashboard rendering, it can be used as a utility to feed data into a TermDash dashboard for monitoring `yt-dlp` operations.
