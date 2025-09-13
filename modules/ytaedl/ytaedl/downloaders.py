from __future__ import annotations

import subprocess
import time
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Iterator, List, Optional, Set

from .models import (
    DownloadEvent,
    DownloadItem,
    DownloadResult,
    DownloadStatus,
    DownloaderConfig,
    StartEvent,
    ProgressEvent,
    MetaEvent,
    DestinationEvent,
    AlreadyEvent,
    LogEvent,
    FinishEvent,
)
# Per your repository layout/snippets these are provided by a top-level module.
from procparsers import parse_ytdlp_line, parse_aebndl_line, sanitize_line
from .url_parser import parse_aebn_scene_controls, is_aebn_url


# -------------------- abort / process tracking --------------------

_ABORT_REQUESTED = False
_ACTIVE_PROCS: Set[subprocess.Popen] = set()


def request_abort() -> None:
    """Signal all downloaders to abort ASAP."""
    global _ABORT_REQUESTED
    _ABORT_REQUESTED = True


def abort_requested() -> bool:
    return _ABORT_REQUESTED


def _register_proc(p: subprocess.Popen) -> None:
    try:
        _ACTIVE_PROCS.add(p)
    except Exception:
        pass


def _unregister_proc(p: subprocess.Popen | None) -> None:
    if p is None:
        return
    try:
        _ACTIVE_PROCS.discard(p)
    except Exception:
        pass


def terminate_all_active_procs() -> None:
    """Best-effort terminate/kill of all tracked child processes."""
    procs = list(_ACTIVE_PROCS)
    for p in procs:
        try:
            if p.poll() is None:
                p.terminate()
        except Exception:
            pass

    deadline = time.time() + 1.5
    for p in procs:
        try:
            if p.poll() is None and time.time() > deadline:
                p.kill()
        except Exception:
            pass

    _ACTIVE_PROCS.clear()


# -------------------- Base --------------------

class DownloaderBase(ABC):
    def __init__(self, config: DownloaderConfig):
        self.config = config

    @abstractmethod
    def download(self, item: DownloadItem) -> Iterator[DownloadEvent]:
        """Yield DownloadEvent objects as the download progresses."""
        raise NotImplementedError


# -------------------- yt-dlp --------------------

class YtDlpDownloader(DownloaderBase):
    """
    Success criteria (to satisfy tests and be reasonably safe in production):
      - If return code != 0  -> FAILED
      - If rc == 0 and we saw:
          • 'already' -> ALREADY_EXISTS
          • 'destination' OR any 'progress' -> COMPLETED
      - Otherwise -> FAILED with clear message
    """

    def download(self, item: DownloadItem) -> Iterator[DownloadEvent]:
        if abort_requested():
            return

        # Validate URL (fixes the core bug you found)
        if not item.url or not item.url.strip():
            raise ValueError("YtDlpDownloader requires a non-empty URL")

        item.output_dir.mkdir(parents=True, exist_ok=True)

        yield StartEvent(item=item)
        start = time.monotonic()
        logs: List[str] = []

        out_tmpl = item.output_dir / "%(title)s.%(ext)s"

        # Build command — IMPORTANT: include the URL argument.
        cmd: List[str] = [
            "yt-dlp",
            "--newline",
            "--print", "TDMETA\t%(id)s\t%(title)s",
            "-o", str(out_tmpl),
            # URL goes on the command line (bug fix)
            item.url,
        ]

        # Apply config knobs (kept conservative; aligns with your snippets)
        if self.config.ytdlp_connections:
            cmd += ["-N", str(self.config.ytdlp_connections)]
        if self.config.ytdlp_buffer_size:
            cmd += ["--buffer-size", self.config.ytdlp_buffer_size]
        if self.config.ytdlp_rate_limit:
            # yt-dlp's throttling arg (do not confuse with aria2)
            cmd += ["--throttled-rate", self.config.ytdlp_rate_limit]
        if self.config.ytdlp_retries is not None:
            cmd += ["--retries", str(self.config.ytdlp_retries)]
        if self.config.ytdlp_fragment_retries is not None:
            cmd += ["--fragment-retries", str(self.config.ytdlp_fragment_retries)]

        # Allow caller-specified extras
        cmd += self.config.extra_ytdlp_args
        cmd += item.extra_args

        status: DownloadStatus = DownloadStatus.FAILED
        err: Optional[str] = None
        saw_progress = False
        saw_destination = False
        saw_already = False

        proc: Optional[subprocess.Popen] = None
        try:
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
                start_new_session=True,  # detached group for clean terminate/kill
            )
            _register_proc(proc)
            assert proc.stdout is not None

            for raw in iter(proc.stdout.readline, ""):
                if abort_requested():
                    raise KeyboardInterrupt
                line = sanitize_line(raw)
                if not line:
                    continue

                logs.append(line)
                data = parse_ytdlp_line(line)

                if not data:
                    yield LogEvent(item=item, message=line)
                    continue

                kind = data.get("event")
                if kind == "progress":
                    saw_progress = True
                    yield ProgressEvent(
                        item=item,
                        percent=data.get("percent"),
                        speed=data.get("speed"),
                        eta=data.get("eta"),
                        downloaded=data.get("downloaded"),
                        total=data.get("total"),
                        unit="bytes",
                    )
                elif kind == "meta":
                    yield MetaEvent(
                        item=item,
                        video_id=data.get("id", "") or "",
                        title=data.get("title", "") or "",
                    )
                elif kind == "destination":
                    saw_destination = True
                    path = Path(data.get("path", "") or "")
                    yield DestinationEvent(item=item, path=path)
                elif kind == "already":
                    saw_already = True
                    yield AlreadyEvent(item=item, message=data.get("message", line))
                else:
                    # Unknown but parsed -> log for visibility
                    yield LogEvent(item=item, message=line)

            rc = proc.wait()
            if rc == 0:
                if saw_already:
                    status = DownloadStatus.ALREADY_EXISTS
                elif saw_destination or saw_progress:
                    status = DownloadStatus.COMPLETED
                else:
                    err = "yt-dlp exited 0, but no destination/progress lines were seen"
                    status = DownloadStatus.FAILED
            else:
                err = f"non-zero exit code: {rc}"
        except KeyboardInterrupt:
            err = "interrupted"
            status = DownloadStatus.FAILED
            raise
        except Exception as e:
            err = str(e)
        finally:
            _unregister_proc(proc)

        dur = time.monotonic() - start
        yield FinishEvent(
            item=item,
            result=DownloadResult(
                item=item,
                status=status,
                final_path=None,  # optionally set if you capture DestinationEvent path
                error_message=err,
                size_bytes=None,
                duration=dur,
                log_output=logs,
            ),
        )


# -------------------- aebndl --------------------

class AebnDownloader(DownloaderBase):
    def download(self, item: DownloadItem) -> Iterator[DownloadEvent]:
        if abort_requested():
            return

        item.output_dir.mkdir(parents=True, exist_ok=True)
        self.config.work_dir.mkdir(parents=True, exist_ok=True)

        yield StartEvent(item=item)
        start = time.monotonic()
        logs: List[str] = []

        # Base command
        cmd: List[str] = [
            "aebndl",
            "-o", str(item.output_dir),
            "-w", str(self.config.work_dir),
            "-t", str(self.config.aebn_threads or 4),
        ]

        # Scene-aware controls based on URL fragments/paths
        controls = parse_aebn_scene_controls(item.url)
        if controls and controls.is_scene:
            # Prefer explicit scene index if present; else scene id
            if controls.scene_index is not None:
                cmd += ["-s", str(controls.scene_index)]
            elif getattr(controls, "scene_id", None):
                cmd += ["-S", str(controls.scene_id)]

        # Allow caller extras
        cmd += self.config.extra_aebn_args
        cmd += item.extra_args
        # Include URL argument (always required)
        if not item.url or not item.url.strip():
            raise ValueError("AebnDownloader requires a non-empty URL")
        cmd.append(item.url)

        status: DownloadStatus = DownloadStatus.FAILED
        err: Optional[str] = None
        saw_completed = False
        saw_already = False

        proc: Optional[subprocess.Popen] = None
        try:
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
                start_new_session=True,
            )
            _register_proc(proc)
            assert proc.stdout is not None

            for raw in iter(proc.stdout.readline, ""):
                if abort_requested():
                    raise KeyboardInterrupt
                line = sanitize_line(raw)
                if not line:
                    continue

                logs.append(line)
                data = parse_aebndl_line(line)

                if not data:
                    yield LogEvent(item=item, message=line)
                    continue

                kind = data.get("event")
                if kind == "progress":
                    yield ProgressEvent(
                        item=item,
                        percent=data.get("percent"),
                        speed=data.get("speed"),
                        eta=data.get("eta"),
                        downloaded=data.get("downloaded"),
                        total=data.get("total"),
                        unit="bytes",
                    )
                elif kind == "destination":
                    yield DestinationEvent(item=item, path=Path(data.get("path", "") or ""))
                elif kind == "already":
                    saw_already = True
                    yield AlreadyEvent(item=item, message=data.get("message", line))
                elif kind == "completed":
                    saw_completed = True
                else:
                    yield LogEvent(item=item, message=line)

            rc = proc.wait()
            if rc == 0:
                if saw_already:
                    status = DownloadStatus.ALREADY_EXISTS
                elif saw_completed:
                    status = DownloadStatus.COMPLETED
                else:
                    err = "aebndl exited 0, but completion wasn’t detected"
            else:
                err = f"non-zero exit code: {rc}"
        except KeyboardInterrupt:
            err = "interrupted"
            status = DownloadStatus.FAILED
            raise
        except Exception as e:
            err = str(e)
        finally:
            _unregister_proc(proc)

        dur = time.monotonic() - start
        yield FinishEvent(
            item=item,
            result=DownloadResult(
                item=item,
                status=status,
                final_path=None,
                error_message=err,
                size_bytes=None,
                duration=dur,
                log_output=logs,
            ),
        )


# -------------------- Router --------------------

def get_downloader(url: str, config: DownloaderConfig) -> DownloaderBase:
    """Return the appropriate downloader class for this URL."""
    return AebnDownloader(config) if is_aebn_url(url) else YtDlpDownloader(config)
