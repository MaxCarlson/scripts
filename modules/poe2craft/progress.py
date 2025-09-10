#!/usr/bin/env python3
from __future__ import annotations

import contextlib
import sys
import time
from dataclasses import dataclass
from typing import Optional

# Optional best-effort Termdash adapter (won't fail if not installed)
try:
    import termdash  # type: ignore
except Exception:  # pragma: no cover
    termdash = None  # sentinel


@dataclass
class _State:
    label: str
    total: int
    n: int = 0
    start: float = 0.0
    last_len: int = 0


class _TTYBar:
    def __init__(self, label: str, total: int):
        self.state = _State(label=label, total=max(1, total), start=time.time())

    def update(self, n: Optional[int] = None, info: str = "") -> None:
        st = self.state
        if n is None:
            st.n += 1
        else:
            st.n = n
        st.n = max(0, min(st.n, st.total))
        elapsed = time.time() - st.start
        pct = 100.0 * st.n / st.total
        line = f"[{st.label}] {st.n}/{st.total}  {pct:4.1f}%   {elapsed:4.1f}s"
        if info:
            line += f" | {info}"
        # erase previous line
        pad = " " * max(0, st.last_len - len(line))
        sys.stdout.write("\r" + line + pad)
        sys.stdout.flush()
        st.last_len = len(line)

    def close(self, final_info: str = "") -> None:
        self.update(info=final_info)
        sys.stdout.write("\n")
        sys.stdout.flush()


@contextlib.contextmanager
def progress(label: str, total: int):
    """
    Context manager yielding a progress object with .update([n], info)
    Usage:
        with progress("Download", 10) as bar:
            ...
            bar.update(info="parsed 3")
    """
    # If a compatible termdash API exists, feel free to adapt here.
    bar = _TTYBar(label, total)
    try:
        yield bar
    finally:
        bar.close()
