from __future__ import annotations

import argparse

from cli_tui.app import CliTuiApp
from cli_tui.state import PaneType, TuiScreenMode


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="layout-tool")
    commands = parser.add_subparsers(dest="command")
    build = commands.add_parser("build")
    build.add_argument("--target", default="all")
    commands.add_parser("status")
    return parser


def test_layout_round_trip_restores_forms_console_and_active_pane(tmp_path) -> None:
    launch_dir = tmp_path / "project"
    launch_dir.mkdir()
    config_dir = tmp_path / "config"
    app = CliTuiApp(
        parser=_parser(),
        layout_dir=config_dir,
        launch_dir=launch_dir,
        layout_id="layout-tool",
    )
    app.process_key(10)
    app.current_form.set_value("target", "release")
    app.workspace.active_pane.extra_data["form_cursor"] = 1
    console = app.workspace.create_pane(title="Shell", pane_type=PaneType.CONSOLE)
    console.runner = __import__(
        "cli_tui.console_pane", fromlist=["ConsolePaneRunner"]
    ).ConsolePaneRunner(cwd=str(launch_dir))
    console.screen_mode = TuiScreenMode.RUNNING
    app.workspace.active_index = 1

    assert app.save_layout() is True

    restored = CliTuiApp(
        parser=_parser(),
        layout_dir=config_dir,
        launch_dir=launch_dir,
        layout_id="layout-tool",
    )

    assert len(restored.workspace.panes) == 2
    assert restored.workspace.active_index == 1
    assert restored.workspace.panes[0].current_form is not None
    assert restored.workspace.panes[0].current_form.get_value("target") == "release"
    assert restored.workspace.panes[0].runner is None
    assert restored.workspace.panes[1].pane_type == PaneType.CONSOLE
    assert restored.workspace.panes[1].runner.cwd == str(launch_dir)


def test_layout_isolated_by_app_and_launch_directory(tmp_path) -> None:
    project = tmp_path / "project"
    other_project = tmp_path / "other"
    project.mkdir()
    other_project.mkdir()
    options = {"layout_dir": tmp_path / "config", "layout_id": "one"}
    app = CliTuiApp(parser=_parser(), launch_dir=project, **options)
    app.workspace.create_pane(title="Extra")
    assert app.save_layout()

    different_app = CliTuiApp(
        parser=_parser(),
        launch_dir=project,
        layout_id="two",
        layout_dir=options["layout_dir"],
    )
    different_dir = CliTuiApp(
        parser=_parser(),
        launch_dir=other_project,
        layout_id="one",
        layout_dir=options["layout_dir"],
    )

    assert len(different_app.workspace.panes) == 1
    assert len(different_dir.workspace.panes) == 1


def test_normal_quit_asks_whether_to_save_and_q_force_quits(tmp_path) -> None:
    app = CliTuiApp(parser=_parser(), layout_dir=tmp_path, layout_id="tool")
    app.process_key(ord("q"))
    app.process_key(ord("y"))
    assert app.is_asking_save_layout
    assert not app.is_terminated

    app.process_key(ord("n"))
    assert app.is_terminated
    assert not app.layout_store.path.exists()

    force_quit = CliTuiApp(parser=_parser(), layout_dir=tmp_path, layout_id="other")
    force_quit.process_key(ord("Q"))
    assert force_quit.is_terminated
    assert not force_quit.is_asking_save_layout


def test_ctrl_o_saves_retained_output_and_streams_future_chunks(tmp_path) -> None:
    from collections import deque

    from cli_tui.process_runner import ProcessRunner

    app = CliTuiApp(
        parser=_parser(),
        layout_dir=tmp_path / "config",
        launch_dir=tmp_path,
        layout_id="capture-tool",
    )
    runner = ProcessRunner(["not-started"])
    runner._lines = deque(["retained"])
    app.workspace.active_pane.runner = runner
    app.workspace.active_pane.screen_mode = TuiScreenMode.RUNNING
    app.workspace.active_pane.navigation.current_screen = TuiScreenMode.RUNNING

    app.process_key(15)  # Ctrl+O
    assert app.is_output_dialog_open
    app.process_key(10)  # Save with the suggested path
    destination = tmp_path / "layout-tool.log"
    assert destination.read_text(encoding="utf-8") == "retained\n"

    runner._dispatch_output("future\n")
    app.close()
    assert destination.read_text(encoding="utf-8") == "retained\nfuture\n"


def test_output_save_dialog_confirms_overwrite_and_validates_directory(
    tmp_path,
) -> None:
    destination = tmp_path / "layout-tool.log"
    destination.write_text("old", encoding="utf-8")
    app = CliTuiApp(
        parser=_parser(),
        layout_dir=tmp_path / "config",
        launch_dir=tmp_path,
        layout_id="overwrite-tool",
    )

    app.process_key(15)
    app.process_key(10)
    assert app.is_output_overwrite_pending
    app.process_key(ord("y"))
    assert not app.is_output_dialog_open
    assert destination.read_text(encoding="utf-8") == ""


def test_console_capture_includes_retained_history_and_future_builtins(
    tmp_path,
) -> None:
    from cli_tui.console_pane import ConsolePaneRunner

    app = CliTuiApp(
        parser=_parser(),
        layout_dir=tmp_path / "config",
        launch_dir=tmp_path,
        layout_id="console-capture",
    )
    pane = app.workspace.active_pane
    pane.title = "Shell Console"
    pane.pane_type = PaneType.CONSOLE
    pane.screen_mode = TuiScreenMode.RUNNING
    console = ConsolePaneRunner(cwd=str(tmp_path))
    console.history_lines.append("previous history")
    pane.runner = console

    app.process_key(15)
    app.process_key(10)
    destination = tmp_path / "Shell_Console.log"
    assert "previous history" in destination.read_text(encoding="utf-8")

    console.execute_line("cd .")
    app.close()
    output = destination.read_text(encoding="utf-8")
    assert f"[{tmp_path}]> cd ." in output
    assert "Directory changed to:" in output


def test_invalid_saved_pane_is_skipped_with_nonfatal_notice(tmp_path) -> None:
    app = CliTuiApp(
        parser=_parser(),
        layout_dir=tmp_path / "config",
        launch_dir=tmp_path,
        layout_id="invalid-layout",
    )
    app.workspace.create_pane(title="extra")
    assert app.save_layout()
    payload = app.layout_store.load()
    payload["panes"][0]["navigation_path"] = ["removed-command"]
    app.layout_store.save(payload)

    restored = CliTuiApp(
        parser=_parser(),
        layout_dir=tmp_path / "config",
        launch_dir=tmp_path,
        layout_id="invalid-layout",
    )
    assert len(restored.workspace.panes) == 1
    assert (
        "invalid" in restored.layout_notice.lower()
        or "skipped" in restored.layout_notice.lower()
    )


def test_normal_quit_can_save_then_exit(tmp_path) -> None:
    app = CliTuiApp(
        parser=_parser(),
        layout_dir=tmp_path,
        launch_dir=tmp_path,
        layout_id="save-on-exit",
    )
    app.workspace.create_pane(title="extra")
    app.process_key(ord("q"))
    app.process_key(ord("y"))
    assert app.is_asking_save_layout

    app.process_key(ord("y"))
    assert app.is_terminated
    assert app.layout_store.path.exists()


def test_save_on_exit_failure_offers_retry_or_exit_without_saving(tmp_path) -> None:
    from cli_tui.layout_store import LayoutError

    app = CliTuiApp(
        parser=_parser(),
        layout_dir=tmp_path,
        launch_dir=tmp_path,
        layout_id="save-error",
    )
    app.process_key(ord("q"))
    app.process_key(ord("y"))
    app.layout_store.save = lambda _payload: (_ for _ in ()).throw(
        LayoutError("disk full")
    )
    app.process_key(ord("y"))

    assert app.is_layout_save_error
    assert not app.is_terminated
    assert "disk full" in "\n".join(app.render_virtual_screen())

    app.process_key(ord("q"))
    assert app.is_terminated
