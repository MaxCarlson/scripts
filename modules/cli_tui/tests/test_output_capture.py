from pathlib import Path

from cli_tui.output_capture import OutputFileCapture


def test_output_capture_writes_initial_snapshot_and_later_chunks(tmp_path: Path) -> None:
    target = tmp_path / "pane.log"
    capture = OutputFileCapture(target)
    capture.write_snapshot(["existing", ""])
    capture.write_chunk("future\n")
    capture.close()

    assert target.read_text(encoding="utf-8") == "existing\n\nfuture\n"


def test_output_capture_refuses_overwrite_by_default(tmp_path: Path) -> None:
    target = tmp_path / "pane.log"
    target.write_text("keep", encoding="utf-8")

    try:
        OutputFileCapture(target)
    except FileExistsError:
        pass
    else:
        raise AssertionError("capture must not overwrite a file without explicit approval")

    assert target.read_text(encoding="utf-8") == "keep"

def test_capture_attaches_before_process_start_and_receives_future_utf8_output(tmp_path: Path) -> None:
    import sys

    from cli_tui.process_runner import ProcessRunner

    target = tmp_path / "stream.log"
    capture = OutputFileCapture(target)
    runner = ProcessRunner([sys.executable, "-c", "print('first'); print('snowman ☃')"])
    capture.attach(runner)
    runner.start()
    runner.wait(timeout=5)
    capture.close()

    assert target.read_text(encoding="utf-8") == "first\nsnowman ☃\n"

def test_capture_attaches_to_console_pane_snapshot_and_live_command(tmp_path: Path) -> None:
    import sys
    import time

    from cli_tui.console_pane import ConsolePaneRunner
    from cli_tui.process_runner import ProcessRunner

    console = ConsolePaneRunner(cwd=str(tmp_path))
    console.history_lines.append("earlier console output")
    console.active_runner = ProcessRunner(
        [sys.executable, "-c", "import time; print('live output', flush=True); time.sleep(0.15)"]
    )
    console.active_runner.start()
    target = tmp_path / "console.log"
    capture = OutputFileCapture(target)
    capture.attach(console)
    console.active_runner.wait(timeout=5)
    time.sleep(0.02)
    capture.close()

    text = target.read_text(encoding="utf-8")
    assert "earlier console output" in text
    assert "live output" in text

def test_capture_started_on_idle_console_follows_later_commands(tmp_path: Path) -> None:
    from cli_tui.console_pane import ConsolePaneRunner

    console = ConsolePaneRunner(cwd=str(tmp_path))
    target = tmp_path / "later.log"
    capture = OutputFileCapture(target)
    capture.attach(console)
    console.execute_line("echo later-output")
    console.wait(timeout=5)
    capture.close()

    assert "later-output" in target.read_text(encoding="utf-8")
