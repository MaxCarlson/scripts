from __future__ import annotations

import sys
from typing import Optional, Sequence

from cli_tui import CliTuiApp, PostRunAction, introspect_parser
from .cli import build_parser


def build_tui_app() -> CliTuiApp:
    """Build a configured CliTuiApp for Compresser."""
    parser = build_parser()
    root_cmd = introspect_parser(parser)

    # Exclude 'tui' subcommand from the interactive menu to avoid recursion
    filtered_subcommands = {
        name: sub_cmd for name, sub_cmd in root_cmd.subcommands.items() if name != "tui"
    }
    cleaned_root = root_cmd.__class__(
        name="compresser",
        prog="compresser",
        description=root_cmd.description,
        help=root_cmd.help,
        epilog=root_cmd.epilog,
        arguments=root_cmd.arguments,
        subcommands=filtered_subcommands,
        subparsers_dest=root_cmd.subparsers_dest,
    )

    app = CliTuiApp(
        root_command=cleaned_root,
        title="Compresser Interactive Dashboard",
        executable=[sys.executable, "-m", "compresser"],
    )

    def _is_preview_finished(a: CliTuiApp) -> bool:
        return (
            len(a.navigation.path) >= 1
            and a.navigation.path[-1] == "preview"
            and (a.runner is not None and a.runner.exit_code == 0)
        )

    def _on_view_previews(a: CliTuiApp) -> None:
        destination = None
        if a.current_form:
            destination = a.current_form.get_value("input") or a.current_form.get_value("destination")
        try:
            from cli_tui.image_viewer import launch_image_viewer

            launch_image_viewer(destination=destination)
        except Exception:
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
    """Launch the Compresser interactive terminal user interface."""
    args = list(argv or [])
    if "-h" in args or "--help" in args:
        parser = build_parser()
        try:
            parser.parse_args(["tui", "--help"])
        except SystemExit:
            pass
        return 0

    try:
        import curses
    except (ImportError, ModuleNotFoundError):
        print(
            "Error: Interactive terminal user interface requires curses.\n"
            "On Windows, please install windows-curses ('pip install windows-curses').",
            file=sys.stderr,
        )
        return 1

    app = build_tui_app()
    return app.run()
