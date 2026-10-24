from pathlib import Path
import threading
import time

from cli_tui.output_capture import OutputFileCapture
from cli_tui.process_runner import ProcessRunner, VirtualTerminalBuffer


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


def test_output_capture_snapshot_precedes_subscribed_output(tmp_path: Path) -> None:
    target = tmp_path / "ordered.log"
    runner = ProcessRunner(["unused"])
    buffer = VirtualTerminalBuffer(max_lines=runner.max_lines)
    runner._accept_output("before\n", buffer)

    capture = OutputFileCapture(target)
    capture.attach(runner)
    runner._accept_output("after\n", buffer)
    capture.close()

    assert target.read_text(encoding="utf-8") == "before\nafter\n"


def test_output_capture_uses_a_bounded_pending_queue(tmp_path: Path) -> None:
    capture = OutputFileCapture(tmp_path / "bounded.log")
    try:
        assert 0 < capture._queue.maxsize <= 1024
    finally:
        capture.close()


def test_stalled_writer_stops_capture_without_blocking_the_output_producer(
    tmp_path: Path,
) -> None:
    target = tmp_path / "backpressure.log"
    capture = OutputFileCapture(target)
    entered_write = threading.Event()
    release_write = threading.Event()
    underlying_file = capture._file

    class SlowFile:
        def write(self, text: str) -> int:
            entered_write.set()
            assert release_write.wait(5)
            return underlying_file.write(text)

        def flush(self) -> None:
            underlying_file.flush()

        def close(self) -> None:
            underlying_file.close()

    capture._file = SlowFile()
    capture.write_chunk("first\n")
    assert entered_write.wait(2)

    def write_many() -> None:
        for index in range(capture._MAX_PENDING_CHUNKS + 4):
            capture.write_chunk(f"chunk-{index}\n")

    producer = threading.Thread(target=write_many)
    producer.start()
    started = time.monotonic()
    try:
        deadline = time.monotonic() + 2
        while capture._queue.qsize() < capture._queue.maxsize and time.monotonic() < deadline:
            time.sleep(0.005)
        assert capture._queue.qsize() == capture._queue.maxsize
        producer.join(timeout=0.5)
        assert not producer.is_alive()
        assert capture.active is False
        assert capture.error is not None
        assert time.monotonic() - started < 1
    finally:
        release_write.set()
        producer.join(timeout=5)
        capture.close()
        capture._writer.join(timeout=5)

    assert not producer.is_alive()
    assert not capture._writer.is_alive()


def test_stalled_capture_cannot_block_a_subprocess_or_app_shutdown(tmp_path: Path) -> None:
    import argparse
    import sys

    from cli_tui import CliTuiApp

    entered_write = threading.Event()
    release_write = threading.Event()
    reported = threading.Event()
    failures = []
    target = tmp_path / "stalled-process.log"
    capture = OutputFileCapture(
        target,
        on_error=lambda error: (failures.append(error), reported.set()),
    )
    underlying_file = capture._file

    class SlowFile:
        def write(self, text: str) -> int:
            entered_write.set()
            assert release_write.wait(10)
            return underlying_file.write(text)

        def flush(self) -> None:
            underlying_file.flush()

        def close(self) -> None:
            underlying_file.close()

    capture._file = SlowFile()
    app = CliTuiApp(parser=argparse.ArgumentParser(prog="stalled-capture"), layout_dir=tmp_path)
    app.workspace.active_pane.extra_data["output_capture"] = capture
    runner = ProcessRunner(
        [
            sys.executable,
            "-c",
            "import sys; chunk='x'*4095+'\\n'; "
            "[sys.stdout.write(chunk) for _ in range(512)]",
        ]
    )
    capture.attach(runner)
    runner.start()

    try:
        assert entered_write.wait(2)
        assert runner.wait(timeout=5) == 0
        assert reported.wait(2)
        assert failures
        started = time.monotonic()
        app.close()
        assert time.monotonic() - started < 1
    finally:
        release_write.set()
        runner.terminate()
        runner.wait(timeout=1)
        capture.close()
        capture._writer.join(timeout=5)
        app.close()

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
    time.sleep(0.05)
    target = tmp_path / "console.log"
    capture = OutputFileCapture(target)
    capture.attach(console)
    console.active_runner.wait(timeout=5)
    time.sleep(0.02)
    capture.close()

    text = target.read_text(encoding="utf-8")
    assert "earlier console output" in text
    assert text.count("live output") == 1

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


def test_output_capture_reports_writer_errors_and_stops_accepting_output(
    tmp_path: Path,
) -> None:
    failures = []
    reported = threading.Event()
    runner = ProcessRunner(["unused"])
    capture = OutputFileCapture(
        tmp_path / "failed.log",
        on_error=lambda error: (failures.append(error), reported.set()),
    )
    capture.attach(runner)
    underlying_file = capture._file

    class FailingFile:
        def write(self, _text: str) -> None:
            raise OSError("disk full")

        def flush(self) -> None:
            pass

        def close(self) -> None:
            underlying_file.close()

    capture._file = FailingFile()
    capture.write_chunk("failure")

    assert reported.wait(2)
    assert len(failures) == 1
    assert "disk full" in str(capture.error)
    assert capture.active is False
    assert not runner._output_listeners
    capture.close()
