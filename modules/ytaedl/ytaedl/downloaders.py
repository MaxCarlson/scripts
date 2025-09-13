from __future__ import annotations

import hashlib
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


# -------------------- helpers: raw log writer --------------------

class _RawLogger:
    def __init__(self, base_dir: Path, url: str, worker_tag: str):
        self.base_dir = base_dir
        self.base_dir.mkdir(parents=True, exist_ok=True)
        slug = hashlib.sha1(url.encode("utf-8")).hexdigest()[:10]
        self.path = self.base_dir / f"ytdlp-{slug}.log"
        # Line counter and start time for elapsed stamps
        self._seq = 0
        self._t0 = time.monotonic()
        self._fh: Optional[object] = open(self.path, "w", encoding="utf-8", buffering=1)
        self._worker_tag = worker_tag

    def _stamp(self) -> str:
        self._seq += 1
        elapsed = time.monotonic() - self._t0
        # hh:mm:ss.mmm
        h = int(elapsed // 3600)
        m = int((elapsed % 3600) // 60)
        s = int(elapsed % 60)
        ms = int((elapsed - int(elapsed)) * 1000)
        return f"[{self._seq:04d}][{h:02d}:{m:02d}:{s:02d}.{ms:03d}]"

    def write_line(self, kind: str, msg: str) -> None:
        if not self._fh:
            return
        try:
            self._fh.write(f"{self._stamp()} {kind:<6} {msg}\n")
        except Exception:
            # Never fail the download on logging errors.
            pass

    def start(self, url: str) -> None:
        self.write_line("START", f"[W={self._worker_tag}] url={url}")

    def cmd(self, argv: List[str]) -> None:
        safe = " ".join(map(str, argv))
        self.write_line("CMD", safe)

    def out(self, raw_line: str) -> None:
        # Raw stdout line from the tool (strip trailing newline only)
        self.write_line("OUT", raw_line.rstrip("\r\n"))

    def finish(self, rc: int, status: DownloadStatus) -> None:
        self.write_line("FINISH", f"[W={self._worker_tag}] rc={rc} status={status.name}")

    def close(self) -> None:
        try:
            if self._fh:
                self._fh.flush()
                self._fh.close()
        except Exception:
            pass
        self._fh = None


def _detect_raw_log_dir(cfg: DownloaderConfig, item: DownloadItem) -> Path:
    # Prefer optional cfg.raw_log_dir if present (additive; safe if absent).
    raw_dir = getattr(cfg, "raw_log_dir", None)
    if raw_dir:
        return Path(raw_dir)
    # Next, prefer cfg.work_dir if present.
    work_dir = getattr(cfg, "work_dir", None)
    if work_dir:
        return Path(work_dir) / "_raw_logs"
    # Fallback: item’s output dir
    return item.output_dir / "_raw_logs"


def _detect_worker_tag(item: DownloadItem) -> str:
    for attr in ("worker_index", "slot", "worker_id", "index"):
        if hasattr(item, attr):
            val = getattr(item, attr)
            if val is not None:
                return str(val)
    return "?"


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
    Success criteria:
      - rc != 0  -> FAILED
      - rc == 0 and we saw:
          • 'already' -> ALREADY_EXISTS
          • 'destination' OR any 'progress' -> COMPLETED
      - else FAILED with clear message
    """

    def download(self, item: DownloadItem) -> Iterator[DownloadEvent]:
        if abort_requested():
            return

        # Validate URL (core bug fix)
        if not item.url or not item.url.strip():
            raise ValueError("YtDlpDownloader requires a non-empty URL")

        item.output_dir.mkdir(parents=True, exist_ok=True)

        yield StartEvent(item=item)
        start = time.monotonic()
        logs: List[str] = []

        out_tmpl = item.output_dir / "%(title)s.%(ext)s"

        # Build command — include the URL.
        cmd: List[str] = [
            "yt-dlp",
            "--newline",
            "--print",
            "TDMETA\t%(id)s\t%(title)s",
            "-o",
            str(out_tmpl),
            item.url,  # <— URL on the command line
        ]

        # Apply config knobs
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
        cmd += self.config.extra_ytdlp_args
        cmd += item.extra_args

        # Setup raw logger
        raw_dir = _detect_raw_log_dir(self.config, item)
        raw = _RawLogger(raw_dir, item.url, _detect_worker_tag(item))
        raw.start(item.url)
        raw.cmd(cmd)

        status: DownloadStatus = DownloadStatus.FAILED
        err: Optional[str] = None
        saw_progress = False
        saw_destination = False
        saw_already = False

        proc: Optional[subprocess.Popen] = None
        rc: int = -1
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

            for raw_line in iter(proc.stdout.readline, ""):
                if abort_requested():
                    raise KeyboardInterrupt

                # Log the exact raw line to the per-item raw log
                if raw_line:
                    raw.out(raw_line)

                # Normal parsed pipeline
                line = sanitize_line(raw_line)
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
                        downloaded_bytes=int(data.get("downloaded") or 0),
                        total_bytes=int(data.get("total") or 0),
                        speed_bps=float(data.get("speed_bps") or 0.0),
                        eta_seconds=data.get("eta_s"),
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
            raw.finish(rc, status)
            raw.close()

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
            "-o",
            str(item.output_dir),
            "-w",
            str(self.config.work_dir),
            "-t",
            str(self.config.aebn_threads or 4),
        ]

        # Scene-aware controls
        controls = parse_aebn_scene_controls(item.url)
        if controls and controls.is_scene:
            if controls.scene_index is not None:
                cmd += ["-s", str(controls.scene_index)]
            elif getattr(controls, "scene_id", None):
                cmd += ["-S", str(controls.scene_id)]

        cmd += self.config.extra_aebn_args
        cmd += item.extra_args

        if not item.url or not item.url.strip():
            raise ValueError("AebnDownloader requires a non-empty URL")
        cmd.append(item.url)

        # Setup raw logger for parity
        raw_dir = _detect_raw_log_dir(self.config, item)
        raw = _RawLogger(raw_dir, item.url, _detect_worker_tag(item))
        raw.start(item.url)
        raw.cmd(cmd)

        status: DownloadStatus = DownloadStatus.FAILED
        err: Optional[str] = None
        saw_completed = False
        saw_already = False

        proc: Optional[subprocess.Popen] = None
        rc: int = -1
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

            for raw_line in iter(proc.stdout.readline, ""):
                if abort_requested():
                    raise KeyboardInterrupt

                if raw_line:
                    raw.out(raw_line)

                line = sanitize_line(raw_line)
                if not line:
                    continue

                logs.append(line)
                data = parse_aebndl_line(line)

                if not data:
                    yield LogEvent(item=item, message=line)
                    continue

                kind = data.get("event")
                if kind in ("aebn_progress", "progress"):
                    # Normalize aebn fields to ProgressEvent
                    if kind == "aebn_progress":
                        done = int(data.get("segments_done") or 0)
                        total = int(data.get("segments_total") or 0)
                        rate = float(data.get("rate_itps") or 0.0)
                        eta = data.get("eta_s")
                        yield ProgressEvent(
                            item=item,
                            downloaded_bytes=done,
                            total_bytes=total,
                            speed_bps=rate,
                            eta_seconds=eta,
                            unit="segments",
                        )
                    else:
                        yield ProgressEvent(
                            item=item,
                            downloaded_bytes=int(data.get("downloaded") or 0),
                            total_bytes=int(data.get("total") or 0),
                            speed_bps=float(data.get("speed_bps") or 0.0),
                            eta_seconds=data.get("eta_s"),
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
            raw.finish(rc, status)
            raw.close()

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
