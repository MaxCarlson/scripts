from __future__ import annotations

import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from .naming import gallery_directory_name

LOOSE_NHENTAI = re.compile(r"^nhentai_(?P<gallery_id>\d+)_(?P<page>\d+)\.(?P<extension>[^.]+)$", re.IGNORECASE)
PAGE_FILE = re.compile(r"^(?P<page>\d+)\.[^.]+$", re.IGNORECASE)
ProgressCallback = Callable[[dict[str, Any]], None]


def _notify(callback: ProgressCallback | None, **values: Any) -> None:
    if callback is not None:
        callback(values)


@dataclass(frozen=True, slots=True)
class GalleryMetadata:
    gallery_id: str
    title: str
    page_count: int
    folder_name: str


@dataclass(frozen=True, slots=True)
class RepairMove:
    source: Path
    destination: Path
    gallery_id: str
    page: int


@dataclass(frozen=True, slots=True)
class GalleryVerification:
    gallery_id: str
    folder: Path
    expected: int
    present_after_repair: int
    missing_pages: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class RepairPlan:
    moves: tuple[RepairMove, ...]
    galleries: tuple[GalleryVerification, ...]
    ignored: int
    conflicts: tuple[str, ...]

    @property
    def valid(self) -> bool:
        return not self.conflicts and all(not gallery.missing_pages for gallery in self.galleries)


def resolve_nhentai_metadata(gallery_id: str) -> GalleryMetadata:
    """Resolve title/count and sanitize the folder with gallery-dl's own rules."""
    from gallery_dl import extractor
    from gallery_dl import path as gallery_path
    from gallery_dl.extractor.message import Message

    instance = extractor.find(f"https://nhentai.net/g/{gallery_id}/")
    if instance is None:
        raise ValueError(f"gallery-dl does not support nhentai gallery {gallery_id}")
    try:
        first = next(iter(instance))
    except StopIteration as exc:
        raise ValueError(f"gallery-dl returned no metadata for nhentai gallery {gallery_id}") from exc
    if first[0] != Message.Directory:
        raise ValueError(f"gallery-dl returned an unexpected first message for nhentai gallery {gallery_id}")
    data = first[2]
    title = str(data.get("title") or "").strip()
    page_count = int(data.get("count") or 0)
    if not title or page_count < 1:
        raise ValueError(f"incomplete metadata for nhentai gallery {gallery_id}")
    formatter = gallery_path.PathFormat(instance)
    folder_name = gallery_directory_name(
        {"category": "nhentai", "gallery_id": gallery_id, "title": title}, formatter.clean_segment
    )
    return GalleryMetadata(gallery_id, title, page_count, folder_name)


def _existing_pages(folder: Path) -> set[int]:
    if not folder.is_dir():
        return set()
    return {
        int(match.group("page"))
        for path in folder.iterdir()
        if path.is_file() and (match := PAGE_FILE.fullmatch(path.name))
    }


def plan_loose_images(
    root: Path,
    resolver: Callable[[str], GalleryMetadata] = resolve_nhentai_metadata,
    progress: ProgressCallback | None = None,
) -> RepairPlan:
    if not root.is_dir():
        raise ValueError(f"destination is not a directory: {root}")
    grouped: dict[str, list[tuple[Path, int, str]]] = {}
    ignored = 0
    for source in sorted(root.iterdir()):
        if not source.is_file() or not (match := LOOSE_NHENTAI.fullmatch(source.name)):
            ignored += 1
            continue
        grouped.setdefault(match.group("gallery_id"), []).append(
            (source, int(match.group("page")), match.group("extension").lower())
        )

    total_files = sum(len(sources) for sources in grouped.values())
    _notify(progress, phase="metadata", gallery_total=len(grouped), file_total=total_files, message="scan complete")

    moves: list[RepairMove] = []
    galleries: list[GalleryVerification] = []
    conflicts: list[str] = []
    expected_total = present_total = missing_total = 0
    for index, (gallery_id, sources) in enumerate(sorted(grouped.items(), key=lambda item: int(item[0])), 1):
        _notify(
            progress,
            phase="metadata",
            gallery_done=index - 1,
            gallery_total=len(grouped),
            file_total=total_files,
            current_id=gallery_id,
            message="resolving gallery metadata",
        )
        metadata = resolver(gallery_id)
        folder = root / metadata.folder_name
        existing = _existing_pages(folder)
        planned: set[int] = set()
        for source, page, extension in sources:
            target = folder / f"{page:03d}.{extension}"
            if page in planned:
                conflicts.append(f"duplicate loose page {page} for nhentai {gallery_id}")
                continue
            if target.exists():
                conflicts.append(f"target exists: {target}")
                continue
            planned.add(page)
            moves.append(RepairMove(source, target, gallery_id, page))
        present = existing | planned
        expected = set(range(1, metadata.page_count + 1))
        missing = tuple(sorted(expected - present))
        expected_total += metadata.page_count
        present_total += len(present & expected)
        missing_total += len(missing)
        galleries.append(GalleryVerification(gallery_id, folder, metadata.page_count, len(present & expected), missing))
        _notify(
            progress,
            phase="metadata",
            gallery_done=index,
            gallery_total=len(grouped),
            file_total=total_files,
            expected_pages=expected_total,
            present_pages=present_total,
            missing_pages=missing_total,
            conflicts=len(conflicts),
            current_id=gallery_id,
            current_title=metadata.title,
            message="metadata resolved",
        )
    _notify(progress, phase="planned", gallery_done=len(grouped), gallery_total=len(grouped), file_total=total_files)
    return RepairPlan(tuple(moves), tuple(galleries), ignored, tuple(conflicts))


def apply_repair(plan: RepairPlan, progress: ProgressCallback | None = None) -> int:
    if not plan.valid:
        raise ValueError("repair is incomplete or has conflicts; no files were moved")
    _notify(progress, phase="moving", move_done=0, move_total=len(plan.moves), gallery_total=len(plan.galleries))
    for index, move in enumerate(plan.moves, 1):
        move.destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(move.source), str(move.destination))
        _notify(
            progress,
            phase="moving",
            move_done=index,
            move_total=len(plan.moves),
            current_id=move.gallery_id,
            message=move.destination.name,
        )
    for index, gallery in enumerate(plan.galleries, 1):
        present = _existing_pages(gallery.folder)
        expected = set(range(1, gallery.expected + 1))
        if not expected.issubset(present):
            raise RuntimeError(f"post-repair verification failed for nhentai {gallery.gallery_id}")
        _notify(
            progress,
            phase="verifying",
            verify_done=index,
            verify_total=len(plan.galleries),
            current_id=gallery.gallery_id,
            message="complete",
        )
    _notify(progress, phase="complete", move_done=len(plan.moves), move_total=len(plan.moves))
    return len(plan.moves)
