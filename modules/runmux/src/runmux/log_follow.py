"""Incremental, bounded reader for Runmux's byte-preserving output logs."""

from __future__ import annotations

import codecs
import threading
from collections import deque
from contextlib import suppress
from pathlib import Path


class IncrementalLogReader:
    """Read appended UTF-8 log data while retaining a bounded line transcript."""

    def __init__(
        self,
        path: Path,
        *,
        max_lines: int = 10_000,
        max_bytes: int = 4_194_304,
        chunk_size: int = 8192,
    ) -> None:
        if max_lines < 1 or max_bytes < 1 or chunk_size < 1:
            raise ValueError("max_lines, max_bytes, and chunk_size must be positive")
        self.path = Path(path)
        self.max_lines = max_lines
        self.max_bytes = max_bytes
        self.chunk_size = chunk_size
        self._lines: deque[str] = deque()
        self._retained_bytes = 0
        self._offset = 0
        self._file_identity: tuple[int, int] | None = None
        self._decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
        self._error: str | None = None
        self._lock = threading.RLock()

    @property
    def lines(self) -> list[str]:
        """Return a copy of the retained transcript, including an unfinished line."""

        with self._lock:
            return list(self._lines)

    @property
    def offset(self) -> int:
        """Return the number of bytes consumed from the current file generation."""

        with self._lock:
            return self._offset

    @property
    def error(self) -> str | None:
        """Return the latest read error, or ``None`` after a successful read."""

        with self._lock:
            return self._error

    def read_available(self) -> list[str]:
        """Read currently available bytes and return newly retained transcript text."""

        with self._lock:
            try:
                stat = self.path.stat()
                identity = (stat.st_dev, stat.st_ino)
                if identity != self._file_identity or stat.st_size < self._offset:
                    self._reset(identity)
                new_text: list[str] = []
                with self.path.open("rb") as stream:
                    stream.seek(self._offset)
                    remaining = self.max_bytes
                    while remaining > 0 and (chunk := stream.read(min(self.chunk_size, remaining))):
                        remaining -= len(chunk)
                        self._offset = stream.tell()
                        decoded = self._decoder.decode(chunk, final=False)
                        if decoded:
                            self._append_text(decoded)
                            new_text.append(decoded)
                self._error = None
                return new_text
            except OSError as error:
                self._error = str(error)
                return []

    def _reset(self, identity: tuple[int, int]) -> None:
        self._file_identity = identity
        self._offset = 0
        self._lines.clear()
        self._retained_bytes = 0
        self._decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")

    def _append_text(self, text: str) -> None:
        # Keep newline delimiters so ANSI sequences and exact output remain visible.
        pieces = text.splitlines(keepends=True)
        for piece in pieces:
            if self._lines and not self._lines[-1].endswith(("\n", "\r")):
                previous = self._lines.pop()
                self._retained_bytes -= len(previous.encode("utf-8"))
                piece = previous + piece
            piece = self._fit_line(piece)
            self._lines.append(piece)
            self._retained_bytes += len(piece.encode("utf-8"))
            self._trim()

    def _fit_line(self, line: str) -> str:
        encoded = line.encode("utf-8")
        if len(encoded) <= self.max_bytes:
            return line
        encoded = encoded[-self.max_bytes :]
        return encoded.decode("utf-8", errors="ignore")

    def _trim(self) -> None:
        while len(self._lines) > self.max_lines or self._retained_bytes > self.max_bytes:
            removed = self._lines.popleft()
            self._retained_bytes -= len(removed.encode("utf-8"))


class LogFollowWorker:
    """Poll a log reader away from the UI thread and expose safe snapshots."""

    def __init__(self, reader: IncrementalLogReader, *, interval: float = 0.1) -> None:
        if interval <= 0:
            raise ValueError("interval must be positive")
        self.reader = reader
        self.interval = interval
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        """Start the polling thread once."""

        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="runmux-log-follow", daemon=True)
        self._thread.start()

    def snapshot(self) -> list[str]:
        """Return the reader's current bounded transcript."""

        return self.reader.lines

    def stop(self) -> None:
        """Stop the polling thread without affecting the managed process."""

        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=max(1.0, self.interval * 2))

    def _run(self) -> None:
        while not self._stop.is_set():
            with suppress(Exception):
                self.reader.read_available()
            self._stop.wait(self.interval)


class PaneOutputCapture:
    """Copy a pane's complete raw output log to a user-selected file and follow it."""

    def __init__(self, source: Path, destination: Path, *, interval: float = 0.1, chunk_size: int = 65536) -> None:
        self.source = Path(source).expanduser().resolve()
        self.destination = Path(destination).expanduser().resolve()
        if self.source == self.destination:
            raise ValueError("pane output cannot be copied over its Runmux source log")
        if interval <= 0 or chunk_size <= 0:
            raise ValueError("interval and chunk_size must be positive")
        self.interval = interval
        self.chunk_size = chunk_size
        self.offset = 0
        self.error: str | None = None
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self.destination.parent.mkdir(parents=True, exist_ok=True)
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="runmux-pane-output-capture", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=max(1.0, self.interval * 2))

    def _run(self) -> None:
        try:
            with self.destination.open("wb") as output:
                while not self._stop.is_set():
                    try:
                        size = self.source.stat().st_size
                        if size < self.offset:
                            self.offset = 0
                        with self.source.open("rb") as source:
                            source.seek(self.offset)
                            while chunk := source.read(self.chunk_size):
                                output.write(chunk)
                                output.flush()
                                self.offset = source.tell()
                        self.error = None
                    except OSError as error:
                        self.error = str(error)
                    self._stop.wait(self.interval)
        except OSError as error:
            self.error = str(error)
