"""Downloader implementations and process control utilities (using procparsers)."""
from __future__ import annotations

import time
import subprocess
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Iterator, List, Optional, Set, Tuple

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


def _unregister_proc(p: subprocess.Popen) -> None:
    try:
        _ACTIVE_PROCS.discard(p)
    except Exception:
        pass


def terminate_all_active_procs() -> None:
    """Best-effort terminate of all tracked child processes."""
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
        item.output_dir.mkdir(parents=True, exist_ok=True)

        yield StartEvent(item=item)
        start_ts = time.monotonic()

        out_tmpl = item.output_dir / "%(title)s.%(ext)s"
        cmd: List[str] = [
            "yt-dlp",
            "--newline",
            "--print", "TDMETA\t%(id)s\t%(title)s",
            "-o", str(out_tmpl),
            item.url,
        ]

        # apply config options
        if self.config.ytdlp_connections:
            cmd += ["-N", str(self.config.ytdlp_connections)]
        if self.config.ytdlp_buffer_size:
            cmd += ["--buffer-size", self.config.ytdlp_buffer_size]
        if self.config.ytdlp_rate_limit:
            cmd += ["--throttled-rate", self.config.ytdlp_rate_limit]
        if self.config.ytdlp_retries is not None:
            cmd += ["--retries", str(self.config.ytdlp_retries)]
        if self.config.ytdlp_fragment_retries is not None:
            cmd += ["--fragment-retries", str(self.config.ytdlp_fragment_retries)]

        # item-specific extras
        if getattr(item, "rate_limit", None):
            cmd += ["--throttled-rate", item.rate_limit]
        if getattr(item, "retries", None) is not None:
            cmd += ["--retries", str(int(item.retries))]
        extra = getattr(item, "extra_ytdlp_args", []) or []
        if extra:
            cmd += list(extra)

        proc: Optional[subprocess.Popen] = None
        logs: List[str] = []
        saw_already = False
        saw_destination = False
        saw_any_progress = False
        last_meta: Tuple[str, str] | None = None  # (id, title)

        try:
            proc = subprocess.Popen(
                cmd,
                cwd=str(self.config.work_dir) if self.config.work_dir else None,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
            _register_proc(proc)

            assert proc.stdout is not None
            # use readline() to play nicely with tests that patch .readline.side_effect
            while True:
                raw = proc.stdout.readline()
                if raw == "":
                    break

                if abort_requested():
                    try:
                        proc.terminate()
                    except Exception:
                        pass
                    break

                line = sanitize_line(raw)
                logs.append(line)

                data = parse_ytdlp_line(line)
                if not data:
                    yield LogEvent(item=item, message=line)
                    continue

                kind = data.get("event")
                if kind == "meta":
                    last_meta = (data.get("id", "") or "", data.get("title", "") or "")
                    yield MetaEvent(item=item, video_id=last_meta[0], title=last_meta[1])
                elif kind == "destination":
                    saw_destination = True
                    yield DestinationEvent(item=item, path=Path(data.get("path") or ""))  # type: ignore[arg-type]
                elif kind == "already":
                    saw_already = True
                    yield AlreadyEvent(item=item)
                elif kind == "progress":
                    saw_any_progress = True
                    total_b = data.get("total")
                    yield ProgressEvent(
                        item=item,
                        downloaded_bytes=int(data.get("downloaded", 0) or 0),
                        total_bytes=int(total_b) if total_b is not None else None,
                        speed_bps=float(data["speed_bps"]) if data.get("speed_bps") is not None else None,
                        eta_seconds=int(data["eta_s"]) if data.get("eta_s") is not None else None,
                        unit="bytes",
                    )
                else:
                    yield LogEvent(item=item, message=line)

            rc = proc.wait(self.config.timeout_seconds) if self.config.timeout_seconds else proc.wait()
            duration = max(0.0, time.monotonic() - start_ts)

            if rc != 0:
                result = DownloadResult(
                    item=item,
                    status=DownloadStatus.FAILED,
                    error_message=f"non-zero exit code: {rc}",
                    duration=duration,
                    log_output=logs,
                )
                yield FinishEvent(item=item, result=result)
                return

            if saw_already:
                result = DownloadResult(
                    item=item,
                    status=DownloadStatus.ALREADY_EXISTS,
                    duration=duration,
                    log_output=logs,
                )
                yield FinishEvent(item=item, result=result)
                return

            if saw_destination or saw_any_progress:
                result = DownloadResult(
                    item=item,
                    status=DownloadStatus.COMPLETED,
                    duration=duration,
                    log_output=logs,
                )
                yield FinishEvent(item=item, result=result)
                return

            result = DownloadResult(
                item=item,
                status=DownloadStatus.FAILED,
                error_message="yt-dlp exited successfully but no completion/destination/progress markers were seen.",
                duration=duration,
                log_output=logs,
            )
            yield FinishEvent(item=item, result=result)

        except KeyboardInterrupt:
            result = DownloadResult(
                item=item,
                status=DownloadStatus.FAILED,
                error_message="interrupted",
                duration=max(0.0, time.monotonic() - start_ts),
                log_output=logs,
            )
            yield FinishEvent(item=item, result=result)
        except FileNotFoundError as ex:
            result = DownloadResult(
                item=item,
                status=DownloadStatus.FAILED,
                error_message=f"executable not found: {ex}",
                duration=max(0.0, time.monotonic() - start_ts),
                log_output=logs,
            )
            yield FinishEvent(item=item, result=result)
        except Exception as ex:
            result = DownloadResult(
                item=item,
                status=DownloadStatus.FAILED,
                error_message=str(ex),
                duration=max(0.0, time.monotonic() - start_ts),
                log_output=logs,
            )
            yield FinishEvent(item=item, result=result)
        finally:
            if proc is not None:
                _unregister_proc(proc)


# -------------------- aebn-dl --------------------

class AebnDownloader(DownloaderBase):
    """
    Minimal aebn-dl wrapper that streams lines through procparsers.aebndl to give Progress.
    Treat non-zero exit codes as failures; otherwise assume success if any segment progress observed.
    """

    def download(self, item: DownloadItem) -> Iterator[DownloadEvent]:
        if abort_requested():
            return
        item.output_dir.mkdir(parents=True, exist_ok=True)

        yield StartEvent(item=item)
        start_ts = time.monotonic()

        # Derive extra args (scene selection, etc.)
        extra = getattr(item, "extra_aebn_args", []) or []
        scene_ctl = parse_aebn_scene_controls(item.url)
        if scene_ctl.get("scene_index") is not None:
            # Tests expect short flag '-s'
            extra += ["-s", str(scene_ctl["scene_index"])]

        # NOTE: tests expect the executable token to be 'aebndl' (no dash)
        cmd = ["aebndl", "--newline", "-o", str(item.output_dir), *extra, item.url]

        proc: Optional[subprocess.Popen] = None
        logs: List[str] = []
        saw_progress = False
        dest_path: Optional[Path] = None

        try:
            proc = subprocess.Popen(
                cmd,
                cwd=str(self.config.work_dir) if self.config.work_dir else None,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
            _register_proc(proc)

            assert proc.stdout is not None
            while True:
                raw = proc.stdout.readline()
                if raw == "":
                    break

                if abort_requested():
                    try:
                        proc.terminate()
                    except Exception:
                        pass
                    break

                line = sanitize_line(raw)
                logs.append(line)
                data = parse_aebndl_line(line)
                if not data:
                    yield LogEvent(item=item, message=line)
                    continue

                if data["event"] == "aebn_progress":
                    saw_progress = True
                    yield ProgressEvent(
                        item=item,
                        downloaded_bytes=int(data["segments_done"]),
                        total_bytes=int(data["segments_total"]),
                        speed_bps=float(data["rate_itps"]),
                        eta_seconds=int(data["eta_s"]),
                        unit="segments",
                    )
                elif data["event"] == "destination":
                    dest_path = Path(data["path"])
                    yield DestinationEvent(item=item, path=dest_path)
                else:
                    yield LogEvent(item=item, message=line)

            rc = proc.wait(self.config.timeout_seconds) if self.config.timeout_seconds else proc.wait()
            duration = max(0.0, time.monotonic() - start_ts)

            if rc != 0:
                result = DownloadResult(item=item, status=DownloadStatus.FAILED, error_message=f"non-zero exit code: {rc}", final_path=dest_path, log_output=logs, duration=duration)
            else:
                result = DownloadResult(item=item, status=DownloadStatus.COMPLETED if saw_progress else DownloadStatus.FAILED, final_path=dest_path, log_output=logs, duration=duration)
            yield FinishEvent(item=item, result=result)

        except Exception as ex:
            result = DownloadResult(item=item, status=DownloadStatus.FAILED, error_message=str(ex), final_path=dest_path, log_output=logs, duration=max(0.0, time.monotonic() - start_ts))
            yield FinishEvent(item=item, result=result)
        finally:
            if proc is not None:
                _unregister_proc(proc)


# -------------------- Router (for legacy/tests) --------------------

def get_downloader(url: str, config: DownloaderConfig) -> DownloaderBase:
    """
    Legacy-compatible factory expected by tests and runner modules.
    """
    return AebnDownloader(config) if is_aebn_url(url) else YtDlpDownloader(config)
