from __future__ import annotations

from pathlib import Path
import queue
import threading
from typing import Callable, Iterable, Optional, TextIO


class OutputFileCapture:
    """Thread-safe UTF-8 transcript writer with asynchronous file I/O."""

    _STOP = object()

    def __init__(
        self,
        path: str | Path,
        initial_lines: Iterable[str],
        *,
        overwrite: bool = False,
        on_error: Optional[Callable[[OSError], None]] = None,
    ) -> None:
        self.path = Path(path)
        self._on_error = on_error
        self._lock = threading.Lock()
        self._queue: queue.Queue[object] = queue.Queue()
        self._file: Optional[TextIO] = None
        self._closed = False
        self._failed = False
        self._writer: Optional[threading.Thread] = None
        try:
            self._file = self.path.open(
                "w" if overwrite else "x", encoding="utf-8", newline=""
            )
            snapshot = self._format_snapshot(initial_lines)
            if snapshot:
                self._queue.put_nowait(snapshot)
            self._writer = threading.Thread(
                target=self._writer_loop, name="cli-tui-output-capture", daemon=True
            )
            self._writer.start()
        except OSError:
            if self._file is not None:
                self._file.close()
            raise

    @staticmethod
    def _format_snapshot(lines: Iterable[str]) -> str:
        values = [str(line) for line in lines]
        return "\n".join(values) + "\n" if values else ""

    def initialize_from(
        self,
        subscribe: Callable[
            [Callable[[str], None]], tuple[list[str], Callable[[], None]]
        ],
    ) -> Callable[[], None]:
        """Subscribe under the writer lock and enqueue that exact snapshot first."""
        unsubscribe: Optional[Callable[[], None]] = None
        try:
            with self._lock:
                lines, unsubscribe = subscribe(self.write)
                snapshot = self._format_snapshot(lines)
                if snapshot:
                    self._queue.put_nowait(snapshot)
        except OSError:
            if unsubscribe is not None:
                unsubscribe()
            self._discard_file()
            raise
        return unsubscribe

    def write_snapshot(self, lines: Iterable[str]) -> None:
        """Queue a retained transcript snapshot before future output chunks."""
        snapshot = self._format_snapshot(lines)
        if not snapshot:
            return
        with self._lock:
            if not self._closed and not self._failed:
                self._queue.put_nowait(snapshot)

    @property
    def active(self) -> bool:
        with self._lock:
            return not self._closed and not self._failed and self._file is not None

    def write(self, text: str) -> None:
        """Queue later output without waiting for disk I/O."""
        with self._lock:
            if not self._closed and not self._failed and self._file is not None:
                self._queue.put_nowait(text)

    def _writer_loop(self) -> None:
        while True:
            item = self._queue.get()
            if item is self._STOP:
                self._flush_and_close()
                return
            with self._lock:
                file = self._file
            if file is None:
                return
            try:
                file.write(str(item))
                file.flush()
            except OSError as exc:
                self._handle_writer_error(exc)
                return

    def _flush_and_close(self) -> None:
        with self._lock:
            file = self._file
            self._file = None
        if file is not None:
            try:
                file.flush()
            except OSError as exc:
                try:
                    file.close()
                except OSError:
                    pass
                self._handle_writer_error(exc)
                return
            try:
                file.close()
            except OSError as exc:
                self._handle_writer_error(exc)

    def _handle_writer_error(self, error: OSError) -> None:
        with self._lock:
            self._failed = True
            self._closed = True
            file = self._file
            self._file = None
            callback = self._on_error
        if file is not None:
            try:
                file.close()
            except OSError:
                pass
        if callback is not None:
            try:
                callback(error)
            except Exception:
                pass

    def _discard_file(self) -> None:
        with self._lock:
            self._failed = True
            self._closed = True
            writer = self._writer
            self._queue.put_nowait(self._STOP)
            file = self._file
            self._file = None
        if file is not None:
            try:
                file.close()
            except OSError:
                pass
        try:
            self.path.unlink(missing_ok=True)
        except OSError:
            pass
        if writer is not None and writer is not threading.current_thread():
            writer.join()

    def close(self) -> None:
        """Drain queued output and close the file without blocking the TUI reader."""
        with self._lock:
            writer = self._writer
            if not self._closed:
                self._closed = True
                self._queue.put_nowait(self._STOP)
        if writer is not None and writer is not threading.current_thread():
            writer.join()
