from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from .constants import COVER_STEM, METADATA_DIR_NAME, SCHEMA_VERSION, SOURCE_MANIFEST_NAME
from .files import existing_cover, replace_cover
from .models import CoverResult, SeriesPageMetadata
from .scraping import fetch_series_metadata, read_cover_bytes
from .util import archive_replaced, atomic_write_json


def write_cover_for_folder(
    url: str,
    folder: Path,
    *,
    apply: bool,
    force: bool = False,
    cookies: Path | None = None,
    timeout: float = 45.0,
    metadata: SeriesPageMetadata | None = None,
    opener: object | None = None,
) -> CoverResult:
    folder = folder.expanduser().resolve()
    metadata = metadata or fetch_series_metadata(url, cookies=cookies, timeout=timeout, opener=opener)
    metadata_dir = folder / METADATA_DIR_NAME
    existing = existing_cover(metadata_dir)
    manifest_path = metadata_dir / SOURCE_MANIFEST_NAME

    if existing is not None and not force:
        return CoverResult(
            url=metadata.canonical_url,
            status="already_present",
            folder=str(folder),
            title=metadata.title,
            cover_url=metadata.cover_url,
            cover_file=str(existing),
            message="existing managed cover retained; use --force to refresh",
        )

    if not apply:
        return CoverResult(
            url=metadata.canonical_url,
            status="planned",
            folder=str(folder),
            title=metadata.title,
            cover_url=metadata.cover_url,
            cover_file=str(metadata_dir / f"{COVER_STEM}.<image-extension>"),
        )

    payload, suffix = read_cover_bytes(metadata, cookies=cookies, timeout=timeout, opener=opener)
    digest = hashlib.sha256(payload).hexdigest()
    target = replace_cover(existing, metadata_dir / f"{COVER_STEM}{suffix}", payload, digest)

    if manifest_path.exists():
        try:
            previous = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            previous = None
        if not isinstance(previous, dict) or previous.get("cover_sha256") != digest:
            archive_replaced(manifest_path)

    manifest = {
        "schema_version": SCHEMA_VERSION,
        "source_url": metadata.source_url,
        "canonical_url": metadata.canonical_url,
        "source_host": metadata.source_host,
        "source_title": metadata.title,
        "alternate_titles": list(metadata.alternate_titles),
        "local_series_path": str(folder),
        "cover_source_url": metadata.cover_url,
        "cover_file": target.name,
        "cover_sha256": digest,
        "cover_bytes": len(payload),
        "retrieved_at": datetime.now(timezone.utc).isoformat(),
    }
    atomic_write_json(manifest_path, manifest)
    return CoverResult(
        url=metadata.canonical_url,
        status="downloaded",
        folder=str(folder),
        title=metadata.title,
        cover_url=metadata.cover_url,
        cover_file=str(target),
    )


def with_match(result: CoverResult, method: str, score: float) -> CoverResult:
    return CoverResult(**{**asdict(result), "match_method": method, "match_score": score})
