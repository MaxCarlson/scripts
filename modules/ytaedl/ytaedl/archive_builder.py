#!/usr/bin/env python3
"""
Archive file rebuilder for ytaedl URL files.
"""
from __future__ import annotations

import argparse
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from .downloader import _ensure_archive_line_has_url, _format_archive_line
from .urlscan import read_url_lines

DEFAULT_URL_DIRS = ["files/downloads/stars", "files/downloads/ae-stars"]
DEFAULT_DOWNLOAD_DIRS = ["./stars"]
ARCHIVE_STATUS = "ARCHIVE_REBUILD"


def _slug_from_path(path: Path) -> str:
    resolved = path.resolve()
    parts = [p for p in resolved.parts if p not in (resolved.anchor, "")]
    slug = "_".join(parts[-3:]) if parts else "root"
    slug = slug.replace(":", "").replace(" ", "_")
    return slug


def _iter_url_files(directories: Iterable[Path]) -> List[Tuple[Path, str]]:
    result: List[Tuple[Path, str]] = []
    for directory in directories:
        if not directory.exists():
            continue
        prefix = _slug_from_path(directory)
        for txt in sorted(directory.glob("*.txt")):
            if txt.is_file():
                result.append((txt, prefix))
    return result


def _gather_mp4_infos(stem: str, download_dirs: List[Path]) -> List[Tuple[Path, int, float]]:
    seen: set[Path] = set()
    infos: List[Tuple[Path, int, float]] = []
    for root in download_dirs:
        folder = root / stem
        if not folder.exists():
            continue
        for mp4 in sorted(folder.glob("*.mp4")):
            if mp4.name.endswith(".part"):
                continue
            try:
                stat = mp4.stat()
            except OSError:
                continue
            resolved = mp4.resolve()
            if resolved in seen:
                continue
            seen.add(resolved)
            infos.append((resolved, stat.st_size, stat.st_mtime))
    infos.sort(key=lambda item: (item[2], item[0].as_posix()))
    return infos


def _format_elapsed(now: float, mtime: float) -> float:
    if mtime <= 0:
        return 0.0
    return max(0.0, now - mtime)


def _format_when(ts: float) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(ts))


@dataclass
class ArchiveBuildResult:
    archive_path: Path
    url_file: Path
    written: bool
    repaired: bool
    mp4_count: int
    needed: int


def build_archive_for_file(
    url_file: Path,
    prefix: str,
    download_dirs: List[Path],
    archive_dir: Path,
    apply: bool,
) -> ArchiveBuildResult:
    urls = read_url_lines(url_file)
    stem = url_file.stem
    mp4_infos = _gather_mp4_infos(stem, download_dirs)
    mp4_iter = iter(mp4_infos)
    now = time.time()
    new_lines: List[str] = []
    mp4_used = 0
    for idx, url in enumerate(urls, start=1):
        try:
            path, size_bytes, mtime = next(mp4_iter)
            mp4_used += 1
        except StopIteration:
            break
        downloaded_mib = size_bytes / (1024 * 1024)
        elapsed = _format_elapsed(now, mtime)
        when = _format_when(mtime if mtime > 0 else now)
        line = _format_archive_line(
            ARCHIVE_STATUS,
            elapsed,
            when,
            downloaded_mib,
            "",
            url,
        )
        new_lines.append(line)
    archive_dir.mkdir(parents=True, exist_ok=True)
    archive_path = archive_dir / f"{prefix}_{stem}.txt"
    new_text = "\n".join(new_lines) + ("\n" if new_lines else "")
    existing_text = ""
    if archive_path.exists():
        existing_text = archive_path.read_text(encoding="utf-8")
    if existing_text == new_text:
        return ArchiveBuildResult(archive_path, url_file, written=False, repaired=False, mp4_count=mp4_used, needed=len(new_lines))
    if existing_text and not apply:
        rebuild_path = archive_path.with_suffix(".rebuild.txt")
        rebuild_path.write_text(new_text, encoding="utf-8")
        return ArchiveBuildResult(rebuild_path, url_file, written=True, repaired=True, mp4_count=mp4_used, needed=len(new_lines))
    archive_path.write_text(new_text, encoding="utf-8")
    return ArchiveBuildResult(archive_path, url_file, written=True, repaired=bool(existing_text), mp4_count=mp4_used, needed=len(new_lines))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ytaedl archive",
        description="Rebuild archive files based on existing downloads.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "-u",
        "--url-dir",
        action="append",
        dest="url_dirs",
        help="Directory containing URL files (*.txt). Can be specified multiple times.",
    )
    parser.add_argument(
        "-d",
        "--download-dir",
        action="append",
        dest="download_dirs",
        help="Directory containing per-urlfile MP4 folders. Can be specified multiple times.",
    )
    parser.add_argument(
        "-A",
        "--archive-dir",
        default="./archives",
        help="Directory where archive files will be written.",
    )
    parser.add_argument(
        "-p",
        "--apply",
        action="store_true",
        help="Overwrite existing archive files instead of writing .rebuild copies.",
    )
    return parser


def cli_main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    url_dirs = [Path(p).expanduser().resolve() for p in (args.url_dirs or DEFAULT_URL_DIRS)]
    download_dirs = [Path(p).expanduser().resolve() for p in (args.download_dirs or DEFAULT_DOWNLOAD_DIRS)]
    archive_dir = Path(args.archive_dir).expanduser().resolve()

    url_files = _iter_url_files(url_dirs)
    if not url_files:
        print("No URL files were found.", file=sys.stderr)
        return 1

    results: List[ArchiveBuildResult] = []
    for url_file, prefix in url_files:
        result = build_archive_for_file(url_file, prefix, download_dirs, archive_dir, args.apply)
        results.append(result)

    total_written = sum(1 for r in results if r.written)
    total_repaired = sum(1 for r in results if r.repaired)
    total_archives = len(url_files)

    print("Archive rebuild summary")
    print("-----------------------")
    print(f"URL directories: {', '.join(str(p) for p in url_dirs)}")
    print(f"Download directories: {', '.join(str(p) for p in download_dirs)}")
    print(f"Archive directory: {archive_dir}")
    print(f"Total URL files: {total_archives}")
    print(f"Archives written: {total_written} ({total_repaired} repairs)")

    mismatches = [r for r in results if r.repaired]
    if mismatches and not args.apply:
        print("\nThe following archives differ from existing files (written as *.rebuild.txt):")
        for r in mismatches:
            print(f" - {r.archive_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(cli_main())
