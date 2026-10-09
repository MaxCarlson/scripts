"""Read-only audit of URL lists against one or more download roots."""

from __future__ import annotations

import json
import re
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable
from urllib.parse import urlsplit

from .input import canonicalize_url
from .models import InputUrl

IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".avif", ".bmp"}
_NHENTAI = re.compile(r"^https?://(?:www\.)?nhentai\.net/g/(\d+)/?$")


@dataclass(frozen=True, slots=True)
class DestinationAudit:
    resolved: dict[str, list[Path]]
    unresolved: list[InputUrl]
    duplicates: dict[str, list[Path]]
    details: dict[str, dict[str, Any]]


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
    for path in folder.iterdir():
        if path.is_file() and path.suffix.lower() in IMAGE_SUFFIXES and (match := _PAGE_FILE.fullmatch(path.name)):
            pages[int(match.group("page"))].append(path)

    valid_pages: set[int] = set()
    corrupt_pages: set[int] = set()
    for page, paths in pages.items():
        for path in paths:
            try:
                valid = path.stat().st_size > 0 and image_validator(path)
            except OSError:
                valid = False
            if valid:
                valid_pages.add(page)
            else:
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
    if issue_pages or extra_pages:
        completeness = "incomplete"
    elif expected_count is None:
        completeness = "unknown"
    else:
        completeness = "complete"
    integrity = "issues" if corrupt_pages or duplicate_pages else "valid" if pages else "unverified"
    return {
        "completeness": completeness,
        "image_integrity": integrity,
        "expected_images": expected_count,
        "present_images": len(pages),
        "valid_images": len(valid_pages),
        "missing_pages": sorted(missing_pages),
        "corrupt_pages": sorted(corrupt_pages),
        "duplicate_pages": sorted(duplicate_pages),
        "extra_pages": sorted(extra_pages),
        "repair_eligible": False,
    }


def _has_images(folder: Path) -> bool:
    try:
        return any(path.is_file() and path.suffix.lower() in IMAGE_SUFFIXES for path in folder.rglob("*"))
    except OSError:
        return False


def _walk_strings(value: Any) -> Iterable[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from _walk_strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from _walk_strings(item)


def _normal(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()


def _folder_url_values(folder: Path) -> set[str]:
    values: set[str] = set()
    for metadata in folder.rglob("*.json"):
        try:
            if metadata.stat().st_size > 2_000_000:
                continue
            payload = json.loads(metadata.read_text(encoding="utf-8", errors="replace"))
        except (OSError, json.JSONDecodeError):
            continue
        for value in _walk_strings(payload):
            try:
                values.add(canonicalize_url(value))
            except ValueError:
                continue
    return values


def _manhwa_slug(url: str) -> str | None:
    parts = urlsplit(url)
    host = (parts.hostname or "").lower().rstrip(".")
    path = [item for item in parts.path.split("/") if item]
    if host in {"hdporncomics.com", "www.hdporncomics.com"} and len(path) >= 2 and path[0].lower() == "manhwa":
        return _normal(path[-1])
    return None


def audit_destinations(
    inputs: list[InputUrl],
    destinations: list[Path],
    progress: Callable[[str], None] | None = None,
    *,
    metadata_resolver: Callable[[str], Any] | None = None,
    image_validator: Callable[[Path], bool] = _validate_image,
) -> DestinationAudit:
    """Match known URL identities to populated top-level gallery folders.

    URL metadata is authoritative.  In its absence, normal gallery-dl nhentai
    IDs and HDPornComics manhwa slugs provide safe folder-name matches.
    """
    metadata_urls: dict[str, list[Path]] = defaultdict(list)
    folders_by_name: dict[str, list[Path]] = defaultdict(list)
    candidate_folders_by_name: dict[str, list[Path]] = defaultdict(list)
    for index, destination in enumerate(destinations, start=1):
        if not destination.is_dir():
            if progress:
                progress(f"[{index}/{len(destinations)}] Skipping missing destination: {destination}")
            continue
        if progress:
            progress(f"[{index}/{len(destinations)}] Scanning destination: {destination}")
        indexed = 0
        for folder_number, folder in enumerate(destination.iterdir(), start=1):
            if progress and folder_number % 50 == 0:
                progress(
                    f"[{index}/{len(destinations)}] Checked {folder_number} top-level folders in {destination.name}"
                )
            if not folder.is_dir() or folder.name == "_partial":
                continue
            candidate_folders_by_name[folder.name.casefold()].append(folder)
            populated = _has_images(folder)
            if populated:
                indexed += 1
                folders_by_name[folder.name.casefold()].append(folder)
            for url in _folder_url_values(folder):
                metadata_urls[url].append(folder)
        if progress:
            progress(f"[{index}/{len(destinations)}] Indexed {indexed} populated download folder(s)")

    resolved: dict[str, list[Path]] = {}
    for item in inputs:
        matches = list(metadata_urls.get(item.canonical_url, []))
        nhentai = _NHENTAI.fullmatch(item.canonical_url)
        if nhentai:
            identity = re.compile(rf"(?:^|-){re.escape(nhentai.group(1))}(?:\s+-|$)")
            matches.extend(
                folder
                for paths in candidate_folders_by_name.values()
                for folder in paths
                if identity.search(folder.name)
            )
        slug = _manhwa_slug(item.canonical_url)
        if slug:
            matches.extend(
                folder for paths in folders_by_name.values() for folder in paths if _normal(folder.name) == slug
            )
        if matches:
            resolved[item.canonical_url] = sorted(set(matches))

    unresolved = [item for item in inputs if item.canonical_url not in resolved]
    duplicates = {name: sorted(paths) for name, paths in folders_by_name.items() if len(paths) > 1}

    details: dict[str, dict[str, Any]] = {}
    for index, item in enumerate(inputs, start=1):
        matches = resolved.get(item.canonical_url, [])
        base: dict[str, Any] = {
            "folder_status": "missing" if not matches else "ambiguous" if len(matches) > 1 else "matched",
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
        }
        if len(matches) == 1:
            expected_count: int | None = None
            nhentai = _NHENTAI.fullmatch(item.canonical_url)
            if nhentai and metadata_resolver is not None:
                try:
                    if progress:
                        progress(f"[{index}/{len(inputs)}] Resolving expected page count for nhentai {nhentai.group(1)}")
                    metadata = metadata_resolver(nhentai.group(1))
                    expected_count = int(metadata.page_count)
                except Exception as exc:
                    base["metadata_error"] = type(exc).__name__
            base.update(_inspect_pages(matches[0], expected_count, image_validator=image_validator))
        elif len(matches) > 1:
            base["completeness"] = "unknown"
            base["metadata_error"] = "ambiguous destination match"
        details[item.canonical_url] = base
    if progress:
        progress(
            f"Matching complete: {len(resolved)} found, {len(unresolved)} missing, {len(duplicates)} duplicate group(s)"
        )
    return DestinationAudit(resolved=resolved, unresolved=unresolved, duplicates=duplicates, details=details)


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
