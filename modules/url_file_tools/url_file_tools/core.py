"""Core planning and filesystem operations for URL-list files."""

from __future__ import annotations

import codecs
import os
import re
import shutil
import tempfile
from collections import OrderedDict
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Iterable, Sequence
from urllib.parse import urlsplit, urlunsplit

import tldextract

NUMBERED_LINE = re.compile(r"^(?P<indent>[ \t]*)(?P<number>\d+)\.\s+(?P<rest>.*)$")
DEFAULT_GLOBS = ("*.txt", "*.url", "*.urls")
_EXTRACT = tldextract.TLDExtract(suffix_list_urls=())


class UrlFileError(Exception):
    """A user-correctable URL file error."""


@dataclass(frozen=True)
class SourceLocation:
    path: Path
    line_number: int

    def display(self, root: Path | None = None) -> str:
        path = self.path
        if root is not None:
            try:
                path = path.relative_to(root)
            except ValueError:
                pass
        return f"{path}:{self.line_number}"


@dataclass(frozen=True)
class UrlRecord:
    url: str
    domain: str
    source: SourceLocation
    mobile_rewritten: bool = False


@dataclass(frozen=True)
class DuplicateOccurrence:
    url: str
    first: SourceLocation
    duplicate: SourceLocation


@dataclass(frozen=True)
class InvalidRow:
    text: str
    source: SourceLocation
    reason: str


@dataclass
class MergeStats:
    source_files: int = 0
    rows_read: int = 0
    blank_rows: int = 0
    comment_rows: int = 0
    numbered_prefixes_removed: int = 0
    mobile_prefixes_removed: int = 0
    valid_urls: int = 0
    invalid_rows: int = 0
    duplicate_occurrences: int = 0
    duplicate_groups: int = 0
    unique_urls: int = 0
    unique_base_domains: int = 0


@dataclass
class MergePlan:
    root: Path
    source_files: list[Path]
    records: list[UrlRecord]
    unique_records: list[UrlRecord]
    duplicates: list[DuplicateOccurrence]
    invalid: list[InvalidRow]
    stats: MergeStats

    def selected_records(self, remove_duplicates: bool) -> list[UrlRecord]:
        return self.unique_records if remove_duplicates else self.records


@dataclass(frozen=True)
class TextDocument:
    text: str
    encoding: str


@dataclass(frozen=True)
class LineChange:
    line_number: int
    before: str
    after: str
    kind: str


@dataclass
class NormalizePlan:
    path: Path
    original: TextDocument
    new_text: str
    changes: list[LineChange] = field(default_factory=list)


def read_text_document(path: Path) -> TextDocument:
    """Decode common BOM encodings, strict UTF-8, then Latin-1 as a lossless fallback."""
    data = path.read_bytes()
    encodings: list[str]
    if data.startswith(codecs.BOM_UTF32_LE) or data.startswith(codecs.BOM_UTF32_BE):
        encodings = ["utf-32"]
    elif data.startswith(codecs.BOM_UTF8):
        encodings = ["utf-8-sig"]
    elif data.startswith(codecs.BOM_UTF16_LE) or data.startswith(codecs.BOM_UTF16_BE):
        encodings = ["utf-16"]
    else:
        encodings = ["utf-8", "latin-1"]

    for encoding in encodings:
        try:
            return TextDocument(data.decode(encoding), encoding)
        except UnicodeDecodeError:
            continue
    raise UrlFileError(f"Could not decode text file: {path}")


def strip_numbered_prefix(text: str, allow_leading_whitespace: bool = False) -> tuple[str, bool]:
    """Remove a leading ``N. `` prefix while optionally preserving indentation."""
    match = NUMBERED_LINE.match(text)
    if match is None or (match.group("indent") and not allow_leading_whitespace):
        return text, False
    prefix = match.group("indent") if allow_leading_whitespace else ""
    return prefix + match.group("rest"), True


def normalize_mobile_url(text: str) -> tuple[str, bool]:
    """Validate an HTTP(S) URL, lowercase its scheme/host, and remove an exact ``m.`` host label."""
    try:
        parsed = urlsplit(text)
        port = parsed.port
    except ValueError as exc:
        raise UrlFileError(str(exc)) from exc

    if parsed.scheme.lower() not in {"http", "https"}:
        raise UrlFileError("URL scheme must be http or https")
    if not parsed.hostname:
        raise UrlFileError("URL has no hostname")

    hostname = parsed.hostname.lower()
    rewritten = hostname.startswith("m.") and len(hostname) > 2
    if rewritten:
        hostname = hostname[2:]

    userinfo = parsed.netloc.rsplit("@", 1)[0] + "@" if "@" in parsed.netloc else ""
    rendered_host = f"[{hostname}]" if ":" in hostname and not hostname.startswith("[") else hostname
    netloc = f"{userinfo}{rendered_host}"
    if port is not None:
        netloc += f":{port}"

    return urlunsplit((parsed.scheme.lower(), netloc, parsed.path, parsed.query, parsed.fragment)), rewritten


def registered_domain(url: str) -> str:
    """Return the registered domain using tldextract's bundled Public Suffix List snapshot."""
    hostname = urlsplit(url).hostname or ""
    result = _EXTRACT(hostname)
    domain = result.top_domain_under_public_suffix
    return domain.lower() if domain else hostname.lower()


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _resolve_selected_path(root: Path, value: str, source: str) -> Path:
    candidate = Path(value)
    if not candidate.is_absolute():
        candidate = root / candidate
    candidate = candidate.resolve()
    if not _is_relative_to(candidate, root):
        raise UrlFileError(f"{source} entry escapes the target folder: {value}")
    if not candidate.is_file():
        raise UrlFileError(f"{source} entry is not a file: {value}")
    return candidate


def read_file_manifest(root: Path, manifest: Path) -> list[Path]:
    """Read relative file paths from a UTF-8 manifest, enforcing target-folder containment."""
    document = read_text_document(manifest)
    selected: list[Path] = []
    for line_number, raw in enumerate(document.text.splitlines(), 1):
        value = raw.strip()
        if not value or value.startswith("#"):
            continue
        try:
            selected.append(_resolve_selected_path(root, value, f"Manifest line {line_number}"))
        except UrlFileError as exc:
            raise UrlFileError(f"{manifest}: {exc}") from exc
    return selected


def discover_files(
    root: Path,
    *,
    names: Sequence[str] | None = None,
    manifest: Path | None = None,
    patterns: Sequence[str] = DEFAULT_GLOBS,
    recurse: bool = False,
    excluded_paths: Iterable[Path] = (),
    excluded_directories: Iterable[Path] = (),
) -> list[Path]:
    """Discover deterministic, distinct input files below ``root``."""
    root = root.resolve()
    if not root.is_dir():
        raise UrlFileError(f"Target folder does not exist: {root}")
    if names and manifest:
        raise UrlFileError("Use either --files or --file-list, not both")

    if names:
        candidates = [_resolve_selected_path(root, name, "--files") for name in names]
    elif manifest:
        candidates = read_file_manifest(root, manifest.resolve())
    else:
        candidates = []
        for pattern in patterns:
            iterator = root.rglob(pattern) if recurse else root.glob(pattern)
            candidates.extend(path.resolve() for path in iterator if path.is_file())

    excluded = {path.resolve() for path in excluded_paths}
    excluded_dirs = [path.resolve() for path in excluded_directories]
    unique: dict[str, Path] = {}
    for candidate in candidates:
        resolved = candidate.resolve()
        if resolved in excluded or any(_is_relative_to(resolved, directory) for directory in excluded_dirs):
            continue
        unique.setdefault(os.path.normcase(str(resolved)), resolved)
    return sorted(unique.values(), key=lambda path: str(path).casefold())


def build_merge_plan(
    root: Path,
    source_files: Sequence[Path],
    *,
    allow_leading_whitespace: bool = False,
) -> MergePlan:
    """Read and normalize URL rows while retaining duplicate and error provenance."""
    root = root.resolve()
    stats = MergeStats(source_files=len(source_files))
    records: list[UrlRecord] = []
    unique_records: list[UrlRecord] = []
    duplicates: list[DuplicateOccurrence] = []
    invalid: list[InvalidRow] = []
    first_by_url: dict[str, UrlRecord] = {}
    duplicate_urls: set[str] = set()

    for path in source_files:
        document = read_text_document(path)
        for line_number, raw in enumerate(document.text.splitlines(), 1):
            stats.rows_read += 1
            stripped = raw.strip()
            if not stripped:
                stats.blank_rows += 1
                continue
            if stripped.startswith("#"):
                stats.comment_rows += 1
                continue

            cleaned, was_numbered = strip_numbered_prefix(raw, allow_leading_whitespace)
            cleaned = cleaned.strip()
            if was_numbered:
                stats.numbered_prefixes_removed += 1
            source = SourceLocation(path.resolve(), line_number)
            try:
                normalized, mobile_rewritten = normalize_mobile_url(cleaned)
                domain = registered_domain(normalized)
            except UrlFileError as exc:
                invalid.append(InvalidRow(cleaned, source, str(exc)))
                stats.invalid_rows += 1
                continue

            record = UrlRecord(normalized, domain, source, mobile_rewritten)
            records.append(record)
            stats.valid_urls += 1
            if mobile_rewritten:
                stats.mobile_prefixes_removed += 1

            first = first_by_url.get(normalized)
            if first is None:
                first_by_url[normalized] = record
                unique_records.append(record)
            else:
                duplicates.append(DuplicateOccurrence(normalized, first.source, source))
                duplicate_urls.add(normalized)

    stats.duplicate_occurrences = len(duplicates)
    stats.duplicate_groups = len(duplicate_urls)
    stats.unique_urls = len(unique_records)
    stats.unique_base_domains = len({record.domain for record in unique_records})
    return MergePlan(root, list(source_files), records, unique_records, duplicates, invalid, stats)


def build_normalize_plan(
    path: Path,
    *,
    allow_leading_whitespace: bool = False,
    unique: bool = False,
    ignore_case: bool = False,
) -> NormalizePlan:
    """Plan in-place numbering removal and optional stable line deduplication."""
    document = read_text_document(path)
    changes: list[LineChange] = []
    output: list[str] = []
    seen: set[str] = set()

    for line_number, line in enumerate(document.text.splitlines(keepends=True), 1):
        content = line.rstrip("\r\n")
        ending = line[len(content) :]
        cleaned, was_numbered = strip_numbered_prefix(content, allow_leading_whitespace)
        key = cleaned.casefold() if ignore_case else cleaned
        if unique and key in seen:
            changes.append(LineChange(line_number, content, "(deleted duplicate)", "duplicate"))
            continue
        seen.add(key)
        if was_numbered:
            changes.append(LineChange(line_number, content, cleaned, "numbering"))
        output.append(cleaned + ending)

    return NormalizePlan(path, document, "".join(output), changes)


def grouped_output(records: Sequence[UrlRecord]) -> OrderedDict[str, list[str]]:
    """Group URLs by registered domain in stable first-seen order."""
    groups: OrderedDict[str, list[str]] = OrderedDict()
    for record in records:
        groups.setdefault(record.domain, []).append(record.url)
    return groups


def domain_filename(domain: str) -> str:
    """Render a registered domain as a portable, deterministic text filename."""
    try:
        ascii_domain = domain.encode("idna").decode("ascii")
    except UnicodeError:
        ascii_domain = domain
    safe = re.sub(r"[^A-Za-z0-9.-]+", "_", ascii_domain).strip("._")
    return f"{safe or 'unknown-domain'}.txt"


def atomic_write_text(path: Path, text: str, encoding: str = "utf-8") -> None:
    """Write a complete text file via same-directory atomic replacement."""
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(handle, "w", encoding=encoding, newline="") as stream:
            stream.write(text)
        os.replace(temporary, path)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def backup_file(path: Path) -> Path:
    """Create a collision-resistant timestamped sibling backup."""
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    destination = path.with_name(f"{path.name}.{stamp}.bak")
    shutil.copy2(path, destination)
    return destination


def render_duplicate_report(plan: MergePlan) -> str:
    """Render duplicate URLs with first and repeated source locations."""
    lines = ["Duplicate URL report", "====================", ""]
    for duplicate in plan.duplicates:
        lines.extend(
            [
                duplicate.url,
                f"  first:     {duplicate.first.display(plan.root)}",
                f"  duplicate: {duplicate.duplicate.display(plan.root)}",
                "",
            ]
        )
    return "\n".join(lines)
