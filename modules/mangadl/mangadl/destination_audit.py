"""Read-only audit of URL lists against one or more download roots."""

from __future__ import annotations

import json
import re
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from .library_index import backfill_source_indexes, resolve_url_folders, scan_library
from .models import InputUrl

IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".avif", ".bmp"}
_NHENTAI = re.compile(r"^https?://(?:www\.)?nhentai\.net/g/(\d+)/?$")


@dataclass(frozen=True, slots=True)
class DestinationAudit:
    resolved: dict[str, list[Path]]
    unresolved: list[InputUrl]
    duplicates: dict[str, list[Path]]
    details: dict[str, dict[str, Any]]
    untracked_folders: list[Path]
    index_backfill: dict[str, int] | None = None


_PAGE_FILE = re.compile(r"^(?P<page>\d+)\.[^.]+$", re.IGNORECASE)


def _validate_image(path: Path) -> bool:
    """Decode image structure without loading pixel data into memory."""
    from PIL import Image, UnidentifiedImageError

    try:
        with Image.open(path) as image:
            image.verify()
        return True
    except (OSError, ValueError, UnidentifiedImageError, Image.DecompressionBombError):
        return False


def _inspect_pages(
    folder: Path,
    expected_count: int | None,
    *,
    image_validator: Callable[[Path], bool],
) -> dict[str, Any]:
    pages: dict[int, list[Path]] = defaultdict(list)
    image_files: list[Path] = []
    try:
        image_files = sorted(
            (path for path in folder.rglob("*") if path.is_file() and path.suffix.lower() in IMAGE_SUFFIXES),
            key=lambda path: str(path.relative_to(folder)).casefold(),
        )
    except OSError:
        pass
    for path in image_files:
        if path.parent == folder and (match := _PAGE_FILE.fullmatch(path.name)):
            pages[int(match.group("page"))].append(path)

    valid_pages: set[int] = set()
    corrupt_pages: set[int] = set()
    corrupt_files: list[str] = []
    corrupt_paths: set[Path] = set()
    valid_images = 0
    valid_paths: set[Path] = set()
    for path in image_files:
        try:
            valid = path.stat().st_size > 0 and image_validator(path)
        except OSError:
            valid = False
        if valid:
            valid_images += 1
            valid_paths.add(path)
        else:
            corrupt_files.append(str(path.relative_to(folder)))
            corrupt_paths.add(path)
    for page, paths in pages.items():
        if any(path in valid_paths for path in paths):
            valid_pages.add(page)
        if any(path in corrupt_paths for path in paths):
            # This branch is guarded by the separate path-based report below;
            # numeric identity remains corrupt only when no valid copy exists.
            if page not in valid_pages:
                corrupt_pages.add(page)

    duplicate_pages = {page for page, paths in pages.items() if len(paths) > 1}
    if expected_count is not None:
        expected_pages = set(range(1, expected_count + 1))
        missing_pages = expected_pages - valid_pages
        extra_pages = valid_pages - expected_pages
    elif valid_pages:
        # A numbered sequence beginning after page 1 proves a leading gap even
        # when source metadata could not be resolved. Its end remains unknown.
        observed_max = max(valid_pages)
        missing_pages = set(range(1, observed_max + 1)) - valid_pages
        extra_pages = set()
    else:
        missing_pages = set()
        extra_pages = set()

    issue_pages = missing_pages | corrupt_pages | duplicate_pages
    if issue_pages or extra_pages or corrupt_files:
        completeness = "incomplete"
    elif expected_count is None:
        completeness = "unknown"
    else:
        completeness = "complete"
    integrity = "issues" if corrupt_files or duplicate_pages else "valid" if image_files else "unverified"
    return {
        "completeness": completeness,
        "image_integrity": integrity,
        "expected_images": expected_count,
        "present_images": len(image_files),
        "valid_images": valid_images,
        "missing_pages": sorted(missing_pages),
        "corrupt_pages": sorted(corrupt_pages),
        "duplicate_pages": sorted(duplicate_pages),
        "extra_pages": sorted(extra_pages),
        "corrupt_files": corrupt_files,
        "repair_eligible": False,
    }


def _has_images(folder: Path) -> bool:
    try:
        return any(path.is_file() and path.suffix.lower() in IMAGE_SUFFIXES for path in folder.rglob("*"))
    except OSError:
        return False


def _flat_numbered_layout(folder: Path) -> bool:
    try:
        images = [path for path in folder.rglob("*") if path.is_file() and path.suffix.lower() in IMAGE_SUFFIXES]
    except OSError:
        return False
    return bool(images) and all(path.parent == folder and _PAGE_FILE.fullmatch(path.name) for path in images)


def audit_destinations(
    inputs: list[InputUrl],
    destinations: list[Path],
    progress: Callable[[str], None] | None = None,
    *,
    metadata_resolver: Callable[[str], Any] | None = None,
    page_resolver: Callable[[str], Any] | None = None,
    image_validator: Callable[[Path], bool] = _validate_image,
    backfill_index: bool = False,
) -> DestinationAudit:
    """Match known URL identities to populated top-level gallery folders.

    URL metadata is authoritative.  In its absence, normal gallery-dl nhentai
    IDs and HDPornComics manhwa slugs provide safe folder-name matches.
    """
    library = scan_library(destinations, progress=progress)
    index_backfill = (
        backfill_source_indexes(
            (item.canonical_url for item in inputs), library, progress=progress
        )
        if backfill_index
        else None
    )
    folders_by_name: dict[str, list[Path]] = defaultdict(list)
    for row in library:
        folders_by_name[row.path.name.casefold()].append(row.path)

    resolved: dict[str, list[Path]] = {}
    for item in inputs:
        matches = [row.path for row in resolve_url_folders(item.canonical_url, library)]
        if matches:
            resolved[item.canonical_url] = sorted(set(matches))

    unresolved = [item for item in inputs if item.canonical_url not in resolved]
    duplicates = {name: sorted(paths) for name, paths in folders_by_name.items() if len(paths) > 1}

    details: dict[str, dict[str, Any]] = {}
    for index, item in enumerate(inputs, start=1):
        match_rows = resolve_url_folders(item.canonical_url, library)
        matches = [row.path for row in match_rows]
        identity_ambiguous = any(row.identity_status == "ambiguous" for row in match_rows)
        base: dict[str, Any] = {
            "folder_status": "missing" if not matches else "ambiguous" if len(matches) > 1 or identity_ambiguous else "matched",
            "completeness": "unknown",
            "image_integrity": "unverified",
            "expected_images": None,
            "present_images": 0,
            "valid_images": 0,
            "missing_pages": [],
            "corrupt_pages": [],
            "duplicate_pages": [],
            "extra_pages": [],
            "repair_eligible": False,
            "metadata_error": None,
            "identity_evidence": None,
            "expected_page_evidence": None,
            "missing_image_count": None,
        }
        if len(matches) == 1 and not identity_ambiguous:
            base["identity_evidence"] = next(
                (row.evidence for row in library if row.path == matches[0]), None
            )
            expected_count: int | None = None
            comparable = False
            nhentai = _NHENTAI.fullmatch(item.canonical_url)
            if nhentai and metadata_resolver is not None:
                try:
                    if progress:
                        progress(f"[{index}/{len(inputs)}] Resolving expected page count for nhentai {nhentai.group(1)}")
                    metadata = metadata_resolver(nhentai.group(1))
                    expected_count = int(metadata.page_count)
                    base["expected_page_evidence"] = "nhentai gallery metadata"
                    comparable = True
                except Exception as exc:
                    base["metadata_error"] = type(exc).__name__
            elif page_resolver is not None:
                try:
                    page_set = page_resolver(item.canonical_url)
                    if page_set is not None:
                        expected_count = int(page_set.count)
                        base["expected_page_evidence"] = page_set.evidence
                        comparable = bool(page_set.complete_identity_set and _flat_numbered_layout(matches[0]))
                except Exception as exc:
                    base["metadata_error"] = type(exc).__name__
            base.update(
                _inspect_pages(
                    matches[0], expected_count if comparable else None, image_validator=image_validator
                )
            )
            if expected_count is not None and not comparable:
                base["expected_images"] = expected_count
                base["missing_image_count"] = max(0, expected_count - base["valid_images"])
                base["completeness"] = "incomplete" if base["valid_images"] < expected_count else "unknown"
        elif matches:
            base["completeness"] = "unknown"
            base["metadata_error"] = "ambiguous destination match"
        details[item.canonical_url] = base
    if progress:
        progress(
            f"Matching complete: {len(resolved)} found, {len(unresolved)} missing, "
            f"{len(duplicates)} duplicate folder group(s)"
        )
    matched_paths = {path for paths in resolved.values() for path in paths}
    untracked = sorted({row.path for row in library if row.path not in matched_paths and _has_images(row.path)})
    return DestinationAudit(
        resolved=resolved,
        unresolved=unresolved,
        duplicates=duplicates,
        details=details,
        untracked_folders=untracked,
        index_backfill=index_backfill,
    )


def audit_library(
    destinations: list[Path],
    progress: Callable[[str], None] | None = None,
    *,
    metadata_resolver: Callable[[str], Any] | None = None,
    page_resolver: Callable[[str], Any] | None = None,
    image_validator: Callable[[Path], bool] = _validate_image,
) -> list[dict[str, Any]]:
    """Audit every top-level library folder without requiring a URL file."""
    folders = scan_library(destinations, progress=progress)
    results: list[dict[str, Any]] = []
    for index, row in enumerate(folders, 1):
        expected_count = None
        metadata_error = None
        page_evidence = None
        match = _NHENTAI.fullmatch(row.source_url or "")
        if match and metadata_resolver is not None:
            try:
                expected_count = int(metadata_resolver(match.group(1)).page_count)
                page_evidence = "nhentai gallery metadata"
            except Exception as exc:
                metadata_error = type(exc).__name__
        elif row.source_url and page_resolver is not None:
            try:
                page_set = page_resolver(row.source_url)
                if page_set is not None:
                    expected_count = int(page_set.count)
                    page_evidence = page_set.evidence
            except Exception as exc:
                metadata_error = type(exc).__name__
        comparable = bool(expected_count is not None and (match or _flat_numbered_layout(row.path)))
        details = _inspect_pages(
            row.path, expected_count if comparable else None, image_validator=image_validator
        )
        if expected_count is not None and not comparable:
            details["expected_images"] = expected_count
            details["missing_image_count"] = max(0, expected_count - details["valid_images"])
            details["completeness"] = "incomplete" if details["valid_images"] < expected_count else "unknown"
        results.append(
            {
                "folder": str(row.path),
                "folder_name": row.path.name,
                "source_url": row.source_url,
                "identity_status": row.identity_status,
                "identity_evidence": row.evidence,
                "backend": row.backend,
                "metadata_error": metadata_error,
                "expected_page_evidence": page_evidence,
                **details,
            }
        )
        if progress and index % 50 == 0:
            progress(f"Audited {index}/{len(folders)} library folders")
    return results


def write_audit_outputs(
    audit: DestinationAudit, missing_output: Path | None = None, duplicates_output: Path | None = None
) -> None:
    if missing_output is not None:
        missing_output.parent.mkdir(parents=True, exist_ok=True)
        missing_output.write_text("".join(f"{item.url}\n" for item in audit.unresolved), encoding="utf-8")
    if duplicates_output is not None:
        duplicates_output.parent.mkdir(parents=True, exist_ok=True)
        duplicates_output.write_text(
            json.dumps(
                [
                    {"folder_name": name, "locations": [str(path) for path in paths]}
                    for name, paths in audit.duplicates.items()
                ],
                indent=2,
                sort_keys=True,
            ),
            encoding="utf-8",
        )
