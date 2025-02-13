"""
standard_ui.py

A standardized UI framework for console output across your modules.
Built on Rich, it provides:
  - Standard logging functions: log_info, log_warning, log_error, log_success.
  - A section context manager (section) to print headers/footers with elapsed time.
  - Global timer utilities to track overall runtime.
  - Helper functions to print tables, panels, and steps.
  - (Planned) Progress bar helpers for in-place or transient progress display.
"""

import time
from contextlib import contextmanager
from rich.console import Console
from rich.rule import Rule
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

# Create a single Console instance for consistent output.
console = Console()

# Global configuration and timer
VERBOSE = True
_global_start_time = None

# ------------------ Global Timer Utilities ------------------ #

def init_timer():
    """Initialize the global timer. Call this once at the very start."""
    global _global_start_time
    _global_start_time = time.time()

def print_global_elapsed():
    """Print the elapsed time since the global timer was initialized."""
    if _global_start_time is None:
        init_timer()
    elapsed = time.time() - _global_start_time
    console.print(f"[bold magenta]Overall Elapsed Time: {elapsed:.2f} sec[/]")

# ------------------ Logging Functions ------------------ #

def set_verbose(verbose: bool):
    """Set the global verbosity flag."""
    global VERBOSE
    VERBOSE = verbose

def log_info(message: str):
    console.print(f"[bold cyan]\u2139  {message}[/]")

def log_warning(message: str):
    console.print(f"[bold yellow]⚠️ {message}[/]")

def log_error(message: str):
    console.print(f"[bold red]❌ {message}[/]")

def log_success(message: str):
    console.print(f"[bold green]✅ {message}[/]")

# ------------------ Section Markers with Timing ------------------ #

@contextmanager
def section(title: str):
    """
    Context manager for a setup/install section.
    It prints a header with the section title and, when finished,
    prints a footer showing the elapsed time for that section.
    """
    start_time = time.time()
    console.rule(f"[bold blue]{title} - START[/]")
    try:
        yield
    finally:
        elapsed = time.time() - start_time
        console.rule(f"[bold blue]{title} - END (Elapsed: {elapsed:.2f} sec)[/]")
        console.print()

def print_section_header(title: str):
    """Print a section header without a footer."""
    console.rule(f"[bold blue]{title}[/]", style="blue")

def print_section_footer(title: str = "END"):
    """Print a section footer."""
    console.rule(f"[bold blue]{title}[/]", style="blue")

# ------------------ Step Logging ------------------ #

def log_step(message: str):
    """
    Log a step message along with a timestamp (relative to the global timer).
    """
    if _global_start_time is None:
        init_timer()
    elapsed = time.time() - _global_start_time
    console.print(f"[bold white]{message}[/] [dim](+{elapsed:.2f} sec)[/]")

# ------------------ Formatting Helpers ------------------ #

def print_table(columns: list, rows: list):
    """
    Print a table with the given columns and rows.
    :param columns: List of column header strings.
    :param rows: List of rows, where each row is a list of cell values.
    """
    table = Table(show_header=True, header_style="bold magenta")
    for col in columns:
        table.add_column(col)
    for row in rows:
        table.add_row(*[str(cell) for cell in row])
    console.print(table)

def print_panel(message: str, title: str = "", style: str = "green"):
    """
    Print a message inside a styled panel.
    """
    panel = Panel(message, title=title, style=style, expand=False)
    console.print(panel)

# ------------------ (Planned) Progress Bar Helper ------------------ #
# This section can be expanded later with Rich's Progress functionality.
# For now, a placeholder function is provided.
def progress_bar(task_description: str, total: int):
    """
    (Planned) Return a progress bar context manager for a given task.
    To be implemented later.
    """
    console.print(f"[bold blue]Progress for: {task_description} (Total: {total})[/]")

# ------------------ Argument Printer (Optional) ------------------ #

def print_parsed_args(args):
    """
    Given an argparse.Namespace, print the script name/path and all argument names with their values
    in a clean, formatted table.
    """
    from rich.table import Table
    import sys
    from pathlib import Path

    script_path = Path(sys.argv[0]).resolve()
    console.rule(f"[bold blue]Script: {script_path}[/]")
    table = Table(show_header=True, header_style="bold magenta")
    table.add_column("Argument")
    table.add_column("Value", overflow="fold")
    args_dict = vars(args)
    for key, value in sorted(args_dict.items()):
        table.add_row(key, str(value))
    console.print(table)
    console.rule()

# ------------------ Example Usage ------------------ #
if __name__ == "__main__":
    # For demonstration purposes:
    init_timer()
    log_info("Starting the setup process...")
    
    with section("Initialization"):
        log_info("Loading configuration...")
        time.sleep(1.2)
        log_info("Configuration loaded.")
    
    log_step("Finished initialization step.")
    
    with section("Installation"):
        log_info("Installing module A...")
        time.sleep(0.8)
        log_success("Module A installed.")
        log_info("Installing module B...")
        time.sleep(1.5)
        log_success("Module B installed.")
    
    print_global_elapsed()
    log_info("Setup process complete.")
