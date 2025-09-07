"""
standard_ui.py

A standardized UI framework for console output across your modules.
Built on Rich, it provides:
  - Standard logging functions: log_info, log_warning, log_error, log_success.
  - A section context manager (section) to print headers/footers with elapsed time.
  - Global timer utilities to track overall runtime.
  - Helper functions to print tables, panels, steps, progress, and compact phase steps.
  - A simple session/phase model so setup scripts can emit a CMake-like summary.

Public API preserved; new helpers are additive and optional.
"""

from __future__ import annotations

import os
import sys
import time
import shlex
import subprocess
from dataclasses import dataclass, field
from typing import Iterable, List, Optional, Tuple, Dict
from contextlib import contextmanager

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.rule import Rule
from rich.text import Text
from rich.progress import (
    Progress,
    SpinnerColumn,
    TextColumn,
    BarColumn,
    TimeElapsedColumn,
)
from rich.status import Status
from rich.theme import Theme

# ---------- Console + Theme ----------

_THEME = Theme(
    {
        "ui.info": "cyan",
        "ui.step": "white",
        "ui.success": "green bold",
        "ui.warn": "yellow bold",
        "ui.error": "red bold",
        "ui.header": "bold blue",
        "ui.footer": "blue",
        "ui.dim": "dim",
        "ui.elapsed": "magenta",
    }
)

console = Console(theme=_THEME, highlight=False)

# ---------- Global State ----------

VERBOSE = False
_global_start_time: Optional[float] = None


def set_verbose(verbose: bool) -> None:
    """Set global verbosity. If False, log_info is suppressed."""
    global VERBOSE
    VERBOSE = bool(verbose)


# ---------- Timer Utilities ----------


def init_timer() -> None:
    """Initialize the global timer once at program start."""
    global _global_start_time
    _global_start_time = time.time()


def _ensure_timer() -> float:
    if _global_start_time is None:
        init_timer()
    return time.time() - (_global_start_time or time.time())


def print_global_elapsed() -> None:
    """Print elapsed time since init."""
    elapsed = _ensure_timer()
    console.print(f"[ui.header]Overall Elapsed Time: [ui.elapsed]{elapsed:.2f} sec[/]")


# ---------- Basic Logging (Preserved) ----------


def log_info(message: str) -> None:
    """Info is suppressed unless VERBOSE is True."""
    if VERBOSE:
        console.print(f"[ui.info]ℹ  {message}[/]")


def log_warning(message: str) -> None:
    console.print(f"[ui.warn]⚠️  {message}[/]")


def log_error(message: str) -> None:
    console.print(f"[ui.error]❌ {message}[/]")


def log_success(message: str) -> None:
    console.print(f"[ui.success]✅ {message}[/]")


def log_step(message: str) -> None:
    """One-off step with delta from global start."""
    delta = _ensure_timer()
    console.print(f"[ui.step]{message}[/] [ui.dim](+{delta:.2f}s)[/]")


# ---------- Sections (Preserved) ----------


@contextmanager
def section(title: str):
    """
    Prints a bold header before the body and a concise footer with per-section elapsed after.
    Keeps output compact and scannable.
    """
    start = time.time()
    console.rule(f"[ui.header]{title} - START[/]")
    try:
        yield
    finally:
        elapsed = time.time() - start
        console.rule(
            f"[ui.header]{title} - END [ui.dim](Elapsed: [ui.elapsed]{elapsed:.2f}s[/ui.elapsed])[/]"
        )


def print_section_header(title: str) -> None:
    console.rule(f"[ui.header]{title}[/]")


def print_section_footer(title: str = "END") -> None:
    console.rule(f"[ui.footer]{title}[/]")


# ---------- Tables / Panels (Preserved) ----------


def print_table(columns: List[str], rows: List[Iterable]) -> None:
    table = Table(show_header=True, header_style="bold magenta")
    for c in columns:
        table.add_column(str(c))
    for r in rows:
        table.add_row(*[str(x) for x in r])
    console.print(table)


def print_panel(message: str, title: str = "", style: str = "green") -> None:
    console.print(Panel(message, title=title, style=style, expand=False))


# ---------- Progress Helpers ----------


@contextmanager
def progress_bar(task_description: str, total: int):
    """
    Minimal progress bar helper. Yields (progress, task_id) so callers can update.
    """
    with Progress(
        SpinnerColumn(),
        TextColumn("[ui.info]{task.description}"),
        BarColumn(),
        TextColumn("{task.completed}/{task.total}"),
        TimeElapsedColumn(),
        transient=True,
        console=console,
    ) as progress:
        task_id = progress.add_task(task_description, total=total)
        yield progress, task_id


@contextmanager
def _status(msg: str):
    with console.status(f"[ui.info]{msg}", spinner="dots"):
        yield


def run_cmd_status(
    cmd: Iterable[str] | str,
    *,
    cwd: Optional[str | os.PathLike] = None,
    env: Optional[Dict[str, str]] = None,
    verbose_cmd: bool = False,
    check: bool = False,
    timeout: Optional[float] = None,
) -> subprocess.CompletedProcess:
    """
    Run a command with a transient spinner. Returns CompletedProcess.
    - If VERBOSE or verbose_cmd, prints the exact command.
    """
    cmd_list = cmd if isinstance(cmd, (list, tuple)) else shlex.split(str(cmd))
    if VERBOSE or verbose_cmd:
        console.print(f"[ui.info]$ {' '.join(shlex.quote(c) for c in cmd_list)}[/]")
    with _status(f"Running: {os.path.basename(cmd_list[0])}"):
        proc = subprocess.run(
            cmd_list,
            cwd=cwd,
            env=env,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    if check and proc.returncode != 0:
        raise subprocess.CalledProcessError(
            proc.returncode, cmd_list, proc.stdout, proc.stderr
        )
    return proc


# ---------- Argument Printer (Preserved) ----------


def print_parsed_args(args) -> None:
    from pathlib import Path

    script_path = Path(sys.argv[0]).resolve()
    console.rule(f"[ui.header]Script: {script_path}[/]")
    table = Table(show_header=True, header_style="bold magenta")
    table.add_column("Argument")
    table.add_column("Value", overflow="fold")
    for k, v in sorted(vars(args).items()):
        table.add_row(k, str(v))
    console.print(table)
    console.rule()


# ---------- Optional: Compact Phases & Summary ----------


@dataclass
class StepRecord:
    message: str
    status: str  # "ok", "warn", "fail"
    detail: Optional[str] = None
    elapsed: float = 0.0


@dataclass
class Phase:
    """Compact logger for steps within a section."""

    title: str
    _start: float = field(default_factory=time.time)
    _steps: List[StepRecord] = field(default_factory=list)

    def _delta(self) -> float:
        return time.time() - self._start

    @dataclass
    class _Step:
        parent: "Phase"
        message: str

        def ok(self) -> None:
            rec = StepRecord(self.message, "ok", elapsed=self.parent._delta())
            self.parent._steps.append(rec)
            console.print(
                f"[ui.success]  • {self.message}[/] [ui.dim](+{rec.elapsed:.2f}s)[/]"
            )

        def warn(self, detail: Optional[str] = None) -> None:
            rec = StepRecord(
                self.message, "warn", detail=detail, elapsed=self.parent._delta()
            )
            self.parent._steps.append(rec)
            tail = f" — {detail}" if detail else ""
            console.print(
                f"[ui.warn]  • {self.message}{tail}[/] [ui.dim](+{rec.elapsed:.2f}s)[/]"
            )

        def fail(self, detail: Optional[str] = None) -> None:
            rec = StepRecord(
                self.message, "fail", detail=detail, elapsed=self.parent._delta()
            )
            self.parent._steps.append(rec)
            tail = f" — {detail}" if detail else ""
            console.print(
                f"[ui.error]  • {self.message}{tail}[/] [ui.dim](+{rec.elapsed:.2f}s)[/]"
            )

    def step(self, message: str) -> "_Step":
        """Start a compact step; end it with .ok() / .warn() / .fail()."""
        return Phase._Step(self, message)

    def counts(self) -> Tuple[int, int, int]:
        oks = sum(s.status == "ok" for s in self._steps)
        warns = sum(s.status == "warn" for s in self._steps)
        fails = sum(s.status == "fail" for s in self._steps)
        return oks, warns, fails


@dataclass
class SetupSession:
    """Top-level run collector; use for a clean summary at the end."""

    name: str = "Setup"
    phases: List[Tuple[str, Phase]] = field(default_factory=list)
    _start: float = field(default_factory=time.time)

    @contextmanager
    def phase(self, title: str):
        with section(title):
            p = Phase(title)
            try:
                yield p
            finally:
                self.phases.append((title, p))

    def summary_rows(self) -> List[List[str]]:
        rows: List[List[str]] = []
        for title, ph in self.phases:
            ok, warn, fail = ph.counts()
            rows.append([title, str(ok), str(warn), str(fail)])
        return rows


def print_run_summary(
    session: SetupSession,
    *,
    show_only_problem_phases: bool = False,
) -> None:
    """Render a concise end-of-run summary like CMake."""
    console.rule(f"[ui.header]{session.name} Summary[/]")
    rows = []
    total_ok = total_warn = total_fail = 0

    for title, ph in session.phases:
        ok, warn, fail = ph.counts()
        total_ok += ok
        total_warn += warn
        total_fail += fail
        if show_only_problem_phases and fail == 0 and warn == 0:
            continue
        rows.append([title, ok, warn, fail])

    if rows:
        table = Table(show_header=True, header_style="bold magenta")
        table.add_column("Phase")
        table.add_column("OK", justify="right")
        table.add_column("Warn", justify="right")
        table.add_column("Fail", justify="right")
        for title, ok, warn, fail in rows:
            table.add_row(
                title,
                f"[ui.success]{ok}[/]",
                f"[ui.warn]{warn}[/]" if warn else "0",
                f"[ui.error]{fail}[/]" if fail else "0",
            )
        console.print(table)

    elapsed = time.time() - session._start
    if total_fail:
        console.print(
            f"[ui.error]❌ {session.name} completed with {total_fail} error(s) and {total_warn} warning(s).[/] [ui.dim](Elapsed {elapsed:.2f}s)[/]"
        )
    elif total_warn:
        console.print(
            f"[ui.warn]⚠️  {session.name} completed with {total_warn} warning(s).[/] [ui.dim](Elapsed {elapsed:.2f}s)[/]"
        )
    else:
        console.print(
            f"[ui.success]✅ All {session.name.lower()} steps completed successfully.[/] [ui.dim](Elapsed {elapsed:.2f}s)[/]"
        )


# ---------- Tiny helpers expected by __init__ (new) ----------

def blank(n: int = 1) -> None:
    """
    Print n blank lines. Kept simple to avoid Rich styling affecting layout.
    """
    for _ in range(max(1, n)):
        console.print("")


def status_line(message: str) -> None:
    """
    Print a subtle, single-line status.
    """
    console.print(f"[ui.dim]{message}[/]")


def rule(text: str = "") -> None:  # noqa: F811 (intentional shadow for public API)
    """
    Thin wrapper so callers can import `rule` from standard_ui.
    """
    console.rule(text)


def term_width() -> int:
    """
    Current terminal width as an int.
    """
    try:
        return console.size.width  # Rich-aware
    except Exception:
        return 80
