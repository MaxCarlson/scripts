from __future__ import annotations

import time
from pathlib import Path

from runmux.log_follow import IncrementalLogReader, LogFollowWorker, PaneOutputCapture


def test_reader_preserves_utf8_and_ansi_sequences_split_across_reads(tmp_path: Path) -> None:
    path = tmp_path / "output.ansi"
    reader = IncrementalLogReader(path, chunk_size=2)
    path.write_bytes(b"caf\xc3")

    assert "".join(reader.read_available()) == "caf"
    with path.open("ab") as stream:
        stream.write(b"\xa9 \x1b[31")
    assert "".join(reader.read_available()) == "é \x1b[31"
    with path.open("ab") as stream:
        stream.write(b"mred\x1b[0m\n")
    assert "".join(reader.read_available()) == "mred\x1b[0m\n"


def test_reader_bounds_transcript_by_lines_and_bytes(tmp_path: Path) -> None:
    path = tmp_path / "output.ansi"
    path.write_bytes(("a" * 30 + "\n") .encode() * 10)
    reader = IncrementalLogReader(path, max_lines=3, max_bytes=64, chunk_size=17)

    while reader.offset < path.stat().st_size:
        reader.read_available()

    assert len(reader.lines) <= 3
    assert sum(len(line.encode("utf-8")) for line in reader.lines) <= 64
    assert reader.offset == path.stat().st_size


def test_reader_limits_each_read_batch_for_very_large_backlogs(tmp_path: Path) -> None:
    path = tmp_path / "output.ansi"
    path.write_bytes((b"line of output\n") * 100_000)
    reader = IncrementalLogReader(path, max_lines=10, max_bytes=256, chunk_size=64)

    batch = reader.read_available()

    assert sum(len(item.encode("utf-8")) for item in batch) <= 256
    assert reader.offset <= 256
    assert len(reader.lines) <= 10


def test_reader_recovers_from_truncation_and_replacement(tmp_path: Path) -> None:
    path = tmp_path / "output.ansi"
    path.write_bytes(b"old output\n")
    reader = IncrementalLogReader(path)
    assert reader.read_available() == ["old output\n"]

    path.write_bytes(b"new\n")
    assert reader.read_available() == ["new\n"]
    assert reader.lines == ["new\n"]


def test_reader_handles_missing_and_recreated_file(tmp_path: Path) -> None:
    path = tmp_path / "output.ansi"
    reader = IncrementalLogReader(path)

    assert reader.read_available() == []
    assert reader.error is not None
    path.write_bytes(b"available\n")
    assert reader.read_available() == ["available\n"]
    assert reader.error is None


def test_worker_reads_off_caller_thread_and_stops(tmp_path: Path) -> None:
    path = tmp_path / "output.ansi"
    path.write_bytes(b"ready\n")
    reader = IncrementalLogReader(path)
    worker = LogFollowWorker(reader, interval=0.01)
    worker.start()
    deadline = time.monotonic() + 1
    while not worker.snapshot() and time.monotonic() < deadline:
        time.sleep(0.005)

    assert worker.snapshot() == ["ready\n"]
    worker.stop()


def test_worker_reader_exception_does_not_escape_or_stop_process_ownership(tmp_path: Path) -> None:
    class FailingReader(IncrementalLogReader):
        def read_available(self) -> list[str]:
            raise OSError("injected reader failure")

    worker = LogFollowWorker(FailingReader(tmp_path / "missing.log"), interval=0.01)
    worker.start()
    time.sleep(0.03)

    assert worker._thread is not None and worker._thread.is_alive()
    worker.stop()


def test_pane_output_capture_copies_existing_and_future_raw_bytes(tmp_path: Path) -> None:
    source = tmp_path / "output.ansi"
    destination = tmp_path / "exports" / "pane ansi.log"
    source.write_bytes(b"\x1b[31mexisting\xe2")
    capture = PaneOutputCapture(source, destination, interval=0.01, chunk_size=3)
    capture.start()
    deadline = time.monotonic() + 1
    while (
        not destination.exists() or destination.stat().st_size < source.stat().st_size
    ) and time.monotonic() < deadline:
        time.sleep(0.005)
    with source.open("ab") as stream:
        stream.write(b"\x82\xac\x1b[0m\nnew line\n")
    expected = source.read_bytes()
    deadline = time.monotonic() + 1
    while (not destination.exists() or destination.stat().st_size < len(expected)) and time.monotonic() < deadline:
        time.sleep(0.005)
    capture.stop()

    assert destination.read_bytes() == expected
    assert capture.error is None


def test_pane_output_capture_rejects_source_path_as_destination(tmp_path: Path) -> None:
    source = tmp_path / "output.ansi"
    source.touch()

    try:
        PaneOutputCapture(source, source)
    except ValueError as error:
        assert "source log" in str(error)
    else:
        raise AssertionError("expected source/destination collision to be rejected")

