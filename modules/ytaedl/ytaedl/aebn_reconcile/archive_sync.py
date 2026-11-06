"""Targeted post-verification archive and domain-index reconciliation."""

from __future__ import annotations

import os
import shutil
import tempfile
import time
from collections import defaultdict
from pathlib import Path

from ytaedl.downloader import _archive_prefix_for, _format_archive_line
from ytaedl.domain_index import DomainIndex
from ytaedl.manager import DomainIndexFileLock
from ytaedl.urlfile_lock import UrlFileLock

from .store import ReconciliationStore


def _atomic_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp_name, path)
    finally:
        try:
            os.unlink(temp_name)
        except FileNotFoundError:
            pass


def sync_verified_archives(database_path: Path | str, *, apply: bool = False) -> dict:
    db_path = Path(database_path).expanduser().resolve()
    with ReconciliationStore(db_path) as store:
        archive_dir_value = store.get_setting("archive_dir")
        if not archive_dir_value:
            raise ValueError("this reconciliation database has no configured --archive-dir")
        archive_dir = Path(archive_dir_value)
        scenes = store.execute(
            """SELECT s.original_url,s.movie_key,s.scene_id,ss.source_file FROM requested_scenes s
               JOIN scene_sources ss USING(movie_key,scene_id) WHERE s.status='scene_verified'
               ORDER BY ss.source_file,s.original_url"""
        ).fetchall()
        by_source: dict[str, set[str]] = defaultdict(set)
        for scene in scenes:
            by_source[scene["source_file"]].add(scene["original_url"])
        operations = []
        for source_text, urls in by_source.items():
            source = Path(source_text)
            archive_path = archive_dir / f"{_archive_prefix_for(source)}-{source.stem}.txt"
            operations.append({"source_file": str(source), "archive_file": str(archive_path), "urls": sorted(urls)})
        if not apply:
            return {"planned_files": len(operations), "planned_urls": sum(len(op["urls"]) for op in operations),
                    "operations": operations, "updated": 0, "deferred": []}
        index_path = archive_dir / "domain_index.json"
        try:
            index_lock = DomainIndexFileLock(index_path)
            index_lock.acquire()
        except Exception as exc:
            return {"planned_files": len(operations), "planned_urls": sum(len(op["urls"]) for op in operations),
                    "operations": [], "updated": 0, "deferred": [f"domain index is locked or unavailable: {exc}"]}
        updated = 0
        deferred = []
        try:
            index = None
            if index_path.exists():
                try:
                    index = DomainIndex.load(index_path)
                except Exception as exc:
                    return {"planned_files": len(operations), "planned_urls": sum(len(op["urls"]) for op in operations),
                            "operations": [], "updated": 0, "deferred": [f"domain index cannot be loaded safely: {exc}"]}
            for operation in operations:
                source = Path(operation["source_file"])
                source_lock = UrlFileLock(source, mode="aebn-reconcile", lock_dir=archive_dir / "locks")
                attempt = source_lock.try_acquire()
                if not attempt.acquired:
                    deferred.append(f"{source}: source URL file is locked ({attempt.status})")
                    continue
                try:
                    archive_path = Path(operation["archive_file"])
                    try:
                        lines = archive_path.read_text(encoding="utf-8", errors="replace").splitlines() if archive_path.exists() else []
                    except OSError as exc:
                        deferred.append(f"{archive_path}: cannot read archive: {exc}")
                        continue
                    changed = False
                    urls = set(operation["urls"])
                    seen = set()
                    result_lines = []
                    for line in lines:
                        columns = line.split("\t")
                        if len(columns) >= 6 and columns[-1] in urls:
                            columns[0] = "downloaded"
                            result_lines.append("\t".join(columns))
                            seen.add(columns[-1])
                            changed = True
                        else:
                            result_lines.append(line)
                    for url in sorted(urls - seen):
                        result_lines.append(_format_archive_line("downloaded", 0.0, time.strftime("%Y-%m-%d %H:%M:%S"),
                                                                  0.0, "", url))
                        changed = True
                    if changed:
                        if archive_path.exists():
                            backup = archive_path.with_suffix(archive_path.suffix + ".reconcile.bak")
                            if not backup.exists():
                                shutil.copy2(archive_path, backup)
                        _atomic_text(archive_path, "\n".join(result_lines) + "\n")
                    if index is not None:
                        for url in urls:
                            index.mark_finished(url, "downloaded")
                    store.record_event("archive_sync", details={"source_file": str(source), "archive_file": str(archive_path),
                                                                 "urls": sorted(urls), "changed": changed})
                    updated += len(urls)
                finally:
                    source_lock.release()
            if index is not None and updated:
                backup = index_path.with_suffix(index_path.suffix + ".reconcile.bak")
                if not backup.exists():
                    shutil.copy2(index_path, backup)
                index.save(index_path)
            return {"planned_files": len(operations), "planned_urls": sum(len(op["urls"]) for op in operations),
                    "operations": operations, "updated": updated, "deferred": deferred}
        finally:
            index_lock.release()
