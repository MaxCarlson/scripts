from __future__ import annotations

import json
from difflib import SequenceMatcher
from pathlib import Path
from typing import Mapping, Sequence
from urllib.parse import urlsplit

from ..input import canonicalize_url, collect_inputs
from ..models import InputUrl
from .constants import METADATA_DIR_NAME, SOURCE_MANIFEST_NAME, URL_FILE_RE
from .files import has_content_images
from .models import FolderMatch, SeriesPageMetadata
from .util import normalize_name, walk_strings


def discover_url_files(urls_folder: Path) -> list[Path]:
    root = urls_folder.expanduser().resolve()
    if not root.is_dir():
        raise ValueError(f"URL folder does not exist or is not a directory: {root}")
    return sorted(
        (path for path in root.rglob("*") if path.is_file() and URL_FILE_RE.fullmatch(path.name)),
        key=lambda path: (str(path.parent).casefold(), path.name.casefold()),
    )


def collect_url_folder(urls_folder: Path) -> tuple[list[InputUrl], list[dict[str, object]], list[Path]]:
    files = discover_url_files(urls_folder)
    if not files:
        raise ValueError(f"no url*.txt files were found under: {urls_folder.expanduser().resolve()}")
    inputs, rejected = collect_inputs(files, [])
    return inputs, rejected, files


def series_folders(destinations: Sequence[Path]) -> list[Path]:
    folders: list[Path] = []
    seen: set[Path] = set()
    for destination in destinations:
        root = destination.expanduser().resolve()
        if not root.is_dir():
            continue
        for folder in root.iterdir():
            if not folder.is_dir() or folder.name in {"_partial", METADATA_DIR_NAME}:
                continue
            if has_content_images(folder) and folder not in seen:
                seen.add(folder)
                folders.append(folder)
    return sorted(folders, key=lambda path: str(path).casefold())


def folder_urls(folder: Path) -> set[str]:
    values: set[str] = set()
    preferred = folder / METADATA_DIR_NAME / SOURCE_MANIFEST_NAME
    candidates = [preferred, *(path for path in folder.rglob("*.json") if path != preferred)]
    for path in candidates:
        if not path.is_file():
            continue
        try:
            if path.stat().st_size > 2_000_000:
                continue
            payload = json.loads(path.read_text(encoding="utf-8", errors="replace"))
        except (OSError, json.JSONDecodeError):
            continue
        for value in walk_strings(payload):
            try:
                values.add(canonicalize_url(value))
            except ValueError:
                continue
    return values


def build_folder_url_index(folders: Sequence[Path]) -> dict[str, list[Path]]:
    index: dict[str, list[Path]] = {}
    for folder in folders:
        for url in folder_urls(folder):
            index.setdefault(url, []).append(folder)
    return index


def url_slug(url: str) -> str:
    path = [part for part in urlsplit(url).path.split("/") if part]
    return normalize_name(path[-1]) if path else ""


def name_score(folder_name: str, candidates: Sequence[str]) -> float:
    folder = normalize_name(folder_name)
    best = 0.0
    for candidate in candidates:
        value = normalize_name(candidate)
        if not value:
            continue
        if folder == value:
            best = max(best, 95.0)
        elif folder.endswith(" " + value) or value.endswith(" " + folder):
            best = max(best, 90.0)
        elif len(value) >= 8 and (value in folder or folder in value):
            best = max(best, 86.0)
        else:
            ratio = SequenceMatcher(None, folder, value).ratio()
            if ratio >= 0.92:
                best = max(best, 80.0 + (ratio - 0.92) * 100.0)
    return min(best, 94.0)


def match_folder(
    url: str,
    folders: Sequence[Path],
    *,
    metadata: SeriesPageMetadata | None = None,
    url_index: Mapping[str, Sequence[Path]] | None = None,
) -> tuple[FolderMatch | None, list[FolderMatch]]:
    canonical = canonicalize_url(url)
    metadata_folders = (
        list(url_index.get(canonical, ()))
        if url_index is not None
        else [folder for folder in folders if canonical in folder_urls(folder)]
    )
    matches = [FolderMatch(folder, "source-metadata", 100.0) for folder in metadata_folders]
    if matches:
        unique = sorted(matches, key=lambda item: str(item.folder).casefold())
        return (unique[0] if len(unique) == 1 else None), unique

    candidates = [url_slug(canonical)]
    if metadata is not None:
        candidates.extend([metadata.title, *metadata.alternate_titles])
    for folder in folders:
        score = name_score(folder.name, candidates)
        if score:
            matches.append(FolderMatch(folder, "normalized-name", score))
    matches.sort(key=lambda item: (-item.score, str(item.folder).casefold()))
    if not matches:
        return None, []
    if len(matches) == 1 or matches[0].score >= matches[1].score + 8.0:
        return matches[0], matches
    return None, matches
