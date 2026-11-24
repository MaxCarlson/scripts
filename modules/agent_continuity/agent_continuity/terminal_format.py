"""Terminal-safe formatting shared by dispatcher lists and selectors."""

from __future__ import annotations

import re
import unicodedata
from datetime import datetime

_ANSI = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")


def format_timestamp(value: str | None) -> str:
    """Render persisted UTC timestamps in local time; preserve unknown values."""
    if not value:
        return "—"
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed.astimezone().strftime("%Y-%m-%d %H:%M")
    except (ValueError, OverflowError):
        return "—"


def display_width(value: str) -> int:
    """Count terminal cells, ignoring ANSI escapes and combining marks."""
    visible = _ANSI.sub("", value)
    return sum(
        0 if unicodedata.combining(char) else
        2 if unicodedata.east_asian_width(char) in {"W", "F"} else 1
        for char in visible
    )


def clip_display(value: str, width: int) -> str:
    """Clip unstyled display text to a terminal-cell width with an ellipsis."""
    if width <= 0:
        return ""
    if display_width(value) <= width:
        return value
    target = max(0, width - 1)
    out: list[str] = []
    used = 0
    for char in value:
        cells = 0 if unicodedata.combining(char) else 2 if unicodedata.east_asian_width(char) in {"W", "F"} else 1
        if used + cells > target:
            break
        out.append(char)
        used += cells
    return "".join(out) + "…"


def pad_display(value: str, width: int) -> str:
    clipped = clip_display(value, width)
    return clipped + " " * max(0, width - display_width(clipped))


def color_enabled(mode: str, *, is_tty: bool) -> bool:
    import os

    return "NO_COLOR" not in os.environ and (mode == "always" or (mode == "auto" and is_tty))


def provider_color(provider: str, *, enabled: bool) -> str:
    value = provider.upper()
    code = {"CODEX": "36", "AGY": "35"}.get(value)
    return f"\033[{code}m{value}\033[0m" if enabled and code else value


def state_color(state: str, *, enabled: bool) -> str:
    value = state.lower()
    code = {"active": "32", "inactive": "2;33", "completed": "2"}.get(value)
    return f"\033[{code}m{value}\033[0m" if enabled and code else value
