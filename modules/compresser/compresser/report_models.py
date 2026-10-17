"""Immutable presentation facts, shared between terminal and Markdown reports."""

from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class ReportContext:
    target: Path
    workspace: Path | None = None
    sampling: dict = field(default_factory=dict)
    snapshot: dict = field(default_factory=dict)
    cache: dict = field(default_factory=dict)
    settings: dict = field(default_factory=dict)
    status: str = "completed"
    operation: str = "comparison"


@dataclass(frozen=True)
class ReportSection:
    title: str
    headers: tuple[str, ...]
    rows: tuple[tuple[str, ...], ...]
    identity_columns: tuple[int, ...] = (0,)
    verbose: bool = False


@dataclass(frozen=True)
class CompressionReport:
    title: str
    operation: str
    status: str
    target: str
    sections: tuple[ReportSection, ...]
    notes: tuple[str, ...] = ()
    schema: int = 1
