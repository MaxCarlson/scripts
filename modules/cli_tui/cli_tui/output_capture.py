from __future__ import annotations

import threading
from pathlib import Path
from typing import Callable, Iterable, Optional


class OutputFileCapture:
    """Write an output snapshot and subsequent text chunks to a user-selected file."""

    def __init__(
        self,
        path: str | Path,
        *,
        overwrite: bool = False,
        on_error: Optional[Callable[[OSError], None]] = None,
    ) -> None:
        self.path = Path(path).expanduser()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._stream = self.path.open("w" if overwrite else "x", encoding="utf-8", newline="")
        self._lock = threading.Lock()
        self._closed = False
        self._unsubscribe: Optional[Callable[[], None]] = None
        self._on_error = on_error
        self.error: Optional[OSError] = None

    def write_snapshot(self, lines: Iterable[str]) -> None:
        snapshot = list(lines)
        if snapshot:
            self._write("\n".join(snapshot) + "\n")

    def write_chunk(self, text: str) -> None:
        if text:
            self._write(text)

    def attach(self, runner: object) -> None:
        """Atomically seed from runner scrollback and subscribe to future decoded output."""
        subscribe = getattr(runner, "subscribe_output", None)
        if not callable(subscribe):
            raise TypeError("runner does not support output subscriptions")
        self._unsubscribe = subscribe(
            self.write_chunk,
            seed_callback=self.write_snapshot,
        )

    def _write(self, text: str) -> None:
        try:
            with self._lock:
                if not self._closed:
                    self._stream.write(text)
                    self._stream.flush()
        except OSError as exc:
            self.error = exc
            if self._on_error:
                self._on_error(exc)

    def close(self) -> None:
        unsubscribe, self._unsubscribe = self._unsubscribe, None
        if unsubscribe:
            unsubscribe()
        with self._lock:
            if self._closed:
                return
            self._closed = True
            try:
                self._stream.flush()
                self._stream.close()
            except OSError as exc:
                self.error = exc
                if self._on_error:
                    self._on_error(exc)

    def __enter__(self) -> OutputFileCapture:
        return self

    def __exit__(self, exc_type: object, exc_value: object, traceback: object) -> None:
        self.close()
