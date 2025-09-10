#!/usr/bin/env python3
import sys
import time
from contextlib import contextmanager
from typing import Iterator, Optional


@contextmanager
def progress(label: str, total: Optional[int] = None, quiet: bool = False) -> Iterator["ProgressBar"]:
    """
    Minimal progress printer that writes to STDERR only so stdout stays clean for JSON.
    """
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
            sys.stderr.write(f"[{self.label}] 0")
            sys.stderr.flush()

    def update(self, current: Optional[int] = None, info: Optional[str] = None):
        if current is not None:
            self.current = current
        if self.quiet:
            return
        elapsed = time.time() - (self.start or time.time())
        if self.total:
            pct = (self.current / self.total) * 100.0
            sys.stderr.write(f"\r[{self.label}] {self.current}/{self.total} {pct:5.1f}%  {elapsed:0.1f}s")
        else:
            sys.stderr.write(f"\r[{self.label}] {self.current}   {elapsed:0.1f}s")
        if info:
            sys.stderr.write(f" | {info}")
        sys.stderr.flush()

    def _finish(self):
        if not self.quiet:
            sys.stderr.write("\n")
            sys.stderr.flush()
