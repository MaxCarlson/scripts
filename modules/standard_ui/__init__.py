# File: modules/standard_ui/__init__.py
"""
standard_ui package

This package provides a standardized UI framework for console output,
built on Rich, including logging functions, section markers, timer utilities,
and formatting helpers.
"""

from .standard_ui import (
    # Existing, preserved API
    init_timer,
    print_global_elapsed,
    set_verbose,
    log_info,
    log_warning,
    log_error,
    log_success,
    section,
    print_section_header,
    print_section_footer,
    log_step,
    print_table,
    print_panel,
    progress_bar,
    print_parsed_args,

    # New, optional higher-level helpers (non-breaking additions)
    SetupSession,
    Phase,
    run_cmd_status,
    print_run_summary,
)

__all__ = [
    # Existing
    "init_timer",
    "print_global_elapsed",
    "set_verbose",
    "log_info",
    "log_warning",
    "log_error",
    "log_success",
    "section",
    "print_section_header",
    "print_section_footer",
    "log_step",
    "print_table",
    "print_panel",
    "progress_bar",
    "print_parsed_args",
    # New
    "SetupSession",
    "Phase",
    "run_cmd_status",
    "print_run_summary",
]
