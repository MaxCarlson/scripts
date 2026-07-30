from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class SeriesPageMetadata:
    source_url: str
    canonical_url: str
    source_host: str
    title: str
    alternate_titles: tuple[str, ...]
    cover_url: str


@dataclass(frozen=True, slots=True)
class FolderMatch:
    folder: Path
    method: str
    score: float


@dataclass(frozen=True, slots=True)
class CoverResult:
    url: str
    status: str
    folder: str | None = None
    match_method: str | None = None
    match_score: float | None = None
    title: str | None = None
    cover_url: str | None = None
    cover_file: str | None = None
    kavita_series_id: int | None = None
    source_file: str | None = None
    source_line: int | None = None
    message: str = ""
