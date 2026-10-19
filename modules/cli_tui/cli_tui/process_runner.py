from __future__ import annotations

from collections import deque
import os
import subprocess
import threading
import time
from typing import List, Optional, Sequence


class ProcessRunner:
    """Manages an asynchronous subprocess with thread-safe output streaming."""

    def __init__(
        self,
        argv: Sequence[str],
        *,
        cwd: Optional[str] = None,
        max_lines: int = 10000,
    ) -> None:
        self.argv = list(argv)
        self.cwd = cwd
        self.max_lines = max_lines
        self._lines: deque[str] = deque(maxlen=max_lines)
        self._lock = threading.Lock()
        self._process: Optional[subprocess.Popen[str]] = None
        self._thread: Optional[threading.Thread] = None
        self._start_time: Optional[float] = None
        self._end_time: Optional[float] = None
        self._exit_code: Optional[int] = None
        self._cancelled: bool = False

    def start(self) -> None:
        """Start the background process."""
        if self._process is not None:
            return

        env = os.environ.copy()
        env["PYTHONUNBUFFERED"] = "1"
        self._start_time = time.monotonic()

        self._process = subprocess.Popen(
            self.argv,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            cwd=self.cwd,
            env=env,
        )

        self._thread = threading.Thread(target=self._reader_loop, daemon=True)
        self._thread.start()

    def _reader_loop(self) -> None:
        if self._process is None or self._process.stdout is None:
            return

        try:
            for line in self._process.stdout:
                clean_line = line.rstrip("\r\n")
                with self._lock:
                    self._lines.append(clean_line)
        except Exception:
            pass
        finally:
            if self._process:
                self._process.wait()
                self._exit_code = self._process.poll()
                self._end_time = time.monotonic()

    @property
    def is_running(self) -> bool:
        if self._process is None:
            return False
        return self._process.poll() is None

    @property
    def exit_code(self) -> Optional[int]:
        if self._process is not None and self._exit_code is None:
            self._exit_code = self._process.poll()
        return self._exit_code

    @property
    def elapsed_seconds(self) -> float:
        if self._start_time is None:
            return 0.0
        end = self._end_time or time.monotonic()
        return max(0.0, end - self._start_time)

    @property
    def lines(self) -> List[str]:
        with self._lock:
            return list(self._lines)

    def terminate(self) -> None:
        """Gracefully terminate running process."""
        if self._process and self.is_running:
            self._cancelled = True
            try:
                self._process.terminate()
            except Exception:
                pass

    def kill(self) -> None:
        """Force kill running process."""
        if self._process and self.is_running:
            self._cancelled = True
            try:
                self._process.kill()
            except Exception:
                pass

    def wait(self, timeout: Optional[float] = None) -> Optional[int]:
        """Wait for process completion."""
        if self._process is None:
            return None
        try:
            self._process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            pass
        return self.exit_code


class OutputViewport:
    """Manages scrollable line window for TUI console viewports."""

    def __init__(self) -> None:
        self.scroll_offset: int = 0
        self.auto_scroll: bool = True

    def scroll_up(self, count: int = 1) -> None:
        self.scroll_offset += max(1, count)
        self.auto_scroll = False

    def scroll_down(self, count: int = 1) -> None:
        self.scroll_offset = max(0, self.scroll_offset - max(1, count))
        if self.scroll_offset == 0:
            self.auto_scroll = True

    def scroll_page_up(self, height: int) -> None:
        self.scroll_up(max(1, height - 2))

    def scroll_page_down(self, height: int) -> None:
        self.scroll_down(max(1, height - 2))

    def scroll_to_end(self) -> None:
        self.scroll_offset = 0
        self.auto_scroll = True

    def scroll_to_top(self, total_lines: int, height: int) -> None:
        self.scroll_offset = max(0, total_lines - height)
        self.auto_scroll = False

    def get_visible_lines(
        self,
        lines: Sequence[str],
        *,
        height: int,
        width: int,
    ) -> List[str]:
        """Return slice of lines fitting within height, clamped by scroll offset."""
        if height <= 0:
            return []

        total = len(lines)
        if total == 0:
            return [""] * height

        # Clamp scroll offset so we don't scroll past the top
        max_offset = max(0, total - height)
        if self.scroll_offset > max_offset:
            self.scroll_offset = max_offset

        if self.auto_scroll:
            start_idx = max(0, total - height)
            end_idx = total
        else:
            end_idx = max(1, total - self.scroll_offset)
            start_idx = max(0, end_idx - height)

        sliced = list(lines[start_idx:end_idx])

        # Pad with empty lines if fewer than height
        while len(sliced) < height:
            sliced.insert(0, "")

        return sliced
