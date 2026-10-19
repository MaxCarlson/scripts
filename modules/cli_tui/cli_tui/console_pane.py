from __future__ import annotations

import curses
import os
import sys
from typing import List, Optional

from .process_runner import ProcessRunner


class ConsolePaneRunner:
    """Embedded interactive shell console runner for cli_tui panes."""

    def __init__(self, cwd: Optional[str] = None) -> None:
        self.cwd: str = os.path.abspath(cwd or os.getcwd())
        self.history_lines: List[str] = [
            f"Interactive Shell Console [{sys.platform}]",
            f"Working directory: {self.cwd}",
            "Type commands and press Enter. Type 'exit' to close.",
            "",
        ]
        self.active_runner: Optional[ProcessRunner] = None
        self.input_buffer: str = ""
        self.cursor_pos: int = 0
        self.is_terminated: bool = False

    @property
    def is_running(self) -> bool:
        if self.active_runner:
            return bool(self.active_runner.is_running)
        return False

    @property
    def lines(self) -> List[str]:
        output = list(self.history_lines)
        if self.active_runner:
            output.extend(self.active_runner.lines)
        return output

    def execute_line(self, line: str) -> None:
        if self.active_runner:
            self.history_lines.extend(self.active_runner.lines)
            self.history_lines.append("")
            self.active_runner = None

        cmd_str = line.strip()
        self.history_lines.append(f"[{self.cwd}]> {line}")

        if not cmd_str:
            return

        # Built-in cd and drive switching handling
        lower = cmd_str.lower()
        is_drive = len(cmd_str) == 2 and cmd_str[1] == ":" and sys.platform == "win32"
        if (
            lower.startswith("cd ")
            or lower == "cd"
            or lower.startswith("cd.")
            or is_drive
        ):
            if is_drive:
                target = cmd_str
            elif lower.startswith("cd."):
                target = cmd_str[2:].strip()
            else:
                target = cmd_str[2:].strip()

            target = target.strip("\"'")
            if not target:
                target = os.path.expanduser("~")
            elif target.lower().startswith("/d "):
                target = target[3:].strip().strip("\"'")

            if len(target) == 2 and target[1] == ":" and sys.platform == "win32":
                new_dir = f"{target.upper()}\\"
            else:
                new_dir = os.path.abspath(os.path.join(self.cwd, target))

            if os.path.isdir(new_dir):
                self.cwd = new_dir
                self.history_lines.append(f"Directory changed to: {self.cwd}")
            else:
                self.history_lines.append(f"Directory not found: {target}")
            self.history_lines.append("")
            return

        if cmd_str.lower() in ("exit", "quit"):
            self.is_terminated = True
            self.history_lines.append("Console session terminated.")
            return

        # Run via shell
        if sys.platform == "win32":
            argv = ["cmd.exe", "/c", cmd_str]
        else:
            argv = ["/bin/sh", "-c", cmd_str]

        self.active_runner = ProcessRunner(argv, cwd=self.cwd)
        self.active_runner.start()

    def wait(self, timeout: Optional[float] = None) -> Optional[int]:
        if self.active_runner:
            rc = self.active_runner.wait(timeout=timeout)
            self.history_lines.extend(self.active_runner.lines)
            self.history_lines.append("")
            self.active_runner = None
            return rc
        return 0

    def stop(self) -> None:
        if self.active_runner and self.active_runner.is_running:
            self.active_runner.terminate()
            self.active_runner.wait(timeout=1.0)

    def terminate(self) -> None:
        if self.active_runner and self.active_runner.is_running:
            self.active_runner.terminate()
            self.active_runner.wait(timeout=1.0)

    def handle_key(self, key: int) -> bool:
        """Handle keystroke for interactive console input."""
        if key in (10, 13):
            line = self.input_buffer
            self.input_buffer = ""
            self.cursor_pos = 0
            self.execute_line(line)
            return True
        elif key in (8, 127, getattr(curses, "KEY_BACKSPACE", -999)):
            if self.cursor_pos > 0:
                self.input_buffer = (
                    self.input_buffer[: self.cursor_pos - 1]
                    + self.input_buffer[self.cursor_pos :]
                )
                self.cursor_pos -= 1
            return True
        elif key == getattr(curses, "KEY_LEFT", -999):
            if self.cursor_pos > 0:
                self.cursor_pos -= 1
            return True
        elif key == getattr(curses, "KEY_RIGHT", -999):
            if self.cursor_pos < len(self.input_buffer):
                self.cursor_pos += 1
            return True
        elif 32 <= key <= 126:
            ch = chr(key)
            self.input_buffer = (
                self.input_buffer[: self.cursor_pos]
                + ch
                + self.input_buffer[self.cursor_pos :]
            )
            self.cursor_pos += 1
            return True

        return False
