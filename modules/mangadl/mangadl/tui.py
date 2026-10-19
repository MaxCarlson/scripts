from __future__ import annotations

import sys
from typing import Optional, Sequence

from cli_tui import CliTuiApp, introspect_parser
from .cli import build_parser


def build_tui_app() -> CliTuiApp:
    """Build a configured CliTuiApp for MangaDL."""
    parser = build_parser()
    root_cmd = introspect_parser(parser)

    # Exclude 'tui' subcommand from the interactive menu
    filtered_subcommands = {
        name: sub_cmd for name, sub_cmd in root_cmd.subcommands.items() if name != "tui"
    }
    cleaned_root = root_cmd.__class__(
        name="mangadl",
        prog="mangadl",
        description=root_cmd.description,
        help=root_cmd.help,
        epilog=root_cmd.epilog,
        arguments=root_cmd.arguments,
        subcommands=filtered_subcommands,
        subparsers_dest=root_cmd.subparsers_dest,
    )

    return CliTuiApp(
        root_command=cleaned_root,
        title="MangaDL Interactive Dashboard",
        executable=[sys.executable, "-m", "mangadl"],
    )


def launch_tui(argv: Optional[Sequence[str]] = None) -> int:
    """Launch the MangaDL interactive terminal user interface."""
    app = build_tui_app()
    return app.run()
