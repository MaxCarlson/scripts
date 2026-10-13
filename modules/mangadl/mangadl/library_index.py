"""Canonical URL-to-library-folder identity and provenance helpers."""

from __future__ import annotations

import json
import os
import re
import tempfile
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urlsplit

from .input import canonicalize_url

SOURCE_MANIFEST = ".mangadl-source.json"
SOURCE_SCHEMA = 1
_NHENTAI = re.compile(r"^https?://(?:www\.)?nhentai\.net/g/(\d+)/?$")
_IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".avif", ".bmp"}


@dataclass(frozen=True, slots=True)
class LibraryFolder:
    path: Path
    source_url: str | None
    backend: str | None
    identity_status: str
    evidence: str
    candidate_urls: tuple[str, ...] = ()
    manifest: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["path"] = str(self.path)
        return payload


def _metadata_urls(folder: Path) -> set[str]:
    urls: set[str] = set()
    for file in folder.rglob("*.json"):
        try:
            if file.stat().st_size > 2_000_000:
                continue
            payload = json.loads(file.read_text(encoding="utf-8", errors="replace"))
        except (OSError, json.JSONDecodeError):
            continue
        # Source identity is not every link in a metadata blob. Covers, artists,
        # advertisements and related galleries must not become gallery owners.
        documents = [payload]
        if isinstance(payload, dict):
            documents += [payload[key] for key in ("metadata", "gallery", "data")
                          if isinstance(payload.get(key), dict)]
        values = [document[key] for document in documents if isinstance(document, dict)
                  for key in ("url", "source_url", "gallery_url", "canonical_url", "webpage_url", "_source_url")
                  if isinstance(document.get(key), str)]
        for value in values:
            try:
                urls.add(canonicalize_url(value))
            except ValueError:
                pass
    return urls


def _has_images(folder: Path) -> bool:
    try:
        return any(path.is_file() and path.suffix.lower() in _IMAGE_SUFFIXES for path in folder.rglob("*"))
    except OSError:
        return False


def read_source_manifest(folder: Path) -> dict[str, Any] | None:
    path = folder / SOURCE_MANIFEST
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if payload.get("schema") != SOURCE_SCHEMA:
            return None
        payload["canonical_url"] = canonicalize_url(payload["canonical_url"])
        if payload.get("folder_name") != folder.name:
            return None
        return payload
    except (OSError, ValueError, TypeError, json.JSONDecodeError, KeyError):
        return None


def write_source_manifest(
    folder: Path,
    source_url: str,
    backend: str,
    *,
    expected_pages: list[str] | None = None,
    identity_evidence: str = "download_success",
) -> Path:
    """Atomically record a source/folder pair without replacing another identity."""
    folder = folder.resolve()
    if not folder.is_dir():
        raise ValueError(f"source manifest target is not a folder: {folder}")
    payload = {
        "schema": SOURCE_SCHEMA,
        "canonical_url": canonicalize_url(source_url),
        "backend": backend,
        "folder_name": folder.name,
        "expected_pages": expected_pages,
        "identity_evidence": identity_evidence,
    }
    target = folder / SOURCE_MANIFEST
    existing = read_source_manifest(folder)
    if target.exists():
        if existing is None or existing["canonical_url"] != payload["canonical_url"]:
            raise ValueError(f"refusing to replace an invalid or different source manifest: {target}")
        return target
    fd, temp_name = tempfile.mkstemp(prefix=".mangadl-source-", suffix=".tmp", dir=folder)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        # Hard-link publication is atomic and does not overwrite a manifest
        # concurrently written for a different URL. It also works on Windows
        # where os.rename refuses an existing target.
        try:
            os.link(temp_name, target)
        except FileExistsError:
            raced = read_source_manifest(folder)
            if raced is None or raced["canonical_url"] != payload["canonical_url"]:
                raise ValueError(f"refusing to replace a concurrently written source manifest: {target}")
    except BaseException:
        try:
            os.unlink(temp_name)
        except OSError:
            pass
        raise
    finally:
        try:
            os.unlink(temp_name)
        except FileNotFoundError:
            pass
    return target


def scan_library(roots: list[Path], *, progress=None) -> list[LibraryFolder]:
    rows: list[LibraryFolder] = []
    for root_index, root in enumerate(roots, 1):
        if not root.is_dir():
            if progress:
                progress(f"Skipping missing library root: {root}")
            continue
        for folder in sorted(root.iterdir(), key=lambda path: path.name.casefold()):
            if not folder.is_dir() or folder.name in {"_partial", ".mangadl"}:
                continue
            manifest = read_source_manifest(folder)
            urls = _metadata_urls(folder) if manifest is None else set()
            nhentai_candidate = re.search(r"(?:^|[-_ ])(?:nhentai[-_ ]?)?\d+(?:\s+-|$)", folder.name, re.IGNORECASE)
            if not (manifest or urls or nhentai_candidate or _has_images(folder)):
                continue
            if manifest:
                rows.append(LibraryFolder(
                    folder, manifest["canonical_url"], manifest.get("backend"), "matched", "mangadl_manifest",
                    (manifest["canonical_url"],), manifest,
                ))
                continue
            if len(urls) == 1:
                rows.append(LibraryFolder(folder, next(iter(urls)), None, "matched", "gallery_metadata", tuple(urls)))
            elif len(urls) > 1:
                rows.append(LibraryFolder(folder, None, None, "ambiguous", "multiple_metadata_urls", tuple(sorted(urls))))
            else:
                rows.append(
                    LibraryFolder(
                        folder,
                        None,
                        None,
                        "unknown",
                        "folder_identity_candidate" if nhentai_candidate else "no_source_metadata",
                    )
                )
        if progress:
            count = sum(row.path.parent == root for row in rows)
            progress(f"Indexed library root {root_index}/{len(roots)}: {root} ({count} folder(s))")
    return rows


def _normal(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", value.casefold()).strip()


def _manhwa_slug(url: str) -> str | None:
    parts = urlsplit(url)
    host = (parts.hostname or "").lower().rstrip(".")
    path = [item for item in parts.path.split("/") if item]
    return _normal(path[-1]) if host in {"hdporncomics.com", "www.hdporncomics.com"} and len(path) >= 2 and path[0].lower() == "manhwa" else None


def resolve_url_folders(url: str, folders: list[LibraryFolder]) -> list[LibraryFolder]:
    """Resolve with exact source metadata then deterministic backend identity."""
    canonical = canonicalize_url(url)
    matches = [row for row in folders if row.source_url == canonical or canonical in row.candidate_urls]
    if matches:
        return matches
    nhentai = _NHENTAI.fullmatch(canonical)
    if nhentai:
        identity = re.compile(
            rf"(?:^|[-_ ])(?:nhentai[-_ ]?)?{re.escape(nhentai.group(1))}(?:\s+-|$)", re.IGNORECASE
        )
        matches = [
            row for row in folders
            if row.source_url is None and not row.candidate_urls and identity.search(row.path.name)
        ]
        if matches:
            return [replace(row, evidence="nhentai_gallery_id") for row in matches]
    slug = _manhwa_slug(canonical)
    if slug:
        return [
            replace(row, evidence="hdporncomics_exact_slug")
            for row in folders
            if row.source_url is None and not row.candidate_urls and _normal(row.path.name) == slug
        ]
    return []


def backfill_source_indexes(
    urls: Iterable[str],
    folders: list[LibraryFolder],
    *,
    progress=None,
    write: bool = True,
) -> dict[str, int]:
    """Persist only unique, image-bearing URL/folder matches that lack a manifest."""
    summary = {
        "urls": 0,
        "created": 0,
        "already_indexed": 0,
        "unresolved": 0,
        "ambiguous": 0,
        "empty_folder": 0,
        "conflict": 0,
        "missing": 0,
    }
    for raw_url in urls:
        url = canonicalize_url(raw_url)
        summary["urls"] += 1
        matches = resolve_url_folders(url, folders)
        if not matches:
            summary["unresolved"] += 1
            continue
        if len(matches) != 1 or matches[0].identity_status == "ambiguous":
            summary["ambiguous"] += 1
            continue
        row = matches[0]
        if row.manifest and row.manifest.get("canonical_url") == url:
            summary["already_indexed"] += 1
            continue
        if not _has_images(row.path):
            summary["empty_folder"] += 1
            continue
        if (row.path / SOURCE_MANIFEST).exists() and read_source_manifest(row.path) is None:
            summary["conflict"] += 1
            continue
        summary["missing"] += 1
        if not write:
            continue
        try:
            write_source_manifest(
                row.path,
                url,
                row.backend or "unknown",
                identity_evidence=row.evidence,
            )
        except (OSError, ValueError):
            summary["conflict"] += 1
            continue
        summary["created"] += 1
        if progress:
            progress(f"Indexed {url} -> {row.path}")
    return summary
