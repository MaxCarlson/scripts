import codecs
from collections import deque
import os
import re
import subprocess
import textwrap
import threading
import time
from typing import Callable, List, Optional, Sequence, Tuple

_ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[a-zA-Z]")


def _visible_len(s: str) -> int:
    return len(_ANSI_RE.sub("", str(s or "")))


def wrap_ansi_line(text: str, width: int) -> List[str]:
    """Wrap line containing ANSI escape sequences without breaking codes."""
    if width <= 0 or _visible_len(text) <= width:
        return [text] if text else [""]

    token_pattern = re.compile(r"(\x1b\[[0-9;?]*[a-zA-Z]|.)", re.DOTALL)
    tokens = token_pattern.findall(text)

    lines: List[str] = []
    current_tokens: List[str] = []
    current_vis_len = 0
    active_sgr: List[str] = []

    for token in tokens:
        if token.startswith("\x1b[") and token.endswith("m"):
            if token == "\x1b[0m":
                active_sgr = []
            else:
                active_sgr.append(token)
            current_tokens.append(token)
        elif token.startswith("\x1b"):
            current_tokens.append(token)
        else:
            if current_vis_len >= width:
                line_str = "".join(current_tokens)
                if active_sgr:
                    line_str += "\x1b[0m"
                lines.append(line_str)
                current_tokens = list(active_sgr)
                current_vis_len = 0
            current_tokens.append(token)
            current_vis_len += 1

    if current_tokens:
        lines.append("".join(current_tokens))
    return lines or [""]


class VirtualTerminalBuffer:
    """Interprets ANSI terminal control sequences and in-place updates."""

    def __init__(self, *, max_lines: int = 10000) -> None:
        self.max_lines = max_lines
        self._lines: List[str] = [""]
        self._cursor_y: int = 0
        self._cursor_x: int = 0
        self._at_cr: bool = False
        self._pending: str = ""

    def feed(self, chunk: str) -> None:
        text = self._pending + chunk
        self._pending = ""
        n = len(text)
        i = 0

        while i < n:
            ch = text[i]

            if ch == "\r":
                self._at_cr = True
                self._cursor_x = 0
                i += 1
                continue

            if ch == "\n":
                self._at_cr = False
                self._cursor_y += 1
                self._cursor_x = 0
                while len(self._lines) <= self._cursor_y:
                    self._lines.append("")
                self._enforce_max_lines()
                i += 1
                continue

            if ch == "\x1b":
                # Escape sequence
                if i == n - 1:
                    self._pending = text[i:]
                    break

                next_ch = text[i + 1]
                if next_ch == "[":
                    # CSI sequence: look for terminating character (@ to ~)
                    j = i + 2
                    found = False
                    while j < n:
                        c = text[j]
                        if "@" <= c <= "~":
                            found = True
                            break
                        j += 1

                    if not found:
                        self._pending = text[i:]
                        break

                    param_str = text[i + 2 : j]
                    cmd = text[j]
                    i = j + 1

                    if cmd == "m":
                        # SGR color/style sequence: retain in text
                        if self._at_cr:
                            self._lines[self._cursor_y] = ""
                            self._at_cr = False
                        self._lines[self._cursor_y] += text[
                            i - (len(param_str) + 3) : i
                        ]
                    elif cmd == "A":
                        # Cursor Up
                        step = int(param_str) if param_str.isdigit() else 1
                        self._cursor_y = max(0, self._cursor_y - step)
                        self._cursor_x = 0
                        self._at_cr = False
                    elif cmd == "B":
                        # Cursor Down
                        step = int(param_str) if param_str.isdigit() else 1
                        self._cursor_y += step
                        while len(self._lines) <= self._cursor_y:
                            self._lines.append("")
                        self._enforce_max_lines()
                        self._cursor_x = 0
                        self._at_cr = False
                    elif cmd == "K":
                        # Erase in line
                        self._lines[self._cursor_y] = ""
                        self._cursor_x = 0
                        self._at_cr = False
                    elif cmd == "J" and param_str == "2":
                        # Clear entire screen
                        self._lines = [""]
                        self._cursor_y = 0
                        self._cursor_x = 0
                        self._at_cr = False
                    else:
                        self._at_cr = False
                    continue

                elif next_ch == "]":
                    # OSC sequence: look for BEL (\x07) or ST (\x1b\)
                    bel_pos = text.find("\x07", i + 2)
                    st_pos = text.find("\x1b\\", i + 2)
                    terminators = [p for p in (bel_pos, st_pos) if p != -1]
                    if not terminators:
                        self._pending = text[i:]
                        break
                    term_pos = min(terminators)
                    i = term_pos + (2 if term_pos == st_pos else 1)
                    continue

                else:
                    # 2-character escape sequence (e.g. \x1b=)
                    i += 2
                    continue

            # Regular text segment
            # Find next special character
            special_indices = [
                idx
                for idx in (
                    text.find("\r", i),
                    text.find("\n", i),
                    text.find("\x1b", i),
                )
                if idx != -1
            ]
            end = min(special_indices) if special_indices else n
            segment = text[i:end]

            if self._at_cr:
                self._lines[self._cursor_y] = ""
                self._at_cr = False

            self._lines[self._cursor_y] += segment
            self._cursor_x += len(segment)
            i = end

    def _enforce_max_lines(self) -> None:
        if len(self._lines) > self.max_lines:
            overflow = len(self._lines) - self.max_lines
            del self._lines[:overflow]
            self._cursor_y = max(0, self._cursor_y - overflow)

    def get_lines(self) -> List[str]:
        res = list(self._lines)
        if len(res) == 1 and res[0] == "":
            return []
        if len(res) > 0 and res[-1] == "":
            res.pop()
        return res


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
        self._process: Optional[subprocess.Popen[bytes]] = None
        self._thread: Optional[threading.Thread] = None
        self._start_time: Optional[float] = None
        self._end_time: Optional[float] = None
        self._exit_code: Optional[int] = None
        self._cancelled: bool = False
        self._output_listeners: set[Callable[[str], None]] = set()

    def start(self) -> None:
        """Start the background process."""
        if self._process is not None:
            return

        env = os.environ.copy()
        env["PYTHONUNBUFFERED"] = "1"
        env["PYTHONIOENCODING"] = "utf-8"
        env["PYTHONUTF8"] = "1"
        env["FORCE_COLOR"] = "1"
        env["CLICOLOR_FORCE"] = "1"
        env["TERM"] = "xterm-256color"
        env["TERMDASH_FORCE_INTERACTIVE"] = "1"
        self._start_time = time.monotonic()

        self._process = subprocess.Popen(
            self.argv,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            bufsize=0,
            cwd=self.cwd,
            env=env,
        )

        self._thread = threading.Thread(target=self._reader_loop, daemon=True)
        self._thread.start()

    def _reader_loop(self) -> None:
        if self._process is None or self._process.stdout is None:
            return

        decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
        buffer = VirtualTerminalBuffer(max_lines=self.max_lines)

        try:
            while True:
                chunk = self._process.stdout.read(4096)
                if not chunk:
                    break
                text = decoder.decode(chunk)
                if text:
                    self._accept_output(text, buffer)
            final_text = decoder.decode(b"", final=True)
            if final_text:
                self._accept_output(final_text, buffer)
        except Exception:
            pass
        finally:
            if self._process:
                self._process.wait()
                self._exit_code = self._process.poll()
                self._end_time = time.monotonic()

    def _accept_output(self, text: str, buffer: VirtualTerminalBuffer) -> None:
        with self._lock:
            buffer.feed(text)
            self._lines = deque(buffer.get_lines(), maxlen=self.max_lines)
            listeners = tuple(self._output_listeners)
        for listener in listeners:
            try:
                listener(text)
            except Exception:
                # Output subscribers are optional and must not break process reading.
                continue

    def subscribe_output(
        self,
        callback: Callable[[str], None],
        *,
        seed_callback: Optional[Callable[[List[str]], None]] = None,
    ) -> Callable[[], None]:
        """Subscribe to decoded output, optionally seeding from current scrollback."""
        with self._lock:
            if seed_callback is not None:
                seed_callback(list(self._lines))
            self._output_listeners.add(callback)

        def unsubscribe() -> None:
            with self._lock:
                self._output_listeners.discard(callback)

        return unsubscribe

    def snapshot_and_subscribe(
        self, callback: Callable[[str], None]
    ) -> Tuple[List[str], Callable[[], None]]:
        """Atomically return retained lines and subscribe to later decoded output."""
        with self._lock:
            lines = list(self._lines)
            self._output_listeners.add(callback)

        def unsubscribe() -> None:
            with self._lock:
                self._output_listeners.discard(callback)

        return lines, unsubscribe

    @property
    def is_running(self) -> bool:
        if self._process is None:
            return False
        return self._process.poll() is None

    @property
    def proc(self) -> Optional[subprocess.Popen[bytes]]:
        return self._process

    @property
    def pid(self) -> Optional[int]:
        if self._process is not None:
            return self._process.pid
        return None

    @property
    def thread(self) -> Optional[threading.Thread]:
        return self._thread

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
            if self._thread and self._thread.is_alive():
                self._thread.join(timeout=timeout)
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

    def wrap_lines(self, lines: Sequence[str], width: int) -> List[str]:
        """Wrap lines to width so horizontal scrolling is not required."""
        if width <= 0:
            return list(lines)
        wrapped: List[str] = []
        for line in lines:
            line_str = str(line).expandtabs(4)
            vis_len = _visible_len(line_str)
            if not line_str or vis_len <= width:
                wrapped.append(line_str)
            elif _ANSI_RE.search(line_str):
                wrapped.extend(wrap_ansi_line(line_str, width))
            else:
                chunks = textwrap.wrap(
                    line_str,
                    width=width,
                    break_long_words=True,
                    break_on_hyphens=False,
                    drop_whitespace=False,
                    replace_whitespace=False,
                )
                wrapped.extend(chunks if chunks else [""])
        return wrapped

    def get_scroll_bounds(
        self,
        lines: Sequence[str],
        *,
        height: int,
        width: int,
    ) -> Tuple[int, int, int]:
        """Return (start_line_1_indexed, end_line_1_indexed, total_lines)."""
        wrapped = self.wrap_lines(lines, width)
        total = len(wrapped)
        if total == 0:
            return (0, 0, 0)
        if total <= height:
            return (1, total, total)

        max_offset = max(0, total - height)
        clamped_offset = min(self.scroll_offset, max_offset)
        if self.auto_scroll:
            start_idx = max(0, total - height)
            end_idx = total
        else:
            end_idx = max(height, total - clamped_offset)
            start_idx = max(0, end_idx - height)
        return (start_idx + 1, min(total, end_idx), total)

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

        wrapped = self.wrap_lines(lines, width)
        total = len(wrapped)
        if total == 0:
            return []

        # If all lines fit within height, top-align (start at line 0)
        if total <= height:
            return list(wrapped)

        max_offset = max(0, total - height)
        if self.scroll_offset > max_offset:
            self.scroll_offset = max_offset

        if self.auto_scroll:
            start_idx = max(0, total - height)
            end_idx = total
        else:
            end_idx = max(height, total - self.scroll_offset)
            start_idx = max(0, end_idx - height)

        return list(wrapped[start_idx:end_idx])
