from __future__ import annotations

import queue
import threading
from pathlib import Path
from typing import Callable, Iterable, Optional, TextIO


class OutputFileCapture:
    """Write a retained transcript and later output on a bounded background queue."""

    _STOP = object()
    _MAX_PENDING_CHUNKS = 256
    _CLOSE_TIMEOUT_SECONDS = 0.5

    def __init__(
        self,
        path: str | Path,
        initial_lines: Iterable[str] = (),
        *,
        overwrite: bool = False,
        on_error: Optional[Callable[[OSError], None]] = None,
    ) -> None:
        self.path = Path(path).expanduser()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._enqueue_lock = threading.RLock()
        self._queue: queue.Queue[object] = queue.Queue(maxsize=self._MAX_PENDING_CHUNKS)
        self._file: Optional[TextIO] = None
        self._closed = False
        self._failed = False
        self._error: Optional[OSError] = None
        self._on_error = on_error
        self._unsubscribe: Optional[Callable[[], None]] = None

        self._file = self.path.open(
            "w" if overwrite else "x", encoding="utf-8", newline=""
        )
        self._writer = threading.Thread(
            target=self._writer_loop, name="cli-tui-output-capture", daemon=True
        )
        self._writer.start()
        self.write_snapshot(initial_lines)

    @staticmethod
    def _format_snapshot(lines: Iterable[str]) -> str:
        values = [str(line) for line in lines]
        return "\n".join(values) + "\n" if values else ""

    @property
    def active(self) -> bool:
        with self._lock:
            return not self._closed and not self._failed and self._file is not None

    @property
    def error(self) -> Optional[OSError]:
        with self._lock:
            return self._error

    def initialize_from(
        self,
        subscribe: Callable[
            [Callable[[str], None]], tuple[list[str], Callable[[], None]]
        ],
    ) -> Callable[[], None]:
        """Atomically subscribe and queue that exact snapshot before later chunks."""
        unsubscribe: Optional[Callable[[], None]] = None
        try:
            with self._enqueue_lock:
                lines, unsubscribe = subscribe(self.write_chunk)
                self._enqueue_locked(self._format_snapshot(lines))
        except Exception:
            if unsubscribe is not None:
                unsubscribe()
            self._discard_file()
            raise
        with self._lock:
            failed = self._failed or self._closed
            if not failed:
                self._unsubscribe = unsubscribe
        if failed and unsubscribe is not None:
            unsubscribe()
        return unsubscribe

    def attach(self, runner: object) -> None:
        """Subscribe to a process or console runner, seeding retained output first."""
        snapshot_subscribe = getattr(runner, "snapshot_and_subscribe", None)
        if callable(snapshot_subscribe):
            self.initialize_from(snapshot_subscribe)
            return

        subscribe_output = getattr(runner, "subscribe_output", None)
        if not callable(subscribe_output):
            raise TypeError("runner does not support output subscriptions")

        def legacy_subscribe(
            callback: Callable[[str], None],
        ) -> tuple[list[str], Callable[[], None]]:
            lines: list[str] = []
            unsubscribe = subscribe_output(callback, seed_callback=lines.extend)
            return lines, unsubscribe

        self.initialize_from(legacy_subscribe)

    def write_snapshot(self, lines: Iterable[str]) -> None:
        """Queue retained lines before output received after capture starts."""
        with self._enqueue_lock:
            self._enqueue_locked(self._format_snapshot(lines))

    def write_chunk(self, text: str) -> None:
        """Queue a later decoded output chunk without doing file I/O on its caller."""
        if not text:
            return
        with self._enqueue_lock:
            self._enqueue_locked(text)

    def _enqueue_locked(self, text: str) -> None:
        if not text:
            return
        with self._lock:
            if self._closed or self._failed or self._file is None:
                return
        try:
            self._queue.put_nowait(text)
        except queue.Full:
            self._signal_failure(
                OSError(
                    f"output capture stopped for {self.path}: the writer fell behind; "
                    "the captured file may be incomplete"
                )
            )
            return
        with self._lock:
            failed = self._failed
        if failed:
            self._discard_pending()

    def _writer_loop(self) -> None:
        pending = 0
        while True:
            try:
                item = self._queue.get(timeout=0.1)
            except queue.Empty:
                with self._lock:
                    stopping = self._closed
                if stopping:
                    self._flush_and_close()
                    return
                continue
            if item is self._STOP:
                self._flush_and_close()
                return
            with self._lock:
                file = self._file
            if file is None:
                return
            try:
                file.write(str(item))
                pending += 1
                if pending >= 64:
                    file.flush()
                    pending = 0
            except OSError as exc:
                self._handle_writer_error(exc)
                return

    def _flush_and_close(self) -> None:
        with self._lock:
            file = self._file
            self._file = None
        if file is None:
            return
        try:
            file.flush()
            file.close()
        except OSError as exc:
            try:
                file.close()
            except OSError:
                pass
            self._handle_writer_error(exc)

    def _handle_writer_error(self, error: OSError) -> None:
        with self._lock:
            file = self._file
            self._file = None
        self._signal_failure(error)
        if file is not None:
            try:
                file.close()
            except OSError:
                pass
        self._discard_pending()

    def _signal_failure(self, error: OSError) -> None:
        with self._lock:
            if self._error is not None:
                return
            self._failed = True
            self._closed = True
            self._error = error
            callback = self._on_error
            unsubscribe, self._unsubscribe = self._unsubscribe, None
        if unsubscribe is not None:
            try:
                unsubscribe()
            except Exception:
                pass
        if callback is not None:
            try:
                callback(error)
            except Exception:
                pass

    def _discard_pending(self) -> None:
        while True:
            try:
                self._queue.get_nowait()
            except queue.Empty:
                return

    def _discard_file(self) -> None:
        with self._lock:
            self._failed = True
            self._closed = True
            unsubscribe, self._unsubscribe = self._unsubscribe, None
        if unsubscribe is not None:
            try:
                unsubscribe()
            except Exception:
                pass
        self._discard_pending()
        try:
            self._queue.put_nowait(self._STOP)
        except queue.Full:
            pass
        if self._writer is not threading.current_thread():
            self._writer.join(timeout=self._CLOSE_TIMEOUT_SECONDS)
        if not self._writer.is_alive():
            try:
                self.path.unlink(missing_ok=True)
            except OSError:
                pass

    def close(self) -> None:
        """Stop capture and wait briefly for queued output to drain and close."""
        with self._lock:
            unsubscribe, self._unsubscribe = self._unsubscribe, None
        if unsubscribe is not None:
            try:
                unsubscribe()
            except Exception:
                pass
        with self._enqueue_lock:
            with self._lock:
                already_closed = self._closed
                if not already_closed:
                    self._closed = True
            if not already_closed:
                try:
                    self._queue.put_nowait(self._STOP)
                except queue.Full:
                    pass
        if self._writer is not threading.current_thread():
            self._writer.join(timeout=self._CLOSE_TIMEOUT_SECONDS)
            if self._writer.is_alive():
                self._signal_failure(
                    OSError(
                        f"output capture writer for {self.path} did not stop within "
                        f"{self._CLOSE_TIMEOUT_SECONDS:.2f}s; the captured file may be incomplete"
                    )
                )

    def __enter__(self) -> OutputFileCapture:
        return self

    def __exit__(self, exc_type: object, exc_value: object, traceback: object) -> None:
        self.close()
