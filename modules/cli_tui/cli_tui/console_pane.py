from __future__ import annotations

import curses
import os
import sys
import threading
from typing import Any, Callable, List, Optional

from .process_runner import ProcessRunner


def detect_shell() -> tuple[str, str, list[str]]:
    """Detect the shell that spawned this process or is standard on the system.

    Returns (executable_path, short_name, command_prefix_list).
    """
    if sys.platform != "win32":
        shell = os.environ.get("SHELL", "/bin/sh")
        return shell, os.path.basename(shell), [shell, "-c"]

    # On Windows: walk up ancestor process tree to find parent shell
    try:
        import ctypes
        from ctypes import wintypes
        import shutil

        kernel32 = ctypes.windll.kernel32
        TH32CS_SNAPPROCESS = 0x00000002
        hSnap = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)

        class PROCESSENTRY32W(ctypes.Structure):
            _fields_ = [
                ("dwSize", wintypes.DWORD),
                ("cntUsage", wintypes.DWORD),
                ("th32ProcessID", wintypes.DWORD),
                ("th32DefaultHeapID", ctypes.c_size_t),
                ("th32ModuleID", wintypes.DWORD),
                ("cntThreads", wintypes.DWORD),
                ("th32ParentProcessID", wintypes.DWORD),
                ("pcPriClassBase", ctypes.c_long),
                ("dwFlags", wintypes.DWORD),
                ("szExeFile", ctypes.c_wchar * 260),
            ]

        pe = PROCESSENTRY32W()
        pe.dwSize = ctypes.sizeof(PROCESSENTRY32W)
        tree: dict[int, tuple[int, str]] = {}
        if kernel32.Process32FirstW(hSnap, ctypes.byref(pe)):
            while True:
                tree[pe.th32ProcessID] = (pe.th32ParentProcessID, pe.szExeFile)
                if not kernel32.Process32NextW(hSnap, ctypes.byref(pe)):
                    break
        kernel32.CloseHandle(hSnap)

        curr = os.getpid()
        while curr in tree:
            p_pid, p_exe = tree[curr]
            name = p_exe.lower()
            if "pwsh" in name:
                full = shutil.which("pwsh") or p_exe
                return full, "pwsh", [full, "-NoLogo", "-Command"]
            if "powershell" in name:
                full = shutil.which("powershell") or p_exe
                return full, "powershell", [full, "-NoLogo", "-Command"]
            if name == "cmd.exe":
                full = shutil.which("cmd") or os.environ.get("COMSPEC", "cmd.exe")
                return full, "cmd", [full, "/c"]
            if any(s in name for s in ("bash", "zsh")):
                full = shutil.which(p_exe) or p_exe
                return full, name, [full, "-c"]
            curr = p_pid
    except Exception:
        pass

    import shutil

    if shutil.which("pwsh"):
        full = shutil.which("pwsh")
        return full, "pwsh", [full, "-NoLogo", "-Command"]
    if "PSModulePath" in os.environ and shutil.which("powershell"):
        full = shutil.which("powershell")
        return full, "powershell", [full, "-NoLogo", "-Command"]
    comspec = os.environ.get("COMSPEC", "cmd.exe")
    return comspec, "cmd", [comspec, "/c"]


class ConsolePaneRunner:
    """Embedded interactive shell console runner for cli_tui panes."""

    def __init__(self, cwd: Optional[str] = None) -> None:
        self.cwd: str = os.path.abspath(cwd or os.getcwd())
        self.shell_exe, self.shell_name, self.shell_prefix = detect_shell()
        self.history_lines: List[str] = [
            f"Interactive Shell Console [{self.shell_name}]",
            f"Working directory: {self.cwd}",
            "Type commands and press Enter. Type 'exit' to close.",
            "",
        ]
        self.active_runner: Optional[ProcessRunner] = None
        self.input_buffer: str = ""
        self.cursor_pos: int = 0
        self.is_terminated: bool = False
        self._output_lock = threading.RLock()
        self._output_listeners: set[Callable[[str], None]] = set()
        self._subscribed_runners: set[ProcessRunner] = set()
        self._runner_unsubscribers: dict[
            ProcessRunner, dict[Callable[[str], None], Callable[[], None]]
        ] = {}

    @property
    def is_running(self) -> bool:
        if self.active_runner:
            return bool(self.active_runner.is_running)
        return False

    @property
    def proc(self) -> Optional[Any]:
        if self.active_runner:
            return self.active_runner.proc
        return None

    @property
    def pid(self) -> Optional[int]:
        if self.active_runner:
            return self.active_runner.pid
        return None

    def subscribe_output(
        self,
        callback: Callable[[str], None],
        *,
        seed_callback: Optional[Callable[[List[str]], None]] = None,
    ) -> Callable[[], None]:
        """Subscribe to the full console transcript, including future commands."""
        with self._output_lock:
            if seed_callback:
                seed_callback(self.lines)
            self._output_listeners.add(callback)
            self._subscribe_active_runner(callback)

        def unsubscribe() -> None:
            with self._output_lock:
                self._output_listeners.discard(callback)
                for runner in tuple(self._subscribed_runners):
                    self._unsubscribe_runner_callback(runner, callback)

        return unsubscribe

    def snapshot_and_subscribe(
        self, callback: Callable[[str], None]
    ) -> tuple[list[str], Callable[[], None]]:
        """Atomically snapshot the console and subscribe to its current and future output."""
        with self._output_lock:
            self._output_listeners.add(callback)
            lines = list(self.history_lines)
            runner = self.active_runner
            if runner is not None:
                runner_lines, unsubscribe_runner = runner.snapshot_and_subscribe(callback)
                self._subscribed_runners.add(runner)
                self._runner_unsubscribers.setdefault(runner, {})[
                    callback
                ] = unsubscribe_runner
                lines.extend(runner_lines)

        def unsubscribe() -> None:
            with self._output_lock:
                self._output_listeners.discard(callback)
                for subscribed in tuple(self._subscribed_runners):
                    self._unsubscribe_runner_callback(subscribed, callback)

        return lines, unsubscribe

    def _subscribe_active_runner(self, callback: Callable[[str], None]) -> None:
        runner = self.active_runner
        if runner is not None and callback not in self._runner_unsubscribers.get(runner, {}):
            unsubscribe = runner.subscribe_output(callback)
            self._runner_unsubscribers.setdefault(runner, {})[callback] = unsubscribe
            self._subscribed_runners.add(runner)

    def _unsubscribe_runner_callback(
        self, runner: ProcessRunner, callback: Callable[[str], None]
    ) -> None:
        callbacks = self._runner_unsubscribers.get(runner)
        unsubscribe = callbacks.pop(callback, None) if callbacks is not None else None
        if unsubscribe is not None:
            unsubscribe()
        if not callbacks:
            self._runner_unsubscribers.pop(runner, None)
            self._subscribed_runners.discard(runner)

    def _record_history(self, line: str) -> None:
        with self._output_lock:
            self.history_lines.append(line)
            listeners = tuple(self._output_listeners)
        for listener in listeners:
            try:
                listener(line + "\n")
            except Exception:
                with self._output_lock:
                    self._output_listeners.discard(listener)

    @property
    def lines(self) -> List[str]:
        output = list(self.history_lines)
        if self.active_runner:
            output.extend(self.active_runner.lines)
        return output

    def execute_line(self, line: str) -> None:
        if self.active_runner:
            self.history_lines.extend(self.active_runner.lines)
            self._record_history("")
            self._forget_runner(self.active_runner)
            self.active_runner = None

        cmd_str = line.strip()
        self._record_history(f"[{self.cwd}]> {line}")

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
                self._record_history(f"Directory changed to: {self.cwd}")
            else:
                self._record_history(f"Directory not found: {target}")
            self._record_history("")
            return

        if cmd_str.lower() in ("exit", "quit"):
            self.is_terminated = True
            self._record_history("Console session terminated.")
            return

        # Run via detected shell
        argv = list(self.shell_prefix) + [cmd_str]

        self.active_runner = ProcessRunner(argv, cwd=self.cwd)
        with self._output_lock:
            for callback in self._output_listeners:
                self._subscribe_active_runner(callback)
        self.active_runner.start()

    def wait(self, timeout: Optional[float] = None) -> Optional[int]:
        if self.active_runner:
            rc = self.active_runner.wait(timeout=timeout)
            self.history_lines.extend(self.active_runner.lines)
            self._record_history("")
            self._forget_runner(self.active_runner)
            self.active_runner = None
            return rc
        return 0

    def _forget_runner(self, runner: ProcessRunner) -> None:
        with self._output_lock:
            for callback in tuple(self._runner_unsubscribers.get(runner, {})):
                self._unsubscribe_runner_callback(runner, callback)

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
