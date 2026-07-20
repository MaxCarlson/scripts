"""Small, reusable terminal loading indicators for gaps between UI states."""

from __future__ import annotations

import sys
import threading
import time
from typing import Optional, Sequence, TextIO


CSI = "\x1b["
CLEAR_LINE = f"{CSI}2K"
DEFAULT_FRAMES = ("✦", "✧", "·", "✧")


class LoadingIndicator:
    """Render a single-line spinner until :meth:`stop` is called."""

    def __init__(self, message: str = "Loading", *, interval: float = 0.12,
                 frames: Sequence[str] = DEFAULT_FRAMES, stream: Optional[TextIO] = None) -> None:
        if not frames:
            raise ValueError("frames must contain at least one character")
        self.message = message
        self.interval = max(0.01, float(interval))
        self.frames = tuple(frames)
        self.stream = stream or sys.stdout
        self._frame_index = 0
        self._lock = threading.RLock()
        self._running = False
        self._thread: Optional[threading.Thread] = None

    def _render(self) -> None:
        with self._lock:
            frame = self.frames[self._frame_index % len(self.frames)]
            self._frame_index += 1
            self.stream.write(f"\r{CLEAR_LINE}{frame} {self.message}")
            self.stream.flush()

    def _run(self) -> None:
        while self._running:
            self._render()
            time.sleep(self.interval)

    def start(self) -> "LoadingIndicator":
        """Begin animating the indicator. Calling this more than once is safe."""
        with self._lock:
            if self._running:
                return self
            self._running = True
            self._render()
            self._thread = threading.Thread(target=self._run, name="termdash-loading", daemon=True)
            self._thread.start()
        return self

    def update(self, message: str) -> None:
        """Replace the visible message immediately."""
        with self._lock:
            self.message = str(message)
            if self._running:
                self._render()

    def stop(self) -> None:
        """Stop the animation and erase its terminal row."""
        with self._lock:
            if not self._running:
                return
            self._running = False
            thread = self._thread
        if thread and thread is not threading.current_thread():
            thread.join(timeout=max(0.2, self.interval * 3))
        with self._lock:
            self.stream.write(f"\r{CLEAR_LINE}\r")
            self.stream.flush()
            self._thread = None

    def __enter__(self) -> "LoadingIndicator":
        return self.start()

    def __exit__(self, exc_type, exc_val, exc_tb) -> bool:
        self.stop()
        return False
