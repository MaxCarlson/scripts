"""Data models for filter-prune."""

from __future__ import annotations

import argparse
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


class SafePruneError(Exception):
    """Raised for expected user-facing errors."""


@dataclass(frozen=True)
class ToolConfig:
    """Executable resolution for external search tools."""

    fd_executable: Optional[str]
    rg_executable: Optional[str]


@dataclass(frozen=True)
class TargetInfo:
    """A matched target and the search root that produced it."""

    path: Path
    root: Path


@dataclass
class TargetSummary:
    """Summary metrics for matched targets."""

    target_count: int = 0
    file_count: int = 0
    folder_count: int = 0
    other_count: int = 0
    file_extension_counts: dict[str, int] = field(default_factory=dict)
    total_file_size_bytes: int = 0
    total_folder_size_bytes: int = 0

    @property
    def total_size_bytes(self) -> int:
        """Return file + folder byte totals."""
        return self.total_file_size_bytes + self.total_folder_size_bytes


@dataclass
class FilterTrace:
    """Verbose trace data for combined fd/rg filtering."""

    order: tuple[str, ...]
    fd_candidates: list[TargetInfo] = field(default_factory=list)
    rg_candidates: list[TargetInfo] = field(default_factory=list)
    filtered_by_fd: list[TargetInfo] = field(default_factory=list)
    filtered_by_rg: list[TargetInfo] = field(default_factory=list)


@dataclass
class OperationStats:
    """Summary of a dry-run or executed operation."""

    command: str
    dry_run: bool
    operation: str
    roots: list[Path]
    matched_count: int = 0
    would_be_affected_count: int = 0
    affected_count: int = 0
    skipped_count: int = 0
    failed_count: int = 0
    targets: list[TargetInfo] = field(default_factory=list)
    would_be_affected: list[TargetInfo] = field(default_factory=list)
    affected: list[TargetInfo] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    failures: list[str] = field(default_factory=list)
    summary: TargetSummary = field(default_factory=TargetSummary)
    trace: Optional[FilterTrace] = None


@dataclass
class ParsedCli:
    """Parsed CLI state after composable subcommand parsing."""

    operation: argparse.Namespace
    order: tuple[str, ...]
    fd: Optional[argparse.Namespace]
    rg: Optional[argparse.Namespace]


class Ansi:
    """ANSI escape codes used for optional terminal color."""

    RESET = "\033[0m"
    RED = "\033[31m"
    YELLOW = "\033[33m"
    GREEN = "\033[32m"
    CYAN = "\033[36m"
    MAGENTA = "\033[35m"
    DIM = "\033[2m"
