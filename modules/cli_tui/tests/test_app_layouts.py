from __future__ import annotations

import argparse
from pathlib import Path

from cli_tui import CliTuiApp


def make_app(layout_dir: Path, launch_dir: Path) -> CliTuiApp:
    parser = argparse.ArgumentParser(prog="layout-test")
    parser.add_argument("--value", default="before")
    return CliTuiApp(
        parser=parser,
        title="Layout Test",
        executable=["layout-test"],
        layout_dir=layout_dir,
        launch_dir=launch_dir,
    )


def test_quit_can_save_and_next_app_restores_pane_descriptors_without_running_jobs(tmp_path: Path) -> None:
    layout_dir = tmp_path / "layouts"
    launch_dir = tmp_path / "project"
    launch_dir.mkdir()
    app = make_app(layout_dir, launch_dir)
    app.workspace.active_pane.title = "Saved pane"
    app.workspace.create_pane(title="Second pane")
    app.workspace.switch_to(0)

    app.process_key(ord("q"))
    app.process_key(ord("y"))
    assert app.is_terminated is False
    assert app.is_confirming_layout_save is True
    app.process_key(ord("y"))
    assert app.is_terminated is True
    app.close()

    restored = make_app(layout_dir, launch_dir)
    assert [pane.title for pane in restored.workspace.panes] == ["Saved pane", "Second pane"]
    assert restored.workspace.active_index == 0
    assert all(pane.runner is None for pane in restored.workspace.panes)
    restored.close()


def test_manual_layout_save_and_restore_is_scoped_by_app_and_root(tmp_path: Path) -> None:
    layout_dir = tmp_path / "layouts"
    root = tmp_path / "root"
    root.mkdir()
    app = make_app(layout_dir, root)
    app.workspace.active_pane.title = "One"

    app.process_key(19)  # Ctrl+S

    assert app.last_message == "Pane layout saved"
    assert [pane.title for pane in make_app(layout_dir, root).workspace.panes] == ["One"]
    assert [pane.title for pane in make_app(layout_dir, tmp_path).workspace.panes] == ["Layout Test"]

def test_form_values_restore_and_running_output_is_viewed_without_relaunch(tmp_path: Path) -> None:
    layout_dir = tmp_path / "layouts"
    root = tmp_path / "root"
    root.mkdir()
    first = make_app(layout_dir, root)
    first._open_form_for_command(first.root_command)
    first.current_form.set_value("value", "after")
    first.navigation.current_screen = first.screen_mode.FORM

    class FinishedRunner:
        lines = ["saved output"]
        is_running = False
        exit_code = 0
        elapsed_seconds = 1.0

    first.runner = FinishedRunner()
    first.navigation.current_screen = first.screen_mode.RUNNING
    first.process_key(19)

    restored = make_app(layout_dir, root)
    assert restored.current_form is not None
    assert restored.current_form.get_value("value") == "after"
    assert restored.screen_mode.name == "RUNNING"
    assert restored.runner is not None
    assert restored.runner.lines == ["saved output"]
    assert getattr(restored.runner, "restored", False)
    restored.close()


def test_ctrl_o_capture_dialog_saves_active_pane_output(tmp_path: Path) -> None:
    import sys

    from cli_tui.process_runner import ProcessRunner

    root = tmp_path / "root"
    root.mkdir()
    app = make_app(tmp_path / "layouts", root)
    runner = ProcessRunner([sys.executable, "-c", "print('pane text')"])
    runner.start()
    runner.wait(timeout=5)
    app.runner = runner
    app.navigation.current_screen = app.screen_mode.RUNNING

    assert app.process_key(15) is True  # Ctrl+O
    assert "Capture Pane Output" in "\n".join(app.render_virtual_screen())
    app.output_capture_directory = str(tmp_path)
    app.output_capture_filename = "captured.log"
    app.process_key(13)  # Continue from directory to filename.
    app.process_key(13)  # Start capture.
    app.close()

    assert (tmp_path / "captured.log").read_text(encoding="utf-8") == "pane text\n"

def test_viewport_state_restores_for_each_pane(tmp_path: Path) -> None:
    root = tmp_path / "project"
    root.mkdir()
    layout_dir = tmp_path / "layouts"
    app = make_app(layout_dir, root)
    app.workspace.active_pane.viewport.scroll_offset = 7
    app.workspace.active_pane.viewport.auto_scroll = False
    app.process_key(19)

    restored = make_app(layout_dir, root)

    assert restored.workspace.active_pane.viewport.scroll_offset == 7
    assert restored.workspace.active_pane.viewport.auto_scroll is False
    restored.close()


def test_console_pane_cwd_and_history_restore(tmp_path: Path) -> None:
    from cli_tui.console_pane import ConsolePaneRunner
    from cli_tui.state import PaneType

    root = tmp_path / "project"
    root.mkdir()
    layout_dir = tmp_path / "layouts"
    app = make_app(layout_dir, root)
    pane = app.workspace.create_pane(title="Shell", pane_type=PaneType.CONSOLE)
    pane.runner = ConsolePaneRunner(cwd=str(root))
    pane.runner.history_lines.append("kept console output")
    app.process_key(19)

    restored = make_app(layout_dir, root)
    console_pane = restored.workspace.panes[1]
    assert console_pane.pane_type == PaneType.CONSOLE
    assert console_pane.runner.cwd == str(root)
    assert "kept console output" in console_pane.runner.lines
    restored.close()


def test_failed_save_on_exit_keeps_prompt_open_for_retry(tmp_path: Path, monkeypatch) -> None:
    root = tmp_path / "project"
    root.mkdir()
    app = make_app(tmp_path / "layouts", root)
    app.process_key(ord("q"))
    app.process_key(ord("y"))
    monkeypatch.setattr(app.layout_store, "save", lambda *args: (_ for _ in ()).throw(OSError("disk full")))

    app.process_key(ord("y"))

    assert app.is_confirming_layout_save is True
    assert app.is_terminated is False
    assert "Could not save pane layout" in "\n".join(app.render_virtual_screen())

def test_deleting_pane_stops_runner_before_closing_output_capture(tmp_path: Path) -> None:
    from cli_tui.state import PaneType

    app = make_app(tmp_path / "layouts", tmp_path)
    pane = app.workspace.create_pane(title="Captured", pane_type=PaneType.COMMAND)
    events = []

    class Runner:
        def stop(self):
            events.append("stop")

        def wait(self, timeout=None):
            events.append("wait")

    class Capture:
        def close(self):
            events.append("capture-close")

    pane.runner = Runner()
    pane.extra_data["output_capture"] = Capture()
    app.is_pane_manager_open = True
    app.manager_cursor = 1
    app.process_key(ord("d"))

    assert events == ["stop", "wait", "capture-close"]

def test_malformed_layout_fields_are_safely_defaulted(tmp_path: Path) -> None:
    from cli_tui.layout_store import PaneLayoutStore

    root = tmp_path / "root"
    root.mkdir()
    store = PaneLayoutStore(tmp_path / "layouts")
    store.save(
        str(root),
        "layout-test",
        {"panes": [{"type": "console", "console_cwd": [], "form_cursor": "bad"}], "active_index": "bad"},
    )

    app = make_app(tmp_path / "layouts", root)

    assert len(app.workspace.panes) == 1
    assert app.workspace.active_pane.title == "Main"
    assert app.workspace.active_pane.runner.cwd == str(Path.cwd())
