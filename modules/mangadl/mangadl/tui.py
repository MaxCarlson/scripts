from __future__ import annotations

import sys
from typing import Optional, Sequence

from cli_tui import CliTuiApp, PostRunAction, introspect_parser
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

    app = CliTuiApp(
        root_command=cleaned_root,
        title="MangaDL Interactive Dashboard",
        executable=[sys.executable, "-m", "mangadl"],
    )

    def _is_preview_finished(a: CliTuiApp) -> bool:
        return (
            len(a.navigation.path) >= 2
            and a.navigation.path[-2:] == ["compress", "preview"]
            and (a.runner is not None and a.runner.exit_code == 0)
        )

    def _on_view_previews(a: CliTuiApp) -> None:
        destination = None
        if a.current_form:
            destination = a.current_form.get_value("destination")
        try:
            from cli_tui.image_viewer import launch_image_viewer

            launch_image_viewer(destination=destination)
        except ImportError:
            pass

    app.add_post_run_action(
        PostRunAction(
            key=ord("v"),
            label="[v] View Previews",
            callback=_on_view_previews,
            predicate=_is_preview_finished,
        )
    )

    return app


def launch_tui(argv: Optional[Sequence[str]] = None) -> int:
    """Launch the MangaDL interactive terminal user interface."""
    app = build_tui_app()
    return app.run()
