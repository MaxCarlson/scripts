#!/usr/bin/env python3
import sys
import time
from contextlib import contextmanager
from typing import Iterator, Optional


@contextmanager
def progress(label: str, total: Optional[int] = None, quiet: bool = False) -> Iterator["ProgressBar"]:
    """Progress that writes to STDERR only (keeps stdout clean for JSON)."""
    bar = ProgressBar(label, total, quiet=quiet)
    try:
        bar._start()
        yield bar
    finally:
        bar._finish()


class ProgressBar:
    def __init__(self, label: str, total: Optional[int], quiet: bool = False):
        self.label = label
        self.total = total
        self.current = 0
        self.start = None
        self.quiet = quiet

    def _start(self):
        self.start = time.time()
        if not self.quiet:
            sys.stderr.write(f"[{self.label}] 0\n")
            sys.stderr.flush()

    def update(self, current: Optional[int] = None, info: Optional[str] = None):
        if current is not None:
            self.current = current
        if self.quiet:
            return
        elapsed = time.time() - (self.start or time.time())
        if self.total:
            pct = (self.current / self.total) * 100.0
            line = f"[{self.label}] {self.current}/{self.total} {pct:5.1f}%  {elapsed:0.1f}s"
        else:
            line = f"[{self.label}] {self.current}   {elapsed:0.1f}s"
        if info:
            line += f" | {info}"
        sys.stderr.write(line + "\n")
        sys.stderr.flush()

    def _finish(self):
        if not self.quiet:
            sys.stderr.flush()
