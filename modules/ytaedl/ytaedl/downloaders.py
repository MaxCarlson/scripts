"""Downloader implementations and process control utilities (using procparsers)."""
from __future__ import annotations

import time
import subprocess
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Callable, Iterator, List, Optional, Set, Tuple

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
    # Give them a moment; then kill whatever remains
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


# -------------------- Utilities --------------------

def _exists_with_dup(dest_path: Path) -> bool:
    """
    Returns True if dest_path exists OR a duplicate variant exists: "<stem> (N)<ext>".
    """
    if dest_path and dest_path.exists():
        return True
    if not dest_path or not dest_path.parent.exists():
        return False
    exp = dest_path
    base = exp.stem
    for f in exp.parent.glob(f"*{exp.suffix.lower()}"):
        if not f.is_file() or f.suffix.lower() != exp.suffix.lower():
            continue
        stem = f.stem
        if stem == base:
            return True
        if stem.startswith(base):
            tail = stem[len(base):]
            if tail.startswith(" (") and tail.endswith(")") and tail[2:-1].isdigit():
                return True
    return False


def _apply_yt_args(cmd: List[str], cfg: DownloaderConfig) -> None:
    # External downloader (aria2)
    aria2_args: List[str] = []
    if cfg.aria2_splits:
        aria2_args += [f"--split={int(cfg.aria2_splits)}"]
    if cfg.aria2_x_conn:
        aria2_args += [f"--max-connection-per-server={int(cfg.aria2_x_conn)}"]
    if cfg.aria2_min_split:
        aria2_args += [f"--min-split-size={cfg.aria2_min_split}"]
    if cfg.aria2_timeout:
        aria2_args += [f"--timeout={int(cfg.aria2_timeout)}"]
    if aria2_args:
        cmd += ["--external-downloader", "aria2c", "--external-downloader-args", " ".join(aria2_args)]

    # yt-dlp tuning
    if cfg.ytdlp_connections:
        cmd += ["-N", str(cfg.ytdlp_connections)]
    if cfg.ytdlp_buffer_size:
        cmd += ["--buffer-size", cfg.ytdlp_buffer_size]
    if cfg.ytdlp_rate_limit:
        cmd += ["--throttled-rate", cfg.ytdlp_rate_limit]
    if cfg.ytdlp_retries is not None:
        cmd += ["--retries", str(cfg.ytdlp_retries)]
    if cfg.ytdlp_fragment_retries is not None:
        cmd += ["--fragment-retries", str(cfg.ytdlp_fragment_retries)]


# -------------------- yt-dlp --------------------

class YtDlpDownloader(DownloaderBase):
    """
    Robust success detection:
      Success iff:
        • We saw an 'already downloaded' marker, OR
        • We saw a Destination: <path> AND, after process exit rc==0, the final file
          exists (directly or via duplicate-suffix variant).
      Otherwise (including rc==0 with no markers) → FAILED with an explicit message.
    """

    def download(self, item: DownloadItem) -> Iterator[DownloadEvent]:
        if abort_requested():
            return
        item.output_dir.mkdir(parents=True, exist_ok=True)

        # Event bookkeeping
        yield StartEvent(item=item)
        start_ts = time.monotonic()

        # Build command
        out_tmpl = item.output_dir / "%(title)s.%(ext)s"
        cmd: List[str] = [
            "yt-dlp",
            "--newline",
            "--print", "TDMETA\t%(id)s\t%(title)s",
            "-o", str(out_tmpl),
            item.url,
        ]
        _apply_yt_args(cmd, self.config)

        # Optional rate limit / retries coming from item
        if getattr(item, "rate_limit", None):
            cmd += ["--throttled-rate", item.rate_limit]
        if getattr(item, "retries", None) is not None:
            cmd += ["--retries", str(int(item.retries))]

        # Run
        proc: Optional[subprocess.Popen] = None
        logs: List[str] = []
        saw_already = False
        saw_destination: Optional[Path] = None
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
            for raw in proc.stdout:
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
                    p = Path(data.get("path", "") or "")
                    if p:
                        saw_destination = p
                        yield DestinationEvent(item=item, path=p)
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

            # Determine final status
            if rc != 0:
                result = DownloadResult(
                    item=item,
                    status=DownloadStatus.FAILED,
                    final_path=saw_destination,
                    error_message=f"non-zero exit code: {rc}",
                    log_output=logs,
                    duration=duration,
                )
                yield FinishEvent(item=item, result=result)
                return

            if saw_already:
                result = DownloadResult(
                    item=item,
                    status=DownloadStatus.ALREADY_EXISTS,
                    final_path=saw_destination,
                    log_output=logs,
                    duration=duration,
                )
                yield FinishEvent(item=item, result=result)
                return

            # Positive completion requires destination (and a real file)
            if saw_destination and _exists_with_dup(saw_destination):
                result = DownloadResult(
                    item=item,
                    status=DownloadStatus.COMPLETED,
                    final_path=saw_destination,
                    log_output=logs,
                    duration=duration,
                )
                yield FinishEvent(item=item, result=result)
                return

            # If we saw progress but no destination, still treat as failure (safer).
            msg = "yt-dlp exited successfully but no completion/destination/progress markers were seen."
            if saw_any_progress:
                msg = "yt-dlp exited successfully but no destination/final file was observed."

            result = DownloadResult(
                item=item,
                status=DownloadStatus.FAILED,
                final_path=saw_destination,
                error_message=msg,
                log_output=logs,
                duration=duration,
            )
            yield FinishEvent(item=item, result=result)

        except KeyboardInterrupt:
            result = DownloadResult(
                item=item,
                status=DownloadStatus.FAILED,
                final_path=saw_destination,
                error_message="interrupted",
                log_output=logs,
                duration=max(0.0, time.monotonic() - start_ts),
            )
            yield FinishEvent(item=item, result=result)
        except FileNotFoundError as ex:
            result = DownloadResult(
                item=item,
                status=DownloadStatus.FAILED,
                error_message=f"executable not found: {ex}",
                log_output=logs,
                duration=max(0.0, time.monotonic() - start_ts),
            )
            yield FinishEvent(item=item, result=result)
        except Exception as ex:
            result = DownloadResult(
                item=item,
                status=DownloadStatus.FAILED,
                error_message=str(ex),
                log_output=logs,
                duration=max(0.0, time.monotonic() - start_ts),
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
            extra += ["--scene", str(scene_ctl["scene_index"])]

        cmd = ["aebn-dl", "--newline", "-o", str(item.output_dir), *extra, item.url]

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
            for raw in proc.stdout:
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

    Returns an AebnDownloader for AEBN URLs, otherwise YtDlpDownloader.
    """
    return AebnDownloader(config) if is_aebn_url(url) else YtDlpDownloader(config)
