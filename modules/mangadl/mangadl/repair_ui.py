from __future__ import annotations

import os
import sys
import time
from typing import Any

from termdash import utils as td_utils

from .ui import clip

PHASE_COLORS = {
    "scanning": "cyan",
    "metadata": "cyan",
    "planned": "green",
    "moving": "yellow",
    "verifying": "magenta",
    "complete": "green",
    "failed": "red",
}


def _bar(done: int, total: int, width: int, color: str) -> str:
    if total <= 0:
        return "[" + td_utils.color_text(">", color) + "." * max(0, width - 1) + "]"
    ratio = max(0.0, min(1.0, done / total))
    filled = int(width * ratio)
    return "[" + td_utils.color_text("=" * filled, color) + "." * (width - filled) + "]"


def render_repair_progress(state: dict[str, Any], *, width: int = 100) -> str:
    phase = str(state.get("phase", "scanning"))
    color = PHASE_COLORS.get(phase, "bright")
    mode = str(state.get("mode", "dry-run")).upper()
    elapsed = td_utils.fmt_hms(time.monotonic() - float(state.get("started", time.monotonic())))
    if phase in {"metadata", "planned"}:
        done, total = int(state.get("gallery_done", 0)), int(state.get("gallery_total", 0))
        progress_label = f"Metadata {done}/{total} galleries"
    elif phase == "moving":
        done, total = int(state.get("move_done", 0)), int(state.get("move_total", 0))
        progress_label = f"Files moved {done}/{total}"
    elif phase in {"verifying", "complete"}:
        done = int(state.get("verify_done", state.get("gallery_total", 0)))
        total = int(state.get("verify_total", state.get("gallery_total", 0)))
        progress_label = f"Verified {done}/{total} galleries"
    else:
        done = total = 0
        progress_label = "Scanning destination"
    bar_width = max(10, min(48, width - len(progress_label) - 4))
    current_id = state.get("current_id", "-")
    lines = [
        clip(
            f"{td_utils.color_text('mangadl repair-loose', 'bright')} | {td_utils.color_text(mode, 'yellow')} | {td_utils.color_text(phase.upper(), color)} | Elapsed {elapsed}",
            width,
        ),
        clip(f"{progress_label} {_bar(done, total, bar_width, color)}", width),
        clip(
            f"Loose files {state.get('file_total', 0)} | Expected {state.get('expected_pages', 0)} | Present {state.get('present_pages', 0)} | Missing {td_utils.color_text(str(state.get('missing_pages', 0)), 'red')} | Conflicts {td_utils.color_text(str(state.get('conflicts', 0)), 'red')}",
            width,
        ),
        clip(f"Current {td_utils.color_text('NH', 'red')}:{current_id} {state.get('current_title', '')}", width),
        clip(str(state.get("message", "")), width),
    ]
    return "\n".join(lines)


class RepairDashboard:
    def __init__(self, *, enabled: bool, mode: str) -> None:
        self.enabled = enabled
        self.interactive = enabled and sys.stdout.isatty()
        self.state: dict[str, Any] = {"phase": "scanning", "mode": mode, "started": time.monotonic()}
        self.last_render = 0.0
        self.last_phase = ""
        if enabled:
            self.render(force=True)

    def __call__(self, values: dict[str, Any]) -> None:
        phase = str(values.get("phase", self.state.get("phase", "")))
        force = phase != self.last_phase or values.get("message") == "resolving gallery metadata"
        self.state.update(values)
        self.render(force=force)

    def render(self, *, force: bool = False) -> None:
        if not self.enabled:
            return
        now = time.monotonic()
        interval = 0.1 if self.interactive else 5.0
        if not force and now - self.last_render < interval:
            return
        width = max(50, min(140, os.get_terminal_size().columns if self.interactive else 100))
        text = render_repair_progress(self.state, width=width)
        if self.interactive:
            print("\x1b[H\x1b[2J" + text, end="", flush=True)
        else:
            print(" | ".join(text.splitlines()[:2]), flush=True)
        self.last_render = now
        self.last_phase = str(self.state.get("phase", ""))

    def close(self) -> None:
        if self.enabled:
            self.render(force=True)
            if self.interactive:
                print()
