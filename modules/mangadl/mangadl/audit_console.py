"""Readable audit/repair console fields and a transient audit progress row."""

from __future__ import annotations

import os
import shutil
import sys
import textwrap
import time
from typing import Any

from termdash.loading import LoadingIndicator
from termdash.progress import ProgressBar
from termdash.utils import color_text


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
        self.interactive = enabled and sys.stderr.isatty() and os.environ.get("TERM") != "dumb"
        self.indicator = LoadingIndicator(stream=sys.stderr, frames=("|", "/", "-", "\\"))
        self.message = ""
        self.last_log = 0.0
        self.last_render = 0.0
        self.last_phase = ""

    def log(self, message: str) -> None:
        if not self.enabled:
            return
        if self.interactive:
            self.indicator.stop()
        print(f"Audit: {message}", file=sys.stderr, flush=True)
        if self.interactive and self.message:
            self.indicator.update(self.message)
            self.indicator.start()

    def update(self, state: dict[str, Any]) -> None:
        if not self.enabled:
            return
        phase = state["phase"]
        if phase == "finished":
            self.close()
            return
        index, total = state["index"], state["total"]
        done = index if phase == "complete" else index - 1
        overall = str(ProgressBar("urls", total, done, width=18, charset="ascii", show_percent=False))
        description = {"metadata": "fetching metadata", "scanning": "listing local images",
                       "images": "checking images", "complete": "checked"}.get(phase, phase)
        images = ""
        if phase == "images":
            checked, count = state["checked"], state["image_total"]
            bar = ProgressBar("images", count, checked, width=18, charset="ascii")
            images = f" {bar} {checked}/{count}"
        self.message = f"{overall} URL {index}/{total} | {description}{images} | {state['url']}"
        if self.interactive:
            width = max(40, shutil.get_terminal_size().columns - 3)
            if (phase != self.last_phase or time.monotonic() - self.last_render >= 0.1
                    or phase == "images" and state["checked"] == state["image_total"]):
                self.indicator.update(self.message[:width])
                self.last_render = time.monotonic()
            self.indicator.start()
        elif phase != "images" or time.monotonic() - self.last_log >= 5:
            print(f"Audit progress: {self.message}", file=sys.stderr, flush=True)
            self.last_log = time.monotonic()
        self.last_phase = phase

    def close(self) -> None:
        self.indicator.stop()
        self.message = ""
