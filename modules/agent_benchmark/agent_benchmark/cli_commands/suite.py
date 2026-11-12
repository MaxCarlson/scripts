"""CLI definitions and handler for suite command group (delegates to suite_cli)."""

from __future__ import annotations

from ..suite_cli import add_suite_parser, handle_suite

__all__ = ["add_suite_parser", "handle_suite"]
