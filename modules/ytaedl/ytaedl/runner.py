"""Parallel download runner with archive-skip, logging hook, and hard abort (matches tests)."""
from __future__ import annotations

import concurrent.futures as cf
import threading
from pathlib import Path
from typing import Iterable, List, Optional, Set

from .downloaders import get_downloader, terminate_all_active_procs, request_abort, abort_requested
from .io import read_urls_from_files, load_archive, save_archive
from .models import (
    DownloaderConfig,
    DownloadItem,
    URLSource,
    DownloadResult,
    DownloadStatus,
    FinishEvent,
    StartEvent,
    DownloadEvent,
)

# (rest of the class unchanged above this point)

class DownloadRunner:
    def __init__(self, config: DownloaderConfig, ui: Optional[UIBase] = None, *_ignore):
        self.config = config
        self.ui = ui
        self._abort = threading.Event()

        # Optional log file (simple line logger) — now from config.log_file
        self._log_fp = None
        log_path: Optional[Path] = getattr(self.config, "log_file", None)
        if log_path:
            try:
                log_path.parent.mkdir(parents=True, exist_ok=True)
                self._log_fp = open(log_path, "a", encoding="utf-8")
            except Exception:
                self._log_fp = None

        # --- Archive support (needed for tests) ---
        self._archived: Set[str] = set()
        if self.config.archive_path:
            self._archived = load_archive(self.config.archive_path)

    def _log(self, line: str) -> None:
        if self._log_fp:
            try:
                self._log_fp.write(line.rstrip("\n") + "\n")
                self._log_fp.flush()
            except Exception:
                pass

    def _handle_event(self, ev: DownloadEvent) -> None:
        if isinstance(ev, StartEvent):
            self._log(f"START {ev.item.id} {ev.item.url}")
        elif isinstance(ev, FinishEvent):
            self._log(f"FINISH {ev.item.id} {getattr(ev.result.status, 'value', '')}")
        else:
            msg = getattr(ev, "message", None)
            if msg is not None:
                self._log(f"LOG {getattr(ev, 'item').id} {msg}")

        if self.ui:
            self.ui.handle_event(ev)

    def _iter_items(self, url_files: Iterable[Path], base_out: Path, per_file_subdirs: bool) -> List[DownloadItem]:
        """Create DownloadItem list, **skipping archived URLs before** calling any downloader."""
        items: List[DownloadItem] = []
        next_id = 0
        for url_file in url_files:
            urls = read_urls_from_files([url_file])
            dest = base_out / url_file.stem if per_file_subdirs else base_out
            dest.mkdir(parents=True, exist_ok=True)

            for _ln, url in enumerate(urls, 1):
                # IMPORTANT: skip archived here → test_runner_skips_archived_urls expects downloader not called
                if self._archived and url in self._archived:
                    next_id += 1
                    continue

                items.append(
                    DownloadItem(
                        id=next_id,
                        url=url,
                        output_dir=dest,
                        source=URLSource(file=url_file, line_number=_ln, original_url=url),
                        total_in_set=len(urls),
                        retries=3,
                    )
                )
                next_id += 1
        return items

    def _worker(self, item: DownloadItem) -> DownloadResult:
        if abort_requested() or self._abort.is_set():
            raise RuntimeError("aborted")

        dl = get_downloader(item.url, self.config)
        result: Optional[DownloadResult] = None
        try:
            for ev in dl.download(item):
                self._handle_event(ev)
                if isinstance(ev, FinishEvent):
                    result = ev.result
        except KeyboardInterrupt:
            request_abort()
            terminate_all_active_procs()
            raise

        result = result or DownloadResult(item=item, status=DownloadStatus.FAILED, error_message="no result")

        # On success/exists, append to archive
        if self.config.archive_path and result.status in (DownloadStatus.COMPLETED, DownloadStatus.ALREADY_EXISTS):
            try:
                self._archived.add(item.url)
                save_archive(self.config.archive_path, self._archived)
            except Exception:
                pass

        return result

    def run_from_files(self, url_files: Iterable[Path], base_out: Path) -> None:
        items = self._iter_items(url_files, base_out, self.config.per_file_subdirs)
        if not items:
            return

        maxw = max(1, int(self.config.max_workers))
        with cf.ThreadPoolExecutor(max_workers=maxw, thread_name_prefix="ytaedl") as ex:
            pending: Set[cf.Future] = set()
            try:
                # Prime the pool
                for _ in range(maxw):
                    item = next(iter(items), None)
                    if item is None:
                        break
                # Re-create iterator (above preview consumed nothing)
                it = iter(items)
                for _ in range(maxw):
                    try:
                        item = next(it)
                    except StopIteration:
                        break
                    pending.add(ex.submit(self._worker, item))

                while pending:
                    done, pending = cf.wait(pending, return_when=cf.FIRST_COMPLETED)
                    for d in done:
                        d.result()  # surface exceptions
                    if abort_requested():
                        break
            except KeyboardInterrupt:
                request_abort()
                terminate_all_active_procs()
                for fut in pending:
                    fut.cancel()
                raise
            finally:
                terminate_all_active_procs()

        if self._log_fp:
            try:
                self._log_fp.close()
            except Exception:
                pass
