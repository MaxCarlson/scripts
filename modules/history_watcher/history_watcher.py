#!/usr/bin/env python3
"""
history_watcher.py

Module that watches a Zsh history file in real time and applies
arbitrary, pluggable reminder rules to each new command with rich output.
"""
import os
import time
from pathlib import Path
from collections import deque

from rich.console import Console

console = Console()


class HistoryTailer:
    """
    Tails a history file, auto-reopening on rotation/truncation.
    """
    def __init__(self, path: Path, encoding: str = 'utf-8'):
        self.path = path
        self.encoding = encoding
        self._fd = None
        self._inode = None
        self._open_and_seek_end()

    def _open_and_seek_end(self):
        self._fd = open(self.path, 'r', encoding=self.encoding, errors='ignore')
        stat = os.fstat(self._fd.fileno())
        self._inode = stat.st_ino
        self._fd.seek(0, os.SEEK_END)

    def _check_rotated(self):
        try:
            stat = os.stat(self.path)
        except FileNotFoundError:
            return
        if stat.st_ino != self._inode:
            self._fd.close()
            self._open_and_seek_end()

    def tail_line(self) -> str:
        """
        Return next line (sans newline), or None if no new line.
        """
        self._check_rotated()
        line = self._fd.readline()
        return line.rstrip("\n") if line else None


def parse_zsh_history_line(raw: str) -> str:
    """
    Parse a Zsh history record of the form ": <timestamp>:<duration>;<command>".
    Splits on the first semicolon only.
    """
    parts = raw.split(';', 1)
    return parts[-1].strip()


class HistoryWatcher:
    """
    Core watcher: registers rules and monitors the history.
    """
    def __init__(self, history_file: Path, interval: float = 1.0, max_buffer: int = 10):
        self.history_file = history_file
        self.interval = interval
        self.max_buffer = max_buffer
        self.buffer = deque(maxlen=self.max_buffer)
        self.rules = []            # list of (name, fn)
        self._suggested = set()    # throttle key: (rule_name, command)

    def rule(self, name: str):
        """
        Decorator to register a reminder rule.
        """
        def decorator(fn):
            self.rules.append((name, fn))
            return fn
        return decorator

    def start(self):
        tailer = HistoryTailer(self.history_file)
        console.print(f"▶ [bold green]Watching[/bold green] {self.history_file} every {self.interval}s. Ctrl-C to quit.\n")
        try:
            while True:
                raw = tailer.tail_line()
                if raw is None:
                    time.sleep(self.interval)
                    continue

                cmd = parse_zsh_history_line(raw)
                for name, fn in self.rules:
                    suggestion = fn(cmd, list(self.buffer), self._suggested)
                    if suggestion:
                        console.print(f"[bold magenta]{name}[/bold magenta] [cyan]{suggestion}[/cyan]")
                        break

                self.buffer.appendleft(cmd)
        except KeyboardInterrupt:
            console.print("\n✋ [bold red]Exiting history watcher.[/bold red]")
