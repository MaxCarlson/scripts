"""Width-safe transient in-place blocks, without taking over the whole screen."""

from __future__ import annotations

import os
import sys
import threading
from typing import Callable, Sequence, TextIO

from .table import _strip_ansi, _truncate_cell


class LiveBlock:
    """Reusable relative-cursor renderer for audit/compression status rows.

    Unlike TermDash's scrolling-region dashboard, this reserves only its rows
    beneath existing console output and never jumps to the top of the screen.
    Redirected output uses periodic plain progress. A callback enables timers
    to keep ticking even while an encoder/metadata request is blocking.
    """

    def __init__(
        self,
        *,
        stream: TextIO | None = None,
        enabled: bool = True,
        interval: float = 0.25,
    ) -> None:
        self.stream = stream if stream is not None else sys.stderr
        self.enabled = enabled
        force = os.environ.get("TERMDASH_FORCE_INTERACTIVE") == "1"
        self.interactive = (
            enabled
            and (self.stream.isatty() or force)
            and os.environ.get("TERM") != "dumb"
        )
        self.interval = interval
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._provider: Callable[[], Sequence[str]] | None = None
        self._height = 0
        self._closed = False

    def _width(self) -> int:
        try:
            cols = int(os.environ.get("COLUMNS", 0))
            if cols > 0:
                return cols - 1
            return max(1, os.get_terminal_size(self.stream.fileno()).columns - 1)
        except (OSError, ValueError, AttributeError):
            return 79

    def _render(self) -> None:
        if not self._provider or not self.interactive:
            return
        rows = [
            str(line).replace("\r", " ").replace("\n", " ") for line in self._provider()
        ]
        rows = [
            _truncate_cell(
                _strip_ansi(line) if "NO_COLOR" in os.environ else line, self._width()
            )
            for line in rows
        ]
        height = max(self._height, len(rows))
        rows += [""] * (height - len(rows))
        if self._height > 1:
            self.stream.write(f"\r\033[{self._height - 1}A")
        else:
            self.stream.write("\r")
        self.stream.write("\n".join("\r\033[2K" + line for line in rows))
        self.stream.flush()
        self._height = height

    def update(self, provider: Callable[[], Sequence[str]]) -> None:
        if not self.enabled or self._closed:
            return
        with self._lock:
            self._provider = provider
            self._render()
            if self.interactive and self._thread is None:
                self._thread = threading.Thread(
                    target=self._tick, name="termdash-live", daemon=True
                )
                self._thread.start()

    def _tick(self) -> None:
        while not self._stop.wait(self.interval):
            with self._lock:
                self._render()

    def log(self, message: str) -> None:
        if not self.enabled:
            return
        with self._lock:
            self._erase()
            print(message, file=self.stream, flush=True)
            self._render()

    def _erase(self) -> None:
        if not self.interactive or not self._height:
            return
        if self._height > 1:
            self.stream.write(f"\r\033[{self._height - 1}A")
        self.stream.write("\n".join("\r\033[2K" for _ in range(self._height)))
        if self._height > 1:
            self.stream.write(f"\r\033[{self._height - 1}A")
        self.stream.write("\r")
        self.stream.flush()
        self._height = 0

    def close(self) -> None:
        self._stop.set()
        if self._thread and self._thread is not threading.current_thread():
            self._thread.join(timeout=1)
        with self._lock:
            self._erase()
            self._closed = True
