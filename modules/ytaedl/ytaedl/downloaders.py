#!/usr/bin/env python3
"""Downloader implementations and process control utilities."""
from __future__ import annotations

import time
import subprocess
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
from .parsers import parse_ytdlp_line, parse_aebndl_line, sanitize_line
from .url_parser import parse_aebn_scene_controls, is_aebn_url

# ------------ global abort flag + process registry ------------
_ABORT_REQUESTED: bool = False

def request_abort() -> None:
    global _ABORT_REQUESTED
    _ABORT_REQUESTED = True

def abort_requested() -> bool:
    return _ABORT_REQUESTED

_ACTIVE_PROCS: Set[subprocess.Popen] = set()

def _register_proc(p: subprocess.Popen) -> None:
    try:
        _ACTIVE_PROCS.add(p)
    except Exception:
        pass

def _unregister_proc(p: Optional[subprocess.Popen]) -> None:
    if not p:
        return
    try:
        _ACTIVE_PROCS.discard(p)
    except Exception:
        pass

def terminate_all_active_procs(timeout: float = 1.5) -> None:
    """Best-effort terminate → kill everything we spawned."""
    procs = list(_ACTIVE_PROCS)
    for p in procs:
        try:
            p.terminate()
        except Exception:
            pass
    t0 = time.monotonic()
    for p in procs:
        try:
            while p.poll() is None:
                if time.monotonic() - t0 > timeout:
                    p.kill()
                    break
                time.sleep(0.05)
        except Exception:
            pass
    _ACTIVE_PROCS.clear()

# -------------------- Base --------------------
class DownloaderBase(ABC):
    def __init__(self, config: DownloaderConfig):
        self.config = config

    @abstractmethod
    def download(self, item: DownloadItem) -> Iterator[DownloadEvent]:
        ...

# -------------------- yt-dlp --------------------
class YtDlpDownloader(DownloaderBase):
    def download(self, item: DownloadItem) -> Iterator[DownloadEvent]:
        if abort_requested():
            return
        item.output_dir.mkdir(parents=True, exist_ok=True)

        yield StartEvent(item=item)
        start = time.monotonic()
        logs: List[str] = []

        out_tmpl = item.output_dir / "%(title)s.%(ext)s"
        cmd: List[str] = [
            "yt-dlp",
            "--newline",
            "--print",
            "TDMETA\t%(id)s\t%(title)s",
            "-o",
            str(out_tmpl),
        ]

        # External downloader & args (aria2c)
        aria2_args: List[str] = []
        if self.config.aria2_x_conn:
            aria2_args += ["-x", str(self.config.aria2_x_conn)]
        if self.config.aria2_splits:
            aria2_args += ["-s", str(self.config.aria2_splits)]
        if self.config.aria2_min_split:
            aria2_args += [f"--min-split-size={self.config.aria2_min_split}"]
        if self.config.ytdlp_rate_limit:
            aria2_args += [f"--lowest-speed-limit={self.config.ytdlp_rate_limit}"]
        if self.config.aria2_timeout:
            aria2_args += [f"--timeout={int(self.config.aria2_timeout)}"]
        if aria2_args:
            cmd += ["--external-downloader", "aria2c", "--external-downloader-args", " ".join(aria2_args)]

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
        if item.retries is not None and self.config.ytdlp_retries is None:
            cmd += ["--retries", str(item.retries)]

        cmd += self.config.extra_ytdlp_args
        cmd += item.extra_args
        cmd.append(item.url)

        yield LogEvent(item=item, message=f"SPAWN yt-dlp: {' '.join(cmd)}")

        status = DownloadStatus.FAILED
        err: Optional[str] = None
        proc: Optional[subprocess.Popen] = None
        saw_already = False
        saw_completion_message = False
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

                if "has already been downloaded" in line:
                    saw_already = True

                data = parse_ytdlp_line(line)
                if not data:
                    yield LogEvent(item=item, message=line)
                    continue
                
                kind = data.get("event")
                if kind == "progress":
                    if data.get("percent") == 100.0:
                        saw_completion_message = True
                    yield ProgressEvent(
                        item=item,
                        downloaded_bytes=int(data["downloaded"]),
                        total_bytes=int(data["total"]) if data.get("total") else None,
                        speed_bps=float(data["speed_bps"]) if data.get("speed_bps") else None,
                        eta_seconds=int(data["eta_s"]) if data.get("eta_s") else None,
                        unit="bytes",
                    )
                elif kind == "meta":
                    yield MetaEvent(item=item, video_id=data.get("id", "") or "", title=data.get("title", "") or "")
                elif kind == "destination":
                    yield DestinationEvent(item=item, path=Path(data.get("path", "") or ""))
                elif kind == "already":
                    saw_already = True
                    yield AlreadyEvent(item=item)
                else:
                    yield LogEvent(item=item, message=line)

            rc = proc.wait(self.config.timeout_seconds)
            if rc == 0:
                if saw_already:
                    status = DownloadStatus.ALREADY_EXISTS
                elif saw_completion_message:
                    status = DownloadStatus.COMPLETED
                else:
                    status = DownloadStatus.FAILED
                    err = "yt-dlp exited successfully but no completion message was found."
            else:
                err = f"non-zero exit code: {rc}"
        except KeyboardInterrupt:
            err = "interrupted"
            status = DownloadStatus.FAILED
            raise
        except Exception as e:
            err = str(e)
        finally:
            if proc is not None:
                _unregister_proc(proc)

        dur = time.monotonic() - start
        yield FinishEvent(
            item=item,
            result=DownloadResult(item=item, status=status, duration=dur, error_message=err, log_output=logs),
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

        cmd: List[str] = ["aebndl", "-o", str(item.output_dir), "-w", str(self.config.work_dir), "-t", "4"]

        if self.config.scene_from_url:
            sc = parse_aebn_scene_controls(item.url)
            if sc.get("scene_index"):
                cmd += ["-s", sc["scene_index"]]

        if self.config.save_covers:
            cmd.append("-c")
        cmd += self.config.extra_aebn_args
        cmd.append(item.url)

        yield LogEvent(item=item, message=f"SPAWN aebndl: {' '.join(cmd)}")

        status = DownloadStatus.FAILED
        err: Optional[str] = None
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

                ev = data.get("event")
                if ev == "destination":
                    yield DestinationEvent(item=item, path=Path(data["path"]))
                elif ev == "aebn_progress":
                    yield ProgressEvent(
                        item=item,
                        downloaded_bytes=int(data["segments_done"]),
                        total_bytes=int(data["segments_total"]),
                        speed_bps=float(data["rate_itps"]),
                        eta_seconds=int(data["eta_s"]),
                        unit="segments",
                    )
                else:
                    yield LogEvent(item=item, message=line)

            rc = proc.wait(self.config.timeout_seconds)
            if rc == 0:
                status = DownloadStatus.COMPLETED
            else:
                err = f"non-zero exit code: {rc}"
        except KeyboardInterrupt:
            err = "interrupted"
            status = DownloadStatus.FAILED
            raise
        except Exception as e:
            err = str(e)
        finally:
            if proc is not None:
                _unregister_proc(proc)

        dur = time.monotonic() - start
        yield FinishEvent(
            item=item,
            result=DownloadResult(item=item, status=status, duration=dur, error_message=err, log_output=logs),
        )

def get_downloader(url: str, config: DownloaderConfig) -> DownloaderBase:
    return AebnDownloader(config) if is_aebn_url(url) else YtDlpDownloader(config)
