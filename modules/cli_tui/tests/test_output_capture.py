from pathlib import Path
import threading

from cli_tui.output_capture import OutputFileCapture
from cli_tui.process_runner import ProcessRunner


def test_output_capture_writes_snapshot_then_future_output(tmp_path: Path) -> None:
    destination = tmp_path / "pane.log"
    capture = OutputFileCapture(destination, ["first", "second"])
    capture.write("third\n")
    capture.close()

    assert destination.read_text(encoding="utf-8") == "first\nsecond\nthird\n"


def test_output_capture_detaches_and_reports_future_write_failure(
    tmp_path: Path,
) -> None:
    failures = []
    reported = threading.Event()

    def on_error(error):
        failures.append(error)
        reported.set()

    capture = OutputFileCapture(tmp_path / "pane.log", [], on_error=on_error)

    class FailingWriter:
        def write(self, _text: str) -> None:
            raise OSError("disk full")

        def close(self) -> None:
            pass

    capture._file.close()
    capture._file = FailingWriter()
    capture.write("later")
    assert reported.wait(2)

    assert len(failures) == 1
    assert "disk full" in str(failures[0])
    assert not capture.active
    capture.close()


def test_process_runner_notifies_output_subscribers() -> None:
    runner = ProcessRunner(["not-started"])
    received = []
    unsubscribe = runner.add_output_listener(received.append)

    runner._dispatch_output("hello")

    assert received == ["hello"]
    unsubscribe()
    runner._dispatch_output("ignored")
    assert received == ["hello"]
