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
    inputs: list[InputUrl], destinations: list[Path], progress: Callable[[str], None] | None = None
) -> DestinationAudit:
    """Match known URL identities to populated top-level gallery folders.

    URL metadata is authoritative.  In its absence, normal gallery-dl nhentai
    IDs and HDPornComics manhwa slugs provide safe folder-name matches.
    """
    metadata_urls: dict[str, list[Path]] = defaultdict(list)
    folders_by_name: dict[str, list[Path]] = defaultdict(list)
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
            if not folder.is_dir() or folder.name == "_partial" or not _has_images(folder):
                continue
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
                folder for paths in folders_by_name.values() for folder in paths if identity.search(folder.name)
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
    if progress:
        progress(
            f"Matching complete: {len(resolved)} found, {len(unresolved)} missing, {len(duplicates)} duplicate group(s)"
        )
    return DestinationAudit(resolved=resolved, unresolved=unresolved, duplicates=duplicates)


def write_audit_outputs(audit: DestinationAudit, missing_output: Path, duplicates_output: Path) -> None:
    missing_output.parent.mkdir(parents=True, exist_ok=True)
    missing_output.write_text("".join(f"{item.url}\n" for item in audit.unresolved), encoding="utf-8")
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
