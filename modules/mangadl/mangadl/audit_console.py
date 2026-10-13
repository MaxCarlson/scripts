"""Readable audit/repair console fields and a transient audit progress row."""

from __future__ import annotations

import os
import shutil
import sys
import textwrap
import time
from collections import deque
from typing import Any

from termdash.live import LiveBlock
from termdash.progress import ProgressBar
from termdash.utils import color_text, fmt_hms


def styled(text: str, color: str) -> str:
    if sys.stdout.isatty() and "NO_COLOR" not in os.environ and os.environ.get("TERM") != "dumb":
        return color_text(text, color)
    return text


def field(label: str, value: Any, *, indent: int = 4, color: str | None = None) -> str:
    prefix = " " * indent + f"{label}: "
    width = max(50, min(140, shutil.get_terminal_size().columns))
    text = textwrap.fill(str(value), width=width, initial_indent=prefix,
                         subsequent_indent=" " * len(prefix), break_on_hyphens=False)
    return styled(text, color) if color else text


class AuditProgress:
    def __init__(self, enabled: bool) -> None:
        self.enabled = enabled
        self.block = LiveBlock(stream=sys.stderr, enabled=enabled)
        self.interactive = self.block.interactive
        self.started = time.monotonic()
        self.samples = deque([(self.started, 0)])
        self.state: dict[str, Any] = {}
        self.message = ""
        self.last_log = 0.0
        self.last_render = 0.0
        self.last_phase = ""

    def log(self, message: str) -> None:
        if not self.enabled:
            return
        self.block.log(f"Audit: {message}")

    def update(self, state: dict[str, Any]) -> None:
        if not self.enabled:
            return
        phase = state["phase"]
        if phase == "finished":
            self.close()
            return
        previous = self.state
        self.state = dict(state)
        if phase == "complete" and (previous.get("phase") != "complete" or previous.get("index") != state["index"]):
            self.samples.append((time.monotonic(), state["index"]))
            while len(self.samples) > 1 and self.samples[0][0] < time.monotonic() - 15:
                self.samples.popleft()
        self.message = " | ".join(self._lines())
        if self.interactive:
            if (phase != self.last_phase or time.monotonic() - self.last_render >= 0.1
                    or phase == "images" and state["checked"] == state["image_total"]):
                self.block.update(self._lines)
                self.last_render = time.monotonic()
        elif time.monotonic() - self.last_log >= 5 or phase == "complete" and state["index"] == state["total"]:
            print(f"Audit progress: {self.message}", file=sys.stderr, flush=True)
            self.last_log = time.monotonic()
        self.last_phase = phase

    def _lines(self) -> list[str]:
        state = self.state
        if not state:
            return []
        index, total, phase = state["index"], state["total"], state["phase"]
        done = index if phase == "complete" else index - 1
        now = time.monotonic()
        samples = [(stamp, count) for stamp, count in tuple(self.samples) if stamp >= now - 15]
        rate = (done - samples[0][1]) / max(.001, now - samples[0][0]) if samples else 0
        eta = fmt_hms((total - done) / rate) if rate > 0 else "unknown"
        label = "Folder" if state.get("folder") else "URL"
        name = state.get("folder") or state.get("url", "unknown source")
        if phase == "images":
            checked, count = state["checked"], state["image_total"]
            bar = ProgressBar("images", count or 1, checked, width=28, charset="ascii")
            item = f"Images: {bar} {checked}/{count} checked"
        elif phase == "complete":
            item = "Item: checked"
        else:
            frame = ("|", "/", "-", "\\")[int((now - self.started) * 4) % 4]
            item = f"Item: {frame} {'fetching metadata' if phase == 'metadata' else 'listing local images'} (progress unknown)"
        overall = ProgressBar("items", total or 1, done, width=28, charset="ascii")
        return [f"{label} {index}/{total}: {name}", item,
                f"Overall: {overall} {done}/{total} | Elapsed: {fmt_hms(now - self.started)} | ETA: {eta}"]

    def close(self) -> None:
        self.block.close()
        self.message = ""
