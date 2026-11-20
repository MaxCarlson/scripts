"""Cross-platform terminal scrollback / session-log capture with explicit backend boundaries."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

CLEAR_SEQUENCES: tuple[str, ...] = (
    "\x1b[3J\x1b[H\x1b[2J",
    "\x1b[H\x1b[2J",
    "\x1b[2J\x1b[H",
    "\x1b[H\x1b[J",
)

_ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)")


@dataclass(frozen=True)
class CaptureResult:
    """Result of a terminal buffer or session-log capture attempt."""

    ok: bool
    backend: str  # tmux, session_log, unsupported
    text: str = ""
    clear_found: bool = False
    clear_index: int = -1
    error: Optional[str] = None
    guidance: Optional[str] = None


def strip_ansi(text: str) -> str:
    """Remove ANSI CSI/OSC escape sequences from captured text."""
    return _ANSI_RE.sub("", text)


def extract_since_last_clear(raw_text: str) -> tuple[str, bool, int]:
    """Return text after the most recent terminal clear sequence, if any."""
    best_pos = -1
    best_seq = ""
    for seq in CLEAR_SEQUENCES:
        pos = raw_text.rfind(seq)
        if pos > best_pos:
            best_pos = pos
            best_seq = seq
    if best_pos != -1:
        return raw_text[best_pos + len(best_seq):], True, best_pos
    return raw_text, False, -1


def capture_tmux_buffer(
    capture_fn: Callable[[str], Optional[str]],
    *,
    full: bool = False,
    start_line: str = "-10000",
) -> CaptureResult:
    """Capture tmux pane scrollback and optionally slice after the last clear sequence."""
    raw = capture_fn(start_line)
    if raw is None:
        return CaptureResult(
            ok=False,
            backend="tmux",
            error="Failed to capture tmux pane buffer.",
        )

    if full:
        return CaptureResult(ok=True, backend="tmux", text=strip_ansi(raw).strip())

    sliced, found, pos = extract_since_last_clear(raw)
    return CaptureResult(
        ok=True,
        backend="tmux",
        text=strip_ansi(sliced).strip(),
        clear_found=found,
        clear_index=pos,
    )


def resolve_session_log_path(explicit_path: Optional[Path | str] = None) -> Optional[Path]:
    """Resolve an optional recorded session log from explicit path, env, or SHLVL log."""
    if explicit_path:
        return Path(explicit_path).expanduser()
    env_log = os.environ.get("CLIPBOARD_SESSION_LOG")
    if env_log:
        return Path(env_log).expanduser()
    shlvl = os.environ.get("SHLVL")
    if shlvl:
        candidate = Path.home() / f".term_log.session_shlvl_{shlvl}"
        if candidate.is_file():
            return candidate
    return None


def capture_session_log(
    log_path: Path,
    *,
    full: bool = False,
) -> CaptureResult:
    """Capture text from a forward-recorded session log file."""
    if not log_path.is_file():
        return CaptureResult(
            ok=False,
            backend="session_log",
            error=f"Session log file not found: '{log_path}'.",
        )
    try:
        raw = log_path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return CaptureResult(
            ok=False,
            backend="session_log",
            error=f"Could not read session log '{log_path}': {exc}",
        )

    if full:
        return CaptureResult(ok=True, backend="session_log", text=strip_ansi(raw).strip())

    sliced, found, pos = extract_since_last_clear(raw)
    return CaptureResult(
        ok=True,
        backend="session_log",
        text=strip_ansi(sliced).strip(),
        clear_found=found,
        clear_index=pos,
    )


def unsupported_native_terminal_result() -> CaptureResult:
    """Return an explicit, honest error for native Windows Terminal / non-tmux scrollback."""
    return CaptureResult(
        ok=False,
        backend="unsupported",
        error=(
            "Cannot capture existing terminal scrollback from a child Python process "
            "outside tmux (Windows Terminal / ConPTY does not expose scrollback to subprocesses)."
        ),
        guidance=(
            "Options: (1) Use Windows Terminal's native `exportBuffer` / `copy` action, "
            "(2) Run inside tmux, or "
            "(3) Record a session with `Start-Transcript` / `script` and pass `--session-log <path>` "
            "(or set CLIPBOARD_SESSION_LOG)."
        ),
    )
