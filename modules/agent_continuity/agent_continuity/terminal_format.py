"""Terminal-safe formatting shared by dispatcher lists and selectors."""

from __future__ import annotations

import os
import re
import sys
import unicodedata
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from typing import TextIO

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


_SEMANTIC_CODES = {
    "gui": "94;1",
    "agent": "93;1",
    "provider_codex": "36",
    "provider_agy": "35",
    "timestamp": "90",
    "session": "37",
    "path_label": "2;37",
    "active": "32",
    "inactive": "33",
    "completed": "2",
    "runtime_in_use": "1;32",
    "runtime_not_observed": "2",
    "pending": "33",
    "unknown": "38;5;146",
    "failed": "31",
    "interrupted": "38;5;208",
    "unresolved": "31",
    "success": "32",
    "warning": "33",
    "error": "31",
    "label": "2;37",
}


def semantic_color(value: str, semantic: str, *, enabled: bool) -> str:
    """Apply a named semantic style while keeping the visible label intact."""
    code = _SEMANTIC_CODES.get(semantic)
    return f"\033[{code}m{value}\033[0m" if enabled and code and value else value


def pad_semantic(value: str, width: int, semantic: str, *, enabled: bool) -> str:
    """Clip and pad a field by terminal cells, styling only its visible text."""
    clipped = clip_display(value, width)
    padding = " " * max(0, width - display_width(clipped))
    return semantic_color(clipped, semantic, enabled=enabled) + padding


def provider_semantic(provider: str, *, enabled: bool) -> str:
    value = provider.upper()
    semantic = {"CODEX": "provider_codex", "AGY": "provider_agy"}.get(value)
    return semantic_color(value, semantic, enabled=enabled) if semantic else value


def lifecycle_semantic(state: str, *, enabled: bool) -> str:
    value = state.casefold()
    return semantic_color(value, value if value in {"active", "inactive", "completed"} else "", enabled=enabled)


def runtime_semantic(runtime: str, *, enabled: bool) -> str:
    value = runtime.upper()
    semantic = {
        "IN USE": "runtime_in_use",
        "NOT OBSERVED": "runtime_not_observed",
        "PENDING": "pending",
        "UNKNOWN": "unknown",
    }.get(value, "")
    return semantic_color(value, semantic, enabled=enabled) if semantic else value


def outcome_semantic(outcome: str, *, enabled: bool) -> str:
    value = outcome.casefold()
    if any(word in value for word in ("failed", "error", "abnormal", "unresolved", "blocked")):
        semantic = "unresolved" if "unresolved" in value else "failed"
    elif "interrupt" in value:
        semantic = "interrupted"
    elif (value in {"ok", "exited", "success", "succeeded", "completed", "normal_exit"}
          or value.startswith("exited ") or "success" in value or "normal_exit" in value):
        semantic = "success"
    elif any(word in value for word in ("launching", "running", "unverified", "pending")):
        semantic = "warning"
    else:
        semantic = "unknown"
    return semantic_color(outcome, semantic, enabled=enabled)


_ENABLE_VIRTUAL_TERMINAL_PROCESSING = 0x0004


def _console_handle(stream: TextIO) -> tuple[object, int] | None:
    """Return the Windows console API and OS handle for this output stream."""
    if os.name != "nt":
        return None
    try:
        import ctypes
        import msvcrt

        handle = msvcrt.get_osfhandle(stream.fileno())
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        return kernel32, handle
    except (AttributeError, OSError, ValueError):
        return None


def _console_mode_for_stream(stream: TextIO) -> int | None:
    console = _console_handle(stream)
    if console is None:
        return None
    import ctypes

    kernel32, handle = console
    flags = ctypes.c_uint32()
    kernel32.GetConsoleMode.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint32)]
    kernel32.GetConsoleMode.restype = ctypes.c_int
    if not kernel32.GetConsoleMode(ctypes.c_void_p(handle), ctypes.byref(flags)):
        return None
    return int(flags.value)


def _set_console_mode_for_stream(stream: TextIO, flags: int) -> bool:
    console = _console_handle(stream)
    if console is None:
        return False
    import ctypes

    kernel32, handle = console
    kernel32.SetConsoleMode.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
    kernel32.SetConsoleMode.restype = ctypes.c_int
    return bool(kernel32.SetConsoleMode(ctypes.c_void_p(handle), flags))


@contextmanager
def temporary_vt_processing(stream: TextIO, mode: str) -> Iterator[bool]:
    """Temporarily enable Windows VT output for this console and restore its mode."""
    if (os.name != "nt" or "NO_COLOR" in os.environ or mode == "never" or not stream.isatty()
            or (mode == "auto" and os.environ.get("TERM", "").casefold() == "dumb")):
        yield False
        return
    original = _console_mode_for_stream(stream)
    if original is None:
        yield False
        return
    if original & _ENABLE_VIRTUAL_TERMINAL_PROCESSING:
        yield True
        return
    if not _set_console_mode_for_stream(stream, original | _ENABLE_VIRTUAL_TERMINAL_PROCESSING):
        yield False
        return
    try:
        yield True
    finally:
        _set_console_mode_for_stream(stream, original)


def color_enabled(mode: str, *, is_tty: bool, stream: TextIO | None = None) -> bool:
    if "NO_COLOR" in os.environ or mode == "never":
        return False
    if mode == "always":
        return True
    if mode != "auto" or not is_tty or os.environ.get("TERM", "").casefold() == "dumb":
        return False
    if os.name == "nt":
        output = stream or sys.stdout
        if not output.isatty():
            return False
        mode_flags = _console_mode_for_stream(output)
        return bool(mode_flags is not None and mode_flags & _ENABLE_VIRTUAL_TERMINAL_PROCESSING)
    return True


def provider_color(provider: str, *, enabled: bool) -> str:
    return provider_semantic(provider, enabled=enabled)


def state_color(state: str, *, enabled: bool) -> str:
    value = state.lower()
    if value == "inactive":
        return f"\033[2;33m{value}\033[0m" if enabled else value
    return lifecycle_semantic(value, enabled=enabled)
