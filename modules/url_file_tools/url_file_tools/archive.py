"""Read-only archive adapters and URL matching APIs."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Mapping
from urllib.parse import urlsplit, urlunsplit

from .core import UrlFileError, normalize_mobile_url

YTAEDL_DOWNLOADED = frozenset({"downloaded", "already", "preexisting", "archive_rebuild"})
MANGADL_DOWNLOADED = frozenset({"succeeded", "succeeded_incomplete", "skipped_archive"})
MANGADL_FAILED_PREFIX = "failed_"


@dataclass(frozen=True)
class ArchiveEvidence:
    url: str
    downloaded: bool
    archive_status: str
    evidence_source: str
    evidence_line: int | None = None


@dataclass(frozen=True)
class ArchiveMatchResult:
    archive_type: str
    archive_path: Path
    evidence: tuple[ArchiveEvidence, ...]

    @property
    def downloaded(self) -> tuple[ArchiveEvidence, ...]:
        return tuple(item for item in self.evidence if item.downloaded)

    @property
    def not_downloaded(self) -> tuple[ArchiveEvidence, ...]:
        return tuple(item for item in self.evidence if not item.downloaded)


@dataclass(frozen=True)
class _StatusEvidence:
    status: str
    source: str
    line: int | None = None


def _normalize_url(url: str) -> str:
    normalized, _ = normalize_mobile_url(url.strip())
    return normalized


def _normalize_mangadl_url(url: str) -> str:
    normalized = _normalize_url(url)
    parts = urlsplit(normalized)
    return urlunsplit((parts.scheme, parts.netloc, parts.path or "/", parts.query, ""))


def _ytaedl_rank(status: str) -> int:
    return 2 if status.casefold() in YTAEDL_DOWNLOADED else 1


def _load_ytaedl_file(path: Path, statuses: dict[str, _StatusEvidence]) -> None:
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError as exc:
        raise UrlFileError(f"Could not read ytaedl archive {path}: {exc}") from exc
    for line_number, line in enumerate(lines, 1):
        parts = line.split("\t")
        if len(parts) < 6:
            continue
        status = parts[0].strip().casefold()
        raw_url = parts[-1].strip()
        if not status or not raw_url.startswith(("http://", "https://")):
            continue
        try:
            url = _normalize_url(raw_url)
        except UrlFileError:
            continue
        current = statuses.get(url)
        if current is None or _ytaedl_rank(status) > _ytaedl_rank(current.status):
            statuses[url] = _StatusEvidence(status, str(path), line_number)


def load_ytaedl_archive(path: Path) -> dict[str, _StatusEvidence]:
    """Load URL status evidence from one ytaedl archive file or an archive directory."""
    resolved = path.resolve()
    statuses: dict[str, _StatusEvidence] = {}
    if resolved.is_file():
        _load_ytaedl_file(resolved, statuses)
        return statuses
    if not resolved.is_dir():
        raise UrlFileError(f"ytaedl archive path does not exist: {resolved}")
    for archive_file in sorted(resolved.glob("*.txt")):
        if archive_file.name.endswith(".rebuild.txt"):
            continue
        _load_ytaedl_file(archive_file, statuses)
    return statuses


def _sqlite_tables(connection: sqlite3.Connection) -> set[str]:
    return {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}


def _sqlite_columns(connection: sqlite3.Connection, table: str) -> set[str]:
    return {row[1] for row in connection.execute(f'PRAGMA table_info("{table}")')}


def load_mangadl_state(path: Path) -> dict[str, _StatusEvidence]:
    """Load URL-level completion evidence from a mangadl manager-state database."""
    resolved = path.resolve()
    if not resolved.is_file():
        raise UrlFileError(f"mangadl state database does not exist: {resolved}")
    try:
        connection = sqlite3.connect(f"file:{resolved}?mode=ro", uri=True)
        connection.row_factory = sqlite3.Row
        try:
            if "jobs" not in _sqlite_tables(connection):
                raise UrlFileError(
                    "The SQLite file has no mangadl jobs table. A gallery-dl media archive cannot reliably prove "
                    "whole source-URL completion; provide mangadl's .mangadl/state.sqlite3 instead."
                )
            columns = _sqlite_columns(connection, "jobs")
            required = {"canonical_url", "state", "updated"}
            if not required.issubset(columns):
                raise UrlFileError("The jobs table is not a supported mangadl state schema")
            rows = connection.execute(
                "SELECT canonical_url,state,updated,rowid AS _rowid FROM jobs ORDER BY updated DESC,_rowid DESC"
            ).fetchall()
        finally:
            connection.close()
    except sqlite3.Error as exc:
        raise UrlFileError(f"Could not read mangadl state database {resolved}: {exc}") from exc

    grouped: dict[str, list[str]] = {}
    for row in rows:
        try:
            url = _normalize_mangadl_url(str(row["canonical_url"]))
        except UrlFileError:
            continue
        grouped.setdefault(url, []).append(str(row["state"]).casefold())

    statuses: dict[str, _StatusEvidence] = {}
    for url, states in grouped.items():
        successful = next((state for state in states if state in MANGADL_DOWNLOADED), None)
        status = successful or states[0]
        statuses[url] = _StatusEvidence(status, str(resolved))
    return statuses


def detect_archive_type(path: Path) -> str:
    """Detect ytaedl text archives or a URL-aware mangadl manager-state database."""
    resolved = path.resolve()
    if resolved.is_dir() or resolved.suffix.casefold() in {".txt", ".log"}:
        return "ytaedl"
    if not resolved.is_file():
        raise UrlFileError(f"Archive path does not exist: {resolved}")
    try:
        connection = sqlite3.connect(f"file:{resolved}?mode=ro", uri=True)
        try:
            tables = _sqlite_tables(connection)
            if "jobs" in tables and {"canonical_url", "state"}.issubset(_sqlite_columns(connection, "jobs")):
                return "mangadl"
            if "archive" in tables:
                raise UrlFileError(
                    "Detected a gallery-dl media archive. Its per-media keys do not reliably prove whole URL "
                    "completion; use mangadl's .mangadl/state.sqlite3 for URL matching."
                )
        finally:
            connection.close()
    except sqlite3.Error as exc:
        raise UrlFileError(f"Could not identify archive {resolved}: {exc}") from exc
    raise UrlFileError(f"Could not identify archive type: {resolved}")


def match_archive_urls(
    urls: Iterable[str],
    archive_path: Path,
    *,
    archive_type: str = "auto",
) -> ArchiveMatchResult:
    """Match URLs against downloader-owned, read-only archive evidence."""
    resolved = archive_path.resolve()
    selected_type = detect_archive_type(resolved) if archive_type == "auto" else archive_type
    if selected_type == "ytaedl":
        statuses: Mapping[str, _StatusEvidence] = load_ytaedl_archive(resolved)
        normalize = _normalize_url
        downloaded_statuses = YTAEDL_DOWNLOADED
    elif selected_type == "mangadl":
        statuses = load_mangadl_state(resolved)
        normalize = _normalize_mangadl_url
        downloaded_statuses = MANGADL_DOWNLOADED
    else:
        raise UrlFileError(f"Unsupported archive type: {selected_type}")

    evidence: list[ArchiveEvidence] = []
    seen: set[str] = set()
    for raw_url in urls:
        url = normalize(raw_url)
        if url in seen:
            continue
        seen.add(url)
        found = statuses.get(url)
        if found is None:
            evidence.append(ArchiveEvidence(url, False, "not-in-archive", str(resolved)))
            continue
        evidence.append(
            ArchiveEvidence(
                url=url,
                downloaded=found.status.casefold() in downloaded_statuses,
                archive_status=found.status,
                evidence_source=found.source,
                evidence_line=found.line,
            )
        )
    return ArchiveMatchResult(selected_type, resolved, tuple(evidence))
